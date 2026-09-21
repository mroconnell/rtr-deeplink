"""Pure parsing for the `/context` feed's two link shapes (WO-943): the
social-media post an entry cites, and the redtaperecordings.com meeting
link it points into. No network I/O and no DB access anywhere in this
module -- an editor pastes both URLs by hand into a form, and everything
here is string parsing over what they typed.

**No server-side fetch of a social post ever happens, on purpose.** This
module never requests instagram.com/tiktok.com/etc. -- it only parses the
URL's own shape (host, path, query) to work out which network it is, a
stable dedupe key, and (for YouTube/Instagram/TikTok) enough to embed the
post client-side. The clip's actual content -- what it shows, whether it
really matches the cited meeting -- is entirely the editor's own written
`summary`; nothing here verifies it.
"""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.platforms.youtube_ids import extract_video_id as _extract_youtube_video_id

from .url_normalize import normalize_url

# Same rule build_base_slug()/_unique_slug() (archive/db/crud.py) actually
# produce: lowercase letters/digits, single hyphens between runs, never a
# leading/trailing/doubled one. Used here only to validate a pasted slug
# looks real, not to generate one.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_MAX_RAW_URL_LENGTH = 2048
CONTEXT_SUMMARY_MAX = 500

MATCH_KINDS = {
    "exact": "Exact moment",
    "approximate": "Same meeting, moment approximate",
    "related": "Related meeting",
}

NETWORK_LABELS = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "x": "X",
    "threads": "Threads",
    "bluesky": "Bluesky",
    "reddit": "Reddit",
    "linkedin": "LinkedIn",
    "other": "the original site",
}


class ContextLinkError(ValueError):
    """Raised by this module's parsers when a pasted link can't be used.

    `.code` is a short, stable, machine-checkable slug (e.g.
    "insecure_url") a caller can branch on; `.message` is plain English
    meant to be shown directly to the editor who pasted the link, per
    CLAUDE.md's "Writing for Ryan" style -- short sentences, no jargon.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SocialRef:
    """What parse_social_url() resolves a pasted URL down to.

    `canonical_url` is rebuilt from the parsed parts -- never the raw
    string an editor pasted -- so two differently-formatted links to the
    same post (different tracking params, `/p/` vs `/reel/`, a bare
    profile-style share) store identically. `key` is the dedupe identity
    (unique on ContextEntry.social_url_key); it deliberately is NOT always
    equal to `canonical_url` -- an id-bearing post's key is
    "{network}:{id}" (stable across the handful of URL shapes that share
    one real post), while a link-out-only post's key is "url:{canonical}"
    (the URL itself is the only identity available).
    """

    network: str
    canonical_url: str
    key: str


# --- Tracking-param stripping -------------------------------------------

# Deliberately narrow. Several platforms use single-letter or short query
# params for something that actually changes the resource (YouTube "v",
# a share's "t"/"s" timestamp or ranking hint) -- stripping those would
# silently corrupt the link, not just tidy it. Only params confirmed to be
# pure tracking noise are removed.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_EXACT = {"igsh", "igshid", "si", "fbclid", "feature", "ref_src"}


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered.startswith(_TRACKING_PARAM_PREFIXES) or lowered in _TRACKING_PARAM_EXACT
    )


def _canonical_generic(parts) -> str:
    """Reconstructs a URL from parsed `parts` with tracking params and the
    fragment dropped, then finishes with the shared normalize_url() (scheme/
    host lowercasing, default-port/trailing-slash stripping, http->https,
    sorted remaining params) -- the same identity rule the resolver and
    Archive already agree on for everything else URL-shaped in this repo.
    """
    kept_params = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    stripped = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept_params), "")
    )
    return normalize_url(stripped)


def _generic_ref(network: str, parts) -> SocialRef:
    canonical = _canonical_generic(parts)
    key = f"url:{canonical}"
    if len(key) > 512:
        raise ContextLinkError(
            "url_too_long", "That link is too long to save -- try a shorter one."
        )
    return SocialRef(network=network, canonical_url=canonical, key=key)


# --- Per-network parsing --------------------------------------------------

_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
# Optional leading "/{username}/" before the real path, matching how
# Instagram renders a share link copied from a profile's grid.
_INSTAGRAM_PATH_RE = re.compile(
    r"^/(?:[^/]+/)?(?P<kind>p|reels?|tv)/(?P<code>[A-Za-z0-9_-]+)"
)


def _parse_instagram(parts) -> SocialRef:
    match = _INSTAGRAM_PATH_RE.match(parts.path)
    if not match:
        # A profile, a story, or any other Instagram path this module
        # doesn't special-case -- still a real, acceptable citation, just
        # link-out only (no embed_for() shape for it).
        return _generic_ref("instagram", parts)
    kind, code = match.group("kind"), match.group("code")
    if kind == "p":
        canonical = f"https://www.instagram.com/p/{code}/"
    elif kind in ("reel", "reels"):
        # "/p/X" and "/reel/X" are the same post shared two different ways
        # -- same key on purpose, so pasting either dedupes to one entry.
        canonical = f"https://www.instagram.com/reel/{code}/"
    else:  # "tv"
        canonical = f"https://www.instagram.com/tv/{code}/"
    return SocialRef(
        network="instagram", canonical_url=canonical, key=f"instagram:{code}"
    )


_TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}
_TIKTOK_SHORT_HOSTS = {"vm.tiktok.com", "vt.tiktok.com"}
# The username is rebuilt into the stored canonical URL, so it is held to
# TikTok's own handle charset rather than "anything but a slash".
_TIKTOK_PATH_RE = re.compile(r"^/@(?P<user>[A-Za-z0-9_.]+)/video/(?P<id>\d+)")


def _parse_tiktok(parts) -> SocialRef:
    match = _TIKTOK_PATH_RE.match(parts.path)
    if not match:
        # Covers tiktok.com/t/<short-code>/ too -- a short link this
        # module can't resolve to a real video id without a network call,
        # which it never makes (see module docstring).
        return _generic_ref("tiktok", parts)
    user, video_id = match.group("user"), match.group("id")
    canonical = f"https://www.tiktok.com/@{user}/video/{video_id}"
    return SocialRef(
        network="tiktok", canonical_url=canonical, key=f"tiktok:{video_id}"
    )


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def _parse_youtube(raw_url: str, parts) -> SocialRef:
    # extract_video_id() (app/platforms/youtube_ids.py) already handles
    # every shape this needs, including /shorts/ -- it's imported rather
    # than re-implemented so the Archive never drifts from the one real
    # id-extraction rule the resolver/worker also use (see that module's
    # own docstring on why it was split out from app/platforms/youtube.py).
    video_id = _extract_youtube_video_id(raw_url)
    if not video_id:
        # A channel URL, a playlist, or anything else with no single
        # video id -- link-out only.
        return _generic_ref("youtube", parts)
    if "/shorts/" in parts.path:
        canonical = f"https://www.youtube.com/shorts/{video_id}"
    else:
        canonical = f"https://www.youtube.com/watch?v={video_id}"
    return SocialRef(
        network="youtube", canonical_url=canonical, key=f"youtube:{video_id}"
    )


_FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"}
_X_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}
_THREADS_HOSTS = {"threads.net", "www.threads.net", "threads.com", "www.threads.com"}
_BLUESKY_HOSTS = {"bsky.app", "www.bsky.app"}
_REDDIT_HOSTS = {"reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"}
_LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com"}


def _is_ip_literal(hostname: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(hostname.strip("[]"))
        return True
    except ValueError:
        return False


def parse_social_url(raw: str) -> SocialRef:
    """Parses a pasted social-post URL into a SocialRef, or raises
    ContextLinkError with a plain-English reason.

    https only, no userinfo/non-default-port/IP-literal/localhost hosts,
    and capped at 2048 characters -- the same "this is a real, public,
    shareable link" bar for every network, applied before any per-network
    parsing runs.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise ContextLinkError("invalid_url", "Paste a link to the post.")
    if len(candidate) > _MAX_RAW_URL_LENGTH:
        raise ContextLinkError(
            "url_too_long", "That link is too long to save -- try a shorter one."
        )

    parts = urlsplit(candidate)
    if parts.scheme != "https":
        raise ContextLinkError(
            "insecure_url", "Paste a link that starts with https://."
        )
    if "@" in parts.netloc:
        raise ContextLinkError(
            "invalid_url", "That link isn't a plain https:// address."
        )
    hostname = parts.hostname
    if not hostname:
        raise ContextLinkError("invalid_url", "That doesn't look like a link.")
    if parts.port is not None and parts.port != 443:
        raise ContextLinkError("invalid_url", "That link uses a non-standard port.")
    if _is_ip_literal(hostname):
        raise ContextLinkError(
            "invalid_url", "Paste a link to the actual post, not a bare IP address."
        )
    hostname = hostname.lower()
    if hostname == "localhost":
        raise ContextLinkError(
            "invalid_url", "That's a local address, not a real post."
        )
    if "." not in hostname:
        raise ContextLinkError(
            "invalid_url", "That doesn't look like a real web address."
        )

    if hostname in _INSTAGRAM_HOSTS:
        return _parse_instagram(parts)
    if hostname in _TIKTOK_HOSTS:
        return _parse_tiktok(parts)
    if hostname in _TIKTOK_SHORT_HOSTS:
        return _generic_ref("tiktok", parts)
    if hostname in _YOUTUBE_HOSTS:
        return _parse_youtube(candidate, parts)
    if hostname in _FACEBOOK_HOSTS:
        return _generic_ref("facebook", parts)
    if hostname in _X_HOSTS:
        return _generic_ref("x", parts)
    if hostname in _THREADS_HOSTS:
        return _generic_ref("threads", parts)
    if hostname in _BLUESKY_HOSTS:
        return _generic_ref("bluesky", parts)
    if hostname in _REDDIT_HOSTS:
        return _generic_ref("reddit", parts)
    if hostname in _LINKEDIN_HOSTS:
        return _generic_ref("linkedin", parts)
    return _generic_ref("other", parts)


def embed_for(network: str, social_url: str) -> Optional[dict]:
    """The client-side embed shape for a stored (network, social_url) pair,
    computed at READ time by re-parsing `social_url` -- never stored, so a
    later change to this module's parsing rules (a new Instagram path
    shape, say) improves every existing entry's embed for free rather than
    needing a backfill.

    Never raises: any parse problem, or a re-parse landing on a different
    network than what's stored (this module's own rules changed since the
    entry was saved), degrades to None -- a missing embed is a link-out
    card, not a broken page.
    """
    try:
        ref = parse_social_url(social_url)
    except ContextLinkError:
        return None
    if ref.network != network:
        return None
    if ref.network == "youtube" and ref.key.startswith("youtube:"):
        return {"kind": "youtube", "video_id": ref.key.split(":", 1)[1]}
    if ref.network == "instagram" and ref.key.startswith("instagram:"):
        return {"kind": "instagram", "permalink": ref.canonical_url}
    if ref.network == "tiktok" and ref.key.startswith("tiktok:"):
        return {
            "kind": "tiktok",
            "video_id": ref.key.split(":", 1)[1],
            "cite": ref.canonical_url,
        }
    return None


# --- The Archive-side link a context entry points into --------------------

_LOCAL_HOSTS = {"localhost", "127.0.0.1"}
_PROD_HOSTS = {"redtaperecordings.com", "www.redtaperecordings.com"}
_MAX_T_SECONDS = 86400  # 24h -- comfortably past any real meeting's length


def parse_rtr_link(
    raw: str, public_base_url: Optional[str]
) -> tuple[str, Optional[int]]:
    """Parses a pasted /m/{slug} link (full URL, relative path, or a bare
    slug) into (slug, t_seconds).

    Accepts: a full URL on `public_base_url`'s own host, on
    redtaperecordings.com/www.redtaperecordings.com, or on localhost/
    127.0.0.1 (any port, http allowed only for these local ones -- a local
    dev server has no real TLS cert to check against); a relative
    "/m/{slug}?t=123"; or a bare slug with no path at all.

    The path must be exactly "/m/{slug}" (an optional trailing slash is
    tolerated) -- "/m/{slug}/video" or any other suffix is rejected rather
    than silently truncated, so a malformed paste surfaces as an error
    instead of quietly pointing at the wrong thing.

    `line` and `version` query params (both real /m/{slug} params
    elsewhere in this app) are accepted and silently ignored -- carrying
    them through into what this entry stores is a logged follow-up, not
    done here (see BACKLOG.md's WO-943 entry).

    Raises ContextLinkError on anything else: `not_rtr_link` for a foreign
    host, `invalid_link` for an unparseable path, `invalid_slug` for a
    slug that isn't the shape build_base_slug() actually produces,
    `invalid_timestamp` for a `t` that isn't a plausible non-negative
    number of seconds.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise ContextLinkError(
            "invalid_link", "Paste a redtaperecordings.com meeting link, or its slug."
        )

    if "://" not in candidate and not candidate.startswith("/"):
        # No scheme and no leading slash -- treated as a bare slug, not a
        # relative path, so "some-city-2026-01-01-council" works without
        # the editor having to type "/m/" themselves.
        if not _SLUG_RE.match(candidate):
            raise ContextLinkError(
                "invalid_slug", "That doesn't look like a meeting page slug."
            )
        return candidate, None

    parts = urlsplit(candidate)
    if parts.netloc:
        hostname = (parts.hostname or "").lower()
        is_local = hostname in _LOCAL_HOSTS
        allowed_hosts = set(_PROD_HOSTS)
        if public_base_url:
            base = (
                public_base_url
                if "://" in public_base_url
                else f"https://{public_base_url}"
            )
            base_host = urlsplit(base).hostname
            if base_host:
                allowed_hosts.add(base_host.lower())
        if not is_local and hostname not in allowed_hosts:
            raise ContextLinkError(
                "not_rtr_link", "That link doesn't point at redtaperecordings.com."
            )
        if not is_local and parts.scheme != "https":
            raise ContextLinkError(
                "not_rtr_link", "That link doesn't point at redtaperecordings.com."
            )
    # else: no netloc -- a bare relative path like "/m/{slug}?t=123",
    # already fully described by `parts`.

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    match = re.match(r"^/m/(?P<slug>[^/]+)$", path)
    if not match:
        raise ContextLinkError(
            "invalid_link", "That doesn't look like a /m/ meeting link."
        )
    slug = match.group("slug")
    if not _SLUG_RE.match(slug):
        raise ContextLinkError(
            "invalid_slug", "That doesn't look like a meeting page slug."
        )

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    t_raw = query.get("t")
    t_seconds: Optional[int] = None
    if t_raw:
        try:
            t_value = float(t_raw)
        except ValueError:
            raise ContextLinkError(
                "invalid_timestamp", "That timestamp doesn't look like a number."
            )
        # Written as a positive range test on purpose: float("nan") parses
        # fine and is neither < 0 nor > the cap, so the obvious "reject if
        # outside" form lets it through to int(), which raises.
        if not (0 <= t_value <= _MAX_T_SECONDS):
            raise ContextLinkError(
                "invalid_timestamp", "That timestamp is out of range."
            )
        t_seconds = int(t_value)  # floor, e.g. 123.7 -> 123

    return slug, t_seconds
