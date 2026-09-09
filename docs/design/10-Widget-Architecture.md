# Widget Architecture & Breaking Auth Cutover (M5)

## TrailMind: from tenant-scoped platform to multi-widget platform

| | |
|---|---|
| Decision | Split the platform's unit of embedding from *tenant* to *widget*: every tenant can run several independent embeddable widgets (e.g. "Credit Cards" vs "Personal Loans"), each with its own API key, allowed-origin allowlist, catalog scope, and vector-store collection. |
| Status | Implemented and live-verified end to end (backend, frontend admin console, tracker/widget SDK). Supersedes the tenant-level auth/scoping design in §3.4/§5/§5a of [`09-Platform-Pivot-Decision.md`](09-Platform-Pivot-Decision.md) and the single `tenant_api_keys` schema in `06-LLD.md` §1. |
| Why now | While building tenant onboarding (M2) it became clear a single tenant recommending across unrelated product lines (e.g. a bank's cards *and* loans) from one shared catalog/vector collection would cross-contaminate recommendations — a visitor evaluating credit cards has no business being shown personal loans just because they share a tenant. The fix is isolating catalog + retrieval + auth at the widget level, not the tenant level. |

---

## 1. What changed

### 1.1 Widget as a first-class entity

`Widget` (`app/models.py`) now owns everything that used to live on `Tenant`:

- its own `status` (`onboarding` → `active`, independent of the tenant's platform-governance
  `status`) — **both** must be healthy for the widget to actually render on a host page;
- `allowed_origins` — the CORS/Origin allowlist enforced on every tracker/widget request;
- `first_event_at` — the "tracker verified" half of the TEN-8 readiness gate;
- `feed_url`/`feed_auth_token` — feed ingestion config, now per widget so two widgets under one
  tenant can sync from two different feeds;
- a Chroma collection scoped as `{collection_name}_widget_{widget_id}`, so retrieval for one
  widget can never surface another widget's catalog items, even within the same tenant.

`Tenant` keeps only platform-level governance (`status`, `max_agent_runs_per_hour`) and is the
parent a business admin logs into; every operational concern moved down to `Widget`.

### 1.2 Breaking auth cutover: `tenant_key` → `widget_key`

`TenantApiKey`/`tenant_key` is fully retired for tracker/widget SDK auth. `WidgetApiKey`/
`widget_key` (same hash + grace-period rotation design) is the only credential the tracker
snippet, the widget snippet, and their APIs accept:

- `POST /api/track/events`
- `GET /api/recommendations/latest`
- `GET /api/widget/stream`, `POST /api/widget/ask`, `GET /api/widget/activity`

This was a deliberate breaking change (no dual-auth transition period) — chosen because the
platform has no production tenants embedded yet, so there was nothing to keep working during a
migration window, and carrying two parallel auth paths would have doubled the surface area for a
capability (tenant-wide key) the product no longer wants tenants to have.

`TenantApiKey` the table (and any already-hashed rows) is kept only so the migration that moves
data off it has something to read from; nothing issues, checks, or rotates one anymore.

### 1.3 CatalogItem stays widget-scoped, not just tenant-scoped

`CatalogItem.widget_id` (added alongside the pre-existing `tenant_id`) is the scope retrieval and
tracking actually isolate on. Existing rows predating widgets were backfilled to their tenant's
auto-created "Default" widget by an idempotent migration in `app/db.py`, so no catalog data was
lost in the cutover.

### 1.4 TEN-8 readiness gate moves to the widget

A widget auto-flips `onboarding` → `active` once **both**:
- `tracker_verified` — a real event has reached the backend under this widget's key
  (`Widget.first_event_at` is set), and
- `catalog_ready` — at least one `approved`, `vector_synced` catalog item exists in this widget's
  scope.

The chat-bot widget stays dark on the host page until its own `active`/`ready` state is reached —
same reasoning as the original tenant-level TEN-8 (`09-Platform-Pivot-Decision.md` §5a step 4), now
correctly scoped per product line instead of per company.

### 1.5 Soft origin allowlist enforcement

If a widget has `allowed_origins` set, an incoming tracker/widget request must carry a matching
`Origin` or `Referer` header or is rejected with `{"detail":"Origin not allowed"}`. A widget with
an empty `allowed_origins` list (the default until an admin sets one) accepts requests from any
origin — origin checking is opt-in per widget, not a default lockdown, so a newly created widget's
embed snippet works immediately without an extra allowlist-configuration step blocking it.

---

## 2. Admin console: Next.js frontend replaces the Jinja2 curator console

The curator console described in the original README (server-rendered Jinja2 + vanilla JS,
same-origin with the API) is retired. The admin console is now a separate Next.js 16 App Router
app (`frontend/`) talking to the FastAPI backend purely over the JSON API with bearer-token auth
(`Authorization: Bearer <jwt>`, never a cookie) — see `frontend/src/lib/api.ts`.

Two admin roles, both served by this one frontend:
- **Platform admin** (`platform@trailmind.dev`) — Tenants page: approve/reject self-serve
  signups, create trusted tenants directly, suspend/reactivate a tenant, inspect its widgets.
- **Business admin** (created per tenant on approval) — Overview (usage totals + live activity +
  onboarding nudge), Widgets (create/list/rotate-key/revoke-key/suspend/reactivate/feed config,
  with the embed-snippet UX below), Catalog (widget-scoped CRUD + bulk upload + ingestion status).

### 2.1 Embed snippet UX (Phase 4 polish)

Widget creation and the widget detail drawer render ready-to-paste `<script>` tags with the real
key substituted in, instead of leaving the admin to hand-assemble them from a bare key:

```html
<script src="{API_BASE}/static/js/tracker.js" data-widget-key="wk_live_..."></script>
<script src="{API_BASE}/static/js/widget.js" data-widget-key="wk_live_..."></script>
```

`API_BASE` is exported from `frontend/src/lib/api.ts` so the snippet always points at whichever
backend the admin console itself is configured against (`NEXT_PUBLIC_API_BASE_URL`). Each snippet
has its own copy button (`CopyBlock` component, `frontend/src/app/admin/widgets/page.tsx`).

### 2.2 Onboarding nudge (Phase 4 polish)

The Overview page shows a one-line nudge — "Create a widget → add catalog items" with direct
links — when a tenant has zero catalog items and zero events, so a freshly approved tenant isn't
looking at an unexplained wall of empty stat tiles.

---

## 3. Live verification (2026-09-09)

The full onboarding-to-recommendation loop was verified end to end in a real browser session
(platform admin login → tenant creation with no `api_key` in the response, confirming the
cutover → self-serve signup → approval → business admin login → onboarding nudge → widget
creation with the embed-snippet UX → widget-scoped catalog item creation → tracker event ingestion
correctly enforcing the widget's origin allowlist → widget auto-flipping `onboarding`/`tracker–` →
`active`/`ready`). No app-level defects were found.

---

## 4. Consequences / follow-up

- `06-LLD.md`'s schema section (single `tenant_api_keys` table, tenant-scoped `models`/`events`)
  is now superseded by §1 above wherever it conflicts — not yet rewritten inline; this document is
  the current source of truth for the widget-scoped schema until `06-LLD.md` gets a full pass.
- `09-Platform-Pivot-Decision.md` §5a ("Tenant onboarding flow") still describes the *shape* of
  onboarding correctly (assisted signup → install → catalog setup → readiness gate → ongoing) but
  its mechanics (tenant-level key, tenant-level TEN-8) are superseded by §1.2/§1.4 above.
- `README.md` and `AGENTS.md` have been updated alongside this document to describe the current
  multi-widget, Next.js-admin-console platform rather than the original single-tenant AI-model-
  catalog demo.
