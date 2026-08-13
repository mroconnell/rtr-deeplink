"""Tests for CivicWeb/iCompass (app/platforms/civicweb.py).

Real API shapes confirmed live 2026-08-12 against a real Dallas County, TX
meeting (dallascounty.civicweb.net) -- see BACKLOG.md/BACKLOG_DONE.md.
"""

from app.platforms.base import detect_platform
from app.platforms.civicweb import CivicWebAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session

MEETING_URL = "https://dallascounty.civicweb.net/Portal/MeetingInformation.aspx?Org=Cal&Id=2108"
VIDEOLINK_URL = "https://dallascounty.civicweb.net/api/videolink/2108"
MEETING_DATA_URL = "https://dallascounty.civicweb.net/Services/MeetingsService.svc/meetings/2108/meetingData"
REAL_VIDEO_ID = "t2rG96zqw7M"

MEETING_HTML = "<html><head><title>\n\tDallas County - Meeting Information\n</title></head><body></body></html>"

# Real gap confirmed live: /api/videolink/{id} double-encodes its JSON --
# the raw body is a JSON *string literal* containing the real array, not
# the array directly (a WCF/.svc-family quirk, unlike meetingData below).
VIDEOLINK_JSON = (
    '"[{\\"MeetingDate\\":\\"2026-08-04T00:00:00\\",\\"TodayLiveStream\\":false,'
    '\\"IndexPoints\\":\\"\\",\\"LocalIndexPoints\\":\\"\\",\\"ShowTimeStamps\\":true,'
    f'\\"ShowVideoLink\\":true,\\"YouTube\\":true,\\"YouTubeEventId\\":\\"{REAL_VIDEO_ID}\\"}}]"'
)
MEETING_DATA_JSON = (
    '{"Id":2108,"Location":"Commissioners Court Room","Name":"Commissioners Court - Aug 04 2026","Time":"09:00 AM","TypeId":10}'
)


def _fake_extract_info(video_id):
    return {"title": "Commissioners Court", "uploader": "Dallas County TV", "upload_date": "20260804"}


def test_detect_platform_recognizes_civicweb_domain():
    assert detect_platform(MEETING_URL) == "civicweb"


async def test_resolve_real_meeting_delegates_to_youtube(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    routes = {
        MEETING_URL: FakeResponse(status=200, text=MEETING_HTML, url=MEETING_URL),
        VIDEOLINK_URL: FakeResponse(status=200, text=VIDEOLINK_JSON, url=VIDEOLINK_URL),
        MEETING_DATA_URL: FakeResponse(status=200, text=MEETING_DATA_JSON, url=MEETING_DATA_URL),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(MEETING_URL)

    assert result.platform == "youtube"
    assert result.source_url == MEETING_URL  # not the delegated platform's own URL
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    assert result.title == "Commissioners Court - Aug 04 2026"
    assert result.date == "2026-08-04"
    assert result.jurisdiction == "Dallas County"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"


async def test_resolve_missing_video_id_reports_no_video(monkeypatch):
    no_video_json = '"[{\\"MeetingDate\\":\\"2026-08-04T00:00:00\\",\\"YouTube\\":false}]"'
    routes = {
        MEETING_URL: FakeResponse(status=200, text=MEETING_HTML, url=MEETING_URL),
        VIDEOLINK_URL: FakeResponse(status=200, text=no_video_json, url=VIDEOLINK_URL),
        MEETING_DATA_URL: FakeResponse(status=200, text=MEETING_DATA_JSON, url=MEETING_DATA_URL),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(MEETING_URL)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]
    # Real page metadata is still surfaced even without a video.
    assert result.jurisdiction == "Dallas County"
    assert result.title == "Commissioners Court - Aug 04 2026"


def test_extract_jurisdiction_fills_in_state_for_an_unambiguous_county():
    # "Dallas County" itself is genuinely ambiguous (real counties by that
    # name exist in AL, AR, IA, MO, *and* TX -- confirmed via
    # app/utils/jurisdiction_data, matching the real fixture above staying
    # state-less). Uses a nationally-unique county name instead to confirm
    # the shared jurisdiction_enrich wiring is actually reached.
    html = "<html><head><title>Napa County - Meeting Information</title></head></html>"
    result = CivicWebAssetFinder._extract_jurisdiction(html, "https://napacounty.civicweb.net/Portal/x")
    assert result == "Napa County, CA"


def test_extract_meeting_id_from_real_url_shape():
    assert CivicWebAssetFinder._extract_meeting_id(MEETING_URL) == "2108"
    assert CivicWebAssetFinder._extract_meeting_id("https://example.civicweb.net/Portal/x") is None


async def test_resolve_url_with_no_meeting_id_reports_error():
    url = "https://dallascounty.civicweb.net/Portal/MeetingInformation.aspx?Org=Cal"

    result = await CivicWebAssetFinder().resolve(url)

    assert result.video_warnings == ["Could not find a meeting id in this CivicWeb URL."]
