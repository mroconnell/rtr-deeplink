import json
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import decode_vtt_bytes, is_likely_garbled, parse_vtt

logger = logging.getLogger("rtr_deeplink.telvue")

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
# A LEADING numeric date (unlike _TITLE_DATE_RE's trailing "- Month DD,
# YYYY" shape) is never itself part of the jurisdiction name -- real
# case, confirmed live 2026-08-29 via the Common Crawl sweep: titles like
# "2024-03-19 Town Board Meeting" and "03/10/2025 Regular Council" have
# no dash-separated trailing date for _TITLE_DATE_RE to strip, so the
# whole string (date included) reached _BODY_SUFFIX_RE below, which
# happily captured "2024-03-19 Town"/"03/10/2025 Regular" as the
# "jurisdiction" -- a confident wrong answer, not just a missed one.
# Stripped before the suffix match runs, not folded into the stopword
# list at the bottom, since a date is never a real word to filter by.
_LEADING_DATE_RE = re.compile(r"^\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\s+")
_BODY_SUFFIX_RE = re.compile(
    # "Select Board"/"Zoning Board" must precede the bare "Board"
    # alternative -- real cases, confirmed live 2026-08-18 and
    # 2026-08-29 respectively: "Natick Select Board June 10, 2026" (no
    # dash-separated date, so _guess_jurisdiction() sees the whole
    # string) matched bare "Board" first, capturing "Natick Select" as
    # the jurisdiction instead of "Natick"; "Newmarket Zoning Board of
    # Adjustments Meeting" the same way captured "Newmarket Zoning".
    # Same shape a third time, same day: "Vail Planning and
    # Environmental Commission" matched bare "Commission", capturing
    # "Vail Planning and Environmental" -- Vail, CO's real governing
    # body name is "Planning and Environmental Commission" (confirmed
    # live via the channel's own real content), not a generic
    # "Planning Commission". All multi-word alternatives are listed
    # first so the regex's leftmost-match search locks onto the phrase
    # starting one word earlier, not because alternation order breaks
    # ties at the same position (it doesn't -- position is what
    # matters here).
    r"^(.*?)\s+(City Council|Council|Planning and Environmental Commission|Planning Commission|Commission|Select Board|Zoning Board|Board|Committee|Authority|District)\b",
    re.I,
)
_VOICE_TAG_RE = re.compile(r"<[^>]+>")
_ORG_TOKEN_RE = re.compile(r"/player/([^/]+)/")

# Per-customer jurisdiction map, the "later" this file's own module
# comment above anticipated -- built one confirmed entry at a time as a
# title-only guess proves ambiguous/wrong, never guessed speculatively.
#
# cT30AQ_xtOBQF0oJM2gIVCDX9kjgfWZb: originally guessed "likely Scranton,
# PA" (BACKLOG.md, "ECTV" -> "Electric City Television" nickname match,
# no direct linking .gov page). Corrected 2026-08-18: the same org token's
# playlist also contains "ECTV Channel 3 Public Access Programs" (exact
# match to Everett, MA's own public-access channel -- cityofeverett.com
# describes it as "Public Comcast (Channel 3)... Government Comcast
# (Channel 22)") and "Community Meeting on Stadium Development" (matches
# the real, well-documented 2025 Everett, MA Kraft Group/New England
# Revolution soccer-stadium community meetings) -- "ECTV" was an acronym
# collision with Scranton's unrelated "Electric City Television", not the
# same organization.
_KNOWN_ORG_TOKEN_JURISDICTIONS = {
    "cT30AQ_xtOBQF0oJM2gIVCDX9kjgfWZb": "Everett, MA",
    # w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP: "Ashland" is nationally ambiguous
    # (also real in OR/WI/OH/KY/VA and more), so the title guess alone
    # ("Ashland Planning Commission") never gets a state -- confirmed
    # 2026-08-28 via this org's own real `id="org-logo"` alt text, "Rogue
    # Valley Community Television (RVTV)". Rogue Valley is a real,
    # unambiguous southern-Oregon region (Medford/Ashland/Grants Pass),
    # so this is a state fill for an already-correct name, not an
    # override -- see resolve()'s own comment on that distinction.
    "w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP": "Ashland, OR",
    # BjiipOg61Ac-YpNM5RFZy8f49fIMR7Kq: title-only guess gets nothing --
    # every real sample title is a bare "Town Board Meeting"/"Public
    # Forum", no city prefix at all. Confirmed 2026-08-29 via the
    # channel's own playlist, which includes one real, unambiguous entry:
    # "Town of Riverhead NY Live Stream".
    "BjiipOg61Ac-YpNM5RFZy8f49fIMR7Kq": "Riverhead, NY",
    # MYHMRKXBbGFaah07vKkZ_-J4SThODdPq: title-only guess gets "Stoneham"
    # with no state (real, well-known MA town, but this file's own guess
    # never appends one on its own). Confirmed 2026-08-29 via the
    # channel's own page directly stating "Stoneham, MA" -- a state fill
    # for an already-correct name, same shape as the Ashland/OR entry
    # above, not an override.
    "MYHMRKXBbGFaah07vKkZ_-J4SThODdPq": "Stoneham, MA",
    # XSekkdEeRsk0JHQVHAvKJVka7_5VjxKP: real, genuine collision, not just
    # a missing state. Title guess -> enrich_jurisdiction_text() resolves
    # bare "Newmarket" to "Newmarket, ON" (Ontario) -- a real, larger
    # place of that name, presumably preferred by whatever the enrichment
    # lookup ranks first among same-named places. This channel is
    # unambiguously Newmarket, NH (confirmed live 2026-08-29 via
    # newmarketnh.gov's own "Zoning Board of Adjustment" page, matching
    # this channel's real title "Newmarket Zoning Board of Adjustments
    # Meeting"). The base-name-only match in resolve() (widened the same
    # day for exactly this shape) catches this even though the guess
    # already has a comma.
    "XSekkdEeRsk0JHQVHAvKJVka7_5VjxKP": "Newmarket, NH",
    # O7e6JrKKSJ3H_TX3VgEvpbSSL7Dbnrk2: same wrong-state collision shape
    # as Newmarket above. Bare "Needham" enriches to "Needham, AL"
    # instead of the correct Needham, MA -- confirmed live 2026-08-29
    # via WebSearch showing this is "Needham Channel" (the real
    # Needham, MA public-access station) covering the Town of Needham,
    # MA's own Select Board.
    "O7e6JrKKSJ3H_TX3VgEvpbSSL7Dbnrk2": "Needham, MA",
    # YGktjFZCLukJd_8Fx53BkVRk4tAZafS4: not a wrong state, a
    # _BODY_SUFFIX_RE gap (fixed the same day, adding "Planning and
    # Environmental Commission" ahead of bare "Commission") that
    # produced "Vail Planning and Environmental" before the fix.
    # Confirmed live via the channel's own content: "Town of Vail",
    # "Colorado". Kept here too as a belt-and-suspenders state fill in
    # case a future title shape slips past the regex fix.
    "YGktjFZCLukJd_8Fx53BkVRk4tAZafS4": "Vail, CO",
}


def _org_token_from_url(url: str) -> Optional[str]:
    match = _ORG_TOKEN_RE.search(url)
    return match.group(1) if match else None


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
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
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
            org_token = _org_token_from_url(final_url)
            known_jurisdiction = (
                _KNOWN_ORG_TOKEN_JURISDICTIONS.get(org_token) if org_token else None
            )
            if not jurisdiction:
                jurisdiction = known_jurisdiction
            elif known_jurisdiction:
                # Real gap found 2026-08-28 (BACKLOG_DONE.md), widened
                # 2026-08-29: originally only handled a *bare*,
                # nationally-ambiguous name (e.g. "Ashland") the title
                # guess had left with no state -- the old `if not
                # jurisdiction` gate only ever consulted this registry on
                # a TOTAL guess failure. That still missed the case where
                # `enrich_jurisdiction_text()` resolves an ambiguous bare
                # name to the WRONG state/country instead of no state at
                # all -- confirmed live: "Newmarket" (bare, from the
                # title) enriched to "Newmarket, ON" (Ontario, presumably
                # the more populous/prominent real place of that name),
                # when this specific channel's own page is unambiguously
                # Newmarket, NH (newmarketnh.gov). Comparing only the
                # base name (before any comma) on both sides -- ignoring
                # whatever state enrichment guessed -- catches both
                # shapes with one check, while the base-name-match
                # requirement still guarantees this never lets one org's
                # registry entry override a genuinely DIFFERENT city's
                # real guess under the same token.
                known_name = known_jurisdiction.split(",")[0].strip().lower()
                guessed_name = jurisdiction.split(",")[0].strip().lower()
                if guessed_name == known_name:
                    jurisdiction = known_jurisdiction

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
                            cue["text"] = (
                                _VOICE_TAG_RE.sub("", cue["text"])
                                .replace("\n", " ")
                                .strip()
                            )
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
                            agenda_items.append(
                                TranscriptSegment(**{**cue, "text": text})
                            )

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
        match = re.search(
            r"Player\.setupData\['playlist'\]\s*=\s*(\[.*?\]);", html, re.S
        )
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

                    return title.strip() or None, datetime.strptime(
                        fmt_text, fmt
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return title.strip() or None, None

    @staticmethod
    def _guess_jurisdiction(title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        title = _LEADING_DATE_RE.sub("", title.strip())
        match = _BODY_SUFFIX_RE.match(title.strip())
        if not match:
            return None
        name = match.group(1).strip()
        # Real bug, confirmed live 2026-08-16: a bare "City Council -
        # 5.6.2025" title (no actual city name prefix) matches the regex
        # with group(1)="City", which enrich_jurisdiction_text() then
        # treats as a real name and appends a state to -- "City, MA".
        # These generic placeholder words are never a real jurisdiction
        # name on their own.
        if name.lower() in {"city", "town", "village", "township"}:
            return None
        if not name:
            return None
        # Second, broader real bug, confirmed live 2026-08-28 while
        # enumerating TelVue customers by search-dorking real player URLs:
        # a title that's just the body name with no city prefix at all
        # ("Select Board", "Planning Board 5-1-2025", "School Committee ...")
        # still matches this regex, because the leftmost-match search
        # happily captures the FIRST word(s) before whichever alternative
        # matches first -- "Select" before bare "Board", "Planning" before
        # "Board" again (the "Planning Commission" alternative doesn't fire
        # when the actual phrase is "Planning Board"), "School" before
        # "Committee". None of "Select"/"Planning"/"School" are real places,
        # but nothing upstream ever checked that -- enrich_jurisdiction_text()
        # only appends a state to whatever it's given, it never validates the
        # base name (see its own docstring: "Returns jurisdiction unchanged
        # if..."), so bad guesses flowed straight through to production.
        #
        # Tried validating the extracted name against jurisdiction_enrich's
        # real Census-backed place lookups first (same fix shape as the
        # CivicWeb/YouTube jurisdiction gaps closed earlier this project,
        # PR #444) -- reverted. `jurisdiction_data/places.csv` turns out to
        # only carry 58 Massachusetts entries and doesn't include Natick, a
        # real, well-known MA town already covered by this file's own
        # `test_guess_jurisdiction_handles_select_board` test -- validating
        # against it would have silently rejected real New England towns
        # wholesale, which is TelVue's actual core customer base. A stopword
        # list, not a validating lookup, is the safe tool here: these three
        # words are governance-generic the same way "city"/"town" already
        # are above, never a real jurisdiction name on their own, checked
        # against just the LAST word so a real prefix name (e.g. "Summit" in
        # "Summit Planning Board") still gets rejected rather than guessed
        # at -- there's no reliable way to know the modifier word is
        # separable from the real name without a validated match, and this
        # file's own decline-rather-than-guess convention says lose the
        # recoverable case over risking a wrong one.
        last_word = name.rsplit(None, 1)[-1].lower()
        # "regular" added 2026-08-29 -- same Common Crawl sweep that found
        # the leading-date bug above also hit "03/10/2025 Regular Council":
        # stripping the leading date left "Regular Council", and "Regular"
        # is a meeting-type modifier ("Regular Meeting", "Regular Session"),
        # never a real place name, same governance-generic shape as the
        # three words already here.
        if last_word in {"select", "planning", "school", "regular"}:
            return None
        return name

    @staticmethod
    async def _fetch_vtt(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(
                vtt_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "TelVue VTT fetch got HTTP %s for %s",
                        response.status,
                        vtt_url,
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning("TelVue VTT fetch failed for %s", vtt_url, exc_info=True)
            return None
        content = decode_vtt_bytes(raw)
        cues = parse_vtt(content)
        return cues or None
