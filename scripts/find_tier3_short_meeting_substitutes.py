#!/usr/bin/env python3
"""For every tier-3 queue meeting longer than 1h30, find a short
(10-50 min) meeting from the same tenant, and write a review CSV --
without touching the queue file itself.

Why: scripts/tier3_auto_transcription_queue.txt feeds 12 meetings per
6 hours into auto-transcription, and a multi-hour meeting costs hours of
Whisper time for one jurisdiction. A short meeting from the same tenant
still gives that jurisdiction real coverage at a fraction of the cost.
The queue rows carry no duration (they are bare URLs, and
tests/test_transcription_queue_files.py would reject inline tags), so
durations live in sidecar CSVs here, and the deliverable is a committed
report (scripts/tier3_short_meeting_substitutes.csv) a human reviews
before anything is re-queued.

Scope (deliberate, decided 2026-08-28): only CivicClerk and Legistar
rows get probed and substituted -- they are the only queue platforms
with a known "list this tenant's other meetings" method (CivicClerk's
per-tenant Events API; Legistar's public webapi.legistar.com). The other
~69% of queue rows (Swagit, eScribe, IQM2, TownHallStreams, CivicWeb,
Cablecast, ClerksHQ) are reported as platform_not_enumerable rather than
silently dropped; BACKLOG.md's "Platform discovery & enumeration"
section already tracks that gap.

Two live-data facts this script leans on:

1. **CivicClerk's `Events/{id}.durationMin` holds SECONDS, not minutes,
   despite its name.** Evidence: tests/fixtures/civicclerk/
   emporiaks_event585.json has durationMin=16821 and that same event's
   committed caption file (emporiaks_585_captions.srt) ends at
   04:40:21 = exactly 16,821s. Only one real datapoint confirms the
   seconds reading, so the `smoke` subcommand cross-validates
   durationMin against ffprobe on a handful of live rows before any
   full run, and `--no-api-durations` forces ffprobe everywhere if the
   field ever turns out unreliable. The field is also sometimes just 0
   with real media present (clovisca_event20.json), so 0/absent always
   falls back to ffprobe (or the caption-file tail).

2. **Legistar's events listing MUST be past-date-filtered**
   (`$filter=EventDate lt datetime'{today}'`): the API reports
   `EventVideoStatus: "Public"` for future meetings whose video does
   not exist yet -- real bug hit live on dekalbcountyga 2026-08-21, see
   BACKLOG_DONE.md's meeting_url_finder entry. Legistar's API has no
   duration field at all, so its rows resolve through the normal
   adapter (LegistarAssetFinder delegates to Granicus) and get
   ffprobed.

Subcommands, in run order:
  smoke      -- egress + ffprobe-through-proxy check, plus the live
                durationMin-vs-ffprobe cross-validation. Run this first;
                it exits 2 with a plain report if the environment's
                network policy blocks the platform hosts.
  probe      -- duration for every CivicClerk/Legistar queue row, into a
                resumable sidecar CSV (gitignored
                local_transcription_backups/, same home as
                probe_backlog_video_durations.py's output).
  substitute -- for each tenant with a >90 min row, enumerate its past
                meetings newest-first and find one in [10 min, 50 min];
                resumable sidecar CSV, one search per tenant.
  report     -- merge everything into the committed
                scripts/tier3_short_meeting_substitutes.csv, one row per
                queue URL.

Proxy notes for a managed/remote environment (no-ops on a normal
machine): ffmpeg/ffprobe honor a lowercase `http_proxy` env var for
https CONNECT, so main() mirrors HTTPS_PROXY into it; aiohttp only uses
proxy env vars with trust_env=True, so when HTTPS_PROXY is set this
script defaults trust_env=True for every ClientSession, including the
sessions platform adapters open internally.
"""

import argparse
import asyncio
import csv
import os
import re
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import certifi

# Must run before `import aiohttp` -- see transcribe_backlog_locally.py's
# own module-level comment for the full incident this works around.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)
from app.platforms.media_probe import binary_versions, probe_duration  # noqa: E402

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
SIDECAR_DIR = REPO_ROOT / "local_transcription_backups"
DURATIONS_CSV = SIDECAR_DIR / "tier3_queue_durations.csv"
SEARCH_CSV = SIDECAR_DIR / "tier3_substitute_search.csv"
REPORT_CSV = REPO_ROOT / "scripts" / "tier3_short_meeting_substitutes.csv"

LONG_SECONDS = 90 * 60
SHORT_MIN_SECONDS = 9 * 60
SHORT_MAX_SECONDS = 40 * 60

# The only queue platforms with a known tenant-enumeration method (see
# module docstring). Everything else is reported, not probed.
ENUMERABLE_PLATFORMS = {"civicclerk", "legistar"}

REQUEST_DELAY_SECONDS = 1.5

_UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}

DURATION_FIELDS = [
    "queue_url",
    "tenant",
    "platform",
    "title",
    "date",
    "duration_seconds",
    "duration_hms",
    "duration_source",
    "note",
]

SEARCH_FIELDS = [
    "tenant",
    "platform",
    "original_title",
    "original_jurisdiction",
    "original_gov_id",
    "search_status",
    "substitute_url",
    "substitute_title",
    "substitute_date",
    "substitute_duration_seconds",
    "substitute_duration_hms",
    "substitute_duration_source",
    "candidates_checked",
    "note",
]

REPORT_FIELDS = [
    "queue_url",
    "tenant",
    "platform",
    "duration_seconds",
    "duration_hms",
    "duration_source",
    "status",
    "substitute_url",
    "substitute_title",
    "substitute_date",
    "substitute_duration_seconds",
    "substitute_duration_hms",
    "candidates_checked",
    "notes",
]


def hms(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def queue_lines() -> list[tuple[str, str, str | None]]:
    """(raw line, url, source_url_override) -- the feed's own line parse,
    since queue lines have carried an optional TAB source field since the
    2026-09 sweeps (see feed_tier3_auto_transcription._parse_queue_line)."""
    out = []
    for raw in QUEUE_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, _, src = line.partition("\t")
        out.append((line, url.strip(), src.strip() or None))
    return out


def queue_urls() -> list[str]:
    return [url for _, url, _ in queue_lines()]


def tenant_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def cc_api_base(tenant: str) -> str:
    # Mirrors civicclerk.py's resolve(): first netloc label is the
    # tenant subdomain, whether the URL is portal.civicclerk.com-shaped
    # or not.
    return f"https://{tenant.split('.')[0]}.api.civicclerk.com/v1"


def cc_event_id(url: str) -> str | None:
    match = re.search(r"/event/(\d+)", urlparse(url).path)
    return match.group(1) if match else None


def cc_portal_url(tenant: str, event_id: int | str) -> str:
    return (
        f"https://{tenant.split('.')[0]}.portal.civicclerk.com/event/{event_id}/media"
    )


def cc_duration_seconds(event: dict) -> float | None:
    """durationMin holds seconds despite its name (see module docstring);
    0/absent means "not populated", never "zero-length meeting"."""
    value = event.get("durationMin")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def cc_media_path(event: dict) -> str | None:
    # Same precedence civicclerk.py applies to the event-level fields
    # (its first choice, EventsMedia's videoUrl, needs a second API call).
    # Absolute URLs only: live losaltoshillsca event 4354 (2026-08-28)
    # returned a *relative* "stream/LOSALTOSHILLSCA/{file}.mp4" here while
    # EventsMedia's videoUrl held the real absolute form
    # (https://cpmedia.azureedge.net/losaltoshillsca/{file}.mp4), so a
    # relative value is treated as "not probeable from this row" and
    # callers fall back to the EventsMedia call rather than guessing the
    # CDN base from one observed mapping.
    for field in ("mediaStreamPath", "mediaSourcePathMp4", "externalMediaUrl"):
        value = event.get(field)
        if value and value.startswith(("http://", "https://")):
            return value
    return None


def cc_past_candidates(
    events: list[dict], *, exclude_ids: set[str], now_iso: str
) -> list[dict]:
    """Filters an Events listing down to substitutable candidates,
    newest first: not deleted, media present, already-queued/self ids
    excluded, and strictly in the past (the listing fallback path can
    include scheduled future meetings, which report media flags before
    any video exists -- same trap as Legistar's EventVideoStatus)."""
    out = []
    for event in events:
        if event.get("isDeleted"):
            continue
        if not (event.get("hasMedia") or cc_media_path(event)):
            continue
        event_id = event.get("id")
        if event_id is None or str(event_id) in exclude_ids:
            continue
        start = event.get("startDateTime") or event.get("eventDate") or ""
        if not start or start >= now_iso:
            continue
        out.append(event)
    out.sort(key=lambda e: e.get("startDateTime") or e.get("eventDate") or "")
    out.reverse()
    return out


def legistar_client(tenant: str) -> str:
    return tenant.split(".")[0]


def legistar_url_id(url: str) -> str | None:
    params = parse_qs(urlparse(url).query)
    values = params.get("ID") or params.get("id")
    return values[0] if values else None


_SRT_ARROW_RE = re.compile(r"-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def srt_tail_seconds(text: str) -> float | None:
    """Last cue's end time in an SRT/VTT file -- a duration lower bound
    that in practice tracks the real media length (captions run to the
    end of these recordings; the emporiaks_585 fixture pair agrees with
    durationMin to the second)."""
    ends = [
        int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0
        for h, m, s, ms in _SRT_ARROW_RE.findall(text)
    ]
    return max(ends) if ends else None


def in_short_window(
    seconds: float,
    *,
    lo: float = SHORT_MIN_SECONDS,
    hi: float = SHORT_MAX_SECONDS,
) -> bool:
    return lo <= seconds <= hi


def _window_label(lo: float, hi: float) -> str:
    return f"{int(lo // 60)}-{int(hi // 60)} min"


def _window_note(lo: float, hi: float) -> str:
    """Search rows record a non-default window so the report says which
    pass found the substitute (e.g. the 50-90 min fallback sweep)."""
    if (lo, hi) == (SHORT_MIN_SECONDS, SHORT_MAX_SECONDS):
        return ""
    return f"found in widened {_window_label(lo, hi)} window"


def classify_duration(seconds: float | None) -> str:
    if seconds is None:
        return "probe_failed"
    return "long" if seconds > LONG_SECONDS else "not_long"


def _patch_proxy_env() -> None:
    """Managed-environment plumbing, a no-op elsewhere: mirror
    HTTPS_PROXY into the lowercase http_proxy ffmpeg reads for https
    CONNECT, and default trust_env=True on every aiohttp session
    (adapters' internal sessions included) since aiohttp ignores proxy
    env vars without it."""
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not https_proxy:
        return
    os.environ.setdefault("http_proxy", https_proxy)

    original_init = aiohttp.ClientSession.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("trust_env", True)
        original_init(self, *args, **kwargs)

    aiohttp.ClientSession.__init__ = patched_init


async def _get_json(session: aiohttp.ClientSession, url: str):
    async with session.get(
        url, headers=_UA_HEADERS, timeout=aiohttp.ClientTimeout(total=45)
    ) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def _get_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(
        url, headers=_UA_HEADERS, timeout=aiohttp.ClientTimeout(total=45)
    ) as resp:
        resp.raise_for_status()
        return await resp.text(errors="replace")


def _odata_rows(payload) -> list[dict]:
    if isinstance(payload, dict):
        return payload.get("value") or []
    return payload or []


async def cc_list_past_events(
    session: aiohttp.ClientSession, api_base: str, *, top: int = 50
) -> list[dict]:
    """Newest-first past events for a tenant. Tries a server-side
    past-date $filter first (the Pittsburg-precedent startDateTime
    field, BACKLOG.md's open.media entry); if the tenant's OData
    dialect rejects it, falls back to a plain newest-first listing --
    cc_past_candidates() re-applies the past-date cut client-side either
    way, so a future scheduled meeting can never be picked."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filtered = (
        f"{api_base}/Events?$filter=startDateTime lt {now_iso}"
        f"&$orderby=startDateTime desc&$top={top}"
    )
    plain = f"{api_base}/Events?$orderby=startDateTime desc&$top={top}"
    try:
        return _odata_rows(await _get_json(session, filtered))
    except aiohttp.ClientResponseError:
        return _odata_rows(await _get_json(session, plain))


async def cc_probeable_video_url(
    session: aiohttp.ClientSession, api_base: str, event: dict
) -> str | None:
    """Absolute media URL for an Events row: the row's own fields when
    already absolute, else EventsMedia/{id}'s videoUrl (see
    cc_media_path's comment on the relative-path finding)."""
    media_url = cc_media_path(event)
    if media_url:
        return media_url
    event_id = event.get("id")
    if event_id is None:
        return None
    try:
        media = await _get_json(session, f"{api_base}/EventsMedia/{event_id}")
    except Exception:  # noqa: BLE001 -- EventsMedia 404s on media-less events
        return None
    return media.get("videoUrl") or media.get("externalVideoUrl") or None


async def legistar_list_past_events(
    session: aiohttp.ClientSession, client: str, *, top: int = 30
) -> list[dict]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = (
        f"https://webapi.legistar.com/v1/{client}/events"
        f"?$filter=EventDate lt datetime'{today}'&$orderby=EventDate desc&$top={top}"
    )
    return _odata_rows(await _get_json(session, url))


def _load_rows(path: Path, key_field: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {row[key_field]: row for row in csv.DictReader(f)}


class _RowWriter:
    """Append-per-row CSV writer (flush every row), same resumability
    shape as probe_backlog_video_durations.py."""

    def __init__(self, path: Path, fields: list[str]):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        if not write_header:
            # WO-205: appending rows under a header from an older field list
            # silently misaligns every later row (real 2026-09-11 case, 275
            # rows). Refuse, and say which file to rebuild.
            with path.open(newline="") as existing:
                header = next(csv.reader(existing), [])
            if header and header != list(fields):
                raise RuntimeError(
                    f"{path} has header {header[:4]}... but this run writes {list(fields)[:4]}... "
                    "-- rebuild the sidecar under the current field list before appending"
                )
        self._f = path.open("a", newline="")
        self._writer = csv.DictWriter(self._f, fieldnames=fields)
        if write_header:
            self._writer.writeheader()
            self._f.flush()

    def write(self, row: dict) -> None:
        self._writer.writerow(row)
        self._f.flush()

    def close(self) -> None:
        self._f.close()


async def _resolve_and_probe(url: str) -> dict:
    """The generic (non-CivicClerk) duration path: adapter resolve to a
    playable video_url, then ffprobe it. Returns partial row fields."""
    platform = detect_platform(url)
    fields: dict = {"title": "", "date": "", "duration_seconds": None}
    try:
        result = await get_finder(platform).resolve(url)
    except Exception as exc:  # noqa: BLE001 -- any resolve failure is a data point here
        fields["note"] = f"resolve failed: {type(exc).__name__}: {exc}"[:300]
        return fields
    fields["title"] = result.title or ""
    fields["date"] = result.date or ""
    if not result.video_url:
        fields["note"] = "no playable video found on resolve"
        return fields
    if result.video_format == "youtube":
        fields["note"] = "youtube-delegated embed -- not a directly probeable media URL"
        return fields
    duration = await probe_duration(result.video_url, source_page_url=url)
    if duration is None:
        fields["note"] = "ffprobe failed or timed out"
        return fields
    fields["duration_seconds"] = duration
    fields["duration_source"] = "ffprobe"
    return fields


async def _cc_queue_row_duration(
    session: aiohttp.ClientSession, url: str, *, use_api_durations: bool
) -> dict:
    fields: dict = {"title": "", "date": "", "duration_seconds": None}
    event_id = cc_event_id(url)
    if not event_id:
        fields["note"] = "no /event/{id} in URL path"
        return fields
    api_base = cc_api_base(tenant_of(url))
    try:
        event = await _get_json(session, f"{api_base}/Events/{event_id}")
    except Exception as exc:  # noqa: BLE001
        fields["note"] = f"Events API failed: {type(exc).__name__}: {exc}"[:300]
        return fields
    fields["title"] = event.get("eventName") or ""
    fields["date"] = (event.get("eventDate") or event.get("startDateTime") or "")[:10]

    if use_api_durations:
        api_duration = cc_duration_seconds(event)
        if api_duration is not None:
            fields["duration_seconds"] = api_duration
            fields["duration_source"] = "civicclerk_api"
            return fields

    media_url = cc_media_path(event)
    caption_url = None
    if not media_url:
        try:
            media = await _get_json(session, f"{api_base}/EventsMedia/{event_id}")
            media_url = media.get("videoUrl") or media.get("externalVideoUrl")
            caption_url = media.get("closedCaptionUrl")
        except Exception:  # noqa: BLE001 -- EventsMedia 404s on media-less events
            pass
    if media_url:
        duration = await probe_duration(media_url, source_page_url=url)
        if duration is not None:
            fields["duration_seconds"] = duration
            fields["duration_source"] = "ffprobe"
            return fields
        fields["note"] = "ffprobe failed on media URL"
    if caption_url:
        try:
            tail = srt_tail_seconds(await _get_text(session, caption_url))
        except Exception:  # noqa: BLE001
            tail = None
        if tail is not None:
            fields["duration_seconds"] = tail
            fields["duration_source"] = "caption_tail"
            fields["note"] = ""
            return fields
    if not fields.get("note"):
        fields["note"] = "no media path on event and no probeable fallback"
    return fields


async def cmd_probe(args) -> None:
    urls = queue_urls()
    targets = []
    for url in urls:
        platform = detect_platform(url)
        if platform in ENUMERABLE_PLATFORMS or args.all_platforms:
            targets.append((url, platform))

    done_rows = _load_rows(DURATIONS_CSV, "queue_url")
    todo = [(u, p) for (u, p) in targets if u not in done_rows]
    if args.limit is not None:
        todo = todo[: args.limit]
    print(
        f"{len(urls)} queue rows, {len(targets)} on probeable platforms, "
        f"{len(done_rows)} already probed, {len(todo)} to probe now."
    )
    if not todo:
        print("Nothing new to probe.")
        return

    register_all_finders()
    semaphore = asyncio.Semaphore(args.concurrency)
    writer = _RowWriter(DURATIONS_CSV, DURATION_FIELDS)
    done = 0

    async def probe_one(url: str, platform: str) -> dict:
        async with semaphore:
            if platform == "civicclerk":
                async with aiohttp.ClientSession() as session:
                    fields = await _cc_queue_row_duration(
                        session, url, use_api_durations=not args.no_api_durations
                    )
            else:
                fields = await _resolve_and_probe(url)
        duration = fields.get("duration_seconds")
        return {
            "queue_url": url,
            "tenant": tenant_of(url),
            "platform": platform,
            "title": fields.get("title", ""),
            "date": fields.get("date", ""),
            "duration_seconds": f"{duration:.1f}" if duration is not None else "",
            "duration_hms": hms(duration) if duration is not None else "",
            "duration_source": fields.get("duration_source", ""),
            "note": fields.get("note", ""),
        }

    try:
        tasks = [asyncio.create_task(probe_one(u, p)) for (u, p) in todo]
        for task in asyncio.as_completed(tasks):
            row = await task
            writer.write(row)
            done += 1
            label = row["duration_hms"] or f"SKIP: {row['note']}"
            print(f"[{done}/{len(todo)}] {row['queue_url']} -> {label}")
    finally:
        writer.close()
    print(f"Probe pass done. Sidecar: {DURATIONS_CSV}")


async def _cc_find_substitute(
    session: aiohttp.ClientSession,
    tenant: str,
    exclude_ids: set[str],
    *,
    max_candidates: int,
    use_api_durations: bool,
    window: tuple[float, float] = (SHORT_MIN_SECONDS, SHORT_MAX_SECONDS),
) -> dict:
    lo, hi = window
    api_base = cc_api_base(tenant)
    try:
        events = await cc_list_past_events(session, api_base)
    except Exception as exc:  # noqa: BLE001
        return {
            "search_status": "error",
            "note": f"Events listing failed: {type(exc).__name__}: {exc}"[:300],
        }
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidates = cc_past_candidates(events, exclude_ids=exclude_ids, now_iso=now_iso)
    checked = 0

    if use_api_durations:
        for event in candidates:
            api_duration = cc_duration_seconds(event)
            if api_duration is None or not in_short_window(api_duration, lo=lo, hi=hi):
                continue
            checked += 1
            substitute_url = cc_portal_url(tenant, event["id"])
            # One verification probe against the media file; if it can't
            # be verified the API duration still stands, honestly labeled.
            media_url = await cc_probeable_video_url(session, api_base, event)
            verified = (
                await probe_duration(media_url, source_page_url=substitute_url)
                if media_url
                else None
            )
            if verified is not None and not in_short_window(verified, lo=lo, hi=hi):
                continue
            duration = verified if verified is not None else api_duration
            source = "ffprobe" if verified is not None else "civicclerk_api_unverified"
            return {
                "search_status": "found",
                "substitute_url": substitute_url,
                "substitute_title": event.get("eventName") or "",
                "substitute_date": (event.get("startDateTime") or "")[:10],
                "substitute_duration_seconds": f"{duration:.1f}",
                "substitute_duration_hms": hms(duration),
                "substitute_duration_source": source,
                "candidates_checked": str(checked),
                "note": _window_note(lo, hi),
            }

    # No candidate had a populated in-window API duration -- ffprobe the
    # newest few with media until one lands in the window.
    for event in candidates[:max_candidates]:
        media_url = await cc_probeable_video_url(session, api_base, event)
        if not media_url:
            continue
        checked += 1
        substitute_url = cc_portal_url(tenant, event["id"])
        duration = await probe_duration(media_url, source_page_url=substitute_url)
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        if duration is None or not in_short_window(duration, lo=lo, hi=hi):
            continue
        return {
            "search_status": "found",
            "substitute_url": substitute_url,
            "substitute_title": event.get("eventName") or "",
            "substitute_date": (event.get("startDateTime") or "")[:10],
            "substitute_duration_seconds": f"{duration:.1f}",
            "substitute_duration_hms": hms(duration),
            "substitute_duration_source": "ffprobe",
            "candidates_checked": str(checked),
            "note": _window_note(lo, hi),
        }
    return {
        "search_status": "none",
        "candidates_checked": str(checked),
        "note": (
            f"no {_window_label(lo, hi)} meeting among {len(candidates)} past "
            f"events ({checked} duration-checked)"
        ),
    }


async def _legistar_find_substitute(
    session: aiohttp.ClientSession,
    tenant: str,
    exclude_ids: set[str],
    *,
    max_candidates: int,
    window: tuple[float, float] = (SHORT_MIN_SECONDS, SHORT_MAX_SECONDS),
) -> dict:
    lo, hi = window
    client = legistar_client(tenant)
    try:
        events = await legistar_list_past_events(session, client)
    except Exception as exc:  # noqa: BLE001
        return {
            "search_status": "error",
            "note": f"webapi listing failed: {type(exc).__name__}: {exc}"[:300],
        }
    checked = 0
    for event in events:
        site_url = event.get("EventInSiteURL")
        if not site_url:
            continue
        event_id = legistar_url_id(site_url) or str(event.get("EventId") or "")
        if event_id and event_id in exclude_ids:
            continue
        if checked >= max_candidates:
            break
        checked += 1
        fields = await _resolve_and_probe(site_url)
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        duration = fields.get("duration_seconds")
        if duration is None or not in_short_window(duration, lo=lo, hi=hi):
            continue
        return {
            "search_status": "found",
            "substitute_url": site_url,
            "substitute_title": fields.get("title") or event.get("EventBodyName") or "",
            "substitute_date": fields.get("date")
            or (event.get("EventDate") or "")[:10],
            "substitute_duration_seconds": f"{duration:.1f}",
            "substitute_duration_hms": hms(duration),
            "substitute_duration_source": "ffprobe",
            "candidates_checked": str(checked),
            "note": _window_note(lo, hi),
        }
    return {
        "search_status": "none",
        "candidates_checked": str(checked),
        "note": (
            f"no {_window_label(lo, hi)} meeting among {len(events)} past "
            f"events ({checked} duration-checked)"
        ),
    }


async def cmd_substitute(args) -> None:
    durations = _load_rows(DURATIONS_CSV, "queue_url")
    if not durations:
        print(f"No durations sidecar at {DURATIONS_CSV} -- run `probe` first.")
        sys.exit(1)

    # Everything already in the queue for a tenant is excluded from
    # candidacy -- substituting one queued meeting for another queued
    # meeting achieves nothing.
    queued_ids_by_tenant: dict[str, set[str]] = {}
    for url in queue_urls():
        tenant = tenant_of(url)
        platform = detect_platform(url)
        event_id = (
            cc_event_id(url) if platform == "civicclerk" else legistar_url_id(url)
        )
        if event_id:
            queued_ids_by_tenant.setdefault(tenant, set()).add(event_id)

    long_tenants: dict[str, str] = {}
    for url, row in durations.items():
        if row["duration_seconds"] and float(row["duration_seconds"]) > LONG_SECONDS:
            long_tenants.setdefault(tenant_of(url), row["platform"])

    window = (args.min_minutes * 60.0, args.max_minutes * 60.0)
    done = _load_rows(SEARCH_CSV, "tenant")
    if args.retry_none:
        # Re-search only tenants whose earlier pass found nothing (a
        # widened-window sweep). The sidecar is append-only and
        # _load_rows keeps the last row per tenant, so the new result
        # simply supersedes the old one on the next load.
        todo = [
            (t, p)
            for (t, p) in long_tenants.items()
            if done.get(t, {}).get("search_status") == "none"
        ]
    else:
        todo = [(t, p) for (t, p) in long_tenants.items() if t not in done]
    print(
        f"{len(long_tenants)} tenant(s) with a >90 min queue row, "
        f"{len(done)} already searched, {len(todo)} to search now "
        f"(window {_window_label(*window)})."
    )
    if not todo:
        print("Nothing new to search.")
        return

    register_all_finders()
    writer = _RowWriter(SEARCH_CSV, SEARCH_FIELDS)
    try:
        async with aiohttp.ClientSession() as session:
            for i, (tenant, platform) in enumerate(todo, start=1):
                exclude = queued_ids_by_tenant.get(tenant, set())
                if platform == "civicclerk":
                    result = await _cc_find_substitute(
                        session,
                        tenant,
                        exclude,
                        max_candidates=args.max_candidates,
                        use_api_durations=not args.no_api_durations,
                        window=window,
                    )
                else:
                    result = await _legistar_find_substitute(
                        session,
                        tenant,
                        exclude,
                        max_candidates=args.max_candidates,
                        window=window,
                    )
                row = {field: "" for field in SEARCH_FIELDS}
                row.update({"tenant": tenant, "platform": platform, **result})
                writer.write(row)
                label = (
                    row["substitute_url"] or f"{row['search_status']}: {row['note']}"
                )
                print(f"[{i}/{len(todo)}] {tenant} -> {label}")
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        writer.close()
    print(f"Substitute pass done. Sidecar: {SEARCH_CSV}")


def cmd_report(args) -> None:
    durations = _load_rows(DURATIONS_CSV, "queue_url")
    searches = _load_rows(SEARCH_CSV, "tenant")
    urls = queue_urls()
    counts: dict[str, int] = {}
    # Round 2: the WO-144 probe sidecar is the primary duration source and
    # rtr-discovery's enumerators widen the listable platforms.
    mb_per_min = calibrate_mb_per_min(load_probe_sidecar())
    sidecar = load_probe_sidecar()
    try:
        listable = set(_discovery_modules()[0]) | ENUMERABLE_PLATFORMS | {"utah_pmn"}
    except RuntimeError:
        listable = ENUMERABLE_PLATFORMS | {"utah_pmn"}
    for url in urls:
        try:
            platform = detect_platform(url)
        except UnsupportedPlatformError:
            continue
        if url in durations or platform in ("youtube", "vimeo"):
            continue
        secs, source = duration_from_row(sidecar.get(url), platform, mb_per_min)
        if secs is not None:
            durations[url] = {
                "queue_url": url,
                "duration_seconds": f"{secs:.1f}",
                "duration_hms": hms(secs),
                "duration_source": source,
                "note": "",
            }

    with REPORT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for url in urls:
            try:
                platform = detect_platform(url)
            except UnsupportedPlatformError:
                continue
            if platform in ("youtube", "vimeo"):
                continue
            tenant = tenant_key(url, platform)
            row = {field: "" for field in REPORT_FIELDS}
            row.update({"queue_url": url, "tenant": tenant, "platform": platform})
            probed = durations.get(url)
            if platform not in listable and not probed:
                row["status"] = "platform_not_enumerable"
                row["notes"] = "no tenant meeting-enumeration method for this platform"
            elif not probed or not probed["duration_seconds"]:
                row["status"] = "probe_failed"
                row["notes"] = (probed or {}).get("note", "not probed")
            else:
                duration = float(probed["duration_seconds"])
                row["duration_seconds"] = probed["duration_seconds"]
                row["duration_hms"] = probed["duration_hms"]
                row["duration_source"] = probed["duration_source"]
                if duration <= LONG_SECONDS:
                    row["status"] = "not_long"
                else:
                    search = searches.get(tenant)
                    if search and search["search_status"] in (
                        "found",
                        "found_shortest",
                    ):
                        row["status"] = (
                            "substitute_found"
                            if search["search_status"] == "found"
                            else "substitute_shortest"
                        )
                        for field in (
                            "substitute_url",
                            "substitute_title",
                            "substitute_date",
                            "substitute_duration_seconds",
                            "substitute_duration_hms",
                            "candidates_checked",
                        ):
                            row[field] = search[field]
                        row["notes"] = "; ".join(
                            part
                            for part in (
                                f"duration source: "
                                f"{search['substitute_duration_source']}",
                                search.get("note", ""),
                            )
                            if part
                        )
                    else:
                        row["status"] = "no_short_meeting_found"
                        row["notes"] = (search or {}).get(
                            "note", "tenant not searched yet -- run `substitute`"
                        )
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            writer.writerow(row)

    print(f"Report written: {REPORT_CSV}")
    for status in sorted(counts):
        print(f"  {status}: {counts[status]}")


async def cmd_smoke(args) -> None:
    failures = []
    versions = await binary_versions()
    print(f"ffprobe: {versions.get('ffprobe') or 'MISSING'}")
    if not versions.get("ffprobe"):
        failures.append("ffprobe is not installed (apt-get install -y ffmpeg)")

    urls = queue_urls()
    cc_urls = [u for u in urls if detect_platform(u) == "civicclerk"]
    lg_urls = [u for u in urls if detect_platform(u) == "legistar"]

    async with aiohttp.ClientSession() as session:
        # Egress check 1: CivicClerk tenant API.
        cc_events: list[tuple[str, dict]] = []
        for url in cc_urls[:10]:
            event_id = cc_event_id(url)
            if not event_id:
                continue
            try:
                event = await _get_json(
                    session, f"{cc_api_base(tenant_of(url))}/Events/{event_id}"
                )
                cc_events.append((url, event))
            except Exception as exc:  # noqa: BLE001
                print(f"CivicClerk API blocked/failed for {tenant_of(url)}: {exc}")
                failures.append(f"CivicClerk API unreachable ({tenant_of(url)})")
                break
            if len(cc_events) >= args.validate_count:
                break
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        if cc_events:
            print(f"CivicClerk API reachable ({len(cc_events)} event(s) fetched).")

        # Egress check 2: Legistar webapi.
        if lg_urls:
            client = legistar_client(tenant_of(lg_urls[0]))
            try:
                rows = await legistar_list_past_events(session, client, top=1)
                print(f"Legistar webapi reachable ({client}: {len(rows)} row(s)).")
            except Exception as exc:  # noqa: BLE001
                print(f"Legistar webapi blocked/failed for {client}: {exc}")
                failures.append("Legistar webapi unreachable")

        # Cross-validate durationMin-is-seconds against ffprobe on real
        # media -- the module docstring's one-fixture evidence, re-proven
        # live before any full run trusts the field at scale.
        validated = 0
        if versions.get("ffprobe"):
            for url, event in cc_events:
                api_duration = cc_duration_seconds(event)
                media_url = await cc_probeable_video_url(
                    session, cc_api_base(tenant_of(url)), event
                )
                if api_duration is None or not media_url:
                    continue
                probed = await probe_duration(media_url, source_page_url=url)
                if probed is None:
                    print(f"  ffprobe FAILED through proxy for {media_url}")
                    failures.append("ffprobe cannot reach media hosts")
                    break
                diff = abs(probed - api_duration)
                agree = diff <= max(60.0, 0.05 * probed)
                validated += 1
                print(
                    f"  durationMin={api_duration:.0f}s vs ffprobe={probed:.0f}s "
                    f"(diff {diff:.0f}s) {'OK' if agree else 'MISMATCH'} "
                    f"[{tenant_of(url)}]"
                )
                if not agree:
                    failures.append(
                        "durationMin/ffprobe mismatch -- rerun probe with "
                        "--no-api-durations"
                    )
            if (
                cc_events
                and not validated
                and "ffprobe cannot reach media hosts" not in failures
            ):
                print("  (no fetched event had both durationMin and a media path)")

    if failures:
        print("\nSMOKE FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(2)
    print("\nSmoke checks passed.")


# ---------------------------------------------------------------------------
# Round 2 (2026-09-11): durations from the WO-144 probe sidecar, a
# per-platform file-size proxy, tenant listings through rtr-discovery's
# enumerators, a Utah PMN per-entity listing, the 9-40 min window with a
# "shortest usable" fallback, and an `apply` step that swaps queue lines.
# ---------------------------------------------------------------------------

PROBE_SIDECAR = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue_probe.csv"
DEFERRED_FILE = REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt"
FALLBACK_MIN_SECONDS = 9 * 60  # the probe gate's own floor for a queued meeting
MAX_LISTING_ITEMS = 40  # newest N listings per tenant before giving up
# Platforms whose tenant listing is meetings-only, so a title needs no
# off-mission word check (a Granicus view or CivicClerk events list is
# the government's own meeting archive).
MEETINGS_ONLY_PLATFORMS = {
    "granicus",
    "civicclerk",
    "legistar",
    "iqm2",
    "escribe",
    "civicweb",
    "primegov",
    "municode_meetings",
}
_MEETING_WORDS_RE = re.compile(
    r"council|commission|committee|board|trustees|supervisors|selectmen|aldermen|"
    r"fiscal court|hearing|meeting|session|work ?session",
    re.I,
)
# MB of media per minute, used only when a probe returns a size but no
# duration. Seeded from the sidecar's own rows that carry both (median,
# 2026-09-11: CivicClerk 21.6, Wistia 8.3); calibrate_mb_per_min()
# recomputes from whatever the sidecar holds at run time and falls back
# to these. A platform with neither is skipped, never guessed.
MB_PER_MIN_DEFAULTS = {"civicclerk": 21.6, "wistia": 8.3}


def looks_on_mission(title: str | None, platform: str) -> bool:
    """Ryan's rule (2026-09-11): no judgment beyond 'not completely
    off-mission'. A meetings-only platform passes; anything else needs a
    meeting word in its title."""
    if platform in MEETINGS_ONLY_PLATFORMS:
        return True
    return bool(_MEETING_WORDS_RE.search(title or ""))


def load_probe_sidecar(path: Path = PROBE_SIDECAR) -> dict[str, dict]:
    """url -> the latest sidecar row (the file is append-only; a re-probe
    appends a newer row, so last one wins)."""
    if not path.exists():
        return {}
    rows: dict[str, dict] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            rows[row["url"]] = row
    return rows


def calibrate_mb_per_min(sidecar: dict[str, dict]) -> dict[str, float]:
    """Median MB/min per platform over sidecar rows that carry both a size
    and a duration (>= 3 rows), over the defaults."""
    by: dict[str, list[float]] = {}
    for row in sidecar.values():
        try:
            size = float(row.get("size_bytes") or 0)
            dur = float(row.get("duration_seconds") or 0)
        except ValueError:
            continue
        if size > 0 and dur > 0 and row.get("platform"):
            by.setdefault(row["platform"], []).append(size / 1e6 / (dur / 60))
    out = dict(MB_PER_MIN_DEFAULTS)
    for platform, vals in by.items():
        if len(vals) >= 3:
            vals.sort()
            out[platform] = vals[len(vals) // 2]
    return out


def duration_from_row(
    row: dict | None, platform: str, mb_per_min: dict[str, float]
) -> tuple[float | None, str]:
    """(seconds, source) for a sidecar row: the measured duration, else a
    size-proxy estimate when the platform's MB/min is known, else None."""
    if not row:
        return None, ""
    try:
        dur = float(row.get("duration_seconds") or 0)
    except ValueError:
        dur = 0.0
    if dur > 0:
        return dur, row.get("probe_method") or "probe"
    try:
        size = float(row.get("size_bytes") or 0)
    except ValueError:
        size = 0.0
    rate = mb_per_min.get(platform)
    if size > 0 and rate:
        return size / 1e6 / rate * 60, "size_proxy"
    return None, ""


def pick_substitute(
    candidates: list[tuple[str, float]],
    existing_seconds: float,
    *,
    lo: float = SHORT_MIN_SECONDS,
    hi: float = SHORT_MAX_SECONDS,
    floor: float = FALLBACK_MIN_SECONDS,
) -> tuple[str | None, str]:
    """`candidates` are (url, seconds) in listing order (newest first).
    Returns (url, how): the first one inside the window ("window"), else
    the shortest one that is at least `floor` and shorter than the current
    meeting ("shortest"), else (None, "none") -- Ryan's fallback rule."""
    for url, secs in candidates:
        if lo <= secs <= hi:
            return url, "window"
    usable = [
        (secs, url)
        for url, secs in candidates
        if secs >= floor and secs < existing_seconds
    ]
    if usable:
        usable.sort()
        return usable[0][1], "shortest"
    return None, "none"


def _discovery_root() -> Path:
    env = os.environ.get("RTR_DISCOVERY_PATH")
    for cand in ([Path(env)] if env else []) + [
        Path.home() / "Documents" / "rtr-discovery",
        REPO_ROOT.parent / "rtr-discovery",
    ]:
        if (cand / "discovery" / "enumerators").is_dir():
            return cand
    raise RuntimeError(
        "rtr-discovery checkout not found -- set RTR_DISCOVERY_PATH "
        "(github.com/mroconnell/rtr-discovery, a sibling checkout)"
    )


def _discovery_modules():
    root = _discovery_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from discovery.enumerators import ENUMERATORS  # noqa: E402
    from discovery.models import TenantRecord  # noqa: E402
    from discovery.polite import PoliteClient  # noqa: E402

    return ENUMERATORS, TenantRecord, PoliteClient


_VIEW_ID_RE = re.compile(r"[?&]view_id=(\d+)")


async def discovery_candidates(
    session: aiohttp.ClientSession,
    platform: str,
    tenant: str,
    queue_urls_for_tenant: list[str],
    *,
    max_items: int = MAX_LISTING_ITEMS,
) -> list[tuple[str, str]]:
    """(url, title) for the tenant's newest listings via rtr-discovery's
    enumerator for `platform`. Granicus view ids already present in the
    tenant's queue URLs are handed over so no view-id probing runs."""
    enumerators, TenantRecord, PoliteClient = _discovery_modules()
    enumerator = enumerators.get(platform)
    if enumerator is None:
        raise RuntimeError(f"no rtr-discovery enumerator for {platform}")
    record = TenantRecord(netloc=tenant, platform=platform)
    client = PoliteClient(session)
    view_ids = sorted(
        {
            m.group(1)
            for u in queue_urls_for_tenant
            for m in [_VIEW_ID_RE.search(u)]
            if m
        }
    )
    if platform == "granicus" and view_ids:
        record.params = {"view_ids": [int(v) for v in view_ids]}
    elif enumerator.needs_params:
        params = await enumerator.discover_params(client, record)
        if not params:
            return []
        record.params = params
    # No date floor: an older short meeting is still real coverage, and
    # the listing is newest-first so recent ones are tried first anyway.
    out: list[tuple[str, str]] = []
    async for cand in enumerator.enumerate_tenant(
        client,
        record,
        date_from=None,
        date_to=None,
        mode="fast",
        should_stop=lambda: len(out) >= max_items,
    ):
        if cand.has_video_hint is False:
            continue
        out.append((cand.url, cand.title or ""))
        if len(out) >= max_items:
            break
    return out


async def probe_candidate(
    url: str, platform: str, mb_per_min: dict[str, float]
) -> tuple[float | None, str, object]:
    """Duration for a listing candidate through the WO-144 probe (resolve +
    probe), recorded to the shared sidecar so the ingest gate already knows
    it if it gets queued. Returns (seconds, source, ProbeResult)."""
    from app.platforms.queue_probe import (
        DEFAULT_SIDECAR_PATH,
        append_probe_row,
        probe_queue_entry,
    )

    result = await probe_queue_entry(url, platform=platform)
    append_probe_row(DEFAULT_SIDECAR_PATH, result)
    row = {
        "duration_seconds": result.duration_seconds or "",
        "size_bytes": result.size_bytes or "",
        "probe_method": result.probe_method or "probe",
        "platform": platform,
    }
    secs, source = duration_from_row(row, platform, mb_per_min)
    if result.verdict == "reject-dead":
        return None, source, result
    return secs, source, result


_BODY_PHRASE_RE = re.compile(
    r"(city council|town council|county council|village board|board of (?:supervisors|"
    r"commissioners|trustees|aldermen|selectmen|education|directors)|"
    r"(?:planning|zoning|park|utility|library|police|fire|historic)\w* (?:commission|board)|"
    r"fiscal court|commission|council|committee of the whole|board)",
    re.I,
)


def body_phrase(title: str | None) -> str | None:
    """The governing-body phrase in a meeting title ("City Council",
    "Board of Supervisors"), lower-cased, or None. Used to prefer a
    substitute from the SAME body as the original (the conductor's
    WO-205 condition), not to reject the others -- Ryan's rule is that
    anything on-mission is acceptable."""
    m = _BODY_PHRASE_RE.search(title or "")
    return m.group(1).lower() if m else None


def prefer_same_body(
    listing: list[tuple[str, str]], original_title: str | None
) -> list[tuple[str, str]]:
    """Stable re-order: candidates whose title names the original's
    governing body first, everything else after, listing order kept."""
    want = body_phrase(original_title)
    if not want:
        return listing
    same = [c for c in listing if body_phrase(c[1]) == want]
    rest = [c for c in listing if body_phrase(c[1]) != want]
    return same + rest


async def resolve_original(url: str, platform: str) -> dict:
    """title / jurisdiction / gov_id for a queued meeting, from one adapter
    resolve plus the identity ladder -- recorded in the search row so the
    deferred file can carry the government (conductor's WO-205 condition)
    without a second resolve at apply time. Blank when the ladder declines."""
    out = {"original_title": "", "original_jurisdiction": "", "original_gov_id": ""}
    try:
        result = await get_finder(platform).resolve(url)
    except Exception:  # noqa: BLE001 -- identity is bookkeeping here
        return out
    out["original_title"] = result.title or ""
    out["original_jurisdiction"] = result.jurisdiction or ""
    try:
        from app.utils.gov_registry import resolve_government

        match = resolve_government(result.jurisdiction, tenant_host=tenant_of(url))
        if match and match.gov_id:
            out["original_gov_id"] = match.gov_id
    except Exception:  # noqa: BLE001
        pass
    return out


def _found_row(
    pick: str,
    how: str,
    secs: float,
    title: str,
    source: str,
    checked: int,
    window: tuple[float, float],
) -> dict:
    lo, hi = window
    return {
        "search_status": "found" if how == "window" else "found_shortest",
        "substitute_url": pick,
        "substitute_title": title,
        "substitute_date": "",
        "substitute_duration_seconds": f"{secs:.1f}",
        "substitute_duration_hms": hms(secs),
        "substitute_duration_source": source,
        "candidates_checked": str(checked),
        "note": _window_note(lo, hi)
        if how == "window"
        else "fallback: shortest usable candidate, none in window",
    }


async def _generic_find_substitute(
    session: aiohttp.ClientSession,
    platform: str,
    tenant: str,
    queue_urls_for_tenant: list[str],
    existing_seconds: float,
    *,
    max_candidates: int,
    window: tuple[float, float],
    mb_per_min: dict[str, float],
    original_title: str | None = None,
) -> dict:
    lo, hi = window
    try:
        listing = await discovery_candidates(
            session, platform, tenant, queue_urls_for_tenant
        )
    except Exception as exc:  # noqa: BLE001 -- a listing failure is a data point
        return {
            "search_status": "error",
            "note": f"listing failed: {type(exc).__name__}: {exc}"[:300],
        }
    exclude = set(queue_urls_for_tenant)
    listing = [
        (u, t) for u, t in listing if u not in exclude and looks_on_mission(t, platform)
    ]
    listing = prefer_same_body(listing, original_title)
    if not listing:
        return {
            "search_status": "none",
            "note": "listing returned no other on-mission meetings",
        }
    measured: list[tuple[str, float]] = []
    titles: dict[str, tuple[str, str]] = {}
    checked = 0
    for url, title in listing[:max_candidates]:
        checked += 1
        secs, source, _ = await probe_candidate(url, platform, mb_per_min)
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        if secs is None:
            continue
        titles[url] = (title, source)
        measured.append((url, secs))
        if lo <= secs <= hi:
            break  # newest in-window meeting wins; stop spending probes
    pick, how = pick_substitute(measured, existing_seconds, lo=lo, hi=hi)
    if not pick:
        return {
            "search_status": "none",
            "candidates_checked": str(checked),
            "note": f"{len(measured)} measured, none in {_window_label(lo, hi)} or shorter than the queued meeting",
        }
    title, source = titles[pick]
    return _found_row(pick, how, dict(measured)[pick], title, source, checked, window)


async def _cc_find_substitute_with_fallback(
    session: aiohttp.ClientSession,
    tenant: str,
    exclude_ids: set[str],
    existing_seconds: float,
    *,
    max_candidates: int,
    window: tuple[float, float],
) -> dict:
    """The CivicClerk finder plus Ryan's fallback: when nothing sits in the
    window, take the shortest past event whose API duration is at least
    the floor and shorter than the queued meeting, verified by probe."""
    result = await _cc_find_substitute(
        session,
        tenant,
        exclude_ids,
        max_candidates=max_candidates,
        use_api_durations=True,
        window=window,
    )
    if result.get("search_status") == "found":
        return result
    try:
        events = await cc_list_past_events(session, cc_api_base(tenant))
    except Exception as exc:  # noqa: BLE001
        if result.get("search_status"):
            return result
        return {"search_status": "error", "note": f"Events listing failed: {exc}"[:300]}
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    measured = []
    for event in cc_past_candidates(events, exclude_ids=exclude_ids, now_iso=now_iso):
        secs = cc_duration_seconds(event)
        if secs is not None:
            measured.append((str(event["id"]), secs))
    pick, how = pick_substitute(measured, existing_seconds, lo=window[0], hi=window[1])
    if not pick or how != "shortest":
        result["note"] = (
            (result.get("note") or "") + "; no shorter past event with an API duration"
        ).strip("; ")
        return result
    secs = dict(measured)[pick]
    event = next(e for e in events if str(e.get("id")) == pick)
    substitute_url = cc_portal_url(tenant, pick)
    media_url = await cc_probeable_video_url(session, cc_api_base(tenant), event)
    verified = (
        await probe_duration(media_url, source_page_url=substitute_url)
        if media_url
        else None
    )
    if verified is not None:
        secs = verified
    row = _found_row(
        substitute_url,
        "shortest",
        secs,
        event.get("eventName") or "",
        "ffprobe" if verified is not None else "civicclerk_api_unverified",
        len(measured),
        window,
    )
    row["substitute_date"] = (event.get("startDateTime") or "")[:10]
    return row


# --- Utah PMN: one entity's notices via the pilot's own search plumbing ---

_pmn = None


def _pmn_module():
    global _pmn
    if _pmn is None:
        import importlib

        _pmn = importlib.import_module("pmn_utah_pilot")
    return _pmn


async def pmn_entity_of(session: aiohttp.ClientSession, notice_url: str) -> str | None:
    fields = await _pmn_module().fetch_notice_detail(session, notice_url)
    return (fields.get("Entity") or ("", None))[0] or None


async def pmn_entity_notices(
    session: aiohttp.ClientSession, entity: str, *, days: int = 548, max_pages: int = 4
) -> list:
    """Notices for one entity, newest first, through the same JSON POST the
    pilot documented (CSRF + application/JSON + XMLHttpRequest)."""
    pmn = _pmn_module()
    csrf_token, csrf_header = await pmn.fetch_csrf(session)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    out = []
    for page in range(max_pages):
        payload = {
            "searchType": "entity",
            "entityName": entity,
            "publicBodyName": "",
            "title": "",
            "agenda": "",
            "tags": "",
            "startDate": start.strftime("%m/%d/%Y"),
            "endDate": end.strftime("%m/%d/%Y"),
            "deadlineDate": "",
            "createdDate": "",
            "sortColumn": "",
            "sortOrder": "",
            "startingRow": str(page * 25),
        }
        headers = {
            **pmn.UA_HEADERS,
            "content-type": "application/JSON",
            "x-requested-with": "XMLHttpRequest",
            csrf_header: csrf_token,
        }
        async with session.post(
            pmn.SEARCH_RESULT_URL,
            data=json.dumps(payload),
            headers=headers,
            timeout=pmn.FETCH_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            html = await resp.text()
        # PMN's own outage page (its real spelling), seen for every entity
        # on 2026-09-11 ~04:00 MT -- a listing failure, not "no notices".
        if "echnical Difficulties" in html:
            raise RuntimeError("PMN search returned its Technical Difficulties page")
        notices = pmn._parse_results_table(html)
        if not notices:
            break
        out.extend(notices)
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
    return out


async def _pmn_find_substitute(
    session: aiohttp.ClientSession,
    queue_url: str,
    existing_seconds: float,
    *,
    max_candidates: int,
    window: tuple[float, float],
    mb_per_min: dict[str, float],
    original_title: str | None = None,
) -> dict:
    lo, hi = window
    try:
        entity = await pmn_entity_of(session, queue_url)
        if not entity:
            return {
                "search_status": "error",
                "note": "notice detail carries no Entity field",
            }
        notices = await pmn_entity_notices(session, entity)
    except Exception as exc:  # noqa: BLE001
        return {
            "search_status": "error",
            "note": f"PMN listing failed: {type(exc).__name__}: {exc}"[:300],
        }
    pmn = _pmn_module()
    cands = [
        n
        for n in notices
        if n.notice_url != queue_url
        and pmn.looks_like_meeting_title(n.title)
        and any(cat.lower().startswith("audio") for _, _, cat in n.attachments)
    ]
    if not cands:
        return {
            "search_status": "none",
            "note": f"{len(notices)} notices for {entity!r}, none with an audio attachment",
        }
    ordered = prefer_same_body([(n.notice_url, n.title) for n in cands], original_title)
    by_url = {n.notice_url: n for n in cands}
    cands = [by_url[u] for u, _ in ordered]
    measured: list[tuple[str, float]] = []
    titles: dict[str, tuple[str, str]] = {}
    checked = 0
    for n in cands[:max_candidates]:
        checked += 1
        secs, source, _ = await probe_candidate(n.notice_url, "utah_pmn", mb_per_min)
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        if secs is None:
            continue
        titles[n.notice_url] = (n.title, source)
        measured.append((n.notice_url, secs))
        if lo <= secs <= hi:
            break
    pick, how = pick_substitute(measured, existing_seconds, lo=lo, hi=hi)
    if not pick:
        return {
            "search_status": "none",
            "candidates_checked": str(checked),
            "note": f"{len(measured)} measured for {entity!r}, none usable",
        }
    title, source = titles[pick]
    return _found_row(pick, how, dict(measured)[pick], title, source, checked, window)


# --- round-2 subcommands ---------------------------------------------------


def long_queue_rows(
    mb_per_min: dict[str, float],
) -> list[tuple[str, str, str | None, float, str]]:
    """(url, platform, source_override, seconds, duration_source) for every
    queue line the probe sidecar (or the old durations sidecar) shows
    longer than LONG_SECONDS. YouTube lines are never considered."""
    sidecar = load_probe_sidecar()
    old = _load_rows(DURATIONS_CSV, "queue_url")
    out = []
    for _, url, src in queue_lines():
        try:
            platform = detect_platform(url)
        except UnsupportedPlatformError:
            continue
        if platform in ("youtube", "vimeo"):
            continue
        secs, source = duration_from_row(sidecar.get(url), platform, mb_per_min)
        if secs is None and old.get(url, {}).get("duration_seconds"):
            secs, source = (
                float(old[url]["duration_seconds"]),
                old[url].get("duration_source", ""),
            )
        if secs is not None and secs > LONG_SECONDS:
            out.append((url, platform, src, secs, source))
    return out


def tenant_key(url: str, platform: str) -> str:
    return url if platform == "utah_pmn" else tenant_of(url)


async def cmd_search(args) -> None:
    """Round-2 replacement for `substitute`: every platform with a listing
    method (CivicClerk and Legistar through this script's own code, Utah
    PMN through the pilot's search, everything else through rtr-discovery),
    durations from the probe sidecar, 9-40 min window, shortest-usable
    fallback. Resumable through SEARCH_CSV."""
    register_all_finders()
    mb_per_min = calibrate_mb_per_min(load_probe_sidecar())
    longs = long_queue_rows(mb_per_min)
    by_tenant: dict[str, list] = {}
    for row in longs:
        by_tenant.setdefault(tenant_key(row[0], row[1]), []).append(row)
    done = _load_rows(SEARCH_CSV, "tenant")
    todo = [
        (k, rows)
        for k, rows in by_tenant.items()
        if k not in done
        or (args.retry_none and done[k].get("search_status") in ("none", "error"))
    ]
    if args.platform:
        todo = [(k, rows) for k, rows in todo if rows[0][1] == args.platform]
    if args.limit is not None:
        todo = todo[: args.limit]
    window = (args.min_minutes * 60.0, args.max_minutes * 60.0)
    print(
        f"{len(longs)} long queue rows across {len(by_tenant)} tenants; {len(done)} searched; "
        f"{len(todo)} to search now (window {_window_label(*window)})."
    )
    if not todo:
        return
    try:
        enumerators, _, _ = _discovery_modules()
        enumerable = set(enumerators)
    except RuntimeError as exc:
        print(f"[WARN] {exc} -- only CivicClerk/Legistar/Utah PMN will be searched")
        enumerable = set()
    writer = _RowWriter(SEARCH_CSV, SEARCH_FIELDS)
    try:
        async with aiohttp.ClientSession() as session:
            for i, (key, rows) in enumerate(todo, start=1):
                # the shortest long one sets the bar a fallback must beat
                url, platform, _, secs, _ = min(rows, key=lambda r: r[3])
                tenant = tenant_of(url)
                tenant_urls = [r[0] for r in rows]
                identity = await resolve_original(url, platform)
                original_title = identity["original_title"] or None
                if platform == "civicclerk":
                    result = await _cc_find_substitute_with_fallback(
                        session,
                        tenant,
                        {cc_event_id(u) for u in tenant_urls if cc_event_id(u)},
                        secs,
                        max_candidates=args.max_candidates,
                        window=window,
                    )
                elif platform == "legistar":
                    result = await _legistar_find_substitute(
                        session,
                        tenant,
                        {legistar_url_id(u) for u in tenant_urls if legistar_url_id(u)},
                        max_candidates=args.max_candidates,
                        window=window,
                    )
                elif platform == "utah_pmn":
                    result = await _pmn_find_substitute(
                        session,
                        url,
                        secs,
                        max_candidates=args.max_candidates,
                        window=window,
                        mb_per_min=mb_per_min,
                        original_title=original_title,
                    )
                elif platform in enumerable:
                    result = await _generic_find_substitute(
                        session,
                        platform,
                        tenant,
                        tenant_urls,
                        secs,
                        max_candidates=args.max_candidates,
                        window=window,
                        mb_per_min=mb_per_min,
                        original_title=original_title,
                    )
                else:
                    result = {
                        "search_status": "not_enumerable",
                        "note": f"no listing method for {platform}",
                    }
                row = {field: "" for field in SEARCH_FIELDS}
                row.update({"tenant": key, "platform": platform, **identity, **result})
                writer.write(row)
                print(
                    f"[{i}/{len(todo)}] {platform} {key[:60]} -> "
                    f"{row['substitute_url'] or row['search_status']}: {row['note'][:80]}"
                )
    finally:
        writer.close()


def cmd_apply(args) -> None:
    """Swap each found substitute into the queue file (keeping the line's
    TAB source field) and park the long original in DEFERRED_FILE. Dry run
    unless --apply. Never touches YouTube lines."""
    mb_per_min = calibrate_mb_per_min(load_probe_sidecar())
    searches = _load_rows(SEARCH_CSV, "tenant")
    longs = {
        url: (platform, src, secs)
        for url, platform, src, secs, _ in long_queue_rows(mb_per_min)
    }
    queued = set(queue_urls())
    raw = QUEUE_FILE.read_text().splitlines()
    swapped, deferred, used = [], [], set()
    out_lines = []
    for line in raw:
        stripped = line.strip()
        url = (
            stripped.partition("\t")[0].strip()
            if stripped and not stripped.startswith("#")
            else None
        )
        if url in longs:
            platform, src, secs = longs[url]
            search = searches.get(tenant_key(url, platform))
            sub = (search or {}).get("substitute_url")
            if (
                search
                and search.get("search_status") in ("found", "found_shortest")
                and sub
                and sub not in queued
                and sub not in used
            ):
                used.add(sub)
                out_lines.append(f"{sub}\t{src}" if src else sub)
                swapped.append(
                    (url, sub, secs, float(search["substitute_duration_seconds"]))
                )
                deferred.append(
                    "\t".join(
                        [
                            url,
                            src or "",
                            search.get("original_gov_id") or "",
                            search.get("original_jurisdiction") or "",
                            hms(secs),
                            (search.get("original_title") or "").replace("\t", " "),
                        ]
                    )
                )
                continue
        out_lines.append(line)
    saved = sum(a - b for _, _, a, b in swapped) / 3600
    print(
        f"{len(swapped)} line(s) would be swapped; ~{saved:.0f} Whisper hours saved; "
        f"{len(longs) - len(swapped)} long line(s) kept."
    )
    for url, sub, a, b in swapped[:20]:
        print(f"  {hms(a)} -> {hms(b)}  {url[:70]}")
    if not args.apply:
        print("Dry run -- pass --apply to write the queue file and the deferred file.")
        return
    QUEUE_FILE.write_text("\n".join(out_lines) + ("\n" if out_lines else ""))
    header = (
        ""
        if DEFERRED_FILE.exists()
        else "# Long tier-3 meetings (>90 min) swapped out of the queue for a shorter meeting from the same government; re-queue later for depth.\n# url<TAB>source_url<TAB>gov_id<TAB>jurisdiction<TAB>duration<TAB>title -- gov_id blank when the identity ladder declined; probe rows stay in tier3_auto_transcription_queue_probe.csv.\n"
    )
    with DEFERRED_FILE.open("a") as f:
        f.write(header + "".join(line + "\n" for line in deferred))
    print(
        f"Wrote {QUEUE_FILE.name} and appended {len(deferred)} line(s) to {DEFERRED_FILE.name}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_smoke = sub.add_parser("smoke", help="egress + ffprobe + durationMin check")
    p_smoke.add_argument("--validate-count", type=int, default=5)

    p_probe = sub.add_parser("probe", help="probe queue-row durations (resumable)")
    p_probe.add_argument("--concurrency", type=int, default=6)
    p_probe.add_argument("--limit", type=int, default=None)
    p_probe.add_argument(
        "--all-platforms",
        action="store_true",
        help="also adapter-resolve+ffprobe the non-enumerable platforms "
        "(hours more work; their tenants can't get substitutes regardless)",
    )
    p_probe.add_argument(
        "--no-api-durations",
        action="store_true",
        help="distrust CivicClerk's durationMin field and ffprobe everything",
    )

    p_sub = sub.add_parser("substitute", help="find a short meeting per long tenant")
    p_sub.add_argument("--max-candidates", type=int, default=8)
    p_sub.add_argument("--no-api-durations", action="store_true")
    p_sub.add_argument(
        "--min-minutes",
        type=float,
        default=SHORT_MIN_SECONDS / 60,
        help="lower bound of the acceptable substitute duration (minutes)",
    )
    p_sub.add_argument(
        "--max-minutes",
        type=float,
        default=SHORT_MAX_SECONDS / 60,
        help="upper bound of the acceptable substitute duration (minutes)",
    )
    p_sub.add_argument(
        "--retry-none",
        action="store_true",
        help="re-search only tenants whose earlier pass found nothing "
        "(for a widened-window fallback sweep); their sidecar rows are "
        "superseded",
    )

    sub.add_parser("report", help="write the committed report CSV")

    p_search = sub.add_parser(
        "search",
        help="round 2: find a 9-40 min substitute per long tenant (all listable platforms)",
    )
    p_search.add_argument("--limit", type=int, default=None)
    p_search.add_argument(
        "--platform", default=None, help="only tenants on this platform"
    )
    p_search.add_argument("--max-candidates", type=int, default=6)
    p_search.add_argument("--min-minutes", type=float, default=SHORT_MIN_SECONDS / 60)
    p_search.add_argument("--max-minutes", type=float, default=SHORT_MAX_SECONDS / 60)
    p_search.add_argument("--retry-none", action="store_true")

    p_apply = sub.add_parser(
        "apply",
        help="swap found substitutes into the queue file (dry run unless --apply)",
    )
    p_apply.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    _patch_proxy_env()

    if args.command == "smoke":
        asyncio.run(cmd_smoke(args))
    elif args.command == "probe":
        asyncio.run(cmd_probe(args))
    elif args.command == "substitute":
        asyncio.run(cmd_substitute(args))
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "search":
        asyncio.run(cmd_search(args))
    elif args.command == "apply":
        cmd_apply(args)


if __name__ == "__main__":
    main()
