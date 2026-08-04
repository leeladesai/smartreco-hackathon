# Build Status

## SmartReco

This file tracks what's actually built, not what's planned — `docs/04-MVP-Roadmap.md` remains the
spec of record for scope and phase ordering, `docs/02-FRD.md` for acceptance criteria per ID, and
`docs/06-LLD.md` for schema/API/node contracts. This file only answers two questions: **what's
done**, and **what's next**.

**Convention:** whoever closes an item checks the box and updates "Next up" as part of the same
commit as the code — don't let this drift into a second, stale plan.

---

## Next up

> Frontend routing migration (below) — the app currently serves one static file
> (`docs/03-mockups.html`) for every screen via `FileResponse`, so every page shows the same URL
> and there's no real client-server routing. Do this before resuming the generation-seam work.
> After this lands, resume: add the generation seam through the configured provider, then persist
> the grounded result for the dashboard — the dashboard currently stops at retrieval-ready
> candidates.

---

## Frontend routing migration — Jinja2 templates + vanilla JS

Replaces the current `FileResponse(docs/03-mockups.html)` shortcut in `app/main.py`, which is why
every screen currently shows the same URL (`/`) — it's one static file with JS toggling which
`<div class="page">` is visible, not real routing. This was a deliberate decision (see the
conversation this task was added from): Jinja2 + vanilla JS over React/TypeScript or Streamlit,
because it already matches `docs/05-HLD.md`/`AGENTS.md`'s documented architecture, needs no new
build tooling (keeps the "single container, no separate frontend deploy" story), and reuses ~90%
of the existing HTML/CSS design system instead of a rewrite. `docs/03-mockups.html` stops being
served as live app code once this lands — it goes back to being purely the design reference.

- [ ] Add `jinja2` to `pyproject.toml` dependencies
- [ ] `app/static/css/app.css` — extract the `<style>` block from `docs/03-mockups.html` unchanged
- [ ] `app/static/js/app.js` — extract the API/interaction JS (`trackEvent`, compare tray, modal,
      forms); delete the fake `go(page)` SPA router entirely, it's no longer needed
- [ ] `app/templates/base.html` — shared nav chrome (already auth-state-driven in the mockup),
      `{% block content %}`
- [ ] Per-screen templates extending `base.html`: `login.html`, `admin_login.html`, `catalog.html`,
      `model_detail.html`, `compare.html`, `dashboard.html`, `activity.html`, `admin.html`
- [ ] Wire `Jinja2Templates` + `StaticFiles` in `app/main.py`; add the `GET` route per template
      below, each auth-gated **server-side** (redirect to `/login` or `/admin/login` on a
      missing/wrong-role session cookie — a real correctness improvement over today's client-only
      nav-state toggle, which only controls visibility, not access)
- [ ] Compare tray selection persists via `localStorage` (an in-memory JS variable doesn't survive
      a real page navigation); `/compare?ids=12,7` reads the actual query string, making a specific
      comparison a real, shareable link
- [ ] Retire `FileResponse(MOCKUP_PATH)` and the catch-all `/` route
- [ ] Update `README.md` quick-start once routes/URLs are final

**Route map:**

| Route | Template | Auth |
|---|---|---|
| `GET /login` | `login.html` | none |
| `GET /admin/login` | `admin_login.html` | none |
| `GET /` or `/catalog` | `catalog.html` | AI engineer (public browse allowed per UX doc; personalized recs require login) |
| `GET /models/{id}` | `model_detail.html` | AI engineer |
| `GET /compare` | `compare.html` | AI engineer |
| `GET /dashboard` | `dashboard.html` | AI engineer |
| `GET /activity` | `activity.html` | AI engineer |
| `GET /admin` | `admin.html` | curator |

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
