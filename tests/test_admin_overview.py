from datetime import datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, Recommendation, Tenant, User
from app.security import create_session_token, hash_password
from app.services.admin_overview import (
    event_type_counts,
    feedback_sentiment,
    recent_activity,
    usage_totals,
)


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


def test_usage_totals_counts_generated_recommendations_only(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        user = User(
            tenant_id=tenant.id,
            email="u@test.dev",
            password_hash=hash_password("x"),
            role="user",
        )
        model = Model(
            tenant_id=tenant.id,
            title="M1",
            provider="P",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add_all([user, model])
        session.commit()
        session.add_all(
            [
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="page_view",
                    metadata_json={},
                ),
                # Generated (has a narrative) — counts.
                Recommendation(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    narrative="hi",
                    model_ids=[],
                    behavior_summary="s",
                    activity_hash="h1",
                    trigger_reason="event_threshold",
                ),
                # Retrieval-only (no narrative, e.g. Mesh unset) — must not count as
                # "generated".
                Recommendation(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    narrative=None,
                    model_ids=[],
                    behavior_summary="s",
                    activity_hash="h2",
                    trigger_reason="event_threshold",
                ),
            ]
        )
        session.commit()

        totals = usage_totals(session, tenant.id)
        assert totals == {"users": 1, "models": 1, "events": 1, "recommendations": 1}


def test_event_type_counts_groups_by_type(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        user = User(
            tenant_id=tenant.id,
            email="u@test.dev",
            password_hash=hash_password("x"),
            role="user",
        )
        session.add(user)
        session.commit()
        session.add_all(
            [
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="page_view",
                    metadata_json={},
                ),
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="page_view",
                    metadata_json={},
                ),
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="search",
                    metadata_json={},
                ),
            ]
        )
        session.commit()

        assert event_type_counts(session, tenant.id) == {"page_view": 2, "search": 1}


def test_feedback_sentiment_counts_up_and_down_ignoring_other_events(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        user = User(
            tenant_id=tenant.id,
            email="u@test.dev",
            password_hash=hash_password("x"),
            role="user",
        )
        session.add(user)
        session.commit()
        session.add_all(
            [
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="recommendation_feedback",
                    metadata_json={"rating": "up"},
                ),
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="recommendation_feedback",
                    metadata_json={"rating": "up"},
                ),
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="recommendation_feedback",
                    metadata_json={"rating": "down"},
                ),
                # Not feedback — must not pollute the count.
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="model_view",
                    metadata_json={},
                ),
            ]
        )
        session.commit()

        assert feedback_sentiment(session, tenant.id) == {"up": 2, "down": 1}


def test_recent_activity_includes_user_email_newest_first(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        user_a = User(
            tenant_id=tenant.id,
            email="a@test.dev",
            password_hash=hash_password("x"),
            role="user",
        )
        user_b = User(
            tenant_id=tenant.id,
            email="b@test.dev",
            password_hash=hash_password("x"),
            role="user",
        )
        session.add_all([user_a, user_b])
        session.commit()
        session.add_all(
            [
                Event(
                    tenant_id=tenant.id,
                    user_id=user_a.id,
                    event_type="page_view",
                    metadata_json={},
                    created_at=datetime(2026, 8, 8, 12, 0, 0),
                ),
                Event(
                    tenant_id=tenant.id,
                    user_id=user_b.id,
                    event_type="search",
                    metadata_json={"query": "voice"},
                    created_at=datetime(2026, 8, 8, 12, 5, 0),
                ),
            ]
        )
        session.commit()

        events, has_more = recent_activity(session, tenant.id, limit=10)
        assert [e["user_email"] for e in events] == ["b@test.dev", "a@test.dev"]
        assert events[0]["event_type"] == "search"
        assert events[0]["metadata"] == {"query": "voice"}
        assert has_more is False


def test_recent_activity_respects_limit(tmp_path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        tenant = _make_tenant(session)
        user = User(
            tenant_id=tenant.id,
            email="u@test.dev",
            password_hash=hash_password("x"),
            role="user",
        )
        session.add(user)
        session.commit()
        session.add_all(
            [
                Event(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    event_type="page_view",
                    metadata_json={},
                )
                for _ in range(5)
            ]
        )
        session.commit()

        events, has_more = recent_activity(session, tenant.id, limit=2)
        assert len(events) == 2
        assert has_more is True


def _make_non_admin(client: TestClient, email: str) -> User:
    """No self-registration path remains for non-admin accounts (the AI-engineer
    login/register surface was removed — docs/design/09-Platform-Pivot-Decision.md);
    create one directly and mint its session cookie the way login used to."""
    with client.app.state.session_factory() as session:
        user = User(
            tenant_id=1,
            email=email,
            password_hash=hash_password("password123"),
            role="user",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_session_token(user, client.app.state.settings)
    client.cookies.set(client.app.state.settings.session_cookie_name, token)
    return user


def test_admin_overview_endpoint_requires_admin(client: TestClient) -> None:
    _make_non_admin(client, "notadmin@test.dev")
    response = client.get("/api/admin/overview")
    assert response.status_code == 403

    activity_response = client.get("/api/admin/overview/activity")
    assert activity_response.status_code == 403


def test_admin_overview_endpoint_returns_real_aggregates(client: TestClient) -> None:
    user = _make_non_admin(client, "overview-user@test.dev")
    with client.app.state.session_factory() as session:
        session.add(
            Event(
                tenant_id=1,
                user_id=user.id,
                event_type="search",
                metadata_json={"query": "voice"},
            )
        )
        session.commit()

    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    response = client.get("/api/admin/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["users"] >= 1
    assert body["totals"]["events"] >= 1
    assert "search" in body["event_type_counts"]

    activity_response = client.get("/api/admin/overview/activity")
    assert activity_response.status_code == 200
    events = activity_response.json()["events"]
    assert any(e["user_email"] == "overview-user@test.dev" for e in events)


def test_admin_page_at_root_serves_overview_and_models_moved_to_subpath(
    client: TestClient,
) -> None:
    client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    overview = client.get("/admin")
    assert overview.status_code == 200
    assert "overview-totals" in overview.text

    models_page = client.get("/admin/models")
    assert models_page.status_code == 200
    assert 'id="admin-model-table"' in models_page.text
