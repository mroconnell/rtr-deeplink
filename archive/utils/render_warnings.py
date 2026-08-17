import html
import re

# Mirrors shared_static/deep_link.js's escapeHtml()/linkifyWarning() plus
# app/static/player.js's renderWarnings() phrase-button behavior -- the
# Archive's own warnings (transcript_warnings, and video_warnings as of
# 2026-08-10, see BACKLOG_DONE.md) are rendered server-side via Jinja2,
# not client-side JS, so they need their own equivalent rather than
# reusing the JS version directly. Kept in sync by hand, same convention
# as every other shared-shape-but-different-runtime pair in this repo.
_URL_RE = re.compile(r"(https?://[^\s<]+)")
_TRANSCRIBE_PHRASE_RE = re.compile(
    r"request a transcript from the audio", re.IGNORECASE
)


def render_warnings_html(warnings: list) -> str:
    """Turns a list of plain warning strings into safe, joined HTML --
    escapes first (warnings are server-generated, not user-submitted, but
    escaped anyway on the same "never trust it" principle the JS side
    already applies), then linkifies bare URLs, then makes the
    standardized "request a transcript from the audio" phrase (see
    generic_fallback.py and friends) a real clickable button --
    archive/static/meeting_page.js wires up `.transcribe-inline-trigger`
    clicks on page load for this exact markup, the same action
    #transcribeToggle's own click handler performs.

    Returns a plain str, already escaped -- the caller must render it
    with Jinja2's `|safe` (or the `warnings_html` filter registered in
    archive/main.py, which does exactly that) since this function does
    its own escaping internally; passing it back through Jinja2's
    autoescape would double-escape it.
    """
    linked = [
        _URL_RE.sub(
            r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
            html.escape(warning),
        )
        for warning in warnings
    ]
    with_buttons = [
        _TRANSCRIBE_PHRASE_RE.sub(
            lambda m: (
                f'<button type="button" class="transcribe-inline-trigger">{m.group(0)}</button>'
            ),
            line,
        )
        for line in linked
    ]
    return "<br>".join(with_buttons)
