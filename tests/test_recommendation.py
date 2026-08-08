from datetime import datetime, timedelta

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, User
from app.security import hash_password
from app.services.recommendation import SESSION_GAP, session_evidence


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
    )
    return build_session_factory(settings)


def test_session_evidence_scopes_to_current_session_only(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(email="evidence@test.dev", password_hash=hash_password("x"), role="user")
        old_model = Model(
            title="Old Model", provider="Test", modality="LLM",
            price="$0", description="d", use_case_tags=[],
        )
        new_model = Model(
            title="New Model", provider="Test", modality="LLM",
            price="$0", description="d", use_case_tags=[],
        )
        session.add_all([user, old_model, new_model])
        session.commit()

        now = datetime.utcnow()
        session.add_all(
            [
                # Older session, well outside SESSION_GAP of the events below.
                Event(
                    user_id=user.id, event_type="model_view", model_id=old_model.id,
                    metadata_json={}, created_at=now - SESSION_GAP - timedelta(hours=1),
                ),
                # Current session.
                Event(
                    user_id=user.id, event_type="model_view", model_id=new_model.id,
                    metadata_json={}, created_at=now,
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
        user = User(email="dedupe@test.dev", password_hash=hash_password("x"), role="user")
        model = Model(
            title="Cartesia Sonic", provider="Cartesia", modality="Voice",
            price="$0", description="d", use_case_tags=[],
        )
        session.add_all([user, model])
        session.commit()

        now = datetime.utcnow()
        session.add_all(
            [
                Event(
                    user_id=user.id, event_type="search", metadata_json={"query": "multilingual"},
                    created_at=now - timedelta(minutes=2),
                ),
                Event(
                    user_id=user.id, event_type="model_view", model_id=model.id,
                    metadata_json={}, created_at=now - timedelta(minutes=1),
                ),
                Event(
                    user_id=user.id, event_type="model_view", model_id=model.id,
                    metadata_json={}, created_at=now,
                ),
            ]
        )
        session.commit()

        events = session.query(Event).order_by(Event.created_at.desc()).all()
        evidence = session_evidence(session, events)

        # Two model_view events for the same model dedupe to one "viewed" entry.
        assert [item["action"] for item in evidence] == ["viewed", "searched"]
        assert evidence[1]["label"] == '"multilingual"'
