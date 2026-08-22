"""Vimeo -- a real, general-purpose video host that a meaningful number of
small local governments use directly as their meeting-video platform,
rather than buying a civic-video vendor product.

Built 2026-08-21 (WO-29). Everything below was confirmed live against
real government meetings before any of it was written, per CLAUDE.md's
"never build a platform adapter from assumption" rule.

## Why this exists at all

Vimeo was already *recognized* here before this adapter -- but only as a
dead end: `generic_fallback.py`'s `_VIMEO_VIDEO_LINK_RE` pointer tier
would say "we think the video is here: <link>" and stop, because nothing
in this app could play a Vimeo video. `detect_platform()` had no Vimeo
case and `app/static/player.js`'s `initVideo()` had no Vimeo branch.
That gap blocked eight separately-confirmed real jurisdictions (see
BACKLOG_DONE.md's WO-29 entry for the full list and how each was found).

## The three real URL shapes, all confirmed live

1. **Channel** -- `vimeo.com/channels/{channel}` (Salisbury NC's
   `coscouncil`), and individual videos under it as either
   `vimeo.com/channels/{channel}/{id}` or a plain `vimeo.com/{id}`.
2. **Showcase** -- `vimeo.com/showcase/{slug-or-id}?video={id}` and
   `vimeo.com/showcase/{slug-or-id}/video/{id}`. Both confirmed real from
   Chicago's ELMS API (`videoLink`), which emits both styles across
   different meetings, and El Paso TX publishes 13 per-body showcases.
3. **Privacy-hashed** -- `vimeo.com/{id}/{hash}` (Sebastopol CA's
   `vimeo.com/1152708575/db9859a2aa`). The hash is required on the embed
   URL (`player.vimeo.com/video/{id}?h={hash}`) or the player refuses.

## What a plain HTTP client CAN get (confirmed live)

`https://vimeo.com/api/oembed.json?url=...` -- Vimeo's public,
unauthenticated oEmbed endpoint -- returns real `title`, `duration`,
`upload_date`, `video_id` and `author_name` for every shape above,
including the privacy-hashed one, from an ordinary `aiohttp` GET. This
is the whole metadata half of the adapter. (It does NOT accept a
showcase URL directly -- `vimeo.com/showcase/citycouncil?video=...`
404s -- so this module always normalizes to `vimeo.com/{id}` first.)

Listing pages (`/showcase/{id}`, `/channels/{name}`) are also plain-
fetchable 200s whose raw HTML embeds a real JSON-LD `ItemList` of
`VideoObject`s (name + url/embedUrl + uploadDate) -- enough for a real
`CalendarPageError` pick-list rather than a bare failure. A bare user
page (`vimeo.com/rocklandmaine`) is NOT: confirmed live to be fully
client-rendered with zero video ids in the raw HTML, so it is
deliberately left to `generic_fallback.py`.

## What a plain HTTP client CANNOT get -- captions and audio

Both live behind the same wall: `player.vimeo.com/video/{id}/config`
returns **403** to a non-browser client (confirmed live), and that
signed config is the only place the signed
`captions.vimeo.com/captions/{id}.vtt?expires=...&sig=...` URL and the
real progressive media file appear. `vimeo.com/{id}` itself sometimes
serves a real Cloudflare "Verify you are human" challenge (hit live on
Spokane) which this app must never attempt to auto-solve.

So: **this adapter is deliberately video-only.** It never claims a
caption path it can't demonstrate, per CLAUDE.md's "don't claim a
caption/data path works without a positive example" rule. Real captions
DO exist on some of these meetings -- confirmed by a real browser on
Salisbury NC (`vimeo.com/1212025580`, a real 7/21/2026 council meeting,
whose Vimeo `getTextTracks()` reports a populated "English
(auto-generated)" track) -- they're just not server-fetchable. Viewers
can still turn them on inside the embedded player itself. On-demand
Whisper transcription is blocked by the *same* wall, not a separate one
(`probe_duration()` needs a real media file); see BACKLOG.md.
"""

import json
import re
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, CalendarCandidate, CalendarPageError
from .models import ResolvedMeeting
from ..utils import jurisdiction_enrich
from ..utils.url_guard import guarded_get, read_capped_text

# Vimeo fronts some page requests with Cloudflare; a modern desktop UA is
# what a real visitor sends. Same scoped-to-this-adapter approach as
# openmedia.py's own UA (not applied app-wide).
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_OEMBED_ENDPOINT = "https://vimeo.com/api/oembed.json?url="

# A Vimeo video id is a plain integer, 6+ digits on every real government
# meeting checked (456202210 .. 1212025580). The privacy hash is a short
# lowercase hex string.
_ID = r"(\d{6,12})"
_HASH = r"([0-9a-f]{6,16})"

_PATH_PATTERNS = (
    # player.vimeo.com/video/{id}
    re.compile(rf"^/video/{_ID}(?:/{_HASH})?/?$"),
    # vimeo.com/showcase/{slug-or-id}/video/{id}
    re.compile(rf"^/showcase/[^/]+/video/{_ID}/?$"),
    # vimeo.com/channels/{channel}/{id}
    re.compile(rf"^/channels/[^/]+/{_ID}/?$"),
    # vimeo.com/groups/{group}/videos/{id}
    re.compile(rf"^/groups/[^/]+/videos/{_ID}/?$"),
    # vimeo.com/{id} and vimeo.com/{id}/{privacy-hash}
    re.compile(rf"^/{_ID}(?:/{_HASH})?/?$"),
)

# A listing page -- many meetings, not one. Only these two shapes are
# claimed: both confirmed live to server-render a real JSON-LD ItemList.
# A bare `vimeo.com/{username}` is deliberately NOT claimed (confirmed
# client-rendered, zero video ids in the raw HTML), which also keeps
# `base.find_platform_link()` from mistaking a city site's
# "vimeo.com/cityname" footer link for a real meeting link -- the same
# false-positive class that made "youtube" an excluded platform there.
_LISTING_PATH_RE = re.compile(r"^/(?:showcase|channels)/[^/]+/?$")

# Real, confirmed meeting-date shapes inside Vimeo video titles. Nothing
# is inferred beyond these three, each taken from a real government
# account: "7/21/2026 City Council Meeting" (Salisbury NC), "Camino Real
# Regional Mobility Authority 5/14/2025" (El Paso TX), "EDITED - City
# Council Meeting - January 6, 2026" (Sebastopol CA), and "2026 July 16 -
# Committee on Budget and Government Operations" (Chicago's own Vimeo
# account -- year first, which matters: without this shape that title
# falls through to Vimeo's upload_date, which is the day BEFORE the real
# meeting on that exact sample).
_MONTH_NAMES = (
    r"January|February|March|April|May|June|July|August|September|October"
    r"|November|December"
)
_TITLE_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
# Same city, same channel, occasional two-digit year -- Salisbury NC's own
# listing really does mix "7/21/2026 City Council Meeting" and "6/2/26
# City Council Meeting" (confirmed live in its channel JSON-LD). Tried
# only after the four-digit shapes, and only ever expanded to 20xx: every
# meeting video on any of these accounts is this century, and a wrong
# guess here would be a wrong date on a public permanent page.
_TITLE_SHORT_YEAR_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b")
_TITLE_MONTH_NAME_DATE_RE = re.compile(
    rf"\b({_MONTH_NAMES})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_TITLE_YEAR_FIRST_DATE_RE = re.compile(
    rf"\b(\d{{4}})\s+({_MONTH_NAMES})\s+(\d{{1,2}})\b",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_NO_CAPTIONS_WARNING = (
    "Vimeo doesn't hand out caption files to anything but its own player, so we "
    "couldn't read a transcript for this meeting. If this video has captions, the "
    "CC button inside the player above will still turn them on."
)


def is_vimeo_host(netloc: str) -> bool:
    netloc = netloc.lower().split(":")[0]
    return netloc in ("vimeo.com", "www.vimeo.com", "player.vimeo.com")


def parse_vimeo_video(url: str) -> Optional[Tuple[str, Optional[str]]]:
    """`(video_id, privacy_hash_or_None)` for any real Vimeo *video* URL
    shape confirmed live, else None. Never matches a listing page, a bare
    user page, or a `/event/{id}` livestream (a different id space that
    `player.vimeo.com/video/{id}` does not accept)."""
    parsed = urlparse(url)
    if not is_vimeo_host(parsed.netloc):
        return None
    path = parsed.path
    query = parse_qs(parsed.query)

    # Showcase pages carry the real video id in `?video=`, e.g. Chicago
    # ELMS's `vimeo.com/showcase/8925576?video=1210310337`.
    if path.lower().startswith("/showcase/"):
        video_param = (query.get("video") or [""])[0]
        if video_param.isdigit():
            return video_param, None

    for pattern in _PATH_PATTERNS:
        match = pattern.match(path)
        if match:
            groups = match.groups()
            video_id = groups[0]
            privacy_hash = groups[1] if len(groups) > 1 else None
            # player.vimeo.com puts the privacy hash in `?h=` rather than
            # the path -- confirmed real on Vimeo's own embed code.
            if not privacy_hash:
                h_param = (query.get("h") or [""])[0].strip().lower()
                if re.fullmatch(_HASH, h_param):
                    privacy_hash = h_param
            return video_id, privacy_hash
    return None


def is_vimeo_listing(url: str) -> bool:
    """True for a showcase/channel listing page (many meetings), which
    `resolve()` answers with a `CalendarPageError` pick-list."""
    parsed = urlparse(url)
    if not is_vimeo_host(parsed.netloc):
        return False
    if parse_vimeo_video(url) is not None:
        return False
    return bool(_LISTING_PATH_RE.match(parsed.path))


def embed_url(video_id: str, privacy_hash: Optional[str] = None) -> str:
    """The player URL `app/static/player.js`'s Vimeo branch embeds. Not a
    media file -- like YouTube's `youtube.com/embed/{id}`, this is an
    iframe page driven by a real cross-frame player API."""
    base = f"https://player.vimeo.com/video/{video_id}"
    return f"{base}?h={privacy_hash}" if privacy_hash else base


def canonical_video_url(video_id: str, privacy_hash: Optional[str] = None) -> str:
    """The `vimeo.com/{id}[/{hash}]` form -- the only shape the public
    oEmbed endpoint accepts (a showcase URL 404s there, confirmed live)."""
    base = f"https://vimeo.com/{video_id}"
    return f"{base}/{privacy_hash}" if privacy_hash else base


def _date_from_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    match = _TITLE_NUMERIC_DATE_RE.search(title)
    if match:
        month, day, year = (int(g) for g in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    match = _TITLE_MONTH_NAME_DATE_RE.search(title)
    if match:
        month = _MONTHS[match.group(1).lower()]
        day, year = int(match.group(2)), int(match.group(3))
        if 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    match = _TITLE_YEAR_FIRST_DATE_RE.search(title)
    if match:
        year = int(match.group(1))
        month = _MONTHS[match.group(2).lower()]
        day = int(match.group(3))
        if 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    match = _TITLE_SHORT_YEAR_DATE_RE.search(title)
    if match:
        month, day, short_year = (int(g) for g in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{2000 + short_year:04d}-{month:02d}-{day:02d}"
    return None


class VimeoAssetFinder(AssetFinder):
    """See this module's docstring for the full live investigation."""

    platform_name = "vimeo"

    async def resolve(self, url: str) -> ResolvedMeeting:
        if is_vimeo_listing(url):
            candidates = await self._listing_candidates(url)
            if candidates:
                raise CalendarPageError(
                    "This is a Vimeo channel/showcase listing many meetings, "
                    "not one specific meeting.",
                    candidates,
                )
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This looks like a Vimeo channel or showcase page, but we "
                    "couldn't read any meetings off it."
                ],
            )

        parsed = parse_vimeo_video(url)
        if parsed is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["We couldn't find a Vimeo video in this link."],
            )

        video_id, privacy_hash = parsed
        return await self.resolve_video_id(
            video_id, privacy_hash=privacy_hash, source_url=url
        )

    @classmethod
    async def resolve_video_id(
        cls,
        video_id: str,
        *,
        privacy_hash: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> ResolvedMeeting:
        """Shared entry point for platforms that WRAP Vimeo rather than
        being Vimeo -- today `chicago_elms.py`, which has a real Vimeo
        `videoLink` from its own API and wants the original ELMS URL kept
        as `source_url` (the PrimeGov/CivicWeb delegation pattern, see
        CLAUDE.md)."""
        oembed = await cls._fetch_oembed(video_id, privacy_hash)

        title = (oembed or {}).get("title") or None
        resolved = ResolvedMeeting(
            platform=cls.platform_name,
            source_url=source_url or canonical_video_url(video_id, privacy_hash),
            external_id=f"vimeo:{video_id}",
            title=title,
            date=_date_from_title(title) or cls._upload_date(oembed),
            jurisdiction=cls._jurisdiction(oembed),
            video_url=embed_url(video_id, privacy_hash),
            video_format="vimeo",
            transcript_warnings=[_NO_CAPTIONS_WARNING],
        )
        if oembed is None:
            # The embed itself still works -- the player fetches its own
            # (signed) config in the browser, which is exactly the request
            # this server can't make. Only the metadata is missing.
            resolved.video_warnings = [
                "We couldn't read this video's details from Vimeo, but the player "
                "above should still work."
            ]
        return resolved

    @staticmethod
    def _upload_date(oembed: Optional[dict]) -> Optional[str]:
        """Vimeo's own `upload_date` ("2026-07-22 10:01:23"), used only
        when the title carries no real meeting date. It's the *upload*
        timestamp -- on every real sample checked that's the meeting day
        or the morning after -- so it's a genuine approximation, not a
        published agenda date. Preferred over no date at all, since the
        Archive sorts and dates every permanent page."""
        raw = (oembed or {}).get("upload_date") or ""
        return raw[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", raw) else None

    @staticmethod
    def _jurisdiction(oembed: Optional[dict]) -> Optional[str]:
        """oEmbed's `author_name` is a Vimeo *account* name, not a
        jurisdiction -- real values range from "City of Sebastopol"
        (usable) through "CitySalisburyNC" / "cityofcorvallis" (glued) to
        "COC" (Chicago's, meaningless out of context). Run through the
        same Census-validated `validated_label_extract()` every other
        adapter uses, which declines rather than guessing -- so most
        Vimeo-direct resolves legitimately carry no jurisdiction at all.
        That's the honest outcome, not a bug: see BACKLOG.md.
        """
        author = ((oembed or {}).get("author_name") or "").strip()
        if not author:
            return None
        label = jurisdiction_enrich.validated_label_extract(author)
        if not label:
            return None
        # `validated_label_extract()` is built for glued subdomain labels,
        # so it title-cases what it returns ("City Of Sebastopol"). When
        # the account name was already real free text that validated
        # as-is, keep the account's own casing ("City of Sebastopol") --
        # these end up on public permanent pages.
        if label.lower() == author.lower():
            label = author
        return jurisdiction_enrich.enrich_jurisdiction_text(label, netloc="vimeo.com")

    @classmethod
    async def _fetch_oembed(
        cls, video_id: str, privacy_hash: Optional[str]
    ) -> Optional[dict]:
        target = canonical_video_url(video_id, privacy_hash)
        body = await cls._fetch(_OEMBED_ENDPOINT + quote(target, safe=""))
        if not body:
            return None
        try:
            payload = json.loads(body)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    async def _listing_candidates(cls, url: str) -> List[CalendarCandidate]:
        """Every showcase/channel listing page checked live server-renders
        a JSON-LD `ItemList` of `VideoObject`s. Read from that structured
        blob rather than by scraping the (client-rendered, class-hashed)
        visible markup."""
        html = await cls._fetch(url)
        if not html:
            return []
        candidates: List[CalendarCandidate] = []
        seen: set[str] = set()
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                blob = json.loads(script.string or "")
            except ValueError:
                continue
            for video in cls._iter_video_objects(blob):
                target = (
                    video.get("url")
                    or video.get("embedUrl")
                    or video.get("embedURL")
                    or ""
                )
                parsed = parse_vimeo_video(target) if target else None
                if not parsed:
                    continue
                video_id, privacy_hash = parsed
                if video_id in seen:
                    continue
                seen.add(video_id)
                title = (video.get("name") or "").strip()
                candidates.append(
                    CalendarCandidate(
                        title=title or f"Vimeo video {video_id}",
                        date=_date_from_title(title)
                        or (video.get("uploadDate") or "")[:10],
                        url=canonical_video_url(video_id, privacy_hash),
                    )
                )
        return candidates

    @classmethod
    def _iter_video_objects(cls, blob):
        """JSON-LD here nests differently between the two listing shapes
        (a showcase's `ItemList.itemListElement[]` holds `VideoObject`s
        directly; a channel's holds `ListItem`s wrapping them in `item`),
        and the top level is sometimes a list of graphs -- so walk the
        whole structure for anything `@type: VideoObject` rather than
        hardcoding either path."""
        if isinstance(blob, list):
            for entry in blob:
                yield from cls._iter_video_objects(entry)
        elif isinstance(blob, dict):
            if blob.get("@type") == "VideoObject":
                yield blob
            for value in blob.values():
                if isinstance(value, (list, dict)):
                    yield from cls._iter_video_objects(value)

    @staticmethod
    async def _fetch(url: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with guarded_get(
                    session, url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        return None
                    return await read_capped_text(response)
        except Exception:
            return None
