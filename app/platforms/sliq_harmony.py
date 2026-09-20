"""Sliq Harmony ("PowerBrowser") -- the video archive behind at least seven
U.S. state legislature websites. Built WO-921 (2026-09-20) after WO-919's
vendor scan found one shared host, `sg001-harmony.sliq.net`, carrying
Arkansas (tenant 00284), Colorado (00327), Delaware (00329), Kansas
(00287), New Mexico (00293), the Oklahoma House (00283) and West
Virginia's Senate (00289).

WHAT WAS CONFIRMED LIVE (2026-09-20, plain HTTP, honest User-Agent, 2s
between requests, no headless browser needed) before any of this was
written -- real pages from all seven tenants, 45 events read by hand (the
finished adapter was then run live over 82 recent events, zero errors):

* Every tenant is a path on ONE shared host:
  `https://sg001-harmony.sliq.net/{tenant}/Harmony/en/...`. The tenant is
  a five-digit number, the government is the tenant, and the host alone
  says nothing about which government it is (so pins must be per tenant
  path, see `tenant_overrides.csv`).
* An event page is `/{tenant}/Harmony/en/PowerBrowser/PowerBrowserV3/
  {yyyymmdd}/-1/{eventId}`. The `{yyyymmdd}` is the day the LINK was made
  (the listing pages stamp today's date on every link), not the meeting
  date -- the same meeting is reachable under any date, so this adapter
  rebuilds a stable source_url from the meeting's own start date.
* The page looks JavaScript-driven but is not: the server writes a
  `var dataModel = {...}` block straight into the HTML, so ONE plain GET
  carries everything -- `EventInfo` (JSON: title, room, status, start and
  end times), `availableStreams` (JSON: the HLS `playlist.m3u8` URL,
  duration in seconds), `ccItems` (JSON: closed captions), `AgendaTree`
  (JSON: timed agenda items) and `Speakers`. The values are JSON inside a
  JavaScript object literal, so they are pulled out with
  `json.JSONDecoder().raw_decode` at the key, never with a regex over the
  braces.
* Video: the HLS URL lives on a media host (`sg002-live.sliq.net`,
  `.../{tenant}-vod/_definst_/YYYY/MM/<name>.mp4/playlist.m3u8`), answers
  with `access-control-allow-origin: *`, and needs no cookie or Referer,
  so the existing hls.js player plays it as `video_format="m3u8"`.
* Captions: `ccItems` is `{language: [{Begin, End, Content}]}`. `Begin`
  and `End` are absolute local wall-clock times
  (`2026-09-17T13:30:34.873`), not offsets. The video starts at
  `mediaStartTime` (always equal to `playRangeStart` and to the meeting's
  actual start on all 45 events, and `mediaStartOffset` was 0 on all 45),
  so a caption's offset into the video is `Begin - mediaStartTime`. Most
  tenants publish real captions on most meetings (Colorado, Oklahoma,
  West Virginia, Arkansas, Delaware, New Mexico); **Kansas published none
  on any of the 12 recent meetings read**, and each tenant has some
  meetings with an empty `ccItems` -- that is reported as "no captions",
  never guessed at. New Mexico's language key is sometimes `lang` instead
  of `en`; the language is taken from the caption text itself, not the key.
* Agenda: `AgendaTree` items carry `startTime` (absolute, same clock as
  captions) and nest through `children`. Empty on Kansas, Delaware,
  Oklahoma and New Mexico events; populated on most Arkansas, Colorado and
  West Virginia events. `Speakers` (West Virginia, Arkansas) are also
  timed but are individual speaker turns, not chapters -- left out on
  purpose, they would swamp the agenda list.
* No video: an event that is scheduled but has not happened has an empty
  `availableStreams`; a meeting whose recording was never published has a
  stream with `Enabled: false` and a placeholder Url (`""` or
  `"http://novod.com"`, confirmed on three New Mexico events). Both come
  back as a real meeting with a plain video warning and no video_url.
* Listing pages (`/{tenant}/Harmony/en/View/RecentEnded/`) are plain HTML
  with one `divEvent` block per meeting (title, room, status class, date).
  A tenant-level or listing URL raises `CalendarPageError` with the ended
  meetings as candidates, the same pick-list pattern Legistar's calendar
  uses.

Identity: one government per state (architecture decision D1), the
chamber or committee is `meeting_body`. This adapter sets `jurisdiction`
from a small tenant table (falling back to the site's own page title for
an unlisted tenant) and `meeting_body` from the event title; the
government id comes from per-tenant pins, never from the shared host.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder, CalendarCandidate, CalendarPageError
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    dedupe_rollup_cues,
    detect_language_from_texts,
    is_likely_garbled,
)

logger = logging.getLogger("rtr_deeplink.sliq_harmony")

TARGET_LANGUAGE = "en"

_USER_AGENT = (
    "Mozilla/5.0 (compatible; RedTapeRecordings/1.0; +https://redtaperecordings.com)"
)

# `sg001-harmony.sliq.net` today; a numbered-server pattern so a sibling
# server (`sg002-harmony...`) is recognised without a code change. The
# MEDIA hosts (`sg002-live.sliq.net`, `sg001-media.sliq.net`) have no
# "harmony" in the name and are deliberately not matched.
_HOST_RE = re.compile(r"^(?:[a-z0-9]+-)?harmony\.sliq\.net$")
_PATH_RE = re.compile(r"^/(\d{5})/harmony(?:/|$)", re.IGNORECASE)
_EVENT_RE = re.compile(
    r"/powerbrowser/powerbrowserv3/(?:(\d{8})/-?\d+/)?(\d+)(?:/|$)", re.IGNORECASE
)

# The seven tenants confirmed live 2026-09-20 (WO-921). One government per
# state (D1): the chamber/committee is the meeting body, never a
# government of its own. An unlisted tenant falls back to the site's own
# page title.
TENANT_JURISDICTIONS: Dict[str, str] = {
    "00284": "Arkansas State Legislature",
    "00327": "Colorado General Assembly",
    "00329": "Delaware General Assembly",
    "00287": "Kansas State Legislature",
    "00293": "New Mexico Legislature",
    "00283": "Oklahoma House of Representatives",
    "00289": "West Virginia Legislature",
}

# Placeholder stream Urls Sliq writes when a meeting has no recording.
_NO_VOD_MARKERS = ("novod.com",)

_MAX_CANDIDATES = 60

_DATAMODEL_KEYS = {
    "event_info": "EventInfo:",
    "streams": "availableStreams",
    "captions": "ccItems:",
    "agenda": "AgendaTree:",
}


def is_sliq_harmony_url(url: str) -> bool:
    """True for any `*-harmony.sliq.net/{tenant}/Harmony/...` URL, event or
    listing. Used by `detect_platform()`."""
    parsed = urlparse(url)
    if not _HOST_RE.match(parsed.netloc.lower()):
        return False
    return _PATH_RE.match(parsed.path) is not None


def parse_sliq_url(url: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """`(host, tenant, event_id_or_None)`; None if not a Harmony URL. A
    None event id means a listing/tenant-level URL."""
    if not is_sliq_harmony_url(url):
        return None
    parsed = urlparse(url)
    tenant = _PATH_RE.match(parsed.path).group(1)  # type: ignore[union-attr]
    m = _EVENT_RE.search(parsed.path)
    return parsed.netloc.lower(), tenant, (m.group(2) if m else None)


def _extract_json_after(html: str, key: str) -> Any:
    """The JSON value that follows `key` in the page's `dataModel` block
    (`key` + optional ` ` + `:`). None when the key is absent or the value
    is not JSON (Sliq writes `null` for `ccItems` on a not-started event)."""
    i = html.find(key)
    if i < 0:
        return None
    i += len(key)
    while i < len(html) and html[i] in " :\t\r\n":
        i += 1
    try:
        value, _end = json.JSONDecoder().raw_decode(html[i:])
    except ValueError:
        return None
    return value


def _js_string(html: str, key: str) -> Optional[str]:
    m = re.search(re.escape(key) + r"\s*:\s*'([^']*)'", html)
    return m.group(1) if m and m.group(1) else None


# Colorado appends the meeting date to every event title
# ("Capitol Building Advisory Committee [Sep 17, 2026]",
# "... [Sep 03, 2026 - Upon Adjournment]"); that is a date, not part of
# the body's name.
_TRAILING_DATE_RE = re.compile(r"\s*\[[^\]]*\b20\d{2}\b[^\]]*\]\s*$")


def _body_name(title: Optional[str]) -> Optional[str]:
    if not title:
        return title
    return _TRAILING_DATE_RE.sub("", title).strip() or title


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """`2026-09-17T13:30:34.873` or `...0000000` (7 fractional digits) ->
    naive datetime; None on anything else."""
    if not value:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?", value)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
    if m.group(2):
        dt = dt.replace(microsecond=int((m.group(2) + "000000")[:6]))
    return dt


def _pick_stream(streams: Any) -> Tuple[Optional[dict], bool]:
    """`(stream, audio_only)`: the first enabled, recorded (not live)
    stream with a real HLS/MP4 URL, video preferred over audio-only."""
    usable: List[dict] = []
    for s in streams if isinstance(streams, list) else []:
        url = (s.get("Url") or "").strip()
        if (
            not s.get("Enabled")
            or s.get("IsLive")
            or not url.lower().startswith("http")
        ):
            continue
        if any(marker in url.lower() for marker in _NO_VOD_MARKERS):
            continue
        if ".m3u8" not in url.lower() and ".mp4" not in url.lower():
            continue
        usable.append(s)
    video = [s for s in usable if not s.get("AudioOnly")]
    if video:
        return video[0], False
    if usable:
        return usable[0], True
    return None, False


def _flatten_agenda(nodes: Any, start: Optional[datetime]) -> List[TranscriptSegment]:
    out: List[TranscriptSegment] = []
    if not isinstance(nodes, list) or start is None:
        return out

    def walk(items: List[dict]) -> None:
        for node in items:
            if not isinstance(node, dict) or node.get("deleted"):
                continue
            text = re.sub(r"\s+", " ", (node.get("text") or "")).strip()
            at = _parse_ts(node.get("startTime"))
            if text and at is not None:
                offset = max(0.0, (at - start).total_seconds())
                out.append(TranscriptSegment(start=offset, end=offset, text=text))
            if node.get("children"):
                walk(node["children"])

    walk(nodes)
    out.sort(key=lambda s: s.start)
    return out


def _caption_cues(items: Any, start: datetime) -> List[Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        begin = _parse_ts(item.get("Begin"))
        if begin is None:
            continue
        text = re.sub(r"\s+", " ", (item.get("Content") or "")).strip()
        if not text:
            continue
        end = _parse_ts(item.get("End")) or begin
        s = max(0.0, (begin - start).total_seconds())
        e = max(s, (end - start).total_seconds())
        cues.append({"start": s, "end": e, "text": text})
    cues.sort(key=lambda c: c["start"])
    return cues


def parse_event_page(html: str) -> Dict[str, Any]:
    """Pull the JSON pieces out of an event page's `dataModel`. Pure and
    offline -- the tests run it on saved real pages."""
    info = _extract_json_after(html, _DATAMODEL_KEYS["event_info"]) or {}
    text_tags = (info.get("textTags") or {}) if isinstance(info, dict) else {}
    time_tags = (info.get("timeTags") or {}) if isinstance(info, dict) else {}

    def tag(name: str) -> Optional[str]:
        v = (text_tags.get(name) or {}).get("text")
        return v.strip() if isinstance(v, str) and v.strip() else None

    def ts(name: str) -> Optional[str]:
        return (time_tags.get(name) or {}).get("timestamp")

    title_m = re.search(r"<title>\s*([^<]*?)\s*</title>", html, re.IGNORECASE)
    duration_m = re.search(r"mediaDuration\s*:\s*(\d+)", html)
    return {
        "title": tag("TITLE"),
        "location": tag("LOCATION"),
        "status": tag("eventStatus"),
        "status_code": tag("MEETINGSTATUS"),
        "scheduled_start": ts("SCHEDULEDSTART"),
        "actual_start": ts("STARTTIME"),
        "media_start": _js_string(html, "mediaStartTime"),
        "duration": int(duration_m.group(1)) if duration_m else None,
        "streams": _extract_json_after(html, _DATAMODEL_KEYS["streams"]),
        "captions": _extract_json_after(html, _DATAMODEL_KEYS["captions"]),
        "agenda": _extract_json_after(html, _DATAMODEL_KEYS["agenda"]),
        "page_title": title_m.group(1) if title_m else None,
    }


_DIV_EVENT_RE = re.compile(
    r"PowerBrowserV3/(\d{8})/-1/(\d+)'\)\"\s+title=\"([^\"]*)\"(.*?)</table>",
    re.DOTALL,
)


def parse_listing(html: str) -> List[Dict[str, str]]:
    """Meetings on a Harmony listing page, newest id first. Skips the
    `{Id}` template block the page ships for its client-side renderer."""
    out: List[Dict[str, str]] = []
    seen = set()
    for m in _DIV_EVENT_RE.finditer(html):
        event_id = m.group(2)
        if event_id in seen:
            continue
        seen.add(event_id)
        block = m.group(4)
        status = re.search(r'class="eventStatus [^"]*">([^<]*)<', block)
        when = re.search(r'class="eventDate">([^<]*)<', block)
        title = re.sub(r"&#39;|&#x27;", "'", m.group(3))
        out.append(
            {
                "id": event_id,
                "title": re.sub(r"&amp;", "&", title).strip(),
                "status": (status.group(1).strip() if status else ""),
                "date": (when.group(1).strip() if when else ""),
            }
        )
    out.sort(key=lambda e: -int(e["id"]))
    return out


def _listing_date_to_iso(text: str) -> str:
    """`Fri, Sep 18, 2026` -> `2026-09-18`; the raw text if it will not parse."""
    try:
        return datetime.strptime(text, "%a, %b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return text


def _site_name(page_title: Optional[str], event_title: Optional[str]) -> Optional[str]:
    """The site's name from `<title>` (`{Site} - {event title}`)."""
    if not page_title:
        return None
    if event_title and page_title.endswith(" - " + event_title):
        return page_title[: -len(" - " + event_title)].strip() or None
    return page_title.split(" - ")[0].strip() or None


class SliqHarmonyAssetFinder(AssetFinder):
    platform_name = "sliq_harmony"

    async def resolve(self, url: str) -> ResolvedMeeting:
        parsed = parse_sliq_url(url)
        if parsed is None:
            raise ValueError(f"Not a Sliq Harmony URL: {url}")
        host, tenant, event_id = parsed
        base = f"https://{host}/{tenant}/Harmony/en"
        headers = {"User-Agent": _USER_AGENT}

        async with aiohttp.ClientSession(headers=headers) as session:
            if event_id is None:
                html = await self._fetch(session, f"{base}/View/RecentEnded/")
                if html is None:
                    raise ValueError(f"Could not read the Sliq Harmony listing: {url}")
                raise self._listing_error(host, tenant, html)

            # Any date segment works; today's is what the site's own links use.
            page_url = f"{base}/PowerBrowser/PowerBrowserV3/{_today()}/-1/{event_id}"
            html = await self._fetch(session, page_url)
        if html is None:
            raise ValueError(f"Could not read the Sliq Harmony event page: {url}")
        return self._build(host, tenant, event_id, html)

    def _listing_error(self, host: str, tenant: str, html: str) -> CalendarPageError:
        events = [
            e for e in parse_listing(html) if e["status"].lower() != "not started"
        ]
        candidates: List[CalendarCandidate] = [
            {
                "title": e["title"],
                "date": _listing_date_to_iso(e["date"]),
                "url": (
                    f"https://{host}/{tenant}/Harmony/en/PowerBrowser/PowerBrowserV3/"
                    f"{_today()}/-1/{e['id']}"
                ),
            }
            for e in events[:_MAX_CANDIDATES]
        ]
        return CalendarPageError(
            "This is a Sliq Harmony listing of recent recordings, not one "
            "meeting. Pick a meeting.",
            candidates,
        )

    def _build(
        self, host: str, tenant: str, event_id: str, html: str
    ) -> ResolvedMeeting:
        page = parse_event_page(html)
        if not page["title"]:
            raise ValueError(
                f"No meeting data found on the Sliq Harmony page for event {event_id}"
            )

        start = _parse_ts(page["media_start"]) or _parse_ts(page["actual_start"])
        scheduled = _parse_ts(page["scheduled_start"])
        when = start or scheduled
        date_iso = when.strftime("%Y-%m-%d") if when else None
        stable_date = when.strftime("%Y%m%d") if when else _today()
        source_url = (
            f"https://{host}/{tenant}/Harmony/en/PowerBrowser/PowerBrowserV3/"
            f"{stable_date}/-1/{event_id}"
        )

        site = _site_name(page["page_title"], page["title"])
        jurisdiction = TENANT_JURISDICTIONS.get(tenant) or site

        video_warnings: List[str] = []
        transcript_warnings: List[str] = []
        stream, audio_only = _pick_stream(page["streams"])
        video_url = stream["Url"].strip() if stream else None
        video_format = (
            "m3u8"
            if video_url and ".m3u8" in video_url.lower()
            else ("mp4" if video_url else None)
        )
        if stream is None:
            status = (page["status"] or "").lower()
            if (
                status in ("not started", "suspended")
                or (page["status_code"] or "") == "0"
            ):
                video_warnings.append(
                    "This meeting has not happened yet, so there is no recording."
                )
            elif status == "in progress":
                video_warnings.append(
                    "This meeting is live now; the recording is published after it ends."
                )
            else:
                video_warnings.append(
                    "The legislature's video site lists this meeting but has "
                    "not published a recording of it."
                )
        elif audio_only:
            video_warnings.append(
                "Only an audio recording is published for this meeting, no picture."
            )

        segments: List[TranscriptSegment] = []
        language: Optional[str] = None
        alternates: List[AlternateTranscript] = []
        agenda_items: List[TranscriptSegment] = []
        if start is not None:
            agenda_items = _flatten_agenda(page["agenda"], start)
            tracks: List[Tuple[Optional[str], List[Dict[str, Any]]]] = []
            captions = page["captions"]
            if isinstance(captions, dict):
                for _key, items in captions.items():
                    cues = dedupe_rollup_cues(_caption_cues(items, start))
                    if cues:
                        tracks.append(
                            (detect_language_from_texts(c["text"] for c in cues), cues)
                        )
            if tracks:
                chosen = next((t for t in tracks if t[0] == TARGET_LANGUAGE), tracks[0])
                language, cues = chosen
                segments = [TranscriptSegment(**c) for c in cues]
                if language and language != TARGET_LANGUAGE:
                    transcript_warnings.append(
                        f"These captions appear to be in '{language}', not "
                        f"'{TARGET_LANGUAGE}' — no matching-language track was found."
                    )
                if is_likely_garbled(cues, lang=language):
                    transcript_warnings.append(
                        "This transcript looks garbled at the source (not a parsing "
                        "bug on our end) — treat it as approximate. You can request "
                        "a transcript from the audio instead."
                    )
                alternates = [
                    AlternateTranscript(
                        language=lang, segments=[TranscriptSegment(**c) for c in other]
                    )
                    for lang, other in tracks
                    if other is not cues
                ]
        if not segments and stream is not None:
            transcript_warnings.append(
                "The legislature's video site published no captions for this meeting."
            )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=source_url,
            external_id=f"sliq_harmony:{host}:{tenant}:{event_id}",
            title=page["title"],
            date=date_iso,
            jurisdiction=jurisdiction,
            meeting_body=_body_name(page["title"]),
            meeting_location=page["location"],
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            agenda_items=agenda_items,
            transcript_language=language,
            alternate_transcripts=alternates,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=25)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Sliq Harmony GET got HTTP %s for %s", response.status, url
                    )
                    return None
                return await response.text()
        except Exception:
            logger.warning("Sliq Harmony GET failed for %s", url, exc_info=True)
            return None
