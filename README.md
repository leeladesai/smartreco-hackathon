# SmartReco — Behavioral AI Recommendation Agent
## Krish Naik Hackathon 2026 Submission

A production-grade platform where an agentic AI system observes user behavior, retrieves relevant
products via RAG + semantic search, and generates personalized, persuasive recommendations that
refresh as behavior evolves.

---

## 📋 SDLC Documentation (complete planning phase)

Read in order:

1. **[docs/01-BRD.md](docs/01-BRD.md)** — Business Requirements: objectives, scope, success metrics
2. **[docs/02-FRD.md](docs/02-FRD.md)** — Functional Requirements: AUTH, CAT, TRK, AGT, DLV, OBS modules
3. **[docs/03-UX-Flows.md](docs/03-UX-Flows.md)** — UX Design: personas, flows, screen specs
4. **[docs/03-mockups.html](docs/03-mockups.html)** — Wireframes (open in a browser)
5. **[docs/04-MVP-Roadmap.md](docs/04-MVP-Roadmap.md)** — Agile sprint plan: MVP-0 → Iteration 3 → submission
6. **[docs/05-HLD.md](docs/05-HLD.md)** — High-level architecture, components, tech choices
7. **[docs/06-LLD.md](docs/06-LLD.md)** — DB schema, API contracts, LangGraph node contracts
8. **[docs/07-Test-Strategy.md](docs/07-Test-Strategy.md)** — TDD test plan mapped to FRD IDs

---

## 🎯 Key decisions

| Decision | Choice |
|---|---|
| Backend | FastAPI (async, non-blocking) |
| LLM integration | Mesh API (mandatory) |
| Vector database | Chroma (local, zero deps) |
| Agent framework | LangGraph (structured nodes) |
| Domain | Learning platform (courses/bootcamps) |
| Database | SQLite (dev) / Postgres (prod-shaped) |
| Testing | pytest, TDD-driven |

---

## 🚀 Quick start (once code is scaffolded)

```bash
cd smartreco-hackathon
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # fill in MESH_API_KEY=rsk_...
python seed_data.py
python -m uvicorn app.main:app --reload
```

Open http://localhost:8000

---

## 📁 Project structure

```
smartreco-hackathon/
├── docs/                 # SDLC documentation (complete)
├── app/                  # FastAPI app (build during MVP-0 — not yet scaffolded)
├── tests/                # pytest suite (TDD)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

See `docs/06-LLD.md` for the intended `app/` internal structure (models, api, agent, utils, frontend).

---

## 📈 Development timeline

- Days 1–3 (MVP-0): walking skeleton, real Mesh API call end to end
- Days 4–6 (Iteration 1): trigger logic, caching, event batching, full CRUD
- Days 7–10 (Iteration 2): LangGraph 5-node pipeline, grading/refine loop
- Days 11–12 (Iteration 3, bonus): LangSmith tracing, scheduled digest
- Days 13–14: README polish, seed data, CI green, demo video

---

**Status:** ✅ Planning phase complete. Ready for MVP-0 implementation.
