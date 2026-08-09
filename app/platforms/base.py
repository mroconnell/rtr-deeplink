from abc import ABC, abstractmethod
from typing import List, TypedDict
from urllib.parse import urlparse

from .models import ResolvedMeeting


class UnsupportedPlatformError(Exception):
    def __init__(self, url: str, detected: str = "unknown"):
        self.url = url
        self.detected = detected
        super().__init__(f"No asset finder for platform '{detected}' ({url})")


class CalendarCandidate(TypedDict):
    title: str
    date: str
    url: str


class CalendarPageError(Exception):
    """Raised when a URL is a calendar/listing page rather than a specific
    meeting -- e.g. Legistar's Calendar.aspx, which lists many meetings each
    with their own video link, rather than one meeting's video. Carries
    enough per-meeting info (title, date, direct URL) for the frontend to
    show the user a pickable list instead of a bare failure.
    """

    def __init__(self, message: str, candidates: List[CalendarCandidate]):
        self.candidates = candidates
        super().__init__(message)


class AssetFinder(ABC):
    """One implementation per civic meeting platform (Granicus, Legistar, ...)."""

    platform_name: str

    @abstractmethod
    async def resolve(self, url: str) -> ResolvedMeeting:
        """Given a meeting URL on this platform, find its video + transcript."""
        raise NotImplementedError


def detect_platform(url: str) -> str:
    """Classify a meeting URL by hosting platform, based on domain/path shape.

    Mirrors the dispatch pattern used by the civic-scraper OSS tool: one
    adapter per platform, not per city, since cities on the same platform
    share the same page structure.
    """
    netloc = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if "granicus.com" in netloc:
        return "granicus"
    if "legistar.com" in netloc:
        return "legistar"
    if "legistar.council.nyc.gov" in netloc:
        # NYC Council runs Legistar on its own nyc.gov domain rather than
        # *.legistar.com -- confirmed live 2026-08-08, real 87-row
        # calendar page, same underlying Legistar software. Hardcoded
        # rather than detecting by page structure since this is the only
        # confirmed custom-domain Legistar instance so far -- see
        # BACKLOG.md and the collect-edge-case-urls memory for why this
        # isn't generalized from one example. NYC's video links use a
        # Telerik JS modal (`onclick="OpenTelerikWindow(...)"`) rather
        # than a plain href/window.open like every other Legistar city --
        # LegistarAssetFinder recognizes that onclick shape too now, and
        # its server-side redirect chain lands on a Viebit URL, delegated
        # to ViebitAssetFinder below.
        return "legistar"
    if "civicclerk.com" in netloc:
        return "civicclerk"
    if "civicplus.com" in netloc or "civicplus" in netloc:
        return "civicplus"
    if "primegov.com" in netloc:
        return "primegov"
    if "swagit.com" in netloc or "swagit-video-player" in path:
        # The swagit.com-domain case covers direct Swagit URLs. The
        # path-based check covers city sites that iframe-embed Swagit at
        # their own domain (e.g. dublin.ca.gov/swagit-video-player) --
        # detection works for these, but SwagitAssetFinder itself hasn't
        # been verified against that embed pattern (no live sample found
        # in testing; see BACKLOG.md).
        return "swagit"
    if "escribemeetings.com" in netloc:
        return "escribe"
    if "assembly.ca.gov" in netloc or "senate.ca.gov" in netloc:
        return "ca_legislature"
    if "youtube.com" in netloc or "youtu.be" in netloc:
        return "youtube"
    if "viebit.com" in netloc:
        # The real video platform underneath NYC Council's Legistar
        # instance, reached by delegation (see the legistar.council.nyc.gov
        # case above) -- confirmed live 2026-08-08. Not yet confirmed
        # whether any city links to Viebit directly rather than through a
        # Legistar wrapper.
        return "viebit"
    return "unknown"


_REGISTRY: dict[str, AssetFinder] = {}


def register(finder: AssetFinder) -> None:
    _REGISTRY[finder.platform_name] = finder


def get_finder(platform: str) -> AssetFinder:
    if platform not in _REGISTRY:
        raise UnsupportedPlatformError(url="", detected=platform)
    return _REGISTRY[platform]


async def resolve_via_platform(url: str) -> ResolvedMeeting:
    """Detect a URL's platform and delegate to its registered finder.

    Used by wrapper platforms like Legistar, which don't host video/captions
    themselves but redirect or link to a platform that does (usually
    Granicus) -- resolving the linked URL should go through that platform's
    real adapter, not be treated as a dead end.
    """
    platform = detect_platform(url)
    finder = get_finder(platform)
    return await finder.resolve(url)
