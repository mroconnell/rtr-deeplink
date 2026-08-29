"""Tests for CivicWeb/iCompass (app/platforms/civicweb.py).

Real API shapes confirmed live 2026-08-12 against a real Dallas County, TX
meeting (dallascounty.civicweb.net) -- see BACKLOG.md/BACKLOG_DONE.md.
"""

from app.platforms.base import detect_platform, register
from app.platforms.civicweb import CivicWebAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session

MEETING_URL = (
    "https://dallascounty.civicweb.net/Portal/MeetingInformation.aspx?Org=Cal&Id=2108"
)
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
MEETING_DATA_JSON = '{"Id":2108,"Location":"Commissioners Court Room","Name":"Commissioners Court - Aug 04 2026","Time":"09:00 AM","TypeId":10}'


def _fake_extract_info(video_id):
    return {
        "title": "Commissioners Court",
        "uploader": "Dallas County TV",
        "upload_date": "20260804",
    }


def test_detect_platform_recognizes_civicweb_domain():
    assert detect_platform(MEETING_URL) == "civicweb"


async def test_resolve_real_meeting_delegates_to_youtube(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    routes = {
        MEETING_URL: FakeResponse(status=200, text=MEETING_HTML, url=MEETING_URL),
        VIDEOLINK_URL: FakeResponse(status=200, text=VIDEOLINK_JSON, url=VIDEOLINK_URL),
        MEETING_DATA_URL: FakeResponse(
            status=200, text=MEETING_DATA_JSON, url=MEETING_DATA_URL
        ),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(MEETING_URL)

    assert result.platform == "youtube"
    assert result.source_url == MEETING_URL  # not the delegated platform's own URL
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    assert result.title == "Commissioners Court - Aug 04 2026"
    assert result.date == "2026-08-04"
    # "Dallas County" is real in AL/AR/IA/MO/TX, so a bare name lookup
    # alone stays ambiguous -- resolved via the confirmed-domain registry
    # instead (added 2026-08-13, see BACKLOG.md/BACKLOG_DONE.md), since
    # this customer's real pages carry no ZIP-anchored address either.
    assert result.jurisdiction == "Dallas County, TX"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"


async def test_resolve_falls_back_to_known_domain_when_title_does_not_match(
    monkeypatch,
):
    # Applying the same fix already confirmed live for lims.py and
    # generic_fallback.py (see BACKLOG_DONE.md): if this page's own
    # <title> ever doesn't match _TITLE_JURISDICTION_RE (unconfirmed so
    # far for CivicWeb, but the same class of bug is proven for two other
    # YouTube-delegating adapters), jurisdiction must not silently fall
    # through to YouTube's own uploader field ("Dallas County TV" here --
    # a channel name, not a jurisdiction).
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    unmatched_title_html = (
        "<html><head><title>Meeting Portal</title></head><body></body></html>"
    )

    routes = {
        MEETING_URL: FakeResponse(
            status=200, text=unmatched_title_html, url=MEETING_URL
        ),
        VIDEOLINK_URL: FakeResponse(status=200, text=VIDEOLINK_JSON, url=VIDEOLINK_URL),
        MEETING_DATA_URL: FakeResponse(
            status=200, text=MEETING_DATA_JSON, url=MEETING_DATA_URL
        ),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(MEETING_URL)

    # Falls back to the confirmed-domain registry (type-aware, "County
    # of" preserved) rather than "Dallas County TV".
    assert result.jurisdiction == "County of Dallas, TX"


async def test_resolve_missing_video_id_reports_no_video(monkeypatch):
    no_video_json = (
        '"[{\\"MeetingDate\\":\\"2026-08-04T00:00:00\\",\\"YouTube\\":false}]"'
    )
    routes = {
        MEETING_URL: FakeResponse(status=200, text=MEETING_HTML, url=MEETING_URL),
        VIDEOLINK_URL: FakeResponse(status=200, text=no_video_json, url=VIDEOLINK_URL),
        MEETING_DATA_URL: FakeResponse(
            status=200, text=MEETING_DATA_JSON, url=MEETING_DATA_URL
        ),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(MEETING_URL)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]
    # Real page metadata is still surfaced even without a video.
    # "Dallas County" is real in AL/AR/IA/MO/TX, so a bare name lookup
    # alone stays ambiguous -- resolved via the confirmed-domain registry
    # instead (added 2026-08-13, see BACKLOG.md/BACKLOG_DONE.md), since
    # this customer's real pages carry no ZIP-anchored address either.
    assert result.jurisdiction == "Dallas County, TX"
    assert result.title == "Commissioners Court - Aug 04 2026"


async def test_resolve_degrades_honestly_when_videolink_fetch_fails(caplog):
    # 2026-08-28: _fetch_json()'s non-200 branch used to be silent.
    routes = {
        MEETING_URL: FakeResponse(status=200, text=MEETING_HTML, url=MEETING_URL),
        VIDEOLINK_URL: FakeResponse(status=404, url=VIDEOLINK_URL),
        MEETING_DATA_URL: FakeResponse(
            status=200, text=MEETING_DATA_JSON, url=MEETING_DATA_URL
        ),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await CivicWebAssetFinder().resolve(MEETING_URL)

    assert result.video_url is None
    assert any("JSON fetch got HTTP 404" in r.message for r in caplog.records)


def test_extract_jurisdiction_fills_in_state_for_an_unambiguous_county():
    # "Dallas County" itself is genuinely ambiguous (real counties by that
    # name exist in AL, AR, IA, MO, *and* TX -- confirmed via
    # app/utils/jurisdiction_data, matching the real fixture above staying
    # state-less). Uses a nationally-unique county name instead to confirm
    # the shared jurisdiction_enrich wiring is actually reached.
    html = "<html><head><title>Napa County - Meeting Information</title></head></html>"
    result = CivicWebAssetFinder._extract_jurisdiction(
        html, "https://napacounty.civicweb.net/Portal/x"
    )
    assert result == "Napa County, CA"


def test_extract_meeting_id_from_real_url_shape():
    assert CivicWebAssetFinder._extract_meeting_id(MEETING_URL) == "2108"
    assert (
        CivicWebAssetFinder._extract_meeting_id("https://example.civicweb.net/Portal/x")
        is None
    )


async def test_resolve_url_with_no_meeting_id_reports_error():
    url = "https://dallascounty.civicweb.net/Portal/MeetingInformation.aspx?Org=Cal"

    result = await CivicWebAssetFinder().resolve(url)

    assert result.video_warnings == [
        "Could not find a meeting id in this CivicWeb URL."
    ]


def test_extract_meeting_id_is_case_insensitive():
    # Real gap fixed 2026-08-27: "Diligent Community"
    # (community.diligentoneplatform.com), a real, live second domain for
    # this exact same underlying software (confirmed live on a real
    # Winthrop, MN meeting -- byte-identical Portal/MeetingInformation.aspx
    # path and Services/MeetingsService.svc backend API), uses a
    # lowercase `id=` query param where classic civicweb.net tenants use
    # `Id=` -- a case-sensitive match silently missed every meeting on
    # this real, live domain. See BACKLOG_DONE.md.
    diligent_community_url = (
        "https://winthropminnesota.community.diligentoneplatform.com/"
        "Portal/MeetingInformation.aspx?Org=Cal&id=63"
    )
    assert CivicWebAssetFinder._extract_meeting_id(diligent_community_url) == "63"


DILIGENT_COMMUNITY_MEETING_URL = (
    "https://winthropminnesota.community.diligentoneplatform.com/"
    "Portal/MeetingInformation.aspx?Org=Cal&id=63"
)
DILIGENT_COMMUNITY_VIDEOLINK_URL = (
    "https://winthropminnesota.community.diligentoneplatform.com/api/videolink/63"
)
DILIGENT_COMMUNITY_MEETING_DATA_URL = (
    "https://winthropminnesota.community.diligentoneplatform.com/"
    "Services/MeetingsService.svc/meetings/63/meetingData"
)
DILIGENT_COMMUNITY_HTML = (
    "<html><head><title>\n\tCity of Winthrop - Meeting Information\n</title>"
    "</head><body></body></html>"
)
REAL_EXTERNAL_VIDEO_ID = "ocPJdmtbtJU"


async def test_resolve_falls_back_to_meeting_data_external_video_link(monkeypatch):
    # Real, confirmed-live second video source: /api/videolink/{id} (the
    # only one previously checked) came back genuinely empty ("[]") on
    # this real Winthrop, MN meeting, while meetingData's own
    # MeetingExternalMinutesLinkUrl carried a real, populated youtu.be
    # link -- paired with MeetingExternalMinutesLinkName: "Video", the
    # signal that gates trusting it. Confirmed byte-for-byte against the
    # real API response.
    register(YouTubeAssetFinder())
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    meeting_data_json = (
        '{"Id":63,"Location":"Council Chambers",'
        '"MeetingExternalLinkName":"","MeetingExternalLinkUrl":"",'
        '"MeetingExternalMinutesLinkName":"Video",'
        f'"MeetingExternalMinutesLinkUrl":"https://youtu.be/{REAL_EXTERNAL_VIDEO_ID}",'
        '"Name":"Regular Council - Aug 03 2026","Time":"07:00 PM","TypeId":10}'
    )
    routes = {
        DILIGENT_COMMUNITY_MEETING_URL: FakeResponse(
            status=200, text=DILIGENT_COMMUNITY_HTML, url=DILIGENT_COMMUNITY_MEETING_URL
        ),
        DILIGENT_COMMUNITY_VIDEOLINK_URL: FakeResponse(
            status=200, text="[]", url=DILIGENT_COMMUNITY_VIDEOLINK_URL
        ),
        DILIGENT_COMMUNITY_MEETING_DATA_URL: FakeResponse(
            status=200, text=meeting_data_json, url=DILIGENT_COMMUNITY_MEETING_DATA_URL
        ),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(DILIGENT_COMMUNITY_MEETING_URL)

    assert result.platform == "youtube"
    assert result.source_url == DILIGENT_COMMUNITY_MEETING_URL
    assert result.external_id == f"youtube:{REAL_EXTERNAL_VIDEO_ID}"
    assert result.title == "Regular Council - Aug 03 2026"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_EXTERNAL_VIDEO_ID}"


async def test_meeting_data_external_link_ignored_when_not_named_video(monkeypatch):
    # The two MeetingExternal*Link fields are generic link slots, not
    # video-specific -- a populated URL whose paired ...LinkName doesn't
    # say "Video" (e.g. a real agenda-packet or minutes link) must not be
    # treated as a video source.
    meeting_data_json = (
        '{"Id":63,"Location":"Council Chambers",'
        '"MeetingExternalLinkName":"Agenda Packet",'
        '"MeetingExternalLinkUrl":"https://example.com/packet.pdf",'
        '"MeetingExternalMinutesLinkName":"","MeetingExternalMinutesLinkUrl":"",'
        '"Name":"Regular Council - Aug 03 2026","Time":"07:00 PM","TypeId":10}'
    )
    routes = {
        DILIGENT_COMMUNITY_MEETING_URL: FakeResponse(
            status=200, text=DILIGENT_COMMUNITY_HTML, url=DILIGENT_COMMUNITY_MEETING_URL
        ),
        DILIGENT_COMMUNITY_VIDEOLINK_URL: FakeResponse(
            status=200, text="[]", url=DILIGENT_COMMUNITY_VIDEOLINK_URL
        ),
        DILIGENT_COMMUNITY_MEETING_DATA_URL: FakeResponse(
            status=200, text=meeting_data_json, url=DILIGENT_COMMUNITY_MEETING_DATA_URL
        ),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(DILIGENT_COMMUNITY_MEETING_URL)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]


async def test_meeting_data_external_video_link_to_an_unsupported_platform_degrades_cleanly(
    monkeypatch,
):
    # A real "Video"-named link that isn't a platform detect_platform()
    # recognizes -- not confirmed to ever happen live, but the field is
    # generic, so this must degrade to the same "no video" outcome rather
    # than raising. Forces the UnsupportedPlatformError branch directly
    # (rather than relying on a real unmocked URL actually being
    # unsupported) since detect_platform() falls through to
    # generic_fallback.py for any ordinary http(s) URL once it's
    # registered -- which, per this file's own process-global _REGISTRY,
    # may or may not be true depending on what other test files already
    # ran in the same pytest process (see conftest.py's own
    # registered_platforms() docstring).
    import app.platforms.civicweb as civicweb_module
    from app.platforms.base import UnsupportedPlatformError

    async def _raise_unsupported(url):
        raise UnsupportedPlatformError(url=url, detected="unknown")

    monkeypatch.setattr(civicweb_module, "resolve_via_platform", _raise_unsupported)

    meeting_data_json = (
        '{"Id":63,"Location":"Council Chambers",'
        '"MeetingExternalLinkName":"","MeetingExternalLinkUrl":"",'
        '"MeetingExternalMinutesLinkName":"Video",'
        '"MeetingExternalMinutesLinkUrl":"https://example.com/not-a-real-platform",'
        '"Name":"Regular Council - Aug 03 2026","Time":"07:00 PM","TypeId":10}'
    )
    routes = {
        DILIGENT_COMMUNITY_MEETING_URL: FakeResponse(
            status=200, text=DILIGENT_COMMUNITY_HTML, url=DILIGENT_COMMUNITY_MEETING_URL
        ),
        DILIGENT_COMMUNITY_VIDEOLINK_URL: FakeResponse(
            status=200, text="[]", url=DILIGENT_COMMUNITY_VIDEOLINK_URL
        ),
        DILIGENT_COMMUNITY_MEETING_DATA_URL: FakeResponse(
            status=200, text=meeting_data_json, url=DILIGENT_COMMUNITY_MEETING_DATA_URL
        ),
    }

    with mock_session(routes):
        result = await CivicWebAssetFinder().resolve(DILIGENT_COMMUNITY_MEETING_URL)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]
