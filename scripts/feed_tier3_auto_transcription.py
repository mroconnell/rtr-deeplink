"""Feeds the worker's auto-transcription idle-time mechanism
(worker/main.py's maybe_generate_auto_job(), see BACKLOG_DONE.md's
2026-08-09 "auto-idle-time transcription job generation" entry) a fixed
batch of "tier 3" pages per run -- same pattern as
feed_granicus_auto_transcription.py, for a different platform mix.

Why this needed a NEW script rather than reusing feed_granicus_
auto_transcription.py's bulk_ingest.py call directly: that script's real
(non-dry-run) ingest still goes through bulk_ingest.py's own client-side
gate (`segments or agenda_items or agenda_link`), which Granicus pages
pass because they carry real agenda_items (AgendaViewer.php chapter
markers) even with zero transcript. This queue's pages -- confirmed live
2026-08-16 to have a real video_url but zero segments AND zero
agenda_items AND no agenda_link -- would be silently skipped by that same
gate and never become a real MeetingPage for the worker to find.

/internal/ingest itself (archive/main.py) has no such requirement --
confirmed reading its source: it's `crud.ingest_resolution(payload, ...)`
unconditionally once the auth token checks out. The segments-or-agenda
gate is a courtesy check bulk_ingest.py/app/main.py's /api/resolve choose
to apply themselves, not something the server enforces. So this script
resolves each URL and pushes it directly (mirroring bulk_ingest.py's own
_ingest() POST shape) whenever a real video_url comes back, regardless of
transcript/agenda content -- exactly the "video present, no transcript"
state find_auto_transcription_candidate() (archive/db/crud.py) is built
to find. worker/main.py's own feasibility check re-resolves live at
pickup time anyway (get_finder(platform) + finder.resolve()), so a stale
or now-broken candidate here just fails cleanly there, the same way a
Granicus queue entry would.

Run via GitHub Actions (.github/workflows/feed-tier3-transcription.yml)
every 6 hours, cron-offset from feed-granicus-transcription.yml's ":13"
so the two don't land in the same minute (same reasoning as daily-report.
yml / send-search-alerts.yml's offset).

**Batch size lowered 48 -> 12 again, 2026-08-22 -- the 48 was sized
from a throughput figure production never actually reached.** The
2026-08-21 raise (see BACKLOG_DONE.md's "Tier-3 feed rate raised to
match real two-worker throughput") derived 192/day from "each worker
~5x realtime on a real completed 900s chunk, ~10x combined", implying
roughly 200 meetings/day. Measured the next day, real output was **35
completed jobs in 24h** (/internal/transcription-queue-stats) -- about
6x under the estimate. Against that, this script at 48/6h plus
feed_granicus_auto_transcription.py's 12/6h pushed ~240 URLs/day, ~210
of which became live pages at this queue's ~88% feasibility rate, so the
site gained transcript-less pages at roughly +150/day (781 of 2,403
archived pages had no good transcript; 478 of 1,577 jurisdictions had
none at all).

**The shortfall is idle workers, not slow ones -- check this before
ever re-raising the rate.** `active_jobs` was **1** against
bulk_queue_transcription_backlog.py's cap of 15 when this was measured.
The hourly top-up workflow that is supposed to keep both workers fed had
created **zero jobs for at least 25 hours**: five runs sampled between
2026-08-21T18:59Z and 2026-08-22T19:39Z each logged "0 created, 8
skipped (of 8 candidates)", and in every run all 8 candidates were
`archive-stream.granicus.com` HLS URLs failing with "ffprobe couldn't
read the media" -- the already-root-caused Granicus origin 504 (see
BACKLOG.md's "Some old/archived Granicus clips' `chunklist.m3u8`
genuinely times out at Granicus's own origin"). The 35 jobs/day were
coming entirely from worker/main.py's own idle-time
maybe_generate_auto_job() trickle. So feeding faster could not have
helped: the constraint sits at job *creation*, downstream of this
script.

Worth stating plainly because it is the tempting wrong answer: the
ffmpeg-timeout retry rate is **not** the explanation. It is real (106
timeout failures across 18 jobs in two days,
/internal/transcription-failure-analysis?days=2) but small as a
throughput tax -- 106 x 120s is ~3.5 hours against ~96 worker-hours
available over the same window, ~4%, consistent with the existing
finding that timeouts account for only 2 of 218 terminal job failures.

12/6h (48/day) restores the pre-2026-08-21 rate. It does not close the
gap on its own -- the Granicus feed contributes another 48/day against
~55-60/day of real output (35 cloud + 15-25 local Whisper) -- see
BACKLOG.md's entry under "Transcription queue & workers" for the
remaining dials and for the top-up-driver bug that deserves the effort
first. Per-request pacing is unchanged either way
(REQUEST_DELAY_SECONDS), and this queue still spans many distinct
government-site domains, so batch size was never a single-domain
hammering question.
"""

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

# Must run before `import aiohttp` -- see scripts/transcribe_backlog_
# locally.py's own longer comment on this same fix (confirmed live
# 2026-08-21: a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp caches its default SSLContext at import time, not
# lazily on first connection). Real incident: without this, every URL in a
# real run failed with SSLCertVerificationError, and since this script
# advances (consumes) the queue file regardless of per-URL outcome, that
# batch was silently dropped from the queue without ever reaching Archive
# -- recovered by hand from git history afterward. Don't remove this.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import aiohttp  # noqa: E402

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (
    detect_platform,
    get_finder,
    UnsupportedPlatformError,
    CalendarPageError,
)  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _ingest, REQUEST_DELAY_SECONDS  # noqa: E402

QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
BATCH_SIZE = 12


async def _push_if_has_video(session: aiohttp.ClientSession, url: str) -> str:
    try:
        platform = detect_platform(url)
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return f"[SKIP] unsupported platform: {url}"

    try:
        result = await finder.resolve(url)
    except CalendarPageError as e:
        return f"[SKIP] calendar page, not a single meeting: {url} ({e})"
    except Exception as e:
        return f"[SKIP] resolve raised: {url} ({e})"

    if not result.video_url:
        return f"[SKIP] no video found on re-resolve: {url}"

    normalized = normalize_url(url)
    try:
        response = await _ingest(session, result.model_dump(), normalized)
    except Exception as e:
        return f"[FAIL] ingest failed: {url} ({e})"

    page_url = response.get("url") if response else None
    return f"[OK] {url} -> {page_url or '(no url in response)'}"


async def main() -> None:
    if not QUEUE_FILE.exists():
        print("No queue file found -- nothing to do.")
        return

    urls = [
        line.strip() for line in QUEUE_FILE.read_text().splitlines() if line.strip()
    ]
    if not urls:
        print("Queue is empty -- nothing left to feed. This script can be retired.")
        return

    batch, remainder = urls[:BATCH_SIZE], urls[BATCH_SIZE:]
    print(f"Feeding {len(batch)} URL(s), {len(remainder)} remaining after this run.")

    register_all_finders()

    async with aiohttp.ClientSession() as session:
        for i, url in enumerate(batch):
            print(await _push_if_has_video(session, url))
            if i < len(batch) - 1:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

    # Advance the queue regardless of individual outcomes -- same "don't
    # retry failing commands in a loop" reasoning as
    # feed_granicus_auto_transcription.py.
    QUEUE_FILE.write_text("\n".join(remainder) + ("\n" if remainder else ""))


if __name__ == "__main__":
    asyncio.run(main())
