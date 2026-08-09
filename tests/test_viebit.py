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
    assert result.date == "2026-07-22"
    assert result.video_url == (
        "https://vbfast-vod.viebit.com/otfp/counciln/hFWIQkuFLuWGb0mw/"
        "NYCC-250-8-1_260722-110636,master.m3u8?fmp4=1"
    )
    assert result.video_format == "m3u8"
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []
    # Real dedupe_rollup_cues()/normalize_shouting_caption() should have
    # already collapsed the raw 1748 two-line-rolling cues down and
    # de-shouted the ALL-CAPS source text -- pinning both behaviors
    # together against this real sample, not just checking segment count.
    assert 800 < len(result.segments) < 900
    full_text = " ".join(s.text for s in result.segments)
    assert full_text != full_text.upper(), "transcript should not still be all-uppercase"
    assert "council" in full_text.lower()


async def test_resolve_missing_page_config_returns_warning_not_crash():
    url = "https://councilnyc.viebit.com/vod/?v=missing"
    html = "<html><body>Not the right shape.</body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await ViebitAssetFinder().resolve(url)

    assert result.platform == "viebit"
    assert result.video_url is None
    assert any("could not find" in w.lower() for w in result.video_warnings)


async def test_resolve_no_caption_track_falls_back_to_warning():
    url = "https://councilnyc.viebit.com/vod/?v=nocaptions"
    html = (
        "<html><body><script>"
        "var pageConfig = {\"video\":{\"id\":\"x\",\"title\":\"No Captions Meeting\","
        "\"dateCreated\":1784734559,"
        "\"src\":[{\"storage\":\"https://vbfast-vod.viebit.com/otfp/x/\","
        "\"url\":\"video,master.m3u8?fmp4=1\",\"type\":\"application/x-mpegurl\"}],"
        "\"textTracks\":[]},\"hasAccess\":true};"
        "</script></body></html>"
    )

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await ViebitAssetFinder().resolve(url)

    assert result.video_url == "https://vbfast-vod.viebit.com/otfp/x/video,master.m3u8?fmp4=1"
    assert result.segments == []
    assert any("no captions found" in w.lower() for w in result.transcript_warnings)


async def test_format_date_handles_missing_and_invalid_values():
    assert ViebitAssetFinder._format_date(None) is None
    assert ViebitAssetFinder._format_date(0) is None
    assert ViebitAssetFinder._format_date("not-a-number") is None
    assert ViebitAssetFinder._format_date(1784734559) == "2026-07-22"
