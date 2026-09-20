"""WO-909 (2026-09-20): `fetch_headless_sync()`
(scripts/wo147_access_ladder_sweep.py) crashed on every single headless
attempt during WO-908's 200-small-government pilot (BACKLOG.md's matching
entry) -- `p.chromium.launch()` with no `executable_path` makes Playwright
look for the exact Chromium revision this repo's pinned
`playwright==1.62.0` expects (build 1234), but the sandbox that pilot ran
in only has a DIFFERENT, pre-installed revision (build 1194) at
`/opt/pw-browsers/chromium`, reachable only via the `PLAYWRIGHT_BROWSERS_
PATH` env var that sandbox sets.

`_headless_chromium_executable_path()` is the fix: use that binary ONLY
when `PLAYWRIGHT_BROWSERS_PATH` is set AND a `chromium` file/symlink sits
directly inside it -- otherwise return None so `fetch_headless_sync()`
calls `p.chromium.launch()` exactly as before, with no argument at all.
This is deliberately NOT a hardcoded path: Ryan's own Mac and this repo's
own GitHub Actions CI runner both install Playwright's browser the normal
way (`playwright install`) at a different location and never set
`PLAYWRIGHT_BROWSERS_PATH`, so a hardcoded sandbox path would fix this one
sandbox and silently break both of those real environments.

These tests exercise only the branching logic -- env var + file-exists
check -> executable_path or None -- via monkeypatched os.environ/
os.path.exists and a fake Playwright (no real browser launch, per this
repo's own convention in tests/test_headless_browser.py). The "does this
actually fix headless for real" question is answered separately by a
throwaway, non-suite smoke test against a real URL -- see this WO's own
PR description for that result; a mocked test like this one can prove the
branching is correct but can never prove a real browser actually launches.
"""

from __future__ import annotations

from scripts.wo147_access_ladder_sweep import (
    _headless_chromium_executable_path,
    fetch_headless_sync,
)

# --- _headless_chromium_executable_path() in isolation ---------------------


def test_returns_env_var_path_when_set_and_binary_present(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    monkeypatch.setattr("os.path.exists", lambda p: p == "/opt/pw-browsers/chromium")
    assert _headless_chromium_executable_path() == "/opt/pw-browsers/chromium"


def test_returns_none_when_env_var_unset(monkeypatch):
    # Explicitly removed regardless of what the running environment (this
    # sandbox included -- it really does set this var) happens to have,
    # so this test proves the "unset" branch on its own merits.
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert _headless_chromium_executable_path() is None


def test_returns_none_when_env_var_set_but_binary_absent(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    monkeypatch.setattr("os.path.exists", lambda p: False)
    assert _headless_chromium_executable_path() is None


def test_uses_a_different_directory_when_env_var_points_elsewhere(monkeypatch):
    # Not hardcoded to /opt/pw-browsers specifically -- any directory the
    # env var names, as long as it carries a `chromium` entry, is used.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/some/other/browsers/dir")
    monkeypatch.setattr(
        "os.path.exists", lambda p: p == "/some/other/browsers/dir/chromium"
    )
    assert _headless_chromium_executable_path() == "/some/other/browsers/dir/chromium"


# --- fetch_headless_sync()'s own launch call, end to end (fake Playwright,
# no real browser) -----------------------------------------------------


class _FakePage:
    url = "https://example.com/"

    def goto(self, url, timeout=None, wait_until=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return "<html><body>fake page</body></html>"


class _FakeBrowser:
    def __init__(self, launch_kwargs):
        self.launch_kwargs = launch_kwargs
        self.closed = False

    def new_page(self, **kwargs):
        return _FakePage()

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, launch_calls):
        self._launch_calls = launch_calls

    def launch(self, **kwargs):
        self._launch_calls.append(kwargs)
        return _FakeBrowser(kwargs)


class _FakePlaywright:
    def __init__(self, launch_calls):
        self.chromium = _FakeChromium(launch_calls)


class _FakeSyncPlaywrightCM:
    """Stands in for the object `sync_playwright()` returns -- a context
    manager whose `__enter__` hands back the top-level Playwright driver
    object (here, just the fake with a `.chromium`)."""

    def __init__(self, launch_calls):
        self._launch_calls = launch_calls

    def __enter__(self):
        return _FakePlaywright(self._launch_calls)

    def __exit__(self, *exc_info):
        return False


def test_fetch_headless_sync_passes_executable_path_when_available(monkeypatch):
    launch_calls: list = []
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywrightCM(launch_calls),
    )
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    monkeypatch.setattr("os.path.exists", lambda p: p == "/opt/pw-browsers/chromium")

    html, final_url, err = fetch_headless_sync("https://example.com")

    assert err is None
    assert html == "<html><body>fake page</body></html>"
    assert launch_calls == [{"executable_path": "/opt/pw-browsers/chromium"}]


def test_fetch_headless_sync_calls_default_launch_when_env_var_unset(monkeypatch):
    launch_calls: list = []
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywrightCM(launch_calls),
    )
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    html, final_url, err = fetch_headless_sync("https://example.com")

    assert err is None
    # No executable_path kwarg at all -- the exact pre-WO-909 call shape,
    # so a normal environment (Ryan's Mac, CI) is completely unaffected.
    assert launch_calls == [{}]


def test_fetch_headless_sync_calls_default_launch_when_binary_absent(monkeypatch):
    launch_calls: list = []
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywrightCM(launch_calls),
    )
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    monkeypatch.setattr("os.path.exists", lambda p: False)

    html, final_url, err = fetch_headless_sync("https://example.com")

    assert err is None
    assert launch_calls == [{}]
