import hashlib
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select

from app.utils.jurisdiction_enrich import finalize_jurisdiction

from ..utils.jurisdiction_format import jurisdiction_search_terms, normalize_state_suffix
from ..utils.language import detect_language_from_texts
from ..utils.search import build_corpus, find_snippet, matches, tokenize
from ..utils.slugify import build_base_slug, random_suffix
from ..utils.url_normalize import normalize_url
from .engine import async_session
from .models import MeetingPage, MeetingPageUrlAlias, SavedItem, TranscriptionJob, TranscriptVersion


def _content_hash(segments: list) -> str:
    joined = "\n".join(seg.get("text", "") for seg in segments)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# Substring shared with app/db/outcomes.py's _GARBLED_MARKER -- keep them
# matching if either message ever changes (see CLAUDE.md's note on that
# file about why this isn't accidental duplication).
_GARBLED_MARKER = "looks garbled at the source"


async def _has_good_transcript(session, meeting_page_id: int) -> bool:
    """True if this page's default TranscriptVersion has real, non-garbled
    content -- used to pick the Archive recheck cadence (see
    ARCHIVE_RECHECK_AFTER's has_transcript branch in app/main.py): a page
    missing a real transcript benefits from being rechecked often, since
    the government source's own captions may catch up at any time; a page
    that already has a good one doesn't."""
    version = (
        await session.execute(
            select(TranscriptVersion).where(
                and_(
                    TranscriptVersion.meeting_page_id == meeting_page_id,
                    TranscriptVersion.is_default.is_(True),
                )
            )
        )
    ).scalars().first()
    if version is None or not version.segments:
        return False
    return not any(_GARBLED_MARKER in w for w in (version.transcript_warnings or []))


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
            await session.execute(
                select(MeetingPageUrlAlias).where(MeetingPageUrlAlias.url_normalized == url_normalized)
            )
        ).scalars().first()
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
            await session.execute(
                select(MeetingPage).where(MeetingPage.source_url_normalized == url_normalized)
            )
        ).scalars().first()
        if page:
            return {
                "slug": page.slug,
                "url": f"/m/{page.slug}",
                "updated_at": page.updated_at.isoformat(),
                "has_transcript": await _has_good_transcript(session, page.id),
            }

    return None


async def _find_existing_page(session, *, platform: str, external_id: Optional[str], source_url_normalized: str, input_url_normalized: str) -> Optional[MeetingPage]:
    alias = (
        await session.execute(
            select(MeetingPageUrlAlias).where(MeetingPageUrlAlias.url_normalized == input_url_normalized)
        )
    ).scalars().first()
    if alias:
        page = await session.get(MeetingPage, alias.meeting_page_id)
        if page:
            return page

    if external_id:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.platform == platform, MeetingPage.external_id == external_id)
            )
        ).scalars().first()
        if page:
            return page

    return (
        await session.execute(
            select(MeetingPage).where(MeetingPage.source_url_normalized == source_url_normalized)
        )
    ).scalars().first()


async def _ensure_alias(session, url_normalized: str, meeting_page_id: int) -> None:
    existing = (
        await session.execute(
            select(MeetingPageUrlAlias).where(MeetingPageUrlAlias.url_normalized == url_normalized)
        )
    ).scalars().first()
    if not existing:
        session.add(MeetingPageUrlAlias(url_normalized=url_normalized, meeting_page_id=meeting_page_id))


async def _unique_slug(session, base: str) -> str:
    slug = base
    for _ in range(5):
        existing = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        if not existing:
            return slug
        slug = f"{base}-{random_suffix()}"
    # Exhausted retries (astronomically unlikely) -- fall back to a longer
    # random suffix rather than looping forever.
    return f"{base}-{random_suffix(12)}"


async def _find_or_create_page(session, payload: dict[str, Any], input_url_normalized: str) -> MeetingPage:
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
    jx_result = finalize_jurisdiction(jurisdiction, netloc=urlparse(source_url_normalized).netloc)
    jurisdiction = jx_result.jurisdiction

    page = await _find_existing_page(
        session,
        platform=platform,
        external_id=external_id,
        source_url_normalized=source_url_normalized,
        input_url_normalized=input_url_normalized,
    )

    if page is None:
        base_slug = build_base_slug(jurisdiction or "", payload.get("date") or "", payload.get("title") or "")
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


def _is_real_improvement(current_default: TranscriptVersion, new_language: Optional[str]) -> bool:
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


def _default_looks_like_copied_agenda(current_default: TranscriptVersion, agenda_items: list) -> bool:
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
            await session.execute(
                select(TranscriptVersion).where(
                    TranscriptVersion.meeting_page_id == page.id,
                    TranscriptVersion.is_default.is_(True),
                )
            )
        ).scalars().first()

        new_version_id = None

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
                await session.execute(
                    select(TranscriptVersion).where(
                        TranscriptVersion.meeting_page_id == page.id,
                        TranscriptVersion.language == language,
                        TranscriptVersion.source == source,
                        TranscriptVersion.content_hash == content_hash,
                    )
                )
            ).scalars().first()

            if duplicate is None:
                any_version = (
                    await session.execute(
                        select(TranscriptVersion).where(TranscriptVersion.meeting_page_id == page.id)
                    )
                ).scalars().first()
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

        if current_default is not None:
            if new_version_id is not None and _is_real_improvement(current_default, payload.get("transcript_language")):
                await promote_transcript_version(session, page.id, new_version_id)
            elif new_version_id is None and _default_looks_like_copied_agenda(current_default, agenda_items):
                current_default.is_default = False

        await session.commit()
        return {"slug": page.slug, "url": f"/m/{page.slug}"}


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
            await session.execute(select(MeetingPage).order_by(MeetingPage.created_at.asc()))
        ).scalars().all()

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
    """Every archived YouTube-backed meeting page with no default
    transcript -- the "transcript wanted" queue consumed by
    scripts/fetch_youtube_transcripts.py. YouTube-only because that's the
    one platform whose captions this service structurally can't fetch
    itself: confirmed live 2026-08-10 that even youtube-transcript-api
    (a different endpoint/recipe from the already-blocked yt-dlp and
    timedtext paths) gets IpBlocked from Render's cloud IP while working
    fine from a residential one, so fetching happens off-server and gets
    pushed back through the normal /internal/ingest path.

    "Missing" means no is_default=True TranscriptVersion, not merely zero
    version rows -- a page whose only version was demoted for being a
    copied agenda (_default_looks_like_copied_agenda) genuinely shows "no
    transcript" and should be re-fetchable too.

    Returns exactly the identity fields a push needs for
    _find_or_create_page() to match the existing page rather than
    creating a duplicate: platform, external_id, source_url_normalized.
    """
    async with async_session() as session:
        default_exists = (
            select(TranscriptVersion.id)
            .where(
                TranscriptVersion.meeting_page_id == MeetingPage.id,
                TranscriptVersion.is_default.is_(True),
            )
            .exists()
        )
        pages = (
            await session.execute(
                select(MeetingPage)
                .where(MeetingPage.video_format == "youtube", ~default_exists)
                .order_by(MeetingPage.created_at.asc())
            )
        ).scalars().all()

        return [
            {
                "slug": page.slug,
                "title": page.title,
                "platform": page.platform,
                "external_id": page.external_id,
                "source_url_normalized": page.source_url_normalized,
                "video_url": page.video_url,
            }
            for page in pages
        ]


async def list_transcription_backlog_candidates(limit: Optional[int] = None) -> list[dict]:
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
        pages = (await session.execute(select(MeetingPage).order_by(MeetingPage.created_at.asc()))).scalars().all()

        candidates = []
        for page in pages:
            if await _has_good_transcript(session, page.id):
                continue
            if await _in_auto_transcription_cooldown(session, page.id):
                continue
            candidates.append({
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
            })
            if limit is not None and len(candidates) >= limit:
                break

    return candidates


async def get_page_by_slug(slug: str) -> Optional[dict]:
    async with async_session() as session:
        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalars().first()
        if page is None:
            return None

        versions = (
            await session.execute(
                select(TranscriptVersion)
                .where(TranscriptVersion.meeting_page_id == page.id)
                .order_by(TranscriptVersion.is_default.desc(), TranscriptVersion.created_at.asc())
            )
        ).scalars().all()

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
    """Paginated listing for the /meetings index page. Filters and the
    keyword search box narrow this same query rather than being a separate
    feature (per the backlog note this was scoped from).

    Keyword search covers title, jurisdiction, agenda item text, and
    *every* transcript version's segment text for the page -- not just the
    default one, so a version that's been demoted (e.g. a garbled scraped
    caption superseded by a later AI transcript, or vice versa) is still
    findable even though the listing itself only ever displays the
    default version's language/has_transcript badge. See
    `archive/utils/search.py`. No search index, no materialized column:
    matching runs in Python, at query time, over whatever this function's
    own SQL query already returned -- deliberately not the "real" fix
    (Postgres trigram search + a materialized/indexed text column) that
    full transcript-body search eventually needs at real scale. Fine for
    the Archive's current size (dozens of meetings); see BACKLOG.md
    ("Search: move to a materialized/indexed column at scale") for what
    outgrowing this looks like and why it isn't built that way now.
    `jurisdiction`/`date_from`/`date_to`/`has_transcript` still filter in
    SQL first (cheap, and `has_transcript` needs no JSON at all), so a
    keyword-less, agenda-less browse of the page never fetches transcript
    JSON it doesn't need. `has_agenda` and `keyword` can only be evaluated
    once agenda/transcript content is in hand, so pagination for those
    happens in Python, over the SQL-filtered candidate set, not via
    LIMIT/OFFSET.

    `date` is stored as an ISO "YYYY-MM-DD" string, not a Date column --
    lexicographic comparison on that format matches chronological order, so
    plain >=/<= works for the date-range filter without a schema change.

    `created_after` is a different axis from `date_from`/`date_to`: those
    filter the meeting's own calendar date (a string), this filters
    `MeetingPage.created_at` (a real timestamp column) -- when the page
    was archived, not when the meeting happened. Added for
    archive/search_alerts.py's "what's new since this saved search was
    last checked" sweep, which has no other reason to exist in the normal
    /meetings browsing UI.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    conditions = []
    if jurisdiction:
        terms = jurisdiction_search_terms(jurisdiction)
        conditions.append(or_(*(MeetingPage.jurisdiction.ilike(f"%{t}%") for t in terms)))
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

    # The display-facing columns (language/has_transcript badge) still
    # come from the default version only, via this same outerjoin as
    # before -- only the *matching* corpus below expands to every version.
    # transcript_warnings is pulled here (not just when a keyword search
    # is active, unlike segments) since it's needed for every row's
    # has_transcript badge below, not just search matching -- cheap, a
    # short warnings list, not the full transcript JSON.
    stmt = (
        select(MeetingPage, TranscriptVersion.language, TranscriptVersion.id, TranscriptVersion.transcript_warnings)
        .outerjoin(
            TranscriptVersion,
            and_(TranscriptVersion.meeting_page_id == MeetingPage.id, TranscriptVersion.is_default.is_(True)),
        )
        .order_by(MeetingPage.created_at.desc())
    )
    if conditions:
        stmt = stmt.where(and_(*conditions))

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

        # Every version's segment text, not just the default's -- pulled
        # in one extra query, only when a keyword search is actually
        # running (same "don't drag transcript JSON over the wire for a
        # plain browse" reasoning as before), keyed by page so a demoted
        # version's text still counts toward a *match* even though it's
        # never the one displayed. Separately, default_transcript_text_by_page
        # tracks only the currently-displayed version's text -- used for
        # the search-result *snippet* (below), not the match check. Real
        # bug fixed 2026-08-08: a query that only matched an old, demoted
        # version's text (e.g. pre-fix ALL-CAPS content superseded by a
        # later re-transcription) still correctly found the page, but the
        # snippet shown for it displayed that stale text -- confusing,
        # since the page itself never shows it. Snippet text should only
        # ever come from what a viewer would actually see on the page.
        transcript_text_by_page: dict[int, str] = {}
        default_transcript_text_by_page: dict[int, str] = {}
        if keyword:
            page_ids = [mp.id for mp, _lang, _vid, _warnings in rows]
            if page_ids:
                version_rows = (
                    await session.execute(
                        select(
                            TranscriptVersion.meeting_page_id,
                            TranscriptVersion.segments,
                            TranscriptVersion.is_default,
                        ).where(TranscriptVersion.meeting_page_id.in_(page_ids))
                    )
                ).all()
                for page_id, segments, is_default in version_rows:
                    text = " ".join(seg.get("text", "") for seg in (segments or []))
                    transcript_text_by_page[page_id] = f"{transcript_text_by_page.get(page_id, '')} {text}"
                    if is_default:
                        default_transcript_text_by_page[page_id] = text

    def _matches_page(mp: MeetingPage) -> bool:
        if has_agenda is True and not mp.agenda_items:
            return False
        if has_agenda is False and mp.agenda_items:
            return False
        if not keyword:
            return True
        corpus = build_corpus(
            mp.title or "",
            mp.jurisdiction or "",
            " ".join(item.get("text", "") for item in (mp.agenda_items or [])),
            transcript_text_by_page.get(mp.id, ""),
        )
        return matches(keyword, corpus, tokenize(corpus) if fuzzy else set(), fuzzy)

    filtered = []
    for mp, lang, version_id, warnings in rows:
        if _matches_page(mp):
            filtered.append({"mp": mp, "lang": lang, "version_id": version_id, "warnings": warnings})

    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_rows = filtered[start:start + page_size]

    def _snippet_for(mp: MeetingPage) -> Optional[str]:
        # Only computed for the page of rows actually being returned, not
        # every filtered match -- a snippet nobody's about to see costs
        # nothing to skip. Deliberately excludes title/jurisdiction (see
        # find_snippet()'s own docstring) since those already render
        # directly above this in meeting_list.html. Uses only the
        # *default* version's text (not transcript_text_by_page's
        # all-versions blob used for matching above) -- if the query only
        # matched an old demoted version, the page still correctly shows
        # up in results, just with no snippet, rather than a misleading
        # excerpt of text the page itself never displays.
        if not keyword:
            return None
        agenda_text = " ".join(item.get("text", "") for item in (mp.agenda_items or []))
        transcript_text = default_transcript_text_by_page.get(mp.id, "")
        return find_snippet(keyword, [transcript_text, agenda_text], fuzzy)

    return {
        "pages": [
            {
                "slug": r["mp"].slug,
                "title": r["mp"].title,
                "date": r["mp"].date,
                "jurisdiction": r["mp"].jurisdiction,
                "meeting_body": r["mp"].meeting_body,
                "platform": r["mp"].platform,
                "language": r["lang"],
                # Quality-aware, not just "a version exists" -- a garbled
                # transcript shouldn't earn the same "Transcript" badge as
                # a real one. Language-independent on purpose (any
                # language counts, per explicit request) -- only quality
                # is gated. Same _GARBLED_MARKER check as
                # _has_good_transcript() above, inlined here rather than
                # calling it (that function does its own DB query per
                # page; this loop already has transcript_warnings from
                # the single batch query above, so re-querying per row
                # would be a real N+1).
                "has_transcript": (
                    r["version_id"] is not None
                    and not any(_GARBLED_MARKER in w for w in (r["warnings"] or []))
                ),
                "has_agenda": bool(r["mp"].agenda_items),
                "snippet": _snippet_for(r["mp"]),
            }
            for r in page_rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


async def find_new_matches_for_saved_search(search_params: dict, since: Optional[datetime]) -> list[dict]:
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
# can never have a demo.
DIRECT_PLATFORMS: dict[str, str] = {
    "granicus": "Granicus",
    "civicclerk": "CivicClerk",
    "swagit": "Swagit",
    "viebit": "Viebit",
    "escribe": "eScribe",
    "cablecast": "Cablecast",
}

# Platforms grouped under a single "Custom" row on /coverage -- each is a
# real, distinct scraper this app built (not a shared vendor product),
# but two of the four (lims, slc) delegate to YouTubeAssetFinder for the
# actual video the exact same way lims.py/slc.py's own resolve() does
# (see their docstrings) -- MeetingPage.platform ends up "youtube" for a
# page from either of them, indistinguishable by platform alone from a
# raw pasted YouTube link. _entry_platform_from_source_url() below
# recovers which of the two it actually was from the page's own
# source_url_normalized instead. ca_legislature and aurora_tv don't have
# this problem (they self-host video, no YouTube delegation), so they're
# matched by MeetingPage.platform directly, same as DIRECT_PLATFORMS.
CUSTOM_PLATFORMS: dict[str, str] = {
    "ca_legislature": "California State Legislature",
    "slc": "Salt Lake City meeting recaps",
    "lims": "Minneapolis LIMS",
    "aurora_tv": "Aurora, CO (auroratv.org)",
}

# YouTube is deliberately never its own /coverage row -- a viewer already
# gets a good deep-linkable transcript straight from YouTube itself for
# a directly-pasted YouTube URL, so this page steers people toward
# pasting the government page that embeds/links it instead (a Granicus/
# Swagit/etc. page, or one of the CUSTOM_PLATFORMS above) wherever one
# exists. See coverage.html's own footer note.
_YOUTUBE_DELEGATING_CUSTOM_PLATFORMS = frozenset({"lims", "slc"})

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
    detect_platform() -- just enough to recognize the two YouTube-
    delegating custom scrapers (see CUSTOM_PLATFORMS above) from a page's
    own source_url_normalized. archive/ deliberately doesn't import from
    app/ (see README's project structure notes on this directory's other
    deliberately-duplicated utils, e.g. url_normalize.py/language.py) --
    this stays scoped to exactly the two cases get_platform_coverage()
    needs, not a general URL classifier.
    """
    netloc = urlparse(source_url_normalized).netloc.lower()
    path = urlparse(source_url_normalized).path.lower()
    if "lims.minneapolismn.gov" in netloc:
        return "lims"
    if netloc.endswith("slc.gov") and "-meeting-recap" in path:
        return "slc"
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
            and_(TranscriptVersion.meeting_page_id == MeetingPage.id, TranscriptVersion.is_default.is_(True)),
        )
        rows = (await session.execute(stmt)).all()

    by_key: dict[str, list[dict]] = {}
    for platform, slug, title, jurisdiction, source_url, version_id, warnings in rows:
        has_transcript = version_id is not None and not any(_GARBLED_MARKER in w for w in (warnings or []))
        example = {"slug": slug, "title": title, "jurisdiction": jurisdiction, "has_transcript": has_transcript}

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
        "direct": [_coverage_row(k, v, by_key.get(k, [])) for k, v in DIRECT_PLATFORMS.items()],
        "custom": [_coverage_row(k, v, by_key.get(k, [])) for k, v in CUSTOM_PLATFORMS.items()],
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
                and_(TranscriptVersion.meeting_page_id == MeetingPage.id, TranscriptVersion.is_default.is_(True)),
            )
            .where(MeetingPage.jurisdiction.is_not(None))
        )
        rows = (await session.execute(stmt)).all()

    by_jurisdiction: dict[str, list[dict]] = {}
    for jurisdiction, slug, title, version_id, warnings in rows:
        has_transcript = version_id is not None and not any(_GARBLED_MARKER in w for w in (warnings or []))
        by_jurisdiction.setdefault(jurisdiction, []).append(
            {"slug": slug, "title": title, "has_transcript": has_transcript}
        )

    result = []
    for jurisdiction in sorted(by_jurisdiction, key=str.casefold):
        examples = by_jurisdiction[jurisdiction]
        example = next((e for e in examples if e["has_transcript"]), examples[0])
        result.append({"jurisdiction": jurisdiction, "example": example, "page_count": len(examples)})
    return result


async def list_all_page_slugs() -> list[dict]:
    """Every page's slug + updated_at, unpaginated -- for sitemap.xml.
    Fine as a single query at hundreds/thousands of rows; revisit (batching,
    a sitemap index + sub-sitemaps) only once actually approaching the
    ~50k-URL point where Google expects that split."""
    async with async_session() as session:
        rows = (
            await session.execute(select(MeetingPage.slug, MeetingPage.updated_at).order_by(MeetingPage.updated_at.desc()))
        ).all()
    return [{"slug": slug, "updated_at": updated_at} for slug, updated_at in rows]


async def list_recent_pages_for_feed(*, jurisdiction: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Most-recently-archived pages for feed.xml -- a separate, deliberately
    simple query rather than reusing list_pages()'s pagination/multi-filter
    machinery, since a feed only ever wants "the last N, optionally scoped
    to one jurisdiction," newest first, with no page number to track."""
    limit = max(1, min(limit, 100))
    stmt = select(MeetingPage).order_by(MeetingPage.created_at.desc()).limit(limit)
    if jurisdiction:
        terms = jurisdiction_search_terms(jurisdiction)
        stmt = stmt.where(or_(*(MeetingPage.jurisdiction.ilike(f"%{t}%") for t in terms)))

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
        await session.execute(select(TranscriptVersion).where(TranscriptVersion.meeting_page_id == page_id))
    ).scalars().all()
    for v in versions:
        v.is_default = v.id == version_id


async def manually_promote_transcript_version(*, slug: str, version_id: int) -> Optional[dict]:
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
        page = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
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
        page = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        if page is None:
            return None

        if version_id is not None:
            version = await session.get(TranscriptVersion, version_id)
            if version is None or version.meeting_page_id != page.id:
                return None
        else:
            version = (
                await session.execute(
                    select(TranscriptVersion).where(
                        TranscriptVersion.meeting_page_id == page.id, TranscriptVersion.is_default.is_(True)
                    )
                )
            ).scalars().first()
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
                TranscriptionJob.created_at >= datetime.now(timezone.utc) - PENDING_CONFIRMATION_EXPIRY,
            ),
        )
        existing = (
            await session.execute(
                select(TranscriptionJob)
                .where(TranscriptionJob.meeting_page_id == page.id, not_expired_pending)
                .order_by(TranscriptionJob.created_at.desc())
            )
        ).scalars().first()
        if existing:
            await session.commit()  # persist the page if it was just created, even though no job was
            return _job_dict(existing, page)

        active_spend_count = (
            await session.execute(
                select(TranscriptionJob).where(TranscriptionJob.status.in_(SPENDING_JOB_STATUSES))
            )
        ).scalars().all()
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
        await session.execute(
            select(TranscriptionJob)
            .where(TranscriptionJob.meeting_page_id == meeting_page_id)
            .order_by(TranscriptionJob.created_at.desc())
        )
    ).scalars().all()

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
        pages = (await session.execute(select(MeetingPage).order_by(MeetingPage.created_at.asc()))).scalars().all()

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
            await session.execute(
                select(TranscriptionJob).where(
                    TranscriptionJob.confirmation_token == token,
                    TranscriptionJob.status == "pending_confirmation",
                    TranscriptionJob.created_at >= datetime.now(timezone.utc) - PENDING_CONFIRMATION_EXPIRY,
                )
            )
        ).scalars().first()
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
            await session.execute(
                select(TranscriptionJob)
                .where(
                    TranscriptionJob.status.in_(("queued", "in_progress")),
                    (TranscriptionJob.claimed_at.is_(None)) | (TranscriptionJob.claimed_at < stale_before),
                )
                .order_by(TranscriptionJob.priority.desc(), TranscriptionJob.created_at.asc())
                .limit(1)
            )
        ).scalars().first()
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
        }


async def report_chunk_result(
    job_id: int,
    *,
    success: bool,
    shifted_segments: Optional[list] = None,
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
            return {"status": job.status, "consecutive_chunk_failures": job.consecutive_chunk_failures}

        job.consecutive_chunk_failures = 0
        job.partial_segments = [*job.partial_segments, *(shifted_segments or [])]
        job.chunks_completed += 1

        if job.chunks_completed >= job.total_chunks:
            language = detect_language_from_texts(s["text"] for s in job.partial_segments)
            version = TranscriptVersion(
                meeting_page_id=job.meeting_page_id,
                language=language,
                source="transcribed",
                is_default=False,  # promote_transcript_version sets the real default below
                segments=sorted(job.partial_segments, key=lambda s: s["start"]),
                transcript_warnings=[],
                content_hash=_content_hash(job.partial_segments),
            )
            session.add(version)
            await session.flush()  # assigns version.id
            await promote_transcript_version(session, job.meeting_page_id, version.id)
            job.transcript_version_id = version.id
            job.status = "completed"
            page = await session.get(MeetingPage, job.meeting_page_id)
            await session.commit()
            return {
                "status": "completed",
                "transcript_version_id": version.id,
                "meeting_page_slug": page.slug if page else None,
                "meeting_page_title": page.title if page else None,
            }

        await session.commit()
        return {"status": "in_progress", "chunks_completed": job.chunks_completed, "total_chunks": job.total_chunks}


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
            await session.execute(
                select(SavedItem.id).where(
                    SavedItem.clerk_user_id == clerk_user_id,
                    SavedItem.item_type == "saved_meeting",
                    SavedItem.meeting_page_id == meeting_page_id,
                )
            )
        ).scalars().first()
        return existing is not None


async def save_meeting(clerk_user_id: str, slug: str) -> Optional[dict]:
    """Saves a meeting to this account, keyed by its slug. Returns the
    saved item as a dict, or None if no meeting with that slug exists (the
    route turns that into a 404). Idempotent -- saving an already-saved
    meeting just returns the existing row, never creates a second one."""
    async with async_session() as session:
        meeting_page_id = (
            await session.execute(select(MeetingPage.id).where(MeetingPage.slug == slug))
        ).scalars().first()
        if meeting_page_id is None:
            return None

        existing = (
            await session.execute(
                select(SavedItem).where(
                    SavedItem.clerk_user_id == clerk_user_id,
                    SavedItem.item_type == "saved_meeting",
                    SavedItem.meeting_page_id == meeting_page_id,
                )
            )
        ).scalars().first()
        if existing:
            item = existing
        else:
            item = SavedItem(clerk_user_id=clerk_user_id, item_type="saved_meeting", meeting_page_id=meeting_page_id)
            session.add(item)
            await session.commit()
            await session.refresh(item)

        return {"id": item.id, "item_type": item.item_type, "meeting_page_id": item.meeting_page_id}


async def unsave_meeting(clerk_user_id: str, slug: str) -> bool:
    """True if a saved-meeting row existed and was removed; False if there
    was nothing to remove (not an error -- unsaving something already
    unsaved is a no-op, same as save_meeting's own idempotence)."""
    async with async_session() as session:
        meeting_page_id = (
            await session.execute(select(MeetingPage.id).where(MeetingPage.slug == slug))
        ).scalars().first()
        if meeting_page_id is None:
            return False

        existing = (
            await session.execute(
                select(SavedItem).where(
                    SavedItem.clerk_user_id == clerk_user_id,
                    SavedItem.item_type == "saved_meeting",
                    SavedItem.meeting_page_id == meeting_page_id,
                )
            )
        ).scalars().first()
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
            await session.execute(
                select(SavedItem).where(
                    SavedItem.clerk_user_id == clerk_user_id, SavedItem.item_type == "saved_search"
                )
            )
        ).scalars().all()
        for row in existing_rows:
            if row.search_params == search_params:
                return {"id": row.id, "item_type": row.item_type, "search_params": row.search_params}

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
        return {"id": item.id, "item_type": item.item_type, "search_params": item.search_params}


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
            await session.execute(select(SavedItem).where(SavedItem.item_type == "saved_search"))
        ).scalars().all()
        return [
            {
                "id": r.id,
                "clerk_user_id": r.clerk_user_id,
                "search_params": r.search_params or {},
                "last_alerted_at": r.last_alerted_at,
            }
            for r in rows
        ]


async def mark_saved_searches_alerted(saved_item_ids: list[int], checked_at: datetime) -> None:
    """Advances last_alerted_at for every saved search included in a
    digest that actually sent -- called only after a real, successful
    send (archive/search_alerts.py), never speculatively, so a failed
    Resend send doesn't silently lose that match by moving the cursor
    forward anyway."""
    if not saved_item_ids:
        return
    async with async_session() as session:
        rows = (
            await session.execute(select(SavedItem).where(SavedItem.id.in_(saved_item_ids)))
        ).scalars().all()
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
            await session.execute(
                select(SavedItem)
                .where(SavedItem.clerk_user_id == clerk_user_id)
                .order_by(SavedItem.created_at.desc())
            )
        ).scalars().all()

        meeting_ids = [r.meeting_page_id for r in rows if r.item_type == "saved_meeting" and r.meeting_page_id]
        pages_by_id = {}
        if meeting_ids:
            page_rows = (
                await session.execute(
                    select(
                        MeetingPage.id, MeetingPage.slug, MeetingPage.title, MeetingPage.date,
                        MeetingPage.jurisdiction, MeetingPage.meeting_body,
                    ).where(
                        MeetingPage.id.in_(meeting_ids)
                    )
                )
            ).all()
            pages_by_id = {
                pid: {"slug": slug, "title": title, "date": date, "jurisdiction": jurisdiction, "meeting_body": meeting_body}
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
            searches.append({"id": row.id, "created_at": row.created_at, "search_params": row.search_params or {}})

    return {"meetings": meetings, "searches": searches}


async def delete_account_data(clerk_user_id: str) -> int:
    """Hard-deletes every SavedItem for this Clerk account -- the entire
    right-to-deletion story on our side of the app.main.py user.deleted
    webhook handler, since this table stores no other PII to clean up.
    Returns the number of rows removed (for the webhook handler's own
    logging, not load-bearing)."""
    async with async_session() as session:
        rows = (await session.execute(select(SavedItem).where(SavedItem.clerk_user_id == clerk_user_id))).scalars().all()
        count = len(rows)
        for row in rows:
            await session.delete(row)
        await session.commit()
        return count
