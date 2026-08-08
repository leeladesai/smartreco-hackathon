from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


def _add_missing_columns(engine) -> None:
    """`create_all` only creates missing tables, not missing columns on tables that
    already exist. There's no Alembic in this MVP, so patch columns added after a
    table's first deploy with a plain idempotent ALTER TABLE (SQLite/Postgres both
    support this syntax)."""
    inspector = inspect(engine)
    if "models" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("models")}
    if "story" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE models ADD COLUMN story TEXT"))


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    engine = create_engine(settings.database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def session_dependency(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
