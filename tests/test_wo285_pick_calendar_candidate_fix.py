"""WO-285 (2026-09-12): every copy of `pick_calendar_candidate()`'s
ambiguous-candidate error message built `dated` as a list of
`(datetime, candidate_dict)` tuples, then did
`[c.get("title") for c in (dated[:5] or candidates[:5])]` in its own
"no clean recent candidate" fallback line -- when `dated` is non-empty,
`c` there is the TUPLE, not the dict, so `.get()` raised
`AttributeError: 'tuple' object has no attribute 'get'`. Hit live by
WO-276 (2026-09-12) on the very first government whose candidate list
was genuinely ambiguous, crashing the whole sweep.

`scripts/nationwide_2404_ingest.py`'s own copy was already fixed
(confirmed by reading it: `[c.get("title") for _, c in dated[:5]] or
[c.get("title") for c in candidates[:5]]`). This test applies the
identical one-line fix to the four other copies BACKLOG.md named --
`scripts/nationwide_1911_ingest.py`, `scripts/nationwide_395_ingest.py`,
`scripts/nationwide_431_ingest.py`, `scripts/wo130_county_ingest.py` --
and confirms all five now behave identically on the real ambiguous shape
this bug needs to reproduce: at least one candidate with a real,
parseable past date (populating `dated`), none of which pass
`_looks_like_real_meeting()` (a real PROMO_BLOCKLIST title word), and
more than one candidate total (so the single-candidate escape hatch in
the function doesn't short-circuit before reaching the buggy line).
"""

import importlib

import pytest

MODULE_NAMES = [
    "scripts.nationwide_2404_ingest",  # already fixed -- included as the reference
    "scripts.nationwide_1911_ingest",
    "scripts.nationwide_395_ingest",
    "scripts.nationwide_431_ingest",
    "scripts.wo130_county_ingest",
]


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_pick_calendar_candidate_ambiguous_case_does_not_crash(module_name):
    mod = importlib.import_module(module_name)

    # Real shape: two real, past-dated candidates, each blocked by a real
    # PROMO_BLOCKLIST word ("tutorial"/"promo") -- ambiguous, not a single
    # candidate, and `dated` is non-empty (both parse as real dates).
    candidates = [
        {"title": "City Council Meeting Tutorial", "date": "2026-08-01"},
        {"title": "Board Promo Video", "date": "2026-07-15"},
    ]

    result, reason = mod.pick_calendar_candidate(candidates)

    assert result is None
    assert "ambiguous" in reason
    # The real titles must actually appear in the message (not a tuple's
    # repr, and not an AttributeError traceback) -- this is what the bug
    # broke: before the fix, this call raised instead of returning.
    assert "City Council Meeting Tutorial" in reason
    assert "Board Promo Video" in reason


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_pick_calendar_candidate_still_picks_a_clean_recent_candidate(module_name):
    mod = importlib.import_module(module_name)

    candidates = [
        {"title": "City Council Regular Meeting", "date": "2026-08-01"},
        {"title": "Board Promo Video", "date": "2026-07-15"},
    ]

    result, reason = mod.pick_calendar_candidate(candidates)

    assert reason == ""
    assert result["title"] == "City Council Regular Meeting"
