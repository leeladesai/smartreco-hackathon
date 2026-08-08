"""OBS-1: LangSmith tracing, off by default. `@traceable` (imported directly by callers)
is a no-op unless tracing is enabled, so this only needs to flip the env vars LangSmith's
SDK reads — no conditional logic needed anywhere else in the codebase."""

import os

from app.config import Settings


def configure_langsmith(settings: Settings) -> bool:
    """Enable LangSmith tracing via env vars if an API key is configured. Returns whether
    tracing is now active, so callers can log/report it without re-checking `settings`.
    """
    if not settings.langsmith_api_key:
        return False
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    return True
