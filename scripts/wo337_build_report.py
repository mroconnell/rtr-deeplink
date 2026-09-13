#!/usr/bin/env python3
"""WO-337: build `research/wo337_report.csv`, one row per government,
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
    .venv/bin/python scripts/wo337_build_report.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo337_recon.jsonl"
CLASSIFIED_CSV = RESEARCH_DIR / "wo337_classified.csv"
TARGETED_CSV = RESEARCH_DIR / "wo337_targeted.csv"
GOVACCESS_DEFERRED_CSV = RESEARCH_DIR / "wo337_govaccess_deferred.csv"
REPORT_CSV = RESEARCH_DIR / "wo337_report.csv"
POPULATION_CSV = RESEARCH_DIR / "wo337_population.csv"

# WO-337-specific fix, found live 2026-09-13: this population has 6 real
# `domain` values shared by more than one distinct government (54 rows
# alone share `local.wv.gov` -- confirmed: 54 different real West
# Virginia towns/cities, not a data error in the usual sense, just no
# per-government website on file, so an earlier enumeration pass filled
# in the same statewide portal placeholder for every one of them; the
# other 5 dupes are 2-3-way each, some a real shared site for a
# town+village pair, some a small multi-tenant community portal). Phase
# 1/2/3 all key their output by `domain` (one fetch per unique domain,
# correctly -- no reason to fetch the same URL 54 times), but the
# original WO-32x `build_report.py` this script was copied from then
# iterated `set(recon) | set(classified)` -- domains, not governments --
# which silently collapsed all 54 WV rows into ONE report row and lost
# 53 real governments' gov_id/name entirely. Confirmed live: only 1 of
# 54 local.wv.gov rows ended up in `wo337_recon.jsonl` after the full
# phase-1 sweep, because the domain-level "already done" resume check
# treated every later same-domain government as already handled. Fixed
# here by iterating the POPULATION file's own rows (one row per
# government, duplicates and all) and joining each one's `domain` into
# the shared recon/classified/targeted-best lookups -- every government
# that shares a domain with another now gets its own report row, all
# pointing at the same fetched evidence, which the hand-check step (not
# this offline report) is what actually decides whether that evidence is
# really about THIS government or a different one on the same domain.

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
    "shared_domain_primary",
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


def load_population_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    recon = load_jsonl(RECON_JSONL)
    classified = load_csv_by_domain(CLASSIFIED_CSV)
    targeted_best = load_targeted_best(TARGETED_CSV)
    govaccess = load_csv_by_domain(GOVACCESS_DEFERRED_CSV)
    population = load_population_rows(POPULATION_CSV)

    seen_domains_only_in_recon_or_classified = (set(recon) | set(classified)) - {
        r["domain"] for r in population
    }
    if seen_domains_only_in_recon_or_classified:
        print(
            f"WARNING: {len(seen_domains_only_in_recon_or_classified)} domains in "
            "recon/classified are not in the population file (stale run?): "
            f"{sorted(seen_domains_only_in_recon_or_classified)[:10]}"
        )

    from collections import Counter as _Counter

    domain_counts = _Counter(r["domain"] for r in population)

    rows = []
    for pop_row in population:
        domain = pop_row["domain"]
        rec = recon.get(domain, {})
        cls = classified.get(domain, {})
        tgt = targeted_best.get(domain, {})

        dns_gate = rec.get("dns_gate", "")
        access_mode = rec.get("access_mode", "")

        platform_confirmed = tgt.get("platform_confirmed", "")
        name_match = tgt.get("name_match", "")
        catchall = tgt.get("catchall_confirmed", "")
        fallback_rung = tgt.get("fallback_rung", "")

        # WO-337 fix (see module docstring): when a domain is shared by
        # more than one government, only the ONE government whose own
        # gov_id matches what phase 1 actually recorded for that domain
        # (`rec.get("gov_id")`) has evidence that was ever scored
        # against ITS OWN name/state. Every other government sharing the
        # domain gets its own report row (so it's never silently
        # dropped) but its outcome is forced to
        # "shared-domain-not-verified" regardless of what the shared
        # fetch found -- a platform_confirmed=True on the primary row
        # says nothing about whether that same page is really about a
        # DIFFERENT government on the same domain, and copying it over
        # would be exactly the kind of unverified claim the hand-check
        # rule exists to prevent.
        is_shared_domain = domain_counts.get(domain, 1) > 1
        rec_gov_id = rec.get("gov_id", "")
        is_primary = (not is_shared_domain) or (
            rec_gov_id and rec_gov_id == pop_row.get("gov_id", "")
        )

        if not is_primary:
            outcome = "shared-domain-not-verified"
        elif domain in govaccess:
            outcome = "blocked-waf-akamai-deferred"
        elif dns_gate == "dns-unresolvable":
            outcome = "dns-unresolvable"
        elif not rec and not cls:
            outcome = "not-yet-processed"
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
                # gov_id/name/state/population come from the POPULATION
                # row itself, never from recon/classified -- those are
                # keyed by domain and, for a shared domain, only ever
                # hold ONE government's identity fields (whichever
                # government's row happened to be fetched), which would
                # silently mislabel every other government on that
                # domain if used here.
                "gov_id": pop_row.get("gov_id", ""),
                "name": pop_row.get("name", ""),
                "state": pop_row.get("state", ""),
                "population": pop_row.get("population", ""),
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
                "shared_domain_primary": is_primary,
            }
        )

    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {REPORT_CSV} ({len(rows)} rows)")

    from collections import Counter

    print("outcome split:", Counter(r["outcome"] for r in rows))
    dup_domains = Counter(r["domain"] for r in rows)
    shared = {d: n for d, n in dup_domains.items() if n > 1}
    print(f"domains shared by >1 government: {len(shared)} -- {shared}")


if __name__ == "__main__":
    main()
