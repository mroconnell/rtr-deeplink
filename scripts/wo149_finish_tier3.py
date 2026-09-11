#!/usr/bin/env python3
"""WO-149 finishing step: probe every tier-3 candidate `scripts/
wo149_county_ladder_sweep.py` found (`rtr-business/research/
wo149_tier3_pending.csv`) before any of them reach the real queue, per
`docs/BREADTH_SWEEP_BRIEF.md`'s "probe before queue" rule.

**Ported to WO-224's shared `finish_candidate()` helper by WO-226.** The
original version of this script (pre-2026-09-11) hand-rolled its own
cached_verdict + append_queue_line + append_deferred_line + write_pin_row
sequence -- exactly the duplicated logic `app/platforms/queue_probe.py`'s
`finish_candidate()` now exists to replace (see `wo191_finish_tier3.py`/
`wo223_finish_tier3.py`/`wo227_finish_tier3.py` for the same port already
done for their own WOs). Behavior for every row already resolved
(queued or deferred under its existing `meeting_url`) is unchanged --
`finish_candidate()`'s own `cached_verdict()` call replays the same
sidecar row the old code read directly, and `append_queue_line()`/
`append_deferred_line()`/`write_pin_row()` are the identical dedupe-
checked writers.

**New in this port (WO-226): `_pick_probe_url()`.** A handful of rows in
`wo149_tier3_pending.csv` were probed against the wrong URL -- a
CivicClerk/CivicPlus wrapper page with "no probe recipe for this media
shape", or a YouTube `/live/...` URL that hadn't started yet at probe
time -- while the real video sits, unprobed, in the row's own `video_url`
column. `_pick_probe_url()` only ever substitutes `video_url` for
`meeting_url` when the ORIGINAL `meeting_url` is not already satisfied
(not sitting in the queue or deferred file under that exact string) --
so no already-resolved row's queue/deferred line is ever touched or
duplicated under a second, normalized spelling. Every such substitution
must be hand-checked (title vs. government) before being trusted; this
script does not do that hand-check itself -- see WO-226's final report
for the titles/channels checked via YouTube/Vimeo oEmbed before this
residual run.

Writes `probe_verdict`/`probe_reason` back onto `wo149_tier3_pending.csv`
itself (same file, same two columns, as before) so the WO-149 funnel
report can show "rejected by probe" as its own row. Never ingests a
page -- every row here is tier 3 (video, no reachable captions): queue
or deferred file only.

Usage:
    python scripts/wo149_finish_tier3.py
    python scripts/wo149_finish_tier3.py --limit 25
    python scripts/wo149_finish_tier3.py --gov-ids us:county:46083,us:county:20161
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    TIER3_LONG_MEETINGS_DEFERRED_FILE,
    TIER3_QUEUE_FILE,
    finish_candidate,
    is_deferred,
    is_queued,
)

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
PENDING_CSV = RESEARCH_DIR / "wo149_tier3_pending.csv"

HOST_DELAY_SECONDS = 2.0
MAX_CONSECUTIVE_ERRORS = 6

_YT_EMBED_RE = re.compile(r"youtube\.com/embed/([\w-]+)", re.I)

CALLER = "wo149_finish_tier3"

# Real probe verdicts `finish_candidate()`/`cached_verdict()` actually
# produce. Anything else sitting in a row's `probe_verdict` column is a
# sentinel written by a different process (e.g. `duplicate-already-
# queued`, set when an earlier pass matched this row's video to another
# row's already-queued line under a DIFFERENT URL spelling -- the two
# differ only by a trailing query-string character in at least one real
# case, WO-226). Such a row must never be re-probed: `_pick_probe_url()`'s
# own `is_queued()` check only catches an exact-string match, so handing
# a sentinel row to `finish_candidate()` risks appending a second,
# differently-spelled queue line for a video already represented under
# the first one -- confirmed live as a real duplicate (AscWHEa0ay4 /
# Lake County, OH) during WO-226's own dry run, found and removed before
# this guard existed.
_REAL_VERDICTS = {"", "accept", "flag-long", "reject-dead", "reject-short"}


def _normalize_youtube_embed(url: str) -> str:
    m = _YT_EMBED_RE.search(url or "")
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url or ""


def _pick_probe_url(row: dict) -> str:
    """The URL to actually probe for this row. See module docstring:
    only substitutes `video_url` for `meeting_url` when the original
    `meeting_url` is not already sitting in the queue or deferred file
    -- never disturbs an already-resolved row's existing line."""
    original = _normalize_youtube_embed(row.get("meeting_url", ""))
    if is_queued(original, queue_path=TIER3_QUEUE_FILE) or is_deferred(
        original, deferred_path=TIER3_LONG_MEETINGS_DEFERRED_FILE
    ):
        return original
    alt = _normalize_youtube_embed(row.get("video_url", ""))
    if alt and alt != original:
        return alt
    return original


def _video_id(url: str) -> str:
    m = re.search(r"(?:watch\?v=|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else ""


async def main_async(limit, gov_ids):
    if not PENDING_CSV.exists():
        print(f"No {PENDING_CSV} -- nothing to finish.")
        return

    with PENDING_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []
    print(f"{len(rows)} rows in {PENDING_CSV.name}")

    if "probe_verdict" not in fieldnames:
        fieldnames = fieldnames + ["probe_verdict", "probe_reason"]

    to_process = rows
    if gov_ids:
        to_process = [r for r in rows if r["gov_id"] in gov_ids]
    if limit:
        to_process = to_process[:limit]
    print(f"Processing {len(to_process)} row(s)...")

    accepted = already_queued = deferred_count = rejected = skipped_sentinel = 0
    consecutive_errors = 0
    last_host = None

    for i, row in enumerate(to_process):
        if (row.get("probe_verdict") or "") not in _REAL_VERDICTS:
            skipped_sentinel += 1
            print(
                f"[{i + 1}/{len(to_process)}] SKIP {row['gov_id']} -- non-probe "
                f"sentinel verdict already recorded: {row.get('probe_verdict')!r}"
            )
            continue
        probe_url = _pick_probe_url(row)
        redirected = probe_url != _normalize_youtube_embed(row.get("meeting_url", ""))
        # A redirected URL points at a different host than the row's own
        # `platform` describes (e.g. a CivicClerk wrapper's `platform`
        # column is "civicclerk", but the redirected URL is the real
        # youtube.com/vimeo.com video) -- passing the stale platform value
        # through skips `detect_platform()` and sends the URL to the WRONG
        # finder (confirmed live, WO-226: three CivicClerk-wrapped rows
        # probed as "Could not find an event ID in URL path" because
        # `platform="civicclerk"` was passed for a youtube.com URL). Let
        # `finish_candidate()`/`probe_queue_entry()` detect it fresh.
        row_platform = None if redirected else (row.get("platform") or None)

        outcome = await finish_candidate(
            probe_url,
            source_url=row.get("source_url") or None,
            platform=row_platform,
            gov_id=row.get("gov_id", ""),
            jurisdiction=row.get("jurisdiction", ""),
            pin={
                "host": "www.youtube.com",
                "match": _video_id(probe_url),
                "gov_id": row.get("gov_id", ""),
                "strength": "fallback",
                "source": CALLER,
                "evidence": (
                    f"{row.get('jurisdiction', '')} -- WO-149 tier-3 residual "
                    f"finish (WO-226 port to finish_candidate()), per-video pin"
                ),
            }
            if "youtube.com" in probe_url and _video_id(probe_url)
            else None,
            caller=CALLER,
        )
        result = outcome.probe

        if redirected:
            row["meeting_url"] = probe_url
        row["probe_verdict"] = result.verdict
        row["probe_reason"] = result.reason or ""

        if outcome.action == "queued":
            accepted += 1
        elif outcome.action in ("already-queued",):
            already_queued += 1
        elif outcome.action in ("deferred", "already-deferred", "skipped-deferred"):
            deferred_count += 1
        else:
            rejected += 1

        if not outcome.used_cache:
            host = urlparse(probe_url).netloc
            if host == last_host:
                time.sleep(HOST_DELAY_SECONDS)
            last_host = host

        is_access_fail = result.verdict == "reject-dead" and any(
            m in (result.reason or "").lower()
            for m in (
                "timeout",
                "unreachable",
                "http 403",
                "http 404",
                "http 5",
                "connection",
            )
        )
        consecutive_errors = (
            consecutive_errors + 1 if (is_access_fail and not outcome.used_cache) else 0
        )

        cache_tag = " (cached)" if outcome.used_cache else ""
        redirect_tag = " (redirected to video_url)" if redirected else ""
        print(
            f"[{i + 1}/{len(to_process)}] [{result.verdict}{cache_tag}]{redirect_tag} "
            f"{row['gov_id']} {probe_url} action={outcome.action} "
            f"queued={outcome.queued} pinned={outcome.pinned} -- {result.reason or ''}"
        )

        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            print(
                f"ABORTING: {consecutive_errors} consecutive access failures.",
                file=sys.stderr,
            )
            break

    with PENDING_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore"
        )
        w.writeheader()
        w.writerows(rows)

    print(
        f"{len(to_process)} processed: {accepted} newly queued, {already_queued} already "
        f"queued, {deferred_count} deferred, {rejected} rejected, {skipped_sentinel} "
        f"skipped (non-probe sentinel verdict)."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--gov-ids",
        type=str,
        default=None,
        help="Comma-separated gov_id allowlist (default: every row).",
    )
    args = parser.parse_args()
    gov_ids = set(args.gov_ids.split(",")) if args.gov_ids else None
    asyncio.run(main_async(args.limit, gov_ids))


if __name__ == "__main__":
    main()
