"""NFR-2 (LLM call budget). NFR-1 (event ingestion latency) has no endpoint to test
against right now — POST /api/events/batch was removed with the AI-engineer
cookie-session surface (docs/design/09-Platform-Pivot-Decision.md) and returns with
the tracker SDK phase (POST /api/track/events); re-add an NFR-1 test against that
endpoint then, scoped to tenant+visitor ingestion instead of a logged-in user.
"""

from app.config import Settings
from app.db import build_session_factory
from app.models import CatalogItem, Event, Tenant
from app.services.agent_graph import prepare_retrieval_recommendation
from app.services.widgets import create_widget


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
        widget, _raw_key = create_widget(session, tenant, "Test Widget")
        visitor_id = "v-nfr2"
        item = CatalogItem(
            tenant_id=tenant.id,
            widget_id=widget.id,
            title="Eventually Found",
            provider="Test",
            category="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add(item)
        session.commit()
        session.add(
            Event(
                tenant_id=tenant.id,
                widget_id=widget.id,
                visitor_id=visitor_id,
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
                widget_id: int,
                limit: int = 5,
                where: dict | None = None,
            ):
                self.calls += 1
                # Weak until the 3rd attempt (initial + 2 retries == MAX_RETRIES), so
                # grade_refine is forced through its full retry budget before proceeding.
                distance = 1.9 if self.calls < 3 else 0.2
                return [(item.id, distance)]

        class CountingMeshGenerator:
            enabled = True

            def __init__(self) -> None:
                self.calls = 0

            def generate(self, behavior_summary, candidates):
                self.calls += 1
                return {"narrative": "ok", "catalog_item_ids": [item.id]}

        store = RetryForcingStore()
        mesh = CountingMeshGenerator()
        recommendation = prepare_retrieval_recommendation(
            session, store, widget.id, tenant.id, visitor_id, mesh
        )

        assert store.calls == 3, "expected the initial attempt plus 2 bounded retries"
        assert mesh.calls == 1, "generation must run exactly once despite the retries"
        assert recommendation is not None
