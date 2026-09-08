# Platform Pivot Decision Record

## TrailMind → Embeddable Behavioral Recommendation Platform

| | |
|---|---|
| Decision | Post-hackathon product direction: convert TrailMind from a single-tenant demo app (own catalog, stub/synthetic data) into a multi-tenant platform that third-party sites embed to get real-time, behaviorally-triggered recommendations. |
| Status | Direction agreed in brainstorming; not yet reflected in BRD/FRD/HLD/LLD or code. |
| Supersedes | Nothing in [`00-Domain-Decision.md`](00-Domain-Decision.md) — that record's domain reasoning (why AI-model-catalog, why comparison-driven narratives) still explains the *origin* of the agent architecture. This document explains how the same architecture generalizes into a platform other sites embed. |

---

## 1. Why this decision needed a document

The hackathon build proved the core loop end-to-end — event tracking → trigger evaluation →
LangGraph retrieve/grade/generate → grounded narrative — against one catalog we owned and
controlled (AI models), with our own UI as the only place recommendations were shown. Turning this
into a real product changes who owns the catalog, who owns the page the tracker runs on, and how
many tenants the system serves at once. Those are architecture-shaping decisions, not incremental
feature work, so they're recorded here before any code changes.

## 2. Problem framing

The AI-model-catalog domain was chosen for hackathon judging reasons (sponsor alignment, RAG-rich
attributes, low collision risk — see `00-Domain-Decision.md` §4). It is not the constraint for the
real product. The real product is domain-agnostic infrastructure: **capture behavioral signal on
a page we don't own, decide when that signal is worth acting on, and surface a grounded
recommendation back to that same visitor before they leave** — regardless of whether the page is
selling AI models, credit cards, or anything else with a comparable catalog shape.

The concrete first vertical raised in brainstorming is **banking/financial products** (e.g. a
bank's credit-card marketing page recommending among its own card lineup) — chosen as an example
of a high-stakes, real-catalog-not-ours scenario that stress-tests the design, not necessarily the
only or first vertical to ship.

## 3. Key decisions made

### 3.1 Domain scope: generalize, don't stay niche

The system becomes domain-agnostic: any tenant with a browsable catalog can embed it. The
AI-model-catalog demo becomes one reference tenant among others rather than the product's fixed
subject.

**Consequence:** "catalog" stops being an entity we curate (`seed_data.py`, AI-assisted curation
with `source_url`) and becomes tenant-owned data we ingest — see §3.3.

### 3.2 Delivery surface: chat-bot launcher

Recommendations surface through a persistent, embeddable chat-bot launcher on the host page (not a
passive toast, not a host-integrated inline rail). It opens proactively when a trigger fires with a
grounded recommendation, and supports visitor follow-up questions.

**Why:** highest engagement surface of the options considered, and matches the "hidden tracker +
bot" framing from the original brainstorm prompt. Trade-off accepted: more UI/conversational-loop
work than a toast, and more scrutiny on grounding correctness since the bot is now answering
follow-ups live, not just stating one generated narrative.

### 3.3 Catalog ingestion: pluggable, all three modes, per tenant

Rejected picking a single ingestion method. Instead, catalog ingestion is a per-tenant
configuration choice among three adapters, normalizing into the same catalog schema + Chroma index
(tagged by tenant):

| Adapter | Mechanism | Failure mode to design for |
|---|---|---|
| Feed/API pull | Tenant provides a JSON/CSV feed or API endpoint; we sync on a schedule | Feed goes stale/unreachable — needs a health check + staleness flag, same spirit as today's `vector_synced` flag for SQL/Chroma dual-write |
| DOM scrape | Tracker snippet also extracts structured product data visible on the page | Most brittle — layout changes silently break extraction; needs a scrape-health signal, not just silent staleness |
| Manual entry | Tenant (or us, during onboarding) enters catalog via an admin console | Doesn't scale past a handful of tenants without more tooling, but is the fastest path to a working tenant with zero integration effort on their side |

**Why all three instead of one:** tenants will differ in technical capability and willingness to
integrate — a bank's marketing team may only be able to offer manual entry or a static page,
while a more technical tenant can wire up a feed. Supporting all three from day one avoids
re-architecting catalog ingestion later as tenant mix diversifies.

### 3.4 Bot grounding: catalog-only, strictly grounded

The chat-bot must only discuss and recommend products present in the tenant's own catalog, using
only facts present in that catalog data. No general financial/product advice beyond the catalog,
no invented numbers (rates, fees, specs).

**Why:** directly extends the existing house style — [[deterministic-grounding-pattern]] (the LLM
never asserts facts/numbers/comparisons; those are computed/retrieved in Python, the LLM only
handles narrative framing) — and is materially more important once a real tenant's catalog is a
regulated product (e.g. a bank's credit cards) with real liability if the bot states something
false. This also caps scope: no general-purpose financial-advice chatbot, no answering questions
the catalog data can't ground.

### 3.5 Real-time bar: push within seconds

A fired trigger must reach the visitor's open chat-bot widget within seconds via a persistent
connection (SSE or WebSocket — transport choice deferred to HLD), not on the visitor's next page
load. This is the literal "real-time" in "convert into a real-time platform" — catching the
visitor while they're still on the page, not after.

## 4. Resulting architecture shape (informal — HLD update pending)

1. **Tracker SDK** — embeddable snippet per tenant (`site_id`/API key), anonymous visitor id
   (cookie/localStorage, no PII), batches events cross-origin. Same event vocabulary as today
   (`model_view` → generalizes to `item_view`, `compare`, `dwell`, `search`, etc.), now tagged by
   `tenant_id` + visitor id.
2. **Catalog ingestion service** — the three adapters in §3.3, normalizing into a per-tenant
   catalog schema + Chroma index.
3. **Event/recommendation pipeline** — reuses the existing 6-node LangGraph shape (analyze →
   retrieve → rerank → grade/refine → generate → store), scoped per tenant, grounded strictly to
   that tenant's catalog only.
4. **Real-time push** — trigger fires → pipeline runs → result pushed to the visitor's open widget
   via SSE/WebSocket.
5. **Chat-bot widget** — persistent launcher on the host page; opens proactively on a fired
   trigger; follow-up Q&A constrained to catalog facts.
6. **Tenant/admin console** — generalizes today's curator console: onboard a site, choose/mix
   catalog ingestion adapters, manage manual entries, view per-tenant event/recommendation
   analytics.
7. **Isolation & compliance layer** — per-tenant data isolation in SQL and Chroma, no PII/PCI
   fields ever captured in events, third-party-tracking consent handling, and an audit trail
   linking each bot answer back to the catalog facts that grounded it.

## 5. Open risks — resolved in follow-up brainstorming (2026-09-08)

All five risks originally flagged here were subsequently discussed and decided. Kept as a record
of the reasoning, not just the outcome:

- **DOM-scrape adapter fragility.** Extraction prefers schema.org/JSON-LD product markup when
  present on the host page (common for SEO, more resilient to redesigns), falling back to
  tenant-configured CSS selectors only when structured markup is absent. On sync failure or
  validation failure (missing fields, item count collapse), the adapter keeps serving the
  last-known-good catalog rather than going empty, while flagging `sync_stale=true` (ING-5) for
  the tenant admin console — chosen over pausing recommendations outright, accepting the small
  risk of briefly recommending a discontinued item in exchange for the bot never going dark on a
  transient scrape failure.
- **Widget style isolation.** iframe, not Shadow DOM — full style/JS isolation from a host page we
  don't control (including a bank's marketing site) is worth the postMessage indirection; this is
  also the industry-standard pattern for embeddable third-party widgets.
- **Real-time transport.** SSE, not WebSocket — the push channel is one-directional
  (server→widget) by design (follow-up Q&A already routes through a separate `POST
  /api/widget/ask`, not the stream itself), so SSE's simpler HTTP-based model with built-in
  reconnect fits without needing WebSocket's full duplex. When a visitor's browser/network can't
  sustain the SSE connection at all, the widget silently falls back to polling
  `GET /api/recommendations/latest` — the visitor should never simply stop getting recommendations
  because of transport, only see slightly delayed ones.
- **Consent/legal posture.** The tracker SDK does not ship its own consent banner — it defers to
  whatever consent-management platform the tenant already runs (a bank almost certainly has one),
  listening for that signal rather than adding a second, possibly conflicting, banner. Tracking
  itself proceeds anonymously by default regardless of that signal (no PII is ever captured per
  TRK-7, so the anonymous behavioral stream is treated as not requiring a consent gate); the
  consent signal is reserved for gating any future identity-adjacent feature, not today's
  anonymous event stream.
- **Multi-tenant auth model.** The tenant API key is a public-ish, client-embedded credential (like
  a Stripe publishable key, not a server secret — it ships in the tracker snippet's page source),
  so its safety comes from scope (write-only to its own `tenant_id`, no admin access) and
  volumetric limits, not secrecy. Rotation (TEN-5) uses a grace period (~24h: old key valid
  alongside the new one, auto-expiring, with a separate immediate-revoke action for a suspected
  leak) rather than instant cutover, so a tenant's already-deployed/cached snippet doesn't break
  mid-rotation. A hard per-tenant ceiling on LLM-triggering agent runs (independent of the
  existing per-visitor AGT-1 cooldown) is required, not optional: because the key is publicly
  readable, an abuser can fabricate unlimited distinct `visitor_id`s to bypass the per-visitor
  cooldown entirely, so only a tenant-aggregate cap actually bounds worst-case Mesh spend and
  protects other tenants on shared infrastructure.

**Schema correction implied by the rotation decision:** `tenants.api_key_hash` (single column, as
first drafted in `06-LLD.md`) is wrong — rotation needs two keys valid at once during the grace
window, so this becomes its own `tenant_api_keys` table (`tenant_id`, `key_hash`, `status:
active|grace|revoked`, `expires_at`). See `06-LLD.md` §1 for the corrected schema.

## 5a. Tenant onboarding flow (decided 2026-09-08)

1. **Signup (assisted, not self-serve for now)** — a platform admin creates the tenant record
   (name, primary domain(s) for the CORS allowlist), which creates `tenants` (`status='onboarding'`),
   an initial `tenant_api_keys` row, and a `tenant_admin` user; credentials handed to the tenant.
   Chosen over public self-serve signup because the realistic near-term tenant mix is a small
   number of higher-touch integrations (e.g. a banking pilot that needs a compliance conversation
   regardless) — the schema doesn't block adding a public signup UI later.
2. **Widget install** — admin console shows the tracker snippet with the key baked in; a live
   "waiting for first event…" status flips to "tracker verified" on the first real
   `POST /api/events/batch` seen for that tenant.
3. **Catalog setup** — admin configures one or more of the three ingestion adapters (§3.3). A
   DOM-scrape adapter's extracted rows are created `review_status='pending_review'` (ING-6) and
   excluded from retrieval until the admin previews and confirms them — chosen because scraping is
   the most failure-prone adapter (§5) and an unreviewed bad extraction reaching a live visitor is
   worse than a slower onboarding step, especially for a regulated tenant.
4. **Go live (readiness gate, TEN-8)** — the chat-bot widget stays dormant on the host page (no
   bubble at all) while `tenants.status='onboarding'`. The tenant flips to `'active'` only once
   the tracker is verified *and* the catalog has at least one `'approved'`, `vector_synced` item.
   Chosen over going live immediately because an empty or broken bot on a tenant's real customer
   page is a worse failure mode than a slightly longer setup flow.
5. **Ongoing** — the existing admin console surfaces (ingestion status/staleness, key rotation,
   observability, analytics) apply per-tenant from here on; no new mechanism beyond what's already
   specified in the FRD/LLD.

## 6. Consequences / follow-up

This does not supersede `00-Domain-Decision.md` — the AI-model-catalog build remains a valid
reference tenant and the origin of the architecture. It does mean `01-BRD.md`, `02-FRD.md`,
`05-HLD.md`, and `06-LLD.md` are now out of date wherever they assume a single tenant, a
self-curated catalog, or a same-origin dashboard as the only delivery surface, and will need
updates before implementation resumes. `AGENTS.md`'s "Source of truth" list should point here
alongside `00-Domain-Decision.md` until those documents are updated.

No code changes have been made as part of this decision — brainstorming and direction-setting
only, per explicit instruction.
