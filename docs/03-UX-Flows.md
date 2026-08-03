# UX Design — Personas, Flows & Wireframes
## SmartReco

Low-fidelity wireframes are provided separately as `03-mockups.html` (open in a browser or view as
an artifact). This document covers personas and flows; the mockups cover layout.

---

## 1. Personas

**Learner (primary user)**
Goal: find courses relevant to what they're currently curious about, with minimal searching.
Behavior: browses, searches loosely, revisits topics before committing.

**Admin (catalog manager)**
Goal: keep the course catalog accurate and see that new products are actually indexed for
retrieval, not just listed.

---

## 2. Primary user flow — Learner

1. Lands on catalog (unauthenticated browse allowed; login required to get personalized recs)
2. Registers/logs in
3. Browses categories, searches, opens product detail pages, spends time reading — every
   meaningful action is silently tracked and batched
4. After the trigger threshold is crossed (e.g. 5 tracked actions or 10 minutes with new activity),
   a recommendation is generated in the background
5. Learner visits their **Dashboard** and sees a persuasive narrative + 3–5 recommended courses,
   each traceable to something they actually did ("since you kept coming back to agentic AI...")
6. Learner continues browsing → new activity → next visit to Dashboard shows an updated
   recommendation (or the same one, unchanged, if behavior hasn't meaningfully shifted)
7. *(Bonus)* Learner receives an afternoon email/Telegram digest without visiting the site

## 3. Primary flow — Admin

1. Logs in with admin role → sees an **Admin** nav item
2. **Product list** view: table of products with a sync-status indicator per row
3. **Add/Edit product** form → on save, product appears in the SQL-backed list immediately;
   sync-status shows "indexing…" then "synced" once the vector write completes
4. Can delete a product; it should disappear from future recommendations

## 4. Screens required (MVP)

| Screen | Users | Notes |
|---|---|---|
| Login / Register | All | Simple, single form each |
| Catalog / search | Learner | Card grid, search bar, category filter |
| Product detail | Learner | Triggers `product_view` + dwell-time tracking |
| Dashboard (recommendations) | Learner | Narrative block + product cards, "why this" tags |
| Admin: product list | Admin | Table with sync-status column |
| Admin: product form | Admin | Create/edit |

## 5. Key UX principles for this build

- **Show your work.** Each recommended product on the dashboard should carry a short tag like
  "Because you viewed: Agentic AI Fundamentals" — this is cheap to build (comes straight from the
  retrieval metadata) and is exactly what judges want to see: grounded, explainable recommendations.
- **Sync status is a UX feature, not just a debug field.** Surfacing `vector_synced` in the admin
  table turns an internal correctness requirement (CAT-4) into visible proof the dual-write works.
- **No dead-end loading states.** Recommendation generation is async — dashboard should show a
  "still learning your interests" empty state for new users, not a blank screen.
