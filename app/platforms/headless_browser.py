"""Shared headless-browser fetch for Cloudflare-JS-challenge-gated sources.

Every other adapter in this repo is a plain `aiohttp.ClientSession.get()` --
this is the one genuinely new kind of dependency, added deliberately (not
defaulted into) after confirming plain HTTP requests can't get past a real
Cloudflare "Just a moment..." JS challenge, and that there's no lighter
workaround: a real visitor's own browser passes it fine, but neither a
server-side `aiohttp` request (realistic headers alone don't help, unlike
Granicus's simpler Referer-only 403) nor a client-side `fetch()` from the
visitor's browser (blocked by CORS on both known real cases) can reach the
page on this app's behalf. See BACKLOG_DONE.md for the full investigation
(Minneapolis LIMS and SLC's meeting-recap pages, the two real cases this
was built for).

**The fix that actually worked, confirmed live against both real sites,
is much smaller than a full "stealth" setup**: a plain headless Chromium
launch alone still gets served the Cloudflare challenge page (confirmed
live against Minneapolis LIMS) -- Playwright's default context sends a
User-Agent string that identifies itself as a headless browser, an easy
signal for Cloudflare's bot detection to key on. Setting a normal desktop
Chrome User-Agent + a real viewport size (nothing else -- no stealth
plugins, no `--disable-blink-features=AutomationControlled`, no extra
wait time) was sufficient for both sites tested. Confirmed by isolating
each variable independently before combining them, not assumed.

A single Chromium instance is launched lazily on first use and reused
across requests (real cold-launch cost, confirmed live: ~1-2s just to
start the browser, on top of page-load/challenge-resolution time) --
launching fresh per-request would make every Cloudflare-gated resolve
noticeably slower than it needs to be. Guarded by a lock so concurrent
first-callers don't race to launch two browsers.

**Real, unverified deployment implication**: Render's plain `runtime:
python` buildpack (confirmed sufficient for ffmpeg/ffprobe, see
BACKLOG_DONE.md) has never been confirmed to also have Chromium available
-- Playwright needs its own downloaded browser binary (`playwright install
chromium`, a real build step, not just a pip package), which this repo's
existing `render.yaml` doesn't do yet. Flagged, not yet verified against a
real Render deploy -- see BACKLOG.md.
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import Browser, async_playwright

logger = logging.getLogger("rtr_deeplink.headless_browser")

# Confirmed live 2026-08-09: this specific combination (realistic desktop
# Chrome UA + a real viewport) is what actually matters -- isolated from
# wait-time and --disable-blink-features=AutomationControlled, neither of
# which made a difference on their own.
_REALISTIC_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 800}

# How long to let a Cloudflare JS challenge resolve before reading the
# page -- confirmed live that 3s wasn't reliably enough for Minneapolis
# LIMS's challenge to finish; 4s was. Not fine-tuned further than that;
# tunable if a slower-resolving challenge turns up on a future platform.
DEFAULT_WAIT_MS = 4000

_browser: Optional[Browser] = None
_browser_lock = asyncio.Lock()
_playwright_cm = None


async def _get_browser() -> Browser:
    global _browser, _playwright_cm
    if _browser is not None:
        return _browser
    async with _browser_lock:
        if _browser is not None:  # another caller won the race while we waited
            return _browser
        _playwright_cm = async_playwright()
        playwright = await _playwright_cm.start()
        _browser = await playwright.chromium.launch(headless=True)
        return _browser


async def fetch_via_browser(url: str, *, wait_ms: int = DEFAULT_WAIT_MS) -> str:
    """Loads `url` in a real (headless) Chromium tab and returns the
    rendered HTML -- for a source that returns a Cloudflare JS challenge
    to a plain HTTP request. Each call gets its own browser context (cheap
    relative to the shared browser instance itself) so concurrent fetches
    don't share cookies/state with each other."""
    browser = await _get_browser()
    context = await browser.new_context(user_agent=_REALISTIC_USER_AGENT, viewport=_VIEWPORT)
    try:
        page = await context.new_page()
        await page.goto(url, timeout=20000)
        await page.wait_for_timeout(wait_ms)
        return await page.content()
    finally:
        await context.close()
