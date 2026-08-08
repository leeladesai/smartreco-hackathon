import pytest

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, Recommendation, User
from app.security import hash_password
from app.services.digest import (
    EmailNotifier,
    LoggingNotifier,
    TelegramNotifier,
    build_notifier,
    run_digest,
)


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
    )
    return build_session_factory(settings)


class NullVectorStore:
    def query_scored(self, text: str, limit: int = 5, where: dict | None = None):
        return []


def test_build_notifier_prefers_email_then_telegram_then_logging() -> None:
    assert isinstance(
        build_notifier(Settings(smtp_host="smtp.test", smtp_from_email="a@test.dev")),
        EmailNotifier,
    )
    assert isinstance(
        build_notifier(Settings(telegram_bot_token="token", telegram_chat_id="chat")),
        TelegramNotifier,
    )
    assert isinstance(build_notifier(Settings()), LoggingNotifier)


def test_telegram_notifier_prefers_users_own_chat_id(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["chat_id"] = json["chat_id"]
        return FakeResponse()

    import app.services.digest as digest_module

    monkeypatch.setattr(digest_module.httpx, "post", fake_post)
    notifier = TelegramNotifier(bot_token="token", fallback_chat_id="shared-chat")
    user = User(id=1, email="x@test.dev", role="user", telegram_chat_id="personal-chat")
    recommendation = Recommendation(
        user_id=1,
        model_ids=[],
        behavior_summary="s",
        activity_hash="h",
        trigger_reason="event_threshold",
        narrative="hi",
    )
    notifier.send(user, recommendation)
    assert captured["chat_id"] == "personal-chat"


def test_telegram_notifier_falls_back_to_shared_chat_id(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        captured["chat_id"] = json["chat_id"]
        return FakeResponse()

    import app.services.digest as digest_module

    monkeypatch.setattr(digest_module.httpx, "post", fake_post)
    notifier = TelegramNotifier(bot_token="token", fallback_chat_id="shared-chat")
    user = User(id=1, email="x@test.dev", role="user", telegram_chat_id=None)
    recommendation = Recommendation(
        user_id=1,
        model_ids=[],
        behavior_summary="s",
        activity_hash="h",
        trigger_reason="event_threshold",
        narrative="hi",
    )
    notifier.send(user, recommendation)
    assert captured["chat_id"] == "shared-chat"


def test_telegram_notifier_raises_without_any_chat_id() -> None:
    notifier = TelegramNotifier(bot_token="token", fallback_chat_id=None)
    user = User(id=1, email="x@test.dev", role="user", telegram_chat_id=None)
    recommendation = Recommendation(
        user_id=1,
        model_ids=[],
        behavior_summary="s",
        activity_hash="h",
        trigger_reason="event_threshold",
        narrative="hi",
    )
    with pytest.raises(ValueError):
        notifier.send(user, recommendation)


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[User, Recommendation]] = []

    def send(self, user: User, recommendation: Recommendation) -> None:
        self.sent.append((user, recommendation))


def test_run_digest_sends_latest_recommendation_and_skips_users_without_one(
    tmp_path,
) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        with_history = User(
            email="with-history@test.dev", password_hash=hash_password("x"), role="user"
        )
        no_history = User(
            email="no-history@test.dev", password_hash=hash_password("x"), role="user"
        )
        session.add_all([with_history, no_history])
        session.commit()
        session.add(
            Event(
                user_id=with_history.id,
                event_type="search",
                metadata_json={"query": "voice"},
            )
        )
        session.commit()

    notifier = RecordingNotifier()
    summary = run_digest(
        session_factory, NullVectorStore(), mesh_generator=None, notifier=notifier
    )

    # No candidates in the empty vector store, so neither user ever gets a stored
    # Recommendation — digest should skip both rather than error or fabricate one.
    assert summary == {"sent": 0, "skipped": 2}
    assert notifier.sent == []


def test_run_digest_delivers_existing_recommendation_without_new_events(
    tmp_path,
) -> None:
    """A user with a stable recommendation (nothing new since last run) should still get
    today's digest — DLV-3 sends the latest recommendation, not only fresh ones."""
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(
            email="stable@test.dev", password_hash=hash_password("x"), role="user"
        )
        session.add(user)
        session.commit()
        session.add(
            Recommendation(
                user_id=user.id,
                narrative="You'll like this.",
                model_ids=[],
                behavior_summary="prior activity",
                activity_hash="deadbeef",
                trigger_reason="event_threshold",
            )
        )
        session.commit()

    notifier = RecordingNotifier()
    summary = run_digest(
        session_factory, NullVectorStore(), mesh_generator=None, notifier=notifier
    )

    assert summary == {"sent": 1, "skipped": 0}
    assert len(notifier.sent) == 1
    sent_user, sent_recommendation = notifier.sent[0]
    assert sent_user.email == "stable@test.dev"
    assert sent_recommendation.narrative == "You'll like this."


def test_run_digest_counts_delivery_failure_as_skipped(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        user = User(
            email="broken@test.dev", password_hash=hash_password("x"), role="user"
        )
        session.add(user)
        session.commit()
        session.add(
            Recommendation(
                user_id=user.id,
                narrative="hi",
                model_ids=[],
                behavior_summary="s",
                activity_hash="h",
                trigger_reason="event_threshold",
            )
        )
        session.commit()

    class FailingNotifier:
        def send(self, user: User, recommendation: Recommendation) -> None:
            raise RuntimeError("smtp down")

    summary = run_digest(
        session_factory,
        NullVectorStore(),
        mesh_generator=None,
        notifier=FailingNotifier(),
    )
    assert summary == {"sent": 0, "skipped": 1}
