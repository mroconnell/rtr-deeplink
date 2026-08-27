"""End-to-end coverage for the calendar-page hint chain: CalendarPageError's
jurisdiction_hint -> /api/resolve's calendar_page response -> (frontend,
not tested here -- see player.js's renderCalendarPage()/init()) ->
ResolveRequest's *_hint fields -> applied onto the picked candidate's own
result. Real, confirmed-live gap this closes: a CivicPlus tenant's own
subdomain already disambiguates its jurisdiction (e.g. "Westminster, MD"),
but the picked video's own platform can't on its own -- see
BACKLOG_DONE.md's 2026-08-27 CivicPlus entries and civicplus.py's
_jurisdiction_from_subdomain().
"""

import pytest
from fastapi.testclient import TestClient

import app.main
from app.platforms.base import register
from app.platforms.civicplus import CivicPlusAssetFinder
from app.platforms.granicus import GranicusAssetFinder
from app.platforms.youtube import YouTubeAssetFinder
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

client = TestClient(app.main.app)


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """/api/resolve runs every URL through url_guard's SSRF check (WO-5),
    which resolves the hostname for real -- the civicplus.com/youtube.com
    hosts used throughout this file are never actually fetched
    (mock_session intercepts session.get(); yt-dlp is monkeypatched
    separately per-test), so real DNS must never run here either. Same
    fixture as test_generic_fallback.py's own _fake_public_dns."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


def _register_platforms():
    register(CivicPlusAssetFinder())
    register(GranicusAssetFinder())
    register(YouTubeAssetFinder())


def test_calendar_page_response_carries_the_jurisdiction_hint():
    _register_platforms()
    url = "https://md-westminster.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_listing.html")
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        response = client.post("/api/resolve", json={"url": url})

    data = response.json()
    assert data["error"] == "calendar_page"
    assert data["jurisdiction_hint"] == "Westminster, MD"


def test_calendar_page_response_has_no_hint_when_the_adapter_has_none():
    # Legistar's Calendar.aspx (or any other adapter that hasn't been
    # taught a hint) should degrade to None, not error or omit the key --
    # the frontend's `data.jurisdiction_hint ? ... : ''` already handles a
    # falsy value fine (see player.js's renderCalendarPage()).
    _register_platforms()
    url = "https://example.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_listing.html")
    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        response = client.post("/api/resolve", json={"url": url})

    assert response.json()["jurisdiction_hint"] is None


def test_jurisdiction_hint_overrides_the_picked_candidates_own_guess(monkeypatch):
    # The real incident: YouTube's own channel-name guess for "City of
    # Westminster, Maryland" declines on its own (real in 5 states) -- the
    # hint from the calendar page it came from should win outright anyway.
    _register_platforms()
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "March 19, 2026 Planning and Zoning Commission Meeting",
            "uploader": "City of Westminster, Maryland",
            "upload_date": "20260319",
        },
    )

    response = client.post(
        "/api/resolve",
        json={
            "url": "https://www.youtube.com/watch?v=hintTest001",
            "jurisdiction_hint": "Westminster, MD",
        },
    )

    data = response.json()
    assert data.get("error") is None
    assert data["jurisdiction"] == "Westminster, MD"


def test_title_and_date_hints_only_fill_in_when_the_resolve_came_back_empty(
    monkeypatch,
):
    _register_platforms()
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": None,
            "uploader": None,
            "upload_date": None,
        },
    )

    response = client.post(
        "/api/resolve",
        json={
            "url": "https://www.youtube.com/watch?v=hintTest002",
            "title_hint": "Planning and Zoning Commission",
            "date_hint": "2026-03-19",
        },
    )

    data = response.json()
    assert data["title"] == "Planning and Zoning Commission"
    assert data["date"] == "2026-03-19"


def test_title_hint_never_overrides_a_real_resolved_title(monkeypatch):
    _register_platforms()
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "The Video's Own Real Title",
            "uploader": None,
            "upload_date": None,
        },
    )

    response = client.post(
        "/api/resolve",
        json={
            "url": "https://www.youtube.com/watch?v=hintTest003",
            "title_hint": "A Listing Page's Own Title",
        },
    )

    assert response.json()["title"] == "The Video's Own Real Title"
