"""Tests for ClerkBase/clerkshq.com (app/platforms/clerkbase.py).

Fixture HTML below is a trimmed real snippet, not a fabricated shape --
confirmed live 2026-08-14 against a real Yellow Springs, OH meeting
(landing page `clerkshq.com/YellowSprings-OH?docId=feb07_22ag&path=...`,
document page `clerkshq.com/Content/YellowSprings-OH/council/2022/
feb07_22ag.htm`), see clerkbase.py's own module docstring and
README.md's platform table. Only one real customer checked so far.
"""

from app.platforms.base import detect_platform
from app.platforms.clerkbase import ClerkBaseAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session

LANDING_URL = (
    "https://clerkshq.com/YellowSprings-OH?docId=feb07_22ag&"
    "path=ArchAgenda_VilCouncil%2C2022_COUNCIL_AGENDAS%2Cfeb07_22ag%2C"
)
CONTENT_URL = "https://clerkshq.com/Content/YellowSprings-OH/council/2022/feb07_22ag.htm"
REAL_VIDEO_ID = "ThJ-uDDbhGQ"

# Real, trimmed to the two JS variables clerkbase.py actually reads --
# confirmed live these appear in the landing page's plain static HTML
# (no JS execution needed).
LANDING_HTML = """
<html><body>
<script>
    window.clientSite = 'YellowSprings-OH';
    window.autoOpenDocUrl = '/Content/YellowSprings-OH/council/2022/feb07_22ag.htm';
    window.autoOpenDocTitle = 'February 7, 2022 - Regular Village Council Meeting';
    window.autoOpenDocId = 'feb07_22ag';
</script>
</body></html>
"""

# Real, trimmed MS-Word-HTML-export shape -- the actual video link found
# on the real document page.
CONTENT_HTML = """
<html><body>
<a href="https://vid.opengovideo.com/playvideo.asp?sFileName=https://www.youtube.com/embed/ThJ-uDDbhGQ?start=1&rel=0&autoplay=1&controls=1" target="_new">
<img src="/Content/YellowSprings-OH/images//video.gif" alt="Video Icon" border="0"></a>
COUNCIL FOR THE VILLAGE OF YELLOW SPRINGS
</body></html>
"""

CONTENT_HTML_NO_VIDEO = "<html><body>COUNCIL FOR THE VILLAGE OF YELLOW SPRINGS -- no video this time</body></html>"


def _fake_extract_info(video_id):
    return {
        "title": "VIRTUAL VILLAGE COUNCIL 2022_02-07",
        "uploader": "YELLOW SPRINGS COMMUNITY ACCESS",
        "release_date": "20220207",
    }


def test_detect_platform_recognizes_clerkshq_domain():
    assert detect_platform(LANDING_URL) == "clerkbase"
    assert detect_platform(CONTENT_URL) == "clerkbase"


async def test_resolve_landing_page_delegates_to_youtube(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    routes = {
        LANDING_URL: FakeResponse(status=200, text=LANDING_HTML, url=LANDING_URL),
        CONTENT_URL: FakeResponse(status=200, text=CONTENT_HTML, url=CONTENT_URL),
    }

    with mock_session(routes):
        result = await ClerkBaseAssetFinder().resolve(LANDING_URL)

    assert result.platform == "youtube"  # same delegation convention as primegov.py/civicweb.py
    assert result.source_url == LANDING_URL  # not the delegated YouTube URL
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    # The landing page's own autoOpenDocTitle wins over YouTube's title.
    assert result.title == "February 7, 2022 - Regular Village Council Meeting"
    assert result.jurisdiction == "Yellow Springs, OH"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"


async def test_resolve_direct_content_url_with_no_landing_wrapper(monkeypatch):
    # The direct `/Content/.../*.htm` URL is also a real, independently
    # linkable page (confirmed live) -- no autoOpenDocUrl/autoOpenDocTitle
    # present, so this must resolve from that single fetch alone.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    routes = {CONTENT_URL: FakeResponse(status=200, text=CONTENT_HTML, url=CONTENT_URL)}

    with mock_session(routes):
        result = await ClerkBaseAssetFinder().resolve(CONTENT_URL)

    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    # No autoOpenDocTitle available here -- falls back to YouTube's own title.
    assert result.title == "VIRTUAL VILLAGE COUNCIL 2022_02-07"
    assert result.jurisdiction == "Yellow Springs, OH"


async def test_resolve_missing_video_reports_no_video():
    routes = {
        LANDING_URL: FakeResponse(status=200, text=LANDING_HTML, url=LANDING_URL),
        CONTENT_URL: FakeResponse(status=200, text=CONTENT_HTML_NO_VIDEO, url=CONTENT_URL),
    }

    with mock_session(routes):
        result = await ClerkBaseAssetFinder().resolve(LANDING_URL)

    assert result.video_url is None
    assert result.video_warnings == ["No video found on this ClerkBase page."]
    # Real page metadata is still surfaced even without a video.
    assert result.title == "February 7, 2022 - Regular Village Council Meeting"
    assert result.jurisdiction == "Yellow Springs, OH"


def test_extract_jurisdiction_from_client_site_slug():
    assert ClerkBaseAssetFinder._extract_jurisdiction(LANDING_URL) == "Yellow Springs, OH"
    assert ClerkBaseAssetFinder._extract_jurisdiction(CONTENT_URL) == "Yellow Springs, OH"
    assert ClerkBaseAssetFinder._extract_jurisdiction("https://clerkshq.com/help?ajax=1") is None
