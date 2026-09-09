from types import SimpleNamespace

from app.config import Settings
from app.vector import (
    CatalogItemVectorStore,
    DeterministicEmbeddingFunction,
    MeshEmbeddingFunction,
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
    store = CatalogItemVectorStore(
        str(tmp_path / "chroma"),
        collection_name="test-failing",
        embedding_function=DeterministicEmbeddingFunction(8),
    )
    store._collections[1] = _FakeFailingCollection()
    assert store.query_scored("anything", 1) == []


class _FakeCatalogItem:
    def __init__(self, id, title):
        self.id = id
        self.title = title
        self.provider = "Test"
        self.category = "LLM"
        self.description = "d"
        self.story = None
        self.use_case_tags = []
        self.price = "$0"


def test_widgets_are_isolated_in_separate_collections(tmp_path) -> None:
    """docs/design/09-Platform-Pivot-Decision.md §5, per-widget cutover: separate
    Chroma collections per widget, not a shared collection with a metadata filter —
    a query for one widget must never return another widget's items, even when both
    have an item with the same id. Isolation now needs to stop a "Personal Loans"
    widget from recommending a "Credit Cards" item, not just stop cross-tenant
    leakage — see CatalogItemVectorStore's docstring."""
    store = CatalogItemVectorStore(
        str(tmp_path / "chroma"),
        collection_name="isolation-test",
        embedding_function=DeterministicEmbeddingFunction(8),
    )
    widget_a_item = _FakeCatalogItem(1, "Widget A Only Item")
    widget_b_item = _FakeCatalogItem(1, "Widget B Only Item")
    store.upsert(widget_a_item, widget_id=1)
    store.upsert(widget_b_item, widget_id=2)

    results_a = store.query_scored("Widget A Only Item", widget_id=1, limit=5)
    results_b = store.query_scored("Widget B Only Item", widget_id=2, limit=5)

    assert [catalog_item_id for catalog_item_id, _ in results_a] == [1]
    assert [catalog_item_id for catalog_item_id, _ in results_b] == [1]
    # Each widget's collection holds only what was upserted into it — even querying
    # widget 1's collection with widget 2's exact text can only ever return widget
    # 1's own single item, never widget 2's, because the collections are entirely
    # separate indexes, not filtered views of one shared index.
    cross_widget = store.query_scored("Widget B Only Item", widget_id=1, limit=5)
    assert [catalog_item_id for catalog_item_id, _ in cross_widget] == [1]
    assert store._collection_for(1).count() == 1
    assert store._collection_for(2).count() == 1
