import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select

from ..utils.slugify import build_base_slug, random_suffix
from ..utils.url_normalize import normalize_url
from .engine import async_session
from .models import MeetingPage, MeetingPageUrlAlias, TranscriptVersion


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


async def ingest_resolution(payload: dict[str, Any], input_url_normalized: str) -> dict:
    """Create a MeetingPage (or attach a new TranscriptVersion to an
    existing one) from a resolver push. `payload` is the resolver's
    ResolvedMeeting.model_dump() shape: platform, source_url, external_id,
    title, date, jurisdiction, video_url, video_format, segments,
    agenda_items, transcript_language, transcript_warnings.
    """
    platform = payload["platform"]
    external_id = payload.get("external_id")
    source_url_normalized = normalize_url(payload["source_url"])
    segments = payload.get("segments") or []

    async with async_session() as session:
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
    language: Optional[str] = None,
    keyword: Optional[str] = None,
) -> dict:
    """Paginated listing for the /meetings index page. Filters and the
    keyword search box narrow this same query rather than being a separate
    feature (per the backlog note this was scoped from).

    v1 keyword search covers title and jurisdiction only, via a portable
    .ilike() (works on both Postgres and the local SQLite fallback) --
    deliberately not full transcript-body text search. `segments` live as
    JSON per TranscriptVersion, not a plain searchable column, so matching
    inside transcript content is a real follow-up (materialized tsvector or
    similar), not something to silently half-implement here.

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
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(or_(MeetingPage.title.ilike(pattern), MeetingPage.jurisdiction.ilike(pattern)))

    def _apply_filters(stmt):
        # Always outer-joined (not just when `language` is set) since the
        # listing also displays each page's default transcript language --
        # one query serves both the filter and the display data.
        stmt = stmt.outerjoin(
            TranscriptVersion,
            and_(TranscriptVersion.meeting_page_id == MeetingPage.id, TranscriptVersion.is_default.is_(True)),
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))
        if language:
            stmt = stmt.where(TranscriptVersion.language == language)
        return stmt

    async with async_session() as session:
        count_stmt = _apply_filters(select(func.count(MeetingPage.id.distinct())))
        total = (await session.execute(count_stmt)).scalar_one()

        list_stmt = (
            _apply_filters(select(MeetingPage, TranscriptVersion.language, TranscriptVersion.id))
            .order_by(MeetingPage.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = (await session.execute(list_stmt)).all()

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "pages": [
            {
                "slug": mp.slug,
                "title": mp.title,
                "date": mp.date,
                "jurisdiction": mp.jurisdiction,
                "platform": mp.platform,
                "language": lang,
                "has_transcript": version_id is not None,
            }
            for mp, lang, version_id in rows
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
