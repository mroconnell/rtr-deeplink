"""IQM2 hub URLs (no MeetingID) return the "pick a meeting" answer.

No network: aiohttp is mocked with saved fixtures; "today" is patched.
"""

import datetime as dt
import pathlib
from unittest import mock

import pytest

from app.platforms import iqm2
from app.platforms.base import CalendarPageError
from app.platforms.iqm2 import IQM2AssetFinder

from aiohttp_mock import FakeResponse, mock_session

FIX = pathlib.Path(__file__).parent / "fixtures" / "iqm2"
KNOX = (FIX / "knoxvillecitytn_calendar_list.html").read_text()
MONROE = (FIX / "monroecountyfl_calendar_list.html").read_text()
CROW = (FIX / "crowwing_calendar_2025.html").read_text()
EMPTY = "<html><body>No meetings</body></html>"


@pytest.fixture(autouse=True)
def _clear_cache():
    iqm2._HUB_CACHE.clear()
    yield
    iqm2._HUB_CACHE.clear()


def _list_url(origin, today, window):
    s = today - dt.timedelta(days=window)
    e = today + dt.timedelta(days=30)
    return (
        f"{origin}/Citizens/calendar.aspx?View=List"
        f"&From={s.month}/{s.day}/{s.year}&To={e.month}/{e.day}/{e.year}"
    )


def _routes(origin, today, narrow, wide=None):
    r = {_list_url(origin, today, 400): narrow}
    if wide is not None:
        r[_list_url(origin, today, 1095)] = wide
    return r


def ok(text):
    return FakeResponse(status=200, text=text)


async def _resolve(url, today, routes):
    with mock.patch.object(iqm2, "_today", lambda: today):
        with mock_session(routes):
            return await IQM2AssetFinder().resolve(url)


KNOX_O = "https://knoxvillecitytn.iqm2.com"
TODAY = dt.date(2026, 1, 15)


@pytest.mark.parametrize(
    "path",
    [
        "/Citizens/Media.aspx",
        "/Citizens/Calendar.aspx",
        "/Citizens/Default.aspx",
        "/Citizens/Boards.aspx",
        "/Citizens/",
        "/Citizens",
        "/Citizens/SplitView.aspx",
        "/Citizens/SplitView.aspx?Mode=Video",
        "/",
    ],
)
async def test_each_hub_shape_gives_calendar_page(path):
    with pytest.raises(CalendarPageError) as exc:
        await _resolve(KNOX_O + path, TODAY, _routes(KNOX_O, TODAY, ok(KNOX)))
    cands = exc.value.candidates
    assert [c["date"] for c in cands] == ["2025-12-09", "2025-11-25"]
    assert cands[0]["url"] == f"{KNOX_O}/Citizens/Detail_Meeting.aspx?ID=1691"
    assert set(cands[0]) == {"title", "date", "url"}


async def test_future_meetings_are_excluded():
    today = dt.date(2025, 12, 1)
    with pytest.raises(CalendarPageError) as exc:
        await _resolve(KNOX_O + "/Citizens/", today, _routes(KNOX_O, today, ok(KNOX)))
    assert [c["date"] for c in exc.value.candidates] == ["2025-11-25"]


async def test_empty_narrow_window_falls_back_to_long_window_and_prefers_video():
    o = "https://monroecountyfl.iqm2.com"
    today = dt.date(2026, 10, 6)
    routes = _routes(o, today, ok(EMPTY), ok(MONROE))
    with pytest.raises(CalendarPageError) as exc:
        await _resolve(o + "/Citizens/Default.aspx", today, routes)
    # Only the row with a real video link is offered when any row has one.
    assert [c["url"] for c in exc.value.candidates] == [
        f"{o}/Citizens/Detail_Meeting.aspx?ID=1180"
    ]


async def test_rows_without_video_are_kept_when_none_has_video():
    # Knoxville rows carry no video link at all.
    with pytest.raises(CalendarPageError) as exc:
        await _resolve(KNOX_O + "/Citizens/", TODAY, _routes(KNOX_O, TODAY, ok(KNOX)))
    assert len(exc.value.candidates) == 2


async def test_video_rows_first_newest_first_and_capped():
    o = "https://crowwingcountymn.iqm2.com"
    today = dt.date(2026, 1, 15)
    with pytest.raises(CalendarPageError) as exc:
        await _resolve(o + "/Citizens/Media.aspx", today, _routes(o, today, ok(CROW)))
    dates = [c["date"] for c in exc.value.candidates]
    assert dates == sorted(dates, reverse=True)
    assert len(dates) <= 15

    many = "<html><body>" + "".join(
        f'<a href="/Citizens/Detail_Meeting.aspx?ID={i}">Jan {i}, 2025 9:00 AM</a>'
        for i in range(1, 29)
    ) + "</body></html>"
    iqm2._HUB_CACHE.clear()
    with pytest.raises(CalendarPageError) as exc:
        await _resolve(o + "/Citizens/", today, _routes(o, today, ok(many)))
    assert len(exc.value.candidates) == 15
    assert exc.value.candidates[0]["date"] == "2025-01-28"


async def test_both_windows_empty_returns_old_warning():
    routes = _routes(KNOX_O, TODAY, ok(EMPTY), ok(EMPTY))
    result = await _resolve(KNOX_O + "/Citizens/", TODAY, routes)
    assert result.video_url is None
    assert "meeting id" in result.video_warnings[0].lower()


async def test_http_error_returns_old_warning_and_is_not_cached():
    routes = _routes(
        KNOX_O, TODAY, FakeResponse(status=500, text=""), FakeResponse(status=500, text="")
    )
    result = await _resolve(KNOX_O + "/Citizens/", TODAY, routes)
    assert result.video_warnings
    assert iqm2._HUB_CACHE == {}


async def test_second_request_for_same_tenant_uses_cache():
    routes = _routes(KNOX_O, TODAY, ok(KNOX))
    with pytest.raises(CalendarPageError):
        await _resolve(KNOX_O + "/Citizens/", TODAY, routes)
    # No routes now: any network call would raise AssertionError.
    with pytest.raises(CalendarPageError) as exc:
        await _resolve(KNOX_O + "/Citizens/Media.aspx", TODAY, {})
    assert len(exc.value.candidates) == 2


async def test_meeting_url_with_meeting_id_still_resolves_as_before():
    o = "https://atlantacityga.iqm2.com"
    outline = (
        f"{o}/Citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
        "&Mode=Video&Frame=Nothing&ID=4294"
    )
    split = f"{o}/Citizens/SplitView.aspx?Mode=Video&MeetingID=4294&Format=Minutes"
    routes = {
        outline: ok(
            "<html><head><title>2026/08/12 01:30 PM Finance Regular Meeting - "
            "Web Outline - City of Atlanta, Georgia</title></head></html>"
        ),
        split: ok("<!-- MEDIA URL: https://x.granicus.com/a/playlist.m3u8-->"),
    }
    result = await _resolve(f"{o}/Citizens/SplitView.aspx?Mode=Video&MeetingID=4294", TODAY, routes)
    assert result.video_url == "https://x.granicus.com/a/playlist.m3u8"
    assert result.date == "2026-08-12"
