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
        platform="youtube",
        source_url="https://www.youtube.com/watch?v=abc123",
        video_format="youtube",
    )
    assert "hosted on YouTube" in _unreadable_media_message(
        result, requested_platform="youtube"
    )


def test_lims_delegated_to_youtube_gets_delegated_message_with_watch_link():
    # The visitor's own URL was lims.minneapolismn.gov, never youtube.com --
    # requested_platform reflects what they actually typed in, not what the
    # delegated finder resolved to. Doesn't claim "hosted on YouTube" (a
    # confusing statement about a URL they never saw), but does include a
    # real watch-on-YouTube link -- per the user 2026-08-10, sending them
    # to YouTube gives the best experience, and the generic "may be
    # unavailable" copy wrongly implied a transient problem for what is a
    # permanent structural one.
    result = ResolvedMeeting(
        platform="youtube",
        source_url="https://lims.minneapolismn.gov/MarkedAgenda/CI/6133",
        video_format="youtube",
        video_url="https://www.youtube.com/embed/YgAu_4xWvGU",
    )
    message = _unreadable_media_message(result, requested_platform="lims")
    assert "hosted on YouTube" not in message
    assert "hosted through a service" in message
    assert "https://www.youtube.com/watch?v=YgAu_4xWvGU" in message


def test_primegov_delegated_to_youtube_gets_delegated_message():
    result = ResolvedMeeting(
        platform="youtube",
        source_url="https://slc.primegov.com/Portal/Meeting?meetingTemplateId=1",
        video_format="youtube",
        video_url="https://www.youtube.com/embed/abcDEF12345",
    )
    message = _unreadable_media_message(result, requested_platform="primegov")
    assert "hosted on YouTube" not in message
    assert "https://www.youtube.com/watch?v=abcDEF12345" in message


def test_delegated_youtube_with_no_extractable_id_falls_back_to_generic():
    # Defensive: video_url is always the youtube.com/embed/{id} shape this
    # app itself builds when video_format == "youtube", but if that ever
    # changes, fall through to the generic message rather than rendering a
    # broken link.
    result = ResolvedMeeting(
        platform="youtube",
        source_url="https://lims.minneapolismn.gov/MarkedAgenda/CI/6133",
        video_format="youtube",
        video_url=None,
    )
    message = _unreadable_media_message(result, requested_platform="lims")
    assert (
        message
        == "We found a media source but couldn't read it -- it may be unavailable."
    )


def test_generic_fallback_embedded_youtube_gets_youtube_specific_message():
    # best_effort=True, source_url on some unbranded small-city page -- the
    # video genuinely is youtube.com, no other jurisdiction system to obscure.
    result = ResolvedMeeting(
        platform="youtube",
        source_url="https://smallcity.example.gov/meeting",
        video_format="youtube",
        best_effort=True,
    )
    assert "hosted on YouTube" in _unreadable_media_message(
        result, requested_platform="unknown"
    )


def test_viebit_gets_viebit_specific_message_not_generic():
    # Same structural shape as Vimeo (iframe-embed video_url, real media
    # 403s every non-browser fetch) -- previously fell through to the
    # generic "may be unavailable" message, which reads as transient when
    # the limitation is permanent and structural. See BACKLOG.md.
    result = ResolvedMeeting(
        platform="legistar",
        source_url="https://legistar.council.nyc.gov/MeetingDetail.aspx?ID=1",
        video_format="viebit",
        video_url="https://vpv2.viebit.com/embed/vod?v=abc123",
    )
    message = _unreadable_media_message(result, requested_platform="legistar")
    assert "hosted on Viebit" in message
    assert "may be unavailable" not in message


def test_non_youtube_platform_stays_generic():
    result = ResolvedMeeting(
        platform="granicus",
        source_url="https://city.granicus.com/player/clip/1",
        video_format="m3u8",
    )
    message = _unreadable_media_message(result, requested_platform="granicus")
    assert "hosted on YouTube" not in message
    assert (
        message
        == "We found a media source but couldn't read it -- it may be unavailable."
    )
