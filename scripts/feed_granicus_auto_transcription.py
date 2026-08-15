"""Feeds the worker's auto-transcription idle-time mechanism
(worker/main.py's maybe_generate_auto_job(), see BACKLOG_DONE.md's
2026-08-09 "auto-idle-time transcription job generation" entry) a fixed
batch of Granicus pages per run.

No new transcription-job code needed -- that mechanism already exists and
already runs in production: it picks the oldest MeetingPage missing a
good transcript and self-generates a low-priority job for it whenever the
job queue is empty. This script's only job is to keep candidates flowing
into that pool: pop the next BATCH_SIZE URLs off
scripts/granicus_auto_transcription_queue.txt, real-ingest them (making
them real MeetingPages with a video_url and no transcript -- exactly what
find_auto_transcription_candidate() looks for), and rewrite the queue
file with whatever's left.

The queue itself is the 481 Granicus "agenda-only" pages confirmed live
2026-08-15 to actually have real video (see
rtr-business/research/session_report_2026-08-15.md) -- the whole reason
that confirmation pass mattered is that queueing a page with no video
would just burn worker idle-time on nothing.

Run via GitHub Actions (.github/workflows/feed-granicus-transcription.yml)
every 6 hours, not locally on a schedule -- Granicus (unlike YouTube) has
no cloud-IP caption-fetch blocking, so there's no reason this needs to run
from a residential IP. Cadence (12/6h = 48/day) decided 2026-08-15 from
the real Granicus median meeting length (144 min) and Whisper tiny's ~6x
realtime speed -- see SOURCING_QUEUE.md's "Cadence decided" note for the
full math. At 12/run this queue lasts ~40 runs (~10 days) before it's
exhausted and this script becomes a silent no-op.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = REPO_ROOT / "scripts" / "granicus_auto_transcription_queue.txt"
BATCH_SIZE = 12


def main() -> None:
    if not QUEUE_FILE.exists():
        print("No queue file found -- nothing to do.")
        return

    urls = [line.strip() for line in QUEUE_FILE.read_text().splitlines() if line.strip()]
    if not urls:
        print("Queue is empty -- nothing left to feed. This script can be retired.")
        return

    batch, remainder = urls[:BATCH_SIZE], urls[BATCH_SIZE:]
    print(f"Feeding {len(batch)} URL(s), {len(remainder)} remaining after this run.")

    batch_file = REPO_ROOT / "scripts" / "_granicus_auto_batch.txt"
    batch_file.write_text("\n".join(batch) + "\n")

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bulk_ingest.py"), str(batch_file)],
        cwd=REPO_ROOT,
    )
    batch_file.unlink(missing_ok=True)

    # Advance the queue regardless of individual ingest outcomes -- these
    # URLs were already confirmed to have real video during the 2026-08-15
    # gate check; a transient failure here isn't worth retrying forever
    # and holding up the rest of the queue (same "don't retry failing
    # commands in a loop" reasoning as everywhere else in this repo).
    QUEUE_FILE.write_text("\n".join(remainder) + ("\n" if remainder else ""))

    if result.returncode != 0:
        print("bulk_ingest.py exited non-zero -- check the log above.", file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
