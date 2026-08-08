import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import hash_password

# configure_langsmith (app/services/tracing.py) mutates these process-global env vars
# with no cleanup — a test that enables tracing would otherwise leak it into every test
# that runs after it in the same pytest process, regardless of that test's own Settings.
# tests/test_handshake.py intentionally imports the real app.asgi singleton (built from
# real .env settings), and that import happens during pytest's *collection* phase —
# before any test or fixture has run — so a per-test "snapshot before, restore after"
# fixture isn't enough: the very first test would already see a polluted "before" state.
# Capturing the snapshot here, at conftest's own import time, is the earliest point that
# is still guaranteed to run before any test module gets imported.
_LANGSMITH_ENV_VARS = (
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_PROJECT",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
)
_PRISTINE_LANGSMITH_ENV = {key: os.environ.get(key) for key in _LANGSMITH_ENV_VARS}


def _restore_pristine_langsmith_env() -> None:
    for key, value in _PRISTINE_LANGSMITH_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _isolate_langsmith_env() -> Iterator[None]:
    _restore_pristine_langsmith_env()
    try:
        yield
    finally:
        _restore_pristine_langsmith_env()


@pytest.fixture()
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
        secret_key="test-secret",
        mesh_api_key=None,
        # Tests must never depend on whatever's in the developer's local .env — a real
        # LANGSMITH_API_KEY there would otherwise make every traced pipeline run in the
        # suite fire real network calls to LangSmith (see _isolate_langsmith_env above).
        langsmith_api_key=None,
    )
    test_app = create_app(settings)
    with test_app.state.session_factory() as session:
        session.add(
            User(
                email="curator@test.dev",
                password_hash=hash_password("password123"),
                role="admin",
            )
        )
        session.commit()
    with TestClient(test_app) as test_client:
        yield test_client
