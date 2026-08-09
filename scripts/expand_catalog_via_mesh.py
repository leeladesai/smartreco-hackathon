"""One-off script: expand the model catalog with LLM-generated synthetic entries.

Uses the Mesh API (same client construction as app.services.mesh.MeshNarrativeGenerator)
to generate ~15-20 clearly fictional AI model catalog entries as JSON, validates each
through app.schemas.ModelCreate, and inserts the valid ones via
app.services.catalog.create_model (same tested path seed_data.py relies on — handles
both the SQL insert and the Chroma vector-store upsert).

Safe to re-run: entries whose title already exists in the DB (case-insensitive) are
skipped rather than duplicated.

IMPORTANT: these are synthetic, LLM-invented catalog entries for hackathon demo
volume. They are not real products and must not be mistaken for real AI vendors.
"""

import json

from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.db import build_session_factory
from app.models import Model
from app.schemas import ModelCreate
from app.services.catalog import create_model
from app.vector import ModelVectorStore, build_embedding_function


EXISTING_TITLES = {
    "GPT-4o mini",
    "Claude 3.5 Sonnet",
    "ElevenLabs Turbo v2.5",
    "Cartesia Sonic",
    "Flux.1 Pro",
    "Stable Diffusion 3.5",
    "Runway Gen-3",
    "Voyage-3",
    "Cohere Embed v3",
}

SYSTEM_PROMPT = (
    "You are a data-generation assistant helping populate a demo catalog for a "
    "hackathon project called TrailMind. Generate clearly FICTIONAL, SYNTHETIC AI "
    "model catalog entries. These must NOT be real products — invent fictional "
    "provider/company names and fictional product names. Do not reuse or lightly "
    "rename any real AI company (e.g. OpenAI, Anthropic, Google, Meta, ElevenLabs, "
    "Cartesia, Black Forest Labs, Stability AI, Runway, Voyage AI, Cohere, Mistral, "
    "xAI, Amazon, Microsoft) or any real product name. The entries should still look "
    "like plausible, realistic catalog rows in terms of formatting (pricing units, "
    "latency, context window) even though the companies and products are made up. "
    'Return ONLY valid JSON: an object with a single key "models" whose value is '
    "an array of entry objects. Do not include markdown fences or commentary."
)

USER_PROMPT = (
    "Generate 18 new, clearly fictional AI model catalog entries as a JSON array "
    'under the "models" key. Each entry must be an object with exactly these '
    "fields:\n"
    "- title (string): a fictional product name, must not collide with these "
    "existing catalog titles: " + ", ".join(sorted(EXISTING_TITLES)) + "\n"
    "- description (string): 1-2 sentences describing what it's good for\n"
    "- provider (string): a fictional company/vendor name\n"
    '- modality (string): one of "LLM", "Voice", "Image", "Video", '
    '"Embedding", or "Multimodal" (use "Multimodal" for at most 2 entries)\n'
    '- price (string): formatted like "$0.15 / 1M input tokens", "$0.05 / '
    'image", "$0.10 / second", "$0.0002 / character", or "$0.02 / 1M '
    'tokens" depending on modality\n'
    "- latency_ms (integer or null): typical latency in milliseconds, null if not "
    "applicable\n"
    '- context_window (string or null): e.g. "128K", "5,000 characters", '
    '"2,048px", "10s max", null if not applicable\n'
    '- use_case_tags (array of 2-4 short strings): e.g. ["structured output", '
    '"classification"]\n'
    "- source_url (string or null): a plausible-looking placeholder documentation "
    "URL on a fictional domain (does not need to resolve)\n\n"
    "Spread the entries across modalities: several LLM, several Voice, several "
    "Image, at least one Video, several Embedding, and 1-2 Multimodal. Make sure "
    "titles and providers are unambiguously invented, not real-world brands.\n\n"
    'Return JSON exactly like: {"models": [{"title": "...", "description": "...", '
    '"provider": "...", "modality": "...", "price": "...", "latency_ms": 123, '
    '"context_window": "...", "use_case_tags": ["...", "..."], "source_url": '
    '"..."}]}'
)


def main() -> None:
    settings = Settings()

    if not settings.mesh_api_key:
        print(
            "Mesh API key is not configured — settings.mesh_api_key is empty.\n"
            "Set MESH_API_KEY in your .env file (see app/config.py: Settings.mesh_api_key, "
            "PROJECT_ROOT/.env). Refusing to fabricate catalog data without going "
            "through Mesh. Stopping."
        )
        return

    client = OpenAI(api_key=settings.mesh_api_key, base_url=settings.mesh_base_url)

    print(
        f"Requesting synthetic catalog entries from Mesh model '{settings.mesh_model}'..."
    )
    response = client.chat.completions.create(
        model=settings.mesh_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
    )
    content = response.choices[0].message.content or "{}"

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"Mesh response was not valid JSON: {exc}")
        print("Raw response:")
        print(content)
        return

    raw_entries = payload.get("models") if isinstance(payload, dict) else None
    if raw_entries is None and isinstance(payload, list):
        raw_entries = payload
    if not isinstance(raw_entries, list):
        print("Mesh response JSON did not contain a 'models' array. Raw payload:")
        print(json.dumps(payload, indent=2))
        return

    print(f"Mesh generated {len(raw_entries)} candidate entries.")

    settings = Settings()
    session_factory = build_session_factory(settings)
    vector_store = ModelVectorStore(
        settings.chroma_db_path,
        collection_name=settings.chroma_collection_name,
        embedding_function=build_embedding_function(settings),
    )

    inserted = 0
    skipped_duplicate = 0
    invalid = 0
    inserted_titles: list[tuple[str, str]] = []

    with session_factory() as session:
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                invalid += 1
                print(f"  [{index}] invalid: entry is not a JSON object")
                continue

            title = str(raw.get("title", "")).strip()

            try:
                payload_model = ModelCreate(**raw)
            except ValidationError as exc:
                invalid += 1
                print(f"  [{index}] invalid entry '{title or '(no title)'}': {exc}")
                continue

            existing = session.scalar(
                select(Model).where(Model.title.ilike(payload_model.title))
            )
            if existing:
                skipped_duplicate += 1
                print(
                    f"  [{index}] skipped (title already exists): '{payload_model.title}'"
                )
                continue

            model = create_model(session, vector_store, payload_model)
            inserted += 1
            inserted_titles.append((model.title, model.modality))
            print(f"  [{index}] inserted: '{model.title}' ({model.modality})")

    print()
    print("=== Summary ===")
    print(f"Generated: {len(raw_entries)}")
    print(f"Inserted:  {inserted}")
    print(f"Skipped (duplicate title): {skipped_duplicate}")
    print(f"Invalid (failed validation / bad shape): {invalid}")
    if inserted_titles:
        print()
        print("New models:")
        for title, modality in inserted_titles:
            print(f"  - {title} ({modality})")


if __name__ == "__main__":
    main()
