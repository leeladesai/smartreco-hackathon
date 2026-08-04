# UX Design — Personas, Flows & Wireframes
## SmartReco

High-fidelity, click-through mockups are provided separately as `03-mockups.html` (open in a
browser or view as an artifact). This document covers personas and flows; the mockups cover visual
design and layout.

---

## 1. Personas

**AI engineer (primary user)**
Goal: find the AI model best suited to what they're currently trying to build, with minimal
searching — often by comparing a few candidates against each other on price, latency, or capability.
Behavior: browses by modality/provider, searches loosely, revisits and compares models before
committing.

**Curator (catalog manager, `admin` role)**
Goal: keep the model catalog accurate and see that new models are actually indexed for
retrieval, not just listed.

---

## 2. Primary user flow — AI engineer

1. Lands on catalog (unauthenticated browse allowed; login required to get personalized recs)
2. Registers/logs in at the AI engineer login screen (`POST /api/auth/register` /
   `POST /api/auth/login`) — no role picker; this screen can only ever produce a `user` account
3. Browses by modality/provider, searches, opens model detail pages, spends time reading — every
   meaningful action is silently tracked and batched
4. Explicitly adds 2–3 models to the **compare tray** (a persistent bottom bar, not an inferred
   signal) and opens the **Compare** screen for a side-by-side spec table — this deliberate action
   is what fires `model_compare`, not simply viewing multiple models in one session
5. After the trigger threshold is crossed (e.g. 5 tracked actions or 10 minutes with new activity),
   a recommendation is generated in the background
6. AI engineer visits their **Dashboard** and sees a persuasive narrative + 3–5 recommended models, each
   connected by an **evidence trail** back to the specific views/searches/comparisons that produced
   it, plus a stepper showing the agent pipeline stage by stage and a delta chip flagging what's new
   since their last visit
7. Curious AI engineers can open **Your Activity** to see the raw tracked event log and exactly how it
   collapsed into the behavior summary, activity hash, and trigger reason behind the current
   recommendation — nothing about the tracking is hidden from them
8. AI engineer continues browsing → new activity → next visit to Dashboard shows an updated
   recommendation (or the same one, unchanged, if behavior hasn't meaningfully shifted)
9. *(Bonus)* AI engineer receives an afternoon email/Telegram digest without visiting the site

## 3. Primary flow — Curator

1. Logs in at a **separate admin login screen** (`POST /api/admin/login`) — distinct route and
   form from the AI engineer login, no register option; landing here always resolves to the admin
   console → sees the **Admin** nav item
2. **Model list** view: table of models with a sync-status indicator per row
3. A **+ Add model** button (top-right, not buried in the list) opens the create form as a
   focused modal overlay, capturing title, description, story (curator's pitch — who should pick
   this model and what trade-off it makes), provider, modality, price, latency, context window,
   use-case tags, and source URL. Editing an existing model reuses the same modal, pre-filled —
   one form, two entry points, not two layouts to keep in sync
4. On save, the model appears in the SQL-backed list immediately; sync-status shows "indexing…"
   then "synced" once the vector write completes, while the modal itself fades/closes rather than
   snapping shut
5. Can delete a model; it should disappear from future recommendations

## 4. Screens required (MVP)

| Screen | Users | Notes |
|---|---|---|
| Login / Register | AI engineer | `/login` — sign-in + register toggle, no role picker |
| Admin login | Curator | `/admin/login` — separate screen, single fixed form, no register option |
| Catalog / search | AI engineer | Card grid, search/filter chips, persistent compare tray at the bottom |
| Model detail | AI engineer | Triggers `model_view` + dwell-time tracking; explicit "add to comparison" action (not inferred from dwell) feeds the compare tray |
| Compare | AI engineer | Side-by-side spec table for 2–3 tray models; the dimension the AI engineer has dwelt on most is auto-highlighted; fires `model_compare` |
| Dashboard (recommendations) | AI engineer | Narrative block + pipeline stepper + model cards with evidence-trail annotations back to source events + "new since last visit" delta |
| Your Activity | AI engineer | Chronological log of tracked events, plus a panel showing how they collapse into `behavior_summary` → `activity_hash` → `trigger_reason` → the delivered recommendation |
| Admin: model list | Curator | Table with sync-status column; `+ Add model` entry point top-right |
| Admin: model form | Curator | Modal overlay (not inline/bottom-of-list), shared by create and edit; captures description *and* story as separate fields |

## 5. Key UX principles for this build

- **Show your work.** Each recommended model on the dashboard should carry a short tag like
  "Because you compared: GPT-4o mini vs Claude Haiku" — this is cheap to build (comes straight from
  the retrieval/event metadata) and is exactly what judges want to see: grounded, explainable
  recommendations.
- **Sync status is a UX feature, not just a debug field.** Surfacing `vector_synced` in the admin
  table turns an internal correctness requirement (CAT-4) into visible proof the dual-write works.
- **No dead-end loading states.** Recommendation generation is async — dashboard should show a
  "still learning your interests" empty state for new users, not a blank screen.
- **Admin access reads as restricted, not just role-gated.** The admin login screen is visually and
  structurally separate (own route, own form, no register option) — this is both a real security
  boundary (AUTH-5/AUTH-6) and a UX signal that this isn't a casual area of the app.
- **Comparison is explicit, not inferred.** The compare tray requires a deliberate "add to
  comparison" action rather than guessing intent from session dwell time — a cleaner, more honest
  `model_compare` signal, and a UI element (the tray) that makes browsing itself a little stickier.
- **Tracking is legible, not just present.** The Your Activity screen turns the internals TRK/AGT
  requirements already produce (raw events, `activity_hash`, `trigger_reason`) into a real product
  surface instead of a hidden debug log — it's simultaneously a trust feature for AI engineers and the
  most direct proof, for a judge, that recommendations are grounded rather than stubbed.
- **Navigation mirrors real app state, not a design-review switcher.** What a screen can navigate
  to depends on who's signed in (nobody / AI engineer / curator) — there's no single nav exposing
  every screen as an equal, always-clickable peer, and nothing in the AI-engineer flow links to
  admin login. This matters beyond visual polish: a spec that shows every screen as reachable from
  everywhere will get implemented that way.
- **Catalog edits happen in a focused overlay, not inline.** Add/edit model opens as a modal over
  the list rather than a form pushing the table around — the list stays the stable "home" view, and
  create/edit share one form definition instead of drifting into two.
