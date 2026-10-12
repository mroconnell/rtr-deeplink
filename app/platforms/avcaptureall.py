"""AV Capture All (media.avcaptureall.cloud) -- one viewer site for many small governments (WO-1190).

OFFICE-MAC ONLY, like Vimeo: the meeting's record comes from `public-api.avcaptureall.cloud`, which refuses a plain client (403) and wants an
`x-aws-waf-token` that AWS's own script mints inside a real browser page. So this adapter loads the meeting page in the headless browser and reads
the reply the page itself asks for (`GET /V1_0/meetings/id/{meetingGuid}`). It builds no header, replays no token and never calls the API on its own.
With no headless browser (Render today, untested there) it raises `HeadlessBrowserUnavailable`, which the cloud services already handle for Vimeo.

Read live on 2026-10-11 (scope: rtr-business research/avcaptureall_2026-10-11/ADAPTER_SCOPE.md), never assumed:

* A meeting is `https://media.avcaptureall.cloud/meeting/{36-char guid}`. The page is an empty Blazor shell; the address does not name the government.
  The customer viewer (`/?customerGuid=...`) is not a meeting.
* The record holds `title`, `customerName`/`customerGuid`, `departmentTitle` (a body such as "Town Council", or only a category such as "Legislative"
  or "Judicial"), `duration` in seconds, `viewUrl` (a direct .mp4 or .mp3 on `download.avcaptureall.cloud`, Range works, no login),
  `videoSubtitlesUrl` (WebVTT; the key is missing when the meeting has no captions; about 1 meeting in 5, and 11 of 36 target customers) and
  `relatedDocuments` (Agenda, PdfBundle = `packet.pdf`).
* `dateScheduled`/`dateRecorded` are UTC, a day late for an evening meeting. The local date is in the file name of `viewUrl`
  (`..._2026-09-22_06-00-56 PM.mp4`). It is used first; the UTC date is the fallback and the result says so.
* A missing caption file answers 403 (S3 AccessDenied), not 404. Some caption URLs repeat their own path
  (`.../customer-{g}/meetings/{m}/customer-{g}/meetings/{m}/name.vtt`); the URL is used as given, then once more in the clean form on a 403.
* The record has no per-item times, so `agenda_items` stays empty.

Tier: source captions present = tier 1 (real segments); none = tier 3 (our own transcription). `video_channel` = `avcapture:{customerGuid, lower case}`
so `tenant_overrides.csv` can pin a customer to its government (`match=channel=avcapture:{guid}`). A customer with no pin stays unattributed on purpose.
`meeting_body` is `departmentTitle` as given; no meeting is dropped here (court calendars included) -- the pins and sweep rules decide what is filed.

Politeness: one headless page load and at most two plain GETs (the VTT, and its clean form after a 403) per resolve. No YouTube.
"""

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import unquote, urlparse

import aiohttp

from .base import AssetFinder
from .headless_browser import fetch_api_reply_via_browser
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    dedupe_rollup_cues,
    is_likely_garbled,
    parse_vtt,
)

logger = logging.getLogger("rtr_deeplink.avcaptureall")

AVC_HOST = "media.avcaptureall.cloud"
_USER_AGENT = "RedTapeRecordings/1.0 (+https://redtaperecordings.com)"
_GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_MEETING_PATH_RE = re.compile(rf"^/meeting/(?P<guid>{_GUID})/?$")
# `Name_2026-09-22_06-00-56 PM.mp4` -> 2026-09-22 (local date; the record's own dates are UTC).
_FILE_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}")
_REPLY_PATH = "/V1_0/meetings/id/"
_CAPTURE_TIMEOUT_S = 45


def is_avcaptureall_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() == AVC_HOST


def meeting_guid_from_url(url: str) -> Optional[str]:
    """The meeting guid (lower case) from `/meeting/{guid}`, else None."""
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != AVC_HOST:
        return None
    match = _MEETING_PATH_RE.match(parsed.path)
    return match.group("guid").lower() if match else None


def meeting_url(guid: str) -> str:
    return f"https://{AVC_HOST}/meeting/{guid.lower()}"


def local_date_from_file_url(view_url: str) -> Optional[str]:
    """`.../Regular%20City%20Council%20Meeting_2026-09-22_06-00-56%20PM.mp4` -> `2026-09-22`; None when the name has no date."""
    name = unquote(urlparse(view_url or "").path.rsplit("/", 1)[-1])
    match = _FILE_DATE_RE.search(name)
    return match.group(1) if match else None


def clean_caption_url(url: str, customer_guid: str, meeting_guid: str) -> str:
    """Drops a doubled `customer-{g}/meetings/{m}/` segment from a caption URL; returns the URL unchanged when it is not doubled."""
    segment = f"customer-{customer_guid}/meetings/{meeting_guid}/"
    lowered = url.lower()
    seg = segment.lower()
    first = lowered.find(seg)
    second = lowered.find(seg, first + len(seg)) if first >= 0 else -1
    if second < 0:
        return url
    return url[:second] + url[second + len(segment) :]


def _doc_link(record: dict, doc_type: str, prefer_pdf: bool = False) -> Optional[str]:
    docs = [
        d
        for d in record.get("relatedDocuments") or []
        if isinstance(d, dict) and d.get("docType") == doc_type and d.get("publicUrl")
    ]
    if prefer_pdf:
        for d in docs:
            if (d.get("mimeType") or "").endswith("pdf") or str(
                d.get("filename") or ""
            ).lower().endswith(".pdf"):
                return d["publicUrl"]
    return docs[0]["publicUrl"] if docs else None


def _format_from_url(video_url: str) -> str:
    ext = urlparse(video_url).path.rsplit(".", 1)[-1].lower()
    return ext if ext in ("mp4", "mp3", "m4a", "m3u8", "webm") else "mp4"


class AVCaptureAllAssetFinder(AssetFinder):
    platform_name = "avcaptureall"

    async def resolve(self, url: str) -> ResolvedMeeting:
        guid = meeting_guid_from_url(url)
        if not guid:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This is an AV Capture All page, but not a single meeting. Open the "
                    "meeting itself (an address like media.avcaptureall.cloud/meeting/"
                    "809abb94-6a6b-474b-83ae-7ed17c067971) and paste that link."
                ],
            )
        source_url = meeting_url(guid)
        external_id = f"avcaptureall:{guid}"
        # Raises HeadlessBrowserUnavailable when no browser can start (office Macs only, like Vimeo).
        try:
            reply = await asyncio.wait_for(
                fetch_api_reply_via_browser(
                    source_url,
                    reply_url_contains=f"{_REPLY_PATH}{guid}",
                ),
                timeout=_CAPTURE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            reply = None
        record = self._record_from_reply(reply, guid)
        if record is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=source_url,
                external_id=external_id,
                video_warnings=["Could not load this AV Capture All meeting."],
            )

        customer_guid = str(record.get("customerGuid") or "").lower()
        view_url = str(record.get("viewUrl") or "")
        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=source_url,
            external_id=external_id,
            title=(record.get("title") or "").strip() or None,
            jurisdiction=(record.get("customerName") or "").strip() or None,
            meeting_body=(record.get("departmentTitle") or "").strip() or None,
            meeting_location=(record.get("location") or "").strip() or None,
            video_channel=f"avcapture:{customer_guid}" if customer_guid else None,
            agenda_link=_doc_link(record, "Agenda", prefer_pdf=True),
            packet_link=_doc_link(record, "PdfBundle"),
        )
        resolved.date = local_date_from_file_url(view_url)
        if resolved.date is None:
            utc_date = str(record.get("dateScheduled") or "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", utc_date):
                resolved.date = utc_date
                resolved.video_warnings.append(
                    "The file name has no date, so the date shown is the scheduled date in UTC "
                    "and may be a day late for an evening meeting."
                )

        if not record.get("hasRecording") or not view_url:
            resolved.video_warnings.append(
                "This AV Capture All meeting has no recording yet."
            )
            return resolved

        resolved.video_url = view_url
        resolved.video_format = _format_from_url(view_url)
        duration = record.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            resolved.video_duration_seconds = float(duration)

        caption_url = record.get("videoSubtitlesUrl")
        if caption_url:
            async with aiohttp.ClientSession(
                headers={"User-Agent": _USER_AGENT}
            ) as session:
                cues = await self._fetch_cues(session, caption_url, customer_guid, guid)
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
    def _record_from_reply(reply, guid: str) -> Optional[dict]:
        if not reply:
            return None
        status, body = reply
        if status != 200:
            logger.warning("avcaptureall record HTTP %s for %s", status, guid)
            return None
        try:
            record = json.loads(body)
        except ValueError:
            logger.warning("avcaptureall record was not JSON for %s", guid)
            return None
        if not isinstance(record, dict) or not record.get("meetingGuid"):
            return None
        return record

    @classmethod
    async def _fetch_cues(
        cls,
        session: aiohttp.ClientSession,
        vtt_url: str,
        customer_guid: str,
        meeting_guid: str,
    ):
        raw, status = await cls._get_bytes(session, vtt_url)
        if raw is None and status == 403:
            clean = clean_caption_url(vtt_url, customer_guid, meeting_guid)
            if clean != vtt_url:
                raw, _ = await cls._get_bytes(session, clean)
        if raw is None:
            return None
        return dedupe_rollup_cues(parse_vtt(decode_vtt_bytes(raw))) or None

    @staticmethod
    async def _get_bytes(session: aiohttp.ClientSession, url: str):
        """`(bytes or None, status or None)`."""
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "avcaptureall VTT HTTP %s for %s", response.status, url
                    )
                    return None, response.status
                return await response.read(), 200
        except Exception:
            logger.warning("avcaptureall VTT fetch failed for %s", url, exc_info=True)
            return None, None
