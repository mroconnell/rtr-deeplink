"""Tests for ProudCity (app/platforms/proudcity.py).

Real shapes confirmed live 2026-08-26 against Town of Fairfax, CA
(townoffairfaxca.gov) -- see BACKLOG_DONE.md for the full evidence trail,
sourced from the actual `wp-proud-meeting`/`wp-proud-theme` plugin code,
not inferred. The fixture below reconstructs the real confirmed fragments
(title, og:site_name, "Date and time:" text, the GCS agenda PDF link, the
YouTube embed) from that live page. The bookmarks block is schema-verified
against the real theme template source but not yet confirmed populated on
any real tenant checked -- marked below, per this repo's "don't claim a
data path works without a positive example" convention.
"""

from app.platforms.base import detect_platform
from app.platforms.proudcity import ProudCityAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session

MEETING_URL = "https://townoffairfaxca.gov/meetings/town-council-meeting-august-5-2026/"
REAL_VIDEO_ID = "LerZN-sctuY"

# Real fragments (title, og:site_name, description date text, GCS PDF link,
# the static YouTube iframe) confirmed live on this exact URL 2026-08-26.
# The bookmark anchors are synthetic -- schema-verified against
# wp-proud-theme/templates/content-single-meeting.php's real
# `data-youtube-seek` markup, no real positive example found yet.
MEETING_HTML = f"""
<html><head>
<meta property="og:site_name" content="Town of Fairfax">
<meta property="og:title" content="Town Council Meeting: August 5, 2026 - Town of Fairfax">
</head><body>
<h1 class="entry-title">
    Town Council Meeting: August 5, 2026  </h1>
<p>Date and time: 2026-08-05 06:30 pmLocation: Fairfax Women&#8217;s Club, 46 Park Road, Fairfax, CA 94930</p>
<div id="tab-agenda">
  <a href="https://storage.googleapis.com/proudcity/fairfaxca/2025/12/08-05-2026-regular-f9ed577d.pdf">Agenda</a>
</div>
<div id="tab-video">
  <iframe id="player" src="https://www.youtube.com/embed/{REAL_VIDEO_ID}?autoplay=0&amp;controls=1&amp;enablejsapi=1&amp;widgetid=1"></iframe>
  <div id="youtube-list">
    <ul class="list-group">
      <a class="list-group-item" href="#" data-youtube-seek="120">
        Call to Order
        <span class="badge">2:00</span>
      </a>
      <a class="list-group-item" href="#" data-youtube-seek="600">
        Public Comment
        <span class="badge">10:00</span>
      </a>
    </ul>
  </div>
</div>
</body></html>
"""


def _fake_extract_info(video_id):
    return {
        "title": "Fairfax Town Council August 5, 2026",
        "uploader": "Town of Fairfax",
        "upload_date": "20260805",
    }


def test_detect_platform_recognizes_known_proudcity_domain():
    assert detect_platform(MEETING_URL) == "proudcity"


def test_detect_platform_leaves_unknown_domains_to_generic_fallback():
    assert detect_platform("https://some-other-city.gov/meetings/foo/") == "unknown"


async def test_resolve_real_meeting_delegates_to_youtube_and_adds_bookmarks(
    monkeypatch,
):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    routes = {MEETING_URL: FakeResponse(status=200, text=MEETING_HTML, url=MEETING_URL)}

    with mock_session(routes):
        result = await ProudCityAssetFinder().resolve(MEETING_URL)

    assert result.platform == "youtube"
    assert (
        result.source_url == MEETING_URL
    )  # not youtube.com -- same as PrimeGov/CivicWeb
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.title == "Town Council Meeting: August 5, 2026"
    assert result.date == "2026-08-05"
    assert result.jurisdiction == "Town of Fairfax, CA"
    assert (
        result.agenda_link
        == "https://storage.googleapis.com/proudcity/fairfaxca/2025/12/08-05-2026-regular-f9ed577d.pdf"
    )
    assert [item.text for item in result.agenda_items] == [
        "Call to Order",
        "Public Comment",
    ]
    assert result.agenda_items[0].start == 120.0
    assert result.agenda_items[1].start == 600.0


async def test_resolve_no_video_reports_a_clear_warning(monkeypatch):
    html_no_video = """
    <html><head>
    <meta property="og:site_name" content="Town of Fairfax">
    </head><body>
    <h1 class="entry-title">Parks and Recreation Commission: August 10, 2026  </h1>
    <p>Date and time: 2026-08-10 06:00 pm</p>
    </body></html>
    """
    routes = {
        MEETING_URL: FakeResponse(status=200, text=html_no_video, url=MEETING_URL)
    }

    with mock_session(routes):
        result = await ProudCityAssetFinder().resolve(MEETING_URL)

    assert result.platform == "proudcity"
    assert result.video_url is None
    assert result.video_link is None
    assert result.video_warnings == ["No video found for this meeting."]


async def test_resolve_external_video_is_a_pointer_not_a_playable_url(monkeypatch):
    html_external = """
    <html><head>
    <meta property="og:site_name" content="Town of Fairfax">
    </head><body>
    <h1 class="entry-title">Special Meeting: August 20, 2026  </h1>
    <a href="https://example-video-host.com/watch/abc123" target="_blank"
       title="View video on external website">Video</a>
    </body></html>
    """
    routes = {
        MEETING_URL: FakeResponse(status=200, text=html_external, url=MEETING_URL)
    }

    with mock_session(routes):
        result = await ProudCityAssetFinder().resolve(MEETING_URL)

    assert result.platform == "proudcity"
    assert result.video_url is None
    assert result.video_link == "https://example-video-host.com/watch/abc123"


async def test_resolve_logs_a_warning_when_the_page_fetch_fails(caplog):
    # Real silent-exception site found live during the 2026-08-28 sweep
    # (BACKLOG.md) -- _fetch_text()'s non-200 branch used to return None
    # with no record of why, so a real fetch failure and a page that
    # genuinely doesn't exist looked identical in the logs.
    routes = {MEETING_URL: FakeResponse(status=500, text="", url=MEETING_URL)}

    with mock_session(routes), caplog.at_level("WARNING"):
        result = await ProudCityAssetFinder().resolve(MEETING_URL)

    assert result.video_warnings == ["Could not fetch this ProudCity meeting page."]
    assert any(
        "500" in record.message and MEETING_URL in record.message
        for record in caplog.records
    )


async def test_resolve_refuses_the_shared_demo_meeting_slug():
    """Real incident, 2026-08-26: this exact slug is a shared WordPress
    seed post on every ProudCity install, confirmed on three unrelated
    tenants -- two accidentally real-ingested with one of ProudCity's own
    marketing videos before this guard existed (see BACKLOG_DONE.md)."""
    demo_url = "https://santa-ana.gov/meetings/example-city-council-meeting/"

    # No route registered -- if the guard didn't fire first, this would
    # raise inside mock_session for an unmocked URL, failing the test.
    with mock_session({}):
        result = await ProudCityAssetFinder().resolve(demo_url)

    assert result.platform == "proudcity"
    assert result.video_url is None
    assert "demo" in result.video_warnings[0].lower()
