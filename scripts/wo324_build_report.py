#!/usr/bin/env python3
"""WO-324 final classification and report builder.

Walks the full 493-row group-5 population (Canadian governments that
only ever had the access ladder) and assigns each one exactly one final
outcome, using phase 1 recon (`wo324_recon.jsonl`), phase 2 classify
(`wo324_classified.csv`), phase 3 targeted fetch (`wo324_targeted.csv`),
and the hand `resolve()` diagnostic (`resolve_diagnostic_output.txt`,
this WO's private scratch dir) run against the 51 real, name-and-state-
matched platform confirmations phase 3 found.

Rules, in order:
1. Quebec rows (258 of 493): the conductor's mid-run instruction
   (2026-09-12, citing WO-323's 0/92 finding that this pipeline's hop-
   link vocabulary is English-only) -- phase 3 was never run for these,
   so they are `deferred-french-vocab`, not a fresh finding. Phase 1
   still ran for all of them, so the saved homepage HTML is ready for
   WO-327's French-vocabulary rerun.
2. A government with a real, name-and-state-matched platform confirmed
   in phase 3, `resolve()`-verified: `meeting-without-video` (0 of 51
   resolved to a real video; see the WO's own report/BACKLOG_DONE entry
   for the two CivicPlus `NoVideoCandidateFound` cases folded in here).
   The one exception (Claresholm, AB) whose confirmed page's own HTML
   embeds a youtube.com video is `PENDING_YOUTUBE_LEAD` here -- not
   verified further per the no-YouTube-fetch rule, not folded into
   meeting-without-video since there IS a video, just an unverified one;
   left untouched in jurisdiction_coverage.csv (its existing
   `prior_reject_reason` stands) rather than guessed.
3. `dns-unresolvable` from phase 1's DNS gate.
4. `blocked-waf-akamai` from phase 1's Akamai/govAccess CNAME check.
5. An access-class block already recorded in phase 1
   (`blocked-plain-http`/`blocked-browser-headers`) -- the site never
   answered at all, so a later phase-3 rung-3 probe failing on a
   certificate/connection error too is the SAME outcome, not a new one.
6. A real `cloudflare-challenge-blocked` seen at any phase-3 rung.
7. Everything else that reached phase 1 successfully but phase 3 found
   no real, name-matched platform: `no-platform-link-found`.

Writes `research/wo324_report.csv` (one row per government, resumable --
this script is a pure offline recompute over the already-flushed phase
files, safe to rerun any time) and prints the funnel tables.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo324_population.csv"
RECON_JSONL = RESEARCH_DIR / "wo324_recon.jsonl"
TARGETED_CSV = RESEARCH_DIR / "wo324_targeted.csv"
REPORT_CSV = RESEARCH_DIR / "wo324_report.csv"

SCRATCH_DIR = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/a5ec6b6cf78e0d437/wo324"
)
RESOLVE_OUTPUT = SCRATCH_DIR / "resolve_diagnostic_output.txt"


def load_population() -> list[dict]:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_recon() -> dict:
    out = {}
    if RECON_JSONL.exists():
        with open(RECON_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                out[r["domain"]] = r
    return out


def load_targeted() -> dict:
    by_domain: dict[str, list[dict]] = {}
    if TARGETED_CSV.exists():
        with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                by_domain.setdefault(row["domain"], []).append(row)
    return by_domain


def load_resolve_output() -> dict:
    """domain -> (kind, url, detail) from the hand resolve_diagnostic run."""
    out = {}
    if not RESOLVE_OUTPUT.exists():
        return out
    with open(RESOLVE_OUTPUT, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            kind = parts[0]
            if kind not in (
                "RESOLVED",
                "RESOLVE_FAILED",
                "CALENDAR_PAGE",
                "UNSUPPORTED",
                "YOUTUBE_EMBED_SKIPPED",
                "NO_URL",
            ):
                continue
            domain = parts[1]
            out[domain] = (kind, line)
    return out


def classify(pop_row: dict, recon: dict, targeted: dict, resolved: dict) -> dict:
    domain = pop_row["domain"]
    gov_id = pop_row["gov_id"]
    name = pop_row["name"]
    state = pop_row["state"]

    if state == "Quebec":
        return {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "outcome": "deferred-french-vocab",
            "evidence_url": "",
            "note": "phase 1 ran (homepage HTML cached for WO-327); "
            "phase 3 skipped per conductor instruction, WO-323's own "
            "0/92 finding on the English-only hop vocabulary",
        }

    if domain in resolved:
        kind, line = resolved[domain]
        if kind == "YOUTUBE_EMBED_SKIPPED":
            return {
                "domain": domain,
                "gov_id": gov_id,
                "name": name,
                "state": state,
                "outcome": "PENDING_YOUTUBE_LEAD",
                "evidence_url": "",
                "note": "confirmed platform page embeds a youtube.com "
                "video; not resolve()-verified per the no-YouTube-fetch "
                "rule; recorded to youtube_channel_leads.csv instead; "
                "existing jurisdiction_coverage.csv row left untouched",
            }
        # RESOLVED (video_url always None here) or RESOLVE_FAILED
        # (NoVideoCandidateFound) -- both are a real, confirmed platform
        # with content and no video.
        m = re.search(r"source_url='([^']*)'", line)
        evidence = m.group(1) if m else ""
        if not evidence:
            m2 = re.match(
                r"RESOLVE_FAILED\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|([^|]*)\|", line
            )
            evidence = m2.group(1) if m2 else ""
        return {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "outcome": "meeting-without-video",
            "evidence_url": evidence,
            "note": "real, name-and-state-matched platform confirmed "
            "in phase 3, resolve()-verified; no video",
        }

    rec = recon.get(domain, {})
    access_mode = rec.get("access_mode")
    dns_gate = rec.get("dns_gate")

    if dns_gate == "dns-unresolvable":
        return {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "outcome": "dns-unresolvable",
            "evidence_url": "",
            "note": "phase 1 DNS gate",
        }
    if access_mode == "blocked-waf-akamai":
        return {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "outcome": "blocked-waf-akamai",
            "evidence_url": "",
            "note": f"govAccess/Akamai CNAME: {rec.get('govaccess_cname', '')}",
        }
    if access_mode in ("blocked-plain-http", "blocked-browser-headers"):
        return {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "outcome": access_mode,
            "evidence_url": "",
            "note": "site never answered in phase 1; a later phase-3 "
            "probe path failing too (cert/connection error) is the "
            "same outcome, not a new one",
        }

    t_rows = targeted.get(domain, [])
    if any(r.get("error") == "challenge-gate" for r in t_rows):
        return {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "outcome": "cloudflare-challenge-blocked",
            "evidence_url": "",
            "note": "challenge-gate seen at a phase-3 fetch",
        }

    return {
        "domain": domain,
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "outcome": "no-platform-link-found",
        "evidence_url": "",
        "note": "phase 1 reached the site; phase 3 (candidates or "
        "fallback ladder) found no real, name-matched platform",
    }


def main() -> None:
    population = load_population()
    recon = load_recon()
    targeted = load_targeted()
    resolved = load_resolve_output()

    rows = [classify(p, recon, targeted, resolved) for p in population]

    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "domain",
                "gov_id",
                "name",
                "state",
                "outcome",
                "evidence_url",
                "note",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    from collections import Counter

    print(f"wrote {REPORT_CSV} ({len(rows)} rows)")
    print("outcome split:")
    for outcome, n in Counter(r["outcome"] for r in rows).most_common():
        print(f"  {outcome}: {n}")


if __name__ == "__main__":
    main()
