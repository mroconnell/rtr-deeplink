"""Read-only, bounded Archive lookup. No platform resolution or network IO.

The small URL recognizer below deliberately supports only fixture-confirmed
recording shapes. Unsupported URLs can still match a stored source/alias;
without that hit they need research, not ingestion. It imports no adapters:
those bring resolver-only dependencies into the Archive service.
"""

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.platforms.youtube_ids import extract_video_id
from app.utils.gov_registry.display import display_name
from app.utils.gov_registry.registry import consolidated, government_for_id
from app.utils.url_normalize import normalize_url
from archive.context.schemas import LookupResult
from archive.context.status import next_action_for
from archive.db.models import MeetingPage, MeetingPageUrlAlias, TranscriptVersion
from archive.utils.context_links import ContextLinkError, parse_rtr_link

MAX_POSSIBLE_PAGES = 20
MAX_ACTIVE_CLAIMS = 100
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def recording_identity(url: str) -> tuple[str, str] | None:
    """Pure identity in the Archive's actual (platform, external_id) format.

    Provenance: test_youtube.py/youtube_ids.py; Fountain Valley clip 607
    in test_granicus.py; Emporia event 585 in test_civicclerk.py; Salisbury
    video 1212025580 in test_vimeo.py. No event/live/listing IDs are guessed.
    Tenant hosts are part of Granicus/CivicClerk IDs, as in their adapters.
    """
    parts = urlsplit(normalize_url(url))
    host = parts.hostname or ""
    if parts.scheme != "https" or parts.username or parts.port:
        return None
    query = parse_qs(parts.query, keep_blank_values=True)
    if host in _YOUTUBE_HOSTS:
        if host == "youtu.be":
            valid_path = re.fullmatch(r"/[A-Za-z0-9_-]{11}/?", parts.path)
        elif parts.path == "/watch":
            valid_path = len(query.get("v", [])) == 1
        else:
            valid_path = re.fullmatch(
                r"/(?:embed|shorts|live|v)/[A-Za-z0-9_-]{11}/?", parts.path
            )
        if valid_path:
            # Drop unrelated query fields before the shared regex sees them.
            clean_query = f"v={query['v'][0]}" if parts.path == "/watch" else ""
            video_id = extract_video_id(
                urlunsplit(("https", host, parts.path, clean_query, ""))
            )
            if video_id:
                return "youtube", f"youtube:{video_id}"
    if re.fullmatch(r"[a-z0-9-]+\.granicus\.com", host):
        match = re.fullmatch(r"/(?:player/clip|videos)/(\d+)(?:/player)?", parts.path)
        clip = match.group(1) if match else None
        if parts.path == "/MediaPlayer.php" and len(query.get("clip_id", [])) == 1:
            clip = query["clip_id"][0]
        if clip and clip.isdigit():
            return "granicus", f"granicus:{host}:{clip}"
    if re.fullmatch(r"[a-z0-9-]+\.portal\.civicclerk\.com", host):
        match = re.fullmatch(r"/event/(\d+)(?:/media)?", parts.path)
        if match:
            return "civicclerk", f"civicclerk:{host}:{match.group(1)}"
    if host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        pattern = r"/video/(\d+)" if host == "player.vimeo.com" else r"/(\d+)"
        match = re.fullmatch(pattern, parts.path)
        if match:
            return "vimeo", f"vimeo:{match.group(1)}"
    return None


def _text(value) -> str | None:
    return " ".join(str(value).split()).casefold() if value not in (None, "") else None


def _gov(value) -> str | None:
    value = str(value).strip() if value else None
    return consolidated().get(value, value)


def _names(gov_id: str | None) -> set[str]:
    canonical = _gov(gov_id)
    if not canonical:
        return set()
    # Committed consolidated aliases include the county's own names as well
    # as its IDs; Marion County and Indianapolis are one government here.
    ids = {canonical} | {old for old, new in consolidated().items() if new == canonical}
    names = set()
    for equivalent_id in ids:
        government = government_for_id(equivalent_id)
        if not government:
            continue
        variants = {government.gov_name, *government.aliases, display_name(government)}
        if government.state:
            suffix = f", {government.state}"
            variants |= {name.removesuffix(suffix) for name in variants}
            variants |= {
                f"{name}{suffix}" for name in variants if not name.endswith(suffix)
            }
        names.update(_text(name) for name in variants)
    return names


def _snapshot(page: MeetingPage) -> dict:
    return {
        "id": page.id,
        "slug": page.slug,
        "url": f"/m/{page.slug}",
        "title": page.title,
        "date": page.date,
        "meeting_body": page.meeting_body,
        "jurisdiction": page.jurisdiction,
        "gov_id": page.gov_id,
        "platform": page.platform,
        "external_id": page.external_id,
        "source_url_normalized": page.source_url_normalized,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


def _metadata_conflicts(claims: list[dict], page: MeetingPage | None) -> list[dict]:
    evidence = []
    fields = {
        "gov_id": "gov_id",
        "meeting_date": "date",
        "meeting_body": "meeting_body",
    }
    for field, attr in fields.items():
        normalize = _gov if field == "gov_id" else _text
        values = {normalize(c.get(field)) for c in claims if c.get(field)}
        stored = normalize(getattr(page, attr)) if page else None
        if len(values) > 1 or (stored and values and stored not in values):
            evidence.append(
                {
                    "kind": "metadata_conflict",
                    "field": field,
                    "claims": sorted(values),
                    "stored": stored,
                }
            )
    gov_ids = {_gov(c.get("gov_id")) for c in claims if c.get("gov_id")}
    if page and page.gov_id:
        gov_ids.add(_gov(page.gov_id))
    known_names = set().union(*(_names(gov_id) for gov_id in gov_ids))
    names = {_text(c.get("jurisdiction")) for c in claims if c.get("jurisdiction")}
    stored_name = _text(page.jurisdiction) if page else None
    if stored_name:
        names.add(stored_name)
    # Only committed registry aliases establish name equivalence. No name,
    # title, or shared-host heuristic assigns a government here.
    unknown_names = names - known_names
    if any(c.get("jurisdiction") for c in claims) and (
        (len(names) > 1 and unknown_names) or (known_names and unknown_names)
    ):
        evidence.append(
            {
                "kind": "metadata_conflict",
                "field": "jurisdiction",
                "claims": sorted(names),
                "stored": stored_name,
            }
        )
    states = {_text(c.get("state")) for c in claims if c.get("state")}
    for gov_id in gov_ids:
        government = government_for_id(gov_id)
        if government and government.state:
            states.add(_text(government.state))
    if len(states) > 1:
        evidence.append(
            {"kind": "metadata_conflict", "field": "state", "claims": sorted(states)}
        )
    return evidence


async def evaluate_candidate(
    claims: list[dict], *, session: AsyncSession
) -> LookupResult:
    """Exhaust identifiers without flushing caller writes; SQL errors propagate."""
    with session.no_autoflush:
        return await _evaluate_candidate(claims, session=session)


def _page_query():
    return select(MeetingPage).options(
        load_only(
            MeetingPage.id,
            MeetingPage.slug,
            MeetingPage.title,
            MeetingPage.date,
            MeetingPage.meeting_body,
            MeetingPage.jurisdiction,
            MeetingPage.gov_id,
            MeetingPage.platform,
            MeetingPage.external_id,
            MeetingPage.source_url_normalized,
            MeetingPage.updated_at,
        )
    )


async def _evaluate_candidate(
    claims: list[dict], *, session: AsyncSession
) -> LookupResult:
    """No large agenda, transcript or media payloads are selected."""
    if len(claims) > MAX_ACTIVE_CLAIMS:
        return LookupResult(
            outcome="ambiguous",
            next_action="resolve_needed",
            reason="Too many active source records for one bounded check. Review the sources.",
        )
    evidence: list[dict] = []
    pages: dict[int, MeetingPage] = {}
    duplicate = False
    identifiers: dict[tuple[str, str], set[int]] = {}
    unknown_urls: set[str] = set()
    unmatched_rtr = False

    async def record(statement, method: str, value: str) -> set[int]:
        nonlocal duplicate
        found = list(
            (
                await session.scalars(
                    statement.order_by(MeetingPage.id).limit(MAX_POSSIBLE_PAGES + 1)
                )
            ).all()
        )
        ids = {p.id for p in found}
        duplicate |= len(ids) > 1
        pages.update({p.id: p for p in found[:MAX_POSSIBLE_PAGES]})
        evidence.append(
            {
                "kind": "direct_lookup",
                "method": method,
                "value": value,
                "page_ids": sorted(ids)[:MAX_POSSIBLE_PAGES],
                "truncated": len(found) > MAX_POSSIBLE_PAGES,
            }
        )
        return ids

    for link in sorted({c["rtr_link"] for c in claims if c.get("rtr_link")}):
        try:
            slug, _ = parse_rtr_link(link, None)
        except ContextLinkError:
            unmatched_rtr = True
            evidence.append({"kind": "unresolved_rtr_link", "value": link})
            continue
        ids = await record(
            _page_query().where(MeetingPage.slug == slug), "rtr_slug", slug
        )
        identifiers[("rtr_slug", slug)] = ids
        if not ids:
            unmatched_rtr = True
            evidence.append(
                {
                    "kind": "unresolved_rtr_link",
                    "value": link,
                    "reason": "No current slug matched. Old-slug redirects are not checked.",
                }
            )

    for url in sorted({c["recording_url"] for c in claims if c.get("recording_url")}):
        normalized = normalize_url(url)
        aliases = select(MeetingPageUrlAlias.meeting_page_id).where(
            MeetingPageUrlAlias.url_normalized == normalized
        )
        ids = await record(
            _page_query().where(
                or_(
                    MeetingPage.source_url_normalized == normalized,
                    MeetingPage.id.in_(aliases),
                )
            ),
            "stored_url",
            normalized,
        )
        identity = recording_identity(url)
        if identity:
            platform, external_id = identity
            ids |= await record(
                _page_query().where(
                    MeetingPage.platform == platform,
                    MeetingPage.external_id == external_id,
                ),
                "platform_id",
                external_id,
            )
            identifiers[identity] = identifiers.get(identity, set()) | ids
        elif not ids:
            unknown_urls.add(normalized)
        identifiers[("url", normalized)] = ids

    page = next(iter(pages.values())) if len(pages) == 1 else None
    conflicts = _metadata_conflicts(claims, page)
    evidence.extend(conflicts)
    # Different IDs on the same platform are contradictory unless stored
    # aliases prove that they refer to the same Archive page.
    for platform in {key[0] for key in identifiers} - {"url", "rtr_slug"}:
        values = [ids for (kind, _), ids in identifiers.items() if kind == platform]
        if len(values) > 1 and not set.intersection(*values):
            conflicts.append(
                {"kind": "recording_identifier_conflict", "platform": platform}
            )
            evidence.append(conflicts[-1])
    if conflicts or (len(pages) > 1 and not duplicate):
        return LookupResult(
            outcome="conflict",
            next_action="conflict",
            reason="The supplied meeting evidence or recording identifiers disagree.",
            possible_pages=[_snapshot(p) for p in pages.values()][:MAX_POSSIBLE_PAGES],
            evidence=evidence,
        )
    if duplicate:
        return LookupResult(
            outcome="ambiguous",
            next_action="resolve_needed",
            reason="A direct identifier matches multiple Archive pages. Review the duplicates.",
            possible_pages=[_snapshot(p) for p in pages.values()][:MAX_POSSIBLE_PAGES],
            evidence=evidence,
        )
    missing_ids = [
        (kind, value)
        for (kind, value), ids in identifiers.items()
        if not ids and kind not in {"url", "rtr_slug"}
    ]
    if page and not unknown_urls and not missing_ids:
        snapshot = _snapshot(page)
        # Existence only: never load transcript bodies or infer video duration.
        snapshot["has_transcript"] = bool(
            await session.scalar(
                select(TranscriptVersion.id)
                .where(TranscriptVersion.meeting_page_id == page.id)
                .limit(1)
            )
        )
        snapshot["duration_seconds"] = None
        return LookupResult(
            outcome="matched",
            next_action="moment_needed",
            method="direct_identifiers",
            meeting_page_id=page.id,
            page_snapshot=snapshot,
            evidence=evidence,
            reason="RTR has this supplied recording. The social clip, proposed timestamp, and explanation still need editorial review.",
        )

    # Suggestions require a date and either an explicit government ID or an
    # exact supplied jurisdiction string. They never certify association.
    suggestions: dict[int, MeetingPage] = {}
    for claim in claims:
        date = claim.get("meeting_date")
        gov_id = _gov(claim.get("gov_id"))
        jurisdiction = _text(claim.get("jurisdiction"))
        if not date or not (gov_id or jurisdiction):
            continue
        query = _page_query().where(MeetingPage.date == date)
        if gov_id:
            equivalent_ids = [gov_id] + [
                old for old, new in consolidated().items() if new == gov_id
            ]
            query = query.where(MeetingPage.gov_id.in_(equivalent_ids))
        else:
            query = query.where(func.lower(MeetingPage.jurisdiction) == jurisdiction)
        found = (
            await session.scalars(
                query.order_by(MeetingPage.id).limit(MAX_POSSIBLE_PAGES)
            )
        ).all()
        suggestions.update({p.id: p for p in found})
        if len(suggestions) >= MAX_POSSIBLE_PAGES:
            break
    possible = {**pages, **suggestions}
    concrete = any(kind not in {"url", "rtr_slug"} for kind, _ in identifiers)
    unresolved = bool(possible or unknown_urls or unmatched_rtr or len(missing_ids) > 1)
    meeting_identified = any(
        c.get("meeting_date")
        and c.get("meeting_body")
        and (c.get("gov_id") or (c.get("jurisdiction") and c.get("state")))
        for c in claims
    )
    action = next_action_for(
        unresolved=unresolved,
        recording_identified=concrete,
        meeting_identified=meeting_identified,
    )
    reasons = {
        "resolve_needed": "The meeting identity is not settled. Review the supplied links and any possible Archive pages.",
        "recording_needed": "The research names a meeting but supplies no identifiable full recording. Find its recording.",
        "ingest_needed": "This recording was not found using the checked identifiers. Review it before any later ingestion.",
    }
    if suggestions:
        evidence.append(
            {
                "kind": "metadata_suggestions",
                "reason": "Government and date suggest pages; metadata alone is never an exact match.",
            }
        )
    return LookupResult(
        outcome="ambiguous" if possible else "not_found",
        next_action=action,
        reason=reasons[action],
        possible_pages=[_snapshot(p) for p in possible.values()][:MAX_POSSIBLE_PAGES],
        evidence=evidence,
    )
