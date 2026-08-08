import csv
import io
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiohttp
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import archive_client
from .db import crud
from .db.engine import init_models
from .platforms import register_all_finders
from .platforms.base import detect_platform, get_finder, CalendarPageError, UnsupportedPlatformError
from .platforms.media_probe import is_plausible_meeting_duration, probe_duration
from .utils.url_normalize import normalize_url

load_dotenv()

logger = logging.getLogger("rtr_deeplink.db")

APP_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_models()
    except Exception:
        # A down/misconfigured DB must never stop the app from serving --
        # it just means caching/reporting silently no-ops (see `safe()`).
        logger.exception("Failed to initialize DB models at startup; continuing without persistence.")
    yield


app = FastAPI(title="rtr-deeplink", lifespan=lifespan)

# /api/resolve is public and unauthenticated, and every call fans out to
# fetch a real government meeting site -- rate limiting protects both that
# site (being a good citizen about how hard we hit it) and this app's own
# Render bill from a scripted/abusive caller. Keyed by client IP via
# get_remote_address, which reads request.client.host -- only trustworthy
# in production because render.yaml's startCommand passes uvicorn
# --proxy-headers --forwarded-allow-ips='*' (Render's edge proxy is
# trusted infra, not an arbitrary client that could spoof the header
# itself). In-memory storage (slowapi's default) is fine for the current
# single-instance free-tier deploy; would need a shared backend (e.g.
# Redis) to stay correct across multiple instances.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals["GA_MEASUREMENT_ID"] = os.environ.get("GA_MEASUREMENT_ID", "")

register_all_finders()


class ResolveRequest(BaseModel):
    url: str


async def safe(fn, *args, **kwargs):
    """Run a DB-layer call, but never let it take down /api/resolve --
    the app worked with zero persistence before this feature and adding
    a DB must never become a new way for it to fail."""
    try:
        return await fn(*args, **kwargs)
    except Exception:
        logger.exception("DB call %s failed; continuing without it.", getattr(fn, "__name__", fn))
        return None


# How long a permanent Archive page can go untouched before a hit on it
# opportunistically triggers a background re-resolve. Government caption
# pipelines can take weeks to catch up (a meeting first archived blank,
# garbled, or agenda-only may get real captions added to the source
# later), but re-scraping on every visit to a popular meeting would be
# wasteful and impolite to the government site being scraped -- 30 days
# is a middle ground between those, not derived from any measured data.
ARCHIVE_RECHECK_AFTER = timedelta(days=30)
# A page missing a good transcript has real upside in being rechecked much
# sooner than a page that already has one -- the source may add real
# captions at any time, and there's nothing to lose by looking again.
# Still has a floor (not "every hit") so a popular page whose source will
# just never add captions doesn't get scraped on every visit -- same
# politeness reasoning ARCHIVE_RECHECK_AFTER was built on, just a shorter
# window. `has_transcript` comes from archive_client.lookup() (backed by
# archive/db/crud.py's _has_good_transcript()) -- absent on a lookup
# response from an Archive too old to have started sending it, in which
# case this falls back to the same 30-day cadence as before.
ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT = timedelta(hours=1)


def _parse_updated_at(raw: str):
    """MeetingPage.updated_at.isoformat() is tz-aware on Postgres (prod)
    but SQLite (local dev) doesn't enforce tz-awareness, so a naive string
    can come back from either side depending on where the Archive is
    running -- treat a naive timestamp as UTC rather than letting the
    aware/naive subtraction below raise."""
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _recheck_archived_page(url: str, normalized: str, platform: str) -> dict:
    """Re-resolve a permanent page and push if it finds real content. Used
    two ways: fired via BackgroundTasks on a lookup hit that's gone stale
    (ARCHIVE_RECHECK_AFTER, return value discarded -- a failure there just
    means the page stays as it was, so it's logged rather than raised), and
    called directly + awaited by /admin/recheck-archive-page below, which
    does want the outcome to show the caller what happened."""
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return {"error": "unsupported_platform", "platform": platform}
    try:
        result = await finder.resolve(url)
    except Exception as e:
        logger.exception("Archive re-check resolve failed for %s", url)
        return {"error": "resolve_failed", "message": str(e)}

    pushed = bool(result.segments or result.agenda_items)
    if pushed:
        await archive_client.push(result.model_dump(), normalized)

    return {
        "pushed": pushed,
        "platform": result.platform,
        "title": result.title,
        "segment_count": len(result.segments),
        "agenda_item_count": len(result.agenda_items),
        "transcript_warnings": result.transcript_warnings,
        "video_warnings": result.video_warnings,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/resolve")
@limiter.limit("20/minute")
async def resolve(request: Request, req: ResolveRequest, background_tasks: BackgroundTasks):
    platform = detect_platform(req.url)
    normalized = normalize_url(req.url)

    # Check the Archive before anything else -- if this meeting already has
    # a permanent page, that's the canonical version (potentially a better
    # transcript than a fresh scrape) and the one we want traffic/sharing to
    # land on, so redirect there instead of re-resolving from scratch.
    archived = await safe(archive_client.lookup, normalized)
    if archived:
        await safe(
            crud.log_resolution,
            input_url=req.url,
            input_url_normalized=normalized,
            input_platform=platform,
            status="archive_redirect",
        )
        updated_at = _parse_updated_at(archived.get("updated_at"))
        recheck_after = (
            ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT
            if archived.get("has_transcript") is False
            else ARCHIVE_RECHECK_AFTER
        )
        if updated_at and (datetime.now(timezone.utc) - updated_at) > recheck_after:
            background_tasks.add_task(_recheck_archived_page, req.url, normalized, platform)
        return {"redirect_url": archived["url"]}

    cached = await safe(crud.get_cached_resolution, normalized)
    if cached:
        # The Archive lookup above already came back empty for this URL, so
        # a locally-cached resolve with real content is a page that's never
        # been pushed -- opportunistically push it now instead of only ever
        # pushing on a fresh live resolve (a real gap: any URL cached before
        # the Archive integration existed, or while it was down/misconfigured,
        # would otherwise never become a permanent page on its own).
        if cached.get("segments") or cached.get("agenda_items"):
            background_tasks.add_task(archive_client.push, cached, normalized)
        return cached

    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        await safe(
            crud.log_resolution,
            input_url=req.url,
            input_url_normalized=normalized,
            input_platform=platform,
            status="unsupported_platform",
        )
        return {
            "error": "unsupported_platform",
            "platform": platform,
            "message": f"We don't support '{platform}' meeting pages yet.",
        }

    start = time.monotonic()
    try:
        result = await finder.resolve(req.url)
    except CalendarPageError as e:
        await safe(
            crud.log_resolution,
            input_url=req.url,
            input_url_normalized=normalized,
            input_platform=platform,
            status="calendar_page",
            error_message=str(e),
        )
        return {
            "error": "calendar_page",
            "platform": platform,
            "message": str(e),
            "candidates": e.candidates,
        }
    except Exception as e:
        await safe(
            crud.log_resolution,
            input_url=req.url,
            input_url_normalized=normalized,
            input_platform=platform,
            status="resolve_failed",
            error_message=str(e),
        )
        return {
            "error": "resolve_failed",
            "platform": platform,
            "message": str(e),
        }

    payload = result.model_dump()
    await safe(
        crud.log_resolution,
        input_url=req.url,
        input_url_normalized=normalized,
        input_platform=platform,
        resolved_platform=result.platform,
        external_id=result.external_id,
        status="success",
        video_found=bool(result.video_url),
        video_format=result.video_format,
        transcript_found=bool(result.segments),
        transcript_language=result.transcript_language,
        segment_count=len(result.segments),
        video_warnings=result.video_warnings,
        transcript_warnings=result.transcript_warnings,
        title=result.title,
        date=result.date,
        jurisdiction=result.jurisdiction,
        resolved_payload=payload,
        resolve_duration_ms=int((time.monotonic() - start) * 1000),
    )

    # Only push resolves with real content -- a transcript or agenda data --
    # so test pastes and broken URLs don't create junk permanent pages.
    # Fired via BackgroundTasks (not a bare asyncio.create_task) so it can't
    # be garbage-collected mid-flight and ties into the response lifecycle
    # properly; never blocks the response the user is waiting on.
    if result.segments or result.agenda_items:
        background_tasks.add_task(archive_client.push, payload, normalized)

    return payload


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NewsletterSignupRequest(BaseModel):
    email: str


@app.post("/api/newsletter/signup")
async def newsletter_signup(req: NewsletterSignupRequest):
    email = req.email.strip()
    if not _EMAIL_RE.match(email):
        return JSONResponse(
            {"error": "invalid_email", "message": "That doesn't look like a valid email address."},
            status_code=400,
        )

    api_key = os.environ.get("RESEND_API_KEY", "")
    audience_id = os.environ.get("RESEND_AUDIENCE_ID", "")
    if not api_key or not audience_id:
        logger.error("Newsletter signup attempted but RESEND_API_KEY/RESEND_AUDIENCE_ID isn't configured.")
        return JSONResponse(
            {"error": "signup_unavailable", "message": "Signups aren't available right now — please try again later."},
            status_code=503,
        )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.resend.com/audiences/{audience_id}/contacts",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"email": email, "unsubscribed": False},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status < 300:
                    return {"status": "subscribed"}
                body_text = await response.text()
                if "already" in body_text.lower():
                    return {"status": "already_subscribed"}
                logger.error("Resend signup failed (%s): %s", response.status, body_text)
    except Exception:
        logger.exception("Newsletter signup request to Resend failed.")

    return JSONResponse(
        {"error": "signup_failed", "message": "Something went wrong — please try again."},
        status_code=502,
    )


class ReportProblemRequest(BaseModel):
    url: str
    issue_type: str
    details: str = ""


@app.post("/api/report-problem")
@limiter.limit("10/minute")
async def report_problem(request: Request, req: ReportProblemRequest):
    if req.issue_type not in crud.VALID_ISSUE_TYPES:
        return JSONResponse(
            {"error": "invalid_issue_type", "message": "Unrecognized issue type."},
            status_code=400,
        )
    if not req.url.strip():
        return JSONResponse(
            {"error": "missing_url", "message": "No meeting URL was given."},
            status_code=400,
        )

    # Unlike caching/reporting (which degrade silently -- see `safe()`),
    # this is a direct response to a user action, so a storage failure
    # must say so rather than falsely claiming the report was received.
    # There's no "unconfigured" state to distinguish here, unlike Resend/GA
    # -- this app always has some database (SQLite fallback or Postgres,
    # see engine.py) -- so safe() returning None here always means a real
    # write failure.
    result = await safe(
        crud.log_problem_report,
        url=req.url.strip(),
        issue_type=req.issue_type,
        details=req.details.strip()[:2000] or None,
    )
    if result is None:
        return JSONResponse(
            {"error": "report_failed", "message": "Something went wrong — please try again."},
            status_code=502,
        )
    return {"status": "received"}


# On-demand transcription -------------------------------------------------
#
# Checkpoint granularity for the worker service, not an external API's
# file-size ceiling (self-hosted faster-whisper has none) -- see the plan
# this was built from for why. Frozen onto the TranscriptionJob row at
# creation, so changing this constant later never affects an in-flight job.
TRANSCRIPTION_CHUNK_SIZE_SECONDS = 900


class TranscriptionFeasibilityRequest(BaseModel):
    url: str


def _media_kind(video_format: Optional[str]) -> str:
    return "audio" if (video_format or "") in ("mp3", "wav") else "video"


@app.post("/api/transcription/check-feasibility")
@limiter.limit("5/hour")
async def transcription_check_feasibility(request: Request, req: TranscriptionFeasibilityRequest):
    """Live-resolves the meeting fresh (never the cache -- a stale/expired
    media URL would fail every chunk hours into a real job) and probes its
    real duration. Read-only: never touches the Archive, never spends a
    transcription request -- this is the client-side toggle-reveal step
    (see app/static/player.js), safe to run on every "Transcribe this
    meeting" click.
    """
    platform = detect_platform(req.url)
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return {"ok": False, "message": f"We don't support '{platform}' meeting pages yet."}

    try:
        result = await finder.resolve(req.url)
    except Exception as e:
        return {"ok": False, "message": f"Couldn't resolve this meeting: {e}"}

    if not result.video_url:
        return {"ok": False, "message": "No usable audio or video source was found for this meeting."}

    duration = await probe_duration(result.video_url, source_page_url=req.url)
    if duration is None:
        return {"ok": False, "message": "We found a media source but couldn't read it -- it may be unavailable."}
    if not is_plausible_meeting_duration(duration):
        return {
            "ok": False,
            "message": "The media we found doesn't look like a full meeting recording (unusual duration).",
        }

    return {
        "ok": True,
        "duration_seconds": duration,
        "media_kind": _media_kind(result.video_format),
        "message": None,
    }


class TranscriptionSubmitRequest(BaseModel):
    url: str
    email: str


@app.post("/api/transcription/submit")
@limiter.limit("5/hour")
async def transcription_submit(request: Request, req: TranscriptionSubmitRequest):
    """Re-runs the entire feasibility check server-side rather than trusting
    a client-supplied "it passed" flag -- this is the step that actually
    creates a job (and, for a first-time email, sends a real message), so
    a bad/missing media URL must never get this far on a forged request.
    """
    email = req.email.strip()
    if not _EMAIL_RE.match(email):
        return JSONResponse(
            {"error": "invalid_email", "message": "That doesn't look like a valid email address."},
            status_code=400,
        )

    platform = detect_platform(req.url)
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return JSONResponse(
            {"error": "unsupported_platform", "message": f"We don't support '{platform}' meeting pages yet."},
            status_code=400,
        )

    try:
        result = await finder.resolve(req.url)
    except Exception as e:
        return JSONResponse({"error": "resolve_failed", "message": str(e)}, status_code=400)

    if not result.video_url:
        return JSONResponse(
            {"error": "no_media", "message": "No usable audio or video source was found for this meeting."},
            status_code=400,
        )

    duration = await probe_duration(result.video_url, source_page_url=req.url)
    if duration is None or not is_plausible_meeting_duration(duration):
        return JSONResponse(
            {"error": "infeasible", "message": "We couldn't verify a usable media source for this meeting."},
            status_code=400,
        )

    normalized = normalize_url(req.url)
    job = await archive_client.request_transcription_job(
        payload=result.model_dump(),
        input_url_normalized=normalized,
        requester_email=email,
        media_url=result.video_url,
        media_kind=_media_kind(result.video_format),
        probed_duration_seconds=duration,
        chunk_size_seconds=TRANSCRIPTION_CHUNK_SIZE_SECONDS,
    )
    if job is None:
        return JSONResponse(
            {
                "error": "archive_unavailable",
                "message": "Transcription requests aren't available right now — please try again later.",
            },
            status_code=503,
        )
    if job.get("error") == "too_many_active_jobs":
        return JSONResponse(
            {
                "error": "too_many_active_jobs",
                "message": "We're at capacity for transcription requests right now — please try again later.",
            },
            status_code=429,
        )

    job.pop("requester_email", None)  # never echo a viewer's own email back into a public JSON response
    return job


@app.get("/api/transcription/status")
async def transcription_status(job_id: int):
    job = await archive_client.get_transcription_status(job_id)
    if job is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    job.pop("requester_email", None)
    return job


@app.get("/confirm-transcription")
async def confirm_transcription(request: Request, token: str = ""):
    job = await archive_client.confirm_transcription_job(token) if token else None
    return templates.TemplateResponse(
        request,
        "confirm_transcription.html",
        {"confirmed": job is not None, "meeting_page_slug": job.get("meeting_page_slug") if job else None},
    )


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/meeting")
async def meeting_redirect(request: Request, url: str = ""):
    if not url:
        return RedirectResponse("/")
    return templates.TemplateResponse(
        request,
        "meeting.html",
        {"source_url": url},
    )


async def _proxy_to_archive(internal_path: str, query_string: str) -> Response:
    """Reverse-proxies a GET request to the Archive service so its permanent
    pages are reachable at redtaperecordings.com/m/{slug} instead of a
    separate subdomain -- keeps SEO authority on one domain. These are
    public, potentially-indexed pages, so a clean failure (503 + message)
    matters more here than for /api/resolve; never let a raw exception or a
    hang reach the browser.
    """
    try:
        session, response = await archive_client.proxy_get(internal_path, query_string)
    except Exception:
        logger.exception("Archive proxy request failed for %s", internal_path)
        return Response(
            content="This page is temporarily unavailable — please try again shortly.",
            status_code=503,
            media_type="text/plain",
        )

    async def body_iterator():
        try:
            async for chunk in response.content.iter_chunked(65536):
                yield chunk
        finally:
            await session.close()

    return StreamingResponse(
        body_iterator(),
        status_code=response.status,
        media_type=response.headers.get("Content-Type"),
        headers=archive_client.filter_proxy_headers(response.headers),
    )


@app.get("/m/{path:path}")
async def archive_meeting_page(path: str, request: Request):
    return await _proxy_to_archive(f"m/{path}", str(request.query_params))


@app.get("/archive-static/{path:path}")
async def archive_static_asset(path: str, request: Request):
    return await _proxy_to_archive(f"static/{path}", str(request.query_params))


@app.get("/meetings")
async def archive_meetings_index(request: Request):
    return await _proxy_to_archive("meetings", str(request.query_params))


@app.get("/sitemap.xml")
async def archive_sitemap():
    return await _proxy_to_archive("sitemap.xml", "")


@app.get("/feed.xml")
async def archive_feed(request: Request):
    return await _proxy_to_archive("feed.xml", str(request.query_params))


@app.get("/robots.txt")
async def robots():
    # /meeting (singular) is the ephemeral resolver page -- once a URL is
    # archived, /m/{slug} is the canonical version, so keeping /meeting?url=
    # variants out of the index avoids thin/duplicate-content pages
    # competing with the permanent ones for the same query.
    lines = [
        "User-agent: *",
        "Disallow: /meeting",
        "Sitemap: https://redtaperecordings.com/sitemap.xml",
    ]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {})


@app.get("/subscribe")
async def subscribe(request: Request):
    return templates.TemplateResponse(request, "subscribe.html", {})


def _admin_token_ok(token: str) -> bool:
    expected = os.environ.get("ADMIN_STATS_TOKEN", "")
    return bool(expected) and secrets.compare_digest(token, expected)


@app.get("/admin/stats")
async def admin_stats(token: str = ""):
    # 404, not 401/403 -- the route's existence shouldn't be distinguishable
    # from a typo'd URL to anyone without the token.
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    stats = await safe(crud.get_stats)
    if stats is None:
        return JSONResponse({"error": "stats_unavailable"}, status_code=503)
    return stats


@app.get("/admin/log")
async def admin_log(token: str = "", limit: int = 200, format: str = "json"):
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    rows = await safe(crud.list_resolutions, limit)
    if rows is None:
        return JSONResponse({"error": "log_unavailable"}, status_code=503)

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["url", "outcome", "platform", "transcript_language", "created_at"])
        for row in rows:
            writer.writerow(
                [row["url"], row["outcome"], row["platform"], row["transcript_language"], row["created_at"]]
            )
        return Response(content=buf.getvalue(), media_type="text/csv")

    return rows


@app.get("/admin/problem-reports")
async def admin_problem_reports(token: str = "", limit: int = 200):
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    rows = await safe(crud.list_problem_reports, limit)
    if rows is None:
        return JSONResponse({"error": "reports_unavailable"}, status_code=503)
    return rows


@app.get("/admin/recheck-archive-page")
async def admin_recheck_archive_page(token: str = "", url: str = ""):
    """On-demand version of the ARCHIVE_RECHECK_AFTER background recheck --
    for when a permanent page needs refreshing sooner than 30 days (e.g. an
    adapter bug fix that should reach an already-archived page now, not on
    its next stale-lookup hit). Synchronous, not a BackgroundTask -- the
    caller is explicitly waiting to see the outcome, unlike the passive
    recheck this reuses."""
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if not url:
        return JSONResponse(
            {"error": "missing_url", "message": "Pass ?url=<the meeting's source URL>."}, status_code=400
        )

    platform = detect_platform(url)
    normalized = normalize_url(url)
    return await _recheck_archived_page(url, normalized, platform)
