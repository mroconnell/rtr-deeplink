"""In-process guard: refuse to look up any YouTube hostname.

CLAUDE.md and `docs/YOUTUBE_DRIP_RUNBOOK.md`: every YouTube request comes from
the drip Mac (`scripts/youtube_drip.py`), because the office shares one
address and YouTube blocks it after a few dozen requests. A sweep or ingest
run from any other machine must make ZERO YouTube requests -- including the
indirect ones: a CivicClerk (or Legistar/CivicPlus/Granicus/PrimeGov) event
whose media is a YouTube embed makes the adapter fetch YouTube captions, the
WO-144 queue probe calls yt-dlp for its metadata, and WO-134's title check
calls YouTube's oEmbed. None of those look like "a YouTube fetch" in the
calling script; all of them end in a hostname lookup. WO-913 (2026-09-20)
hit exactly this: one hand-confirmed CivicClerk find (Toledo OR) had a
YouTube embed, and the standard ingest path made about two YouTube requests
(one metadata probe, one caption fetch) from a machine that must not.

This makes the rule a property of the process instead of a hope:
`install()` makes any lookup of a YouTube hostname raise `YouTubeFetchRefused`
(an `OSError`), before any connection is attempted. It guards
  - the standard-library resolver (`socket.getaddrinfo`), which yt-dlp,
    urllib, requests and httpx all end up in; and
  - aiohttp's connector (`TCPConnector._resolve_host`), separately, because
    this repo's aiohttp uses c-ares (`aiodns`) and never touches
    `socket.getaddrinfo`. That is the single entry point for every aiohttp
    connection, redirect hops included.
A refusal surfaces as an ordinary fetch error in whatever called it, so a row
fails or is skipped rather than the run crashing; `REFUSED` records each
refused host so a caller can tell which rows needed YouTube.

Behind an HTTPS proxy (`HTTPS_PROXY`, as in every cloud session) a client
asks the proxy to connect and never looks the host up itself, so neither
hook above would see it. `install()` therefore also adds YouTube's domains
to `NO_PROXY`/`no_proxy`: yt-dlp, urllib, requests, httpx and aiohttp
(`trust_env=True`) then connect to them directly, which goes through the
lookup the guard refuses (found 2026-09-26, WO-1082/WO-1090). A caller that
passes an explicit proxy option (yt-dlp's `proxy`, aiohttp's `proxy=`)
bypasses the environment and is not covered.

It does not (and cannot) guard a separate browser process such as Playwright's
Chromium; a script that drives one must refuse YouTube URLs itself, as
`wo912_headless_second_opinion.py` does.

Usage:
    from scripts.youtube_fetch_guard import install
    install()          # before any resolve/probe/ingest call
"""

from __future__ import annotations

import os
import socket
from typing import List

# Substrings, not exact hosts: "youtube" alone also covers youtube-nocookie.com
# and youtubei.googleapis.com (the innertube API host, which has no ".com" after
# "youtube"). ytimg/ggpht/googlevideo are YouTube's own thumbnail, avatar and
# video-delivery domains.
YOUTUBE_HOST_MARKERS = (
    "youtube",
    "youtu.be",
    "googlevideo.com",
    "ytimg.com",
    "ggpht.com",
)

# Every host this process was refused, in order, for the caller to report.
REFUSED: List[str] = []

_installed = False

# NO_PROXY entries for the hosts above. NO_PROXY matches a domain and its
# subdomains, not a substring, so the markers are spelled out as domains.
YOUTUBE_NO_PROXY_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "youtubei.googleapis.com",
    "googlevideo.com",
    "ytimg.com",
    "ggpht.com",
)


class YouTubeFetchRefused(OSError):
    """Raised instead of resolving a YouTube hostname."""


def is_youtube_host(host: object) -> bool:
    text = (
        host.decode("ascii", "ignore") if isinstance(host, bytes) else str(host or "")
    )
    text = text.lower()
    return any(marker in text for marker in YOUTUBE_HOST_MARKERS)


def _refuse(host: object) -> None:
    name = host.decode("ascii", "ignore") if isinstance(host, bytes) else str(host)
    REFUSED.append(name)
    raise YouTubeFetchRefused(
        f"refused: {name} is a YouTube host; YouTube is fetched only by the "
        "drip Mac (CLAUDE.md)"
    )


def _bypass_proxy_for_youtube() -> None:
    """Adds YouTube's domains to NO_PROXY and no_proxy (both spellings:
    Python reads the lowercase one first), so a proxied client connects to
    them directly and its own lookup reaches the guarded resolver."""
    current = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    entries = [e.strip() for e in current.split(",") if e.strip()]
    if "*" in entries:
        return
    for domain in YOUTUBE_NO_PROXY_DOMAINS:
        if domain not in entries:
            entries.append(domain)
    merged = ",".join(entries)
    os.environ["no_proxy"] = merged
    os.environ["NO_PROXY"] = merged


def install() -> None:
    """Idempotent. Safe to call before or after aiohttp is imported."""
    global _installed
    if _installed:
        return
    _installed = True

    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        if is_youtube_host(host):
            _refuse(host)
        return real_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = guarded_getaddrinfo

    _bypass_proxy_for_youtube()

    try:
        from aiohttp import connector
    except ImportError:  # pragma: no cover -- aiohttp is a hard dependency here
        return

    real_resolve_host = connector.TCPConnector._resolve_host

    async def guarded_resolve_host(self, host, port, traces=None):
        if is_youtube_host(host):
            _refuse(host)
        return await real_resolve_host(self, host, port, traces)

    connector.TCPConnector._resolve_host = guarded_resolve_host
