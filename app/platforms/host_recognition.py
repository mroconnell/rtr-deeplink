"""Single, maintained source of truth for recognizing a bare HOST (no
path/query -- just a hostname) as a known meeting/video platform.

WO-1015, part A (2026-09-23). Ryan's framing: `detect_platform()` (this
package's `base.py`) is already used at almost every step of discovery/
enumeration, with good reason -- but a few discovery stages that only
ever see a *hostname* (a DNS CNAME hop, a CT-log subdomain -- never a
full meeting URL) had grown their own hand-copied, drifting vendor-suffix
lists instead of asking this repo's one real platform registry. This
module closes that gap: it is the one place a hostname-only caller should
ask "what platform is this," instead of hand-copying a vendor-domain list
of its own.

Two tiers, in order:

1. `detect_platform()` on a synthetic `https://<host>/` URL. Most
   platforms this repo supports key off the host alone (Granicus,
   Legistar, CivicClerk, CivicPlus, PrimeGov, Swagit, eScribe,
   DestinyHosted, CivicWeb/Diligent, TelVue/peg.tv, Viebit, ClerkBase,
   ChampDS, IQM2, Aurora TV, Town Hall Streams, open.media/OMPnetwork,
   SuiteOne, CivicLive, Municode Meetings, YouTube) -- this function's
   own docstring already documents each branch, and this module
   deliberately does NOT re-derive any of that logic, it only calls it.

2. `_HOST_ONLY_PLATFORMS`, a short, explicitly-commented list of real,
   adapter-backed platforms whose `detect_platform()` branch needs a real
   path or query to confirm a SPECIFIC page (a `/show/{id}`, a real
   `clientID`+`eventID`, a `/medias/{id}`) -- Cablecast, BoxCast,
   BoardDocs, Invintus, Castus, Hyland -- so a bare `https://<host>/`
   correctly, deliberately, comes back "unknown" from tier 1. A hostname-
   only sweep never had a path to begin with, so "is this platform's host
   at all" is the only question it can ever answer -- these hosts are
   single-purpose vendor domains (not general-content sites), so
   recognizing the host alone as "this platform, page unconfirmed" is a
   safe call. Wistia and Vimeo don't need an entry here: both already
   expose a real, host-only predicate (`is_wistia_account_host()`,
   `is_vimeo_host()`) that this module reuses directly rather than
   re-deriving anything.

Hyland is a special case worth calling out explicitly (caught in
conductor review, 2026-09-23): `detect_platform()`'s own Hyland branch
matches on the `/Meetings/ViewMeeting` path ALONE, with no netloc check
at all -- confirmed live across three real customer domains that don't
even share a common suffix (`tucsonaz.hylandcloud.com`,
`mccobagenda.databankcloud.com`, `agendanet.saccounty.gov`). So
`hylandcloud.com` is NOT NECESSARY to identify a Hyland tenant (two of
the three known real tenants aren't even on it) -- but it IS SUFFICIENT:
every real `*.hylandcloud.com` host seen so far (including
`tenant_overrides.csv`'s own 8 pins onto `hylandcloud.com` hosts) is a
genuine Hyland customer, and the old stage-2 `VENDOR_SUFFIXES` list
already matched on it. "Not the only host" and "not a reliable host at
all" are different claims -- only the first is true here, so
`hylandcloud.com` IS in `_HOST_ONLY_PLATFORMS` below. What's still
correctly unrecognized by host: a Hyland customer on `databankcloud.com`,
`saccounty.gov`, or any other domain that isn't `hylandcloud.com` itself
-- those need the real `/Meetings/ViewMeeting` path, which a hostname-
only caller never has.

One platform is deliberately left unrecognized by this module even
though it has a real rtr-deeplink adapter -- "dropped" in the WO-1015
sense (see the PR/BACKLOG_DONE entry for the full no-signal-lost table),
not silently missing:

- Seattle Channel (`seattlechannel.org`): the host is a general city
  broadcast site (news, sports, many non-meeting pages), not a single-
  purpose vendor domain -- `seattlechannel.py`'s own module docstring is
  explicit that only the narrow `/videos?videoid=` shape is claimed, on
  purpose, for exactly this reason. Recognizing the bare host would be a
  materially different (much weaker) signal than every other entry here.

See `UNSUPPORTED_PLATFORMS` below for known vendor domains with NO
rtr-deeplink adapter at all -- a different thing from either list above.

A third, separate thing: `VENDOR_WEB_HOST_HINTS` (Ryan's decision,
2026-09-23 -- see that constant's own comment for the verbatim quote) is
for a host that's a meeting VENDOR's own general-purpose WEBSITE hosting
-- not a meeting platform, and not proof one exists either. Recognizing
a host as this kind of hint is deliberately NOT part of
`platform_for_host()`'s return value (a web host is not a platform
confirmation) -- use `web_host_hint_for_host()` instead, and treat its
answer as a reason to go looking for that vendor's real platform tenant,
never as a match on its own.
"""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from .base import detect_platform
from .boarddocs import _HOST as _BOARDDOCS_HOST
from .sliq_harmony import _HOST_RE as _SLIQ_HARMONY_HOST_RE
from .vimeo import is_vimeo_host
from .wistia import is_wistia_account_host

# ---------------------------------------------------------------------
# Tier 2: real, adapter-backed platforms whose `detect_platform()` branch
# needs a path/query this module never has. Each suffix below is the
# SAME host string already checked inside that platform's own module (or
# base.py's own branch for it) -- copied here as a plain string, not as
# re-derived matching logic, since a bare-suffix check has no "logic" to
# duplicate. See this module's own docstring above for why these are
# safe to recognize by host alone (single-purpose vendor domains) where
# Seattle Channel is not.
_HOST_ONLY_PLATFORMS: Tuple[Tuple[str, str], ...] = (
    # Cablecast -- base.py's own cablecast branch checks "cablecast.tv"
    # in netloc (plus a `/show/{id}`-shaped path); real tenant example:
    # detroit-vod.cablecast.tv (Detroit, MI -- see cablecast.py).
    ("cablecast.tv", "cablecast"),
    # BoxCast -- boxcast.py's own `parse_boxcast_id()` checks the bare
    # host is exactly boxcast.tv/www.boxcast.tv (plus a real
    # /view|view-embed|channel/{id} path); real tenants live on the bare
    # boxcast.tv domain itself (Wilmington OH, Hondo TX, ...).
    ("boxcast.tv", "boxcast"),
    ("www.boxcast.tv", "boxcast"),
    # BoardDocs -- reuses boarddocs.py's own `_HOST` constant directly
    # (imported above) rather than hand-copying the string; real tenant
    # path shape is `/{st}/{slug}/Board.nsf/...` on this one shared host.
    (_BOARDDOCS_HOST, "boarddocs"),
    # Invintus -- invintus.py's own `is_invintus_meeting_url()`/
    # `parse_invintus_ids()` check `netloc.endswith("invintus.com")` as
    # their own first step (plus a real clientID+eventID query); real
    # host: player.invintus.com.
    ("invintus.com", "invintus"),
    # Castus -- base.py's own castus branch checks "castus.tv" in netloc
    # (plus "/vod/" in path); real tenant: cloud.castus.tv (Billings, MT).
    ("castus.tv", "castus"),
    # Hyland "OnBase Agenda Online" -- base.py's own Hyland branch matches
    # on the `/Meetings/ViewMeeting` path alone, no netloc check at all,
    # because real tenants also live on `databankcloud.com`/`saccounty.gov`
    # (not just this domain). But `hylandcloud.com` itself IS a reliable,
    # SUFFICIENT signal even without a path -- every real
    # `*.hylandcloud.com` host seen so far (real tenant:
    # tucsonaz.hylandcloud.com, Tucson AZ; also 8 tenant_overrides.csv
    # pins) is a genuine Hyland customer, and the old stage-2
    # VENDOR_SUFFIXES list already matched on it (conductor review,
    # 2026-09-23 -- see this module's own docstring for the fuller
    # necessary-vs-sufficient reasoning). A Hyland tenant on any OTHER
    # domain still can't be recognized by host alone.
    ("hylandcloud.com", "hyland"),
)

# Sliq Harmony -- not a plain suffix like the entries above: real hosts
# are `sg001-harmony.sliq.net`/`sg002-harmony.sliq.net`/etc. (a numbered-
# server PREFIX joined to "harmony" with a hyphen, not a dotted
# subdomain), so a `str.endswith("." + suffix)` check can never match it.
# `sliq_harmony.py` already owns the real regex for this
# (`_HOST_RE`, imported above) -- reused directly rather than
# re-derived, same pattern as this module already uses for Vimeo/Wistia's
# own host predicates just below. WO-1021 (2026-09-23): confirmed this is
# a single-purpose vendor host (every real tenant is a path segment on
# one of these numbered hosts -- see that module's own docstring), so a
# bare-host match is a safe "this platform, page unconfirmed" answer,
# same reasoning as Hyland above (`is_sliq_harmony_url()`'s own path
# check needs a real `/{tenant}/Harmony/...` path a hostname-only caller
# never has).

# ---------------------------------------------------------------------
# Known vendor/meeting-platform domains with NO rtr-deeplink adapter --
# seeded from the dns_ctlog_sweep_2026-09-17 VENDOR_SUFFIXES list's
# unsupported entries (WO-1015). Every entry needs a one-line source
# comment so a later reader isn't left guessing whether "no adapter" was
# ever actually checked.
UNSUPPORTED_PLATFORMS: Tuple[Tuple[str, str], ...] = (
    # NovusAGENDA -- named explicitly in CLAUDE.md's WO-1015 brief as a
    # known vendor with no rtr-deeplink adapter; also confirmed in
    # ~/Documents/rtr-business/research/UNSUPPORTED_PLATFORMS.md
    # (`{tenant}.novusagenda.com`, "Confirmed dead end (thin sample)":
    # 2 real agenda-only tenants, no video) as of WO-1021 (2026-09-23).
    ("novusagenda.com", "novusagenda"),
    # Simbli (eBoardSolutions) -- rtr-business's UNSUPPORTED_PLATFORMS.md,
    # "Confirmed dead end": ENUMERATION_METHODS.md §312 (WO-291,
    # 2026-09-12) found 39 real governments on Simbli, zero with any video
    # field (agenda-only). WO-1018 (2026-09-23).
    ("simbli.eboardsolutions.com", "simbli"),
    # AgendaSuite -- rtr-business's UNSUPPORTED_PLATFORMS.md, "Unconfirmed
    # candidate": real path-based-tenancy domain (2 governments tagged in
    # jurisdiction_coverage.csv), video capability unconfirmed either way,
    # no rtr-deeplink adapter exists. WO-1018 (2026-09-23).
    ("agendasuite.org", "agendasuite"),
    # IBM Video Streaming -- rtr-business's UNSUPPORTED_PLATFORMS.md,
    # "Confirmed real, not yet built": live 2026-09-18 against Lafayette
    # Consolidated Government LA (real enumerable channel + a real
    # `.m3u8`), one government so far -- not built pending a 2nd tenant.
    # WO-1018 (2026-09-23).
    ("video.ibm.com", "ibm_video_streaming"),
    # Laserfiche Cloud -- rtr-business's UNSUPPORTED_PLATFORMS.md,
    # "Laserfiche WebLink (incl. Laserfiche Cloud)", "Confirmed real, not
    # yet built (deferred)": 1 real video example (Jefferson County WA,
    # Zoom MP4 + WebVTT) out of 20 repositories opened; deferred since
    # every other studied government already has its real video
    # elsewhere. `portal.laserfiche.com` is the Cloud-hosted variant's
    # shared host (the self-hosted WebLink variant has no fixed host, so
    # it isn't listed here). WO-1018 (2026-09-23).
    ("portal.laserfiche.com", "laserfiche_cloud"),
)

# ---------------------------------------------------------------------
# Ryan's decision, 2026-09-23, verbatim: "granicusgovaccess.net is a
# hint/signature for granicus platform sometimes but it is in fact a web
# host." So this is neither a platform (`_HOST_ONLY_PLATFORMS`) nor an
# unsupported vendor (`UNSUPPORTED_PLATFORMS`) -- it's a THIRD kind of
# thing, a vendor's own general-purpose website hosting, which only ever
# HINTS that a Granicus tenant might be nearby, never confirms one.
# `platform_for_host()` deliberately does NOT return this as a platform
# match (a web host is not a platform confirmation) -- see
# `web_host_hint_for_host()` below, which a caller uses as a reason to
# go looking for a real Granicus tenant, not as a hit on its own.
VENDOR_WEB_HOST_HINTS: Tuple[Tuple[str, str], ...] = (
    ("granicusgovaccess.net", "granicus"),
)


# ---------------------------------------------------------------------
# Path-only platform signatures (WO-1021, 2026-09-23): a URL PATH shape
# that identifies a platform regardless of which domain it lives on --
# confirms a self-hosted, first-party-government-domain tenant of a
# vendor whose other detection is normally host-based (base.py's own
# `detect_platform()` netloc checks don't fire for these, since the
# domain is the government's own, not the vendor's).
#
# Two of `detect_platform()`'s own branches are ALREADY netloc-
# independent path checks -- CivicPlus AgendaCenter (`path.startswith
# ("/agendacenter")`) and Hyland "OnBase Agenda Online"
# (`"/meetings/viewmeeting" in path`) -- so `platform_for_path()` below
# calls `detect_platform()` on a neutral placeholder host first and picks
# those two up for free, rather than re-deriving them a second time. The
# four entries below are the ones base.py does NOT (yet) recognize
# without a real netloc match -- moved here verbatim (not re-derived)
# from wo282_recon.py's old `_PATH_SHAPE_PLATFORMS` (itself copied from
# wo147_access_ladder_sweep.py/wo268, per that script's own history), the
# same source that fed wo282_classify.py's `vendor_platform_for_url()`.
_PATH_ONLY_PLATFORMS: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"/citizens/", re.I), "iqm2"),
    (re.compile(r"/portal/meetinginformation\.aspx", re.I), "civicclerk"),
    (re.compile(r"/archive\.aspx\?amid=", re.I), "legistar"),
    (re.compile(r"/viewpublisher\.php", re.I), "granicus"),
    (re.compile(r"/mediaplayer\.php", re.I), "granicus"),
)

# Canonical first-party probe paths for wo282_targeted.py's fallback
# ladder (rung 3): one concrete, blindly-fetchable example path per
# `detect_platform()`-native path-only branch (CivicPlus AgendaCenter,
# Hyland AgendaOnline) -- these are the only two signatures in this
# module worth blind-probing on an arbitrary first-party domain, since
# they're confirmed real, common self-hosted shapes (see base.py's own
# comments on each). The four `_PATH_ONLY_PLATFORMS` entries above are
# NOT probe targets -- they only ever confirm a platform on a URL this
# repo already has in hand (a sitemap/archive/homepage-link URL), never a
# path worth guessing blind. Moved here verbatim from wo282_targeted.py's
# own hand-copied `FIRST_PARTY_PROBE_PATHS` (WO-1021, 2026-09-23).
FIRST_PARTY_PROBE_PATHS: Tuple[str, ...] = (
    "/AgendaCenter",
    "/AgendaOnline/Meetings/ViewMeeting",
)


def platform_for_path(path: str) -> Optional[str]:
    """Classify a URL PATH alone (no real host in hand) by platform --
    for a first-party-domain tenant of a vendor whose adapter/base.py
    detection is normally host-based. Checks `detect_platform()` against
    a neutral placeholder host first (covers CivicPlus AgendaCenter and
    Hyland AgendaOnline, whose base.py branches are already netloc-
    independent), then `_PATH_ONLY_PLATFORMS` for the signatures base.py
    doesn't yet check without a real netloc match. Returns `None` if
    nothing matches -- this function never distinguishes "no adapter"
    from "unrecognized" the way `platform_for_host()` does, since a path
    shape alone was never checked against `UNSUPPORTED_PLATFORMS`."""
    if not path:
        return None
    if not path.startswith("/"):
        path = "/" + path
    neutral_url = f"https://first-party-government-domain.invalid{path}"
    detected = detect_platform(neutral_url)
    if detected != "unknown":
        return detected
    for rx, platform in _PATH_ONLY_PLATFORMS:
        if rx.search(path):
            return platform
    return None


def platform_for_host(host: str) -> Tuple[Optional[str], Optional[bool]]:
    """Classify a bare HOSTNAME (no path/query) by platform.

    Returns `(platform, supported)`:
    - `(name, True)` -- a real rtr-deeplink adapter exists for this
      platform, either because `detect_platform()` itself recognizes a
      synthetic `https://<host>/` URL, or because the host matches one of
      the path-dependent-but-adapter-backed platforms in
      `_HOST_ONLY_PLATFORMS` / the Wistia/Vimeo host predicates.
    - `(name, False)` -- a known vendor domain with NO rtr-deeplink
      adapter (see `UNSUPPORTED_PLATFORMS`).
    - `(None, None)` -- unrecognized. This is also the answer for a host
      in `VENDOR_WEB_HOST_HINTS` (e.g. `granicusgovaccess.net`) --
      deliberately: a vendor's own website hosting is not a platform
      confirmation, only a hint (see `web_host_hint_for_host()`), so it
      must never come back from this function as if it were a match.
    """
    host = host.strip().lower().rstrip(".")
    if not host:
        return None, None

    synthetic_url = f"https://{host}/"
    detected = detect_platform(synthetic_url)
    if detected != "unknown":
        return detected, True

    for suffix, platform in _HOST_ONLY_PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return platform, True

    if _SLIQ_HARMONY_HOST_RE.match(host):
        return "sliq_harmony", True

    if is_vimeo_host(host):
        return "vimeo", True
    if is_wistia_account_host(host):
        return "wistia", True

    for suffix, platform in UNSUPPORTED_PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return platform, False

    return None, None


def web_host_hint_for_host(host: str) -> Optional[str]:
    """A vendor name if `host` is known to be that vendor's own general-
    purpose WEBSITE hosting (`VENDOR_WEB_HOST_HINTS`) -- e.g.
    `granicusgovaccess.net` hints "granicus". This is NOT a platform
    match: Ryan's decision (2026-09-23, verbatim) is "granicusgovaccess.net
    is a hint/signature for granicus platform sometimes but it is in fact
    a web host." A caller should treat a non-None return as a reason to
    go look for a real tenant of that platform elsewhere (another CNAME
    hop, another record), never as a hit to report on its own -- see
    `platform_for_host()`, which never returns a `VENDOR_WEB_HOST_HINTS`
    entry as a platform.

    Matches by plain substring, not just suffix -- confirmed live
    (2026-09-23 replay) that a real Akamai `edgekey.net` CNAME target can
    carry the vendor's hint domain as a MIDDLE label
    (`san-h2.granicusgovaccess.net.edgekey.net`, from a real Alameda, CA
    CNAME chain), not just as the host's own suffix. That's the same
    substring semantics the old stage-2 `VENDOR_SUFFIXES` list already
    used for this exact entry -- kept here so this hint doesn't quietly
    become narrower than what was already being caught."""
    host = host.strip().lower().rstrip(".")
    if not host:
        return None
    for suffix, vendor in VENDOR_WEB_HOST_HINTS:
        if suffix in host:
            return vendor
    return None


def platform_for_url(url: str) -> Tuple[Optional[str], Optional[bool]]:
    """Convenience wrapper: `platform_for_host()` on a full URL's own
    host. Prefer calling `detect_platform()` directly when a real
    path/query is available -- this exists for a caller that already has
    a full URL in hand but wants the same three-way (adapter/no-adapter/
    unrecognized) answer `platform_for_host()` gives, e.g. to fall back
    to the host-only answer when `detect_platform()` itself says
    "unknown" for lack of a matching path."""
    return platform_for_host(urlparse(url).netloc)
