"""WO-1004 (2026-09-22): scripts/wo1004_domain_health_check.py's pure
classifier, `classify_domain_health()`. This is a script test, not an
app/archive one -- no network, no DB -- so it exercises the classifier
directly with hand-built HTML, same synthetic-test convention
`tests/test_challenge_markers.py` and `tests/test_civicclerk.py` already
use: the shape reuses a schema already confirmed real elsewhere
(`name_matches()`'s own city+state substring check, unchanged from
`wo273_targeted.py`), and the facts are real, independently verifiable
places -- Fresno, CA and Crystal River, FL both already appear as real
examples in this repo's own BACKLOG.md/BACKLOG_DONE.md history, not
invented for this test.

Real-world shape this guards: WO-145's Crystal River, FL row (the
registry's real, live, wrong-tenant finding -- its recorded `domain`
resolves to Citrus County's content, not Crystal River's) and WO-347's
Elmore City, OK row (a real domain repurposed by an unrelated business)
are both the `domain_mismatch`/`domain_catch_all` shapes below, not
invented cases.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from wo1004_domain_health_check import (  # noqa: E402
    DOMAIN_CATCH_ALL,
    DOMAIN_CHALLENGE_GATE,
    DOMAIN_CONFIRMED,
    DOMAIN_MISMATCH,
    DOMAIN_UNREACHABLE,
    _normalize_domain,
    classify_domain_health,
)


def test_confirmed_when_page_names_the_right_city_and_state():
    # Real, unambiguous city -- same "Fresno, CA" fact this repo's own
    # test_civicclerk.py already relies on being real and unambiguous.
    outcome, evidence = classify_domain_health(
        html="<html><body>City of Fresno, California -- Council Agenda</body></html>",
        http_status=200,
        fetch_error="",
        catch_all=False,
        city_name="Fresno",
        state="CA",
    )
    assert outcome == DOMAIN_CONFIRMED
    assert "Fresno" in evidence


def test_mismatch_when_page_fetches_fine_but_names_a_different_government():
    # The real shape of WO-145's Crystal River, FL finding: the domain
    # resolves fine, it just isn't Crystal River's own content.
    outcome, evidence = classify_domain_health(
        html="<html><body>Citrus County Value Adjustment Board</body></html>",
        http_status=200,
        fetch_error="",
        catch_all=False,
        city_name="Crystal River",
        state="FL",
    )
    assert outcome == DOMAIN_MISMATCH
    assert "Crystal River" in evidence
    assert "200" in evidence


def test_unreachable_when_fetch_itself_failed():
    outcome, evidence = classify_domain_health(
        html="",
        http_status=None,
        fetch_error="dead-on-head",
        catch_all=False,
        city_name="Elmore City",
        state="OK",
    )
    assert outcome == DOMAIN_UNREACHABLE
    assert evidence == "dead-on-head"


def test_unreachable_when_response_has_no_body():
    outcome, evidence = classify_domain_health(
        html="",
        http_status=404,
        fetch_error="",
        catch_all=False,
        city_name="Elmore City",
        state="OK",
    )
    assert outcome == DOMAIN_UNREACHABLE
    assert "404" in evidence


def test_challenge_gate_takes_priority_over_name_check():
    # A challenge page can echo real place names back in its own markup
    # (see scripts/challenge_markers.py's own docstring on the Radware
    # redirect echoing the requested target) -- must be caught before
    # name_matches() ever runs, not after.
    outcome, _ = classify_domain_health(
        html="<title>Just a moment...</title> Fresno California",
        http_status=200,
        fetch_error="",
        catch_all=False,
        city_name="Fresno",
        state="CA",
    )
    assert outcome == DOMAIN_CHALLENGE_GATE


def test_catch_all_takes_priority_over_name_check():
    # A parked/vendor-demo shell (WO-347's Hometown, IL /
    # hometown.cablecast.tv shape) shouldn't be reported as a confident
    # mismatch -- it's inconclusive, same "inconclusive isn't proof"
    # rule wo145_api_first_sweep.py's own checks already use.
    outcome, evidence = classify_domain_health(
        html="<html>Generic parked page</html>",
        http_status=200,
        fetch_error="",
        catch_all=True,
        city_name="Hometown",
        state="IL",
    )
    assert outcome == DOMAIN_CATCH_ALL
    assert "nonsense-path" in evidence


def test_unreachable_when_row_has_no_name_to_check_against():
    # Never guesses a verdict from a row missing the data needed to
    # check it -- CLAUDE.md's "reports report, never guess" rule.
    outcome, evidence = classify_domain_health(
        html="<html>some real page</html>",
        http_status=200,
        fetch_error="",
        catch_all=False,
        city_name="",
        state="",
    )
    assert outcome == DOMAIN_UNREACHABLE
    assert "no name" in evidence


def test_normalize_domain_strips_scheme_and_path():
    assert (
        _normalize_domain("https://Emigration.Utah.gov/agendas")
        == "emigration.utah.gov"
    )
    assert _normalize_domain("http://cityoffloydada.com/") == "cityoffloydada.com"


def test_normalize_domain_passes_through_a_bare_host():
    assert _normalize_domain("cityofforistell.org") == "cityofforistell.org"


def test_normalize_domain_handles_blank():
    assert _normalize_domain("") == ""
    assert _normalize_domain(None) == ""
