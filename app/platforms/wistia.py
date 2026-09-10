"""Wistia -- a general-purpose video host, confirmed live 2026-09-10 as
the real, tier-1-shaped platform behind RegionalWebTV (Advanced Media
Solutions of Virginia, `amsva.wistia.com`), the video vendor for at least
four confirmed Virginia governments: Warrenton (town), Manassas (city),
Fredericksburg (city), and Stafford County. Built for WO-161, following
CLAUDE.md's "never build a platform adapter from assumption" rule -- every
shape below was fetched and read live before being coded.

## Why this is tier 1, not just another video host

Every real Wistia endpoint below is a plain, unauthenticated `aiohttp`
GET, confirmed live against Warrenton's own channel:

* Channel listing -- `https://fast.wistia.com/embed/channel/{channelId}.json`
  -- real titled episodes newest-first, e.g. "Warrenton Town Council
  Evening Session 9/8/2026" (`durationInSeconds: 9869.17`).
* Media metadata -- `https://fast.wistia.com/embed/medias/{hashedId}.json`
  -- real `name`/`duration`/`createdAt`, plus a `media.assets[]` list of
  **public, unauthenticated, byte-range-capable MP4 delivery URLs**
  (confirmed live with a plain `curl -I`: `content-type: video/mp4`,
  `accept-ranges: bytes`, no Referer/signed-token needed) -- unlike
  Vimeo, whose real media file is walled off behind a signed config this
  app can't reach (see vimeo.py's own docstring), Wistia hands over a
  directly playable file for free.
* Captions -- `https://fast.wistia.com/embed/captions/{hashedId}.vtt?language=eng`
  -- a real, full WebVTT transcript with real timestamps (confirmed live
  on Warrenton's 8/11/2026 evening session, 3,953 lines). This is the
  genuine tier-1 property: real video AND real captions, no headless
  browser, no signed URL, no third caption-fetch trick needed at all.

A dead/pruned id answers HTTP 200 with `{"error": true, "iframe": true}`
(confirmed live against several 2019/2021 hashed ids linked from
RegionalWebTV's own year-archive pages) -- **not** a 404. Every fetch
below checks for this `error` key explicitly; treating a 200 as success
without checking it would silently "resolve" a dead meeting with no
video and no captions. Real caution, confirmed live (2026-09-10, see
`~/Documents/rtr-business/research/ENUMERATION_METHODS.md` §186): every
2019/2021-dated media id checked from RegionalWebTV's archive pages came
back dead this way, while current-year (2026) content resolved fully --
so a sweep against this vendor should target *this year's* meetings, not
its historical archive.

## The account/tenant shape

`{account}.wistia.com` is the human-facing per-account subdomain
(`amsva.wistia.com` for RegionalWebTV/AMS-VA). It is NOT one tenant per
government -- confirmed live, `amsva.wistia.com` alone carries at least
four separate Virginia governments' channels -- so (per this module's
own `tenant_overrides.csv` guidance, see `app/utils/gov_registry/
resolver.py`) a pin against this shared account needs a per-media or
per-channel match, never a bare `match=host=amsva.wistia.com` rule.
`fast.wistia.com`/`fast.wistia.net`/`embed-ssl.wistia.com`/
`app.wistia.com` are Wistia's own infrastructure hosts, not government
tenants, and `wistia.com`/`www.wistia.com` are the vendor's own
marketing site -- both excluded the same way `base.py`'s
`CORPORATE_HOSTS_BY_PLATFORM` already excludes every other vendor's
corporate host (WO-163).

## The two real URL shapes a caller hands this adapter

1. **A direct Wistia URL** -- `https://{account}.wistia.com/medias/{hashedId}`
   (a single meeting) or `https://{account}.wistia.com/channel/{channelId}`
   (a listing of many -- raises `CalendarPageError`, same pattern as
   Vimeo's showcase/channel listings). `amsva.wistia.com/medias/{id}` is
   real and browsable (confirmed live, HTTP 200); the bare
   `{account}.wistia.com/channel/{id}` page itself 404s on the one real
   channel checked (Warrenton's `kcpy3xurof`) even though the channel's
   own JSON API resolves fine -- Wistia channels appear to be
   embed-only, not independently browsable pages, on at least this
   account. Detection doesn't depend on that page actually rendering:
   the URL *shape* is what's classified, and resolution goes straight to
   the JSON API either way.

2. **A delegating government page** -- confirmed live against
   RegionalWebTV's own per-government pages (`regionalwebtv.com/{slug}`,
   a Wix site) in two real, different shapes:
   - Older year-archive pages (e.g. `regionalwebtv.com/fredcc2019`) are
     plain, server-rendered HTML with real `<a href="https://amsva.
     wistia.com/medias/{id}">` links, one per meeting -- no JS rendering
     needed. `resolve()` finds these itself, but a page like this would
     *also* already be caught by `base.py`'s own `find_platform_link()`
     scan (used by `generic_fallback.py`), since a bare `<a href>` to a
     URL this module's own `detect_platform()` branch now recognizes is
     exactly the shape that scanner already looks for -- this module's
     own scan exists for the embed shapes below, which that generic
     scanner's href/src-only check cannot see.
   - Current-year pages (e.g. `regionalwebtv.com/warrentontc`) embed the
     account's whole CHANNEL via a Wix "Embed HTML" custom-code widget
     -- confirmed live (2026-09-10, via a real headless-browser render
     plus reading the rendered DOM's `<iframe>` elements) that the outer
     page's *static* HTML carries no mention of Wistia at all; the
     channel embed (`class="wistia_channel wistia_async_kcpy3xurof"`,
     Wistia's own standard channel-embed code) lives inside a SECOND,
     separate document at a Wix-hosted custom-HTML URL
     (`{site}.filesusr.com/html/{id}.html`) that the outer page's own
     client-side JS runtime injects as an `<iframe src=...>` -- never
     present in the outer page's server-rendered markup. That inner
     document, once found, is itself perfectly plain static HTML (no
     further JS needed to read it) -- the JS rendering is only needed to
     discover *which* nested document to fetch. `_resolve_delegating()`
     below tries a plain fetch first (covers the archive-page shape for
     free) and only escalates to a headless render, then a plain fetch
     of any nested `<iframe src>` found in the rendered DOM, when the
     plain fetch alone turns up nothing -- the same purely-additive,
     never-worse-than-before shape as `vimeo.py`'s own headless-caption
     fallback.

`class="wistia_embed wistia_async_{id}"` (a single media, Wistia's other
standard embed code) and `fast.wistia.com/embed/medias/{id}.jsonp` /
`fast.wistia.net/embed/iframe/{id}` (both standard Wistia embed URL
forms, publicly documented by Wistia itself) are also recognized by the
same scan, alongside the two shapes above -- these three are Wistia's
own well-known, publicly documented embed codes, not independently
found live on a real government page by this session, so the fixtures
covering them are synthetic (commented as such in `tests/test_wistia.py`)
per CLAUDE.md's synthetic-test rule, reusing the exact class/URL shapes
Wistia's own documentation and the confirmed-live channel embed above
both use -- never an invented shape.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, CalendarCandidate, CalendarPageError
from .headless_browser import HeadlessBrowserUnavailable, fetch_via_browser
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.url_guard import guarded_get, read_capped_text
from ..utils.vtt_parser import (
    detect_language_from_texts,
    is_likely_garbled,
    parse_captions_by_extension,
)

logger = logging.getLogger("rtr_deeplink.wistia")

# A realistic desktop UA -- same reasoning as vimeo.py's/openmedia.py's
# own scoped UA, not applied app-wide: CLAUDE.md's "politely" bullet
# (a realistic header so a naive check doesn't false-positive us as a
# bot), not an attempt to evade anything.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Every real hashedId/channelId checked live (Warrenton's `kcpy3xurof`
# channel, `i2vooa0pno`/`t4pvo654qu`/etc. media ids) is a 10-char
# lowercase-alnum token; Wistia's own docs describe the id space as
# case-sensitive alphanumeric generally, so this is intentionally a
# little looser (8-12 chars, both cases) rather than over-fitting to the
# handful of ids seen so far.
_WISTIA_ID_RE = r"([a-zA-Z0-9]{8,12})"

# Wistia's own infrastructure/API hosts -- never a per-government tenant,
# same reasoning as `base.py`'s `CORPORATE_HOSTS_BY_PLATFORM` (which
# separately excludes the bare `wistia.com`/`www.wistia.com` marketing
# site). Kept here, not there, since these are *subdomain* exclusions
# specific to this module's own "is this a real {account} tenant host"
# check, not a bare host `detect_platform()` would otherwise misclassify
# as some OTHER platform.
_INFRA_SUBDOMAINS = frozenset(
    {"fast", "embed-ssl", "embed", "distillery", "app", "www", "support"}
)

_MEDIA_PATH_RE = re.compile(r"^/medias/" + _WISTIA_ID_RE + r"/?$")
_CHANNEL_PATH_RE = re.compile(r"^/channel/" + _WISTIA_ID_RE + r"/?$")

# The four delegating-page embed shapes this module recognizes -- see
# this module's own docstring for which are confirmed live vs. Wistia's
# own publicly documented standard embed codes.
_JSONP_MEDIA_RE = re.compile(
    r"fast\.wistia\.(?:com|net)/embed/medias/" + _WISTIA_ID_RE + r"\.jsonp"
)
_IFRAME_MEDIA_RE = re.compile(
    r"fast\.wistia\.(?:com|net)/embed/iframe/" + _WISTIA_ID_RE
)
_ASYNC_CLASS_RE = re.compile(
    r'class\s*=\s*"([^"]*\bwistia_async_' + _WISTIA_ID_RE + r"\b[^\"]*)\""
)
_PLAIN_MEDIA_ANCHOR_RE = re.compile(
    r'href\s*=\s*"https?://([a-zA-Z0-9-]+)\.wistia\.com/medias/' + _WISTIA_ID_RE
)
_PLAIN_CHANNEL_ANCHOR_RE = re.compile(
    r'href\s*=\s*"https?://([a-zA-Z0-9-]+)\.wistia\.com/channel/' + _WISTIA_ID_RE
)

# Real, confirmed governing-body suffixes seen in RegionalWebTV channel
# titles ("Warrenton Town Council", "Stafford Board of Supervisors", ...)
# -- used both to split off a `meeting_body` and to find the leading
# jurisdiction text to validate. Not a generic NLP guess: every entry is
# a literal phrase confirmed on a real title during this WO's own live
# checks.
_BODY_SUFFIXES = (
    "Town Council",
    "City Council",
    "Board of Supervisors",
    "School Board",
    "Planning Commission",
    "Board of Zoning Appeals",
    "Architectural Review Board",
    "Citizens Budget Review Committee",
)
_BODY_SUFFIX_RE = re.compile(
    r"^\s*(.*?)\s+(" + "|".join(re.escape(b) for b in _BODY_SUFFIXES) + r")\b",
    re.IGNORECASE,
)

# "8/11/2026" / "9/8/2026" (Warrenton, Manassas, Fredericksburg's own
# channels) and "1-6-2026" / "8-25-2026" (Stafford's own channel, found
# live 2026-09-10 during this WO's real ingest -- an earlier version of
# this regex only accepted "/" and silently fell through to
# `_date_from_unix()` on every Stafford title, which is the *upload*
# timestamp, one day off from the real "1-6-2026" meeting date on the
# one real sample checked). Both real m/d/yyyy separators seen live; no
# month-name or year-first shape has been confirmed on a real Wistia
# title yet, unlike vimeo.py's broader set, so only these are claimed.
_TITLE_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")

# Ryan's picking rule (docs/BREADTH_SWEEP_BRIEF.md, restated in this WO's
# own instructions): prefer a meeting between 9 and 40 minutes; if none
# in that window, take the shortest available rather than the longest.
_PREFERRED_MIN_SECONDS = 9 * 60
_PREFERRED_MAX_SECONDS = 40 * 60

# A dead/pruned Wistia id answers HTTP 200 with this body -- confirmed
# live on several 2019/2021 hashed ids linked from RegionalWebTV's own
# archive pages (see this module's docstring). Never a 404, so every
# fetch below checks for this key explicitly rather than trusting a 200
# status code alone.
_DEAD_ID_MARKER = "error"


def is_wistia_account_host(netloc: str) -> bool:
    """True for a real per-account `{account}.wistia.com` tenant host --
    false for the bare `wistia.com`/`www.wistia.com` marketing site and
    for Wistia's own infrastructure subdomains (`fast.`, `embed-ssl.`,
    etc, see `_INFRA_SUBDOMAINS`)."""
    netloc = netloc.lower().split(":")[0]
    if netloc in ("wistia.com", "www.wistia.com"):
        return False
    if not netloc.endswith(".wistia.com"):
        return False
    subdomain = netloc[: -len(".wistia.com")]
    return bool(subdomain) and subdomain not in _INFRA_SUBDOMAINS


def parse_wistia_account_url(url: str) -> Optional[Tuple[str, str, str]]:
    """`(kind, wistia_id, account)` for a direct `{account}.wistia.com`
    media or channel URL, `kind` being "media" or "channel" -- else
    None. Never matches an infra/marketing host (see
    `is_wistia_account_host()`)."""
    parsed = urlparse(url)
    if not is_wistia_account_host(parsed.netloc):
        return None
    account = parsed.netloc.lower().split(":")[0][: -len(".wistia.com")]
    match = _MEDIA_PATH_RE.match(parsed.path)
    if match:
        return "media", match.group(1), account
    match = _CHANNEL_PATH_RE.match(parsed.path)
    if match:
        return "channel", match.group(1), account
    return None


def _find_embed_in_html(html: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """`(kind, wistia_id, account_or_None)` for the first recognized
    Wistia embed shape in `html` -- see this module's docstring for the
    four shapes checked, in the order tried below. `account` is only
    ever known from the plain-anchor shapes (the account subdomain is
    right there in the URL); the embed-code shapes carry no account at
    all, which is fine -- `fast.wistia.net/embed/iframe/{id}` (confirmed
    live, HTTP 200) is a real, always-constructible fallback page that
    needs no account name."""
    if not html:
        return None
    match = _JSONP_MEDIA_RE.search(html)
    if match:
        return "media", match.group(1), None
    match = _IFRAME_MEDIA_RE.search(html)
    if match:
        return "media", match.group(1), None
    match = _ASYNC_CLASS_RE.search(html)
    if match:
        class_value, wistia_id = match.group(1), match.group(2)
        kind = "channel" if "wistia_channel" in class_value else "media"
        return kind, wistia_id, None
    match = _PLAIN_MEDIA_ANCHOR_RE.search(html)
    if match:
        return "media", match.group(2), match.group(1)
    match = _PLAIN_CHANNEL_ANCHOR_RE.search(html)
    if match:
        return "channel", match.group(2), match.group(1)
    return None


# Iframe hosts that are never worth a second plain fetch when hunting for
# a nested custom-HTML embed on a delegating page (WO-161's own
# RegionalWebTV live check turned up exactly this noise on a real Wix
# page: analytics/consent/live-chat iframes sit alongside the one real
# custom-HTML embed). Skipping these keeps the nested-iframe fallback to
# "a handful of fetches," per CLAUDE.md's politeness rule, rather than
# fetching every iframe a modern marketing site embeds.
_SKIP_NESTED_IFRAME_HOSTS = (
    "google.com",
    "googletagmanager.com",
    "doubleclick.net",
    "facebook.com",
    "recaptcha",
    "hcaptcha",
    "cookiebot",
)
_MAX_NESTED_IFRAMES_CHECKED = 4


def _date_from_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    match = _TITLE_NUMERIC_DATE_RE.search(title)
    if not match:
        return None
    month, day, year = (int(g) for g in match.groups())
    if 1 <= month <= 12 and 1 <= day <= 31:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _date_from_unix(value) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _jurisdiction_and_body(title: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """`(jurisdiction, meeting_body)` from a Wistia channel/media title --
    see `_BODY_SUFFIXES`. Declines (returns `(None, meeting_body)`) rather
    than guessing when the leading text doesn't independently validate as
    a real place, same reasoning as `vimeo.py`/`youtube.py`'s own
    `_jurisdiction()`. "Village of Friendship Heights" (no body suffix at
    all -- the channel title IS the jurisdiction) is handled by falling
    back to validating the whole title when no suffix matches."""
    title = (title or "").strip()
    if not title:
        return None, None
    match = _BODY_SUFFIX_RE.match(title)
    if match:
        base, body = match.group(1).strip(), match.group(2)
        # Normalize to the canonical casing from _BODY_SUFFIXES rather
        # than whatever casing the title happened to use.
        body_canonical = next(
            (b for b in _BODY_SUFFIXES if b.lower() == body.lower()), body
        )
    else:
        base, body_canonical = title, None
    if not base:
        return None, body_canonical
    if (
        jurisdiction_enrich.lookup_city_state(base)
        or jurisdiction_enrich.lookup_county_state(base)
        or jurisdiction_enrich.is_literal_known_place(base)
    ):
        return (
            jurisdiction_enrich.enrich_jurisdiction_text(base, netloc="wistia.com"),
            body_canonical,
        )
    return None, body_canonical


class WistiaAssetFinder(AssetFinder):
    """See this module's docstring for the full live investigation."""

    platform_name = "wistia"

    async def resolve(self, url: str) -> ResolvedMeeting:
        direct = parse_wistia_account_url(url)
        if direct:
            kind, wistia_id, account = direct
            if kind == "channel":
                return await self._resolve_channel_listing(
                    wistia_id, source_url=url, account=account
                )
            return await self.resolve_media_id(
                wistia_id, source_url=url, account=account
            )
        return await self._resolve_delegating_page(url)

    async def _resolve_delegating_page(self, url: str) -> ResolvedMeeting:
        html = await self._fetch(url)
        found = _find_embed_in_html(html) if html else None
        if not found:
            found = await self._find_embed_via_headless(url)
        if not found:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "We couldn't find a Wistia video or channel embed on this page."
                ],
            )
        kind, wistia_id, account = found
        if kind == "channel":
            resolved = await self._resolve_channel_listing(
                wistia_id, source_url=url, account=account
            )
            # _resolve_channel_listing always raises CalendarPageError for
            # a real channel -- this line only runs for the (currently
            # theoretical) empty-channel case, which returns a plain
            # ResolvedMeeting instead. Keep the delegating page as
            # source_url either way.
            resolved.source_url = url
            return resolved
        resolved = await self.resolve_media_id(
            wistia_id, source_url=url, account=account
        )
        # Delegation convention (see CLAUDE.md's wrapper-platform rule and
        # generic_fallback.py's own `_try_delegate_to_known_platform()`):
        # the government's own page stays `source_url`, not the Wistia
        # media URL resolve_media_id() defaults to.
        resolved.source_url = url
        return resolved

    async def _find_embed_via_headless(
        self, url: str
    ) -> Optional[Tuple[str, str, Optional[str]]]:
        """Purely additive fallback for a JS-rendered delegating page --
        confirmed live necessary for RegionalWebTV's own current-year
        government pages (see this module's docstring). Any failure
        (Playwright unavailable, timeout, no embed found even after
        rendering) returns None, same as a plain fetch finding nothing --
        never raises, never worse than not having this fallback at all."""
        try:
            html = await asyncio.wait_for(fetch_via_browser(url), timeout=30)
        except HeadlessBrowserUnavailable:
            return None
        except asyncio.TimeoutError:
            logger.warning("Wistia headless page fetch timed out for %s", url)
            return None
        except Exception:
            logger.warning(
                "Wistia headless page fetch failed for %s", url, exc_info=True
            )
            return None

        found = _find_embed_in_html(html)
        if found:
            return found

        # The embed itself may live inside a nested custom-HTML iframe the
        # outer page's JS injected (confirmed live: a Wix "Embed HTML"
        # widget hosted at a separate `{site}.filesusr.com/html/{id}.html`
        # URL) -- that inner document is plain static HTML once found, so
        # a normal `_fetch()` reads it, no second headless render needed.
        soup = BeautifulSoup(html, "html.parser")
        checked = 0
        for iframe in soup.find_all("iframe"):
            if checked >= _MAX_NESTED_IFRAMES_CHECKED:
                break
            src = (iframe.get("src") or "").strip()
            if not src or src.startswith("javascript:"):
                continue
            host = urlparse(src).netloc.lower()
            if not host or any(skip in host for skip in _SKIP_NESTED_IFRAME_HOSTS):
                continue
            checked += 1
            nested_html = await self._fetch(src)
            nested_found = _find_embed_in_html(nested_html) if nested_html else None
            if nested_found:
                return nested_found
        return None

    @classmethod
    async def resolve_media_id(
        cls,
        wistia_id: str,
        *,
        source_url: Optional[str] = None,
        account: Optional[str] = None,
        title_hint: Optional[str] = None,
    ) -> ResolvedMeeting:
        """Shared entry point for a single Wistia media -- used directly
        above, and available for any future wrapper platform that finds a
        Wistia media id on its own page the same way `chicago_elms.py`
        calls `VimeoAssetFinder.resolve_video_id()` (see CLAUDE.md's
        wrapper-platform rule).

        `title_hint` -- real, confirmed gap (WO-161, live-checked against
        Stafford/Augusta/Manassas/Fredericksburg's real channels): a
        media's own JSON `name` field is sometimes just the recording
        software's raw capture filename ("1 (50)", "2026-02-25 17-30-47"),
        not a human title -- Warrenton's own channel is the exception, not
        the rule (its media names are already clean, "Warrenton Town
        Council Evening Session 8/11/2026"). The channel JSON's own
        `episodeTitle` for the same media is consistently the real,
        human-written title. A caller that already has that (this
        module's own `_resolve_channel_listing`, or a script walking a
        channel to pick a meeting) should pass it here; it wins over
        `media.name` outright rather than only filling a blank, since a
        real capture filename is not "no title" -- it is a wrong one. A
        bare pasted `{account}.wistia.com/medias/{id}` URL has no channel
        context at all, so it still shows whatever `media.name` carries --
        a known, logged residual gap (see BACKLOG.md)."""
        canonical_url = _canonical_media_url(wistia_id, account)
        payload = await cls._fetch_media_json(wistia_id)
        if payload is None:
            return ResolvedMeeting(
                platform=cls.platform_name,
                source_url=source_url or canonical_url,
                external_id=f"wistia:{wistia_id}",
                video_warnings=["We couldn't read this video's details from Wistia."],
            )
        if payload.get(_DEAD_ID_MARKER):
            # Confirmed live: a dead/pruned Wistia id answers HTTP 200
            # with `{"error": true, "iframe": true}` -- this is a genuine
            # not-found, not a partial success, so it's raised rather than
            # silently returned as an empty ResolvedMeeting (per this
            # WO's own instructions: "never an empty result").
            raise ValueError(
                f"Wistia says this video no longer exists (id {wistia_id})."
            )

        media = payload.get("media") or {}
        title = title_hint or media.get("name") or None
        jurisdiction, meeting_body = _jurisdiction_and_body(title)
        video_url, video_format = _best_public_asset(media)

        resolved = ResolvedMeeting(
            platform=cls.platform_name,
            source_url=source_url or canonical_url,
            external_id=f"wistia:{wistia_id}",
            title=title,
            date=_date_from_title(title) or _date_from_unix(media.get("createdAt")),
            jurisdiction=jurisdiction,
            meeting_body=meeting_body,
            video_channel=account,
            video_url=video_url,
            video_format=video_format,
        )
        if video_url is None:
            resolved.video_warnings = [
                "We found this meeting on Wistia, but no playable video file was public."
            ]

        cues, language = await cls._fetch_captions(wistia_id)
        if cues:
            resolved.segments = [TranscriptSegment(**cue) for cue in cues]
            resolved.transcript_language = language
            if language and language != "en":
                resolved.transcript_warnings = [
                    f"These captions appear to be in '{language}', not 'en' -- no "
                    "matching-language track was found for this meeting."
                ]
            if is_likely_garbled(cues):
                resolved.transcript_warnings = (resolved.transcript_warnings or []) + [
                    "This transcript looks garbled at the source (not a parsing "
                    "bug on our end) -- treat it as approximate."
                ]
        else:
            resolved.transcript_warnings = [
                "We couldn't find captions for this meeting on Wistia."
            ]
        return resolved

    @classmethod
    async def _resolve_channel_listing(
        cls, channel_id: str, *, source_url: str, account: Optional[str] = None
    ) -> ResolvedMeeting:
        payload = await cls._fetch_channel_json(channel_id)
        if payload is None or payload.get(_DEAD_ID_MARKER):
            return ResolvedMeeting(
                platform=cls.platform_name,
                source_url=source_url,
                video_warnings=[
                    "This looks like a Wistia channel, but we couldn't read its "
                    "episode list."
                ],
            )
        episodes = list_channel_episodes(payload)
        if not episodes:
            return ResolvedMeeting(
                platform=cls.platform_name,
                source_url=source_url,
                video_warnings=[
                    "This is a Wistia channel, but it doesn't list any episodes."
                ],
            )
        candidates: List[CalendarCandidate] = [
            CalendarCandidate(
                title=ep["title"],
                date=_date_from_title(ep["title"]) or "",
                url=_canonical_media_url(ep["hashed_id"], account),
            )
            for ep in episodes
        ]
        series_title = (payload.get("series") or [{}])[0].get("title")
        jurisdiction_hint, _body = _jurisdiction_and_body(series_title)
        raise CalendarPageError(
            "This is a Wistia channel listing many meetings, not one specific meeting.",
            candidates,
            jurisdiction_hint=jurisdiction_hint,
        )

    @staticmethod
    async def _fetch_media_json(wistia_id: str) -> Optional[dict]:
        body = await WistiaAssetFinder._fetch(
            f"https://fast.wistia.com/embed/medias/{wistia_id}.json"
        )
        if not body:
            return None
        try:
            payload = json.loads(body)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    async def _fetch_channel_json(channel_id: str) -> Optional[dict]:
        body = await WistiaAssetFinder._fetch(
            f"https://fast.wistia.com/embed/channel/{channel_id}.json"
        )
        if not body:
            return None
        try:
            payload = json.loads(body)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    async def _fetch_captions(
        wistia_id: str,
    ) -> Tuple[Optional[List[dict]], Optional[str]]:
        """`(cues, language)` from the real public VTT endpoint, or
        `(None, None)` if this meeting has no captions -- a real, honest
        outcome (not every Wistia media has captions turned on), not a
        bug. Only "eng" is requested -- the one language confirmed live;
        see this module's docstring."""
        body = await WistiaAssetFinder._fetch(
            f"https://fast.wistia.com/embed/captions/{wistia_id}.vtt?language=eng"
        )
        if not body or not body.strip().upper().startswith("WEBVTT"):
            return None, None
        cues, _fallback_text = parse_captions_by_extension(f"{wistia_id}.vtt", body)
        if not cues:
            return None, None
        language = detect_language_from_texts(c.get("text") for c in cues) or "en"
        return cues, language

    @staticmethod
    async def _fetch(url: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with guarded_get(
                    session, url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Wistia fetch got HTTP %s for %s", response.status, url
                        )
                        return None
                    return await read_capped_text(response)
        except Exception:
            logger.warning("Wistia fetch failed for %s", url, exc_info=True)
            return None


def _canonical_media_url(wistia_id: str, account: Optional[str]) -> str:
    """`{account}.wistia.com/medias/{id}` when the account is known (the
    real, human-facing page -- confirmed live, HTTP 200), else
    `fast.wistia.net/embed/iframe/{id}` -- a real, always-constructible
    playable page needing no account name (confirmed live, HTTP 200;
    see this module's docstring)."""
    if account:
        return f"https://{account}.wistia.com/medias/{wistia_id}"
    return f"https://fast.wistia.net/embed/iframe/{wistia_id}"


def _best_public_asset(media: dict) -> Tuple[Optional[str], Optional[str]]:
    """`(video_url, video_format)` for the best real, public MP4 asset on
    a Wistia media JSON payload, or `(None, None)` if nothing public was
    found. Confirmed live: every asset's `url` ends `.bin`, not `.mp4` --
    a real content-type-correct (`video/mp4`), byte-range-capable
    (`Accept-Ranges: bytes`) file despite the extension, which is why
    `video_format="mp4"` is set explicitly here rather than derived from
    the URL's own suffix -- `app/static/player.js`'s plain `<video>`
    branch (anything that isn't `m3u8`/`youtube`/`vimeo`/`viebit`, see
    `models.py`'s own `video_format` comment) plays it fine either way.
    Prefers the highest-bitrate `hd_mp4_video` asset (a real meeting can
    run several hours; the "original" asset is a multi-GB master file
    not meant for direct browser playback)."""
    assets = media.get("assets") or []
    best = None
    best_bitrate = -1
    for asset in assets:
        if not asset.get("public"):
            continue
        if asset.get("type") not in ("hd_mp4_video", "md_mp4_video", "mp4_video"):
            continue
        url = asset.get("url")
        if not url:
            continue
        bitrate = asset.get("bitrate") or 0
        if bitrate > best_bitrate:
            best, best_bitrate = url, bitrate
    if best:
        return best, "mp4"
    return None, None


def list_channel_episodes(channel_payload: dict) -> List[dict]:
    """Every real episode on a Wistia channel JSON payload
    (`fast.wistia.com/embed/channel/{channelId}.json`), newest first --
    `[{"title", "hashed_id", "duration_seconds"}, ...]`. Confirmed live
    (Warrenton's `kcpy3xurof`) that `series[].sections[].episodes[]`
    already comes back newest-first with no per-episode date field of its
    own (the real date lives only inside the title, see
    `_date_from_title()`) -- shared here so both `resolve()`'s
    `CalendarPageError` candidates and a future breadth sweep read the
    identical real structure rather than two parsers that could drift
    apart, per CLAUDE.md's own reasoning for `should_cache_whole_audio()`.
    """
    episodes: List[dict] = []
    for series in channel_payload.get("series") or []:
        for section in series.get("sections") or []:
            for ep in section.get("episodes") or []:
                hashed_id = ep.get("episodeMediaHashedId") or ep.get("hashedId")
                title = ep.get("episodeTitle") or ep.get("name")
                if not hashed_id or not title:
                    continue
                episodes.append(
                    {
                        "title": title,
                        "hashed_id": hashed_id,
                        "duration_seconds": ep.get("durationInSeconds"),
                    }
                )
    return episodes


def filter_episodes_by_year(episodes: List[dict], year: str) -> List[dict]:
    """Episodes whose title names `year` (e.g. "2026") -- real, confirmed
    live necessary before picking a sweep target: Warrenton's own channel
    carries 165 episodes total across many years, but every 2019/2021
    hashed id checked live from RegionalWebTV's own archive pages (a
    DIFFERENT real page shape, see this module's docstring) came back
    dead. A channel's own older episodes are not independently confirmed
    either way, so the same caution applies here -- filter to the current
    year before calling `pick_episode_by_duration_rule()` for a real
    sweep, rather than picking from the whole history. Title-based (not a
    per-section year, which Wistia's own channel JSON sometimes but not
    always names, e.g. "2026 Meetings") since every episode's real date
    only ever lives in its title anyway (see `_date_from_title()`) --
    one real signal, not two that could disagree."""
    return [ep for ep in episodes if re.search(rf"\b{re.escape(year)}\b", ep["title"])]


def pick_episode_by_duration_rule(episodes: List[dict]) -> Optional[dict]:
    """Ryan's picking rule for a breadth sweep (docs/BREADTH_SWEEP_BRIEF.md,
    restated for this WO): prefer a meeting between 9 and 40 minutes; if
    none qualify, take the shortest available rather than the longest (a
    multi-hour meeting is real but a poor pick for a first sample -- see
    Warrenton's own channel, where every 2026 episode ran well over 40
    minutes and the shortest, ~61 minutes, was the honest pick). None for
    an empty list.

    Callers should pass an already current-year-filtered list (see
    `filter_episodes_by_year()`) for a real sweep -- an unfiltered channel
    can carry old, possibly-dead episodes that would otherwise look like
    a great short pick."""
    if not episodes:
        return None
    preferred = [
        ep
        for ep in episodes
        if ep.get("duration_seconds") is not None
        and _PREFERRED_MIN_SECONDS <= ep["duration_seconds"] <= _PREFERRED_MAX_SECONDS
    ]
    if preferred:
        return min(preferred, key=lambda ep: ep["duration_seconds"])
    timed = [ep for ep in episodes if ep.get("duration_seconds") is not None]
    if timed:
        return min(timed, key=lambda ep: ep["duration_seconds"])
    return episodes[0]
