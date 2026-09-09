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


class Tenant(Base):
    """A site embedding TrailMind (docs/design/09-Platform-Pivot-Decision.md). The
    hackathon-era AI-model-catalog app runs as a single seeded 'reference' tenant so its
    behavior is unchanged while the schema underneath becomes tenant-aware. `status`
    drives the widget readiness gate (TEN-8) once the widget exists; `allowed_origins`
    and `max_agent_runs_per_hour` are part of the target schema but unused until the
    tracker SDK / rate-limiting phases land."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    allowed_origins: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_agent_runs_per_hour: Mapped[int] = mapped_column(Integer, default=500)
    # Set once, on the first successful tracker-SDK ingestion for this tenant (see
    # POST /api/track/events) — the "tracker verified" half of the TEN-8 widget
    # readiness gate. Null until then.
    first_event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Feed/API catalog ingestion (ING-1) config. `feed_auth_token` is a bearer token
    # for *their* feed endpoint, not a TrailMind credential, so it's stored as-is
    # rather than hashed like a TenantApiKey.
    feed_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    feed_auth_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TenantApiKey(Base):
    """Schema only in this phase — no issuance/rotation/request-auth logic yet
    (TEN-1/TEN-4/TEN-5 land with the tracker SDK phase). `status` supports the
    grace-period rotation design from docs/design/09-Platform-Pivot-Decision.md §5."""

    __tablename__ = "tenant_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
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
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
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
    # Catalog ingestion adapters (M4, docs/design plan): who/what produced this row.
    # "manual" (CAT-1..5, default — unaffected by this phase) never needs review; a
    # "feed"-sourced row is auto-approved like manual entries, while a "scrape"-sourced
    # row starts "pending_review" and is excluded from retrieval/vector-indexing until
    # an admin approves it (see app/services/catalog.py::approve_model). `sync_stale`
    # marks a feed-sourced row as no-longer-confirmed-fresh after a failed re-sync
    # (ING-5: serve last-known-good rather than delete or block on a feed outage).
    ingestion_adapter: Mapped[str] = mapped_column(String(20), default="manual")
    review_status: Mapped[str] = mapped_column(String(20), default="approved")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    # Adapter-specific provenance (ING-6 traceability) that doesn't warrant its own
    # column: the scraped page URL/markup type/CSS selector for a "scrape" row, or the
    # feed URL a "feed" row came from. Empty dict for "manual" rows.
    ingestion_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    # An anonymous, tracker-assigned identity (see app/static/js/tracker.js) — not a
    # User row. The AI-engineer cookie-session `user_id` this replaced was removed
    # along with that login surface (docs/design/09-Platform-Pivot-Decision.md).
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
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
    # DLV-2: set when this recommendation was actually pushed to an open
    # `/api/widget/stream` connection at generation time — null means either no
    # connection was open (the visitor picks it up via GET /api/recommendations/latest
    # on next poll/reconnect) or push was never attempted.
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WidgetSession(Base):
    """DLV-2: one row per open `/api/widget/stream` SSE connection, for audit/
    observability — the actual push routing is an in-process registry
    (`app/main.py`'s `widget_connections`), rebuilt from scratch on every reconnect;
    this table is not consulted to route a push, only to record that one was open."""

    __tablename__ = "widget_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    connection_id: Mapped[str] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
