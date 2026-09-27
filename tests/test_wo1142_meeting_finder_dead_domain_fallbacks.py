"""WO-1142: Meeting Finder stopped at `dns-unresolvable` for governments
it could still have reached. Two real gaps, both confirmed on the
2026-09-27 domain-fill run (rtr-business
`research/domain_fill_2026-09-26/dead_domains/`):

  1. `FinderInput` had no way to carry a research row's other domains,
     and `runner.py` never passed `alternates` to `start()`. 134 small
     governments whose main domain is a lapsed .gov had a working domain
     sitting in `alternate_domains`, never tried.
  2. `start._dns_resolves()` threw away `dns_lookup()`'s own guessed
     subdomains and vendor-account labels whenever the apex and `www.`
     were both dead, even when one of those guesses resolved.

The `dns_lookup()` dicts below are SYNTHETIC -- hand-built with exactly
the keys the real function (`scripts/wo282_recon.py`) returns -- because
this file guards the fallback logic, not DNS itself.
"""

from __future__ import annotations

import csv

import pytest

from app.platforms.meeting_finder import runner, start
from app.platforms.meeting_finder.fetch import Fetcher
from app.platforms.meeting_finder.models import (
    OUTCOME_DNS_UNRESOLVABLE,
    FinderInput,
)
from app.platforms.meeting_finder.start import StartResult


def _info(*, homepage=False, subdomain=None, wildcard=False, vendor=None) -> dict:
    return {
        "apex_a": ["203.0.113.10"] if homepage else [],
        "apex_cname": "",
        "www_a": [],
        "www_cname": "",
        "resolving_subdomains": (
            [
                {
                    "subdomain": subdomain.split(".")[0],
                    "host": subdomain,
                    "cname": "",
                    "a": ["198.51.100.7"],
                    "likely_own_domain_wildcard": wildcard,
                }
            ]
            if subdomain
            else []
        ),
        "resolving_vendor_labels": (
            [
                {
                    "host": vendor,
                    "platform": "civicweb",
                    "a": ["198.51.100.8"],
                    "cname": "",
                }
            ]
            if vendor
            else []
        ),
    }


def _patch(monkeypatch, table: dict) -> list:
    """`dns_lookup()` answers from `table` (domain -> dict, missing = dead).
    robots/sitemap calls are recorded so a test can assert none happened."""
    live_calls: list = []
    dead = _info()
    monkeypatch.setattr(start, "dns_lookup", lambda d: table.get(d, dead))

    def robots(domain):
        live_calls.append(("robots", domain))
        return {"crawl_delay_seconds": None, "error": None}

    def sitemap(domain, robots_info):
        live_calls.append(("sitemap", domain))
        return {"found": False, "error": None, "urls": []}

    monkeypatch.setattr(start, "fetch_live_robots_v2", robots)
    monkeypatch.setattr(start, "fetch_live_sitemap_v2", sitemap)
    return live_calls


@pytest.mark.asyncio
async def test_dead_domain_falls_back_to_an_alternate_with_a_homepage(monkeypatch):
    _patch(monkeypatch, {"townofelberta.com": _info(homepage=True)})
    result = await start.start(
        "elbertaal.gov", Fetcher(max_fetches=12), alternates=["townofelberta.com"]
    )
    assert result.outcome is None
    assert "https://townofelberta.com/" in result.starting_points


@pytest.mark.asyncio
async def test_a_guessed_subdomain_is_kept_when_the_homepage_is_dead(monkeypatch):
    calls = _patch(
        monkeypatch, {"deadtown.gov": _info(subdomain="agenda.deadtown.gov")}
    )
    result = await start.start("deadtown.gov", Fetcher(max_fetches=12))
    assert result.outcome is None
    assert result.starting_points == ["https://agenda.deadtown.gov/"]
    assert "starting from guessed hosts only" in result.note
    assert calls == []  # no robots.txt or sitemap fetch against a dead homepage


@pytest.mark.asyncio
async def test_a_guessed_vendor_label_is_kept_when_the_homepage_is_dead(monkeypatch):
    _patch(monkeypatch, {"deadtown.gov": _info(vendor="deadtown.civicweb.net")})
    result = await start.start("deadtown.gov", Fetcher(max_fetches=12))
    assert result.starting_points == ["https://deadtown.civicweb.net/"]


@pytest.mark.asyncio
async def test_an_alternate_homepage_beats_a_guessed_subdomain(monkeypatch):
    _patch(
        monkeypatch,
        {
            "deadtown.gov": _info(subdomain="agenda.deadtown.gov"),
            "deadtown.org": _info(homepage=True),
        },
    )
    result = await start.start(
        "deadtown.gov", Fetcher(max_fetches=12), alternates=["deadtown.org"]
    )
    assert "https://deadtown.org/" in result.starting_points
    assert "https://agenda.deadtown.gov/" not in result.starting_points


@pytest.mark.asyncio
async def test_nothing_resolving_is_still_dns_unresolvable(monkeypatch):
    _patch(monkeypatch, {})
    result = await start.start(
        "deadtown.gov", Fetcher(max_fetches=12), alternates=["deadtown.org"]
    )
    assert result.outcome == OUTCOME_DNS_UNRESOLVABLE
    assert "deadtown.org" in result.note


@pytest.mark.asyncio
async def test_guess_subdomains_off_keeps_the_old_gate(monkeypatch):
    _patch(monkeypatch, {"deadtown.gov": _info(subdomain="agenda.deadtown.gov")})
    result = await start.start(
        "deadtown.gov", Fetcher(max_fetches=12), guess_subdomains=False
    )
    assert result.outcome == OUTCOME_DNS_UNRESOLVABLE


@pytest.mark.asyncio
async def test_an_own_domain_wildcard_entry_does_not_count(monkeypatch):
    _patch(
        monkeypatch,
        {"deadtown.gov": _info(subdomain="agenda.deadtown.gov", wildcard=True)},
    )
    result = await start.start("deadtown.gov", Fetcher(max_fetches=12))
    assert result.outcome == OUTCOME_DNS_UNRESOLVABLE


@pytest.mark.asyncio
async def test_runner_hands_alternates_to_start(monkeypatch):
    seen = {}

    async def fake_start(domain_or_url, fetcher, **kwargs):
        seen.update(kwargs)
        return StartResult(starting_points=[], outcome="dns-unresolvable", note="dead")

    monkeypatch.setattr(runner, "run_start", fake_start)
    fi = FinderInput(url="deadtown.gov", entry="start", alternates=("deadtown.org",))
    await runner.run_one(fi, run_id="wo1142")
    assert seen.get("alternates") == ("deadtown.org",)


def test_cli_reads_the_alternates_column(tmp_path):
    from scripts import meeting_finder as cli

    path = tmp_path / "rows.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "gov_id", "alternates"])
        w.writerow(
            ["deadtown.gov", "us:place:0000001", "deadtown.org; www.deadtown.com"]
        )
        w.writerow(["other.gov", "", ""])
    rows = cli._read_inputs(path, default_mode="audit", default_entry="start")
    assert rows[0].alternates == ("deadtown.org", "www.deadtown.com")
    assert rows[1].alternates == ()
