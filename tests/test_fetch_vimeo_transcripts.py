"""Tests for scripts/fetch_vimeo_transcripts.py (WO-1147, 2026-09-27) --
the Vimeo sibling of scripts/fetch_youtube_transcripts.py, built for the
same reason (this service's own Render IP can't fetch captions itself;
see BACKLOG.md's "Vimeo blocks Render" entry). Follows the exact mocking
idioms tests/test_fetch_youtube_transcripts.py already established
(monkeypatched aiohttp.ClientSession.post, AsyncMock-free contextmanager
fakes) rather than inventing a new style.
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_vimeo_transcripts import (  # noqa: E402
    classify_vimeo_block,
    confirmed_no_captions,
    process_one,
)

from app.platforms.models import ResolvedMeeting, TranscriptSegment  # noqa: E402
from app.platforms.vimeo import (  # noqa: E402
    VIMEO_NO_CAPTIONS_CONFIRMED_MARKER,
    _NO_CAPTIONS_WARNING,
)

# Real log-message strings copied verbatim from app/platforms/vimeo.py's
# own _log_caption_fallback() call sites (per CLAUDE.md's synthetic-test
# convention: reuse a confirmed-real shape, don't invent a plausible one).
_REAL_CHALLENGE_MESSAGE = (
    "vimeo captions fallback: plain-fetch route: player page returned a "
    "challenge (HTTP 401) (video 1226646429)"
)


def _log_both_routes_found_nothing():
    import logging

    log = logging.getLogger("rtr_deeplink.vimeo")
    log.warning(
        "vimeo captions fallback: plain-fetch route: no window.playerConfig "
        "text_tracks found (video 1212025580)"
    )
    log.warning(
        "vimeo captions fallback: no <track> element found on player page "
        "(video 1212025580)"
    )


_REAL_NON_CHALLENGE_MESSAGES = [
    "vimeo captions fallback: no <track> element found on player page (video 1212025580)",
    "vimeo captions fallback: caption file parsed to zero cues (video 1212025580)",
    "vimeo captions fallback: no headless browser available (video 1212025580)",
    "vimeo captions fallback: plain-fetch route: no window.playerConfig text_tracks found (video 1212025580)",
]


def test_classify_vimeo_block_true_for_a_real_challenge_message():
    assert classify_vimeo_block([_REAL_CHALLENGE_MESSAGE])
    assert classify_vimeo_block(["unrelated", _REAL_CHALLENGE_MESSAGE])


def test_classify_vimeo_block_false_for_real_non_challenge_messages():
    for msg in _REAL_NON_CHALLENGE_MESSAGES:
        assert not classify_vimeo_block([msg])
    assert not classify_vimeo_block(_REAL_NON_CHALLENGE_MESSAGES)
    assert not classify_vimeo_block([])


class _FakePostResponse:
    def __init__(self, json_body):
        self._json_body = json_body
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return str(self._json_body)

    async def json(self):
        return self._json_body


@contextmanager
def _mock_post(routes: dict):
    """Same convention as tests/test_fetch_youtube_transcripts.py's own
    _mock_post: routes maps exact URL -> response dict, calls are recorded
    as (url, json_body) tuples."""
    calls = []

    def fake_post(self, url, json=None, **kwargs):
        calls.append((str(url), json))
        key = str(url)
        if key not in routes:
            raise AssertionError(f"Unmocked POST in test: {key}")
        return _FakePostResponse(routes[key])

    with mock.patch.object(aiohttp.ClientSession, "post", fake_post):
        yield calls


def _page(**overrides) -> dict:
    page = {
        "slug": "vimeo-test-meeting",
        "title": "Vimeo Test Meeting",
        "platform": "vimeo",
        "external_id": "vimeo:1212025580",
        "source_url_normalized": "https://vimeo.com/1212025580",
        "video_url": "https://player.vimeo.com/video/1212025580",
    }
    page.update(overrides)
    return page


async def test_process_one_no_video_id_fails():
    async with aiohttp.ClientSession() as session:
        result = await process_one(
            session, _page(video_url="https://example.com/not-vimeo"), dry_run=False
        )
    assert result["status"] == "failed"
    assert "no Vimeo video id" in result["detail"]


async def test_process_one_ingests_and_promotes_real_segments(monkeypatch):
    base = "https://archive.example.com"
    monkeypatch.setattr("scripts.fetch_youtube_transcripts._base_url", lambda: base)

    resolved = ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/1212025580",
        external_id="vimeo:1212025580",
        video_url="https://player.vimeo.com/video/1212025580",
        video_format="vimeo",
        segments=[TranscriptSegment(start=0.0, end=1.0, text="hello")],
        transcript_language="en",
        transcript_warnings=[],
    )

    async def fake_resolve_video_id(video_id, *, privacy_hash=None, source_url=None):
        _log_both_routes_found_nothing()
        return resolved

    monkeypatch.setattr(
        "fetch_vimeo_transcripts.VimeoAssetFinder.resolve_video_id",
        fake_resolve_video_id,
    )
    routes = {
        f"{base}/internal/ingest": {
            "slug": "vimeo-test-meeting",
            "url": "/m/vimeo-test-meeting",
            "version_id": 42,
        },
        f"{base}/internal/transcript-version/promote": {
            "slug": "vimeo-test-meeting",
            "promoted_version_id": 42,
        },
    }

    async with aiohttp.ClientSession() as session:
        with _mock_post(routes) as calls:
            result = await process_one(session, _page(), dry_run=False)

    assert result["status"] == "ingested"
    assert "(promoted to default)" in result["detail"]
    urls_called = [url for url, _body in calls]
    assert urls_called == [
        f"{base}/internal/ingest",
        f"{base}/internal/transcript-version/promote",
    ]
    ingest_body = calls[0][1]
    assert ingest_body["video_format"] == "vimeo"
    assert ingest_body["segments"] == [
        {"start": 0.0, "end": 1.0, "text": "hello", "speaker": None}
    ]
    assert ingest_body["transcript_language"] == "en"
    promote_body = calls[1][1]
    assert promote_body == {
        "slug": "vimeo-test-meeting",
        "version_id": 42,
        "clear_warnings": True,
    }


async def test_process_one_records_permanent_marker_when_no_captions_confirmed(
    monkeypatch,
):
    base = "https://archive.example.com"
    monkeypatch.setattr("scripts.fetch_youtube_transcripts._base_url", lambda: base)

    resolved = ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/1212025580",
        external_id="vimeo:1212025580",
        video_url="https://player.vimeo.com/video/1212025580",
        video_format="vimeo",
        segments=[],
        transcript_warnings=[_NO_CAPTIONS_WARNING],
    )

    async def fake_resolve_video_id(video_id, *, privacy_hash=None, source_url=None):
        _log_both_routes_found_nothing()
        return resolved

    monkeypatch.setattr(
        "fetch_vimeo_transcripts.VimeoAssetFinder.resolve_video_id",
        fake_resolve_video_id,
    )
    routes = {
        f"{base}/internal/pages/vimeo-test-meeting/video-status": {
            "slug": "vimeo-test-meeting",
            "page_id": 1,
            "version_id": None,
        },
    }

    async with aiohttp.ClientSession() as session:
        with _mock_post(routes) as calls:
            result = await process_one(session, _page(), dry_run=False)

    assert result["status"] == "skipped"
    assert "recorded permanent no-captions marker" in result["detail"]
    assert calls == [
        (
            f"{base}/internal/pages/vimeo-test-meeting/video-status",
            {"transcript_marker": VIMEO_NO_CAPTIONS_CONFIRMED_MARKER},
        )
    ]


async def test_process_one_returns_blocked_on_a_real_challenge(monkeypatch):
    base = "https://archive.example.com"
    monkeypatch.setattr("scripts.fetch_youtube_transcripts._base_url", lambda: base)

    resolved = ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/1226646429",
        external_id="vimeo:1226646429",
        video_url="https://player.vimeo.com/video/1226646429",
        video_format="vimeo",
        segments=[],
        transcript_warnings=[_NO_CAPTIONS_WARNING],
    )

    async def fake_resolve_video_id(video_id, *, privacy_hash=None, source_url=None):
        # Simulate the real code path logging a genuine challenge through
        # the "rtr_deeplink.vimeo" logger during the resolve call, the way
        # app/platforms/vimeo.py's own _log_caption_fallback() does.
        import logging

        logging.getLogger("rtr_deeplink.vimeo").warning(_REAL_CHALLENGE_MESSAGE)
        return resolved

    monkeypatch.setattr(
        "fetch_vimeo_transcripts.VimeoAssetFinder.resolve_video_id",
        fake_resolve_video_id,
    )

    async def _unexpected_record(*args, **kwargs):
        raise AssertionError("_record_video_status must not be called on a block")

    monkeypatch.setattr(
        "fetch_vimeo_transcripts._record_video_status", _unexpected_record
    )

    async with aiohttp.ClientSession() as session:
        with _mock_post({}):
            result = await process_one(
                session, _page(slug="vimeo-blocked-meeting"), dry_run=False
            )

    assert result["status"] == "blocked"
    assert "challenge" in result["detail"].lower()


async def test_process_one_dry_run_ingest_case_makes_no_network_call(monkeypatch):
    base = "https://archive.example.com"
    monkeypatch.setattr("scripts.fetch_youtube_transcripts._base_url", lambda: base)

    resolved = ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/1212025580",
        external_id="vimeo:1212025580",
        video_url="https://player.vimeo.com/video/1212025580",
        video_format="vimeo",
        segments=[TranscriptSegment(start=0.0, end=1.0, text="hello")],
        transcript_language="en",
        transcript_warnings=[],
    )

    async def fake_resolve_video_id(video_id, *, privacy_hash=None, source_url=None):
        _log_both_routes_found_nothing()
        return resolved

    monkeypatch.setattr(
        "fetch_vimeo_transcripts.VimeoAssetFinder.resolve_video_id",
        fake_resolve_video_id,
    )

    async with aiohttp.ClientSession() as session:
        with _mock_post({}) as calls:
            result = await process_one(session, _page(), dry_run=True)

    assert result["status"] == "skipped"
    assert "[dry-run] would push" in result["detail"]
    assert calls == []


async def test_process_one_dry_run_no_captions_case_makes_no_network_call(monkeypatch):
    base = "https://archive.example.com"
    monkeypatch.setattr("scripts.fetch_youtube_transcripts._base_url", lambda: base)

    resolved = ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/1212025580",
        external_id="vimeo:1212025580",
        video_url="https://player.vimeo.com/video/1212025580",
        video_format="vimeo",
        segments=[],
        transcript_warnings=[_NO_CAPTIONS_WARNING],
    )

    async def fake_resolve_video_id(video_id, *, privacy_hash=None, source_url=None):
        _log_both_routes_found_nothing()
        return resolved

    monkeypatch.setattr(
        "fetch_vimeo_transcripts.VimeoAssetFinder.resolve_video_id",
        fake_resolve_video_id,
    )

    async with aiohttp.ClientSession() as session:
        with _mock_post({}) as calls:
            result = await process_one(session, _page(), dry_run=True)

    assert result["status"] == "skipped"
    assert "[dry-run] would record permanent no-captions marker" in result["detail"]
    assert calls == []


def test_confirmed_no_captions_needs_both_routes():
    plain = _REAL_NON_CHALLENGE_MESSAGES[3]
    headless = _REAL_NON_CHALLENGE_MESSAGES[0]
    assert confirmed_no_captions([plain, headless])
    assert not confirmed_no_captions([plain])
    assert not confirmed_no_captions([headless])
    assert not confirmed_no_captions([])


def test_confirmed_no_captions_false_when_a_route_could_not_look():
    plain = _REAL_NON_CHALLENGE_MESSAGES[3]
    headless = _REAL_NON_CHALLENGE_MESSAGES[0]
    no_browser = _REAL_NON_CHALLENGE_MESSAGES[2]
    timed_out = "vimeo captions fallback: headless browser fetch timed out (video 1)"
    assert not confirmed_no_captions([plain, no_browser])
    assert not confirmed_no_captions([plain, timed_out])
    assert not confirmed_no_captions([_REAL_CHALLENGE_MESSAGE, headless])
