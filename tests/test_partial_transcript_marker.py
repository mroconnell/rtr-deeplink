"""WO-923: a transcript that covers only part of the video gets a reader warning.

Measured on the real Rhode Island Senate page (Capitol TV, Cablecast,
2026-06-10): cues run to about 81 minutes; the video's own HLS playlist
sums to about 149 minutes (ratio 0.545). The tests below build small
ResolvedMeeting objects at the real measured ratios -- 0.545 (Rhode Island
Senate), 0.9598 and 0.962 (two real Swagit meetings, the closest real
"normal" cases above the line) -- so the threshold is exercised at values
that actually occurred. The durations and cue times are synthetic
scaffolding around those ratios.
"""

import pytest

from app.platforms import base
from app.platforms.coverage_check import (
    PARTIAL_TRANSCRIPT_MARKER,
    flag_partial_transcript,
    looks_partial,
    partial_transcript_warning,
)
from app.platforms.models import ResolvedMeeting, TranscriptSegment
from archive.db import crud


@pytest.fixture(autouse=True)
def _check_on(monkeypatch):
    # tests/conftest.py switches the check off suite-wide; this file
    # tests it, so it is on here.
    monkeypatch.setenv("RTR_PARTIAL_TRANSCRIPT_CHECK", "1")


def _meeting(last_cue_s, *, duration=None, fmt="m3u8", warnings=None):
    return ResolvedMeeting(
        platform="cablecast",
        source_url="https://example.cablecast.tv/show/1",
        video_url="https://example.cablecast.tv/vod/1/vod.m3u8",
        video_format=fmt,
        video_duration_seconds=duration,
        segments=[
            TranscriptSegment(start=20.0, end=40.0, text="Called to order."),
            TranscriptSegment(start=last_cue_s - 5, end=last_cue_s, text="Last words."),
        ],
        transcript_warnings=list(warnings or []),
    )


def _probe_returning(seconds):
    calls = []

    async def probe(media_url, source_url):
        calls.append(media_url)
        return seconds

    probe.calls = calls
    return probe


def test_resolver_marker_matches_the_archive_marker():
    # The resolver cannot import archive/, so the substring is copied.
    # If these ever differ, a warning added here would stop counting as
    # "not a good transcript" in the Archive.
    assert PARTIAL_TRANSCRIPT_MARKER == crud._EARLY_TRUNCATION_MARKER


def test_warning_carries_the_marker_and_plain_numbers():
    text = partial_transcript_warning(4888.0, 8967.0)
    assert PARTIAL_TRANSCRIPT_MARKER in text
    assert "1 hour 21 minutes" in text
    assert "2 hour 29 minute recording" in text
    assert "stop early at the source" in text


def test_the_warning_makes_the_archive_treat_it_as_truncated():
    warnings = [partial_transcript_warning(4888.0, 8967.0)]
    assert not crud._has_real_warning_free_transcript(warnings)
    assert (
        crud._classify_page_outcome(
            video_url="https://example.com/v.m3u8",
            agenda_items=[],
            default_content_hash="x",
            default_transcript_warnings=warnings,
            default_transcript_language="en",
        )
        == "truncated_transcript"
    )


@pytest.mark.parametrize(
    "last, duration, expected",
    [
        (4888.0, 8967.5, True),  # Rhode Island Senate, ratio 0.545
        (8967.5 * 0.97, 8967.5, False),  # 97%: real meetings end before the tail
        (0.9598 * 4692.0, 4692.0, False),  # real Swagit case, 3 min gap
        (900.0, 3600.0, True),  # 25%
        (54.0, 66.0, False),  # short clip, 82% but only a 12 second gap
        (25200.0, 25560.0, False),  # 7 hour meeting, 98.6%, 6 minute gap
        (14400.0, 20000.0, True),  # 72%, 93 minute gap
        (3000.0, 3300.0, False),  # 90.9%, 5 minute gap: above the ratio line
    ],
)
def test_threshold_needs_both_a_low_ratio_and_a_ten_minute_gap(
    last, duration, expected
):
    assert looks_partial(last, duration) is expected


def test_unknown_or_implausible_duration_never_flags():
    assert looks_partial(1000.0, None) is False
    assert looks_partial(1000.0, 0.0) is False
    assert looks_partial(0.0, 5000.0) is False
    assert looks_partial(10.0, 30.0 * 3600) is False  # over the 14 hour ceiling


async def test_last_cue_at_45_percent_gets_the_warning():
    result = await flag_partial_transcript(_meeting(4500.0, duration=10000.0))
    assert any(PARTIAL_TRANSCRIPT_MARKER in w for w in result.transcript_warnings)


async def test_last_cue_at_97_percent_gets_no_warning():
    result = await flag_partial_transcript(_meeting(9700.0, duration=10000.0))
    assert result.transcript_warnings == []


async def test_unknown_duration_and_no_probe_answer_gets_no_warning():
    probe = _probe_returning(None)
    result = await flag_partial_transcript(_meeting(4500.0), probe=probe)
    assert result.transcript_warnings == []
    assert result.video_duration_seconds is None  # never hand-filled
    assert probe.calls  # it did try


async def test_probed_duration_is_used_and_recorded():
    probe = _probe_returning(10000.0)
    result = await flag_partial_transcript(_meeting(4500.0), probe=probe)
    assert any(PARTIAL_TRANSCRIPT_MARKER in w for w in result.transcript_warnings)
    assert result.video_duration_seconds == 10000.0


@pytest.mark.parametrize("fmt", ["youtube", "vimeo", "viebit", None])
async def test_iframe_formats_are_never_probed(fmt):
    probe = _probe_returning(10000.0)
    result = await flag_partial_transcript(_meeting(4500.0, fmt=fmt), probe=probe)
    assert result.transcript_warnings == []
    assert probe.calls == []


async def test_no_cues_means_no_probe_and_no_warning():
    probe = _probe_returning(10000.0)
    meeting = _meeting(4500.0)
    meeting.segments = []
    result = await flag_partial_transcript(meeting, probe=probe)
    assert result.transcript_warnings == []
    assert probe.calls == []


async def test_check_is_idempotent():
    meeting = _meeting(4500.0, duration=10000.0)
    once = await flag_partial_transcript(meeting)
    twice = await flag_partial_transcript(once)
    assert len(twice.transcript_warnings) == 1


async def test_a_failing_probe_never_breaks_a_resolve():
    async def boom(media_url, source_url):
        raise RuntimeError("ffprobe exploded")

    result = await flag_partial_transcript(_meeting(4500.0), probe=boom)
    assert result.transcript_warnings == []


async def test_registered_finders_run_the_check(monkeypatch):
    monkeypatch.setenv("RTR_PARTIAL_TRANSCRIPT_CHECK", "1")

    class Fake(base.AssetFinder):
        platform_name = "wo923_fake"

        async def resolve(self, url):
            return _meeting(4500.0, duration=10000.0)

    monkeypatch.setattr(base, "_REGISTRY", {})
    base.register(Fake())
    result = await base.get_finder("wo923_fake").resolve("https://x.example/1")
    assert any(PARTIAL_TRANSCRIPT_MARKER in w for w in result.transcript_warnings)


async def test_the_switch_turns_the_check_off(monkeypatch):
    monkeypatch.setenv("RTR_PARTIAL_TRANSCRIPT_CHECK", "0")
    result = await flag_partial_transcript(_meeting(4500.0, duration=10000.0))
    assert result.transcript_warnings == []


async def test_re_pushing_identical_cues_attaches_the_new_warning():
    """The Rhode Island Senate case: the page already holds these exact
    cues, so a fresh resolve used to dedupe to the old version and drop
    the warning."""
    url = "https://wo923.cablecast.tv/show/ri-senate"
    payload = {
        "platform": "cablecast",
        "source_url": url,
        "external_id": "cablecast:wo923.cablecast.tv:1",
        "title": "Senate",
        "date": "2026-06-10",
        "jurisdiction": "State of Rhode Island",
        "video_url": "https://wo923.cablecast.tv/vod/1/vod.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 4500, "text": "words words words"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, url)
    slug = (await crud.lookup_page_for_url(url))["slug"]
    assert await _default_warnings(slug) == []

    warning = partial_transcript_warning(4500.0, 8967.0)
    await crud.ingest_resolution({**payload, "transcript_warnings": [warning]}, url)
    assert await _default_warnings(slug) == [warning]
    # Pushed again: still exactly one copy.
    await crud.ingest_resolution({**payload, "transcript_warnings": [warning]}, url)
    assert await _default_warnings(slug) == [warning]


async def test_warning_reaches_the_shown_version_when_the_cue_text_changed():
    """WO-925, the Edina MN case (page 3645). The stored captions were
    ingested before a later adapter change; a fresh resolve of the same
    source returns the same cues with different text, so the content hash
    differs, no duplicate is found, and a NEW non-default version carried
    the warning while the page kept rendering the old default without it.
    The warning describes the source captions, not a text variant, so it
    must land on the default version too when both end at the same time."""
    url = "https://wo925a.cablecast.tv/show/3562"
    payload = {
        "platform": "cablecast",
        "source_url": url,
        "external_id": "cablecast:wo925a.cablecast.tv:3562",
        "title": "School Board",
        "date": "2026-03-11",
        "jurisdiction": "State of Rhode Island",
        "video_url": "https://wo925a.cablecast.tv/vod/1/vod.m3u8",
        "video_format": "m3u8",
        "segments": [
            {"start": 0, "end": 2000, "text": "S1:"},
            {"start": 2000, "end": 4105, "text": "Motion carries"},
        ],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, url)
    slug = (await crud.lookup_page_for_url(url))["slug"]

    warning = partial_transcript_warning(4105.0, 4775.0 * 2)
    changed = {
        **payload,
        "segments": [
            {"start": 0, "end": 2000, "text": "Order of business is agenda approval."},
            {"start": 2000, "end": 4105, "text": "Motion carries"},
        ],
        "transcript_warnings": [warning],
    }
    await crud.ingest_resolution(changed, url)
    assert await _default_warnings(slug) == [warning]


async def test_warning_is_not_copied_onto_a_default_that_ends_elsewhere():
    """Guard for the fix above: a default whose captions end at a clearly
    different time is a different recording, so it is not marked."""
    url = "https://wo925b.cablecast.tv/show/1"
    payload = {
        "platform": "cablecast",
        "source_url": url,
        "external_id": "cablecast:wo925b.cablecast.tv:1",
        "title": "Board",
        "date": "2026-03-11",
        "jurisdiction": "State of Rhode Island",
        "video_url": "https://wo925b.cablecast.tv/vod/1/vod.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 9000, "text": "long stored text"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    await crud.ingest_resolution(payload, url)
    slug = (await crud.lookup_page_for_url(url))["slug"]
    warning = partial_transcript_warning(4105.0, 20000.0)
    await crud.ingest_resolution(
        {
            **payload,
            "segments": [{"start": 0, "end": 4105, "text": "short fresh text"}],
            "transcript_warnings": [warning],
        },
        url,
    )
    assert await _default_warnings(slug) == []


def _edina_fixture():
    import json
    from pathlib import Path

    path = (
        Path(__file__).parent
        / "fixtures"
        / "cablecast"
        / "wo926_edina_3562_stored_vs_fresh.json"
    )
    return json.loads(path.read_text())


def _edina_payload(url, segments, warnings):
    return {
        "platform": "cablecast",
        "source_url": url,
        "external_id": "cablecast:" + url.split("//")[1].replace("/show/", ":"),
        "title": "School Board",
        "date": "2026-03-11",
        "jurisdiction": "State of Rhode Island",
        "video_url": url.split("/show/")[0] + "/vod/1/vod.m3u8",
        "video_format": "m3u8",
        "segments": segments,
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": warnings,
    }


async def _clear_default_warnings(slug):
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion
    from sqlalchemy import select

    async with async_session() as session:
        version = (
            await session.execute(
                select(TranscriptVersion)
                .join(MeetingPage, MeetingPage.id == TranscriptVersion.meeting_page_id)
                .where(MeetingPage.slug == slug, TranscriptVersion.is_default.is_(True))
            )
        ).scalar_one()
        version.transcript_warnings = []
        await session.commit()


async def test_warning_reaches_the_shown_version_on_a_repeat_push_of_the_fresh_text():
    """WO-926, the real Edina MN page (3645) after WO-925 shipped. The
    fresh text had already been stored as a hidden second version (pushed
    before the WO-925 fix was live), so every later re-check pushed that
    same text again, matched the hidden version as an identical duplicate,
    and never offered the warning to the shown version. Cues below are the
    real ones (trimmed): the shown version holds speaker labels only, the
    hidden one real text, identical timing, last cue ends at 4105.47 s."""
    fx = _edina_fixture()
    url = "https://wo926a.cablecast.tv/show/3562"
    warning = partial_transcript_warning(4105.47, 4800.0 * 2)
    await crud.ingest_resolution(_edina_payload(url, fx["stored"], []), url)
    slug = (await crud.lookup_page_for_url(url))["slug"]
    fresh = _edina_payload(url, fx["fresh"], [warning])
    await crud.ingest_resolution(fresh, url)
    # Reproduce the live state: the hidden version exists, the shown one
    # never got the marker (the first push ran before the WO-925 code).
    await _clear_default_warnings(slug)
    assert await _default_warnings(slug) == []

    await crud.ingest_resolution(fresh, url)  # identical to the hidden version
    assert await _default_warnings(slug) == [warning]
    # A third push adds nothing more.
    await crud.ingest_resolution(fresh, url)
    assert await _default_warnings(slug) == [warning]


async def test_repeat_push_does_not_mark_a_shown_version_that_is_really_complete():
    """Guard for the WO-926 fix: a shown version whose last cue is near the
    real end of a long meeting must NOT be marked by a shorter fresh resolve
    (a different, shorter caption set), even when that fresh text is
    already stored as a hidden duplicate."""
    fx = _edina_fixture()
    url = "https://wo926b.cablecast.tv/show/1"
    warning = partial_transcript_warning(4105.47, 4800.0 * 2)
    full = [dict(c) for c in fx["stored"]]
    full[-1] = {"start": 9000.0, "end": 9500.0, "text": "Adjourned."}
    await crud.ingest_resolution(_edina_payload(url, full, []), url)
    slug = (await crud.lookup_page_for_url(url))["slug"]
    fresh = _edina_payload(url, fx["fresh"], [warning])
    await crud.ingest_resolution(fresh, url)
    await crud.ingest_resolution(fresh, url)  # identical to the hidden version
    assert await _default_warnings(slug) == []


async def _default_warnings(slug):
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion
    from sqlalchemy import select

    async with async_session() as session:
        return (
            await session.execute(
                select(TranscriptVersion.transcript_warnings)
                .join(MeetingPage, MeetingPage.id == TranscriptVersion.meeting_page_id)
                .where(MeetingPage.slug == slug, TranscriptVersion.is_default.is_(True))
            )
        ).scalar_one()
