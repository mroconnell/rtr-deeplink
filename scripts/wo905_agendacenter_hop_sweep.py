"""WO-905 (2026-09-19): AgendaCenter-empty-shell hop sweep.

BACKLOG.md's "AgendaCenter-empty-shell population" entry: 1,125 governments
tested and rejected as having no video actually carry a bare, EMPTY
`/AgendaCenter` hub as their recorded example -- not the government's real
meeting hub, which usually sits one link deeper. WO-226's 6-row hand-check
found the real hub one hop away converts 4 of 6 to real video (Hagerstown
MD, Harvey IL, Flagler Beach FL, Greenwood Village CO); the other 2
(Hoffman Estates IL, Melrose MA) correctly stay no-video after the same
closer look. The entry's own "Next action" said to sweep this population
once WO-228's ranked hop-link finder shipped -- it has (later reweighted
by WO-274, see docs/COVERAGE_HANDOVER.md Sec.4) -- so this script builds
and validates that sweep. It does NOT run the real 1,125-row population:
that list lives only in `~/Documents/rtr-business/research/
jurisdiction_coverage.csv` on Ryan's Mac, unreachable from the sandbox
this was built in. See this repo's CLAUDE.md multi-session bullets and
BACKLOG.md's own entry for that context.

What this script does, per government:
  1. Fetch the recorded (possibly-empty) `hub_url` -- honest headers, one
     browser-header retry only on a blocked/dead/timeout outcome, never
     after a plain 404 (CLAUDE.md's "politely" rule; this module's own
     `_fetch_with_retry`).
  2. ALSO fetch the government's own `domain` home page, independently --
     not merely as a fallback for when the hub fetch fails. Confirmed
     live 2026-09-19: Flagler Beach FL's own `/AgendaCenter` answers 200
     with a JS-rendered, statically-empty shell (0 ViewFile/.pdf/category
     links), while its HOME page server-renders real `/Calendar.aspx?EID=`
     meeting entries the AgendaCenter fetch never shows -- the real hub
     sits one hop from the home page, not from the empty widget itself.
  3. Run `find_platform_link()` directly on whatever page(s) were reached
     (a hit here needs no hop at all -- confirmed live on Hoffman Estates,
     IL, whose own home page links straight to a real CivicClerk portal
     and a real YouTube channel).
  4. If nothing yet, gather ranked hop-link candidates from each reached
     page via `find_hop_links()` (WO-228/274's weighted scorer, reused
     verbatim from scripts/wo147_access_ladder_sweep.py), PLUS this
     script's own `_find_icon_shortcut_links()` supplement (see its
     docstring -- a same-domain, icon-only shortcut link like `/youtube`
     with no anchor text scores 0 under the weighted scorer and is
     silently dropped, confirmed live on Hagerstown MD and Greenwood
     Village CO, both of whose real conversion path is exactly this
     shape). Each candidate is then evaluated (see `sweep_one`'s own
     comments for the never-fetch-a-recognized-platform-URL rule this
     applies at every step) and, for a calendar-shaped page with no
     document evidence, one further hop into its dated entries via
     `find_calendar_entry_links()` (also reused verbatim) -- confirmed
     live to be exactly how Flagler Beach FL's real conversion is
     reached (a `Calendar.aspx?EID=` entry links a specific
     `flaglerbeachfl.portal.civicclerk.com/event/1509/files` URL that
     the home page's own top-level anchors never show).

A bare vendor-tenant root is recognized, not fetched (WO-905 fix, credited
to a sibling pipeline's finding -- see `_url_shape_hit()`'s own docstring
for the full explanation and the passive-discovery-v2 credit). This is
also what keeps this script honest about "found a platform LINK" not
meaning "confirmed real video": `needs_listing_discovery` on a report row
means exactly that gap -- a CivicClerk/Swagit/Granicus/PrimeGov/eScribe/
IQM2/CivicWeb bare root needs that platform's own listing-discovery step
before anyone should treat it as confirmed video ("CivicWeb" added
WO-910, 2026-09-20, the first real-scale run: see `_LISTING_REQUIRED_
PLATFORMS`'s own comment). For CivicClerk specifically,
`sweep_one()` takes that step itself rather than leaving it as a flagged
gap: it calls `scripts/adhoc_civicplus_pipeline.py`'s already-built,
already-tested `civicclerk_latest_event_url()` (a plain read of the
tenant's own public Events API, WO-137, 2026-09-09) to look for a real
past event before settling for "bare root, needs a check." The other
vendors have no equivalent helper in this repo yet, so a bare root
on one of those stays a flagged, unresolved `needs_listing_discovery`
row -- a real residual gap for a future WO, not silently papered over.

This script never calls ingest, never writes to any research file, and
never fetches youtube.com/youtu.be directly -- not even via an ordinary
same-domain redirect shortcut (`_fetch_no_external_redirect()` follows
ONLY same-host redirects by hand; a redirect to any other host, including
a recognized platform, is classified by URL shape alone and never
fetched). Its only output is its own report CSV -- read-only with respect
to everything else in this repo and this project. There is no non-dry-run
mode: every run is a dry run by construction.

Usage (from the repo root, this script's own venv):
    .venv/bin/python scripts/wo905_agendacenter_hop_sweep.py --limit 30
    .venv/bin/python scripts/wo905_agendacenter_hop_sweep.py   # full run, resumable

Expected input CSV columns (default path under RESEARCH_DIR, override with
--candidates-csv): gov_id, name, state, population, domain, hub_url
(falls back to reading a column named `example_url` for `hub_url` if the
source file used the same column name BACKLOG.md's entry does), and an
optional reject_reason (carried through unchanged, informational only).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402

import scripts.adhoc_civicplus_pipeline as civicplus_pipeline  # noqa: E402
import scripts.wo147_access_ladder_sweep as ladder  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo905_agendacenter_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo905_report.csv"

# Bound on live fetches spent hopping per government, beyond the hub_url
# and domain-home fetches themselves -- keeps worst-case runtime/request
# volume predictable regardless of how many candidates a page's nav
# turns up. Same order of magnitude as ladder.MAX_HOP_LINKS (8), a little
# higher since candidates here are merged from two starting pages.
MAX_HOP_FETCHES = 8
PER_GOVERNMENT_TIMEOUT_SECONDS = 180
_NOTE_MAX_LEN = 500

# Platforms whose real content sits behind a specific listing/event path
# the adapter itself discovers -- a bare tenant ROOT (no path, no query)
# is a real, confirmed find but not yet a confirmed video. Exact platform
# list credited to BACKLOG.md's "[NEEDS-AUDIT] The passive-discovery-v2
# pipeline (WO-283/WO-320 onward) treats a vendor-tenant-host domain like
# an ordinary government homepage" entry (WO-322, 2026-09-12): that
# sibling pipeline found 12 of 1,266 rows carried exactly one of these
# five vendors' bare tenant root as their own `domain` column, fetched it
# like an ordinary homepage, and mostly hit each adapter's own "no event
# id in this URL" error -- landing as `no-platform-link-found` even
# though the tenant is real. This module's `_url_shape_hit()` is WO-905's
# fix for the identical shape turning up in ITS OWN hop candidates:
# confirmed live 2026-09-19 on Hoffman Estates, IL, whose own home page
# links straight to a bare `hoffmanestatesil.portal.civicclerk.com` root
# with no event path at all. "iqm2" is added here beyond the entry's own
# five -- this WO's own live validation found the identical shape a
# sixth time: Melrose, MA's real hop lands on
# `melrosecityma.iqm2.com/citizens/default.aspx`, IQM2's generic tenant
# landing page (confirmed live: it links only `granicus.com`'s own
# marketing/support address and a further `/Citizens/calendar.aspx` hop
# -- no meeting content of its own), the exact same "root, not a
# listing" shape under a different vendor. "civicweb" added WO-910
# (2026-09-20), the first real-scale run of this script: 3 of the
# broader (non-AgendaCenter) population's 5 civicweb hits were a bare
# `<tenant>.civicweb.net/Portal` tenant root with no event/meeting path
# at all (Invermere BC, Gulf Breeze FL, Shawano WI) -- the identical
# "root, not a listing" shape the other six vendors already needed this
# flag for, just never seen against a real CivicWeb tenant before this
# run (none of the 6 original validation governments used CivicWeb, and
# neither did anything in the AgendaCenter-shaped primary population --
# 0 of its 656 rows hit civicweb at all). See `_GENERIC_LANDING_PATHS`'s
# own comment for the matching "portal" path addition this needed.
_LISTING_REQUIRED_PLATFORMS = frozenset(
    {"civicclerk", "swagit", "granicus", "primegov", "escribe", "iqm2", "civicweb"}
)

# A same-domain, ICON-ONLY shortcut link (no anchor text -- an <img>/
# aria-label carries the label instead) whose href path itself names a
# video-platform shortcut. find_hop_links()'s own weighted scorer
# requires real anchor TEXT or a path/bigram already present in
# hop_link_weights.csv (_score_hop_candidate_weighted's own docstring in
# wo147_access_ladder_sweep.py) -- neither is true for this shape, so it
# scores 0 (no path weight for a bare "/youtube" token, no anchor text at
# all) and is silently dropped. Confirmed live 2026-09-19 on two of this
# WO's own six real validation governments: Hagerstown MD
# (`<a class="widgetDesc widgetGraphicLinksLink" href="/youtube"
# aria-label="YouTube opens in new window"><img alt="YouTube" .../></a>`)
# and Greenwood Village CO (`<a href="/youtube">YouTube</a>`, this one
# WITH text -- still excluded by the weighted scorer since "youtube" the
# WORD isn't a measured anchor-text token in hop_link_weights.csv either)
# both redirect to their real, real YouTube channel this exact way -- see
# this module's own tests for the captured real markup.
_ICON_SHORTCUT_PATH_RE = re.compile(
    r"^/(youtube|vimeo|video|videos|livestream|live-stream|streaming|watch)/?$",
    re.I,
)
_ICON_SHORTCUT_LABEL_WORDS = ("youtube", "vimeo", "video", "webcam", "stream", "watch")

# "civicplus" is never a real answer for THIS population. Confirmed live
# 2026-09-19, first run of this exact script against all 6 real
# validation governments: detect_platform() recognizes ANY
# `/agendacenter`-shaped path on ANY domain as "civicplus" (base.py's own
# `if path.startswith("/agendacenter"): return "civicplus"`), and
# find_platform_link() has its OWN separate "agendacenter in html_text"
# early-exit that fires on the hub page's mere mention of the word --
# both of which trivially re-confirm the SAME platform this whole
# population already starts from (a bare `/AgendaCenter` URL is exactly
# how each candidate arrives here). Reporting that back as "found a
# platform" would be tautological, not a finding -- and COVERAGE_
# HANDOVER.md Sec.4's own measured finding is that AgendaCenter is "an
# agenda host, not a video host" to begin with. All 6 real governments'
# hub AND home pages re-triggered this before this constant existed,
# masking every real hop result behind a false "already answered".
#
# "civiclive" added WO-910 (2026-09-20), for a different reason than
# civicplus's tautology: CivicLive (Intrafinity) is a real municipal
# CMS with 1000+ customers and NO video product of its own at all --
# already established elsewhere in this codebase, not a new finding
# here (see `app/platforms/base.py`'s own `detect_platform()` comment
# on its civiclive recognizer, confirmed live WO-92, 2026-09-01). A
# `civiclive`-shaped link can never be real meeting video by
# construction, so it is just as non-actionable as a tautological
# civicplus hit even though the underlying reason is different. Found
# live in the broader population: Camden village, NY's own home page
# hop landed on `camdenny.hosted2.civiclive.com/living_here/about_us/
# our_history` -- a real page on the town's real CivicLive-hosted site,
# just its "About Us" history page, not a meeting or a video.
_TRIVIAL_PLATFORMS = frozenset({"civicplus", "civiclive"})


def log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class CandidateHit:
    platform: str
    url: str
    source: str
    needs_listing: bool


def _is_channel_shaped(platform: str, url: str) -> bool:
    """True for a YouTube URL that names a CHANNEL/HANDLE/USER -- the
    platform's own durable tenant identity, the same shape
    tenant_overrides.csv pins on -- rather than one specific embedded
    video. This script treats a channel-shaped hit as reliable; see
    `_looks_like_decorative_embed()` for why a bare embed is not."""
    if platform != "youtube":
        return False
    path = urlparse(url).path.lower()
    return path.startswith(("/channel/", "/user/", "/c/")) or "/@" in path


def _looks_like_decorative_embed(platform: str, url: str, source: str) -> bool:
    """True when a youtube/vimeo hit is suspect as a homepage decorative/
    welcome-video embed rather than real meeting content, and should NOT
    be trusted as this script's answer on its own. Confirmed live
    2026-09-19 building this script: Harvey, IL's real home page embeds a
    generic, unlabelled `<iframe src="youtube.com/embed/..." title=
    "YouTube video">` inside a styled hero card with no meeting context
    at all -- the exact false-positive class scripts/wo361_find_hub.py's
    own `_is_decorative_hit()` was built to catch (WO-355, 2026-09-13:
    "62 of 64 'videos' were the homepage's own welcome/promo clip"). The
    embedded video id even changed between two live fetches minutes
    apart during this WO's own validation -- further confirming it is
    rotating homepage content, not a stable meeting archive reference.
    Scoped narrowly on purpose: never true for a channel/handle-shaped
    hit (`_is_channel_shaped()`, the same shape a real pin trusts), and
    never true for anything reached through this script's own ranked
    hop-link/icon-shortcut/redirect machinery (`source` not ending in
    exactly "hub_page_anchor"/"home_page_anchor") -- those already carry
    a different, stronger signal (a link the site's own nav specifically
    labelled or scored on real measured vocabulary), not an anonymous
    embed picked up by a raw scan of the hub or home page itself."""
    if platform not in ("youtube", "vimeo"):
        return False
    if _is_channel_shaped(platform, url):
        return False
    if source not in ("hub_page_anchor", "home_page_anchor"):
        return False
    path = urlparse(url).path.lower()
    return path.startswith("/embed/") or path == "/watch"


def _is_actionable_hit(hit: CandidateHit) -> bool:
    """False for a hit this script has good, specific, live-confirmed
    reason to distrust as "the answer" for this population -- see
    `_TRIVIAL_PLATFORMS`, `_looks_like_decorative_embed()`, and
    `_is_youtube_search_link()`'s own docstrings for exactly what each
    excludes and why. Centralized here (used by every `_add_hit()` call
    site) so all three checks apply identically everywhere a hit can be
    recorded -- the hub/home direct scan, a hop candidate, an
    icon-shortcut, and a same-host or off-host-recognized redirect all
    funnel through the same gate."""
    if hit.platform in _TRIVIAL_PLATFORMS:
        return False
    if _is_youtube_search_link(hit.platform, hit.url):
        return False
    if _looks_like_decorative_embed(hit.platform, hit.url, hit.source):
        return False
    return True


def _add_hit(hits: List[CandidateHit], notes: List[str], hit: CandidateHit) -> None:
    """Appends `hit` to `hits` when `_is_actionable_hit()` accepts it;
    otherwise records why it was left out in `notes` instead of silently
    dropping it -- a human rereading this row's report should be able to
    see that something was found and reasoned about, not just nothing."""
    if _is_actionable_hit(hit):
        hits.append(hit)
    else:
        notes.append(
            f"excluded non-actionable hit: {hit.platform} {hit.url} (source={hit.source})"
        )


@dataclass
class HopSweepResult:
    gov_id: str = ""
    name: str = ""
    state: str = ""
    population: str = ""
    domain: str = ""
    hub_url: str = ""
    hub_fetch_status: str = ""
    home_fetch_status: str = ""
    hop_candidates_checked: int = 0
    fetches_used: int = 0
    outcome: str = ""
    platform: str = ""
    hit_url: str = ""
    hit_source: str = ""
    needs_listing_discovery: bool = False
    all_platforms_found: str = ""
    note: str = ""
    error: str = ""


FIELDNAMES = [f.name for f in fields(HopSweepResult)]


def _same_site(netloc_a: str, netloc_b: str) -> bool:
    """True when two netlocs are the same site up to a leading "www."
    label. Confirmed live 2026-09-19: Hoffman Estates, IL's bare apex
    (`hoffmanestates.org`) 301s to `www.hoffmanestates.org`, and Harvey,
    IL's `www.cityofharveyil.gov` 301s the OTHER direction, down to the
    bare apex -- both are the same ordinary, benign normalization
    `run_access_ladder()` already treats as just another candidate to
    try (it builds both variants up front rather than relying on a
    redirect at all), never a reason to refuse to follow. An exact-netloc
    comparison instead treated both as "off-host" and silently refused to
    reach either government's real home page at all."""

    def _strip_www(host: str) -> str:
        return host[4:] if host.startswith("www.") else host

    return _strip_www(netloc_a) == _strip_www(netloc_b)


# A vendor's own generic tenant LANDING document -- structurally a bare
# root even though it carries a path, since it is one fixed, non-
# specific page every tenant on that vendor shares (a home/index
# document, not a listing or a specific event). Confirmed live
# 2026-09-19 on Melrose, MA's real IQM2 tenant
# (`melrosecityma.iqm2.com/citizens/default.aspx`, see
# `_LISTING_REQUIRED_PLATFORMS`'s own comment for what it showed). Kept
# as an explicit, small, real-confirmed set rather than a guessed
# pattern, per this repo's "never build from assumption" rule. "portal"
# added WO-910 (2026-09-20): CivicWeb's own generic tenant landing page
# is `<tenant>.civicweb.net/Portal` -- confirmed live on 3 real broader-
# population tenants (Invermere BC, Gulf Breeze FL, Shawano WI), all
# bare with no event/meeting path at all.
_GENERIC_LANDING_PATHS = frozenset(
    {
        "",
        "citizens/default.aspx",
        "default.aspx",
        "index.html",
        "index.php",
        "home",
        "portal",
    }
)


def _round_robin(lists: List[List[Tuple[str, str]]]) -> List[Tuple[str, str]]:
    """Interleaves several lists position-by-position (item 0 of every
    list, then item 1 of every list, ...) rather than concatenating them
    -- see the candidate-gathering comment in `sweep_one` for why this
    matters here specifically."""
    out: List[Tuple[str, str]] = []
    max_len = max((len(lst) for lst in lists), default=0)
    for i in range(max_len):
        for lst in lists:
            if i < len(lst):
                out.append(lst[i])
    return out


def _pick_best(hits: List[CandidateHit]) -> CandidateHit:
    """The first hit that needs no further listing check, or the first
    hit at all when every one of them does (the caller may still try to
    resolve that further, e.g. `sweep_one`'s own CivicClerk upgrade)."""
    for h in hits:
        if not h.needs_listing:
            return h
    return hits[0]


def _is_bare_root(url: str) -> bool:
    p = urlparse(url)
    if p.query:
        return False
    return p.path.strip("/").lower() in _GENERIC_LANDING_PATHS


def _needs_listing_discovery(platform: str, url: str) -> bool:
    return platform in _LISTING_REQUIRED_PLATFORMS and _is_bare_root(url)


def _is_youtube_search_link(platform: str, url: str) -> bool:
    """A `youtube.com/results?search_query=...` link is a "search
    YouTube for this" widget, never a specific channel or video --
    confirmed live 2026-09-19 on Flagler Beach FL's real AgendaCenter
    page, whose "Watch us on YouTube" badge links exactly this shape
    rather than the government's real channel. Excluded outright
    regardless of source in `_is_actionable_hit()` -- unlike
    `_looks_like_decorative_embed()`'s narrower scope, a search-results
    link is never meaningful evidence no matter how it was reached."""
    return (
        platform == "youtube" and urlparse(url).path.rstrip("/").lower() == "/results"
    )


def _url_shape_hit(url: str) -> Optional[CandidateHit]:
    """Free (no network) check: does `url` already self-identify as a
    known platform purely by its own shape, via detect_platform()? If so,
    that already IS the answer for this script's purposes -- see this
    module's own docstring and the `_LISTING_REQUIRED_PLATFORMS` comment
    above for why a caller must check this BEFORE ever spending a fetch
    on a candidate URL, not after: fetching a bare vendor-tenant root
    like an ordinary page mostly returns nothing usable (that pipeline's
    own adapters expect a specific listing/event URL, not the root), so
    treating a fetch failure there as "nothing found" would silently
    misreport a government that is, in fact, already sitting on a real
    platform. Returns None for "unknown" (detect_platform()'s own
    not-found sentinel -- never falsy/empty-string)."""
    platform = detect_platform(url)
    if platform == "unknown":
        return None
    return CandidateHit(
        platform, url, "url_shape", _needs_listing_discovery(platform, url)
    )


def _find_icon_shortcut_links(html_text: str, final_url: str) -> List[str]:
    """See `_ICON_SHORTCUT_PATH_RE`'s own comment block above for why this
    exists and the two real governments it was confirmed against. Only
    ever returns a SAME-DOMAIN href (an off-domain link is already
    find_platform_link()'s/find_hop_links()'s job) -- this never itself
    claims a platform hit, it only surfaces a candidate for the caller to
    fetch (carefully -- see `_fetch_no_external_redirect`) and classify."""
    soup = ladder._safe_soup(html_text)
    if soup is None:
        return []
    base_netloc = urlparse(final_url).netloc.lower()
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(final_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https") or full in seen:
            continue
        if parsed.netloc.lower() != base_netloc:
            continue
        if not _ICON_SHORTCUT_PATH_RE.match(parsed.path):
            label = (
                f"{a.get_text() or ''} {a.get('aria-label') or ''} "
                f"{a.get('title') or ''}"
            ).lower()
            if not any(w in label for w in _ICON_SHORTCUT_LABEL_WORDS):
                continue
        seen.add(full)
        out.append(full)
    return out


async def _fetch_no_external_redirect(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    *,
    max_same_host_hops: int = 3,
) -> Tuple["ladder.FetchResult", str]:
    """Fetches `url`, following ONLY same-host redirects (up to
    `max_same_host_hops` times) by hand via `allow_redirects=False` plus a
    manual Location check. A redirect to a DIFFERENT host is never
    followed -- its target is returned as the second tuple element (empty
    string when no such redirect happened) so the caller can classify it
    with `_url_shape_hit()`/`detect_platform()` on the URL string alone,
    with no request ever made to it. This is what keeps a same-domain
    shortcut link (e.g. a CivicPlus site's own icon-only `/youtube` link,
    confirmed live on Hagerstown MD and Greenwood Village CO, 2026-09-19)
    from ever turning into a real HTTP request to youtube.com: this
    script's own NEVER rule is about not fetching youtube.com/youtu.be at
    all, not just never typing its name as the URL we start from."""
    start_netloc = urlparse(url).netloc.lower()
    current = url
    for _ in range(max_same_host_hops):
        try:
            async with session.get(
                current,
                headers=headers,
                timeout=ladder.REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        return ladder.FetchResult(
                            status=resp.status, final_url=current
                        ), ""
                    target = urljoin(current, location)
                    if _same_site(urlparse(target).netloc.lower(), start_netloc):
                        current = target
                        continue
                    return ladder.FetchResult(
                        status=resp.status, final_url=current
                    ), target
                html_text = await resp.text(errors="replace")
                return (
                    ladder.FetchResult(
                        status=resp.status,
                        final_url=str(resp.url),
                        html=html_text,
                        waf_family=ladder.waf_family_from_headers(dict(resp.headers)),
                    ),
                    "",
                )
        except Exception as e:  # noqa: BLE001 -- record and classify, never raise
            return (
                ladder.FetchResult(
                    error=str(e)[:200], error_kind=ladder.classify_exception(e)
                ),
                "",
            )
    return (
        ladder.FetchResult(final_url=current, error="too many same-host redirects"),
        "",
    )


def _classify_fetch(fr: "ladder.FetchResult") -> str:
    """ok | not_found | challenge | dead | blocked | timeout -- the
    outcomes this script's hub_fetch_status/home_fetch_status report."""
    if fr.error_kind == "dns":
        return "dead"
    if fr.error_kind == "timeout":
        return "timeout"
    if fr.html is None:
        return "blocked" if fr.error else "dead"
    if ladder.is_challenge(fr.html):
        return "challenge"
    if fr.status == 404:
        return "not_found"
    if fr.status and fr.status >= 400:
        return "blocked"
    return "ok"


async def _fetch_with_retry(
    session: aiohttp.ClientSession, url: str
) -> Tuple["ladder.FetchResult", str, str]:
    """Honest headers first; a browser-header retry only on a blocked/
    dead/timeout outcome, never after a plain 404 -- CLAUDE.md's
    "politely" rule and run_access_ladder's own rung order, reused here
    rather than re-derived. Returns (FetchResult, redirect_off_host_or_
    empty, status_label); status_label is one of _classify_fetch's own
    values, "ok_browser_headers", "redirect_off_host", or
    "<first_status>_then_<retry_status>"."""
    fr, redirect = await _fetch_no_external_redirect(
        session, url, ladder.HONEST_HEADERS
    )
    if redirect:
        return fr, redirect, "redirect_off_host"
    status = _classify_fetch(fr)
    if status not in ("blocked", "dead", "timeout"):
        return fr, "", status
    await asyncio.sleep(ladder.HOST_DELAY_SECONDS)
    fr2, redirect2 = await _fetch_no_external_redirect(
        session, url, ladder.BROWSER_HEADERS
    )
    if redirect2:
        return fr2, redirect2, "redirect_off_host"
    status2 = _classify_fetch(fr2)
    if status2 == "ok":
        return fr2, "", "ok_browser_headers"
    return fr2, "", f"{status}_then_{status2}"


async def sweep_one(session: aiohttp.ClientSession, row: dict) -> HopSweepResult:
    """One government: see this module's own docstring for the four-step
    method. Never raises on an ordinary fetch/parse problem (every helper
    this calls already turns that into a normal outcome) -- the caller
    still wraps this in a timeout/except for a genuinely unexpected bug,
    matching every other sweep script's own per-row safety net."""
    gov_id = (row.get("gov_id") or "").strip()
    name = (row.get("name") or "").strip()
    state = (row.get("state") or "").strip()
    population = (row.get("population") or "").strip()
    domain_raw = (row.get("domain") or "").strip()
    domain = ladder.normalize_home_url(domain_raw) if domain_raw else ""
    raw_hub = (row.get("hub_url") or row.get("example_url") or "").strip()
    hub_url = ladder.normalize_home_url(raw_hub) if raw_hub else ""
    if not hub_url and domain:
        # Same guessed shape find_platform_link()'s own AgendaCenter
        # fallback already uses -- this population's own defining shape.
        hub_url = domain.rstrip("/") + "/AgendaCenter"

    out = HopSweepResult(
        gov_id=gov_id,
        name=name,
        state=state,
        population=population,
        domain=domain,
        hub_url=hub_url,
    )
    if not hub_url and not domain:
        out.outcome = "no_hub_or_domain"
        out.error = "row carries neither a hub_url/example_url nor a domain"
        return out

    pages: List[Tuple[str, str, str]] = []  # (html, final_url, label)
    early_hits: List[CandidateHit] = []
    use_browser_headers = False
    note_parts: List[str] = []

    if hub_url:
        fr, redirect, status = await _fetch_with_retry(session, hub_url)
        out.fetches_used += 1
        out.hub_fetch_status = status
        if status == "redirect_off_host":
            hit = _url_shape_hit(redirect)
            if hit:
                _add_hit(
                    early_hits,
                    note_parts,
                    CandidateHit(
                        hit.platform, redirect, "hub_redirect", hit.needs_listing
                    ),
                )
            else:
                note_parts.append(
                    f"hub_url redirects off-host, not fetched: {redirect[:200]}"
                )
        elif status in ("ok", "ok_browser_headers"):
            pages.append((fr.html, fr.final_url, "hub"))
            use_browser_headers = use_browser_headers or status == "ok_browser_headers"
        elif status == "challenge":
            note_parts.append(
                "hub_url is behind a human-verification challenge; stopped there"
            )
    else:
        out.hub_fetch_status = "no_hub_url"

    if domain:
        domain_norm = domain.rstrip("/")
        hub_norm = hub_url.rstrip("/") if hub_url else ""
        if domain_norm == hub_norm:
            out.home_fetch_status = "same_as_hub"
        else:
            await asyncio.sleep(ladder.HOST_DELAY_SECONDS)
            fr, redirect, status = await _fetch_with_retry(session, domain)
            out.fetches_used += 1
            out.home_fetch_status = status
            if status == "redirect_off_host":
                hit = _url_shape_hit(redirect)
                if hit:
                    _add_hit(
                        early_hits,
                        note_parts,
                        CandidateHit(
                            hit.platform, redirect, "home_redirect", hit.needs_listing
                        ),
                    )
                else:
                    note_parts.append(
                        f"domain home redirects off-host, not fetched: {redirect[:200]}"
                    )
            elif status in ("ok", "ok_browser_headers"):
                pages.append((fr.html, fr.final_url, "home"))
                use_browser_headers = (
                    use_browser_headers or status == "ok_browser_headers"
                )
            elif status == "challenge":
                note_parts.append(
                    "domain home is behind a human-verification challenge; stopped there"
                )
    else:
        out.home_fetch_status = "no_domain"

    all_hits: List[CandidateHit] = list(early_hits)
    for html, final_url, label in pages:
        hit = ladder.find_platform_link(html, final_url)
        if hit:
            platform, url = hit
            _add_hit(
                all_hits,
                note_parts,
                CandidateHit(
                    platform,
                    url,
                    f"{label}_page_anchor",
                    _needs_listing_discovery(platform, url),
                ),
            )

    if not pages and not early_hits:
        out.outcome = "hub_and_home_unreachable"
        out.note = "; ".join(note_parts)[:_NOTE_MAX_LEN]
        return out

    if not all_hits:
        headers = (
            ladder.BROWSER_HEADERS if use_browser_headers else ladder.HONEST_HEADERS
        )
        # Built per-page (icon-shortcuts first -- few, high-precision,
        # cheap to check -- then the ranked hop links), then interleaved
        # ACROSS pages round-robin rather than exhausting one page's list
        # before touching the other's. Confirmed live 2026-09-19 this
        # matters, not just in theory: Flagler Beach FL's real answer
        # (a home-page calendar entry linking a specific CivicClerk
        # event) never got a fetch at all in the first version of this
        # script, which walked the HUB page's full ~8-candidate ranked
        # list to exhaustion before ever starting on the home page's own
        # list -- the fetch budget was gone by the time it got there.
        per_page: List[List[Tuple[str, str]]] = []
        for html, final_url, label in pages:
            page_candidates: List[Tuple[str, str]] = []
            for u in _find_icon_shortcut_links(html, final_url):
                page_candidates.append((u, f"{label}_icon_shortcut"))
            for u in ladder.find_hop_links(html, final_url, gov_id=gov_id):
                page_candidates.append((u, f"{label}_hop_link"))
            per_page.append(page_candidates)

        candidates: List[Tuple[str, str]] = []
        seen_urls = set()
        for cand in _round_robin(per_page):
            if cand[0] not in seen_urls:
                seen_urls.add(cand[0])
                candidates.append(cand)

        out.hop_candidates_checked = len(candidates)
        fetch_budget = MAX_HOP_FETCHES

        for cand_url, source_label in candidates:
            shape_hit = _url_shape_hit(cand_url)
            if shape_hit:
                _add_hit(
                    all_hits,
                    note_parts,
                    CandidateHit(
                        shape_hit.platform,
                        cand_url,
                        source_label,
                        shape_hit.needs_listing,
                    ),
                )
                continue
            if fetch_budget <= 0:
                continue
            await asyncio.sleep(ladder.HOST_DELAY_SECONDS)
            fr, redirect = await _fetch_no_external_redirect(session, cand_url, headers)
            out.fetches_used += 1
            fetch_budget -= 1
            if redirect:
                rhit = _url_shape_hit(redirect)
                if rhit:
                    _add_hit(
                        all_hits,
                        note_parts,
                        CandidateHit(
                            rhit.platform,
                            redirect,
                            f"{source_label}_redirect",
                            rhit.needs_listing,
                        ),
                    )
                else:
                    note_parts.append(
                        f"{source_label} redirects off-host, not fetched: {redirect[:200]}"
                    )
                continue
            if fr.html is None:
                continue
            if ladder.is_challenge(fr.html):
                note_parts.append(f"challenge at {source_label} ({cand_url[:200]})")
                continue
            inner_hit = ladder.find_platform_link(fr.html, fr.final_url)
            if inner_hit:
                platform, url = inner_hit
                _add_hit(
                    all_hits,
                    note_parts,
                    CandidateHit(
                        platform,
                        url,
                        f"{source_label}_page_anchor",
                        _needs_listing_discovery(platform, url),
                    ),
                )
                continue
            is_calendar_shaped = (
                "calendar" in cand_url.lower() or "event" in cand_url.lower()
            )
            if is_calendar_shaped and not ladder.looks_like_document_hub(fr.html):
                for entry_url in ladder.find_calendar_entry_links(
                    fr.html, fr.final_url
                ):
                    ehit = _url_shape_hit(entry_url)
                    if ehit:
                        _add_hit(
                            all_hits,
                            note_parts,
                            CandidateHit(
                                ehit.platform,
                                entry_url,
                                f"{source_label}_calendar_entry",
                                ehit.needs_listing,
                            ),
                        )
                        continue
                    if fetch_budget <= 0:
                        continue
                    await asyncio.sleep(ladder.HOST_DELAY_SECONDS)
                    efr, eredirect = await _fetch_no_external_redirect(
                        session, entry_url, headers
                    )
                    out.fetches_used += 1
                    fetch_budget -= 1
                    if eredirect:
                        erhit = _url_shape_hit(eredirect)
                        if erhit:
                            _add_hit(
                                all_hits,
                                note_parts,
                                CandidateHit(
                                    erhit.platform,
                                    eredirect,
                                    f"{source_label}_calendar_entry_redirect",
                                    erhit.needs_listing,
                                ),
                            )
                        continue
                    if efr.html and not ladder.is_challenge(efr.html):
                        entry_hit = ladder.find_platform_link(efr.html, efr.final_url)
                        if entry_hit:
                            platform, url = entry_hit
                            _add_hit(
                                all_hits,
                                note_parts,
                                CandidateHit(
                                    platform,
                                    url,
                                    f"{source_label}_calendar_entry_page_anchor",
                                    _needs_listing_discovery(platform, url),
                                ),
                            )

    if all_hits:
        best: Optional[CandidateHit] = _pick_best(all_hits)

        if best.needs_listing and best.platform == "civicclerk":
            # Hand off to the platform's OWN listing-discovery step
            # rather than stopping at "found a bare root" -- exactly what
            # BACKLOG.md's passive-discovery-v2 entry (credited above)
            # says a generic hop pipeline should do here. Reused, not
            # reinvented: scripts/adhoc_civicplus_pipeline.py already
            # built and tested this precise CivicClerk tenant-root ->
            # real-event lookup (WO-137, 2026-09-09, its own
            # `civicclerk_latest_event_url()`, a plain read of the
            # tenant's public Events API -- no ingest, same "here's what
            # I found" scope as the rest of this script). Confirmed live
            # 2026-09-19 on Hoffman Estates, IL: the API call itself
            # succeeds and comes back with a real, specific answer --
            # "no past CivicClerk events with real media found" -- which
            # is qualitatively different from "unconfirmed, needs a
            # check" (a bare root sitting there unexamined). That answer
            # DISPROVES this hit rather than merely leaving it open, so
            # it's dropped from consideration below rather than kept as
            # `best`, and reporting falls through to whatever else this
            # government's `all_hits` still has, or to a clean
            # `no_platform_link_found` when nothing else does.
            await asyncio.sleep(ladder.HOST_DELAY_SECONDS)
            try:
                (
                    upgraded_url,
                    reason,
                ) = await civicplus_pipeline.civicclerk_latest_event_url(
                    session, best.url
                )
            except Exception as e:  # noqa: BLE001 -- best-effort upgrade only
                upgraded_url, reason = None, f"{type(e).__name__}: {str(e)[:200]}"
            out.fetches_used += 1
            if upgraded_url:
                best = CandidateHit(
                    "civicclerk", upgraded_url, "civicclerk_listing_api", False
                )
                all_hits.insert(0, best)
            else:
                note_parts.append(
                    f"civicclerk bare root checked and confirmed empty: {reason}"
                )
                remaining = [h for h in all_hits if h is not best]
                best = _pick_best(remaining) if remaining else None

        if best is None:
            out.outcome = "no_platform_link_found"
        else:
            out.platform = best.platform
            out.hit_url = best.url
            out.hit_source = best.source
            out.needs_listing_discovery = best.needs_listing
            out.outcome = (
                "platform_found_bare_root" if best.needs_listing else "platform_found"
            )

        seen_pairs: List[str] = []
        seen_set = set()
        for h in all_hits:
            key = (h.platform, h.url)
            if key in seen_set:
                continue
            seen_set.add(key)
            seen_pairs.append(f"{h.platform}:{h.url}")
        out.all_platforms_found = "; ".join(seen_pairs[:8])
    else:
        out.outcome = "no_platform_link_found"

    out.note = "; ".join(note_parts)[:_NOTE_MAX_LEN]
    return out


def _load_done_gov_ids(report_csv: Path) -> set:
    if not report_csv.exists():
        return set()
    with report_csv.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


async def main_async(
    limit: Optional[int], candidates_csv: Path, report_csv: Path
) -> None:
    if not candidates_csv.exists():
        log(
            f"No candidates file at {candidates_csv} -- nothing to do. "
            "See this script's own module docstring for the expected columns."
        )
        return

    with candidates_csv.open(newline="", encoding="utf-8") as f:
        population = list(csv.DictReader(f))

    done = _load_done_gov_ids(report_csv)
    remaining = [r for r in population if (r.get("gov_id") or "") not in done]
    to_process = remaining[:limit] if limit else remaining
    log(
        f"{len(population)} in population, {len(done)} already in {report_csv.name}, "
        f"{len(to_process)} to process this run"
    )

    report_csv.parent.mkdir(parents=True, exist_ok=True)
    write_header = not report_csv.exists()
    consecutive_errors = 0
    start = time.monotonic()

    headers = {"User-Agent": ladder.HONEST_HEADERS["user-agent"]}
    async with aiohttp.ClientSession(headers=headers) as session:
        with report_csv.open("a", newline="", encoding="utf-8") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
            if write_header:
                writer.writeheader()
                out_f.flush()

            for i, row in enumerate(to_process, 1):
                gov_id = row.get("gov_id", "")
                try:
                    result = await asyncio.wait_for(
                        sweep_one(session, row), timeout=PER_GOVERNMENT_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    result = HopSweepResult(
                        gov_id=gov_id,
                        name=row.get("name", ""),
                        state=row.get("state", ""),
                        population=row.get("population", ""),
                        domain=row.get("domain", ""),
                        hub_url=row.get("hub_url", "") or row.get("example_url", ""),
                        outcome="timeout",
                        error=f"hard timeout after {PER_GOVERNMENT_TIMEOUT_SECONDS}s",
                    )
                except Exception as e:  # noqa: BLE001 -- one bad row never kills the sweep
                    result = HopSweepResult(
                        gov_id=gov_id,
                        name=row.get("name", ""),
                        state=row.get("state", ""),
                        population=row.get("population", ""),
                        domain=row.get("domain", ""),
                        hub_url=row.get("hub_url", "") or row.get("example_url", ""),
                        outcome="error",
                        error=f"{type(e).__name__}: {str(e)[:300]}",
                    )

                writer.writerow(asdict(result))
                out_f.flush()

                consecutive_errors = (
                    consecutive_errors + 1 if result.outcome == "error" else 0
                )

                elapsed = time.monotonic() - start
                log(
                    f"[{i}/{len(to_process)}] {gov_id} ({result.name}, {result.state}) "
                    f"-> {result.outcome} platform={result.platform or '-'} "
                    f"needs_listing={result.needs_listing_discovery} elapsed={elapsed:.0f}s"
                )

                if consecutive_errors >= 6:
                    log(
                        f"\nABORTING: {consecutive_errors} consecutive errors. "
                        "Re-run to resume (already-reported rows are skipped)."
                    )
                    return

                if i < len(to_process):
                    await asyncio.sleep(ladder.GOV_DELAY_SECONDS)

    log(
        f"done: {len(to_process)} processed this run, "
        f"{len(remaining) - len(to_process)} remaining"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--candidates-csv", type=Path, default=CANDIDATES_CSV)
    parser.add_argument("--report-csv", type=Path, default=REPORT_CSV)
    args = parser.parse_args()
    asyncio.run(main_async(args.limit, args.candidates_csv, args.report_csv))


if __name__ == "__main__":
    main()
