"""OBS-1: LangSmith tracing, off by default. `@traceable` (imported directly by
callers) is a no-op unless tracing is enabled, so this only needs to flip the env vars
LangSmith's SDK reads — no conditional logic needed anywhere else in the codebase."""

import os

from app.config import Settings


def configure_langsmith(settings: Settings) -> bool:
    """Enable LangSmith tracing via env vars if an API key is configured. Returns
    whether tracing is now active, so callers can log/report it without re-checking
    `settings`.

    The pinned `langsmith==0.0.87` SDK predates the `LANGSMITH_*` env var names — its
    `tracing_is_enabled()`/`get_tracer_project()` only ever read the older
    `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY`/`LANGCHAIN_PROJECT` names (verified
    against the installed package's `langsmith/utils.py`). Setting `LANGSMITH_*` alone
    silently no-ops `@traceable` — nothing reaches LangSmith even with a valid key
    configured. Both sets are set here so this keeps working if the pin is ever
    upgraded past the rename.
    """
    if not settings.langsmith_api_key:
        return False
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    return True
