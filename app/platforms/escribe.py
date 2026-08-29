import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .generic_fallback import scan_page_for_video_evidence
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    dedupe_rollup_cues,
    detect_language_from_texts,
    is_likely_garbled,
    parse_vtt,
)

logger = logging.getLogger("rtr_deeplink.escribe")

TARGET_LANGUAGE = "en"
# eScribe/iSiLIVE encodes caption language in the filename itself, unlike
# Granicus's untrustworthy srclang label -- e.g. "{file}.vtt" is English,
# "{file}.fr.vtt" is French. This is the set of suffixes actually observed
# on a real Richmond, CA meeting page (2026-08-06); none were populated for
# that specific meeting (all 404), so the *shape* is confirmed but not the
# content quality.
KNOWN_LANGUAGE_SUFFIXES = [None, "fr", "es", "zh", "zh-hant", "tl"]

_SELECT_ITEM_ID_RE = re.compile(r"SelectItem\((\d+)")
# Non-greedy up to the first "]" is safe here specifically because the
# array's own contents are flat objects (no nested "[") -- confirmed
# against the real Bakersfield sample this was built from.
_BOOKMARKS_ARRAY_RE = re.compile(r"Bookmarks\s*:\s*(\[.*?\])\s*,", re.S)
_SUBDOMAIN_RE = re.compile(r"pub-([a-z0-9-]+)\.escribemeetings\.com")


class EscribeAssetFinder(AssetFinder):
    """Resolves video + transcript for an eScribe meeting page.

    Unlike CivicClerk (one consistent SPA+API) or Swagit (one consistent
    server-rendered template), eScribe is purely an agenda-management
    platform -- video integration is entirely up to each city and varies a
    lot. Confirmed cases in testing (2026-08-06):
      - Richmond, CA: real video hosted on a third video infrastructure,
        iSiLIVE (video.isilive.ca / cdn1.isilive.ca), configured via a
        `<div id="isi_player" data-client_id="..." data-stream_name="...">`
        element embedded directly in the static page HTML -- no headless
        browser needed, just BeautifulSoup.
      - Perry, GA: no video/iSiLIVE integration at all -- just a plain-text
        link to a live Vimeo stream, no archive shown anywhere on the page.
      - A second real iSiLIVE page shape, confirmed live 2026-08-19: eScribe
        also serves standalone `Players/ISIStandAlonePlayer.aspx?Id=<guid>`
        video-only pages (linked from a Meeting.aspx page's "watch video"
        modal, same meeting Id, but a genuinely separate URL/page) whose
        `#isi_player` div carries `data-file_name` instead of
        `data-stream_name` -- confirmed on 5 real live Canadian tenants
        (Caledon, Mississauga, Markham, Victoria, Edmonton). Every Meeting.aspx
        page checked for the same meeting Id still used `data-stream_name` as
        before, so this shape is specific to someone submitting an
        ISIStandAlonePlayer.aspx URL directly, not a hidden variant of the
        regular Meeting.aspx page. `data-file_name`'s value plugs into the
        exact same cdn1.isilive.ca/video.isilive.ca URL construction as
        `data-stream_name` -- confirmed by fetching both a real playlist.m3u8
        and a real, populated .vtt for Caledon's value.
    So "no video found" is an expected, common, non-error outcome for this
    platform, not a bug to chase -- this adapter must degrade gracefully
    rather than assume video is always present the way Granicus/Swagit do.
    """

    platform_name = "escribe"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            title, date, jurisdiction = self._extract_metadata(soup, url, html)
            agenda_items = self._extract_agenda_items(soup, html)

            # Real second page shape confirmed live 2026-08-19: eScribe's own
            # `isi_player.js` (fetched from //video.isilive.ca/cdn/isi_player.js)
            # treats `data-file_name` as a "legacy" synonym for `stream_name`
            # ("legacy support for file_name / stream_name" -- `if
            # typeof(file_name) != 'undefined') { stream_name = file_name }`),
            # used on a genuinely different real page:
            # `Players/ISIStandAlonePlayer.aspx?Id=<guid>`, a standalone
            # video-only page eScribe's own Meeting.aspx page links to (a
            # "watch video" modal, same meeting Id) rather than embedding
            # directly. Confirmed on 5 real live tenants (Caledon, Mississauga,
            # Markham, Victoria, Edmonton): each one's own Meeting.aspx page
            # embeds `data-stream_name` (the shape already handled below), but
            # the linked ISIStandAlonePlayer.aspx page for that exact same
            # meeting Id embeds `data-file_name` instead with the identical
            # value eScribe's own JS would have used for `stream_name` --
            # confirmed by fetching both cdn1.isilive.ca's playlist.m3u8 (200)
            # and video.isilive.ca's .vtt (200, real populated captions) for
            # Caledon's data-file_name value using the exact same URL
            # construction as the data-stream_name path below. So a URL
            # someone submits that happens to *be* an ISIStandAlonePlayer.aspx
            # page (e.g. a "share video" link, distinct from the Meeting.aspx
            # URLs this adapter is normally given) needs the same attribute
            # accepted, not a different construction.
            player = soup.select_one(
                "#isi_player[data-client_id][data-stream_name]"
            ) or soup.select_one("#isi_player[data-client_id][data-file_name]")
            video_url, video_format = None, None
            video_link: Optional[str] = None
            video_link_recognized = False
            best_effort = False
            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None

            if not player:
                # Opt-in backstop (2026-08-14 rebuild, first adapter wired
                # in): eScribe's own docstring documents "no video
                # integration" as a common, real outcome here, and its
                # pages are per-meeting (no other meetings' videos on the
                # page -- low wrong-video risk, unlike e.g. Cablecast's
                # related-shows carousel). Perry, GA is the confirmed real
                # beneficiary shape: its only video is a plain Vimeo
                # live-stream link, exactly what the pointer tier
                # surfaces. A backstop hit is best-effort by definition --
                # it came from a generic scan, not eScribe's own
                # structure -- so the result is flagged accordingly.
                scanned_url, scanned_format, scanned_link, scanned_recognized = (
                    scan_page_for_video_evidence(html, url)
                )
                if scanned_format == "youtube":
                    # Real gap found + fixed 2026-08-16: scan_page_for_video_evidence()
                    # deliberately returns just the embed URL for a YouTube hit (see
                    # its own docstring -- "an opting-in adapter already has its own
                    # better metadata"), never fetching captions itself. Every other
                    # caller that reaches this tier (generic_fallback.py's own
                    # resolve, primegov.py, civicweb.py, clerkbase.py) follows up
                    # with a real YouTubeAssetFinder.resolve_video_id() call for
                    # captions -- this adapter never did, so real, confirmed
                    # YouTube-embedded meetings sat with segments=[] even though a
                    # caption fetch (this app's own residential-IP advantage over
                    # Render's blocked cloud IP) could reach them. video_id is
                    # always the last path segment of the embed URL returned above.
                    video_id = scanned_url.rsplit("/", 1)[-1]
                    yt_resolved = await YouTubeAssetFinder.resolve_video_id(
                        video_id, source_url=url
                    )
                    video_url, video_format = (
                        yt_resolved.video_url,
                        yt_resolved.video_format,
                    )
                    segments = yt_resolved.segments
                    transcript_language = yt_resolved.transcript_language
                    transcript_warnings.extend(yt_resolved.transcript_warnings)
                    video_warnings.extend(yt_resolved.video_warnings)
                    best_effort = True
                    video_warnings.append(
                        "This city's eScribe setup has no recognized video integration, "
                        "but a general scan of the page found what looks like the "
                        "video -- treat it as best-effort, not confirmed."
                    )
                    # Prefer eScribe's own page metadata over YouTube's channel/video
                    # title -- same reasoning as primegov.py's identical override.
                    title = title or yt_resolved.title
                    date = date or yt_resolved.date
                elif scanned_url or scanned_link:
                    video_url, video_format = scanned_url, scanned_format
                    video_link, video_link_recognized = scanned_link, scanned_recognized
                    best_effort = True
                    video_warnings.append(
                        "This city's eScribe setup has no recognized video integration, "
                        "but a general scan of the page found what looks like the "
                        "video -- treat it as best-effort, not confirmed."
                    )
                else:
                    video_warnings.append(
                        "No video integration found on this page -- this city's eScribe "
                        "setup may only offer a live stream (e.g. Vimeo) with no archive, "
                        "or use a video platform this adapter doesn't recognize yet."
                    )
            else:
                client_id = player["data-client_id"]
                # data-file_name is the ISIStandAlonePlayer.aspx variant --
                # see the comment above where `player` is selected.
                stream_name = player.get("data-stream_name") or player["data-file_name"]
                encoded_stream = quote(stream_name, safe="")
                video_url = f"https://cdn1.isilive.ca/vod/_definst_/mp4:{client_id}/{encoded_stream}/playlist.m3u8"
                video_format = "m3u8"

                candidates = []
                for suffix in KNOWN_LANGUAGE_SUFFIXES:
                    vtt_url = (
                        f"https://video.isilive.ca/{client_id}/{encoded_stream}"
                        + (f".{suffix}" if suffix else "")
                        + ".vtt"
                    )
                    cues = await self._fetch_vtt(session, vtt_url)
                    if cues:
                        candidates.append(
                            (vtt_url, cues, self._detect_cue_language(cues))
                        )

                target_match = next(
                    (c for c in candidates if c[2] == TARGET_LANGUAGE), None
                )
                chosen = target_match or (candidates[0] if candidates else None)

                if chosen:
                    _vtt_url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if lang and lang != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' -- "
                            "no matching-language track was found for this meeting."
                        )
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) -- treat it as approximate. You can request "
                            "a transcript from the audio instead."
                        )
                else:
                    transcript_warnings.append(
                        "This meeting has video but no caption file was found in any "
                        "known language -- captioning doesn't appear to have been "
                        "generated for it yet."
                    )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            video_link=video_link,
            video_link_recognized=video_link_recognized,
            segments=segments,
            agenda_items=agenda_items,
            transcript_language=transcript_language,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
            best_effort=best_effort,
        )

    @staticmethod
    async def _fetch_vtt(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(
                vtt_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "eScribe VTT fetch got HTTP %s for %s",
                        response.status,
                        vtt_url,
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning("eScribe VTT fetch failed for %s", vtt_url, exc_info=True)
            return None
        content = decode_vtt_bytes(raw)
        # eScribe is one of the three platforms BACKLOG.md named as serving
        # roll-up ("scrolling ticker") captions with no dedupe wired in
        # (WO-34) -- unlike Granicus/CivicClerk it parses VTT directly
        # instead of going through parse_captions_by_extension(), so it
        # needs the call here. No-ops on a non-roll-up track, which is what
        # every eScribe fixture in tests/fixtures/escribe/ actually is.
        cues = dedupe_rollup_cues(parse_vtt(content))
        return cues or None

    @staticmethod
    def _detect_cue_language(cues) -> Optional[str]:
        # Was a private copy of detect_language_from_texts() carrying the
        # same head-only `[:2000]` sampling bug (WO-34); now just the shared
        # implementation, which votes across the whole transcript.
        return detect_language_from_texts(c.get("text") for c in cues)

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup, url: str, html: str):
        raw_title = soup.title.get_text(strip=True) if soup.title else ""
        title, date = raw_title or None, None
        if " - " in raw_title:
            title_part, date_part = raw_title.rsplit(" - ", 1)
            title = title_part.strip() or title
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    date = datetime.strptime(date_part.strip(), fmt).strftime(
                        "%Y-%m-%d"
                    )
                    break
                except ValueError:
                    continue

        page_text = soup.get_text(" ", strip=True)
        # Real bug fixed 2026-08-16 (WO-14, BACKLOG.md): this used to be a
        # bare `re.search(r"City of ([A-Za-z .]+)", page_text)` -- the exact
        # same open-ended, unbounded character class as Granicus's version
        # (written independently, not shared code), confirmed live on 6 real
        # customers including Gainesville ("Gainesville General Policy
        # Committee Meeting AGENDA Thursday, FL") and 4 Canadian examples
        # where the regex ran on past the city name into land-acknowledgment
        # boilerplate. extract_jurisdiction_chain() is the same bounded
        # stop-rule/capitalization-walk chain already shipped for
        # swagit/civicclerk/generic_fallback -- fixing both adapters' copies
        # of this bug with one shared, Census-validated helper instead of
        # patching each site independently.
        jurisdiction = jurisdiction_enrich.extract_jurisdiction_chain(
            page_text=page_text, html=html, url=url
        )
        if not jurisdiction:
            # Real gap fixed 2026-08-08: the "City of X" phrasing above
            # isn't universal -- Bakersfield, CA's page just has a plain
            # address ("...Bakersfield, CA 93301"), no "City of" anywhere,
            # so jurisdiction silently came back None. Every eScribe page
            # does reliably carry its city in the subdomain
            # (`pub-{city}.escribemeetings.com`), a real signal independent
            # of body wording.
            jurisdiction = EscribeAssetFinder._jurisdiction_from_subdomain(url)

        # Neither source above ever includes a state -- see BACKLOG.md's
        # "no-state jurisdiction audit". Bakersfield's own page text is a
        # real example of exactly the address shape the ZIP fallback is
        # built for ("...Bakersfield, CA 93301").
        jurisdiction = jurisdiction_enrich.enrich_jurisdiction_text(
            jurisdiction, netloc=urlparse(url).netloc, page_text=page_text
        )

        return title, date, jurisdiction

    @staticmethod
    def _jurisdiction_from_subdomain(url: str) -> Optional[str]:
        match = _SUBDOMAIN_RE.match(urlparse(url).netloc.lower())
        if not match:
            return None
        label = match.group(1).replace("-", "")
        # Real bug fixed 2026-08-16 (WO-14, BACKLOG.md): this used to be a
        # bare `.replace("-", " ").title()`, which only helps a subdomain
        # with literal hyphens -- every real customer confirmed live is one
        # concatenated word ("cityofgainesville", "thunderbay", "portmoody"),
        # so a multi-word city collapsed into one mashed-together word
        # ("Thunderbay", "Portmoody" instead of "Thunder Bay"/"Port Moody").
        # wordninja-split the same way Granicus's _humanize_subdomain() does.
        #
        # Was deliberately NOT gated on Census-table validation at first --
        # eScribe serves real Canadian customers the then-US-only Census
        # tables couldn't validate by construction. That reasoning went
        # stale the very next day: PR #158 (2026-08-17) added 5,028 real
        # StatsCan places to the same table `validated_label_extract()`
        # checks against. Left ungated, this produced a real, confirmed-live
        # bug of its own (2026-08-18): re-resolving "townofbonnyville" with
        # this function's own wordninja split gives "Bonny Ville" -- a
        # different, confidently WRONG string, not the almost-right
        # "Townofbonnyville" it started from. Now delegates to the same
        # gated, validated logic Granicus's `_humanize_subdomain()` already
        # uses (`jurisdiction_enrich.validated_label_extract()`), rather
        # than reimplementing wordninja-split-and-guess locally -- declining
        # (returning None) on a subdomain that doesn't validate rather than
        # asserting a wrong name. Known, honestly-flagged residual gap: a
        # handful of real Ontario "regional municipality" names (Durham
        # Region, Peel Region, Region of Waterloo) and hyphenated municipal
        # names (Chatham-Kent, Arran-Elderslie) aren't in the StatsCan table
        # under this exact form, so they now decline instead of returning
        # their previous (accurate but unvalidated) guess -- see BACKLOG.md.
        return jurisdiction_enrich.validated_label_extract(label)

    @staticmethod
    def _extract_agenda_items(
        soup: BeautifulSoup, html: str
    ) -> List[TranscriptSegment]:
        """Real per-item video timestamps, when present, come from a
        `video.Bookmarks` JS array embedded in the page (confirmed live on
        a real Bakersfield, CA meeting) -- entries shaped like
        `{"AgendaItemId": N, "TimeStart": milliseconds, "TimeEnd":
        milliseconds}`, keyed by the same numeric id each `.AgendaItem`
        div's title link passes to `SelectItem(N)`.

        Not every agenda item gets a bookmark -- confirmed live: only 4 of
        10 real items did, apparently only substantive/voted-on items, not
        procedural ones like "ROLL CALL". Rather than fabricate a start
        time for items with none, which would both be a real, unverified
        claim and risk several items sharing an identical made-up
        timestamp (tripping the frontend's "unreliable timestamps"
        all-identical heuristic and losing clickability for the items that
        *do* have a real one), items without a real bookmark are simply
        omitted rather than included with a guessed time.
        """
        bookmarks_match = _BOOKMARKS_ARRAY_RE.search(html)
        if not bookmarks_match:
            return []
        try:
            bookmarks = json.loads(bookmarks_match.group(1))
        except json.JSONDecodeError:
            return []

        # Earliest bookmark per agenda item id -- an item can have more
        # than one discrete video segment (confirmed: item 3 in the real
        # sample had two, presumably discussed then revisited later); use
        # the first/earliest as "when this item starts".
        earliest_by_id: Dict[int, dict] = {}
        for b in bookmarks:
            item_id = b.get("AgendaItemId")
            time_start = b.get("TimeStart")
            time_end = b.get("TimeEnd")
            if item_id is None or time_start is None or time_end is None:
                continue
            if (
                item_id not in earliest_by_id
                or time_start < earliest_by_id[item_id]["TimeStart"]
            ):
                earliest_by_id[item_id] = b

        items: List[TranscriptSegment] = []
        for div in soup.select(".AgendaItem"):
            title_link = div.select_one(".AgendaItemTitle a")
            if not title_link:
                continue
            id_match = _SELECT_ITEM_ID_RE.search(title_link.get("href") or "")
            if not id_match:
                continue
            bookmark = earliest_by_id.get(int(id_match.group(1)))
            if not bookmark:
                continue
            text = title_link.get_text(strip=True)
            if not text:
                continue
            items.append(
                TranscriptSegment(
                    start=bookmark["TimeStart"] / 1000,
                    end=bookmark["TimeEnd"] / 1000,
                    text=text,
                )
            )
        return items
