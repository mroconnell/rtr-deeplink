"""Tests for CivicPlus's CivicMedia video widget (app/platforms/civicmedia.py,
WO-341). Real, raw-saved fixtures from Hobart, IN (`cityofhobart.org`) --
see `tests/fixtures/civicmedia/README.md` for what was fetched and why.
"""

from app.platforms.base import detect_platform
from app.platforms.civicmedia import (
    CivicMediaAssetFinder,
    _jurisdiction_from_page,
    _video_id_from_url,
    civicmedia_page_id,
    is_civicmedia_page_url,
    is_tikilive_embed_url,
    looks_like_file_name,
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


def test_detect_platform_recognizes_civicmedia_page_on_civicplus_subdomain():
    # WO-341's original check only ever confirmed the government's-own-
    # domain shape (cityofhobart.org). A CivicMedia page hosted on the
    # government's own *.civicplus.com tenant subdomain -- confirmed live
    # 2026-09-29 (pinned-only walk routing) against
    # pa-westmorelandcounty2.civicplus.com/CivicMedia?VID=Prison-Board-
    # 4262021-51 -- used to be misrouted to "civicplus", since the
    # netloc-based "civicplus.com" branch in detect_platform() ran before
    # this path-based CivicMedia check and matched first. That branch is
    # now checked ahead of the netloc one.
    assert (
        detect_platform(
            "https://pa-westmorelandcounty2.civicplus.com/CivicMedia?VID=Prison-Board-4262021-51"
        )
        == "civicmedia"
    )


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


async def test_tikilive_embed_url_with_no_video_page_has_no_title():
    # The embed page carries no title. With the video page unreachable
    # (unmocked here, so the fetch fails) the title stays None and the
    # rest of the resolve is unchanged (WO-1172).
    with mock_session(_routes(vtt_body=None)):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_URL)

    assert resolved.title is None
    assert resolved.video_url == M3U8_URL
    assert resolved.external_id == "civicmedia:160547"
    # The channel, from the stream address's own `chid=93145`.
    assert resolved.video_channel == "civicmedia:93145"


async def test_government_page_carries_the_channel_too():
    with mock_session(_routes(vtt_body=None)):
        resolved = await CivicMediaAssetFinder().resolve(PAGE_URL)

    assert resolved.video_channel == "civicmedia:93145"


async def test_no_stream_means_no_channel():
    routes = {EMBED_URL: FakeResponse(status=200, text="<html></html>", url=EMBED_URL)}
    with mock_session(routes):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_URL)

    assert resolved.video_channel is None


async def test_no_iframe_found_is_an_honest_video_warning_not_a_crash():
    bland = "<html><body>Nothing here.</body></html>"
    routes = {PAGE_URL: FakeResponse(status=200, text=bland, url=PAGE_URL)}
    with mock_session(routes):
        resolved = await CivicMediaAssetFinder().resolve(PAGE_URL)

    assert resolved.video_url is None
    assert resolved.video_warnings == [
        "This looks like a CivicMedia page, but we couldn't find its video player."
    ]


# -- which title (WO-1165) ---------------------------------------------
# Real government pages fetched live 2026-09-29, see
# tests/fixtures/civicmedia/README.md. Each test serves an empty TikiLive
# embed for the page's video, since only the title is under test.


def _embed_for(video_id):
    return (
        "https://civplus.tikiliveapi.com/embed?scheme=embedVod"
        f"&videoId={video_id}&autoplay=no"
    )


async def _resolve_page(url, fixture_name, video_id, html=None):
    page_html = html if html is not None else load_fixture("civicmedia", fixture_name)
    embed = _embed_for(video_id)
    routes = {
        url: FakeResponse(status=200, text=page_html, url=url),
        embed: FakeResponse(status=200, text="<html></html>", url=embed),
    }
    with mock_session(routes):
        return await CivicMediaAssetFinder().resolve(url)


ISANTI_URL = "https://www.isanticountymn.gov/CivicMedia?VID=461"
SEAGOVILLE_URL = (
    "https://seagoville.us/CivicMedia?VID=20250519-Regular-Session-Part-2-719"
)
STJOSEPH_URL = (
    "https://stjosephmo.gov/CivicMedia?VID=St-Joseph-Stormwater-Protection-and-Insp-1"
)


async def test_good_og_title_is_used():
    # Real Hobart page: og:title and player title agree.
    with mock_session(_routes(vtt_body=None)):
        resolved = await CivicMediaAssetFinder().resolve(PAGE_URL)

    assert resolved.title == "Park Board 08-10-26"


async def test_file_name_player_title_loses_to_the_page_title():
    # Real Isanti County, MN page. The player says "Video - Autorecord Jul
    # 14 2026, 10:18 AM" (the recorder's default name); the county's own
    # og:title names the meeting.
    resolved = await _resolve_page(
        ISANTI_URL, "isanti_civicmedia_vid461.html", "160294"
    )

    assert resolved.title == "Live Stream Committee of the Whole - July 14, 2026"
    assert resolved.jurisdiction == "Isanti County, MN"


async def test_part_number_comes_from_the_government_page():
    # Real Seagoville, TX page. The city's page and its VID say Part 2; the
    # TikiLive upload is named Part 3. Before WO-1165 the page got "Part 3".
    resolved = await _resolve_page(
        SEAGOVILLE_URL, "seagoville_civicmedia_vid719.html", "156829"
    )

    assert resolved.title == "2025-05-19 Regular Session (Part 2)"


async def test_cut_off_og_title_takes_the_players_full_version():
    # Real St. Joseph, MO page. CivicPlus cut og:title at 50 characters:
    # "St. Joseph Stormwater Protection and Inspection Me". The player has
    # the same words in full.
    resolved = await _resolve_page(
        STJOSEPH_URL, "stjoseph_civicmedia_vid1.html", "158548"
    )

    assert (
        resolved.title == "St. Joseph Stormwater Protection and Inspection Meeting 2025"
    )


async def test_bare_embed_with_failed_video_page_stays_untitled():
    # A 404 on the video page is handled the same as an unreachable one.
    routes = _routes(vtt_body=None)
    page = "https://civplus.tikiliveapi.com/video/160547"
    routes[page] = FakeResponse(status=404, text="", url=page)
    with mock_session(routes):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_URL)

    assert resolved.title is None
    assert resolved.video_url == M3U8_URL


async def test_missing_og_title_falls_back_to_the_player():
    # SYNTHETIC: the real Isanti page with its og:title tag removed. Real
    # shape: Fort Madison, IA's VID=681 page has no og:title (routing round
    # 2026-09-29). The <title> is CivicMedia boilerplate and is skipped, so
    # the player's file-name title is kept rather than no title.
    html = load_fixture("civicmedia", "isanti_civicmedia_vid461.html")
    stripped = html.replace('property="og:title"', 'property="og:ignored"')
    assert stripped != html
    resolved = await _resolve_page(ISANTI_URL, None, "160294", html=stripped)

    assert resolved.title == "Autorecord Jul 14 2026, 10:18 AM"


async def test_every_title_a_file_name_keeps_the_government_one():
    # SYNTHETIC page built from the real Northampton, MA values
    # (northamptonma.gov/CivicMedia?VID=BOH_011923-13, routing round
    # 2026-09-29): og:title "BOH_011923", player "DHHS_Amy_video060923".
    html = (
        "<html><head><title>CivicMedia\u2122 \u2022 Northampton, MA \u2022 "
        "CivicEngage</title>"
        '<meta property="og:title" content="BOH_011923" />'
        '<meta property="og:site_name" content="Northampton, MA" /></head><body>'
        '<iframe id="videoPlayer" title="Video - DHHS_Amy_video060923" '
        'src="https://civplus.tikiliveapi.com/embed?scheme=embedVod'
        '&videoId=152347&autoplay=yes"></iframe></body></html>'
    )
    url = "https://northamptonma.gov/CivicMedia?VID=BOH_011923-13"
    resolved = await _resolve_page(url, None, "152347", html=html)

    assert resolved.title == "BOH_011923"


def test_looks_like_file_name_on_real_titles():
    # Every string here is a real CivicMedia title (routing round
    # 2026-09-29 and the Archive's own CivicMedia pages).
    for name in (
        "DHHS_Amy_video060923",
        "BudgetHearing_11292022",
        "cm011226",
        "Pink Patch Project Meeting Irwindale 7-24-17.m4v",
        "Autorecord Sep 22 2026, 08:08 AM",
        "GMT20220519-000329_Recording_640x360",
        "",
        None,
    ):
        assert looks_like_file_name(name), name
    for name in (
        "Park Board 08-10-26",
        "2025-05-19 Regular Session (Part 2)",
        "City Council Meeting - Sep. 21, 2026",
        "SWFRS Public Scoping Mtg Recording 05-13-23 (MP4)",
        "20260908 Council Meeting",
    ):
        assert not looks_like_file_name(name), name


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


# -- TikiLive /video/{id} page (WO-1172) -------------------------------
# Real fixtures, fetched live 2026-09-30: video 144112, "260 - City
# Council Meeting 12.17.20.", channel 146.

VIDEO_PAGE_URL = "https://civplus.tikiliveapi.com/video/144112"
EMBED_144112_URL = (
    "https://civplus.tikiliveapi.com/embed?scheme=embedVod&videoId=144112&autoplay=no"
)
TITLE_144112 = "260 - City Council Meeting 12.17.20."


def _routes_144112():
    return {
        VIDEO_PAGE_URL: FakeResponse(
            status=200,
            text=load_fixture("civicmedia", "tikilive_video_144112.html"),
            url=VIDEO_PAGE_URL,
        ),
        EMBED_144112_URL: FakeResponse(
            status=200,
            text=load_fixture("civicmedia", "tikilive_embed_144112.html"),
            url=EMBED_144112_URL,
        ),
    }


def test_video_page_url_is_recognized_and_gives_the_video_id():
    assert detect_platform(VIDEO_PAGE_URL) == "civicmedia"
    assert _video_id_from_url(VIDEO_PAGE_URL) == "144112"
    assert _video_id_from_url(VIDEO_PAGE_URL + "/") == "144112"
    assert _video_id_from_url(EMBED_144112_URL) == "144112"
    assert _video_id_from_url("https://civplus.tikiliveapi.com/video/abc") is None


async def test_video_page_url_resolves_with_title_and_channel():
    with mock_session(_routes_144112()):
        resolved = await CivicMediaAssetFinder().resolve(VIDEO_PAGE_URL)

    assert resolved.title == TITLE_144112
    assert resolved.external_id == "civicmedia:144112"
    assert resolved.video_url and "videoId=144112" in resolved.video_url
    assert resolved.video_format == "m3u8"
    assert resolved.video_channel == "civicmedia:146"
    assert not resolved.video_warnings


async def test_embed_url_now_gets_the_title_from_the_video_page():
    with mock_session(_routes_144112()):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_144112_URL)

    assert resolved.title == TITLE_144112
    assert resolved.external_id == "civicmedia:144112"
    assert resolved.video_channel == "civicmedia:146"


async def test_embed_url_title_falls_back_to_html_title_without_og_title():
    routes = _routes_144112()
    routes[VIDEO_PAGE_URL] = FakeResponse(
        status=200,
        text="<html><head><title>Some Meeting</title></head></html>",
        url=VIDEO_PAGE_URL,
    )
    with mock_session(routes):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_144112_URL)

    assert resolved.title == "Some Meeting"


async def test_video_page_fetch_failure_leaves_embed_resolve_intact():
    routes = _routes_144112()
    routes[VIDEO_PAGE_URL] = FakeResponse(status=500, text="", url=VIDEO_PAGE_URL)
    with mock_session(routes):
        resolved = await CivicMediaAssetFinder().resolve(EMBED_144112_URL)

    assert resolved.title is None
    assert resolved.video_url and "videoId=144112" in resolved.video_url
    assert resolved.video_channel == "civicmedia:146"


async def test_refresh_playlist_url_works_from_a_video_page_url():
    with mock_session(_routes_144112()):
        fresh = await refresh_playlist_url(VIDEO_PAGE_URL)

    assert fresh and "videoId=144112" in fresh
