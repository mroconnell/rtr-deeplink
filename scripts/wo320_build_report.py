#!/usr/bin/env python3
"""WO-320: build `research/wo320_report.csv`, one row per government,
from phase 1's recon file, phase 2's classification, and phase 3's
targeted-fetch results -- the per-government report the preamble's
"Finish (every WO)" step asks every WO to leave behind.

Offline, idempotent (rewrites the file fresh from the three inputs each
run -- cheap, no network I/O), and safe to run at any point mid-sweep to
see where things stand.

For each government, picks the single BEST targeted-phase result (by
rank ascending, preferring platform_confirmed=True, then name_match=True,
then lowest fallback_rung) as `best_url`/`best_outcome`.

Usage:
    .venv/bin/python scripts/wo320_build_report.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo320_recon.jsonl"
CLASSIFIED_CSV = RESEARCH_DIR / "wo320_classified.csv"
TARGETED_CSV = RESEARCH_DIR / "wo320_targeted.csv"
GOVACCESS_DEFERRED_CSV = RESEARCH_DIR / "wo320_govaccess_deferred.csv"
REPORT_CSV = RESEARCH_DIR / "wo320_report.csv"

FIELDNAMES = [
    "domain",
    "gov_id",
    "name",
    "state",
    "population",
    "dns_gate",
    "access_mode",
    "confidence",
    "platform",
    "n_candidates",
    "best_url",
    "best_source",
    "platform_confirmed",
    "name_match",
    "catchall_confirmed",
    "fallback_rung",
    "outcome",
]


def load_jsonl(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            out[rec.get("domain", "")] = rec
    return out


def load_csv_by_domain(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row.get("domain", "")] = row
    return out


def load_targeted_best(path: Path) -> dict:
    """One best row per domain from the (domain, url) rows targeted.csv
    holds -- prefers a real platform confirmation, then a name match,
    then the lowest fallback_rung (0 = a top-5 classified candidate,
    ranked ahead of any fallback-ladder rung)."""
    best: dict[str, dict] = {}
    if not path.exists():
        return best
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domain = row.get("domain", "")
            if not domain:
                continue
            existing = best.get(domain)

            def score(r):
                return (
                    r.get("platform_confirmed") not in ("", "False", None),
                    r.get("name_match") in ("True", True),
                    -int(r.get("fallback_rung") or 0),
                    -int(r.get("rank") or 99),
                )

            if existing is None or score(row) > score(existing):
                best[domain] = row
    return best


def main() -> None:
    recon = load_jsonl(RECON_JSONL)
    classified = load_csv_by_domain(CLASSIFIED_CSV)
    targeted_best = load_targeted_best(TARGETED_CSV)
    govaccess = load_csv_by_domain(GOVACCESS_DEFERRED_CSV)

    domains = set(recon) | set(classified)
    rows = []
    for domain in sorted(domains):
        rec = recon.get(domain, {})
        cls = classified.get(domain, {})
        tgt = targeted_best.get(domain, {})

        dns_gate = rec.get("dns_gate", "")
        access_mode = rec.get("access_mode", "")

        platform_confirmed = tgt.get("platform_confirmed", "")
        name_match = tgt.get("name_match", "")
        catchall = tgt.get("catchall_confirmed", "")
        fallback_rung = tgt.get("fallback_rung", "")

        if domain in govaccess:
            outcome = "blocked-waf-akamai-deferred"
        elif dns_gate == "dns-unresolvable":
            outcome = "dns-unresolvable"
        elif platform_confirmed:
            outcome = "platform-confirmed"
        elif tgt.get("error", "").startswith("third-party-portal-guard"):
            outcome = "third-party-portal-guard"
        elif cls.get("n_candidates") == "0" or not cls.get("n_candidates"):
            outcome = "no-candidate"
        else:
            outcome = "candidate-not-confirmed"

        rows.append(
            {
                "domain": domain,
                "gov_id": rec.get("gov_id") or cls.get("gov_id", ""),
                "name": rec.get("name") or cls.get("name", ""),
                "state": rec.get("state") or cls.get("state", ""),
                "population": rec.get("population") or cls.get("population", ""),
                "dns_gate": dns_gate,
                "access_mode": access_mode,
                "confidence": cls.get("confidence", ""),
                "platform": cls.get("platform", ""),
                "n_candidates": cls.get("n_candidates", ""),
                "best_url": tgt.get("url", ""),
                "best_source": tgt.get("source", ""),
                "platform_confirmed": platform_confirmed,
                "name_match": name_match,
                "catchall_confirmed": catchall,
                "fallback_rung": fallback_rung,
                "outcome": outcome,
            }
        )

    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {REPORT_CSV} ({len(rows)} rows)")

    from collections import Counter

    print("outcome split:", Counter(r["outcome"] for r in rows))


if __name__ == "__main__":
    main()
