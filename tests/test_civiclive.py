"""Tests for CivicLive (app/platforms/civiclive.py), WO-92.

Real shapes confirmed live 2026-09-01 (see civiclive.py's own module
docstring for the full investigation): Auburn, WA's own "Agendas &
Minutes" page is a genuine plain-HTTP 302 redirect straight to
`auburnwa.portal.civicclerk.com` (CivicClerk's public portal home);
Escalon, CA's real City Council agenda listing page has no per-meeting
video link at all -- only a single page-wide YouTube *channel* link,
which must never be mistaken for a specific meeting's video.
"""

import pytest

from app.platforms.base import detect_platform, register
from app.platforms.civiclive import CivicLiveAssetFinder, is_civiclive_host
from app.platforms.granicus import GranicusAssetFinder
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """See test_generic_fallback.py's identical fixture -- this suite is
    network-free, so guarded_get()'s real hostname resolution is patched
    out."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


@pytest.fixture(autouse=True)
def _register_granicus():
    register(GranicusAssetFinder())


def test_detect_platform_recognizes_hosted_and_hosted2():
    assert detect_platform("https://auburn.hosted.civiclive.com/") == "civiclive"
    assert detect_platform("https://cityoflynn.hosted2.civiclive.com/") == "civiclive"


def test_detect_platform_does_not_claim_bare_apex_or_unrelated_domain():
    # The vendor's own marketing site (www.civiclive.com) and the
    # Cloudflare-wildcarded-but-nonexistent hostedN>=3 shapes (confirmed
    # live: hosted3/4/5.civiclive.com don't even resolve) are deliberately
    # NOT claimed -- only the two confirmed-real tenant host shapes are.
    assert detect_platform("https://www.civiclive.com/") == "unknown"
    assert detect_platform("https://example.hosted3.civiclive.com/") == "unknown"
    assert detect_platform("https://example.com/") == "unknown"


def test_is_civiclive_host_matches_suffix_not_substring():
    assert is_civiclive_host("auburn.hosted.civiclive.com")
    assert is_civiclive_host("cityoflynn.hosted2.civiclive.com")
    # A host that merely CONTAINS the suffix as a substring elsewhere
    # (not a real subdomain relationship) must not match.
    assert not is_civiclive_host("nothosted.civiclive.com.evil.example")
    assert not is_civiclive_host("civiclive.com")


async def test_resolve_follows_real_redirect_off_civiclive_to_granicus():
    # Modeled on Auburn, WA's confirmed real shape: a CivicLive page
    # 302-redirects off civiclive.com entirely to an already-supported
    # platform (Auburn's real target is CivicClerk; Granicus is used here
    # to reuse the existing, already-verified fixture/route set from
    # test_civicplus.py's own single-video delegation test, since the
    # mechanism being tested -- "follow the redirect, delegate to
    # whatever's actually there" -- is the same regardless of which
    # downstream platform it lands on).
    civiclive_url = "https://example.hosted.civiclive.com/city_hall/agendas___minutes"
    granicus_url = "https://westlakevillage.granicus.com/player/clip/1201?view_id=1"
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        civiclive_url: FakeResponse(
            status=302,
            url=civiclive_url,
            headers={"Location": granicus_url},
        ),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://westlakevillage.granicus.com/videos/1201/captions.vtt": FakeResponse(
            status=404
        ),
        "https://westlakevillage.granicus.com/AgendaViewer.php?clip_id=1201&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await CivicLiveAssetFinder().resolve(civiclive_url)

    # A successful off-domain delegation's own platform identity must
    # survive, never masked by "civiclive" -- same convention as
    # destinyhosted.py's identical test.
    assert result.platform == "granicus"
    assert result.external_id == "granicus:westlakevillage.granicus.com:1201"


async def test_resolve_degrades_gracefully_when_redirect_target_has_no_specific_meeting():
    # Real, confirmed-live shape (2026-09-01): Auburn, WA's own "Agendas &
    # Minutes" page 302-redirects to auburnwa.portal.civicclerk.com --
    # CivicClerk's bare portal HOME, no event id in the path at all.
    # CivicClerkAssetFinder.resolve() raises a bare ValueError for that
    # shape (confirmed live via this exact dry run) rather than declining
    # gracefully -- this must degrade to an honest result, not propagate
    # a raw crash, since a redirect landing on a portal home rather than
    # one specific meeting is a routine, expected outcome for this
    # adapter (CivicLive's own per-meeting linking is client-rendered).
    from app.platforms.civicclerk import CivicClerkAssetFinder

    register(CivicClerkAssetFinder())
    civiclive_url = "https://auburn.hosted.civiclive.com/city_hall/agendas___minutes"
    portal_home_url = "https://auburnwa.portal.civicclerk.com"

    routes = {
        civiclive_url: FakeResponse(
            status=302,
            url=civiclive_url,
            headers={"Location": portal_home_url},
        ),
        portal_home_url: FakeResponse(status=200, text="", url=portal_home_url),
    }

    with mock_session(routes):
        result = await CivicLiveAssetFinder().resolve(civiclive_url)

    assert result.platform == "civiclive"
    assert result.source_url == civiclive_url
    assert result.video_url is None
    assert any("couldn't find a specific meeting" in w for w in result.video_warnings)


async def test_real_escalon_agenda_page_finds_no_per_meeting_video():
    # Real, raw-saved live page (escalon.hosted.civiclive.com/government/
    # agenda_packets/city_council_agendas_and_minutes, fetched 2026-09-01)
    # -- see tests/fixtures/civiclive/README.md. The real per-meeting
    # agenda table is client-rendered and absent from this raw HTML; the
    # only video reference present is a page-wide YouTube *channel* link,
    # which must not be mistaken for a specific meeting's video.
    url = (
        "https://escalon.hosted.civiclive.com/government/agenda_packets/"
        "city_council_agendas_and_minutes"
    )
    html = load_fixture("civiclive", "escalon_city_council_agendas.html")
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CivicLiveAssetFinder().resolve(url)

    assert result.platform == "civiclive"
    assert result.video_url is None
    assert result.best_effort is True


async def test_channel_link_alone_is_not_treated_as_a_video():
    # Synthetic HTML, but the exact real confirmed shape (Auburn/Escalon,
    # both channel-only): a bare youtube.com/channel/... or /@handle link
    # must never be mistaken for a specific meeting's video --
    # YouTubeAssetFinder's own _VIDEO_ID_RE structurally can't match a
    # channel/handle URL (no watch?v=/embed//shorts//live//v/ shape, no
    # 11-char id), the same guarantee civicplus.py's own
    # _is_real_video_link() fix relies on.
    url = "https://example.hosted.civiclive.com/city_hall/agendas"
    html = (
        "<html><body>"
        '<a href="https://www.youtube.com/@watchexample">Watch Live</a>'
        '<a href="https://www.youtube.com/channel/UCabc123">Our Channel</a>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CivicLiveAssetFinder().resolve(url)

    assert result.platform == "civiclive"
    assert result.video_url is None


async def test_resolve_finds_a_real_single_youtube_video_still_on_civiclive():
    # Synthetic HTML (no live CivicLive tenant with a server-rendered,
    # per-meeting embedded YouTube video has been found yet -- see
    # civiclive.py's own module docstring) modeled on the real, confirmed
    # embed shape GenericFallbackAssetFinder already handles elsewhere
    # (a plain youtube.com/embed/{id} iframe). Proves the positive path:
    # when a real video IS present, delegation attributes the result to
    # "youtube", not masked by "civiclive".
    url = "https://example.hosted.civiclive.com/city_hall/some_meeting_page"
    html = (
        "<html><body>"
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        "</body></html>"
    )
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CivicLiveAssetFinder().resolve(url)

    assert result.platform == "youtube"
    assert result.video_url == "https://www.youtube.com/embed/dQw4w9WgXcQ"
