import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from langsmith import traceable
from openai import OpenAI

from app.config import Settings
from app.services.narrative import encode_narrative
from app.services.prompts import NARRATIVE_SYSTEM_PROMPT, build_narrative_user_message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NarrativeResult:
    narrative: str
    model_ids: list[int]
    # Cost/latency rollup (bonus, efficiency polish) — captured here, at the one place
    # the real Mesh call happens, and persisted straight onto the Recommendation row
    # (app/services/agent_graph.py) so the admin cost dashboard reads it back from our
    # own DB rather than re-querying LangSmith for it.
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


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
        self.base_url = settings.mesh_base_url
        self.api_key = settings.mesh_api_key
        self.client = OpenAI(
            api_key=settings.mesh_api_key or "missing-mesh-key",
            base_url=settings.mesh_base_url,
        )
        # Lazily fetched and cached on first use, not at startup — a pricing lookup
        # failure must never block app boot, and most local/dev runs never need it.
        self._pricing_cache: dict[str, tuple[float, float] | None] = {}

    def _pricing_per_1m_tokens(self, model: str) -> tuple[float, float] | None:
        """(prompt_usd_per_1m, completion_usd_per_1m) for `model`, or None if the
        lookup fails or the model isn't listed — cost then just shows as unknown
        rather than guessed. Best-effort only: token counts and latency (the more
        load-bearing efficiency signals) never depend on this succeeding."""
        if model in self._pricing_cache:
            return self._pricing_cache[model]
        pricing = None
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            response.raise_for_status()
            for entry in response.json():
                if entry.get("id") == model:
                    prices = entry.get("pricing") or {}
                    prompt_price = prices.get("prompt_usd_per_1m")
                    completion_price = prices.get("completion_usd_per_1m")
                    if prompt_price is not None and completion_price is not None:
                        pricing = (float(prompt_price), float(completion_price))
                    break
        except Exception:
            logger.warning(
                "Could not fetch Mesh pricing for model=%s; cost will show as unknown",
                model,
                exc_info=True,
            )
        self._pricing_cache[model] = pricing
        return pricing

    def _estimate_cost_usd(
        self, prompt_tokens: int | None, completion_tokens: int | None
    ) -> float | None:
        if prompt_tokens is None or completion_tokens is None:
            return None
        pricing = self._pricing_per_1m_tokens(self.model)
        if pricing is None:
            return None
        prompt_price, completion_price = pricing
        return (prompt_tokens / 1_000_000) * prompt_price + (
            completion_tokens / 1_000_000
        ) * completion_price

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
        started_at = time.monotonic()
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
        latency_ms = (time.monotonic() - started_at) * 1000
        usage = getattr(response, "usage", None)
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        cost_usd = self._estimate_cost_usd(prompt_tokens, completion_tokens)

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
        return NarrativeResult(
            narrative=narrative,
            model_ids=model_ids,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
