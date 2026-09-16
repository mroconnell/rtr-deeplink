#!/usr/bin/env python3
"""WO-327 (2026-09-13): re-derive the vendor-tenant DNS guess for the
Quebec rows this WO's own rerun had to hand-exclude, now that WO-328
(merged to `main`, #1111) fixed `registrable_label()` upstream.

Why this exists, separate from just re-running with the hand-exclusion
removed: the hand-exclusion (in `wo327_rerun_quebec_phases.py`, this
WO's own guard added BEFORE WO-328 landed) only discards a false
`qc.primegov.com` hit -- it does not ask the RIGHT question, which is
"what does `mirabel.primegov.com` (or `mirabel.civicweb.net`) actually
resolve to?" That DNS query was never made by WO-323's original phase 1
recon (it only ever guessed "qc"), so the frozen `wo323_recon.jsonl`/
`wo324_recon.jsonl` files have no data for it at all -- this script
makes that one cheap, additional DNS query per affected government
(2 vendor templates x 2 record types = 4 `dig` calls, no HTTP fetch) and
patches ONLY the `dns.resolving_vendor_labels` field of the affected
rows in memory before re-running phase 2/3, exactly the two rung
`wo273_recon.dns_lookup()` itself would have run under the fixed code.

Input: the RAW phase-1 recon.jsonl (`find_polluted_domains()` reads
`dns.resolving_vendor_labels` directly -- NOT a prior reclassified CSV,
which already has the hand-exclusion applied and so never shows a
qc.primegov.com hit at all; real bug caught testing this script before
it was fixed to read raw recon instead).

Output: `<out-prefix>_reclassified.csv` / `<out-prefix>_retargeted.csv`,
covering ONLY the affected domains -- meant to be read ALONGSIDE the
original rerun's output, not to replace it (the unaffected majority of
rows are unchanged and not worth re-fetching).

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo327_refix_scratch.db" \\
        .venv/bin/python scripts/wo327_refix_qc_primegov.py \\
        --recon-jsonl ~/Documents/rtr-business/research/wo323_recon.jsonl \\
        --out-prefix wo327_qc323_refixed
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import wo273_recon as w273  # noqa: E402
import wo323_targeted as w323t  # noqa: E402
from wo327_rerun_quebec_phases import (  # noqa: E402
    CLASSIFIED_FIELDS,
    QC_PRIMEGOV_HOST,
    TARGETED_FIELDS,
    classify_record_fr,
    record_youtube_lead_wo327,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"


def refresh_vendor_labels(domain: str) -> list[dict]:
    """Redoes ONLY the vendor-tenant-label half of wo273_recon.dns_lookup()
    for one domain, using the FIXED registrable_label()/label_is_guessable()
    (WO-328). Cheap: at most 2 templates x 2 dig() calls."""
    label = w273.registrable_label(domain)
    out = []
    for template, platform in w273.VENDOR_LABEL_TEMPLATES:
        if not w273.label_is_guessable(label):
            break
        host = template.format(label=label)
        a = w273.dig("A", host)
        cname = (w273.dig("CNAME", host) or [""])[0]
        if a or cname:
            out.append({"host": host, "platform": platform, "a": a, "cname": cname})
    return out


def find_polluted_domains(recon_jsonl: Path) -> list[str]:
    """Scans the RAW phase-1 recon file for `qc.primegov.com` in
    `dns.resolving_vendor_labels` -- NOT the prior reclassified CSV,
    which already has the hand-exclusion applied (`wo327_rerun_quebec_
    phases.classify_record_fr()` never lets a qc.primegov.com hit reach
    `candidates_json`/`platform_evidence_url` in the first place, so
    searching that output finds nothing; real bug caught testing this
    script -- see the module's own reasoning for reading raw recon
    instead)."""
    domains = []
    with open(recon_jsonl, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            labels = (rec.get("dns") or {}).get("resolving_vendor_labels") or []
            if any(v.get("host") == QC_PRIMEGOV_HOST for v in labels):
                domains.append(rec["domain"])
    return domains


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recon-jsonl", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--source-wo", default="WO-327")
    args = parser.parse_args()

    polluted_domains = set(find_polluted_domains(Path(args.recon_jsonl)))
    print(
        f"{len(polluted_domains)} domains hit qc.primegov.com in the raw phase-1 recon"
    )

    recon_by_domain = {}
    with open(args.recon_jsonl, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["domain"] in polluted_domains:
                recon_by_domain[r["domain"]] = r

    print(
        "Re-querying DNS with the fixed registrable_label() (cheap, no HTTP fetch)..."
    )
    label_changes = 0
    for domain, rec in recon_by_domain.items():
        old_label = "qc"  # every one of these hit qc.primegov.com by construction
        new_labels = refresh_vendor_labels(domain)
        new_label = w273.registrable_label(domain)
        rec.setdefault("dns", {})["resolving_vendor_labels"] = new_labels
        if new_label != old_label:
            label_changes += 1
        found = ", ".join(f"{v['host']}" for v in new_labels) or "(nothing resolves)"
        print(f"  {domain}: label {old_label!r} -> {new_label!r}; {found}")
    print(
        f"{label_changes} of {len(recon_by_domain)} domains got a DIFFERENT "
        f"real label under the fix (the rest still resolve to nothing under "
        f"either template, or are unaffected)"
    )

    reclassified = [classify_record_fr(rec) for rec in recon_by_domain.values()]
    reclassified_csv = RESEARCH_DIR / f"{args.out_prefix}_reclassified.csv"
    with open(reclassified_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CLASSIFIED_FIELDS)
        w.writeheader()
        w.writerows(reclassified)
    print(f"wrote {len(reclassified)} rows to {reclassified_csv}")

    from collections import Counter

    print(
        f"confidence distribution (refixed): {dict(Counter(r['confidence'] for r in reclassified))}"
    )

    w323t.PORTAL_GUARD_CSV = RESEARCH_DIR / f"{args.out_prefix}_portal_guard.csv"

    def _record_lead(domain, gov_id, name, state, url, _source_wo=args.source_wo):
        record_youtube_lead_wo327(
            domain, gov_id, name, state, url, source_wo=_source_wo
        )

    w323t.record_youtube_lead = _record_lead

    fetchable = [r for r in reclassified if r["n_candidates"] > 0]
    print(
        f"\n{len(fetchable)} of {len(reclassified)} refixed rows have a candidate; fetching..."
    )

    retargeted_csv = RESEARCH_DIR / f"{args.out_prefix}_retargeted.csv"
    all_results = []
    t0 = time.monotonic()
    with open(retargeted_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TARGETED_FIELDS)
        w.writeheader()
        for i, row in enumerate(fetchable):
            results = w323t.process_with_candidates(row)
            all_results.extend(results)
            for r in results:
                w.writerow({k: r.get(k, "") for k in TARGETED_FIELDS})
            f.flush()
            if (i + 1) % 5 == 0:
                print(
                    f"  {i + 1}/{len(fetchable)} ({time.monotonic() - t0:.0f}s elapsed)"
                )
    print(f"wrote {len(all_results)} candidate-fetch rows to {retargeted_csv}")

    confirmed = {
        r["domain"]
        for r in all_results
        if r.get("platform_confirmed") and not r.get("catchall_confirmed")
    }
    print(f"\nconfirmed after refix: {len(confirmed)}")
    for d in sorted(confirmed):
        print(f"  {d}")


if __name__ == "__main__":
    main()
