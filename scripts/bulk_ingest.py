"""Bulk-ingest a list of meeting URLs into the Archive.

Reuses the exact same resolve pipeline every real adapter and /api/resolve
already go through (app/platforms/base.py's detect_platform()/get_finder()),
then POSTs directly to the Archive's own POST /internal/ingest -- the same
endpoint app/archive_client.py's push() calls, except that fire-and-forget
helper discards the response, and this script needs the real returned
{"slug", "url"} back to confirm where each meeting landed.

Deliberately calls the underlying Python functions rather than going
through the deployed resolver's HTTP /api/resolve -- that route is rate-
limited (20/minute, slowapi, app/main.py), a decorator on the FastAPI route
itself, not enforced anywhere in the call stack this script actually uses.
Appropriate here since a bulk run is a deliberate, human-approved batch
action, not the case that limit exists to guard against.

Usage (from the repo root, with the venv active):
    python scripts/bulk_ingest.py urls.txt
    python scripts/bulk_ingest.py urls.txt --dry-run
    python scripts/bulk_ingest.py --playlist "https://www.youtube.com/playlist?list=..."
    python scripts/bulk_ingest.py urls.txt --gov-id us:place:0627000

urls.txt: one URL per line; blank lines and lines starting with # are
ignored. A line that's itself a YouTube playlist/watch?list= URL is
expanded to its member video URLs at run time (via yt-dlp's flat
extraction -- confirmed live 2026-08-11 against a real 66-video "Town
Council Meetings" playlist), so a playlist URL can also just be dropped
into the file directly instead of using --playlist.

gov_id (WO-222): when the caller already knows which government a URL
belongs to -- the common case, every enumeration method in
rtr-business starts from a known gov_id (docs/COVERAGE_HANDOVER.md §3)
-- pass it and the ingested page is keyed to it immediately, rather than
depending on a tenant_overrides.csv pin reaching production before the
page is created (a YouTube/Vimeo/other shared-host page otherwise lands
`rtr:unknown:<host>` until that pin deploys). Two ways to supply one,
usable together: (1) a second, tab-separated field on a urls.txt line
(`https://youtu.be/abc123<TAB>us:place:0627000`) -- a playlist line's
gov_id, if any, applies to every video it expands to; (2) `--gov-id`,
applied to every URL in this run (file lines and --playlist URLs alike)
that doesn't already carry its own per-line gov_id. A URL with neither
is ingested exactly as before -- the ladder in
app/utils/gov_registry/resolver.py decides its government, same as
every other existing caller of this script.

Requires ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN in the repo's local
.env (or already exported in the environment) -- the real Render values
for the deployed Archive service, not the .env.example placeholders.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import certifi

# Must run before `import aiohttp` -- confirmed live 2026-08-21 (see
# scripts/transcribe_backlog_locally.py's own longer comment on this same
# fix for the full root cause): a fresh Homebrew-Python venv has an empty
# default SSL trust store, and aiohttp/connector.py builds+caches its
# default SSLContext as a module-level statement evaluated the instant
# `import aiohttp` runs, not lazily on first connection -- so this has to
# exist before that import line, not just before this script's own first
# network call.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
import yt_dlp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()  # ARCHIVE_* env vars are populated by the time _base_url()/_headers() below read them

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
    probe_queue_entry,
)
from app.utils.url_normalize import normalize_url  # noqa: E402

REQUEST_DELAY_SECONDS = 1.5
INGEST_TIMEOUT = aiohttp.ClientTimeout(
    total=65
)  # matches archive_client.PUSH_TIMEOUT -- tolerates a Render cold start


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _read_urls(path: str) -> List[Tuple[str, Optional[str]]]:
    """Returns (url, gov_id) pairs. gov_id is None unless the line carries
    an optional second, tab-separated field -- see this module's own
    docstring (WO-222) for the format and why."""
    urls = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        url = parts[0].strip()
        gov_id = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        urls.append((url, gov_id))
    return urls


def _playlist_id(url: str) -> Optional[str]:
    """Returns the `list=` query param if present -- covers both a bare
    playlist URL (youtube.com/playlist?list=...) and a single video's URL
    when it was copied from within a playlist (watch?v=...&list=...).
    Either shape means "expand this to every video in the playlist", not
    just the one video."""
    query = parse_qs(urlparse(url).query)
    values = query.get("list")
    return values[0] if values else None


def _expand_playlist(playlist_id: str) -> List[str]:
    """Flat-extracts a YouTube playlist's member video URLs via yt-dlp,
    without downloading anything. Confirmed live 2026-08-11 against a
    real 66-video "Town Council Meetings" playlist -- ordinary
    extract_flat, no special options needed the way single-video
    resolves in app/platforms/youtube.py do (that file's player_client
    workaround is for the anti-bot check on actual caption/format
    extraction, which flat playlist listing never touches)."""
    opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/playlist?list={playlist_id}", download=False
        )
    entries = (info or {}).get("entries") or []
    return [e["url"] for e in entries if e.get("url")]


def _expand_urls(
    urls: List[Tuple[str, Optional[str]]],
) -> List[Tuple[str, Optional[str]]]:
    """Replaces any playlist/in-playlist URL in the list with its member
    video URLs, preserving order and leaving every other URL untouched. A
    playlist line's own gov_id (if any) is carried onto every video it
    expands to -- one playlist is one government's own channel in every
    real case this script has been used against."""
    expanded: List[Tuple[str, Optional[str]]] = []
    for url, gov_id in urls:
        playlist_id = _playlist_id(url)
        if not playlist_id:
            expanded.append((url, gov_id))
            continue
        video_urls = _expand_playlist(playlist_id)
        print(f"[PLAYLIST] {url}\n           expanded to {len(video_urls)} video(s)")
        expanded.extend((video_url, gov_id) for video_url in video_urls)
    return expanded


class IngestGateRejected(RuntimeError):
    """Raised by _ingest() when WO-156's duration/dead-link gate refuses a
    payload before it ever reaches the Archive. str(exception) is exactly
    the "[SKIP] <verdict>: <reason>" shape every other probe caller in
    this repo already logs (scripts/feed_tier3_auto_transcription.py's
    own [SKIP] lines), so a caller's existing `except Exception as e:
    ...f"...{e}"` handling surfaces it in the same recognizable form
    without needing its own except clause."""


async def _ingest(
    session: aiohttp.ClientSession,
    payload: dict,
    input_url_normalized: str,
    *,
    already_probed: bool = False,
    caller: str = "bulk_ingest",
) -> Optional[dict]:
    """POSTs `payload` to the Archive's /internal/ingest.

    WO-156: every one of this function's 10 real callers (see
    BACKLOG_DONE.md's WO-156 entry -- feed_granicus_auto_transcription.py
    inherits this too, since it shells out to this script) creates a real
    Archive page with no duration/dead-link check of its own. Only the
    tier-3 queue (WO-144's probe_queue_entry(), wired into
    feed_tier3_auto_transcription.py) and the worker's claim-time check
    (worker/main.py's probe_duration()/is_plausible_meeting_duration())
    gated this before today -- meaning a tier-1/2 sweep result (real
    segments, `_ingest_with_retry()` in scripts/wo134_confirmed_hits_
    ingest.py and the ~9 scripts like it) walked straight past both. A
    59-second "Larry J. Dix Boardroom" camera clip became a real county
    page this exact way (WO-149, 2026-09-10, deleted by hand).

    So: whenever `payload` carries a `video_url`, this runs WO-144's own
    probe_queue_entry() (metadata only, never a download) and refuses a
    `reject-dead`/`reject-short` verdict before the POST -- a
    `flag-long` verdict (a real multi-hour meeting, see queue_probe.py's
    own Anaheim comment) is still accepted. `already_probed=True` skips
    this **only** when `payload` also carries real `segments` -- a
    caller that already ran the exact same probe on a *tier-3* (video,
    no captions) payload moments ago (feed_tier3_auto_transcription.py's
    `_push_if_has_video()`) still gets probed again here, deliberately:
    a video-only payload is precisely the shape WO-149's incident came
    from, so this gate never takes an upstream caller's word for it on
    that shape, only on a tier-1/2 (real-transcript) one where the risk
    this WO exists for doesn't apply. No current caller passes both
    `already_probed=True` and a `segments`-bearing payload (none probes a
    tier-1/2 result before calling this), so today this always runs for
    a video_url-bearing payload in practice -- documented here rather
    than silently, so a future caller that adds that combination knows
    exactly what it's opting out of.

    The worker's own claim-time gate is untouched and stays a second,
    independent check -- this only stops a bad payload from becoming a
    page in the first place; it doesn't replace that check.
    """
    video_url = payload.get("video_url")
    skip_probe = already_probed and bool(payload.get("segments"))
    if video_url and not skip_probe:
        probe = await probe_queue_entry(
            payload.get("source_url") or input_url_normalized,
            video_url=video_url,
            source_page_url=payload.get("source_url"),
            platform=payload.get("platform"),
        )
        append_probe_row(DEFAULT_SIDECAR_PATH, probe, caller=caller)
        if probe.verdict.startswith("reject-"):
            raise IngestGateRejected(f"[SKIP] {probe.verdict}: {probe.reason}")

    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(
        f"{_base_url()}/internal/ingest",
        json=body,
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    ) as response:
        if response.status == 200:
            return await response.json()
        text = await response.text()
        raise RuntimeError(f"ingest failed ({response.status}): {text[:300]}")


async def process_one(
    session: aiohttp.ClientSession,
    url: str,
    *,
    dry_run: bool,
    gov_id: Optional[str] = None,
) -> dict:
    """Returns a result dict: {"url", "status": "ingested"|"skipped"|"failed", "detail"}.

    `gov_id` (WO-222), when given, rides into the ingest payload so the
    page keys to it immediately -- see this module's docstring."""
    try:
        platform = detect_platform(url)
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return {
            "url": url,
            "status": "failed",
            "detail": f"unsupported platform (detected: {platform!r})",
        }

    try:
        result = await finder.resolve(url)
    except CalendarPageError as e:
        return {
            "url": url,
            "status": "failed",
            "detail": f"calendar page, not a single meeting: {e}",
        }
    except Exception as e:
        return {"url": url, "status": "failed", "detail": f"resolve raised: {e}"}

    # Same gate app/main.py's /api/resolve already uses to decide whether a
    # resolve is worth pushing to the Archive at all. Includes video_url --
    # a video-only resolve (no transcript/agenda yet) is still real content
    # worth an Archive page; several adapters (Cablecast, ChampDS, PrimeGov's
    # YouTube-delegated path) can populate video_url with segments/
    # agenda_items/agenda_link all empty, and omitting it here silently
    # dropped real, ingestable meetings (see BACKLOG_DONE.md).
    if not (
        result.segments or result.agenda_items or result.agenda_link or result.video_url
    ):
        return {
            "url": url,
            "status": "skipped",
            "detail": f"platform={result.platform}, no transcript, agenda items, agenda link, or video found",
        }

    normalized = normalize_url(url)
    if dry_run:
        return {
            "url": url,
            "status": "skipped",
            "detail": (
                f"[dry-run] would ingest: platform={result.platform}, title={result.title!r}, "
                f"segments={len(result.segments)}, agenda_items={len(result.agenda_items)}"
                + (f", gov_id={gov_id!r}" if gov_id else "")
            ),
        }

    # WO-222: send the caller's gov_id, when it has one, so the page keys
    # to it immediately rather than depending on a tenant_overrides.csv
    # pin reaching production first (see this module's docstring). Omitted
    # entirely rather than sent as "" when blank/None, so this is
    # indistinguishable from every prior call to _ingest() that never knew
    # a gov_id.
    payload = result.model_dump()
    if gov_id:
        payload["gov_id"] = gov_id
    try:
        response = await _ingest(session, payload, normalized)
    except Exception as e:
        return {"url": url, "status": "failed", "detail": f"ingest failed: {e}"}

    page_url = response.get("url") if response else None
    return {
        "url": url,
        "status": "ingested",
        "detail": page_url or "(no url in response)",
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "urls_file",
        nargs="?",
        help="Path to a text file with one meeting URL per line (omit if using --playlist alone)",
    )
    parser.add_argument(
        "--playlist",
        action="append",
        default=[],
        metavar="URL",
        help="A YouTube playlist (or in-playlist video) URL to expand and ingest; repeatable",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and report, but don't actually ingest",
    )
    parser.add_argument(
        "--gov-id",
        default=None,
        metavar="GOV_ID",
        help=(
            "WO-222: applied to every URL in this run (urls_file lines and "
            "--playlist URLs alike) that doesn't already carry its own "
            "per-line gov_id (a tab-separated second field in urls_file) -- "
            "so the page(s) key to this government immediately instead of "
            "depending on a tenant_overrides.csv pin. Use for a single-"
            "government run, e.g. one YouTube channel/playlist."
        ),
    )
    args = parser.parse_args()

    if not _base_url():
        print(
            "ERROR: ARCHIVE_BASE_URL is not set (check the repo's .env).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.dry_run and not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.urls_file and not args.playlist:
        print("ERROR: pass a urls_file, --playlist, or both.", file=sys.stderr)
        sys.exit(1)

    raw_urls: List[Tuple[str, Optional[str]]] = (
        _read_urls(args.urls_file) if args.urls_file else []
    ) + [(u, None) for u in args.playlist]
    if not raw_urls:
        print(f"No URLs found in {args.urls_file}.", file=sys.stderr)
        sys.exit(1)

    if args.gov_id:
        # --gov-id is a fallback: a URL's own per-line gov_id (urls_file's
        # optional tab-separated field) always wins over it.
        raw_urls = [(u, gid or args.gov_id) for u, gid in raw_urls]

    urls = _expand_urls(raw_urls)
    if not urls:
        print("No URLs left after playlist expansion.", file=sys.stderr)
        sys.exit(1)

    register_all_finders()

    print(
        f"{'[DRY RUN] ' if args.dry_run else ''}Processing {len(urls)} URL(s) against {_base_url()}...\n"
    )

    results = []
    async with aiohttp.ClientSession() as session:
        for i, (url, gov_id) in enumerate(urls):
            result = await process_one(
                session, url, dry_run=args.dry_run, gov_id=gov_id
            )
            results.append(result)
            print(
                f"[{result['status'].upper():8}] {url}\n           {result['detail']}"
            )
            if i < len(urls) - 1:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

    ingested = [r for r in results if r["status"] == "ingested"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed = [r for r in results if r["status"] == "failed"]
    print(
        f"\n{len(ingested)} ingested, {len(skipped)} skipped, {len(failed)} failed (of {len(urls)} total)."
    )


if __name__ == "__main__":
    asyncio.run(main())
