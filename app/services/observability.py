"""OBS-2: pulls recent LangSmith pipeline traces into the admin portal itself, rather
than requiring a curator to hold their own LangSmith login. Read-only — never writes
to LangSmith. Depends on OBS-1 (app/services/tracing.py) already being enabled; if it
isn't, or the API call fails, callers get ObservabilityUnavailable with a UI-safe
message.
"""

import itertools
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from langsmith import Client

from app.config import Settings


class ObservabilityUnavailable(Exception):
    """Raised when LangSmith isn't configured or the API call fails; UI-safe message."""


@dataclass(frozen=True)
class TraceRun:
    id: str
    name: str
    run_type: str
    status: str
    start_time: datetime | None
    latency_ms: float | None
    error: str | None
    url: str | None


@dataclass(frozen=True)
class TraceStep:
    name: str
    run_type: str
    status: str
    start_time: datetime | None
    latency_ms: float | None
    error: str | None
    depth: int
    inputs: dict | None
    outputs: dict | None


@dataclass(frozen=True)
class TraceDetail:
    id: str
    name: str
    status: str
    start_time: datetime | None
    # Raw wall-clock time of the whole traced call (root end_time - start_time).
    # Dominated by LangGraph 0.0.20's own internal state-channel bookkeeping spans
    # when tracing is on (confirmed live: ~40s of a ~43s run was pure LangGraph/
    # LangSmith overhead, not our own code) — kept here as "total wall time", with
    # `pipeline_latency_ms` below as the honest "what our own pipeline actually spent"
    # figure, so neither number is presented as the other.
    latency_ms: float | None
    # Sum of each named step's own latency_ms (the same steps in `steps` below) — our
    # actual analyze/retrieve/rerank/grade_refine/generate/store work, excluding every
    # LangGraph-internal wrapper span. Free to compute: `steps` already required
    # fetching the full child-run tree for the step-by-step view.
    pipeline_latency_ms: float | None
    url: str | None
    steps: list[TraceStep]


# LangGraph's own execution machinery generates dozens of internal spans per run
# (`LangGraph`, `__start__`, `RunnableLambda`, `ChannelWrite<...>`, `*:edges`, ...) —
# real, but noise a curator never needs to see. Only our own named `@traceable` nodes
# (app/services/agent_graph.py, app/services/mesh.py) are surfaced as steps; everything
# else is skipped without losing its children, so a genuinely nested span (the Mesh
# call inside generate_narrative) still shows up at a sensible depth.
KNOWN_STEP_NAMES = {
    "analyze_activity",
    "retrieve_models",
    "rerank_candidates",
    "grade_refine",
    "generate_narrative",
    "store_and_deliver",
    "mesh_generate_narrative",
}


def _run_url(client: Client, run) -> str | None:
    # Best-effort only — a run list is still useful without a working deep link, so a
    # failure here must never take down the whole page.
    try:
        return client.get_run_url(run=run)
    except Exception:
        return None


def _latency_ms(run) -> float | None:
    if not run.start_time or not run.end_time:
        return None
    return (run.end_time - run.start_time).total_seconds() * 1000


def _safe_payload(value):
    # LangSmith already reduces non-JSON-serializable call args (a live SQLAlchemy
    # Session, the vector store) to a plain-dict representation before this ever comes
    # back from the API, so this is mostly a defensive backstop — one field that still
    # can't round-trip through JSON must never crash the whole detail view.
    if not isinstance(value, dict):
        return value
    safe: dict = {}
    for key, val in value.items():
        try:
            json.dumps(val, default=str)
        except TypeError:
            safe[key] = f"<{type(val).__name__}>"
        else:
            safe[key] = val
    return safe


def _collect_steps(run, depth: int) -> list["TraceStep"]:
    is_known = run.name in KNOWN_STEP_NAMES
    steps: list[TraceStep] = []
    if is_known:
        steps.append(
            TraceStep(
                name=run.name,
                run_type=run.run_type,
                status=run.status or ("error" if run.error else "success"),
                start_time=run.start_time,
                latency_ms=_latency_ms(run),
                error=run.error,
                depth=depth,
                inputs=_safe_payload(run.inputs),
                outputs=_safe_payload(run.outputs),
            )
        )
    children = sorted(
        run.child_runs or [],
        key=lambda child: child.start_time or datetime.min.replace(tzinfo=timezone.utc),
    )
    next_depth = depth + 1 if is_known else depth
    for child in children:
        steps.extend(_collect_steps(child, next_depth))
    return steps


def fetch_recent_runs(
    settings: Settings, limit: int = 25, offset: int = 0, user_id: int | None = None
) -> tuple[list[TraceRun], bool]:
    """The top-level `agent_pipeline` run per trigger, newest first — not every child
    node, which would bury the signal a curator actually wants ("did the last few runs
    succeed, how long did they take") under 5x as many rows.

    `user_id`, when given, scopes this to one user's own runs via LangSmith's native
    tag filter — every `agent_pipeline` run is tagged `user:<id>` at trace time
    (`prepare_retrieval_recommendation`), so this is a real server-side LangSmith query
    (`has(tags, "user:<id>")`), not a client-side filter over the full run list.

    Returns `(page, has_more)`. The pinned SDK's `list_runs` has no server-side offset
    param, so pagination is done by pulling `offset + limit + 1` items from its lazy
    iterator (itself paging against the LangSmith API under the hood, so this stays
    bounded rather than fetching the whole project) and slicing locally — the "+1"
    lets us detect a next page exists without a separate count query.
    """
    if not settings.langsmith_api_key:
        raise ObservabilityUnavailable(
            "LANGSMITH_API_KEY is not configured — set it in .env to enable "
            "tracing and this dashboard."
        )
    client = Client(api_key=settings.langsmith_api_key)
    list_runs_kwargs: dict = {
        "project_name": settings.langsmith_project,
        "execution_order": 1,
    }
    if user_id is not None:
        list_runs_kwargs["filter"] = f'has(tags, "user:{user_id}")'
    try:
        runs = list(
            itertools.islice(
                client.list_runs(**list_runs_kwargs),
                offset + limit + 1,
            )
        )
    except Exception as exc:  # network error, bad key, project doesn't exist yet, etc.
        raise ObservabilityUnavailable(
            f"Couldn't reach LangSmith ({exc}). Check LANGSMITH_API_KEY and "
            "network access."
        ) from exc

    runs.sort(
        key=lambda run: run.start_time or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    has_more = len(runs) > offset + limit
    page = runs[offset : offset + limit]
    return (
        [
            TraceRun(
                id=str(run.id),
                name=run.name,
                run_type=run.run_type,
                status=run.status or ("error" if run.error else "success"),
                start_time=run.start_time,
                latency_ms=_latency_ms(run),
                error=run.error,
                url=_run_url(client, run),
            )
            for run in page
        ],
        has_more,
    )


def fetch_run_detail(settings: Settings, run_id: str) -> TraceDetail:
    """The full step-by-step breakdown of a single `agent_pipeline` run — one call to
    LangSmith (`read_run(..., load_child_runs=True)` already returns the whole subtree),
    filtered down to our own named nodes via `_collect_steps`."""
    if not settings.langsmith_api_key:
        raise ObservabilityUnavailable(
            "LANGSMITH_API_KEY is not configured — set it in .env to enable "
            "tracing and this dashboard."
        )
    client = Client(api_key=settings.langsmith_api_key)
    try:
        run = client.read_run(run_id, load_child_runs=True)
    except Exception as exc:
        raise ObservabilityUnavailable(
            f"Couldn't load that trace ({exc}). It may have expired or the ID is wrong."
        ) from exc

    # The root run itself (agent_pipeline) is already represented by this TraceDetail's
    # own top-level fields, so steps start from its children, not the root. Real traces
    # can have several separate top-level branches (e.g. each grade_refine retry sits
    # under its own internal LangGraph wrapper span rather than all under one shared
    # parent), so sorting only within each branch doesn't guarantee a globally
    # chronological result — a final sort on the flattened list does, and a strict
    # execution-order timeline (including how retries actually interleaved) is more
    # useful here than a tree grouped by parent anyway.
    steps = [
        step for child in (run.child_runs or []) for step in _collect_steps(child, 0)
    ]
    steps.sort(
        key=lambda step: step.start_time or datetime.min.replace(tzinfo=timezone.utc)
    )
    # Only depth-0 steps — a nested step (e.g. mesh_generate_narrative inside
    # generate_narrative) occupies a time window already contained within its
    # parent's own latency_ms, so summing every depth would double-count it.
    step_latencies = [
        step.latency_ms
        for step in steps
        if step.depth == 0 and step.latency_ms is not None
    ]
    pipeline_latency_ms = sum(step_latencies) if step_latencies else None

    return TraceDetail(
        id=str(run.id),
        name=run.name,
        status=run.status or ("error" if run.error else "success"),
        start_time=run.start_time,
        latency_ms=_latency_ms(run),
        pipeline_latency_ms=pipeline_latency_ms,
        url=_run_url(client, run),
        steps=steps,
    )
