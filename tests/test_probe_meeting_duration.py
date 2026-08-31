"""Tests for app/main.py's _probe_meeting_duration() (WO-79) -- the shared
helper behind /api/transcription/check-feasibility and /api/transcription/
submit that reports a meeting's real WHOLE duration and a per-clip chunk
plan for a multi-clip Swagit meeting (result.video_segments, see
swagit.py), instead of just probing the first clip alone.
"""

import app.main as app_main
from app.platforms.models import ResolvedMeeting, VideoSegment


async def test_ordinary_single_video_meeting_is_unchanged(monkeypatch):
    """0 video_segments -- every non-Swagit platform, and an ordinary
    single-video Swagit meeting -- must behave exactly as
    probe_duration(result.video_url) always did."""
    result = ResolvedMeeting(
        platform="granicus",
        source_url="https://city.granicus.com/player/clip/1",
        video_url="https://example.org/meeting.m3u8",
        video_format="m3u8",
    )

    async def _probe(video_url, *, source_page_url):
        assert video_url == "https://example.org/meeting.m3u8"
        return 3600.0

    monkeypatch.setattr(app_main, "probe_duration", _probe)

    duration, chunk_plan = await app_main._probe_meeting_duration(
        result, source_page_url="https://city.granicus.com/player/clip/1"
    )
    assert duration == 3600.0
    assert chunk_plan is None


async def test_no_video_url_returns_none_without_probing(monkeypatch):
    result = ResolvedMeeting(
        platform="unknown", source_url="https://example.org/meeting", video_url=None
    )

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("must not probe when there's no video_url")

    monkeypatch.setattr(app_main, "probe_duration", _fail_if_called)

    duration, chunk_plan = await app_main._probe_meeting_duration(
        result, source_page_url="https://example.org/meeting"
    )
    assert (duration, chunk_plan) == (None, None)


async def test_multi_clip_meeting_reports_the_real_summed_total(monkeypatch):
    """A meeting with more than one video_segment must report the real
    WHOLE-meeting duration (sum of every clip) and a real chunk plan, not
    just the first clip's own duration."""
    result = ResolvedMeeting(
        platform="swagit",
        source_url="https://yolocountyca.new.swagit.com/videos/324107",
        video_url="https://x/a.m3u8",
        video_format="m3u8",
        video_segments=[
            VideoSegment(url="https://x/a.m3u8", seq=6, title="First"),
            VideoSegment(url="https://x/b.m3u8", seq=13, title="Second"),
        ],
    )

    async def _plan(video_segments, *, source_page_url):
        return [
            {
                "media_url": "https://x/a.m3u8",
                "start": 0.0,
                "duration": 120.0,
                "title": "First",
                "seq": 6,
            },
            {
                "media_url": "https://x/b.m3u8",
                "start": 120.0,
                "duration": 300.0,
                "title": "Second",
                "seq": 13,
            },
        ]

    monkeypatch.setattr(app_main, "probe_multi_clip_chunk_plan", _plan)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "a successful multi-clip plan must skip the single-clip probe_duration()"
        )

    monkeypatch.setattr(app_main, "probe_duration", _fail_if_called)

    duration, chunk_plan = await app_main._probe_meeting_duration(
        result, source_page_url="https://yolocountyca.new.swagit.com/videos/324107"
    )
    assert duration == 420.0  # 120 + 300, not just the first clip's 120
    assert chunk_plan[1]["start"] == 120.0


async def test_multi_clip_plan_failure_falls_back_to_first_clip_probe(monkeypatch):
    """probe_multi_clip_chunk_plan() is all-or-nothing -- a None result
    (one clip failed to probe) must fall back to the ordinary single-clip
    path, not turn an otherwise-transcribable meeting into a hard
    failure."""
    result = ResolvedMeeting(
        platform="swagit",
        source_url="https://yolocountyca.new.swagit.com/videos/324107",
        video_url="https://x/a.m3u8",
        video_format="m3u8",
        video_segments=[
            VideoSegment(url="https://x/a.m3u8", seq=6),
            VideoSegment(url="https://x/b.m3u8", seq=13),
        ],
    )

    async def _plan(video_segments, *, source_page_url):
        return None

    monkeypatch.setattr(app_main, "probe_multi_clip_chunk_plan", _plan)

    async def _probe(video_url, *, source_page_url):
        assert video_url == "https://x/a.m3u8"
        return 120.0

    monkeypatch.setattr(app_main, "probe_duration", _probe)

    duration, chunk_plan = await app_main._probe_meeting_duration(
        result, source_page_url="https://yolocountyca.new.swagit.com/videos/324107"
    )
    assert (duration, chunk_plan) == (120.0, None)
