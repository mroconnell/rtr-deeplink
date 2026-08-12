import asyncio
import re
from typing import List, Optional, Tuple

import yt_dlp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import decode_vtt_bytes, dedupe_rollup_cues, is_likely_garbled, parse_vtt

TARGET_LANGUAGE = "en"

_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


class YouTubeAssetFinder(AssetFinder):
    """Resolves a standalone YouTube URL -- or a video id handed to it
    directly by a delegating platform (PrimeGov) -- into video + transcript.

    Real, confirmed constraints from live investigation (2026-08-07):
    - There's no direct playable video file URL for YouTube, unlike every
      other platform here. Playback needs an embedded iframe + the
      YouTube IFrame Player API (see player.js's "youtube" video_format
      branch), not the native <video>/hls.js pathway.
    - Caption *content* download is blocked for plain HTTP requests --
      every caption URL YouTube hands out returned 200 OK with 0 bytes
      across 5 different request shapes tried live (aiohttp/curl, with a
      real browser User-Agent, cross-origin fetch, same-origin fetch from
      youtube.com itself, freshly-signed same-session URLs). yt-dlp's own
      request handling works reliably (confirmed against a real
      5985-second LA City Council meeting, 570KB of real captions) -- it
      evidently works around whatever's blocking bare HTTP clients, so
      caption fetching goes through yt-dlp's `urlopen()`, not our own
      aiohttp session.
    - yt-dlp needs to stay reasonably current or extraction may silently
      break -- it's under active, frequent maintenance specifically
      because YouTube keeps changing things to block scraping. Left
      unpinned (latest) in requirements.txt for this reason.
    - YouTube's auto-generated (and, per a real sample, also its manual/
      CC-sourced) VTT uses a "roll-up" cue style, not one cue per line --
      see `dedupe_rollup_cues()` in vtt_parser.py.
    - **yt-dlp can fail entirely** (confirmed live 2026-08-09: YouTube's
      anti-bot check blocking Render's server IP outright, independent
      of which internal client is used) **without losing the video
      itself** -- `resolve_video_id()` degrades to a playable-but-no-
      metadata/no-captions `ResolvedMeeting` rather than raising, since
      embedding only ever needed the video id (a plain string, no
      network call), never yt-dlp. This is also why a delegating
      adapter with its own metadata (`lims.py` parses Minneapolis's own
      agenda page for title/date/jurisdiction, and its own JSON endpoint
      for the video id and real per-item timestamps -- none of that
      touches YouTube at all) still works close to fully even when
      yt-dlp itself is completely blocked -- only the transcript is
      genuinely unavailable in that case.
    """

    platform_name = "youtube"

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        match = _VIDEO_ID_RE.search(url)
        return match.group(1) if match else None

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError(f"Could not find a YouTube video ID in {url}")
        return await self.resolve_video_id(video_id, source_url=url)

    @classmethod
    async def resolve_video_id(cls, video_id: str, source_url: str) -> ResolvedMeeting:
        """Shared entry point for both a direct YouTube URL and a
        delegating platform that already extracted the video id."""
        video_url = f"https://www.youtube.com/embed/{video_id}"

        try:
            info = await asyncio.to_thread(cls._extract_info, video_id)
        except yt_dlp.utils.DownloadError as e:
            # Real production incident, 2026-08-09: YouTube's anti-bot
            # check ("Sign in to confirm you're not a bot") blocks
            # Render's server IP outright, regardless of which internal
            # yt-dlp client is used (confirmed live -- see BACKLOG.md,
            # the player_client workaround in _extract_info() below
            # didn't help). Previously this raised and killed the whole
            # resolve -- but playback itself needs *nothing* from yt-dlp,
            # just this video id (the embed URL above is pure string
            # formatting, no network call) -- the same insight behind
            # this repo's whole "no direct video file URL, playback is
            # always an iframe embed" design. Degrade instead: return a
            # real, playable ResolvedMeeting with no title/date/captions
            # rather than no meeting at all. This also means a delegating
            # adapter with its own metadata (e.g. lims.py's own agenda-
            # page parsing) still gets to use it -- resolve_video_id()
            # failing outright previously threw that away too, even when
            # the caller already had it in hand.
            return ResolvedMeeting(
                platform=cls.platform_name,
                source_url=source_url,
                external_id=f"youtube:{video_id}",
                video_url=video_url,
                video_format="youtube",
                video_warnings=[
                    "YouTube is currently blocking automated caption requests from our server, so "
                    "no transcript is available for this video — but it should still play fine "
                    "above."
                ],
                transcript_warnings=[
                    "No transcript available — YouTube is currently blocking caption requests from "
                    "our server."
                ],
            )
        if not info:
            raise ValueError(f"YouTube video {video_id} could not be resolved (no info returned by yt-dlp).")

        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        # Real bug fixed 2026-08-12: yt-dlp's "upload_date" is consistently
        # one day late for a government meeting streamed live and archived
        # (confirmed on two independent real samples -- Columbus, OH and
        # Oklahoma City, both was_live=True -- see BACKLOG_DONE.md) since it
        # reflects when the VOD finished processing, not when the meeting
        # actually happened. "release_date" (the live broadcast's own start
        # date) matched the real meeting date on both samples instead --
        # preferred here, falling back to upload_date for a plain
        # never-live upload where release_date isn't set at all. This was
        # previously worked around per-adapter (see primegov.py's own page-
        # text date extraction) rather than fixed at the root; this fix
        # benefits every adapter that delegates to YouTubeAssetFinder
        # (direct YouTube URLs, SLC, LIMS, Mesa/Albuquerque's Legistar
        # delegation), not just PrimeGov.
        raw_date = info.get("release_date") or info.get("upload_date")  # YYYYMMDD or None
        date = None
        if raw_date and len(raw_date) == 8:
            date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None

        track = info.get("_chosen_track")
        if track:
            raw_bytes, lang, is_manual = track
            content = decode_vtt_bytes(raw_bytes)
            cues = dedupe_rollup_cues(parse_vtt(content))
            if cues:
                segments = [TranscriptSegment(**c) for c in cues]
                transcript_language = lang
                if lang and lang != TARGET_LANGUAGE:
                    transcript_warnings.append(
                        f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' — "
                        "no matching-language track was found for this video."
                    )
                if not is_manual:
                    transcript_warnings.append(
                        "These are YouTube's auto-generated captions, not a human "
                        "transcript — expect occasional errors, especially with names "
                        "and technical terms."
                    )
                if is_likely_garbled(cues):
                    transcript_warnings.append(
                        "This transcript looks garbled at the source (not a parsing "
                        "bug on our end) — treat it as approximate."
                    )
        if not segments:
            transcript_warnings.append("No captions found on this video.")

        return ResolvedMeeting(
            platform=cls.platform_name,
            source_url=source_url,
            external_id=f"youtube:{video_id}",
            title=info.get("title"),
            date=date,
            jurisdiction=info.get("uploader"),
            video_url=video_url,
            video_format="youtube",
            segments=segments,
            transcript_language=transcript_language,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_info(video_id: str) -> Optional[dict]:
        """Runs in a thread (yt-dlp is synchronous/blocking). Fetches
        metadata and picks the best available caption track, without
        downloading any video/audio."""
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            # Confirmed live 2026-08-09: YouTube's "Sign in to confirm
            # you're not a bot" anti-bot check hit our Render server IP
            # (yt-dlp was already current at the time, 2026.7.4 -- not a
            # stale-extractor issue). That check is tied to yt-dlp's
            # default "web" internal client, which requires a PO token we
            # don't have. android/ios/tv are yt-dlp's other internal
            # clients and have historically not enforced that same check
            # -- try them first, falling back to web only if none of them
            # returns anything usable. Not a guaranteed permanent fix
            # (YouTube tightens this periodically) -- see BACKLOG.md.
            "extractor_args": {"youtube": {"player_client": ["android", "ios", "tv", "web"]}},
            # False (not the original True) so a real failure raises a
            # real yt_dlp.utils.DownloadError instead of silently
            # returning None -- see resolve_video_id's try/except, and
            # BACKLOG.md for why "always guess removed/private/blocked"
            # was wrong.
            "ignoreerrors": False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if not info:
                return None

            result = {
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "upload_date": info.get("upload_date"),
                "release_date": info.get("release_date"),
            }
            chosen = YouTubeAssetFinder._pick_caption_track(ydl, info)
            if chosen:
                result["_chosen_track"] = chosen
            return result

    @staticmethod
    def _pick_caption_track(ydl, info: dict) -> Optional[Tuple[bytes, str, bool]]:
        """Returns (raw_bytes, language_code, is_manual) for the best
        available caption track, or None.

        Prefers a manual (non-ASR) track over auto-generated, but only
        when its coverage is comparable to the auto-generated one --
        confirmed live on a real meeting (LA City Council, 5/19/2021)
        where the "manual" CC track only starts at 18:49 into the video
        (likely a government CART feed that skips pre-meeting dead air),
        while the auto-generated track covers the full video from :01. A
        transcript with a 19-minute unlinkable gap at the start is a
        worse outcome for a deep-link tool than a slightly lower-quality
        but complete one, so manual is only used when it starts within
        60s of the auto-generated track's start.
        """
        manual = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}

        auto_entry = YouTubeAssetFinder._vtt_entry(auto.get(TARGET_LANGUAGE, []))
        manual_key = next((k for k in manual if k.startswith(TARGET_LANGUAGE)), None)
        manual_entry = YouTubeAssetFinder._vtt_entry(manual.get(manual_key, [])) if manual_key else None

        auto_bytes = ydl.urlopen(auto_entry["url"]).read() if auto_entry else None

        if manual_entry:
            manual_bytes = ydl.urlopen(manual_entry["url"]).read()
            if auto_bytes:
                auto_start = YouTubeAssetFinder._first_cue_start(auto_bytes)
                manual_start = YouTubeAssetFinder._first_cue_start(manual_bytes)
                if auto_start is not None and manual_start is not None and manual_start - auto_start > 60:
                    return auto_bytes, TARGET_LANGUAGE, False
            return manual_bytes, TARGET_LANGUAGE, True

        if auto_bytes:
            return auto_bytes, TARGET_LANGUAGE, False

        # No target-language track at all -- fall back to any language,
        # preferring manual.
        for key, entries in manual.items():
            entry = YouTubeAssetFinder._vtt_entry(entries)
            if entry:
                return ydl.urlopen(entry["url"]).read(), key, True
        for key, entries in auto.items():
            entry = YouTubeAssetFinder._vtt_entry(entries)
            if entry:
                return ydl.urlopen(entry["url"]).read(), key, False

        return None

    @staticmethod
    def _vtt_entry(entries: list) -> Optional[dict]:
        return next((e for e in entries if e.get("ext") == "vtt"), None)

    @staticmethod
    def _first_cue_start(raw_bytes: bytes) -> Optional[float]:
        try:
            cues = parse_vtt(decode_vtt_bytes(raw_bytes))
            return cues[0]["start"] if cues else None
        except Exception:
            return None
