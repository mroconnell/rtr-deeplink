from app.platforms.escribe import EscribeAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG.md's "zero test coverage" note). PAGE_URL/VTT_URL below are the
# real Bakersfield, CA meeting this adapter's agenda-timestamp and
# jurisdiction-fallback support were both built against 2026-08-08/09 --
# see BACKLOG_DONE.md.

PAGE_URL = (
    "https://pub-bakersfield.escribemeetings.com/Meeting.aspx"
    "?Id=981f78d7-8211-4b4b-b066-5f93b4fd5e74&Agenda=Agenda&lang=English"
)
VTT_URL = (
    "https://video.isilive.ca/bakersfield/"
    "iSiLIVE%20Encoder%20760_CCM330_2026-07-15-06-04.mp4.vtt"
)


async def test_resolve_real_bakersfield_meeting():
    html = load_fixture("escribe", "bakersfield_ccm330_page.html")
    vtt = load_fixture("escribe", "bakersfield_ccm330_captions.vtt")

    routes = {
        PAGE_URL: FakeResponse(status=200, text=html, url=PAGE_URL),
        VTT_URL: FakeResponse(status=200, text=vtt, url=VTT_URL),
    }

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(PAGE_URL)

    assert result.platform == "escribe"
    assert result.title == "City Council Meeting 330"
    assert result.date == "2026-07-15"
    # Real bug fixed 2026-08-09: the page body has no "City of X" phrase
    # (just a plain address), so jurisdiction used to silently come back
    # None -- now falls back to the pub-{city}.escribemeetings.com
    # subdomain. State appended 2026-08-12 via the shared
    # jurisdiction_enrich module -- "Bakersfield" is a real, nationally-
    # unique incorporated place name.
    assert result.jurisdiction == "Bakersfield, CA"
    assert result.video_url == (
        "https://cdn1.isilive.ca/vod/_definst_/mp4:bakersfield/"
        "iSiLIVE%20Encoder%20760_CCM330_2026-07-15-06-04.mp4/playlist.m3u8"
    )
    assert result.video_format == "m3u8"
    assert len(result.segments) == 25  # the trimmed real VTT fixture's cue count
    assert result.segments[0].text == "The 330 p. m. meeting of the Bakersfield City Council"

    # Real bug fixed 2026-08-09: EscribeAssetFinder never extracted
    # agenda_items at all, despite the real page having exactly the
    # structured markup needed for it (see BACKLOG_DONE.md). Only 4 of
    # the page's 10 real .AgendaItem entries have a matching video.
    # Bookmarks timestamp -- the other 6 (procedural items like "ROLL
    # CALL") are deliberately omitted rather than given a fake time.
    assert len(result.agenda_items) == 4
    assert [item.text for item in result.agenda_items] == [
        "Non-Agenda Item Public Statements",
        "Public Employee Performance Evaluation - City Manager; Closed Session "
        "pursuant to Government Code Section 54957(b)(1) / 54957.6",
        "CLOSED SESSION ACTION",
        "ADJOURNMENT",
    ]
    first = result.agenda_items[0]
    assert first.start == 1753.667
    assert first.end == 2136.595


async def test_jurisdiction_from_subdomain_used_only_as_fallback():
    assert EscribeAssetFinder._jurisdiction_from_subdomain(
        "https://pub-bakersfield.escribemeetings.com/Meeting.aspx?Id=1"
    ) == "Bakersfield"
    assert EscribeAssetFinder._jurisdiction_from_subdomain(
        "https://pub-simi-valley.escribemeetings.com/Meeting.aspx?Id=1"
    ) == "Simi Valley"
    assert EscribeAssetFinder._jurisdiction_from_subdomain(
        "https://example.com/Meeting.aspx?Id=1"
    ) is None


async def test_extract_agenda_items_handles_missing_bookmarks_array():
    html = "<html><body><div class='AgendaItem'><div class='AgendaItemTitle'>" \
        "<a href=\"javascript:SelectItem(1);\">Roll Call</a></div></div></body></html>"
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    assert EscribeAssetFinder._extract_agenda_items(soup, html) == []


async def test_extract_agenda_items_handles_malformed_bookmarks_json():
    html = (
        "<script>var video = { Bookmarks : [{\"AgendaItemId\":1,not-json},"
        "</script>"
        "<div class='AgendaItem'><div class='AgendaItemTitle'>"
        "<a href=\"javascript:SelectItem(1);\">Roll Call</a></div></div>"
    )
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    assert EscribeAssetFinder._extract_agenda_items(soup, html) == []


async def test_extract_agenda_items_skips_items_without_a_matching_bookmark():
    html = (
        '<script>var video = { Bookmarks : [{"AgendaItemId":2,"TimeStart":1000,"TimeEnd":2000}],'
        "</script>"
        "<div class='AgendaItem'><div class='AgendaItemTitle'>"
        "<a href=\"javascript:SelectItem(1);\">Roll Call</a></div></div>"
        "<div class='AgendaItem'><div class='AgendaItemTitle'>"
        "<a href=\"javascript:SelectItem(2);\">Public Comment</a></div></div>"
    )
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    items = EscribeAssetFinder._extract_agenda_items(soup, html)
    assert len(items) == 1
    assert items[0].text == "Public Comment"
    assert items[0].start == 1.0
    assert items[0].end == 2.0


async def test_resolve_no_video_integration_returns_warning_not_crash():
    url = "https://pub-example.escribemeetings.com/Meeting.aspx?Id=2"
    html = "<html><head><title>Untitled - January 1, 2026</title></head><body>No player here.</body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.platform == "escribe"
    assert result.video_url is None
    assert result.jurisdiction == "Example"
    assert any("no video integration found" in w.lower() for w in result.video_warnings)


async def test_resolve_video_present_but_no_caption_file_found():
    url = "https://pub-example.escribemeetings.com/Meeting.aspx?Id=3"
    html = (
        '<html><head><title>Meeting - January 1, 2026</title></head><body>'
        '<div id="isi_player" data-client_id="example" data-stream_name="clip.mp4"></div>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}
    for suffix in [None, "fr", "es", "zh", "zh-hant", "tl"]:
        vtt_url = "https://video.isilive.ca/example/clip.mp4" + (f".{suffix}" if suffix else "") + ".vtt"
        routes[vtt_url] = FakeResponse(status=404)

    with mock_session(routes):
        result = await EscribeAssetFinder().resolve(url)

    assert result.video_url is not None
    assert result.segments == []
    assert any("no caption file was found" in w.lower() for w in result.transcript_warnings)
