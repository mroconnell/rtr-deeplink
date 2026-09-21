"""WO-934: the full-corpus wrong-page screen, as a repeatable read-only command.

This is the 2026-09-06 screen that flagged 414 of 5,857 live pages (7.1%),
moved into the repo so it can be run again after the repairs. The rules are
copied unchanged from `rtr-business/research/archive_audit/audit_heuristics.py`
(the audit's own report is `AUDIT_REPORT.md` in that folder). It reads pages;
it never writes to anything but its own output files.

The three rules, on each page's title and government type:

  no_meeting_keyword
      the title has no meeting-shaped word (council, board, committee,
      meeting, hearing, ...). Every one of the first nine confirmed-bad pages
      failed this. It also fires on ordinary meetings with unusual titles, so
      it is a screen and not a verdict.
  explicit_non_meeting_marker
      the title carries a talk-show, promo or news-segment word (episode,
      weekly update, year in review, welcome to, ...).
  non_school_gov_type_but_school_body_in_title
      the page is filed under a city, county or town, but the title names a
      school board. The wrong-government-type pattern.
  school_district_gov_type_but_non_school_body_in_title
      the page is filed under a school district, but the title names a city
      council, planning commission and so on.

Where the pages come from (choose one).

  --from-archive   Read `GET /internal/export/pages` in pages of 500, no
                   transcripts. Needs ARCHIVE_INGEST_TOKEN in the environment.
                   Run it on the Archive's Render shell, where the address is
                   http://127.0.0.1:$PORT (or pass --base-url). About 21 small
                   requests for 10,000 pages.
  --from-inventory FILE
                   A local export CSV (`scripts/export_meeting_inventory.py`).
                   Reads no production data.

What it writes. `--out` gets one row per flagged page: `page_id`, `slug`,
`title`, `government`, `gov_type`, `platform`, `source_url`, `reasons`, and
`on_worklist` (`yes` when the page is a row of `--worklist`, with its action).
The console gets a table of counts by reason. The point of the re-run: a page
that is flagged and NOT on the worklist is still waiting for a person; a
page that is flagged and IS on the worklist is waiting for the worklist.

Usage (Archive Render shell, repo root):
    python scripts/wrong_page_screen.py --from-archive \\
        --worklist reports/wrong_page_worklist.csv --out /tmp/wrong_page_screen.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Copied unchanged from the 2026-09-06 audit so the numbers stay comparable.
MEETING_KEYWORDS_RE = re.compile(
    r"\b("
    r"council|board|commission|committee|meeting|session|hearing|"
    r"trustees|supervisors|authority|assembly|selectboard|select board|"
    r"aldermen|legislature|caucus|forum|workshop|zoning|planning|"
    r"budget|finance|education|regular|special|work session|"
    r"study session|public hearing|town hall|freeholders|"
    r"commissioners|directors|governing|advisory|task force|"
    r"subcommittee|delegation|conference|retreat|deliberation"
    r")\b",
    re.IGNORECASE,
)
SCHOOL_BODY_RE = re.compile(
    r"\b(school board|board of education|school committee|superintendent|"
    r"school district)\b",
    re.IGNORECASE,
)
NON_SCHOOL_BODY_RE = re.compile(
    r"\b(city council|town council|village council|board of supervisors|"
    r"county commission|planning commission|zoning commission|"
    r"planning & zoning|planning and zoning|solid waste|"
    r"board of aldermen|board of freeholders|county board|"
    r"sheriff|public works commission|water district board|"
    r"parks and recreation commission|library board|"
    r"historic preservation commission)\b",
    re.IGNORECASE,
)
NON_MEETING_CONTENT_RE = re.compile(
    r"\b(newsbreak|weekly update|episode|the poetry room|tinyhome|"
    r"tiny home|spotlight|newsmagazine|documentary|human interest|"
    r"psa\b|public service announcement|commercial break|promo\b|"
    r"year in review|welcome to|greetings from|profile:|feature:|"
    r"student built|student-built|behind the scenes)\b",
    re.IGNORECASE,
)

OUT_COLUMNS = [
    "page_id",
    "slug",
    "title",
    "government",
    "gov_type",
    "platform",
    "source_url",
    "reasons",
    "on_worklist",
]


def screen_reasons(title: str, gov_type: Optional[str]) -> List[str]:
    """The audit's reasons for flagging one page, in the audit's order."""
    reasons: List[str] = []
    if not MEETING_KEYWORDS_RE.search(title):
        reasons.append("no_meeting_keyword")
    if NON_MEETING_CONTENT_RE.search(title):
        reasons.append("explicit_non_meeting_marker")
    has_school_body = bool(SCHOOL_BODY_RE.search(title))
    has_non_school_body = bool(NON_SCHOOL_BODY_RE.search(title))
    if gov_type == "school_district" and has_non_school_body:
        reasons.append("school_district_gov_type_but_non_school_body_in_title")
    if gov_type and gov_type != "school_district" and has_school_body:
        reasons.append("non_school_gov_type_but_school_body_in_title")
    return reasons


def pages_from_inventory(path: Path) -> Iterator[Dict[str, str]]:
    """Pages as (id, slug, title, jurisdiction, gov_type, platform, source_url)."""
    with open(path, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            yield {
                "id": raw.get("page_id", ""),
                "slug": (raw.get("archive_url") or "").rsplit("/m/", 1)[-1],
                "title": raw.get("meeting_name") or "",
                "jurisdiction": raw.get("page_display_name") or "",
                "gov_type": raw.get("gov_type") or "",
                "platform": raw.get("page_platform") or "",
                "source_url": raw.get("source_url") or "",
            }


def pages_from_archive(
    base_url: str, token: str, *, client=None
) -> Iterator[Dict[str, str]]:
    """Every live page, 500 at a time, metadata only (no transcripts)."""
    import httpx

    http = client or httpx.Client(base_url=base_url, timeout=120.0)
    headers = {"Authorization": f"Bearer {token}"}
    after_id = 0
    while True:
        response = http.get(
            "/internal/export/pages",
            params={"after_id": after_id, "limit": 500},
            headers=headers,
        )
        if response.status_code != 200:
            raise SystemExit(
                f"GET /internal/export/pages answered HTTP {response.status_code} "
                "(a 404 usually means a wrong or missing ARCHIVE_INGEST_TOKEN)"
            )
        body = response.json()
        for page in body.get("pages") or []:
            yield {
                "id": str(page.get("id")),
                "slug": page.get("slug") or "",
                "title": page.get("title") or "",
                "jurisdiction": page.get("jurisdiction") or "",
                "gov_type": page.get("gov_type") or "",
                "platform": page.get("platform") or "",
                "source_url": page.get("source_url_normalized") or "",
            }
        after_id = body.get("next_after_id")
        if after_id is None:
            return


def worklist_actions(path: Optional[Path]) -> Dict[str, str]:
    """page_id -> action for every row of a sheet."""
    if path is None:
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {
            (row.get("page_id") or "").strip(): (row.get("action") or "").strip()
            for row in csv.DictReader(fh)
        }


def screen(
    pages: Iterable[Dict[str, str]], on_worklist: Optional[Dict[str, str]] = None
) -> tuple[int, List[Dict[str, str]]]:
    """(pages scanned, flagged rows)."""
    on_worklist = on_worklist or {}
    scanned = 0
    flagged: List[Dict[str, str]] = []
    for page in pages:
        scanned += 1
        reasons = screen_reasons(page["title"], page["gov_type"] or None)
        if not reasons:
            continue
        action = on_worklist.get(page["id"])
        flagged.append(
            {
                "page_id": page["id"],
                "slug": page["slug"],
                "title": page["title"],
                "government": page["jurisdiction"],
                "gov_type": page["gov_type"],
                "platform": page["platform"],
                "source_url": page["source_url"],
                "reasons": ";".join(reasons),
                "on_worklist": f"yes ({action})" if action else "no",
            }
        )
    return scanned, flagged


def summary_lines(scanned: int, flagged: List[Dict[str, str]]) -> List[str]:
    by_reason: Counter = Counter()
    for row in flagged:
        for reason in row["reasons"].split(";"):
            by_reason[reason] += 1
    on = sum(1 for r in flagged if r["on_worklist"].startswith("yes"))
    pct = 100 * len(flagged) / scanned if scanned else 0.0
    lines = [
        f"Pages scanned: {scanned}",
        f"Pages flagged: {len(flagged)} ({pct:.1f}%)",
        "",
        "Reason | Count of flagged pages",
    ]
    lines += [f"{reason} | {n}" for reason, n in by_reason.most_common()]
    lines += [
        "",
        "Flagged pages | Count",
        f"Already a row on the worklist | {on}",
        f"Not on the worklist (still waiting for a person) | {len(flagged) - on}",
    ]
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-archive", action="store_true")
    source.add_argument("--from-inventory", help="a local export CSV")
    parser.add_argument(
        "--base-url", help="default: ARCHIVE_BASE_URL, then http://127.0.0.1:$PORT"
    )
    parser.add_argument(
        "--worklist", help="mark flagged pages that are rows of this sheet"
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.from_archive:
        token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
        if not token:
            print(
                "ARCHIVE_INGEST_TOKEN is not set in the environment.", file=sys.stderr
            )
            return 1
        base = (
            args.base_url
            or os.environ.get("ARCHIVE_BASE_URL")
            or (
                f"http://127.0.0.1:{os.environ['PORT']}"
                if os.environ.get("PORT")
                else ""
            )
        )
        if not base:
            print(
                "No Archive address: pass --base-url or set ARCHIVE_BASE_URL.",
                file=sys.stderr,
            )
            return 1
        pages: Iterable[Dict[str, str]] = pages_from_archive(base.rstrip("/"), token)
    else:
        pages = pages_from_inventory(Path(args.from_inventory))

    scanned, flagged = screen(
        pages, worklist_actions(Path(args.worklist) if args.worklist else None)
    )
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(flagged)
    print("\n".join(summary_lines(scanned, flagged)))
    print(f"\nFlagged pages written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
