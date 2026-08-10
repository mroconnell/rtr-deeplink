"""Tests for Minneapolis's "LIMS" adapter (app/platforms/lims.py).

Confirmed live 2026-08-09 (see BACKLOG_DONE.md): both the agenda page and
its /MeetingYoutubeVideo/{id} JSON endpoint return a genuine Cloudflare JS
challenge to a plain HTTP request, so this adapter uses
headless_browser.fetch_via_browser() instead of aiohttp -- mocked here via
monkeypatch rather than launching a real browser during tests, same
reasoning as every other adapter test in this suite mocking its HTTP layer.
"""

from app.platforms.lims import LimsAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

MEETING_URL = "https://lims.minneapolismn.gov/MarkedAgenda/CI/6133"
REAL_VIDEO_ID = "YgAu_4xWvGU"

# Trimmed real page shape, confirmed live 2026-08-09 against the real
# MarkedAgenda/CI/6133 page -- only the <title> tag matters to this
# adapter's own parsing.
AGENDA_PAGE_HTML = (
    "<html><head><title>Climate &amp; Infrastructure Committee Agenda "
    "8/6/2026 1:30 PM - City of Minneapolis</title></head><body></body></html>"
)

# Real shape confirmed live: a browser rendering a raw JSON response wraps
# it in <html><body><pre>...</pre>, and HTML-escapes special characters
# within the <pre> (note the &amp; inside the JSON's own title text) --
# the adapter must html.unescape() before json.loads().
JSON_ENDPOINT_HTML = (
    '<html><head></head><body><pre>{"url":"https://youtube.com/watch?v='
    + REAL_VIDEO_ID
    + '","SerializedVideoTimestamps":[{"id":17,"title":"Public Hearing",'
    '"timeInSeconds":null,"files":[{"id":144258,"title":"Sidewalk repair '
    'and construction assessments","timeInSeconds":"298"}]},{"id":5,'
    '"title":"Consent","timeInSeconds":"122","files":null},{"id":6,'
    '"title":"2026-2029 Climate &amp; Infrastructure (C&amp;I) Committee '
    'Work Plan","timeInSeconds":"3266","files":null}]}</pre></body></html>'
)


def _fake_extract_info(video_id):
    return {"title": "Real YouTube Title", "uploader": "cityofminneapolis", "upload_date": "20260806"}


async def _fake_fetch_via_browser(url, **kwargs):
    if "MeetingYoutubeVideo" in url:
        return JSON_ENDPOINT_HTML
    return AGENDA_PAGE_HTML


async def test_resolve_extracts_real_video_title_date_jurisdiction(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.lims.fetch_via_browser", _fake_fetch_via_browser)

    result = await LimsAssetFinder().resolve(MEETING_URL)

    assert result.platform == "youtube"  # delegated finder's own platform name, unchanged
    assert result.title == "Climate & Infrastructure Committee"
    assert result.date == "2026-08-06"
    assert result.jurisdiction == "City of Minneapolis"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"


async def test_resolve_keeps_original_lims_url_as_source_url(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.lims.fetch_via_browser", _fake_fetch_via_browser)

    result = await LimsAssetFinder().resolve(MEETING_URL)

    assert result.source_url == MEETING_URL


async def test_resolve_flattens_category_and_file_level_timestamps(monkeypatch):
    # Real bug this guards against: SerializedVideoTimestamps is a
    # category -> item tree, not a flat list. A category with its own
    # real timestamp and no files ("Consent") must not be dropped just
    # because it isn't a leaf -- confirmed live this matters.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.lims.fetch_via_browser", _fake_fetch_via_browser)

    result = await LimsAssetFinder().resolve(MEETING_URL)

    texts_by_start = {item.start: item.text for item in result.agenda_items}
    assert texts_by_start[122.0] == "Consent"  # category-level, no files
    assert texts_by_start[298.0] == "Sidewalk repair and construction assessments"  # file-level
    assert texts_by_start[3266.0] == "2026-2029 Climate & Infrastructure (C&I) Committee Work Plan"
    # A category with neither a real timestamp nor files ("Public
    # Hearing" itself, timeInSeconds=null) contributes no entry of its own.
    assert "Public Hearing" not in texts_by_start.values()


async def test_resolve_agenda_items_sorted_by_timestamp(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.lims.fetch_via_browser", _fake_fetch_via_browser)

    result = await LimsAssetFinder().resolve(MEETING_URL)

    starts = [item.start for item in result.agenda_items]
    assert starts == sorted(starts)


async def test_resolve_returns_no_video_warning_when_video_missing(monkeypatch):
    async def _no_video(url, **kwargs):
        if "MeetingYoutubeVideo" in url:
            return '<html><body><pre>{"url":"","SerializedVideoTimestamps":[]}</pre></body></html>'
        return AGENDA_PAGE_HTML

    monkeypatch.setattr("app.platforms.lims.fetch_via_browser", _no_video)

    result = await LimsAssetFinder().resolve(MEETING_URL)

    assert result.platform == "lims"
    assert result.video_url is None
    assert any("no video" in w.lower() for w in result.video_warnings)


async def test_resolve_still_works_when_youtube_metadata_fetch_fails(monkeypatch):
    # Real production incident, 2026-08-09: YouTube's anti-bot check
    # blocked Render's server IP entirely, so YouTubeAssetFinder._extract_
    # info() raised for every video, including this real Minneapolis one
    # (YgAu_4xWvGU). Before youtube.py's resolve_video_id() was made to
    # degrade gracefully instead of raising, this killed the whole LIMS
    # resolve -- even though LIMS never needed YouTube for title/date/
    # jurisdiction (its own agenda page) or for the video id/agenda items
    # (its own JSON endpoint) in the first place. Confirms the real fix:
    # the meeting still resolves with LIMS's own real data and a playable
    # video, missing only the transcript.
    import yt_dlp

    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    monkeypatch.setattr("app.platforms.lims.fetch_via_browser", _fake_fetch_via_browser)

    result = await LimsAssetFinder().resolve(MEETING_URL)

    assert result.title == "Climate & Infrastructure Committee"
    assert result.date == "2026-08-06"
    assert result.jurisdiction == "City of Minneapolis"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert len(result.agenda_items) == 3  # LIMS's own JSON data, untouched by the YouTube failure
    assert result.segments == []
    assert any("blocking automated caption requests" in w for w in result.video_warnings)


async def test_resolve_works_for_a_non_ci_committee_code(monkeypatch):
    # Real bug reported live 2026-08-10: a real user-submitted URL,
    # https://lims.minneapolismn.gov/MarkedAgenda/BHZ/6105 (Business,
    # Housing & Zoning committee, not City Council), failed with "Could
    # not find a meeting id in this LIMS URL" -- _ID_RE used to hardcode
    # the literal "CI" segment. The numeric id is what every downstream
    # step actually uses (the JSON endpoint URL is built from it alone),
    # so any committee code should resolve exactly the same way.
    bhz_url = "https://lims.minneapolismn.gov/MarkedAgenda/BHZ/6105"
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    monkeypatch.setattr("app.platforms.lims.fetch_via_browser", _fake_fetch_via_browser)

    result = await LimsAssetFinder().resolve(bhz_url)

    assert result.platform == "youtube"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert not any("could not find a meeting id" in w.lower() for w in result.video_warnings)


def test_extract_page_meta_parses_real_title_shape():
    title, date, jurisdiction = LimsAssetFinder._extract_page_meta(AGENDA_PAGE_HTML)
    assert title == "Climate & Infrastructure Committee"
    assert date == "2026-08-06"
    assert jurisdiction == "City of Minneapolis"


def test_extract_video_and_timestamps_parses_real_json_shape():
    video_id, agenda_items = LimsAssetFinder._extract_video_and_timestamps(JSON_ENDPOINT_HTML)
    assert video_id == REAL_VIDEO_ID
    assert len(agenda_items) == 3
