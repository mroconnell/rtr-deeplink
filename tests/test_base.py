import pytest

from app.platforms.base import (
    UnsupportedPlatformError,
    detect_platform,
    find_platform_link,
    get_finder,
    register,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://sandiego.granicus.com/player/clip/123", "granicus"),
        ("https://maricopa.legistar.com/MeetingDetail.aspx?ID=1", "legistar"),
        ("https://legistar.council.nyc.gov/Calendar.aspx", "legistar"),
        ("https://clovisca.portal.civicclerk.com/event/20/media", "civicclerk"),
        ("https://ca-westlakevillage.civicplus.com/AgendaCenter", "civicplus"),
        ("https://lacity.primegov.com/Portal/Meeting?id=1", "primegov"),
        ("https://yountvilleca.new.swagit.com/videos/394093", "swagit"),
        ("https://dublin.ca.gov/swagit-video-player?video_id=1", "swagit"),
        ("https://richmond.escribemeetings.com/Meeting.aspx?Id=1", "escribe"),
        ("https://assembly.ca.gov/media/2026", "ca_legislature"),
        ("https://senate.ca.gov/media/2026", "ca_legislature"),
        ("https://www.youtube.com/watch?v=abc123", "youtube"),
        ("https://youtu.be/abc123", "youtube"),
        ("https://lims.minneapolismn.gov/MarkedAgenda/CI/6133", "lims"),
        ("https://www.slc.gov/council/march-3-2026-meeting-recap/", "slc"),
        ("https://slc.gov/council/may-5-2026-meeting-recap/", "slc"),
        # slc.gov's own non-recap pages are ordinary city-government
        # content this app has no reason to try to resolve -- confirmed
        # scoped to the "-meeting-recap" path pattern only, not the whole
        # domain.
        ("https://www.slc.gov/council/agendas/", "unknown"),
        ("https://example.com/some/random/page", "unknown"),
    ],
)
def test_detect_platform(url, expected):
    assert detect_platform(url) == expected


def test_get_finder_raises_for_unregistered_platform():
    with pytest.raises(UnsupportedPlatformError):
        get_finder("some_platform_never_registered")


def test_register_and_get_finder_roundtrip():
    class FakeFinder:
        platform_name = "fake_test_platform"

    finder = FakeFinder()
    register(finder)
    assert get_finder("fake_test_platform") is finder


def test_find_platform_link_finds_a_swagit_link_in_a_plain_a_tag():
    # Real shape confirmed live 2026-08-10: Austin, TX's council pages
    # link out to their Swagit-hosted video as a plain <a href>, not an
    # embed.
    html = '<html><body><a href="http://austintx.swagit.com/play/1/0/">Video</a></body></html>'
    result = find_platform_link(html, "https://www.austintexas.gov/council/2026/x-reg")
    assert result == ("http://austintx.swagit.com/play/1/0/", "swagit")


def test_find_platform_link_resolves_relative_hrefs_to_absolute():
    html = '<html><body><a href="/videos/1">Video</a></body></html>'
    # A relative href on its own domain never matches a real platform --
    # confirms urljoin() runs before detect_platform(), not that this
    # specific case matches (it correctly won't).
    assert find_platform_link(html, "https://example.gov/meeting") is None


def test_find_platform_link_checks_iframe_and_video_src_too():
    html = '<html><body><iframe src="https://city.granicus.com/player/clip/1"></iframe></body></html>'
    result = find_platform_link(html, "https://example.gov/meeting")
    assert result == ("https://city.granicus.com/player/clip/1", "granicus")


def test_find_platform_link_returns_none_for_unrecognized_links():
    html = '<html><body><a href="https://example.com/random">Random</a></body></html>'
    assert find_platform_link(html, "https://example.gov/meeting") is None


def test_find_platform_link_respects_exclude():
    # The real reason "exclude" exists: detect_platform()'s broad
    # "youtube.com" in netloc check also matches a bare channel/user
    # link, not just a real video -- callers with their own tighter,
    # video-ID-validated YouTube check exclude it here deliberately.
    html = '<html><body><a href="https://www.youtube.com/user/somechannel">Watch us</a></body></html>'
    assert find_platform_link(html, "https://example.gov/meeting") == (
        "https://www.youtube.com/user/somechannel",
        "youtube",
    )
    assert (
        find_platform_link(
            html, "https://example.gov/meeting", exclude=frozenset({"youtube"})
        )
        is None
    )


def test_find_platform_link_skips_same_page_fragment_anchors():
    # Real bug, confirmed live 2026-08-12: a same-page "#fragment" href
    # (e.g. an accessibility "skip to content" link, present on nearly
    # every Legistar page) resolves back to page_url itself via urljoin().
    # Without this check, a caller whose own platform isn't in `exclude`
    # gets its own page back as a "match" and recurses into resolving it
    # again -- unbounded recursion, confirmed on a real Columbus, OH
    # Legistar meeting with no other video link on the page.
    html = '<html><body><a href="#mainContent">Skip to main content</a></body></html>'
    assert (
        find_platform_link(
            html, "https://columbus.legistar.com/MeetingDetail.aspx?ID=1"
        )
        is None
    )


def test_find_platform_link_skips_same_page_absolute_self_link():
    # Same protection, for an absolute self-referencing href with a
    # fragment rather than a bare "#fragment" -- both resolve to the same
    # URL once the fragment is stripped.
    page_url = "https://columbus.legistar.com/MeetingDetail.aspx?ID=1"
    html = f'<html><body><a href="{page_url}#mainContent">Skip</a></body></html>'
    assert find_platform_link(html, page_url) is None
