from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from .engine import async_session
from .models import MeetingResolution, ProblemReport
from .outcomes import classify_outcome

VALID_ISSUE_TYPES = {"wrong_video", "bad_transcript", "wrong_metadata", "wrong_language", "other"}

# Rows past this many failed push attempts stop being retried by the
# sweep -- a permanently-broken payload (e.g. the source video got taken
# down between the original resolve and a retry) shouldn't retry forever.
# Still visible in /admin/stats' pending count either way, just no longer
# actively retried.
MAX_ARCHIVE_PUSH_ATTEMPTS = 5


async def get_cached_resolution(normalized_url: str) -> Optional[dict]:
    """Return (resolution_id, resolved_payload) for the most recent
    successful resolve of this normalized URL, or None. Bumps hit_count/
    last_seen_at on a hit -- failed/calendar/unsupported rows are never
    eligible, so a currently-broken URL always re-fetches live.

    Returns the row id too (not just the payload) so a cache-hit path
    that opportunistically re-pushes to the Archive (app/main.py) can
    mark the same durable-push tracking a fresh resolve does, rather
    than pushing blind with no way to record success.
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

        return {"resolution_id": row.id, "payload": row.resolved_payload}


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
) -> int:
    """Insert one row for a real resolve attempt. Called unconditionally
    on every branch of /api/resolve (success, calendar_page,
    unsupported_platform, resolve_failed) -- this is what makes the table
    useful as a reporting log, independent of caching.

    Returns the new row's id -- needed by the success branch to later
    mark_archive_pushed()/record_archive_push_failure() once the
    BackgroundTasks push actually runs (or to let the sweep find it if
    that push is lost). Every other branch discards it; only the
    success-with-real-content case does anything with it.
    """
    async with async_session() as session:
        row = MeetingResolution(
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
        session.add(row)
        await session.flush()  # assigns row.id
        await session.commit()
        return row.id


async def mark_archive_pushed(resolution_id: int) -> None:
    async with async_session() as session:
        row = await session.get(MeetingResolution, resolution_id)
        if row is not None:
            row.archive_pushed_at = datetime.now(timezone.utc)
            await session.commit()


async def record_archive_push_failure(resolution_id: int) -> None:
    async with async_session() as session:
        row = await session.get(MeetingResolution, resolution_id)
        if row is not None:
            row.archive_push_attempts += 1
            await session.commit()


def _worth_pushing(row: MeetingResolution) -> bool:
    if row.transcript_found:
        return True
    payload = row.resolved_payload or {}
    return bool(payload.get("agenda_items"))


async def get_pending_archive_pushes(*, min_age_minutes: int = 5, limit: int = 10) -> list[dict]:
    """Resolutions with real content that still have no confirmed Archive
    push, old enough that the fast BackgroundTasks path has clearly had
    its chance (avoids the sweep racing a push that's genuinely still
    in-flight seconds after the response returned). Consumed by
    app/main.py's opportunistic sweep and the GET /admin/sweep-pending-
    pushes admin endpoint.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=min_age_minutes)
    async with async_session() as session:
        stmt = (
            select(MeetingResolution)
            .where(
                MeetingResolution.status == "success",
                MeetingResolution.archive_pushed_at.is_(None),
                MeetingResolution.archive_push_attempts < MAX_ARCHIVE_PUSH_ATTEMPTS,
                MeetingResolution.created_at < cutoff,
            )
            .order_by(MeetingResolution.created_at.asc())
            # No SQL-level LIMIT here -- _worth_pushing() runs in Python
            # afterward (agenda_items lives in JSON, not filtered at the
            # SQL level), and a real bug found live 2026-08-10 shows why an
            # over-fetch multiplier (this used to be .limit(limit * 3))
            # isn't safe: production has plenty of "success" rows with no
            # real content (blank_transcript/no_video outcomes) mixed in
            # with real ones, so if most of the oldest N*multiplier SQL
            # matches aren't worth pushing, real candidates further down
            # the list are silently never found. Same "personal reporting
            # log, a full scan per call is fine" reasoning get_stats()
            # already uses for this table.
        )
        rows = (await session.execute(stmt)).scalars().all()

    candidates = [row for row in rows if _worth_pushing(row)][:limit]
    return [
        {
            "resolution_id": row.id,
            "input_url_normalized": row.input_url_normalized,
            "payload": row.resolved_payload,
            "attempts": row.archive_push_attempts,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in candidates
    ]


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

    # A row worth pushing (real content) that's stayed unpushed -- see
    # get_pending_archive_pushes()'s docstring for the full mechanism.
    # No age/attempts filtering here (unlike that function) -- this is a
    # visibility count, not a retry candidate list, so it should surface
    # a genuinely stuck row even after MAX_ARCHIVE_PUSH_ATTEMPTS gives up
    # retrying it.
    pending_archive_pushes = sum(
        1 for row in rows if row.status == "success" and row.archive_pushed_at is None and _worth_pushing(row)
    )

    return {
        "total_attempts": total,
        "success_rate": (success_count / total) if total else None,
        "total_cache_hits": total_hits,
        "pending_archive_pushes": pending_archive_pushes,
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
