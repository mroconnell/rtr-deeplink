"""Tests for `archive/utils/hub_aliases.py` -- the `/j/{slug}` retired-
slug redirect map (WO-99, hand-add exception added WO-106).

Reads the real committed `archive/data/hub_slug_aliases.csv` rather than
a synthetic fixture -- per CLAUDE.md, that file's own docstring says it
is generated wholesale and reviewable in the PR beside the numbers that
justify it, so testing against a fabricated file would not catch a real
regression in the committed data.
"""

from archive.utils import hub_aliases


def test_gloucester_ma_redirects_to_the_school_district_hub():
    """Real production case (2026-09-03): `/j/gloucester-ma` was a live
    hub whose one page was a Gloucester County, VA school-board meeting
    mis-keyed to Gloucester, MA. Fixed per-page via
    `POST /internal/jurisdiction/override` to `us:sd:5101620`, which
    retired the `gloucester-ma` hub -- but `scripts/score_gov_registry.py`
    cannot regenerate this specific redirect (verified: it re-derives
    old/new from the same stored `jurisdiction` string, so it never sees
    a single-page manual override), so this row was hand-added to
    `hub_slug_aliases.csv` as a documented exception. This test is what
    would catch that hand-added row being lost to a future wholesale
    regen."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("gloucester-ma") == (
        "gloucester-county-public-schools-va"
    )


def test_a_slug_never_retired_has_no_redirect():
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("not-a-real-slug-at-all") is None
