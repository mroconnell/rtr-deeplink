import pytest
import yt_dlp

from app.platforms.youtube import YouTubeAssetFinder

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG.md's "zero test coverage" note). YouTube's real dependency,
# yt-dlp, is itself out of scope to mock at the network level -- these
# tests monkeypatch YouTubeAssetFinder._extract_info() instead, the exact
# seam resolve_video_id() calls it through, so the yt-dlp call itself
# stays real/untouched and only its *result* is stubbed. The real sample
# data below (video id, title, uploader, upload_date) is the actual
# Oklahoma City PrimeGov meeting resolved live 2026-08-08 -- see
# BACKLOG.md's PrimeGov date/jurisdiction entry.

REAL_VIDEO_ID = "uNDJRR3ywVo"
REAL_TITLE = "Oklahoma City Council Meeting - August 4, 2026"
REAL_UPLOADER = "cityofokc"
REAL_UPLOAD_DATE = "20260805"  # one day after the real meeting -- see BACKLOG.md

MANUAL_VTT = (
    "WEBVTT\n\n"
    "00:00:01.000 --> 00:00:03.000\n"
    "The ticker was appointed.\n\n"
    "00:00:03.000 --> 00:00:06.000\n"
    "Thank you all for joining us today.\n"
)


def _info_with_track(*, is_manual: bool, lang: str = "en", vtt: str = MANUAL_VTT) -> dict:
    return {
        "title": REAL_TITLE,
        "uploader": REAL_UPLOADER,
        "upload_date": REAL_UPLOAD_DATE,
        "_chosen_track": (vtt.encode("utf-8"), lang, is_manual),
    }


def test_extract_video_id_handles_every_real_url_shape():
    cases = {
        f"https://www.youtube.com/watch?v={REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/watch?feature=share&v={REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://youtu.be/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/embed/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/shorts/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/live/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        "https://example.com/not-youtube": None,
    }
    for url, expected in cases.items():
        assert YouTubeAssetFinder.extract_video_id(url) == expected


async def test_resolve_video_id_happy_path_with_manual_captions(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder, "_extract_info",
        lambda video_id: _info_with_track(is_manual=True),
    )

    result = await YouTubeAssetFinder.resolve_video_id(REAL_VIDEO_ID, source_url="https://okc.primegov.com/x")

    assert result.platform == "youtube"
    assert result.source_url == "https://okc.primegov.com/x"
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    assert result.title == REAL_TITLE
    # upload_date YYYYMMDD -> ISO, per BACKLOG.md's confirmed real-meeting-
    # date-mismatch note (upload_date is when it was posted, not the real
    # meeting date -- this test pins the current, imperfect behavior).
    assert result.date == "2026-08-05"
    assert result.jurisdiction == REAL_UPLOADER
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.video_format == "youtube"
    assert [s.text for s in result.segments] == [
        "The ticker was appointed.",
        "Thank you all for joining us today.",
    ]
    assert result.transcript_language == "en"
    # Manual captions -- no auto-generated-caption disclaimer.
    assert not any("auto-generated" in w for w in result.transcript_warnings)


async def test_resolve_video_id_flags_auto_generated_captions(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder, "_extract_info",
        lambda video_id: _info_with_track(is_manual=False),
    )

    result = await YouTubeAssetFinder.resolve_video_id(REAL_VIDEO_ID, source_url="https://example.com")

    assert any("auto-generated" in w for w in result.transcript_warnings)


async def test_resolve_video_id_flags_non_english_captions(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder, "_extract_info",
        lambda video_id: _info_with_track(is_manual=True, lang="es"),
    )

    result = await YouTubeAssetFinder.resolve_video_id(REAL_VIDEO_ID, source_url="https://example.com")

    assert result.transcript_language == "es"
    assert any("'es'" in w and "'en'" in w for w in result.transcript_warnings)


async def test_resolve_video_id_no_captions_available(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder, "_extract_info",
        lambda video_id: {"title": REAL_TITLE, "uploader": REAL_UPLOADER, "upload_date": REAL_UPLOAD_DATE},
    )

    result = await YouTubeAssetFinder.resolve_video_id(REAL_VIDEO_ID, source_url="https://example.com")

    assert result.segments == []
    assert result.transcript_language is None
    assert any("no captions found" in w.lower() for w in result.transcript_warnings)


async def test_resolve_video_id_missing_upload_date_leaves_date_none(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder, "_extract_info",
        lambda video_id: {"title": REAL_TITLE, "uploader": REAL_UPLOADER, "upload_date": None},
    )

    result = await YouTubeAssetFinder.resolve_video_id(REAL_VIDEO_ID, source_url="https://example.com")

    assert result.date is None


async def test_resolve_video_id_degrades_to_playable_meeting_on_download_error(monkeypatch):
    # Real production incident, 2026-08-09 (see BACKLOG.md): YouTube's
    # anti-bot check blocks Render's server IP outright, regardless of
    # which internal yt-dlp client is used. Previously any DownloadError
    # here raised and killed the whole resolve -- now it degrades to a
    # real, playable ResolvedMeeting instead, since embedding only ever
    # needed the video id, never yt-dlp. This also lets a delegating
    # adapter's own metadata (e.g. lims.py) still get used -- resolve_
    # video_id() failing outright previously threw that away too.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)

    result = await YouTubeAssetFinder.resolve_video_id(REAL_VIDEO_ID, source_url="https://example.com")

    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.video_format == "youtube"
    assert result.title is None
    assert result.segments == []
    assert any("blocking automated caption requests" in w for w in result.video_warnings)
    assert any("No transcript available" in w for w in result.transcript_warnings)


async def test_resolve_video_id_raises_when_no_info_returned(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", lambda video_id: None)

    with pytest.raises(ValueError, match="no info returned by yt-dlp"):
        await YouTubeAssetFinder.resolve_video_id(REAL_VIDEO_ID, source_url="https://example.com")


async def test_resolve_delegates_to_resolve_video_id_for_a_standalone_url(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder, "_extract_info",
        lambda video_id: _info_with_track(is_manual=True),
    )

    url = f"https://www.youtube.com/watch?v={REAL_VIDEO_ID}"
    result = await YouTubeAssetFinder().resolve(url)

    # A standalone YouTube URL keeps itself as source_url (no delegating
    # platform involved), unlike PrimeGov's override.
    assert result.source_url == url


async def test_resolve_raises_for_a_non_youtube_url():
    with pytest.raises(ValueError, match="Could not find a YouTube video ID"):
        await YouTubeAssetFinder().resolve("https://example.com/not-youtube")
