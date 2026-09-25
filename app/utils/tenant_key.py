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
from typing import Callable, Dict, FrozenSet, Optional, Tuple
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


# --- Tenants that carry several governments (WO-1057).
#
# On a keyed shared host a tenant is normally ONE customer, so the name its
# adapter reads from the vendor's own record ("Cobb Co GA", "City of
# Chandler", a Town Hall Streams town) is as trustworthy as on that
# customer's own website, and `resolver` lets the name ladder run for it.
# These tenants are the exception: one customer (a regional station or
# commission) publishing several governments' meetings, where the name
# comes from one meeting's title -- and TelVue's adapter falls back to one
# town per station, which is how RVTV's Jackson County meetings read as
# "Ashland". For these, only a pin identifies the government.
#
# Every entry is real and evidenced; tests/test_tenant_key.py fails if the
# pins show another tenant naming more than one government that is not
# listed here.
MULTI_GOVERNMENT_TENANTS: FrozenSet[Tuple[str, str]] = frozenset(
    {
        # RVTV (Rogue Valley, OR): Jackson County, Ashland, Grants Pass,
        # Medford, Eagle Point, Ashland School District, RVTD -- playlist
        # pins, and its own /home listing (checked 2026-09-25).
        ("videoplayer.telvue.com", "w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP"),
        # CMNtv (Oakland County, MI): Auburn Hills, Berkley, Madison
        # Heights, Royal Oak, Troy, Rochester, Berkley School District.
        ("videoplayer.telvue.com", "Hejq7tDUseFZXc46e8pIxdl8NpmSEupd"),
        # Schopeg (Schoharie County, NY): 8 governments, playlist pins.
        ("videoplayer.telvue.com", "lfzlfeW2jHTLCtEU2AKNyEA0B8A5stMI"),
        # C-NET (Centre County, PA): Bellefonte borough, Halfmoon Township.
        ("videoplayer.telvue.com", "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru"),
        # Derry, NH: the town and Derry Cooperative School District.
        ("videoplayer.telvue.com", "CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l"),
        # Pacifica Coast TV: Pacifica and Half Moon Bay, CA council
        # meetings (BACKLOG_DONE.md's Half Moon Bay/Pacifica entry).
        ("videoplayer.telvue.com", "wuZKb9gwEY7sMACIIsr7VSJglB35kNZA"),
        # Kalamazoo, MI's TelVue station: City of Kalamazoo committees and
        # the Kalamazoo County Board of Commissioners (WO-1060).
        ("videoplayer.telvue.com", "2bm0gzQWeVRzdCgvjXziXKwO3icSKh05"),
        # Castus "tbnk" (Kentucky regional commission): a dozen-plus cities
        # (registry.py's MULTI_GOV_HOSTS comment; per-video pins).
        ("cloud.castus.tv", "tbnk"),
    }
)


# Keyed shared hosts whose adapter reads the town from each MEETING'S
# title rather than from the customer's own record, so the name is exactly
# as untrustworthy as a YouTube title and only a pin identifies. TelVue:
# telvue.py's `_guess_jurisdiction(title)` runs first, then a per-station
# table and the station logo; WO-316's Pittsford mis-filing and RVTV's
# "Ashland" for Jackson County meetings both came from this path.
NAME_FROM_MEETING_TITLE_HOSTS: FrozenSet[str] = frozenset({"videoplayer.telvue.com"})


def trusted_tenant_key(url: str) -> Optional[str]:
    """The tenant key when `url` is on a keyed shared host, carries its
    key, and that tenant is ONE government's -- so its adapter's name can
    be trusted as on a single website. None otherwise: a single-website
    host (nothing to decide), an out-of-scope host, a URL missing its key,
    or a tenant in `MULTI_GOVERNMENT_TENANTS`."""
    host = _host(url)
    if not host or _rule_for(host) is None:
        return None
    if host in NAME_FROM_MEETING_TITLE_HOSTS:
        return None
    key = tenant_key(url)
    if not key:
        return None
    if (host, key) in MULTI_GOVERNMENT_TENANTS:
        return None
    return key


# --- Pins (tenant_overrides.csv rows) and tenant keys.
#
# A `match` is a substring of `path?query` or a `key=value` page hint
# (see `resolver._match_override()`), so it is not a URL. To read one as
# a tenant, a query-only pin needs a real page path in front of it.
_QUERY_PIN_PATH: Dict[str, str] = {
    "public.destinyhosted.com": "agenda_publish.cfm",
    "townhallstreams.com": "stream.php",
}
_TELVUE_BARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")
_BOXCAST_CHANNEL_HINT_RE = re.compile(r"^channel=boxcast:(.+)$", re.IGNORECASE)
# How a pin may spell "exactly this tenant" in front of the bare key.
_WHOLE_TENANT_PREFIXES = (
    "player/",
    "vod/",
    "channel/",
    "channel=boxcast:",
    "clientid=",
    "location_id=",
    "id=",
)


def pin_tenant_key(host: str, match: Optional[str]) -> Optional[str]:
    """The tenant key when this pin names a WHOLE tenant on a keyed
    shared host (`/atlantaga/`, `site=8`, `player/{token}`, `id=24263`),
    else None -- a narrower pin (one playlist, one event, one show), a
    pin on any other host, or a match that cannot be read as a tenant.

    `resolver._match_override()` uses this for two things (WO-1056):
    a whole-tenant pin also matches every URL with that tenant key (so
    DestinyHosted's `id=N` pins reach `/{N}/agenda/...` pages), and a
    narrower pin wins over its tenant's whole-tenant pin (so a CMNtv
    playlist pin beats the station pin).
    """
    host = _HOST_ALIASES.get((host or "").lower(), (host or "").lower())
    if not match or _rule_for(host) is None:
        return None
    match = match.strip()
    if host == "videoplayer.telvue.com" and _TELVUE_BARE_TOKEN_RE.match(match):
        return match
    hint = _BOXCAST_CHANNEL_HINT_RE.match(match)
    if host == "boxcast.tv" and hint:
        return hint.group(1).lower()
    if re.match(r"^[A-Za-z_]+=", match):
        url = f"https://{host}/{_QUERY_PIN_PATH.get(host, '')}?{match}"
    else:
        url = f"https://{host}/{match.lstrip('/')}"
    key = tenant_key(url)
    if not key:
        return None
    norm = match.strip("/").lower()
    for prefix in _WHOLE_TENANT_PREFIXES:
        if norm.startswith(prefix):
            norm = norm[len(prefix) :]
            break
    return key if norm == key.lower() else None


def tenant_name(url: str) -> Optional[str]:
    """The tenant's name: the host alone when the key is blank, else
    `host#key` (e.g. `play.champds.com#atlantaga`)."""
    key = tenant_key(url)
    if key is None:
        return None
    host = _host(url)
    return host if key == "" else f"{host}#{key}"
