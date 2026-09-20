"""WO-912 (2026-09-20): headless as a SECOND OPINION on every government the
ladder skipped it for -- the missing half of `scripts/wo908_headless_pilot.py`.

Why this exists. `run_access_ladder()` only launches headless when a page
loaded fine but showed NO meeting-shaped link at all (see the
`if not hop_links:` branch in `scripts/wo147_access_ladder_sweep.py`). When a
page has hop links, the ladder follows them over plain HTTP, and if nothing
leads to a platform it stops with "reached, hop links checked, no platform
link found" -- headless never runs. Measured on this WO's own sample, that
is ~80% of governments. WO-148 (2026-09-10) ran an older ladder that sent 850
of 1,132 governments through headless; 61 (7.2%) found a link. So the
pilot on its own measures the ladder's TRIGGER RULE as much as headless
itself, and a low headless count from it would not mean "headless doesn't
help." This script measures the other half: run the ladder's own headless
step, unmodified, on the skipped governments' home pages.

It reuses the ladder's own functions unchanged (`fetch_headless`,
`is_challenge`, `find_platform_link`, `_is_decorative_hit`) plus the pilot's
`direct_file_hit_is_plausible`, so a "found" here means exactly what a
headless "found" means inside the ladder. Same rules as the ladder: one
browser, one government at a time; a human-verification page ends that
government for good (recorded as `challenge`, never retried, never
solved); a government whose plain fetch was blocked by a WAF (rung
`browser-headers`) is never sent to headless at all.

Measurement only: reads the pilot's report CSV, writes its own report CSV,
no ingest, no research-file write. Resumable (skips gov_ids already in its
output). Safe to run while the pilot is still appending to its report --
it reads whatever complete rows exist, then can be re-run later for the
rest.

Usage (from the repo root):
    python scripts/wo912_headless_second_opinion.py \\
        --report-csv <pilot report> --out-csv <second-opinion report>
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

from app.platforms import register_all_finders  # noqa: E402

import scripts.wo147_access_ladder_sweep as ladder  # noqa: E402
from scripts.wo908_headless_pilot import direct_file_hit_is_plausible  # noqa: E402

# Same threshold as the pilot / ladder sweeps: consecutive real failures
# (here, headless failing to launch or load at all) abort the run.
MAX_CONSECUTIVE_ERRORS = 6

OUT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "domain",
    "final_url",
    "second_opinion",
    "platform",
    "hit_url",
    "direct_file_plausible",
    "error",
    "elapsed_seconds",
]


def _is_youtube(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(h in host for h in ("youtube.com", "youtu.be"))


def qualifies(row: Dict[str, str]) -> bool:
    """True when the ladder reached the government's page over PLAIN HTTP,
    followed its hop links, found nothing, and therefore never ran
    headless. Anything else is out of scope: a row the ladder already sent
    to headless (`rung_answered` headless, or a "headless failed" note),
    a platform already found, a WAF/challenge/dead outcome, or a plain-fetch
    403 (`browser-headers` -- never sent to headless, by the ladder's own
    rule)."""
    if row.get("exception"):
        return False
    if row.get("rung_answered") != "plain" or row.get("platform"):
        return False
    note = (row.get("note") or "").lower()
    if "headless" in note:
        return False
    final_url = row.get("final_url") or ""
    # CLAUDE.md: youtube.com / youtu.be are fetched only by the drip Mac.
    # The pilot never lands on one (its `final_url_is_youtube` column audits
    # that), but a browser load here would be a direct fetch, so refuse.
    if row.get("final_url_is_youtube") == "True" or _is_youtube(final_url):
        return False
    return bool(final_url) and "hop links checked" in note


def load_qualifying(report_csv: Path) -> List[Dict[str, str]]:
    """Complete rows only: the pilot may be mid-append, and a partly
    written last line parses as a short row (missing fields -> None)."""
    with report_csv.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if None not in r.values()]
    return [r for r in rows if qualifies(r)]


def classify(
    html: Optional[str], final_url: str, err: Optional[str], gov_domain: str
) -> Dict[str, str]:
    """Turns one headless fetch into the report fields, using the ladder's
    own tests in the ladder's own order (challenge check first, then the
    decorative-hit rejection, then the pilot's direct_file plausibility)."""
    out = {"second_opinion": "none", "platform": "", "hit_url": "", "error": ""}
    out["direct_file_plausible"] = ""
    if err or not html:
        out["second_opinion"] = "error"
        out["error"] = (err or "empty page")[:300]
        return out
    if ladder.is_challenge(html):
        out["second_opinion"] = "challenge"
        return out
    hit = ladder.find_platform_link(html, final_url)
    if not hit:
        return out
    platform, url = hit
    if ladder._is_decorative_hit(url):
        out["error"] = f"decorative hit skipped: {url}"[:300]
        return out
    if platform == "direct_file":
        plausible = direct_file_hit_is_plausible(gov_domain, url)
        out["direct_file_plausible"] = str(plausible)
        if not plausible:
            out["error"] = f"direct_file hit rejected as implausible: {url}"[:300]
            return out
    out.update(second_opinion="found", platform=platform, hit_url=url)
    return out


async def run(
    report_csv: Path, out_csv: Path, limit: Optional[int], skip_tail: int = 0
) -> None:
    register_all_finders()
    todo = load_qualifying(report_csv)
    if skip_tail:
        # The pilot may still be running: leave its newest rows alone so a
        # government is never browser-loaded moments after its plain fetch.
        todo = todo[:-skip_tail]
    done = set()
    if out_csv.exists():
        with out_csv.open(newline="", encoding="utf-8") as f:
            done = {r["gov_id"] for r in csv.DictReader(f)}
    todo = [r for r in todo if r["gov_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} governments to give a headless second opinion this run.")

    is_new = not out_csv.exists()
    consecutive_errors = 0
    with out_csv.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        for i, row in enumerate(todo, 1):
            t0 = time.monotonic()
            html, url, err = await ladder.fetch_headless(row["final_url"])
            res = classify(html, url or row["final_url"], err, row["domain"])
            rec = {k: row.get(k, "") for k in OUT_FIELDS if k in row}
            rec.update(res)
            rec["elapsed_seconds"] = f"{time.monotonic() - t0:.1f}"
            w.writerow({k: rec.get(k, "") for k in OUT_FIELDS})
            f.flush()
            print(
                f"[{i}/{len(todo)}] {row['name']}, {row['state']} -- "
                f"{rec['second_opinion']} platform={rec['platform'] or '-'} "
                f"({rec['elapsed_seconds']}s)"
            )
            consecutive_errors = (
                consecutive_errors + 1 if res["second_opinion"] == "error" else 0
            )
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(
                    f"\nABORTING: {consecutive_errors} consecutive headless "
                    "failures. Re-run with the same --out-csv to resume.",
                    file=sys.stderr,
                )
                return
            if i < len(todo):
                await asyncio.sleep(ladder.GOV_DELAY_SECONDS)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-csv", type=Path, required=True)
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--skip-tail",
        type=int,
        default=0,
        help="Ignore the newest N qualifying rows (use while the pilot is running).",
    )
    args = ap.parse_args()
    asyncio.run(run(args.report_csv, args.out_csv, args.limit, args.skip_tail))


if __name__ == "__main__":
    main()
