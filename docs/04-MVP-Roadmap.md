# MVP Definition & Agile Iteration Roadmap
## SmartReco — 2-week Scrum plan (4 sprints of ~2.5 days, or 2 sprints of ~1 week — pick per team availability)

Framework: Scrum-lite. Daily 10-min standup, sprint review = working demo, sprint retro = 10 min.
Definition of Done (DoD) for every ticket: code merged to `main`, CI green, README updated if setup
changed, linked FRD ID closed.

---

## MVP-0 — "Walking skeleton" (the absolute floor)

Goal: prove the whole request path end-to-end with a real (not mocked) LLM call, even if the agent
logic is trivial. This exists specifically to avoid the rubric's "faked/stubbed features" penalty —
by day 3 you already have a genuine Mesh API call, a genuine vector query, and a genuine dual-write.

Scope:
- AUTH-1, AUTH-2, AUTH-3, AUTH-4, AUTH-5, AUTH-6 (builder and admin login as separate modules from day 1 — cheap to do now, awkward to retrofit later)
- CAT-1, CAT-4 (create only, dual-write working)
- TRK-1, TRK-4 (tracking exists, naive per-event POST is acceptable here — batching comes next)
- AGT-3, AGT-5, AGT-7 (single-shot: retrieve top-k, one LLM call, no grading/refine/cache yet)
- DLV-1

Explicitly deferred: retries/grading, caching, batching, scheduling, observability.

---

## Iteration 1 — Production hardening of the core loop

Maps to: TRK-2, TRK-3, TRK-5, TRK-6, AGT-1, AGT-2, AGT-6, CAT-2, CAT-3, DLV-4, NFR-1, NFR-2, NFR-3

- Client-side event batching + `sendBeacon` flush
- Trigger engine (event-count / time-since-last / cooldown) replacing "call LLM every request"
- Activity-hash caching to skip redundant generations
- Full CRUD on models with sync-status surfaced
- Explicit `model_compare` event (compare tray) + same-modality view clustering in `analyze_activity`
- `GET /api/activity/me` (DLV-4) — read-only, reuses data already persisted for AGT-2/AGT-6/NFR-6
- This is the point where the "efficiency & production thinking" rubric line starts being satisfied

**Sprint review demo:** show two browsing sessions — one that changes the recommendation, one that
doesn't (proving the cache), plus network tab showing batched (not per-click) event calls.

---

## Iteration 2 — Real agentic depth (bonus scope begins)

Maps to: AGT-4 (grade & refine), FR bonus "structured agent framework" (LangGraph), DLV-2

- Convert the single-shot pipeline into the 5-node LangGraph graph (analyze → retrieve → grade/
  refine → generate → store)
- Bounded retry logic on weak retrieval
- Dashboard reflects "why this" tags sourced from retrieval metadata (UX principle)

**Sprint review demo:** deliberately weak query → show the retry/refine loop firing (via logs or
LangSmith if iteration 3 is already in place).

---

## Iteration 3 — Bonus polish (prioritize by team capacity, not all required)

Priority order (highest score-per-effort first, per team assessment):
1. **LangSmith observability (OBS-1)** — cheap to wire once the graph exists, high visible payoff for judges
2. **Scheduled digest (DLV-3)** — APScheduler job, real cron trigger, email or Telegram delivery
3. **Retrieval polish** — metadata filtering (category/price) before re-ranking; re-ranking only if time allows

---

## Final sprint — submission readiness

- README: architecture summary, setup steps, bonus features implemented, known limitations
- `.gitignore` includes `.env`; GitHub secrets (`MESH_API_KEY`, `SUBMISSION_TOKEN`) configured
- CI workflow file added, pushed, verified green in Actions tab
- Seed script populating demo users/models (curated AI-model catalog data, see
  `docs/00-Domain-Decision.md` §6) so judges see something real without manual setup
- Optional: deployed URL + 3–5 min demo video

---

## Backlog grooming note

Every ticket in Iterations 1–3 should carry its FRD ID in the title (e.g. `[AGT-4] grading node
with bounded retry`) so the eventual README/demo can map straight back to the rubric — this is a
cheap, high-value habit for a graded hackathon.
