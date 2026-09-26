"""ONE shared gate for "is this candidate really a meeting video?" (WO-933,
2026-09-21). Every place that decides this -- `verify_hub()`,
`generic_fallback.py`, the sweep and ingest scripts -- calls
`assess_video_candidate()` below instead of keeping its own copy of the
title lists, the risky-platform set or the decorative-video checks. Before
WO-933 those lived in six ingest scripts (`HIGH_RISK_TITLE_PLATFORMS`,
`MEETING_ALLOWLIST`, `PROMO_BLOCKLIST`, a substring or a word-boundary
`_looks_like_real_meeting()`), one more ladder script
(`_DECORATIVE_FILENAME_RE`) and three hand-read scripts, and they had
drifted apart (five of the copies still let "Larry J. Dix Boardroom" and
"Commissioners Tour Picatinny Arsenal's Revolutionary Roots" through).

The gate returns one of three verdicts, and NEVER guesses:

- `REJECT`: positive evidence the candidate is not a meeting recording
  (a decorative-asset host, a hero-embed parameter, a looping
  `<video>` with no controls, a test event, a promo or wrong-body title,
  a link that is not a video at all).
- `PASS`: positive evidence it is one (a governing-body word in the
  title, a meeting phrase next to the link on the page, or a caller who
  says it came from a per-meeting listing or a dedicated meeting
  platform).
- `CANNOT_TELL`: neither. The caller records that and does not treat it
  as accepted (an ingest script skips the row and logs the reason; a
  sweep records the video as "found but unverified"). A blank is a
  finding, never a gap to fill.

`classify_video_hand_check()` (the WO-191 phrase list, lifted out of
`scripts/wo174_pipeline.py` in WO-227, 2026-09-11) stays here too and is
one of the checks the gate runs, so `app/platforms/boxcast.py` and the
older sweep scripts that import it directly are unchanged.

`scripts/` has no top-level package the way `app/` does and `app/`
adapters must never depend on `scripts/` (the dependency only ever runs
the other way -- a sweep script imports the adapters it drives), so this
couldn't stay in `scripts/wo174_pipeline.py` once an adapter needed it
too. `scripts/wo174_pipeline.py` now imports `classify_video_hand_check`
from here instead of defining it locally -- every existing caller
(`scripts/wo216_access_ladder_sweep.py`, `scripts/wo217_handcheck.py`,
`tests/test_wo174_hand_check.py`, all of which import it off
`scripts.wo174_pipeline`) is unaffected, since that module still exposes
the same name.

Before a video is accepted, look at its own title/channel text for signs
it belongs to a DIFFERENT identifiable body (Kind A) or is real content
from what looks like this government's own channel but isn't a
deliberative meeting (Kind B). WO-191's own by-hand oEmbed audit of one
798-government batch found 8 of 80 "found" videos wrong on inspection,
every one from this exact gap: a school board, a state DOT district,
regional/multi-township commissions, a county assessor, and two
ceremonies/recruitment videos (see `BACKLOG_DONE.md`'s WO-191 entry for
the real, confirmed examples this phrase list is built from).

Deliberately conservative and phrase-based -- not a general classifier,
and it will not catch a mismatch that doesn't name itself in the
title/channel text (e.g. a proper-noun-only regional body whose name
doesn't contain any of these generic phrases). A miss here is not new
risk: WO-191's own by-hand oEmbed check remains the backstop this
doesn't replace, and every ingest this run makes is still available for
that same audit. A false trigger only costs one extra candidate-video
try (Kind B) or one skipped government whose real owner gets recorded
for a human to check (Kind A).
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

# Kind A: the title/channel names a different, identifiable body -- never
# this government's own meeting, regardless of gov_kind. Each phrase maps
# to a short, generic description of the likely real owner, for a human
# (WO-201's own cross-government cleanup) to follow up on -- these bodies
# mostly aren't in our own government registry at all (school districts,
# state DOT districts, and regional/multi-township commissions are a
# different KIND of entity than the general-purpose governments this
# project tracks), so no gov_id lookup is attempted here.
_HAND_CHECK_KIND_A_PHRASES = (
    ("school board", "the named school district's own board"),
    ("board of education", "the named school district's own board"),
    ("school committee", "the named school district's own committee"),
    ("board of assessors", "a county/regional assessor's office"),
    ("county assessor", "the named county's assessor's office"),
    (
        "department of transportation",
        "a state department of transportation district office",
    ),
    ("state police", "a state police barracks/troop, not a local government"),
    ("council of governments", "a regional council of governments"),
    (
        "regional planning commission",
        "a regional, multi-jurisdiction planning commission",
    ),
    (
        "metropolitan planning organization",
        "a regional metropolitan planning organization",
    ),
    ("river commission", "a regional, multi-jurisdiction river/watershed commission"),
    ("watershed commission", "a regional, multi-jurisdiction watershed commission"),
    ("interstate commission", "a multi-state regional commission"),
    # WO-230, 2026-09-11: a county government page linked a state court
    # system's own public-information video (real example: Woodford
    # County, IL's `/Government` page linked a "IllinoisCourts"-channel
    # video titled "Illinois Jury Orientation" -- the state judicial
    # branch's own jury-service orientation, not a Woodford County
    # meeting). The court system is a real, separate public body from
    # the county/city government that happened to link to it. Multi-word
    # on purpose -- a bare "court" phrase would false-positive on a
    # parks-and-rec tennis/basketball court.
    ("jury orientation", "a state or county court system's own jury-service video"),
    ("jury duty", "a state or county court system's own jury-service video"),
    ("circuit court", "a state or county circuit court, not the general government"),
    (
        "clerk of the circuit court",
        "the circuit court clerk's office, not the general government",
    ),
)

# Kind B: content that looks like it's from this government's own channel
# but isn't a deliberative meeting -- try the next candidate video
# instead of ingesting this one.
_HAND_CHECK_KIND_B_PHRASES = (
    "swearing in",
    "swearing-in",
    "oath of office",
    "inaugural ceremony",
    "ribbon cutting",
    "ribbon-cutting",
    "groundbreaking",
    "ground breaking",
    "why run for",
    "run for city council",
    "run for town council",
    "run for township",
    "candidate forum",
    "meet the candidates",
    "recruitment video",
    "award ceremony",
    "recognition ceremony",
)


# State DOT district/region channels are commonly named by gluing a
# state abbreviation straight onto "DOT" with no space or punctuation
# ("PennDOT District 6-0", "NYSDOT Region 8", "CTDOT District 3") --
# a plain word-bounded "department of transportation" phrase never
# matches that shape, so this is checked separately, unanchored at the
# start (deliberately, to match inside "penndot") but still requiring
# "district"/"region" right after "dot" so a state's OWN transportation
# department meeting doesn't get flagged if it somehow named itself with
# a full "Department of Transportation" phrase elsewhere (already caught
# by the phrase list above) while a completely unrelated word ending in
# "dot" (there are essentially none in real channel names) doesn't
# false-positive on the word "district"/"region" alone.
_STATE_DOT_CHANNEL_RE = re.compile(r"dot\s+(district|region)\b")


def _hand_check_phrase_hit(haystack_lower: str, phrase: str) -> bool:
    return re.search(r"\b" + re.escape(phrase) + r"\b", haystack_lower) is not None


# WO-1076 addendum (Ryan, 2026-09-25): a hand-check of calibration set D's
# weak leads found 10 real false positives -- Glendale USD, Nassau County
# SD (FL), Prince George County Public Schools (VA), South Windsor SD,
# Baltimore County PS, Calvert County PS, Midland PS, Falmouth Schools
# (ME), South Pasadena USD, Lake Oswego SD -- every one a school
# district's OWN board/committee meeting, rejected by the very phrases
# above ("school board"/"board of education"/"school committee") that
# exist to catch a DIFFERENT government's video. The same rejection is
# right when the searched government is a town/city (Coventry CT,
# Springfield MA, Sanford ME, Windsor CT all got their school district's
# board, not their own). These three phrases are the only ones in
# `_HAND_CHECK_KIND_A_PHRASES` that can ever name the searched
# government's OWN body -- every other phrase there (a county assessor, a
# state DOT district, a regional commission, a court system) never does,
# whatever `gov_kind` is, so this set stays narrow on purpose.
_SCHOOL_DISTRICT_OWN_BODY_PHRASES = frozenset(
    {"school board", "board of education", "school committee"}
)


def _gov_kind_is_school_district(gov_kind) -> bool:
    """Accepts either the registry's own `gov_type` spelling
    (`app.utils.gov_registry.classify.SCHOOL_DISTRICT`, `"school_district"`)
    or a plain-English research-CSV value (`"school district"`, `"sd"`) --
    callers pass either shape (see this function's own call site)."""
    normalized = (gov_kind or "").strip().lower().replace(" ", "_")
    return normalized in ("school_district", "sd")


def classify_video_hand_check(title, channel_text, gov_name, gov_kind):
    """Returns None (no concern), or (kind, reason) where kind is "A" or
    "B" -- see module comment above. `channel_text` is whatever channel-
    derived text the adapter already resolved (YouTube's `video_channel`
    handle plus its own validated `jurisdiction` guess -- see
    `resolve_candidate()`'s caller) -- no extra network call is made
    here, this only reads fields the resolve step already populated.

    `gov_kind`: used ONLY to un-reject a school district's own board/
    committee meeting (`_SCHOOL_DISTRICT_OWN_BODY_PHRASES`) when the
    government being searched IS a school district -- see that
    constant's own comment for the real false positives this fixes.
    Every other Kind A/B phrase stays gov_kind-independent, since none of
    them can ever be the searched government's own meeting (`gov_name`
    itself remains unused by today's phrase list for the same reason --
    accepted for a future, more targeted check)."""
    title_low = (title or "").lower()
    channel_low = (channel_text or "").lower()
    haystack = f"{title_low} {channel_low}"
    is_school_district = _gov_kind_is_school_district(gov_kind)

    for phrase, owner_hint in _HAND_CHECK_KIND_A_PHRASES:
        if is_school_district and phrase in _SCHOOL_DISTRICT_OWN_BODY_PHRASES:
            continue
        if _hand_check_phrase_hit(haystack, phrase):
            return ("A", f"{owner_hint} (matched {phrase!r})")

    if _STATE_DOT_CHANNEL_RE.search(haystack):
        return (
            "A",
            "a state department of transportation district/region office "
            "(matched a 'DOT district/region'-shaped channel name)",
        )

    for phrase in _HAND_CHECK_KIND_B_PHRASES:
        if _hand_check_phrase_hit(title_low, phrase):
            return ("B", f"title suggests non-meeting content (matched {phrase!r})")

    return None


# ===========================================================================
# WO-933 (2026-09-21): the shared gate.
# ===========================================================================

PASS = "pass"
REJECT = "reject"
CANNOT_TELL = "cannot_tell"


@dataclass(frozen=True)
class GateVerdict:
    """One gate answer. `verdict` is PASS, REJECT or CANNOT_TELL. `reason`
    is a short machine-readable tag (stable enough to tabulate). `detail`
    is one plain sentence for a report or a CSV note."""

    verdict: str
    reason: str
    detail: str = ""

    @property
    def tag(self) -> str:
        return f"{self.verdict}:{self.reason}"

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    @property
    def rejected(self) -> bool:
        return self.verdict == REJECT

    @property
    def undecided(self) -> bool:
        return self.verdict == CANNOT_TELL

    def skip_note(self) -> str:
        """Text for a sweep's "skipped because" reason. It STARTS with the
        phrase every sweep's reject-reason map already keys on ("title looks
        like a non-meeting video", `_CONTENT_TAXONOMY` in the WO-147/149/152
        ladder scripts and `backfill_wo134_ingest_into_jc.py`), so no
        downstream classification changes; the gate's own tag says whether
        it rejected or could not tell."""
        how = "gate could not tell" if self.undecided else "gate rejected"
        return (
            f"title looks like a non-meeting video ({how}, {self.tag}: {self.detail})"
        )


# Platforms whose candidate needs real meeting evidence (a governing-body
# word in the title, or a meeting phrase next to the link) before it is
# trusted, because the host also carries things that are not meetings.
# The ONE definition: six ingest scripts each used to define their own
# `{"youtube", "vimeo"}` and `scripts/wo145_api_first_sweep.py` kept a
# wider local set, so the same candidate was judged differently by
# different scripts.
#
# - youtube, vimeo: general video hosts (WO-134..149: 7 of 16 real channel-
#   listing hits and 62 of 64 real homepage Vimeo/direct hits were not
#   meetings).
# - cablecast: a general community-access broadcast platform. Confirmed
#   live 2026-09-10 (WO-145): Hometown, IL's tenant resolved "Weekly Chat,
#   Explosion in E-Learning!" and "Case Study: HCAM" as meetings. The real
#   Cablecast fixtures show the same mix: "Maple Grove Report 3/4/2025" is
#   a show, while "City Council Regular meeting - 8/24/2026" (Urbana),
#   "Beer Board Meeting - April 6, 2026" (Smyrna), "Council Meeting - June
#   22, 2026" (Charlotte) and "City Council Meeting 2026-09-08"
#   (Dyersville) all carry an allowlist word, so a real meeting still passes.
# - swagit: added defensively. It is a meeting-video vendor, no live false
#   positive has been seen, and `scripts/wo145_api_first_sweep.py` already
#   applied it to enumerator hits. The real Swagit titles on file ("Jun 02,
#   2025 Planning Commission - Middleburg, VA", "Jan 13, 2026 City Council
#   - Dublin, CA") pass. A Swagit title with no body word ("Budget
#   Workshop") comes back CANNOT_TELL, which an ingest script records and
#   skips, never a wrong page.
#
# `direct_file` is handled separately (see `_needs_evidence`): it has no
# title at all, so it can only be judged from the page around the link.
HIGH_RISK_TITLE_PLATFORMS = frozenset({"youtube", "vimeo", "cablecast", "swagit"})

MEETING_ALLOWLIST = (
    "council",
    "commission",
    "board",
    "committee",
    "meeting",
    "session",
    "hearing",
    "authority",
    "trustees",
    "supervisors",
    "assembly",
    "selectboard",
    "select board",
    # "Board of County Commissioners" abbreviation -- real, confirmed-live
    # false negative caught in WO-149's own 30-row county pilot
    # (2026-09-10): Tulsa County OK's own YouTube channel titles its real
    # commission meetings "BOCC Livestream - December 1, 2025", which
    # contains neither "board" nor "commission" as a substring and was
    # rejected as off-mission before this was added.
    "bocc",
)
PROMO_BLOCKLIST = (
    "promo",
    "advertisement",
    "commercial",
    "psa",
    "public service announcement",
    "how to",
    "tutorial",
    "instructional",
    "training video",
    "orientation video",
    "welcome",
    "message from the mayor",
    "highlight reel",
    "sizzle reel",
    "ribbon cutting",
    "parade",
    "test stream",
    "test broadcast",
    "sample video",
    "demo video",
    "career",
    "job fair",
    "recruitment",
    "state of the city",
    "year in review",
    "commercial break",
    "tour of",
    # Real, confirmed-live false positive caught by WO-187 (2026-09-11):
    # Capitol Heights, MD's YouTube channel titled a real clip "Council
    # Member Victor James Sr interview for N'style back to school block
    # party" -- "Council" alone satisfies MEETING_ALLOWLIST, and nothing
    # here caught that the video is a promotional interview, not a
    # meeting recording. Ingested live before being caught by hand;
    # flagged for deletion (BACKLOG_DONE.md's WO-187 entry).
    "interview",
)


def contains_word(text: str, phrase: str) -> bool:
    """Word-boundary match, not a bare substring test. Real, confirmed-
    live false positive caught in WO-149's own county sweep (2026-09-10):
    a plain `"board" in title` check passed "Larry J. Dix Boardroom" --
    a YouTube channel's persistent room-name livestream title, not a
    meeting -- straight through to a live 59-second Archive page. Every
    other MEETING_ALLOWLIST/PROMO_BLOCKLIST entry is a real word or
    phrase too, so this closes the same class of bug for all of them,
    not just "board". (Five older script copies kept the plain substring
    test until WO-933 replaced them with this one.)"""
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


def decode_filename_text(url: Optional[str]) -> Optional[str]:
    """A URL's filename/path, turned into space-separated words so
    `contains_word()`'s `\\b` matching can actually see them (WO-1049).

    Two real, confirmed gaps this closes, both from `assess_meeting_
    evidence()` reading a raw URL as one of its evidence texts:

    (1) A percent-encoded URL still has its OWN literal characters glued
    together after encoding -- `unquote()` alone isn't enough. Real case:
    "...%282026-09-22%29%20City%20Council%20Special%20Meeting.mp4"
    decodes to "...(2026-09-22) City Council Special Meeting.mp4", but the
    `0` in what was "%20" sits directly against "Council" with no `\\b`
    between them (both are `\\w` characters) -- `contains_word()` never
    matches "council" there.

    (2) An underscore-joined filename has the same problem with no
    percent-encoding involved at all -- an underscore counts as a `\\w`
    character in Python's `re` module, so e.g.
    "2025_01_07_Reorganization_Meeting_1.mp3" glues "Reorganization" and
    "Meeting" to their neighboring digits with no boundary either (no
    confirmed real example of this shape yet; a hyphen-joined filename
    like Bound Brook NJ's real
    "1-7-2025-Bound-Brook-Borough-Reorganization-Meeting-1.mp3" already
    matches without decoding, since a hyphen is not a `\\w` character).

    Replacing `_-.+` with spaces after `unquote()` fixes both, and leaves
    an already-matching hyphenated name matching just the same: the
    decoded text becomes "( 2026 09 22) City Council Special Meeting mp4"
    / "1 7 2025 Bound Brook Borough Reorganization Meeting 1 mp3", and
    "council"/"meeting" sit on real word boundaries either way."""
    if not url:
        return None
    from urllib.parse import unquote

    return re.sub(r"[_\-.+]", " ", unquote(url))


def blocklisted_word(title: Optional[str]) -> Optional[str]:
    t = (title or "").lower()
    for word in PROMO_BLOCKLIST:
        if contains_word(t, word):
            return word
    return None


def allowlisted_word(title: Optional[str]) -> Optional[str]:
    t = (title or "").lower()
    for word in MEETING_ALLOWLIST:
        if contains_word(t, word):
            return word
    return None


def looks_like_real_meeting(title: str, *, require_allowlist: bool = False) -> bool:
    """The title-only half of the gate, kept as a plain boolean for the
    scripts that only ever asked this one question. Blocklist first (a
    blocklisted word always loses), then, when `require_allowlist`, a
    governing-body word must be present. Prefer `assess_video_candidate()`
    where the caller has more than a title to offer.

    `require_allowlist=True` is for the highest-risk case: one video found
    by a generic scan of a general-purpose video host, with no per-meeting
    listing behind it. Real, confirmed-live gap found running
    `nationwide_2404_ingest.py` on 2026-09-07, AFTER the blocklist-only
    check already caught Grandview WA's promo video: a blocklist alone
    missed Colfax, WA's real queued title, "Colfax, Washington on the
    Palouse Scenic Byway" (a tourism video). No blocklist word describes
    every way a non-meeting video can be titled, so for this risk class the
    check is flipped to require a real meeting signal. NOT applied to
    CivicPlus/CivicClerk/Legistar/Municode Meetings listing candidates:
    those come from a per-meeting system by construction (a CivicPlus row
    with the default title "Untitled meeting" is still a meeting)."""
    if blocklisted_word(title):
        return False
    if require_allowlist and not allowlisted_word(title):
        return False
    return True


# A test upload, not a meeting. Real: Forest Park city, GA's CivicClerk
# event is literally titled "TEST 3" with no agenda (WO-348, hand-read).
# Only a title that is nothing BUT "test" and an optional number matches. The
# entry this comes from wrote it as `^TEST\b`, but that would also reject a
# title like "Test City Council Meeting" (a fixture in
# `tests/test_wo222_gov_id_ingest_payload.py` caught exactly that), and the
# one real example is the number form. "test stream" / "test broadcast" are
# already on the blocklist for anywhere in a title.
_TEST_TITLE_RE = re.compile(r"^\W*test\W*\d*\W*$", re.IGNORECASE)

# A camera file name or bare number is not a title. Real: Oak Bluffs, MA's
# Vimeo video "video1516165031" (page 10200, WO-925). The three patterns
# are exactly the ones that entry named; do not add more without a real
# example. A placeholder title carries no meeting evidence either way, so
# the gate treats it as "no title", never as a reject.
_PLACEHOLDER_TITLE_RES = (
    re.compile(r"^video\d+$", re.IGNORECASE),
    re.compile(r"^img_\d+", re.IGNORECASE),
    re.compile(r"^\d+$"),
)


def is_placeholder_title(title: Optional[str]) -> bool:
    t = (title or "").strip()
    return bool(t) and any(r.search(t) for r in _PLACEHOLDER_TITLE_RES)


# --- Decorative and not-a-video checks (no network, no page needed) -------

# Third-party embed hosts whose "videos" are page furniture, never a
# meeting. Match by HOST, not by the path: an embed can ship a differently
# named file on the same host. Real: `a0.muscache.com/videos/search-bar-
# icons/hevc/house-twirl-selected.mov`, an Airbnb embed's own UI animation,
# matched as a video on two unrelated governments (Ferdinand town, IN and
# Council Grove city, KS, WO-284). Add a host only with a real example.
DECORATIVE_ASSET_HOSTS = ("muscache.com",)

# Filename tokens of a decorative homepage video. Built from real hits
# (WO-355/361/364/368, tokens added by WO-909, "videobg"/"background" by WO-933
# for Dummerston town, VT's real `img/videobg.mp4`, named in BACKLOG.md's
# "verdict off verify_hub()'s bare-homepage fallback" entry): a production
# reel, a tourism clip, a drone flyover, a hero banner, a background loop.
# Applied to the URL PATH only, and only where the caller says the link came
# off a bare homepage scan (`check_filename=True`): a real meeting file is
# very unlikely to carry one of these, but a per-meeting listing already
# vouches for its rows, and a false reject on a real listed meeting would
# cost more than a miss.
_DECORATIVE_FILENAME_RE = re.compile(
    r"(promo|promotion|accueil|welcome|tourism|flyover|drone|dji_|"
    r"site.?asset|homepage|hero|banner|banniere|placeholder|discover|explore|"
    r"videobg|background)",
    re.IGNORECASE,
)

_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
        "www.youtu.be",
    }
)


def _parsed(url: Optional[str]):
    try:
        return urlparse((url or "").strip())
    except ValueError:
        return None


def decorative_url_reason(url: Optional[str], *, check_filename: bool = False):
    """A short tag when the URL's own shape says "decorative", else None.

    - A decorative-asset host (`DECORATIVE_ASSET_HOSTS`).
    - Vimeo's hero-embed query signature: `background=1`, or `loop=1`
      (WO-355 confirmed `background=1` / `loop=1`+`muted=1` on 20 real
      government tenants; WO-909 found a real hero embed with `loop=1`
      alone, so `loop=1` is enough).
    - With `check_filename=True`, a decorative filename token in the path.
    """
    parsed = _parsed(url)
    if parsed is None or (not parsed.netloc and not parsed.path):
        return None
    host = (parsed.hostname or "").lower()
    for asset_host in DECORATIVE_ASSET_HOSTS:
        if host == asset_host or host.endswith("." + asset_host):
            return f"decorative_asset_host:{asset_host}"
    params = parse_qs(parsed.query.lower())
    if "1" in params.get("background", []):
        return "hero_embed_parameter:background=1"
    if "1" in params.get("loop", []):
        return "hero_embed_parameter:loop=1"
    if check_filename:
        match = _DECORATIVE_FILENAME_RE.search(parsed.path)
        if match:
            return f"decorative_filename:{match.group(1).lower()}"
    return None


def not_a_real_video_link_reason(url: Optional[str]):
    """A short tag when the link is not a video or a channel at all, else
    None. Real WO-912/913 hand-read finds that were "found" as videos: a
    bare `youtube.com`, a YouTube search-results page, a YouTube Shorts
    clip (too short to be a meeting), an embed with no id, a Google
    sign-in check. A real channel link (`youtube.com/@handle`) is NOT
    rejected here: it is a valid channel lead."""
    parsed = _parsed(url)
    if parsed is None:
        return None
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").rstrip("/")
    if host == "accounts.google.com" or "servicelogin" in path.lower():
        return "google_sign_in_page"
    if host in _YOUTUBE_HOSTS:
        if path == "":
            return "bare_youtube_host"
        if path.startswith("/results"):
            return "youtube_search_page"
        if path == "/shorts" or path.startswith("/shorts/"):
            return "youtube_short"
        if path == "/embed":
            return "youtube_embed_without_id"
        if path == "/watch" and not parse_qs(parsed.query).get("v"):
            return "youtube_watch_without_id"
    return None


def structural_reject(
    video_url: Optional[str],
    *,
    title: Optional[str] = None,
    check_filename: bool = False,
) -> Optional[GateVerdict]:
    """The checks that need no page and no government name: not a video
    link, a decorative URL shape, a test event title. Returns a REJECT
    verdict, or None. This is the whole check a per-meeting listing walk
    runs (it must not judge a listed row's title beyond "test"), and the
    first step of `assess_video_candidate()`."""
    reason = not_a_real_video_link_reason(video_url)
    if reason:
        return GateVerdict(REJECT, reason, "the link is not a video or a channel")
    reason = decorative_url_reason(video_url, check_filename=check_filename)
    if reason:
        return GateVerdict(
            REJECT,
            reason,
            "the link's own address is the shape of a decorative page video",
        )
    if title and _TEST_TITLE_RE.search(title):
        return GateVerdict(
            REJECT, "test_title", f"the title reads like a test upload: {title!r}"
        )
    return None


# --- What the page around a link says -------------------------------------

# A meeting phrase next to a link on the page. From `scripts/wo355_handread.py`
# / `wo364_handread.py`'s `_MEETING_CONTEXT_RE`, the working reference from
# the WO-355 hand-read of 64 candidates, with two tightenings: a bare
# "minutes" ("in just 3 minutes") and a bare "board of " (a school or tourism
# board) no longer count, and a body word followed within a few words by
# meeting/session/hearing does.
_MEETING_CONTEXT_RE = re.compile(
    r"(\bagenda|"
    r"\b(council|board|commission|committee|trustees|supervisors)\W+"
    r"(?:\w+\W+){0,3}(meeting|session|hearing)\b|"
    r"\b(regular|special|public)\s+(meeting|hearing)\b|\bwork\s+session\b|"
    r"\bmeeting\s+(minutes|archive|recording|video)|\bwatch\s+live\b|"
    r"\bs[ée]ance\b|\bconseil\s+municipal\b)",
    re.IGNORECASE,
)

_LINK_TAGS = ("a", "iframe", "video", "source")
_NO_CONTEXT_ANCESTORS = ("body", "html", "[document]")


@dataclass(frozen=True)
class PageEvidence:
    """What the page itself says about one link on it. `found` is False
    when the link could not be located in the HTML at all (then nothing
    here is evidence). `context` is the visible text next to the link.
    `hero_reason` is set when the link sits in a looping `<video>` with no
    controls, the homepage hero-banner shape."""

    found: bool = False
    context: str = ""
    hero_reason: Optional[str] = None

    @property
    def has_meeting_context(self) -> bool:
        return (
            bool(self.context) and _MEETING_CONTEXT_RE.search(self.context) is not None
        )


def _without_fragment(url: str) -> str:
    return urlparse(url)._replace(fragment="").geturl()


@lru_cache(maxsize=8)
def _parse_html(html: str):
    """One parse per page, however many links on it are checked (a bare
    homepage scan asks about every recognised link in turn). The tree is
    only ever read, never changed, so sharing it is safe."""
    return BeautifulSoup(html, "html.parser")


def _context_text(tag, video) -> str:
    parts = [tag.get_text(" ", strip=True)]
    for attr in ("title", "aria-label", "alt"):
        value = tag.get(attr)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if video is not None:
        value = video.get("title")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    # The largest container (up to three levels up) that is still small
    # enough to be "the card this link sits in", never the whole page: a
    # homepage nav that says "Agendas" must not make every link look like a
    # meeting.
    node, best = tag.parent, ""
    for _ in range(3):
        if node is None or node.name in _NO_CONTEXT_ANCESTORS:
            break
        text = node.get_text(" ", strip=True)
        if len(text) > 400:
            break
        best = text
        node = node.parent
    parts.append(best)
    return " ".join(p for p in parts if p)


def page_evidence(
    html: Optional[str], link_url: Optional[str], page_url: str = ""
) -> PageEvidence:
    """Finds `link_url` among the page's own `<a>`/`<iframe>`/`<video>`/
    `<source>` tags and reports the hero-banner markup and the nearby text.
    Pure (no network). Real calibration, all in `tests/fixtures/`: the three
    real homepages with a hero video (McLeansboro IL, Atlantic City NJ,
    Union Grove WI) all use `<video ... autoplay muted loop>` with no
    `controls`; none of the real meeting-player pages on file has a `loop`
    attribute."""
    if not html or not link_url:
        return PageEvidence()
    try:
        soup = _parse_html(html)
    except Exception:  # noqa: BLE001 -- a page the parser rejects is "no evidence"
        return PageEvidence()
    target = _without_fragment(link_url)
    base = page_url or link_url
    found, hero, contexts = False, None, []
    for tag in soup.find_all(_LINK_TAGS):
        matched = False
        for attr in ("href", "src", "data-src"):
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                if _without_fragment(urljoin(base, value.strip())) == target:
                    matched = True
                    break
        if not matched:
            continue
        found = True
        video = None
        if tag.name == "video":
            video = tag
        elif tag.name == "source":
            video = tag.find_parent("video")
        if (
            video is not None
            and video.has_attr("loop")
            and not video.has_attr("controls")
        ):
            hero = hero or "looping_video_without_controls"
        contexts.append(_context_text(tag, video))
    return PageEvidence(
        found=found,
        context=" ".join(c for c in contexts if c)[:1200],
        hero_reason=hero,
    )


def prescreen_homepage_link(
    html: Optional[str], page_url: str, link_url: str, *, check_filename: bool = True
) -> Optional[GateVerdict]:
    """The reject-only checks for a link found by a bare homepage scan,
    run BEFORE the link is resolved: structural shape, decorative
    filename, and the looping-hero-video markup. Returns a REJECT verdict
    or None. Used as `find_platform_link(..., accept=...)`'s predicate so
    a decorative first link no longer shadows a real one further down."""
    verdict = structural_reject(link_url, check_filename=check_filename)
    if verdict is not None:
        return verdict
    evidence = page_evidence(html, link_url, page_url)
    if evidence.hero_reason:
        return GateVerdict(
            REJECT,
            f"hero_video_markup:{evidence.hero_reason}",
            "the link sits in a looping video with no player controls, the "
            "homepage banner shape",
        )
    return None


# --- Same organization ------------------------------------------------------

_NAME_STOPWORDS = frozenset(
    {
        "the", "and", "city", "town", "village", "county", "township", "borough",
        "parish", "municipality", "municipal", "government", "district", "school",
        "schools", "regional", "state", "board", "department", "authority",
        "commission", "council", "unified", "independent", "metropolitan",
        "utility", "utilities", "public", "of", "for",
    }
)  # fmt: skip


def _distinctive_name_words(gov_name: Optional[str]) -> list:
    words = re.findall(r"[a-z0-9]+", (gov_name or "").lower())
    return [w for w in words if len(w) >= 3 and w not in _NAME_STOPWORDS]


def _site_host(url: Optional[str]) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = _parsed(raw if "://" in raw else f"https://{raw}")
    host = ((parsed.hostname if parsed else "") or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_organization_flag(
    page_url: Optional[str],
    gov_name: Optional[str],
    *,
    gov_domain: Optional[str] = None,
) -> Optional[GateVerdict]:
    """A CANNOT_TELL verdict when the page a link was found on looks like
    somebody else's site, else None. Never a REJECT: real regional and
    shared cable-access channels carry no name overlap at all (Shorewood
    city, MN's real Cablecast clip is on `reflect-lmcc.cablecast.tv`), so a
    no-overlap page is flagged for a human look, not thrown away.

    The rule is the one measured in `BACKLOG.md` on WO-912's 225 hand-read
    finds (57 wrong, 80 right): flag when the page is on another site AND
    that site's address holds no distinctive word of the government's name.
    On those finds it flagged 47 of the 57 wrong ones and 4 of the 80 right
    ones. WO-933 built it from that measurement and did NOT re-run the
    measurement (the hand-read data lives outside this repo).

    The page is "the government's own site" when its host equals or sits
    under `gov_domain` (the recorded website), or when its host contains a
    distinctive word of the name (`garfieldnj.gov` holds "garfield").
    """
    page_host = _site_host(page_url)
    words = _distinctive_name_words(gov_name)
    if not page_host or not words:
        return None
    own = _site_host(gov_domain)
    if own and (page_host == own or page_host.endswith("." + own)):
        return None
    compact = re.sub(r"[^a-z0-9]", "", page_host)
    if any(w in compact for w in words):
        return None
    return GateVerdict(
        CANNOT_TELL,
        "other_organization_site",
        f"the link was found on {page_host}, whose address holds no distinctive "
        f"word of {gov_name!r}; a human should look before trusting it",
    )


# --- The composed gate ------------------------------------------------------


def _needs_evidence(platform: Optional[str], structured: bool) -> bool:
    """True when this candidate must show real meeting evidence. A per-
    meeting listing row (`structured=True`) is evidence on its own, and a
    platform built only for government meetings (Granicus, CivicClerk,
    Legistar, ...) is too. A general video host, a bare direct file or an
    unknown platform is not."""
    if structured:
        return False
    p = (platform or "").lower()
    return p in HIGH_RISK_TITLE_PLATFORMS or p in ("direct_file", "unknown", "")


def assess_video_candidate(
    *,
    title: Optional[str] = None,
    video_url: Optional[str] = None,
    platform: Optional[str] = None,
    structured: bool = False,
    channel_text: Optional[str] = None,
    gov_name: Optional[str] = None,
    gov_kind: Optional[str] = None,
    evidence: Optional[PageEvidence] = None,
    page_url: Optional[str] = None,
    gov_domain: Optional[str] = None,
    check_filename: bool = False,
    require_evidence: Optional[bool] = None,
) -> GateVerdict:
    """Is this candidate really a meeting video? Returns PASS, REJECT or
    CANNOT_TELL, never a guess (see the module docstring).

    Order: (1) structural rejects (not a video link, decorative URL shape,
    test title); (2) the looping-hero-video markup, when `evidence` from
    `page_evidence()` is given; (3) the WO-191 Kind A/B phrase list, on the
    title and channel text; (4) the promo blocklist; (5) evidence -- a
    caller's `structured` claim, a dedicated meeting platform, a governing-
    body word in the title, or a meeting phrase next to the link
    (`evidence.has_meeting_context`); (6) a same-organization flag, which
    turns a PASS into CANNOT_TELL when `page_url` and `gov_name` show the
    link came off another organization's site.

    `structured=True` means the caller took this candidate from a per-
    meeting listing (a CivicPlus AgendaCenter row, a CivicClerk event, a
    Legistar meeting): the listing is the evidence. `require_evidence`
    overrides the platform-based default (`_needs_evidence`) for callers
    that have already decided, as the older sweep scripts had.
    """
    verdict = structural_reject(video_url, title=title, check_filename=check_filename)
    if verdict is not None:
        return verdict

    if evidence is not None and evidence.hero_reason:
        return GateVerdict(
            REJECT,
            f"hero_video_markup:{evidence.hero_reason}",
            "the link sits in a looping video with no player controls, the "
            "homepage banner shape",
        )

    hand_check = classify_video_hand_check(title, channel_text, gov_name, gov_kind)
    if hand_check is not None:
        kind, why = hand_check
        return GateVerdict(REJECT, f"hand_check_kind_{kind.lower()}", why)

    word = blocklisted_word(title)
    if word:
        return GateVerdict(
            REJECT, "promo_title", f"the title contains {word!r}: {title!r}"
        )

    need = (
        require_evidence
        if require_evidence is not None
        else _needs_evidence(platform, structured)
    )
    if not need:
        result = GateVerdict(
            PASS,
            "structured_listing" if structured else "dedicated_meeting_platform",
            "no negative signal, and the source is a per-meeting listing or a "
            "platform built for government meetings",
        )
    else:
        body_word = allowlisted_word(title)
        if body_word:
            result = GateVerdict(
                PASS,
                "title_names_governing_body",
                f"the title contains {body_word!r}",
            )
        elif evidence is not None and evidence.has_meeting_context:
            result = GateVerdict(
                PASS,
                "page_context_names_meeting",
                "the text next to the link on the page names a meeting",
            )
        else:
            if is_placeholder_title(title):
                reason = "placeholder_title"
                detail = f"the title {title!r} is a camera file name, not a title"
            elif not (title or "").strip():
                reason = "no_title"
                detail = "no title to read, and no meeting text next to the link"
            else:
                reason = "no_meeting_word_in_title"
                detail = (
                    f"the title {title!r} names no governing body, and no "
                    "meeting text sits next to the link"
                )
            result = GateVerdict(CANNOT_TELL, reason, detail)

    if result.verdict == PASS:
        flag = same_organization_flag(page_url, gov_name, gov_domain=gov_domain)
        if flag is not None:
            return flag
    return result


# ===========================================================================
# WO-1041 (2026-09-24): "meeting evidence" for a found video -- additive to
# the WO-933 gate above, not a replacement. Built from real spot-check
# evidence gathered for WO-1041 (see BACKLOG_DONE.md's WO-1041 entry): 10
# real Cablecast/Swagit-calibration-run direct-file titles (0/10 were real
# meetings unless the file was long or titled), 12 real Vimeo hand-check
# verdicts (3/12 were real meetings, and every one of those 3 had a
# governing-body/meeting word or a date in its title), and a 10,381-title
# corpus of real Archive titles for the meeting-word list itself. Nothing
# above this point in the file is touched -- this section only adds names.
#
# `assess_video_candidate()` above already asks "is this a meeting video at
# all" for a handful of high-risk platforms (YouTube, Vimeo, Cablecast,
# Swagit) via its own narrower `MEETING_ALLOWLIST`. This section is a
# SEPARATE, wider check meeting_finder's own resolve.py applies specifically
# to `direct_file`/`vimeo` finds and to any candidate picked by pick.py's
# weakest bucket ("picked by: undated, lister order") -- sources with no
# per-meeting listing to vouch for them at all, where the WO-1041 spot-check
# found the true miss rate (Vimeo 9/12, direct files 10/10) sat.
# ===========================================================================

# The wider meeting-word list (superset of MEETING_ALLOWLIST above): every
# word cited in the WO-1041 brief, drawn from a 10,381-title Archive corpus.
# Multi-word phrases are checked as substrings after their component words
# are also checked individually via `contains_word()`, so "select board" and
# "selectboard" both match regardless of spacing.
MEETING_EVIDENCE_WORDS = (
    "meeting",
    "meetings",
    "council",
    "board",
    "regular",
    "commission",
    "commissioner",
    "commissioners",
    "committee",
    "planning",
    "special",
    "session",
    "public",
    "supervisors",
    "zoning",
    "hearing",
    "budget",
    "workshop",
    "agenda",
    "trustees",
    "advisory",
    "court",
    "authority",
    "directors",
    "review",
    "joint",
    "appeals",
    "finance",
    "work session",
    "select board",
    "selectboard",
    "town meeting",
    "school committee",
)

# Abbreviations from real recorder/title shapes, matched as whole (case-
# sensitive) tokens only -- a lowercase "cc" or "sb" is ordinary English,
# never evidence of a meeting; only the ALL-CAPS token means anything here.
MEETING_EVIDENCE_ABBREVIATIONS = (
    "TB",
    "BOT",
    "BOS",
    "BOE",
    "SC",
    "SB",
    "SHAC",
    "ZHB",
    "Mtg",
    "CC",
)

_MEETING_EVIDENCE_ABBR_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in MEETING_EVIDENCE_ABBREVIATIONS) + r")\b"
)

# Date/time shapes that count as evidence on their own (WO-1041 brief):
# month names/abbreviations, numeric dates in a few common orderings, ISO
# dates, a recorder filename's YYMMDD_HHMM stamp, and am/pm times.
_MEETING_EVIDENCE_MONTH_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b",
    re.IGNORECASE,
)
_MEETING_EVIDENCE_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\b")
_MEETING_EVIDENCE_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MEETING_EVIDENCE_RECORDER_DATE_RE = re.compile(r"(?<!\d)\d{6}_\d{3,4}(?!\d)")
_MEETING_EVIDENCE_AMPM_RE = re.compile(
    r"\b\d{1,2}(:\d{2})?\s*[ap]\.?m\.?\b", re.IGNORECASE
)


def contains_date_evidence(text: Optional[str]) -> bool:
    """True when `text` carries a date or time shape (WO-1041) -- a month
    name, a numeric or ISO date, a recorder's YYMMDD_HHMM stamp, or an
    am/pm time. Dates never eliminate a candidate anywhere in this repo
    (CLAUDE.md's "date orders, it never eliminates" rule); here a date is
    only ever used as positive evidence toward, never against, a find."""
    t = text or ""
    return bool(
        _MEETING_EVIDENCE_MONTH_RE.search(t)
        or _MEETING_EVIDENCE_NUMERIC_DATE_RE.search(t)
        or _MEETING_EVIDENCE_ISO_DATE_RE.search(t)
        or _MEETING_EVIDENCE_RECORDER_DATE_RE.search(t)
        or _MEETING_EVIDENCE_AMPM_RE.search(t)
    )


# Non-meeting signs (WO-1041 spot-check): filename/title words that
# positively say "this is not a meeting recording" -- a decorative/hero
# clip, an unrelated school or community-access program, a ceremony or a
# sports broadcast. Word-boundary matched via `contains_word()`, same as
# MEETING_ALLOWLIST/PROMO_BLOCKLIST above.
NON_MEETING_SIGNS = (
    "banner",
    "hero",
    "homepage",
    "drone",
    "doodle",
    "overview",
    "welcome",
    "promo",
    "tour",
    "compilation",
    "reel",
    "podcast",
    "episode",
    "training",
    "webinar",
    "title ix",
    "graduation",
    "commencement",
    "concert",
    "band",
    "choir",
    "theater",
    "theatre",
    "musical",
    "game",
    "football",
    "basketball",
    "athletics",
    "sports",
    "homecoming",
    "parade",
    "ceremony",
)

# A short (<10 min) video whose title is nothing but a presentation/intro/
# explainer word is a weak lead, not a meeting, even with no other
# non-meeting sign present -- WO-1041 spot-check: these are typically a
# single agenda-item clip or an orientation video, not the meeting itself.
_SHORT_WEAK_LEAD_WORDS = ("presentation", "intro", "explainer")

# The HTML5 `<video>` fallback text, seen next to a decorative homepage
# clip's markup (usually paired with autoplay/muted/loop -- see
# `decorative_url_reason()` above for the query-parameter half of this same
# real shape).
_HTML5_FALLBACK_TEXT_RE = re.compile(r"does not support the video tag", re.IGNORECASE)


def has_non_meeting_sign(text: Optional[str]) -> Optional[str]:
    """The first `NON_MEETING_SIGNS` word found in `text` (word-boundary),
    or None."""
    t = (text or "").lower()
    for word in NON_MEETING_SIGNS:
        if contains_word(t, word):
            return word
    return None


def has_meeting_evidence_word(text: Optional[str]) -> Optional[str]:
    """The first `MEETING_EVIDENCE_WORDS` word, or `MEETING_EVIDENCE_
    ABBREVIATIONS` token, found in `text`, or None. Wider than
    `allowlisted_word()` above -- see this section's module comment for
    why the two lists are kept separate rather than merged."""
    t = text or ""
    low = t.lower()
    for word in MEETING_EVIDENCE_WORDS:
        if contains_word(low, word):
            return word
    m = _MEETING_EVIDENCE_ABBR_RE.search(t)
    if m:
        return m.group(1)
    return None


@dataclass(frozen=True)
class MeetingEvidence:
    """WO-1041's verdict on one found video: is there real, positive
    evidence it's a meeting recording? `has_evidence=False` is a finding
    (a blank), never a guess -- same posture as `GateVerdict.undecided`
    above, just without a three-way split since the caller (resolve.py)
    only ever needs a yes/no to decide whether to keep the find as a
    clean success or demote it to `OUTCOME_VIDEO_LOW_CONFIDENCE`."""

    has_evidence: bool
    reason: str = ""
    non_meeting_sign: Optional[str] = None


def assess_meeting_evidence(
    *texts: Optional[str],
    duration_seconds: Optional[float] = None,
    is_direct_file: bool = False,
) -> MeetingEvidence:
    """WO-1041: read whatever text the caller has about a found video --
    its title, its filename, a Google Drive file's own page title, the
    link's anchor text, the linking page's title -- and decide whether
    there is real evidence it's a meeting recording.

    Order, per the WO-1041 brief: (1) a non-meeting sign anywhere in the
    combined text is decisive -- REJECT regardless of length or any
    meeting word also present; (2) a meeting word/abbreviation -- ACCEPT;
    (3) a date/time shape -- ACCEPT; (4) `is_direct_file` and
    `duration_seconds` >= 15 minutes -- ACCEPT, no upper bound (a long
    official recording on the government's own site, even with a bare
    filename); (5) otherwise, no evidence -- REJECT. A short (<10 min)
    presentation/intro/explainer-titled video never accepts on word/date
    evidence alone (WO-1041: "weak lead"), even though "presentation"
    itself isn't a `NON_MEETING_SIGNS` word (a real committee "budget
    presentation" is common inside an actual meeting) -- it only
    downgrades a SHORT one.

    WO-1058 (Ryan, 2026-09-25): the threshold was 45 minutes; hand-checks
    of direct files found 21 of 28 in the 15-45 min range were real
    meetings, and 7 of 11 over 45 min -- so 45 min was rejecting mostly-
    real meetings outright. Lowered to 15 minutes, still no upper bound,
    and the non-meeting-sign veto above still applies first.
    """
    combined = " ".join(t for t in texts if t)

    non_meeting = has_non_meeting_sign(combined)
    if non_meeting:
        return MeetingEvidence(False, non_meeting_sign=non_meeting)
    if _HTML5_FALLBACK_TEXT_RE.search(combined):
        return MeetingEvidence(False, non_meeting_sign="html5_fallback_text")

    short_weak_lead = (
        duration_seconds is not None
        and duration_seconds < 10 * 60
        and any(contains_word(combined.lower(), w) for w in _SHORT_WEAK_LEAD_WORDS)
    )
    if short_weak_lead:
        return MeetingEvidence(False, non_meeting_sign="short_presentation_or_intro")

    word = has_meeting_evidence_word(combined)
    if word:
        return MeetingEvidence(True, reason=f"meeting_word:{word}")
    if contains_date_evidence(combined):
        return MeetingEvidence(True, reason="date")
    if is_direct_file and duration_seconds is not None and duration_seconds >= 15 * 60:
        return MeetingEvidence(True, reason="long_direct_file(>=15min)")
    return MeetingEvidence(False)
