"""WO-939 (2026-09-21): scripts/challenge_markers.py -- the shared
CHALLENGE_MARKERS list/is_challenge() every sweep script now imports
instead of carrying its own copy.

Marker strings are real (confirmed live, WO-278 and earlier): the plain
list, and the 3-marker Radware/ShieldSquare addition confirmed against a
real block page served by co.roseau.mn.us (see BACKLOG_DONE.md's WO-939
and WO-278 entries). This file tests the shared module's own behavior and
the consolidation itself (every consuming script now sees the same,
current list), not a new real-world finding.
"""

import sys

import pytest

from scripts.challenge_markers import CHALLENGE_MARKERS, is_challenge


def test_is_challenge_matches_a_real_cloudflare_marker():
    assert is_challenge("<title>Just a moment...</title>")


def test_is_challenge_matches_the_radware_markers():
    # The real gap WO-278 found live (co.roseau.mn.us, 2026-09-12): a
    # Radware/ShieldSquare bot-management challenge that 8 of the 9
    # scripts' own local copies didn't recognize before this WO.
    assert is_challenge("<title>Radware Block Page</title>")
    assert is_challenge("redirected via validate.perfdrive.com")
    assert is_challenge("blocked by shieldsquare")


def test_is_challenge_is_case_insensitive():
    assert is_challenge("ATTENTION REQUIRED! | CLOUDFLARE")


def test_is_challenge_false_for_ordinary_page_text():
    assert not is_challenge("<html><body>City Council Agenda</body></html>")


def test_is_challenge_handles_falsy_input():
    assert not is_challenge("")
    assert not is_challenge(None)


def test_challenge_markers_is_immutable():
    # A tuple, not a list -- nothing importing it can accidentally mutate
    # the shared instance out from under every other importer.
    assert isinstance(CHALLENGE_MARKERS, tuple)


@pytest.mark.parametrize(
    "module_name",
    [
        "wo145_api_first_sweep",
        "wo147_access_ladder_sweep",
        "wo149_county_ladder_sweep",
        "wo176_path_pilot",
        "wo265_school_district_sweep",
        "wo268_passive_discovery",
        "wo270_wordpress_pilot",
        "wo272_probe_first_party_paths",
        "wo282_recon",
    ],
)
def test_every_consolidated_script_shares_the_canonical_list(module_name):
    """WO-939's own count, re-derived from `git grep -l CHALLENGE_MARKERS`
    on 2026-09-21: exactly these 9 scripts carried their own literal copy
    (re-confirming WO-931's earlier recount from 8 to 9). Each now imports
    the shared constant instead -- this pins that they all see the exact
    same, current (Radware-inclusive) list, not just "a" list.

    Value equality, not `is`: three of the nine (wo268/wo270/wo282) import
    it bare (`from challenge_markers import ...`, not `scripts.challenge_
    markers`, since they don't otherwise add the repo root to sys.path --
    see each one's own WO-939 comment), which loads the same file under a
    SECOND module-cache key and legitimately produces a second, equal-but-
    not-identical tuple object. That's a Python import-system fact about
    dual bare/qualified imports, not a real content drift -- what matters
    is every script seeing the same 16 real markers, which `==` checks.

    `wo145_api_first_sweep` also imports rtr-discovery (`discovery.ledger`)
    at module level, same gap `tests/test_wo932_wo145_raw_identity.py`
    already documents: CI has no `~/Documents/rtr-discovery` checkout, so
    this fails there with `ModuleNotFoundError: No module named
    'discovery'` even though it imports fine on a machine that has that
    sibling repo checked out (confirmed live 2026-09-21 -- passed locally,
    failed in CI on first push). Skip that one param there rather than
    fail the build; the other 8 don't touch rtr-discovery and still run
    everywhere."""
    sys.path.insert(0, "scripts")
    try:
        module = __import__(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == "discovery":
            pytest.skip(
                f"{module_name} imports rtr-discovery (`discovery`), not "
                "installed here -- needs a machine with "
                "~/Documents/rtr-discovery checked out"
            )
        raise
    finally:
        if sys.path and sys.path[0] == "scripts":
            sys.path.pop(0)
    assert module.CHALLENGE_MARKERS == CHALLENGE_MARKERS
