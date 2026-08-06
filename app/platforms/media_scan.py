import json
import re
from typing import List
from urllib.parse import urljoin, urlparse

MEDIA_URL_PATTERNS = [
    r"https?://[^\"']+\.m3u8[^\"']*",
    r"https?://[^\"']+\.(?:mp4|mp3|wav|webm|ogg|vtt|srt)[^\"']*",
    r"src=[\"']([^\"']+\.(?:mp4|mp3|wav|webm|ogg|m3u8|vtt|srt))[\"'&]",
    r"data-src=[\"']([^\"']+\.(?:mp4|mp3|wav|webm|ogg|m3u8|vtt|srt))[\"'&]",
]


def scan_media_urls(html: str, page_url: str) -> List[str]:
    """Regex-scan raw page HTML/JS for playable media URLs, resolving any
    relative paths against page_url. Generic text pattern-matching, not tied
    to any one platform's page structure — shared by GranicusAssetFinder and
    SwagitAssetFinder since both embed real media URLs as plain strings
    somewhere in server-rendered HTML/inline <script> content, just in
    different surrounding structures.
    """
    media_urls = set()

    for pattern in MEDIA_URL_PATTERNS:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            raw = match.group(1) if match.groups() else match.group(0)
            if raw and not any(x in raw.lower() for x in ("placeholder", "logo", "icon")):
                media_urls.add(urljoin(page_url, raw.strip("\"'")))

    try:
        for json_str in re.findall(r'({[^}]*"sources"\s*:\s*\[[^}]*\][^}]*})', html, re.DOTALL):
            try:
                data = json.loads(json_str)
                for source in data.get("sources", []):
                    if isinstance(source, dict) and "src" in source:
                        media_urls.add(urljoin(page_url, source["src"]))
            except json.JSONDecodeError:
                continue
    except Exception:
        pass

    return list(media_urls)


def media_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if url.lower().endswith(".m3u8"):
        return "video"
    if path.endswith((".mp4", ".mov", ".m4v")):
        return "video"
    if path.endswith((".mp3", ".wav", ".m4a")):
        return "audio"
    if path.endswith((".vtt", ".srt")):
        return "subtitle"
    return "unknown"
