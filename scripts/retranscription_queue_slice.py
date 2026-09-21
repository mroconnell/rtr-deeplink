"""Print the next URLs from one section of scripts/retranscription_queue.txt.

WO-929. The local transcription script (`scripts/transcribe_backlog_locally.py
--urls-file FILE`) ignores `--limit` when given a file and takes every
non-comment line, so a "next 5" run needs a file with only those 5 lines.
This makes that file. It is a manual helper: nothing calls it
automatically, and it never edits the queue. It reads two things:

  scripts/retranscription_queue.txt        sections and URL order
  scripts/retranscription_queue_meta.csv   page id per URL, and the
                                           `# done,...` progress records

A page counts as finished when the meta file holds a done record for its
page id whose verdict is `promoted` or `kept-old` (a person looked at the
new version and decided). A `failed` record does not remove a page: it stays
in line to be tried again.

Usage (from the repo root):
    python scripts/retranscription_queue_slice.py --section PILOT > /tmp/retranscribe_pilot.txt
    python scripts/retranscription_queue_slice.py --section MAIN --count 10 > /tmp/retranscribe_next10.txt
    python scripts/retranscription_queue_slice.py --status

Record a finished page by appending one line to the meta CSV (never delete a
history line):
    # done,<page_id>,<YYYY-MM-DD>,<new_version_id>,<promoted|kept-old|failed>
"""

import argparse
import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = REPO_ROOT / "scripts" / "retranscription_queue.txt"
META_FILE = REPO_ROOT / "scripts" / "retranscription_queue_meta.csv"

SECTION_START = re.compile(r"^# === SECTION: (?P<name>[A-Z-]+) \((?P<n>\d+) pages, ")
SECTION_END = re.compile(r"^# === END SECTION: (?P<name>[A-Z-]+) ===$")
FINISHED_VERDICTS = {"promoted", "kept-old"}


def parse_sections(text: str) -> dict[str, list[str]]:
    """Section name -> URLs in order. Raises ValueError on a malformed file."""
    sections: dict[str, list[str]] = {}
    current = None
    for lineno, line in enumerate(text.split("\n"), 1):
        start = SECTION_START.match(line)
        end = SECTION_END.match(line)
        if start:
            if current is not None:
                raise ValueError(f"line {lineno}: section {current} not closed")
            current = start.group("name")
            if current in sections:
                raise ValueError(f"line {lineno}: duplicate section {current}")
            sections[current] = []
        elif end:
            if end.group("name") != current:
                raise ValueError(
                    f"line {lineno}: END {end.group('name')} without start"
                )
            current = None
        elif line.strip() and not line.startswith("#"):
            if current is None:
                raise ValueError(f"line {lineno}: URL outside any section")
            sections[current].append(line.strip())
    if current is not None:
        raise ValueError(f"section {current} not closed")
    return sections


def read_meta(text: str) -> tuple[list[dict], list[list[str]]]:
    """(data rows as dicts, done records as lists). Comment lines other than
    `# done,...` are ignored."""
    data_lines: list[str] = []
    done: list[list[str]] = []
    for line in text.split("\n"):
        if line.startswith("# done,"):
            done.append(next(csv.reader([line[2:]])))
        elif line.strip() and not line.startswith("#"):
            data_lines.append(line)
    rows = list(csv.DictReader(data_lines))
    return rows, done


def finished_page_ids(done: list[list[str]]) -> set[str]:
    return {rec[1] for rec in done if len(rec) >= 5 and rec[4] in FINISHED_VERDICTS}


def next_urls(
    sections: dict[str, list[str]],
    meta_rows: list[dict],
    done: list[list[str]],
    section: str,
    count: int | None,
) -> list[str]:
    page_by_url = {r["url"]: r["page_id"] for r in meta_rows}
    finished = finished_page_ids(done)
    urls = [u for u in sections[section] if page_by_url.get(u) not in finished]
    return urls if count is None else urls[:count]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--section", choices=["PILOT", "MAIN", "DRIP-MAC-ONLY"])
    ap.add_argument("--count", type=int, default=None, help="At most this many URLs")
    ap.add_argument("--status", action="store_true", help="Show progress per section")
    args = ap.parse_args()

    sections = parse_sections(QUEUE_FILE.read_text(encoding="utf-8"))
    meta_rows, done = read_meta(META_FILE.read_text(encoding="utf-8"))
    if args.status:
        finished = finished_page_ids(done)
        page_by_url = {r["url"]: r["page_id"] for r in meta_rows}
        for name, urls in sections.items():
            n_done = sum(1 for u in urls if page_by_url.get(u) in finished)
            print(
                f"{name}: {len(urls)} pages, {n_done} finished, {len(urls) - n_done} left"
            )
        return 0
    if not args.section:
        ap.error("give --section or --status")
    for url in next_urls(sections, meta_rows, done, args.section, args.count):
        print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
