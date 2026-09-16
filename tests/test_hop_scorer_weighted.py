"""Tests for WO-274's re-weighted `find_hop_links()` default scorer
(`legacy=False`, `scripts/wo147_access_ladder_sweep.py`).

Why this file exists, separate from `tests/test_hub_link_ranking.py`:
that file pins the OLD WO-228 word-list scorer exactly (`legacy=True`
everywhere, see its own WO-274 note) as a historical/comparison record.
This file tests the scorer real traffic actually gets now.

Real-page fixtures are reused from `tests/fixtures/wo228_hub_ranking/`
(fetched live 2026-09-11, see that file's own docstring for exact
sources) rather than re-saved -- they are still real pages, and two of
them are the actual regression cases this WO found and fixed while
building the new scorer (see below). A few cases are minimal synthetic
HTML, each commented per CLAUDE.md's synthetic-test rule: used only to
exercise one already-measured logic branch (a nav/footer position
check, a plural-vs-singular weight comparison, a named-path bonus),
never to invent a payload shape that hasn't been confirmed against real
data -- every WORD used below is a real token from
`app/utils/jurisdiction_data/hop_link_weights.csv`, measured by
`scripts/derive_hop_weights.py` against real jurisdiction_coverage.csv/
Archive/WO-267 data (see `docs/investigations/hop_scorer_measurement.md`).
"""

from __future__ import annotations

import os

from scripts.wo147_access_ladder_sweep import find_hop_links

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo228_hub_ranking")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8", errors="replace") as f:
        return f.read()


# --- Real-data regressions this WO found and fixed while building the
# new scorer (both confirmed live against the fixtures below before the
# fix -- see derive_hop_weights.py's _STOPWORD_TOKENS comment and
# wo147_access_ladder_sweep.py's path-must-qualify comment for the root
# cause of each). ---


def test_madison_county_tn_prefers_dated_entries_over_bare_calendar_list():
    """Real regression caught building this scorer: `day=`/`month=`/
    `year=`/`CID=` query names leaked into the HUB positive vocabulary
    from OTHER governments' own (mis-recorded, calendar-shaped)
    `jurisdiction_coverage.csv` rows, which briefly made Madison County
    TN's bare `calendar.aspx?...CID=...` list view outscore its own real
    dated committee entries. Stoplisted in `derive_hop_weights.py`."""
    html = _load("madison_county_tn_home.html")
    top3 = find_hop_links(html, "https://madisoncountytn.gov/")[:3]
    assert top3, "expected at least one ranked candidate"
    for url in top3:
        assert "EID=" in url, f"expected a dated entry in the top 3, got {url}"


def test_cleveland_county_ranks_legistar_link_above_a_press_release():
    """Real regression: a CivicAlerts.aspx PRESS RELEASE headlined "Board
    of County Commissioners Response to Call for Special Election" is
    real prose rich in hub-anchor vocabulary (board/of/commissioners) but
    is a news item, not a meeting page. Fixed by requiring real PATH (or
    target-shape) evidence to qualify a candidate at all -- anchor-text
    vocabulary alone can no longer carry a link into the ranking."""
    html = _load("cleveland_county_legistar_home.html")
    top3 = find_hop_links(html, "https://clevelandcountyok.com/")[:3]
    assert any("legistar.com" in u for u in top3), (
        f"expected the real legistar.com link in the top 3, got {top3}"
    )
    assert not any("civicalerts" in u.lower() for u in top3), (
        f"a CivicAlerts press release should never outrank the real hub, got {top3}"
    )


def test_lavon_tx_ranks_the_real_vimeo_link_first():
    """Real case: the government's own homepage links a real Vimeo video
    ("Watch the Video") alongside several first-party nav pages
    (City Council, Boards & Commissions, Event Calendar) that individually
    score well on vocabulary alone. The target-shape bonus for a
    meeting-vendor host must be large enough to win regardless."""
    html = _load("lavon_vimeo_home.html")
    top3 = find_hop_links(html, "https://lavontx.gov/")[:3]
    assert top3[0] == "https://vimeo.com/461557381", top3


def test_littleton_co_top_three_are_all_meeting_or_council_pages():
    """The real named "Meeting-Videos-Agendas" page (the WO-228 test's own
    pick) ranks #4 here, not top-3 -- a real, acknowledged trade-off of
    a measured-vocabulary sum: "Citizens Guide to City Council Meetings"
    and "City Council Meetings" both contain MORE separately-weighted
    real vocabulary (city + council + meetings, plus the "city-council"
    bigram) than "Meeting Videos & Agendas" does (meeting + agendas, no
    "council" token at all), so they outscore it. All three of the
    actual top 3 are still genuine meeting/council pages, and none is
    the bare "City-Calendars" page WO-228's fixture-comment says Ryan's
    spot-check flagged as wrong -- see
    docs/investigations/hop_scorer_measurement.md's Littleton note for
    the full trade-off writeup."""
    html = _load("littleton_co_home.html")
    top3 = find_hop_links(html, "https://www.littletonco.gov/")[:3]
    assert len(top3) == 3
    for url in top3:
        low = url.lower()
        assert "city-calendars" not in low, (
            f"bare City-Calendars page should not rank top-3, got {top3}"
        )
        assert "council" in low or "meeting" in low or "youtube.com" in low, (
            f"expected a meeting/council/video page, got {url} in {top3}"
        )


# --- Synthetic, logic-isolating cases (real measured words, hand-built
# HTML -- see this file's own docstring for why that's fine here). ---


def test_plural_beats_singular_when_otherwise_identical():
    """ "agendas" (measured weight ~2.7, lift 15.5x) must outrank singular
    "agenda" (measured weight ~0.02, lift ~1.0x, i.e. noise) when the two
    links are otherwise identical in every other respect -- the central
    finding this WO was commissioned to fix (the OLD list treated both
    words the same, via a single substring gate on "agenda")."""
    html = """
    <html><body>
      <a href="/Agenda/2026-09-01">Agenda</a>
      <a href="/Agendas/2026-09-01">Agendas</a>
    </body></html>
    """
    ranked = find_hop_links(html, "https://example.gov/")
    agendas_idx = next(i for i, u in enumerate(ranked) if "/Agendas/" in u)
    agenda_idx = next(
        (i for i, u in enumerate(ranked) if u.endswith("/Agenda/2026-09-01")),
        len(ranked),
    )
    assert agendas_idx < agenda_idx, ranked


def test_named_firstparty_path_beats_a_bare_hint_word():
    """A named first-party platform path (AgendaCenter) must beat a
    generic single-word nav link (bare "Council") even though "council"
    also carries real positive weight on its own -- the target-shape
    bonus this WO added specifically for named paths/vendor hosts."""
    html = """
    <html><body>
      <a href="/Council">Council</a>
      <a href="/AgendaCenter">Agendas</a>
    </body></html>
    """
    ranked = find_hop_links(html, "https://example.gov/")
    assert ranked[0].endswith("/AgendaCenter"), ranked


def test_nav_position_beats_footer_when_vocabulary_is_identical():
    """Two links with IDENTICAL anchor text and path vocabulary
    ("Agendas & Minutes"/"agendas-minutes") -- only one is inside <nav>,
    the other inside <footer>. The nav one must rank first."""
    html = """
    <html><body>
      <footer><a href="/footer/agendas-minutes">Agendas &amp; Minutes</a></footer>
      <nav><a href="/nav/agendas-minutes">Agendas &amp; Minutes</a></nav>
    </body></html>
    """
    ranked = find_hop_links(html, "https://example.gov/")
    nav_idx = next(i for i, u in enumerate(ranked) if "/nav/" in u)
    footer_idx = next(i for i, u in enumerate(ranked) if "/footer/" in u)
    assert nav_idx < footer_idx, ranked


def test_old_hop1_word_list_would_have_dropped_this_real_signal_word():
    """ "supervisors" (real, measured hub vocabulary -- lift 9.4x) contains
    NONE of the 12 HOP1_HINT_WORDS as a substring (no "board of", no
    "commission", no "council", no "meeting", etc.), so the OLD scorer's
    gate would have excluded a link like this from the ranking ENTIRELY,
    regardless of score. The new default scorer has no such pre-filter --
    every anchor is scored, so a link like this is found at all."""
    html = "<html><body><a href='/Supervisors'>Supervisors</a></body></html>"
    ranked = find_hop_links(html, "https://example.gov/")
    assert ranked == ["https://example.gov/Supervisors"], ranked

    # Sanity check on the premise itself (not the new behavior): confirm
    # the OLD gate really would have dropped this exact text/href.
    from scripts.wo147_access_ladder_sweep import HOP1_HINT_WORDS

    hay = "supervisors /supervisors".lower()
    assert not any(w in hay for w in HOP1_HINT_WORDS), (
        "this fixture unexpectedly matches an old HOP1_HINT_WORDS entry -- "
        "it no longer isolates the gap this test documents"
    )
