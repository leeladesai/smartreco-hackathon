"""Catalog ingestion adapters beyond manual entry (CAT-1..5) and the plain file
bulk-upload (app/services/catalog_import.py): a feed/API pull (ING-1) and a
DOM-scrape with preview/confirm (ING-2), on top of the existing manual adapter.

Both adapters funnel through catalog_import.import_catalog_rows / catalog.create_model
so a row ingested this way gets the exact same validation, dedupe-by-title, and
vector-store sync path as a manually entered one — only `ingestion_adapter` and
`review_status` differ per-row.
"""

import json
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Model, Tenant
from app.schemas import ModelCreate
from app.services.catalog import create_model
from app.services.catalog_import import (
    CatalogParseError,
    _coerce_row,
    import_catalog_rows,
    parse_catalog_file,
)
from app.vector import ModelVectorStore

FETCH_TIMEOUT_SECONDS = 10.0


class FeedSyncError(ValueError):
    """The feed URL couldn't be fetched or parsed. Existing feed-sourced rows are
    flagged `sync_stale` rather than removed (ING-5: serve last-known-good)."""


class ScrapeError(ValueError):
    """The page couldn't be fetched, or no Product markup/matching selector was
    found — nothing is persisted in either case (scrape/preview never writes)."""


def configure_feed(
    session: Session, tenant: Tenant, feed_url: str, auth_token: str | None = None
) -> Tenant:
    tenant.feed_url = feed_url
    tenant.feed_auth_token = auth_token
    session.commit()
    session.refresh(tenant)
    return tenant


def _set_feed_rows_stale(session: Session, tenant_id: int, stale: bool) -> None:
    session.execute(
        update(Model)
        .where(Model.tenant_id == tenant_id, Model.ingestion_adapter == "feed")
        .values(sync_stale=stale)
    )
    session.commit()


def sync_feed(
    session: Session, vector_store: ModelVectorStore, tenant: Tenant
) -> list[dict]:
    """ING-1: fetches `tenant.feed_url`, parses it with the same CSV/JSON reader the
    manual bulk-upload endpoint uses, and imports every row exactly like a manual
    bulk-upload would — just tagged `ingestion_adapter="feed"` with `last_synced_at`
    stamped now. On any fetch/parse failure, existing feed-sourced rows for this
    tenant are marked `sync_stale=True` (and left in place, still serving) rather than
    raising past the caller silently — callers surface `FeedSyncError` to the admin.
    """
    if not tenant.feed_url:
        raise FeedSyncError("No feed URL configured for this tenant.")

    headers = (
        {"Authorization": f"Bearer {tenant.feed_auth_token}"}
        if tenant.feed_auth_token
        else {}
    )
    try:
        response = httpx.get(
            tenant.feed_url, headers=headers, timeout=FETCH_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        raw_rows = parse_catalog_file("feed.json", response.content)
    except httpx.HTTPError as exc:
        _set_feed_rows_stale(session, tenant.id, True)
        raise FeedSyncError(f"Could not fetch feed: {exc}") from exc
    except CatalogParseError as exc:
        _set_feed_rows_stale(session, tenant.id, True)
        raise FeedSyncError(str(exc)) from exc

    results = import_catalog_rows(
        session,
        vector_store,
        tenant.id,
        raw_rows,
        ingestion_adapter="feed",
        last_synced_at=datetime.now(timezone.utc),
    )
    _set_feed_rows_stale(session, tenant.id, False)
    return results


def _extract_json_ld_products(soup: BeautifulSoup) -> list[dict]:
    """Prefers schema.org `Product` markup — the highest-confidence signal a page
    actually describes a catalog item, and structured enough to map straight onto
    ModelCreate's fields without guessing at page layout."""
    rows: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for entry in candidates:
            if isinstance(entry, dict) and entry.get("@graph"):
                candidates = candidates + entry["@graph"]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            if entry.get("@type") not in ("Product", "Offer"):
                continue
            offers = entry.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            offers = offers if isinstance(offers, dict) else {}
            brand = entry.get("brand")
            brand_name = (brand.get("name") if isinstance(brand, dict) else brand) or ""
            price = offers.get("price")
            currency = offers.get("priceCurrency", "")
            row = {
                "title": entry.get("name"),
                "description": entry.get("description") or entry.get("name") or "",
                "provider": brand_name,
                "price": f"{currency} {price}".strip() if price else "",
                "source_url": entry.get("url"),
                "modality": entry.get("category") or "",
            }
            if row["title"]:
                rows.append(row)
    return rows


def _extract_via_selectors(
    soup: BeautifulSoup, selectors: dict[str, str]
) -> list[dict]:
    """Fallback for pages with no schema.org markup: a tenant-configured CSS
    selector per field, applied to a single-item page (each selector's first match)."""
    row: dict = {}
    for field, selector in selectors.items():
        element = soup.select_one(selector)
        if element is not None:
            row[field] = element.get_text(strip=True)
    return [row] if row.get("title") else []


def _default_missing_fields(row: dict) -> dict:
    row = dict(row)
    row.setdefault("modality", "general")
    row["modality"] = row["modality"] or "general"
    row.setdefault("provider", "")
    row["provider"] = row["provider"] or "Unknown"
    row.setdefault("price", "")
    row["price"] = row["price"] or "Not listed"
    return row


def scrape_preview(url: str, selectors: dict[str, str] | None = None) -> dict:
    """ING-2: fetches `url` and extracts candidate catalog rows without persisting
    anything — the admin reviews these before `scrape_confirm` writes them. Returns
    `{"rows": [...], "markup_type": "json-ld" | "css-selector"}`.
    """
    try:
        response = httpx.get(url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ScrapeError(f"Could not fetch page: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    rows = _extract_json_ld_products(soup)
    markup_type = "json-ld"
    if not rows and selectors:
        rows = _extract_via_selectors(soup, selectors)
        markup_type = "css-selector"
    if not rows:
        raise ScrapeError(
            "No schema.org Product markup found, and no matching CSS selectors "
            "configured for this page."
        )
    rows = [_default_missing_fields(row) for row in rows]
    return {"rows": rows, "markup_type": markup_type}


def scrape_confirm(
    session: Session,
    vector_store: ModelVectorStore,
    tenant_id: int,
    source_url: str,
    markup_type: str,
    rows: list[dict],
) -> list[dict]:
    """Persists a previewed scrape result with `review_status="pending_review"` —
    nothing here is eligible for retrieval until an admin calls
    `catalog.approve_model` (via POST /api/admin/catalog/{id}/approve)."""
    results = []
    for index, raw in enumerate(rows, start=1):
        fallback_title = str(raw.get("title") or "").strip() or None
        try:
            coerced = _coerce_row(raw)
        except (TypeError, ValueError) as exc:
            results.append(
                {
                    "row": index,
                    "title": fallback_title,
                    "status": "invalid",
                    "errors": [str(exc)],
                }
            )
            continue
        try:
            payload = ModelCreate(**coerced)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            ]
            results.append(
                {
                    "row": index,
                    "title": fallback_title,
                    "status": "invalid",
                    "errors": errors,
                }
            )
            continue

        existing = session.scalar(
            select(Model).where(
                Model.title.ilike(payload.title), Model.tenant_id == tenant_id
            )
        )
        if existing:
            results.append(
                {
                    "row": index,
                    "title": payload.title,
                    "status": "skipped_duplicate",
                    "errors": [],
                }
            )
            continue

        model = create_model(
            session,
            vector_store,
            tenant_id,
            payload,
            ingestion_adapter="scrape",
            review_status="pending_review",
            last_synced_at=datetime.now(timezone.utc),
            ingestion_meta={"source_url": source_url, "markup_type": markup_type},
        )
        results.append(
            {
                "row": index,
                "title": model.title,
                "status": "pending_review",
                "errors": [],
                "model_id": model.id,
            }
        )
    return results


def ingestion_status(session: Session, tenant_id: int) -> dict:
    """GET /api/admin/ingestion/status: per-adapter `last_synced_at`/`sync_stale`,
    folded into the onboarding-readiness check (M2, when it lands)."""
    status: dict[str, dict] = {}
    for adapter in ("feed", "scrape"):
        rows = session.scalars(
            select(Model).where(
                Model.tenant_id == tenant_id, Model.ingestion_adapter == adapter
            )
        ).all()
        last_synced = max(
            (row.last_synced_at for row in rows if row.last_synced_at is not None),
            default=None,
        )
        status[adapter] = {
            "count": len(rows),
            "last_synced_at": last_synced,
            "sync_stale": any(row.sync_stale for row in rows),
            "pending_review": sum(
                1 for row in rows if row.review_status == "pending_review"
            ),
        }
    return status
