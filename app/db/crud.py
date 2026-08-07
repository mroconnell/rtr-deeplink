from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from .engine import async_session
from .models import MeetingResolution


async def get_cached_resolution(normalized_url: str) -> Optional[dict]:
    """Return the most recent successful resolved_payload for this
    normalized URL, or None. Bumps hit_count/last_seen_at on a hit --
    failed/calendar/unsupported rows are never eligible, so a
    currently-broken URL always re-fetches live.
    """
    async with async_session() as session:
        stmt = (
            select(MeetingResolution)
            .where(
                MeetingResolution.input_url_normalized == normalized_url,
                MeetingResolution.status == "success",
            )
            .order_by(MeetingResolution.created_at.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalars().first()
        if row is None or row.resolved_payload is None:
            return None

        row.hit_count += 1
        row.last_seen_at = datetime.now(timezone.utc)
        await session.commit()

        return row.resolved_payload


async def log_resolution(
    *,
    input_url: str,
    input_url_normalized: str,
    input_platform: str,
    status: str,
    resolved_platform: Optional[str] = None,
    external_id: Optional[str] = None,
    error_message: Optional[str] = None,
    video_found: bool = False,
    video_format: Optional[str] = None,
    transcript_found: bool = False,
    transcript_language: Optional[str] = None,
    segment_count: Optional[int] = None,
    video_warnings: Optional[list] = None,
    transcript_warnings: Optional[list] = None,
    title: Optional[str] = None,
    date: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    resolved_payload: Optional[dict] = None,
    resolve_duration_ms: Optional[int] = None,
) -> None:
    """Insert one row for a real resolve attempt. Called unconditionally
    on every branch of /api/resolve (success, calendar_page,
    unsupported_platform, resolve_failed) -- this is what makes the table
    useful as a reporting log, independent of caching.
    """
    async with async_session() as session:
        session.add(
            MeetingResolution(
                input_url=input_url,
                input_url_normalized=input_url_normalized,
                input_platform=input_platform,
                resolved_platform=resolved_platform,
                external_id=external_id,
                status=status,
                error_message=error_message,
                video_found=video_found,
                video_format=video_format,
                transcript_found=transcript_found,
                transcript_language=transcript_language,
                segment_count=segment_count,
                video_warnings=video_warnings,
                transcript_warnings=transcript_warnings,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                resolved_payload=resolved_payload,
                resolve_duration_ms=resolve_duration_ms,
            )
        )
        await session.commit()


async def get_stats() -> dict[str, Any]:
    async with async_session() as session:
        by_platform_status = (
            await session.execute(
                select(
                    MeetingResolution.input_platform,
                    MeetingResolution.status,
                    func.count().label("count"),
                ).group_by(MeetingResolution.input_platform, MeetingResolution.status)
            )
        ).all()

        totals = (
            await session.execute(
                select(
                    func.count().label("total"),
                    func.sum(func.coalesce(MeetingResolution.hit_count, 0)).label("total_cache_hits"),
                    func.avg(MeetingResolution.resolve_duration_ms).label("avg_duration_ms"),
                )
            )
        ).one()

        recent_failures = (
            (
                await session.execute(
                    select(MeetingResolution)
                    .where(MeetingResolution.status != "success")
                    .order_by(MeetingResolution.created_at.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )

        total = totals.total or 0
        success_count = sum(count for _, status, count in by_platform_status if status == "success")

        return {
            "total_attempts": total,
            "success_rate": (success_count / total) if total else None,
            "total_cache_hits": int(totals.total_cache_hits or 0),
            "avg_resolve_duration_ms": float(totals.avg_duration_ms) if totals.avg_duration_ms is not None else None,
            "by_platform_status": [
                {"platform": platform, "status": status, "count": count}
                for platform, status, count in by_platform_status
            ],
            "recent_failures": [
                {
                    "input_url": row.input_url,
                    "input_platform": row.input_platform,
                    "status": row.status,
                    "error_message": row.error_message,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in recent_failures
            ],
        }
