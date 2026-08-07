import re
from typing import Optional

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder

_VIDEO_URL_VAR_RE = re.compile(r'var\s+videoUrl\s*=\s*"([A-Za-z0-9_-]{11})"')


class PrimeGovAssetFinder(AssetFinder):
    """PrimeGov doesn't host video itself -- confirmed live (LA City's
    portal, lacity.primegov.com) that meeting pages embed a YouTube video
    via the IFrame Player API, with the video id set server-side as a
    plain JS variable: `var videoUrl = "{11-char-YouTube-id}";`, right
    next to a `youtube.com/iframe_api` script tag. Delegates to
    YouTubeAssetFinder once that id is extracted -- same "wrapper
    platform" pattern as Legistar/CivicPlus delegating to Granicus.

    Confirmed the video id is only present on meeting pages that actually
    have a recording (`Portal/Meeting?compiledMeetingDocumentFileId=...`
    URLs, the shape a real shared/indexed meeting link uses) -- an
    agenda-only page reached via `Portal/Meeting?meetingTemplateId=...`
    may have no matching videoUrl at all.

    Unlike Legistar/CivicPlus's delegation (where the final
    ResolvedMeeting.source_url ends up being the delegated platform's
    URL, not what the user pasted -- a known quirk, see BACKLOG.md), this
    calls YouTubeAssetFinder.resolve_video_id() directly with the
    original PrimeGov URL as source_url, so "View original source" keeps
    pointing back to the actual PrimeGov meeting page.
    """

    platform_name = "primegov"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                html = await response.text()

        video_id = self._extract_video_id(html)
        if not video_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["No video found on this PrimeGov page."],
            )

        return await YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)

    @staticmethod
    def _extract_video_id(html: str) -> Optional[str]:
        match = _VIDEO_URL_VAR_RE.search(html)
        return match.group(1) if match else None
