# Business Requirements Document (BRD)
## SmartReco — Behavioral AI Recommendation Agent

| | |
|---|---|
| Project | SmartReco Build Challenge 2026 |
| Document owner | [Your name / team] |
| Version | 1.0 |
| Status | Draft for sprint 0 sign-off |

---

## 1. Background

SmartReco Build Challenge 2026 asks teams to build a catalog/marketplace platform where an
agentic AI system observes user behavior, retrieves relevant catalog items via RAG, and produces
persuasive, personalized recommendations that refresh as behavior evolves. Submissions are
screened by an automated system, then judged by humans. Faked features (hardcoded recs, unused
vector DB, unused LLM client) score poorly; efficient, production-minded AI usage is explicitly
rewarded.

The team chose an **AI model & tool catalog** as the domain — a catalog of AI models across
providers and modalities (LLM, voice, image, video) that users browse, search, and compare, with
the agent recommending models based on that evaluation behavior. See
[`docs/00-Domain-Decision.md`](00-Domain-Decision.md) for the alternatives considered and the
reasoning behind this choice; this domain replaces the learning-platform (courses/bootcamps)
domain used in the first planning pass.

## 2. Business objective

Deliver a working, demonstrable product that:
1. Proves the team can design and ship a real agentic AI system, not a scripted demo.
2. Scores maximally against the published rubric (functional completeness, efficiency/production
   thinking, bonus features).
3. Doubles as a portfolio-grade reference project for each team member.

## 3. Stakeholders

| Stakeholder | Interest |
|---|---|
| Hackathon organizers (Krish Naik / KrishAI) | Rubric compliance, valid Mesh API usage, code quality |
| Automated CI screener | Repo structure, dependency manifest, no syntax errors, secrets hygiene |
| Human judges (finalist round) | Depth of agentic reasoning, UX polish, demo quality |
| End users (simulated) | Two personas: **AI engineer** (browses/compares AI models) and **Curator** (manages the model catalog) |
| Team | Shippable, well-architected codebase within the 2-week window |

## 4. Scope

### 4.1 In scope (MVP + iterations — see MVP Roadmap doc)
- Email/password auth, two roles (user, admin/curator)
- Admin CRUD on the model catalog with dual-write to SQL + vector store
- Frontend behavioral event tracking (views, searches, comparisons, dwell time), batched
- Agent pipeline (LangGraph) that reasons over behavior, retrieves via RAG, grades retrieval,
  and generates persuasive, grounded recommendations
- Trigger + caching logic so the LLM is not called on every event
- Recommendations surfaced in-app and refreshed as behavior changes
- All LLM calls routed through Mesh API

### 4.2 Stretch scope (bonus, prioritized in later iterations)
- Scheduled proactive digest via email/Telegram (APScheduler/Celery Beat)
- LangSmith observability across the agent graph
- Retrieval polish: re-ranking / metadata filtering / better chunking

### 4.3 Out of scope
- Real payment processing / checkout
- Multi-tenant orgs, SSO, password reset flows
- Mobile native apps
- Horizontal scaling / multi-region infra (documented in HLD as a future concern only)

## 5. Success metrics

| Metric | Target |
|---|---|
| Automated CI checks | 100% pass (compiles, deps present, no committed secrets) |
| Functional rubric coverage | All "required" items in problem statement implemented and demoable |
| Bonus items implemented | ≥ 2 of 4 |
| LLM call efficiency | No LLM call fired on a single raw event; demonstrable caching/trigger logic |
| Grounding | 100% of recommended models traceable to vector DB retrieval results (no hallucinated models) |
| Demo readiness | Deployed URL + 3–5 min video by finalist deadline |

## 6. Assumptions

- Team has working knowledge of FastAPI, LangGraph, and a vector DB of choice (Chroma assumed as default).
- Mesh API key provisioning is self-serve and reliable within the hackathon window.
- SQLite is sufficient for the judged environment (Postgres kept as a config swap, not a hard requirement).
- Real or realistic AI-model catalog data (provider, modality, price, latency, context window) is
  obtainable within the delivery window — via a Mesh models endpoint if available, otherwise via
  AI-assisted curation from public provider sources (see `docs/00-Domain-Decision.md` §6).

## 7. Constraints

- Backend must be Python (Flask or FastAPI) — **FastAPI selected** (async support benefits both
  batched event ingestion and background agent runs).
- Every LLM/AI call must go through Mesh API — non-negotiable, CI-checked.
- No secrets committed; `.env` gitignored; `MESH_API_KEY` and `SUBMISSION_TOKEN` as GitHub Actions secrets.
- 2-week delivery window, team working part-time alongside other commitments.

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Over-engineering the agent graph, running out of time for polish | Medium | MVP0 ships with a minimal 3-node graph; grading/refine loop added in iteration 2 |
| LLM cost/rate limits during demo | Medium | Aggressive caching + trigger cooldown from day 1, not bolted on later |
| Vector DB / SQL drift (dual-write bugs) | High — directly penalized by rubric | `vector_synced` flag + idempotent upsert, covered by integration tests |
| Judges can't run the repo | High | README with one-command setup, CI badge, seed script for demo data |
| Model catalog data is thin, stale, or inaccurate | Medium — a judge familiar with the AI model landscape may notice | Curate with `source_url` per model; prefer a real Mesh models endpoint over hand-typed figures where available |
| Pitch overstates what's tracked (implies live tracking on Mesh's own site) | Medium — credibility risk with judges | Be explicit in demo/README: this is our own model-comparison catalog seeded with realistic data, inspired by and Mesh-API-powered, not live telemetry from `app.meshapi.ai` |

## 9. Deliverables (this SDLC package)

1. BRD (this document)
2. FRD — functional + non-functional requirements
3. UX flows + low-fidelity wireframes
4. MVP definition and iteration roadmap (Agile/Scrum)
5. HLD — system architecture
6. LLD — schema, API contracts, agent node contracts, sequence diagrams
7. Test strategy (TDD-driven) mapped to requirements
