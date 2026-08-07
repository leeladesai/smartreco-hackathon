"""DLV-3: scheduled digest, delivered via email or Telegram, driven by a real cron
scheduler (see `app/services/scheduler.py`) rather than a manual trigger.

Delivery is provider-agnostic (`Notifier`): email addresses recipients per-user via
`User.email`, which already exists on the schema. Telegram has no per-user chat-id mapping
in this MVP, so it broadcasts to a single configured chat. If neither is configured, the
digest still runs and is logged instead of silently dropped — same graceful-degradation
pattern as `MeshNarrativeGenerator.enabled`.
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
from app.vector import ModelVectorStore

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, user: User, recommendation: Recommendation) -> None: ...


@dataclass
class LoggingNotifier:
    """Fallback when no email/Telegram credentials are configured — still proves the
    scheduled digest ran and what it would have delivered."""

    def send(self, user: User, recommendation: Recommendation) -> None:
        logger.info(
            "[digest:log-only] would notify user_id=%s (%s): %s",
            user.id,
            user.email,
            recommendation.narrative or recommendation.behavior_summary,
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
            recommendation.narrative
            or f"Based on your recent activity: {recommendation.behavior_summary}"
        )
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)
            server.send_message(message)


@dataclass
class TelegramNotifier:
    bot_token: str
    chat_id: str

    def send(self, user: User, recommendation: Recommendation) -> None:
        text = (
            f"SmartReco digest for {user.email}:\n"
            f"{recommendation.narrative or recommendation.behavior_summary}"
        )
        response = httpx.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text},
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
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(
            bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id
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
