from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


def _add_columns_if_missing(engine, inspector, table: str, additions: dict) -> None:
    existing = {col["name"] for col in inspector.get_columns(table)}
    with engine.begin() as conn:
        for column, column_type in additions.items():
            if column not in existing:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
                )


def _add_missing_columns(engine) -> None:
    """`create_all` only creates missing tables, not missing columns on tables that
    already exist. There's no Alembic in this MVP, so patch columns added after a
    table's first deploy with a plain idempotent ALTER TABLE (SQLite/Postgres both
    support this syntax)."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "models" in table_names:
        _add_columns_if_missing(engine, inspector, "models", {"story": "TEXT"})

    if "recommendations" in table_names:
        _add_columns_if_missing(
            engine,
            inspector,
            "recommendations",
            {
                "mesh_latency_ms": "FLOAT",
                "mesh_prompt_tokens": "INTEGER",
                "mesh_completion_tokens": "INTEGER",
                "mesh_cost_usd": "FLOAT",
            },
        )

    if "users" in table_names:
        _add_columns_if_missing(
            engine, inspector, "users", {"telegram_chat_id": "VARCHAR(120)"}
        )


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
