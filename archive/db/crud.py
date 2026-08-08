import hashlib
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, select

from ..utils.language import detect_language_from_texts
from ..utils.search import build_corpus, matches, tokenize
from ..utils.slugify import build_base_slug, random_suffix
from ..utils.url_normalize import normalize_url
from .engine import async_session
from .models import MeetingPage, MeetingPageUrlAlias, TranscriptionJob, TranscriptVersion


def _content_hash(segments: list) -> str:
    joined = "\n".join(seg.get("text", "") for seg in segments)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


async def lookup_page_for_url(url_normalized: str) -> Optional[dict]:
    """Used by GET /internal/lookup -- the resolver only has the raw pasted
    URL at this point, not yet a platform/external_id, so this can only key
    off what's already recorded as an alias (every ingest records its
    input_url_normalized as an alias, including the very first one -- see
    ingest_resolution). Falls back to a direct source_url_normalized match
    for robustness, though in practice the alias table should already cover
    that case.
    """
    async with async_session() as session:
        alias = (
            await session.execute(
                select(MeetingPageUrlAlias).where(MeetingPageUrlAlias.url_normalized == url_normalized)
            )
        ).scalars().first()
        if alias:
            page = await session.get(MeetingPage, alias.meeting_page_id)
            if page:
                return {"slug": page.slug, "url": f"/m/{page.slug}", "updated_at": page.updated_at.isoformat()}

        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.source_url_normalized == url_normalized)
            )
        ).scalars().first()
        if page:
            return {"slug": page.slug, "url": f"/m/{page.slug}", "updated_at": page.updated_at.isoformat()}

    return None


async def _find_existing_page(session, *, platform: str, external_id: Optional[str], source_url_normalized: str, input_url_normalized: str) -> Optional[MeetingPage]:
    alias = (
        await session.execute(
            select(MeetingPageUrlAlias).where(MeetingPageUrlAlias.url_normalized == input_url_normalized)
        )
    ).scalars().first()
    if alias:
        page = await session.get(MeetingPage, alias.meeting_page_id)
        if page:
            return page

    if external_id:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.platform == platform, MeetingPage.external_id == external_id)
            )
        ).scalars().first()
        if page:
            return page

    return (
        await session.execute(
            select(MeetingPage).where(MeetingPage.source_url_normalized == source_url_normalized)
        )
    ).scalars().first()


async def _ensure_alias(session, url_normalized: str, meeting_page_id: int) -> None:
    existing = (
        await session.execute(
            select(MeetingPageUrlAlias).where(MeetingPageUrlAlias.url_normalized == url_normalized)
        )
    ).scalars().first()
    if not existing:
        session.add(MeetingPageUrlAlias(url_normalized=url_normalized, meeting_page_id=meeting_page_id))


async def _unique_slug(session, base: str) -> str:
    slug = base
    for _ in range(5):
        existing = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        if not existing:
            return slug
        slug = f"{base}-{random_suffix()}"
    # Exhausted retries (astronomically unlikely) -- fall back to a longer
    # random suffix rather than looping forever.
    return f"{base}-{random_suffix(12)}"


async def _find_or_create_page(session, payload: dict[str, Any], input_url_normalized: str) -> MeetingPage:
    """Shared by ingest_resolution() and create_transcription_job() -- both
    need "find this meeting's permanent page, or create one if this is the
    first thing that's ever landed for it" from the same resolver-payload
    shape. Extracted 2026-08-08 when the transcription feature needed the
    exact same logic ingest_resolution() already had inline.
    """
    platform = payload["platform"]
    external_id = payload.get("external_id")
    source_url_normalized = normalize_url(payload["source_url"])

    page = await _find_existing_page(
        session,
        platform=platform,
        external_id=external_id,
        source_url_normalized=source_url_normalized,
        input_url_normalized=input_url_normalized,
    )

    if page is None:
        base_slug = build_base_slug(payload.get("jurisdiction") or "", payload.get("date") or "", payload.get("title") or "")
        slug = await _unique_slug(session, base_slug)
        page = MeetingPage(
            slug=slug,
            platform=platform,
            external_id=external_id,
            source_url_normalized=source_url_normalized,
            title=payload.get("title"),
            date=payload.get("date"),
            jurisdiction=payload.get("jurisdiction"),
            video_url=payload.get("video_url"),
            video_format=payload.get("video_format"),
            agenda_items=payload.get("agenda_items") or [],
        )
        session.add(page)
        await session.flush()  # assigns page.id
    else:
        # Keep page-level fields fresh (title/video/agenda can improve
        # on a later, better resolve) without touching the slug.
        page.title = payload.get("title") or page.title
        page.date = payload.get("date") or page.date
        page.jurisdiction = payload.get("jurisdiction") or page.jurisdiction
        page.video_url = payload.get("video_url") or page.video_url
        page.video_format = payload.get("video_format") or page.video_format
        if payload.get("agenda_items"):
            page.agenda_items = payload["agenda_items"]
        # Reassigning a column to its *current* value doesn't dirty it
        # for SQLAlchemy's purposes, so `onupdate=func.now()` silently
        # never fires on a re-ingest whose content is byte-identical to
        # what's already stored -- the common case for a re-check that
        # finds nothing new. That left `updated_at` permanently stuck on
        # a stale page (confirmed live: a backdated page stayed "stale"
        # forever, re-triggering the opportunistic re-check in
        # app/main.py on every single hit instead of once per
        # ARCHIVE_RECHECK_AFTER window). Touch it explicitly so
        # `updated_at` always means "last time this page was actually
        # checked," independent of whether anything changed.
        page.updated_at = datetime.now(timezone.utc)

    await _ensure_alias(session, input_url_normalized, page.id)
    await _ensure_alias(session, source_url_normalized, page.id)
    return page


async def ingest_resolution(payload: dict[str, Any], input_url_normalized: str) -> dict:
    """Create a MeetingPage (or attach a new TranscriptVersion to an
    existing one) from a resolver push. `payload` is the resolver's
    ResolvedMeeting.model_dump() shape: platform, source_url, external_id,
    title, date, jurisdiction, video_url, video_format, segments,
    agenda_items, transcript_language, transcript_warnings.
    """
    segments = payload.get("segments") or []

    async with async_session() as session:
        page = await _find_or_create_page(session, payload, input_url_normalized)

        if segments:
            language = payload.get("transcript_language")
            content_hash = _content_hash(segments)

            duplicate = (
                await session.execute(
                    select(TranscriptVersion).where(
                        TranscriptVersion.meeting_page_id == page.id,
                        TranscriptVersion.language == language,
                        TranscriptVersion.source == "scraped",
                        TranscriptVersion.content_hash == content_hash,
                    )
                )
            ).scalars().first()

            if duplicate is None:
                any_version = (
                    await session.execute(
                        select(TranscriptVersion).where(TranscriptVersion.meeting_page_id == page.id)
                    )
                ).scalars().first()
                session.add(
                    TranscriptVersion(
                        meeting_page_id=page.id,
                        language=language,
                        source="scraped",
                        is_default=any_version is None,
                        segments=segments,
                        transcript_warnings=payload.get("transcript_warnings") or [],
                        content_hash=content_hash,
                    )
                )

        await session.commit()
        return {"slug": page.slug, "url": f"/m/{page.slug}"}


async def get_page_by_slug(slug: str) -> Optional[dict]:
    async with async_session() as session:
        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalars().first()
        if page is None:
            return None

        versions = (
            await session.execute(
                select(TranscriptVersion)
                .where(TranscriptVersion.meeting_page_id == page.id)
                .order_by(TranscriptVersion.is_default.desc(), TranscriptVersion.created_at.asc())
            )
        ).scalars().all()

        return {
            "slug": page.slug,
            "title": page.title,
            "date": page.date,
            "jurisdiction": page.jurisdiction,
            "video_url": page.video_url,
            "video_format": page.video_format,
            "agenda_items": page.agenda_items or [],
            "source_url": page.source_url_normalized,
            "versions": [
                {
                    "id": v.id,
                    "language": v.language,
                    "source": v.source,
                    "is_default": v.is_default,
                    "segments": v.segments,
                    "transcript_warnings": v.transcript_warnings or [],
                }
                for v in versions
            ],
        }


async def list_pages(
    *,
    page: int = 1,
    page_size: int = 20,
    jurisdiction: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    has_agenda: Optional[bool] = None,
    has_transcript: Optional[bool] = None,
    keyword: Optional[str] = None,
    fuzzy: bool = False,
) -> dict:
    """Paginated listing for the /meetings index page. Filters and the
    keyword search box narrow this same query rather than being a separate
    feature (per the backlog note this was scoped from).

    Keyword search covers title, jurisdiction, agenda item text, and the
    default transcript version's segment text -- see
    `archive/utils/search.py`. No search index, no materialized column:
    matching runs in Python, at query time, over whatever this function's
    own SQL query already returned -- deliberately not the "real" fix
    (Postgres trigram search + a materialized/indexed text column) that
    full transcript-body search eventually needs at real scale. Fine for
    the Archive's current size (dozens of meetings); see BACKLOG.md
    ("Search: move to a materialized/indexed column at scale") for what
    outgrowing this looks like and why it isn't built that way now.
    `jurisdiction`/`date_from`/`date_to`/`has_transcript` still filter in
    SQL first (cheap, and `has_transcript` needs no JSON at all), so a
    keyword-less, agenda-less browse of the page never fetches transcript
    JSON it doesn't need. `has_agenda` and `keyword` can only be evaluated
    once agenda/transcript content is in hand, so pagination for those
    happens in Python, over the SQL-filtered candidate set, not via
    LIMIT/OFFSET.

    `date` is stored as an ISO "YYYY-MM-DD" string, not a Date column --
    lexicographic comparison on that format matches chronological order, so
    plain >=/<= works for the date-range filter without a schema change.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    conditions = []
    if jurisdiction:
        conditions.append(MeetingPage.jurisdiction.ilike(f"%{jurisdiction}%"))
    if date_from:
        conditions.append(MeetingPage.date >= date_from)
    if date_to:
        conditions.append(MeetingPage.date <= date_to)
    if has_transcript is True:
        conditions.append(TranscriptVersion.id.is_not(None))
    elif has_transcript is False:
        conditions.append(TranscriptVersion.id.is_(None))

    # segments only ever pulled from the DB when a keyword search is
    # actually running -- otherwise a plain browse/filter of the listing
    # would drag every meeting's full transcript JSON over the wire for
    # nothing (Dublin's real 36k-segment transcript alone is well over a
    # megabyte of JSON).
    columns = [MeetingPage, TranscriptVersion.language, TranscriptVersion.id]
    if keyword:
        columns.append(TranscriptVersion.segments)

    stmt = (
        select(*columns)
        .outerjoin(
            TranscriptVersion,
            and_(TranscriptVersion.meeting_page_id == MeetingPage.id, TranscriptVersion.is_default.is_(True)),
        )
        .order_by(MeetingPage.created_at.desc())
    )
    if conditions:
        stmt = stmt.where(and_(*conditions))

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    def _matches_page(mp: MeetingPage, segments: Optional[list]) -> bool:
        if has_agenda is True and not mp.agenda_items:
            return False
        if has_agenda is False and mp.agenda_items:
            return False
        if not keyword:
            return True
        corpus = build_corpus(
            mp.title or "",
            mp.jurisdiction or "",
            " ".join(item.get("text", "") for item in (mp.agenda_items or [])),
            " ".join(seg.get("text", "") for seg in (segments or [])),
        )
        return matches(keyword, corpus, tokenize(corpus) if fuzzy else set(), fuzzy)

    filtered = []
    for row in rows:
        if keyword:
            mp, lang, version_id, segments = row
        else:
            mp, lang, version_id = row
            segments = None
        if _matches_page(mp, segments):
            filtered.append({"mp": mp, "lang": lang, "version_id": version_id})

    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_rows = filtered[start:start + page_size]

    return {
        "pages": [
            {
                "slug": r["mp"].slug,
                "title": r["mp"].title,
                "date": r["mp"].date,
                "jurisdiction": r["mp"].jurisdiction,
                "platform": r["mp"].platform,
                "language": r["lang"],
                "has_transcript": r["version_id"] is not None,
                "has_agenda": bool(r["mp"].agenda_items),
            }
            for r in page_rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


async def list_all_page_slugs() -> list[dict]:
    """Every page's slug + updated_at, unpaginated -- for sitemap.xml.
    Fine as a single query at hundreds/thousands of rows; revisit (batching,
    a sitemap index + sub-sitemaps) only once actually approaching the
    ~50k-URL point where Google expects that split."""
    async with async_session() as session:
        rows = (
            await session.execute(select(MeetingPage.slug, MeetingPage.updated_at).order_by(MeetingPage.updated_at.desc()))
        ).all()
    return [{"slug": slug, "updated_at": updated_at} for slug, updated_at in rows]


async def list_recent_pages_for_feed(*, jurisdiction: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Most-recently-archived pages for feed.xml -- a separate, deliberately
    simple query rather than reusing list_pages()'s pagination/multi-filter
    machinery, since a feed only ever wants "the last N, optionally scoped
    to one jurisdiction," newest first, with no page number to track."""
    limit = max(1, min(limit, 100))
    stmt = select(MeetingPage).order_by(MeetingPage.created_at.desc()).limit(limit)
    if jurisdiction:
        stmt = stmt.where(MeetingPage.jurisdiction.ilike(f"%{jurisdiction}%"))

    async with async_session() as session:
        rows = (await session.execute(stmt)).scalars().all()

    return [
        {
            "slug": mp.slug,
            "title": mp.title,
            "date": mp.date,
            "jurisdiction": mp.jurisdiction,
            "created_at": mp.created_at,
        }
        for mp in rows
    ]


# --- On-demand transcription -------------------------------------------
#
# A job moves pending_confirmation -> queued -> in_progress -> completed |
# failed. pending_confirmation and queued/in_progress are both "active" for
# the purposes of blocking a duplicate request against the same page, but
# only queued/in_progress count toward MAX_CONCURRENT_TRANSCRIPTION_JOBS --
# an unconfirmed request isn't spending any worker/transcription time yet.
#
# Known gap, not solved here: a pending_confirmation job that's never
# confirmed blocks new requests for that page indefinitely (no expiry).
# Fine to leave for now given how new this feature is; worth a cleanup pass
# (e.g. treat pending_confirmation older than 48h as abandoned) once this
# has been live long enough to know if it's a real problem. Tracked in
# BACKLOG.md.

ACTIVE_JOB_STATUSES = ("pending_confirmation", "queued", "in_progress")
SPENDING_JOB_STATUSES = ("queued", "in_progress")
MAX_CONCURRENT_TRANSCRIPTION_JOBS = 3
# Was 10 minutes; shortened live 2026-08-08 after a real OOM-crash-loop
# meant the countdown kept resetting (each auto-restart re-claimed the
# job, pushing "stale" 10 more minutes out every time) -- annoying to
# wait out mid-debugging. 5 minutes is still comfortably longer than a
# single chunk should ever legitimately take with the "tiny" model, and
# the only real instance of this repo's single worker process, so there's
# no concurrent-worker race this protects against, just crash detection.
STALE_CLAIM_AFTER = timedelta(minutes=5)
MAX_CONSECUTIVE_CHUNK_FAILURES = 3


async def promote_transcript_version(session, page_id: int, version_id: int) -> None:
    """Make `version_id` the one /m/{slug} renders by default, demoting
    whichever version held that spot before -- never deletes anything, the
    demoted version stays reachable via the existing `?version=` picker.
    Real gap this closes: previously only the very first TranscriptVersion
    a page ever got was set is_default, and nothing later ever promoted a
    subsequent one (see BACKLOG_DONE.md). Caller must be inside an existing
    session/transaction (this doesn't commit) -- both call sites below
    (finalize) already are.
    """
    versions = (
        await session.execute(select(TranscriptVersion).where(TranscriptVersion.meeting_page_id == page_id))
    ).scalars().all()
    for v in versions:
        v.is_default = v.id == version_id


async def create_transcription_job(
    *,
    payload: dict[str, Any],
    input_url_normalized: str,
    requester_email: str,
    media_url: str,
    media_kind: str,
    probed_duration_seconds: float,
    chunk_size_seconds: int,
    skip_confirmation: bool,
) -> dict:
    """Find-or-create the MeetingPage (a request can be the very first thing
    that ever creates a permanent page for a meeting -- the ephemeral
    resolver page doesn't require one to exist first), then create the job
    -- unless one's already active for this page, in which case that
    existing job's status is returned instead of creating a duplicate.

    `skip_confirmation` is decided by the caller (archive/main.py, after
    checking Resend audience membership) -- this function doesn't reach out
    to Resend itself, keeping external API calls out of the DB layer.
    """
    async with async_session() as session:
        page = await _find_or_create_page(session, payload, input_url_normalized)

        existing = (
            await session.execute(
                select(TranscriptionJob)
                .where(TranscriptionJob.meeting_page_id == page.id, TranscriptionJob.status.in_(ACTIVE_JOB_STATUSES))
                .order_by(TranscriptionJob.created_at.desc())
            )
        ).scalars().first()
        if existing:
            await session.commit()  # persist the page if it was just created, even though no job was
            return _job_dict(existing, page)

        active_spend_count = (
            await session.execute(
                select(TranscriptionJob).where(TranscriptionJob.status.in_(SPENDING_JOB_STATUSES))
            )
        ).scalars().all()
        if len(active_spend_count) >= MAX_CONCURRENT_TRANSCRIPTION_JOBS:
            await session.commit()
            return {"error": "too_many_active_jobs", "slug": page.slug}

        total_chunks = math.ceil(probed_duration_seconds / chunk_size_seconds)
        job = TranscriptionJob(
            meeting_page_id=page.id,
            requester_email=requester_email,
            confirmation_token=None if skip_confirmation else secrets.token_urlsafe(32),
            status="queued" if skip_confirmation else "pending_confirmation",
            media_url=media_url,
            media_kind=media_kind,
            probed_duration_seconds=probed_duration_seconds,
            chunk_size_seconds=chunk_size_seconds,
            total_chunks=total_chunks,
        )
        session.add(job)
        await session.commit()
        return _job_dict(job, page)


async def confirm_transcription_job(token: str) -> Optional[dict]:
    """Flips a first-time requester's job from pending_confirmation to
    queued once they click the link in their confirmation email. Returns
    None if the token doesn't match any job still awaiting confirmation
    (already confirmed, or never existed) -- the caller shows a generic
    "link invalid or already used" message either way, not distinguishing
    which, same reasoning as the admin/internal routes' 404-not-401
    pattern elsewhere in this codebase."""
    async with async_session() as session:
        job = (
            await session.execute(
                select(TranscriptionJob).where(
                    TranscriptionJob.confirmation_token == token,
                    TranscriptionJob.status == "pending_confirmation",
                )
            )
        ).scalars().first()
        if job is None:
            return None
        job.status = "queued"
        job.confirmation_token = None
        page = await session.get(MeetingPage, job.meeting_page_id)
        await session.commit()
        return _job_dict(job, page)


async def claim_next_chunk() -> Optional[dict]:
    """Atomically claims the oldest queued/in_progress job with no live
    claim, marking it in_progress and stamping claimed_at so a second
    concurrent caller won't also pick it up. The staleness window
    (STALE_CLAIM_AFTER) exists for a crashed/restarted worker process, not
    a multi-worker race -- only one worker process is planned (see the
    plan this was built from), so this is a safety net, not load-bearing
    concurrency control. Returns everything the worker needs to process
    one chunk, or None if nothing's claimable right now.
    """
    now = datetime.now(timezone.utc)
    stale_before = now - STALE_CLAIM_AFTER

    async with async_session() as session:
        job = (
            await session.execute(
                select(TranscriptionJob)
                .where(
                    TranscriptionJob.status.in_(("queued", "in_progress")),
                    (TranscriptionJob.claimed_at.is_(None)) | (TranscriptionJob.claimed_at < stale_before),
                )
                .order_by(TranscriptionJob.created_at.asc())
                .limit(1)
            )
        ).scalars().first()
        if job is None:
            return None

        job.status = "in_progress"
        job.claimed_at = now
        page = await session.get(MeetingPage, job.meeting_page_id)
        await session.commit()

        return {
            "job_id": job.id,
            "meeting_page_id": job.meeting_page_id,
            "source_url": page.source_url_normalized if page else None,
            "platform": page.platform if page else None,
            "media_url": job.media_url,
            "chunk_index": job.chunks_completed,  # next chunk to process
            "total_chunks": job.total_chunks,
            "chunk_size_seconds": job.chunk_size_seconds,
            "probed_duration_seconds": job.probed_duration_seconds,
        }


async def report_chunk_result(
    job_id: int,
    *,
    success: bool,
    shifted_segments: Optional[list] = None,
    error: Optional[str] = None,
) -> dict:
    """Called by the worker after attempting one chunk. On success, appends
    already-offset segments and advances progress; if that was the last
    chunk, finalizes the job (writes the TranscriptVersion, promotes it,
    caller -- archive/main.py -- sends the completion email afterward using
    this function's returned `completed`/`transcript_version_id`). On
    failure, counts toward MAX_CONSECUTIVE_CHUNK_FAILURES before giving up
    on the whole job -- a single flaky chunk (transient network blip)
    shouldn't fail an otherwise-fine multi-hour job.
    """
    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        if job is None:
            return {"error": "job_not_found"}

        job.claimed_at = None  # release the claim regardless of outcome

        if not success:
            job.consecutive_chunk_failures += 1
            job.error_message = error
            if job.consecutive_chunk_failures >= MAX_CONSECUTIVE_CHUNK_FAILURES:
                job.status = "failed"
            await session.commit()
            return {"status": job.status, "consecutive_chunk_failures": job.consecutive_chunk_failures}

        job.consecutive_chunk_failures = 0
        job.partial_segments = [*job.partial_segments, *(shifted_segments or [])]
        job.chunks_completed += 1

        if job.chunks_completed >= job.total_chunks:
            language = detect_language_from_texts(s["text"] for s in job.partial_segments)
            version = TranscriptVersion(
                meeting_page_id=job.meeting_page_id,
                language=language,
                source="transcribed",
                is_default=False,  # promote_transcript_version sets the real default below
                segments=sorted(job.partial_segments, key=lambda s: s["start"]),
                transcript_warnings=[],
                content_hash=_content_hash(job.partial_segments),
            )
            session.add(version)
            await session.flush()  # assigns version.id
            await promote_transcript_version(session, job.meeting_page_id, version.id)
            job.transcript_version_id = version.id
            job.status = "completed"
            page = await session.get(MeetingPage, job.meeting_page_id)
            await session.commit()
            return {
                "status": "completed",
                "transcript_version_id": version.id,
                "meeting_page_slug": page.slug if page else None,
                "meeting_page_title": page.title if page else None,
            }

        await session.commit()
        return {"status": "in_progress", "chunks_completed": job.chunks_completed, "total_chunks": job.total_chunks}


def _job_dict(job: TranscriptionJob, page: Optional[MeetingPage]) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "chunks_completed": job.chunks_completed,
        "total_chunks": job.total_chunks,
        "meeting_page_slug": page.slug if page else None,
        "meeting_page_title": page.title if page else None,
        "error_message": job.error_message,
        # Only meaningful to internal (token-gated) callers -- app/main.py's
        # public status-poll proxy strips this before it ever reaches a
        # browser, no reason to echo a viewer's own email back to them.
        "requester_email": job.requester_email,
    }


async def get_transcription_job_status(job_id: int) -> Optional[dict]:
    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        if job is None:
            return None
        page = await session.get(MeetingPage, job.meeting_page_id)
        return _job_dict(job, page)


async def get_confirmation_token(job_id: int) -> Optional[str]:
    """Deliberately separate from _job_dict() (which never includes the
    token) -- the only caller is archive/main.py's create-job endpoint,
    immediately after creating a pending_confirmation job, solely to build
    the emailed confirm link. Never returned to any other caller."""
    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        return job.confirmation_token if job else None
