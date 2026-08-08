import hashlib
from typing import Any, Optional

from sqlalchemy import select

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
                return {"slug": page.slug, "url": f"/m/{page.slug}"}

        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.source_url_normalized == url_normalized)
            )
        ).scalars().first()
        if page:
            return {"slug": page.slug, "url": f"/m/{page.slug}"}

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
