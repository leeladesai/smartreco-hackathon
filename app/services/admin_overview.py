"""Platform-usage metrics for the admin "Overview" landing page — distinct from
app/services/observability.py (AI pipeline/LangSmith technical health). Everything
here is a plain aggregation over our own tables (User/Model/Event/Recommendation);
no external calls, no new instrumentation required.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Event, Model, Recommendation, User


def usage_totals(session: Session) -> dict[str, int]:
    return {
        "users": session.scalar(select(func.count(User.id))) or 0,
        "models": session.scalar(select(func.count(Model.id))) or 0,
        "events": session.scalar(select(func.count(Event.id))) or 0,
        # "Generated" specifically — a Recommendation row can exist as retrieval-only
        # (no Mesh narrative, e.g. MESH_API_KEY unset), so counting every row would
        # overstate what the AI has actually produced.
        "recommendations": session.scalar(
            select(func.count(Recommendation.id)).where(
                Recommendation.narrative.is_not(None)
            )
        )
        or 0,
    }


def event_type_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Event.event_type, func.count(Event.id)).group_by(Event.event_type)
    ).all()
    return {event_type: count for event_type, count in rows}


def feedback_sentiment(session: Session) -> dict[str, int]:
    """Counts thumbs up/down across recommendation_feedback events. Parsed in Python
    rather than a JSON-column SQL operator (e.g. SQLite's json_extract) — the event
    volume here is small, and this stays portable/debuggable rather than depending on
    a specific DB's JSON extension, consistent with this codebase's existing
    preference for computing in Python over DB-specific query tricks.
    """
    events = session.scalars(
        select(Event).where(Event.event_type == "recommendation_feedback")
    ).all()
    counts = {"up": 0, "down": 0}
    for event in events:
        rating = (event.metadata_json or {}).get("rating")
        if rating in counts:
            counts[rating] += 1
    return counts


def recent_activity(session: Session, limit: int = 30) -> list[dict]:
    """The admin-wide "live activity" feed — every user's events, newest first.
    Distinct from GET /api/activity/me, which is deliberately scoped to the signed-in
    user's own history; this is the curator's cross-user view."""
    rows = session.execute(
        select(Event, User.email)
        .join(User, Event.user_id == User.id)
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": event.id,
            "user_id": event.user_id,
            "user_email": email,
            "event_type": event.event_type,
            "model_id": event.model_id,
            "metadata": event.metadata_json,
            "created_at": event.created_at,
        }
        for event, email in rows
    ]
