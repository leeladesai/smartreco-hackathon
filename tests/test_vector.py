from types import SimpleNamespace

from app.config import Settings
from app.vector import (
    DeterministicEmbeddingFunction,
    MeshEmbeddingFunction,
    ModelVectorStore,
    build_embedding_function,
)


def test_build_embedding_function_falls_back_without_mesh_key() -> None:
    settings = Settings(mesh_api_key=None)
    embedding_function = build_embedding_function(settings)
    assert isinstance(embedding_function, DeterministicEmbeddingFunction)


def test_build_embedding_function_uses_mesh_when_configured() -> None:
    settings = Settings(
        mesh_api_key="fake-key", mesh_embedding_model="fake/embed-model"
    )
    embedding_function = build_embedding_function(settings)
    assert isinstance(embedding_function, MeshEmbeddingFunction)
    assert embedding_function.model == "fake/embed-model"


def test_mesh_embedding_function_calls_client_and_preserves_order() -> None:
    captured = {}

    class FakeEmbeddings:
        def create(self, model, input):
            captured["model"] = model
            captured["input"] = input
            return SimpleNamespace(
                data=[
                    SimpleNamespace(embedding=[float(i)] * 3) for i in range(len(input))
                ]
            )

    fake_client = SimpleNamespace(embeddings=FakeEmbeddings())
    embedding_function = MeshEmbeddingFunction(fake_client, "fake/embed-model")

    result = embedding_function(["first text", "second text"])

    assert captured["model"] == "fake/embed-model"
    assert captured["input"] == ["first text", "second text"]
    assert result == [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]


class _FakeFailingCollection:
    """Chroma's real Collection is a pydantic model that rejects ad-hoc attribute
    patching, so this stands in for it wholesale rather than patching methods onto
    the real one."""

    def count(self) -> int:
        return 1

    def query(self, **kwargs):
        raise RuntimeError("Mesh embedding call failed")


def test_query_scored_degrades_gracefully_on_embedding_failure(tmp_path) -> None:
    """Regression test: retrieval is core to every recommendation (unlike narrative
    generation, which already degrades gracefully) — a transient embedding failure
    must return no candidates, not crash the whole background pipeline run."""
    store = ModelVectorStore(
        str(tmp_path / "chroma"),
        collection_name="test-failing",
        embedding_function=DeterministicEmbeddingFunction(8),
    )
    store.collection = _FakeFailingCollection()
    assert store.query_scored("anything") == []
