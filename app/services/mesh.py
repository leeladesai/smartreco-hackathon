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
        candidate_text = "\n".join(
            f"- {candidate['id']}: {candidate['title']} ({candidate['provider']}). "
            f"{candidate.get('description', '')} "
            + (f"Why it stands out: {candidate['story']}" if candidate.get("story") else "")
            for candidate in candidates
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Recommend only models in the supplied candidate list. "
                        "Do not invent model IDs or providers. Return valid JSON "
                        'with exactly two keys: "narrative" (string) and '
                        '"model_ids" (array of integer candidate IDs).'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Activity summary: {behavior_summary}\n"
                        f"Candidates:\n{candidate_text}\n"
                        "Write a concise comparison-driven recommendation as JSON."
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
