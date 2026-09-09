"""TEN-3/NFR-8: no read path returns another tenant's data. Builds a second tenant
directly against the same per-test SQLite DB the `client` fixture already seeded with
the reference tenant (id=1 — see tests/conftest.py), then proves tenant A's session
cannot see tenant B's catalog/events/recommendations, and vice versa, through the
public API rather than by inspecting internals directly.

The event-ingestion cross-tenant model_id guard (dropping a foreign-tenant model_id
rather than storing it) is covered in tests/test_tracker.py against the tracker SDK's
own POST /api/track/events, which replaced the old cookie-session
POST /api/events/batch. This file's own tracker-key test below covers a different
angle: tenant A's key must never surface tenant B's stored data.
"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Model, Tenant, User
from app.security import hash_password
from app.services.tenants import create_tenant


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


def test_catalog_list_never_returns_another_tenants_models(client: TestClient) -> None:
    second_tenant = _make_second_tenant(client)
    # GET /api/models is admin-only in this build (no tenant API key / public catalog
    # surface exists yet — that returns with the tracker SDK phase), so tenant A's own
    # admin is what proves the isolation here.
    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )

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


def test_tracker_key_never_surfaces_another_tenants_recommendation(
    client: TestClient,
) -> None:
    """A visitor_id is just a client-chosen string, not scoped to any tenant on its
    own — two tenants' visitors could easily collide on the same id (e.g. both using
    "v-1" from a fresh browser). Isolation must come entirely from the tenant key,
    not from visitor_id happening to be unique."""
    with client.app.state.session_factory() as session:
        tenant_a, key_a = create_tenant(session, "Tenant A")
        tenant_b, key_b = create_tenant(session, "Tenant B")
        model_b = Model(
            tenant_id=tenant_b.id,
            title="Tenant B Secret Model",
            provider="P",
            modality="LLM",
            price="$0",
            description="Only for tenant B.",
            use_case_tags=[],
        )
        session.add(model_b)
        session.commit()
        model_b_id = model_b.id

    same_visitor_id = "v-shared"
    client.post(
        "/api/track/events",
        json={
            "tenant_key": key_b,
            "visitor_id": same_visitor_id,
            "events": [
                {"event_type": "model_view", "model_id": model_b_id, "metadata": {}}
            ],
        },
    )

    # Tenant A, querying with the same visitor_id string, must see nothing of
    # tenant B's — the tenant key is what scopes this, not the visitor_id value.
    response = client.get(
        f"/api/recommendations/latest?tenant_key={key_a}&visitor_id={same_visitor_id}"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["evidence"] == []
