import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Event, Model, Recommendation


class FeedbackRecord(NamedTuple):
    rating: str
    # The behavior_summary of the recommendation the feedback was given on, so the
    # rerank node can tell whether *this* query is the same kind of ask the user was
    # rating, rather than applying the opinion everywhere. Empty for feedback events
    # recorded before a recommendation link was tracked.
    context_query: str


SESSION_GAP = timedelta(minutes=30)
LOOKBACK_EVENT_LIMIT = 50
LOOKBACK_DAYS = timedelta(days=3)
SESSION_DECAY = 0.5
SESSION_TRIGGER_COUNT = 2
SESSION_COOLDOWN = timedelta(minutes=3)
MODALITY_FILTER_RATIO = 1.5

# Explicit feedback loop: a thumbs up/down on a past recommendation card should keep
# influencing ranking longer than ordinary browsing activity (LOOKBACK_DAYS, 3 days) —
# "don't show me this again" is a deliberate, longer-lived preference, not a passing
# browse signal.
FEEDBACK_LOOKBACK_DAYS = timedelta(days=14)

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
        watchlisted_titles = [
            models_by_id[event.model_id].title for event in watchlist_events
        ]
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
                parts.append(
                    f"Browsing multiple {modality} models — evaluating options."
                )

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
    older = _summarize_bucket(
        session, [event for bucket in buckets[1:] for event in bucket]
    )
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

    model_ids = {
        event.model_id for events_ in buckets for event in events_ if event.model_id
    }
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


def session_evidence(
    session: Session, events: list[Event], limit: int = 5
) -> list[dict]:
    """Current session only (buckets[0]), newest-first — the raw, itemized "what actually
    happened" list backing the Dashboard's evidence row, as opposed to `activity_summary`'s
    prose blob. Deduped by (action, key) so re-viewing the same model twice in a row only
    shows once. Each item: {"action", "label", "model": Model | None, "created_at"}.
    """
    buckets = session_bucket_events(events)
    if not buckets:
        return []
    current = buckets[0]

    model_ids = {event.model_id for event in current if event.model_id}
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

    action_by_type = {
        "model_view": "viewed",
        "model_compare": "compared",
        "search": "searched",
        "model_watchlist": "watchlisted",
    }

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for event in current:
        action = action_by_type.get(event.event_type)
        if not action:
            continue
        if (
            event.event_type == "model_watchlist"
            and (event.metadata_json or {}).get("action") != "add"
        ):
            continue
        if event.event_type == "search":
            query = (event.metadata_json or {}).get("query")
            if not query:
                continue
            label = f'"{query}"'
            key = (action, query)
        else:
            model = models_by_id.get(event.model_id)
            if not model:
                continue
            label = model.title
            key = (action, model.title)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "action": action,
                "label": label,
                "model": models_by_id.get(event.model_id)
                if event.event_type != "search"
                else None,
                "created_at": event.created_at,
            }
        )
        if len(items) >= limit:
            break
    return items


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


def recent_feedback_by_model(
    session: Session, user_id: int
) -> dict[int, FeedbackRecord]:
    """Most recent explicit up/down feedback per model within FEEDBACK_LOOKBACK_DAYS —
    newest rating wins if the user changed their mind. No new table: feedback is just
    another `Event` (event_type="recommendation_feedback", metadata={"rating": ...,
    "recommendation_id": ...}), tracked through the same batched /api/events/batch path
    as every other behavioral signal. Feeds the rerank_candidates node
    (app/services/agent_graph.py) so a downvote actually suppresses that model from
    reappearing, not just logs a rating.

    Each record carries the behavior_summary of the recommendation it was given on
    (via the linked Recommendation row) so the caller can scope the adjustment to a
    similar query rather than applying it globally — a downvote on a voice model shown
    for a "rack-based" search shouldn't also suppress that same model the next time the
    user is genuinely looking for voice models.
    """
    cutoff = datetime.utcnow() - FEEDBACK_LOOKBACK_DAYS
    events = session.scalars(
        select(Event)
        .where(
            Event.user_id == user_id,
            Event.event_type == "recommendation_feedback",
            Event.created_at >= cutoff,
        )
        .order_by(Event.created_at.desc())
    ).all()
    if not events:
        return {}
    recommendation_ids = {
        (event.metadata_json or {}).get("recommendation_id") for event in events
    }
    recommendation_ids.discard(None)
    context_by_recommendation_id = (
        {
            rec.id: rec.behavior_summary
            for rec in session.scalars(
                select(Recommendation).where(Recommendation.id.in_(recommendation_ids))
            ).all()
        }
        if recommendation_ids
        else {}
    )
    feedback: dict[int, FeedbackRecord] = {}
    for event in events:
        if event.model_id is None:
            continue
        metadata = event.metadata_json or {}
        rating = metadata.get("rating")
        if rating not in ("up", "down"):
            continue
        context_query = context_by_recommendation_id.get(
            metadata.get("recommendation_id"), ""
        )
        feedback.setdefault(
            event.model_id, FeedbackRecord(rating=rating, context_query=context_query)
        )
    return feedback


def is_recommendation_stale(events: list[Event], latest: Recommendation | None) -> bool:
    """True if a new pipeline run could actually produce something different from
    `latest` — i.e. activity changed since it was generated and its cooldown window
    has passed. Shared by `should_trigger` (the pre-check that decides whether to even
    schedule a background run) and the graph's own `analyze` node (AGT-6's authoritative
    short-circuit) so the two can never quietly disagree — see the "so many agent
    pipelines running" observability report this was split out to fix: every batch in an
    already-triggered session was re-passing the old count-only check and spawning a new
    background task (and LangSmith trace) that almost always immediately no-opped here
    anyway. Checking it once, up front, means that wasted spawn no longer happens.
    """
    if latest is None:
        return True
    if not events:
        return False
    if latest.activity_hash == activity_hash(events):
        return False
    if (
        latest.created_at
        and events[0].created_at - latest.created_at < SESSION_GAP
        and datetime.utcnow() - latest.created_at < SESSION_COOLDOWN
    ):
        return False
    return True


def should_trigger(session: Session, user_id: int) -> bool:
    """Cheap, pure-SQL gate run synchronously at the end of `/api/events/batch` (AGT-1).

    Deliberately outside the LangGraph pipeline — the graph only runs once this says
    yes, so a per-event LLM call never happens (still true here: this only adds a
    second cheap SQL lookup, never a Mesh/LangSmith call).

    Gated on *current-session* activity, not lifetime event count: 2 fresh clicks in a
    new session trigger regardless of how much history sits behind the SESSION_GAP. On
    top of that, also skips triggering when AGT-6's cooldown/hash-dedupe would
    immediately no-op anyway, so an active browsing session doesn't spawn a new
    background pipeline run (and LangSmith trace) on every single batch flush once the
    threshold has been crossed once.
    """
    events = recent_events(session, user_id)
    buckets = session_bucket_events(events)
    if not buckets or len(buckets[0]) < SESSION_TRIGGER_COUNT:
        return False
    latest = session.scalar(
        select(Recommendation)
        .where(Recommendation.user_id == user_id)
        .order_by(Recommendation.created_at.desc())
    )
    return is_recommendation_stale(events, latest)


def mesh_cost_rollup(session: Session, limit: int = 10) -> dict:
    """Aggregates Mesh cost/latency/token usage straight out of our own DB (the
    `mesh_*` columns on `Recommendation`, captured at generation time in
    app/services/mesh.py) — no LangSmith call involved, so this stays cheap and
    available even when tracing (OBS-1/OBS-2) isn't configured. Only rows where
    generation actually ran (mesh_latency_ms is not null) count; retrieval-only runs
    are excluded rather than silently averaged in as zeros.
    """
    has_generation = Recommendation.mesh_latency_ms.is_not(None)
    totals = session.execute(
        select(
            func.count(),
            func.avg(Recommendation.mesh_latency_ms),
            func.sum(Recommendation.mesh_prompt_tokens),
            func.sum(Recommendation.mesh_completion_tokens),
            func.sum(Recommendation.mesh_cost_usd),
        ).where(has_generation)
    ).one()
    call_count, avg_latency_ms, prompt_tokens, completion_tokens, cost_usd = totals
    recent = session.scalars(
        select(Recommendation)
        .where(has_generation)
        .order_by(Recommendation.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "call_count": call_count or 0,
        "avg_latency_ms": float(avg_latency_ms) if avg_latency_ms is not None else None,
        "total_prompt_tokens": prompt_tokens or 0,
        "total_completion_tokens": completion_tokens or 0,
        "total_cost_usd": float(cost_usd) if cost_usd is not None else None,
        "recent": [
            {
                "id": rec.id,
                "created_at": rec.created_at,
                "latency_ms": rec.mesh_latency_ms,
                "prompt_tokens": rec.mesh_prompt_tokens,
                "completion_tokens": rec.mesh_completion_tokens,
                "cost_usd": rec.mesh_cost_usd,
            }
            for rec in recent
        ],
    }
