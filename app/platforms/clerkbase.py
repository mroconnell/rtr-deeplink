import html
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder

# ClerkBase ("ClerkHQ", clerkshq.com) is a hosted agenda/minutes document
# archive for small municipalities -- confirmed live 2026-08-14 on Yellow
# Springs, OH. A URL like `clerkshq.com/YellowSprings-OH?docId=feb07_22ag&
# path=...` is a client-rendered landing page whose *static* HTML (no JS
# execution needed) already embeds the real document location and title as
# plain JS variables:
#   window.autoOpenDocUrl = '/Content/YellowSprings-OH/council/2022/feb07_22ag.htm';
#   window.autoOpenDocTitle = 'February 7, 2022 - Regular Village Council Meeting';
# That `/Content/.../*.htm` document is itself a real page (also directly
# linkable/fetchable on its own, no landing wrapper needed) -- a raw MS
# Word HTML export of the agenda -- which embeds the meeting video as a
# plain `<a href="https://vid.opengovideo.com/playvideo.asp?sFileName=
# https://www.youtube.com/embed/{id}?...">` link. ClerkBase doesn't host
# video itself; "opengovideo.com" is just a redirect/wrapper in front of a
# real YouTube embed -- confirmed live, so this delegates straight to
# YouTubeAssetFinder for video + captions, the same "wrapper platform"
# pattern PrimeGov uses (see primegov.py's own docstring). Real captions
# confirmed present (auto-generated) on the one sample checked so far.
#
# Jurisdiction is derived from the URL itself rather than page text: every
# ClerkBase URL seen so far encodes the client site as a `{Name}-{ST}`
# path segment (e.g. "YellowSprings-OH"), which is a ClerkBase product
# convention (the "client site" identifier), not a per-city guess -- see
# `window.clientSite = 'YellowSprings-OH';` on the landing page. Only
# confirmed against this one real customer, though; unlike jurisdiction,
# no attempt is made here to scrape a title from raw page text when
# `autoOpenDocTitle` isn't present (e.g. a URL that's already the direct
# `/Content/.../*.htm` page) -- the agenda document is a messy Word HTML
# export with no `<title>` tag, and no second real sample has been checked
# yet to know if a reliable pattern exists there.


class ClerkBaseAssetFinder(AssetFinder):
    platform_name = "clerkbase"

    _AUTO_OPEN_URL_RE = re.compile(r"window\.autoOpenDocUrl\s*=\s*'([^']+)'")
    _AUTO_OPEN_TITLE_RE = re.compile(r"window\.autoOpenDocTitle\s*=\s*'([^']+)'")
    _SITE_SLUG_RE = re.compile(r"/([A-Za-z]+)-([A-Z]{2})(?:[/?]|$)")

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            landing_html = await self._get(session, url)

            doc_url_match = self._AUTO_OPEN_URL_RE.search(landing_html)
            title_match = self._AUTO_OPEN_TITLE_RE.search(landing_html)
            title = html.unescape(title_match.group(1)) if title_match else None

            if doc_url_match:
                content_url = urljoin(url, doc_url_match.group(1))
                content_html = await self._get(session, content_url)
            else:
                # Already on the direct document page (no landing wrapper) --
                # confirmed real shape (the third of the three sample URLs
                # checked live for Yellow Springs, OH).
                content_html = landing_html

        jurisdiction = self._extract_jurisdiction(url)

        video_id = YouTubeAssetFinder.extract_video_id(content_html)
        if not video_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                title=title,
                jurisdiction=jurisdiction,
                video_warnings=["No video found on this ClerkBase page."],
                transcript_warnings=["No video found on this ClerkBase page."],
            )

        resolved = await YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)
        # Deliberately not overriding resolved.platform (stays "youtube") --
        # same convention primegov.py already established for this kind of
        # delegation.
        if title:
            resolved.title = title
        if jurisdiction:
            resolved.jurisdiction = jurisdiction
        return resolved

    @staticmethod
    async def _get(session: aiohttp.ClientSession, url: str) -> str:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=20)
        ) as response:
            response.raise_for_status()
            return await response.text()

    @classmethod
    def _extract_jurisdiction(cls, url: str) -> Optional[str]:
        match = cls._SITE_SLUG_RE.search(urlparse(url).path)
        if not match:
            return None
        name, state = match.groups()
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
        return f"{spaced}, {state}"
