import hashlib
import logging
import re
from collections.abc import Sequence
from pathlib import Path

import chromadb
from openai import OpenAI

# This pinned chromadb version calls posthog's old positional capture(distinct_id, event,
# properties) signature; the installed posthog major version rewrote that to capture(event,
# **kwargs), so the call now raises a TypeError before posthog's own code ever runs — meaning
# chromadb.Settings(anonymized_telemetry=False) can't prevent it (that flag is checked inside
# posthog, past the point where the mismatched call already failed). Silencing the logger it
# reports through is what actually stops the noise; the failure itself was always harmless
# (chromadb catches it internally either way).
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)


class DeterministicEmbeddingFunction:
    """Offline fallback embedding — used whenever Mesh isn't configured (no API key),
    so the catalog/retrieval loop still works without any external dependency. Also
    what tests use, since they deliberately run with mesh_api_key=None."""

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def __call__(self, input: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimension
            values[index] += 1.0
        norm = sum(value * value for value in values) ** 0.5 or 1.0
        return [value / norm for value in values]


class MeshEmbeddingFunction:
    """Real semantic embeddings via the Mesh API — same Chroma EmbeddingFunction
    interface as DeterministicEmbeddingFunction, so it's a drop-in replacement. One
    batched call regardless of how many texts Chroma passes in; the API preserves
    input order, so results map back to documents by position."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self.client = client
        self.model = model

    def __call__(self, input: Sequence[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=list(input))
        return [item.embedding for item in response.data]


def build_embedding_function(settings):
    """Mesh-backed embeddings when configured, the deterministic fallback otherwise —
    mirrors MeshNarrativeGenerator's own enabled/disabled pattern (app/services/mesh.py)
    so the app degrades the same way in both places rather than two different stories.
    """
    if settings.mesh_api_key:
        client = OpenAI(api_key=settings.mesh_api_key, base_url=settings.mesh_base_url)
        return MeshEmbeddingFunction(client, settings.mesh_embedding_model)
    return DeterministicEmbeddingFunction(settings.embedding_dimension)


class ModelVectorStore:
    def __init__(
        self,
        path: str,
        collection_name: str = "models",
        embedding_function=None,
        embedding_dimension: int = 64,
    ) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        # anonymized_telemetry=False: this pinned chromadb version calls posthog's old
        # positional capture() signature, which the installed posthog major version no longer
        # accepts — chromadb swallows the resulting TypeError and just logs it every client
        # init. Harmless, but disabling telemetry removes the noise (and the outbound call).
        client = chromadb.PersistentClient(
            path=path, settings=chromadb.Settings(anonymized_telemetry=False)
        )
        self.collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function
            or DeterministicEmbeddingFunction(embedding_dimension),
        )

    @staticmethod
    def document(model) -> str:
        tags = ", ".join(model.use_case_tags or [])
        story = f" {model.story}." if getattr(model, "story", None) else ""
        return (
            f"{model.title}. {model.provider}. {model.modality}. "
            f"{model.description}.{story} {tags}"
        )

    def upsert(self, model) -> None:
        self.collection.upsert(
            ids=[str(model.id)],
            documents=[self.document(model)],
            metadatas=[
                {
                    "provider": model.provider,
                    "modality": model.modality,
                    "price": model.price,
                    "latency_ms": model.latency_ms or -1,
                }
            ],
        )

    def delete(self, model_id: int) -> None:
        self.collection.delete(ids=[str(model_id)])

    def query_scored(
        self, text: str, limit: int = 5, where: dict | None = None
    ) -> list[tuple[int, float]]:
        """Like `query`, but also returns each result's distance (lower = more similar) —
        used by the grade/refine node to detect weak retrieval. `where` applies Chroma
        metadata filtering (e.g. `{"modality": "Voice"}`) before the ANN search runs, not
        as a post-hoc re-rank filter."""
        if not text.strip() or self.collection.count() == 0:
            return []
        try:
            results = self.collection.query(
                query_texts=[text], n_results=limit, where=where, include=["distances"]
            )
        except Exception:
            # A transient Mesh embedding failure here must degrade to "no candidates
            # this round" (same as an empty collection), not crash the whole
            # background pipeline run — retrieval is core to every recommendation,
            # unlike narrative generation, which already fails this gracefully.
            logger.exception("Vector store query failed; returning no candidates")
            return []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return [
            (int(model_id), float(distance))
            for model_id, distance in zip(ids, distances)
        ]
