"""WO-1044: Hop link-ranking fixes from Ryan's Suffolk County NY notes
(`app/platforms/meeting_finder/hop.py`).

Real evidence (conductor, 2026-09-24): Meeting Finder on suffolkcountyny.gov
(`us:county:36103`) spent its whole fetch budget on news articles, an
EasyDNNNews PDF, `/Site-Feedback`, `/county-executive` and a Google
tracking-tag page -- and never followed the homepage's own
`<a href="https://www.scnylegislature.us/" target="_blank">Legislature</a>`
link. Fixtures under `tests/fixtures/wo1044/` are the REAL saved homepages
(fetched live 2026-09-24) for both suffolkcountyny.gov and its Legislature's
own site, scnylegislature.us -- every href/anchor text asserted on below is
real, confirmed markup from those pages, not invented.
"""

from __future__ import annotations

import os

from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import (
    _GOVERNING_BODY_TEXT_RE,
    _is_calendar_hub_dead_end,
    _is_non_page_resource,
    rank_hops,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo1044")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def _page(html: str, url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )


# --- Item 1: a CivicPlus calendar HUB (CID=, no EID, or bare) is a dead
# end -- Ryan: "virtually NEVER has video". ------------------------------


def test_calendar_hub_with_cid_and_no_eid_is_a_dead_end():
    # Real scnylegislature.us homepage shape.
    url = (
        "https://www.scnylegislature.us/calendar.aspx?CID=138,123,23,62,134,"
        "78,119,143,113,116,36,127,39,142,145,28"
    )
    assert _is_calendar_hub_dead_end(url) is True


def test_bare_calendar_aspx_is_a_dead_end():
    assert _is_calendar_hub_dead_end("https://example.gov/calendar.aspx") is True


def test_calendar_aspx_with_eid_is_not_a_dead_end():
    # A real dated entry -- handled by the existing `_is_calendar_entry_link`
    # penalty/cap instead, not this one.
    assert (
        _is_calendar_hub_dead_end("https://example.gov/Calendar.aspx?EID=1438") is False
    )


def test_calendar_hub_ranks_below_a_generic_nav_link():
    html = """
    <html><body><nav>
      <a href="/calendar.aspx?CID=138,123,23">Calendar</a>
      <a href="/149/Meeting-Information">Meeting Information</a>
    </nav></body></html>
    """
    page = _page(html, "https://www.scnylegislature.us/")
    hops = rank_hops(page)
    urls = [h.url for h in hops]
    calendar_url = "https://www.scnylegislature.us/calendar.aspx?CID=138,123,23"
    meeting_info_url = "https://www.scnylegislature.us/149/Meeting-Information"
    assert meeting_info_url in urls
    if calendar_url in urls:
        cal_score = next(h.score for h in hops if h.url == calendar_url)
        info_score = next(h.score for h in hops if h.url == meeting_info_url)
        assert cal_score < info_score


def test_real_legislature_homepage_ranks_calendar_hub_below_video_hub():
    # Real scnylegislature.us homepage: two CivicPlus calendar-hub links
    # (CID=, no EID) and the real video hub, `/1737/Video-Broadcast-and-
    # Gallery`, all appear on the same page. Evidence (conductor,
    # 2026-09-24): before this fix, a calendar-hub link outranked the real
    # video hub (score 8.4 vs 25.3, i.e. only the video hub's own strong
    # first-party score kept it on top there -- this pins that the
    # calendar hub never climbs above it, and stays well down the list).
    html = _load("scnylegislature_home.html")
    page = _page(html, "https://www.scnylegislature.us/")
    hops = rank_hops(page, limit=20)
    video_hub_url = "https://www.scnylegislature.us/1737/Video-Broadcast-and-Gallery"
    assert any(h.url == video_hub_url for h in hops)
    video_hub_score = next(h.score for h in hops if h.url == video_hub_url)
    for h in hops:
        if "calendar.aspx" in h.url.lower() and "eid=" not in h.url.lower():
            assert h.score < video_hub_score


# --- Item 2: never hop to a non-page resource. ---------------------------


def test_jquery_ui_script_is_not_a_hop_candidate():
    # Real scnylegislature.us shape: `/Common/Controls/jquery-ui-1.14.2/
    # jquery-ui.min.js`.
    url = "https://www.scnylegislature.us/Common/Controls/jquery-ui-1.14.2/jquery-ui.min.js"
    assert _is_non_page_resource(url) is True


def test_googletagmanager_host_is_not_a_hop_candidate():
    assert _is_non_page_resource("https://www.googletagmanager.com/ns.html") is True


def test_css_and_image_assets_are_not_hop_candidates():
    assert _is_non_page_resource("https://example.gov/static/site.css") is True
    assert _is_non_page_resource("https://example.gov/img/logo.png") is True


def test_ordinary_page_is_not_a_non_page_resource():
    assert _is_non_page_resource("https://example.gov/149/Meeting-Information") is False


def test_script_tag_is_never_offered_unless_a_recognized_platform():
    html = """
    <html><body>
      <script src="/Areas/Calendar/Assets/Scripts/Calendar.js"></script>
      <a href="/149/Meeting-Information">Meeting Information</a>
    </body></html>
    """
    page = _page(html, "https://www.scnylegislature.us/")
    hops = rank_hops(page)
    urls = [h.url for h in hops]
    assert not any("Calendar.js" in u for u in urls)


def test_real_legislature_homepage_never_offers_jquery_or_tracking_hop():
    html = _load("scnylegislature_home.html")
    page = _page(html, "https://www.scnylegislature.us/")
    hops = rank_hops(page, limit=25)
    urls = [h.url for h in hops]
    assert not any("jquery-ui" in u for u in urls)
    assert not any("googletagmanager.com" in u for u in urls)
    assert not any("/Common/Controls/" in u for u in urls)


# --- Item 3: a link naming the government's own governing body ranks near
# the top, off-site included. --------------------------------------------


def test_legislature_text_matches_governing_body_regex():
    assert _GOVERNING_BODY_TEXT_RE.search("Legislature") is not None


def test_board_of_supervisors_and_city_council_match():
    assert _GOVERNING_BODY_TEXT_RE.search("Board of Supervisors") is not None
    assert _GOVERNING_BODY_TEXT_RE.search("City Council") is not None
    assert _GOVERNING_BODY_TEXT_RE.search("Board of Education") is not None


def test_offsite_legislature_link_ranks_as_a_hop_candidate():
    # Real Suffolk County NY shape: the homepage's own bare "Legislature"
    # anchor text, no other hub vocabulary at all, links off-site.
    html = """
    <html><body>
      <a href="https://www.scnylegislature.us/" target="_blank" rel="noopener">
        Legislature
      </a>
    </body></html>
    """
    page = _page(html, "https://www.suffolkcountyny.gov/")
    hops = rank_hops(page)
    urls = [h.url for h in hops]
    assert "https://www.scnylegislature.us/" in urls


def test_real_suffolk_homepage_ranks_legislature_link_near_the_top():
    # Real suffolkcountyny.gov homepage -- the fix this WO exists for.
    html = _load("suffolkcountyny_home.html")
    page = _page(html, "https://www.suffolkcountyny.gov/")
    hops = rank_hops(page, limit=10)
    urls = [h.url for h in hops]
    assert "https://www.scnylegislature.us/" in urls
    rank = urls.index("https://www.scnylegislature.us/")
    assert rank < 5, f"expected the Legislature link in the top 5, got rank {rank}"


# --- Item 4: news articles and site chrome are ranked down, not
# excluded. ----------------------------------------------------------------


def test_civicplus_news_article_and_site_chrome_rank_below_a_real_hub():
    # Real Suffolk County NY shapes.
    html = """
    <html><body>
      <a href="/Events/ArtMID/585/ArticleID/15369/A-Taste-of-Italy">
        A Taste of Italy
      </a>
      <a href="/Site-Feedback">Site Feedback</a>
      <a href="/QuickLinks.aspx?CID=47">Quick Links</a>
      <a href="/149/Meeting-Information">Meeting Information</a>
    </body></html>
    """
    page = _page(html, "https://www.suffolkcountyny.gov/")
    hops = rank_hops(page, limit=10)
    by_url = {h.url: h.score for h in hops}
    hub_url = "https://www.suffolkcountyny.gov/149/Meeting-Information"
    assert hub_url in by_url
    for chrome_path in ("A-Taste-of-Italy", "Site-Feedback", "QuickLinks"):
        chrome_url = next((u for u in by_url if chrome_path in u), None)
        if chrome_url is not None:
            assert by_url[chrome_url] < by_url[hub_url]


def test_easydnnnews_document_download_ranks_below_a_real_hub():
    html = """
    <html><body>
      <a href="/DesktopModules/EasyDNNNews/DocumentDownload.ashx?portalid=0&moduleid=585&articleid=14419&documentid=699">
        Agenda PDF
      </a>
      <a href="/149/Meeting-Information">Meeting Information</a>
    </body></html>
    """
    page = _page(html, "https://www.suffolkcountyny.gov/")
    hops = rank_hops(page, limit=10)
    by_url = {h.url: h.score for h in hops}
    hub_url = "https://www.suffolkcountyny.gov/149/Meeting-Information"
    pdf_url = next((u for u in by_url if "DocumentDownload" in u), None)
    assert hub_url in by_url
    if pdf_url is not None:
        assert by_url[pdf_url] < by_url[hub_url]


# --- Full real-page regression: the homepage that started this WO. -------


def test_real_suffolk_homepage_end_to_end_ranking():
    """Real suffolkcountyny.gov homepage, everything together: the real
    Legislature link ranks ahead of the real news articles/site-chrome
    links that used up Meeting Finder's whole fetch budget before this
    fix (conductor evidence, 2026-09-24)."""
    html = _load("suffolkcountyny_home.html")
    page = _page(html, "https://www.suffolkcountyny.gov/")
    hops = rank_hops(page, limit=15)
    by_url = {h.url: h.score for h in hops}
    legislature_url = "https://www.scnylegislature.us/"
    assert legislature_url in by_url
    for u, score in by_url.items():
        if "/Events/ArtMID/" in u or "/Site-Feedback" in u or "/QuickLinks.aspx" in u:
            assert score < by_url[legislature_url]
