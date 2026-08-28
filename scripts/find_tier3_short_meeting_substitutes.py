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
import sys
from datetime import datetime, timezone
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
from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.platforms.media_probe import binary_versions, probe_duration  # noqa: E402

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
SIDECAR_DIR = REPO_ROOT / "local_transcription_backups"
DURATIONS_CSV = SIDECAR_DIR / "tier3_queue_durations.csv"
SEARCH_CSV = SIDECAR_DIR / "tier3_substitute_search.csv"
REPORT_CSV = REPO_ROOT / "scripts" / "tier3_short_meeting_substitutes.csv"

LONG_SECONDS = 90 * 60
SHORT_MIN_SECONDS = 10 * 60
SHORT_MAX_SECONDS = 50 * 60

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


def queue_urls() -> list[str]:
    # Same parse feed_tier3_auto_transcription.py uses: whole stripped
    # line is the URL.
    return [
        line.strip() for line in QUEUE_FILE.read_text().splitlines() if line.strip()
    ]


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
    # (its first choice, EventsMedia's videoUrl, needs a second API call
    # -- callers that made one pass its videoUrl separately).
    return (
        event.get("mediaStreamPath")
        or event.get("mediaSourcePathMp4")
        or event.get("externalMediaUrl")
        or None
    )


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


def in_short_window(seconds: float) -> bool:
    return SHORT_MIN_SECONDS <= seconds <= SHORT_MAX_SECONDS


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
) -> dict:
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
            if api_duration is None or not in_short_window(api_duration):
                continue
            checked += 1
            substitute_url = cc_portal_url(tenant, event["id"])
            # One verification probe against the media file; if it can't
            # be verified the API duration still stands, honestly labeled.
            media_url = cc_media_path(event)
            verified = (
                await probe_duration(media_url, source_page_url=substitute_url)
                if media_url
                else None
            )
            if verified is not None and not in_short_window(verified):
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
                "note": "",
            }

    # No candidate had a populated in-window API duration -- ffprobe the
    # newest few with media until one lands in the window.
    for event in candidates[:max_candidates]:
        media_url = cc_media_path(event)
        if not media_url:
            continue
        checked += 1
        substitute_url = cc_portal_url(tenant, event["id"])
        duration = await probe_duration(media_url, source_page_url=substitute_url)
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        if duration is None or not in_short_window(duration):
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
            "note": "",
        }
    return {
        "search_status": "none",
        "candidates_checked": str(checked),
        "note": (
            f"no 10-50 min meeting among {len(candidates)} past events "
            f"({checked} duration-checked)"
        ),
    }


async def _legistar_find_substitute(
    session: aiohttp.ClientSession,
    tenant: str,
    exclude_ids: set[str],
    *,
    max_candidates: int,
) -> dict:
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
        if duration is None or not in_short_window(duration):
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
            "note": "",
        }
    return {
        "search_status": "none",
        "candidates_checked": str(checked),
        "note": (
            f"no 10-50 min meeting among {len(events)} past events "
            f"({checked} duration-checked)"
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

    done = _load_rows(SEARCH_CSV, "tenant")
    todo = [(t, p) for (t, p) in long_tenants.items() if t not in done]
    print(
        f"{len(long_tenants)} tenant(s) with a >90 min queue row, "
        f"{len(done)} already searched, {len(todo)} to search now."
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
                    )
                else:
                    result = await _legistar_find_substitute(
                        session, tenant, exclude, max_candidates=args.max_candidates
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

    with REPORT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for url in urls:
            platform = detect_platform(url)
            tenant = tenant_of(url)
            row = {field: "" for field in REPORT_FIELDS}
            row.update({"queue_url": url, "tenant": tenant, "platform": platform})
            probed = durations.get(url)
            if platform not in ENUMERABLE_PLATFORMS and not probed:
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
                    if search and search["search_status"] == "found":
                        row["status"] = "substitute_found"
                        for field in (
                            "substitute_url",
                            "substitute_title",
                            "substitute_date",
                            "substitute_duration_seconds",
                            "substitute_duration_hms",
                            "candidates_checked",
                        ):
                            row[field] = search[field]
                        row["notes"] = (
                            f"duration source: {search['substitute_duration_source']}"
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
                media_url = cc_media_path(event)
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

    sub.add_parser("report", help="write the committed report CSV")

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


if __name__ == "__main__":
    main()
