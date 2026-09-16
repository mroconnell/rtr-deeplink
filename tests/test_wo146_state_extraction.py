"""Tests for `scripts/wo146_api_relist_sweep.py`'s state/province
extraction inside `_looks_wrong_government()` (WO-280, 2026-09-12).

Real, confirmed-live bug (filed by WO-259 part 2, recovered by hand that
session -- see BACKLOG_DONE.md's WO-259 entry and BACKLOG.md's
"Open bugs" entry this WO closes): `_extract_state_from_text()` scanned
the WHOLE resolved jurisdiction/meeting_body/title text for ANY bare,
standalone two-letter word and compared it against the full US+Canada
state/province code table, with no requirement that the word actually
read as a state suffix. "la" in "Portage la Prairie" matched as
Louisiana (LA) even though the row's own state (MB) and the video's own
title/channel both said Manitoba -- a French place-name word, not a real
mismatch. The candidate was auto-rejected by `IDENTITY_CHECK_HOOK`
before it ever reached the mandatory hand-read gate.

The same collision risk applies to any other common short word that
also happens to be a real postal code ("or" -> Oregon, "de" -> Delaware,
"in" -> Indiana, and others BACKLOG.md names). The fix restricts the
two-letter scan to a comma-adjacent match ("City, ST" -- the shape every
genuine catch this function already relies on has: "Loudoun County,
VA", "Village of Winfield, IL", "Greenville, NC"), never a bare interior
token. Full state-NAME matching (e.g. "Colorado General Assembly") is
untouched -- that half was never the bug.

All names below are real governments, looked up in
`app/utils/jurisdiction_data/places.csv` / `ca_csd.csv`, not invented --
per CLAUDE.md's synthetic-test convention, the payload TEXT is
hand-built (these governments' real resolved jurisdiction strings were
never recorded verbatim) but every place name, its real state/province,
and its real government kind are confirmed real facts, independently
checkable in those files.
"""

from scripts.wo146_api_relist_sweep import (
    _extract_state_from_text,
    _looks_wrong_government,
)


def _payload(jurisdiction: str) -> dict:
    return {"jurisdiction": jurisdiction, "meeting_body": "", "title": ""}


def test_positive_trailing_comma_suffix_still_means_its_real_state():
    """Grand Isle town, LA is real and really is in Louisiana -- a
    genuine ", LA" suffix must still be read as Louisiana."""
    assert _extract_state_from_text("Grand Isle town, LA") == "LA"
    assert (
        _looks_wrong_government(
            {"state": "LA", "gov_kind": "town"}, _payload("Grand Isle town, LA")
        )
        is None
    )


def test_portage_la_prairie_mb_is_not_read_as_louisiana():
    """The exact real case WO-259 part 2 hit and had to recover by
    hand: Portage la Prairie is a real Manitoba city/RM
    (app/utils/jurisdiction_data/ca_csd.csv), and "la" is an ordinary
    French place-name word, not a state code."""
    assert _extract_state_from_text("Portage la Prairie") is None
    assert (
        _looks_wrong_government(
            {"state": "MB", "gov_kind": "cousub"}, _payload("Portage la Prairie")
        )
        is None
    )


def test_truth_or_consequences_nm_is_not_read_as_oregon():
    """Truth or Consequences city, NM is real (places.csv). The old bare
    two-letter scan matched "or" (Oregon) as its FIRST hit, left-to-right,
    before ever reaching the real ", NM" suffix later in the same
    string -- a false mismatch against this row's own correct state."""
    assert _extract_state_from_text("Truth or Consequences city, NM") == "NM"
    assert (
        _looks_wrong_government(
            {"state": "NM", "gov_kind": "municipality"},
            _payload("Truth or Consequences city, NM"),
        )
        is None
    )


def test_ponce_de_leon_fl_is_not_read_as_delaware():
    """Ponce de Leon town, FL is real (places.csv); "de" is an ordinary
    word in the name, not the Delaware code."""
    assert _extract_state_from_text("Ponce de Leon town, FL") == "FL"
    assert (
        _looks_wrong_government(
            {"state": "FL", "gov_kind": "town"}, _payload("Ponce de Leon town, FL")
        )
        is None
    )


def test_lake_in_the_hills_il_is_not_read_as_indiana():
    """Lake in the Hills village, IL is real (places.csv); "in" is an
    ordinary word in the name, not the Indiana code."""
    assert _extract_state_from_text("Lake in the Hills village, IL") == "IL"
    assert (
        _looks_wrong_government(
            {"state": "IL", "gov_kind": "village"},
            _payload("Lake in the Hills village, IL"),
        )
        is None
    )


def test_comma_adjacent_real_mismatch_still_catches_a_genuine_collision():
    """The check must still do its real job: a row that expects one
    state but whose resolved content names a different one, in the
    genuine "City, ST" shape, is still a real mismatch."""
    result = _looks_wrong_government(
        {"state": "LA", "gov_kind": "municipality"},
        _payload("Some Other City, VA"),
    )
    assert result is not None
    assert "VA" in result
    assert "LA" in result


def test_state_full_name_matching_is_unaffected_by_the_fix():
    """Colorado General Assembly names its state by full word, not a
    2-letter code -- this half of the function (full state NAMES) was
    never the bug and must still work."""
    assert _extract_state_from_text("Colorado General Assembly") == "CO"


def test_no_comma_no_state_found_even_with_a_real_collision_risk_word():
    """ "City of Greenville" (no comma, no state at all) is the function's
    own original motivating case (WO-146) -- must still return None, not
    regress to falsely finding a state via some other interior word."""
    assert _extract_state_from_text("City of Greenville") is None
