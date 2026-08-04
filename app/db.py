from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    engine = create_engine(settings.database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def session_dependency(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
