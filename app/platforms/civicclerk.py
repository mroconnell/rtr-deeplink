import re
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    STRUCTURED_CAPTION_PARSERS,
    decode_vtt_bytes,
    detect_language_from_texts,
    is_likely_garbled,
    parse_captions_by_extension,
)

TARGET_LANGUAGE = "en"


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
      - `EventsMedia.eventBookmarks`: agenda-item markers with `markerTitle`
        and `markerTimeStart` (seconds). Used here as a deep-link fallback
        when there's no real transcript — deep-linking to a moment is this
        app's primary goal, so "no captions" shouldn't mean "no deep links."
      - `EventsMedia.closedCaptionUrl` / `.closedCaptionTracks`: real,
        populated caption data — confirmed 2026-08-08 via a real Emporia, KS
        event (id 585, user-supplied example) after three earlier sample
        cities all had these null/empty. The file is **SRT, not VTT**
        (`.closedCaptionTracks[].file` ends in `.srt`) — the first real
        CivicClerk sample with populated captions, so this is the only
        confirmed format; a VTT track has never actually been observed
        here, only assumed possible from the schema.
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

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        alternate_transcripts: List[AlternateTranscript] = []

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

            # Real order confirmed live (Emporia, KS, event 585):
            # closedCaptionUrl and closedCaptionTracks[0].file point at the
            # same file, so a bare closedCaptionUrl alone is enough when
            # there's no tracks array -- but closedCaptionTracks is the
            # richer source when there's more than one language, so it's
            # preferred when present.
            caption_urls = [t["file"] for t in (media.get("closedCaptionTracks") or []) if t.get("file")]
            if not caption_urls:
                fallback = media.get("closedCaptionUrl") or media.get("transcriptionUrl")
                if fallback:
                    caption_urls = [fallback]

            if caption_urls:
                candidates = []  # (url, cues, detected_language) -- structured formats only
                text_fallback_candidates = []  # (url, text) -- no real timing available
                unreadable_urls = []
                for caption_url in caption_urls:
                    cues, fallback_text = await self._fetch_captions(session, caption_url)
                    if cues:
                        candidates.append((caption_url, cues, detect_language_from_texts(c.get("text") for c in cues)))
                    elif fallback_text:
                        text_fallback_candidates.append((caption_url, fallback_text))
                    elif caption_url.lower().split("?")[0].rsplit(".", 1)[-1] not in STRUCTURED_CAPTION_PARSERS:
                        unreadable_urls.append(caption_url)

                target_match = next((c for c in candidates if c[2] == TARGET_LANGUAGE), None)
                chosen = target_match or (candidates[0] if candidates else None)

                if chosen:
                    _url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if lang and lang != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' — "
                            "no matching-language track was found for this meeting."
                        )
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) — treat it as approximate. You can request "
                            "a fresh transcript generated from the audio below."
                        )
                    alternate_transcripts = [
                        AlternateTranscript(language=lang, segments=[TranscriptSegment(**cue) for cue in candidate_cues])
                        for candidate_url, candidate_cues, lang in candidates
                        if candidate_url != _url
                    ]
                elif text_fallback_candidates:
                    # No structured (timed) transcript available, but real
                    # caption text exists in a format with no parser here
                    # -- see Granicus's resolve() for the same reasoning.
                    # Never verified against a real CivicClerk sample in
                    # this format (only .srt has been observed live); see
                    # BACKLOG.md.
                    _url, fallback_text = text_fallback_candidates[0]
                    segments = [
                        TranscriptSegment(start=0.0, end=0.0, text=line)
                        for line in fallback_text.split("\n") if line.strip()
                    ]
                    transcript_warnings.append(
                        "This meeting has captions, but in a format we can only show "
                        "as plain text, not a clickable per-line transcript."
                    )
                elif unreadable_urls:
                    transcript_warnings.append(
                        "This meeting has a caption file, but in a format we can't "
                        f"read at all yet — you can view it directly: {unreadable_urls[0]}"
                    )
                else:
                    transcript_warnings.append(
                        "A caption file is referenced for this event but couldn't be fetched or parsed."
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
            alternate_transcripts=alternate_transcripts,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    async def _fetch_captions(session: aiohttp.ClientSession, caption_url: str):
        """Returns (cues, fallback_text) via parse_captions_by_extension.
        Real confirmed format so far is .srt (Emporia, KS); .vtt is in the
        schema's shape but has never actually been observed either."""
        try:
            async with session.get(caption_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200:
                    return None, None
                raw = await response.read()
        except Exception:
            return None, None
        content = decode_vtt_bytes(raw)
        return parse_captions_by_extension(caption_url, content)

    @staticmethod
    async def _fetch_json_pair(session: aiohttp.ClientSession, url_a: str, url_b: str):
        async def get(u):
            async with session.get(u, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                resp.raise_for_status()
                return await resp.json()

        import asyncio
        return await asyncio.gather(get(url_a), get(url_b))
