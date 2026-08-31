"""Chicago's City Clerk "ELMS" (`chicityclerkelms.chicago.gov`) -- the
legislative portal for the third-largest city in the US, one of the two
"50 largest US cities" gaps this adapter closes (El Paso, TX is the
other, and reaches this app through `vimeo.py` directly).

Built 2026-08-21 (WO-29), against a real public API confirmed live long
before any of this was written -- see BACKLOG_DONE.md's WO-29 entry and
BACKLOG.md's original 2026-08-10/11/12 investigation for how it was
found.

## Why an adapter, when generic_fallback already "handled" it

It didn't, really: the meeting page's raw server HTML contains zero
mention of "vimeo" -- confirmed live by curling the page and grepping.
The video is injected client-side from a separate API call
(`data.videoLink.forEach(...)` in the page's own JS), so the generic
fallback could only ever produce an honest "we couldn't find anything."

## The real API

`https://api.chicityclerkelms.chicago.gov/meeting-agenda/{meetingId}` --
public, unauthenticated, plain-`curl`-fetchable, no Cloudflare and no
headless browser needed. `meetingId` is a **GUID**, taken straight off
the portal URL's own `?meetingId=` query param. Real fields used here:

- `videoLink` -- a list, whose one entry is a real Vimeo URL. Two
  distinct real shapes across the five confirmed samples:
  `vimeo.com/showcase/8925576?video=1210310337` (numeric showcase id) and
  `vimeo.com/showcase/citycouncil/...` / `.../video/{id}` (slug id).
  `vimeo.py` parses all of them; this module never string-slices a Vimeo
  URL itself.
- `body` -- the meeting body ("City Council", "Committee on Budget and
  Government Operations"), used as the title.
- `date` -- a real ISO timestamp.
- `files[]` -- real PDF attachments, including an `attachmentType:
  "Agenda"` one, surfaced as `agenda_link`.

## Two real, documented limitations -- neither hidden

1. **No captions.** `transcriptLink` exists in the API schema but is
   empty (`[""]` or `[]`) on all five confirmed real samples spanning
   2020-2026. Nothing is guessed from it; when it IS populated, it's
   surfaced as a warning rather than parsed against an invented format,
   the same treatment `townhallstreams.py` gives its own unconfirmed
   `get_transcriptions` endpoint. Vimeo's own caption wall applies on top
   of that -- see `vimeo.py`'s module docstring.
2. **No timestamped agenda items.** `agenda.groups[].items[]` is genuinely
   rich -- 473 real items on one confirmed sample (matter title, matter
   type, record number, action taken, vote type) -- but carries **no time
   offsets of any kind**. Unlike LIMS/Hyland/IQM2, there is nothing to
   join against a video position, so populating `agenda_items` would mean
   inventing timestamps (every item seeking to 0:00). It is deliberately
   left unpopulated; the real, linkable agenda PDF goes in `agenda_link`
   instead. Surfacing that item text as untimestamped agenda *text* would
   need a new `ResolvedMeeting` field plus an Archive schema change --
   tracked as its own entry in BACKLOG.md, not smuggled in here.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting
from .vimeo import VimeoAssetFinder, parse_vimeo_video
from ..utils.url_guard import guarded_get, read_capped_text

logger = logging.getLogger("rtr_deeplink.chicago_elms")

_API_BASE = "https://api.chicityclerkelms.chicago.gov/meeting-agenda/"

# Single-tenant platform: this domain IS the City of Chicago's own clerk
# portal, so the jurisdiction is a fact about the domain rather than
# something to mine out of page text (same as lims.py's Minneapolis and
# slc.py's Salt Lake City).
_JURISDICTION = "Chicago, IL"


def extract_meeting_id(url: str) -> Optional[str]:
    """The portal's own `?meetingId={GUID}` param, matched case-
    insensitively -- real URLs use `/Meeting/?meetingId=...`."""
    query = parse_qs(urlparse(url).query)
    for key, values in query.items():
        if key.lower() == "meetingid" and values and values[0].strip():
            return values[0].strip()
    return None


class ChicagoElmsAssetFinder(AssetFinder):
    """See this module's docstring for the real API this was built from."""

    platform_name = "chicago_elms"

    async def resolve(self, url: str) -> ResolvedMeeting:
        meeting_id = extract_meeting_id(url)
        if not meeting_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This Chicago City Clerk link doesn't point at one specific "
                    "meeting -- open a meeting from the calendar and paste that "
                    "link instead."
                ],
            )

        payload = await self._fetch_meeting(meeting_id)
        if payload is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=f"chicago_elms:{meeting_id}",
                video_warnings=[
                    "We couldn't load this meeting from the Chicago City Clerk's "
                    "site -- it may be temporarily unreachable."
                ],
            )

        vimeo_parsed = self._first_vimeo_video(payload.get("videoLink"))
        if vimeo_parsed:
            video_id, privacy_hash = vimeo_parsed
            # `url` is this portal's own real domain
            # (`chicityclerkelms.chicago.gov`) -- pass it as the Vimeo
            # oEmbed Referer so a video whose owner later restricts it to
            # specific domains (see vimeo.py's `domain_hint`, WO-86) has a
            # real chance of recovering rather than declining outright.
            # No Chicago video has needed this yet, but it's confirmed
            # harmless to send unconditionally.
            resolved = await VimeoAssetFinder.resolve_video_id(
                video_id,
                privacy_hash=privacy_hash,
                source_url=url,
                domain_hint=urlparse(url).netloc,
            )
            # Delegation keeps the original ELMS URL as source_url (the
            # PrimeGov/CivicWeb pattern), but everything else below comes
            # from ELMS's own far better metadata, not Vimeo's account
            # name / video title.
            resolved.platform = self.platform_name
        else:
            resolved = ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "No video has been posted for this Chicago meeting yet."
                ],
            )

        resolved.external_id = f"chicago_elms:{meeting_id}"
        resolved.jurisdiction = _JURISDICTION
        title = (payload.get("body") or "").strip()
        if title:
            resolved.title = title
        date = (payload.get("date") or "").strip()
        if len(date) >= 10:
            resolved.date = date[:10]

        agenda_link = self._agenda_link(payload.get("files"))
        if agenda_link:
            resolved.agenda_link = agenda_link

        transcript_link = self._first_nonempty(payload.get("transcriptLink"))
        if transcript_link:
            # Never confirmed populated on any real sample (see the module
            # docstring) -- surfaced honestly rather than parsed against a
            # format nobody has actually seen.
            resolved.transcript_warnings = [
                "Chicago's site lists a transcript for this meeting, which we "
                f"haven't been able to read yet: {transcript_link}",
                *resolved.transcript_warnings,
            ]
        return resolved

    @staticmethod
    def _first_vimeo_video(video_links: Any):
        for link in video_links or []:
            if not isinstance(link, str) or not link.strip():
                continue
            parsed = parse_vimeo_video(link.strip())
            if parsed:
                return parsed
        return None

    @staticmethod
    def _first_nonempty(values: Any) -> Optional[str]:
        for value in values or []:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _agenda_link(files: Any) -> Optional[str]:
        """Prefers the real `attachmentType: "Agenda"` file, then a
        "Notice" (which on the confirmed Budget-committee sample IS the
        agenda notice). Skips `.crdownload` paths -- a real artifact seen
        live on Chicago's own blob store, where a partially-uploaded file
        kept its browser download-in-progress extension."""
        entries: List[Dict[str, Any]] = [
            f for f in (files or []) if isinstance(f, dict)
        ]

        def usable(entry: Dict[str, Any]) -> Optional[str]:
            path = (entry.get("path") or "").strip()
            if not path or path.lower().endswith(".crdownload"):
                return None
            return path

        for wanted in ("agenda", "notice"):
            for entry in entries:
                if (entry.get("attachmentType") or "").strip().lower() == wanted:
                    path = usable(entry)
                    if path:
                        return path
        return None

    @staticmethod
    async def _fetch_meeting(meeting_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with guarded_get(
                    session,
                    _API_BASE + meeting_id,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Chicago ELMS meeting fetch got HTTP %s for %s",
                            response.status,
                            meeting_id,
                        )
                        return None
                    payload = json.loads(await read_capped_text(response))
        except Exception:
            logger.warning(
                "Chicago ELMS meeting fetch failed for %s", meeting_id, exc_info=True
            )
            return None
        return payload if isinstance(payload, dict) else None
