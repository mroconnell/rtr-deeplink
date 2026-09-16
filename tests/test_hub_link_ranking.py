"""Tests for WO-228's scored, ranked `find_hop_links()` plus its
`looks_like_document_hub()`/`find_calendar_entry_links()` helpers in
`scripts/wo147_access_ladder_sweep.py`.

**WO-274 (2026-09-12) note**: `find_hop_links()`'s DEFAULT scoring is now
the measured, re-weighted scorer (`legacy=False`, the new default) --
see `tests/test_hop_scorer_weighted.py` and
`docs/investigations/hop_scorer_measurement.md` for that scorer's own
tests and the before/after measurement. Every `find_hop_links()` call in
THIS file now passes `legacy=True` explicitly, so this file keeps
testing the exact WO-228 word-list scorer it was written for (a real,
useful historical/comparison record), rather than silently starting to
test a different scorer than the one its own docstrings describe.
`looks_like_document_hub()`/`find_calendar_entry_links()` are unrelated
to hop-link scoring and are untouched by WO-274.

Every fixture in `tests/fixtures/wo228_hub_ranking/` is a REAL page saved
from a live fetch on 2026-09-11 (not hand-built), per CLAUDE.md's rule
that a new adapter/heuristic is built and tested against real samples
first:

- The four named spot-check governments Ryan flagged with a wrong
  recorded hub (`madison_county_tn_home.html`, `littleton_co_home.html`,
  `atlantic_city_nj_home.html`, `mcleod_county_mn_home.html`) -- their
  real homepages, fetched live. The OLD first-match `find_hop_links()`
  is what led each of these to a calendar/index page instead of the real
  agenda/video hub; the ranked version must put the real hub above it.
- Two positives per major platform family, drawn from
  `research/wo228_positive_links.csv` (itself built from
  `wo148_report.csv`/`wo184_report.csv` real "no platform link found ->
  real hit" rows): civicclerk (Warrenton OR, Yachats OR), civicplus
  (South Congaree SC, Waukee IA), civicweb (Delavan WI, Union Grove WI),
  iqm2 (Somervell County TX, Mosinee WI), legistar (Tehama County CA,
  Cleveland County OK), vimeo (McLeansboro IL, Lavon TX), swagit
  (Larchmont NY).

See `research/wo228_report.csv` and this WO's ENUMERATION_METHODS.md
section for the full study (90 positives, 60 negative calendar-shaped
hubs) the weights below come from.
"""

from __future__ import annotations

import os

import pytest

from scripts.wo147_access_ladder_sweep import (
    find_calendar_entry_links,
    find_hop_links,
    find_platform_link,
    looks_like_document_hub,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo228_hub_ranking")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def _top(html: str, url: str, n: int = 3):
    return find_hop_links(html, url, legacy=True)[:n]


# --- The four named spot-check governments: the real hub must rank
# above the old wrongly-recorded calendar/index page. ---


def test_madison_county_tn_ranks_a_real_committee_entry_above_the_bare_calendar():
    html = _load("madison_county_tn_home.html")
    top3 = _top(html, "https://madisoncountytn.gov/")
    # Real anchor text behind these three (confirmed live): "Agenda
    # Review", "Personnel Committee", "Excess Resale Real Estate
    # Property Committee" -- individual dated committee-meeting entries,
    # not the bare CID= list-view calendar Ryan's spot-check flagged
    # (madisoncountytn.gov/calendar.aspx?CID=... with no EID).
    assert top3, "expected at least one ranked candidate"
    for url in top3:
        assert "EID=" in url, f"expected a dated entry in the top 3, got {url}"


def test_littleton_co_ranks_meeting_videos_agendas_above_city_calendars():
    html = _load("littleton_co_home.html")
    top3 = _top(html, "https://www.littletonco.gov/")
    assert any("Meeting-Videos-Agendas" in u for u in top3)
    ranked = find_hop_links(html, "https://www.littletonco.gov/", legacy=True)
    meeting_idx = next(i for i, u in enumerate(ranked) if "Meeting-Videos-Agendas" in u)
    calendar_idx = next(
        (i for i, u in enumerate(ranked) if "City-Calendars" in u), len(ranked)
    )
    assert meeting_idx < calendar_idx, (
        "the real Meeting-Videos-Agendas page must rank above City-Calendars, "
        "the page Ryan's spot-check flagged as the wrong recorded hub"
    )


def test_atlantic_city_nj_ranks_meetings_above_calendar():
    html = _load("atlantic_city_nj_home.html")
    ranked = find_hop_links(html, "https://acnj.gov/", legacy=True)
    meetings_idx = next(i for i, u in enumerate(ranked) if "meeting" in u.lower())
    calendar_idx = next(
        (i for i, u in enumerate(ranked) if "calendar" in u.lower()), len(ranked)
    )
    assert meetings_idx < calendar_idx, (
        "acnj.gov/meetings (or /Meetings) must rank above acnj.gov/calendar, "
        "the page Ryan's spot-check flagged as the wrong recorded hub"
    )


def test_atlantic_city_video_tag_fallback_text_is_not_a_candidate():
    """Real false positive caught building this WO's fixtures: an HTML5
    <video> tag's browser-fallback text ("Your browser does not support
    the video tag.") is itself wrapped in an <a> by this site's template
    and was outranking the real /meetings link before the boilerplate
    guard was added."""
    html = _load("atlantic_city_nj_home.html")
    ranked = find_hop_links(html, "https://acnj.gov/", legacy=True)
    assert not any("fishbowlmedia" in u for u in ranked)


def test_mcleod_county_mn_ranks_agendas_and_minutes_above_the_bare_board_index():
    html = _load("mcleod_county_mn_home.html")
    ranked = find_hop_links(html, "https://mcleodcountymn.gov/", legacy=True)
    agendas_idx = next(
        i for i, u in enumerate(ranked) if "agendas___minutes" in u.lower()
    )
    # McLeod County MN's own recorded (wrong) hub, per the spot-check:
    # https://mcleodcountymn.gov/government/county_board/index.php
    bare_index_idx = next(
        (
            i
            for i, u in enumerate(ranked)
            if u.rstrip("/").endswith("county_board/index.php")
        ),
        len(ranked),
    )
    assert agendas_idx < bare_index_idx
    assert agendas_idx < 3, "the real agendas & minutes page should rank in the top 3"


# --- Two positives per platform: the real hop candidate that led to a
# genuine hit (per wo228_positive_links.csv) must rank in the top 3. ---

POSITIVE_CASES = [
    (
        "warrenton_civicclerk_home.html",
        "https://www.warrentonoregon.us",
        "civicclerk.com",
    ),
    ("yachats_civicclerk_home.html", "https://yachatsoregon.org/", "civicclerk.com"),
    (
        "south_congaree_civicplus_home.html",
        "https://www.townofsouthcongaree.org",
        "agendacenter",
    ),
    ("waukee_civicplus_home.html", "https://www.waukee.org/", "agendacenter"),
    ("delavan_civicweb_home.html", "https://ci.delavan.wi.us/", "civicweb.net"),
    ("union_grove_civicweb_home.html", "https://www.uniongrovewi.gov/", "civicweb.net"),
    ("somervell_iqm2_home.html", "https://www.somervell.co", "iqm2.com"),
    ("mosinee_iqm2_home.html", "https://www.mosinee.wi.us/", "iqm2.com"),
    ("tehama_legistar_home.html", "https://www.tehama.gov/", "legistar.com"),
    (
        "cleveland_county_legistar_home.html",
        "https://clevelandcountyok.com/",
        "legistar.com",
    ),
    ("mcleansboro_vimeo_home.html", "https://mcleansboro.us/", "vimeo.com"),
    ("lavon_vimeo_home.html", "https://lavontx.gov/", "vimeo.com"),
    ("larchmont_swagit_home.html", "https://larchmontny.gov/", "swagit.com"),
]


@pytest.mark.parametrize("fixture,base_url,expect_hint", POSITIVE_CASES)
def test_positive_platform_hit_ranks_in_top_three(fixture, base_url, expect_hint):
    html = _load(fixture)
    top3 = _top(html, base_url)
    assert top3, f"expected candidates for {fixture}"
    assert any(expect_hint in u.lower() for u in top3), (
        f"expected a {expect_hint} link in the top 3 for {fixture}, got {top3}"
    )


def test_zoar_and_sidney_youtube_links_are_caught_by_find_platform_link_directly():
    """These two real positives never reach find_hop_links() in
    production at all: their homepage's own YouTube anchor (bare
    "Youtube"/"YouTube" text, no HOP1_HINT_WORDS match) is caught by
    find_platform_link()'s unconstrained anchor scan BEFORE
    find_hop_links() is ever invoked -- confirmed live building this
    WO's fixtures. Documented here as a real, checked architectural fact
    rather than silently assumed."""
    for fixture, base_url in [
        ("zoar_youtube_home.html", "https://historiczoarvillage.com/"),
        ("sidney_youtube_home.html", "http://sinistersidney.com/"),
    ]:
        html = _load(fixture)
        hit = find_platform_link(html, base_url)
        assert hit is not None and hit[0] == "youtube"


# --- Negative fixtures: a bare "calendar" candidate must never rank
# above a real agenda/minutes/meeting-video candidate on the same page. ---


def test_calendar_word_alone_never_outranks_agenda_minutes_when_both_present():
    # Yachats' homepage has both an agenda&minutes-shaped civicclerk link
    # and several bare CID= calendar list-view links; the platform link
    # must win.
    html = _load("yachats_civicclerk_home.html")
    ranked = find_hop_links(html, "https://yachatsoregon.org/", legacy=True)
    civicclerk_idx = next(i for i, u in enumerate(ranked) if "civicclerk.com" in u)
    bare_calendar_idxs = [
        i
        for i, u in enumerate(ranked)
        if "calendar.aspx" in u.lower() and "cid=" in u.lower()
    ]
    if bare_calendar_idxs:
        assert civicclerk_idx < min(bare_calendar_idxs)


# --- looks_like_document_hub() ---


def test_looks_like_document_hub_true_for_agendacenter_page():
    html = "<html><body><a href='/AgendaCenter/ViewFile/Item/123'>2026 Agenda</a></body></html>"
    assert looks_like_document_hub(html) is True


def test_looks_like_document_hub_true_for_pdf_link():
    html = (
        "<html><body><a href='/docs/minutes-2026-09-01.pdf'>Minutes</a></body></html>"
    )
    assert looks_like_document_hub(html) is True


def test_looks_like_document_hub_true_for_platform_host_present():
    html = "<html><body><a href='https://townofx.granicus.com/ViewPublisher.php?view_id=2'>Meetings</a></body></html>"
    assert looks_like_document_hub(html) is True


def test_looks_like_document_hub_false_for_a_thin_events_shell():
    # Real shape confirmed on Atlantic City NJ's own /calendar page while
    # building this WO's negative sample (research/wo228_negative_hubs.csv):
    # a plain-fetched calendar shell with no document/platform evidence at
    # all, because the real events load client-side after the fetch.
    html = "<html><body><div id='calendar-app'></div></body></html>"
    assert looks_like_document_hub(html) is False


# --- find_calendar_entry_links(): the one-hop-into-two-dated-entries step ---


def test_find_calendar_entry_links_finds_eid_shaped_entries_in_document_order():
    html = """
    <html><body>
      <a href="/Calendar.aspx?view=list&year=2026&month=9">Full Calendar</a>
      <a href="/Calendar.aspx?EID=3925">Personnel Committee</a>
      <a href="/Calendar.aspx?EID=3922">Excess Resale Real Estate Property Committee</a>
      <a href="/Calendar.aspx?EID=3926">Agenda Review</a>
    </body></html>
    """
    entries = find_calendar_entry_links(html, "https://example.gov/", limit=2)
    assert entries == [
        "https://example.gov/Calendar.aspx?EID=3925",
        "https://example.gov/Calendar.aspx?EID=3922",
    ]


def test_find_calendar_entry_links_real_madison_county_tn_fixture():
    html = _load("madison_county_tn_home.html")
    entries = find_calendar_entry_links(html, "https://madisoncountytn.gov/", limit=2)
    assert len(entries) == 2
    assert all("EID=" in e for e in entries)


def test_find_calendar_entry_links_empty_when_no_dated_entries():
    html = "<html><body><a href='/about'>About</a></body></html>"
    assert find_calendar_entry_links(html, "https://example.gov/") == []
