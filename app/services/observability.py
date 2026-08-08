"""OBS-2: pulls recent LangSmith pipeline traces into the admin portal itself, rather
than requiring a curator to hold their own LangSmith login. Read-only — never writes
to LangSmith. Depends on OBS-1 (app/services/tracing.py) already being enabled; if it
isn't, or the API call fails, callers get ObservabilityUnavailable with a UI-safe
message.
"""

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
    latency_ms: float | None
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


def fetch_recent_runs(settings: Settings, limit: int = 25) -> list[TraceRun]:
    """The top-level `agent_pipeline` run per trigger, newest first — not every child
    node, which would bury the signal a curator actually wants ("did the last few runs
    succeed, how long did they take") under 5x as many rows.
    """
    if not settings.langsmith_api_key:
        raise ObservabilityUnavailable(
            "LANGSMITH_API_KEY is not configured — set it in .env to enable "
            "tracing and this dashboard."
        )
    client = Client(api_key=settings.langsmith_api_key)
    try:
        runs = list(
            client.list_runs(
                project_name=settings.langsmith_project,
                execution_order=1,
                limit=limit,
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
    return [
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
        for run in runs[:limit]
    ]


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

    return TraceDetail(
        id=str(run.id),
        name=run.name,
        status=run.status or ("error" if run.error else "success"),
        start_time=run.start_time,
        latency_ms=_latency_ms(run),
        url=_run_url(client, run),
        steps=steps,
    )
