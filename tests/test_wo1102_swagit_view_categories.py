"""WO-1102: a Swagit view page that is only an index of category pages.

Why (2026-09-26): some `/views/{n}/` pages hold no meetings of their own.
Their tabs link category sub-pages, `/views/{n}/{slug}`, that do. San
Benito, TX is the worked example: `/views/322/` has no table rows, and
links `/views/322/commission-meetings` (the meetings) and `/views/322/live`
(the live stream). The lister read only the index page, so it found none.

Both fixtures are real captures of San Benito's pages, 2026-09-26,
trimmed (see the comment inside each). Dublin, CA's `dublin_views_876.html`
(WO-1081) is the control: a view page with its own rows.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.platforms.meeting_finder import listing
from app.platforms.meeting_finder.fetch import BudgetExceeded, Fetcher, FetchResult

FIXTURES = Path(__file__).parent / "fixtures" / "swagit"
INDEX = (FIXTURES / "sanbenito_views_322_index.html").read_text()
CATEGORY = (FIXTURES / "sanbenito_views_322_commission_meetings.html").read_text()
DUBLIN_VIEW = (FIXTURES / "dublin_views_876.html").read_text()
SAN_BENITO = "https://sanbenitotx.new.swagit.com"


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


def _fake_site(pages: dict[str, str], requested: list[str]):
    async def fake_fetch(url: str, *, need_links: bool = True):
        requested.append(url)
        if url not in pages:  # pragma: no cover
            raise AssertionError(f"unexpected fetch: {url}")
        return _page(url, pages[url])

    return fake_fetch


def test_the_index_page_links_one_meeting_category_and_skips_live():
    assert listing._swagit_view_category_urls(INDEX, f"{SAN_BENITO}/views/322/") == [
        f"{SAN_BENITO}/views/322/commission-meetings"
    ]


async def test_an_index_view_leads_to_its_category_pages_meetings(fetcher):
    requested: list[str] = []
    pages = {
        f"{SAN_BENITO}/views/322/": INDEX,
        f"{SAN_BENITO}/views/322/commission-meetings": CATEGORY,
    }
    with patch.object(fetcher, "fetch", side_effect=_fake_site(pages, requested)):
        result = await listing._list_via_swagit_views_page(
            "swagit", f"{SAN_BENITO}/views/322/", fetcher, 20
        )

    # `live` is never fetched.
    assert requested == list(pages)
    assert result.lister == "swagit_views_page"
    assert [(c.url, c.title, c.date) for c in result.candidates] == [
        (f"{SAN_BENITO}/videos/401170", "Commission Meetings", "2026-09-15"),
        (f"{SAN_BENITO}/videos/399675", "Commission Meetings", "2026-09-01"),
        (f"{SAN_BENITO}/videos/396629", "Commission Meetings", "2026-08-18"),
    ]
    assert all(
        c.source_url == f"{SAN_BENITO}/views/322/commission-meetings"
        for c in result.candidates
    )


async def test_the_category_pages_respect_the_limit(fetcher):
    requested: list[str] = []
    pages = {
        f"{SAN_BENITO}/views/322/": INDEX,
        f"{SAN_BENITO}/views/322/commission-meetings": CATEGORY,
    }
    with patch.object(fetcher, "fetch", side_effect=_fake_site(pages, requested)):
        result = await listing._list_via_swagit_views_page(
            "swagit", f"{SAN_BENITO}/views/322/", fetcher, 2
        )

    assert len(result.candidates) == 2


async def test_a_view_with_its_own_rows_does_not_fetch_categories(fetcher):
    # Dublin's real view page has rows; add a category link to it so the
    # test proves the lister chose not to follow it.
    url = "https://dublinca.new.swagit.com/views/876/"
    html = DUBLIN_VIEW + '<a href="/views/876/city-council">City Council</a>'
    requested: list[str] = []
    with patch.object(fetcher, "fetch", side_effect=_fake_site({url: html}, requested)):
        result = await listing._list_via_swagit_views_page("swagit", url, fetcher, 20)

    assert requested == [url]
    assert len(result.candidates) == 3


async def test_a_spent_budget_stops_before_the_category_page(fetcher):
    requested: list[str] = []

    async def fake_fetch(url: str, *, need_links: bool = True):
        requested.append(url)
        if url.endswith("/views/322/"):
            return _page(url, INDEX)
        raise BudgetExceeded("fetch budget of 1 used")

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing._list_via_swagit_views_page(
            "swagit", f"{SAN_BENITO}/views/322/", fetcher, 20
        )

    assert result.candidates == []
    assert "budget" in result.note
