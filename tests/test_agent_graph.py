from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, User
from app.security import hash_password
from app.services.agent_graph import prepare_retrieval_recommendation


class FakeVectorStore:
    """Returns a weak match on the first call and a strong match on the second — proves
    grade_refine (AGT-4) actually retries with a broadened query rather than accepting a
    poor first result."""

    def __init__(self, weak_id: int, strong_id: int) -> None:
        self.weak_id = weak_id
        self.strong_id = strong_id
        self.calls: list[str] = []

    def query_scored(self, text: str, limit: int = 5):
        self.calls.append(text)
        if len(self.calls) == 1:
            return [(self.weak_id, 1.9)]
        return [(self.strong_id, 0.3)]


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
    )
    return build_session_factory(settings)


def test_grade_refine_retries_on_weak_retrieval(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(email="grade@test.dev", password_hash=hash_password("x"), role="user")
        weak_model = Model(
            title="Weak Match", provider="Test", modality="LLM",
            price="$0", description="d", use_case_tags=[],
        )
        strong_model = Model(
            title="Strong Match", provider="Test", modality="LLM",
            price="$0", description="d", use_case_tags=[],
        )
        session.add_all([user, weak_model, strong_model])
        session.commit()

        session.add_all(
            [
                Event(user_id=user.id, event_type="search", metadata_json={"query": "test"}),
                Event(
                    user_id=user.id,
                    event_type="model_view",
                    model_id=weak_model.id,
                    metadata_json={},
                ),
                Event(
                    user_id=user.id,
                    event_type="model_compare",
                    model_id=weak_model.id,
                    metadata_json={"explicit": True},
                ),
            ]
        )
        session.commit()

        fake_store = FakeVectorStore(weak_model.id, strong_model.id)
        recommendation = prepare_retrieval_recommendation(
            session, fake_store, user.id, mesh_generator=None
        )

        assert len(fake_store.calls) == 2, "grade_refine should retry once on a weak match"
        assert recommendation is not None
        assert recommendation.model_ids == [strong_model.id]


def test_grade_refine_stops_after_max_retries_with_no_candidates(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(email="empty@test.dev", password_hash=hash_password("x"), role="user")
        session.add(user)
        session.commit()

        session.add_all(
            [
                Event(user_id=user.id, event_type="search", metadata_json={"query": "a b c d e"}),
                Event(user_id=user.id, event_type="search", metadata_json={"query": "f g h"}),
                Event(user_id=user.id, event_type="search", metadata_json={"query": "i j k"}),
            ]
        )
        session.commit()

        class EmptyVectorStore:
            def __init__(self) -> None:
                self.calls = 0

            def query_scored(self, text: str, limit: int = 5):
                self.calls += 1
                return []

        empty_store = EmptyVectorStore()
        recommendation = prepare_retrieval_recommendation(
            session, empty_store, user.id, mesh_generator=None
        )

        # Initial attempt + MAX_RETRIES(=2) retries, then give up without storing anything.
        assert empty_store.calls == 3
        assert recommendation is None
