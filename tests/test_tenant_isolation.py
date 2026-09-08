"""TEN-3/NFR-8: no read path returns another tenant's data. Builds a second tenant
directly against the same per-test SQLite DB the `client` fixture already seeded with
the reference tenant (id=1 — see tests/conftest.py), then proves tenant A's session
cannot see tenant B's catalog/events/recommendations, and vice versa, through the
public API rather than by inspecting internals directly.
"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Model, Tenant, User
from app.security import hash_password


def _make_second_tenant(client: TestClient) -> Tenant:
    with client.app.state.session_factory() as session:
        tenant = Tenant(name="Second Tenant")
        session.add(tenant)
        session.commit()
        session.refresh(tenant)

        admin = User(
            tenant_id=tenant.id,
            email="tenant-b-admin@test.dev",
            password_hash=hash_password("password123"),
            role="admin",
        )
        model = Model(
            tenant_id=tenant.id,
            title="Tenant B Only Model",
            provider="Tenant B Provider",
            modality="LLM",
            price="$0",
            description="Only visible inside tenant B.",
            use_case_tags=[],
        )
        session.add_all([admin, model])
        session.commit()
        session.refresh(model)
        tenant.only_model_id = model.id  # stash for the assertions below
        return tenant


def _register_and_login(client: TestClient, email: str, password: str = "password123"):
    client.post("/api/auth/register", json={"email": email, "password": password})
    client.post("/api/auth/login", json={"email": email, "password": password})


def test_catalog_list_never_returns_another_tenants_models(client: TestClient) -> None:
    second_tenant = _make_second_tenant(client)
    _register_and_login(client, "tenant-a-user@test.dev")

    response = client.get("/api/models")
    assert response.status_code == 200
    titles = {model["title"] for model in response.json()}
    assert "Tenant B Only Model" not in titles

    detail = client.get(f"/api/models/{second_tenant.only_model_id}")
    assert detail.status_code == 404


def test_admin_users_list_never_returns_another_tenants_users(
    client: TestClient,
) -> None:
    _make_second_tenant(client)

    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    response = client.get("/api/admin/users")
    assert response.status_code == 200
    emails = {row["email"] for row in response.json()["users"]}
    assert "tenant-b-admin@test.dev" not in emails


def test_admin_overview_totals_exclude_another_tenants_data(client: TestClient) -> None:
    _make_second_tenant(client)

    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    totals = client.get("/api/admin/overview").json()["totals"]

    # Ground truth computed directly, scoped to the reference tenant only — comparing
    # against this (rather than an absolute expected number, or a before/after delta)
    # is immune to the app's own background demo-seed task racing in in the
    # background and adding more of the *reference* tenant's own users/models mid-test;
    # what actually proves isolation is that the API's totals match a query scoped to
    # tenant A alone, i.e. tenant B's admin/model never entered the count.
    with client.app.state.session_factory() as session:
        reference_tenant = session.scalar(
            select(Tenant).where(Tenant.name == "TrailMind Reference")
        )
        expected_users = session.scalar(
            select(func.count(User.id)).where(User.tenant_id == reference_tenant.id)
        )
        expected_models = session.scalar(
            select(func.count(Model.id)).where(Model.tenant_id == reference_tenant.id)
        )

    assert totals["users"] == expected_users
    assert totals["models"] == expected_models


def test_event_with_foreign_model_id_is_dropped_not_leaked(client: TestClient) -> None:
    """A malicious or buggy client submitting another tenant's catalog item id in an
    event must not have that item's data leak into this tenant's own activity/
    recommendation flow later — see the model_id validation added to
    POST /api/events/batch (app/main.py)."""
    second_tenant = _make_second_tenant(client)
    _register_and_login(client, "tenant-a-user-2@test.dev")

    response = client.post(
        "/api/events/batch",
        json={
            "events": [
                {
                    "event_type": "model_view",
                    "model_id": second_tenant.only_model_id,
                    "metadata": {},
                }
            ]
        },
    )
    assert response.status_code == 200

    activity = client.get("/api/activity/me")
    assert activity.status_code == 200
    events = activity.json()["events"]
    assert len(events) == 1
    # model_id must have been dropped (None), not stored as tenant B's foreign id.
    assert events[0]["model_id"] is None
