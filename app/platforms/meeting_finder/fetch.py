"""Meeting Finder's fetch helper (WO-1025).

One fetch helper used by every phase in docs/MEETING_FINDER.md that reads
a page live -- Start, Identify, Scan and Hop. See that doc's "How every
page is fetched" section for the ladder this implements:

    1. Plain request (always first).
    2. Browser headers -- only after a 403 or a dropped connection, never
       after a plain 404 (CLAUDE.md's "politely" rule: a realistic
       User-Agent/Referer is compliance with a naive bot check, not
       defiance of one).
    3. Headless browser -- only when a page loaded (200) but shows no
       `<a href>` links and the caller asked for links.
    4. Wayback's latest capture, read via the `id_` raw form, after a
       genuine human-verification challenge -- OR after the ladder ends
       in an ordinary hard block with no challenge marker at all (a 403
       or dropped connection that persists through the browser-headers
       rung; WO-1032, prompted by Essex, ON's `calendar.essex.ca/meetings`
       returning a plain 403 with no Wayback fallback). Links only, never
       media -- this is the one rung this module will never try to get
       past (CLAUDE.md, and docs/MEETING_FINDER.md's own line: "We never
       try to get past a site's challenge"). The outcome string itself
       (`cloudflare-challenge-blocked`/`blocked-waf-akamai`/
       `blocked-browser-headers`) never changes when Wayback supplies
       links -- `FetchResult.wayback_timestamp` being set is the flag
       that it did, and `FetchResult.challenge` says whether this was a
       real challenge or an ordinary block.

YouTube is refused outright, before any request: Meeting Finder never
fetches YouTube (docs/MEETING_FINDER.md; CLAUDE.md's YouTube-drip rule).

What this reuses, and why, rather than re-implementing:

  - `scripts/challenge_markers.py`'s `is_challenge()` -- the shared,
    pure-stdlib human-verification marker list every sweep script already
    uses. No changes needed there; it was already built to be imported.
  - `scripts/youtube_fetch_guard.py`'s `install()`/`is_youtube_host()` --
    same reasoning. `install()` is called from `Fetcher.__init__`, not at
    import time: it makes any YouTube hostname lookup raise for the rest
    of the PROCESS, not just this module, so calling it merely because
    something imported this file would break YouTube for every other
    caller sharing that process. `fetch()`'s own upfront host check
    stands on its own regardless of whether the guard is installed.
  - The Akamai-specific two of `app/platforms/generic_fallback.py`'s own
    `_CHALLENGE_MARKERS` (`errors.edgesuite.net`, `access denied` --
    tied to the real captured body in `tests/fixtures/generic_fallback/
    wayne_akamai_403.html`) to tell a `blocked-waf-akamai` verdict apart
    from a `cloudflare-challenge-blocked` one. Not the whole tuple: its
    third marker, `just a moment`, is that module's own comment's words
    for Cloudflare's interstitial, not Akamai's -- already covered by
    `scripts/challenge_markers.py`'s list. See `_AKAMAI_MARKERS`'s own
    comment below.
  - `scripts/wo282_recon.py`'s `cdx_get()`/`wayback_id_read()`/
    `newest_capture()` for the Wayback rung -- its retry/backoff/wall-
    clock-deadline behavior (WO-366/WO-939) is real, tuned behavior worth
    keeping in one place. Those are synchronous (`requests`-based) while
    this Fetcher is async (`aiohttp`), so they're called via
    `asyncio.to_thread()` rather than ported -- a straight import proved
    fine, not "awkward" in the sense the WO-1025 brief warned about:
    `scripts/wo282_recon.py` already puts `scripts/` on `sys.path` at its
    own module level (so its own bare `from challenge_markers import
    ...` resolves), opens no DB connection and makes no network call at
    import time (its own module docstring says so, confirmed live
    WO-1021), and `tests/test_wo282_recon_wayback_index.py` already
    imports it the same way (`importlib.import_module("scripts.
    wo282_recon")`) from this same test suite. So this module imports it
    directly rather than moving code out of a file under heavy, active,
    multi-session iteration (a dozen `wo3xx_recon.py`/`wo3xx_targeted.py`
    clones reference it) -- lower blast radius than the brief's
    "move it and have the script import it back" fallback, which is kept
    in reserve for a case where a direct import genuinely doesn't work.
  - `scripts/wo147_access_ladder_sweep.py`'s `fetch_headless_sync()`,
    `HONEST_HEADERS` and `BROWSER_HEADERS` -- same reasoning as above.
    One correction to the WO-1025 brief worth flagging: it named
    `app/platforms/headless_browser.py` as this function's home, but that
    module only has the Playwright *async* path used by the LIMS/SLC
    finders (`fetch_via_browser()`); the actual `fetch_headless_sync()`
    (sync, YouTube-embed-blocking, used by the WO-147+ ladder sweeps)
    lives in `scripts/wo147_access_ladder_sweep.py`. Imported from there
    instead of rewritten, for the same reasons as `wo282_recon.py` above
    -- it already blocks YouTube requests made *by the browser itself*
    (`_block_youtube_requests()`), which `scripts/youtube_fetch_guard.py`
    cannot do (that guards this Python process, not a separate Chromium
    one) and which a rewrite would have to reproduce exactly to stay
    safe.

Header-set choice per host, and the 403-vs-challenge distinction, also
follow measured findings in `~/Documents/rtr-upcoming`'s
`UPCOMING_AGENDAS_FIELD_GUIDE.md` ("Blocked hosts", re-measured
2026-08-26 across 108 real hosts): default to an honest, identifying
User-Agent rather than a Chrome header set (a Cloudflare host can 403 a
Chrome UA whose TLS fingerprint doesn't match its claim while serving the
honest UA 200 -- confirmed there for Marin County; Portola Valley's Akamai
needed the opposite, which is why this module still escalates rather than
picking one set forever); retry with browser headers on a 403 OR a
connection-level refusal, never a 404; remember which header set worked
per HOST for the rest of the run, since bot policy lives at the edge and
applies to every page on that host; and never call a plain 403 a
challenge -- only the presence of a real marker earns that.

Politeness: a minimum delay is enforced per host (`per_host_delay_s`,
default 2.5s, matching `wo282_recon.py`'s own `HOST_DELAY_SECONDS`) before
every real fetch to that host, including the browser-headers/headless
retries. A caller that has already read a host's robots.txt
`Crawl-delay` (Start already does, per docs/MEETING_FINDER.md) can pass it
in via `note_crawl_delay()` -- this module does not fetch robots.txt
itself, to avoid spending part of `max_fetches`' budget on a page no
phase asked for.

`max_fetches` counts real fetches of the *target site* (plain,
browser-headers, headless) -- not the Wayback CDX lookup or the `id_` raw
read, which only ever run after live fetching has already stopped for
that URL. That mirrors `wo282_recon.py`'s own design: CDX/Wayback calls
run under their own separate concurrency limit
(`ARCHIVE_CONCURRENCY`/`_ARCHIVE_SEMA`), not a government's per-request
budget. This budget only ever counted THIS Fetcher's own requests to the
target site -- see `.pacing`'s `pace_all_requests()` (WO-1032) for the
separate, process-wide count of every real request a government's whole
walk makes, adapters' own aiohttp sessions included.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import certifi

# CLAUDE.md: a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp builds its default SSLContext at import time -- this
# must run before `import aiohttp`, not just before the first request, so
# unlike the YouTube guard below this one CANNOT be deferred to
# `Fetcher.__init__`. Low risk to run merely on import: it's a
# `setdefault`, so it changes nothing for a process that already has a
# real `SSL_CERT_FILE` (or a working trust store) of its own.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

from scripts.challenge_markers import is_challenge  # noqa: E402
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    BROWSER_HEADERS,
    HONEST_HEADERS,
    fetch_headless_sync,
)
from scripts.wo282_recon import cdx_get, newest_capture, wayback_id_read  # noqa: E402
from scripts.youtube_fetch_guard import install as _install_youtube_guard  # noqa: E402
from scripts.youtube_fetch_guard import is_youtube_host  # noqa: E402

# NOT installed at import time on purpose (conductor review, WO-1025):
# `youtube_fetch_guard.install()` makes ANY YouTube hostname lookup raise
# for the rest of the PROCESS, not just this module -- calling it merely
# because something imported `app.platforms.meeting_finder.fetch` would
# break YouTube for every other caller sharing that process (another
# test, a future script, or the drip Mac's `youtube_drip.py` if it ever
# imports anything from this package). It's called from `Fetcher.__init__`
# instead (idempotent, so constructing more than one `Fetcher` is fine),
# and `fetch()`'s own upfront `is_youtube_host()` check stays regardless
# of whether the guard is installed.

_LINK_RE = re.compile(r"<a\b[^>]*\bhref\s*=", re.IGNORECASE)

# WO-1037 item 7: real, confirmed shape found diagnosing Aiken County SD
# SC, Sherwood AR and Chesterfield County PS VA (a shared Thrillshare/
# Apptegy CMS) -- the page's real navigation, including its Swagit
# link, is only present inside a JSON hydration blob, rendered as HTML
# markup ONLY after a JS framework runs. The ORIGINAL `_has_links()` gate
# never fires because the page also carries ~150+ ordinary utility
# `<a href>` links (site chrome, footer, skip-links) that ARE real parsed
# anchors -- so "the page has links" is true even though none of them are
# useful. The two real signs a JSON blob is hiding the real nav: an
# HTML-escaped anchor tag (`&lt;a `, since the real markup is itself a
# JSON-STRING-encoded HTML fragment) or a named video-vendor hostname
# that appears in the raw text but never as an actual parsed href/src.
_ESCAPED_ANCHOR_RE = re.compile(r"&lt;a[\s>]", re.IGNORECASE)
_UNPARSED_VENDOR_HOST_HINTS = ("swagit.com", "cablecast.tv")
_HREF_OR_SRC_ATTR_RE = re.compile(
    r'(?:href|src)\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE
)


def _real_link_targets(html: str) -> str:
    """Every value that actually sits inside a real, parsed `href=`/
    `src=` attribute -- used only to tell a vendor hostname that's merely
    named somewhere in the raw markup (a JSON blob, an escaped fragment)
    apart from one that's already a genuine link `_has_links()` would
    have found anyway."""
    return " ".join(_HREF_OR_SRC_ATTR_RE.findall(html)).lower()


def _has_no_useful_link_evidence(html: str | None) -> bool:
    """True when `html` offers nothing worth Hop/Scan following: no
    `<a href>` at all (the original gate), or the raw markup shows an
    HTML-escaped anchor or names a known video-vendor host that never
    actually shows up as a real parsed href/src -- both real, confirmed
    JS-hydrated-nav shapes where the zero-links gate alone never fires
    (see this module's own comment above `_ESCAPED_ANCHOR_RE`)."""
    if not html:
        return True
    if not _has_links(html):
        return True
    if _ESCAPED_ANCHOR_RE.search(html):
        return True
    lower = html.lower()
    real_targets = _real_link_targets(html)
    return any(
        hint in lower and hint not in real_targets
        for hint in _UNPARSED_VENDOR_HOST_HINTS
    )


# --- Cross-Fetcher-instance per-host pacing (WO-1030) -----------------
#
# `Fetcher._wait_for_host()` alone only paces requests made by ONE
# `Fetcher` instance. `runner.py`'s `--concurrency` flag creates one
# `Fetcher` per government running concurrently, and several governments
# can share the same vendor host (many `*.granicus.com` tenants, for
# instance) -- an instance-only wait lets two concurrent governments both
# hit that shared host at the same moment, which is exactly the kind of
# impoliteness CLAUDE.md's "we query sites politely" rule warns about.
# This is a small, process-wide, host-keyed pacer every `Fetcher` consults
# in addition to its own per-instance bookkeeping, so two DIFFERENT
# `Fetcher`s (different governments) still can't both start a request to
# the same host inside the same window. `_HOST_PACER_LOCK` guards the
# dict with no `await` inside the critical section, so the check-and-
# reserve is atomic under asyncio (no other task can interleave between
# reading and writing `_HOST_PACER_NEXT_AT`).
_HOST_PACER_NEXT_AT: dict[str, float] = {}
_HOST_PACER_LOCK = asyncio.Lock()


async def _global_wait_for_host(host: str, delay: float) -> None:
    async with _HOST_PACER_LOCK:
        now = time.monotonic()
        next_at = max(now, _HOST_PACER_NEXT_AT.get(host, 0.0))
        wait = next_at - now
        _HOST_PACER_NEXT_AT[host] = next_at + delay
    if wait > 0:
        await asyncio.sleep(wait)


# Per-attempt socket timeout. Deliberately shorter than
# `wo282_recon.py`'s `GOV_REQUEST_WALL_CLOCK_DEADLINE` (25s): this is a
# single-page interactive fetch inside a live Meeting Finder walk, not a
# batch sweep, so a slow host should fail fast enough to try the next
# rung (or the next fork) rather than stall the whole walk.
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)

# WO-1039 item 4: aiohttp's own default (8190 bytes, matching most other
# HTTP clients' conventional limit) is too small for some real sites --
# confirmed live, `nortoncityschools.org` (2026-09-23):
# `ClientResponseError: 400, message='Got more than 8190 bytes when
# reading Header value is too long.'` on an ordinary plain GET, well
# before this Fetcher ever got to see a status code or body. aiohttp
# exposes both limits directly on `ClientSession.__init__` (added
# upstream for exactly this shape of failure) -- raised generously (8x)
# here rather than to some exact value tuned to one site's own header,
# since the failure mode (a hard exception instead of a normal response)
# is the same whatever pushed a real site over the old default. Adapters
# that build their OWN `aiohttp.ClientSession` (outside this Fetcher) are
# NOT covered by this -- see CLAUDE.md/this WO's own note for which ones
# may need the identical fix if this same error shows up against one of
# them.
_MAX_HEADER_SIZE = 65536


class BudgetExceeded(RuntimeError):
    """Raised by `Fetcher.fetch()` when performing the fetch would push
    `fetches_used` past `max_fetches`. Raised before the request is made,
    so the caller's own loop (Start/Identify/Scan/Hop) can stop cleanly
    and record how much budget was actually used."""


class SoftBudgetExceeded(BudgetExceeded):
    """WO-1039 item 2: raised instead of the plain `BudgetExceeded` above
    when a caller has asked this Fetcher to keep a few fetches in RESERVE
    (`Fetcher.reserve()`) for a later phase, even though the real
    `max_fetches` ceiling hasn't actually been reached yet. A SUBCLASS of
    `BudgetExceeded` on purpose: every existing `except BudgetExceeded`
    site across `identify.py`/`listing.py` already treats hitting the
    ceiling as "this one fetch failed, stop gracefully and return
    whatever's already been found" -- exactly the behavior wanted here
    too, so none of those call sites need to change. Only `runner.py`'s
    own Pass-1/Pass-2 split (the one thing that actually calls
    `reserve()`/`release_reserve()`) needs to tell the two apart, via
    `isinstance(exc, SoftBudgetExceeded)`, so a reserved-budget stop
    during cheap Pass 1 (Identify/List) never gets recorded as real
    government-wide budget exhaustion the way a genuine `BudgetExceeded`
    does -- see `runner.py`'s own docstring for the real Ashland, OR case
    this fixes (a CivicPlus AgendaCenter listing walk alone used all 12
    fetches, `hops=0` the entire run -- Hop never got a single real fetch
    to spend)."""


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str | None
    status: int | None
    html: str | None
    access_mode: str
    outcome: str | None
    challenge: bool
    wayback_timestamp: str | None
    links_only: bool
    elapsed_ms: int


def _has_links(html: str | None) -> bool:
    return bool(html) and bool(_LINK_RE.search(html))


# Deliberately NOT the whole of app/platforms/generic_fallback.py's own
# `_CHALLENGE_MARKERS` tuple: that tuple bundles three markers, each tied
# to one real captured body, but for THREE different WAFs -- its own
# comment says so explicitly: "access denied"/"errors.edgesuite.net" are
# the real Akamai body (tests/fixtures/generic_fallback/
# wayne_akamai_403.html), "just a moment" is Cloudflare's own interstitial
# (already covered by `scripts/challenge_markers.py`'s CHALLENGE_MARKERS,
# imported above). Importing that tuple whole and calling the Cloudflare
# marker "Akamai" was an early bug in this module, caught by
# `tests/test_meeting_finder_fetch.py`'s own "Just a moment..." case
# resolving to `blocked-waf-akamai` before this was narrowed.
_AKAMAI_MARKERS = ("errors.edgesuite.net", "access denied")


def _is_akamai_block(body: str) -> bool:
    lower = (body or "").lower()
    return any(marker in lower for marker in _AKAMAI_MARKERS)


def _looks_like_challenge(body: str | None) -> bool:
    if not body:
        return False
    return is_challenge(body) or _is_akamai_block(body)


def _challenge_outcome(body: str | None) -> str:
    if _is_akamai_block(body or ""):
        return "blocked-waf-akamai"
    return "cloudflare-challenge-blocked"


class Fetcher:
    """One fetch helper, reused across every page a single Meeting Finder
    walk reads. See this module's docstring for the ladder and what each
    rung reuses."""

    def __init__(
        self,
        *,
        max_fetches: int = 12,
        per_host_delay_s: float = 2.5,
        allow_headless: bool = True,
        allow_wayback: bool = True,
        user_agent: str | None = None,
    ) -> None:
        # Guards this PROCESS's own socket/aiohttp resolution against a
        # YouTube hostname -- belt and braces on top of `fetch()`'s own
        # upfront `is_youtube_host()` check. Installed here, not at
        # import time (see this module's own comment above
        # `_LINK_RE` for why), and idempotent -- constructing more than
        # one `Fetcher` in the same process is fine.
        _install_youtube_guard()
        self.max_fetches = max_fetches
        self.per_host_delay_s = per_host_delay_s
        self.allow_headless = allow_headless
        self.allow_wayback = allow_wayback
        self.fetches_used = 0
        self._user_agent = user_agent
        self._crawl_delays: dict[str, float] = {}
        self._last_fetch_at: dict[str, float] = {}
        self._host_header_mode: dict[str, str] = {}
        self._session: aiohttp.ClientSession | None = None
        # WO-1039 item 2: see `SoftBudgetExceeded`'s own docstring.
        self._reserved_fetches = 0

    def reserve(self, n: int) -> None:
        """Keep `n` fetches back: any further real fetch that would push
        `fetches_used` past `max_fetches - n` raises `SoftBudgetExceeded`
        instead of performing the request, until `release_reserve()` is
        called. A no-op (clamped to 0) for a negative `n`."""
        self._reserved_fetches = max(0, n)

    def release_reserve(self) -> None:
        self._reserved_fetches = 0

    def note_crawl_delay(self, host: str, seconds: float) -> None:
        """Record a robots.txt `Crawl-delay` a caller already read for
        `host` (Start already fetches robots.txt for its own reasons --
        see docs/MEETING_FINDER.md). Applied to every future fetch to
        that host for the life of this Fetcher, same as `wo282_recon.py`
        applying it to "that host's own entry in the shared rate limiter
        for the REST of this government's requests"."""
        self._crawl_delays[host] = seconds

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    def _headers(self, *, browser: bool) -> dict:
        base = dict(BROWSER_HEADERS if browser else HONEST_HEADERS)
        # WO-1034: never offer Brotli. The shared browser header set says
        # `gzip, deflate, br`, but aiohttp can't decode `br` without the
        # optional Brotli package, and a site that honours it (Oxnard, CA,
        # calibration run A 2026-09-23) raised ClientResponseError and lost
        # that government's row. Only this copy changes, not wo147's.
        for key in list(base):
            if key.lower() == "accept-encoding":
                base[key] = "gzip, deflate"
        if self._user_agent:
            base["user-agent"] = self._user_agent
        return base

    async def _session_for(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=DEFAULT_TIMEOUT,
                max_line_size=_MAX_HEADER_SIZE,
                max_field_size=_MAX_HEADER_SIZE,
            )
        return self._session

    async def _wait_for_host(self, host: str) -> None:
        delay = max(self.per_host_delay_s, self._crawl_delays.get(host, 0.0))
        # Instance-local spacing (belt) plus the process-wide pacer
        # (braces, WO-1030) -- see `_global_wait_for_host()`'s own
        # comment for why a single Fetcher's own bookkeeping isn't
        # enough once more than one Fetcher (one per government under
        # `--concurrency`) can share a host.
        last = self._last_fetch_at.get(host)
        if last is not None:
            remaining = delay - (time.monotonic() - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        await _global_wait_for_host(host, delay)

    def _mark_host(self, host: str) -> None:
        self._last_fetch_at[host] = time.monotonic()

    def _take_budget(self) -> None:
        if self.fetches_used >= self.max_fetches:
            raise BudgetExceeded(
                f"max_fetches ({self.max_fetches}) reached; refusing one more "
                "real fetch"
            )
        if (
            self._reserved_fetches
            and self.fetches_used >= self.max_fetches - self._reserved_fetches
        ):
            # WO-1039 item 2: the hard ceiling hasn't been hit, but this
            # fetch would eat into the fetches `reserve()` is holding back
            # for a later phase.
            raise SoftBudgetExceeded(
                f"{self._reserved_fetches} fetch(es) reserved for a later "
                "phase; refusing one more real fetch during this one"
            )
        self.fetches_used += 1

    async def _plain_get(self, url: str, *, browser: bool):
        """One real HTTP GET (plain headers or browser headers). Returns
        (status, final_url, text_or_None, error_kind), where error_kind
        is None, 'dns', 'timeout' or 'dropped'."""
        host = urlparse(url).hostname or ""
        await self._wait_for_host(host)
        self._take_budget()
        session = await self._session_for()
        try:
            async with session.get(
                url, headers=self._headers(browser=browser), allow_redirects=True
            ) as resp:
                status = resp.status
                final_url = str(resp.url)
                text: str | None
                try:
                    text = await resp.text(errors="replace")
                except (UnicodeDecodeError, aiohttp.ClientPayloadError):
                    text = None
                return status, final_url, text, None
        except aiohttp.ClientConnectorDNSError:
            return None, url, None, "dns"
        except (
            asyncio.TimeoutError,
            aiohttp.ServerTimeoutError,
            aiohttp.ConnectionTimeoutError,
            aiohttp.SocketTimeoutError,
        ):
            return None, url, None, "timeout"
        except (
            aiohttp.ServerDisconnectedError,
            aiohttp.ClientOSError,
            aiohttp.ClientConnectorError,
            aiohttp.ClientPayloadError,
            aiohttp.ClientConnectionError,
        ):
            return None, url, None, "dropped"
        finally:
            self._mark_host(host)

    async def _headless(self, url: str):
        """Headless-browser rung. Runs the existing sync Playwright helper
        in a thread (it launches/closes its own browser per call -- see
        that function's own module for why)."""
        host = urlparse(url).hostname or ""
        self._take_budget()
        await self._wait_for_host(host)
        try:
            html, final_url, err = await asyncio.to_thread(fetch_headless_sync, url)
        finally:
            self._mark_host(host)
        return html, final_url, err

    async def _wayback_latest(self, url: str) -> tuple[str | None, str | None]:
        """CDX lookup + `id_` raw read of `url`'s newest 200 capture.
        Links only -- callers must never treat this html as a media
        source (`FetchResult.links_only` says so explicitly)."""
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?url="
            + quote(url, safe="")
            + "&filter=statuscode:200&collapse=urlkey&limit=-5"
            "&fl=original,timestamp&output=json"
        )
        resp = await asyncio.to_thread(cdx_get, cdx_url)
        if resp is None:
            return None, None
        try:
            rows = json.loads(resp.text)[1:]
        except (ValueError, TypeError):
            rows = []
        best = newest_capture(rows)
        if not best:
            return None, None
        original_url, timestamp = best
        body = await asyncio.to_thread(wayback_id_read, original_url, timestamp)
        if body is None:
            return None, timestamp
        try:
            html: str | None = body.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, LookupError):
            html = None
        return html, timestamp

    def _result(
        self,
        *,
        requested_url: str,
        final_url: str | None = None,
        status: int | None = None,
        html: str | None = None,
        access_mode: str,
        outcome: str | None = None,
        challenge: bool = False,
        wayback_timestamp: str | None = None,
        links_only: bool = False,
        start: float,
    ) -> FetchResult:
        return FetchResult(
            requested_url=requested_url,
            final_url=final_url,
            status=status,
            html=html,
            access_mode=access_mode,
            outcome=outcome,
            challenge=challenge,
            wayback_timestamp=wayback_timestamp,
            links_only=links_only,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )

    async def _wayback_fallback_result(
        self,
        url: str,
        *,
        access_mode: str,
        outcome: str,
        challenge: bool,
        status: int | None = None,
        final_url: str | None = None,
        start: float,
    ) -> FetchResult:
        """Shared by both ladder endings that give up on live access to
        `url`: a genuine human-verification challenge (`challenge=True`,
        via `_challenge_result()`) and a hard block that never showed a
        challenge marker -- a 403/dropped connection that persisted
        through the browser-headers rung (`challenge=False`, WO-1032).
        Both try Wayback's latest capture for LINKS ONLY (never media --
        `links_only` says so on the result), same as the docstring's own
        "How every page is fetched" table. The outcome string itself
        (`outcome`) is never changed by a successful Wayback read -- a
        caller who only reads `outcome` still sees "this was blocked";
        `wayback_timestamp` not being `None` is the flag that Wayback
        links were used to get past it, and `challenge` says which kind
        of block this was.
        """
        wayback_html = None
        wayback_ts = None
        if self.allow_wayback:
            wayback_html, wayback_ts = await self._wayback_latest(url)
        return self._result(
            requested_url=url,
            final_url=final_url,
            status=status,
            html=wayback_html,
            access_mode="wayback" if wayback_html else access_mode,
            outcome=outcome,
            challenge=challenge,
            wayback_timestamp=wayback_ts,
            links_only=bool(wayback_html),
            start=start,
        )

    async def _challenge_result(
        self, url: str, access_mode: str, body: str | None, start: float
    ) -> FetchResult:
        return await self._wayback_fallback_result(
            url,
            access_mode=access_mode,
            outcome=_challenge_outcome(body),
            challenge=True,
            start=start,
        )

    async def fetch(self, url: str, *, need_links: bool = True) -> FetchResult:
        start = time.monotonic()
        host = urlparse(url).hostname or ""

        # Rung 0: refuse YouTube outright. No request at all -- doesn't
        # touch `fetches_used`.
        if is_youtube_host(host):
            return self._result(
                requested_url=url,
                access_mode="dead",
                outcome="youtube-not-fetched",
                start=start,
            )

        # rtr-upcoming `UPCOMING_AGENDAS_FIELD_GUIDE.md`'s "Blocked hosts"
        # section (re-measured 2026-08-26 across 108 real hosts): bot
        # policy lives at the edge, so which header set actually gets
        # through is a property of the HOST, not of any one page on it --
        # confirmed there for both directions (Marin County's Cloudflare
        # 403'd a full Chrome header set but served the honest UA 200;
        # Portola Valley's Akamai needed the opposite). Once this Fetcher
        # has confirmed a host needs browser headers, every later fetch()
        # to that host starts there directly instead of re-spending a
        # fetch on a plain attempt already known to fail.
        start_with_browser_headers = self._host_header_mode.get(host) == "browser"

        status, final_url, text, err = await self._plain_get(
            url, browser=start_with_browser_headers
        )
        access_mode = "browser-headers" if start_with_browser_headers else "plain"

        if err == "dns":
            return self._result(
                requested_url=url,
                access_mode=access_mode,
                outcome="dns-unresolvable",
                start=start,
            )
        if err == "timeout":
            return self._result(
                requested_url=url,
                access_mode=access_mode,
                outcome="timeout",
                start=start,
            )

        # Rung 2: browser headers -- only after a 403 or a connection-level
        # refusal (a dropped connection, a `RemoteDisconnected`-shaped
        # reset with no status line -- rtr-upcoming's field guide confirmed
        # this live against Municode), never after a plain 404. Skipped
        # when we already started with browser headers above.
        if not start_with_browser_headers and (err == "dropped" or status == 403):
            status2, final_url2, text2, err2 = await self._plain_get(url, browser=True)
            access_mode = "browser-headers"

            if err2 == "dns":
                return self._result(
                    requested_url=url,
                    access_mode=access_mode,
                    outcome="dns-unresolvable",
                    start=start,
                )
            if err2 == "timeout":
                return self._result(
                    requested_url=url,
                    access_mode=access_mode,
                    outcome="timeout",
                    start=start,
                )
            if err2 == "dropped" or status2 == 403:
                # A 403 (or a reset) is not itself a challenge page --
                # rtr-upcoming's field guide, point 4 -- only call it
                # `cloudflare-challenge-blocked`/`blocked-waf-akamai` when
                # a real challenge marker is present in the body.
                body = text2 or text
                self._host_header_mode[host] = "browser"
                if _looks_like_challenge(body):
                    return await self._challenge_result(url, access_mode, body, start)
                # WO-1032: the browser-headers rung also ended in a hard
                # block (a 403 or dropped connection, no challenge marker
                # in the body) -- fall back to Wayback for links, same as
                # a real challenge would, per docs/MEETING_FINDER.md's
                # "How every page is fetched" table and CLAUDE.md's
                # Essex, ON finding (a plain 403 with no challenge marker
                # got no Wayback fallback before this).
                return await self._wayback_fallback_result(
                    url,
                    access_mode=access_mode,
                    outcome="blocked-browser-headers",
                    challenge=False,
                    status=status2,
                    final_url=final_url2,
                    start=start,
                )
            status, final_url, text = status2, final_url2, text2
            self._host_header_mode[host] = "browser"
        elif start_with_browser_headers and (err == "dropped" or status == 403):
            body = text
            if _looks_like_challenge(body):
                return await self._challenge_result(url, access_mode, body, start)
            # WO-1032: same hard-block Wayback fallback as above, for the
            # case where this Fetcher already knew the host needed
            # browser headers and started there directly.
            return await self._wayback_fallback_result(
                url,
                access_mode=access_mode,
                outcome="blocked-browser-headers",
                challenge=False,
                status=status,
                final_url=final_url,
                start=start,
            )
        elif not start_with_browser_headers:
            # Plain headers worked on the first try -- remember that for
            # this host too, so a later fetch() doesn't have to re-learn
            # it (no-op once already recorded either way).
            self._host_header_mode.setdefault(host, "plain")

        # A human-verification challenge can show up on a real 200, on
        # either rung -- checked regardless of how we got here.
        if _looks_like_challenge(text):
            return await self._challenge_result(url, access_mode, text, start)

        # Rung 3: headless -- only when the page loaded but shows no real
        # link evidence worth following (WO-1037 item 7: zero links, OR a
        # JS-hydrated nav whose real content never shows up as a parsed
        # href/src -- see `_has_no_useful_link_evidence()`), and the
        # caller actually needs links. Still one headless render per
        # fetch() call at most -- this only widens WHEN it fires, not how
        # often.
        if (
            status == 200
            and need_links
            and self.allow_headless
            and _has_no_useful_link_evidence(text)
        ):
            hl_html, hl_final_url, hl_err = await self._headless(url)
            if hl_html:
                access_mode = "headless"
                if _looks_like_challenge(hl_html):
                    return await self._challenge_result(
                        url, access_mode, hl_html, start
                    )
                return self._result(
                    requested_url=url,
                    final_url=hl_final_url or final_url,
                    status=status,
                    html=hl_html,
                    access_mode=access_mode,
                    start=start,
                )
            return self._result(
                requested_url=url,
                final_url=final_url,
                status=status,
                html=text,
                access_mode="headless",
                outcome="blocked-headless",
                start=start,
            )

        return self._result(
            requested_url=url,
            final_url=final_url,
            status=status,
            html=text,
            access_mode=access_mode,
            start=start,
        )
