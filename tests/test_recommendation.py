from datetime import datetime, timedelta

import pytest

from app.config import Settings
from app.db import build_session_factory
from app.models import CatalogItem, Event, Recommendation, Tenant, Widget
from app.services.recommendation import (
    SESSION_COOLDOWN,
    SESSION_GAP,
    FeedbackRecord,
    activity_hash,
    is_recommendation_stale,
    mesh_cost_rollup,
    recent_feedback_by_catalog_item,
    session_evidence,
    should_trigger,
)
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


def _make_widget(session, tenant: Tenant) -> Widget:
    widget, _raw_key = create_widget(session, tenant, "Test Widget")
    return widget


def test_session_evidence_scopes_to_current_session_only(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = "v-evidence"
        old_model = CatalogItem(
            tenant_id=tenant.id,
            widget_id=widget.id,
            title="Old Model",
            provider="Test",
            category="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        new_model = CatalogItem(
            tenant_id=tenant.id,
            widget_id=widget.id,
            title="New Model",
            provider="Test",
            category="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([old_model, new_model])
        session.commit()

        now = datetime.utcnow()
        session.add_all(
            [
                # Older session, well outside SESSION_GAP of the events below.
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="model_view",
                    catalog_item_id=old_model.id,
                    metadata_json={},
                    created_at=now - SESSION_GAP - timedelta(hours=1),
                ),
                # Current session.
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="model_view",
                    catalog_item_id=new_model.id,
                    metadata_json={},
                    created_at=now,
                ),
            ]
        )
        session.commit()

        events = session.query(Event).order_by(Event.created_at.desc()).all()
        evidence = session_evidence(session, widget.id, events)

        assert len(evidence) == 1
        assert evidence[0]["label"] == "New Model"
        assert evidence[0]["action"] == "viewed"


def test_session_evidence_dedupes_repeat_views_and_includes_search(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = "v-dedupe"
        model = CatalogItem(
            tenant_id=tenant.id,
            widget_id=widget.id,
            title="Cartesia Sonic",
            provider="Cartesia",
            category="Voice",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add(model)
        session.commit()

        now = datetime.utcnow()
        session.add_all(
            [
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="search",
                    metadata_json={"query": "multilingual"},
                    created_at=now - timedelta(minutes=2),
                ),
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="model_view",
                    catalog_item_id=model.id,
                    metadata_json={},
                    created_at=now - timedelta(minutes=1),
                ),
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="model_view",
                    catalog_item_id=model.id,
                    metadata_json={},
                    created_at=now,
                ),
            ]
        )
        session.commit()

        events = session.query(Event).order_by(Event.created_at.desc()).all()
        evidence = session_evidence(session, widget.id, events)

        # Two model_view events for the same model dedupe to one "viewed" entry.
        assert [item["action"] for item in evidence] == ["viewed", "searched"]
        assert evidence[1]["label"] == '"multilingual"'


def _make_visitor_with_events(session, widget_id, visitor_id, event_count=2):
    now = datetime.utcnow()
    session.add_all(
        [
            Event(
                widget_id=widget_id,
                visitor_id=visitor_id,
                event_type="search",
                metadata_json={"query": f"query {i}"},
                created_at=now - timedelta(seconds=event_count - i),
            )
            for i in range(event_count)
        ]
    )
    session.commit()
    return visitor_id


def test_should_trigger_false_below_session_threshold(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = _make_visitor_with_events(
            session, widget.id, "v-below", event_count=1
        )
        assert should_trigger(session, widget.id, visitor_id) is False


def test_should_trigger_true_with_no_prior_recommendation(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = _make_visitor_with_events(
            session, widget.id, "v-fresh", event_count=2
        )
        assert should_trigger(session, widget.id, visitor_id) is True


def test_should_trigger_false_when_activity_unchanged_since_last_recommendation(
    tmp_path,
) -> None:
    """Regression test: this is the fix for "so many agent_pipeline traces running" —
    should_trigger must not keep re-firing on every batch in an already-triggered
    session once nothing has actually changed since the last recommendation."""
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = _make_visitor_with_events(
            session, widget.id, "v-unchanged", event_count=2
        )
        events = list(
            session.query(Event)
            .filter(Event.visitor_id == visitor_id)
            .order_by(Event.created_at.desc())
        )
        session.add(
            Recommendation(
                tenant_id=tenant.id,
                widget_id=widget.id,
                visitor_id=visitor_id,
                catalog_item_ids=[],
                behavior_summary="",
                activity_hash=activity_hash(events),
                trigger_reason="event_threshold",
            )
        )
        session.commit()

        assert should_trigger(session, widget.id, visitor_id) is False


def test_should_trigger_true_when_activity_changed_after_cooldown_expires(
    tmp_path,
) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = _make_visitor_with_events(
            session, widget.id, "v-changed", event_count=2
        )
        session.add(
            Recommendation(
                tenant_id=tenant.id,
                widget_id=widget.id,
                visitor_id=visitor_id,
                catalog_item_ids=[],
                behavior_summary="",
                activity_hash="a-different-hash-entirely",
                trigger_reason="event_threshold",
                created_at=datetime.utcnow() - SESSION_COOLDOWN - timedelta(seconds=1),
            )
        )
        session.commit()

        assert should_trigger(session, widget.id, visitor_id) is True


def test_is_recommendation_stale_true_with_no_prior_recommendation() -> None:
    assert is_recommendation_stale([], None) is True


def test_is_recommendation_stale_false_on_matching_hash() -> None:
    event = Event(
        tenant_id=1, visitor_id="v1", event_type="search", metadata_json={"query": "x"}
    )
    recommendation = Recommendation(
        tenant_id=1,
        visitor_id="v1",
        catalog_item_ids=[],
        behavior_summary="",
        activity_hash=activity_hash([event]),
        trigger_reason="event_threshold",
        created_at=datetime.utcnow(),
    )
    assert is_recommendation_stale([event], recommendation) is False


def test_is_recommendation_stale_false_within_cooldown_same_session() -> None:
    now = datetime.utcnow()
    event = Event(
        tenant_id=1,
        visitor_id="v1",
        event_type="search",
        metadata_json={"query": "x"},
        created_at=now,
    )
    recommendation = Recommendation(
        tenant_id=1,
        visitor_id="v1",
        catalog_item_ids=[],
        behavior_summary="",
        activity_hash="different-hash",
        trigger_reason="event_threshold",
        created_at=now - timedelta(seconds=30),
    )
    assert is_recommendation_stale([event], recommendation) is False


def test_is_recommendation_stale_true_once_cooldown_expires() -> None:
    now = datetime.utcnow()
    event = Event(
        tenant_id=1,
        visitor_id="v1",
        event_type="search",
        metadata_json={"query": "x"},
        created_at=now,
    )
    recommendation = Recommendation(
        tenant_id=1,
        visitor_id="v1",
        catalog_item_ids=[],
        behavior_summary="",
        activity_hash="different-hash",
        trigger_reason="event_threshold",
        created_at=now - SESSION_COOLDOWN - timedelta(seconds=1),
    )
    assert is_recommendation_stale([event], recommendation) is True


def test_recent_feedback_by_catalog_item_returns_latest_rating_per_item(
    tmp_path,
) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = "v-feedback"
        now = datetime.utcnow()
        session.add_all(
            [
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="recommendation_feedback",
                    catalog_item_id=1,
                    metadata_json={"rating": "up", "recommendation_id": 10},
                    created_at=now - timedelta(minutes=5),
                ),
                # Visitor changed their mind about model 1 — the newer "down" must win.
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="recommendation_feedback",
                    catalog_item_id=1,
                    metadata_json={"rating": "down", "recommendation_id": 11},
                    created_at=now,
                ),
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="recommendation_feedback",
                    catalog_item_id=2,
                    metadata_json={"rating": "up", "recommendation_id": 11},
                    created_at=now,
                ),
                # Not feedback — must not pollute the result.
                Event(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    event_type="model_view",
                    catalog_item_id=3,
                    metadata_json={},
                    created_at=now,
                ),
            ]
        )
        session.commit()

        feedback = recent_feedback_by_catalog_item(session, widget.id, visitor_id)
        assert feedback == {
            1: FeedbackRecord(rating="down", context_query=""),
            2: FeedbackRecord(rating="up", context_query=""),
        }


def test_recent_feedback_by_catalog_item_resolves_context_query_from_linked_recommendation(
    tmp_path,
) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = "v-context"
        recommendation = Recommendation(
            tenant_id=tenant.id,
            widget_id=widget.id,
            visitor_id=visitor_id,
            catalog_item_ids=[1],
            behavior_summary="rack based server model",
            activity_hash="hash-1",
            trigger_reason="event_threshold",
        )
        session.add(recommendation)
        session.commit()
        session.add(
            Event(
                tenant_id=tenant.id,
                widget_id=widget.id,
                visitor_id=visitor_id,
                event_type="recommendation_feedback",
                catalog_item_id=1,
                metadata_json={
                    "rating": "down",
                    "recommendation_id": recommendation.id,
                },
                created_at=datetime.utcnow(),
            )
        )
        session.commit()

        feedback = recent_feedback_by_catalog_item(session, widget.id, visitor_id)
        assert feedback == {
            1: FeedbackRecord(rating="down", context_query="rack based server model")
        }


def test_recent_feedback_by_catalog_item_ignores_stale_feedback(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = "v-stale"
        session.add(
            Event(
                tenant_id=tenant.id,
                widget_id=widget.id,
                visitor_id=visitor_id,
                event_type="recommendation_feedback",
                catalog_item_id=1,
                metadata_json={"rating": "down"},
                created_at=datetime.utcnow() - timedelta(days=30),
            )
        )
        session.commit()

        assert recent_feedback_by_catalog_item(session, widget.id, visitor_id) == {}


def test_mesh_cost_rollup_aggregates_only_generated_recommendations(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        widget = _make_widget(session, tenant)
        visitor_id = "v-cost"
        session.add_all(
            [
                Recommendation(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    catalog_item_ids=[],
                    behavior_summary="",
                    activity_hash="hash-1",
                    trigger_reason="event_threshold",
                    mesh_latency_ms=200.0,
                    mesh_prompt_tokens=100,
                    mesh_completion_tokens=50,
                    mesh_cost_usd=0.001,
                ),
                Recommendation(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    catalog_item_ids=[],
                    behavior_summary="",
                    activity_hash="hash-2",
                    trigger_reason="event_threshold",
                    mesh_latency_ms=400.0,
                    mesh_prompt_tokens=300,
                    mesh_completion_tokens=150,
                    mesh_cost_usd=0.003,
                ),
                # Retrieval-only (no Mesh call) — must not be counted or averaged in.
                Recommendation(
                    tenant_id=tenant.id,
                    widget_id=widget.id,
                    visitor_id=visitor_id,
                    catalog_item_ids=[],
                    behavior_summary="",
                    activity_hash="hash-3",
                    trigger_reason="event_threshold",
                ),
            ]
        )
        session.commit()

        rollup = mesh_cost_rollup(session, tenant.id)
        assert rollup["call_count"] == 2
        assert rollup["avg_latency_ms"] == 300.0
        assert rollup["total_prompt_tokens"] == 400
        assert rollup["total_completion_tokens"] == 200
        assert rollup["total_cost_usd"] == pytest.approx(0.004)
        assert len(rollup["recent"]) == 2


def test_mesh_cost_rollup_is_empty_with_no_generated_recommendations(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        rollup = mesh_cost_rollup(session, tenant.id)
        assert rollup["call_count"] == 0
        assert rollup["avg_latency_ms"] is None
        assert rollup["total_cost_usd"] is None
        assert rollup["recent"] == []
