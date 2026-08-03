# UX Design — Personas, Flows & Wireframes
## SmartReco

High-fidelity, click-through mockups are provided separately as `03-mockups.html` (open in a
browser or view as an artifact). This document covers personas and flows; the mockups cover visual
design and layout.

---

## 1. Personas

**Builder (primary user)**
Goal: find the AI model best suited to what they're currently trying to build, with minimal
searching — often by comparing a few candidates against each other on price, latency, or capability.
Behavior: browses by modality/provider, searches loosely, revisits and compares models before
committing.

**Curator (catalog manager, `admin` role)**
Goal: keep the model catalog accurate and see that new models are actually indexed for
retrieval, not just listed.

---

## 2. Primary user flow — Builder

1. Lands on catalog (unauthenticated browse allowed; login required to get personalized recs)
2. Registers/logs in at the builder login screen (`POST /api/auth/register` /
   `POST /api/auth/login`) — no role picker; this screen can only ever produce a `user` account
3. Browses by modality/provider, searches, opens model detail pages, spends time reading — every
   meaningful action is silently tracked and batched
4. Explicitly adds 2–3 models to the **compare tray** (a persistent bottom bar, not an inferred
   signal) and opens the **Compare** screen for a side-by-side spec table — this deliberate action
   is what fires `model_compare`, not simply viewing multiple models in one session
5. After the trigger threshold is crossed (e.g. 5 tracked actions or 10 minutes with new activity),
   a recommendation is generated in the background
6. Builder visits their **Dashboard** and sees a persuasive narrative + 3–5 recommended models, each
   connected by an **evidence trail** back to the specific views/searches/comparisons that produced
   it, plus a stepper showing the agent pipeline stage by stage and a delta chip flagging what's new
   since their last visit
7. Curious builders can open **Your Activity** to see the raw tracked event log and exactly how it
   collapsed into the behavior summary, activity hash, and trigger reason behind the current
   recommendation — nothing about the tracking is hidden from them
8. Builder continues browsing → new activity → next visit to Dashboard shows an updated
   recommendation (or the same one, unchanged, if behavior hasn't meaningfully shifted)
9. *(Bonus)* Builder receives an afternoon email/Telegram digest without visiting the site

## 3. Primary flow — Curator

1. Logs in at a **separate admin login screen** (`POST /api/admin/login`) — distinct route and
   form from the builder login, no register option; landing here always resolves to the admin
   console → sees the **Admin** nav item
2. **Model list** view: table of models with a sync-status indicator per row
3. **Add/Edit model** form → on save, model appears in the SQL-backed list immediately;
   sync-status shows "indexing…" then "synced" once the vector write completes
4. Can delete a model; it should disappear from future recommendations

## 4. Screens required (MVP)

| Screen | Users | Notes |
|---|---|---|
| Login / Register | Builder | `/login` — sign-in + register toggle, no role picker |
| Admin login | Curator | `/admin/login` — separate screen, single fixed form, no register option |
| Catalog / search | Builder | Card grid, search/filter chips, persistent compare tray at the bottom |
| Model detail | Builder | Triggers `model_view` + dwell-time tracking; explicit "add to comparison" action (not inferred from dwell) feeds the compare tray |
| Compare | Builder | Side-by-side spec table for 2–3 tray models; the dimension the builder has dwelt on most is auto-highlighted; fires `model_compare` |
| Dashboard (recommendations) | Builder | Narrative block + pipeline stepper + model cards with evidence-trail annotations back to source events + "new since last visit" delta |
| Your Activity | Builder | Chronological log of tracked events, plus a panel showing how they collapse into `behavior_summary` → `activity_hash` → `trigger_reason` → the delivered recommendation |
| Admin: model list | Curator | Table with sync-status column |
| Admin: model form | Curator | Create/edit |

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
  surface instead of a hidden debug log — it's simultaneously a trust feature for builders and the
  most direct proof, for a judge, that recommendations are grounded rather than stubbed.
