# High-Level Design (HLD)
## TrailMind — Embeddable Behavioral Recommendation Platform

Updated per [`09-Platform-Pivot-Decision.md`](09-Platform-Pivot-Decision.md). The original
component-level architecture diagram (deployment boundary, both loops, the 6-node agent pipeline,
SQL/vector databases, single external LLM call) is at
[`05-architecture-diagram.md`](05-architecture-diagram.md) — still structurally accurate for the
interaction/recommendation loop split; it does not yet show the tenant, tracker-SDK, ingestion, or
real-time-push additions below. This document is the prose/tabular companion.

## 1. Architecture overview

Three loops now, sharing tenant-scoped storage (the third is new):

- **Interaction loop** (synchronous, cheap): Tracker SDK (on a host page we don't own) → FastAPI →
  SQL DB / Vector DB, both tenant-scoped. Handles catalog ingestion writes and event ingestion. No
  LLM calls anywhere in this path.
- **Recommendation loop** (asynchronous, LLM-bearing): a trigger evaluator (invoked after event
  ingestion, cheaply) decides whether to kick off the LangGraph agent for that tenant+visitor,
  which reads from both data stores (scoped to that tenant), calls Mesh API, and writes back a
  recommendation.
- **Real-time delivery loop** *(new)*: when a recommendation is stored, it's pushed over a
  persistent connection (SSE/WebSocket) to that visitor's open chat-bot widget, rather than
  waiting for the widget to poll or the visitor to reload.

The interaction/recommendation split is unchanged in spirit from the hackathon build — it's still
what lets the system satisfy "track everything" and "don't call the LLM on every action." The
real-time loop is the new piece that makes it a live platform rather than a dashboard the visitor
has to come back and check.

## 2. Components

| Component | Responsibility | Tech |
|---|---|---|
| Tracker SDK *(was: tracking client)* | Embeddable snippet on a tenant's host page; batches behavioral events, flushes via beacon/timer, tags `tenant_id` + anonymous visitor id, cross-origin | JS module, no dependencies, async-loaded |
| Chat-bot widget *(new)* | Persistent launcher on the host page; opens proactively on a pushed trigger; renders narrative + catalog-item cards; carries follow-up Q&A, catalog-grounded only | JS module, style-isolated (iframe or shadow DOM — open, §5 of pivot record) |
| Catalog ingestion service *(new)* | Normalizes a tenant's catalog from any of three adapters (feed/API pull, DOM scrape, manual entry) into the shared catalog schema + tenant's vector index | FastAPI service + scheduled sync jobs |
| API layer | Tenant onboarding/auth, catalog CRUD (manual adapter + reference tenant), event ingestion, recommendation read, real-time push endpoint | FastAPI |
| Trigger evaluator | Decides if/when to run the agent for a given tenant+visitor | Runs inline after event batch insert, cheap SQL check (no LLM) |
| Agent worker | LangGraph pipeline: analyze → retrieve → rerank → grade/refine → generate → store, scoped per tenant | LangGraph + Mesh API (OpenAI-compatible client) |
| Real-time push service *(new)* | Delivers a stored recommendation to an open widget session within seconds | SSE or WebSocket (transport choice open, §5 of pivot record) |
| SQL database | Source of truth: tenants, users, catalog items, events, recommendations — all tenant-scoped | SQLite (dev) / Postgres (prod-shaped) via SQLAlchemy |
| Vector database | Semantic index of each tenant's own catalog | Chroma, one collection (or namespace) per tenant |
| Tenant/admin console *(was: admin UI)* | Onboard a site, configure catalog ingestion adapters, manage manual entries, view per-tenant analytics | Jinja2 templates + vanilla JS |
| Scheduler (bonus) | Daily digest trigger, per tenant; also drives feed-adapter sync | APScheduler, in-process |
| Observability (bonus) | Trace agent runs, filterable per tenant | LangSmith |

The reference AI-model-catalog tenant (see `docs/00-Domain-Decision.md`) remains a valid tenant on
this platform — its entity shape and comparison-oriented attributes are unchanged — but it is no
longer the platform's only subject.

## 3. Data flow

1. Tracker SDK on the tenant's host page batches events (item views, searches, comparisons, dwell
   time) → `POST /api/events/batch` (cross-origin, tenant API key) → bulk insert into `events`,
   tagged `tenant_id` + visitor id.
2. Same request, after insert, cheaply checks the trigger condition for that tenant+visitor
   (count/time/cooldown — no LLM call). If satisfied, enqueues an agent run scoped to that
   tenant+visitor (background task; a real queue remains a documented upgrade path, §6).
3. Agent worker pulls recent events for that tenant+visitor, summarizes behavior, embeds a
   retrieval query, queries that tenant's vector index, grades results, generates a
   comparison-driven narrative via Mesh API using only that tenant's catalog facts, writes to
   `recommendations`.
4. **Real-time push** *(new)*: storing the recommendation triggers a push to that visitor's open
   widget session over SSE/WebSocket. If no session is open, the recommendation is still persisted
   and available on the widget's next open (graceful degradation, not a hard real-time
   requirement).
5. Chat-bot widget renders the pushed narrative + item cards; follow-up questions route back
   through the same catalog-grounded retrieval path, not a separate ungrounded chat completion.
6. Activity view (where a tenant exposes it) reads raw `events` plus the
   `behavior_summary`/`activity_hash`/`trigger_reason` already persisted on that same
   `recommendations` row — unchanged read-only pattern from the hackathon build, now tenant-scoped.
7. Catalog ingestion service independently syncs feed/scrape adapters on a schedule (or on
   snippet-reported DOM changes for scrape), writing into the same tenant catalog + vector index
   path CAT-1..4 already uses for manual entry.
8. (Bonus) Scheduler independently sweeps active tenants+visitors on a cron and reuses the same
   agent pipeline to produce and email/Telegram a digest.

## 4. Why these tech choices

Unchanged from the hackathon build and still valid at platform scale:
- **FastAPI over Flask**: async support matters more now, not less — cross-origin event ingestion
  under real (not synthetic) bursty traffic, plus a persistent-connection push service, both
  benefit from it.
- **Chroma**: still viable per-tenant at moderate tenant counts (one collection/namespace per
  tenant); revisit if tenant count or per-tenant catalog size grows enough to need a managed
  vector DB — not yet a blocker.
- **LangGraph for the agent**: unchanged — each stage (retrieve, grade, generate) stays a clean,
  independently testable seam, which matters more, not less, once grounding correctness is a
  compliance concern (banking-style tenants) rather than a rubric line item.
- **In-process background task vs. a full message queue**: revisit sooner than the hackathon build
  assumed — real-time push and multi-tenant trigger volume are exactly the conditions that make a
  real queue (Celery/Redis or similar) worth its infra cost. Flagged as a near-term upgrade, not
  immediately required.

## 5. Security & config

- Passwords hashed (passlib/bcrypt); session via signed cookie or short-lived JWT, carrying
  `tenant_id`.
- End-user and tenant-admin auth are separate router modules (`/api/auth/*` vs `/api/admin/login`)
  — the end-user module can never mint an admin role, and there is no admin self-registration
  endpoint.
- Admin routes protected by a server-side dependency (`require_role(...)`) that also checks
  `tenant_id` match — never client-side-only, never cross-tenant.
- Tracker SDK/ingestion requests authenticate via a per-tenant API key (hashed at rest, rotatable —
  TEN-4/TEN-5 in the FRD); CORS restricted to that tenant's registered domain(s).
- No PII/PCI fields ever captured in tracked events, across all three ingestion adapters — a hard
  constraint now that a tenant may be regulated (e.g. banking).
- `MESH_API_KEY` read from environment only; `.env` gitignored.

## 6. Explicit non-goals / open design work

Non-goals (still out of scope, unchanged reasoning from the hackathon build):
- Horizontal scaling, multi-region — not needed yet; noted so the design isn't mistaken for an
  oversight.
- Real payment processing, mobile native apps.

Open design work (raised in the pivot record, deliberately not decided here):
- Real-time transport: WebSocket vs. SSE, and fallback behavior when neither is reachable
  (corporate proxy, older browser).
- Widget style isolation: iframe vs. shadow DOM.
- DOM-scrape adapter health signal: how staleness/breakage is detected and surfaced (ING-5).
- Cookie-consent integration for third-party tracking.
- Multi-tenant auth model details: key rotation grace period, per-tenant rate limiting.

## 7. Deployment view

Single container or single VM remains viable for moderate tenant counts: FastAPI app (serves
templates + API + real-time push endpoint), SQLite file or managed Postgres, Chroma persisted to
disk (namespaced per tenant), `.env` injected via platform secret store. A persistent-connection
push service is the one new deployment consideration versus the hackathon build — confirm the
hosting platform supports long-lived SSE/WebSocket connections, not just short request/response
cycles, before committing to a host.
