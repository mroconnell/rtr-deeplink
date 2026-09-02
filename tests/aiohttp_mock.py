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
        self,
        status: int = 200,
        text: str = "",
        raw: bytes = None,
        url: str = None,
        text_raises: Exception = None,
        headers: dict = None,
        encoding: str = "utf-8",
    ):
        self.status = status
        self._text = text
        self._raw = raw if raw is not None else text.encode("utf-8")
        self.url = url if url is not None else ""
        # aiohttp's own guessed encoding (from Content-Type/chardet) --
        # `read_capped_text()` (app/utils/url_guard.py) reads this after
        # `.read()`, same as real aiohttp. Defaults to "utf-8" as real
        # aiohttp does when nothing more specific is detectable.
        self._encoding = encoding
        # Simulates a 200 response whose body isn't decodable as text (e.g.
        # a redirect straight to a binary PDF) -- real aiohttp raises
        # UnicodeDecodeError from .text() in that case, not from .get().
        self._text_raises = text_raises
        # Real aiohttp headers are case-insensitive; a plain dict is fine
        # for the two things tests actually need out of it so far
        # (Location on a redirect, Content-Length for url_guard.py's size
        # cap) -- exact-case lookups only, unlike the real CIMultiDict.
        self.headers = headers if headers is not None else {}

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

    def get_encoding(self):
        return self._encoding

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
                request_info=mock.Mock(),
                history=(),
                status=self.status,
            )


@contextmanager
def mock_session(routes: dict, post_routes: dict = None):
    """routes: {url: FakeResponse}. url defaults to response.url == the
    request url unless the FakeResponse was built with a different `url`
    (simulating a redirect).

    post_routes: same shape, for `session.post(url, ...)` calls -- added
    for castus.py (WO-19), the first adapter here that needs a POST (its
    real `/upload/info` endpoint takes no GET form at all, confirmed live:
    a plain GET returns "Cannot GET /upload/info"). Kept as a separate,
    optional dict rather than folding into `routes` so every existing
    GET-only adapter test is unaffected -- `session.post()` is only
    patched (and only raises on an unmocked call) when a caller actually
    passes some.
    """

    def fake_get(self, url, **kwargs):
        key = str(url)
        if key not in routes:
            raise AssertionError(
                f"Unmocked request in test: {key}\nKnown routes: {sorted(routes)}"
            )
        response = routes[key]
        if not response.url:
            response.url = key
        return response

    def fake_post(self, url, **kwargs):
        key = str(url)
        if key not in (post_routes or {}):
            raise AssertionError(
                f"Unmocked POST in test: {key}\nKnown POST routes: {sorted(post_routes or {})}"
            )
        response = post_routes[key]
        if not response.url:
            response.url = key
        return response

    with mock.patch.object(aiohttp.ClientSession, "get", fake_get):
        if post_routes is not None:
            with mock.patch.object(aiohttp.ClientSession, "post", fake_post):
                yield
        else:
            yield
