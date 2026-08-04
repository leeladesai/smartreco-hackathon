from fastapi.testclient import TestClient

from app.main import app


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
    assert 'id="admin-model-table"' in response.text
    assert 'id="model-form"' in response.text
    assert 'onclick="openModelModal()"' in response.text
    assert 'id="model-modal"' in response.text
    assert "reviewer-jump" not in response.text
    assert "POST /login" not in response.text
    assert "00 — Sign in" not in response.text
    assert "\n+\n<!--" not in response.text


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
