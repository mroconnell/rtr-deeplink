"""Meeting Finder hops for school districts (Ryan, 2026-09-30).

School sites say "Board" / "Board Meetings" / "Meeting Recordings", not
"Government". `rank_hops(school=True)` has a school vocabulary; the
runner must pass it for every `us:sd:` input. The page below is a
synthetic nav shaped after three real sites Ryan hand-reviewed
(asdk12.org /school-board/board-meetings, svusd.org /board/
meeting-recordings, wccusd.net /fs/pages/14775); it is a small nav-only
page, not a captured payload.
"""

from __future__ import annotations

import ast
import pathlib

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import rank_hops

BASE = "https://www.exampleusd.org/"

HTML = """
<html><body>
<header><nav><ul>
<li><a href="/about-us">About Us</a></li>
<li><a href="/news">News</a></li>
<li><a href="/fs/pages/14775">Board of Education</a></li>
<li><a href="/school-board/board-meetings">Board Meetings</a></li>
<li><a href="/board/meeting-recordings">Meeting Recordings</a></li>
<li><a href="/fs/pages/20001">Agendas &amp; Minutes</a></li>
<li><a href="/fs/pages/20002">Watch meetings online</a></li>
<li><a href="/fs/pages/20003">Livestream</a></li>
<li><a href="/parents/lunch-menus">Lunch Menus</a></li>
<li><a href="/departments/transportation">Transportation</a></li>
</ul></nav></header></body></html>
"""

SCHOOL_TARGETS = {
    "/fs/pages/14775",
    "/school-board/board-meetings",
    "/board/meeting-recordings",
    "/fs/pages/20001",
    "/fs/pages/20002",
    "/fs/pages/20003",
}


def _page() -> FetchResult:
    return FetchResult(
        requested_url=BASE,
        final_url=BASE,
        status=200,
        html=HTML,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )


def _paths(hops):
    return [h.url.replace("https://www.exampleusd.org", "") for h in hops]


def test_school_true_ranks_board_and_recording_links_first():
    hops = rank_hops(_page(), school=True, limit=20)
    top = set(_paths(hops)[: len(SCHOOL_TARGETS)])
    assert top == SCHOOL_TARGETS, _paths(hops)
    # Generic links are never above a school nav link.
    ordered = _paths(hops)
    for generic in ("/about-us", "/news", "/parents/lunch-menus"):
        if generic in ordered:
            assert ordered.index(generic) >= len(SCHOOL_TARGETS)


def test_school_false_does_not_rescue_finalsite_anchor_only_links():
    # City vocabulary: the anchor-only Finalsite links (opaque /fs/pages/
    # paths) are not boosted the way school=True boosts them.
    plain = {h.url: h.score for h in rank_hops(_page(), limit=20)}
    school = {h.url: h.score for h in rank_hops(_page(), school=True, limit=20)}
    u = BASE + "fs/pages/20002"
    assert school[u] > plain.get(u, float("-inf"))


def test_runner_is_school_input():
    f = runner.FinderInput
    assert runner._is_school_input(
        f(url="https://x.org", entry="resolve", gov_id="us:sd:0601234")
    )
    assert not runner._is_school_input(
        f(url="https://x.gov", entry="resolve", gov_id="us:mu:123")
    )
    assert not runner._is_school_input(f(url="https://x.gov", entry="resolve"))


def test_every_runner_rank_hops_call_passes_school():
    src = pathlib.Path(runner.__file__).read_text()
    calls = [
        n
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "rank_hops"
    ]
    assert len(calls) >= 5
    for c in calls:
        assert any(k.arg == "school" for k in c.keywords), ast.get_source_segment(
            src, c
        )
