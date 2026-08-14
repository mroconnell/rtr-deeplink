import html as html_module
import re
from typing import List
from urllib.parse import urljoin, urlparse

# Caption/subtitle formats seen or plausible in the wild for civic meeting
# platforms, beyond the two (.vtt/.srt) this app originally only looked
# for. Structured parsers exist for vtt/srt/ttml/dfxp/itt
# (app/utils/vtt_parser.py); the rest are detected but only get a
# best-effort text fallback or a link-only mention -- see
# vtt_parser.parse_captions_by_extension() for what happens once one of
# these URLs is actually found and fetched. Kept here (not just in
# vtt_parser.py) since detection -- finding the URL on a page at all --
# and parsing are genuinely separate concerns with separate risk: adding
# an extension here just means "notice this file exists," not "trust we
# can read it."
CAPTION_EXTENSIONS = (
    "vtt", "srt", "ttml", "dfxp", "itt", "scc", "stl", "sbv", "sub", "smi", "sami",
)

_MEDIA_EXTS = "mp4|mp3|wav|webm|ogg"
_ALL_EXTS = f"{_MEDIA_EXTS}|m3u8|{'|'.join(CAPTION_EXTENSIONS)}"

# Absolute-URL patterns terminate on quotes, whitespace, angle brackets,
# and backslashes -- the original quote-only termination let a bare
# (unquoted) URL in page text swallow everything up to the next quote
# character, including newlines and following markup (confirmed by running
# the old pattern against real captures during the 2026-08-14 rebuild).
MEDIA_URL_PATTERNS = [
    r"https?://[^\"'\s<>\\]+\.m3u8[^\"'\s<>\\]*",
    rf"https?://[^\"'\s<>\\]+\.(?:mp4|mp3|wav|webm|ogg|{'|'.join(CAPTION_EXTENSIONS)})[^\"'\s<>\\]*",
    # src=/data-src= attributes (relative and protocol-relative URLs live
    # here). The original terminator class ["'&] rejected any URL with a
    # query string -- the real Sacramento County OnBase page's
    # `playlist.m3u8?instance=1&amp;token=...` never matched it. Query
    # strings are now captured up to the closing quote.
    rf"(?:data-)?src=[\"']([^\"']+\.(?:{_ALL_EXTS})(?:\?[^\"']*)?)[\"']",
    # JW Player-style config `file:` keys -- `sources: [{file: "..."}]` and
    # `tracks: [{file: "..."}]` both use it. Justified by three real
    # confirmed pages (2026-08-14 captures in tests/fixtures/generic_fallback/):
    # Sacramento + Maricopa County (absolute m3u8 with an &amp;-escaped
    # query token) and Seattle Channel (protocol-relative //host mp4 in
    # sources, RELATIVE-path srt in tracks -- urljoin resolves both).
    # Deliberately scoped to the `file:` key shape, not a generic
    # quoted-string grab, to keep wrong-video risk down.
    rf"[\"']?file[\"']?\s*:\s*[\"']([^\"']+\.(?:{_ALL_EXTS})(?:\?[^\"']*)?)[\"']",
    # .xml/.txt are too generic to match unconditionally (sitemap
    # references, analytics config, any random text file on the page) --
    # only treated as a possible caption file when the URL path itself
    # also looks caption-related, matching how real ones are actually
    # named (e.g. CivicClerk's "ClosedCaption/...", Granicus's
    # "captions.vtt").
    r"https?://[^\"'\s<>\\]*(?:caption|subtitle|transcript|/cc[_./-])[^\"'\s<>\\]*\.(?:xml|txt)[^\"'\s<>\\]*",
]

# Segment-aware, not a plain substring check -- the original
# `"icon" in url` blocklist also blocked any URL containing e.g.
# "silicon"/"iconic" in a path segment. A blocked word must now stand
# alone between separators (start/end, "/", "_", ".", "-").
_BLOCKLIST_RE = re.compile(r"(?:^|[/_.\-])(?:placeholder|logo|icon)(?:[/_.\-]|$)")


def scan_media_urls(html: str, page_url: str) -> List[str]:
    """Regex-scan raw page HTML/JS for playable media URLs, resolving any
    relative paths against page_url. Generic text pattern-matching, not tied
    to any one platform's page structure — shared by GranicusAssetFinder and
    SwagitAssetFinder since both embed real media URLs as plain strings
    somewhere in server-rendered HTML/inline <script> content, just in
    different surrounding structures.

    Returns candidates in **document order** (first occurrence wins on
    duplicates) -- this used to return `list(set(...))`, whose
    nondeterministic ordering made every "first match wins" caller
    (e.g. generic_fallback's `_pick_video_url`) a per-run coin flip on
    pages with more than one media URL.

    Each extracted candidate is HTML-entity-unescaped (`&amp;` -> `&`,
    numeric entities too) before being returned -- confirmed live
    2026-08-14 on the real Sacramento County OnBase page, whose m3u8 URL
    carries `?instance=1&amp;token=...` in the raw HTML: without
    unescaping, the CDN receives a literal `amp;token` parameter and the
    real `token` is lost. Unescaping is per-candidate only, never applied
    to the whole document (which could corrupt offsets/other matches).

    Also de-escapes JSON-style backslash-escaped slashes before matching --
    confirmed live 2026-08-10 against a real small-city site (Aurora, CO's
    auroratv.org, found via the generic fallback adapter): a real playable
    .mp4 and a real .vtt caption file were both genuinely on the page, just
    inside an inline <script> JSON blob (a JW Player config object) with
    every forward slash backslash-escaped, e.g.
    "https:" + chr(92) + "/" + chr(92) + "/reflect-aurora.cablecast.tv/.../vod.mp4"
    in the raw HTML, which none of MEDIA_URL_PATTERNS matches since they
    all require a literal "https?://". A backslash immediately before a
    forward slash is never legitimate outside of this exact JSON/JS escape
    convention, so a blanket replace is safe -- it can only ever recover a
    real URL, never invent content that wasn't already there.
    """
    html = html.replace("\\/", "/")

    positioned = []  # (position, resolved_url)
    for pattern in MEDIA_URL_PATTERNS:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            raw = match.group(1) if match.groups() else match.group(0)
            if not raw:
                continue
            raw = html_module.unescape(raw.strip("\"'"))
            # Unescaping can re-introduce characters the pattern's own
            # termination already excluded (e.g. a literal &quot; that was
            # part of an escaped JSON blob) -- trim at the first one.
            raw = re.split(r"[\"'\s<>\\]", raw, maxsplit=1)[0]
            if not raw or _BLOCKLIST_RE.search(raw.lower()):
                continue
            positioned.append((match.start(), urljoin(page_url, raw)))

    positioned.sort(key=lambda item: item[0])
    seen = set()
    media_urls = []
    for _, url in positioned:
        if url not in seen:
            seen.add(url)
            media_urls.append(url)
    return media_urls


def is_hls_url(url: str) -> bool:
    """True when the URL's *path* ends in .m3u8, query string ignored.

    Exists because four separate call sites (generic_fallback, granicus,
    swagit, ca_legislature) each hand-rolled
    `candidate.lower().endswith(".m3u8")` against the FULL url -- which is
    False for a real HLS URL carrying a query string
    (`playlist.m3u8?instance=1&token=...`), the confirmed root cause of
    the Sacramento County "no video found" production bug (2026-08-14).
    """
    return urlparse(url).path.lower().endswith(".m3u8")


def media_type(url: str) -> str:
    path = urlparse(url).path.lower()
    # Checked against the path, not the full URL -- a query string after
    # .m3u8 used to make this fall through to "unknown" (same root cause
    # as is_hls_url()'s docstring describes).
    if path.endswith(".m3u8"):
        return "video"
    if path.endswith((".mp4", ".mov", ".m4v")):
        return "video"
    if path.endswith((".mp3", ".wav", ".m4a")):
        return "audio"
    if path.endswith(tuple(f".{ext}" for ext in CAPTION_EXTENSIONS)):
        return "subtitle"
    # .xml/.txt are only "subtitle" when the path also looks caption-related
    # -- same keyword gate as MEDIA_URL_PATTERNS, kept here too since
    # media_type() is a general classifier callers may run on a URL that
    # didn't come through scan_media_urls's own gate (e.g. a caption URL
    # from an API field, not a page scan).
    if path.endswith((".xml", ".txt")) and re.search(r"caption|subtitle|transcript|/cc[_./-]", path):
        return "subtitle"
    return "unknown"
