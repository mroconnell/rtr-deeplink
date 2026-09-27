"""Start (WO-1030): turn a domain into starting points --
docs/MEETING_FINDER.md's Start section.

    Start -> Identify -> List / Scan -> Hop -> Resolve -> Verdict

Reuses stage 1's own functions in `scripts/wo282_recon.py` rather than
re-deriving DNS/robots/sitemap logic a second time -- `dns_lookup()`
(including its `VENDOR_SUBDOMAIN_GUESSES` list and its civicweb.net/
primegov.com tenant-label guess), `fetch_live_robots_v2()` and
`fetch_live_sitemap_v2()`. Those are synchronous (`requests`-based, built
for `wo282_recon.py`'s own thread-pool sweep), so they're called via
`asyncio.to_thread()` rather than ported -- same reasoning `fetch.py`'s
own docstring already gives for importing `wo282_recon.py`'s Wayback
helpers directly.

**DNS gate first** (docs/MEETING_FINDER.md): if neither the apex domain
nor `www.` resolves, Start tries each of `alternates` (the research row's
own alternate domains, passed in by the caller as `FinderInput.alternates`
since WO-1142; Start itself never reads rtr-business) and continues
against the first whose homepage resolves. If none does, it falls back
(WO-1142) to the first candidate where a guessed subdomain or vendor-
account label resolved, and starts from those hosts alone. Only when
nothing resolves at all is the outcome `dns-unresolvable`.

**Cheap extra starting points**, all real, all cited above: guessed
vendor subdomains that actually resolved (`agenda.`, `meetings.`,
`live.`, `video.`, `granicus.`, `legistar.`...), a guessed CivicWeb/
PrimeGov tenant label host that resolved, and sitemap URLs that
`detect_platform()`/`host_recognition.platform_for_host()`/
`platform_for_path()` recognizes as a known platform, or that look like
a specific meeting page (the same `_OWN_SITE_MEETING_PAGE_RE` shape
Identify's own rank-3 signal uses -- imported from `identify.py` rather
than re-derived, so the two "is this a meeting page URL" checks never
drift apart).

The DNS lookup, robots read and sitemap read are their own small,
separate budget -- like `fetch.py`'s own Wayback CDX lookup, they don't
spend any of `Fetcher.max_fetches` (Start's job is to find starting
points cheaply, before a single real page fetch happens against any of
them; the phase loop's own Identify/Scan/Hop calls are what spend the
per-government fetch budget). A robots.txt `Crawl-delay` found here is
handed to `fetcher.note_crawl_delay()` so every later fetch to this
government's host already knows about it, per that method's own
docstring.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from urllib.parse import urlparse

from app.platforms import host_recognition
from app.platforms.base import detect_platform
from scripts.wo282_recon import (
    dns_lookup,
    fetch_live_robots_v2,
    fetch_live_sitemap_v2,
)

from .fetch import Fetcher
from .identify import _OWN_SITE_MEETING_PAGE_RE
from .models import OUTCOME_DNS_UNRESOLVABLE

# How many extra (non-homepage) starting points Start hands back at most --
# a generous but bounded number, since every one of these becomes a real
# fork candidate later and `max_forks` is what actually limits how many
# get tried.
_MAX_EXTRA_STARTING_POINTS = 8


@dataclass(frozen=True)
class StartResult:
    starting_points: List[str] = field(default_factory=list)
    outcome: Optional[str] = None
    note: str = ""


def _normalize_domain(domain_or_url: str) -> str:
    """A bare domain (`pomonaca.gov`) or any URL -> its own registrable
    host, lowercased, no scheme/path/port. `www.` is kept as-is here --
    the DNS gate checks both the given host and its `www.` sibling
    separately below, whichever form was passed in."""
    value = (domain_or_url or "").strip()
    if "://" not in value:
        value = f"https://{value}"
    host = urlparse(value).netloc.lower().split(":")[0]
    return host or value.lower()


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def _homepage_resolves(info: dict) -> bool:
    return bool(
        info.get("apex_a")
        or info.get("apex_cname")
        or info.get("www_a")
        or info.get("www_cname")
    )


def _guessed_hosts_resolve(info: dict) -> bool:
    """WO-1142: a guessed subdomain or vendor-account label that resolved
    -- the same entries `start()` turns into starting points below. An
    own-domain wildcard entry doesn't count (same A records as the apex:
    not a separate host)."""
    subs = [
        e
        for e in info.get("resolving_subdomains") or []
        if not e.get("likely_own_domain_wildcard")
    ]
    return bool(subs or info.get("resolving_vendor_labels"))


async def _dns_resolves(domain: str) -> Optional[dict]:
    """`dns_lookup()` (sync, real `dig` subprocess calls) off the event
    loop. Returns the raw dict when the apex or `www.` resolves, or
    (WO-1142) when only a guessed subdomain / vendor-account label does;
    else `None`. `dns_lookup()` already runs every guess on each call, so
    keeping a guess that resolved costs no extra lookup -- before WO-1142
    it was computed and then thrown away whenever the homepage was dead."""
    info = await asyncio.to_thread(dns_lookup, domain)
    if _homepage_resolves(info) or _guessed_hosts_resolve(info):
        return info
    return None


def _sitemap_starting_points(urls: Sequence[str]) -> List[str]:
    """Sitemap URLs worth trying as their own starting point: a known
    platform (`detect_platform()`/`host_recognition`) or a shape that
    looks like one specific meeting/agenda page on the government's own
    site (Identify's own rank-3 regex, reused verbatim)."""
    out: List[str] = []
    seen = set()
    for url in urls:
        if url in seen:
            continue
        platform = detect_platform(url)
        is_known_platform = platform != "unknown"
        if not is_known_platform:
            host_platform, _ = host_recognition.platform_for_host(urlparse(url).netloc)
            is_known_platform = host_platform is not None
        looks_like_meeting = bool(_OWN_SITE_MEETING_PAGE_RE.search(url))
        if is_known_platform or looks_like_meeting:
            seen.add(url)
            out.append(url)
        if len(out) >= _MAX_EXTRA_STARTING_POINTS:
            break
    return out


async def _try_domain(
    domain_or_url: str, fetcher: Fetcher
) -> "tuple[Optional[str], Optional[dict]]":
    """Normalizes and DNS-checks one candidate domain. Returns
    `(resolved_domain, dns_info)` or `(None, None)` when neither the apex
    nor `www.` resolves."""
    host = _strip_www(_normalize_domain(domain_or_url))
    info = await _dns_resolves(host)
    if info is None:
        return None, None
    return host, info


async def start(
    domain_or_url: str,
    fetcher: Fetcher,
    *,
    alternates: Optional[Sequence[str]] = None,
    guess_subdomains: bool = True,
) -> StartResult:
    """See this module's own docstring. `alternates` are tried, in
    order, only when `domain_or_url` itself is DNS-dead -- they come from
    the caller (a research row's own `alternate_domains`), never read
    from rtr-business by this function itself."""
    # WO-1142: a domain whose homepage resolves always wins. Failing that,
    # the alternates (the research row's other domains) are tried for a
    # homepage too, in order. Only when no candidate has a live homepage
    # does Start fall back to the first candidate whose guessed subdomain
    # or vendor-account label resolved -- a found host, but a guess, so
    # identity is left to Verdict (audit mode) as for any link-first find.
    tried: List[str] = []
    subdomain_only: "Optional[tuple[str, dict]]" = None
    domain, dns_info = None, None
    for candidate in [domain_or_url, *(alternates or [])]:
        host, info = await _try_domain(candidate, fetcher)
        tried.append(candidate)
        if host is None or info is None:
            continue
        if _homepage_resolves(info):
            domain, dns_info = host, info
            break
        if subdomain_only is None:
            subdomain_only = (host, info)
    if domain is None and subdomain_only is not None and guess_subdomains:
        domain, dns_info = subdomain_only
    if domain is None or dns_info is None:
        return StartResult(
            starting_points=[],
            outcome=OUTCOME_DNS_UNRESOLVABLE,
            note=f"neither apex nor www. resolved for: {', '.join(tried)}",
        )
    homepage_live = _homepage_resolves(dns_info)

    starting_points: List[str] = []
    seen = set()

    def _add(url: str) -> None:
        if url not in seen:
            seen.add(url)
            starting_points.append(url)

    # Homepage variants, per docs/MEETING_FINDER.md's own order -- but
    # WO-1086: only add whichever of the apex/`www.` actually resolves
    # (`dns_info` already carries both, from the DNS gate above, which
    # only ever required ONE of them to resolve, never both). Adding
    # both unconditionally produced a doomed, DNS-erroring fetch for real
    # governments in EITHER direction, confirmed live 2026-09-26:
    #   - apex resolves, `www.` doesn't -- true of every one of a
    #     subdomain host (streaming.easdpa.org, video.collierschools.com,
    #     streamgages.springfieldmo.gov, media.polson.k12.mt.us,
    #     streaming.usd367.org) -- there's no such thing as
    #     `www.streaming.easdpa.org`.
    #   - apex doesn't resolve, `www.` does -- the OPPOSITE asymmetry,
    #     just as common in practice (ppps.org, hartisd.net,
    #     midkotaschools.k12.nd.us and 20 more from one real sweep alone,
    #     2026-09-26: the bare apex has no A/CNAME record at all, only
    #     `www.` does, mostly on Apptegy-hosted districts).
    # Either doomed fetch raised a DNS error, `fetch.py` reported it as
    # that fork's own `dns-unresolvable` outcome, and `runner.py`'s
    # outcome ranking (35, well above `no-meeting-nor-video`'s 10) let
    # that secondary fork's failure override a real finding from the
    # fork that actually resolved. See `_WalkState.dns_gate_passed` in
    # runner.py for the second half of the fix (belt and braces for any
    # OTHER way a secondary fork could still raise a stray
    # `dns-unresolvable`, e.g. a broken link found later in the walk --
    # confirmed live too, see that field's own comment).
    apex_resolves = bool(dns_info.get("apex_a") or dns_info.get("apex_cname"))
    www_resolves = bool(dns_info.get("www_a") or dns_info.get("www_cname"))
    if apex_resolves:
        _add(f"https://{domain}/")
    if www_resolves:
        _add(f"https://www.{domain}/")
    if apex_resolves:
        _add(f"http://{domain}/")
    # WO-1134: the same plain-http fallback as the apex form, one line
    # up -- both https forks are always tried first (fork order, above),
    # so this is "after https failed for this form", never "instead of".
    # Real, measured gap: a live probe of 384 `site-broken`/blocked-*
    # governments (2026-09-26, see docs/MEETING_FINDER.md and
    # BACKLOG_DONE.md's WO-1134 entry) found 212 whose domain actually
    # works in SOME form -- of those, 15 needed plain http on the `www.`
    # host specifically (e.g. `http://www.cityofkress.tx.citygovt.org/`),
    # a form Start never tried before this: only the apex got an http
    # fallback, `www.` only ever got https. 83 more needed the apex http
    # fallback that already existed above.
    if www_resolves:
        _add(f"http://www.{domain}/")

    notes: List[str] = []

    if guess_subdomains:
        for entry in dns_info.get("resolving_subdomains") or []:
            if entry.get("likely_own_domain_wildcard"):
                continue  # same A records as the apex -- not a real vendor host
            _add(f"https://{entry['host']}/")
        for entry in dns_info.get("resolving_vendor_labels") or []:
            _add(f"https://{entry['host']}/")

    if not homepage_live:
        # WO-1142: the homepage is dead, so robots.txt and the sitemap
        # would only fail against it. Start from the guessed hosts alone.
        notes.append(
            f"apex and www. dead for {domain}; starting from guessed hosts only"
        )
        return StartResult(
            starting_points=starting_points,
            outcome=None,
            note="; ".join(notes),
        )

    # Robots + sitemap -- own small budget, never spends Fetcher.max_fetches
    # (see module docstring). Never raises: both wo282_recon helpers already
    # catch their own real-world failures and report them in `error`.
    robots_info = await asyncio.to_thread(fetch_live_robots_v2, domain)
    if robots_info.get("crawl_delay_seconds"):
        fetcher.note_crawl_delay(domain, robots_info["crawl_delay_seconds"])
        fetcher.note_crawl_delay(f"www.{domain}", robots_info["crawl_delay_seconds"])
    if robots_info.get("error"):
        notes.append(f"robots.txt: {robots_info['error']}")

    sitemap_info = await asyncio.to_thread(fetch_live_sitemap_v2, domain, robots_info)
    if sitemap_info.get("found"):
        for url in _sitemap_starting_points(sitemap_info.get("urls") or []):
            _add(url)
    elif sitemap_info.get("error"):
        notes.append(f"sitemap: {sitemap_info['error']}")

    return StartResult(
        starting_points=starting_points,
        outcome=None,
        note="; ".join(notes),
    )
