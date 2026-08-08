import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, select

from ..utils.search import build_corpus, matches, tokenize
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
