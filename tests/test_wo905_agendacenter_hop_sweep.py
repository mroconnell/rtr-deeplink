"""Tests for scripts/wo905_agendacenter_hop_sweep.py -- see that module's
own docstring for the full WO-905 background (BACKLOG.md's
"AgendaCenter-empty-shell population" entry, WO-226's 6-row hand-check).

These tests cover the script's own logic -- parsing, ranking, and the
decision rules that turn a fetched page into a reported outcome -- not a
live fetch (this WO's own report to the conductor carries that half: a
real, live run against the 6 named governments). Per CLAUDE.md's
synthetic-test convention, several fixtures below are hand-built rather
than raw-saved pages, but every one reuses a real, live-confirmed SHAPE
(a real anchor, a real redirect, a real platform URL) rather than an
invented one -- each test says which real government it is modeled on
and what was actually confirmed live 2026-09-19 building this WO.
"""

import aiohttp

import scripts.wo905_agendacenter_hop_sweep as wo905
from tests.aiohttp_mock import FakeResponse, mock_session


# ---------------------------------------------------------------------
# _is_bare_root / _needs_listing_discovery
# ---------------------------------------------------------------------


class TestIsBareRoot:
    def test_bare_domain_root_with_trailing_slash_is_bare(self):
        # Real, confirmed live 2026-09-19: Hoffman Estates, IL's own home
        # page links straight to this bare CivicClerk tenant root.
        assert wo905._is_bare_root("https://hoffmanestatesil.portal.civicclerk.com/")

    def test_bare_domain_root_without_trailing_slash_is_bare(self):
        assert wo905._is_bare_root("https://hoffmanestatesil.portal.civicclerk.com")

    def test_specific_event_path_is_not_bare(self):
        # Real, confirmed live 2026-09-19: Flagler Beach FL's real
        # CivicClerk conversion, reached via a home-page calendar entry.
        assert not wo905._is_bare_root(
            "https://flaglerbeachfl.portal.civicclerk.com/event/1509/files"
        )

    def test_query_string_makes_a_root_not_bare(self):
        assert not wo905._is_bare_root("https://example.civicclerk.com/?x=1")

    def test_known_generic_landing_document_is_bare(self):
        # Real, confirmed live 2026-09-19: Melrose, MA's real IQM2 hop
        # lands on this exact path -- a generic tenant landing page (it
        # links only Granicus's own marketing/support address and one
        # further hop to its own calendar, no meeting content itself),
        # structurally a root even though the URL carries a path.
        assert wo905._is_bare_root(
            "https://melrosecityma.iqm2.com/citizens/default.aspx"
        )

    def test_unrelated_specific_path_is_not_a_known_generic_landing_document(self):
        assert not wo905._is_bare_root(
            "https://example.iqm2.com/citizens/detail_meeting.aspx?id=42"
        )


class TestNeedsListingDiscovery:
    def test_bare_civicclerk_root_needs_listing(self):
        assert wo905._needs_listing_discovery(
            "civicclerk", "https://hoffmanestatesil.portal.civicclerk.com/"
        )

    def test_specific_civicclerk_event_does_not_need_listing(self):
        assert not wo905._needs_listing_discovery(
            "civicclerk",
            "https://flaglerbeachfl.portal.civicclerk.com/event/1509/files",
        )

    def test_bare_iqm2_landing_page_needs_listing(self):
        assert wo905._needs_listing_discovery(
            "iqm2", "https://melrosecityma.iqm2.com/citizens/default.aspx"
        )

    def test_youtube_channel_root_never_needs_listing(self):
        # youtube isn't in _LISTING_REQUIRED_PLATFORMS -- a channel/handle
        # IS the platform's own durable identity, not a placeholder page.
        assert not wo905._needs_listing_discovery(
            "youtube", "https://www.youtube.com/channel/UCgWC6TiLUWbrV9MaDGRq8Bw"
        )

    def test_bare_civicplus_root_never_needs_listing(self):
        # civicplus is excluded entirely elsewhere (_TRIVIAL_PLATFORMS) --
        # this just confirms the two checks are independent and neither
        # accidentally covers for the other.
        assert not wo905._needs_listing_discovery(
            "civicplus", "https://example.gov/AgendaCenter"
        )


# ---------------------------------------------------------------------
# _url_shape_hit
# ---------------------------------------------------------------------


class TestUrlShapeHit:
    def test_recognizes_a_real_platform_domain(self):
        hit = wo905._url_shape_hit(
            "https://flaglerbeachfl.portal.civicclerk.com/event/1509/files"
        )
        assert hit is not None
        assert hit.platform == "civicclerk"
        assert hit.needs_listing is False

    def test_bare_root_is_recognized_and_flagged(self):
        hit = wo905._url_shape_hit("https://hoffmanestatesil.portal.civicclerk.com/")
        assert hit is not None
        assert hit.platform == "civicclerk"
        assert hit.needs_listing is True

    def test_unrecognized_same_domain_shortcut_returns_none(self):
        # Real, confirmed live 2026-09-19: this is exactly Hagerstown
        # MD's own `/youtube` shortcut URL BEFORE it is fetched and
        # followed -- detect_platform() can't know it's YouTube from the
        # URL string alone, which is why this script fetches it rather
        # than stopping here.
        assert wo905._url_shape_hit("https://www.hagerstownmd.org/youtube") is None

    def test_self_hosted_agendacenter_path_is_civicplus_on_any_domain(self):
        # app/platforms/base.py's own path-based rule: ANY `/agendacenter`
        # path, on any domain, is "civicplus" -- real, confirmed live
        # 2026-09-19 on Harvey, IL's own www<->apex redirect target.
        hit = wo905._url_shape_hit("https://cityofharveyil.gov/AgendaCenter")
        assert hit is not None
        assert hit.platform == "civicplus"


# ---------------------------------------------------------------------
# _is_channel_shaped / _looks_like_decorative_embed / _is_youtube_search_link
# ---------------------------------------------------------------------


class TestIsChannelShaped:
    def test_channel_path(self):
        assert wo905._is_channel_shaped(
            "youtube", "https://www.youtube.com/channel/UCgWC6TiLUWbrV9MaDGRq8Bw"
        )

    def test_handle_path(self):
        assert wo905._is_channel_shaped(
            "youtube", "https://www.youtube.com/@HoffmanEstatesIL"
        )

    def test_user_path(self):
        assert wo905._is_channel_shaped(
            "youtube", "https://www.youtube.com/user/greenwoodvillage"
        )

    def test_embed_path_is_not_channel_shaped(self):
        assert not wo905._is_channel_shaped(
            "youtube", "https://www.youtube.com/embed/u51FbAjkZnk"
        )

    def test_non_youtube_platform_is_never_channel_shaped(self):
        assert not wo905._is_channel_shaped("vimeo", "https://vimeo.com/channel/x")


class TestLooksLikeDecorativeEmbed:
    def test_real_harvey_homepage_embed_is_suspect(self):
        # Real, confirmed live 2026-09-19: Harvey, IL's own home page
        # embeds `<iframe src="youtube.com/embed/u51FbAjkZnk..." title=
        # "YouTube video">` inside a styled hero card with no meeting
        # context at all -- the same false-positive class
        # scripts/wo361_find_hub.py's own `_is_decorative_hit()` was
        # built to catch on a different real government (WO-355). The
        # embedded video id even changed between two live fetches minutes
        # apart during this WO's own validation.
        assert wo905._looks_like_decorative_embed(
            "youtube",
            "https://www.youtube.com/embed/u51FbAjkZnk?si=aKRXKafqf-whTJJx",
            "home_page_anchor",
        )

    def test_channel_shaped_hit_is_never_suspect(self):
        assert not wo905._looks_like_decorative_embed(
            "youtube", "https://www.youtube.com/@thecityofharvey", "home_page_anchor"
        )

    def test_same_embed_reached_via_a_hop_link_is_not_suspect(self):
        # A different, stronger signal already (the site's own nav scored
        # it, or an icon-shortcut specifically labelled it) -- only a raw
        # scan of the hub/home page itself gets this extra caution.
        assert not wo905._looks_like_decorative_embed(
            "youtube",
            "https://www.youtube.com/embed/u51FbAjkZnk",
            "home_hop_link_page_anchor",
        )

    def test_non_video_platform_is_never_suspect(self):
        assert not wo905._looks_like_decorative_embed(
            "civicclerk",
            "https://x.portal.civicclerk.com/event/1/files",
            "home_page_anchor",
        )


class TestIsYoutubeSearchLink:
    def test_real_flaglerbeach_search_link_is_excluded(self):
        # Real, confirmed live 2026-09-19: Flagler Beach FL's own
        # AgendaCenter page links a "Watch us on YouTube" badge straight
        # to a search-results URL, not the government's real channel.
        assert wo905._is_youtube_search_link(
            "youtube",
            "https://www.youtube.com/results?search_query=flagler+beach+commission+meeting",
        )

    def test_channel_link_is_not_a_search_link(self):
        assert not wo905._is_youtube_search_link(
            "youtube", "https://www.youtube.com/channel/UCxyz"
        )

    def test_non_youtube_platform_is_never_a_search_link(self):
        assert not wo905._is_youtube_search_link(
            "vimeo", "https://vimeo.com/results?search_query=x"
        )


# ---------------------------------------------------------------------
# _is_actionable_hit / _add_hit / _pick_best
# ---------------------------------------------------------------------


class TestIsActionableHit:
    def test_civicplus_is_never_actionable(self):
        hit = wo905.CandidateHit(
            "civicplus", "https://example.gov/AgendaCenter", "hub_page_anchor", False
        )
        assert not wo905._is_actionable_hit(hit)

    def test_youtube_search_link_is_never_actionable(self):
        hit = wo905.CandidateHit(
            "youtube",
            "https://www.youtube.com/results?search_query=x",
            "hub_hop_link_page_anchor",
            False,
        )
        assert not wo905._is_actionable_hit(hit)

    def test_decorative_homepage_embed_is_not_actionable(self):
        hit = wo905.CandidateHit(
            "youtube", "https://www.youtube.com/embed/abc", "home_page_anchor", False
        )
        assert not wo905._is_actionable_hit(hit)

    def test_real_channel_hit_is_actionable(self):
        hit = wo905.CandidateHit(
            "youtube",
            "https://www.youtube.com/channel/UCxyz",
            "hub_icon_shortcut_redirect",
            False,
        )
        assert wo905._is_actionable_hit(hit)

    def test_specific_civicclerk_event_is_actionable(self):
        hit = wo905.CandidateHit(
            "civicclerk",
            "https://x.portal.civicclerk.com/event/1/files",
            "home_hop_link_page_anchor",
            False,
        )
        assert wo905._is_actionable_hit(hit)

    def test_bare_civicclerk_root_is_actionable_but_flagged(self):
        # needs_listing=True already carries the caveat -- being a bare
        # root doesn't make a hit non-actionable on its own, it just
        # means the eventual OUTCOME is "found, needs a listing check"
        # rather than a flat "found".
        hit = wo905.CandidateHit(
            "civicclerk", "https://x.portal.civicclerk.com/", "home_page_anchor", True
        )
        assert wo905._is_actionable_hit(hit)


class TestAddHit:
    def test_actionable_hit_is_appended_with_no_note(self):
        hits, notes = [], []
        hit = wo905.CandidateHit(
            "youtube",
            "https://www.youtube.com/channel/UCxyz",
            "hub_icon_shortcut_redirect",
            False,
        )
        wo905._add_hit(hits, notes, hit)
        assert hits == [hit]
        assert notes == []

    def test_non_actionable_hit_is_noted_not_appended(self):
        hits, notes = [], []
        hit = wo905.CandidateHit(
            "civicplus", "https://example.gov/AgendaCenter", "hub_page_anchor", False
        )
        wo905._add_hit(hits, notes, hit)
        assert hits == []
        assert len(notes) == 1
        assert "civicplus" in notes[0]
        assert "excluded" in notes[0]


class TestPickBest:
    def test_prefers_a_hit_that_needs_no_further_check(self):
        bare = wo905.CandidateHit("civicclerk", "https://x.civicclerk.com/", "a", True)
        specific = wo905.CandidateHit(
            "civicclerk", "https://x.civicclerk.com/event/1/files", "b", False
        )
        assert wo905._pick_best([bare, specific]) is specific

    def test_falls_back_to_the_first_hit_when_all_need_a_check(self):
        first = wo905.CandidateHit("civicclerk", "https://x.civicclerk.com/", "a", True)
        second = wo905.CandidateHit("swagit", "https://y.swagit.com/", "b", True)
        assert wo905._pick_best([first, second]) is first


# ---------------------------------------------------------------------
# _same_site / _round_robin
# ---------------------------------------------------------------------


class TestSameSite:
    def test_apex_and_www_are_the_same_site(self):
        # Real, confirmed live 2026-09-19: Hoffman Estates, IL's bare
        # apex 301s to its own www subdomain.
        assert wo905._same_site("hoffmanestates.org", "www.hoffmanestates.org")

    def test_reverse_direction_too(self):
        # Real, confirmed live 2026-09-19: Harvey, IL's www host 301s the
        # other way, down to its bare apex.
        assert wo905._same_site("www.cityofharveyil.gov", "cityofharveyil.gov")

    def test_identical_netlocs_are_the_same_site(self):
        assert wo905._same_site("example.gov", "example.gov")

    def test_different_hosts_are_not_the_same_site(self):
        assert not wo905._same_site("hoffmanestates.org", "www.youtube.com")

    def test_case_is_not_folded_by_this_helper_alone(self):
        # Callers are expected to .lower() first (sweep_one/_fetch_no_
        # external_redirect always do) -- documenting the contract here
        # rather than silently double-handling case inside the helper.
        assert not wo905._same_site("Example.gov", "example.gov")


class TestRoundRobin:
    def test_interleaves_position_by_position(self):
        a = [("a1", "x"), ("a2", "x")]
        b = [("b1", "y")]
        assert wo905._round_robin([a, b]) == [("a1", "x"), ("b1", "y"), ("a2", "x")]

    def test_empty_lists_are_skipped_cleanly(self):
        assert wo905._round_robin([[], []]) == []

    def test_single_list_is_unchanged(self):
        a = [("a1", "x")]
        assert wo905._round_robin([a]) == a

    def test_three_lists_of_uneven_length(self):
        a = [("a1", "x")]
        b = []
        c = [("c1", "z"), ("c2", "z")]
        assert wo905._round_robin([a, b, c]) == [("a1", "x"), ("c1", "z"), ("c2", "z")]


# ---------------------------------------------------------------------
# _find_icon_shortcut_links
# ---------------------------------------------------------------------


class TestFindIconShortcutLinks:
    def test_real_hagerstown_icon_only_link(self):
        # Real markup, captured live 2026-09-19 from
        # https://www.hagerstownmd.org/ (trimmed around the real anchor --
        # per CLAUDE.md's synthetic-test convention, the SHAPE is a real
        # capture, not an invented structure; the surrounding page is a
        # minimal made-up shell).
        html = """<html><body><nav>
        <a class="widgetDesc widgetGraphicLinksLink" href="/youtube"
           target="_blank" aria-label="YouTube opens in new window">
          <img src="/ImageRepository/Document?documentID=3929" alt="YouTube">
        </a>
        </nav></body></html>"""
        links = wo905._find_icon_shortcut_links(
            html, "https://www.hagerstownmd.org/AgendaCenter"
        )
        assert links == ["https://www.hagerstownmd.org/youtube"]

    def test_real_greenwood_village_labelled_link(self):
        # Real markup, captured live 2026-09-19 from
        # https://www.greenwoodvillage.com/ -- this one DOES carry
        # visible anchor text ("YouTube"), unlike Hagerstown's icon-only
        # version, confirming both real shapes are covered.
        html = '<html><body><a href="/youtube">YouTube</a></body></html>'
        links = wo905._find_icon_shortcut_links(
            html, "https://www.greenwoodvillage.com/AgendaCenter"
        )
        assert links == ["https://www.greenwoodvillage.com/youtube"]

    def test_off_domain_link_is_not_a_shortcut_candidate(self):
        # An off-domain link is already find_platform_link()'s/
        # find_hop_links()'s own job -- this helper only ever surfaces a
        # SAME-domain shortcut.
        html = '<html><body><a href="https://www.youtube.com/channel/UCxyz">Channel</a></body></html>'
        assert (
            wo905._find_icon_shortcut_links(html, "https://example.gov/AgendaCenter")
            == []
        )

    def test_unrelated_same_domain_link_is_not_a_shortcut(self):
        html = '<html><body><a href="/about-us">About</a></body></html>'
        assert (
            wo905._find_icon_shortcut_links(html, "https://example.gov/AgendaCenter")
            == []
        )

    def test_long_article_path_is_not_a_shortcut_even_with_video_in_it(self):
        # Narrow-path guard: a long, specific slug under /videos/ is an
        # ordinary content page, not an icon shortcut -- and carries no
        # matching label either.
        html = '<html><body><a href="/videos/some-real-article-slug">Read more</a></body></html>'
        assert (
            wo905._find_icon_shortcut_links(html, "https://example.gov/AgendaCenter")
            == []
        )

    def test_javascript_and_fragment_hrefs_are_ignored(self):
        html = """<html><body>
        <a href="#" aria-label="video">skip</a>
        <a href="javascript:void(0)" aria-label="stream">js</a>
        </body></html>"""
        assert (
            wo905._find_icon_shortcut_links(html, "https://example.gov/AgendaCenter")
            == []
        )


# ---------------------------------------------------------------------
# _classify_fetch
# ---------------------------------------------------------------------


class TestClassifyFetch:
    def test_dns_failure_is_dead(self):
        fr = wo905.ladder.FetchResult(error_kind="dns")
        assert wo905._classify_fetch(fr) == "dead"

    def test_timeout_is_timeout(self):
        fr = wo905.ladder.FetchResult(error_kind="timeout")
        assert wo905._classify_fetch(fr) == "timeout"

    def test_no_html_with_an_error_is_blocked(self):
        fr = wo905.ladder.FetchResult(html=None, error="boom")
        assert wo905._classify_fetch(fr) == "blocked"

    def test_no_html_and_no_error_is_dead(self):
        fr = wo905.ladder.FetchResult(html=None)
        assert wo905._classify_fetch(fr) == "dead"

    def test_challenge_page_is_challenge(self):
        fr = wo905.ladder.FetchResult(html="<html>Just a moment...</html>", status=200)
        assert wo905._classify_fetch(fr) == "challenge"

    def test_404_is_not_found(self):
        fr = wo905.ladder.FetchResult(html="<html>gone</html>", status=404)
        assert wo905._classify_fetch(fr) == "not_found"

    def test_500_is_blocked(self):
        fr = wo905.ladder.FetchResult(html="<html>oops</html>", status=500)
        assert wo905._classify_fetch(fr) == "blocked"

    def test_200_is_ok(self):
        fr = wo905.ladder.FetchResult(html="<html>fine</html>", status=200)
        assert wo905._classify_fetch(fr) == "ok"


# ---------------------------------------------------------------------
# _fetch_no_external_redirect -- mocked HTTP, no live network
# ---------------------------------------------------------------------


class TestFetchNoExternalRedirect:
    async def test_follows_a_same_host_redirect(self):
        # Real, confirmed live 2026-09-19 shape: an apex<->www redirect
        # (Hoffman Estates, IL / Harvey, IL) should be followed silently.
        routes = {
            "https://example.gov/a": FakeResponse(
                status=301, headers={"Location": "https://www.example.gov/a"}
            ),
            "https://www.example.gov/a": FakeResponse(
                status=200, text="<html>ok</html>"
            ),
        }
        with mock_session(routes):
            async with aiohttp.ClientSession() as session:
                fr, redirect = await wo905._fetch_no_external_redirect(
                    session, "https://example.gov/a", {"user-agent": "x"}
                )
        assert redirect == ""
        assert fr.status == 200
        assert fr.html == "<html>ok</html>"

    async def test_stops_at_a_cross_host_redirect_without_fetching_it(self):
        # This is the script's own NEVER-fetch-youtube.com-directly rule
        # in its most literal form: a same-domain shortcut link (the
        # exact shape confirmed live on Hagerstown MD/Greenwood Village
        # CO's own `/youtube`) must never turn into a real request to
        # youtube.com. Only ONE route is registered on purpose --
        # mock_session raises on any unmocked request, so this test fails
        # loudly if the code under test ever tries to fetch the Location.
        routes = {
            "https://example.gov/youtube": FakeResponse(
                status=302,
                headers={
                    "Location": "https://www.youtube.com/channel/UCFAKE0000000000"
                },
            ),
        }
        with mock_session(routes):
            async with aiohttp.ClientSession() as session:
                fr, redirect = await wo905._fetch_no_external_redirect(
                    session, "https://example.gov/youtube", {"user-agent": "x"}
                )
        assert redirect == "https://www.youtube.com/channel/UCFAKE0000000000"
        assert fr.html is None

    async def test_a_run_of_same_host_redirects_eventually_lands(self):
        routes = {
            "https://example.gov/a": FakeResponse(
                status=302, headers={"Location": "/b"}
            ),
            "https://example.gov/b": FakeResponse(status=200, text="<html>done</html>"),
        }
        with mock_session(routes):
            async with aiohttp.ClientSession() as session:
                fr, redirect = await wo905._fetch_no_external_redirect(
                    session, "https://example.gov/a", {"user-agent": "x"}
                )
        assert redirect == ""
        assert fr.html == "<html>done</html>"


# ---------------------------------------------------------------------
# sweep_one -- end-to-end wiring, mocked HTTP, no live network
# ---------------------------------------------------------------------


class TestSweepOneIntegration:
    async def test_icon_shortcut_redirect_path_end_to_end(self):
        """Models Hagerstown MD's real, live-confirmed conversion path
        (2026-09-19): the recorded /AgendaCenter hub is gone (404 here,
        matching what several of this WO's own real hub fetches actually
        returned live), the home page carries no direct platform link
        find_platform_link() would catch, but does carry an icon-only
        `/youtube` shortcut -- this script's own `_find_icon_shortcut_
        links()` supplement -- that redirects to a real YouTube channel.
        The government/domain/channel here are a synthetic stand-in
        (there is no real "example-hop-test.gov"); the SHAPE (a same-
        domain icon shortcut redirecting to a youtube.com channel) is the
        real, live-confirmed one this test exists to protect."""
        home_html = """<html><body>
        <nav>
        <a class="widgetGraphicLinksLink" href="/youtube"
           aria-label="YouTube opens in new window">
          <img alt="YouTube">
        </a>
        </nav>
        <p>Welcome to Example Hop Test.</p>
        </body></html>"""
        routes = {
            "https://example-hop-test.gov/AgendaCenter": FakeResponse(
                status=404, text="not found"
            ),
            "https://example-hop-test.gov": FakeResponse(status=200, text=home_html),
            "https://example-hop-test.gov/youtube": FakeResponse(
                status=302,
                headers={
                    "Location": "https://www.youtube.com/channel/UCFAKE0000000000"
                },
            ),
        }
        row = {
            "gov_id": "manual:example-hop-test",
            "name": "Example Hop Test",
            "state": "ZZ",
            "population": "",
            "domain": "example-hop-test.gov",
            "hub_url": "https://example-hop-test.gov/AgendaCenter",
        }
        with mock_session(routes):
            async with aiohttp.ClientSession() as session:
                result = await wo905.sweep_one(session, row)

        assert result.hub_fetch_status == "not_found"
        assert result.home_fetch_status == "ok"
        assert result.outcome == "platform_found"
        assert result.platform == "youtube"
        assert result.hit_url == "https://www.youtube.com/channel/UCFAKE0000000000"
        assert result.hit_source == "home_icon_shortcut_redirect"
        assert result.needs_listing_discovery is False

    async def test_hub_and_home_both_unreachable(self):
        routes = {
            "https://example-dead-gov.test/AgendaCenter": FakeResponse(
                status=500, text="server error"
            ),
            "https://example-dead-gov.test": FakeResponse(
                status=500, text="server error"
            ),
        }
        row = {
            "gov_id": "manual:example-dead-gov",
            "name": "Example Dead Gov",
            "state": "ZZ",
            "population": "",
            "domain": "example-dead-gov.test",
            "hub_url": "https://example-dead-gov.test/AgendaCenter",
        }
        with mock_session(routes):
            async with aiohttp.ClientSession() as session:
                result = await wo905.sweep_one(session, row)
        assert result.outcome == "hub_and_home_unreachable"
        assert result.platform == ""

    async def test_only_civicplus_found_is_reported_as_no_platform_link(self):
        """Real, confirmed live 2026-09-19 (Melrose MA is the real
        example -- see this module's own top-of-file comment on
        _TRIVIAL_PLATFORMS): a page that only ever leads back to another
        AgendaCenter/civicplus URL must not be reported as a hit -- this
        population's whole starting point already IS civicplus."""
        hub_html = (
            '<html><body><a href="/AgendaCenter/Search">Search AgendaCenter</a>'
            "</body></html>"
        )
        home_html = '<html><body><a href="/AgendaCenter">Agendas</a></body></html>'
        routes = {
            "https://example-agenda-only.gov/AgendaCenter": FakeResponse(
                status=200, text=hub_html
            ),
            "https://example-agenda-only.gov": FakeResponse(status=200, text=home_html),
        }
        row = {
            "gov_id": "manual:example-agenda-only",
            "name": "Example Agenda Only",
            "state": "ZZ",
            "population": "",
            "domain": "example-agenda-only.gov",
            "hub_url": "https://example-agenda-only.gov/AgendaCenter",
        }
        with mock_session(routes):
            async with aiohttp.ClientSession() as session:
                result = await wo905.sweep_one(session, row)
        assert result.outcome == "no_platform_link_found"
        assert result.platform == ""
        assert "civicplus" in result.note

    async def test_missing_hub_url_falls_back_to_a_guessed_agendacenter_path(self):
        home_html = "<html><body><p>hello</p></body></html>"
        routes = {
            "https://example-guess.gov/AgendaCenter": FakeResponse(
                status=404, text="not found"
            ),
            "https://example-guess.gov": FakeResponse(status=200, text=home_html),
        }
        row = {
            "gov_id": "manual:example-guess",
            "name": "Example Guess",
            "state": "ZZ",
            "population": "",
            "domain": "example-guess.gov",
            "hub_url": "",
        }
        with mock_session(routes):
            async with aiohttp.ClientSession() as session:
                result = await wo905.sweep_one(session, row)
        assert result.hub_url == "https://example-guess.gov/AgendaCenter"
        assert result.outcome == "no_platform_link_found"

    async def test_neither_hub_url_nor_domain_is_a_clean_early_outcome(self):
        row = {"gov_id": "manual:example-blank", "name": "", "state": "", "domain": ""}
        async with aiohttp.ClientSession() as session:
            result = await wo905.sweep_one(session, row)
        assert result.outcome == "no_hub_or_domain"
        assert result.error
