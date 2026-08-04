# SmartReco — Behavioral AI Recommendation Agent
## Krish Naik Hackathon 2026 Submission

A production-grade platform where an agentic AI system observes user behavior, retrieves relevant
AI models via RAG + semantic search, and generates personalized, persuasive comparison
recommendations that refresh as behavior evolves.

---

## 📋 SDLC Documentation (complete planning phase)

Read in order:

1. **[docs/00-Domain-Decision.md](docs/00-Domain-Decision.md)** — Domain decision record: options
   considered, scoring, and why the AI model/tool catalog was chosen
2. **[docs/01-BRD.md](docs/01-BRD.md)** — Business Requirements: objectives, scope, success metrics
3. **[docs/02-FRD.md](docs/02-FRD.md)** — Functional Requirements: AUTH, CAT, TRK, AGT, DLV, OBS modules
4. **[docs/03-UX-Flows.md](docs/03-UX-Flows.md)** — UX Design: personas, flows, screen specs
5. **[docs/03-mockups.html](docs/03-mockups.html)** — Wireframes (open in a browser)
6. **[docs/04-MVP-Roadmap.md](docs/04-MVP-Roadmap.md)** — Agile sprint plan: MVP-0 → Iteration 3 → submission
7. **[docs/05-HLD.md](docs/05-HLD.md)** — High-level architecture, components, tech choices
8. **[docs/05-architecture-diagram.md](docs/05-architecture-diagram.md)** — component diagram: deployment boundary, both loops, agent pipeline, SQL/vector DBs, external LLM call
9. **[docs/06-LLD.md](docs/06-LLD.md)** — DB schema, API contracts, LangGraph node contracts
10. **[docs/07-Test-Strategy.md](docs/07-Test-Strategy.md)** — TDD test plan mapped to FRD IDs

---

## 🎯 Key decisions

| Decision | Choice |
|---|---|
| Backend | FastAPI (async, non-blocking) |
| LLM integration | Mesh API (mandatory) |
| Vector database | Chroma (local, zero deps) |
| Agent framework | LangGraph (structured nodes) |
| Domain | AI model & tool catalog (comparison-based recs) — see `docs/00-Domain-Decision.md` |
| Database | SQLite (dev) / Postgres (prod-shaped) |
| Testing | pytest, TDD-driven |

---

## 🚀 Quick start

```bash
cd smartreco-hackathon
uv sync
source .venv/bin/activate      # Windows: .venv\Scripts\activate
cp .env.example .env           # fill in MESH_API_KEY=rsk_...
uv run python seed_data.py
uv run uvicorn app.main:app --reload --port 8001
```

Open http://localhost:8001

### One-command development startup

The current FastAPI process serves both the backend APIs and the frontend UI. Start it with log
tailing enabled:

```bash
./scripts/start_dev.sh
```

It uses port `8001` by default. Override it with `PORT=8002 ./scripts/start_dev.sh`. Press Ctrl-C
to stop the server and log tail.

---

## 📁 Project structure

```
smartreco-hackathon/
├── docs/                 # SDLC documentation (complete)
├── app/                  # FastAPI application
├── tests/                # pytest suite (TDD)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

See `docs/06-LLD.md` for the intended `app/` internal structure (models, api, agent, utils, frontend).

### Current handshake MVP

The first slice serves the updated self-contained UI at `/`. It includes the AI engineer and Curator
entry points, model catalog, model detail, comparison tray, dashboard recommendation preview,
activity trace, and catalog management view using local demo data from `docs/03-mockups.html`.
The backend now includes local authentication, SQL/Chroma model catalog APIs, seed data, batched
event ingestion, and server-rendered routes for each screen. The Curator login and model catalog
screens use those APIs; dashboard candidates are grounded in Chroma and, when `MESH_API_KEY` is
configured, the triggered recommendation is generated through Mesh and persisted with only
retrieved model IDs. Without a Mesh key the dashboard honestly remains in retrieval-ready mode.
For the seeded local demo, use `curator@smartreco.dev` / `admin@123`.

---

## 📈 Development timeline

- Days 1–3 (MVP-0): walking skeleton, real Mesh API call end to end
- Days 4–6 (Iteration 1): trigger logic, caching, event batching, full CRUD
- Days 7–10 (Iteration 2): LangGraph 5-node pipeline, grading/refine loop
- Days 11–12 (Iteration 3, bonus): LangSmith tracing, scheduled digest
- Days 13–14: README polish, seed data, CI green, demo video

---

**Status:** ✅ Planning phase complete. MVP-0 implementation is in progress.
