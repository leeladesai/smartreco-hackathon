# Functional Requirements Document (FRD)
## SmartReco — Behavioral AI Recommendation Agent

Traces to BRD v1.0. Each requirement has an ID used in the MVP roadmap, LLD, and test strategy for
end-to-end traceability.

---

## 1. Modules

| Module code | Module |
|---|---|
| AUTH | Authentication & roles |
| CAT  | Catalog / product management (admin) |
| TRK  | Behavioral event tracking |
| AGT  | Agentic recommendation engine |
| DLV  | Delivery (in-app + proactive) |
| OBS  | Observability |

---

## 2. Functional requirements

### AUTH
| ID | Requirement | Acceptance criteria |
|---|---|---|
| AUTH-1 | User can register with email/password | Password hashed (bcrypt/argon2); duplicate email rejected |
| AUTH-2 | User can log in and receive a session | Session cookie or JWT issued; invalid credentials rejected with generic error |
| AUTH-3 | Two roles exist: `user`, `admin` | Role stored on user record; role seeded for at least 1 admin at setup |
| AUTH-4 | Admin-only routes are protected | Non-admin hitting `/admin/*` receives 403 |

### CAT
| ID | Requirement | Acceptance criteria |
|---|---|---|
| CAT-1 | Admin can create a product (title, description, category, price) | Row written to SQL; response includes generated ID |
| CAT-2 | Admin can edit a product | SQL row updated; `updated_at` bumped |
| CAT-3 | Admin can delete a product | SQL row removed (or soft-deleted); no longer retrievable by agent |
| CAT-4 | Every create/edit/delete dual-writes to the vector store | Vector store reflects the product within the same request; failure sets `vector_synced=false` and is retried |
| CAT-5 | Users can browse/search the catalog | Catalog page lists products; search returns matching subset |

### TRK
| ID | Requirement | Acceptance criteria |
|---|---|---|
| TRK-1 | Frontend captures page/product views, searches, clicks, dwell time | Each event has type, user, optional product ref, timestamp |
| TRK-2 | Events are batched client-side | No network call per single event under normal browsing |
| TRK-3 | Events flush on a timer, size threshold, or page unload | Uses `sendBeacon` on unload; periodic flush otherwise |
| TRK-4 | Backend ingests events in bulk without blocking the request | Single POST accepts an array; bulk insert |
| TRK-5 | Tracking never breaks or visibly slows the page | No synchronous blocking calls in the tracking path; verified via manual perf check |

### AGT
| ID | Requirement | Acceptance criteria |
|---|---|---|
| AGT-1 | System decides *when* to (re)generate recommendations, not on every event | Trigger rule documented and testable (event count / time-since-last / cooldown) |
| AGT-2 | Agent aggregates a user's recent activity into a behavior summary | Summary derived from `events` table, not from raw dump into the prompt |
| AGT-3 | Agent retrieves candidate products via semantic search over the vector store | Retrieval is grounded — no product returned that isn't in the vector store |
| AGT-4 | Agent evaluates retrieval quality and can refine/retry | Bounded retry (max 2) on low-relevance results |
| AGT-5 | Agent generates a persuasive narrative referencing only retrieved products | LLM output validated: every referenced product ID exists in the retrieval set |
| AGT-6 | Recommendation is cached / reused when behavior is unchanged | Activity-hash comparison prevents redundant LLM calls |
| AGT-7 | All LLM calls route through Mesh API | No direct OpenAI/Anthropic/Gemini SDK calls outside Mesh base URL |

### DLV
| ID | Requirement | Acceptance criteria |
|---|---|---|
| DLV-1 | Latest recommendation is shown on the user's dashboard | Narrative + product cards rendered |
| DLV-2 | Recommendation view refreshes after new agent runs | Stale recommendation not shown once a new one is stored |
| DLV-3 (bonus) | Scheduled digest delivered via email/Telegram | Real scheduler (APScheduler/Celery Beat), not a manual trigger |

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
| NFR-3 | Reliability | Dual-write failures never leave the catalog in a state where a product is orderable/browsable but absent from the vector store silently — must be flagged (`vector_synced`) |
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
