"""Tests for Detroit, MI and Charlotte, NC's Cablecast video portals
(app/platforms/cablecast.py).

Real fixtures fetched live 2026-08-12 (see BACKLOG.md/BACKLOG_DONE.md) --
a real show page, a Remix.js SSR app embedding the target show plus a
~35-item "related shows" carousel in one window.__remixContext JSON blob.
Charlotte's fixture is the same underlying template as Detroit's -- the
two are checked side by side throughout this file specifically because a
real bug (jurisdiction hardcoded to "Detroit, MI" for every customer) was
only found once a second real customer was checked.
"""

import json

from app.platforms.base import detect_platform
from app.platforms.cablecast import CablecastAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

PORTAL_URL = "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"
REAL_VOD_URL = (
    "https://reflect-detroit-vod.cablecast.tv/store-8/"
    "15323-Detroit-City-Council-Formal-Session-07-28-2026-v3/vod.m3u8"
)

CHARLOTTE_PORTAL_URL = "http://charlotte.cablecast.tv/internetchannel/show/2451?site=1"
CHARLOTTE_VOD_URL = (
    "https://charlotte.cablecast.tv/store-40/2451-City-Council-Meeting-v17/vod.m3u8"
)
CHARLOTTE_TRANSCRIPT_URL = "https://charlotte.cablecast.tv/store-40/2451-City-Council-Meeting-v17/transcript.en.txt"


def test_detect_platform_recognizes_cablecast_show_url():
    assert detect_platform(PORTAL_URL) == "cablecast"
    # Charlotte, NC's confirmed Cablecast site uses a different template
    # (no /internetchannel/show/ path) -- deliberately not matched here,
    # see cablecast.py's module docstring.
    assert (
        detect_platform("https://charlotte.cablecast.tv/internetchannel/?site=1")
        == "unknown"
    )


async def test_resolve_real_detroit_show():
    html = load_fixture("cablecast", "detroit_show_15323.html")
    # Real gap confirmed live: the portal's HTTPS hangs indefinitely for
    # the whole domain, so resolve() always fetches over plain HTTP --
    # the mocked route reflects that (only the http:// URL is registered).
    fetch_url = "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"

    routes = {fetch_url: FakeResponse(status=200, text=html, url=fetch_url)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(PORTAL_URL)

    assert result.platform == "cablecast"
    # Host-namespaced, not just the bare show_id -- see cablecast.py's own
    # external_id comment for the real duplicate-page bug (Coralville, IA)
    # this closes.
    assert result.external_id == "cablecast:detroit-vod.cablecast.tv:15323"
    assert result.title == "Detroit City Council Formal Session 07-28-2026"
    assert result.date == "2026-07-28"
    assert result.jurisdiction == "Detroit, MI"
    assert result.video_url == REAL_VOD_URL
    assert result.video_format == "m3u8"
    # This specific Detroit show's own vodTranscripts is empty (unlike the
    # real Charlotte example below, the first positive one found) -- still
    # a real, common outcome worth covering, not just the happy path.
    assert result.transcript_warnings == ["No transcript found for this event."]


async def test_resolve_real_charlotte_show():
    # Real bug fixed 2026-08-12: this used to resolve with
    # jurisdiction="Detroit, MI" (the old hardcoded constant) even though
    # everything else about this real Charlotte, NC meeting resolved
    # correctly. site.title here ("City of Charlotte GOV Channel") is
    # city-shaped, unlike Detroit's ("Channel 10") -- see the module-level
    # comment on _JURISDICTION_RE for why pageDescription is tried first
    # regardless.
    #
    # This real show also has a real, populated vodTranscripts entry
    # (unlike every Detroit show checked) -- the first positive example of
    # this field ever found, fetched and parsed here against the real
    # transcript file (tests/fixtures/cablecast/charlotte_transcript_2451.
    # en.txt, fetched live 2026-08-12: 512 real cues, ALL CAPS, spanning a
    # real ~3h16m meeting).
    html = load_fixture("cablecast", "charlotte_show_2451.html")
    transcript = load_fixture("cablecast", "charlotte_transcript_2451.en.txt")
    fetch_url = "http://charlotte.cablecast.tv/internetchannel/show/2451?site=1"

    routes = {
        fetch_url: FakeResponse(status=200, text=html, url=fetch_url),
        CHARLOTTE_TRANSCRIPT_URL: FakeResponse(
            status=200, text=transcript, url=CHARLOTTE_TRANSCRIPT_URL
        ),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(CHARLOTTE_PORTAL_URL)

    assert result.platform == "cablecast"
    assert result.external_id == "cablecast:charlotte.cablecast.tv:2451"
    assert result.title == "Council Meeting - June 22, 2026"
    assert result.date == "2026-06-22"
    # "City of Charlotte, NC" not bare "Charlotte, NC" as of 2026-08-29:
    # _extract_jurisdiction() now tries extract_jurisdiction_chain()
    # first (see that change's own comment -- fixes real multi-word-name
    # truncation on Virginia Beach/La Quinta), and its capitalization-
    # bounded walk correctly keeps the "City of" prefix from this real
    # fixture's own text ("...The City of Charlotte is committed to
    # making our services..." -- stops cleanly at the lowercase "is"),
    # same convention every other chain-based adapter already uses. Not
    # a correctness regression, just a formatting change for an
    # already-correct real customer.
    assert result.jurisdiction == "City of Charlotte, NC"
    assert result.video_url == CHARLOTTE_VOD_URL
    assert result.video_format == "m3u8"
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []
    assert len(result.segments) == 512
    assert result.segments[0].start == 20.83
    # ALL-CAPS re-cased by normalize_shouting_caption(), same as every
    # other platform's shouting captions -- note the real leading comma
    # artifact ("," before the first word) means the sentence-case regex
    # finds no letter right at position 0 to capitalize, so this one cue
    # starts lowercase; real, unrelated to this fix, not corrected here.
    assert result.segments[0].text.startswith(",wow. >> man good evening")
    # No explicit end time in the source -- each cue's end is the next
    # cue's own start.
    assert result.segments[0].end == result.segments[1].start == 38.8


async def test_resolve_external_id_is_stable_across_scheme_and_query_variants():
    # Real bug, confirmed live 2026-08-29 (Coralville, IA show 2907): the
    # same show reachable at http+"?site=1", https bare, and https+
    # "?site=1" produced 3 separate archived pages because nothing tied
    # them together except source_url string equality, which normalize_url
    # deliberately doesn't collapse across scheme/query differences. All
    # three variants must now resolve to the identical external_id so
    # _find_existing_page() (archive/db/crud.py) merges them into one page.
    html = load_fixture("cablecast", "detroit_show_15323.html")
    # resolve() always forces http (_force_http()) but leaves the query
    # string as pasted, so both the with- and without-"?site=1" forced
    # URLs need a registered route to exercise every real variant.
    with_query = "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"
    without_query = "http://detroit-vod.cablecast.tv/internetchannel/show/15323"
    routes = {
        with_query: FakeResponse(status=200, text=html, url=with_query),
        without_query: FakeResponse(status=200, text=html, url=without_query),
    }

    variants = [
        "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1",
        "https://detroit-vod.cablecast.tv/internetchannel/show/15323",
        "https://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1",
    ]
    external_ids = set()
    for variant in variants:
        with mock_session(routes):
            result = await CablecastAssetFinder().resolve(variant)
        external_ids.add(result.external_id)

    assert external_ids == {"cablecast:detroit-vod.cablecast.tv:15323"}


async def test_resolve_falls_back_gracefully_when_transcript_fetch_fails(caplog):
    # A populated vodTranscripts entry whose URL 404s (or times out) must
    # degrade to the same honest "no transcript" outcome as one with no
    # entry at all, not raise or crash the whole resolve.
    html = load_fixture("cablecast", "charlotte_show_2451.html")
    fetch_url = "http://charlotte.cablecast.tv/internetchannel/show/2451?site=1"

    routes = {
        fetch_url: FakeResponse(status=200, text=html, url=fetch_url),
        CHARLOTTE_TRANSCRIPT_URL: FakeResponse(status=404),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await CablecastAssetFinder().resolve(CHARLOTTE_PORTAL_URL)

    assert result.segments == []
    assert result.transcript_warnings == ["No transcript found for this event."]
    # 2026-08-28: a failed transcript fetch used to be silent -- now logged.
    assert any("transcript fetch got HTTP 404" in r.message for r in caplog.records)


async def test_resolve_forces_http_even_when_https_is_pasted():
    # The more natural thing for someone to paste/type -- resolve() must
    # never actually attempt the hanging HTTPS request.
    html = load_fixture("cablecast", "detroit_show_15323.html")
    fetch_url = "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"
    https_url = "https://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"

    routes = {fetch_url: FakeResponse(status=200, text=html, url=fetch_url)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(https_url)

    assert result.source_url == https_url  # what the user actually pasted is preserved
    assert result.video_url == REAL_VOD_URL


async def test_resolve_missing_show_id_reports_error():
    url = "http://detroit-vod.cablecast.tv/internetchannel/watch-now?site=1"

    result = await CablecastAssetFinder().resolve(url)

    assert result.video_warnings == ["Could not find a show id in this Cablecast URL."]


async def test_resolve_show_not_found_in_page_reports_no_video():
    # A real page shape (has __remixContext) but the requested showId
    # genuinely isn't in it -- distinct from the missing-show-id case
    # above.
    url = "http://detroit-vod.cablecast.tv/internetchannel/show/999999999?site=1"
    html = load_fixture("cablecast", "detroit_show_15323.html")

    # The requested show isn't in the direct-fetch page, so resolve() also
    # tries the site root as a fallback (see the newer-template/WAF note in
    # cablecast.py) -- also mocked here, with the same fixture, since it
    # genuinely doesn't contain showId 999999999 either.
    root_url = "http://detroit-vod.cablecast.tv/"
    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        root_url: FakeResponse(status=200, text=html, url=root_url),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]


async def test_resolve_no_vod_url_still_surfaces_the_shows_real_title_and_date():
    # Real bug found 2026-08-29 investigating a user report on Detroit:
    # a show that's found but genuinely has no video (Cablecast's own
    # `isWatchable: false`, confirmed live on real show 13797 -- a short
    # "Council Corner" segment, not a committee meeting) used to come
    # back with title=None/date=None too, even though the same JSON this
    # method already parses has both. Synthetic tree (see this repo's
    # convention for a narrower edge case on an already fixture-verified
    # adapter), but the title text and the no-`vodUrl` shape are real,
    # grounded in that live show.
    show_id = 13797
    tree = {
        "shows": [
            {
                "showId": show_id,
                "title": "Council Member YOUNG    Brush Park Manor Council Corner",
                "eventDate": "2026-08-29T06:04:03-04:00",
                "isWatchable": False,
            }
        ],
        "site": {"siteId": 1, "title": "Channel 10"},
    }
    html = (
        "<html><body><script>window.__remixContext = "
        + json.dumps(tree)
        + ";</script></body></html>"
    )
    fetch_url = f"http://detroit-vod.cablecast.tv/internetchannel/show/{show_id}?site=1"
    routes = {fetch_url: FakeResponse(status=200, text=html, url=fetch_url)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(fetch_url)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]
    assert result.title == "Council Member YOUNG    Brush Park Manor Council Corner"
    assert result.date == "2026-08-29"
    assert result.external_id == "cablecast:detroit-vod.cablecast.tv:13797"


async def test_resolve_newer_template_show_url_falls_back_to_root():
    # Real gap found 2026-08-18 re-checking a research pass's Cablecast
    # "miss" list against this adapter: a newer Cablecast portal template
    # (confirmed live on satellitebeach.cablecast.tv) drops the
    # "/internetchannel" prefix -- real show pages live at bare
    # "/show/{id}" -- and that specific path is behind an AWS WAF JS
    # challenge for non-browser requests (this fixture is the real
    # response: 202, a `challenge.js`/`awsWafCookieDomainList` page, no
    # usable content -- this adapter never tries to solve it). The site's
    # own root page is NOT WAF-protected and its `window.__remixContext`
    # already embeds the full show catalog (this fixture has 287 real
    # shows spanning 2019-2026), so resolve() falls back to it. Also
    # exercises the real `showId` type mismatch found alongside this:
    # it's a `str` ("535") on this template vs. an `int` on Detroit/
    # Charlotte's older one -- `_find_show()` compares both sides as
    # strings specifically so this doesn't silently fail to match.
    url = "https://satellitebeach.cablecast.tv/show/535"
    direct_url = "http://satellitebeach.cablecast.tv/show/535"
    root_url = "http://satellitebeach.cablecast.tv/"
    challenge_html = load_fixture("cablecast", "satellitebeach_waf_challenge.html")
    root_html = load_fixture("cablecast", "satellitebeach_root.html")

    routes = {
        direct_url: FakeResponse(status=202, text=challenge_html, url=direct_url),
        root_url: FakeResponse(status=200, text=root_html, url=root_url),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.title == "City Council Workshop 08-05-2026"
    assert result.date == "2026-08-05"
    assert result.video_url == (
        "https://satellitebeach.cablecast.tv/vod/"
        "535-City-Council-Workshop-08-05-2026-v2/vod.m3u8"
    )
    # This show's own vodTranscripts entry is real in the page data, but
    # the actual transcript file 403s on direct fetch (confirmed live
    # 2026-08-18, independent of this adapter fix) -- no positive example
    # of a fetchable transcript on this newer template exists yet, same
    # "don't claim a caption path works without a positive example"
    # convention as CivicClerk/eScribe.
    assert result.segments == []


def test_extract_show_id_recognizes_newer_template_bare_show_path():
    assert (
        CablecastAssetFinder._extract_show_id(
            "https://satellitebeach.cablecast.tv/show/535"
        )
        == 535
    )


def test_find_show_matches_string_showid_against_int_lookup():
    # Real type mismatch found 2026-08-18 (see
    # test_resolve_newer_template_show_url_falls_back_to_root): the
    # payload's showId is a str on the newer template.
    obj = {"showId": "535", "title": "String-keyed show"}
    assert CablecastAssetFinder._find_show(obj, 535) == obj
    assert CablecastAssetFinder._find_show({"showId": 535}, 535) == {"showId": 535}
    assert CablecastAssetFinder._find_show({"showId": "12"}, 535) is None


def test_extract_show_id():
    assert CablecastAssetFinder._extract_show_id(PORTAL_URL) == 15323
    assert (
        CablecastAssetFinder._extract_show_id(
            "http://detroit-vod.cablecast.tv/internetchannel/watch-now"
        )
        is None
    )


def test_force_http():
    assert (
        CablecastAssetFinder._force_http(
            "https://detroit-vod.cablecast.tv/internetchannel/show/1?site=1"
        )
        == "http://detroit-vod.cablecast.tv/internetchannel/show/1?site=1"
    )
    assert (
        CablecastAssetFinder._force_http(
            "http://detroit-vod.cablecast.tv/internetchannel/show/1?site=1"
        )
        == "http://detroit-vod.cablecast.tv/internetchannel/show/1?site=1"
    )


def test_find_show_recursively_searches_nested_structure():
    tree = {
        "a": {"b": [{"showId": 1, "title": "wrong"}, {"showId": 2, "title": "right"}]}
    }
    found = CablecastAssetFinder._find_show(tree, 2)
    assert found == {"showId": 2, "title": "right"}
    assert CablecastAssetFinder._find_show(tree, 999) is None


def test_find_site_ignores_per_show_siteid_decoys():
    # Real shape confirmed live: each show's own upcomingRuns entries
    # carry a small {siteId, title: None} decoy that also has "siteId" --
    # matched on pageDescription too so the real top-level site object
    # (the only one with real prose) is found instead of a decoy.
    tree = {
        "shows": [{"showId": 1, "site": {"siteId": 1, "title": None}}],
        "root": {
            "siteId": 1,
            "title": "Channel 10",
            "pageDescription": "The City of Detroit's Channel 10...",
        },
    }
    found = CablecastAssetFinder._find_site(tree)
    assert found == tree["root"]


_UNKNOWN_DOMAIN_URL = (
    "http://some-other-city.cablecast.tv/internetchannel/show/1?site=1"
)


def test_extract_jurisdiction_prefers_page_description_over_title():
    # Real bug fixed 2026-08-12: site.title alone is often just TV-channel
    # branding ("Channel 10"), not a jurisdiction -- pageDescription's
    # prose is what actually names the city on both real customers
    # checked.
    site = {
        "title": "Channel 10",
        "pageDescription": "The City of Detroit's Channel 10 features programming...",
    }
    assert CablecastAssetFinder._extract_jurisdiction(site, PORTAL_URL) == "Detroit, MI"


def test_extract_jurisdiction_falls_back_to_title():
    site = {
        "title": "City of Example GOV Channel",
        "pageDescription": "Watch local government meetings here.",
    }
    assert (
        CablecastAssetFinder._extract_jurisdiction(site, _UNKNOWN_DOMAIN_URL)
        == "Example"
    )


def test_extract_jurisdiction_returns_none_when_neither_field_matches():
    site = {
        "title": "Channel 10",
        "pageDescription": "Watch local government meetings here.",
    }
    assert CablecastAssetFinder._extract_jurisdiction(site, _UNKNOWN_DOMAIN_URL) is None


def test_extract_jurisdiction_falls_back_to_known_domain_when_branding_is_generic():
    # Real gap confirmed live 2026-08-19: Broomfield, CO's Cablecast site
    # has no "City of"/"County of" phrase anywhere -- title is just
    # "Channel 8" and pageDescription is empty. Falls back to the
    # confirmed-domain registry (same one Detroit/Charlotte use) instead
    # of dropping jurisdiction entirely.
    site = {"title": "Channel 8", "pageDescription": ""}
    broomfield_url = "http://broomfieldco.cablecast.tv/internetchannel/show/1674?site=1"
    assert (
        CablecastAssetFinder._extract_jurisdiction(site, broomfield_url)
        == "Broomfield, CO"
    )


def test_extract_jurisdiction_omits_state_for_an_unconfirmed_city():
    # A city with no confirmed domain AND no unambiguous real-world match
    # (a fake name here) gets no state suffix -- an honest gap, not a
    # guess. See test_extract_jurisdiction_resolves_state_via_gazetteer_
    # for_an_unconfirmed_but_unambiguous_real_city below for the case
    # where this *does* now resolve, via the shared Census-backed lookup.
    site = {"title": "City of Example Channel", "pageDescription": ""}
    assert (
        CablecastAssetFinder._extract_jurisdiction(site, _UNKNOWN_DOMAIN_URL)
        == "Example"
    )


def test_extract_jurisdiction_resolves_state_via_gazetteer_for_an_unconfirmed_but_unambiguous_real_city():
    # Real improvement from the shared jurisdiction_enrich module: a
    # Cablecast customer with no confirmed domain entry still gets a real
    # state, for free, as long as its city name is unambiguous nationally
    # -- "Chicago" is a real, unique (per app/utils/jurisdiction_data)
    # incorporated place name, unlike "Detroit"/"Charlotte" which need
    # the confirmed-domain registry specifically because they collide.
    site = {
        "title": "Channel 10",
        "pageDescription": "The City of Chicago's Channel 10 features programming...",
    }
    assert (
        CablecastAssetFinder._extract_jurisdiction(site, _UNKNOWN_DOMAIN_URL)
        == "Chicago, IL"
    )


def test_extract_jurisdiction_recovers_a_multi_word_name_the_narrow_regex_truncates():
    # Real bug, confirmed live 2026-08-29 auditing stored (not missing --
    # confidently WRONG) jurisdictions via /coverage: the narrow
    # _JURISDICTION_RE below only ever captures ONE word after "City of"/
    # "County of", so a real multi-word city name gets truncated at the
    # first word. Both are real customers: virginiabeach.cablecast.tv's
    # own site title is literally "City of Virginia Beach" (used to
    # store bare "Virginia"), laquinta.cablecast.tv's is "City of La
    # Quinta" (used to store bare "La").
    assert (
        CablecastAssetFinder._extract_jurisdiction(
            {"title": "City of Virginia Beach", "pageDescription": ""},
            "http://virginiabeach.cablecast.tv/show/2235?site=1",
        )
        == "City of Virginia Beach, VA"
    )
    assert (
        CablecastAssetFinder._extract_jurisdiction(
            {"title": "City of La Quinta", "pageDescription": ""},
            "https://laquinta.cablecast.tv/show/825?site=1",
        )
        == "City of La Quinta, CA"
    )


def test_extract_jurisdiction_falls_back_to_validated_subdomain():
    # Real gap found 2026-08-29 auditing archived pages missing a
    # jurisdiction: neither title/pageDescription branding nor the
    # curated known-domain table covers most real Cablecast customers --
    # confirmed live, 23 of 62 real distinct subdomains among 101 archived
    # gap pages validate cleanly via the same validated-subdomain-label
    # machinery eScribe/CivicPlus/TownHallStreams already share, which
    # this adapter never called at all. "Champaign" is nationally
    # unambiguous, so this also confirms a real state (IL).
    site = {"title": "Channel 8", "pageDescription": ""}
    url = "https://champaign.cablecast.tv/internetchannel/show/6000"
    assert CablecastAssetFinder._extract_jurisdiction(site, url) == "Champaign, IL"


def test_extract_jurisdiction_subdomain_fallback_omits_state_when_ambiguous():
    # "Fargo" alone is nationally ambiguous (real in ND and elsewhere per
    # the Census place table) -- same honest-gap philosophy as every
    # other tier here, not a guess just because the subdomain is a strong
    # real-world hint.
    site = {"title": "Channel 8", "pageDescription": ""}
    url = "https://fargo.cablecast.tv/internetchannel/show/13272"
    assert CablecastAssetFinder._extract_jurisdiction(site, url) == "Fargo"


def test_extract_jurisdiction_subdomain_fallback_declines_an_unvalidatable_subdomain():
    # _UNKNOWN_DOMAIN_URL's "some-other-city" label doesn't validate
    # against the Census tables either raw or wordninja-split -- must
    # stay None, not the previous behavior (also None, but confirms the
    # new tier doesn't regress this).
    site = {"title": "Channel 10", "pageDescription": "Watch local meetings here."}
    assert CablecastAssetFinder._extract_jurisdiction(site, _UNKNOWN_DOMAIN_URL) is None


def test_parse_transcript_reads_real_cue_shape():
    # Real shape confirmed live 2026-08-12 on a real Charlotte show: one
    # cue per line, "HH:MM:SS,mmm<TAB>TEXT", blank-line-separated, real
    # \r\n line endings -- not SRT (no sequence numbers, no "-->" range).
    content = "00:00:20,830\tFirst cue text.\r\n\r\n00:01:02,600\tSecond cue text.\r\n"
    cues = CablecastAssetFinder._parse_transcript(content)
    assert cues == [
        {"start": 20.83, "end": 62.6, "text": "First cue text."},
        {"start": 62.6, "end": 62.6, "text": "Second cue text."},
    ]


def test_parse_transcript_last_cue_end_equals_its_own_start():
    # No explicit end time exists anywhere in this format -- the last cue
    # has no "next cue" to borrow an end from, so it falls back to its own
    # start (same convention Granicus's AgendaViewer.php chapter markers
    # already use for the identical "only a start time given" shape).
    content = "00:00:00,000\tOnly cue.\r\n"
    cues = CablecastAssetFinder._parse_transcript(content)
    assert cues == [{"start": 0.0, "end": 0.0, "text": "Only cue."}]


def test_parse_transcript_skips_lines_that_do_not_match_the_shape():
    content = "not a cue line\r\n\r\n00:00:05,000\tReal cue.\r\n\r\ngarbage\r\n"
    cues = CablecastAssetFinder._parse_transcript(content)
    assert cues == [{"start": 5.0, "end": 5.0, "text": "Real cue."}]


def test_parse_transcript_returns_empty_list_for_no_matches():
    assert CablecastAssetFinder._parse_transcript("nothing here") == []


def test_format_date_handles_iso_with_offset_and_invalid():
    assert (
        CablecastAssetFinder._format_date("2026-07-28T00:00:00-04:00") == "2026-07-28"
    )
    assert CablecastAssetFinder._format_date(None) is None
    assert CablecastAssetFinder._format_date("not-a-date") is None


# --------------------------------------------------------------------
# CablecastPublicSite -- a third, genuinely different real portal
# template (Ember.js, not Remix), found via a 2026-08-29 wildcard-free
# DNS sweep. No HTML scraping here at all: real content sits behind a
# plain, open, unauthenticated JSON API (`cablecastapi/v1/shows/{id}`,
# `cablecastapi/v1/vods/{id}`) that this session confirmed live on two
# independent tenants -- fixtures below are the real, unmodified JSON
# responses fetched 2026-08-29. See cablecast.py's own module docstring
# above `_PUBLICSITE_SHOW_ID_RE` for the full investigation, including
# the confirmed HTTPS/HTTP asymmetry between the two tenants (Urbana
# answers over HTTPS; Smyrna's HTTPS times out outright, HTTP-only).
# --------------------------------------------------------------------

URBANA_SHOW_URL = "https://urbana.cablecast.tv/CablecastPublicSite/show/870?site=1"
SMYRNA_SHOW_URL = "https://smyrna.cablecast.tv/CablecastPublicSite/show/4070?site=1"


def test_detect_platform_recognizes_cablecast_publicsite_show_url():
    assert detect_platform(URBANA_SHOW_URL) == "cablecast"
    assert detect_platform(SMYRNA_SHOW_URL) == "cablecast"
    # A bare CablecastPublicSite channel-listing page (no /show/{id})
    # isn't a single meeting -- correctly unclaimed, same posture as the
    # Remix templates' own listing/root pages.
    assert (
        detect_platform("https://urbana.cablecast.tv/CablecastPublicSite/?site=1")
        == "unknown"
    )
    # WebSchedule -- confirmed live 2026-08-29 to be a legacy print-
    # schedule generator with no per-show links or video at all (see
    # BACKLOG.md) -- correctly never claimed by this or any adapter.
    assert (
        detect_platform(
            "https://peabody.cablecast.tv/Cablecast/Plugins/WebSchedule/default.aspx"
        )
        == "unknown"
    )


async def test_resolve_real_urbana_publicsite_show():
    show_json = load_fixture("cablecast", "urbana_publicsite_show_870.json")
    vod_json = load_fixture("cablecast", "urbana_publicsite_vod_1207.json")
    routes = {
        "https://urbana.cablecast.tv/cablecastapi/v1/shows/870": FakeResponse(
            status=200, text=show_json
        ),
        "https://urbana.cablecast.tv/cablecastapi/v1/vods/1207": FakeResponse(
            status=200, text=vod_json
        ),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(URBANA_SHOW_URL)

    assert result.platform == "cablecast"
    assert result.external_id == "cablecast:urbana.cablecast.tv:870"
    assert result.title == "City Council Regular meeting - 8/24/2026 6:30:00 PM"
    assert result.date == "2026-08-24"
    assert result.jurisdiction == "Urbana, IL"
    assert (
        result.video_url
        == "https://urbana.cablecast.tv/store-3/870-City-Council-Regular-v1/vod.mp4"
    )
    assert result.video_format == "mp4"
    assert result.video_warnings == []
    # No confirmed transcript source for this template yet -- see
    # cablecast.py's own module note.
    assert result.transcript_warnings == ["No transcript found for this event."]


async def test_resolve_real_smyrna_publicsite_show_falls_back_to_http():
    # The confirmed real HTTPS/HTTP asymmetry: Smyrna's HTTPS times out
    # outright, so this test mocks the HTTPS attempt as reachable-but-
    # unusable (a non-200) to exercise the fallback path, then the real
    # HTTP fixture data for the successful attempt.
    show_json = load_fixture("cablecast", "smyrna_publicsite_show_4070.json")
    vod_json = load_fixture("cablecast", "smyrna_publicsite_vod_2746.json")
    routes = {
        "https://smyrna.cablecast.tv/cablecastapi/v1/shows/4070": FakeResponse(
            status=503
        ),
        "http://smyrna.cablecast.tv/cablecastapi/v1/shows/4070": FakeResponse(
            status=200, text=show_json
        ),
        "https://smyrna.cablecast.tv/cablecastapi/v1/vods/2746": FakeResponse(
            status=503
        ),
        "http://smyrna.cablecast.tv/cablecastapi/v1/vods/2746": FakeResponse(
            status=200, text=vod_json
        ),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(SMYRNA_SHOW_URL)

    assert result.platform == "cablecast"
    assert result.title == "Beer Board Meeting - April 6, 2026"
    assert result.date == "2026-04-06"
    assert result.jurisdiction == "Smyrna, TN"
    assert result.video_url is not None
    assert result.video_format == "mp4"
    assert result.video_warnings == []


async def test_resolve_publicsite_show_not_found_on_either_scheme():
    routes = {
        "https://urbana.cablecast.tv/cablecastapi/v1/shows/999999999": FakeResponse(
            status=404
        ),
        "http://urbana.cablecast.tv/cablecastapi/v1/shows/999999999": FakeResponse(
            status=404
        ),
    }
    url = "https://urbana.cablecast.tv/CablecastPublicSite/show/999999999?site=1"

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.platform == "cablecast"
    assert result.video_url is None
    assert result.video_warnings == [
        "Could not find this show on the CablecastPublicSite API."
    ]
    # Jurisdiction still resolves from the known-domain registry even
    # when the specific show id doesn't exist -- same posture the Remix
    # path already has for a not-found show.
    assert result.jurisdiction == "Urbana, IL"


# --------------------------------------------------------------------
# CCX Media -- reflect-ccx.cablecast.tv is one Cablecast host shared by 9
# real, distinct Minnesota cities (Brooklyn Center, Brooklyn Park,
# Crystal, Golden Valley, Maple Grove, New Hope, Osseo, Plymouth,
# Robbinsdale), keyed apart only by a `site=` query param. Real bug fixed
# 2026-08-30: none of `_extract_jurisdiction()`'s existing tiers could
# tell the 9 apart -- every one resolved jurisdiction=None. Real, current
# CCX links use the "/CablecastPublicSite/show/{id}?site=X" URL shape
# (confirmed live -- Google indexes these directly), which this host
# 301s to its Remix template server-side but which itself routes through
# `_resolve_publicsite()`'s JSON-API branch, not the Remix/HTML branch --
# both branches needed the fix, so both are covered here. Fixtures below
# are the real, unmodified `cablecastapi/v1/shows|vods` JSON responses
# fetched live 2026-08-30 for two of the 9 cities.
# --------------------------------------------------------------------

CCX_MAPLEGROVE_SHOW_URL = (
    "https://reflect-ccx.cablecast.tv/CablecastPublicSite/show/36986?site=16"
)
CCX_BROOKLYNPARK_SHOW_URL = (
    "https://reflect-ccx.cablecast.tv/CablecastPublicSite/show/35842?site=8"
)


async def test_resolve_real_ccx_maple_grove_show_resolves_jurisdiction_via_site_param():
    show_json = load_fixture("cablecast", "ccx_maplegrove_publicsite_show_36986.json")
    vod_json = load_fixture("cablecast", "ccx_maplegrove_publicsite_vod_11039.json")
    routes = {
        "https://reflect-ccx.cablecast.tv/cablecastapi/v1/shows/36986": FakeResponse(
            status=200, text=show_json
        ),
        "https://reflect-ccx.cablecast.tv/cablecastapi/v1/vods/11039": FakeResponse(
            status=200, text=vod_json
        ),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(CCX_MAPLEGROVE_SHOW_URL)

    assert result.platform == "cablecast"
    assert result.title == "Maple Grove Report 3/4/2025"
    assert result.date == "2025-03-04"
    # The real fix: this used to be None -- pageDescription is generic
    # CCX Media+ app-download text (identical across all 9 cities) and
    # the bare site title ("Maple Grove") has no "City of" prefix for
    # the regex, so only the confirmed site=16 -> Maple Grove mapping
    # gets this right.
    assert result.jurisdiction == "Maple Grove, MN"
    assert result.video_url == (
        "https://reflect-ccx.cablecast.tv/store-17/"
        "36986-Maple-Grove-Report-3-4-25-v1/vod.mp4"
    )
    assert result.video_warnings == []


async def test_resolve_real_ccx_brooklyn_park_show_resolves_jurisdiction_via_site_param():
    show_json = load_fixture("cablecast", "ccx_brooklynpark_publicsite_show_35842.json")
    vod_json = load_fixture("cablecast", "ccx_brooklynpark_publicsite_vod_10386.json")
    routes = {
        "https://reflect-ccx.cablecast.tv/cablecastapi/v1/shows/35842": FakeResponse(
            status=200, text=show_json
        ),
        "https://reflect-ccx.cablecast.tv/cablecastapi/v1/vods/10386": FakeResponse(
            status=200, text=vod_json
        ),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(CCX_BROOKLYNPARK_SHOW_URL)

    assert result.platform == "cablecast"
    assert result.title == "Northwest Development-BP 11-11-24 to 12-2-24"
    # Different siteId (8), different real city -- confirms the mapping
    # isn't just hardcoded to one CCX city.
    assert result.jurisdiction == "Brooklyn Park, MN"
    assert result.video_url == (
        "https://reflect-ccx.cablecast.tv/store-17/"
        "35842-Northwest-Development-BP-11-11-24-to-12-2-24-v1/vod.mp4"
    )


def test_ccx_media_jurisdiction_covers_all_9_real_confirmed_cities():
    # Synthetic (no live fixture per city -- see this repo's convention
    # for a narrower edge case on an already fixture-verified adapter):
    # the shape here (host + a numeric `site=` query param) is real and
    # fixture-confirmed by the two live tests above; the remaining 7
    # (siteId, city) pairs are the real values read directly off CCX
    # Media's own real, live site catalog (confirmed 2026-08-30, embedded
    # identically on every real CCX show page checked -- see
    # cablecast.py's `_CCX_MEDIA_SITES` module comment), just not each
    # independently fixture-verified end to end through a full resolve().
    expected = {
        7: "Brooklyn Center, MN",
        8: "Brooklyn Park, MN",
        10: "Crystal, MN",
        15: "Golden Valley, MN",
        16: "Maple Grove, MN",
        17: "New Hope, MN",
        18: "Osseo, MN",
        19: "Plymouth, MN",
        20: "Robbinsdale, MN",
    }
    for site_id, jurisdiction in expected.items():
        url = f"https://reflect-ccx.cablecast.tv/internetchannel/show/1?site={site_id}"
        assert CablecastAssetFinder._ccx_media_jurisdiction(url) == jurisdiction


def test_ccx_media_jurisdiction_declines_an_unmapped_site_id():
    url = "https://reflect-ccx.cablecast.tv/internetchannel/show/1?site=999"
    assert CablecastAssetFinder._ccx_media_jurisdiction(url) is None


def test_ccx_media_jurisdiction_declines_a_different_cablecast_host():
    # Same site=8 value, but not the CCX Media host -- must not leak into
    # an unrelated Cablecast customer's own resolve.
    url = "https://charlotte.cablecast.tv/internetchannel/show/1?site=8"
    assert CablecastAssetFinder._ccx_media_jurisdiction(url) is None


# --------------------------------------------------------------------
# yourtown.cablecast.tv -- Cablecast's own vendor demo/sales tenant, not
# a real government. Real bug found 2026-08-30: its real catalog is
# deliberately built to look like ordinary local-government content
# (confirmed real show titles: "Pasadena City Council Meeting 3-31-23",
# "YourTown School Board Meeting with Agenda") and its own
# pageDescription plainly says so ("...send an email to
# sales@cablecast.tv"), but nothing in the page's structure otherwise
# distinguished it from a genuine tenant -- risking bulk-ingest as if it
# were a real Pasadena, CA meeting.
# --------------------------------------------------------------------


async def test_resolve_rejects_the_vendor_demo_tenant_outright():
    # No route registered at all -- mock_session raises AssertionError on
    # any unmocked request, so this also proves the guard fires before
    # any network fetch, not just that the final result looks rejected.
    url = "https://yourtown.cablecast.tv/internetchannel/show/32?site=1"

    with mock_session({}):
        result = await CablecastAssetFinder().resolve(url)

    assert result.platform == "cablecast"
    assert result.video_url is None
    assert result.title is None
    assert result.jurisdiction is None
    assert result.video_warnings == [
        "yourtown.cablecast.tv is Cablecast's own vendor demo/sales tenant, "
        "not a real government -- not resolved as a real meeting."
    ]


async def test_resolve_rejects_the_vendor_demo_tenant_via_publicsite_url_shape_too():
    # The guard is a hostname check at the very top of resolve(), before
    # either URL-shape branch -- confirm the CablecastPublicSite-shaped
    # URL is caught the same way as the plain internetchannel one above.
    url = "https://yourtown.cablecast.tv/CablecastPublicSite/show/32?site=1"

    with mock_session({}):
        result = await CablecastAssetFinder().resolve(url)

    assert result.video_warnings == [
        "yourtown.cablecast.tv is Cablecast's own vendor demo/sales tenant, "
        "not a real government -- not resolved as a real meeting."
    ]


async def test_resolve_publicsite_show_with_no_vods_reports_no_video():
    show_json = json.dumps(
        {
            "show": {
                "id": 999,
                "title": "A meeting with no recording yet",
                "eventDate": "2026-09-01T18:30:00-05:00",
                "vods": [],
            }
        }
    )
    routes = {
        "https://urbana.cablecast.tv/cablecastapi/v1/shows/999": FakeResponse(
            status=200, text=show_json
        ),
    }
    url = "https://urbana.cablecast.tv/CablecastPublicSite/show/999?site=1"

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.platform == "cablecast"
    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]
    assert result.jurisdiction == "Urbana, IL"
