"""WO-1037: Cablecast/Swagit calibration-run fixes to Meeting Finder's
Hop, Scan and Fetch phases (`app/platforms/meeting_finder/hop.py`,
`scan.py`, `fetch.py`).

Eight diagnosis agents traced 37 real Cablecast/Swagit calibration
misses (see `docs/MEETING_FINDER.md` and this WO's own BACKLOG_DONE.md
entry for the full writeup); this file has one regression test per item
in that brief. Every anchor text/href below is a REAL, confirmed shape
from a named real government -- "King County TV (KCTV)" was re-fetched
live from `https://www.kingcounty.gov/council` while building this fix
(real href: `/en/independents/about-king-county/king-county-tv`) -- but
each test builds a small SYNTHETIC page around that real fragment
(CLAUDE.md's synthetic-test rule: reusing a real shape, not inventing
one, and said so here) rather than saving a full real page, since only
one specific link on a large real homepage is under test.
"""

from __future__ import annotations

from app.platforms.meeting_finder.fetch import FetchResult, _has_no_useful_link_evidence
from app.platforms.meeting_finder.hop import (
    _is_calendar_entry_link,
    _looks_like_nav_hub_label,
    rank_hops,
)
from app.platforms.meeting_finder.scan import find_meeting_page_links


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


# --- Item 1: TV/cable vocabulary + one-brand-token label rescue. --------


def test_king_county_tv_kctv_label_is_accepted():
    # Real anchor text/href confirmed live on kingcounty.gov/council.
    assert _looks_like_nav_hub_label("King County TV (KCTV)") is True


def test_watch_tvctv_label_is_accepted():
    # Real Tigard OR nav label (per WO-1037 diagnosis, cablecast1 group).
    assert _looks_like_nav_hub_label("Watch TVCTV") is True


def test_mcfarland_cable_label_is_accepted():
    # Real McFarland WI homepage tile text (cablecast1 group).
    assert _looks_like_nav_hub_label("McFarland Cable") is True


def test_still_rejects_prose_with_more_than_one_non_vocab_word():
    # Same real CivicAlerts.aspx-shaped false positive test_wo1033 already
    # pins -- five non-vocabulary words, well past the one-brand-token
    # allowance.
    assert (
        _looks_like_nav_hub_label("City Council Meeting Rescheduled for Next Week")
        is False
    )


def test_king_county_tv_link_ranks_as_a_real_hop_candidate():
    html = """
    <html><body><nav>
      <a href="/en/shared-topics/about-king-county/departments">Departments</a>
      <a href="/en/independents/about-king-county/king-county-tv">King County TV (KCTV)</a>
    </nav></body></html>
    """
    page = _page(html, "https://www.kingcounty.gov/council")
    hops = rank_hops(page)
    urls = [h.url for h in hops]
    assert (
        "https://www.kingcounty.gov/en/independents/about-king-county/king-county-tv"
        in urls
    )


# --- Item 2: rank_hops scans iframe/embed src, not just <a href>. -------


def test_rank_hops_ranks_a_video_iframe_as_a_candidate():
    # Fontana USD CA shape: a Swagit iframe embed alongside an agenda-only
    # anchor -- the iframe itself must be offered as a hop candidate.
    html = """
    <html><body>
      <iframe src="https://fontanausdca.new.swagit.com/views/602"></iframe>
      <a href="https://fontanausdca.civicweb.net/portal/">Agendas</a>
    </body></html>
    """
    page = _page(html, "https://www.fusd.net/live-board-meeting")
    hops = rank_hops(page)
    urls = [h.url for h in hops]
    assert "https://fontanausdca.new.swagit.com/views/602" in urls


# --- Item 3: "Meeting Video"/"Watch Meetings"/"Meeting Recordings" get
# the hub bonus even when the weighted scorer already scored something. --


def test_meeting_video_label_beats_a_plain_agenda_link():
    # Real Johnson County TX shape: "Meeting Video" scores ~8 from
    # ordinary path vocabulary alone and used to lose to a generic
    # agendas/minutes link scoring higher.
    html = """
    <html><body><nav>
      <a href="/commissioners-court/public-information/meeting-video">Meeting Video</a>
      <a href="/commissioners-court/agendas-and-minutes">Agendas and Minutes</a>
    </nav></body></html>
    """
    page = _page(html, "https://www.co.johnson.tx.us/")
    hops = rank_hops(page)
    assert hops, "expected at least one ranked candidate"
    assert "meeting-video" in hops[0].url


def test_meeting_recordings_label_is_a_nav_hub_label():
    assert _looks_like_nav_hub_label("Meeting Recordings") is True


# --- Item 4: per-date agenda pages crowd like calendar entries. ---------


def test_per_date_agenda_page_is_treated_as_a_calendar_entry():
    # Real Des Plaines IL shape.
    url = (
        "https://www.desplaines.org/Agendas-and-Minutes/2026/"
        "City-Council/11-02-2026-City-Council-Meeting"
    )
    assert _is_calendar_entry_link(url) is True


def test_per_date_agenda_pages_are_capped_in_top_candidates():
    base = "https://www.desplaines.org"
    dated_links = "\n".join(
        f'<a href="{base}/Agendas-and-Minutes/2026/City-Council/'
        f'{month:02d}-02-2026-City-Council-Meeting">Council Meeting {month}/2/2026</a>'
        for month in range(1, 8)
    )
    html = f"""
    <html><body><nav>
      {dated_links}
      <a href="{base}/?site=6">Watch Meetings</a>
    </nav></body></html>
    """
    page = _page(html, base + "/Your-Government/City-Council")
    hops = rank_hops(page, limit=8)
    dated = [h for h in hops if "City-Council-Meeting" in h.url]
    assert len(dated) <= 2


# --- Item 5: host_recognition fallback for a bare vendor tenant root. ---


def test_bare_cablecast_tenant_root_is_recognized_via_host_fallback():
    # Real Des Plaines IL / Niagara Falls SD NY shape: a bare tenant root
    # with no show/gallery path -- detect_platform() alone says "unknown".
    html = """
    <html><body><nav>
      <a href="https://desplainesil.cablecast.tv/?site=6">on-demand</a>
      <a href="/Agendas-and-Minutes/2026/City-Council/11-02-2026-City-Council-Meeting">
        11/2/2026 City Council Meeting
      </a>
    </nav></body></html>
    """
    page = _page(html, "https://www.desplaines.org/Your-Government/City-Council")
    hops = rank_hops(page)
    urls = [h.url for h in hops]
    assert "https://desplainesil.cablecast.tv/?site=6" in urls
    top = next(h for h in hops if h.url == "https://desplainesil.cablecast.tv/?site=6")
    assert "vendor-host link" in top.reason


# --- Item 6: scan.py only opens the government's own site or a
# recognized vendor -- no Facebook permalinks, no unrelated third-party
# domains. -----------------------------------------------------------


def test_find_meeting_page_links_skips_facebook_permalink():
    # Real James Island SC shape: a Facebook permalink sits next to the
    # real Swagit iframe and also carries meeting-shaped anchor text.
    html = """
    <html><body>
      <a href="https://www.facebook.com/JamesIslandSC/posts/123456">
        Town Council Meeting 9/2/2026
      </a>
      <a href="/agendas/city-council-2026-09-02">City Council Agenda</a>
    </body></html>
    """
    hits = find_meeting_page_links(html, "https://www.jamesislandsc.us/livestream")
    urls = [url for url, _date, _title in hits]
    assert not any("facebook.com" in u for u in urls)
    assert any("agendas/city-council" in u for u in urls)


def test_find_meeting_page_links_skips_unrelated_third_party_domain():
    # Real Cecil County PS MD shape: a usgbc.org (green-building
    # certification) link sits on the same page as the real meeting link.
    html = """
    <html><body>
      <a href="https://www.usgbc.org/leed">LEED Certified</a>
      <a href="/board/meeting-2026-09-02">Board Meeting 9/2/2026</a>
    </body></html>
    """
    hits = find_meeting_page_links(html, "https://www.ccpsmd.org/board")
    urls = [url for url, _date, _title in hits]
    assert not any("usgbc.org" in u for u in urls)
    assert any("board/meeting" in u for u in urls)


def test_find_meeting_page_links_keeps_a_recognized_vendor_link():
    # A recognized meeting vendor is still allowed even though it's a
    # different host from the government's own site.
    html = """
    <html><body>
      <a href="https://ccpsmd.new.swagit.com/views/647">
        Board Meeting Live Feed and Recordings 9/2/2026
      </a>
    </body></html>
    """
    hits = find_meeting_page_links(html, "https://www.ccpsmd.org/board")
    urls = [url for url, _date, _title in hits]
    assert any("ccpsmd.new.swagit.com" in u for u in urls)


# --- Item 7: fetch's headless gate widens beyond "zero links". ----------


def test_no_useful_link_evidence_true_for_escaped_anchor_in_json_blob():
    # Real Aiken County SD SC / Sherwood AR shape: plenty of ordinary
    # utility <a href> links, but the real nav is JSON-hydrated (its HTML
    # markup appears only as an escaped string).
    utility_links = "".join(f'<a href="/util-{i}">Util {i}</a>' for i in range(20))
    html = (
        "<html><body>"
        + utility_links
        + "<script>var hydration = "
        + '"&lt;a href=\\"/page/school-board\\"&gt;'
        + 'Watch Live &amp; Archived Meeting Video&lt;/a&gt;";'
        + "</script></body></html>"
    )
    assert _has_no_useful_link_evidence(html) is True


def test_no_useful_link_evidence_true_for_unparsed_vendor_hostname():
    # Real Chesterfield County PS VA shape: swagit.com is named in the
    # raw markup (a JSON config blob) but never shows up as a real
    # parsed href/src -- ordinary utility <a href> links are still there.
    html = (
        "<html><body>"
        + "".join(f'<a href="/util-{i}">Util {i}</a>' for i in range(20))
        + '<script>var cfg = {"account": "chesterfieldschoolsva.swagit.com"};</script>'
        "</body></html>"
    )
    assert _has_no_useful_link_evidence(html) is True


def test_no_useful_link_evidence_false_for_an_ordinary_page():
    html = '<html><body><a href="/agendas">Agendas</a></body></html>'
    assert _has_no_useful_link_evidence(html) is False


def test_no_useful_link_evidence_false_when_vendor_host_is_a_real_link():
    # The vendor host DOES show up as a real parsed href -- not a
    # JS-hydrated-nav case, should not force headless.
    html = (
        '<html><body><a href="/agendas">Agendas</a>'
        '<a href="https://ccpsmd.new.swagit.com/views/647">Watch</a></body></html>'
    )
    assert _has_no_useful_link_evidence(html) is False


# --- Item 8: an off-site TV/cable/community-television station link is
# a valid one-hop candidate; on a shared hub, prefer a link naming this
# government. --------------------------------------------------------


def test_offsite_community_television_org_link_ranks_as_a_hop():
    # Real Lake Oswego OR shape: "Tualatin Valley Community Television"
    # links off-site to tvctv.org, carrying no ordinary hub vocabulary at
    # all (it's a station's own proper name).
    html = """
    <html><body>
      <a href="https://tvctv.org/lake-oswego">
        Tualatin Valley Community Television
      </a>
    </body></html>
    """
    page = _page(html, "https://www.ci.oswego.or.us/citycouncil/meeting-2026-09-02")
    hops = rank_hops(page)
    urls = [h.url for h in hops]
    assert "https://tvctv.org/lake-oswego" in urls


def test_shared_hub_prefers_the_link_naming_this_government():
    # Real Bismarck ND shape: a shared Dakota Media Access hub links
    # several nearby cities; the government's own link should outrank a
    # sibling naming a different city, given the government's real name.
    html = """
    <html><body>
      <a href="https://dakotamediaaccess.org/programs/show/lincoln-city-council/">
        Lincoln City Council
      </a>
      <a href="https://dakotamediaaccess.org/programs/show/bismarck-city-commission/">
        Bismarck City Commission
      </a>
    </body></html>
    """
    page = _page(html, "https://dakotamediaaccess.org/watch/")
    hops = rank_hops(page, gov_name="Bismarck")
    assert hops, "expected at least one ranked candidate"
    assert "bismarck" in hops[0].url
