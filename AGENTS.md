# AGENTS.md

## Start here

TrailMind's core recommendation loop (see "Project overview" below) is complete and verified live
against the real Mesh API — this isn't a partially-built walking skeleton. The platform has since
pivoted twice from its hackathon origin: first from single-tenant to multi-tenant
(`docs/design/09-Platform-Pivot-Decision.md`), then from tenant-scoped to widget-scoped
(`docs/design/10-Widget-Architecture.md`, M5) with a Next.js admin console replacing the original
server-rendered curator UI. If you're picking up new work, read `README.md` first for the current
feature set and known limitations, then `docs/design/10-Widget-Architecture.md`, then the rest of
"Source of truth" below for the reasoning behind them. A local-only `docs/design/08-Build-Status.md`
(gitignored, not present in a fresh clone) is used as a personal task tracker in active
development sessions — recreate it yourself if you want that workflow, but don't assume it exists.

## Project overview

TrailMind is a multi-tenant, embeddable behavioral recommendation platform. A tenant (a company)
runs one or more independently isolated **widgets** (e.g. "Credit Cards" vs "Personal Loans"),
each embedded on a host page via a tracker snippet + a chat-bot widget snippet. TrailMind tracks a
visitor's browsing/comparison behavior on that page, retrieves candidate catalog items via Chroma
semantic search scoped to that one widget, and generates grounded, comparison-driven
recommendations through the Mesh API using a 6-node LangGraph pipeline (analyze → retrieve →
rerank → grade/refine → generate → store), pushed to the visitor in real time over SSE.

The recommendation pipeline itself originated as a hackathon build for an AI model/tool catalog
domain — see `docs/design/00-Domain-Decision.md` for why that domain was chosen — and was proven
live end-to-end there before being generalized into today's domain-agnostic, multi-widget
platform. See `README.md` for the complete current feature list and
`docs/design/10-Widget-Architecture.md` for the widget-scoping architecture.

## Source of truth

Read these documents before making architectural or product changes, in this order:

1. `docs/design/10-Widget-Architecture.md` — **current state**: the widget entity, the
   tenant-key→widget-key breaking auth cutover, per-widget Chroma isolation, and the Next.js admin
   console. Read this first.
2. `docs/design/09-Platform-Pivot-Decision.md` — the post-hackathon decision to convert from a
   single-tenant demo into a multi-tenant, embeddable platform (tracker SDK, chat-bot widget,
   pluggable catalog ingestion, tenant onboarding flow). Superseded by document 1 above wherever
   the two disagree on scoping (tenant-level → widget-level).
3. `docs/design/00-Domain-Decision.md` — why the original AI model/tool catalog domain was chosen;
   still explains the origin of the agent architecture, not the current product scope.
4. `docs/design/01-BRD.md` — business goals, scope, constraints, risks, and success metrics
   (hackathon-era; out of date wherever it assumes a single tenant).
5. `docs/design/02-FRD.md` — functional requirements and requirement IDs (`AUTH`, `CAT`, `TRK`,
   `AGT`, `DLV`, `OBS`) — still the source for requirement-ID traceability in tests even though
   some requirements have since moved from tenant-scoped to widget-scoped.
6. `docs/design/03-UX-Flows.md` and `docs/design/03-mockups.html` — personas, screens, and user
   flows (hackathon-era single-tenant UI; the actual current UI is the Next.js admin console under
   `frontend/`).
7. `docs/design/04-MVP-Roadmap.md` — delivery order and definition of done (hackathon-era).
8. `docs/design/05-HLD.md` and `docs/design/06-LLD.md` — component boundaries, schema, and API
   contracts (hackathon-era; the current schema/API surface is `app/models.py` and `app/main.py`
   directly plus document 1 above — these have not been rewritten inline).
9. `docs/design/07-Test-Strategy.md` — test cases mapped to requirements.

When code and planning documents disagree, trust the code and `docs/design/10-Widget-Architecture.md`
first, then update whichever older design document is now stale as part of the change — preserve
requirement IDs when you do.

## Intended architecture

- FastAPI serves the JSON API only. The admin console is a separate Next.js app (`frontend/`)
  authenticating with a bearer JWT, never a cookie — see `frontend/src/lib/api.ts`.
- SQLAlchemy uses SQLite locally and should remain portable to Postgres.
- SQL is the source of truth for tenants, widgets, catalog items, events, and recommendations.
- Chroma stores the semantic catalog index, **one collection per widget**
  (`{collection_name}_widget_{widget_id}`) — this is the actual cross-product-leakage isolation
  boundary, not `tenant_id`. Catalog item create/edit/delete operations must keep SQL and Chroma
  synchronized and expose `vector_synced` when synchronization fails.
- Behavioral events are batched in the browser and ingested through `POST /api/track/events`,
  authenticated with a per-widget key (`item_view`, `search`, `compare`, `dwell`, etc.).
- Event ingestion must stay cheap and must not call an LLM for every event.
- Trigger evaluation decides whether to start a background recommendation run, scoped to one
  widget's catalog.
- The recommendation pipeline is expressed as named LangGraph nodes: analyze activity, retrieve,
  grade/refine, generate, and store/deliver, then pushed to the visitor's open widget over SSE
  (`GET /api/widget/stream`), falling back to polling on connection failure. The generated
  narrative is comparison-driven and strictly grounded in that widget's own catalog data.
- Every LLM call must use the Mesh API through its OpenAI-compatible base URL. Never add direct
  OpenAI, Anthropic, or Gemini calls outside Mesh configuration.
- Catalog item data (`title`, `provider`, `category`, `price`, free-form `specs` label/value
  pairs) is tenant/widget-owned data ingested via one of three adapters — manual entry, feed/API
  pull, or DOM scrape — never platform-curated. See `docs/design/09-Platform-Pivot-Decision.md`
  §3.3 and `app/services/ingestion.py`.

## Implementation order

The hackathon-era build followed `docs/design/04-MVP-Roadmap.md`'s phase ordering — auth and
dual-write first, then event batching/triggers, then the full LangGraph pipeline with grounded
"why this" metadata, then tracing/digest/retrieval polish. Post-hackathon work has followed the
platform-pivot phases instead: multi-tenant foundation → tracker SDK → catalog ingestion adapters
→ chat-bot widget → widget entity/breaking auth cutover (M5) → admin console polish. New work
doesn't need to follow either sequence exactly, but should still keep tests tagged with their FRD
ID (for example `[AGT-4]` or `[CAT-4]`) so behavior stays traceable back to
`docs/design/02-FRD.md`.

## Configuration and secrets

- Copy `.env.example` to `.env` for local development.
- Keep `.env`, API keys, database files, and Chroma data untracked; `.gitignore` already covers
  them.
- Required configuration includes `MESH_API_KEY`, `DATABASE_URL`, `SECRET_KEY`, and
  `CHROMA_DB_PATH`.
- `LANGSMITH_API_KEY` and `SUBMISSION_TOKEN` are optional/CI-related values.
- Never commit real credentials or paste them into source code, tests, or documentation.

## Commands

Dependencies are managed with `uv` (`pyproject.toml` / `uv.lock`; `requirements.txt` is kept in
sync for tooling that expects it). Setup and run flow:

```bash
uv sync
source .venv/bin/activate      # Windows: .venv\\Scripts\\activate
cp .env.example .env           # fill in MESH_API_KEY=rsk_...
uv run python seed_data.py
uv run uvicorn app.asgi:app --reload --port 8001
```

Or use the one-command dev startup (defaults to port 8001, override with `PORT=8002`):

```bash
./scripts/start_dev.sh
```

Checks to run before handing off a backend change:

```bash
uv run pytest
uv run pytest --cov=app
uv run black --check .
uv run flake8 .
```

The admin console lives in `frontend/` (Next.js 16 App Router, npm). Setup:

```bash
cd frontend
npm install
# .env.development: NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:<backend port>
npm run dev
```

Checks to run before handing off a frontend change:

```bash
cd frontend
npx tsc --noEmit
npx eslint .
npm run build
```

## Testing expectations

Use TDD for new behavior: add a failing test mapped to an FRD ID before implementation where
practical. Prioritize:

- authentication hashing and admin authorization;
- SQL/Chroma dual-write consistency and failure flags;
- bulk event ingestion and malformed-event handling;
- trigger threshold, cooldown, and activity-hash cache behavior;
- retrieval grounding and bounded grade/refine retries;
- filtering LLM-returned model IDs against retrieved candidates;
- asserting that the configured LLM client uses the Mesh base URL.

Mock Mesh calls in normal CI tests to avoid spend and nondeterminism. Use temporary/in-memory test
storage for SQLite and Chroma. Real Mesh smoke tests should be manual or isolated to a deliberate
nightly check.

## Coding and design conventions

- Keep FastAPI routes thin; put business logic in testable services or agent nodes.
- Prefer async/non-blocking request paths, especially event ingestion.
- Use typed Pydantic request/response models and explicit SQLAlchemy models.
- Keep agent nodes small, named, and independently testable rather than building one monolithic
  prompt/function.
- Validate LLM output server-side. Never trust model IDs returned by the LLM without checking
  them against the retrieval set.
- Enforce roles server-side with dependencies; hiding UI controls is not authorization.
- Preserve traceability: record recommendation `activity_hash`, `trigger_reason`, and timestamps.
- Update `README.md` when setup, commands, supported features, or known limitations change.

## Change checklist

Before completing a feature:

- Identify the relevant BRD/FRD requirement IDs.
- Update the applicable design or roadmap document if behavior or architecture changes.
- Add or update unit, integration, or contract tests.
- Run the available formatting, linting, and test checks.
- Verify no secrets, generated databases, Chroma files, or unrelated files were added.
- Keep the README and this guide accurate about what is implemented versus planned.
