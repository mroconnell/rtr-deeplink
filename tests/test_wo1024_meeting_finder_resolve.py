"""WO-1024: app/platforms/meeting_finder/resolve.py -- YouTube is never
fetched, tier 1/3 selection, and the CalendarPageError widen-the-search
path. Uses monkeypatched adapters (no network) -- these exercise the
Resolve module's own control flow, not any adapter's real parsing (that
stays covered by each adapter's own fixture-backed tests per CLAUDE.md's
synthetic-test rules)."""

import pytest

from app.platforms import meeting_finder as mf
from app.platforms.meeting_finder.models import Candidate, FinderInput
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
async def test_video_gate_rejection_is_not_credited_as_a_meeting(monkeypatch):
    """A resolved video that the shared gate rejects (a promo/decorative
    link) must not be accepted, even with a video_url present."""
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
    assert result.tier is None
    assert result.outcome == mf.models.OUTCOME_NO_MEETING_NOR_VIDEO
