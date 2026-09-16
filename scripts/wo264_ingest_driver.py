"""WO-264 close-out: ingest driver for governments whose hand-read
decision is "pass" (see wo264_hand_read_decisions.csv, `verdict=pass`).

For each passing row:
  1. Resolve the chosen video URL through the real production adapter
     (app.platforms.base.get_finder/detect_platform) -- same call every
     other sweep in this repo uses, never a new resolve path.
  2. If result.segments is non-empty (tier 1/2, real captions): ingest
     directly via wo134's _ingest_with_retry(), sending gov_id in the
     payload (WO-222). Pin per this WO's rule: channel=@handle ONLY when
     `own_channel=yes` in the decisions file (a hand-verified own
     channel); otherwise a per-video fallback pin via
     wo134.maybe_write_tenant_override() (never a blank/channel-wide pin
     on an unverified channel).
  3. If result.segments is empty but result.video_url is present (tier
     3): probe via app.platforms.queue_probe.finish_candidate(). A
     `deferred`/`already-deferred` outcome on a row flagged
     `long_only_queue_anyway=yes` (Ryan's 2026-09-12 rule: never defer a
     long-only video for length alone once the deeper look found nothing
     shorter) is overridden -- this script appends the queue line and
     pin directly via append_queue_line()/write_pin_row(), bypassing the
     defer branch, and logs that override explicitly.
  4. One meeting per government -- stop at the first candidate that
     ingests or queues successfully for a gov_id.

Writes one row per government to a log CSV (resumable: a gov_id already
logged is skipped on a re-run).

Input shape: `--decisions` takes a CSV with either (a) `gov_id`, `name`,
`state`, `chosen_url`, `own_channel`, `own_channel_handle`,
`long_only_queue_anyway` and no `verdict` column (a file pre-filtered to
pass-only rows -- this WO's own `research/wo264_all_passes.csv`, built by
merging `wo264_candidate_decisions.csv`/`wo264_platform_decisions.csv`/
`wo264_nonvideo_final.csv` down to their `verdict == "pass"` rows), or
(b) the same columns plus a `verdict` column, filtered to `pass` rows
automatically.

Usage (repo root, venv active):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo264_ingest_unused.db" \\
        .venv/bin/python scripts/wo264_ingest_driver.py \\
        --decisions /path/to/wo264_all_passes.csv \\
        --log /path/to/wo264_ingest_log.csv
"""

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    detect_platform,
    get_finder,
    UnsupportedPlatformError,
    CalendarPageError,
)
from app.platforms import queue_probe  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts import wo134_confirmed_hits_ingest as wo134  # noqa: E402

register_all_finders()

GOV_DELAY_SECONDS = 1.5
CALLER = "wo264_closeout"


def _already_logged(log_path: Path) -> dict:
    done = {}
    if log_path.exists():
        with log_path.open(newline="") as f:
            for row in csv.DictReader(f):
                done[row["gov_id"]] = row
    return done


async def process_one(session, row: dict) -> dict:
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    url = row["chosen_url"]
    own_channel = (row.get("own_channel") or "").strip().lower() == "yes"
    long_only_queue_anyway = (
        row.get("long_only_queue_anyway") or ""
    ).strip().lower() == "yes"

    out = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "url": url,
        "outcome": "",
        "page_url": "",
        "note": "",
    }

    try:
        platform = detect_platform(url)
        finder = get_finder(platform)
    except UnsupportedPlatformError as e:
        out["outcome"] = "error"
        out["note"] = f"unsupported platform: {e}"
        return out

    try:
        result = await finder.resolve(url)
    except CalendarPageError as e:
        out["outcome"] = "error"
        out["note"] = f"calendar page, not single meeting: {e}"
        return out
    except Exception as e:  # noqa: BLE001
        out["outcome"] = "error"
        out["note"] = f"resolve raised: {type(e).__name__}: {e}"
        return out

    wo134.apply_display_jurisdiction(result, gov_id)

    if result.segments:
        payload = result.model_dump()
        payload["gov_id"] = gov_id
        try:
            response = await wo134._ingest_with_retry(
                session, payload, normalize_url(url)
            )
        except Exception as e:  # noqa: BLE001
            out["outcome"] = "error"
            out["note"] = f"ingest raised: {e}"
            return out
        if response is None:
            out["outcome"] = "error"
            out["note"] = (
                f"resolved {len(result.segments)} segments but POST to Archive failed twice"
            )
            return out
        # A blank own_channel_handle (own_channel=yes but no real @handle
        # confirmed -- e.g. a Vimeo account, which has no YouTube-style
        # @handle at all) must still fall back to the per-video pin, not
        # write nothing -- a bug caught live 2026-09-12 (Victor city, ID)
        # where the `else` branch was unreachable whenever own_channel was
        # true, leaving a real ingested video with no pin at all for a
        # future re-resolve to key off of.
        pinned_own = False
        if own_channel and platform in wo134.SHARED_HOST_PLATFORMS:
            handle = row.get("own_channel_handle", "")
            if handle:
                queue_probe.write_pin_row(
                    host=urlparse(result.video_url or url).netloc.lower()
                    or "www.youtube.com",
                    match=f"channel=@{handle}",
                    gov_id=gov_id,
                    strength="fallback",
                    source=CALLER,
                    evidence=f"{name}, {state} -- WO-264 close-out, hand-verified own channel",
                )
                pinned_own = True
        if not pinned_own:
            wo134.maybe_write_tenant_override(
                platform, result, url, gov_id, f"{name}, {state}", CALLER
            )
        out["outcome"] = "ingested_tier1_2"
        out["page_url"] = response.get("url", "")
        out["note"] = f"{len(result.segments)} transcript segments"
        return out

    if result.video_url:
        pin = None
        if own_channel and platform in wo134.SHARED_HOST_PLATFORMS:
            handle = row.get("own_channel_handle", "")
            if handle:
                pin = {
                    "host": "www.youtube.com",
                    "match": f"channel=@{handle}",
                    "gov_id": gov_id,
                    "strength": "fallback",
                    "source": CALLER,
                    "evidence": f"{name}, {state} -- WO-264 close-out, hand-verified own channel",
                }
        if pin is None:
            # Same fallback-on-blank-handle fix as the tier-1/2 branch
            # above -- own_channel=yes with no real @handle (e.g. a
            # Vimeo account) must still get a per-video pin.
            match = wo134._tenant_override_match(platform, result, url)
            host = wo134._tenant_override_host(platform, result, url)
            if match and host:
                pin = {
                    "host": host,
                    "match": match,
                    "gov_id": gov_id,
                    "strength": "fallback",
                    "source": CALLER,
                    "evidence": f"{name}, {state} -- WO-264 close-out",
                }

        outcome = await queue_probe.finish_candidate(
            url,
            video_url=result.video_url,
            source_url=result.source_url or url,
            platform=platform,
            gov_id=gov_id,
            jurisdiction=result.jurisdiction or f"{name}, {state}",
            title=result.title or "",
            pin=pin,
            caller=CALLER,
        )
        if outcome.action in ("queued", "already-queued"):
            out["outcome"] = "queued_tier3"
            out["note"] = (
                f"probe accepted ({outcome.probe.duration_seconds}s): {outcome.action}"
            )
            return out
        if outcome.action in ("deferred", "already-deferred", "skipped-deferred"):
            if long_only_queue_anyway:
                # Ryan's 2026-09-12 rule: never defer a long-only video
                # for length alone once the deeper look found nothing
                # shorter -- queue it anyway, bypassing finish_candidate's
                # auto-defer branch.
                queued = queue_probe.append_queue_line(
                    url,
                    result.source_url or url,
                    queue_path=queue_probe.TIER3_QUEUE_FILE,
                )
                pinned = False
                if pin:
                    pinned = queue_probe.write_pin_row(
                        host=pin["host"],
                        match=pin["match"],
                        gov_id=pin["gov_id"],
                        strength=pin["strength"],
                        source=pin["source"],
                        evidence=pin["evidence"],
                    )
                out["outcome"] = "queued_tier3_long_only_override"
                out["note"] = (
                    f"probe duration {outcome.probe.duration_seconds}s over 90min; queued anyway "
                    f"per Ryan's 2026-09-12 rule (queued={queued}, pinned={pinned})"
                )
                return out
            out["outcome"] = "deferred_long"
            out["note"] = (
                f"probe over 90min ({outcome.probe.duration_seconds}s): {outcome.action}"
            )
            return out
        out["outcome"] = "rejected_by_probe"
        out["note"] = (
            f"probe rejected ({outcome.probe.verdict}): {outcome.probe.reason}"
        )
        return out

    out["outcome"] = "no_video_after_resolve"
    out["note"] = "resolved but no segments and no video_url"
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", default="wo264_hand_read_decisions.csv")
    ap.add_argument("--log", default="wo264_ingest_log.csv")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    decisions_path = Path(args.decisions)
    log_path = Path(args.log)
    with decisions_path.open(newline="") as f:
        all_rows = list(csv.DictReader(f))
        if "verdict" in (all_rows[0].keys() if all_rows else []):
            rows = [
                r
                for r in all_rows
                if (r.get("verdict") or "").strip().lower() == "pass"
            ]
        else:
            # wo264_all_passes.csv is pre-filtered to pass-only rows already.
            rows = all_rows
    print(f"{len(rows)} passing rows in {decisions_path}")

    done = _already_logged(log_path)
    todo = [r for r in rows if r["gov_id"] not in done]
    print(f"{len(done)} already logged, {len(todo)} to do")
    if args.limit:
        todo = todo[: args.limit]

    fieldnames = ["gov_id", "name", "state", "url", "outcome", "page_url", "note"]
    is_new = not log_path.exists()
    async with aiohttp.ClientSession() as session:
        with log_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if is_new:
                writer.writeheader()
            for i, row in enumerate(todo):
                if i:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
                try:
                    result = await process_one(session, row)
                except Exception as e:  # noqa: BLE001
                    result = {
                        "gov_id": row["gov_id"],
                        "name": row["name"],
                        "state": row["state"],
                        "url": row["chosen_url"],
                        "outcome": "error",
                        "page_url": "",
                        "note": f"unhandled: {type(e).__name__}: {e}",
                    }
                writer.writerow(result)
                f.flush()
                print(
                    f"[{i + 1}/{len(todo)}] {result['gov_id']} {result['name']} -> {result['outcome']}",
                    flush=True,
                )


if __name__ == "__main__":
    asyncio.run(main())
