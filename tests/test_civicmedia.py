"""Tests for CivicPlus's CivicMedia video widget (app/platforms/civicmedia.py,
WO-341). Real, raw-saved fixtures from Hobart, IN (`cityofhobart.org`) --
see `tests/fixtures/civicmedia/README.md` for what was fetched and why.
"""

from app.platforms.base import detect_platform
from app.platforms.civicmedia import (
    CivicMediaAssetFinder,
    _jurisdiction_from_page,
    civicmedia_page_id,
    is_civicmedia_page_url,
    is_tikilive_embed_url,
    refresh_playlist_url,
)

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

PAGE_URL = "https://www.cityofhobart.org/CivicMedia?VID=326"
EMBED_URL = (
    "https://civplus.tikiliveapi.com/embed?scheme=embedVod&videoId=160547&autoplay=no"
)
M3U8_URL = (
    "https://wms.civplus.tikiliveapi.com/vodhttporigin_civplustest/160547/"
    "smil:civplustest/encoded_streams/0/928/160547.smil/playlist.m3u8"
    "?p=vodcdn&chid=93145&ts_chunk_length=6&op_id=1&userId=0&videoId=160547"
    "&stime=1789314015&etime=1789400415&token=01a16af706806ef1e0299"
)
CAPTION_URL = (
    "https://civplus.tikiliveapi.com/public/files/closed-captions/160/160547_en.vtt"
)


def _routes(vtt_body=None):
    routes = {
        PAGE_URL: FakeResponse(
            status=200,
            text=load_fixture("civicmedia", "hobart_civicmedia_vid326.html"),
            url=PAGE_URL,
        ),
        EMBED_URL: FakeResponse(
            status=200,
            text=load_fixture("civicmedia", "tikilive_embed_160547.html"),
            url=EMBED_URL,
        ),
    }
    if vtt_body is not None:
        routes[CAPTION_URL] = FakeResponse(status=200, text=vtt_body, url=CAPTION_URL)
    return routes


# -- detect_platform() -------------------------------------------------


def test_detect_platform_recognizes_civicmedia_page_url():
    assert detect_platform(PAGE_URL) == "civicmedia"
    assert (
        detect_platform(
            "https://www.cityofhobart.org/CivicMedia.aspx?VID=Board-of-Works-09022026-327"
        )
        == "civicmedia"
    )


def test_detect_platform_recognizes_tikilive_embed_host():
    assert detect_platform(EMBED_URL) == "civicmedia"


def test_detect_platform_ignores_civicmedia_page_with_no_vid():
    # A bare `/CivicMedia` with no `VID=` isn't a resolvable single video --
    # falls through to CivicPlus's own AgendaCenter-shaped/unknown checks,
    # same as any other unrecognized path.
    assert detect_platform("https://www.cityofhobart.org/CivicMedia") == "unknown"


def test_is_civicmedia_page_url_and_is_tikilive_embed_url():
    assert is_civicmedia_page_url(PAGE_URL)
    assert not is_civicmedia_page_url(EMBED_URL)
    assert is_tikilive_embed_url(EMBED_URL)
    assert not is_tikilive_embed_url(PAGE_URL)


# -- civicmedia_page_id() (VID id space, NOT TikiLive's videoId) -------


def test_civicmedia_page_id_reads_bare_and_slug_forms():
    assert civicmedia_page_id("https://x/CivicMedia?VID=326") == "326"
    assert (
        civicmedia_page_id("https://x/CivicMedia.aspx?VID=Board-of-Works-09022026-327")
        == "327"
    )


# -- CivicMediaAssetFinder.resolve() ------------------------------------


async def test_real_hobart_civicmedia_page_resolves_video_and_captions():
    # Real per-video title, m3u8 and closed-caption track, all read from
    # the two real fixtures (the CivicMedia page's own iframe, then the
    # TikiLive embed underneath) -- see module docstring.
    vtt_body = load_fixture("civicmedia", "hobart_160547_en_excerpt.vtt")
    with mock_session(_routes(vtt_body=vtt_body)):
        resolved = await CivicMediaAssetFinder().resolve(PAGE_URL)

    assert resolved.platform == "civicmedia"
    assert resolved.source_url == PAGE_URL
    assert resolved.external_id == "civicmedia:160547"
    # "Video - " boilerplate prefix stripped from the iframe's own title.
    assert resolved.title == "Park Board 08-10-26"
    assert resolved.video_url == M3U8_URL
    assert resolved.video_format == "m3u8"
    assert resolved.segments, "expected real caption segments from the VTT fixture"
    assert resolved.segments[0].text.startswith("Great. It's 6 o'clock")
    assert resolved.transcript_language == "en"
    assert not resolved.video_warnings
    assert not resolved.transcript_warnings


async def test_civicmedia_page_with_no_captions_warns_honestly():
    # Same real page/embed, but no closed-caption route registered -- the
    # honest, real outcome for a CivicMedia video with none (per module
    # docstring: only ONE real example with captions is confirmed so
    # far, so a caller MUST be able to tell "no captions on this one"
    # apart from "we haven't checked yet").
    with mock_session(_routes(vtt_body=None)):
        resolved = await CivicMediaAssetFinder().resolve(PAGE_URL)

    assert resolved.video_url == M3U8_URL
    assert not resolved.segments
    assert resolved.transcript_warnings == [
        "We couldn't find captions for this meeting on CivicMedia."
    ]


async def test_tikilive_embed_url_resolved_directly_has_no_title():
    # A bare TikiLive embed URL (no parent CivicMedia page) carries no
    # title of its own -- see module docstring, "no title info in the
    # TikiLive embed page itself" finding.
    with mock_session(_routes(vtt_body=None)):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_URL)

    assert resolved.title is None
    assert resolved.video_url == M3U8_URL
    assert resolved.external_id == "civicmedia:160547"


async def test_no_iframe_found_is_an_honest_video_warning_not_a_crash():
    bland = "<html><body>Nothing here.</body></html>"
    routes = {PAGE_URL: FakeResponse(status=200, text=bland, url=PAGE_URL)}
    with mock_session(routes):
        resolved = await CivicMediaAssetFinder().resolve(PAGE_URL)

    assert resolved.video_url is None
    assert resolved.video_warnings == [
        "This looks like a CivicMedia page, but we couldn't find its video player."
    ]


# -- jurisdiction from the page's own site name (WO-1069) -------------


async def test_real_hobart_page_names_its_own_government():
    # The real page's `og:site_name` is "Hobart, IN" -- before WO-1069
    # resolve() returned no jurisdiction at all, and a caller that sent
    # no gov_id got "no government".
    with mock_session(_routes(vtt_body=None)):
        resolved = await CivicMediaAssetFinder().resolve(PAGE_URL)

    assert resolved.jurisdiction == "Hobart, IN"


def test_real_hobart_site_name_keys_to_the_archive_government():
    # us:place:1834114 is the gov_id the Archive already holds for this
    # page (pinned by the WO-349 ingest script); the page's own name now
    # reaches it at registry level with no pin.
    from app.utils.gov_registry import resolve_government

    html = load_fixture("civicmedia", "hobart_civicmedia_vid326.html")
    match = resolve_government(
        _jurisdiction_from_page(html, PAGE_URL), tenant_host="www.cityofhobart.org"
    )
    assert (match.gov_id, match.tier) == ("us:place:1834114", "registry")


def test_real_snyder_site_name_without_a_state_gets_one():
    # Real page, snydertx.gov/CivicMedia?VID=133: its site name is "City
    # of Snyder", no state. Snyder is real in more than one state, so the
    # name alone doesn't place it; the ZIP in the page's own footer
    # address does, via enrich_jurisdiction_text().
    html = load_fixture("civicmedia", "snyder_civicmedia_vid133.html")
    assert (
        _jurisdiction_from_page(html, "https://snydertx.gov/CivicMedia?VID=133")
        == "City of Snyder, TX"
    )


def test_title_is_the_fallback_when_og_site_name_is_missing():
    # SYNTHETIC: the real Hobart page with its og:site_name tag removed,
    # leaving the real "CivicMedia™ • Hobart, IN • CivicEngage" title.
    # Every CivicMedia page checked so far (11 tenants) carries both, so
    # no real page missing the tag has been seen.
    html = load_fixture("civicmedia", "hobart_civicmedia_vid326.html")
    stripped = html.replace('property="og:site_name"', 'property="og:ignored"')
    assert stripped != html
    assert _jurisdiction_from_page(stripped, PAGE_URL) == "Hobart, IN"


def test_civicplus_subdomain_is_the_last_resort():
    # SYNTHETIC page text; the host shape is real (ma-middleton.civicplus
    # .com serves the same CivicMedia site as www.middletonma.gov).
    url = "https://ma-middleton.civicplus.com/CivicMedia?VID=814"
    assert _jurisdiction_from_page("<html></html>", url) == "Middleton, MA"
    assert _jurisdiction_from_page("<html></html>", PAGE_URL) is None


async def test_bare_tikilive_embed_has_no_government_to_read():
    # The embed's own HTML names no tenant -- the honest answer is None.
    with mock_session(_routes(vtt_body=None)):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_URL)

    assert resolved.jurisdiction is None


# -- refresh_playlist_url() (signed/expiring HLS playlist, WO-341) -----


async def test_refresh_playlist_url_refetches_a_fresh_m3u8():
    with mock_session(_routes()):
        fresh = await refresh_playlist_url(PAGE_URL)

    assert fresh == M3U8_URL


async def test_refresh_playlist_url_returns_none_on_fetch_failure():
    routes = {PAGE_URL: FakeResponse(status=404, text="", url=PAGE_URL)}
    with mock_session(routes):
        fresh = await refresh_playlist_url(PAGE_URL)

    assert fresh is None
