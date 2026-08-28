#!/usr/bin/env python3
"""Probes the real video duration of every meeting currently missing a
transcript, and writes the results to a CSV queue -- lets a human (or a
future batch run) prioritize scripts/transcribe_backlog_locally.py's
oldest-first queue by *how long each meeting actually is* instead of
picking blind.

Reads GET /internal/transcription-backlog the same way
transcribe_backlog_locally.py does (same ARCHIVE_BASE_URL/
ARCHIVE_INGEST_TOKEN env vars, same _get_candidates()/_base_url()/
_headers() helpers, imported directly from that module rather than
duplicated), but probes duration from each candidate's already-stored
video_url via app/platforms/media_probe.probe_duration() -- no adapter
re-resolve, no finder registry. That is a deliberate scope cut: a full
fresh re-resolve per candidate (register_all_finders() + get_finder() +
finder.resolve()) is what transcribe_backlog_locally.py does because it
is about to *use* the fresh video_url; this script only wants to know how
long the media is, and the stored video_url from the last resolve is good
enough for that on every platform except a signed/expiring URL -- which
just fails the probe cleanly (recorded as a skip, not a crash) rather
than silently producing a wrong duration.

Two categories are skipped rather than probed, and both are recorded in
the output with a reason, never silently dropped:
  * no video_url at all (can't ever get a transcript this way)
  * video_format == "youtube" (a youtube.com/embed/ page, not a directly
    probeable media URL -- same pre-filter transcribe_backlog_locally.py's
    process_one() already applies, see that function's own comment)

Concurrency, not sequential: ffprobe is network-bound, not CPU-bound the
way Whisper is, so unlike the transcription scripts this parallelizes
several probes at once (--concurrency, default 6) rather than one at a
time -- at up to 508 real candidates (2026-08-27 count) and a worst case
of _SUBPROCESS_TIMEOUT_SECONDS (120s) per probe on a ChampDS-style
seek-hostile source (see media_probe.extract_full_audio()'s own docstring
for why that specific host is slow even just to read metadata), a
sequential sweep could take most of a day; a modest concurrency cap keeps
this to under an hour while still not hammering any one host harder than
this script's other network calls already do.

Resumable: writes one CSV row per candidate as each probe finishes (not
buffered to the end), and skips a URL already present in an existing
output file on a re-run -- same "commit per row, skip already-current
rows" shape CLAUDE.md asks of every backfill script here, so Ctrl-C
mid-run loses nothing already probed.
"""

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

# Must run before `import aiohttp` -- see transcribe_backlog_locally.py's
# own module-level comment for the full incident this works around.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms.media_probe import probe_duration  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcribe_backlog_locally as tbl  # noqa: E402

load_dotenv()

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "local_transcription_backups"
    / "backlog_video_durations.csv"
)

CSV_FIELDS = [
    "source_url",
    "video_url",
    "platform",
    "title",
    "jurisdiction",
    "date",
    "video_format",
    "duration_seconds",
    "duration_hms",
    "skip_reason",
]


def _hms(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _load_already_probed(output_path: Path) -> set:
    if not output_path.exists():
        return set()
    with output_path.open(newline="") as f:
        return {row["source_url"] for row in csv.DictReader(f)}


async def _probe_one(page: dict, *, semaphore: asyncio.Semaphore) -> dict:
    source_url = page["source_url_normalized"]
    row = {
        "source_url": source_url,
        "video_url": page.get("video_url") or "",
        "platform": page.get("platform") or "",
        "title": page.get("title") or "",
        "jurisdiction": page.get("jurisdiction") or "",
        "date": page.get("date") or "",
        "video_format": page.get("video_format") or "",
        "duration_seconds": "",
        "duration_hms": "",
        "skip_reason": "",
    }

    if not page.get("video_url"):
        row["skip_reason"] = "no video_url on this page"
        return row
    if page.get("video_format") == "youtube":
        row["skip_reason"] = (
            "youtube-delegated embed -- not a directly probeable media URL"
        )
        return row

    async with semaphore:
        duration = await probe_duration(page["video_url"], source_page_url=source_url)

    if duration is None:
        row["skip_reason"] = "ffprobe failed or timed out"
        return row

    row["duration_seconds"] = f"{duration:.1f}"
    row["duration_hms"] = _hms(duration)
    return row


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="CSV path to write/resume"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Max ffprobe calls in flight at once (default 6)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Probe at most this many NEW (not-yet-probed) candidates",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    already_probed = _load_already_probed(args.output)
    write_header = not args.output.exists()

    async with aiohttp.ClientSession() as session:
        candidates = await tbl._get_candidates(session, limit=None)

    todo = [p for p in candidates if p["source_url_normalized"] not in already_probed]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(
        f"{len(candidates)} candidates on the backlog, {len(already_probed)} "
        f"already probed, {len(todo)} to probe now."
    )
    if not todo:
        print("Nothing new to probe.")
        return

    semaphore = asyncio.Semaphore(args.concurrency)
    done = 0
    with args.output.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
            f.flush()

        tasks = [asyncio.create_task(_probe_one(p, semaphore=semaphore)) for p in todo]
        for task in asyncio.as_completed(tasks):
            row = await task
            writer.writerow(row)
            f.flush()
            done += 1
            label = row["duration_hms"] or f"SKIP: {row['skip_reason']}"
            print(f"[{done}/{len(todo)}] {row['source_url']} -> {label}")

    print(f"Done. Results in {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
