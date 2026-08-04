import os

from sqlalchemy import select

from app.config import Settings
from app.db import build_session_factory
from app.models import Model, User
from app.security import hash_password
from app.vector import ModelVectorStore


SEED_MODELS = [
    {
        "title": "GPT-4o mini",
        "description": (
            "A fast, cost-aware general model for classification, extraction, "
            "and everyday product features."
        ),
        "provider": "OpenAI",
        "modality": "LLM",
        "price": "$0.15 / 1M input tokens",
        "context_window": "128K",
        "use_case_tags": ["structured output", "classification", "cost sensitive"],
        "source_url": "https://platform.openai.com/docs/models",
    },
    {
        "title": "ElevenLabs Turbo v2.5",
        "description": (
            "Low-latency text-to-speech for conversational agents that need "
            "streaming audio quickly."
        ),
        "provider": "ElevenLabs",
        "modality": "Voice",
        "price": "$0.0002 / character",
        "latency_ms": 275,
        "context_window": "5,000 characters",
        "use_case_tags": ["real-time voice", "customer support", "streaming"],
        "source_url": "https://elevenlabs.io/docs",
    },
    {
        "title": "Flux.1 Pro",
        "description": (
            "High-fidelity image generation for product concepts, marketing "
            "assets, and visual exploration."
        ),
        "provider": "Black Forest Labs",
        "modality": "Image",
        "price": "$0.05 / image",
        "context_window": "2,048px",
        "use_case_tags": ["image generation", "concept art", "marketing"],
        "source_url": "https://bfl.ai/models",
    },
    {
        "title": "Voyage-3",
        "description": (
            "Embedding model for semantic retrieval across technical documents "
            "and product catalogs."
        ),
        "provider": "Voyage AI",
        "modality": "Embedding",
        "price": "$0.02 / 1M tokens",
        "context_window": "32K",
        "use_case_tags": ["semantic search", "retrieval", "reranking"],
        "source_url": "https://docs.voyageai.com/docs/embeddings",
    },
]


def main() -> None:
    settings = Settings()
    session_factory = build_session_factory(settings)
    vector_store = ModelVectorStore(settings.chroma_db_path)
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "curator@smartreco.dev").lower()
    admin_password = os.getenv("SEED_ADMIN_PASSWORD", "admin@123")

    with session_factory() as session:
        admin = session.scalar(select(User).where(User.email == admin_email))
        if not admin:
            session.add(
                User(
                    email=admin_email,
                    password_hash=hash_password(admin_password),
                    role="admin",
                )
            )
        else:
            admin.role = "admin"
            admin.password_hash = hash_password(admin_password)

        for values in SEED_MODELS:
            model = session.scalar(select(Model).where(Model.title == values["title"]))
            if not model:
                model = Model(**values, vector_synced=False)
                session.add(model)
                session.flush()
            else:
                for key, value in values.items():
                    setattr(model, key, value)
            vector_store.upsert(model)
            model.vector_synced = True
        session.commit()

    print(f"Seeded Curator account: {admin_email}")
    print(f"Seeded {len(SEED_MODELS)} models into SQL and Chroma")


if __name__ == "__main__":
    main()
