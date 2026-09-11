"""Tests for scripts/coverage_alternates.py (WO-181, 2026-09-10).

Rows are hand-built (SYNTHETIC -- no live HTTP happens in this file), but
every name/domain used is a real row from
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` as of
2026-09-10, not an invented government, per CLAUDE.md's rule that a
synthetic test's facts must be independently verifiable even when the
page/response is hand-built:

- Athens city, AL: `domain` athensal.us, `alternate_domains`
  athensalabama.us, `reject_reason` dns-unresolvable (an ACCESS-class
  reject -- the case this WO's alternates retry is for).
- Ashland town, AL: `domain` cityofashland.net, `alternate_domains`
  cityofashlandal.com, `reject_reason` no-platform-link-found (a
  CONTENT-class reject -- the case this WO's scope explicitly does NOT
  retry against an alternate).
- Calera city, AL: `domain` cityofcalera.org, `alternate_domains`
  caleraal.portal.civicclerk.com, `alternate_urls`
  https://caleraal.portal.civicclerk.com/event/803/media -- same host on
  both columns, used to check `candidate_domains()` dedupes it to one
  entry rather than trying it twice.
"""

from __future__ import annotations

import pytest

from scripts.coverage_alternates import (
    ACCESS_REASONS,
    CONTENT_REASONS,
    FOUND,
    AlternatesResult,
    LadderOutcome,
    candidate_domains,
    classify_wo147_ladder_result,
    ladder_with_alternates,
    normalize_host,
)


def test_normalize_host_strips_scheme_path_port_and_userinfo():
    assert normalize_host("athensal.us") == "athensal.us"
    assert normalize_host("https://athensal.us/") == "athensal.us"
    assert normalize_host("http://www.athensal.us/agendas/") == "www.athensal.us"
    assert normalize_host("https://user:pass@athensal.us:8443/x") == "athensal.us"
    assert normalize_host("") == ""
    assert normalize_host(None) == ""
    # a leading www. is a distinct candidate, not stripped -- the ladder
    # itself tries the www/non-www variant of whatever it's given.
    assert normalize_host("www.athensal.us") == "www.athensal.us"


def test_candidate_domains_orders_primary_then_alternates_then_alt_url_hosts():
    row = {
        "domain": "cityofcalera.org",
        "alternate_domains": "caleraal.portal.civicclerk.com",
        "alternate_urls": "https://caleraal.portal.civicclerk.com/event/803/media",
    }
    # the alternate_urls host is the SAME as the alternate_domains entry
    # -- deduped to one candidate, not tried twice.
    assert candidate_domains(row) == [
        "cityofcalera.org",
        "caleraal.portal.civicclerk.com",
    ]


def test_candidate_domains_skips_blanks_and_dedupes():
    row = {
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us;;athensal.us",
        "alternate_urls": "",
    }
    assert candidate_domains(row) == ["athensal.us", "athensalabama.us"]


def test_candidate_domains_handles_missing_columns():
    assert candidate_domains({}) == []
    assert candidate_domains({"domain": "athensal.us"}) == ["athensal.us"]


def _scripted_ladder_fn(answers):
    """Returns a ladder_fn that returns `answers[domain]` in sequence,
    recording every call for assertions."""
    calls = []

    async def ladder_fn(domain, row):
        calls.append(domain)
        return answers[domain]

    ladder_fn.calls = calls
    return ladder_fn


@pytest.mark.asyncio
async def test_alternate_answers_after_access_reject_on_primary():
    """Athens city, AL shape: primary domain is dns-unresolvable (ACCESS
    class), the alternate domain finds a real platform link. The helper
    should try the alternate and report it as the answering domain."""
    row = {
        "city_name": "Athens city",
        "state_or_province": "Alabama",
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us",
        "alternate_urls": "",
        "reject_reason": "dns-unresolvable",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "athensal.us": LadderOutcome(reason="dns-unresolvable"),
            "athensalabama.us": LadderOutcome(
                reason=FOUND,
                platform="civicplus",
                hit_url="https://athensalabama.us/agendacenter",
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn)
    assert isinstance(result, AlternatesResult)
    assert result.outcome.reason == FOUND
    assert result.answered_domain == "athensalabama.us"
    assert ladder_fn.calls == ["athensal.us", "athensalabama.us"]
    assert result.alternates_tried == "athensal.us;athensalabama.us"


@pytest.mark.asyncio
async def test_content_reject_on_primary_never_tries_alternate():
    """Ashland town, AL shape: primary is no-platform-link-found (CONTENT
    class). Per WO-181's scope, this must stop at the primary -- the
    alternate is never called, even though one exists."""
    row = {
        "city_name": "Ashland town",
        "state_or_province": "Alabama",
        "domain": "cityofashland.net",
        "alternate_domains": "cityofashlandal.com",
        "alternate_urls": "",
        "reject_reason": "no-platform-link-found",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "cityofashland.net": LadderOutcome(reason="no-platform-link-found"),
            "cityofashlandal.com": LadderOutcome(
                reason=FOUND, platform="civicplus", hit_url="x"
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn)
    assert result.outcome.reason == "no-platform-link-found"
    assert result.answered_domain == "cityofashland.net"
    assert ladder_fn.calls == ["cityofashland.net"]  # alternate never touched


@pytest.mark.asyncio
async def test_every_candidate_access_class_returns_last_tried():
    row = {
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us",
        "alternate_urls": "",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "athensal.us": LadderOutcome(reason="dns-unresolvable"),
            "athensalabama.us": LadderOutcome(reason="timeout"),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn)
    assert result.outcome.reason == "timeout"
    assert result.answered_domain == "athensalabama.us"
    assert ladder_fn.calls == ["athensal.us", "athensalabama.us"]


@pytest.mark.asyncio
async def test_no_candidate_domains_reports_dns_unresolvable_without_calling_ladder_fn():
    calls = []

    async def ladder_fn(domain, row):
        calls.append(domain)
        return LadderOutcome(reason=FOUND)

    result = await ladder_with_alternates({}, ladder_fn)
    assert result.outcome.reason == "dns-unresolvable"
    assert calls == []


@pytest.mark.asyncio
async def test_max_candidates_caps_the_trail():
    row = {
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us;a-third-domain.example",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "athensal.us": LadderOutcome(reason="dns-unresolvable"),
            "athensalabama.us": LadderOutcome(reason="timeout"),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn, max_candidates=2)
    assert ladder_fn.calls == ["athensal.us", "athensalabama.us"]
    assert result.outcome.reason == "timeout"


def test_reason_sets_do_not_overlap_and_found_is_in_neither():
    assert ACCESS_REASONS & CONTENT_REASONS == set()
    assert FOUND not in ACCESS_REASONS
    assert FOUND not in CONTENT_REASONS


class _FakeLadderResult:
    def __init__(self, access_mode, platform=None, hit_url=None, note=""):
        self.access_mode = access_mode
        self.platform = platform
        self.hit_url = hit_url
        self.note = note


def test_classify_wo147_ladder_result_found():
    r = _FakeLadderResult(
        "plain", platform="civicplus", hit_url="https://x/AgendaCenter"
    )
    outcome = classify_wo147_ladder_result(r)
    assert outcome.reason == FOUND
    assert outcome.platform == "civicplus"


@pytest.mark.parametrize(
    "access_mode,expected_reason",
    [
        ("dead", "dns-unresolvable"),
        ("challenge", "cloudflare-challenge-blocked"),
        ("blocked-plain-http", "blocked-plain-http"),
        ("blocked-browser-headers", "blocked-browser-headers"),
        ("timeout", "timeout"),
    ],
)
def test_classify_wo147_ladder_result_access_class(access_mode, expected_reason):
    r = _FakeLadderResult(access_mode)
    assert classify_wo147_ladder_result(r).reason == expected_reason


def test_classify_wo147_ladder_result_reached_no_link_is_content_class():
    r = _FakeLadderResult("plain", platform=None, hit_url=None)
    outcome = classify_wo147_ladder_result(r)
    assert outcome.reason == "no-platform-link-found"
    assert outcome.reason in CONTENT_REASONS
