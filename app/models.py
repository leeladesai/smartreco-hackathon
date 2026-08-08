from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")
    # Per-user Telegram digest delivery (DLV-3 bonus follow-up): set via
    # PUT /api/auth/me/telegram-chat-id, self-serve. Optional — TelegramNotifier
    # (app/services/digest.py) falls back to the single configured broadcast chat
    # (TELEGRAM_CHAT_ID) for any user who hasn't set their own.
    telegram_chat_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    story: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(120))
    modality: Mapped[str] = mapped_column(String(40))
    price: Mapped[str] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_window: Mapped[str | None] = mapped_column(String(120), nullable=True)
    use_case_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vector_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    retrieval_meta: Mapped[list[dict]] = mapped_column(JSON, default=list)
    behavior_summary: Mapped[str] = mapped_column(Text, default="")
    activity_hash: Mapped[str] = mapped_column(String(64), index=True)
    trigger_reason: Mapped[str] = mapped_column(String(120))
    # Cost/latency rollup (bonus, retrieval/efficiency polish): captured directly from
    # the Mesh response at generation time (app/services/mesh.py), not re-derived from
    # LangSmith — the admin cost dashboard aggregates these straight out of our own DB.
    # Null whenever generation was skipped (no Mesh configured, or retrieval-only).
    mesh_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    mesh_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mesh_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mesh_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DemoModeSetting(Base):
    """Single-row table (id is always 1) — a global, admin-controlled switch that shows a
    live event-tracking overlay in the model drawer/detail page for every AI-engineer
    session. Off by default; meant to be flipped on only while demoing the pipeline live
    (e.g. to hackathon judges), not left on for normal use."""

    __tablename__ = "demo_mode_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
