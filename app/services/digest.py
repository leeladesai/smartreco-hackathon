"""DLV-3: scheduled digest, delivered via email or Telegram, driven by a real cron
scheduler (the APScheduler wiring in `app/main.py`'s `create_app`) rather than a manual
trigger.

Delivery is provider-agnostic (`Notifier`): email addresses recipients per-user via
`User.email`, which already exists on the schema. Telegram now also delivers per-user,
via the self-serve `User.telegram_chat_id` (`PUT /api/auth/me/telegram-chat-id`) —
falling back to the single configured broadcast chat (`TELEGRAM_CHAT_ID`) only for a
user who hasn't set their own, and raising (counted as a skipped delivery, not a crash)
if neither exists. If nothing is configured at all, the digest still runs and is logged
instead of silently dropped — same graceful-degradation pattern as
`MeshNarrativeGenerator.enabled`.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Recommendation, User
from app.services.agent_graph import prepare_retrieval_recommendation
from app.services.narrative import narrative_as_plain_text
from app.vector import ModelVectorStore

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, user: User, recommendation: Recommendation) -> None:
        ...


@dataclass
class LoggingNotifier:
    """Fallback when no email/Telegram credentials are configured — still proves the
    scheduled digest ran and what it would have delivered."""

    def send(self, user: User, recommendation: Recommendation) -> None:
        logger.info(
            "[digest:log-only] would notify user_id=%s (%s): %s",
            user.id,
            user.email,
            narrative_as_plain_text(
                recommendation.narrative, recommendation.behavior_summary
            ),
        )


@dataclass
class EmailNotifier:
    smtp_host: str
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    from_email: str

    def send(self, user: User, recommendation: Recommendation) -> None:
        message = EmailMessage()
        message["Subject"] = "Your SmartReco recommendation digest"
        message["From"] = self.from_email
        message["To"] = user.email
        message.set_content(
            narrative_as_plain_text(
                recommendation.narrative,
                f"Based on your recent activity: {recommendation.behavior_summary}",
            )
        )
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)
            server.send_message(message)


@dataclass
class TelegramNotifier:
    bot_token: str
    # Single shared broadcast chat — only used as a fallback for a user who hasn't set
    # their own User.telegram_chat_id (the per-user path this was added to support).
    fallback_chat_id: str | None = None

    def send(self, user: User, recommendation: Recommendation) -> None:
        chat_id = user.telegram_chat_id or self.fallback_chat_id
        if not chat_id:
            raise ValueError(
                f"No Telegram chat_id configured for user_id={user.id} and no "
                "TELEGRAM_CHAT_ID fallback set"
            )
        body = narrative_as_plain_text(
            recommendation.narrative, recommendation.behavior_summary
        )
        text = f"SmartReco digest for {user.email}:\n{body}"
        response = httpx.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        response.raise_for_status()


def build_notifier(settings: Settings) -> Notifier:
    if settings.smtp_host and settings.smtp_from_email:
        return EmailNotifier(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_username=settings.smtp_username,
            smtp_password=settings.smtp_password,
            from_email=settings.smtp_from_email,
        )
    if settings.telegram_bot_token:
        return TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            fallback_chat_id=settings.telegram_chat_id,
        )
    return LoggingNotifier()


def run_digest(
    session_factory: sessionmaker[Session],
    vector_store: ModelVectorStore,
    mesh_generator,
    notifier: Notifier,
) -> dict[str, int]:
    """Runs the agent pipeline for every AI-engineer user (trigger_reason=scheduled_digest,
    subject to the same AGT-6 hash-dedupe/cooldown as an event-triggered run — cheap and
    correct since the digest cadence is far coarser than the 15-minute cooldown), then
    delivers whatever the latest stored recommendation is, new or not, so users with a
    stable recommendation still get their digest."""
    sent = skipped = 0
    with session_factory() as session:
        users = session.scalars(select(User).where(User.role == "user")).all()
        for user in users:
            prepare_retrieval_recommendation(
                session,
                vector_store,
                user.id,
                mesh_generator,
                trigger_reason="scheduled_digest",
            )
            latest = session.scalar(
                select(Recommendation)
                .where(Recommendation.user_id == user.id)
                .order_by(Recommendation.created_at.desc())
            )
            if latest is None:
                skipped += 1
                continue
            try:
                notifier.send(user, latest)
                sent += 1
            except Exception:
                logger.exception("Digest delivery failed for user_id=%s", user.id)
                skipped += 1
    logger.info("Digest run complete: sent=%s skipped=%s", sent, skipped)
    return {"sent": sent, "skipped": skipped}
