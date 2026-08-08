import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Model


SESSION_GAP = timedelta(minutes=30)
LOOKBACK_EVENT_LIMIT = 50
LOOKBACK_DAYS = timedelta(days=3)
SESSION_DECAY = 0.5
SESSION_TRIGGER_COUNT = 2
SESSION_COOLDOWN = timedelta(minutes=3)
MODALITY_FILTER_RATIO = 1.5

# Still used by activity_summary's "browsing multiple X" clause within a session bucket.
MODALITY_CLUSTER_WINDOW = timedelta(minutes=15)


def session_bucket_events(events: list[Event]) -> list[list[Event]]:
    """Split a newest-first event list into session buckets, also newest-first.

    bucket[0] is the current (most recent) session. A new bucket starts whenever the
    gap between two consecutive events (in time) exceeds SESSION_GAP.
    """
    if not events:
        return []
    buckets: list[list[Event]] = [[events[0]]]
    for previous, current in zip(events, events[1:]):
        gap = previous.created_at - current.created_at
        if gap > SESSION_GAP:
            buckets.append([])
        buckets[-1].append(current)
    return buckets


def session_weight(session_index: int) -> float:
    return SESSION_DECAY**session_index


def _summarize_bucket(session: Session, events: list[Event]) -> str:
    """Aggregate a single session bucket of events into a natural-language behavior
    summary.

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

    # A watchlist add is a stronger, more deliberate interest signal than a passive view
    # (AGT-2-style) — surfaced as its own clause and folded into the same modality-clustering
    # pass below so "starred 2 Image models" counts toward dominant_modality like viewing does.
    watchlist_events = [
        event
        for event in events
        if event.event_type == "model_watchlist"
        and (event.metadata_json or {}).get("action") == "add"
        and event.model_id in models_by_id
    ]
    if watchlist_events:
        watchlisted_titles = [models_by_id[event.model_id].title for event in watchlist_events]
        parts.append(f"Watchlisted: {', '.join(dict.fromkeys(watchlisted_titles))}.")

    interest_events = view_events + watchlist_events
    if interest_events:
        by_modality: dict[str, list[Event]] = defaultdict(list)
        for event in interest_events:
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


def activity_summary(session: Session, events: list[Event]) -> str:
    """Session-aware behavior summary: current-session activity is called out first,
    older sessions (beyond the SESSION_GAP inactivity boundary) are folded in as
    secondary "Earlier: ..." context rather than blended in unweighted.
    """
    buckets = session_bucket_events(events)
    if not buckets:
        return ""
    current = _summarize_bucket(session, buckets[0])
    older = _summarize_bucket(session, [event for bucket in buckets[1:] for event in bucket])
    parts: list[str] = []
    if current:
        parts.append(f"In this session: {current}")
    if older:
        parts.append(f"Earlier: {older}")
    return " ".join(parts)


def dominant_modality(session: Session, events: list[Event]) -> str | None:
    """Retrieval polish (Iteration 3): session-weighted modality scoring, replacing the
    old all-or-nothing rule (which required *exactly one* modality to have 2+ distinct
    models, else gave up entirely — a 3-way tie across session boundaries disabled
    filtering completely). Each session bucket's distinct-model-per-modality counts are
    weighted by session_weight(bucket_index) (current session counts full, each older
    session counts half as much as the one before it) and summed across buckets. The
    winner is used as a Chroma metadata `where` filter only if it has a real signal
    (score >= 2, i.e. at least 2 distinct models' worth of weighted signal) and clearly
    beats the runner-up by MODALITY_FILTER_RATIO — otherwise returns None (no filter),
    same fallback behavior as before.
    """
    buckets = session_bucket_events(events)
    if not buckets:
        return None

    model_ids = {event.model_id for events_ in buckets for event in events_ if event.model_id}
    if not model_ids:
        return None
    models_by_id = {
        model.id: model
        for model in session.scalars(select(Model).where(Model.id.in_(model_ids))).all()
    }

    scores: dict[str, float] = defaultdict(float)
    for bucket_index, bucket_events in enumerate(buckets):
        weight = session_weight(bucket_index)
        signal_events = [
            event
            for event in bucket_events
            if (
                event.event_type in ("model_view", "model_compare")
                or (
                    event.event_type == "model_watchlist"
                    and (event.metadata_json or {}).get("action") == "add"
                )
            )
            and event.model_id in models_by_id
        ]
        by_modality: dict[str, set[int]] = defaultdict(set)
        for event in signal_events:
            by_modality[models_by_id[event.model_id].modality].add(event.model_id)
        for modality, ids in by_modality.items():
            scores[modality] += weight * len(ids)

    if not scores:
        return None

    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    leader_modality, leader_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0

    if leader_score < 2:
        return None
    if runner_up_score > 0 and leader_score < runner_up_score * MODALITY_FILTER_RATIO:
        return None
    return leader_modality


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
    cutoff = datetime.utcnow() - LOOKBACK_DAYS
    return session.scalars(
        select(Event)
        .where(Event.user_id == user_id, Event.created_at >= cutoff)
        .order_by(Event.created_at.desc())
        .limit(LOOKBACK_EVENT_LIMIT)
    ).all()


def should_trigger(session: Session, user_id: int) -> bool:
    """Cheap, pure-SQL gate run synchronously at the end of `/api/events/batch` (AGT-1).

    Deliberately outside the LangGraph pipeline — the graph only runs once this says yes,
    so a per-event LLM call never happens. Cooldown/dedupe against unchanged behavior is
    handled inside the graph's `analyze_activity` node (AGT-6), not here.

    Gated on *current-session* activity, not lifetime event count: 2 fresh clicks in a
    new session trigger regardless of how much history sits behind the SESSION_GAP.
    """
    buckets = session_bucket_events(recent_events(session, user_id))
    return bool(buckets) and len(buckets[0]) >= SESSION_TRIGGER_COUNT
