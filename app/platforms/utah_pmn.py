"""Utah's Public Notice Website (`utah.gov/pmn`) -- the state's statutory
Open and Public Meetings Act notice board. Every Utah government type
(State Agency, County, Municipality, Special Service District, Public
School, College or University, Interlocal, Judicial Branch, Associations
of Government, Independent/Quasi-Government, Local District) is legally
required to post its meeting notices here. Confirmed live 2026-09-08
against a real 30-day-then-6-month statewide pilot
(`scripts/pmn_utah_pilot.py`, `rtr-business/research/
ENUMERATION_METHODS.md` §105) -- see that section for how this was found
and measured before this adapter was built; this docstring covers only
what the adapter itself needs.

A notice detail page (`utah.gov/pmn/sitemap/notice/{id}.html`) is plain
server-rendered HTML -- no JS execution, no cookies, no CSRF needed for a
GET (unlike the search/enumeration endpoints the pilot script used) --
with a real `<dt>label</dt><dd>value</dd>` structure carrying
self-reported, ground-truth Government Type / Entity / Public Body /
Notice Title / Event Start Date fields, plus a `Download Attachments`
table (File Name / Category / Date Added columns).

TWO REAL MEDIA SHAPES, confirmed live from the pilot's actual data:

1. A separate "Audio File Address" section with an `Audio File Location`
   field whose value is a link OFF utah.gov -- most commonly YouTube,
   sometimes Vimeo/CivicClerk/Granicus/etc. PMN doesn't host this video
   itself, it just links to it -- same "wrapper platform" pattern this
   project already uses for Legistar/CivicPlus (-> Granicus), PrimeGov/
   CivicWeb/ClerkBase (-> YouTube): delegate to whatever
   `detect_platform()` says the linked URL actually is, via
   `resolve_via_platform()`, then override jurisdiction/meeting_body/
   title/date with PMN's own ground-truth fields (the known-identity-
   override pattern from `ENUMERATION_METHODS.md`'s §98) -- a generic
   YouTube/Vimeo resolve's own jurisdiction guess is never as reliable as
   what the state notice board already told us directly.
2. No "Audio File Address" section at all -- instead, the Download
   Attachments table has a row categorized "Audio Recording" or "Video
   Recording", a bare file hosted directly on `utah.gov`
   (`/pmn/files/{id}.m4a`/`.mp3`/`.mp4`/`.MP3`) with NO platform wrapper
   at all. This is the shape no other adapter in this repo (or any
   general civic-scraper tool) has ever needed to handle -- most
   platforms' whole reason for existing is a page to scrape a video OFF
   of; here the "page" IS the file. `detect_platform()` correctly
   returns "unknown" for these, so before this adapter existed they were
   entirely unresolvable (see BACKLOG.md's "no adapter for a bare hosted
   audio/video file" entry, filed after the pilot found 825 real
   examples across 353 distinct Utah entities in one 30-day scan, mostly
   Public School districts).

   This case needs NO new transcription-pipeline work: `video_url` is
   just set directly to the raw file URL with `video_format` set to its
   real file extension (lowercased) -- `app/platforms/media_probe.py`'s
   own `probe_has_video_stream()` docstring already documents 19 real,
   confirmed-live audio-only meetings from OTHER platforms (audio hiding
   inside an mp4/m3u8 container on Granicus/IQM2), so the on-demand
   Whisper pipeline is already audio-format-agnostic -- ffmpeg extracts
   audio whether or not a video stream exists, and `player.js`'s
   `initVideo()` falls through to a plain native `<video src=...>` for
   any format string other than "m3u8"/"youtube"/"vimeo"/"viebit" (a
   `<video>` element plays an audio-only source fine, just with no
   picture -- acceptable here since the whole point is following along
   with the transcript, not watching video).

Not attempted here (a separate, real, currently-open gap, same
BACKLOG.md entry): a populated Audio File Location pointing to
`drive.google.com` or `soundcloud.com` -- neither is a platform this
repo resolves, and unlike case 2 above, a Drive/SoundCloud sharing link
isn't a directly-fetchable file URL without its own investigation.
"""

import re
from datetime import datetime
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, UnsupportedPlatformError, detect_platform, get_finder
from .models import ResolvedMeeting

_NOTICE_ID_RE = re.compile(r"/notice/(\d+)\.html")

_DT_TEXT_RE = re.compile(r"\s+")

_PMN_DATE_FORMATS = ("%B %d, %Y %I:%M %p", "%B %d, %Y")


def _short_date(text: Optional[str]) -> Optional[str]:
    """PMN's own "Event Start Date & Time" field is a long, human-
    readable string ("August 10, 2026 05:30 PM", 24 characters) -- real,
    confirmed-live production bug (2026-09-09): the Archive's `date`
    column is `VARCHAR(20)` (archive/alembic/versions/..._baseline_
    schema.py), and every other adapter already respects that by storing
    a short ISO date instead (civicclerk.py's own convention:
    `event.get("eventDate")[:10]`) -- passing PMN's raw text straight
    through crashed a real production ingest with asyncpg's
    StringDataRightTruncationError. Parsed down to plain "YYYY-MM-DD"
    (10 characters) here, matching that same convention, rather than
    guessing at how much of the raw text might happen to fit. Returns
    None (never the original long text) when the format doesn't match
    one of PMN's two confirmed-live shapes -- a missing date is safe
    everywhere downstream; an oversized one crashes the database."""
    if not text:
        return None
    for fmt in _PMN_DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


class UtahPMNAssetFinder(AssetFinder):
    """Resolves a Utah PMN notice detail page -- see this module's own
    docstring for the two real media shapes this handles."""

    platform_name = "utah_pmn"

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
                url, timeout=aiohttp.ClientTimeout(total=25)
            ) as response:
                response.raise_for_status()
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        fields = self._parse_dt_dd(soup, url)
        attachments = self._parse_attachments(soup, url)

        entity = fields.get("Entity", ("", None))[0] or None
        public_body = fields.get("Public Body", ("", None))[0] or None
        notice_title = fields.get("Notice Title", ("", None))[0] or None
        event_date = _short_date(fields.get("Event Start Date & Time", ("", None))[0])
        audio_field_url = fields.get("Audio File Location", ("", None))[1]

        jurisdiction = f"{entity}, Utah" if entity else None
        notice_id_match = _NOTICE_ID_RE.search(url)
        external_id = (
            f"utah_pmn:{notice_id_match.group(1)}" if notice_id_match else None
        )

        if audio_field_url:
            platform = detect_platform(audio_field_url)
            try:
                get_finder(platform)
                is_known_platform = platform != "unknown"
            except UnsupportedPlatformError:
                is_known_platform = False

            if is_known_platform:
                from .base import resolve_via_platform

                result = await resolve_via_platform(audio_field_url)
                # `source_url` stays the PMN notice page, not the
                # delegated platform's own URL -- unlike Legistar/
                # CivicPlus's delegation through this same
                # resolve_via_platform() helper (CLAUDE.md calls that "a
                # known quirk", not a deliberate choice), there's no
                # reason to lose the canonical page here: the notice page
                # IS the real, citable source, and this call site knows
                # it. Same effect PrimeGov/ClerkBase get a different way
                # (calling YouTubeAssetFinder.resolve_video_id() directly
                # with an explicit source_url= instead of going through
                # this generic helper).
                result.source_url = url
                # Known-identity override (ENUMERATION_METHODS.md §98) --
                # PMN already told us who this government and public body
                # are; a generic resolve's own guess is never as reliable.
                result.jurisdiction = jurisdiction or result.jurisdiction
                result.meeting_body = public_body or result.meeting_body
                if notice_title:
                    result.title = notice_title
                if event_date:
                    result.date = event_date
                return result

            # A populated Audio File Location that isn't on any platform
            # this repo resolves (most commonly drive.google.com/
            # soundcloud.com in the real pilot data) -- not a bare file
            # this adapter can hand to the transcription pipeline
            # directly, so treated the same as "no media found" rather
            # than guessed at. See this module's own docstring.
            return self._no_media_result(
                url,
                external_id,
                notice_title,
                event_date,
                jurisdiction,
                public_body,
                warning=f"Audio File Location isn't on a known video/audio platform: {audio_field_url}",
            )

        media_attachment = self._pick_media_attachment(attachments)
        if media_attachment:
            _filename, file_url, _category = media_attachment
            video_format = self._infer_video_format(file_url)
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=external_id,
                title=notice_title,
                date=event_date,
                jurisdiction=jurisdiction,
                meeting_body=public_body,
                video_url=file_url,
                video_format=video_format,
            )

        return self._no_media_result(
            url,
            external_id,
            notice_title,
            event_date,
            jurisdiction,
            public_body,
            warning="No Audio File Location and no Audio/Video Recording attachment on this PMN notice.",
        )

    def _no_media_result(
        self,
        url: str,
        external_id: Optional[str],
        title: Optional[str],
        date: Optional[str],
        jurisdiction: Optional[str],
        meeting_body: Optional[str],
        *,
        warning: str,
    ) -> ResolvedMeeting:
        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=external_id,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            meeting_body=meeting_body,
            video_warnings=[warning],
        )

    @staticmethod
    def _infer_video_format(file_url: str) -> Optional[str]:
        path = urlparse(file_url).path
        if "." not in path:
            return None
        extension = path.rsplit(".", 1)[-1].lower()
        # The Archive's `video_format` column is VARCHAR(10) (see
        # `_short_date()`'s own docstring for the sibling VARCHAR(20)
        # bug this same class of issue caused) -- every real extension
        # confirmed live so far (mp4/m4a/mp3/MP3) is 3 characters, but a
        # URL with no real extension could plausibly trail off into
        # something longer that isn't a real format string at all, so
        # this refuses to guess past the column's own limit rather than
        # risk a second StringDataRightTruncationError.
        if not extension or len(extension) > 10:
            return None
        return extension

    @staticmethod
    def _pick_media_attachment(
        attachments: list[Tuple[str, str, str]],
    ) -> Optional[Tuple[str, str, str]]:
        """Prefers a "Video Recording" attachment over "Audio Recording"
        when both exist (not yet confirmed live on the same notice, but a
        video is strictly more useful than audio alone when there's a
        choice); otherwise the first media-categorized attachment found,
        matching this repo's general "don't force an ambiguous pick"
        posture -- there's no per-meeting listing to pick "most recent"
        from here, every notice is already exactly one meeting."""
        video = next(
            (a for a in attachments if a[2].strip().lower() == "video recording"),
            None,
        )
        if video:
            return video
        return next(
            (a for a in attachments if a[2].strip().lower() == "audio recording"),
            None,
        )

    @classmethod
    def _parse_dt_dd(
        cls, soup: BeautifulSoup, base_url: str
    ) -> Dict[str, Tuple[str, Optional[str]]]:
        """Maps every real `<dt>label</dt><dd>...</dd>` pair on a notice
        detail page to (text, first_href_in_dd_or_None) -- confirmed live
        2026-09-08 against real Alpine/Grand County notices, see this
        module's own docstring."""
        out: Dict[str, Tuple[str, Optional[str]]] = {}
        for dt in soup.find_all("dt"):
            label = _DT_TEXT_RE.sub(" ", dt.get_text(strip=True))
            dd = dt.find_next_sibling("dd")
            if dd is None:
                continue
            text = _DT_TEXT_RE.sub(" ", dd.get_text(" ", strip=True))
            a = dd.find("a")
            href = urljoin(base_url, a["href"]) if a and a.get("href") else None
            out[label] = (text, href)
        return out

    @staticmethod
    def _parse_attachments(
        soup: BeautifulSoup, base_url: str
    ) -> list[Tuple[str, str, str]]:
        """Parses the "Download Attachments" table (File Name / Category
        / Date Added columns) into (filename, url, category) tuples --
        confirmed live 2026-09-08, see this module's own docstring."""
        out: list[Tuple[str, str, str]] = []
        table = soup.find("table")
        while table is not None:
            caption = table.find("caption")
            if (
                caption
                and "download attachments" in caption.get_text(strip=True).lower()
            ):
                break
            table = table.find_next("table")
        if table is None:
            return out
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            a = tds[0].find("a")
            if not a or not a.get("href"):
                continue
            filename = a.get_text(strip=True)
            file_url = urljoin(base_url, a["href"])
            category = tds[1].get_text(strip=True)
            out.append((filename, file_url, category))
        return out
