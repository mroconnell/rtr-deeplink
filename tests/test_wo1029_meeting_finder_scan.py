"""WO-1029: Meeting Finder's Scan phase (`app/platforms/meeting_finder/
scan.py`).

Real fixtures reused, not re-saved:

- `tests/fixtures/municode_meetings/` (WO's own README explains each
  file) -- `bristol_home.html`'s own "Video" column is empty on most
  rows, but its "View Details" links lead to real meeting-detail pages
  (`bristol_meeting_278.html`, a real YouTube embed via `#mcc_agenda_
  video`; `hamburg_meeting_pc12.html`, a real Vimeo embed) -- exactly
  the "embedded video is often only visible one click down" case this
  phase exists for. `fairoaks_home.html` is the other real shape: every
  populated video cell already holds a bare, absolute YouTube URL
  directly on the homepage, no second hop needed.
- `tests/fixtures/civicplus/durham_agendacenter_citycouncil.html` --
  Durham NC's real AgendaCenter page, 22 of 31 rows with a real video
  link in `td.media` (21 Granicus, 1 YouTube; see that fixture's own
  README note). The Granicus links are real player PAGES
  (`durham.granicus.com/player/clip/N`), not a direct stream URL --
  confirmed live 2026-09-23 building this WO -- so they surface as
  `meeting_page_links`, and the real stream only turns up one hop
  further, same as Municode's own "View Details" case.

A few small synthetic snippets (documented inline) exercise one already-
decided branch each (the minutes/pagination guard, the bare-year
ancestor skip, the Wayback links-only rule) per CLAUDE.md's synthetic-
test convention.
"""

from __future__ import annotations

import asyncio
import os

from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.scan import find_meeting_page_links, scan_page

FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(*parts: str) -> str:
    with open(
        os.path.join(FIXTURE_ROOT, *parts), encoding="utf-8", errors="replace"
    ) as f:
        return f.read()


def _page(html: str, url: str, *, links_only: bool = False) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=links_only,
        elapsed_ms=0,
    )


class _StubFetcher:
    """Returns a canned page per URL (or an empty page for anything
    unlisted), never makes a real request. `calls` records what
    `scan_page()` asked for, so tests can assert it opened the RIGHT
    pages within `max_meeting_pages`."""

    def __init__(self, pages: dict[str, FetchResult] | None = None):
        self.pages = pages or {}
        self.calls: list[str] = []

    async def fetch(self, url: str, **kwargs):
        self.calls.append(url)
        if url in self.pages:
            return self.pages[url]
        return _page("<html><body></body></html>", url)


def _run(coro):
    return asyncio.run(coro)


# --- find_meeting_page_links: the three detection rules + guards -------


def test_bristol_home_finds_dated_view_pages_newest_first():
    html = _load("municode_meetings", "bristol_home.html")
    hits = find_meeting_page_links(
        html, "https://bristol-ri.municodemeetings.com/", limit=6
    )
    urls = [u for u, _d, _t in hits]
    # Real "View Details" meeting-detail pages (rule 2: the row's own
    # "View" column, since the anchor text alone carries no date/meeting
    # word) -- newest date first.
    assert urls[0] == (
        "https://bristol-ri.municodemeetings.com/bc-towncouncil/page/"
        "town-council-meeting-275"
    )
    dates = [d for _u, d, _t in hits]
    assert dates == sorted(dates, reverse=True)
    # Icon-only Agenda/Agenda Packet document links (column-header rule
    # would otherwise catch "Agenda") must never appear -- they're
    # documents, not meeting-detail pages.
    assert not any("adaHtmlDocument" in u for u in urls)
    # The homepage's own pagination link must never be treated as a dated
    # meeting page (real bug this WO fixed -- see scan.py's own
    # `_PAGINATION_TEXT_RE` comment).
    assert not any("meetings3" in u for u in urls)


def test_fairoaks_home_does_not_treat_absolute_youtube_links_as_pages():
    html = _load("municode_meetings", "fairoaks_home.html")
    hits = find_meeting_page_links(
        html, "https://fairoaksranch-tx.municodemeetings.com/", limit=6
    )
    urls = [u for u, _d, _t in hits]
    assert all("youtube.com" not in u and "youtu.be" not in u for u in urls)
    # The real "View Details"-style meeting pages are still found.
    assert any("/bc-cc/page/" in u for u in urls)


def test_durham_agendacenter_skips_viewfile_document_links():
    """Real regression caught live against Jackson County AL's
    AgendaCenter page while building this WO (see scan.py's own
    `_DOCUMENT_HREF_RE` comment): a `ViewFile/Agenda/...` link serves a
    PDF with no `.pdf` in its URL and must never be offered as a page to
    open. Durham's own fixture has the same `ViewFile` shape."""
    html = _load("civicplus", "durham_agendacenter_citycouncil.html")
    hits = find_meeting_page_links(
        html, "https://nc-durham.civicplus.com/AgendaCenter/City-Council-4", limit=10
    )
    urls = [u for u, _d, _t in hits]
    assert not any("viewfile" in u.lower() for u in urls)


_MINUTES_GUARD_HTML = """
<html><head><title>City Council Agendas</title></head><body>
<a href="/agendas-and-minutes/2026-09-08">September 8, 2026 Minutes</a>
<a href="/agendas-and-minutes/2026-09-15">September 15, 2026 Agenda</a>
</body></html>
"""


def test_minutes_guard_applies_even_on_an_agenda_shaped_page():
    """Synthetic, documented: reproduces the field guide's own Menlo Park
    finding (every document served from an `agendas-and-minutes` path,
    so the href alone says "agenda" for the minutes too) -- exercises
    the one already-decided branch (the guard applies regardless of
    which rule would otherwise match), not a new payload shape."""
    hits = find_meeting_page_links(_MINUTES_GUARD_HTML, "https://example.gov/", limit=5)
    urls = [u for u, _d, _t in hits]
    assert urls == ["https://example.gov/agendas-and-minutes/2026-09-15"]


_BARE_YEAR_ANCESTOR_HTML = """
<html><body>
<h2>2026</h2>
<div>
  <h3>Related Documents</h3>
  <a href="/documents/council-meeting-agenda">Council Meeting Agenda</a>
</div>
</body></html>
"""


def test_walk_up_for_date_skips_a_bare_year_heading():
    """Synthetic, documented: the field guide's Sebastopol case (a
    "Related Documents" block whose real date sits nowhere on the link
    itself) minus a real date anywhere -- confirms a bare year heading
    is never mistaken for the meeting's own date, one already-decided
    branch, not a claim that this shape resolves a date when none is
    present."""
    hits = find_meeting_page_links(
        _BARE_YEAR_ANCESTOR_HTML, "https://example.gov/", limit=5
    )
    assert hits, "the page-level/text rule should still find the link"
    _url, date_text, _title = hits[0]
    assert date_text is None


# --- scan_page(): media candidates, youtube leads, opening sub-pages ----


def test_scan_page_bristol_home_opens_view_pages_and_finds_youtube_lead():
    home_html = _load("municode_meetings", "bristol_home.html")
    detail_html = _load("municode_meetings", "bristol_meeting_278.html")
    home_url = "https://bristol-ri.municodemeetings.com/"
    detail_url = (
        "https://bristol-ri.municodemeetings.com/bc-towncouncil/page/"
        "town-council-meeting-275"
    )
    fetcher = _StubFetcher({detail_url: _page(detail_html, detail_url)})
    result = _run(scan_page(_page(home_html, home_url), fetcher, max_meeting_pages=1))
    assert fetcher.calls == [detail_url]
    assert result.opened_pages == 1
    assert not result.media_candidates  # bristol_meeting_278's video is YouTube
    assert any(lead["video_id"] == "bhpXBnBdpZc" for lead in result.youtube_leads)


def test_scan_page_hamburg_meeting_finds_vimeo_media_candidate():
    html = _load("municode_meetings", "hamburg_meeting_pc12.html")
    url = (
        "https://hamburg-mi.municodemeetings.com/bc-pc/page/"
        "planning-commission-meeting-12"
    )
    fetcher = _StubFetcher()
    result = _run(scan_page(_page(html, url), fetcher, max_meeting_pages=6))
    assert any(c.platform == "vimeo" for c in result.media_candidates)
    assert all(c.source_phase == "scan" for c in result.media_candidates)
    assert all(c.lister == "media_scan" for c in result.media_candidates)


def test_scan_page_durham_lists_granicus_player_pages_and_a_youtube_lead():
    """Durham's real `td.media` links (per the fixture's own README: 21
    Granicus + 1 YouTube of 31 rows) are Granicus PLAYER pages
    (`durham.granicus.com/player/clip/N?redirect=true`), not a direct
    stream URL -- the real video only turns up one hop further (this is
    the Granicus equivalent of Municode's own "View Details" case).
    `max_meeting_pages=0` reports every found link but opens none, so no
    media candidate should appear from the listing page alone."""
    html = _load("civicplus", "durham_agendacenter_citycouncil.html")
    url = "https://nc-durham.civicplus.com/AgendaCenter/City-Council-4"
    fetcher = _StubFetcher()
    result = _run(scan_page(_page(html, url), fetcher, max_meeting_pages=0))
    assert result.opened_pages == 0
    assert result.media_candidates == []
    granicus_links = [u for u in result.meeting_page_links if "granicus.com" in u]
    assert len(granicus_links) >= 15
    assert result.youtube_leads, "Durham's one real YouTube row should be a lead"


def test_scan_page_durham_opens_a_granicus_player_page_for_its_stream():
    """With a real budget, Scan opens the newest Granicus player page and
    finds the actual playable stream inside it (a real, live-confirmed
    `archive-stream.granicus.com/.../playlist.m3u8` shape, reused here as
    the stub's canned response since fetching Granicus live isn't needed
    to prove Scan's own one-hop-deeper wiring)."""
    html = _load("civicplus", "durham_agendacenter_citycouncil.html")
    url = "https://nc-durham.civicplus.com/AgendaCenter/City-Council-4"
    player_html = (
        '<html><body><script>file: "https://archive-stream.granicus.com/'
        'OnDemand/_definst_/mp4:archive/durham/durham_x.mp4/playlist.m3u8"'
        "</script></body></html>"
    )
    canned = {}
    fetcher = _StubFetcher(canned)

    async def fetch_first_then_canned(url, **kwargs):
        fetcher.calls.append(url)
        return _page(player_html, url)

    fetcher.fetch = fetch_first_then_canned  # type: ignore[method-assign]
    result = _run(scan_page(_page(html, url), fetcher, max_meeting_pages=1))
    assert result.opened_pages == 1
    assert any(c.platform == "granicus" for c in result.media_candidates)
    assert any(c.lister == "meeting_page" for c in result.media_candidates)


def test_scan_page_max_meeting_pages_caps_how_many_are_opened():
    home_html = _load("municode_meetings", "bristol_home.html")
    fetcher = _StubFetcher()
    result = _run(
        scan_page(
            _page(home_html, "https://bristol-ri.municodemeetings.com/"),
            fetcher,
            max_meeting_pages=2,
        )
    )
    assert result.opened_pages == 2
    assert len(fetcher.calls) == 2


def test_scan_page_links_only_page_yields_no_media_candidates():
    """fetch.py's own rule: a Wayback capture is for links only, never a
    source of the government's own media -- even when its raw HTML
    would otherwise match `scan_media_urls()`."""
    html = (
        '<html><body><a href="https://example.gov/media/clip.mp4">Watch</a>'
        '<a href="/meetings/2026-09-08-council">September 8, 2026 Council</a>'
        "</body></html>"
    )
    page = _page(html, "https://example.gov/", links_only=True)
    fetcher = _StubFetcher()
    result = _run(scan_page(page, fetcher, max_meeting_pages=0))
    assert result.media_candidates == []
    assert result.meeting_page_links  # the meeting-page link is still real


def test_scan_page_handles_a_dead_top_page_without_raising():
    page = FetchResult(
        requested_url="https://example.gov/",
        final_url="https://example.gov/",
        status=None,
        html=None,
        access_mode="dead",
        outcome="dns-unresolvable",
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )
    result = _run(scan_page(page, _StubFetcher(), max_meeting_pages=3))
    assert result.media_candidates == []
    assert result.meeting_page_links == []
    assert result.opened_pages == 0
