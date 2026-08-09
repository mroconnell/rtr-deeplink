import pytest

from app.platforms.base import (
    UnsupportedPlatformError,
    detect_platform,
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
