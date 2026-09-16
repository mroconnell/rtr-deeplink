#!/usr/bin/env python3
"""WO-327 (2026-09-13): rerun phases 2-3 of the passive-discovery-v2
pipeline on WO-323's 92 Quebec rows, now that the French hop-link
vocabulary (`app/utils/jurisdiction_data/hop_link_weights_fr.csv`) is
wired into `find_hop_links()`.

WO-323 (merged to `main`, #1109) already ran phase 2 (`wo323_classify.py`)
and phase 3 (`wo323_targeted.py`) on these 92 rows and confirmed 0 --
but its phase 2 never passed `gov_id` into `find_hop_links()` at all (so
neither the WO-292 school vocabulary nor this WO's French one was ever
in play for ANY of its 247 rows, not just the Quebec ones -- a real,
separate gap, filed to BACKLOG.md rather than fixed here since fixing it
for the general case is out of this WO's scope).

This script does NOT touch `wo323_classified.csv`/`wo323_targeted.csv`
(WO-323's own committed, historical record) -- it reimplements just the
one line that needed to change (`homepage_candidates_fr()` below, a
near-verbatim copy of `wo323_classify.py`'s `homepage_candidates()` with
`gov_id=` added to the `find_hop_links()` call) and REUSES everything
else by importing it: `wo323_classify.classify_record`'s scoring rules
(via a thin per-row wrapper), and `wo323_targeted.process_with_candidates`
verbatim for phase 3 (real fetch, catch-all test, name-match, YouTube
skip-and-record, portal guard) -- see CLAUDE.md's "never fetch YouTube"
and "one meeting per government" rules, both already enforced inside
`process_with_candidates`.

Two small redirects so this run's writes never land in WO-323's own
files: `PORTAL_GUARD_CSV` -> `wo327_qc_portal_guard.csv` (a different,
WO-327-owned sidecar), and YouTube leads get `source_wo="WO-327"`
(`record_youtube_lead_wo327()` below) instead of WO-323's hardcoded
"WO-323" -- both still write to the SAME shared
`research/youtube_channel_leads.csv`, correctly attributed.

Output: `research/wo327_qc323_reclassified.csv` (phase 2, one row per
government) and `research/wo327_qc323_retargeted.csv` (phase 3, one row
per candidate actually fetched).

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo327_rerun_scratch.db" \\
        .venv/bin/python scripts/wo327_rerun_quebec_phases.py
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import wo147_access_ladder_sweep as w147  # noqa: E402
import wo323_classify as w323c  # noqa: E402
import wo323_targeted as w323t  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo323_recon.jsonl"

# Conductor-flagged bug (2026-09-13): the shared DNS tenant-guess takes
# the second-to-last label of a domain as a guessed vendor subdomain --
# for any `*.qc.ca` government that label is literally "qc", and
# `qc.primegov.com` is a real REGIONAL PrimeGov tenant unrelated to any
# specific municipality. WO-324 saw 66-70 false "confirmations" from
# this on its 258-row Quebec population. Never trusted as evidence here.
QC_PRIMEGOV_HOST = "qc.primegov.com"
_QC_PRIMEGOV_POLLUTED_COUNT = 0

# Redirect phase 3's portal-guard sidecar to a WO-327-owned file --
# never write into WO-323's own wo323_portal_guard_hosts.csv.
w323t.PORTAL_GUARD_CSV = RESEARCH_DIR / "wo327_qc_portal_guard.csv"


def record_youtube_lead_wo327(
    domain: str,
    gov_id: str,
    name: str,
    state: str,
    url: str,
    *,
    source_wo: str = "WO-327",
) -> None:
    """Same as wo323_targeted.record_youtube_lead(), except `source_wo`
    is correctly attributed (WO-327 for the WO-323 rerun, WO-327-for-
    WO-324 for that rerun) instead of WO-323's hardcoded value -- both
    still write to the same shared `research/youtube_channel_leads.csv`,
    same dedupe-by-(url, gov_id) rule, same pinned-handle skip."""
    kind = (
        "channel"
        if any(m in url for m in w323t._YOUTUBE_CHANNEL_PATH_MARKERS)
        else "single_video"
    )
    key = (url, gov_id)
    with w323t._youtube_lead_write_lock:
        pin_key = w323t._youtube_key_from_url(url)
        if pin_key and pin_key in w323t._load_youtube_pinned_handles():
            return
        seen = w323t._load_youtube_leads_seen()
        if key in seen:
            return
        seen.add(key)
        write_header = not w323t.YOUTUBE_LEADS_CSV.exists()
        with open(w323t.YOUTUBE_LEADS_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "channel_url",
                    "gov_id",
                    "government",
                    "state",
                    "source_wo",
                    "kind",
                    "verified",
                    "note",
                ],
            )
            if write_header:
                w.writeheader()
            w.writerow(
                {
                    "channel_url": url,
                    "gov_id": gov_id,
                    "government": name,
                    "state": state,
                    "source_wo": source_wo,
                    "kind": kind,
                    "verified": "false",
                    "note": (
                        "not fetched -- CLAUDE.md's no-YouTube-calls rule "
                        "(Quebec webcasts are drip leads); URL-shape kind guess only"
                    ),
                }
            )


def homepage_candidates_fr(rec: dict) -> tuple[list[dict], str]:
    """Verbatim copy of wo323_classify.homepage_candidates(), with the
    ONE change this WO exists to make: find_hop_links() is called WITH
    gov_id, so a `ca:` row whose page looks French gets the French
    vocabulary (wo147_access_ladder_sweep.looks_french() + the
    hop_link_weights_fr.csv addition to _weights_for_gov()). WO-323's
    own homepage_candidates() never passed gov_id at all -- a separate,
    real gap (filed to BACKLOG.md), not fixed here for the general case."""
    homepage = rec.get("homepage") or {}
    gz_path = homepage.get("homepage_gz_path", "")
    html = w323c.load_homepage_html(gz_path)
    if not html:
        return [], ""

    final_url = homepage.get("final_url") or f"https://{rec.get('domain', '')}/"
    raw_links = homepage.get("links") or []
    position_by_href = {ln["href"]: ln.get("position", "body") for ln in raw_links}

    def source_for(url: str) -> str:
        pos = position_by_href.get(url, "body")
        if pos in ("nav", "menu"):
            return "homepage-nav" if pos == "nav" else "homepage-body"
        if pos == "footer":
            return "homepage-footer"
        return "homepage-body"

    candidates: dict[str, dict] = {}

    ranked = w147.find_hop_links(html, final_url, gov_id=rec.get("gov_id", ""))
    for i, url in enumerate(ranked):
        score = max(1.0, 100.0 - i)
        candidates[url] = {
            "url": url,
            "source": source_for(url),
            "score": score,
            "kind": "platform" if detect_platform(url) != "unknown" else "hub",
        }

    for ln in raw_links:
        url = ln["href"]
        platform = detect_platform(url)
        if platform != "unknown" and url not in candidates:
            candidates[url] = {
                "url": url,
                "source": source_for(url),
                "score": 200.0,
                "kind": "platform",
            }

    builder = ""
    try:
        from platform_fingerprints import classify_site_builder

        result = classify_site_builder(html, url=final_url)
        builder = getattr(result, "family", "") or ""
    except Exception:  # noqa: BLE001
        builder = ""

    return list(candidates.values()), builder


def classify_record_fr(rec: dict) -> dict:
    """Same as wo323_classify.classify_record(), calling
    homepage_candidates_fr() instead of the original. Everything else
    (vendor-host regex, DNS platform, sitemap/archive URL scoring,
    confidence labelling) is unchanged, reused by calling straight
    through to wo323_classify's own module-level functions."""
    domain = rec.get("domain", "")

    if rec.get("dns_gate") == "dns-unresolvable":
        return {
            "domain": domain,
            "gov_id": rec.get("gov_id", ""),
            "name": rec.get("name", ""),
            "state": rec.get("state", ""),
            "population": rec.get("population", ""),
            "group": rec.get("group", ""),
            "platform": "",
            "platform_evidence_url": "",
            "confidence": "none",
            "site_builder": "",
            "catchall_preflag": False,
            "n_candidates": 0,
            "candidates_json": "[]",
            "note": "dns-unresolvable",
        }

    urls = w323c.all_urls_from_record(rec)

    platform, platform_evidence = "", ""
    dns_plat, dns_evidence = w323c.dns_platform(rec)
    if dns_plat and QC_PRIMEGOV_HOST in (dns_evidence or ""):
        # Conductor-flagged real bug (2026-09-13, confirmed live on
        # WO-324's 258-row Quebec run: 66-70 false confirmations): the
        # shared DNS tenant-guess in wo323_recon.py's phase 1 takes the
        # SECOND-TO-LAST label of a government's own domain as a guessed
        # vendor subdomain -- for any `*.qc.ca` domain that label is
        # literally "qc", and `qc.primegov.com` is a REAL regional
        # PrimeGov tenant (unrelated to any specific municipality), so
        # DNS resolving it is not evidence this government uses PrimeGov
        # at all. Never trust it as a platform confirmation. The general
        # fix (don't guess a tenant label off `*.qc.ca`'s own second
        # label) is filed to BACKLOG.md for the small-fixes WO; this is
        # a narrow exclusion for this rerun only.
        global _QC_PRIMEGOV_POLLUTED_COUNT
        _QC_PRIMEGOV_POLLUTED_COUNT += 1
        dns_plat, dns_evidence = "", ""
    if dns_plat:
        platform, platform_evidence = dns_plat, dns_evidence
    else:
        for u in urls:
            if QC_PRIMEGOV_HOST in u:
                continue
            p = w323c.vendor_platform_for_url(u)
            if p:
                platform, platform_evidence = p, u
                break

    all_candidates: dict[str, dict] = {}

    domain_root_url = f"https://{domain}/"
    domain_root_platform = w323c.vendor_platform_for_url(domain_root_url)
    if domain_root_platform:
        if not platform:
            platform, platform_evidence = domain_root_platform, domain_root_url
        all_candidates[domain_root_url] = {
            "url": domain_root_url,
            "source": "vendor-host-domain",
            "score": 500.0,
            "kind": "platform",
        }

    for u in urls:
        hs = w323c.hub_score(u)
        ms = w323c.meeting_score(u)
        best = max(hs, ms)
        if best <= 0:
            continue
        source = "sitemap" if u in (rec.get("sitemap_urls") or []) else "archive"
        all_candidates[u] = {
            "url": u,
            "source": source,
            "score": best,
            "kind": "meeting-detail" if ms >= hs else "hub",
        }

    hp_candidates, site_builder = homepage_candidates_fr(rec)
    for c in hp_candidates:
        existing = all_candidates.get(c["url"])
        if existing is None or c["score"] > existing["score"]:
            all_candidates[c["url"]] = c

    if not platform:
        for c in all_candidates.values():
            if c["kind"] == "platform":
                platform, platform_evidence = detect_platform(c["url"]), c["url"]
                break

    ranked = sorted(all_candidates.values(), key=lambda c: -c["score"])

    if platform:
        confidence = "high"
    elif ranked and ranked[0]["score"] >= 20:
        confidence = "medium"
    elif ranked:
        confidence = "low"
    else:
        confidence = "none"

    link_count = (rec.get("homepage") or {}).get("link_count", 0)
    catchall_preflag = bool(
        (rec.get("homepage") or {}).get("fetched")
        and link_count < w323c.CATCHALL_PREFLAG_LINK_FLOOR
    )

    return {
        "domain": domain,
        "gov_id": rec.get("gov_id", ""),
        "name": rec.get("name", ""),
        "state": rec.get("state", ""),
        "population": rec.get("population", ""),
        "group": rec.get("group", ""),
        "platform": platform,
        "platform_evidence_url": platform_evidence,
        "confidence": confidence,
        "site_builder": site_builder,
        "catchall_preflag": catchall_preflag,
        "n_candidates": len(ranked),
        "candidates_json": json.dumps(ranked[:5]),
        "note": "",
    }


def load_quebec_recon(recon_path: Path = RECON_JSONL) -> list[dict]:
    rows = []
    with open(recon_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("state") == "Quebec":
                rows.append(r)
    return rows


CLASSIFIED_FIELDS = [
    "domain",
    "gov_id",
    "name",
    "state",
    "population",
    "group",
    "platform",
    "platform_evidence_url",
    "confidence",
    "site_builder",
    "catchall_preflag",
    "n_candidates",
    "candidates_json",
    "note",
]

TARGETED_FIELDS = [
    "domain",
    "gov_id",
    "url",
    "rank",
    "source",
    "source_kind",
    "source_score",
    "fetch_method",
    "http_status",
    "body_len",
    "catchall_confirmed",
    "platform_confirmed",
    "platform_signal",
    "name_match",
    "fallback_rung",
    "error",
    "timing_ms",
]


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recon-jsonl",
        default=str(RECON_JSONL),
        help="Phase-1 recon file to read Quebec rows from (default: wo323_recon.jsonl)",
    )
    parser.add_argument(
        "--out-prefix",
        default="wo327_qc323",
        help="Output filename prefix (default: wo327_qc323 -- WO-323's 92 rows)",
    )
    parser.add_argument(
        "--source-wo",
        default="WO-327",
        help="Attribution written into youtube_channel_leads.csv's source_wo column",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop phase 3 after this many governments (0 = no limit, resumable via --skip)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Skip this many governments before starting phase 3 (resume point)",
    )
    args = parser.parse_args()

    recon_path = Path(args.recon_jsonl)
    reclassified_csv = RESEARCH_DIR / f"{args.out_prefix}_reclassified.csv"
    retargeted_csv = RESEARCH_DIR / f"{args.out_prefix}_retargeted.csv"
    w323t.PORTAL_GUARD_CSV = RESEARCH_DIR / f"{args.out_prefix}_portal_guard.csv"

    def _record_lead(domain, gov_id, name, state, url, _source_wo=args.source_wo):
        record_youtube_lead_wo327(
            domain, gov_id, name, state, url, source_wo=_source_wo
        )

    w323t.record_youtube_lead = _record_lead

    print(f"=== Phase 2: reclassify (offline, no network) -- {recon_path} ===")
    recon_rows = load_quebec_recon(recon_path)
    print(f"{len(recon_rows)} Quebec recon rows")

    reclassified = []
    for rec in recon_rows:
        new_row = classify_record_fr(rec)
        reclassified.append(new_row)

    with open(reclassified_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CLASSIFIED_FIELDS)
        w.writeheader()
        w.writerows(reclassified)
    print(f"wrote {len(reclassified)} rows to {reclassified_csv}")

    from collections import Counter

    conf_counts = Counter(r["confidence"] for r in reclassified)
    print(f"confidence distribution: {dict(conf_counts)}")
    print(
        f"qc.primegov.com false-tenant-guess rows excluded from platform "
        f"confirmation: {_QC_PRIMEGOV_POLLUTED_COUNT}"
    )

    print("\n=== Phase 3: targeted fetches (live, polite) ===")
    fetchable = [r for r in reclassified if r["n_candidates"] > 0]
    print(f"{len(fetchable)} of {len(reclassified)} rows have at least one candidate")

    if args.skip:
        fetchable = fetchable[args.skip :]
        print(f"resuming: skipped {args.skip}, {len(fetchable)} remain")
    if args.limit:
        fetchable = fetchable[: args.limit]
        print(f"limiting this run to {len(fetchable)} governments")

    # Resumable: append mode when a --skip is given (continuing a prior
    # partial run), fresh file otherwise.
    write_header = not (args.skip and retargeted_csv.exists())
    mode = "a" if (args.skip and retargeted_csv.exists()) else "w"

    all_results = []
    t_start = time.monotonic()
    with open(retargeted_csv, mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TARGETED_FIELDS)
        if write_header:
            w.writeheader()
        for i, row in enumerate(fetchable):
            results = w323t.process_with_candidates(row)
            all_results.extend(results)
            for r in results:
                w.writerow({k: r.get(k, "") for k in TARGETED_FIELDS})
            f.flush()
            if (i + 1) % 10 == 0:
                elapsed = time.monotonic() - t_start
                print(
                    f"  {i + 1}/{len(fetchable)} governments processed "
                    f"({elapsed:.0f}s elapsed)"
                )
    print(f"wrote {len(all_results)} candidate-fetch rows to {retargeted_csv}")

    confirmed_govs = {
        r["domain"]
        for r in all_results
        if r.get("platform_confirmed") and not r.get("catchall_confirmed")
    }
    print(f"\ngovernments with a platform CONFIRMED this run: {len(confirmed_govs)}")
    for d in sorted(confirmed_govs):
        print(f"  {d}")


if __name__ == "__main__":
    main()
