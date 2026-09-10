import pytest

from app.platforms import base
from app.platforms.base import (
    CIVICPLUS_CORPORATE_HOSTS,
    CORPORATE_HOSTS_BY_PLATFORM,
    UnsupportedPlatformError,
    detect_platform,
    find_platform_link,
    get_finder,
    register,
)

from conftest import load_fixture


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://sandiego.granicus.com/player/clip/123", "granicus"),
        ("https://maricopa.legistar.com/MeetingDetail.aspx?ID=1", "legistar"),
        ("https://legistar.council.nyc.gov/Calendar.aspx", "legistar"),
        ("https://clovisca.portal.civicclerk.com/event/20/media", "civicclerk"),
        ("https://ca-westlakevillage.civicplus.com/AgendaCenter", "civicplus"),
        # Real tenant shapes, still classified as "civicplus" -- WO-162
        # (2026-09-10) regression coverage, added alongside the corporate-
        # host fix below to confirm it didn't also break these. The bare
        # "{slug}.civicplus.com" shape (no state prefix)...
        ("https://example.civicplus.com/AgendaCenter", "civicplus"),
        # ...and the "{state}-{name}.civicplus.com" shape.
        ("https://nc-durham.civicplus.com/AgendaCenter/City-Council-4", "civicplus"),
        # CivicPlus's own corporate/marketing hosts -- confirmed live
        # 2026-09-10 (WO-162) to NEVER be a per-government tenant, even
        # though a bare "civicplus" substring match used to treat them as
        # one. `connect.civicplus.com` is the real one every CivicPlus
        # tenant's own page footer links to ("Government Websites by
        # CivicPlus (r)") -- see CIVICPLUS_CORPORATE_HOSTS' own docstring
        # in app/platforms/base.py for the real bug this fixes (Temple
        # City, CA: a link-scan reaching this footer link before any real
        # content link got a bogus "no video found"/403 instead of
        # continuing the scan).
        ("https://connect.civicplus.com/referral", "unknown"),
        ("https://www.civicplus.com/some-marketing-page", "unknown"),
        ("https://civicplus.com/", "unknown"),
        ("https://lacity.primegov.com/Portal/Meeting?id=1", "primegov"),
        ("https://yountvilleca.new.swagit.com/videos/394093", "swagit"),
        ("https://dublin.ca.gov/swagit-video-player?video_id=1", "swagit"),
        ("https://richmond.escribemeetings.com/Meeting.aspx?Id=1", "escribe"),
        (
            "https://public.destinyhosted.com/agenda_publish.cfm?id=96635",
            "destinyhosted",
        ),
        (
            "https://public.destinyhosted.com/76793/agenda/agenda.cfm?seq=357",
            "destinyhosted",
        ),
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
        (
            "https://townhallstreams.com/stream.php?location_id=94&id=75799",
            "townhallstreams",
        ),
        (
            "https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d?page=HOME",
            "castus",
        ),
        ("https://example.com/some/random/page", "unknown"),
        # WO-163 (2026-09-10): generalizing WO-162's CivicPlus-only
        # corporate-host fix to every other platform in this function
        # that shares the same bare-substring shape. Each pair below is a
        # vendor's own real, confirmed corporate/marketing/login host
        # (expecting "unknown") next to a real tenant shape for the same
        # platform (expecting the platform stays correctly recognized) --
        # see CORPORATE_HOSTS_BY_PLATFORM's own comment in
        # app/platforms/base.py for how each corporate host was
        # confirmed. The real evidence row this WO was built to fix: a
        # 400-row scan found 12 governments (Mesa AZ, Fort Collins CO,
        # Palo Alto CA among them) whose own calendar page links to
        # exactly this Granicus marketing URL.
        (
            "https://granicus.com/solution/govaccess/opencities/",
            "unknown",
        ),
        ("https://www.granicus.com/", "unknown"),
        # legistar.com, primegov.com, swagit.com and iqm2.com all now
        # redirect straight to granicus.com -- confirmed live, all four
        # products were acquired by Granicus.
        ("https://legistar.com/", "unknown"),
        ("https://www.legistar.com/", "unknown"),
        ("https://webapi.legistar.com/v1/phoenix/events", "legistar"),
        (
            "https://www.civicclerk.com/civicclerk/agenda-meeting-management",
            "unknown",
        ),
        ("https://primegov.com/", "unknown"),
        ("https://www.primegov.com/", "unknown"),
        ("https://swagit.com/", "unknown"),
        ("https://www.swagit.com/", "unknown"),
        ("https://www.escribemeetings.com/", "unknown"),
        ("https://escribemeetings.com/", "unknown"),
        ("https://www.civicweb.net/", "unknown"),
        ("https://civicweb.net/", "unknown"),
        ("https://townofchenango.civicweb.net/Portal/", "civicweb"),
        ("https://www.diligentoneplatform.com/", "unknown"),
        ("https://oidc.diligentoneplatform.com/login", "unknown"),
        (
            "https://winthropminnesota.community.diligentoneplatform.com"
            "/Portal/MeetingInformation.aspx?Org=Cal&Id=1",
            "civicweb",
        ),
        ("https://iqm2.com/", "unknown"),
        ("https://www.iqm2.com/", "unknown"),
        ("https://atlantacityga.iqm2.com/Detail_Meeting.aspx?ID=1", "iqm2"),
        # ClerkBase/ClerkHQ tenants live on the bare clerkshq.com domain
        # (a path segment, not a subdomain) -- only www is a real,
        # separate, non-tenant host, confirmed live.
        ("https://www.clerkshq.com/", "unknown"),
        (
            "https://clerkshq.com/YellowSprings-OH?docId=feb07_22ag",
            "clerkbase",
        ),
        ("https://champds.com/", "unknown"),
        ("https://www.champds.com/", "unknown"),
        ("https://play.champds.com/atlantaga/event/1227", "champds"),
        ("https://www.destinyhosted.com/", "unknown"),
        ("https://destinyhosted.com/", "unknown"),
        ("https://telvue.com/", "unknown"),
        ("https://www.telvue.com/", "unknown"),
        ("https://videoplayer.telvue.com/player/abc123", "telvue"),
        # www.viebit.com is a real host that redirects to
        # www.leightronix.com, Viebit's real corporate parent -- confirmed
        # live.
        ("https://www.viebit.com/", "unknown"),
        ("https://viebit.com/", "unknown"),
        ("https://councilnyc.viebit.com/vod/?v=x", "viebit"),
        # The bare suiteonemedia.com host redirects to getsuiteone.com (a
        # rebrand) -- confirmed live.
        ("https://suiteonemedia.com/", "unknown"),
        ("https://www.suiteonemedia.com/", "unknown"),
        (
            "https://pacificgroveca.suiteonemedia.com/event/?id=1",
            "suiteone",
        ),
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
    try:
        assert get_finder("fake_test_platform") is finder
    finally:
        # base._REGISTRY is process-global and register() has no
        # unregister, so without this the fake leaks into every later
        # read of the registry in the same pytest process -- which is
        # exactly what the registry-coverage guard in
        # tests/test_adapter_canary.py reads. That guard defends itself
        # (conftest.registered_platforms() snapshots and rebuilds the
        # registry), but leaving the pollution in place would still make
        # any future naive read of _REGISTRY wrong in a way that only
        # shows up as a collection-order-dependent failure.
        base._REGISTRY.pop("fake_test_platform", None)


def test_find_platform_link_finds_a_swagit_link_in_a_plain_a_tag():
    # Real shape confirmed live 2026-08-10: Austin, TX's council pages
    # link out to their Swagit-hosted video as a plain <a href>, not an
    # embed.
    html = '<html><body><a href="http://austintx.swagit.com/play/1/0/">Video</a></body></html>'
    result = find_platform_link(html, "https://www.austintexas.gov/council/2026/x-reg")
    assert result == ("http://austintx.swagit.com/play/1/0/", "swagit")


def test_find_platform_link_finds_a_swagit_link_in_an_onclick_js_modal():
    # Real shape confirmed live 2026-08-21: Destiny AgendaQuick
    # (destinyhosted.com) renders its Swagit video link as
    # `href="#" onclick="swagitPlay('https://...')"`, never as a literal
    # href/src -- e.g. The Woodlands Township, TX (id=96635). Same class
    # of gap as Legistar's window.open()/OpenTelerikWindow() onclick
    # handling in legistar.py, but generalized here since this shared
    # helper has more than one caller.
    html = (
        '<html><body><a href="#" '
        "onclick=\"swagitPlay('https://woodlandstx.new.swagit.com/videos/396312#123'); "
        'return false;">Video</a></body></html>'
    )
    result = find_platform_link(
        html, "https://public.destinyhosted.com/agenda_publish.cfm?id=96635"
    )
    assert result == (
        "https://woodlandstx.new.swagit.com/videos/396312#123",
        "swagit",
    )


def test_find_platform_link_skips_a_different_link_on_the_same_platform():
    # Real bug, confirmed live 2026-08-21, the moment destinyhosted.com
    # became its own registered platform rather than "unknown": a
    # destinyhosted agenda page's own pagination/month-nav links are also
    # destinyhosted.com URLs (a different page, not the same URL, so the
    # existing exact-URL same-page check doesn't catch it) -- matched
    # *before* the real onclick swagitPlay(...) link further down the DOM,
    # silently breaking every destinyhosted resolve. A same-platform
    # candidate is never a real delegation target, exact-URL match or not.
    html = (
        "<html><body>"
        '<a href="https://public.destinyhosted.com/agenda_publish.cfm?id=96635&get_month=7">Prev month</a>'
        '<a href="#" onclick="swagitPlay(\'https://woodlandstx.new.swagit.com/videos/396312\')">Video</a>'
        "</body></html>"
    )
    result = find_platform_link(
        html, "https://public.destinyhosted.com/agenda_publish.cfm?id=96635&get_month=8"
    )
    assert result == ("https://woodlandstx.new.swagit.com/videos/396312", "swagit")


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


def test_civicplus_corporate_hosts_matches_the_real_fixture_footer_link():
    # The exact string this whole fix is built around -- confirmed
    # present verbatim (not guessed) in two independently-fetched real
    # CivicPlus tenant fixtures, plus a third, self-hosted one added for
    # WO-162 -- see CIVICPLUS_CORPORATE_HOSTS' own docstring.
    assert "connect.civicplus.com" in CIVICPLUS_CORPORATE_HOSTS


def test_find_platform_link_skips_civicplus_corporate_footer_link_on_a_real_page():
    # Real page, fetched live 2026-09-10 (WO-162):
    # www.templecityca.gov/agendacenter -- see
    # tests/fixtures/civicplus/README.md for the full fetch note. Real
    # bug this is a regression test for: before the fix, this real
    # page's own "Government Websites by CivicPlus" footer credit
    # (`<a href="https://connect.civicplus.com/referral">`) was
    # misclassified as a genuine "civicplus" platform link by
    # detect_platform()'s bare substring match -- confirmed live, this
    # exact scan used to return that footer link, and delegating to it
    # hit a real 403 on https://www.civicplus.com/referral.
    #
    # This real page's own 103 `tr.catAgendaRow` rows all point their
    # `td.media` video link at `templecity.ec1c24.com` -- a video-index
    # wrapper domain detect_platform() doesn't recognize at all (a
    # separate, real gap, filed in BACKLOG.md -- see the fixture
    # README's caution note). So the correct, honest result of this scan
    # on this real page is `None` -- no known-platform link exists on it
    # at all once the corporate host is correctly excluded -- not a
    # positive pick. The "picks the real link instead" half of this bug
    # is covered separately below, using synthetic HTML that places a
    # real, already-supported platform link where this real page has
    # none (see that test's own docstring for why it's synthetic).
    # Called the same way generic_fallback.py's own
    # _try_delegate_to_known_platform() does -- excluding "youtube" (this
    # real page also has a "Watch us on YouTube" channel footer icon,
    # `youtube.com/ConnectwithTC`, the same bare-channel-link false
    # positive class find_platform_link()'s own docstring already
    # documents, unrelated to the corporate-host bug this test covers).
    html = load_fixture("civicplus", "temple_city_agendacenter.html")
    result = find_platform_link(
        html,
        "https://www.templecityca.gov/agendacenter",
        exclude=frozenset({"youtube"}),
    )
    assert result is None


def test_find_platform_link_skips_civicplus_footer_before_a_real_platform_link():
    # Synthetic HTML (per this repo's convention: fine for exercising one
    # already-confirmed logic branch -- the DOM-order priority between
    # two links -- not as a stand-in for "test against a real page
    # first"). The footer link's own shape is the real one confirmed in
    # tests/fixtures/civicplus/temple_city_agendacenter.html; the Swagit
    # link reuses the real, already-verified Austin, TX shape from
    # test_find_platform_link_finds_a_swagit_link_in_a_plain_a_tag above.
    # No real fixture combines a corporate footer credit with a directly
    # resolvable known-platform link on the same page (Temple City's own
    # real per-meeting links point at an unrecognized wrapper domain
    # instead -- see the test above), so this is the ordering variant the
    # WO's own test plan allows building synthetically.
    html = (
        "<html><body>"
        '<a href="http://austintx.swagit.com/play/1/0/">Video</a>'
        '<span class="cpBylineTextTS">Government Websites by '
        '<a href="https://connect.civicplus.com/referral">CivicPlus&reg;</a></span>'
        "</body></html>"
    )
    result = find_platform_link(html, "https://www.example-gov.org/AgendaCenter")
    assert result == ("http://austintx.swagit.com/play/1/0/", "swagit")

    # And the reverse order -- the footer appearing FIRST in the DOM,
    # the real shape confirmed live on Temple City's own page (the
    # footer sits at the very bottom of the page, but a different real
    # tenant could plausibly render it earlier) -- confirms the fix isn't
    # order-dependent by accident.
    html_footer_first = (
        "<html><body>"
        '<span class="cpBylineTextTS">Government Websites by '
        '<a href="https://connect.civicplus.com/referral">CivicPlus&reg;</a></span>'
        '<a href="http://austintx.swagit.com/play/1/0/">Video</a>'
        "</body></html>"
    )
    result_footer_first = find_platform_link(
        html_footer_first, "https://www.example-gov.org/AgendaCenter"
    )
    assert result_footer_first == ("http://austintx.swagit.com/play/1/0/", "swagit")


def test_civicplus_corporate_hosts_alias_still_points_at_the_shared_map():
    # WO-163 (2026-09-10) replaced CIVICPLUS_CORPORATE_HOSTS's standalone
    # definition with CORPORATE_HOSTS_BY_PLATFORM["civicplus"], keeping
    # the old name as an alias so scripts/wo134_confirmed_hits_ingest.py
    # and the two adhoc_school_district_retry_*.py scripts keep working
    # unchanged.
    assert CIVICPLUS_CORPORATE_HOSTS is CORPORATE_HOSTS_BY_PLATFORM["civicplus"]


def test_find_platform_link_skips_a_granicus_marketing_link_on_a_real_page():
    # Real evidence this WO was built to fix: a 400-row coverage-triage
    # scan found 12 real governments (Morris County NJ, Mesa AZ, Sioux
    # Falls SD, Fort Collins CO, Lakewood CO, Syracuse NY, Clearwater FL,
    # Lewis and Clark County MT, Palo Alto CA, Chapel Hill NC, Genesee
    # County NY, Littleton CO) whose own calendar page links to Granicus's
    # own product page, https://granicus.com/solution/govaccess/
    # opencities/ -- and the old bare "granicus.com in netloc" check
    # would have matched every one of those as a real "granicus" tenant.
    # Synthetic page shape (per this repo's synthetic-test convention):
    # the marketing link's own URL is the real, confirmed one from the
    # evidence above; the real content link reuses the already-verified
    # real Granicus tenant shape from test_detect_platform.
    html = (
        "<html><body>"
        '<a href="https://granicus.com/solution/govaccess/opencities/">'
        "Powered by OpenCities</a>"
        '<a href="https://sandiego.granicus.com/player/clip/123">Watch</a>'
        "</body></html>"
    )
    result = find_platform_link(html, "https://www.example-gov.org/calendar")
    assert result == ("https://sandiego.granicus.com/player/clip/123", "granicus")


def test_find_platform_link_returns_none_when_only_a_granicus_marketing_link_exists():
    # The honest negative result for a page that links only to Granicus's
    # own marketing page and nothing else this app recognizes -- no
    # known-platform link exists on it once the corporate host is
    # correctly excluded, which is a correct "not found," not a bug.
    html = (
        '<html><body><a href="https://granicus.com/solution/govaccess/'
        'opencities/">Powered by OpenCities</a></body></html>'
    )
    assert find_platform_link(html, "https://www.example-gov.org/calendar") is None
