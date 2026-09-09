from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.asgi import app
from app.models import User
from app.security import hash_password
from app.services.tenants import get_or_create_reference_tenant


client = TestClient(app)

# This module hits the real app.asgi singleton (real .env DATABASE_URL), not an
# isolated per-test db — see app/asgi.py and tests/conftest.py for why. Every email
# these tests create/log in as must be listed here so the autouse fixture can delete
# the rows afterward; otherwise they pile up in the real database forever, one set
# per pytest run.
_HANDSHAKE_TEST_EMAILS = ("handshake-admin@test.dev",)


@pytest.fixture(autouse=True, scope="module")
def _cleanup_handshake_users() -> Iterator[None]:
    yield
    with app.state.session_factory() as session:
        session.execute(
            User.__table__.delete().where(User.email.in_(_HANDSHAKE_TEST_EMAILS))
        )
        session.commit()


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "trailmind"}


def test_admin_login_returns_a_bearer_token_not_html() -> None:
    # The admin console is the separate React app (frontend/) now — this backend is
    # a pure JSON API and no longer serves any admin HTML of its own. Admins can't
    # self-register (AUTH-5), and this module hits the real app singleton rather than
    # an isolated per-test db, so seed a dedicated admin directly rather than relying
    # on `seed_data.py` having already been run against whatever db this points to.
    email, password = "handshake-admin@test.dev", "handshake-admin-pw"
    with app.state.session_factory() as session:
        tenant = get_or_create_reference_tenant(session)
        existing = session.scalar(select(User).where(User.email == email))
        if existing:
            existing.role = "admin"
            existing.tenant_id = tenant.id
            existing.password_hash = hash_password(password)
        else:
            session.add(
                User(
                    tenant_id=tenant.id,
                    email=email,
                    password_hash=hash_password(password),
                    role="admin",
                )
            )
        session.commit()

    with TestClient(app) as admin_client:
        login = admin_client.post(
            "/api/admin/login", json={"email": email, "password": password}
        )
        assert login.status_code == 200
        assert login.json()["token"]

        response = admin_client.get(
            "/api/admin/me",
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        )
    assert response.status_code == 200
    assert response.json()["email"] == email


def test_admin_html_routes_are_gone() -> None:
    # These used to be server-rendered Jinja2 pages — the backend no longer serves
    # any HTML at all, admin or otherwise, now that the console is a separate app.
    for path in (
        "/admin",
        "/admin/login",
        "/admin/models",
        "/admin/observability",
        "/admin/users",
        "/admin/tenants",
    ):
        assert client.get(path, follow_redirects=False).status_code == 404


def test_removed_ai_engineer_routes_are_gone() -> None:
    # The AI-engineer self-service catalog/dashboard/activity/login surface was
    # removed as part of the platform pivot (docs/design/09-Platform-Pivot-Decision.md)
    # — these must not still resolve to a page or an API response.
    for path in (
        "/",
        "/login",
        "/catalog",
        "/models/1",
        "/compare",
        "/dashboard",
        "/activity",
    ):
        assert client.get(path, follow_redirects=False).status_code == 404
    for path in ("/api/auth/register", "/api/auth/login"):
        assert client.post(path, json={}).status_code == 404
    for path in ("/api/auth/me", "/api/recommendations/me", "/api/activity/me"):
        assert client.get(path).status_code == 404
