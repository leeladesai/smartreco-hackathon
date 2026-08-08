from datetime import datetime

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, User
from app.security import hash_password
from app.services.agent_graph import contextual_reason, prepare_retrieval_recommendation


class FakeVectorStore:
    """Returns a weak match on the first call and a strong match on the second — proves
    grade_refine (AGT-4) actually retries with a broadened query rather than accepting a
    poor first result."""

    def __init__(self, weak_id: int, strong_id: int) -> None:
        self.weak_id = weak_id
        self.strong_id = strong_id
        self.calls: list[str] = []

    def query_scored(self, text: str, limit: int = 5, where: dict | None = None):
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
        user = User(
            email="grade@test.dev", password_hash=hash_password("x"), role="user"
        )
        weak_model = Model(
            title="Weak Match",
            provider="Test",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        strong_model = Model(
            title="Strong Match",
            provider="Test",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([user, weak_model, strong_model])
        session.commit()

        session.add_all(
            [
                Event(
                    user_id=user.id,
                    event_type="search",
                    metadata_json={"query": "test"},
                ),
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

        assert (
            len(fake_store.calls) == 2
        ), "grade_refine should retry once on a weak match"
        assert recommendation is not None
        assert recommendation.model_ids == [strong_model.id]
        assert recommendation.retrieval_meta == [
            {
                "model_id": strong_model.id,
                "distance": 0.3,
                "reason": "Matched after broadening your activity signal",
            }
        ]


def test_retrieval_meta_reason_reflects_distance_without_retry(tmp_path) -> None:
    """ "Why this" tags (DLV-2/Iteration 2) should read a plain match-strength reason off
    the retrieval distance when grade_refine never had to broaden the query."""
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(
            email="strong@test.dev", password_hash=hash_password("x"), role="user"
        )
        model = Model(
            title="Immediate Match",
            provider="Test",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([user, model])
        session.commit()

        session.add(
            Event(user_id=user.id, event_type="search", metadata_json={"query": "test"})
        )
        session.commit()

        class StrongFirstTryStore:
            def query_scored(
                self, text: str, limit: int = 5, where: dict | None = None
            ):
                return [(model.id, 0.4)]

        recommendation = prepare_retrieval_recommendation(
            session, StrongFirstTryStore(), user.id, mesh_generator=None
        )

        assert recommendation is not None
        assert recommendation.retrieval_meta == [
            {
                "model_id": model.id,
                "distance": 0.4,
                "reason": "Strong match to your recent activity",
            }
        ]


def test_retrieval_applies_modality_filter_on_first_pass_only(tmp_path) -> None:
    """Retrieval polish (Iteration 3): browsing 2+ Voice models in one session should
    pre-filter the first retrieval call to `modality=Voice`, but a retry (triggered here by
    a weak first-pass match) drops the filter again since the query text is already being
    broadened."""
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(
            email="filter@test.dev", password_hash=hash_password("x"), role="user"
        )
        voice_a = Model(
            title="Voice A",
            provider="Test",
            modality="Voice",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        voice_b = Model(
            title="Voice B",
            provider="Test",
            modality="Voice",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([user, voice_a, voice_b])
        session.commit()

        session.add_all(
            [
                Event(
                    user_id=user.id,
                    event_type="model_view",
                    model_id=voice_a.id,
                    metadata_json={},
                ),
                Event(
                    user_id=user.id,
                    event_type="model_view",
                    model_id=voice_b.id,
                    metadata_json={},
                ),
            ]
        )
        session.commit()

        class RecordingStore:
            def __init__(self) -> None:
                self.wheres: list[dict | None] = []

            def query_scored(
                self, text: str, limit: int = 5, where: dict | None = None
            ):
                self.wheres.append(where)
                if len(self.wheres) == 1:
                    return [(voice_a.id, 1.9)]  # weak -> forces a retry
                return [(voice_a.id, 0.3)]

        store = RecordingStore()
        recommendation = prepare_retrieval_recommendation(
            session, store, user.id, mesh_generator=None
        )

        assert recommendation is not None
        assert store.wheres == [{"modality": "Voice"}, None]


def test_grade_refine_stops_after_max_retries_with_no_candidates(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(
            email="empty@test.dev", password_hash=hash_password("x"), role="user"
        )
        session.add(user)
        session.commit()

        session.add_all(
            [
                Event(
                    user_id=user.id,
                    event_type="search",
                    metadata_json={"query": "a b c d e"},
                ),
                Event(
                    user_id=user.id,
                    event_type="search",
                    metadata_json={"query": "f g h"},
                ),
                Event(
                    user_id=user.id,
                    event_type="search",
                    metadata_json={"query": "i j k"},
                ),
            ]
        )
        session.commit()

        class EmptyVectorStore:
            def __init__(self) -> None:
                self.calls = 0

            def query_scored(
                self, text: str, limit: int = 5, where: dict | None = None
            ):
                self.calls += 1
                return []

        empty_store = EmptyVectorStore()
        recommendation = prepare_retrieval_recommendation(
            session, empty_store, user.id, mesh_generator=None
        )

        # Initial attempt + MAX_RETRIES(=2) retries, then give up without storing anything.
        assert empty_store.calls == 3
        assert recommendation is None


def _model(id, title, modality, latency_ms=None, use_case_tags=None, description="d"):
    return Model(
        id=id,
        title=title,
        modality=modality,
        provider="Test",
        price="$0",
        latency_ms=latency_ms,
        description=description,
        use_case_tags=use_case_tags or [],
    )


def test_contextual_reason_prefers_latency_comparison_over_compared_models() -> None:
    candidate = _model(1, "Fast Voice", "Voice", latency_ms=100)
    slower_compared = _model(2, "Slow Voice A", "Voice", latency_ms=300)
    evidence = [
        {
            "action": "compared",
            "label": "Slow Voice A",
            "model": slower_compared,
            "created_at": datetime.utcnow(),
        },
    ]
    assert (
        contextual_reason(candidate, 0.5, False, evidence)
        == "beats Slow Voice A on latency"
    )


def test_contextual_reason_matches_search_term_to_use_case_tag() -> None:
    candidate = _model(1, "Multilingual TTS", "Voice", use_case_tags=["multilingual"])
    evidence = [
        {
            "action": "searched",
            "label": '"multilingual"',
            "model": None,
            "created_at": datetime.utcnow(),
        },
    ]
    assert (
        contextual_reason(candidate, 0.5, False, evidence)
        == 'matches your "multilingual" search'
    )


def test_contextual_reason_falls_back_to_distance_reason() -> None:
    candidate = _model(1, "Plain Model", "LLM")
    assert (
        contextual_reason(candidate, 0.5, False, [])
        == "Strong match to your recent activity"
    )
    assert (
        contextual_reason(candidate, 0.5, True, [])
        == "Matched after broadening your activity signal"
    )


def test_contextual_reason_ignores_cross_modality_latency_and_unset_latency() -> None:
    # A faster model in a different modality must never be used as a latency comparison —
    # ms are only comparable within the same modality (e.g. Voice vs Voice).
    candidate = _model(1, "Image Gen", "Image")
    unrelated = _model(2, "Fast Voice", "Voice", latency_ms=50)
    evidence = [
        {
            "action": "compared",
            "label": "Fast Voice",
            "model": unrelated,
            "created_at": datetime.utcnow(),
        },
    ]
    assert (
        contextual_reason(candidate, 0.5, False, evidence)
        == "Strong match to your recent activity"
    )
