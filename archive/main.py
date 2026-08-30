import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

load_dotenv()


def _init_sentry() -> None:
    """No-op when SENTRY_DSN unset, same degrade pattern as Clerk/
    ARCHIVE_INGEST_TOKEN elsewhere in this codebase -- see app/main.py's
    matching _init_sentry() for the fuller reasoning (deliberately
    duplicated per service, same as clerk_auth.py/url_normalize.py)."""
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=0,
    )


_init_sentry()

from .db import crud
from .db.engine import init_models
from .topics import TOPICS
from .utils import email as email_utils
from .utils import social
from .utils.cache_static import RevalidatingStaticFiles
from .utils.clerk_auth import clerk_frontend_api_url, get_clerk_user_id
from .utils.date_status import (
    iso_meeting_date,
    meeting_date_html,
    meeting_date_status,
)
from .utils.highlights import meta_description
from .utils.jurisdiction_format import (
    STATE_SLUG_TO_ABBR,
    US_STATE_ABBR_TO_NAME,
    format_jurisdiction_display,
    jurisdiction_hub_slug,
    state_abbr_from_jurisdiction,
    state_slug_from_abbr,
)
from .utils.language import language_display_name
from .utils.render_warnings import render_warnings_html
from .utils.segment_time import format_segment_time
from .utils.transcript_export import to_srt, to_txt
from .utils import video_thumbnail
from .utils.clips import clip_entries
from .utils.video_thumbnail import youtube_thumbnail_url

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


@app.middleware("http")
async def handle_head_requests(request: Request, call_next):
    """Same fix as app/main.py's identically-named middleware (deliberate
    duplicate per this repo's own convention of not sharing code between
    the two services) -- every route here is declared with
    @app.get(...)/@app.post(...) etc, and FastAPI/Starlette does *not*
    automatically answer a bare HTTP HEAD for a GET route, so a HEAD
    (uptime checks, some crawlers, `curl -I`) 405s on all 19 routes with
    no handling at all. Dispatch a HEAD internally as a GET (rewriting
    `request.scope["method"]` before it reaches routing) and return the
    real response's status/headers with the body stripped -- per RFC 9110
    4.2, HEAD's response must carry the same headers a GET would
    (including Content-Length), just no body.

    Note: `call_next`'s returned object is always Starlette's internal
    `_StreamingResponse` wrapper, whose own `.background` is hardcoded to
    `None` -- any real background work a route attaches runs as part of
    the real handler's own response inside `call_next`'s concurrent
    dispatch, independent of the empty response built here, so there's
    nothing to carry over."""
    if request.method != "HEAD":
        return await call_next(request)
    request.scope["method"] = "GET"
    response = await call_next(request)
    return Response(
        content=b"",
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


app.mount(
    "/static", RevalidatingStaticFiles(directory=APP_DIR / "static"), name="static"
)
# Deep-link JS shared with the resolver service (app/main.py mounts the
# same top-level directory identically) -- see shared_static/deep_link.js's
# own header comment for why this exists.
app.mount(
    "/shared-static",
    RevalidatingStaticFiles(directory=APP_DIR.parent / "shared_static"),
    name="shared_static",
)
# Two roots: this service's own templates, then the repo-root
# shared_templates/ holding the partials both services render
# (topic chips + featured meeting cards -- the Archive's /state/ and
# /j/ pages and the resolver's home page, WO-50). Same "one copy,
# mounted by both" shape as shared_static/. Own templates first, so a
# service can always shadow a shared partial by name if it ever needs
# to diverge.
templates = Jinja2Templates(
    directory=[APP_DIR / "templates", APP_DIR.parent / "shared_templates"]
)
# Used only for <link rel="canonical">/OpenGraph tags -- the public domain
# these pages are actually reached at (via the resolver's /m/* proxy), not
# this service's own onrender.com URL. Empty locally, where there's no
# real public domain to canonicalize against.
templates.env.globals["public_base_url"] = os.environ.get("PUBLIC_BASE_URL", "").rstrip(
    "/"
)
templates.env.globals["CLERK_PUBLISHABLE_KEY"] = os.environ.get(
    "CLERK_PUBLISHABLE_KEY", ""
)
# WO-9 (2026-08-16): this service had no GA setup at all -- app/main.py's
# matching global existed, but a redirect from /meeting to a permanent
# /m/{slug} page landed on a template with no gtag snippet, so the visit
# (and any outreach UTM params riding along in the URL) went untracked
# the moment it arrived here, regardless of whether the params themselves
# survived the redirect. Same pattern as app/templates/base.html.
templates.env.globals["GA_MEASUREMENT_ID"] = os.environ.get("GA_MEASUREMENT_ID", "")
templates.env.globals["CLERK_FRONTEND_API_URL"] = clerk_frontend_api_url(
    os.environ.get("CLERK_PUBLISHABLE_KEY", "")
)
# Server-side equivalent of shared_static/deep_link.js's linkifyWarning()
# -- wraps render_warnings_html()'s already-escaped output in Markup so a
# template call site doesn't also need `|safe` (a forgotten `|safe`
# would otherwise silently re-escape real markup this filter already
# produced correctly).
templates.env.filters["warnings_html"] = lambda warnings: Markup(
    render_warnings_html(warnings or [])
)
templates.env.filters["language_name"] = language_display_name
# TranscriptVersion.source values are internal tokens -- never shown
# verbatim to a reader, who has no reason to know or care that "scraped"
# means "downloaded from the source site's own captions" versus
# AI-transcribed. Every value a reader can reach needs an entry here;
# anything unmapped falls through to its raw token, which is a bug, not a
# design (see BACKLOG.md's version-picker entry).
_SOURCE_LABELS = {
    "scraped": "sourced",
    # 2026-08-22: the same source captions with roll-up duplication
    # removed (scripts/dedupe_rollup_transcripts.py). Labeled distinctly
    # so the version picker can tell two same-language versions of the
    # same meeting apart -- "English (sourced)" vs.
    # "English (de-duplicated)" -- which language+source alone could not.
    "deduped": "de-duplicated",
}
templates.env.filters["source_label"] = lambda source: _SOURCE_LABELS.get(
    source, source
)
templates.env.filters["jurisdiction_display"] = format_jurisdiction_display
templates.env.filters["youtube_thumbnail_url"] = youtube_thumbnail_url
# schema.org Clip entries (start/end/text) out of stored agenda_items --
# see archive/utils/clips.py for the real Search Console endOffset
# warnings this resolves and why the look-ahead isn't done in the
# template.
templates.env.filters["clip_entries"] = clip_entries
# Real bug, confirmed live: meeting_page.html used to render agenda-item/
# transcript-segment timestamps with a naive "%d:%02d"|format(seconds //
# 60, seconds % 60), which has no hour rollover -- a segment at 21887s
# rendered as the literal "364:47" instead of "6:04:47". See
# archive/utils/segment_time.py's own docstring.
templates.env.filters["segment_time"] = format_segment_time
# Normalized "YYYY-MM-DD" (or None) for a MeetingPage.date -- gates both
# the `<time datetime="...">` markup on visible meeting dates and the
# JSON-LD uploadDate/startDate values, neither of which may ever emit an
# unvalidated free-string date. See iso_meeting_date's own docstring.
#
# Deliberately NOT applied to transcript/agenda offsets ("[12:34]"): those
# are durations, not datetimes -- HTML's <time datetime> would need
# "PT12M34S" for them, a different and much less obviously-valuable change.
# See CLAUDE_BACKLOG.md's SEO Tier 3 entry.
templates.env.filters["iso_date"] = iso_meeting_date


templates.env.filters["meeting_date_html"] = meeting_date_html


@app.exception_handler(StarletteHTTPException)
async def not_found_handler(request: Request, exc: StarletteHTTPException):
    # Only genuinely unmatched routes raise this -- every 404 this app
    # returns deliberately (API/internal endpoints, and /m/{slug}'s own
    # explicit not_found.html render below) is a plain response, not a
    # raised HTTPException, so this never intercepts those. A real signal
    # for broken inbound links (old bookmarks, stale references from other
    # sites) that was previously invisible.
    if exc.status_code == 404:
        logger.warning(
            "404: %s (referer=%s)", request.url.path, request.headers.get("referer", "")
        )
        return templates.TemplateResponse(
            request, "not_found.html", {}, status_code=404
        )
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


def _parse_id_filter(raw: Optional[str]) -> Optional[Set[int]]:
    """Comma-separated `meeting_page_id`s -> a set, for POST /internal/
    jurisdiction/backfill-apply's only_ids/exclude_ids. None (param absent)
    stays None, meaning "no filter at all" -- distinct from an empty set,
    which for only_ids legitimately means "no row is allowed through".

    Raises ValueError on any non-integer token rather than skipping it: a
    silently-dropped id in `exclude_ids` would fail OPEN (writing a row the
    operator explicitly asked to hold back) on an endpoint whose whole
    reason for existing is that part of the candidate set is known-wrong.
    """
    if raw is None:
        return None
    return {int(part.strip()) for part in raw.split(",") if part.strip()}


def _token_ok(authorization: Optional[str]) -> bool:
    expected = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    if not expected or not authorization or not authorization.startswith("Bearer "):
        return False
    return secrets.compare_digest(authorization[len("Bearer ") :], expected)


@app.get("/api/health")
async def health():
    """Render gates deploys on this endpoint (render.yaml), so it has to be
    able to actually fail. During the 2026-08-09 incident the app was
    failing every query on a missing column and this would still have
    reported "ok" -- a health check that can't fail isn't one. The count
    query (rather than just SELECT 1) also catches a real table missing
    or misnamed, which a bare connection check wouldn't."""
    from sqlalchemy import func, select

    from .db.engine import engine
    from .db.models import MeetingPage

    try:
        async with engine.connect() as conn:
            await conn.execute(select(func.count()).select_from(MeetingPage))
    except Exception:
        logger.exception("Health check failed: database unreachable.")
        return JSONResponse(
            {"status": "error", "reason": "database unreachable"}, status_code=503
        )
    return {"status": "ok", "media_tools": await _media_tools()}


# Probed once per process and cached: the answer cannot change while the
# service is running, and /api/health is Render's deploy gate -- polled
# often enough that spawning two subprocesses per call would be a real,
# pointless cost.
_media_tools_cache: Optional[dict] = None


async def _media_tools() -> dict:
    """Reports whether ffmpeg/ffprobe are actually on PATH *in this
    service*, alongside the health check that was already here.

    This settled a real unknown rather than documenting a known one
    (2026-08-21, WO-28). Before the meeting-card frames, the Archive was
    a plain `runtime: python` service that shelled out to no binary at
    all -- render.yaml records a confirmed-live ffprobe check on the
    *resolver* and worker/Dockerfile installs ffmpeg explicitly, but
    nothing confirmed either binary here. Card extraction runs
    Archive-side (that's where the page, the DB and the route live), so
    the answer is load-bearing, and one `curl $ARCHIVE_BASE_URL/api/health`
    now answers it against the deployed service instead of requiring a
    Render shell.

    Deliberately informational: a missing binary must NOT fail this
    endpoint. Render gates deploys on it, and a service that serves every
    page perfectly and merely cannot generate new thumbnails is healthy.
    Pages degrade to no og:image (see meeting_page.html), which is exactly
    where they were before this feature.
    """
    global _media_tools_cache
    if _media_tools_cache is None:
        from app.platforms.media_probe import binary_versions

        try:
            _media_tools_cache = await binary_versions()
        except Exception:
            logger.exception("ffmpeg/ffprobe availability probe failed")
            _media_tools_cache = {"ffmpeg": None, "ffprobe": None}
    return _media_tools_cache


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
                table_name: sorted(
                    col["name"] for col in sa_inspect(sync_conn).get_columns(table_name)
                )
                for table_name in sa_inspect(sync_conn).get_table_names()
            }
        )
        alembic_version = None
        if "alembic_version" in actual_columns:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            alembic_version = row[0] if row else None

    expected_columns = {
        table.name: sorted(col.name for col in table.columns)
        for table in Base.metadata.sorted_tables
    }
    mismatched_tables = [
        name
        for name, cols in expected_columns.items()
        if actual_columns.get(name) != cols
    ]

    return {
        "alembic_version": alembic_version,
        "expected_columns": expected_columns,
        "actual_columns": actual_columns,
        "mismatched_tables": mismatched_tables,
        "schema_matches_models": not mismatched_tables,
    }


@app.get("/internal/db-size")
async def internal_db_size(authorization: Optional[str] = Header(None)):
    """Read-only storage report for the Postgres server this service is on,
    so "how close is rtr-deeplink-db to its storage limit?" is answerable
    without a Render dashboard login.

    Built for the same reason /internal/schema-info above was, and it's
    the same lesson: a 2026-08-24 Render alert said the database was over
    90% of its storage limit, and nothing in this repo could size that
    against anything. render.yaml's own plan comment (`basic-1gb`) is
    entirely a RAM/shared_buffers argument and says nothing about the
    storage allotment, so the only number anyone had was the alert's own
    "more than 90%". When a doc asserts a fact about production that
    nothing in the repo can verify, build the read that answers it.

    Overlaps deliberately with scripts/analyze_db_storage.py (WO-60),
    which answered the same 2026-08-24 alert from the Render shell and
    found the real cause (meeting_page_thumbnails). Two differences keep
    both worth having: that script reads
    pg_database_size(current_database()), i.e. rtr_archive alone, and it
    needs shell access. This route needs neither.

    Reports *every* database on the server, not just this one: the alert
    is about the server's storage, and this single instance hosts both
    rtr_archive (this service's) and rtr_deeplink_db (the resolver's) --
    a suspension takes down both. That works cross-database because
    pg_database_size() is a catalog read, not a query against the other
    database's contents.

    Also reports the largest relations in the *current* database, so the
    follow-up question -- what actually grew -- is answerable from the
    same call rather than needing a second trip. Raw byte counts sit
    alongside the pretty strings so a later comparison is arithmetic, not
    string parsing.

    Read-only and side-effect free. Never writes, never vacuums.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    from sqlalchemy import text

    from .db.engine import engine

    # Same dialect guard as crud.py's Postgres-only helpers -- the local
    # and test path is SQLite, which has none of these functions. Reported
    # rather than raised, so hitting this locally says why instead of 500ing.
    if engine.dialect.name != "postgresql":
        return {
            "dialect": engine.dialect.name,
            "supported": False,
            "detail": "Storage sizes are Postgres-only; this service is not on Postgres.",
        }

    async with engine.connect() as conn:
        databases = [
            {
                "name": row[0],
                "bytes": int(row[1]),
                "pretty": row[2],
            }
            for row in (
                await conn.execute(
                    text(
                        "SELECT datname, pg_database_size(datname), "
                        "pg_size_pretty(pg_database_size(datname)) "
                        "FROM pg_database WHERE datistemplate = false "
                        "ORDER BY pg_database_size(datname) DESC"
                    )
                )
            ).all()
        ]
        # pg_total_relation_size includes indexes and TOAST, which is the
        # number that matters here -- the transcript JSON this service
        # stores is overwhelmingly TOASTed, so a table-only size would
        # understate the biggest consumer by design.
        largest_relations = [
            {
                "relation": f"{row[0]}.{row[1]}",
                "bytes": int(row[2]),
                "pretty": row[3],
            }
            for row in (
                await conn.execute(
                    text(
                        "SELECT schemaname, relname, "
                        "pg_total_relation_size(relid), "
                        "pg_size_pretty(pg_total_relation_size(relid)) "
                        "FROM pg_catalog.pg_statio_user_tables "
                        "ORDER BY pg_total_relation_size(relid) DESC LIMIT 15"
                    )
                )
            ).all()
        ]
        current_database = (
            await conn.execute(text("SELECT current_database()"))
        ).scalar()

    return {
        "dialect": "postgresql",
        "supported": True,
        "current_database": current_database,
        "server_total_bytes": sum(db["bytes"] for db in databases),
        "databases": databases,
        "largest_relations_in_current_database": largest_relations,
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


# The home-page payload, cached in-process. This is the busiest page on
# the domain and its content changes only when a new meeting is ingested,
# so recomputing the national pool per request (or per crawler hit) buys
# nothing. The resolver caches it again on its side; this second layer
# exists because several resolver instances share one Archive, and
# because a cold resolver cache must not turn into a corpus query.
_HOME_CACHE: dict[str, tuple[float, dict]] = {}
_HOME_CACHE_TTL_SECONDS = 300.0


@app.get("/internal/home-highlights")
async def internal_home_highlights(
    topic: str = "", authorization: Optional[str] = Header(None)
):
    """Topic chips + the national recent-moments feed + the browse-by-
    state list, for the resolver's home page (WO-50).

    Lives here rather than the resolver reading the shared Postgres
    directly: every piece of this (meeting_highlights, archive/topics.py,
    _build_featured()) is the Archive's, and having app/ import Archive
    models would make an Archive migration able to break the resolver.
    The resolver already treats this service as optional everywhere else,
    and app/archive_client.py's home_highlights() keeps that posture --
    it returns None on any failure and the home page simply renders
    without the section.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    key = topic or ""
    hit = _HOME_CACHE.get(key)
    now = time.monotonic()
    if hit and (now - hit[0]) < _HOME_CACHE_TTL_SECONDS:
        return hit[1]

    data = await crud.get_home_highlights(topic or None)
    _HOME_CACHE[key] = (now, data)
    return data


@app.get("/internal/topic-candidates")
async def internal_topic_candidates(
    days: int = 90,
    limit: int = 40,
    phrase: str = "",
    authorization: Optional[str] = Header(None),
):
    """Candidate subjects for `archive/topics.py`, out of what people
    actually searched for (WO-51).

    Curation stays human -- this ranks and previews, it never adds a
    topic. Two modes: without `phrase`, the ranked list of searched
    phrases the curated set does not already cover, each with its
    zero-result rate; with `?phrase=...`, what adding that phrase would
    surface (a corpus count plus a few real meetings).

    Deliberately internal and read-only. The reader-facing version of
    this idea -- a "suggest a topic" form -- was considered and rejected:
    `search_queries` already collects the same signal passively, at far
    higher volume, and records what people looked for rather than what
    they say they want. See STATE_HUB_PAGES.md section 9.

    **Expect thin results for a while.** `search_queries` only started
    filling 2026-08-23, so an empty list means "no data yet", not
    "nothing worth adding".
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if phrase:
        return await crud.topic_candidate_preview(phrase)
    return {
        "window_days": days,
        "candidates": await crud.topic_candidates(days=days, limit=limit),
    }


@app.get("/internal/transcript-wanted")
async def internal_transcript_wanted(authorization: Optional[str] = Header(None)):
    """The "transcript wanted" queue: every archived YouTube-backed page
    with no *good* default transcript -- missing entirely, or present but
    flagged bad (garbled/no real content), see
    list_youtube_pages_missing_transcripts()'s own docstring (WO-15,
    BACKLOG.md). Consumed by scripts/fetch_youtube_transcripts.py, which
    fetches captions from a residential IP (this service's own cloud IP is
    confirmed blocked by YouTube -- see the crud function's docstring) and
    pushes them back through the normal /internal/ingest path.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return {"pages": await crud.list_youtube_pages_missing_transcripts()}


@app.get("/internal/transcription-backlog")
async def internal_transcription_backlog(
    limit: Optional[int] = None, authorization: Optional[str] = Header(None)
):
    """Batch counterpart to /internal/transcript-wanted above -- every
    archived page across ANY platform missing a good transcript,
    oldest-archived-first, skipping pages already in escalating-failure
    cooldown (see crud._in_auto_transcription_cooldown()). Consumed by
    scripts/transcribe_backlog_locally.py, run on a local Mac with a
    bigger faster-whisper model than the Render-2GB-constrained worker's
    "tiny" default -- see that script's own module docstring.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return {"pages": await crud.list_transcription_backlog_candidates(limit=limit)}


async def _tier3_queue_remaining() -> int:
    """The tier-3 discovery queue's remaining depth, as of the last real
    feed run -- sourced from the database (crud.read_tier3_queue_remaining(),
    see Tier3QueueState's own docstring for why), not by reading
    scripts/tier3_auto_transcription_queue.txt off disk. This used to be
    a plain line count of that tracked file, which meant it was the sole
    reason the file had to sit in this service's render.yaml build-filter
    allow-list, and its freshness silently depended on deploy cadence
    rather than on when the queue actually last changed. Returns 0 if no
    feed run has ever reported a count yet -- this is one line of an ops
    report, not something that should 500 the whole route.
    """
    remaining = await crud.read_tier3_queue_remaining()
    return remaining if remaining is not None else 0


@app.post("/internal/tier3-queue-remaining")
async def internal_tier3_queue_remaining(
    remaining: int, authorization: Optional[str] = Header(None)
):
    """Written by scripts/feed_tier3_auto_transcription.py right after it
    rewrites the queue file, so _tier3_queue_remaining() above can read a
    real, current count from the database instead of needing the file
    itself present in this service's deploy tree. `remaining` is a query
    param (matches this service's other simple internal-token routes,
    e.g. /admin/recheck-archive-page's `url=`) rather than a JSON body --
    the caller has exactly one integer to send.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    await crud.set_tier3_queue_remaining(remaining)
    return {"ok": True, "remaining": remaining}


@app.get("/internal/transcription-queue-stats")
async def internal_transcription_queue_stats(
    authorization: Optional[str] = Header(None),
):
    """Real-time snapshot of transcription workload -- see
    crud.get_transcription_queue_summary()'s own docstring for exactly
    what each field means and how it's computed. Read-only, side-effect
    free (unlike /internal/send-worker-daily-report below, which advances
    the report snapshot) -- safe to call as often as wanted, e.g. for a
    future dashboard, not just the daily report.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    summary = await crud.get_transcription_queue_summary()
    summary["tier3_queue_remaining"] = await _tier3_queue_remaining()
    return summary


@app.get("/internal/transcription-failure-analysis")
async def internal_transcription_failure_analysis(
    days: Optional[int] = None, authorization: Optional[str] = Header(None)
):
    """Groups every recorded chunk failure by media host, page host and
    position-within-job, so the recurring "workers keep hitting `ffmpeg
    timed out after 120s`" question gets answered from real stored data
    instead of from a plausible-sounding theory.

    No new instrumentation was needed for this: TranscriptionJob.
    failure_history has recorded a real per-attempt `chunk_index` since
    2026-08-19, which is what makes the two conflated failure modes
    separable -- see crud.get_transcription_failure_analysis()'s own
    docstring and the block comment above it for exactly what each
    grouping discriminates, and why media host (a shared Granicus CDN)
    is the grouping that matters rather than page host (~300 distinct
    per-tenant subdomains that are really one party).

    Read-only and side-effect free, like /internal/transcription-queue-
    stats above. `?days=N` restricts to recent failures; omitted is
    all-time.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return await crud.get_transcription_failure_analysis(days=days)


@app.get("/internal/send-worker-daily-report")
async def internal_send_worker_daily_report(
    to: str, authorization: Optional[str] = Header(None)
):
    """Composes and sends the transcription-worker daily activity report
    (email_utils.send_worker_daily_report()), then advances the stored
    snapshot (crud.advance_worker_report_snapshot(), only when the send
    actually succeeded -- WO-52) so the NEXT
    send's 24h delta is measured from this moment, not from whenever the
    snapshot was last touched. Triggered by .github/workflows/
    worker-daily-report.yml -- same "GitHub Actions just pings an
    already-running Render service that already holds the real Resend
    credentials" pattern /admin/send-search-alerts (app/main.py) already
    established, not a new script with its own copy of RESEND_API_KEY.

    `to` is a required query param rather than a fixed env var -- keeps
    this route reusable (a different recipient without touching Render
    config) the same way /admin/recheck-archive-page?url= takes its
    target as a param instead of hardcoding one.

    GET despite the real side effect (advancing the snapshot, sending an
    email) -- same precedent as /admin/send-search-alerts and
    /admin/recheck-archive-page, both of which are also side-effecting
    GETs on this codebase's existing token-gated internal/admin surface,
    not a REST purity violation introduced here.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # This route returns 200 whether or not the send succeeded (see the
    # return below), so a caller that passes no recipient otherwise gets
    # no signal at all -- which is exactly why the GitHub Actions run
    # behind Sentry PYTHON-FASTAPI-11 showed green while Resend was
    # rejecting the request. `to: str` alone doesn't catch it: FastAPI
    # accepts `?to=` as a perfectly valid empty string.
    if not to.strip():
        return JSONResponse(
            {"detail": "`to` is required and cannot be empty."}, status_code=400
        )

    summary = await crud.get_transcription_queue_summary()
    summary["tier3_queue_remaining"] = await _tier3_queue_remaining()

    previous = await crud.read_worker_report_snapshot()

    sent = await email_utils.send_worker_daily_report(
        to,
        summary=summary,
        previous=previous,
        # Explicitly passed (never omitted) so a clean day renders a real
        # "none" line rather than silently dropping the section -- see
        # send_worker_daily_report()'s own note on the None/[] distinction.
        failures=await crud.list_recent_transcription_failures(hours=24),
    )
    # Advance ONLY on a real send (WO-52). Advancing first meant a failed
    # send silently consumed the day's reference point and the next report
    # read zero -- see advance_worker_report_snapshot()'s docstring for the
    # live 2026-08-23 occurrence.
    if sent:
        await crud.advance_worker_report_snapshot(
            cumulative_chunks_completed=summary["cumulative_chunks_completed_all_time"],
            cumulative_jobs_completed=summary["cumulative_jobs_completed_all_time"],
        )
    return {"sent": sent, "summary": summary}


@app.get("/internal/transcription/completed-multichunk")
async def internal_transcription_completed_multichunk(
    authorization: Optional[str] = Header(None),
):
    """Read-only audit list: every completed TranscriptionJob with
    total_chunks > 1 -- real candidates for the seam-duplication bug fixed
    2026-08-16 (see worker/segment_utils.py's "Seam-duplication dedup"
    note and BACKLOG_DONE.md) having already shipped to a live public page
    before the fix existed. Added specifically to answer that audit
    without needing direct DATABASE_URL access (same reasoning as
    /internal/schema-info -- see its own docstring). Never re-transcribes
    or modifies anything itself.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return {"jobs": await crud.list_completed_multichunk_transcription_jobs()}


@app.get("/internal/transcription/hallucination-candidates")
async def internal_transcription_hallucination_candidates(
    limit: int = 500,
    after_id: Optional[int] = None,
    authorization: Optional[str] = Header(None),
):
    """Read-only audit list: every already-completed source=="transcribed"
    TranscriptVersion whose *stored* segments trip
    detect_hallucination_warnings() (archive/utils/transcription_quality.py)
    when re-run today -- real candidates for the stereo phase-cancellation
    hallucination bug fixed 2026-08-16 (see
    worker/segment_utils.py's "Hallucinated-transcription detection" note
    and BACKLOG_DONE.md) having already shipped to a live public page
    before either the extraction-side fix or this detection check existed.
    Same reasoning and structure as
    GET /internal/transcription/completed-multichunk right above (that
    audit's own template for this one) -- answers the audit without
    needing direct DATABASE_URL access. Never re-transcribes or modifies
    anything itself; a human decides what's worth re-running.

    Rewritten 2026-08-21 -- this endpoint was confirmed live-502ing
    (see BACKLOG_DONE.md) because crud.list_hallucination_candidate_
    transcript_versions() pulled every source=="transcribed" row's full
    segments JSON in one unbounded query. It now only pulls segments for
    rows already carrying the hallucination marker (a small, trusted set)
    plus up to `limit` not-yet-flagged rows (default 500) -- pass
    `after_id` (the previous batch's max version_id) to page through the
    rest, same keyset-pagination shape as other batch audit endpoints in
    this file.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return {
        "candidates": await crud.list_hallucination_candidate_transcript_versions(
            limit=limit, after_id=after_id
        )
    }


@app.get("/internal/transcript-quality-audit")
async def internal_transcript_quality_audit(
    list_outcomes: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Read-only aggregate: every archived page's transcript-quality outcome
    bucket (success / garbled_transcript / non_english_transcript /
    blank_transcript / agenda_fallback / no_video -- same buckets as
    /coverage's per-jurisdiction outcome column and app/db/outcomes.py's
    classify_outcome()), counted across the whole archive rather than one
    best example per jurisdiction. Added to answer "how many archived
    meetings have a low-quality/garbled/non-English transcript" without
    needing direct DATABASE_URL access (same reasoning as
    /internal/schema-info). Never re-transcribes or modifies anything.

    `list_outcomes` (comma-separated bucket names, e.g.
    "garbled_transcript,non_english_transcript") also returns the real
    slug/source URL/platform/language/warnings for every page in those
    buckets -- e.g. to target the real garbled pages directly with
    scripts/transcribe_backlog_locally.py --url, or to eyeball whether any
    non_english_transcript page is actually a garbled scraped caption
    whose language got misdetected (the confirmed Fountain Valley, CA
    pattern -- see CLAUDE.md).
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    outcomes = (
        {o.strip() for o in list_outcomes.split(",") if o.strip()}
        if list_outcomes
        else None
    )
    return await crud.get_transcript_quality_audit(list_outcomes=outcomes)


@app.get("/internal/thin-page-audit")
async def internal_thin_page_audit(
    slugs: Optional[str] = None, authorization: Optional[str] = Header(None)
):
    """Read-only: which archived pages hold nothing a reader can use.

    Ships alongside WO-62's Soft 404 fix so the size of that change is
    measured rather than assumed -- the fix stops counting a bare
    `agenda_link` as content, and this says how many live pages that
    de-indexes and on which platforms. Same reasoning as
    /internal/schema-info and /internal/db-size: answer it from production
    instead of from an estimate.

    `?slugs=a,b,c` restricts to named pages, so a specific Search Console
    URL gets a straight answer rather than being inferred from a bucket
    total -- e.g.
    `?slugs=fairview-tn-2025-10-02-regular-meeting`, the page Google
    actually flagged.

    See crud.get_thin_page_audit() for the buckets and why `platform`
    rides along on every thin row. Never modifies anything.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    wanted = {s.strip() for s in slugs.split(",") if s.strip()} if slugs else None
    return await crud.get_thin_page_audit(slugs=wanted)


@app.get("/internal/date-format-audit")
async def internal_date_format_audit(
    limit: int = 200,
    authorization: Optional[str] = Header(None),
):
    """Read-only: every archived page's `date` bucketed by shape (null /
    iso_date / parseable_non_iso / unparseable), plus the real slug and
    stored value for anything that isn't a clean "YYYY-MM-DD".

    Exists to settle, in one call, BACKLOG.md's long-open Search Console
    question -- whether the `uploadDate` "invalid datetime value" flag is
    caused by a real malformed row from a bad adapter extraction, or was
    only ever the (since-fixed) missing-timezone problem in the same
    JSON-LD block. Same reasoning and structure as
    GET /internal/transcript-quality-audit above: answers a "how big is
    this really" question without needing direct DATABASE_URL access.
    Never writes anything.

    Run it as:

        curl -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" \\
             "$ARCHIVE_BASE_URL/internal/date-format-audit"

    Reading the result: `by_shape.unparseable > 0` means real malformed
    rows exist and the flag has a live cause worth chasing to the adapter
    that wrote them. All-zero for both non-ISO buckets means no stored
    value can be producing it, and the flag should clear on recrawl now
    that the template validates before emitting (see meeting_page.html's
    uploadDate comment).
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return await crud.get_meeting_date_format_audit(limit=max(1, min(limit, 2000)))


@app.get("/internal/jurisdiction/bleed-backfill-candidates")
async def internal_jurisdiction_bleed_backfill_candidates(
    authorization: Optional[str] = Header(None),
):
    """Read-only audit list: every already-archived MeetingPage whose
    stored `jurisdiction` would come out differently (a different string,
    or a better confidence tier) if re-run through today's
    finalize_jurisdiction() (app/utils/jurisdiction_enrich.py) -- real
    candidates for the 2026-08-17 Canadian-data + Title-Case-bleed fixes
    (BACKLOG.md's "Jurisdiction-bleed, confirmed cross-platform" entry)
    having already shipped to a live public page before either fix
    existed. Same reasoning and structure as
    GET /internal/transcription/hallucination-candidates above (that
    audit's own template for this one) -- answers "how big would a
    backfill be" without needing direct DATABASE_URL access. Never
    re-writes anything itself; a human decides what's worth backfilling.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return await crud.list_jurisdiction_bleed_backfill_candidates()


@app.get("/internal/low-trust-pages")
async def internal_low_trust_pages(
    limit: int = 200,
    offset: int = 0,
    unreviewed: bool = False,
    reason: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Read-only review queue: every archived page whose provenance was
    never actually verified -- `platform == "unknown"` (generic_fallback's
    own registered name), `best_effort` (the same fallback path, including
    the YouTube-delegated results whose platform reads "youtube" instead --
    the most common real case, which is why a platform-only check isn't
    enough), or a `jurisdiction_confidence` of "unverified"/"blank".

    Exists because the resolve -> Archive -> public page -> social
    announcement pipeline is fully automatic end to end, with nothing
    that could ever answer "what has this thing published that nobody
    verified?" Same read-only, size-the-problem role as
    GET /internal/jurisdiction/bleed-backfill-candidates above (this
    route's own template), and it never modifies anything -- a human
    decides what, if anything, to do with each row.

    Deliberately does NOT change what the public site shows. The noindex
    condition in meeting_page.html, the sitemap filter
    (crud.list_all_page_slugs()) and the /j/* hub filter
    (crud._hub_base_conditions()) were all left exactly as they were, by
    explicit product decision -- see BACKLOG.md's entry. Most best_effort
    pages are legitimate small cities that happened to resolve via the
    fallback, and pulling them out of Google would cost real reach for no
    proportionate trust gain.

    **What's really in here, measured 2026-08-21 (WO-38).** The first
    production call returned 474 rows: 470 `unverified_jurisdiction`, 7
    `unknown_platform`, 0 `best_effort`. So in practice this is a
    *data-quality* queue -- meetings whose jurisdiction couldn't be
    determined -- and a trust queue only prospectively; see
    crud.list_low_trust_pages()'s docstring for why, and don't come to
    this expecting spoofed content.

    `?unreviewed=true` (WO-38) hides rows already stamped via
    POST /internal/low-trust-pages/mark-reviewed below -- without it, 474
    rows have to be re-triaged from scratch on every read.
    `?reason=unknown_platform|best_effort|unverified_jurisdiction`
    narrows to one reason, which matters given the skew above: the 4 rows
    that aren't `unverified_jurisdiction` are otherwise invisible. Both
    are optional and an unfiltered call returns exactly what it always
    did.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    try:
        return await crud.list_low_trust_pages(
            limit=limit, offset=offset, unreviewed=unreviewed, reason=reason
        )
    except ValueError:
        return JSONResponse(
            {"detail": "reason must be one of " + ", ".join(crud._LOW_TRUST_REASONS)},
            status_code=400,
        )


@app.post("/internal/low-trust-pages/mark-reviewed")
async def internal_low_trust_pages_mark_reviewed(
    ids: Optional[str] = None,
    dry_run: bool = True,
    unreview: bool = False,
    authorization: Optional[str] = Header(None),
):
    """Write counterpart to GET /internal/low-trust-pages above: records
    that a human has actually looked at specific pages, so the queue
    shrinks as it's worked instead of re-presenting all 474 rows forever
    (WO-38). Stamps `meeting_pages.reviewed_at` and nothing else -- it
    does not hide, de-index, edit or delete anything, and a reviewed page
    is served to the public exactly as before.

    `ids` is REQUIRED, comma-separated `meeting_page_id`s (the same ids
    the GET above returns), same parse as
    /internal/jurisdiction/backfill-apply's only_ids. There is
    deliberately no "mark everything" mode: on the backfill endpoint the
    ids narrow a candidate set the server recomputed itself, so omitting
    them safely means "all candidates" -- here, omitting them would mean
    declaring 474 unexamined pages reviewed in one keystroke and
    permanently destroying the distinction this column exists to record.

    Idempotent: an id already in the requested state comes back under
    `already_reviewed` with its original timestamp untouched, and an id
    matching no row comes back under `missing_ids` instead of failing the
    whole batch. `dry_run` defaults to true (this repo's read-only-first
    convention, see /internal/schema-info); pass `?dry_run=false` to
    commit. `?unreview=true` clears the stamp back to NULL -- the undo
    for a mis-pasted id list, which otherwise would need direct database
    access to repair.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    try:
        parsed = _parse_id_filter(ids)
    except ValueError:
        return JSONResponse(
            {"detail": "ids must be comma-separated integers"}, status_code=400
        )

    try:
        result = await crud.mark_low_trust_pages_reviewed(
            ids=parsed or set(), dry_run=dry_run, unreview=unreview
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    if not result["reviewed_at_column_available"]:
        # The one-deploy window where this build is live but its
        # migration hasn't run. The read endpoint degrades honestly; a
        # write can't, so say so loudly rather than reporting a success
        # that recorded nothing.
        return JSONResponse(
            {
                "detail": "meeting_pages.reviewed_at does not exist yet; "
                "run the Alembic migration and retry",
                **result,
            },
            status_code=503,
        )
    return result


@app.post("/internal/jurisdiction/backfill-apply")
async def internal_jurisdiction_backfill_apply(
    dry_run: bool = True,
    only_ids: Optional[str] = None,
    exclude_ids: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Write counterpart to GET /internal/jurisdiction/bleed-backfill-
    candidates above -- actually backfills the 2026-08-17 Canadian-data +
    Title-Case-bleed fixes (PRs #158/#161) onto MeetingPage rows archived
    before either fix existed. Always recomputes candidates itself from
    each row's own stored inputs (crud.apply_jurisdiction_bleed_backfill())
    -- never trusts a client-supplied jurisdiction string, so a stale or
    forged request can't write arbitrary text. Only patches the
    `jurisdiction` and `jurisdiction_confidence` columns; every other field
    on the row (title, video_url, segments, ...) is untouched. Narrower
    than the GET audit above: only rows where the jurisdiction STRING
    actually changes are touched -- a confidence-tier-only diff (e.g. null
    -> "validated" with the same text) isn't worth a write and is skipped.

    dry_run defaults to true (mirrors this repo's read-only-first pattern
    for internal tooling, see /internal/schema-info's docstring) and
    returns the exact before/after diff it *would* write without touching
    the database. Pass ?dry_run=false to actually commit.

    `only_ids` / `exclude_ids` (comma-separated `meeting_page_id`s, the
    same ids the GET audit above returns) apply a SUBSET of the candidate
    set -- added 2026-08-21 (WO-22) because the real production candidate
    set turned out not to be uniformly safe: a handful of rows were
    confidently-wrong repairs while the large majority were plain, safe
    state-suffix appends, and without a filter the only choices were all
    or nothing (see BACKLOG.md's "Bare/state-suffixed jurisdiction
    duplicates" entry). Ids are only ever a filter over rows this endpoint
    recomputed itself -- an unknown or unchanged id simply matches
    nothing, and no caller-supplied jurisdiction text is accepted here any
    more than before. `exclude_ids` wins if an id appears in both.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    try:
        only = _parse_id_filter(only_ids)
        exclude = _parse_id_filter(exclude_ids)
    except ValueError:
        return JSONResponse(
            {"detail": "only_ids/exclude_ids must be comma-separated integers"},
            status_code=400,
        )

    return await crud.apply_jurisdiction_bleed_backfill(
        dry_run=dry_run, only_ids=only, exclude_ids=exclude
    )


@app.post("/internal/pages/clear-future-dates")
async def internal_pages_clear_future_dates(
    dry_run: bool = True,
    grace_days: int = 7,
    only_ids: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Null out `date` on pages whose stored date lies more than
    `grace_days` in the future -- the repair half of the Granicus
    body-text future-date bug (see crud.clear_future_meeting_dates()'s
    docstring for the three confirmed production rows and why a
    re-ingest can't fix them: the refresh path's date update is
    truthy-gated on purpose). Same posture as
    /internal/jurisdiction/backfill-apply above: recompute-only (the
    only possible write is date -> NULL on a row the recompute itself
    flagged; no caller-supplied date is ever accepted), dry_run defaults
    true, `only_ids` narrows which flagged rows may be written.
    Near-future dates inside the grace window are reported but never
    touched -- a genuinely-scheduled upcoming meeting's agenda page is
    real (confirmed live: Sarasota County OnBase, Aug 25 meeting
    resolved Aug 23).
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    try:
        only = _parse_id_filter(only_ids)
    except ValueError:
        return JSONResponse(
            {"detail": "only_ids must be comma-separated integers"},
            status_code=400,
        )

    return await crud.clear_future_meeting_dates(
        dry_run=dry_run, grace_days=grace_days, only_ids=only
    )


@app.get("/internal/lookup")
async def internal_lookup(
    normalized_url: str, authorization: Optional[str] = Header(None)
):
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
    # Mirrors ResolvedMeeting.meeting_body (app/platforms/models.py,
    # 2026-08-23) -- an adapter-supplied governing body ("City Council",
    # "Board of Supervisors"). Without this field here it would be
    # silently dropped at the boundary, the exact failure shape
    # video_warnings/agenda_link/best_effort below each document.
    # crud._find_or_create_page() prefers it over the split-from-
    # jurisdiction fallback and never lets a payload that omits it clear
    # a stored value.
    meeting_body: Optional[str] = None
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
    # Also mirrors ResolvedMeeting -- and was also silently dropped by
    # Pydantic on every single ingest until 2026-08-21 (WO-21), the exact
    # same failure shape as video_warnings/agenda_link above. The
    # resolver has always *sent* it (app/main.py pushes
    # `result.model_dump()`, and best_effort is a real field on
    # ResolvedMeeting); this model just had no matching field, so it
    # never survived the boundary and `grep -rn best_effort archive/`
    # found nothing at all.
    #
    # This one is a trust signal, not a display detail: it marks a
    # resolve that came out of generic_fallback.py's scan-any-page path
    # instead of a real vendor adapter. Two things read it now --
    # crud.ingest_resolution() persists it to MeetingPage.best_effort for
    # GET /internal/low-trust-pages, and social.payload_is_high_quality()
    # refuses to publicly announce a page carrying it. Note the second
    # one works off this parsed model's dump and therefore needs *only*
    # this field, not the column: the social gate is safe even against a
    # database where the migration hasn't run.
    #
    # Defaults False, so every partial pusher that omits it
    # (scripts/fetch_youtube_transcripts.py and friends) is unaffected --
    # and crud only ever lets this SET the flag, never clear one, for
    # exactly that reason (see _find_or_create_page()).
    best_effort: bool = False
    input_url_normalized: str
    # Archive-only -- not part of ResolvedMeeting (app/platforms/models.py),
    # so every normal resolver push/bulk_ingest.py/fetch_youtube_transcripts.py
    # call simply omits it and gets the "scraped" default crud.
    # ingest_resolution() already applied before this field existed.
    # scripts/transcribe_backlog_locally.py is the one real caller that
    # sets this to "transcribed" -- see that function's own docstring for
    # why mislabeling self-transcribed content as "scraped" would be a
    # real problem (losing the AI-transcript disclaimer), not a cosmetic
    # one.
    source: Optional[str] = None


@app.post("/internal/ingest")
async def internal_ingest(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    payload = req.model_dump(exclude={"input_url_normalized"})
    result = await crud.ingest_resolution(payload, req.input_url_normalized)
    # Social auto-announce -- only a freshly *created* page can trigger it
    # (re-ingests/backfills never can, see _find_or_create_page()'s
    # docstring); the quality gate, env-based enablement, and per-network
    # dedup all live inside announce_new_page() itself. BackgroundTasks so
    # a slow/down social API can never delay the resolver's push.
    if result.get("created"):
        background_tasks.add_task(
            social.announce_new_page, result["page_id"], result["slug"], payload
        )
    # Warm the page's default card frame (WO-28). BackgroundTasks for the
    # same reason as the social post above, only more so: this runs
    # ffprobe and then ffmpeg against a government CDN, where a slow or
    # rate-limited source is routine -- it can never be allowed to delay
    # the resolver's push. Fired on re-ingest too, not just creation:
    # extract_and_store() no-ops when the frame already exists, and a
    # re-ingest is exactly when a page that previously had no video (or a
    # broken one) may finally have gained a usable one.
    _schedule_card_warm(
        background_tasks,
        page_id=result["page_id"],
        video_url=payload.get("video_url"),
        video_format=payload.get("video_format"),
        source_url=payload.get("source_url") or req.input_url_normalized,
    )
    return result


def _schedule_card_warm(
    background_tasks: BackgroundTasks,
    *,
    page_id: Optional[int],
    video_url: Optional[str],
    video_format: Optional[str],
    source_url: Optional[str],
    timestamp: Optional[int] = None,
) -> None:
    """Queue one best-effort card-frame extraction, or do nothing.

    One helper rather than the same four-line guard at each of the three
    call sites (ingest, /m/{slug}, the card route), so "is there anything
    ffmpeg could even open here" can't drift between them -- and so the
    template render path's version of this is provably a queue-and-return,
    never a subprocess.

    extract_and_store()'s FrameOutcome (WO-42) is discarded here by
    construction: a BackgroundTask has no caller left to return it to,
    and the failure reason is already logged Archive-side. It is the
    backfill sweep below -- the one caller that awaits the result -- that
    the outcome exists for.
    """
    if not page_id or not video_thumbnail.is_extractable(video_url, video_format):
        return
    background_tasks.add_task(
        video_thumbnail.extract_and_store,
        page_id=page_id,
        video_url=video_url,
        source_page_url=source_url or video_url,
        timestamp=timestamp,
    )


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
    # Same mirror as IngestRequest.meeting_body above, for the same
    # boundary-drop reason -- this payload also reaches
    # crud._find_or_create_page() (via create_transcription_job()).
    meeting_body: Optional[str] = None
    video_url: Optional[str] = None
    video_format: Optional[str] = None
    segments: List[TranscriptSegmentIn] = []
    agenda_items: List[TranscriptSegmentIn] = []
    transcript_language: Optional[str] = None
    transcript_warnings: List[str] = []
    # Added alongside IngestRequest.best_effort (2026-08-21, WO-21) rather
    # than left to diverge: this payload also reaches
    # crud._find_or_create_page() (via create_transcription_job()), and
    # that call can genuinely *create* a MeetingPage -- a "Request
    # Transcript from Audio" on a fallback-resolved URL nobody had
    # archived yet. Without the field here, exactly those pages -- the
    # ones with no vendor adapter behind them at all -- would be the ones
    # created unflagged.
    best_effort: bool = False


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
    # Optional -- omitted (the default) preserves every existing caller's
    # behavior exactly, since crud.create_transcription_job() itself
    # defaults to PRIORITY_MEDIUM when no priority= kwarg is passed. Added
    # 2026-08-21 so scripts/bulk_queue_transcription_backlog.py can
    # explicitly submit at PRIORITY_LOW over this HTTP surface --
    # previously only worker/main.py's own in-process auto-generation
    # call could ever use that tier (see crud.PRIORITY_LOW's own
    # "reserved for future self-generated/idle-time batch work" comment --
    # this is exactly that future use). Restricted to the two tiers that
    # actually exist today so this internal, token-gated route can't be
    # used to sneak a job in above PRIORITY_MEDIUM.
    priority: Optional[int] = None

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in (crud.PRIORITY_LOW, crud.PRIORITY_MEDIUM):
            raise ValueError(
                f"priority must be {crud.PRIORITY_LOW} or {crud.PRIORITY_MEDIUM}"
            )
        return v


@app.post("/internal/transcription/create-job")
async def internal_transcription_create_job(
    req: TranscriptionCreateJobRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    skip_confirmation = (
        req.clerk_verified
        or await email_utils.check_audience_membership(req.requester_email)
    )

    job = await crud.create_transcription_job(
        payload=req.payload.model_dump(),
        input_url_normalized=req.input_url_normalized,
        requester_email=req.requester_email,
        media_url=req.media_url,
        media_kind=req.media_kind,
        probed_duration_seconds=req.probed_duration_seconds,
        chunk_size_seconds=req.chunk_size_seconds,
        skip_confirmation=skip_confirmation,
        **({"priority": req.priority} if req.priority is not None else {}),
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
async def internal_transcription_confirm(
    req: TranscriptionConfirmRequest, authorization: Optional[str] = Header(None)
):
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
async def internal_transcription_status(
    job_id: int, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    job = await crud.get_transcription_job_status(job_id)
    if job is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return job


class PromoteVersionRequest(BaseModel):
    slug: str
    version_id: int
    # Opt-in only -- a caller re-pushing content it fetched independently
    # (e.g. scripts/fetch_youtube_transcripts.py re-fetching via a
    # different library than the original resolve) can assert that this
    # promotion should also clear any stale garbled/hallucination warning
    # already on the version, since dedup-by-content-hash in
    # ingest_resolution() reuses the existing version row -- and its old
    # warnings -- rather than creating a fresh one. Left False by default
    # so scripts/transcribe_backlog_locally.py's own opt-in --promote for
    # human-reviewed Whisper re-transcriptions is unaffected: a human
    # promoting a version doesn't mean its hallucination flag was wrong.
    clear_warnings: bool = False


@app.post("/internal/transcript-version/promote")
async def internal_promote_version(
    req: PromoteVersionRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    result = await crud.manually_promote_transcript_version(
        slug=req.slug,
        version_id=req.version_id,
        clear_warnings=req.clear_warnings,
    )
    if result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No matching meeting page/version."},
            status_code=404,
        )
    return result


class RepairSeamDuplicationRequest(BaseModel):
    slug: str
    # sha256 of the raw /m/{slug}/transcript.srt body the caller scanned
    # for seam duplication -- optimistic concurrency, see
    # crud.create_seam_repair_version()'s own docstring for why this must
    # be a hard refusal on mismatch, not a warning, and why it's hashed
    # against to_srt() output rather than TranscriptVersion.content_hash.
    expected_srt_hash: str
    drop_segment_indices: List[int]


@app.post("/internal/transcript-version/repair-seam-duplication")
async def internal_repair_seam_duplication(
    req: RepairSeamDuplicationRequest, authorization: Optional[str] = Header(None)
):
    """Backs scripts/repair_seam_duplication.py --apply -- see
    crud.create_seam_repair_version()'s own docstring for the full
    reasoning. Dry-run needs no route at all (the script reads the
    public transcript.srt export directly); this is only ever called
    for a confirmed finding a human has already had the chance to see.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    result = await crud.create_seam_repair_version(
        slug=req.slug,
        expected_srt_hash=req.expected_srt_hash,
        drop_segment_indices=req.drop_segment_indices,
    )
    if result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No matching meeting page/version."},
            status_code=404,
        )
    if result.get("error") == "stale":
        return JSONResponse(result, status_code=409)
    if result.get("error") == "empty_result":
        return JSONResponse(result, status_code=400)
    return result


class CorrectLanguageRequest(BaseModel):
    slug: str
    language: str
    version_id: Optional[int] = None


@app.post("/internal/transcript-version/correct-language")
async def internal_correct_language(
    req: CorrectLanguageRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    result = await crud.correct_transcript_version_language(
        slug=req.slug, language=req.language, version_id=req.version_id
    )
    if result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No matching meeting page/version."},
            status_code=404,
        )
    return result


class CorrectWarningsRequest(BaseModel):
    slug: str
    transcript_warnings: list[str]
    version_id: Optional[int] = None


@app.post("/internal/transcript-version/correct-warnings")
async def internal_correct_warnings(
    req: CorrectWarningsRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    result = await crud.correct_transcript_version_warnings(
        slug=req.slug, warnings=req.transcript_warnings, version_id=req.version_id
    )
    if result is None:
        return JSONResponse(
            {"error": "not_found", "message": "No matching meeting page/version."},
            status_code=404,
        )
    return result


class SaveMeetingRequest(BaseModel):
    clerk_user_id: str
    slug: str


@app.post("/internal/account/save-meeting")
async def internal_save_meeting(
    req: SaveMeetingRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    item = await crud.save_meeting(req.clerk_user_id, req.slug)
    if item is None:
        return JSONResponse(
            {"error": "not_found", "message": "No meeting with that slug."},
            status_code=404,
        )
    return item


@app.post("/internal/account/unsave-meeting")
async def internal_unsave_meeting(
    req: SaveMeetingRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    removed = await crud.unsave_meeting(req.clerk_user_id, req.slug)
    return {"removed": removed}


class SaveSearchRequest(BaseModel):
    clerk_user_id: str
    search_params: dict


@app.post("/internal/account/save-search")
async def internal_save_search(
    req: SaveSearchRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await crud.save_search(req.clerk_user_id, req.search_params)


class UnsaveItemRequest(BaseModel):
    clerk_user_id: str
    saved_item_id: int


@app.post("/internal/account/unsave-search")
async def internal_unsave_search(
    req: UnsaveItemRequest, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    removed = await crud.unsave_item(req.clerk_user_id, req.saved_item_id)
    return {"removed": removed}


@app.post("/internal/account/send-search-alerts")
async def internal_send_search_alerts(
    dry_run: bool = False, authorization: Optional[str] = Header(None)
):
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
    removed = (
        await crud.unsave_item_by_id(saved_item_id)
        if saved_item_id is not None
        else False
    )
    return templates.TemplateResponse(
        request, "alert_unsubscribed.html", {"removed": removed}
    )


@app.get("/internal/account/saved")
async def internal_list_saved_items(
    clerk_user_id: str, authorization: Optional[str] = Header(None)
):
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await crud.list_saved_items(clerk_user_id)


class DeleteAccountDataRequest(BaseModel):
    clerk_user_id: str


@app.post("/internal/account/delete-data")
async def internal_delete_account_data(
    req: DeleteAccountDataRequest, authorization: Optional[str] = Header(None)
):
    """The right-to-deletion cascade, triggered by app/main.py's Clerk
    user.deleted webhook handler -- see crud.delete_account_data()'s own
    docstring for why this one call is the entire story on our side."""
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    count = await crud.delete_account_data(req.clerk_user_id)
    return {"deleted": count}


class DeletePagesRequest(BaseModel):
    slugs: list[str]


@app.post("/internal/admin/delete-pages")
async def internal_delete_pages(
    req: DeletePagesRequest,
    dry_run: bool = True,
    authorization: Optional[str] = Header(None),
):
    """Permanently removes MeetingPage rows by slug -- see
    crud.delete_meeting_pages_by_slug()'s own docstring for the cascade
    detail and why this exists (a real 2026-08-19 cleanup: 3 PrimeGov
    UAT/staging tenant pages accidentally real-ingested during a bulk
    gate-blindness recheck, not a general content-moderation tool). Slug
    only, never a fuzzy match, so a typo can't take out an unrelated real
    page. dry_run defaults true, matching this file's existing read-only-
    first convention (see /internal/jurisdiction/backfill-apply)."""
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await crud.delete_meeting_pages_by_slug(req.slugs, dry_run=dry_run)


class ReslugPageRequest(BaseModel):
    slug: str


@app.post("/internal/admin/reslug-page")
async def internal_reslug_page(
    req: ReslugPageRequest,
    dry_run: bool = True,
    authorization: Optional[str] = Header(None),
):
    """One-off, by-hand slug correction -- see crud.reslug_page()'s own
    docstring for the full reasoning. After a real (non-dry-run) call,
    add the returned old_slug -> new_slug mapping to `_SLUG_REDIRECTS`
    below in the same change and deploy, so the old permalink 301s
    instead of 404ing."""
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await crud.reslug_page(req.slug, dry_run=dry_run)


def _pick_active_version(page: dict, version: Optional[int]) -> Optional[dict]:
    versions = page["versions"]
    if not versions:
        return None
    if version is not None:
        match = next((v for v in versions if v["id"] == version), None)
        if match is not None:
            return match
    return next((v for v in versions if v["is_default"]), versions[0])


# Permanent 301s for the small number of pages hand-reslugged via
# POST /internal/admin/reslug-page (see crud.reslug_page()'s docstring --
# by-hand corrections for a slug frozen from vendor boilerplate rather
# than the meeting's own title, not a general redirect system). Add an
# entry here in the same change that performs the real rename.
_SLUG_REDIRECTS: dict[str, str] = {
    # 2026-08-28: build_base_slug() froze the literal fallback "meeting"
    # (plus hex-suffixed collisions) from a first resolve that had no
    # jurisdiction/date/title yet -- all 4 have real metadata now (see
    # BACKLOG_DONE.md's "Five frozen-slug pages reslugged" entry).
    "meeting": "tucson-az-2026-08-05-regular-meeting",
    "meeting-1e9bac": "maricopa-county-az-2026-07-15-formal",
    "meeting-38ca49": "sacramento-county-ca-2026-08-11-board-of-supervisors-meeting",
    "meeting-ef5ba6": "maricopa-county-az-2026-04-08-formal",
    # 2026-08-24/28: slug frozen from ClerkBase's boilerplate page title
    # at first resolve, not the meeting's own -- see BACKLOG_DONE.md.
    "welcome-to-clerkbase": "yellow-springs-oh-2022-02-07-february-7-2022-regular-village-council-meeting",
    # 2026-08-29: granicus.py's Census-validated jurisdiction extraction
    # chain (page-text phrasing, reversed "X County" pattern, then a
    # humanized subdomain fallback) failed all three tiers for
    # stlouispark.granicus.com, freezing the literal "Unknown
    # Jurisdiction" placeholder into the slug -- see BACKLOG.md's
    # matching entry (real extraction gap, not fixed in the adapter
    # itself this pass) and BACKLOG_DONE.md's GovAccess fuzzy-match
    # entry for how this page was found.
    "unknown-jurisdiction-st-louis-park-planning-commission-meeting-feb-7-2024": "st-louis-park-mn-st-louis-park-planning-commission-meeting-feb-7-2024",
    # 2026-08-29: this page's own stored jurisdiction was already correct
    # ("Albemarle County, VA") from whenever it was first ingested -- only
    # the slug carried the wrong label, frozen from the domain-guess era
    # that mistook albemarle.granicus.com for Albemarle, NC's tenant
    # (it's actually Albemarle County, VA's -- see BACKLOG.md's Granicus
    # GovAccess entry). No data was wrong, just a bad-looking URL.
    "albemarle-nc-2026-03-04-board-of-supervisors-on-2026-03-04-1-00-pm-regular-first": "albemarle-county-va-2026-03-04-board-of-supervisors-on-2026-03-04-1-00-pm-regula",
    # 2026-08-29: TelVue round-2 ingest froze two more wrong-state/gap
    # jurisdictions into slugs before the same-day telvue.py fixes
    # (Needham AL->MA collision, Vail Planning-and-Environmental
    # _BODY_SUFFIX_RE gap) landed -- see BACKLOG_DONE.md.
    "needham-al-needham-select-board-8-11-26": "needham-ma-needham-select-board-8-11-26",
    "vail-vail-planning-and-environmental-commission": "vail-co-vail-planning-and-environmental-commission",
}


@app.get("/m/{slug}")
async def meeting_page(
    request: Request,
    background_tasks: BackgroundTasks,
    slug: str,
    version: Optional[int] = None,
    t: Optional[int] = None,
):
    if slug in _SLUG_REDIRECTS:
        return RedirectResponse(f"/m/{_SLUG_REDIRECTS[slug]}", status_code=301)

    page = await crud.get_page_by_slug(slug)
    if page is None:
        logger.warning(
            "404: /m/%s (referer=%s)", slug, request.headers.get("referer", "")
        )
        return templates.TemplateResponse(
            request, "not_found.html", {}, status_code=404
        )

    active_version = _pick_active_version(page, version)
    active_account = get_clerk_user_id(request)
    # is_meeting_saved() only runs for a real verified session -- an
    # anonymous visitor never pays this extra query, matching the
    # "nothing existing gets gated, nothing extra costs anonymous
    # traffic" design note.
    meeting_saved = (
        await crud.is_meeting_saved(active_account, page["id"])
        if active_account
        else False
    )

    state_abbr = state_abbr_from_jurisdiction(page["jurisdiction"])

    # Python twin of crud._is_empty_page_condition() (no video, no agenda
    # items, no transcript version at all) -- the template noindexes such a
    # page, matching its exclusion from /meetings, the sitemap and the
    # feed. Kept in lockstep with the SQL predicate on purpose; a
    # divergence would put a noindexed page back in the sitemap, the
    # exact Search Console contradiction the 2026-08-17 fix removed.
    # tests/test_thin_page_predicate.py asserts the two agree, since
    # nothing else can catch them drifting apart.
    #
    # agenda_link is NOT in this list (WO-62) -- it renders as one
    # sentence pointing off-site and holds no content of its own, which
    # made a page carrying only an agenda_link a real Google Soft 404
    # while still being indexed and sitemapped. See the SQL predicate's
    # docstring for the measurement.
    page_is_empty = not (page["video_url"] or page["agenda_items"] or page["versions"])

    # One cheap indexed existence check, no image bytes loaded (see
    # crud.has_thumbnail()). When nothing is stored yet and the page has a
    # real media file, queue an extraction *as a background task* -- the
    # render path must never wait on ffmpeg. Legacy pages therefore warm
    # themselves the first time anyone (or Googlebot) looks at them;
    # freshly ingested ones were already warmed at ingest.
    card_available = await crud.has_thumbnail(page["id"])
    # The meta/og description. These pages hold real quotable text now,
    # and were still sharing (and appearing in search results) as
    # "A public meeting in X on Y, with video and transcript." -- the
    # same sentence for all ~2,400 of them, which is the templated-thin
    # shape the state/hub rebuild was diagnosed with. The stored
    # highlight is the one line on the page unique to this meeting.
    # None for a meeting with nothing quotable, where meeting_page.html
    # keeps the generic sentence.
    highlight_text = await crud.get_highlight_text(page["id"])
    if not card_available:
        _schedule_card_warm(
            background_tasks,
            page_id=page["id"],
            video_url=page["video_url"],
            video_format=page["video_format"],
            source_url=page["source_url"],
        )

    return templates.TemplateResponse(
        request,
        "meeting_page.html",
        {
            "page": page,
            "active_version": active_version,
            "page_is_empty": page_is_empty,
            # "upcoming" / "recent" / None -- drives the notice under the
            # title explaining why a page may not have video/captions yet.
            "date_status": meeting_date_status(
                page["date"], has_transcript=bool(page["versions"])
            ),
            # The <html lang> attribute should reflect what's actually on
            # the page, not always English -- a transcript's real language
            # comes from its TranscriptVersion, not a sitewide constant.
            "page_lang": (active_version["language"] if active_version else None)
            or "en",
            # Truthy only for a real, verified Clerk session -- the cookie
            # is forwarded through the resolver's reverse proxy (see
            # app/archive_client.py's proxy_get()), so this is a single
            # local check, no internal HTTP round-trip. None for every
            # anonymous visitor; nothing else on this page is conditional
            # on it (see this feature's "nothing existing gets gated"
            # design note).
            "active_account": active_account,
            "meeting_saved": meeting_saved,
            # For the "More {State} meetings" link to /state/{slug} --
            # both None when the stored jurisdiction has no recognized
            # ", ST" suffix, and the template omits the link.
            "state_name": US_STATE_ABBR_TO_NAME[state_abbr] if state_abbr else None,
            "state_slug": state_slug_from_abbr(state_abbr) if state_abbr else None,
            # For the "More {Jurisdiction} meetings" link to /j/{slug} --
            # None (link omitted) when the page has no jurisdiction at all.
            "hub_slug": jurisdiction_hub_slug(page.get("jurisdiction")),
            # og:image / VideoObject.thumbnailUrl / Event.image for
            # non-YouTube pages (WO-28). Only true once a real frame is
            # actually stored -- advertising a card URL that would 404 is
            # worse than advertising none, since Google's validator and
            # every social scraper fetch it. `card_t` is the visitor's own
            # `?t=`, passed through unchanged so the card URL matches the
            # link that was shared; the +20s lead lives in the card route.
            "card_available": card_available,
            "card_t": t if (t is not None and t >= 0) else None,
            # Plain text, never markup -- meta content can't carry tags.
            "highlight_description": (
                meta_description(highlight_text) if highlight_text else None
            ),
        },
    )


@app.get("/m/{slug}/card.jpg")
async def meeting_card_image(
    request: Request,
    background_tasks: BackgroundTasks,
    slug: str,
    t: Optional[int] = None,
):
    """The social/SEO card image for a meeting page: a real frame out of
    the meeting's own video (see archive/utils/video_thumbnail.py for the
    three targeting tiers and archive/db/models.py for why the bytes live
    in Postgres).

    **Degrades, never blocks.** The chain is: the exact per-timestamp
    frame, else the page's stored default frame, else 404 -- and a miss
    queues the extraction as a background task so the *next* fetch is
    precise. Nothing here waits on ffmpeg: a social scraper's fetch
    timeout is a few seconds, and a Granicus stall is routinely much
    longer than that.

    YouTube-backed pages redirect to their free i.ytimg.com thumbnail
    instead, so the route is a single stable card URL for every page shape
    even though only one of them involves extraction.
    """
    page = await crud.get_page_card_target(slug)
    if page is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    youtube_url = youtube_thumbnail_url(page["video_url"])
    if youtube_url:
        return RedirectResponse(youtube_url, status_code=302)

    timestamp = t if (t is not None and t >= 0) else None
    meta = None
    if timestamp is not None:
        offset = video_thumbnail.target_offset_seconds(timestamp=timestamp)
        meta = await crud.get_thumbnail_meta(page["id"], offset_seconds=offset)
        if meta is None:
            # Queue the precise frame, serve the default one meanwhile --
            # a slightly-wrong real frame now beats a correct one that
            # doesn't exist until after the scraper gave up.
            _schedule_card_warm(
                background_tasks,
                page_id=page["id"],
                video_url=page["video_url"],
                video_format=page["video_format"],
                source_url=page["source_url"],
                timestamp=timestamp,
            )
    if meta is None:
        meta = await crud.get_thumbnail_meta(page["id"])
    if meta is None:
        _schedule_card_warm(
            background_tasks,
            page_id=page["id"],
            video_url=page["video_url"],
            video_format=page["video_format"],
            source_url=page["source_url"],
        )
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    etag = f'"{meta["etag"]}"'
    # A frame for a given (page, offset) is immutable once stored, so a
    # conditional GET can be answered without ever loading the bytes --
    # which matters: Googlebot and three social networks all refetch these.
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    data = await crud.get_thumbnail_bytes(meta["id"])
    if data is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return Response(
        content=data,
        media_type=meta["content_type"],
        headers={
            "ETag": etag,
            # A day at the edge, a week stale-while-revalidate: the image
            # itself never changes, and the only thing that *can* change
            # is which frame a `?t=` maps to once its precise extraction
            # lands -- worth picking up, not worth revalidating hourly.
            "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
            "X-Card-Offset-Seconds": str(meta["offset_seconds"]),
        },
    )


# Ceiling on `slugs` below. Sized against what this endpoint actually
# does: one ffprobe plus one ffmpeg per page, sequentially, inside the
# request. A stubborn source can burn 165s of that on its own, so even a
# few dozen is a long-held connection -- the real sweep uses batches of a
# handful and this is only the outer guard rail.
MAX_BACKFILL_SLUGS = 50


@app.post("/internal/thumbnails/backfill")
async def internal_thumbnails_backfill(
    limit: int = 10,
    offset: int = 0,
    slugs: Optional[list[str]] = Query(None),
    dry_run: bool = True,
    authorization: Optional[str] = Header(None),
):
    """Warm default card frames for already-archived pages, newest first.

    Needed because nothing else reaches them: new pages warm at ingest and
    legacy pages warm when someone loads them, but the ~1200 pages already
    in the Archive would otherwise sit imageless until a crawler happened
    by. Runs the extractions inline (not BackgroundTasks) so the response
    reports what actually happened -- it is an operator endpoint called by
    hand with a small `limit`, not something on a request path.
    dry_run defaults true, matching this file's read-only-first
    convention (see /internal/jurisdiction/backfill-apply).

    Each non-dry-run result carries `offset_seconds` (null when no frame
    was produced), `reason` (why, when there is none) and `skipped` --
    see video_thumbnail.FrameOutcome. `skipped` marks the cases where
    nothing was attempted against the source at all (an in-flight
    duplicate, the 6h per-frame failure cooldown, a full queue), which a
    caller must not mistake for a page whose video is unreachable.

    `offset` pages past the head of the queue. It exists because a page
    whose extraction fails keeps no record of that failure in the
    database, so it stays a candidate forever and (newest-first) sits at
    the front of every subsequent call -- enough of them and a fixed
    `limit` sweep never reaches another new page.

    `slugs` names exact pages instead, ignoring `limit`/`offset`, and is
    what a real sweep uses. Extraction pulls bytes off a live government
    CDN, and one of them -- `archive-stream.granicus.com`, 59% of the
    backlog measured 2026-08-21 -- is the same host the transcription
    workers are already hitting `ffmpeg timed out after 120s` against.
    Letting the caller choose the pages is what lets it interleave across
    hosts and pace each one separately, instead of walking newest-first
    straight into a thousand consecutive Granicus requests. Capped at
    MAX_BACKFILL_SLUGS per call: this endpoint runs its work inline, so
    asking for hundreds at once is asking for a timeout, not a faster
    sweep. The "already has a default frame" filter applies to a named
    slug exactly as it does to a paged one, so naming a slug can never
    force a duplicate extraction. See
    crud.list_pages_missing_default_thumbnail() and
    scripts/backfill_meeting_cards.py, which drives this endpoint over
    the whole archive.
    """
    if not _token_ok(authorization):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if slugs is not None and len(slugs) > MAX_BACKFILL_SLUGS:
        return JSONResponse(
            {
                "detail": f"At most {MAX_BACKFILL_SLUGS} slugs per call "
                f"({len(slugs)} requested)."
            },
            status_code=400,
        )

    candidates = await crud.list_pages_missing_default_thumbnail(
        limit=max(1, limit), offset=max(0, offset), slugs=slugs
    )
    if slugs is not None:
        # Preserve the caller's order: the query returns rows in whatever
        # order the database likes, and for a paced sweep the order asked
        # for is the entire point.
        by_slug = {c["slug"]: c for c in candidates}
        candidates = [by_slug[s] for s in slugs if s in by_slug]
    if dry_run:
        return {
            "dry_run": True,
            "offset": max(0, offset),
            "candidates": [
                {"slug": c["slug"], "video_url": c["video_url"]} for c in candidates
            ],
        }

    results = []
    for candidate in candidates:
        # Deliberately NOT named `offset`: that's this endpoint's own query
        # parameter, and shadowing it here was a real 500 in production
        # (2026-08-21, caught by the first bounded --apply run of
        # scripts/backfill_meeting_cards.py). extract_and_store()'s
        # FrameOutcome.offset is None whenever an extraction fails -- so a
        # batch whose LAST page failed left `offset` as None and the
        # response's `max(0, offset)` raised TypeError. Failures are the
        # normal case here, not the exception (government CDNs time out
        # constantly), and the paged mode had the same bug, so any sweep
        # would have hit it.
        outcome = await video_thumbnail.extract_and_store(
            page_id=candidate["id"],
            video_url=candidate["video_url"],
            source_page_url=candidate["source_url"] or candidate["video_url"],
        )
        results.append(
            {
                "slug": candidate["slug"],
                # Carried through so a caller can group failures by media
                # host without a second lookup -- the single most useful
                # signal when a sweep starts failing (one CDN rate-
                # limiting is a very different problem from scattered
                # dead links).
                "video_url": candidate["video_url"],
                "offset_seconds": outcome.offset,
                # WO-42. Until this, a sweep's only per-slug signal was
                # `offset_seconds: null` and the real reason lived in an
                # Archive log line nobody correlates back to a slug --
                # which is exactly why the first production sweep's 179
                # failures came back undiagnosable. `skipped` is not
                # cosmetic: a skip means nothing was attempted against
                # the source (cooldown, in-flight, queue full), so a
                # caller must not record it as a dead page the way it
                # records a real failure.
                "reason": outcome.reason,
                "skipped": outcome.skipped,
            }
        )
    return {
        "dry_run": False,
        "offset": max(0, offset),
        "attempted": len(results),
        "stored": sum(1 for r in results if r["offset_seconds"] is not None),
        "skipped": sum(1 for r in results if r["skipped"]),
        "results": results,
    }


@app.get("/m/{slug}/transcript.{ext}")
async def meeting_transcript_export(slug: str, ext: str, version: Optional[int] = None):
    if ext not in ("txt", "srt"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    page = await crud.get_page_by_slug(slug)
    if page is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    active_version = _pick_active_version(page, version)
    if not active_version or not active_version["segments"]:
        return JSONResponse(
            {"detail": "No transcript available for this meeting."}, status_code=404
        )

    body = (
        to_srt(active_version["segments"])
        if ext == "srt"
        else to_txt(active_version["segments"])
    )
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
    background_tasks: BackgroundTasks,
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
    # Search Step 2a: "relevance" orders keyword results by ts_rank_cd()
    # (Postgres full-text search only -- see crud.list_pages()); anything
    # else, incl. the tolerated empty string, means the default newest-
    # first. Same tolerant-string shape as the three bools above.
    sort: Optional[str] = None,
):
    fuzzy_bool = fuzzy == "true"
    has_agenda_bool = _parse_optional_bool(has_agenda)
    has_transcript_bool = _parse_optional_bool(has_transcript)
    sort_relevance = sort == "relevance"
    result = await crud.list_pages(
        page=page,
        jurisdiction=jurisdiction,
        date_from=date_from,
        date_to=date_to,
        has_agenda=has_agenda_bool,
        has_transcript=has_transcript_bool,
        keyword=q,
        fuzzy=fuzzy_bool,
        sort="relevance" if sort_relevance else "newest",
    )
    # Record the keyword (and nothing about who typed it) so the curated
    # topic list in archive/topics.py can eventually be ranked by real
    # demand instead of guesswork -- see models.SearchQuery. Fire-and-
    # forget: a logging failure must never break a search, and the write
    # must never be on the response's critical path.
    if q and q.strip():
        background_tasks.add_task(
            crud.record_search_query,
            keyword=q.strip()[:200],
            jurisdiction=jurisdiction,
            result_count=result.get("total") or 0,
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
            "sort_relevance": sort_relevance,
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
    states = await crud.get_state_coverage_index()
    transcribed_count = await crud.count_transcribed_pages()
    return templates.TemplateResponse(
        request,
        "coverage.html",
        {
            "coverage": coverage_rows,
            "jurisdictions": jurisdictions,
            "states": states,
            "transcribed_count": transcribed_count,
            "active_account": get_clerk_user_id(request),
        },
    )


@app.get("/coverage/detail")
async def coverage_detail(request: Request):
    """The sortable/filterable "Full jurisdiction detail table," split out
    of /coverage 2026-08-26 -- mostly a personal/power-user tool (see
    CLAUDE.md), kept noindex and linked only from /coverage's "What about
    Platform XYZ?" FAQ answer rather than rendered on the public page."""
    full_jurisdictions = await crud.get_full_jurisdiction_coverage()
    # Distinct filter-dropdown option lists, derived from the real rows
    # rather than DIRECT_PLATFORMS/CUSTOM_PLATFORMS directly -- this table
    # can show labels those dicts don't have (e.g. "PrimeGov", a raw
    # video_url host for a generic_fallback row), so the dropdowns should
    # only ever offer options a filter click can actually match something.
    detail_platform_options = sorted(
        {row["detail_platform"] for row in full_jurisdictions}, key=str.casefold
    )
    video_platform_options = sorted(
        {row["video_platform"] for row in full_jurisdictions}, key=str.casefold
    )
    outcome_options = sorted(
        {(row["outcome"], row["outcome_label"]) for row in full_jurisdictions},
        key=lambda o: o[1],
    )
    return templates.TemplateResponse(
        request,
        "coverage_detail.html",
        {
            "full_jurisdictions": full_jurisdictions,
            "detail_platform_options": detail_platform_options,
            "video_platform_options": video_platform_options,
            "outcome_options": outcome_options,
            "active_account": get_clerk_user_id(request),
        },
    )


@app.get("/api/jurisdictions")
async def api_jurisdictions(q: str = ""):
    """Public jurisdiction-name lookup behind /coverage's "Find your
    government" search box. No auth -- same public-data posture as
    /api/health, unlike the token-gated /internal/* routes. Each match
    already carries its own `kind` ("state" or "jurisdiction")/`label`/
    `link` from crud.search_jurisdictions() -- typing a full state name
    returns a "state" match (linking to /state/{slug}) followed by that
    state's most-covered governments, not just a plain substring match
    against jurisdiction names."""
    results = await crud.search_jurisdictions(q, limit=10)
    return {"matches": results}


@app.get("/state/all-50")
async def state_all50(request: Request, topic: str = ""):
    """A national, 50-US-states-only hub -- deliberately narrower than
    "every jurisdiction" for a first cut (see CLAUDE.md). Registered
    ahead of the dynamic /state/{state_slug} route below so this literal
    path is matched first; "all-50" isn't a real state slug so it would
    otherwise just fall through to that route's own 404."""
    data = await crud.get_all50_page_data(topic_slug=topic or None)
    return templates.TemplateResponse(
        request,
        "state_all50.html",
        {**data, "active_account": get_clerk_user_id(request)},
    )


@app.get("/state/{state_slug}")
async def state_page(request: Request, state_slug: str, topic: str = ""):
    abbr = STATE_SLUG_TO_ABBR.get(state_slug)
    # An unknown ?topic= is ignored rather than 404'd: the parameter only
    # reorders which real meetings are featured, so a stale or
    # hand-edited value should still render the page. get_state_page_data
    # validates the slug against TOPICS_BY_SLUG itself.
    data = (
        await crud.get_state_page_data(abbr, topic_slug=topic or None) if abbr else None
    )
    if data is None:
        # Unknown slug, or a real state with no indexable meetings yet --
        # same in-route 404 pattern as /m/{slug}.
        return templates.TemplateResponse(
            request, "not_found.html", {}, status_code=404
        )
    return templates.TemplateResponse(
        request,
        "state_page.html",
        {
            **data,
            "state_slug": state_slug,
            "all_topics": TOPICS,
            "active_account": get_clerk_user_id(request),
        },
    )


@app.get("/j/{hub_slug}")
async def jurisdiction_page(request: Request, hub_slug: str, topic: str = ""):
    """Per-government hub: every archived meeting for one jurisdiction
    (see crud.get_jurisdiction_hub_data() -- grouped by
    jurisdiction_hub_slug(), so raw-string variants of one city land on one
    page). 404s for an unknown slug or one with no indexable meetings, same
    in-route pattern as /m/{slug} and /state/{slug}. Below
    crud.JURISDICTION_HUB_MIN_INDEXABLE meetings the page renders with a
    noindex (thin-content posture) and stays out of sitemap.xml."""
    data = await crud.get_jurisdiction_hub_data(hub_slug, topic_slug=topic or None)
    if data is None:
        return templates.TemplateResponse(
            request, "not_found.html", {}, status_code=404
        )
    return templates.TemplateResponse(
        request,
        "jurisdiction_page.html",
        {**data, "active_account": get_clerk_user_id(request)},
    )


# Public, indexable static pages -- not MeetingPage rows, so they have no
# real lastmod and aren't produced by list_all_page_slugs(). Deliberately
# excludes /account/saved, /alerts/unsubscribe, /meeting (already
# robots.txt-disallowed as the ephemeral, unarchived resolver page), and
# every /admin/* route -- none of those are public content.
_SITEMAP_STATIC_PATHS = ["/", "/about", "/coverage", "/meetings", "/state/all-50"]


@app.get("/sitemap.xml")
async def sitemap():
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    entries = await crud.list_all_page_slugs()
    states = await crud.get_state_coverage_index()
    hubs = await crud.list_indexable_hub_entries()
    body = templates.get_template("sitemap.xml.jinja").render(
        base_url=base,
        entries=entries,
        states=states,
        hubs=hubs,
        static_paths=_SITEMAP_STATIC_PATHS,
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
    # An RSS feed isn't meant to be an indexable page -- Search Console was
    # crawling and index-judging it (declining it as "Crawled - currently
    # not indexed") despite feed.xml never appearing in sitemap.xml.
    # Deliberately X-Robots-Tag, not a robots.txt Disallow: a Disallow would
    # also stop Google following the links *inside* the feed, which is a
    # real discovery path for new meeting pages. noindex takes the feed
    # itself out of the index while keeping that discovery intact. Covers
    # a direct hit on this route; app/main.py's /feed.xml proxy passes
    # response headers through unchanged, so this also covers the public
    # feed.xml URL readers actually use.
    return Response(
        content=body,
        media_type="application/rss+xml",
        headers={"X-Robots-Tag": "noindex"},
    )
