# Functional Requirements Document (FRD)
## SmartReco — Behavioral AI Recommendation Agent

Traces to BRD v1.0. Each requirement has an ID used in the MVP roadmap, LLD, and test strategy for
end-to-end traceability.

---

## 1. Modules

| Module code | Module |
|---|---|
| AUTH | Authentication & roles |
| CAT  | Catalog / model management (admin) |
| TRK  | Behavioral event tracking |
| AGT  | Agentic recommendation engine |
| DLV  | Delivery (in-app + proactive) |
| OBS  | Observability |

---

## 2. Functional requirements

### AUTH
AI engineer and admin auth are deliberately two separate modules — a separate route, a separate form,
and (for admin) no self-registration — not one login screen with a role picker.

| ID | Requirement | Acceptance criteria |
|---|---|---|
| AUTH-1 | AI engineer can register with email/password at `POST /api/auth/register` | Password hashed (bcrypt/argon2); duplicate email rejected; role always created as `user` — this endpoint can never create an admin |
| AUTH-2 | AI engineer can log in and receive a session at `POST /api/auth/login` | Session cookie or JWT issued; invalid credentials rejected with generic error |
| AUTH-3 | Two roles exist: `user`, `admin` | Role stored on user record; at least 1 admin seeded at setup; no runtime endpoint grants the `admin` role |
| AUTH-4 | Admin-only routes are protected | Non-admin hitting `/api/admin/*` receives 403, enforced server-side by a role dependency |
| AUTH-5 | Admin logs in through a separate module at `POST /api/admin/login` | Distinct route/handler from AI engineer login; **no corresponding admin-registration endpoint exists** — admin accounts are only ever created by seeding or by another admin via a user-management action, never self-service |
| AUTH-6 | `POST /api/admin/login` only authenticates accounts with role `admin` | A correct password for a non-admin account is rejected with the same generic error as a wrong password — the endpoint never reveals whether the account exists or merely lacks the admin role |

### CAT
| ID | Requirement | Acceptance criteria |
|---|---|---|
| CAT-1 | Admin can create a model (title, description, story, provider, modality, price, latency, context window, use-case tags) via a modal form, not an inline page element | Row written to SQL; response includes generated ID; the create/edit form is a focused overlay, not a form embedded in the catalog list |
| CAT-2 | Admin can edit a model | SQL row updated; `updated_at` bumped |
| CAT-3 | Admin can delete a model | SQL row removed (or soft-deleted); no longer retrievable by agent |
| CAT-4 | Every create/edit/delete dual-writes to the vector store | Vector store reflects the model within the same request; failure sets `vector_synced=false` and is retried |
| CAT-5 | Users can browse/search the catalog | Catalog page lists models; search/filter by modality, provider, or use-case returns matching subset |

### TRK
| ID | Requirement | Acceptance criteria |
|---|---|---|
| TRK-1 | Frontend captures page/model views, searches, comparisons, dwell time | Each event has type, user, optional model ref, timestamp |
| TRK-2 | Events are batched client-side | No network call per single event under normal browsing |
| TRK-3 | Events flush on a timer, size threshold, or page unload | Uses `sendBeacon` on unload; periodic flush otherwise |
| TRK-4 | Backend ingests events in bulk without blocking the request | Single POST accepts an array; bulk insert |
| TRK-5 | Tracking never breaks or visibly slows the page | No synchronous blocking calls in the tracking path; verified via manual perf check |
| TRK-6 | A `model_compare` event is recorded only when the AI engineer takes an explicit "add to comparison" action (compare tray / Compare screen) | Never inferred from dwell time or session view count alone; powers the high-confidence "because you compared X vs Y" narrative tag |

### AGT
| ID | Requirement | Acceptance criteria |
|---|---|---|
| AGT-1 | System decides *when* to (re)generate recommendations, not on every event | Trigger rule documented and testable (event count / time-since-last / cooldown) |
| AGT-2 | Agent aggregates a user's recent activity into a behavior summary | Summary derived from `events` table, not from raw dump into the prompt; `model_view` events for 2+ distinct models of the same modality within a short window are folded in as a soft evaluation signal (e.g. "browsing multiple voice models") — distinct from, and never phrased as, an explicit `model_compare` |
| AGT-3 | Agent retrieves candidate models via semantic search over the vector store | Retrieval is grounded — no model returned that isn't in the vector store |
| AGT-4 | Agent evaluates retrieval quality and can refine/retry | Bounded retry (max 2) on low-relevance results |
| AGT-5 | Agent generates a persuasive, comparison-driven narrative referencing only retrieved models | LLM output validated: every referenced model ID exists in the retrieval set |
| AGT-6 | Recommendation is cached / reused when behavior is unchanged | Activity-hash comparison prevents redundant LLM calls |
| AGT-7 | All LLM calls route through Mesh API | No direct OpenAI/Anthropic/Gemini SDK calls outside Mesh base URL |

### DLV
| ID | Requirement | Acceptance criteria |
|---|---|---|
| DLV-1 | Latest recommendation is shown on the user's dashboard | Narrative + model cards rendered |
| DLV-2 | Recommendation view refreshes after new agent runs | Stale recommendation not shown once a new one is stored |
| DLV-3 (bonus) | Scheduled digest delivered via email/Telegram | Real scheduler (APScheduler/Celery Beat), not a manual trigger |
| DLV-4 | AI engineer can view their own tracked activity and how it produced their current recommendation | Read-only view over already-persisted data (`events`, `activity_hash`, `trigger_reason` from `recommendations`) — no new backend logic; shows the raw event log plus the `behavior_summary` → `activity_hash` → `trigger_reason` chain behind the delivered recommendation |

### OBS
| ID | Requirement | Acceptance criteria |
|---|---|---|
| OBS-1 (bonus) | Agent graph execution is traced | LangSmith trace exists per pipeline run, inspectable |

---

## 3. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Performance | Event ingestion endpoint responds < 150ms p95 under demo load |
| NFR-2 | Cost/efficiency | Agent pipeline must not exceed 1 LLM generation call per trigger event (excluding bounded retries) |
| NFR-3 | Reliability | Dual-write failures never leave the catalog in a state where a model is browsable but absent from the vector store silently — must be flagged (`vector_synced`) |
| NFR-4 | Security | No secrets in repo; passwords hashed; admin routes authorization-checked server-side (not just hidden in UI) |
| NFR-5 | Maintainability | Agent pipeline expressed as named, testable nodes (LangGraph) rather than one monolithic prompt/function |
| NFR-6 | Observability | Every agent run persists `trigger_reason` and timestamps for post-hoc debugging even without LangSmith |
| NFR-7 | Portability | App runs from a documented one-command local setup (README) with SQLite by default |

---

## 4. Traceability note

Every ID above is referenced in:
- **MVP Roadmap** — which sprint/iteration delivers it
- **LLD** — which component/table/endpoint implements it
- **Test Strategy** — which test(s) verify it
