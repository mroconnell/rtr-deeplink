import html as html_module
import os
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, find_platform_link, get_finder
from .media_scan import is_hls_url, media_type, scan_media_urls
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich
from ..utils.url_guard import guarded_get, read_capped_bytes, read_capped_text
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    detect_language_from_texts,
    parse_captions_by_extension,
)

_AGENDA_TEXT_RE = re.compile(r"agenda", re.IGNORECASE)

# Real page shape confirmed live 2026-08-13 across 5 real CRRMA board
# meeting URLs (crrma.org/information/meetings/board/{date}) -- see
# BACKLOG.md's "generic_fallback.py's YouTube-embed branch" entry. Only
# used as a last-resort backfill when the delegated finder's own
# metadata extraction came back completely empty (confirmed root cause:
# YouTube's yt-dlp call is blocked by anti-bot from Render's server IP,
# youtube.py's own documented gap, so `resolved.title` is None) --
# scoped to this exact shape, never assumed to generalize to other
# generic-fallback sites without their own confirmed example, same
# convention as every other adapter in this repo.
_TITLE_TAG_PIPE_RE = re.compile(r"^(.*?)\s*\|\s*(.+?)\s*$")
# Second confirmed real separator style, found live 2026-08-13 on
# Sebastopol, CA (cityofsebastopol.gov/events/{slug}/, a WordPress "The
# Events Calendar" page -- a different generic-fallback template family
# from CRRMA's <title>Org | Jurisdiction</title> shape above): "City
# Council Meeting January 6, 2026 - City of Sebastopol, California".
# Scoped to the LAST " - " in the title (an early hyphen inside a
# meeting name, e.g. "Special Session - Budget Item", shouldn't split
# there -- greedy group 1 backtracks from the end to find it) and
# requires the tail to contain a comma, since a real jurisdiction here
# reads "City[, State]"/"City of X, State" while a bare meeting-name
# segment wouldn't. Only two real separator styles confirmed so far --
# not a general last-resort splitter, just a second exact shape, same
# "verify before generalizing" convention as everywhere else in this
# file.
_TITLE_TAG_DASH_RE = re.compile(r"^(.*)\s+-\s+([^-]*,\s*[^-]+?)\s*$")
_URL_PATH_DATE_RE = re.compile(r"/(\d{4})-(\d{2})-(\d{2})(?:[/?]|$)")
# Real vendor-generated `title` attribute found live 2026-08-13 on
# Sacramento County's OnBase Agenda Online-family agenda link ("View
# Agenda Packet for BOARD OF SUPERVISORS BOARD OF SUPERVISORS MEETING on
# 8/11/2026 9:30:00 AM") -- see BACKLOG.md's "Sacramento County, CA's own
# agenda site" entry. Only used to backfill title/date, never
# jurisdiction (the body/type text here never names the county itself,
# confirmed on this one example -- "Sacramento County" only appears in
# the page's generic, non-per-meeting <title> tag). The apparent
# duplication ("BOARD OF SUPERVISORS BOARD OF SUPERVISORS MEETING") is
# left as-is rather than deduped -- with only one real example in hand,
# it's plausibly a real "{meeting type} {body name} MEETING" template
# that happens to coincide here, not a confirmed universal artifact worth
# guessing a dedup rule for.
_AGENDA_LINK_TITLE_RE = re.compile(
    r"View Agenda Packet for\s+(.+?)\s+on\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.IGNORECASE
)
# The notice-of-meeting body paragraph names the governing body more
# specifically ("CRRMA Board of Directors") than the bare org name in
# <title> ("Camino Real Regional Mobility Authority") -- user's own
# stated preference, 2026-08-13: "I'd expect it to have CRRMA in there
# somewhere."
_BOARD_OF_DIRECTORS_RE = re.compile(r"\b([A-Z]{2,8}\s+Board\s+of\s+Directors)\b")

# --- YouTube discovery beyond youtube.py's own URL-shaped regex. These
# live here (private), NOT in youtube.py's _VIDEO_ID_RE, so the 16
# dedicated adapters that depend on that regex keep their exact behavior.
#
# youtube-nocookie.com is YouTube's real privacy-enhanced embed domain --
# the same 11-char id space, just a different host _VIDEO_ID_RE doesn't
# know. No government page with this shape has been confirmed yet
# (2026-08-14) -- included because it's a pure URL-shape variant of an
# already-confirmed pattern, not a new guess; upgrade this comment when a
# real example turns up.
_NOCOOKIE_EMBED_RE = re.compile(r"youtube-nocookie\.com/embed/([A-Za-z0-9_-]{11})")
# Bare JS assignment shape, confirmed live 2026-08-13 on Tarrant County's
# Agenda Management System (agendamgmtprod.tarrantcountytx.gov):
# `const videoId = 'Awrb74sMXyM';` with no youtube.com URL around it at
# all -- the id is handed to the IFrame Player API loader, whose
# `<script src="https://www.youtube.com/iframe_api">` tag is the
# corroboration signal this match is gated on (see
# _find_youtube_video_id) so a random 11-char string on a page that
# never loads the YouTube player can't false-positive.
_BARE_VIDEO_ID_RE = re.compile(r"\bvideoId\s*=\s*['\"]([A-Za-z0-9_-]{11})['\"]")
_IFRAME_API_MARKER = "youtube.com/iframe_api"

# Machine-readable per-meeting date meta tag, confirmed live 2026-08-13 on
# Seattle Channel (<meta name="video_date" content="2026-08-11">) -- part
# of the WCAG/accessibility-markup family of signals BACKLOG.md's
# feed-cities entry catalogued from real government pages.
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTHS_FULL = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# Textual date inside a heading, confirmed live 2026-08-13 on Tarrant
# County's `<h4>TUESDAY, AUGUST 19, 2025 - 10:00 AM</h4>` (an
# address-only sibling <h4> precedes it -- no month name, so this
# correctly skips it).
_HEADING_DATE_RE = re.compile(
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    rf"({'|'.join(_MONTHS_FULL)})\s+(\d{{1,2}}),?\s+(\d{{4}})",
    re.IGNORECASE,
)
# Trailing textual date in a URL slug, e.g. Wayne County MI's
# ".../Wayne-County-Commission-January-8-2026" and Sebastopol's
# "/events/city-council-meeting-january-6-2026/" -- both real confirmed
# shapes (2026-08-13/14).
_SLUG_DATE_RE = re.compile(
    rf"({'|'.join(_MONTHS_FULL)})-(\d{{1,2}})-(\d{{4}})/?$", re.IGNORECASE
)

# --- Video pointer (2026-08-14 rebuild, per the user's explicit call:
# "the pointer where the video lives would be a GREAT outcome for the
# fallback page"). Two confidence tiers with distinct UI copy:
#
# Curated tier: a Vimeo video-page link -- numeric video id required
# (optionally with a privacy hash), which structurally excludes
# channel/user/home links ("vimeo.com/cityname" footer links, the same
# false-positive class youtube.py's own regex avoids). Confirmed real on
# Sebastopol CA (vimeo.com/1152708575/db9859a2aa) and Chicago ELMS
# (vimeo.com/showcase/... -- also numeric-id'd); vimeo is the only
# curated host until another unsupported video host shows a real example.
_VIMEO_VIDEO_LINK_RE = re.compile(
    r"https?://(?:www\.)?vimeo\.com/(?:showcase/[^\s\"'<>]+|\d+(?:/[0-9a-f]+)?(?:\?[^\s\"'<>]*)?)",
    re.IGNORECASE,
)
# Loose tier: an <a> whose visible text is video-shaped. Anchored
# whole-text match (not substring) so a sentence merely mentioning video
# doesn't fire; "Video" is Wayne County MI's real link text, the shape
# that motivated this tier. The user explicitly accepted wrong-ish
# pointers here -- the UI copy says "proceed with caution."
_VIDEO_TEXT_RE = re.compile(
    r"^(?:watch(?:\s+(?:the\s+)?(?:video|meeting|recording|live\s*stream))?"
    r"|(?:view|meeting|full)?\s*video(?:\s+recording)?"
    r"|live\s*stream(?:/recording)?|recording)$",
    re.IGNORECASE,
)
# Iframes whose src host serves page furniture, not video -- the junk
# blocklist for the loose iframe tier. Each entry seen on a real capture
# in tests/fixtures/generic_fallback/ (GTM on OCFL's page, `javascript:`
# on PBC's) or ubiquitous enough to need no citation (analytics,
# recaptcha, social embeds).
_IFRAME_JUNK_HOSTS = (
    "googletagmanager.com",
    "google-analytics.com",
    "doubleclick.net",
    "recaptcha.net",
    "google.com/recaptcha",
    "facebook.com",
    "twitter.com",
    "platform.twitter.com",
    "youtube.com",  # youtube iframes are tier-1 territory, never a pointer
)

# --- Headless-browser escalation (2026-08-14 rebuild, Phase 5).
# Env-gated OFF by default: playwright-on-Render has never been confirmed
# working in production (two real 2026-08-09 build incidents -- see
# render.yaml:16-40 and headless_browser.py's own docstring). Flip
# GENERIC_FALLBACK_HEADLESS=1 only after a real prod verification of the
# headless build (e.g. a successful LIMS/SLC prod resolve). The worker
# never sets it -- playwright is deliberately absent from
# worker/requirements.txt.
_HEADLESS_ESCALATION_ENV = "GENERIC_FALLBACK_HEADLESS"
# Statuses a WAF/bot-gate answers with -- 403 is Wayne County MI's real
# confirmed Akamai response (tests/fixtures/generic_fallback/
# wayne_akamai_403.html); the rest are the standard block-status family.
_BLOCK_STATUSES = {401, 403, 429, 503}
# Challenge-page body markers for blocks served as a 200 -- each tied to a
# real observed body: "access denied"/"errors.edgesuite.net" are literal
# strings in the captured Akamai body; "just a moment" is Cloudflare's
# interstitial, the exact page LIMS/SLC's always-headless fetch was built
# against (headless_browser.py's docstring). Only checked on small bodies
# (a real page mentioning "access denied" in prose is fine).
_CHALLENGE_MARKERS = ("errors.edgesuite.net", "access denied", "just a moment")
_CHALLENGE_BODY_MAX_BYTES = 2048
# Empty-evidence retry gate: the resolve found literally nothing AND the
# page's visible text is near-empty -- the client-rendered-shell shape.
# Threshold tuned against the real Tucson Hyland capture (153 chars of
# visible text). Deliberately does NOT catch PBC's SharePoint shell (6KB
# of real nav/chrome text, measured 2026-08-14): firing on every
# evidence-less page that still has real text would make an enabled flag
# pay a >=4s browser fetch on ordinary no-video pages -- PBC stays a
# documented gap, see BACKLOG.md.
_EMPTY_SHELL_TEXT_MAX_CHARS = 500


def _headless_escalation_enabled() -> bool:
    # Read at call time, not import time, so the flag can be set/unset
    # without a process restart being silently required in tests.
    return os.environ.get(_HEADLESS_ESCALATION_ENV, "") == "1"


_BEST_EFFORT_VIDEO_WARNING = (
    "This city isn't officially supported yet, so we're trying our best — we think we found the "
    "video below. Deep-linking to a specific moment might work here, or it might not — feel free "
    'to try the "Go to time" / "Share video at" tools, but if a link doesn\'t land right, going '
    "back to the original source is the safer bet."
)
_NO_VIDEO_FOUND_WARNING = (
    "This city isn't officially supported yet, so we're trying our best — but we couldn't find a "
    "video on this page automatically. Try going straight to the original source instead."
)
_VIDEO_POINTER_WARNING = (
    "This city isn't officially supported yet, so we're trying our best — we found what looks "
    "like the video, but we can't play it here yet. The link on this page goes to the original."
)
_NO_TRANSCRIPT_WARNING = (
    "We didn't automatically find a transcript here — this city isn't officially supported yet — "
    "but you can try to request one from the audio instead."
)


class GenericFallbackAssetFinder(AssetFinder):
    """Best-effort handling for any URL `detect_platform()` doesn't
    recognize -- registered under `platform_name = "unknown"`, the exact
    string `detect_platform()` already returns for anything unmatched, so
    `get_finder("unknown")` finds this instead of every unrecognized URL
    raising `UnsupportedPlatformError` with zero attempt made. Built
    2026-08-09 directly from the user's own request: "try our best"
    instead of a flat "we don't support this yet."

    Deliberately narrow in what it attempts, in priority order:
    1. An embedded/linked YouTube video (`<iframe src="youtube.com/
       embed/...">`, or a plain `youtube.com/watch?v=...`/`youtu.be/...`
       link anywhere in the page) -- delegates to `YouTubeAssetFinder`
       for real video + real captions, the best possible outcome here
       since a huge share of small-city sites just embed a YouTube
       video with no dedicated platform at all.
    2. A link to any OTHER platform this app already fully supports --
       `_try_delegate_to_known_platform()` scans every `<a href>`/
       `<iframe src>`/`<video src>`/`<source src>` on the page through
       the same `detect_platform()` every URL gets classified by, and
       delegates to that adapter's real `resolve()` if one matches.
       Confirmed live 2026-08-10: Austin, TX's own council meeting pages
       (`austintexas.gov/council/{date}-reg`) don't embed video at all --
       they link out to `austintx.swagit.com/play/{id}/0/` as a plain
       `<a href>`, which `SwagitAssetFinder` already resolves correctly
       on its own. No reason to guess at a generic media-URL scan when a
       real, already-tested adapter is one link away.
    3. A direct playable media URL (`.m3u8`/`.mp4`) found by
       `media_scan.scan_media_urls()` -- the same generic scanner
       Granicus/Swagit already use, reused here rather than
       reimplemented. A caption-shaped URL (`.vtt`/`.srt`/etc.) found in
       the same scan is fetched and parsed via the same
       `parse_captions_by_extension()` dispatch every real adapter uses.
    4. Nothing found at all -- returns a real, honest "we tried and
       couldn't find anything" message, a genuinely different (more
       informative) outcome than today's blunt "we don't support this
       platform yet," which never attempted anything.

    5. A plain link to an agenda document -- any <a> tag whose visible
       text or href contains "agenda" (case-insensitive), preferring one
       that looks like a PDF if more than one matches (per the user's
       real experience triaging many small-city sites, an agenda is very
       often a standalone PDF download rather than part of the page
       itself). Deliberately NOT attempted: structured agenda-ITEM
       detection (per-topic entries with real timestamps). Every other
       adapter's item-level agenda parsing is tied to that platform's own
       known page structure (Granicus's AgendaViewer.php, CivicClerk's
       eventBookmarks, ...) -- there's no reliable generic pattern to
       reuse the way there is for media URLs or a single link, and
       guessing badly at *items* would be worse than them just being
       absent. A found agenda link goes into `ResolvedMeeting.agenda_link`
       (a single raw URL) rather than forced into `agenda_items`, since
       that field implies real per-item timestamps this doesn't have --
       the user's own framing: "they don't need to be clickable
       timestamps for this fallback mode." The frontend renders it as a
       plain "we think we found an agenda here: <link>" line.

    `best_effort=True` on every result this adapter produces (see
    `ResolvedMeeting.best_effort`'s own docstring for why `platform ==
    "unknown"` alone isn't a reliable enough signal for the frontend to
    key off of) drives a dedicated, deliberately tentative UI on the
    meeting page (built 2026-08-10, live-tested against real
    never-before-seen cities -- see BACKLOG_DONE.md): a full-width "we're
    trying our best" banner, plain (non-alarmed) "we think the video/
    agenda is here: <link>" lines instead of the video/agenda_link
    fields being silently invisible or looking like a real warning, and
    a manual timestamp-entry box in place of the live-tracking playhead
    reader other platforms get (deep-linking reliability isn't confirmed
    here the way it is on a supported platform, so there's no adapter-
    driven "current time" to honestly display).

    Real, deliberate architecture note: this makes the `unsupported_
    platform` error branch in `app/main.py`'s `/api/resolve` (and its
    matching `unsupported_platform` outcome bucket in `app/db/
    outcomes.py`) effectively unreachable going forward -- every URL now
    resolves to *something*, even if that something is "no video found."
    Left in place rather than removed (a safe, conservative choice, not
    dead-code bloat) since `get_finder()` could still raise for a
    genuinely different reason in the future.
    """

    platform_name = "unknown"

    def __init__(self):
        self.headers = {
            # A modern UA, not the Chrome/91 (2021) string every other
            # adapter in this repo still uses -- confirmed live 2026-08-13
            # that at least one real WAF (cityofsebastopol.gov's) 403s the
            # old string while a current Chrome UA gets a clean 200 for
            # the identical request. Scoped to just this adapter, not
            # copied to the other 10 files still using Chrome/91: those
            # target known vendor platforms already confirmed working
            # with it, and changing an already-working request header
            # sitewide needs its own per-platform verification, not a
            # drive-by bundled into this fix -- see BACKLOG.md.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        html, escalated = await self._fetch_page(url)
        if html is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "We don't recognize this website's platform, and couldn't even load the page "
                    "to look for a video."
                ],
                best_effort=True,
            )

        resolved = await self._resolve_from_html(url, html)

        # Empty-evidence retry (escalation trigger c): the plain fetch
        # succeeded but produced literally nothing AND the page reads as a
        # client-rendered shell (Tucson Hyland's confirmed shape). One
        # browser attempt per resolve, total -- never after an already-
        # escalated fetch.
        if (
            not escalated
            and _headless_escalation_enabled()
            and self._is_empty_evidence(resolved)
            and self._looks_like_empty_shell(html)
        ):
            rendered = await self._try_browser_fetch(url)
            if rendered is not None:
                re_resolved = await self._resolve_from_html(url, rendered)
                if not self._is_empty_evidence(re_resolved):
                    return re_resolved
        return resolved

    async def _resolve_from_html(self, url: str, html: str) -> ResolvedMeeting:
        agenda_link, agenda_link_title = self._find_agenda_link(html, url)

        # Video tier 1+2: an embedded YouTube video, in any of the
        # confirmed shapes (URL-shaped id, HTML-escaped watch URL,
        # nocookie embed, or Tarrant's bare corroborated JS assignment).
        youtube_video_id = self._find_youtube_video_id(html)
        if youtube_video_id:
            resolved = await YouTubeAssetFinder.resolve_video_id(
                youtube_video_id, source_url=url
            )
            resolved.video_warnings = [
                _BEST_EFFORT_VIDEO_WARNING,
                *resolved.video_warnings,
            ]
            resolved.agenda_link = agenda_link
            # YouTubeAssetFinder.resolve_video_id() always returns
            # platform="youtube" (its own identity, unchanged, regardless
            # of caller) -- best_effort is the frontend's real signal for
            # "this came from the fallback," since checking platform ==
            # "unknown" alone would silently miss this, the *most* common
            # real outcome (a small city just embeds a YouTube video).
            resolved.best_effort = True
            self._backfill_metadata_from_page(resolved, html, url, agenda_link_title)
            return resolved

        # Video tier 3: a link out to a platform with a real dedicated
        # adapter -- that adapter's own resolve() is strictly better than
        # anything this generic scan could do.
        delegated = await self._try_delegate_to_known_platform(html, url)
        if delegated:
            delegated.agenda_link = delegated.agenda_link or agenda_link
            return delegated

        # Video tier 4: a directly playable media URL found by the shared
        # generic scan.
        media_urls = scan_media_urls(html, url)
        video_url, video_format = self._pick_video_url(media_urls)

        # Video tier 5: nothing playable -- point at where the video
        # probably lives instead of showing a bare "no video found."
        video_link, video_link_recognized = (None, False)
        if not video_url:
            video_link, video_link_recognized = self._find_video_pointer(html, url)

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        for caption_url in self._collect_caption_candidates(html, media_urls, url):
            cues = await self._try_fetch_caption(caption_url)
            if cues:
                segments = [TranscriptSegment(**c) for c in cues]
                transcript_language = detect_language_from_texts(
                    c["text"] for c in cues
                )
                break

        transcript_warnings = [] if segments else [_NO_TRANSCRIPT_WARNING]

        if video_url:
            video_warning = _BEST_EFFORT_VIDEO_WARNING
        elif video_link:
            video_warning = _VIDEO_POINTER_WARNING
        else:
            video_warning = _NO_VIDEO_FOUND_WARNING

        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            video_url=video_url,
            video_format=video_format,
            video_link=video_link,
            video_link_recognized=video_link_recognized,
            segments=segments,
            transcript_language=transcript_language,
            video_warnings=[video_warning],
            transcript_warnings=transcript_warnings,
            agenda_link=agenda_link,
            best_effort=True,
        )
        self._backfill_metadata_from_page(resolved, html, url, agenda_link_title)
        return resolved

    @staticmethod
    def _find_video_pointer(html: str, page_url: str) -> Tuple[Optional[str], bool]:
        """Where the video probably lives, when nothing playable was
        found -- returns (url, recognized). Tiers, in confidence order
        (see the module-level pointer regexes for the real examples each
        is built on):

        1. A link to a curated known video host (Vimeo video/showcase
           pages) -> recognized=True.
        2. An <a> whose visible text is video-shaped ("Video",
           "Watch...", "Live Stream/Recording") -> recognized=False.
        3. An iframe to a third-party host that isn't page furniture
           (analytics/recaptcha/social) -> recognized=False.

        The user explicitly accepted loose matches here (2026-08-14):
        the UI renders recognized=False pointers with "we don't
        recognize {host} as a supported video host, so proceed with
        caution" -- a wrong-ish pointer behind tentative copy beats a
        bare "[No video found]".
        """
        match = _VIMEO_VIDEO_LINK_RE.search(html)
        if match:
            return html_module.unescape(match.group(0)), True

        soup = BeautifulSoup(html, "html.parser")
        page_host = urlparse(page_url).netloc.lower()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if (
                not href
                or href.startswith("#")
                or href.lower().startswith("javascript:")
            ):
                continue
            if _VIDEO_TEXT_RE.match(a.get_text(" ", strip=True)):
                return urljoin(page_url, href), False
        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"].strip()
            if not src.lower().startswith(("http://", "https://", "//")):
                continue
            candidate = urljoin(page_url, src)
            host = urlparse(candidate).netloc.lower()
            if not host or host == page_host:
                continue
            if any(junk in candidate.lower() for junk in _IFRAME_JUNK_HOSTS):
                continue
            return candidate, False
        return None, False

    async def _fetch_page(self, url: str) -> Tuple[Optional[str], bool]:
        """Fetch the page; returns `(html, escalated)`. `html is None`
        means "couldn't load the page at all."

        Escalation triggers a+b (env-gated OFF by default -- see the
        module-level _HEADLESS_ESCALATION_ENV block): a block-family
        status (Wayne County MI's real Akamai 403), or a 200 whose small
        body is a challenge interstitial. When the flag is off, or the
        browser is unavailable/fails, a blocked fetch degrades to exactly
        the pre-escalation behavior: None, and the honest "couldn't even
        load the page" message. A challenge body is never handed to the
        extraction layers as if it were the real page.
        """
        status: Optional[int] = None
        body: Optional[str] = None
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                # guarded_get, not a bare session.get(allow_redirects=True)
                # -- re-validates the destination on every redirect hop
                # (a permitted host can 302 to a private one) rather than
                # trusting aiohttp's own follow. See url_guard.py's module
                # docstring / AUDIT_2026-08-14.md finding #2. A blocked
                # destination degrades to the same honest "couldn't even
                # load the page" outcome as any other fetch failure below,
                # same as an unrelated timeout/connection error would.
                async with guarded_get(
                    session, url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    status = response.status
                    body = await read_capped_text(response)
        except Exception:
            pass

        blocked = status in _BLOCK_STATUSES or (
            status == 200
            and body is not None
            and len(body) <= _CHALLENGE_BODY_MAX_BYTES
            and any(marker in body.lower() for marker in _CHALLENGE_MARKERS)
        )
        if status is not None and 200 <= status < 300 and not blocked:
            return body, False

        if blocked and _headless_escalation_enabled():
            rendered = await self._try_browser_fetch(url)
            if rendered is not None:
                return rendered, True
        return None, False

    @staticmethod
    async def _try_browser_fetch(url: str) -> Optional[str]:
        """One real-Chromium fetch, degrading to None on ANY failure --
        including HeadlessBrowserUnavailable, which no other caller in
        this repo catches (LIMS/SLC let it propagate because their
        hostnames are KNOWN to need a browser; this escalation is
        speculative, so a missing browser must never turn a normal
        fallback resolve into a crash). Imported lazily so the worker
        (which deliberately omits playwright) never touches the module
        unless the flag is actually on."""
        try:
            from .headless_browser import fetch_via_browser

            return await fetch_via_browser(url)
        except Exception:
            return None

    @staticmethod
    def _is_empty_evidence(resolved: ResolvedMeeting) -> bool:
        """Whether a resolve found nothing worth keeping -- the
        empty-evidence escalation gate. `agenda_link` is deliberately NOT
        counted: the real Tucson Hyland shell (the page this trigger was
        built for) carries an "Agenda" NAV link that `_find_agenda_link`
        best-effort-matches to the site root -- the exact junk-link
        outcome BACKLOG.md already documented from prod -- and counting
        it would veto escalation on precisely the page that needs it."""
        return not any(
            (
                resolved.video_url,
                resolved.video_link,
                resolved.title,
                resolved.segments,
            )
        )

    @staticmethod
    def _looks_like_empty_shell(html: str) -> bool:
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        return len(text) <= _EMPTY_SHELL_TEXT_MAX_CHARS

    @staticmethod
    def _find_youtube_video_id(html: str) -> Optional[str]:
        """Every confirmed way a real government page embeds a YouTube
        video, tried in confidence order:

        1. A URL-shaped id anywhere in the raw HTML -- youtube.py's own
           regex, unchanged.
        2. The same, over an entity-unescaped copy -- a watch URL written
           as `watch?a=1&amp;v={id}` in raw HTML never matches the plain
           regex, whose `(?:.*&)?v=` needs a literal `&` (no confirmed
           government example yet; a pure escaping variant of an
           already-confirmed shape, not a new guess).
        3. A youtube-nocookie.com embed (same id space, different host --
           see _NOCOOKIE_EMBED_RE's comment).
        4. Tarrant County's bare `videoId = '{id}'` JS assignment --
           gated on the page actually loading the IFrame Player API
           (_IFRAME_API_MARKER) AND every such assignment agreeing on a
           single distinct id; ambiguity means skip, since guessing
           between two ids risks attaching the wrong meeting's video,
           which is worse than none.
        """
        video_id = YouTubeAssetFinder.extract_video_id(html)
        if video_id:
            return video_id
        video_id = YouTubeAssetFinder.extract_video_id(html_module.unescape(html))
        if video_id:
            return video_id
        match = _NOCOOKIE_EMBED_RE.search(html)
        if match:
            return match.group(1)
        if _IFRAME_API_MARKER in html:
            ids = set(_BARE_VIDEO_ID_RE.findall(html))
            if len(ids) == 1:
                return ids.pop()
        return None

    @staticmethod
    def _collect_caption_candidates(
        html: str, media_urls: List[str], page_url: str
    ) -> List[str]:
        """Caption URLs to try, in confidence order, deduped, capped at 3
        (each is a real network fetch; a page with many caption-shaped
        links shouldn't turn one resolve into a crawl):

        1. <track> elements -- the actual HTML5 captions standard,
           confirmed present and identically shaped on three real
           government pages (BACKLOG.md's accessibility-markup findings).
           kind="captions"/"subtitles"/absent all count (subtitles is the
           spec default when kind is omitted).
        2. A plain <a href> whose path ends in a caption extension --
           confirmed live 2026-08-13 on Seattle Channel ("Download a SRT
           caption file <a href=...>here</a>"), a RELATIVE path resolved
           against the page URL.
        3. Subtitle-typed URLs from the generic media scan (which now
           also surfaces JW-config `tracks: {file: ...}` entries -- on
           Seattle that's the same .srt as tier 2, deduped away).
        """
        candidates: List[str] = []
        soup = BeautifulSoup(html, "html.parser")
        for track in soup.find_all("track", src=True):
            kind = (track.get("kind") or "subtitles").lower()
            if kind in ("captions", "subtitles"):
                candidates.append(urljoin(page_url, track["src"].strip()))
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if (
                not href
                or href.startswith("#")
                or href.lower().startswith("javascript:")
            ):
                continue
            candidate = urljoin(page_url, href)
            if media_type(candidate) == "subtitle":
                candidates.append(candidate)
        candidates.extend(u for u in media_urls if media_type(u) == "subtitle")

        seen = set()
        unique = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique[:3]

    @staticmethod
    def _backfill_metadata_from_page(
        resolved: ResolvedMeeting,
        html: str,
        url: str,
        agenda_link_title: Optional[str] = None,
    ) -> None:
        """Last-resort title/jurisdiction/date fill-in for a still-empty
        `resolved.title` -- see the module-level regex comments above for
        the real confirmed page shape this targets. Deliberately only
        fires on a still-empty title, so it can never clobber a real
        title/jurisdiction a delegated finder (e.g. YouTube, when yt-dlp
        isn't blocked) already found.

        `resolved.jurisdiction` is intentionally stored as raw text
        ("El Paso, Texas", not "El Paso, TX") -- `normalize_state_suffix()`
        already runs on every ingest server-side
        (`archive/db/crud.py`'s `_find_or_create_page()`), so abbreviating
        it here too would just be redundant, not incorrect.
        """
        date_match = _URL_PATH_DATE_RE.search(url)
        if date_match and not resolved.date:
            resolved.date = (
                f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            )

        soup = BeautifulSoup(html, "html.parser")
        board_match = _BOARD_OF_DIRECTORS_RE.search(soup.get_text(" ", strip=True))

        org_name, jurisdiction = None, None
        title_tag = soup.title.get_text(strip=True) if soup.title else None
        if title_tag:
            pipe_match = _TITLE_TAG_PIPE_RE.match(title_tag)
            if pipe_match:
                org_name, jurisdiction = pipe_match.group(1), pipe_match.group(2)
            else:
                dash_match = _TITLE_TAG_DASH_RE.match(title_tag)
                if dash_match:
                    org_name, jurisdiction = dash_match.group(1), dash_match.group(2)

        if not resolved.title:
            # Prefer the notice-block's own body-name phrase over the bare
            # <title>-derived org name when both are available -- user's
            # own stated preference, see the _BOARD_OF_DIRECTORS_RE
            # comment above.
            resolved.title = board_match.group(1) if board_match else org_name

        # Jurisdiction, unlike title, always prefers the page's own value
        # over whatever's already on `resolved` -- real bug found live
        # 2026-08-13 confirmed via a re-resolved CRRMA page
        # (/m/meeting-732f78): when yt-dlp isn't blocked,
        # `YouTubeAssetFinder.resolve_video_id()` unconditionally sets
        # `jurisdiction=info.get("uploader")` (youtube.py), a channel
        # name ("Camino Real Regional Mobility Authority"), not a real
        # jurisdiction -- the exact same class of bug already fixed for
        # PrimeGov (primegov.py's own resolve() unconditionally overrides
        # YouTube's uploader for the same reason). Since this branch's
        # only possible delegate is YouTubeAssetFinder, there's no other
        # legitimate source `resolved.jurisdiction` could hold here.
        if not jurisdiction and not resolved.jurisdiction:
            # Neither confirmed <title>-tag shape matched (both are
            # scoped to one confirmed real page family each -- see the
            # module-level regex comments) and no delegate already set
            # anything. Try the shared chain before leaving this page
            # blank -- generic_fallback never called into this module at
            # all before (2026-08-15 audit), despite being one of the two
            # highest-volume sources of blank jurisdictions.
            jurisdiction = jurisdiction_enrich.extract_jurisdiction_chain(
                page_text=soup.get_text(" ", strip=True), html=html, url=url
            )

        if jurisdiction:
            resolved.jurisdiction = jurisdiction

        # --- Broader title fallbacks (2026-08-14 rebuild), each tried
        # only while title is still empty, strictly after the
        # confirmed-shape <title>-tag extractors above:
        if not resolved.title:
            # og:title / twitter:title -- confirmed real and per-meeting on
            # Wayne County MI ('<meta property="og:title" content="Wayne
            # County Commission - January 8, 2026">'). A site whose
            # og:title is generic boilerplate just re-states its <title>
            # tag, which already failed to match above -- same
            # best-effort risk profile as every other extractor here.
            for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
                meta = soup.find("meta", attrs=attrs)
                if meta and meta.get("content", "").strip():
                    resolved.title = meta["content"].strip()
                    break
        if not resolved.title:
            # h1 assembly -- confirmed live 2026-08-13 on Tarrant County,
            # whose real header is TWO sibling <h1>s ("Tarrant County" +
            # "Commissioners Court"). Joined in document order; gated to
            # at most 3 h1s total, since a page using many h1s is using
            # them as section styling, not identity.
            h1_texts = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
            h1_texts = [t for t in h1_texts if t]
            if 0 < len(h1_texts) <= 3:
                assembled = " ".join(dict.fromkeys(h1_texts))
                if assembled and len(assembled) <= 120:
                    resolved.title = assembled
        # --- Broader date fallbacks (2026-08-14 rebuild), same
        # only-fill-empty rule:
        if not resolved.date:
            # <meta name="video_date" content="YYYY-MM-DD"> -- Seattle
            # Channel's real machine-readable per-meeting date.
            meta = soup.find("meta", attrs={"name": "video_date"})
            if meta and _ISO_DATE_RE.match(meta.get("content", "").strip()):
                resolved.date = meta["content"].strip()[:10]
        if not resolved.date:
            # <time datetime="..."> -- semantic markup confirmed real on
            # Portland.gov (BACKLOG.md's accessibility-markup findings);
            # first occurrence, ISO date prefix only.
            time_tag = soup.find("time", datetime=True)
            if time_tag:
                iso = _ISO_DATE_RE.match(time_tag["datetime"].strip())
                if iso:
                    resolved.date = iso.group(0)
        if not resolved.date:
            # A textual date inside a prominent heading -- Tarrant's
            # "<h4>TUESDAY, AUGUST 19, 2025 - 10:00 AM</h4>". First
            # month-named heading in document order wins.
            for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
                match = _HEADING_DATE_RE.search(heading.get_text(" ", strip=True))
                if match:
                    month = [m.lower() for m in _MONTHS_FULL].index(
                        match.group(1).lower()
                    ) + 1
                    resolved.date = f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"
                    break

        # Title/date backfill from the agenda link's own `title`
        # attribute -- see _AGENDA_LINK_TITLE_RE's module-level comment.
        # Only fires when the field is still empty, so it can never
        # clobber a real title/date any path above already found.
        if agenda_link_title:
            agenda_match = _AGENDA_LINK_TITLE_RE.search(agenda_link_title)
            if agenda_match:
                body_text, month, day, year = agenda_match.groups()
                if not resolved.title:
                    resolved.title = (
                        body_text.title() if body_text.isupper() else body_text
                    )
                if not resolved.date:
                    resolved.date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        # --- True last resorts: the URL slug itself (2026-08-14 rebuild).
        # Confirmed real slug shapes: Wayne County MI
        # ("Wayne-County-Commission-January-8-2026") and Sebastopol
        # ("city-council-meeting-january-6-2026").
        if not resolved.title:
            # Requires >= 2 ALPHABETIC hyphen-separated words, so
            # "ViewMeeting"/bare-numeric-id/date-only paths (e.g.
            # "council-2026-01-01", which would humanize into junk) never
            # fire.
            slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            words = [w for w in slug.split("-") if w]
            if len(words) >= 2 and sum(1 for w in words if w.isalpha()) >= 2:
                resolved.title = " ".join(words)
        if not resolved.date:
            match = _SLUG_DATE_RE.search(urlparse(url).path)
            if match:
                month = [m.lower() for m in _MONTHS_FULL].index(
                    match.group(1).lower()
                ) + 1
                resolved.date = (
                    f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"
                )

    @staticmethod
    async def _try_delegate_to_known_platform(
        html: str, page_url: str
    ) -> Optional[ResolvedMeeting]:
        """Uses `base.find_platform_link()` to look for a link to a
        platform this app already fully supports, and delegates to that
        adapter's own real resolve() -- e.g. a city page that just links
        out to its Swagit-hosted video as a plain <a href> rather than
        embedding it, confirmed live 2026-08-10 (Austin, TX: austintexas.
        gov/council/{date}-reg links to austintx.swagit.com/play/{id}/0/,
        a real, already-correctly-working SwagitAssetFinder target -- no
        reason to guess at a generic media-URL scan when a real, tested
        adapter is right there).

        Excludes "youtube" -- already handled above by
        `YouTubeAssetFinder.extract_video_id()`, a tighter, video-ID-
        validated check; see `find_platform_link()`'s own docstring for
        why its broader `detect_platform()`-based match would otherwise
        false-positive on a bare channel/user link.

        Any failure (a bad match that doesn't actually resolve, a
        CalendarPageError from e.g. a Legistar calendar link, network
        errors) is swallowed and treated as "no delegation possible" --
        this is a bonus attempt on top of the existing fallback logic, not
        allowed to replace an honest "found nothing" with a crash.
        """
        match = find_platform_link(html, page_url, exclude=frozenset({"youtube"}))
        if not match:
            return None
        candidate, platform = match
        try:
            finder = get_finder(platform)
            resolved = await finder.resolve(candidate)
        except Exception:
            # Covers CalendarPageError (e.g. a Legistar calendar link
            # rather than one specific meeting) same as any other resolve
            # failure -- see this method's own docstring.
            return None
        resolved.source_url = page_url
        resolved.video_warnings = [_BEST_EFFORT_VIDEO_WARNING, *resolved.video_warnings]
        resolved.best_effort = True
        return resolved

    @staticmethod
    def _find_agenda_link(
        html: str, page_url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Best-effort: a single <a> tag whose visible text or href
        contains "agenda" (case-insensitive). Doesn't attempt to extract
        agenda *items* -- see class docstring. Prefers a PDF-looking href
        (the common real-world shape) over an HTML page, since a PDF is
        the more specific, less-likely-to-be-a-false-positive signal.

        Returns `(url, title_attr)` -- the winning `<a>` tag's own `title`
        attribute (or None) is handed back alongside the link so callers
        can mine it for a title/date backfill (see
        `_AGENDA_LINK_TITLE_RE`) without a second pass over the page."""
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if (
                not href
                or href.startswith("#")
                or href.lower().startswith("javascript:")
            ):
                continue
            text = a.get_text(" ", strip=True)
            if _AGENDA_TEXT_RE.search(text) or _AGENDA_TEXT_RE.search(href):
                candidates.append((urljoin(page_url, href), a.get("title")))
        if not candidates:
            return None, None
        for candidate, title_attr in candidates:
            if candidate.lower().split("?")[0].endswith(".pdf"):
                return candidate, title_attr
        return candidates[0]

    @staticmethod
    def _pick_video_url(media_urls: List[str]) -> Tuple[Optional[str], Optional[str]]:
        for candidate in media_urls:
            if media_type(candidate) == "video" and is_hls_url(candidate):
                return candidate, "m3u8"
        for candidate in media_urls:
            if media_type(candidate) == "video":
                return candidate, "mp4"
        return None, None

    @staticmethod
    async def _try_fetch_caption(caption_url: str):
        try:
            async with aiohttp.ClientSession() as session:
                # Same SSRF guard as _fetch_page above -- caption_url comes
                # from scanning the fetched page's own markup, so it's just
                # as caller-influenced as the entry URL.
                async with guarded_get(
                    session, caption_url, timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        return None
                    raw = await read_capped_bytes(response)
        except Exception:
            return None
        content = decode_vtt_bytes(raw)
        cues, _fallback_text = parse_captions_by_extension(caption_url, content)
        return cues


def scan_page_for_video_evidence(
    html: str, page_url: str
) -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
    """The generic fallback's page-analysis tiers, packaged for DEDICATED
    adapters to opt into as a backstop when their own platform-specific
    extraction found no video (2026-08-14 rebuild, the user's explicit
    call: opt-in per adapter, never blanket -- a blind second-pass scan on
    a page carrying OTHER meetings' videos, like Cablecast's related-shows
    carousel, could attach the wrong meeting's video, which is worse than
    none).

    Returns `(video_url, video_format, video_link, video_link_recognized)`
    -- at most one of video_url/video_link is set. Pure page analysis, no
    network: the YouTube tier returns the embed URL directly rather than
    running YouTubeAssetFinder's metadata resolve, since an opting-in
    adapter already has its own (better) metadata.

    Callers should set `best_effort=True` and append a provenance warning
    when attaching anything from here -- the result came from a generic
    scan, not the platform's own confirmed structure.
    """
    video_id = GenericFallbackAssetFinder._find_youtube_video_id(html)
    if video_id:
        return f"https://www.youtube.com/embed/{video_id}", "youtube", None, False
    media_urls = scan_media_urls(html, page_url)
    video_url, video_format = GenericFallbackAssetFinder._pick_video_url(media_urls)
    if video_url:
        return video_url, video_format, None, False
    video_link, recognized = GenericFallbackAssetFinder._find_video_pointer(
        html, page_url
    )
    return None, None, video_link, recognized
