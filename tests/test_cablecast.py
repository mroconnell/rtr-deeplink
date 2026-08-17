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
    assert result.title == "Council Meeting - June 22, 2026"
    assert result.date == "2026-06-22"
    assert result.jurisdiction == "Charlotte, NC"
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


async def test_resolve_falls_back_gracefully_when_transcript_fetch_fails():
    # A populated vodTranscripts entry whose URL 404s (or times out) must
    # degrade to the same honest "no transcript" outcome as one with no
    # entry at all, not raise or crash the whole resolve.
    html = load_fixture("cablecast", "charlotte_show_2451.html")
    fetch_url = "http://charlotte.cablecast.tv/internetchannel/show/2451?site=1"

    routes = {
        fetch_url: FakeResponse(status=200, text=html, url=fetch_url),
        CHARLOTTE_TRANSCRIPT_URL: FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(CHARLOTTE_PORTAL_URL)

    assert result.segments == []
    assert result.transcript_warnings == ["No transcript found for this event."]


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

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]


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
