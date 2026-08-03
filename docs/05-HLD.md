# High-Level Design (HLD)
## SmartReco

## 1. Architecture overview

Two decoupled loops sharing storage:

- **Interaction loop** (synchronous, cheap): Browser → FastAPI → SQL DB / Vector DB. Handles auth,
  catalog CRUD, and event ingestion. No LLM calls anywhere in this path.
- **Recommendation loop** (asynchronous, LLM-bearing): a trigger evaluator (invoked after event
  ingestion, cheaply) decides whether to kick off the LangGraph agent, which reads from both data
  stores, calls Mesh API, and writes back a recommendation.

This separation is the core architectural decision behind the whole design — it's what lets the
system satisfy both "track everything" and "don't call the LLM on every action."

## 2. Components

| Component | Responsibility | Tech |
|---|---|---|
| Web frontend | Catalog browsing, product pages, dashboard, admin UI | Jinja2 templates + vanilla JS |
| Tracking client | Batches behavioral events, flushes via beacon/timer | JS module, no dependencies |
| API layer | Auth, catalog CRUD, event ingestion, recommendation read | FastAPI |
| Trigger evaluator | Decides if/when to run the agent for a user | Runs inline after event batch insert, cheap SQL check (no LLM) |
| Agent worker | LangGraph pipeline: analyze → retrieve → grade/refine → generate → store | LangGraph + Mesh API (OpenAI-compatible client) |
| SQL database | Source of truth: users, products, events, recommendations | SQLite (dev) / Postgres (prod-shaped) via SQLAlchemy |
| Vector database | Semantic index of products | Chroma (local, zero external deps — good fit for a graded repo) |
| Scheduler (bonus) | Daily digest trigger | APScheduler, in-process |
| Observability (bonus) | Trace agent runs | LangSmith |

## 3. Data flow (see also companion diagrams already shared in chat)

1. Browser batches events → `POST /api/events/batch` → bulk insert into `events`.
2. Same request, after insert, cheaply checks the trigger condition for that user
   (count/time/cooldown — no LLM call). If satisfied, enqueues an agent run
   (in-process background task via FastAPI `BackgroundTasks`, or a lightweight queue if the team
   wants real async decoupling — see §6).
3. Agent worker pulls recent events, summarizes behavior, embeds a retrieval query, queries the
   vector DB, grades results, generates narrative via Mesh API, writes to `recommendations`.
4. Dashboard reads the latest row from `recommendations` for the logged-in user.
5. (Bonus) Scheduler independently sweeps active users on a cron and reuses the same agent
   pipeline to produce and email/Telegram a digest.

## 4. Why these tech choices

- **FastAPI over Flask**: native async support matters for two things in this spec — non-blocking
  event ingestion under bursty tracking traffic, and cleanly kicking off background agent runs
  without extra infra. Flask is an equally valid rubric choice; this is a team preference, not a
  requirement.
- **Chroma over Pinecone/Qdrant**: local, file-based, zero external account/API key needed — reduces
  setup friction for judges running the repo, satisfies NFR-7 (portability).
- **LangGraph for the agent**: makes "structured agent framework" (explicit bonus) a natural
  outcome of the design rather than a bolt-on, and gives each stage (retrieve, grade, generate) a
  clean seam for unit testing (see Test Strategy).
- **In-process background task over a full message queue (Celery/Redis)**: right-sized for a
  2-week hackathon and a judged demo — a real external queue is a legitimate upgrade path (documented
  as a "future work" note, not built) but adds infra risk without rubric payoff.

## 5. Security & config

- Passwords hashed (passlib/bcrypt); session via signed cookie or short-lived JWT.
- Admin routes protected by a server-side dependency (`require_role("admin")`), never
  client-side-only.
- `MESH_API_KEY` read from environment only; `.env` gitignored; CI secrets configured per submission
  instructions.

## 6. Explicit non-goals / future work

- Horizontal scaling, multi-region, real message broker — not needed for this deliverable; noted
  here so the design isn't mistaken for an oversight.
- Multi-tenant/org support, SSO, password reset — out of scope per BRD §4.3.

## 7. Deployment view (optional finalist bonus)

Single container or single VM: FastAPI app (serves templates + API), SQLite file or managed
Postgres, Chroma persisted to disk, `.env` injected via platform secret store (Railway/Render/Fly —
team's choice). No separate frontend build step since templates are server-rendered.
