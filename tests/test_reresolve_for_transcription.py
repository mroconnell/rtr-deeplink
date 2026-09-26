"""Tests for app/platforms/reresolve.py's `reresolve_for_transcription()`
(WO-1073) -- the shared video_url fallback used by all three real
transcription re-resolve callers (worker/main.py, scripts/bulk_queue_
transcription_backlog.py, scripts/transcribe_backlog_locally.py) when a
page's stored `source_url_normalized` can no longer be re-resolved by its
own platform adapter, but its stored `video_url` still can be.

SYNTHETIC, per CLAUDE.md's synthetic-test rule: these hand-build
`ResolvedMeeting`/fake finders rather than fetching a real page, but the
SHAPE reused is the real, confirmed-live 2026-09-25 case this WO closes --
Mary Esther, FL (Archive page id 11151, platform civicclerk): a bare
CivicClerk portal root (`https://maryestherfl.portal.civicclerk.com`, no
event id in the path) that `civicclerk.py`'s real adapter cannot parse,
paired with a real, playable stored `video_url`
(`https://cpmedia.azureedge.net/maryestherfl/1a1a01e3-6195-4f33-be2c-
4f0c7c235deb.mp4`). Fake finders stand in for the real civicclerk/
direct_file adapters so this test doesn't depend on either adapter's own
internals or a live network call.
"""

import pytest

import app.platforms.reresolve as reresolve_mod
from app.platforms.models import ResolvedMeeting
from app.platforms.reresolve import reresolve_for_transcription

MARY_ESTHER_SOURCE_URL = "https://maryestherfl.portal.civicclerk.com"
MARY_ESTHER_VIDEO_URL = (
    "https://cpmedia.azureedge.net/maryestherfl/"
    "1a1a01e3-6195-4f33-be2c-4f0c7c235deb.mp4"
)


class _RaisingFinder:
    """Stands in for civicclerk.py's real adapter raising on a bare
    portal-root URL with no event id -- the real, confirmed error shape
    is `ValueError("Could not find an event ID in URL path: ")`."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def resolve(self, url):
        raise self._exc


class _NoMediaFinder:
    """A resolve that succeeds but finds nothing usable -- the other
    real shape `transcription_media_url()` treats as a failure, e.g.
    direct_file.py's own graceful "could not confirm this URL serves a
    playable video" degradation."""

    async def resolve(self, url):
        return ResolvedMeeting(platform="civicclerk", source_url=url)


class _WorkingFinder:
    def __init__(self, platform: str, video_url: str):
        self._platform = platform
        self._video_url = video_url

    async def resolve(self, url):
        return ResolvedMeeting(
            platform=self._platform,
            source_url=url,
            video_url=self._video_url,
            video_format="mp4",
        )


async def test_primary_success_returns_unchanged_no_fallback_attempted(monkeypatch):
    """When the primary resolve already finds usable media, the fallback
    machinery (detect_platform/get_finder) must never even be consulted --
    monkeypatched to blow up if called, to prove that."""

    def _boom(*args, **kwargs):
        raise AssertionError("fallback must not be attempted when primary succeeds")

    monkeypatch.setattr(reresolve_mod, "detect_platform", _boom)
    monkeypatch.setattr(reresolve_mod, "get_finder", _boom)

    finder = _WorkingFinder("civicclerk", "https://example.com/real-video.mp4")
    result = await reresolve_for_transcription(
        finder=finder,
        platform="civicclerk",
        source_url="https://example.civicclerk.com/event/42/media",
        video_url=MARY_ESTHER_VIDEO_URL,
    )
    assert result.platform == "civicclerk"
    assert result.source_url == "https://example.civicclerk.com/event/42/media"
    assert result.video_url == "https://example.com/real-video.mp4"


async def test_fallback_used_when_primary_raises(monkeypatch):
    """The real Mary Esther, FL shape: the primary resolve of the bare
    portal-root source_url raises, but the stored video_url (a direct
    MP4 file) re-resolves fine via direct_file's own platform."""
    monkeypatch.setattr(reresolve_mod, "detect_platform", lambda url: "direct_file")
    monkeypatch.setattr(
        reresolve_mod,
        "get_finder",
        lambda platform: _WorkingFinder("direct_file", MARY_ESTHER_VIDEO_URL),
    )

    primary = _RaisingFinder(ValueError("Could not find an event ID in URL path: "))
    result = await reresolve_for_transcription(
        finder=primary,
        platform="civicclerk",
        source_url=MARY_ESTHER_SOURCE_URL,
        video_url=MARY_ESTHER_VIDEO_URL,
    )
    assert result.video_url == MARY_ESTHER_VIDEO_URL
    # source_url/platform restored back to the PAGE's own values, not the
    # fallback resolve's own direct_file platform/video URL -- see the
    # module docstring for why this matters (duplicate-page risk,
    # platform-column overwrite risk on the next re-ingest).
    assert result.source_url == MARY_ESTHER_SOURCE_URL
    assert result.platform == "civicclerk"


async def test_fallback_used_when_primary_finds_no_usable_media(monkeypatch):
    """The primary resolve doesn't have to raise to trigger a fallback --
    a graceful "found nothing" result (direct_file.py's own degradation
    shape) counts too."""
    monkeypatch.setattr(reresolve_mod, "detect_platform", lambda url: "direct_file")
    monkeypatch.setattr(
        reresolve_mod,
        "get_finder",
        lambda platform: _WorkingFinder("direct_file", MARY_ESTHER_VIDEO_URL),
    )

    result = await reresolve_for_transcription(
        finder=_NoMediaFinder(),
        platform="civicclerk",
        source_url=MARY_ESTHER_SOURCE_URL,
        video_url=MARY_ESTHER_VIDEO_URL,
    )
    assert result.video_url == MARY_ESTHER_VIDEO_URL
    assert result.source_url == MARY_ESTHER_SOURCE_URL
    assert result.platform == "civicclerk"


async def test_no_video_url_reraises_primary_exception():
    exc = ValueError("Could not find an event ID in URL path: ")
    with pytest.raises(ValueError):
        await reresolve_for_transcription(
            finder=_RaisingFinder(exc),
            platform="civicclerk",
            source_url=MARY_ESTHER_SOURCE_URL,
            video_url=None,
        )


async def test_fallback_never_used_for_a_youtube_video_url(monkeypatch):
    """Per CLAUDE.md's YouTube-drip-only rule: this path must never make
    a YouTube request, even when a page's own stored video_url happens
    to be a youtube.com link. detect_platform() is the real function
    here (not monkeypatched) specifically so this proves the actual
    "youtube" classification is what's checked, not a stub; get_finder()
    is monkeypatched to blow up so a YouTube fallback attempt would fail
    the test loudly rather than silently doing nothing."""

    def _boom(*args, **kwargs):
        raise AssertionError("must never call get_finder for a YouTube fallback")

    monkeypatch.setattr(reresolve_mod, "get_finder", _boom)

    exc = ValueError("Could not find an event ID in URL path: ")
    with pytest.raises(ValueError):
        await reresolve_for_transcription(
            finder=_RaisingFinder(exc),
            platform="civicclerk",
            source_url=MARY_ESTHER_SOURCE_URL,
            video_url="https://www.youtube.com/watch?v=abc123",
        )


async def test_fallback_resolve_itself_failing_reraises_primary_exception(
    monkeypatch,
):
    """A stale/broken video_url (the residual case the module docstring
    calls out -- "a stale video_url still fails cleanly") must not mask
    the primary failure with a confusing fallback-specific one."""
    monkeypatch.setattr(reresolve_mod, "detect_platform", lambda url: "direct_file")

    class _AlsoRaisingFinder:
        async def resolve(self, url):
            raise TimeoutError("fallback video host unreachable")

    monkeypatch.setattr(
        reresolve_mod, "get_finder", lambda platform: _AlsoRaisingFinder()
    )

    exc = ValueError("Could not find an event ID in URL path: ")
    with pytest.raises(ValueError):
        await reresolve_for_transcription(
            finder=_RaisingFinder(exc),
            platform="civicclerk",
            source_url=MARY_ESTHER_SOURCE_URL,
            video_url=MARY_ESTHER_VIDEO_URL,
        )


async def test_fallback_finding_no_media_either_reraises_primary_exception(
    monkeypatch,
):
    monkeypatch.setattr(reresolve_mod, "detect_platform", lambda url: "direct_file")
    monkeypatch.setattr(reresolve_mod, "get_finder", lambda platform: _NoMediaFinder())

    exc = ValueError("Could not find an event ID in URL path: ")
    with pytest.raises(ValueError):
        await reresolve_for_transcription(
            finder=_RaisingFinder(exc),
            platform="civicclerk",
            source_url=MARY_ESTHER_SOURCE_URL,
            video_url=MARY_ESTHER_VIDEO_URL,
        )
