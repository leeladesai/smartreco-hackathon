"""Structured storage for the Mesh-generated narrative: a short "what we understood
about your activity" statement, plus a separate list of concrete justification points
for the recommendation — kept apart so the UI can render them as two distinct sections
instead of one running paragraph (see the "split it into two categories" feedback this
was added from). Still just a `str` in `Recommendation.narrative` (no schema change) —
this module is the only place that knows it's actually JSON-encoded underneath.

Fully backward compatible: anything already stored as a plain string (old narratives,
placeholder copy, direct test fixtures) fails to parse as the expected shape and is
returned unchanged by `narrative_as_plain_text`/left for the caller to handle as before.
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Narrative:
    understanding: str
    points: list[str]


def encode_narrative(understanding: str, points: list[str]) -> str:
    return json.dumps({"understanding": understanding, "points": points})


def decode_narrative(raw: str | None) -> Narrative | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    understanding = str(data.get("understanding") or "").strip()
    points = [
        str(point).strip() for point in data.get("points") or [] if str(point).strip()
    ]
    if not understanding and not points:
        return None
    return Narrative(understanding=understanding, points=points)


def narrative_as_plain_text(raw: str | None, fallback: str = "") -> str:
    """Flattens the structured narrative into plain text for channels that can't render
    two sections (email, Telegram, logs). Non-JSON input passes through unchanged."""
    parsed = decode_narrative(raw)
    if parsed is None:
        return raw or fallback
    lines: list[str] = []
    if parsed.understanding:
        lines.append(f"Understanding your activity: {parsed.understanding}")
    if parsed.points:
        lines.append("Why these recommendations:")
        lines.extend(f"- {point}" for point in parsed.points)
    return "\n".join(lines) or fallback
