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
yml / send-search-alerts.yml's offset). Batch size reuses Granicus's
12/6h pacing as a starting default -- NOT independently derived from this
queue's actual median video length the way Granicus's was (see
SOURCING_QUEUE.md's "Cadence decided" note); worth revisiting once real
per-platform duration data exists for this mix (escribe/iqm2/civicclerk/
etc., see video_hosting_catalog_combined.csv in rtr-business/research/).
"""

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv()

import aiohttp  # noqa: E402

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder, UnsupportedPlatformError, CalendarPageError  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _ingest, INGEST_TIMEOUT, REQUEST_DELAY_SECONDS  # noqa: E402

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

    urls = [line.strip() for line in QUEUE_FILE.read_text().splitlines() if line.strip()]
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
