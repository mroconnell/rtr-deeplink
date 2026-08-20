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
    slug: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    source_url_normalized: Mapped[str] = mapped_column(
        String(2048), nullable=False, index=True
    )

    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Both added 2026-08-15 (JURISDICTION_METADATA_PLAN.md), populated by
    # app/utils/jurisdiction_enrich.py's finalize_jurisdiction() in
    # _find_or_create_page() -- never set directly from a raw adapter
    # payload. meeting_body is the entity name split off a leading
    # "<Entity> of <Jurisdiction>" shape (e.g. "Housing Authority" split
    # from "Housing Authority of the County of Santa Clara", leaving
    # `jurisdiction` as the clean "County of Santa Clara") -- null on
    # every page where no split applied, which is most of them.
    # jurisdiction_confidence is one of finalize_jurisdiction()'s
    # JurisdictionResult.confidence values ("authoritative"/"validated"/
    # "repaired"/"fallback"/"unverified"/"blank") -- a plain string
    # column, not an enum, so a new confidence tier never needs a
    # migration to add.
    meeting_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jurisdiction_confidence: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_format: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    agenda_items: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Both mirror ResolvedMeeting fields (app/platforms/models.py) that
    # never had a matching column here -- silently dropped by
    # crud.ingest_resolution() on every push until 2026-08-10 (see
    # BACKLOG_DONE.md). NOT `agenda_warnings`: that field existed only
    # briefly in an earlier session and was deliberately replaced by
    # `agenda_link` (a raw URL, not a pre-formatted sentence) before
    # anything else in the codebase started depending on it -- an earlier
    # BACKLOG.md entry describing this gap was stale on exactly this
    # point, corrected the same day this column was added.
    video_warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    agenda_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Precomputed, lowercased title+jurisdiction+agenda+all-transcript-
    # versions text (archive/utils/search.py's compute_search_corpus()) --
    # written by crud.ingest_resolution() on every ingest. Nullable because
    # pre-existing rows only get it via the one-time
    # scripts/backfill_search_corpus.py sweep. GIN-trigram-indexed on
    # Postgres by the migration that adds this column, but not via an
    # ORM-level `index=True` here -- see that migration for why. See
    # BACKLOG_DONE.md's "Search: move to a materialized/indexed column --
    # full saga, closed" entry for why this exists and
    # archive/db/crud.py's list_pages() for how it's queried.
    #
    # deferred=True is load-bearing, not an optimization: this column
    # holds every meeting's *entire* transcript text, and every
    # `select(MeetingPage)` in crud.py -- including list_pages()'s plain
    # no-keyword browse behind /meetings -- would otherwise pull all of
    # it into memory just to render 20 title rows. That is exactly what
    # OOM-crashed the Archive on 2026-08-17 the moment the backfill
    # populated the column (see BACKLOG_DONE.md). Deferred, it's only
    # ever referenced in WHERE clauses (ilike / word_similarity), which
    # never need the value loaded; nothing reads it as an attribute.
    search_corpus: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, deferred=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TranscriptVersion(Base):
    """A single transcript "take" for a MeetingPage -- a page can have
    several (different languages, a scraped vs. a future manual
    re-transcription). Exactly one row per page has is_default=True.
    """

    __tablename__ = "transcript_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_page_id: Mapped[int] = mapped_column(
        ForeignKey("meeting_pages.id"), nullable=False, index=True
    )

    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="scraped")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    segments: Mapped[list] = mapped_column(JSON, nullable=False)
    transcript_warnings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # sha256 of the concatenated segment text -- used to skip re-ingesting a
    # push that didn't actually change anything, without relying on the
    # weaker "segment count" proxy (see BACKLOG.md / plan notes).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TranscriptionJob(Base):
    """An on-demand "transcribe this meeting from audio" request and its
    progress -- created when a viewer asks for our own transcription
    because the source's own captions are missing/garbled/absent. One row
    per request; a meeting can accumulate several over time (each producing
    its own TranscriptVersion, source="transcribed"), but only one may be
    active (queued/in_progress) per MeetingPage at once -- see
    crud.create_transcription_job()'s duplicate-lock check.

    Processed by the worker/ service in chunks (see worker/main.py) so a
    multi-hour job survives a worker restart/redeploy losing at most one
    in-flight chunk -- chunks_completed/partial_segments are the durable
    checkpoint, not anything held in the worker process's own memory.
    """

    __tablename__ = "transcription_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_page_id: Mapped[int] = mapped_column(
        ForeignKey("meeting_pages.id"), nullable=False, index=True
    )

    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Set only while status == "pending_confirmation"; cleared once
    # confirmed. Not reused across jobs -- a fresh token per request.
    confirmation_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    # "pending_confirmation" -> "queued" -> "in_progress" ->
    #     "completed" | "retry_scheduled" -> ... -> "completed" | "failed"
    # A requester already in the Resend audience skips straight to
    # "queued" (see archive/utils/email.py's check_audience_membership) --
    # "pending_confirmation" only applies to a first-time email address.
    # "retry_scheduled" is a real chunk-processing budget exhaustion
    # (MAX_CONSECUTIVE_CHUNK_FAILURES) for a real user-priority job that
    # hasn't used up its retry budget yet (crud.MAX_JOB_RETRIES) -- see
    # crud.report_chunk_result()'s escalating-backoff retry, added
    # 2026-08-19 after a real user-submitted job (Redwood City, CA) died
    # on a single slow/rate-limited chunk and a later manual re-run of the
    # exact same source succeeded outright, confirming the failure wasn't
    # the source being genuinely broken. claim_next_chunk() also claims a
    # "retry_scheduled" job once next_retry_at has passed. A PRIORITY_LOW
    # auto-generated job never enters this state -- it keeps the older
    # immediate-"failed" behavior, since it already has its own separate
    # page-level escalating cooldown (AUTO_TRANSCRIPTION_BASE_COOLDOWN).
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_confirmation", index=True
    )

    # Higher claimed first (claim_next_chunk() orders by priority.desc(),
    # created_at.asc() -- FIFO within the same tier), so a real visitor's
    # request never lands behind self-generated batch work in the queue.
    # A plain int, not an enum, so a future higher tier needs no schema
    # change -- see PRIORITY_LOW/PRIORITY_MEDIUM in crud.py for the named
    # constants every call site should use instead of a raw number.
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )

    # Frozen at submit time for the feasibility-checked URL, but the worker
    # re-resolves the adapter fresh before every chunk rather than trusting
    # this indefinitely -- HLS/signed URLs can go stale over a job that
    # sits queued a while or runs long. Kept here mainly for the record and
    # as a fallback if a fresh re-resolve ever fails outright.
    media_url: Mapped[str] = mapped_column(Text, nullable=False)
    media_kind: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "audio" | "video"
    probed_duration_seconds: Mapped[float] = mapped_column(nullable=False)

    chunk_size_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    chunks_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Already timestamp-shifted (worker/segment_utils.shift_segments) to be
    # full-meeting-relative, same {start,end,text,speaker} shape as
    # TranscriptVersion.segments -- written there directly on completion,
    # no separate merge step.
    partial_segments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Stale-claim safety net against a crashed/restarted worker process,
    # not a multi-worker race (only one worker process is planned) --
    # belt-and-suspenders, not load-bearing.
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_chunk_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Last failure's message only -- kept for backward-compatible display
    # (e.g. _job_dict()'s existing "error_message" field). failure_history
    # below is the real per-attempt record; this is redundant with its
    # last entry but cheap to keep as the simple single-value case.
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Every chunk failure across this job's whole life (survives a retry
    # reset of consecutive_chunk_failures), each entry
    # {"chunk_index": int, "error": str, "at": iso8601 str} -- added
    # 2026-08-19 because error_message alone (overwritten on every
    # failure, and previously a fixed "ffmpeg extraction failed" string
    # with no real detail -- see media_probe.extract_chunk_audio()) made
    # it impossible to tell "this job failed the same way three times" from
    # "three different real problems" after the fact. Not JOIN-queried
    # anywhere, so a plain JSON column (matching partial_segments'
    # precedent above) rather than a separate table.
    failure_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # How many times this job has been rescheduled after exhausting
    # MAX_CONSECUTIVE_CHUNK_FAILURES -- see crud.MAX_JOB_RETRIES. Only
    # ever incremented for a PRIORITY_MEDIUM+ (real user-submitted) job;
    # stays 0 for a PRIORITY_LOW auto-job, which fails immediately instead.
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Set (status="retry_scheduled") when a retry is pending, cleared back
    # to NULL the moment claim_next_chunk() actually claims it. NULL in
    # every other status.
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    transcript_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transcript_versions.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


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
    url_normalized: Mapped[str] = mapped_column(
        String(2048), unique=True, nullable=False, index=True
    )
    meeting_page_id: Mapped[int] = mapped_column(
        ForeignKey("meeting_pages.id"), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SavedItem(Base):
    """A meeting or a search saved to someone's account -- phase 1 of the
    accounts feature (see BACKLOG.md's "Accounts + token billing" section
    and the plan this was built from). Auth itself is entirely external
    (Clerk, chosen 2026-08-10 specifically so this app doesn't have to
    hand-roll session/cookie security) -- `clerk_user_id` is Clerk's own
    stable user id (e.g. "user_2abc..."), never an email address. This
    table deliberately stores **no PII at all**: Clerk holds the email,
    we hold only an opaque id plus what was saved, so an account-deletion
    webhook (see app/main.py's /api/clerk/webhook) only ever needs one
    `DELETE ... WHERE clerk_user_id = ...` to fully satisfy a right-to-
    deletion request on our side.

    Unsave is a hard delete, not a status flip -- unlike TranscriptVersion
    (never deleted, just demoted), nothing else ever references a
    SavedItem row, so there's no history worth preserving.
    """

    __tablename__ = "saved_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    clerk_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # "saved_meeting" | "saved_search" -- plain String, not a SQL enum,
    # matching TranscriptionJob.status's existing convention.
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Set only for item_type == "saved_meeting".
    meeting_page_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("meeting_pages.id"), nullable=True, index=True
    )

    # Set only for item_type == "saved_search" -- the exact query-param
    # shape /meetings already accepts (q, jurisdiction, date_from, date_to,
    # has_agenda, has_transcript, fuzzy), stored verbatim so "run this
    # saved search" is just crud.list_pages(**search_params) and "show its
    # link" is just building /meetings?<the same dict>. Note: `q` maps to
    # list_pages()'s `keyword` param, not a literal **-unpack -- see
    # archive/search_alerts.py's `_run_saved_search()`.
    search_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Cursor for the saved-search alert sweep (archive/search_alerts.py) --
    # only ever meaningful for item_type == "saved_search" rows, left NULL
    # for saved_meeting. No server_default: a DB-level default would also
    # populate it on saved_meeting creation, where it means nothing.
    # crud.save_search() sets this explicitly to "now" on a genuinely new
    # row so the very first sweep only ever alerts on meetings archived
    # *after* the search was saved, never a dump of pre-existing matches.
    last_alerted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SearchVocabulary(Base):
    """Distinct real words seen anywhere in the archive's search_corpus,
    globally deduped -- no page association, unlike MeetingPage/
    TranscriptVersion's FK-linked shape. See archive/db/crud.py's
    _fuzzy_keyword_conditions_via_vocabulary() for why none is needed:
    this table only ever answers "which real words anywhere in the
    archive are close to this typo'd query term" -- the separate,
    already-fast search_corpus LIKE check (Step 1) decides whether a
    specific page actually contains one of those words.

    Populated by crud._refresh_search_corpus() (the same single choke
    point that recomputes search_corpus itself) via
    crud._upsert_vocabulary_words(), ON CONFLICT DO NOTHING since many
    pages share common words. Cross-dialect like MeetingPage.search_corpus
    (unlike search_tsv's deliberately-unmapped, Postgres-only,
    generated-column shape) because populating it needs a real
    application-level write path, not something Postgres can compute on
    its own -- so it exists on SQLite too via create_all(), keeping the
    write path dialect-agnostic and unit-testable without a live
    Postgres. Only ever *queried* on Postgres though (GIN-trigram indexed
    by this table's own migration) -- see crud._vocab_available(); fuzzy
    search stays fully Python-streamed on SQLite dev/CI, same as before
    this table existed.
    """

    __tablename__ = "search_vocabulary"

    word: Mapped[str] = mapped_column(String(255), primary_key=True)
