import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder, resolve_via_platform
from .models import ResolvedMeeting

logger = logging.getLogger("rtr_deeplink.tvw")


# TVW (tvw.org) -- Washington State's public-affairs network, confirmed
# live 2026-09-22 (WO-1010, following up on WO-1009's Washington/TVW
# recon) to be an Invintus tenant reached through a wrapper page, the same
# delegation shape `az_legislature.py` already documents for azleg.gov --
# NOT a separate video platform of its own.
#
# **Confirmed live against three real, distinct TVW pages**: a real
# `tvw.org/video/{slug}-{eventID}/` page (e.g. `house-agriculture-natural-
# resources-2026091164`, `senate-housing-2026091165`, `joint-oregon-
# washington-legislative-action-committee-2026091156`) is a WordPress page
# running TVW's own "Invintus Player" plugin, and carries the real
# clientID/eventID pair as plain `<meta>` tags in the page `<head>`:
#   <meta name="eventID" content="2026091165">
#   <meta name="clientID" content="9375922947">
# Unlike azleg.gov's inline `Invintus.launch({...})` JS call, TVW's page
# never puts a `player.invintus.com/?clientID=...&eventID=...` URL
# anywhere in its own markup -- the client-side player instead reads
# `invintusConfig = {"clientId":"9375922947"}` (note the different casing
# from the meta tag's `clientID`) and separately loads `player.invintus.
# com/app.js`, so `invintus.py`'s own `extract_invintus_client_id()` --
# built for a `clientID`-shaped key -- does not match this page at all.
# The two `<meta>` tags are the one shape that's actually reliable here,
# confirmed identical across all three real pages fetched.
#
# **Real fields all come from InvintusAssetFinder**, not this wrapper page
# -- confirmed live: clientID 9375922947 is added to `invintus.py`'s
# `LEGISLATURE_CLIENTS` (mapped to `us:state:53`, "Washington State
# Legislature"), and `legislative_chamber()` got a TVW-specific branch,
# since TVW's own `categories`/`categoriesDetail` carry a genuinely clean,
# explicit "Legislative" tag (confirmed on real House/Senate/Joint
# committee events, e.g. `["Legislative", "Senate Housing", "AIR-ON-TV",
# "CABLE-LIVE"]`) -- a stronger, more reliable signal than Oregon's
# title-prefix-only heuristic, and unlike Wisconsin's messier category
# set there is no other TVW-hosted program (Supreme Court, Governor's
# Office, agencies, campaigns, "Inside Olympia") that also carries
# "Legislative" (confirmed against a real 50-row/520-total September 2026
# sample: only real House/Senate/Joint/interim-committee sessions carry
# it). Real captions confirmed live and coherent (Senate Housing,
# 2026-09-17, `captionPath` populated with a real, readable transcript),
# so this is NOT a video-only tenant the way Vimeo is.
def _meta_re(name: str) -> re.Pattern:
    return re.compile(
        rf'<meta\s+name=["\']{name}["\']\s+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )


_CLIENT_ID_META_RE = _meta_re("clientID")
_EVENT_ID_META_RE = _meta_re("eventID")


def is_tvw_video_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    return netloc.endswith("tvw.org") and path.startswith("/video/")


class TVWAssetFinder(AssetFinder):
    """Resolves video + captions for a `tvw.org/video/{slug}/` page by
    extracting its embedded Invintus clientID/eventID `<meta>` tags and
    delegating to `InvintusAssetFinder`. See the module docstring above
    for the real investigation this was built against."""

    platform_name = "tvw"

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                html = await response.text()

        client_id, event_id = self._extract_ids(html)
        if not client_id or not event_id:
            raise ValueError(
                f"Could not find an embedded Invintus clientID/eventID on "
                f"tvw.org page: {url}"
            )

        invintus_url = (
            f"https://player.invintus.com/?clientID={client_id}&eventID={event_id}"
        )
        result = await resolve_via_platform(invintus_url)
        result.platform = self.platform_name
        result.source_url = url
        result.external_id = f"tvw:{event_id}"
        return result

    @staticmethod
    def _extract_ids(html: str) -> Tuple[Optional[str], Optional[str]]:
        client = _CLIENT_ID_META_RE.search(html)
        event = _EVENT_ID_META_RE.search(html)
        return (
            client.group(1) if client else None,
            event.group(1) if event else None,
        )
