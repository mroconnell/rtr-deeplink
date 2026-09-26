"""WO-913 (2026-09-20): `scripts/youtube_fetch_guard.py` refuses every YouTube
hostname lookup, on every route the ingest path can take.

The real incident: a hand-confirmed CivicClerk find (Toledo OR) had a
YouTube embed as its media, and WO-134's standard resolve + WO-144 probe made
about two YouTube requests from a machine that must make none (CLAUDE.md:
YouTube is the drip Mac's job). These tests pin the fix.

Every test is network-free, including if the guard were broken: each installs
a TRIPWIRE under the guard first (the resolver the guard wraps raises
AssertionError for a YouTube host), so a regression fails the test instead of
sending a request. The aiohttp test uses a local server that redirects to
YouTube -- the redirect hop is the case a URL check on the first request would
miss, and this repo's aiohttp uses c-ares (`aiodns`), so patching
`socket.getaddrinfo` alone would not have caught it.
"""

import socket

import aiohttp
import pytest
from aiohttp import connector, web
from aiohttp.test_utils import TestServer

import scripts.youtube_fetch_guard as guard


@pytest.fixture
def armed_guard(monkeypatch):
    """The guard installed over tripwires, with all global state restored."""

    def tripwire_getaddrinfo(host, *args, **kwargs):
        assert not guard.is_youtube_host(host), f"REAL lookup reached: {host}"
        return real_getaddrinfo(host, *args, **kwargs)

    real_getaddrinfo = socket.getaddrinfo
    real_resolve_host = connector.TCPConnector._resolve_host

    async def tripwire_resolve_host(self, host, port, traces=None):
        assert not guard.is_youtube_host(host), f"REAL aiohttp lookup reached: {host}"
        return await real_resolve_host(self, host, port, traces)

    monkeypatch.setattr(socket, "getaddrinfo", tripwire_getaddrinfo)
    monkeypatch.setattr(connector.TCPConnector, "_resolve_host", tripwire_resolve_host)
    monkeypatch.setattr(guard, "_installed", False)
    monkeypatch.setattr(guard, "REFUSED", [])
    guard.install()
    return guard


@pytest.mark.parametrize(
    "host",
    [
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtube-nocookie.com",
        "youtubei.googleapis.com",
        "i.ytimg.com",
        "rr1---sn-abc123.googlevideo.com",
        "yt3.ggpht.com",
        "WWW.YOUTUBE.COM",
        b"www.youtube.com",
    ],
)
def test_youtube_hosts_are_recognised(host):
    assert guard.is_youtube_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "example.com",
        "toledoor.portal.civicclerk.com",
        "cpmedia.azureedge.net",
        "vimeo.com",
        "townofgeorgetown.ompnetwork.org",
        "play.champds.com",
        "",
        None,
    ],
)
def test_other_hosts_are_not_touched(host):
    assert not guard.is_youtube_host(host)


def test_stdlib_resolver_refuses_youtube_and_still_resolves_others(armed_guard):
    with pytest.raises(guard.YouTubeFetchRefused, match="drip Mac"):
        socket.getaddrinfo("www.youtube.com", 443)
    with pytest.raises(OSError):  # a YouTubeFetchRefused IS an OSError
        socket.getaddrinfo("youtu.be", 443)
    assert socket.getaddrinfo("localhost", 80)
    assert armed_guard.REFUSED == ["www.youtube.com", "youtu.be"]


async def test_aiohttp_refuses_a_redirect_hop_to_youtube(armed_guard):
    """The first request goes to a local server (allowed); its 302 to
    youtube.com is the hop that must be refused."""

    async def to_youtube(request):
        raise web.HTTPFound("http://www.youtube.com/watch?v=jNQXAC9IVRw")

    app = web.Application()
    app.router.add_get("/", to_youtube)
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientConnectorError):
                await session.get(server.make_url("/"))
    assert armed_guard.REFUSED == ["www.youtube.com"]


async def test_aiohttp_still_reaches_a_non_youtube_host(armed_guard):
    async def ok(request):
        return web.Response(text="fine")

    app = web.Application()
    app.router.add_get("/", ok)
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as session:
            async with session.get(server.make_url("/")) as resp:
                assert resp.status == 200
                assert await resp.text() == "fine"
    assert armed_guard.REFUSED == []


@pytest.mark.real_yt_dlp
def test_yt_dlp_metadata_call_is_refused_before_any_connection(armed_guard):
    """The WO-144 queue probe's route: yt-dlp asking YouTube for metadata.

    Opted out of conftest.py's yt-dlp refusal, because the real call is
    what this test is about. `"proxy": ""` makes yt-dlp connect directly:
    through an HTTPS proxy it never looks the host up itself, so the guard
    never sees it and the call reaches YouTube (WO-1084, found in a cloud
    container with a proxy -- the guard's own gap there is a BACKLOG.md
    entry)."""
    yt_dlp = pytest.importorskip("yt_dlp")
    opts = {
        "proxy": "",
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 2,
        "retries": 0,
        "extractor_retries": 0,
    }
    with pytest.raises(yt_dlp.utils.DownloadError, match="YouTube host"):
        yt_dlp.YoutubeDL(opts).extract_info(
            "https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False
        )
    assert armed_guard.REFUSED
    assert all(guard.is_youtube_host(h) for h in armed_guard.REFUSED)


def test_install_is_idempotent(armed_guard):
    before = socket.getaddrinfo
    armed_guard.install()
    assert socket.getaddrinfo is before
