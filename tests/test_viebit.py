from app.platforms.viebit import ViebitAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

PAGE_URL = "https://councilnyc.viebit.com/vod/?s=true&v=NYCC-250-8-1_260722-110636.mp4"
VTT_URL = "https://vbfast-vod.viebit.com/counciln/hFWIQkuFLuWGb0mw/NYCC-250-8-1_260722-110636.vtt"


async def test_resolve_real_nyc_council_meeting():
    # Real page + captions fetched live 2026-08-08 from the actual Viebit
    # URL a real NYC Council Legistar video link's redirect chain lands on
    # (see tests/test_legistar.py's NYC delegation tests for that chain) --
    # the first real eScribe-adjacent... no, first real Viebit sample this
    # adapter was built against. 1748 raw VTT cues, ALL-CAPS, two-line
    # rolling-caption style.
    html = load_fixture("viebit", "nycc_vod_page.html")
    vtt = load_fixture("viebit", "nycc_captions.vtt")

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        VTT_URL: FakeResponse(status=200, text=vtt, url=VTT_URL),
    }

    with mock_session(routes):
        result = await ViebitAssetFinder().resolve(PAGE_URL)

    assert result.platform == "viebit"
    assert result.title == "NYCC-250-8-1_260722-110636.mp4"
    assert result.jurisdiction == "New York City, NY"
    assert result.date == "2026-07-22"
    # Real fix 2026-08-12: the raw master.m3u8 is CDN-gated (403s even with
    # realistic headers, confirmed live in production) -- video_url is now
    # always rebuilt as the confirmed-safe-to-iframe /embed/vod?v={id} path
    # on the fetched page's own origin, not the raw HLS manifest.
    assert (
        result.video_url == "https://councilnyc.viebit.com/embed/vod?v=hFWIQkuFLuWGb0mw"
    )
    assert result.video_format == "viebit"
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []
    # Real dedupe_rollup_cues()/normalize_shouting_caption() should have
    # already collapsed the raw 1748 two-line-rolling cues down and
    # de-shouted the ALL-CAPS source text -- pinning both behaviors
    # together against this real sample, not just checking segment count.
    assert 800 < len(result.segments) < 900
    full_text = " ".join(s.text for s in result.segments)
    assert full_text != full_text.upper(), (
        "transcript should not still be all-uppercase"
    )
    assert "council" in full_text.lower()


async def test_resolve_vtt_fetch_failure_is_logged(caplog):
    # 2026-08-28: _fetch_vtt()'s non-200 branch used to be silent.
    html = load_fixture("viebit", "nycc_vod_page.html")
    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        VTT_URL: FakeResponse(status=404, url=VTT_URL),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await ViebitAssetFinder().resolve(PAGE_URL)

    assert result.segments == []
    assert any("Viebit VTT fetch got HTTP 404" in r.message for r in caplog.records)


async def test_resolve_missing_page_config_returns_warning_not_crash():
    url = "https://councilnyc.viebit.com/vod/?v=missing"
    html = "<html><body>Not the right shape.</body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await ViebitAssetFinder().resolve(url)

    assert result.platform == "viebit"
    assert result.video_url is None
    assert any("could not find" in w.lower() for w in result.video_warnings)


async def test_resolve_ringwood_nj_not_mistagged_as_nyc():
    # WO-71 (2026-08-30) regression test. No real Ringwood Viebit page
    # fixture has been captured yet (this is a synthetic pageConfig, same
    # shape already confirmed real from the NYC fixture above -- see this
    # repo's synthetic-test convention), but the facts pinned here are
    # real: fetching https://redtaperecordings.com/m/new-york-ny-2026-08-19
    # -8-18-26-council-meeting-mp4 live (2026-08-30) showed it was tagged
    # "New York, NY" while its own "View original source" link points to
    # https://ringwoodtv.viebit.com/watch?hash=Qb9n3sr6XRM44mOD -- and that
    # host is confirmed to be the Borough of Ringwood, NJ's own official
    # Viebit channel (ringwoodnj.net links it as "Ringwood TV"). Before this
    # fix, ViebitAssetFinder hardcoded "New York City, NY" for every Viebit
    # URL; this pins that a non-NYC tenant now resolves its own real
    # jurisdiction via jurisdiction_enrich's domain registry instead.
    url = "https://ringwoodtv.viebit.com/watch?hash=Qb9n3sr6XRM44mOD"
    html = (
        "<html><body><script>"
        'var pageConfig = {"video":{"id":"y","title":"Council Meeting",'
        '"dateCreated":1784734559,'
        '"src":[{"storage":"https://vbfast-vod.viebit.com/otfp/y/",'
        '"url":"video,master.m3u8?fmp4=1","type":"application/x-mpegurl"}],'
        '"textTracks":[]},"hasAccess":true};'
        "</script></body></html>"
    )

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await ViebitAssetFinder().resolve(url)

    assert result.jurisdiction == "Ringwood, NJ"
    assert result.jurisdiction != "New York City, NY"


async def test_resolve_unknown_viebit_tenant_leaves_jurisdiction_unset():
    # No real example of a THIRD Viebit tenant (beyond councilnyc and
    # ringwoodtv) has turned up yet. Per this repo's "don't claim a data
    # path works without a positive example" convention, an unrecognized
    # netloc must resolve with jurisdiction=None rather than either
    # inheriting the old NYC hardcode (the WO-71 bug this fix closes) or
    # guessing a jurisdiction from the subdomain text.
    url = "https://someothertown.viebit.com/watch?hash=abc"
    html = (
        "<html><body><script>"
        'var pageConfig = {"video":{"id":"z","title":"Meeting",'
        '"dateCreated":1784734559,'
        '"src":[{"storage":"https://vbfast-vod.viebit.com/otfp/z/",'
        '"url":"video,master.m3u8?fmp4=1","type":"application/x-mpegurl"}],'
        '"textTracks":[]},"hasAccess":true};'
        "</script></body></html>"
    )

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await ViebitAssetFinder().resolve(url)

    assert result.jurisdiction is None


async def test_resolve_no_caption_track_falls_back_to_warning():
    url = "https://councilnyc.viebit.com/vod/?v=nocaptions"
    html = (
        "<html><body><script>"
        'var pageConfig = {"video":{"id":"x","title":"No Captions Meeting",'
        '"dateCreated":1784734559,'
        '"src":[{"storage":"https://vbfast-vod.viebit.com/otfp/x/",'
        '"url":"video,master.m3u8?fmp4=1","type":"application/x-mpegurl"}],'
        '"textTracks":[]},"hasAccess":true};'
        "</script></body></html>"
    )

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await ViebitAssetFinder().resolve(url)

    assert result.video_url == "https://councilnyc.viebit.com/embed/vod?v=x"
    assert result.video_format == "viebit"
    assert result.segments == []
    assert any("no captions found" in w.lower() for w in result.transcript_warnings)


async def test_format_date_handles_missing_and_invalid_values():
    assert ViebitAssetFinder._format_date(None) is None
    assert ViebitAssetFinder._format_date(0) is None
    assert ViebitAssetFinder._format_date("not-a-number") is None
    assert ViebitAssetFinder._format_date(1784734559) == "2026-07-22"


def test_build_embed_url_rebuilds_confirmed_safe_path():
    # Real fix 2026-08-12: always rebuilds /embed/vod?v={id} on the fetched
    # page's own origin, regardless of whether the fetch landed on the
    # outer /vod/?v=... page or /embed/vod?v=... directly -- only the
    # latter is confirmed to have no X-Frame-Options restriction.
    assert (
        ViebitAssetFinder._build_embed_url(
            "https://councilnyc.viebit.com/vod/?s=true&v=x.mp4", "abc123"
        )
        == "https://councilnyc.viebit.com/embed/vod?v=abc123"
    )
    assert (
        ViebitAssetFinder._build_embed_url("https://councilnyc.viebit.com/vod/", None)
        is None
    )
    assert ViebitAssetFinder._build_embed_url("not-a-real-url", "abc123") is None
