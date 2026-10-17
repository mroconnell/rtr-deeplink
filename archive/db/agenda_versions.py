"""Storage for AgendaVersion rows (WO-1966).

Its own module rather than another section of crud.py: the table is new,
narrow, and deliberately never joined into any query that spans every
page (packet text runs to 1.8M characters; the 2026-08-17 out-of-memory
restart came from loading all transcript text at once).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .engine import async_session
from .models import AgendaVersion


async def roles_checked_since(page_id: int, since: datetime) -> set[str]:
    """The document roles ("agenda", "packet") this page already has a
    version of that was read (or re-read unchanged) at or after `since`."""
    async with async_session() as session:
        rows = await session.execute(
            select(AgendaVersion.doc_role)
            .where(AgendaVersion.meeting_page_id == page_id)
            .where(AgendaVersion.last_checked_at >= since)
            .distinct()
        )
        return {r[0] for r in rows}


async def has_text(page_id: int, doc_role: str, content_hash: str) -> bool:
    """True when this page already stores this exact text for this role."""
    async with async_session() as session:
        row = await session.execute(
            select(AgendaVersion.id)
            .where(AgendaVersion.meeting_page_id == page_id)
            .where(AgendaVersion.doc_role == doc_role)
            .where(AgendaVersion.content_hash == content_hash)
            .limit(1)
        )
        return row.first() is not None


async def store_agenda_version(
    page_id: int,
    *,
    doc_role: str,
    text: str,
    content_hash: str,
    fmt: Optional[str],
    source_url: str,
    resolved_url: Optional[str],
    extractor: str,
    extractor_version: int,
) -> str:
    """Store one read. Returns "created" for text this page has not had for
    this role before, "unchanged" when the same text is already stored
    (only `last_checked_at` moves)."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        existing = (
            await session.execute(
                select(AgendaVersion).where(
                    AgendaVersion.meeting_page_id == page_id,
                    AgendaVersion.doc_role == doc_role,
                    AgendaVersion.content_hash == content_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.last_checked_at = now
            existing.resolved_url = existing.resolved_url or resolved_url
            await session.commit()
            return "unchanged"
        session.add(
            AgendaVersion(
                meeting_page_id=page_id,
                doc_role=doc_role,
                text=text,
                content_hash=content_hash,
                format=fmt,
                source_url=source_url,
                resolved_url=resolved_url,
                extractor=extractor,
                extractor_version=extractor_version,
                char_count=len(text),
                fetched_at=now,
                last_checked_at=now,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # Two Archive workers stored the same text at the same moment.
            await session.rollback()
            return "unchanged"
        return "created"


async def list_versions(page_id: int, *, include_text: bool = False) -> list[dict]:
    """One page's versions, newest first. Text only on request: a packet's
    text is large, and most callers need only the metadata."""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(AgendaVersion)
                    .where(AgendaVersion.meeting_page_id == page_id)
                    .order_by(AgendaVersion.fetched_at.desc(), AgendaVersion.id.desc())
                )
            )
            .scalars()
            .all()
        )
        out = []
        for v in rows:
            item = {
                "id": v.id,
                "doc_role": v.doc_role,
                "content_hash": v.content_hash,
                "format": v.format,
                "source_url": v.source_url,
                "resolved_url": v.resolved_url,
                "extractor": v.extractor,
                "extractor_version": v.extractor_version,
                "char_count": v.char_count,
                "fetched_at": v.fetched_at.isoformat() if v.fetched_at else None,
                "last_checked_at": (
                    v.last_checked_at.isoformat() if v.last_checked_at else None
                ),
            }
            if include_text:
                item["text"] = v.text
            out.append(item)
        return out


def recheck_cutoff(hours: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)
