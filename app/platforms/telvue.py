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
# WO-67, 2026-08-30: the separator before the trailing date was always a
# dash in every sample seen until the 2026-08-30 TelVue batch surfaced a
# real colon-separated title -- Summit, NJ's own real title is "Summit
# Planning Board Meeting: August 17, 2026" (confirmed live,
# /m/summit-planning-board-meeting-august-17-2026). A dash-only pattern
# never strips this, so the whole string (colon-date included) used to
# reach _BODY_SUFFIX_RE below, same "date never gets separated from the
# body" failure family as the leading-date bug documented on
# _LEADING_DATE_RE just below. `[-:]` covers both separators without
# widening what counts as "a date" on either side.
_TITLE_DATE_RE = re.compile(r"^(.*?)\s*[-:]\s*([A-Za-z]+ \d{1,2},? \d{4})$")
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
    #
    # Two more real cases, same shape, both WO-67 (2026-08-30):
    # "Planning Board" -- Summit, NJ's real title, once the colon-date
    # fix above strips the trailing date, is "Summit Planning Board
    # Meeting". Without its own alternative this matched bare "Board"
    # first, capturing "Summit Planning" (which the "planning" stopword
    # below then rejected outright, so the meeting resolved with NO
    # jurisdiction rather than a wrong one -- still a bug, just a
    # quieter one). "Common Council" -- Albany, NY's real governing-body
    # name, confirmed live via "Albany Common Council 08 03 26"
    # (/m/albany-common-albany-common-council-08-03-26); without its own
    # alternative this matched bare "Council" first, capturing "Albany
    # Common" -- a CONFIDENT WRONG answer, not just a missed one, since
    # "Albany Common" reads like a plausible place name on its own.
    #
    # Two more, WO-74 (2026-08-30 CDX batch-2 verification): "City
    # Commission" -- Rome, GA's real title "Rome City Commission
    # Meeting: August 24th, 2026" matched bare "Commission" first,
    # capturing "Rome City" -- which enrich_jurisdiction_text() then
    # resolves to "Rome City, IN" (a real, tiny, unrelated Indiana town
    # that happens to share the literal string "Rome City") -- a
    # CONFIDENT WRONG answer and a genuine wrong-state collision, not
    # just a missed one, same failure family as the Newmarket/Needham
    # entries in _KNOWN_ORG_TOKEN_JURISDICTIONS below. "Town Council" --
    # Truckee, CA's real title "Truckee Town Council, August 11, 2026"
    # matched bare "Council" first, capturing "Truckee Town" instead of
    # "Truckee" -- cosmetic (enrich_jurisdiction_text("Truckee") already
    # resolves unambiguously via the Census table), but the same
    # "generic word survives into the captured name" shape.
    r"^(.*?)\s+(City Council|Common Council|Town Council|Council|Planning and Environmental Commission|Planning Commission|City Commission|Planning Board|Select Board|Zoning Board|Board|Committee|Commission|Authority|District)\b",
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
    # WO-67, 2026-08-30: found auditing the same 2026-08-30 TelVue batch
    # that surfaced the colon-date and "Common Council" gaps above.
    # Real title is a bare "Monday, August 24, 2026" (/m/monday-
    # august-24-2026) -- no body-suffix phrase at all, so the title
    # guess never runs. Confirmed via this org's own real `id="org-logo"`
    # alt text, "Leominster TV (MA) - Leominster Access TV -
    # organization logo" -- the state IS present here but in parens
    # ("(MA)"), a shape `_reduce_org_logo_piece()` doesn't parse (it only
    # accepts a trailing bare 2-letter abbreviation), so the org-logo
    # fallback also declines on this one without this registry entry.
    # Independently confirmed via leominster.tv / Mass Access's own
    # directory listing for "Leominster Access Television (LTV)".
    "m-2Fvz8xhxNtIFGMxiGzJrgCaIr0cVZT": "Leominster, MA",
    # WO-67, 2026-08-30: same batch, same shape -- real title is a bare
    # "City Commission (2026-08-24)" (/m/2026-08-24-city-commission), no
    # body-suffix phrase for the title guess to run against. Confirmed
    # via this org's own real `id="org-logo"` alt text, "City of Royal
    # Oak Michigan - Royal Oak VOD Player - organization logo" -- the
    # state is spelled out in full ("Michigan") rather than as a 2-letter
    # abbreviation, which `_reduce_org_logo_piece()`'s state check
    # doesn't recognize (it only matches entries in
    # `US_STATE_ABBREVIATIONS`), so the org-logo fallback also declines
    # on this one without this registry entry. "Royal Oak" is otherwise
    # unambiguous in the Census place table (only one real match, MI).
    "aOt1iJYvW4IQawSCE8Goebgvo0CdBFwN": "Royal Oak, MI",
    # WO-67, 2026-08-30: same batch, same shape -- real title is a bare
    # "City Council Meeting (2026-08-25)" (/m/2026-08-25-city-council-
    # meeting), no body-suffix phrase for the title guess to run against.
    # This org's own real `id="org-logo"` alt text, "City of Luverne -
    # LuvTV VOD Player - organization logo", has no state anywhere (same
    # shape as Auburn Hills/Nashua/Piscataway above), so the general
    # org-logo parser correctly declines. "Luverne" is nationally
    # ambiguous (real places in MN and AL per the Census table) --
    # confirmed specifically MN via cityofluverne.org/luvtv, the City of
    # Luverne, Minnesota's own page for this exact "LuvTV" public-access
    # channel.
    "yHwj4ve7ki-YFodojv3bS3m9Y1sTcXCC": "Luverne, MN",
    # WO-74, 2026-08-30: the 16 entries below all come from a second CDX
    # `collapse=urlkey:64` enumeration pass (see
    # ~/Documents/rtr-business/research/cc_scan_data/
    # telvue_batch2_verified.json and _methodology.md for the full
    # per-token evidence -- second independent source URL + a live
    # resolve() check for every one). 23 org tokens were verified real in
    # that pass; 16 of them (not the research doc's own headline "17" --
    # re-derived directly from its `resolve_check.jurisdiction_bug` field,
    # see this WO's own report) resolve today with either a missing or a
    # wrong jurisdiction. None of these 16 jurisdictions are ingested into
    # Archive as of this WO -- this dict entry only fixes what a *future*
    # resolve/ingest of them would produce.
    #
    # Orange, CT: real title "Zoning Board of Appeals - Monday, November
    # 3, 2025" has no city prefix at all -- before this WO, the
    # leftmost-match search captured "Zoning" (the modifier before bare
    # "Board") as the jurisdiction, a confident wrong answer. Fixed by
    # adding "zoning" to _guess_jurisdiction()'s last-word stopword list
    # (same fix category as "conservation" below), which makes the guess
    # correctly come up empty so this registry entry applies via the
    # "if not jurisdiction" branch. Confirmed via orange-ct.gov's own
    # "Orange Government Access Television (OGAT)" page (Board of
    # Selectmen / Planning & Zoning coverage).
    "BUJHRRxhCf0u3AtXMrx7Sx7CjdW8zUFT": "Orange, CT",
    # Marlboro Township, NJ: real title "council 8-20-26 1" is bare,
    # lowercase, no city prefix -- the title-guess regex never matches at
    # all (no whitespace precedes "council" at the start of the string),
    # so the guess is already empty; this registry entry supplies the
    # jurisdiction outright. Confirmed via marlboro-nj.gov's own
    # "Marlboro TV" streaming page (Optimum 77 / FiOS 44).
    "1VSAEpYHq96Q6serFVh1RRX5Y_XOzuSA": "Marlboro Township, NJ",
    # Oradell, NJ: real titles are cryptic lowercase abbreviations ("mc
    # 8 25 26f hd" = Mayor & Council, "zb"/"pb" for Zoning/Planning
    # Board) with no city name and no recognizable body-suffix phrase --
    # the title guess never matches. Confirmed via oradell.org's own
    # "OPTV (Oradell Public Television)" page. Real 2785-segment
    # transcript exists on the sample checked (tier1-worthy once
    # ingested).
    "1VW_MUovXoKdUW9jRAnqt0YBpoJ5zDVU": "Oradell, NJ",
    # Miami Beach, FL: real title "Board of Adjustment Meeting: October
    # 11, 2024" has no city name anywhere -- the title guess correctly
    # comes up empty (no prefix before "Board"). Confirmed via
    # miamibeachfl.gov's own "MBTV" page (Commission/committee/Board of
    # Adjustment coverage).
    "0cCY8Wm5F5ODnSOeAaE0k0Lxsinvidcb": "Miami Beach, FL",
    # Berkley, MI: real title "Planning Commission" is bare, no city
    # name -- the title guess correctly comes up empty ("planning" is
    # already a last-word stopword). Confirmed via berkleymi.gov's own
    # WBRK-station page (City Council / Planning Commission coverage).
    # A distinct org token from the earlier-known Oakland-County
    # multi-city token Hejq7tDUseFZXc46e8pIxdl8NpmSEupd (a different,
    # CMNtv-run tenant that also happens to cover Berkley) -- not a
    # duplicate entry.
    "EJtfn8ouxWiUp9uEPl2tc6q8wbMfpV1O": "Berkley, MI",
    # Truckee, CA: real title "Truckee Town Council, August 11, 2026"
    # used to resolve "Truckee Town, CA" (an extra "Town" word) instead
    # of "Truckee, CA" -- fixed by adding "Town Council" as its own
    # _BODY_SUFFIX_RE alternative (parallel to the existing "City
    # Council"/"Common Council" entries), so the guess is now the
    # correct bare "Truckee", which already enriches to "Truckee, CA" via
    # the Census table on its own. This registry entry is belt-and-
    # suspenders, same reasoning as the Vail/Irondequoit entries above.
    # Confirmed via townoftruckee.com's own Town Council page.
    "EdhI2xtM1vAxHWMytVkqEFJ6vUupMLaS": "Truckee, CA",
    # Savannah, GA: real title "Savannah City Council 2/8/24" guesses the
    # correct bare "Savannah" but with no state -- a state fill, same
    # shape as the Ashland/OR and Stoneham/MA entries above, not an
    # override. Confirmed via savannahga.gov's own "Savannah Government
    # Television (SGTV)" and Council-Meeting-Schedule pages. Real
    # 2372-segment transcript on the sample checked (tier1-worthy once
    # ingested).
    "KPxII4Dm-djtTqV7JZXpXeOM2kiyqvRV": "Savannah, GA",
    # Madison, NH: the specific sample checked ("A Brief History of
    # Atkinson Park, Madison, NH") happened to be a non-meeting local-
    # history video with no body-suffix phrase, so the title guess comes
    # up empty; real dated meeting titles on the same channel ("Madison
    # Board of Selectmen - August 4, 2026") guess correctly to bare
    # "Madison" and are fixed the same way via the state-fill branch.
    # This org's own org-logo alt text is empty, so only this registry
    # entry closes the gap. Confirmed via madison-nh.org's own Board of
    # Selectmen page and vdoe-nh.org (an independent, unrelated village
    # district inside the town) both naming "Madison TV".
    "YhjrGzjr53TBI-xqCQGATh6xTOfUjhiy": "Madison, NH",
    # Tewksbury, MA: real title "Conservation Commission" is bare, no
    # city prefix -- before this WO, this matched bare "Commission",
    # capturing "Conservation" as the jurisdiction. Fixed by adding
    # "conservation" to _guess_jurisdiction()'s last-word stopword list
    # (same category as "zoning" above), so the guess now correctly comes
    # up empty. Confirmed via tewksbury-ma.gov's own Telemedia Department
    # and Select Board pages; this org's own org-logo alt text is empty,
    # so only this registry entry closes the gap.
    "eUhghhtERCG4gx5ywQy9U8mv66_FACrU": "Tewksbury, MA",
    # Gardner, MA: real title "Planning Board" is bare, no city name --
    # the title guess correctly comes up empty ("planning" is already a
    # last-word stopword). Confirmed via gardner-ma.gov's own "Gardner
    # Educational Television (GETV, Channel 8)" page (City Council /
    # School Committee / Planning & Zoning coverage).
    "f8r896ULmGZtrF3mCzOdRbTTP_Wnx2Q1": "Gardner, MA",
    # Stoughton, WI: real title "City Council 7/28/26" is bare, no city
    # name -- the title guess correctly comes up empty ("City" alone is
    # already an explicit reject). Confirmed specifically as the
    # Wisconsin city (not Stoughton, MA, which has no "City of"
    # government) via cityofstoughton.com and wsto.tv, both describing
    # WSTO's GOV channel as run by City of Stoughton IT/Media Services.
    # Real 3068-segment transcript on the sample checked (tier1-worthy
    # once ingested).
    "fSUt1ChllWIwWn_g28Mu3g-avz7I94a_": "Stoughton, WI",
    # Rome, GA (Rome-Floyd County joint government): REAL BUG, not just a
    # missing value. Real title "Rome City Commission Meeting: August
    # 24th, 2026" used to resolve to "Rome City, IN" -- enrich_
    # jurisdiction_text() treating the captured name "Rome City" (from
    # the title guess matching bare "Commission" and pulling in "City" as
    # part of the name) as the real, small Indiana town of that literal
    # name, a genuine wrong-STATE collision, same failure family as the
    # existing Newmarket/Needham entries above. Fixed by adding "City
    # Commission" as its own _BODY_SUFFIX_RE alternative (parallel to the
    # existing "City Council" entry), so the guess is now the correct
    # bare "Rome" -- this registry entry then corrects the state via the
    # base-name-match branch (enrich_jurisdiction_text("Rome") stays bare
    # with no state on its own, so the registry supplies "GA"). Confirmed
    # via romefloyd.com/rome/commission and floydcountyga.gov -- this
    # tenant covers both a Rome City Commission and a Floyd County Board
    # of Commissioners under one org token; "Rome, GA" is used here since
    # the sample checked was a City Commission meeting specifically.
    "iOiDZeQipT8NNECGBd7HJNiDkuPUTlCw": "Rome, GA",
    # Walpole, MA: real title "School Committee" is bare, no city name --
    # the title guess correctly comes up empty ("school" is already a
    # last-word stopword). Confirmed via walpole-ma.gov and
    # walpole.k12.ma.us, both independently confirming Walpole Media
    # broadcasts Select Board / School Committee meetings. Real
    # 1432-segment transcript on the sample checked (tier1-worthy once
    # ingested).
    "uZcpghEaKQJJjrP2iCkoRSkyKbNZPvO-": "Walpole, MA",
    # Long Hill Township, NJ: real title "LHT - Planing Board Mtg:
    # 8-11-26" (a real source typo, "Planing" for "Planning") used to
    # resolve the literal "LHT - Planing" as the jurisdiction -- the
    # leading "LHT" acronym-dash prefix is the same unreliable shape as
    # the existing bare "WB"/"MCS" initialism reject just above, just
    # with a dash-separated continuation instead of standing alone.
    # Fixed by declining any name starting with a short (2-5 letter)
    # all-caps acronym followed by " - " in _guess_jurisdiction(), so the
    # guess now correctly comes up empty. Confirmed via longhillnj.gov's
    # own Planning Board and Zoning Board of Adjustment pages, and this
    # channel's own real "Long Hill Township Memorial Day Parade" video
    # title spelling the name out in full.
    "ydrTBZKBSaGNTnGcCEGmbeMYupgFhhCk": "Long Hill Township, NJ",
    # Wilbraham, MA: real title "Select Board - 08-17-2026" is bare, no
    # city name -- the title guess correctly comes up empty ("select" is
    # already a last-word stopword). Confirmed via wilbraham-ma.gov's own
    # Broadband Advisory Committee and Select Board pages.
    "wCwBAXHtGCN-aqYz22Xuje-5ELUZawSc": "Wilbraham, MA",
    # Pipestone, MN: real title "Pipestone City Council Meeting 7.6"
    # guesses the correct bare "Pipestone" but with no state -- a state
    # fill, same shape as the Ashland/OR and Savannah/GA entries above.
    # Confirmed via progressivepipestone.com's own City Council page and
    # independent YouTube uploads of the same real meetings. Caution:
    # this tenant's catalog is dominated by unrelated school sports/
    # on-demand content (RTR/Edgerton/SWC high schools) -- use a real
    # dated council-meeting media id for any future ingest, not this
    # token's first/generic sample.
    "qDzDQ8k2993lxm2IqCNZjdoqxagPQUa_": "Pipestone, MN",
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
                        if is_likely_garbled(cues, lang=transcript_language):
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
        # "zoning"/"conservation" added WO-74 (2026-08-30, CDX batch-2
        # verification): Orange, CT's real "Zoning Board of Appeals -
        # Monday, November 3, 2025" and Tewksbury, MA's real
        # "Conservation Commission" are both BARE (no city prefix at
        # all), so the leftmost-match search matches "Board"/"Commission"
        # with "Zoning"/"Conservation" as group(1) -- neither is a real
        # jurisdiction name, same governance-generic shape as the four
        # words already here. Yes, this can also reject a real prefixed
        # name in an unconfirmed case ("Wayland Conservation Commission"
        # -> last word "conservation" -> rejected even though "Wayland"
        # was recoverable) -- same accepted tradeoff as "select"/
        # "planning"/"school" above, not a new one.
        if last_word in {
            "select",
            "planning",
            "school",
            "regular",
            "zoning",
            "conservation",
        }:
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
        # WO-74 (2026-08-30): Long Hill Township, NJ's real title "LHT -
        # Planing Board Mtg: 8-11-26" (a real source typo, "Planing" for
        # "Planning") matches this regex with name="LHT - Planing" -- the
        # leading "LHT" acronym is the same shape as the bare "WB"/"MCS"
        # initialisms just above, just with a dash-separated continuation
        # instead of standing alone, so the len<=3-and-upper check above
        # doesn't catch it. No real US/CA jurisdiction name is written as
        # a short all-caps acronym followed by " - ", so this declines on
        # shape, same reasoning as the bare-initialism check.
        if re.match(r"^[A-Z]{2,5}\s*-\s", name):
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
