"""Tests for the Invintus hub walker (WO-922, 2026-09-20).

Everything under `tests/fixtures/invintus_hub/` is a real response captured
2026-09-20 from the two state-legislature tenants this WO found, trimmed to
a handful of rows (shape unchanged):

  * Oregon Legislature, clientID 4879615486 (its video page,
    oregonlegislature.gov, embeds `InvintusEventListing.launch(...)`).
  * WisconsinEye, clientID 2789595964 (wiseye.org, which also carries
    courts, the governor and news conferences, so the walker filters).
  * `empty_tenant_search.json`: the real answer for a clientID that owns
    no events (1000000001).
  * `*_getDetailed.json`: real `Event/getDetailed` answers. Neither has a
    `captionPath`: 0 of 75 sampled legislative events on either tenant did.
"""

import json

from app.platforms.base import register
from app.platforms.invintus import (
    LEGISLATURE_CLIENTS,
    InvintusAssetFinder,
    extract_invintus_client_id,
    is_invintus_hub_url,
    is_invintus_meeting_url,
    legislative_chamber,
    legislative_meeting_body,
    list_recent_events,
)
from app.platforms.passive_verify import _invintus_walker, verify_hub

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

OR = "4879615486"
WI = "2789595964"
SEARCH_URL = "https://api.v3.invintus.com/v2/Search/general"
DETAIL_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"
OR_PAGE = (
    "https://www.oregonlegislature.gov/citizen_engagement/Pages/Legislative-Video.aspx"
)
WI_PAGE = "https://wiseye.org/2026/06/02/joint-committee-on-finance-191/"


def _search(fixture):
    return FakeResponse(
        status=200, text=load_fixture("invintus_hub", fixture), url=SEARCH_URL
    )


# --- chamber classification (real titles and categories) ---------------


def test_oregon_chambers_from_real_titles():
    cases = {
        "Joint Interim Committee On Interstate 5 Bridge 09/17/2026 1:00 PM": "Joint",
        "House Interim Committee On Higher Education 09/10/2026 12:30 PM": "House",
        "Senate Chamber Convenes 09/10/2026 11:00 AM": "Senate",
        "Public Meetings Law Workgroup - September 17, 2026": None,
        "Vote-by-Mail Press Conference with Secretary of State Tobias Read": None,
        "Testing Electronic Reading New Voices": None,
    }
    for title, expected in cases.items():
        assert legislative_chamber(OR, title, []) == expected, title


def test_wisconsin_chambers_from_real_titles_and_categories():
    cases = [
        (
            "Assembly Committee on Environment",
            ["Committees", "State Assembly"],
            "Assembly",
        ),
        ("Senate Committee on Health", ["Committees", "State Senate"], "Senate"),
        (
            "Joint Committee on Finance",
            ["Committees", "Meetings", "State Assembly", "State Senate"],
            "Joint",
        ),
        (
            "2026 Legislative Council Study Committee on Cemeteries",
            ["Study Committee", "Meetings"],
            "Joint",
        ),
        (
            "Wisconsin State Assembly Floor Session",
            ["Assembly Floor Session", "State Assembly"],
            "Assembly",
        ),
        ("Wisconsin State Senate Floor Session", ["Senate Floor Session"], "Senate"),
        # Not legislative meetings:
        (
            "Governors Commutation Advisory Board - Part 2",
            ["Governor", "Meetings"],
            None,
        ),
        (
            "Dane County Circuit Court: Josh Kaul et al vs. Wisconsin State Legislature Joint Committee",
            ["Circuit Court"],
            None,
        ),
        (
            "Campaign 2026 News Conference: Democrats Highlight Tax Burden",
            ["Campaign", "News Conferences", "State Senate"],
            None,
        ),
        (
            "WisPolitics-State Affairs Luncheon with Senate Democratic Leader Dianne Hesselbein",
            ["WisPolitics"],
            None,
        ),
        (
            "News Conference: Assembly Republicans Pre-Session",
            ["News Conferences", "State Assembly"],
            None,
        ),
    ]
    for title, cats, expected in cases:
        assert legislative_chamber(WI, title, cats) == expected, title


def test_tvw_chambers_from_real_titles_and_categories():
    # Real TVW (Washington) titles/categories, 2026-09-22 (WO-1010) --
    # confirmed via a live 50-row/520-total Search/general sample that no
    # non-legislative TVW program (courts, agencies, "Inside Olympia")
    # carries the "Legislative" category tag.
    TVW = "9375922947"
    cases = [
        ("Senate Housing", ["Legislative", "Senate Housing"], "Senate"),
        (
            "House Agriculture & Natural Resources",
            ["Legislative", "House Agriculture & Natural Resources"],
            "House",
        ),
        (
            "Joint Oregon-Washington Legislative Action Committee",
            ["Legislative", "Joint Oregon-Washington Legislative Action Committee"],
            "Joint",
        ),
        (
            "JLARC - Joint Legislative Audit & Review Committee",
            ["Legislative", "Joint Legislative Audit & Review Committee"],
            "Joint",
        ),
        (
            "Select Committee on Pension Policy",
            ["Legislative", "Select Committee on Pension Policy"],
            "Joint",
        ),
        # Not legislative meetings -- no "Legislative" category tag:
        (
            "Division 2 Court of Appeals",
            ["Division 2 Court of Appeals", "Other Court"],
            None,
        ),
        (
            "Bi-State Tolling Subcommittee",
            ["Agencies and Boards", "Bi-State Tolling Subcommittee"],
            None,
        ),
        ("Inside Olympia - Washington Income Tax", ["Inside Olympia", "SERIES"], None),
    ]
    for title, cats, expected in cases:
        assert legislative_chamber(TVW, title, cats) == expected, title


def test_unknown_tenant_has_no_chamber():
    # University Place, WA (the tenant invintus.py was first built on).
    assert legislative_chamber("1872740071", "House Committee", []) is None


def test_meeting_body_drops_oregons_trailing_date_time():
    assert (
        legislative_meeting_body("House Committee On Health Care 02/26/2026 3:00 PM")
        == "House Committee On Health Care"
    )
    assert (
        legislative_meeting_body("Assembly Committee on Environment")
        == "Assembly Committee on Environment"
    )


# --- listing --------------------------------------------------------------


async def test_oregon_listing_newest_first_legislative_only():
    with mock_session({}, post_routes={SEARCH_URL: _search("oregon_search.json")}):
        events = await list_recent_events(OR)
    assert [e["event_id"] for e in events] == [
        "2026091050",
        "2026091002",
        "2026091000",
        "2026061048",
    ]
    first = events[0]
    assert first["chamber"] == "Joint"
    assert first["date"] == "2026-09-17"
    assert first["duration"] == 151 * 60
    assert first["url"] == (
        "https://player.invintus.com/?clientID=4879615486&eventID=2026091050"
    )
    assert [e["chamber"] for e in events] == ["Joint", "House", "Senate", "Joint"]


async def test_wisconsin_listing_drops_courts_news_and_governor():
    with mock_session({}, post_routes={SEARCH_URL: _search("wisconsin_search.json")}):
        events = await list_recent_events(WI)
    titles = [e["title"] for e in events]
    assert titles == [
        "2026 Legislative Council Study Committee on the Use of Artificial "
        "Intelligence in Health Care",
        "Joint Committee on Finance",
        "Senate Committee on Health",
        "Wisconsin State Senate Floor Session",
        "Wisconsin State Assembly Floor Session",
        "Assembly Committee on Environment",
    ]
    assert [e["chamber"] for e in events] == [
        "Joint",
        "Joint",
        "Senate",
        "Senate",
        "Assembly",
        "Assembly",
    ]


async def test_legislative_only_false_keeps_every_event():
    with mock_session({}, post_routes={SEARCH_URL: _search("wisconsin_search.json")}):
        events = await list_recent_events(WI, legislative_only=False)
    assert len(events) == 11


async def test_tenant_with_no_events_lists_nothing():
    # Negative control: the real answer for a clientID that owns no events.
    with mock_session(
        {}, post_routes={SEARCH_URL: _search("empty_tenant_search.json")}
    ):
        assert await list_recent_events("1000000001") == []


# --- hub recognition -------------------------------------------------------


def test_hub_url_is_a_client_id_without_an_event_id():
    assert is_invintus_hub_url("https://player.invintus.com/?clientID=4879615486")
    assert not is_invintus_hub_url(
        "https://player.invintus.com/?clientID=4879615486&eventID=2026091050"
    )
    assert not is_invintus_hub_url("https://www.oregonlegislature.gov/?clientID=1")
    assert not is_invintus_hub_url("https://player.invintus.com/")
    # A meeting URL stays a meeting URL; a hub URL is not one.
    assert is_invintus_meeting_url(
        "https://player.invintus.com/?clientID=4879615486&eventID=2026091050"
    )
    assert not is_invintus_meeting_url(
        "https://player.invintus.com/?clientID=4879615486"
    )


def test_client_id_read_from_real_government_page_markup():
    assert (
        extract_invintus_client_id(
            load_fixture("invintus_hub", "oregon_video_page_snippet.html")
        )
        == OR
    )
    assert (
        extract_invintus_client_id(
            load_fixture("invintus_hub", "wiseye_event_page_snippet.html")
        )
        == WI
    )


def test_client_id_needs_invintus_on_the_page():
    # Negative control: a clientID with no Invintus anywhere is some other
    # service's id and is not taken.
    assert (
        extract_invintus_client_id('<script>launch({"clientID":"1234567890"})</script>')
        is None
    )
    assert (
        extract_invintus_client_id("<html><title>Example Domain</title></html>") is None
    )


# --- the walker -------------------------------------------------------------


async def test_walker_from_a_player_hub_url():
    with mock_session({}, post_routes={SEARCH_URL: _search("oregon_search.json")}):
        candidates = await _invintus_walker(
            "https://player.invintus.com/?clientID=4879615486"
        )
    assert candidates[0]["url"].endswith("eventID=2026091050")
    assert candidates[0]["title"].startswith("Joint Interim Committee On Interstate 5")


async def test_walker_from_the_oregon_government_page():
    routes = {
        OR_PAGE: FakeResponse(
            status=200,
            text=load_fixture("invintus_hub", "oregon_video_page_snippet.html"),
            url=OR_PAGE,
        )
    }
    with mock_session(routes, post_routes={SEARCH_URL: _search("oregon_search.json")}):
        candidates = await _invintus_walker(OR_PAGE)
    assert len(candidates) == 4
    assert {c["client_id"] for c in candidates} == {OR}


async def test_walker_from_the_wisconsin_page():
    routes = {
        WI_PAGE: FakeResponse(
            status=200,
            text=load_fixture("invintus_hub", "wiseye_event_page_snippet.html"),
            url=WI_PAGE,
        )
    }
    with mock_session(
        routes, post_routes={SEARCH_URL: _search("wisconsin_search.json")}
    ):
        candidates = await _invintus_walker(WI_PAGE)
    assert len(candidates) == 6
    assert {c["client_id"] for c in candidates} == {WI}


async def test_walker_on_a_non_invintus_host_returns_nothing():
    # Negative control: a real, ordinary page that mentions no Invintus.
    page = "https://example.gov/meetings"
    routes = {
        page: FakeResponse(
            status=200,
            text="<html><title>Example Domain</title><body>Meetings</body></html>",
            url=page,
        )
    }
    with mock_session(routes, post_routes={}):
        assert await _invintus_walker(page) == []


# --- resolve() on a legislative event ---------------------------------------


async def test_resolve_oregon_committee_is_filed_under_the_legislature():
    detail = FakeResponse(
        status=200, text=load_fixture("invintus_hub", "oregon_getDetailed.json")
    )
    url = "https://player.invintus.com/?clientID=4879615486&eventID=2026091002"
    with mock_session({}, post_routes={DETAIL_URL: detail}):
        result = await InvintusAssetFinder().resolve(url)
    assert result.jurisdiction == "Oregon Legislative Assembly"
    assert result.meeting_body == "House Interim Committee On Higher Education"
    assert result.video_format == "mp4"
    assert result.video_url.startswith("https://m-download.invintus.com/4879615486/")
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_resolve_wisconsin_committee_is_filed_under_the_legislature():
    detail = FakeResponse(
        status=200, text=load_fixture("invintus_hub", "wisconsin_getDetailed.json")
    )
    url = "https://player.invintus.com/?clientID=2789595964&eventID=2026051017"
    with mock_session({}, post_routes={DETAIL_URL: detail}):
        result = await InvintusAssetFinder().resolve(url)
    assert result.jurisdiction == "Wisconsin State Legislature"
    assert result.meeting_body == "Assembly Committee on Environment"


async def test_resolve_wisconsin_non_legislative_event_keeps_its_own_categories():
    # A WisconsinEye event that is not a legislative meeting must NOT be
    # relabelled as the Legislature.
    payload = json.loads(load_fixture("invintus_hub", "wisconsin_getDetailed.json"))
    payload["data"]["title"] = "Governors Commutation Advisory Board - Part 2"
    payload["data"]["categories"] = ["Governor", "Public Hearings", "Meetings"]
    detail = FakeResponse(status=200, text=json.dumps(payload))
    url = "https://player.invintus.com/?clientID=2789595964&eventID=2026091011"
    with mock_session({}, post_routes={DETAIL_URL: detail}):
        result = await InvintusAssetFinder().resolve(url)
    assert result.jurisdiction == "Governor"
    assert result.jurisdiction != "Wisconsin State Legislature"


# --- verify_hub() end to end -------------------------------------------------


async def test_verify_hub_walks_the_oregon_page_to_real_video():
    register(InvintusAssetFinder())
    routes = {
        OR_PAGE: FakeResponse(
            status=200,
            text=load_fixture("invintus_hub", "oregon_video_page_snippet.html"),
            url=OR_PAGE,
        )
    }
    post_routes = {
        SEARCH_URL: _search("oregon_search.json"),
        DETAIL_URL: FakeResponse(
            status=200, text=load_fixture("invintus_hub", "oregon_getDetailed.json")
        ),
    }
    with mock_session(routes, post_routes=post_routes):
        result = await verify_hub(OR_PAGE, platform_hint="invintus")
    assert result.meeting_found is True
    assert result.video_found is True
    assert result.captions_found is False
    assert result.platform == "invintus"
    assert result.meeting_url.startswith(
        "https://player.invintus.com/?clientID=4879615486"
    )


async def test_verify_hub_recognizes_a_player_hub_url_without_a_hint():
    register(InvintusAssetFinder())
    post_routes = {
        SEARCH_URL: _search("oregon_search.json"),
        DETAIL_URL: FakeResponse(
            status=200, text=load_fixture("invintus_hub", "oregon_getDetailed.json")
        ),
    }
    with mock_session({}, post_routes=post_routes):
        result = await verify_hub("https://player.invintus.com/?clientID=4879615486")
    assert result.video_found is True
    assert result.platform == "invintus"


async def test_verify_hub_finds_wisconsin_from_the_page_alone():
    # No platform hint and no Invintus link: the client id in the page's
    # own script config is the only signal.
    register(InvintusAssetFinder())
    routes = {
        WI_PAGE: FakeResponse(
            status=200,
            text=load_fixture("invintus_hub", "wiseye_event_page_snippet.html"),
            url=WI_PAGE,
        )
    }
    post_routes = {
        SEARCH_URL: _search("wisconsin_search.json"),
        DETAIL_URL: FakeResponse(
            status=200, text=load_fixture("invintus_hub", "wisconsin_getDetailed.json")
        ),
    }
    with mock_session(routes, post_routes=post_routes):
        result = await verify_hub(WI_PAGE)
    assert result.video_found is True
    assert result.platform == "invintus"


def test_known_legislature_clients_map_to_one_state_government():
    assert LEGISLATURE_CLIENTS[OR][0] == "us:state:41"
    assert LEGISLATURE_CLIENTS[WI][0] == "us:state:55"


# --- pins ---------------------------------------------------------------------


def test_oregon_and_wisconsin_pins_are_scoped_never_by_host_alone():
    from app.utils.gov_registry import resolve_government
    from app.utils.gov_registry.resolver import page_hints_for

    def gov_for(cid, eid, name):
        return resolve_government(
            name,
            tenant_host="player.invintus.com",
            path=f"/?clientID={cid}&eventID={eid}",
            page_hints=page_hints_for("invintus", f"invintus:{cid}:{eid}"),
        )

    oregon = gov_for(OR, "2026021271", "Oregon Legislative Assembly")
    assert oregon.government.gov_id == "us:state:41"
    assert oregon.tier == "pinned"
    # A different Invintus customer (University Place, WA) is untouched.
    other = gov_for("1872740071", "2026081000", "University Place")
    assert other.government.gov_id != "us:state:41"
    assert "wo922" not in other.evidence
