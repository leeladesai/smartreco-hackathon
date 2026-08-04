# AGENTS.md

## Start here

Before doing anything else, read `docs/08-Build-Status.md`. It tracks what's actually been built
(not just planned) and has a single "Next up" pointer to the current task. Pick that up, cross-
reference its FRD ID(s) in `docs/02-FRD.md` for acceptance criteria and `docs/06-LLD.md` for
schema/API/node details, then implement. When done: check the box, update "Next up" to the next
item per `docs/04-MVP-Roadmap.md`'s phase ordering, and commit the status-file change together with
the code — it must never drift into a second, stale plan.

## Project overview

SmartReco is a planned FastAPI application for an AI model/tool catalog recommendation agent. It
will track an AI engineer's browsing/comparison behavior, retrieve AI models with Chroma semantic
search, and generate grounded, comparison-driven recommendations through the Mesh API using a
LangGraph pipeline. See `docs/00-Domain-Decision.md` for why this domain (over alternatives like a
grocery/quick-commerce catalog) was chosen.

The repository is currently in the planning phase. The implementation directories (`app/`,
`tests/`) and the seed script referenced by the README do not exist yet. Do not assume that the
documented runtime commands work until MVP-0 scaffolding has been added.

## Source of truth

Read these documents before making architectural or product changes:

1. `docs/00-Domain-Decision.md` — why the AI model/tool catalog domain was chosen over the
   alternatives considered.
2. `docs/01-BRD.md` — business goals, scope, constraints, risks, and success metrics.
3. `docs/02-FRD.md` — functional requirements and requirement IDs (`AUTH`, `CAT`, `TRK`, `AGT`,
   `DLV`, `OBS`).
4. `docs/03-UX-Flows.md` and `docs/03-mockups.html` — personas, screens, and user flows.
5. `docs/04-MVP-Roadmap.md` — delivery order and definition of done.
6. `docs/05-HLD.md` — component boundaries and data flow.
7. `docs/06-LLD.md` — schema, API paths, trigger logic, and LangGraph node contracts.
8. `docs/07-Test-Strategy.md` — test cases mapped to requirements.
9. `docs/08-Build-Status.md` — current build status and the "Next up" pointer (see Start here).

When code and planning documents disagree, preserve the requirement IDs and update the relevant
design document as part of the change.

## Intended architecture

- FastAPI serves the API and server-rendered Jinja2/vanilla-JS UI.
- SQLAlchemy uses SQLite locally and should remain portable to Postgres.
- SQL is the source of truth for users, models, events, and recommendations.
- Chroma stores the semantic model index. Model create/edit/delete operations must keep SQL
  and Chroma synchronized and expose `vector_synced` when synchronization fails.
- Behavioral events are batched in the browser and ingested through `POST /api/events/batch`
  (`model_view`, `search`, `model_compare`, `dwell`, etc.).
- Event ingestion must stay cheap and must not call an LLM for every event.
- Trigger evaluation decides whether to start a background recommendation run.
- The recommendation pipeline is expressed as named LangGraph nodes: analyze activity, retrieve,
  grade/refine, generate, and store/deliver. The generated narrative is comparison-driven (e.g.
  "you've been comparing low-latency voice models").
- Every LLM call must use the Mesh API through its OpenAI-compatible base URL. Never add direct
  OpenAI, Anthropic, or Gemini calls outside Mesh configuration.
- Model catalog data (provider, modality, price, latency, context window) comes either from a
  Mesh models endpoint if available, or AI-assisted curation from public provider sources with a
  `source_url` kept per entry — see `docs/00-Domain-Decision.md` §6.

## Implementation order

Follow the roadmap unless a task explicitly changes scope:

1. MVP-0: auth, model creation plus dual-write, basic event ingestion, one real Mesh call,
   vector retrieval, and dashboard delivery.
2. Iteration 1: event batching/flush behavior, trigger thresholds and cooldown, activity-hash
   caching, full model CRUD, and sync-status handling.
3. Iteration 2: the full LangGraph pipeline, bounded grading/refinement retries, and grounded
   “why this” metadata.
4. Iteration 3: optional LangSmith tracing, scheduled digest delivery, and retrieval polish.

Keep tickets and tests tagged with their FRD ID, for example `[AGT-4]` or `[CAT-4]`.

## Configuration and secrets

- Copy `.env.example` to `.env` for local development.
- Keep `.env`, API keys, database files, and Chroma data untracked; `.gitignore` already covers
  them.
- Required configuration includes `MESH_API_KEY`, `DATABASE_URL`, `SECRET_KEY`, and
  `CHROMA_DB_PATH`.
- `LANGSMITH_API_KEY` and `SUBMISSION_TOKEN` are optional/CI-related values.
- Never commit real credentials or paste them into source code, tests, or documentation.

## Commands

The dependency manifest is `requirements.txt`. The intended setup and run flow is:

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
python seed_data.py
python -m uvicorn app.main:app --reload
```

Once implementation exists, use these checks before handing off a change:

```bash
pytest
pytest --cov=app
black --check .
flake8 .
```

At the time this file was created, those commands are partly aspirational because the application
and test directories have not been scaffolded.

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
