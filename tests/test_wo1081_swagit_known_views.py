"""WO-1081: known Swagit `/views/{id}` pages (`swagit_views.csv`), and dates
on a view page.

Why (2026-09-26): a Swagit tenant's tab pages are empty shells (WO-1036),
so only a numbered view page lists its meetings. Dublin, CA is the worked
example: its own "Watch Meetings" page embeds
`dublinca.new.swagit.com/views/876/`, which lists 17 City Council
meetings. That page puts each date in its own column, which
`_parse_swagit_video_table` never read, so all 17 came back undated. The
older WO-1028 test used a synthetic row with the date under the title, so
it could not catch this.

`tests/fixtures/swagit/dublin_views_876.html` is a real capture of that
page, 2026-09-26, trimmed to the table header and 3 rows (see the comment
inside it).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.platforms.meeting_finder import listing
from app.platforms.meeting_finder.fetch import Fetcher, FetchResult
from app.platforms.swagit import (
    SWAGIT_VIEWS_FILE,
    known_view_for,
    known_views,
    known_views_for,
)

FIXTURE = Path(__file__).parent / "fixtures" / "swagit" / "dublin_views_876.html"
DUBLIN = "dublinca.new.swagit.com"


@pytest.fixture
def fetcher():
    return Fetcher(max_fetches=12, allow_headless=False, allow_wayback=False)


def _page(url: str, html: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )


def test_a_real_view_page_row_keeps_its_date():
    candidates = listing._parse_swagit_video_table(
        FIXTURE.read_text(), f"https://{DUBLIN}/views/876/"
    )
    assert [(c.url, c.title, c.date) for c in candidates] == [
        (f"https://{DUBLIN}/videos/401121", "City Council", "2026-09-15"),
        (f"https://{DUBLIN}/videos/399711", "City Council", "2026-09-01"),
        (f"https://{DUBLIN}/videos/396611", "City Council", "2026-08-18"),
    ]


def test_the_known_views_file_is_well_formed():
    # WO-1087: every row is owner-proven (rtr-discovery's 2026-09-26 owner
    # sweep); a tenant may have several views, one row each.
    with SWAGIT_VIEWS_FILE.open(newline="") as f:
        rows = list(csv.DictReader(f))
    pairs = [(r["tenant_host"], r["views_id"]) for r in rows]
    assert len(pairs) == len(set(pairs)), "one row per tenant and view"
    views = [r["views_id"] for r in rows]
    assert len(views) == len(set(views)), "a view belongs to one tenant"
    for r in rows:
        assert r["tenant_host"].endswith(".swagit.com")
        assert re.fullmatch(r"\d+", r["views_id"])
        assert r["source_url"] == f"https://{r['tenant_host']}/views/{r['views_id']}"
        assert r["found_in"] and r["evidence"]
    assert known_views()[DUBLIN] == ["876"]


def test_the_three_wrong_views_are_filed_under_their_real_owners():
    # WO-1087: WO-1081 filed these under the wrong tenant. The owner sweep
    # read two video pages from each view; both named the real owner, and
    # Ryan confirmed in a browser (2026-09-26).
    assert known_views_for("austintx.new.swagit.com") == ["794"]
    assert known_views_for("ferndalesd.new.swagit.com") == ["312"]
    assert known_views_for("idahofallsid.new.swagit.com") == ["169"]
    assert "5" in known_views_for("dentontx.new.swagit.com")
    assert known_views_for("hamiltonseschoolsin.new.swagit.com") == ["44"]
    assert known_views_for("murphytx.new.swagit.com") == ["170"]


def test_a_bare_swagit_host_finds_its_new_swagit_row():
    # A bare *.swagit.com host redirects to *.new.swagit.com (WO-1036).
    assert known_view_for("dublinca.swagit.com") == "876"
    assert known_view_for("DublinCA.new.swagit.com") == "876"
    assert known_view_for("nowhere.new.swagit.com") is None


async def test_a_bare_tenant_url_lists_its_known_view_page(fetcher):
    requested: list[str] = []

    async def fake_fetch(url: str, *, need_links: bool = True):
        requested.append(url)
        return _page(url, FIXTURE.read_text())

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing._list_via_swagit_views_page(
            "swagit", f"https://{DUBLIN}/", fetcher, 20
        )

    assert requested == [f"https://{DUBLIN}/views/876/"]
    assert result.lister == "swagit_views_page"
    assert [c.date for c in result.candidates] == [
        "2026-09-15",
        "2026-09-01",
        "2026-08-18",
    ]


async def test_a_bare_tenant_url_with_no_known_view_is_left_to_other_listers(
    fetcher,
):
    async def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("no known view: nothing to fetch here")

    with patch.object(fetcher, "fetch", side_effect=fail_if_called):
        result = await listing._list_via_swagit_views_page(
            "swagit", "https://nowhere.new.swagit.com/", fetcher, 20
        )

    assert result is None


async def test_a_tenant_with_several_views_lists_all_of_them(fetcher, monkeypatch):
    # WO-1087: 48 tenants have more than one view (one per channel or set
    # of bodies). Each is fetched and their meetings are combined.
    monkeypatch.setattr(listing, "known_views_for", lambda host: ["876", "999"])
    requested: list[str] = []

    async def fake_fetch(url: str, *, need_links: bool = True):
        requested.append(url)
        return _page(url, FIXTURE.read_text())

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing._list_via_swagit_views_page(
            "swagit", f"https://{DUBLIN}/", fetcher, 20
        )

    assert requested == [f"https://{DUBLIN}/views/876/", f"https://{DUBLIN}/views/999/"]
    assert len(result.candidates) == 6
