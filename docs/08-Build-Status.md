# Build Status

## SmartReco

This file tracks what's actually built, not what's planned — `docs/04-MVP-Roadmap.md` remains the
spec of record for scope and phase ordering, `docs/02-FRD.md` for acceptance criteria per ID, and
`docs/06-LLD.md` for schema/API/node contracts. This file only answers two questions: **what's
done**, and **what's next**.

**Convention:** whoever closes an item (Claude or Codex) checks the box and updates "Next up" as
part of the same commit as the code — don't let this drift into a second, stale plan.

---

## Next up

> Data layer first: SQLAlchemy models (`users`, `models`, `events`, `recommendations`), the Chroma
> collection, and a single `create_model()` service function that dual-writes both and sets
> `vector_synced`. Then a `seed_data.py` that calls it to populate ~10-20 real models — this proves
> CAT-1/CAT-4 without needing the admin UI yet. See the "MVP-0 build order" note below for why.

---

## MVP-0 — Walking skeleton

**Build order within this phase** (narrower than the roadmap's scope list, which doesn't imply
sequencing): data layer + seed script → AI-engineer walking skeleton (login → browse → one real
Mesh call → dashboard) → admin console UI last. The admin UI isn't on the critical path once the
`create_model()` service function it will reuse already works via the seed script — see the
conversation this file was created from for the full reasoning.

- [ ] `AUTH-1` — AI engineer register (`POST /api/auth/register`), always role `user`
- [ ] `AUTH-2` — AI engineer login (`POST /api/auth/login`)
- [ ] `AUTH-3` — two roles exist on the user record, ≥1 admin seeded
- [ ] `AUTH-4` — admin-only routes 403 for non-admins, server-side
- [ ] `AUTH-5` — separate admin login module (`POST /api/admin/login`), no admin-register endpoint
- [ ] `AUTH-6` — admin login rejects non-admin accounts with the same generic error as wrong password
- [ ] `CAT-1` — create a model (dual-write service function; UI can come later)
- [ ] `CAT-4` — create/edit/delete dual-writes SQL + Chroma, `vector_synced` flag
- [ ] `CAT-5` — browse/search catalog (needed for the walking skeleton to be clickable at all —
      implied by the walking-skeleton goal, not explicit in the roadmap's MVP-0 bullet list)
- [ ] `TRK-1` — frontend captures model views/searches/comparisons/dwell
- [ ] `TRK-4` — bulk event ingestion (naive per-event POST acceptable here; batching is Iteration 1)
- [ ] `AGT-3` — retrieve candidate models via Chroma (grounded — no result outside the vector store)
- [ ] `AGT-5` — generate a persuasive narrative referencing only retrieved models (grounding filter)
- [ ] `AGT-7` — LLM calls route through Mesh API only
- [ ] `DLV-1` — latest recommendation shown on the dashboard

Explicitly deferred: retries/grading, caching, batching, scheduling, observability, the full admin
console (list/modal/sync-status polish).

---

## Iteration 1 — Production hardening of the core loop

- [ ] `TRK-2` — client-side event batching
- [ ] `TRK-3` — flush on timer/threshold/unload (`sendBeacon`)
- [ ] `TRK-5` — tracking never blocks/slows the page
- [ ] `TRK-6` — `model_compare` fires only on explicit "add to comparison," never inferred
- [ ] `AGT-1` — trigger evaluator (event-count / time-elapsed / cooldown), not per-event LLM calls
- [ ] `AGT-2` — behavior summary aggregation, incl. same-modality view clustering as a soft signal
- [ ] `AGT-6` — activity-hash caching skips redundant generations
- [ ] `CAT-2` — edit a model
- [ ] `CAT-3` — delete a model
- [ ] `DLV-4` — `GET /api/activity/me` (read-only; reuses data already persisted for AGT-2/AGT-6)
- [ ] `NFR-1` — event ingestion < 150ms p95
- [ ] `NFR-2` — ≤ 1 LLM generation call per trigger event (excl. bounded retries)
- [ ] `NFR-3` — dual-write failures never silently orphan a browsable-but-unindexed model
- [ ] Admin console UI: model list + sync-status column + `+ Add model` modal (create/edit shared
      form, description/story split) + delete — see `docs/03-mockups.html` for the target design

**Sprint review demo:** two browsing sessions — one that changes the recommendation, one that
doesn't (proves the cache) — plus network tab showing batched, not per-click, event calls.

---

## Iteration 2 — Real agentic depth (bonus scope begins)

- [ ] `AGT-4` — grade/refine node, bounded retry (max 2) on weak retrieval
- [ ] Convert single-shot pipeline into the 5-node LangGraph graph (analyze → retrieve → grade/
      refine → generate → store)
- [ ] `DLV-2` — dashboard refreshes after new agent runs, no stale recommendation shown
- [ ] "Why this" tags on dashboard sourced from retrieval metadata

**Sprint review demo:** deliberately weak query → show the retry/refine loop firing (logs or
LangSmith if Iteration 3 is already in place).

---

## Iteration 3 — Bonus polish (prioritize by capacity, not all required)

1. [ ] `OBS-1` — LangSmith trace per pipeline run
2. [ ] `DLV-3` — scheduled digest (APScheduler, real cron, email/Telegram)
3. [ ] Retrieval polish — metadata filtering before re-ranking; re-ranking only if time allows

---

## Cross-cutting NFRs (not phase-bound in the roadmap)

- [ ] `NFR-4` — no secrets in repo; passwords hashed; admin routes checked server-side
- [ ] `NFR-5` — agent pipeline is named, testable LangGraph nodes, not one monolith (lands with
      Iteration 2's graph conversion)
- [ ] `NFR-6` — every agent run persists `trigger_reason` + timestamps (schema supports this from
      MVP-0; the *trigger logic itself* is Iteration 1's `AGT-1`)
- [ ] `NFR-7` — one-command local setup, SQLite by default (finalized in the submission-readiness pass)

---

## Final sprint — submission readiness

- [ ] README: architecture summary, setup steps, bonus features implemented, known limitations
- [ ] `.gitignore` covers `.env`; GitHub secrets (`MESH_API_KEY`, `SUBMISSION_TOKEN`) configured
- [ ] CI workflow verified green in Actions tab
- [ ] `seed_data.py` populates demo users/models from curated data (`docs/00-Domain-Decision.md` §6)
- [ ] Optional: deployed URL + 3–5 min demo video
