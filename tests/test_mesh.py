import json
from types import SimpleNamespace

from app.config import Settings
from app.services.mesh import MeshNarrativeGenerator
from app.services.narrative import decode_narrative


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    def create(self, **kwargs):
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _generator_with_response(content: str) -> MeshNarrativeGenerator:
    generator = MeshNarrativeGenerator(Settings(mesh_api_key="fake-key"))
    generator.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(content))
    )
    return generator


def test_generate_splits_understanding_and_points() -> None:
    content = json.dumps(
        {
            "activity_understanding": "Building a real-time voice agent.",
            "recommendation_points": [
                "Cartesia Sonic wins on latency.",
                "ElevenLabs Turbo v2.5 wins on naturalness.",
            ],
            "model_ids": [4, 3],
        }
    )
    generator = _generator_with_response(content)
    result = generator.generate(
        "summary",
        [
            {"id": 4, "title": "Cartesia Sonic", "provider": "Cartesia"},
            {"id": 3, "title": "ElevenLabs Turbo v2.5", "provider": "ElevenLabs"},
        ],
    )
    parsed = decode_narrative(result.narrative)
    assert parsed.understanding == "Building a real-time voice agent."
    assert parsed.points == [
        "Cartesia Sonic wins on latency.",
        "ElevenLabs Turbo v2.5 wins on naturalness.",
    ]
    assert result.model_ids == [4, 3]


def test_generate_strips_id_mentions_from_both_sections() -> None:
    content = json.dumps(
        {
            "activity_understanding": "Comparing Cartesia Sonic (ID 4) to peers.",
            "recommendation_points": [
                "Cartesia Sonic (ID 4) beats ElevenLabs Turbo v2.5 (id: 3) on latency."
            ],
            "model_ids": [4],
        }
    )
    generator = _generator_with_response(content)
    result = generator.generate(
        "summary", [{"id": 4, "title": "Cartesia Sonic", "provider": "Cartesia"}]
    )
    parsed = decode_narrative(result.narrative)
    assert "4" not in parsed.understanding
    assert "ID" not in parsed.understanding
    assert "4" not in parsed.points[0]
    assert "3" not in parsed.points[0]
    assert "Cartesia Sonic" in parsed.points[0]
    assert "ElevenLabs Turbo v2.5" in parsed.points[0]


def test_candidate_id_is_not_embedded_in_the_readable_description() -> None:
    """The candidate_id must still reach the model (for model_ids grounding), but not as
    part of the human-readable name/description text the narrative gets built from."""
    captured = {}

    class RecordingCompletions:
        def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            content = json.dumps(
                {
                    "activity_understanding": "ok",
                    "recommendation_points": ["ok"],
                    "model_ids": [4],
                }
            )
            message = SimpleNamespace(content=content)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    generator = MeshNarrativeGenerator(Settings(mesh_api_key="fake-key"))
    generator.client = SimpleNamespace(
        chat=SimpleNamespace(completions=RecordingCompletions())
    )
    generator.generate(
        "summary", [{"id": 4, "title": "Cartesia Sonic", "provider": "Cartesia"}]
    )
    user_message = captured["messages"][1]["content"]
    assert "- Cartesia Sonic (Cartesia, candidate_id=4)." in user_message
    assert "- 4: Cartesia Sonic" not in user_message
