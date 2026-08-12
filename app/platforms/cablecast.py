import json
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting

# Detroit, MI's Cablecast video portal (detroit-vod.cablecast.tv) --
# confirmed live 2026-08-12, found while investigating why an earlier
# Wave 2 research pass's specific sample URL for Detroit was unreachable
# (see BACKLOG.md/BACKLOG_DONE.md for the full dead-end-that-wasn't
# investigation). Real findings this adapter is built on:
#
# - The portal's own HTTPS (port 443) hangs indefinitely for the entire
#   domain (confirmed via direct curl: HTTPS times out at 15s+, plain
#   HTTP responds in under a second) -- Detroit's own city website
#   (detroitmi.gov) links this portal with a plain http:// URL, not
#   https://, matching that reality rather than a mistake. `resolve()`
#   always fetches over HTTP regardless of what scheme was pasted, so a
#   real https:// paste (the more natural thing for someone to type/paste)
#   doesn't hang the whole resolve.
# - A show page (`/internetchannel/show/{id}?site=1`) is a Remix.js
#   (React) SSR app -- all the real data, for the requested show *and* a
#   "related shows" carousel of ~35 others, is embedded as one JSON blob
#   in `window.__remixContext = {...};`. `_find_show()` recursively
#   searches that whole tree for the object whose own `showId` matches
#   the URL's, rather than assuming a fixed key path -- Remix's loader
#   data nesting is keyed by route id, not something worth hardcoding.
# - The real video is a direct, unauthenticated `.m3u8` (HLS) URL on a
#   *different* subdomain (`reflect-detroit-vod.cablecast.tv`, confirmed
#   reachable over HTTPS just fine -- only the portal domain itself hangs)
#   -- already fully supported by this app's existing hls.js pathway
#   (`video_format="m3u8"`), no new frontend work needed.
# - `vodTranscripts` is a real field in the schema but was an empty `[]`
#   on every one of 36 real shows checked on this one page -- per this
#   repo's "don't claim a data path works without a positive example"
#   convention, no extraction is attempted; only whether it's non-empty
#   is checked, so a future real example can be wired in without needing
#   to first prove the field exists.
#
# Deliberately scoped to this specific portal template (Remix-based
# `/internetchannel/show/{id}` pages), not a general "any *.cablecast.tv
# domain" rule -- Charlotte, NC's confirmed Cablecast site
# (charlotte.cablecast.tv) uses a visibly different template (a
# "DOWNLOADS" tab exposing plain `store-N/...-vN/vod.mp4` +
# `transcript.en.txt` files directly, no Remix JSON, HTTPS works fine
# there), so this vendor is not a single uniform shape across customers.
_SHOW_ID_RE = re.compile(r"/internetchannel/show/(\d+)")
_REMIX_CONTEXT_RE = re.compile(r"window\.__remixContext\s*=\s*(\{.*?\});</script>", re.DOTALL)


class CablecastAssetFinder(AssetFinder):
    """Detroit, MI's Cablecast video portal. See module docstring above."""

    platform_name = "cablecast"
    # Confirmed single-jurisdiction so far (only Detroit's portal template
    # has been checked against this shape) -- matches this repo's "narrow
    # fix until real examples exist" convention (see Viebit/SLC/Aurora).
    _JURISDICTION = "Detroit, MI"

    async def resolve(self, url: str) -> ResolvedMeeting:
        show_id = self._extract_show_id(url)
        if show_id is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a show id in this Cablecast URL."],
            )

        fetch_url = self._force_http(url)
        async with aiohttp.ClientSession() as session:
            async with session.get(fetch_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                html = await response.text()

        remix_data = self._extract_remix_context(html)
        show = self._find_show(remix_data, show_id) if remix_data else None

        if not show or not show.get("vodUrl"):
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                jurisdiction=self._JURISDICTION,
                video_warnings=["No video found for this meeting."],
            )

        transcript_warnings = []
        if not show.get("vodTranscripts"):
            transcript_warnings.append("No transcript found for this event.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=show.get("title"),
            date=self._format_date(show.get("eventDate")),
            jurisdiction=self._JURISDICTION,
            video_url=show["vodUrl"],
            video_format="m3u8",
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_show_id(url: str) -> Optional[int]:
        match = _SHOW_ID_RE.search(urlparse(url).path)
        return int(match.group(1)) if match else None

    @staticmethod
    def _force_http(url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(scheme="http").geturl()

    @staticmethod
    def _extract_remix_context(html: str) -> Optional[dict]:
        match = _REMIX_CONTEXT_RE.search(html)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _find_show(obj, show_id: int) -> Optional[dict]:
        if isinstance(obj, dict):
            if obj.get("showId") == show_id:
                return obj
            for value in obj.values():
                found = CablecastAssetFinder._find_show(value, show_id)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = CablecastAssetFinder._find_show(item, show_id)
                if found:
                    return found
        return None

    @staticmethod
    def _format_date(event_date: Optional[str]) -> Optional[str]:
        if not event_date:
            return None
        try:
            return datetime.fromisoformat(event_date).strftime("%Y-%m-%d")
        except ValueError:
            return None
