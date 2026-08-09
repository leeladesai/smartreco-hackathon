from app.services.narrative import (
    decode_narrative,
    encode_narrative,
    narrative_as_plain_text,
)


def test_encode_decode_roundtrip() -> None:
    raw = encode_narrative("Building a voice agent.", ["Point one.", "Point two."])
    parsed = decode_narrative(raw)
    assert parsed.understanding == "Building a voice agent."
    assert parsed.points == ["Point one.", "Point two."]


def test_decode_returns_none_for_plain_text() -> None:
    assert decode_narrative("Just a plain sentence.") is None
    assert decode_narrative(None) is None
    assert decode_narrative("") is None


def test_decode_returns_none_for_empty_structure() -> None:
    assert decode_narrative(encode_narrative("", [])) is None


def test_plain_text_flattens_structured_narrative() -> None:
    raw = encode_narrative("Building a voice agent.", ["Point one.", "Point two."])
    text = narrative_as_plain_text(raw)
    assert text == (
        "Understanding your activity: Building a voice agent.\n"
        "Why these recommendations:\n"
        "- Point one.\n"
        "- Point two."
    )


def test_plain_text_passes_through_non_structured_narrative() -> None:
    assert narrative_as_plain_text("You'll like this.") == "You'll like this."


def test_plain_text_uses_fallback_when_narrative_is_empty() -> None:
    assert narrative_as_plain_text(None, "fallback summary") == "fallback summary"
    assert narrative_as_plain_text("", "fallback summary") == "fallback summary"
