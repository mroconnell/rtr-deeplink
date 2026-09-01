"""Tests for the Municode Meetings adapter (app/platforms/municode_meetings.py).

Real fixtures (bristol_home.html, bristol_meeting_278.html,
hamburg_meeting_pc12.html, fairoaks_home.html) are raw-saved live pages,
fetched 2026-09-01 -- see tests/fixtures/municode_meetings/README.md for
what each one confirms and, for the one synthetic case
(`test_login_wall_iframe_is_treated_as_no_video`), why it's synthetic.
"""

import bs4
import pytest

from app.platforms.base import CalendarPageError, detect_platform, register
from app.platforms.municode_meetings import MunicodeMeetingsAssetFinder
from app.platforms.youtube import YouTubeAssetFinder
from app.platforms.vimeo import VimeoAssetFinder
from app.platforms.headless_browser import HeadlessBrowserUnavailable
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

BRISTOL_HOME = "https://bristol-ri.municodemeetings.com/"
BRISTOL_MEETING_278 = "https://bristol-ri.municodemeetings.com/bc-towncouncil/page/town-council-meeting-278"
HAMBURG_MEETING_PC12 = (
    "https://hamburg-mi.municodemeetings.com/bc-pc/page/planning-commission-meeting-12"
)
FAIROAKS_HOME = "https://fairoaksranch-tx.municodemeetings.com/"


@pytest.fixture(autouse=True)
def _register_delegates():
    register(YouTubeAssetFinder())
    register(VimeoAssetFinder())
    # The listing branch's single-candidate path re-dispatches a
    # same-tenant detail-page URL through resolve_via_platform(), which
    # needs this platform registered too (see module docstring).
    register(MunicodeMeetingsAssetFinder())


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    # VimeoAssetFinder.resolve_video_id() uses guarded_get(), which
    # resolves hostnames for real unless patched -- see test_vimeo.py's
    # identical fixture.
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


@pytest.fixture(autouse=True)
def _no_headless_captions(monkeypatch):
    # Keeps the Vimeo-delegation test below network-free/video-only --
    # see test_vimeo.py's identical fixture for the full reasoning.
    async def _unavailable(url, **kwargs):
        raise HeadlessBrowserUnavailable("no headless browser in tests")

    monkeypatch.setattr("app.platforms.vimeo.fetch_via_browser", _unavailable)


def _oembed_route(target: str, fixture: str) -> dict:
    from urllib.parse import quote

    url = "https://vimeo.com/api/oembed.json?url=" + quote(target, safe="")
    return {
        url: FakeResponse(
            status=200,
            text=load_fixture("municode_meetings", fixture),
            url=url,
        )
    }


def test_detect_platform_claims_municodemeetings_domain():
    assert detect_platform(BRISTOL_HOME) == "municode_meetings"
    assert detect_platform(BRISTOL_MEETING_278) == "municode_meetings"


async def test_real_bristol_homepage_raises_multi_candidate_pick_list():
    # Real, raw-saved live page -- bristol-ri.municodemeetings.com/,
    # fetched 2026-09-01. 25 meeting rows, 4 with a populated
    # views-field-field-video-link cell -- this is the fixture that
    # answers this adapter's own "does a real homepage ever list more
    # than one video row" question live (see module docstring). Every
    # one of the 4 populated cells here holds a *relative* link to a
    # same-tenant detail page, not a direct video URL.
    html = load_fixture("municode_meetings", "bristol_home.html")
    routes = {BRISTOL_HOME: FakeResponse(status=200, text=html, url=BRISTOL_HOME)}

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await MunicodeMeetingsAssetFinder().resolve(BRISTOL_HOME)

    candidates = exc_info.value.candidates
    assert len(candidates) == 4
    assert exc_info.value.jurisdiction_hint == "Bristol, RI"

    dated = {c["date"]: c for c in candidates}
    assert set(dated) == {"2026-08-19", "2026-06-24", "2026-06-03", "2026-05-13"}

    row_278 = next(
        c for c in candidates if c["url"].endswith("town-council-meeting-278")
    )
    assert row_278["title"] == "Town Council Meeting"
    assert row_278["date"] == "2026-08-19"
    # A relative href resolved against the homepage's own URL, not left
    # as a bare path -- and NOT the final video URL, since building this
    # list never fetches each row's own detail page (see module
    # docstring's "not pre-validated" section).
    assert row_278["url"] == BRISTOL_MEETING_278
    # Real, confirmed agenda/packet shape: HTML rendition preferred over
    # the parallel PDF rendition, distinguished by the ip=True/ip=False
    # query flag on the adaHtmlDocument viewer link.
    assert row_278["agenda_link"] == (
        "https://meetings.municode.com/adaHtmlDocument/index"
        "?cc=BRISTOLRI&me=e12d1c0b0b3041689df7f26d5aaf3f49&ip=False"
    )
    assert row_278["packet_link"] == (
        "https://meetings.municode.com/adaHtmlDocument/index"
        "?cc=BRISTOLRI&me=e12d1c0b0b3041689df7f26d5aaf3f49&ip=True"
    )


async def test_real_fairoaks_homepage_candidates_are_already_final_urls():
    # Real, raw-saved live page -- fairoaksranch-tx.municodemeetings.com/,
    # fetched 2026-09-01. Structurally different from Bristol: all 14
    # populated video-link cells hold an ABSOLUTE link straight to the
    # real video platform already (bare youtube.com/live/{id} and
    # youtu.be/{id} URLs), confirming both real href shapes exist live,
    # not just in the throwaway research script's single sample.
    html = load_fixture("municode_meetings", "fairoaks_home.html")
    routes = {FAIROAKS_HOME: FakeResponse(status=200, text=html, url=FAIROAKS_HOME)}

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await MunicodeMeetingsAssetFinder().resolve(FAIROAKS_HOME)

    candidates = exc_info.value.candidates
    assert len(candidates) == 14
    assert exc_info.value.jurisdiction_hint == "Fair Oaks Ranch, TX"
    # Already-final external URLs, not a municodemeetings.com detail page
    # -- confirms no unnecessary second hop is implied for this shape.
    assert all("youtube.com" in c["url"] or "youtu.be" in c["url"] for c in candidates)
    assert any(
        c["url"] == "https://www.youtube.com/live/I_LgBP8QEck?si=FPA6mJ2SluJMCgya"
        for c in candidates
    )


def _single_row_listing_html(video_href: str) -> str:
    # Trimmed to a single row, copied verbatim from bristol_home.html's
    # own real markup shape (see that fixture) -- only the video-link
    # cell's href varies per test. Keeps the single-candidate tests fast
    # and focused without re-parsing the full 25-row real fixture.
    return f"""
    <table class="views-table">
    <tbody>
      <tr class="odd">
        <td data-th="Date">
          <span class="date-display-single" property="dc:date"
                datatype="xsd:dateTime" content="2026-08-19T19:00:00-04:00">
            08/19/2026 - 7:00pm</span>
        </td>
        <td class="views-field views-field-title" data-th="Meeting">
          Town Council Meeting
        </td>
        <td class="views-field views-field-field-agendas" data-th="Agenda">
          <a href="https://mccmeetings.blob.core.usgovcloudapi.net/bristolri-pubu/MEET-Agenda-e12d1c0b0b3041689df7f26d5aaf3f49.pdf">PDF</a>
          <a href="https://meetings.municode.com/adaHtmlDocument/index?cc=BRISTOLRI&amp;me=e12d1c0b0b3041689df7f26d5aaf3f49&amp;ip=False">HTML</a>
        </td>
        <td class="views-field views-field-field-packets" data-th="Agenda Packet">
          <a href="https://mccmeetings.blob.core.usgovcloudapi.net/bristolri-pubu/MEET-Packet-e12d1c0b0b3041689df7f26d5aaf3f49.pdf">PDF</a>
          <a href="https://meetings.municode.com/adaHtmlDocument/index?cc=BRISTOLRI&amp;me=e12d1c0b0b3041689df7f26d5aaf3f49&amp;ip=True">HTML</a>
        </td>
        <td class="views-field views-field-field-video-link" data-th="Video">
          <a href="{video_href}">Video</a>
        </td>
      </tr>
    </tbody>
    </table>
    """


async def test_single_relative_href_delegates_via_second_hop_to_youtube(monkeypatch):
    # Real second-hop shape: the listing row's own href is a relative,
    # same-tenant page path (bristol-ri's real shape); resolving it
    # re-fetches that page and reads its #mcc_agenda_video iframe --
    # bristol_meeting_278.html is a real, raw-saved live page whose
    # iframe embeds a real YouTube video.
    html = _single_row_listing_html("/bc-towncouncil/page/town-council-meeting-278")
    detail_html = load_fixture("municode_meetings", "bristol_meeting_278.html")
    routes = {
        BRISTOL_HOME: FakeResponse(status=200, text=html, url=BRISTOL_HOME),
        BRISTOL_MEETING_278: FakeResponse(
            status=200, text=detail_html, url=BRISTOL_MEETING_278
        ),
    }

    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Town Council Meeting",
            "uploader": "Town of Bristol, Rhode Island",
            "upload_date": "20260819",
        },
    )

    with mock_session(routes):
        result = await MunicodeMeetingsAssetFinder().resolve(BRISTOL_HOME)

    assert result.platform == "youtube"
    assert result.external_id == "youtube:bhpXBnBdpZc"
    # Subdomain jurisdiction wins outright over YouTube's own guess, same
    # precedent as civicplus.py.
    assert result.jurisdiction == "Bristol, RI"
    # Agenda/packet threaded through from the LISTING row, not from
    # whatever YouTube's own page returns (it returns neither).
    assert result.agenda_link == (
        "https://meetings.municode.com/adaHtmlDocument/index"
        "?cc=BRISTOLRI&me=e12d1c0b0b3041689df7f26d5aaf3f49&ip=False"
    )
    assert result.packet_link == (
        "https://meetings.municode.com/adaHtmlDocument/index"
        "?cc=BRISTOLRI&me=e12d1c0b0b3041689df7f26d5aaf3f49&ip=True"
    )


async def test_single_relative_href_delegates_via_second_hop_to_vimeo():
    # Real second-hop shape confirmed on a SECOND real tenant
    # (hamburg-mi) -- confirms the delegated platform is genuinely not
    # YouTube-only, per this adapter's own module docstring.
    url = "https://hamburg-mi.municodemeetings.com/"
    html = _single_row_listing_html("/bc-pc/page/planning-commission-meeting-12")
    detail_html = load_fixture("municode_meetings", "hamburg_meeting_pc12.html")
    vimeo_url = "https://player.vimeo.com/video/1221763469"

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        HAMBURG_MEETING_PC12: FakeResponse(
            status=200, text=detail_html, url=HAMBURG_MEETING_PC12
        ),
        **_oembed_route(vimeo_url, "hamburg_oembed_1221763469.json"),
    }

    with mock_session(routes):
        result = await MunicodeMeetingsAssetFinder().resolve(url)

    assert result.platform == "vimeo"
    assert result.video_url == vimeo_url
    assert result.jurisdiction == "Hamburg, MI"


async def test_single_absolute_href_resolves_without_a_second_fetch(monkeypatch):
    # fairoaksranch-tx's real shape: the listing row's own href is
    # already the final video URL -- resolving it should NOT need to
    # fetch any municodemeetings.com detail page at all (only the
    # homepage URL is registered as a route; a route miss would raise
    # from aiohttp_mock's mock_session).
    html = _single_row_listing_html("https://www.youtube.com/live/I_LgBP8QEck")
    routes = {FAIROAKS_HOME: FakeResponse(status=200, text=html, url=FAIROAKS_HOME)}

    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "City Council Regular Meeting",
            "uploader": "City of Fair Oaks Ranch, Texas",
            "upload_date": "20251204",
        },
    )

    with mock_session(routes):
        result = await MunicodeMeetingsAssetFinder().resolve(FAIROAKS_HOME)

    assert result.platform == "youtube"
    assert result.external_id == "youtube:I_LgBP8QEck"
    assert result.jurisdiction == "Fair Oaks Ranch, TX"


async def test_no_video_rows_returns_warning():
    url = "https://example.municodemeetings.com/"
    html = (
        "<html><body><table class='views-table'><tbody></tbody></table></body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await MunicodeMeetingsAssetFinder().resolve(url)

    assert result.platform == "municode_meetings"
    assert result.video_url is None
    assert any("no video" in w.lower() for w in result.video_warnings)


async def test_login_wall_iframe_is_treated_as_no_video():
    # Synthetic, documented as such -- see
    # tests/fixtures/municode_meetings/README.md for why (the real
    # 2026-08-31 observation wasn't reproducible on a live re-check of
    # fairoaksranch-tx 2026-09-01). The markup shell is copied from
    # bristol_meeting_278.html's own confirmed #mcc_agenda_video iframe
    # structure; only the src is swapped for the real URL SHAPE recorded
    # when the login wall was observed
    # (accounts.google.com/ServiceLogin?service=youtube&...) -- not a
    # made-up domain.
    url = "https://fairoaksranch-tx.municodemeetings.com/bc-cc/page/some-meeting"
    html = """
    <html><body>
    <iframe id="mcc_agenda_video"
            src="https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/watch%3Fv%3Dabc"></iframe>
    </body></html>
    """
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await MunicodeMeetingsAssetFinder().resolve(url)

    assert result.platform == "municode_meetings"
    assert result.video_url is None
    assert any("no video" in w.lower() for w in result.video_warnings)


async def test_youtube_channel_link_excluded_from_video_row_candidates():
    # Synthetic, per this repo's convention: the payload shape (a single
    # views-table row) is copied from the real bristol_home.html markup,
    # and the two hrefs used are both real, independently-verified ones
    # -- a real DeSoto, KS channel link confirmed (via civicplus.py's own
    # regression test) to have no parseable video id, and
    # fairoaksranch-tx's own real direct video link from the fixture
    # above. Exercises the case where an absolute href resolves to a
    # real domain civicplus/base.py recognizes but isn't a real single
    # video -- the row should be dropped entirely, not counted as a
    # candidate.
    html = """
    <table class="views-table">
    <tbody>
      <tr>
        <td data-th="Date"><span class="date-display-single" content="2026-08-01T00:00:00-04:00">x</span></td>
        <td class="views-field views-field-title">Channel link only</td>
        <td class="views-field views-field-field-agendas"></td>
        <td class="views-field views-field-field-packets"></td>
        <td class="views-field views-field-field-video-link">
          <a href="https://www.youtube.com/@DeSotoKansas">Video</a>
        </td>
      </tr>
      <tr>
        <td data-th="Date"><span class="date-display-single" content="2025-12-04T18:30:00-06:00">x</span></td>
        <td class="views-field views-field-title">Real video</td>
        <td class="views-field views-field-field-agendas"></td>
        <td class="views-field views-field-field-packets"></td>
        <td class="views-field views-field-field-video-link">
          <a href="https://www.youtube.com/live/I_LgBP8QEck">Video</a>
        </td>
      </tr>
    </tbody>
    </table>
    """
    url = "https://example.municodemeetings.com/"

    finder = MunicodeMeetingsAssetFinder()
    soup = bs4.BeautifulSoup(html, "html.parser")
    table_soup = soup.find("table", class_="views-table")
    candidates = finder._find_video_rows(table_soup, url)

    assert len(candidates) == 1
    assert candidates[0]["url"] == "https://www.youtube.com/live/I_LgBP8QEck"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://bristol-ri.municodemeetings.com/", "Bristol, RI"),
        ("https://hamburg-mi.municodemeetings.com/", "Hamburg, MI"),
        ("https://fairoaksranch-tx.municodemeetings.com/", "Fair Oaks Ranch, TX"),
        ("https://columbus-wi.municodemeetings.com/", "Columbus, WI"),
        ("https://uppermarlboro-md.municodemeetings.com/", "Upper Marlboro, MD"),
        ("https://highlands-nj.municodemeetings.com/", "Highlands, NJ"),
        # No hyphen at all -- not the real convention, declines rather
        # than guessing.
        ("https://example.municodemeetings.com/", None),
        # Real known false-hit tenant (Municode's own internal sandbox,
        # see MUNICODE_MEETINGS_ENUMERATION.md) -- "p1" isn't a real
        # state code, so this correctly declines rather than guessing.
        ("https://sandbox-p1.municodemeetings.com/", None),
        # A real known tenant whose subdomain suffix is a sub-tenant
        # label, not a state code (uppermarlboro-committees, from
        # municode_meetings_video_finder.py's own TENANTS list) --
        # declines rather than guessing.
        ("https://uppermarlboro-committees.municodemeetings.com/", None),
    ],
)
def test_jurisdiction_from_subdomain(url, expected):
    assert MunicodeMeetingsAssetFinder._jurisdiction_from_subdomain(url) == expected
