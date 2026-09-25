#!/usr/bin/env python3
"""WO-1053: link-first hub harvest -- regional TV hubs to governments.

Some governments' meetings are never findable by starting from their own
website (Nashwauk, MN and Wilder, KY are the two Ryan named 2026-09-24) --
they only exist on a REGIONAL hub run by a bigger group or county, with a
per-town or per-body section. This is the "link-first" flow
(rtr-business `research/LINK_FIRST_MATCHING.md`): read the hub, match each
section to a real government by name AND state AND type, then record a
pin -- never trust a hub's own slug/host name as evidence on its own.

Dry run only. This script never ingests, never writes
`tenant_overrides.csv`, `jurisdiction_coverage.csv`, or any ingest queue --
it only reads `app/utils/jurisdiction_data/regional_tv_hubs.csv` (seeded by
this same WO) and real hub pages, and writes three CSVs to an output
directory the caller names:

    hub_sections.csv        every section this pass found on every hub,
                             whether or not it matched a government
    ingest_queue_plan.csv   confident, not-yet-covered matches only, with
                             a caption tier from a real (read-only) adapter
                             resolve() call
    hand_read.csv           everything a human needs to look at: no clean
                             match, or a hub shape this pass can't walk yet

Usage:
    PYTHONPATH=. .venv/bin/python scripts/hub_harvest.py --out <dir>

Polite by design: one request at a time per host, a real delay between
requests, YouTube fetch guard installed unconditionally (Pierce County TV
is YouTube-only and is never fetched here at all -- see `_youtube_hub()`).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.youtube_fetch_guard import install as install_youtube_guard  # noqa: E402
from app.platforms.cablecast import CablecastAssetFinder  # noqa: E402
from app.platforms.telvue import TelvueAssetFinder  # noqa: E402
from app.utils.gov_registry import resolver  # noqa: E402

HUB_CSV = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "utils"
    / "jurisdiction_data"
    / "regional_tv_hubs.csv"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; RedTapeRecordingsHubHarvest/1.0; "
        "+https://redtaperecordings.com)"
    )
}

# Politeness: one request at a time per host, with a real gap between
# requests to the same host (CLAUDE.md: "we query sites politely").
POLITE_DELAY_SECONDS = 1.5

# Real, confirmed real-world phrases that name a governing BODY (not just
# a place) -- used only to decide whether a section's own title is worth
# trying to match at all, and to describe (not authoritatively classify --
# that is `resolver.resolve_government()`'s job) the body type for the
# report. Every phrase here is one actually seen on a real hub while
# building this script (see `regional_tv_hubs.csv`'s own notes) or named
# in the WO-1053 brief.
_BODY_TYPE_WORDS: Tuple[Tuple[str, str], ...] = (
    ("school board", "school district"),
    ("school district", "school district"),
    ("board of education", "school district"),
    ("county board", "county"),
    ("board of commissioners", "county"),
    ("commissioners court", "county"),
    ("borough council", "borough"),
    ("town council", "town"),
    ("township board", "township"),
    ("board of supervisors", "township"),
    ("board of trustees", "township-or-village"),
    ("select board", "town"),
    ("village board", "village"),
    ("city council", "city"),
    ("city commission", "city"),
    ("town board", "town"),
    ("planning commission", "same-as-named-place"),
    ("park board", "same-as-named-place"),
    ("township council", "township"),
)

# A looser, single-word gate for "is this even worth trying to match" --
# broader than `_BODY_TYPE_WORDS` on purpose. Real gap found live
# 2026-09-24: Centre County C-NET's own real playlist titles include
# "Borough of State College - Council" and "College Township Council",
# neither of which contains any exact two-word phrase above, so the
# stricter phrase check alone skipped real governing-body sections
# outright instead of letting `resolve_government()` decide. This gate
# only decides whether to TRY a match at all; the resolver (and its own
# `unverified`/`blank` tiers) is what actually decides confidence, so a
# false positive here costs nothing worse than an extra hand_read row.
_LOOSE_BODY_WORDS = (
    "council",
    "commission",
    "board",
    "supervisors",
    "trustees",
    "select board",
    "aldermen",
)


def _looks_like_a_government_body(text: str) -> bool:
    lowered = (text or "").lower()
    if any(phrase in lowered for phrase in (w for w, _ in _BODY_TYPE_WORDS)):
        return True
    return any(word in lowered for word in _LOOSE_BODY_WORDS)


def _guessed_body_type(text: str) -> str:
    lowered = (text or "").lower()
    for phrase, body_type in _BODY_TYPE_WORDS:
        if phrase in lowered:
            return body_type
    return ""


def _resolver_candidate_text(text: str) -> str:
    """`app/utils/jurisdiction_enrich.finalize_jurisdiction()`'s repair
    rule turns "X City Council MEETING, ST" into "X City, ST" (a real
    place-table hit) but does NOT recognize a bare "X City Council, ST"
    with no trailing "Meeting" -- confirmed live 2026-09-24 building this
    script: `resolve_government("Nashwauk City Council, MN", ...)` minted
    a new `rtr:` id instead of finding the real, already-registered
    `us:place:2744980`, while the identical text with " Meeting" appended
    matched the registry cleanly (same real gap on Wilder, KY and
    Cohasset, MN). Every section title this script sees is a hub's own
    listing/category name, never literally "... Meeting" already in most
    cases (e.g. plain "Nashwauk City Council"), so this appends the one
    word `finalize_jurisdiction()` is already looking for whenever the
    text doesn't already end with it -- a workaround kept in this WO's
    own script rather than a change to `jurisdiction_enrich.py`, which
    this WO does not own."""
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    if stripped.lower().endswith(("meeting", "meetings")):
        return stripped
    return f"{stripped} Meeting"


@dataclass
class HubRow:
    hub: str
    platform: str
    url: str
    region_state: str
    notes: str


@dataclass
class SectionResult:
    hub: str
    section: str
    jurisdiction_text: str
    body_type: str
    newest_title: str
    newest_date: str
    newest_url: str
    matched_gov_id: str
    matched_gov_name: str
    confidence: str
    reason: str
    resolve_url: str = ""  # canonical URL to re-resolve for a real tier check


def load_hubs() -> List[HubRow]:
    with open(HUB_CSV, newline="", encoding="utf-8") as f:
        return [HubRow(**row) for row in csv.DictReader(f)]


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status >= 400:
                return None
            return await response.text()
    except (aiohttp.ClientError, TimeoutError):
        return None


_REMIX_CONTEXT_RE = re.compile(
    r"window\.__remixContext\s*=\s*(\{.*?\});</script>", re.DOTALL
)


def _extract_remix_context(html: str) -> Optional[dict]:
    match = _REMIX_CONTEXT_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def _find_all(obj: Any, predicate) -> List[dict]:
    results: List[dict] = []
    if isinstance(obj, dict):
        if predicate(obj):
            results.append(obj)
        for value in obj.values():
            results.extend(_find_all(value, predicate))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_find_all(item, predicate))
    return results


def _find_site_object(data: dict) -> Optional[dict]:
    hits = _find_all(data, lambda o: "siteId" in o and "pageDescription" in o)
    return hits[0] if hits else None


def _parse_show_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _newest_show(shows: List[dict]) -> Optional[dict]:
    ready = [s for s in shows if s.get("vodUrl")]
    pool = ready or shows
    if not pool:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return max(pool, key=lambda s: _parse_show_date(s.get("eventDate")) or epoch)


def _with_site_param(url: str, site_id: Any) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["site"] = [str(site_id)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


async def _harvest_cablecast_remix(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    """Walks a Cablecast Remix-template hub: `site.otherSites` (if any)
    lists every section/town on the host, and each section's own
    `site.galleries` are its per-body categories -- see
    `regional_tv_hubs.csv`'s own notes for the real examples this is
    built on (Iron Range TV has no otherSites at all, just galleries on
    one site; North Metro TV and Harbor Media have several sites each
    with their own galleries)."""
    html = await _fetch_text(session, hub.url)
    if html is None:
        return [], "fetch_failed"
    data = _extract_remix_context(html)
    if data is None:
        return [], "no_remix_context_found"
    site = _find_site_object(data)
    if site is None:
        return [], "no_site_object_found"

    other_sites = site.get("otherSites") or [site]
    seen_ids: set = set()
    sections: List[SectionResult] = []
    for other in other_sites:
        site_id = other.get("siteId")
        if site_id in seen_ids:
            continue
        seen_ids.add(site_id)

        if site_id == site.get("siteId"):
            site_data = data
        else:
            await asyncio.sleep(POLITE_DELAY_SECONDS)
            site_url = _with_site_param(hub.url, site_id)
            site_html = await _fetch_text(session, site_url)
            site_data = _extract_remix_context(site_html) if site_html else None
        if site_data is None:
            sections.append(
                _section(
                    hub,
                    section=other.get("title") or f"site {site_id}",
                    reason="site_fetch_failed",
                )
            )
            continue

        # De-duplicated by cablecastGalleryId -- confirmed live 2026-09-24
        # that the same gallery object appears more than once in one
        # page's remix tree (e.g. both a nav-menu copy and a home-content
        # copy), the same real shape `_resolve_gallery()`'s own docstring
        # in cablecast.py warns about for "any show-shaped object
        # anywhere on the page". Walking the whole tree without this
        # produced the same "Anoka County Board Meetings" section (and
        # its ingest-queue row) six times over on North Metro TV.
        seen_gallery_ids: set = set()
        galleries = []
        for gallery in _find_all(site_data, lambda o: "cablecastGalleryId" in o):
            gallery_id = gallery.get("cablecastGalleryId")
            if gallery_id in seen_gallery_ids:
                continue
            seen_gallery_ids.add(gallery_id)
            galleries.append(gallery)
        site_title = other.get("title") or ""
        if not galleries:
            sections.append(_build_matched_section(hub, site_title, site_title, None))
            continue
        for gallery in galleries:
            newest = _newest_show(gallery.get("shows") or [])
            sections.append(
                _build_matched_section(
                    hub, gallery.get("title") or "", site_title, newest
                )
            )
    return sections, None


def _canonical_cablecast_show_url(hub_url: str, show: dict) -> Optional[str]:
    show_id = show.get("showId")
    if show_id is None:
        return None
    parsed = urlparse(hub_url)
    return f"{parsed.scheme}://{parsed.netloc}/internetchannel/show/{show_id}"


def _build_matched_section(
    hub: HubRow, section_name: str, site_title: str, newest: Optional[dict]
) -> SectionResult:
    text_for_match = section_name if _looks_like_a_government_body(section_name) else ""
    if not text_for_match and _looks_like_a_government_body(site_title):
        text_for_match = site_title

    result = _section(
        hub,
        section=section_name or site_title,
        newest_title=(newest or {}).get("title") or "",
        newest_date=(newest or {}).get("eventDate") or "",
        newest_url=(newest or {}).get("vodUrl") or "",
        resolve_url=_canonical_cablecast_show_url(hub.url, newest) if newest else "",
    )
    if not text_for_match:
        result.reason = "section title does not name a governing body"
        return result

    raw_name = (
        f"{_resolver_candidate_text(text_for_match)}, {hub.region_state}"
        if hub.region_state
        else _resolver_candidate_text(text_for_match)
    )
    match = resolver.resolve_government(raw_name, tenant_host=urlparse(hub.url).netloc)
    result.jurisdiction_text = text_for_match
    result.body_type = _guessed_body_type(text_for_match)
    result.matched_gov_id = match.gov_id or ""
    result.matched_gov_name = match.gov_name or ""
    if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
        result.confidence = "confident"
        result.reason = f"exact name+state+type match ({match.tier})"
    else:
        result.confidence = "hand_read"
        result.reason = f"resolver tier={match.tier}: {match.evidence}"
    return result


def _section(hub: HubRow, section: str, **kwargs) -> SectionResult:
    defaults = dict(
        hub=hub.hub,
        section=section,
        jurisdiction_text="",
        body_type="",
        newest_title="",
        newest_date="",
        newest_url="",
        matched_gov_id="",
        matched_gov_name="",
        confidence="hand_read",
        reason="",
        resolve_url="",
    )
    defaults.update(kwargs)
    return SectionResult(**defaults)


# TelVue's own `/home` page (see telvue.py's `list_playlist_items` module
# note) renders one card per playlist -- title, "(N Videos)", and a link
# straight to that playlist's newest media item. Confirmed live 2026-09-24
# on Centre County C-NET's real org token (see regional_tv_hubs.csv).
_TELVUE_CARD_RE = re.compile(
    r'<a href="(/player/[^/]+/playlists/\d+/media/\d+)">.*?'
    r'<span class="h4 title block">([^<]*)</span>',
    re.DOTALL,
)


async def _harvest_telvue(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    html = await _fetch_text(session, hub.url)
    if html is None:
        return [], "fetch_failed"
    parsed = urlparse(hub.url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    sections: List[SectionResult] = []
    for path, title in _TELVUE_CARD_RE.findall(html):
        title = title.strip()
        section = _section(
            hub,
            section=title,
            newest_url=urljoin(origin, path),
            resolve_url=urljoin(origin, path),
        )
        if not _looks_like_a_government_body(title):
            section.reason = "section title does not name a governing body"
        else:
            raw_name = (
                f"{_resolver_candidate_text(title)}, {hub.region_state}"
                if hub.region_state
                else _resolver_candidate_text(title)
            )
            match = resolver.resolve_government(raw_name, tenant_host=parsed.netloc)
            section.jurisdiction_text = title
            section.body_type = _guessed_body_type(title)
            section.matched_gov_id = match.gov_id or ""
            section.matched_gov_name = match.gov_name or ""
            if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
                section.confidence = "confident"
                section.reason = f"exact name+state+type match ({match.tier})"
            else:
                section.confidence = "hand_read"
                section.reason = f"resolver tier={match.tier}: {match.evidence}"
        sections.append(section)
    return sections, None


# CablecastPublicSite (TVCTV): confirmed live 2026-09-24 that its own show
# API has no per-site/per-category filter that actually narrows the
# 24,000+-show shared catalog (see regional_tv_hubs.csv's own note) --
# recorded as hand-read leads only, one per known site id, no newest-show
# claim made for any of them.
_TVCTV_SITES = (
    ("1", "Our Channels site 1"),
    ("2", "Our Channels site 2"),
    ("3", "Our Channels site 3"),
    ("5", "Our Channels site 5"),
    ("6", "Government site 6"),
    ("7", "Government site 7"),
)


async def _harvest_cablecast_publicsite(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    del session  # no fetch is trusted enough yet -- see module note above
    sections = [
        _section(
            hub,
            section=label,
            newest_url=_with_site_param(hub.url, site_id),
            reason=(
                "CablecastPublicSite per-site/category show listing is not "
                "confirmed yet -- recorded as a lead only, see "
                "regional_tv_hubs.csv"
            ),
        )
        for site_id, label in _TVCTV_SITES
    ]
    return sections, None


# Pierce County TV: YOUTUBE-DRIP-ONLY. This never fetches piercecountytv's
# YouTube channel or any youtube.com URL at all -- the section list below
# is the real, confirmed (2026-09-24) result of reading the site's own
# non-YouTube navigation (see regional_tv_hubs.csv's note), hardcoded here
# rather than re-fetched every run so this function makes zero network
# requests of its own kind that could ever touch YouTube.
_PIERCE_COUNTY_SECTIONS = (
    ("City of DuPont", "https://www.piercecountytv.org/91/City-of-DuPont"),
    ("City of Fife", "https://www.piercecountytv.org/94/City-of-Fife"),
    ("City of Orting", "https://www.piercecountytv.org/97/City-of-Orting"),
    (
        "Pierce County Council",
        "https://www.piercecountytv.org/100/Pierce-County-Council",
    ),
    ("City of Puyallup", "https://www.piercecountytv.org/103/City-of-Puyallup"),
    (
        "Rainier Communications Commission",
        "https://www.piercecountytv.org/106/Rainier-Communications-Commission",
    ),
    ("City of Sumner", "https://www.piercecountytv.org/108/City-of-Sumner"),
    (
        "City of University Place",
        "https://www.piercecountytv.org/111/City-of-University-Place",
    ),
    (
        "Tacoma-Pierce County Health Department",
        "https://www.piercecountytv.org/1317/Tacoma-Pierce-County-Health-Department",
    ),
)


async def _harvest_youtube_hub(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    del session  # deliberately unused -- see module note above
    sections = []
    for name, url in _PIERCE_COUNTY_SECTIONS:
        section = _section(
            hub,
            section=name,
            newest_url=url,
            reason=(
                "YouTube-drip-only hub: never fetched here. This is a "
                "confirmed per-government section page, not a video -- "
                "the newest meeting still needs the drip Mac to check "
                "the channel."
            ),
        )
        text = name
        raw_name = (
            f"{_resolver_candidate_text(text)}, {hub.region_state}"
            if hub.region_state
            else _resolver_candidate_text(text)
        )
        match = resolver.resolve_government(
            raw_name, tenant_host=urlparse(hub.url).netloc
        )
        section.jurisdiction_text = text
        section.matched_gov_id = match.gov_id or ""
        section.matched_gov_name = match.gov_name or ""
        if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
            section.confidence = "confident_no_video_yet"
        else:
            section.confidence = "hand_read"
        sections.append(section)
    return sections, None


async def _harvest_vimeo_channel(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    """A single-government Vimeo channel (Montague, MA) -- no per-town
    section to walk, so this records exactly one section: the hub's own
    name against its `region_state`. Vimeo's own newest-video listing API
    needs an authenticated call this pass doesn't have, so `newest_*`
    fields are left blank rather than guessed (this hub's town-video
    resolve already goes through `app/platforms/vimeo.py`'s own headless
    path when a real URL is in hand -- out of scope here)."""
    del session
    text = hub.hub.replace("Community Television", "").strip()
    raw_name = (
        f"{_resolver_candidate_text(text)}, {hub.region_state}"
        if hub.region_state
        else _resolver_candidate_text(text)
    )
    match = resolver.resolve_government(raw_name, tenant_host=urlparse(hub.url).netloc)
    section = _section(
        hub,
        section=hub.hub,
        jurisdiction_text=text,
        newest_url=hub.url,
        matched_gov_id=match.gov_id or "",
        matched_gov_name=match.gov_name or "",
        reason="single-government Vimeo channel; newest video not fetched this pass",
    )
    section.confidence = (
        "confident_no_video_yet"
        if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY)
        else "hand_read"
    )
    return [section], None


_HARVESTERS = {
    "cablecast_remix": _harvest_cablecast_remix,
    "telvue": _harvest_telvue,
    "cablecast_publicsite": _harvest_cablecast_publicsite,
    "youtube_hub": _harvest_youtube_hub,
    "vimeo": _harvest_vimeo_channel,
}


async def _resolve_tier(section: SectionResult, platform: str) -> str:
    """A real (read-only) adapter `resolve()` call against the section's
    own canonical show URL, used only to report a caption tier for the
    ingest-queue plan -- never writes anything. Never called for a
    YouTube-hosted section (Pierce County TV is filtered out by the
    caller before this runs)."""
    if not section.resolve_url:
        return "unknown"
    try:
        if platform in ("cablecast_remix",):
            result = await CablecastAssetFinder().resolve(section.resolve_url)
        elif platform == "telvue":
            result = await TelvueAssetFinder().resolve(section.resolve_url)
        else:
            return "unknown"
    except Exception as exc:  # noqa: BLE001 -- dry run: never crash the pass
        return f"resolve_error: {exc}"
    if result.segments:
        return "tier1_captions"
    if result.video_url:
        return "tier3_video_only"
    return "no_video"


def _dedupe_sections(sections: List[SectionResult]) -> List[SectionResult]:
    """A shared body (e.g. a county board) can legitimately appear as its
    own identical gallery on EVERY member city's own site page within one
    hub -- confirmed live 2026-09-24 on North Metro TV: "Anoka County
    Board Meetings" is a real gallery embedded on each of its 7 city
    sites, not a parsing bug (the per-page duplicate GALLERY-object copy
    bug is separate and is fixed where the galleries are read, see that
    comment). This collapses same-hub repeats of the exact same section
    name + newest video down to one row, so the reports (and the ingest
    queue) count each real government/section once, not once per site it
    happens to be syndicated onto."""
    seen: set = set()
    deduped = []
    for section in sections:
        key = (section.section, section.newest_url, section.matched_gov_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(section)
    return deduped


async def run(out_dir: Path) -> Dict[str, List[SectionResult]]:
    install_youtube_guard()
    hubs = load_hubs()
    by_hub: Dict[str, List[SectionResult]] = {}
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for hub in hubs:
            harvester = _HARVESTERS.get(hub.platform)
            if harvester is None:
                by_hub[hub.hub] = [
                    _section(
                        hub,
                        section="(hub)",
                        reason=f"unknown platform {hub.platform!r}",
                    )
                ]
                continue
            sections, hub_error = await harvester(session, hub)
            if hub_error:
                sections = [_section(hub, section="(hub)", reason=hub_error)]
            by_hub[hub.hub] = _dedupe_sections(sections)
            await asyncio.sleep(POLITE_DELAY_SECONDS)

    out_dir.mkdir(parents=True, exist_ok=True)
    all_sections = [s for rows in by_hub.values() for s in rows]

    with open(out_dir / "hub_sections.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "hub",
                "section",
                "jurisdiction_text",
                "body_type",
                "newest_title",
                "newest_date",
                "newest_url",
                "matched_gov_id",
                "matched_gov_name",
                "confidence",
                "reason",
            ]
        )
        for s in all_sections:
            writer.writerow(
                [
                    s.hub,
                    s.section,
                    s.jurisdiction_text,
                    s.body_type,
                    s.newest_title,
                    s.newest_date,
                    s.newest_url,
                    s.matched_gov_id,
                    s.matched_gov_name,
                    s.confidence,
                    s.reason,
                ]
            )

    confident = [
        s for s in all_sections if s.confidence == "confident" and s.resolve_url
    ]
    with open(
        out_dir / "ingest_queue_plan.csv", "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["url", "source", "gov_id", "gov_name", "tier"])
        hub_platform = {h.hub: h.platform for h in hubs}
        for s in confident:
            tier = await _resolve_tier(s, hub_platform.get(s.hub, ""))
            writer.writerow(
                [s.resolve_url, s.hub, s.matched_gov_id, s.matched_gov_name, tier]
            )
            await asyncio.sleep(POLITE_DELAY_SECONDS)

    hand_read = [s for s in all_sections if s.confidence != "confident"]
    with open(out_dir / "hand_read.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "hub",
                "section",
                "jurisdiction_text",
                "newest_url",
                "matched_gov_id",
                "matched_gov_name",
                "confidence",
                "reason",
            ]
        )
        for s in hand_read:
            writer.writerow(
                [
                    s.hub,
                    s.section,
                    s.jurisdiction_text,
                    s.newest_url,
                    s.matched_gov_id,
                    s.matched_gov_name,
                    s.confidence,
                    s.reason,
                ]
            )

    return by_hub


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory for the 3 CSVs")
    args = parser.parse_args()
    by_hub = asyncio.run(run(Path(args.out)))
    for hub_name, sections in by_hub.items():
        confident = sum(1 for s in sections if s.confidence == "confident")
        print(
            f"{hub_name}: {len(sections)} section(s), {confident} confident match(es)"
        )


if __name__ == "__main__":
    main()
