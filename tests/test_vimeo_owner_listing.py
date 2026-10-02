"""List the account behind a bare Vimeo video link (2026-10-02,
rtr-findmeeting request "list a Vimeo account from a bare Vimeo video
link").

Every fixture used here is a real, unmodified live capture taken
2026-10-02 from an office Mac with `vimeo.py`'s own User-Agent, one
request at a time -- see `vimeo.py`'s "Listing a video's OWNER account"
comment block for the investigation. The five videos are the weak Vimeo
finds rtr-findmeeting's pipe reported:

- `oembed_malverne_168650512.json` -- Malverne NY, "Memorial Day - 2016",
  owner `malvernetv` (MalverneTV, a real village account).
- `v2_videos_malvernetv_page{1,2,3}.json` -- that owner's 60 newest videos
  from Vimeo's public v2 API (`vimeo.com/api/v2/malvernetv/videos.json`),
  full of "Village of Malverne - Meeting of the Board of Trustees" rows.
- `v2_videos_malvernetv_page4_forbidden.html` -- page 4 of the same API: a
  real 403 "You are not permitted" page. 60 is the ceiling.
- `rss_malvernetv.xml` -- the same owner's RSS feed (10 newest), the
  fallback when the API can't be read.
- `oembed_clinton_575538718.json` + `v2_videos_user142310876.json` --
  Clinton MO's find: owner "keith stidham", 14 videos, all promo clips.
- `oembed_howells_200384043.json` + `v2_videos_ncf_page1.json` -- Howells
  NE's find: owner Nebraska Community Foundation (`ncf`).
- `oembed_tarentum_391007677_no_owner.json` -- Tarentum PA's find: oEmbed
  answers 200 with no title and no author (the owner hid the video).
- `video_page_391007677_human_check.html` -- `vimeo.com/391007677` itself:
  a real "Verify to continue ... confirm that you're a human" page. Kept to
  prove the parsers read it as "nothing", never as something to get past.
"""

from types import SimpleNamespace
from urllib.parse import quote

import pytest

from app.platforms import vimeo
from app.platforms.meeting_finder import identify as identify_mod
from app.platforms.meeting_finder import listing
from app.platforms.meeting_finder.models import VerdictRow
from app.platforms.meeting_finder.verdict import append_verdict
from app.platforms.vimeo import (
    LISTER_RSS,
    LISTER_V2_API,
    list_owner_videos,
    owner_slug_from_author_url,
    parse_user_rss,
    parse_v2_videos_json,
)

from conftest import load_fixture


def _oembed_url(video_id: str) -> str:
    return vimeo._OEMBED_ENDPOINT + quote(f"https://vimeo.com/{video_id}", safe="")


def _v2_url(owner: str, page: int) -> str:
    return f"https://vimeo.com/api/v2/{owner}/videos.json?page={page}"


MALVERNE_ROUTES = {
    _oembed_url("168650512"): "oembed_malverne_168650512.json",
    _v2_url("malvernetv", 1): "v2_videos_malvernetv_page1.json",
    _v2_url("malvernetv", 2): "v2_videos_malvernetv_page2.json",
    _v2_url("malvernetv", 3): "v2_videos_malvernetv_page3.json",
    "https://vimeo.com/malvernetv/videos/rss": "rss_malvernetv.xml",
}


@pytest.fixture
def routed_fetch(monkeypatch):
    """Route `VimeoAssetFinder._fetch` to real fixtures by exact URL. An
    unrouted URL answers like a failed fetch (None) -- the same thing the
    real `_fetch()` returns for any non-200. Every requested URL is
    recorded, so a test can check how many requests were made."""
    calls = []

    def install(routes):
        async def _fake_fetch(url, referer=None):
            calls.append(url)
            name = routes.get(url)
            if name is None:
                return None
            return load_fixture("vimeo", name)

        monkeypatch.setattr(vimeo.VimeoAssetFinder, "_fetch", staticmethod(_fake_fetch))
        return calls

    return install


# --- Parsers ---------------------------------------------------------


def test_v2_page_parses_to_newest_first_candidates():
    rows = parse_v2_videos_json(
        load_fixture("vimeo", "v2_videos_malvernetv_page1.json")
    )
    assert len(rows) == 20
    assert rows[2] == {
        "title": "Village of Malverne - Meeting of the Board of Trustees - September 2, 2026",
        "date": "2026-09-02",
        "url": "https://vimeo.com/1223529996",
    }
    # A title with no date shape falls back to Vimeo's upload date.
    assert rows[13]["title"] == "Girl Scout Government Day 2026"
    assert rows[13]["date"] == "2026-03-07"


def test_v2_forbidden_page_and_human_check_page_read_as_nothing():
    assert (
        parse_v2_videos_json(
            load_fixture("vimeo", "v2_videos_malvernetv_page4_forbidden.html")
        )
        is None
    )
    assert (
        parse_v2_videos_json(
            load_fixture("vimeo", "video_page_391007677_human_check.html")
        )
        is None
    )
    assert parse_v2_videos_json(None) is None


def test_rss_keeps_each_videos_privacy_hash():
    rows = parse_user_rss(load_fixture("vimeo", "rss_malvernetv.xml"))
    assert len(rows) == 10
    assert rows[2] == {
        "title": "Village of Malverne - Meeting of the Board of Trustees - September 2, 2026",
        "date": "2026-09-02",
        "url": "https://vimeo.com/1223529996/e345d0687d",
    }


def test_rss_parser_reads_a_human_check_page_as_nothing():
    assert (
        parse_user_rss(load_fixture("vimeo", "video_page_391007677_human_check.html"))
        is None
    )


@pytest.mark.parametrize(
    "author_url,expected",
    [
        ("https://vimeo.com/malvernetv", "malvernetv"),
        ("https://vimeo.com/user142310876", "user142310876"),
        ("https://vimeo.com/ncf/", "ncf"),
        (None, None),
        ("", None),
        ("https://vimeo.com/channels/coscouncil", None),
        ("https://vimeo.com/showcase", None),
        ("https://example.com/malvernetv", None),
    ],
)
def test_owner_slug_from_author_url(author_url, expected):
    assert owner_slug_from_author_url(author_url) == expected


# --- list_owner_videos() ----------------------------------------------


async def test_malverne_weak_video_lists_its_village_account(routed_fetch):
    calls = routed_fetch(MALVERNE_ROUTES)
    result = await list_owner_videos("https://player.vimeo.com/video/168650512")
    assert result.owner_slug == "malvernetv"
    assert result.owner_name == "MalverneTV"
    assert result.video_title == "Memorial Day - 2016"
    assert result.video_date == "2016-05-30"
    assert result.source == LISTER_V2_API
    assert result.pages_read == 3
    assert len(result.candidates) == 60
    # oEmbed + three API pages; page 4 (a real 403) is never asked for.
    assert len(calls) == 4
    assert _v2_url("malvernetv", 4) not in calls


async def test_enough_stops_paging_early(routed_fetch):
    calls = routed_fetch(MALVERNE_ROUTES)
    result = await list_owner_videos(
        "https://vimeo.com/168650512", enough=lambda rows: len(rows) >= 20
    )
    assert result.pages_read == 1
    assert len(result.candidates) == 20
    assert len(calls) == 2


async def test_short_page_is_the_end_of_the_account(routed_fetch):
    calls = routed_fetch(
        {
            _oembed_url("575538718"): "oembed_clinton_575538718.json",
            _v2_url("user142310876", 1): "v2_videos_user142310876.json",
        }
    )
    result = await list_owner_videos("https://player.vimeo.com/video/575538718")
    assert result.owner_slug == "user142310876"
    assert result.owner_name == "keith stidham"
    assert len(result.candidates) == 14
    assert len(calls) == 2


async def test_api_failure_falls_back_to_rss(routed_fetch):
    routes = {
        _oembed_url("168650512"): "oembed_malverne_168650512.json",
        _v2_url("malvernetv", 1): "v2_videos_malvernetv_page4_forbidden.html",
        "https://vimeo.com/malvernetv/videos/rss": "rss_malvernetv.xml",
    }
    routed_fetch(routes)
    result = await list_owner_videos("https://player.vimeo.com/video/168650512")
    assert result.source == LISTER_RSS
    assert len(result.candidates) == 10


async def test_hidden_owner_lists_nothing_and_says_why(routed_fetch):
    calls = routed_fetch(
        {_oembed_url("391007677"): "oembed_tarentum_391007677_no_owner.json"}
    )
    result = await list_owner_videos("https://player.vimeo.com/video/391007677")
    assert result.owner_slug is None
    assert result.candidates == []
    assert "names no owner" in result.note
    assert len(calls) == 1  # no guessing at an owner, no other request


async def test_not_a_video_link_makes_no_request(routed_fetch):
    calls = routed_fetch({})
    result = await list_owner_videos("https://vimeo.com/showcase/11598114")
    assert result.candidates == []
    assert calls == []


# --- Meeting Finder: Identify and List ---------------------------------


class _NoFetch:
    """A Fetcher stand-in that fails the test if anything fetches through
    it -- Identify's rule 1 and the Vimeo owner lister need no page fetch."""

    async def fetch(self, *args, **kwargs):  # pragma: no cover -- must not run
        raise AssertionError("no page fetch expected")


@pytest.mark.parametrize(
    "url",
    [
        "https://player.vimeo.com/video/168650512",
        "https://vimeo.com/575516842",
        "https://vimeo.com/1152708575/db9859a2aa",
    ],
)
async def test_identify_keeps_a_vimeo_video_link_as_the_account(url):
    result = await identify_mod.identify(url, _NoFetch())
    assert result.platform == "vimeo"
    assert result.account_url == url


async def test_identify_keeps_a_vimeo_showcase_link_as_the_account():
    url = "https://vimeo.com/showcase/11598114/embed"
    result = await identify_mod.identify(url, _NoFetch())
    assert result.account_url == url


async def test_list_account_puts_meetings_first_and_keeps_the_weak_video(routed_fetch):
    routed_fetch(MALVERNE_ROUTES)
    result = await listing.list_account(
        "vimeo", "https://player.vimeo.com/video/168650512", _NoFetch(), limit=15
    )
    assert result.lister == LISTER_V2_API
    assert len(result.candidates) == 15
    titles = [c.title for c in result.candidates]
    assert titles[0] == (
        "Village of Malverne - Meeting of the Board of Trustees - September 2, 2026"
    )
    assert all("Meeting" in t or "Hearing" in t for t in titles[:14])
    # The weak input video is never dropped: it is kept, with its own
    # oEmbed title and date, right after the meetings.
    last = result.candidates[-1]
    assert last.url == "https://player.vimeo.com/video/168650512"
    assert (last.title, last.date) == ("Memorial Day - 2016", "2016-05-30")
    assert all(c.has_video_hint for c in result.candidates)
    assert all(c.platform == "vimeo" for c in result.candidates)
    assert "owner malvernetv" in result.note
    assert "21 of 60 title(s) look like a meeting" in result.note


async def test_list_account_on_an_account_with_no_meetings(routed_fetch):
    routed_fetch(
        {
            _oembed_url("575538718"): "oembed_clinton_575538718.json",
            _v2_url("user142310876", 1): "v2_videos_user142310876.json",
        }
    )
    result = await listing.list_account(
        "vimeo", "https://player.vimeo.com/video/575538718", _NoFetch()
    )
    assert "0 of 14 title(s) look like a meeting" in result.note
    # No meeting titles: the input video leads, the rest follow in the
    # account's own order. Nothing is dropped up to the limit.
    assert result.candidates[0].url == "https://vimeo.com/575538718"
    assert len(result.candidates) == 14


async def test_list_account_keeps_the_input_video_when_the_owner_is_hidden(
    routed_fetch,
):
    routed_fetch({_oembed_url("391007677"): "oembed_tarentum_391007677_no_owner.json"})
    result = await listing.list_account(
        "vimeo", "https://player.vimeo.com/video/391007677", _NoFetch()
    )
    assert [c.url for c in result.candidates] == [
        "https://player.vimeo.com/video/391007677"
    ]
    assert result.outcome is None
    assert "names no owner" in result.note


async def test_list_account_still_reads_a_showcase_through_its_own_lister(monkeypatch):
    """A showcase link is a listing on its own -- the owner lister steps
    aside and lister (c) answers, as before."""

    async def _fake_listing(cls, url):
        return [
            {
                "title": "City Council 1/2/2026",
                "date": "2026-01-02",
                "url": "https://vimeo.com/1",
            }
        ]

    async def _no_discovery(*args, **kwargs):
        return None

    monkeypatch.setattr(
        vimeo.VimeoAssetFinder, "_listing_candidates", classmethod(_fake_listing)
    )
    monkeypatch.setattr(listing, "_list_via_discovery", _no_discovery)
    from app.platforms import register_all_finders

    register_all_finders()
    result = await listing.list_account(
        "vimeo", "https://vimeo.com/showcase/11598114", _NoFetch()
    )
    assert result.lister == "adapter_list"


# --- Verdict keeps the list ---------------------------------------------


def test_verdict_row_carries_the_list_and_csv_counts_it(tmp_path):
    entry = {
        "platform": "vimeo",
        "account_url": "https://player.vimeo.com/video/168650512",
        "lister": LISTER_V2_API,
        "outcome": None,
        "note": "owner malvernetv",
        "candidates": [
            {"url": "https://vimeo.com/1223529996", "title": "t", "date": "2026-09-02"}
        ],
    }
    row = VerdictRow(
        run_id="r",
        input_url="https://player.vimeo.com/video/168650512",
        entry_phase="identify",
        listed=[entry],
    )
    csv_path = tmp_path / "v.csv"
    append_verdict(csv_path, row)
    assert "listed_count" in csv_path.read_text().splitlines()[0]
    assert csv_path.read_text().splitlines()[1].split(",")[-2] == "1"
    jsonl = (tmp_path / "v.csv.jsonl").read_text()
    assert (
        '"listed": [{"account_url": "https://player.vimeo.com/video/168650512"' in jsonl
    )


async def test_runner_records_each_listed_account_once(monkeypatch):
    from app.platforms.meeting_finder import runner

    calls = []

    async def _fake_list_account(platform, account_url, fetcher, **kwargs):
        calls.append(account_url)
        return listing.ListResult(
            candidates=[], lister=LISTER_V2_API, outcome=None, note="n"
        )

    monkeypatch.setattr(runner, "list_account", _fake_list_account)
    state = runner._WalkState()
    for _ in range(2):
        await runner._cached_list_account(
            "vimeo", "https://vimeo.com/1", SimpleNamespace(), state
        )
    assert len(calls) == 1
    assert state.listed == [
        {
            "platform": "vimeo",
            "account_url": "https://vimeo.com/1",
            "lister": LISTER_V2_API,
            "outcome": None,
            "note": "n",
            "candidates": [],
        }
    ]
