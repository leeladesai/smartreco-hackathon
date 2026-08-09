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
from app.models import Model, Recommendation, User
from app.services.agent_graph import prepare_retrieval_recommendation
from app.services.email_template import render_recommendation_email_html
from app.services.narrative import decode_narrative, narrative_as_plain_text
from app.vector import ModelVectorStore

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(
        self, user: User, recommendation: Recommendation, models: list[dict]
    ) -> None:
        ...


@dataclass
class LoggingNotifier:
    """Fallback when no email/Telegram credentials are configured — still proves the
    scheduled digest ran and what it would have delivered."""

    def send(
        self, user: User, recommendation: Recommendation, models: list[dict]
    ) -> None:
        logger.info(
            "[digest:log-only] would notify user_id=%s (%s) about %s: %s",
            user.id,
            user.email,
            [model["title"] for model in models],
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
    # Optional "View full dashboard" link in the HTML email — omitted when unset (no
    # deployed URL yet) rather than pointing at a link nobody outside localhost can use.
    app_url: str | None = None

    def send(
        self, user: User, recommendation: Recommendation, models: list[dict]
    ) -> None:
        message = EmailMessage()
        subject = "Your TrailMind recommendation digest"
        if models:
            subject = (
                f"Your TrailMind picks: {len(models)} models based on your activity"
            )
        message["Subject"] = subject
        message["From"] = self.from_email
        message["To"] = user.email
        fallback_summary = (
            f"Based on your recent activity: {recommendation.behavior_summary}"
        )
        message.set_content(
            narrative_as_plain_text(recommendation.narrative, fallback_summary)
        )
        message.add_alternative(
            render_recommendation_email_html(
                decode_narrative(recommendation.narrative),
                models,
                fallback_summary,
                app_url=self.app_url,
            ),
            subtype="html",
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

    def send(
        self, user: User, recommendation: Recommendation, models: list[dict]
    ) -> None:
        chat_id = user.telegram_chat_id or self.fallback_chat_id
        if not chat_id:
            raise ValueError(
                f"No Telegram chat_id configured for user_id={user.id} and no "
                "TELEGRAM_CHAT_ID fallback set"
            )
        body = narrative_as_plain_text(
            recommendation.narrative, recommendation.behavior_summary
        )
        text = f"TrailMind digest for {user.email}:\n{body}"
        if models:
            titles = ", ".join(model["title"] for model in models)
            text += f"\n\nRecommended: {titles}"
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
            app_url=settings.app_base_url,
        )
    if settings.telegram_bot_token:
        return TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            fallback_chat_id=settings.telegram_chat_id,
        )
    return LoggingNotifier()


def _recommendation_models(
    session: Session, recommendation: Recommendation
) -> list[dict]:
    """Resolves the plain-dict shape both notifiers render from — title/provider/
    modality/price plus the same deterministic `why_this` reason the dashboard shows
    (`Recommendation.retrieval_meta`, computed in agent_graph.py, never re-derived
    here)."""
    if not recommendation.model_ids:
        return []
    models_by_id = {
        model.id: model
        for model in session.scalars(
            select(Model).where(Model.id.in_(recommendation.model_ids))
        ).all()
    }
    reason_by_id = {
        entry["model_id"]: entry.get("reason")
        for entry in recommendation.retrieval_meta or []
    }
    return [
        {
            "title": models_by_id[model_id].title,
            "provider": models_by_id[model_id].provider,
            "modality": models_by_id[model_id].modality,
            "price": models_by_id[model_id].price,
            "why_this": reason_by_id.get(model_id),
        }
        for model_id in recommendation.model_ids
        if model_id in models_by_id
    ]


def run_digest(
    session_factory: sessionmaker[Session],
    vector_store: ModelVectorStore,
    mesh_generator,
    notifier: Notifier,
) -> dict[str, int]:
    """Runs the agent pipeline for every AI-engineer user
    (trigger_reason=scheduled_digest, subject to the same AGT-6 hash-dedupe/cooldown as
    an event-triggered run — cheap and correct since the digest cadence is far coarser
    than the 15-minute cooldown), then
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
                notifier.send(user, latest, _recommendation_models(session, latest))
                sent += 1
            except Exception:
                logger.exception("Digest delivery failed for user_id=%s", user.id)
                skipped += 1
    logger.info("Digest run complete: sent=%s skipped=%s", sent, skipped)
    return {"sent": sent, "skipped": skipped}
