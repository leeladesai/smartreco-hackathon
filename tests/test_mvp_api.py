from fastapi.testclient import TestClient


def test_register_login_and_batch_events(client: TestClient) -> None:
    register = client.post(
        "/api/auth/register",
        json={"email": "engineer@test.dev", "password": "password123"},
    )
    assert register.status_code == 201
    assert register.json()["role"] == "user"

    login = client.post(
        "/api/auth/login",
        json={"email": "engineer@test.dev", "password": "password123"},
    )
    assert login.status_code == 200

    events = client.post(
        "/api/events/batch",
        json={
            "events": [
                {"event_type": "search", "metadata": {"query": "low latency voice"}}
            ]
        },
    )
    assert events.status_code == 200
    assert events.json() == {"accepted": 1, "recommendation_triggered": False}


def test_admin_can_create_model_and_dual_write(client: TestClient) -> None:
    login = client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    assert login.status_code == 200

    create = client.post(
        "/api/admin/models",
        json={
            "title": "Test Voice",
            "description": "A low latency voice model for agents.",
            "provider": "Test Labs",
            "modality": "Voice",
            "price": "$0.001/char",
            "latency_ms": 120,
            "use_case_tags": ["real-time voice"],
        },
    )
    assert create.status_code == 201
    assert create.json()["vector_synced"] is True
    assert client.get("/api/models?modality=Voice").json()[0]["title"] == "Test Voice"


def test_non_admin_cannot_manage_models(client: TestClient) -> None:
    client.post(
        "/api/auth/register", json={"email": "user@test.dev", "password": "password123"}
    )
    client.post(
        "/api/auth/login", json={"email": "user@test.dev", "password": "password123"}
    )

    response = client.post(
        "/api/admin/models",
        json={
            "title": "Blocked",
            "description": "Should not be created.",
            "provider": "Test Labs",
            "modality": "LLM",
            "price": "$1",
        },
    )
    assert response.status_code == 403


def test_admin_can_manually_trigger_digest_but_non_admin_cannot(client: TestClient) -> None:
    client.post(
        "/api/auth/register", json={"email": "digest-user@test.dev", "password": "password123"}
    )
    client.post(
        "/api/auth/login", json={"email": "digest-user@test.dev", "password": "password123"}
    )
    blocked = client.post("/api/admin/digest/run")
    assert blocked.status_code == 403

    client.post(
        "/api/admin/login", json={"email": "curator@test.dev", "password": "password123"}
    )
    allowed = client.post("/api/admin/digest/run")
    assert allowed.status_code == 200
    assert set(allowed.json().keys()) == {"sent", "skipped"}


def test_recommendation_retrieves_only_indexed_catalog_candidates(
    client: TestClient,
) -> None:
    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    created = client.post(
        "/api/admin/models",
        json={
            "title": "Realtime Voice",
            "description": "Low latency speech for realtime agents.",
            "provider": "Test Labs",
            "modality": "Voice",
            "price": "$0.001/char",
            "latency_ms": 100,
            "use_case_tags": ["realtime voice"],
        },
    )
    assert created.status_code == 201

    client.post(
        "/api/auth/register",
        json={"email": "retrieval@test.dev", "password": "password123"},
    )
    client.post(
        "/api/auth/login",
        json={"email": "retrieval@test.dev", "password": "password123"},
    )
    client.post(
        "/api/events/batch",
        json={
            "events": [
                {"event_type": "search", "metadata": {"query": "realtime voice"}},
                {"event_type": "model_view", "model_id": created.json()["id"]},
                {"event_type": "model_compare", "model_id": created.json()["id"]},
            ]
        },
    )

    recommendation = client.get("/api/recommendations/me")
    assert recommendation.status_code == 200
    assert recommendation.json()["status"] == "retrieval_ready"
    assert recommendation.json()["activity_hash"]
    assert recommendation.json()["models"][0]["id"] == created.json()["id"]

    # `recommendation_triggered` on the response only reflects the cheap AGT-1 event-count
    # check (NFR-1: the expensive pipeline now runs in the background, off the request path,
    # so the response can't wait to know whether AGT-6 will end up deduping it). AGT-6's
    # actual no-duplicate-work guarantee is verified directly below: the stored recommendation
    # itself must be unchanged, not just this field.
    first_created_at = recommendation.json()["created_at"]
    client.post(
        "/api/events/batch",
        json={
            "events": [
                {"event_type": "search", "metadata": {"query": "realtime voice"}},
                {"event_type": "model_view", "model_id": created.json()["id"]},
                {"event_type": "model_compare", "model_id": created.json()["id"]},
            ]
        },
    )
    unchanged = client.get("/api/recommendations/me").json()
    assert unchanged["created_at"] == first_created_at, (
        "AGT-6 should dedupe unchanged activity — no new recommendation should be stored"
    )


def test_mesh_narrative_is_persisted_and_model_ids_are_grounded(
    client: TestClient,
) -> None:
    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    created = client.post(
        "/api/admin/models",
        json={
            "title": "Grounded Voice",
            "description": "Low latency speech for realtime agents.",
            "provider": "Test Labs",
            "modality": "Voice",
            "price": "$0.001/char",
            "latency_ms": 100,
            "use_case_tags": ["realtime voice"],
        },
    )
    model_id = created.json()["id"]

    class FakeMeshGenerator:
        enabled = True

        def generate(self, behavior_summary, candidates):
            assert candidates[0]["id"] == model_id
            return {
                "narrative": "Grounded Voice is the lower-latency choice.",
                "model_ids": [model_id, 999999],
            }

    client.app.state.mesh_generator = FakeMeshGenerator()
    client.post(
        "/api/auth/register",
        json={"email": "narrative@test.dev", "password": "password123"},
    )
    client.post(
        "/api/auth/login",
        json={"email": "narrative@test.dev", "password": "password123"},
    )
    response = client.post(
        "/api/events/batch",
        json={
            "events": [
                {"event_type": "search", "metadata": {"query": "realtime voice"}},
                {"event_type": "model_view", "model_id": model_id},
                {"event_type": "model_compare", "model_id": model_id},
            ]
        },
    )

    assert response.json()["recommendation_triggered"] is True
    recommendation = client.get("/api/recommendations/me").json()
    assert recommendation["status"] == "ready"
    assert recommendation["narrative"] == "Grounded Voice is the lower-latency choice."
    assert [model["id"] for model in recommendation["models"]] == [model_id]


def test_analyze_activity_clusters_same_modality_views(client: TestClient) -> None:
    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    voice_a = client.post(
        "/api/admin/models",
        json={
            "title": "Voice Alpha",
            "description": "Low latency speech for realtime agents.",
            "provider": "Test Labs",
            "modality": "Voice",
            "price": "$0.001/char",
            "use_case_tags": ["realtime voice"],
        },
    ).json()["id"]
    voice_b = client.post(
        "/api/admin/models",
        json={
            "title": "Voice Beta",
            "description": "Streaming speech for conversational agents.",
            "provider": "Test Labs",
            "modality": "Voice",
            "price": "$0.002/char",
            "use_case_tags": ["realtime voice"],
        },
    ).json()["id"]

    client.post(
        "/api/auth/register",
        json={"email": "cluster@test.dev", "password": "password123"},
    )
    client.post(
        "/api/auth/login",
        json={"email": "cluster@test.dev", "password": "password123"},
    )
    client.post(
        "/api/events/batch",
        json={
            "events": [
                {"event_type": "search", "metadata": {"query": "realtime voice"}},
                {"event_type": "model_view", "model_id": voice_a},
                {"event_type": "model_view", "model_id": voice_b},
            ]
        },
    )

    recommendation = client.get("/api/recommendations/me").json()
    summary = recommendation["behavior_summary"]
    assert "browsing multiple voice models" in summary.lower()
    # Clustering is a soft signal, never phrased as an explicit comparison.
    assert " vs " not in summary.lower()
