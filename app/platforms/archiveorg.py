"""Internet Archive items (archive.org/details/{item_id}) -- WO-1962.

The Internet Archive holds two kinds of meeting item. Read live on 2026-10-14, never assumed:

* An **own-station upload**: a community TV station uploads its own recording (Foxborough Cable Access, `bos-2021-05-11`, "Foxborough Board of Selectmen
  Meeting 2021/05/11"). The item holds an original .mov, an .mp4 and an .mp3 derivative, and no caption file.
* A **bulk mirror of a station's YouTube channel** (ORCA Media, Vermont: `orcavt-Berlin_Selectboard_-_September_28_2026_BNS-CRVIP1m2Lo0`). The metadata
  carries `youtube-id`, the item holds an .mp4 and an .mp3, and about half carry caption files: `*.en.vtt` and `*.en.asr.srt`.

One shared host, any government's items. This adapter claims only the item page, `https://archive.org/details/{item_id}` (http and www too, any trailing
slash, query or hash). It does not claim `/download/...` media links; those keep resolving through `direct_file.py`.

How it reads an item (politeness: one metadata request, at most one caption request, the project User-Agent, no retries, nothing else):

1. `GET https://archive.org/metadata/{item_id}` -- JSON, `metadata` plus a `files` list. A missing item answers 200 with `{}`.
2. If a caption file is listed, one `GET https://archive.org/download/{item_id}/{name}`.

Mapping:

* `title` = metadata.title as given. `date` = metadata.date (first 10 characters, when they read as a date); else a `YYYY-MM-DD` / `YYYY_MM_DD` in the
  title or the file name; else blank. A blank date gets a plain note.
* `video_url` = the .mp4 (file format h.264 or MPEG4 first), else the .mp3 (audio counts). Never fetched. `video_duration_seconds` = the file's `length`,
  which the Archive writes as seconds (`4271.3`) or `HH:MM:SS` (`01:24:18`); both are read.
* `jurisdiction` and `meeting_body` are left blank. `creator` is the station, not the government, so it goes in no government field.
* `youtube-id` in the metadata becomes `external_id` = `youtube:{id}` (recorded, never fetched) and the reader sees "Copy of a YouTube video held by the
  Internet Archive." Without it, `external_id` = `archiveorg:{item_id}`.
* Captions, in this order: `*.en.vtt`, any other `*.vtt`, `*.en.asr.srt`/`*.en.srt`, any other `*.srt`. VTT and SRT both parse (`parse_captions_by_extension`
  in `app/utils/vtt_parser.py` already carries an SRT parser). The note "Captions are archive.org's own speech recognition."
  is added only when the caption file used is an `.asr.` file; any other caption file on an item with a `youtube-id` gets "Captions were copied from the YouTube video."
* No caption file: no segments and "No captions found for this video." (tier 3).
* A missing item, a dark or restricted item, or an item with no mp4/mp3 gives a result with a plain warning and no `video_url`. Nothing raises.

Identity: `archive.org` is in `MULTI_GOV_HOSTS`, so a page from here is never filed under a guessed government. Callers pass an explicit `gov_id`.
"""

import logging
import re
from typing import Optional
from urllib.parse import quote, urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    is_likely_garbled,
    parse_captions_by_extension,
)

logger = logging.getLogger("rtr_deeplink.archiveorg")

ARCHIVEORG_HOSTS = ("archive.org", "www.archive.org")
_USER_AGENT = "RedTapeRecordings/1.0 (+https://redtaperecordings.com)"

COPY_WARNING = "Copy of a YouTube video held by the Internet Archive."
MACHINE_CAPTION_NOTE = "Captions are archive.org's own speech recognition."
YOUTUBE_CAPTION_NOTE = "Captions were copied from the YouTube video."
NO_CAPTIONS_NOTE = "No captions found for this video."

_DETAILS_RE = re.compile(r"^/details/(?P<id>[^/?#]+)/?$")
_DATE_IN_TEXT_RE = re.compile(r"(?<!\d)(\d{4})[-_/.](\d{2})[-_/.](\d{2})(?!\d)")
_VIDEO_FORMATS = ("h.264", "mpeg4")


def item_id_from_url(url: str) -> Optional[str]:
    """`https://archive.org/details/{item_id}` -> item_id; None for any other archive.org address (including `/download/...`)."""
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in ARCHIVEORG_HOSTS:
        return None
    match = _DETAILS_RE.match(parsed.path)
    return match.group("id") if match else None


def is_archiveorg_details_url(url: str) -> bool:
    return item_id_from_url(url) is not None


def parse_length(value) -> Optional[float]:
    """`'4271.3'` -> 4271.3, `'01:24:18'` -> 5058.0, `'24:18'` -> 1458.0; None for anything else or zero."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if ":" in text:
            parts = text.split(":")
            if len(parts) > 3:
                return None
            seconds = 0.0
            for part in parts:
                seconds = seconds * 60 + float(part)
        else:
            seconds = float(text)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _iso_date(text: str) -> Optional[str]:
    """First real calendar date in `text` as YYYY-MM-DD, else None."""
    from datetime import date

    for match in _DATE_IN_TEXT_RE.finditer(text or ""):
        try:
            return date(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            ).isoformat()
        except ValueError:
            continue
    return None


def _file_url(item_id: str, name: str) -> str:
    return f"https://archive.org/download/{quote(item_id)}/{quote(name)}"


def _ext(name: str) -> str:
    return name.lower().rsplit(".", 1)[-1] if "." in name else ""


def _pick_media(files: list) -> Optional[dict]:
    """The .mp4 (h.264 / MPEG4 first), else the .mp3."""
    mp4s = [f for f in files if _ext(f.get("name", "")) == "mp4"]
    if mp4s:
        preferred = [
            f for f in mp4s if (f.get("format") or "").lower() in _VIDEO_FORMATS
        ]
        return (preferred or mp4s)[0]
    mp3s = [f for f in files if _ext(f.get("name", "")) == "mp3"]
    return mp3s[0] if mp3s else None


def _pick_caption(files: list) -> Optional[dict]:
    """`*.en.vtt`, then any `*.vtt`, then `*.en.asr.srt` / `*.en.srt`, then any `*.srt`."""
    names = {f.get("name", ""): f for f in files if f.get("name")}

    def first(predicate):
        for name in sorted(names):
            if predicate(name.lower()):
                return names[name]
        return None

    return (
        first(lambda n: n.endswith(".en.vtt"))
        or first(lambda n: n.endswith(".vtt"))
        or first(lambda n: n.endswith(".en.asr.srt"))
        or first(lambda n: n.endswith(".en.srt"))
        or first(lambda n: n.endswith(".srt"))
    )


class ArchiveOrgAssetFinder(AssetFinder):
    platform_name = "archiveorg"

    async def resolve(self, url: str) -> ResolvedMeeting:
        item_id = item_id_from_url(url)
        if not item_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This is an archive.org address, but not a single item page. Open the "
                    "item itself (an address like archive.org/details/bos-2021-05-11) and "
                    "paste that link."
                ],
            )
        external_id = f"archiveorg:{item_id}"
        resolved = ResolvedMeeting(
            platform=self.platform_name, source_url=url, external_id=external_id
        )
        async with aiohttp.ClientSession(
            headers={"User-Agent": _USER_AGENT}
        ) as session:
            record = await self._get_json(
                session, f"https://archive.org/metadata/{quote(item_id)}"
            )
            if not isinstance(record, dict) or not record.get("metadata"):
                resolved.video_warnings = [
                    "Could not load this Internet Archive item. It may have been removed."
                ]
                return resolved
            meta = record["metadata"]
            files = [f for f in (record.get("files") or []) if isinstance(f, dict)]

            if record.get("is_dark") or str(meta.get("is_dark", "")).lower() == "true":
                resolved.video_warnings = [
                    "This Internet Archive item is restricted and its files are not available."
                ]
                resolved.title = _as_text(meta.get("title"))
                return resolved

            youtube_id = _as_text(meta.get("youtube-id"))
            if youtube_id:
                resolved.external_id = f"youtube:{youtube_id}"
                resolved.transcript_warnings.append(COPY_WARNING)

            resolved.title = _as_text(meta.get("title"))
            media = _pick_media(files)
            date = _iso_date(_as_text(meta.get("date")) or "")
            if not date:
                date = _iso_date(resolved.title or "") or _iso_date(
                    (media or {}).get("name", "")
                )
            resolved.date = date
            if not date:
                resolved.transcript_warnings.append(
                    "The Internet Archive item states no meeting date."
                )

            if not media:
                resolved.video_warnings = [
                    "We found this Internet Archive item but no downloadable video or audio file."
                ]
                return resolved
            resolved.video_url = _file_url(item_id, media["name"])
            resolved.video_format = _ext(media["name"])
            resolved.video_duration_seconds = parse_length(media.get("length"))

            caption = _pick_caption(files)
            machine = bool(caption and ".asr." in caption["name"].lower())
            cues = None
            if caption:
                cues = await self._fetch_cues(
                    session, _file_url(item_id, caption["name"])
                )
            if cues:
                resolved.segments = [TranscriptSegment(**c) for c in cues]
                if machine:
                    resolved.transcript_warnings.append(MACHINE_CAPTION_NOTE)
                elif youtube_id:
                    resolved.transcript_warnings.append(YOUTUBE_CAPTION_NOTE)
                if is_likely_garbled(cues, lang="en"):
                    resolved.transcript_warnings.append(
                        "This transcript looks garbled at the source (not a parsing "
                        "bug on our end) -- treat it as approximate."
                    )
            else:
                resolved.transcript_warnings.append(NO_CAPTIONS_NOTE)
        return resolved

    @staticmethod
    async def _get_json(session: aiohttp.ClientSession, url: str):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.warning("archiveorg HTTP %s for %s", response.status, url)
                    return None
                return await response.json(content_type=None)
        except Exception:
            logger.warning("archiveorg fetch failed for %s", url, exc_info=True)
            return None

    @staticmethod
    async def _fetch_cues(session: aiohttp.ClientSession, caption_url: str):
        try:
            async with session.get(
                caption_url, timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "archiveorg caption HTTP %s for %s",
                        response.status,
                        caption_url,
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning(
                "archiveorg caption fetch failed for %s", caption_url, exc_info=True
            )
            return None
        cues, _text = parse_captions_by_extension(caption_url, decode_vtt_bytes(raw))
        return cues or None


def _as_text(value) -> Optional[str]:
    """Archive metadata fields may be a string or a list of strings; the first non-empty string, else None."""
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v.strip()), None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
