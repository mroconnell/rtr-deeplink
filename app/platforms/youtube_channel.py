"""Find a meeting's real recording on a city's own YouTube channel, for
the confirmed case where the meeting-management system (Legistar) hosts
no video at all (WO-30, built 2026-08-21).

Why this exists
---------------
Five large US cities run a Legistar instance whose video column is
*structurally* empty -- not "empty for this meeting," empty for every
meeting -- while the real recordings sit, public and unlinked, on the
city's own YouTube channel. Confirmed live 2026-08-21 (2026-08-30 for
Columbus) against real pages/APIs, not assumed:

- **Phoenix, AZ** (`phoenix.legistar.com`): every MeetingDetail page
  server-renders `<a class="videolink" ...>Not Available</a>` with no
  `onclick` at all (re-confirmed on the real 7/1/2026 Formal Meeting),
  and `webapi.legistar.com/v1/phoenix/events` returns
  `EventVideoPath: null` / `EventMedia: null` for every event checked.
- **Philadelphia, PA** (`phila.legistar.com`): no `a.videolink` anchor on
  the page at all, not even the disabled one.
- **Baltimore, MD** (`baltimore.legistar.com`): most meetings have a
  completely empty attachments table; a minority carry a real YouTube
  "Recording" link, which `legistar.py`'s existing
  `_try_fallback_video_link()` already catches (and still does -- this
  module only ever runs after that returns nothing).
- **Albuquerque, NM** (`cabq.legistar.com`): *partially* -- see the
  registry entry below; its full City Council meetings really do carry a
  Granicus video link, only the committee meetings don't. (BACKLOG.md's
  original survey entry described the whole instance as video-less; that
  turned out to be too broad, corrected there.)
- **Columbus, OH** (`columbus.legistar.com`, added 2026-08-30, WO-72): no
  `a.videolink` anchor at all on a real meeting page
  (MeetingDetail.aspx?ID=1436780, "Columbus City Council" on 8/24/2026) --
  same shape as Philadelphia. The matching recording is a past livestream
  on the city's own channel, published under its `/streams` tab.

Why a scoped channel listing, not `ytsearch:`
---------------------------------------------
yt-dlp can do both. Relying on YouTube's relevance ranking to decide
which video is a given government's meeting is exactly the kind of guess
this repo doesn't make -- a wrong match publishes some other meeting's
video under a real government's name, which is worse than the honest "no
video found" this replaces. So: enumerate a *known*, human-verified
channel (`_CHANNEL_FALLBACKS` below) and match locally, on evidence we
can inspect.

Real constraints found while building this, all live-confirmed
---------------------------------------------------------------
1. **A flat channel listing carries no dates.** With
   `extract_flat: "in_playlist"`, every entry's `timestamp` /
   `release_timestamp` / `upload_date` is `None` (confirmed on all four
   channels). The only per-entry date available without a separate
   per-video extraction is the one the city itself typed into the video
   title -- which, on all four channels, is always there. That's why the
   matcher below parses dates out of titles rather than reading a field.
2. **The listing is NOT lazy.** `extract_info()` on a channel tab
   downloads the *entire* channel before returning (measured: 34s and a
   plain `list` for Philadelphia's channel, iterating and breaking early
   saves nothing). `playlistend` is therefore load-bearing, not an
   optimization -- see `_LISTING_LIMIT`.
3. **Meetings can live on either channel tab.** Phoenix's meetings are
   past livestreams and appear only under `/streams`; Baltimore's are
   plain uploads under `/videos`; Albuquerque and Philadelphia have real
   meetings on both. Both tabs are always enumerated.
4. **yt-dlp's own upload date is not the meeting date, and the gap is
   not bounded by a day.** Measured on real uploads: Philadelphia's
   "Committee on Finance 06-4-25" was uploaded 2025-06-10 (6 days late)
   and "Committee on Rules 6/3/2026" on 2026-06-10 (7 days late). A hard
   +/-1 day check against `upload_date` would falsely reject real,
   correct matches. See `video_date_is_plausible()` for the one-sided
   check that's actually sound.
5. **No blocking observed.** Channel listings are a heavier call than the
   single-video fetch `youtube.py` makes, and a plausible new
   anti-scraping surface (see CLAUDE.md's yt-dlp bullet and the
   2026-08-09 Render IP block). Nothing was blocked from this machine on
   2026-08-21: ~1.4s per 100 entries, no captcha/consent interstitial, no
   429. That's a residential IP, not Render's -- if this starts failing in
   production while working locally, that asymmetry is the first thing to
   check, and `find_channel_match()` already degrades to `None` (i.e.
   today's "no video found") rather than raising.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
import yt_dlp

logger = logging.getLogger("rtr_deeplink.youtube_channel")


@dataclass(frozen=True)
class ChannelFallback:
    """One human-verified (meeting-system netloc -> YouTube channel) pair."""

    channel_id: str  # the stable UC... id, not a handle -- see below
    channel_name: str  # exactly as YouTube reports it, for the provenance warning


# Curated, human-verified, and deliberately in code -- same precedent as
# `jurisdiction_enrich._KNOWN_DOMAINS`: a small dict where every entry
# cites the real evidence that earned it, grown one confirmed customer at
# a time. Not a DB table (a new resolver table means `create_all()`
# behavior on Postgres, the pattern behind four documented incidents --
# and the resolver's `create_all()` is a no-op on Postgres now anyway, so
# a new table wouldn't appear on its own), and not a config file (no
# precedent for one here; `jurisdiction_data/`'s CSVs are bulk Census
# tables, not curated per-tenant facts).
#
# Channel *ids* (`UC...`), not `@handles`: an id is immutable, a handle is
# renameable by the channel owner, and a renamed handle would silently
# start 404ing (confirmed: yt-dlp raises a plain HTTP 404 on a
# non-existent handle). Every id below was read off a real video's own
# `channel_id` field or a real channel page, never guessed.
_CHANNEL_FALLBACKS: Dict[str, ChannelFallback] = {
    # Phoenix, AZ. Earned by the exact pair BACKLOG.md documents: the real
    # 7/1/2026 "City Council Formal Meeting" (Legistar EventId 2651,
    # video "Not Available") is published as
    # youtube.com/watch?v=srjuXI5vGuw, "Phoenix City Council Formal
    # Meeting July 1, 2026", whose own channel_id is this one.
    "phoenix.legistar.com": ChannelFallback(
        "UCx7FQNzOFCbtExt_gRub9JQ", "CityofPhoenixAZ"
    ),
    # Philadelphia, PA -- phlcouncil.com's own "Watch City Council" page
    # points at this channel, and its listing lines up meeting-for-meeting
    # with phila.legistar.com's calendar (verified on 2025-06-04, where
    # Legistar's three separate bodies -- Committee on Finance, Committee
    # on Rules, Committee of the Whole -- each have their own video, all
    # three titled with that same date).
    "phila.legistar.com": ChannelFallback(
        "UC9bXJCRFPLxMhT22nZ7t8XA", "Philadelphia City Council"
    ),
    # Baltimore, MD -- CharmTV, the city's own cable channel. Earned the
    # same way as Phoenix: the one Baltimore meeting known to have a real
    # "Recording" link (City Council Hearing, 2025-10-20, ID=1282692) links
    # to youtu.be/XFaAY2G_cl0, whose channel_id is this one. Verified
    # 7-for-7 against real Legistar events 2026-07-20..2026-08-20.
    #
    # Note this channel is *mixed* -- ribbon cuttings, press availabilities
    # and swearing-in ceremonies sit alongside real meetings, all with the
    # same "Title; Month D, YYYY" shape. That's the strongest argument for
    # the strict body-name matching below rather than a date-only match.
    "baltimore.legistar.com": ChannelFallback(
        "UCasQyO1K4yMq3Hi_0RQ0jfA", "CharmTV Citizens' Hub"
    ),
    # Albuquerque, NM. **Not** the main "One Albuquerque Media (GOV-TV)"
    # channel (UCdpRwD5FA0g3ynJWxGk7BVQ) -- checked live, its first 400
    # uploads contain zero meeting recordings. The meetings are on GOV TV's
    # separate "Boards & Commission Meetings" channel, confirmed by reading
    # `channel_id` off a real meeting video (Land Use, Planning and Zoning
    # Committee Meeting - June 10, 2026 = r3yOkniCcUQ) that matches
    # Legistar EventId 3152 exactly.
    #
    # Correction to BACKLOG.md's original survey: cabq.legistar.com is only
    # *partly* video-less. Its "City Council" events carry a real
    # `Video.aspx?Mode=Granicus` link and resolve through the normal
    # Legistar path untouched by this module; it's the committee meetings
    # (Land Use/Planning/Zoning, Finance & Government Operations,
    # Intergovernmental Legislative Relations) that render "Not Available".
    "cabq.legistar.com": ChannelFallback(
        "UCEqpcP42AmnpJPyuOy1jASQ", "GOV TV - Boards & Commission Meetings"
    ),
    # Columbus, OH (WO-72, 2026-08-30). Same precondition as Phoenix/
    # Philadelphia/Baltimore above: a real past meeting
    # (columbus.legistar.com/MeetingDetail.aspx?ID=1436780, "Columbus City
    # Council" on 8/24/2026) renders no `a.videolink` anchor at all --
    # confirmed live via a direct fetch of the page, not assumed. The
    # matching recording sits on the city's own channel, under its
    # `/streams` tab (a past livestream, `live_status: "was_live"`, same
    # as most of Phoenix's): "Columbus City Council Meeting (8/24/26)" =
    # youtube.com/watch?v=lJR39FcIhM8, whose own channel_id is this one --
    # read off a real yt-dlp channel listing on 2026-08-30, matching the
    # id independently confirmed via the same listing's `channel_id`
    # field.
    "columbus.legistar.com": ChannelFallback(
        "UCfttJJ9T5_1W1JewiTJqzqA", "City of Columbus"
    ),
}

# Both real channel tabs. See constraint 3 in the module docstring -- which
# tab a meeting lands on depends on whether the city streamed it live, and
# all four cities do it differently.
_CHANNEL_TABS = ("videos", "streams")

# How far back one tab is enumerated. Measured live 2026-08-21: ~1.4s per
# 100 entries, so 400 is ~6s per tab and ~12s for both -- paid once per
# channel per `_CACHE_TTL_SECONDS` thanks to the cache below, not per
# resolve. 400 entries reached 2025-06 on Philadelphia's channel (the
# busiest of the four), i.e. roughly a 14-month window there and longer on
# the quieter channels. A meeting older than the window simply isn't found
# and we decline -- the same outcome as before this existed.
_LISTING_LIMIT = 400

_CACHE_TTL_SECONDS = 30 * 60
_listing_cache: Dict[str, Tuple[float, List[dict]]] = {}

# Structural noise that appears on one side of a real match and not the
# other, on real observed titles: Legistar's body name is "Committee on
# Finance" where the video is "Committee on Finance 06-4-25", and
# "Public Health & Environment Committee" where the video is "City Council
# Hearing: Public Health & Environment; August 5, 2026". Dropping these
# from BOTH sides is what lets those line up. Deliberately short: words
# that actually distinguish one body from another ("formal", "special",
# "policy", "subcommittee", "city", "council") are NOT here, because
# Phoenix really does hold a "City Council Formal Meeting" and a "City
# Council Special Meeting", and telling them apart is the whole job.
#
# "session" is in here on real evidence, not by analogy: Phoenix's own
# channel titles the same body's meetings "Phoenix City Council Policy
# Session - May 19, 2026" and "Phoenix City Council Policy Meeting -
# June 9, 2026" in the same season, against a single Legistar body named
# "City Council Policy Session". Treating it as a distinguishing word
# declined two real, correct 2026 matches.
_GENERIC_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "for",
        "hearing",
        "hearings",
        "meeting",
        "meetings",
        "of",
        "on",
        "session",
        "sessions",
        "the",
    }
)

# Words a real body name carries that the city's own video title often
# drops, without either side meaning anything different by it: Baltimore's
# Legistar body "Public Health & Environment Committee" is published as
# "City Council Hearing: Public Health & Environment; August 5, 2026"
# (confirmed -- that exact video is the one Baltimore itself attached to
# the meeting page, so it's ground truth, not a guess). These are NOT in
# _GENERIC_TOKENS because they still have to *count* toward the
# two-significant-token floor below: Philadelphia's "Committee on Finance"
# is only {committee, finance}, and dropping "committee" outright would
# push that whole city's bodies under the floor and decline everything.
# So: soft tokens count, but aren't required to appear on the video side.
_SOFT_TOKENS = frozenset({"committee", "subcommittee"})

# "Committee on Finance 06-03-26 (Part 1)" -- real, common on
# Philadelphia's channel, where one long meeting is uploaded as several
# videos. Stripped before tokenizing so the parts compare equal, then used
# to pick part 1 (see `_pick`).
_PART_RE = re.compile(r"\(?\bpart\s*(\d+)\)?", re.IGNORECASE)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# "July 1, 2026" / "August 07, 2026" / "Sept 9 2026" -- Phoenix, Baltimore
# and Albuquerque's shape. The comma is optional on real titles.
_TEXT_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
# "06-4-25" / "6-11-26" / "5/21/2026" / "(5-13-26)" -- Philadelphia's
# shape, and the reason a two-digit year has to be handled at all.
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})\b")


@dataclass(frozen=True)
class ChannelMatch:
    video_id: str
    video_title: str
    channel_name: str
    channel_url: str
    # Best-effort corroboration only, from the channel's public Atom feed
    # (see _fetch_atom_published_date below) -- None whenever the fetch
    # fails or the video isn't among the feed's ~15 most recent entries.
    # Never a rejection signal on its own; see video_date_is_plausible().
    atom_published_date: Optional[str] = None


def has_channel_fallback(netloc: str) -> bool:
    return netloc.lower().lstrip(".") in _CHANNEL_FALLBACKS


def parse_title_date(title: str) -> Optional[date_cls]:
    """The date the *city itself* put in the video title.

    This is the primary date signal on purpose -- see constraint 1 in the
    module docstring (a flat listing has no date fields at all) and
    constraint 4 (yt-dlp's upload date really can be a week after the
    meeting).
    """
    match = _TEXT_DATE_RE.search(title)
    if match:
        month = _MONTHS[match.group(1).lower()]
        try:
            return date_cls(int(match.group(3)), month, int(match.group(2)))
        except ValueError:
            return None

    match = _NUMERIC_DATE_RE.search(title)
    if match:
        month, day, year = (int(g) for g in match.groups())
        if len(match.group(3)) == 2:
            # Real titles use a bare 2-digit year ("06-4-25"). Government
            # meeting video is a post-2000 artifact; 2000+YY is the only
            # reading that can be right for any of it.
            year += 2000
        try:
            return date_cls(year, month, day)
        except ValueError:
            # Guards the real "Board of Municipal & Zoning Appeals
            # Hearing; August 2026" case one level up too: a title with no
            # usable day never produces a date, so it can never match.
            return None
    return None


def _strip_dates(title: str) -> str:
    return _NUMERIC_DATE_RE.sub(" ", _TEXT_DATE_RE.sub(" ", title))


def _tokens(text: str) -> frozenset:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return frozenset(t for t in text.split() if t and t not in _GENERIC_TOKENS)


def _part_number(title: str) -> Optional[int]:
    match = _PART_RE.search(title)
    return int(match.group(1)) if match else None


def _body_tokens(meeting_title: str) -> frozenset:
    """Significant tokens of the Legistar body name, e.g. "Committee on
    Finance" -> {finance}, "Board of Estimates" -> {board, estimates}."""
    return _tokens(_strip_dates(meeting_title))


def _video_tokens(video_title: str) -> frozenset:
    return _tokens(_PART_RE.sub(" ", _strip_dates(video_title)))


def find_matches(
    entries: List[dict], meeting_title: str, meeting_date: date_cls
) -> List[dict]:
    """Every listing entry that matches on BOTH date and body name.

    Split out from the network call so the matching rules -- the risky
    half of this feature -- are testable against real listing data with no
    yt-dlp involved.

    The rules, and the real evidence behind each:

    * **The title's date must equal the meeting date exactly.** This
      started as the +/-1 day window WO-30 specified and was tightened on
      real evidence: with a one-day window, Baltimore's 2026-06-01
      "Baltimore City Council" meeting matched "City Council Hearing:
      FY2027 Live Baltimore; June 2, 2026" -- a different hearing whose
      title happens to contain the body's own words. Across ~40 real
      matches on all four channels, every correct one was same-day; the
      one-day slack bought nothing and cost a wrong attribution, which is
      the exact failure this feature must not have. The day of slack lives
      in `video_date_is_plausible()` instead, where it belongs -- see that
      function for why publication dates really do drift and meeting-title
      dates don't.
    * **Every required body token must appear in the video title.**
      Containment, not equality -- the video title is almost always a
      superset ("Phoenix City Council Formal Meeting July 1, 2026" vs
      Legistar's "City Council Formal Meeting"; "City Council Hearing:
      Public Health & Environment; August 5, 2026" vs "Public Health &
      Environment Committee"). Verified to pick the right one out of a
      real same-day pair on both Baltimore (Board of Estimates vs. Public
      Health & Environment, both 2026-08-05, where the right answer is
      independently known because Baltimore itself attached that video to
      the meeting page) and Philadelphia (Finance vs. Rules vs. Committee
      of the Whole, all 2025-06-04).
    * **At least two significant body tokens required.** A one-word body
      ("President", a real Albuquerque body name) is too weak a signal to
      bet a real government's name on -- a single common word could match
      almost anything on a mixed channel like Baltimore's, which carries
      ribbon cuttings and press availabilities alongside real hearings.
    """
    tokens = _body_tokens(meeting_title)
    if len(tokens) < 2:
        return []
    wanted = tokens - _SOFT_TOKENS

    matches = []
    for entry in entries:
        title = entry.get("title") or ""
        entry_date = parse_title_date(title)
        if entry_date is None or entry_date != meeting_date:
            continue
        if not wanted <= _video_tokens(title):
            continue
        matches.append(entry)
    return matches


def _pick(matches: List[dict]) -> Optional[dict]:
    """Decline on a genuine ambiguity; allow exactly one non-guess.

    The non-guess: Philadelphia really does split one long meeting across
    "... (Part 1)", "(Part 2)", "(Part 3)" -- confirmed live on the real
    2026-06-03 Committee on Finance. Those aren't different meetings to
    choose between, they're one meeting in pieces, so taking part 1 picks
    a *place in the ordering*, not a candidate. Anything else that ties --
    two genuinely different videos both matching one body on one date --
    returns None, which lands the caller back on the honest "no video
    found" it had before this existed.
    """
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    tokensets = {_video_tokens(m.get("title") or "") for m in matches}
    parts = [_part_number(m.get("title") or "") for m in matches]
    if len(tokensets) == 1 and all(p is not None for p in parts):
        return min(matches, key=lambda m: _part_number(m.get("title") or ""))
    return None


def video_date_is_plausible(meeting_date: str, video_date: Optional[str]) -> bool:
    """Second, independent date check -- against yt-dlp's own metadata
    this time, not the title -- and deliberately one-sided.

    `video_date` is `ResolvedMeeting.date` as `youtube.py` computes it:
    a livestream's own `release_date` when there is one, otherwise
    `upload_date` (see that module's own comment on why release_date is
    preferred). Both dates were checked against reality on 2026-08-21:

    * `release_date` matched the real meeting date exactly on every
      live-streamed sample (Phoenix 2026-07-01, Albuquerque 2026-06-01 and
      2026-06-08).
    * `upload_date` did not, and not by a day either. Philadelphia's
      "Committee on Finance 06-4-25" was uploaded 2025-06-10 -- six days
      after its meeting -- and "Committee on Rules 6/3/2026" seven days
      after. Publishing lag is real and unbounded, so there is no honest
      upper bound to enforce; a +/-1 day check here would have rejected
      two confirmed-correct matches.

    What *is* sound in both cases is the floor: a recording published more
    than a day before the meeting happened cannot be a recording of that
    meeting. That's the check -- it catches a title whose date is a typo
    or refers to something else entirely, and costs no correct match.

    A missing date is not a rejection: `youtube.py` degrades to a
    dateless, caption-less result when YouTube blocks the server outright
    (the real 2026-08-09 incident), and the title's own date already had
    to match exactly by then.
    """
    if not video_date:
        return True
    try:
        parsed = datetime.strptime(video_date, "%Y-%m-%d").date()
        target = datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return True
    return parsed >= target - timedelta(days=1)


def _list_channel_tab(channel_id: str, tab: str) -> List[dict]:
    """Blocking. One flat listing of one channel tab, TTL-cached.

    `extract_flat: "in_playlist"` returns titles + ids with no per-video
    extraction, which is what makes enumerating hundreds of entries cheap
    enough to do at resolve time at all.
    """
    url = f"https://www.youtube.com/channel/{channel_id}/{tab}"
    cached = _listing_cache.get(url)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": _LISTING_LIMIT,
        # Same anti-block workaround youtube.py's _extract_info() carries,
        # for the same reason (the 2026-08-09 Render IP block) -- see its
        # comment. A channel listing is a heavier, differently-shaped call,
        # so it's a plausible separate block surface; nothing was blocked
        # when this was built, but keeping the clients aligned means one
        # place to change if that stops being true.
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "tv", "web"]}
        },
        "ignoreerrors": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
    _listing_cache[url] = (now, entries)
    return entries


def _list_channel(channel_id: str) -> List[dict]:
    entries: List[dict] = []
    seen = set()
    for tab in _CHANNEL_TABS:
        try:
            tab_entries = _list_channel_tab(channel_id, tab)
        except Exception:
            # One missing/blocked tab shouldn't lose the other. A channel
            # with no live streams at all really does 404 its /streams tab.
            continue
        for entry in tab_entries:
            if entry["id"] not in seen:
                seen.add(entry["id"])
                entries.append(entry)
    return entries


def is_publishable(entry: dict) -> bool:
    """Skips a scheduled-but-not-yet-happened livestream.

    Real case: Albuquerque's channel lists "Albuquerque City Council
    Meeting - September 9, 2026" as `live_status: "is_upcoming"` with a
    null duration, weeks before it happens. Matching one would put an
    unplayable placeholder on a meeting page.
    """
    if entry.get("live_status") in ("is_upcoming", "is_live"):
        return False
    return bool(entry.get("duration"))


_ATOM_ENTRY_RE = re.compile(r"<entry>(?:(?!</entry>).)*?</entry>", re.DOTALL)
_ATOM_VIDEO_ID_RE = re.compile(r"<yt:videoId>([^<]+)</yt:videoId>")
_ATOM_PUBLISHED_RE = re.compile(r"<published>([^<]+)</published>")


async def _fetch_atom_published_date(channel_id: str, video_id: str) -> Optional[str]:
    """Best-effort corroboration only for a video `_pick()` already chose.

    YouTube's public per-channel Atom feed -- unauthenticated, no yt-dlp,
    a structurally different call surface from the single-video fetch
    that's the documented Render IP-block target (see this module's own
    docstring and youtube.py's resolve_video_id()). Real shape confirmed
    live 2026-08-29 against Phoenix's channel (UCx7FQNzOFCbtExt_gRub9JQ):
    each <entry> carries a sibling <yt:videoId>/<published> pair, e.g.
    <published>2026-08-28T17:00:23+00:00</published>.

    Capped at the feed's ~15 most recent uploads (confirmed real, binding
    limit -- also live-tested just now: Phoenix's most recent entries are
    mostly non-meeting "Shorts" content, so this misses often on anything
    not resolved same-day, or on a Shorts-heavy channel). Returns None
    (never an error, never raises) whenever the video isn't among the
    feed's entries, the fetch fails, or the feed is malformed -- callers
    must treat this purely as corroboration, not a required signal.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "YouTube Atom feed fetch got HTTP %s for channel %s",
                        response.status,
                        channel_id,
                    )
                    return None
                xml = await response.text()
    except Exception:
        logger.warning(
            "YouTube Atom feed fetch failed for channel %s",
            channel_id,
            exc_info=True,
        )
        return None

    for entry_match in _ATOM_ENTRY_RE.finditer(xml):
        entry_xml = entry_match.group(0)
        id_match = _ATOM_VIDEO_ID_RE.search(entry_xml)
        if not id_match or id_match.group(1) != video_id:
            continue
        published_match = _ATOM_PUBLISHED_RE.search(entry_xml)
        if not published_match:
            return None
        try:
            return datetime.fromisoformat(published_match.group(1)).date().isoformat()
        except ValueError:
            return None
    return None


async def find_channel_match(
    netloc: str, meeting_title: Optional[str], meeting_date: Optional[str]
) -> Optional[ChannelMatch]:
    """Returns the one confidently-matching video on this tenant's known
    channel, or None. None is not an error -- it's the pre-existing "no
    video found" outcome, so every uncertain path here declines into it.
    """
    fallback = _CHANNEL_FALLBACKS.get((netloc or "").lower().lstrip("."))
    if not fallback or not meeting_title or not meeting_date:
        return None
    try:
        target = datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except ValueError:
        return None

    try:
        entries = await asyncio.to_thread(_list_channel, fallback.channel_id)
    except Exception:
        logger.warning(
            "YouTube channel listing failed for %s (netloc %s) -- possible "
            "IP block, see this module's own docstring on the Render-vs-"
            "residential asymmetry",
            fallback.channel_id,
            netloc,
            exc_info=True,
        )
        return None

    matches = [
        e for e in find_matches(entries, meeting_title, target) if is_publishable(e)
    ]
    chosen = _pick(matches)
    if not chosen:
        return None
    atom_published_date = await _fetch_atom_published_date(
        fallback.channel_id, chosen["id"]
    )
    return ChannelMatch(
        video_id=chosen["id"],
        video_title=chosen.get("title") or "",
        channel_name=fallback.channel_name,
        channel_url=f"https://www.youtube.com/channel/{fallback.channel_id}",
        atom_published_date=atom_published_date,
    )
