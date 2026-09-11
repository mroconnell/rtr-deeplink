"""BoxCast -- a real government video vendor, confirmed live across four
independent tenants (Wilmington OH, St. Louis County - Clayton MO, City of
Hondo TX, Atlantic City NJ). Two things live in this module:

1. `find_channel_match()` -- BoxCast video delegation for ProudCity's
   `video_style === 'external'` case (`proudcity.py`'s `_EXTERNAL_VIDEO_RE`),
   a plain outbound link to a whole BoxCast *channel*, e.g.
   `boxcast.tv/channel/x1jps4n28nlgtaozsv5y` (Wilmington, OH's real link).
   Built 2026-08-29, unchanged by WO-227 below -- ProudCity's own
   `resolve()` still calls this directly, still matches a page's own
   known meeting date against the channel, and its existing tests
   (`tests/test_proudcity.py`) still pass.
2. `BoxcastAssetFinder` (WO-227, 2026-09-11) -- a real, standalone
   `AssetFinder` so a bare `boxcast.tv/view/{...}`, `boxcast.tv/view-embed/
   {...}` or `boxcast.tv/channel/{...}` URL resolves on its own, the way
   every other platform here does, not only as a ProudCity delegation
   target.

## The real REST API (confirmed live 2026-08-29, extended 2026-09-11)

    GET https://rest.boxcast.com/channels/{channel_id}/broadcasts/_search?l={N}
    GET https://rest.boxcast.com/channels/{channel_id}/broadcasts?l={N}&s=-starts_at

are real, public, unauthenticated REST endpoints (found via `boxcast.tv`'s
own JS bundle) returning every broadcast's real `id`/`name`/`starts_at`/
`stops_at`/`time_zone_offset`/`account_id`/`channel_id` for a channel --
unlike `youtube_channel.py`'s flat yt-dlp listing, this carries REAL
structured dates directly, no title-parsing needed. And:

    GET https://rest.boxcast.com/broadcasts/{broadcast_id}
    GET https://rest.boxcast.com/broadcasts/{broadcast_id}/view

The first returns the same per-broadcast metadata as the channel listing
(so a single broadcast id can be resolved without knowing its channel);
the second returns `{"status": "recorded", "playlist": "https://
play.boxcast.com/p/{id}/v/all.m3u8?Expires=...&Signature=...&
Key-Pair-Id=..."}` -- a genuine, working, unauthenticated **signed** HLS
master playlist (confirmed live, 200, real multi-bitrate `#EXT-X-
STREAM-INF` variants across all four tenants). Signed and expiring --
`worker/main.py` already re-resolves every queue URL fresh before
transcribing (confirmed by reading its own resolve-then-probe call), so
this is the same posture every other signed-URL platform here already
has, not a new risk.

## Two ids that look alike but are NOT the government's channel (WO-227)

A public `boxcast.tv/view/{x}` or `boxcast.tv/view-embed/{x}` URL's `{x}`
is a human-readable slug (e.g. `city-council-meeting-081926-
kdhkjrwnostnrznx7yxy`), confirmed live (real search hits: Hondo TX's
`boxcast.tv/view-embed/city-council-meeting-06092025-kmgfucefqd0naxdwcoh2`,
several real `/view/{slug}` results for other cities' council meetings).
That slug is **not** a broadcast id -- `GET /broadcasts/{slug}/view` 404s
-- it is BoxCast's own per-broadcast "channel" (every broadcast gets a
dedicated, single-broadcast channel under the hood): `GET /channels/
{slug}/broadcasts` answers 200 with exactly that one broadcast, whose own
`id` field (a random 20-char id, e.g. `ixrwo0drj4qs4v9bidoc`) is what
`/broadcasts/{id}/view` actually needs. Confirmed both directions live:
a real broadcast id 404s as a channel and a real channel id (single- or
multi-broadcast) 404s as a broadcast -- so the two are told apart by
asking the API, never guessed from the URL shape, exactly as the brief
for this WO specifies.

The per-broadcast `channel_id` field a broadcast object itself carries
(e.g. Atlantic City's `wuv2iiwzlyzhny1zietp` broadcast has its own
`channel_id: "city-council-meeting-081926-kdhkjrwnostnrznx7yxy"`) is
*this* one-broadcast pseudo-channel, and it is what `resolve()` below
uses to build a stable `source_url` for whatever broadcast it picked
(`https://boxcast.tv/view/{that channel_id}`) -- confirmed to be BoxCast's
own real, public URL shape for that exact broadcast, not invented.

**The real, stable, government-level channel id is a different thing
again**, reachable only via the broadcast's `account_id`:

    GET https://rest.boxcast.com/accounts/{account_id}

returns `{"id", "name", "channel_id", ...}` where `name` is the clean
government name (`"City of Atlantic City, NJ"`, no "All broadcasts for"
prefix) and `channel_id` is the SAME id a `boxcast.tv/channel/{id}` link
on the government's own site embeds -- confirmed identical live on all
four tenants (Atlantic City: account `uihhbexsazftbrytfhlb` ->
`channel_id "lqsszohc5p0q4yemoddl"`, matching the real channel embedded
on `acnj.gov/pages/meeting-recordings`; Wilmington: account
`gutfku8y1lmddbijjyam` -> `channel_id "x1jps4n28nlgtaozsv5y"`, matching
`proudcity.py`'s own known Wilmington channel). This is what `resolve()`
uses for `external_id` (`boxcast:{account.channel_id}`) and `jurisdiction`
(`account.name`) when the account is single-tenant -- the SAME two
values regardless of whether the original URL was a `/channel/`,
`/view/` or `/view-embed/` link, since every broadcast (however reached)
carries its own real `account_id`. `GET /channels/{channel_id}` alone (a
plain channel object, no `account_id`) is NOT used for jurisdiction: its
own `name` field reads `"All broadcasts for {name}"`, a description, not
the clean name -- confirmed on all four tenants, including one genuinely
messy one (Hondo's real channel name is `"All broadcasts for City of
Hondo - ,"`, missing its state -- the `/accounts/{id}` route sidesteps
this entirely).

## An account can be a shared regional media operator, not the government (WO-227b)

The account-is-the-government assumption above holds for all four of
WO-227's original tenants and three of the five WO-227b added (Ingleside
TX, Maywood IL, Bartow FL), but broke on the other two: Livermore Falls,
ME's real channel (`vvohjjgvcdbmeatv03km`, found on the town's own
WordPress site) and Atlantic Beach, SC's (`dtoujlfjxuu2lde6bvp8`, found
the same way) both sit on a BoxCast account that is NOT the government --
`GET /accounts/{account_id}` for Livermore Falls' channel returns
`"Mt. Blue Television - Farmington, ME"`, a regional community-TV
operator whose own umbrella channel (confirmed live) carries Farmington's
own Select Board, Jay's Select Board, an RSU 9 school-board meeting, and
several high-school sports broadcasts -- a real multi-government host,
the same hazard `docs/COVERAGE_HANDOVER.md` section 3 documents for
youtube.com/vimeo.com, one layer deeper (inside a single BoxCast
account rather than a whole domain). Atlantic Beach's account
("Media Mike") reads the same way structurally, though no second real
government has been confirmed on it yet. Using `account.channel_id`
unconditionally here (as the module did before this WO) would silently
compute the SAME `external_id` for every government sharing that
account -- exactly the collision WO-210 fixed at the domain level, just
unreachable by that fix since BoxCast accounts aren't in
`MULTI_GOV_HOSTS`. `_resolve_broadcast()`'s `channel_hint` parameter is
the fix: when the scan reached a real, DISTINCT channel (different from
the picked broadcast's own one-off per-broadcast pseudo-channel), that
channel -- not the account -- is trusted for `external_id`, and the
account's `name` is trusted for `jurisdiction` only when it agrees with
that same distinct channel (i.e. the account looks single-tenant for
this specific channel). See `tests/test_boxcast.py`'s Livermore Falls
and Atlantic Beach cases.

## A channel URL auto-picks its newest meeting-like PAST broadcast

`boxcast.tv/channel/{id}` (and a `boxcast.tv/view-embed/{id}` that turns
out to hold more than one broadcast -- confirmed real on Atlantic City's
own recordings page, which embeds its multi-broadcast government channel
via `view-embed`, not `channel`) resolve to the newest broadcast whose
`timeframe` is `"past"` (a `"future"` one has no recording) AND whose
`name` looks like a real deliberative meeting -- reusing
`app.utils.video_hand_check.classify_video_hand_check()`'s Kind B phrase
list (moved there from `scripts/wo174_pipeline.py` in this same WO so
this adapter can import it -- see that module's own docstring) plus a
positive keyword requirement (`GOVERNING_BODY_KEYWORDS` from
`granicus.py`, plus "meeting"/"session"/"workshop"/"authority"),
confirmed necessary against Atlantic City's real recent broadcast mix:
"Great Day Cafe Grand Opening", "Mayor's Press Conference ... Groundbreaking"
(caught by Kind B's "groundbreaking" phrase) and "Coursey Building
Dedication Ceremony" (caught by the missing positive keyword) all sit
NEWER than the real "City Council Meeting 08/19/26" in the channel's own
`-starts_at` order -- a bare "pick the newest past broadcast" rule would
have silently picked a ribbon-cutting instead of a council meeting.
`"CITISTAT Meeting 08/05/26"` (a real Atlantic City performance-review
meeting, confirmed 30 minutes) passes (has "meeting"); the bare
`"CITISTAT"` broadcast (21 minutes, no "meeting" in its own title) does
not -- see `BACKLOG_DONE.md`'s WO-227 entry for why that split was left
as-is rather than special-cased.

When exactly ONE past broadcast answers the id (true for both a genuine
newly-live channel and, in the ordinary case, for a `/view` or
`/view-embed` single-broadcast slug -- see above), it is used directly
with no title filtering: that URL already names one specific broadcast,
the same trust level a direct Vimeo/YouTube video URL gets.

## Captions ARE real and server-fetchable here -- on SOME tenants (WO-227)

The earlier version of this module (and this WO's own brief) called
BoxCast video-only, "no confirmed caption track on any government tenant
checked". That was true of the three original tenants (Wilmington OH,
St. Louis County was never actually checked for this, Hondo TX) but
turned out to be a gap in what was checked, not a real platform limit:
**Atlantic City NJ's real signed HLS master playlist carries a genuine
`#EXT-X-MEDIA:TYPE=SUBTITLES` track** (`GROUP-ID="sub1"`, `LANGUAGE="en"`),
confirmed live 2026-09-11 on the real 08/19/26 City Council meeting. Its
own media playlist is NOT one caption file -- it's ~12-second WebVTT
*segments*, each its own separately-signed
`https://captions.boxcast.com/recordings/{id}/webvtt?...&start_mpegts=
{n}&stop_mpegts={n}` URL (533 of them for this 107-minute meeting) --
confirmed a real, coherent, non-garbled English transcript by fetching
several (`"we're well informed and I'd like to take time..."` at the
~50-minute mark, a real remark from a real meeting). St. Louis County -
Clayton MO's real master playlist ALSO carries this subtitle track
(confirmed live); Wilmington OH's and Hondo TX's do NOT -- this is a
paid, per-BoxCast-account add-on (a real St. Louis Call Newspapers
article, found independently, confirms St. Louis County pays "$1,500
yearly fee for live closed-captioning to comply with the Americans with
Disabilities Act" -- exactly the account-by-account split observed here).
So: `resolve()` always tries this track and uses it when present,
falling back to the existing honest `_NO_CAPTIONS_WARNING` when it
isn't -- never assumed either way, checked on every resolve, the same
"don't claim a caption path works without a positive example" discipline
CLAUDE.md asks for, now with the positive example this module previously
lacked.

Each segment's own WebVTT cues already carry ABSOLUTE, broadcast-relative
timestamps -- confirmed live by sampling 20 segments spread evenly across
a real 107-minute meeting (every 25th of 533): the segment at playlist
index N has its own first real cue at `N * 12` seconds, +/- ~3 seconds,
from the start of the recording straight through to the end, with no
further adjustment needed. This took a real, wrong first attempt to find:
BoxCast's own URL query string on each segment carries `start_mpegts`/
`stop_mpegts` (and the segment's `X-TIMESTAMP-MAP` header echoes the
`start_` value), which looks exactly like the "per-segment offset on a
90kHz MPEG-TS clock" shape several other real caption sources in this
repo actually have -- but treating it that way here silently roughly
DOUBLED every later cue's timestamp, only caught by noticing a real
resolve's own last caption segment landed at minute 199 of a 107-minute
meeting. That field barely changes across the whole real playlist (two
distinct values seen across all 533 segments) and isn't this recording's
own zero point at all -- it's some other, unrelated internal BoxCast
clock. `_fetch_boxcast_captions()` below concatenates each segment's
parsed cues, in playlist order, with no offset math at all, then runs
the combined list through the same shared `vtt_parser` dedupe/garbled/
language pipeline every other adapter here uses.

Fetching one segment per HTTP request is real cost -- confirmed live,
533 real requests (Atlantic City's full 107-minute meeting) at 10-way
concurrency completed in 7.5 seconds with zero failures. Bounded to 10
concurrent requests to this one host (CLAUDE.md's "politely" bullet);
any segment that fails to fetch or parse is simply skipped (a few
missing seconds of transcript, never a failed resolve) -- purely
additive over the video-only fallback, the same posture Vimeo's own
headless-caption fetch takes.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp

from .base import AssetFinder
from .granicus import GOVERNING_BODY_KEYWORDS
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    dedupe_rollup_cues,
    detect_language_from_texts,
    is_likely_garbled,
    parse_vtt,
)
from ..utils.video_hand_check import classify_video_hand_check

logger = logging.getLogger("rtr_deeplink.boxcast")

_SEARCH_LIMIT = 50


@dataclass
class BoxcastMatch:
    broadcast_id: str
    broadcast_name: str
    video_url: str


def _tokens(text: str) -> frozenset:
    return frozenset(w for w in text.lower().split() if len(w) > 2)


def _broadcast_local_date(broadcast: dict) -> Optional[str]:
    """The broadcast's own `starts_at` (always UTC, confirmed live),
    shifted by its own `time_zone_offset` (minutes, confirmed live e.g.
    -240 for Eastern) before taking the date -- a bare UTC date would be
    wrong for any evening meeting whose UTC timestamp has already rolled
    into the next calendar day (confirmed live: Wilmington's real 8/6/2026
    meeting has `starts_at` "2026-08-06T23:00:00Z", already past 7pm
    Eastern -- a same-day meeting starting any later would roll over)."""
    starts_at = broadcast.get("starts_at")
    if not starts_at:
        return None
    try:
        dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    offset = broadcast.get("time_zone_offset")
    if isinstance(offset, (int, float)):
        dt = dt + timedelta(minutes=offset)
    return dt.date().isoformat()


async def _search_channel(
    session: aiohttp.ClientSession, channel_id: str
) -> List[dict]:
    url = (
        f"https://rest.boxcast.com/channels/{channel_id}/broadcasts/_search"
        f"?l={_SEARCH_LIMIT}"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning(
                    "BoxCast channel search got HTTP %s for %s", resp.status, url
                )
                return []
            payload = await resp.json(content_type=None)
    except Exception:
        logger.warning("BoxCast channel search failed for %s", url, exc_info=True)
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    return [b for b in (results or []) if isinstance(b, dict)]


async def _fetch_playlist(
    session: aiohttp.ClientSession, broadcast_id: str
) -> Optional[str]:
    url = f"https://rest.boxcast.com/broadcasts/{broadcast_id}/view"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning(
                    "BoxCast broadcast view got HTTP %s for %s", resp.status, url
                )
                return None
            payload = await resp.json(content_type=None)
    except Exception:
        logger.warning("BoxCast broadcast view fetch failed for %s", url, exc_info=True)
        return None
    if not isinstance(payload, dict) or payload.get("status") != "recorded":
        return None
    playlist = payload.get("playlist")
    return playlist if isinstance(playlist, str) and playlist else None


async def find_channel_match(
    channel_id: str, meeting_title: Optional[str], meeting_date: Optional[str]
) -> Optional[BoxcastMatch]:
    """Returns the one confidently-matching broadcast on this channel, or
    None -- None is not an error, it's the honest "no video found"
    outcome, same posture as `youtube_channel.find_channel_match()`.
    """
    if not channel_id or not meeting_date:
        return None
    try:
        target = datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except ValueError:
        return None

    async with aiohttp.ClientSession() as session:
        broadcasts = await _search_channel(session, channel_id)
        same_day = [
            b
            for b in broadcasts
            if b.get("timeframe") == "past"
            and _broadcast_local_date(b) == target.isoformat()
        ]
        if not same_day:
            return None
        if len(same_day) > 1 and meeting_title:
            # More than one real meeting on the same real calendar day
            # (confirmed common -- e.g. St. Louis County's Council +
            # Budget Committee meetings sharing a date) -- disambiguate
            # by title token overlap the same conservative way
            # youtube_channel.py's own matcher does, rather than
            # guessing which one the reader meant.
            wanted = _tokens(meeting_title)
            scored = [(len(wanted & _tokens(b.get("name") or "")), b) for b in same_day]
            scored.sort(key=lambda pair: pair[0], reverse=True)
            if len(scored) > 1 and scored[0][0] == scored[1][0]:
                return None
            same_day = [scored[0][1]] if scored[0][0] > 0 else []
        if len(same_day) != 1:
            return None

        chosen = same_day[0]
        broadcast_id = chosen.get("id")
        if not broadcast_id:
            return None
        video_url = await _fetch_playlist(session, broadcast_id)
        if not video_url:
            return None
        return BoxcastMatch(
            broadcast_id=broadcast_id,
            broadcast_name=chosen.get("name") or "",
            video_url=video_url,
        )


# ---------------------------------------------------------------------------
# WO-227 (2026-09-11): a real, standalone AssetFinder -- see module
# docstring's "Two ids that look alike" / "A channel URL auto-picks" /
# "Captions ARE real" sections above for the full investigation.
# ---------------------------------------------------------------------------

_NO_CAPTIONS_WARNING = "No transcript found for this event."

# `GOVERNING_BODY_KEYWORDS` (granicus.py) is real prior art for exactly
# this "does this title name a governing body" question -- reused rather
# than re-invented, per CLAUDE.md's reuse convention. "meeting"/"session"/
# "workshop"/"authority" are added locally: Atlantic City's own real
# "CITISTAT Meeting 08/05/26" and "Wilmington City Council - Public
# Workshop" (a real Wilmington broadcast title) need them and granicus.py
# has no reason to carry words specific to a channel-listing scan.
_MEETING_LIKE_KEYWORDS = GOVERNING_BODY_KEYWORDS + (
    "meeting",
    "session",
    "workshop",
    "authority",
)

# `boxcast.tv/view/{x}`, `boxcast.tv/view-embed/{x}`, `boxcast.tv/channel/{x}`
# -- confirmed live shapes (module docstring). The id itself is opaque
# (could be a broadcast, a real government channel, or a per-broadcast
# pseudo-channel slug) -- `_resolve_id()` below asks the real API rather
# than trying to tell them apart from the path alone, per this WO's brief.
_BOXCAST_URL_RE = re.compile(r"^/(?:view|view-embed|channel)/([^/?#]+)", re.IGNORECASE)


def parse_boxcast_id(url: str) -> Optional[str]:
    """The opaque id out of any of the three confirmed `boxcast.tv` URL
    shapes, or None if this isn't one of them."""
    parsed = urlparse(url)
    if parsed.netloc.lower() not in ("boxcast.tv", "www.boxcast.tv"):
        return None
    match = _BOXCAST_URL_RE.match(parsed.path)
    return match.group(1) if match else None


async def _get_json(session: aiohttp.ClientSession, url: str) -> Optional[object]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            return await resp.json(content_type=None)
    except Exception:
        logger.warning("BoxCast GET failed for %s", url, exc_info=True)
        return None


async def _fetch_broadcast(
    session: aiohttp.ClientSession, broadcast_id: str
) -> Optional[dict]:
    """`GET /broadcasts/{id}` -- full per-broadcast metadata, 404s for a
    real channel id (confirmed live, module docstring)."""
    payload = await _get_json(
        session, f"https://rest.boxcast.com/broadcasts/{broadcast_id}"
    )
    return payload if isinstance(payload, dict) else None


async def _fetch_channel_broadcasts(
    session: aiohttp.ClientSession, channel_id: str
) -> Optional[List[dict]]:
    """`GET /channels/{id}/broadcasts?...&s=-starts_at` -- None (not `[]`)
    when `channel_id` isn't a real channel at all (404s), so a caller can
    tell "no such channel" apart from "a real channel with zero
    broadcasts". Works identically for a real multi-broadcast government
    channel and a `/view`|`/view-embed` single-broadcast pseudo-channel
    (confirmed live, module docstring) -- both answer this same
    endpoint."""
    url = (
        f"https://rest.boxcast.com/channels/{channel_id}/broadcasts"
        f"?l={_SEARCH_LIMIT}&s=-starts_at"
    )
    payload = await _get_json(session, url)
    if payload is None:
        return None
    return (
        [b for b in payload if isinstance(b, dict)] if isinstance(payload, list) else []
    )


async def _fetch_view(
    session: aiohttp.ClientSession, broadcast_id: str
) -> Optional[dict]:
    """`GET /broadcasts/{id}/view` -- `{"status", "playlist"}`."""
    payload = await _get_json(
        session, f"https://rest.boxcast.com/broadcasts/{broadcast_id}/view"
    )
    return payload if isinstance(payload, dict) else None


async def _fetch_account(
    session: aiohttp.ClientSession, account_id: str
) -> Optional[dict]:
    """`GET /accounts/{id}` -- `{"id", "name", "channel_id", ...}`, the
    clean jurisdiction name plus the STABLE government channel id (module
    docstring's "A different thing again" section) -- None on any
    failure, never blocks the rest of the resolve."""
    if not account_id:
        return None
    payload = await _get_json(
        session, f"https://rest.boxcast.com/accounts/{account_id}"
    )
    return payload if isinstance(payload, dict) else None


def _looks_like_meeting(name: Optional[str]) -> bool:
    """Conservative "auto-pick this as a real meeting" gate for a channel
    scan (module docstring's "A channel URL auto-picks" section) --
    requires BOTH a positive governing-body/meeting keyword AND no Kind B
    ("not a deliberative meeting") hit from the shared hand-check phrase
    list. Never applied to a URL that already names one specific
    broadcast directly (`resolve()` only calls this when picking among
    more than one candidate)."""
    if not name:
        return False
    hand_check = classify_video_hand_check(name, None, None, None)
    if hand_check is not None and hand_check[0] == "B":
        return False
    low = name.lower()
    return any(kw in low for kw in _MEETING_LIKE_KEYWORDS)


async def _resolve_id(
    session: aiohttp.ClientSession, raw_id: str
) -> Tuple[str, List[dict]]:
    """`("channel", broadcasts)` or `("broadcast", [broadcast])`,
    whichever the real API says `raw_id` actually is (module docstring;
    this WO's own brief: "tell them apart by asking the API"). `("unknown",
    [])` when neither endpoint recognizes it at all."""
    broadcasts = await _fetch_channel_broadcasts(session, raw_id)
    if broadcasts is not None:
        return "channel", broadcasts
    broadcast = await _fetch_broadcast(session, raw_id)
    if broadcast is not None:
        return "broadcast", [broadcast]
    return "unknown", []


# --- Caption reassembly (module docstring's "Captions ARE real" section) ---

_CAPTION_CONCURRENCY = 10
_SUBTITLE_MEDIA_RE = re.compile(
    r'#EXT-X-MEDIA:TYPE=SUBTITLES[^\n]*URI="([^"]+)"', re.IGNORECASE
)


def _extract_subtitle_track_url(master_text: str, master_url: str) -> Optional[str]:
    """The first `#EXT-X-MEDIA:TYPE=SUBTITLES` track's absolute URL in a
    BoxCast master HLS playlist, or None (most tenants: no track at all,
    confirmed on Wilmington OH/Hondo TX; a genuine account-level absence,
    not a fetch failure)."""
    match = _SUBTITLE_MEDIA_RE.search(master_text)
    return urljoin(master_url, match.group(1)) if match else None


def _parse_subtitle_media_playlist(text: str) -> List[str]:
    """The ordered list of segment URLs from a BoxCast subtitle media
    playlist -- every non-comment, non-blank line. Each is a signed
    `captions.boxcast.com/.../webvtt?...` URL carrying its own
    `start_mpegts`/`stop_mpegts` query parameters, but those turned out
    NOT to be needed for reassembly -- see module docstring's own
    "confirmed live" correction below `_fetch_boxcast_captions()`."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


async def _fetch_boxcast_captions(
    session: aiohttp.ClientSession, master_text: str, master_url: str
) -> Tuple[Optional[List[dict]], Optional[str]]:
    """`(cues, language)` for this broadcast's real BoxCast captions, or
    `(None, None)` on any failure or genuine absence -- never raises, so
    a caller always has the video-only fallback available. `cues` are
    plain dicts (`start`/`end`/`text`) ready for `TranscriptSegment(**cue)`,
    already deduped/normalized through the shared `vtt_parser` pipeline
    every other adapter here uses.

    Each ~12-second segment's own WebVTT cues carry ABSOLUTE
    broadcast-relative timestamps already, confirmed live 2026-09-11 by
    sampling 20 segments spread across a real 107-minute meeting (every
    25th of 533): a segment at playlist index N has its own first real
    cue at N*12 seconds +/- ~3 seconds, every time, from the start of the
    recording straight through to the end. That ruled out this module's
    first assumption -- that a segment's own `#EXT-X-TIMESTAMP-MAP` /
    `start_mpegts` query parameter had to be used to shift each segment's
    cues onto a shared timeline. It does not: that field barely changes
    across the whole file (two distinct values seen across a 533-segment
    real playlist) and is roughly 548 seconds off true position where it
    was checked, i.e. it isn't this recording's own zero point at all --
    using it to compute an offset (an earlier version of this function
    did) silently roughly DOUBLED every later cue's timestamp, caught
    only by checking a real resolve's own last segment against the
    broadcast's real, known duration. So: no offset math at all -- concat
    each segment's parsed cues, in playlist order, as-is."""
    subtitle_url = _extract_subtitle_track_url(master_text, master_url)
    if not subtitle_url:
        return None, None

    playlist_text, _ = await _get_text(session, subtitle_url)
    if not playlist_text:
        return None, None

    segment_urls = _parse_subtitle_media_playlist(playlist_text)
    if not segment_urls:
        return None, None

    semaphore = asyncio.Semaphore(_CAPTION_CONCURRENCY)

    async def _fetch_segment(segment_url: str) -> Optional[str]:
        async with semaphore:
            text, _ = await _get_text(session, segment_url)
            return text

    fetched = await asyncio.gather(
        *[_fetch_segment(url) for url in segment_urls], return_exceptions=True
    )

    all_cues: List[dict] = []
    ok_count = 0
    for body in fetched:
        if not isinstance(body, str) or not body:
            continue
        ok_count += 1
        all_cues.extend(parse_vtt(body))

    # Fewer than half the segments came back -- treat as a failed fetch
    # rather than deliver a transcript with large silent holes in it
    # (never observed live -- 533/533 succeeded on the real meeting this
    # was built against -- but a real, honest floor to have rather than
    # ship whatever fraction happened to succeed).
    if ok_count < len(segment_urls) / 2:
        return None, None
    if not all_cues:
        return None, None

    all_cues = dedupe_rollup_cues(all_cues)
    language = detect_language_from_texts(c.get("text") for c in all_cues)
    return all_cues, language


async def _get_text(
    session: aiohttp.ClientSession, url: str
) -> Tuple[Optional[str], Optional[int]]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None, resp.status
            return await resp.text(), resp.status
    except Exception:
        return None, None


class BoxcastAssetFinder(AssetFinder):
    """See this module's docstring for the full live investigation."""

    platform_name = "boxcast"

    async def resolve(self, url: str) -> ResolvedMeeting:
        raw_id = parse_boxcast_id(url)
        if not raw_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "We couldn't find a BoxCast broadcast or channel here."
                ],
            )

        async with aiohttp.ClientSession() as session:
            shape, broadcasts = await _resolve_id(session, raw_id)
            if shape == "unknown":
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[
                        "We couldn't find this BoxCast broadcast or channel."
                    ],
                )

            past = [b for b in broadcasts if b.get("timeframe") == "past"]
            if not past:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[
                        "This BoxCast channel has no recorded broadcasts yet."
                    ],
                )

            if len(past) == 1:
                # Exactly one past broadcast -- true for a genuine
                # single-broadcast `/view`|`/view-embed` link (the normal
                # case) and, more rarely, a real government channel that
                # happens to have only one recording so far. Either way
                # there is nothing to auto-pick among, so no title
                # filtering (module docstring: the same trust level a
                # direct Vimeo/YouTube video URL gets).
                target = past[0]
            else:
                past_sorted = sorted(
                    past, key=lambda b: b.get("starts_at") or "", reverse=True
                )
                meeting_like = [
                    b for b in past_sorted if _looks_like_meeting(b.get("name"))
                ]
                if not meeting_like:
                    return ResolvedMeeting(
                        platform=self.platform_name,
                        source_url=url,
                        video_warnings=[
                            "Found this BoxCast channel, but none of its recent "
                            "broadcasts look like a real meeting."
                        ],
                    )
                target = meeting_like[0]

            if shape == "channel":
                # `GET /channels/{id}/broadcasts` (the endpoint `_resolve_id()`
                # used to find `target`) omits `time_zone_offset` on every
                # item -- confirmed live on all 25 real Atlantic City
                # broadcasts it returned -- while `GET /broadcasts/{id}`
                # (the "broadcast" shape's own source) carries it. Without
                # this re-fetch, `_broadcast_local_date()` below would
                # silently fall back to a bare UTC date for anything
                # reached via a channel scan, wrong for any evening
                # meeting whose UTC timestamp has already rolled into the
                # next calendar day (the exact bug that function's own
                # docstring exists to prevent). The "broadcast" shape
                # already came from `/broadcasts/{id}` directly, so it
                # already has this field and needs no re-fetch.
                full = await _fetch_broadcast(session, target.get("id") or "")
                target = full or target

            # `raw_id` is only a candidate for a real, distinct,
            # per-government channel when the scan reached it AS a
            # channel at all (module docstring: a `/view`|`/view-embed`
            # single-broadcast pseudo-channel also answers the channel
            # endpoint, so `shape == "channel"` alone doesn't mean
            # `raw_id` is the stable government channel -- `_resolve_broadcast()`
            # below tells the two apart itself by comparing `raw_id`
            # against the picked broadcast's own `channel_id`).
            channel_hint = raw_id if shape == "channel" else None

            return await self._resolve_broadcast(session, target, url, channel_hint)

    async def _resolve_broadcast(
        self,
        session: aiohttp.ClientSession,
        broadcast: dict,
        original_url: str,
        channel_hint: Optional[str] = None,
    ) -> ResolvedMeeting:
        broadcast_id = broadcast.get("id")
        title = broadcast.get("name") or None
        date = _broadcast_local_date(broadcast)
        # The broadcast's own dedicated one-broadcast pseudo-channel
        # (module docstring) -- BoxCast's real, public URL for exactly
        # this broadcast, stable across re-resolves regardless of which
        # of the three URL shapes originally reached it (a channel scan
        # can pick a different "newest" broadcast on a later re-resolve;
        # this specific broadcast's own URL never does).
        own_slug = broadcast.get("channel_id") or broadcast_id
        source_url = f"https://boxcast.tv/view/{own_slug}" if own_slug else original_url

        # A real, DISTINCT channel the scan actually reached (`channel_hint`)
        # is a MORE reliable stable id than the broadcast's own account --
        # confirmed live 2026-09-11 (WO-227b) on two of the five new
        # tenants this WO was built for: Livermore Falls, ME's and
        # Atlantic Beach, SC's own real, dedicated, multi-broadcast
        # channels (`vvohjjgvcdbmeatv03km`, `dtoujlfjxuu2lde6bvp8`) sit on
        # a SHARED regional media operator's BoxCast account -- Mt. Blue
        # Television (Farmington, ME; real channel also carries Farmington
        # Select Board, Jay Select Board, RSU 9 school board and high-school
        # sports broadcasts) and "Media Mike" respectively, not a
        # government-owned account. Blindly trusting `account.channel_id`
        # (the ONLY id the module used before this WO) would silently
        # collapse every government on that shared account onto ONE
        # external_id -- the exact multi-gov-host hazard
        # `docs/COVERAGE_HANDOVER.md` section 3 already documents for
        # youtube.com/vimeo.com, just one layer deeper (a shared account
        # inside a single-tenant-looking host). `channel_hint` is only
        # trusted when it's genuinely a DIFFERENT id than the picked
        # broadcast's own one-off pseudo-channel (`own_slug` above) --
        # equal to it (Wilmington OH/Hondo TX/Bartow FL/Ingleside TX, all
        # reached via a `/view`|`/view-embed` link whose id IS that
        # one-off slug) means there was nothing distinct to prefer, and
        # the account fallback below is exactly right (each of those
        # four is a genuine single-tenant government account, confirmed
        # live). See `tests/test_boxcast.py`'s Livermore Falls/Atlantic
        # Beach cases for the full before/after.
        distinct_channel = (
            channel_hint if channel_hint and channel_hint != own_slug else None
        )

        external_id: Optional[str] = None
        jurisdiction: Optional[str] = None
        account_id = broadcast.get("account_id")
        if account_id:
            account = await _fetch_account(session, account_id)
            if account:
                account_channel_id = account.get("channel_id")
                channel_id = distinct_channel or account_channel_id
                if channel_id:
                    external_id = f"boxcast:{channel_id}"
                # The account's own `name` is only trustworthy as THIS
                # meeting's jurisdiction when the account is (as far as
                # this resolve can tell) single-tenant -- i.e. its own
                # channel_id agrees with the distinct channel we already
                # trust, or there was no distinct channel to compare
                # against at all. A shared media operator's account name
                # ("Mt. Blue Television - Farmington, ME", "Media Mike")
                # is never the right jurisdiction for ANY one government
                # on it -- left blank here rather than guessed, same
                # "never claim what isn't confirmed" posture as the
                # caption-path discipline elsewhere in this module.
                if distinct_channel and distinct_channel != account_channel_id:
                    jurisdiction = None
                else:
                    name = account.get("name")
                    if name and isinstance(name, str):
                        jurisdiction = name
        elif distinct_channel:
            external_id = f"boxcast:{distinct_channel}"

        if not broadcast_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=source_url,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                external_id=external_id,
                video_warnings=[
                    "This BoxCast broadcast has no id to fetch video from."
                ],
            )

        view = await _fetch_view(session, broadcast_id)
        if not view or view.get("status") != "recorded":
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=source_url,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                external_id=external_id,
                video_warnings=[
                    "This BoxCast broadcast's recording isn't available yet."
                ],
            )
        video_url = view.get("playlist")
        if not isinstance(video_url, str) or not video_url:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=source_url,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                external_id=external_id,
                video_warnings=["This BoxCast broadcast has no playable recording."],
            )

        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=source_url,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            external_id=external_id,
            video_url=video_url,
            video_format="m3u8",
            transcript_warnings=[_NO_CAPTIONS_WARNING],
        )

        # Purely additive (module docstring's "Captions ARE real"
        # section) -- any failure here (master playlist fetch, no
        # subtitle track, a segment fetch/parse problem) leaves the
        # video-only warning above untouched.
        try:
            master_text, _ = await _get_text(session, video_url)
            if master_text:
                cues, language = await _fetch_boxcast_captions(
                    session, master_text, video_url
                )
                if cues:
                    resolved.segments = [TranscriptSegment(**cue) for cue in cues]
                    resolved.transcript_language = language
                    resolved.transcript_warnings = []
                    if is_likely_garbled(cues):
                        resolved.transcript_warnings.append(
                            "This transcript looks garbled at the source (not a "
                            "parsing bug on our end) -- treat it as approximate."
                        )
        except Exception:
            logger.warning(
                "BoxCast caption fetch failed for broadcast %s",
                broadcast_id,
                exc_info=True,
            )

        return resolved
