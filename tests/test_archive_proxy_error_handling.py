"""Two Archive reverse-proxy error-handling bugs, both confirmed live via
Sentry and fixed together (see BACKLOG_DONE.md's 2026-08-21 entry):

1. `app/archive_client.py`'s `proxy_get()` created its `aiohttp.ClientSession`
   directly (not via `async with`) and called `session.get()` with no
   try/except -- if `session.get()` itself raised (timeout, connection
   reset, DNS failure before headers came back), the session was never
   closed and leaked until Python's GC finalized it, which is when aiohttp
   emitted its "Unclosed connector" warning (Sentry PYTHON-FASTAPI-V/
   PYTHON-FASTAPI-S, 2026-08-20/21).

2. `app/main.py`'s `_proxy_to_archive()` -> `body_iterator()` had only a
   `finally` to close the session -- no try/except around the streaming
   loop itself, so a cut-short upstream response (aiohttp's own
   TransferEncodingError/ClientPayloadError) propagated unhandled *after*
   StreamingResponse had already committed to a response (Sentry
   PYTHON-FASTAPI-Q, 2026-08-18).

Both are exercised here with a fake aiohttp session/response rather than a
real network call -- the thing under test is this repo's own exception
handling, not aiohttp's or a real Archive instance's behavior.
"""

import aiohttp
import pytest
from fastapi.testclient import TestClient

import app.archive_client as archive_client
import app.main

app_client = TestClient(app.main.app)


# --- proxy_get() closes its session when session.get() raises -----------


class _RaisingSession:
    """Stands in for aiohttp.ClientSession: .get() raises before headers
    come back, mirroring a real timeout/connection-reset/DNS failure."""

    def __init__(self, *args, **kwargs):
        self.closed = False

    async def get(self, url, headers=None):
        raise aiohttp.ClientConnectionError("simulated connection failure")

    async def close(self):
        self.closed = True


async def test_proxy_get_closes_session_when_session_get_raises(monkeypatch):
    monkeypatch.setenv("ARCHIVE_BASE_URL", "https://archive.example.test")
    created_sessions = []

    def _fake_session_factory(*args, **kwargs):
        session = _RaisingSession()
        created_sessions.append(session)
        return session

    monkeypatch.setattr(archive_client.aiohttp, "ClientSession", _fake_session_factory)

    with pytest.raises(aiohttp.ClientConnectionError):
        await archive_client.proxy_get("meetings", "")

    assert len(created_sessions) == 1
    assert created_sessions[0].closed is True


# --- _proxy_to_archive()'s body_iterator() survives a cut-short stream --


class _FakeContent:
    def __init__(self, chunks, error):
        self._chunks = chunks
        self._error = error

    def iter_chunked(self, size):
        return self._iterate()

    async def _iterate(self):
        for chunk in self._chunks:
            yield chunk
        if self._error:
            raise self._error


class _FakeResponse:
    def __init__(self, chunks, error, status=200):
        self.content = _FakeContent(chunks, error)
        self.status = status
        self.headers = {"Content-Type": "text/plain"}


class _FakeSession:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


async def test_proxy_to_archive_stream_cut_short_ends_cleanly(monkeypatch):
    # A real occurrence (Sentry PYTHON-FASTAPI-Q) raised
    # aiohttp.ClientPayloadError partway through the body -- the fix must
    # let the generator end instead of raising into StreamingResponse's
    # already-committed response.
    fake_session = _FakeSession()
    fake_response = _FakeResponse(
        chunks=[b"partial "],
        error=aiohttp.ClientPayloadError("Response payload is not completed"),
    )

    async def _fake_proxy_get(
        internal_path, query_string, cookie_header=None, extra_headers=None
    ):
        return fake_session, fake_response

    monkeypatch.setattr(app.main.archive_client, "proxy_get", _fake_proxy_get)

    response = app_client.get("/m/some-slug")
    assert response.status_code == 200
    assert response.content == b"partial "
    assert fake_session.closed is True


async def test_proxy_to_archive_stream_completes_normally(monkeypatch):
    fake_session = _FakeSession()
    fake_response = _FakeResponse(chunks=[b"hello ", b"world"], error=None)

    async def _fake_proxy_get(
        internal_path, query_string, cookie_header=None, extra_headers=None
    ):
        return fake_session, fake_response

    monkeypatch.setattr(app.main.archive_client, "proxy_get", _fake_proxy_get)

    response = app_client.get("/m/some-slug")
    assert response.status_code == 200
    assert response.content == b"hello world"
    assert fake_session.closed is True


# --- conditional-request forwarding (WO-28) -----------------------------


class _EmptyChunkIter:
    async def iter_chunked(self, _size):
        return
        yield


def test_m_route_forwards_if_none_match_but_static_does_not(monkeypatch):
    """/m/{slug}/card.jpg is the first proxied route that returns a real
    ETag, so a client's If-None-Match has to reach the Archive or a 304
    can never happen through the public domain -- Googlebot and every
    social scraper would re-stream the full image through two services on
    each refetch. Deliberately opt-in per call site (like cookie_header),
    so the static-asset route keeps sending nothing extra."""
    captured = []

    async def _fake_proxy_get(
        path, query_string, cookie_header=None, extra_headers=None
    ):
        captured.append((path, extra_headers))

        class _FakeResponse:
            status = 200
            headers = {}
            content = _EmptyChunkIter()

        class _FakeSession:
            async def close(self):
                pass

        return _FakeSession(), _FakeResponse()

    monkeypatch.setattr(app.main.archive_client, "proxy_get", _fake_proxy_get)

    app_client.get("/m/some-slug/card.jpg", headers={"If-None-Match": '"abc"'})
    app_client.get("/m/some-slug")
    app_client.get("/archive-static/style.css", headers={"If-None-Match": '"abc"'})

    assert captured[0] == ("m/some-slug/card.jpg", {"If-None-Match": '"abc"'})
    # No header on the request -> nothing invented.
    assert captured[1] == ("m/some-slug", None)
    assert captured[2] == ("static/style.css", None)


# --- a schemeless ARCHIVE_BASE_URL is a config error, not a request ------
#
# Third bug in the same proxy path, confirmed live 2026-08-22 (Sentry
# PYTHON-FASTAPI-Y): ARCHIVE_BASE_URL was set to a bare `rtr-deeplink-
# archive:10000`, and `proxy_get()` handed that straight to aiohttp, which
# raised NonHttpUrlClientError from deep inside the request -- once per
# proxied page view, across `/coverage`, `/meetings` and
# `/archive-static/*`. The variable is `sync: false` in render.yaml
# (dashboard-managed), so nothing in the repo constrains its shape.


def test_base_url_rejects_a_value_with_no_scheme(monkeypatch):
    monkeypatch.setenv("ARCHIVE_BASE_URL", "rtr-deeplink-archive:10000")

    assert archive_client._base_url() == ""
    problem = archive_client.configuration_problem()
    assert problem is not None
    assert "rtr-deeplink-archive:10000" in problem
    assert "scheme" in problem


@pytest.mark.parametrize(
    "value",
    [
        "https://rtr-deeplink-archive.onrender.com",
        "https://rtr-deeplink-archive.onrender.com/",
        "http://rtr-deeplink-archive:10000",
        "  https://rtr-deeplink-archive.onrender.com  ",
    ],
)
def test_base_url_accepts_real_shapes_including_the_internal_address(
    monkeypatch, value
):
    """The internal `http://host:port` form matters specifically: pointing
    ARCHIVE_BASE_URL at Render's internal address is the next planned
    change to this variable (BACKLOG.md's bandwidth entry), and it must
    not be mistaken for the malformed shape above."""
    monkeypatch.setenv("ARCHIVE_BASE_URL", value)

    assert archive_client.configuration_problem() is None
    assert archive_client._base_url() == value.strip().rstrip("/")


def test_unset_base_url_is_a_valid_configuration_not_a_problem(monkeypatch):
    """Local development with no Archive is legitimate, and every caller
    in archive_client already degrades correctly on "" -- a misconfigured
    Archive must never block a live resolve."""
    monkeypatch.delenv("ARCHIVE_BASE_URL", raising=False)

    assert archive_client.configuration_problem() is None
    assert archive_client._base_url() == ""


async def test_proxy_get_raises_a_named_error_for_a_schemeless_base_url(monkeypatch):
    """The value of the fix: a named RuntimeError this repo raises itself,
    rather than aiohttp's NonHttpUrlClientError from inside the request."""
    monkeypatch.setenv("ARCHIVE_BASE_URL", "rtr-deeplink-archive:10000")

    with pytest.raises(RuntimeError, match="ARCHIVE_BASE_URL"):
        await archive_client.proxy_get("coverage", "")
