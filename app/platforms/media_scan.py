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

MEDIA_URL_PATTERNS = [
    r"https?://[^\"']+\.m3u8[^\"']*",
    rf"https?://[^\"']+\.(?:mp4|mp3|wav|webm|ogg|{'|'.join(CAPTION_EXTENSIONS)})[^\"']*",
    rf"src=[\"']([^\"']+\.(?:mp4|mp3|wav|webm|ogg|m3u8|{'|'.join(CAPTION_EXTENSIONS)}))[\"'&]",
    rf"data-src=[\"']([^\"']+\.(?:mp4|mp3|wav|webm|ogg|m3u8|{'|'.join(CAPTION_EXTENSIONS)}))[\"'&]",
    # .xml/.txt are too generic to match unconditionally (sitemap
    # references, analytics config, any random text file on the page) --
    # only treated as a possible caption file when the URL path itself
    # also looks caption-related, matching how real ones are actually
    # named (e.g. CivicClerk's "ClosedCaption/...", Granicus's
    # "captions.vtt").
    r"https?://[^\"']*(?:caption|subtitle|transcript|/cc[_./-])[^\"']*\.(?:xml|txt)[^\"']*",
]


def scan_media_urls(html: str, page_url: str) -> List[str]:
    """Regex-scan raw page HTML/JS for playable media URLs, resolving any
    relative paths against page_url. Generic text pattern-matching, not tied
    to any one platform's page structure — shared by GranicusAssetFinder and
    SwagitAssetFinder since both embed real media URLs as plain strings
    somewhere in server-rendered HTML/inline <script> content, just in
    different surrounding structures.

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
    media_urls = set()

    for pattern in MEDIA_URL_PATTERNS:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            raw = match.group(1) if match.groups() else match.group(0)
            if raw and not any(x in raw.lower() for x in ("placeholder", "logo", "icon")):
                media_urls.add(urljoin(page_url, raw.strip("\"'")))

    return list(media_urls)


def media_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if url.lower().endswith(".m3u8"):
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
