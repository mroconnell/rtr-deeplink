"""Identify (WO-1027): say which platform a page is on, and which
account -- docs/MEETING_FINDER.md's Identify section.

Does not fetch itself unless it needs to: a bare URL is checked against
`detect_platform()`/`host_recognition.py` first (rule 1, "URL first, no
fetch"). Only when that comes back empty does this module ask the caller's
`Fetcher` for the page, then re-checks the SAME host-based rules against
the URL the site actually redirected to (rule 2 -- rtr-upcoming
2026-09-23 found `publicrecords.cityofsanrafael.org` redirects straight to
a Laserfiche Cloud repository; checking only the input host would have
missed that entirely).

If the host checks still come back empty, this reads the raw HTML
(including `<iframe src>`/`<embed>`/`<script src>`, per
UPCOMING_AGENDAS_FIELD_GUIDE.md's "the page you were given is often a
frame around a different product" finding -- Vacaville's own "Agendas and
Minutes" page is a full-viewport `<iframe>` around eScribe, with no
visible text of its own at all) and ranks every link/signal it finds,
per Ryan's ranking (2026-09-23, docs/MEETING_FINDER.md's own table):

    1. Meeting-platform vendor links (Granicus, Legistar, CivicClerk, ...)
    2. Direct media files (.mp4, .m3u8, Google Drive, Dropbox, ...)
    3. Links to specific meeting pages on the government's own site
    4. Other general-purpose video hosts (Vimeo, Wistia, BoxCast)
    5. YouTube, only as a meeting list (several distinct videos, each its
       own meeting)
    last. Any other YouTube link -- a drip lead, never the answer

This module never returns "youtube"/"youtube_channel" as `platform` --
even a rank-5 meeting-list finding stays a `signals` entry plus a
`youtube_leads` URL, for List (wave 2) to pick up on its own terms (e.g.
via `app/platforms/youtube_channel.py`'s flat-channel-listing adapter, or
the drip queue) -- never something Identify hands back as the account to
resolve. See this module's own `_rank_platform()` for where that's
enforced.

What this reuses, and why:

  - `app.platforms.base.detect_platform()`/`find_platform_link` and
    `app.platforms.host_recognition.platform_for_host()`/
    `platform_for_path()`/`web_host_hint_for_host()` -- the one registry
    of known platforms/vendor hosts this repo already maintains. This
    module does not hand-copy a vendor suffix list of its own anywhere.
  - `scripts/platform_fingerprints.fingerprint()` -- measured page-content
    signatures (`app/utils/jurisdiction_data/platform_signatures.csv`) for
    a platform that doesn't announce itself via a vendor hostname link
    (a first-party CivicClerk/eScribe/Granicus path shape).
  - `app.utils.video_hand_check.prescreen_homepage_link()` -- the
    reject-only decorative-link filter (`structural_reject()` +
    looping-hero-video markup) `find_platform_link(..., accept=...)` was
    built to take, so a homepage's own promo/hero video doesn't shadow a
    real vendor link found further down the page (the same false-positive
    class WO-355 measured: 62 of 64 bare-homepage "video found" verdicts
    were decorative).
  - `app.platforms.youtube_ids.extract_video_id()` -- the pure (no
    `yt_dlp` import) video-id regex, so telling a real per-video YouTube
    link apart from a bare channel/user link never needs the `yt_dlp`
    dependency this module (and the whole no-YouTube-fetch contract) has
    no business pulling in.

CivicLive on a city's OWN domain (not `*.hosted.civiclive.com`, which
`detect_platform()` already recognizes) is not a measured row in
`platform_signatures.csv` -- per this WO's brief, that needs a real,
measured signature before being added there, not a guess. This module
measures one narrowly, in place, rather than adding an unmeasured CSV row
-- see `_civiclive_first_party_signal()` below for the two real tenants
(Piedmont, CA and Williams, AZ) this was built and confirmed against
live, 2026-09-23, and why it stops short of touching
`platform_signatures.csv` itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.platforms import host_recognition
from app.platforms.base import _ALL_CORPORATE_HOSTS, _REGISTRY, detect_platform
from app.platforms.youtube_ids import extract_video_id
from app.utils.video_hand_check import prescreen_homepage_link, same_organization_flag
from scripts.platform_fingerprints import fingerprint, load_signatures

from .fetch import FetchResult, Fetcher
from .models import OUTCOME_ACCOUNT_NOT_FOUND, OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER
from .scan import (
    _SAME_SITE_SOCIAL_REDIRECT_RE,
    _extract_date_text,
    _row_context,
    _walk_up_for_date,
)

# --- Ranking (Ryan, 2026-09-23; docs/MEETING_FINDER.md's Identify table) --

RANK_VENDOR_LINK = 1
RANK_DIRECT_MEDIA = 2
RANK_OWN_SITE_MEETING_PAGE = 3
RANK_OTHER_VIDEO_HOST = 4
RANK_YOUTUBE_MEETING_LIST = 5
RANK_YOUTUBE_LEAD_ONLY = 99  # "last" -- never the answer

# General-purpose video hosts (rank 4) -- NOT government-meeting-specific
# vendors, even though each has a real rtr-deeplink adapter. Every other
# name detect_platform()/host_recognition can return (granicus,
# civicclerk, civicplus, legistar, escribe, cablecast, ... including
# civic-specific video vendors like castus/suiteone/civicmedia) is treated
# as a rank-1 "meeting-platform vendor" instead -- see
# docs/MEETING_FINDER.md's own examples ("Vimeo, BoxCast...") for this
# exact split.
_OTHER_VIDEO_HOST_PLATFORMS: FrozenSet[str] = frozenset({"vimeo", "wistia", "boxcast"})

_DIRECT_MEDIA_PLATFORMS: FrozenSet[str] = frozenset({"direct_file"})

_YOUTUBE_PLATFORMS: FrozenSet[str] = frozenset({"youtube"})

# Same tag set `find_platform_link()` scans, plus `embed`/`script` --
# WO-1027's brief calls these out explicitly ("read the raw HTML
# including <iframe src>, <embed>, <script src> ... before visible
# text"), since a vendor account is often reachable only as a script/embed
# src, not a plain <a href> (Vacaville's eScribe frame is a bare
# full-viewport <iframe>, no link text at all).
_SCAN_TAGS = ("a", "iframe", "embed", "video", "source", "script")

# A link to a SPECIFIC meeting/agenda page on the government's OWN site
# (rank 3) -- not a recognized platform (that's rank 1), just a URL shape
# that says "this is one meeting", so Scan (wave 2) has somewhere
# concrete to look next. Deliberately narrow, real shapes already used
# elsewhere in this repo (CivicPlus's own `?EID=`, a dated `/event/{id}/`
# or `/meetings/YYYY-MM-DD-...` page, generic `/agendacenter`-style
# calendars) rather than "any link on the same host".
# WO-1030 conductor review, 2026-09-23, found live on Piedmont, CA's own
# sitemap: `\d+` with no trailing boundary matched the LEADING digit of a
# non-numeric slug -- `/news/events/4th-of-july-parade` matched
# `/events/\d+` (on "4" alone, "th-of-july-parade" just along for the
# ride), so `start.py`'s sitemap starting-point filter picked it as a
# real meeting page. `\d+\b` requires the digits to actually end the
# numeric id (end of string, or a non-word character like `/` or `?`
# right after) -- `/events/12345` and `/events/12345/details` still
# match; `/events/4th-of-july-parade` no longer does.
# WO-1036 (2026-09-23): added a fourth shape, a numeric CivicPlus-style
# page id followed by a meeting/video/watch slug -- e.g. Jurupa Valley,
# CA's real `/422/Meeting-Videos` (only reachable via `/sitemap`/
# `sitemap.xml`; the site's own mega-menu is JS-only, so this sitemap-
# derived shape is the only way `start.py`'s `_sitemap_starting_points()`
# ever sees it). The slug must actually CONTAIN one of the three words,
# not just start with a digit -- `/422/Budget-FY26` must not match.
_OWN_SITE_MEETING_PAGE_RE = re.compile(
    r"(\?eid=\d+\b|/event/\d+\b|/events/\d+\b|/meetings?/\d{4}-\d{1,2}-\d{1,2}"
    r"|/agendacenter\b|/agenda-center\b|/calendar\.aspx\?eid=\d+\b"
    r"|/\d+/[\w-]*(?:meeting|video|watch)[\w-]*\b)",
    re.I,
)

# Granicus's "GovAccess" municipal CMS credits itself in a page footer
# with this exact phrase -- confirmed live 2026-09-23 on Lake Helen, FL
# (`lakehelen.org`, a real `*.granicusgovaccess.net` CNAME target per
# rtr-business `research/wo282_recon.jsonl`): "Created By
# <a href="//www.granicus.com/">Granicus</a> - Connecting People and
# Government". `host_recognition.web_host_hint_for_host()` only ever sees
# a HOSTNAME (the CNAME target itself, e.g.
# `www.lakehelen.org.granicusgovaccess.net`) -- a caller that only has the
# government's own domain in hand (the ordinary case for Identify, since
# DNS CNAME resolution is Start's job, not built yet) never has that
# hostname to check. This page-content signal is the same real fact
# (GovAccess hosting), reachable without a DNS lookup.
_GRANICUS_GOVACCESS_FOOTER_RE = re.compile(
    r"created\s+by\s*(?:<[^>]+>\s*)?granicus", re.I
)

# CivicLive's real footer credit, confirmed BYTE-IDENTICAL live 2026-09-23
# on two independent real first-party-domain tenants -- Piedmont, CA
# (`piedmont.ca.gov`) and Williams, AZ (`williamsaz.gov`, found via
# rtr-business `research/wo282_recon.jsonl`'s own DNS record for it):
#   `... class="label_skin_corporation">City of X | All Rights Reserved |
#   Powered by <a href="https://www.civiclive.com" />CivicLive</a> | ...`
# Two real tenants is short of platform_signatures.csv's own 10-per-
# platform measurement bar (WO-267's own docstring) and no negative
# sample was checked here -- so this is NOT added there, per this WO's
# brief ("measure ... before adding a row; if you can't measure it
# properly, report rather than add"). It's kept here instead, as a
# narrow, explicitly-sourced, reportable heuristic -- see this module's
# own report for the flag to a later WO that DOES do the full measurement.
_CIVICLIVE_FOOTER_RE = re.compile(r"powered\s+by\s*(?:<[^>]+>\s*)?civiclive", re.I)

# The tenant's own `{tenant}.hosted[2].civiclive.com` CDN/asset host,
# confirmed on both Piedmont (`cdnsm5-hosted.civiclive.com` +
# `piedmont.hosted.civiclive.com`-shaped `UserFiles/Servers/Server_<n>/`
# paths) and Williams (`williamsaz.hosted.civiclive.com` appears directly
# in the page body, alongside `cdnsm{1,2,5}-hosted.civiclive.com` CDN
# asset hosts) -- used to recover the real tenant host (this WO's
# `account_url`) from a first-party-domain page.
_CIVICLIVE_TENANT_HOST_RE = re.compile(
    r"https?://([a-z0-9-]+\.hosted2?\.civiclive\.com)", re.I
)

# `platform_signatures.csv`'s own `kind` column (WO-267's docstring):
# "vendor_hostname" rows are a plain "vendor domain anywhere in the page"
# text search -- a re-derivation of `detect_platform()`'s own netloc
# check, MINUS the corporate-host exclusion `_scan_links()` below already
# applies (real, confirmed false positive found building this WO: Lake
# Helen, FL's real Granicus GovAccess footer credit -- "Created By
# <a href="//www.granicus.com/">Granicus</a>" -- contains the literal
# text "granicus.com" and would otherwise fire the CSV's own
# `granicus-vendor-host` signal as if it were a real tenant link, even
# though that specific host is exactly the marketing/corporate link
# `_ALL_CORPORATE_HOSTS` exists to skip). Only `first_party_path` rows
# (a real path/subdomain SHAPE, e.g. eScribe's own `pub-<tenant>.
# escribemeetings.com` or `/player/clip/{id}`) are kept -- these catch a
# genuinely different case `_scan_links()`'s href/src scan can miss (a
# tenant reference embedded in page text/script, not a clickable link).
_FINGERPRINT_KIND_BY_SIGNAL_ID: Dict[str, str] = {
    sig.signal_id: sig.kind for sig in load_signatures()
}


@dataclass(frozen=True)
class Signal:
    """One ranked piece of evidence Identify found. `kind` is one of
    "url_host" (a direct URL/host match, no fetch or page scan needed),
    "fingerprint" (scripts/platform_fingerprints.fingerprint()),
    "civiclive_footer", "vendor_link", "direct_media",
    "own_site_meeting_page", "other_video_host", "youtube_meeting_list",
    "web_host_hint", or "platform_hint"."""

    kind: str
    platform: Optional[str]
    url: Optional[str]
    rank: int
    evidence: str


@dataclass(frozen=True)
class IdentifyResult:
    input_url: str
    final_url: str
    platform: Optional[str]
    account_url: Optional[str]
    supported: Optional[bool]
    web_host_hint: Optional[str]
    signals: List[Signal] = field(default_factory=list)
    youtube_leads: List[str] = field(default_factory=list)
    outcome: Optional[str] = None
    guess_queue_row: Optional[Dict[str, Any]] = None
    page: Optional[FetchResult] = None
    # WO-1041 ("destination check"): set when `gov_name` was given and an
    # off-site vendor/video-host link's own destination doesn't name this
    # government -- see `identify()`'s own `gov_name`/`gov_domain` params
    # and `same_organization_flag()` (app.utils.video_hand_check). `None`
    # when no check was possible/needed. Real confirmed cases this catches
    # (WO-1041 hop-quality follow-up): Gresham SD WI's own site linking a
    # PrimeGov tenant that turns out to be Gresham, OR's; Auburn SD linking
    # a Hooksett, NH Granicus tenant; Laclede Co MO linking Lebanon, MO;
    # Muskegon SD linking a city's CivicClerk tenant.
    destination_mismatch: Optional[str] = None


# Every platform name `host_recognition.UNSUPPORTED_PLATFORMS` knows has
# no rtr-deeplink adapter -- used below to answer "supported=False" for a
# `platform_hint`/found platform that isn't in `_REGISTRY` but IS a known,
# confirmed-no-adapter vendor (rather than just "unrecognized").
_UNSUPPORTED_PLATFORM_NAMES: FrozenSet[str] = frozenset(
    name for _, name in host_recognition.UNSUPPORTED_PLATFORMS
)


def _supported_flag(platform: str) -> Optional[bool]:
    """`True` when a real rtr-deeplink adapter is registered for
    `platform` (only meaningful after `app.platforms.register_all_finders()`
    has run -- the CLI already does this at startup, same as every other
    caller of `resolve_via_platform()`/`get_finder()`), `False` when it's a
    known vendor with no adapter, or `None` when it's neither (an
    unrecognized name, e.g. a mistyped `platform_hint`)."""
    if platform in _REGISTRY:
        return True
    if platform in _UNSUPPORTED_PLATFORM_NAMES:
        return False
    return None


def _classify_url(url: str) -> Tuple[Optional[str], Optional[bool]]:
    """Rule 1 (and rule 2, reapplied to the final URL): `detect_platform()`
    on the URL itself, then `host_recognition`'s host-only and path-only
    checks. No fetch. Returns `(platform, supported)` -- `(None, None)`
    when nothing matches."""
    platform = detect_platform(url)
    if platform != "unknown":
        return (
            platform,
            True,
        )  # detect_platform() only knows adapters it can get_finder() for
    parsed = urlparse(url)
    host_platform, host_supported = host_recognition.platform_for_host(parsed.netloc)
    if host_platform is not None:
        return host_platform, host_supported
    path_platform = host_recognition.platform_for_path(
        parsed.path + (f"?{parsed.query}" if parsed.query else "")
    )
    if path_platform is not None:
        return path_platform, True
    return None, None


def _account_base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


# WO-1036 (2026-09-23): Swagit's tab-slug listing pages (`/commissioners-
# court`, `/study-session-archive`, ...) are empty JS-filled shells on
# `*.new.swagit.com` -- confirmed live across multiple tenants (Wise
# County TX, Ferndale SD WA, Hamilton Southeastern IN, Baltimore County PS
# MD, ...), even fetched headless. Only a numeric `/views/{id}` (a
# tenant's server-rendered listing page) or `/videos/{id}` (a single
# video) path is actually usable. Collapsing either one back to the bare
# tenant root (what `_account_base_url()` always did before this WO) threw
# away the only URL Listing could use and sent it straight to the empty
# tab-slug default instead.
_SWAGIT_SPECIFIC_PATH_RE = re.compile(r"/(?:views|videos)/\d+\b", re.I)

# WO-1036 (2026-09-23, Ryan confirmed): the Cablecast version of the same
# rule -- a specific `/gallery/{id}` (with or without the older
# `/internetchannel/` prefix; see `cablecast.py`'s own `_GALLERY_ID_RE`
# comment) is one governing body's own scoped show list. Collapsing it to
# the bare tenant root would mix in unrelated programming the way
# Virginia Beach, VA's own tenant root does (a live-stream embed plus
# unrelated PEG content) -- the opposite of Swagit's problem (an empty
# page) but the same fix: keep the specific URL, don't collapse it.
_CABLECAST_GALLERY_PATH_RE = re.compile(r"/gallery/\d+\b", re.I)


def _account_url_for_platform(platform: Optional[str], final_url: str) -> str:
    """The account URL to hand to List for `platform`/`final_url` --
    normally the bare host, except when `final_url` already carries a
    platform-specific path that must not be collapsed away. See
    `_SWAGIT_SPECIFIC_PATH_RE`'s and `_CABLECAST_GALLERY_PATH_RE`'s own
    comments for why Swagit and Cablecast each need this."""
    path = urlparse(final_url).path
    if platform == "swagit" and _SWAGIT_SPECIFIC_PATH_RE.search(path):
        return final_url
    if platform == "cablecast" and _CABLECAST_GALLERY_PATH_RE.search(path):
        return final_url
    return _account_base_url(final_url)


def _classify_platform_kind(platform: str) -> Tuple[int, str]:
    """(rank, signal-kind) for a platform `detect_platform()`/fingerprint
    already named -- everything that isn't YouTube, a direct file, or a
    general-purpose video host is a rank-1 meeting-platform vendor link,
    per this module's own docstring."""
    if platform in _YOUTUBE_PLATFORMS:
        return RANK_YOUTUBE_LEAD_ONLY, "youtube_lead"
    if platform in _DIRECT_MEDIA_PLATFORMS:
        return RANK_DIRECT_MEDIA, "direct_media"
    if platform in _OTHER_VIDEO_HOST_PLATFORMS:
        return RANK_OTHER_VIDEO_HOST, "other_video_host"
    return RANK_VENDOR_LINK, "vendor_link"


def _civiclive_first_party_signal(html: str) -> Optional[Signal]:
    """See this module's own `_CIVICLIVE_FOOTER_RE` comment for the two
    real tenants this was measured against. Returns a rank-1 Signal with
    the real tenant host recovered as `url`, or None."""
    if not _CIVICLIVE_FOOTER_RE.search(html):
        return None
    tenant_match = _CIVICLIVE_TENANT_HOST_RE.search(html)
    account_url = f"https://{tenant_match.group(1)}/" if tenant_match else None
    return Signal(
        kind="civiclive_footer",
        platform="civiclive",
        url=account_url,
        rank=RANK_VENDOR_LINK,
        evidence=(
            "page footer carries CivicLive's real credit "
            '("Powered by ... CivicLive") -- measured live on Piedmont, CA '
            "and Williams, AZ, 2026-09-23; not yet in platform_signatures.csv "
            "(only 2 real tenants checked, no negative sample)"
        ),
    )


def _web_host_hint(final_url: str, html: Optional[str]) -> Optional[str]:
    """`host_recognition.web_host_hint_for_host()` on the final URL's own
    host, falling back to the Granicus GovAccess CMS footer credit found
    directly in the page (see `_GRANICUS_GOVACCESS_FOOTER_RE`'s own
    comment for why a page-content check is needed at all: Identify never
    does the DNS CNAME lookup that would otherwise reveal
    `granicusgovaccess.net`)."""
    host = urlparse(final_url).netloc
    hint = host_recognition.web_host_hint_for_host(host)
    if hint:
        return hint
    if html and _GRANICUS_GOVACCESS_FOOTER_RE.search(html):
        return "granicus"
    return None


def _fingerprint_signals(
    html: str, final_url: str, *, exclude_platforms: FrozenSet[str] = frozenset()
) -> List[Signal]:
    """`scripts/platform_fingerprints.fingerprint()`'s matches, one Signal
    per distinct platform (its own highest-confidence signal kept) --
    `first_party_path` rows only (see `_FINGERPRINT_KIND_BY_SIGNAL_ID`'s
    own comment for why `vendor_hostname` rows are skipped), and never for
    a platform `exclude_platforms` already names (the link scan already
    found a real, specific account URL for it -- a bare fingerprint hit
    on the same page adds no value and, being URL-less, would only push a
    worse `account_url` fallback in front of the real one)."""
    best: Dict[str, Tuple[float, str]] = {}
    for platform, signal_id, confidence in fingerprint(html, url=final_url):
        if platform in exclude_platforms:
            continue
        if _FINGERPRINT_KIND_BY_SIGNAL_ID.get(signal_id) != "first_party_path":
            continue
        prior = best.get(platform)
        if prior is None or confidence > prior[0]:
            best[platform] = (confidence, signal_id)
    signals: List[Signal] = []
    for platform, (confidence, signal_id) in best.items():
        rank, kind = _classify_platform_kind(platform)
        if kind == "youtube_lead":
            continue  # fingerprint has no youtube signals today; defensive
        signals.append(
            Signal(
                kind="fingerprint",
                platform=platform,
                url=final_url,
                rank=rank,
                evidence=f"measured page signature {signal_id!r} (confidence {confidence:.2f})",
            )
        )
    return signals


# A looser "date-ish" match than scan.py's own `_DATE_TEXT_RE` (which
# requires a full year) -- a per-meeting YouTube link's own anchor text is
# often just "Sep 8" (current-year meetings, no year printed), which is
# still a real per-item date, not a promo carousel's caption. Kept local
# to this one check rather than loosened in scan.py itself, since
# scan.py's own callers (meeting-page-link detection) want the stricter,
# full-year match to avoid a bare "page 8"/"item 8"-shaped false hit.
_LENIENT_MONTH_DAY_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b",
    re.IGNORECASE,
)


def _youtube_link_has_meeting_context(tag: Any) -> bool:
    """True when a YouTube link `tag` sits in a per-item row/section that
    itself carries a real date or a nearby dated heading -- "several
    meetings each have their own YouTube link" (docs/MEETING_FINDER.md's
    rank-5 row), not just several videos anywhere on the page.

    Fixes a known false positive (this module's own docstring, "known
    false-positive risk"): Piedmont, CA's own homepage links 6 distinct
    YouTube ids from a plain promotional-video carousel with no date
    anywhere near any of them -- confirmed live 2026-09-23 that none of
    those anchors have a table-row/ancestor date context, so this check
    correctly returns False for all six. Reuses `scan.py`'s own date-
    finding helpers (row context + ancestor walk) rather than a third
    date-detection implementation -- see this module's own import."""
    text = tag.get_text(" ", strip=True) if hasattr(tag, "get_text") else ""
    if _extract_date_text(text) or _LENIENT_MONTH_DAY_RE.search(text):
        return True
    title_attr = tag.get("title", "") if hasattr(tag, "get") else ""
    if _extract_date_text(title_attr) or _LENIENT_MONTH_DAY_RE.search(title_attr):
        return True
    if getattr(tag, "name", None) != "a":
        return False
    try:
        row = _row_context(tag)
        if any(_extract_date_text(v) for v in row.values()):
            return True
        return bool(_walk_up_for_date(tag))
    except AttributeError:
        return False


def _scan_links(
    html: str, final_url: str
) -> Tuple[List[Signal], List[str], FrozenSet[str]]:
    """Every `<a href>`/`<iframe src>`/`<embed src>`/`<video|source src>`/
    `<script src>` on the page (rule 3's "raw HTML including iframe/embed/
    script" instruction), classified and ranked. Returns
    `(signals, youtube_urls, dated_youtube_urls)` -- `youtube_urls` is
    every distinct YouTube URL found (channel or per-video), for the
    caller to fold into `youtube_leads`; `dated_youtube_urls` is the
    subset whose own link sits in a per-item dated context (see
    `_youtube_link_has_meeting_context()`), used to decide the
    rank-5-vs-last split without counting a bare promo carousel."""
    soup = BeautifulSoup(html, "html.parser")
    final_no_fragment = urlparse(final_url)._replace(fragment="").geturl()
    own_platform = detect_platform(final_url)

    vendor_best: Dict[str, Signal] = {}
    own_site_meeting_pages = 0
    own_site_example: Optional[str] = None
    youtube_urls: List[str] = []
    dated_youtube_urls: set = set()
    seen_youtube: set = set()

    for tag in soup.find_all(_SCAN_TAGS):
        value = tag.get("href") or tag.get("src")
        if not value:
            continue
        candidate = urljoin(final_url, value.strip())
        if not candidate.lower().startswith(("http://", "https://")):
            continue
        if urlparse(candidate)._replace(fragment="").geturl() == final_no_fragment:
            continue
        candidate_host = urlparse(candidate).netloc.lower()
        if candidate_host in _ALL_CORPORATE_HOSTS:
            continue

        platform = detect_platform(candidate)

        if platform == "youtube":
            if candidate not in seen_youtube:
                seen_youtube.add(candidate)
                youtube_urls.append(candidate)
            if _youtube_link_has_meeting_context(tag):
                dated_youtube_urls.add(candidate)
            continue

        # WO-1033: a same-site redirect to the government's own YouTube
        # channel (CivicPlus's own quick-link-widget shape, confirmed
        # live on Emporia KS's real homepage: `<a href="/youtube"
        # aria-label="YouTube"><img alt="YouTube"></a>`, no visible
        # anchor text) -- `detect_platform()` never recognizes this as
        # "youtube" since the URL itself is on the government's own host,
        # but it's the same kind of lead. See `scan.py`'s own docstring
        # for the same shape handled there.
        if (
            platform == "unknown"
            and candidate_host == urlparse(final_url).netloc.lower()
        ):
            candidate_path = urlparse(candidate).path or "/"
            if (
                _SAME_SITE_SOCIAL_REDIRECT_RE.match(candidate_path)
                and "youtube" in candidate_path.lower()
            ):
                if candidate not in seen_youtube:
                    seen_youtube.add(candidate)
                    youtube_urls.append(candidate)
                continue

        if platform == "unknown":
            if candidate_host == urlparse(final_url).netloc.lower() and (
                _OWN_SITE_MEETING_PAGE_RE.search(candidate)
            ):
                own_site_meeting_pages += 1
                own_site_example = own_site_example or candidate
            continue

        if platform == own_platform:
            continue  # internal navigation on an already-identified platform

        reject = prescreen_homepage_link(html, final_url, candidate)
        if reject is not None:
            continue

        rank, kind = _classify_platform_kind(platform)
        prior = vendor_best.get(platform)
        if prior is None:
            vendor_best[platform] = Signal(
                kind=kind,
                platform=platform,
                url=candidate,
                rank=rank,
                evidence=f"found on the page as a <{tag.name}> link/src",
            )

    signals = list(vendor_best.values())
    if own_site_meeting_pages:
        signals.append(
            Signal(
                kind="own_site_meeting_page",
                platform=None,
                url=own_site_example,
                rank=RANK_OWN_SITE_MEETING_PAGE,
                evidence=(
                    f"{own_site_meeting_pages} meeting/agenda-page-shaped link(s) "
                    "on the government's own site"
                ),
            )
        )
    return signals, youtube_urls, frozenset(dated_youtube_urls)


def _youtube_signal_and_leads(
    youtube_urls: List[str], dated_youtube_urls: FrozenSet[str]
) -> Tuple[Optional[Signal], List[str]]:
    """Splits found YouTube URLs into a rank-5 "meeting list" Signal
    (2+ distinct per-video ids, each sitting in its own dated row/section
    -- "several meetings each with their own YouTube link",
    docs/MEETING_FINDER.md) plus the full lead list, or just the lead
    list when there's only a channel link, a single video, or several
    videos with no per-item date context (a promo carousel -- see
    `_youtube_link_has_meeting_context()`'s own docstring for the real
    Piedmont, CA false positive this guards against). Every URL found
    becomes a lead either way -- Identify never fetches YouTube itself
    (`Fetcher` already refuses to), it only records what it saw."""
    if not youtube_urls:
        return None, []
    dated_video_ids = {
        vid
        for url in youtube_urls
        if url in dated_youtube_urls
        for vid in [extract_video_id(url)]
        if vid
    }
    if len(dated_video_ids) >= 2:
        dated_first = next(u for u in youtube_urls if u in dated_youtube_urls)
        signal = Signal(
            kind="youtube_meeting_list",
            platform="youtube",
            url=dated_first,
            rank=RANK_YOUTUBE_MEETING_LIST,
            evidence=(
                f"{len(dated_video_ids)} distinct YouTube videos, each in its own "
                "dated row/section -- looks like a real meeting list, not a promo "
                "carousel"
            ),
        )
        return signal, list(youtube_urls)
    return None, list(youtube_urls)


# WO-1036 (2026-09-23), Ryan's tie-break rule: on a rank-1 tie between a
# real video-meeting vendor and a pure agenda/minutes CMS that merely
# LINKS to whatever video platform a tenant happens to use (never hosting
# video itself), the video-capable one should win instead of whichever
# link happened to appear first in the page's document order. Each name
# below is confirmed, in its own module's docstring, to be an agenda/
# minutes CMS with no video of its own (BoardDocs, CivicWeb, DestinyHosted
# "AgendaQuick", IQM2, Hyland "OnBase Agenda Online", Municode Meetings
# "MCC Portal", ClerkBase) or to delegate to a DIFFERENT real vendor via
# `resolve_via_platform()` per CLAUDE.md's "platform turns out to be a
# wrapper" convention (Legistar, CivicPlus -- both just link out to
# Granicus). Real cases this fixes: Calvert County PS MD and Wilson
# County Schools TN (a BoardDocs link ranked ahead of a real Swagit
# iframe by document order alone) and Fontana USD CA (CivicWeb ahead of a
# real Swagit iframe on the same page).
_AGENDA_ONLY_VENDOR_PLATFORMS: FrozenSet[str] = frozenset(
    {
        "boarddocs",
        "civicweb",
        "destinyhosted",
        "iqm2",
        "hyland",
        "municode_meetings",
        "clerkbase",
        "legistar",
        "civicplus",
    }
)


def _pick_winner(signals: List[Signal]) -> Optional[Signal]:
    """The lowest-ranked (best) signal whose platform is a real answer --
    never a `youtube_meeting_list`/`youtube_lead` signal (this module's
    own docstring: Identify never hands back YouTube as `platform`). On a
    tie for the best rank, a signal carrying real video/embed evidence
    (`_SCAN_TAGS`'s iframe/embed/video/source, not a plain `<a href>`) or
    a platform this module knows is video-capable beats an agenda-only
    vendor -- see `_AGENDA_ONLY_VENDOR_PLATFORMS`'s own comment. Document
    order (the previous tie-break) is the last resort, not the first."""
    candidates = [
        s
        for s in signals
        if s.platform is not None
        and s.rank not in (RANK_YOUTUBE_MEETING_LIST, RANK_YOUTUBE_LEAD_ONLY)
    ]
    if not candidates:
        return None
    best_rank = min(s.rank for s in candidates)
    tied = [s for s in candidates if s.rank == best_rank]
    if len(tied) == 1:
        return tied[0]
    video_capable = [s for s in tied if s.platform not in _AGENDA_ONLY_VENDOR_PLATFORMS]
    return video_capable[0] if video_capable else tied[0]


async def identify(
    url: str,
    fetcher: Fetcher,
    *,
    platform_hint: Optional[str] = None,
    page: Optional[FetchResult] = None,
    gov_name: Optional[str] = None,
    gov_domain: Optional[str] = None,
) -> IdentifyResult:
    """See this module's own docstring for the full ranking/reuse
    rationale. `page`, when given, is an already-fetched `FetchResult` for
    `url` (or whatever `url` redirects to) -- reused instead of
    refetching, per this WO's brief.

    `gov_name`/`gov_domain` (WO-1041, both optional, default `None` so
    every existing caller is unaffected): when given, and the winning
    signal is an off-site vendor/other-video-host link (`rank` ==
    `RANK_VENDOR_LINK`/`RANK_OTHER_VIDEO_HOST`), the link's own
    destination (`account_url`) is checked with `same_organization_flag()`
    -- the same host/distinctive-name-word check `assess_video_candidate()`
    already applies to a found VIDEO, applied here one step earlier, to
    the ACCOUNT a hop found. See `IdentifyResult.destination_mismatch`'s
    own comment for the real wrong-government hops this catches. Never
    rejects the platform outright (Ryan's "keep at least one" posture) --
    it's still returned, with `destination_mismatch` set, so a caller can
    decide whether to keep walking it or treat it as unconfirmed.
    """

    # Rule 1: URL first, no fetch. `platform_hint` does NOT short-circuit
    # this -- a real URL/host match always beats a caller's belief about
    # what the platform is.
    platform, supported = _classify_url(url)
    if platform is not None:
        return _direct_result(url, url, platform, supported, kind="url_host", page=page)

    # Need the page now. Reuse `page` if the caller already fetched it.
    fetched = page if page is not None else await fetcher.fetch(url, need_links=True)
    final_url = fetched.final_url or url

    # Rule 2: re-check hosts on the FINAL url after redirects.
    if final_url != url:
        platform, supported = _classify_url(final_url)
        if platform is not None:
            return _direct_result(
                url, final_url, platform, supported, kind="url_host", page=fetched
            )

    html = fetched.html
    if not html:
        # Nothing to scan -- report the fetch's own outcome (dns/timeout/
        # blocked/challenge/youtube-not-fetched) as Identify's outcome.
        return IdentifyResult(
            input_url=url,
            final_url=final_url,
            platform=None,
            account_url=None,
            supported=None,
            web_host_hint=None,
            signals=[],
            youtube_leads=[],
            outcome=fetched.outcome,
            guess_queue_row=None,
            page=fetched,
        )

    # Rule 4/9: scan the raw HTML we actually have -- including a
    # links-only Wayback copy read after a challenge (rule 9): the fetch's
    # own `outcome` (e.g. cloudflare-challenge-blocked) is preserved below
    # unless a real platform/account is found despite it.
    signals: List[Signal] = []
    link_signals, youtube_urls, dated_youtube_urls = _scan_links(html, final_url)
    signals.extend(link_signals)
    found_platforms = frozenset(
        s.platform for s in link_signals if s.platform is not None
    )
    signals.extend(
        _fingerprint_signals(html, final_url, exclude_platforms=found_platforms)
    )
    if "civiclive" not in found_platforms:
        civiclive_signal = _civiclive_first_party_signal(html)
        if civiclive_signal is not None:
            signals.append(civiclive_signal)
    youtube_signal, youtube_leads = _youtube_signal_and_leads(
        youtube_urls, dated_youtube_urls
    )
    if youtube_signal is not None:
        signals.append(youtube_signal)

    web_host_hint = _web_host_hint(final_url, html)

    signals.sort(key=lambda s: s.rank)
    winner = _pick_winner(signals)

    if winner is not None:
        supported = _supported_flag(winner.platform)
        account_url = winner.url or _account_url_for_platform(
            winner.platform, final_url
        )
        outcome = (
            OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER if supported is False else None
        )
        # WO-1041 destination check: only for an off-site hop (a vendor
        # tenant or another video host found via a link on the page) --
        # never for a `url_host`/fingerprint/civiclive signal on the
        # government's OWN site, which this same check would false-flag
        # on every plain case (its own domain never shares the account
        # host by construction).
        destination_mismatch = None
        if gov_name and winner.kind in ("vendor_link", "other_video_host"):
            flag = same_organization_flag(account_url, gov_name, gov_domain=gov_domain)
            if flag is not None:
                destination_mismatch = flag.detail
        # A genuine access block found along the way (rule 9's Wayback
        # links-only case) is still worth surfacing even when a platform
        # was found on the recovered links -- but a real answer takes
        # priority over reporting the block as the outcome.
        return IdentifyResult(
            input_url=url,
            final_url=final_url,
            platform=winner.platform,
            account_url=account_url,
            supported=supported,
            web_host_hint=web_host_hint,
            signals=signals,
            youtube_leads=youtube_leads,
            outcome=outcome,
            guess_queue_row=None,
            page=fetched,
            destination_mismatch=destination_mismatch,
        )

    # Rule 7: "platform known, account unknown." A believed vendor --
    # either the caller's own `platform_hint` (Input rows: "for custom
    # domains where the platform is not obvious") or a web-host hint found
    # on this page -- with nothing found on the page to confirm an actual
    # account. Never guess a slug here: name the vendor and the evidence
    # on the guess-ladder queue instead. `platform_hint` takes priority as
    # the named vendor when both are present, since it's the caller's own
    # belief about THIS government, not a generic hosting signal.
    vendor_for_guess_queue = platform_hint or web_host_hint
    guess_queue_row = None
    outcome = fetched.outcome  # preserve a genuine access-block finding, if any
    result_platform = None
    result_supported = None
    if vendor_for_guess_queue:
        source = "platform_hint" if platform_hint else "web-host hint"
        guess_queue_row = {
            "vendor": vendor_for_guess_queue,
            "evidence": (
                f"{source} ({vendor_for_guess_queue}), but no "
                f"{vendor_for_guess_queue} tenant link or account was found on "
                f"{final_url}"
            ),
        }
        outcome = OUTCOME_ACCOUNT_NOT_FOUND
        result_platform = vendor_for_guess_queue
        result_supported = _supported_flag(vendor_for_guess_queue)

    return IdentifyResult(
        input_url=url,
        final_url=final_url,
        platform=result_platform,
        account_url=None,
        supported=result_supported,
        web_host_hint=web_host_hint,
        signals=signals,
        youtube_leads=youtube_leads,
        outcome=outcome,
        guess_queue_row=guess_queue_row,
        page=fetched,
    )


def _direct_result(
    input_url: str,
    final_url: str,
    platform: str,
    supported: Optional[bool],
    *,
    kind: str,
    page: Optional[FetchResult],
    evidence: Optional[str] = None,
) -> IdentifyResult:
    account_url = _account_url_for_platform(platform, final_url)
    rank, _ = _classify_platform_kind(platform)
    signal = Signal(
        kind=kind,
        platform=platform,
        url=final_url,
        rank=rank,
        evidence=evidence or "matched directly from the URL/host, no page scan needed",
    )
    outcome = OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER if supported is False else None
    return IdentifyResult(
        input_url=input_url,
        final_url=final_url,
        platform=platform,
        account_url=account_url,
        supported=supported,
        web_host_hint=None,
        signals=[signal],
        youtube_leads=[],
        outcome=outcome,
        guess_queue_row=None,
        page=page,
    )
