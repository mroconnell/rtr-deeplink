"""Tests for WO-1054 (Meeting Finder hub/link-context fixes + WordPress
lister), covering the six rules from Ryan's 2026-09-24 human-browsing
notes (see docs/MEETING_FINDER.md and this WO's own module comments for
the full write-up of each):

  1. Link CONTEXT (not just link text) makes a strong hop, off-site
     included -- `hop.py`'s `_rescue_link_context_broadcast_score()`.
  2. A per-meeting YouTube table is a rank-5 meeting list -- already
     built (WO-1027/1030); not re-tested here.
  3. Cablecast Connect (a WordPress plugin) is listed directly --
     `identify.py`'s `_cablecast_connect_signal()` +
     `listing.py`'s `_list_via_cablecast_connect()`.
  4. A broken TelVue playlist link falls back to the same org token's
     `/home` listing -- `resolve.py`'s `_telvue_broken_media_fallback()`.
  5. A shared hub is filtered to THIS government's own meetings --
     `pick.py`'s `filter_candidates_to_government()`.
  6. A generic WordPress site is listed via its own REST API --
     `identify.py`'s `_wordpress_signal()` + `listing.py`'s
     `_list_via_wordpress()`.

Fixtures under `tests/fixtures/wo1054/` are real, trimmed excerpts fetched
live 2026-09-24 from `townsquare.tv` (Mendota Heights, MN's real Cablecast
Connect station, Ryan's own browsing note) -- not hand-built HTML. The
Lake Oswego, OR paragraph text quoted in the hop.py test below is Ryan's
own quoted note, not independently re-fetched this session, so that one
test is synthetic per CLAUDE.md's convention (real, confirmed phrasing,
hand-assembled page shape).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.platforms.meeting_finder import identify as identify_mod
from app.platforms.meeting_finder import listing
from app.platforms.meeting_finder.fetch import FetchResult, Fetcher
from app.platforms.meeting_finder.hop import rank_hops
from app.platforms.meeting_finder.models import (
    Candidate,
    OUTCOME_HUB_OTHER_GOVERNMENT,
)
from app.platforms.meeting_finder.pick import filter_candidates_to_government

FIXTURES = Path(__file__).parent / "fixtures" / "wo1054"


def _fetch_result(url: str, html: str, *, status: int = 200) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=status,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )


@pytest.fixture
def fetcher():
    return Fetcher(max_fetches=12, allow_headless=False, allow_wayback=False)


# --- Rule 1: link context, not just link text (hop.py) ------------------


def test_rank_hops_rescues_offsite_link_from_nearby_broadcast_context():
    """Real Lake Oswego, OR shape (Ryan's own note, 2026-09-24):
    `ci.oswego.or.us/citycouncil/city-council-meetings` names its cable
    partner in a paragraph -- "Tualatin Valley Community Television
    (TVCTV) streams the meetings and airs replays. Check their website"
    -- whose own link text is generic ("Check their website" ->
    tvctv.org). Synthetic page shape (see module docstring), real quoted
    phrasing."""
    page = _fetch_result(
        "https://www.ci.oswego.or.us/citycouncil/city-council-meetings",
        """
        <html><body>
        <p>Agendas and minutes are posted here after each meeting.</p>
        <p>Tualatin Valley Community Television (TVCTV) streams the
        meetings and airs replays. <a href="https://tvctv.org">Check
        their website</a> for the schedule.</p>
        </body></html>
        """,
    )
    hops = rank_hops(page, limit=8)
    assert any(h.url == "https://tvctv.org" for h in hops)


def test_link_context_rescue_does_not_fire_without_broadcast_wording():
    """A generic off-site link with no nearby broadcast phrase gets no
    rescue from this rule -- it should rank far below (or simply not
    beat) a real on-site hub link, not be treated as a strong hop just
    for being off-site."""
    page = _fetch_result(
        "https://www.example.gov/",
        """
        <html><body>
        <p>For general information about our city, visit
        <a href="https://unrelated-example.org">our partner site</a>.</p>
        <a href="/1604/Meetings-Agendas-Minutes-Video-on-Demand">Meetings,
        Agendas, Minutes &amp; Video on Demand</a>
        </body></html>
        """,
    )
    hops = rank_hops(page, limit=8)
    assert hops, "expected at least the real hub link to rank"
    assert hops[0].url.endswith("Video-on-Demand")


# --- Rule 3: Cablecast Connect (identify.py + listing.py) ----------------


def test_identify_recognizes_cablecast_connect_page():
    html = (FIXTURES / "townsquare_site_page_excerpt.html").read_text()
    signal = identify_mod._cablecast_connect_signal(
        html, "https://townsquare.tv/programs/site/mendota-heights-8/"
    )
    assert signal is not None
    assert signal.platform == "cablecast_connect"
    assert signal.url == "https://townsquare.tv/programs/site/mendota-heights-8/"
    assert signal.rank == identify_mod.RANK_VENDOR_LINK


@pytest.mark.asyncio
async def test_list_via_cablecast_connect_unwraps_show_pages_to_real_video(fetcher):
    site_html = (FIXTURES / "townsquare_site_page_excerpt.html").read_text()
    show_html = (FIXTURES / "townsquare_show_page_excerpt.html").read_text()
    account_url = "https://townsquare.tv/programs/site/mendota-heights-8/"
    show_url = (
        "https://townsquare.tv/programs/show/"
        "mendota-heights-city-council-meeting-of-september-15-2026-8-5977/"
    )

    async def fake_fetch(url: str, *, need_links: bool = True):
        if url == account_url:
            return _fetch_result(url, site_html)
        if url == show_url:
            return _fetch_result(url, show_html)
        # The other show row on the page -- no fixture for its own show
        # page, so it degrades to "no iframe found" (skipped) rather than
        # erroring out.
        return _fetch_result(url, "<html><body>no player here</body></html>")

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "cablecast_connect", account_url, fetcher, limit=5
        )

    assert result.lister == "cablecast_connect"
    assert result.outcome is None
    urls = [c.url for c in result.candidates]
    assert (
        "https://reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=5977&site=8" in urls
    )
    winner = next(
        c
        for c in result.candidates
        if c.url
        == "https://reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=5977&site=8"
    )
    assert winner.platform == "cablecast"
    assert winner.has_video_hint is True
    assert winner.date == "2026-09-15"
    assert winner.source_url == show_url


@pytest.mark.asyncio
async def test_list_via_cablecast_connect_declines_for_other_platforms(fetcher):
    assert (
        await listing._list_via_cablecast_connect(
            "granicus", "https://example.granicus.com/", fetcher, 5
        )
        is None
    )


# --- Rule 4: broken TelVue playlist -> fall back to /home (resolve.py) --


@pytest.mark.asyncio
async def test_telvue_broken_media_fallback_lists_the_orgs_home_page():
    from app.platforms.meeting_finder import resolve as resolve_mod

    broken = Candidate(
        url=(
            "https://videoplayer.telvue.com/player/"
            "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru/playlists/4807/media/698580"
        ),
        title=None,
        date=None,
        platform="telvue",
        source_phase="scan",
        lister="scan_media",
    )

    async def fake_telvue_walker(hub_url: str):
        assert "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru" in hub_url
        return [
            {
                "url": (
                    "https://videoplayer.telvue.com/player/"
                    "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru/media/700001"
                ),
                "title": "College Township Board Meeting",
                "date": None,
            }
        ]

    with patch(
        "app.platforms.meeting_finder.resolve.passive_verify._telvue_walker",
        side_effect=fake_telvue_walker,
    ):
        fallback = await resolve_mod._telvue_broken_media_fallback(broken, set())

    assert len(fallback) == 1
    assert fallback[0].url.endswith("/media/700001")
    assert fallback[0].lister == "telvue_playlist_fallback"
    assert fallback[0].has_video_hint is True


@pytest.mark.asyncio
async def test_telvue_broken_media_fallback_only_fires_once_per_org():
    from app.platforms.meeting_finder import resolve as resolve_mod

    broken = Candidate(
        url="https://videoplayer.telvue.com/player/abc123/playlists/1/media/1",
        platform="telvue",
        source_phase="scan",
        lister="scan_media",
    )
    tried: set = {"abc123"}
    calls = []

    async def fake_telvue_walker(hub_url: str):
        calls.append(hub_url)
        return []

    with patch(
        "app.platforms.meeting_finder.resolve.passive_verify._telvue_walker",
        side_effect=fake_telvue_walker,
    ):
        fallback = await resolve_mod._telvue_broken_media_fallback(broken, tried)

    assert fallback == []
    assert calls == []  # already tried -- no second fetch


@pytest.mark.asyncio
async def test_telvue_broken_media_fallback_ignores_non_telvue_candidates():
    from app.platforms.meeting_finder import resolve as resolve_mod

    non_telvue = Candidate(
        url="https://example.granicus.com/clip/1",
        platform="granicus",
        source_phase="scan",
        lister="scan_media",
    )
    assert await resolve_mod._telvue_broken_media_fallback(non_telvue, set()) == []


# --- Rule 5: shared hub -> only this government's own meetings (pick.py) --


def _cand(title, url="https://example.com/m"):
    return Candidate(url=url, title=title, date=None, platform="telvue")


def test_filter_keeps_all_when_no_gov_name_given():
    candidates = [_cand("Borough of Bellefonte - Council")]
    kept, note = filter_candidates_to_government(candidates, None)
    assert kept == candidates
    assert note is None


def test_filter_drops_only_other_governments_meetings():
    """Real College Township PA / Bellefonte PA shape (shared Centre
    County C-NET TelVue org token) -- College Township's own meeting is
    kept, Bellefonte's own is dropped."""
    own = _cand("College Township Board of Supervisors Meeting")
    other = _cand("Borough of Bellefonte - Council")
    kept, note = filter_candidates_to_government([own, other], "College Township")
    assert kept == [own]
    assert note is None


def test_filter_does_not_confuse_college_township_with_state_college():
    """Real live regression, confirmed 2026-09-24: College Township, PA's
    own shared TelVue token also lists the Borough of STATE COLLEGE, PA's
    meetings -- a genuinely different real municipality whose name
    happens to also contain the bare word "college". A first version of
    this filter (plain word-overlap) let "Borough of State College -
    Council" through as if it were College Township's own meeting, since
    both names share that one word. `_place_core()`'s phrase-level
    comparison ("state college" vs "college") must not treat these as the
    same place."""
    own = _cand("College Township Board of Supervisors Meeting")
    other = _cand("Borough of State College - Council")
    kept, note = filter_candidates_to_government([own, other], "College township")
    assert kept == [own]
    assert note is None

    # And the true "hub carries other governments" case when ONLY the
    # State College meeting is on offer.
    kept2, note2 = filter_candidates_to_government([other], "College township")
    assert kept2 == []
    assert "State College" in (note2 or "")


def test_filter_reports_hub_other_government_when_everything_is_foreign():
    """Real Nashwauk MN / Cohasset MN shape."""
    other = _cand("Cohasset City Council")
    kept, note = filter_candidates_to_government([other], "Nashwauk")
    assert kept == []
    assert note is not None
    assert "Cohasset City Council" in note


def test_filter_keeps_ambiguous_untitled_rows_never_manufactures_emptiness():
    """A title with no governing-body word at all ("Budget Workshop", a
    bare date) is never treated as evidence of another government --
    Ryan's "keep at least one" posture. Real risk this guards: an
    ordinary same-government meeting titled by TYPE, not by place name,
    must not be misread as a foreign hub."""
    ambiguous = _cand("Budget Workshop")
    bare_date = _cand(None)
    kept, note = filter_candidates_to_government(
        [ambiguous, bare_date], "College Township"
    )
    assert kept == [ambiguous, bare_date]
    assert note is None


@pytest.mark.asyncio
async def test_list_account_reports_hub_other_government_outcome(fetcher):
    """End-to-end through `listing.list_account()`'s own gov_name
    filtering wrapper -- a lister that only ever finds another
    government's own meetings reports `OUTCOME_HUB_OTHER_GOVERNMENT`, not
    a bare `OUTCOME_NO_MEETING_NOR_VIDEO`."""
    from app.platforms import passive_verify

    async def fake_telvue_walker(hub_url: str):
        return [
            {
                "url": "https://videoplayer.telvue.com/player/tok/media/1",
                "title": "Borough of Bellefonte - Council",
                "date": None,
            }
        ]

    passive_verify._ensure_walkers_registered()
    before = dict(passive_verify._LISTING_WALKERS)
    passive_verify.register_listing_walker("telvue", fake_telvue_walker)
    try:
        result = await listing.list_account(
            "telvue",
            "https://videoplayer.telvue.com/player/tok/home",
            fetcher,
            gov_name="College Township",
        )
    finally:
        passive_verify._LISTING_WALKERS.clear()
        passive_verify._LISTING_WALKERS.update(before)

    assert result.candidates == []
    assert result.outcome == OUTCOME_HUB_OTHER_GOVERNMENT
    assert "Bellefonte" in (result.note or "")


# --- Rule 6: generic WordPress site, listed via its own REST API --------


def test_identify_recognizes_plain_wordpress_site_as_last_resort():
    html = (
        '<html><head><link rel="https://api.w.org/" '
        'href="https://wilderky.gov/wp-json/" /></head>'
        "<body>no other platform link anywhere on this page</body></html>"
    )
    signal = identify_mod._wordpress_signal(html)
    assert signal is not None
    assert signal.platform == "wordpress"
    assert signal.rank == identify_mod.RANK_WORDPRESS_ACCOUNT


def test_wordpress_signal_absent_without_the_rest_discovery_link():
    assert (
        identify_mod._wordpress_signal("<html><body>plain page</body></html>") is None
    )


@pytest.mark.asyncio
async def test_list_via_wordpress_finds_a_post_embedding_real_video(fetcher):
    origin = "https://wilderky.gov"
    meeting_search_url = (
        f"{origin}/wp-json/wp/v2/posts?search=meeting"
        f"&per_page=10&_fields=link,title,date,content"
    )
    video_search_url = (
        f"{origin}/wp-json/wp/v2/posts?search=video"
        f"&per_page=10&_fields=link,title,date,content"
    )
    posts_json = (
        '[{"link": "https://wilderky.gov/2026/09/council-meeting/", '
        '"title": {"rendered": "September Council Meeting"}, '
        '"date": "2026-09-08T19:00:00", '
        '"content": {"rendered": '
        '"<p>Watch it here: <a href=\\"https://vimeo.com/123456789\\">'
        'video</a></p>"}}]'
    )

    async def fake_fetch(url: str, *, need_links: bool = True):
        if url == meeting_search_url:
            return _fetch_result(url, posts_json)
        if url == video_search_url:
            return _fetch_result(url, "[]")
        raise AssertionError(f"unexpected fetch: {url}")

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "wordpress", f"{origin}/", fetcher, limit=10
        )

    assert result.lister == "wordpress_rest"
    assert result.outcome is None
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.url == "https://vimeo.com/123456789"
    assert candidate.title == "September Council Meeting"
    assert candidate.date == "2026-09-08"
    assert candidate.has_video_hint is True


@pytest.mark.asyncio
async def test_list_via_wordpress_real_wilder_ky_may_have_none(fetcher):
    """Ryan's own note: Wilder, KY may truthfully have no video-bearing
    post at all -- that's a real, valid finding (empty candidates), not a
    bug."""
    origin = "https://wilderky.gov"

    async def fake_fetch(url: str, *, need_links: bool = True):
        return _fetch_result(url, "[]")

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "wordpress", f"{origin}/", fetcher, limit=10
        )

    assert result.candidates == []
