"""Probe tier-3 queue candidates' duration/date/size before they become
Archive pages -- CLI wrapper around app/platforms/queue_probe.py
(WO-144). Read-only against the queue itself: this never edits
scripts/tier3_auto_transcription_queue.txt, it only reads it (or a
separate --urls-file) and appends findings to a sidecar CSV.

Usage:

    python scripts/probe_tier3_queue.py --queue --limit 25
    python scripts/probe_tier3_queue.py --urls-file some_candidates.txt

Append-only and resumable: a URL already in the sidecar is skipped on a
later run unless --reprobe is passed, so a long queue can be worked
through across several runs (or by more than one of WO-145/WO-146's
breadth-sweep sessions, each pointed at their own --urls-file) without
re-paying for a URL already probed.

Politeness (CLAUDE.md's "we query sites politely" convention): one host
at a time (a real per-host delay, reusing bulk_ingest.py's own
REQUEST_DELAY_SECONDS), and the whole run stops after 6 consecutive
access-shaped failures (a timeout, a 403/404/429/5xx, a fetch exception)
rather than hammering a host that has started refusing every request --
same reasoning as CLAUDE.md's "stop after 6 consecutive errors" convention
for a sweep across many distinct government-site domains. This never
attempts to solve or bypass anything -- a genuine human-verification gate
just surfaces as a normal HTTP failure and gets treated the same as any
other access error, counted and then stopped on.
"""

import argparse
import asyncio
import csv
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

# Must run before `import aiohttp` -- see scripts/transcribe_backlog_
# locally.py's own module-level fix and CLAUDE.md's matching convention
# bullet: a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp caches its default SSLContext the instant `import
# aiohttp` runs anywhere in the process, not lazily on first connection.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    ProbeResult,
    append_probe_row,
    probe_queue_entry,
)
from scripts.bulk_ingest import REQUEST_DELAY_SECONDS  # noqa: E402
from scripts.feed_tier3_auto_transcription import (  # noqa: E402
    QUEUE_FILE,
    _parse_queue_line,
)

DEFAULT_SIDECAR = DEFAULT_SIDECAR_PATH

# Reasons whose text marks an access failure (couldn't even look) rather
# than a content finding (looked, and it was dead/implausible) -- same
# two-class split docs/BREADTH_SWEEP_BRIEF.md's "Reject reasons" section
# draws for the breadth sweep's own reject reasons.
_ACCESS_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "unreachable",
    "returned http 5",
    "returned http 403",
    "returned http 404",
    "returned http 429",
    "fetch failed",
    "fetch raised",
    "connection",
)
_CONSECUTIVE_ERROR_STOP_THRESHOLD = 6


def _is_access_error(reason: str) -> bool:
    lowered = reason.lower()
    return any(marker in lowered for marker in _ACCESS_ERROR_MARKERS)


class _HostGate:
    """One host at a time, with a real delay between requests to the same
    host -- doesn't limit overall concurrency (that's --concurrency's
    job), just paces repeated hits to one host when several candidates
    happen to share it."""

    def __init__(self, delay_seconds: float):
        self._delay = delay_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def wait_turn(self, host: str) -> None:
        async with self._lock_for(host):
            last = self._last_call.get(host)
            if last is not None:
                remaining = self._delay - (time.monotonic() - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_call[host] = time.monotonic()


def _load_probed_urls(sidecar_path: Path) -> set:
    if not sidecar_path.exists():
        return set()
    seen = set()
    with sidecar_path.open(newline="") as f:
        for row in csv.DictReader(f):
            url = row.get("url")
            if url:
                seen.add(url)
    return seen


async def _process_one(
    gate: _HostGate,
    url: str,
    sidecar_path: Path,
    semaphore: asyncio.Semaphore,
    state: dict,
) -> Optional[ProbeResult]:
    async with semaphore:
        if state["stopped"]:
            return None
        host = urlparse(url).netloc
        await gate.wait_turn(host)
        if state["stopped"]:
            return None

        result = await probe_queue_entry(url)
        append_probe_row(sidecar_path, result)
        print(
            f"[{result.verdict}] {url} -- {result.reason or f'{result.duration_seconds:.1f}s'}"
        )

        if result.verdict == "reject-dead" and _is_access_error(result.reason or ""):
            state["consecutive_errors"] += 1
        else:
            state["consecutive_errors"] = 0

        if state["consecutive_errors"] >= _CONSECUTIVE_ERROR_STOP_THRESHOLD:
            if not state["stopped"]:
                print(
                    f"[STOP] {_CONSECUTIVE_ERROR_STOP_THRESHOLD} consecutive access "
                    f"errors -- stopping early, remaining candidates untouched this run."
                )
            state["stopped"] = True
        return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--urls-file",
        type=Path,
        help=(
            "File of URLs, one per line (optional tab-separated source_url "
            "second column) -- same line shape as the tier-3 queue file."
        ),
    )
    source.add_argument(
        "--queue",
        action="store_true",
        help=(
            "Probe scripts/tier3_auto_transcription_queue.txt directly. "
            "Read-only -- this never edits the queue file."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Probe at most this many URLs this run."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max simultaneous probes (default 4).",
    )
    parser.add_argument(
        "--sidecar",
        type=Path,
        default=DEFAULT_SIDECAR,
        help=f"CSV sidecar to append to (default {DEFAULT_SIDECAR}).",
    )
    parser.add_argument(
        "--reprobe",
        action="store_true",
        help="Re-probe a URL even if it's already in the sidecar (appends a new row).",
    )
    return parser


async def main() -> None:
    args = _build_arg_parser().parse_args()
    source_path = QUEUE_FILE if args.queue else args.urls_file
    if not source_path.exists():
        print(f"No file found at {source_path} -- nothing to do.")
        return

    lines = [
        line.strip() for line in source_path.read_text().splitlines() if line.strip()
    ]
    urls = []
    seen = set()
    for line in lines:
        url, _source_override = _parse_queue_line(line)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    already_probed = set() if args.reprobe else _load_probed_urls(args.sidecar)
    candidates = [u for u in urls if u not in already_probed]
    skipped_already_probed = len(urls) - len(candidates)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    print(
        f"{len(urls)} URL(s) in {source_path.name}, {skipped_already_probed} already "
        f"in {args.sidecar.name} (skipped), probing {len(candidates)} now "
        f"(concurrency={args.concurrency})."
    )
    if not candidates:
        return

    register_all_finders()

    gate = _HostGate(delay_seconds=REQUEST_DELAY_SECONDS)
    semaphore = asyncio.Semaphore(args.concurrency)
    state = {"consecutive_errors": 0, "stopped": False}

    results = await asyncio.gather(
        *[_process_one(gate, url, args.sidecar, semaphore, state) for url in candidates]
    )

    tally = Counter(r.verdict for r in results if r is not None)
    attempted = sum(tally.values())
    skipped_for_stop = len(candidates) - attempted

    print()
    print(f"Probed {attempted} of {len(candidates)} candidates this run.")
    for verdict in ("accept", "flag-long", "reject-short", "reject-dead"):
        print(f"  {verdict}: {tally.get(verdict, 0)}")
    print("  (flag-long still counts as accepted -- a long meeting can be real.)")
    if skipped_for_stop:
        print(
            f"  skipped this run (stopped early after "
            f"{_CONSECUTIVE_ERROR_STOP_THRESHOLD} consecutive access errors): "
            f"{skipped_for_stop}"
        )


if __name__ == "__main__":
    asyncio.run(main())
