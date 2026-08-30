import json
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

import aiohttp

from .base import AssetFinder
from .granicus import US_STATE_ABBREVIATIONS
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

# Automated last-resort fallback, added 2026-08-29 after the Irondequoit
# fix below was found by hand: every TelVue page already carries an
# `id="org-logo"` <img> with descriptive alt text (no extra fetch --
# it's in the same `html` already downloaded for the playlist). But the
# shape of that text is NOT consistent enough to trust blindly --
# confirmed from two real fixtures already in this file: Irondequoit's is
# "Irondequoit, NY - Irondequoit, NY - organization logo" (a clean,
# duplicated "City, ST"), while Ashland/RVTV's is "Rogue Valley Community
# Television (RVTV) - Watch RVTV - organization logo" (an org name + a
# tagline, not a place at all -- using this blindly would have produced
# "Rogue Valley Community Television (RVTV)" as a "jurisdiction", exactly
# the confident-wrong-guess failure mode this file exists to avoid). So
# this only ever fires when the two dash-separated halves are IDENTICAL
# and already comma-state-shaped -- narrow enough that a non-place tagline
# never matches, at the cost of not helping the (unknown, possibly
# common) case where the two halves differ but both are still real city
# names. Runs only as a last resort, after both the title guess and the
# hand-curated _KNOWN_ORG_TOKEN_JURISDICTIONS map have already failed --
# never overrides either, since both are more specific/more verified than
# a generic parse of a logo caption.
#
# This is still the FIRST thing `_reduce_org_logo_piece()` below checks
# (an already-clean "City, ST" segment is accepted immediately, no
# stripping needed) -- the messy-org-name parsing added after it (see
# that function's own module comment) is a second, broader pass over the
# same alt text for the common case this narrow rule declines on.
_ORG_LOGO_ALT_RE = re.compile(r'id="org-logo"[^>]*\balt="([^"]*)"')
_ORG_LOGO_CITY_STATE_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]*,\s*[A-Z]{2}$")

# Messy-org-name parser, built 2026-08-29 to close the residual gap
# `_org_logo_jurisdiction()`'s narrow "identical, already City,ST-shaped"
# check above correctly declines on -- BACKLOG.md's "TelVue's jurisdiction
# extraction still can't parse a *messy* org name" entry. Every phrase and
# shape below comes from real org-logo alt text fetched live from real
# TelVue customer pages 2026-08-29 (org tokens found via the same
# search-dork method BACKLOG_DONE.md's TelVue entries already document),
# not from assumption:
#   "Fitchburg Access TV - Fitchburg MA VOD Player"                  (Fitchburg, MA)
#   "Town of Orleans MA - Town of Orleans Video on Demand"           (Orleans, MA)
#   "Stoneham, MA - Stoneham, MA VOD Player"                         (Stoneham, MA -- already known)
#   "Town of Riverhead, NY - Town of Riverhead, New York"            (Riverhead, NY -- already known)
#   "Newmarket TV - Newmarket NH Video on Demand"                    (Newmarket, NH -- already known)
#   "NCM - Nashua Community Media - Nashua Government TV"            (no explicit state anywhere -- declines)
#   "Everett Community TV - Everett Community TV VOD Player"         (no explicit state -- declines)
#   "CMNtv Chris Weagel for Auburn Hills Govt Cable - Auburn Hills Live and VoD" (no explicit state -- declines)
#   "Rogue Valley Community Television (RVTV) - Watch RVTV"          (not a place at all -- declines)
#   "High Five Access Media - High Five Access Media"                (Vail, CO's real media org name,
#                                                                      NOT a place -- declines)
#   "City Of Clifton VoD" / "Natick Pegasus ... VOD Player" /
#   "Wellesley Media Corporation ... VOD Player" / "CNET - C-NET VOD Player" (no explicit state -- decline)
#
# The design choice this data forces: NEVER fill in a missing state via a
# Census-table lookup here. `jurisdiction_enrich.lookup_city_state("Needham")`
# returns "AL" (confirmed live 2026-08-29) because `places.csv` is missing
# Needham, MA entirely -- New England towns are frequently absent from the
# Census incorporated-place gazetteer this repo's lookup tables are built
# from (the same gap this file's own `_KNOWN_ORG_TOKEN_JURISDICTIONS`
# comment already documents for the title-guess path, e.g. Needham's own
# entry there). A stopword-strip-then-lookup design would have silently
# reproduced that exact wrong-state bug on Needham's real alt text
# ("Needham Community TV VOD Player" reduces cleanly to bare "Needham").
# So the rule here is narrower and always safe: strip only boilerplate
# phrases (a leading "Town/City/Village/Township/County of", a trailing
# PEG-industry tagline), and accept the result ONLY when a real two-letter
# US state abbreviation is *already literally present* in the source text
# -- never guessed. This is exactly why Fitchburg and Orleans resolve (the
# state is right there in the alt text) while Auburn Hills, Nashua, and
# Everett -- all real, all independently verified for
# `_KNOWN_ORG_TOKEN_JURISDICTIONS` below -- do not: nothing in their
# org-logo alt text states a jurisdiction, so this parser declines rather
# than guess, the same philosophy `validated_label_extract()` uses
# elsewhere in this codebase.
_ORG_LOGO_LEADING_ENTITY_RE = re.compile(
    r"^(?:Town|City|Village|Township|County)\s+of\s+", re.I
)
# Ordered longest-phrase-first so a loop that strips one matching phrase
# per pass never grabs a short phrase (e.g. bare "vod") when a longer one
# also matches the same trailing text (e.g. "live and vod") -- otherwise
# a real case like "Auburn Hills Live and VoD" could strip down to
# "Auburn Hills Live and" instead of "Auburn Hills". "Access Media" is
# deliberately NOT in this list -- see the module comment above (Vail's
# real "High Five Access Media" alt text, where "Access Media" is part of
# the media nonprofit's own name, not boilerplate). "Community Access
# Television", "Media Center", and "Telecommunications" are carried over
# from BACKLOG.md's own pre-existing candidate list (real prior research,
# not directly re-fetched this session) rather than dropped -- safe to
# include either way since a stopword can only ever help reach the
# explicit-state gate below, never produce a wrong guess on its own.
_ORG_LOGO_TRAILING_STOPWORDS = [
    "community access television",
    "community television",
    "telecommunications",
    "video on demand",
    "community media",
    "government tv",
    "community tv",
    "media center",
    "live and vod",
    "govt cable",
    "vod player",
    "access tv",
    "govt tv",
    "vod",
]
_ORG_LOGO_TRAILING_TVNUM_RE = re.compile(r"\s+tv\s*\d+$", re.I)

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
    # XRGvXhGamdDe6nt3IU9wLyKjf4BqK24i: same title-shape gap as Riverhead
    # above -- every real sample title is a bare "Town Board Meeting" with
    # no city prefix, plus this ingest predates the leading-date fix
    # above, so the stored jurisdiction was the literal date+"Town"
    # ("2024-03-19 Town"). Confirmed live 2026-08-29 via this org's own
    # `id="org-logo"` alt text, "Irondequoit, NY - Irondequoit, NY -
    # organization logo" (reported by a user after seeing the wrong
    # jurisdiction on a live page). This is also the sample that prompted
    # `_org_logo_jurisdiction()` below, which would now catch this same
    # org token on its own -- kept here anyway as the confirmed, permanent
    # record, same belt-and-suspenders reasoning as the Ashland/Vail
    # entries above.
    "XRGvXhGamdDe6nt3IU9wLyKjf4BqK24i": "Irondequoit, NY",
    # RbS8sAKYVBOy0BmYID5GwGYZw1XwFiLb: found 2026-08-29 while gathering
    # real org-logo alt-text samples for the messy-org-name parser above
    # (`_reduce_org_logo_piece()`) -- this org's own alt text, "CMNtv
    # Chris Weagel for Auburn Hills Govt Cable - Auburn Hills Live and
    # VoD", has no explicit state anywhere, so the general parser
    # correctly declines on it. Confirmed live via two independent real
    # sources: this org token's own real meeting titles ("City Council
    # Meeting - April 7, 2025", location "1827 North Squirrel Road,
    # Auburn Hills, MI") and auburnhills.org's own official page (same
    # street address, "1827 N. Squirrel Road, Auburn Hills, Michigan
    # 48326"). "Auburn Hills" is otherwise unambiguous in the Census
    # place table (only one real match, MI).
    "RbS8sAKYVBOy0BmYID5GwGYZw1XwFiLb": "Auburn Hills, MI",
    # LGzST4YdA6GIkRCa0H5CwbVBptJRJ3XD: same shape as Auburn Hills above
    # -- real alt text "NCM - Nashua Community Media - Nashua Government
    # TV" has no explicit state, and "Nashua" is nationally ambiguous
    # (real places in IA/MN/NH/MT per the Census table), so the general
    # parser correctly declines. Confirmed live via nashuanh.gov's own
    # "Watch Nashua Community Media TV Anytime | Nashua, NH" page
    # describing this exact service (GOV TV 16, Nashua ETV Ch. 22, NPTV
    # Ch. 6, NCM-HD Ch. 1073) -- the same channel names appear verbatim
    # on this org token's own real TelVue page ("NASHUA ETV22", "NPTV
    # Ch. 6", "NCM-HD CH. 1073").
    "LGzST4YdA6GIkRCa0H5CwbVBptJRJ3XD": "Nashua, NH",
    # Uf_haH9SRhiC9hGsGoevnFKJwHM7n6eY: found 2026-08-29 auditing archived
    # pages missing a jurisdiction (a real, "Eye on Piscataway August
    # 2026"-titled meeting -- a talk-show-style title, not "X Board/
    # Council", so the title-guess path never even runs). Real alt text
    # "Piscataway Community TV - Piscataway Community TV VOD Player" has
    # no explicit state, so the general org-logo parser correctly
    # declines on it (same shape as Auburn Hills/Nashua above). Confirmed
    # unambiguous via `jurisdiction_enrich`'s own county-subdivisions
    # table: real, single-state NJ township, no collision.
    "Uf_haH9SRhiC9hGsGoevnFKJwHM7n6eY": "Piscataway, NJ",
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
            if not jurisdiction:
                jurisdiction = self._org_logo_jurisdiction(html)

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
        # Real bug, confirmed live 2026-08-29 auditing archived pages
        # missing a jurisdiction: two real, independent titles ("WB Board
        # of Selectmen Mtg" for West Bridgewater, MA; "MCS Board Mtg." --
        # an unconfirmed district) both matched this regex with an
        # all-caps 2-3 letter initialism as `name`, which enrich_
        # jurisdiction_text() then happily stored verbatim ("WB", "MCS")
        # since it never validates the base name any more than it does
        # for the "select"/"planning"/etc. stopwords above. No real US/CA
        # jurisdiction is a bare 2-3 letter all-caps initialism, so this
        # is a safe, general decline -- same "lose the recoverable case
        # over risking a wrong one" reasoning as the stopword list, just
        # keyed on shape (short + all-caps) rather than a specific word
        # list, since an initialism could be anything.
        if len(name) <= 3 and name.isupper():
            return None
        return name

    @staticmethod
    def _reduce_org_logo_piece(piece: str) -> Optional[str]:
        """One dash-separated segment of the org-logo alt text, reduced
        to a "City, ST" jurisdiction using only boilerplate-stripping and
        a state abbreviation already present in the text -- or None if it
        doesn't reduce to one. See the module comment above
        `_ORG_LOGO_LEADING_ENTITY_RE` for the real data this is built
        from and why it never falls back to a Census-table lookup for the
        state."""
        text = _ORG_LOGO_LEADING_ENTITY_RE.sub("", piece.strip()).strip()
        if not text:
            return None
        changed = True
        while changed:
            changed = False
            stripped = _ORG_LOGO_TRAILING_TVNUM_RE.sub("", text)
            if stripped != text:
                text = stripped.strip()
                changed = True
                continue
            lower = text.lower()
            for phrase in _ORG_LOGO_TRAILING_STOPWORDS:
                if lower.endswith(phrase) and len(text) > len(phrase):
                    text = text[: -len(phrase)].strip()
                    changed = True
                    break
        if not text:
            return None
        if _ORG_LOGO_CITY_STATE_RE.match(text):
            return text
        words = text.rsplit(None, 1)
        if len(words) != 2:
            return None
        name, maybe_state = words
        name = name.rstrip(",").strip()
        if not name or maybe_state.lower() not in US_STATE_ABBREVIATIONS:
            return None
        return f"{name}, {maybe_state.upper()}"

    @staticmethod
    def _org_logo_jurisdiction(html: str) -> Optional[str]:
        match = _ORG_LOGO_ALT_RE.search(html)
        if not match:
            return None
        # Drop the trailing "organization logo" boilerplate segment every
        # real sample ends with -- confirmed on every fixture/live fetch
        # in this file -- and reduce each remaining segment independently
        # (there can be 2 or 3+, e.g. Nashua's real "NCM - Nashua
        # Community Media - Nashua Government TV"). Only accept when every
        # segment that DOES reduce to a jurisdiction produces the exact
        # same "City, ST" string -- a segment that doesn't reduce at all
        # (no explicit state) is simply ignored, not treated as a
        # conflict, but two segments landing on the SAME city name with
        # DIFFERENT states (a real, plausible collision -- Springfield is
        # a real place in over 20 states) must decline rather than pick
        # either one, which comparing base names alone would have missed.
        parts = [p.strip() for p in match.group(1).split(" - ") if p.strip()]
        if parts and parts[-1].lower() == "organization logo":
            parts = parts[:-1]
        candidates = []
        for part in parts:
            reduced = TelvueAssetFinder._reduce_org_logo_piece(part)
            if reduced:
                candidates.append(reduced)
        if not candidates or len(set(candidates)) > 1:
            return None
        return candidates[0]

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
