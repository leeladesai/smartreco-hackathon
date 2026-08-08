import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from langsmith import traceable
from openai import OpenAI

from app.config import Settings
from app.services.narrative import encode_narrative
from app.services.prompts import NARRATIVE_SYSTEM_PROMPT, build_narrative_user_message


@dataclass(frozen=True)
class NarrativeResult:
    narrative: str
    model_ids: list[int]


# Deterministic safety net, not just a prompt request: catalog primary keys are an
# internal implementation detail (see the "ignore the ID" feedback this was added
# from), so any "(ID 4)"/"id: 4"/"#4"-style leak is stripped regardless of whether the
# model actually followed the system prompt's instruction not to mention them.
_ID_MENTION_RE = re.compile(
    r"[\(\[]?\s*\b(?:candidate[_ ]?)?id\s*[:#]?\s*\d+\s*[\)\]]?", re.IGNORECASE
)


def _strip_id_mentions(text: str) -> str:
    cleaned = _ID_MENTION_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -")


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
            # Only include facts that are actually set — most fields are modality-
            # specific (Voice has latency, LLM has context_window, neither always has
            # both), and an absent field must not silently read as "0"/"None" here.
            facts = [f"price {candidate['price']}"] if candidate.get("price") else []
            if candidate.get("latency_ms"):
                facts.append(f"latency ~{candidate['latency_ms']}ms")
            if candidate.get("context_window"):
                facts.append(f"context window {candidate['context_window']}")
            if candidate.get("use_case_tags"):
                facts.append(f"use cases: {', '.join(candidate['use_case_tags'])}")
            return f" [{'; '.join(facts)}]" if facts else ""

        # candidate_id is kept out of the human-readable description entirely — it's
        # only needed so the model can echo back which candidates it picked in
        # `model_ids`, never as part of the name/description the narrative is built
        # from.
        candidate_text = "\n".join(
            f"- {candidate['title']} ({candidate['provider']}, "
            f"candidate_id={candidate['id']})."
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
                {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_narrative_user_message(
                        behavior_summary, candidate_text
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = {"activity_understanding": content, "recommendation_points": []}
        model_ids = []
        for model_id in payload.get("model_ids", []):
            try:
                model_ids.append(int(model_id))
            except (TypeError, ValueError):
                continue

        understanding = _strip_id_mentions(
            str(payload.get("activity_understanding", ""))
        )
        raw_points = payload.get("recommendation_points", [])
        if not isinstance(raw_points, list):
            raw_points = [raw_points]
        points = [
            _strip_id_mentions(str(point)) for point in raw_points if str(point).strip()
        ]
        narrative = encode_narrative(understanding, points)
        return NarrativeResult(narrative=narrative, model_ids=model_ids)
