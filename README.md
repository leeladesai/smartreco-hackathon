# SmartReco — Behavioral AI Recommendation Agent
## Krish Naik Hackathon 2026 Submission

An agentic AI system that observes AI-engineer behavior (searches, model views, comparisons),
retrieves relevant models from a catalog via RAG + vector search, and generates grounded,
persuasive, comparison-driven recommendations that refresh as behavior evolves — with a
cron-scheduled digest and full pipeline tracing on top.

**Status: MVP-0 through Iteration 3 (all bonus scope) are complete and verified live against the
real Mesh API.** See "Known limitations" below for what's deliberately out of scope or descoped.

---

## 🏗️ Architecture summary

Single FastAPI process serves both the JSON API and the server-rendered frontend (Jinja2 templates
+ vanilla JS) — one container, no separate frontend build/deploy. No client-side framework, no
separate frontend service.

- **Auth**: two independent modules — AI-engineer (`/api/auth/*`) and admin/curator
  (`/api/admin/login`), server-side role checks on every admin route, no admin self-registration.
- **Catalog**: SQLite (via SQLAlchemy) is the system of record; every create/edit/delete
  dual-writes into a Chroma vector store in the same request, with a `vector_synced` flag so a
  partial failure is visible, never silent.
- **Behavioral tracking**: events batch client-side (size/timer/`sendBeacon`-on-unload), never one
  network call per click, and ingestion never blocks on the agent pipeline.
- **Agent pipeline**: a 5-node LangGraph graph — `analyze → retrieve → grade/refine → generate →
  store` — triggered by a cheap event-count/cooldown check (`AGT-1`), not per-event. Grading
  bounds retries at 2 on weak retrieval; generation never runs more than once per trigger
  regardless of retries. The pipeline runs in a FastAPI background task, not inline on the
  ingestion request (see NFR-1 below).
- **Delivery**: dashboard shows the latest recommendation, with a "Because you looked at these"
  evidence row (itemized, deduped, current-session activity) and a per-model "why this" tag
  computed deterministically from that same evidence — a latency win against models the user
  actually compared/viewed, or a search-term match on the candidate's own use-case tags — falling
  back to a retrieval-distance label only when neither applies. Polls for freshness so a stale
  recommendation is never shown after a new background run completes. A cron-scheduled digest
  (APScheduler) re-runs the pipeline per user and delivers via email/Telegram/log-fallback.
- **Observability**: every agent run persists `trigger_reason` + timestamps regardless of
  LangSmith; LangSmith tracing wraps every graph node plus the Mesh call itself, opt-in via
  `LANGSMITH_API_KEY`.

See `docs/06-LLD.md` for the full schema/API/node contracts and `docs/05-architecture-diagram.md`
for the component diagram.

---

## 📋 SDLC Documentation (complete planning phase)

Read in order:

1. **[docs/00-Domain-Decision.md](docs/00-Domain-Decision.md)** — Domain decision record: options
   considered, scoring, and why the AI model/tool catalog was chosen
2. **[docs/01-BRD.md](docs/01-BRD.md)** — Business Requirements: objectives, scope, success metrics
3. **[docs/02-FRD.md](docs/02-FRD.md)** — Functional Requirements: AUTH, CAT, TRK, AGT, DLV, OBS modules
4. **[docs/03-UX-Flows.md](docs/03-UX-Flows.md)** — UX Design: personas, flows, screen specs
5. **[docs/03-mockups.html](docs/03-mockups.html)** — Wireframes (open in a browser) — design
   reference only; not served as live app code
6. **[docs/04-MVP-Roadmap.md](docs/04-MVP-Roadmap.md)** — Agile sprint plan: MVP-0 → Iteration 3 → submission
7. **[docs/05-HLD.md](docs/05-HLD.md)** — High-level architecture, components, tech choices
8. **[docs/05-architecture-diagram.md](docs/05-architecture-diagram.md)** — component diagram: deployment boundary, both loops, agent pipeline, SQL/vector DBs, external LLM call
9. **[docs/06-LLD.md](docs/06-LLD.md)** — DB schema, API contracts, LangGraph node contracts
10. **[docs/07-Test-Strategy.md](docs/07-Test-Strategy.md)** — TDD test plan mapped to FRD IDs

---

## 🎯 Key decisions

| Decision | Choice |
|---|---|
| Backend | FastAPI (async, non-blocking) |
| Frontend | Jinja2 server-rendered templates + vanilla JS — no React/TS/Streamlit, one container |
| LLM integration | Mesh API only (mandatory) — `MeshNarrativeGenerator`, no direct OpenAI/Anthropic/Gemini SDK calls |
| Vector database | Chroma (local, zero external deps) |
| Agent framework | LangGraph (5 named, independently testable nodes) |
| Scheduling | APScheduler (real cron, not a manual trigger) |
| Observability | LangSmith, opt-in via env var |
| Domain | AI model & tool catalog (comparison-based recs) — see `docs/00-Domain-Decision.md` |
| Database | SQLite (dev) / Postgres-shaped schema (prod) |
| Testing | pytest, TDD-driven |

---

## 🚀 Quick start

```bash
cd smartreco-hackathon
uv sync
source .venv/bin/activate      # Windows: .venv\Scripts\activate
cp .env.example .env           # fill in MESH_API_KEY=rsk_...
uv run python seed_data.py
uv run uvicorn app.asgi:app --reload --port 8001
```

Open http://localhost:8001

Seeded demo logins:
- AI engineer: `engineer@smartreco.dev` / `engineer@123`
- Curator/admin: `curator@smartreco.dev` / `admin@123`

Without a `MESH_API_KEY`, the app still runs end to end — the dashboard honestly stays in
retrieval-ready mode (real Chroma retrieval, no fabricated narrative) instead of faking output.

### One-command development startup

```bash
./scripts/start_dev.sh          # start (detached) and tail the log
./scripts/start_dev.sh stop     # stop it
./scripts/start_dev.sh restart
./scripts/start_dev.sh status
./scripts/start_dev.sh logs     # just tail, without starting/stopping anything
```

Uses port `8001` by default. Override with `PORT=8002 ./scripts/start_dev.sh`. The server runs
detached — Ctrl-C only stops the log tail, not the server itself; use `stop` (or `restart`) for
that. SmartReco is one FastAPI process serving both the API and the server-rendered frontend, so
there's a single log stream, not separate frontend/backend logs.

### Running tests

```bash
pytest
```

---

## 📁 Project structure

```
smartreco-hackathon/
├── docs/                 # SDLC documentation (complete)
├── app/
│   ├── main.py            # routes, app wiring, scheduler registration
│   ├── models.py          # SQLAlchemy schema
│   ├── vector.py          # Chroma wrapper (dual-write, metadata filtering)
│   ├── services/
│   │   ├── agent_graph.py   # the 5-node LangGraph pipeline
│   │   ├── recommendation.py# trigger check, behavior summary, activity hash
│   │   ├── mesh.py          # Mesh API client (the only LLM call boundary)
│   │   ├── digest.py        # scheduled digest + notifier abstraction
│   │   ├── tracing.py       # LangSmith opt-in wiring
│   │   └── observability.py # admin-portal LangSmith run viewer (OBS-2)
│   ├── templates/          # Jinja2 per-screen templates extending base.html
│   └── static/{css,js}/    # shared styling + frontend logic
├── tests/                # pytest suite (TDD)
├── seed_data.py           # demo users + curated model catalog
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## ✅ What's implemented

Every FRD module (AUTH, CAT, TRK, AGT, DLV, OBS) and every NFR is implemented and covered by
tests. See `docs/02-FRD.md` for full acceptance criteria and `docs/08-Build-Status.md` (local-only,
gitignored) for the live build tracker.

**Core loop (MVP-0 + Iteration 1):** registration/login for two independent roles; full catalog
CRUD with dual-write to Chroma and a visible `vector_synced` flag; client-batched behavioral
tracking (`sendBeacon` on unload, never per-click); a trigger engine (event count + cooldown)
instead of calling the LLM on every event; activity-hash caching so unchanged behavior never
re-triggers generation.

**Real agentic depth (Iteration 2, bonus scope):** the pipeline is a genuine 5-node LangGraph graph
(`analyze → retrieve → grade/refine → generate → store`), not a single-shot prompt — with bounded
retry (max 2) on weak retrieval, and per-model "why this" tags on the dashboard computed
deterministically from the user's actual session evidence (see below), not canned text. The
dashboard polls for a fresher recommendation rather than ever showing a stale one after a
background run completes.

**Bonus polish (Iteration 3, all three items done, not just prioritized):**
- LangSmith trace per pipeline run, opt-in via `LANGSMITH_API_KEY` — every graph node plus the
  Mesh call itself is instrumented.
- A real cron-scheduled digest (APScheduler `CronTrigger`, default daily) that re-runs the
  pipeline per user and delivers via email (per-user) or Telegram, falling back to logging if
  neither is configured rather than silently dropping the run. A `POST /api/admin/digest/run`
  admin endpoint exists only to demo it on demand, not as the primary delivery path.
- Chroma metadata pre-filtering (by modality) on the first retrieval pass before any re-ranking,
  derived from the same same-modality browsing signal already used in behavior summaries.

**Non-functional requirements:** `NFR-1` (ingestion <150ms p95) required an actual fix, not just a
measurement — the triggered pipeline's live Mesh call was originally blocking the ingestion
response; it now runs in a `BackgroundTasks` job, verified live at ~50ms response time.
`NFR-2` (≤1 LLM call per trigger) is guaranteed by the graph's structure and covered by a test that
forces two retries and asserts the Mesh call still only fires once.

---

## 🎁 Post-roadmap enhancements

Beyond the original FRD/roadmap scope, built and verified live in a follow-up hardening pass:

- **Session-aware recommendation weighting** — the current browsing session dominates the
  recommendation over older, diluted history (geometric decay per inactivity-gap session bucket)
  instead of a flat "last 20 events" window; fixes a real bug where a 3-way modality tie across
  sessions disabled retrieval filtering entirely.
- **Dashboard evidence + grounded "why this" tags** — a "Because you looked at these" row shows
  the itemized, deduped activity from the current session; each recommendation card's reason is
  computed deterministically (a latency win against models actually compared/viewed, or a
  search-term match on the candidate's own use-case tags) rather than a flat distance label. The
  top narrative is now intent-framed (e.g. "building a real-time voice agent") because the Mesh
  prompt was fixed to actually receive price/latency/context-window/use-case-tag facts it was
  previously silently dropping.
- **Curator "story" field wired end-to-end** — the persuasive "why this model" text captured in
  the admin console previously never reached the database or the Mesh prompt; it's now a real
  column, folded into both the Chroma embedding text and the narrative-generation candidate data.
- **Catalog expansion via Mesh** — `scripts/expand_catalog_via_mesh.py` grew the seed catalog from
  9 to 27 models using the Mesh LLM itself, validated through the existing dual-write path.
- **Engagement features**: copy-to-clipboard on a model's identifier (tracked as its own event
  type), a client-side watchlist/wishlist that feeds the same recommendation signal as views and
  comparisons, and a content-similarity "you might also be interested in" endpoint
  (`/api/models/{id}/related`) distinct from the activity-driven dashboard recommendation.
- **Judge demo mode** — an admin-only, global toggle (`GET`/`PUT /api/settings/demo-mode`) that
  shows a live queued→sent event-tracking overlay in the model drawer/detail page for every
  AI-engineer session. Off by default so it never surfaces during normal use; meant only for live
  pipeline demonstrations.
- A real per-user `asyncio.Lock` fixing a genuine race condition that could produce duplicate
  `Recommendation` rows from two near-simultaneous qualifying event batches.
- **Admin observability dashboard** (`OBS-2`) — an admin-only `/admin/observability` screen pulls
  recent `agent_pipeline` LangSmith runs (status, latency, error, trace link) directly into the
  admin portal via `GET /api/admin/observability/runs`, so a curator can see whether the last few
  pipeline runs succeeded without a separate LangSmith login. Requires `OBS-1`'s
  `LANGSMITH_API_KEY` to be set; shows a clear "not configured" state otherwise rather than
  erroring.

---

## ⚠️ Known limitations

- **Telegram digest delivery is a single broadcast chat**, not per-user — there's no per-user
  Telegram chat-id field on the `User` model in this MVP. Email delivery *is* per-user (via the
  existing `User.email`). Configure whichever fits your judge/demo setup, or leave both unset to
  see the honest logging fallback.
- **No re-ranking step** — retrieval polish (Iteration 3) stopped at metadata pre-filtering; the
  catalog is small enough in this MVP that a re-ranking pass wasn't worth the added complexity.
- **Retrieval embeddings are a deterministic hashed bag-of-words function (`app/vector.py`), not a
  real embedding model** — a documented cost/scope tradeoff, not an oversight. It's stable
  (identical text always maps to the same vector) and dependency-light, so grounding and
  same-modality filtering work reliably, but it only captures exact/near-exact term overlap — a
  paraphrased query like "fast realtime speech" won't score as well against catalog copy that
  says "low-latency voice" as literal keyword overlap would. Swapping in a real embedding model
  (Mesh likely exposes one) would fix this; not done here because the current catalog size and
  demo scenarios don't yet expose the gap in practice.
- **No production deployment or demo video** — both were optional per the roadmap and weren't
  prioritized over completing functional/bonus scope.
- **`recommendation_triggered` in the `/api/events/batch` response** reflects `should_trigger`
  (`recommendation.py`): the session-activity-count threshold *and* the same cheap SQL AGT-6
  cooldown/hash-dedupe check the graph's `analyze` node uses (`is_recommendation_stale`), so it
  no longer fires on every batch in an already-triggered session. It still can't know whether
  the *generation* step will actually succeed (a real Mesh call, which only runs in the
  background per the NFR-1 fix) — that part of the outcome genuinely isn't knowable
  synchronously without reintroducing the latency problem NFR-1 fixes.

---

**Status:** ✅ Planning phase complete. MVP-0 through Iteration 3 implemented and verified live
against the real Mesh API. CI's critical checks all pass (compiles, requirements, Mesh usage, Mesh
key valid) — the job only fails at the organizer's result-recording step until the hackathon
dashboard submission form is filled in. Remaining: submit that form, and optionally a deployed URL
+ demo video.
