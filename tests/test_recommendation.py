from datetime import datetime, timedelta

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, Recommendation, User
from app.security import hash_password
from app.services.recommendation import (
    SESSION_COOLDOWN,
    SESSION_GAP,
    activity_hash,
    is_recommendation_stale,
    session_evidence,
    should_trigger,
)


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
    )
    return build_session_factory(settings)


def test_session_evidence_scopes_to_current_session_only(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(
            email="evidence@test.dev", password_hash=hash_password("x"), role="user"
        )
        old_model = Model(
            title="Old Model",
            provider="Test",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        new_model = Model(
            title="New Model",
            provider="Test",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([user, old_model, new_model])
        session.commit()

        now = datetime.utcnow()
        session.add_all(
            [
                # Older session, well outside SESSION_GAP of the events below.
                Event(
                    user_id=user.id,
                    event_type="model_view",
                    model_id=old_model.id,
                    metadata_json={},
                    created_at=now - SESSION_GAP - timedelta(hours=1),
                ),
                # Current session.
                Event(
                    user_id=user.id,
                    event_type="model_view",
                    model_id=new_model.id,
                    metadata_json={},
                    created_at=now,
                ),
            ]
        )
        session.commit()

        events = session.query(Event).order_by(Event.created_at.desc()).all()
        evidence = session_evidence(session, events)

        assert len(evidence) == 1
        assert evidence[0]["label"] == "New Model"
        assert evidence[0]["action"] == "viewed"


def test_session_evidence_dedupes_repeat_views_and_includes_search(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(
            email="dedupe@test.dev", password_hash=hash_password("x"), role="user"
        )
        model = Model(
            title="Cartesia Sonic",
            provider="Cartesia",
            modality="Voice",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([user, model])
        session.commit()

        now = datetime.utcnow()
        session.add_all(
            [
                Event(
                    user_id=user.id,
                    event_type="search",
                    metadata_json={"query": "multilingual"},
                    created_at=now - timedelta(minutes=2),
                ),
                Event(
                    user_id=user.id,
                    event_type="model_view",
                    model_id=model.id,
                    metadata_json={},
                    created_at=now - timedelta(minutes=1),
                ),
                Event(
                    user_id=user.id,
                    event_type="model_view",
                    model_id=model.id,
                    metadata_json={},
                    created_at=now,
                ),
            ]
        )
        session.commit()

        events = session.query(Event).order_by(Event.created_at.desc()).all()
        evidence = session_evidence(session, events)

        # Two model_view events for the same model dedupe to one "viewed" entry.
        assert [item["action"] for item in evidence] == ["viewed", "searched"]
        assert evidence[1]["label"] == '"multilingual"'


def _make_user_with_events(session, email, event_count=2):
    user = User(email=email, password_hash=hash_password("x"), role="user")
    session.add(user)
    session.commit()
    now = datetime.utcnow()
    session.add_all(
        [
            Event(
                user_id=user.id,
                event_type="search",
                metadata_json={"query": f"query {i}"},
                created_at=now - timedelta(seconds=event_count - i),
            )
            for i in range(event_count)
        ]
    )
    session.commit()
    return user


def test_should_trigger_false_below_session_threshold(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = _make_user_with_events(session, "below@test.dev", event_count=1)
        assert should_trigger(session, user.id) is False


def test_should_trigger_true_with_no_prior_recommendation(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = _make_user_with_events(session, "fresh@test.dev", event_count=2)
        assert should_trigger(session, user.id) is True


def test_should_trigger_false_when_activity_unchanged_since_last_recommendation(
    tmp_path,
) -> None:
    """Regression test: this is the fix for "so many agent_pipeline traces running" —
    should_trigger must not keep re-firing on every batch in an already-triggered
    session once nothing has actually changed since the last recommendation."""
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = _make_user_with_events(session, "unchanged@test.dev", event_count=2)
        events = list(
            session.query(Event)
            .filter(Event.user_id == user.id)
            .order_by(Event.created_at.desc())
        )
        session.add(
            Recommendation(
                user_id=user.id,
                model_ids=[],
                behavior_summary="",
                activity_hash=activity_hash(events),
                trigger_reason="event_threshold",
            )
        )
        session.commit()

        assert should_trigger(session, user.id) is False


def test_should_trigger_true_when_activity_changed_after_cooldown_expires(
    tmp_path,
) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = _make_user_with_events(session, "changed@test.dev", event_count=2)
        session.add(
            Recommendation(
                user_id=user.id,
                model_ids=[],
                behavior_summary="",
                activity_hash="a-different-hash-entirely",
                trigger_reason="event_threshold",
                created_at=datetime.utcnow() - SESSION_COOLDOWN - timedelta(seconds=1),
            )
        )
        session.commit()

        assert should_trigger(session, user.id) is True


def test_is_recommendation_stale_true_with_no_prior_recommendation() -> None:
    assert is_recommendation_stale([], None) is True


def test_is_recommendation_stale_false_on_matching_hash() -> None:
    event = Event(user_id=1, event_type="search", metadata_json={"query": "x"})
    recommendation = Recommendation(
        user_id=1,
        model_ids=[],
        behavior_summary="",
        activity_hash=activity_hash([event]),
        trigger_reason="event_threshold",
        created_at=datetime.utcnow(),
    )
    assert is_recommendation_stale([event], recommendation) is False


def test_is_recommendation_stale_false_within_cooldown_same_session() -> None:
    now = datetime.utcnow()
    event = Event(
        user_id=1, event_type="search", metadata_json={"query": "x"}, created_at=now
    )
    recommendation = Recommendation(
        user_id=1,
        model_ids=[],
        behavior_summary="",
        activity_hash="different-hash",
        trigger_reason="event_threshold",
        created_at=now - timedelta(seconds=30),
    )
    assert is_recommendation_stale([event], recommendation) is False


def test_is_recommendation_stale_true_once_cooldown_expires() -> None:
    now = datetime.utcnow()
    event = Event(
        user_id=1, event_type="search", metadata_json={"query": "x"}, created_at=now
    )
    recommendation = Recommendation(
        user_id=1,
        model_ids=[],
        behavior_summary="",
        activity_hash="different-hash",
        trigger_reason="event_threshold",
        created_at=now - SESSION_COOLDOWN - timedelta(seconds=1),
    )
    assert is_recommendation_stale([event], recommendation) is True
