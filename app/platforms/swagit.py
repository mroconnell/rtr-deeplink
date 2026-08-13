import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .media_scan import scan_media_urls, media_type
from .models import ResolvedMeeting, TranscriptSegment
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
    word_segments: List[TranscriptSegment], window_seconds: float = WORD_GROUPING_WINDOW_SECONDS
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
            grouped.append(TranscriptSegment(start=group_start, end=group_end, text=" ".join(group_words)))
            group_words = []
            group_start = seg.start
        group_words.append(seg.text)
        group_end = seg.end

    if group_words:
        grouped.append(TranscriptSegment(start=group_start, end=group_end, text=" ".join(group_words)))

    return grouped


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

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=self.headers, allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                final_url = str(response.url)
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        title, date, jurisdiction = self._extract_metadata(soup)

        media_urls = scan_media_urls(html, final_url)
        video_url, video_format = None, None
        for candidate in media_urls:
            if media_type(candidate) == "video" and candidate.lower().endswith(".m3u8"):
                video_url, video_format = candidate, "m3u8"
                break
        if not video_url:
            for candidate in media_urls:
                if media_type(candidate) == "video":
                    video_url, video_format = candidate, "mp4"
                    break
        if not video_url:
            video_warnings.append("No playable video found on this page.")

        segments: List[TranscriptSegment] = []

        fragments = soup.select("#transcript-fragments a[data-ts]")
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
                    word_segments.append(TranscriptSegment(start=start, end=start, text=text))
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
            cue_dicts = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
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
                        for line in fallback_text.split("\n") if line.strip()
                    ]
                    transcript_warnings.append(
                        "This meeting has captions, but in a format we can only show "
                        "as plain text, not a clickable per-line transcript."
                    )
                elif caption_urls[0].lower().split("?")[0].rsplit(".", 1)[-1] not in STRUCTURED_CAPTION_PARSERS:
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
        transcript_language = detect_language_from_texts(s.text for s in segments) if segments else None

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
            agenda_items.append(TranscriptSegment(start=start, end=max(end, start), text=text))

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
    async def _fetch_captions(caption_url: str):
        """Returns (cues, fallback_text) via parse_captions_by_extension.
        Opens its own short-lived session -- unlike Granicus/CA Legislature,
        Swagit's page-fetch session is already closed by the time this
        (new, speculative) path runs."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(caption_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                    if response.status != 200:
                        return None, None
                    raw = await response.read()
        except Exception:
            return None, None
        content = decode_vtt_bytes(raw)
        return parse_captions_by_extension(caption_url, content)

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup):
        raw_title = soup.title.get_text(strip=True) if soup.title else ""
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
                        date = datetime.strptime(date_match.group(1).replace(".", ""), fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
        return title, date, jurisdiction
