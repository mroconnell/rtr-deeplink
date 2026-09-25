"""The tenant key: which piece of a URL tells one customer apart from
another on a shared website.

Ryan's definition (2026-09-25, rtr-discovery's SHARED_WEBSITE_TENANTS.md):
a tenant is one customer's meeting listing -- usually a whole website,
and on a shared website (many governments on one host) one customer's
slice of it. The "tenant key" is the piece of the address that picks out
that slice. It is defined once, here, next to the adapters and the
`tenant_overrides.csv` pins, so rtr-discovery's walkers and this repo's
pins cannot describe the same tenant two different ways again. That is
what happened in rtr-discovery's FINDING-23: Town Square's Cablecast pins
matched on `site=N`, the walker built show URLs without `site=`, and
those shows got no government for weeks.

    tenant_key(url)   ""    a single-website platform: the whole host
                            is the tenant
                      "..." the key on a shared website (the bare value:
                            `atlantaga`, `4879615486`, `site=8`)
                      None  no tenant defined: out of scope (YouTube,
                            Vimeo, file-sharing hosts), or a shared-host
                            URL that does not carry its key (a Cablecast
                            show URL with no `site=`, a BoxCast `/view/`
                            link). None never means "the whole host".
    tenant_name(url)  host, or `host#key`; None when tenant_key is None.

Standard library only, so rtr-discovery can import it without pulling in
aiohttp or yt-dlp. Every rule below copies the tenant parsing its own
adapter already does (the adapter file is named on each rule) and was
checked against real URLs and real pin rows -- see
`tests/test_tenant_key.py`. Keys are compared case-insensitively by the
pin matcher (`resolver._match_override()` lowercases both sides), so a
path slug is lowercased here; ids that are case-sensitive at the vendor
(TelVue org tokens) keep their case.
"""

import re
from typing import Callable, Dict, FrozenSet, Optional
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Out of scope: no tenant defined (None).
#
# YouTube and Vimeo are out of scope by Ryan's decision. The rest are the
# `MULTI_GOV_HOSTS` entries (app/utils/gov_registry/registry.py) that have
# no adapter and no listing a walker could read -- a file-sharing or
# social host is not one customer's meeting listing. Their pins, where
# any exist, are per-file (drive.google.com has one).
OUT_OF_SCOPE_HOSTS: FrozenSet[str] = frozenset(
    {
        "www.youtube.com",
        "youtube.com",
        "youtu.be",
        "m.youtube.com",
        "vimeo.com",
        "player.vimeo.com",
        "www.vimeo.com",
        "facebook.com",
        "fb.watch",
        "livestream.com",
        "soundcloud.com",
        "drive.google.com",
        "dropbox.com",
        "sharepoint.com",
    }
)

# Shared, but ONE listing: a single customer (a regional station or a
# shared account) publishes several governments' meetings on one listing,
# and only the individual meeting says which government it is. The whole
# host is the tenant (""), and its pins are per-meeting pins inside it.
# Listed so the classification is explicit; `tenant_key()` would return
# "" for them anyway.
SHARED_SINGLE_LISTING_HOSTS: FrozenSet[str] = frozenset(
    {
        # AMSVA's Wistia account: several Virginia governments, per-video
        # pins (`external_id=wistia:{id}`). See wistia.py.
        "amsva.wistia.com",
        # LMC Media's Swagit tenant: Town and Village of Mamaroneck,
        # per-video pins (`/videos/{id}`).
        "lmctvny.new.swagit.com",
        # Lake Minnetonka Communications Commission: 7+ cities, told apart
        # only by show title, per-show pins. Every show URL carries
        # `site=1`; it does not separate governments.
        "reflect-lmcc.cablecast.tv",
        # Merrimack TV: the town and its School Board on one vault,
        # per-show pins.
        "reflect-townofmerrimack.cablecast.tv",
    }
)

# Hosts that answer under two names for the same tenants.
_HOST_ALIASES: Dict[str, str] = {
    "www.townhallstreams.com": "townhallstreams.com",
    "www.spectrumstream.com": "spectrumstream.com",
    "playapi.champds.com": "play.champds.com",
}


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return _HOST_ALIASES.get(host, host)


def _query(url: str) -> Dict[str, str]:
    """Query parameters with lowercased names, first value each."""
    parsed = parse_qs(urlparse(url).query, keep_blank_values=False)
    return {k.lower(): v[0] for k, v in parsed.items() if v}


def _segments(path: str) -> list:
    return [s for s in path.split("/") if s]


# --- ChampDS (champds.py): `/{customer}/event/{id}`. The same customer
# appears as the second segment of ChampDS's own `/CAPTION/`, `/ATT/` and
# `/DOWNLOAD-MEDIA/` paths, and in the VOD2 stream path
# (`securestream10.champds.com/VOD/event/{Customer}/...`, WO-1045).
_CHAMPDS_PREFIX_SEGMENTS = frozenset({"caption", "att", "download-media"})
_CHAMPDS_NOT_A_CUSTOMER = frozenset({"_common", "vod", "event"})


def _champds(url: str) -> Optional[str]:
    segs = _segments(urlparse(url).path)
    if segs and segs[0].lower() in _CHAMPDS_PREFIX_SEGMENTS:
        segs = segs[1:]
    if not segs or segs[0].lower() in _CHAMPDS_NOT_A_CUSTOMER:
        return None
    return segs[0].lower()


_CHAMPDS_VOD_RE = re.compile(r"^/VOD/event/([^/]+)/", re.IGNORECASE)


def _champds_stream(url: str) -> Optional[str]:
    match = _CHAMPDS_VOD_RE.match(urlparse(url).path)
    return match.group(1).lower() if match else None


# --- Invintus (invintus.py): `/?clientID={N}&eventID={M}`. The client is
# the tenant; an `eventID=` pin is a per-meeting pin inside it.
def _invintus(url: str) -> Optional[str]:
    client = _query(url).get("clientid", "")
    return client if client.isdigit() else None


# --- Cablecast stations shared by site (cablecast.py): `?site={N}` names
# one government's own site on the station. The key keeps the `site=`
# name, per Ryan's example (`site=8`). A URL with no `site=` cannot be
# placed -- FINDING-23 -- so it returns None rather than the whole host.
def _cablecast_site(url: str) -> Optional[str]:
    site = _query(url).get("site", "")
    return f"site={site}" if site.isdigit() else None


# --- Castus (castus.py): `/vod/{slug}/...`, and the older hash route
# `/vod/#/{slug}/...` (the slug is then in the fragment).
_CASTUS_PATH_RE = re.compile(r"^/vod/([^/?#]+)", re.IGNORECASE)
_CASTUS_FRAGMENT_RE = re.compile(r"^/([^/?#]+)")


def _castus(url: str) -> Optional[str]:
    parsed = urlparse(url)
    match = _CASTUS_PATH_RE.match(parsed.path)
    if match:
        return match.group(1).lower()
    if parsed.path.rstrip("/").lower() == "/vod":
        frag = _CASTUS_FRAGMENT_RE.match(parsed.fragment or "")
        if frag:
            return frag.group(1).lower()
    return None


# --- TelVue (telvue.py): `/player/{org_token}/...`. The org token is the
# tenant, not the playlist -- see `telvue_org_token()`.
_TELVUE_ORG_TOKEN_RE = re.compile(r"/player/([^/?#]+)")


def telvue_org_token(url: str) -> Optional[str]:
    """TelVue's org token from a `/player/{token}/...` URL, case kept.

    The one definition: telvue.py's `_org_token_from_url()` uses this.
    The token is the tenant because it is the one listing every TelVue
    URL names -- a `/media/{id}` link, which is most of them, carries no
    playlist -- and it is what `telvue.account_url_for()` lists. Some
    tokens are regional stations carrying several governments (RVTV,
    CMNtv, Schopeg, C-NET); their per-government playlists are narrower
    pins inside the station's tenant.
    """
    match = _TELVUE_ORG_TOKEN_RE.search(urlparse(url).path)
    return match.group(1) if match else None


# --- Sliq Harmony (sliq_harmony.py): `/{5-digit tenant}/Harmony/...`.
_SLIQ_HOST_RE = re.compile(r"^(?:[a-z0-9]+-)?harmony\.sliq\.net$")
_SLIQ_PATH_RE = re.compile(r"^/(\d{5})(?:/|$)")


def _sliq(url: str) -> Optional[str]:
    match = _SLIQ_PATH_RE.match(urlparse(url).path)
    return match.group(1) if match else None


# --- BoardDocs (boarddocs.py): `/{state}/{slug}/Board.nsf/...`. Both
# parts, since a slug alone could repeat across states.
_BOARDDOCS_RE = re.compile(r"^/([A-Za-z]+)/([A-Za-z0-9_-]+)(?:/|$)")


def _boarddocs(url: str) -> Optional[str]:
    match = _BOARDDOCS_RE.match(urlparse(url).path)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}".lower()


# --- ClerkBase (clerkbase.py): `clerkshq.com/{Place}-{ST}` or
# `/Content/{Place}-{ST}/...`. Lowercased, as the pins are.
_CLERKBASE_RE = re.compile(r"/([A-Za-z]+-[A-Za-z]{2})(?:[/?#]|$)")


def _clerkbase(url: str) -> Optional[str]:
    match = _CLERKBASE_RE.search(urlparse(url).path)
    return match.group(1).lower() if match else None


# --- BoxCast (boxcast.py): the tenant is the account's channel id. Only a
# `/channel/{id}` URL names it. A `/view/{x}` or `/view-embed/{x}` URL may
# hold a channel id OR a one-broadcast id, and boxcast.py tells them apart
# only by asking BoxCast's API, so from the URL alone it is None.
_BOXCAST_CHANNEL_RE = re.compile(r"^/channel/([^/?#]+)", re.IGNORECASE)


def _boxcast(url: str) -> Optional[str]:
    match = _BOXCAST_CHANNEL_RE.match(urlparse(url).path)
    return match.group(1).lower() if match else None


# --- Town Hall Streams (townhallstreams.py): `stream.php?location_id={N}`,
# and `town.php?id={N}` for the same town's listing.
def _townhallstreams(url: str) -> Optional[str]:
    parsed = urlparse(url)
    query = _query(url)
    value = query.get("location_id", "")
    if not value and parsed.path.lower().endswith("/town.php"):
        value = query.get("id", "")
    return value if value.isdigit() else None


# --- DestinyHosted (destinyhosted.py): `/{id}/agenda/...` and
# `agenda_publish.cfm?id={id}` carry the same customer id (checked live
# 2026-09-25: 24263 is the City of Chandler, AZ in both shapes).
_DESTINY_PATH_RE = re.compile(r"^/(\d+)(?:/|$)")


def _destinyhosted(url: str) -> Optional[str]:
    parsed = urlparse(url)
    match = _DESTINY_PATH_RE.match(parsed.path)
    if match:
        return match.group(1)
    if parsed.path.lower().endswith("/agenda_publish.cfm"):
        value = _query(url).get("id", "")
        return value if value.isdigit() else None
    return None


# --- SpectrumStream (spectrumstream.py): `/streaming/{slug}/...`.
_SPECTRUM_RE = re.compile(r"^/streaming/([^/?#]+)", re.IGNORECASE)


def _spectrumstream(url: str) -> Optional[str]:
    match = _SPECTRUM_RE.match(urlparse(url).path)
    return match.group(1).lower() if match else None


# Host -> key rule for every shared website with a defined key.
KEYED_SHARED_HOSTS: Dict[str, Callable[[str], Optional[str]]] = {
    "play.champds.com": _champds,
    "securestream10.champds.com": _champds_stream,
    "player.invintus.com": _invintus,
    "reflect-tst-mn.cablecast.tv": _cablecast_site,
    "reflect-ccx.cablecast.tv": _cablecast_site,
    "cloud.castus.tv": _castus,
    "videoplayer.telvue.com": telvue_org_token,
    "go.boarddocs.com": _boarddocs,
    "clerkshq.com": _clerkbase,
    "boxcast.tv": _boxcast,
    "townhallstreams.com": _townhallstreams,
    "public.destinyhosted.com": _destinyhosted,
    "spectrumstream.com": _spectrumstream,
}


def _rule_for(host: str) -> Optional[Callable[[str], Optional[str]]]:
    rule = KEYED_SHARED_HOSTS.get(host)
    if rule is None and _SLIQ_HOST_RE.match(host):
        rule = _sliq
    return rule


def is_keyed_shared_host(host: str) -> bool:
    """True when `host` is a shared website whose tenants have a key."""
    host = _HOST_ALIASES.get(host.lower(), host.lower())
    return _rule_for(host) is not None


def tenant_key(url: str) -> Optional[str]:
    """See this module's docstring for the three kinds of answer."""
    host = _host(url)
    if not host:
        return None
    if host in OUT_OF_SCOPE_HOSTS:
        return None
    if host == "www.utah.gov" and urlparse(url).path.lower().startswith("/pmn/"):
        # Utah's Public Meeting Notice site: every Utah government on one
        # host, pinned per notice (139 pins); no listing is walked per
        # government here.
        return None
    rule = _rule_for(host)
    if rule is None:
        return ""
    return rule(url)


def tenant_name(url: str) -> Optional[str]:
    """The tenant's name: the host alone when the key is blank, else
    `host#key` (e.g. `play.champds.com#atlantaga`)."""
    key = tenant_key(url)
    if key is None:
        return None
    host = _host(url)
    return host if key == "" else f"{host}#{key}"
