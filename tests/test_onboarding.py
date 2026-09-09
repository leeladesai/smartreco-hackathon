"""M2 (tenant onboarding & auth generalization): HTTP tenant creation gated behind a
new `platform_admin` role (TEN-1), key rotation/revoke over HTTP (TEN-5), and the
onboarding-readiness gate (TEN-8) that flips a tenant from `onboarding` to `active`
once its tracker is verified and its catalog has at least one approved item — the
underlying service functions (app/services/tenants.py) already had unit coverage in
tests/test_tracker.py; this file covers the HTTP layer and the role split on top.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models import Model, Tenant, TenantApiKey, User
from app.security import hash_password


def _login_platform_admin(client: TestClient) -> None:
    response = client.post(
        "/api/admin/login",
        json={"email": "platform-admin@test.dev", "password": "password123"},
    )
    assert response.status_code == 200


def _login_tenant_admin(client: TestClient) -> None:
    response = client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    assert response.status_code == 200


def test_platform_admin_can_create_a_tenant(client: TestClient) -> None:
    _login_platform_admin(client)
    response = client.post(
        "/api/tenants", json={"name": "Acme Bank", "allowed_origins": ["acme.com"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "onboarding"
    assert body["api_key"].startswith("tk_live_")


def test_tenant_admin_cannot_create_a_tenant(client: TestClient) -> None:
    _login_tenant_admin(client)
    response = client.post("/api/tenants", json={"name": "Acme Bank"})
    assert response.status_code == 403


def test_anonymous_cannot_create_a_tenant(client: TestClient) -> None:
    response = client.post("/api/tenants", json={"name": "Acme Bank"})
    assert response.status_code == 401


def test_tenant_admin_can_rotate_its_own_key(client: TestClient) -> None:
    _login_tenant_admin(client)
    response = client.post("/api/tenants/1/rotate-key")
    assert response.status_code == 200
    assert response.json()["api_key"].startswith("tk_live_")


def test_tenant_admin_cannot_rotate_another_tenants_key(client: TestClient) -> None:
    _login_platform_admin(client)
    other = client.post("/api/tenants", json={"name": "Other Tenant"}).json()

    _login_tenant_admin(client)
    response = client.post(f"/api/tenants/{other['id']}/rotate-key")
    assert response.status_code == 404


def test_tenant_admin_can_revoke_its_own_key(client: TestClient) -> None:
    # The reference tenant seeded by the `client` fixture has no key of its own
    # (get_or_create_reference_tenant predates TEN-1 key issuance) — rotate first to
    # get a real key to revoke.
    _login_tenant_admin(client)
    client.post("/api/tenants/1/rotate-key")
    with client.app.state.session_factory() as session:
        key = session.query(TenantApiKey).filter_by(tenant_id=1, status="active").one()
        key_id = key.id

    response = client.post(f"/api/tenants/1/revoke-key/{key_id}")
    assert response.status_code == 204
    with client.app.state.session_factory() as session:
        assert session.get(TenantApiKey, key_id).status == "revoked"


def test_tenant_admin_cannot_revoke_another_tenants_key(client: TestClient) -> None:
    _login_platform_admin(client)
    other = client.post("/api/tenants", json={"name": "Other Tenant"}).json()
    with client.app.state.session_factory() as session:
        other_key = session.query(TenantApiKey).filter_by(tenant_id=other["id"]).one()
        other_key_id = other_key.id

    _login_tenant_admin(client)
    response = client.post(f"/api/tenants/1/revoke-key/{other_key_id}")
    assert response.status_code == 404
    with client.app.state.session_factory() as session:
        assert session.get(TenantApiKey, other_key_id).status == "active"


def test_onboarding_status_not_ready_with_no_activity(client: TestClient) -> None:
    _login_tenant_admin(client)
    response = client.get("/api/admin/onboarding/status")
    assert response.status_code == 200
    body = response.json()
    assert body["tracker_verified"] is False
    assert body["catalog_ready"] is False
    assert body["ready"] is False


def test_onboarding_status_flips_tenant_to_active_once_ready(
    client: TestClient,
) -> None:
    _login_tenant_admin(client)
    with client.app.state.session_factory() as session:
        tenant = session.get(Tenant, 1)
        tenant.status = "onboarding"
        tenant.first_event_at = datetime.now(timezone.utc)
        model = Model(
            tenant_id=1,
            title="Ready Model",
            provider="P",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
            review_status="approved",
            vector_synced=True,
        )
        session.add(model)
        session.commit()

    response = client.get("/api/admin/onboarding/status")
    assert response.status_code == 200
    body = response.json()
    assert body["tracker_verified"] is True
    assert body["catalog_ready"] is True
    assert body["ready"] is True
    assert body["status"] == "active"


def test_onboarding_status_isolated_per_tenant(client: TestClient) -> None:
    _login_platform_admin(client)
    other = client.post("/api/tenants", json={"name": "Other Tenant"}).json()

    with client.app.state.session_factory() as session:
        session.add(
            User(
                tenant_id=other["id"],
                email="other-admin@test.dev",
                password_hash=hash_password("password123"),
                role="admin",
            )
        )
        session.commit()

        reference_tenant = session.get(Tenant, 1)
        reference_tenant.first_event_at = datetime.now(timezone.utc)
        session.add(
            Model(
                tenant_id=1,
                title="Reference Only Model",
                provider="P",
                modality="LLM",
                price="$0",
                description="d",
                use_case_tags=[],
                review_status="approved",
                vector_synced=True,
            )
        )
        session.commit()

    login = client.post(
        "/api/admin/login",
        json={"email": "other-admin@test.dev", "password": "password123"},
    )
    assert login.status_code == 200
    response = client.get("/api/admin/onboarding/status")
    body = response.json()
    assert body["tracker_verified"] is False
    assert body["catalog_ready"] is False
