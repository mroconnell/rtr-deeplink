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
from app.platforms.cablecast import CablecastAssetFinder, list_gallery_shows

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


def test_parse_transcript_reads_the_speaker_label_on_its_own_line_shape():
    # Real second cue shape, confirmed live 2026-09-12 (WO-309 resume) on
    # three unrelated tenants: Wilder KY (reflect-campbellcounty), Cape
    # Elizabeth ME (reflect-cetv), and this excerpt, from Huron charter
    # Township, MI's real Zoning Board of Appeals transcript (show 480,
    # huron-township.cablecast.tv) -- a bare speaker label on the
    # timestamp line, the real text on the following line. Before the
    # fix, `_parse_transcript()` returned "S4:" as the cue text and
    # silently dropped the real sentence.
    content = (
        "00:05:44,319\tS4:\n"
        "Order this meeting of the Zoning Board of Appeals of Huron "
        "Township at 630. Pledge of allegiance to the flag. Please "
        "stand for the pledge.\n"
        "\n"
        "00:06:17,529\tS4:\n"
        "Roll call. Vote, please.\n"
    )
    cues = CablecastAssetFinder._parse_transcript(content)
    assert cues == [
        {
            "start": 344.319,
            "end": 377.529,
            "text": (
                "Order this meeting of the Zoning Board of Appeals of Huron "
                "Township at 630. Pledge of allegiance to the flag. Please "
                "stand for the pledge."
            ),
        },
        {"start": 377.529, "end": 377.529, "text": "Roll call. Vote, please."},
    ]


def test_parse_transcript_still_handles_the_single_line_shape_mixed_in():
    # The two real cue shapes can appear in the same file (unconfirmed
    # whether any single real tenant actually mixes them -- this pins
    # the parser's own per-cue dispatch, not a claim about real data).
    content = (
        "00:00:20,830\tFirst cue text.\r\n"
        "\r\n"
        "00:00:25,000\tS2:\n"
        "Second cue, on its own line.\n"
    )
    cues = CablecastAssetFinder._parse_transcript(content)
    assert cues == [
        {"start": 20.83, "end": 25.0, "text": "First cue text."},
        {"start": 25.0, "end": 25.0, "text": "Second cue, on its own line."},
    ]


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


# WO-306 (2026-09-12): a real CablecastPublicSite customer hosted on its
# OWN government domain, not a *.cablecast.tv subdomain -- confirmed live,
# Maplewood, MN (`vod.maplewoodmn.gov`). Its `/cablecastapi/v1/shows/{id}`
# API answers in the exact same shape as the vendor-subdomain tenants
# above. Before this fix, detect_platform()'s CablecastPublicSite branch
# required "cablecast.tv" in netloc, so this real URL fell through to
# generic_fallback -- reached only by fixing this branch to key off the
# distinctive "/cablecastpublicsite/show/" path alone, not the host.
MAPLEWOOD_SHOW_URL = "https://vod.maplewoodmn.gov/CablecastPublicSite/show/1719?site=1"


def test_detect_platform_recognizes_cablecast_publicsite_on_government_domain():
    assert detect_platform(MAPLEWOOD_SHOW_URL) == "cablecast"
    # The bare "/show/{id}" template stays scoped to real cablecast.tv
    # netlocs -- too weak a signal to trust against an arbitrary
    # government domain that just happens to have a "/show/123" path for
    # something unrelated.
    assert detect_platform("https://vod.maplewoodmn.gov/show/1719") == "unknown"
    # WO-309 (2026-09-12): the Remix "/internetchannel/show/{id}" template
    # no longer requires "cablecast.tv" in netloc either, for the same
    # reason as the CablecastPublicSite branch above -- confirmed live on
    # Edison, NJ's own custom-domain tenant
    # (`cablecast.edisonnj.org/internetchannel/show/{id}?site=1`), a real
    # Remix-template Cablecast page with real captions, not on a
    # cablecast.tv subdomain at all.
    assert (
        detect_platform("https://vod.maplewoodmn.gov/internetchannel/show/1719")
        == "cablecast"
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


# --------------------------------------------------------------------
# WO-344: the third real Cablecast template -- the same "cablecast-
# public-site" Ember/FastBoot app as the CablecastPublicSite tests above,
# mounted at a custom domain's own ROOT instead of under
# "/CablecastPublicSite/", so neither of the two branches above reaches
# it (the Remix path finds no `window.__remixContext`; the PublicSite
# JSON API 404s on this tenant's own subdomain). Confirmed live
# 2026-09-13 on Dyersville, IA (`city-dyersville-ia.cablecast.tv/show/
# 3660?site=1`, real "City Council Meeting 2026-09-08" content, filed as
# an adapter gap in WO-309 (resume), BACKLOG.md). Fixtures are real,
# unmodified content fetched live the same day -- the two caption
# segment/playlist fixtures are trimmed from the real show's own 221
# segments down to the first 2 (the m3u8 playlist edited to list only
# those two URIs, each segment file itself byte-for-byte the real
# response), kept small for a fast test while still exercising real
# content and the real absolute-timestamp/concatenation behavior.
# --------------------------------------------------------------------

DYERSVILLE_SHOW_URL = "https://city-dyersville-ia.cablecast.tv/show/3660?site=1"


async def test_resolve_real_dyersville_fastboot_show():
    routes = {
        "http://city-dyersville-ia.cablecast.tv/show/3660?site=1": FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_show_3660_raw.html"),
        ),
        "http://city-dyersville-ia.cablecast.tv/": FakeResponse(
            status=200, text=load_fixture("cablecast", "dyersville_root.html")
        ),
        "http://city-dyersville-ia.cablecast.tv/embed/vod?show=3660&site=1": (
            FakeResponse(
                status=200,
                text=load_fixture("cablecast", "dyersville_embed_vod_3660.html"),
            )
        ),
        (
            "https://city-dyersville-ia.cablecast.tv/vod/"
            "3660-City-Council-Meeting-2026-09-08-v2/vod.m3u8"
        ): FakeResponse(
            status=200, text=load_fixture("cablecast", "dyersville_vod_3660.m3u8")
        ),
        (
            "https://city-dyersville-ia.cablecast.tv/vod/"
            "3660-City-Council-Meeting-2026-09-08-v2/captions.en.m3u8"
        ): FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_captions_en_3660.m3u8"),
        ),
        (
            "https://city-dyersville-ia.cablecast.tv/vod/"
            "3660-City-Council-Meeting-2026-09-08-v2/subtitles/28986/"
            "captions.en.00000.vtt?duration=10"
        ): FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_captions_en_00000.vtt"),
        ),
        (
            "https://city-dyersville-ia.cablecast.tv/vod/"
            "3660-City-Council-Meeting-2026-09-08-v2/subtitles/28986/"
            "captions.en.00001.vtt?duration=10"
        ): FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_captions_en_00001.vtt"),
        ),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(DYERSVILLE_SHOW_URL)

    assert result.platform == "cablecast"
    assert result.title == "City Council Meeting 2026-09-08"
    # The embed page carries no separate eventDate field -- extracted from
    # the real title text instead (see cablecast.py's module docstring).
    assert result.date == "2026-09-08"
    # No Remix `site` object exists on this template -- confirmed real
    # `validated_subdomain_extract()` + `resolve_state()` fallback.
    assert result.jurisdiction == "Dyersville, IA"
    assert result.video_url == (
        "https://city-dyersville-ia.cablecast.tv/vod/"
        "3660-City-Council-Meeting-2026-09-08-v2/vod.m3u8"
    )
    assert result.video_format == "m3u8"
    assert result.external_id == "cablecast:city-dyersville-ia.cablecast.tv:3660"
    # 5 real cues from segment 0 + 3 from segment 1, already-absolute
    # timestamps concatenated with no offset and no duplicates -- see
    # cablecast.py's module docstring point 2.
    assert len(result.segments) == 8
    assert result.segments[0].start == 1.43
    assert result.segments[0].text == "And I wish I wouldn't\neven said that."
    assert result.segments[-1].start == 12.91
    assert result.segments[-1].text == "Right."
    assert result.transcript_warnings == []


async def test_resolve_fastboot_embed_returns_none_without_a_source_tag():
    # Synthetic (no real video-less FastBoot show confirmed yet -- see
    # this repo's "don't claim a data path works without a positive
    # example" convention): reuses the real embed page's own confirmed
    # `window.TRMS` shape, minus the `<source>` tag a genuinely video-less
    # show would presumably lack. Confirms `_resolve_fastboot_embed()`
    # returns `None` (not a fabricated "no video" ResolvedMeeting) so the
    # caller's own standard no-video message applies instead.
    embed_html_no_source = (
        "<html><head><script>window.TRMS = {siteId: 'x', "
        "showTitle: 'Special Meeting 2026-01-05', showId: 42};"
        "</script></head><body></body></html>"
    )
    routes = {
        "http://city-dyersville-ia.cablecast.tv/show/42?site=1": FakeResponse(
            status=200,
            text=load_fixture("cablecast", "dyersville_show_3660_raw.html"),
        ),
        "http://city-dyersville-ia.cablecast.tv/": FakeResponse(
            status=200, text=load_fixture("cablecast", "dyersville_root.html")
        ),
        "http://city-dyersville-ia.cablecast.tv/embed/vod?show=42&site=1": (
            FakeResponse(status=200, text=embed_html_no_source)
        ),
    }
    url = "https://city-dyersville-ia.cablecast.tv/show/42?site=1"

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.platform == "cablecast"
    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]


async def test_resolve_fastboot_fallback_is_not_tried_for_a_show_the_remix_path_found():
    # Huron charter Township, MI's real tenant uses this exact bare
    # "/show/{id}" URL shape but IS the Remix template (see BACKLOG.md's
    # WO-309 (resume) entry) -- the FastBoot fallback must never run once
    # the Remix path already found a real show, or it would waste a real
    # network round-trip on every ordinary newer-template resolve. Reuses
    # satellitebeach's real root-catalog fixture (which embeds a real
    # show 535) as the direct show-page response, purely to get a
    # real `window.__remixContext` payload the Remix path can match on
    # the FIRST fetch -- not a claim that satellitebeach's own site
    # serves this content at this exact path.
    show_html = load_fixture("cablecast", "satellitebeach_root.html")
    routes = {
        "http://satellitebeach.cablecast.tv/show/535": FakeResponse(
            status=200, text=show_html
        ),
    }
    url = "https://satellitebeach.cablecast.tv/show/535"

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    # Only the one route above is mocked -- if the fallback were
    # incorrectly tried, `mock_session` would raise on the unmocked
    # "/embed/vod" request instead of returning a normal result.
    assert result.video_url is not None


# --- Gallery listing pages (2026-09-23) --------------------------------
#
# Real fixtures fetched live 2026-09-23: `oldsaybrook_gallery_22.html` is
# reflect-vsctv.cablecast.tv's real `/internetchannel/gallery/22` page --
# one shared Cablecast tenant serving 4 distinct Connecticut towns by
# gallery id (this project's own research found the other 3: Haddam=10,
# Deep River=9, Clinton=3), found while hand-checking CivicPlus
# governments whose AgendaCenter has no video but whose homepage links
# out to a separate video platform. `oldsaybrook_show_7480.html` is the
# real page for the specific show gallery/22's own listing picks as
# newest, used to confirm `_resolve_gallery()` really does delegate to
# (and get a real result from) that show's own canonical page rather than
# building a `ResolvedMeeting` out of the gallery's own (differently
# shaped, see `_GALLERY_EVENT_DATE_FORMAT`'s module note) data directly.

GALLERY_URL = "https://reflect-vsctv.cablecast.tv/internetchannel/gallery/22?site=1"
GALLERY_FETCH_URL = (
    "http://reflect-vsctv.cablecast.tv/internetchannel/gallery/22?site=1"
)
GALLERY_SHOW_URL = "http://reflect-vsctv.cablecast.tv/internetchannel/show/7480?site=1"


# --- WO-1036: "Cablecast Connect" WordPress plugin's /watch-vod-embed ---


def test_detect_platform_recognizes_watch_vod_embed_url():
    # Real hosts confirmed live (WO-1036, 2026-09-23): reflect-tst-mn.
    # cablecast.tv (Mendota Heights, MN) and reflect-dakotamediaaccess.
    # cablecast.tv (Bismarck, ND).
    assert (
        detect_platform(
            "https://reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=5964&site=8"
        )
        == "cablecast"
    )


def test_detect_platform_declines_watch_vod_embed_without_showid():
    assert (
        detect_platform("https://reflect-tst-mn.cablecast.tv/watch-vod-embed")
        == "unknown"
    )


def test_detect_platform_declines_watch_vod_embed_off_cablecast_tv():
    assert (
        detect_platform("https://example.org/watch-vod-embed?showId=5964") == "unknown"
    )


async def test_resolve_watch_vod_embed_reuses_the_fastboot_embed_path():
    # The plugin's iframe URL carries showId/site directly -- no separate
    # /show/{id} page to derive them from. Reuses the real, confirmed
    # `dyersville_embed_vod_3660.html` fixture's own `window.TRMS`/
    # `<source>` shape (see the real Dyersville FastBoot test above) --
    # the HOST/URL here is synthetic (no live Mendota Heights fixture
    # captured yet), but the embed page's own shape is the same real
    # template already confirmed live.
    url = "https://reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=5964&site=8"
    routes = {
        "https://reflect-tst-mn.cablecast.tv/embed/vod?show=5964&site=8": (
            FakeResponse(
                status=200,
                text=load_fixture("cablecast", "dyersville_embed_vod_3660.html"),
            )
        ),
        # The reused fixture's own <source> tag is an ABSOLUTE URL back to
        # the real Dyersville host it was captured from -- mocked here too
        # so this test stays fully offline; captions aren't the point of
        # this test (real caption fetching is already covered by the
        # Dyersville FastBoot test above), so a 404 (no captions found) is
        # fine.
        (
            "https://city-dyersville-ia.cablecast.tv/vod/"
            "3660-City-Council-Meeting-2026-09-08-v2/vod.m3u8"
        ): FakeResponse(status=404, text=""),
    }
    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.platform == "cablecast"
    # source_url stays the REAL given URL (the plugin's own iframe src),
    # not a synthesized /show/{id} URL this app never actually resolved --
    # see _resolve_watch_vod_embed()'s own docstring for why this matters
    # for Archive dedup.
    assert result.source_url == url
    assert result.title == "City Council Meeting 2026-09-08"
    assert result.external_id == "cablecast:reflect-tst-mn.cablecast.tv:5964"


async def test_resolve_watch_vod_embed_defaults_site_to_one():
    url = "https://reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=5964"
    routes = {
        "https://reflect-tst-mn.cablecast.tv/embed/vod?show=5964&site=1": (
            FakeResponse(
                status=200,
                text=load_fixture("cablecast", "dyersville_embed_vod_3660.html"),
            )
        ),
        (
            "https://city-dyersville-ia.cablecast.tv/vod/"
            "3660-City-Council-Meeting-2026-09-08-v2/vod.m3u8"
        ): FakeResponse(status=404, text=""),
    }
    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)
    assert result.platform == "cablecast"
    assert result.video_url is not None


async def test_resolve_watch_vod_embed_falls_through_without_a_showid():
    # No showId at all -- resolve() falls through to its own generic
    # _extract_show_id() handling (which also finds nothing here) rather
    # than this branch inventing a warning for an unconfirmed shape.
    url = "https://reflect-tst-mn.cablecast.tv/watch-vod-embed"
    result = await CablecastAssetFinder().resolve(url)
    assert result.video_warnings == ["Could not find a show id in this Cablecast URL."]


def test_detect_platform_recognizes_cablecast_gallery_url():
    assert detect_platform(GALLERY_URL) == "cablecast"


# --- WO-1036 (2026-09-23, Ryan confirmed): the bare, prefix-dropped
# `/gallery/{id}` shape -- Champaign, IL's real City Council hub,
# `champaign-cablecast.cablecast.tv/gallery/4`.

BARE_GALLERY_URL = "https://champaign-cablecast.cablecast.tv/gallery/4"


def test_detect_platform_recognizes_bare_gallery_url_without_internetchannel_prefix():
    assert detect_platform(BARE_GALLERY_URL) == "cablecast"


def test_detect_platform_declines_bare_gallery_path_off_cablecast_tv():
    assert detect_platform("https://example.org/gallery/4") == "unknown"


def test_gallery_id_re_matches_both_shapes():
    from app.platforms.cablecast import _GALLERY_ID_RE

    assert _GALLERY_ID_RE.search("/gallery/4").group(1) == "4"
    assert _GALLERY_ID_RE.search("/internetchannel/gallery/22").group(1) == "22"


async def test_resolve_bare_gallery_url_delegates_the_same_way_as_the_prefixed_form():
    # Reuses the real Old Saybrook gallery/show fixtures -- only the
    # REQUEST URL's shape (bare vs. /internetchannel/-prefixed) differs
    # from test_resolve_gallery_picks_newest_ready_show_and_delegates_...
    # above; the underlying Remix data and resolve behavior are identical.
    gallery_html = load_fixture("cablecast", "oldsaybrook_gallery_22.html")
    show_html = load_fixture("cablecast", "oldsaybrook_show_7480.html")
    bare_url = "https://reflect-vsctv.cablecast.tv/gallery/22?site=1"
    routes = {
        "http://reflect-vsctv.cablecast.tv/gallery/22?site=1": FakeResponse(
            status=200, text=gallery_html
        ),
        GALLERY_SHOW_URL: FakeResponse(status=200, text=show_html),
    }
    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(bare_url)
    assert result.video_url is not None
    assert result.date == "2026-08-19"


# --- WO-1036: list_gallery_shows() -- every video-ready show in a
# gallery, not just the newest.


def test_list_gallery_shows_returns_every_video_ready_show_newest_first():
    gallery_html = load_fixture("cablecast", "oldsaybrook_gallery_22.html")
    rows = list_gallery_shows(GALLERY_URL, gallery_html)
    assert len(rows) == 4
    assert rows[0]["url"] == GALLERY_SHOW_URL.replace("http://", "https://")
    assert rows[0]["date"] == "2026-08-19"
    assert rows[0]["has_video_hint"] is True
    # newest-first
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_list_gallery_shows_returns_empty_for_a_non_gallery_url():
    assert (
        list_gallery_shows("https://example.cablecast.tv/show/1", "<html></html>") == []
    )


def test_list_gallery_shows_returns_empty_when_gallery_not_found_in_page():
    assert (
        list_gallery_shows(
            GALLERY_URL, "<html><body>no remix context here</body></html>"
        )
        == []
    )


async def test_resolve_gallery_picks_newest_ready_show_and_delegates_to_its_own_page():
    gallery_html = load_fixture("cablecast", "oldsaybrook_gallery_22.html")
    show_html = load_fixture("cablecast", "oldsaybrook_show_7480.html")
    routes = {
        GALLERY_FETCH_URL: FakeResponse(status=200, text=gallery_html),
        GALLERY_SHOW_URL: FakeResponse(status=200, text=show_html),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(GALLERY_URL)

    # Real, live-confirmed newest ready show in this gallery page's own
    # scoped list as of 2026-09-23 -- picking the wrong one (an older
    # show, or content from a different gallery entirely -- see
    # `_resolve_gallery()`'s own docstring for a real bug that did
    # exactly that) would fail this.
    assert result.title == (
        "Old Saybrook Joint Zoning Commission Planning Commission "
        "Regional Housing Plan Workshop - August 19 2026"
    )
    assert result.date == "2026-08-19"
    assert result.video_url is not None
    # source_url reflects the show's own canonical page the gallery walk
    # delegated to, not the original gallery URL -- correct, matching
    # every other delegation this adapter already does (e.g. the
    # root-page fallback for a blocked bare "/show/{id}" URL above).
    assert (
        result.source_url
        == "http://reflect-vsctv.cablecast.tv/internetchannel/show/7480?site=1"
    )


def test_find_gallery_shows_matches_by_gallery_id_not_tree_position():
    # Real shape confirmed live 2026-09-23: a gallery page's remix tree
    # also embeds a site-wide "slideShow" carousel and OTHER galleries'
    # own sample shows (a different category, "Arts & Entertainment"),
    # both reachable from the same tree and both shaped just like a real
    # per-gallery shows list (a dict with a "shows" key). Only the one
    # object whose own `cablecastGalleryId` matches the id asked for
    # should ever be returned.
    tree = {
        "state": {
            "loaderData": {
                "root": {
                    "site": {
                        "slideShow": [{"showId": 999, "title": "sitewide decoy"}],
                        "galleries": [
                            {
                                "cablecastGalleryId": 8,
                                "title": "Arts & Entertainment",
                                "shows": [{"showId": 998, "title": "wrong gallery"}],
                            }
                        ],
                    }
                },
                "routes/_shell.gallery.$galleryId": {
                    "gallery": {
                        "cablecastGalleryId": 22,
                        "title": "Old Saybrook Meetings",
                        "shows": [{"showId": 7413, "title": "right gallery"}],
                    }
                },
            }
        }
    }
    found = CablecastAssetFinder._find_gallery_shows(tree, 22)
    assert found == [{"showId": 7413, "title": "right gallery"}]


async def test_resolve_gallery_reports_cleanly_when_no_show_is_video_ready():
    gallery_html_no_video = (
        "<html><body><script>window.__remixContext = "
        + json.dumps(
            {
                "state": {
                    "loaderData": {
                        "routes/_shell.gallery.$galleryId": {
                            "gallery": {
                                "cablecastGalleryId": 22,
                                "shows": [
                                    {"showId": 1, "title": "no video yet"},
                                ],
                            }
                        }
                    }
                }
            }
        )
        + ";</script></body></html>"
    )
    routes = {GALLERY_FETCH_URL: FakeResponse(status=200, text=gallery_html_no_video)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(GALLERY_URL)

    assert result.video_url is None
    assert "no video-ready show" in result.video_warnings[0].lower()


def test_parse_gallery_event_date_handles_both_real_formats():
    # Real bug found live 2026-09-23: the SAME show's eventDate appears in
    # BOTH formats within one gallery page (see
    # `_parse_gallery_event_date()`'s own docstring) -- whichever copy
    # survives must still parse.
    from datetime import datetime

    assert CablecastAssetFinder._parse_gallery_event_date(
        "7/10/2024 12:00:00 AM"
    ) == datetime(2024, 7, 10)
    assert CablecastAssetFinder._parse_gallery_event_date(
        "2024-07-10T00:00:00-04:00"
    ) == datetime(2024, 7, 10)
    assert CablecastAssetFinder._parse_gallery_event_date(None) is None
    assert CablecastAssetFinder._parse_gallery_event_date("not a date") is None


# --- WO-1045 (2026-09-24): title date beats a wrong eventDate ------------
# Collier County, FL (reflect-collier-countyboc.cablecast.tv), fetched
# live 2026-09-24. The show page itself answers 202 with an empty body
# (the WAF shape the root fallback exists for); the site root's Remix
# tree carries the show. Fields below are copied from that real record,
# trimmed to the ones the adapter reads.
COLLIER_HOST = "reflect-collier-countyboc.cablecast.tv"
COLLIER_SHOW_2277 = {
    "showId": "2277",
    "title": "County Commission - Sept. 22, 2026",
    "eventDate": "2026-09-21T04:00:00Z",
    "vodUrl": f"https://{COLLIER_HOST}/vod/2277-BCC-9-22-2026-v2/vod.m3u8",
}
COLLIER_SITE = {
    "siteId": "1",
    "host": COLLIER_HOST,
    "title": "Collier Television",
    "pageDescription": (
        "Collier Television is a service provided by the Collier County "
        "Board of County Commissioners"
    ),
}


async def test_resolve_prefers_the_titles_date_over_a_wrong_event_date():
    # eventDate 04:00Z is midnight Eastern -- this tenant's storage
    # convention for every show -- so the stored value really says
    # Sept 21. Not a time-zone shift; the title and the VOD file name
    # (BCC-9-22-2026) both say Sept 22.
    tree = {"shows": [COLLIER_SHOW_2277], "site": COLLIER_SITE}
    root_html = (
        "<html><body><script>window.__remixContext = "
        + json.dumps(tree)
        + ";</script></body></html>"
    )
    show_url = f"http://{COLLIER_HOST}/show/2277"
    root_url = f"http://{COLLIER_HOST}/"
    routes = {
        show_url: FakeResponse(status=202, text=""),
        root_url: FakeResponse(status=200, text=root_html),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(
            f"https://{COLLIER_HOST}/show/2277"
        )

    assert result.title == "County Commission - Sept. 22, 2026"
    assert result.date == "2026-09-22"
    assert result.video_url == COLLIER_SHOW_2277["vodUrl"]


def test_show_date_keeps_event_date_when_the_title_has_no_full_date():
    # Real Collier show 2265: "Sept. 3. 2026" (a period, not a comma)
    # doesn't parse as a full date, so its eventDate -- which agrees --
    # stands. And a title with no date at all is unaffected.
    assert (
        CablecastAssetFinder._show_date(
            {
                "title": "BCC Budget Hearing - Sept. 3. 2026",
                "eventDate": "2026-09-03T04:00:00Z",
            }
        )
        == "2026-09-03"
    )
    assert (
        CablecastAssetFinder._show_date(
            {
                "title": "Council Member YOUNG    Brush Park Manor Council Corner",
                "eventDate": "2026-08-29T06:04:03-04:00",
            }
        )
        == "2026-08-29"
    )
