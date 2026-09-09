# Session Handoff — 2026-09-09

Written for whichever agent (human or AI) picks this up next. Read
`docs/design/10-Widget-Architecture.md` first for the architecture itself; this document is just
"where things stand and what to do next."

## State as of this handoff

- **Branch:** `feature/mvp-0-scaffolding`, 2 commits ahead of `origin/feature/mvp-0-scaffolding`
  (not yet pushed — push wasn't requested).
- **M5 (Widget entity + breaking tenant-key→widget-key auth cutover) is done**, backend + frontend
  + SDK, in one commit: `8606600` ("Generalize catalog to CatalogItem and add multi-widget
  architecture"). 181/181 backend tests passing, flake8 clean against the tracked baseline,
  frontend `tsc`/`eslint`/`next build` all clean.
- **Phase 4 polish (embed snippet UX, onboarding empty-state nudge) is done**, commit `0d78767`.
- **Full live browser verification passed** (2026-09-09): platform admin login → tenant creation
  (confirmed no `api_key` in the response, i.e. the breaking cutover actually took effect) →
  self-serve signup → confirmation screen → platform admin approval → business admin login →
  Overview onboarding nudge rendering → widget creation with the embed-snippet UX rendering real
  `tracker.js`/`widget.js` tags with the key substituted → widget-scoped catalog item creation
  (vector-synced) → a tracker event correctly rejected for origin mismatch, then accepted with the
  right `Origin` header → the widget auto-flipping `onboarding`/`tracker–`/`catalog–` →
  `active`/`ready`. No app-level defects found.
- **This documentation pass** (this commit): rewrote `README.md` for the current multi-tenant,
  multi-widget platform (it previously still described the single-tenant AI-model-catalog demo);
  added `docs/design/10-Widget-Architecture.md` recording the M5 decision and its consequences;
  updated `AGENTS.md`'s "Start here"/"Project overview"/"Source of truth"/"Intended architecture"/
  "Commands" sections to point at the current architecture and add frontend check commands; added
  this handoff document.

## Known non-blocking loose ends

- **Test artifacts in the live dev database** from the browser verification pass: tenants "Demo
  Bank" (from an earlier agent's testing), "Verify Corp \<timestamp\>", and "Verify Widgets Co
  \<timestamp\>" (with a "Personal Loans" widget and one catalog item). Harmless, but worth a
  cleanup pass (`DELETE FROM tenants WHERE name LIKE 'Verify%'` cascades, or just re-seed) before
  a demo/judging session if a clean tenant list matters.
- **`docs/design/06-LLD.md` and `05-HLD.md` are not rewritten inline** — they still describe the
  hackathon-era single-tenant schema/API. `docs/design/10-Widget-Architecture.md` §4 documents
  this explicitly as the current source of truth for the widget-scoped schema until someone does a
  full rewrite pass on 05/06. Not urgent — every current agent-facing doc (`AGENTS.md`, `README.md`)
  now points to document 10 first, so this doesn't cause anyone to build against the stale schema
  by accident.
- **`docs/design/09-Platform-Pivot-Decision.md` §5a** (tenant onboarding flow) describes the
  correct *shape* of onboarding but its mechanics reference the now-retired tenant-level key and
  tenant-level TEN-8 gate — document 10 §4 notes this supersession but §5a itself hasn't been
  edited in place.

## Natural next steps (not yet scoped/committed to)

Nothing is currently blocked or in progress. Candidates for a next phase, none yet discussed with
the user beyond the original "Phase 4 polish" selection (embed snippet UX, onboarding empty
states, live browser verification — all three now done):

- Push the 2 local commits to `origin/feature/mvp-0-scaffolding` (not done — never asked).
- Clean up the test tenants above.
- A pass through `docs/design/05-HLD.md`/`06-LLD.md` to bring the formal schema/API contract docs
  in line with `app/models.py`/`app/main.py`, if the team wants those documents authoritative
  again rather than deferring to document 10 + the code.
- Decide whether self-serve tenant signup (already implemented — see `/api/auth/signup`) should
  become the primary onboarding path or stay secondary to platform-admin-created tenants; the
  design docs currently describe assisted-only onboarding as the deliberate near-term choice
  (`09-Platform-Pivot-Decision.md` §5a step 1) even though the self-serve code path exists and was
  used in this session's verification.
