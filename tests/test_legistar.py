import pytest

from app.platforms.base import CalendarPageError, register
from app.platforms.granicus import GranicusAssetFinder
from app.platforms.legistar import LegistarAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _register_granicus():
    # resolve_via_platform() looks up the registered finder by platform
    # name -- register the real GranicusAssetFinder so delegation exercises
    # real Granicus parsing, not a stub.
    register(GranicusAssetFinder())


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
    assert all("granicus.com" in c["url"] or "Video.aspx" in c["url"] for c in candidates)
    assert all(c["title"] and c["date"] for c in candidates)


async def test_single_meeting_delegates_to_granicus():
    # A MeetingDetail-style page with exactly one video link, which
    # redirects (per the real confirmed Maricopa pattern) straight to a
    # Granicus player/clip URL -- delegation should hand off to a real
    # GranicusAssetFinder.resolve() call on that URL, not just detect it.
    meeting_url = "https://maricopa.legistar.com/MeetingDetail.aspx?ID=1"
    video_aspx = "https://maricopa.legistar.com/Video.aspx?Mode=Granicus&ID1=1504&Mode2=Video"
    granicus_url = "https://cityofmaricopa.granicus.com/player/clip/1504"

    meeting_html = (
        '<html><body><table><tr><td>City Council Meeting</td>'
        '<td>4/8/2026</td></tr></table>'
        f'<a class="videolink" onclick="window.open(\'{video_aspx}\',\'video\');'
        'return false;">Video</a></body></html>'
    )
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        meeting_url: FakeResponse(status=200, text=meeting_html, url=meeting_url),
        video_aspx: FakeResponse(status=200, text="", url=granicus_url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://cityofmaricopa.granicus.com/videos/1504/captions.vtt": FakeResponse(status=404),
        "https://cityofmaricopa.granicus.com/AgendaViewer.php?clip_id=1504&embedded=1": FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(meeting_url)

    assert result.platform == "granicus"
    assert result.external_id == "granicus:1504"


async def test_no_video_link_returns_warning_not_crash():
    url = "https://maricopa.legistar.com/MeetingDetail.aspx?ID=2"
    html = "<html><body>No video for this one.</body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await LegistarAssetFinder().resolve(url)

    assert result.platform == "legistar"
    assert any("no video" in w.lower() for w in result.video_warnings)
