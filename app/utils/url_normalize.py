from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def normalize_url(url: str) -> str:
    """Normalize a URL into a stable cache/log key.

    Deliberately conservative: lowercases scheme+host, strips the
    default port and fragment, sorts query params for stable ordering,
    collapses http/https to the same identity, and drops one trailing
    slash (when the path isn't just "/"). Does NOT touch query param
    casing/values or drop any params -- several adapters' identity lives
    entirely in query strings (e.g. Granicus "?view_id=&clip_id="), so
    being more aggressive here would create false cache collisions
    between different meetings.
    """
    parts = urlsplit(url.strip())

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    default_ports = {"http": ":80", "https": ":443"}
    if scheme in default_ports and netloc.endswith(default_ports[scheme]):
        netloc = netloc[: -len(default_ports[scheme])]

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))

    # http:// and https:// are the same resource in every real case this
    # codebase has ever seen -- confirmed 2026-08-29 investigating the
    # Coralville, IA Cablecast triplicate (BACKLOG_DONE.md): two of its
    # three duplicate archived pages differed only by scheme (plus a
    # separate query-string variant -- see this function's own query-
    # param comment above for why that part stays untouched). Canonicalize
    # to "https" here, after the scheme-specific default-port strip above
    # (which still needs the real scheme to know which port is
    # "default"), so a URL pasted or re-ingested under either scheme
    # produces the same identity key.
    if scheme in default_ports:
        scheme = "https"

    return urlunsplit((scheme, netloc, path, query, ""))
