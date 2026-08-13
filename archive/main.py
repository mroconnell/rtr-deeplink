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
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

load_dotenv()

from .db import crud
from .db.engine import init_models
from .utils import email as email_utils
from .utils.clerk_auth import clerk_frontend_api_url, get_clerk_user_id
from .utils.jurisdiction_format import format_jurisdiction_display
from .utils.language import language_display_name
from .utils.render_warnings import render_warnings_html
from .utils.transcript_export import to_srt, to_txt
from .utils.url_normalize import normalize_url

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
# Deep-link JS shared with the resolver service (app/main.py mounts the
# same top-level directory identically) -- see shared_static/deep_link.js's
# own header comment for why this exists.
app.mount("/shared-static", StaticFiles(directory=APP_DIR.parent / "shared_static"), name="shared_static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
# Used only for <link rel="canonical">/OpenGraph tags -- the public domain
# these pages are actually reached at (via the resolver's /m/* proxy), not
# this service's own onrender.com URL. Empty locally, where there's no
# real public domain to canonicalize against.
templates.env.globals["public_base_url"] = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
templates.env.globals["CLERK_PUBLISHABLE_KEY"] = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
templates.env.globals["CLERK_FRONTEND_API_URL"] = clerk_frontend_api_url(os.environ.get("CLERK_PUBLISHABLE_KEY", ""))
# Server-side equivalent of shared_static/deep_link.js's linkifyWarning()
# -- wraps render_warnings_html()'s already-escaped output in Markup so a
# template call site doesn't also need `|safe` (a forgotten `|safe`
# would otherwise silently re-escape real markup this filter already
# produced correctly).
templates.env.filters["warnings_html"] = lambda warnings: Markup(render_warnings_html(warnings or []))
templates.env.filters["language_name"] = language_display_name
# "scraped" is our internal TranscriptVersion.source value (see
# archive/db/models.py) -- never shown verbatim to a reader, who has no
# reason to know or care that it means "downloaded from the source site's
# own captions" versus AI-transcribed.
templates.env.filters["source_label"] = lambda source: "sourced" if source == "scraped" else source
templates.env.filters["jurisdiction_display"] = format_jurisdiction_display


@app.exception_handler(StarletteHTTPException)
async def not_found_handler(request: Request, exc: StarletteHTTPException):
    # Only genuinely unmatched routes raise this -- every 404 this app
    # returns deliberately (API/internal endpoints, and /m/{slug}'s own
    # explicit not_found.html render below) is a plain response, not a
    # raised HTTPException, so this never intercepts those. A real signal
    # for broken inbound links (old bookmarks, stale references from other
    # sites) that was previously invisible.
    if exc.status_code == 404:
        logger.warning("404: %s (referer=%s)", request.url.path, request.headers.get("referer", ""))
        return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
    return await http_exception_handler(request, exc)


def _parse_optional_bool(value: Optional[str]) -> Optional[bool]:
    """Tolerant tri-state parse for a query param that means "unset" (None,
    filter not applied) vs. explicitly true/false -- unlike fuzzy's plain
    `== "true"` (which only ever needs true/false, never "unset"), a missing
    has_agenda/has_transcript must stay None so crud.list_pages() doesn't
    filter on it at all. Treats "" the same as missing, not as False."""
    if not value:
        return None
    return value == "true"


def _token_ok(authorization: Optional[str]) -> bool:
    expected = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    if not expected or not authorization or not authorization.startswith("Bearer "):
        return False
    return secrets.compare_digest(authorization[len("Bearer "):], expected)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/internal/schema-info")
async def internal_schema_info(authorization: Optional[str] = Header(None)):
    """Read-only DB introspection, so confirming production's real schema
    state doesn't require someone with DATABASE_URL access to run psql/
    alembic commands and paste output back by hand -- see BACKLOG_DONE.md's
    2026-08-10 Alembic incident, where trusting a doc's stale account of
    "what production's state is" instead of checking it directly caused a
    real (contained) mistake.

    Compares actual reflected columns (via SQLAlchemy's Inspector against
    a live connection -- the real, current truth) against what
    `archive/db/models.py`'s `Base.metadata` currently expects. That
    comparison is the signal that actually matters here -- whether
    they match -- independent of whatever `alembic_version`'s own
    bookkeeping row claims, which is exactly the value that went stale
    and caused the incident above. `alembic_version` is still reported
    too (useful context), just not treated as ground truth on its own.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    from sqlalchemy import inspect as sa_inspect, text

    from .db.engine import engine
    from .db.models import Base

    async with engine.connect() as conn:
        actual_columns = await conn.run_sync(
            lambda sync_conn: {
                table_name: sorted(col["name"] for col in sa_inspect(sync_conn).get_columns(table_name))
                for table_name in sa_inspect(sync_conn).get_table_names()
            }
        )
        alembic_version = None
        if "alembic_version" in actual_columns:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            alembic_version = row[0] if row else None

    expected_columns = {
        table.name: sorted(col.name for col in table.columns) for table in Base.metadata.sorted_tables
    }
    mismatched_tables = [
        name for name, cols in expected_columns.items() if actual_columns.get(name) != cols
    ]

    return {
        "alembic_version": alembic_version,
        "expected_columns": expected_columns,
        "actual_columns": actual_columns,
        "mismatched_tables": mismatched_tables,
        "schema_matches_models": not mismatched_tables,
    }


@app.get("/internal/pages/all-urls")
async def internal_all_page_urls(authorization: Optional[str] = Header(None)):
    """Every archived page's real source URL + platform -- the backfill
    sweep's starting point (scripts/backfill_archived_pages.py). See
    crud.list_all_page_urls()'s own docstring for why this exists at all:
    nothing re-checks an already-archived page on its own, so an adapter/
    jurisdiction fix only ever reaches pages resolved *after* it shipped
    unless something re-resolves the old ones deliberately.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return {"pages": await crud.list_all_page_urls()}


@app.get("/internal/transcript-wanted")
async def internal_transcript_wanted(authorization: Optional[str] = Header(None)):
    """The "transcript wanted" queue: every archived YouTube-backed page
    with no default transcript. Consumed by
    scripts/fetch_youtube_transcripts.py, which fetches captions from a
    residential IP (this service's own cloud IP is confirmed blocked by
    YouTube -- see the crud function's docstring) and pushes them back
    through the normal /internal/ingest path.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return {"pages": await crud.list_youtube_pages_missing_transcripts()}


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
    # Unused today (see app/platforms/models.py's TranscriptSegment for
    # why it exists at all) -- declared here too so it round-trips through
    # ingest instead of Pydantic silently dropping an unrecognized field,
    # which would otherwise quietly break a future diarization pass that
    # assumes this value survives the resolver -> Archive boundary.
    speaker: Optional[str] = None


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
    # Mirrors ResolvedMeeting (app/platforms/models.py) -- previously
    # silently dropped by Pydantic on every ingest since MeetingPage had
    # no matching columns (fixed 2026-08-10, see BACKLOG_DONE.md).
    video_warnings: List[str] = []
    agenda_link: Optional[str] = None
    input_url_normalized: str


@app.post("/internal/ingest")
async def internal_ingest(req: IngestRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    payload = req.model_dump(exclude={"input_url_normalized"})
    result = await crud.ingest_resolution(payload, req.input_url_normalized)
    return result


class ResolvedMeetingIn(BaseModel):
    """Same shape as IngestRequest minus input_url_normalized (that's a
    sibling field on the request models below, not part of the resolved-
    meeting payload itself) -- kept separate rather than reused so this
    can evolve independently (e.g. dropping a field IngestRequest still
    needs) without a shared-model coupling."""

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


class TranscriptionCreateJobRequest(BaseModel):
    payload: ResolvedMeetingIn
    input_url_normalized: str
    requester_email: str
    media_url: str
    media_kind: str
    probed_duration_seconds: float
    chunk_size_seconds: int
    # Real server-side Clerk session check (get_clerk_user_id(request)
    # against the visitor's own cookie), done by the resolver -- the only
    # one of the two services with that cookie on this request path (see
    # tests/test_accounts_anonymous_regression.py's own docstring on
    # which routes the proxy forwards Cookie to). Trusted here the same
    # way every other resolver->Archive call already is: a bearer-token-
    # gated internal call, not a client-asserted flag. User request
    # 2026-08-11: a signed-in visitor's email is already Clerk-verified,
    # so it should skip the confirm-by-email step the same way an
    # existing newsletter subscriber's email already does below.
    clerk_verified: bool = False


@app.post("/internal/transcription/create-job")
async def internal_transcription_create_job(
    req: TranscriptionCreateJobRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    skip_confirmation = req.clerk_verified or await email_utils.check_audience_membership(req.requester_email)

    job = await crud.create_transcription_job(
        payload=req.payload.model_dump(),
        input_url_normalized=req.input_url_normalized,
        requester_email=req.requester_email,
        media_url=req.media_url,
        media_kind=req.media_kind,
        probed_duration_seconds=req.probed_duration_seconds,
        chunk_size_seconds=req.chunk_size_seconds,
        skip_confirmation=skip_confirmation,
    )

    if job.get("status") == "pending_confirmation":
        # The token itself lives server-side only (crud never returns it in
        # a job dict) -- fetched separately so it's never logged/returned
        # to the resolver, only ever emailed directly to the requester.
        token = await crud.get_confirmation_token(job["job_id"])
        base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
        confirm_url = f"{base}/confirm-transcription?token={token}"
        await email_utils.send_confirmation_email(req.requester_email, confirm_url)

    return job


class TranscriptionConfirmRequest(BaseModel):
    token: str


@app.post("/internal/transcription/confirm")
async def internal_transcription_confirm(req: TranscriptionConfirmRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    job = await crud.confirm_transcription_job(req.token)
    if job is None:
        return JSONResponse({"error": "invalid_or_used_token"}, status_code=404)

    # Confirming implicitly opts them into the audience -- every request
    # after their first is frictionless from here on, same as a newsletter
    # subscriber (see archive/utils/email.py's upsert_audience_contact).
    await email_utils.upsert_audience_contact(job["requester_email"])
    return job


@app.get("/internal/transcription/status/{job_id}")
async def internal_transcription_status(job_id: int, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    job = await crud.get_transcription_job_status(job_id)
    if job is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return job


class PromoteVersionRequest(BaseModel):
    slug: str
    version_id: int


@app.post("/internal/transcript-version/promote")
async def internal_promote_version(req: PromoteVersionRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    result = await crud.manually_promote_transcript_version(slug=req.slug, version_id=req.version_id)
    if result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No matching meeting page/version."}, status_code=404
        )
    return result


class CorrectLanguageRequest(BaseModel):
    slug: str
    language: str
    version_id: Optional[int] = None


@app.post("/internal/transcript-version/correct-language")
async def internal_correct_language(req: CorrectLanguageRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    result = await crud.correct_transcript_version_language(
        slug=req.slug, language=req.language, version_id=req.version_id
    )
    if result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No matching meeting page/version."}, status_code=404
        )
    return result


class SaveMeetingRequest(BaseModel):
    clerk_user_id: str
    slug: str


@app.post("/internal/account/save-meeting")
async def internal_save_meeting(req: SaveMeetingRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    item = await crud.save_meeting(req.clerk_user_id, req.slug)
    if item is None:
        return JSONResponse({"error": "not_found", "message": "No meeting with that slug."}, status_code=404)
    return item


@app.post("/internal/account/unsave-meeting")
async def internal_unsave_meeting(req: SaveMeetingRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    removed = await crud.unsave_meeting(req.clerk_user_id, req.slug)
    return {"removed": removed}


class SaveSearchRequest(BaseModel):
    clerk_user_id: str
    search_params: dict


@app.post("/internal/account/save-search")
async def internal_save_search(req: SaveSearchRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await crud.save_search(req.clerk_user_id, req.search_params)


class UnsaveItemRequest(BaseModel):
    clerk_user_id: str
    saved_item_id: int


@app.post("/internal/account/unsave-search")
async def internal_unsave_search(req: UnsaveItemRequest, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    removed = await crud.unsave_item(req.clerk_user_id, req.saved_item_id)
    return {"removed": removed}


@app.post("/internal/account/send-search-alerts")
async def internal_send_search_alerts(dry_run: bool = False, authorization: Optional[str] = Header(None)):
    """All the real work for the saved-search alert sweep happens here --
    direct DB access, direct Clerk/Resend credentials, no extra hop.
    GET /admin/send-search-alerts (app/main.py) is the public trigger
    (GitHub Actions cron), delegating here via app/archive_client.py --
    same /admin/* -> /internal/* split every other admin action already
    uses (e.g. /admin/promote-transcript-version).
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    from . import search_alerts

    return await search_alerts.run_search_alerts(dry_run=dry_run)


@app.get("/alerts/unsubscribe")
async def alerts_unsubscribe(request: Request, token: str = ""):
    """One-click unsubscribe from a single saved-search alert -- the
    email's "[unsubscribe from this alert]" link, distinct from the
    sitewide /unsubscribe (app/main.py). No login, no confirmation step,
    same CAN-SPAM-driven reasoning as that route: this needs to work from
    a plain email click. Authorized by a signed token
    (archive/utils/link_tokens.py) rather than clerk_user_id, since the
    click itself carries no session -- crud.unsave_item_by_id() trusts
    that the token was already verified here.
    """
    from .utils import link_tokens

    saved_item_id = link_tokens.verify_saved_item_token(token)
    removed = await crud.unsave_item_by_id(saved_item_id) if saved_item_id is not None else False
    return templates.TemplateResponse(request, "alert_unsubscribed.html", {"removed": removed})


@app.get("/internal/account/saved")
async def internal_list_saved_items(clerk_user_id: str, authorization: Optional[str] = Header(None)):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await crud.list_saved_items(clerk_user_id)


class DeleteAccountDataRequest(BaseModel):
    clerk_user_id: str


@app.post("/internal/account/delete-data")
async def internal_delete_account_data(req: DeleteAccountDataRequest, authorization: Optional[str] = Header(None)):
    """The right-to-deletion cascade, triggered by app/main.py's Clerk
    user.deleted webhook handler -- see crud.delete_account_data()'s own
    docstring for why this one call is the entire story on our side."""
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    count = await crud.delete_account_data(req.clerk_user_id)
    return {"deleted": count}


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
        logger.warning("404: /m/%s (referer=%s)", slug, request.headers.get("referer", ""))
        return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)

    active_version = _pick_active_version(page, version)
    active_account = get_clerk_user_id(request)
    # is_meeting_saved() only runs for a real verified session -- an
    # anonymous visitor never pays this extra query, matching the
    # "nothing existing gets gated, nothing extra costs anonymous
    # traffic" design note.
    meeting_saved = await crud.is_meeting_saved(active_account, page["id"]) if active_account else False

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
            # Truthy only for a real, verified Clerk session -- the cookie
            # is forwarded through the resolver's reverse proxy (see
            # app/archive_client.py's proxy_get()), so this is a single
            # local check, no internal HTTP round-trip. None for every
            # anonymous visitor; nothing else on this page is conditional
            # on it (see this feature's "nothing existing gets gated"
            # design note).
            "active_account": active_account,
            "meeting_saved": meeting_saved,
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
    if ext == "txt" and active_version["source"] == "transcribed":
        # Prepended, not injected into the .srt -- SRT is a strict cue
        # format meant for subtitle players, and a fake cue at 00:00
        # would visually overlay the video as if it were spoken dialogue,
        # competing with the real first line. Plain text has no such
        # constraint.
        body = (
            "[This transcript was generated automatically from audio using AI and hasn't "
            "been reviewed by a person -- it can contain mistakes, including "
            "plausible-sounding sentences that were never actually said. Treat it as a "
            "starting point, not a verbatim record.]\n\n"
        ) + body
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
    # Real bug fixed 2026-08-09: these three used to be bool/Optional[bool],
    # which FastAPI rejects with a 422 (bool_parsing) on an empty string --
    # not just missing, an explicit "?fuzzy=" (present, empty value). A
    # since-fixed template bug (meeting_list.html's pagination links) used
    # to generate exactly that shape, and existing bookmarked/shared links
    # built before that fix still have it -- accepting a plain string here
    # and parsing it tolerantly means those old links keep working instead
    # of 404ing/500ing forever.
    fuzzy: Optional[str] = None,
    has_agenda: Optional[str] = None,
    has_transcript: Optional[str] = None,
):
    fuzzy_bool = fuzzy == "true"
    has_agenda_bool = _parse_optional_bool(has_agenda)
    has_transcript_bool = _parse_optional_bool(has_transcript)
    result = await crud.list_pages(
        page=page,
        jurisdiction=jurisdiction,
        date_from=date_from,
        date_to=date_to,
        has_agenda=has_agenda_bool,
        has_transcript=has_transcript_bool,
        keyword=q,
        fuzzy=fuzzy_bool,
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
            "fuzzy": fuzzy_bool,
            "has_agenda": has_agenda_bool,
            "has_transcript": has_transcript_bool,
            "active_account": get_clerk_user_id(request),
        },
    )


@app.get("/account/saved")
async def account_saved(request: Request):
    clerk_user_id = get_clerk_user_id(request)
    items = await crud.list_saved_items(clerk_user_id) if clerk_user_id else None
    return templates.TemplateResponse(
        request,
        "saved_items.html",
        {"active_account": clerk_user_id, "items": items},
    )


@app.get("/coverage")
async def coverage(request: Request):
    coverage_rows = await crud.get_platform_coverage()
    jurisdictions = await crud.get_jurisdiction_coverage()
    return templates.TemplateResponse(
        request,
        "coverage.html",
        {"coverage": coverage_rows, "jurisdictions": jurisdictions, "active_account": get_clerk_user_id(request)},
    )



# Public, indexable static pages -- not MeetingPage rows, so they have no
# real lastmod and aren't produced by list_all_page_slugs(). Deliberately
# excludes /account/saved, /alerts/unsubscribe, /meeting (already
# robots.txt-disallowed as the ephemeral, unarchived resolver page), and
# every /admin/* route -- none of those are public content.
_SITEMAP_STATIC_PATHS = ["/", "/about", "/coverage", "/meetings"]


@app.get("/sitemap.xml")
async def sitemap():
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    entries = await crud.list_all_page_slugs()
    body = templates.get_template("sitemap.xml.jinja").render(
        base_url=base, entries=entries, static_paths=_SITEMAP_STATIC_PATHS
    )
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
