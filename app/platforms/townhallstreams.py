import re
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
import wordninja

from .base import AssetFinder
from .models import ResolvedMeeting
from ..utils import jurisdiction_enrich

# townhallstreams.com -- a small, real, live, multi-town government video
# vendor (one meeting per `stream.php?location_id={town}&id={meeting}`
# URL), found by accident 2026-08-19/20, not by any of this repo's usual
# enumeration methods (see BACKLOG.md's own entry for the full discovery
# story -- this docstring covers only what building the adapter itself
# confirmed).
#
# Re-verified live 2026-08-20 (this session) against all 7 of BACKLOG.md's
# sample URLs before writing a single line of parsing code, per this
# repo's "test against a real URL first" rule -- all 7 still resolve.
#
# The page itself carries no jurisdiction- or meeting-identifying text at
# all (confirmed: `<title>` is the generic "Stream Video - Town Hall
# Streams" on every sample, no h1/breadcrumb/meeting name anywhere in the
# HTML) -- every real fact this adapter extracts comes from one place: the
# real HLS video URL embedded in a `jwplayer("myElement").setup({file:
# "..."})` call, e.g.:
#   https://cdn.townhallstreams.com/vod/_definst_/mp4:lisbon_me/
#     2026-07-28_330055_Town_Council_Special_Meeting.mp4/playlist.m3u8
# That URL's own path is a rich, structured metadata source: a
# `{town_slug}` segment, then `{date}_{internal_numeric_id}_{Meeting_
# Title}.mp4` -- confirmed to hold real, human-readable data across all 7
# samples (dates from 2019 through 2026, titles like "Town Council Special
# Meeting", "Planning and Zoning Commission Meeting", "Board of
# Selectmen"; one real edge case, `id 21880`'s title is the single word
# "B" -- left as-is rather than treated as a parse failure, since it's
# genuinely what the source contains).
#
# Confirmed live 2026-08-20: the CDN's `playlist.m3u8` itself has no
# Referer/Origin gating at all (`Access-Control-Allow-Origin: *`, 200 OK
# with or without a browser User-Agent) -- unlike Granicus/Viebit, this
# needs no special headers or iframe workaround. Played natively via
# `video_format="m3u8"`.
#
# **Jurisdiction -- routed through the shared, Census-validated
# `jurisdiction_enrich` pipeline, never a by-eye slug decode.** See
# BACKLOG.md's own investigation: 2 of the 7 real slugs (`newboston`,
# `northgreenbush`) have ZERO state information in them at all, and a
# by-eye guess only got them right via outside knowledge of real town
# names a validator has no way to check. `_extract_jurisdiction()` below
# mirrors `GranicusAssetFinder._humanize_subdomain()`'s already-established
# pattern for this exact "concatenated slug, maybe with a trailing state
# abbreviation" shape: `jurisdiction_enrich.validated_label_extract()`
# gives the validated bare name (declining, e.g. on `oob_maine`, whose
# "oob" isn't a real word/name -- confirmed live), and a separate
# `wordninja.split()` of the same slug independently checks whether its
# OWN last token is a real state abbreviation, since that's real data the
# vendor embedded (not a guess) and `validated_label_extract()` discards
# it once used internally to strip the name. When the slug carries no
# state abbreviation at all, falls back to `resolve_state()`'s
# Census-unambiguous-name lookup as a bonus (confirmed live: this doesn't
# help "New Boston" or "North Greenbush" either -- both are genuinely
# ambiguous nationally -- so both correctly end up state-less rather than
# guessed, matching BACKLOG.md's own conclusion).
#
# Canadian samples: none confirmed yet for this vendor (all 7 known
# samples are US towns) -- scoped to US state abbreviations only, same as
# `GranicusAssetFinder`'s own `US_STATE_ABBREVIATIONS`, until a real
# Canadian customer turns up.
#
# **Transcript: a real AJAX endpoint exists
# (`stream.php?full=1&location_id={X}&id={Y}&action=get_transcriptions`,
# plain GET, no auth) but returned empty on all 7 real samples checked
# (2026-08-19/20 and re-confirmed 2026-08-20)** -- the page's own JS
# (`checkTranscriptions()`) treats an empty/`"1"` response as the normal
# "no captions yet" case, not an error. Its success handler just dumps the
# raw response into a div via `.html(response)` -- confirmed live in the
# page JS that this is a raw HTML fragment, not VTT/SRT/JSON, and NO
# per-cue timestamp shape is visible anywhere in the client code that
# consumes it. Per this repo's "don't claim a data path works without a
# positive example" convention, this adapter does NOT attempt to parse
# that response into timed `TranscriptSegment`s -- there's no confirmed
# real shape to parse, and inventing one would be a guess, not a parse.
# If a real non-empty response is ever seen, `_check_for_transcript()`
# below surfaces it as a `transcript_warnings` entry (rather than
# silently dropping it) so a future session has a real positive example
# to build the actual parser against, instead of this comment being the
# only trace of it.
TARGET_LANGUAGE = "en"

_VIDEO_FILE_RE = re.compile(
    r'file:\s*"(https://cdn\.townhallstreams\.com/vod/[^"]+)"'
)
_FILE_PATH_RE = re.compile(
    r"mp4:(?P<slug>[^/]+)/(?P<date>\d{4}-\d{2}-\d{2})_(?P<num_id>\d+)_(?P<title>[^/]+?)\.mp4"
)

# Same scope/source as GranicusAssetFinder.US_STATE_ABBREVIATIONS -- not
# imported from there since no real Canadian townhallstreams customer is
# confirmed yet to justify reaching for the wider (US+Canada) private sets
# inside jurisdiction_enrich.py.
_US_STATE_ABBREVIATIONS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc",
}


class TownHallStreamsAssetFinder(AssetFinder):
    """Resolves a townhallstreams.com meeting's video (+ best-effort
    transcript check) from the `jwplayer` video URL embedded in its page.
    See the module docstring above for the real investigation this was
    built against."""

    platform_name = "townhallstreams"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        location_id, meeting_id = self._extract_ids(url)

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                html = await response.text()

            match = _VIDEO_FILE_RE.search(html)
            if not match:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[
                        "Could not find Town Hall Streams' video configuration on this page."
                    ],
                )
            video_url = match.group(1)

            path_match = _FILE_PATH_RE.search(video_url)
            town_slug = path_match.group("slug") if path_match else None
            date = path_match.group("date") if path_match else None
            title = (
                path_match.group("title").replace("_", " ").strip()
                if path_match
                else None
            )

            jurisdiction = (
                self._extract_jurisdiction(town_slug) if town_slug else None
            )

            transcript_warnings: List[str] = ["No captions found for this video."]
            if location_id is not None and meeting_id is not None:
                transcript_warnings = await self._check_for_transcript(
                    session, location_id, meeting_id
                )

        external_id = (
            f"townhallstreams:{location_id}:{meeting_id}"
            if location_id is not None and meeting_id is not None
            else None
        )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=external_id,
            title=title,
            jurisdiction=jurisdiction,
            date=date,
            video_url=video_url,
            video_format="m3u8",
            segments=[],
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_ids(url: str) -> Tuple[Optional[str], Optional[str]]:
        query = parse_qs(urlparse(url).query)
        location_id = (query.get("location_id") or [None])[0]
        meeting_id = (query.get("id") or [None])[0]
        return location_id, meeting_id

    @staticmethod
    def _extract_jurisdiction(town_slug: str) -> Optional[str]:
        name = jurisdiction_enrich.validated_label_extract(town_slug)
        if not name:
            return None

        words = wordninja.split(town_slug)
        if words and len(words) > 1 and words[-1].lower() in _US_STATE_ABBREVIATIONS:
            return f"{name}, {words[-1].upper()}"

        state = jurisdiction_enrich.resolve_state(name, "city")
        return f"{name}, {state}" if state else name

    @staticmethod
    async def _check_for_transcript(
        session: aiohttp.ClientSession, location_id: str, meeting_id: str
    ) -> List[str]:
        """Best-effort check of the real (always-empty-so-far) captions
        endpoint -- see the module docstring's transcript section for why
        this never attempts to parse a positive response into segments."""
        query = urlencode(
            {
                "full": "1",
                "location_id": location_id,
                "id": meeting_id,
                "action": "get_transcriptions",
            }
        )
        try:
            async with session.get(
                f"https://townhallstreams.com/stream.php?{query}",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status != 200:
                    return ["No captions found for this video."]
                text = (await response.text()).strip()
        except Exception:
            return ["No captions found for this video."]

        if not text or text == "1":
            return ["No captions found for this video."]

        return [
            "Town Hall Streams may have captions for this meeting, but this "
            "app doesn't yet know how to read that format -- treat this as "
            "no transcript for now."
        ]
