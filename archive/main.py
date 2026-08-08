import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .db import crud
from .db.engine import init_models
from .utils.transcript_export import to_srt, to_txt
from .utils.url_normalize import normalize_url

load_dotenv()

logger = logging.getLogger("rtr_archive")

APP_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_models()
    except Exception:
        logger.exception("Failed to initialize DB models at startup.")
    yield


app = FastAPI(title="rtr-archive", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
# Used only for <link rel="canonical">/OpenGraph tags -- the public domain
# these pages are actually reached at (via the resolver's /m/* proxy), not
# this service's own onrender.com URL. Empty locally, where there's no
# real public domain to canonicalize against.
templates.env.globals["public_base_url"] = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def _token_ok(authorization: Optional[str]) -> bool:
    expected = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    if not expected or not authorization or not authorization.startswith("Bearer "):
        return False
    return secrets.compare_digest(authorization[len("Bearer "):], expected)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/internal/lookup")
async def internal_lookup(normalized_url: str, authorization: Optional[str] = Header(None)):
    # 404, not 401/403 -- this is a private endpoint, its existence
    # shouldn't be distinguishable from a typo to anyone without the token
    # (same reasoning as the resolver's /admin/* routes).
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    result = await crud.lookup_page_for_url(normalized_url)
    if result is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return result


class TranscriptSegmentIn(BaseModel):
    start: float
    end: float
    text: str


class IngestRequest(BaseModel):
    platform: str
    source_url: str
    external_id: Optional[str] = None
    title: Optional[str] = None
    date: Optional[str] = None
    jurisdiction: Optional[str] = None
    video_url: Optional[str] = None
    video_format: Optional[str] = None
    segments: List[TranscriptSegmentIn] = []
    agenda_items: List[TranscriptSegmentIn] = []
    transcript_language: Optional[str] = None
    transcript_warnings: List[str] = []
    input_url_normalized: str


@app.post("/internal/ingest")
async def internal_ingest(req: IngestRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    payload = req.model_dump(exclude={"input_url_normalized"})
    result = await crud.ingest_resolution(payload, req.input_url_normalized)
    return result


def _pick_active_version(page: dict, version: Optional[int]) -> Optional[dict]:
    versions = page["versions"]
    if not versions:
        return None
    if version is not None:
        match = next((v for v in versions if v["id"] == version), None)
        if match is not None:
            return match
    return next((v for v in versions if v["is_default"]), versions[0])


@app.get("/m/{slug}")
async def meeting_page(request: Request, slug: str, version: Optional[int] = None):
    page = await crud.get_page_by_slug(slug)
    if page is None:
        return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)

    active_version = _pick_active_version(page, version)

    return templates.TemplateResponse(
        request,
        "meeting_page.html",
        {
            "page": page,
            "active_version": active_version,
            # The <html lang> attribute should reflect what's actually on
            # the page, not always English -- a transcript's real language
            # comes from its TranscriptVersion, not a sitewide constant.
            "page_lang": (active_version["language"] if active_version else None) or "en",
        },
    )


@app.get("/m/{slug}/transcript.{ext}")
async def meeting_transcript_export(slug: str, ext: str, version: Optional[int] = None):
    if ext not in ("txt", "srt"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    page = await crud.get_page_by_slug(slug)
    if page is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    active_version = _pick_active_version(page, version)
    if not active_version or not active_version["segments"]:
        return JSONResponse({"detail": "No transcript available for this meeting."}, status_code=404)

    body = to_srt(active_version["segments"]) if ext == "srt" else to_txt(active_version["segments"])
    filename = f"{slug}.{ext}"
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/meetings")
async def meetings_index(
    request: Request,
    page: int = 1,
    q: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    fuzzy: bool = False,
    has_agenda: Optional[bool] = None,
    has_transcript: Optional[bool] = None,
):
    result = await crud.list_pages(
        page=page,
        jurisdiction=jurisdiction,
        date_from=date_from,
        date_to=date_to,
        has_agenda=has_agenda,
        has_transcript=has_transcript,
        keyword=q,
        fuzzy=fuzzy,
    )
    return templates.TemplateResponse(
        request,
        "meeting_list.html",
        {
            **result,
            "q": q or "",
            "jurisdiction": jurisdiction or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "fuzzy": fuzzy,
            "has_agenda": has_agenda,
            "has_transcript": has_transcript,
        },
    )


@app.get("/sitemap.xml")
async def sitemap():
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    entries = await crud.list_all_page_slugs()
    body = templates.get_template("sitemap.xml.jinja").render(base_url=base, entries=entries)
    return Response(content=body, media_type="application/xml")


@app.get("/feed.xml")
async def feed(jurisdiction: Optional[str] = None):
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    entries = await crud.list_recent_pages_for_feed(jurisdiction=jurisdiction)
    # created_at is tz-aware on Postgres (prod) but SQLite (local dev)
    # doesn't enforce it -- assume UTC for a naive value so %z below
    # renders a real offset instead of silently coming back empty, same
    # workaround as app/main.py's _parse_updated_at for the same underlying
    # SQLite-vs-Postgres gap.
    for entry in entries:
        if entry["created_at"].tzinfo is None:
            entry["created_at"] = entry["created_at"].replace(tzinfo=timezone.utc)
    # Not str(request.url) -- this service is reached via the resolver's
    # /feed.xml proxy (see app/main.py), so the request it actually sees
    # carries its own internal host/port, not the public one. base_url
    # (from PUBLIC_BASE_URL) is the same fix already used for canonical/
    # OpenGraph URLs elsewhere in this app.
    feed_query = f"?jurisdiction={quote(jurisdiction)}" if jurisdiction else ""
    body = templates.get_template("feed.xml.jinja").render(
        base_url=base,
        feed_url=f"{base}/feed.xml{feed_query}",
        jurisdiction=jurisdiction,
        entries=entries,
    )
    return Response(content=body, media_type="application/rss+xml")
