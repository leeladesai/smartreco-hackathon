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
        "latency_ms": 820,
        "context_window": "128K",
        "use_case_tags": ["structured output", "classification", "cost sensitive"],
        "source_url": "https://platform.openai.com/docs/models",
    },
    {
        "title": "Claude 3.5 Sonnet",
        "description": (
            "Anthropic's balanced flagship — strong reasoning and long-document "
            "work at a lower cost than top-tier frontier models."
        ),
        "provider": "Anthropic",
        "modality": "LLM",
        "price": "$3.00 / 1M input tokens",
        "latency_ms": 640,
        "context_window": "200K",
        "use_case_tags": ["long context", "reasoning", "document analysis"],
        "source_url": "https://www.anthropic.com/pricing",
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
        "title": "Cartesia Sonic",
        "description": (
            "Ultra-low-latency speech generation built for real-time voice agents "
            "where every millisecond of round trip matters."
        ),
        "provider": "Cartesia",
        "modality": "Voice",
        "price": "$0.00015 / character",
        "latency_ms": 135,
        "context_window": "N/A",
        "use_case_tags": ["real-time voice", "low latency", "voice agents"],
        "source_url": "https://cartesia.ai",
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
        "title": "Stable Diffusion 3.5",
        "description": (
            "Open-weight image generation with strong prompt adherence at a "
            "fraction of the cost of closed-source alternatives."
        ),
        "provider": "Stability AI",
        "modality": "Image",
        "price": "$0.035 / image",
        "context_window": "1,536px",
        "use_case_tags": ["image generation", "open weights", "cost sensitive"],
        "source_url": "https://stability.ai/news/stable-diffusion-3-5",
    },
    {
        "title": "Runway Gen-3",
        "description": (
            "Text-to-video generation for short-form clips, concept previews, "
            "and storyboard exploration."
        ),
        "provider": "Runway",
        "modality": "Video",
        "price": "$0.10 / second",
        "context_window": "10s max",
        "use_case_tags": ["video generation", "storyboarding", "concept preview"],
        "source_url": "https://runwayml.com/research/introducing-gen-3-alpha",
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
    {
        "title": "Cohere Embed v3",
        "description": (
            "Multilingual embedding model tuned for retrieval-augmented generation "
            "and search re-ranking."
        ),
        "provider": "Cohere",
        "modality": "Embedding",
        "price": "$0.10 / 1M tokens",
        "context_window": "512",
        "use_case_tags": ["semantic search", "multilingual", "reranking"],
        "source_url": "https://cohere.com/pricing",
    },
]


def main() -> None:
    settings = Settings()
    session_factory = build_session_factory(settings)
    vector_store = ModelVectorStore(settings.chroma_db_path)
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "curator@smartreco.dev").lower()
    admin_password = os.getenv("SEED_ADMIN_PASSWORD", "admin@123")
    engineer_email = os.getenv("SEED_ENGINEER_EMAIL", "engineer@smartreco.dev").lower()
    engineer_password = os.getenv("SEED_ENGINEER_PASSWORD", "engineer@123")

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

        engineer = session.scalar(select(User).where(User.email == engineer_email))
        if not engineer:
            session.add(
                User(
                    email=engineer_email,
                    password_hash=hash_password(engineer_password),
                    role="user",
                )
            )
        else:
            engineer.role = "user"
            engineer.password_hash = hash_password(engineer_password)

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
    print(f"Seeded AI-engineer account: {engineer_email}")
    print(f"Seeded {len(SEED_MODELS)} models into SQL and Chroma")


if __name__ == "__main__":
    main()
