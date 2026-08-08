from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MeetingPage(Base):
    """One permanent, publicly-linkable page per real-world meeting.

    Identity is `(platform, external_id)` when the resolver populated
    external_id (Granicus/CivicClerk-derived platforms, including anything
    that delegates to them -- Legistar/CivicPlus/PrimeGov), else falls back
    to `source_url_normalized`. See MeetingPageUrlAlias for why lookup
    needs a third path on top of these two.
    """

    __tablename__ = "meeting_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    source_url_normalized: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)

    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_format: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    agenda_items: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TranscriptVersion(Base):
    """A single transcript "take" for a MeetingPage -- a page can have
    several (different languages, a scraped vs. a future manual
    re-transcription). Exactly one row per page has is_default=True.
    """

    __tablename__ = "transcript_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_page_id: Mapped[int] = mapped_column(ForeignKey("meeting_pages.id"), nullable=False, index=True)

    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="scraped")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    segments: Mapped[list] = mapped_column(JSON, nullable=False)
    transcript_warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # sha256 of the concatenated segment text -- used to skip re-ingesting a
    # push that didn't actually change anything, without relying on the
    # weaker "segment count" proxy (see BACKLOG.md / plan notes).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MeetingPageUrlAlias(Base):
    """Every normalized input URL that has ever successfully pushed to a
    given MeetingPage. Exists specifically so /internal/lookup -- which only
    has the raw pasted URL, not yet a platform/external_id -- can
    short-circuit for wrapper-platform URLs (Legistar/CivicPlus/PrimeGov)
    whose real identity lives on the *delegated* platform's URL, not the one
    the user actually pasted. Populated on every ingest, not just the first.
    """

    __tablename__ = "meeting_page_url_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    url_normalized: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, index=True)
    meeting_page_id: Mapped[int] = mapped_column(ForeignKey("meeting_pages.id"), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
