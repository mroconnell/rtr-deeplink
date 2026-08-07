import re
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment


class CivicClerkAssetFinder(AssetFinder):
    """Resolves video + transcript/chapters for a CivicClerk meeting page.

    CivicClerk portal pages (`<subdomain>.portal.civicclerk.com/event/<id>/media`)
    are a client-rendered SPA with no server HTML to scrape — unlike Granicus,
    there's nothing to BeautifulSoup. Instead it's backed by a clean public REST
    API at `<subdomain>.api.civicclerk.com/v1/...` (found by watching network
    requests in a real browser against clovisca.portal.civicclerk.com), so this
    adapter calls that API directly rather than rendering the page.

    Real API responses observed (2026-08-06) across 3 sample cities:
      - `Events/{id}`: title (eventName), date (eventDate), jurisdiction
        (eventLocation.city/state) — far more reliable than Granicus's
        subdomain-guessing.
      - `EventsMedia/{id}`: `videoUrl` (direct mp4, no HLS involved) or, when
        empty, `externalVideoUrl` pointing to a file hosted on the city's own
        site (seen for Highland, CA — an MP3 audio recording, not video).
        `transcriptionUrl` / `closedCaptionUrl` / `closedCaptionTracks` exist
        in the schema but were null/empty for every sample meeting checked —
        no real example of populated caption data seen yet, so that path is
        unverified (see BACKLOG.md).
      - `EventsMedia.eventBookmarks`: agenda-item markers with `markerTitle`
        and `markerTimeStart` (seconds). Used here as a deep-link fallback
        when there's no real transcript — deep-linking to a moment is this
        app's primary goal, so "no captions" shouldn't mean "no deep links."
    """

    platform_name = "civicclerk"

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        parsed = urlparse(url)
        subdomain = parsed.netloc.split(".")[0]
        api_base = f"https://{subdomain}.api.civicclerk.com/v1"

        match = re.search(r"/event/(\d+)", parsed.path)
        if not match:
            raise ValueError(f"Could not find an event ID in URL path: {parsed.path}")
        event_id = match.group(1)

        async with aiohttp.ClientSession() as session:
            event, media = await self._fetch_json_pair(
                session, f"{api_base}/Events/{event_id}", f"{api_base}/EventsMedia/{event_id}"
            )

        title = event.get("eventName") or None
        date = (event.get("eventDate") or "")[:10] or None
        location = event.get("eventLocation") or {}
        jurisdiction = ", ".join(p for p in (location.get("city"), location.get("state")) if p) or None

        video_url = media.get("videoUrl") or event.get("mediaStreamPath") or event.get("mediaSourcePathMp4")
        if not video_url:
            video_url = media.get("externalVideoUrl") or event.get("externalMediaUrl")
        video_format = None
        if video_url:
            ext = video_url.rsplit(".", 1)[-1].split("?")[0].lower()
            video_format = ext if ext in ("mp4", "mp3", "m3u8", "wav") else None
        if not video_url:
            video_warnings.append("No playable video found for this event.")

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None

        caption_url = media.get("closedCaptionUrl") or media.get("transcriptionUrl")
        if caption_url:
            # Unverified path: no sample meeting in testing had real caption
            # data to confirm the file format (VTT assumed but not observed).
            transcript_warnings.append(
                "A caption/transcript file is referenced for this event but "
                "this adapter hasn't verified that format yet — not rendered."
            )
        else:
            transcript_warnings.append("No caption or transcript data found for this event.")

        # Agenda is fetched independently of whether a real transcript was
        # found -- useful navigation context either way, not just a
        # fallback. Kept in its own field, never folded into `segments`.
        agenda_items: List[TranscriptSegment] = []
        bookmarks = media.get("eventBookmarks") or []
        if bookmarks:
            sorted_marks = sorted(bookmarks, key=lambda b: b.get("markerTimeStart") or 0)
            for i, mark in enumerate(sorted_marks):
                start = float(mark.get("markerTimeStart") or 0)
                end = float(sorted_marks[i + 1].get("markerTimeStart") or start) if i + 1 < len(sorted_marks) else start
                text = mark.get("markerTitle") or mark.get("markerText") or ""
                if text:
                    agenda_items.append(TranscriptSegment(start=start, end=max(end, start), text=text))

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=f"civicclerk:{event_id}",
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            agenda_items=agenda_items,
            transcript_language=transcript_language,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    async def _fetch_json_pair(session: aiohttp.ClientSession, url_a: str, url_b: str):
        async def get(u):
            async with session.get(u, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                resp.raise_for_status()
                return await resp.json()

        import asyncio
        return await asyncio.gather(get(url_a), get(url_b))
