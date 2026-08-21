import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
import wordninja
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    detect_language_from_texts,
    is_likely_garbled,
    parse_vtt,
)

# SuiteOne Media (suiteonemedia.com) -- a small, real, multi-tenant civic
# video vendor, one meeting per `https://{tenant}.suiteonemedia.com/event/
# ?id={N}` page. Confirmed live 2026-08-21 against 6 real, distinct
# tenants (2 pre-confirmed by a prior investigation this session,
# `pacificgroveca` and `lorainoh`; 4 more freshly confirmed live from this
# repo's CDX-derived candidate list: `tuscaloosaal`, `camaswa`,
# `holladayut`, `stmarysga`) before writing any parsing code, per this
# repo's "test against a real URL first" rule -- see `tests/fixtures/
# suiteone/` for the real captured HTML/VTT this was built against.
# `mcallentx`, `southbendin`, `prescottaz`, `richlandwa`, `laytonut` all
# 404 on their home page (dead/unconfirmed leads -- not this vendor's
# current tenants, or retired) and are NOT registered anywhere.
#
# **Video**: every event page's static HTML (no JS execution needed)
# embeds a plain jQuery-ready JW Player setup with a hardcoded JS var:
#   var src = 'https://s3.amazonaws.com/suiteone.{tenant}.videofiles/{hash}.mp4';
# -- a direct, unauthenticated S3 MP4 URL, confirmed fetchable across all
# 6 tenants above. When a meeting genuinely has no video yet, the SAME
# page shape is served with `var src = '';` (confirmed live on St Marys,
# GA event id 1000, "Orange Hall Management Committee") -- the page's own
# JS treats this as the "stream is offline" case, and this adapter treats
# it the same way (a real per-meeting negative, not a parse failure).
#
# **Captions**: when present, the same JW Player config's `tracks` array
# has an entry pointing at
#   https://{tenant}.suiteonemedia.com/Event/GetCaptions/?eventId={id}
# -- fetched directly, real populated WebVTT (confirmed real dialogue
# content, not empty/placeholder, on both Pacific Grove event 2099 and
# Holladay, UT event 2652). The `tracks` key is omitted entirely (not an
# empty array) when a meeting has no captions -- confirmed on Lorain, OH
# event 2794, which has a real video but no captions at all.
#
# **Title**: `<h1 class="ev-header">{title}</h1>`, confirmed identical
# across all 6 tenants.
#
# **Date -- the one real gap in this vendor's own event page**: the event
# page itself carries NO date anywhere in its markup (checked full HTML
# on all 6 tenants -- no date near the h1, no JSON-LD, no meta tag). The
# only place a date exists is the tenant's own home/calendar page
# (`https://{tenant}.suiteonemedia.com/`), in a `<tr>` whose first `<td>`
# holds an `<a href="/event/?id={id}">` link to that same event and whose
# second `<td class="text-nowrap" data-sort="{.NET ticks}">` holds real,
# human-readable text like "Jan 02, 2025 | 09:00 AM" -- confirmed
# identical shape across Pacific Grove, Lorain, and Tuscaloosa's home
# pages. This adapter fetches that second page, finds the `<tr>` whose
# event-id link matches, and parses the human-readable date text (never
# the `.NET ticks` `data-sort` value -- that needs epoch conversion the
# display text avoids entirely). If the event isn't found on the
# currently-visible home page listing (an older meeting likely paginated
# off it -- unconfirmed how far back the home page goes on any tenant),
# this degrades to `date=None` rather than raising, and the same happens
# if the home-page fetch itself fails for any reason -- honest
# best-effort, not a guess.
#
# **Jurisdiction**: no real city-name text appears anywhere on the page --
# only the raw tenant subdomain, in a logo/asset path (e.g.
# "PACIFICGROVECA"). This is exactly the glued-city+state-code shape
# `jurisdiction_enrich.validated_subdomain_extract()` already handles, so
# this adapter reuses it directly rather than writing new jurisdiction-
# parsing logic, plus the same "check the raw slug's own wordninja-split
# last token against a real US state abbreviation" trick
# `townhallstreams.py`'s `_extract_jurisdiction()` already established for
# this identical "concatenated slug, maybe with a trailing state
# abbreviation" shape. Confirmed working end to end on all 6 real tenants
# above -- e.g. "lorainoh" wordninja-splits to ['lora', 'in', 'oh'], whose
# glued non-state remainder validates as "Lorain" and whose own last
# token "oh" is a real state code, giving "Lorain, OH".
#
# **A real, confirmed residual gap**: `stmarysga` (St Marys, GA) and
# `camaswa` (Camas, WA) -- specifically flagged as worth checking since
# they're the least obviously-splittable of the known real tenants --
# both fail to validate via this shared pipeline at all. wordninja splits
# "stmarysga" as ['st', 'mary', 'sga'] and "camaswa" as ['ca', 'maswa']:
# neither's last token is a real 2-letter state code (the trailing state
# letters get absorbed into a longer, non-word chunk -- "sga"/"maswa" --
# by wordninja's own dictionary-cost minimization instead of splitting
# cleanly), so `validated_subdomain_extract()` never even produces a bare
# name to attach a state to. Confirmed directly: stripping the real
# trailing state code by hand first ("stmarys" / "camas") DOES validate
# correctly ("St Marys" / "Camas") -- but doing that generically would be
# new jurisdiction-parsing logic, which this adapter deliberately doesn't
# add (see CLAUDE.md's "reuse jurisdiction_enrich directly" instruction
# for this platform). So `jurisdiction` is honestly `None` for these two
# real, confirmed-live tenants today -- declining rather than guessing,
# same as every other adapter's stated policy -- tracked in BACKLOG.md as
# a real, still-open residual gap for a future session that's willing to
# extend the shared module itself.
#
# **A second document endpoint, confirmed real but only lightly used
# here**: `/event/GetAgendaFile/Agenda?aid={N}` (an `<object data="...">`
# PDF embed, not a plain `<a href>`) is a real, separate agenda PDF --
# confirmed present on 3 of 6 sampled events (Holladay UT event 2652, and
# both sampled St Marys GA events). Surfaced as `agenda_link` when found,
# matching what that field is for (a best-effort "we think we found the
# agenda here" link, never parsed into real per-item timestamps). A
# different, more general `/event/GetDocumentFile/{title}?did={N}` also
# exists and confirmed live to serve a real "Transcript" PDF on Pacific
# Grove (alongside that same event's real VTT captions) as well as
# assorted unrelated document titles on St Marys ("Stars and Stripes -
# Major Subdivision Preliminary Plat", etc.) -- this is a general
# per-tenant document library, not agenda-specific, and no real example
# has been found yet of a "Transcript" PDF existing on a meeting that
# lacks real VTT captions. Building a fallback to that PDF would be a
# guess with no confirmed positive case behind it, so it's deliberately
# not attempted here (real VTT is always preferred when present, per this
# repo's "don't claim a data path works without a positive example"
# convention).
TARGET_LANGUAGE = "en"

_VIDEO_SRC_RE = re.compile(r"var\s+src\s*=\s*'([^']*)'\s*;")
_CAPTIONS_URL_RE = re.compile(
    r"file:\s*'(https?://[^']+/Event/GetCaptions/\?eventId=\d+)'", re.IGNORECASE
)
_AGENDA_FILE_RE = re.compile(r'data="(/event/GetAgendaFile/[^"]+)"', re.IGNORECASE)
_DATE_PREFIX_RE = re.compile(r"^([A-Za-z]{3}\s+\d{1,2},\s+\d{4})")

# Same scope/source as GranicusAssetFinder.US_STATE_ABBREVIATIONS -- not
# imported from jurisdiction_enrich.py's wider (US+Canada) private sets,
# same reasoning townhallstreams.py's own copy of this set gives: no real
# Canadian suiteonemedia.com customer is confirmed yet to justify it.
_US_STATE_ABBREVIATIONS = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}


class SuiteOneAssetFinder(AssetFinder):
    """Resolves video + captions (+ best-effort agenda link) for a
    SuiteOne Media (suiteonemedia.com) meeting page. See the module
    docstring above for the real investigation this was built against."""

    platform_name = "suiteone"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        tenant, event_id = self._extract_ids(url)
        if not tenant or not event_id:
            raise ValueError(f"Could not find a SuiteOne tenant/event id in URL: {url}")

        video_warnings: List[str] = []
        transcript_warnings: List[str] = []
        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        alternate_transcripts: List[AlternateTranscript] = []

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                html = await response.text()

            title = self._extract_title(html)

            src_match = _VIDEO_SRC_RE.search(html)
            video_url = src_match.group(1) if src_match and src_match.group(1) else None
            if not video_url:
                video_warnings.append("No playable video found for this event.")

            agenda_link = self._extract_agenda_link(html, tenant)

            caption_urls = _CAPTIONS_URL_RE.findall(html)
            if caption_urls:
                candidates = []  # (url, cues, detected_language)
                for caption_url in caption_urls:
                    cues = await self._fetch_captions(session, caption_url)
                    if cues:
                        candidates.append(
                            (
                                caption_url,
                                cues,
                                detect_language_from_texts(c["text"] for c in cues),
                            )
                        )

                target_match = next(
                    (c for c in candidates if c[2] == TARGET_LANGUAGE), None
                )
                chosen = target_match or (candidates[0] if candidates else None)

                if chosen:
                    _url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if lang and lang != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{lang}', not "
                            f"'{TARGET_LANGUAGE}' — no matching-language track "
                            "was found for this meeting."
                        )
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not "
                            "a parsing bug on our end) — treat it as "
                            "approximate. You can request a transcript from "
                            "the audio instead."
                        )
                    alternate_transcripts = [
                        AlternateTranscript(
                            language=alt_lang,
                            segments=[TranscriptSegment(**cue) for cue in alt_cues],
                        )
                        for alt_url, alt_cues, alt_lang in candidates
                        if alt_url != _url
                    ]
                else:
                    transcript_warnings.append(
                        "A caption file is referenced for this event but "
                        "couldn't be fetched or parsed."
                    )
            else:
                transcript_warnings.append("No captions found for this video.")

            date = await self._fetch_date(session, tenant, event_id)

        jurisdiction = self._extract_jurisdiction(tenant)

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=f"suiteone:{tenant}:{event_id}",
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format="mp4" if video_url else None,
            segments=segments,
            agenda_link=agenda_link,
            transcript_language=transcript_language,
            alternate_transcripts=alternate_transcripts,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_ids(url: str) -> Tuple[Optional[str], Optional[str]]:
        parsed = urlparse(url)
        tenant = parsed.netloc.split(".")[0] if parsed.netloc else None
        event_id = (parse_qs(parsed.query).get("id") or [None])[0]
        return tenant, event_id

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        header = soup.find("h1", class_="ev-header")
        return header.get_text(strip=True) if header else None

    @staticmethod
    def _extract_agenda_link(html: str, tenant: str) -> Optional[str]:
        match = _AGENDA_FILE_RE.search(html)
        if not match:
            return None
        base = f"https://{tenant}.suiteonemedia.com/"
        return urljoin(base, match.group(1))

    @staticmethod
    async def _fetch_captions(session: aiohttp.ClientSession, caption_url: str):
        """`GetCaptions` URLs carry no file extension at all (a bare
        `?eventId=N` query string, confirmed on every real tenant checked)
        -- `parse_captions_by_extension()`'s usual extension-sniffing
        dispatch (every other adapter's caption URLs end in `.vtt`/`.srt`/
        etc.) can never identify this shape, so this parses directly with
        `parse_vtt()` instead. Safe to assume WebVTT unconditionally: both
        real fetched samples (Pacific Grove, Holladay UT) are confirmed
        real WebVTT (a literal "WEBVTT" header), and JW Player's own
        `kind: 'captions'` track config only ever expects WebVTT/SRT --
        this vendor's own player-setup JS never varies the file format by
        tenant."""
        try:
            async with session.get(
                caption_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                raw = await response.read()
        except Exception:
            return None
        content = decode_vtt_bytes(raw)
        return parse_vtt(content) or None

    @staticmethod
    async def _fetch_date(
        session: aiohttp.ClientSession, tenant: str, event_id: str
    ) -> Optional[str]:
        """Best-effort recovery of a meeting's date from the tenant's own
        home/calendar page -- see the module docstring's "Date" section
        for why the event page itself has none. Never raises: any failure
        (network error, non-200, event not found on the currently-visible
        listing) degrades to None rather than blocking the rest of the
        resolve."""
        home_url = f"https://{tenant}.suiteonemedia.com/"
        try:
            async with session.get(
                home_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                home_html = await response.text()
        except Exception:
            return None
        return SuiteOneAssetFinder._extract_date_from_home(home_html, event_id)

    @staticmethod
    def _extract_date_from_home(home_html: str, event_id: str) -> Optional[str]:
        soup = BeautifulSoup(home_html, "html.parser")
        target_href = f"/event/?id={event_id}"
        link = next(
            (a for a in soup.find_all("a", href=True) if a["href"] == target_href),
            None,
        )
        if not link:
            return None
        row = link.find_parent("tr")
        if not row:
            return None
        date_cell = row.find("td", class_="text-nowrap")
        if not date_cell:
            return None
        return SuiteOneAssetFinder._parse_display_date(date_cell.get_text(strip=True))

    @staticmethod
    def _parse_display_date(text: str) -> Optional[str]:
        match = _DATE_PREFIX_RE.match(text.strip())
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%b %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _extract_jurisdiction(tenant: str) -> Optional[str]:
        name = jurisdiction_enrich.validated_subdomain_extract(
            f"https://{tenant}.suiteonemedia.com/event/"
        )
        if not name:
            return None

        words = wordninja.split(tenant)
        if words and len(words) > 1 and words[-1].lower() in _US_STATE_ABBREVIATIONS:
            return f"{name}, {words[-1].upper()}"

        state = jurisdiction_enrich.resolve_state(name, "city")
        return f"{name}, {state}" if state else name
