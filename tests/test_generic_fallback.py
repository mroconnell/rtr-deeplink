"""Tests for the generic "unknown platform" fallback (built 2026-08-09,
directly from the user's own request: try our best instead of a flat
"we don't support this yet"). Registered under platform_name="unknown",
the exact string detect_platform() returns for anything unmatched.
"""

from app.platforms.generic_fallback import GenericFallbackAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session

PAGE_URL = "https://some-city.example.gov/meetings/council-2026-01-01"
REAL_VIDEO_ID = "dQw4w9WgXcQ"

PAGE_WITH_YOUTUBE_EMBED = f"""
<html><body>
<iframe src="https://www.youtube.com/embed/{REAL_VIDEO_ID}"></iframe>
</body></html>
"""

PAGE_WITH_DIRECT_MEDIA = """
<html><body>
<video src="https://cdn.example.gov/videos/meeting.m3u8"></video>
<a href="https://cdn.example.gov/captions/meeting.vtt">Captions</a>
</body></html>
"""

PAGE_WITH_NOTHING = "<html><body>Agenda: Item 1, Item 2. No video here.</body></html>"

REAL_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello and welcome.

00:00:02.000 --> 00:00:04.000
This meeting is now in session.
"""


def _fake_extract_info(video_id):
    return {"title": "Some City Council Meeting", "uploader": "Some City Gov", "upload_date": "20260101"}


async def test_resolve_delegates_to_youtube_when_embed_found(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_YOUTUBE_EMBED, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "youtube"  # delegated finder's own platform name, unchanged -- real dedup identity
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert any("isn't officially supported" in w for w in result.video_warnings)


async def test_resolve_finds_direct_media_and_captions(monkeypatch):
    routes = {
        PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_DIRECT_MEDIA, url=PAGE_URL),
        "https://cdn.example.gov/captions/meeting.vtt": FakeResponse(status=200, text=REAL_VTT, url="x"),
    }

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "unknown"
    assert result.video_url == "https://cdn.example.gov/videos/meeting.m3u8"
    assert result.video_format == "m3u8"
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello and welcome."
    assert any("isn't officially supported" in w for w in result.video_warnings)


async def test_resolve_returns_honest_no_video_message_when_nothing_found():
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_NOTHING, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "unknown"
    assert result.video_url is None
    assert result.segments == []
    assert any("couldn't find a video on this page automatically" in w for w in result.video_warnings)
    assert any("didn't automatically find a transcript" in w for w in result.transcript_warnings)


async def test_resolve_handles_page_fetch_failure_cleanly():
    routes = {PAGE_URL: FakeResponse(status=500, text="", url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.platform == "unknown"
    assert result.video_url is None
    assert any("couldn't even load the page" in w for w in result.video_warnings)


async def test_resolve_finds_media_without_captions(monkeypatch):
    page_no_captions = """
    <html><body><video src="https://cdn.example.gov/videos/meeting.mp4"></video></body></html>
    """
    routes = {PAGE_URL: FakeResponse(status=200, text=page_no_captions, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.video_url == "https://cdn.example.gov/videos/meeting.mp4"
    assert result.video_format == "mp4"
    assert result.segments == []
    assert any("didn't automatically find a transcript" in w for w in result.transcript_warnings)


async def test_resolve_surfaces_agenda_pdf_link_alongside_youtube_video(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    page = f"""
    <html><body>
    <iframe src="https://www.youtube.com/embed/{REAL_VIDEO_ID}"></iframe>
    <p>Agenda: Item 1, Item 2, Item 3.</p>
    <a href="/docs/2026-01-01-agenda.pdf">View Agenda (PDF)</a>
    <a href="/minutes/2026-01-01.pdf">Minutes</a>
    </body></html>
    """
    routes = {PAGE_URL: FakeResponse(status=200, text=page, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    expected_link = "https://some-city.example.gov/docs/2026-01-01-agenda.pdf"
    assert any(expected_link in w for w in result.agenda_warnings)
    # The plain-text "Agenda: Item 1..." paragraph must not be picked up as
    # if it were structured agenda items -- this adapter never populates
    # agenda_items, only a plain link message.
    assert result.agenda_items == []


async def test_resolve_ignores_plain_text_agenda_mention_with_no_link():
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_WITH_NOTHING, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert result.agenda_warnings == []


async def test_resolve_prefers_pdf_agenda_link_over_html_agenda_page():
    page = """
    <html><body>
    <video src="https://cdn.example.gov/videos/meeting.mp4"></video>
    <a href="/meetings/2026-01-01/agenda">Agenda</a>
    <a href="/docs/2026-01-01-agenda.pdf">Agenda (PDF)</a>
    </body></html>
    """
    routes = {PAGE_URL: FakeResponse(status=200, text=page, url=PAGE_URL)}

    with mock_session(routes):
        result = await GenericFallbackAssetFinder().resolve(PAGE_URL)

    assert any("2026-01-01-agenda.pdf" in w for w in result.agenda_warnings)
