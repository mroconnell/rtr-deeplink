"""Match a Legistar meeting to a Granicus "Video on Demand" RSS item, for
the confirmed case where the meeting-management system's own video-link
mechanism (`a.videolink[onclick]`, see `legistar.py`) attaches nothing
even though a real Granicus recording exists under a *different* meeting
id in the tenant's own public listing.

Why this exists
----------------
Kansas City, MO (`kansascity.legistar.com`) confirmed live 2026-08-29:
checked 9 real Council meetings across 9 different dates (2026-05-21
through 2026-08-20) and every single one has NO `a.videolink[onclick]`
video mechanism at all -- not a rare gap, the structural norm for this
body. A broader sweep of 49 real committee bodies (one recent meeting
each, 2026-07-01..2026-08-25) found only 2/49 resolving real video via
the existing mechanisms. This isn't the already-covered "video column is
structurally empty, recordings live only on the city's own YouTube
channel" case `youtube_channel.py` handles (Phoenix/Philadelphia/
Baltimore/Albuquerque, WO-30) -- Kansas City's real recordings are on
Granicus, not YouTube, and they're not unlinked from *everywhere*: the
tenant's own "Video on Demand" listing
(`kansascity.granicus.com/ViewPublisher.php?view_id=2`) has them, just
under Granicus's own separate per-meeting id space, with no link back
from the Legistar page to it.

`ViewPublisherRSS.php?view_id={id}&mode=video` -- the same real,
public, unauthenticated Granicus RSS feed `granicus.py`'s own
`_fetch_channel_info()` already reads (there, only to *corroborate* a
date/jurisdiction once a `clip_id` is already known) -- confirmed live
to carry every recent meeting across every body on the tenant in ONE
feed (100 real items checked, spanning 2025-12-16..2026-08-20; Council,
committee, and board meetings all mixed together, not one feed per
body), each with a real structured `<gran:pubDateParts>` date and a
`<link>` carrying a real `clip_id` -- `granicus.py`'s own already-tested
`clip_id`-based extraction handles the resulting URL with zero new code.
Confirmed end-to-end live: a matched clip_id resolves a real, playable
`archive-stream.granicus.com/.../playlist.m3u8`.

Unlike `youtube_channel.py`'s YouTube listing (no dates at all, title-
parsing required, capped at ~400 lazily-unbounded entries), this RSS
feed carries real dates directly and needs no title-date-parsing -- but
is capped at 100 most-recent items (unconfirmed whether that's a hard
platform limit or just this feed's current size), so an older meeting
than the feed covers won't be found here either.

Curated per-tenant, same as `youtube_channel.py`'s `_CHANNEL_FALLBACKS`
-- this is real, confirmed live for exactly one tenant so far (Kansas
City), not a general Legistar+Granicus rule. Add a second entry once
another real Legistar tenant with the same "video exists on Granicus,
just not linked from the meeting page" shape is confirmed.

Real wording drift confirmed live between Legistar's own body name and
Granicus's own RSS item title for the SAME committee (see `_normalize()`
below): KC's Legistar names one real committee "Finance, Governance and
Public Safety Committee" while Granicus's RSS titles it "Finance
Governance & Public Safety Committee" -- comma dropped, "&" instead of
"and". `_normalize()` closes this specific confirmed case; a title from
this RSS feed is always HTML-entity-encoded ("&amp;"), so any caller
comparing it must `html.unescape()` first or a literal "&" is never
actually found to normalize.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger("rtr_deeplink.granicus_channel")


@dataclass
class ViewPublisherFallback:
    granicus_domain: str
    view_id: str


# Confirmed live 2026-08-29 -- see this module's own docstring.
_VIEW_PUBLISHER_FALLBACKS: Dict[str, ViewPublisherFallback] = {
    "kansascity.legistar.com": ViewPublisherFallback(
        granicus_domain="kansascity.granicus.com", view_id="2"
    ),
}


def has_view_publisher_fallback(netloc: str) -> bool:
    return (netloc or "").lower().lstrip(".") in _VIEW_PUBLISHER_FALLBACKS


_ITEM_RE = re.compile(r"<item>((?:(?!</item>).)*?)</item>", re.DOTALL)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>")
# The real link text HTML-entity-encodes its query string ("&amp;clip_id
# =...", confirmed live), so match "clip_id=" directly rather than
# requiring a literal "?"/"&" separator right before it -- same fix
# granicus.py's own _fetch_channel_info() already needed for the
# identical RSS <item> shape (see its own docstring).
_CLIP_LINK_RE = re.compile(r"<link>([^<]*clip_id=\d+[^<]*)</link>")
_PUBDATE_PARTS_TAG_RE = re.compile(r"<gran:pubDateParts\b[^>]*/?>")


def _normalize(text: str) -> str:
    """Real, confirmed-live wording drift between Legistar's own body name
    and Granicus's own RSS item title for the SAME real committee: KC's
    Legistar names it "Finance, Governance and Public Safety Committee"
    (comma, "and"), Granicus's RSS titles it "Finance Governance & Public
    Safety Committee" (no comma, "&") -- while other real committees
    (Transportation, Infrastructure and Operations) keep the comma on both
    sides. Comma-stripping and "&"<->"and" normalization close this
    specific confirmed gap without assuming every punctuation difference
    needs handling -- only the two variants actually observed live."""
    text = text.replace("&", "and").replace(",", "")
    return re.sub(r"\s+", " ", text).strip().casefold()


def _item_local_date(item_xml: str) -> Optional[str]:
    """Same real `gran:pubDateParts` shape `granicus.py`'s own
    `_fetch_channel_info()` already parses -- see that function's
    docstring for the confirmed live example this mirrors."""
    tag_match = _PUBDATE_PARTS_TAG_RE.search(item_xml)
    if not tag_match:
        return None
    tag = tag_match.group(0)
    yr = re.search(r"yr=['\"](\d{4})['\"]", tag)
    mo = re.search(r"mo=['\"](\d{1,2})['\"]", tag)
    day = re.search(r"day=['\"](\d{1,2})['\"]", tag)
    if not (yr and mo and day):
        return None
    try:
        return date_cls(
            int(yr.group(1)), int(mo.group(1)), int(day.group(1))
        ).isoformat()
    except ValueError:
        return None


def _item_body_and_clip_url(item_xml: str) -> Optional[tuple]:
    title_match = _TITLE_RE.search(item_xml)
    link_match = _CLIP_LINK_RE.search(item_xml)
    if not title_match or not link_match:
        return None
    # Real confirmed title shape: "{Body name} - {Mon DD, YYYY}" (an
    # inconsistent extra space sometimes precedes the " - ", normalized
    # away by _normalize() at comparison time, not here) -- rsplit on the
    # LAST " - " rather than the first, since a body name could itself
    # contain " - " (not observed yet, but cheap to guard against).
    # html.unescape() first: the raw XML text is entity-encoded ("&amp;"),
    # and _normalize()'s own "&"->"and" substitution (see its docstring)
    # needs a literal "&" to find -- real bug caught live: comparing the
    # un-unescaped "&amp;" left "andamp;" behind instead of "and".
    title = html.unescape(title_match.group(1))
    body = title.rsplit(" - ", 1)[0].strip()
    clip_url = html.unescape(link_match.group(1))
    return body, clip_url


@dataclass
class ViewPublisherMatch:
    clip_url: str
    item_body: str


async def find_view_publisher_match(
    netloc: str, meeting_body: Optional[str], meeting_date: Optional[str]
) -> Optional[ViewPublisherMatch]:
    """Returns the one confidently-matching Granicus RSS item for this
    tenant's known fallback feed, or None -- None is not an error, it's
    the honest "nothing found" outcome, same posture as
    `youtube_channel.find_channel_match()`.
    """
    fallback = _VIEW_PUBLISHER_FALLBACKS.get((netloc or "").lower().lstrip("."))
    if not fallback or not meeting_body or not meeting_date:
        return None
    try:
        datetime.strptime(meeting_date, "%Y-%m-%d")
    except ValueError:
        return None

    rss_url = (
        f"https://{fallback.granicus_domain}/ViewPublisherRSS.php"
        f"?view_id={fallback.view_id}&mode=video"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                rss_url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Granicus ViewPublisher RSS fetch got HTTP %s for %s",
                        response.status,
                        rss_url,
                    )
                    return None
                xml = await response.text()
    except Exception:
        logger.warning(
            "Granicus ViewPublisher RSS fetch failed for %s", rss_url, exc_info=True
        )
        return None

    wanted_body = _normalize(meeting_body)
    candidates: List[ViewPublisherMatch] = []
    for item_match in _ITEM_RE.finditer(xml):
        item_xml = item_match.group(1)
        if _item_local_date(item_xml) != meeting_date:
            continue
        parsed = _item_body_and_clip_url(item_xml)
        if not parsed:
            continue
        item_body, clip_url = parsed
        if _normalize(item_body).startswith(wanted_body):
            candidates.append(
                ViewPublisherMatch(clip_url=clip_url, item_body=item_body)
            )

    if len(candidates) != 1:
        # Either nothing matched, or more than one real meeting shares
        # this date and this body-name prefix (not confirmed to happen in
        # practice, but declining is the same safe posture every other
        # matcher in this file's sibling modules takes) -- an honest
        # "nothing found" beats a guess either way.
        return None
    return candidates[0]
