import hashlib
import logging
import re
from collections.abc import Sequence
from pathlib import Path

import chromadb

# This pinned chromadb version calls posthog's old positional capture(distinct_id, event,
# properties) signature; the installed posthog major version rewrote that to capture(event,
# **kwargs), so the call now raises a TypeError before posthog's own code ever runs — meaning
# chromadb.Settings(anonymized_telemetry=False) can't prevent it (that flag is checked inside
# posthog, past the point where the mismatched call already failed). Silencing the logger it
# reports through is what actually stops the noise; the failure itself was always harmless
# (chromadb catches it internally either way).
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


class DeterministicEmbeddingFunction:
    """Small offline embedding used for the MVP handshake and local tests."""

    dimension = 64

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


class ModelVectorStore:
    def __init__(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        # anonymized_telemetry=False: this pinned chromadb version calls posthog's old
        # positional capture() signature, which the installed posthog major version no longer
        # accepts — chromadb swallows the resulting TypeError and just logs it every client
        # init. Harmless, but disabling telemetry removes the noise (and the outbound call).
        client = chromadb.PersistentClient(
            path=path, settings=chromadb.Settings(anonymized_telemetry=False)
        )
        self.collection = client.get_or_create_collection(
            name="models",
            embedding_function=DeterministicEmbeddingFunction(),
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

    def query(
        self, text: str, limit: int = 5, where: dict | None = None
    ) -> list[int]:
        if not text.strip() or self.collection.count() == 0:
            return []
        results = self.collection.query(
            query_texts=[text], n_results=limit, where=where
        )
        ids = results.get("ids", [[]])[0]
        return [int(model_id) for model_id in ids]

    def query_scored(
        self, text: str, limit: int = 5, where: dict | None = None
    ) -> list[tuple[int, float]]:
        """Like `query`, but also returns each result's distance (lower = more similar) —
        used by the grade/refine node to detect weak retrieval. `where` applies Chroma
        metadata filtering (e.g. `{"modality": "Voice"}`) before the ANN search runs, not
        as a post-hoc re-rank filter."""
        if not text.strip() or self.collection.count() == 0:
            return []
        results = self.collection.query(
            query_texts=[text], n_results=limit, where=where, include=["distances"]
        )
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return [
            (int(model_id), float(distance))
            for model_id, distance in zip(ids, distances)
        ]

    def count(self) -> int:
        return self.collection.count()
