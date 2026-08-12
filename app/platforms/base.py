from abc import ABC, abstractmethod
from typing import FrozenSet, List, Optional, Tuple, TypedDict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

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
    if "lims.minneapolismn.gov" in netloc:
        # Minneapolis's own "Legislative Information Management System" --
        # confirmed live 2026-08-09 to need a real headless-browser fetch
        # (see headless_browser.py), not the plain aiohttp GET every other
        # adapter here uses. Not yet confirmed whether "LIMS" is a white-
        # labeled product other cities use under different domains -- see
        # BACKLOG.md.
        return "lims"
    if netloc.endswith("slc.gov") and "-meeting-recap" in path:
        # Salt Lake City's own council meeting-recap pages -- confirmed
        # live 2026-08-09 to also need a real headless-browser fetch (same
        # Cloudflare-challenge blocker as Minneapolis LIMS above, a real
        # recurring platform-coverage gap, not two unrelated ones -- see
        # BACKLOG.md). Scoped to the specific "-meeting-recap" path
        # pattern confirmed across four real pages, not the whole
        # slc.gov domain, since most of that site is ordinary city-
        # government content this app has no reason to try to resolve.
        return "slc"
    if "auroratv.org" in netloc:
        # Aurora, CO's own Drupal-built council video site -- confirmed
        # live 2026-08-12, found during a Wave 2 platform-coverage pass
        # (see BACKLOG.md). Plain aiohttp GET works (no Cloudflare
        # challenge like the two cases above), but its underlying video/
        # caption hosts' response to Render's specific cloud IP is
        # genuinely unconfirmed -- see aurora.py's own module docstring.
        return "aurora_tv"
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


_DELEGATABLE_LINK_TAGS = ("a", "iframe", "video", "source")


def find_platform_link(
    html: str, page_url: str, *, exclude: FrozenSet[str] = frozenset()
) -> Optional[Tuple[str, str]]:
    """Scans every <a href>/<iframe src>/<video src>/<source src> on a page
    for a link to a platform `detect_platform()` recognizes, returning
    `(absolute_url, platform)` for the first match, or None.

    Built 2026-08-10 for `generic_fallback.py`'s delegation to an
    already-supported platform found as a plain link (e.g. Austin, TX's
    council pages linking out to their Swagit-hosted video). Reused by
    `legistar.py` for the same real gap on a different page shape:
    Baltimore's Legistar instance puts its video link in an attachments
    table as a plain `<a>Recording</a>` pointing at YouTube, not the
    `a.videolink` shape `_find_video_links()` looks for -- Legistar's own
    adapter claims the domain and gives up before generic_fallback.py ever
    gets a chance to run its own version of this same scan.

    `exclude` matters specifically for "youtube": `detect_platform()`'s
    broad `"youtube.com" in netloc` check also matches a bare channel/user
    link (a real false positive confirmed live on Aurora, CO's "Watch Us
    on YouTube" footer icon) -- callers that already have a tighter,
    video-ID-validated YouTube check of their own (both `generic_fallback.
    py` and `legistar.py` do, via `YouTubeAssetFinder.extract_video_id()`)
    should exclude "youtube" here and rely on that instead.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_DELEGATABLE_LINK_TAGS):
        value = tag.get("href") or tag.get("src")
        if not value:
            continue
        candidate = urljoin(page_url, value.strip())
        platform = detect_platform(candidate)
        if platform == "unknown" or platform in exclude:
            continue
        return candidate, platform
    return None
