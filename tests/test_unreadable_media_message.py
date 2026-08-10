"""Tests for app/main.py's _unreadable_media_message() -- the copy shown by
/api/transcription/check-feasibility when ffprobe can't read result.video_url.

Built 2026-08-10 directly from a real user report: clicking "Request
Transcript from Audio" on a YouTube-hosted meeting showed a generic "we
found a media source but couldn't read it" message, when the real cause is
structural (result.video_url for YouTube is an iframe-embed *page*, never a
real media file -- ffprobe can never read it, regardless of any blocking).

Deliberately NOT keyed on video_format == "youtube" alone -- that's also
true for LIMS/PrimeGov, which delegate to YouTube behind a *different*
jurisdiction's own branded page (source_url stays lims.minneapolismn.gov,
never youtube.com). Telling that visitor "hosted on YouTube" would be a
confusing claim about a URL they never saw -- confirmed with the user
directly before building this distinction.
"""

from app.main import _unreadable_media_message
from app.platforms.models import ResolvedMeeting


def test_direct_youtube_url_gets_youtube_specific_message():
    result = ResolvedMeeting(
        platform="youtube", source_url="https://www.youtube.com/watch?v=abc123", video_format="youtube"
    )
    assert "hosted on YouTube" in _unreadable_media_message(result, requested_platform="youtube")


def test_lims_delegated_to_youtube_stays_generic():
    # The visitor's own URL was lims.minneapolismn.gov, never youtube.com --
    # requested_platform reflects what they actually typed in, not what the
    # delegated finder resolved to.
    result = ResolvedMeeting(
        platform="youtube",
        source_url="https://lims.minneapolismn.gov/MarkedAgenda/CI/6133",
        video_format="youtube",
    )
    message = _unreadable_media_message(result, requested_platform="lims")
    assert "hosted on YouTube" not in message
    assert message == "We found a media source but couldn't read it -- it may be unavailable."


def test_primegov_delegated_to_youtube_stays_generic():
    result = ResolvedMeeting(
        platform="youtube", source_url="https://slc.primegov.com/Portal/Meeting?meetingTemplateId=1",
        video_format="youtube",
    )
    message = _unreadable_media_message(result, requested_platform="primegov")
    assert "hosted on YouTube" not in message


def test_generic_fallback_embedded_youtube_gets_youtube_specific_message():
    # best_effort=True, source_url on some unbranded small-city page -- the
    # video genuinely is youtube.com, no other jurisdiction system to obscure.
    result = ResolvedMeeting(
        platform="youtube", source_url="https://smallcity.example.gov/meeting", video_format="youtube",
        best_effort=True,
    )
    assert "hosted on YouTube" in _unreadable_media_message(result, requested_platform="unknown")


def test_non_youtube_platform_stays_generic():
    result = ResolvedMeeting(
        platform="granicus", source_url="https://city.granicus.com/player/clip/1", video_format="m3u8"
    )
    message = _unreadable_media_message(result, requested_platform="granicus")
    assert "hosted on YouTube" not in message
    assert message == "We found a media source but couldn't read it -- it may be unavailable."
