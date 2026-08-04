# SmartReco — Technical Architecture Diagram

Component-level view: where each piece runs, which database/vector store it talks to, and how
requests flow end to end — client, through the deployment boundary, to the external LLM call, and
back.

> **Living document.** This reflects the design as of the current planning/build phase. Update it
> as the architecture evolves — especially once real deployment infra (hosting target, secrets
> store, CI/CD) is decided — rather than letting it drift from what's actually built.

```mermaid
flowchart TB
    engineer["Browser — AI Engineer\nPOST /login"]
    curator["Browser — Curator\nPOST /admin/login"]

    subgraph DEPLOY["DEPLOYMENT BOUNDARY — single container / VM (Railway / Render / Fly)"]
        api["FastAPI App\nroutes: auth · catalog · events · recommendations · activity"]

        subgraph INTERACTION["Interaction loop — synchronous, no LLM calls"]
            ingest["Event Ingestion\nPOST /events/batch"]
            dualwrite["Admin Dual-Write\nPOST/PUT/DELETE /admin/models"]
            browse["Catalog Browse / Search\nGET /models"]
        end

        trigger{{"Trigger Evaluator\nevents_since_last ≥ 5\nOR time_elapsed > 10min\n(2min cooldown)\n— cheap SQL check"}}

        subgraph AGENT["Recommendation loop — async background task — LangGraph pipeline"]
            direction LR
            analyze["① Analyze\nActivity"]
            retrieve["② Retrieve\nModels"]
            grade["③ Grade /\nRefine"]
            generate["④ Generate\nNarrative"]
            store["⑤ Store &\nDeliver"]
            analyze --> retrieve --> grade
            grade -. "weak score\nretry ≤ 2" .-> retrieve
            grade --> generate --> store
        end

        sql[("SQL Database\nSQLite (dev) / PostgreSQL (prod)\ntables: users, models, events, recommendations")]
        vector[("Vector Database\nChroma\ncollection: models")]
        scheduler["Scheduler\nAPScheduler — bonus"]
    end

    mesh["Mesh API\nOpenAI-compatible base URL\nthe ONLY LLM call in the system"]
    langsmith["LangSmith\noptional tracing — bonus"]
    digest["Email / Telegram\nproactive digest — bonus"]

    engineer --> api
    curator --> api
    api --> ingest
    api --> dualwrite
    api --> browse

    ingest -->|"bulk insert"| sql
    dualwrite -->|"write row"| sql
    dualwrite -->|"upsert / delete\nsets vector_synced"| vector
    browse -->|"read"| sql

    ingest --> trigger
    trigger -->|"fires"| analyze
    trigger -.->|"no fire — 200 OK,\nno agent run"| api

    retrieve <-->|"top-k=8\nsemantic search"| vector
    generate -->|"single generation\ncall per trigger"| mesh
    store -->|"write recommendation\nnarrative + model_ids +\nbehavior_summary + activity_hash"| sql

    sql -->|"GET /recommendations/me\nGET /activity/me"| api
    api --> engineer
    api --> curator

    scheduler -.->|"cron sweep"| analyze
    store -.-> langsmith
    store -.-> digest

    classDef sync stroke:#5ec8d8,stroke-width:2px;
    classDef async stroke:#e8a33d,stroke-width:2px;
    classDef data stroke:#4fd1a5,stroke-width:2px;
    classDef external stroke:#a78bfa,stroke-width:2px;
    classDef bonus stroke:#f0708a,stroke-width:2px,stroke-dasharray: 4 3;

    class ingest,dualwrite,browse,trigger sync
    class analyze,retrieve,grade,generate,store async
    class sql,vector data
    class mesh,langsmith external
    class scheduler,digest bonus
```

## Legend

| Style | Meaning |
|---|---|
| Cyan border | Interaction loop — synchronous, cheap, never calls an LLM |
| Amber border | Recommendation loop — async background task, the one path that calls an LLM |
| Teal border, cylinder shape | Data store (SQL or vector) |
| Violet border | External service (outside the deployment boundary) |
| Rose dashed border | Bonus / optional (scheduler, digest, LangSmith) |
| Diamond | Decision point (trigger evaluator) |
| Dashed arrow | Optional or conditional path |

## Component-to-storage map

| Component | Reads | Writes |
|---|---|---|
| Event ingestion | — | SQL `events` |
| Admin dual-write | — | SQL `models`, Chroma `models` collection |
| Catalog browse/search | SQL `models` | — |
| Trigger evaluator | SQL `recommendations`, `events` | — |
| `analyze_activity` | SQL `events`, `recommendations` (last hash) | — |
| `retrieve_models` | Chroma `models` collection | — |
| `generate_narrative` | — | Mesh API (external call) |
| `store_and_deliver` | — | SQL `recommendations` |
| Dashboard / Activity read | SQL `recommendations`, `events` | — |

Full requirement-level detail (schema DDL, API contracts, per-node input/output) stays in
[`06-LLD.md`](06-LLD.md); this diagram is the visual index into that document, not a replacement
for it.
