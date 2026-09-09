"""Chat-bot widget phase, backend half (DLV-2 real-time push, DLV-4 grounded
follow-up Q&A, DLV-6 activity view). The actual SSE data flow
(GET /api/widget/stream) is covered by a live smoke test, not here — a sync
TestClient reading an infinite server-sent-events generator is a good way to write a
test that hangs; the auth/gate checks that fail before the stream ever opens are
covered below, and the push mechanism itself is tested at the service layer
(prepare_retrieval_recommendation's push_callback), independent of any real
connection.
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, Tenant
from app.services.agent_graph import (
    NO_ANSWER_MESSAGE,
    answer_visitor_question,
    prepare_retrieval_recommendation,
)
from app.services.mesh import QAResult
from app.services.tenants import (
    create_tenant,
    get_or_create_reference_tenant,
    issue_api_key,
)


class FakeVectorStore:
    def __init__(self, scored: list[tuple[int, float]]) -> None:
        self.scored = scored

    def query_scored(
        self, text: str, tenant_id: int, limit: int = 5, where: dict | None = None
    ):
        return self.scored

    @staticmethod
    def document(model) -> str:
        return f"{model.title}. {model.provider}. {model.modality}. {model.description}"


class FakeMeshGenerator:
    enabled = True

    def __init__(self, answer: str, model_ids: list[int]) -> None:
        self._answer = answer
        self._model_ids = model_ids

    def answer_question(self, question, candidates):
        return QAResult(answer=self._answer, model_ids=self._model_ids)


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
    )
    return build_session_factory(settings)


def _make_tenant_and_model(session) -> tuple[Tenant, Model]:
    tenant = Tenant(name="Test Tenant", status="active")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    model = Model(
        tenant_id=tenant.id,
        title="Travel Card",
        provider="Acme",
        modality="LLM",
        price="$0",
        latency_ms=200,
        description="A travel rewards card with no annual fee.",
        use_case_tags=["travel"],
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return tenant, model


def test_answer_visitor_question_returns_fixed_message_with_no_candidates(
    tmp_path,
) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant, _ = _make_tenant_and_model(session)
        result = answer_visitor_question(
            session, FakeVectorStore([]), tenant.id, "v-1", "what is the fee?"
        )
        assert result == {"answer": NO_ANSWER_MESSAGE, "model_ids": []}


def test_answer_visitor_question_returns_fixed_message_on_weak_retrieval(
    tmp_path,
) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant, model = _make_tenant_and_model(session)
        # Above WEAK_RETRIEVAL_DISTANCE (1.5) — not a groundable match, must never
        # reach the LLM (AGT-8).
        result = answer_visitor_question(
            session,
            FakeVectorStore([(model.id, 1.9)]),
            tenant.id,
            "v-1",
            "unrelated question",
            mesh_generator=FakeMeshGenerator("should never be returned", [model.id]),
        )
        assert result == {"answer": NO_ANSWER_MESSAGE, "model_ids": []}


def test_answer_visitor_question_grounds_to_retrieved_candidates(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant, model = _make_tenant_and_model(session)
        other = Model(
            tenant_id=tenant.id,
            title="Other Card",
            provider="Acme",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add(other)
        session.commit()
        session.refresh(other)

        # The LLM (fake) tries to cite a model that wasn't actually retrieved —
        # filtered out, same grounding-guard discipline as _generate_narrative.
        fake_mesh = FakeMeshGenerator("No annual fee.", [model.id, other.id + 999])
        result = answer_visitor_question(
            session,
            FakeVectorStore([(model.id, 0.2)]),
            tenant.id,
            "v-1",
            "does it have an annual fee?",
            mesh_generator=fake_mesh,
        )
        assert result == {"answer": "No annual fee.", "model_ids": [model.id]}


def test_widget_push_sets_pushed_at_when_a_connection_is_open(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant, model = _make_tenant_and_model(session)
        session.add(
            Event(
                tenant_id=tenant.id,
                visitor_id="v-push",
                event_type="model_view",
                model_id=model.id,
                metadata_json={},
            )
        )
        session.commit()

        recommendation = prepare_retrieval_recommendation(
            session,
            FakeVectorStore([(model.id, 0.2)]),
            tenant.id,
            "v-push",
            mesh_generator=None,
            push_callback=lambda payload: True,
        )
        assert recommendation is not None
        assert recommendation.pushed_at is not None


def test_widget_push_leaves_pushed_at_null_with_no_connection(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant, model = _make_tenant_and_model(session)
        session.add(
            Event(
                tenant_id=tenant.id,
                visitor_id="v-nopush",
                event_type="model_view",
                model_id=model.id,
                metadata_json={},
            )
        )
        session.commit()

        recommendation = prepare_retrieval_recommendation(
            session,
            FakeVectorStore([(model.id, 0.2)]),
            tenant.id,
            "v-nopush",
            mesh_generator=None,
            push_callback=lambda payload: False,
        )
        assert recommendation is not None
        assert recommendation.pushed_at is None


def test_widget_ask_endpoint_rejects_unknown_tenant_key(client: TestClient) -> None:
    response = client.post(
        "/api/widget/ask",
        json={
            "tenant_key": "tk_live_bogus",
            "visitor_id": "v-1",
            "question": "anything",
        },
    )
    assert response.status_code == 401


def test_widget_ask_endpoint_rejects_onboarding_tenant(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        _, raw_key = create_tenant(session, "Not Ready Yet")

    response = client.post(
        "/api/widget/ask",
        json={"tenant_key": raw_key, "visitor_id": "v-1", "question": "anything"},
    )
    assert response.status_code == 403


def test_widget_ask_endpoint_answers_with_no_mesh_configured(
    client: TestClient,
) -> None:
    # The client fixture's reference tenant has no Mesh key configured — a question
    # with no LLM available still returns AGT-8's explicit "don't know" response
    # rather than erroring.
    with client.app.state.session_factory() as session:
        tenant = get_or_create_reference_tenant(session)
        raw_key = issue_api_key(session, tenant)

    response = client.post(
        "/api/widget/ask",
        json={
            "tenant_key": raw_key,
            "visitor_id": "v-1",
            "question": "what's the cheapest option?",
        },
    )
    assert response.status_code == 200
    assert response.json()["answer"] == NO_ANSWER_MESSAGE


def test_widget_activity_endpoint_returns_recent_events(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        tenant = get_or_create_reference_tenant(session)
        raw_key = issue_api_key(session, tenant)
        session.add(
            Event(
                tenant_id=tenant.id,
                visitor_id="v-activity",
                event_type="search",
                metadata_json={"query": "travel"},
            )
        )
        session.commit()

    response = client.get(
        f"/api/widget/activity?tenant_key={raw_key}&visitor_id=v-activity"
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["type"] == "search"
    assert body["pipeline"] is None


def test_widget_activity_endpoint_rejects_onboarding_tenant(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
        _, raw_key = create_tenant(session, "Not Ready Yet")

    response = client.get(f"/api/widget/activity?tenant_key={raw_key}&visitor_id=v-1")
    assert response.status_code == 403


def test_widget_stream_rejects_onboarding_tenant(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        _, raw_key = create_tenant(session, "Not Ready Yet")

    response = client.get(f"/api/widget/stream?tenant_key={raw_key}&visitor_id=v-1")
    assert response.status_code == 403
