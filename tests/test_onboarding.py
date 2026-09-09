"""M2 (tenant onboarding & auth generalization): HTTP tenant creation gated behind a
new `platform_admin` role (TEN-1), and the per-widget key cutover — key rotation/
revoke and the onboarding-readiness gate (TEN-8, tracker verified + catalog ready)
now live at the Widget level, not the Tenant (see Widget's docstring in
app/models.py). The underlying service functions (app/services/tenants.py,
app/services/widgets.py) already have unit coverage in tests/test_tracker.py; this
file covers the HTTP layer and the role split on top.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models import CatalogItem, Tenant, User, Widget, WidgetApiKey


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
    response = client.post("/api/tenants", json={"name": "Acme Bank"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert "api_key" not in body


def test_tenant_admin_cannot_create_a_tenant(client: TestClient) -> None:
    _login_tenant_admin(client)
    response = client.post("/api/tenants", json={"name": "Acme Bank"})
    assert response.status_code == 403


def test_anonymous_cannot_create_a_tenant(client: TestClient) -> None:
    response = client.post("/api/tenants", json={"name": "Acme Bank"})
    assert response.status_code == 401


def test_tenant_admin_can_create_and_rotate_its_own_widget_key(
    client: TestClient,
) -> None:
    _login_tenant_admin(client)
    created = client.post(
        "/api/admin/widgets", json={"name": "Credit Cards", "allowed_origins": []}
    ).json()
    assert created["api_key"].startswith("wk_live_")
    widget_id = created["widget"]["id"]

    response = client.post(f"/api/admin/widgets/{widget_id}/rotate-key")
    assert response.status_code == 200
    assert response.json()["api_key"].startswith("wk_live_")


def test_tenant_admin_cannot_rotate_another_tenants_widget_key(
    client: TestClient,
) -> None:
    _login_platform_admin(client)
    other_tenant = client.post("/api/tenants", json={"name": "Other Tenant"}).json()
    with client.app.state.session_factory() as session:
        from app.services.widgets import create_widget

        tenant = session.get(Tenant, other_tenant["id"])
        other_widget, _ = create_widget(session, tenant, "Other Widget")
        other_widget_id = other_widget.id

    _login_tenant_admin(client)
    response = client.post(f"/api/admin/widgets/{other_widget_id}/rotate-key")
    assert response.status_code == 404


def test_tenant_admin_can_revoke_its_own_widget_key(client: TestClient) -> None:
    _login_tenant_admin(client)
    created = client.post(
        "/api/admin/widgets", json={"name": "Credit Cards", "allowed_origins": []}
    ).json()
    widget_id = created["widget"]["id"]

    with client.app.state.session_factory() as session:
        key = (
            session.query(WidgetApiKey)
            .filter_by(widget_id=widget_id, status="active")
            .one()
        )
        key_id = key.id

    response = client.post(f"/api/admin/widgets/{widget_id}/revoke-key/{key_id}")
    assert response.status_code == 204
    with client.app.state.session_factory() as session:
        assert session.get(WidgetApiKey, key_id).status == "revoked"


def test_tenant_admin_cannot_revoke_another_tenants_widget_key(
    client: TestClient,
) -> None:
    _login_platform_admin(client)
    other_tenant = client.post("/api/tenants", json={"name": "Other Tenant"}).json()
    with client.app.state.session_factory() as session:
        from app.services.widgets import create_widget

        tenant = session.get(Tenant, other_tenant["id"])
        other_widget, _ = create_widget(session, tenant, "Other Widget")
        other_key = (
            session.query(WidgetApiKey).filter_by(widget_id=other_widget.id).one()
        )
        other_key_id = other_key.id

    _login_tenant_admin(client)
    created = client.post(
        "/api/admin/widgets", json={"name": "My Widget", "allowed_origins": []}
    ).json()
    my_widget_id = created["widget"]["id"]

    response = client.post(
        f"/api/admin/widgets/{my_widget_id}/revoke-key/{other_key_id}"
    )
    assert response.status_code == 404
    with client.app.state.session_factory() as session:
        assert session.get(WidgetApiKey, other_key_id).status == "active"


def test_onboarding_status_not_ready_with_no_activity(client: TestClient) -> None:
    _login_tenant_admin(client)
    created = client.post(
        "/api/admin/widgets", json={"name": "Credit Cards", "allowed_origins": []}
    ).json()
    widget_id = created["widget"]["id"]
    response = client.get(f"/api/admin/widgets/{widget_id}/onboarding/status")
    assert response.status_code == 200
    body = response.json()
    assert body["tracker_verified"] is False
    assert body["catalog_ready"] is False
    assert body["ready"] is False


def test_onboarding_status_flips_widget_to_active_once_ready(
    client: TestClient,
) -> None:
    _login_tenant_admin(client)
    created = client.post(
        "/api/admin/widgets", json={"name": "Credit Cards", "allowed_origins": []}
    ).json()
    widget_id = created["widget"]["id"]

    with client.app.state.session_factory() as session:
        widget = session.get(Widget, widget_id)
        widget.first_event_at = datetime.now(timezone.utc)
        item = CatalogItem(
            tenant_id=widget.tenant_id,
            widget_id=widget_id,
            title="Ready Item",
            provider="P",
            category="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
            review_status="approved",
            vector_synced=True,
        )
        session.add(item)
        session.commit()

    response = client.get(f"/api/admin/widgets/{widget_id}/onboarding/status")
    assert response.status_code == 200
    body = response.json()
    assert body["tracker_verified"] is True
    assert body["catalog_ready"] is True
    assert body["ready"] is True
    assert body["status"] == "active"


def test_onboarding_status_isolated_per_widget(client: TestClient) -> None:
    _login_tenant_admin(client)
    widget_a = client.post(
        "/api/admin/widgets", json={"name": "Widget A", "allowed_origins": []}
    ).json()["widget"]
    widget_b = client.post(
        "/api/admin/widgets", json={"name": "Widget B", "allowed_origins": []}
    ).json()["widget"]

    with client.app.state.session_factory() as session:
        widget_a_row = session.get(Widget, widget_a["id"])
        widget_a_row.first_event_at = datetime.now(timezone.utc)
        session.add(
            CatalogItem(
                tenant_id=widget_a_row.tenant_id,
                widget_id=widget_a["id"],
                title="Widget A Only Item",
                provider="P",
                category="LLM",
                price="$0",
                description="d",
                use_case_tags=[],
                review_status="approved",
                vector_synced=True,
            )
        )
        session.commit()

    response = client.get(f"/api/admin/widgets/{widget_b['id']}/onboarding/status")
    body = response.json()
    assert body["tracker_verified"] is False
    assert body["catalog_ready"] is False


# ---- tenant management console (platform_admin) ----


def test_platform_admin_can_list_tenants(client: TestClient) -> None:
    _login_platform_admin(client)
    client.post("/api/tenants", json={"name": "Acme Bank"})
    response = client.get("/api/tenants")
    assert response.status_code == 200
    body = response.json()
    names = {row["name"] for row in body["tenants"]}
    assert "Acme Bank" in names
    assert "has_more" in body


def test_tenant_admin_cannot_list_tenants(client: TestClient) -> None:
    _login_tenant_admin(client)
    response = client.get("/api/tenants")
    assert response.status_code == 403


def test_platform_admin_can_view_tenant_detail_with_widgets(
    client: TestClient,
) -> None:
    _login_platform_admin(client)
    created = client.post("/api/tenants", json={"name": "Acme Bank"}).json()
    with client.app.state.session_factory() as session:
        from app.services.widgets import create_widget

        tenant = session.get(Tenant, created["id"])
        create_widget(session, tenant, "Credit Cards")

    response = client.get(f"/api/tenants/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Acme Bank"
    assert len(body["widgets"]) == 1
    assert body["widgets"][0]["name"] == "Credit Cards"


def test_tenant_detail_404s_for_unknown_tenant(client: TestClient) -> None:
    _login_platform_admin(client)
    response = client.get("/api/tenants/999")
    assert response.status_code == 404


def test_platform_admin_can_suspend_and_reactivate_a_tenant(
    client: TestClient,
) -> None:
    _login_platform_admin(client)
    created = client.post("/api/tenants", json={"name": "Acme Bank"}).json()

    suspend = client.post(f"/api/tenants/{created['id']}/suspend")
    assert suspend.status_code == 204
    detail = client.get(f"/api/tenants/{created['id']}").json()
    assert detail["status"] == "suspended"

    reactivate = client.post(f"/api/tenants/{created['id']}/reactivate")
    assert reactivate.status_code == 204
    detail = client.get(f"/api/tenants/{created['id']}").json()
    assert detail["status"] == "active"


def test_tenant_admin_cannot_suspend_a_tenant(client: TestClient) -> None:
    _login_tenant_admin(client)
    with client.app.state.session_factory() as session:
        curator = session.query(User).filter(User.email == "curator@test.dev").one()
        tenant_id = curator.tenant_id
    response = client.post(f"/api/tenants/{tenant_id}/suspend")
    assert response.status_code == 403


# ---- self-serve signup, approval, bearer-token login ----


def test_signup_creates_a_pending_tenant(client: TestClient) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "company_name": "ICICI Bank",
            "email": "priya.sharma@icici.com",
            "password": "password123",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"

    with client.app.state.session_factory() as session:
        tenant = session.get(Tenant, body["tenant_id"])
        assert tenant.status == "pending_approval"
        assert tenant.name == "ICICI Bank"


def test_signup_rejects_a_duplicate_email(client: TestClient) -> None:
    client.post(
        "/api/auth/signup",
        json={
            "company_name": "ICICI Bank",
            "email": "priya.sharma@icici.com",
            "password": "password123",
        },
    )
    response = client.post(
        "/api/auth/signup",
        json={
            "company_name": "Other Bank",
            "email": "priya.sharma@icici.com",
            "password": "password123",
        },
    )
    assert response.status_code == 409


def test_login_is_blocked_while_tenant_is_pending_approval(
    client: TestClient,
) -> None:
    client.post(
        "/api/auth/signup",
        json={
            "company_name": "ICICI Bank",
            "email": "priya.sharma@icici.com",
            "password": "password123",
        },
    )
    response = client.post(
        "/api/admin/login",
        json={"email": "priya.sharma@icici.com", "password": "password123"},
    )
    assert response.status_code == 403
    assert "awaiting approval" in response.json()["detail"]


def test_login_succeeds_and_returns_a_bearer_token_after_approval(
    client: TestClient,
) -> None:
    signup = client.post(
        "/api/auth/signup",
        json={
            "company_name": "ICICI Bank",
            "email": "priya.sharma@icici.com",
            "password": "password123",
        },
    ).json()

    _login_platform_admin(client)
    approve = client.post(f"/api/tenants/{signup['tenant_id']}/approve")
    assert approve.status_code == 204

    login = client.post(
        "/api/admin/login",
        json={"email": "priya.sharma@icici.com", "password": "password123"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    assert token

    # Clear the session cookie the login response also set, then prove auth still
    # works purely off the bearer token — the way the React admin frontend uses it.
    client.cookies.clear()
    me = client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "priya.sharma@icici.com"


def test_login_is_blocked_after_rejection(client: TestClient) -> None:
    signup = client.post(
        "/api/auth/signup",
        json={
            "company_name": "ICICI Bank",
            "email": "priya.sharma@icici.com",
            "password": "password123",
        },
    ).json()

    _login_platform_admin(client)
    reject = client.post(f"/api/tenants/{signup['tenant_id']}/reject")
    assert reject.status_code == 204

    login = client.post(
        "/api/admin/login",
        json={"email": "priya.sharma@icici.com", "password": "password123"},
    )
    assert login.status_code == 403
    assert "not approved" in login.json()["detail"]
