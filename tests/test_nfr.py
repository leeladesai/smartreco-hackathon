"""Iteration 1 close-out: NFR-1 (ingestion latency) and NFR-2 (LLM call budget)."""

import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, User
from app.security import hash_password
from app.services.agent_graph import prepare_retrieval_recommendation

NFR1_P95_BUDGET_SECONDS = 0.150
SAMPLE_SIZE = 40


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def test_event_ingestion_p95_latency_under_budget(client: TestClient) -> None:
    """NFR-1: ingestion must stay under 150ms p95. This only holds because the triggered
    agent pipeline (a real network LLM call) runs in a background task after the response is
    sent, not inline — see `run_pipeline_in_background` in `app/main.py`. Each sample uses a
    fresh user with a single event, staying under AGT-1's 3-event trigger threshold, so this
    isolates plain ingestion cost rather than measuring a run that also happens to trigger."""
    samples: list[float] = []
    for i in range(SAMPLE_SIZE):
        email = f"perf{i}@test.dev"
        client.post("/api/auth/register", json={"email": email, "password": "password123"})
        client.post("/api/auth/login", json={"email": email, "password": "password123"})

        start = time.perf_counter()
        response = client.post(
            "/api/events/batch",
            json={"events": [{"event_type": "search", "metadata": {"query": "test"}}]},
        )
        samples.append(time.perf_counter() - start)
        assert response.status_code == 200
        assert response.json()["recommendation_triggered"] is False

    p95 = _p95(samples)
    assert p95 < NFR1_P95_BUDGET_SECONDS, (
        f"p95 ingestion latency {p95 * 1000:.1f}ms exceeds the {NFR1_P95_BUDGET_SECONDS * 1000:.0f}ms budget"
    )


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
    )
    return build_session_factory(settings)


def test_agent_pipeline_calls_generation_at_most_once_per_trigger(tmp_path) -> None:
    """NFR-2: at most 1 LLM generation call per trigger event, excluding bounded retries.
    Retries (AGT-4) only re-run retrieval, never generation — forcing 2 retries here proves
    the Mesh call count stays at 1 regardless of how many retrieval attempts happened."""
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(email="nfr2@test.dev", password_hash=hash_password("x"), role="user")
        model = Model(
            title="Eventually Found", provider="Test", modality="LLM",
            price="$0", description="d", use_case_tags=[],
        )
        session.add_all([user, model])
        session.commit()
        session.add(
            Event(user_id=user.id, event_type="search", metadata_json={"query": "test"})
        )
        session.commit()

        class RetryForcingStore:
            def __init__(self) -> None:
                self.calls = 0

            def query_scored(self, text: str, limit: int = 5, where: dict | None = None):
                self.calls += 1
                # Weak until the 3rd attempt (initial + 2 retries == MAX_RETRIES), so
                # grade_refine is forced through its full retry budget before proceeding.
                distance = 1.9 if self.calls < 3 else 0.2
                return [(model.id, distance)]

        class CountingMeshGenerator:
            enabled = True

            def __init__(self) -> None:
                self.calls = 0

            def generate(self, behavior_summary, candidates):
                self.calls += 1
                return {"narrative": "ok", "model_ids": [model.id]}

        store = RetryForcingStore()
        mesh = CountingMeshGenerator()
        recommendation = prepare_retrieval_recommendation(session, store, user.id, mesh)

        assert store.calls == 3, "expected the initial attempt plus 2 bounded retries"
        assert mesh.calls == 1, "generation must run exactly once despite the retries"
        assert recommendation is not None
