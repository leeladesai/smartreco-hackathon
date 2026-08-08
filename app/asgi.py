"""Real ASGI entrypoint (`uvicorn app.asgi:app`) — kept separate from `app/main.py` so
that importing `create_app` (as every test does, via `from app.main import create_app`)
never has the side effect of building a real, `.env`-configured app instance. Building
one always runs `configure_langsmith()`; with a real `LANGSMITH_API_KEY` in `.env`, that
used to be harmless (the old env var names it set were ignored by the pinned SDK) but
now genuinely opens background network threads to LangSmith the moment the module
importing `create_app` is loaded — including under pytest, before any test's own
`Settings()` override ever gets a chance to run.
"""

from app.main import create_app

app = create_app()
