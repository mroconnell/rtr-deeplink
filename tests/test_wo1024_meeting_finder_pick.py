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


def test_declines_rather_than_guessing_when_nothing_looks_clean():
    candidates = [
        {"title": "Promo video", "date": _iso(1), "url": "https://x/1"},
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert picked == []
    assert "ambiguous" in reason or reason


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


def test_minutes_link_is_never_picked():
    """A link whose own title says "minutes" is a document, not a
    meeting recording -- conductor feedback, 2026-09-23."""
    candidates = [
        {
            "title": "City Council Meeting Minutes",
            "date": _iso(1),
            "url": "https://x/1",
        },
    ]
    picked, reason = pick_calendar_candidates(candidates)
    assert picked == []


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
