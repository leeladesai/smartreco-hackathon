import pytest

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, Recommendation, User
from app.security import hash_password
from app.services.digest import (
    EmailNotifier,
    LoggingNotifier,
    TelegramNotifier,
    _recommendation_models,
    build_notifier,
    run_digest,
)
from app.services.narrative import encode_narrative


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
    # Settings() reads the developer's real .env by default — explicitly nulling the
    # fields each case isn't testing keeps this robust regardless of what's actually
    # configured locally (same isolation rationale as conftest.py's client fixture).
    assert isinstance(
        build_notifier(Settings(smtp_host="smtp.test", smtp_from_email="a@test.dev")),
        EmailNotifier,
    )
    assert isinstance(
        build_notifier(
            Settings(
                smtp_host=None,
                smtp_from_email=None,
                telegram_bot_token="token",
                telegram_chat_id="chat",
            )
        ),
        TelegramNotifier,
    )
    assert isinstance(
        build_notifier(
            Settings(
                smtp_host=None,
                smtp_from_email=None,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
        ),
        LoggingNotifier,
    )


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
    notifier.send(user, recommendation, [])
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
    notifier.send(user, recommendation, [])
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
        notifier.send(user, recommendation, [])


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[User, Recommendation, list[dict]]] = []

    def send(
        self, user: User, recommendation: Recommendation, models: list[dict]
    ) -> None:
        self.sent.append((user, recommendation, models))


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
    sent_user, sent_recommendation, _sent_models = notifier.sent[0]
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
        def send(
            self, user: User, recommendation: Recommendation, models: list[dict]
        ) -> None:
            raise RuntimeError("smtp down")

    summary = run_digest(
        session_factory,
        NullVectorStore(),
        mesh_generator=None,
        notifier=FailingNotifier(),
    )
    assert summary == {"sent": 0, "skipped": 1}


def test_recommendation_models_resolves_title_provider_and_why_this(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        model = Model(
            title="Voice X",
            provider="Test Labs",
            modality="Voice",
            price="$1",
            description="d",
            use_case_tags=[],
        )
        session.add(model)
        session.commit()
        recommendation = Recommendation(
            user_id=1,
            model_ids=[model.id],
            retrieval_meta=[
                {"model_id": model.id, "reason": "great fit", "distance": 0.2}
            ],
            behavior_summary="s",
            activity_hash="h",
            trigger_reason="event_threshold",
        )
        session.add(recommendation)
        session.commit()

        models = _recommendation_models(session, recommendation)
        assert models == [
            {
                "title": "Voice X",
                "provider": "Test Labs",
                "modality": "Voice",
                "price": "$1",
                "why_this": "great fit",
            }
        ]


def test_recommendation_models_skips_ids_with_no_matching_row(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        recommendation = Recommendation(
            user_id=1,
            model_ids=[999],
            behavior_summary="s",
            activity_hash="h",
            trigger_reason="event_threshold",
        )
        session.add(recommendation)
        session.commit()

        assert _recommendation_models(session, recommendation) == []


class FakeSMTPServer:
    """Stands in for smtplib.SMTP as a context manager, recording what EmailNotifier
    actually sends rather than hitting a real mail server."""

    instances: list["FakeSMTPServer"] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in_as = None
        self.sent_message = None
        FakeSMTPServer.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in_as = username

    def send_message(self, message):
        self.sent_message = message


def test_email_notifier_sends_html_alternative_with_model_cards(monkeypatch) -> None:
    import app.services.digest as digest_module

    FakeSMTPServer.instances = []
    monkeypatch.setattr(digest_module.smtplib, "SMTP", FakeSMTPServer)

    notifier = EmailNotifier(
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_username="u",
        smtp_password="p",
        from_email="digest@trailmind.dev",
        app_url="https://trailmind.example/dashboard",
    )
    user = User(id=1, email="recipient@test.dev", role="user")
    recommendation = Recommendation(
        user_id=1,
        model_ids=[1],
        narrative=encode_narrative(
            "You've been comparing low-latency voice models.",
            ["ElevenLabs beats the field on latency."],
        ),
        behavior_summary="s",
        activity_hash="h",
        trigger_reason="event_threshold",
    )
    models = [
        {
            "title": "ElevenLabs Turbo v2.5",
            "provider": "ElevenLabs",
            "modality": "Voice",
            "price": "$0.001/char",
            "why_this": "beats Cartesia Sonic on latency",
        }
    ]

    notifier.send(user, recommendation, models)

    server = FakeSMTPServer.instances[-1]
    assert server.started_tls is True
    assert server.logged_in_as == "u"
    message = server.sent_message
    assert message["Subject"] == "Your TrailMind picks: 1 models based on your activity"
    assert message.is_multipart()

    html_part = message.get_body(preferencelist=("html",))
    html_content = html_part.get_content()
    assert "ElevenLabs Turbo v2.5" in html_content
    assert "beats Cartesia Sonic on latency" in html_content
    assert "https://trailmind.example/dashboard" in html_content

    plain_part = message.get_body(preferencelist=("plain",))
    assert "comparing low-latency voice models" in plain_part.get_content()


def test_email_notifier_omits_cta_link_when_app_url_unset(monkeypatch) -> None:
    import app.services.digest as digest_module

    FakeSMTPServer.instances = []
    monkeypatch.setattr(digest_module.smtplib, "SMTP", FakeSMTPServer)

    notifier = EmailNotifier(
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_username=None,
        smtp_password=None,
        from_email="digest@trailmind.dev",
    )
    user = User(id=1, email="recipient@test.dev", role="user")
    recommendation = Recommendation(
        user_id=1,
        model_ids=[],
        narrative="hi",
        behavior_summary="s",
        activity_hash="h",
        trigger_reason="event_threshold",
    )

    notifier.send(user, recommendation, [])

    server = FakeSMTPServer.instances[-1]
    assert server.logged_in_as is None  # no username/password -> login() never called
    html_content = server.sent_message.get_body(preferencelist=("html",)).get_content()
    assert "View full dashboard" not in html_content
