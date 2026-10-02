"""One shared robots.txt check for rtr-deeplink (Ryan, 2026-10-02: honor any matching
Disallow, in both repos, as one rule; stage it).

`check_url(url)` answers: does the host's robots.txt disallow this address for us? It reads
each host's robots.txt once per process and caches it. The matcher is
`app/utils/robots_rules.py`, the same rules as rtr-findmeeting's.

Two modes, one switch
- Log-only (the default, and the staging step): `pacing.py`'s request hook calls this for
  every request a Meeting Finder walk makes, records what WOULD have been skipped in
  `RequestStats`, and blocks nothing.
- Enforce: set the environment variable `ROBOTS_ENFORCE=1`. A disallowed request then raises
  `RobotsDisallowedError` (an `aiohttp.ClientError`, so an adapter's existing
  `except aiohttp.ClientError` handles it) before any request is made.
The length probe (`queue_probe.py`) always enforces; it is one explicit call.

What counts as "no block"
- A robots.txt that cannot be read (timeout, connection error, 5xx) is not a block. The
  check returns allowed and the host is cached as unreachable for this process.
- A 4xx (no robots.txt) means no rules, so allowed (RFC 9309).
- A loopback host (`127.0.0.1`, `localhost`) is never checked.
"""

from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from .robots_rules import Rule, matching_rule, parse_rules

USER_AGENT = (
    "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
    "+https://redtaperecordings.com/about)"
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# origin ("https://host") -> the rules that apply to us ([] when none or unreadable).
_RULES: Dict[str, List[Rule]] = {}
_UNREACHABLE: set = set()
# One lock per (running loop, origin), so concurrent callers read a host's robots.txt once.
_LOCKS: Dict[Tuple[int, str], asyncio.Lock] = {}


class RobotsDisallowedError(aiohttp.ClientError):
    """A request was not made: the host's robots.txt disallows this address for us."""

    def __init__(self, url: str, rule: Optional[Rule]) -> None:
        self.url = url
        self.rule = rule
        pattern = rule.pattern if rule else ""
        super().__init__(
            f"robots.txt disallows {urlparse(url).path or '/'} ({pattern})"
        )


def enforcing() -> bool:
    return os.environ.get("ROBOTS_ENFORCE", "").strip().lower() in ("1", "true", "yes")


def is_robots_txt_url(url: str) -> bool:
    return urlparse(str(url)).path.lower() == "/robots.txt"


def clear_cache() -> None:
    _RULES.clear()
    _UNREACHABLE.clear()
    _LOCKS.clear()


def _origin(url: str) -> Optional[str]:
    parts = urlparse(str(url))
    if not parts.scheme or not parts.netloc:
        return None
    if (parts.hostname or "").lower() in _LOOPBACK_HOSTS:
        return None
    return f"{parts.scheme}://{parts.netloc}"


async def _fetch_rules(origin: str) -> List[Rule]:
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
            async with session.get(
                f"{origin}/robots.txt", timeout=aiohttp.ClientTimeout(total=8)
            ) as response:
                if response.status == 200:
                    return parse_rules(await response.text(errors="replace"))
                if 400 <= response.status < 500:
                    return []  # no robots.txt: no rules (RFC 9309)
                _UNREACHABLE.add(origin)
                return []
    except Exception:
        _UNREACHABLE.add(origin)
        return []


async def rules_for(origin: str) -> List[Rule]:
    if origin in _RULES:
        return _RULES[origin]
    key = (id(asyncio.get_running_loop()), origin)
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        if origin not in _RULES:
            _RULES[origin] = await _fetch_rules(origin)
    return _RULES[origin]


async def check_url(url: str) -> Tuple[bool, Optional[Rule]]:
    """(allowed, the Disallow rule that blocks it). `(True, None)` when allowed, when the
    host is a loopback host, or when its robots.txt cannot be read."""
    origin = _origin(url)
    if origin is None or is_robots_txt_url(url):
        return True, None
    allowed, rule = matching_rule(await rules_for(origin), str(url))
    return allowed, (None if allowed else rule)
