"""NFR-2 (LLM call budget). NFR-1 (event ingestion latency) has no endpoint to test
against right now — POST /api/events/batch was removed with the AI-engineer
cookie-session surface (docs/design/09-Platform-Pivot-Decision.md) and returns with
the tracker SDK phase (POST /api/track/events); re-add an NFR-1 test against that
endpoint then, scoped to tenant+visitor ingestion instead of a logged-in user.
"""

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, Tenant, User
from app.security import hash_password
from app.services.agent_graph import prepare_retrieval_recommendation


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
    )
    return build_session_factory(settings)


def _make_tenant(session) -> Tenant:
    tenant = Tenant(name="Test Tenant")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def test_agent_pipeline_calls_generation_at_most_once_per_trigger(tmp_path) -> None:
    """NFR-2: at most 1 LLM generation call per trigger event, excluding bounded retries.
    Retries (AGT-4) only re-run retrieval, never generation — forcing 2 retries here proves
    the Mesh call count stays at 1 regardless of how many retrieval attempts happened.
    """
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        user = User(
            tenant_id=tenant.id,
            email="nfr2@test.dev",
            password_hash=hash_password("x"),
            role="user",
        )
        model = Model(
            tenant_id=tenant.id,
            title="Eventually Found",
            provider="Test",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([user, model])
        session.commit()
        session.add(
            Event(
                tenant_id=tenant.id,
                user_id=user.id,
                event_type="search",
                metadata_json={"query": "test"},
            )
        )
        session.commit()

        class RetryForcingStore:
            def __init__(self) -> None:
                self.calls = 0

            def query_scored(
                self,
                text: str,
                tenant_id: int,
                limit: int = 5,
                where: dict | None = None,
            ):
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
        recommendation = prepare_retrieval_recommendation(
            session, store, tenant.id, user.id, mesh
        )

        assert store.calls == 3, "expected the initial attempt plus 2 bounded retries"
        assert mesh.calls == 1, "generation must run exactly once despite the retries"
        assert recommendation is not None
