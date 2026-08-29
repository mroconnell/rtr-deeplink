"""BoxCast video delegation for ProudCity's `video_style === 'external'`
case (`proudcity.py`'s `_EXTERNAL_VIDEO_RE`) -- a plain outbound link to
a whole BoxCast *channel*, e.g. `boxcast.tv/channel/x1jps4n28nlgtaozsv5y`
(Wilmington, OH's real link, `wilmingtonohio.gov/meetings/city-council-
meeting-april-16-2026`), not a link to one specific broadcast. So unlike
a normal single-URL resolve, this needs to MATCH the ProudCity page's own
already-known meeting date to the right broadcast within the channel --
the same shape of problem `youtube_channel.py` already solves for
Legistar/YouTube, via a real, confirmed, unauthenticated REST API rather
than a headless player.

Investigated 2026-08-27/29 (BACKLOG.md's ProudCity/BoxCast `[NEEDS-AUDIT]`
entry): `_EXTERNAL_VIDEO_RE` correctly finds the channel link and reports
it as `video_link` (never `video_url`, since a channel link alone isn't
directly playable), but the real playable HLS manifest URL was
unconfirmed -- BoxCast's own web player (`boxcast.tv/view/{slug}`)
renders into a `blob:` MediaSource URL with no segment-fetch requests
visible in a plain JS-bundle read. **The real unlock, confirmed live
2026-08-29 across three independent real government tenants** (Wilmington
OH, St. Louis County - Clayton MO, City of Hondo TX -- found via a plain
web search for `"boxcast.tv/channel"`, not guessed):

    GET https://rest.boxcast.com/channels/{channel_id}/broadcasts/_search?l={N}

is a real, public, unauthenticated REST API (found via `boxcast.tv`'s own
JS bundle, same discovery as the original investigation) returning every
broadcast's real `id`/`name`/`starts_at`/`stops_at`/`time_zone_offset` for
a channel -- unlike `youtube_channel.py`'s flat yt-dlp listing, this
carries REAL structured dates directly, no title-parsing needed. And:

    GET https://rest.boxcast.com/broadcasts/{broadcast_id}/view

returns `{"status": "recorded", "playlist": "https://play.boxcast.com/
p/{id}/r/{start}s/{end}s/v/all.m3u8?Expires=...&Signature=...&
Key-Pair-Id=..."}` -- a genuine, working, unauthenticated signed HLS
master playlist, confirmed live with a real `curl` fetch (200,
`content-type: application/vnd.apple.mpegurl`, real multi-bitrate
`#EXT-X-STREAM-INF` variants) against all three tenants above, not just
Wilmington. No transcript/caption source found or expected here -- BoxCast
government tenants checked carry no confirmed caption track, so this is
video-only, the same honest posture Vimeo's adapter takes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import aiohttp

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
