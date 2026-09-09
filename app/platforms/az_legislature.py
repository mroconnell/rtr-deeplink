import logging
import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp

from .base import AssetFinder, resolve_via_platform
from .models import ResolvedMeeting

logger = logging.getLogger("rtr_deeplink.az_legislature")

# Arizona State Legislature (azleg.gov) -- found 2026-09-09 while chasing
# WO-102's Invintus prevalence sweep: `clientID` 6361162879 (395 archived
# Wayback captures, sustained real activity 2020-2025, real titles like
# "House Floor Special Session" and "Joint Legislative Oversight Committee
# on the Department of Child Safety" -- Arizona's own DCS agency name)
# turned out, confirmed live, to belong to azleg.gov itself, not a random
# unrelated client -- see `rtr-business/research/ENUMERATION_METHODS.md`
# §102 for the sweep this was found from.
#
# **Unlike every Invintus tenant `invintus.py` was built against, this one
# is reached through a wrapper page, not a direct `player.invintus.com`
# link** -- the same "delegation" shape Legistar/CivicPlus/peg.tv already
# use elsewhere in this repo. `azleg.gov/videoplayer/?eventID={N}`
# (confirmed live, e.g. eventID 2025011041 and a fresh batch of 50 real,
# distinct, current eventIDs on `azleg.gov/archivedmeetings/` running into
# 2026) is a real azleg.gov page whose OWN markup is empty of any real
# title/date (`<title>Video Player</title>`, `<h1>Video Player</h1>` --
# confirmed by fetching and reading the raw HTML) -- all it does is embed
# the Invintus player directly (no iframe) via inline JS:
#   Invintus.launch({'clientID':'6361162879','eventID':'2025011041'});
# So every real field (title, date, video, captions) still comes entirely
# from `InvintusAssetFinder` -- this module's only job is extracting the
# real `clientID`/`eventID` pair from the wrapper page and delegating via
# `resolve_via_platform()`, exactly like Roswell, NM's CivicPlus page
# delegating to `destinyhosted.py`, or NYC Council's Legistar page
# delegating to `viebit.py`.
#
# **Jurisdiction is corrected here, not trusted from Invintus's own
# `categories` field** -- unlike University Place's clean `[jurisdiction,
# body]` pair, AZ Legislature events carry inconsistent, chamber/session-
# code-shaped categories (`["57,1R", "Senate", "Interim Committee",
# "Interim Committee 2025"]`, `["House Majority Press Availability",
# "House Republicans"]`) that would produce a nonsense jurisdiction string
# if used as-is. Since this module's whole scope IS the AZ Legislature,
# the chamber is derived from that same category/title text instead (the
# same "derive from a scoped signal rather than trust an unscoped field"
# reasoning `ca_legislature.py`'s own `chamber = "Senate" if ... else
# "Assembly"` already uses, just from content instead of URL since
# azleg.gov serves both chambers off one shared page family).
#
# **Scope confirmed but NOT yet built**: `/archivedmeetings/` is a real,
# rich listing page (50 distinct real eventIDs on its default view alone,
# current into 2026, with session/committee filter controls) -- the same
# CalendarPageError-shaped "pick a real candidate" opportunity Legistar's
# Calendar.aspx and CivicPlus's AgendaCenter already have adapters for.
# This module only resolves ONE already-known `videoplayer` URL; building
# real pick-list support against the listing page is a distinct, larger
# follow-up left for later, not attempted here.
_CLIENT_EVENT_RE = re.compile(
    r"""Invintus\.launch\(\s*\{\s*['"]clientID['"]\s*:\s*['"](\d+)['"]\s*,\s*"""
    r"""['"]eventID['"]\s*:\s*['"]([A-Za-z0-9]+)['"]""",
)


def is_az_legislature_video_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if not netloc.endswith("azleg.gov") or "/videoplayer" not in path:
        return False
    return bool((parse_qs(urlparse(url).query).get("eventID") or [None])[0])


class ArizonaLegislatureAssetFinder(AssetFinder):
    """Resolves video + captions for an azleg.gov `/videoplayer/?eventID=`
    page by extracting its embedded Invintus clientID/eventID and
    delegating to `InvintusAssetFinder`. See the module docstring above
    for the real investigation this was built against."""

    platform_name = "az_legislature"

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
                f"azleg.gov page: {url}"
            )

        invintus_url = (
            f"https://player.invintus.com/?clientID={client_id}&eventID={event_id}"
        )
        result = await resolve_via_platform(invintus_url)
        result.platform = self.platform_name
        result.source_url = url
        result.external_id = f"az_legislature:{event_id}"
        # Chamber signal, when it exists at all, is spread across
        # Invintus's own title AND its (messy, chamber/session-code-
        # shaped) categories -- already flattened into `jurisdiction`/
        # `meeting_body` by InvintusAssetFinder before this override runs
        # -- so all three are checked together rather than title alone.
        signal = " ".join(
            filter(None, [result.title, result.jurisdiction, result.meeting_body])
        )
        result.jurisdiction = self._derive_jurisdiction(signal)
        return result

    @staticmethod
    def _extract_ids(html: str) -> Tuple[Optional[str], Optional[str]]:
        match = _CLIENT_EVENT_RE.search(html)
        if not match:
            return None, None
        return match.group(1), match.group(2)

    @staticmethod
    def _derive_jurisdiction(title: Optional[str]) -> str:
        lowered = (title or "").lower()
        if "senate" in lowered:
            return "Arizona State Senate"
        if "house" in lowered:
            return "Arizona State House of Representatives"
        return "Arizona State Legislature"
