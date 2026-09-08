"""Tracker SDK phase (M3, docs/design/09-Platform-Pivot-Decision.md): tenant API-key
issuance/rotation/resolution (app/services/tenants.py) and the anonymous-visitor
ingestion endpoint POST /api/track/events (app/main.py).
"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.models import Event, Model, Recommendation, TenantApiKey
from app.services.tenants import (
    create_tenant,
    hash_api_key,
    issue_api_key,
    resolve_tenant_by_api_key,
    revoke_api_key,
    rotate_api_key,
)


def test_create_tenant_issues_a_working_key(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        tenant, raw_key = create_tenant(session, "Acme Bank")
        assert tenant.status == "onboarding"
        resolved = resolve_tenant_by_api_key(session, raw_key)
        assert resolved is not None
        assert resolved.id == tenant.id


def test_raw_key_is_never_stored(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        tenant, raw_key = create_tenant(session, "Acme Bank")
        key_row = session.query(TenantApiKey).filter_by(tenant_id=tenant.id).one()
        assert key_row.key_hash == hash_api_key(raw_key)
        assert raw_key not in key_row.key_hash


def test_resolve_tenant_by_api_key_rejects_unknown_key(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        assert resolve_tenant_by_api_key(session, "tk_live_does-not-exist") is None


def test_resolve_tenant_by_api_key_rejects_revoked_key(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        tenant, raw_key = create_tenant(session, "Acme Bank")
        key_row = session.query(TenantApiKey).filter_by(tenant_id=tenant.id).one()
        revoke_api_key(session, key_row.id)
        assert resolve_tenant_by_api_key(session, raw_key) is None


def test_rotate_api_key_keeps_old_key_valid_during_grace_period(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
        tenant, old_key = create_tenant(session, "Acme Bank")
        new_key = rotate_api_key(session, tenant)

        assert resolve_tenant_by_api_key(session, new_key) is not None
        # Old key still resolves — TEN-5's grace period, not an instant cutover.
        assert resolve_tenant_by_api_key(session, old_key) is not None

        old_key_row = (
            session.query(TenantApiKey)
            .filter_by(tenant_id=tenant.id, key_hash=hash_api_key(old_key))
            .one()
        )
        assert old_key_row.status == "grace"
        assert old_key_row.expires_at is not None


def test_resolve_tenant_by_api_key_rejects_expired_grace_key(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
        tenant, old_key = create_tenant(session, "Acme Bank")
        rotate_api_key(session, tenant)
        old_key_row = (
            session.query(TenantApiKey)
            .filter_by(tenant_id=tenant.id, key_hash=hash_api_key(old_key))
            .one()
        )
        old_key_row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()

        assert resolve_tenant_by_api_key(session, old_key) is None


def test_issue_api_key_adds_a_second_active_key(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        tenant, first_key = create_tenant(session, "Acme Bank")
        second_key = issue_api_key(session, tenant)
        assert resolve_tenant_by_api_key(session, first_key) is not None
        assert resolve_tenant_by_api_key(session, second_key) is not None


def test_track_events_accepts_a_valid_tenant_key(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        _, raw_key = create_tenant(session, "Acme Bank")

    response = client.post(
        "/api/track/events",
        json={
            "tenant_key": raw_key,
            "visitor_id": "v-1",
            "events": [{"event_type": "search", "metadata": {"query": "travel card"}}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["recommendation_triggered"] is False


def test_track_events_rejects_an_unknown_tenant_key(client: TestClient) -> None:
    response = client.post(
        "/api/track/events",
        json={
            "tenant_key": "tk_live_bogus",
            "visitor_id": "v-1",
            "events": [{"event_type": "search", "metadata": {"query": "x"}}],
        },
    )
    assert response.status_code == 401


def test_track_events_drops_a_foreign_tenants_model_id(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        tenant_a, key_a = create_tenant(session, "Tenant A")
        tenant_b, _ = create_tenant(session, "Tenant B")
        tenant_a_id = tenant_a.id
        foreign_model = Model(
            tenant_id=tenant_b.id,
            title="Tenant B Only",
            provider="P",
            modality="LLM",
            price="$0",
            description="d",
            use_case_tags=[],
        )
        session.add(foreign_model)
        session.commit()
        foreign_model_id = foreign_model.id

    response = client.post(
        "/api/track/events",
        json={
            "tenant_key": key_a,
            "visitor_id": "v-1",
            "events": [
                {
                    "event_type": "model_view",
                    "model_id": foreign_model_id,
                    "metadata": {},
                }
            ],
        },
    )
    assert response.status_code == 200

    latest = client.get(
        f"/api/recommendations/latest?tenant_key={key_a}&visitor_id=v-1"
    ).json()
    # Nothing retrieved yet either way (below trigger threshold), but the real check
    # is server-side: confirm the stored event's model_id was actually dropped.
    assert latest["status"] == "pending"
    with client.app.state.session_factory() as session:
        stored = (
            session.query(Event)
            .filter_by(tenant_id=tenant_a_id, visitor_id="v-1")
            .one()
        )
        assert stored.model_id is None


def test_track_events_triggers_pipeline_after_session_threshold(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
        tenant, raw_key = create_tenant(session, "Acme Bank")
        model = Model(
            tenant_id=tenant.id,
            title="Travel Card",
            provider="P",
            modality="LLM",
            price="$0",
            description="A travel rewards card.",
            use_case_tags=["travel"],
        )
        session.add(model)
        session.commit()
        model_id = model.id

    response = client.post(
        "/api/track/events",
        json={
            "tenant_key": raw_key,
            "visitor_id": "v-trigger",
            "events": [
                {"event_type": "search", "metadata": {"query": "travel"}},
                {"event_type": "model_view", "model_id": model_id, "metadata": {}},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["recommendation_triggered"] is True


def test_track_events_respects_tenant_rate_limit(client: TestClient) -> None:
    with client.app.state.session_factory() as session:
        tenant, raw_key = create_tenant(session, "Acme Bank")
        tenant.max_agent_runs_per_hour = 1
        session.add(
            Recommendation(
                tenant_id=tenant.id,
                visitor_id="v-other",
                model_ids=[],
                behavior_summary="",
                activity_hash="already-at-cap",
                trigger_reason="event_threshold",
            )
        )
        session.commit()

    response = client.post(
        "/api/track/events",
        json={
            "tenant_key": raw_key,
            "visitor_id": "v-new",
            "events": [
                {"event_type": "search", "metadata": {"query": "a"}},
                {"event_type": "search", "metadata": {"query": "b"}},
            ],
        },
    )
    assert response.status_code == 200
    # Would otherwise trigger (2 fresh events, new session) but the tenant is already
    # at its hourly cap (TEN-6) — a fabricated new visitor_id must not bypass it.
    assert response.json()["recommendation_triggered"] is False


def test_recommendations_latest_requires_a_valid_tenant_key(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/recommendations/latest?tenant_key=tk_live_bogus&visitor_id=v-1"
    )
    assert response.status_code == 401


def test_recommendations_latest_is_pending_with_no_activity(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
        _, raw_key = create_tenant(session, "Acme Bank")

    response = client.get(
        f"/api/recommendations/latest?tenant_key={raw_key}&visitor_id=v-none"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
