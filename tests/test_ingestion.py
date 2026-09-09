"""M4 (catalog ingestion adapters): feed/API pull (ING-1) and DOM-scrape with
preview/confirm (ING-2), both layered on top of the existing manual-entry adapter
(CAT-1..5) via app/services/ingestion.py. Retrieval-exclusion for a "pending_review"
scrape row is proven by checking it never lands in the vector store rather than by
inspecting agent_graph internals — that's the actual mechanism (see
app/services/catalog.py::create_model).
"""

import httpx

import app.services.ingestion as ingestion_module
from app.models import Model, Tenant
from app.services.ingestion import (
    FeedSyncError,
    ScrapeError,
    configure_feed,
    scrape_confirm,
    scrape_preview,
    sync_feed,
)


class _FakeResponse:
    def __init__(self, *, content: bytes = b"", text: str = "", status_code: int = 200):
        self.content = content
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError(f"status {self.status_code}")


FEED_JSON = b"""
{"models": [
    {"title": "Feed Model One", "provider": "Feed Co", "modality": "LLM",
     "price": "$1", "description": "From the feed."}
]}
"""

PRODUCT_PAGE_HTML = """
<html><head>
<script type="application/ld+json">
{"@type": "Product", "name": "Scraped Widget", "description": "A widget.",
 "brand": {"name": "Acme"}, "category": "Hardware",
 "offers": {"price": "19.99", "priceCurrency": "USD"},
 "url": "https://example.com/widget"}
</script>
</head><body></body></html>
"""


def _login(client) -> None:
    login = client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    assert login.status_code == 200


def test_feed_sync_imports_rows_tagged_and_stamped(client, monkeypatch) -> None:
    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(content=FEED_JSON)

    monkeypatch.setattr(ingestion_module.httpx, "get", fake_get)

    with client.app.state.session_factory() as session:
        tenant = session.get(Tenant, 1)
        configure_feed(session, tenant, "https://vendor.example.com/feed.json")
        rows = sync_feed(session, client.app.state.vector_store, tenant)
        assert rows[0]["status"] == "inserted"

        model = session.query(Model).filter_by(title="Feed Model One").one()
        assert model.ingestion_adapter == "feed"
        assert model.review_status == "approved"
        assert model.last_synced_at is not None
        assert model.sync_stale is False
        # Approved feed rows sync to the vector store immediately, same as manual.
        assert model.vector_synced is True


def test_feed_sync_marks_existing_rows_stale_on_failure(client, monkeypatch) -> None:
    def fake_get_ok(url, headers=None, timeout=None):
        return _FakeResponse(content=FEED_JSON)

    monkeypatch.setattr(ingestion_module.httpx, "get", fake_get_ok)

    with client.app.state.session_factory() as session:
        tenant = session.get(Tenant, 1)
        configure_feed(session, tenant, "https://vendor.example.com/feed.json")
        sync_feed(session, client.app.state.vector_store, tenant)

    def fake_get_fail(url, headers=None, timeout=None):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(ingestion_module.httpx, "get", fake_get_fail)

    with client.app.state.session_factory() as session:
        tenant = session.get(Tenant, 1)
        try:
            sync_feed(session, client.app.state.vector_store, tenant)
            assert False, "expected FeedSyncError"
        except FeedSyncError:
            pass

        model = session.query(Model).filter_by(title="Feed Model One").one()
        assert model.sync_stale is True


def test_scrape_preview_extracts_json_ld_product(client, monkeypatch) -> None:
    def fake_get(url, timeout=None, follow_redirects=True):
        return _FakeResponse(text=PRODUCT_PAGE_HTML)

    monkeypatch.setattr(ingestion_module.httpx, "get", fake_get)

    result = scrape_preview("https://shop.example.com/widget")
    assert result["markup_type"] == "json-ld"
    assert result["rows"][0]["title"] == "Scraped Widget"
    assert result["rows"][0]["provider"] == "Acme"


def test_scrape_preview_raises_when_no_markup_found(client, monkeypatch) -> None:
    def fake_get(url, timeout=None, follow_redirects=True):
        return _FakeResponse(text="<html><body>Nothing here.</body></html>")

    monkeypatch.setattr(ingestion_module.httpx, "get", fake_get)

    try:
        scrape_preview("https://shop.example.com/empty")
        assert False, "expected ScrapeError"
    except ScrapeError:
        pass


def test_scrape_confirm_creates_pending_review_row_excluded_from_vector_store(
    client,
) -> None:
    with client.app.state.session_factory() as session:
        rows = scrape_confirm(
            session,
            client.app.state.vector_store,
            1,
            "https://shop.example.com/widget",
            "json-ld",
            [
                {
                    "title": "Scraped Widget",
                    "description": "A widget.",
                    "provider": "Acme",
                    "modality": "Hardware",
                    "price": "USD 19.99",
                }
            ],
        )
        assert rows[0]["status"] == "pending_review"
        model_id = rows[0]["model_id"]
        model = session.get(Model, model_id)
        assert model.review_status == "pending_review"
        assert model.ingestion_adapter == "scrape"
        assert model.vector_synced is False

        # Not eligible for retrieval yet — the vector store never got an upsert for it.
        matches = client.app.state.vector_store.query_scored(
            "Scraped Widget Acme Hardware", 1, limit=5
        )
        assert model_id not in {mid for mid, _ in matches}


def test_admin_approve_endpoint_syncs_to_vector_store(client) -> None:
    _login(client)
    with client.app.state.session_factory() as session:
        rows = scrape_confirm(
            session,
            client.app.state.vector_store,
            1,
            "https://shop.example.com/widget",
            "json-ld",
            [
                {
                    "title": "Pending Widget",
                    "description": "Awaiting approval.",
                    "provider": "Acme",
                    "modality": "Hardware",
                    "price": "USD 9.99",
                }
            ],
        )
        model_id = rows[0]["model_id"]

    response = client.post(f"/api/admin/catalog/{model_id}/approve")
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "approved"
    assert body["vector_synced"] is True


def test_ingestion_status_reflects_feed_and_scrape_state(client, monkeypatch) -> None:
    _login(client)

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(content=FEED_JSON)

    monkeypatch.setattr(ingestion_module.httpx, "get", fake_get)

    client.post(
        "/api/admin/ingestion/feed",
        json={"feed_url": "https://vendor.example.com/feed.json"},
    )
    sync_response = client.post("/api/admin/ingestion/feed/sync")
    assert sync_response.status_code == 200

    with client.app.state.session_factory() as session:
        scrape_confirm(
            session,
            client.app.state.vector_store,
            1,
            "https://shop.example.com/widget",
            "json-ld",
            [
                {
                    "title": "Status Widget",
                    "description": "For status coverage.",
                    "provider": "Acme",
                    "modality": "Hardware",
                    "price": "USD 5.00",
                }
            ],
        )

    status = client.get("/api/admin/ingestion/status")
    assert status.status_code == 200
    body = status.json()
    assert body["feed"]["count"] == 1
    assert body["feed"]["sync_stale"] is False
    assert body["scrape"]["pending_review"] == 1


def test_non_admin_cannot_configure_feed(client) -> None:
    response = client.post(
        "/api/admin/ingestion/feed",
        json={"feed_url": "https://vendor.example.com/feed.json"},
    )
    assert response.status_code in (401, 403)


def test_ingestion_status_isolated_per_tenant(client) -> None:
    from app.models import User
    from app.security import hash_password

    with client.app.state.session_factory() as session:
        other_tenant = Tenant(name="Other Tenant")
        session.add(other_tenant)
        session.commit()
        session.refresh(other_tenant)
        session.add(
            User(
                tenant_id=other_tenant.id,
                email="other-admin@test.dev",
                password_hash=hash_password("password123"),
                role="admin",
            )
        )
        session.commit()

        scrape_confirm(
            session,
            client.app.state.vector_store,
            1,
            "https://shop.example.com/widget",
            "json-ld",
            [
                {
                    "title": "Reference Tenant Widget",
                    "description": "Belongs to tenant 1.",
                    "provider": "Acme",
                    "modality": "Hardware",
                    "price": "USD 5.00",
                }
            ],
        )

    login = client.post(
        "/api/admin/login",
        json={"email": "other-admin@test.dev", "password": "password123"},
    )
    assert login.status_code == 200
    status = client.get("/api/admin/ingestion/status")
    assert status.json()["scrape"]["pending_review"] == 0
