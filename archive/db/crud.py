import hashlib
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, or_, select

from ..utils.language import detect_language_from_texts
from ..utils.search import build_corpus, find_snippet, matches, tokenize
from ..utils.slugify import build_base_slug, random_suffix
from ..utils.url_normalize import normalize_url
from .engine import async_session
from .models import MeetingPage, MeetingPageUrlAlias, TranscriptionJob, TranscriptVersion


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

    page = await _find_existing_page(
        session,
        platform=platform,
        external_id=external_id,
        source_url_normalized=source_url_normalized,
        input_url_normalized=input_url_normalized,
    )

    if page is None:
        base_slug = build_base_slug(payload.get("jurisdiction") or "", payload.get("date") or "", payload.get("title") or "")
        slug = await _unique_slug(session, base_slug)
        page = MeetingPage(
            slug=slug,
            platform=platform,
            external_id=external_id,
            source_url_normalized=source_url_normalized,
            title=payload.get("title"),
            date=payload.get("date"),
            jurisdiction=payload.get("jurisdiction"),
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
        page.title = payload.get("title") or page.title
        page.date = payload.get("date") or page.date
        page.jurisdiction = payload.get("jurisdiction") or page.jurisdiction
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
    agenda_items, transcript_language, transcript_warnings.

    Also handles promoting/demoting the page's default TranscriptVersion
    when warranted -- see _is_real_improvement() and
    _default_looks_like_copied_agenda() above, and BACKLOG_DONE.md for
    the two real bugs (Dublin, Yountville) this closes. Only ever touches
    an *existing* default; a brand-new page's first version is already
    is_default=True from creation, nothing more to do.
    """
    segments = payload.get("segments") or []
    agenda_items = payload.get("agenda_items") or []

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

            duplicate = (
                await session.execute(
                    select(TranscriptVersion).where(
                        TranscriptVersion.meeting_page_id == page.id,
                        TranscriptVersion.language == language,
                        TranscriptVersion.source == "scraped",
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
                    source="scraped",
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
            "slug": page.slug,
            "platform": page.platform,
            "title": page.title,
            "date": page.date,
            "jurisdiction": page.jurisdiction,
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
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    conditions = []
    if jurisdiction:
        conditions.append(MeetingPage.jurisdiction.ilike(f"%{jurisdiction}%"))
    if date_from:
        conditions.append(MeetingPage.date >= date_from)
    if date_to:
        conditions.append(MeetingPage.date <= date_to)
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
        stmt = stmt.where(MeetingPage.jurisdiction.ilike(f"%{jurisdiction}%"))

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
