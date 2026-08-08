from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from .engine import async_session
from .models import MeetingResolution, ProblemReport
from .outcomes import classify_outcome

VALID_ISSUE_TYPES = {"wrong_video", "bad_transcript", "wrong_metadata", "other"}


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
    """Aggregates by *content outcome* (see outcomes.classify_outcome), not
    just whether resolve() raised -- a row with a video but no transcript
    is a "blank_transcript" here, not lumped in with real successes.

    Classifies in Python rather than SQL: this table is a personal
    reporting log, not high-volume analytics, so a full scan per call is
    fine for now. Revisit (e.g. a stored outcome column, updated at write
    time) if this table grows large enough for that to matter.
    """
    async with async_session() as session:
        rows = (
            (await session.execute(select(MeetingResolution).order_by(MeetingResolution.created_at.desc())))
            .scalars()
            .all()
        )

    platform_outcome_counts: Counter = Counter()
    total_hits = 0
    durations = []
    for row in rows:
        platform_outcome_counts[(row.input_platform, classify_outcome(row))] += 1
        total_hits += row.hit_count or 0
        if row.resolve_duration_ms is not None:
            durations.append(row.resolve_duration_ms)

    total = len(rows)
    success_count = sum(count for (_, outcome), count in platform_outcome_counts.items() if outcome == "success")

    recent_problems = [row for row in rows if classify_outcome(row) != "success"][:20]

    return {
        "total_attempts": total,
        "success_rate": (success_count / total) if total else None,
        "total_cache_hits": total_hits,
        "avg_resolve_duration_ms": (sum(durations) / len(durations)) if durations else None,
        "by_platform_outcome": [
            {"platform": platform, "outcome": outcome, "count": count}
            for (platform, outcome), count in sorted(platform_outcome_counts.items())
        ],
        "recent_problems": [
            {
                "input_url": row.input_url,
                "input_platform": row.input_platform,
                "outcome": classify_outcome(row),
                "transcript_language": row.transcript_language,
                "error_message": row.error_message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in recent_problems
        ],
    }


async def list_resolutions(limit: int = 200) -> list[dict]:
    """Unaggregated per-attempt list: one entry per logged URL with its
    classified outcome, most recent first."""
    limit = max(1, min(limit, 1000))
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(MeetingResolution).order_by(MeetingResolution.created_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )

    return [
        {
            "url": row.input_url,
            "platform": row.input_platform,
            "outcome": classify_outcome(row),
            "transcript_language": row.transcript_language,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def log_problem_report(*, url: str, issue_type: str, details: Optional[str]) -> bool:
    # Returns True (not None) on success -- the caller uses safe(), which
    # itself returns None on a genuine DB failure, so this function
    # returning None on success too would make the two indistinguishable.
    async with async_session() as session:
        session.add(ProblemReport(url=url, issue_type=issue_type, details=details))
        await session.commit()
    return True


async def list_problem_reports(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 1000))
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(ProblemReport).order_by(ProblemReport.created_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )

    return [
        {
            "url": row.url,
            "issue_type": row.issue_type,
            "details": row.details,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
