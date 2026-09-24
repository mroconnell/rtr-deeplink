"""WO-1024: app/platforms/meeting_finder/pick.py -- the one picking rule,
moved from scripts/wo134_confirmed_hits_ingest.py, plus the conductor's
2026-09-23 additions (test/demo/minutes filtering, governing-body
preference on a same-day tie). Titles marked SYNTHETIC below are
hand-built rows exercising one branch each, per CLAUDE.md's synthetic-
test rules -- but the TITLES themselves are real, confirmed strings the
conductor cited from rtr-upcoming's UPCOMING_AGENDAS_FIELD_GUIDE.md
(Fremont's Granicus demo tenant, Marin County's PrimeGov "DO NOT USE"
row), not invented.
"""

from datetime import datetime, timedelta, timezone

from app.platforms.meeting_finder.models import Candidate
from app.platforms.meeting_finder.pick import (
    pick_calendar_candidates,
    pick_candidates,
    parse_candidate_date,
)

TODAY = datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _future_iso(days_ahead: int) -> str:
    return (TODAY + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def test_parse_candidate_date_formats():
    assert parse_candidate_date("2026-09-08") == datetime(2026, 9, 8)
    assert parse_candidate_date("Sep 08, 2026") == datetime(2026, 9, 8)
    assert parse_candidate_date("September 08, 2026") == datetime(2026, 9, 8)
    assert parse_candidate_date("09/08/2026") == datetime(2026, 9, 8)
    assert parse_candidate_date("") is None
    assert parse_candidate_date(None) is None
    assert parse_candidate_date("not a date") is None


def test_picks_newest_clean_meeting_first():
    candidates = [
        {"title": "City Council Meeting", "date": _iso(10), "url": "https://x/1"},
        {"title": "City Council Meeting", "date": _iso(1), "url": "https://x/2"},
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert reason == ""
    assert [c["url"] for c in picked] == ["https://x/2", "https://x/1"]


def test_weak_title_is_kept_despite_when_nothing_else_looks_clean():
    """WO-1035 (Ryan's rule): a step that would otherwise reject every
    candidate keeps the best one instead. A single weak-looking title is
    now DEMOTED, not dropped -- pick.py still returns it, with a reason
    saying so, rather than reporting "ambiguous" while a real (if
    unconfirmed) candidate exists."""
    candidates = [
        {"title": "Promo video", "date": _iso(1), "url": "https://x/1"},
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert [c["url"] for c in picked] == ["https://x/1"]
    assert "weak title kept" in reason


def test_ambiguous_only_when_nothing_survives_at_all():
    """ "ambiguous" is reserved for the one case nothing can be done about:
    every candidate was a test/demo-tenant title, so nothing real is left
    to fall back to."""
    candidates = [
        {
            "title": "TEST - CC - Livemeeting demo",
            "date": _iso(1),
            "url": "https://fremont.granicus.com/x",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert picked == []
    assert "ambiguous" in reason


def test_future_dated_candidate_is_excluded():
    """SYNTHETIC: exercises the existing dt <= today filter with a real
    confirmed shape (Marin County PrimeGov's "DO NOT USE - Cathy Test
    Meeting" row is dated 2035 per the conductor's citation) -- future
    dates are never real past meetings."""
    candidates = [
        {
            "title": "DO NOT USE - Cathy Test Meeting",
            "date": _future_iso(3000),
            "url": "https://marincounty.primegov.com/x",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert picked == []
    assert reason  # excluded either by the date filter or the test/demo marker


def test_test_demo_titles_are_never_picked_even_when_dated_in_the_past():
    """SYNTHETIC test exercising the new test/demo filter with the real,
    confirmed titles the conductor cited (2026-09-23, from rtr-upcoming's
    field guide): Fremont's Granicus tenant has real rows literally
    titled "TEST - CC - Livemeeting demo"; a demo tenant can backdate a
    row just as easily as it can post one dated in the far future, so the
    title marker must catch it even with an ordinary past date."""
    candidates = [
        {
            "title": "TEST - CC - Livemeeting demo",
            "date": _iso(1),
            "url": "https://fremont.granicus.com/x",
        },
        {
            "title": "DO NOT USE - Cathy Test Meeting",
            "date": _iso(2),
            "url": "https://marincounty.primegov.com/y",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert picked == []
    assert "ambiguous" in reason


def test_real_meeting_titled_test_is_still_accepted():
    """A real government's own meeting name that happens to start with
    "Test" (an existing fixture title used across this repo's tests,
    e.g. tests/test_wo222_gov_id_ingest_payload.py) must not be caught by
    the new test/demo marker -- it's deliberately narrower than a bare
    "test" word."""
    candidates = [
        {"title": "Test City Council Meeting", "date": _iso(1), "url": "https://x/1"},
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert reason == ""
    assert [c["url"] for c in picked] == ["https://x/1"]


def test_minutes_link_is_ranked_below_a_real_meeting_candidate():
    """A link whose own title says "minutes" is a document, not a
    meeting recording -- conductor feedback, 2026-09-23 -- so it's
    demoted below a real meeting candidate rather than picked first."""
    candidates = [
        {
            "title": "City Council Meeting Minutes",
            "date": _iso(1),
            "url": "https://x/minutes",
        },
        {
            "title": "City Council Meeting",
            "date": _iso(2),
            "url": "https://x/meeting",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert [c["url"] for c in picked] == ["https://x/meeting", "https://x/minutes"]


def test_minutes_link_is_kept_when_it_is_the_only_candidate():
    """WO-1035: even a minutes-only candidate is kept as a last resort
    rather than returning nothing (Ryan's "keep at least one" rule)."""
    candidates = [
        {
            "title": "City Council Meeting Minutes",
            "date": _iso(1),
            "url": "https://x/1",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert [c["url"] for c in picked] == ["https://x/1"]


def test_governing_body_preferred_on_a_same_day_tie():
    """Conductor feedback, 2026-09-23, citing rtr-upcoming's field guide:
    Tiburon's "Heritage & Arts Only" filtered view had MORE items than
    the view carrying Town Council -- volume alone points the wrong way.
    SYNTHETIC: two candidates dated the same real day, one from a
    governing body, one from a lesser committee; the governing body one
    must be preferred when the dates tie."""
    same_day = _iso(1)
    candidates = [
        {
            "title": "Heritage & Arts Only",
            "date": same_day,
            "url": "https://x/heritage",
        },
        {
            "title": "Town Council Meeting",
            "date": same_day,
            "url": "https://x/council",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert reason == ""
    assert picked[0]["url"] == "https://x/council"


def test_governing_body_tiebreak_does_not_reorder_different_dates():
    """The governing-body preference is a same-day TIE-BREAK only --
    date order always wins first, same as before this change."""
    candidates = [
        {
            "title": "Heritage & Arts Commission Meeting",
            "date": _iso(1),
            "url": "https://x/newer",
        },
        {"title": "Town Council Meeting", "date": _iso(5), "url": "https://x/older"},
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert [c["url"] for c in picked] == ["https://x/newer", "https://x/older"]


def test_parse_candidate_date_two_digit_year():
    """cablecast2 report (2026-09-23): real Cablecast/Remix tenants put
    the meeting date in the DATE field as e.g. "9/22/26"."""
    assert parse_candidate_date("9/22/26") == datetime(2026, 9, 22)


def test_undated_candidates_kept_in_lister_order_not_dropped():
    """Champaign IL / Glendora CA (cablecast2 report, 2026-09-23): every
    real candidate's date field was unparseable. WO-1035's rule: date
    orders, it never eliminates -- undated candidates are kept, in the
    order the lister handed them over (walkers list newest-first)."""
    candidates = [
        {"title": "City Council Meeting", "date": None, "url": "https://x/newest"},
        {"title": "City Council Meeting", "date": None, "url": "https://x/older"},
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert [c["url"] for c in picked] == ["https://x/newest", "https://x/older"]
    assert "picked by: undated, lister order" in reason


def test_date_extracted_from_title_when_date_field_is_blank():
    """Redlands CA (cablecast4 report, 2026-09-23): a Remix title like
    "City Council Special Meeting September 21, 2026" carries the real
    date in the TITLE, with the structured date field blank."""
    candidates = [
        {
            "title": "City Council Special Meeting September 21, 2026",
            "date": "",
            "url": "https://x/1",
        },
        {
            "title": "City Council Meeting - 9/22/26",
            "date": "",
            "url": "https://x/2",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    # Both dates parse from the title; 9/22/26 is newer than Sep 21, 2026.
    assert [c["url"] for c in picked] == ["https://x/2", "https://x/1"]
    assert reason == ""


def test_dated_real_candidate_beats_undated_and_future_dated():
    """The three-bucket order (recent dated -> undated -> future-dated)
    holds even when an undated or future-dated candidate would otherwise
    look fine."""
    candidates = [
        {
            "title": "City Council Meeting",
            "date": _future_iso(5),
            "url": "https://x/future",
        },
        {"title": "City Council Meeting", "date": None, "url": "https://x/undated"},
        {"title": "City Council Meeting", "date": _iso(2), "url": "https://x/dated"},
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert [c["url"] for c in picked] == [
        "https://x/dated",
        "https://x/undated",
        "https://x/future",
    ]


def test_pick_candidates_same_rule_on_candidate_dataclass():
    candidates = [
        Candidate(url="https://x/1", title="City Council Meeting", date=_iso(5)),
        Candidate(url="https://x/2", title="City Council Meeting", date=_iso(1)),
        Candidate(
            url="https://x/3", title="TEST - CC - Livemeeting demo", date=_iso(2)
        ),
    ]
    picked, reason = pick_candidates(candidates)
    assert reason == ""
    assert [c.url for c in picked] == ["https://x/2", "https://x/1"]
