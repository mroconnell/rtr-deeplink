from .models import MeetingResolution

# Matches the adapters' actual warning text (granicus.py, civicclerk.py,
# swagit.py, escribe.py, ca_legislature.py) -- string-matched rather than a
# stored boolean so this doesn't require touching every adapter's model just
# for reporting. The agenda-fallback marker is shared verbatim across the
# three adapters that use it (CivicClerk's eventBookmarks, Swagit's
# playerControl chapters, Granicus's AgendaViewer.php).
_GARBLED_MARKER = "looks garbled at the source"
_AGENDA_FALLBACK_MARKER = "showing agenda-item chapter markers instead"
TARGET_LANGUAGE = "en"


def classify_outcome(row: MeetingResolution) -> str:
    """Map a logged row to a content-quality outcome, not just whether
    resolve() raised. A resolve that returns 200 with a video but no real
    transcript is not a real success -- and agenda/chapter-marker
    fallbacks (CivicClerk, Swagit, Granicus) are a real result but still a
    step down from an actual transcript, so they get their own bucket
    rather than silently counting as "success" just because `segments`
    is non-empty. This is what lets the report tell "the adapter is
    broken" apart from "the adapter half-worked."
    """
    if row.status != "success":
        return row.status  # resolve_failed | calendar_page | unsupported_platform

    if not row.video_found:
        return "no_video"
    if row.transcript_warnings and any(_AGENDA_FALLBACK_MARKER in w for w in row.transcript_warnings):
        return "agenda_fallback"
    if not row.transcript_found:
        return "blank_transcript"
    if row.transcript_warnings and any(_GARBLED_MARKER in w for w in row.transcript_warnings):
        return "garbled_transcript"
    if row.transcript_language and row.transcript_language != TARGET_LANGUAGE:
        return "non_english_transcript"
    return "success"
