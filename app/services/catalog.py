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
    session: Session, vector_store: ModelVectorStore, payload: ModelCreate
) -> Model:
    model = Model(vector_synced=False)
    _apply_payload(model, payload)
    session.add(model)
    session.commit()
    session.refresh(model)
    _sync_model(session, vector_store, model)
    return model


def update_model(
    session: Session, vector_store: ModelVectorStore, model: Model, payload: ModelCreate
) -> Model:
    model.vector_synced = False
    _apply_payload(model, payload)
    session.commit()
    session.refresh(model)
    _sync_model(session, vector_store, model)
    return model


def delete_model(
    session: Session, vector_store: ModelVectorStore, model: Model
) -> None:
    vector_store.delete(model.id)
    session.delete(model)
    session.commit()


def _sync_model(session: Session, vector_store: ModelVectorStore, model: Model) -> None:
    try:
        vector_store.upsert(model)
        model.vector_synced = True
        session.commit()
    except Exception:
        session.rollback()
        persisted_model = session.get(Model, model.id)
        if persisted_model:
            persisted_model.vector_synced = False
            session.commit()
