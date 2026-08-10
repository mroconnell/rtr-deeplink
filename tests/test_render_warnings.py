"""Tests for archive/utils/render_warnings.py -- the server-side Jinja2
equivalent of shared_static/deep_link.js's linkifyWarning() +
app/static/player.js's renderWarnings() phrase-button behavior, kept in
sync by hand since the Archive renders warnings server-side, not via
client-side JS. Built alongside adding video_warnings/agenda_link
storage to MeetingPage (2026-08-10, see BACKLOG_DONE.md).
"""

from archive.utils.render_warnings import render_warnings_html


def test_escapes_html_metacharacters():
    result = render_warnings_html(["<script>alert(1)</script>"])
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_linkifies_a_bare_url():
    result = render_warnings_html(["We think we found an agenda here: https://example.gov/agenda.pdf"])
    assert '<a href="https://example.gov/agenda.pdf"' in result
    assert 'rel="noopener noreferrer"' in result


def test_wraps_transcribe_phrase_in_a_real_button():
    result = render_warnings_html(["No captions found. You can request a transcript from the audio instead."])
    assert '<button type="button" class="transcribe-inline-trigger">request a transcript from the audio</button>' in result


def test_transcribe_phrase_matching_is_case_insensitive():
    result = render_warnings_html(["Request a Transcript From the Audio if you need one."])
    assert 'class="transcribe-inline-trigger"' in result


def test_multiple_warnings_joined_with_line_break():
    result = render_warnings_html(["First warning.", "Second warning."])
    assert result == "First warning.<br>Second warning."


def test_empty_list_returns_empty_string():
    assert render_warnings_html([]) == ""


def test_escapes_before_linkifying_so_injected_html_cannot_smuggle_a_fake_link():
    # A real safety property, not just a cosmetic detail: if a warning
    # somehow contained raw HTML (it shouldn't, these are server-
    # generated, but escape-then-linkify is the same defense-in-depth
    # order the JS side uses), the injected tag itself must never survive
    # as real markup.
    result = render_warnings_html(['<a href="https://evil.example">click</a> https://real.gov/agenda'])
    assert "<a href=\"https://evil.example\">" not in result
    assert '<a href="https://real.gov/agenda"' in result
