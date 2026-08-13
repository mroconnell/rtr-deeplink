"""Minimal aiohttp.ClientSession.get() mock for adapter tests.

`aioresponses` (latest release 0.7.9) doesn't support the aiohttp version
this project's unpinned `aiohttp>=3.9` requirement resolves to today
(3.14.3) -- its `_build_response` doesn't pass the now-required
`stream_writer` kwarg into `ClientResponse.__init__`. Rather than pin the
app's real dependency down just to satisfy a mocking library, this routes
`session.get(url, ...)` calls to canned `FakeResponse`s by exact URL
(query string included), which is all every adapter here actually needs.
"""

from contextlib import contextmanager
from unittest import mock

import aiohttp


class FakeResponse:
    def __init__(
        self, status: int = 200, text: str = "", raw: bytes = None, url: str = None,
        text_raises: Exception = None,
    ):
        self.status = status
        self._text = text
        self._raw = raw if raw is not None else text.encode("utf-8")
        self.url = url if url is not None else ""
        # Simulates a 200 response whose body isn't decodable as text (e.g.
        # a redirect straight to a binary PDF) -- real aiohttp raises
        # UnicodeDecodeError from .text() in that case, not from .get().
        self._text_raises = text_raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        if self._text_raises:
            raise self._text_raises
        return self._text

    async def read(self):
        return self._raw

    async def json(self, content_type=None):
        # `content_type` accepted (and ignored, same as real aiohttp when
        # passed `content_type=None`) so a caller can skip real aiohttp's
        # Content-Type-header check -- champds.py needs this since the
        # real ChampDS API serves its JSON as `text/html` (confirmed
        # live), not `application/json`.
        import json as _json
        return _json.loads(self._text)

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=mock.Mock(), history=(), status=self.status,
            )


@contextmanager
def mock_session(routes: dict):
    """routes: {url: FakeResponse}. url defaults to response.url == the
    request url unless the FakeResponse was built with a different `url`
    (simulating a redirect)."""

    def fake_get(self, url, **kwargs):
        key = str(url)
        if key not in routes:
            raise AssertionError(f"Unmocked request in test: {key}\nKnown routes: {sorted(routes)}")
        response = routes[key]
        if not response.url:
            response.url = key
        return response

    with mock.patch.object(aiohttp.ClientSession, "get", fake_get):
        yield
