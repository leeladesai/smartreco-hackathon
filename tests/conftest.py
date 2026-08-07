from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import hash_password


@pytest.fixture()
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
        secret_key="test-secret",
        mesh_api_key=None,
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
