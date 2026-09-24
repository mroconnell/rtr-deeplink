"""WO-1043: send Meeting Finder's unfinished governments to the drains,
and bring the drains' finds back into Meeting Finder.

BACKLOG.md's "Meeting Finder follow-up plumbing" entry names the gap this
closes: Meeting Finder (`docs/MEETING_FINDER.md`) ends at a read-only
Verdict row and never talks to the slow follow-up queues -- the
certificate-log + Common Crawl drains (`queue_pipeline.py`'s `drain2`/
`drain3`, in rtr-business `research/dns_ctlog_sweep_2026-09-17/`). This
script is the plumbing in both directions:

  1. `to-drains` reads one or more Meeting Finder `verdicts.csv.jsonl`
     files (`app/platforms/meeting_finder/verdict.py`'s own JSONL shape)
     and picks the rows whose `outcome` means "nothing usable found, and
     the government's own site has nothing left to try" -- see
     `DIRECT_OUTCOMES`/`is_drain_outcome()` below. It writes one row per
     government in `queue_pipeline.py feed`'s own INPUT format: a
     `wo282_recon.jsonl`-shaped record. `feed` classifies every record it
     reads with `wo282_classify.classify_record()` and queues it for the
     drains only when that comes back with no platform and "none"/"low"
     confidence (`queue_pipeline.is_failure()`). A bare record carrying
     none of `classify_record()`'s optional fields (`sitemap_urls`,
     `wayback_index`, `common_crawl`, `homepage`, `dns`) always scores
     that way -- every one of those fields is read with `rec.get(...)`
     and defaults to nothing found, confirmed by reading
     `scripts/wo282_classify.py` directly rather than assumed. That is
     the right classification here regardless: Meeting Finder already
     tried harder than the passive pipe that classifier was built for and
     still failed, so there is nothing more to feed it. A
     `dns-unresolvable` verdict also sets `dns_gate` on the emitted row,
     which short-circuits `classify_record()` straight to that same
     "none" confidence without even reaching the optional-field checks --
     see that function's own first branch.

  2. `from-drains` reads a `drain2` results file (the JSON array
     `queue_pipeline.py`'s `cmd_drain2()` writes to `results_stage2.json`,
     one entry per government with a `resolutions` list) and a `drain3`
     results file (the JSONL `cmd_drain3()` appends to
     `results_stage3.jsonl`, one line per subdomain with `hub_hits`) and
     writes Meeting Finder input rows (`url,gov_id,url_source,entry,mode`
     -- `scripts/meeting_finder.py`'s own `_read_inputs()` column set) for
     the new subdomains/vendor accounts they found. `url_source` is
     always `own-site` (docs/MEETING_FINDER.md's Pin/audit section:
     identity only carries over along a path that started on the
     government's own site, and everything the drains find is a
     government-owned host, never a directory or a guess). `entry` is
     `identify` when the drain already confirmed a real vendor account
     (a CNAME match, or a `platform_hits` hit with a real adapter --
     Identify can start from a known platform), or `start` when it's only
     a keyword-shaped subdomain with nothing confirmed yet (needs the
     full Start walk).

Both directions are pure local file-to-file transforms -- this script
makes no network requests itself (CLAUDE.md's "we query sites politely"
rule: the drains do their own fetching, at their own pace, and re-running
this script never sends a second request anywhere).

Usage:

    python scripts/meeting_finder_to_drains.py to-drains \\
        --verdicts-jsonl overnight/verdicts.csv.jsonl \\
        --verdicts-jsonl overnight2/verdicts.csv.jsonl \\
        --out followup/drains/queue_pipeline_feed_input.jsonl \\
        --summary followup/drains/summary.md

    # then, on the machine that owns the rtr-business checkout:
    #   python queue_pipeline.py feed --recon <the file above written by to-drains>
    #   python queue_pipeline.py drain2 --wait-for-feeder
    #   python queue_pipeline.py drain3 --wait-for-stage2

    python scripts/meeting_finder_to_drains.py from-drains \\
        --stage2-results queue/results_stage2.json \\
        --stage3-results queue/results_stage3.jsonl \\
        --out followup/drains/meeting_finder_input.csv \\
        --summary followup/drains/from_drains_summary.md
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------- #
# to-drains: Meeting Finder verdicts -> queue_pipeline.py feed's input   #
# --------------------------------------------------------------------- #

# Outcomes spelled with a fixed name in app/platforms/meeting_finder/
# models.py -- confirmed by reading that file, not guessed. A
# "blocked-*" outcome (blocked-plain-http, blocked-browser-headers,
# blocked-waf-akamai, blocked-headless -- the last two are literal
# strings in fetch.py, never promoted to a models.py constant) is matched
# by prefix instead of listed here one by one, so a future blocked-*
# variant is picked up without editing this set.
DIRECT_OUTCOMES = {
    "no-meeting-nor-video",
    "cloudflare-challenge-blocked",
    "dns-unresolvable",
    "timeout",
    "internal-timeout",
    "account-not-found",
}


def is_drain_outcome(outcome: Optional[str]) -> bool:
    """True for a verdict outcome that means "nothing usable found, and
    the government's own site has nothing left to try" -- the population
    WO-1043 sends to the certificate-log/Common Crawl drains."""
    if not outcome:
        return False
    return outcome in DIRECT_OUTCOMES or outcome.startswith("blocked-")


def domain_from_url(url: str) -> str:
    """A bare, lowercase, www-stripped domain from a Meeting Finder
    `input_url` -- which is often already a bare domain (confirmed in
    the sample verdicts.csv.jsonl files: `"input_url": "elkcounty.org"`),
    but urlparse needs a scheme to put it in `.netloc` rather than
    `.path`."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    host = host.split("@")[-1].split(":")[0]  # drop userinfo/port, if any
    return host[4:] if host.startswith("www.") else host


def load_verdicts_jsonl(paths: Iterable[Path]) -> List[dict]:
    rows: List[dict] = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a torn last line from a killed writer
    return rows


def verdict_to_recon_row(verdict: dict, domain: str) -> dict:
    """One `wo282_recon.jsonl`-shaped record -- see this module's
    docstring for why a bare record like this always classifies as a
    drain-queue failure. `identity_expected_gov_id` is the verdict row's
    own gov_id field (there is no plain `gov_id` key in a Meeting Finder
    verdict row -- confirmed against the real sample files)."""
    row = {
        "gov_id": verdict.get("identity_expected_gov_id") or "",
        "domain": domain,
        "meeting_finder_outcome": verdict.get("outcome") or "",
        "meeting_finder_try_next": verdict.get("try_next") or "",
        "meeting_finder_run_id": verdict.get("run_id") or "",
        "meeting_finder_input_url": verdict.get("input_url") or "",
    }
    if verdict.get("outcome") == "dns-unresolvable":
        row["dns_gate"] = "dns-unresolvable"
    return row


def build_drain_feed(
    verdict_rows: Iterable[dict],
) -> Tuple[List[dict], Dict[str, int], int]:
    """Returns (recon_rows, counts_by_outcome, skipped_no_domain).

    One row per government: the same domain can appear in more than one
    input file (e.g. a government retried across two overnight runs), and
    the last verdict read wins, since a later run's verdict is the more
    current one. `counts_by_outcome` counts every MATCHING verdict row
    seen (before this dedupe), so the summary reports what was actually
    found in the inputs, not just what survived deduping."""
    by_domain: Dict[str, dict] = {}
    counts: Dict[str, int] = {}
    skipped_no_domain = 0
    for verdict in verdict_rows:
        outcome = verdict.get("outcome")
        if not is_drain_outcome(outcome):
            continue
        counts[outcome] = counts.get(outcome, 0) + 1
        domain = domain_from_url(verdict.get("input_url", ""))
        if not domain:
            skipped_no_domain += 1
            continue
        by_domain[domain] = verdict_to_recon_row(verdict, domain)
    return list(by_domain.values()), counts, skipped_no_domain


def write_recon_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def write_to_drains_summary(
    path: Path,
    *,
    counts_by_outcome: Dict[str, int],
    matched_rows: int,
    governments_written: int,
    skipped_no_domain: int,
    inputs: List[Path],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WO-1043: Meeting Finder -> drains feed, dry-run summary\n",
        "Purpose: pick Meeting Finder's unfinished governments (no meeting or "
        "video found, or the government's own site had nothing left to try) "
        "and write them in queue_pipeline.py feed's own input format, so the "
        "certificate-log and Common Crawl drains can look for their vendor "
        "account without ever touching the blocked or empty site again.\n",
        "Verdict files read: " + ", ".join(str(p) for p in inputs) + "\n",
        "## Result | Count of matching verdict rows\n",
        "| Outcome | Count |",
        "|---|---|",
    ]
    for outcome in sorted(counts_by_outcome):
        lines.append(f"| {outcome} | {counts_by_outcome[outcome]} |")
    lines.append(f"| **Total matching rows** | **{matched_rows}** |\n")
    lines.append("## Result | Count\n")
    lines.append("| Result | Count |")
    lines.append("|---|---|")
    lines.append(f"| Governments written (deduped by domain) | {governments_written} |")
    lines.append(
        f"| Matching rows with no usable domain (skipped) | {skipped_no_domain} |"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------- #
# from-drains: drain2/drain3 result files -> Meeting Finder input rows  #
# --------------------------------------------------------------------- #

# Duplicated, deliberately, from rtr-business
# `research/dns_ctlog_sweep_2026-09-17/queue_pipeline.py`'s own
# `interesting_subdomains()` -- that file lives in a sibling repo this
# one's CI never checks out, so it can't be imported, only read (per this
# WO's brief: "READ ONLY; never edit or commit rtr-business -- agents
# can't; the conductor applies"). Same "duplicated here deliberately,
# small enough to keep in sync by inspection" pattern
# `scripts/wo282_classify.py`'s own `dns_platform()` already uses for a
# comparable cross-file duplication. Keep this in sync BY HAND if
# `queue_pipeline.py`'s vocabulary ever changes.
KEYWORD_SUBSTRINGS = (
    "video",
    "media",
    "stream",
    "webcast",
    "agenda",
    "meeting",
    "council",
    "cablecast",
    "gallery",
    "granicus",
    "legistar",
)
KEYWORD_TOKENS = {"vod", "live", "tv", "watch", "channel", "boardroom"}
NOISE = (
    "airwatch",
    "vpn",
    "vcenter",
    "exchange",
    "mdm",
    "sso",
    "autodiscover",
    "lyncdiscover",
    "enterprise",
    "helpdesk",
    "dashboard",
    "cybersafe",
    "smtp",
    "webmail",
    "owa",
    "citrix",
    "globalprotect",
    "mobile",
    "gisopendata",
    "gis",
)

MF_INPUT_FIELDNAMES = ["url", "gov_id", "url_source", "entry", "mode"]


def _subdomain_label(host: str, apex: str) -> str:
    return host[: -(len(apex) + 1)] if apex and host.endswith("." + apex) else host


def resolution_is_interesting(resolution: dict, apex: str) -> bool:
    """Mirrors `queue_pipeline.interesting_subdomains()`'s per-resolution
    test: did it resolve at all, and (a real vendor CNAME match, or does
    its own label read like a meeting/video host)?"""
    if not resolution.get("chain"):
        return False
    if resolution.get("vendor_match"):
        return True
    label = _subdomain_label(resolution.get("subdomain") or "", apex).lower()
    if any(n in label for n in NOISE):
        return False
    tokens = set(re.split(r"[.\-_0-9]+", label))
    return (
        any(k in label for k in KEYWORD_SUBSTRINGS)
        or bool(tokens & KEYWORD_TOKENS)
        or label.endswith("vod")
    )


def resolution_vendor_confirmed(resolution: dict) -> bool:
    """True when a resolution is more than a keyword guess: a real
    vendor-suffix CNAME match, or a `platform_hits` entry backed by a
    real adapter (`supported: True`)."""
    if resolution.get("vendor_match"):
        return True
    return any(hit.get("supported") for hit in resolution.get("platform_hits") or [])


def mf_row(url: str, gov_id: str, entry: str) -> dict:
    return {
        "url": url,
        "gov_id": gov_id or "",
        "url_source": "own-site",
        "entry": entry,
        "mode": "pin",
    }


def load_stage2_results(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_stage3_results(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def stage2_rows_to_mf(entries: Iterable[dict]) -> List[dict]:
    """A row per interesting, resolving subdomain each drain2 entry
    found. `entry` is "identify" once a real vendor account is confirmed
    (Identify can start straight from a known platform), or "start" for a
    keyword-shaped subdomain nothing has confirmed yet."""
    rows = []
    for gov_entry in entries:
        apex = (gov_entry.get("domain") or "").strip().lower()
        gov_id = gov_entry.get("gov_id") or ""
        for resolution in gov_entry.get("resolutions") or []:
            if not resolution_is_interesting(resolution, apex):
                continue
            host = resolution.get("subdomain")
            if not host:
                continue
            entry_phase = (
                "identify" if resolution_vendor_confirmed(resolution) else "start"
            )
            rows.append(mf_row(f"https://{host}/", gov_id, entry_phase))
    return rows


def stage3_rows_to_mf(results: Iterable[dict]) -> List[dict]:
    """A row per real page drain3's Common Crawl seek found on an
    already-interesting subdomain (`hub_hits`), or, when it found no
    page but the subdomain was already a confirmed vendor CNAME
    (`reason == "vendor-cname"`), a row for the subdomain root itself --
    still a new starting point worth trying even without a Common Crawl
    hit. A keyword-only subdomain (`reason == "keyword"`) with no
    `hub_hits` has nothing new to offer here; drain2 already sent it to
    Meeting Finder's `start` entry on its own."""
    rows = []
    for result in results:
        if not result.get("query_ok"):
            continue
        gov_id = result.get("gov_id") or ""
        vendor_confirmed = result.get("reason") == "vendor-cname"
        entry_phase = "identify" if vendor_confirmed else "start"
        hub_hits = result.get("hub_hits") or []
        if hub_hits:
            seen_urls = set()
            for hit in hub_hits:
                url = hit.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                rows.append(mf_row(url, gov_id, entry_phase))
        elif vendor_confirmed:
            subdomain = result.get("subdomain")
            if subdomain:
                rows.append(mf_row(f"https://{subdomain}/", gov_id, entry_phase))
    return rows


def dedupe_mf_rows(rows: Iterable[dict]) -> List[dict]:
    """One row per URL. When the same URL shows up as both "start" and
    "identify" (e.g. drain2's resolution and drain3's vendor-cname-but-
    no-hub-hit fallback both proposed the bare subdomain root), keep
    "identify" -- it's the stronger, vendor-confirmed claim."""
    by_url: Dict[str, dict] = {}
    for row in rows:
        existing = by_url.get(row["url"])
        if existing is None:
            by_url[row["url"]] = row
        elif existing["entry"] == "start" and row["entry"] == "identify":
            by_url[row["url"]] = row
    return list(by_url.values())


def write_mf_input_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MF_INPUT_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_from_drains_summary(
    path: Path,
    *,
    stage2_rows: List[dict],
    stage3_rows: List[dict],
    total_rows: int,
    stage2_path: Path,
    stage3_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def counts(rows: List[dict]) -> Tuple[int, int]:
        identify = sum(1 for r in rows if r["entry"] == "identify")
        start = sum(1 for r in rows if r["entry"] == "start")
        return identify, start

    s2_identify, s2_start = counts(stage2_rows)
    s3_identify, s3_start = counts(stage3_rows)
    lines = [
        "# WO-1043: drains -> Meeting Finder input, dry-run summary\n",
        "Purpose: turn what the certificate-log drain (drain2) and the Common "
        "Crawl drain (drain3) found for governments Meeting Finder could not "
        "reach into new Meeting Finder starting points.\n",
        f"drain2 results file: {stage2_path}\n",
        f"drain3 results file: {stage3_path}\n",
        "## Result | Count\n",
        "| Result | Count |",
        "|---|---|",
        f"| New rows from drain2 (certificate log) | {len(stage2_rows)} |",
        f"| drain2 rows entering at Identify (vendor confirmed) | {s2_identify} |",
        f"| drain2 rows entering at Start (keyword match only) | {s2_start} |",
        f"| New rows from drain3 (Common Crawl) | {len(stage3_rows)} |",
        f"| drain3 rows entering at Identify (vendor confirmed) | {s3_identify} |",
        f"| drain3 rows entering at Start (keyword match only) | {s3_start} |",
        f"| **Total Meeting Finder input rows (deduped by URL)** | **{total_rows}** |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------- #
# CLI                                                                    #
# --------------------------------------------------------------------- #


def cmd_to_drains(args: argparse.Namespace) -> None:
    input_paths = [Path(p) for p in args.verdicts_jsonl]
    verdict_rows = load_verdicts_jsonl(input_paths)
    recon_rows, counts_by_outcome, skipped_no_domain = build_drain_feed(verdict_rows)
    out_path = Path(args.out)
    write_recon_jsonl(out_path, recon_rows)
    matched_rows = sum(counts_by_outcome.values())
    if args.summary:
        write_to_drains_summary(
            Path(args.summary),
            counts_by_outcome=counts_by_outcome,
            matched_rows=matched_rows,
            governments_written=len(recon_rows),
            skipped_no_domain=skipped_no_domain,
            inputs=input_paths,
        )
    print(
        f"to-drains: {matched_rows} matching verdict rows, "
        f"{len(recon_rows)} governments written to {out_path}"
    )
    for outcome in sorted(counts_by_outcome):
        print(f"  {outcome}: {counts_by_outcome[outcome]}")


def cmd_from_drains(args: argparse.Namespace) -> None:
    stage2_path = Path(args.stage2_results)
    stage3_path = Path(args.stage3_results)
    stage2_entries = load_stage2_results(stage2_path)
    stage3_results = load_stage3_results(stage3_path)
    stage2_rows = stage2_rows_to_mf(stage2_entries)
    stage3_rows = stage3_rows_to_mf(stage3_results)
    all_rows = dedupe_mf_rows(stage2_rows + stage3_rows)
    out_path = Path(args.out)
    write_mf_input_csv(out_path, all_rows)
    if args.summary:
        write_from_drains_summary(
            Path(args.summary),
            stage2_rows=stage2_rows,
            stage3_rows=stage3_rows,
            total_rows=len(all_rows),
            stage2_path=stage2_path,
            stage3_path=stage3_path,
        )
    print(
        f"from-drains: {len(stage2_rows)} rows from drain2, {len(stage3_rows)} from "
        f"drain3, {len(all_rows)} Meeting Finder input rows written to {out_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    to_drains = sub.add_parser(
        "to-drains", help="Meeting Finder verdicts -> queue_pipeline.py feed's input"
    )
    to_drains.add_argument(
        "--verdicts-jsonl",
        action="append",
        required=True,
        metavar="PATH",
        help="A verdicts.csv.jsonl file to read; repeatable",
    )
    to_drains.add_argument(
        "--out", required=True, help="Where to write the recon-shaped feed file"
    )
    to_drains.add_argument("--summary", default=None, help="Optional summary.md path")
    to_drains.set_defaults(func=cmd_to_drains)

    from_drains = sub.add_parser(
        "from-drains", help="drain2/drain3 result files -> Meeting Finder input rows"
    )
    from_drains.add_argument(
        "--stage2-results", required=True, help="Path to drain2's results_stage2.json"
    )
    from_drains.add_argument(
        "--stage3-results", required=True, help="Path to drain3's results_stage3.jsonl"
    )
    from_drains.add_argument(
        "--out", required=True, help="Where to write the Meeting Finder input CSV"
    )
    from_drains.add_argument("--summary", default=None, help="Optional summary.md path")
    from_drains.set_defaults(func=cmd_from_drains)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
