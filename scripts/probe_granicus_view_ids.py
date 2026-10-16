"""WO-1965: find each Granicus tenant's video-listing `view_id` once and
store it in `app/utils/jurisdiction_data/granicus_views.csv`.

Why: a Granicus tenant lists its video meetings at
`https://{host}/ViewPublisherRSS.php?view_id=N&mode=video`, and a bare host
like `cityoftacoma.granicus.com` does not say which N. Meeting Finder's
live probe tries only 1-6. The 2026-10-07 measurement (274 tenants with no
known feed) found 25 feeds, and 11 of them were only at ids 44-50. So this
script probes a wider range once, offline, and the app reads the stored
answer (`app.platforms.granicus.known_granicus_views_for()`).

RUN IT FROM THE OFFICE MAC. Cloud sessions get a proxy 403 from
granicus.com, so this script has never made a live request from the
session that wrote it. Its feed parser is tested against real saved
Granicus feeds in `tests/fixtures/`; the probe loop is tested only with a
fake fetcher.

    python scripts/probe_granicus_view_ids.py --hosts-file hosts.txt
    python scripts/probe_granicus_view_ids.py --hosts-file hosts.txt --write

`hosts.txt`: one host or Granicus URL per line; `#` starts a comment.
Hosts can also be given as arguments.

Politeness, the same way Meeting Finder does it:
  - robots.txt is read first. A host whose robots.txt disallows
    `/ViewPublisherRSS.php` for us (`app.utils.robots_check`, the shared
    rule) is skipped. A `Crawl-delay` is obeyed (read the way Meeting
    Finder's Start reads it).
  - Every request goes through Meeting Finder's own `Fetcher`, which keeps
    a minimum gap between two requests to one host (`--delay`, default
    3 s) and refuses any YouTube host. Headless browsing and Wayback are
    off.
  - Only numbered ids are probed (`--ids`, default 1-60). Bare
    `ViewPublisher.php` without a view_id is gated by Granicus on purpose
    and is never requested.
  - A response that redirected away from `ViewPublisherRSS.php` on the
    same host is not counted as a feed.
  - A host that blocks 3 requests in a row is abandoned.

What counts as found: the video feed has at least one item with a
`clip_id` and no "(No Video)" marker (the same test as Meeting Finder's
live probe). Every populated id on a host is recorded, because one
Granicus account can carry several governments' bodies; the feed's
channel title is stored so the app can pick the right one.

A row says only that the host serves that feed. It does not prove which
government owns the host: confirm an owner by hand before pinning or
subscribing (see BACKLOG.md's Granicus lead-spreadsheet entry).

Dry run by default: prints what it found. `--write` appends rows for
(host, view_id) pairs not already in the file. Existing rows are never
edited or removed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms import granicus  # noqa: E402
from app.platforms.resolving.fetch import BudgetExceeded, Fetcher  # noqa: E402

DEFAULT_IDS = "1-60"
DEFAULT_DELAY_S = 3.0
BLOCKED_IN_A_ROW_LIMIT = 3
CSV_FIELDS = ["host", "view_id", "channel_title", "evidence", "checked"]
RSS_PATH = "/ViewPublisherRSS.php"

_CHANNEL_TITLE_RE = re.compile(
    r"<channel>.*?<title>\s*(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))\s*</title>",
    re.IGNORECASE | re.DOTALL,
)
_FEED_SUFFIX_RE = re.compile(r"\s*\((?:Videos|Agendas|Podcast)\s+Feed\)\s*$", re.I)


@dataclass
class FoundView:
    host: str
    view_id: int
    channel_title: str
    clip_count: int
    newest_date: Optional[str]

    def evidence(self) -> str:
        newest = self.newest_date or "no date"
        return (
            f"probe_granicus_view_ids.py: video RSS with {self.clip_count} "
            f"clip item(s), newest {newest}"
        )


def parse_ids(spec: str) -> List[int]:
    """`"1-60"` or `"1-6,44-50"` -> sorted unique positive ints."""
    ids = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            ids.update(range(lo, hi + 1))
        else:
            ids.add(int(part))
    return sorted(i for i in ids if i > 0)


def normalize_host(raw: str) -> Optional[str]:
    raw = raw.split("#", 1)[0].strip()
    if not raw:
        return None
    netloc = urlparse(raw if "://" in raw else f"https://{raw}").netloc
    host = netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def read_hosts(args_hosts: Sequence[str], hosts_file: Optional[Path]) -> List[str]:
    raw: List[str] = list(args_hosts)
    if hosts_file:
        raw.extend(hosts_file.read_text().splitlines())
    hosts: List[str] = []
    for line in raw:
        host = normalize_host(line)
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def parse_video_feed(xml: str, host: str, view_id: int) -> Optional[FoundView]:
    """A populated video feed -> FoundView, else None. Uses the app's own
    item parser (`granicus._parse_rss_items`), so "found" means the same
    clip links the app would list."""
    if not xml or "<item>" not in xml or "(No Video)" in xml:
        return None
    items = granicus._parse_rss_items(xml, host, str(view_id), limit=10_000)
    if not items:
        return None
    title_match = _CHANNEL_TITLE_RE.search(xml)
    title = ""
    if title_match:
        title = (title_match.group(1) or title_match.group(2) or "").strip()
    title = _FEED_SUFFIX_RE.sub("", title)
    dates = [i["date"] for i in items if i.get("date")]
    return FoundView(
        host=host,
        view_id=view_id,
        channel_title=title,
        clip_count=len(items),
        newest_date=max(dates) if dates else None,
    )


async def check_robots(host: str) -> Tuple[bool, Optional[float], str]:
    """(allowed, crawl_delay_seconds, note) for one host. The Disallow
    check is `app.utils.robots_check` (the rule Meeting Finder and the
    length probe use), always enforced here. The Crawl-delay comes from
    `scripts.wo282_recon.fetch_live_robots_v2`, as Meeting Finder's Start
    reads it."""
    from app.utils import robots_check
    from scripts.wo282_recon import fetch_live_robots_v2

    probe_url = f"https://{host}{RSS_PATH}?view_id=1&mode=video"
    allowed, rule = await robots_check.check_url(probe_url)
    if not allowed:
        pattern = rule.pattern if rule else ""
        return False, None, f"robots.txt disallows {RSS_PATH} ({pattern})"
    info = await asyncio.to_thread(fetch_live_robots_v2, host)
    return True, info.get("crawl_delay_seconds"), ""


def _same_feed(requested: str, final: Optional[str]) -> bool:
    if not final:
        return True
    a, b = urlparse(requested), urlparse(final)
    return a.netloc.lower() == b.netloc.lower() and b.path == RSS_PATH


async def probe_host(
    host: str, ids: Sequence[int], fetcher
) -> Tuple[List[FoundView], str]:
    """Probe each id on one host. Returns (found views, note)."""
    found: List[FoundView] = []
    blocked_in_a_row = 0
    for view_id in ids:
        url = f"https://{host}{RSS_PATH}?view_id={view_id}&mode=video"
        try:
            result = await fetcher.fetch(url, need_links=False)
        except BudgetExceeded:
            return found, "fetch budget used up"
        outcome = result.outcome or ""
        if result.challenge or outcome.startswith("blocked") or result.status == 403:
            blocked_in_a_row += 1
            if blocked_in_a_row >= BLOCKED_IN_A_ROW_LIMIT:
                return found, f"blocked {BLOCKED_IN_A_ROW_LIMIT} times in a row"
            continue
        blocked_in_a_row = 0
        if outcome in ("dns-unresolvable", "site-broken"):
            return found, outcome
        if result.status != 200 or not _same_feed(url, result.final_url):
            continue
        view = parse_video_feed(result.html or "", host, view_id)
        if view:
            found.append(view)
    return found, ""


def read_existing(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="") as f:
        return {
            (
                (row.get("host") or "").strip().lower(),
                (row.get("view_id") or "").strip(),
            )
            for row in csv.DictReader(f)
        }


def append_rows(path: Path, views: Sequence[FoundView], checked: str) -> int:
    """Append views whose (host, view_id) is not in the file yet. Returns
    how many rows were written."""
    existing = read_existing(path)
    new_rows = []
    for v in views:
        key = (v.host, str(v.view_id))
        if key in existing:
            continue
        existing.add(key)
        new_rows.append(
            {
                "host": v.host,
                "view_id": str(v.view_id),
                "channel_title": v.channel_title,
                "evidence": v.evidence(),
                "checked": checked,
            }
        )
    if not new_rows:
        return 0
    write_header = not path.exists() or path.stat().st_size == 0
    if not write_header:
        # Keep each appended row on its own line even if the file lost its
        # final newline in an edit.
        with path.open("rb") as f:
            f.seek(-1, 2)
            needs_newline = f.read(1) != b"\n"
        if needs_newline:
            with path.open("a") as f:
                f.write("\n")
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    return len(new_rows)


async def run(args: argparse.Namespace) -> int:
    ids = parse_ids(args.ids)
    hosts = read_hosts(args.hosts, args.hosts_file)
    if not hosts:
        print("No hosts given (use arguments or --hosts-file).", file=sys.stderr)
        return 2
    stored_hosts = {h for h, _ in read_existing(args.views_file)}
    all_found: List[FoundView] = []
    print(f"Probing {len(hosts)} host(s), ids {ids[0]}-{ids[-1]} ({len(ids)} ids)")
    for host in hosts:
        if host in stored_hosts and not args.recheck:
            print(f"{host}: already stored, skipped (use --recheck)")
            continue
        allowed, crawl_delay, note = await check_robots(host)
        if not allowed:
            print(f"{host}: skipped, {note}")
            continue
        fetcher = Fetcher(
            max_fetches=len(ids) * 2,
            per_host_delay_s=args.delay,
            allow_headless=False,
            allow_wayback=False,
        )
        if crawl_delay:
            fetcher.note_crawl_delay(host, float(crawl_delay))
        async with fetcher:
            found, note = await probe_host(host, ids, fetcher)
        all_found.extend(found)
        if found:
            for v in found:
                print(
                    f"{host}: view_id={v.view_id} clips={v.clip_count} "
                    f"newest={v.newest_date or '-'} title={v.channel_title!r}"
                )
        else:
            print(f"{host}: no video feed found" + (f" ({note})" if note else ""))
        if found and note:
            print(f"{host}: stopped early ({note})")
    print(
        f"Found {len(all_found)} feed(s) on {len({v.host for v in all_found})} host(s)."
    )
    if args.write:
        written = append_rows(args.views_file, all_found, date.today().isoformat())
        print(f"Wrote {written} new row(s) to {args.views_file}")
    else:
        print("Dry run: nothing written. Add --write to append new rows.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("hosts", nargs="*", help="Granicus hosts or URLs")
    p.add_argument("--hosts-file", type=Path, help="one host or URL per line")
    p.add_argument("--ids", default=DEFAULT_IDS, help="e.g. 1-60 or 1-6,44-50")
    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help="minimum seconds between two requests to one host",
    )
    p.add_argument(
        "--views-file",
        type=Path,
        default=granicus.GRANICUS_VIEWS_FILE,
        help="the CSV to read and append to",
    )
    p.add_argument("--recheck", action="store_true", help="probe stored hosts too")
    p.add_argument("--write", action="store_true", help="append new rows")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
