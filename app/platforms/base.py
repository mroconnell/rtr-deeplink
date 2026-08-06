from abc import ABC, abstractmethod
from urllib.parse import urlparse

from .models import ResolvedMeeting


class UnsupportedPlatformError(Exception):
    def __init__(self, url: str, detected: str = "unknown"):
        self.url = url
        self.detected = detected
        super().__init__(f"No asset finder for platform '{detected}' ({url})")


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
    if "civicclerk.com" in netloc:
        return "civicclerk"
    if "civicplus.com" in netloc or "civicplus" in netloc:
        return "civicplus"
    if "primegov.com" in netloc:
        return "primegov"
    return "unknown"


_REGISTRY: dict[str, AssetFinder] = {}


def register(finder: AssetFinder) -> None:
    _REGISTRY[finder.platform_name] = finder


def get_finder(platform: str) -> AssetFinder:
    if platform not in _REGISTRY:
        raise UnsupportedPlatformError(url="", detected=platform)
    return _REGISTRY[platform]
