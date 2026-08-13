import asyncio
import json
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import decode_vtt_bytes, detect_language_from_texts, normalize_shouting_caption

TARGET_LANGUAGE = "en"

# Detroit, MI's Cablecast video portal (detroit-vod.cablecast.tv) --
# confirmed live 2026-08-12, found while investigating why an earlier
# Wave 2 research pass's specific sample URL for Detroit was unreachable
# (see BACKLOG.md/BACKLOG_DONE.md for the full dead-end-that-wasn't
# investigation). Real findings this adapter is built on:
#
# - The portal's own HTTPS (port 443) hangs indefinitely for the entire
#   domain (confirmed via direct curl: HTTPS times out at 15s+, plain
#   HTTP responds in under a second) -- Detroit's own city website
#   (detroitmi.gov) links this portal with a plain http:// URL, not
#   https://, matching that reality rather than a mistake. `resolve()`
#   always fetches over HTTP regardless of what scheme was pasted, so a
#   real https:// paste (the more natural thing for someone to type/paste)
#   doesn't hang the whole resolve.
# - A show page (`/internetchannel/show/{id}?site=1`) is a Remix.js
#   (React) SSR app -- all the real data, for the requested show *and* a
#   "related shows" carousel of ~35 others, is embedded as one JSON blob
#   in `window.__remixContext = {...};`. `_find_show()` recursively
#   searches that whole tree for the object whose own `showId` matches
#   the URL's, rather than assuming a fixed key path -- Remix's loader
#   data nesting is keyed by route id, not something worth hardcoding.
# - The real video is a direct, unauthenticated `.m3u8` (HLS) URL on a
#   *different* subdomain (`reflect-detroit-vod.cablecast.tv`, confirmed
#   reachable over HTTPS just fine -- only the portal domain itself hangs)
#   -- already fully supported by this app's existing hls.js pathway
#   (`video_format="m3u8"`), no new frontend work needed.
# - `vodTranscripts` was an empty `[]` on every one of 36 Detroit shows
#   checked originally, but a real, populated, fetchable example was found
#   2026-08-12 on a real Charlotte show (`show/2451`) -- a real
#   `{languageCode, url}` entry pointing at a plain-text transcript file.
#   That file's own shape (confirmed live, not guessed): one real cue per
#   block, `HH:MM:SS,mmm<TAB>ALL CAPS TEXT`, blank-line-separated, real
#   `\r\n` line endings -- NOT SRT (no sequence-number lines, no `-->`
#   end-time range, just a single start timestamp per block) despite the
#   URL's own `.txt` extension, so it's parsed here directly
#   (`_parse_transcript()`) rather than through `vtt_parser.py`'s shared
#   extension-based dispatch -- routing a Cablecast-specific format
#   through that generic `.txt` fallback would also incorrectly capture
#   every OTHER platform's generic plain-text caption fallback. No
#   explicit end time per cue; each cue's end is the next cue's start
#   (same convention Granicus's AgendaViewer.php chapter markers already
#   use for the same "only a start time is given" shape).
#
# Deliberately scoped to this specific portal template (Remix-based
# `/internetchannel/show/{id}` pages), not a general "any *.cablecast.tv
# domain" rule. An early investigation (before Charlotte was confirmed)
# suspected Charlotte's site used a visibly different, non-Remix
# "DOWNLOADS"-tab template -- that suspicion was wrong: Charlotte's real
# `/internetchannel/show/{id}` pages (e.g. show/2451, see the
# vodTranscripts note above) use the exact same Remix template as
# Detroit's, and both are now confirmed handled by this one adapter (see
# CablecastAssetFinder's own docstring). Still scoped to this template
# specifically, not a blanket *.cablecast.tv rule, since Cablecast is a
# multi-tenant product and a still-unconfirmed customer could genuinely
# use a different portal template -- just not Charlotte.
_SHOW_ID_RE = re.compile(r"/internetchannel/show/(\d+)")
_REMIX_CONTEXT_RE = re.compile(r"window\.__remixContext\s*=\s*(\{.*?\});</script>", re.DOTALL)

# Real bug fixed 2026-08-12: this used to be a single hardcoded
# "Detroit, MI" constant applied to *every* Cablecast customer, confirmed
# wrong live on a real Charlotte, NC meeting (resolved everything else
# correctly -- title, date, video -- but jurisdiction was Detroit's).
# site.title turns out to be plain TV-channel branding, not reliably
# city-shaped -- confirmed live on Detroit's real site ("Channel 10", no
# "Detroit" anywhere in it) -- but site.pageDescription's prose names the
# real city on both real customers checked so far: Detroit's opens "The
# City of Detroit's Channel 10 features...", Charlotte's includes "The
# City of Charlotte is committed to...". Tried first; falls back to
# title for a customer whose description doesn't follow this shape.
#
# Single word only, deliberately -- both real customers confirmed so far
# (Detroit, Charlotte) are one-word city names, and title's own trailing
# branding words ("... GOV Channel") would otherwise get greedily pulled
# in as if they were part of a real multi-word city name. Revisit if a
# real multi-word-city customer (e.g. "City of Fountain Valley") turns up.
_JURISDICTION_RE = re.compile(r"\b(?:City|County|Town) of ([A-Z][a-zA-Z]+)\b")

# Cablecast's own page data has no state field anywhere, and no reliable
# domain-based signal either (neither "charlotte.cablecast.tv" nor
# "detroit-vod.cablecast.tv" encodes a state) -- state is filled in via
# jurisdiction_enrich.resolve_state() below, which tries (1) the shared
# confirmed-domain registry (real, necessary here: both "Detroit" and
# "Charlotte" are genuinely ambiguous nationally -- real cities named
# Detroit exist in MI/OR/AL/TX, and Charlotte in NC/MI/IA/TX/TN -- so
# only a confirmed domain, not the bare city name, can safely resolve
# either), then (2) an unambiguous city-name lookup against real US
# Census data, which a future not-yet-confirmed Cablecast customer with a
# nationally-unique city name would get for free with no allowlist entry
# needed at all.


class CablecastAssetFinder(AssetFinder):
    """Detroit, MI and Charlotte, NC's Cablecast video portals (same
    underlying Remix.js template -- see module docstring above and
    `_extract_jurisdiction()` for how the two are told apart)."""

    platform_name = "cablecast"

    async def resolve(self, url: str) -> ResolvedMeeting:
        show_id = self._extract_show_id(url)
        if show_id is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a show id in this Cablecast URL."],
            )

        fetch_url = self._force_http(url)
        async with aiohttp.ClientSession() as session:
            async with session.get(fetch_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                html = await response.text()

        remix_data = self._extract_remix_context(html)
        show = self._find_show(remix_data, show_id) if remix_data else None
        site = self._find_site(remix_data) if remix_data else None
        jurisdiction = self._extract_jurisdiction(site, url) if site else None

        if not show or not show.get("vodUrl"):
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                jurisdiction=jurisdiction,
                video_warnings=["No video found for this meeting."],
            )

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        alternate_transcripts: List[AlternateTranscript] = []
        transcript_warnings = []

        vod_transcripts = show.get("vodTranscripts") or []
        if vod_transcripts:
            async with aiohttp.ClientSession() as session:
                fetched = await asyncio.gather(
                    *(self._fetch_transcript(session, t.get("url")) for t in vod_transcripts if t.get("url")),
                    return_exceptions=True,
                )
            # Same "never trust the source-provided language label" stance
            # every other adapter here takes -- language is re-derived from
            # each track's own real cue text, not the entry's own
            # `languageCode` field.
            candidates = []  # (cues, detected_language)
            for result in fetched:
                if isinstance(result, Exception) or not result:
                    continue
                normalize_shouting_caption(result)
                lang = detect_language_from_texts(c["text"] for c in result)
                candidates.append((result, lang))

            target_match = next((c for c in candidates if c[1] == TARGET_LANGUAGE), None)
            chosen = target_match or (candidates[0] if candidates else None)
            if chosen:
                cues, transcript_language = chosen
                segments = [TranscriptSegment(**cue) for cue in cues]
                if transcript_language and transcript_language != TARGET_LANGUAGE:
                    transcript_warnings.append(
                        f"These captions appear to be in '{transcript_language}', not "
                        f"'{TARGET_LANGUAGE}' — no matching-language track was found for this meeting."
                    )
                alternate_transcripts = [
                    AlternateTranscript(language=lang, segments=[TranscriptSegment(**cue) for cue in cues])
                    for cues, lang in candidates
                    if cues is not chosen[0]
                ]

        if not segments:
            transcript_warnings.append("No transcript found for this event.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=show.get("title"),
            date=self._format_date(show.get("eventDate")),
            jurisdiction=jurisdiction,
            video_url=show["vodUrl"],
            video_format="m3u8",
            segments=segments,
            transcript_language=transcript_language,
            alternate_transcripts=alternate_transcripts,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_show_id(url: str) -> Optional[int]:
        match = _SHOW_ID_RE.search(urlparse(url).path)
        return int(match.group(1)) if match else None

    @staticmethod
    def _force_http(url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(scheme="http").geturl()

    @staticmethod
    def _extract_remix_context(html: str) -> Optional[dict]:
        match = _REMIX_CONTEXT_RE.search(html)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _find_show(obj, show_id: int) -> Optional[dict]:
        if isinstance(obj, dict):
            if obj.get("showId") == show_id:
                return obj
            for value in obj.values():
                found = CablecastAssetFinder._find_show(value, show_id)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = CablecastAssetFinder._find_show(item, show_id)
                if found:
                    return found
        return None

    @staticmethod
    def _find_site(obj) -> Optional[dict]:
        """Same recursive-search shape as `_find_show()` (Remix's loader
        data nesting is keyed by route id, not a fixed path -- see
        `_find_show()`'s own docstring). Matched on `siteId` *and*
        `pageDescription` together, not `siteId` alone -- confirmed real
        pages also carry many small `{siteId, title: None}` decoys nested
        under each show's own `upcomingRuns` list, which would otherwise
        match first and never reach the real top-level site object.
        """
        if isinstance(obj, dict):
            if "siteId" in obj and "pageDescription" in obj:
                return obj
            for value in obj.values():
                found = CablecastAssetFinder._find_site(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = CablecastAssetFinder._find_site(item)
                if found:
                    return found
        return None

    @staticmethod
    def _extract_jurisdiction(site: dict, url: str) -> Optional[str]:
        page_description = site.get("pageDescription")
        for text in (page_description, site.get("title")):
            if not text:
                continue
            match = _JURISDICTION_RE.search(text)
            if match:
                city = match.group(1).strip()
                state = jurisdiction_enrich.resolve_state(
                    city, "city", netloc=urlparse(url).netloc, page_text=page_description
                )
                return f"{city}, {state}" if state else city
        return None

    @staticmethod
    async def _fetch_transcript(session: aiohttp.ClientSession, transcript_url: str) -> Optional[List[dict]]:
        try:
            async with session.get(transcript_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200:
                    return None
                raw = await response.read()
        except Exception:
            return None
        cues = CablecastAssetFinder._parse_transcript(decode_vtt_bytes(raw))
        return cues or None

    _CUE_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\t(.+)$")

    @staticmethod
    def _parse_transcript(content: str) -> List[dict]:
        """See the module docstring's `vodTranscripts` note for the real
        confirmed shape this parses -- one real cue per line
        (`HH:MM:SS,mmm<TAB>TEXT`), blank-line-separated, no explicit end
        time. Each cue's end is the next cue's start; the last cue's end
        equals its own start (same "no better answer available" fallback
        Granicus's AgendaViewer.php chapter markers already use).
        """
        raw_cues = []
        for line in content.splitlines():
            match = CablecastAssetFinder._CUE_RE.match(line.strip())
            if not match:
                continue
            h, m, s, ms, text = match.groups()
            start = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            text = text.strip()
            if text:
                raw_cues.append((start, text))

        cues = []
        for i, (start, text) in enumerate(raw_cues):
            end = raw_cues[i + 1][0] if i + 1 < len(raw_cues) else start
            cues.append({"start": start, "end": max(end, start), "text": text})
        return cues

    @staticmethod
    def _format_date(event_date: Optional[str]) -> Optional[str]:
        if not event_date:
            return None
        try:
            return datetime.fromisoformat(event_date).strftime("%Y-%m-%d")
        except ValueError:
            return None
