from app.services.email_template import render_recommendation_email_html
from app.services.narrative import decode_narrative, encode_narrative


def test_render_includes_understanding_and_points() -> None:
    narrative = decode_narrative(
        encode_narrative(
            "You've been comparing low-latency voice models.",
            ["ElevenLabs beats the field on latency."],
        )
    )
    html = render_recommendation_email_html(narrative, [], "fallback")
    assert "You&#x27;ve been comparing low-latency voice models." in html
    assert "ElevenLabs beats the field on latency." in html


def test_render_falls_back_to_summary_when_no_narrative() -> None:
    html = render_recommendation_email_html(None, [], "evaluating voice models")
    assert "evaluating voice models" in html


def test_render_model_card_includes_title_provider_price_and_reason() -> None:
    models = [
        {
            "title": "Cartesia Sonic",
            "provider": "Cartesia",
            "modality": "Voice",
            "price": "$0.00015/char",
            "why_this": "matches your real-time voice search",
        }
    ]
    html = render_recommendation_email_html(None, models, "fallback")
    assert "Cartesia Sonic" in html
    assert "Cartesia" in html
    assert "$0.00015/char" in html
    assert "matches your real-time voice search" in html
    assert "Voice" in html


def test_render_shows_placeholder_when_no_models() -> None:
    html = render_recommendation_email_html(None, [], "fallback")
    assert "still catching up" in html


def test_render_omits_cta_link_without_app_url() -> None:
    html = render_recommendation_email_html(None, [], "fallback", app_url=None)
    assert "View full dashboard" not in html


def test_render_includes_cta_link_with_app_url() -> None:
    html = render_recommendation_email_html(
        None, [], "fallback", app_url="https://trailmind.example/dashboard"
    )
    assert "https://trailmind.example/dashboard" in html
    assert "View full dashboard" in html


def test_render_escapes_html_in_model_and_narrative_fields() -> None:
    """Model titles are curator-authored (or bulk-uploaded) content, not app-controlled
    strings — they must never be interpolated into the email unescaped, or a malicious
    catalog entry becomes stored XSS against every recipient's mail client."""
    models = [
        {
            "title": "<script>alert(1)</script>",
            "provider": "<img src=x onerror=alert(2)>",
            "modality": "Voice",
            "price": "$1",
            "why_this": "<b>bold</b> claim",
        }
    ]
    html = render_recommendation_email_html(None, models, "<script>evil</script>")
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(2)>" not in html
    assert "<b>bold</b>" not in html
    assert "&lt;script&gt;" in html
