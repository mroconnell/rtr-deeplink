"""WO-193 (2026-09-11): normalise `domain` (and `alternate_domains`) in
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` to a bare,
lowercase host -- no scheme, no path, no query, no port, no trailing
dot. A `www.` prefix is kept exactly as recorded (never added or
stripped). See `BACKLOG_DONE.md`'s WO-193 entry and
`docs/COVERAGE_HANDOVER.md` for why.

What this does, per row:
1. If `domain` is a bare, already-canonical host: leave it alone.
2. If `domain` carries a scheme, a path, a query, a port, uppercase
   letters, or a trailing dot: rewrite it to the bare canonical host.
   If it also carried a real path or query (a real page, not just a
   scheme), the original full value is preserved by appending it to
   `alternate_urls` (semicolon-separated, deduped) -- nothing is lost.
3. If `domain` is two or more space/comma-separated values that each
   independently look like a real hostname: the first becomes `domain`,
   the rest fold into `alternate_domains`.
4. `alternate_domains` entries get the same treatment, one at a time
   (semicolon-separated); the result is deduped, and any entry that
   normalises to the same host as the (possibly just-changed) primary
   `domain` is dropped from `alternate_domains`.
5. A blank `domain` is NEVER filled in and NEVER blanked -- this script
   only reshapes an already-present value.

Never touches `example_meeting_url` / `example_agenda_or_calendar_url`
(URLs by design) or any other column.

Follows `ENUMERATION_METHODS.md` §158's write protocol: flock, re-read
immediately before writing, refuse below 99% of the last committed line
count, temp file + `os.replace`, LF endings, caller must `git diff
--stat` and commit with explicit paths right after this returns 0.

Usage:
    python3 scripts/wo193_apply_domain_normalise.py [--dry-run] [path-to-csv]

`--dry-run` runs the full read-modify-diff pipeline (including writing
the per-row report) but does not touch the CSV itself -- use it to check
the report and change count before doing the real, locked write.
"""

from __future__ import annotations

import csv
import fcntl
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.coverage_alternates import canonicalize_domain, classify_domain_shape  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business"
DEFAULT_CSV = RESEARCH_DIR / "research" / "jurisdiction_coverage.csv"
REPORT_CSV = RESEARCH_DIR / "research" / "wo193_report.csv"
LOCK_PATH = RESEARCH_DIR / "research" / "jurisdiction_coverage.csv.lock"

REPORT_FIELDS = [
    "gov_id",
    "domain_before",
    "domain_after",
    "alternate_domains_before",
    "alternate_domains_after",
    "alternate_urls_added",
    "shape",
]

_HOSTNAME_LIKE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)


def try_split_multi_value(value: str) -> Optional[List[str]]:
    """If `value` looks like two or more space/comma-separated real
    hostnames rather than one (possibly malformed) host, return the
    lowercased list. Otherwise None. Deliberately conservative: every
    split part must independently look like a real hostname (a dot,
    valid label characters) -- a single garbled host (e.g. a comma
    typo'd in place of a dot, a real row in this file:
    `http://www.msvalere.qc,ca`) fails this on purpose, since "ca" alone
    is not a real second host, and is left to `canonicalize_domain` as
    one odd host instead of being torn into two."""
    if "://" in value:
        return None
    parts = [
        p.strip().rstrip(".") for p in re.split(r"[,\s]+", value.strip()) if p.strip()
    ]
    if len(parts) < 2:
        return None
    lowered = [p.lower() for p in parts]
    if not all(_HOSTNAME_LIKE.match(p) for p in lowered):
        return None
    return lowered


def process_row(row: Dict[str, str]) -> Tuple[bool, Dict[str, str], Dict[str, str]]:
    """Returns (changed, new_values_for_row, report_row_or_empty).
    `new_values_for_row` has keys 'domain', 'alternate_domains',
    'alternate_urls' -- only ever a rewrite of those three columns."""
    orig_domain = row.get("domain") or ""
    orig_alt_domains = row.get("alternate_domains") or ""
    orig_alt_urls = row.get("alternate_urls") or ""

    alt_urls_list = [u.strip() for u in orig_alt_urls.split(";") if u.strip()]
    alt_urls_seen = set(alt_urls_list)
    added_urls: List[str] = []

    def add_alt_url(u: str) -> None:
        if u and u not in alt_urls_seen:
            alt_urls_seen.add(u)
            alt_urls_list.append(u)
            added_urls.append(u)

    domain_val = orig_domain.strip()
    shape = classify_domain_shape(domain_val) if domain_val else "blank"
    new_domain = orig_domain
    extra_domains_from_split: List[str] = []
    multi_split_found = False

    if domain_val:
        multi = try_split_multi_value(domain_val)
        if multi:
            multi_split_found = True
            new_domain = multi[0]
            extra_domains_from_split = multi[1:]
        else:
            host, extra_url = canonicalize_domain(domain_val)
            if host:
                new_domain = host
            if extra_url:
                add_alt_url(extra_url)

    new_domain_norm = new_domain.strip().lower()

    canon_alts: List[str] = []
    alts_seen = set()

    def add_alt_domain(h: str) -> None:
        if h and h != new_domain_norm and h not in alts_seen:
            alts_seen.add(h)
            canon_alts.append(h)

    for entry in (e.strip() for e in orig_alt_domains.split(";")):
        if not entry:
            continue
        m = try_split_multi_value(entry)
        if m:
            for h in m:
                add_alt_domain(h)
            continue
        host, extra_url = canonicalize_domain(entry)
        if host:
            add_alt_domain(host)
        if extra_url:
            add_alt_url(extra_url)

    for h in extra_domains_from_split:
        add_alt_domain(h)

    new_alt_domains = ";".join(canon_alts)
    new_alt_urls = ";".join(alt_urls_list)

    changed = (
        new_domain != orig_domain
        or new_alt_domains != orig_alt_domains
        or new_alt_urls != orig_alt_urls
    )

    new_values = {
        "domain": new_domain,
        "alternate_domains": new_alt_domains,
        "alternate_urls": new_alt_urls,
    }

    report_row: Dict[str, str] = {}
    if changed:
        report_shape = "multi_value" if multi_split_found else shape
        report_row = {
            "gov_id": row.get("gov_id", ""),
            "domain_before": orig_domain,
            "domain_after": new_domain,
            "alternate_domains_before": orig_alt_domains,
            "alternate_domains_after": new_alt_domains,
            "alternate_urls_added": ";".join(added_urls),
            "shape": report_shape,
        }

    return changed, new_values, report_row


def git_committed_line_count() -> int:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(RESEARCH_DIR),
            "show",
            "HEAD:research/jurisdiction_coverage.csv",
        ],
        capture_output=True,
        check=True,
    )
    return out.stdout.count(b"\n")


def run(csv_path: Path, dry_run: bool) -> int:
    min_lines = int(git_committed_line_count() * 0.99)

    lock_path = LOCK_PATH
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Re-read immediately before writing.
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        current_lines = sum(1 for _ in open(csv_path, "rb"))
        if current_lines < min_lines:
            print(
                f"REFUSING: {csv_path} has {current_lines} lines, "
                f"below 99% of the committed {git_committed_line_count()} -- "
                "looks truncated. Not writing.",
                file=sys.stderr,
            )
            return 1

        report_rows: List[Dict[str, str]] = []
        changed_count = 0
        multi_value_count = 0

        for row in rows:
            changed, new_values, report_row = process_row(row)
            if changed:
                changed_count += 1
                row["domain"] = new_values["domain"]
                row["alternate_domains"] = new_values["alternate_domains"]
                row["alternate_urls"] = new_values["alternate_urls"]
                if report_row.get("shape") == "multi_value":
                    multi_value_count += 1
                report_rows.append(report_row)

        print(f"Rows read: {len(rows)}")
        print(f"Rows changed: {changed_count}")
        print(f"Multi-valued domain cells split: {multi_value_count}")

        # Always write the report (even in dry-run) so it can be reviewed.
        with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
            writer.writeheader()
            for r in report_rows:
                writer.writerow(r)
        print(f"Report written: {REPORT_CSV} ({len(report_rows)} rows)")

        if dry_run:
            print("Dry run -- not writing the CSV.")
            return 0

        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(csv_path.parent), suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            os.replace(tmp_path, csv_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        print("Wrote", csv_path)
        return 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    csv_path = Path(args[0]) if args else DEFAULT_CSV
    return run(csv_path, dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
