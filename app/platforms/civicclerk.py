import re
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import (
    STRUCTURED_CAPTION_PARSERS,
    decode_vtt_bytes,
    detect_language_from_texts,
    is_likely_garbled,
    parse_captions_by_extension,
)

TARGET_LANGUAGE = "en"

# A county tenant's subdomain, when it encodes one at all, reads
# "{countyname}(co|county){state-code}" -- all four real production
# instances confirmed live 2026-08-23: churchillconv (Churchill County,
# NV), lincolncoor (Lincoln County, OR), fultoncoin (Fulton County, IN),
# lancastercosc (Lancaster County, SC). Never trusted alone: the parse
# only wins when the meeting venue's own ZIP independently maps to the
# SAME county via the Census ZCTA crosswalk (see
# _county_tenant_jurisdiction()), which is what keeps a city subdomain
# that merely contains "co{state}" letters (chicoca -> "chi"+co+ca,
# sanfranciscoca -> "sanfrancis"+co+ca) from ever matching -- their ZIP
# counties don't agree with the accidental name fragment.
_COUNTY_SUBDOMAIN_RE = re.compile(
    r"^(?P<name>[a-z][a-z.\-]*?)(?:co|county)(?P<st>[a-z]{2})\d*$"
)

# County-body meeting names, anchored at the start so "Joint Meeting
# with County Board" (a city meeting that merely involves the county)
# can never match. Both real shapes confirmed live: "County Board of
# Supervisors" (sccwi -- St. Croix County, WI, whose subdomain encodes
# nothing parseable), "Board of County Commissioners - ..."
# (churchillconv).
_COUNTY_BODY_EVENT_RE = re.compile(
    r"^\s*(?:county\s+(?:board|council|commission)\b"
    r"|board\s+of\s+county\s+commissioners\b)",
    re.IGNORECASE,
)


class CivicClerkAssetFinder(AssetFinder):
    """Resolves video + transcript/chapters for a CivicClerk meeting page.

    CivicClerk portal pages (`<subdomain>.portal.civicclerk.com/event/<id>/media`)
    are a client-rendered SPA with no server HTML to scrape — unlike Granicus,
    there's nothing to BeautifulSoup. Instead it's backed by a clean public REST
    API at `<subdomain>.api.civicclerk.com/v1/...` (found by watching network
    requests in a real browser against clovisca.portal.civicclerk.com), so this
    adapter calls that API directly rather than rendering the page.

    Real API responses observed (2026-08-06) across 3 sample cities:
      - `Events/{id}`: title (eventName), date (eventDate), jurisdiction
        (eventLocation.city/state) — far more reliable than Granicus's
        subdomain-guessing.
      - `EventsMedia/{id}`: `videoUrl` (direct mp4, no HLS involved) or, when
        empty, `externalVideoUrl` pointing to a file hosted on the city's own
        site (seen for Highland, CA — an MP3 audio recording, not video).
      - `EventsMedia.eventBookmarks`: agenda-item markers with `markerTitle`
        and `markerTimeStart` (seconds). Used here as a deep-link fallback
        when there's no real transcript — deep-linking to a moment is this
        app's primary goal, so "no captions" shouldn't mean "no deep links."
      - `EventsMedia.closedCaptionUrl` / `.closedCaptionTracks`: real,
        populated caption data — confirmed 2026-08-08 via a real Emporia, KS
        event (id 585, user-supplied example) after three earlier sample
        cities all had these null/empty. The file is **SRT, not VTT**
        (`.closedCaptionTracks[].file` ends in `.srt`) — the first real
        CivicClerk sample with populated captions, so this is the only
        confirmed format; a VTT track has never actually been observed
        here, only assumed possible from the schema.
    """

    platform_name = "civicclerk"

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        parsed = urlparse(url)
        subdomain = parsed.netloc.split(".")[0]
        api_base = f"https://{subdomain}.api.civicclerk.com/v1"

        match = re.search(r"/event/(\d+)", parsed.path)
        if not match:
            raise ValueError(f"Could not find an event ID in URL path: {parsed.path}")
        event_id = match.group(1)

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        alternate_transcripts: List[AlternateTranscript] = []

        async with aiohttp.ClientSession() as session:
            event, media = await self._fetch_json_pair(
                session,
                f"{api_base}/Events/{event_id}",
                f"{api_base}/EventsMedia/{event_id}",
            )

            title = event.get("eventName") or None
            date = (event.get("eventDate") or "")[:10] or None
            location = event.get("eventLocation") or {}
            city = location.get("city")
            state = location.get("state")
            if city and not state:
                # The API's own location.state is empty for some customers
                # (unconfirmed how common -- no real example seen yet, see
                # BACKLOG.md's "no-state jurisdiction audit") -- falls back
                # to the same shared lookup every free-text adapter uses.
                state = jurisdiction_enrich.lookup_city_state(city)
            jurisdiction = ", ".join(p for p in (city, state) if p) or None
            # eventLocation is the meeting VENUE's address, not the
            # government's name -- for a county tenant the venue city is
            # the county seat, so the plain join above files a county
            # government under an unrelated city. See
            # _county_tenant_jurisdiction() for the four real production
            # rows this produced and the two signals that correct it.
            county_jurisdiction = self._county_tenant_jurisdiction(
                subdomain, event, location
            )
            if county_jurisdiction:
                jurisdiction = county_jurisdiction
            if not jurisdiction:
                # eventLocation is sometimes entirely empty (city AND
                # state both null, not just a missing state) -- confirmed
                # live on Los Altos Hills, CA (event 4567), where the
                # chain's validated-subdomain tier alone resolves this
                # correctly with zero extra network calls, no page_text/
                # html needed.
                jurisdiction = jurisdiction_enrich.extract_jurisdiction_chain(
                    page_text="", html="", url=url
                )
            if not jurisdiction:
                # Richer, costlier fallback: CivicClerk's own agenda file
                # is fetchable as plain text (confirmed live on Los Altos
                # Hills' real "Town of Los Altos Hills / City Council..."
                # agenda) and is a stronger signal than the subdomain
                # alone -- it doesn't depend on wordninja splitting a
                # customer's subdomain cleanly. Only tried once the free
                # subdomain-only tier above has already failed, since it
                # costs two extra requests (the GetMeetingFile lookup,
                # then the SAS-signed blob itself).
                agenda_text = await self._fetch_agenda_text(session, event)
                if agenda_text:
                    jurisdiction = jurisdiction_enrich.extract_jurisdiction_chain(
                        page_text=agenda_text, html="", url=url
                    )

            video_url = (
                media.get("videoUrl")
                or event.get("mediaStreamPath")
                or event.get("mediaSourcePathMp4")
            )
            if not video_url:
                video_url = media.get("externalVideoUrl") or event.get(
                    "externalMediaUrl"
                )
            video_format = None
            if video_url:
                ext = video_url.rsplit(".", 1)[-1].split("?")[0].lower()
                video_format = ext if ext in ("mp4", "mp3", "m3u8", "wav") else None
            if not video_url:
                video_warnings.append("No playable video found for this event.")

            # Real gap found + fixed 2026-08-16: some customers set
            # externalVideoUrl/externalMediaUrl to a plain YouTube link,
            # but the extension-based video_format check above always
            # left format=None for one (no file extension in a youtube.com
            # URL) -- the frontend needs video_format="youtube" specifically
            # for the iframe+Player-API playback path, so this wasn't just
            # a missing-captions gap, the video may not have played at all.
            # Confirmed live on a real customer (ashlandcowi, event 362):
            # externalVideoUrl was a bare youtube.com/watch?v= link,
            # video_format came back None, segments=0. Delegates to
            # YouTubeAssetFinder for real captions the same way escribe.py/
            # primegov.py/civicweb.py/clerkbase.py already do -- CivicClerk's
            # own captions (fetched below) are still preferred when present,
            # since those are usually curated per-meeting rather than
            # auto-generated.
            youtube_delegated = None
            if video_url:
                yt_video_id = YouTubeAssetFinder.extract_video_id(video_url)
                if yt_video_id:
                    youtube_delegated = await YouTubeAssetFinder.resolve_video_id(
                        yt_video_id, source_url=url
                    )
                    video_url = youtube_delegated.video_url
                    video_format = youtube_delegated.video_format

            # Real order confirmed live (Emporia, KS, event 585):
            # closedCaptionUrl and closedCaptionTracks[0].file point at the
            # same file, so a bare closedCaptionUrl alone is enough when
            # there's no tracks array -- but closedCaptionTracks is the
            # richer source when there's more than one language, so it's
            # preferred when present.
            caption_urls = [
                t["file"]
                for t in (media.get("closedCaptionTracks") or [])
                if t.get("file")
            ]
            if not caption_urls:
                fallback = media.get("closedCaptionUrl") or media.get(
                    "transcriptionUrl"
                )
                if fallback:
                    caption_urls = [fallback]

            if caption_urls:
                candidates = []  # (url, cues, detected_language) -- structured formats only
                text_fallback_candidates = []  # (url, text) -- no real timing available
                unreadable_urls = []
                for caption_url in caption_urls:
                    cues, fallback_text = await self._fetch_captions(
                        session, caption_url
                    )
                    if cues:
                        candidates.append(
                            (
                                caption_url,
                                cues,
                                detect_language_from_texts(c.get("text") for c in cues),
                            )
                        )
                    elif fallback_text:
                        text_fallback_candidates.append((caption_url, fallback_text))
                    elif (
                        caption_url.lower().split("?")[0].rsplit(".", 1)[-1]
                        not in STRUCTURED_CAPTION_PARSERS
                    ):
                        unreadable_urls.append(caption_url)

                target_match = next(
                    (c for c in candidates if c[2] == TARGET_LANGUAGE), None
                )
                chosen = target_match or (candidates[0] if candidates else None)

                if chosen:
                    _url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if lang and lang != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' — "
                            "no matching-language track was found for this meeting."
                        )
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) — treat it as approximate. You can request "
                            "a transcript from the audio instead."
                        )
                    alternate_transcripts = [
                        AlternateTranscript(
                            language=lang,
                            segments=[
                                TranscriptSegment(**cue) for cue in candidate_cues
                            ],
                        )
                        for candidate_url, candidate_cues, lang in candidates
                        if candidate_url != _url
                    ]
                elif text_fallback_candidates:
                    # No structured (timed) transcript available, but real
                    # caption text exists in a format with no parser here
                    # -- see Granicus's resolve() for the same reasoning.
                    # Never verified against a real CivicClerk sample in
                    # this format (only .srt has been observed live); see
                    # BACKLOG.md.
                    _url, fallback_text = text_fallback_candidates[0]
                    segments = [
                        TranscriptSegment(start=0.0, end=0.0, text=line)
                        for line in fallback_text.split("\n")
                        if line.strip()
                    ]
                    transcript_warnings.append(
                        "This meeting has captions, but in a format we can only show "
                        "as plain text, not a clickable per-line transcript."
                    )
                elif unreadable_urls:
                    transcript_warnings.append(
                        "This meeting has a caption file, but in a format we can't "
                        f"read at all yet — you can view it directly: {unreadable_urls[0]}"
                    )
                else:
                    transcript_warnings.append(
                        "A caption file is referenced for this event but couldn't be fetched or parsed."
                    )
            else:
                transcript_warnings.append(
                    "No caption or transcript data found for this event."
                )

            if not segments and youtube_delegated and youtube_delegated.segments:
                segments = youtube_delegated.segments
                transcript_language = youtube_delegated.transcript_language
                transcript_warnings = list(youtube_delegated.transcript_warnings)

        # Agenda is fetched independently of whether a real transcript was
        # found -- useful navigation context either way, not just a
        # fallback. Kept in its own field, never folded into `segments`.
        agenda_items: List[TranscriptSegment] = []
        bookmarks = media.get("eventBookmarks") or []
        if bookmarks:
            sorted_marks = sorted(
                bookmarks, key=lambda b: b.get("markerTimeStart") or 0
            )
            for i, mark in enumerate(sorted_marks):
                start = float(mark.get("markerTimeStart") or 0)
                end = (
                    float(sorted_marks[i + 1].get("markerTimeStart") or start)
                    if i + 1 < len(sorted_marks)
                    else start
                )
                text = mark.get("markerTitle") or mark.get("markerText") or ""
                if text:
                    agenda_items.append(
                        TranscriptSegment(start=start, end=max(end, start), text=text)
                    )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            # Namespaced by host, not just the bare event ID -- CivicClerk
            # is multi-tenant and every customer numbers events from near 1
            # independently, so two different cities routinely share the
            # same event_id. Real bug, confirmed live 2026-08-18: unnamespaced
            # external_id let _find_existing_page() (archive/db/crud.py)
            # match "civicclerk:395" across 3 unrelated cities (Montrose CO /
            # Ashland WI / Liberty MO) and silently overwrite each other's
            # title/date/jurisdiction on one shared row. See BACKLOG.md.
            external_id=f"civicclerk:{parsed.netloc}:{event_id}",
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            agenda_items=agenda_items,
            transcript_language=transcript_language,
            alternate_transcripts=alternate_transcripts,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _county_tenant_jurisdiction(
        subdomain: str, event: dict, location: dict
    ) -> Optional[str]:
        """The county government's own "{Name} County, {ST}" when this
        tenant is demonstrably a county, else None.

        eventLocation is a street address for the meeting VENUE. For a
        county government the venue sits in the county seat, so using
        `location.city` as the jurisdiction files the county's meetings
        under an unrelated city government -- four real production rows
        confirmed live 2026-08-23: St. Croix County WI stored as
        "Hudson, WI", Churchill County NV as "Fallon, NV", Lincoln
        County OR as "Newport, OR", Fulton County IN as "Rochester, IN"
        (each city is exactly that county's seat).

        The county identity is recovered from the venue ZIP via the
        Census ZCTA-county crosswalk, but only when a second,
        independent signal says "this tenant is a county" at all:
        either the subdomain encodes the same county
        (`_COUNTY_SUBDOMAIN_RE` -- the ZIP county and the subdomain
        name must AGREE, see that regex's comment for why neither
        signal is trusted alone), or the meeting's own name is
        anchored county-body phrasing (`_COUNTY_BODY_EVENT_RE`). A
        plain city meeting matches neither and keeps today's behavior
        untouched.
        """
        zip_code = (location.get("zipCode") or "").strip()[:5]
        if not zip_code:
            return None
        zip_county = jurisdiction_enrich.lookup_county_by_zip(zip_code)
        if not zip_county:
            return None
        county_name, county_state = zip_county
        result = f"{county_name}, {county_state}"

        m = _COUNTY_SUBDOMAIN_RE.match(subdomain)
        if m and m.group("st").upper() == county_state:
            county_key = re.sub(
                r"[^a-z]", "", re.sub(r"(?i)\s+county$", "", county_name).lower()
            )
            subdomain_key = re.sub(r"[^a-z]", "", m.group("name"))
            if county_key and county_key == subdomain_key:
                return result

        for field in ("eventName", "categoryName", "agendaName"):
            if _COUNTY_BODY_EVENT_RE.match(event.get(field) or ""):
                return result
        return None

    @staticmethod
    async def _fetch_captions(session: aiohttp.ClientSession, caption_url: str):
        """Returns (cues, fallback_text) via parse_captions_by_extension.
        Real confirmed format so far is .srt (Emporia, KS); .vtt is in the
        schema's shape but has never actually been observed either."""
        try:
            async with session.get(
                caption_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None, None
                raw = await response.read()
        except Exception:
            return None, None
        content = decode_vtt_bytes(raw)
        return parse_captions_by_extension(caption_url, content)

    @staticmethod
    async def _fetch_agenda_text(
        session: aiohttp.ClientSession, event: dict
    ) -> Optional[str]:
        """Best-effort plaintext of this event's real agenda file, when one
        exists -- never raises, returns None on any failure. `publishedFiles`
        entries carry a `GetMeetingFile(fileId=...,plainText=false)` URL by
        default; swapping in `plainText=true` returns a small JSON
        `{"blobUri": ...}` pointing to a SAS-signed Azure blob `.txt`
        (confirmed live on Los Altos Hills, CA, event 4567, fileId 8983) --
        fetched here as a second request, since the blob itself isn't JSON.
        """
        agenda_file = next(
            (
                f
                for f in (event.get("publishedFiles") or [])
                if f.get("type") == "Agenda" and f.get("url")
            ),
            None,
        )
        if not agenda_file:
            return None
        plaintext_url = agenda_file["url"].replace("plainText=false", "plainText=true")
        try:
            async with session.get(
                plaintext_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return None
                blob_info = await resp.json()
            blob_uri = blob_info.get("blobUri")
            if not blob_uri:
                return None
            async with session.get(
                blob_uri, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
        except Exception:
            return None

    @staticmethod
    async def _fetch_json_pair(session: aiohttp.ClientSession, url_a: str, url_b: str):
        async def get(u):
            async with session.get(u, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                resp.raise_for_status()
                return await resp.json()

        import asyncio

        return await asyncio.gather(get(url_a), get(url_b))
