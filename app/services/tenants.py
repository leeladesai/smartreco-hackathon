"""Phase 1 of the multi-tenant pivot (docs/design/09-Platform-Pivot-Decision.md) has no
tenant-resolution mechanism yet — no tracker SDK, no tenant API key, no subdomain
routing (that's later phases: TEN-1/TEN-4). Until then, every request that needs a
tenant (registration, and any public/unauthenticated catalog read) resolves to a
single seeded "reference" tenant, keeping the existing single-tenant AI-model-catalog
app behaviorally unchanged while the schema underneath becomes tenant-aware.
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
