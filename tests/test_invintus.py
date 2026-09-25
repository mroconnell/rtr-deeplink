import pytest

from app.platforms.invintus import (
    CLIENT_BODY_GOVERNMENTS,
    CLIENT_PLACE_PREFIXES,
    CLIENT_STATES,
    LEGISLATURE_CLIENTS,
    InvintusAssetFinder,
    is_invintus_meeting_url,
    parse_invintus_ids,
)

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# Invintus (player.invintus.com) -- found 2026-09-08 via a real gap on
# University Place, WA's CivicPlus AgendaCenter page (14 real per-meeting
# video links this repo had no adapter for). See invintus.py's own module
# docstring and `rtr-business/research/ENUMERATION_METHODS.md` §102 for
# the full investigation. `university_place_getDetailed.json` is a real,
# live `Event/getDetailed` response (clientID 1872740071, eventID
# 2026081000) fetched 2026-09-08, unmodified. `university_place_captions.
# vtt` is trimmed to its first 30 real cues (same "trimmed real VTT
# fixture" convention test_castus.py/test_telvue.py use for a long real
# transcript).

PAGE_URL = "https://player.invintus.com/?clientID=1872740071&eventID=2026081000"
API_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"
CAPTIONS_URL = (
    "https://m-download.invintus.com/1872740071/"
    "6ee20a1b6e41803e5e16810439a5c84076f78509.vtt"
)


async def test_resolve_real_university_place_city_council():
    detail_json = load_fixture("invintus", "university_place_getDetailed.json")
    captions_vtt = load_fixture("invintus", "university_place_captions.vtt")

    routes = {
        CAPTIONS_URL: FakeResponse(status=200, text=captions_vtt, url=CAPTIONS_URL),
    }
    post_routes = {
        API_URL: FakeResponse(status=200, text=detail_json, url=API_URL),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert result.platform == "invintus"
    assert result.external_id == "invintus:1872740071:2026081000"
    assert result.title == "University Place City Council 8/3/2026"
    assert result.date == "2026-08-03"
    # The state comes from CLIENT_STATES (Pierce County channel). Same
    # government as the bare "University Place" (us:place:5373465).
    assert result.jurisdiction == "University Place, WA"
    assert result.meeting_body == "University Place City Council"
    assert (
        result.video_url == "https://m-download.invintus.com/1872740071/"
        "096f7a9a4fefe5971b5f2b04b34c444fba43a5ee.mp4"
    )
    assert result.video_format == "mp4"
    assert result.video_warnings == []
    assert len(result.segments) == 30
    assert (
        result.segments[0].text
        == "All right, all right good evening ladies and gentlemen."
    )
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []


async def test_resolve_falls_back_to_hls_when_no_direct_download_link(monkeypatch):
    # Real shape confirmed live is always `downloadLinks.videoDownloadURI`
    # -- this covers the documented `streamingURIs.main` fallback in case
    # a future tenant's event ever omits it.
    import json

    data = json.loads(load_fixture("invintus", "university_place_getDetailed.json"))
    data["data"]["downloadLinks"] = {}
    data["data"]["captionPath"] = None

    # No captionPath but streamingURIs.main is set (used as the fallback
    # video URL above), so resolve() would otherwise try a real embedded-
    # captions probe against it -- irrelevant to what this test covers
    # (the video URL fallback), so it's stubbed out.
    async def fake_probe(session, stream_url):
        return False

    monkeypatch.setattr("app.platforms.invintus.probe_embedded_captions", fake_probe)

    post_routes = {
        API_URL: FakeResponse(status=200, text=json.dumps(data), url=API_URL),
    }

    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert (
        result.video_url
        == "https://api.v3.invintus.com/StreamURI/hls/1872740071/2026081000/media.m3u8"
    )
    assert result.video_format == "m3u8"
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_resolve_degrades_when_categories_and_captions_are_null(monkeypatch):
    # Real shape confirmed live on Des Moines, WA (a historical, now-
    # churned Invintus customer) and Leon County, FL's Tourism
    # Development Council: `categories`/`captionPath` are `null`, not
    # every tenant sets them.
    import json

    data = json.loads(load_fixture("invintus", "university_place_getDetailed.json"))
    data["data"]["categories"] = None
    data["data"]["captionPath"] = None
    data["data"]["title"] = "City Council, September 17, 2020"

    # captionPath is null but streamingURIs.main is still set on this
    # fixture, so resolve() would otherwise run a real embedded-captions
    # probe -- irrelevant to what this test covers (categories/title),
    # so it's stubbed to the plain "no captions" branch.
    async def fake_probe(session, stream_url):
        return False

    monkeypatch.setattr("app.platforms.invintus.probe_embedded_captions", fake_probe)

    post_routes = {
        API_URL: FakeResponse(status=200, text=json.dumps(data), url=API_URL),
    }

    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert result.title == "City Council, September 17, 2020"
    assert result.jurisdiction is None
    assert result.meeting_body is None
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]
    # Video is unaffected -- this only exercises the categories/captions gap.
    assert result.video_url is not None


async def test_resolve_no_event_found_degrades_to_warning_not_exception():
    post_routes = {
        API_URL: FakeResponse(
            status=200,
            text='{"errors": {"hasError": true, "message": "Event not found"}, "data": null}',
            url=API_URL,
        ),
    }

    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert result.platform == "invintus"
    assert result.external_id == "invintus:1872740071:2026081000"
    assert result.video_url is None
    assert result.video_warnings == ["No event found for this Invintus meeting."]


async def test_resolve_missing_ids_raises_value_error():
    with pytest.raises(ValueError):
        await InvintusAssetFinder().resolve("https://player.invintus.com/")


def test_parse_invintus_ids_normalizes_html_entity_ampersand():
    # Real shape confirmed live in University Place's own raw AgendaCenter
    # page source (un-decoded `&amp;` between params).
    url = "https://player.invintus.com/?clientID=1872740071&amp;eventID=2026081000"
    assert parse_invintus_ids(url) == ("1872740071", "2026081000")


def test_is_invintus_meeting_url_requires_both_ids():
    assert is_invintus_meeting_url(PAGE_URL) is True
    assert is_invintus_meeting_url("https://player.invintus.com/?clientID=123") is False
    assert (
        is_invintus_meeting_url("https://hostedevents.invintus.com/equitysummit/")
        is False
    )
    assert is_invintus_meeting_url("https://example.gov/agendacenter") is False


# WO-1065 (2026-09-25): a real event (Oregon Legislature Joint Emergency
# Board, clientID 4879615486, eventID 2026091029) that has no captionPath
# at all, but does have a playable HLS stream (streamingURIs.main) --
# real shape confirmed live, see embedded_captions.py's module docstring
# and invintus.py's updated caption comment block.
OREGON_PAGE_URL = "https://player.invintus.com/?clientID=4879615486&eventID=2026091029"
OREGON_STREAM_URL = (
    "https://api.v3.invintus.com/StreamURI/hls/4879615486/2026091029/media.m3u8"
)


async def test_resolve_adds_embedded_captions_warning_when_probe_finds_words(
    monkeypatch,
):
    detail_json = load_fixture(
        "invintus", "getdetailed_oregon_eb_2026091029_embedded.json"
    )

    async def fake_probe(session, stream_url):
        assert stream_url == OREGON_STREAM_URL
        return True

    monkeypatch.setattr("app.platforms.invintus.probe_embedded_captions", fake_probe)

    post_routes = {
        API_URL: FakeResponse(status=200, text=detail_json, url=API_URL),
    }
    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(OREGON_PAGE_URL)

    assert result.segments == []
    assert result.transcript_warnings == [
        "Captions are embedded in this video but aren't text yet. We'll "
        "add them to this page once they're extracted."
    ]


@pytest.mark.parametrize("probe_result", [False, None])
async def test_resolve_keeps_no_captions_warning_when_probe_finds_nothing(
    monkeypatch, probe_result
):
    detail_json = load_fixture(
        "invintus", "getdetailed_oregon_eb_2026091029_embedded.json"
    )

    async def fake_probe(session, stream_url):
        return probe_result

    monkeypatch.setattr("app.platforms.invintus.probe_embedded_captions", fake_probe)

    post_routes = {
        API_URL: FakeResponse(status=200, text=detail_json, url=API_URL),
    }
    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(OREGON_PAGE_URL)

    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


# --- Place from a body-name category (2026-09-25) ------------------------
#
# Real `Event/getDetailed` responses, captured live 2026-09-25 from
# api.v3.invintus.com, trimmed to the fields the adapter reads (eventID,
# clientID, startDateTime, title, categories, categoriesDetail,
# captionPath, downloadLinks, streamingURIs); values unmodified:
#   dupont_getDetailed.json                      1872740071 / 2026091009
#   fife_reversed_categories_getDetailed.json    1872740071 / 2026061017
#   tacoma_pierce_board_of_health_getDetailed.json 1872740071 / 2026091032
#   cvtv_vancouver_getDetailed.json              2917038973 / 2026091017
# `dupont_captions.vtt` is the first 20 real cues of that event's
# captionPath file, fetched the same day.

PIERCE = "1872740071"
CVTV = "2917038973"


def _page(client_id, event_id):
    return f"https://player.invintus.com/?clientID={client_id}&eventID={event_id}"


async def _resolve_fixture(name, client_id, event_id, routes=None):
    post_routes = {
        API_URL: FakeResponse(
            status=200, text=load_fixture("invintus", name), url=API_URL
        ),
    }
    with mock_session(routes or {}, post_routes=post_routes):
        return await InvintusAssetFinder().resolve(_page(client_id, event_id))


async def test_resolve_real_dupont_splits_city_council_and_adds_state():
    # Only category is the body, "DuPont City Council". Handing that to
    # the resolver gave "unresolved"; adding only the state minted
    # rtr:us:wa:dupont-city-council. "DuPont, WA" is us:place:5318965.
    captions_url = (
        "https://m-download.invintus.com/1872740071/"
        "ffab77b4b3c632172001f88863c0028f2e635ed9.vtt"
    )
    routes = {
        captions_url: FakeResponse(
            status=200,
            text=load_fixture("invintus", "dupont_captions.vtt"),
            url=captions_url,
        )
    }
    result = await _resolve_fixture(
        "dupont_getDetailed.json", PIERCE, "2026091009", routes
    )

    assert result.title == "DuPont City Council 9/22/2026"
    assert result.date == "2026-09-22"
    assert result.jurisdiction == "DuPont, WA"
    assert result.meeting_body == "DuPont City Council"
    assert len(result.segments) == 20
    assert result.transcript_warnings == []


async def test_resolve_real_cvtv_vancouver_city_council():
    # CVTV lists only "Vancouver City Council", and has no captionPath.
    result = await _resolve_fixture(
        "cvtv_vancouver_getDetailed.json", CVTV, "2026091017"
    )

    assert result.title == "Vancouver City Council (09-21-26)"
    assert result.jurisdiction == "Vancouver, WA"
    assert result.meeting_body == "Vancouver City Council"
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_resolve_real_fife_with_body_listed_first():
    # The flat list here is ["Fife City Council", "Fife"], body first.
    # categoriesDetail says "Fife" is the top entry, so the place is
    # read from there, not from categories[0].
    result = await _resolve_fixture(
        "fife_reversed_categories_getDetailed.json", PIERCE, "2026061017"
    )

    assert result.jurisdiction == "Fife, WA"
    assert result.meeting_body == "Fife City Council"


async def test_resolve_real_board_of_health_gets_no_state():
    # "Tac-PC Board of Health" names no place. With ", WA" added it
    # would mint rtr:us:wa:tac-pc-board-of-health, so it stays as-is.
    result = await _resolve_fixture(
        "tacoma_pierce_board_of_health_getDetailed.json", PIERCE, "2026091032"
    )

    assert result.jurisdiction == "Tac-PC Board of Health"
    assert result.meeting_body is None


def test_county_council_with_committee_child():
    # Real Pierce channel shapes (categoriesDetail, IDs as served live
    # 2026-09-25): the committee is the child of "Pierce County Council".
    detail = [
        {"ID": "433", "name": "Pierce County Perf Audit", "childOf": "94"},
        {"ID": "94", "name": "Pierce County Council", "childOf": None},
    ]
    assert InvintusAssetFinder._extract_categories(
        ["Pierce County Perf Audit", "Pierce County Council"], detail, "WA"
    ) == ("Pierce County, WA", "Pierce County Perf Audit")
    only_council = [{"ID": "94", "name": "Pierce County Council", "childOf": None}]
    assert InvintusAssetFinder._extract_categories(
        ["Pierce County Council"], only_council, "WA"
    ) == ("Pierce County, WA", "Pierce County Council")


def test_place_with_non_council_child_gets_state():
    # Real Sumner shape: "Sumner" alone is unresolved (several states
    # have one); "Sumner, WA" is us:place:5368435.
    detail = [
        {"ID": "107", "name": "Sumner", "childOf": None},
        {"ID": "7050", "name": "Sumner Study Session ", "childOf": "107"},
    ]
    assert InvintusAssetFinder._extract_categories(
        ["Sumner", "Sumner Study Session "], detail, "WA"
    ) == ("Sumner, WA", "Sumner Study Session")


def test_unknown_client_splits_body_but_adds_no_state():
    # A customer not in CLIENT_STATES: the place is still split off, but
    # no state is guessed.
    detail = [{"ID": "95", "name": "DuPont City Council", "childOf": None}]
    assert InvintusAssetFinder._extract_categories(
        ["DuPont City Council"], detail, None
    ) == ("DuPont", "DuPont City Council")


def test_without_categories_detail_first_category_is_the_top():
    # No categoriesDetail: behaves as before (first category, last one
    # as the body).
    assert InvintusAssetFinder._extract_categories(
        ["University Place", "University Place City Council"]
    ) == ("University Place", "University Place City Council")


def test_client_states_never_covers_a_legislature_tenant():
    # WO-922's legislature path owns those tenants; WisconsinEye in
    # particular also carries courts and news conferences.
    assert not set(CLIENT_STATES) & set(LEGISLATURE_CLIENTS)


# --- CVTV place prefixes and the Leon County pin (WO-1066, 2026-09-25) ---
# Real category shapes, read live from CVTV's (2917038973) own
# Event/getDetailed on 2026-09-25: each is one top entry, no child.


def _cvtv(name):
    return InvintusAssetFinder._extract_categories(
        [name],
        [{"ID": "1", "name": name, "childOf": None}],
        CLIENT_STATES["2917038973"],
        CLIENT_PLACE_PREFIXES["2917038973"],
        CLIENT_BODY_GOVERNMENTS["2917038973"],
    )


@pytest.mark.parametrize(
    "category, place",
    [
        ("Clark County Planning Commission", "Clark County, WA"),
        ("Clark County Board of Health", "Clark County, WA"),
        ("Clark County Land Use Hearings", "Clark County, WA"),
        ("Clark County Veterans Advisory Board", "Clark County, WA"),
        ("Clark County Commission on Aging", "Clark County, WA"),
        ("Vancouver Planning Commission", "Vancouver, WA"),
        ("Vancouver Land Use Hearings", "Vancouver, WA"),
        # Unchanged by the prefixes: the council rule already placed these.
        ("Vancouver City Council", "Vancouver, WA"),
        ("Clark County Council", "Clark County, WA"),
    ],
)
def test_cvtv_body_under_a_place_prefix(category, place):
    assert _cvtv(category) == (place, category)


@pytest.mark.parametrize(
    "category",
    [
        # Its own government, with no registry id: stays blank.
        "Regional Transportation Council",
        # Names no city, in its category or its description ("Complete
        # coverage of the September 21, 2026, City Council workshop
        # meeting."): stays blank rather than guessed as Vancouver.
        "City Council Workshops",
    ],
)
def test_cvtv_category_without_a_place_stays_as_is(category):
    assert _cvtv(category) == (category, None)


def test_place_prefix_skips_a_special_district():
    # Synthetic: no CVTV category names a district or authority yet
    # (checked 2026-09-25). C-TRAN's legal name is the real one.
    for name in (
        "Clark County Public Transportation Benefit Area Authority",
        "Clark County Fire District 6",
    ):
        assert _cvtv(name) == (name, None)


def test_place_prefixes_only_for_a_channel_with_a_state():
    assert set(CLIENT_PLACE_PREFIXES) <= set(CLIENT_STATES)


def test_leon_county_channel_is_pinned_to_leon_county():
    # Leon County's categories are folder names ("Board Meetings"); the
    # whole-customer pin in tenant_overrides.csv files every event there.
    from app.utils.gov_registry.resolver import resolve_government

    for raw in ("Board Meetings", "Tourism Development Council Meetings", None):
        match = resolve_government(
            raw,
            tenant_host="player.invintus.com",
            path="/?clientID=4853176732&eventID=2026091000",
        )
        assert match.gov_id == "us:county:12073"
    # CVTV is a mixed listing and has no whole-customer pin.
    other = resolve_government(
        "City Council Workshops",
        tenant_host="player.invintus.com",
        path="/?clientID=2917038973&eventID=2026091015",
    )
    assert other.gov_id != "us:county:12073"


# --- CVTV bodies that are their own governments (WO-1067, 2026-09-25) ---
# Real CVTV categories, read live 2026-09-25. Each is a Census of
# Governments unit with a curated registry row (curated_governments.csv).


@pytest.mark.parametrize(
    "category, government, gov_id",
    [
        (
            "Port of Vancouver Board of Commissioners",
            "Port of Vancouver, WA",
            "rtr:us:wa:port-of-vancouver",
        ),
        ("C-TRAN Board of Directors", "C-TRAN, WA", "rtr:us:wa:c-tran"),
    ],
)
def test_cvtv_body_that_is_its_own_government(category, government, gov_id):
    from app.utils.gov_registry.resolver import resolve_government

    assert _cvtv(category) == (government, category)
    match = resolve_government(
        government,
        tenant_host="player.invintus.com",
        path="/?clientID=2917038973&eventID=2026091001",
    )
    assert match.gov_id == gov_id
    # Never the city or the county it sits in.
    assert match.gov_id not in ("us:place:5374060", "us:county:53011")


def test_body_governments_only_for_a_channel_with_a_state():
    assert set(CLIENT_BODY_GOVERNMENTS) <= set(CLIENT_STATES)
