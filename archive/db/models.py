from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
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

    # Mirrors ResolvedMeeting.best_effort (app/platforms/models.py): True
    # when the resolve behind this page came from generic_fallback.py's
    # best-effort page scan rather than a real, vendor-specific adapter.
    # Added 2026-08-21 (WO-21); until then the resolver sent this field on
    # every push and archive/main.py's IngestRequest silently dropped it,
    # so the Archive had no idea which of its pages were unverified --
    # `grep -rn best_effort archive/` returned nothing at all.
    #
    # NOT the same question as `platform == "unknown"`, and that
    # difference is the whole reason this column exists rather than
    # reusing the platform check: generic_fallback delegates to
    # YouTubeAssetFinder whenever it finds a YouTube embed, and that
    # result's `platform` is "youtube", not "unknown" -- the most common
    # real fallback outcome. See ResolvedMeeting.best_effort's own
    # docstring for the same warning at the resolver end.
    #
    # Three deliberate choices here, all deploy-safety related (see
    # CLAUDE.md's Alembic bullet and the 2026-08-17 UndefinedColumnError
    # outage in BACKLOG_DONE.md):
    #   * server_default, no Python-side `default=` -- an ORM insert that
    #     doesn't set the attribute omits the column from the INSERT
    #     entirely, so ingest still works against a database where the
    #     migration hasn't run yet.
    #   * deferred=True -- keeps the column out of every plain
    #     `select(MeetingPage)` (the /m/{slug} render, list_pages(), the
    #     sitemap, the hubs). Pre-migration, those all keep working
    #     untouched instead of failing on an unknown column. Unlike
    #     search_corpus's deferral this isn't about payload size (it's one
    #     boolean); nothing reads it as a loaded attribute -- the one
    #     reader, crud.list_low_trust_pages(), selects it explicitly.
    #   * crud._best_effort_available() gates both the write and the read
    #     on the column actually existing, the same feature-detect
    #     discipline crud._fts_available() uses for search_tsv, so this
    #     code and its migration are safe to deploy in either order.
    best_effort: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), deferred=True
    )

    # When a human last marked this page as reviewed in the low-trust
    # audit queue (GET /internal/low-trust-pages), NULL until someone
    # does. Added 2026-08-21 (WO-38) because that endpoint shipped as a
    # stateless JSON dump: re-reading it meant re-triaging all 474
    # production rows from scratch every time, the same failure mode the
    # Gmail triage Routine had before WO-33 gave it a ledger.
    #
    # A timestamp, not a boolean, for two reasons. It answers "when was
    # this last looked at?" -- which is what makes a stale review
    # detectable if a page is later re-ingested with different content --
    # and NULL is then the only "never reviewed" state, so the
    # ?unreviewed=true filter is a plain IS NULL with no third case.
    #
    # Deliberately NOT a filter on anything user-facing, exactly like
    # best_effort above: reviewing a page changes nothing about what the
    # site shows. The production queue is overwhelmingly pages whose
    # jurisdiction couldn't be determined -- real, live, publicly-indexed
    # meetings with real video -- not suspected spoofs, so "unreviewed"
    # must never come to mean "hide it".
    #
    # Same three deploy-safety choices as best_effort, for the same
    # reason (CLAUDE.md's Alembic bullet):
    #   * nullable with no server_default and no Python-side `default=`
    #     -- an ORM insert never names the column, so ingest keeps
    #     working against a database whose migration hasn't run yet.
    #   * deferred=True -- keeps it out of every plain
    #     `select(MeetingPage)`; the only readers select it explicitly.
    #   * crud._reviewed_at_available() gates every read and write.
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, deferred=True
    )

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


class MeetingPageThumbnail(Base):
    """One extracted video frame, stored as raw JPEG bytes, used as a
    meeting page's `og:image` / `VideoObject.thumbnailUrl` / `Event.image`
    (served by GET /m/{slug}/card.jpg).

    **Why bytes in Postgres.** Verified absent before choosing this
    (2026-08-21): this repo has no object storage, no persistent disk, no
    image-processing library, and no image column anywhere. Adding a
    vendor (S3/R2/Cloudinary) for what is ~1200 pages x one ~30-120KB
    JPEG -- the real San Carlos IQM2 mp4 measured 30KB at 640x480 -- would
    be a bigger, more permanent decision than the problem warrants. A
    plain table also *is* the cache: the unique constraint on
    `(meeting_page_id, offset_seconds)` means a per-timestamp card is
    extracted at most once and every later fetch is one indexed row read.

    **Why a row per offset rather than one per page.** The share link a
    person actually posts usually carries `?t=N` -- the moment they cared
    about -- and the card should show *that* moment, not a generic still.
    See archive/utils/video_thumbnail.py's target_offset_seconds() for the
    three targeting tiers and archive/main.py's card route for how a
    per-timestamp miss degrades to the default frame instead of failing.

    `is_default` marks the one row per page used when the request carries
    no timestamp (same one-flagged-row shape as
    TranscriptVersion.is_default) -- necessary because the default
    offset is derived from the video's real duration, which is only known
    at extraction time, so "the default frame" can't be recomputed from
    the URL alone on a later request without another ffprobe call.
    """

    __tablename__ = "meeting_page_thumbnails"
    __table_args__ = (
        UniqueConstraint(
            "meeting_page_id", "offset_seconds", name="uq_thumbnail_page_offset"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_page_id: Mapped[int] = mapped_column(
        ForeignKey("meeting_pages.id"), nullable=False, index=True
    )
    # Seconds into the video this frame was grabbed at -- the *resolved*
    # target (see target_offset_seconds()), not the raw `?t=` a visitor
    # asked for.
    offset_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )

    # deferred=True for the same load-bearing reason as
    # MeetingPage.search_corpus: this is the only column in the schema
    # holding a six-figure-byte blob, and nothing except the card route
    # itself ever wants the bytes. A relationship-less design plus
    # deferral means no /meetings, sitemap, hub or /m/{slug} query can
    # ever accidentally drag image data into memory -- the exact shape of
    # the 2026-08-17 OOM crash (see BACKLOG_DONE.md).
    image_bytes: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, deferred=True
    )
    content_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="image/jpeg"
    )
    # sha256 of image_bytes, served as the HTTP ETag so a repeat fetch
    # from a social scraper or Googlebot costs a 304 rather than a
    # re-download. Stored rather than computed per request so the bytes
    # don't have to be loaded to answer a conditional GET.
    etag: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
    # Deliberately doing two jobs at once, recorded here so it isn't
    # rediscovered as an accident: `source` is both real *provenance* and
    # the version picker's user-visible *label* (rendered through
    # archive/main.py's _SOURCE_LABELS as "English (sourced)" /
    # "English (de-duplicated)" / "English (transcribed)"). The user's
    # explicit call, 2026-08-22, over adding a separate label column and
    # the migration that needs.
    #
    # Two consequences worth knowing before adding a value here:
    #   1. Add it to _SOURCE_LABELS, or the raw token leaks to a reader.
    #   2. Only "transcribed" means AI-generated. Everything else is
    #      third-party source content and gets meeting_page.html's
    #      non-AI disclaimer via that template's `{% else %}` fallback --
    #      which is why that branch is a fallback and not an allowlist.
    #
    # Plain String(20), no enum or CHECK, so a new value needs no
    # migration -- but it does need both of the above.
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


class SocialPost(Base):
    """One row per (meeting page, network) social-media announcement --
    the dedup ledger for archive/utils/social.py's auto-posting. A row is
    inserted ("claimed") *before* the network call, so the unique
    constraint makes posting at-most-once even if the same page is
    ingested twice concurrently (e.g. the resolver's push-retry sweep
    racing a fresh resolve) -- a duplicate public post is worse than a
    silently skipped one, hence claim-first rather than post-then-record.
    A failed post keeps its row (status="failed", error populated) for
    /admin visibility rather than being retried automatically; see
    social.py's module docstring.
    """

    __tablename__ = "social_posts"
    __table_args__ = (
        UniqueConstraint("meeting_page_id", "network", name="uq_social_post_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_page_id: Mapped[int] = mapped_column(
        ForeignKey("meeting_pages.id"), nullable=False, index=True
    )
    # "bluesky" | "mastodon" -- plain string, not an enum, so a new
    # network never needs a migration (same reasoning as
    # MeetingPage.jurisdiction_confidence).
    network: Mapped[str] = mapped_column(String(20), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # The network's own identifier/permalink for the created post (an
    # at:// URI for Bluesky, the status URL for Mastodon) -- null until a
    # post actually succeeds.
    post_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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


class WorkerReportSnapshot(Base):
    """Single-row cumulative snapshot backing the worker daily activity
    report (archive/main.py's `GET /internal/send-worker-daily-report`,
    scripts/... none -- this route is the only writer/reader). Always
    exactly one row (id=1 by convention, enforced by the route always
    updating that row rather than inserting a new one) -- overwritten on
    every report send, never appended to, so this table is a snapshot,
    not a log.

    Why this exists: `TranscriptionJob.chunks_completed` is already a
    real, monotonically-increasing per-job counter (never decremented --
    see `report_chunk_result()`), so `SUM(chunks_completed)` across every
    job, ever, is a genuine all-time cumulative total with zero schema
    change needed for that part. But there's no per-chunk timestamp
    anywhere in this schema, so answering "how many chunks completed in
    the last 24h" needs *some* stored reference point to diff the current
    cumulative total against -- this table holds exactly that reference
    point (the totals as of the last report), nothing else. Cheaper and
    simpler than a real per-chunk event-log table for a single daily
    number, and avoids the alternative of parsing Render's own worker
    logs (a new external API dependency this repo doesn't otherwise have)
    just to reconstruct a count that's already implicit in existing
    columns.
    """

    __tablename__ = "worker_report_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cumulative_chunks_completed: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_jobs_completed: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MeetingHighlight(Base):
    """One precomputed, quotable moment per meeting page (plus a moment
    per curated topic present in it) -- what the state pages and
    jurisdiction hubs render as real transcript snippets with deep links.

    **Why stored rather than computed per request.** The heuristic in
    `archive/utils/highlights.py` needs the meeting's *segments*, and a
    long meeting's segment JSON is a six-figure-byte blob (San Diego's
    Board of Directors: 6,313 segments). A state page features a dozen
    meetings and a crawler walks every topic x state combination, so
    computing on demand would decode multiple megabytes per render on the
    exact surface being built *for* crawlers. Precomputing turns all of
    that into one indexed row read.

    Kept in sync from `crud._refresh_search_corpus()` -- the same single
    choke point that already recomputes `MeetingPage.search_corpus` and
    upserts `search_vocabulary`, for the same reason: every path that
    creates a TranscriptVersion already calls it, so a highlight cannot
    silently go stale the way the pre-2026-08-17 corpus did when a
    Whisper transcript finished after the page's last ingest.

    A page with no quotable transcript simply has no row here (the
    heuristic returns None for an empty, too-short, or entirely
    procedural transcript) -- every consumer treats a missing row as
    "no snippet to show" and renders without one, so this table is
    additive and nothing breaks if it is empty or lagging.
    """

    __tablename__ = "meeting_highlights"

    meeting_page_id: Mapped[int] = mapped_column(
        ForeignKey("meeting_pages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Seconds into the meeting -- a real segment's own `start`, so
    # /m/{slug}?t={int(start)} lands on the moment being quoted.
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Topic slugs (archive/topics.py) present in `text` itself -- what the
    # rendered snippet gets <mark>-highlighted for.
    topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # {topic_slug: {"start": float, "text": str}} -- the best moment for
    # each topic anywhere in the meeting, not just inside `text`. This is
    # what makes a ?topic= view a pure table read: no transcript load, no
    # per-topic scan, at request time.
    topic_moments: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # archive/topics.py's TOPICS_VERSION at compute time. A stored row
    # computed under an older phrase list is stale in a way nothing else
    # can detect, so the backfill script re-runs those rather than
    # leaving a meeting tagged for a topic whose definition has moved.
    topics_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SearchQuery(Base):
    """Every keyword typed into `/meetings`, with no user identity at all.

    Exists to answer one question the curated topic list in
    `archive/topics.py` currently answers by guesswork: *what are people
    actually looking for?* Round 1 of the topic chips ranks a hand-written
    list by corpus hits; once this table has real volume, the same chips
    can be ranked by real demand, and genuinely popular phrases missing
    from the curated list become visible instead of invisible.

    **Deliberately identity-free**: keyword, an optional jurisdiction
    filter, the result count, and a timestamp. No IP, no user id, no
    session, no user agent -- nothing that could turn a search log into a
    record of what a named person was researching, which for a site about
    scrutinizing local government is a meaningful thing not to hold.
    """

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
