"""Tenant governance (TEN-1, TEN-8's approval flow) — creation, platform-admin
approve/reject/suspend/reactivate, and the seeded "reference" tenant every request
that predates real tenant resolution falls back to. `Tenant.status` is
platform-governance only now: `pending_approval` (self-serve signup, awaiting a
platform admin) -> `active` (approved, or trusted immediately if a platform admin
created it directly) -> `suspended`/`rejected`. It no longer tracks
tracker/catalog readiness — that moved to `Widget.status`
(app/services/widgets.py::onboarding_status), since a tenant can run several widgets
independently ready at different times. Tenant API keys were retired the same way —
see `Widget`'s docstring in app/models.py.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant

REFERENCE_TENANT_NAME = "TrailMind Reference"


def get_or_create_reference_tenant(session: Session) -> Tenant:
    tenant = session.scalar(select(Tenant).where(Tenant.name == REFERENCE_TENANT_NAME))
    if tenant is None:
        tenant = Tenant(name=REFERENCE_TENANT_NAME, status="active")
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
    return tenant


def create_tenant(session: Session, name: str, status: str = "active") -> Tenant:
    """TEN-1. `status` defaults to `active` for a platform-admin-created tenant
    (trusted immediately, no approval step); self-serve signup passes
    `pending_approval` instead — see `approve_tenant`/`reject_tenant`. Doesn't touch
    widgets or keys at all anymore — a tenant is just a governance shell now; its
    first business-admin user creates their own widget(s) afterward."""
    tenant = Tenant(name=name, status=status)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def approve_tenant(session: Session, tenant: Tenant) -> None:
    """Unlocks login for a self-serve signup — moves it straight to `active` (no
    intermediate "onboarding" tenant state anymore; readiness now lives per-widget).
    No-op if the tenant isn't actually pending."""
    if tenant.status != "pending_approval":
        return
    tenant.status = "active"
    session.commit()


def reject_tenant(session: Session, tenant: Tenant) -> None:
    """Permanently blocks login for a self-serve signup that shouldn't be approved.
    Kept as a distinct status (not a delete) so the request stays visible/auditable
    rather than silently disappearing."""
    if tenant.status != "pending_approval":
        return
    tenant.status = "rejected"
    session.commit()


def suspend_tenant(session: Session, tenant: Tenant) -> None:
    """Manual platform-admin override — every widget under this tenant goes dark
    immediately regardless of its own individual status (see
    app/main.py::_resolve_widget's TEN-8 gate, which checks both the widget's own
    status and its tenant's)."""
    tenant.status = "suspended"
    session.commit()


def reactivate_tenant(session: Session, tenant: Tenant) -> None:
    """Manual counterpart to `suspend_tenant`."""
    tenant.status = "active"
    session.commit()
