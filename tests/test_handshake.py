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


def test_admin_page_ships_admin_only_markup() -> None:
    # Admins can't self-register (AUTH-5), and this module hits the real app singleton
    # rather than an isolated per-test db, so seed a dedicated admin directly rather than
    # relying on `seed_data.py` having already been run against whatever db this points to.
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

    # A scoped client, not the shared module-level `client` — logging in here must not leak
    # a session cookie into other tests in this file that assume an unauthenticated client.
    with TestClient(app) as admin_client:
        admin_client.post(
            "/api/admin/login", json={"email": email, "password": password}
        )
        response = admin_client.get("/admin/models")

    assert response.status_code == 200
    assert 'id="admin-model-table"' in response.text
    assert 'id="model-form"' in response.text
    assert 'onclick="openModelModal()"' in response.text
    assert 'id="model-modal"' in response.text


def test_screen_routes_and_server_side_access_checks() -> None:
    # Every admin console page requires a session — signed-out visitors are sent to
    # /admin/login, the only page still browsable while signed out (besides /health).
    admin = client.get("/admin", follow_redirects=False)
    assert admin.status_code == 303
    assert admin.headers["location"] == "/admin/login"

    assert client.get("/admin/login").status_code == 200

    for path in ("/admin/models", "/admin/observability", "/admin/users"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"


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
