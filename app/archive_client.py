import logging
import os
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("rtr_deeplink.archive")

# lookup() indirectly blocks the user-visible /api/resolve response, so it
# gets a short bound -- better to fall through to a live resolve than make
# the user wait on a slow/cold Archive. push() has nothing user-visible
# waiting on it (fired via BackgroundTasks), so it can afford to sit out a
# Render free-tier cold start (~30-60s) rather than fail fast and silently
# drop a real meeting.
LOOKUP_TIMEOUT = aiohttp.ClientTimeout(total=5)
PUSH_TIMEOUT = aiohttp.ClientTimeout(total=65)
PROXY_TIMEOUT = aiohttp.ClientTimeout(total=65)
# Tighter than LOOKUP_TIMEOUT, and deliberately so: what this buys is one
# *optional* section on the busiest, most-indexed page on the site, so
# the value of waiting is far lower than for lookup() (which can save a
# whole live resolve). Measured against a deliberately-hanging Archive,
# the 5s budget made the home page take 5.2s to render a page it was
# always going to render without the section. The only case a longer
# budget would rescue is "alive but briefly slow" -- a Render cold start
# is 30-60s and hopeless at any of these values. app/main.py caches the
# failure for 30s on top, so few requests pay even this.
HOME_TIMEOUT = aiohttp.ClientTimeout(total=2)
# Same reasoning as LOOKUP_TIMEOUT -- these three block a real user-facing
# resolver request/response (not fired via BackgroundTasks), so they need
# a bound that fails fast rather than making a viewer wait out a slow/cold
# Archive.
TRANSCRIPTION_TIMEOUT = aiohttp.ClientTimeout(total=15)
# A single call here fans out to N Clerk lookups + N Resend sends inside
# Archive's own /internal/account/send-search-alerts handler, unlike every
# other proxy call above (one object in, one object out) -- needs real
# headroom for a corpus-wide sweep, not the fast-fail budget those get.
SEARCH_ALERTS_TIMEOUT = aiohttp.ClientTimeout(total=120)

_HOP_BY_HOP_HEADERS = {
    "connection",
    "transfer-encoding",
    "keep-alive",
    "content-encoding",
    "content-length",
}


# aiohttp raises NonHttpUrlClientError from deep inside the request when
# handed a schemeless URL, which is what a real production window looked
# like on 2026-08-22 (Sentry PYTHON-FASTAPI-Y:
# `rtr-deeplink-archive:10000/coverage`, i.e. an ARCHIVE_BASE_URL set to a
# bare host:port). ARCHIVE_BASE_URL is `sync: false` in render.yaml --
# dashboard-managed, so nothing in this repo constrains its shape, and the
# next planned change to it (pointing it at Render's internal address, see
# BACKLOG.md's bandwidth entry) is exactly the edit that can reintroduce
# the bad shape.
_VALID_BASE_URL_SCHEMES = ("http://", "https://")


def configuration_problem() -> Optional[str]:
    """Why ARCHIVE_BASE_URL is unusable, or None when it's fine.

    Only reports a value that is *set but wrong*. An unset variable is a
    valid configuration here (local development with no Archive), and
    every caller below already degrades correctly on it.

    Called at resolver startup (app/main.py's lifespan) so a bad value
    shows up once in the deploy log, rather than only as a per-request
    failure on every proxied page.
    """
    raw = os.environ.get("ARCHIVE_BASE_URL", "").strip()
    if raw and not raw.startswith(_VALID_BASE_URL_SCHEMES):
        return (
            f"ARCHIVE_BASE_URL is set to {raw!r}, which has no http:// or "
            "https:// scheme. The Archive will be treated as unconfigured "
            "and every proxied page will fail until it's fixed in Render's "
            "dashboard."
        )
    return None


def _base_url() -> str:
    """The Archive's base URL, or "" when it isn't usable.

    A value set without an http:// or https:// scheme is treated as
    *unusable* rather than passed through. Every caller in this module
    already degrades correctly on "" -- a down or misconfigured Archive
    must never block a live resolve -- so this converts an obscure
    aiohttp error raised once per proxied page view into this module's
    own explicit handling.
    """
    if configuration_problem():
        return ""
    return os.environ.get("ARCHIVE_BASE_URL", "").strip().rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def lookup(normalized_url: str) -> Optional[dict]:
    """Check whether a permanent Archive page already exists for this
    (normalized) input URL. Returns None on any failure -- a down/
    misconfigured Archive must never block a live resolve, same
    reasoning as the resolver's own safe() wrapper around DB calls.
    """
    base = _base_url()
    if not base:
        return None

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base}/internal/lookup",
            params={"normalized_url": normalized_url},
            headers=_headers(),
            timeout=LOOKUP_TIMEOUT,
        ) as response:
            if response.status == 200:
                return await response.json()
            return None


async def home_highlights(topic: str = "") -> Optional[dict]:
    """Topic chips + the national recent-moments feed + browse-by-state,
    for the home page. None on any failure.

    Same posture as lookup() above and the same reason, sharpened: this
    blocks the busiest, most-indexed page on the domain, so it gets the
    fast-fail budget rather than the generous one. A down, cold or slow
    Archive must cost the home page one optional section and nothing
    else -- never a 500, never a hang. app/main.py's index() renders the
    section only when this returns a dict.
    """
    base = _base_url()
    if not base:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base}/internal/home-highlights",
                params={"topic": topic} if topic else None,
                headers=_headers(),
                timeout=HOME_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.warning("home highlights fetch failed", exc_info=True)
        return None


async def list_all_page_urls() -> Optional[list[dict]]:
    """Every archived page's real source URL + platform -- the backfill
    sweep's starting point (scripts/backfill_archived_pages.py). Returns
    None on any failure, same pattern as every other call here."""
    base = _base_url()
    if not base:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base}/internal/pages/all-urls",
                headers=_headers(),
                timeout=PROXY_TIMEOUT,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("pages")
                logger.error(
                    "Archive all-urls fetch failed (%s): %s",
                    response.status,
                    await response.text(),
                )
                return None
    except Exception:
        logger.exception("Archive all-urls request failed.")
        return None


async def push(payload: dict[str, Any], input_url_normalized: str) -> bool:
    """Push a completed resolve to the Archive to create a permanent page
    or attach a new transcript version to an existing one. Fire-and-forget
    from most callers' perspective (see app/main.py's BackgroundTasks use)
    -- failures are logged, never raised.

    Returns True/False (success or not) rather than the previous bare
    None -- app/main.py's _push_and_track() needs this to know whether to
    mark_archive_pushed() or record_archive_push_failure() (see
    BACKLOG_DONE.md's silent-push-loss entry for why that tracking
    exists). A caller that doesn't care can still ignore the return value.
    """
    base = _base_url()
    if not base:
        return False

    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/ingest",
                json=body,
                headers=_headers(),
                timeout=PUSH_TIMEOUT,
            ) as response:
                if response.status >= 300:
                    text = await response.text()
                    logger.error(
                        "Archive ingest failed (%s): %s", response.status, text
                    )
                    return False
                return True
    except Exception:
        logger.exception("Archive ingest request failed.")
        return False


async def request_transcription_job(
    *,
    payload: dict[str, Any],
    input_url_normalized: str,
    requester_email: str,
    media_url: str,
    media_kind: str,
    probed_duration_seconds: float,
    chunk_size_seconds: int,
    clerk_verified: bool = False,
) -> Optional[dict]:
    """Ask the Archive to create (or return the existing active) on-demand
    transcription job for this meeting. Returns None if the Archive is
    unreachable/unconfigured or the call otherwise fails -- the caller
    (app/main.py's /api/transcription/submit) turns that into a clean
    user-facing error rather than a raw exception, same pattern as
    lookup().

    clerk_verified: real result of get_clerk_user_id(request) in the
    caller, not a client-asserted flag -- lets Archive skip the
    confirm-by-email step for an already-signed-in visitor the same way
    an existing newsletter subscriber's email already does (user request
    2026-08-11).
    """
    base = _base_url()
    if not base:
        return None

    body = {
        "payload": payload,
        "input_url_normalized": input_url_normalized,
        "requester_email": requester_email,
        "media_url": media_url,
        "media_kind": media_kind,
        "probed_duration_seconds": probed_duration_seconds,
        "chunk_size_seconds": chunk_size_seconds,
        "clerk_verified": clerk_verified,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/transcription/create-job",
                json=body,
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(
                    "Archive transcription create-job failed (%s): %s",
                    response.status,
                    await response.text(),
                )
                return None
    except Exception:
        logger.exception("Archive transcription create-job request failed.")
        return None


async def confirm_transcription_job(token: str) -> Optional[dict]:
    base = _base_url()
    if not base:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/transcription/confirm",
                json={"token": token},
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.exception("Archive transcription confirm request failed.")
        return None


async def get_transcription_status(job_id: int) -> Optional[dict]:
    base = _base_url()
    if not base:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base}/internal/transcription/status/{job_id}",
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.exception("Archive transcription status request failed.")
        return None


async def save_meeting(clerk_user_id: str, slug: str) -> Optional[dict]:
    base = _base_url()
    if not base:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/account/save-meeting",
                json={"clerk_user_id": clerk_user_id, "slug": slug},
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.exception("Archive save-meeting request failed.")
        return None


async def unsave_meeting(clerk_user_id: str, slug: str) -> Optional[dict]:
    base = _base_url()
    if not base:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/account/unsave-meeting",
                json={"clerk_user_id": clerk_user_id, "slug": slug},
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.exception("Archive unsave-meeting request failed.")
        return None


async def save_search(clerk_user_id: str, search_params: dict) -> Optional[dict]:
    base = _base_url()
    if not base:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/account/save-search",
                json={"clerk_user_id": clerk_user_id, "search_params": search_params},
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.exception("Archive save-search request failed.")
        return None


async def unsave_search(clerk_user_id: str, saved_item_id: int) -> Optional[dict]:
    base = _base_url()
    if not base:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/account/unsave-search",
                json={"clerk_user_id": clerk_user_id, "saved_item_id": saved_item_id},
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.exception("Archive unsave-search request failed.")
        return None


async def delete_account_data(clerk_user_id: str) -> Optional[dict]:
    """Called only from the Clerk user.deleted webhook handler -- see
    archive/db/crud.py's delete_account_data() for what this actually
    removes and why that's the entire right-to-deletion story on our
    side."""
    base = _base_url()
    if not base:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/account/delete-data",
                json={"clerk_user_id": clerk_user_id},
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        logger.exception("Archive delete-account-data request failed.")
        return None


async def proxy_get(
    path: str,
    query_string: str,
    cookie_header: Optional[str] = None,
    extra_headers: Optional[dict] = None,
):
    """Forward a GET request to the Archive service and return the raw
    aiohttp response (caller streams it back to the client). Raises on
    connection failure/timeout -- app/main.py's proxy routes decide how to
    present that to the browser, since these are public pages and want a
    clean branded failure, not a raw exception.

    cookie_header, when given, is forwarded as-is so Archive can verify
    the visitor's Clerk session itself (see archive/utils/clerk_auth.py) --
    only the handful of call sites that render auth-aware content pass
    one (see app/main.py's proxy routes); static assets/sitemap/feed don't
    need it and don't send it.

    extra_headers exists for conditional requests: /m/{slug}/card.jpg
    (WO-28) is the first proxied route that returns a real ETag, and
    without forwarding the client's If-None-Match the Archive can never
    answer 304 through the public domain -- every Googlebot/social-scraper
    refetch would re-stream the full image through two services. Kept as
    an explicit opt-in per call site rather than a blanket
    forward-everything, matching how cookie_header is already handled.
    """
    base = _base_url()
    if not base:
        # Covers both "unset" and "set to something unusable" -- see
        # _base_url(), which logs the specific reason for the latter.
        raise RuntimeError("ARCHIVE_BASE_URL is not configured or is not usable")

    url = f"{base}/{path}"
    if query_string:
        url = f"{url}?{query_string}"

    headers = dict(extra_headers or {})
    if cookie_header:
        headers["Cookie"] = cookie_header
    session = aiohttp.ClientSession(timeout=PROXY_TIMEOUT)
    try:
        response = await session.get(url, headers=headers or None)
    except Exception:
        # session.get() itself can raise (timeout, connection reset, DNS
        # failure) before headers ever come back -- if we don't close the
        # session here it leaks until GC finalizes it, which is when
        # aiohttp emits its "Unclosed connector" warning (confirmed via
        # Sentry issues PYTHON-FASTAPI-V/PYTHON-FASTAPI-S, 2026-08-20/21).
        await session.close()
        raise
    return session, response


def filter_proxy_headers(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}


async def promote_transcript_version(slug: str, version_id: int) -> Optional[dict]:
    """Admin action: make `version_id` this page's default TranscriptVersion
    -- see app/main.py's /admin/promote-transcript-version and
    BACKLOG_DONE.md's 2026-08-12 stale-transcript entry. Returns None on
    any failure, same pattern as every other call here."""
    base = _base_url()
    if not base:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/transcript-version/promote",
                json={"slug": slug, "version_id": version_id},
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(
                    "Archive promote-version failed (%s): %s",
                    response.status,
                    await response.text(),
                )
                return None
    except Exception:
        logger.exception("Archive promote-version request failed.")
        return None


async def send_search_alerts(dry_run: bool = False) -> Optional[dict]:
    """Admin action: run the saved-search alert sweep -- see app/main.py's
    /admin/send-search-alerts. Returns None on any failure, same pattern
    as every other call here."""
    base = _base_url()
    if not base:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/account/send-search-alerts",
                params={"dry_run": "true" if dry_run else "false"},
                headers=_headers(),
                timeout=SEARCH_ALERTS_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(
                    "Archive send-search-alerts failed (%s): %s",
                    response.status,
                    await response.text(),
                )
                return None
    except Exception:
        logger.exception("Archive send-search-alerts request failed.")
        return None


async def correct_transcript_language(
    slug: str, language: str, version_id: Optional[int] = None
) -> Optional[dict]:
    """Admin correction for a wrong TranscriptVersion.language -- see
    app/main.py's /admin/correct-transcript-language and BACKLOG_DONE.md's
    language-picker entry. Returns None on any failure, same pattern as
    every other call here."""
    base = _base_url()
    if not base:
        return None

    body: dict[str, Any] = {"slug": slug, "language": language}
    if version_id is not None:
        body["version_id"] = version_id

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/internal/transcript-version/correct-language",
                json=body,
                headers=_headers(),
                timeout=TRANSCRIPTION_TIMEOUT,
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(
                    "Archive correct-language failed (%s): %s",
                    response.status,
                    await response.text(),
                )
                return None
    except Exception:
        logger.exception("Archive correct-language request failed.")
        return None
