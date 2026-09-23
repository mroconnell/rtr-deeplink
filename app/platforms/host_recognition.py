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
   BoardDocs, Invintus, Castus -- so a bare `https://<host>/` correctly,
   deliberately, comes back "unknown" from tier 1. A hostname-only sweep
   never had a path to begin with, so "is this platform's host at all"
   is the only question it can ever answer -- these hosts are single-
   purpose vendor domains (not general-content sites), so recognizing
   the host alone as "this platform, page unconfirmed" is a safe call.
   Wistia and Vimeo don't need an entry here: both already expose a
   real, host-only predicate (`is_wistia_account_host()`,
   `is_vimeo_host()`) that this module reuses directly rather than
   re-deriving anything.

Two platforms are deliberately left unrecognized by this module even
though they have real rtr-deeplink adapters -- both are "dropped" in the
WO-1015 sense (see the PR/BACKLOG_DONE entry for the full no-signal-lost
table), not silently missing:

- Seattle Channel (`seattlechannel.org`): the host is a general city
  broadcast site (news, sports, many non-meeting pages), not a single-
  purpose vendor domain -- `seattlechannel.py`'s own module docstring is
  explicit that only the narrow `/videos?videoid=` shape is claimed, on
  purpose, for exactly this reason. Recognizing the bare host would be a
  materially different (much weaker) signal than every other entry here.
- Hyland "OnBase Agenda Online" (`hylandcloud.com`): `detect_platform()`'s
  own Hyland branch matches on the `/Meetings/ViewMeeting` path ALONE,
  with no netloc check at all -- confirmed live across three real
  customer domains that don't even share a common suffix
  (`tucsonaz.hylandcloud.com`, `mccobagenda.databankcloud.com`,
  `agendanet.saccounty.gov`). There is no reliable *host* signal for this
  platform at all, so a host-only helper has nothing correct to say about
  it either way.

See `UNSUPPORTED_PLATFORMS` below for known vendor domains with NO
rtr-deeplink adapter at all -- a different thing from either list above.
"""

from typing import Optional, Tuple
from urllib.parse import urlparse

from .base import detect_platform
from .boarddocs import _HOST as _BOARDDOCS_HOST
from .vimeo import is_vimeo_host
from .wistia import is_wistia_account_host

# ---------------------------------------------------------------------
# Tier 2: real, adapter-backed platforms whose `detect_platform()` branch
# needs a path/query this module never has. Each suffix below is the
# SAME host string already checked inside that platform's own module (or
# base.py's own branch for it) -- copied here as a plain string, not as
# re-derived matching logic, since a bare-suffix check has no "logic" to
# duplicate. See this module's own docstring above for why these five are
# safe to recognize by host alone (single-purpose vendor domains) where
# Seattle Channel and Hyland are not.
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
)

# ---------------------------------------------------------------------
# Known vendor/meeting-platform domains with NO rtr-deeplink adapter --
# seeded from the dns_ctlog_sweep_2026-09-17 VENDOR_SUFFIXES list's
# unsupported entries (WO-1015). Every entry needs a one-line source
# comment so a later reader isn't left guessing whether "no adapter" was
# ever actually checked.
UNSUPPORTED_PLATFORMS: Tuple[Tuple[str, str], ...] = (
    # NovusAGENDA -- named explicitly in CLAUDE.md's WO-1015 brief as a
    # known vendor with no rtr-deeplink adapter; not in
    # docs/../UNSUPPORTED_PLATFORMS.md as of 2026-09-23 (that file is a
    # dead-end/candidate log, not an exhaustive registry) -- flagged here
    # as a gap in that doc, not acted on further (out of this WO's scope).
    ("novusagenda.com", "novusagenda"),
)

# A single host that this WO's brief explicitly says NOT to decide --
# `granicusgovaccess.net` is called "website-CMS hosting noise, not a
# meeting platform" by one write-up, but that hasn't been confirmed
# against real data, and Ryan's framing here is "ask once with the
# trade-off stated," not "guess." Kept OUT of both lists above on
# purpose so `platform_for_host()` returns the honest "don't know"
# rather than silently picking a side either way. See the WO-1015
# report/PR for the question as put to Ryan.
AMBIGUOUS_HOSTS: Tuple[str, ...] = ("granicusgovaccess.net",)


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
    - `(None, None)` -- unrecognized, OR one of the explicitly-flagged
      `AMBIGUOUS_HOSTS` this WO declines to classify either way.
    """
    host = host.strip().lower().rstrip(".")
    if not host:
        return None, None
    if host in AMBIGUOUS_HOSTS:
        return None, None

    synthetic_url = f"https://{host}/"
    detected = detect_platform(synthetic_url)
    if detected != "unknown":
        return detected, True

    for suffix, platform in _HOST_ONLY_PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return platform, True

    if is_vimeo_host(host):
        return "vimeo", True
    if is_wistia_account_host(host):
        return "wistia", True

    for suffix, platform in UNSUPPORTED_PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return platform, False

    return None, None


def platform_for_url(url: str) -> Tuple[Optional[str], Optional[bool]]:
    """Convenience wrapper: `platform_for_host()` on a full URL's own
    host. Prefer calling `detect_platform()` directly when a real
    path/query is available -- this exists for a caller that already has
    a full URL in hand but wants the same three-way (adapter/no-adapter/
    unrecognized) answer `platform_for_host()` gives, e.g. to fall back
    to the host-only answer when `detect_platform()` itself says
    "unknown" for lack of a matching path."""
    return platform_for_host(urlparse(url).netloc)
