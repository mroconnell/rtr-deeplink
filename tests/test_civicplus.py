import pytest

from app.platforms.base import CalendarPageError, NoVideoCandidateFound, register
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
    # Real td.downloads shape for this exact row, confirmed live: an
    # ?html=true rendition, a bare-PDF rendition, and a ?packet=true
    # rendition -- agenda_link prefers HTML, packet_link is the
    # deliberately separate, much larger document.
    assert clip_3313["agenda_link"] == (
        "https://nc-durham.civicplus.com/AgendaCenter/ViewFile/Agenda/"
        "_06092026-3475?html=true"
    )
    assert clip_3313["packet_link"] == (
        "https://nc-durham.civicplus.com/AgendaCenter/ViewFile/Agenda/"
        "_06092026-3475?packet=true"
    )

    # Row 3554 (Aug 20, 2026 work session) has no video link at all, so
    # it's correctly excluded from `candidates` entirely -- confirming
    # this doesn't crash on a video-less row that still has real
    # agenda/packet links, since _find_video_rows() never gets far
    # enough to extract them for a skipped row.
    assert not any(c["date"] == "2026-08-20" for c in candidates)


async def test_real_desoto_listing_page_raises_no_video_candidate_found():
    # Real, raw-saved live page -- ks-desoto.civicplus.com/AgendaCenter,
    # fetched live 2026-09-01. This is the real regression case for the
    # bug fixed alongside this test: `_find_video_rows()` used to accept
    # any `td.media` link whose domain `detect_platform()` recognized,
    # with no check that a YouTube-domain link was an actual single-video
    # URL. Every `td.media` link on this real page is a YouTube channel
    # (`/user/DeSotoKansas/live.`) or `@handle` (`@DeSotoKansas`) link --
    # zero real single-meeting videos anywhere on the page (confirmed by
    # inspecting the raw fixture directly). Before that fix, 12 of those
    # channel/handle links passed the old filter and were returned as
    # candidates; `CivicPlusAssetFinder().resolve()` raised
    # `CalendarPageError` with a pick-list of 12 candidates that would
    # *all* fail with `ValueError('Could not find a YouTube video ID in
    # ...')` the moment anything tried to resolve one -- confirmed live
    # via `resolve_via_platform()` before that fix landed.
    #
    # This exact tenant was one of 28 real jurisdictions a 2026-08-31 DNS
    # enumeration dry run against 1,118 fresh CivicPlus tenants found
    # failing with this error when picking the newest multi-candidate row
    # -- see civicplus.py's `_is_real_video_link()` docstring.
    #
    # Updated 2026-09-07 alongside the `NoVideoCandidateFound` fix: this
    # page has 33 real (title+date) rows -- the channel-link filter above
    # means none of the first `_RETRY_LIMIT` (5) has a real video link,
    # so `resolve()` now raises `NoVideoCandidateFound` after checking
    # exactly 5, rather than falling back to a fabricated `ResolvedMeeting`
    # keyed to the bare listing URL.
    url = "https://ks-desoto.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "ks_desoto_agendacenter.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(NoVideoCandidateFound) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    assert exc_info.value.candidates_checked == 5
    assert exc_info.value.jurisdiction_hint == "Desoto, KS"


async def test_youtube_channel_link_excluded_from_video_row_candidates():
    # Synthetic, per this repo's convention: the payload shape (a
    # tr.catAgendaRow/td.media row) is copied from the real, confirmed
    # markup in durham_agendacenter_citycouncil.html and
    # ks_desoto_agendacenter.html above, and the two URLs used are both
    # real, independently-verified ones -- durham.granicus.com/player/
    # clip/3313 (spot-checked live 2026-08-30, see the durham test above)
    # and youtube.com/@DeSotoKansas (the real DeSoto, KS channel link
    # confirmed live 2026-08-31 to have no video ID, see the test above)
    # -- rather than an invented URL shape. Exercises the one case neither
    # real fixture covers on its own: a channel-link row *and* a real
    # single-video row on the same page, confirming the channel link is
    # dropped rather than merely losing a tiebreak, and the real video
    # still resolves as the sole remaining candidate. Dates added
    # 2026-09-07 alongside the `_find_candidate_rows()` generalization,
    # which now requires a real title AND a real date to count as a
    # candidate at all (previously date wasn't required) -- these two
    # rows need one each to keep being recognized as real candidates.
    html = """
    <table>
      <tr class="catAgendaRow">
        <td><h3><strong>Sep 01, 2026</strong></h3><p><a>Newer Meeting (channel link only)</a></p></td>
        <td class="media"><a href="https://www.youtube.com/@DeSotoKansas">Video</a></td>
      </tr>
      <tr class="catAgendaRow">
        <td><h3><strong>Aug 15, 2026</strong></h3><p><a>Older Meeting (real video)</a></p></td>
        <td class="media">
          <a href="https://durham.granicus.com/player/clip/3313">Video</a>
        </td>
      </tr>
    </table>
    """
    url = "https://example.civicplus.com/AgendaCenter"
    granicus_url = "https://durham.granicus.com/player/clip/3313"
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
    }

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    # The channel link never became a candidate at all, so with exactly
    # one real candidate left, resolve() delegates directly instead of
    # raising CalendarPageError with a pick-list.
    assert result.platform == "granicus"
    assert result.source_url == granicus_url


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
    # agenda_link/packet_link come from THIS row's own td.downloads, not
    # from whatever the delegated Granicus page happened to find --
    # confirms the threading in resolve() survives resolve_via_platform().
    assert result.agenda_link == (
        "https://example.civicplus.com/AgendaCenter/ViewFile/Agenda/"
        "_04082026-1001?html=true"
    )
    assert result.packet_link == (
        "https://example.civicplus.com/AgendaCenter/ViewFile/Agenda/"
        "_04082026-1001?packet=true"
    )


async def test_self_hosted_domain_parses_own_agendacenter_html():
    # Real bug fixed 2026-09-07: most real CivicPlus tenants are
    # white-labeled onto the government's own domain and never touch
    # civicplus.com at all -- confirmed live (direct fetch, no redirect)
    # on www.trentonnj.org, www.cityofazle.org, www.ci.brownfield.tx.us,
    # among others. The old domain gate (`"civicplus.com" not in
    # final_url netloc`) treated every one of these as if it must have
    # redirected to some other real platform, diverting to
    # `resolve_via_platform()` -- which detects a plain gov domain as
    # "unknown" and hands it to generic_fallback.py, never reaching this
    # class's own row-parsing at all. Same fixture as
    # `test_listing_with_single_video_delegates_to_granicus` above, just
    # served from a self-hosted, non-civicplus domain -- confirms the
    # adapter's own `_find_candidate_rows`/delegate logic now runs
    # regardless of which domain served the HTML.
    url = "https://www.example-gov.org/AgendaCenter"
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
    assert result.agenda_link == (
        "https://www.example-gov.org/AgendaCenter/ViewFile/Agenda/"
        "_04082026-1001?html=true"
    )


async def test_self_hosted_domain_with_no_video_raises_no_video_candidate_found():
    # Same self-hosted-domain gap as above, exercised against the "no
    # video yet" outcome specifically -- confirms `NoVideoCandidateFound`
    # (not a generic_fallback.py fabrication) is what a self-hosted tenant
    # with real rows but no video gets too, not just the successful-
    # delegation case above.
    url = "https://www.example-gov.org/AgendaCenter"
    html = """
    <table>
      <tr class="catAgendaRow">
        <td><h3><strong>Sep 01, 2026</strong></h3><p><a>Newest Meeting</a></p></td>
        <td class="media"></td>
      </tr>
    </table>
    """

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(NoVideoCandidateFound) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    assert exc_info.value.candidates_checked == 1


async def test_final_url_redirected_to_different_platform_still_defers():
    # The gate's real remaining purpose: an AgendaCenter link that
    # 301-redirects straight to a different real platform's own page,
    # bypassing CivicPlus's HTML entirely (e.g. a government that's since
    # migrated off CivicPlus but left old links redirecting to the new
    # system). `detect_platform(final_url)` returning a real platform
    # (here "granicus", not "unknown" and not "civicplus") is what should
    # still trigger deferring to `resolve_via_platform()` instead of
    # trying to run CivicPlus's own row-parsing against a page that isn't
    # CivicPlus HTML at all.
    url = "https://example.civicplus.com/AgendaCenter"
    granicus_url = "https://durham.granicus.com/player/clip/3313"
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        # The initial fetch's *final* url (post-redirect) already lands on
        # Granicus's own domain -- the response body is irrelevant since
        # the gate diverts before any CivicPlus HTML is ever parsed.
        url: FakeResponse(status=200, text="<html></html>", url=granicus_url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
    }

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.platform == "granicus"
    assert result.source_url == granicus_url


async def test_no_candidate_rows_raises_no_video_candidate_found():
    # The true zero-candidates case (no tr.catAgendaRow at all, e.g. City
    # of Azle, TX) -- candidates_checked is 0 since there was nothing to
    # walk, distinguishing it (in principle, via the count) from a page
    # that has real rows but none with video yet.
    url = "https://example.civicplus.com/AgendaCenter"
    html = "<html><body><table></table></body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(NoVideoCandidateFound) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    assert exc_info.value.candidates_checked == 0


async def test_no_candidate_rows_still_carries_subdomain_jurisdiction():
    # Real gap fixed 2026-08-27: a tenant with no video-bearing row at all
    # previously got jurisdiction=None even when the subdomain itself
    # validates -- there's no reason to throw that away just because
    # there's no video to delegate to. Updated 2026-09-07: the "no video"
    # outcome is now a raised `NoVideoCandidateFound` rather than a
    # returned `ResolvedMeeting`, but the same jurisdiction_hint threading
    # still applies.
    url = "https://md-westminster.civicplus.com/AgendaCenter"
    html = "<html><body><table></table></body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(NoVideoCandidateFound) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    assert exc_info.value.jurisdiction_hint == "Westminster, MD"


async def test_real_candidates_with_no_video_raises_no_video_candidate_found():
    # Distinct from the true zero-candidates case above: real rows exist
    # (title + date), just none with video -- the City of Brownfield, TX
    # real-world shape (agendas but no video on any row). Confirms
    # candidates_checked reflects the real rows actually walked, not 0.
    url = "https://example.civicplus.com/AgendaCenter"
    html = """
    <table>
      <tr class="catAgendaRow">
        <td><h3><strong>Sep 01, 2026</strong></h3><p><a>Newest Meeting</a></p></td>
        <td class="media"></td>
      </tr>
      <tr class="catAgendaRow">
        <td><h3><strong>Aug 15, 2026</strong></h3><p><a>Older Meeting</a></p></td>
        <td class="media"></td>
      </tr>
    </table>
    """

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(NoVideoCandidateFound) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    assert exc_info.value.candidates_checked == 2


async def test_video_beyond_retry_limit_is_not_walked():
    # Confirms the retry limit is a real bound, not just documentation:
    # 6 real candidate rows, newest-first, where only the 6th (oldest,
    # beyond `_RETRY_LIMIT` == 5) has a real video link. resolve() should
    # give up after checking the first 5 rather than walking the whole
    # page, since a video that stale isn't worth surfacing as "the"
    # meeting for this listing page.
    url = "https://example.civicplus.com/AgendaCenter"
    no_video_row = """
      <tr class="catAgendaRow">
        <td><h3><strong>{date}</strong></h3><p><a>Meeting {date}</a></p></td>
        <td class="media"></td>
      </tr>
    """
    video_row = """
      <tr class="catAgendaRow">
        <td><h3><strong>Jan 01, 2026</strong></h3><p><a>Oldest Meeting</a></p></td>
        <td class="media">
          <a href="https://durham.granicus.com/player/clip/3313">Video</a>
        </td>
      </tr>
    """
    html = "<table>" + "".join(
        no_video_row.format(date=d)
        for d in (
            "Sep 05, 2026",
            "Sep 04, 2026",
            "Sep 03, 2026",
            "Sep 02, 2026",
            "Sep 01, 2026",
        )
    ) + video_row + "</table>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(NoVideoCandidateFound) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    assert exc_info.value.candidates_checked == 5


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


async def test_blocked_delegate_title_backfills_from_own_agenda_row(monkeypatch):
    # Real, confirmed-live gap fixed 2026-09-07 (caught by
    # scripts/nationwide_395_ingest.py's own smoke test): a delegated
    # YouTube video's title extraction can come back None (yt-dlp blocked
    # by anti-bot on this host -- see youtube.py's own docstring) even
    # though this row's own title/date, straight from the AgendaCenter
    # listing, was already sitting right here. Same fallback legistar.py's
    # own `page_info["title"]` already provides for the identical gap.
    from app.platforms.base import register
    from app.platforms.youtube import YouTubeAssetFinder

    register(YouTubeAssetFinder())

    url = "https://example.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_single.html")
    youtube_html = html.replace(
        "https://westlakevillage.granicus.com/player/clip/1201?view_id=1",
        "https://www.youtube.com/watch?v=abcdefghijk",
    )
    routes = {url: FakeResponse(status=200, text=youtube_html, url=url)}

    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {"title": None, "uploader": None, "upload_date": None},
    )

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.platform == "youtube"
    assert result.title == "City Council Regular Meeting"
    assert result.date == "2026-04-08"
