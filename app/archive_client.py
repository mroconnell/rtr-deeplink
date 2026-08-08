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
# Same reasoning as LOOKUP_TIMEOUT -- these three block a real user-facing
# resolver request/response (not fired via BackgroundTasks), so they need
# a bound that fails fast rather than making a viewer wait out a slow/cold
# Archive.
TRANSCRIPTION_TIMEOUT = aiohttp.ClientTimeout(total=15)

_HOP_BY_HOP_HEADERS = {"connection", "transfer-encoding", "keep-alive", "content-encoding", "content-length"}


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


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


async def push(payload: dict[str, Any], input_url_normalized: str) -> None:
    """Push a completed resolve to the Archive to create a permanent page
    or attach a new transcript version to an existing one. Fire-and-forget
    from the caller's perspective (see app/main.py's BackgroundTasks use) --
    failures are logged, never raised.
    """
    base = _base_url()
    if not base:
        return

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
                    logger.error("Archive ingest failed (%s): %s", response.status, text)
    except Exception:
        logger.exception("Archive ingest request failed.")


async def request_transcription_job(
    *,
    payload: dict[str, Any],
    input_url_normalized: str,
    requester_email: str,
    media_url: str,
    media_kind: str,
    probed_duration_seconds: float,
    chunk_size_seconds: int,
) -> Optional[dict]:
    """Ask the Archive to create (or return the existing active) on-demand
    transcription job for this meeting. Returns None if the Archive is
    unreachable/unconfigured or the call otherwise fails -- the caller
    (app/main.py's /api/transcription/submit) turns that into a clean
    user-facing error rather than a raw exception, same pattern as
    lookup()."""
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
                logger.error("Archive transcription create-job failed (%s): %s", response.status, await response.text())
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


async def proxy_get(path: str, query_string: str):
    """Forward a GET request to the Archive service and return the raw
    aiohttp response (caller streams it back to the client). Raises on
    connection failure/timeout -- app/main.py's proxy routes decide how to
    present that to the browser, since these are public pages and want a
    clean branded failure, not a raw exception.
    """
    base = _base_url()
    if not base:
        raise RuntimeError("ARCHIVE_BASE_URL is not configured")

    url = f"{base}/{path}"
    if query_string:
        url = f"{url}?{query_string}"

    session = aiohttp.ClientSession(timeout=PROXY_TIMEOUT)
    response = await session.get(url)
    return session, response


def filter_proxy_headers(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
