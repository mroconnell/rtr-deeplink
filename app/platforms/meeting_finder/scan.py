"""Meeting Finder's Scan phase (WO-1029).

docs/MEETING_FINDER.md's Scan section: find media links and meeting-page
links on a page already in hand (a `fetch.py` `FetchResult`). Two kinds of
find:

- **Media candidates** -- something playable/downloadable right here:
  direct `.mp4`/`.m3u8` (via `app/platforms/media_scan.py`'s existing
  regex scanner, already shared by several adapters), Vimeo, Google
  Drive and CivicWeb links (via `app/platforms/base.py`'s
  `detect_platform()` and `app/platforms/direct_file.py`'s
  `is_direct_file_url()` -- both already cover exactly these shapes, so
  this module calls them rather than re-deriving Vimeo/Drive/CivicWeb URL
  patterns a third time). YouTube is never a media candidate here -- it
  becomes a `youtube_leads` entry instead (docs/MEETING_FINDER.md: "Any
  other YouTube link: saved as a drip lead, never the answer"; Resolve
  never fetches YouTube either).
- **Meeting-page links** -- a dated agenda/meeting-detail page
  (`?EID=123`, `/event/123/`, `/meetings/2026-09-08-council`, a Municode-
  style `/page/town-council-meeting-278`) worth opening one hop further,
  because a real embedded player is often only visible one click down
  (confirmed on `bristol-ri.municodemeetings.com`'s own homepage table --
  see `tests/fixtures/municode_meetings/README.md`: most rows' own
  "Video" column is empty on the homepage, but their "View Details" link
  leads to a page with a real `#mcc_agenda_video` iframe).

Detection follows rtr-upcoming's `UPCOMING_AGENDAS_FIELD_GUIDE.md`
("Detection: three rules, in this order" plus "The guard that matters
more than the rules"), read in full for this WO:

1. **Link text** -- a real date, or a meeting/agenda/video word.
2. **Column header** -- when the link sits in a table cell, that cell's
   own `data-th` attribute (Municode's shape) or its column's `<th>`
   text (the general shape) names what the link is, even when the link's
   own text/href says nothing (Municode's "View Details" carries neither
   a date nor a meeting word by itself).
3. **Href shape** -- `?EID=`/`?eventId=`/`/event/N/`, `/meetings?/`
   with a date or slug, or a named meeting-detail path.

Dates come from the link text first, else from the same table row (a
sibling cell whose own header says "date"), else by walking UP through
ancestor headings -- skipping a heading that is bare year text
("2026") on its own, per the field guide's own instruction, since that
heading names a section, not a specific meeting.

**The minutes/subscribe/calendar guard applies to every one of the three
rules, not just the ones where it looks necessary** -- the field guide's
own "guard that matters more than the rules" section: a link whose text
or href says "minutes"/"subscribe"/"calendar" is a document or a feed,
not a meeting-detail page to open, even when it also matches a href-shape
or column-header rule. A page whose own `<title>`/`<h1>` says something
like "City Council Agendas" additionally makes a bare, date-only link a
meeting link on its own (the field guide's page-level rule) -- but the
minutes guard still applies on top of that.

Test/demo-tenant titles ("TEST - CC - Livemeeting demo", "DO NOT USE -
...") are dropped using the exact same markers `pick.py` already uses for
Resolve's own picking rule (`pick._is_test_or_demo_title`) -- imported
directly rather than duplicated, so the two only ever need updating in
one place.

A page fetched from Wayback (`FetchResult.links_only=True`) may still
yield real meeting-page links (they're just anchor text/hrefs on an old
snapshot), but never media candidates -- `fetch.py`'s own docstring says
why: a Wayback capture is for finding links, never treated as a source of
the government's own media.

## WO-1033: three real false-positive shapes, found against real pages

Real, live-observed on Dublin CA's and Emporia KS's own homepages
(`tests/fixtures/wo1033_hop_scan/`): a news item, an email-signup page,
and an ordinary community calendar event (no meeting/body words in its
own title) were each being treated as a meeting page worth opening.

1. **News items (`CivicAlerts.aspx`)** are never a meeting page, no
   matter what their own headline says -- a real false positive this
   fixes: a CivicAlerts headline like "City Council Responds to Special
   Election Call" scores as meeting-shaped on link text alone (real
   council/commission words), but the page itself is a press release,
   not a meeting.
2. **Email-signup/subscription pages** (GovDelivery's own
   `.../subscribers/...` URL, a `/list.aspx` subscribe page, or a link
   whose own text says "Stay Informed"/"Notify Me") are a feed sign-up,
   not a meeting page.
3. **A calendar-event permalink** (`/calendar/event/detail/<n>`,
   `Calendar.aspx?EID=<n>`) is only a real meeting page when its own
   title names a governing body or a meeting -- reusing
   `app.platforms.granicus.GOVERNING_BODY_KEYWORDS` (council, commission,
   board, committee, hearing) plus "meeting" itself, the same vocabulary
   `pick.py`'s own title filters already lean on elsewhere. Without this,
   an ordinary town calendar event ("Night Market", "Senior Info Fair")
   qualifies just because it carries a date, the same way a real meeting
   entry does -- a bare date is not by itself evidence of a *meeting*. A
   meeting-worded href shape that ISN'T a bare calendar permalink
   (`/meetings/2026-09-08-council`, a Municode `/page/...-meeting-278`)
   is unaffected -- this gate only applies to the generic calendar/event
   permalink shape, which carries no meeting-specific vocabulary of its
   own.

**Item 4 (same WO): a same-site YouTube redirect is a YouTube lead.**
CivicPlus's own quick-link widget (real Emporia KS example:
`<a href="/youtube" aria-label="YouTube"><img alt="YouTube" ...></a>`,
no visible anchor text at all) redirects to the government's YouTube
channel via a path on the GOVERNMENT'S OWN site, not a `youtube.com`
URL -- `youtube_ids.extract_video_id()` never recognizes it, so it used
to vanish silently instead of becoming a lead. `_youtube_leads()` now
also recognizes this same-site-redirect shape (the same pattern
`hop.py`'s own `_SAME_SITE_SOCIAL_REDIRECT_RE` uses, re-declared here
rather than imported -- this module doesn't otherwise depend on
`hop.py`, and the pattern is a two-line regex) and reports it as a lead
with `video_id=None`; it is never followed or fetched, same as every
other YouTube lead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.platforms import host_recognition
from app.platforms.base import detect_platform
from app.platforms.direct_file import is_direct_file_url
from app.platforms.granicus import GOVERNING_BODY_KEYWORDS
from app.platforms.media_scan import media_type, scan_media_urls
from app.platforms.youtube_ids import extract_video_id

from .fetch import FetchResult, Fetcher
from .models import Candidate
from .pick import _is_test_or_demo_title, parse_candidate_date

# Extensions that are a document/download, never a page worth opening for
# embedded video -- excluded from meeting-page-link candidates outright
# (opening a PDF through the Fetcher wastes one of `max_meeting_pages`'
# budget on something that can never itself embed a player). Deliberately
# NOT the full `media_scan.CAPTION_EXTENSIONS` list -- those are handled
# as media candidates, not meeting pages, by `scan_media_urls()` already.
_DOCUMENT_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
)

# Known document-serving path shapes that carry no file extension at all
# (rtr-upcoming field guide's own rule-3 href list, minus the plain
# extensions already covered above) -- "sniff content type, not the URL,
# for documents" in practice means these paths are DOCUMENT endpoints by
# how the vendor serves them, confirmed live (Jackson County AL's real
# `AgendaCenter/ViewFile/Agenda/_09142026-286` serves a PDF with no
# `.pdf` in its URL at all, WO-1029), not a guess from the URL's own
# shape. A real HEAD-based content-type check per candidate would be
# more precise but costs a fetch per link before Scan even knows which
# ones matter -- this fixed list is the same trade the field guide's own
# rule 3 already makes.
_DOCUMENT_HREF_RE = re.compile(
    r"viewfile|documentcenter|fileopen\.aspx|showpublisheddocument|/document/\d+",
    re.IGNORECASE,
)

# rtr-upcoming field guide's "Href shape" rule (adapted: Scan wants a
# meeting *page* to open, not an agenda *document* -- a bare `.pdf` is
# excluded above instead of matched here). Same `?EID=`/`/event/N/` shape
# `scripts/wo147_access_ladder_sweep.py`'s `find_calendar_entry_links()`
# already uses for its own, narrower "one more hop into a calendar's
# first N dated entries" job -- Scan's version is broader (any position on
# the page, not just the first `limit`) so it isn't imported from there.
_MEETING_PAGE_HREF_RE = re.compile(
    r"[?&](?:eid|eventid|id)=\d+"
    r"|/event/\d+/?"
    r"|/events/\d+/?"
    r"|/meetings?/\d{4}-\d{1,2}-\d{1,2}"
    r"|/meetings?/[a-z0-9]+-\d{4}-\d{1,2}-\d{1,2}"
    r"|/page/[a-z0-9-]*meeting[a-z0-9-]*-\d+",
    re.IGNORECASE,
)

# Link text/href words that, by themselves, say "this is a meeting-shaped
# page" (rule 1). Deliberately excludes "minutes"/"calendar"/"subscribe"
# -- those are handled by `_MINUTES_GUARD_RE` below, applied to every
# rule, not folded in here.
_MEETING_TEXT_RE = re.compile(
    r"\bagenda\b|\bmeeting\b|\bvideo\b|\bwatch\b|\bview\s+details?\b|\bcouncil\b"
    r"|\bcommission\b|\bboard\b|\bhearing\b",
    re.IGNORECASE,
)

# A column whose header names a DOCUMENT (agenda, packet, minutes) --
# real Municode/CivicPlus shape, e.g. Municode's own "Agenda"/"Agenda
# Packet" columns hold icon-only links straight to a PDF/HTML document,
# never a meeting-detail page with an embedded player. Checked before
# rule 2's own header-word list so an icon-only agenda-document link
# (empty anchor text, so rule 1 never fires on it) isn't mistaken for a
# meeting page just because "agenda" also appears in a column label --
# excluded outright, the same way `_DOCUMENT_EXTENSIONS` excludes a bare
# `.pdf` by its own extension.
_DOCUMENT_COLUMN_RE = re.compile(r"agenda|packet|minutes|document", re.IGNORECASE)

# Pagination/login chrome that can otherwise pick up a stray nearby date
# from an unrelated ancestor during the "walk up" fallback (confirmed on
# `bristol_home.html`'s own "View Additional Meetings" pager link, whose
# nearest heading-shaped ancestor text is actually the results table
# above it).
_PAGINATION_TEXT_RE = re.compile(
    r"\bview\s+additional\b|\bshow\s+more\b|\bnext\s+page\b|\blogin\b", re.IGNORECASE
)

# The field guide's own guard, applied to every rule below: a link whose
# text says minutes/subscribe/calendar is a document or a feed, never a
# meeting-detail page to open. Word-boundary, not substring (a real
# "Administrative" title shouldn't be caught by an unrelated substring,
# the same reasoning `pick.py`'s own `_is_minutes_link()` already
# documents for its narrower single-word check).
#
# TEXT only, deliberately not the href too -- the field guide's own
# Menlo Park finding is the reason why: "every document served from a
# path containing agendas-and-minutes, so the href alone says agenda for
# the minutes too." Guarding on the href there would exclude BOTH the
# real minutes AND the real agenda links sharing that path; the anchor's
# own text is what actually distinguishes them (confirmed by this
# module's own synthetic regression test built from that exact shape).
_MINUTES_GUARD_RE = re.compile(r"\bminutes\b|\bsubscribe\b|\bcalendar\b", re.IGNORECASE)

# WO-1033 item 1: a news item is never a meeting page, whatever its own
# headline says (real false positive: a CivicAlerts.aspx press release
# headlined "City Council Responds to Special Election Call" scores as
# meeting-shaped on link text alone). Checked against the raw href, not
# `hay`, since a news item's own anchor text is exactly what makes it
# look meeting-shaped in the first place.
_NEWS_ITEM_HREF_RE = re.compile(r"civicalerts\.aspx", re.IGNORECASE)

# WO-1033 item 1: an email-signup/subscription page (a feed sign-up, not
# a meeting page) -- real GovDelivery shape
# (`public.govdelivery.com/accounts/<code>/subscribers/...`) plus the
# more general CivicPlus `/list.aspx` subscribe page and "Stay
# Informed"/"Notify Me" link text.
_SIGNUP_PAGE_RE = re.compile(
    r"govdelivery\.com/accounts/[^/]+/subscribers"
    r"|/list\.aspx"
    r"|\bstay\s+informed\b"
    r"|\bnotify\s*me\b",
    re.IGNORECASE,
)

# WO-1033 item 1: a bare calendar-event permalink -- a real meeting page
# only when its own title names a governing body or a meeting (checked
# separately, against `GOVERNING_BODY_KEYWORDS` -- see this module's own
# docstring). Deliberately narrower than `_MEETING_PAGE_HREF_RE`'s own
# `/event/\d+/?`/`/events/\d+/?` shapes (which already require a rule-1/
# rule-2/rule-page-level hit to qualify at all) -- this is specifically
# the CivicPlus/CivicEngage calendar-widget shape confirmed live on
# Dublin CA (`/m/calendar/event/detail/<n>`) and Emporia KS
# (`Calendar.aspx?EID=<n>`).
_CALENDAR_EVENT_PERMALINK_RE = re.compile(
    r"/calendar/event/detail/\d+|calendar\.aspx\?[^#]*\beid=\d+", re.IGNORECASE
)

# WO-1033 item 1: the vocabulary that makes a calendar event a real
# MEETING (as opposed to "Night Market"/"Senior Info Fair") -- Granicus's
# own governing-body word list plus "meeting" itself, same words
# `pick.py`'s own title filters already lean on elsewhere.
_MEETING_BODY_OR_WORD_RE = re.compile(
    r"\b(?:" + "|".join(GOVERNING_BODY_KEYWORDS) + r"|meeting)\b", re.IGNORECASE
)

# WO-1039 item 3: shapes that are never a meeting page, whatever anchor
# text sits on them -- a print view, a contact/mail form, or a raw image/
# asset link. Real, confirmed shapes: Montclair SD, NJ's own Infinite
# Campus "Send Email" form (`/email/Default.aspx?action=
# sendemailtous`), Bellefonte, PA's own WordPress news feed, whose every
# post links a `.../print/` view and embeds real uploaded images
# (`wp-content/uploads/.../*.png`/`.jpg`) -- `hop.py`'s own
# `_JUNK_LINK_HREF_RE` covers the identical shapes for Hop's own ranking
# (re-declared, not imported, same convention this module already
# follows elsewhere for a `hop.py` pattern).
_JUNK_HREF_RE = re.compile(
    r"/print/?(?:[?#].*)?$"
    r"|/email/default\.aspx\?[^#]*\baction=sendemailtous\b"
    r"|\.(?:png|jpe?g|gif|svg)(?:[?#].*)?$",
    re.IGNORECASE,
)
# WO-1039 item 3: an ordinary CMS/blog news post whose own headline
# announces an office closure/holiday hours -- never a meeting, even
# though it carries a real date (real Bellefonte, PA case: "Borough
# Office Closed-Monday, September 7, 2026"). Narrow on purpose (a real
# meeting is never itself an office-closure announcement).
_CLOSURE_NEWS_TEXT_RE = re.compile(
    r"\boffice\s+closed\b|\bclosed\s+\w+day\b|\bholiday\s+(?:hours|closure)\b",
    re.IGNORECASE,
)

# WO-1033 item 4: a same-site redirect to a social platform (CivicPlus's
# own quick-link-widget shape: `<a href="/youtube" aria-label="YouTube">
# <img alt="YouTube"></a>`, no visible anchor text at all, confirmed live
# on Emporia KS's real homepage) -- a YouTube lead, never a page to open.
# Same pattern as `hop.py`'s own `_SAME_SITE_SOCIAL_REDIRECT_RE`,
# re-declared here (see this module's own docstring for why) rather than
# imported.
_SAME_SITE_SOCIAL_REDIRECT_RE = re.compile(r"^/(?:youtube|facebook)/?$", re.IGNORECASE)

# A bare year heading ("2026") that groups a whole year's worth of
# meetings -- the field guide's own instruction to skip past this rather
# than treat it as a meeting's real date when walking up through
# ancestors.
_BARE_YEAR_RE = re.compile(r"^\s*\d{4}\s*$")


# WO-1037 item 6: a "meeting page" is only worth opening when it's on the
# government's OWN site or a recognized meeting vendor -- real false
# positives caught live: James Island SC's homepage "LIVESTREAM TOWN
# MEETINGS" nav sits next to Facebook permalinks that also carry
# meeting-shaped anchor text, and Cecil County PS MD's own "Board Meeting
# Live Feed and Recordings" iframe sits on a page that also links
# usgbc.org (a green-building certification badge, unrelated). Neither is
# a meeting page to open. A crude last-two-labels domain-family compare
# (same one `scripts/wo908_headless_pilot.py`'s `_registrable_domain()`
# already uses for the same "same government's own site" question --
# not a general public-suffix-list implementation, just good enough to
# tell `www.james-island.sc.gov` from `facebook.com`).
def _registrable_domain(host: str) -> str:
    parts = [p for p in (host or "").lower().split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "").lower()


def _is_own_site_or_recognized_vendor(url: str, base_netloc: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        return False
    if netloc == base_netloc or _registrable_domain(netloc) == _registrable_domain(
        base_netloc
    ):
        return True
    platform = detect_platform(url)
    if platform and platform != "unknown":
        return True
    host_platform, _supported = host_recognition.platform_for_host(netloc)
    return host_platform is not None


# WO-1039 item 1: the same "off-site link naming a TV/cable/community-
# access station" rescue `hop.py`'s own `_rescue_tv_station_link_score()`
# uses for Hop's ranking (see that module's docstring for the full real
# examples this fixes: Winchester MA's "WinCAM"/wincam.org, Tigard/Lake
# Oswego OR's "tvctv.org", Bismarck ND's "dakotamediaaccess.org", Mendota
# Heights MN's "townsquare.tv") -- re-declared here rather than imported,
# same convention this module already follows for
# `_SAME_SITE_SOCIAL_REDIRECT_RE` (see this module's own docstring for
# why it doesn't otherwise depend on `hop.py`). Without this,
# `_is_own_site_or_recognized_vendor()` above blocks the town's own
# station domain outright (a different registrable domain than the
# government's, and not a recognized meeting VENDOR host), so the real
# video -- one or two hops further into the station's own site -- is
# never reached at all; `hop.py`'s own ranking is what actually walks
# those further hops once this gate lets the station's homepage through
# as a meeting-page link worth opening.
_TV_STATION_TEXT_RE = re.compile(
    r"\btelevision\b|\bcable\s*access\b|\bpublic\s*access\b|\bcommunity\s+access\b"
    r"|\bmedia\s+access\b|\bcommunity\s+media\b",
    re.IGNORECASE,
)
_TV_STATION_BRAND_WORD_RE = re.compile(r"^[A-Za-z]{2,}(?:tv|cam)$", re.IGNORECASE)
_TV_STATION_BRAND_STOPLIST = frozenset(
    {"hdtv", "iptv", "cctv", "smarttv", "appletv", "webcam", "dashcam", "gocam"}
)
_TV_VANITY_TLD_RE = re.compile(r"\.tv$", re.IGNORECASE)
# Never rescued for a social/unrelated host, whatever its anchor text
# happens to say -- CLAUDE.md's "keep Facebook/social/unrelated sites
# out" for this WO's item 1.
_SOCIAL_HOST_HINTS = (
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
)


def _is_off_site_tv_station_link(text: str, url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if any(hint in netloc for hint in _SOCIAL_HOST_HINTS):
        return False
    if _TV_STATION_TEXT_RE.search(text or ""):
        return True
    words = (text or "").strip().split()
    if len(words) == 1:
        word = words[0].strip(",&-()").lower()
        if (
            _TV_STATION_BRAND_WORD_RE.match(word)
            and word not in _TV_STATION_BRAND_STOPLIST
        ):
            return True
    return bool(_TV_VANITY_TLD_RE.search(netloc))


_DATE_TEXT_RE = re.compile(
    r"\d{1,2}/\d{1,2}/\d{4}"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|"
    r"Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)

# A page whose own <title>/<h1> says this makes a bare, date-only link a
# meeting link on its own (field guide's page-level rule, Pleasant Hill's
# 713 date-only agenda links).
_PAGE_LEVEL_AGENDA_RE = re.compile(r"\bagendas?\b|\bmeetings?\b", re.IGNORECASE)


@dataclass(frozen=True)
class ScanResult:
    media_candidates: List[Candidate] = field(default_factory=list)
    meeting_page_links: List[str] = field(default_factory=list)
    youtube_leads: List[dict] = field(default_factory=list)
    opened_pages: int = 0
    note: str = ""


def _extract_date_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _DATE_TEXT_RE.search(text)
    return m.group(0) if m else None


def _row_context(a_tag) -> Dict[str, str]:
    """For an anchor inside a `<td>`, returns a lowercased
    {column-label: cell-text} map for the whole enclosing `<tr>` --
    Municode's own `data-th="Date"` attribute (see this module's
    docstring) when present, else the table's `<thead>`/first-row `<th>`
    text by column position. Empty dict when `a_tag` isn't in a table
    row at all (a plain nav/list link)."""
    td = a_tag.find_parent("td")
    if td is None:
        return {}
    tr = td.find_parent("tr")
    if tr is None:
        return {}
    table = tr.find_parent("table")
    header_labels: List[str] = []
    if table is not None:
        header_row = table.find("tr")
        if header_row is not None and header_row is not tr:
            header_labels = [
                (th.get_text(" ", strip=True) or "").lower()
                for th in header_row.find_all(("th", "td"))
            ]
    cells = tr.find_all("td")
    row_map: Dict[str, str] = {}
    for i, cell in enumerate(cells):
        label = (cell.get("data-th") or "").strip().lower()
        if not label and i < len(header_labels):
            label = header_labels[i]
        if label:
            row_map[label] = cell.get_text(" ", strip=True)
    return row_map


def _own_column_label(a_tag) -> str:
    td = a_tag.find_parent("td")
    if td is None:
        return ""
    label = (td.get("data-th") or "").strip().lower()
    if label:
        return label
    row_map = _row_context(a_tag)
    cell_text = td.get_text(" ", strip=True).lower()
    for label, text in row_map.items():
        if text and text.lower() == cell_text:
            return label
    return ""


def _walk_up_for_date(a_tag, *, max_depth: int = 4) -> Optional[str]:
    """Ancestor date walk (field guide: Sebastopol's "Related Documents"
    block has a date nowhere near its immediate parent). Skips a heading
    that is a bare year on its own -- that names a whole year's section,
    not this one meeting."""
    depth = 0
    for parent in a_tag.parents:
        if parent is None or getattr(parent, "name", None) in (None, "[document]"):
            break
        depth += 1
        if depth > max_depth:
            break
        heading = parent.find(("h1", "h2", "h3", "h4", "h5"))
        candidates = []
        if heading is not None:
            candidates.append(heading.get_text(" ", strip=True))
        # A preceding sibling's own text (Sebastopol's accordion header).
        prev = parent.find_previous_sibling()
        if prev is not None:
            candidates.append(prev.get_text(" ", strip=True))
        for text in candidates:
            if not text or len(text) > 80 or _BARE_YEAR_RE.match(text):
                # A long blob (a whole sibling table's flattened text, not
                # a real heading/label) is never a trustworthy date source
                # -- real headings/labels are short.
                continue
            found = _extract_date_text(text)
            if found:
                return found
    return None


def _page_title_text(soup: BeautifulSoup) -> str:
    parts = []
    if soup.title is not None:
        parts.append(soup.title.get_text(" ", strip=True))
    h1 = soup.find("h1")
    if h1 is not None:
        parts.append(h1.get_text(" ", strip=True))
    return " ".join(parts)


def find_meeting_page_links(
    html: str, final_url: str, *, limit: int = 6
) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Returns up to `limit` `(url, date_text, title)` tuples, newest
    dated link first (undated links, if any survive because the page-
    level rule applied, come after, in document order). Pure function --
    no fetching -- so it's independently testable against a saved page."""
    soup = BeautifulSoup(html or "", "html.parser")
    page_text = _page_title_text(soup)
    page_says_agendas = bool(_PAGE_LEVEL_AGENDA_RE.search(page_text))
    base_netloc = urlparse(final_url).netloc.lower()

    found: List[Tuple[Optional[datetime], str, Optional[str], Optional[str]]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        text = a.get_text(" ", strip=True)
        hay = f"{text} {href}"
        if _MINUTES_GUARD_RE.search(text) or _PAGINATION_TEXT_RE.search(hay):
            continue
        # WO-1033 item 1: a news item or an email-signup page is never a
        # meeting page, whatever its own link text says (see this
        # module's docstring for the real CivicAlerts.aspx/GovDelivery
        # false positives this guards against).
        if _NEWS_ITEM_HREF_RE.search(href) or _SIGNUP_PAGE_RE.search(hay):
            continue
        # WO-1039 item 3: a print view, a contact/mail form, or a raw
        # image/asset link is never a meeting page, whatever date or
        # vocabulary its own anchor text (or a sibling's) carries -- see
        # `_JUNK_HREF_RE`'s own comment for the real Bellefonte PA/
        # Montclair SD NJ shapes this guards against.
        if _JUNK_HREF_RE.search(href):
            continue
        # WO-1039 item 3: a news post is never a meeting page just because
        # its own headline carries a real date (rule1_text's bar below) --
        # the generic version of WO-1033 item 1's CivicAlerts.aspx-specific
        # guard, for an ordinary CMS/blog "office closed" post that isn't
        # on that one platform's own URL shape (real Bellefonte, PA case).
        if _CLOSURE_NEWS_TEXT_RE.search(text):
            continue
        full = urljoin(final_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        # WO-1037 item 6: only the government's own site or a recognized
        # meeting vendor -- see this module's own
        # `_is_own_site_or_recognized_vendor()` docstring for the real
        # Facebook-permalink/usgbc.org false positives this guards
        # against. WO-1039 item 1: OR an off-site link naming a TV/cable/
        # community-access station, worth opening for one step even
        # though it fails that check -- see `_is_off_site_tv_station_link()`
        # 's own comment.
        is_own_or_vendor = _is_own_site_or_recognized_vendor(full, base_netloc)
        is_tv_station_offsite = not is_own_or_vendor and _is_off_site_tv_station_link(
            text, full
        )
        if not is_own_or_vendor and not is_tv_station_offsite:
            continue
        if any(parsed.path.lower().endswith(ext) for ext in _DOCUMENT_EXTENSIONS):
            continue
        if _DOCUMENT_HREF_RE.search(href):
            continue
        if full in seen:
            continue
        # A direct media/YouTube link is already handled by this module's
        # own media-candidate/YouTube-lead scans -- never also offered as
        # a "page" to open (real bug caught live against Jackson County
        # AL's real AgendaCenter page, WO-1029: its `td.media` column's
        # bare `youtu.be/...` links matched rule 1 on the word "Video" in
        # their own anchor text).
        if extract_video_id(full) is not None:
            continue
        _link_platform = detect_platform(full)
        if _link_platform in _SCAN_MEDIA_PLATFORMS:
            continue
        # WO-1038: only a SPECIFIC TelVue video link is excluded here (it's
        # already handled as a media candidate below) -- a `/home`/`/videos`
        # listing link must still be offered as a page to visit, exactly as
        # before this WO (that's how Irondequoit NY/Ashland OR's own TelVue
        # listing pages get reached today).
        if _link_platform == "telvue" and _is_specific_telvue_media_url(full):
            continue

        column_label = _own_column_label(a)
        if _DOCUMENT_COLUMN_RE.search(column_label):
            continue
        row_map = _row_context(a)

        date_text = _extract_date_text(text)
        if not date_text:
            for label, value in row_map.items():
                if "date" in label:
                    date_text = _extract_date_text(value)
                    if date_text:
                        break
        if not date_text:
            date_text = _walk_up_for_date(a)

        rule1_text = (
            bool(_MEETING_TEXT_RE.search(text))
            or bool(date_text)
            or is_tv_station_offsite
        )
        # Deliberately NOT "agenda"/"video" here -- those name a document
        # column (guarded above) or a direct-media column (Scan's own
        # media-candidate detection already covers a real video link),
        # not a meeting-DETAIL page worth opening for an embedded player.
        rule2_header = any(w in column_label for w in ("meeting", "view", "details"))
        rule3_href = bool(_MEETING_PAGE_HREF_RE.search(href))
        rule_page_level = page_says_agendas and bool(date_text)

        if not (rule1_text or rule2_header or rule3_href or rule_page_level):
            continue

        # WO-1033 item 1: a bare calendar-event permalink only counts as a
        # real meeting page when its own title names a governing body or
        # a meeting -- otherwise a plain date (which alone already
        # satisfies rule1_text above) makes an ordinary community event
        # ("Night Market", "Senior Info Fair") indistinguishable from a
        # real meeting. Meeting-worded href shapes that aren't a bare
        # calendar permalink (`/meetings/2026-09-08-council`, a Municode
        # `/page/...-meeting-278`) already carry their own meeting
        # vocabulary in the URL and are unaffected.
        if _CALENDAR_EVENT_PERMALINK_RE.search(href) and not (
            _MEETING_BODY_OR_WORD_RE.search(text)
        ):
            continue

        title = row_map.get("meeting") or row_map.get("title") or text or None
        if title and _is_test_or_demo_title(title):
            continue

        seen.add(full)
        dt = parse_candidate_date(date_text) if date_text else None
        found.append((dt, full, date_text, title))

    # Newest dated links first (stable sort keeps document order for
    # ties, same convention as pick.py's own rule); undated links sort
    # after every dated one.
    found.sort(
        key=lambda item: (item[0] is None, item[0] or datetime.min), reverse=False
    )
    dated = [item for item in found if item[0] is not None]
    undated = [item for item in found if item[0] is None]
    dated.sort(key=lambda item: item[0], reverse=True)
    ordered = dated + undated
    return [(url, date_text, title) for _dt, url, date_text, title in ordered[:limit]]


# Media-hosting platforms `detect_platform()`/`is_direct_file_url()`
# already recognize that Scan treats as a genuine media candidate --
# docs/MEETING_FINDER.md's Scan section names exactly these three (plus
# the direct .mp4/.m3u8 shapes `scan_media_urls()` already covers).
# Deliberately NOT the wider platform set `detect_platform()` also
# recognizes (Granicus, CivicClerk, Legistar...) -- those are List's
# account-level job (a known vendor account, walked properly), not a
# same-page media find.
#
# WO-1038: added "cablecast" -- Cablecast's own `detect_platform()`
# branch only ever matches a URL that already names a SPECIFIC show
# (`/show/{id}`, `/gallery/{id}`, a bare numeric `cablecast.tv` id, the
# `/cablecastapi/v1/shows/{id}` API), never a bare tenant root, so it's
# just as safe a same-page media find as vimeo/civicweb -- real
# governments this fixes had a Cablecast player embedded directly in an
# `<iframe>`, which only `_anchor_media_candidates()` below scans (Scan's
# `<a href>`-only `find_meeting_page_links()` never sees an iframe at
# all). TelVue is deliberately NOT added here wholesale: its
# `detect_platform()` branch matches ANY `telvue.com`/`peg.tv` URL,
# including a `/home`/`/videos` LISTING page (no single video to
# resolve) -- see `_is_specific_telvue_media_url()` just below for the
# narrower, shape-aware check `_anchor_media_candidates()` uses instead so
# a TelVue iframe/link is only ever treated as a video candidate when it
# actually names one.
_SCAN_MEDIA_PLATFORMS = ("vimeo", "civicweb", "direct_file", "cablecast")

# WO-1038: a TelVue URL that names one specific video -- `/media/{id}`,
# with or without a `/playlists/{n}/` or `/categories/{n}/` prefix (see
# `telvue.py`'s own module docstring for these three real shapes). A
# `/home`, `/videos` or `/stream/{n}` TelVue URL does NOT match this --
# those are listing/live-stream pages with no single video to resolve
# directly (see `passive_verify._telvue_walker()`, which lists them
# instead).
_TELVUE_MEDIA_ID_RE = re.compile(r"/media/\d+", re.I)


def _is_specific_telvue_media_url(url: str) -> bool:
    return bool(_TELVUE_MEDIA_ID_RE.search(urlparse(url).path))


def _anchor_media_candidates(
    html: str, final_url: str, *, lister: str
) -> List[Candidate]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Candidate] = []
    seen = set()
    for tag in soup.find_all(("a", "iframe", "source", "video")):
        raw = tag.get("href") or tag.get("src")
        if not raw:
            continue
        full = urljoin(final_url, raw.strip())
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https") or full in seen:
            continue
        platform = detect_platform(full)
        if platform not in _SCAN_MEDIA_PLATFORMS:
            # WO-1038: a TelVue iframe/link naming one specific video
            # (`/media/{id}`) is a genuine media candidate too -- see
            # `_is_specific_telvue_media_url()`'s own comment for why
            # TelVue isn't just added to `_SCAN_MEDIA_PLATFORMS` wholesale
            # (a `/home`/`/videos` listing page would falsely become a
            # "media candidate" that can never actually resolve).
            if platform == "telvue" and _is_specific_telvue_media_url(full):
                pass
            elif platform == "direct_file" or is_direct_file_url(full):
                platform = "direct_file"
            else:
                continue
        seen.add(full)
        out.append(
            Candidate(
                url=full,
                platform=platform,
                source_phase="scan",
                lister=lister,
                source_url=final_url,
                has_video_hint=True,
            )
        )
    return out


def _direct_media_candidates(
    html: str, final_url: str, *, lister: str
) -> List[Candidate]:
    out: List[Candidate] = []
    for url in scan_media_urls(html or "", final_url):
        kind = media_type(url)
        if kind not in ("video", "audio"):
            continue
        platform = detect_platform(url)
        out.append(
            Candidate(
                url=url,
                platform=platform if platform != "unknown" else None,
                source_phase="scan",
                lister=lister,
                source_url=final_url,
                has_video_hint=True,
            )
        )
    return out


def _youtube_leads(html: str, final_url: str) -> List[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    base_netloc = urlparse(final_url).netloc.lower()
    leads: List[dict] = []
    seen_ids = set()
    seen_redirects = set()
    for tag in soup.find_all(("a", "iframe")):
        raw = tag.get("href") or tag.get("src")
        if not raw:
            continue
        full = urljoin(final_url, raw.strip())
        video_id = extract_video_id(full)
        if video_id:
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            leads.append(
                {
                    "url": full,
                    "video_id": video_id,
                    "anchor_text": (
                        tag.get_text(" ", strip=True) if tag.name == "a" else ""
                    ),
                    "source_url": final_url,
                }
            )
            continue
        # WO-1033 item 4: a same-site redirect (CivicPlus's own
        # "/youtube" quick-link button) -- see this module's docstring.
        # Only for <a> (an <iframe src="/youtube"> isn't a real shape),
        # only on the SAME host as the page itself (a link to some other
        # site's own "/youtube" path is not this government's channel).
        parsed = urlparse(full)
        if (
            tag.name == "a"
            and parsed.netloc.lower() == base_netloc
            and _SAME_SITE_SOCIAL_REDIRECT_RE.match(parsed.path or "/")
            and "youtube" in parsed.path.lower()
            and full not in seen_redirects
        ):
            seen_redirects.add(full)
            leads.append(
                {
                    "url": full,
                    "video_id": None,
                    "anchor_text": tag.get_text(" ", strip=True),
                    "source_url": final_url,
                }
            )
    return leads


def _media_candidates_for_page(
    html: str, final_url: str, *, links_only: bool, lister: str
) -> List[Candidate]:
    if links_only:
        # fetch.py's own rule: a Wayback capture is for links only, never
        # trusted as a source of the government's own media.
        return []
    out = _direct_media_candidates(html, final_url, lister=lister)
    seen = {c.url for c in out}
    for c in _anchor_media_candidates(html, final_url, lister=lister):
        if c.url not in seen:
            seen.add(c.url)
            out.append(c)
    return out


# How many meeting-page link candidates `ScanResult.meeting_page_links`
# reports in total -- deliberately larger than any realistic
# `max_meeting_pages` (Scan only OPENS the newest `max_meeting_pages` of
# these; the rest are still real findings other phases/reporting may
# want, e.g. Hop trying one further down the list if the top ones turn
# out to be off-mission). Newest-first, so a caller that only wants what
# Scan itself opened can just take `meeting_page_links[:max_meeting_pages]`.
_MAX_REPORTED_MEETING_PAGE_LINKS = 20


async def scan_page(
    page: FetchResult, fetcher: Fetcher, *, max_meeting_pages: int = 6
) -> ScanResult:
    """Scans one already-fetched page (`page`, a `fetch.py` `FetchResult`)
    for media candidates, meeting-page links and YouTube leads, then opens
    up to `max_meeting_pages` of the newest meeting-page links through
    `fetcher` and scans each of those too (one level -- a sub-page's own
    meeting-page links are not followed further; that is Hop's job, with
    its own budget). `max_meeting_pages=0` finds and reports links but
    opens none."""
    html = page.html or ""
    final_url = page.final_url or page.requested_url

    media = _media_candidates_for_page(
        html, final_url, links_only=page.links_only, lister="media_scan"
    )
    youtube_leads = _youtube_leads(html, final_url) if html else []
    all_hits = find_meeting_page_links(
        html, final_url, limit=_MAX_REPORTED_MEETING_PAGE_LINKS
    )
    meeting_page_links = [url for url, _date, _title in all_hits]
    meeting_page_hits = all_hits[: max(max_meeting_pages, 0)]

    opened = 0
    notes: List[str] = []
    if page.links_only and meeting_page_hits:
        notes.append(
            f"{len(meeting_page_hits)} meeting-page link(s) found on a "
            "Wayback (links-only) capture; opening them for media anyway "
            "since they are ordinary live URLs, not the Wayback copy itself"
        )

    for url, _date, _title in meeting_page_hits:
        try:
            sub_page = await fetcher.fetch(url)
        except Exception as exc:  # noqa: BLE001 -- BudgetExceeded or a real
            # fetch-layer error; stop opening more pages rather than fail
            # the whole scan (media/links already found above still stand).
            notes.append(f"stopped opening meeting pages: {exc}")
            break
        opened += 1
        if sub_page.html:
            sub_media = _media_candidates_for_page(
                sub_page.html,
                sub_page.final_url or url,
                links_only=sub_page.links_only,
                lister="meeting_page",
            )
            seen = {c.url for c in media}
            for c in sub_media:
                if c.url not in seen:
                    seen.add(c.url)
                    media.append(c)
            youtube_leads.extend(
                _youtube_leads(sub_page.html, sub_page.final_url or url)
            )
        elif sub_page.outcome:
            notes.append(f"{url}: {sub_page.outcome}")

    return ScanResult(
        media_candidates=media,
        meeting_page_links=meeting_page_links,
        youtube_leads=youtube_leads,
        opened_pages=opened,
        note="; ".join(notes),
    )
