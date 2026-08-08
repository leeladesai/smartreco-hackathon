import csv
import io
import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Model
from app.schemas import ModelCreate
from app.services.catalog import create_model
from app.vector import ModelVectorStore


class CatalogParseError(ValueError):
    """The uploaded file itself couldn't be read (bad encoding, malformed JSON, no CSV
    header, empty/oversized) — distinct from a single row failing validation, which is
    reported per-row in import_catalog_rows instead of aborting the whole import.
    """


# A few hundred rows is already a large catalog for this app; caps the per-row loop
# (and the Chroma upsert calls it triggers) at something a single admin request can
# process synchronously without a background job.
MAX_BULK_IMPORT_ROWS = 500

_ROW_FIELDS = (
    "title",
    "provider",
    "modality",
    "price",
    "description",
    "story",
    "context_window",
    "source_url",
)


def _split_tags(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    for sep in (";", "|"):
        if sep in text:
            return [tag.strip() for tag in text.split(sep) if tag.strip()]
    # No semicolon/pipe present — fall back to comma-splitting for a single-tag CSV
    # cell or a JSON source that already used commas.
    return [tag.strip() for tag in text.split(",") if tag.strip()]


def _coerce_row(raw: dict) -> dict:
    """Normalizes one raw row into the shape ModelCreate expects. CSV cells always
    arrive as strings (or missing); JSON rows may already be correctly typed."""
    row = {str(key).strip().lower(): value for key, value in raw.items() if key}
    coerced: dict = {}
    for field in _ROW_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        if value == "":
            continue
        coerced[field] = value

    tags = row.get("use_case_tags")
    if isinstance(tags, list):
        coerced["use_case_tags"] = [
            str(tag).strip() for tag in tags if str(tag).strip()
        ]
    elif isinstance(tags, str) and tags.strip():
        coerced["use_case_tags"] = _split_tags(tags)

    latency = row.get("latency_ms")
    if isinstance(latency, str):
        latency = latency.strip()
    if latency not in (None, ""):
        coerced["latency_ms"] = int(latency)

    return coerced


def parse_catalog_file(filename: str, content: bytes) -> list[dict]:
    """Accepts a CSV or JSON catalog file and returns a list of raw row dicts, not yet
    validated against ModelCreate (see import_catalog_rows for that). JSON may be a
    bare array of model objects, or {"models": [...]} — the same shape
    scripts/expand_catalog_via_mesh.py already produces.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogParseError("File must be UTF-8 encoded text.") from exc

    if (filename or "").lower().endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CatalogParseError(f"Invalid JSON: {exc}") from exc
        if isinstance(data, dict):
            data = data.get("models")
        if not isinstance(data, list):
            raise CatalogParseError(
                'Expected a JSON array of models, or {"models": [...]}.'
            )
        rows = [row for row in data if isinstance(row, dict)]
    else:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise CatalogParseError("CSV file has no header row.")
        rows = list(reader)

    if not rows:
        raise CatalogParseError("No rows found in the uploaded file.")
    if len(rows) > MAX_BULK_IMPORT_ROWS:
        raise CatalogParseError(f"Too many rows (max {MAX_BULK_IMPORT_ROWS}).")
    return rows


def import_catalog_rows(
    session: Session, vector_store: ModelVectorStore, raw_rows: list[dict]
) -> list[dict]:
    """Validates and inserts each row independently — reuses catalog.create_model so a
    bulk import writes through the exact same DB+vector-store path (and the same
    resiliency around a failed Chroma upsert) as the single-model admin API. One bad
    row never aborts the rest of the batch, mirroring
    scripts/expand_catalog_via_mesh.py's per-row validate/dedupe/insert pattern. Each
    result dict is `{row, title, status, errors}` with status one of "inserted",
    "skipped_duplicate", "invalid".
    """
    results = []
    for index, raw in enumerate(raw_rows, start=1):
        fallback_title = str(raw.get("title") or raw.get("Title") or "").strip() or None
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

        existing = session.scalars(
            select(Model).where(Model.title.ilike(payload.title))
        ).first()
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

        try:
            create_model(session, vector_store, payload)
        except (
            Exception
        ) as exc:  # noqa: BLE001 — one row's failure must not abort the batch
            results.append(
                {
                    "row": index,
                    "title": payload.title,
                    "status": "invalid",
                    "errors": [f"Could not save: {exc}"],
                }
            )
            continue

        results.append(
            {"row": index, "title": payload.title, "status": "inserted", "errors": []}
        )
    return results
