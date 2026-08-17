import hashlib
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.orm import aliased

from app.utils.jurisdiction_enrich import finalize_jurisdiction

from ..utils.date_status import meeting_date_status
from ..utils.jurisdiction_format import (
    US_STATE_ABBR_TO_NAME,
    jurisdiction_search_terms,
    normalize_state_suffix,
    state_abbr_from_jurisdiction,
    state_slug_from_abbr,
)
from ..utils.language import detect_language_from_texts
from ..utils.search import (
    compute_search_corpus,
    find_snippet,
    matches,
    parse_query,
    tokenize,
)
from ..utils.slugify import build_base_slug, random_suffix
from ..utils.transcription_quality import detect_hallucination_warnings
from ..utils.url_normalize import normalize_url
from .engine import async_session
from .models import (
    MeetingPage,
    MeetingPageUrlAlias,
    SavedItem,
    TranscriptionJob,
    TranscriptVersion,
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


def _has_real_warning_free_transcript(warnings: Optional[list]) -> bool:
    """True if none of `warnings` mark this version as garbled-at-source or
    likely-hallucinated -- the shared "is this actually a good transcript"
    check every call site below needs, factored out so a third quality
    marker never again needs updating in four separate places."""
    return not any(
        _GARBLED_MARKER in w or _HALLUCINATION_MARKER in w for w in (warnings or [])
    )


async def _has_good_transcript(session, meeting_page_id: int) -> bool:
    """True if this page's default TranscriptVersion has real, non-garbled
    content -- used to pick the Archive recheck cadence (see
    ARCHIVE_RECHECK_AFTER's has_transcript branch in app/main.py): a page
    missing a real transcript benefits from being rechecked often, since
    the government source's own captions may catch up at any time; a page
    that already has a good one doesn't."""
    version = (
        (
            await session.execute(
                select(TranscriptVersion).where(
                    and_(
                        TranscriptVersion.meeting_page_id == meeting_page_id,
                        TranscriptVersion.is_default.is_(True),
                    )
                )
            )
        )
        .scalars()
        .first()
    )
    if version is None or not version.segments:
        return False
    return _has_real_warning_free_transcript(version.transcript_warnings)


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
) -> MeetingPage:
    """Shared by ingest_resolution() and create_transcription_job() -- both
    need "find this meeting's permanent page, or create one if this is the
    first thing that's ever landed for it" from the same resolver-payload
    shape. Extracted 2026-08-08 when the transcription feature needed the
    exact same logic ingest_resolution() already had inline.
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
            meeting_body=jx_result.meeting_body,
            jurisdiction_confidence=jx_result.confidence,
            video_url=payload.get("video_url"),
            video_format=payload.get("video_format"),
            agenda_items=payload.get("agenda_items") or [],
            video_warnings=payload.get("video_warnings") or [],
            agenda_link=payload.get("agenda_link"),
        )
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
    return page


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


async def ingest_resolution(payload: dict[str, Any], input_url_normalized: str) -> dict:
    """Create a MeetingPage (or attach a new TranscriptVersion to an
    existing one) from a resolver push. `payload` is the resolver's
    ResolvedMeeting.model_dump() shape: platform, source_url, external_id,
    title, date, jurisdiction, video_url, video_format, segments,
    agenda_items, transcript_language, transcript_warnings. `source` is an
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
        page = await _find_or_create_page(session, payload, input_url_normalized)

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
        return {
            "slug": page.slug,
            "url": f"/m/{page.slug}",
            "version_id": matched_version_id,
        }


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


async def list_hallucination_candidate_transcript_versions() -> list[dict]:
    """Retroactive audit, same role as list_completed_multichunk_transcription_
    jobs() above plays for the seam-duplication bug: re-runs
    detect_hallucination_warnings() (archive/utils/transcription_quality.py --
    the same function report_chunk_result() now calls at finalize time, and
    scripts/transcribe_backlog_locally.py's transcribe_meeting() calls
    directly) against the *stored* segments of every already-completed
    source=="transcribed" TranscriptVersion, to find which ones would trip
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
    """
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
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
                .join(MeetingPage, MeetingPage.id == TranscriptVersion.meeting_page_id)
                .outerjoin(
                    TranscriptionJob,
                    TranscriptionJob.transcript_version_id == TranscriptVersion.id,
                )
                .where(TranscriptVersion.source == "transcribed")
                .order_by(TranscriptVersion.id.asc())
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
        ) in rows:
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

        return candidates


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

    Fuzzy words are the one thing SQL can't decide: matches()'s bounded
    Levenshtein against real corpus words has no recall-safe SQL
    equivalent -- pg_trgm's word_similarity() over a multi-hundred-KB
    document is either too loose to narrow anything (at the recall-safe
    0.15 threshold the earlier version used) or drops genuine 2-edit
    typos (anything selective), and costs tens of ms of server CPU per
    row either way. So fuzzy words are returned for the caller to check
    in Python over the corpus text -- streamed one row at a time (see
    list_pages()), never the transcript JSON. The real fix for fuzzy is a
    trigram-indexed vocabulary table (BACKLOG.md's search entry, "Step
    2b"); until then fuzzy stays the opt-in, UI-labeled "slower" mode.
    """
    phrases, words, excluded_phrases, excluded_words = parse_query(keyword)
    conditions = [_corpus_contains(p) for p in phrases]
    conditions += [~_corpus_contains(p) for p in excluded_phrases]
    conditions += [~_corpus_contains(w) for w in excluded_words]
    if fuzzy:
        return conditions, list(words)
    conditions += [_corpus_contains(w) for w in words]
    return conditions, []


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
) -> dict:
    """Paginated meeting list behind /meetings (and the saved-search alert
    sweep, via find_new_matches_for_saved_search()).

    Every filter is applied in SQL -- jurisdiction (via
    jurisdiction_search_terms()'s state-name expansion), date range,
    created_after, has_transcript, has_agenda (_has_agenda_condition()),
    and exact-mode keyword search (_keyword_conditions() against the
    materialized `MeetingPage.search_corpus`, GIN-trigram-indexed on
    Postgres). Pagination is LIMIT/OFFSET plus one COUNT(*), so a plain
    browse or an exact search costs O(page_size) memory no matter how many
    meetings match -- the 2026-08-17 rewrite, after the previous shape
    (SQL pre-filter, then load every candidate's full transcript JSON for
    a Python re-check, then paginate in Python) OOM-crashed the Archive on
    common terms and took 25-35s when it survived. See BACKLOG_DONE.md.

    Fuzzy mode is the one exception: unquoted words are matched in Python
    by matches()'s bounded Levenshtein against each candidate's
    `search_corpus` *text* (not transcript JSON), streamed one row at a
    time so memory stays bounded, and paginated in Python. Phrases and
    exclusions still narrow in SQL first. Measured ~5ms/doc CPU, so a few
    seconds across the whole archive -- slow but no longer a crash; the
    UI already labels fuzzy "slower". Why SQL can't do this: see
    _keyword_conditions().

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
    fuzzy_words: list[str] = []
    if keyword:
        keyword_conditions, fuzzy_words = _keyword_conditions(keyword, fuzzy)
        conditions.extend(keyword_conditions)

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
    if fuzzy_words:
        columns.append(MeetingPage.search_corpus)
    stmt = (
        select(*columns)
        .outerjoin(TranscriptVersion, default_version)
        .order_by(MeetingPage.created_at.desc(), MeetingPage.id.desc())
    )
    if conditions:
        stmt = stmt.where(and_(*conditions))

    async with async_session() as session:
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


# Platforms that host video directly (or, for Viebit/Cablecast, are
# reached by delegation but ARE the real host) -- ordered to match
# README.md's "Supported platforms" table. Deliberately excludes
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
}

# YouTube is deliberately never its own /coverage row -- a viewer already
# gets a good deep-linkable transcript straight from YouTube itself for
# a directly-pasted YouTube URL, so this page steers people toward
# pasting the government page that embeds/links it instead (a Granicus/
# Swagit/etc. page, or one of the CUSTOM_PLATFORMS above) wherever one
# exists. See coverage.html's own footer note.
_YOUTUBE_DELEGATING_CUSTOM_PLATFORMS = frozenset({"lims", "slc", "clerkbase"})

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
    detect_platform() -- just enough to recognize the three YouTube-
    delegating custom scrapers (see CUSTOM_PLATFORMS above) from a page's
    own source_url_normalized. archive/ deliberately doesn't import from
    app/ (see README's project structure notes on this directory's other
    deliberately-duplicated utils, e.g. url_normalize.py/language.py) --
    this stays scoped to exactly the three cases get_platform_coverage()
    needs, not a general URL classifier.
    """
    netloc = urlparse(source_url_normalized).netloc.lower()
    path = urlparse(source_url_normalized).path.lower()
    if "lims.minneapolismn.gov" in netloc:
        return "lims"
    if netloc.endswith("slc.gov") and "-meeting-recap" in path:
        return "slc"
    if "clerkshq.com" in netloc:
        return "clerkbase"
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
            if entry in _YOUTUBE_DELEGATING_CUSTOM_PLATFORMS:
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


async def get_state_coverage_index() -> list[dict]:
    """One row per US state with >= 1 indexable archived meeting, for the
    /state/{slug} landing pages: /coverage's "Browse by state" section and
    sitemap.xml's per-state entries. Excludes platform == "unknown"
    (generic_fallback) pages -- state pages are an indexable SEO surface
    and carry the same trust posture as the sitemap (see
    list_all_page_slugs() below). Jurisdictions without a recognized
    ", ST" suffix (school districts, state agencies, non-US) simply don't
    group into any state -- a documented limitation, not a bug.
    Sorted by state name."""
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
            "jurisdiction_count": len(entry["jurisdictions"]),
            "page_count": entry["page_count"],
            "last_updated": entry["last_updated"],
        }
        for abbr, entry in by_state.items()
    ]
    result.sort(key=lambda s: s["name"])
    return result


async def get_state_page_data(abbr: str) -> Optional[dict]:
    """Everything /state/{slug} renders, or None when the state has no
    indexable pages (the route 404s). Anchored suffix match on the stored
    jurisdiction -- normalize_state_suffix() guarantees the canonical
    ", CA" form at write time, so LIKE '%, CA' can't false-positive the
    way list_pages()'s substring ilike would ("Decatur, GA" contains
    "ca"). Same platform != "unknown" exclusion and default-version
    transcript-badge join as get_jurisdiction_coverage() above."""
    async with async_session() as session:
        stmt = (
            select(
                MeetingPage.jurisdiction,
                MeetingPage.slug,
                MeetingPage.title,
                MeetingPage.date,
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
    for jurisdiction, slug, title, date, version_id, warnings in rows:
        # LIKE is case-insensitive on SQLite (dev/tests), so re-check the
        # suffix exactly -- keeps dev and prod (case-sensitive Postgres
        # LIKE) behaving identically.
        if state_abbr_from_jurisdiction(jurisdiction) != abbr:
            continue
        has_transcript = version_id is not None and _has_real_warning_free_transcript(
            warnings
        )
        pages.append(
            {
                "jurisdiction": jurisdiction,
                "slug": slug,
                "title": title,
                "date": date,
                "has_transcript": has_transcript,
            }
        )
    if not pages:
        return None

    by_jurisdiction: dict[str, list[dict]] = {}
    for p in pages:
        by_jurisdiction.setdefault(p["jurisdiction"], []).append(p)
    jurisdictions = []
    for jurisdiction in sorted(by_jurisdiction, key=str.casefold):
        examples = by_jurisdiction[jurisdiction]
        example = next((e for e in examples if e["has_transcript"]), examples[0])
        jurisdictions.append(
            {
                "jurisdiction": jurisdiction,
                "example": example,
                "page_count": len(examples),
            }
        )

    recent_pages = sorted(pages, key=lambda p: p["date"] or "", reverse=True)[:25]
    return {
        "abbr": abbr,
        "name": US_STATE_ABBR_TO_NAME[abbr],
        "jurisdictions": jurisdictions,
        "recent_pages": recent_pages,
        "total_pages": len(pages),
        "jurisdiction_count": len(jurisdictions),
    }


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
# single chunk should ever legitimately take with the "tiny" model, and
# the only real instance of this repo's single worker process, so there's
# no concurrent-worker race this protects against, just crash detection.
STALE_CLAIM_AFTER = timedelta(minutes=5)
MAX_CONSECUTIVE_CHUNK_FAILURES = 3

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
    *, slug: str, version_id: int
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
        await session.commit()
        return {"slug": slug, "promoted_version_id": version_id}


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
        page = await _find_or_create_page(session, payload, input_url_normalized)

        not_expired_pending = or_(
            TranscriptionJob.status.in_(SPENDING_JOB_STATUSES),
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


async def _in_auto_transcription_cooldown(session, meeting_page_id: int) -> bool:
    """True if this page has failed auto/manual transcription recently
    enough that it shouldn't be tried again yet -- see
    AUTO_TRANSCRIPTION_BASE_COOLDOWN's docstring for the escalating-backoff
    reasoning. Counts *consecutive* failures walking back from the most
    recent job, stopping at the first non-"failed" one (a "completed" job
    means this page already has what it needs; an older failure before a
    completed one is stale history, not part of the current streak)."""
    jobs = (
        (
            await session.execute(
                select(TranscriptionJob)
                .where(TranscriptionJob.meeting_page_id == meeting_page_id)
                .order_by(TranscriptionJob.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    consecutive_failures = 0
    most_recent_failed_at = None
    for job in jobs:
        if job.status != "failed":
            break
        consecutive_failures += 1
        if most_recent_failed_at is None:
            most_recent_failed_at = job.updated_at

    if consecutive_failures == 0:
        return False

    cooldown = min(
        AUTO_TRANSCRIPTION_BASE_COOLDOWN * (2 ** (consecutive_failures - 1)),
        AUTO_TRANSCRIPTION_MAX_COOLDOWN,
    )
    return datetime.now(timezone.utc) < _aware(most_recent_failed_at) + cooldown


async def find_auto_transcription_candidate() -> Optional[dict]:
    """Oldest-archived-first MeetingPage missing a good transcript and not
    in escalating-failure cooldown, for worker/main.py's idle-time
    auto-generation. Caller is responsible for confirming the job queue is
    completely empty before calling this -- this function only picks a
    candidate, it doesn't check that itself.

    Full Python-side scan over every page, deliberately -- fine at today's
    scale (dozens of meetings) and only ever called at most once every
    AUTO_GENERATION_CHECK_INTERVAL_SECONDS (see worker/main.py), same
    "acceptable now, revisit at real scale" reasoning as /meetings' own
    search scan (BACKLOG.md's materialized-search-column entry).
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

        for page in pages:
            if await _has_good_transcript(session, page.id):
                continue
            if await _in_auto_transcription_cooldown(session, page.id):
                continue
            return {
                "meeting_page_id": page.id,
                "slug": page.slug,
                "source_url": page.source_url_normalized,
                "platform": page.platform,
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
    (STALE_CLAIM_AFTER) exists for a crashed/restarted worker process, not
    a multi-worker race -- only one worker process is planned (see the
    plan this was built from), so this is a safety net, not load-bearing
    concurrency control. Returns everything the worker needs to process
    one chunk, or None if nothing's claimable right now.
    """
    now = datetime.now(timezone.utc)
    stale_before = now - STALE_CLAIM_AFTER

    async with async_session() as session:
        job = (
            (
                await session.execute(
                    select(TranscriptionJob)
                    .where(
                        TranscriptionJob.status.in_(("queued", "in_progress")),
                        (TranscriptionJob.claimed_at.is_(None))
                        | (TranscriptionJob.claimed_at < stale_before),
                    )
                    .order_by(
                        TranscriptionJob.priority.desc(),
                        TranscriptionJob.created_at.asc(),
                    )
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if job is None:
            return None

        job.status = "in_progress"
        job.claimed_at = now
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
) -> dict:
    """Called by the worker after attempting one chunk. On success, appends
    already-offset segments and advances progress; if that was the last
    chunk, finalizes the job (writes the TranscriptVersion, promotes it,
    caller -- archive/main.py -- sends the completion email afterward using
    this function's returned `completed`/`transcript_version_id`). On
    failure, counts toward MAX_CONSECUTIVE_CHUNK_FAILURES before giving up
    on the whole job -- a single flaky chunk (transient network blip)
    shouldn't fail an otherwise-fine multi-hour job.

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
            if job.consecutive_chunk_failures >= MAX_CONSECUTIVE_CHUNK_FAILURES:
                job.status = "failed"
            await session.commit()
            return {
                "status": job.status,
                "consecutive_chunk_failures": job.consecutive_chunk_failures,
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
