import pytest

from app.platforms.base import CalendarPageError, register
from app.platforms.civicplus import CivicPlusAssetFinder
from app.platforms.granicus import GranicusAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _register_granicus():
    register(GranicusAssetFinder())


async def test_listing_with_multiple_videos_raises_pick_list():
    # Reconstructed from the exact real markup shape confirmed on
    # ca-westlakevillage.civicplus.com 2026-08-06 -- see
    # tests/fixtures/civicplus/README.md for why this isn't a raw-saved
    # live page (the original site has since been restructured).
    url = "https://example.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_listing.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    candidates = exc_info.value.candidates
    assert len(candidates) == 2
    assert all("granicus.com" in c["url"] for c in candidates)
    assert candidates[0]["date"] == "2026-04-08"
    assert candidates[0]["title"] == "City Council Regular Meeting"


async def test_real_durham_listing_page_parses_correctly():
    # Real, raw-saved live page -- nc-durham.civicplus.com/AgendaCenter/
    # City-Council-4, fetched live 2026-08-30. This is the confirmed real
    # sample the class docstring and BACKLOG.md reference; unlike
    # agendacenter_listing.html above (hand-built after the original
    # ca-westlakevillage sample went DNS-dead), this fixture is the actual
    # HTML the site served, with only <script>/<style>/comment blocks
    # stripped to keep the file a reasonable size -- every
    # tr.catAgendaRow/td.media/h3>strong/td>p>a element is untouched.
    #
    # Live-confirmed at fetch time: 31 tr.catAgendaRow rows, 22 with a
    # real video link in td.media (21 Granicus + 1 YouTube). One specific
    # link spot-checked live before saving: durham.granicus.com/player/
    # clip/3313 ("Joint City County Meeting", June 9, 2026).
    url = "https://nc-durham.civicplus.com/AgendaCenter/City-Council-4"
    html = load_fixture("civicplus", "durham_agendacenter_citycouncil.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    candidates = exc_info.value.candidates
    assert len(candidates) == 22
    assert exc_info.value.jurisdiction_hint == "Durham, NC"

    granicus_candidates = [c for c in candidates if "granicus.com" in c["url"]]
    youtube_candidates = [c for c in candidates if "youtube.com" in c["url"]]
    assert len(granicus_candidates) == 21
    assert len(youtube_candidates) == 1

    clip_3313 = next(
        c for c in candidates if "durham.granicus.com/player/clip/3313" in c["url"]
    )
    assert clip_3313["title"] == "Joint City County Meeting"
    assert clip_3313["date"] == "2026-06-09"


async def test_listing_with_single_video_delegates_to_granicus():
    url = "https://example.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_single.html")
    granicus_url = "https://westlakevillage.granicus.com/player/clip/1201?view_id=1"
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://westlakevillage.granicus.com/videos/1201/captions.vtt": FakeResponse(
            status=404
        ),
        "https://westlakevillage.granicus.com/AgendaViewer.php?clip_id=1201&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.platform == "granicus"
    assert result.external_id == "granicus:westlakevillage.granicus.com:1201"


async def test_no_video_rows_returns_warning():
    url = "https://example.civicplus.com/AgendaCenter"
    html = "<html><body><table></table></body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.platform == "civicplus"
    assert any("no video" in w.lower() for w in result.video_warnings)


async def test_no_video_rows_still_carries_subdomain_jurisdiction():
    # Real gap fixed 2026-08-27: a tenant with no video-bearing row at all
    # previously got jurisdiction=None even when the subdomain itself
    # validates -- there's no reason to throw that away just because
    # there's no video to delegate to.
    url = "https://md-westminster.civicplus.com/AgendaCenter"
    html = "<html><body><table></table></body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.jurisdiction == "Westminster, MD"
    assert any("no video" in w.lower() for w in result.video_warnings)


# _jurisdiction_from_subdomain() coverage. Real subdomains throughout --
# ca-westlakevillage is this module's own confirmed real sample (see the
# class docstring); the rest are real tenants from the 2026-08-27
# CivicPlus multi-candidate scan (BACKLOG_DONE.md).
@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://ca-westlakevillage.civicplus.com/AgendaCenter",
            "Westlake Village, CA",
        ),
        (
            "https://md-westminster.civicplus.com/AgendaCenter",
            "Westminster, MD",
        ),
        ("https://ri-eastgreenwich.civicplus.com/AgendaCenter", "East Greenwich, RI"),
        # No hyphen at all -- not the real convention, declines rather
        # than guessing (also covers this file's own fake "example"
        # subdomain used throughout the tests above).
        ("https://example.civicplus.com/AgendaCenter", None),
        # Hyphenated, but the prefix isn't a real 2-letter state code.
        ("https://not-a-state.civicplus.com/AgendaCenter", None),
        # Real state prefix, but the name half is too acronym-heavy for
        # wordninja to split into anything Census recognizes -- an honest
        # decline, not a bug (same two real tenants confirmed live).
        (
            "https://tn-hamiltoncountywwta.civicplus.com/AgendaCenter",
            None,
        ),
        (
            "https://ga-fultoncountymagistratecourt.civicplus.com/AgendaCenter",
            None,
        ),
    ],
)
def test_jurisdiction_from_subdomain(url, expected):
    assert CivicPlusAssetFinder._jurisdiction_from_subdomain(url) == expected


async def test_subdomain_jurisdiction_overrides_delegated_platforms_own_guess(
    monkeypatch,
):
    # Real, confirmed-live incident this fix closes: YouTube's own
    # jurisdiction guess for a real Westminster, MD government channel
    # ("City of Westminster, Maryland") declines to validate on its own,
    # since Westminster is also a real place in CA/CO/SC/VT -- see
    # youtube.py's _jurisdiction() and BACKLOG_DONE.md. CivicPlus's own
    # subdomain already carries the disambiguating state, so it should
    # win outright, not just fill in when the delegated guess is empty.
    from app.platforms.base import register
    from app.platforms.youtube import YouTubeAssetFinder

    register(YouTubeAssetFinder())

    url = "https://md-westminster.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_single.html")
    # The fixture's own single video row is a Granicus link, which
    # already validates jurisdiction correctly on its own -- swap it for
    # a plain YouTube link here so this test actually exercises the case
    # where the delegated platform's own guess would otherwise be None.
    youtube_html = html.replace(
        "https://westlakevillage.granicus.com/player/clip/1201?view_id=1",
        "https://www.youtube.com/watch?v=abcdefghijk",
    )
    routes = {url: FakeResponse(status=200, text=youtube_html, url=url)}

    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Some Meeting",
            "uploader": "City of Westminster, Maryland",
            "upload_date": "20260101",
        },
    )

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.platform == "youtube"
    assert result.jurisdiction == "Westminster, MD"
