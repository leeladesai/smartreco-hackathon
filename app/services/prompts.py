"""Mesh narrative-generation prompt content — kept separate from app/services/mesh.py
so the prompt itself (what gets asked of the LLM) can be read, reviewed, and iterated on
without touching the API-calling/response-parsing mechanics. mesh.py owns the HTTP call
and grounding (ID-stripping, model_ids filtering); this module owns the prompt copy.
"""

NARRATIVE_SYSTEM_PROMPT = (
    "Analyze the AI engineer's activity summary and the supplied "
    "candidate list, then respond with strict JSON containing "
    "exactly three keys.\n"
    '"activity_understanding": 1-2 sentences describing what you '
    "understand about their goal or use case (e.g. 'building a "
    "real-time voice agent') — infer this only from the given "
    "activity summary and candidate data, never invent specifics "
    "not present in either.\n"
    '"recommendation_points": an array of 2-4 short, standalone '
    "strings, each a concrete justification for recommending "
    "specific candidates by name, citing real numeric tradeoffs "
    "(latency, price, context window) from the candidate data "
    "where relevant. Recommend only models from the supplied "
    "candidate list; do not invent model IDs, providers, or "
    "facts not present in it.\n"
    "Every candidate has a `candidate_id` — that number is an "
    "internal database key, never part of its name: use it only "
    'in the "model_ids" array below (array of integer '
    "candidate_id values), and never write it, or phrases like "
    "'ID 4' or '(#4)', anywhere in activity_understanding or "
    "recommendation_points — refer to every model only by its "
    "name."
)


def build_narrative_user_message(behavior_summary: str, candidate_text: str) -> str:
    return (
        f"Activity summary: {behavior_summary}\n"
        f"Candidates:\n{candidate_text}\n"
        "Respond with the activity_understanding, "
        "recommendation_points, and model_ids JSON described above."
    )
