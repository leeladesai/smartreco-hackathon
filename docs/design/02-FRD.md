# Functional Requirements Document (FRD)
## TrailMind — Embeddable Behavioral Recommendation Platform

Traces to BRD v2.0. Each requirement has an ID used in the MVP roadmap, LLD, and test strategy for
end-to-end traceability. Updated per
[`09-Platform-Pivot-Decision.md`](09-Platform-Pivot-Decision.md): requirements below are scoped
per-tenant unless stated otherwise; the original single-tenant AI-model-catalog requirements are
kept where the pivot doesn't change them (auth pattern, dual-write, LangGraph node contracts) and
marked where it does.

---

## 1. Modules

| Module code | Module |
|---|---|
| TEN  | Tenant management & isolation *(new)* |
| AUTH | Authentication & roles (tenant admin + platform, generalizes former user/curator auth) |
| ING  | Catalog ingestion adapters *(new — replaces admin-only CAT for tenant catalogs)* |
| CAT  | Catalog / model management (reference tenant + manual-entry adapter UI) |
| TRK  | Behavioral event tracking (tracker SDK, cross-origin) |
| AGT  | Agentic recommendation engine |
| DLV  | Delivery — chat-bot widget + real-time push (supersedes in-app-dashboard-only delivery) |
| OBS  | Observability |

---

## 2. Functional requirements

### TEN *(new)*
| ID | Requirement | Acceptance criteria |
|---|---|---|
| TEN-1 | A tenant can be onboarded (site registered) and issued an API key | Assisted onboarding for now — a platform admin creates the tenant record (self-serve public signup deferred, not a schema blocker later); tenant created with a unique `tenant_id` and `status='onboarding'`; API key generated, shown once, hashed at rest |
| TEN-8 *(new)* | The chat-bot widget stays dormant on the host page until the tenant is ready | Widget renders nothing to real visitors while `tenants.status='onboarding'`; tenant flips to `'active'` only once the tracker is verified (a real event received) and the catalog is non-empty with synced items — prevents an empty/broken bot reaching real visitors mid-setup |
| TEN-2 | Every tenant-scoped write (events, catalog rows, recommendations) is tagged with `tenant_id` | No insert path exists that omits `tenant_id`; enforced at the ORM/service layer, not just by convention |
| TEN-3 | No read path returns another tenant's data | Cross-tenant isolation covered by dedicated tests (e.g. tenant A's API key cannot list tenant B's catalog/events/recommendations) |
| TEN-4 | Tenant API key authenticates tracker SDK and ingestion requests | Requests without a valid, unexpired API key rejected before touching tenant data |
| TEN-5 | Tenant admin can rotate their API key, or revoke one immediately | Rotation issues a new `active` key and flips the previous key to `grace` (valid ~24h, then auto-expires) so an already-deployed snippet doesn't break mid-rotation; a separate immediate-revoke action (for a suspected leak) bypasses the grace period and fails closed right away |
| TEN-6 *(new)* | A hard per-tenant ceiling bounds LLM-triggering agent runs, independent of the per-visitor AGT-1 cooldown | Because the tenant API key is a public, client-embedded credential (readable in page source), per-visitor cooldown alone doesn't stop an abuser fabricating unlimited `visitor_id`s to bypass it; a tenant-aggregate cap (`max_agent_runs_per_hour`) rejects/queues further runs once hit, protecting Mesh spend and other tenants on shared infra |
| TEN-7 *(new)* | Tracker SDK defers to the tenant's own consent-management platform rather than shipping its own banner | SDK listens for the tenant's existing consent signal; anonymous, non-PII event tracking proceeds by default regardless of that signal (no PII is ever captured per TRK-7), with the signal reserved for gating any future identity-adjacent feature |

### AUTH
AI engineer and admin auth are deliberately two separate modules — a separate route, a separate form,
and (for admin) no self-registration — not one login screen with a role picker. This pattern now
generalizes to **tenant admin** (manages that tenant's catalog/ingestion/widget config) replacing
the former single-admin "Curator" role; a **platform admin** role (us, not a tenant) is layered on
top for cross-tenant operations.

**Implementation status:** the AI-engineer-facing `user` role/module below (AUTH-1, AUTH-2) was
actively removed from the running code — not merely frozen — as part of the tracker-SDK-phase work
(`docs/design/09-Platform-Pivot-Decision.md`), along with the cookie-session catalog/dashboard/
activity UI it gated. `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, and
`PUT /api/auth/me/telegram-chat-id` no longer exist. The reference tenant's own end-user surface
returns later in that same phase, built on anonymous tracker-SDK visitor identity rather than this
cookie-session `user` role — AUTH-1/AUTH-2 below describe that *target* shape, not current code.
`AUTH-3` through `AUTH-6` (admin auth) are current and unaffected; the running `User.role` is
`'admin'` only for now (no `tenant_admin`/`platform_admin` split until tenant onboarding, TEN-1).

| ID | Requirement | Acceptance criteria |
|---|---|---|
| AUTH-1 | A user can register with email/password at `POST /api/auth/register`, scoped to a tenant | Password hashed (bcrypt/argon2); duplicate email rejected within that tenant; role always created as `user` — this endpoint can never create an admin |
| AUTH-2 | A user can log in and receive a session at `POST /api/auth/login` | Session cookie or JWT issued, carrying `tenant_id`; invalid credentials rejected with generic error |
| AUTH-3 | Three roles exist: `user`, `tenant_admin`, `platform_admin` | Role stored on user record along with `tenant_id` (`platform_admin` has no single `tenant_id`); no runtime endpoint grants `tenant_admin` or `platform_admin` |
| AUTH-4 | Tenant-admin-only routes are protected and scoped to that tenant | Non-admin hitting `/api/admin/*` receives 403; a tenant admin hitting another tenant's admin routes also receives 403, enforced server-side |
| AUTH-5 | Tenant admin logs in through a separate module at `POST /api/admin/login` | Distinct route/handler from end-user login; **no corresponding admin-registration endpoint exists** — tenant admin accounts are only ever created at tenant onboarding or by a platform admin, never self-service |
| AUTH-6 | `POST /api/admin/login` only authenticates accounts with an admin role | A correct password for a non-admin account is rejected with the same generic error as a wrong password — the endpoint never reveals whether the account exists or merely lacks the admin role |

### ING *(new)*
| ID | Requirement | Acceptance criteria |
|---|---|---|
| ING-1 | A tenant can configure a feed/API-pull catalog adapter | Tenant provides a feed URL/credentials; scheduled sync normalizes rows into the tenant's catalog + vector index |
| ING-2 | A tenant can enable a DOM-scrape catalog adapter | Extraction prefers schema.org/JSON-LD product markup when present on the host page, falling back to tenant-configured CSS selectors only when structured markup is absent; each scraped row records its source page/selector/markup-type for traceability |
| ING-3 | A tenant can manage a manual-entry catalog | Same CRUD shape as the former admin catalog management (see CAT), scoped to that tenant |
| ING-4 | A tenant can mix adapters | E.g. feed for the bulk catalog, manual entry for overrides — later writes for the same item id win, tracked per adapter source |
| ING-5 | Feed/scrape adapter staleness is visible, and the catalog keeps serving through it | A tenant catalog row/adapter exposes a last-synced timestamp and a staleness flag when a sync fails, the source is unreachable, or extracted data fails validation (missing fields, item-count collapse), analogous to `vector_synced`; recommendations continue serving the last-known-good catalog rather than going empty or pausing (pivot record §5) |
| ING-6 *(new)* | Scraped items require tenant confirmation before grounding bot answers | Rows from the DOM-scrape adapter are created with `review_status='pending_review'` and excluded from retrieval/vector indexing until a tenant admin previews and confirms them (`'approved'`) during onboarding or after a re-scrape; feed/manual rows default `'approved'` |

### CAT
Now the manual-entry adapter's UI (ING-3) plus the reference AI-model-catalog tenant, rather than
the platform's only catalog path.

| ID | Requirement | Acceptance criteria |
|---|---|---|
| CAT-1 | Tenant admin can create a catalog item via a modal form, not an inline page element | Row written to SQL, tagged with `tenant_id`; response includes generated ID; the create/edit form is a focused overlay, not a form embedded in the catalog list |
| CAT-2 | Tenant admin can edit a catalog item | SQL row updated; `updated_at` bumped |
| CAT-3 | Tenant admin can delete a catalog item | SQL row removed (or soft-deleted); no longer retrievable by agent |
| CAT-4 | Every create/edit/delete dual-writes to that tenant's vector index | Vector store reflects the item within the same request; failure sets `vector_synced=false` and is retried |
| CAT-5 | End visitors can browse/search a tenant's catalog (where the tenant exposes browsing, not just widget recs) | Catalog page lists items scoped to that tenant; search/filter returns matching subset |

### TRK
Now the embeddable tracker SDK — runs on a host page we don't own, cross-origin, identifying an
anonymous visitor rather than a logged-in platform user.

| ID | Requirement | Acceptance criteria |
|---|---|---|
| TRK-1 | Tracker snippet captures page/item views, searches, comparisons, dwell time on the host page | Each event has type, anonymous visitor id, `tenant_id`, optional catalog-item ref, timestamp |
| TRK-2 | Events are batched client-side | No network call per single event under normal browsing |
| TRK-3 | Events flush on a timer, size threshold, or page unload | Uses `sendBeacon` on unload; periodic flush otherwise |
| TRK-4 | Backend ingests events in bulk without blocking the request, across origins | Single POST accepts an array with valid CORS for the tenant's registered domain(s); bulk insert scoped to `tenant_id` |
| TRK-5 | Tracking never breaks or visibly slows the host page | No synchronous blocking calls in the tracking path; verified via manual perf check on a real host page, not just our own |
| TRK-6 | An explicit "compare" event is recorded only on an explicit visitor action, where the host UI supports one | Never inferred from dwell time or session view count alone; powers the high-confidence "because you compared X vs Y" narrative tag |
| TRK-7 *(new)* | Visitor identification never captures PII | Anonymous id only (cookie/localStorage); no name/email/account/card data ever placed in event payloads, even if present on the host page |

### AGT
| ID | Requirement | Acceptance criteria |
|---|---|---|
| AGT-1 | System decides *when* to (re)generate recommendations, not on every event, per tenant per visitor | Trigger rule documented and testable (event count / time-since-last / cooldown), scoped by `tenant_id` + visitor id |
| AGT-2 | Agent aggregates a visitor's recent activity into a behavior summary | Summary derived from that tenant's `events` rows only, not from raw dump into the prompt; same-category view clustering folded in as a soft evaluation signal, distinct from an explicit compare action |
| AGT-3 | Agent retrieves candidate catalog items via semantic search over that tenant's own vector index | Retrieval is grounded and tenant-scoped — no item returned that isn't in that tenant's vector store |
| AGT-4 | Agent evaluates retrieval quality and can refine/retry | Bounded retry (max 2) on low-relevance results |
| AGT-5 | Agent generates a persuasive, comparison-driven narrative referencing only retrieved catalog items, using only facts present in that catalog data | LLM output validated: every referenced item ID exists in the retrieval set; no numeric/factual claim (price, rate, fee, spec) appears in the narrative that isn't present in the retrieved catalog data |
| AGT-6 | Recommendation is cached / reused when behavior is unchanged | Activity-hash comparison (per tenant + visitor) prevents redundant LLM calls |
| AGT-7 | All LLM calls route through Mesh API | No direct OpenAI/Anthropic/Gemini SDK calls outside Mesh base URL |
| AGT-8 *(new)* | Bot never answers outside the tenant's own catalog | A visitor question with no groundable answer in that tenant's catalog data gets an explicit "I don't have that information" style response, never a best-guess or general-knowledge answer |

### DLV
Now chat-bot-launcher delivery with real-time push, not an in-app dashboard (see pivot record §3.2,
§3.5).

**Implementation status:** the former dashboard/activity UI (`GET /api/recommendations/me`,
`GET /api/activity/me`, and their pages) was removed along with the AI-engineer login surface
(AUTH note above) — DLV-1 through DLV-4 and DLV-6 below describe the *target* chat-bot-widget
shape, not yet built. DLV-5 (scheduled digest) is disabled (its APScheduler job unregistered in
`app/main.py`) rather than redesigned, since it has no visitors to iterate over until the tracker
SDK reintroduces them — `app/services/digest.py` itself is untouched and ready to be re-registered
against visitor identity once that lands.

| ID | Requirement | Acceptance criteria |
|---|---|---|
| DLV-1 | Chat-bot launcher on the host page opens proactively when a trigger fires for that visitor | Launcher state change (badge/open) driven by a real-time push, not a poll; narrative + item cards rendered inside the widget |
| DLV-2 *(new)* | Real-time push reaches an open widget within seconds of the trigger firing | Trigger-fire-to-widget-update latency measured under normal load; push via SSE/WebSocket, not next-page-load polling |
| DLV-3 | Widget view refreshes after new agent runs | Stale recommendation not shown once a new one is stored/pushed |
| DLV-4 *(new)* | Visitor can ask the bot follow-up questions after a recommendation is shown | Follow-up answers are generated through the same catalog-grounded path as AGT-5/AGT-8, not a separate ungrounded chat completion |
| DLV-5 (bonus) | Scheduled digest delivered via email/Telegram, per tenant | Real scheduler (APScheduler/Celery Beat), not a manual trigger |
| DLV-6 | End visitor can view their own tracked activity and how it produced their current recommendation, where the tenant exposes this | Read-only view over already-persisted data (`events`, `trigger_reason` from `recommendations`) scoped to that tenant + visitor — no new backend logic |

### OBS
| ID | Requirement | Acceptance criteria |
|---|---|---|
| OBS-1 (bonus) | Agent graph execution is traced, per tenant | LangSmith trace exists per pipeline run, inspectable, filterable by `tenant_id` |
| OBS-2 (bonus) | Tenant admin can inspect recent pipeline traces for their own tenant only | Admin-only `/admin/observability` screen lists recent `agent_pipeline` runs for that tenant (status, latency, error, trace link) pulled live from the LangSmith API; shows a clear "not configured" state when `LANGSMITH_API_KEY` is unset rather than erroring |
| OBS-3 *(new)* | Every bot answer's grounding is auditable | The catalog facts that grounded a given bot answer are retrievable after the fact (audit trail — pivot record §4) |

---

## 3. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Performance | Event ingestion endpoint responds < 150ms p95, cross-origin, under demo load |
| NFR-2 | Cost/efficiency | Agent pipeline must not exceed 1 LLM generation call per trigger event (excluding bounded retries), per tenant per visitor |
| NFR-3 | Reliability | Dual-write failures never leave a tenant's catalog in a state where an item is browsable but absent from that tenant's vector store silently — must be flagged (`vector_synced`) |
| NFR-4 | Security | No secrets in repo; passwords hashed; admin routes authorization-checked server-side and tenant-scoped (not just hidden in UI) |
| NFR-5 | Maintainability | Agent pipeline expressed as named, testable nodes (LangGraph) rather than one monolithic prompt/function |
| NFR-6 | Observability | Every agent run persists `trigger_reason`, `tenant_id`, and timestamps for post-hoc debugging even without LangSmith |
| NFR-7 | Portability | App runs from a documented one-command local setup (README) with SQLite by default |
| NFR-8 *(new)* | Isolation | No query path can return cross-tenant data even under a coding mistake in a single route — enforced at the data-access layer, tested explicitly |
| NFR-9 *(new)* | Privacy | No PII/PCI fields ever persisted from tracked events, across all three catalog ingestion adapters |
| NFR-10 *(new)* | Real-time | Push transport degrades gracefully (documented fallback, even if not yet implemented) when SSE/WebSocket is unavailable to a visitor's browser/network |

---

## 4. Traceability note

Every ID above is referenced in:
- **MVP Roadmap** — which sprint/iteration delivers it
- **LLD** — which component/table/endpoint implements it
- **Test Strategy** — which test(s) verify it
