import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .media_scan import is_hls_url, scan_media_urls, media_type
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich

logger = logging.getLogger("rtr_deeplink.swagit")
from ..utils.vtt_parser import (
    STRUCTURED_CAPTION_PARSERS,
    decode_vtt_bytes,
    detect_language_from_texts,
    normalize_shouting_caption,
    parse_captions_by_extension,
)

# Rolling time window for grouping #transcript-fragments' word-level
# segments into readable lines -- decided over a fixed word count since
# it naturally adapts to speaking pace (a fast talker gets more words per
# line, a slow one fewer), and over sentence-aware grouping since these
# fragments carry no punctuation at all to key off of. Not derived from
# measured data, just a reasonable reading-line length.
WORD_GROUPING_WINDOW_SECONDS = 4.0


def _group_word_fragments(
    word_segments: List[TranscriptSegment],
    window_seconds: float = WORD_GROUPING_WINDOW_SECONDS,
) -> List[TranscriptSegment]:
    """Merges consecutive single-word segments (as emitted by Swagit's
    #transcript-fragments DOM, one <a data-ts> per word) into multi-word
    lines. A new line starts once the gap between the current group's
    first word and the next word exceeds `window_seconds`. Pure function,
    no I/O -- easy to unit test independent of the DOM-scraping code
    that produces its input.
    """
    if not word_segments:
        return []

    grouped: List[TranscriptSegment] = []
    group_words: List[str] = []
    group_start = word_segments[0].start
    group_end = word_segments[0].end

    for seg in word_segments:
        if group_words and seg.start - group_start > window_seconds:
            grouped.append(
                TranscriptSegment(
                    start=group_start, end=group_end, text=" ".join(group_words)
                )
            )
            group_words = []
            group_start = seg.start
        group_words.append(seg.text)
        group_end = seg.end

    if group_words:
        grouped.append(
            TranscriptSegment(
                start=group_start, end=group_end, text=" ".join(group_words)
            )
        )

    return grouped


# A Swagit meeting page (`/videos/{id}`) that has a generated transcript
# links to a *separate* download endpoint at `/videos/{id}/transcript`,
# confirmed live 2026-08-18 against three real customers on three
# different meetings (huberheightsoh clip 267352, allentx clip 189248,
# amarillotx clip 317100): that endpoint is not another HTML page at all
# -- it's a `Content-Type: text/plain` / `Content-Disposition: attachment`
# download of a real, Swagit-hosted plain-text transcript (voice-to-text
# ASR for huberheightsoh's meeting, "uncorrected Closed Captioning" per
# allentx's own closing disclaimer line -- the provenance varies by
# customer/meeting, always stated in a "* This transcript was ..." line at
# the top and/or bottom). This is what caused the reported bug: pasting
# the `/transcript` URL itself into this app fed that plain-text download
# through the HTML-scraping resolve() path meant for `/videos/{id}` pages
# -- no video markup, no #transcript-fragments DOM, so it silently
# resolved to "no video". Confirmed NOT a same-video-different-view case:
# the two URLs are genuinely different resources (an HTML page vs. a
# plain-text file), so the fix normalizes a `/transcript` URL back to its
# base video page for video/metadata/chapters, and *also* fetches the
# transcript download (from either URL shape) as a real transcript
# source. Every checked meeting that offers one links to it via a plain
# `<a href="/videos/{id}/transcript">` button distinguishable from the
# page's unrelated `href="#transcript"` in-page anchor (confirmed absent
# entirely on a real collincountytx meeting with no generated transcript
# -- so this is genuinely optional per meeting, not skipped on a guess).
_TRANSCRIPT_URL_SUFFIX_RE = re.compile(r"/transcript/?(?:\?.*)?$", re.IGNORECASE)

# Within the downloaded transcript text, a line that is *only* a
# "[HH:MM:SS]" bracket is a real timestamp anchor (observed roughly every
# 5 minutes on all three confirmed examples -- coarse compared to a real
# VTT file, but still a genuine second-offset from the source, not
# fabricated). A line that's bracket-wrapped but isn't a timestamp (e.g.
# "[1. Call to Order]") is an inline agenda-item marker matching the same
# titles already available with real second-offsets via this page's own
# `a.playerControl[data-title]` chapters -- skipped here rather than
# duplicated into agenda_items from lower-resolution text.
_TRANSCRIPT_TIMESTAMP_LINE_RE = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]$")
_TRANSCRIPT_BRACKET_LINE_RE = re.compile(r"^\[.*\]$")

# Real, confirmed-live bug (found 2026-08-19, root-caused 2026-08-21 --
# see BACKLOG.md/BACKLOG_DONE.md): Swagit's `/events/{id}` URL shape is a
# genuinely different page template from `/videos/{id}` -- a *live-event*
# page, not an archived on-demand recording, confirmed by the template's
# own dead error-handler text (see `resolve()`'s comment above
# `media_urls` below for the full writeup). Every one of 5 real tenants
# checked (petalumaca #43607, norwalkca #44163, westjordan #43963,
# cambridgema #43940, solvangca #43961 -- all 5 independently curl-
# verified live, not just the first 3 as BACKLOG.md originally recorded)
# embeds this exact byte-identical dead JS-commented `player.src(...)`
# line crediting a generic Swagit demo/QA recording (tenant "abilenetx")
# that cannot belong to any real customer -- confirmed dead template
# code, not real per-tenant content, since it's inside a `//` JS comment
# that `scan_media_urls`'s generic regex scan (unaware of JS syntax)
# still picks up as a valid HLS candidate.
_SWAGIT_EVENTS_TEMPLATE_PLACEHOLDER_RE = re.compile(
    r"vault01/abilenetx/59d7e173-684b-4da4-9433-50d6e22555f1\.mp4", re.IGNORECASE
)


def _is_swagit_events_template_dead_candidate(url: str) -> bool:
    """True for either of the two non-viable media candidates Swagit's
    `/events/{id}` live-event page template embeds -- see the module-
    level comment above `_SWAGIT_EVENTS_TEMPLATE_PLACEHOLDER_RE` and
    `resolve()`'s own comment for the full live-verified writeup:

    1. The dead, byte-identical-across-every-tenant "abilenetx" demo
       placeholder left in a JS comment (never real content).
    2. The real (uncommented) `player.src(...)` line right below it,
       which points to a genuine per-tenant *live-channel* stream
       (`edge-f.swagit.com/live[-edge]/{tenant}/live-1-a/playlist.m3u8`)
       -- but that's only ever valid while a meeting is actively
       broadcasting: confirmed live, it 404s on all 5 tenants above (all
       real meetings that had already happened by the time they were
       checked), and even when it does work it's a live stream, not an
       archived on-demand recording this app's transcript/deep-link
       model expects.
    """
    if _SWAGIT_EVENTS_TEMPLATE_PLACEHOLDER_RE.search(url):
        return True
    parsed = urlparse(url)
    path = parsed.path.lower()
    return parsed.netloc.lower() == "edge-f.swagit.com" and path.startswith(
        ("/live/", "/live-edge/")
    )


def _parse_swagit_transcript_download(
    text: str,
) -> Tuple[List[TranscriptSegment], List[str]]:
    """Parses the plain-text body of a Swagit `/videos/{id}/transcript`
    download into (segments, source_notes). Pure function, no I/O.

    Groups prose lines under the most recent "[HH:MM:SS]" anchor into one
    multi-line segment per anchor (rather than emitting many
    identically-timestamped micro-segments) since that's the real
    granularity of the source -- confirmed live, timestamps land roughly
    every 5 minutes, not per line or per sentence.
    """
    disclaimers: List[str] = []
    blocks: List[Tuple[float, List[str]]] = []
    current_start = 0.0
    current_lines: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("*"):
            note = line.lstrip("*").strip()
            if note and note not in disclaimers:
                disclaimers.append(note)
            continue
        ts_match = _TRANSCRIPT_TIMESTAMP_LINE_RE.match(line)
        if ts_match:
            if current_lines:
                blocks.append((current_start, current_lines))
                current_lines = []
            hh, mm, ss = (int(g) for g in ts_match.groups())
            current_start = float(hh * 3600 + mm * 60 + ss)
            continue
        if _TRANSCRIPT_BRACKET_LINE_RE.match(line):
            continue
        current_lines.append(line)
    if current_lines:
        blocks.append((current_start, current_lines))

    segments: List[TranscriptSegment] = []
    for i, (start, lines) in enumerate(blocks):
        end = blocks[i + 1][0] if i + 1 < len(blocks) else start
        segments.append(
            TranscriptSegment(start=start, end=max(end, start), text=" ".join(lines))
        )
    return segments, disclaimers


class SwagitAssetFinder(AssetFinder):
    """Resolves video + chapter markers for a Swagit meeting page.

    Swagit pages are server-rendered (unlike CivicClerk's SPA), so this
    reuses the Granicus-style "fetch HTML, scan it" approach rather than an
    API client — but the page structure itself is Swagit-specific:

      - Video: a jwplayer `playlist: [{...,"file":"https://archive-stream.
        granicus.com/.../playlist.m3u8"}]` JSON blob embedded in an inline
        <script> tag. Notably the actual video FILE is served from
        Granicus's own archive-stream CDN (confirmed 2026-08-06 against a
        real League City, TX meeting) — Swagit runs on Granicus's streaming
        infrastructure — but the page around it is entirely different from
        a Granicus page, so it still needs this separate parser. The
        shared `media_scan.scan_media_urls()` regex scan (also used by
        GranicusAssetFinder) picks up the .m3u8/.mp4 URLs from the raw HTML
        without needing to understand the jwplayer JSON structure.
      - Metadata: the <title> tag reliably follows "{Date}, {Title} - {City},
        {State}", e.g. "Jul 28, 2026 Regular Meetings - League City, TX" —
        cleaner and more reliable than Granicus's scraped/guessed metadata.
      - Chapters: `a.playerControl[data-ts][data-title]` elements, server-
        rendered with real agenda-item titles and second-offsets on
        meetings that have them populated (confirmed on a real regular
        meeting; a candidate-forum sample had these present but empty —
        chapter population appears to vary per meeting, same as everywhere
        else in this space). Used as the deep-link fallback exactly like
        CivicClerk's eventBookmarks, since deep-linking to a moment matters
        more here than a full transcript.
      - Real free-text transcript: the page's JS references
        `#transcript-fragments a[data-ts]`, but that container was never
        present in the static HTML for any sample checked — unverified
        whether it's ever server-rendered or requires a separate call; see
        BACKLOG.md. Attempted defensively below and simply yields nothing
        when absent.
      - A genuine, separate transcript resource: `/videos/{id}/transcript`
        (confirmed live 2026-08-18, see `_parse_swagit_transcript_download`
        above) is a real plain-text download, not another HTML page —
        preferred over both #transcript-fragments and the never-yet-seen
        caption-file path below when available, since it's now confirmed
        present across three different customers rather than a single
        sample. A meeting page that has no generated transcript simply
        has no `/transcript` link to find, so this is skipped rather than
        guessed at.
      - `/events/{id}` is a genuinely different, LIVE-event page template
        from `/videos/{id}` above (confirmed live 2026-08-21 against 5
        real tenants — see `_is_swagit_events_template_dead_candidate`'s
        docstring and `resolve()`'s own comment for the full writeup).
        It has no discoverable archived recording at all: its only two
        embedded media candidates are a dead, byte-identical-across-every-
        tenant demo placeholder and a per-tenant live-channel stream that
        404s once the meeting is over. Both are excluded from video
        selection so this never again silently serves the wrong (bogus
        placeholder) video, the way it did before this was found and
        fixed — see BACKLOG_DONE.md.
    """

    platform_name = "swagit"

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

        # Real bug found live 2026-08-18: `/videos/{id}/transcript` is not
        # a view of the same page, it's a distinct plain-text download
        # (see the class docstring and `_parse_swagit_transcript_download`
        # above). Fetching it through this same HTML-scraping path meant
        # for `/videos/{id}` silently resolved to "no video" -- no video
        # markup exists in a plain-text file. Normalize back to the base
        # video page for video/metadata/chapters; the transcript text
        # itself (from whichever URL shape the caller passed) is fetched
        # separately below.
        transcript_url_requested = bool(_TRANSCRIPT_URL_SUFFIX_RE.search(url))
        fetch_url = (
            _TRANSCRIPT_URL_SUFFIX_RE.sub("", url) if transcript_url_requested else url
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(
                fetch_url,
                headers=self.headers,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                final_url = str(response.url)
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        title, date, jurisdiction = self._extract_metadata(soup)
        if not jurisdiction:
            # <title> didn't match the "... - City, ST" shape this
            # adapter's own extraction expects (special-purpose entities:
            # school districts, MPOs, transit/utility authorities -- see
            # BACKLOG.md's "Swagit blank-jurisdiction gap" entry, the
            # highest-volume source of blank jurisdictions in the
            # 2026-08-15 audit). Try the shared chain before giving up.
            jurisdiction = jurisdiction_enrich.extract_jurisdiction_chain(
                page_text=soup.get_text(" ", strip=True), html=html, url=final_url
            )

        # Real bug found live 2026-08-18, confirmed on yolocountyca (clip
        # 324107), whiteplainsny (292830), and others: some Swagit pages
        # embed an early, dead `player.src(...)` fallback pointing at a
        # decommissioned legacy host (`107.178.209.195`, a bare Google
        # Cloud VM with no working HTTP response at all) *before* the
        # real jwplayer `playlist: [...]` JSON blob later in the same
        # page (see this class's own docstring -- the actual video file
        # is always served from Granicus's archive-stream CDN). Both are
        # `.m3u8`-shaped, so the naive "first HLS candidate in document
        # order" scan below picks the dead one. Since every confirmed-
        # working Swagit page resolves to an `archive-stream.granicus.com`
        # URL, prefer any candidate on that host outright, and only fall
        # back to plain document-order scanning when none exists (e.g. a
        # page structure not yet seen).
        media_urls = scan_media_urls(html, final_url)

        # Real, confirmed-live bug (found 2026-08-19, root-caused
        # 2026-08-21): a `/events/{id}` page's own dead template
        # candidates (see `_is_swagit_events_template_dead_candidate`'s
        # docstring for the full writeup) must never be selected as
        # video_url -- the bogus "abilenetx" placeholder is a specific,
        # plausible-looking WRONG video (not just a missing one), and the
        # real per-tenant live-stream URL beneath it is dead 404 for any
        # meeting that isn't currently broadcasting (every real case
        # checked). Filtered out up front so neither can win any of the
        # three selection passes below, the same way the dead legacy-host
        # candidate just above is deprioritized rather than excluded --
        # except this pair has no good candidate to fall back to on the
        # same page, so exclusion (not just deprioritization) is required.
        dead_template_candidates = [
            u for u in media_urls if _is_swagit_events_template_dead_candidate(u)
        ]
        if dead_template_candidates:
            media_urls = [u for u in media_urls if u not in dead_template_candidates]

        video_url, video_format = None, None
        for candidate in media_urls:
            if (
                media_type(candidate) == "video"
                and is_hls_url(candidate)
                and "archive-stream.granicus.com" in candidate
            ):
                video_url, video_format = candidate, "m3u8"
                break
        if not video_url:
            for candidate in media_urls:
                if media_type(candidate) == "video" and is_hls_url(candidate):
                    video_url, video_format = candidate, "m3u8"
                    break
        if not video_url:
            for candidate in media_urls:
                if media_type(candidate) == "video":
                    video_url, video_format = candidate, "mp4"
                    break
        if not video_url:
            if dead_template_candidates:
                # Confirmed live on all 5 tenants above, straight from
                # this Swagit template's own (dead, JS-commented) error
                # handler text: "Our live stream is not currently active.
                # Please check back during a regularly scheduled meeting
                # or view our on-demand content for previously run
                # meetings." -- i.e. Swagit's own template concedes
                # `/events/{id}` is a live-only page and directs viewers
                # elsewhere ("on-demand content") for an archived
                # recording, which this page never itself links to (no
                # `/videos/{id}` or archive-stream.granicus.com reference
                # found on any of the 5 real pages checked).
                video_warnings.append(
                    "This is a Swagit live-event page (`/events/{id}`), not an "
                    "archived on-demand recording -- Swagit's own page confirms "
                    "the live stream isn't currently active, and no archived "
                    "video is linked from this page. If this meeting was later "
                    "archived, look for it under this tenant's /videos/{id} "
                    "page instead."
                )
            else:
                video_warnings.append("No playable video found on this page.")

        segments: List[TranscriptSegment] = []

        # Highest-priority real transcript source: the `/transcript`
        # download endpoint (see class docstring + module-level parsing
        # helpers above). Trust the original URL directly when the caller
        # passed the `/transcript` shape themselves -- no need to re-find
        # the link on the page in that case. Otherwise look for the real
        # download link (`href` ending in "/transcript", distinct from
        # the page's own unrelated `href="#transcript"` in-page anchor)
        # and only fetch it if present, since not every meeting has one.
        transcript_download_url = None
        if transcript_url_requested:
            transcript_download_url = url
        else:
            transcript_link = soup.select_one('a[href$="/transcript"]')
            if transcript_link and transcript_link.get("href"):
                transcript_download_url = urljoin(final_url, transcript_link["href"])

        if transcript_download_url:
            transcript_text = await self._fetch_transcript_download(
                transcript_download_url
            )
            if transcript_text:
                downloaded_segments, source_notes = _parse_swagit_transcript_download(
                    transcript_text
                )
                if downloaded_segments:
                    segments = downloaded_segments
                    for note in source_notes:
                        transcript_warnings.append(f"Transcript source note: {note}")

        fragments = [] if segments else soup.select("#transcript-fragments a[data-ts]")
        if fragments:
            # Confirmed live 2026-08-08 against a real Dublin, CA meeting
            # (clip 372020, 36,085 fragments) -- this DOM path is real,
            # not just a defensive fallback (see the language-detection
            # comment below for the same confirmation).
            word_segments: List[TranscriptSegment] = []
            for a in fragments:
                try:
                    start = float(a.get("data-ts") or 0)
                except ValueError:
                    continue
                text = a.get_text(strip=True)
                if text:
                    word_segments.append(
                        TranscriptSegment(start=start, end=start, text=text)
                    )
            # #transcript-fragments is one DOM element per *word*, each
            # with start == end (a true instant) -- confirmed live on that
            # same Dublin meeting: "GOOD"/"EVENING"/"AND"/"HAPPY"/"NEW"/
            # "YEAR" each rendered as a separate clickable line a fraction
            # of a second apart, unreadable as a transcript. Every other
            # adapter's segments come from real VTT/SRT cues, already
            # authored in multi-word phrases, so this grouping step is
            # Swagit-specific -- only applied to this DOM-fragment path,
            # not the real-caption-file path below (which already has
            # proper multi-word cues; grouping those could incorrectly
            # merge separate real cues together).
            segments = _group_word_fragments(word_segments)

            # Confirmed on that same Dublin meeting: #transcript-fragments
            # text is ALL CAPS ("GOOD EVENING AND HAPPY NEW YEAR"), which
            # reads as shouting once grouped into real lines. Reuses the
            # same shouting-detection + sentence-casing utility Granicus's
            # VTT parsing already uses for the identical real problem (San
            # Francisco's all-caps live captions) rather than inventing a
            # second casing standard -- it only rewrites text when the
            # sample is genuinely ~all-uppercase, so a Swagit deployment
            # that turns out to emit normal-case text (unconfirmed either
            # way, no second sample yet) would pass through untouched.
            cue_dicts = [
                {"start": s.start, "end": s.end, "text": s.text} for s in segments
            ]
            normalize_shouting_caption(cue_dicts)
            for seg, cue in zip(segments, cue_dicts):
                seg.text = cue["text"]

        # A real caption *file* (as opposed to #transcript-fragments' DOM
        # elements above) has never been observed on any Swagit sample
        # either -- every meeting checked only had .m3u8/.mp4 in
        # scan_media_urls's results. Tried anyway now that media_scan.py
        # recognizes a wider set of caption extensions, purely defensive:
        # costs nothing when absent (the common case), and Swagit runs on
        # Granicus's own CDN infrastructure, so a caption file isn't
        # implausible even though none has turned up yet. See BACKLOG.md.
        if not segments:
            caption_urls = [u for u in media_urls if media_type(u) == "subtitle"]
            if caption_urls:
                cues, fallback_text = await self._fetch_captions(caption_urls[0])
                if cues:
                    segments = [TranscriptSegment(**cue) for cue in cues]
                elif fallback_text:
                    segments = [
                        TranscriptSegment(start=0.0, end=0.0, text=line)
                        for line in fallback_text.split("\n")
                        if line.strip()
                    ]
                    transcript_warnings.append(
                        "This meeting has captions, but in a format we can only show "
                        "as plain text, not a clickable per-line transcript."
                    )
                elif (
                    caption_urls[0].lower().split("?")[0].rsplit(".", 1)[-1]
                    not in STRUCTURED_CAPTION_PARSERS
                ):
                    transcript_warnings.append(
                        "This meeting has a caption file, but in a format we can't "
                        f"read at all yet — you can view it directly: {caption_urls[0]}"
                    )

        if not segments:
            transcript_warnings.append("No transcript found for this event.")

        # Never previously detected -- every real segment source above
        # (#transcript-fragments DOM text, a caption file) is real prose,
        # so it's worth running the same content-based detection every
        # other adapter that fetches real transcript text already does.
        # Confirmed live 2026-08-08: a real Dublin CA meeting (clip
        # 372020) had a genuine 36,085-segment English #transcript-fragments
        # transcript -- the first real confirmation that DOM path is ever
        # actually populated (previously unverified, see BACKLOG.md) -- but
        # showed no language at all on the /meetings listing since this was
        # never set, silently masked on the meeting page itself by that
        # page's own `page_lang` "or en" fallback (archive/main.py).
        transcript_language = (
            detect_language_from_texts(s.text for s in segments) if segments else None
        )

        # Chapter markers are fetched independently of whether a real
        # transcript was found -- useful navigation context either way,
        # not just a fallback. Kept in its own field, never folded into
        # `segments`.
        #
        # Swagit's page renders each agenda-item marker in two separate
        # DOM copies (a compact video-index list + a detailed agenda
        # list), both matching this selector with identical (ts, title)
        # -- confirmed on a real League City meeting, which without
        # dedup rendered every chapter twice. Dedup on (start, text).
        agenda_items: List[TranscriptSegment] = []
        chapters = soup.select("a.playerControl[data-ts][data-title]")
        seen = set()
        marks = []
        for a in chapters:
            ts = a.get("data-ts")
            title_attr = a.get("data-title")
            if not ts or not title_attr:
                continue
            try:
                start = float(ts)
            except ValueError:
                continue
            text = title_attr.strip()
            key = (start, text)
            if key in seen:
                continue
            seen.add(key)
            marks.append((start, text))
        marks.sort(key=lambda m: m[0])
        for i, (start, text) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else start
            agenda_items.append(
                TranscriptSegment(start=start, end=max(end, start), text=text)
            )

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
    async def _fetch_transcript_download(transcript_url: str) -> Optional[str]:
        """Fetches the plain-text body of a Swagit `/videos/{id}/transcript`
        download. Opens its own short-lived session, same reasoning as
        `_fetch_captions` below. Real responses report `Content-Length: 0`
        with the actual body sent chunked (confirmed live 2026-08-18) --
        `.text()` handles that correctly, so no special-casing needed here
        beyond not trusting that header."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    transcript_url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Swagit transcript fetch got HTTP %s for %s",
                            response.status,
                            transcript_url,
                        )
                        return None
                    raw = await response.read()
        except Exception:
            logger.warning(
                "Swagit transcript fetch failed for %s",
                transcript_url,
                exc_info=True,
            )
            return None
        return decode_vtt_bytes(raw)

    @staticmethod
    async def _fetch_captions(caption_url: str):
        """Returns (cues, fallback_text) via parse_captions_by_extension.
        Opens its own short-lived session -- unlike Granicus/CA Legislature,
        Swagit's page-fetch session is already closed by the time this
        (new, speculative) path runs."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    caption_url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Swagit caption fetch got HTTP %s for %s",
                            response.status,
                            caption_url,
                        )
                        return None, None
                    raw = await response.read()
        except Exception:
            logger.warning(
                "Swagit caption fetch failed for %s", caption_url, exc_info=True
            )
            return None, None
        content = decode_vtt_bytes(raw)
        return parse_captions_by_extension(caption_url, content)

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup):
        raw_title = soup.title.get_text(strip=True) if soup.title else ""
        raw_title = re.sub(r"\s+", " ", raw_title)
        # "{Date}, {Meeting Title} - {City}, {State}" -- but real bug found
        # live 2026-08-13: some meetings carry an extra "- Revised -" or
        # "- Closed Session -" marker before the city (e.g. "Aug 04, 2026
        # City Council Special Meeting - Revised - Long Beach, CA"). A lazy
        # (.*?) title-part match locks onto the *first* " - " it can make
        # work, and since the marker text itself has no comma, that first
        # split still satisfies the rest of the pattern -- swallowing
        # "Revised - Long Beach" into the city group. A greedy (.*) title
        # match instead backtracks from the end, always landing on the
        # *last* " - " before ", {State}$", which is the real city
        # boundary in every real title shape seen so far (both this one
        # and the plain no-marker case).
        match = re.match(r"^(.*)\s*-\s*([^,]+),\s*([A-Za-z]{2})\s*$", raw_title)
        title, jurisdiction = raw_title or None, None
        date = None
        if match:
            title_part, city, state = match.groups()
            title = title_part.strip() or None
            jurisdiction = f"{city.strip()}, {state.strip()}"
            date_match = re.match(
                r"^([A-Za-z]{3,9}\.?\s+\d{1,2},\s*\d{4})", title_part.strip()
            )
            if date_match:
                for fmt in ("%b %d, %Y", "%B %d, %Y"):
                    try:
                        date = datetime.strptime(
                            date_match.group(1).replace(".", ""), fmt
                        ).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
        return title, date, jurisdiction
