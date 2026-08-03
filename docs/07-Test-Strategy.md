# Test Strategy (TDD-driven)
## SmartReco

Approach: write the failing test for a node/endpoint before implementing it, per FRD ID. This also
directly de-risks the rubric's "faked or stubbed features score poorly" line — a test suite that
actually exercises the vector DB and Mesh API is itself evidence of a non-stubbed system.

## 1. Test pyramid

| Layer | Tooling | What it covers |
|---|---|---|
| Unit | `pytest` | Trigger evaluator logic, activity-hash function, grading threshold logic, grounding filter |
| Integration | `pytest` + test SQLite + Chroma in-memory/tmp path | Dual-write consistency, event batch ingestion, recommendation storage round-trip |
| Contract | `pytest` + `respx`/mocked Mesh client | Agent nodes against a mocked Mesh API response (deterministic, no real spend in CI) |
| End-to-end (manual/scripted) | Browser or `httpx` against running app | Full user journey: browse → trigger → dashboard shows grounded recs |

CI should run unit + integration + contract on every push (mocked LLM); a small number of real
Mesh API calls can be run manually or in a nightly job to sanity-check prompts, not on every commit.

## 2. Test cases mapped to FRD

### AUTH
- `test_register_hashes_password` (AUTH-1)
- `test_register_never_creates_admin_role` (AUTH-1, AUTH-3) — assert `POST /api/auth/register` cannot produce a role other than `user`, even if a `role` field is smuggled into the request body
- `test_login_rejects_wrong_password` (AUTH-2)
- `test_admin_route_blocks_non_admin` (AUTH-4)
- `test_admin_login_is_separate_route_from_builder_login` (AUTH-5) — assert `/api/admin/login` and `/api/auth/login` are distinct handlers and no `/api/admin/register` route exists
- `test_admin_login_rejects_non_admin_account_with_generic_error` (AUTH-6) — a valid password for a non-admin user hitting `/api/admin/login` gets the same error as a wrong password, not a role-specific message

### CAT — dual-write correctness (highest-value tests for this rubric)
- `test_create_model_writes_sql_and_vector` (CAT-1, CAT-4): assert row exists in SQL **and**
  a query against Chroma returns it
- `test_vector_write_failure_sets_synced_false` (CAT-4, NFR-3): mock Chroma failure, assert
  `vector_synced=False` and model still readable from SQL (no data loss, no silent success)
- `test_delete_model_removes_from_vector_store` (CAT-3)

### TRK
- `test_batch_endpoint_bulk_inserts` (TRK-4)
- `test_batch_endpoint_handles_partial_bad_events` — malformed single event in a batch doesn't
  drop the whole batch (robustness beyond the literal FRD line, worth having)
- `test_model_compare_only_fires_on_explicit_action` (TRK-6) — simulate 2+ `model_view` events for
  distinct models with no "add to comparison" action; assert **no** `model_compare` event is
  produced by session view count alone

### AGT — the core of the rubric's "efficiency" and "grounding" judgment
- `test_trigger_does_not_fire_below_threshold` (AGT-1)
- `test_trigger_fires_on_event_count` / `test_trigger_fires_on_time_elapsed` (AGT-1)
- `test_trigger_respects_cooldown` (AGT-1, NFR-2) — **this is the test that proves you don't spam
  the LLM**
- `test_same_activity_hash_skips_generation` (AGT-6) — assert the mocked Mesh client is called
  **zero** times on the second run when activity hasn't changed
- `test_analyze_activity_clusters_same_modality_views` (AGT-2) — feed 2+ `model_view` events for
  distinct models of the same modality within the clustering window; assert `behavior_summary`
  reflects the soft "evaluating <modality>" signal without claiming an explicit comparison
- `test_retrieval_returns_only_indexed_models` (AGT-3)
- `test_grade_refine_retries_on_weak_scores_then_stops_at_max` (AGT-4)
- `test_narrative_ids_are_filtered_against_candidates` (AGT-5) — feed the mocked LLM a response
  containing a model ID that was **not** in the candidate set; assert it's dropped before storage.
  **This is the single most important test in the suite** — it's the automated proof that
  recommendations are grounded, not hallucinated.
- `test_all_llm_calls_use_mesh_base_url` (AGT-7) — inspect the configured client base URL in a
  fixture/config test; cheap and directly protects against CI disqualification

### DLV
- `test_dashboard_returns_latest_recommendation_only` (DLV-1, DLV-2)
- `test_activity_endpoint_returns_persisted_data_not_hardcoded` (DLV-4) — seed real events and a
  real recommendation, assert `GET /api/activity/me` returns them verbatim (events, behavior
  summary, activity hash, trigger reason) rather than a static/mocked payload

### OBS (bonus)
- `test_langsmith_trace_created_per_run` (OBS-1) — can be a lightweight assertion that tracing env
  vars are honored / a trace object is produced, not a full LangSmith integration test

## 3. Definition of Done, test-wise

A ticket referencing an FRD ID is not "done" until its corresponding test(s) above are written and
green — this should be stated explicitly in the sprint board (see MVP Roadmap) so TDD isn't a
one-off intention but a per-ticket gate.

## 4. What NOT to over-test

Don't chase 100% coverage on Jinja2 templates or CSS — time is better spent on the dual-write and
grounding tests above, since those map directly to the two ways this specific rubric penalizes
teams (faked features, ungrounded/hardcoded recommendations).
