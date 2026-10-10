"""CATS (catstv.net) -- Community Access Television Services, Monroe County Public Library, Bloomington, Indiana.

One station, many separate governments: the City of Bloomington, Monroe County and its boards, the Town of Ellettsville, the Monroe County and
Richland-Bean Blossom school boards, the library board, the Waste Reduction District and more (the body list on `government.php`). Read live on
2026-10-10, never assumed:

* A meeting is `https://catstv.net/m.php?q=<number>`. Plain HTML, no script needed. There is no robots.txt (the path answers 404).
* The page holds the whole record: `<source src>` is the video (an .m4v on `catstv.blob.core.windows.net/videoarchive/`), `<track kind="captions"
  src>` is the WebVTT file, `p.video-name` the title ("Bloomington City Council 10/7"), `p.video-date` ("Wed, October 7, 2026") and
  `p.video-duration` ("03:18:18"). A text transcript sits beside the VTT as `<name>_transcript.txt`; this adapter reads the VTT, which has the times.
* Only some meetings carry captions. When a meeting has no `<track>` the result has no segments and a plain warning (Tier 3, our own transcription).
* The body is not named on the page in a field of its own. The file name is `<CODE>_<yymmdd>.m4v`: `B_CC` (Bloomington City Council), `M_CS_WS`
  (Monroe County Commissioners work session), `E_ETC` (Ellettsville Town Council), `M_MCCSC`, `M_RBB`, `M_MCPL`, `M_WRD`. The code goes out as
  `video_channel` = `cats:{code}` (lower case) so `tenant_overrides.csv` can pin each code to its government (`match=channel=cats:{code}`). A code with no pin
  stays unattributed on purpose.
* The `Runtime` field is the source's own length for the file and is passed on as `video_duration_seconds`.

Politeness: two requests per resolve (the page, then the VTT), the project User-Agent, no retries.
"""

import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    dedupe_rollup_cues,
    is_likely_garbled,
    parse_vtt,
)

logger = logging.getLogger("rtr_deeplink.catstv")

CATS_HOSTS = ("catstv.net", "www.catstv.net")
_USER_AGENT = "RedTapeRecordings/1.0 (+https://redtaperecordings.com)"

# `<CODE>_<yymmdd>` at the start of a video file name, e.g. B_CC_261007.m4v -> B_CC.
_CODE_RE = re.compile(r"^(?P<code>[A-Za-z0-9_]+?)_\d{6}(?:[_.-]|$)")


def is_catstv_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in CATS_HOSTS


def meeting_id_from_url(url: str) -> Optional[str]:
    """The number in `m.php?q=<number>`, else None."""
    parsed = urlparse(url)
    if not parsed.path.rstrip("/").endswith("/m.php"):
        return None
    value = (parse_qs(parsed.query).get("q") or [""])[0]
    return value if value.isdigit() else None


def body_code_from_video_url(video_url: str) -> Optional[str]:
    """`https://.../B_CC_261007.m4v` -> `B_CC`; None when the name has no `_yymmdd` part."""
    name = urlparse(video_url).path.rsplit("/", 1)[-1]
    match = _CODE_RE.match(name)
    return match.group("code") if match else None


def _parse_date(text: str) -> Optional[str]:
    """`Wed, October 7, 2026` -> `2026-10-07`."""
    try:
        return datetime.strptime(text.strip(), "%a, %B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_runtime(text: str) -> Optional[float]:
    """`03:18:18` -> 11898.0; None for anything else."""
    parts = text.strip().split(":")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    h, m, s = (int(p) for p in parts)
    seconds = h * 3600 + m * 60 + s
    return float(seconds) if seconds else None


def _text(soup: BeautifulSoup, css: str) -> Optional[str]:
    node = soup.select_one(css)
    value = node.get_text(" ", strip=True) if node else ""
    return value or None


class CatsTvAssetFinder(AssetFinder):
    platform_name = "catstv"

    async def resolve(self, url: str) -> ResolvedMeeting:
        meeting_id = meeting_id_from_url(url)
        if not meeting_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This is a catstv.net page, but not a single meeting. Open the meeting "
                    "itself (an address like catstv.net/m.php?q=16544) and paste that link."
                ],
            )
        external_id = f"catstv:{meeting_id}"
        page_url = f"https://catstv.net/m.php?q={meeting_id}"
        async with aiohttp.ClientSession(
            headers={"User-Agent": _USER_AGENT}
        ) as session:
            html = await self._get_text(session, page_url)
            if html is None:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    external_id=external_id,
                    video_warnings=["Could not load this catstv.net meeting."],
                )
            soup = BeautifulSoup(html, "html.parser")
            source = soup.select_one("video source[src]")
            video_url = urljoin(page_url, source["src"]) if source else None
            resolved = ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=external_id,
                title=_text(soup, "p.video-name"),
                date=_parse_date(_text(soup, "p.video-date") or ""),
                video_url=video_url,
                video_format="mp4" if video_url else None,
                video_duration_seconds=_parse_runtime(
                    _text(soup, "p.video-duration") or ""
                ),
            )
            if not video_url:
                resolved.video_warnings = [
                    "We found this catstv.net meeting but no video on the page."
                ]
                return resolved
            code = body_code_from_video_url(video_url)
            if code:
                resolved.video_channel = f"cats:{code.lower()}"
            track = soup.select_one('video track[kind="captions"][src]')
            if track:
                cues = await self._fetch_cues(session, urljoin(page_url, track["src"]))
                if cues:
                    resolved.segments = [TranscriptSegment(**c) for c in cues]
                    if is_likely_garbled(cues, lang="en"):
                        resolved.transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) -- treat it as approximate."
                        )
            if not resolved.segments:
                resolved.transcript_warnings.append("No captions found for this video.")
        return resolved

    @staticmethod
    async def _get_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.warning("catstv HTTP %s for %s", response.status, url)
                    return None
                return await response.text()
        except Exception:
            logger.warning("catstv fetch failed for %s", url, exc_info=True)
            return None

    @staticmethod
    async def _fetch_cues(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(
                vtt_url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "catstv VTT HTTP %s for %s", response.status, vtt_url
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning("catstv VTT fetch failed for %s", vtt_url, exc_info=True)
            return None
        return dedupe_rollup_cues(parse_vtt(decode_vtt_bytes(raw))) or None
