"""Tests for app/platforms/headless_browser.py's self-heal path -- built
2026-08-09 in direct response to a real production incident: the
`playwright install --with-deps chromium` build step (render.yaml) didn't
leave a working browser binary where the running service looked for it,
and Playwright's own raw multi-line error text leaked onto a real
visitor's page (app/main.py's generic `except Exception: str(e)` handler
has no reason to expect an exception message that large/ugly). See
BACKLOG_DONE.md for the full incident writeup.

Mocks Playwright itself (no real browser launch/download during the test
suite) -- these tests are about `_get_browser()`'s own retry/error-
translation logic, not Playwright's real behavior.
"""

import app.platforms.headless_browser as hb
from app.platforms.headless_browser import HeadlessBrowserUnavailable, _get_browser


def _reset_module_state():
    hb._browser = None
    hb._playwright_cm = None
    hb._install_attempted = False


async def test_get_browser_self_heals_when_binary_missing(monkeypatch):
    _reset_module_state()

    launch_calls = []

    async def fake_launch(headless):
        launch_calls.append(1)
        if len(launch_calls) == 1:
            raise Exception(
                "BrowserType.launch: Executable doesn't exist at "
                "/opt/render/.cache/ms-playwright/chromium_headless_shell-1234/"
                "chrome-headless-shell-linux64/chrome-headless-shell\n"
                "╔════════════════════════════════════════════════════════════╗\n"
                "║ Looks like Playwright was just installed or updated.        ║\n"
                "╚════════════════════════════════════════════════════════════╝"
            )
        return "fake-browser-instance"

    class FakeChromium:
        launch = staticmethod(fake_launch)

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContextManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(hb, "async_playwright", lambda: FakePlaywrightContextManager())
    monkeypatch.setattr(hb, "_install_chromium", lambda: True)  # simulate a successful runtime install

    browser = await _get_browser()

    assert browser == "fake-browser-instance"
    assert len(launch_calls) == 2  # first attempt failed, retry after install succeeded


async def test_get_browser_raises_clean_message_when_install_also_fails(monkeypatch):
    _reset_module_state()

    async def fake_launch(headless):
        raise Exception("BrowserType.launch: Executable doesn't exist at /some/path")

    class FakeChromium:
        launch = staticmethod(fake_launch)

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContextManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(hb, "async_playwright", lambda: FakePlaywrightContextManager())
    monkeypatch.setattr(hb, "_install_chromium", lambda: False)  # simulate a failed runtime install

    try:
        await _get_browser()
        assert False, "expected HeadlessBrowserUnavailable"
    except HeadlessBrowserUnavailable as e:
        # The whole point: short and clean, not Playwright's raw ASCII-art text.
        assert len(str(e)) < 200
        assert "╔" not in str(e)


async def test_get_browser_reraises_unrelated_errors_without_attempting_install(monkeypatch):
    _reset_module_state()

    install_calls = []

    async def fake_launch(headless):
        raise Exception("some unrelated real launch failure")

    class FakeChromium:
        launch = staticmethod(fake_launch)

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContextManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(hb, "async_playwright", lambda: FakePlaywrightContextManager())
    monkeypatch.setattr(hb, "_install_chromium", lambda: install_calls.append(1) or True)

    try:
        await _get_browser()
        assert False, "expected HeadlessBrowserUnavailable"
    except HeadlessBrowserUnavailable:
        pass

    assert install_calls == []  # never even tried to self-heal for an unrelated error


async def test_get_browser_raises_clean_error_when_playwright_package_missing(monkeypatch):
    """Real 2026-08-09 incident: worker/requirements.txt deliberately
    doesn't include playwright (kept lean on purpose), but worker/main.py
    imports app.platforms, which registers LimsAssetFinder/SlcAssetFinder,
    which import this module -- a top-level `from playwright.async_api
    import ...` meant that alone crashed the *entire* worker process with
    ModuleNotFoundError. async_playwright is None here to simulate that
    environment (this module's own try/except ImportError sets it to None
    when the package isn't installed)."""
    _reset_module_state()
    monkeypatch.setattr(hb, "async_playwright", None)

    try:
        await _get_browser()
        assert False, "expected HeadlessBrowserUnavailable"
    except HeadlessBrowserUnavailable as e:
        assert len(str(e)) < 200


def test_install_chromium_only_attempts_once(monkeypatch):
    _reset_module_state()

    run_calls = []

    def fake_run(*args, **kwargs):
        run_calls.append(1)

        class FakeResult:
            returncode = 1
            stderr = "boom"

        return FakeResult()

    monkeypatch.setattr(hb.subprocess, "run", fake_run)

    first = hb._install_chromium()
    second = hb._install_chromium()

    assert first is False
    assert second is False  # short-circuited by _install_attempted, no second subprocess call
    assert len(run_calls) == 1
