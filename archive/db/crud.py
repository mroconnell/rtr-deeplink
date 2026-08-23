import hashlib
import logging
import math
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence, Set
from urllib.parse import urlparse

from sqlalchemy import (
    Text,
    and_,
    cast,
    delete,
    exists,
    false,
    func,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.utils.jurisdiction_enrich import finalize_jurisdiction

from ..utils.date_status import iso_meeting_date, meeting_date_status
from ..utils.jurisdiction_format import (
    US_STATE_ABBR_TO_NAME,
    format_jurisdiction_display,
    is_canadian_abbr,
    jurisdiction_hub_slug,
    jurisdiction_search_terms,
    normalize_state_suffix,
    state_abbr_from_jurisdiction,
    state_slug_from_abbr,
)
from ..utils.language import detect_language_from_texts
from ..utils.search import (
    _fuzzy_threshold,
    _levenshtein,
    compute_search_corpus,
    find_snippet,
    matches,
    parse_query,
    tokenize,
)
from ..utils.slugify import build_base_slug, random_suffix
from ..utils.video_formats import IFRAME_EMBED_VIDEO_FORMATS
from ..utils.highlights import compute_highlight_payload, display_text
from ..topics import TOPICS, TOPICS_BY_SLUG, TOPICS_VERSION
from ..utils.gov_classify import GROUP_LABELS, GROUP_ORDER, classify_government
from ..utils.highlights import highlight_html
from ..utils.transcription_quality import detect_hallucination_warnings
from ..utils.url_normalize import normalize_url
from .engine import async_session
from .models import (
    MeetingHighlight,
    MeetingPage,
    MeetingPageThumbnail,
    MeetingPageUrlAlias,
    SavedItem,
    SearchQuery,
    SearchVocabulary,
    SocialPost,
    TranscriptionJob,
    TranscriptVersion,
    WorkerReportSnapshot,
)


def _content_hash(segments: list) -> str:
    joined = "\n".join(seg.get("text", "") for seg in segments)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# Substring shared with app/db/outcomes.py's _GARBLED_MARKER -- keep them
# matching if either message ever changes (see CLAUDE.md's note on that
# file about why this isn't accidental duplication).
_GARBLED_MARKER = "looks garbled at the source"
# Substring of archive/utils/transcription_quality.py's HALLUCINATION_WARNING
# -- a Whisper-produced transcript is a genuinely different failure mode
# than a garbled *scraped* caption (model hallucination on our own extracted
# audio, not corruption at the government source -- see that module's own
# docstring), kept as its own distinct, honestly-worded warning rather than
# folded into _GARBLED_MARKER's wording. Still needs to count as "not a
# good transcript" everywhere _GARBLED_MARKER does (re-transcription
# eligibility, the /coverage and /meetings "✓ Transcript" badges), so every
# call site below checks both markers, not just _GARBLED_MARKER alone.
_HALLUCINATION_MARKER = "hallucinated by the transcription model"
# Substring of app/platforms/granicus.py's own 36,000-cue scraped-caption
# truncation warning -- added 2026-08-23 after confirming that warning had
# never been wired into any "is this transcript good enough" check: a page
# stuck at that cap counted as permanently "done" and could never become a
# real re-transcription candidate, even though real content is genuinely
# missing past the cut-off point -- the same reader-facing problem
# _GARBLED_MARKER/_HALLUCINATION_MARKER exist to catch, just a different
# root cause (a third-party vendor's own truncation, not our own
# extraction/model failure).
_GRANICUS_TRUNCATION_MARKER = "36,000 lines, a known limit"


def _has_real_warning_free_transcript(warnings: Optional[list]) -> bool:
    """True if none of `warnings` mark this version as garbled-at-source,
    likely-hallucinated, or a truncated Granicus scraped caption -- the
    shared "is this actually a good transcript" check every call site
    below needs, factored out so a new quality marker never again needs
    updating in four separate places."""
    markers = (_GARBLED_MARKER, _HALLUCINATION_MARKER, _GRANICUS_TRUNCATION_MARKER)
    return not any(marker in w for w in (warnings or []) for marker in markers)


# sha256 of the empty string: what _content_hash() yields for a version
# whose segments are [] or all-empty-text. Both paths that create a
# TranscriptVersion (ingest_resolution(), report_chunk_result()) set
# content_hash via _content_hash(), so "has real content" is decidable
# from this indexed 64-char column without ever reading `segments` --
# which matters: segments is the full transcript JSON (102MB across
# prod's default versions, 2026-08-17), and reading it just to test
# emptiness was what made _has_good_transcript()'s callers the #1
# consumer of production DB time (see BACKLOG_DONE.md).
_EMPTY_CONTENT_HASH = _content_hash([])


def _good_default_transcript_exists():
    """SQL `EXISTS` for "this MeetingPage has a real, non-garbled,
    non-truncated default transcript" -- the same decision _has_good_
    transcript() makes, as a correlated subquery usable in a WHERE clause,
    and touching only is_default / content_hash / transcript_warnings,
    never `segments`. transcript_warnings is a small JSON list; all three
    quality markers are plain ASCII substrings so a text-cast LIKE is
    exact on both Postgres (json::text is the stored text verbatim) and
    SQLite. NULL warnings means "no warnings", i.e. good -- guarded
    explicitly, since `NOT (NULL LIKE ...)` is NULL and would silently
    drop those rows."""
    warnings_text = cast(TranscriptVersion.transcript_warnings, Text)
    return exists().where(
        TranscriptVersion.meeting_page_id == MeetingPage.id,
        TranscriptVersion.is_default.is_(True),
        TranscriptVersion.content_hash != _EMPTY_CONTENT_HASH,
        or_(
            TranscriptVersion.transcript_warnings.is_(None),
            and_(
                ~warnings_text.like(f"%{_GARBLED_MARKER}%"),
                ~warnings_text.like(f"%{_HALLUCINATION_MARKER}%"),
                ~warnings_text.like(f"%{_GRANICUS_TRUNCATION_MARKER}%"),
            ),
        ),
    )


async def _has_good_transcript(session, meeting_page_id: int) -> bool:
    """True if this page's default TranscriptVersion has real, non-garbled
    content -- used to pick the Archive recheck cadence (see
    ARCHIVE_RECHECK_AFTER's has_transcript branch in app/main.py): a page
    missing a real transcript benefits from being rechecked often, since
    the government source's own captions may catch up at any time; a page
    that already has a good one doesn't. Reads only content_hash +
    transcript_warnings -- see _EMPTY_CONTENT_HASH for why not segments;
    keep this and _good_default_transcript_exists() making the same
    decision."""
    row = (
        await session.execute(
            select(
                TranscriptVersion.content_hash, TranscriptVersion.transcript_warnings
            ).where(
                and_(
                    TranscriptVersion.meeting_page_id == meeting_page_id,
                    TranscriptVersion.is_default.is_(True),
                )
            )
        )
    ).first()
    if row is None or row[0] == _EMPTY_CONTENT_HASH:
        return False
    return _has_real_warning_free_transcript(row[1])


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
            (
                await session.execute(
                    select(MeetingPageUrlAlias).where(
                        MeetingPageUrlAlias.url_normalized == url_normalized
                    )
                )
            )
            .scalars()
            .first()
        )
        if alias:
            page = await session.get(MeetingPage, alias.meeting_page_id)
            if page:
                return {
                    "slug": page.slug,
                    "url": f"/m/{page.slug}",
                    "updated_at": page.updated_at.isoformat(),
                    "has_transcript": await _has_good_transcript(session, page.id),
                }

        page = (
            (
                await session.execute(
                    select(MeetingPage).where(
                        MeetingPage.source_url_normalized == url_normalized
                    )
                )
            )
            .scalars()
            .first()
        )
        if page:
            return {
                "slug": page.slug,
                "url": f"/m/{page.slug}",
                "updated_at": page.updated_at.isoformat(),
                "has_transcript": await _has_good_transcript(session, page.id),
            }

    return None


async def _find_existing_page(
    session,
    *,
    platform: str,
    external_id: Optional[str],
    source_url_normalized: str,
    input_url_normalized: str,
) -> Optional[MeetingPage]:
    alias = (
        (
            await session.execute(
                select(MeetingPageUrlAlias).where(
                    MeetingPageUrlAlias.url_normalized == input_url_normalized
                )
            )
        )
        .scalars()
        .first()
    )
    if alias:
        page = await session.get(MeetingPage, alias.meeting_page_id)
        if page:
            return page

    if external_id:
        # NOTE: external_id is trusted as-is for this match -- it must
        # already be globally unique across every real source it can come
        # from, not just unique within one adapter's own output. A bare
        # per-customer clip/event number on a multi-tenant platform (e.g.
        # civicclerk.py's/granicus.py's own event/clip IDs, which restart
        # near 1 for every separate customer) is NOT globally unique and
        # must be host-namespaced by the adapter itself -- see those two
        # files' own external_id comments for the real, confirmed-live
        # 2026-08-18 incident this describes (multiple unrelated cities
        # silently merged onto one row, each overwriting the other's
        # title/date/jurisdiction, see BACKLOG.md).
        #
        # A netloc cross-check was tried here as a second line of defense
        # and reverted: `source_url` is *deliberately* set to a different
        # host than the real content for two legitimate existing cases --
        # legistar.py's `fallback.source_url = url` keeps the original
        # Legistar URL while platform/external_id point at the real
        # Granicus host, and primegov.py's
        # `YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)`
        # does the same for the original PrimeGov URL vs. youtube.com. A
        # netloc check would have silently broken both of those intended
        # cross-host merges into duplicate pages instead. Globally-unique
        # external_id at the adapter level is the real fix; there's no
        # cheap, generic way to also verify it here.
        page = (
            (
                await session.execute(
                    select(MeetingPage).where(
                        MeetingPage.platform == platform,
                        MeetingPage.external_id == external_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if page:
            return page

    return (
        (
            await session.execute(
                select(MeetingPage).where(
                    MeetingPage.source_url_normalized == source_url_normalized
                )
            )
        )
        .scalars()
        .first()
    )


async def _ensure_alias(session, url_normalized: str, meeting_page_id: int) -> None:
    existing = (
        (
            await session.execute(
                select(MeetingPageUrlAlias).where(
                    MeetingPageUrlAlias.url_normalized == url_normalized
                )
            )
        )
        .scalars()
        .first()
    )
    if not existing:
        session.add(
            MeetingPageUrlAlias(
                url_normalized=url_normalized, meeting_page_id=meeting_page_id
            )
        )


# --- best_effort column feature-detect -----------------------------------
#
# meeting_pages.best_effort is a real, mapped column (unlike search_tsv),
# but it's brand new as of 2026-08-21 and every reference to it -- the
# ingest write below and list_low_trust_pages()'s read -- goes through
# this gate, so the code and its Alembic migration are safe to deploy in
# either order. Byte-for-byte the same caching/TTL shape as
# _fts_available() above; see MeetingPage.best_effort's own comment for
# the two other halves of that safety (server_default + deferred=True).

_BEST_EFFORT_CHECK_TTL = timedelta(seconds=60)
_best_effort_state: dict[str, Any] = {"available": None, "checked_at": None}
_reviewed_at_state: dict[str, Any] = {"available": None, "checked_at": None}


async def _meeting_pages_column_available(session, column: str, state: dict) -> bool:
    """True when `meeting_pages.<column>` really exists on the connected
    database. Shared body for the ordinary-column feature-detects below.

    Inverted relative to _fts_available() on the SQLite branch, and
    deliberately so: search_tsv is a Postgres-only generated column that
    SQLite can never have, whereas these are ordinary cross-dialect
    columns that dev/CI's SQLite gets from create_all() built straight off
    today's model -- so on SQLite they are always present by construction
    and there's nothing to detect. Only Postgres, where the schema is
    migration-driven and can genuinely lag the code by one deploy, needs
    the information_schema lookup. Cached per-column for
    _BEST_EFFORT_CHECK_TTL so running the migration against a live service
    flips it on within a minute with no restart.
    """
    if session.bind.dialect.name != "postgresql":
        return True
    now = datetime.now(timezone.utc)
    checked_at = state["checked_at"]
    if checked_at is not None and now - checked_at < _BEST_EFFORT_CHECK_TTL:
        return bool(state["available"])
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'meeting_pages' AND column_name = :column"
            ),
            {"column": column},
        )
    ).first()
    state["available"] = row is not None
    state["checked_at"] = now
    return bool(state["available"])


async def _best_effort_available(session) -> bool:
    """True when meeting_pages.best_effort really exists (2026-08-21,
    WO-21). See MeetingPage.best_effort's comment for the two other halves
    of the deploy safety this gate is one third of."""
    return await _meeting_pages_column_available(
        session, "best_effort", _best_effort_state
    )


async def _reviewed_at_available(session) -> bool:
    """True when meeting_pages.reviewed_at really exists (2026-08-21,
    WO-38). Same gate, one migration later: list_low_trust_pages()'s read
    and mark_low_trust_pages_reviewed()'s write both go through it, so
    that code and its migration are safe to deploy in either order."""
    return await _meeting_pages_column_available(
        session, "reviewed_at", _reviewed_at_state
    )


async def _unique_slug(session, base: str) -> str:
    slug = base
    for _ in range(5):
        existing = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        if not existing:
            return slug
        slug = f"{base}-{random_suffix()}"
    # Exhausted retries (astronomically unlikely) -- fall back to a longer
    # random suffix rather than looping forever.
    return f"{base}-{random_suffix(12)}"


async def _find_or_create_page(
    session, payload: dict[str, Any], input_url_normalized: str
) -> tuple[MeetingPage, bool]:
    """Shared by ingest_resolution() and create_transcription_job() -- both
    need "find this meeting's permanent page, or create one if this is the
    first thing that's ever landed for it" from the same resolver-payload
    shape. Extracted 2026-08-08 when the transcription feature needed the
    exact same logic ingest_resolution() already had inline.

    Returns (page, created) -- `created` is True only when this call
    built a brand-new page rather than matching an existing one. The
    social auto-posting hook (archive/utils/social.py) keys off this so
    re-ingests (the resolver's push-retry sweep, the backfill script
    re-resolving the whole corpus) can never announce an old page again.
    """
    platform = payload["platform"]
    external_id = payload.get("external_id")
    source_url_normalized = normalize_url(payload["source_url"])
    jurisdiction = normalize_state_suffix(payload.get("jurisdiction"))
    # finalize_jurisdiction() runs AFTER normalize_state_suffix() on
    # purpose -- it expects an already-2-letter state suffix (e.g. "City
    # of Boston, MA"), not a full state name ("Massachusetts"), so
    # validation/repair/split has a clean value to work with. See
    # JURISDICTION_METADATA_PLAN.md for the design and BACKLOG.md's
    # "Census-table baseline validation" entry for the real data this was
    # tuned against. Cross-package import (archive/ -> app/) mirrors the
    # same boundary worker/main.py already crosses -- jurisdiction_enrich
    # is a pure utility module (stdlib + CSV data only), not FastAPI/
    # app-server-specific.
    jx_result = finalize_jurisdiction(
        jurisdiction, netloc=urlparse(source_url_normalized).netloc
    )
    jurisdiction = jx_result.jurisdiction

    page = await _find_existing_page(
        session,
        platform=platform,
        external_id=external_id,
        source_url_normalized=source_url_normalized,
        input_url_normalized=input_url_normalized,
    )

    created = page is None
    if page is None:
        base_slug = build_base_slug(
            jurisdiction or "", payload.get("date") or "", payload.get("title") or ""
        )
        slug = await _unique_slug(session, base_slug)
        page = MeetingPage(
            slug=slug,
            platform=platform,
            external_id=external_id,
            source_url_normalized=source_url_normalized,
            title=payload.get("title"),
            date=payload.get("date"),
            jurisdiction=jurisdiction,
            # An adapter that names the governing body itself (Granicus's
            # RSS channel title, 2026-08-23) beats the split-from-
            # jurisdiction fallback finalize_jurisdiction() produces.
            meeting_body=payload.get("meeting_body") or jx_result.meeting_body,
            jurisdiction_confidence=jx_result.confidence,
            video_url=payload.get("video_url"),
            video_format=payload.get("video_format"),
            agenda_items=payload.get("agenda_items") or [],
            video_warnings=payload.get("video_warnings") or [],
            agenda_link=payload.get("agenda_link"),
        )
        # Set only when both true, never as a constructor kwarg: an
        # unset attribute is omitted from the INSERT and the column's
        # server_default supplies False, so an ingest against a database
        # where the migration hasn't landed yet still succeeds (see
        # MeetingPage.best_effort's comment).
        if payload.get("best_effort") and await _best_effort_available(session):
            page.best_effort = True
        session.add(page)
        await session.flush()  # assigns page.id
    else:
        # Keep page-level fields fresh (title/video/agenda can improve
        # on a later, better resolve) without touching the slug.
        #
        # Real bug fixed 2026-08-16: `platform` was never in this list --
        # every other content field refreshed on re-ingest, but a page
        # created before its adapter existed (or before an adapter fix
        # landed, e.g. escribe.py's/civicclerk.py's YouTube-delegation
        # fix) stayed frozen at whatever platform value it had on first
        # creation forever, even once the content itself was demonstrably
        # fixed by a later re-ingest. Confirmed live: 3 TelVue pages kept
        # showing platform="unknown" after building telvue.py and
        # re-ingesting them, despite real segments/agenda_items/video_url
        # all having updated correctly. Safe to always trust the fresh
        # payload's platform (not truthy-gated like the others) --
        # `payload["platform"]` is never blank, and confirmed every
        # partial-push caller (scripts/fetch_youtube_transcripts.py)
        # already echoes the page's own current platform back rather
        # than hardcoding something else, so this can't regress an
        # already-correct page.
        page.platform = payload.get("platform") or page.platform
        page.title = payload.get("title") or page.title
        page.date = payload.get("date") or page.date
        page.jurisdiction = jurisdiction or page.jurisdiction
        # meeting_body/jurisdiction_confidence only refresh alongside a
        # real new jurisdiction value -- same truthy-gated pattern as
        # jurisdiction itself just above, so a later resolve with no
        # jurisdiction at all can't silently wipe a previously-split body.
        if jurisdiction:
            page.meeting_body = jx_result.meeting_body
            page.jurisdiction_confidence = jx_result.confidence
        # Truthy-gated like every other refresh field above: an adapter
        # that names the governing body itself overrides both the stored
        # value and the jurisdiction-split fallback just applied, but a
        # payload that omits it (every partial transcript-only pusher)
        # can never clear one.
        if payload.get("meeting_body"):
            page.meeting_body = payload["meeting_body"]
        page.video_url = payload.get("video_url") or page.video_url
        page.video_format = payload.get("video_format") or page.video_format
        if payload.get("agenda_items"):
            page.agenda_items = payload["agenda_items"]
        # Same truthy-gated pattern as agenda_items just above, not an
        # unconditional overwrite -- a partial ingest payload that omits
        # these fields entirely (e.g. scripts/fetch_youtube_transcripts.py's
        # transcript-only push) defaults to []/None via Pydantic, and an
        # unconditional overwrite would silently wipe a real warning/link
        # a fuller earlier resolve had found. Same accepted tradeoff
        # agenda_items already has: a warning that's since been resolved
        # won't auto-clear until a fuller re-resolve explicitly says so.
        if payload.get("video_warnings"):
            page.video_warnings = payload["video_warnings"]
        page.agenda_link = payload.get("agenda_link") or page.agenda_link
        # Truthy-gated, i.e. this flag can be *set* by a re-ingest but
        # never cleared by one -- same shape as agenda_items /
        # video_warnings just above, and for the same concrete reason,
        # sharpened by what this particular field means. Every
        # transcript-only pusher (scripts/fetch_youtube_transcripts.py,
        # transcribe_backlog_locally.py, retranscribe_first_chunk.py)
        # sends a partial payload with no best_effort key at all, which
        # IngestRequest defaults to False; an unconditional overwrite
        # would let any of them silently un-flag a genuinely unverified
        # page. For a trust signal specifically, erring toward
        # still-flagged is the safe direction -- a stale True costs one
        # extra row in the /internal/low-trust-pages review queue, while
        # a wrongly-cleared True is exactly the blind spot this whole
        # column exists to close. Accepted residual (logged in
        # BACKLOG.md): a page later re-resolved by a real adapter keeps
        # the flag until a human clears it, so the queue needs pruning by
        # hand rather than draining itself.
        if payload.get("best_effort") and await _best_effort_available(session):
            page.best_effort = True
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
    return page, created


def _is_real_improvement(
    current_default: TranscriptVersion, new_language: Optional[str]
) -> bool:
    """True if a freshly-created TranscriptVersion (which always has real
    segments -- ingest_resolution() only creates one `if segments:`) is a
    genuine improvement over the page's current default, and should be
    promoted over it. Narrowly scoped to the two confirmed real cases
    (see BACKLOG_DONE.md): the default had no real segments at all, or it
    had segments but no detected language and the fresh one has one
    (exactly the Dublin, CA bug -- a Swagit page ingested before language
    detection was wired up for that adapter). Deliberately *not* a
    blanket "always promote the newest" rule -- if the current default
    already has both real segments and a language, a fresh duplicate-ish
    version isn't confidently better, so it's left alone rather than
    flip-flopping the default unpredictably.
    """
    if not current_default.segments:
        return True
    return not current_default.language and bool(new_language)


def _default_looks_like_copied_agenda(
    current_default: TranscriptVersion, agenda_items: list
) -> bool:
    """True if the page's current default TranscriptVersion is actually
    just a copy of the meeting's agenda items, not a genuine transcript --
    a real, confirmed historical bug (see BACKLOG_DONE.md's Yountville
    entry) from a since-removed code path that briefly folded
    `agenda_items` into `segments`. Detected structurally (same count,
    identical text in the same order) against the *freshly resolved*
    agenda_items in this ingest's own payload, rather than by matching
    old warning-message text -- a structural check generalizes to any
    page with the same underlying data shape, not just the one page this
    bug was first found on.
    """
    seg_texts = [s.get("text") for s in (current_default.segments or [])]
    agenda_texts = [a.get("text") for a in (agenda_items or [])]
    return bool(seg_texts) and seg_texts == agenda_texts


# Real incident, 2026-08-18: scripts/backfill_search_vocabulary.py passed
# an entire 200-page batch's *union* of distinct words -- 62,000+ of them
# -- to one call, which built one INSERT with one bound parameter per
# word and hit PostgreSQL's hard 65535-bound-parameters-per-statement
# protocol limit. A single ingest_resolution() call (one page's words,
# a few hundred to a couple thousand) never came close, so this had never
# been exercised before the backfill script's batch-sized calls existed.
# Chunked here, in the shared helper, so every caller is protected, not
# just the one that happened to trigger it -- 2000 is comfortably under
# the hard limit with room for other statements on the same connection,
# not tuned against any real measured ceiling.
_VOCAB_UPSERT_CHUNK_SIZE = 2000


async def _upsert_vocabulary_words(session, words: set) -> None:
    """Inserts any of `words` not already in `search_vocabulary`, ignoring
    duplicates -- many pages share common words, and the table is a
    distinct, page-agnostic set (see SearchVocabulary's docstring for
    why no page association is needed). Dialect-dispatched because
    `ON CONFLICT DO NOTHING` needs the dialect-specific `insert()`
    construct; runs on both SQLite and Postgres so the write path stays
    dialect-agnostic and testable without a live Postgres, same
    principle as search_corpus itself -- only the *query* side
    (crud._vocab_available()) is Postgres-only.
    """
    # No real English word or plausible transcription token is anywhere
    # near this long -- guards against a pathological run (a pasted URL,
    # an ID string with no whitespace) exceeding the word column's
    # String(255) and failing the whole ingest transaction on Postgres.
    words = sorted({w for w in words if len(w) <= 255})
    if not words:
        return
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    for start in range(0, len(words), _VOCAB_UPSERT_CHUNK_SIZE):
        chunk = words[start : start + _VOCAB_UPSERT_CHUNK_SIZE]
        stmt = (
            dialect_insert(SearchVocabulary)
            .values([{"word": w} for w in chunk])
            .on_conflict_do_nothing()
        )
        await session.execute(stmt)


async def _refresh_search_corpus(session, page: MeetingPage) -> None:
    """Recompute `page.search_corpus` from the page's current metadata +
    every linked TranscriptVersion's segments (flushed, not necessarily
    committed -- runs inside the caller's session). Must be called from
    every path that creates a TranscriptVersion or changes title/
    jurisdiction/agenda_items -- as of 2026-08-17 that's
    ingest_resolution() and the worker's transcription-completion path in
    report_chunk_result(). The latter was a real gap found the same day
    the SQL-side search shipped: a Whisper transcript that finished after
    a page's last ingest never made it into the corpus, so on Postgres
    (where the corpus is the authoritative match, see list_pages()) that
    meeting's transcript text was silently unsearchable until something
    re-ingested the page.

    Also upserts the corpus's distinct real words into `search_vocabulary`
    (Search Step 2b) -- the same choke point that keeps search_corpus
    itself in sync is the natural place to keep the vocabulary in sync
    too, rather than duplicating this call at both real call sites.
    """
    all_segments = (
        (
            await session.execute(
                select(TranscriptVersion.segments).where(
                    TranscriptVersion.meeting_page_id == page.id
                )
            )
        )
        .scalars()
        .all()
    )
    page.search_corpus = compute_search_corpus(
        page.title, page.jurisdiction, page.agenda_items, all_segments
    )
    await _upsert_vocabulary_words(session, tokenize(page.search_corpus))
    await _refresh_meeting_highlight(session, page, all_segments)


async def _refresh_meeting_highlight(session, page: MeetingPage, all_segments) -> None:
    """Recompute this page's stored `meeting_highlights` row from the
    segments `_refresh_search_corpus()` just gathered.

    Same choke-point argument as the vocabulary upsert above, and folded
    into the same call for the same reason: every path that creates a
    TranscriptVersion already reaches here, so a page cannot end up with
    a transcript and no highlight (or, worse, a highlight quoting a
    transcript that has since been replaced).

    **Non-fatal by construction, including the database write.** A
    highlight is page *decoration* -- the state/hub pages render fine
    without one, and the backfill script picks up anything missing --
    while this function runs inside the *ingest* transaction. Letting it
    fail an ingest would trade a missing snippet for a lost transcript,
    which is a strictly worse outcome.

    That guarantee needs a SAVEPOINT, not just a `try`. On Postgres a
    failed statement poisons the surrounding transaction until it is
    rolled back, so catching the exception here and continuing would
    still fail at the caller's `commit()` -- the transcript would be lost
    anyway, just with a more confusing traceback. `begin_nested()` scopes
    the damage: the savepoint rolls back, the outer ingest transaction
    survives intact, and the page simply has no highlight until the next
    ingest or backfill run.
    """
    logger = logging.getLogger(__name__)
    try:
        payload = compute_highlight_payload(all_segments)
    except Exception:  # pragma: no cover - defensive, see docstring
        logger.exception("highlight computation failed for page id=%s", page.id)
        return

    highlight = payload["highlight"]
    if highlight is None:
        # Nothing quotable (empty/short/all-procedural transcript). Drop
        # any previous row rather than leaving a stale quote behind -- a
        # re-transcription that got *worse* must not keep showing the
        # old text as if it were current.
        try:
            async with session.begin_nested():
                await session.execute(
                    delete(MeetingHighlight).where(
                        MeetingHighlight.meeting_page_id == page.id
                    )
                )
        except Exception:  # pragma: no cover - defensive, see docstring
            logger.exception("highlight delete failed for page id=%s", page.id)
        return

    values = {
        "meeting_page_id": page.id,
        "start_seconds": highlight["start"],
        "text": highlight["text"],
        "topics": highlight["topics"],
        "topic_moments": payload["topic_moments"],
        "topics_version": TOPICS_VERSION,
        "computed_at": datetime.now(timezone.utc),
    }
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    stmt = dialect_insert(MeetingHighlight).values(**values)
    try:
        async with session.begin_nested():
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[MeetingHighlight.meeting_page_id],
                    set_={k: v for k, v in values.items() if k != "meeting_page_id"},
                )
            )
    except Exception:  # pragma: no cover - defensive, see docstring
        logger.exception("highlight write failed for page id=%s", page.id)


async def ingest_resolution(payload: dict[str, Any], input_url_normalized: str) -> dict:
    """Create a MeetingPage (or attach a new TranscriptVersion to an
    existing one) from a resolver push. `payload` is the resolver's
    ResolvedMeeting.model_dump() shape: platform, source_url, external_id,
    title, date, jurisdiction, video_url, video_format, segments,
    agenda_items, transcript_language, transcript_warnings, best_effort.
    `source` is an
    optional extra key (not part of ResolvedMeeting itself -- Archive-only)
    defaulting to "scraped" when absent, same as every existing caller
    (the resolver's own push, bulk_ingest.py, fetch_youtube_transcripts.py
    all omit it). scripts/transcribe_backlog_locally.py is the one real
    caller that sets it to "transcribed" explicitly -- without this,
    locally-Whisper-transcribed content pushed through this same endpoint
    would silently get labeled "scraped" (a real government caption),
    losing the meeting_page.html disclaimer and other source=="transcribed"
    -gated behavior real self-transcribed content already gets when the
    worker writes it directly (see report_chunk_result() below) -- a
    hallucination-risk mislabeling this repo has already flagged as a real
    reputational concern (BACKLOG.md's "tiny" quality findings), not a
    cosmetic one.

    Also handles promoting/demoting the page's default TranscriptVersion
    when warranted -- see _is_real_improvement() and
    _default_looks_like_copied_agenda() above, and BACKLOG_DONE.md for
    the two real bugs (Dublin, Yountville) this closes. Only ever touches
    an *existing* default; a brand-new page's first version is already
    is_default=True from creation, nothing more to do.
    """
    segments = payload.get("segments") or []
    agenda_items = payload.get("agenda_items") or []
    source = payload.get("source") or "scraped"

    async with async_session() as session:
        page, page_created = await _find_or_create_page(
            session, payload, input_url_normalized
        )

        current_default = (
            (
                await session.execute(
                    select(TranscriptVersion).where(
                        TranscriptVersion.meeting_page_id == page.id,
                        TranscriptVersion.is_default.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )

        new_version_id = None
        # Tracks whichever TranscriptVersion this push's content actually
        # corresponds to -- either the id of one freshly created here, or
        # (when a content-hash duplicate already exists, e.g. re-running
        # this same transcription a second time) that existing version's
        # id. Kept as a separate variable from new_version_id on purpose:
        # the auto-promotion check right below must still only ever fire
        # for a genuinely *new* version (new_version_id), never re-promote
        # an old duplicate just because it was pushed again -- but a caller
        # asking "what version does this push correspond to" (e.g.
        # scripts/transcribe_backlog_locally.py's --promote) needs an id
        # either way. Real gap this closes, found live re-transcribing
        # Boulder County (see BACKLOG_DONE.md): the fixed transcript's
        # content already matched a non-default version from an earlier
        # real (non-dry-run) push during the original bug investigation,
        # so nothing "new" was created on this call, but there was still a
        # real, promotable version to point at.
        matched_version_id = None

        if segments:
            language = payload.get("transcript_language")
            content_hash = _content_hash(segments)

            # Dedup is scoped to the same `source` value too -- otherwise
            # a "transcribed" push could never dedup against an earlier
            # identical "transcribed" push (it would only ever check
            # against "scraped" rows), creating a fresh duplicate version
            # every time the same meeting gets re-transcribed with the
            # same result.
            duplicate = (
                (
                    await session.execute(
                        select(TranscriptVersion).where(
                            TranscriptVersion.meeting_page_id == page.id,
                            TranscriptVersion.language == language,
                            TranscriptVersion.source == source,
                            TranscriptVersion.content_hash == content_hash,
                        )
                    )
                )
                .scalars()
                .first()
            )

            if duplicate is None:
                any_version = (
                    (
                        await session.execute(
                            select(TranscriptVersion).where(
                                TranscriptVersion.meeting_page_id == page.id
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                version = TranscriptVersion(
                    meeting_page_id=page.id,
                    language=language,
                    source=source,
                    is_default=any_version is None,
                    segments=segments,
                    transcript_warnings=payload.get("transcript_warnings") or [],
                    content_hash=content_hash,
                )
                session.add(version)
                await session.flush()  # assigns version.id
                new_version_id = version.id
                matched_version_id = version.id
            else:
                matched_version_id = duplicate.id

        if current_default is not None:
            if new_version_id is not None and _is_real_improvement(
                current_default, payload.get("transcript_language")
            ):
                await promote_transcript_version(session, page.id, new_version_id)
            elif new_version_id is None and _default_looks_like_copied_agenda(
                current_default, agenda_items
            ):
                current_default.is_default = False

        # Recomputed unconditionally on every ingest, not just when a new
        # version is created -- cheap (one extra indexed SELECT), and
        # simpler than special-casing "did anything relevant change".
        # Covers every trigger case: page.title/jurisdiction/agenda_items
        # were already updated above via _find_or_create_page(), and any
        # new TranscriptVersion is already flushed above, so this SELECT
        # sees fresh state for both. Promotion/demotion alone never
        # changes this: the corpus covers every version's text regardless
        # of is_default (see list_pages()'s docstring), so which version
        # is currently default doesn't affect what's in the corpus.
        await _refresh_search_corpus(session, page)

        await session.commit()
        # version_id is matched_version_id above: the TranscriptVersion this
        # push's content corresponds to (freshly created or an existing
        # content-hash duplicate), or None when there were no segments to
        # ingest at all. Added 2026-08-16: previously nothing surfaced this
        # at all, a real gap hit re-transcribing Boulder County/Port
        # Coquitlam after the seam-duplication/phase-cancellation fixes (see
        # BACKLOG_DONE.md) -- promoting the relevant version requires its
        # id, and the page's existing default already has segments+
        # language, so _is_real_improvement() alone won't auto-promote a
        # fresh push.
        # page_id/created: consumed by /internal/ingest's social
        # auto-posting hook (archive/main.py + archive/utils/social.py) --
        # `created` is the only signal that distinguishes "a brand-new
        # permanent page just came into existence" from the far more
        # common re-ingest of an existing one. Extra keys are harmless to
        # every pre-existing caller (they read slug/url/version_id only).
        return {
            "slug": page.slug,
            "url": f"/m/{page.slug}",
            "version_id": matched_version_id,
            "page_id": page.id,
            "created": page_created,
        }


async def claim_social_post(meeting_page_id: int, network: str) -> Optional[int]:
    """Insert the dedup row for a (page, network) announcement *before*
    any network call is made -- returns the new row's id, or None when a
    row already exists (someone else already claimed/posted this target).
    Claim-first is the whole point of the SocialPost table (see its model
    docstring): the unique constraint turns a race between two concurrent
    ingests of the same brand-new page into one post and one silent skip,
    never two public posts.
    """
    async with async_session() as session:
        row = SocialPost(
            meeting_page_id=meeting_page_id, network=network, status="pending"
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            return None
        return row.id


async def finish_social_post(
    post_id: int,
    *,
    status: str,
    post_uri: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Record how a claimed announcement actually went ("posted" with the
    network's own permalink, or "failed" with the error text). A "failed"
    row deliberately keeps its claim -- no automatic retry loop reposts
    it -- so a transient network error costs one missed announcement, not
    a risk of duplicates; see archive/utils/social.py's module docstring
    for that tradeoff.
    """
    async with async_session() as session:
        row = await session.get(SocialPost, post_id)
        if row is None:
            return
        row.status = status
        row.post_uri = post_uri
        row.error = error
        await session.commit()


async def list_all_page_urls() -> list[dict]:
    """Every archived page's identity fields -- the backfill sweep's
    starting point (scripts/backfill_archived_pages.py), for re-resolving
    every page fresh so already-shipped adapter/jurisdiction fixes reach
    pages archived before they existed, not just new resolves going
    forward. `MeetingPage.jurisdiction` (and every other field) is only
    ever set at ingest time -- nothing re-checks an already-archived page
    on its own, confirmed live 2026-08-13 against seven real, separate
    jurisdiction bugs that were already fixed in code but still showing
    the old wrong value because the pages themselves were never
    re-resolved (see BACKLOG.md's "archived pages don't self-heal" entry).

    Returns exactly what the resolver's own `_recheck_archived_page()`
    (app/main.py) needs: the real source URL to re-resolve, and the
    platform to pick the right adapter -- same shape convention as
    `list_youtube_pages_missing_transcripts()` above.
    """
    async with async_session() as session:
        pages = (
            (
                await session.execute(
                    select(MeetingPage).order_by(MeetingPage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        return [
            {
                "slug": page.slug,
                "title": page.title,
                "platform": page.platform,
                "source_url_normalized": page.source_url_normalized,
                # Added 2026-08-22 for scripts/dedupe_rollup_transcripts.py,
                # whose whole affected population is "archived before WO-34
                # shipped" -- a page first archived after that date was
                # necessarily parsed with dedupe_rollup_cues() already in
                # place, so an ingest-date bound is what keeps that sweep's
                # candidate set from being every page on four platforms.
                # Free here (no extra query, no segments blob touched) and
                # purely additive for the existing consumer, which reads
                # slug/platform/source_url_normalized only.
                "created_at": page.created_at.isoformat() if page.created_at else None,
            }
            for page in pages
        ]


async def list_youtube_pages_missing_transcripts() -> list[dict]:
    """Every archived YouTube-backed meeting page with no *good* default
    transcript -- the "transcript wanted" queue consumed by
    scripts/fetch_youtube_transcripts.py. YouTube-only because that's the
    one platform whose captions this service structurally can't fetch
    itself: confirmed live 2026-08-10 that even youtube-transcript-api
    (a different endpoint/recipe from the already-blocked yt-dlp and
    timedtext paths) gets IpBlocked from Render's cloud IP while working
    fine from a residential one, so fetching happens off-server and gets
    pushed back through the normal /internal/ingest path.

    "No good transcript" reuses `_has_good_transcript()` (the same quality
    gate `list_transcription_backlog_candidates()` already uses) rather
    than the narrower "no is_default=True row at all" this used to check.
    Real gap fixed 2026-08-16 (WO-15, BACKLOG.md): a YouTube-backed page
    whose default transcript is *present but garbled* (e.g. a Whisper
    audio-fallback transcript that never got a real caption track) used to
    never resurface here at all, even though a real YouTube caption fetch
    -- strictly better than an audio transcription when it exists -- would
    fix it. `_has_good_transcript()` already covers the original "no
    is_default row" case too (no segments -> False), so this is a strict
    broadening, not a behavior change for the original case.

    Returns exactly the identity fields a push needs for
    _find_or_create_page() to match the existing page rather than
    creating a duplicate: platform, external_id, source_url_normalized.
    """
    async with async_session() as session:
        pages = (
            (
                await session.execute(
                    select(MeetingPage)
                    .where(MeetingPage.video_format == "youtube")
                    .order_by(MeetingPage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        wanted = []
        for page in pages:
            if await _has_good_transcript(session, page.id):
                continue
            wanted.append(
                {
                    "slug": page.slug,
                    "title": page.title,
                    "platform": page.platform,
                    "external_id": page.external_id,
                    "source_url_normalized": page.source_url_normalized,
                    "video_url": page.video_url,
                }
            )
        return wanted


async def list_transcription_backlog_candidates(
    limit: Optional[int] = None,
) -> list[dict]:
    """Oldest-archived-first MeetingPages missing a good transcript, across
    ANY platform -- the batch counterpart to find_auto_transcription_
    candidate() (which only ever returns one candidate at a time, for the
    worker's own idle-time single-job auto-generation loop) and to
    list_youtube_pages_missing_transcripts() (YouTube-only, feeding the
    real-caption *fetch* path in scripts/fetch_youtube_transcripts.py,
    strictly better than an audio transcription when real captions
    exist). Consumed by scripts/transcribe_backlog_locally.py, which runs
    on a local Mac (no Render 2GB ceiling) and works a real batch per
    invocation rather than one page every AUTO_GENERATION_CHECK_INTERVAL_
    SECONDS.

    Applies the exact same _has_good_transcript() quality check and
    _in_auto_transcription_cooldown() escalating-backoff skip the worker's
    own auto-generation candidate search uses, so this script and the
    worker's idle-time path never duplicate feasibility-probe effort on
    (or fight over) the same recently-failed page.

    Not platform-restricted (unlike list_youtube_pages_missing_
    transcripts()): the caller extracts audio directly from whatever
    video_url a fresh resolve returns (via app/platforms/media_probe.py's
    extract_chunk_audio(), an HTTP Range/HLS-segment pull, not a full
    download), which works the same way regardless of which platform
    found that URL. The one real exception is a YouTube-backed page
    (video_format == "youtube", a youtube.com/embed/{id} URL, not a
    direct-streamable one) -- included here rather than filtered out
    server-side, since a plausible-in-the-future audio-fallback path for
    those (see BACKLOG.md's "Whisper fallback for YouTube videos with no
    captions at all") is a different, still-unbuilt mechanism (yt-dlp
    audio download, not direct URL extraction); the caller filters these
    out cheaply using the same video_format field returned here, rather
    than this function silently dropping a real candidate a future caller
    might handle differently.

    Full Python-side scan over every page, same "fine at today's scale,
    revisit at real scale" reasoning as find_auto_transcription_candidate()
    and list_pages()'s own keyword search -- this is a manually-invoked
    local batch tool, not a hot request path.
    """
    async with async_session() as session:
        pages = (
            (
                await session.execute(
                    select(MeetingPage).order_by(MeetingPage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        candidates = []
        for page in pages:
            if await _has_good_transcript(session, page.id):
                continue
            if await _in_auto_transcription_cooldown(session, page.id):
                continue
            candidates.append(
                {
                    "slug": page.slug,
                    "title": page.title,
                    "platform": page.platform,
                    "external_id": page.external_id,
                    "source_url_normalized": page.source_url_normalized,
                    "video_url": page.video_url,
                    "video_format": page.video_format,
                    "jurisdiction": page.jurisdiction,
                    "date": page.date,
                    "created_at": page.created_at.isoformat(),
                }
            )
            if limit is not None and len(candidates) >= limit:
                break

    return candidates


async def get_transcription_queue_summary() -> dict:
    """Real-time snapshot of transcription workload, for operator
    reporting (archive/main.py's `GET /internal/send-worker-daily-report`).
    Every field here is either a cheap integer aggregate over
    TranscriptionJob (never touches `partial_segments`) or the same fast
    `_good_default_transcript_exists()` SQL predicate
    find_auto_transcription_candidate() already uses -- deliberately NOT
    list_transcription_backlog_candidates()'s slower per-page Python-loop
    query above (see BACKLOG.md: that function still does one DB round
    trip per MeetingPage, a real, pre-existing N+1 this doesn't need to
    inherit for a simple count).

    `segments_added_last_24h` is Postgres-only (`json_array_length`
    computed server-side, never loading the segments JSON into Python --
    same "don't move the blob" discipline as `_good_default_transcript_
    exists()`) -- None on SQLite (dev/test), same dialect-feature-detect
    pattern as `_fts_available()`. `json_array_length`, not
    `jsonb_array_length` -- confirmed live 2026-08-21 (real production
    500, `UndefinedFunctionError: function jsonb_array_length(json) does
    not exist`): `TranscriptVersion.segments` is a plain SQLAlchemy
    `JSON` column, which maps to Postgres `json`, not `jsonb` -- the two
    types have separate, non-interchangeable function families. This
    Postgres-only branch has no SQLite equivalent to exercise it in the
    test suite (dialect-gated to None there by design), so this specific
    mistake wasn't caught until a real request hit it -- worth a live
    curl re-check after any future change here, not just `pytest`.
    """
    async with async_session() as session:
        active_rows = (
            await session.execute(
                select(
                    TranscriptionJob.total_chunks, TranscriptionJob.chunks_completed
                ).where(
                    TranscriptionJob.status.in_(
                        ("queued", "in_progress", "retry_scheduled")
                    )
                )
            )
        ).all()
        active_jobs = len(active_rows)
        remaining_chunks = sum(total - done for total, done in active_rows)

        cumulative_chunks_completed = (
            await session.execute(
                select(func.coalesce(func.sum(TranscriptionJob.chunks_completed), 0))
            )
        ).scalar()
        cumulative_jobs_completed = (
            await session.execute(
                select(func.count())
                .select_from(TranscriptionJob)
                .where(TranscriptionJob.status == "completed")
            )
        ).scalar()

        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        jobs_completed_last_24h = (
            await session.execute(
                select(func.count())
                .select_from(TranscriptionJob)
                .where(
                    TranscriptionJob.status == "completed",
                    TranscriptionJob.updated_at >= day_ago,
                )
            )
        ).scalar()

        segments_added_last_24h = None
        if session.bind.dialect.name == "postgresql":
            segments_added_last_24h = (
                await session.execute(
                    select(
                        func.coalesce(
                            func.sum(
                                func.json_array_length(TranscriptVersion.segments)
                            ),
                            0,
                        )
                    ).where(
                        TranscriptVersion.source == "transcribed",
                        TranscriptVersion.created_at >= day_ago,
                    )
                )
            ).scalar()

        backlog_no_transcript = (
            await session.execute(
                select(func.count())
                .select_from(MeetingPage)
                .where(~_good_default_transcript_exists())
            )
        ).scalar()

        return {
            "active_jobs": active_jobs,
            "remaining_chunks_in_active_jobs": remaining_chunks,
            "cumulative_chunks_completed_all_time": cumulative_chunks_completed,
            "cumulative_jobs_completed_all_time": cumulative_jobs_completed,
            "jobs_completed_last_24h": jobs_completed_last_24h,
            "segments_added_last_24h": segments_added_last_24h,
            "backlog_no_transcript": backlog_no_transcript,
        }


async def get_and_advance_worker_report_snapshot(
    *, cumulative_chunks_completed: int, cumulative_jobs_completed: int
) -> Optional[dict]:
    """Reads the previous worker-report snapshot (None the very first time
    this ever runs -- see WorkerReportSnapshot's own docstring), then
    overwrites it with the current cumulative totals -- single row, id=1
    by convention, updated in place rather than appended to. Returns the
    PREVIOUS snapshot (before overwriting) so the caller can diff
    "current cumulative total" against "yesterday's cumulative total" for
    a real 24h chunk-completion delta. Commits unconditionally (read and
    write happen in the same call) -- there's only ever one caller
    (the report-send route), so no risk of two callers racing to
    advance this the same way claim_next_chunk() has to guard against.
    """
    async with async_session() as session:
        previous = await session.get(WorkerReportSnapshot, 1)
        previous_dict = (
            {
                "cumulative_chunks_completed": previous.cumulative_chunks_completed,
                "cumulative_jobs_completed": previous.cumulative_jobs_completed,
                "recorded_at": previous.recorded_at,
            }
            if previous is not None
            else None
        )

        if previous is not None:
            previous.cumulative_chunks_completed = cumulative_chunks_completed
            previous.cumulative_jobs_completed = cumulative_jobs_completed
            previous.recorded_at = datetime.now(timezone.utc)
        else:
            session.add(
                WorkerReportSnapshot(
                    id=1,
                    cumulative_chunks_completed=cumulative_chunks_completed,
                    cumulative_jobs_completed=cumulative_jobs_completed,
                )
            )
        await session.commit()
        return previous_dict


# ---------------------------------------------------------------------------
# Transcription failure analysis (WO-40)
# ---------------------------------------------------------------------------

# The two shapes of failure that keep getting conflated in the incident
# record, and that call for opposite mitigations:
#
#   * Rate limiting -- the host throttles us because we asked too much,
#     too fast. Spreading requests across different hosts helps.
#   * Cold storage / rehydration -- a Granicus archive clip that hasn't
#     been touched in a long time isn't warm on the CDN yet, so the
#     FIRST pull times out while later ones (against a now-warm asset)
#     succeed. A real confirmed case: a King County clip failed for
#     ~a day, then succeeded untouched with no code change (BACKLOG.md).
#     Here, clustering HELPS -- chunk 0 warms the asset for chunks 1..N.
#
# Nothing in the schema labels a failure as one or the other, but two
# stored signals discriminate between them without new instrumentation:
#
#   1. WHERE in the job the failure landed. TranscriptionJob.failure_
#      history already records a real `chunk_index` per failed attempt
#      (added 2026-08-19). A failure on chunk 0 is cold-storage-shaped:
#      nothing had been pulled from that asset yet, so no rate limit
#      could plausibly have accumulated. A failure on chunk 15 after 14
#      successes is rate-limit-shaped: the only thing that changed
#      between chunk 0 and chunk 15 is how much we'd already asked for.
#   2. WHICH host actually served the media. This is deliberately keyed
#      on `media_url`'s host, not the page's -- on Granicus every tenant
#      has its own `{tenant}.granicus.com` page subdomain, but the media
#      itself comes off a small number of SHARED CDN hosts
#      (archive-video/archive-stream/archive-media.granicus.com). The
#      rate-limiting party is the CDN, not the tenant, so grouping by
#      page host would report ~300 distinct "hosts" that are really one.
#      Both groupings are returned so that difference is visible rather
#      than assumed.
#
# Read-only, side-effect free, and a full Python-side scan over
# TranscriptionJob -- same "fine at today's scale" reasoning as
# list_transcription_backlog_candidates() above (a few hundred rows,
# operator-invoked, not a hot request path). It never selects
# partial_segments, which is the only large column here.

_FFMPEG_TIMEOUT_MARKER = "ffmpeg timed out"

# Two failures against the same host inside this window count as
# "clustered". An hour is deliberately loose: a single chunk can take
# minutes, so a genuine throttle-driven burst of failures across
# concurrent workers still lands well inside it, while genuinely
# unrelated failures against the same host days apart do not.
FAILURE_CLUSTER_WINDOW = timedelta(hours=1)


def _failure_host_of(url: Optional[str]) -> str:
    if not url:
        return "(none)"
    try:
        return (urlparse(url).hostname or "(unparseable)").lower()
    except ValueError:
        return "(unparseable)"


def _max_failures_in_window(timestamps: list[datetime]) -> int:
    """Largest number of failures for one host falling inside any single
    FAILURE_CLUSTER_WINDOW-wide sliding window. A plain two-pointer scan
    over sorted timestamps -- this is the "do failures burst, or are they
    scattered singletons?" question, and a burst is what rate limiting
    looks like."""
    if not timestamps:
        return 0
    ordered = sorted(timestamps)
    best = 1
    start = 0
    for end in range(len(ordered)):
        while ordered[end] - ordered[start] > FAILURE_CLUSTER_WINDOW:
            start += 1
        best = max(best, end - start + 1)
    return best


def _parse_failure_at(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# Two failures this close together are plausibly the same underlying
# episode. Deliberately much tighter than FAILURE_CLUSTER_WINDOW: this is
# asking "were these two failures contending with each other", not "did
# this host have a bad afternoon".
FAILURE_PAIR_WINDOW = timedelta(minutes=10)


def _failure_pair_shape(rows, cutoff: Optional[datetime]) -> dict:
    """Classifies every pair of failures falling within FAILURE_PAIR_WINDOW
    of each other by how related the two are.

    This is the direct, falsifiable test of the "workers claim consecutive
    jobs from the same host and hammer it" theory. That theory predicts
    failures should pile up across *different jobs* against the *same
    host* at nearly the same time. If instead nearly every close pair is
    within a single job, the clustering that actually hurts is happening
    inside one job's own chunk loop -- which no amount of queue reordering
    can reach, since a worker holds a job through all its chunks
    (claim_next_chunk() claims a whole job, not a chunk, despite its name).
    """
    events: list[tuple[datetime, str, str, int]] = []
    for row in rows:
        host = _failure_host_of(row.source_url_normalized)
        domain = ".".join(host.split(".")[-2:])
        for entry in row.failure_history or []:
            if not isinstance(entry, dict):
                continue
            at = _parse_failure_at(entry.get("at"))
            if at is None or (cutoff is not None and at < cutoff):
                continue
            events.append((at, host, domain, row.id))
    events.sort(key=lambda e: e[0])

    counts = {
        "same_job": 0,
        "same_host_different_job": 0,
        "same_domain_different_host": 0,
        "unrelated_hosts": 0,
    }
    for i, first in enumerate(events):
        for second in events[i + 1 :]:
            if second[0] - first[0] > FAILURE_PAIR_WINDOW:
                break
            if first[3] == second[3]:
                counts["same_job"] += 1
            elif first[1] == second[1]:
                counts["same_host_different_job"] += 1
            elif first[2] == second[2]:
                counts["same_domain_different_host"] += 1
            else:
                counts["unrelated_hosts"] += 1
    return counts


async def get_transcription_failure_analysis(days: Optional[int] = None) -> dict:
    """Groups every recorded chunk failure by media host, by page host, and
    by position-within-job, so "are we being rate limited, or is this cold
    storage?" is answered from real stored data rather than argued from
    first principles. See the module comment above this function for what
    each signal actually discriminates.

    `days` optionally restricts to failures recorded within the last N
    days (by the failure_history entry's own `at` timestamp, not the job's
    created_at -- a job created weeks ago can fail today via the
    retry_scheduled path). Omitted means all-time.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days) if days is not None else None
    )

    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    TranscriptionJob.id,
                    TranscriptionJob.media_url,
                    TranscriptionJob.total_chunks,
                    TranscriptionJob.status,
                    TranscriptionJob.priority,
                    TranscriptionJob.failure_history,
                    MeetingPage.source_url_normalized,
                    MeetingPage.platform,
                ).join(MeetingPage, MeetingPage.id == TranscriptionJob.meeting_page_id)
            )
        ).all()

    return summarize_failure_rows(rows, cutoff=cutoff, days=days)


def summarize_failure_rows(rows, *, cutoff: Optional[datetime], days: Optional[int]):
    """The whole diagnostic, as a pure function over already-fetched rows.

    Split out from the query deliberately: this is the part with real
    reasoning in it (the attempt-normalization especially, which is what
    keeps a reader from misreading raw counts), and keeping it
    DB-free means it can be tested directly against constructed rows
    instead of against whatever jobs happen to be in the shared test
    database -- which several other test modules also write failures into,
    making any whole-table assertion order-dependent.

    `rows` is any iterable of objects exposing the attributes selected in
    get_transcription_failure_analysis() above.
    """
    by_media_host: dict[str, dict] = {}
    by_page_host: dict[str, dict] = {}
    by_platform: dict[str, dict] = {}
    position_buckets = {
        "chunk_0_first_pull": 0,
        "chunk_1_to_2": 0,
        "chunk_3_plus": 0,
        "unknown_chunk_index": 0,
    }
    # Only meaningful for a multi-chunk job: "did this job get anywhere
    # before it failed?" A first-chunk failure on a 1-chunk job can't
    # distinguish the two hypotheses at all, so it's counted separately.
    single_chunk_failures = 0
    multi_chunk_first_failures = 0
    multi_chunk_later_failures = 0
    total_failures = 0
    jobs_with_failures = 0
    ffmpeg_timeout_failures = 0
    failure_times_by_media_host: dict[str, list[datetime]] = {}
    # RAW FAILURE COUNTS BY POSITION ARE ACTIVELY MISLEADING, and the
    # normalization below is the whole reason this function is worth
    # having. A job has exactly one chunk 0 but many later chunks, so
    # "75% of failures happened after the first chunk" is what you see
    # even when the first chunk is by far the most failure-prone
    # position -- that is precisely the wrong read (it looks like an
    # accumulating rate limit) and it is the read the raw buckets above
    # invite. Dividing by the number of times each chunk index was
    # actually ATTEMPTED is what makes positions comparable:
    #
    #   rising with chunk index  -> accumulating rate limit
    #   spike at 0, flat after   -> cold storage / rehydration
    #   flat and high throughout -> a source that is simply slow
    #                               relative to the fixed ffmpeg timeout
    #
    # Attempts are derived, not stored: a job with total_chunks == N
    # attempts every index 0..N-1 at least once (the worker walks them
    # in order and a job only finishes by reaching the end), so N is a
    # sound lower bound on attempts per index for the jobs counted here.
    # Ratios can therefore exceed 1.0 -- an index that failed several
    # times before succeeding -- which is meaningful, not a bug.
    attempts_by_index: dict[int, int] = {}
    failures_by_index: dict[int, int] = {}
    attempts_by_decile: dict[int, int] = {}
    failures_by_decile: dict[int, int] = {}

    for row in rows:
        history = row.failure_history or []
        if not history:
            continue

        media_host = _failure_host_of(row.media_url)
        page_host = _failure_host_of(row.source_url_normalized)
        platform = row.platform or "(unknown)"
        counted_this_job = False

        for entry in history:
            if not isinstance(entry, dict):
                continue
            at = _parse_failure_at(entry.get("at"))
            if cutoff is not None and (at is None or at < cutoff):
                continue

            total_failures += 1
            if not counted_this_job:
                jobs_with_failures += 1
                counted_this_job = True
                # Attempt denominators, counted once per job rather than
                # once per failure -- see the comment above the
                # attempts_by_* declarations for why this normalization
                # is the point of the whole function.
                for idx in range(row.total_chunks or 0):
                    attempts_by_index[idx] = attempts_by_index.get(idx, 0) + 1
                    dec = min(9, (10 * idx) // (row.total_chunks or 1))
                    attempts_by_decile[dec] = attempts_by_decile.get(dec, 0) + 1

            error = entry.get("error") or ""
            is_timeout = _FFMPEG_TIMEOUT_MARKER in error
            if is_timeout:
                ffmpeg_timeout_failures += 1

            chunk_index = entry.get("chunk_index")
            if isinstance(chunk_index, int):
                failures_by_index[chunk_index] = (
                    failures_by_index.get(chunk_index, 0) + 1
                )
                dec = min(9, (10 * chunk_index) // (row.total_chunks or 1))
                failures_by_decile[dec] = failures_by_decile.get(dec, 0) + 1
            if not isinstance(chunk_index, int):
                position_buckets["unknown_chunk_index"] += 1
            elif chunk_index == 0:
                position_buckets["chunk_0_first_pull"] += 1
            elif chunk_index <= 2:
                position_buckets["chunk_1_to_2"] += 1
            else:
                position_buckets["chunk_3_plus"] += 1

            if (row.total_chunks or 0) <= 1:
                single_chunk_failures += 1
            elif isinstance(chunk_index, int) and chunk_index == 0:
                multi_chunk_first_failures += 1
            elif isinstance(chunk_index, int):
                multi_chunk_later_failures += 1

            for bucket, key in (
                (by_media_host, media_host),
                (by_page_host, page_host),
                (by_platform, platform),
            ):
                stats = bucket.setdefault(
                    key,
                    {
                        "failures": 0,
                        "ffmpeg_timeouts": 0,
                        "first_chunk_failures": 0,
                        "later_chunk_failures": 0,
                        "job_ids": set(),
                    },
                )
                stats["failures"] += 1
                stats["job_ids"].add(row.id)
                if is_timeout:
                    stats["ffmpeg_timeouts"] += 1
                if isinstance(chunk_index, int):
                    if chunk_index == 0:
                        stats["first_chunk_failures"] += 1
                    else:
                        stats["later_chunk_failures"] += 1

            if at is not None:
                failure_times_by_media_host.setdefault(media_host, []).append(at)

    def _finalize(bucket: dict[str, dict], with_windows: bool) -> list[dict]:
        out = []
        for key, stats in bucket.items():
            entry = {
                "host": key,
                "failures": stats["failures"],
                "ffmpeg_timeouts": stats["ffmpeg_timeouts"],
                "first_chunk_failures": stats["first_chunk_failures"],
                "later_chunk_failures": stats["later_chunk_failures"],
                "distinct_jobs": len(stats["job_ids"]),
            }
            if with_windows:
                entry["max_failures_in_1h_window"] = _max_failures_in_window(
                    failure_times_by_media_host.get(key, [])
                )
            out.append(entry)
        return sorted(out, key=lambda e: -e["failures"])

    positioned = multi_chunk_first_failures + multi_chunk_later_failures
    return {
        "window_days": days,
        "total_failures": total_failures,
        "jobs_with_failures": jobs_with_failures,
        "ffmpeg_timeout_failures": ffmpeg_timeout_failures,
        # Raw counts. Read failure_rate_by_chunk_index below INSTEAD of
        # these when asking "where in a job do failures happen" -- these
        # are dominated by how many chunks exist at each position, not by
        # how failure-prone each position is. Kept because they're the
        # honest raw material the rates are computed from.
        "failure_position": position_buckets,
        "multi_chunk_jobs": {
            "first_chunk_failures": multi_chunk_first_failures,
            "later_chunk_failures": multi_chunk_later_failures,
            "first_chunk_share": (
                round(multi_chunk_first_failures / positioned, 3)
                if positioned
                else None
            ),
        },
        # THE diagnostic. Failures per actual attempt at each chunk index,
        # and the same thing bucketed by decile of job length so jobs of
        # different lengths are comparable. See the comment above
        # attempts_by_index for how to read the shape.
        "failure_rate_by_chunk_index": [
            {
                "chunk_index": idx,
                "attempts": attempts_by_index[idx],
                "failures": failures_by_index.get(idx, 0),
                "failures_per_attempt": round(
                    failures_by_index.get(idx, 0) / attempts_by_index[idx], 3
                ),
            }
            for idx in sorted(attempts_by_index)
        ],
        "failure_rate_by_decile": [
            {
                "decile": dec,
                "attempts": attempts_by_decile[dec],
                "failures": failures_by_decile.get(dec, 0),
                "failures_per_attempt": round(
                    failures_by_decile.get(dec, 0) / attempts_by_decile[dec], 3
                ),
            }
            for dec in sorted(attempts_by_decile)
        ],
        "single_chunk_job_failures": single_chunk_failures,
        "by_media_host": _finalize(by_media_host, with_windows=True),
        "by_page_host": _finalize(by_page_host, with_windows=False),
        "by_platform": _finalize(by_platform, with_windows=False),
        # Directly tests the "workers grab consecutive jobs from the same
        # host and hammer it" hypothesis: that predicts a large
        # same_host_different_job bucket. Measured 2026-08-21 against
        # real production data, this bucket was exactly 0 -- see
        # BACKLOG_DONE.md's WO-40 entry.
        "concurrency_pairs_within_10min": _failure_pair_shape(rows, cutoff),
    }


async def list_completed_multichunk_transcription_jobs() -> list[dict]:
    """Every completed TranscriptionJob with total_chunks > 1 -- i.e. every
    on-demand transcription that actually went through the real per-chunk
    extract_chunk_audio()/shift_segments() loop (worker/main.py's
    process_next_chunk()) before this loop dropped its own seam-duplicate
    detection (worker/segment_utils.py's count_seam_overlap_segments(),
    added 2026-08-16 -- see BACKLOG_DONE.md's matching entry for the full
    root-cause writeup). A single-chunk job (total_chunks == 1) never hit
    a chunk boundary at all, so it isn't a candidate for that bug.

    Read-only and audit-only, on purpose: this just sizes how much
    already-completed, already-live work is a real candidate for the bug
    having shipped before the fix -- it deliberately doesn't re-transcribe
    or touch anything itself. A human decides what (if anything) from this
    list is worth re-running.
    """
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    TranscriptionJob.id,
                    TranscriptionJob.meeting_page_id,
                    TranscriptionJob.total_chunks,
                    TranscriptionJob.chunk_size_seconds,
                    TranscriptionJob.probed_duration_seconds,
                    TranscriptionJob.updated_at,
                    MeetingPage.slug,
                    MeetingPage.title,
                )
                .join(MeetingPage, MeetingPage.id == TranscriptionJob.meeting_page_id)
                .where(
                    TranscriptionJob.status == "completed",
                    TranscriptionJob.total_chunks > 1,
                )
                .order_by(TranscriptionJob.id.asc())
            )
        ).all()

        return [
            {
                "job_id": r.id,
                "meeting_page_id": r.meeting_page_id,
                "slug": r.slug,
                "title": r.title,
                "total_chunks": r.total_chunks,
                "chunk_size_seconds": r.chunk_size_seconds,
                "probed_duration_seconds": r.probed_duration_seconds,
                "completed_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


async def list_hallucination_candidate_transcript_versions(
    *, limit: int = 500, after_id: Optional[int] = None
) -> list[dict]:
    """Retroactive audit, same role as list_completed_multichunk_transcription_
    jobs() above plays for the seam-duplication bug: re-runs
    detect_hallucination_warnings() (archive/utils/transcription_quality.py --
    the same function report_chunk_result() now calls at finalize time, and
    scripts/transcribe_backlog_locally.py's transcribe_meeting() calls
    directly) against the *stored* segments of already-completed
    source=="transcribed" TranscriptVersions, to find which ones would trip
    the check today but shipped before it existed (or before this specific
    row was ever re-evaluated). See BACKLOG.md's phase-cancellation write-up
    -- this was flagged there as open/not yet built.

    source=="transcribed" (not "scraped") covers both real populations the
    brief calls out: the cloud worker's report_chunk_result() and
    scripts/transcribe_backlog_locally.py's local-Mac runs both set this
    exact value (see ingest_resolution()'s own docstring on why the script
    sets it explicitly) -- a plain "scraped" caption was never run through
    Whisper at all, so it isn't a candidate for a Whisper-hallucination
    symptom in the first place. Left-joins TranscriptionJob on
    transcript_version_id to label which real path produced each version:
    a matching job means the cloud worker produced it (job_id present); no
    match means scripts/transcribe_backlog_locally.py did, since that script
    deliberately never writes to transcription_jobs at all (see its own
    module docstring).

    `already_flagged` is True when this exact version's stored
    transcript_warnings already carries the hallucination marker (i.e. it
    was created after the check went live and correctly caught this itself)
    -- included so a caller can tell "newly discovered by this audit" apart
    from "already known", without needing to inspect every row by hand.

    Read-only and audit-only, on purpose, same as the seam-duplication
    audit: sizes the real exposure without touching anything. A human
    decides what (if anything) from this list is worth re-running.

    Rewritten 2026-08-21 after this endpoint was confirmed live-502ing --
    the previous version pulled TranscriptVersion.segments (the full
    per-cue JSON blob) for *every* source=="transcribed" row in one query
    with no limit, then ran detect_hallucination_warnings() (CPU-bound
    Python) over each synchronously in the request handler. Exact same
    shape find_auto_transcription_candidate() had before its own
    2026-08-17 rewrite (see that function's docstring), which
    pg_stat_statements caught as the #1 consumer of production DB time for
    the same reason: pulling every transcript's full segments JSON on a
    recurring basis. Unlike that function's fix, this audit's whole job is
    to run real CPU-bound detection over segments -- there's no SQL-only
    predicate that replaces detect_hallucination_warnings() itself, so the
    elimination has to be data-shaped instead:

    - Rows that ALREADY carry the hallucination marker in stored
      transcript_warnings are a small, slow-growing set (only real
      hallucination-loop transcripts get flagged, by this same check,
      at ingest/finalize time -- see _has_real_warning_free_transcript()).
      Selected via the same cast(...).like() text-match
      _good_default_transcript_exists() already uses, so this branch never
      touches `segments` at the SQL level; segments is then pulled ONLY
      for this small already-flagged set (still re-run through detection
      below, so a row that stops tripping the check under updated
      detection logic falls back out rather than reporting stale state).
    - Rows NOT yet flagged are the big, actively-growing population (every
      clean "transcribed" version, plus any pre-2026-08-16 hallucinated one
      that was never caught) -- this is what made the previous version
      unbounded. Bounded here by `limit` + keyset pagination on
      TranscriptVersion.id (`after_id`), same shape as
      list_transcription_backlog_candidates()'s own `limit` param, so a
      single call can only ever pull `limit` rows' worth of segments no
      matter how large this population gets. A caller auditing the full
      backlog pages through by repeatedly passing the previous batch's
      max version_id as the next after_id.
    """
    warnings_text = cast(TranscriptVersion.transcript_warnings, Text)
    # NULL transcript_warnings must count as "not flagged", guarded
    # explicitly same as _good_default_transcript_exists() above --
    # `NULL LIKE ...` (and its negation) is NULL, not False, and a bare
    # `~warnings_text.like(...)` would silently drop every NULL-warnings
    # row out of BOTH branches (WHERE NULL is falsy) rather than routing
    # it into the unflagged/candidate-scan side where it belongs.
    already_flagged_clause = and_(
        TranscriptVersion.transcript_warnings.is_not(None),
        warnings_text.like(f"%{_HALLUCINATION_MARKER}%"),
    )
    not_flagged_clause = or_(
        TranscriptVersion.transcript_warnings.is_(None),
        ~warnings_text.like(f"%{_HALLUCINATION_MARKER}%"),
    )

    base_columns = (
        TranscriptVersion.id,
        TranscriptVersion.meeting_page_id,
        TranscriptVersion.language,
        TranscriptVersion.is_default,
        TranscriptVersion.segments,
        TranscriptVersion.transcript_warnings,
        TranscriptVersion.created_at,
        MeetingPage.slug,
        MeetingPage.title,
        TranscriptionJob.id,
    )

    async with async_session() as session:
        flagged_query = (
            select(*base_columns)
            .join(MeetingPage, MeetingPage.id == TranscriptVersion.meeting_page_id)
            .outerjoin(
                TranscriptionJob,
                TranscriptionJob.transcript_version_id == TranscriptVersion.id,
            )
            .where(
                TranscriptVersion.source == "transcribed",
                already_flagged_clause,
            )
        )
        unflagged_query = (
            select(*base_columns)
            .join(MeetingPage, MeetingPage.id == TranscriptVersion.meeting_page_id)
            .outerjoin(
                TranscriptionJob,
                TranscriptionJob.transcript_version_id == TranscriptVersion.id,
            )
            .where(
                TranscriptVersion.source == "transcribed",
                not_flagged_clause,
            )
        )
        if after_id is not None:
            flagged_query = flagged_query.where(TranscriptVersion.id > after_id)
            unflagged_query = unflagged_query.where(TranscriptVersion.id > after_id)

        flagged_rows = (
            await session.execute(flagged_query.order_by(TranscriptVersion.id.asc()))
        ).all()
        unflagged_rows = (
            await session.execute(
                unflagged_query.order_by(TranscriptVersion.id.asc()).limit(limit)
            )
        ).all()

        candidates = []
        for (
            version_id,
            meeting_page_id,
            language,
            is_default,
            segments,
            transcript_warnings,
            created_at,
            slug,
            title,
            job_id,
        ) in [*flagged_rows, *unflagged_rows]:
            warnings = detect_hallucination_warnings(segments or [])
            if not warnings:
                continue
            already_flagged = any(
                _HALLUCINATION_MARKER in w for w in (transcript_warnings or [])
            )
            candidates.append(
                {
                    "version_id": version_id,
                    "meeting_page_id": meeting_page_id,
                    "slug": slug,
                    "title": title,
                    "language": language,
                    "is_default": is_default,
                    "segment_count": len(segments or []),
                    "already_flagged": already_flagged,
                    "produced_by": "cloud_worker"
                    if job_id is not None
                    else "local_script",
                    "job_id": job_id,
                    "created_at": created_at.isoformat() if created_at else None,
                }
            )

        candidates.sort(key=lambda c: c["version_id"])
        return candidates


# The two jurisdiction_confidence tiers that mean "we never actually
# confirmed this jurisdiction against anything" -- see
# app/utils/jurisdiction_enrich.py's JurisdictionResult.confidence and
# MeetingPage.jurisdiction_confidence's own comment for the full ladder
# ("authoritative"/"validated"/"repaired"/"fallback"/"unverified"/
# "blank"). "fallback" is deliberately NOT here: it means a real value
# was derived, just not from an authoritative source, which is a
# different (and much larger) bucket than "unverified".
_LOW_TRUST_CONFIDENCES = ("unverified", "blank")

_LOW_TRUST_DEFAULT_LIMIT = 200
_LOW_TRUST_MAX_LIMIT = 1000

# The `reason` strings list_low_trust_pages() reports per row, and the
# only values its `reason=` filter accepts. Kept as one tuple so the
# filter can never drift from what the rows actually say.
_LOW_TRUST_REASONS = ("unknown_platform", "best_effort", "unverified_jurisdiction")

# Upper bound on how many ids one mark-reviewed call may touch. Not a
# performance limit (it's a single UPDATE) -- it's the ceiling on how
# much damage one mis-pasted request can do to production rows, and it
# sits comfortably above _LOW_TRUST_MAX_LIMIT/2 so a reviewer working a
# realistic page of the queue never hits it.
_MARK_REVIEWED_MAX_IDS = 1000


async def list_low_trust_pages(
    *,
    limit: int = _LOW_TRUST_DEFAULT_LIMIT,
    offset: int = 0,
    unreviewed: bool = False,
    reason: Optional[str] = None,
) -> dict:
    """Read-only audit list backing GET /internal/low-trust-pages
    (archive/main.py) -- every archived page whose provenance was never
    really verified, so a human can review what the fully-automatic
    pipeline has published. Same read-only-audit role and response shape
    as list_jurisdiction_bleed_backfill_candidates() above, this
    function's own template; never writes anything.

    Three independent reasons put a page in this list, OR'd together
    because they genuinely overlap rather than nest:

    * `platform == "unknown"` -- the string generic_fallback.py registers
      under, i.e. a page built by best-effort-scanning an arbitrary URL
      with no vendor adapter involved.
    * `best_effort` -- the resolver's own flag for the same fallback
      path, and NOT redundant with the above: generic_fallback delegates
      to YouTubeAssetFinder whenever the page embeds a YouTube video, and
      those results carry platform "youtube". That delegated case is the
      most common real fallback outcome, so a platform-only check misses
      most of what this list is for (see MeetingPage.best_effort).
    * `jurisdiction_confidence` in _LOW_TRUST_CONFIDENCES -- the page is
      published under a jurisdiction name nothing ever validated, which
      is the specific fabricated-jurisdiction risk BACKLOG.md's "Trust &
      safety" section threat-modeled.

    Explicitly NOT a filter on anything user-facing. This does not change
    what's indexed, what's in the sitemap, or what a /j/* hub lists --
    that was a deliberate product decision (see BACKLOG.md's entry): most
    best_effort pages are real small cities that merely happened to
    resolve via the fallback, and de-indexing them would cost real reach.
    This endpoint exists so "what's low-trust?" is answerable without
    making the pipeline synchronous or gated.

    Paginated (unlike the jurisdiction audit, which is bounded by how few
    rows can be stale): the low-trust set is a standing slice of the whole
    archive, not a one-off backfill batch, so it can be large. `total` is
    the full match count regardless of the page returned.

    **What this queue actually holds, measured (2026-08-21, WO-38).** The
    first real production call returned 474 rows, and the breakdown is
    not what the trust threat model expected: 470 are
    `unverified_jurisdiction`, 7 are `unknown_platform` (3 of those
    overlapping), and *zero* are `best_effort`. So today this is
    overwhelmingly a **data-quality** queue -- "we could not determine
    this meeting's jurisdiction" -- and a trust queue only prospectively.
    Two reasons for that, both expected rather than broken: best_effort
    cannot be backfilled onto rows archived before its column existed
    (see the d4e5f6a7b8c9 migration), so it only appears on pages
    ingested from 2026-08-21 onward; and genuinely spoofed government
    content has never actually been observed, whereas a missing
    jurisdiction is routine. A reviewer opening this expecting spoofing
    will be confused, which is why it's written down here.

    Those 474 rows are real, live, publicly-indexed pages with real video
    (472 of 474 had `has_video`), not junk -- nothing here should ever be
    read as "hide or delete these".

    Two filters, both narrowing the same base query and both optional so
    an unfiltered call returns exactly what it always did:

    * `unreviewed=True` -- only rows nobody has marked reviewed
      (`reviewed_at IS NULL`, see mark_low_trust_pages_reviewed()). This
      is what turns a 474-row dump into a workable queue: without it,
      re-reading the endpoint means re-triaging everything from scratch
      every time.
    * `reason` -- one of _LOW_TRUST_REASONS, restricting the OR to that
      single condition. Worth having precisely *because* of the
      measured skew above: with 470 of 474 rows sharing one reason, the
      4 pages that are low-trust for a different reason are invisible in
      practice without it.

    Raises ValueError on an unrecognised `reason` rather than silently
    ignoring it -- a typo'd filter that quietly returns the unfiltered
    474 rows would read as "nothing was filtered out", which is the
    wrong conclusion.
    """
    limit = max(1, min(int(limit), _LOW_TRUST_MAX_LIMIT))
    offset = max(0, int(offset))
    if reason is not None and reason not in _LOW_TRUST_REASONS:
        raise ValueError(f"unknown reason {reason!r}")

    async with async_session() as session:
        best_effort_available = await _best_effort_available(session)
        reviewed_at_available = await _reviewed_at_available(session)

        conditions = []
        if reason in (None, "unknown_platform"):
            conditions.append(MeetingPage.platform == "unknown")
        if reason in (None, "unverified_jurisdiction"):
            conditions.append(
                MeetingPage.jurisdiction_confidence.in_(_LOW_TRUST_CONFIDENCES)
            )
        if best_effort_available and reason in (None, "best_effort"):
            conditions.append(MeetingPage.best_effort.is_(True))
        # Only reachable as ?reason=best_effort during the one-deploy
        # window where that column doesn't exist yet: an empty OR() is
        # SQL-invalid, and "match nothing" is the honest answer -- with
        # no column, no row can carry the flag.
        where = or_(*conditions) if conditions else false()
        if unreviewed and reviewed_at_available:
            where = and_(where, MeetingPage.reviewed_at.is_(None))
        # When the column doesn't exist yet, `unreviewed=True` is a
        # deliberate no-op rather than an error, and that's not a
        # fail-open: nothing can have been marked reviewed without a
        # column to record it in, so every row genuinely IS unreviewed.
        # `reviewed_at_column_available` below tells a caller which case
        # they're in.

        total = (
            await session.execute(
                select(func.count()).select_from(MeetingPage).where(where)
            )
        ).scalar_one()

        columns = [
            MeetingPage.id,
            MeetingPage.slug,
            MeetingPage.title,
            MeetingPage.platform,
            MeetingPage.jurisdiction,
            MeetingPage.jurisdiction_confidence,
            MeetingPage.source_url_normalized,
            MeetingPage.video_url,
            MeetingPage.created_at,
        ]
        if best_effort_available:
            columns.append(MeetingPage.best_effort)
        if reviewed_at_available:
            columns.append(MeetingPage.reviewed_at)

        rows = (
            await session.execute(
                select(*columns)
                .where(where)
                # Newest first: a review queue is most useful pointed at
                # what the pipeline published most recently.
                .order_by(MeetingPage.created_at.desc(), MeetingPage.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        pages = []
        for row in rows:
            values = row._mapping
            best_effort = (
                bool(values[MeetingPage.best_effort])
                if best_effort_available
                else False
            )
            reviewed_at = (
                values[MeetingPage.reviewed_at] if reviewed_at_available else None
            )
            confidence = values[MeetingPage.jurisdiction_confidence]
            platform = values[MeetingPage.platform]
            reasons = []
            if platform == "unknown":
                reasons.append("unknown_platform")
            if best_effort:
                reasons.append("best_effort")
            if confidence in _LOW_TRUST_CONFIDENCES:
                reasons.append("unverified_jurisdiction")
            created_at = values[MeetingPage.created_at]
            pages.append(
                {
                    "meeting_page_id": values[MeetingPage.id],
                    "slug": values[MeetingPage.slug],
                    "title": values[MeetingPage.title],
                    "platform": platform,
                    "best_effort": best_effort,
                    "jurisdiction": values[MeetingPage.jurisdiction],
                    "jurisdiction_confidence": confidence,
                    "source_url": values[MeetingPage.source_url_normalized],
                    "has_video": bool(values[MeetingPage.video_url]),
                    "created_at": created_at.isoformat() if created_at else None,
                    "reasons": reasons,
                    "reviewed_at": (reviewed_at.isoformat() if reviewed_at else None),
                }
            )

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "unreviewed": unreviewed,
            "reason": reason,
            # False only in the one-deploy window where this code is live
            # but its migration hasn't run yet -- in which case the
            # best_effort half of the query is simply absent and every
            # row reports best_effort=false. Surfaced rather than hidden
            # so a caller can tell "no best_effort pages" apart from "the
            # column isn't there yet."
            "best_effort_column_available": best_effort_available,
            # Same one-deploy window, one migration later. False means
            # every row reports reviewed_at=null and `unreviewed=true`
            # filtered nothing -- which is accurate, not a silent failure
            # (no column, nothing reviewable), but a caller should know.
            "reviewed_at_column_available": reviewed_at_available,
            "pages": pages,
        }


async def mark_low_trust_pages_reviewed(
    *,
    ids: Set[int],
    dry_run: bool = True,
    unreview: bool = False,
) -> dict:
    """Write counterpart to list_low_trust_pages() above: stamps (or
    clears) MeetingPage.reviewed_at on specific pages, so the audit queue
    stops re-presenting rows a human has already worked through.

    **Explicitly id-driven, with no "mark everything" mode.** Structured
    after apply_jurisdiction_bleed_backfill()'s only_ids handling (WO-22,
    the established pattern here for a targeted bulk write) but stricter:
    there, ids narrow a set the endpoint recomputed itself, so omitting
    them means "all candidates"; here an empty/absent id set means
    nothing at all is written. Marking 474 rows reviewed in one
    unconsidered call would destroy exactly the signal this column
    exists to create, and there is no recovering "which of these had a
    human actually looked at?" afterwards. Capped at
    _MARK_REVIEWED_MAX_IDS per call for the same reason.

    **Idempotent by construction.** An id that is already stamped is
    reported as `already_reviewed` and its existing timestamp is left
    alone -- re-running the same call is a no-op, never a re-dating. An
    id matching no row is reported in `missing_ids` rather than failing
    the batch, so one stale id out of fifty doesn't block the other
    forty-nine.

    `unreview=True` clears the stamp back to NULL instead (and reports
    already-NULL rows as `already_reviewed`, i.e. already in the
    requested state). It exists because this writes production rows from
    a hand-pasted id list: without an undo, a mis-pasted batch could only
    be repaired with direct DATABASE_URL access, which is precisely what
    the /internal/* endpoints exist to avoid needing.

    dry_run=True is the default, matching every other write endpoint here
    (see apply_jurisdiction_bleed_backfill()): it computes and returns
    exactly what it *would* change without touching anything.

    Touches only the `reviewed_at` column, and nothing user-facing
    depends on it -- reviewing a page does not hide it, de-index it, or
    remove it from any hub. See MeetingPage.reviewed_at's comment.
    """
    ids = {int(i) for i in ids}
    if not ids:
        raise ValueError("ids is required and must contain at least one id")
    if len(ids) > _MARK_REVIEWED_MAX_IDS:
        raise ValueError(f"at most {_MARK_REVIEWED_MAX_IDS} ids per call")

    async with async_session() as session:
        if not await _reviewed_at_available(session):
            # A write, unlike the read above, cannot degrade honestly --
            # "marked reviewed" that recorded nothing would be worse than
            # an error. The caller (archive/main.py) turns this into a
            # 503; retrying after the migration runs succeeds.
            return {
                "reviewed_at_column_available": False,
                "dry_run": dry_run,
                "unreview": unreview,
                "requested": sorted(ids),
                "updated": 0,
                "changed": [],
                "already_reviewed": [],
                "missing_ids": [],
            }

        rows = (
            await session.execute(
                select(
                    MeetingPage.id,
                    MeetingPage.slug,
                    MeetingPage.reviewed_at,
                ).where(MeetingPage.id.in_(ids))
            )
        ).all()

        found = {row[0] for row in rows}
        changed = []
        already = []
        for page_id, slug, reviewed_at in rows:
            entry = {
                "meeting_page_id": page_id,
                "slug": slug,
                "reviewed_at_before": (
                    reviewed_at.isoformat() if reviewed_at else None
                ),
            }
            # "Already in the requested state" -- stamped when marking,
            # clear when unmarking. Either way, nothing to write.
            if (reviewed_at is None) == unreview:
                already.append(entry)
            else:
                changed.append(entry)

        stamp = None if unreview else datetime.now(timezone.utc)
        for entry in changed:
            entry["reviewed_at_after"] = stamp.isoformat() if stamp else None

        if changed and not dry_run:
            await session.execute(
                update(MeetingPage)
                .where(MeetingPage.id.in_([e["meeting_page_id"] for e in changed]))
                .values(reviewed_at=stamp)
            )
            await session.commit()

        return {
            "reviewed_at_column_available": True,
            "dry_run": dry_run,
            "unreview": unreview,
            "requested": sorted(ids),
            "updated": len(changed) if not dry_run else 0,
            "would_update": len(changed),
            "changed": sorted(changed, key=lambda e: e["meeting_page_id"]),
            "already_reviewed": sorted(already, key=lambda e: e["meeting_page_id"]),
            "missing_ids": sorted(ids - found),
        }


async def list_jurisdiction_bleed_backfill_candidates() -> dict:
    """Read-only audit, same role/template as
    list_hallucination_candidate_transcript_versions() above: re-runs
    finalize_jurisdiction() (app/utils/jurisdiction_enrich.py) against
    every already-archived MeetingPage's CURRENT stored `jurisdiction`
    value, to size how many pages a future backfill of the 2026-08-17
    Canadian-data + Title-Case-bleed fixes (BACKLOG.md's
    "Jurisdiction-bleed, confirmed cross-platform" entry) would actually
    touch. This session's own fixes are code-only and were explicitly
    scoped to NOT re-process already-archived pages -- see that entry --
    so this just answers "how many, if someone chooses to" without
    changing anything itself.

    A row counts as a candidate when re-running finalize_jurisdiction()
    on its own already-stored value produces a *different* jurisdiction
    string or a *better* confidence tier than what's on the row today --
    safe to compare directly since the stored value is already whatever
    the LAST finalize_jurisdiction() run produced for it (see
    _find_or_create_page()'s own call), so re-running it now is
    idempotent for any row neither fix actually changes.
    """
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    MeetingPage.id,
                    MeetingPage.slug,
                    MeetingPage.title,
                    MeetingPage.jurisdiction,
                    MeetingPage.jurisdiction_confidence,
                    MeetingPage.source_url_normalized,
                ).where(MeetingPage.jurisdiction.is_not(None))
            )
        ).all()

        candidates = []
        for page_id, slug, title, jurisdiction, confidence, source_url in rows:
            netloc = urlparse(source_url).netloc if source_url else None
            result = finalize_jurisdiction(jurisdiction, netloc=netloc)
            if result.jurisdiction == jurisdiction and result.confidence == confidence:
                continue
            candidates.append(
                {
                    "meeting_page_id": page_id,
                    "slug": slug,
                    "title": title,
                    "current_jurisdiction": jurisdiction,
                    "current_confidence": confidence,
                    "repaired_jurisdiction": result.jurisdiction,
                    "repaired_confidence": result.confidence,
                }
            )

        return {"total_checked": len(rows), "candidates": candidates}


async def apply_jurisdiction_bleed_backfill(
    *,
    dry_run: bool = True,
    only_ids: Optional[Set[int]] = None,
    exclude_ids: Optional[Set[int]] = None,
) -> dict:
    """Write counterpart to list_jurisdiction_bleed_backfill_candidates()
    above -- actually patches MeetingPage.jurisdiction /
    jurisdiction_confidence for rows where finalize_jurisdiction() produces
    a genuinely different jurisdiction STRING today (BACKLOG.md's
    "Jurisdiction-bleed, confirmed cross-platform" backfill). Deliberately
    narrower than the read-only audit: a confidence-tier-only change (e.g.
    null -> "validated" with the same string) isn't worth a write and is
    excluded here, unlike the audit above which reports both kinds.

    Always recomputes candidates itself from each row's own stored
    `jurisdiction` + `source_url_normalized` -- never accepts a
    caller-supplied jurisdiction string to write, so a stale or forged
    request body can't push arbitrary text into the column. Only the
    `jurisdiction` and `jurisdiction_confidence` columns are touched; every
    other MeetingPage field (title, video_url, segments, ...) is left
    alone.

    dry_run=True (the default) computes and returns the exact before/after
    diff without writing anything -- mirrors this repo's existing
    read-only-first pattern for internal tooling. dry_run=False commits the
    updates and returns the same before/after shape for an audit trail.

    `only_ids` / `exclude_ids` (sets of MeetingPage ids) narrow which rows
    may be written -- added 2026-08-21 (WO-22) for a real, concrete need:
    the production audit's candidate set was NOT uniformly safe to apply
    (BACKLOG.md's "Bare/state-suffixed jurisdiction duplicates" entry --
    the 83 text-changing rows included two confidently-wrong subdomain
    repairs, "Alameda County, CA" -> "Bart, CA" and "Modesto, CA" ->
    "Agenda, CA"), and with no per-id filter the only options were "apply
    everything" or "apply nothing". Both are applied to the recomputed
    candidate list, not to the SELECT: every row is still re-checked
    against today's finalize_jurisdiction() and the filters only decide
    what may be WRITTEN, so a caller can't use them to smuggle in a row
    the recompute wouldn't have changed anyway. `exclude_ids` wins over
    `only_ids` when a row is in both (deny beats allow -- the safer
    reading of a contradictory request).
    """
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    MeetingPage.id,
                    MeetingPage.slug,
                    MeetingPage.title,
                    MeetingPage.jurisdiction,
                    MeetingPage.jurisdiction_confidence,
                    MeetingPage.source_url_normalized,
                ).where(MeetingPage.jurisdiction.is_not(None))
            )
        ).all()

        changes = []
        skipped_by_filter = 0
        for page_id, slug, title, jurisdiction, confidence, source_url in rows:
            netloc = urlparse(source_url).netloc if source_url else None
            result = finalize_jurisdiction(jurisdiction, netloc=netloc)
            if result.jurisdiction == jurisdiction:
                continue
            if (only_ids is not None and page_id not in only_ids) or (
                exclude_ids is not None and page_id in exclude_ids
            ):
                skipped_by_filter += 1
                continue
            changes.append(
                {
                    "meeting_page_id": page_id,
                    "slug": slug,
                    "title": title,
                    "before": {
                        "jurisdiction": jurisdiction,
                        "jurisdiction_confidence": confidence,
                    },
                    "after": {
                        "jurisdiction": result.jurisdiction,
                        "jurisdiction_confidence": result.confidence,
                    },
                }
            )

        if not dry_run and changes:
            for change in changes:
                page = await session.get(MeetingPage, change["meeting_page_id"])
                if page is None:
                    continue
                page.jurisdiction = change["after"]["jurisdiction"]
                page.jurisdiction_confidence = change["after"][
                    "jurisdiction_confidence"
                ]
            await session.commit()

        return {
            "dry_run": dry_run,
            "applied_count": len(changes),
            "skipped_by_filter": skipped_by_filter,
            "changes": changes,
        }


async def clear_future_meeting_dates(
    *,
    dry_run: bool = True,
    grace_days: int = 7,
    only_ids: Optional[Set[int]] = None,
) -> dict:
    """Null out MeetingPage.date on rows whose stored date lies further
    than `grace_days` in the future -- same recompute-only,
    dry-run-first shape as apply_jurisdiction_bleed_backfill() above
    (never accepts a caller-supplied replacement date; the only write it
    can ever perform is date -> NULL on a row the recompute itself
    flagged).

    Why this exists (2026-08-23, found via Google's crawl of
    /state/california): Granicus's body-text date fallback used to store
    a future date mined from arbitrary agenda text as the meeting's own
    date -- confirmed on three real customers (Mission Viejo's
    "General Municipal Election on November 3, 2026" item, Tulsa's
    "term expires December 31, 2026", Tarrant County College's
    "Services Through August 31, 2026"). The extraction is fixed (the
    body scan now rejects future matches, and the RSS item date beats a
    body guess -- see granicus.py), but a re-ingest can't repair the
    stored rows: `page.date = payload.get("date") or page.date` is
    truthy-gated on purpose, so an honest date=None re-resolve keeps the
    wrong stored date forever. A NULL date renders fine everywhere
    (date-less pages already exist) and is strictly more honest than a
    fabricated future one.

    `grace_days` keeps genuinely-scheduled near-future meetings intact:
    a real agenda page can legitimately be published days ahead
    (confirmed live: Sarasota County's OnBase agenda for an Aug 25
    meeting, resolved Aug 23), but no real recorded meeting sits months
    out. Rows inside the window are reported (as "kept_in_grace_window")
    but never touched.
    """
    today = datetime.now(timezone.utc).date()
    cutoff = (today + timedelta(days=max(0, grace_days))).isoformat()
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    MeetingPage.id,
                    MeetingPage.slug,
                    MeetingPage.date,
                    MeetingPage.platform,
                ).where(MeetingPage.date > today.isoformat())
            )
        ).all()

        changes = []
        kept_in_grace_window = []
        skipped_by_filter = 0
        for page_id, slug, date, platform in rows:
            # The column is a string; the SQL `>` above is a lexical
            # compare that a non-ISO value (e.g. a stray "Sept ..."
            # shape, see /internal/date-format-audit) can satisfy
            # spuriously. Only a clean ISO date is ever eligible.
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
                continue
            entry = {
                "meeting_page_id": page_id,
                "slug": slug,
                "platform": platform,
                "date": date,
            }
            if date <= cutoff:
                kept_in_grace_window.append(entry)
                continue
            if only_ids is not None and page_id not in only_ids:
                skipped_by_filter += 1
                continue
            changes.append(entry)

        if not dry_run and changes:
            for change in changes:
                page = await session.get(MeetingPage, change["meeting_page_id"])
                if page is not None:
                    page.date = None
            await session.commit()

        return {
            "dry_run": dry_run,
            "cutoff": cutoff,
            "cleared_count": len(changes),
            "cleared": changes,
            "kept_in_grace_window": kept_in_grace_window,
            "skipped_by_filter": skipped_by_filter,
        }


async def get_page_by_slug(slug: str) -> Optional[dict]:
    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        if page is None:
            return None

        versions = (
            (
                await session.execute(
                    select(TranscriptVersion)
                    .where(TranscriptVersion.meeting_page_id == page.id)
                    .order_by(
                        TranscriptVersion.is_default.desc(),
                        TranscriptVersion.created_at.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

        return {
            "id": page.id,
            "slug": page.slug,
            "platform": page.platform,
            "title": page.title,
            "date": page.date,
            "jurisdiction": page.jurisdiction,
            # Both added 2026-08-15 alongside the columns themselves --
            # deliberately included from the start rather than repeating
            # the exact "platform" key omission this same function's own
            # docstring/test (test_get_page_by_slug_includes_platform)
            # documents as a real, previously-shipped bug.
            "meeting_body": page.meeting_body,
            "jurisdiction_confidence": page.jurisdiction_confidence,
            "video_url": page.video_url,
            "video_format": page.video_format,
            "agenda_items": page.agenda_items or [],
            "video_warnings": page.video_warnings or [],
            "agenda_link": page.agenda_link,
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


def _escape_like(term: str) -> str:
    """Escapes `\\`, `%`, `_` so a literal one of these typed in a search
    box is matched literally against `search_corpus`, not treated as a
    LIKE wildcard/escape character."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _corpus_contains(term: str):
    """`LIKE`, deliberately not `ILIKE`: `search_corpus` is lowercased by
    construction (compute_search_corpus() -> build_corpus() -> .lower())
    and parse_query() lowercases every term, so the two are the same
    predicate -- but Postgres's ILIKE lowercases the *whole document* per
    row via locale case-folding before matching, and these documents are
    multi-hundred-KB transcripts. Measured 2026-08-17 on a real
    postgres:16 with 1,219 x 300KB docs + the pg_trgm GIN index: ILIKE
    7.7s vs LIKE 1.75s for `%budget%` (identical gap with the index
    disabled, so it's the recheck/case-fold, not index selection). SQLite's
    LIKE is ASCII-case-insensitive anyway, so dev/CI behave the same."""
    return MeetingPage.search_corpus.like(f"%{_escape_like(term)}%", escape="\\")


def _keyword_conditions(keyword: str, fuzzy: bool) -> tuple[list, list[str]]:
    """Translates `keyword` into SQL conditions against
    `MeetingPage.search_corpus`, plus the list of unquoted words that
    still need Python-side fuzzy matching (empty in exact mode).

    In exact mode the SQL is *authoritative*, not a pre-filter: `matches()`
    (archive/utils/search.py) decides exact mode as `term in corpus` where
    `corpus` is `build_corpus(title, jurisdiction, agenda, transcript)` --
    and `search_corpus` is `compute_search_corpus()`, which is that same
    `build_corpus()` over the same four fields, lowercased, with
    `parse_query()` lowercasing the terms. `ILIKE '%term%'` on that column
    is therefore literally the same predicate; re-running it in Python
    over freshly-loaded transcript JSON (what list_pages() did before
    2026-08-17) added nothing but the memory/latency that OOM-crashed the
    Archive on common terms -- see BACKLOG_DONE.md. Phrases and exclusions
    are exact in both modes (matches()'s own rule), so they always go to
    SQL. Runs identically on Postgres (where the GIN trigram index makes
    it fast) and SQLite (dev/CI, unindexed but the same code path).

    Fuzzy words are the one thing this function can't decide: matches()'s
    bounded Levenshtein against real corpus words has no recall-safe SQL
    equivalent -- pg_trgm's word_similarity() over a multi-hundred-KB
    document is either too loose to narrow anything (at a recall-safe
    threshold) or drops genuine 2-edit typos (anything selective), and
    costs tens of ms of server CPU per row either way. So fuzzy words are
    returned for the caller to check in Python over the corpus text --
    streamed one row at a time (see list_pages()), never the transcript
    JSON. This is now only the fallback path: on Postgres with
    search_vocabulary present, list_pages() uses
    _fuzzy_keyword_conditions_via_vocabulary() instead, which makes fuzzy
    SQL-authoritative too (a small trigram-indexed word table, not
    word_similarity() over whole documents) -- see that function's
    docstring and BACKLOG_DONE.md's search entry. This function's fuzzy
    branch still runs on SQLite (dev/CI) or Postgres before that
    migration, where fuzzy stays the opt-in, UI-labeled "slower" mode.
    """
    phrases, words, excluded_phrases, excluded_words = parse_query(keyword)
    conditions = [_corpus_contains(p) for p in phrases]
    conditions += [~_corpus_contains(p) for p in excluded_phrases]
    conditions += [~_corpus_contains(w) for w in excluded_words]
    if fuzzy:
        return conditions, list(words)
    conditions += [_corpus_contains(w) for w in words]
    return conditions, []


# --- Search Step 2a: Postgres full-text search over search_corpus ---------
#
# meeting_pages.search_tsv is a GENERATED tsvector column added by Alembic
# revision c1d2e3f4a5b6, Postgres-only, and deliberately NOT mapped on the
# MeetingPage model (so SQLite / create_all() / ORM inserts never see it).
# It's referenced only through the literal below, and only after
# _fts_available() has confirmed the column exists on the connected DB --
# which is what lets the migration and this code deploy in either order
# (the 2026-08-17 UndefinedColumnError incident was exactly a model column
# arriving before its migration; see BACKLOG_DONE.md).

_SEARCH_TSV = literal_column("meeting_pages.search_tsv")
_FTS_CONFIG = "english"
_FTS_CHECK_TTL = timedelta(seconds=60)
_fts_state: dict[str, Any] = {"available": None, "checked_at": None}


async def _fts_available(session) -> bool:
    """True when the connected DB is Postgres AND meeting_pages.search_tsv
    exists. Cached for _FTS_CHECK_TTL so a search costs at most one extra
    ~1ms information_schema lookup a minute, and so running the migration
    against a live service flips FTS on within a minute with no restart.
    Always False on SQLite (dev/CI) -- the LIKE path stays the tested,
    dialect-agnostic fallback there."""
    if session.bind.dialect.name != "postgresql":
        return False
    now = datetime.now(timezone.utc)
    checked_at = _fts_state["checked_at"]
    if checked_at is not None and now - checked_at < _FTS_CHECK_TTL:
        return bool(_fts_state["available"])
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'meeting_pages' AND column_name = 'search_tsv'"
            )
        )
    ).first()
    _fts_state["available"] = row is not None
    _fts_state["checked_at"] = now
    return bool(_fts_state["available"])


def _fts_query(keyword: str):
    """The tsquery for a user's search string. websearch_to_tsquery()
    natively understands the syntax parse_query() already accepts --
    "quoted phrase" (adjacency), -word / -"phrase" (exclusion), bare words
    ANDed -- and adds `OR` (BACKLOG.md's "no OR support" gap closes for
    free), stemming (budget/budgets/budgeting) and stopword removal via
    the 'english' config. `+`/`&`/`and` (parse_query()'s no-ops) become
    punctuation/stopwords, i.e. still no-ops. Never raises on odd input
    (unbalanced quotes etc.) -- that's why it's used over to_tsquery()."""
    return func.websearch_to_tsquery(_FTS_CONFIG, keyword)


def _fts_condition(keyword: str):
    """`search_tsv @@ websearch_to_tsquery(...)` -- answered from the GIN
    index on the tsvector; never reads search_corpus, which is why it
    stays fast on a common word where the trigram LIKE path had to
    detoast and scan every candidate's whole document (16.5s mean under
    load on prod, 2026-08-17)."""
    return _SEARCH_TSV.op("@@")(_fts_query(keyword))


def _fts_rank(keyword: str):
    """ts_rank_cd(search_tsv, query): cover-density relevance, for
    sort=relevance. Reads the tsvector (not the corpus) for each matched
    row, so it's the one FTS operation that scales with match count --
    opt-in, default order stays newest-first."""
    return func.ts_rank_cd(_SEARCH_TSV, _fts_query(keyword))


# --- Search Step 2b: trigram-indexed vocabulary for fast fuzzy search -----
#
# search_vocabulary is a real table (unlike search_tsv's generated column),
# added by Alembic revision c684908ce5ff, populated by
# _upsert_vocabulary_words() (called from _refresh_search_corpus()) and
# cross-dialect on the model -- but only ever *queried* on Postgres, same
# "feature-detect, don't assume the migration has run" discipline as
# _fts_available(), gated by _vocab_available() below.

_VOCAB_CHECK_TTL = timedelta(seconds=60)
_vocab_state: dict[str, Any] = {"available": None, "checked_at": None}

# pg_trgm's own default. A recall-safe *first pass* only -- every
# candidate this turns up still gets re-verified against the exact same
# _levenshtein()/_fuzzy_threshold() matches() itself uses, so a threshold
# that's too loose costs a few wasted candidate checks, never a wrong
# answer. Needs the same real-data tuning pass Step 1's fuzzy work got
# once this has run against production for a while -- see BACKLOG.md.
_VOCAB_SIMILARITY_THRESHOLD = 0.3
_VOCAB_CANDIDATE_LIMIT = 50


async def _vocab_available(session) -> bool:
    """True when the connected DB is Postgres AND search_vocabulary
    exists. Byte-for-byte mirror of _fts_available()'s caching/dialect/
    fallback shape -- see that function's docstring; the only difference
    is checking information_schema.tables (a whole table) rather than
    .columns (search_tsv is a column on an existing table)."""
    if session.bind.dialect.name != "postgresql":
        return False
    now = datetime.now(timezone.utc)
    checked_at = _vocab_state["checked_at"]
    if checked_at is not None and now - checked_at < _VOCAB_CHECK_TTL:
        return bool(_vocab_state["available"])
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'search_vocabulary'"
            )
        )
    ).first()
    _vocab_state["available"] = row is not None
    _vocab_state["checked_at"] = now
    return bool(_vocab_state["available"])


def _vocab_candidate_stmt(term: str, limit: int):
    """Pure statement builder, no DB access -- unit-testable via
    .compile() the same way _fts_condition() is. The `%` operator (not a
    bare `similarity() > threshold` call) is what makes the planner use
    search_vocabulary's GIN trigram index; it reads
    pg_trgm.similarity_threshold, which the caller must SET LOCAL first.
    `term` is bound as a parameter (SQLAlchemy's normal Core behavior),
    never string-interpolated -- it's user search input."""
    return (
        select(SearchVocabulary.word)
        .where(SearchVocabulary.word.op("%")(term))
        .order_by(func.similarity(SearchVocabulary.word, term).desc())
        .limit(limit)
    )


async def _fuzzy_keyword_conditions_via_vocabulary(session, keyword: str) -> list:
    """SQL-authoritative fuzzy search: the vocabulary-lookup replacement
    for _keyword_conditions()'s Python-streamed fuzzy path. Phrases and
    exclusions are always exact (matches()'s own rule, unaffected by
    fuzzy) so they go through _corpus_contains() exactly as
    _keyword_conditions() already does.

    Each unquoted word:
    - _fuzzy_threshold(word) == 0 (<=4 chars, matches()'s own "short
      words require exact" rule) -- no vocabulary lookup needed, becomes
      a plain _corpus_contains(word) exact condition. Note: matches()'s
      own fuzzy branch checks *token* membership for these
      (`word in corpus_words`), while _corpus_contains() is a substring
      check -- the same deliberate substring-is-the-system's-canonical-
      "contains" redefinition Step 1 already made for every other exact
      term, extended here for consistency rather than reintroducing a
      token-boundary special case.
    - otherwise -- queries search_vocabulary via _vocab_candidate_stmt()
      (a small, index-accelerated candidate set), re-verifies every
      candidate against the *exact* _levenshtein()/_fuzzy_threshold()
      matches() uses (byte-for-byte parity -- the trigram step is purely
      a fast candidate generator, never the final decision), then becomes
      an OR of _corpus_contains() over the confirmed real words. A term
      with zero confirmed candidates becomes `false()`, not a skipped
      condition -- a fuzzy term with no real match anywhere in the
      archive must fail the whole AND, exactly like _keyword_conditions()
      already requires (via matches()'s "not any(...)" semantics).

    Returns conditions only, no fuzzy_words list -- nothing downstream in
    list_pages() needs Python-side streaming after this.
    """
    phrases, words, excluded_phrases, excluded_words = parse_query(keyword)
    conditions = [_corpus_contains(p) for p in phrases]
    conditions += [~_corpus_contains(p) for p in excluded_phrases]
    conditions += [~_corpus_contains(w) for w in excluded_words]

    fuzzy_words = [w for w in words if _fuzzy_threshold(w) > 0]
    conditions += [_corpus_contains(w) for w in words if _fuzzy_threshold(w) == 0]

    if fuzzy_words:
        # Scoped to this transaction only (SET LOCAL), never leaks to any
        # other query on this connection. Postgres doesn't support a bind
        # parameter here (SET doesn't accept $1-style placeholders) --
        # safe to interpolate since this is a fixed module constant, not
        # user input.
        await session.execute(
            text(
                f"SET LOCAL pg_trgm.similarity_threshold = {_VOCAB_SIMILARITY_THRESHOLD}"
            )
        )
        for term in fuzzy_words:
            threshold = _fuzzy_threshold(term)
            candidates = (
                (
                    await session.execute(
                        _vocab_candidate_stmt(term, _VOCAB_CANDIDATE_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
            confirmed = [
                w
                for w in candidates
                if w == term or _levenshtein(term, w, threshold) <= threshold
            ]
            conditions.append(
                or_(*(_corpus_contains(w) for w in confirmed)) if confirmed else false()
            )

    return conditions


def _has_agenda_condition():
    """SQL equivalent of Python's `bool(mp.agenda_items)`. agenda_items is
    a JSON column that can hold SQL NULL (older rows), JSON `null`
    (SQLAlchemy's default for a Python None -- `none_as_null` is off), or
    `[]` (what ingest writes when the resolver sent nothing, crud.py's
    `payload.get("agenda_items") or []`) -- all three are "no agenda".
    Compared as text rather than via json_array_length(), which raises on
    Postgres for a JSON scalar like `null`. Portable across Postgres JSON
    (`::text` yields the stored JSON text verbatim) and SQLite (already
    text). The app only ever writes json.dumps output, so an empty array
    is exactly `[]`, never `[ ]`.
    """
    return and_(
        MeetingPage.agenda_items.is_not(None),
        cast(MeetingPage.agenda_items, Text).not_in(("[]", "null")),
    )


def _is_empty_page_condition():
    """SQL predicate for a "zero-value" page: no video, no agenda items, no
    agenda link, and no TranscriptVersion of any kind. Such a page has
    nothing a visitor can watch or read -- just a title/date shell.

    Deliberately a *query-time* predicate, not a stored flag or a delete
    (Ryan's call, 2026-08-17 -- see CLAUDE_BACKLOG.md's "Archive
    hygiene" section for the live numbers behind it): 17 of ~1,200 prod
    pages matched at the time, several of them recent or not-yet-held
    meetings whose source will publish video/captions days-to-weeks later
    (the exact case ARCHIVE_RECHECK_AFTER exists for). Evaluating "empty"
    live means such a page reappears in browse/sitemap/feed the moment a
    recheck fills anything in, with no un-hide step, and a future-dated
    meeting is never permanently judged. It also needs no schema change
    (a new column would be an Alembic-migration case, see CLAUDE.md), and
    hard-deleting would orphan SavedItem rows and break already-shared
    /m/ links. The page itself keeps serving at /m/{slug} regardless --
    meeting_page.html just noindexes it while it's empty.

    "Any TranscriptVersion", not "a default one": a version that exists
    but was demoted still means the page holds real text.
    """
    # Aliased + explicitly correlated to MeetingPage only: list_pages()
    # already outer-joins TranscriptVersion (the default version) in the
    # outer query, and without the alias SQLAlchemy auto-correlates that
    # table away too, leaving the subquery with no FROM at all.
    any_version = aliased(TranscriptVersion)
    has_any_version = (
        select(any_version.id)
        .where(any_version.meeting_page_id == MeetingPage.id)
        .correlate(MeetingPage)
        .exists()
    )
    return and_(
        or_(MeetingPage.video_url.is_(None), MeetingPage.video_url == ""),
        or_(MeetingPage.agenda_link.is_(None), MeetingPage.agenda_link == ""),
        ~_has_agenda_condition(),
        ~has_any_version,
    )


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
    created_after: Optional[datetime] = None,
    sort: str = "newest",
) -> dict:
    """Paginated meeting list behind /meetings (and the saved-search alert
    sweep, via find_new_matches_for_saved_search()).

    Every filter is applied in SQL -- jurisdiction (via
    jurisdiction_search_terms()'s state-name expansion), date range,
    created_after, has_transcript, has_agenda (_has_agenda_condition()),
    and keyword search. Pagination is LIMIT/OFFSET plus one COUNT(*), so a
    plain browse or a keyword search costs O(page_size) memory no matter
    how many meetings match -- the 2026-08-17 rewrite, after the previous
    shape (SQL pre-filter, then load every candidate's full transcript
    JSON for a Python re-check, then paginate in Python) OOM-crashed the
    Archive on common terms and took 25-35s when it survived. See
    BACKLOG_DONE.md.

    Keyword search has two SQL forms, chosen per request by
    _fts_available() (Search Step 2a, 2026-08-17):
    - **Full-text (Postgres with the search_tsv column present)**:
      `search_tsv @@ websearch_to_tsquery('english', keyword)` -- answered
      from the GIN index on the generated tsvector without reading the
      corpus, so cost no longer scales with how common the word is
      (the trigram LIKE path had to detoast + scan every candidate's whole
      document: 16.5s mean under real load on prod for "budget"). Adds
      stemming, stopword removal and `OR`; phrases/exclusions keep their
      meaning. Semantics therefore differ slightly from matches(): a
      substring inside a longer word ("cat" in "concatenate") no longer
      matches, an all-stopword query ("the") matches nothing.
    - **LIKE (SQLite, or Postgres before the migration has run)**:
      _keyword_conditions() against `search_corpus` -- byte-for-byte
      matches()'s exact mode. This is what dev/CI exercise.
    `sort="relevance"` (only meaningful with a keyword, FTS only) orders
    by ts_rank_cd(); the default "newest" keeps created_at DESC so the
    UX doesn't change under anyone.

    Fuzzy mode has its own two-tier fallback (Search Step 2b, once
    Alembic revision c684908ce5ff is applied):
    - **Vocabulary-backed (Postgres with search_vocabulary present)**:
      SQL-authoritative, same as exact/FTS -- see
      _fuzzy_keyword_conditions_via_vocabulary(). Each fuzzy word is
      trigram-matched against the small, GIN-indexed vocabulary table,
      re-verified with the exact same Levenshtein check matches() uses,
      and the confirmed real words are checked against search_corpus via
      the already-fast Step 1 LIKE path. O(page_size) memory, like
      everything else.
    - **Python-streamed (SQLite dev/CI, or Postgres before that
      migration)**: unquoted words are matched in Python by matches()'s
      bounded Levenshtein against each candidate's `search_corpus` text
      (not transcript JSON), streamed one row at a time so memory stays
      bounded, and paginated in Python. Measured ~5ms/doc CPU, so a few
      seconds across the whole archive -- slow but no longer a crash; the
      UI already labels fuzzy "slower". Why SQL alone can't do this
      without a vocabulary table: see _keyword_conditions().
    Phrases and exclusions are always exact and always narrow in SQL
    first, in both tiers.

    Snippets are built only for the page of rows actually returned, from
    the *default* transcript version's segments (loaded for those <=
    page_size rows only) plus agenda text -- deliberately not from
    `search_corpus`, which spans every version: a query that only matches
    an old, demoted version's text should still find the page, but never
    show an excerpt the page itself doesn't display (real bug fixed
    2026-08-08). See find_snippet().

    The keyword search covers *every* TranscriptVersion of a page (the
    corpus is computed over all of them, see compute_search_corpus()), so
    a demoted version's text still counts toward a match while the
    listing's language/has_transcript badge reflects the default version
    only. `date` is an ISO "YYYY-MM-DD" string, so lexicographic
    comparison is chronological. `created_after` filters
    MeetingPage.created_at (when archived), a different axis from
    date_from/date_to (when the meeting happened) -- used by the alert
    sweep's "new since last check".

    Empty pages (_is_empty_page_condition(): no video, no agenda, no
    transcript) are excluded by default -- a plain browse or keyword
    search shouldn't surface a title-only shell. The exclusion is
    deliberately *off* whenever has_transcript or has_agenda is set
    explicitly: `has_transcript=false` is how gaps get found and worked
    on, so it must keep showing everything without a transcript, empties
    included (Ryan, 2026-08-17). `has_transcript=true`/`has_agenda=true`
    already imply non-empty, so nothing is lost there either.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    conditions = []
    if has_transcript is None and has_agenda is None:
        conditions.append(~_is_empty_page_condition())
    if jurisdiction:
        terms = jurisdiction_search_terms(jurisdiction)
        conditions.append(
            or_(*(MeetingPage.jurisdiction.ilike(f"%{t}%") for t in terms))
        )
    if date_from:
        conditions.append(MeetingPage.date >= date_from)
    if date_to:
        conditions.append(MeetingPage.date <= date_to)
    if created_after:
        conditions.append(MeetingPage.created_at > created_after)
    if has_transcript is True:
        conditions.append(TranscriptVersion.id.is_not(None))
    elif has_transcript is False:
        conditions.append(TranscriptVersion.id.is_(None))
    if has_agenda is True:
        conditions.append(_has_agenda_condition())
    elif has_agenda is False:
        conditions.append(~_has_agenda_condition())
    # Explicit columns, not the MeetingPage entity: keeps every row light
    # (no identity map, no chance of a deferred column sneaking back in)
    # and lets the fuzzy path stream + discard each corpus as it goes.
    # id DESC as a tiebreaker makes pagination stable when many pages
    # share a created_at (bulk ingests do).
    default_version = and_(
        TranscriptVersion.meeting_page_id == MeetingPage.id,
        TranscriptVersion.is_default.is_(True),
    )
    columns = [
        MeetingPage.id,
        MeetingPage.slug,
        MeetingPage.title,
        MeetingPage.date,
        MeetingPage.jurisdiction,
        MeetingPage.meeting_body,
        MeetingPage.platform,
        MeetingPage.agenda_items,
        TranscriptVersion.language,
        TranscriptVersion.id,
        TranscriptVersion.transcript_warnings,
    ]

    async with async_session() as session:
        # Keyword form is decided here, per request, because detecting the
        # FTS column / vocabulary table needs a session. Fuzzy mode never
        # uses FTS. When search_vocabulary is available (Step 2b), fuzzy
        # is SQL-authoritative too -- see
        # _fuzzy_keyword_conditions_via_vocabulary() -- and fuzzy_words
        # stays empty, same as the FTS branch. Only pre-migration Postgres
        # or SQLite (dev/CI) still falls through to the Python-streamed
        # path below.
        fuzzy_words: list[str] = []
        order_by = [MeetingPage.created_at.desc(), MeetingPage.id.desc()]
        if keyword:
            if not fuzzy and await _fts_available(session):
                conditions.append(_fts_condition(keyword))
                if sort == "relevance":
                    order_by.insert(0, _fts_rank(keyword).desc())
            elif fuzzy and await _vocab_available(session):
                conditions.extend(
                    await _fuzzy_keyword_conditions_via_vocabulary(session, keyword)
                )
            else:
                keyword_conditions, fuzzy_words = _keyword_conditions(keyword, fuzzy)
                conditions.extend(keyword_conditions)
        if fuzzy_words:
            columns.append(MeetingPage.search_corpus)
        stmt = (
            select(*columns)
            .outerjoin(TranscriptVersion, default_version)
            .order_by(*order_by)
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))

        if fuzzy_words:
            # Python-authoritative for the fuzzy words; stream so at most
            # one corpus text is in memory at a time. `keyword` is passed
            # whole to matches() -- it re-parses phrases/exclusions and
            # re-checks them too, which is redundant with the SQL above
            # but harmless (they already hold for every row we see).
            matched: list[tuple] = []
            result = await session.stream(stmt.execution_options(yield_per=200))
            async for row in result:
                corpus = row[-1] or ""
                if matches(keyword, corpus, tokenize(corpus), True):
                    matched.append(tuple(row[:-1]))
            total = len(matched)
            start = (page - 1) * page_size
            page_rows = matched[start : start + page_size]
        else:
            # One scan, not two: the total rides along as a window
            # aggregate on the same LIMIT/OFFSET query. A keyword LIKE
            # over huge TOASTed corpora costs ~seconds per pass on
            # Postgres (see _corpus_contains()), so a separate COUNT(*)
            # doubled the whole request. Only a page past the end (no
            # rows, so no window value) still needs the standalone count.
            paged = (
                await session.execute(
                    stmt.add_columns(func.count().over().label("total"))
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            ).all()
            if paged:
                total = paged[0][-1]
                page_rows = [tuple(r[:-1]) for r in paged]
            else:
                page_rows = []
                count_stmt = (
                    select(func.count())
                    .select_from(MeetingPage)
                    .outerjoin(TranscriptVersion, default_version)
                )
                if conditions:
                    count_stmt = count_stmt.where(and_(*conditions))
                total = (await session.execute(count_stmt)).scalar_one()

        # Snippet inputs for the returned rows only: the default version's
        # segments (see the docstring for why not search_corpus).
        default_segments_by_page: dict[int, list] = {}
        if keyword and page_rows:
            page_ids = [r[0] for r in page_rows]
            seg_rows = (
                await session.execute(
                    select(
                        TranscriptVersion.meeting_page_id, TranscriptVersion.segments
                    ).where(
                        TranscriptVersion.meeting_page_id.in_(page_ids),
                        TranscriptVersion.is_default.is_(True),
                    )
                )
            ).all()
            default_segments_by_page = {pid: segs or [] for pid, segs in seg_rows}

    def _snippet_for(page_id: int, agenda_items: Optional[list]) -> Optional[str]:
        # Deliberately excludes title/jurisdiction (see find_snippet()'s
        # docstring) since those already render directly above this in
        # meeting_list.html.
        if not keyword:
            return None
        agenda_text = " ".join(item.get("text", "") for item in (agenda_items or []))
        transcript_text = " ".join(
            seg.get("text", "") for seg in default_segments_by_page.get(page_id, [])
        )
        return find_snippet(keyword, [transcript_text, agenda_text], fuzzy)

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "pages": [
            {
                "slug": slug,
                "title": title,
                "date": date,
                "jurisdiction": jurisdiction_,
                "meeting_body": meeting_body,
                "platform": platform,
                "language": lang,
                # Quality-aware, not just "a version exists" -- a garbled
                # transcript shouldn't earn the same "Transcript" badge as
                # a real one. Language-independent on purpose (any
                # language counts, per explicit request) -- only quality
                # is gated. Same quality check as _has_good_transcript()
                # (via _has_real_warning_free_transcript()), inlined here
                # since transcript_warnings already rides along in the
                # main query -- re-querying per row would be a real N+1.
                "has_transcript": (
                    version_id is not None
                    and _has_real_warning_free_transcript(warnings)
                ),
                "has_agenda": bool(agenda_items),
                "snippet": _snippet_for(page_id, agenda_items),
                # "upcoming" / "recent" / None -- drives the date pill in
                # meeting_list.html. Any version at all counts as "has a
                # transcript" for this purpose (a garbled one is still
                # something the source published, so there's nothing left
                # to wait for), unlike the quality-gated badge above.
                "date_status": meeting_date_status(
                    date, has_transcript=version_id is not None
                ),
            }
            for (
                page_id,
                slug,
                title,
                date,
                jurisdiction_,
                meeting_body,
                platform,
                agenda_items,
                lang,
                version_id,
                warnings,
            ) in page_rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


async def find_new_matches_for_saved_search(
    search_params: dict, since: Optional[datetime]
) -> list[dict]:
    """The alert sweep's core query (archive/search_alerts.py) -- reuses
    list_pages() wholesale rather than reimplementing its filter/keyword/
    fuzzy logic, scoped to pages archived after `since` via
    `created_after`.

    `search_params` is stored using /meetings's own query-param name `q`
    (see SavedItem.search_params's docstring) -- list_pages()'s own
    keyword param is `keyword`, so a bare `list_pages(**search_params)`
    raises TypeError. Translated here rather than at every call site.
    """
    params = dict(search_params)
    keyword = params.pop("q", None)
    result = await list_pages(
        page_size=100,
        keyword=keyword,
        created_after=since,
        jurisdiction=params.get("jurisdiction"),
        date_from=params.get("date_from"),
        date_to=params.get("date_to"),
        has_agenda=params.get("has_agenda"),
        has_transcript=params.get("has_transcript"),
        fuzzy=bool(params.get("fuzzy", False)),
    )
    return result["pages"]


# The shared, multi-tenant vendor platforms -- one row each on /coverage,
# roughly ordered to match README.md's "Supported platforms" table. Most
# host video directly (or, for Viebit/Cablecast, are reached by
# delegation but ARE the real host); a few (hyland, destinyhosted,
# open_media) are agenda/CMS front-ends that hand video off elsewhere but
# still deserve their own row, because they're the page a visitor
# actually pastes and -- unlike the routers below -- a real archived page
# can still be attributed back to them. The line this dict draws against
# CUSTOM_PLATFORMS is "one product many jurisdictions buy" vs. "a bespoke
# scraper this app wrote for one government", NOT "hosts video" vs.
# "doesn't". Deliberately excludes
# Legistar/CivicPlus/PrimeGov/CivicWeb: those are calendar-tool detection
# routers that delegate to one of the platforms below via
# resolve_via_platform() (or, for CivicWeb, a direct YouTubeAssetFinder
# call) -- on every real, successfully-ingested push the delegated
# finder's own ResolvedMeeting is returned as-is, so MeetingPage.platform
# ends up "granicus"/"youtube"/etc., never "legistar"/"civicplus"/
# "primegov"/"civicweb" (confirmed by reading each adapter's resolve() --
# platform=self.platform_name only ever appears on their error-path
# returns, which are never pushed to the Archive since a push requires
# real segments/agenda_items). Listing them here would mean every one of
# those rows stays permanently exampleless, not because nothing's
# supported but because the label itself never occurs -- coverage.html
# adds a short note about these wrapper platforms instead of a row that
# can never have a demo. iqm2 and hyland both *can* embed/delegate a
# video from elsewhere (a raw Granicus HLS URL for iqm2; an occasional
# YouTube fallback for hyland -- see each adapter's own docstring) but,
# unlike the routers above, neither overrides ResolvedMeeting.platform
# when doing so -- confirmed by reading both adapters' resolve() end to
# end, platform=self.platform_name on every return path -- so they're
# genuine direct rows, not YouTube-delegation lookalikes. clerkbase is
# the opposite case -- see CUSTOM_PLATFORMS below, it's deliberately not
# here.
#
# WO-35, 2026-08-21: four platforms that shipped 2026-08-19..21
# (destinyhosted #244, suiteone #263, castus #264, open_media #265) were
# missing from BOTH this dict and CUSTOM_PLATFORMS, so their rows hit
# get_platform_coverage()'s if/elif chain with no matching branch and
# vanished from /coverage entirely -- confirmed live on the production
# page (zero headings for all four) before this fix. That's the exact
# gap BACKLOG.md's own "[JUST-DO-IT] /coverage's 'By platform' section
# should list more platforms" entry described for the *previous* six
# (champds/iqm2/clerkbase/seattle_channel/telvue/hyland), recreated. The
# durable fix is tests/test_coverage_platform_registry.py, which now
# fails CI when a registered platform has no /coverage decision at all --
# same shape as WO-26's adapter-canary coverage test.
DIRECT_PLATFORMS: dict[str, str] = {
    "granicus": "Granicus",
    "civicclerk": "CivicClerk",
    "swagit": "Swagit",
    "viebit": "Viebit",
    "escribe": "eScribe",
    "cablecast": "Cablecast",
    "champds": "CHAMP/ChampDS",
    "iqm2": "IQM2",
    "seattle_channel": "Seattle Channel",
    "telvue": "TelVue",
    "hyland": "Hyland OnBase Agenda Online",
    "townhallstreams": "Town Hall Streams",
    # Destiny Software's AgendaQuick (public.destinyhosted.com) -- an
    # agenda/minutes CMS across 61 confirmed real tenants, not a video
    # host, so it looks at first glance like the Legistar/CivicPlus
    # routers excluded above. It isn't, and the difference is worth being
    # precise about: destinyhosted.py delegates to
    # GenericFallbackAssetFinder and only reassigns
    # `resolved.platform = "destinyhosted"` when the delegate came back
    # "unknown" -- i.e. when nothing deeper was found and this page IS
    # the terminal identity. A generic-fallback resolve can still carry
    # real agenda_items/media from the AgendaQuick page itself, so those
    # rows are pushable and really do land labeled "destinyhosted"
    # (unlike legistar/civicplus, whose own label only ever appears on
    # never-pushed error returns). Same shape as hyland above.
    "destinyhosted": "Destiny AgendaQuick",
    # open.media -- a real shared vendor across 7 confirmed tenants, but
    # a YouTube-delegating one: openmedia.py hands off to
    # YouTubeAssetFinder.resolve_video_id() and never reassigns
    # `resolved.platform` afterwards (confirmed by reading resolve() end
    # to end -- it sets title/jurisdiction/external_id/agenda_link only),
    # so a real ingested open.media page's MeetingPage.platform is
    # "youtube", exactly like lims/slc/clerkbase. It's listed HERE rather
    # than under CUSTOM_PLATFORMS because it's one product many
    # jurisdictions buy, not a bespoke single-city scraper -- the row is
    # populated via _entry_platform_from_source_url() below instead of by
    # a platform-name match, which is why that helper and
    # _YOUTUBE_DELEGATING_PLATFORMS are no longer custom-only.
    "open_media": "open.media",
    "castus": "Castus",
    "suiteone": "SuiteOne Media",
    # Not a civic-video vendor like everything else in this dict -- Vimeo
    # is a general-purpose video host that a real, confirmed set of small
    # local governments use directly as their meeting-video platform
    # (WO-29, 2026-08-21). Listed here rather than under CUSTOM_PLATFORMS
    # because MeetingPage.platform really is "vimeo" for these rows, and
    # because it genuinely is one shared platform across many cities,
    # which is what this table's rows mean.
    "vimeo": "Vimeo",
}

# Platforms grouped under a single "Custom" row on /coverage -- each is a
# real, distinct scraper this app built (not a shared vendor product),
# but three of the five (lims, slc, clerkbase) delegate to
# YouTubeAssetFinder for the actual video the exact same way
# lims.py/slc.py/clerkbase.py's own resolve() does (see their docstrings)
# -- MeetingPage.platform ends up "youtube" for a page from any of the
# three, indistinguishable by platform alone from a raw pasted YouTube
# link. _entry_platform_from_source_url() below recovers which one it
# actually was from the page's own source_url_normalized instead.
# Unlike lims/slc, clerkbase has *no* success path that keeps its own
# "clerkbase" platform label -- confirmed by reading clerkbase.py's
# resolve() end to end, "clerkbase" only appears on its no-video error
# return, which is never pushed to the Archive (a push requires real
# segments/agenda_items) -- so without this special-casing, a
# "clerkbase" DIRECT_PLATFORMS row would be permanently exampleless for
# a structural reason, not just because no example has shown up yet
# (the same gap this section already fixed for lims/slc). ca_legislature
# and aurora_tv don't have this problem (they self-host video, no
# YouTube delegation), so they're matched by MeetingPage.platform
# directly, same as DIRECT_PLATFORMS.
CUSTOM_PLATFORMS: dict[str, str] = {
    "ca_legislature": "California State Legislature",
    "slc": "Salt Lake City meeting recaps",
    "lims": "Minneapolis LIMS",
    "clerkbase": "ClerkBase (clerkshq.com)",
    "aurora_tv": "Aurora, CO (auroratv.org)",
    # Chicago's own City Clerk legislative portal -- a single-city
    # scraper like the four above. Unlike lims/slc/clerkbase it does NOT
    # end up labeled by whatever it delegates to: chicago_elms.py sets
    # `resolved.platform` back to its own name after taking the video
    # from vimeo.py, so these rows are matched by MeetingPage.platform
    # directly (same as ca_legislature/aurora_tv).
    "chicago_elms": "Chicago City Clerk (ELMS)",
}

# Registered platforms (app/platforms/__init__.py's
# register_all_finders()) that deliberately get NO /coverage row, each
# with the real reason -- the direct analogue of scripts/adapter_canary.py's
# CANARY_EXCLUSIONS, and the other half of the WO-35 guard.
#
# tests/test_coverage_platform_registry.py asserts every registered
# platform appears in exactly one of DIRECT_PLATFORMS, CUSTOM_PLATFORMS,
# or this dict -- so a new adapter that forgets /coverage fails CI at PR
# time instead of silently vanishing from the page, which is what
# happened to destinyhosted/suiteone/castus/open_media (and, before them,
# to champds/iqm2/clerkbase/seattle_channel/telvue/hyland). Adding a
# platform means making a real decision here, not defaulting to silence.
COVERAGE_EXCLUSIONS: dict[str, str] = {
    "legistar": (
        "Calendar/agenda router: legistar.py delegates via "
        "resolve_via_platform() and the delegated finder's own "
        "ResolvedMeeting is returned as-is, so a successfully-ingested "
        "page's MeetingPage.platform is 'granicus'/'youtube'/etc., never "
        "'legistar'. Its own label appears only on error-path returns, "
        "which are never pushed (a push requires real segments or "
        "agenda_items) -- a row here could never have a real example. "
        "coverage.html's 'What about Platform XYZ?' section explains "
        "this to visitors in prose instead."
    ),
    "civicplus": (
        "Same calendar/agenda-router shape as legistar above -- "
        "delegates to Granicus via resolve_via_platform(), keeps none of "
        "its own platform identity on any pushable result. Named in "
        "coverage.html's 'What about Platform XYZ?' prose."
    ),
    "primegov": (
        "Same shape, delegating to YouTube via "
        "YouTubeAssetFinder.resolve_video_id() rather than "
        "resolve_via_platform(). Its source_url IS preserved, so "
        "_wrapper_detail_label() can still name it in the full "
        "jurisdiction table's 'Detail page' column -- but the 'By "
        "platform' section deliberately doesn't give it a row, since "
        "that section exists to show which video platforms are "
        "supported, and PrimeGov meetings appear there under YouTube's "
        "own deliberate exclusion below. Named in 'What about Platform "
        "XYZ?' prose."
    ),
    "civicweb": (
        "Same as primegov -- a YouTube-delegating calendar tool, named "
        "in 'What about Platform XYZ?' prose and recoverable in the "
        "'Detail page' column via _wrapper_detail_label()."
    ),
    "youtube": (
        "Deliberate product decision, not an oversight: a viewer already "
        "gets a good deep-linkable transcript straight from YouTube for a "
        "directly-pasted YouTube URL, so this page steers people toward "
        "pasting the government page that embeds it instead. See the "
        "'What about YouTube?' section in coverage.html, and "
        "test_coverage_page_excludes_youtube_as_its_own_row."
    ),
    "unknown": (
        "generic_fallback.py's registered platform_name -- the literal "
        "string detect_platform() returns for an unrecognized host, not "
        "a platform anyone could look for on this page. Rows land in the "
        "full jurisdiction table as 'Custom/Generic' (with the raw video "
        "host shown where one was found) via _platform_split(); a 'By "
        "platform' row for it would be meaningless."
    ),
}

# YouTube is deliberately never its own /coverage row -- a viewer already
# gets a good deep-linkable transcript straight from YouTube itself for
# a directly-pasted YouTube URL, so this page steers people toward
# pasting the government page that embeds/links it instead (a Granicus/
# Swagit/etc. page, or one of the CUSTOM_PLATFORMS above) wherever one
# exists. See coverage.html's own footer note, and COVERAGE_EXCLUSIONS
# above.

# Coverage keys whose real archived rows are stored with
# MeetingPage.platform == "youtube" (their adapter delegates to
# YouTubeAssetFinder and doesn't reassign `platform` afterwards), and so
# have to be recovered from source_url_normalized instead. Three of the
# four are CUSTOM_PLATFORMS entries; open_media (added WO-35) is a
# DIRECT_PLATFORMS one -- hence the name change from
# _YOUTUBE_DELEGATING_CUSTOM_PLATFORMS, this was never really a
# custom-only property.
_YOUTUBE_DELEGATING_PLATFORMS = frozenset({"lims", "slc", "clerkbase", "open_media"})

# How many example rows to show per platform on /coverage. Granicus gets
# more because it's this app's most common platform by a wide margin (see
# README's "Supported platforms" table ordering) -- showing several cities
# under it communicates real vendor breadth in a way a single example
# doesn't. Every other DIRECT_PLATFORMS/CUSTOM_PLATFORMS key uses the
# default.
_DEFAULT_EXAMPLE_COUNT = 3
_PLATFORM_EXAMPLE_COUNTS: dict[str, int] = {"granicus": 5}


def _select_examples(examples: list[dict], count: int) -> list[dict]:
    """Pick up to `count` examples out of all real examples found for a
    platform, preferring (1) a different jurisdiction each time, so a
    multi-example row demonstrates real multi-city breadth instead of
    several meetings from the same one city, then (2) has_transcript=True
    within that first pass, so the examples shown make for a convincing
    demo. Never fabricates rows -- a platform with only 1-2 real
    jurisdictions (most CUSTOM_PLATFORMS entries are single-city scrapers
    by nature) just returns however many real examples actually exist.
    """
    if not examples:
        return []
    ordered = sorted(examples, key=lambda e: not e["has_transcript"])
    seen_jurisdictions: set = set()
    picked: list[dict] = []
    leftover: list[dict] = []
    for e in ordered:
        j = e["jurisdiction"]
        if j is None or j not in seen_jurisdictions:
            if j is not None:
                seen_jurisdictions.add(j)
            picked.append(e)
        else:
            leftover.append(e)
        if len(picked) >= count:
            return picked[:count]
    picked.extend(leftover)
    return picked[:count]


def _entry_platform_from_source_url(source_url_normalized: str) -> Optional[str]:
    """Minimal, deliberately duplicated subset of app/platforms/base.py's
    detect_platform() -- just enough to recognize the YouTube-delegating
    platforms that still need their own /coverage row (see
    _YOUTUBE_DELEGATING_PLATFORMS above) from a page's own
    source_url_normalized. archive/ deliberately doesn't import from
    app/ (see README's project structure notes on this directory's other
    deliberately-duplicated utils, e.g. url_normalize.py/language.py) --
    this stays scoped to exactly the cases get_platform_coverage() needs,
    not a general URL classifier.
    """
    netloc = urlparse(source_url_normalized).netloc.lower()
    path = urlparse(source_url_normalized).path.lower()
    if "lims.minneapolismn.gov" in netloc:
        return "lims"
    if netloc.endswith("slc.gov") and "-meeting-recap" in path:
        return "slc"
    if "clerkshq.com" in netloc:
        return "clerkbase"
    # Same check app/platforms/base.py's detect_platform() uses for this
    # platform, kept character-for-character: every real tenant is a
    # `{tenant}.open.media` subdomain (7 confirmed live -- see README's
    # platform table).
    if netloc.endswith("open.media"):
        return "open_media"
    return None


def _coverage_row(key: str, label: str, examples: list[dict]) -> dict:
    count = _PLATFORM_EXAMPLE_COUNTS.get(key, _DEFAULT_EXAMPLE_COUNT)
    selected = _select_examples(examples, count)
    return {
        "platform": key,
        "label": label,
        "examples": selected,
        # Kept for back-compat with any caller/test that reads a single
        # "best" example (same has_transcript-preferred pick as before) --
        # coverage.html itself now renders `examples` (plural).
        "example": selected[0] if selected else None,
        "page_count": len(examples),
    }


async def get_platform_coverage() -> dict:
    """Grouped rows for the public /coverage page -- one or more real
    example permanent pages per platform (see _PLATFORM_EXAMPLE_COUNTS),
    preferring ones with a good transcript and distinct jurisdictions for
    a more convincing demo, plus a transcript-availability checkmark per
    example, not aggregate stats. Returns {"direct": [...], "custom":
    [...]}, matching how coverage.html renders "Custom" as one grouped
    section with its own sub-rows rather than a flat list.

    Every key in DIRECT_PLATFORMS/CUSTOM_PLATFORMS is returned even with
    zero live examples ("example": None) -- an honest "no example live
    yet" beats silently omitting a platform this app genuinely supports
    in code but hasn't happened to resolve a real meeting on yet, per
    CLAUDE.md's "don't claim a data path works without a positive
    example" convention (the thing being demonstrated here is "does a
    real page exist," not "is this code path exercised" -- those are
    different claims).
    """
    async with async_session() as session:
        stmt = select(
            MeetingPage.platform,
            MeetingPage.slug,
            MeetingPage.title,
            MeetingPage.jurisdiction,
            MeetingPage.source_url_normalized,
            TranscriptVersion.id,
            TranscriptVersion.transcript_warnings,
        ).outerjoin(
            TranscriptVersion,
            and_(
                TranscriptVersion.meeting_page_id == MeetingPage.id,
                TranscriptVersion.is_default.is_(True),
            ),
        )
        rows = (await session.execute(stmt)).all()

    by_key: dict[str, list[dict]] = {}
    for platform, slug, title, jurisdiction, source_url, version_id, warnings in rows:
        has_transcript = version_id is not None and _has_real_warning_free_transcript(
            warnings
        )
        example = {
            "slug": slug,
            "title": title,
            "jurisdiction": jurisdiction,
            "has_transcript": has_transcript,
        }

        if platform in DIRECT_PLATFORMS:
            by_key.setdefault(platform, []).append(example)
        elif platform == "youtube":
            entry = _entry_platform_from_source_url(source_url)
            if entry in _YOUTUBE_DELEGATING_PLATFORMS:
                by_key.setdefault(entry, []).append(example)
            # else: a raw pasted YouTube link, or a Legistar/CivicPlus/
            # PrimeGov/CivicWeb/best-effort page that happened to
            # delegate to YouTube -- not shown, YouTube is intentionally
            # excluded from this page (see coverage.html's footer note).
        elif platform in CUSTOM_PLATFORMS:
            # ca_legislature, aurora_tv -- self-hosted, no delegation.
            by_key.setdefault(platform, []).append(example)

    return {
        "direct": [
            _coverage_row(k, v, by_key.get(k, [])) for k, v in DIRECT_PLATFORMS.items()
        ],
        "custom": [
            _coverage_row(k, v, by_key.get(k, [])) for k, v in CUSTOM_PLATFORMS.items()
        ],
    }


async def get_jurisdiction_coverage() -> list[dict]:
    """One row per distinct jurisdiction (MeetingPage.jurisdiction) with
    at least one archived meeting -- a real "did you cover my city"
    roster meant to be Ctrl+F'd, complementing get_platform_coverage()'s
    per-platform summary above it on /coverage. That one groups by
    engineering detail (which vendor) most viewers don't think in terms
    of; user request 2026-08-12: "only software engineers think platform
    first... most people want to ctrl-f 'napa' or 'aurora'." Sorted
    alphabetically (case-insensitively), not by volume or recency, since
    Ctrl+F relies on the reader's own scan order matching what they
    typed, not this app's.

    No platform grouping/exclusion logic here (unlike
    get_platform_coverage()) -- a real archived meeting counts regardless
    of which platform or delegation path found it, since "did you cover
    my city" doesn't care how.
    """
    async with async_session() as session:
        stmt = (
            select(
                MeetingPage.jurisdiction,
                MeetingPage.slug,
                MeetingPage.title,
                TranscriptVersion.id,
                TranscriptVersion.transcript_warnings,
            )
            .outerjoin(
                TranscriptVersion,
                and_(
                    TranscriptVersion.meeting_page_id == MeetingPage.id,
                    TranscriptVersion.is_default.is_(True),
                ),
            )
            .where(MeetingPage.jurisdiction.is_not(None))
        )
        rows = (await session.execute(stmt)).all()

    by_jurisdiction: dict[str, list[dict]] = {}
    for jurisdiction, slug, title, version_id, warnings in rows:
        has_transcript = version_id is not None and _has_real_warning_free_transcript(
            warnings
        )
        by_jurisdiction.setdefault(jurisdiction, []).append(
            {"slug": slug, "title": title, "has_transcript": has_transcript}
        )

    result = []
    for jurisdiction in sorted(by_jurisdiction, key=str.casefold):
        examples = by_jurisdiction[jurisdiction]
        example = next((e for e in examples if e["has_transcript"]), examples[0])
        result.append(
            {
                "jurisdiction": jurisdiction,
                "example": example,
                "page_count": len(examples),
            }
        )
    return result


# --- get_full_jurisdiction_coverage() and its helpers -----------------------
# BACKLOG.md's "Coverage page -- a public, sortable/filterable table" entry:
# one row per successfully-archived jurisdiction (same population as
# get_jurisdiction_coverage() above, sharing its `MeetingPage.jurisdiction
# is not None` gate), but with the fuller per-jurisdiction column spec that
# function was never meant to carry -- video/agenda/transcript yes-no
# columns, a two-column provider split, an outcome bucket, and a
# last-verified date. Deliberately a new function rather than growing
# get_jurisdiction_coverage() itself: that one backs the existing "Every
# place we've covered" table and its own tests, which should keep behaving
# exactly as before.


# Domains recovering a YouTube-delegating wrapper platform's own real
# identity from a page's source_url_normalized -- superset of
# _entry_platform_from_source_url() above (which only recognizes the
# platforms with their own /coverage row: lims/slc/clerkbase, plus
# open_media as of WO-35). PrimeGov and CivicWeb are added here too: real, confirmed-live
# wrapper platforms (README's "Supported platforms" table) that preserve
# their own source_url on delegation the same way lims/slc/clerkbase do
# (see primegov.py/civicweb.py's own docstrings), but that don't have a
# DIRECT_PLATFORMS/CUSTOM_PLATFORMS row of their own today -- not a gap
# this function needs to fix, just two more identities worth recovering
# for the "Detail page" column below, which is the entire reason this
# split exists (BACKLOG.md's "Provider, split into two columns" spec).
def _wrapper_detail_label(source_url_normalized: str) -> Optional[str]:
    netloc = urlparse(source_url_normalized).netloc.lower()
    path = urlparse(source_url_normalized).path.lower()
    if "lims.minneapolismn.gov" in netloc:
        return "Minneapolis LIMS"
    if netloc.endswith("slc.gov") and "-meeting-recap" in path:
        return "Salt Lake City meeting recaps"
    if "clerkshq.com" in netloc:
        return "ClerkBase (clerkshq.com)"
    if netloc.endswith("open.media"):
        return "open.media"
    if netloc.endswith("primegov.com"):
        return "PrimeGov"
    if netloc.endswith("civicweb.net"):
        return "CivicWeb"
    return None


_PLATFORM_LABELS: dict[str, str] = {**DIRECT_PLATFORMS, **CUSTOM_PLATFORMS}

# ResolvedMeeting.video_format values whose `video_url` is an iframe
# *embed page*, not a fetchable media file -- so on-demand Whisper can
# never run against them no matter what, and /coverage's "Audio
# transcript possible" column must say no. See the full reasoning at the
# one use site in get_full_jurisdiction_coverage() below. Keep this in
# sync with any new adapter that stores an embed URL as `video_url`:
# tests/test_coverage_platform_registry.py asserts the set stays
# non-empty and correctly typed, but only a human reading a new adapter
# can decide whether its format belongs here.
# Re-exported from archive/utils/video_formats.py so existing callers
# and tests keep working; that module is the single definition.
_IFRAME_EMBED_VIDEO_FORMATS = IFRAME_EMBED_VIDEO_FORMATS


def _platform_split(
    platform: str, source_url_normalized: str, video_url: Optional[str]
) -> tuple[str, str]:
    """Returns (detail_page_label, video_label) for one MeetingPage row.

    Only genuinely splits into two different labels when there's real
    recoverable evidence they differ (the YouTube-wrapper case, or a
    generic_fallback "unknown" row where the raw video host is at least
    visible even though it isn't a named platform this app has an adapter
    for) -- everywhere else both columns show the same label, which is the
    honest answer given what's actually stored. Per CLAUDE.md's
    wrapper-platform bullet, a Legistar/CivicPlus-delegated row's
    MeetingPage.platform is already overwritten to the delegated platform
    (e.g. "granicus") by the time it's ingested, and source_url_normalized
    is the delegated platform's own URL too -- this app genuinely has no
    stored way to tell, post-hoc, that a given Granicus row arrived via a
    Legistar page rather than a directly-pasted Granicus link. Showing
    "Detail page: Granicus; Video: Granicus" for that row isn't a missed
    split, it's the real limit of what's recoverable from stored data.
    """
    if platform == "youtube":
        wrapper = _wrapper_detail_label(source_url_normalized)
        if wrapper:
            return wrapper, "YouTube"
        return "YouTube", "YouTube"
    if platform == "unknown":
        # generic_fallback.py's own scan for a directly playable media URL
        # (no named platform/adapter involved) -- the raw host is real,
        # derivable signal even though it isn't a platform this app has
        # code for, so it's shown as-is rather than guessed at (e.g. never
        # labeled "Vimeo" without a confirmed vimeo.com host -- see
        # CLAUDE.md's "don't claim a data path works without a positive
        # example" convention).
        if video_url:
            host = urlparse(video_url).netloc or "Custom/Generic"
            return "Custom/Generic", host
        return "Custom/Generic", "Custom/Generic"
    label = _PLATFORM_LABELS.get(platform, platform)
    return label, label


# Mirrors app/db/outcomes.py's classify_outcome() bucket names/ordering, but
# reads MeetingPage/TranscriptVersion (archive/db/models.py) instead of a
# MeetingResolution row (app/db/models.py, a different schema on a
# different service's DB) -- archive/ deliberately doesn't import from
# app/ (see README's project-structure notes on other deliberately-
# duplicated utils), and the inputs differ anyway (a page's already-
# persisted state here vs. a fresh resolve() payload there). Same bucket
# keys, so a reader comparing the two /admin/stats-style views gets the
# same mental model.
_OUTCOME_LABELS: dict[str, str] = {
    "no_video": "No video",
    "blank_transcript": "Blank/no transcript",
    "agenda_fallback": "Agenda only",
    "garbled_transcript": "Garbled transcript",
    # Added 2026-08-23 alongside _GRANICUS_TRUNCATION_MARKER -- its own
    # bucket rather than folded into "garbled_transcript": the covered
    # portion is real, correct content (a government-provided caption,
    # not a hallucination), it just stops at Granicus's own 36,000-cue
    # cap -- a different problem than garbled, worth telling apart in a
    # report the same way agenda_fallback is kept distinct from
    # blank_transcript.
    "truncated_transcript": "Truncated transcript (Granicus cap)",
    "non_english_transcript": "Transcript (non-English)",
    "success": "Transcript (English)",
}
# Lower is better -- used to pick which of a jurisdiction's several pages
# best represents it (same "prefer the most convincing real example"
# intent as _select_examples() above, just scored on the fuller bucket
# list instead of a single has_transcript bool). truncated_transcript
# ranks just above garbled_transcript -- most of a real transcript is
# arguably more useful to a reader than one that's full-length but
# possibly-hallucinated, though this ordering is a judgment call, not a
# measured one.
_OUTCOME_RANK: dict[str, int] = {
    "success": 0,
    "non_english_transcript": 1,
    "garbled_transcript": 2,
    "truncated_transcript": 3,
    "agenda_fallback": 4,
    "blank_transcript": 5,
    "no_video": 6,
}


def _classify_page_outcome(
    *,
    video_url: Optional[str],
    agenda_items: Optional[list],
    default_content_hash: Optional[str],
    default_transcript_warnings: Optional[list],
    default_transcript_language: Optional[str],
) -> str:
    if not video_url:
        return "no_video"
    if default_content_hash is None or default_content_hash == _EMPTY_CONTENT_HASH:
        if agenda_items:
            return "agenda_fallback"
        return "blank_transcript"
    if default_transcript_warnings and any(
        _GARBLED_MARKER in w or _HALLUCINATION_MARKER in w
        for w in default_transcript_warnings
    ):
        return "garbled_transcript"
    if default_transcript_warnings and any(
        _GRANICUS_TRUNCATION_MARKER in w for w in default_transcript_warnings
    ):
        return "truncated_transcript"
    if default_transcript_language and default_transcript_language != "en":
        return "non_english_transcript"
    return "success"


async def get_transcript_quality_audit(
    list_outcomes: Optional[set[str]] = None,
) -> dict:
    """Aggregate page counts per outcome bucket (same buckets as
    _classify_page_outcome above / app/db/outcomes.py's classify_outcome())
    across EVERY archived page, not just one best-example-per-jurisdiction
    row like get_full_jurisdiction_coverage() below returns -- for
    answering "how many archived meetings have a low-quality/garbled/
    non-English/missing transcript" without needing direct DATABASE_URL
    access (same reasoning as /internal/schema-info). Reads only the same
    cheap columns _classify_page_outcome already needs, never
    TranscriptVersion.segments -- see MeetingPage.search_corpus's own
    docstring on why that matters at this table's real production scale.

    `list_outcomes`, if given, also returns identifying rows (slug, real
    source URL, platform, language, warnings) for every page landing in
    one of those buckets -- e.g. {"garbled_transcript"} to get the real
    list of garbled pages to target directly (scripts/
    transcribe_backlog_locally.py --url), rather than just their count.
    Still never touches segments.
    """
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    MeetingPage.slug,
                    MeetingPage.source_url_normalized,
                    MeetingPage.platform,
                    MeetingPage.video_url,
                    MeetingPage.agenda_items,
                    TranscriptVersion.content_hash,
                    TranscriptVersion.transcript_warnings,
                    TranscriptVersion.language,
                ).outerjoin(
                    TranscriptVersion,
                    and_(
                        TranscriptVersion.meeting_page_id == MeetingPage.id,
                        TranscriptVersion.is_default.is_(True),
                    ),
                )
            )
        ).all()

    counts: dict[str, int] = {}
    examples: list[dict] = []
    for (
        slug,
        source_url_normalized,
        platform,
        video_url,
        agenda_items,
        content_hash,
        transcript_warnings,
        language,
    ) in rows:
        outcome = _classify_page_outcome(
            video_url=video_url,
            agenda_items=agenda_items,
            default_content_hash=content_hash,
            default_transcript_warnings=transcript_warnings,
            default_transcript_language=language,
        )
        if list_outcomes and outcome in list_outcomes:
            examples.append(
                {
                    "slug": slug,
                    "source_url_normalized": source_url_normalized,
                    "platform": platform,
                    "outcome": outcome,
                    "language": language,
                    "transcript_warnings": transcript_warnings,
                }
            )
        counts[outcome] = counts.get(outcome, 0) + 1
    result = {"total_pages": len(rows), "by_outcome": counts}
    if list_outcomes:
        result["examples"] = examples
    return result


async def get_meeting_date_format_audit(limit: int = 200) -> dict:
    """Read-only audit answering, in one call, the question BACKLOG.md's
    Google Search Console entry has left open since 2026-08-12: does any
    real production row hold a `MeetingPage.date` that isn't a plain
    "YYYY-MM-DD"? That's what the `uploadDate` "invalid datetime value"
    flag would need to be caused by a stored value, and the entry
    explicitly notes it has never been cross-checked against production.

    Why nothing already answers it: `date` is an unvalidated free string
    the whole way down -- `Optional[str]` on ResolvedMeeting
    (app/platforms/models.py), `Optional[str]` on IngestRequest
    (archive/main.py), a `String(20)` column here -- so no layer would have
    rejected a bad value on the way in. Every *adapter* is structurally
    constrained to emit "YYYY-MM-DD" or None today (each goes through
    strftime("%Y-%m-%d") or an anchored ISO regex), but that says nothing
    about rows written by an older adapter version, or pushed by one of
    the scripts/ ingest paths.

    Buckets every page by shape:
      - `null` -- no date at all (legitimate; emits no uploadDate)
      - `iso_date` -- a clean "YYYY-MM-DD"
      - `parseable_non_iso` -- normalizes to a real date but isn't stored
        bare (e.g. a stored "2026-08-03T00:00:00"); the template's
        iso_date filter now repairs these on render
      - `unparseable` -- the real smoking gun, if any exist

    Returns identifying rows (capped by `limit`) for the last two buckets
    only, so this stays a small response on a table of any size. Reads two
    cheap columns, never TranscriptVersion.segments -- see
    get_transcript_quality_audit()'s own docstring on why that matters
    here. Never writes anything; a human decides what (if anything) to
    backfill.
    """
    async with async_session() as session:
        rows = (await session.execute(select(MeetingPage.slug, MeetingPage.date))).all()

    counts = {
        "null": 0,
        "iso_date": 0,
        "parseable_non_iso": 0,
        "unparseable": 0,
    }
    suspect_rows: list[dict] = []
    for slug, raw in rows:
        if not raw:
            counts["null"] += 1
            continue
        normalized = iso_meeting_date(raw)
        if normalized == raw:
            counts["iso_date"] += 1
            continue
        bucket = "parseable_non_iso" if normalized else "unparseable"
        counts[bucket] += 1
        if len(suspect_rows) < limit:
            suspect_rows.append(
                {
                    "slug": slug,
                    "stored_date": raw,
                    "normalized_date": normalized,
                    "bucket": bucket,
                }
            )

    return {
        "total_pages": len(rows),
        "by_shape": counts,
        "suspect_rows": suspect_rows,
        "suspect_rows_truncated": (counts["parseable_non_iso"] + counts["unparseable"])
        > len(suspect_rows),
    }


async def get_full_jurisdiction_coverage() -> list[dict]:
    """One row per distinct jurisdiction, same population as
    get_jurisdiction_coverage() above, with the full column spec from
    BACKLOG.md's "Coverage page" entry: video-embeds / agenda-embedded /
    instant-transcript-from-source / transcript-from-audio-possible
    (yes/no each), a two-column "detail page" vs "video" provider split
    (see _platform_split()), an outcome bucket (see _classify_page_outcome,
    mirroring app/db/outcomes.py's classify_outcome()), and a last-verified
    date. A jurisdiction with several archived pages gets its yes/no
    columns computed as "true if ANY of its pages has this" (this is a
    "did we ever manage this for this city" roster, not a per-meeting
    one), but its platform-split/outcome/example columns come from
    whichever single page best represents it (lowest _OUTCOME_RANK, i.e.
    the most convincing real example) -- same spirit as
    get_jurisdiction_coverage()'s own has_transcript-preferred example
    pick, just scored on the fuller outcome bucket instead of one bool.

    Reads only the columns each computation actually needs (never
    TranscriptVersion.segments, the heavy JSON column -- see
    MeetingPage.search_corpus's own docstring on why that matters at this
    table's real production scale) via an EXISTS subquery for "a real
    source-provided (source='scraped') transcript exists on ANY version of
    this page" (not just the default one -- a page's default can be
    promoted to a later 'transcribed' version via
    manually_promote_transcript_version() without deleting the original
    scraped one, so checking only the default would wrongly say "no" for
    a page that still has a real scraped transcript sitting non-default),
    plus a plain outerjoin on the default version for the outcome-bucket
    fields (content_hash/transcript_warnings/language), which are always
    about "what does /m/{slug} show by default right now."
    """
    # Aliased + explicitly correlated to MeetingPage only, same reason as
    # _is_empty_page_condition()'s identical pattern above: the outer query
    # below already outerjoins TranscriptVersion (the default version), so
    # without the alias SQLAlchemy auto-correlates that join away too,
    # leaving this subquery with no FROM at all.
    any_scraped_version = aliased(TranscriptVersion)
    has_scraped_transcript = (
        select(any_scraped_version.id)
        .where(
            any_scraped_version.meeting_page_id == MeetingPage.id,
            # Not `== "scraped"`: any non-AI source counts as a real
            # source-provided transcript, so a page whose only version was
            # re-labeled (e.g. "deduped", 2026-08-22) keeps counting here.
            # Same allowlist-to-fallback fix as meeting_page.html's
            # disclaimer branch.
            any_scraped_version.source != "transcribed",
            any_scraped_version.content_hash != _EMPTY_CONTENT_HASH,
        )
        .correlate(MeetingPage)
        .exists()
    )
    async with async_session() as session:
        stmt = (
            select(
                MeetingPage.jurisdiction,
                MeetingPage.slug,
                MeetingPage.title,
                MeetingPage.platform,
                MeetingPage.source_url_normalized,
                MeetingPage.video_url,
                MeetingPage.video_format,
                MeetingPage.agenda_items,
                MeetingPage.updated_at,
                has_scraped_transcript.label("has_scraped_transcript"),
                TranscriptVersion.content_hash,
                TranscriptVersion.transcript_warnings,
                TranscriptVersion.language,
            )
            .outerjoin(
                TranscriptVersion,
                and_(
                    TranscriptVersion.meeting_page_id == MeetingPage.id,
                    TranscriptVersion.is_default.is_(True),
                ),
            )
            .where(MeetingPage.jurisdiction.is_not(None))
        )
        rows = (await session.execute(stmt)).all()

    by_jurisdiction: dict[str, list[dict]] = {}
    for (
        jurisdiction,
        slug,
        title,
        platform,
        source_url_normalized,
        video_url,
        video_format,
        agenda_items,
        updated_at,
        has_scraped,
        content_hash,
        transcript_warnings,
        language,
    ) in rows:
        detail_label, video_label = _platform_split(
            platform, source_url_normalized, video_url
        )
        outcome = _classify_page_outcome(
            video_url=video_url,
            agenda_items=agenda_items,
            default_content_hash=content_hash,
            default_transcript_warnings=transcript_warnings,
            default_transcript_language=language,
        )
        by_jurisdiction.setdefault(jurisdiction, []).append(
            {
                "slug": slug,
                "title": title,
                "video_embeds": video_url is not None,
                "agenda_embedded": bool(agenda_items),
                "instant_transcript": bool(has_scraped),
                # Mirrors app/main.py's own _unreadable_media_message()
                # reasoning: a video_format=="youtube" result is
                # structurally unprobeable by ffprobe (an iframe-embed
                # page, never a real media file), so the on-demand
                # Whisper path can never succeed for it regardless of
                # whether anyone has actually tried yet -- see that
                # function's own docstring for the full trace. "vimeo"
                # (added 2026-08-21, WO-29) is the same shape for the
                # same reason: a player.vimeo.com iframe page, with the
                # real media behind a signed config that 403s every
                # non-browser client. "viebit" (added 2026-08-21, WO-35 --
                # the WO-29 residual BACKLOG.md flagged as "cheap and
                # safe to fix") completes the set: viebit.py stores
                # `video_url` as the platform's own `/embed/vod?v={id}`
                # embed page, deliberately rebuilt as that path on every
                # resolve so the frontend can iframe it (see that
                # adapter's docstring on `video_format="viebit"` and
                # reload-based seeking). The BACKLOG entry wondered
                # whether Viebit's underlying `master.m3u8` might be
                # probeable after all; that question doesn't apply here,
                # because the stored `video_url` is never that stream --
                # it's an HTML page, so ffprobe can't read it regardless
                # of the CDN's Referer check. Every other real
                # `video_format` this app stores (mp4/m3u8/mp3/wav --
                # confirmed by grepping every adapter's `video_format=`
                # assignment) is a genuine fetchable media URL, so this
                # exclusion list is complete as of today.
                #
                # A live ffprobe check per row here would be far too
                # expensive for a full coverage table; this is the same
                # structural approximation the resolver itself already
                # relies on.
                "audio_transcript_possible": video_url is not None
                and video_format not in _IFRAME_EMBED_VIDEO_FORMATS,
                "detail_platform": detail_label,
                "video_platform": video_label,
                "outcome": outcome,
                "updated_at": updated_at,
            }
        )

    result = []
    for jurisdiction in sorted(by_jurisdiction, key=str.casefold):
        pages = by_jurisdiction[jurisdiction]
        best = min(pages, key=lambda p: _OUTCOME_RANK[p["outcome"]])
        last_verified = max(p["updated_at"] for p in pages)
        result.append(
            {
                "jurisdiction": jurisdiction,
                "video_embeds": any(p["video_embeds"] for p in pages),
                "agenda_embedded": any(p["agenda_embedded"] for p in pages),
                "instant_transcript": any(p["instant_transcript"] for p in pages),
                "audio_transcript_possible": any(
                    p["audio_transcript_possible"] for p in pages
                ),
                "detail_platform": best["detail_platform"],
                "video_platform": best["video_platform"],
                "outcome": best["outcome"],
                "outcome_label": _OUTCOME_LABELS[best["outcome"]],
                "last_verified": last_verified,
                "example": {"slug": best["slug"], "title": best["title"]},
                "page_count": len(pages),
            }
        )
    return result


async def get_state_coverage_index() -> list[dict]:
    """One row per US state or Canadian province/territory with >= 1
    indexable archived meeting, for the /state/{slug} landing pages:
    /coverage's "Browse by state" section and sitemap.xml's per-state
    entries. Excludes platform == "unknown" (generic_fallback) pages --
    state pages are an indexable SEO surface and carry the same trust
    posture as the sitemap (see list_all_page_slugs() below).
    Jurisdictions without a recognized ", ST" suffix (school districts,
    state agencies, non-US/non-Canada) simply don't group into any state
    -- a documented limitation, not a bug. Sorted by name within each of
    two country groups (US first, matching /coverage's existing "Browse
    by state" heading; Canada second under its own "country": "CA" rows)
    -- each row's "country" field ("US"/"CA", from is_canadian_abbr())
    is what lets coverage.html render the two as separate sections
    without a second query."""
    async with async_session() as session:
        stmt = select(MeetingPage.jurisdiction, MeetingPage.updated_at).where(
            MeetingPage.jurisdiction.is_not(None),
            MeetingPage.platform != "unknown",
        )
        rows = (await session.execute(stmt)).all()

    by_state: dict[str, dict] = {}
    for jurisdiction, updated_at in rows:
        abbr = state_abbr_from_jurisdiction(jurisdiction)
        if not abbr:
            continue
        entry = by_state.setdefault(
            abbr, {"jurisdictions": set(), "page_count": 0, "last_updated": updated_at}
        )
        entry["jurisdictions"].add(jurisdiction)
        entry["page_count"] += 1
        if updated_at > entry["last_updated"]:
            entry["last_updated"] = updated_at

    result = [
        {
            "abbr": abbr,
            "name": US_STATE_ABBR_TO_NAME[abbr],
            "slug": state_slug_from_abbr(abbr),
            "country": "CA" if is_canadian_abbr(abbr) else "US",
            "jurisdiction_count": len(entry["jurisdictions"]),
            "page_count": entry["page_count"],
            "last_updated": entry["last_updated"],
        }
        for abbr, entry in by_state.items()
    ]
    result.sort(key=lambda s: (s["country"] != "US", s["name"]))
    return result


# --- State/hub page highlights, topics and activity -----------------------
#
# How many recent transcribed meetings a state page scans for featured
# snippets and topic counts. Deliberately a *recent* pool rather than the
# whole state: "which subjects are live here right now" is the useful
# question, and an all-time count would be dominated by whichever
# jurisdictions happened to be bulk-ingested first. Also bounds the JSON
# decoded per render -- topic_moments is small per row but 400+ rows of
# it would not be.
STATE_HIGHLIGHT_POOL = 150
STATE_FEATURED_COUNT = 12
# "Most active governments" is meaningless for a state with a handful of
# governments (the list would just be the whole state, reordered), so the
# section renders only above this threshold.
# Chips are a way in, not an index: past a dozen they stop being
# scannable and start being another wall of links. The curated list can
# grow past this without the page getting noisier.
MAX_TOPIC_CHIPS = 12
# At most this many featured cards may share a topic, so one busy subject
# can't take over the page (see _build_featured()). Never shrinks the
# set -- skipped cards backfill any slots left over.
MAX_FEATURED_PER_TOPIC = 2
# Distinct topics marked per snippet in the default (no-topic) view.
# Marking every match turned a quote about flock cameras into three
# highlighted "playground"s, burying the word the reader came for.
# One topic marked per snippet in the default (no-topic) view.
#
# Marking every match buried the point: the Darth Vader flock-camera
# quote also matched `libraries-parks` on the word "playground", so it
# rendered with `flock` highlighted twice and `playground` three times.
# A rarity *ratio* guard was tried first and rejected by measurement --
# rarity here is counted over the page's own pool, and in a six-meeting
# hub pool both topics have a count of 1, so no ratio can separate them.
# Marking the single best topic needs no archive-wide count query and is
# what a reader wants anyway: with `?topic=` selected exactly that topic
# is marked, and without one, the rarest/most newsworthy is.
MAX_MARKED_TOPICS = 1
MOST_ACTIVE_MIN_GOVERNMENTS = 8
MOST_ACTIVE_WINDOW_DAYS = 90
MOST_ACTIVE_COUNT = 6
FRESHNESS_WINDOW_DAYS = 7


def format_timestamp_label(seconds: float) -> str:
    """`1:23:45` / `4:07` -- the deep link's target, shown next to a
    snippet so a reader knows they are jumping into a long meeting rather
    than starting it over."""
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


async def _load_highlights(session, page_ids: Sequence[int]) -> dict[int, dict]:
    """meeting_page_id -> stored highlight row, for the pages given."""
    if not page_ids:
        return {}
    rows = (
        await session.execute(
            select(
                MeetingHighlight.meeting_page_id,
                MeetingHighlight.start_seconds,
                MeetingHighlight.text,
                MeetingHighlight.topics,
                MeetingHighlight.topic_moments,
            ).where(MeetingHighlight.meeting_page_id.in_(list(page_ids)))
        )
    ).all()
    return {
        page_id: {
            "start": start,
            "text": text,
            "topics": topics or [],
            "topic_moments": moments or {},
        }
        for page_id, start, text, topics, moments in rows
    }


def _featured_entry(
    page: dict,
    highlight: dict,
    topic_slug: Optional[str],
    topic_counts: Optional[dict[str, int]] = None,
):
    """One rendered featured-meeting card, or None when this page has
    nothing to show for the requested topic.

    With a topic selected the quote comes from that topic's stored
    moment (so the snippet actually contains the thing the reader
    clicked); with no topic it is the meeting's default highlight, and
    the *rarest* topics in it get marked (see
    `_rank_topics_by_rarity()`)."""
    # An untitled page renders as a card headed "Untitled meeting", which
    # is fine in a dense list but reads as broken as a *featured* card on
    # an indexed page -- and featuring is optional, so decline rather than
    # publish a placeholder. Real case (2026-08-23): nine PrimeGov pages
    # ingested on one bad day carried no title and one reached
    # /state/california as a featured card. Deliberately a render-time
    # guard, not a fix: the underlying rows still want re-resolving (see
    # BACKLOG.md), and this just stops the gap being user-visible while
    # they wait.
    if not (page.get("title") or "").strip():
        return None

    if topic_slug:
        moment = (highlight.get("topic_moments") or {}).get(topic_slug)
        if not moment:
            return None
        start, text, marks = moment["start"], moment["text"], [topic_slug]
    else:
        start, text = highlight["start"], highlight["text"]
        marks = _marks_for(highlight.get("topics") or [], topic_counts)
    return {
        "_page_id": page["id"],
        "slug": page["slug"],
        "title": page["title"],
        "jurisdiction": page["jurisdiction"],
        "hub_slug": jurisdiction_hub_slug(page["jurisdiction"]),
        "date": page["date"],
        "start_seconds": start,
        "timestamp_label": format_timestamp_label(start),
        # The whole point of the archive, on the hub page: a link into
        # the exact second being quoted.
        "deep_link": f"/m/{page['slug']}?t={int(start)}",
        "snippet_html": highlight_html(text, marks),
        # The same quote as plain text, for JSON-LD (which must not
        # contain markup) and any non-HTML consumer.
        "snippet_text": display_text(text),
        "topics": marks,
        # Filled in by _attach_thumbnails() once the bulk existence check
        # has run -- never assumed.
        "card_url": None,
    }


def _attach_thumbnails(featured: Sequence[dict], page_ids_with_cards: set) -> None:
    """Point each featured card at its stored frame *at the quoted
    moment* -- the card route takes the same `?t=` the deep link does, so
    the image a reader sees is the one from the second being quoted."""
    for entry in featured:
        if entry["_page_id"] in page_ids_with_cards:
            entry["card_url"] = (
                f"/m/{entry['slug']}/card.jpg?t={int(entry['start_seconds'])}"
            )


def _rank_topics_by_rarity(
    slugs: Sequence[str], topic_counts: Optional[dict[str, int]]
) -> list[str]:
    """Topic slugs ordered rarest-first within this page's own pool.

    Rarity is a decent proxy for newsworthiness: "property taxes" appears
    in 450 archived meetings and "surveillance cameras" in a handful, so
    when one snippet contains both, the surveillance mention is the one a
    reader came for. Ties fall back to TOPICS order so the result is
    deterministic (a stored highlight must render identically on every
    request).
    """
    order = {topic.slug: index for index, topic in enumerate(TOPICS)}
    counts = topic_counts or {}
    return sorted(slugs, key=lambda slug: (counts.get(slug, 0), order.get(slug, 999)))


def _marks_for(
    slugs: Sequence[str], topic_counts: Optional[dict[str, int]]
) -> list[str]:
    """Which topics in a snippet actually get `<mark>`ed.

    Rarest first (see `_rank_topics_by_rarity()`), capped at
    MAX_MARKED_TOPICS -- see that constant for the real case behind the
    cap, and for why a rarity-ratio filter was tried and rejected.

    Note the tiebreak does real work here: within a small pool every
    topic has a count of 1, so ranking falls through to curated TOPICS
    order -- which is roughly newsworthiness-ordered, putting
    `surveillance-cameras` ahead of `libraries-parks`.
    """
    return _rank_topics_by_rarity(slugs, topic_counts)[:MAX_MARKED_TOPICS]


def _build_featured(
    pages: Sequence[dict],
    highlights: dict[int, dict],
    topic_slug: Optional[str],
    limit: int,
    topic_counts: Optional[dict[str, int]] = None,
) -> list[dict]:
    """Featured cards for the newest pages that have a usable highlight.

    Date-ordered, but with a **topic diversity cap**: at most
    `MAX_FEATURED_PER_TOPIC` cards may share a topic, so one busy subject
    cannot take over the page. Real case that prompted this (San Diego's
    hub, 2026-08-23): six cards, two of them cannabis and two housing,
    while a public comment delivered *in character as Darth Vader* about
    flock camera surveillance sat in the same pool. Recency alone had no
    way to prefer the interesting one.

    Two passes rather than a sort, so recency still drives the result:
    pass one takes cards whose topics are not yet at the cap, pass two
    backfills any remaining slots from what was skipped, in the original
    date order. That means the cap never *shrinks* the featured set --
    a page whose meetings genuinely all share one topic still fills up.

    A card with no topics at all is never constrained: it cannot cluster,
    and excluding it would quietly bias the page toward topic-tagged
    meetings.
    """
    candidates: list[dict] = []
    for page in pages:
        highlight = highlights.get(page["id"])
        if not highlight:
            continue
        entry = _featured_entry(page, highlight, topic_slug, topic_counts)
        if entry is not None:
            candidates.append(entry)

    # With a topic explicitly selected every card is *about* that topic by
    # construction, so a diversity cap would be self-defeating.
    if topic_slug:
        return candidates[:limit]

    featured: list[dict] = []
    skipped: list[dict] = []
    used: dict[str, int] = {}
    for entry in candidates:
        if len(featured) >= limit:
            break
        topics = entry["topics"]
        if topics and all(
            used.get(slug, 0) >= MAX_FEATURED_PER_TOPIC for slug in topics
        ):
            skipped.append(entry)
            continue
        featured.append(entry)
        for slug in topics:
            used[slug] = used.get(slug, 0) + 1
    if len(featured) < limit:
        featured.extend(skipped[: limit - len(featured)])
    return featured


def _pool_topic_counts(highlights: dict[int, dict]) -> dict[str, int]:
    """topic slug -> how many meetings in this pool carry a moment for it.
    Shared by the chips (which rank by it) and the featured cards (which
    mark the rarest topics), so the two can never disagree."""
    counts: dict[str, int] = {}
    for highlight in highlights.values():
        for slug in highlight.get("topic_moments") or {}:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


def _topic_chips(highlights: dict[int, dict], active_slug: Optional[str]) -> list[dict]:
    """Curated topics that actually appear in this pool, most-covered
    first, with the meeting count behind each one.

    A topic with no meetings behind it is omitted rather than rendered
    as an empty chip -- a chip that leads to "no results" is worse than
    no chip, both for a reader and for a crawler following it."""
    counts = _pool_topic_counts(highlights)
    chips = []
    for topic in TOPICS:
        count = counts.get(topic.slug, 0)
        if not count:
            continue
        chips.append(
            {
                "slug": topic.slug,
                "label": topic.label,
                "count": count,
                "selected": topic.slug == active_slug,
            }
        )
    chips.sort(key=lambda chip: (-chip["count"], chip["label"]))
    chips = chips[:MAX_TOPIC_CHIPS]
    # The selected topic always stays visible, even if it ranks below the
    # cut -- otherwise following a ?topic= link lands on a page whose own
    # chip row doesn't show what is currently selected.
    if active_slug and not any(chip["selected"] for chip in chips):
        topic = TOPICS_BY_SLUG[active_slug]
        chips.append(
            {
                "slug": topic.slug,
                "label": topic.label,
                "count": counts.get(active_slug, 0),
                "selected": True,
            }
        )
    return chips


def _group_governments(jurisdictions: Sequence[dict]) -> list[dict]:
    """The flat government list split into County / City / School /
    Agency sections, empty sections dropped."""
    buckets: dict[str, list[dict]] = {key: [] for key in GROUP_ORDER}
    for row in jurisdictions:
        buckets[row["gov_type"]].append(row)
    return [
        {"key": key, "label": GROUP_LABELS[key], "rows": buckets[key]}
        for key in GROUP_ORDER
        if buckets[key]
    ]


async def get_state_page_data(
    abbr: str, topic_slug: Optional[str] = None
) -> Optional[dict]:
    """Everything /state/{slug} renders, or None when the state/province
    has no indexable pages (the route 404s). `abbr` works for either a US
    state or a Canadian province/territory -- US_STATE_ABBR_TO_NAME
    combines both (see jurisdiction_format.py), so no country-specific
    branch is needed here just to resolve a display name; a Canadian
    jurisdiction's own ", AB"-style suffix already carries a "(Canada)"
    display marker wherever it's rendered through the jurisdiction_display
    filter (see format_jurisdiction_display()). Anchored suffix match on
    the stored jurisdiction -- normalize_state_suffix() guarantees the
    canonical ", CA" form at write time, so LIKE '%, CA' can't
    false-positive the way list_pages()'s substring ilike would
    ("Decatur, GA" contains "ca"). Same platform != "unknown" exclusion
    and default-version transcript-badge join as get_jurisdiction_coverage().

    Beyond the coverage table this also returns what the page leads with:
    featured meetings carrying **real transcript snippets** deep-linked
    to the moment quoted, topic chips ranked over the recent pool, the
    most active governments, and a freshness count. `topic_slug` (from
    `?topic=`) swaps the featured set to that subject; an unknown slug is
    treated as no topic by the caller.
    """
    async with async_session() as session:
        stmt = (
            select(
                MeetingPage.id,
                MeetingPage.jurisdiction,
                MeetingPage.slug,
                MeetingPage.title,
                MeetingPage.date,
                MeetingPage.meeting_body,
                MeetingPage.created_at,
                TranscriptVersion.id,
                TranscriptVersion.transcript_warnings,
            )
            .outerjoin(
                TranscriptVersion,
                and_(
                    TranscriptVersion.meeting_page_id == MeetingPage.id,
                    TranscriptVersion.is_default.is_(True),
                ),
            )
            .where(
                MeetingPage.jurisdiction.like(f"%, {abbr}"),
                MeetingPage.platform != "unknown",
            )
        )
        rows = (await session.execute(stmt)).all()

        pages = []
        for (
            page_id,
            jurisdiction,
            slug,
            title,
            date,
            meeting_body,
            created_at,
            version_id,
            warnings,
        ) in rows:
            # LIKE is case-insensitive on SQLite (dev/tests), so re-check
            # the suffix exactly -- keeps dev and prod (case-sensitive
            # Postgres LIKE) behaving identically.
            if state_abbr_from_jurisdiction(jurisdiction) != abbr:
                continue
            has_transcript = (
                version_id is not None and _has_real_warning_free_transcript(warnings)
            )
            pages.append(
                {
                    "id": page_id,
                    "jurisdiction": jurisdiction,
                    "slug": slug,
                    "title": title,
                    "date": date,
                    "meeting_body": meeting_body,
                    "created_at": created_at,
                    "has_transcript": has_transcript,
                }
            )
        if not pages:
            return None

        by_date = sorted(pages, key=lambda p: p["date"] or "", reverse=True)
        # Only transcribed meetings can be featured -- the snippet *is*
        # the feature, so a meeting without one has nothing to show.
        pool = [p for p in by_date if p["has_transcript"]][:STATE_HIGHLIGHT_POOL]
        highlights = await _load_highlights(session, [p["id"] for p in pool])
        carded = await pages_with_thumbnails(session, [p["id"] for p in pool])

    # Grouped by hub slug (jurisdiction_hub_slug(), i.e. the display form),
    # not the raw string -- since 2026-08-17 each row links to its /j/{slug}
    # hub, and raw variants of one government ("City of Napa, CA" /
    # "Napa, CA") must be one row pointing at one hub, not two rows with
    # the same display name. `jurisdiction` stays the first raw string
    # seen, for the jurisdiction_display filter and any raw-string uses.
    by_hub: dict[str, list[dict]] = {}
    for p in pages:
        by_hub.setdefault(jurisdiction_hub_slug(p["jurisdiction"]) or "", []).append(p)
    jurisdictions = []
    for hub_slug in sorted(
        by_hub, key=lambda s: by_hub[s][0]["jurisdiction"].casefold()
    ):
        examples = by_hub[hub_slug]
        # The linked example must belong to *this* government: pick the
        # newest transcribed meeting, falling back to the newest at all.
        ordered = sorted(examples, key=lambda e: e["date"] or "", reverse=True)
        example = next((e for e in ordered if e["has_transcript"]), ordered[0])
        body = next((e["meeting_body"] for e in examples if e["meeting_body"]), None)
        jurisdictions.append(
            {
                "jurisdiction": examples[0]["jurisdiction"],
                "hub_slug": hub_slug or None,
                "example": example,
                "page_count": len(examples),
                "gov_type": classify_government(examples[0]["jurisdiction"], body),
            }
        )

    active_slug = topic_slug if topic_slug in TOPICS_BY_SLUG else None
    topic_counts = _pool_topic_counts(highlights)
    featured = _build_featured(
        pool, highlights, active_slug, STATE_FEATURED_COUNT, topic_counts
    )
    # A topic chip is only offered when it has meetings behind it, so an
    # empty featured set here means the pool changed under a cached chip
    # list; fall back to the untopiced set rather than an empty page.
    if active_slug and not featured:
        featured = _build_featured(
            pool, highlights, None, STATE_FEATURED_COUNT, topic_counts
        )
        active_slug = None
    _attach_thumbnails(featured, carded)

    now = datetime.now(timezone.utc)

    def _within(page: dict, days: int) -> bool:
        created = page.get("created_at")
        if created is None:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (now - created) <= timedelta(days=days)

    active_counts: dict[str, int] = {}
    for p in pages:
        if _within(p, MOST_ACTIVE_WINDOW_DAYS):
            slug_key = jurisdiction_hub_slug(p["jurisdiction"]) or ""
            active_counts[slug_key] = active_counts.get(slug_key, 0) + 1
    most_active = []
    if len(jurisdictions) >= MOST_ACTIVE_MIN_GOVERNMENTS:
        for slug_key, count in sorted(
            active_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )[:MOST_ACTIVE_COUNT]:
            group = by_hub.get(slug_key)
            if not group or not slug_key:
                continue
            most_active.append(
                {
                    "hub_slug": slug_key,
                    "jurisdiction": group[0]["jurisdiction"],
                    "recent_count": count,
                    "total_count": len(group),
                }
            )

    return {
        "abbr": abbr,
        "name": US_STATE_ABBR_TO_NAME[abbr],
        "jurisdictions": jurisdictions,
        "government_groups": _group_governments(jurisdictions),
        "recent_pages": by_date[:25],
        "featured": featured,
        "topic_chips": _topic_chips(highlights, active_slug),
        "active_topic": active_slug,
        "active_topic_label": (
            TOPICS_BY_SLUG[active_slug].label if active_slug else None
        ),
        "most_active": most_active,
        "most_active_days": MOST_ACTIVE_WINDOW_DAYS,
        "recently_added_count": sum(
            1 for p in pages if _within(p, FRESHNESS_WINDOW_DAYS)
        ),
        "freshness_days": FRESHNESS_WINDOW_DAYS,
        "transcript_count": sum(1 for p in pages if p["has_transcript"]),
        # Biggest governments by meeting count, for the meta description:
        # "San Diego, Napa and Long Beach" is what people actually search,
        # and a description naming them beats one that names none. The
        # ", CA" suffix is stripped because the description already says
        # "California" -- repeating it three more times reads as machine
        # output and burns characters Google may truncate.
        "top_jurisdictions": [
            format_jurisdiction_display(j["jurisdiction"]).rsplit(",", 1)[0].strip()
            for j in sorted(jurisdictions, key=lambda j: -j["page_count"])[:3]
        ],
        "total_pages": len(pages),
        "jurisdiction_count": len(jurisdictions),
    }


# --- Jurisdiction hub pages: /j/{slug} -----------------------------------
#
# One landing page per government ("Napa, CA -- public meeting video &
# transcripts"), grouped by jurisdiction_hub_slug() (the display form's
# slug, so raw-string variants of one government consolidate) rather than
# by the raw stored string. Built 2026-08-17 on top of the state pages;
# same posture as those and the sitemap: platform == "unknown" and empty
# pages are excluded throughout.
#
# The archive is wide and shallow (measured 2026-08-17 from the live
# /state/* tables: 574 stateful jurisdictions, 439 with exactly ONE
# meeting, 110 with two, 25 with three+, two with 10+ -- San Diego 42,
# Napa 24). A one-meeting "hub" is a near-duplicate of that meeting's own
# page, i.e. thin/doorway content to a crawler. So every hub *renders*
# (useful navigation, and every /m/* page links to its hub) but only hubs
# with >= JURISDICTION_HUB_MIN_INDEXABLE meetings are indexable (no
# noindex) and listed in sitemap.xml. Evaluated live per request, so a
# singleton hub becomes indexable by itself the moment a second meeting
# lands -- the bulk-ingest scripts add depth over time and this tracks
# it with no code change. One dial; 3 is the conservative alternative.
JURISDICTION_HUB_MIN_INDEXABLE = 2

# Fewer featured cards than a state page: a hub is one government, so
# after a handful of snippets the reader is better served by the full
# meeting list directly below them.
HUB_FEATURED_COUNT = 6


def _hub_base_conditions():
    return (
        MeetingPage.jurisdiction.is_not(None),
        MeetingPage.platform != "unknown",
        ~_is_empty_page_condition(),
    )


async def _hub_groups(session) -> dict[str, dict]:
    """slug -> {display, jurisdictions: [raw strings], page_count,
    last_updated, state_abbr}, from one GROUP BY over indexable, non-empty
    pages. A few hundred rows -- cheap enough to run per request (no
    cache, so nothing can go stale), same approach the state pages use."""
    stmt = (
        select(
            MeetingPage.jurisdiction,
            func.count(),
            func.max(MeetingPage.updated_at),
        )
        .where(*_hub_base_conditions())
        .group_by(MeetingPage.jurisdiction)
    )
    rows = (await session.execute(stmt)).all()
    groups: dict[str, dict] = {}
    for jurisdiction, count, last_updated in rows:
        slug = jurisdiction_hub_slug(jurisdiction)
        if not slug:
            continue
        g = groups.setdefault(
            slug,
            {
                "slug": slug,
                "display": format_jurisdiction_display(jurisdiction),
                "jurisdictions": [],
                "page_count": 0,
                "last_updated": last_updated,
                "state_abbr": state_abbr_from_jurisdiction(jurisdiction),
            },
        )
        g["jurisdictions"].append(jurisdiction)
        g["page_count"] += count
        if last_updated and (
            g["last_updated"] is None or last_updated > g["last_updated"]
        ):
            g["last_updated"] = last_updated
    return groups


async def get_jurisdiction_hub_data(
    slug: str, topic_slug: Optional[str] = None
) -> Optional[dict]:
    """Everything /j/{slug} renders, or None when no indexable page maps to
    this slug (the route 404s). Every meeting for the hub's raw
    jurisdiction strings, newest first; counts, date range, transcript
    count, a by-body breakdown (meeting_body, e.g. "City Council" x 30 --
    None when the split never happened); the state for the breadcrumb and
    "Part of {State}" link; and `indexable`, the threshold verdict the
    template turns into a robots meta and the sitemap uses to include the
    hub. Loads every meeting for one government -- San Diego's 42 is the
    current maximum, so no pagination; the "search all" link to
    /meetings?jurisdiction= covers a future 500-meeting city."""
    async with async_session() as session:
        groups = await _hub_groups(session)
        group = groups.get(slug)
        if group is None:
            return None
        stmt = (
            select(
                MeetingPage.id,
                MeetingPage.slug,
                MeetingPage.title,
                MeetingPage.date,
                MeetingPage.jurisdiction,
                MeetingPage.meeting_body,
                TranscriptVersion.id,
                TranscriptVersion.transcript_warnings,
            )
            .outerjoin(
                TranscriptVersion,
                and_(
                    TranscriptVersion.meeting_page_id == MeetingPage.id,
                    TranscriptVersion.is_default.is_(True),
                ),
            )
            .where(
                MeetingPage.jurisdiction.in_(group["jurisdictions"]),
                *_hub_base_conditions(),
            )
            .order_by(
                MeetingPage.date.desc().nulls_last(), MeetingPage.created_at.desc()
            )
        )
        rows = (await session.execute(stmt)).all()

        pages = [
            {
                "id": page_id,
                "slug": page_slug,
                "title": title,
                "date": date,
                "jurisdiction": jurisdiction,
                "meeting_body": meeting_body,
                "has_transcript": version_id is not None
                and _has_real_warning_free_transcript(warnings),
            }
            for page_id, page_slug, title, date, jurisdiction, meeting_body, version_id, warnings in rows
        ]
        if not pages:
            return None
        # `pages` is already newest-first from the query's ORDER BY, so
        # the transcribed subset is too. A hub is one government -- San
        # Diego's 44 meetings is the current maximum -- so the whole
        # transcribed set is the pool, no STATE_HIGHLIGHT_POOL cap needed.
        pool = [p for p in pages if p["has_transcript"]]
        highlights = await _load_highlights(session, [p["id"] for p in pool])
        carded = await pages_with_thumbnails(session, [p["id"] for p in pool])

    active_slug = topic_slug if topic_slug in TOPICS_BY_SLUG else None
    topic_counts = _pool_topic_counts(highlights)
    featured = _build_featured(
        pool, highlights, active_slug, HUB_FEATURED_COUNT, topic_counts
    )
    if active_slug and not featured:
        featured = _build_featured(
            pool, highlights, None, HUB_FEATURED_COUNT, topic_counts
        )
        active_slug = None
    _attach_thumbnails(featured, carded)
    body_counts: dict[str, int] = {}
    for p in pages:
        if p["meeting_body"]:
            body_counts[p["meeting_body"]] = body_counts.get(p["meeting_body"], 0) + 1
    bodies = sorted(body_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    dates = sorted(p["date"] for p in pages if p["date"])
    abbr = group["state_abbr"]
    return {
        "slug": slug,
        "display": group["display"],
        "pages": pages,
        "total_pages": len(pages),
        "transcript_count": sum(1 for p in pages if p["has_transcript"]),
        "bodies": [{"name": n, "count": c} for n, c in bodies],
        "earliest_date": dates[0] if dates else None,
        "latest_date": dates[-1] if dates else None,
        "state_abbr": abbr,
        "state_name": US_STATE_ABBR_TO_NAME.get(abbr) if abbr else None,
        "state_slug": state_slug_from_abbr(abbr) if abbr else None,
        "featured": featured,
        "topic_chips": _topic_chips(highlights, active_slug),
        "active_topic": active_slug,
        "active_topic_label": (
            TOPICS_BY_SLUG[active_slug].label if active_slug else None
        ),
        "indexable": len(pages) >= JURISDICTION_HUB_MIN_INDEXABLE,
        "min_indexable": JURISDICTION_HUB_MIN_INDEXABLE,
        # The raw strings, for the /meetings?jurisdiction= "search all" link
        # (the first is as good as any -- list_pages()'s jurisdiction
        # filter is a substring match).
        "search_jurisdiction": group["jurisdictions"][0],
    }


async def list_indexable_hub_entries() -> list[dict]:
    """[{slug, display, last_updated}] for every hub at or above
    JURISDICTION_HUB_MIN_INDEXABLE -- sitemap.xml's /j/ entries (real
    lastmod, same as the state entries). Sorted by slug for a stable
    file."""
    async with async_session() as session:
        groups = await _hub_groups(session)
    return sorted(
        (
            {
                "slug": g["slug"],
                "display": g["display"],
                "last_updated": g["last_updated"],
            }
            for g in groups.values()
            if g["page_count"] >= JURISDICTION_HUB_MIN_INDEXABLE
        ),
        key=lambda g: g["slug"],
    )


async def list_all_page_slugs() -> list[dict]:
    """Every indexable page's slug + updated_at, unpaginated -- for
    sitemap.xml. Excludes platform == "unknown" (generic_fallback) pages:
    meeting_page.html noindexes exactly those, so listing them in the
    sitemap sends Google contradictory signals (the real Search Console
    "Excluded by 'noindex' tag ... in a sitemap" alert, 2026-08-17).
    Same reasoning for empty pages (_is_empty_page_condition()): the
    template noindexes those too, and they're the likeliest source of
    Search Console's "Page indexed without content" (see
    CLAUDE_BACKLOG.md); a page that later fills in reappears here on its
    own since the predicate is evaluated live.
    Fine as a single query at hundreds/thousands of rows; revisit (batching,
    a sitemap index + sub-sitemaps) only once actually approaching the
    ~50k-URL point where Google expects that split."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(MeetingPage.slug, MeetingPage.updated_at)
                .where(
                    MeetingPage.platform != "unknown",
                    ~_is_empty_page_condition(),
                )
                .order_by(MeetingPage.updated_at.desc())
            )
        ).all()
    return [{"slug": slug, "updated_at": updated_at} for slug, updated_at in rows]


async def list_recent_pages_for_feed(
    *, jurisdiction: Optional[str] = None, limit: int = 50
) -> list[dict]:
    """Most-recently-archived pages for feed.xml -- a separate, deliberately
    simple query rather than reusing list_pages()'s pagination/multi-filter
    machinery, since a feed only ever wants "the last N, optionally scoped
    to one jurisdiction," newest first, with no page number to track.
    Empty pages are excluded, same as list_pages()'s default browse -- a
    feed entry a subscriber can't watch or read anything on is just
    noise (and a subscriber's reader would never re-fetch it once the
    source fills the page in)."""
    limit = max(1, min(limit, 100))
    stmt = (
        select(MeetingPage)
        .where(~_is_empty_page_condition())
        .order_by(MeetingPage.created_at.desc())
        .limit(limit)
    )
    if jurisdiction:
        terms = jurisdiction_search_terms(jurisdiction)
        stmt = stmt.where(
            or_(*(MeetingPage.jurisdiction.ilike(f"%{t}%") for t in terms))
        )

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


# --- On-demand transcription -------------------------------------------
#
# A job moves pending_confirmation -> queued -> in_progress -> completed |
# failed. pending_confirmation and queued/in_progress are both "active" for
# the purposes of blocking a duplicate request against the same page, but
# only queued/in_progress count toward MAX_CONCURRENT_TRANSCRIPTION_JOBS --
# an unconfirmed request isn't spending any worker/transcription time yet.
#
# A pending_confirmation job older than PENDING_CONFIRMATION_EXPIRY is
# treated as abandoned: it no longer blocks a fresh request for the same
# page (create_transcription_job), and a stale confirmation-email link for
# it no longer works (confirm_transcription_job) -- both need to agree,
# otherwise a late click on an abandoned link could resurrect a job after
# a newer one already superseded it, leaving two active jobs for the same
# page. The row itself is left as-is (still pending_confirmation forever,
# never flipped to some new "expired" status) -- it's dead weight, not
# correctness-affecting, since both read paths already skip it by age.

PENDING_CONFIRMATION_EXPIRY = timedelta(hours=48)
SPENDING_JOB_STATUSES = ("queued", "in_progress")
MAX_CONCURRENT_TRANSCRIPTION_JOBS = 15  # was 3; raised 2026-08-08, see BACKLOG_DONE.md

# claim_next_chunk() orders by priority.desc() first -- higher claimed
# first, FIFO within the same tier. Named constants, not raw numbers
# scattered through call sites, with room for a higher tier later without
# a schema change (the column's just an int). PRIORITY_MEDIUM's value
# must match TranscriptionJob.priority's model-level default/server_default
# in models.py (kept as a literal there, not imported, to avoid a
# models->crud import cycle) -- update both together if this ever changes.
PRIORITY_LOW = 0  # reserved for future self-generated/idle-time batch work
PRIORITY_MEDIUM = 10  # every real user-submitted request today
# Was 10 minutes; shortened live 2026-08-08 after a real OOM-crash-loop
# meant the countdown kept resetting (each auto-restart re-claimed the
# job, pushing "stale" 10 more minutes out every time) -- annoying to
# wait out mid-debugging. 5 minutes is still comfortably longer than a
# single chunk should ever legitimately take with the "tiny" model. This
# is still purely crash detection, not a concurrent-worker guard -- that's
# claim_next_chunk()'s own FOR UPDATE SKIP LOCKED below, which already
# stops two worker processes (a second one is real now, see render.yaml's
# rtr-transcription-worker-2) from double-claiming the same row. This
# window only matters for a worker that crashes mid-chunk without ever
# calling report_chunk_result() to release its claim -- after it elapses,
# *some* worker (the other replica, or this one after a restart) can
# reclaim the row; which worker that ends up being isn't what this timer
# is about.
STALE_CLAIM_AFTER = timedelta(minutes=5)
MAX_CONSECUTIVE_CHUNK_FAILURES = 3

# Escalating-backoff retry for a real user-submitted (PRIORITY_MEDIUM+) job
# that's exhausted MAX_CONSECUTIVE_CHUNK_FAILURES -- added 2026-08-19 after
# a real case (job 256, Redwood City CA, requested by an early user)
# failed on a single ffmpeg timeout and a later manual re-run of the exact
# same source succeeded outright, confirming the source wasn't genuinely
# broken. A PRIORITY_LOW auto-generated job deliberately does NOT use
# this -- it keeps the older immediate-"failed" behavior, since it already
# has its own separate page-level escalating cooldown
# (AUTO_TRANSCRIPTION_BASE_COOLDOWN) that re-tries the page later anyway;
# duplicating both mechanisms on the same job would just double-count the
# backoff. Doubling per retry, same shape as that cooldown, scaled to
# hours instead of days since a stalled *specific request* someone is
# waiting on deserves a much faster second look than idle backlog work.
MAX_JOB_RETRIES = 3
JOB_RETRY_BASE_DELAY = timedelta(hours=1)
JOB_RETRY_MAX_DELAY = timedelta(hours=6)

# Escalating backoff for auto-generated transcription jobs (worker/main.py's
# idle-time candidate search) -- decided 2026-08-09 over a flat cooldown or
# a hard give-up-forever cap: each consecutive failure for the same page
# doubles the wait before it's tried again, capped at
# AUTO_TRANSCRIPTION_MAX_COOLDOWN (matches ARCHIVE_RECHECK_AFTER's existing
# 30-day precedent) rather than escalating forever -- a page that's failed
# many times still gets retried eventually, on the theory that a broken
# source might work again later (a transient outage, an adapter bug fixed
# in a later deploy), just far less often than a page that's never failed.
AUTO_TRANSCRIPTION_BASE_COOLDOWN = timedelta(days=1)
AUTO_TRANSCRIPTION_MAX_COOLDOWN = timedelta(days=30)


async def promote_transcript_version(session, page_id: int, version_id: int) -> None:
    """Make `version_id` the one /m/{slug} renders by default, demoting
    whichever version held that spot before -- never deletes anything, the
    demoted version stays reachable via the existing `?version=` picker.
    Real gap this closes: previously only the very first TranscriptVersion
    a page ever got was set is_default, and nothing later ever promoted a
    subsequent one (see BACKLOG_DONE.md). Caller must be inside an existing
    session/transaction (this doesn't commit) -- both call sites below
    (finalize) already are.
    """
    versions = (
        (
            await session.execute(
                select(TranscriptVersion).where(
                    TranscriptVersion.meeting_page_id == page_id
                )
            )
        )
        .scalars()
        .all()
    )
    for v in versions:
        v.is_default = v.id == version_id


async def manually_promote_transcript_version(
    *, slug: str, version_id: int, clear_warnings: bool = False
) -> Optional[dict]:
    """Admin action: make `version_id` this page's default TranscriptVersion.
    Real gap this closes -- found 2026-08-12 fixing a real stale ALL-CAPS
    transcript (Minneapolis City Council): `promote_transcript_version()`
    only ever fires automatically from inside `ingest_resolution()`'s own
    `_is_real_improvement()` check (no segments yet, or no language yet on
    the current default), which doesn't cover "a fresh push is simply
    better-quality than what's already there" -- a manually-pushed
    replacement for an already-has-segments-and-language default has no
    path to become the default at all without this. Standalone
    session/commit, same "always a top-level admin action" reasoning as
    `correct_transcript_version_language()` right below.

    `clear_warnings=True` also strips any `_GARBLED_MARKER`/`_HALLUCINATION_MARKER`
    entries from the *promoted* version's own `transcript_warnings` --
    deliberately a filter, not a wipe (see 2026-08-20 correction below).
    Real gap this closes -- found 2026-08-20 investigating why several
    YouTube pages (e.g. nashua-2025-05-28-committee-on-infrastructure)
    stayed permanently flagged `garbled_transcript` despite
    scripts/fetch_youtube_transcripts.py successfully re-fetching and
    promoting them every day: `ingest_resolution()` dedupes by content
    hash, so a re-fetch of the same underlying caption track (via a
    different library than the original resolve) reuses the existing,
    already-garbled-flagged version row instead of creating a fresh one --
    promoting it alone never cleared that stale flag, even though the
    caller's whole point in promoting was "trust this over whatever's
    already there." Never touches the *demoted* version's warnings -- same
    "never destroys history" spirit as the rest of this function; only the
    version now being vouched for gets its flag reset.

    Correction same day: the first version of this simply reset
    `transcript_warnings` to `[]` outright, which also silently discarded
    unrelated, still-true informational warnings on the same list (e.g.
    "These are YouTube's auto-generated captions..." from
    app/platforms/youtube.py) -- a real regression caught live on the
    first 6 pages this ran against in production, fixed here by filtering
    only the two quality-blocking markers instead. See
    `correct_transcript_version_warnings()` below for how those 6 pages'
    dropped disclaimer text was restored.
    """
    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        if page is None:
            return None

        version = await session.get(TranscriptVersion, version_id)
        if version is None or version.meeting_page_id != page.id:
            return None

        await promote_transcript_version(session, page.id, version_id)
        if clear_warnings:
            version.transcript_warnings = [
                w
                for w in (version.transcript_warnings or [])
                if _GARBLED_MARKER not in w and _HALLUCINATION_MARKER not in w
            ]
        await session.commit()
        return {"slug": slug, "promoted_version_id": version_id}


async def correct_transcript_version_warnings(
    *, slug: str, warnings: list[str], version_id: Optional[int] = None
) -> Optional[dict]:
    """Admin correction for a TranscriptVersion's `transcript_warnings` list
    -- same "public report, admin fixes" shape as
    `correct_transcript_version_language()` right below (targets the
    page's current default when `version_id` isn't given). Built 2026-08-20
    specifically to restore informational warnings (e.g. the YouTube
    auto-caption disclaimer) that `manually_promote_transcript_version()`'s
    first `clear_warnings=True` implementation had wiped outright on 6 real
    production pages before that was corrected to filter instead -- see
    its docstring. General-purpose beyond that one-time fix: any other
    future case needing a direct warnings correction (mirroring how
    `correct_transcript_version_language()` already exists for the
    language field) can reuse this rather than a new one-off.
    """
    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        if page is None:
            return None

        if version_id is not None:
            version = await session.get(TranscriptVersion, version_id)
            if version is None or version.meeting_page_id != page.id:
                return None
        else:
            version = (
                (
                    await session.execute(
                        select(TranscriptVersion).where(
                            TranscriptVersion.meeting_page_id == page.id,
                            TranscriptVersion.is_default.is_(True),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if version is None:
                return None

        version.transcript_warnings = warnings
        await session.commit()
        return {
            "slug": slug,
            "version_id": version.id,
            "transcript_warnings": version.transcript_warnings,
        }


async def correct_transcript_version_language(
    *, slug: str, language: str, version_id: Optional[int] = None
) -> Optional[dict]:
    """Admin correction for a wrong/mis-detected TranscriptVersion.language
    -- the "public report, admin fixes" flow decided 2026-08-09 (see
    BACKLOG_DONE.md's language-picker entry). Applies to any version's
    source, not just self-transcribed ones: a scraped caption's
    source-provided language can be just as wrong as langdetect's guess.

    Targets the page's current default version when version_id isn't
    given, since that's almost always what a reporter was actually
    looking at when they filed the report -- correcting a specific
    non-default version needs its id looked up first (e.g. via
    get_page_by_slug()'s versions list). Manages its own session/commit,
    unlike promote_transcript_version() -- this is always a standalone
    top-level admin action, never chained inside another write.
    """
    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        if page is None:
            return None

        if version_id is not None:
            version = await session.get(TranscriptVersion, version_id)
            if version is None or version.meeting_page_id != page.id:
                return None
        else:
            version = (
                (
                    await session.execute(
                        select(TranscriptVersion).where(
                            TranscriptVersion.meeting_page_id == page.id,
                            TranscriptVersion.is_default.is_(True),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if version is None:
                return None

        version.language = language
        await session.commit()
        return {"slug": slug, "version_id": version.id, "language": version.language}


async def create_transcription_job(
    *,
    payload: dict[str, Any],
    input_url_normalized: str,
    requester_email: str,
    media_url: str,
    media_kind: str,
    probed_duration_seconds: float,
    chunk_size_seconds: int,
    skip_confirmation: bool,
    priority: int = PRIORITY_MEDIUM,
) -> dict:
    """Find-or-create the MeetingPage (a request can be the very first thing
    that ever creates a permanent page for a meeting -- the ephemeral
    resolver page doesn't require one to exist first), then create the job
    -- unless one's already active for this page, in which case that
    existing job's status is returned instead of creating a duplicate.

    `skip_confirmation` is decided by the caller (archive/main.py, after
    checking Resend audience membership) -- this function doesn't reach out
    to Resend itself, keeping external API calls out of the DB layer.
    `priority` defaults to PRIORITY_MEDIUM (every real user-submitted
    request) -- worker/main.py's auto-generation path is the one real
    caller that passes PRIORITY_LOW instead.
    """
    async with async_session() as session:
        page, _ = await _find_or_create_page(session, payload, input_url_normalized)

        not_expired_pending = or_(
            TranscriptionJob.status.in_(SPENDING_JOB_STATUSES),
            # A job waiting out its retry backoff is still "this page has
            # an active request in flight" -- a fresh submit during that
            # window should find the existing job, not start a second one
            # racing it once the retry fires.
            TranscriptionJob.status == "retry_scheduled",
            and_(
                TranscriptionJob.status == "pending_confirmation",
                TranscriptionJob.created_at
                >= datetime.now(timezone.utc) - PENDING_CONFIRMATION_EXPIRY,
            ),
        )
        existing = (
            (
                await session.execute(
                    select(TranscriptionJob)
                    .where(
                        TranscriptionJob.meeting_page_id == page.id, not_expired_pending
                    )
                    .order_by(TranscriptionJob.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if existing:
            await (
                session.commit()
            )  # persist the page if it was just created, even though no job was
            return _job_dict(existing, page)

        active_spend_count = (
            (
                await session.execute(
                    select(TranscriptionJob).where(
                        TranscriptionJob.status.in_(SPENDING_JOB_STATUSES)
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(active_spend_count) >= MAX_CONCURRENT_TRANSCRIPTION_JOBS:
            await session.commit()
            return {"error": "too_many_active_jobs", "slug": page.slug}

        total_chunks = math.ceil(probed_duration_seconds / chunk_size_seconds)
        job = TranscriptionJob(
            meeting_page_id=page.id,
            requester_email=requester_email,
            confirmation_token=None if skip_confirmation else secrets.token_urlsafe(32),
            status="queued" if skip_confirmation else "pending_confirmation",
            media_url=media_url,
            media_kind=media_kind,
            probed_duration_seconds=probed_duration_seconds,
            chunk_size_seconds=chunk_size_seconds,
            total_chunks=total_chunks,
            priority=priority,
        )
        session.add(job)
        await session.commit()
        return _job_dict(job, page)


def _aware(dt: datetime) -> datetime:
    """SQLite (local dev) doesn't enforce tz-awareness on a DateTime(timezone=True)
    column, so a naive datetime can come back even though Postgres (prod)
    always returns an aware one -- treat a naive value as UTC rather than
    letting an aware-vs-naive subtraction raise. Same convention as
    app/main.py's _parse_updated_at()."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cooldown_active(jobs_newest_first: list[tuple], now: datetime) -> bool:
    """The escalating-backoff decision on a page's TranscriptionJob history
    -- `jobs_newest_first` is [(status, updated_at), ...] ordered by
    created_at DESC. Counts *consecutive* failures walking back from the
    most recent job, stopping at the first non-"failed" one (an older
    failure before a completed one is stale history, not part of the
    current streak). Pure so find_auto_transcription_candidate() can
    evaluate it over a batch it fetched in one query, and
    _in_auto_transcription_cooldown() over a single page.

    **A newest job of "completed" is also a cooldown, not a free pass
    (WO-45, 2026-08-23).** This used to return False there, on the
    reasoning that "a completed job means this page already has what it
    needs" -- but both callers only ever reach this function for a page
    that does NOT have a good transcript, so a page whose transcription
    genuinely succeeded and simply found no speech was re-picked
    immediately, forever. Real occurrence: five separate completed jobs,
    5/5 chunks each, on the identical page in 17 minutes (jobs 732-736,
    st-louis-park-high-school-wind-ensemble-concert -- a music concert,
    so an empty transcript is the correct and final answer), producing
    TranscriptVersions 2058-2062 and leaving the public page still
    reading "No transcript". /internal/transcript-quality-audit put 448
    pages in the `blank_transcript` bucket, i.e. that is the size of the
    population this could loop on.

    Deliberately narrow: this changes only how often such a page is
    RETRIED, not whether its transcript counts as good. A blank page
    still reads as needing a transcript everywhere else, and still comes
    back around on the max cooldown -- a government source's own captions
    really can catch up later, which is the whole reason these pages stay
    candidates at all. It just does so monthly instead of every idle
    poll.
    """
    if jobs_newest_first and jobs_newest_first[0][0] == "completed":
        return now < _aware(jobs_newest_first[0][1]) + AUTO_TRANSCRIPTION_MAX_COOLDOWN

    consecutive_failures = 0
    most_recent_failed_at = None
    for status, updated_at in jobs_newest_first:
        if status != "failed":
            break
        consecutive_failures += 1
        if most_recent_failed_at is None:
            most_recent_failed_at = updated_at

    if consecutive_failures == 0:
        return False

    cooldown = min(
        AUTO_TRANSCRIPTION_BASE_COOLDOWN * (2 ** (consecutive_failures - 1)),
        AUTO_TRANSCRIPTION_MAX_COOLDOWN,
    )
    return now < _aware(most_recent_failed_at) + cooldown


async def _in_auto_transcription_cooldown(session, meeting_page_id: int) -> bool:
    """True if this page has failed auto/manual transcription recently
    enough that it shouldn't be tried again yet -- see
    AUTO_TRANSCRIPTION_BASE_COOLDOWN's docstring for the escalating-backoff
    reasoning and _cooldown_active() for the rule. Selects only
    status/updated_at: TranscriptionJob carries `partial_segments` (a whole
    in-progress transcript as JSON), which the previous full-entity select
    dragged along for every job of every page checked."""
    jobs = (
        await session.execute(
            select(TranscriptionJob.status, TranscriptionJob.updated_at)
            .where(TranscriptionJob.meeting_page_id == meeting_page_id)
            .order_by(TranscriptionJob.created_at.desc())
        )
    ).all()
    return _cooldown_active([tuple(j) for j in jobs], datetime.now(timezone.utc))


async def find_auto_transcription_candidate() -> Optional[dict]:
    """Oldest-archived-first MeetingPage missing a good transcript and not
    in escalating-failure cooldown, for worker/main.py's idle-time
    auto-generation. Caller is responsible for confirming the job queue is
    completely empty before calling this -- this function only picks a
    candidate, it doesn't check that itself.

    Two light queries, no transcript data moved -- rewritten 2026-08-17
    after `pg_stat_statements` showed the previous shape (load every
    MeetingPage, then per page call _has_good_transcript() -- which
    selected the full TranscriptVersion incl. its `segments` JSON -- and
    _in_auto_transcription_cooldown()) as the #1 consumer of production
    DB time: 218,480 calls / 47 minutes, i.e. all 102MB of transcript JSON
    pulled through a 64MB-shared_buffers Postgres every 5 idle minutes to
    make one decision. Now: (1) the pages *lacking* a good default
    transcript, in SQL via _good_default_transcript_exists() -- the same
    filter shape /meetings' has_transcript=False uses -- ordered
    created_at ASC (a few hundred light rows, not 1,219 + their
    transcripts); (2) those pages' TranscriptionJob status/updated_at
    history in one query; then the cooldown rule in Python per candidate
    until one passes. Same "oldest page without a good transcript and not
    in cooldown" result as before.
    """
    async with async_session() as session:
        candidates = (
            await session.execute(
                select(
                    MeetingPage.id,
                    MeetingPage.slug,
                    MeetingPage.source_url_normalized,
                    MeetingPage.platform,
                )
                .where(~_good_default_transcript_exists())
                .order_by(MeetingPage.created_at.asc())
            )
        ).all()
        if not candidates:
            return None

        job_rows = (
            await session.execute(
                select(
                    TranscriptionJob.meeting_page_id,
                    TranscriptionJob.status,
                    TranscriptionJob.updated_at,
                )
                .where(TranscriptionJob.meeting_page_id.in_([c[0] for c in candidates]))
                .order_by(TranscriptionJob.created_at.desc())
            )
        ).all()
    jobs_by_page: dict[int, list[tuple]] = {}
    for page_id, status, updated_at in job_rows:
        jobs_by_page.setdefault(page_id, []).append((status, updated_at))

    now = datetime.now(timezone.utc)
    for page_id, slug, source_url, platform in candidates:
        if _cooldown_active(jobs_by_page.get(page_id, []), now):
            continue
        return {
            "meeting_page_id": page_id,
            "slug": slug,
            "source_url": source_url,
            "platform": platform,
        }
    return None


async def create_failed_auto_transcription_job(
    *, meeting_page_id: int, requester_email: str, error_message: str
) -> dict:
    """Records a failed auto-generation attempt (re-resolve failed, no
    media found, or the feasibility check itself failed) as a real, already-
    failed TranscriptionJob row -- deliberately reuses the exact same table
    and escalating-cooldown mechanism a real chunk-processing failure uses,
    rather than a separate "skip list", so a candidate that can't actually
    be transcribed doesn't get re-probed on every single auto-generation
    check until its cooldown catches up too."""
    async with async_session() as session:
        job = TranscriptionJob(
            meeting_page_id=meeting_page_id,
            requester_email=requester_email,
            status="failed",
            media_url="",
            media_kind="video",
            probed_duration_seconds=0,
            chunk_size_seconds=1,
            total_chunks=1,
            error_message=error_message,
            priority=PRIORITY_LOW,
        )
        session.add(job)
        await session.commit()
        return {"job_id": job.id, "status": job.status}


async def confirm_transcription_job(token: str) -> Optional[dict]:
    """Flips a first-time requester's job from pending_confirmation to
    queued once they click the link in their confirmation email. Returns
    None if the token doesn't match any job still awaiting confirmation
    (already confirmed, expired, or never existed) -- the caller shows a
    generic "link invalid or already used" message either way, not
    distinguishing which, same reasoning as the admin/internal routes'
    404-not-401 pattern elsewhere in this codebase."""
    async with async_session() as session:
        job = (
            (
                await session.execute(
                    select(TranscriptionJob).where(
                        TranscriptionJob.confirmation_token == token,
                        TranscriptionJob.status == "pending_confirmation",
                        TranscriptionJob.created_at
                        >= datetime.now(timezone.utc) - PENDING_CONFIRMATION_EXPIRY,
                    )
                )
            )
            .scalars()
            .first()
        )
        if job is None:
            return None
        job.status = "queued"
        job.confirmation_token = None
        page = await session.get(MeetingPage, job.meeting_page_id)
        await session.commit()
        return _job_dict(job, page)


async def claim_next_chunk() -> Optional[dict]:
    """Atomically claims the oldest queued/in_progress job with no live
    claim, marking it in_progress and stamping claimed_at so a second
    concurrent caller won't also pick it up. The staleness window
    (STALE_CLAIM_AFTER) exists for a crashed/restarted worker process.

    Genuine multi-worker concurrency (several worker processes/replicas
    calling this at once, to use more than one CPU -- see BACKLOG.md's
    "Render worker plan sizing" follow-up) is now real, not hypothetical,
    so the SELECT below takes `FOR UPDATE SKIP LOCKED` on Postgres: two
    concurrent transactions each lock the row they're about to claim, so
    neither can select a row the other is mid-claim on, and SKIP LOCKED
    means a caller that would've collided just falls through to the next
    candidate instead of blocking on the lock. Without this, the previous
    plain SELECT-then-UPDATE had a real TOCTOU window where two processes
    could both read the same row before either committed. Same dialect
    gate as _fts_available() -- SQLite (dev/CI) doesn't support SKIP
    LOCKED, and doesn't need to: nothing there runs more than one process
    against the same DB file.
    """
    now = datetime.now(timezone.utc)
    stale_before = now - STALE_CLAIM_AFTER

    async with async_session() as session:
        stmt = (
            select(TranscriptionJob)
            .where(
                or_(
                    TranscriptionJob.status.in_(("queued", "in_progress")),
                    and_(
                        TranscriptionJob.status == "retry_scheduled",
                        TranscriptionJob.next_retry_at <= now,
                    ),
                ),
                (TranscriptionJob.claimed_at.is_(None))
                | (TranscriptionJob.claimed_at < stale_before),
            )
            .order_by(
                TranscriptionJob.priority.desc(),
                TranscriptionJob.created_at.asc(),
            )
            .limit(1)
        )
        if session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        job = (await session.execute(stmt)).scalars().first()
        if job is None:
            return None

        job.status = "in_progress"
        job.claimed_at = now
        job.next_retry_at = None
        page = await session.get(MeetingPage, job.meeting_page_id)
        await session.commit()

        return {
            "job_id": job.id,
            "meeting_page_id": job.meeting_page_id,
            "source_url": page.source_url_normalized if page else None,
            "platform": page.platform if page else None,
            "media_url": job.media_url,
            "chunk_index": job.chunks_completed,  # next chunk to process
            "total_chunks": job.total_chunks,
            "chunk_size_seconds": job.chunk_size_seconds,
            "probed_duration_seconds": job.probed_duration_seconds,
            # Every segment persisted by a prior chunk of this same job --
            # the worker needs this to detect a seam-duplicate at this
            # chunk's own boundary (worker/segment_utils.py's
            # count_seam_overlap_segments(), see its own docstring for
            # why -- confirmed live 2026-08-16, see BACKLOG_DONE.md)
            # before it ever calls report_chunk_result().
            "partial_segments": job.partial_segments,
        }


async def report_chunk_result(
    job_id: int,
    *,
    success: bool,
    shifted_segments: Optional[list] = None,
    drop_previous_tail: int = 0,
    error: Optional[str] = None,
    chunk_index: Optional[int] = None,
) -> dict:
    """Called by the worker after attempting one chunk. On success, appends
    already-offset segments and advances progress; if that was the last
    chunk, finalizes the job (writes the TranscriptVersion, promotes it,
    caller -- archive/main.py -- sends the completion email afterward using
    this function's returned `completed`/`transcript_version_id`). On
    failure, counts toward MAX_CONSECUTIVE_CHUNK_FAILURES before doing
    anything further -- a single flaky chunk (transient network blip)
    shouldn't fail an otherwise-fine multi-hour job.

    Once that budget's exhausted, a real user-priority job (priority >=
    PRIORITY_MEDIUM) with retries left gets rescheduled (status
    "retry_scheduled", see MAX_JOB_RETRIES/JOB_RETRY_BASE_DELAY's own
    comment) rather than failed outright -- added 2026-08-19 after a real
    case where the exact same source succeeded on a later manual re-run,
    meaning the original failure wasn't the source being genuinely broken.
    A PRIORITY_LOW auto-generated job, or a user job that's used up its
    retries, still goes straight to "failed" -- the terminal outcome
    worker/main.py's failure email (now actually reachable, see that
    module's own note) fires on.

    `chunk_index` (optional, for the failure_history entry only -- callers
    written before 2026-08-19 that omit it still work, just with a null
    chunk_index in that one history entry).

    `drop_previous_tail` (default 0, a pure no-op -- existing callers/tests
    are unaffected): the caller (worker/main.py) has already compared this
    chunk's own segments against the job's previously-persisted
    `partial_segments` (via worker/segment_utils.py's
    count_seam_overlap_segments(), using the `partial_segments` claim_next_
    chunk() now returns) and found this many trailing entries there are a
    real seam-duplicate of what `shifted_segments` is about to restate --
    see that function's own docstring for the confirmed root cause. They're
    dropped here, right before the new segments are appended, so a fixed
    HLS chunk-boundary duplicate never reaches a real TranscriptVersion.
    """
    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        if job is None:
            return {"error": "job_not_found"}

        job.claimed_at = None  # release the claim regardless of outcome

        if not success:
            job.consecutive_chunk_failures += 1
            job.error_message = error
            job.failure_history = [
                *job.failure_history,
                {
                    "chunk_index": chunk_index,
                    "error": error,
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            ]
            if job.consecutive_chunk_failures >= MAX_CONSECUTIVE_CHUNK_FAILURES:
                if (
                    job.priority >= PRIORITY_MEDIUM
                    and job.retry_count < MAX_JOB_RETRIES
                ):
                    job.retry_count += 1
                    delay = min(
                        JOB_RETRY_BASE_DELAY * (2 ** (job.retry_count - 1)),
                        JOB_RETRY_MAX_DELAY,
                    )
                    job.status = "retry_scheduled"
                    job.next_retry_at = datetime.now(timezone.utc) + delay
                    job.consecutive_chunk_failures = 0  # fresh budget for the retry
                else:
                    job.status = "failed"
            await session.commit()
            return {
                "status": job.status,
                "consecutive_chunk_failures": job.consecutive_chunk_failures,
                "retry_count": job.retry_count,
                "next_retry_at": job.next_retry_at.isoformat()
                if job.next_retry_at
                else None,
            }

        job.consecutive_chunk_failures = 0
        kept_previous = (
            job.partial_segments[: len(job.partial_segments) - drop_previous_tail]
            if drop_previous_tail
            else job.partial_segments
        )
        job.partial_segments = [*kept_previous, *(shifted_segments or [])]
        job.chunks_completed += 1

        if job.chunks_completed >= job.total_chunks:
            language = detect_language_from_texts(
                s["text"] for s in job.partial_segments
            )
            # Real, confirmed gap closed 2026-08-16 (Port Coquitlam, BC --
            # see BACKLOG_DONE.md and archive/utils/transcription_quality.py's
            # own docstring): a Whisper-produced transcript had no equivalent
            # of the scraped-caption path's is_likely_garbled() check before
            # this version went live. Applied here, once, on the full
            # finished transcript -- covers both a real user-submitted job
            # and the worker's own idle-time auto-generated ones, the one
            # place both actually finish.
            hallucination_warnings = detect_hallucination_warnings(job.partial_segments)
            version = TranscriptVersion(
                meeting_page_id=job.meeting_page_id,
                language=language,
                source="transcribed",
                is_default=False,  # promote_transcript_version sets the real default below
                segments=sorted(job.partial_segments, key=lambda s: s["start"]),
                transcript_warnings=hallucination_warnings,
                content_hash=_content_hash(job.partial_segments),
            )
            session.add(version)
            await session.flush()  # assigns version.id
            await promote_transcript_version(session, job.meeting_page_id, version.id)
            job.transcript_version_id = version.id
            job.status = "completed"
            page = await session.get(MeetingPage, job.meeting_page_id)
            if page is not None:
                # The finished transcript must become searchable -- see
                # _refresh_search_corpus()'s docstring for the real gap
                # this closes.
                await _refresh_search_corpus(session, page)
            await session.commit()
            return {
                "status": "completed",
                "transcript_version_id": version.id,
                "meeting_page_slug": page.slug if page else None,
                "meeting_page_title": page.title if page else None,
            }

        await session.commit()
        return {
            "status": "in_progress",
            "chunks_completed": job.chunks_completed,
            "total_chunks": job.total_chunks,
        }


def _job_dict(job: TranscriptionJob, page: Optional[MeetingPage]) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "chunks_completed": job.chunks_completed,
        "total_chunks": job.total_chunks,
        "meeting_page_slug": page.slug if page else None,
        "meeting_page_title": page.title if page else None,
        "error_message": job.error_message,
        # Only meaningful to internal (token-gated) callers -- app/main.py's
        # public status-poll proxy strips this before it ever reaches a
        # browser, no reason to echo a viewer's own email back to them.
        "requester_email": job.requester_email,
        # Real bug fixed 2026-08-11: this was missing entirely, so
        # worker/main.py's _send_completion_email() always looked up
        # None and every completion email's transcript excerpt rendered
        # empty -- the data already exists on the model (set in
        # report_chunk_result() above), it just never got surfaced here.
        "transcript_version_id": job.transcript_version_id,
        # Added 2026-08-19 for worker/main.py's admin failure alert (see
        # email.send_admin_job_failure_alert()) -- source_url is the
        # original government meeting URL, distinct from meeting_page_slug
        # (this app's own /m/ page).
        "source_url": page.source_url_normalized if page else None,
        "retry_count": job.retry_count,
        "failure_history": job.failure_history,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


async def get_transcription_job_status(job_id: int) -> Optional[dict]:
    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        if job is None:
            return None
        page = await session.get(MeetingPage, job.meeting_page_id)
        return _job_dict(job, page)


async def get_confirmation_token(job_id: int) -> Optional[str]:
    """Deliberately separate from _job_dict() (which never includes the
    token) -- the only caller is archive/main.py's create-job endpoint,
    immediately after creating a pending_confirmation job, solely to build
    the emailed confirm link. Never returned to any other caller."""
    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        return job.confirmation_token if job else None


# --- Saved meetings/searches (accounts phase 1, Clerk-backed) ----------
#
# clerk_user_id is Clerk's own stable user id -- this module never sees or
# stores an email address for accounts; Clerk holds that. See
# app/utils/clerk_auth.py / archive/utils/clerk_auth.py for verification,
# and app/main.py's /api/clerk/webhook for the account-deletion cascade
# that makes delete_account_data() below the entire right-to-deletion
# story on our side.


async def is_meeting_saved(clerk_user_id: str, meeting_page_id: int) -> bool:
    """For the correct initial "Save this meeting" vs. "Saved" button
    state on page load -- called only when a request already has a
    verified Clerk session (see archive/main.py's meeting_page() route),
    so an anonymous visitor never pays this query at all."""
    async with async_session() as session:
        existing = (
            (
                await session.execute(
                    select(SavedItem.id).where(
                        SavedItem.clerk_user_id == clerk_user_id,
                        SavedItem.item_type == "saved_meeting",
                        SavedItem.meeting_page_id == meeting_page_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        return existing is not None


async def save_meeting(clerk_user_id: str, slug: str) -> Optional[dict]:
    """Saves a meeting to this account, keyed by its slug. Returns the
    saved item as a dict, or None if no meeting with that slug exists (the
    route turns that into a 404). Idempotent -- saving an already-saved
    meeting just returns the existing row, never creates a second one."""
    async with async_session() as session:
        meeting_page_id = (
            (
                await session.execute(
                    select(MeetingPage.id).where(MeetingPage.slug == slug)
                )
            )
            .scalars()
            .first()
        )
        if meeting_page_id is None:
            return None

        existing = (
            (
                await session.execute(
                    select(SavedItem).where(
                        SavedItem.clerk_user_id == clerk_user_id,
                        SavedItem.item_type == "saved_meeting",
                        SavedItem.meeting_page_id == meeting_page_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing:
            item = existing
        else:
            item = SavedItem(
                clerk_user_id=clerk_user_id,
                item_type="saved_meeting",
                meeting_page_id=meeting_page_id,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)

        return {
            "id": item.id,
            "item_type": item.item_type,
            "meeting_page_id": item.meeting_page_id,
        }


async def unsave_meeting(clerk_user_id: str, slug: str) -> bool:
    """True if a saved-meeting row existed and was removed; False if there
    was nothing to remove (not an error -- unsaving something already
    unsaved is a no-op, same as save_meeting's own idempotence)."""
    async with async_session() as session:
        meeting_page_id = (
            (
                await session.execute(
                    select(MeetingPage.id).where(MeetingPage.slug == slug)
                )
            )
            .scalars()
            .first()
        )
        if meeting_page_id is None:
            return False

        existing = (
            (
                await session.execute(
                    select(SavedItem).where(
                        SavedItem.clerk_user_id == clerk_user_id,
                        SavedItem.item_type == "saved_meeting",
                        SavedItem.meeting_page_id == meeting_page_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            return False
        await session.delete(existing)
        await session.commit()
        return True


async def save_search(clerk_user_id: str, search_params: dict) -> dict:
    """Saves a search to this account. Dedup is a Python-side exact-dict
    comparison against this user's existing saved searches (not a SQL
    JSON-equality query, which is dialect-fragile) -- fine at the scale
    one account's saved-search list will ever reach, same "keep it simple
    at this scale" reasoning archive/utils/search.py's own docstring
    already applies elsewhere in this file."""
    async with async_session() as session:
        existing_rows = (
            (
                await session.execute(
                    select(SavedItem).where(
                        SavedItem.clerk_user_id == clerk_user_id,
                        SavedItem.item_type == "saved_search",
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in existing_rows:
            if row.search_params == search_params:
                return {
                    "id": row.id,
                    "item_type": row.item_type,
                    "search_params": row.search_params,
                }

        # last_alerted_at starts at "now," not None -- the alert sweep
        # (archive/search_alerts.py) treats a None cursor as "alert on
        # everything ever archived," which would dump every pre-existing
        # match on this brand-new search's very first check. Only a
        # dedup-hit (the loop above) skips this -- an existing row's
        # cursor must never be reset backward by re-saving the same query.
        item = SavedItem(
            clerk_user_id=clerk_user_id,
            item_type="saved_search",
            search_params=search_params,
            last_alerted_at=datetime.now(timezone.utc),
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return {
            "id": item.id,
            "item_type": item.item_type,
            "search_params": item.search_params,
        }


async def unsave_item(clerk_user_id: str, saved_item_id: int) -> bool:
    """Removes any saved item (meeting or search) by id -- scoped to
    clerk_user_id so one account can never delete another's row even if
    it somehow guessed a valid id."""
    async with async_session() as session:
        item = await session.get(SavedItem, saved_item_id)
        if item is None or item.clerk_user_id != clerk_user_id:
            return False
        await session.delete(item)
        await session.commit()
        return True


async def unsave_item_by_id(saved_item_id: int) -> bool:
    """Like unsave_item(), but for the one caller that has no
    clerk_user_id to scope against: a click on a saved-search alert
    email's per-alert unsubscribe link (archive/main.py's
    /alerts/unsubscribe route). That click is authorized by a signed
    token (archive/utils/link_tokens.py) instead -- verified by the
    caller before this function is ever reached, so no ownership check
    is needed here."""
    async with async_session() as session:
        item = await session.get(SavedItem, saved_item_id)
        if item is None:
            return False
        await session.delete(item)
        await session.commit()
        return True


async def list_all_saved_searches() -> list[dict]:
    """Every saved_search SavedItem across every account -- the alert
    sweep's (archive/search_alerts.py) starting point. Intentionally
    unscoped by clerk_user_id (unlike every other SavedItem query in this
    file): the sweep itself iterates every user's saved searches in one
    pass, not one account's."""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(SavedItem).where(SavedItem.item_type == "saved_search")
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "clerk_user_id": r.clerk_user_id,
                "search_params": r.search_params or {},
                "last_alerted_at": r.last_alerted_at,
            }
            for r in rows
        ]


async def mark_saved_searches_alerted(
    saved_item_ids: list[int], checked_at: datetime
) -> None:
    """Advances last_alerted_at for every saved search included in a
    digest that actually sent -- called only after a real, successful
    send (archive/search_alerts.py), never speculatively, so a failed
    Resend send doesn't silently lose that match by moving the cursor
    forward anyway."""
    if not saved_item_ids:
        return
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(SavedItem).where(SavedItem.id.in_(saved_item_ids))
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.last_alerted_at = checked_at
        await session.commit()


async def list_saved_items(clerk_user_id: str) -> dict:
    """Everything saved to this account, newest first -- for GET
    /account/saved. Saved meetings are joined against MeetingPage for
    display fields (title/date/jurisdiction/slug) in the same pass, since
    the page needs those regardless."""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(SavedItem)
                    .where(SavedItem.clerk_user_id == clerk_user_id)
                    .order_by(SavedItem.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        meeting_ids = [
            r.meeting_page_id
            for r in rows
            if r.item_type == "saved_meeting" and r.meeting_page_id
        ]
        pages_by_id = {}
        if meeting_ids:
            page_rows = (
                await session.execute(
                    select(
                        MeetingPage.id,
                        MeetingPage.slug,
                        MeetingPage.title,
                        MeetingPage.date,
                        MeetingPage.jurisdiction,
                        MeetingPage.meeting_body,
                    ).where(MeetingPage.id.in_(meeting_ids))
                )
            ).all()
            pages_by_id = {
                pid: {
                    "slug": slug,
                    "title": title,
                    "date": date,
                    "jurisdiction": jurisdiction,
                    "meeting_body": meeting_body,
                }
                for pid, slug, title, date, jurisdiction, meeting_body in page_rows
            }

    meetings, searches = [], []
    for row in rows:
        if row.item_type == "saved_meeting":
            page = pages_by_id.get(row.meeting_page_id)
            if page is None:
                continue  # meeting page was deleted out from under a saved item -- skip, don't crash
            meetings.append({"id": row.id, "created_at": row.created_at, **page})
        elif row.item_type == "saved_search":
            searches.append(
                {
                    "id": row.id,
                    "created_at": row.created_at,
                    "search_params": row.search_params or {},
                }
            )

    return {"meetings": meetings, "searches": searches}


async def delete_account_data(clerk_user_id: str) -> int:
    """Hard-deletes every SavedItem for this Clerk account -- the entire
    right-to-deletion story on our side of the app.main.py user.deleted
    webhook handler, since this table stores no other PII to clean up.
    Returns the number of rows removed (for the webhook handler's own
    logging, not load-bearing)."""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(SavedItem).where(SavedItem.clerk_user_id == clerk_user_id)
                )
            )
            .scalars()
            .all()
        )
        count = len(rows)
        for row in rows:
            await session.delete(row)
        await session.commit()
        return count


async def delete_meeting_pages_by_slug(slugs: list[str], *, dry_run: bool) -> dict:
    """Permanently removes one or more MeetingPage rows by slug, plus every
    row that references them (TranscriptionJob, TranscriptVersion,
    MeetingPageUrlAlias, SavedItem) -- there's no DB-level ON DELETE CASCADE
    on any of those foreign keys, so a plain `session.delete(page)` would
    fail with a real FK violation, not silently cascade. TranscriptionJob is
    deleted before TranscriptVersion since a job can reference a version via
    `transcript_version_id`.

    Built for one specific real cleanup (3 PrimeGov UAT/staging tenant
    pages accidentally real-ingested during a bulk gate-blindness recheck,
    see BACKLOG_DONE.md), not a general content-moderation tool -- slug is
    required (not a fuzzy match) so a typo can't take out an unrelated real
    page. `dry_run=True` (the default, matching this file's existing
    read-only-first convention -- see backfill_apply's docstring) reports
    exactly what would be deleted without touching anything.

    Returns {"dry_run": bool, "found": [...], "not_found": [...], "deleted": int}.
    """
    async with async_session() as session:
        found: list[dict] = []
        not_found: list[str] = []
        for slug in slugs:
            page = (
                await session.execute(
                    select(MeetingPage).where(MeetingPage.slug == slug)
                )
            ).scalar_one_or_none()
            if page is None:
                not_found.append(slug)
                continue
            found.append(
                {
                    "slug": page.slug,
                    "title": page.title,
                    "platform": page.platform,
                    "source_url_normalized": page.source_url_normalized,
                }
            )
            if dry_run:
                continue

            jobs = (
                (
                    await session.execute(
                        select(TranscriptionJob).where(
                            TranscriptionJob.meeting_page_id == page.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for job in jobs:
                await session.delete(job)

            versions = (
                (
                    await session.execute(
                        select(TranscriptVersion).where(
                            TranscriptVersion.meeting_page_id == page.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for version in versions:
                await session.delete(version)

            aliases = (
                (
                    await session.execute(
                        select(MeetingPageUrlAlias).where(
                            MeetingPageUrlAlias.meeting_page_id == page.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for alias in aliases:
                await session.delete(alias)

            saved = (
                (
                    await session.execute(
                        select(SavedItem).where(SavedItem.meeting_page_id == page.id)
                    )
                )
                .scalars()
                .all()
            )
            for item in saved:
                await session.delete(item)

            await session.delete(page)

        if not dry_run:
            await session.commit()

        return {
            "dry_run": dry_run,
            "found": found,
            "not_found": not_found,
            "deleted": 0 if dry_run else len(found),
        }


# --- Meeting card frames (WO-28) ----------------------------------------

_THUMBNAILS_CHECK_TTL = timedelta(minutes=1)
_thumbnails_state: dict[str, Any] = {"available": False, "checked_at": None}


async def _thumbnails_available(session) -> bool:
    """True when the meeting_page_thumbnails table really exists on the
    connected database.

    Exactly the discipline _best_effort_available() applies to a column,
    applied to a table: on SQLite (dev/CI) create_all() builds it from
    today's model so it is always present, while on Postgres the schema is
    migration-driven and can genuinely lag the code. render.yaml's
    preDeployCommand normally closes that window before the new build
    serves, but "normally" is not a guarantee worth a 500 on a public
    page -- and this is the pattern CLAUDE.md's migration bullet asks for
    (code and migration deployable in either order). Cached for
    _THUMBNAILS_CHECK_TTL so running the migration against a live service
    flips this on within a minute with no restart.
    """
    if session.bind.dialect.name != "postgresql":
        return True
    now = datetime.now(timezone.utc)
    checked_at = _thumbnails_state["checked_at"]
    if checked_at is not None and now - checked_at < _THUMBNAILS_CHECK_TTL:
        return bool(_thumbnails_state["available"])
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'meeting_page_thumbnails'"
            )
        )
    ).first()
    _thumbnails_state["available"] = row is not None
    _thumbnails_state["checked_at"] = now
    return bool(_thumbnails_state["available"])


async def get_page_card_target(slug: str) -> Optional[dict]:
    """The bare minimum GET /m/{slug}/card.jpg needs about a page: its id
    and the three fields an extraction takes. Deliberately NOT
    get_page_by_slug(), which also loads every TranscriptVersion's full
    segments blob -- an image route hit by crawlers has no business
    pulling a meeting's entire transcript into memory to decide which
    frame to serve."""
    async with async_session() as session:
        row = (
            await session.execute(
                select(
                    MeetingPage.id,
                    MeetingPage.video_url,
                    MeetingPage.video_format,
                    MeetingPage.source_url_normalized,
                ).where(MeetingPage.slug == slug)
            )
        ).first()
        if row is None:
            return None
        return {
            "id": row[0],
            "video_url": row[1],
            "video_format": row[2],
            "source_url": row[3],
        }


async def get_thumbnail_meta(
    page_id: int, *, offset_seconds: Optional[int] = None
) -> Optional[dict]:
    """Everything about a stored card frame EXCEPT its bytes -- id,
    offset, etag, content type, size. `offset_seconds=None` asks for the
    page's default frame. Separate from get_thumbnail_bytes() so a
    conditional GET (If-None-Match) can be answered with a 304 without
    ever loading the image.
    """
    async with async_session() as session:
        if not await _thumbnails_available(session):
            return None
        stmt = select(
            MeetingPageThumbnail.id,
            MeetingPageThumbnail.offset_seconds,
            MeetingPageThumbnail.etag,
            MeetingPageThumbnail.content_type,
            MeetingPageThumbnail.byte_size,
        ).where(MeetingPageThumbnail.meeting_page_id == page_id)
        if offset_seconds is None:
            stmt = stmt.where(MeetingPageThumbnail.is_default.is_(True))
        else:
            stmt = stmt.where(MeetingPageThumbnail.offset_seconds == offset_seconds)
        row = (await session.execute(stmt.limit(1))).first()
        if row is None:
            return None
        return {
            "id": row[0],
            "offset_seconds": row[1],
            "etag": row[2],
            "content_type": row[3],
            "byte_size": row[4],
        }


async def get_thumbnail_bytes(thumbnail_id: int) -> Optional[bytes]:
    async with async_session() as session:
        if not await _thumbnails_available(session):
            return None
        row = (
            await session.execute(
                select(MeetingPageThumbnail.image_bytes).where(
                    MeetingPageThumbnail.id == thumbnail_id
                )
            )
        ).first()
        return row[0] if row else None


async def record_search_query(
    keyword: str, jurisdiction: Optional[str], result_count: int
) -> None:
    """Append one row to `search_queries`. Identity-free by design (see
    models.SearchQuery) and non-fatal by design: it runs as a FastAPI
    background task after the response is already on its way, so an
    exception here can only cost a log line, never a search.
    """
    try:
        async with async_session() as session:
            session.add(
                SearchQuery(
                    keyword=keyword,
                    jurisdiction=jurisdiction,
                    result_count=result_count,
                )
            )
            await session.commit()
    except Exception:  # pragma: no cover - defensive, see docstring
        logging.getLogger(__name__).exception("failed to record search query")


async def top_search_keywords(days: int = 30, limit: int = 20) -> list[tuple[str, int]]:
    """Most-typed keywords over the window, most-frequent first.

    Nothing renders this yet -- it is the read side of SearchQuery, here
    so the next round of topic-chip work has real demand data to rank
    against rather than needing to add both the write and the read at
    once. Deliberately lower-cased and grouped, since "Flock" and "flock"
    are the same question.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    func.lower(SearchQuery.keyword).label("kw"),
                    func.count().label("n"),
                )
                .where(SearchQuery.created_at >= since)
                .group_by(func.lower(SearchQuery.keyword))
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
    return [(row[0], row[1]) for row in rows]


async def pages_with_thumbnails(session, page_ids: Sequence[int]) -> set[int]:
    """The subset of `page_ids` that already have a stored frame -- the
    bulk form of has_thumbnail(), for the state/hub pages that feature a
    dozen meetings at once and would otherwise issue a dozen queries.

    Same "never advertise a card URL that would 404" rule as
    has_thumbnail(): callers use this to decide whether to emit an
    <img> and a VideoObject.thumbnailUrl at all. Unlike /m/{slug}, a
    missing frame here does *not* queue a warm -- a hub listing twelve
    meetings would fire twelve ffmpeg jobs per crawl, and each of those
    pages warms itself when it is actually visited."""
    if not page_ids or not await _thumbnails_available(session):
        return set()
    rows = (
        await session.execute(
            select(MeetingPageThumbnail.meeting_page_id).where(
                MeetingPageThumbnail.meeting_page_id.in_(list(page_ids))
            )
        )
    ).all()
    return {row[0] for row in rows}


async def has_thumbnail(page_id: int) -> bool:
    """Whether this page has ANY stored frame yet -- what /m/{slug} checks
    before advertising an og:image at all. Emitting a card URL that would
    404 is worse than emitting none: Google's validator and every social
    scraper would fetch it, and a broken og:image is its own flag."""
    async with async_session() as session:
        if not await _thumbnails_available(session):
            return False
        row = (
            await session.execute(
                select(MeetingPageThumbnail.id)
                .where(MeetingPageThumbnail.meeting_page_id == page_id)
                .limit(1)
            )
        ).first()
        return row is not None


async def count_thumbnails(page_id: int) -> int:
    async with async_session() as session:
        if not await _thumbnails_available(session):
            return 0
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(MeetingPageThumbnail)
                    .where(MeetingPageThumbnail.meeting_page_id == page_id)
                )
            ).scalar_one()
        )


async def store_thumbnail(
    page_id: int,
    *,
    offset_seconds: int,
    image_bytes: bytes,
    etag: str,
    is_default: bool,
) -> bool:
    """Insert one extracted frame. Returns False (never raises) when the
    table isn't there yet, when the page already has MAX_FRAMES_PER_PAGE
    frames, or when a concurrent writer got there first -- all normal
    outcomes for a best-effort background warm.

    A page has at most one is_default row, same invariant
    TranscriptVersion.is_default keeps: storing a new default clears the
    old one rather than adding a second.
    """
    from ..utils.video_thumbnail import MAX_FRAMES_PER_PAGE

    async with async_session() as session:
        if not await _thumbnails_available(session):
            return False
        existing = (
            await session.execute(
                select(MeetingPageThumbnail).where(
                    MeetingPageThumbnail.meeting_page_id == page_id,
                    MeetingPageThumbnail.offset_seconds == offset_seconds,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(MeetingPageThumbnail)
                    .where(MeetingPageThumbnail.meeting_page_id == page_id)
                )
            ).scalar_one()
        )
        if count >= MAX_FRAMES_PER_PAGE:
            return False
        if is_default:
            for row in (
                (
                    await session.execute(
                        select(MeetingPageThumbnail).where(
                            MeetingPageThumbnail.meeting_page_id == page_id,
                            MeetingPageThumbnail.is_default.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            ):
                row.is_default = False
        session.add(
            MeetingPageThumbnail(
                meeting_page_id=page_id,
                offset_seconds=offset_seconds,
                is_default=is_default,
                image_bytes=image_bytes,
                content_type="image/jpeg",
                etag=etag,
                byte_size=len(image_bytes),
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # Two background warms raced on the same (page, offset). The
            # unique constraint is the arbiter; the loser just stops.
            await session.rollback()
            return False
        return True


async def list_pages_missing_default_thumbnail(
    limit: int = 25, offset: int = 0, slugs: Optional[Sequence[str]] = None
) -> list[dict]:
    """Pages with a real, extractable video and no default frame stored
    yet -- the work queue for POST /internal/thumbnails/backfill.

    Newest first, because a page that was archived recently is the one
    most likely to be shared or crawled next. Every iframe-embed platform
    (IFRAME_EMBED_VIDEO_FORMATS: youtube, vimeo, viebit) is excluded in
    SQL rather than fetched and filtered in Python -- their `video_url`
    is a player *page*, not media, so ffmpeg can only ever fail on them.
    Was YouTube-only until 2026-08-22, which meant vimeo and viebit rows
    were handed to the sweep and produced failures that could never
    succeed; mirrors video_thumbnail.is_extractable(), and both now read
    the same constant.

    Two ways to select rows, and the *filter* above always applies to
    both -- a page that already has a default frame is never returned,
    however it was asked for:

    * `limit`/`offset` page through the queue newest-first. `offset`
      exists because a page whose extraction *fails* never gets a
      default frame, so it stays in this result set forever, and since a
      sweep works newest-to-oldest those failures pile up as a
      contiguous prefix; without a way to page past them a caller with a
      fixed `limit` stalls the moment they fill a whole window.
    * `slugs` names exact pages instead, ignoring `limit`/`offset`. That
      is what lets a caller choose the *order* work happens in rather
      than accepting newest-first -- specifically, to interleave across
      media hosts and rate-limit one CDN independently of the others
      (see scripts/backfill_meeting_cards.py, and BACKLOG.md's Granicus
      timeout entries for why that host in particular needs it).
    """
    if slugs is not None and not slugs:
        return []
    async with async_session() as session:
        if not await _thumbnails_available(session):
            return []
        has_default = (
            select(MeetingPageThumbnail.id)
            .where(
                MeetingPageThumbnail.meeting_page_id == MeetingPage.id,
                MeetingPageThumbnail.is_default.is_(True),
            )
            .exists()
        )
        stmt = select(
            MeetingPage.id,
            MeetingPage.slug,
            MeetingPage.video_url,
            MeetingPage.video_format,
            MeetingPage.source_url_normalized,
        ).where(
            MeetingPage.video_url.isnot(None),
            MeetingPage.video_url != "",
            or_(
                MeetingPage.video_format.is_(None),
                # Not just "youtube": vimeo and viebit also store an
                # iframe embed *page* as video_url, so selecting them
                # here pointed ffmpeg at HTML and produced failures that
                # could never succeed -- polluting the sweep's failure
                # set. Mirrors video_thumbnail.is_extractable(); both now
                # read the same constant.
                MeetingPage.video_format.notin_(sorted(IFRAME_EMBED_VIDEO_FORMATS)),
            ),
            ~has_default,
        )
        if slugs is not None:
            stmt = stmt.where(MeetingPage.slug.in_(list(slugs)))
        else:
            # id.desc() is a tiebreaker, not decoration: a bulk ingest
            # gives many rows the same created_at, and without it the
            # offset window above is not stable between calls.
            stmt = (
                stmt.order_by(MeetingPage.created_at.desc(), MeetingPage.id.desc())
                .limit(limit)
                .offset(max(0, offset))
            )
        rows = (await session.execute(stmt)).all()
        return [
            {
                "id": r[0],
                "slug": r[1],
                "video_url": r[2],
                "video_format": r[3],
                "source_url": r[4],
            }
            for r in rows
        ]
