"""Canonical-host recovery for CivicPlus (Ryan, 2026-10-03).

The problem. A CivicPlus government's site answers on two kinds of address: the vendor's
(`ma-ipswich.civicplus.com`, whose robots.txt disallows every crawler) and the government's
own (`www.ipswichma.gov`, whose robots.txt blocks only editing and admin paths). We honor
robots.txt (see `robots_check.py`), so a vendor address is refused. Verified 2026-10-03 on
9 of 9 governments: the same meeting is listed on the government's own domain.

What `recover_civicplus()` does, for one refused vendor address:
  1. Take the path and query of the vendor address.
  2. For each candidate authority (the government's own domain, with and without `www.`),
     rebuild the SAME path and query there.
  3. Evaluate that authority's own robots.txt for that exact address. Skip it if disallowed.
  4. Check it is the same CivicPlus site and the same content, without touching the vendor
     address:
       * `listed`: the authority's `/AgendaCenter` page carries the meeting's own id token
         (`_09102026-105`). Strongest evidence; works for recent meetings.
       * `fetched`: the exact rebuilt address answers 200 with a document or page. Weaker:
         a different site could hold a different file at the same path.
       * `structure`: the address asked for is the AgendaCenter page itself, and the
         authority's page has CivicPlus's agenda-list structure.
  5. Use the authority's address only if one of those holds.

The vendor address is never requested. Candidates come from the caller (Meeting Finder's
`alternates`, a research row's `domain` and `alternate_domains`); this repo holds no table
of government domains.

Other platforms: the method is general, but the counts (2026-10-03) say it pays off for
CivicPlus (1,297 government-owned hosts seen carrying CivicPlus paths) and barely elsewhere
(Swagit 8, Cablecast 23, Granicus 1, PrimeGov, CivicWeb and CivicClerk 0). See
`research/` in rtr-business.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from . import robots_check
from .robots_rules import path_and_query

# `state-name.civicplus.com`, for example `ma-ipswich.civicplus.com` or `mn-chippewacounty2.civicplus.com`.
CIVICPLUS_TENANT_RE = re.compile(r"^[a-z]{2}-[a-z0-9-]+\.civicplus\.com$")

# `/AgendaCenter/ViewFile/Agenda/_09102026-105` -> `_09102026-105`.
_VIEWFILE_TOKEN_RE = re.compile(r"/AgendaCenter/ViewFile/[A-Za-z]+/(_\d{8}-\d+)")
_LISTING_PATH_RE = re.compile(r"^/AgendaCenter/?(?:\?.*)?$", re.I)
_STRUCTURE_RE = re.compile(r"catAgendaRow|/AgendaCenter/ViewFile/", re.I)

_MAX_BYTES = 1_500_000


@dataclass(frozen=True)
class FetchResult:
    status: int
    content_type: str
    text: str


# (url) -> FetchResult. Injected in tests; the default does one polite GET.
Fetch = Callable[[str], Awaitable[Optional[FetchResult]]]
RobotsCheck = Callable[[str], Awaitable[Tuple[bool, object]]]


@dataclass(frozen=True)
class Recovery:
    original_url: str
    recovered_url: Optional[str] = None
    authority: Optional[str] = None
    evidence: str = ""  # "listed" | "fetched" | "structure" | ""
    skipped: Tuple[Tuple[str, str], ...] = ()  # (authority, why)
    reason: str = ""  # why nothing was recovered

    @property
    def recovered(self) -> bool:
        return self.recovered_url is not None


@dataclass
class _Cache:
    # authority -> the text of its /AgendaCenter page ("" when it had none).
    listings: Dict[str, str] = field(default_factory=dict)
    # tenant host -> the authority that proved to be the same site.
    authority_for: Dict[str, str] = field(default_factory=dict)


_CACHE = _Cache()


def clear_cache() -> None:
    _CACHE.listings.clear()
    _CACHE.authority_for.clear()


def is_civicplus_vendor_url(url: str) -> bool:
    return bool(CIVICPLUS_TENANT_RE.match((urlparse(url).hostname or "").lower()))


def meeting_token(url: str) -> Optional[str]:
    """The meeting's own id token in a CivicPlus ViewFile address, else None."""
    m = _VIEWFILE_TOKEN_RE.search(urlparse(url).path)
    return m.group(1) if m else None


def _authorities(candidates: Iterable[str]) -> List[str]:
    """Candidate hosts to try, in order: each domain as given, then its `www.` twin. Vendor
    hosts, raw IP addresses and blanks are dropped."""
    out: List[str] = []
    for raw in candidates:
        d = (raw or "").strip().lower()
        d = re.sub(r"^https?://", "", d).split("/")[0].split(":")[0]
        if not d or "." not in d or re.fullmatch(r"[\d.]+", d):
            continue
        if "civicplus.com" in d or "civiclive.com" in d:
            continue
        bare = d[4:] if d.startswith("www.") else d
        for host in (d, f"www.{bare}" if not d.startswith("www.") else bare):
            if host not in out:
                out.append(host)
    return out


async def _default_fetch(url: str) -> Optional[FetchResult]:
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": robots_check.USER_AGENT}
        ) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                ctype = (response.headers.get("Content-Type") or "").lower()
                if "html" in ctype or "text" in ctype:
                    # `content.read(n)` returns only what is buffered so far; read the
                    # whole page (capped) so a token far down the listing is seen.
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) >= _MAX_BYTES:
                            break
                    text = bytes(body).decode("utf8", "replace")
                else:
                    await response.content.read(
                        1
                    )  # a document: status and type are enough
                    text = ""
                return FetchResult(response.status, ctype, text)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


async def recover_civicplus(
    url: str,
    candidates: Iterable[str],
    *,
    fetch: Fetch = _default_fetch,
    robots: RobotsCheck = robots_check.check_url,
    delay_s: float = 0.0,
    cache: _Cache = _CACHE,
) -> Recovery:
    """Find an allowed, same-content address on the government's own domain for a CivicPlus
    vendor address. See the module words. Never requests the vendor address."""
    parsed = urlparse(url)
    tenant = (parsed.hostname or "").lower()
    if not CIVICPLUS_TENANT_RE.match(tenant):
        return Recovery(url, reason="not a CivicPlus vendor address")

    tail = path_and_query(url)
    token = meeting_token(url)
    is_listing = bool(_LISTING_PATH_RE.match(tail))
    authorities = _authorities(candidates)
    if tenant in cache.authority_for and cache.authority_for[tenant] in authorities:
        # Try the authority that already proved to be this site first.
        first = cache.authority_for[tenant]
        authorities = [first] + [a for a in authorities if a != first]
    if not authorities:
        return Recovery(url, reason="no candidate domain for this government")

    skipped: List[Tuple[str, str]] = []
    for auth in authorities:
        rebuilt = f"https://{auth}{tail}"
        allowed, rule = await robots(rebuilt)
        if not allowed:
            pattern = getattr(rule, "pattern", "") or ""
            skipped.append((auth, f"robots.txt disallows {tail} ({pattern})"))
            continue

        if auth not in cache.listings:
            listing_url = f"https://{auth}/AgendaCenter"
            ok, _ = await robots(listing_url)
            text = ""
            if ok:
                if delay_s:
                    await asyncio.sleep(delay_s)
                got = await fetch(listing_url)
                if got is not None and got.status == 200:
                    text = got.text
            cache.listings[auth] = text
        listing = cache.listings[auth]
        is_civicplus = bool(_STRUCTURE_RE.search(listing))

        if not is_civicplus:
            skipped.append((auth, "no CivicPlus AgendaCenter page found there"))
            continue
        if is_listing:
            cache.authority_for[tenant] = auth
            return Recovery(url, rebuilt, auth, "structure", tuple(skipped))
        if token and token in listing:
            cache.authority_for[tenant] = auth
            return Recovery(url, rebuilt, auth, "listed", tuple(skipped))

        # Not on the first page of the listing: ask for the exact address (weaker evidence).
        if delay_s:
            await asyncio.sleep(delay_s)
        got = await fetch(rebuilt)
        if got is not None and got.status == 200:
            ctype = got.content_type
            if "pdf" in ctype or "html" in ctype or "officedocument" in ctype:
                cache.authority_for[tenant] = auth
                return Recovery(url, rebuilt, auth, "fetched", tuple(skipped))
        skipped.append((auth, "the same meeting was not found there"))

    return Recovery(
        url,
        skipped=tuple(skipped),
        reason="no allowed address on the government's own domain served the same content",
    )
