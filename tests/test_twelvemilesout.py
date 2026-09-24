from app.platforms.twelvemilesout import (
    TwelveMilesOutAssetFinder,
    is_twelvemilesout_tenant_host,
)
from app.platforms.passive_verify import _twelvemilesout_walker

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# Every fixture below was fetched live 2026-09-24 (WO-1045) against real,
# current tenants -- confirmed against 4 real tenants, 2 real listing
# themes (see twelvemilesout.py's own module docstring): coronado/colton
# (Vue-rendered, backed by a real `/api/meetings/list` JSON endpoint) and
# escondido/covina (plain server-rendered, no JS needed).

CORONADO_URL = "https://coronado.12milesout.com/meeting/council/9-15-2026"
CORONADO_CAPTIONS_URL = (
    "https://coronado.12milesout.com/api/captions/coronado-ccm-20260915/en/0/5117000"
)
ESCONDIDO_MEETING_URL = "https://escondido.12milesout.com/Video/Meeting/5118e256-6968-4318-83a2-be76bce62bac"
COVINA_MEETING_URL = (
    "https://covina.12milesout.com/meeting/79bed72e-ca6d-4ad0-ad18-7b275caac901"
)
COLTON_MEETING_URL = (
    "https://colton.12milesout.com/video/meeting/f05e0cf7-b4b1-4447-ad51-96b4a73f3453"
)


async def test_resolve_real_coronado_meeting_with_captions():
    # Real Coronado, CA City Council meeting (2026-09-15) -- the happy
    # path: a direct CloudFront MP4, real `data-start`/`data-duration`
    # agenda chapters, and a real, populated English caption track via
    # the vendor's own `/api/captions/{fileId}/{lang}/{start}/{end}`
    # endpoint (confirmed live: 1,874 real cues).
    html = load_fixture("twelvemilesout", "coronado_meeting.html")
    captions = load_fixture("twelvemilesout", "coronado_captions_en.vtt")

    routes = {
        CORONADO_URL: FakeResponse(status=200, text=html, url=CORONADO_URL),
        CORONADO_CAPTIONS_URL: FakeResponse(
            status=200, text=captions, url=CORONADO_CAPTIONS_URL
        ),
    }

    with mock_session(routes):
        result = await TwelveMilesOutAssetFinder().resolve(CORONADO_URL)

    assert result.platform == "twelvemilesout"
    assert result.title == "City Council Meeting"
    assert result.date == "2026-09-15"
    assert result.jurisdiction == "Coronado, CA"
    assert result.video_url == (
        "https://d2vr3rrbtycvrt.cloudfront.net/coronado-ccm-20260915/videos/"
        "full/mp4/coronado-ccm-20260915_720.mp4"
    )
    assert result.video_format == "mp4"
    assert result.video_duration_seconds == 5117.0
    assert result.transcript_language == "en"
    assert len(result.segments) > 1000
    assert result.transcript_warnings == []
    assert result.video_warnings == []
    assert len(result.agenda_items) == 9
    assert result.agenda_items[0].start == 0


async def test_resolve_real_escondido_meeting_no_captions():
    # Real Escondido, CA City Council meeting (2026-09-16) -- the
    # server-rendered static theme, and a real "no captions at all"
    # tenant (no `data-captions` attribute on the `<video>` tag).
    html = load_fixture("twelvemilesout", "escondido_meeting.html")

    routes = {
        ESCONDIDO_MEETING_URL: FakeResponse(
            status=200, text=html, url=ESCONDIDO_MEETING_URL
        ),
    }

    with mock_session(routes):
        result = await TwelveMilesOutAssetFinder().resolve(ESCONDIDO_MEETING_URL)

    assert result.title == "City Council Meeting"
    assert result.date == "2026-09-16"
    assert result.jurisdiction == "Escondido, CA"
    assert result.video_url == (
        "https://d2vr3rrbtycvrt.cloudfront.net/escondido-ccm-20260916/videos/"
        "full/mp4/escondido-ccm-20260916_720.mp4"
    )
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]
    assert result.video_duration_seconds == 5067.0
    assert len(result.agenda_items) == 18
    assert result.agenda_items[-1].text == "ADJOURNMENT"


async def test_resolve_real_covina_meeting_empty_data_captions_attribute():
    # Real Covina, CA City Council meeting (2026-09-15) -- a real,
    # confirmed "no captions" shape distinct from Escondido's: the
    # `<video>` tag HAS a `data-captions` attribute, but it's an empty
    # string (`data-captions=""`), not absent -- must not be treated as a
    # single empty-string language code.
    html = load_fixture("twelvemilesout", "covina_meeting.html")

    routes = {
        COVINA_MEETING_URL: FakeResponse(status=200, text=html, url=COVINA_MEETING_URL),
    }

    with mock_session(routes):
        result = await TwelveMilesOutAssetFinder().resolve(COVINA_MEETING_URL)

    assert result.jurisdiction == "Covina, CA"
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]
    assert len(result.agenda_items) == 15


async def test_is_twelvemilesout_tenant_host():
    assert is_twelvemilesout_tenant_host("escondido.12milesout.com")
    assert is_twelvemilesout_tenant_host("Coronado.12MilesOut.com")
    # Bare/`www` marketing host and confirmed non-government subdomains
    # (radio station demo content, vendor CDN infra) -- see this module's
    # own `_NON_TENANT_SUBDOMAINS` comment.
    assert not is_twelvemilesout_tenant_host("12milesout.com")
    assert not is_twelvemilesout_tenant_host("www.12milesout.com")
    assert not is_twelvemilesout_tenant_host("lax-vod.12milesout.com")
    assert not is_twelvemilesout_tenant_host("radio.12milesout.com")
    assert not is_twelvemilesout_tenant_host("unrelatedsite.com")


async def test_walker_uses_real_json_api_when_present():
    # Coronado/Colton's Vue-rendered listing theme -- the walker tries
    # the real `/api/meetings/list/1/12` JSON endpoint first.
    api_json = load_fixture("twelvemilesout", "coronado_meetings_api.json")
    api_url = "https://coronado.12milesout.com/api/meetings/list/1/12"

    routes = {api_url: FakeResponse(status=200, text=api_json, url=api_url)}

    with mock_session(routes):
        candidates = await _twelvemilesout_walker("https://coronado.12milesout.com/")

    assert len(candidates) == 3
    assert candidates[0]["date"] == "2026-09-15"
    assert candidates[0]["url"] == (
        "https://coronado.12milesout.com/meeting/council/9-15-2026"
    )
    assert candidates[1]["title"] == "Planning and Design Commission Meeting"


async def test_walker_falls_back_to_static_table_when_api_missing():
    # Escondido/Covina's static server-rendered listing theme -- the API
    # 404s (confirmed live: Covina's `/api/meetings/list/...` is a real
    # 404, not just unmocked), so the walker falls back to scraping the
    # plain `<table>` on the tenant's own home page.
    home_html = load_fixture("twelvemilesout", "escondido_home.html")
    api_url = "https://escondido.12milesout.com/api/meetings/list/1/12"
    home_url = "https://escondido.12milesout.com/"

    routes = {
        api_url: FakeResponse(status=404, text="", url=api_url),
        home_url: FakeResponse(status=200, text=home_html, url=home_url),
    }

    with mock_session(routes):
        candidates = await _twelvemilesout_walker(home_url)

    assert len(candidates) == 10
    assert candidates[0]["date"] == "2026-09-16"
    assert candidates[0]["url"] == (
        "https://escondido.12milesout.com/Video/Meeting/"
        "5118e256-6968-4318-83a2-be76bce62bac"
    )
    assert candidates[0]["title"] == "City Council Meeting"


async def test_resolve_listing_root_delegates_to_walker_and_picks_newest_with_video():
    api_json = load_fixture("twelvemilesout", "colton_meetings_api.json")
    api_url = "https://colton.12milesout.com/api/meetings/list/1/12"
    meeting_html = load_fixture("twelvemilesout", "colton_meeting.html")

    routes = {
        api_url: FakeResponse(status=200, text=api_json, url=api_url),
        COLTON_MEETING_URL: FakeResponse(
            status=200, text=meeting_html, url=COLTON_MEETING_URL
        ),
    }

    with mock_session(routes):
        result = await TwelveMilesOutAssetFinder().resolve(
            "https://colton.12milesout.com/"
        )

    assert result.jurisdiction == "Colton, CA"
    assert result.video_url is not None
    assert result.source_url == COLTON_MEETING_URL
