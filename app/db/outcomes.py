from .models import MeetingResolution

# Matches the adapters' actual warning text (granicus.py, escribe.py,
# ca_legislature.py) -- string-matched rather than a stored boolean so this
# doesn't require touching every adapter's model just for reporting.
_GARBLED_MARKER = "looks garbled at the source"
TARGET_LANGUAGE = "en"

# Mirrors app/platforms/youtube.py's YOUTUBE_CAPTIONS_DISABLED_MARKER /
# YOUTUBE_VIDEO_UNAVAILABLE_MARKER (WO-135, 2026-09-09) -- independently
# defined here, same "duplicate the literal string with a cross-reference
# comment" convention _GARBLED_MARKER above already uses across this
# module/archive/db/crud.py. These mean "there is no transcript, and a
# real yt-dlp metadata check confirmed there never will be" -- worth its
# own bucket for the same reason archive/db/crud.py's matching
# `captions_disabled` bucket is: it looks identical to blank_transcript
# (zero segments) but is a permanent, confirmed answer rather than "the
# government source hasn't posted captions yet".
_YOUTUBE_CAPTIONS_DISABLED_MARKER = "YouTube: captions are disabled by the channel"
_YOUTUBE_VIDEO_UNAVAILABLE_MARKER = "YouTube: video is unavailable (removed or private)"


def classify_outcome(row: MeetingResolution) -> str:
    """Map a logged row to a content-quality outcome, not just whether
    resolve() raised. A resolve that returns 200 with a video but no real
    transcript is not a real success -- and agenda/chapter-marker data
    (CivicClerk, Swagit, Granicus -- now in `ResolvedMeeting.agenda_items`,
    a field separate from `segments`) is a real result but still a step
    down from an actual transcript, so it gets its own bucket rather than
    silently counting as "success". This is what lets the report tell
    "the adapter is broken" apart from "the adapter half-worked."

    Checks `resolved_payload["agenda_items"]` (the full ResolvedMeeting
    JSON stored on the row) rather than a warning-text marker -- agenda
    is now populated independently of transcript availability (see
    granicus.py/civicclerk.py/swagit.py), so its presence is a direct,
    reliable signal on its own, not something that needs inferring from
    warning text anymore.
    """
    if row.status != "success":
        return (
            row.status
        )  # resolve_failed | calendar_page | unsupported_platform | archive_redirect

    if not row.video_found:
        return "no_video"
    if row.transcript_warnings and any(
        _YOUTUBE_CAPTIONS_DISABLED_MARKER in w or _YOUTUBE_VIDEO_UNAVAILABLE_MARKER in w
        for w in row.transcript_warnings
    ):
        return "captions_disabled"
    if not row.transcript_found:
        payload = row.resolved_payload or {}
        if payload.get("agenda_items"):
            return "agenda_fallback"
        return "blank_transcript"
    if row.transcript_warnings and any(
        _GARBLED_MARKER in w for w in row.transcript_warnings
    ):
        return "garbled_transcript"
    if row.transcript_language and row.transcript_language != TARGET_LANGUAGE:
        return "non_english_transcript"
    return "success"
