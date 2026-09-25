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
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Tuple

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
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    append_probe_row,
    has_owner,
    parse_queue_line,
    probe_queue_entry,
)
from app.platforms.media_probe import transcription_media_url  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import (  # noqa: E402
    _base_url,
    _headers,
    _ingest,
    REQUEST_DELAY_SECONDS,
)

QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
BATCH_SIZE = 12

# WO-937: a durable per-line record of _push_if_has_video()'s own
# [OK]/[SKIP]/[FAIL]/[NO-OWNER] result -- before this, the only place a
# result lived was stdout, so once a line is popped off QUEUE_FILE (which
# advances "regardless of individual outcomes," see main()'s own comment),
# its fate only survived in that one day's GitHub Actions run transcript.
# Real gap raised directly by Ryan, 2026-09-09, mid-run on the
# 2,404-candidate batch -- every other batch ingest script here
# (nationwide_*_ingest.py, wo130_county_ingest.py,
# wo134_confirmed_hits_ingest.py) already writes a resumable per-row CSV
# log; this was the one that didn't. Append-only, same shape as the probe
# sidecar CSV (DEFAULT_SIDECAR_PATH) -- and, like that file, the
# .github/workflows/feed-tier3-transcription.yml workflow's own commit
# step must `git add` this path too or every run's rows are discarded
# with the ephemeral runner (WO-254's own real incident, for the probe
# sidecar CSV, before that workflow fix).
FEED_LOG_CSV = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue_feed_log.csv"
FEED_LOG_HEADER = ["timestamp", "url", "tag", "detail"]


def _append_feed_log_row(url: str, result: str) -> None:
    """`result` is `_push_if_has_video()`'s own `"[TAG] rest of message"`
    string -- split into a `tag` column (OK/SKIP/FAIL/NO-OWNER) and a
    `detail` column so a later reader can filter/count by outcome without
    parsing free text."""
    tag = "UNKNOWN"
    detail = result
    if result.startswith("[") and "]" in result:
        end = result.index("]")
        tag = result[1:end]
        detail = result[end + 1 :].strip()
    is_new = not FEED_LOG_CSV.exists()
    FEED_LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    with FEED_LOG_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(FEED_LOG_HEADER)
        writer.writerow(
            [datetime.now(timezone.utc).isoformat(timespec="seconds"), url, tag, detail]
        )


def _parse_queue_line(line: str) -> Tuple[str, Optional[str], Optional[str]]:
    """A queue line is a bare URL, `URL<TAB>SOURCE_URL` when the queued
    URL is itself a bare video link discovered via a *different* page
    (see BACKLOG_DONE.md's tier3 source_url-override entry), or, as of
    WO-1016, `URL<TAB>SOURCE_URL<TAB>GOV_ID` when the sweep that queued
    this line already knew the government. The second field, when
    present, overrides what gets recorded as the meeting's source_url --
    otherwise a bare YouTube/Vimeo link would be ingested under its own
    URL as source_url, the exact bug already fixed for direct ingests (a
    reader's "View original source" link should point at the government
    page the video was found on, not the video host). The third field, a
    gov_id, is handled by `_push_if_has_video()`'s own precedence rule
    against `has_owner()`'s pin -- see that function's docstring.

    This is now a thin wrapper over `app.platforms.queue_probe.
    parse_queue_line()` (WO-1016) -- kept as a module-level name here,
    rather than inlined at every call site, because `scripts/youtube_
    drip.py` and `scripts/probe_tier3_queue.py` already import this exact
    name (`from scripts.feed_tier3_auto_transcription import
    _parse_queue_line`); moving the real parsing logic into queue_probe.py
    (already the shared home for queue-line decisions via
    `finish_candidate()`) means every reader tolerates a 3rd field
    identically instead of drifting. Was a 2-tuple (url, source_url)
    before WO-1016; every existing caller was updated in the same change
    to unpack the new 3rd `gov_id` element (see BACKLOG_DONE.md's
    WO-1016 entry for the full list)."""
    return parse_queue_line(line)


async def _push_if_has_video(
    session: aiohttp.ClientSession,
    url: str,
    source_url_override: Optional[str] = None,
    line_gov_id: Optional[str] = None,
    *,
    probe_sidecar_path: Path = DEFAULT_SIDECAR_PATH,
) -> str:
    """`probe_sidecar_path` defaults to the tracked CSV (this script's own
    GitHub Actions run and every other caller). WO-248: the always-on
    YouTube drip (scripts/youtube_drip.py) passes its own LOCAL, gitignored
    buffer here instead -- appending to the tracked file hundreds of times
    a day, hours apart from the one daily commit, is what produced a merge
    conflict on every `git pull` on the drip Mac. The drip's daily
    `advance` step folds that local buffer into the tracked file once,
    right before the commit, the same shape as the queue file itself."""
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

    # WO-1045: a server-only stream (ChampDS VOD2) is transcribable too.
    media_url = transcription_media_url(result)
    if not media_url:
        return f"[SKIP] no video found on re-resolve: {url}"

    # WO-144: probe the resolved video before it becomes a real Archive
    # page -- the worker's own claim-time duration gate
    # (worker/main.py's probe_duration()/is_plausible_meeting_duration())
    # still runs later as a second, independent check, but only a probe
    # here stops a dead link or an implausibly short clip from becoming a
    # page at all. Same sidecar CSV scripts/probe_tier3_queue.py writes
    # to, so a row from either path tells the same story.
    probe = await probe_queue_entry(
        url,
        video_url=media_url,
        source_page_url=result.source_url,
        platform=platform,
        # WO-937: without this, a direct-file candidate whose URL itself
        # carries no recognized extension (a ChampDS DOWNLOAD-MEDIA
        # redirect, a CivicPlus DocumentCenter link) lost the one signal
        # probe_queue_entry()'s dispatch needs once this caller already
        # has `result` in hand -- the resolve-from-scratch path (when a
        # caller passes no video_url at all) already carried this
        # through correctly; only a caller passing video_url= separately
        # could drop it. Confirmed live via this same gap in
        # wo169_probe_rejected_rerun.py's own _real_probe_hook() (see
        # BACKLOG.md's matching entry) -- this is the same class of bug
        # in a second caller, not a new one.
        video_format=result.video_format,
    )
    append_probe_row(probe_sidecar_path, probe)
    if probe.verdict.startswith("reject-"):
        return f"[SKIP] {probe.verdict}: {probe.reason} ({url})"

    if source_url_override:
        result.source_url = source_url_override

    # WO-346: refuse to advance a line whose source_url has no owner --
    # a MULTI_GOV_HOSTS host (youtube.com, vimeo.com, ...) with no
    # tenant_overrides.csv pin matching THIS page ingests as
    # rtr:unknown:{host} (no hub link, no identity), exactly the gap the
    # tier-3 queue ownership audit found sitting unrecorded across 478 of
    # 3,012 queue+deferred lines. Checked on the FINAL source_url (after
    # source_url_override above), since that's what
    # archive/db/crud.py::_resolve_page_government() actually parses the
    # tenant host from. This line is put BACK into the queue (not
    # dropped) so it can still ingest once a pin exists -- see main()'s
    # own handling of a [NO-OWNER] result below.
    owned, owner_gov_id, reason = has_owner(result.source_url)
    if not owned:
        return f"[NO-OWNER] {reason} ({url})"

    # WO-1016: a queue line can now carry its OWN gov_id (a research
    # sweep that already knew the government, filed as the line's 3rd
    # tab field -- see _parse_queue_line()'s own docstring), separate
    # from `owner_gov_id` above (a tenant_overrides.csv pin has_owner()
    # found on a SHARED host). The line's gov_id wins when both exist and
    # agree -- it's the more specific, per-sweep fact. When both exist
    # and DISAGREE, don't guess which one is right (CLAUDE.md's "reports
    # report, they never guess" standard applies just as much to a
    # feeder's own ingest decision as to a written report) -- skip this
    # line with a clear reason instead of ingesting under either gov_id.
    # A line with no gov_id of its own keeps today's behavior unchanged
    # (owner_gov_id, or None on a single-tenant host).
    final_gov_id = owner_gov_id
    if line_gov_id:
        if owner_gov_id and owner_gov_id != line_gov_id:
            return (
                f"[SKIP] gov_id disagreement: queue line says {line_gov_id}, "
                f"tenant_overrides.csv pin says {owner_gov_id} -- not "
                f"ingesting under either without a human check ({url})"
            )
        final_gov_id = line_gov_id

    normalized = normalize_url(url)
    try:
        # already_probed=True: the probe just above ran on this exact
        # video_url. WO-156's gate in bulk_ingest._ingest() only honors
        # that flag when the payload also carries real segments, though
        # -- this queue's payloads never do (tier-3 is video-only by
        # definition), so this still re-probes there today. That's
        # deliberate (see _ingest()'s own docstring): a video-only
        # payload is exactly WO-149's Boardroom-clip shape, so the final
        # gate never skips on an upstream caller's say-so for that shape
        # alone. Passed anyway so the call site is honest about what
        # already happened, and so nothing changes here if segments ever
        # do show up on a future tier-3 payload.
        #
        # gov_id (WO-346, extended WO-1016): send whichever gov_id this
        # line resolved to above (`final_gov_id` -- the line's own gov_id
        # when it had one, else has_owner()'s tenant_overrides.csv pin) --
        # CLAUDE.md's "send the government's id in every ingest payload"
        # rule, so this page keys correctly the moment it ingests even if
        # the Archive service's own deployed copy of tenant_overrides.csv
        # hasn't picked up this WO's new pins yet. None for a
        # single-tenant host with no line gov_id either (has_owner()
        # doesn't run the full ladder to derive one) -- the Archive's own
        # server-side resolve still handles that case fine. _ingest()
        # itself has no gov_id parameter (see bulk_ingest.py's
        # process_one(), the pattern this follows) -- it rides in the
        # payload dict instead.
        payload = result.model_dump()
        if final_gov_id:
            payload["gov_id"] = final_gov_id
        response = await _ingest(
            session,
            payload,
            normalized,
            already_probed=True,
            caller="feed_tier3_auto_transcription",
        )
    except Exception as e:
        return f"[FAIL] ingest failed: {url} ({e})"

    page_url = response.get("url") if response else None
    return f"[OK] {url} -> {page_url or '(no url in response)'}"


def select_batch(
    lines: list[str], claimed_by_drip: Callable[[str], bool], size: int = BATCH_SIZE
) -> tuple[list[str], list[str]]:
    """(batch, remainder): the first `size` lines the YouTube drip does
    NOT claim, and everything else in its original order.

    WO-1063 (2026-09-25): this used to be a plain `lines[:BATCH_SIZE]`.
    The queue also holds YouTube lines, which only the drip Mac may fetch
    (`docs/YOUTUBE_DRIP_RUNBOOK.md`), and once 35 of them were queued at
    the front (#1423) this GitHub-runner feed took them first. YouTube
    answered "Sign in to confirm you're not a bot", the line was logged
    `reject-dead` and dropped: 148 real meetings between 2026-09-22 and
    2026-09-25, none of them dead. A claimed line now stays exactly where
    it is for the drip's feed lane."""
    batch: list[str] = []
    remainder: list[str] = []
    for line in lines:
        url, _src, _gov_id = _parse_queue_line(line)
        if len(batch) < size and not claimed_by_drip(url):
            batch.append(line)
        else:
            remainder.append(line)
    return batch, remainder


def needed_youtube(result: str, refused_before: int, refused_now: int) -> bool:
    """True when a push was stopped by the YouTube guard (a YouTube host
    was refused during it) and didn't still make a page. Such a line
    isn't dead -- it embeds YouTube indirectly (e.g. a CivicClerk event
    whose media is a YouTube video), which the drip's URL check can't
    see -- so the caller keeps it in the queue instead of dropping it."""
    return refused_now > refused_before and not result.startswith("[OK]")


async def main() -> None:
    if not QUEUE_FILE.exists():
        print("No queue file found -- nothing to do.")
        return

    lines = [
        line.strip() for line in QUEUE_FILE.read_text().splitlines() if line.strip()
    ]
    if not lines:
        print("Queue is empty -- nothing left to feed. This script can be retired.")
        return

    # WO-1063: this process must make no YouTube request at all, direct or
    # through an adapter (CLAUDE.md; the runbook's rule 5). Installed here,
    # not at import, because the drip Mac imports this module for
    # `_push_if_has_video()` and must keep its own YouTube access.
    from scripts import youtube_fetch_guard
    from scripts.youtube_drip import _classify_queue_url

    youtube_fetch_guard.install()

    batch, remainder = select_batch(
        lines, lambda url: _classify_queue_url(url)[0], BATCH_SIZE
    )
    print(
        f"Feeding {len(batch)} URL(s), {len(remainder)} remaining after this run "
        "(YouTube lines are left for the drip Mac)."
    )

    register_all_finders()

    # WO-346: a [NO-OWNER] line is put back at the end of the queue
    # rather than dropped -- it's a real, fixable gap (a missing
    # tenant_overrides.csv pin), not a dead link, so the same "advance
    # the queue regardless of individual outcomes" rule below would
    # otherwise permanently lose it the moment its batch slot comes up.
    no_owner_lines: list[str] = []
    youtube_lines: list[str] = []
    async with aiohttp.ClientSession() as session:
        for i, line in enumerate(batch):
            url, source_url_override, line_gov_id = _parse_queue_line(line)
            refused_before = len(youtube_fetch_guard.REFUSED)
            result = await _push_if_has_video(
                session, url, source_url_override, line_gov_id
            )
            if needed_youtube(result, refused_before, len(youtube_fetch_guard.REFUSED)):
                result = f"[YOUTUBE] needs YouTube, left in the queue: {url} ({result})"
                youtube_lines.append(line)
            print(result)
            _append_feed_log_row(url, result)
            if result.startswith("[NO-OWNER]"):
                no_owner_lines.append(line)
            if i < len(batch) - 1:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

    if no_owner_lines:
        print(
            f"[NO-OWNER] {len(no_owner_lines)} line(s) refused and left in the "
            "queue -- needs a tenant_overrides.csv pin (see BACKLOG.md's "
            "queue-ownership entry / WO-346)."
        )
        remainder = remainder + no_owner_lines

    if youtube_lines:
        # WO-1063: same reasoning as [NO-OWNER] -- not a dead link. The
        # drip Mac can't claim these by URL either (see BACKLOG.md), so
        # they go to the end rather than blocking the front.
        print(
            f"[YOUTUBE] {len(youtube_lines)} line(s) needed YouTube and were left "
            "in the queue."
        )
        remainder = remainder + youtube_lines

    # Advance the queue regardless of individual outcomes -- same "don't
    # retry failing commands in a loop" reasoning as
    # feed_granicus_auto_transcription.py. The one exception is a
    # [NO-OWNER] line (folded back into `remainder` above): that's a
    # fixable gap, not a dead link, so it stays in the queue instead of
    # being lost the way a genuine failure is.
    QUEUE_FILE.write_text("\n".join(remainder) + ("\n" if remainder else ""))

    # Report the new depth to the Archive so its own
    # /internal/transcription-queue-stats reads a real, current number
    # from the database instead of needing this file present in its
    # deploy tree (see archive/db/models.py's Tier3QueueState docstring).
    # Best-effort: the queue file above is the real source of truth, so a
    # failed report here shouldn't fail the whole run -- the next run's
    # report just catches the count back up.
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{_base_url()}/internal/tier3-queue-remaining",
                params={"remaining": len(remainder)},
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    print(
                        f"[WARN] failed to report queue depth to Archive: "
                        f"HTTP {response.status}"
                    )
    except Exception as e:
        print(f"[WARN] failed to report queue depth to Archive: {e}")


if __name__ == "__main__":
    asyncio.run(main())
