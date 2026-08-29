import pytest

from app.platforms.base import CalendarPageError, register
from app.platforms.granicus import GranicusAssetFinder
from app.platforms.legistar import LegistarAssetFinder
from app.platforms.viebit import ViebitAssetFinder
from app.platforms.youtube import YouTubeAssetFinder
from app.platforms import youtube_channel

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _register_granicus():
    # resolve_via_platform() looks up the registered finder by platform
    # name -- register the real GranicusAssetFinder/ViebitAssetFinder so
    # delegation exercises real parsing, not a stub.
    register(GranicusAssetFinder())
    register(ViebitAssetFinder())


async def test_calendar_page_raises_pick_list_from_real_maricopa_calendar():
    # Real maricopa.legistar.com/Calendar.aspx, fetched live 2026-08-07 --
    # the exact real site BACKLOG_DONE.md documents (20 video links across
    # 47 rows at the time it was originally verified).
    url = "https://maricopa.legistar.com/Calendar.aspx"
    html = load_fixture("legistar", "maricopa_calendar.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await LegistarAssetFinder().resolve(url)

    candidates = exc_info.value.candidates
    assert len(candidates) > 1
    assert all(
        "granicus.com" in c["url"] or "Video.aspx" in c["url"] for c in candidates
    )
    assert all(c["title"] and c["date"] for c in candidates)


async def test_single_meeting_delegates_to_granicus():
    # A MeetingDetail-style page with exactly one video link, which
    # redirects (per the real confirmed Maricopa pattern) straight to a
    # Granicus player/clip URL -- delegation should hand off to a real
    # GranicusAssetFinder.resolve() call on that URL, not just detect it.
    meeting_url = "https://maricopa.legistar.com/MeetingDetail.aspx?ID=1"
    video_aspx = (
        "https://maricopa.legistar.com/Video.aspx?Mode=Granicus&ID1=1504&Mode2=Video"
    )
    granicus_url = "https://cityofmaricopa.granicus.com/player/clip/1504"

    meeting_html = (
        "<html><body><table><tr><td>City Council Meeting</td>"
        "<td>4/8/2026</td></tr></table>"
        f"<a class=\"videolink\" onclick=\"window.open('{video_aspx}','video');"
        'return false;">Video</a></body></html>'
    )
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        video_aspx: FakeResponse(status=200, text="", url=granicus_url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://cityofmaricopa.granicus.com/videos/1504/captions.vtt": FakeResponse(
            status=404
        ),
        "https://cityofmaricopa.granicus.com/AgendaViewer.php?clip_id=1504&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(meeting_url)

    assert result.platform == "granicus"
    assert result.external_id == "granicus:cityofmaricopa.granicus.com:1504"


async def test_single_meeting_delegation_populates_meeting_body():
    # 2026-08-28: legistar.py's own page <title> already carried the real
    # governing-body name ("Meeting of {body}") -- it was only ever used
    # as a title fallback, never surfaced as ResolvedMeeting.meeting_body
    # (the field Granicus's RSS channel title already feeds, see
    # archive/db/crud.py's precedence comment). Wired up on all three
    # resolve() paths; this covers the primary a.videolink delegation one.
    meeting_url = "https://maricopa.legistar.com/MeetingDetail.aspx?ID=1"
    video_aspx = (
        "https://maricopa.legistar.com/Video.aspx?Mode=Granicus&ID1=1504&Mode2=Video"
    )
    granicus_url = "https://cityofmaricopa.granicus.com/player/clip/1504"

    meeting_html = (
        "<html><head><title>The City of Maricopa - Meeting of City Council "
        "on 4/8/2026 at 6:00 PM</title></head><body>"
        f"<a class=\"videolink\" onclick=\"window.open('{video_aspx}','video');"
        'return false;">Video</a></body></html>'
    )
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        video_aspx: FakeResponse(status=200, text="", url=granicus_url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://cityofmaricopa.granicus.com/videos/1504/captions.vtt": FakeResponse(
            status=404
        ),
        "https://cityofmaricopa.granicus.com/AgendaViewer.php?clip_id=1504&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(meeting_url)

    assert result.platform == "granicus"
    assert result.meeting_body == "City Council"


def test_find_video_links_ignores_audio_only_variants():
    # Real bug fixed 2026-08-12, confirmed live on Charlotte, NC: some
    # Legistar instances render three separate a.videolink anchors per real
    # video (Mode2=Video, Mode2=Audio, Mode2=AudioDownload), all sharing
    # the same "Video.aspx" substring the onclick check requires -- a
    # single real meeting was miscounted as 3 video links and misclassified
    # as a calendar page. Maricopa (the original reference case) only ever
    # emits the Mode2=Video anchor, which is why this wasn't caught earlier.
    from bs4 import BeautifulSoup

    html = (
        "<html><body><table><tr><td>City Council Business Meeting</td>"
        "<td>6/22/2026</td></tr></table>"
        "<a class=\"videolink\" onclick=\"window.open('Video.aspx?Mode=Granicus&ID1=3692&Mode2=Video','video');return false;\">Video</a>"
        "<a class=\"videolink\" onclick=\"window.open('Video.aspx?Mode=Granicus&ID1=3692&Mode2=Audio','video');return false;\">Audio</a>"
        "<a class=\"videolink\" onclick=\"window.open('Video.aspx?Mode=Granicus&ID1=3692&Mode2=AudioDownload','video');return false;\">Audio Download</a>"
        "</body></html>"
    )
    soup = BeautifulSoup(html, "html.parser")

    links = LegistarAssetFinder()._find_video_links(
        soup, "https://charlottenc.legistar.com/MeetingDetail.aspx?ID=1"
    )

    assert len(links) == 1
    assert "Mode2=Video" in links[0]["url"]


async def test_charlotte_single_meeting_with_audio_links_delegates_to_granicus():
    # Same bug as above, end-to-end against the real fetched Charlotte
    # page (tests/fixtures/legistar/charlotte_meeting_audio_download.html)
    # -- confirms the fix holds against real markup, not just a synthetic
    # minimal case.
    meeting_url = (
        "https://charlottenc.legistar.com/MeetingDetail.aspx?ID=1365278"
        "&GUID=E6E474AC-A2A9-4CE4-BCF0-5B118522E3BE&Options=info|"
    )
    video_aspx = (
        "https://charlottenc.legistar.com/Video.aspx?Mode=Granicus&ID1=3692&Mode2=Video"
    )
    granicus_url = "https://charlottenc.granicus.com/player/clip/3692"

    meeting_html = load_fixture("legistar", "charlotte_meeting_audio_download.html")
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        video_aspx: FakeResponse(status=200, text="", url=granicus_url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://charlottenc.granicus.com/videos/3692/captions.vtt": FakeResponse(
            status=404
        ),
        "https://charlottenc.granicus.com/AgendaViewer.php?clip_id=3692&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(meeting_url)

    # Real bug this regresses against: without the fix, this raised
    # CalendarPageError instead of ever reaching a real resolve.
    assert result.platform == "granicus"
    assert result.external_id == "granicus:charlottenc.granicus.com:3692"


async def test_fallback_delegation_failure_is_logged_and_degrades_honestly(caplog):
    # No a.videolink, no YouTube link -- forces _try_fallback_video_link()
    # into find_platform_link()'s delegation branch. The delegated
    # Granicus page's .text() call raises a plain (non-ClientError)
    # exception, which GranicusAssetFinder._fetch_page()'s own retry logic
    # doesn't catch -- exercising legistar.py's `except Exception` path
    # (2026-08-28: previously silent) rather than the CalendarPageError
    # one right above it.
    url = "https://example.legistar.com/MeetingDetail.aspx?ID=1"
    granicus_url = "https://example.granicus.com/player/clip/1"
    html = (
        "<html><head><title>City Council Meeting</title></head><body>"
        f'<a href="{granicus_url}">Watch here</a>'
        "</body></html>"
    )
    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        granicus_url: FakeResponse(
            status=200, text_raises=ValueError("boom"), url=granicus_url
        ),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await LegistarAssetFinder().resolve(url)

    assert result.video_warnings == ["No video link found on this Legistar page."]
    assert any(
        "Legistar delegation to granicus failed" in r.message for r in caplog.records
    )


async def test_nyc_calendar_page_raises_pick_list_via_telerik_onclick():
    # Real legistar.council.nyc.gov/Calendar.aspx, fetched live 2026-08-08.
    # NYC's video links use onclick="OpenTelerikWindow('Video.aspx?Mode=
    # Auto&URL={base64}&Mode2=Video', ...)" instead of every other Legistar
    # city's plain window.open(...) -- confirmed real, on-domain candidates
    # now come back instead of zero (the pre-fix behavior: _find_video_links
    # simply never matched this onclick shape at all).
    url = "https://legistar.council.nyc.gov/Calendar.aspx"
    html = load_fixture("legistar", "nyc_council_calendar.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await LegistarAssetFinder().resolve(url)

    candidates = exc_info.value.candidates
    assert len(candidates) > 1
    assert all("Video.aspx?Mode=Auto" in c["url"] for c in candidates)
    assert all(c["title"] and c["date"] for c in candidates)


async def test_nyc_single_meeting_delegates_to_viebit():
    # Real chain confirmed live 2026-08-08: Video.aspx?Mode=Auto&URL=
    # {base64} does a real server-side redirect straight through to a
    # Viebit /embed/vod URL -- LegistarAssetFinder's existing
    # allow_redirects=True fetch already lands there directly, no
    # base64-decoding needed in this adapter itself.
    meeting_url = "https://legistar.council.nyc.gov/MeetingDetail.aspx?ID=1"
    video_aspx = (
        "https://legistar.council.nyc.gov/Video.aspx?Mode=Auto&URL="
        "aHR0cHM6Ly9jb3VuY2lsbnljLnZpZWJpdC5jb20vdm9kLz9zPXRydWUmdj1OWUND"
        "LTI1MC04LTFfMjYwNzIyLTExMDYzNi5tcDQ%3d&Mode2=Video"
    )
    viebit_url = (
        "https://councilnyc.viebit.com/embed/vod?v=hFWIQkuFLuWGb0mw&s=true&d=false"
    )
    vtt_url = "https://vbfast-vod.viebit.com/counciln/hFWIQkuFLuWGb0mw/NYCC-250-8-1_260722-110636.vtt"

    meeting_html = (
        "<html><body><table><tr><td>Subcommittee on Landmarks</td>"
        "<td>7/22/2026</td></tr></table>"
        f'<a class="videolink" onclick="OpenTelerikWindow(\'{video_aspx}\','
        "'video');return false;\">Video</a></body></html>"
    )
    viebit_html = load_fixture("viebit", "nycc_vod_page.html")
    vtt = load_fixture("viebit", "nycc_captions.vtt")

    routes = {
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        video_aspx: FakeResponse(status=200, text="", url=viebit_url),
        viebit_url: FakeResponse(status=200, text=viebit_html, url=viebit_url),
        vtt_url: FakeResponse(status=200, text=vtt, url=vtt_url),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(meeting_url)

    assert result.platform == "viebit"
    assert result.video_url is not None
    assert len(result.segments) > 800


def test_is_legistar_domain_recognizes_nyc_custom_domain():
    # Real bug fixed 2026-08-08: this used to be a bare "legistar.com"
    # substring check, which was False for NYC's own
    # legistar.council.nyc.gov pages -- meaning resolve() would treat NYC's
    # own domain as "not Legistar" and send it straight back into
    # resolve_via_platform(), which re-detects it as "legistar" and would
    # have recursed on the same URL instead of ever reaching
    # _find_video_links.
    assert LegistarAssetFinder._is_legistar_domain(
        "https://legistar.council.nyc.gov/Calendar.aspx"
    )
    assert LegistarAssetFinder._is_legistar_domain(
        "https://maricopa.legistar.com/MeetingDetail.aspx"
    )
    assert not LegistarAssetFinder._is_legistar_domain(
        "https://councilnyc.viebit.com/embed/vod?v=x"
    )


async def test_nyc_meeting_title_overrides_viebits_raw_filename_title():
    # Real bug fixed 2026-08-09: ViebitAssetFinder's own title comes from
    # Viebit's `video.title` field, confirmed live to just be the raw
    # uploaded filename ("NYCC-250-8-2_251218-120823.mp4") -- not a human
    # title. The NYC MeetingDetail.aspx page's own <title> tag has real
    # info ("The New York City Council - Meeting of Committee on Finance
    # on 12/18/2025 at 11:30 AM"), confirmed live on two real samples --
    # this should now be preferred whenever the delegated title looks like
    # a raw filename.
    meeting_url = "https://legistar.council.nyc.gov/MeetingDetail.aspx?ID=1362373"
    video_aspx = (
        "https://legistar.council.nyc.gov/Video.aspx?Mode=Auto&URL="
        "aHR0cHM6Ly9jb3VuY2lsbnljLnZpZWJpdC5jb20vdm9kLz9zPXRydWUmdj1OWUND"
        "LTI1MC04LTFfMjYwNzIyLTExMDYzNi5tcDQ%3d&Mode2=Video"
    )
    viebit_url = (
        "https://councilnyc.viebit.com/embed/vod?v=hFWIQkuFLuWGb0mw&s=true&d=false"
    )
    vtt_url = "https://vbfast-vod.viebit.com/counciln/hFWIQkuFLuWGb0mw/NYCC-250-8-1_260722-110636.vtt"

    meeting_html = (
        "<html><head><title>The New York City Council - Meeting of "
        "Committee on Finance on 12/18/2025 at 11:30 AM</title></head>"
        "<body><table><tr><td>Video</td></tr></table>"
        f'<a class="videolink" onclick="OpenTelerikWindow(\'{video_aspx}\','
        "'video');return false;\">Video</a></body></html>"
    )
    viebit_html = load_fixture("viebit", "nycc_vod_page.html")
    vtt = load_fixture("viebit", "nycc_captions.vtt")

    routes = {
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        video_aspx: FakeResponse(status=200, text="", url=viebit_url),
        viebit_url: FakeResponse(status=200, text=viebit_html, url=viebit_url),
        vtt_url: FakeResponse(status=200, text=vtt, url=vtt_url),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(meeting_url)

    # Confirm the fixture's own delegated title really is the raw-filename
    # shape this override exists for, not some other unrelated value.
    assert result.title == "Committee on Finance"
    # jurisdiction is NOT overridden here either, same "already have a real
    # answer" shape as date below -- ViebitAssetFinder now hardcodes its
    # own confirmed-correct "New York City, NY" (2026-08-10, see
    # BACKLOG_DONE.md), so the page title's "New York City Council" (a
    # legislative-body name, not the city+state format used elsewhere)
    # never gets a chance to fill in what's already a real, better value.
    assert result.jurisdiction == "New York City, NY"
    # date is NOT overridden here -- Viebit's own dateCreated (2026-07-22,
    # baked into this fixture) already resolved successfully, so the page
    # title's date (12/18/2025, from this test's deliberately mismatched
    # meeting_html) is only ever a fallback for a missing date, never a
    # silent replacement for one that's already there.
    assert result.date == "2026-07-22"


async def test_nyc_meeting_without_page_title_keeps_viebits_title_unchanged():
    # No <title> tag on the source page (matches every other existing
    # fixture in this file) -- _extract_page_meeting_info() returns None,
    # so the delegated platform's own title/date pass through completely
    # unchanged, even if title is the same raw-filename shape. jurisdiction
    # was never sourced from page_info here anyway -- ViebitAssetFinder
    # sets its own directly (2026-08-10).
    meeting_url = "https://legistar.council.nyc.gov/MeetingDetail.aspx?ID=1"
    video_aspx = (
        "https://legistar.council.nyc.gov/Video.aspx?Mode=Auto&URL="
        "aHR0cHM6Ly9jb3VuY2lsbnljLnZpZWJpdC5jb20vdm9kLz9zPXRydWUmdj1OWUND"
        "LTI1MC04LTFfMjYwNzIyLTExMDYzNi5tcDQ%3d&Mode2=Video"
    )
    viebit_url = (
        "https://councilnyc.viebit.com/embed/vod?v=hFWIQkuFLuWGb0mw&s=true&d=false"
    )
    vtt_url = "https://vbfast-vod.viebit.com/counciln/hFWIQkuFLuWGb0mw/NYCC-250-8-1_260722-110636.vtt"

    meeting_html = (
        "<html><body><table><tr><td>Video</td></tr></table>"
        f'<a class="videolink" onclick="OpenTelerikWindow(\'{video_aspx}\','
        "'video');return false;\">Video</a></body></html>"
    )
    viebit_html = load_fixture("viebit", "nycc_vod_page.html")
    vtt = load_fixture("viebit", "nycc_captions.vtt")

    routes = {
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        video_aspx: FakeResponse(status=200, text="", url=viebit_url),
        viebit_url: FakeResponse(status=200, text=viebit_html, url=viebit_url),
        vtt_url: FakeResponse(status=200, text=vtt, url=vtt_url),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(meeting_url)

    assert result.title == "NYCC-250-8-1_260722-110636.mp4"
    # jurisdiction still comes through even with no page_info to fall back
    # on -- ViebitAssetFinder now sets it directly (2026-08-10).
    assert result.jurisdiction == "New York City, NY"


def test_extract_page_meeting_info_parses_real_nyc_title_shapes():
    from bs4 import BeautifulSoup

    committee_soup = BeautifulSoup(
        "<title>The New York City Council - Meeting of Committee on Finance "
        "on 12/18/2025 at 11:30 AM</title>",
        "html.parser",
    )
    assert LegistarAssetFinder._extract_page_meeting_info(
        committee_soup, "https://legistar.council.nyc.gov/MeetingDetail.aspx?ID=1"
    ) == {
        "title": "Committee on Finance",
        "body": "Committee on Finance",
        "jurisdiction": "New York City Council",
        "date": "2025-12-18",
        "agenda_link": None,
    }

    full_council_soup = BeautifulSoup(
        "<title>The New York City Council - Meeting of City Council "
        "on 12/18/2025 at 1:30 PM</title>",
        "html.parser",
    )
    assert LegistarAssetFinder._extract_page_meeting_info(
        full_council_soup, "https://legistar.council.nyc.gov/MeetingDetail.aspx?ID=1"
    ) == {
        "title": "City Council",
        "body": "City Council",
        "jurisdiction": "New York City Council",
        "date": "2025-12-18",
        "agenda_link": None,
    }


def test_extract_page_meeting_info_returns_none_without_matching_title():
    from bs4 import BeautifulSoup

    no_title_soup = BeautifulSoup("<body>No title tag here.</body>", "html.parser")
    assert (
        LegistarAssetFinder._extract_page_meeting_info(
            no_title_soup, "https://example.legistar.com/MeetingDetail.aspx?ID=1"
        )
        is None
    )

    unrelated_title_soup = BeautifulSoup("<title>Meeting</title>", "html.parser")
    assert (
        LegistarAssetFinder._extract_page_meeting_info(
            unrelated_title_soup, "https://example.legistar.com/MeetingDetail.aspx?ID=1"
        )
        is None
    )


def test_extract_page_meeting_info_falls_back_to_rss_link_when_title_empty():
    from bs4 import BeautifulSoup

    # Real shape confirmed live 2026-08-10: Baltimore's Legistar instance.
    soup = BeautifulSoup(
        '<head><title></title><link rel="alternate" type="application/rss+xml" '
        'title="City of Baltimore - Meeting of Baltimore City Council on 10/20/2025 at 5:00 PM" /></head>',
        "html.parser",
    )
    assert LegistarAssetFinder._extract_page_meeting_info(
        soup, "https://baltimore.legistar.com/MeetingDetail.aspx?ID=1"
    ) == {
        "title": "Baltimore City Council",
        "body": "Baltimore City Council",
        "jurisdiction": "City of Baltimore, MD",
        "date": "2025-10-20",
        "agenda_link": None,
    }


def test_extract_page_meeting_info_fills_in_state_for_an_unambiguous_jurisdiction():
    # Real wiring confirmation: "New York City Council" (used above) stays
    # state-less because it's a genuine real collision -- this uses a
    # real, nationally-unique jurisdiction name instead to confirm the
    # enrichment step is actually reached, not just safely inert.
    # ("City of Baltimore" used to be the go-to example here too, until
    # baltimore.legistar.com became a confirmed domain -- see the RSS-link
    # test above, and jurisdiction_enrich's own tests, for that case now.)
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<title>The City of Chicago - Meeting of City Council on 1/2/2026 at 10:00 AM</title>",
        "html.parser",
    )
    info = LegistarAssetFinder._extract_page_meeting_info(
        soup, "https://chicago.legistar.com/MeetingDetail.aspx?ID=1"
    )
    assert info["jurisdiction"] == "City of Chicago, IL"


def test_extract_agenda_link_reads_real_mesa_page_shape():
    # Real shape confirmed live 2026-08-12 and re-confirmed 2026-08-13 on
    # a real Mesa, AZ meeting (mesa.legistar.com/MeetingDetail.aspx?
    # ID=1428059) -- see BACKLOG.md/BACKLOG_DONE.md.
    from bs4 import BeautifulSoup

    html = (
        '<span id="ctl00_ContentPlaceHolder1_lblAgendaX">Published agenda:</span>'
        '<a id="ctl00_ContentPlaceHolder1_hypAgenda" '
        'href="View.ashx?M=A&amp;ID=1428059&amp;GUID=C6D3581F-B224-4A1C-A59D-0885C238FD52">Agenda</a>'
    )
    soup = BeautifulSoup(html, "html.parser")
    link = LegistarAssetFinder._extract_agenda_link(
        soup, "https://mesa.legistar.com/MeetingDetail.aspx?ID=1428059"
    )
    assert (
        link
        == "https://mesa.legistar.com/View.ashx?M=A&ID=1428059&GUID=C6D3581F-B224-4A1C-A59D-0885C238FD52"
    )


def test_extract_agenda_link_returns_none_when_absent():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<span>No agenda link here.</span>", "html.parser")
    assert (
        LegistarAssetFinder._extract_agenda_link(
            soup, "https://example.legistar.com/MeetingDetail.aspx?ID=1"
        )
        is None
    )


def test_looks_like_raw_filename_matches_real_viebit_title():
    assert LegistarAssetFinder._looks_like_raw_filename(
        "NYCC-250-8-2_251218-120823.mp4"
    )
    assert not LegistarAssetFinder._looks_like_raw_filename("Committee on Finance")
    assert not LegistarAssetFinder._looks_like_raw_filename(None)


async def test_no_video_link_returns_warning_not_crash():
    url = "https://maricopa.legistar.com/MeetingDetail.aspx?ID=2"
    html = "<html><body>No video for this one.</body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    assert result.platform == "legistar"
    assert any("no video" in w.lower() for w in result.video_warnings)


async def test_falls_back_to_a_plain_youtube_link_when_no_videolink_found(monkeypatch):
    # Real gap confirmed live 2026-08-10: Baltimore's Legistar instance
    # (baltimore.legistar.com) has no a.videolink at all -- its real
    # recording is a plain <a href="https://youtu.be/...">Recording</a>
    # in an attachments table. _find_video_links() correctly finds
    # nothing there; the new fallback should still find the real video.
    url = "https://baltimore.legistar.com/MeetingDetail.aspx?ID=1"
    html = (
        "<html><body><table><tr><td>Attachments</td></tr></table>"
        '<a href="https://youtu.be/dQw4w9WgXcQ">Recording</a></body></html>'
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    def _fake_extract_info(video_id):
        return {
            "title": "City Council Hearing",
            "uploader": "CharmTV",
            "upload_date": "20251020",
        }

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    assert result.platform == "youtube"
    assert result.video_url == "https://www.youtube.com/embed/dQw4w9WgXcQ"
    # source_url stays the original Legistar page, not youtu.be -- same
    # convention every other delegation in this file already follows.
    assert result.source_url == url


async def test_fallback_extracts_jurisdiction_from_empty_title_via_rss_link(
    monkeypatch,
):
    # Real bug confirmed live 2026-08-10: Baltimore's Legistar instance
    # leaves <title> completely empty (unlike NYC's, which has the real
    # info directly in <title>) -- but the identical "{jurisdiction} -
    # Meeting of {body} on {date} at {time}" text is present in the
    # page's own RSS <link> tag, a standard Legistar template element.
    # Without this, jurisdiction fell through to YouTube's own uploader
    # field ("CharmTV Citizens' Hub", a real but wrong answer to "what
    # jurisdiction is this").
    url = "https://baltimore.legistar.com/MeetingDetail.aspx?ID=1"
    html = (
        "<html><head><title></title>"
        '<link rel="alternate" type="application/rss+xml" '
        'title="City of Baltimore - Meeting of Baltimore City Council on 10/20/2025 at 5:00 PM" />'
        "</head><body><table><tr><td>Attachments</td></tr></table>"
        '<a href="https://youtu.be/dQw4w9WgXcQ">Recording</a></body></html>'
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    def _fake_extract_info(video_id):
        return {
            "title": "City Council Hearing",
            "uploader": "CharmTV Citizens' Hub",
            "upload_date": "20251020",
        }

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    # Legistar's own page wins over YouTube's real-but-wrong uploader
    # field, even though that field wasn't empty -- the fallback path's
    # jurisdiction override is unconditional when page_info has one,
    # unlike the primary a.videolink delegation path.
    assert result.jurisdiction == "City of Baltimore, MD"
    assert result.date == "2025-10-20"


async def test_falls_back_to_a_plain_granicus_link_when_no_videolink_found():
    # Same real class of gap as the YouTube case above, but for any OTHER
    # platform this app already supports -- proves the fallback isn't
    # YouTube-specific, it's the same base.find_platform_link()
    # generic_fallback.py already uses for Austin, TX's Swagit link.
    url = "https://somecity.legistar.com/MeetingDetail.aspx?ID=1"
    granicus_url = "https://cityofmaricopa.granicus.com/player/clip/1504"
    html = (
        "<html><body><table><tr><td>Attachments</td></tr></table>"
        f'<a href="{granicus_url}">Watch the recording</a></body></html>'
    )
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://cityofmaricopa.granicus.com/videos/1504/captions.vtt": FakeResponse(
            status=404
        ),
        "https://cityofmaricopa.granicus.com/AgendaViewer.php?clip_id=1504&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    assert result.platform == "granicus"
    assert result.external_id == "granicus:cityofmaricopa.granicus.com:1504"
    assert result.source_url == url


async def test_no_video_link_with_only_a_same_page_skip_link_does_not_recurse():
    # Real bug, confirmed live 2026-08-12 on a real Columbus, OH meeting
    # (ID=1425378, reported by the user as a hang followed by a bogus
    # "invalid JSON" error): a page with no a.videolink and no YouTube
    # link, but a completely standard accessibility "skip to content"
    # anchor, used to recurse without bound -- urljoin() resolves
    # "#mainContent" back to this exact page's own URL, detect_platform()
    # classifies that URL as "legistar" again, and the fallback delegated
    # to LegistarAssetFinder.resolve() on the same page it was already
    # resolving, forever. Fixed at the root in base.find_platform_link()
    # (skips any candidate resolving to the same URL as page_url) plus
    # belt-and-suspenders here (exclude "legistar" too).
    url = "https://columbus.legistar.com/MeetingDetail.aspx?ID=1425378"
    html = (
        '<html><body><a href="#mainContent" class="skip-to-content">Skip to main content</a>'
        "<table><tr><td>Attachments</td></tr></table></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    assert result.platform == "legistar"
    assert result.video_warnings == ["No video link found on this Legistar page."]


# --------------------------------------------------------------------
# WO-30: the city-YouTube-channel fallback, for the four confirmed
# Legistar instances whose video column is structurally empty. The
# matching rules themselves are covered against real captured channel
# listings in tests/test_youtube_channel.py -- these tests cover the
# *wiring*: when it runs, what it overrides, and what it says about where
# the video came from.
# --------------------------------------------------------------------

# Synthetic page HTML, in this file's established style -- but every fact
# in it is real and independently verifiable: this is the exact <title>
# phoenix.legistar.com serves for that real meeting (fetched live
# 2026-08-21), and the "Not Available" anchor with no onclick at all is
# the real markup that instance renders in place of a video link on every
# meeting ever checked there.
_PHOENIX_HTML = (
    "<html><head><title>City of Phoenix - Meeting of City Council Formal "
    "Meeting on 7/1/2026 at 10:00 AM</title></head><body>"
    '<a class="videolink" id="ctl00_ContentPlaceHolder1_hypVideo" '
    'style="color:Gray;">Not Available</a>'
    "</body></html>"
)
_PHOENIX_URL = "https://phoenix.legistar.com/MeetingDetail.aspx?ID=1425831"

# Real entries, in the shape yt-dlp's flat channel listing returns them.
# Both are genuine videos on Phoenix's own channel.
_PHOENIX_LISTING = [
    {
        "id": "srjuXI5vGuw",
        "title": "Phoenix City Council Formal Meeting July 1, 2026",
        "duration": 10753,
        "live_status": "was_live",
    },
    {
        "id": "at8qFIkVIjk",
        "title": "Reading of The Declaration of Independence",
        "duration": 2016,
        "live_status": "was_live",
    },
]


def _stub_channel(monkeypatch, entries):
    monkeypatch.setattr(
        youtube_channel, "_list_channel", lambda channel_id: list(entries)
    )


def _stub_youtube(monkeypatch):
    def _fake_extract_info(video_id):
        return {
            "title": "Phoenix City Council Formal Meeting July 1, 2026",
            "uploader": "CityofPhoenixAZ",
            # Real values for this video: the livestream ran on the
            # meeting date, the VOD finished processing the next day.
            "upload_date": "20260702",
            "release_date": "20260701",
        }

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)


async def test_channel_fallback_finds_phoenixs_unlinked_recording(monkeypatch):
    # The exact pair BACKLOG.md recorded as the motivating example: a real
    # Phoenix meeting whose Legistar page says "Not Available", and the
    # real recording that only exists on the city's own YouTube channel.
    _stub_channel(monkeypatch, _PHOENIX_LISTING)
    _stub_youtube(monkeypatch)
    routes = {
        _PHOENIX_URL: FakeResponse(status=200, text=_PHOENIX_HTML, url=_PHOENIX_URL)
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(_PHOENIX_URL)

    assert result.platform == "youtube"
    assert result.video_url == "https://www.youtube.com/embed/srjuXI5vGuw"
    assert result.source_url == _PHOENIX_URL
    # Legistar's own page is authoritative for all three, over YouTube's
    # channel-name uploader and its upload date.
    assert result.title == "City Council Formal Meeting"
    assert result.date == "2026-07-01"
    assert result.jurisdiction == "City of Phoenix"


async def test_channel_fallback_says_where_the_video_came_from(monkeypatch):
    # Provenance has to be visible: a reader must be able to tell "we
    # matched this from the city's YouTube channel" apart from "the
    # meeting page linked this". Deliberately a video_warning and NOT
    # best_effort -- that flag renders as "this government website isn't
    # supported yet" (player.js), which would be false here, and would
    # also mis-route main.py's _unreadable_media_message().
    _stub_channel(monkeypatch, _PHOENIX_LISTING)
    _stub_youtube(monkeypatch)
    routes = {
        _PHOENIX_URL: FakeResponse(status=200, text=_PHOENIX_HTML, url=_PHOENIX_URL)
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(_PHOENIX_URL)

    assert result.best_effort is False
    warning = result.video_warnings[0]
    assert "CityofPhoenixAZ" in warning
    assert "Phoenix City Council Formal Meeting July 1, 2026" in warning
    assert "not linked from the meeting page" in warning


async def test_channel_fallback_declines_rather_than_matching_the_wrong_video(
    monkeypatch,
):
    # Same real channel, same real date, but the only candidate that day
    # is a different event entirely. Declining leaves exactly the
    # pre-existing honest message -- no regression, and no wrong
    # attribution, which is the outcome that actually matters here.
    _stub_channel(
        monkeypatch,
        [
            {
                "id": "at8qFIkVIjk",
                "title": "Reading of The Declaration of Independence July 1, 2026",
                "duration": 2016,
                "live_status": "was_live",
            }
        ],
    )
    _stub_youtube(monkeypatch)
    routes = {
        _PHOENIX_URL: FakeResponse(status=200, text=_PHOENIX_HTML, url=_PHOENIX_URL)
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(_PHOENIX_URL)

    assert result.platform == "legistar"
    assert result.video_url is None
    assert result.video_warnings == ["No video link found on this Legistar page."]


async def test_channel_fallback_does_not_run_for_an_unregistered_instance(monkeypatch):
    # Every other Legistar tenant keeps its existing behavior exactly --
    # the registry is a short, human-verified list, not a heuristic, so
    # nothing should even reach the network here.
    url = "https://charlottenc.legistar.com/MeetingDetail.aspx?ID=1"
    html = _PHOENIX_HTML.replace("City of Phoenix", "City of Charlotte")

    def _boom(channel_id):  # pragma: no cover - must never be called
        raise AssertionError("channel listing should not be fetched here")

    monkeypatch.setattr(youtube_channel, "_list_channel", _boom)
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    assert result.platform == "legistar"
    assert result.video_warnings == ["No video link found on this Legistar page."]


async def test_channel_fallback_never_pre_empts_a_link_the_page_does_carry(monkeypatch):
    # Baltimore is in the registry, but a minority of its meetings really
    # do carry their own "Recording" link -- those must keep using the
    # city's own answer (_try_fallback_video_link), never the matcher.
    url = "https://baltimore.legistar.com/MeetingDetail.aspx?ID=1"
    html = (
        "<html><head><title>City of Baltimore - Meeting of Public Health &amp; "
        "Environment Committee on 8/5/2026 at 10:00 AM</title></head><body>"
        '<a href="https://youtu.be/sfIH-uqHpNI">Recording</a></body></html>'
    )

    def _boom(channel_id):  # pragma: no cover - must never be called
        raise AssertionError("the page's own link should win over the matcher")

    monkeypatch.setattr(youtube_channel, "_list_channel", _boom)

    def _fake_extract_info(video_id):
        return {
            "title": "City Council Hearing: Public Health & Environment; August 5, 2026",
            "uploader": "CharmTV Citizens' Hub",
            # Real: CharmTV posted this recording on 2026-08-17, twelve
            # days after the meeting (confirmed live 2026-08-21).
            "upload_date": "20260817",
        }

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    assert result.video_url == "https://www.youtube.com/embed/sfIH-uqHpNI"
    # Real bug found and fixed in the same pass: this used to render as
    # 2026-08-17, YouTube's upload date, because the fallback path only
    # filled in the page's own date when the delegated one was empty.
    assert result.date == "2026-08-05"
