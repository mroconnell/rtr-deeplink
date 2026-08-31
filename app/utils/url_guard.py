"""SSRF guard for URLs this app fetches on a caller's behalf.

`/api/resolve` takes a bare, unauthenticated URL and (for anything that
isn't a known platform) hands it to `generic_fallback.py`, which does a
plain `aiohttp` GET with `allow_redirects=True` and, in production
(`GENERIC_FALLBACK_HEADLESS=1`), can escalate to a real headless browser.
Nothing validated the destination -- a POST of
`http://169.254.169.254/latest/meta-data/...` or an internal hostname was
fetched from inside the network, with the response returned in the
resolve payload. See AUDIT_2026-08-14.md finding #2 / BACKLOG.md's SSRF
entry.

`check_destination()` is the one thing every caller needs: scheme +
resolved-IP validation. It must be called again on every redirect hop, not
just the first URL -- a permitted host can 302 to a private one, and
re-checking only the entry URL misses that entirely (this is the gap
`guarded_get()` below closes for generic_fallback.py's own fetches).
"""

import asyncio
import ipaddress
import socket
from typing import List, Union
from urllib.parse import urljoin, urlparse

_IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

_ALLOWED_SCHEMES = {"http", "https"}

# Cap on redirect hops guarded_get() will follow, each one re-validated.
# Matches the spirit of aiohttp's own default (10) without being generous
# about it -- this app has no legitimate reason to need a long chain.
MAX_REDIRECTS = 5

# Generous for an HTML page or a caption file, well short of a real
# resource-exhaustion concern. A response larger than this is truncated
# read-side, never buffered in full first.
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class BlockedURLError(ValueError):
    """A URL failed the SSRF guard. The message is written to be shown
    directly to a caller -- never wraps or repeats the underlying
    exception, so a rejected destination can't leak internal detail."""


def _resolve_hostname(hostname: str) -> List[str]:
    """Real DNS resolution, factored out to its own function so tests can
    monkeypatch it without touching the network -- see
    test_generic_fallback.py's `_fake_public_dns` autouse fixture. Blocking
    (uses the stdlib resolver); callers run it off the event loop."""
    infos = socket.getaddrinfo(hostname, None)
    return [info[4][0] for info in infos]


def _is_blocked_ip(ip: _IPAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def check_scheme(url: str) -> str:
    """Validates scheme and extracts the hostname -- the cheap, sync half
    of the guard. Raises BlockedURLError on anything but http/https or a
    URL with no host. Returns the hostname for callers that want it."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise BlockedURLError(
            f"Only http/https URLs are supported (got '{parsed.scheme or 'no scheme'}')."
        )
    if not parsed.hostname:
        raise BlockedURLError("That doesn't look like a valid URL.")
    return parsed.hostname


async def check_destination(url: str) -> None:
    """Full guard: scheme + hostname resolution + private/internal IP
    rejection. Call before EVERY fetch this app makes to a caller-
    influenced URL, including each redirect hop.

    A literal IP in the URL (including a redirect Location header, which
    is the case that matters most) is classified directly, with no DNS
    involved. A hostname is resolved via the stdlib resolver, off the
    event loop, and every returned address is checked -- a multi-A-record
    host is blocked if *any* record resolves somewhere disallowed.
    """
    hostname = check_scheme(url)
    try:
        # urlparse().hostname already strips IPv6 brackets, so a literal
        # `http://169.254.169.254/...` or `http://[::1]/...` lands here
        # with no DNS involved at all.
        candidates = [ipaddress.ip_address(hostname)]
    except ValueError:
        loop = asyncio.get_event_loop()
        try:
            raw_ips = await loop.run_in_executor(None, _resolve_hostname, hostname)
        except (socket.gaierror, UnicodeError) as e:
            # UnicodeError alongside gaierror: getaddrinfo()'s IDNA
            # encoding raises this (not gaierror) for a hostname with a
            # single DNS label over 63 octets -- confirmed live via
            # Sentry PYTHON-FASTAPI-15, a 74-character slug-shaped string
            # sent to /api/refresh-archived-page, which 500'd instead of
            # getting this same clean rejection.
            raise BlockedURLError("Couldn't resolve that host.") from e
        if not raw_ips:
            raise BlockedURLError("Couldn't resolve that host.")
        candidates = [ipaddress.ip_address(raw) for raw in raw_ips]

    for ip in candidates:
        if _is_blocked_ip(ip):
            raise BlockedURLError(
                "That URL resolves to a private or internal address, which isn't allowed."
            )


def _check_content_length(response, max_bytes: int) -> None:
    """Cheap short-circuit shared by read_capped_text/read_capped_bytes --
    that header is caller-supplied and not trusted alone, so both callers
    also check the real decoded/read length regardless of what it claims."""
    content_length = response.headers.get("Content-Length")
    if content_length is None:
        return
    try:
        declared = int(content_length)
    except (TypeError, ValueError):
        return
    if declared > max_bytes:
        raise BlockedURLError("Response too large.")


async def read_capped_text(response, max_bytes: int = MAX_RESPONSE_BYTES) -> str:
    """`await response.text()`, but rejects a body over `max_bytes`
    instead of handing an unbounded page to the HTML parser. Not a true
    streaming abort (aiohttp's own `.text()` still buffers the response
    first); the per-request `ClientTimeout` already bounds worst-case
    latency, and this bounds worst-case memory for what gets returned/
    parsed."""
    _check_content_length(response, max_bytes)
    body = await response.text()
    if len(body.encode("utf-8", errors="ignore")) > max_bytes:
        raise BlockedURLError("Response too large.")
    return body


async def read_capped_bytes(response, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """`await response.read()`, but rejects a body over `max_bytes` -- the
    raw-bytes counterpart to read_capped_text(), used for caption fetches
    that need the undecoded body."""
    _check_content_length(response, max_bytes)
    raw = await response.read()
    if len(raw) > max_bytes:
        raise BlockedURLError("Response too large.")
    return raw


class guarded_get:
    """Drop-in replacement for `async with session.get(url, allow_redirects=True, ...)`
    that re-validates the destination on every redirect hop instead of
    trusting aiohttp's own follow. `allow_redirects` (if passed) is
    ignored -- redirects are always followed manually, up to
    MAX_REDIRECTS, so each hop gets checked before the connection is made.

    Usage is identical to the pattern it replaces:

        async with guarded_get(session, url, timeout=...) as response:
            body = await response.text()
    """

    def __init__(self, session, url: str, **kwargs):
        self._session = session
        self._url = url
        kwargs.pop("allow_redirects", None)
        self._kwargs = kwargs
        self._cm = None

    async def __aenter__(self):
        current = self._url
        for hop in range(MAX_REDIRECTS + 1):
            await check_destination(current)
            cm = self._session.get(current, allow_redirects=False, **self._kwargs)
            response = await cm.__aenter__()
            location = (
                response.headers.get("Location")
                if response.status in _REDIRECT_STATUSES
                else None
            )
            if not location:
                # Not a redirect, or a redirect with no Location to follow
                # -- either way, nothing left to do but hand it back.
                self._cm = cm
                return response
            await cm.__aexit__(None, None, None)
            current = urljoin(current, location)
        raise BlockedURLError("Too many redirects.")

    async def __aexit__(self, exc_type, exc, tb):
        if self._cm is not None:
            return await self._cm.__aexit__(exc_type, exc, tb)
        return False
