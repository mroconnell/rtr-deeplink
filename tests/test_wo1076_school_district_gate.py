"""WO-1076 addendum (Ryan, 2026-09-25): the video quality gate
(`app/utils/video_hand_check.py`'s `classify_video_hand_check()`, called
from `assess_video_candidate()`) rejects a "school board"/"board of
education"/"school committee" title outright, on the theory that it
always names a DIFFERENT government's board. A hand-check of calibration
set D's weak leads found that's wrong when the government being SEARCHED
is itself a school district -- these are real, confirmed false
positives:

    Glendale USD (gusd.net), Nassau County SD (nassau.k12.fl.us), Prince
    George County Public Schools (pgs.k12.va.us), South Windsor SD,
    Baltimore County PS (bcps.org), Calvert County PS, Midland PS
    (midlandps.org), Falmouth Schools ME, South Pasadena USD (spusd.net),
    Lake Oswego SD (losdschools.org)

-- each one's own real board/committee meeting, rejected because its
title said "school board"/"board of education"/"school committee". The
SAME rejection is right when the searched government is a town/city and
the video is some OTHER district's board (Coventry CT, Springfield MA,
Sanford ME, Windsor CT all got their own school district's board this
way -- real names, government kind is what should gate this, not a
guess at whether the title "sounds like" the right body).

Titles below are SYNTHETIC (a school board's real meeting title isn't in
this repo), built in the exact shape `_HAND_CHECK_KIND_A_PHRASES` already
matches against ("school board"/"board of education"/"school committee"
literally in the title) -- the fact under test is the real government
kind (school district vs. town/city), not the title wording, which is
already covered by `tests/test_video_gate_wo933.py`."""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import resolve as resolve_mod
from app.platforms.meeting_finder.models import Candidate, FinderInput
from app.platforms.meeting_finder.resolve import resolve_candidates
from app.platforms.models import ResolvedMeeting
from app.utils.gov_registry.registry import Government
from app.utils.video_hand_check import classify_video_hand_check


def _finder_input(url: str, **overrides) -> FinderInput:
    fields = dict(url=url, gov_id=None, mode="pin", entry="resolve")
    fields.update(overrides)
    return FinderInput(**fields)


# --- Direct unit tests: `classify_video_hand_check()` --------------------


@pytest.mark.parametrize(
    "title",
    [
        "School Board Meeting - March 3, 2026",
        "Board of Education Regular Meeting",
        "School Committee Meeting 3/3/26",
    ],
)
def test_school_district_own_board_meeting_is_not_flagged(title):
    assert (
        classify_video_hand_check(title, None, "Glendale USD", "school_district")
        is None
    )


@pytest.mark.parametrize(
    "title",
    [
        "School Board Meeting - March 3, 2026",
        "Board of Education Regular Meeting",
    ],
)
@pytest.mark.parametrize("gov_kind", ["city", "town", "county", None, ""])
def test_a_towns_video_of_a_school_boards_meeting_is_still_flagged(title, gov_kind):
    """Real Coventry CT / Springfield MA / Sanford ME / Windsor CT shape:
    the searched government is a town/city, and the video is its school
    district's board -- still the wrong body for THIS government."""
    hit = classify_video_hand_check(title, None, "Coventry", gov_kind)
    assert hit is not None
    assert hit[0] == "A"


@pytest.mark.parametrize(
    "spelling", ["school_district", "school district", "SD", "sd", " School_District "]
)
def test_gov_kind_school_district_spelling_is_normalized(spelling):
    assert (
        classify_video_hand_check("School Board Meeting", None, "X", spelling) is None
    )


def test_other_kind_a_phrases_are_unaffected_by_school_district_gov_kind():
    """Only the three school-board-shaped phrases are gov_kind-aware --
    a county assessor's/state DOT's/court's own video is never THIS
    government's meeting, whatever kind of government is being searched."""
    hit = classify_video_hand_check(
        "County Assessor's Office Update",
        None,
        "Some School District",
        "school_district",
    )
    assert hit is not None
    assert hit[0] == "A"


# --- Integration: resolve.py's own wiring (`_government_for_input()`) ---


def _school_board_meeting(url: str) -> ResolvedMeeting:
    return ResolvedMeeting(
        platform="civicclerk",
        source_url=url,
        jurisdiction="Glendale, CA",
        title="School Board Meeting - March 3, 2026",
        video_url=f"{url}.mp4",
        segments=[{"start": 0, "end": 1, "text": "hello"}],
    )


@pytest.mark.asyncio
async def test_resolve_passes_a_school_districts_own_board_meeting(monkeypatch):
    async def fake_resolve_via_platform(url, *, allow_youtube=True):
        return _school_board_meeting(url)

    def fake_government_for_id(gov_id):
        assert gov_id == "us:sd:0629820"
        return Government(
            gov_id="us:sd:0629820",
            gov_name="Glendale Unified School District",
            gov_type="school_district",
            state="CA",
        )

    monkeypatch.setattr(resolve_mod, "resolve_via_platform", fake_resolve_via_platform)
    monkeypatch.setattr(resolve_mod, "government_for_id", fake_government_for_id)
    resolve_mod._GOV_CACHE.clear()

    candidates = [
        Candidate(
            url="https://glendaleusd.civicclerk.com/event/1/media",
            date="2026-03-03",
            title="School Board Meeting - March 3, 2026",
        )
    ]
    result = await resolve_candidates(
        candidates, _finder_input(candidates[0].url, gov_id="us:sd:0629820")
    )

    assert result.outcome is None
    assert result.video_url == f"{candidates[0].url}.mp4"


@pytest.mark.asyncio
async def test_resolve_still_flags_a_school_boards_meeting_for_a_town(monkeypatch):
    """Same real video, but the government being searched is a town, not
    the school district it names -- the gate should still reject it (kept
    only as a low-confidence fallback, never a clean find)."""

    async def fake_resolve_via_platform(url, *, allow_youtube=True):
        return _school_board_meeting(url)

    def fake_government_for_id(gov_id):
        assert gov_id == "us:place:0715540"
        return Government(
            gov_id="us:place:0715540",
            gov_name="Coventry",
            gov_type="city",
            state="CT",
        )

    monkeypatch.setattr(resolve_mod, "resolve_via_platform", fake_resolve_via_platform)
    monkeypatch.setattr(resolve_mod, "government_for_id", fake_government_for_id)
    resolve_mod._GOV_CACHE.clear()

    candidates = [
        Candidate(
            url="https://coventryct.civicclerk.com/event/1/media",
            date="2026-03-03",
            title="School Board Meeting - March 3, 2026",
        )
    ]
    result = await resolve_candidates(
        candidates, _finder_input(candidates[0].url, gov_id="us:place:0715540")
    )

    assert result.outcome is not None
    assert "hand_check_kind_a" in (result.note or "")
