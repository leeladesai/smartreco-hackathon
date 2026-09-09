"""Tenant resolution, API-key issuance/verification, and onboarding-readiness (TEN-1,
TEN-4, TEN-5, TEN-8). The HTTP layer (`POST /api/tenants`, key rotation/revoke,
`GET /api/admin/onboarding/status`) lives in app/main.py and calls straight through to
the functions here.

Every request that needs a tenant but predates real tenant resolution (the admin
console's own login, which still has no tenant-selection step) resolves to a single
seeded "reference" tenant, keeping the original single-tenant AI-model-catalog app
behaviorally unchanged while the schema underneath is tenant-aware.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Model, Tenant, TenantApiKey

REFERENCE_TENANT_NAME = "TrailMind Reference"

# TEN-5: old key stays valid for this long after rotation, rather than cutting off
# instantly, so an already-deployed tracker snippet (cached HTML/CDN, not something we
# can force-refresh) doesn't start failing before the tenant redeploys with the new key
# (docs/design/09-Platform-Pivot-Decision.md §5).
KEY_ROTATION_GRACE = timedelta(hours=24)


def get_or_create_reference_tenant(session: Session) -> Tenant:
    tenant = session.scalar(select(Tenant).where(Tenant.name == REFERENCE_TENANT_NAME))
    if tenant is None:
        tenant = Tenant(name=REFERENCE_TENANT_NAME, status="active")
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
    return tenant


def hash_api_key(raw_key: str) -> str:
    # A tenant API key is a public, client-embedded credential (it ships in the
    # tracker snippet's page source, like a Stripe publishable key) — hashing it at
    # rest isn't about secrecy the way a password hash is, it's so a leaked/stale copy
    # of the database alone can't be replayed as a working key. A plain, fast SHA-256
    # (not bcrypt) is deliberate: this hash is looked up on every tracker request, and
    # there's no offline brute-force risk to defend against for a value that's already
    # public by design.
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _generate_raw_key() -> str:
    return f"tk_live_{secrets.token_urlsafe(32)}"


def create_tenant(
    session: Session, name: str, allowed_origins: list[str] | None = None
) -> tuple[Tenant, str]:
    """TEN-1. Returns `(tenant, raw_key)` — the raw key is shown/returned exactly
    once; only its hash is ever persisted (see `hash_api_key`)."""
    tenant = Tenant(
        name=name, status="onboarding", allowed_origins=allowed_origins or []
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    raw_key = issue_api_key(session, tenant)
    return tenant, raw_key


def issue_api_key(session: Session, tenant: Tenant) -> str:
    """Mints a new `active` key for `tenant` and returns the raw value (once). Does
    not touch any existing key — see `rotate_api_key` for that."""
    raw_key = _generate_raw_key()
    session.add(
        TenantApiKey(
            tenant_id=tenant.id, key_hash=hash_api_key(raw_key), status="active"
        )
    )
    session.commit()
    return raw_key


def rotate_api_key(session: Session, tenant: Tenant) -> str:
    """TEN-5: issues a new `active` key and flips every currently-`active` key for
    this tenant to `grace` (valid for KEY_ROTATION_GRACE, then effectively expired —
    see `resolve_tenant_by_api_key`). Returns the new raw key."""
    now = datetime.utcnow()
    active_keys = session.scalars(
        select(TenantApiKey).where(
            TenantApiKey.tenant_id == tenant.id, TenantApiKey.status == "active"
        )
    ).all()
    for key in active_keys:
        key.status = "grace"
        key.expires_at = now + KEY_ROTATION_GRACE
    session.commit()
    return issue_api_key(session, tenant)


def revoke_api_key(session: Session, key_id: int) -> None:
    """Immediate revoke (suspected leak) — bypasses the grace period entirely."""
    key = session.get(TenantApiKey, key_id)
    if key is not None:
        key.status = "revoked"
        key.expires_at = datetime.utcnow()
        session.commit()


def onboarding_status(session: Session, tenant: Tenant) -> dict:
    """TEN-8's widget readiness gate: "tracker verified" (a real event has reached
    `POST /api/track/events`) AND "catalog ready" (at least one approved, vector-synced
    catalog item exists to recommend). Flips `tenant.status` from `onboarding` to
    `active` the first time both are true — a future chat-bot widget phase will read
    `status` to decide whether to render at all."""
    tracker_verified = tenant.first_event_at is not None
    catalog_ready = (
        session.scalar(
            select(func.count())
            .select_from(Model)
            .where(
                Model.tenant_id == tenant.id,
                Model.review_status == "approved",
                Model.vector_synced.is_(True),
            )
        )
        > 0
    )
    ready = tracker_verified and catalog_ready
    if ready and tenant.status == "onboarding":
        tenant.status = "active"
        session.commit()
    return {
        "tenant_id": tenant.id,
        "status": tenant.status,
        "tracker_verified": tracker_verified,
        "catalog_ready": catalog_ready,
        "ready": ready,
    }


def resolve_tenant_by_api_key(session: Session, raw_key: str) -> Tenant | None:
    """The tracker SDK's only auth mechanism (TRK-4): a valid, unexpired key
    (`active`, or `grace` and not yet past `expires_at`) resolves to its tenant.
    Anything else — unknown hash, `revoked`, or an expired `grace` key — resolves to
    `None`, which callers must treat as an authentication failure, not "no tenant
    scoping applied"."""
    if not raw_key:
        return None
    key_hash = hash_api_key(raw_key)
    api_key = session.scalar(
        select(TenantApiKey).where(TenantApiKey.key_hash == key_hash)
    )
    if api_key is None or api_key.status == "revoked":
        return None
    if api_key.status == "grace" and (
        api_key.expires_at is None or api_key.expires_at < datetime.utcnow()
    ):
        return None
    return session.get(Tenant, api_key.tenant_id)
