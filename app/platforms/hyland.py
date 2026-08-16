import html as html_module
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from .base import AssetFinder
from .media_scan import is_hls_url, media_type, scan_media_urls
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich

# Hyland "OnBase Agenda Online" -- confirmed 2026-08-16 across 5 real
# customers on 5 different hosting domains, spanning TWO distinct real
# versions of the same underlying vendor product (found by testing extra
# real URLs the user found via a plain Google search, not enumeration --
# domain/CDX enumeration alone would never have surfaced the version
# split, since it only shows up once you actually resolve a page).
#
# **Version A** (the "accessible" outline UI) -- tucsonaz.hylandcloud.com
# (Tucson, AZ), mccobagenda.databankcloud.com (Maricopa County, AZ),
# agendanet.saccounty.gov (Sacramento County, CA). All confirmed via plain
# `curl` -- no headless browser needed, overturning BACKLOG.md's earlier
# "Tucson genuinely renders client-side" conclusion (that investigation's
# AJAX probe used the literal `type=AGENDATYPEVALUE` placeholder left in
# the page's own JS template rather than substituting the real doctype).
# Real structure:
# - The main `/Meetings/ViewMeeting?id={id}&doctype={doctype}` page has no
#   static title/date/jurisdiction text at all (Maricopa/Tucson) or only a
#   generic sitewide one (Sacramento's <title>), but does carry two things
#   a plain fetch can use: (1) a JW Player `file:` config with a real
#   CloudFront HLS URL (Maricopa/Sacramento only -- Tucson never has video,
#   confirmed across 2 independent meeting ids), and (2) inline
#   `itemEventPoints`/`sectionEventPoints` JS objects mapping numeric
#   agenda-item ids to a real video-seek offset in seconds.
# - A separate `/Meetings/ViewMeetingAgenda?meetingId={id}&type={doctype}`
#   endpoint (same `{id}`/`{doctype}` from the URL, substituted directly)
#   is plain server-rendered HTML with NO JS execution needed: a real
#   `<h1>{meeting name}<br>{date time}<br></h1>` header, plus a full nested
#   outline of `accessible-item`/`accessible-section` divs, each item
#   carrying its own real text and a `loadAgendaItem({id}); return
#   false;"` onclick whose `{id}` is the same id used as a key in
#   `itemEventPoints` -- the two pages join on that id to produce a real,
#   timestamped agenda outline with no headless browser involved.
#
# **Version B** (a converted-Word-document UI, confirmed on a real,
# distinctly newer-looking template) -- docs.santabarbaraca.gov (Santa
# Barbara, CA, no video) and stream2.ci.concord.ca.us (Concord, CA, real
# video). Version A's `/Meetings/ViewMeetingAgenda` endpoint 302-redirects
# to a generic `/Error/NotFound` page for these customers -- their own
# `loadAgendaDocument()` JS never references that path at all, only
# `/Documents/ViewAgenda?meetingId={id}&type={agenda|minutes|summary}&
# doctype={doctype}` (the `type` word, not a raw doctype number, mapped
# from the real `doctype` value via the JS's own `if (doctype==2)
# type='minutes'; else if (doctype==3) type='summary';` -- confirmed
# identical in both customers' own page source). That endpoint's response
# is a real Aspose.Words-converted HTML render of the agenda document
# (base64-embedded images, inline Word styling) -- genuinely different
# markup from Version A, but it still embeds the SAME real
# `loadAgendaItem({id},{isSection})` links per outline item, joinable
# against the same `itemEventPoints` mechanism. Real item text can span
# multiple sibling `<span>` tags within one `<a>` (confirmed on Concord --
# extracting only the first span truncates real content, e.g. "Considering"
# instead of the full "Considering – a presentation by..."), so this
# version's extraction captures the whole anchor and strips inner tags
# rather than anchoring on one span the way Version A's does. Neither
# customer's main ViewMeeting page carries an `<h1>` shape like Version
# A's AJAX page -- but *does* carry a real, per-meeting `<title>{meeting
# name} - {date time} - OnBase Agenda Online</title>`, used as this
# version's title/date source instead.
#
# Common to all 5 samples: no caption/transcript track of any kind was
# found on any JW Player config (no `tracks:` key at all, unlike TelVue)
# -- this platform is video(+agenda)-only until a real example says
# otherwise. Jurisdiction: none has reliable in-page jurisdiction text
# (Sacramento's <title> is the closest, one unconfirmed-to-generalize
# example) -- same reasoning as this file's LIMS/lookup_by_domain()
# precedent, so every known domain is registered in
# jurisdiction_enrich._KNOWN_DOMAINS rather than extracted from text.
#
# Which version a given customer runs isn't detectable from the URL alone
# -- `resolve()` always tries Version A's endpoint first (cheap, and the
# large majority of confirmed customers so far) and falls back to Version
# B only when that yields no title, confirmed safe since Version A pages
# never redirect to /Error/NotFound (a Version-B-only failure mode).

TARGET_LANGUAGE = "en"

_MEETINGS_PATH_RE = re.compile(r"^(.*/)Meetings/ViewMeeting$", re.IGNORECASE)
_DATE_RE_TEXT = r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M"
# Version A: the ViewMeetingAgenda AJAX page's own <h1> header.
_TITLE_DATE_RE = re.compile(
    rf"<h1[^>]*>\s*([^<]+?)\s*<br\s*/?>\s*({_DATE_RE_TEXT})\s*<br",
    re.IGNORECASE,
)
# Version B: no equivalent <h1> on the agenda document itself -- title/date
# instead come from the main ViewMeeting page's own <title> tag.
_TITLE_DATE_MAIN_RE = re.compile(
    rf"<title>\s*(.+?)\s*-\s*({_DATE_RE_TEXT})\s*-\s*OnBase Agenda Online\s*</title>",
    re.IGNORECASE,
)
# Version A: item text sits in one specific <span class="accessible-item-text">.
_AGENDA_ITEM_RE = re.compile(
    r'loadAgendaItem\((\d+)\);\s*return false;"[\s\S]*?'
    r'accessible-item-text">([^<]*)</span>',
    re.IGNORECASE,
)
# Version B: item text can span multiple sibling <span> tags inside the
# same <a> -- captured whole, inner tags stripped separately (see
# _clean_item_text()) rather than anchored on one span.
_AGENDA_ITEM_NEW_RE = re.compile(
    r'loadAgendaItem\((\d+)[^)]*\)[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_INNER_TAG_RE = re.compile(r"<[^>]+>")
_EVENT_POINTS_RE = re.compile(r"var\s+itemEventPoints\s*=\s*\{([^}]*)\}", re.IGNORECASE)
_EVENT_POINT_ENTRY_RE = re.compile(r"(\d+)\s*:\s*(\d+(?:\.\d+)?)")
# Version B's doctype->type-word mapping, confirmed identical in both known
# customers' own loadAgendaDocument() JS source.
_DOCTYPE_WORDS = {"2": "minutes", "3": "summary"}


class HylandAssetFinder(AssetFinder):
    """Resolves video + agenda outline for a Hyland "OnBase Agenda Online"
    meeting page (see module docstring above for the real page structure
    this was built against)."""

    platform_name = "hyland"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        meeting_id = self._param(params, "id")
        doctype = self._param(params, "doctype")

        path_match = _MEETINGS_PATH_RE.match(parsed.path)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        async with aiohttp.ClientSession(headers=self.headers) as session:
            html = await self._fetch(session, url)
            if html is None:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=["Could not load this Hyland Agenda Online page."],
                )

            video_url, video_format = self._find_video(html, url)
            event_points = self._parse_event_points(html)

            title, date, agenda_items, agenda_link = None, None, [], None
            if meeting_id and doctype and path_match:
                prefix = path_match.group(1)

                # Version A first -- the more common of the two confirmed
                # shapes, and safe to try unconditionally: Version B
                # customers 302-redirect this path to a generic error page
                # that never matches _TITLE_DATE_RE, so this can't
                # misfire into wrong content for them.
                agenda_url_a = f"{origin}{prefix}Meetings/ViewMeetingAgenda?meetingId={meeting_id}&type={doctype}"
                agenda_html_a = await self._fetch(session, agenda_url_a)
                title, date = self._extract_title_date(agenda_html_a)

                if title:
                    agenda_items = self._build_agenda_items(agenda_html_a, event_points, _AGENDA_ITEM_RE)
                    agenda_link = agenda_url_a
                else:
                    type_word = _DOCTYPE_WORDS.get(doctype, "agenda")
                    agenda_url_b = (
                        f"{origin}{prefix}Documents/ViewAgenda"
                        f"?meetingId={meeting_id}&type={type_word}&doctype={doctype}"
                    )
                    agenda_html_b = await self._fetch(session, agenda_url_b)
                    title, date = self._extract_title_date_from_main(html)
                    agenda_items = self._build_agenda_items(agenda_html_b, event_points, _AGENDA_ITEM_NEW_RE)
                    agenda_link = agenda_url_b

        if agenda_items:
            agenda_link = None

        jurisdiction: Optional[str] = None
        known = jurisdiction_enrich.lookup_by_domain(parsed.netloc)
        if known:
            jurisdiction = f"{known.name} County, {known.state}" if known.type == "county" else f"{known.name}, {known.state}"

        if not video_url:
            video_warnings.append("No video found on this page.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=f"hyland:{parsed.netloc}:{meeting_id}" if meeting_id else None,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            agenda_items=agenda_items,
            agenda_link=agenda_link,
            video_warnings=video_warnings,
        )

    @staticmethod
    def _param(params: dict, key: str) -> Optional[str]:
        for candidate_key, values in params.items():
            if candidate_key.lower() == key and values:
                return values[0]
        return None

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    return None
                return await response.text()
        except Exception:
            return None

    @staticmethod
    def _find_video(html: str, page_url: str):
        for candidate in scan_media_urls(html, page_url):
            if media_type(candidate) == "video":
                return candidate, ("m3u8" if is_hls_url(candidate) else "mp4")
        return None, None

    @staticmethod
    def _extract_title_date(html: Optional[str]):
        if not html:
            return None, None
        match = _TITLE_DATE_RE.search(html)
        if not match:
            return None, None
        return html_module.unescape(match.group(1).strip()) or None, HylandAssetFinder._parse_date(match.group(2))

    @staticmethod
    def _extract_title_date_from_main(html: Optional[str]):
        """Version B fallback -- no <h1> equivalent to _TITLE_DATE_RE exists
        on the agenda document itself, but the main ViewMeeting page's own
        <title> carries real "{name} - {date} - OnBase Agenda Online" text."""
        if not html:
            return None, None
        match = _TITLE_DATE_MAIN_RE.search(html)
        if not match:
            return None, None
        return html_module.unescape(match.group(1).strip()) or None, HylandAssetFinder._parse_date(match.group(2))

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        try:
            return datetime.strptime(text.strip(), "%m/%d/%Y %I:%M:%S %p").strftime("%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _parse_event_points(html: str) -> dict:
        match = _EVENT_POINTS_RE.search(html)
        if not match:
            return {}
        return {
            item_id: float(seconds)
            for item_id, seconds in _EVENT_POINT_ENTRY_RE.findall(match.group(1))
        }

    @staticmethod
    def _clean_item_text(raw: str) -> str:
        # A no-op for Version A's regex (already a single plain-text span),
        # and strips Version B's real multi-<span> markup down to plain
        # text -- one shared cleaner works for both since Version A's
        # captured text never contains a tag to strip.
        return " ".join(html_module.unescape(_INNER_TAG_RE.sub(" ", raw)).split())

    @staticmethod
    def _build_agenda_items(
        agenda_html: Optional[str], event_points: dict, item_re: re.Pattern
    ) -> List[TranscriptSegment]:
        if not agenda_html or not event_points:
            return []
        items = []
        for item_id, raw_text in item_re.findall(agenda_html):
            start = event_points.get(item_id)
            text = HylandAssetFinder._clean_item_text(raw_text)
            if start is None or not text:
                continue
            items.append((start, text))
        if not items:
            return []
        items.sort(key=lambda pair: pair[0])
        agenda_items: List[TranscriptSegment] = []
        for i, (start, text) in enumerate(items):
            end = items[i + 1][0] if i + 1 < len(items) else start
            agenda_items.append(TranscriptSegment(start=start, end=max(end, start), text=text))
        return agenda_items
