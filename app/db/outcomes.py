from .models import MeetingResolution

# Matches the adapters' actual warning text (granicus.py, escribe.py,
# ca_legislature.py) -- string-matched rather than a stored boolean so this
# doesn't require touching every adapter's model just for reporting.
_GARBLED_MARKER = "looks garbled at the source"
TARGET_LANGUAGE = "en"


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
        return row.status  # resolve_failed | calendar_page | unsupported_platform | archive_redirect

    if not row.video_found:
        return "no_video"
    if not row.transcript_found:
        payload = row.resolved_payload or {}
        if payload.get("agenda_items"):
            return "agenda_fallback"
        return "blank_transcript"
    if row.transcript_warnings and any(_GARBLED_MARKER in w for w in row.transcript_warnings):
        return "garbled_transcript"
    if row.transcript_language and row.transcript_language != TARGET_LANGUAGE:
        return "non_english_transcript"
    return "success"
