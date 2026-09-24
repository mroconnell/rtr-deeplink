"""Tests for scripts/meeting_finder_to_drains.py (WO-1043).

`to-drains` fixtures use the real field names and shape confirmed
2026-09-24 by reading two real Meeting Finder overnight batches
(overnight/verdicts.csv.jsonl, overnight2/verdicts.csv.jsonl) -- the
specific rows below are hand-built, but the shape (field names, a bare
domain in `input_url`, `identity_expected_gov_id` rather than a plain
`gov_id`) is real, not invented.

`from-drains` fixtures are synthetic per CLAUDE.md's synthetic-test
convention: no drain2/drain3 run has produced a real results file yet
(this WO's own dry run only had verdicts.csv.jsonl to work with), so
these reuse the schema confirmed straight from
`elastic_sweep_script.py`'s `resolutions` shape and
`queue_pipeline.py`'s `cmd_drain2()`/`cmd_drain3()` docstrings and code
(both read, not guessed) rather than an invented structure.
"""

from __future__ import annotations

import csv
import json

from scripts.meeting_finder_to_drains import (
    build_drain_feed,
    dedupe_mf_rows,
    domain_from_url,
    is_drain_outcome,
    load_stage2_results,
    load_stage3_results,
    load_verdicts_jsonl,
    resolution_is_interesting,
    resolution_vendor_confirmed,
    stage2_rows_to_mf,
    stage3_rows_to_mf,
    verdict_to_recon_row,
    write_mf_input_csv,
    write_recon_jsonl,
)


def _verdict(**overrides):
    row = {
        "audio_only": False,
        "duration_seconds": None,
        "entry_phase": "start",
        "fetches": 0,
        "finished_at": "2026-09-24T05:26:39Z",
        "forks": 0,
        "hops": 0,
        "identity_expected_gov_id": "us:cousub:2004954925",
        "identity_points_to": None,
        "identity_resolved_gov_id": None,
        "identity_verdict": "not-checked",
        "input_url": "elkcounty.org",
        "leads": [],
        "low_confidence_reason": "",
        "note": "dns-unresolvable",
        "outcome": "dns-unresolvable",
        "path": [],
        "phase_reached": "start",
        "platform": None,
        "requests_total": 0,
        "result_url": None,
        "run_id": "b1a411c48570",
        "tier": None,
        "try_next": "domain dead: find the current website (alternate domains)",
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------- #
# is_drain_outcome / domain_from_url                                     #
# --------------------------------------------------------------------- #


def test_is_drain_outcome_matches_named_outcomes():
    for outcome in (
        "no-meeting-nor-video",
        "cloudflare-challenge-blocked",
        "dns-unresolvable",
        "timeout",
        "internal-timeout",
        "account-not-found",
    ):
        assert is_drain_outcome(outcome)


def test_is_drain_outcome_matches_blocked_prefix():
    assert is_drain_outcome("blocked-headless")
    assert is_drain_outcome("blocked-browser-headers")
    assert is_drain_outcome("blocked-waf-akamai")
    assert is_drain_outcome("blocked-plain-http")


def test_is_drain_outcome_rejects_a_real_find():
    # A real find, or nothing to report -- never sent to the drains.
    assert not is_drain_outcome(None)
    assert not is_drain_outcome("meeting-without-video")
    assert not is_drain_outcome("video-low-confidence")
    assert not is_drain_outcome("youtube-lead-only")
    assert not is_drain_outcome("error")


def test_domain_from_url_handles_bare_domain_and_full_url():
    assert domain_from_url("elkcounty.org") == "elkcounty.org"
    assert domain_from_url("https://www.example.gov/agendas") == "example.gov"
    assert domain_from_url("http://Example.GOV:8080/") == "example.gov"
    assert domain_from_url("") == ""
    assert domain_from_url(None) == ""


# --------------------------------------------------------------------- #
# to-drains                                                              #
# --------------------------------------------------------------------- #


def test_verdict_to_recon_row_sets_dns_gate_for_dns_unresolvable():
    v = _verdict(outcome="dns-unresolvable", input_url="elkcounty.org")
    row = verdict_to_recon_row(v, "elkcounty.org")
    assert row["gov_id"] == "us:cousub:2004954925"
    assert row["domain"] == "elkcounty.org"
    assert row["dns_gate"] == "dns-unresolvable"
    assert row["meeting_finder_outcome"] == "dns-unresolvable"


def test_verdict_to_recon_row_no_dns_gate_for_other_outcomes():
    v = _verdict(
        outcome="timeout",
        input_url="example.gov",
        try_next="site timed out: retry later",
    )
    row = verdict_to_recon_row(v, "example.gov")
    assert "dns_gate" not in row
    assert row["meeting_finder_try_next"] == "site timed out: retry later"


def test_build_drain_feed_picks_only_matching_outcomes_and_counts_them():
    rows = [
        _verdict(
            outcome="dns-unresolvable", input_url="a.gov", identity_expected_gov_id="g1"
        ),
        _verdict(
            outcome="blocked-headless", input_url="b.gov", identity_expected_gov_id="g2"
        ),
        _verdict(
            outcome="no-meeting-nor-video",
            input_url="c.gov",
            identity_expected_gov_id="g3",
        ),
        # A real find -- never sent to the drains.
        _verdict(
            outcome="meeting-without-video",
            input_url="d.gov",
            identity_expected_gov_id="g4",
        ),
        # Nothing resolved at all, still not a drain outcome.
        _verdict(outcome=None, input_url="e.gov", identity_expected_gov_id="g5"),
    ]
    recon_rows, counts, skipped = build_drain_feed(rows)
    assert skipped == 0
    assert {r["domain"] for r in recon_rows} == {"a.gov", "b.gov", "c.gov"}
    assert counts == {
        "dns-unresolvable": 1,
        "blocked-headless": 1,
        "no-meeting-nor-video": 1,
    }


def test_build_drain_feed_dedupes_by_domain_keeping_the_last_verdict():
    rows = [
        _verdict(outcome="timeout", input_url="a.gov", try_next="first try"),
        _verdict(outcome="dns-unresolvable", input_url="a.gov", try_next="second try"),
    ]
    recon_rows, counts, _ = build_drain_feed(rows)
    assert len(recon_rows) == 1
    assert recon_rows[0]["meeting_finder_try_next"] == "second try"
    assert recon_rows[0]["dns_gate"] == "dns-unresolvable"
    # Both matching rows are still counted, even though only one survives
    # the domain dedupe.
    assert counts == {"timeout": 1, "dns-unresolvable": 1}


def test_build_drain_feed_skips_a_row_with_no_usable_domain():
    rows = [_verdict(outcome="timeout", input_url="")]
    recon_rows, counts, skipped = build_drain_feed(rows)
    assert recon_rows == []
    assert skipped == 1
    assert counts == {"timeout": 1}


def test_load_verdicts_jsonl_reads_real_shaped_files(tmp_path):
    path = tmp_path / "verdicts.csv.jsonl"
    path.write_text(
        json.dumps(_verdict(input_url="a.gov"))
        + "\n"
        + json.dumps(_verdict(input_url="b.gov"))
        + "\n"
        # a torn last line, same as a killed writer would leave
        + '{"outcome": "timeout", "input_url":',
        encoding="utf-8",
    )
    rows = load_verdicts_jsonl([path])
    assert [r["input_url"] for r in rows] == ["a.gov", "b.gov"]


def test_write_recon_jsonl_round_trips(tmp_path):
    out = tmp_path / "drains" / "feed.jsonl"
    write_recon_jsonl(out, [{"domain": "a.gov"}, {"domain": "b.gov"}])
    lines = out.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["domain"] for line in lines] == ["a.gov", "b.gov"]


def test_a_real_overnight_dns_unresolvable_row_becomes_a_drain_feed_row():
    # Real row from overnight/verdicts.csv.jsonl (WO-1043's dry run).
    real = json.loads(
        '{"audio_only": false, "duration_seconds": null, "entry_phase": "start", '
        '"fetches": 0, "finished_at": "2026-09-24T05:26:39Z", "forks": 0, "hops": 0, '
        '"identity_expected_gov_id": "us:cousub:2004954925", "identity_points_to": null, '
        '"identity_resolved_gov_id": null, "identity_verdict": "not-checked", '
        '"input_url": "elkcounty.org", "leads": [], "low_confidence_reason": "", '
        '"note": "dns-unresolvable", "outcome": "dns-unresolvable", "path": [], '
        '"phase_reached": "start", "platform": null, "requests_total": 0, '
        '"result_url": null, "run_id": "b1a411c48570", "tier": null, '
        '"try_next": "domain dead: find the current website (alternate domains)"}'
    )
    recon_rows, counts, skipped = build_drain_feed([real])
    assert skipped == 0
    assert counts == {"dns-unresolvable": 1}
    assert recon_rows[0]["domain"] == "elkcounty.org"
    assert recon_rows[0]["gov_id"] == "us:cousub:2004954925"
    assert recon_rows[0]["dns_gate"] == "dns-unresolvable"


# --------------------------------------------------------------------- #
# from-drains                                                            #
# --------------------------------------------------------------------- #


def _resolution(**overrides):
    row = {
        "subdomain": "live.example.gov",
        "chain": ["live.example.gov", "granicus.com"],
        "vendor_match": [],
        "platform_hits": [],
        "web_host_hints": [],
    }
    row.update(overrides)
    return row


def test_resolution_is_interesting_requires_a_resolved_chain():
    assert not resolution_is_interesting(_resolution(chain=[]), "example.gov")


def test_resolution_is_interesting_true_for_vendor_match():
    res = _resolution(subdomain="www2.example.gov", vendor_match=["granicus.com"])
    assert resolution_is_interesting(res, "example.gov")


def test_resolution_is_interesting_true_for_keyword_label():
    res = _resolution(subdomain="live.example.gov")
    assert resolution_is_interesting(res, "example.gov")


def test_resolution_is_interesting_false_for_noise_label():
    res = _resolution(subdomain="vpn.example.gov", chain=["vpn.example.gov", "1.2.3.4"])
    assert not resolution_is_interesting(res, "example.gov")


def test_resolution_is_interesting_false_for_an_ordinary_label():
    res = _resolution(
        subdomain="mail.example.gov", chain=["mail.example.gov", "1.2.3.4"]
    )
    assert not resolution_is_interesting(res, "example.gov")


def test_resolution_vendor_confirmed_true_for_supported_platform_hit():
    res = _resolution(
        platform_hits=[{"host": "x", "platform": "granicus", "supported": True}]
    )
    assert resolution_vendor_confirmed(res)


def test_resolution_vendor_confirmed_false_for_unsupported_platform_hit():
    res = _resolution(
        platform_hits=[{"host": "x", "platform": "simbli", "supported": False}]
    )
    assert not resolution_vendor_confirmed(res)


def test_stage2_rows_to_mf_enters_at_identify_when_vendor_confirmed():
    entries = [
        {
            "gov_id": "us:place:1",
            "domain": "example.gov",
            "resolutions": [
                _resolution(
                    subdomain="cablecast.example.gov", vendor_match=["cablecast.tv"]
                ),
            ],
        }
    ]
    rows = stage2_rows_to_mf(entries)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://cablecast.example.gov/"
    assert rows[0]["gov_id"] == "us:place:1"
    assert rows[0]["entry"] == "identify"
    assert rows[0]["url_source"] == "own-site"
    assert rows[0]["mode"] == "pin"


def test_stage2_rows_to_mf_enters_at_start_for_keyword_only_match():
    entries = [
        {
            "gov_id": "us:place:2",
            "domain": "example.gov",
            "resolutions": [_resolution(subdomain="live.example.gov")],
        }
    ]
    rows = stage2_rows_to_mf(entries)
    assert rows[0]["entry"] == "start"


def test_stage2_rows_to_mf_skips_uninteresting_resolutions():
    entries = [
        {
            "gov_id": "us:place:3",
            "domain": "example.gov",
            "resolutions": [
                _resolution(
                    subdomain="vpn.example.gov", chain=["vpn.example.gov", "1.2.3.4"]
                )
            ],
        }
    ]
    assert stage2_rows_to_mf(entries) == []


def test_stage3_rows_to_mf_emits_hub_hit_urls_at_identify_for_vendor_cname():
    results = [
        {
            "subdomain": "live.example.gov",
            "gov_id": "us:place:1",
            "reason": "vendor-cname",
            "query_ok": True,
            "hub_hits": [
                {
                    "url": "https://live.example.gov/agenda/1",
                    "status": 200,
                    "timestamp": "2026",
                },
                {
                    "url": "https://live.example.gov/agenda/1",
                    "status": 200,
                    "timestamp": "2026",
                },
            ],
        }
    ]
    rows = stage3_rows_to_mf(results)
    assert len(rows) == 1  # deduped by URL
    assert rows[0]["url"] == "https://live.example.gov/agenda/1"
    assert rows[0]["entry"] == "identify"


def test_stage3_rows_to_mf_emits_root_when_no_hub_hits_but_vendor_confirmed():
    results = [
        {
            "subdomain": "video.example.gov",
            "gov_id": "us:place:1",
            "reason": "vendor-cname",
            "query_ok": True,
            "hub_hits": [],
        }
    ]
    rows = stage3_rows_to_mf(results)
    assert rows == [
        {
            "url": "https://video.example.gov/",
            "gov_id": "us:place:1",
            "url_source": "own-site",
            "entry": "identify",
            "mode": "pin",
        }
    ]


def test_stage3_rows_to_mf_skips_keyword_only_row_with_no_hub_hits():
    results = [
        {
            "subdomain": "live.example.gov",
            "gov_id": "us:place:1",
            "reason": "keyword",
            "query_ok": True,
            "hub_hits": [],
        }
    ]
    assert stage3_rows_to_mf(results) == []


def test_stage3_rows_to_mf_skips_a_failed_query():
    results = [
        {
            "subdomain": "live.example.gov",
            "gov_id": "us:place:1",
            "reason": "vendor-cname",
            "query_ok": False,
            "hub_hits": [],
        }
    ]
    assert stage3_rows_to_mf(results) == []


def test_dedupe_mf_rows_prefers_identify_over_start():
    rows = [
        {
            "url": "https://a.gov/",
            "gov_id": "g",
            "url_source": "own-site",
            "entry": "start",
            "mode": "pin",
        },
        {
            "url": "https://a.gov/",
            "gov_id": "g",
            "url_source": "own-site",
            "entry": "identify",
            "mode": "pin",
        },
    ]
    deduped = dedupe_mf_rows(rows)
    assert len(deduped) == 1
    assert deduped[0]["entry"] == "identify"


def test_load_stage2_results_reads_a_json_array(tmp_path):
    path = tmp_path / "results_stage2.json"
    path.write_text(
        json.dumps([{"domain": "a.gov"}, {"domain": "b.gov"}]), encoding="utf-8"
    )
    assert [e["domain"] for e in load_stage2_results(path)] == ["a.gov", "b.gov"]


def test_load_stage2_results_missing_file_is_empty(tmp_path):
    assert load_stage2_results(tmp_path / "missing.json") == []


def test_load_stage3_results_reads_jsonl(tmp_path):
    path = tmp_path / "results_stage3.jsonl"
    path.write_text(
        json.dumps({"subdomain": "a.gov"})
        + "\n"
        + json.dumps({"subdomain": "b.gov"})
        + "\n",
        encoding="utf-8",
    )
    assert [r["subdomain"] for r in load_stage3_results(path)] == ["a.gov", "b.gov"]


def test_write_mf_input_csv_has_the_expected_header_and_rows(tmp_path):
    out = tmp_path / "input.csv"
    write_mf_input_csv(
        out,
        [
            {
                "url": "https://a.gov/",
                "gov_id": "g1",
                "url_source": "own-site",
                "entry": "identify",
                "mode": "pin",
            }
        ],
    )
    with out.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["url", "gov_id", "url_source", "entry", "mode"]
        rows = list(reader)
    assert rows == [
        {
            "url": "https://a.gov/",
            "gov_id": "g1",
            "url_source": "own-site",
            "entry": "identify",
            "mode": "pin",
        }
    ]
