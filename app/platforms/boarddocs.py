import logging
import re
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from .vimeo import VimeoAssetFinder
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich

logger = logging.getLogger("rtr_deeplink.boarddocs")

# BoardDocs (Diligent) -- mechanism confirmed live 2026-09-14 (WO-365), spec
# in docs/investigations/boarddocs_video_adapter.md (Breadth). Every tenant
# lives on the ONE shared host `go.boarddocs.com`, with the government
# encoded as `/{st}/{slug}/Board.nsf/...` -- `{st}` is BoardDocs' OWN state
# prefix (not always USPS: "fla" for Florida, confirmed live; every other
# prefix seen so far -- "az", "ca", "md", "mo", "tx" -- already matches its
# USPS abbreviation).
#
# Per-meeting video, when it exists at all, is exposed through a fixed,
# unauthenticated 3-step mechanism, same shape for every tenant:
#   1. GET  /{st}/{slug}/Board.nsf/Public              -- tenant page. Inline
#      script carries `bd.videoservice = "N"`: "0" no video service, "1"
#      YouTube, "2" Vimeo, "3" a third service (unmapped -- no real tenant
#      confirmed live yet; logged and treated as video-less).
#   2. GET  /{st}/{slug}/Board.nsf/BD-GETMeetingsListForSEO -- JSON array of
#      every meeting, newest first: Name, Description, Unique (12-char
#      meeting id), Date (ISO, midnight UTC; includes FUTURE meetings, so a
#      tenant-level resolve filters Date <= today).
#   3. POST /{st}/{slug}/Board.nsf/VIDEO-GetAgenda?open  body `id={Unique}`
#      -- an HTML fragment. Its first <script> sets
#      `$("#video-dialog input[name=video_id]").val("...")`: the YouTube or
#      Vimeo video id (service 1/2), or an empty string for no video. The
#      real query string a browser sends is `?open&{cachebuster}` --
#      confirmed live 2026-09-14 the server answers identically to a bare
#      `?open`, so no cachebuster is sent here. Every call needs a `Referer`
#      of the tenant's own Public page and a browser User-Agent; without it
#      CloudFront 403s (confirmed live, matches this repo's "politely" rule
#      in CLAUDE.md -- this is compliance with a request-shape check, not
#      circumventing a human-verification gate).
#
# The rest of the fragment is the meeting's agenda outline: each real
# section is an `<li class="category">` heading with no timestamp, each
# real agenda ITEM is a following `<li class="item" ...>` carrying
# `data-videohours`/`data-videominutes`/`data-videoseconds` (a real offset
# into the video) and its text in a nested `<div class="view">`. A meeting
# with no video still returns category headings with NO item rows at all
# (confirmed live: Colorado City's own no-video fragment) -- the spec doc's
# "no times" note was written before this fixture was in hand; it's wrong,
# and this adapter uses the real per-item offsets.
#
# ---------------------------------------------------------------------
# HOUSE RULE -- read before changing anything below: `go.boarddocs.com/
# robots.txt` is `Disallow: /` with `Crawl-delay: 1000`. This adapter
# reads ONE tenant, ONE meeting, ON DEMAND -- exactly what a reader's own
# browser visit would do -- and NEVER enumerates tenants or runs as a
# sweep. Per resolve: 1 tenant-page GET + 1 list GET + at most N
# per-meeting POSTs (N = however many of the newest meetings it takes to
# find one with a video, capped at `_MAX_MEETINGS_WALKED` = 40; a single
# already-known meeting URL costs exactly one POST). No script in this
# repo may call `go.boarddocs.com` in a loop over tenants -- tenant slugs
# come from a government's own site, the research file, or a Wayback
# index, never from probing this host. See BACKLOG_DONE.md's WO-365 entry
# and the investigation doc for the full reasoning and the live evidence
# (2 real tenants with video, 4 confirmed negative controls) this was
# built and tested against.
# ---------------------------------------------------------------------

_HOST = "go.boarddocs.com"

# Tenant path shape confirmed live on all 6 tenants checked:
# `/{st}/{slug}/Board.nsf/...` -- `st`/`slug` are lowercase in every real
# example seen, but this doesn't assume that (lowered explicitly below).
_TENANT_PATH_RE = re.compile(r"^/([A-Za-z0-9]+)/([A-Za-z0-9_-]+)/Board\.nsf(?:/|$)")

_VIDEOSERVICE_RE = re.compile(r'bd\.videoservice\s*=\s*"(\d)"')
_VIDEO_ID_RE = re.compile(r'input\[name=video_id\]"\)\.val\("([^"]*)"\)', re.IGNORECASE)

# BoardDocs' own state prefix -- confirmed NOT always USPS (`fla` for
# Florida). Only entries actually confirmed live belong here (CLAUDE.md's
# "never build from assumption" rule); everything else falls back to
# uppercasing the prefix, which happens to be correct for every other
# real prefix seen so far ("az", "ca", "md", "mo", "tx").
_STATE_PREFIXES: Dict[str, str] = {
    "fla": "FL",
}

# A SiteTitle2/<title> value that's really a mailing address, not an
# organisation name -- confirmed live 2026-09-14 on two of three real
# tenants checked (Colorado City schools' SiteTitle2 is "PO Box 309
# Colorado City, AZ 86021"; Austin ISD's is a street address). Cheap
# heuristic, same shape as legistar.py's own `_looks_like_street_address`:
# a number followed by more text, a PO Box, or a "ST #####" tail.
_ADDRESS_LIKE_RE = re.compile(
    r"\d{1,6}\s+\S|\bP\.?O\.?\s*Box\b|\b[A-Z]{2}\s+\d{5}\b", re.IGNORECASE
)
_TITLE_TAG_SUFFIX_RE = re.compile(r"\s*BoardDocs®?\s*\S*\s*$", re.IGNORECASE)

_MAX_MEETINGS_WALKED = 40

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


def is_boarddocs_tenant_url(url: str) -> bool:
    """True for any `go.boarddocs.com/{st}/{slug}/Board.nsf/...` URL --
    tenant-level (`Public`, `vpublic?open`) or meeting-level
    (`goto?open&id=...`) alike. Used by `detect_platform()`."""
    parsed = urlparse(url)
    if parsed.netloc.lower() != _HOST:
        return False
    return _TENANT_PATH_RE.match(parsed.path) is not None


def _parse_tenant(url: str) -> Optional[Tuple[str, str]]:
    parsed = urlparse(url)
    if parsed.netloc.lower() != _HOST:
        return None
    match = _TENANT_PATH_RE.match(parsed.path)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).lower()


def _extract_meeting_unique(url: str) -> Optional[str]:
    """The `id=` value off a `goto?open&id={Unique}` meeting URL -- the
    query string is genuinely `open&id=...` (no `=` on the first token),
    which `parse_qs` already handles (a bare token with no `=` is simply
    dropped, not raised on, since `strict_parsing` defaults to False)."""
    value = parse_qs(urlparse(url).query).get("id", [None])[0]
    return value or None


class BoardDocsAssetFinder(AssetFinder):
    """BoardDocs (Diligent) -- see this module's own docstring for the
    full live mechanism, the house rule this adapter must never violate,
    and the fixtures/evidence it was built and tested against.

    Delegates the actual video (and, for YouTube, captions) to
    `YouTubeAssetFinder`/`VimeoAssetFinder` the same way `primegov.py`
    does: called directly with THIS module's own meeting URL as
    `source_url`, not via `resolve_via_platform()` -- so "View original
    source" keeps pointing at the real BoardDocs meeting page, and
    `ResolvedMeeting.platform` stays "boarddocs" rather than being
    overwritten by the delegated platform's name.

    No BoardDocs-native captions are claimed anywhere in this file --
    there is no confirmed positive example of BoardDocs hosting its own
    caption track (see the module docstring's citation of the spec doc).
    Captions only ever arrive via the delegated YouTube video, exactly as
    for any other standalone YouTube meeting.
    """

    platform_name = "boarddocs"

    def __init__(self):
        self.headers = {"User-Agent": _USER_AGENT}

    async def resolve(self, url: str) -> ResolvedMeeting:
        tenant = _parse_tenant(url)
        if tenant is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not read a BoardDocs tenant from this URL."],
            )
        st, slug = tenant
        public_url = f"https://{_HOST}/{st}/{slug}/Board.nsf/Public"
        referer_headers = {**self.headers, "Referer": public_url}

        async with aiohttp.ClientSession(headers=self.headers) as session:
            html = await self._fetch_text(session, public_url, referer_headers)
            if html is None:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[
                        "Could not reach this BoardDocs tenant's Public page."
                    ],
                )

            video_service = self._extract_video_service(html)
            org_name = self._extract_org_name(html)
            jurisdiction = self._build_jurisdiction(org_name, st, url)

            if video_service == "0":
                # This tenant's own flag says there's no video service at
                # all -- confirmed live on 3 real negative controls (Seat
                # Pleasant MD, San Bernardino/Vista USD CA). Never worth a
                # single per-meeting POST: the answer is already known.
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    jurisdiction=jurisdiction,
                    video_warnings=[
                        "This BoardDocs tenant has no video service enabled."
                    ],
                    origin_host=urlparse(url).netloc.lower(),
                )

            meetings = await self._fetch_meetings_list(
                session, st, slug, referer_headers
            )
            requested_unique = _extract_meeting_unique(url)

            if requested_unique:
                meta = next(
                    (m for m in meetings if m.get("Unique") == requested_unique),
                    {"Unique": requested_unique},
                )
                candidates = [meta]
            else:
                candidates = self._newest_past_meetings(meetings)

            video_id = None
            chosen_meta: Optional[dict] = None
            fragment_html: Optional[str] = None
            for meta in candidates:
                unique = meta.get("Unique")
                if not unique:
                    continue
                vid, fragment = await self._fetch_video_id(
                    session, st, slug, referer_headers, unique
                )
                if vid:
                    video_id, chosen_meta, fragment_html = vid, meta, fragment
                    break
                if requested_unique:
                    # Only one meeting was ever asked for -- keep its
                    # (video-less) fragment for the agenda outline rather
                    # than treating a genuine "no video" as a fetch
                    # failure.
                    chosen_meta, fragment_html = meta, fragment

            meeting_unique = (chosen_meta or {}).get("Unique") or requested_unique
            meeting_url = (
                f"https://{_HOST}/{st}/{slug}/Board.nsf/goto?open&id={meeting_unique}"
                if meeting_unique
                else url
            )
            agenda_items = _parse_agenda_items(fragment_html) if fragment_html else []
            title, meeting_date = self._extract_meeting_meta(chosen_meta)

            if not video_id:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=meeting_url,
                    jurisdiction=jurisdiction,
                    title=title,
                    date=meeting_date,
                    agenda_items=agenda_items,
                    video_warnings=[
                        "No BoardDocs meeting with a video was found."
                        if not requested_unique
                        else "No video for this BoardDocs meeting."
                    ],
                    origin_host=urlparse(url).netloc.lower(),
                )

            if video_service == "1":
                resolved = await YouTubeAssetFinder.resolve_video_id(
                    video_id, source_url=meeting_url
                )
            elif video_service == "2":
                resolved = await VimeoAssetFinder.resolve_video_id(
                    video_id, source_url=meeting_url, domain_hint=public_url
                )
            else:
                # videoservice "3" (or anything else unmapped) -- no real
                # tenant confirmed live yet, see the module docstring.
                logger.warning(
                    "BoardDocs tenant %s/%s has an unmapped videoservice %r "
                    "with a real video id %r -- returning video-less.",
                    st,
                    slug,
                    video_service,
                    video_id,
                )
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=meeting_url,
                    jurisdiction=jurisdiction,
                    title=title,
                    date=meeting_date,
                    agenda_items=agenda_items,
                    video_warnings=[
                        f"This BoardDocs meeting's video service ({video_service}) "
                        "isn't one we can play yet."
                    ],
                    origin_host=urlparse(url).netloc.lower(),
                )

            # jurisdiction/title/date: prefer this tenant's own real
            # signal, and only backfill from the delegated platform's
            # result where BoardDocs itself found nothing -- same
            # "backfill only" discipline primegov.py's Granicus/Swagit
            # delegation already follows, for the same reason (the
            # delegated platform's own extraction is a worse source for
            # metadata that BoardDocs itself already names cleanly).
            resolved.jurisdiction = jurisdiction or resolved.jurisdiction
            if title:
                resolved.title = title
            if meeting_date:
                resolved.date = meeting_date
            if agenda_items:
                resolved.agenda_items = agenda_items
            # WO-214: keep this tenant's own host as identity evidence
            # even though source_url already carries it (this delegation
            # calls resolve_video_id() directly, not
            # resolve_via_platform(), so source_url/platform are never
            # overwritten the way CivicPlus/Legistar's delegation
            # overwrites them) -- belt-and-braces, matches the brief.
            resolved.origin_host = urlparse(url).netloc.lower()
            return resolved

    async def _fetch_text(
        self, session: aiohttp.ClientSession, url: str, headers: dict
    ) -> Optional[str]:
        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "BoardDocs GET got HTTP %s for %s", response.status, url
                    )
                    return None
                return await response.text()
        except Exception:
            logger.warning("BoardDocs GET failed for %s", url, exc_info=True)
            return None

    async def _fetch_meetings_list(
        self,
        session: aiohttp.ClientSession,
        st: str,
        slug: str,
        headers: dict,
    ) -> List[dict]:
        list_url = f"https://{_HOST}/{st}/{slug}/Board.nsf/BD-GETMeetingsListForSEO"
        html = await self._fetch_text(session, list_url, headers)
        if not html:
            return []
        try:
            import json

            data = json.loads(html)
        except (ValueError, TypeError):
            logger.warning("BoardDocs meetings list wasn't valid JSON for %s", list_url)
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _newest_past_meetings(meetings: List[dict]) -> List[dict]:
        """Newest-first, `Date <= today` (the list includes future
        meetings -- see the module docstring), capped at
        `_MAX_MEETINGS_WALKED` real per-meeting POSTs."""
        today = datetime.now(timezone.utc).date()
        past = []
        for meeting in meetings:
            raw_date = (meeting.get("Date") or "")[:10]
            try:
                meeting_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if meeting_date <= today:
                past.append(meeting)
        return past[:_MAX_MEETINGS_WALKED]

    async def _fetch_video_id(
        self,
        session: aiohttp.ClientSession,
        st: str,
        slug: str,
        headers: dict,
        unique: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        agenda_url = f"https://{_HOST}/{st}/{slug}/Board.nsf/VIDEO-GetAgenda?open"
        try:
            async with session.post(
                agenda_url,
                headers={
                    **headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"id": unique},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "BoardDocs VIDEO-GetAgenda got HTTP %s for %s id=%s",
                        response.status,
                        agenda_url,
                        unique,
                    )
                    return None, None
                fragment = await response.text()
        except Exception:
            logger.warning(
                "BoardDocs VIDEO-GetAgenda failed for %s id=%s",
                agenda_url,
                unique,
                exc_info=True,
            )
            return None, None
        match = _VIDEO_ID_RE.search(fragment)
        video_id = match.group(1) if match else None
        return (video_id or None), fragment

    @staticmethod
    def _extract_video_service(html: str) -> str:
        match = _VIDEOSERVICE_RE.search(html)
        return match.group(1) if match else "0"

    @staticmethod
    def _extract_org_name(html: str) -> Optional[str]:
        """SiteTitle2 when it looks like a real organisation name;
        otherwise the `<title>` tag with its "BoardDocs® {tier}" suffix
        stripped -- see the module-level comment on `_ADDRESS_LIKE_RE`
        for the real, confirmed-live gap this covers (one tenant's
        SiteTitle2 is a mailing address, the other's <title> is)."""
        soup = BeautifulSoup(html, "html.parser")
        site_title_tag = soup.find(id="SiteTitle2")
        site_title = site_title_tag.get_text(strip=True) if site_title_tag else ""
        if site_title and not _ADDRESS_LIKE_RE.search(site_title):
            return site_title
        title_tag = soup.find("title")
        if title_tag:
            stripped = _TITLE_TAG_SUFFIX_RE.sub(
                "", title_tag.get_text(strip=True)
            ).strip()
            if stripped and not _ADDRESS_LIKE_RE.search(stripped):
                return stripped
        return site_title or None

    @staticmethod
    def _build_jurisdiction(
        org_name: Optional[str], st: str, url: str
    ) -> Optional[str]:
        if not org_name:
            return None
        state = _STATE_PREFIXES.get(st, st.upper() if len(st) == 2 else None)
        name = f"{org_name}, {state}" if state else org_name
        return jurisdiction_enrich.enrich_jurisdiction_text(
            name, netloc=urlparse(url).netloc
        )

    @staticmethod
    def _extract_meeting_meta(
        meta: Optional[dict],
    ) -> Tuple[Optional[str], Optional[str]]:
        if not meta:
            return None, None
        title = meta.get("Name") or None
        raw_date = (meta.get("Date") or "")[:10]
        try:
            meeting_date = date.fromisoformat(raw_date).isoformat()
        except ValueError:
            meeting_date = None
        return title, meeting_date


def _parse_agenda_items(fragment_html: str) -> List[TranscriptSegment]:
    """The agenda outline from a real VIDEO-GetAgenda fragment -- each
    `<li class="category">` is a section heading (no timestamp), each
    following `<li class="item" data-videohours=.. data-videominutes=..
    data-videoseconds=..>` is one real, timed agenda item (confirmed live
    2026-09-14 on both real video fixtures). A meeting with no video still
    returns category headings with no item rows at all (confirmed live on
    Colorado City's own no-video meeting) -- this correctly returns an
    empty list for that shape, not an error.

    `end` for each item is the next item's own start (or, for the last
    item, its own start again) -- same "no real end time, use the next
    item's start" convention granicus.py's own `agenda_items` already
    uses.
    """
    soup = BeautifulSoup(fragment_html, "html.parser")
    ordered_list = soup.find("ol")
    if not ordered_list:
        return []
    raw: List[Tuple[float, str]] = []
    current_category: Optional[str] = None
    for li in ordered_list.find_all("li", recursive=False):
        classes = li.get("class") or []
        if "category" in classes:
            current_category = li.get_text(strip=True)
            continue
        if "item" not in classes:
            continue
        hours = li.get("data-videohours") or ""
        minutes = li.get("data-videominutes") or ""
        seconds = li.get("data-videoseconds") or ""
        if not (hours or minutes or seconds):
            continue
        try:
            total_seconds = (
                int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(seconds or 0)
            )
        except ValueError:
            continue
        view = li.find("div", class_="view")
        text = view.get_text(strip=True) if view else li.get_text(strip=True)
        if current_category:
            text = f"{current_category} -- {text}"
        if text:
            raw.append((float(total_seconds), text))
    raw.sort(key=lambda item: item[0])
    items = []
    for i, (start, text) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else start
        items.append(TranscriptSegment(start=start, end=max(end, start), text=text))
    return items
