"""HTML rendering for the scheduled recommendation digest email — kept separate from
digest.py's delivery/orchestration logic. Table-based layout with everything inlined
(styles, no external assets) since that's the only markup subset that renders
consistently across real inboxes (Gmail, Outlook, Apple Mail); no `<style>` block,
no JS, no remote images.
"""

import html

from app.services.narrative import Narrative

# Mirrors the modality accent colors used in the app itself (app/static/js/app.js
# modalityColors) so the email doesn't invent a second, inconsistent palette.
MODALITY_COLORS = {
    "LLM": "#5ec8d8",
    "Voice": "#e8a33d",
    "Image": "#a78bfa",
    "Video": "#f0708a",
    "Embedding": "#4fd1a5",
    "Multimodal": "#5ec8d8",
}
DEFAULT_MODALITY_COLOR = "#8b93a3"


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _model_card_html(model: dict) -> str:
    color = MODALITY_COLORS.get(model.get("modality") or "", DEFAULT_MODALITY_COLOR)
    meta_bits = [bit for bit in (model.get("provider"), model.get("price")) if bit]
    why_this = model.get("why_this")
    why_block = (
        f"""
              <tr><td style="padding-top:10px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr><td style="background:#f6f4ee;border-left:3px solid {color};
                      border-radius:4px;padding:8px 12px;font-size:13px;line-height:1.5;
                      color:#3a362c;">{_esc(why_this)}</td></tr>
                </table>
              </td></tr>"""
        if why_this
        else ""
    )
    return f"""
      <tr><td style="padding:0 32px 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #e2ddce;border-radius:10px;">
          <tr><td style="padding:16px 18px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-size:15px;font-weight:700;color:#1c1a16;font-family:
                    -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
                  {_esc(model.get("title"))}
                </td>
                <td align="right" style="white-space:nowrap;">
                  <span style="display:inline-block;padding:3px 10px;
                      border-radius:999px;font-size:11px;font-weight:600;
                      letter-spacing:.02em;background:{color}26;color:{color};
                      font-family:monospace;">
                    {_esc(model.get("modality"))}
                  </span>
                </td>
              </tr>
              <tr><td colspan="2" style="padding-top:3px;font-size:13px;
                  color:#6b6455;font-family:-apple-system,Segoe UI,Roboto,
                  Helvetica,Arial,sans-serif;">
                {_esc(" · ".join(meta_bits))}
              </td></tr>
              {why_block}
            </table>
          </td></tr>
        </table>
      </td></tr>"""


def render_recommendation_email_html(
    narrative: Narrative | None,
    models: list[dict],
    fallback_summary: str,
    app_url: str | None = None,
) -> str:
    """Builds the full HTML document for the digest email. `models` is a plain list of
    dicts (title, provider, modality, price, why_this) — deliberately not the ORM
    objects or the API's ModelResponse schema, so this module has no dependency on
    either and stays easy to unit-test in isolation.
    """
    understanding = narrative.understanding if narrative else fallback_summary
    points = narrative.points if narrative else []

    points_html = ""
    if points:
        items = "".join(
            f"""<li style="margin:0 0 6px;font-size:14px;line-height:1.5;
                    color:#3a362c;">{_esc(point)}</li>"""
            for point in points
        )
        points_html = f"""
      <tr><td style="padding:4px 32px 8px;">
        <p style="margin:0 0 6px;font-size:12px;font-weight:700;letter-spacing:.05em;
            text-transform:uppercase;color:#8f8875;font-family:monospace;">
          Why these picks
        </p>
        <ul style="margin:0;padding-left:18px;">{items}</ul>
      </td></tr>"""

    cards_html = "".join(_model_card_html(model) for model in models) or (
        """<tr><td style="padding:0 32px 16px;font-size:14px;color:#6b6455;">
             Retrieval is still catching up — check your dashboard shortly.
           </td></tr>"""
    )

    cta_html = ""
    if app_url:
        cta_html = f"""
      <tr><td style="padding:8px 32px 28px;">
        <a href="{_esc(app_url)}" style="display:inline-block;background:#1c1a16;
            color:#fbfaf6;text-decoration:none;font-size:13px;font-weight:600;
            padding:11px 20px;border-radius:7px;font-family:-apple-system,Segoe UI,
            Roboto,Helvetica,Arial,sans-serif;">
          View full dashboard →
        </a>
      </td></tr>"""

    return f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#f3f1ea;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#f3f1ea;">
    <tr><td align="center" style="padding:32px 16px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;
             overflow:hidden;border:1px solid #e2ddce;">
        <tr><td style="background:#12151c;padding:22px 32px;">
          <span style="font-family:monospace;font-size:13px;font-weight:700;
              letter-spacing:.08em;color:#eceff3;">
            <span style="color:#5ec8d8;">▍</span><span style="color:#e8a33d;">▍</span
            ><span style="color:#a78bfa;">▍</span> TRAILMIND
          </span>
          <span style="font-family:monospace;font-size:12px;color:#8b93a3;">
            &nbsp;/ your recommendation digest
          </span>
        </td></tr>
        <tr><td style="padding:28px 32px 6px;">
          <p style="margin:0 0 6px;font-size:12px;font-weight:700;letter-spacing:.05em;
              text-transform:uppercase;color:#8f8875;font-family:monospace;">
            Based on your recent activity
          </p>
          <p style="margin:0;font-size:16px;line-height:1.6;color:#1c1a16;
              font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
            {_esc(understanding)}
          </p>
        </td></tr>
        {points_html}
        <tr><td style="padding:20px 32px 4px;">
          <p style="margin:0;font-size:12px;font-weight:700;letter-spacing:.05em;
              text-transform:uppercase;color:#8f8875;font-family:monospace;">
            Recommended for you
          </p>
        </td></tr>
        <tr><td style="padding-top:10px;"></td></tr>
        {cards_html}
        {cta_html}
        <tr><td style="padding:18px 32px 26px;border-top:1px solid #e2ddce;">
          <p style="margin:0;font-size:12px;line-height:1.5;color:#8f8875;
              font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
            You're receiving this because you have an active TrailMind account.
            Manage delivery preferences from your dashboard's "Proactive digest
            delivery" panel.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
