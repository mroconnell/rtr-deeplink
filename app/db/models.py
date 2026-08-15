from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MeetingResolution(Base):
    """One row per real resolve attempt (insert-only) -- doubles as the
    per-adapter reporting log and, for successful rows, the read-through
    cache payload. Failed/calendar/unsupported rows are always logged but
    are never served back as a cache hit -- see app/db/crud.py.
    """

    __tablename__ = "meeting_resolutions"

    id: Mapped[int] = mapped_column(primary_key=True)

    input_url: Mapped[str] = mapped_column(Text, nullable=False)
    input_url_normalized: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    input_platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resolved_platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    video_found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    video_format: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    transcript_found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transcript_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    segment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    video_warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    transcript_warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Added 2026-08-15 (JURISDICTION_METADATA_PLAN.md) -- diagnostic only,
    # for /admin/stats visibility into extraction quality at resolve time.
    # `jurisdiction` above stays the raw, unmodified adapter output (this
    # table's whole purpose is an honest log of every resolve attempt, see
    # the class docstring); this records what
    # app/utils/jurisdiction_enrich.py's finalize_jurisdiction() would
    # score it as, WITHOUT rewriting `jurisdiction` itself -- the actual
    # repaired/split value only ever gets written to the Archive's
    # meeting_pages.jurisdiction, never here.
    jurisdiction_confidence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    resolved_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    resolve_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Durable push tracking -- real bug found 2026-08-10: the fire-and-
    # forget BackgroundTasks push to the Archive can be silently lost if
    # this process restarts (a deploy, a crash) between the response
    # being sent and the task actually running, with zero log trace of
    # the loss. archive_pushed_at is null until a push actually succeeds;
    # a periodic sweep (app/main.py) retries any row with real content
    # that's stayed null past a grace period, instead of relying on the
    # background task alone. See BACKLOG_DONE.md for the full incident.
    archive_pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_push_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProblemReport(Base):
    """A viewer-submitted "something's wrong with this meeting" report --
    crowdsourced signal pointing at a specific adapter failure, cheaper
    than manually re-testing sample cities every session. Deliberately its
    own table rather than a column on MeetingResolution: a report can come
    in from either the ephemeral resolver page or a permanent Archive page,
    and isn't tied to any one resolve attempt.
    """

    __tablename__ = "problem_reports"

    id: Mapped[int] = mapped_column(primary_key=True)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
