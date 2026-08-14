"""Tests for the SSRF guard (WO-5, AUDIT_2026-08-14.md finding #2):
app/utils/url_guard.py, its wiring into /api/resolve, and its wiring into
generic_fallback.py's own fetches (including the redirect-to-private-IP
case, and the headless escalation -- see test_headless_browser.py for
that last one).

All private/loopback/link-local/etc. cases below use literal IP
addresses, not domain names -- check_destination() classifies a literal
IP directly with no DNS involved, keeping this hermetic. The one
DNS-resolution path (a plain hostname) is exercised separately with
_resolve_hostname() monkeypatched, same as
test_generic_fallback.py's `_fake_public_dns` fixture does for the
adapter-level tests.
"""

import socket

import pytest
from fastapi.testclient import TestClient

import app.main
from app.utils import url_guard
from app.utils.url_guard import BlockedURLError, check_destination, check_scheme, guarded_get, read_capped_bytes, read_capped_text

from aiohttp_mock import FakeResponse, mock_session

client = TestClient(app.main.app)


# --- check_scheme: cheap sync half ----------------------------------------

def test_rejects_non_http_scheme():
    with pytest.raises(BlockedURLError):
        check_scheme("file:///etc/passwd")


def test_rejects_ftp_scheme():
    with pytest.raises(BlockedURLError):
        check_scheme("ftp://example.com/file")


def test_rejects_url_with_no_hostname():
    with pytest.raises(BlockedURLError):
        check_scheme("http:///no-host-here")


def test_accepts_http_and_https():
    assert check_scheme("http://example.com/") == "example.com"
    assert check_scheme("https://example.com/") == "example.com"


# --- check_destination: literal-IP classification (no DNS) ----------------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://127.0.0.1:8080/admin",
    "http://[::1]/",
])
async def test_rejects_loopback(url):
    with pytest.raises(BlockedURLError):
        await check_destination(url)


@pytest.mark.parametrize("url", [
    "http://10.0.0.5/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
])
async def test_rejects_private_ranges(url):
    with pytest.raises(BlockedURLError):
        await check_destination(url)


async def test_rejects_link_local_including_cloud_metadata_endpoint():
    # 169.254.169.254 -- the AWS/GCP/Azure instance-metadata address and
    # the canonical real-world SSRF target named in the audit finding.
    with pytest.raises(BlockedURLError):
        await check_destination("http://169.254.169.254/latest/meta-data/")


async def test_rejects_multicast():
    with pytest.raises(BlockedURLError):
        await check_destination("http://224.0.0.1/")


async def test_rejects_unspecified_address():
    with pytest.raises(BlockedURLError):
        await check_destination("http://0.0.0.0/")


async def test_rejects_reserved_range():
    # 240.0.0.0/4 -- IANA reserved, never a legitimate real-world target.
    with pytest.raises(BlockedURLError):
        await check_destination("http://240.0.0.1/")


async def test_allows_a_public_ip():
    # Literal public IP, not a domain -- exercises the "allowed" path
    # with no DNS involved either.
    await check_destination("http://93.184.216.34/")  # does not raise


# --- check_destination: hostname resolution path ---------------------------

async def test_rejects_a_hostname_that_resolves_to_a_private_address(monkeypatch):
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["10.0.0.9"])
    with pytest.raises(BlockedURLError):
        await check_destination("http://internal.example.corp/")


async def test_allows_a_hostname_that_resolves_to_a_public_address(monkeypatch):
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"])
    await check_destination("http://some-city.example.gov/meeting")  # does not raise


async def test_blocked_if_any_resolved_address_is_private(monkeypatch):
    # A multi-A-record host is blocked if ANY record resolves somewhere
    # disallowed, not only if all of them do.
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34", "127.0.0.1"])
    with pytest.raises(BlockedURLError):
        await check_destination("http://mixed.example.com/")


async def test_dns_failure_raises_a_clean_error(monkeypatch):
    def _raise(hostname):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr(url_guard, "_resolve_hostname", _raise)
    with pytest.raises(BlockedURLError):
        await check_destination("http://this-host-does-not-resolve.invalid/")


# --- guarded_get: redirect-hop re-validation --------------------------------
# The case the brief calls out as "the one people forget": a URL that
# passes the guard can still 302 to a private one, and re-checking only
# the entry URL misses that entirely.

async def test_guarded_get_follows_an_allowed_redirect_chain(monkeypatch):
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"])
    routes = {
        "http://a.example.com/": FakeResponse(
            status=302, headers={"Location": "http://b.example.com/"}, url="http://a.example.com/",
        ),
        "http://b.example.com/": FakeResponse(status=200, text="final page", url="http://b.example.com/"),
    }
    import aiohttp

    with mock_session(routes):
        async with aiohttp.ClientSession() as session:
            async with guarded_get(session, "http://a.example.com/") as response:
                assert response.status == 200
                assert await response.text() == "final page"


async def test_guarded_get_rejects_a_redirect_to_a_private_ip(monkeypatch):
    # Deliberately does NOT register a route for the private target below
    # -- if guarded_get ever actually issued that second request instead
    # of blocking it first, mock_session's own "unmocked request" assertion
    # would fail this test, not just the BlockedURLError expectation.
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"])
    routes = {
        "http://a.example.com/": FakeResponse(
            status=302, headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            url="http://a.example.com/",
        ),
    }
    import aiohttp

    with mock_session(routes):
        async with aiohttp.ClientSession() as session:
            with pytest.raises(BlockedURLError):
                async with guarded_get(session, "http://a.example.com/"):
                    pass


async def test_guarded_get_caps_redirect_chain_length(monkeypatch):
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"])
    # One more hop than MAX_REDIRECTS allows, each redirecting to the next.
    routes = {}
    for i in range(url_guard.MAX_REDIRECTS + 2):
        routes[f"http://hop{i}.example.com/"] = FakeResponse(
            status=302, headers={"Location": f"http://hop{i + 1}.example.com/"},
            url=f"http://hop{i}.example.com/",
        )
    import aiohttp

    with mock_session(routes):
        async with aiohttp.ClientSession() as session:
            with pytest.raises(BlockedURLError):
                async with guarded_get(session, "http://hop0.example.com/"):
                    pass


async def test_guarded_get_ignores_allow_redirects_kwarg(monkeypatch):
    # allow_redirects=True is a no-op -- guarded_get always follows
    # redirects itself so it can re-validate each hop.
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"])
    routes = {"http://plain.example.com/": FakeResponse(status=200, text="ok", url="http://plain.example.com/")}
    import aiohttp

    with mock_session(routes):
        async with aiohttp.ClientSession() as session:
            async with guarded_get(session, "http://plain.example.com/", allow_redirects=True) as response:
                assert await response.text() == "ok"


# --- response size cap ------------------------------------------------------

async def test_read_capped_text_rejects_an_oversized_content_length_header():
    response = FakeResponse(status=200, text="small body", headers={"Content-Length": str(50 * 1024 * 1024)})
    with pytest.raises(BlockedURLError):
        await read_capped_text(response, max_bytes=1024)


async def test_read_capped_text_rejects_an_oversized_body_with_no_content_length_header():
    response = FakeResponse(status=200, text="x" * 2000)
    with pytest.raises(BlockedURLError):
        await read_capped_text(response, max_bytes=1024)


async def test_read_capped_text_allows_a_body_under_the_cap():
    response = FakeResponse(status=200, text="small body")
    assert await read_capped_text(response, max_bytes=1024) == "small body"


async def test_read_capped_bytes_rejects_an_oversized_body():
    response = FakeResponse(status=200, raw=b"x" * 2000)
    with pytest.raises(BlockedURLError):
        await read_capped_bytes(response, max_bytes=1024)


async def test_read_capped_bytes_allows_a_body_under_the_cap():
    response = FakeResponse(status=200, raw=b"small body")
    assert await read_capped_bytes(response, max_bytes=1024) == b"small body"


# --- /api/resolve entrypoint -------------------------------------------------
# The guard runs before any archive/DB lookup, so a rejected URL never
# reaches that machinery -- no mocking needed for these, unlike a normal
# resolve.

def test_resolve_endpoint_rejects_link_local_metadata_url():
    response = client.post("/api/resolve", json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert response.status_code == 200  # a clean, handled rejection -- not a 500
    body = response.json()
    assert body["error"] == "blocked_url"
    assert "Traceback" not in body["message"]


def test_resolve_endpoint_rejects_a_private_ip():
    response = client.post("/api/resolve", json={"url": "http://10.0.0.5/"})
    assert response.json()["error"] == "blocked_url"


def test_resolve_endpoint_rejects_a_non_http_scheme():
    response = client.post("/api/resolve", json={"url": "file:///etc/passwd"})
    assert response.status_code == 200
    assert response.json()["error"] == "blocked_url"


def test_resolve_endpoint_rejects_localhost():
    response = client.post("/api/resolve", json={"url": "http://127.0.0.1:6379/"})
    assert response.json()["error"] == "blocked_url"
