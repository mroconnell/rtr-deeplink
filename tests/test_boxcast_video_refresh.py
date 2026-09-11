"""A BoxCast meeting page keeps playing after its stored signed playlist
expires -- WO-229.

`app/platforms/boxcast.py`'s signed HLS playlist (`video_url`) carries a
real `Expires=`/`Signature=` and stops working a couple of days after
ingest (confirmed live on the first two real BoxCast pages, ingested
2026-09-11 -- see BACKLOG_DONE.md's WO-229 entry). These tests cover the
Archive-side fix: the player is pointed at `/m/{slug}/video` instead of
the raw stored `video_url` for a BoxCast page, and that route resolves a
fresh playlist (falling back to the stored one on any failure).

Synthetic pages via `crud.ingest_resolution()`, same pattern as
`test_meeting_page_structured_data.py` -- an EXPIRED `Expires=` is used
throughout (a real, no-longer-valid BoxCast timestamp shape, not an
invented URL structure) specifically to prove the fix doesn't depend on
the stored URL still happening to work.
"""

import json
import re

from fastapi.testclient import TestClient

import archive.main
from app.platforms import boxcast as boxcast_adapter
from archive.db import crud
from archive.utils import video_refresh

archive_client = TestClient(archive.main.app)

_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.DOTALL
)

# A real, already-expired BoxCast signed-playlist shape (module docstring
# of boxcast.py) -- Expires is a Unix timestamp well in this test suite's
# past relative to 2026-09-11, when this WO was built.
_EXPIRED_VIDEO_URL = (
    "https://play.boxcast.com/p/skd3evxqqhli7timl3qw/v/all.m3u8"
    "?Expires=1789329408&Signature=abc&Key-Pair-Id=xyz"
)
_FRESH_VIDEO_URL = (
    "https://play.boxcast.com/p/skd3evxqqhli7timl3qw/v/all.m3u8"
    "?Expires=1799999999&Signature=def&Key-Pair-Id=xyz"
)
_BOXCAST_SOURCE_URL = (
    "https://boxcast.tv/view/livermore-falls-select-board-meeting-a1b2c3"
)


def _payload(external_id: str, **overrides) -> dict:
    payload = {
        "platform": "boxcast",
        "source_url": _BOXCAST_SOURCE_URL,
        "external_id": external_id,
        "title": "Select Board Meeting",
        "date": "2026-09-01",
        "jurisdiction": "Livermore Falls, ME",
        "video_url": _EXPIRED_VIDEO_URL,
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _make_page(external_id: str, **overrides) -> str:
    result = await crud.ingest_resolution(
        _payload(external_id, **overrides), _BOXCAST_SOURCE_URL
    )
    return result["slug"]


async def _make_granicus_page(external_id: str) -> str:
    # Wilmington, OH -- a real, Census-valid city already used throughout
    # tests/test_boxcast.py (repo convention: synthetic payloads reuse
    # confirmed-real facts, never an invented jurisdiction like
    # "Anytown, CA" -- test_state_pages.py's own docstring, and a real,
    # confirmed-live hazard: an earlier session's fake jurisdiction in
    # this same shared-session DB broke an unrelated /state/{slug}
    # assertion elsewhere in the suite).
    url = f"https://example.granicus.com/{external_id}"
    payload = {
        "platform": "granicus",
        "source_url": url,
        "external_id": external_id,
        "title": "Council Meeting",
        "date": "2026-09-01",
        "jurisdiction": "City of Wilmington, OH",
        "video_url": "https://archive-media.granicus.com/OnDemand/g/g.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    result = await crud.ingest_resolution(payload, url)
    return result["slug"]


def _get_json_ld(html: str) -> dict:
    match = _JSON_LD_RE.search(html)
    assert match, "no JSON-LD script block found"
    return json.loads(match.group(1))


def setup_function(_):
    # The refresh cache is process-global and keyed by slug -- clear it
    # before every test so one test's cached fresh URL can't leak into
    # the next one's assertions.
    video_refresh._cache.clear()


async def test_boxcast_page_points_its_player_at_the_video_redirect(monkeypatch):
    async def _fake_refresh(source_url):
        assert source_url == _BOXCAST_SOURCE_URL
        return _FRESH_VIDEO_URL

    monkeypatch.setattr(boxcast_adapter, "refresh_playlist_url", _fake_refresh)

    slug = await _make_page("wo229-player-target")
    html = archive_client.get(f"/m/{slug}").text

    assert f'data-video-url="/m/{slug}/video"' in html
    assert _EXPIRED_VIDEO_URL not in html
    data = _get_json_ld(html)
    assert data["contentUrl"] == f"/m/{slug}/video"


async def test_non_boxcast_page_is_completely_unaffected():
    # The negative control: every other platform's player still points
    # straight at page.video_url, exactly as before this WO.
    slug = await _make_granicus_page("wo229-negative-control")
    html = archive_client.get(f"/m/{slug}").text

    assert (
        'data-video-url="https://archive-media.granicus.com/OnDemand/g/g.m3u8"' in html
    )
    assert f"/m/{slug}/video" not in html
    data = _get_json_ld(html)
    assert data["contentUrl"] == "https://archive-media.granicus.com/OnDemand/g/g.m3u8"


async def test_video_redirect_follows_to_a_freshly_resolved_playlist(monkeypatch):
    async def _fake_refresh(source_url):
        return _FRESH_VIDEO_URL

    monkeypatch.setattr(boxcast_adapter, "refresh_playlist_url", _fake_refresh)

    slug = await _make_page("wo229-fresh-redirect")
    response = archive_client.get(f"/m/{slug}/video", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == _FRESH_VIDEO_URL


async def test_video_redirect_falls_back_to_the_stored_url_on_refresh_failure(
    monkeypatch,
):
    # The whole point: even with an EXPIRED stored video_url, a BoxCast
    # API hiccup degrades to "serve the last-known URL" rather than a 404
    # -- the same graceful-degradation posture as every other signed-URL
    # source in this codebase.
    async def _fake_refresh(source_url):
        return None

    monkeypatch.setattr(boxcast_adapter, "refresh_playlist_url", _fake_refresh)

    slug = await _make_page("wo229-refresh-fails")
    response = archive_client.get(f"/m/{slug}/video", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == _EXPIRED_VIDEO_URL


async def test_video_redirect_404s_for_an_unknown_slug():
    response = archive_client.get("/m/not-a-real-slug/video", follow_redirects=False)
    assert response.status_code == 404


async def test_fresh_video_url_is_cached_within_the_ttl_window(monkeypatch):
    calls = []

    async def _fake_refresh(source_url):
        calls.append(source_url)
        return _FRESH_VIDEO_URL

    monkeypatch.setattr(boxcast_adapter, "refresh_playlist_url", _fake_refresh)

    slug = await _make_page("wo229-cache-hit")
    archive_client.get(f"/m/{slug}/video", follow_redirects=False)
    archive_client.get(f"/m/{slug}/video", follow_redirects=False)

    assert len(calls) == 1


async def test_fresh_video_url_returns_none_immediately_for_a_non_refresh_platform():
    # No network call attempted at all -- NEEDS_REFRESH gates before
    # _REFRESHERS is even consulted.
    fresh = await video_refresh.fresh_video_url(
        "granicus", "https://example.granicus.com/x", "some-slug"
    )
    assert fresh is None
