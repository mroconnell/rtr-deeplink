"""Tests for `archive/utils/hub_aliases.py` -- the `/j/{slug}` retired-
slug redirect map (WO-99, hand-add exception added WO-106/WO-108,
merge-not-overwrite regen added WO-109, match-scoped-pin blind spot
fixed and the hamilton/woodland incumbent decision reversed by WO-112).

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


def test_ambiguous_bare_slugs_hamilton_and_woodland_now_favor_the_new_pin():
    """WO-109's regen found three bare slugs (`hamilton`, `victoria`,
    `woodland`) where a NEWLY pinned tenant's raw jurisdiction text
    collides with an OLDER, still-live redirect already serving a
    different real government, and kept the incumbent destination for
    all three out of caution (safe because every runner-up tenant was
    `unresolved` before its pin, meaning it had no live hub_slug to
    protect).

    WO-112 (2026-09-03) reverses that default for two of the three, on
    Ryan's own explicit instruction after reviewing the live site
    following the WO-107 backfill: for `hamilton` and `woodland`, the
    NEW destination is what he wants live -- `/j/hamilton` should go to
    Hamilton, OH (`tvhamilton.cablecast.tv`'s pin) and `/j/woodland`
    should go to Woodland, WA, not the incumbent Ontario police board /
    Woodland, CA hubs that happened to claim the bare slug first. Both
    incumbents remain real, live hubs -- just no longer reachable via
    the bare, ambiguous slug -- confirmed independently reachable at
    their own unambiguous slugs
    (`hamilton-police-services-board-on`, `woodland-ca`) via
    `display.hub_slug()` on their own gov_ids, so this flip does not
    orphan either one.

    `victoria` is deliberately UNCHANGED: Ryan did not mention it, and
    per BACKLOG.md it's a different kind of case -- `STATE_gov_identity.md`
    already flags `victoria-bc` as possibly based on a premise #707 later
    corrected (the tenant may actually be Victoria, MN), so it stays an
    open question for Ryan rather than assumed to follow the same
    resolution as the other two."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("hamilton") == "hamilton-city-oh"
    assert hub_aliases.redirect_target("woodland") == "woodland-wa"
    assert hub_aliases.redirect_target("victoria") == "victoria-bc"


def test_bellefonte_borough_redirects_after_the_match_scoped_pin_fix():
    """Real row added by WO-112 (2026-09-03): WO-107 pinned
    `videoplayer.telvue.com`'s `GNduNoua2rBThhw6N4PRP9OCSPf6B2ru` TelVue
    org token to `us:county:42027` (Centre County, PA), but
    `scripts/score_gov_registry.py`'s WO-109 regen missed it, because
    `score_rows()` calls `resolve_government()` with no `path`/
    `page_hints` argument, so `_pinned()` can only see host-level pins,
    never `match`-scoped ones like this ("Bellefonte Borough" -> Centre
    County, PA). Added by hand from the pre-backfill
    `reports/gov_registry_scoring_2026-09-03/sheet_archive.csv` snapshot,
    the same source WO-109's other rows came from."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("bellefonte-borough") == "centre-county-pa"


def test_town_of_woodside_redirects_after_the_match_scoped_pin_fix():
    """Same WO-112 fix, same root cause as the Bellefonte Borough test
    above: WO-107 pinned 24 `youtu.be` video ids to `us:place:0686440`
    (Woodside, CA), a per-video `match`-scoped pin the WO-109 regen could
    not see."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("town-of-woodside") == "woodside-ca"


def test_phoenix_redirects_after_the_match_scoped_pin_fix():
    """Same WO-112 fix: WO-107 pinned 3 `www.youtube.com` video ids to
    `us:place:0455000` (Phoenix, AZ), a per-video `match`-scoped pin the
    WO-109 regen could not see. `phoenix` is also the bare slug for a
    `phoenix.legistar.com` page whose raw jurisdiction was "City of
    Phoenix" -- both hash to the same `old_hub_slug` and both are the
    same real government, so one redirect row correctly covers both."""
    hub_aliases.hub_slug_aliases.cache_clear()
    assert hub_aliases.redirect_target("phoenix") == "phoenix-az"
