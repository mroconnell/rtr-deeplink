"""WO-1033: link-quality fixes in Meeting Finder's Hop and Scan phases
(`app/platforms/meeting_finder/hop.py`, `scan.py`).

Real fixtures, `tests/fixtures/wo1033_hop_scan/` (that directory's own
README has the exact sources/fetch dates -- Dublin CA fetched live,
Emporia KS via Wayback since it started 403ing during this WO's own
investigation). Every case below is a real, confirmed shape from those
two governments -- see `hop.py`/`scan.py`'s own module docstrings for the
full write-up of each bug.
"""

from __future__ import annotations

import os

from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import (
    _is_calendar_entry_link,
    _is_same_site_social_redirect,
    _looks_like_nav_hub_label,
    canonical_page_key,
    rank_hops,
)
from app.platforms.meeting_finder.scan import find_meeting_page_links, _youtube_leads

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo1033_hop_scan")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def _page(html: str, url: str, *, access_mode: str = "plain") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode=access_mode,
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )


DUBLIN_HOME = _load("dublin_home.html")
DUBLIN_1604 = _load("dublin_1604.html")
EMPORIA_HOME = _load("emporia_home_wayback.html")
EMPORIA_1310 = _load("emporia_1310_wayback.html")


# --- Item 1: a word-less nav link (Emporia's real "Agendas & Minutes"
# CivicPlus quick-link button, `<a href="/1300">`) must rank, and near
# the top. ---------------------------------------------------------------


def test_looks_like_nav_hub_label_accepts_real_nav_labels():
    assert _looks_like_nav_hub_label("Agendas & Minutes") is True
    assert _looks_like_nav_hub_label("Watch Meetings") is True
    assert _looks_like_nav_hub_label("Meetings, Agendas, Minutes & Video on Demand")


def test_looks_like_nav_hub_label_rejects_prose_with_the_same_words():
    # A real CivicAlerts.aspx-style headline -- contains "meeting"/
    # "council" but is prose, not a short nav label.
    assert (
        _looks_like_nav_hub_label("City Council Meeting Rescheduled for Next Week")
        is False
    )
    assert _looks_like_nav_hub_label("Night Market at St. Pat's Row") is False
    assert _looks_like_nav_hub_label("") is False


def test_emporia_homepage_ranks_the_real_agendas_and_minutes_button_first():
    """Real bug: `/1300` (Emporia's real meetings hub, a CivicPlus
    graphic-links quick-link button with no path words at all) did not
    appear even in the top 60 candidates before this WO -- the calendar
    widget's own dated entries filled the top of the list instead."""
    page = _page(EMPORIA_HOME, "https://www.emporiaks.gov/", access_mode="wayback")
    hops = rank_hops(page, limit=10)
    assert hops, "expected ranked hops"
    top3_urls = [h.url for h in hops[:3]]
    assert any(u.endswith("/1300") for u in top3_urls), top3_urls
    assert hops[0].url.endswith("/1300")


def test_dublin_homepage_still_ranks_its_own_real_hub_link_first():
    """Dublin's own top nav item survives via ordinary path-token
    scoring (its path carries real words) -- confirmed unaffected by the
    nav-hub-label rescue, which only ever applies when the normal scorer
    found nothing at all."""
    page = _page(DUBLIN_HOME, "https://dublin.ca.gov/")
    hops = rank_hops(page, limit=5)
    assert (
        hops[0].url
        == "https://dublin.ca.gov/1604/Meetings-Agendas-Minutes-Video-on-Demand"
    )


# --- Item 2: calendar events must not crowd out hub links. -------------


def test_is_calendar_entry_link_matches_real_emporia_and_dublin_shapes():
    assert _is_calendar_entry_link("https://www.emporiaks.gov/Calendar.aspx?EID=2497")
    assert _is_calendar_entry_link(
        "https://www.emporiaks.gov/calendar.aspx?view=list&year=2026&month=9&day=12"
    )
    assert _is_calendar_entry_link("https://dublin.ca.gov/m/calendar/event/detail/7874")
    assert not _is_calendar_entry_link("https://dublin.ca.gov/1604/Meetings-Agendas")


def test_dublin_homepage_top10_has_no_more_than_two_calendar_entries():
    """Before this WO, Dublin's homepage top 10 included THREE separate
    community calendar events ranked #2, #5, #6, #7 (a real Council
    meeting, but also "Night Market at St. Pat's Row" and "Senior Info
    Fair", both non-meeting community events that merely have a date)."""
    page = _page(DUBLIN_HOME, "https://dublin.ca.gov/")
    hops = rank_hops(page, limit=10)
    calendar_hits = [h for h in hops if _is_calendar_entry_link(h.url)]
    assert len(calendar_hits) <= 2, [h.url for h in calendar_hits]


def test_emporia_homepage_top10_has_no_calendar_entry_shapes_at_all():
    """Before this WO, Emporia's homepage top 10 was ENTIRELY
    calendar.aspx EID/day-view links -- confirmed by re-running the
    unmodified (pre-WO-1033) scorer against this same fixture."""
    page = _page(EMPORIA_HOME, "https://www.emporiaks.gov/", access_mode="wayback")
    hops = rank_hops(page, limit=10)
    calendar_hits = [h for h in hops if _is_calendar_entry_link(h.url)]
    assert len(calendar_hits) <= 2, [h.url for h in calendar_hits]


def test_calendar_entries_are_capped_not_dropped():
    """The cap only limits how many make the TOP candidates -- a wider
    scan still finds them (`find_calendar_entry_links()`'s own one-hop-
    into-a-calendar role is untouched)."""
    page = _page(EMPORIA_HOME, "https://www.emporiaks.gov/", access_mode="wayback")
    hops = rank_hops(page, limit=30)
    calendar_hits = [h for h in hops if _is_calendar_entry_link(h.url)]
    assert len(calendar_hits) == 2


# --- Item 3: prefer_video gives a real, measured boost. -----------------


def test_prefer_video_boosts_dublins_real_watch_meetings_link():
    page = _page(
        DUBLIN_1604,
        "https://dublin.ca.gov/1604/Meetings-Agendas-Minutes-Video-on-Demand",
    )
    watch_url = "https://dublin.ca.gov/2875/Watch-Meetings"

    without = {h.url: h.score for h in rank_hops(page, limit=15)}
    with_pref = {h.url: h.score for h in rank_hops(page, limit=15, prefer_video=True)}

    assert watch_url in without and watch_url in with_pref
    assert with_pref[watch_url] > without[watch_url]
    # A real, clear boost, not a rounding nudge.
    assert with_pref[watch_url] - without[watch_url] >= 5.0


# --- Item 4: a same-site social redirect (CivicPlus's own "/youtube")
# is never offered as a hop. ---------------------------------------------


def test_same_site_social_redirect_recognized():
    assert _is_same_site_social_redirect(
        "https://www.emporiaks.gov/youtube", "www.emporiaks.gov"
    )
    assert _is_same_site_social_redirect(
        "https://www.emporiaks.gov/facebook", "www.emporiaks.gov"
    )
    assert not _is_same_site_social_redirect(
        "https://www.youtube.com/channel/xyz", "www.emporiaks.gov"
    )
    assert not _is_same_site_social_redirect(
        "https://www.emporiaks.gov/youtube-videos", "www.emporiaks.gov"
    )


def test_emporia_homepage_never_ranks_the_youtube_redirect_button():
    page = _page(EMPORIA_HOME, "https://www.emporiaks.gov/", access_mode="wayback")
    hops = rank_hops(page, limit=60)
    assert not any(h.url.endswith("/youtube") for h in hops)


# --- Item 5: canonical_page_key collapses same-page calendar params. ----


def test_canonical_page_key_collapses_real_emporia_calendar_param_variants():
    a = "https://www.emporiaks.gov/Calendar.aspx?EID=2662"
    b = "https://www.emporiaks.gov/calendar.aspx?PREVIEW=YES&EID=2662"
    c = "https://www.emporiaks.gov/Calendar.aspx?EID=2662&month=9&year=2026&day=23&calType=0"
    assert canonical_page_key(a) == canonical_page_key(b) == canonical_page_key(c)


def test_canonical_page_key_keeps_different_eids_distinct():
    a = "https://www.emporiaks.gov/Calendar.aspx?EID=2662"
    b = "https://www.emporiaks.gov/Calendar.aspx?EID=2497"
    assert canonical_page_key(a) != canonical_page_key(b)


def test_canonical_page_key_normalizes_trailing_slash_and_case():
    a = "https://Dublin.ca.gov/1604/Meetings/"
    b = "https://dublin.ca.gov/1604/Meetings"
    assert canonical_page_key(a) == canonical_page_key(b)


# --- Scan item 1: news/signup/ordinary-calendar-event false positives. --


def test_dublin_homepage_meeting_page_links_exclude_news_and_calendar_noise():
    """Before this WO, Dublin's homepage meeting-page-link scan surfaced
    CivicAlerts.aspx press releases, a "Stay Informed" signup page, and
    two ordinary community calendar events ("Night Market at St. Pat's
    Row", "Senior Info Fair") alongside the one real meeting. After: only
    the real "Regular City Council Meeting" survives."""
    hits = find_meeting_page_links(DUBLIN_HOME, "https://dublin.ca.gov/", limit=15)
    urls = [u for u, _d, _t in hits]
    titles = [t for _u, _d, t in hits]
    assert not any("civicalerts" in u.lower() for u in urls), urls
    assert not any("list.aspx" in u.lower() for u in urls), urls
    assert not any(t and "night market" in t.lower() for t in titles), titles
    assert not any(t and "senior info fair" in t.lower() for t in titles), titles
    assert any(t and "regular city council meeting" in t.lower() for t in titles), (
        titles
    )


def test_emporia_homepage_meeting_page_links_exclude_calendar_noise():
    hits = find_meeting_page_links(EMPORIA_HOME, "https://www.emporiaks.gov/", limit=15)
    titles = [t for _u, _d, t in hits]
    urls = [u for u, _d, _t in hits]
    # The real "Commission Meeting" entry (EID=2497) is a governing-body
    # meeting and must survive; the two municipal-court-docket and one
    # "Absurdly Small Big Band" calendar entries (EID=2706/2709/2710,
    # none of which name a governing body) must not.
    assert any(t and "commission meeting" in t.lower() for t in titles), titles
    assert not any(t and "big band" in t.lower() for t in titles), titles
    assert not any("eid=2706" in u.lower() for u in urls), urls


def test_civic_alerts_press_release_never_a_meeting_page_even_with_council_words():
    html = """
    <html><body>
    <a href="/CivicAlerts.aspx?AID=9001">City Council Responds to Special
    Election Call</a>
    </body></html>
    """
    hits = find_meeting_page_links(html, "https://example.gov/", limit=5)
    assert hits == []


def test_govdelivery_signup_page_never_a_meeting_page():
    html = """
    <html><body>
    <a href="https://public.govdelivery.com/accounts/EXAMPLE/subscribers/new">
    Stay Informed</a>
    <a href="/list.aspx">Sign up for city council meeting notices</a>
    </body></html>
    """
    hits = find_meeting_page_links(html, "https://example.gov/", limit=5)
    assert hits == []


def test_calendar_event_without_governing_body_words_is_not_a_meeting_page():
    html = """
    <html><body>
    <a href="/m/calendar/event/detail/8013">Senior Info Fair -
    September 23, 2026</a>
    <a href="/m/calendar/event/detail/8014">Regular City Council Meeting
    - September 23, 2026</a>
    </body></html>
    """
    hits = find_meeting_page_links(html, "https://example.gov/", limit=5)
    urls = [u for u, _d, _t in hits]
    assert not any("8013" in u for u in urls), urls
    assert any("8014" in u for u in urls), urls


# --- Scan item 4: a same-site YouTube redirect is a YouTube lead. -------


def test_emporia_homepage_youtube_button_becomes_a_lead():
    leads = _youtube_leads(EMPORIA_HOME, "https://www.emporiaks.gov/")
    assert any(lead["url"].endswith("/youtube") for lead in leads)
    redirect_lead = next(lead for lead in leads if lead["url"].endswith("/youtube"))
    assert redirect_lead["video_id"] is None


def test_emporia_city_commission_page_youtube_link_becomes_a_lead():
    """Ryan's own real ground truth: `/1310/City-Commission` links only
    `href="/youtube"` -- no direct video of its own."""
    leads = _youtube_leads(
        EMPORIA_1310, "https://www.emporiaks.gov/1310/City-Commission"
    )
    assert any(lead["url"].endswith("/youtube") for lead in leads)


def test_same_site_youtube_redirect_never_becomes_a_meeting_page_link():
    hits = find_meeting_page_links(
        EMPORIA_1310, "https://www.emporiaks.gov/1310/City-Commission", limit=15
    )
    assert not any(u.endswith("/youtube") for u, _d, _t in hits)


def test_youtube_redirect_on_a_different_host_is_not_a_lead():
    html = '<html><body><a href="https://example.gov/youtube">YouTube</a></body></html>'
    leads = _youtube_leads(html, "https://other.gov/")
    assert leads == []
