"""The 5-node recommendation pipeline: analyze -> retrieve -> grade/refine -> generate -> store.

Each stage is a plain function over a shared state dict, wired together with LangGraph so the
pipeline is a named, testable graph (NFR-5) rather than one monolithic function. `should_trigger`
(app/services/recommendation.py) stays outside this graph — it's the cheap, synchronous SQL check
that decides whether to run the graph at all (AGT-1), so a per-event LLM call never happens.
"""

import logging
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langsmith import traceable
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Model, Recommendation
from app.services.mesh import NarrativeResult
from app.services.recommendation import (
    SESSION_COOLDOWN,
    SESSION_GAP,
    _summarize_bucket,
    activity_hash,
    activity_summary,
    dominant_modality,
    recent_events,
    session_bucket_events,
    session_evidence,
)
from app.vector import ModelVectorStore


logger = logging.getLogger(__name__)

RETRIEVAL_TOP_K = 8
MAX_RETRIES = 2

# Empirically calibrated against app/vector.py's deterministic hashed bag-of-words embedding:
# genuinely relevant matches score well under 1.0 on this collection, off-topic/generic queries
# score 1.5+. Not a universal constant — specific to this embedding function.
WEAK_RETRIEVAL_DISTANCE = 1.5
STRONG_RETRIEVAL_DISTANCE = 0.9


class AgentState(TypedDict, total=False):
    user_id: int
    trigger_reason: str
    behavior_summary: str
    retrieval_query: str
    refined_query: str
    activity_hash: str
    retry_count: int
    modality_filter: str | None
    evidence: list[dict]
    candidates_scored: list[tuple[int, float]]
    query_refined: bool
    grade_action: str
    narrative: str | None
    model_ids: list[int]
    retrieval_meta: list[dict]
    short_circuit: bool
    recommendation: Recommendation | None


def retrieval_reason(distance: float, query_refined: bool) -> str:
    """AGT-4 grounding, surfaced to the user: a plain-language "why this" tag derived
    from the Chroma distance (lower = more similar) rather than a canned string."""
    if query_refined:
        return "Matched after broadening your activity signal"
    if distance <= STRONG_RETRIEVAL_DISTANCE:
        return "Strong match to your recent activity"
    if distance <= WEAK_RETRIEVAL_DISTANCE:
        return "Related to your recent activity"
    return "Broader catalog match"


def _latency_beats(candidate: Model, evidence: list[dict], action: str) -> str | None:
    peers = [
        item["model"]
        for item in evidence
        if item["action"] == action
        and item.get("model")
        and item["model"].id != candidate.id
        and item["model"].modality == candidate.modality
        and item["model"].latency_ms is not None
    ]
    if candidate.latency_ms is None or not peers:
        return None
    beaten = [peer for peer in peers if candidate.latency_ms < peer.latency_ms]
    if not beaten:
        return None
    names = list(dict.fromkeys(peer.title for peer in beaten))[:2]
    return f"beats {' + '.join(names)} on latency"


def contextual_reason(
    candidate: Model, distance: float, query_refined: bool, evidence: list[dict]
) -> str:
    """Grounds `why_this` in what the user actually did this session, computed
    deterministically from real fields (never asked of the LLM — see the "story" field
    grounding discussion this was added from). Tries, in order: a latency win against
    models the user explicitly compared, then against models the user merely viewed, then
    a search term matching this candidate's own use-case tags/description. Falls back to
    the existing distance-only `retrieval_reason` when none of that evidence exists —
    never invents a reason with no real backing."""
    reason = _latency_beats(candidate, evidence, "compared")
    if reason:
        return reason
    reason = _latency_beats(candidate, evidence, "viewed")
    if reason:
        return reason

    tags = [tag.lower() for tag in (candidate.use_case_tags or [])]
    description = (candidate.description or "").lower()
    for item in evidence:
        if item["action"] != "searched":
            continue
        term = item["label"].strip('"').lower()
        if not term:
            continue
        if any(term in tag or tag in term for tag in tags) or term in description:
            return f"matches your {item['label']} search"

    return retrieval_reason(distance, query_refined)


def _analyze_activity(session: Session):
    @traceable(run_type="chain", name="analyze_activity")
    def node(state: AgentState) -> AgentState:
        events = recent_events(session, state["user_id"])
        summary = activity_summary(session, events)
        event_hash = activity_hash(events)
        latest = session.scalar(
            select(Recommendation)
            .where(Recommendation.user_id == state["user_id"])
            .order_by(Recommendation.created_at.desc())
        )
        # AGT-6: unchanged behavior since the last recommendation skips a redundant run.
        if latest and latest.activity_hash == event_hash:
            return {**state, "short_circuit": True}
        # Rate limit: only enforce the cooldown if we're still inside the same session as
        # the last recommendation (newest event and last recommendation within SESSION_GAP
        # of each other) — a brand new session is never blocked by a stale prior cooldown.
        if (
            latest
            and latest.created_at
            and events
            and events[0].created_at - latest.created_at < SESSION_GAP
            and datetime.utcnow() - latest.created_at < SESSION_COOLDOWN
        ):
            return {**state, "short_circuit": True}

        buckets = session_bucket_events(events)
        current_bucket = buckets[0] if buckets else []
        older_events = [event for bucket in buckets[1:] for event in bucket]
        current_text = _summarize_bucket(session, current_bucket)
        older_text = _summarize_bucket(session, older_events)
        # Weight the current session 2x relative to older sessions in the retrieval
        # query text (via repetition) — the deterministic hashed bag-of-words embedding
        # in app/vector.py has no real semantics to lean on, so query-text weighting via
        # repetition is how the current session dominates retrieval.
        retrieval_parts = [current_text, current_text]
        if older_text:
            retrieval_parts.append(older_text)
        retrieval_query = " ".join(part for part in retrieval_parts if part) or summary

        return {
            **state,
            "behavior_summary": summary,
            "retrieval_query": retrieval_query,
            "activity_hash": event_hash,
            "retry_count": 0,
            "modality_filter": dominant_modality(session, events),
            "evidence": session_evidence(session, events),
            "short_circuit": False,
        }

    return node


def _retrieve_models(vector_store: ModelVectorStore):
    @traceable(run_type="retriever", name="retrieve_models")
    def node(state: AgentState) -> AgentState:
        query = (
            state.get("refined_query")
            or state.get("retrieval_query")
            or state["behavior_summary"]
        )
        # Only pre-filter on the first pass — a retry already broadens the query text
        # because the narrower search came back weak, so keep the candidate pool wide too.
        modality_filter = state.get("modality_filter") if state.get("retry_count") == 0 else None
        where = {"modality": modality_filter} if modality_filter else None
        scored = vector_store.query_scored(query, limit=RETRIEVAL_TOP_K, where=where)
        return {**state, "candidates_scored": scored}

    return node


@traceable(run_type="chain", name="grade_refine")
def _grade_refine(state: AgentState) -> AgentState:
    """AGT-4: bounded retry (max 2) when retrieval quality is weak."""
    scored = state.get("candidates_scored", [])
    retry_count = state.get("retry_count", 0)
    best_distance = min((distance for _, distance in scored), default=None)
    weak = best_distance is None or best_distance > WEAK_RETRIEVAL_DISTANCE

    if weak and retry_count < MAX_RETRIES:
        # Broaden the query for the next retrieval pass by dropping its most specific
        # clause (the tail of the summary tends to carry the narrowest detail). Broaden
        # from the same weighted retrieval_query text that's actually driving retrieval,
        # not the display-only behavior_summary.
        base_query = state.get("retrieval_query") or state["behavior_summary"]
        words = base_query.split()
        broadened = (
            " ".join(words[: max(3, len(words) * 2 // 3)])
            if len(words) > 3
            else base_query
        )
        logger.info(
            "Weak retrieval (best_distance=%s) for user_id=%s; retry %s/%s with a broadened query",
            best_distance,
            state["user_id"],
            retry_count + 1,
            MAX_RETRIES,
        )
        return {
            **state,
            "retry_count": retry_count + 1,
            "refined_query": broadened,
            "query_refined": True,
            "grade_action": "retry",
        }
    return {**state, "grade_action": "proceed"}


def _generate_narrative(session: Session, mesh_generator):
    @traceable(run_type="chain", name="generate_narrative")
    def node(state: AgentState) -> AgentState:
        model_ids = [model_id for model_id, _ in state.get("candidates_scored", [])]
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
        ordered_ids = [model_id for model_id in model_ids if model_id in models_by_id]

        narrative: str | None = None
        final_ids = ordered_ids
        if mesh_generator is not None and mesh_generator.enabled and ordered_ids:
            candidates = [
                {
                    "id": models_by_id[model_id].id,
                    "title": models_by_id[model_id].title,
                    "provider": models_by_id[model_id].provider,
                    "modality": models_by_id[model_id].modality,
                    "price": models_by_id[model_id].price,
                    "latency_ms": models_by_id[model_id].latency_ms,
                    "context_window": models_by_id[model_id].context_window,
                    "use_case_tags": models_by_id[model_id].use_case_tags,
                    "description": models_by_id[model_id].description,
                    "story": models_by_id[model_id].story,
                }
                for model_id in ordered_ids
            ]
            try:
                result = mesh_generator.generate(state["behavior_summary"], candidates)
            except Exception:
                logger.exception(
                    "Mesh narrative generation failed for user_id=%s; "
                    "leaving recommendation retrieval-only",
                    state["user_id"],
                )
            else:
                if isinstance(result, NarrativeResult):
                    narrative, generated_ids = result.narrative, result.model_ids
                elif isinstance(result, dict):
                    narrative = str(result.get("narrative", ""))
                    generated_ids = result.get("model_ids", [])
                else:
                    narrative, generated_ids = str(result), []
                candidate_id_set = set(ordered_ids)
                filtered = [
                    int(model_id)
                    for model_id in generated_ids
                    if str(model_id).isdigit() and int(model_id) in candidate_id_set
                ]
                final_ids = filtered or ordered_ids

        distances = dict(state.get("candidates_scored", []))
        query_refined = state.get("query_refined", False)
        evidence = state.get("evidence", [])
        retrieval_meta = [
            {
                "model_id": model_id,
                "distance": distances.get(model_id),
                "reason": contextual_reason(
                    models_by_id[model_id],
                    distances.get(model_id, WEAK_RETRIEVAL_DISTANCE),
                    query_refined,
                    evidence,
                ),
            }
            for model_id in final_ids
            if model_id in models_by_id
        ]

        return {
            **state,
            "model_ids": final_ids,
            "narrative": narrative,
            "retrieval_meta": retrieval_meta,
        }

    return node


def _store_and_deliver(session: Session):
    @traceable(run_type="chain", name="store_and_deliver")
    def node(state: AgentState) -> AgentState:
        recommendation = Recommendation(
            user_id=state["user_id"],
            model_ids=state.get("model_ids") or [],
            retrieval_meta=state.get("retrieval_meta") or [],
            narrative=state.get("narrative"),
            behavior_summary=state["behavior_summary"],
            activity_hash=state["activity_hash"],
            trigger_reason=state["trigger_reason"],
        )
        session.add(recommendation)
        session.commit()
        session.refresh(recommendation)
        return {**state, "recommendation": recommendation}

    return node


def build_agent_graph(
    session: Session, vector_store: ModelVectorStore, mesh_generator=None
):
    graph = StateGraph(AgentState)
    graph.add_node("analyze", _analyze_activity(session))
    graph.add_node("retrieve", _retrieve_models(vector_store))
    graph.add_node("grade_refine", _grade_refine)
    graph.add_node("generate", _generate_narrative(session, mesh_generator))
    graph.add_node("store", _store_and_deliver(session))

    graph.set_entry_point("analyze")
    graph.add_conditional_edges(
        "analyze",
        lambda state: "short_circuit" if state.get("short_circuit") else "proceed",
        {"short_circuit": END, "proceed": "retrieve"},
    )
    graph.add_edge("retrieve", "grade_refine")
    graph.add_conditional_edges(
        "grade_refine",
        lambda state: (
            "retrieve"
            if state.get("grade_action") == "retry"
            else ("generate" if state.get("candidates_scored") else END)
        ),
        {"retrieve": "retrieve", "generate": "generate", END: END},
    )
    graph.add_edge("generate", "store")
    graph.add_edge("store", END)
    return graph.compile()


@traceable(run_type="chain", name="agent_pipeline")
def prepare_retrieval_recommendation(
    session: Session,
    vector_store: ModelVectorStore,
    user_id: int,
    mesh_generator=None,
    trigger_reason: str = "event_threshold",
) -> Recommendation | None:
    graph = build_agent_graph(session, vector_store, mesh_generator)
    result = graph.invoke({"user_id": user_id, "trigger_reason": trigger_reason})
    return result.get("recommendation")
