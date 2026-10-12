import re
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder, resolve_via_platform
from .models import ResolvedMeeting

# CVTV (cvtv.org) -- Clark/Vancouver Television, Washington. Found
# 2026-10-11 (WO-1189). Like tvw.org it is a WordPress site running the
# Invintus plugin, so it is an Invintus tenant reached through a wrapper
# page, not a video platform of its own.
#
# Confirmed live 2026-10-11 on five real `cvtv.org/video/{slug}-{eventID}/`
# pages (Vancouver City Council, Regional Transportation Council, Clark
# County Veterans Advisory Board, Clark County Charter Review Commission
# town hall, a disability awareness celebration). Each page has:
#   <div class="invintus-player" data-eventid="2026101001" data-playerid="832">
#   var invintusConfig = {"clientId":"2917038973","playerPrefID":"832"};
# The clientId is identical on all five. Unlike tvw.org there are no
# <meta> tags, and the page never shows a player.invintus.com link. The
# trailing 10 digits of the path equal data-eventid on all five, so the
# link alone is enough and cvtv.org need not be fetched.
# The public Invintus API (Event/getDetailed) returns the real event for
# client 2917038973 / event 2026101001: "Vancouver City Council (10-05-26)",
# with an MP4, an HLS stream and an audio link (no captions on that one).
CVTV_CLIENT_ID = "2917038973"

_EVENT_ID_IN_PATH_RE = re.compile(r"-(20\d{8})/?$")
_EVENT_ID_ATTR_RE = re.compile(r'data-eventid=["\'](\d+)["\']', re.IGNORECASE)
_CLIENT_ID_JS_RE = re.compile(r'"clientId"\s*:\s*"(\d+)"')


def _event_id_from_url(url: str) -> Optional[str]:
    match = _EVENT_ID_IN_PATH_RE.search(urlparse(url).path)
    return match.group(1) if match else None


def is_cvtv_video_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower().endswith(
        "cvtv.org"
    ) and parsed.path.lower().startswith("/video/")


class CVTVAssetFinder(AssetFinder):
    """Resolves a `cvtv.org/video/{slug}-{eventID}/` page by delegating to
    `InvintusAssetFinder` with CVTV's clientID. See the module comment."""

    platform_name = "cvtv"

    async def resolve(self, url: str) -> ResolvedMeeting:
        event_id = _event_id_from_url(url)
        client_id = CVTV_CLIENT_ID
        if not event_id:
            html = await self._fetch_page(url)
            event_match = _EVENT_ID_ATTR_RE.search(html)
            if not event_match:
                raise ValueError(
                    f"Could not find an Invintus eventID on cvtv.org page: {url}"
                )
            event_id = event_match.group(1)
            client_match = _CLIENT_ID_JS_RE.search(html)
            client_id = client_match.group(1) if client_match else CVTV_CLIENT_ID

        invintus_url = (
            f"https://player.invintus.com/?clientID={client_id}&eventID={event_id}"
        )
        result = await resolve_via_platform(invintus_url)
        result.platform = self.platform_name
        result.source_url = url
        result.external_id = f"cvtv:{event_id}"
        return result

    @staticmethod
    async def _fetch_page(url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                return await response.text()
