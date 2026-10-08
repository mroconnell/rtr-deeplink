"""SWD Live (swd-live.com) -- council webcasts hosted by Service Web Diffusion (SWD Inc.), Montreal.

Two governments are known on it: Gatineau (`/fr/gatineau/...`) and Mont-Royal (`/fr/mont-royal/...`). SWD is an event-production company; municipal
webcasting is a sideline, and no client list is published. The Wayback index holds 5 addresses for the whole domain, nothing for the API or the
media host (read 2026-10-07/08).

Everything below was read from the real site on 2026-10-08 (Gatineau), never assumed:

* The site is a JavaScript application (Next.js): `https://swd-live.com/<fr|en>/<tenant>/archive` is an empty shell until the page's script runs, and
  a meeting is `/<lang>/<tenant>/archive/<uuid>`. There is no robots.txt (the path answers 200 with the site's own HTML page).
* The page gets its data from a JSON API on `api.swd-live.com`, and the only thing it adds to a plain request is the header
  `X-Tenant-Name: <tenant>` (the first path segment after the language). Without it the API answers HTTP 500.
    - list:   `GET /api/v1/events/list_archived/?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` -> `{"success":true,"data":{"count":N,"results":[...]}}`;
              each result has `id`, `start_time`, `translations.fr.title` / `.en.title` and `category.category_code`
              (council-meeting, executive-committee, committee-of-the-whole, preparatory-caucus, special-session, budget-study).
    - detail: `GET /api/v1/events/<uuid>/` (no `data` wrapper) -> the same plus `vod_blog_url` (the archived video), `streaming_type`
              (the live stream is a Vimeo event; this adapter never touches it), `live_start_time`, `live_end_time`, and `sections[].documents[]`
              (the agenda, a .docx on the same media host).
* The archived video is a plain MP4 on `villeswd.blob.core.windows.net/media/archive/<year>/<mm Month>/...mp4` (public, `Accept-Ranges: bytes`).
* The broadcast window (`live_end_time` - `live_start_time`) is longer than the file: the Sept 1 2026 Gatineau plenary had a 4.42 h window and a 3.88 h
  file; a 4.5-minute file had a 13.7-minute window. So the window is NOT returned as the video length; the queue's length probe measures the file.
* There are no caption files. Every meeting resolves with no segments and a plain warning (Tier 3, our own transcription).
* A listing day with no meeting, or a meeting whose `vod_blog_url` is empty (not yet archived), resolves with a plain warning, never an error.

Politeness: one request at a time, 3 seconds apart, the project User-Agent, and a 429 stops the resolve at once with a plain warning.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting

logger = logging.getLogger("rtr_deeplink.swd_live")

SWD_HOST = "swd-live.com"
API_BASE = "https://api.swd-live.com/api/v1"

# `/<lang>/<tenant>/archive/<uuid>` is one meeting; `/<lang>/<tenant>/archive` is the list; `/broadcast` is the live page (never fetched).
_MEETING_PATH_RE = re.compile(
    r"^/(?P<lang>fr|en)/(?P<tenant>[a-z0-9-]+)/archive/(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
_TENANT_PATH_RE = re.compile(r"^/(?:fr|en)/(?P<tenant>[a-z0-9-]+)(?:/|$)", re.IGNORECASE)
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# Seconds to wait between two requests to swd-live.com / api.swd-live.com (one at a time).
PAUSE_BETWEEN_REQUESTS_SECONDS = 3.0

_USER_AGENT = "RedTapeRecordings/1.0 (+https://redtaperecordings.com)"


class SwdRateLimited(Exception):
    """api.swd-live.com answered 429. Stop; do not retry."""


def is_swd_live_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in (SWD_HOST, f"www.{SWD_HOST}")


def tenant_from_url(url: str) -> Optional[str]:
    """The tenant (the government's slug, e.g. `gatineau`) from any swd-live.com page address, else None."""
    match = _TENANT_PATH_RE.match(urlparse(url).path)
    return match.group("tenant").lower() if match else None


def event_id_from_url(url: str) -> Optional[str]:
    """The meeting uuid from a `/<lang>/<tenant>/archive/<uuid>` address, else None."""
    match = _MEETING_PATH_RE.match(urlparse(url).path)
    return match.group("id").lower() if match else None


def _api_headers(tenant: str) -> dict:
    return {"User-Agent": _USER_AGENT, "Accept": "application/json", "X-Tenant-Name": tenant}


async def _get_json(session: aiohttp.ClientSession, url: str, tenant: str) -> Optional[dict]:
    try:
        async with session.get(url, headers=_api_headers(tenant), timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 429:
                raise SwdRateLimited()
            if response.status != 200:
                logger.warning("swd-live API HTTP %s for %s", response.status, url)
                return None
            return await response.json(content_type=None)
    except SwdRateLimited:
        raise
    except Exception:
        logger.warning("swd-live API fetch failed for %s", url, exc_info=True)
        return None


async def list_archived(tenant: str, from_date: str, to_date: str) -> Optional[List[dict]]:
    """The archived meetings of a tenant between two dates (`YYYY-MM-DD`), newest first as the API gives them; None when the API did not answer.
    Each item: `id`, `start_time`, `translations`, `category`. A walk script pages this by month, one request at a time."""
    url = f"{API_BASE}/events/list_archived/?from_date={from_date}&to_date={to_date}"
    async with aiohttp.ClientSession() as session:
        body = await _get_json(session, url, tenant)
    if not body:
        return None
    return list((body.get("data") or {}).get("results") or [])


def _title(event: dict, lang: str) -> Optional[str]:
    tr = event.get("translations") or {}
    for code in (lang, "fr", "en"):
        title = ((tr.get(code) or {}).get("title") or "").strip()
        if title:
            return title
    return None


def _date(event: dict) -> Optional[str]:
    match = _DATE_RE.match(event.get("start_time") or "")
    return match.group(1) if match else None


class SwdLiveAssetFinder(AssetFinder):
    platform_name = "swd_live"

    async def resolve(self, url: str) -> ResolvedMeeting:
        event_id = event_id_from_url(url)
        tenant = tenant_from_url(url)
        if not event_id or not tenant:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This is a swd-live.com page, but not a single meeting. Open the meeting "
                    "itself (an address ending in /archive/ and a long id) and paste that link."
                ],
            )
        external_id = f"swd_live:{tenant}:{event_id}"
        try:
            async with aiohttp.ClientSession() as session:
                event = await _get_json(session, f"{API_BASE}/events/{event_id}/", tenant)
        except SwdRateLimited:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=external_id,
                video_warnings=["swd-live.com asked us to slow down (HTTP 429), so we stopped. Try again later."],
            )
        if not isinstance(event, dict):
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=external_id,
                video_warnings=["Could not load this swd-live.com meeting."],
            )
        lang = (_MEETING_PATH_RE.match(urlparse(url).path).group("lang") or "fr").lower()
        video_url = (event.get("vod_blog_url") or "").strip() or None
        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=external_id,
            title=_title(event, lang),
            date=_date(event),
            video_channel=f"swd_live:{tenant}",
            video_url=video_url,
            video_format="mp4" if video_url else None,
        )
        if not video_url:
            resolved.video_warnings = [
                "We found this swd-live.com meeting but no archived video yet (it may still be live or not uploaded)."
            ]
        resolved.transcript_warnings.append("No captions found for this video.")
        return resolved
