import json
from collections.abc import Sequence
from dataclasses import dataclass

from langsmith import traceable
from openai import OpenAI

from app.config import Settings


@dataclass(frozen=True)
class NarrativeResult:
    narrative: str
    model_ids: list[int]


class MeshNarrativeGenerator:
    """Provider boundary for grounded narrative generation through Mesh only."""

    def __init__(self, settings: Settings) -> None:
        self.enabled = bool(settings.mesh_api_key)
        self.model = settings.mesh_model
        self.client = OpenAI(
            api_key=settings.mesh_api_key or "missing-mesh-key",
            base_url=settings.mesh_base_url,
        )

    @traceable(run_type="llm", name="mesh_generate_narrative")
    def generate(
        self, behavior_summary: str, candidates: Sequence[dict]
    ) -> NarrativeResult:
        if not self.enabled:
            raise RuntimeError("Mesh narrative generation is not configured")

        def _facts(candidate: dict) -> str:
            # Only include facts that are actually set — most fields are modality-specific
            # (Voice has latency, LLM has context_window, neither always has both), and an
            # absent field must not silently read as "0" or "None" in the prompt.
            facts = [f"price {candidate['price']}"] if candidate.get("price") else []
            if candidate.get("latency_ms"):
                facts.append(f"latency ~{candidate['latency_ms']}ms")
            if candidate.get("context_window"):
                facts.append(f"context window {candidate['context_window']}")
            if candidate.get("use_case_tags"):
                facts.append(f"use cases: {', '.join(candidate['use_case_tags'])}")
            return f" [{'; '.join(facts)}]" if facts else ""

        candidate_text = "\n".join(
            f"- {candidate['id']}: {candidate['title']} ({candidate['provider']})."
            f"{_facts(candidate)} {candidate.get('description', '')} "
            + (
                f"Why it stands out: {candidate['story']}"
                if candidate.get("story")
                else ""
            )
            for candidate in candidates
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "First, in one sentence, name the AI engineer's likely use case or "
                        "goal based on their activity summary (e.g. 'building a real-time "
                        "voice agent') — infer this only from the given activity summary and "
                        "candidate data, never invent specifics not present in either. Then "
                        "recommend only models from the supplied candidate list, referencing "
                        "specific models the user already looked at by name and concrete "
                        "numeric tradeoffs (latency, price, context window) from the candidate "
                        "data where relevant. Do not invent model IDs, providers, or facts not "
                        "present in the candidate list. Return valid JSON with exactly two "
                        'keys: "narrative" (string, 2-3 sentences) and "model_ids" (array of '
                        "integer candidate IDs)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Activity summary: {behavior_summary}\n"
                        f"Candidates:\n{candidate_text}\n"
                        "Write the intent-framed, comparison-driven recommendation as JSON."
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = {"narrative": content, "model_ids": []}
        model_ids = []
        for model_id in payload.get("model_ids", []):
            try:
                model_ids.append(int(model_id))
            except (TypeError, ValueError):
                continue
        return NarrativeResult(
            narrative=str(payload.get("narrative", "")), model_ids=model_ids
        )
