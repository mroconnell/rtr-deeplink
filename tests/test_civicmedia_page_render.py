"""A CivicMedia meeting page renders even when the view-time TikiLive
refetch fails -- WO-362.

Real incident: Englewood city, OH (`https://englewood.oh.us/CivicMedia?
VID=106`, ingested by WO-357, 583 real caption segments) returned a live
HTTP 500 on `/m/{slug}` and kept doing so after a re-ingest. Reproducing
locally against a seeded SQLite Archive showed the real cause: WO-341's
CivicMedia support put `civicmedia` in `archive.utils.video_refresh.
NEEDS_REFRESH` (its signed HLS playlist expires ~24h after generation,
same shape as BoxCast), and the `/m/{slug}` route (and `/m/{slug}/
card.jpg`) AWAITED `fresh_video_url()` INLINE, on the request path,
whenever the page's card thumbnail hadn't warmed yet -- up to two
sequential live HTTP fetches (30s aiohttp timeout each) blocking the
actual page render. Hobart, IN (the other real CivicMedia page, already
live for days with its card long since cached) never hit this path at
all, which is why it kept rendering fine while Englewood -- freshly
ingested, its ffmpeg card extraction failing against the signed
playlist's own high seek offset -- stayed permanently stuck re-running
that blocking fetch on every single view.

The fix (`archive/main.py`'s `_schedule_card_warm()`/
`_extract_card_with_refresh()`) moves that resolution into the
background task itself, so the response for `/m/{slug}` (and `/m/{slug}/
card.jpg`) never waits on it -- plus a defense-in-depth timeout + catch-
all inside `fresh_video_url()` itself (`archive/utils/video_refresh.py`),
since every refresher's "never raises" claim was trusted, not enforced,
before this WO.

These tests use the real Hobart, IN CivicMedia URL/ids already fixture-
verified by `tests/test_civicmedia.py` (never an invented URL shape),
with the refetch itself monkeypatched to fail -- the scenario a real
network hiccup or a stale/broken signed playlist produces.
"""

from fastapi.testclient import TestClient

import archive.main
from app.platforms import civicmedia as civicmedia_adapter
from archive.db import crud
from archive.utils import video_refresh

archive_client = TestClient(archive.main.app)

# Real Hobart, IN CivicMedia page/ids -- same constants tests/
# test_civicmedia.py uses, confirmed live (WO-341, BACKLOG_DONE.md).
_SOURCE_URL = "https://www.cityofhobart.org/CivicMedia?VID=326"
_STORED_VIDEO_URL = (
    "https://wms.civplus.tikiliveapi.com/vodhttporigin_civplustest/160547/"
    "smil:civplustest/encoded_streams/0/928/160547.smil/playlist.m3u8"
    "?p=vodcdn&chid=93145&ts_chunk_length=6&op_id=1&userId=0&videoId=160547"
    "&stime=1789314015&etime=1789400415&token=01a16af706806ef1e0299"
)


def setup_function(_):
    # Same reasoning as tests/test_boxcast_video_refresh.py's own
    # setup_function -- the refresh cache is process-global and keyed by
    # slug, so one test's cached (or cached-failure) result can't leak
    # into the next one's assertions.
    video_refresh._cache.clear()


async def _make_page(external_id: str, **overrides) -> str:
    payload = {
        "platform": "civicmedia",
        "source_url": _SOURCE_URL,
        "external_id": external_id,
        "title": "Park Board Meeting",
        "date": "2026-08-10",
        "jurisdiction": "Hobart, IN",
        "video_url": _STORED_VIDEO_URL,
        "video_format": "m3u8",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Call to order."},
        ],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    payload.update(overrides)
    result = await crud.ingest_resolution(payload, _SOURCE_URL)
    return result["slug"]


async def test_meeting_page_renders_when_the_civicmedia_refetch_raises(
    monkeypatch,
):
    """The core WO-362 regression test: a page whose card thumbnail has
    not warmed yet (a fresh ingest, exactly Englewood's real state) must
    still render 200 even when the view-time TikiLive refetch blows up
    with a genuine exception -- never a 500."""

    async def _raising_refresh(source_url):
        raise RuntimeError("simulated TikiLive outage (WO-362 regression test)")

    monkeypatch.setattr(civicmedia_adapter, "refresh_playlist_url", _raising_refresh)

    slug = await _make_page("wo362-render-refetch-raises")
    response = archive_client.get(f"/m/{slug}")

    assert response.status_code == 200
    assert "Park Board Meeting" in response.text


async def test_card_image_route_renders_when_the_civicmedia_refetch_raises(
    monkeypatch,
):
    """Same failure, the other call site: /m/{slug}/card.jpg (hit by
    social scrapers and Googlebot, not by a human visitor's browser) must
    also degrade to its documented "no card yet" 404 rather than
    surfacing the refetch's exception."""

    async def _raising_refresh(source_url):
        raise RuntimeError("simulated TikiLive outage (WO-362 regression test)")

    monkeypatch.setattr(civicmedia_adapter, "refresh_playlist_url", _raising_refresh)

    slug = await _make_page("wo362-card-refetch-raises")
    response = archive_client.get(f"/m/{slug}/card.jpg")

    # No frame stored yet (nothing extracted synchronously by this
    # request) -- the documented "not found yet, come back later" shape,
    # not a 500.
    assert response.status_code == 404


async def test_fresh_video_url_falls_back_to_none_when_the_refresher_raises():
    """Unit-level coverage for video_refresh.py's own defense-in-depth:
    even though every refresher documents "never raises", fresh_video_url()
    itself must not propagate one -- belt and braces, WO-362."""

    async def _raising_refresh(source_url):
        raise RuntimeError("boom")

    import archive.utils.video_refresh as video_refresh_module

    original = video_refresh_module._REFRESHERS["civicmedia"]
    video_refresh_module._REFRESHERS["civicmedia"] = _raising_refresh
    try:
        result = await video_refresh.fresh_video_url(
            "civicmedia", _SOURCE_URL, "wo362-unit-cache-key"
        )
    finally:
        video_refresh_module._REFRESHERS["civicmedia"] = original

    assert result is None


async def test_meeting_page_still_renders_normally_when_the_refetch_succeeds(
    monkeypatch,
):
    """Negative control: a successful refetch still works exactly as
    before this WO -- the fix only changes WHEN/WHERE the call happens,
    not its outcome."""

    async def _fake_refresh(source_url):
        return _STORED_VIDEO_URL

    monkeypatch.setattr(civicmedia_adapter, "refresh_playlist_url", _fake_refresh)

    slug = await _make_page("wo362-render-refetch-succeeds")
    response = archive_client.get(f"/m/{slug}")

    assert response.status_code == 200
    assert "Park Board Meeting" in response.text
