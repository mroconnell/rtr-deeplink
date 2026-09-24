"""WO-1039: the four TelVue/link-ranking items cut from WO-1038 for time
(see BACKLOG_DONE.md's WO-1039 entry and BACKLOG.md's WO-1038 entry for
the full writeup).

1. An off-site link naming a TV/cable/community-access station is worth
   one hop even when it's a different registrable domain than the
   government's own -- `scan._is_off_site_tv_station_link()` (Scan's own
   meeting-page-link filter) and `hop._rescue_tv_station_link_score()`
   (Hop's own ranking).
2. A budget floor: Pass 1 (Identify->List->Resolve) reserves a few
   fetches for Pass 2 (Scan/Hop) rather than being able to spend the
   WHOLE government budget on its own -- `fetch.Fetcher.reserve()` /
   `SoftBudgetExceeded`.
3. Contact/mail forms, print views, raw image/asset links, and news/
   "closed" posts rank below a same-page known-platform link (`hop.py`)
   and are excluded outright from Scan's own meeting-page-link candidates
   (`scan.py`).
4. aiohttp's own default 8190-byte header-size limit is raised, so a real
   site whose response headers exceed it doesn't fail outright.

Every anchor text/href below is a REAL, confirmed shape from a named real
government (see this WO's own diagnosis case files) -- each test builds a
small SYNTHETIC page around that real fragment (CLAUDE.md's synthetic-
test rule), rather than saving a full real page, since only one specific
link/shape on a large real homepage is under test.
"""

from __future__ import annotations

import asyncio

import pytest

from app.platforms.meeting_finder.fetch import (
    BudgetExceeded,
    FetchResult,
    Fetcher,
    SoftBudgetExceeded,
    _MAX_HEADER_SIZE,
)
from app.platforms.meeting_finder.hop import rank_hops
from app.platforms.meeting_finder.scan import (
    _is_off_site_tv_station_link,
    find_meeting_page_links,
)


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


# --- Item 1: off-site TV/cable/community-access station links. ---------


def test_wincam_bare_brand_text_is_recognized_off_site():
    # Real Winchester, MA homepage link: <a href="https://wincam.org/">
    # WinCAM</a> -- no "television"/"access" vocabulary at all.
    assert _is_off_site_tv_station_link("WinCAM", "https://wincam.org/") is True


def test_dakota_media_access_text_is_recognized_off_site():
    # Real Bismarck, ND anchor text: "Dakota Media Access".
    assert (
        _is_off_site_tv_station_link(
            "Dakota Media Access", "https://dakotamediaaccess.org/"
        )
        is True
    )


def test_tv_vanity_tld_is_recognized_off_site_even_without_station_words():
    # Real Mendota Heights, MN link: townsquare.tv, anchor text carries no
    # station vocabulary of its own.
    assert _is_off_site_tv_station_link("Watch Us", "https://townsquare.tv/") is True


def test_facebook_link_is_never_rescued_even_with_station_looking_text():
    assert (
        _is_off_site_tv_station_link("WinCAM", "https://www.facebook.com/wincam")
        is False
    )


def test_webcam_stoplist_word_is_not_mistaken_for_a_station_brand():
    assert _is_off_site_tv_station_link("webcam", "https://example.org/") is False


def test_find_meeting_page_links_follows_the_wincam_style_offsite_link():
    # Winchester, MA's own real homepage shape: a plain nav link to a
    # different registrable domain, bare "WinCAM" anchor text, no date,
    # no ordinary meeting vocabulary at all -- WO-1037 item 6's own-site-
    # or-vendor filter would otherwise drop it outright.
    html = """
    <html><body>
    <nav>
      <a href="https://wincam.org/">WinCAM</a>
      <a href="/agenda-center">Agenda Center</a>
    </nav>
    </body></html>
    """
    links = find_meeting_page_links(html, "https://winchester.us/", limit=6)
    urls = [u for u, _date, _title in links]
    assert "https://wincam.org/" in urls


def test_find_meeting_page_links_still_excludes_facebook_offsite_links():
    html = """
    <html><body>
    <a href="https://www.facebook.com/townpage">Council Meeting Updates</a>
    </body></html>
    """
    links = find_meeting_page_links(html, "https://example-town.gov/", limit=6)
    assert links == []


def test_rank_hops_rescues_the_wincam_style_offsite_link():
    html = """
    <html><body>
    <nav><a href="https://wincam.org/">WinCAM</a></nav>
    </body></html>
    """
    page = _page(html, "https://winchester.us/")
    hops = rank_hops(page, limit=8)
    assert any(h.url == "https://wincam.org/" for h in hops)


# --- Item 2: Pass-1 budget reserve (SoftBudgetExceeded). ----------------


def test_fetcher_reserve_raises_soft_budget_exceeded_before_the_hard_ceiling():
    fetcher = Fetcher(max_fetches=12)
    fetcher.reserve(3)
    # Fill up to the soft ceiling (12 - 3 = 9) without raising.
    for _ in range(9):
        fetcher._take_budget()
    with pytest.raises(SoftBudgetExceeded):
        fetcher._take_budget()
    # The hard ceiling itself is untouched -- fetches_used never moved
    # past the soft ceiling on the failed call.
    assert fetcher.fetches_used == 9


def test_soft_budget_exceeded_is_a_budget_exceeded_subclass():
    # Every existing `except BudgetExceeded` site across identify.py/
    # listing.py must keep working unchanged -- see fetch.py's own
    # docstring for SoftBudgetExceeded.
    assert issubclass(SoftBudgetExceeded, BudgetExceeded)


def test_release_reserve_lets_pass_2_use_the_full_remaining_budget():
    fetcher = Fetcher(max_fetches=5)
    fetcher.reserve(2)
    for _ in range(3):
        fetcher._take_budget()
    with pytest.raises(SoftBudgetExceeded):
        fetcher._take_budget()
    fetcher.release_reserve()
    # Now the full remaining budget (2 more, up to the hard ceiling of 5)
    # is available again.
    fetcher._take_budget()
    fetcher._take_budget()
    assert fetcher.fetches_used == 5
    with pytest.raises(BudgetExceeded):
        fetcher._take_budget()


# --- Item 3: rank down/exclude junk link shapes. ------------------------


def test_contact_form_link_is_excluded_from_meeting_page_links():
    # Real Montclair SD, NJ shape: an Infinite Campus "Send Email" contact
    # form, real anchor text, on a page that also has a real dated
    # meeting link.
    html = """
    <html><body>
    <a href="/common/controls/general/email/Default.aspx?action=sendemailtous&recipients=x">Send Email</a>
    <a href="/Calendar.aspx?EID=123">Board Meeting September 23, 2026</a>
    </body></html>
    """
    links = find_meeting_page_links(html, "https://montclair.k12.nj.us/", limit=6)
    urls = [u for u, _date, _title in links]
    assert not any("sendemailtous" in u for u in urls)
    assert any("EID=123" in u for u in urls)


def test_print_view_and_raw_image_links_are_excluded_from_meeting_page_links():
    # Real Bellefonte, PA shape: a WordPress news feed's own print view
    # and uploaded images.
    html = """
    <html><body>
    <a href="/2026/borough-office-closed-monday-september-7-2026/print/"></a>
    <a href="/wp-content/uploads/2026/09/photo.png"></a>
    </body></html>
    """
    links = find_meeting_page_links(html, "https://bellefonte.net/", limit=6)
    assert links == []


def test_office_closed_news_post_is_excluded_despite_carrying_a_real_date():
    # Real Bellefonte, PA headline: a real date alone would otherwise
    # satisfy rule1_text.
    html = """
    <html><body>
    <a href="/2026/borough-office-closed-monday-september-7-2026/">Borough Office Closed-Monday, September 7, 2026</a>
    </body></html>
    """
    links = find_meeting_page_links(html, "https://bellefonte.net/", limit=6)
    assert links == []


def test_rank_hops_penalizes_contact_form_and_print_and_image_links():
    html = """
    <html><body>
    <a href="/common/controls/general/email/Default.aspx?action=sendemailtous">Send Email</a>
    <a href="/2026/some-post/print/">Print</a>
    <a href="/wp-content/uploads/2026/photo.png">Photo</a>
    <a href="/1604/Meetings-Agendas-Minutes-Video-on-Demand">Meetings, Agendas, Minutes &amp; Video on Demand</a>
    </body></html>
    """
    page = _page(html, "https://example-town.gov/")
    hops = rank_hops(page, limit=8)
    by_url = {h.url: h.score for h in hops}
    hub_score = by_url[
        "https://example-town.gov/1604/Meetings-Agendas-Minutes-Video-on-Demand"
    ]
    for junk_path in (
        "/common/controls/general/email/Default.aspx?action=sendemailtous",
        "/2026/some-post/print/",
        "/wp-content/uploads/2026/photo.png",
    ):
        junk_url = "https://example-town.gov" + junk_path
        assert junk_url not in by_url or by_url[junk_url] < hub_score


# --- Item 4: header-size limit. ------------------------------------------


def test_max_header_size_is_raised_above_aiohttps_default():
    # aiohttp's own default is 8190 -- real Norton City Schools failure
    # (`ClientResponseError: 400 ... Got more than 8190 bytes`).
    assert _MAX_HEADER_SIZE > 8190


def test_session_for_uses_the_raised_header_size_limits():
    async def _check():
        fetcher = Fetcher()
        session = await fetcher._session_for()
        try:
            assert session._max_line_size == _MAX_HEADER_SIZE
            assert session._max_field_size == _MAX_HEADER_SIZE
        finally:
            await fetcher.aclose()

    asyncio.run(_check())
