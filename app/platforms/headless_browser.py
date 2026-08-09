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

**Real production incident, 2026-08-09, confirmed the deployment risk
flagged above: `render.yaml`'s `playwright install --with-deps chromium`
build step did not leave a working browser binary where the running
service looks for it** -- a real user hit `BrowserType.launch: Executable
doesn't exist at /opt/render/.cache/ms-playwright/...` on a real
Minneapolis LIMS resolve, and Playwright's own multi-line ASCII-art error
message leaked verbatim onto the page (`app/main.py`'s `/api/resolve`
catches any `Exception` from `finder.resolve()` and shows `str(e)`
directly -- fine for every other adapter's typically-short exceptions,
not fine for this one). Root cause of the missing binary itself is still
unconfirmed (possibilities: the Render service isn't actually
Blueprint-synced to this repo's `render.yaml`, so the dashboard's own
build command never picked up the change; `--with-deps`'s apt-get step
silently failing without permissions in Render's build environment; a
build-time-vs-runtime `$HOME`/cache-path mismatch) -- worth checking
Render's actual build logs directly, not just guessing from here.

**`_get_browser()` below now self-heals**: if the browser fails to
launch because the binary is missing, it runs `playwright install
chromium` once, right there in the running process, and retries -- so a
misconfigured/incomplete build step doesn't leave this permanently
broken until a redeploy. This does NOT replace fixing the real build
step (see BACKLOG.md) -- it's a safety net, and the self-heal itself
costs real time (a real browser download) on whichever request first
triggers it after each process start, and won't survive a restart on a
host with an ephemeral filesystem. `fetch_via_browser()` also now raises
a short, clean message instead of letting Playwright's own multi-line
error text reach a real visitor's page.
"""

import asyncio
import logging
import subprocess
import sys
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
_install_attempted = False


class HeadlessBrowserUnavailable(Exception):
    """Raised in place of Playwright's own raw (multi-line, ASCII-art)
    error text, which is not fit to show a real visitor -- see this
    module's docstring for the real 2026-08-09 incident this fixes."""


def _install_chromium() -> bool:
    """Runs `playwright install chromium` in-process, once. Real download
    (tens of seconds to a couple minutes depending on network), so this is
    a last-resort self-heal for a build step that didn't work, not a
    substitute for fixing that build step. Returns whether it succeeded."""
    global _install_attempted
    if _install_attempted:
        return False
    _install_attempted = True
    logger.warning("Chromium binary missing -- attempting a runtime `playwright install chromium`.")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.error("Runtime playwright install failed: %s", result.stderr[-2000:])
            return False
        logger.warning("Runtime playwright install succeeded.")
        return True
    except Exception:
        logger.exception("Runtime playwright install raised.")
        return False


async def _get_browser() -> Browser:
    global _browser, _playwright_cm
    if _browser is not None:
        return _browser
    async with _browser_lock:
        if _browser is not None:  # another caller won the race while we waited
            return _browser
        _playwright_cm = async_playwright()
        playwright = await _playwright_cm.start()
        try:
            _browser = await playwright.chromium.launch(headless=True)
        except Exception as e:
            if "Executable doesn't exist" not in str(e) or not _install_chromium():
                raise HeadlessBrowserUnavailable(
                    "This meeting needs a real browser to load, and it isn't available right now."
                ) from e
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
