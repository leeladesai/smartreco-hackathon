from fastapi.testclient import TestClient
from sqlalchemy import select

from app.asgi import app
from app.models import User
from app.security import hash_password


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "smartreco"}


def test_handshake_serves_updated_model_catalog_ui() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SMARTRECO" in response.text
    assert "model catalog" in response.text
    assert "Your activity" in response.text
    assert 'id="catalog-grid"' in response.text
    # Per-screen templates now genuinely isolate what each route ships (see
    # docs/08-Build-Status.md's "Frontend routing migration" section) — the catalog page must
    # not also ship the admin-only model-management markup the way the old single shared
    # base.html did.
    assert 'id="admin-model-table"' not in response.text
    assert 'id="model-form"' not in response.text
    assert 'onclick="openModelModal()"' not in response.text
    assert 'id="model-modal"' not in response.text
    assert "reviewer-jump" not in response.text
    assert "POST /login" not in response.text
    assert "00 — Sign in" not in response.text
    assert "\n+\n<!--" not in response.text


def test_admin_page_ships_admin_only_markup_not_shared_with_other_routes() -> None:
    # Admins can't self-register (AUTH-5), and this module hits the real app singleton
    # rather than an isolated per-test db, so seed a dedicated admin directly rather than
    # relying on `seed_data.py` having already been run against whatever db this points to.
    email, password = "handshake-admin@test.dev", "handshake-admin-pw"
    with app.state.session_factory() as session:
        existing = session.scalar(select(User).where(User.email == email))
        if existing:
            existing.role = "admin"
            existing.password_hash = hash_password(password)
        else:
            session.add(
                User(email=email, password_hash=hash_password(password), role="admin")
            )
        session.commit()

    # A scoped client, not the shared module-level `client` — logging in here must not leak
    # a session cookie into other tests in this file that assume an unauthenticated client.
    with TestClient(app) as admin_client:
        admin_client.post(
            "/api/admin/login", json={"email": email, "password": password}
        )
        response = admin_client.get("/admin")

    assert response.status_code == 200
    assert 'id="admin-model-table"' in response.text
    assert 'id="model-form"' in response.text
    assert 'onclick="openModelModal()"' in response.text
    assert 'id="model-modal"' in response.text
    # And the reverse: admin-only markup must not leak the AI-engineer catalog grid.
    assert 'id="catalog-grid"' not in response.text


def test_screen_routes_and_server_side_access_checks() -> None:
    assert client.get("/catalog").status_code == 200
    assert client.get("/login").status_code == 200

    dashboard = client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/login"

    admin = client.get("/admin", follow_redirects=False)
    assert admin.status_code == 303
    assert admin.headers["location"] == "/admin/login"

    client.post(
        "/api/auth/register",
        json={"email": "route-user@test.dev", "password": "password123"},
    )
    client.post(
        "/api/auth/login",
        json={"email": "route-user@test.dev", "password": "password123"},
    )
    assert client.get("/dashboard").status_code == 200
