"""WO-289 phase 2: finish the rows in wo289_pending_handread.csv that a
hand-read (WO-289's own agent, per the WO-289 brief's "hand-check every
found video" rule) marked `decision=approve`.

Tier 1/2 (segments already resolved -- the adapter fetched real
captions): written to a tab-separated urls file
(`meeting_url<TAB>gov_id`, scripts/bulk_ingest.py's own documented
per-line gov_id shape, WO-222) and ingested via that script directly, so
the page carries its government from the ingest payload rather than
depending on a pin reaching production first.

Tier 3 (real video, no reachable captions): routed through
`app/platforms/queue_probe.py`'s shared `finish_candidate()` -- the one
place a probe verdict should become a queue line, per
docs/COVERAGE_HANDOVER.md section 4 and BACKLOG_DONE.md's WO-224 entry.

A pin is written only when the candidate's own host is genuinely a
multi-government shared host (`app/utils/gov_registry/registry.py`'s
`MULTI_GOV_HOSTS`) -- every platform this run's phase 1
(wo289_list_candidates.py) can reach is a single-tenant vendor
subdomain (`cityofracine.granicus.com`, `leecoal.portal.civicclerk.
com`, ...), which the normal registry ladder already keys correctly on
a future re-resolve without an explicit pin; writing one anyway would
either be a no-op (write_pin_row requires a non-blank match, which a
single-tenant host pin has none of) or misleading.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo289_test.db" \\
    /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python scripts/wo289_finish_approved.py --dry-run
    ... (same) ... scripts/wo289_finish_approved.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import finish_candidate  # noqa: E402
from app.utils.gov_registry.registry import is_multi_gov_host  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
PENDING_CSV = RESEARCH_DIR / "wo289_pending_handread.csv"
APPROVED_URLS_TXT = RESEARCH_DIR / "wo289_approved_tier12_urls.txt"
FINISH_LOG_CSV = RESEARCH_DIR / "wo289_finish_log.csv"

CALLER = "wo289"


def _load_pending():
    with PENDING_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _finish_log_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    fieldnames = [
        "gov_id",
        "group",
        "platform",
        "tier",
        "meeting_url",
        "outcome",
        "detail",
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    if is_new:
        w.writeheader()
    return f, w


async def finish_tier3(row: dict, log_w, dry_run: bool) -> None:
    netloc = row.get("netloc", "")
    pin = None
    if is_multi_gov_host(netloc):
        # None of this run's phase-1 platforms actually hit a multi-gov
        # host (see module docstring) -- if one ever does, refuse to
        # guess a match; record it for a human rather than writing a
        # blank-match pin (the exact WO-210 mistake).
        log_w.writerow(
            dict(
                gov_id=row["gov_id"],
                group=row["group"],
                platform=row["platform"],
                tier="tier3",
                meeting_url=row["meeting_url"],
                outcome="skipped-needs-pin-match",
                detail=f"{netloc} is a multi-gov host; no per-video match derived, needs a human",
            )
        )
        return
    if dry_run:
        log_w.writerow(
            dict(
                gov_id=row["gov_id"],
                group=row["group"],
                platform=row["platform"],
                tier="tier3",
                meeting_url=row["meeting_url"],
                outcome="dry-run",
                detail="would call finish_candidate()",
            )
        )
        return
    outcome = await finish_candidate(
        row["meeting_url"],
        video_url=row.get("video_url") or None,
        source_url=row.get("source_url") or None,
        platform=row.get("platform") or None,
        gov_id=row["gov_id"],
        jurisdiction=row.get("jurisdiction", ""),
        title=row.get("title", ""),
        pin=pin,
        caller=CALLER,
    )
    log_w.writerow(
        dict(
            gov_id=row["gov_id"],
            group=row["group"],
            platform=row["platform"],
            tier="tier3",
            meeting_url=row["meeting_url"],
            outcome=outcome.action,
            detail=f"verdict={outcome.probe.verdict} reason={outcome.probe.reason}",
        )
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = _load_pending()
    approved = [
        r for r in rows if (r.get("decision") or "").strip().lower() == "approve"
    ]
    print(f"{len(rows)} pending rows, {len(approved)} approved.")

    tier12 = [r for r in approved if r.get("tier") == "tier1_2"]
    tier3 = [r for r in approved if r.get("tier") == "tier3"]

    if tier12:
        with APPROVED_URLS_TXT.open("w", encoding="utf-8") as f:
            for r in tier12:
                f.write(f"{r['meeting_url']}\t{r['gov_id']}\n")
        print(f"wrote {len(tier12)} tier1/2 URLs to {APPROVED_URLS_TXT}")
        print(
            "run: DATABASE_URL=... /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python "
            f"scripts/bulk_ingest.py {APPROVED_URLS_TXT}"
            + (" --dry-run" if args.dry_run else "")
        )

    if tier3:
        log_f, log_w = _finish_log_writer(FINISH_LOG_CSV)
        asyncio.run(_run_tier3(tier3, log_w, args.dry_run))
        log_f.close()
        print(f"tier3: {len(tier3)} row(s) processed, see {FINISH_LOG_CSV}")


async def _run_tier3(tier3, log_w, dry_run):
    for row in tier3:
        await finish_tier3(row, log_w, dry_run)


if __name__ == "__main__":
    main()
