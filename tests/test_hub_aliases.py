"""Tests for `archive/utils/hub_aliases.py` -- the `/j/{slug}` retired-
slug redirect map (WO-99, hand-add exception added WO-106/WO-108,
merge-not-overwrite regen added WO-109).

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


def test_las_vegas_redirects_after_the_pin_worklist_backfill():
    """Real row from the WO-109 regen (2026-09-03): `lasvegas.primegov.com`
    was pinned to `us:place:3240000` (Las Vegas, NV) in WO-107, retiring
    the bare `las-vegas` hub in favor of the state-suffixed one."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("las-vegas") == "las-vegas-nv"


def test_howard_county_redirects_after_the_pin_worklist_backfill():
    """Same WO-109 regen: `howardcounty.granicus.com` was pinned to
    `us:county:24027` (Howard County, MD) in WO-107, retiring the bare
    `howard-county` hub."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("howard-county") == "howard-county-md"


def test_ambiguous_bare_slugs_keep_their_incumbent_redirect():
    """WO-109's regen found three bare slugs (`hamilton`, `victoria`,
    `woodland`) where a NEWLY pinned tenant's raw jurisdiction text
    collides with an OLDER, still-live redirect already serving a
    different real government -- e.g. `hamilton` was already retired to
    Hamilton Police Services Board, ON (a real, currently-live hub) before
    WO-107 pinned `tvhamilton.cablecast.tv` to Hamilton, OH, whose raw
    text is also bare "Hamilton". `scripts/score_gov_registry.py` has no
    way to detect this across separate runs -- it always overwrites the
    file wholesale and never reads the previous one, so a naive re-run
    would have silently redirected `/j/hamilton` away from a real,
    currently-indexed hub. The merge deliberately keeps the incumbent
    (first-claimed) destination for all three and does not add a
    conflicting new row for the runner-up -- safe because none of the
    runner-up tenants had a live hub before their pin (all three were
    `unresolved`, which has no hub_slug at all). See BACKLOG.md for the
    general gap this is a symptom of."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert (
        hub_aliases.redirect_target("hamilton") == "hamilton-police-services-board-on"
    )
    assert hub_aliases.redirect_target("victoria") == "victoria-bc"
    assert hub_aliases.redirect_target("woodland") == "woodland-ca"
