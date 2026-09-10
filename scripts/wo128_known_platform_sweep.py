"""WO-128: known-platform / no-Archive-page sweep.

Input: rtr-business/research/coverage_registry/coverage_registry.csv rows
where population >= 5000, archive_pages == "0", known_platform is set,
and gov_kind != "county" (counties are WO-130, running in parallel),
re-confirmed against a fresh `scripts/export_meeting_inventory.py
--source export` pull (a registry row's own archive_pages can be stale --
see CLAUDE.md's "a backlog entry is a lead, not a spec" bullet, same
reasoning applies to any research CSV). No discovery needed here -- the
platform is already known; what's missing is a resolvable per-government
seed URL, exactly the gap `scripts/nationwide_2404_ingest.py` already
solves for its own 2,404-row batch.

Reuses everything `scripts/nationwide_2404_ingest.py`'s `process_row()`
depends on -- `locate_platform_url`, `resolve_civicplus_seed`,
`resolve_seed`, `civicclerk_latest_event_url`, `pick_calendar_candidate`,
`_looks_like_real_meeting`, `youtube_oembed_title`, `_ingest_with_retry`,
`UNSUPPORTED_PLATFORMS` -- unchanged, rather than reimplementing the same
homepage-crawl / CalendarPageError-picking / title-safety-gate logic --
see CLAUDE.md's "reuse existing pipelines" instruction for WO-128. The
input row shape differs (this batch has no two-hop-crawl
`hit_source_urls` of its own, so `_seed_url()` below synthesizes one from
`example_meeting_url` -- the strongest lead jurisdiction_coverage.csv can
offer -- then `example_agenda_or_calendar_url`, then the government's own
homepage `domain` as a last resort), and so does the ingest bar itself:
`process_row()`'s own "agenda_items/agenda_link present, no video" branch
DOES ingest that as `ingested_agenda_only` -- correct for that script's
own task, wrong for this one. WO-128's instructions are explicit: "ONLY
meetings with video... Agenda-only meetings are NOT ingested; record
no-video-found." `process_row_video_only()` below is process_row()'s own
body, copied rather than reused for exactly that one branch (it does the
resolve *and* the ingest POST in the same call, so there is no seam to
hook into from outside) -- every other branch (tier1/2 real ingest,
tier3-video-only queuing, the title-safety gate, dedup) is identical.
Real incident this guards against: the first version of this script
called `process_row()` directly and it ingested one real agenda-only
page (Mobile, AL, civicclerk) before this was caught -- flagged to Ryan
to delete by hand (`POST /internal/admin/delete-pages`,
slug `mobile-al-2026-09-01-city-council-meeting`) rather than done here,
since a production delete is outside what this session does on its own.

CivicPlus rows are handled by the dedicated `adhoc_civicplus_pipeline.py`
instead (this repo's own purpose-built tool for that platform -- see its
docstring for the `NoVideoCandidateFound` handling and automatic
jurisdiction_coverage.csv reject-reason write this script does not
duplicate); this script covers every other platform in the WO-128
candidate list.

Resumable: skips any gov_id already present in the log CSV (any
outcome), same convention as every adhoc_*_pipeline.py sibling.

Run from rtr-deeplink repo root with the shared venv active:
    python scripts/wo128_known_platform_sweep.py [candidates.csv] [--limit N]
(ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN come from .env via cwd-walk --
confirmed pointed at production before running for real.)
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi
import yt_dlp

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)
from app.platforms.youtube_channel import is_publishable  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.nationwide_2404_ingest import (  # noqa: E402
    RowResult,
    RowSkip,
    TIER3_QUEUE_FILE,
    UNSUPPORTED_PLATFORMS,
    _dedup_key,
    _ingest_with_retry,
    _log_writer,
    _already_logged_gov_ids,
    _looks_like_real_meeting,
    _parse_hit_source_urls,
    _seen_keys,
    locate_platform_url,
    resolve_seed,
    youtube_oembed_title,
    REQUEST_DELAY_SECONDS,
)
from scripts.bulk_ingest import _base_url  # noqa: E402
from scripts.adhoc_cdx_escribe_pipeline import discover_candidate_ids  # noqa: E402

# Real, confirmed gap found mid-run (WO-128, 2026-09-09): a bare eScribe
# tenant root (jurisdiction_coverage.csv's own `domain` column IS the
# tenant host verbatim for many Canadian eScribe candidates, e.g.
# `pub-southdundas.escribemeetings.com` with no path at all) resolves
# "successfully" -- escribe.py's own `resolve()` fetches whatever URL
# it's given and never raises `CalendarPageError` the way civicplus.py/
# municode_meetings.py/vimeo.py do for a listing page -- but extracts
# nothing (no agenda items, no video, no metadata a bare tenant
# homepage has), which reads as a dead end rather than "wrong page,
# try a real meeting". 29 of the first 38 eScribe rows this sweep
# processed hit exactly this. `scripts/adhoc_cdx_escribe_pipeline.py`
# already solved this for its own tenant-list input via a real,
# undocumented-but-public tenant API,
# `POST {domain}/MeetingsCalendarView.aspx/GetCalendarMeetings`
# (`discover_candidate_ids()`, imported above) -- reused here rather
# than reimplemented, same as everything else this module pulls from
# its sibling scripts. See BACKLOG.md for the filed entry.
_ESCRIBE_MEETING_PATH_HINTS = ("meeting.aspx", "isistandaloneplayer.aspx")


def _is_bare_escribe_tenant_url(url: str) -> bool:
    if detect_platform(url) != "escribe":
        return False
    path = urlparse(url).path.lower()
    return not any(hint in path for hint in _ESCRIBE_MEETING_PATH_HINTS)


async def _discover_escribe_meeting(session: aiohttp.ClientSession, tenant_url: str):
    """Returns (meeting_url, None) for the first of the tenant's own
    `GetCalendarMeetings` candidates (most-recent-first, HasVideo only)
    that actually resolves with real content, or (None, reason)."""
    domain = urlparse(tenant_url).netloc
    candidate_ids = await discover_candidate_ids(session, domain)
    if not candidate_ids:
        return None, "no HasVideo meeting via GetCalendarMeetings in the last 120 days"
    last_reason = ""
    for guid in candidate_ids:
        candidate_url = f"https://{domain}/Meeting.aspx?Id={guid}"
        try:
            result = await get_finder("escribe").resolve(candidate_url)
        except CalendarPageError as e:
            last_reason = f"calendar page: {e}"
            continue
        except Exception as e:
            last_reason = f"resolve raised: {e}"
            continue
        if (
            result.segments
            or result.agenda_items
            or result.agenda_link
            or result.video_url
        ):
            return candidate_url, None
    return (
        None,
        last_reason or f"checked {len(candidate_ids)} candidate(s), none had content",
    )


# Same video-id shape nationwide_2404_ingest.py's youtube_oembed_title()
# checks for -- a seed URL with none of these is a channel/user/@handle
# URL, not a single video, and needs the channel-listing path below
# instead of a direct resolve() (app/platforms/youtube.py's own finder
# only ever handles one specific video). See CLAUDE.md's YouTube-channel
# bullet: a flat listing carries no dates, so "first publishable,
# real-meeting-titled entry in the channel's own /videos listing order"
# is the same "most recent real meeting" pick every other platform's
# CalendarPageError candidate-picking makes, just without a date to sort
# by (YouTube's own /videos tab is already newest-first).
_YT_VIDEO_ID_RE = re.compile(r"(?:v=|/embed/|/live/|youtu\.be/)([A-Za-z0-9_-]{11})")


def _is_youtube_channel_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if "youtube.com" not in netloc and "youtu.be" not in netloc:
        return False
    return not _YT_VIDEO_ID_RE.search(url)


def _pick_channel_video(channel_url: str) -> tuple:
    """Blocking (yt-dlp). Returns (video_url, title) for the first
    publishable entry on the channel's own /videos listing whose title
    looks like a real governing-body meeting, or (None, reason) if none
    qualifies. Same flat-extraction shape as
    youtube_channel.py's `_list_channel_tab()`, called directly against
    whatever channel URL form the candidate row has (`/channel/{id}`,
    `/c/{name}`, `/user/{name}`, `/@{handle}`) rather than requiring a
    pre-resolved `UC...` id -- yt-dlp resolves the vanity form itself."""
    base = channel_url.rstrip("/")
    if not base.endswith(("/videos", "/streams")):
        base = base + "/videos"
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": 40,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "tv", "web"]}
        },
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(base, download=False)
    except Exception as e:
        return None, f"channel listing failed: {e}"
    # Real, confirmed gap found mid-run: `ignoreerrors: True` means a
    # channel URL yt-dlp can't make sense of at all (e.g. jurisdiction_
    # coverage.csv's bare "www.youtube.com" for Fortuna, CA -- not a real
    # channel/handle, a garbage `domain` value) returns `info=None`
    # rather than raising, which crashed this on `.get()` before this
    # guard (logged as an opaque "unhandled exception:
    # 'NoneType' object has no attribute 'get'").
    if not info:
        return None, "channel listing returned no info (not a real channel URL?)"
    entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
    if not entries:
        return None, "channel listing returned no entries"
    for entry in entries:
        if not is_publishable(entry):
            continue
        title = entry.get("title") or ""
        if _looks_like_real_meeting(title, require_allowlist=True):
            return f"https://www.youtube.com/watch?v={entry['id']}", title
    return (
        None,
        f"checked {len(entries)} channel video(s), none looked like a real meeting",
    )


async def process_row_video_only(
    session: aiohttp.ClientSession, row: dict
) -> RowResult:
    """`nationwide_2404_ingest.process_row()`'s own body, copied so the
    agenda-only branch can be changed from an ingest to a no-op -- see
    this module's docstring for why (WO-128's explicit "ONLY meetings
    with video" rule vs. that script's own "ingest agenda content too"
    default). Every other branch is unchanged."""
    gov_id = row["gov_id"]
    unit_name = row["unit_name"]
    homepage = row.get("homepage") or ""
    hop2_urls = [
        u.strip() for u in (row.get("hop2_urls") or "").split(";") if u.strip()
    ]
    hits = _parse_hit_source_urls(row.get("hit_source_urls") or "")

    if not hits:
        return RowResult(
            gov_id, unit_name, "", "skipped", "no hit_source_urls on this row"
        )

    supported_hits = [(p, u) for p, u in hits if p not in UNSUPPORTED_PLATFORMS]
    if not supported_hits:
        # "skipped", not "no-video-found": there was no adapter to even
        # try, a different (and more specific, see
        # backfill_2404_ingest_into_jc.py's classify_reject_reason())
        # taxonomy bucket than "resolved and found no video".
        platforms_seen = ", ".join(sorted({p for p, _ in hits}))
        return RowResult(
            gov_id,
            unit_name,
            platforms_seen,
            "skipped",
            "unsupported platform, no adapter in this repo "
            "(boarddocs/municipalcodeonline/novusagenda/agendasuite)",
        )

    last_reason = ""
    for platform, hit_url in supported_hits:
        try:
            get_finder(platform)
        except UnsupportedPlatformError:
            last_reason = f"{platform}: not registered in get_finder() (unexpected)"
            continue

        seed_url, reason = await locate_platform_url(
            session, platform, hit_url, hop2_urls, homepage
        )
        if not seed_url:
            last_reason = f"{platform}: {reason}"
            continue

        try:
            result, final_seed, high_risk_title = await resolve_seed(
                session, platform, seed_url
            )
        except RowSkip as e:
            last_reason = f"{platform}: {e}"
            continue
        except Exception as e:
            last_reason = f"{platform}: resolve raised: {e}"
            continue

        segments = result.segments or []
        agenda_items = result.agenda_items or []
        if not (segments or agenda_items or result.agenda_link or result.video_url):
            last_reason = (
                f"{platform}: resolved but no transcript/agenda/video ({final_seed})"
            )
            continue

        key = _dedup_key(result)
        if key in _seen_keys:
            last_reason = f"{platform}: duplicate of an already-processed meeting this run ({key})"
            continue

        effective_title = result.title or ""
        if not effective_title and result.video_url:
            oembed_title = await youtube_oembed_title(session, result.video_url)
            if oembed_title:
                effective_title = oembed_title
        if not _looks_like_real_meeting(
            effective_title, require_allowlist=high_risk_title
        ):
            why = (
                "no governing-body keyword in title"
                if high_risk_title
                else "blocklisted term in title"
            )
            last_reason = f"{platform}: title looks like a non-meeting video ({why}), not ingested: {effective_title!r} ({final_seed})"
            continue

        _seen_keys.add(key)

        title = result.title or ""
        date = result.date or ""

        if segments:
            normalized = normalize_url(final_seed)
            response = await _ingest_with_retry(
                session, result.model_dump(), normalized
            )
            if response is None:
                last_reason = f"{platform}: resolved real content ({len(segments)} segments) but POST to Archive failed twice, not ingested: {final_seed}"
                continue
            page_url = response.get("url")
            created = response.get("created")
            note = "" if created else " (matched an EXISTING page, not newly created)"
            return RowResult(
                gov_id,
                unit_name,
                platform,
                "ingested_tier1_2",
                f"{len(segments)} transcript segments{note}",
                final_seed,
                title,
                date,
                page_url or "",
            )

        if result.video_url:
            source_line = (
                f"{final_seed}\t{hit_url}" if hit_url != final_seed else final_seed
            )
            with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(source_line + "\n")
            return RowResult(
                gov_id,
                unit_name,
                platform,
                "queued_tier3",
                "real video, no transcript yet -- appended to tier3_auto_transcription_queue.txt",
                final_seed,
                title,
                date,
                "",
            )

        # WO-128 deviation from process_row(): agenda_items/agenda_link
        # present, no video/segments -- NOT ingested. Ryan's rule for
        # this WO is exact: "Agenda-only meetings are NOT ingested;
        # record no-video-found."
        return RowResult(
            gov_id,
            unit_name,
            platform,
            "no-video-found",
            f"agenda-only, no video (not ingested per WO-128 rule): {final_seed}",
            final_seed,
            title,
            date,
            "",
        )

    return RowResult(
        gov_id,
        unit_name,
        ", ".join(p for p, _ in supported_hits),
        "skipped",
        last_reason or "no usable platform link found",
    )


LOG_CSV = REPO_ROOT / "scripts" / "wo128_data" / "wo128_sweep_log.csv"


def _homepage(domain: str) -> str:
    domain = (domain or "").strip()
    if not domain:
        return ""
    if "://" not in domain:
        domain = "https://" + domain
    return domain


def _seed_url(row: dict) -> str:
    return (
        row.get("example_meeting_url")
        or row.get("example_agenda_or_calendar_url")
        or _homepage(row.get("domain", ""))
    )


_PLATFORM_ALIASES = {
    "escribemeetings": "escribe",
}


def _normalize_platform(raw: str) -> str:
    """Real, confirmed gap found mid-run: 8 rows in the WO-128 candidate
    set (Tuscaloosa AL, Columbus GA, Savannah GA, Lowell MA, Springfield
    MO, Milton GA, Richmond IN, Tecumseh MI -- all real, notable-
    population cities) carry `known_platform` as either a `.com`-suffixed
    domain (`vimeo.com`, `granicus.com`, `civicplus.com`,
    `civicclerk.com`) or the vendor's own product name
    (`escribemeetings`, the actual hostname suffix -- e.g.
    `pub-milton.escribemeetings.com`) rather than the bare platform name
    `get_finder()` registers (`vimeo`, `granicus`, ..., `escribe`) -- a
    jurisdiction_coverage.csv data-entry inconsistency, not a domain/
    platform field swap (each row's own `domain` column is a correct
    government homepage). Without this, these rows fail with
    "not registered in get_finder() (unexpected)" instead of ever being
    tried for real."""
    platform = (raw or "").strip().lower()
    if platform.endswith(".com"):
        platform = platform[: -len(".com")]
    return _PLATFORM_ALIASES.get(platform, platform)


def _read_candidates(path: Path) -> list:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        platform = _normalize_platform(r.get("known_platform", ""))
        homepage = _homepage(r.get("domain", ""))
        seed = _seed_url(r)
        if not seed:
            continue
        out.append(
            {
                "gov_id": r["gov_id"],
                "unit_name": f"{r.get('name', '')}, {r.get('state', '')}",
                "homepage": homepage,
                "hop2_urls": "",
                "hit_source_urls": f"{platform}={seed}",
            }
        )
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "candidates",
        help="CSV with gov_id, name, state, known_platform, domain, "
        "example_meeting_url, example_agenda_or_calendar_url columns "
        "(WO-128's own candidate list has no stable repo home -- pass "
        "it explicitly rather than relying on a default path).",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)

    rows = _read_candidates(Path(args.candidates))
    already_done = _already_logged_gov_ids(LOG_CSV)
    to_process = [r for r in rows if r["gov_id"] not in already_done]
    if args.limit:
        to_process = to_process[: args.limit]

    print(
        f"{len(rows)} total candidates, {len(already_done)} already logged, "
        f"{len(to_process)} to go (from {args.candidates})"
    )

    log_f, log_writer = _log_writer(LOG_CSV)
    tally: dict = {}

    def _record(result: RowResult) -> None:
        tally[result.outcome] = tally.get(result.outcome, 0) + 1
        print(
            f"[{result.outcome:20}] {result.gov_id} {result.unit_name!r} "
            f"platform={result.platform!r} -- {result.reason}"
        )
        log_writer.writerow(result.__dict__)
        log_f.flush()

    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                try:
                    platform, _, seed = row["hit_source_urls"].partition("=")
                    if platform == "youtube":
                        # Same homepage-crawl process_row() would do
                        # internally, run here first so a channel/user/
                        # @handle link discovered ON the homepage (not
                        # just one already sitting in the candidate row's
                        # own seed) also gets the channel-listing
                        # treatment below -- see this module's docstring.
                        located, reason = await locate_platform_url(
                            session, "youtube", seed, [], row["homepage"]
                        )
                        if not located:
                            _record(
                                RowResult(
                                    row["gov_id"],
                                    row["unit_name"],
                                    "youtube",
                                    "skipped",
                                    f"youtube: {reason}",
                                )
                            )
                            if i < len(to_process) - 1:
                                await asyncio.sleep(REQUEST_DELAY_SECONDS)
                            continue
                        if _is_youtube_channel_url(located):
                            video_url, title_or_reason = await asyncio.to_thread(
                                _pick_channel_video, located
                            )
                            if not video_url:
                                _record(
                                    RowResult(
                                        row["gov_id"],
                                        row["unit_name"],
                                        "youtube",
                                        "skipped",
                                        f"youtube channel: {title_or_reason} ({located})",
                                    )
                                )
                                if i < len(to_process) - 1:
                                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
                                continue
                            located = video_url
                        row = dict(row)
                        row["hit_source_urls"] = f"youtube={located}"
                    elif platform == "escribe" and _is_bare_escribe_tenant_url(seed):
                        meeting_url, reason = await _discover_escribe_meeting(
                            session, seed
                        )
                        if not meeting_url:
                            _record(
                                RowResult(
                                    row["gov_id"],
                                    row["unit_name"],
                                    "escribe",
                                    "skipped",
                                    f"escribe tenant calendar: {reason} ({seed})",
                                )
                            )
                            if i < len(to_process) - 1:
                                await asyncio.sleep(REQUEST_DELAY_SECONDS)
                            continue
                        row = dict(row)
                        row["hit_source_urls"] = f"escribe={meeting_url}"
                    result = await process_row_video_only(session, row)
                except Exception as e:
                    result = RowResult(
                        row["gov_id"],
                        row["unit_name"],
                        "",
                        "skipped",
                        f"unhandled exception: {e}",
                    )
                _record(result)
                if i < len(to_process) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        log_f.close()

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull log: {LOG_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
