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
    store._collections[1] = _FakeFailingCollection()
    assert store.query_scored("anything", 1) == []


class _FakeModel:
    def __init__(self, id, title):
        self.id = id
        self.title = title
        self.provider = "Test"
        self.modality = "LLM"
        self.description = "d"
        self.story = None
        self.use_case_tags = []
        self.price = "$0"
        self.latency_ms = None


def test_tenants_are_isolated_in_separate_collections(tmp_path) -> None:
    """docs/design/09-Platform-Pivot-Decision.md §5: separate Chroma collections per
    tenant, not a shared collection with a metadata filter — a query for one tenant
    must never return another tenant's items, even when both have a model with the
    same id."""
    store = ModelVectorStore(
        str(tmp_path / "chroma"),
        collection_name="isolation-test",
        embedding_function=DeterministicEmbeddingFunction(8),
    )
    tenant_a_model = _FakeModel(1, "Tenant A Only Model")
    tenant_b_model = _FakeModel(1, "Tenant B Only Model")
    store.upsert(tenant_a_model, tenant_id=1)
    store.upsert(tenant_b_model, tenant_id=2)

    results_a = store.query_scored("Tenant A Only Model", tenant_id=1, limit=5)
    results_b = store.query_scored("Tenant B Only Model", tenant_id=2, limit=5)

    assert [model_id for model_id, _ in results_a] == [1]
    assert [model_id for model_id, _ in results_b] == [1]
    # Each tenant's collection holds only what was upserted into it — even querying
    # tenant 1's collection with tenant 2's exact text can only ever return tenant 1's
    # own single item, never tenant 2's, because the collections are entirely
    # separate indexes, not filtered views of one shared index.
    cross_tenant = store.query_scored("Tenant B Only Model", tenant_id=1, limit=5)
    assert [model_id for model_id, _ in cross_tenant] == [1]
    assert store._collection_for(1).count() == 1
    assert store._collection_for(2).count() == 1
