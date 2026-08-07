import csv
import io
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .db import crud
from .db.engine import init_models
from .platforms.base import detect_platform, get_finder, register, CalendarPageError, UnsupportedPlatformError
from .platforms.granicus import GranicusAssetFinder
from .platforms.civicclerk import CivicClerkAssetFinder
from .platforms.swagit import SwagitAssetFinder
from .platforms.escribe import EscribeAssetFinder
from .platforms.ca_legislature import CaliforniaLegislatureAssetFinder
from .platforms.legistar import LegistarAssetFinder
from .platforms.civicplus import CivicPlusAssetFinder
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
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals["GA_MEASUREMENT_ID"] = os.environ.get("GA_MEASUREMENT_ID", "")

register(GranicusAssetFinder())
register(CivicClerkAssetFinder())
register(SwagitAssetFinder())
register(EscribeAssetFinder())
register(CaliforniaLegislatureAssetFinder())
register(LegistarAssetFinder())
register(CivicPlusAssetFinder())


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


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/resolve")
async def resolve(req: ResolveRequest):
    platform = detect_platform(req.url)
    normalized = normalize_url(req.url)

    cached = await safe(crud.get_cached_resolution, normalized)
    if cached:
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


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {})


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
