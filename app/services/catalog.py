from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Model
from app.schemas import ModelCreate
from app.vector import ModelVectorStore


def _apply_payload(model: Model, payload: ModelCreate) -> None:
    values = payload.model_dump()
    if values["source_url"] is not None:
        values["source_url"] = str(values["source_url"])
    for field, value in values.items():
        setattr(model, field, value)


def create_model(
    session: Session,
    vector_store: ModelVectorStore,
    tenant_id: int,
    payload: ModelCreate,
    *,
    ingestion_adapter: str = "manual",
    review_status: str = "approved",
    last_synced_at: datetime | None = None,
    ingestion_meta: dict | None = None,
) -> Model:
    """`ingestion_adapter`/`review_status`/`last_synced_at`/`ingestion_meta` are set by
    the ingestion adapters (app/services/ingestion.py) — manual admin creation (the only
    caller before M4) leaves them at their defaults. A row is only pushed into the
    vector store (and therefore eligible for retrieval) once `review_status ==
    "approved"` — a "pending_review" scrape row stays out of Chroma until
    `approve_model` runs.
    """
    model = Model(
        tenant_id=tenant_id,
        vector_synced=False,
        ingestion_adapter=ingestion_adapter,
        review_status=review_status,
        last_synced_at=last_synced_at,
        ingestion_meta=ingestion_meta or {},
    )
    _apply_payload(model, payload)
    session.add(model)
    session.commit()
    session.refresh(model)
    if review_status == "approved":
        _sync_model(session, vector_store, tenant_id, model)
    return model


def approve_model(
    session: Session, vector_store: ModelVectorStore, tenant_id: int, model: Model
) -> Model:
    """ING-6: flips a "pending_review" scrape row to "approved", making it eligible
    for retrieval/vector-indexing for the first time."""
    model.review_status = "approved"
    session.commit()
    _sync_model(session, vector_store, tenant_id, model)
    return model


def update_model(
    session: Session,
    vector_store: ModelVectorStore,
    tenant_id: int,
    model: Model,
    payload: ModelCreate,
) -> Model:
    model.vector_synced = False
    _apply_payload(model, payload)
    session.commit()
    session.refresh(model)
    _sync_model(session, vector_store, tenant_id, model)
    return model


def delete_model(
    session: Session, vector_store: ModelVectorStore, tenant_id: int, model: Model
) -> None:
    vector_store.delete(model.id, tenant_id)
    session.delete(model)
    session.commit()


def _sync_model(
    session: Session, vector_store: ModelVectorStore, tenant_id: int, model: Model
) -> None:
    try:
        vector_store.upsert(model, tenant_id)
        model.vector_synced = True
        session.commit()
    except Exception:
        session.rollback()
        persisted_model = session.get(Model, model.id)
        if persisted_model:
            persisted_model.vector_synced = False
            session.commit()
