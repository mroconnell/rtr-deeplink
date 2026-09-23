"""WO-1029: Meeting Finder's Hop phase (`app/platforms/meeting_finder/
hop.py`).

`rank_hops()`/`is_document_hub()`/`calendar_entry_links()` are thin
wrappers around `scripts/wo147_access_ladder_sweep.py`'s already-tested
`find_hop_links()`/`looks_like_document_hub()`/`find_calendar_entry_
links()` (see `hop.py`'s own module docstring for why they're reused
directly rather than moved). This file's job is narrower than
`tests/test_hop_scorer_weighted.py`/`tests/test_hub_link_ranking.py`,
which already cover the underlying scorer in depth: it checks the
wrapper's own contract (a `FetchResult` in, `HopLink` objects with a
real score/anchor/reason out) and the one piece of NEW behavior this WO
adds -- `prefer_vendor`.

Real fixtures reused from `tests/fixtures/wo228_hub_ranking/` (fetched
live 2026-09-11 -- see that directory's own test file for exact
sources), not re-saved. The `prefer_vendor` boost itself is exercised
against a small synthetic page (documented as such below) built from two
already-real, already-measured vendor-host shapes (`*.legistar.com`,
`*.iqm2.com` -- both appear in `is_vendor_href_host()`/real fixtures
elsewhere in this suite) rather than an invented shape, per CLAUDE.md's
synthetic-test rule: it exercises one already-confirmed branch
(`detect_platform()` matching a specific vendor host), not a new,
unverified payload shape.
"""

from __future__ import annotations

import os

from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import (
    HopLink,
    calendar_entry_links,
    is_document_hub,
    rank_hops,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo228_hub_ranking")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def _page(html: str, url: str, *, links_only: bool = False) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=links_only,
        elapsed_ms=0,
    )


# --- Wrapper contract -------------------------------------------------


def test_rank_hops_returns_hoplinks_matching_find_hop_links_top_pick():
    """Real regression fixture (`tests/test_hop_scorer_weighted.py`'s own
    `test_cleveland_county_ranks_legistar_link_above_a_press_release`):
    the real legistar.com link belongs in the top 3 and a CivicAlerts
    press release must not outrank it. `rank_hops()` must preserve that
    ordering -- it's a thin wrapper, not a second scorer."""
    html = _load("cleveland_county_legistar_home.html")
    page = _page(html, "https://clevelandcountyok.com/")
    hops = rank_hops(page, limit=3)
    assert hops, "expected at least one ranked hop"
    assert all(isinstance(h, HopLink) for h in hops)
    urls = [h.url for h in hops]
    assert any("legistar.com" in u for u in urls), urls
    assert not any("civicalerts" in u.lower() for u in urls), urls
    # Scores are sorted best-first and each has a non-empty reason.
    scores = [h.score for h in hops]
    assert scores == sorted(scores, reverse=True)
    assert all(h.reason for h in hops)
    legistar_hop = next(h for h in hops if "legistar.com" in h.url)
    assert "vendor-host link" in legistar_hop.reason


def test_rank_hops_empty_for_a_page_with_no_html():
    page = FetchResult(
        requested_url="https://example.gov/",
        final_url="https://example.gov/",
        status=None,
        html=None,
        access_mode="dead",
        outcome="dns-unresolvable",
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )
    assert rank_hops(page) == []


def test_rank_hops_respects_limit():
    html = _load("madison_county_tn_home.html")
    page = _page(html, "https://madisoncountytn.gov/")
    hops = rank_hops(page, limit=2)
    assert len(hops) <= 2


# --- prefer_vendor (new in WO-1029) ------------------------------------


# Synthetic, documented: two vendor-shaped links, both real recognized
# vendor hosts (legistar.com and iqm2.com, both listed in
# wo147_access_ladder_sweep.py's own `is_vendor_href_host()`), with the
# SAME anchor text so the only vocabulary difference is each link's own
# path -- `find_hop_links()`'s own scorer ranks the legistar link higher
# on plain path vocabulary (confirmed below), so a `prefer_vendor="iqm2"`
# flip to the iqm2 link is real evidence of the added bonus, not a tie
# that could go either way anyway.
_TWO_VENDOR_LINKS_HTML = """
<html><body>
<nav>
<a href="https://cityx.legistar.com/Calendar.aspx">Meetings and Agendas</a>
<a href="https://cityx.iqm2.com/Citizens/Default.aspx">Meetings and Agendas</a>
</nav>
</body></html>
"""


def test_prefer_vendor_boosts_the_matching_vendor_link_above_an_equal_one():
    page = _page(_TWO_VENDOR_LINKS_HTML, "https://cityx.gov/")

    plain = rank_hops(page, limit=2)
    assert len(plain) == 2
    # With no preference, legistar's own path vocabulary ("calendar")
    # already outscores iqm2's ("citizens/default").
    assert plain[0].url == "https://cityx.legistar.com/Calendar.aspx"
    assert plain[0].score > plain[1].score

    preferred = rank_hops(page, prefer_vendor="iqm2", limit=2)
    assert preferred[0].url == "https://cityx.iqm2.com/Citizens/Default.aspx"
    assert preferred[0].score > preferred[1].score
    assert "preferred vendor" in preferred[0].reason


def test_prefer_vendor_no_effect_when_that_vendor_is_not_on_the_page():
    page = _page(_TWO_VENDOR_LINKS_HTML, "https://cityx.gov/")
    without = [h.url for h in rank_hops(page, limit=2)]
    with_absent_pref = [
        h.url for h in rank_hops(page, prefer_vendor="granicus", limit=2)
    ]
    assert without == with_absent_pref


# --- is_document_hub / calendar_entry_links ----------------------------


def test_is_document_hub_true_for_a_real_agendacenter_page():
    html = _load("south_congaree_civicplus_home.html")
    page = _page(html, "https://www.townofsouthcongaree.org")
    assert is_document_hub(page) is True


def test_is_document_hub_false_with_no_html():
    page = FetchResult(
        requested_url="https://example.gov/",
        final_url="https://example.gov/",
        status=None,
        html=None,
        access_mode="dead",
        outcome="timeout",
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )
    assert is_document_hub(page) is False


def test_calendar_entry_links_real_madison_county_tn_fixture():
    """Same real fixture/assertions as `tests/test_hub_link_ranking.py`'s
    `test_find_calendar_entry_links_real_madison_county_tn_fixture` --
    confirms the wrapper didn't change the underlying behavior."""
    html = _load("madison_county_tn_home.html")
    page = _page(html, "https://madisoncountytn.gov/")
    entries = calendar_entry_links(page, limit=2)
    assert len(entries) == 2
    assert all("EID=" in e for e in entries)


def test_calendar_entry_links_empty_with_no_html():
    page = FetchResult(
        requested_url="https://example.gov/",
        final_url="https://example.gov/",
        status=None,
        html=None,
        access_mode="dead",
        outcome="timeout",
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )
    assert calendar_entry_links(page) == []
