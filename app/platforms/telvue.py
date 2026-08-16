import json
import re
from typing import List, Optional
from urllib.parse import urljoin

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import decode_vtt_bytes, is_likely_garbled, parse_vtt

TARGET_LANGUAGE = "en"

# TelVue -- a real public-access/government-TV video platform (same
# category as Cablecast), found 2026-08-16 not from any enumeration pass
# but from generic_fallback.py already having resolved 2 real customer
# meetings under platform="unknown" (videoplayer.telvue.com), plus a
# third reached via a u.peg.tv shortlink (confirmed live: u.peg.tv/s/{code}
# is a plain HTTP redirect straight to a videoplayer.telvue.com URL, no
# separate platform to support). Confirmed live against a real Ashland,
# OR Planning Commission meeting
# (videoplayer.telvue.com/player/{org_token}/media/{media_id}):
#
# Everything needed is embedded as plain JSON in the static page HTML, no
# JS execution needed -- a `Player.setupData['playlist']` array with one
# entry per video:
#   {"title": "...", "file": "https://.../master.m3u8", "duration": N,
#    "tracks": [{"file": "/closed_captions/{signed-blob}?sha=...",
#                "label": "English", "kind": "captions"},
#               {"file": "/player/media/{media_id}/chapters.vtt",
#                "kind": "chapters"}]}
# The captions track URL is a signed, non-deterministic path -- it must
# be read from this JSON, not constructed. The chapters track URL is
# plain and deterministic (just the media id), but read from the JSON
# anyway rather than reconstructed, in case that ever isn't true for
# another customer.
#
# Real captions confirmed present and high-quality on the one sample
# checked -- a 2h40m meeting with real per-speaker dialogue
# (`<v Speaker N>...</v>` WebVTT voice tags, which parse_vtt() doesn't
# strip on its own -- stripped here via _VOICE_TAG_RE, a TelVue-specific
# concern not yet seen elsewhere in this codebase). Real chapter/agenda
# timestamps also confirmed present via the separate chapters.vtt track,
# a real start/end range per chapter (not point-in-time markers).
#
# Jurisdiction: TelVue's URL path uses an opaque per-customer org token,
# not a readable city name (unlike eScribe's pub-{city} subdomain), and
# no "City of X" phrase was found anywhere in the one sample's HTML --
# best-effort only, extracted from the title's body-name portion (e.g.
# "Ashland Planning Commission" -> "Ashland") when it matches a known
# governance-body-name suffix. Unconfirmed against multiple real
# customers; may need a real per-customer jurisdiction map later the way
# some other adapters already have.
_TITLE_DATE_RE = re.compile(r"^(.*?)\s*-\s*([A-Za-z]+ \d{1,2},? \d{4})$")
_BODY_SUFFIX_RE = re.compile(
    r"^(.*?)\s+(City Council|Council|Planning Commission|Commission|Board|Committee|Authority|District)\b",
    re.I,
)
_VOICE_TAG_RE = re.compile(r"<[^>]+>")


class TelvueAssetFinder(AssetFinder):
    """Resolves video + transcript for a TelVue-hosted meeting page."""

    platform_name = "telvue"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                final_url = str(response.url)
                html = await response.text()

            entry = self._extract_playlist_entry(html)
            if not entry:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=["No video found on this TelVue page."],
                )

            title, date = self._split_title_date(entry.get("title"))
            jurisdiction = self._guess_jurisdiction(title)
            jurisdiction = jurisdiction_enrich.enrich_jurisdiction_text(
                jurisdiction, netloc=None, page_text=html
            )

            video_url = entry.get("file")
            video_format = "m3u8" if video_url and ".m3u8" in video_url else None

            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None
            agenda_items: List[TranscriptSegment] = []

            for track in entry.get("tracks", []):
                track_url = track.get("file")
                if not track_url:
                    continue
                absolute_url = urljoin(final_url, track_url)
                if track.get("kind") == "captions":
                    cues = await self._fetch_vtt(session, absolute_url)
                    if cues:
                        for cue in cues:
                            cue["text"] = _VOICE_TAG_RE.sub("", cue["text"]).replace("\n", " ").strip()
                        cues = [c for c in cues if c["text"]]
                    if cues:
                        segments = [TranscriptSegment(**cue) for cue in cues]
                        transcript_language = TARGET_LANGUAGE
                        if is_likely_garbled(cues):
                            transcript_warnings.append(
                                "This transcript looks garbled at the source (not a parsing "
                                "bug on our end) -- treat it as approximate. You can request "
                                "a transcript from the audio instead."
                            )
                    else:
                        transcript_warnings.append(
                            "This meeting has video but no caption file was found -- "
                            "captioning doesn't appear to have been generated for it yet."
                        )
                elif track.get("kind") == "chapters":
                    cues = await self._fetch_vtt(session, absolute_url)
                    for cue in cues or []:
                        text = cue["text"].strip()
                        if text and text.lower() != "coming up...":
                            agenda_items.append(TranscriptSegment(**{**cue, "text": text}))

            if not video_url:
                video_warnings.append("No video found on this TelVue page.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
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
    def _extract_playlist_entry(html: str) -> Optional[dict]:
        match = re.search(r"Player\.setupData\['playlist'\]\s*=\s*(\[.*?\]);", html, re.S)
        if not match:
            return None
        try:
            playlist = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        return playlist[0] if playlist else None

    @staticmethod
    def _split_title_date(raw_title: Optional[str]):
        if not raw_title:
            return None, None
        match = _TITLE_DATE_RE.match(raw_title.strip())
        if not match:
            return raw_title.strip() or None, None
        title, date_text = match.groups()
        for fmt_text in (date_text, date_text.replace(",", "")):
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    from datetime import datetime

                    return title.strip() or None, datetime.strptime(fmt_text, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return title.strip() or None, None

    @staticmethod
    def _guess_jurisdiction(title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        match = _BODY_SUFFIX_RE.match(title.strip())
        return match.group(1).strip() or None if match else None

    @staticmethod
    async def _fetch_vtt(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(vtt_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200:
                    return None
                raw = await response.read()
        except Exception:
            return None
        content = decode_vtt_bytes(raw)
        cues = parse_vtt(content)
        return cues or None
