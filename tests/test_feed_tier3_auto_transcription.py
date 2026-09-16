"""Tests for scripts/feed_tier3_auto_transcription.py's queue-line format
extension (BACKLOG_DONE.md, 2026-08-29): a queue line can now optionally
carry a second, tab-separated `source_url` field for the case where the
queued URL is itself a bare video link discovered via a *different* page
-- without this, that video gets ingested under its own URL as
source_url, the same real bug already fixed for direct ingests.

The `_push_if_has_video()` tests below also stub out WO-144's queue probe
(`probe_queue_entry`/`append_probe_row`, wired in right after resolve()
and before ingest) -- these tests are about the source_url-override
behavior specifically, not the probe, and a real probe call would hit
yt-dlp/network for a fake URL that was never resolved against anything
real. tests/test_queue_probe.py covers the probe itself.
"""

import csv
from pathlib import Path

from app.platforms.queue_probe import ProbeResult
from scripts.feed_tier3_auto_transcription import (
    _parse_queue_line,
    _push_if_has_video,
)


async def _accepting_probe_stub(
    url, *, video_url=None, source_page_url=None, platform=None
):
    return ProbeResult(
        url=url,
        platform=platform,
        probe_method="test-stub",
        duration_seconds=1200.0,
        date=None,
        size_bytes=None,
        verdict="accept",
        reason=None,
        probe_seconds=0.01,
        over_nine_minutes=True,
    )


def _noop_append_probe_row(sidecar_path, result):
    pass


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
    monkeypatch.setattr(mod, "probe_queue_entry", _accepting_probe_stub)
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)

    captured = {}

    async def _fake_ingest(
        session, payload, input_url_normalized, *, already_probed=False, caller=""
    ):
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
    monkeypatch.setattr(mod, "probe_queue_entry", _accepting_probe_stub)
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)

    captured = {}

    async def _fake_ingest(
        session, payload, input_url_normalized, *, already_probed=False, caller=""
    ):
        captured["payload"] = payload
        return {"url": "/m/example-page-2"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)

    outcome = await _push_if_has_video(session=None, url=url, source_url_override=None)

    assert "[OK]" in outcome
    assert captured["payload"]["source_url"] == url


async def test_push_if_has_video_skips_a_probe_rejected_dead_link(monkeypatch):
    """WO-144: a resolve that comes back with a video_url the probe finds
    dead (a removed video, an empty HLS playlist, ...) must not reach
    ingest at all."""
    import scripts.feed_tier3_auto_transcription as mod

    url = "https://example.granicus.com/player/clip/999"
    result = _FakeResolvedMeeting(
        video_url="https://example.com/dead.m3u8", source_url=url
    )

    monkeypatch.setattr(mod, "detect_platform", lambda u: "granicus")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder(result))
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)

    async def _rejecting_probe(
        url, *, video_url=None, source_page_url=None, platform=None
    ):
        return ProbeResult(
            url=url,
            platform=platform,
            probe_method="hls-master+variant",
            duration_seconds=None,
            date=None,
            size_bytes=None,
            verdict="reject-dead",
            reason="HLS variant playlist carried zero segments",
            probe_seconds=0.05,
            over_nine_minutes=False,
        )

    monkeypatch.setattr(mod, "probe_queue_entry", _rejecting_probe)

    ingest_called = False

    async def _fake_ingest(
        session, payload, input_url_normalized, *, already_probed=False, caller=""
    ):
        nonlocal ingest_called
        ingest_called = True
        return {"url": "/m/should-not-happen"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)

    outcome = await _push_if_has_video(session=None, url=url, source_url_override=None)

    assert not ingest_called
    assert "[SKIP]" in outcome
    assert "reject-dead" in outcome
    assert "zero segments" in outcome


async def test_push_if_has_video_refuses_to_ingest_a_line_with_no_owner(monkeypatch):
    """WO-346: a MULTI_GOV_HOSTS host with no tenant_overrides.csv pin
    matching this page must never reach ingest -- it would land on
    `rtr:unknown:{host}`, the exact gap the tier-3 queue ownership audit
    found sitting unrecorded across 478 of 3,012 queue+deferred lines."""
    import scripts.feed_tier3_auto_transcription as mod

    url = "https://www.youtube.com/watch?v=zzzzzzzzzzz"
    result = _FakeResolvedMeeting(
        video_url="https://www.youtube.com/embed/zzzzzzzzzzz", source_url=url
    )

    monkeypatch.setattr(mod, "detect_platform", lambda u: "youtube")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder(result))
    monkeypatch.setattr(mod, "probe_queue_entry", _accepting_probe_stub)
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)
    monkeypatch.setattr(
        mod,
        "has_owner",
        lambda source_url: (False, None, f"{source_url} has no owner"),
    )

    ingest_called = False

    async def _fake_ingest(
        session, payload, input_url_normalized, *, already_probed=False, caller=""
    ):
        nonlocal ingest_called
        ingest_called = True
        return {"url": "/m/should-not-happen"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)

    outcome = await _push_if_has_video(session=None, url=url, source_url_override=None)

    assert not ingest_called
    assert outcome.startswith("[NO-OWNER]")
    assert "has no owner" in outcome


async def test_push_if_has_video_ingests_normally_when_owned(monkeypatch):
    """The guard is a refusal, not a new requirement -- an owned line
    (has_owner() True) still ingests exactly as before."""
    import scripts.feed_tier3_auto_transcription as mod

    url = "https://example.granicus.com/player/clip/42"
    result = _FakeResolvedMeeting(
        video_url="https://example.com/v.m3u8", source_url=url
    )

    monkeypatch.setattr(mod, "detect_platform", lambda u: "granicus")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder(result))
    monkeypatch.setattr(mod, "probe_queue_entry", _accepting_probe_stub)
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)
    monkeypatch.setattr(mod, "has_owner", lambda source_url: (True, None, ""))

    captured = {}

    async def _fake_ingest(
        session, payload, input_url_normalized, *, already_probed=False, caller=""
    ):
        captured["payload"] = payload
        return {"url": "/m/example-page-3"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)

    outcome = await _push_if_has_video(session=None, url=url, source_url_override=None)

    assert "[OK]" in outcome
    assert "gov_id" not in captured["payload"]


async def test_push_if_has_video_sends_the_pins_gov_id_straight_through(monkeypatch):
    """WO-346: when has_owner() found the gov_id from a tenant_overrides.csv
    pin, it rides straight into the ingest payload (CLAUDE.md's "send the
    government's id in every ingest payload" rule) rather than depending
    on the Archive service's own deployed pins being up to date."""
    import scripts.feed_tier3_auto_transcription as mod

    url = "https://www.youtube.com/watch?v=pinnedvideo1"
    result = _FakeResolvedMeeting(
        video_url="https://www.youtube.com/embed/pinnedvideo1", source_url=url
    )

    monkeypatch.setattr(mod, "detect_platform", lambda u: "youtube")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder(result))
    monkeypatch.setattr(mod, "probe_queue_entry", _accepting_probe_stub)
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)
    monkeypatch.setattr(
        mod, "has_owner", lambda source_url: (True, "us:place:0000009", "")
    )

    captured = {}

    async def _fake_ingest(
        session, payload, input_url_normalized, *, already_probed=False, caller=""
    ):
        captured["payload"] = payload
        return {"url": "/m/example-page-4"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)

    outcome = await _push_if_has_video(session=None, url=url, source_url_override=None)

    assert "[OK]" in outcome
    assert captured["payload"]["gov_id"] == "us:place:0000009"


async def test_lmc_pending_lines_keep_exact_owner_through_feeder(monkeypatch):
    """The LMC producer page is evidence, not a source-url override:
    the feeder must check each Swagit video's own pin before ingest."""
    import scripts.feed_tier3_auto_transcription as mod

    pending = (
        Path(__file__).parent.parent
        / "reports"
        / "yesgov_694_pending_queue_2026-09-15.csv"
    )
    with pending.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2

    monkeypatch.setattr(mod, "detect_platform", lambda url: "swagit")
    monkeypatch.setattr(mod, "probe_queue_entry", _accepting_probe_stub)
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)

    for row in rows:
        url, override = _parse_queue_line(row["queue_line"])
        assert url == row["meeting_url"]
        assert override is None
        assert row["first_party_evidence_url"].startswith("https://lmcmedia.org/")

        result = _FakeResolvedMeeting(
            video_url="https://archive-stream.granicus.com/test.m3u8",
            source_url=url,
        )
        monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder(result))
        captured = {}

        async def _fake_ingest(
            session, payload, input_url_normalized, *, already_probed=False, caller=""
        ):
            captured["payload"] = payload
            return {"url": "/m/exact-lmc-owner"}

        monkeypatch.setattr(mod, "_ingest", _fake_ingest)
        outcome = await _push_if_has_video(
            session=None, url=url, source_url_override=override
        )
        assert outcome.startswith("[OK]")
        assert captured["payload"]["source_url"] == url
        assert captured["payload"]["gov_id"] == row["gov_id"]

    assert mod.has_owner("https://lmctvny.new.swagit.com/videos/999999")[0] is False
