"""WO-1024: app/platforms/meeting_finder/resolve.py -- YouTube is never
fetched, tier 1/3 selection, and the CalendarPageError widen-the-search
path. Uses monkeypatched adapters (no network) -- these exercise the
Resolve module's own control flow, not any adapter's real parsing (that
stays covered by each adapter's own fixture-backed tests per CLAUDE.md's
synthetic-test rules)."""

import pytest

from app.platforms.meeting_finder.models import (
    OUTCOME_VIDEO_LOW_CONFIDENCE,
    Candidate,
    FinderInput,
)
from app.platforms.meeting_finder.resolve import resolve_candidates
from app.platforms.models import ResolvedMeeting


def _finder_input(url: str, **overrides) -> FinderInput:
    fields = dict(url=url, gov_id=None, mode="pin", entry="resolve")
    fields.update(overrides)
    return FinderInput(**fields)


@pytest.mark.asyncio
async def test_youtube_candidate_is_never_resolved(monkeypatch):
    """A youtube.com candidate must become a tier-2 lead without ever
    calling YouTubeAssetFinder.resolve()."""
    from app.platforms.youtube import YouTubeAssetFinder

    async def _boom(self, url):
        raise AssertionError(f"YouTubeAssetFinder.resolve() was called for {url}")

    monkeypatch.setattr(YouTubeAssetFinder, "resolve", _boom)

    candidates = [
        Candidate(
            url="https://www.youtube.com/watch?v=abc123",
            date="2026-09-08",
            title="City Council Meeting",
        )
    ]
    result = await resolve_candidates(candidates, _finder_input(candidates[0].url))
    assert result.tier == 2
    assert result.outcome is None
    assert result.video_url == "https://www.youtube.com/watch?v=abc123"


@pytest.mark.asyncio
async def test_internal_youtube_delegation_becomes_a_lead_not_a_fetch(monkeypatch):
    """A candidate that is NOT itself a youtube.com URL but whose resolve
    delegates internally to YouTube (e.g. a PrimeGov/CivicPlus embed) must
    also become a tier-2 lead, never a real yt-dlp fetch -- this is what
    `resolve_via_platform(allow_youtube=False)`'s `YouTubeResolveBlocked`
    exists for."""

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        from app.platforms.base import YouTubeResolveBlocked

        raise YouTubeResolveBlocked("https://www.youtube.com/watch?v=delegated")

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )

    candidates = [
        Candidate(
            url="https://cityx.civicplus.com/meeting/1",
            date="2026-09-08",
            title="City Council Meeting",
        )
    ]
    result = await resolve_candidates(candidates, _finder_input(candidates[0].url))
    assert result.tier == 2
    assert result.outcome is None


@pytest.mark.asyncio
async def test_tier1_returned_immediately_when_segments_present(monkeypatch):
    from app.utils.video_hand_check import GateVerdict, PASS

    meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://x.portal.civicclerk.com/event/1/media",
        jurisdiction="Fresno, CA",
        title="City Council Meeting",
        video_url="https://x.portal.civicclerk.com/media/1.mp4",
        segments=[{"start": 0, "end": 1, "text": "hello"}],
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(PASS, "ok"),
    )

    async def _audio_ok(url):
        return True

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [
        Candidate(
            url=meeting.source_url, date="2026-09-08", title="City Council Meeting"
        )
    ]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))
    assert result.tier == 1
    assert result.has_segments is True
    assert result.platform == "civicclerk"


@pytest.mark.asyncio
async def test_video_gate_rejection_is_kept_as_a_last_resort(monkeypatch):
    """WO-1035 (Ryan's rule): a resolved video the shared gate rejects (a
    promo/decorative link) is no longer thrown away outright -- with
    nothing else to try, it's kept as a last-resort find (never a clean
    tier-1/tier-3 pick, and always distinguishable via
    `low_confidence_reason`), rather than reporting "no meeting" while a
    real video URL sits right there."""
    from app.utils.video_hand_check import GateVerdict, REJECT

    meeting = ResolvedMeeting(
        platform="civicplus",
        source_url="https://cityx.civicplus.com/promo",
        title="Ribbon cutting ceremony",
        video_url="https://cityx.civicplus.com/promo.mp4",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(REJECT, "promo_blocklist"),
    )

    candidates = [
        Candidate(
            url=meeting.source_url, date="2026-09-08", title="City Council Meeting"
        )
    ]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))
    # WO-1035 follow-up (conductor live check, 2026-09-23): this must NOT
    # look like a clean success -- a bare `outcome is None` here is
    # exactly the bug that let a homepage banner .mp4 stop a whole
    # government's walk (champaignil.gov) before it ever reached the real
    # meeting account.
    assert result.outcome == OUTCOME_VIDEO_LOW_CONFIDENCE
    assert result.candidate is not None
    assert result.video_url == meeting.video_url
    assert result.low_confidence_reason
    assert "kept despite" in result.note


@pytest.mark.asyncio
async def test_too_short_video_is_kept_as_a_last_resort(monkeypatch):
    """WO-1035: a probed video below the 60s meeting-plausibility floor is
    kept as a last-resort find (not silently dropped)."""
    from app.utils.video_hand_check import PASS, GateVerdict
    from app.platforms import queue_probe

    meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://x.portal.civicclerk.com/event/1/media",
        title="City Council Meeting",
        video_url="https://x.portal.civicclerk.com/media/1.mp4",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="civicclerk",
            probe_method="ffprobe",
            duration_seconds=12.0,
            date=None,
            size_bytes=None,
            verdict="reject-short",
            reason="duration 12.0s is below the 60s meeting-plausibility floor",
            probe_seconds=0.1,
        )

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(PASS, "ok"),
    )
    monkeypatch.setattr(queue_probe, "probe_queue_entry", _fake_probe)

    async def _audio_ok(url):
        return True

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [
        Candidate(
            url=meeting.source_url, date="2026-09-08", title="City Council Meeting"
        )
    ]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))
    assert result.outcome == OUTCOME_VIDEO_LOW_CONFIDENCE
    assert result.video_url == meeting.video_url
    assert result.duration_seconds == 12.0
    assert "too short" in result.low_confidence_reason


@pytest.mark.asyncio
async def test_unmeasurable_video_is_kept_last_after_a_known_length_one(monkeypatch):
    """WO-1035: "a video whose length can't be measured is kept as 'video,
    length unknown', tried after measured ones" -- given both a too-short
    (known duration) candidate and an unmeasurable one, the known-duration
    one wins."""
    from app.utils.video_hand_check import PASS, GateVerdict
    from app.platforms import queue_probe

    short_meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://x.portal.civicclerk.com/event/1/media",
        title="City Council Meeting",
        video_url="https://x.portal.civicclerk.com/media/1.mp4",
    )
    unmeasurable_meeting = ResolvedMeeting(
        platform="viebit",
        source_url="https://x.viebit.com/event/2/media",
        title="City Council Meeting",
        video_url="https://x.viebit.com/media/2.m3u8",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return unmeasurable_meeting if "viebit" in url else short_meeting

    async def _fake_probe(url, **kwargs):
        if "viebit" in url:
            return queue_probe.ProbeResult(
                url=url,
                platform="viebit",
                probe_method="ffprobe",
                duration_seconds=None,
                date=None,
                size_bytes=None,
                verdict="reject-dead",
                reason="ffprobe couldn't read the media",
                probe_seconds=0.1,
            )
        return queue_probe.ProbeResult(
            url=url,
            platform="civicclerk",
            probe_method="ffprobe",
            duration_seconds=12.0,
            date=None,
            size_bytes=None,
            verdict="reject-short",
            reason="duration 12.0s is below the 60s meeting-plausibility floor",
            probe_seconds=0.1,
        )

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(PASS, "ok"),
    )
    monkeypatch.setattr(queue_probe, "probe_queue_entry", _fake_probe)

    async def _audio_ok(url):
        return True

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_ok
    )

    candidates = [
        Candidate(
            url=unmeasurable_meeting.source_url,
            date="2026-09-09",
            title="City Council Meeting",
        ),
        Candidate(
            url=short_meeting.source_url,
            date="2026-09-08",
            title="City Council Meeting",
        ),
    ]
    result = await resolve_candidates(
        candidates, _finder_input(unmeasurable_meeting.source_url), max_tries=6
    )
    assert result.outcome == OUTCOME_VIDEO_LOW_CONFIDENCE
    # The known-duration (too-short) candidate wins over the unmeasurable
    # one, even though the unmeasurable one was listed first (newer date).
    assert result.video_url == short_meeting.video_url
    assert "too short" in result.low_confidence_reason


@pytest.mark.asyncio
async def test_audio_only_video_counts_as_a_real_find(monkeypatch):
    """WO-1035 item 3: audio-only recordings are GOOD -- they count as
    finds, labelled "audio only", not rejected."""
    from app.utils.video_hand_check import PASS, GateVerdict
    from app.platforms import queue_probe

    meeting = ResolvedMeeting(
        platform="civicclerk",
        source_url="https://x.portal.civicclerk.com/event/1/media",
        title="City Council Meeting",
        video_url="https://x.portal.civicclerk.com/media/1.mp3",
    )

    async def _fake_resolve_via_platform(url, *, allow_youtube=True):
        return meeting

    async def _fake_probe(*args, **kwargs):
        return queue_probe.ProbeResult(
            url=meeting.source_url,
            platform="civicclerk",
            probe_method="ffprobe",
            duration_seconds=1800.0,
            date=None,
            size_bytes=None,
            verdict="accept",
            reason=None,
            probe_seconds=0.1,
        )

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.resolve_via_platform",
        _fake_resolve_via_platform,
    )
    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve.assess_video_candidate",
        lambda **kwargs: GateVerdict(PASS, "ok"),
    )
    monkeypatch.setattr(queue_probe, "probe_queue_entry", _fake_probe)

    async def _audio_only(url):
        return False  # "not confirmed as audio-only" == False means IS audio-only

    monkeypatch.setattr(
        "app.platforms.meeting_finder.resolve._confirm_not_audio_only", _audio_only
    )

    candidates = [
        Candidate(
            url=meeting.source_url, date="2026-09-08", title="City Council Meeting"
        )
    ]
    result = await resolve_candidates(candidates, _finder_input(meeting.source_url))
    assert result.outcome is None
    assert result.tier == 3
    assert result.audio_only is True
    assert "audio only" in result.note
