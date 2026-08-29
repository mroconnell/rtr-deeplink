"""Tests for scripts/feed_tier3_auto_transcription.py's queue-line format
extension (BACKLOG_DONE.md, 2026-08-29): a queue line can now optionally
carry a second, tab-separated `source_url` field for the case where the
queued URL is itself a bare video link discovered via a *different* page
-- without this, that video gets ingested under its own URL as
source_url, the same real bug already fixed for direct ingests.
"""

from scripts.feed_tier3_auto_transcription import (
    _parse_queue_line,
    _push_if_has_video,
)


def test_parse_queue_line_bare_url_has_no_override():
    assert _parse_queue_line("https://example.com/videos/1") == (
        "https://example.com/videos/1",
        None,
    )


def test_parse_queue_line_splits_on_tab():
    line = "https://youtube.com/watch?v=abc123\thttps://example.gov/agenda/42"
    assert _parse_queue_line(line) == (
        "https://youtube.com/watch?v=abc123",
        "https://example.gov/agenda/42",
    )


def test_parse_queue_line_trims_whitespace_around_both_fields():
    line = "  https://youtube.com/watch?v=abc123  \t  https://example.gov/agenda/42  "
    assert _parse_queue_line(line) == (
        "https://youtube.com/watch?v=abc123",
        "https://example.gov/agenda/42",
    )


def test_parse_queue_line_trailing_tab_with_no_second_field_has_no_override():
    assert _parse_queue_line("https://example.com/videos/1\t") == (
        "https://example.com/videos/1",
        None,
    )


class _FakeResolvedMeeting:
    def __init__(self, video_url, source_url):
        self.video_url = video_url
        self.source_url = source_url

    def model_dump(self):
        return {"video_url": self.video_url, "source_url": self.source_url}


class _FakeFinder:
    def __init__(self, result):
        self._result = result

    async def resolve(self, url):
        return self._result


async def test_push_if_has_video_overrides_source_url_when_given(monkeypatch):
    import scripts.feed_tier3_auto_transcription as mod

    bare_video_url = "https://youtube.com/watch?v=abc123"
    real_source_url = "https://example.gov/agenda/42"
    result = _FakeResolvedMeeting(
        video_url="https://youtube.com/embed/abc123", source_url=bare_video_url
    )

    monkeypatch.setattr(mod, "detect_platform", lambda url: "youtube")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder(result))

    captured = {}

    async def _fake_ingest(session, payload, input_url_normalized):
        captured["payload"] = payload
        return {"url": "/m/example-page"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)

    outcome = await _push_if_has_video(
        session=None, url=bare_video_url, source_url_override=real_source_url
    )

    assert "[OK]" in outcome
    assert captured["payload"]["source_url"] == real_source_url


async def test_push_if_has_video_leaves_source_url_alone_without_an_override(
    monkeypatch,
):
    import scripts.feed_tier3_auto_transcription as mod

    url = "https://example.granicus.com/player/clip/123"
    result = _FakeResolvedMeeting(
        video_url="https://example.com/v.m3u8", source_url=url
    )

    monkeypatch.setattr(mod, "detect_platform", lambda u: "granicus")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder(result))

    captured = {}

    async def _fake_ingest(session, payload, input_url_normalized):
        captured["payload"] = payload
        return {"url": "/m/example-page-2"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)

    outcome = await _push_if_has_video(session=None, url=url, source_url_override=None)

    assert "[OK]" in outcome
    assert captured["payload"]["source_url"] == url
