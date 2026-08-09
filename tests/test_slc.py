"""Tests for Salt Lake City's meeting-recap adapter (app/platforms/slc.py).

Confirmed live 2026-08-09 (see BACKLOG_DONE.md): also behind a Cloudflare
JS challenge, same as Minneapolis LIMS -- mocked here via monkeypatch
rather than launching a real browser during tests.

Real, corrected finding this adapter's whole design is built on: these
pages were originally assumed to embed several distinct videos. Checked
live across four real pages instead -- every one has exactly one video
with several t= timestamp links into it. REAL_HTML below mirrors the real
March 3, 2026 page's structure closely enough to exercise that: multiple
"(Watch)" links, all pointing at the same video id, different t= values
in both the "...s" and bare-integer shapes real pages mix.
"""

from app.platforms.slc import SlcAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

MEETING_URL = "https://www.slc.gov/council/march-3-2026-meeting-recap/"
REAL_VIDEO_ID = "IxqEGR5x_1M"

# Trimmed real page shape, confirmed live 2026-08-09 against
# slc.gov/council/march-3-2026-meeting-recap/ -- real topics, real
# timestamps, real mixed t=1441 / t=2455s formatting, all pointing at the
# same video id (the real, corrected finding this adapter exists for).
REAL_HTML = f"""
<html><head><title>March 3, 2026 Meeting Recap | City Council Office</title></head>
<body>
<h2>Briefings</h2>
<p>Proposals that would expand the actions a land use applicant can take to
prevent an approved land use application from expiring.
(<a href="https://www.youtube.com/live/{REAL_VIDEO_ID}?t=1086s">Watch</a>)</p>
<p>The city's Annual Comprehensive Financial Report provided by an
independent analysis firm.
(<a href="http://youtube.com/live/{REAL_VIDEO_ID}?si=abc123&t=1441">Watch</a>)</p>
<p>An alley vacation for an unused area east of 519 E Browning Avenue.
(<a href="https://www.youtube.com/live/{REAL_VIDEO_ID}?t=1451s">Watch</a>)</p>
</body></html>
"""

NO_VIDEO_HTML = "<html><head><title>Some Page</title></head><body>No video here.</body></html>"


def _fake_extract_info(video_id):
    return {
        "title": "Salt Lake City Council Work Session - 03/03/2026",
        "uploader": "SLC Council",
        "upload_date": "20260304",
    }


async def _fake_fetch_via_browser(url, **kwargs):
    return REAL_HTML


async def test_resolve_delegates_to_youtube_and_overrides_metadata(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.slc.fetch_via_browser", _fake_fetch_via_browser)

    result = await SlcAssetFinder().resolve(MEETING_URL)

    assert result.platform == "youtube"  # delegated finder's own platform name, unchanged
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.title == "Salt Lake City Council Meeting"
    assert result.date == "2026-03-03"
    assert result.jurisdiction == "Salt Lake City, UT"


async def test_resolve_keeps_original_slc_url_as_source_url(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.slc.fetch_via_browser", _fake_fetch_via_browser)

    result = await SlcAssetFinder().resolve(MEETING_URL)

    assert result.source_url == MEETING_URL


async def test_resolve_turns_watch_links_into_agenda_items_not_a_video_picker(monkeypatch):
    # The real, corrected finding this whole adapter exists for: several
    # "(Watch)" links on one page are timestamps into ONE video, not
    # several distinct videos -- see BACKLOG_DONE.md.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.slc.fetch_via_browser", _fake_fetch_via_browser)

    result = await SlcAssetFinder().resolve(MEETING_URL)

    assert len(result.agenda_items) == 3
    texts_by_start = {item.start: item.text for item in result.agenda_items}
    assert texts_by_start[1086.0] == (
        "Proposals that would expand the actions a land use applicant can take to "
        "prevent an approved land use application from expiring."
    )
    assert "Annual Comprehensive Financial Report" in texts_by_start[1441.0]
    assert "alley vacation" in texts_by_start[1451.0]


async def test_resolve_handles_both_t_param_formats(monkeypatch):
    # Real pages mix "t=1441" (bare seconds) and "t=1086s" (trailing "s")
    # on the very same page -- both must parse to the same kind of value.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.slc.fetch_via_browser", _fake_fetch_via_browser)

    result = await SlcAssetFinder().resolve(MEETING_URL)

    starts = sorted(item.start for item in result.agenda_items)
    assert starts == [1086.0, 1441.0, 1451.0]


async def test_resolve_agenda_items_sorted_by_timestamp(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.slc.fetch_via_browser", _fake_fetch_via_browser)

    result = await SlcAssetFinder().resolve(MEETING_URL)

    starts = [item.start for item in result.agenda_items]
    assert starts == sorted(starts)


async def test_resolve_returns_no_video_warning_when_page_has_no_watch_links(monkeypatch):
    async def _no_video(url, **kwargs):
        return NO_VIDEO_HTML

    monkeypatch.setattr("app.platforms.slc.fetch_via_browser", _no_video)

    result = await SlcAssetFinder().resolve(MEETING_URL)

    assert result.platform == "slc"
    assert result.video_url is None
    assert result.jurisdiction == "Salt Lake City, UT"
    assert any("no video" in w.lower() for w in result.video_warnings)


def test_extract_date_parses_real_title_shape():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(REAL_HTML, "html.parser")
    assert SlcAssetFinder._extract_date(soup) == "2026-03-03"


def test_extract_timestamp_handles_both_formats():
    assert SlcAssetFinder._extract_timestamp("https://youtube.com/live/x?t=1086s") == 1086.0
    assert SlcAssetFinder._extract_timestamp("https://youtube.com/live/x?t=1441") == 1441.0
    assert SlcAssetFinder._extract_timestamp("https://youtube.com/live/x") is None
