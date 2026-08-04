import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Model


TRIGGER_EVENT_COUNT = 3
TRIGGER_COOLDOWN = timedelta(minutes=15)
MODALITY_CLUSTER_WINDOW = timedelta(minutes=15)


def activity_summary(session: Session, events: list[Event]) -> str:
    """Aggregate recent events into a natural-language behavior summary.

    Never a raw dump of event data into the prompt: `model_view` events for 2+ distinct
    models of the same modality within a short window are folded in as a soft "browsing
    this modality" signal, kept distinct from an explicit `model_compare` (AGT-2).
    """
    if not events:
        return ""

    model_ids = {event.model_id for event in events if event.model_id}
    models_by_id = (
        {
            model.id: model
            for model in session.scalars(
                select(Model).where(Model.id.in_(model_ids))
            ).all()
        }
        if model_ids
        else {}
    )

    parts: list[str] = []

    queries = [
        event.metadata_json["query"]
        for event in events
        if event.event_type == "search" and (event.metadata_json or {}).get("query")
    ]
    if queries:
        parts.append(f"Searched for: {', '.join(dict.fromkeys(queries))}.")

    view_events = [
        event
        for event in events
        if event.event_type == "model_view" and event.model_id in models_by_id
    ]
    if view_events:
        viewed_titles = [models_by_id[event.model_id].title for event in view_events]
        parts.append(f"Viewed: {', '.join(dict.fromkeys(viewed_titles))}.")

        by_modality: dict[str, list[Event]] = defaultdict(list)
        for event in view_events:
            by_modality[models_by_id[event.model_id].modality].append(event)
        for modality, modality_events in by_modality.items():
            distinct_ids = {event.model_id for event in modality_events}
            if len(distinct_ids) < 2:
                continue
            ordered = sorted(modality_events, key=lambda event: event.created_at)
            span = ordered[-1].created_at - ordered[0].created_at
            if span <= MODALITY_CLUSTER_WINDOW:
                parts.append(f"Browsing multiple {modality} models — evaluating options.")

    compare_events = [
        event
        for event in events
        if event.event_type == "model_compare" and event.model_id in models_by_id
    ]
    compared_titles = list(
        dict.fromkeys(models_by_id[event.model_id].title for event in compare_events)
    )
    if len(compared_titles) >= 2:
        parts.append(f"Compared {' vs '.join(compared_titles)}.")
    elif len(compared_titles) == 1:
        parts.append(f"Added {compared_titles[0]} to comparison.")

    return " ".join(parts)


def activity_hash(events: list[Event]) -> str:
    payload = [
        {
            "type": event.event_type,
            "model_id": event.model_id,
            "metadata": event.metadata_json or {},
        }
        for event in events
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def recent_events(session: Session, user_id: int) -> list[Event]:
    return session.scalars(
        select(Event)
        .where(Event.user_id == user_id)
        .order_by(Event.created_at.desc())
        .limit(20)
    ).all()


def should_trigger(session: Session, user_id: int) -> bool:
    """Cheap, pure-SQL gate run synchronously at the end of `/api/events/batch` (AGT-1).

    Deliberately outside the LangGraph pipeline — the graph only runs once this says yes,
    so a per-event LLM call never happens. Cooldown/dedupe against unchanged behavior is
    handled inside the graph's `analyze_activity` node (AGT-6), not here.
    """
    return len(recent_events(session, user_id)) >= TRIGGER_EVENT_COUNT
