import csv
import html
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
from urllib.parse import quote

import aiohttp
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from svix.webhooks import Webhook

load_dotenv()

from . import archive_client, reporting
from .db import crud
from .db.engine import init_models
from .platforms import register_all_finders
from .platforms.base import detect_platform, get_finder, CalendarPageError, UnsupportedPlatformError
from .platforms.headless_browser import warm_up as warm_up_headless_browser
from .platforms.media_probe import is_plausible_meeting_duration, probe_duration
from .platforms.models import ResolvedMeeting
from .platforms.youtube import YouTubeAssetFinder
from .utils.clerk_auth import clerk_frontend_api_url, get_clerk_user_id
from .utils.url_normalize import normalize_url

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
    try:
        # Launches (and, if needed, self-heals) the shared Chromium
        # instance Minneapolis LIMS/SLC's adapters use, once, at startup
        # -- so the real ~1-2s cold-launch cost (and a broken install)
        # land in deploy logs before any real visitor hits it, not on a
        # random future request. Same "log and keep serving" pattern as
        # init_models() above -- these two platforms failing to warm up
        # must never stop the other ~10 platforms from working.
        await warm_up_headless_browser()
    except Exception:
        logger.exception("Failed to warm up the headless browser at startup; continuing without it.")
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
# Deep-link JS shared with the Archive service (archive/main.py mounts the
# same top-level directory identically) -- see shared_static/deep_link.js's
# own header comment for why this exists.
app.mount("/shared-static", StaticFiles(directory=APP_DIR.parent / "shared_static"), name="shared_static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals["GA_MEASUREMENT_ID"] = os.environ.get("GA_MEASUREMENT_ID", "")
templates.env.globals["CLERK_PUBLISHABLE_KEY"] = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
templates.env.globals["CLERK_FRONTEND_API_URL"] = clerk_frontend_api_url(os.environ.get("CLERK_PUBLISHABLE_KEY", ""))


@app.exception_handler(StarletteHTTPException)
async def not_found_handler(request: Request, exc: StarletteHTTPException):
    # Only genuinely unmatched routes raise this -- every 404 this app
    # returns deliberately (API/internal endpoints) is a plain JSONResponse,
    # not a raised HTTPException, so this never intercepts those. A real
    # signal for broken inbound links (old bookmarks, stale references from
    # other sites) that was previously invisible.
    if exc.status_code == 404:
        logger.warning("404: %s (referer=%s)", request.url.path, request.headers.get("referer", ""))
        return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
    return await http_exception_handler(request, exc)

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


# Real bug found 2026-08-10: the BackgroundTasks push to the Archive can
# be silently lost if this process restarts (a deploy, a crash) between
# the response being sent and the task actually running -- zero log
# trace of the loss, since the process that would have logged it is the
# one that got killed. A push worth retrying gets a grace period first
# (ARCHIVE_PUSH_RETRY_AFTER_MINUTES) so the sweep doesn't race the normal
# fast path seconds after a response returns; the sweep itself only runs
# this often (ARCHIVE_PUSH_SWEEP_INTERVAL), a simple in-memory gate --
# fine for a single-instance free-tier deploy, same reasoning the rate
# limiter's own module comment already gives for in-memory state. See
# BACKLOG_DONE.md for the full incident this closes.
ARCHIVE_PUSH_RETRY_AFTER_MINUTES = 5
ARCHIVE_PUSH_SWEEP_INTERVAL = timedelta(minutes=5)
_last_push_sweep_at: Optional[datetime] = None


async def _push_and_track(resolution_id: int, payload: dict, normalized: str) -> None:
    """Wraps archive_client.push() with durable tracking
    (MeetingResolution.archive_pushed_at/archive_push_attempts in
    app/db) -- fired via BackgroundTasks so it never blocks a response,
    same as a bare archive_client.push() call did before this existed.
    On success, marks the row pushed so it's never treated as pending
    again; on failure, records the attempt so
    crud.get_pending_archive_pushes() can find and retry it later (via
    the sweep below or the admin endpoint)."""
    ok = await archive_client.push(payload, normalized)
    if ok:
        await safe(crud.mark_archive_pushed, resolution_id)
    else:
        await safe(crud.record_archive_push_failure, resolution_id)


async def _sweep_pending_archive_pushes() -> list[dict]:
    """Finds resolutions with real content that never got a confirmed
    Archive push and retries each one -- the actual fix for the silent-
    loss bug (the other half is _push_and_track() marking success/
    failure so this has something accurate to query). Returns what it
    found, for the admin endpoint below to report back synchronously;
    the passive opportunistic caller in /api/resolve ignores it."""
    pending = await safe(crud.get_pending_archive_pushes, min_age_minutes=ARCHIVE_PUSH_RETRY_AFTER_MINUTES)
    if not pending:
        return []
    for item in pending:
        await _push_and_track(item["resolution_id"], item["payload"], item["input_url_normalized"])
    return pending


def _maybe_schedule_push_sweep(background_tasks: BackgroundTasks) -> None:
    """Opportunistic, not a real scheduler -- this app deliberately has no
    background job queue (see CLAUDE.md), so the sweep only ever runs as
    a side effect of real traffic hitting /api/resolve, the same pattern
    ARCHIVE_RECHECK_AFTER's stale-page recheck already uses. The
    in-memory time gate (not persisted, resets on every restart) keeps a
    burst of concurrent requests from all triggering redundant sweeps at
    once -- good enough for a single-instance deploy, not a distributed-
    lock-grade guarantee."""
    global _last_push_sweep_at
    now = datetime.now(timezone.utc)
    if _last_push_sweep_at is not None and (now - _last_push_sweep_at) < ARCHIVE_PUSH_SWEEP_INTERVAL:
        return
    _last_push_sweep_at = now
    background_tasks.add_task(_sweep_pending_archive_pushes)


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

    pushed = bool(result.segments or result.agenda_items or result.agenda_link)
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

    # Opportunistic, cheap on every call (in-memory time gate) -- see
    # _maybe_schedule_push_sweep()'s own docstring for why this lives here
    # rather than a real scheduler.
    _maybe_schedule_push_sweep(background_tasks)

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
        # _push_and_track (not a bare archive_client.push) so this path gets
        # the same durable tracking/retry the fresh-resolve path below does
        # -- get_cached_resolution() returns resolution_id alongside the
        # payload specifically for this.
        cached_payload = cached["payload"]
        if cached_payload.get("segments") or cached_payload.get("agenda_items") or cached_payload.get("agenda_link"):
            background_tasks.add_task(_push_and_track, cached["resolution_id"], cached_payload, normalized)
        return cached_payload

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
    resolution_id = await safe(
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
    #
    # _push_and_track, not a bare archive_client.push -- real bug found
    # 2026-08-10: that fire-and-forget call could be silently lost if this
    # process restarted between the response returning and the task
    # actually running, with zero trace of the loss (see
    # BACKLOG_DONE.md). resolution_id can be None if the DB call above
    # itself failed (safe() swallows it) -- nothing to track against in
    # that case, so this falls back to the old best-effort behavior
    # rather than crashing on a None id.
    if result.segments or result.agenda_items or result.agenda_link:
        if resolution_id is not None:
            background_tasks.add_task(_push_and_track, resolution_id, payload, normalized)
        else:
            background_tasks.add_task(archive_client.push, payload, normalized)

    return payload


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NewsletterSignupRequest(BaseModel):
    email: str


async def _resend_audience_upsert(email: str, *, unsubscribed: bool) -> Optional[bool]:
    """Shared POST to Resend's audience-contacts endpoint (upserts by
    email) -- used for both newsletter signup (unsubscribed=False) and
    the /unsubscribe route below (unsubscribed=True), which is where the
    footer link every archive/utils/email.py send now includes actually
    lands (that module builds the link but has no Resend-write call of
    its own for it -- this is the only place the actual unsubscribe
    write happens). Returns True/False on a real response, None if
    Resend isn't configured at all (caller decides how to surface that).
    """
    api_key = os.environ.get("RESEND_API_KEY", "")
    audience_id = os.environ.get("RESEND_AUDIENCE_ID", "")
    if not api_key or not audience_id:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.resend.com/audiences/{audience_id}/contacts",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"email": email, "unsubscribed": unsubscribed},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status < 300:
                    return True
                logger.error("Resend audience upsert failed (%s): %s", response.status, await response.text())
                return False
    except Exception:
        logger.exception("Resend audience upsert request failed.")
        return False


# --- Lifecycle-triggered transactional sends (rtr-business's
# marketing/LIFECYCLE_EMAILS.md, approved copy/voice) -----------------
#
# A resolver-side counterpart to archive/utils/email.py's _send() --
# duplicated rather than called cross-service, same reasoning as
# get_clerk_user_id()/_resend_audience_upsert() already being duplicated
# here: these three emails (Thanks/Welcome/Goodbye) are triggered by
# routes that already live in this file (the Clerk webhook, newsletter
# signup, /unsubscribe), and a plain HTTPS call to Resend's own API needs
# no round trip through Archive. RESEND_FROM_ADDRESS/RESEND_REPLY_TO_ADDRESS
# are new env vars on this service specifically for this (previously only
# RESEND_API_KEY/RESEND_AUDIENCE_ID were needed here, for audience-upsert
# only) -- see render.yaml.


def _unsubscribe_footer_html(to: str) -> str:
    """Mirrors archive/utils/email.py's helper of the same name exactly --
    see that module's docstring for the deliverability reasoning. Returns
    "" (no footer) when PUBLIC_BASE_URL isn't set."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        return ""
    unsubscribe_url = f"{base}/unsubscribe?email={quote(to)}"
    return (
        f'<p style="margin-top:24px;font-size:12px;color:#999;">'
        f'<a href="{unsubscribe_url}" style="color:#999;">Unsubscribe</a> from future emails.</p>'
    )


def _branded_email_html(body_html: str) -> str:
    """Mirrors archive/utils/email.py's _branded_wrapper() exactly, same
    hand-inlined colors/font, so an email sent from this service looks
    identical to one sent from Archive/worker -- see that function's
    docstring for the full reasoning."""
    return f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fa;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border:1px solid #ddd;">
<tr><td style="background:#b71c1c;padding:14px 24px;">
<span style="font-family:'Courier New',monospace;font-weight:bold;letter-spacing:0.11em;font-size:15px;color:#ffffff;border:2px solid #a84b00;padding:4px 14px;display:inline-block;">RED TAPE RECORDINGS</span>
</td></tr>
<tr><td style="padding:28px 24px 8px;">
{body_html}
</td></tr>
</table>
</td></tr>
</table>
"""


def _email_signoff_html() -> str:
    return (
        '<p style="margin:24px 0 0;font-family:Georgia,\'Times New Roman\',serif;'
        'font-size:14px;color:#2c3e50;">Signing out,<br>Ryan<br>Red Tape Recordings</p>'
    )


async def _resend_send(to: str, subject: str, body_html: str, *, cc: str = "", skip_unsubscribe_footer: bool = False) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_address = os.environ.get("RESEND_FROM_ADDRESS", "")
    if not api_key or not from_address:
        logger.error("Transactional email send attempted but RESEND_API_KEY/RESEND_FROM_ADDRESS isn't configured.")
        return False

    if not skip_unsubscribe_footer:
        body_html = body_html + _unsubscribe_footer_html(to)

    payload = {"from": from_address, "to": [to], "subject": subject, "html": body_html}
    if cc:
        payload["cc"] = [cc]
    reply_to = os.environ.get("RESEND_REPLY_TO_ADDRESS", "")
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status < 300:
                    return True
                logger.error("Resend transactional send failed (%s): %s", response.status, await response.text())
                return False
    except Exception:
        logger.exception("Resend transactional send request failed.")
        return False


async def _send_account_created_email(to: str, *, first_name: Optional[str]) -> bool:
    """"Thanks" -- LIFECYCLE_EMAILS.md #1. Fires once, from the Clerk
    user.created webhook, instead of also sending "Welcome" -- account
    creation already auto-subscribes the address to the newsletter (see
    that webhook handler below), so sending both back to back would be
    two emails for one action. first_name comes straight from Clerk's
    webhook payload (data.get("first_name")) -- not yet live-verified
    that Clerk always populates it (e.g. an email-code signup with no
    OAuth profile might not); "Hi there," is the documented fallback.
    """
    greeting_name = html.escape(first_name) if first_name else "there"
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://redtaperecordings.com"
    body_html = f"""\
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:17px;color:#2c3e50;">Hi {greeting_name},</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">You're in.</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">Red Tape Recordings creates power tools for the most effective grassroots advocates &mdash; so important government decisions don't stay locked inside a five-hour video nobody has time to watch.</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">With your new account you can drop in the URL of a public meeting recording and get the video and a full transcript, side by side.</p>
<p style="margin:0 0 20px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">Click any line to jump to that moment. Grab a "deep link" that you can share with colleagues so they land at that exact second in the video.</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">
<tr><td style="background:#ffffff;border:2px solid #222;">
<a href="{base}/" style="display:inline-block;padding:10px 22px;font-family:'Courier New',monospace;font-weight:bold;font-size:15px;letter-spacing:0.5px;color:#222426;text-decoration:none;">Paste your first URL &rarr;</a>
</td></tr>
</table>
"""
    body_html += _email_signoff_html()
    return await _resend_send(to, "Congrats on the new library card :)", _branded_email_html(body_html))


async def _send_newsletter_welcome_email(to: str) -> bool:
    """"Welcome" -- LIFECYCLE_EMAILS.md #2, joining the free list via the
    standalone /subscribe form (never a name field, so always "Hi
    there,"). Includes an inline unsubscribe mention as part of the
    approved copy itself, on top of the standard footer link every send
    here gets -- deliberate per the doc's own voice, not an oversight.
    """
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://redtaperecordings.com"
    unsubscribe_url = f"{base}/unsubscribe?email={quote(to)}"
    body_html = f"""\
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:17px;color:#2c3e50;">Hi there,</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">Thank you so much for using Red Tape Recordings.</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">We really appreciate early adopters like you. Please let us know what should be improved.</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">We'll send you an email here and there when there are important updates or things we think are genuinely useful to the majority of the advocates, journalists, and other grassroots action-takers who use the tools.</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">Honestly, I used to write sales emails for a living and I sort of hate them. So I promise I will only write to you when I think it's really worth getting out of bed. And naturally, one click and you're out, anytime: <a href="{unsubscribe_url}" style="color:#3498db;">unsubscribe</a>.</p>
<p style="margin:0 0 20px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">But hopefully, you think the tools are cool and they save you a lot of time.</p>
"""
    body_html += _email_signoff_html()
    return await _resend_send(to, "You're on the list", _branded_email_html(body_html))


async def _send_unsubscribed_email(to: str) -> bool:
    """"Goodbye for now" -- LIFECYCLE_EMAILS.md #3. Deliberately skips the
    standard unsubscribe-footer link (skip_unsubscribe_footer=True): this
    email IS the unsubscribe confirmation, so a second "click here to
    unsubscribe" link right under it would read as a bug, not a courtesy.
    """
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or "https://redtaperecordings.com"
    body_html = f"""\
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:17px;color:#2c3e50;">Hi there,</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">Done. You're off the email list, and we won't send any more. A quiet inbox is a fair thing to want, and we're grateful for the time you gave us.</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">The tool is still yours whenever you need it. The record isn't going anywhere, and neither are we: <a href="{base}/" style="color:#3498db;">redtaperecordings.com</a></p>
<p style="margin:0 0 20px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">If you ever want back in, you're welcome anytime.</p>
"""
    body_html += _email_signoff_html()
    return await _resend_send(to, "Goodbye for now", _branded_email_html(body_html), skip_unsubscribe_footer=True)


@app.post("/api/newsletter/signup")
async def newsletter_signup(req: NewsletterSignupRequest):
    email = req.email.strip()
    if not _EMAIL_RE.match(email):
        return JSONResponse(
            {"error": "invalid_email", "message": "That doesn't look like a valid email address."},
            status_code=400,
        )

    ok = await _resend_audience_upsert(email, unsubscribed=False)
    if ok is None:
        logger.error("Newsletter signup attempted but RESEND_API_KEY/RESEND_AUDIENCE_ID isn't configured.")
        return JSONResponse(
            {"error": "signup_unavailable", "message": "Signups aren't available right now — please try again later."},
            status_code=503,
        )
    if ok:
        await _send_newsletter_welcome_email(email)
        return {"status": "subscribed"}

    return JSONResponse(
        {"error": "signup_failed", "message": "Something went wrong — please try again."},
        status_code=502,
    )


@app.get("/unsubscribe")
async def unsubscribe(request: Request, email: str = ""):
    """One-click unsubscribe link, no login/confirmation step (CAN-SPAM's
    requirement) -- appended to every email archive/utils/email.py sends
    as of 2026-08-10, per Resend's own deliverability guidance flagging a
    missing opt-out path as a real sender-reputation risk. GET, not POST,
    since this is meant to work from a plain email link click.
    """
    ok = False
    if email and _EMAIL_RE.match(email):
        result = await _resend_audience_upsert(email, unsubscribed=True)
        ok = bool(result)
        if ok:
            await _send_unsubscribed_email(email)
    return templates.TemplateResponse(request, "unsubscribed.html", {"unsubscribed": ok, "email": email})


@app.post("/api/clerk/webhook")
async def clerk_webhook(request: Request):
    """Clerk notifies us of account lifecycle events here -- the glue for
    three product decisions: account creation auto-subscribes to the
    newsletter and sends the "Thanks" welcome email (user.created,
    LIFECYCLE_EMAILS.md #1), and deleting a Clerk account purges the
    account's saved_items on our side (user.deleted, the right-to-deletion
    cascade -- see archive/db/crud.py's delete_account_data()).

    Verified via svix before trusting anything in the body -- an
    unverifiable payload gets a 400 and no side effects at all. Handlers
    are naturally idempotent (Resend upsert, a DELETE that's a no-op if
    already gone, an email send with no dedup but harmless to repeat), so
    a Svix retry on a non-2xx response is harmless to replay, no separate
    dedup needed.
    """
    signing_secret = os.environ.get("CLERK_WEBHOOK_SIGNING_SECRET", "")
    if not signing_secret:
        logger.error("Clerk webhook received but CLERK_WEBHOOK_SIGNING_SECRET isn't configured.")
        return JSONResponse({"error": "not_configured"}, status_code=503)

    body = await request.body()
    try:
        event = Webhook(signing_secret).verify(body, dict(request.headers))
    except Exception:
        logger.warning("Clerk webhook signature verification failed.")
        return JSONResponse({"error": "invalid_signature"}, status_code=400)

    event_type = event.get("type", "")
    data = event.get("data", {})

    if event_type == "user.created":
        primary_id = data.get("primary_email_address_id")
        email = next(
            (e.get("email_address") for e in data.get("email_addresses", []) if e.get("id") == primary_id),
            None,
        )
        if email:
            await _resend_audience_upsert(email, unsubscribed=False)
            await _send_account_created_email(email, first_name=data.get("first_name"))
        else:
            logger.warning("Clerk user.created webhook had no resolvable primary email for user %s.", data.get("id"))
    elif event_type == "user.deleted":
        clerk_user_id = data.get("id")
        if clerk_user_id:
            await archive_client.delete_account_data(clerk_user_id)

    return {"status": "ok"}


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


# Saved meetings/searches (accounts phase 1, Clerk-backed) ----------------
#
# A real 401, not the /internal/* 404-disguise convention -- these are
# genuinely public routes, so "you're not logged in" is honest information
# to return, not something worth hiding the route's existence over.
_NOT_LOGGED_IN = JSONResponse({"error": "not_logged_in", "message": "Sign in to save meetings and searches."}, status_code=401)


class SaveMeetingApiRequest(BaseModel):
    slug: str


@app.post("/api/account/save-meeting")
async def api_save_meeting(request: Request, req: SaveMeetingApiRequest):
    clerk_user_id = get_clerk_user_id(request)
    if clerk_user_id is None:
        return _NOT_LOGGED_IN
    result = await archive_client.save_meeting(clerk_user_id, req.slug)
    if result is None:
        return JSONResponse({"error": "not_found", "message": "No meeting with that slug."}, status_code=404)
    return result


@app.post("/api/account/unsave-meeting")
async def api_unsave_meeting(request: Request, req: SaveMeetingApiRequest):
    clerk_user_id = get_clerk_user_id(request)
    if clerk_user_id is None:
        return _NOT_LOGGED_IN
    result = await archive_client.unsave_meeting(clerk_user_id, req.slug)
    return result if result is not None else {"removed": False}


class SaveSearchApiRequest(BaseModel):
    search_params: dict


@app.post("/api/account/save-search")
async def api_save_search(request: Request, req: SaveSearchApiRequest):
    clerk_user_id = get_clerk_user_id(request)
    if clerk_user_id is None:
        return _NOT_LOGGED_IN
    result = await archive_client.save_search(clerk_user_id, req.search_params)
    if result is None:
        return JSONResponse(
            {"error": "save_failed", "message": "Something went wrong — please try again."}, status_code=502
        )
    return result


class UnsaveSearchApiRequest(BaseModel):
    saved_item_id: int


@app.post("/api/account/unsave-search")
async def api_unsave_search(request: Request, req: UnsaveSearchApiRequest):
    clerk_user_id = get_clerk_user_id(request)
    if clerk_user_id is None:
        return _NOT_LOGGED_IN
    result = await archive_client.unsave_search(clerk_user_id, req.saved_item_id)
    return result if result is not None else {"removed": False}


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


_YOUTUBE_UNREADABLE_MEDIA_MESSAGE = (
    "This meeting is hosted on YouTube, which doesn't make it easy for us to pull audio to "
    "transcribe here — but you can turn on captions and jump to specific timestamps directly in "
    "the YouTube player above."
)

# For a platform that delegates to YouTube behind its own branded page (LIMS,
# PrimeGov) -- same structural "can't read an iframe-embed page" cause as
# above, but deliberately doesn't name YouTube as the visited site (see the
# docstring below). Still tells the visitor exactly where the real video
# lives, real clickable link included -- confirmed with the user this reads
# as empowering rather than confusing, since the video player they're
# already looking at genuinely is that same YouTube embed.
_YOUTUBE_DELEGATED_UNREADABLE_MEDIA_MESSAGE_TEMPLATE = (
    "This meeting's video is hosted through a service we can't pull audio from to transcribe "
    "here — but you may still be able to turn on captions and jump to specific timestamps "
    "directly in the video player above. You can open it directly on YouTube for more options "
    "as well: {youtube_watch_url}"
)


def _unreadable_media_message(result: ResolvedMeeting, requested_platform: str) -> str:
    # video_url for a YouTube result is an iframe-embed page
    # (youtube.com/embed/{id}), never a real media file -- ffprobe can
    # never read it, a structural mismatch rather than "unavailable"
    # (see BACKLOG.md for the full trace, including why the real fix is
    # coupled to the separate, already-known YouTube IP-block issue).
    #
    # Deliberately NOT just `result.video_format == "youtube"` -- that's
    # also true for LIMS/PrimeGov, which delegate to YouTube behind a
    # *different* jurisdiction's own branded page (source_url stays
    # lims.minneapolismn.gov, never youtube.com). Telling that visitor
    # "hosted on YouTube" would be a confusing claim about a URL they
    # never saw. Only say it when the video is YouTube *and* either the
    # visitor's own URL was directly youtube.com/youtu.be, or this is a
    # generic_fallback result (best_effort) where the page itself has no
    # other branded identity and the video genuinely is youtube.com.
    if result.video_format == "youtube" and (requested_platform == "youtube" or result.best_effort):
        return _YOUTUBE_UNREADABLE_MEDIA_MESSAGE
    # The delegated case (LIMS/PrimeGov) previously fell all the way
    # through to the generic message below, which reads as "maybe
    # transient, try again" -- wrong for a permanent, structural
    # limitation. Real bug reported live 2026-08-10. video_id is always
    # extractable here since video_url is always the youtube.com/embed/{id}
    # shape this app itself builds (see youtube.py) whenever
    # video_format == "youtube".
    if result.video_format == "youtube":
        video_id = YouTubeAssetFinder.extract_video_id(result.video_url or "")
        if video_id:
            return _YOUTUBE_DELEGATED_UNREADABLE_MEDIA_MESSAGE_TEMPLATE.format(
                youtube_watch_url=f"https://www.youtube.com/watch?v={video_id}"
            )
    return "We found a media source but couldn't read it -- it may be unavailable."


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
        return {"ok": False, "message": _unreadable_media_message(result, platform)}
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
        clerk_verified=bool(get_clerk_user_id(request)),
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


async def _proxy_to_archive(internal_path: str, query_string: str, cookie_header: Optional[str] = None) -> Response:
    """Reverse-proxies a GET request to the Archive service so its permanent
    pages are reachable at redtaperecordings.com/m/{slug} instead of a
    separate subdomain -- keeps SEO authority on one domain. These are
    public, potentially-indexed pages, so a clean failure (503 + message)
    matters more here than for /api/resolve; never let a raw exception or a
    hang reach the browser.

    cookie_header is forwarded only by the few call sites that render
    auth-aware content (see archive_meeting_page/archive_meetings_index/
    account_saved below) -- passing it lets Archive verify the visitor's
    Clerk session itself with one local check, no separate internal HTTP
    round-trip needed (see app/utils/clerk_auth.py / archive/utils/clerk_auth.py).
    """
    try:
        session, response = await archive_client.proxy_get(internal_path, query_string, cookie_header)
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
    return await _proxy_to_archive(f"m/{path}", str(request.query_params), request.headers.get("cookie"))


@app.get("/archive-static/{path:path}")
async def archive_static_asset(path: str, request: Request):
    return await _proxy_to_archive(f"static/{path}", str(request.query_params))


@app.get("/meetings")
async def archive_meetings_index(request: Request):
    return await _proxy_to_archive("meetings", str(request.query_params), request.headers.get("cookie"))


@app.get("/account/saved")
async def account_saved(request: Request):
    return await _proxy_to_archive("account/saved", str(request.query_params), request.headers.get("cookie"))


@app.get("/coverage")
async def coverage(request: Request):
    return await _proxy_to_archive("coverage", str(request.query_params), request.headers.get("cookie"))


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


@app.get("/admin/daily-report")
async def admin_daily_report(token: str = "", dry_run: bool = False):
    """Triggers the once-a-day operator digest (app/reporting.py) on
    demand -- called by the GitHub Actions cron workflow
    (.github/workflows/daily-report.yml) once a day, and usable manually
    for testing (?dry_run=true composes but doesn't send). Deliberately
    an HTTP endpoint on this already-running service rather than a
    separate Render Cron Job service: Render Cron Jobs have no free tier
    (confirmed, minimum $1/mo), while this reuses infrastructure that's
    already paid for and already has direct DATABASE_URL/CLERK_SECRET_KEY/
    RESEND_API_KEY access -- see app/reporting.py's own docstring for what
    the report actually contains.
    """
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    to = os.environ.get("DAILY_REPORT_EMAIL_TO", "ryan@how-to-adu.com")
    try:
        result = await reporting.run_daily_report(to=to, dry_run=dry_run)
    except Exception:
        logger.exception("Daily report run failed unexpectedly.")
        return JSONResponse({"error": "daily_report_failed"}, status_code=500)

    if not dry_run and not result["sent"]:
        return JSONResponse({"error": "send_failed", "subject": result["subject"]}, status_code=502)
    return result


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


@app.get("/admin/sweep-pending-pushes")
async def admin_sweep_pending_pushes(token: str = ""):
    """On-demand version of the opportunistic push-retry sweep
    (_maybe_schedule_push_sweep, fired passively from /api/resolve) --
    for checking on or forcing the durable-push retry mechanism directly
    rather than waiting for real traffic to trigger it. Synchronous, not
    a BackgroundTask, so the caller sees exactly what was found and
    retried. See BACKLOG_DONE.md's silent-push-loss entry for why this
    mechanism exists at all."""
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    retried = await _sweep_pending_archive_pushes()
    return {
        "retried_count": len(retried),
        "retried": [
            {"resolution_id": item["resolution_id"], "url": item["input_url_normalized"], "attempts": item["attempts"]}
            for item in retried
        ],
    }


@app.get("/admin/promote-transcript-version")
async def admin_promote_transcript_version(token: str = "", url: str = "", version_id: Optional[int] = None):
    """Manually makes a specific TranscriptVersion a page's default --
    for the real gap found 2026-08-12 fixing a stale ALL-CAPS transcript
    (Minneapolis City Council): a manually-pushed replacement transcript
    has no automatic path to become the default once the page already
    has a with-segments-and-language default (see crud.py's
    manually_promote_transcript_version() and
    BACKLOG_DONE.md). Same url-lookup shape as
    /admin/correct-transcript-language above."""
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if not url or version_id is None:
        return JSONResponse(
            {"error": "missing_params", "message": "Pass ?url=<the meeting's source URL>&version_id=<id>."},
            status_code=400,
        )

    normalized = normalize_url(url)
    lookup_result = await archive_client.lookup(normalized)
    if lookup_result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No archived permanent page matches that URL."}, status_code=404
        )

    result = await archive_client.promote_transcript_version(lookup_result["slug"], version_id)
    if result is None:
        return JSONResponse({"error": "promotion_failed", "message": "Could not promote that version."}, status_code=502)
    return result


@app.get("/admin/correct-transcript-language")
async def admin_correct_transcript_language(token: str = "", url: str = "", language: str = "", version_id: Optional[int] = None):
    """Applies a "wrong_language" problem report's correction -- the
    "public report, admin fixes" flow decided 2026-08-09 (see
    BACKLOG_DONE.md). Takes the reported meeting's raw source URL (same
    shape as /admin/recheck-archive-page above) rather than an Archive
    slug directly, since that's all a ProblemReport row actually has --
    looks up the matching permanent page the same way a repeat paste
    would. Targets the page's current default transcript version unless a
    specific version_id is given."""
    if not _admin_token_ok(token):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if not url or not language:
        return JSONResponse(
            {"error": "missing_params", "message": "Pass ?url=<the meeting's source URL>&language=<ISO 639-1 code>."},
            status_code=400,
        )

    normalized = normalize_url(url)
    lookup_result = await archive_client.lookup(normalized)
    if lookup_result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No archived permanent page matches that URL."}, status_code=404
        )

    result = await archive_client.correct_transcript_language(lookup_result["slug"], language, version_id)
    if result is None:
        return JSONResponse({"error": "correction_failed", "message": "Could not apply the correction."}, status_code=502)
    return result
