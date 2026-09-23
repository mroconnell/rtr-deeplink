"""Candidate next actions, independent of public Context publication states."""

from archive.context.schemas import NextAction

NEXT_ACTION_LABELS: dict[str, str] = {
    "new": "Not checked yet",
    "check_failed": "Check failed — retry",
    "conflict": "Review conflicting evidence",
    "resolve_needed": "Identify the meeting",
    "recording_needed": "Find the full recording",
    "ingest_needed": "Review recording for ingestion",
    "moment_needed": "Review the moment and explanation",
}


def next_action_for(
    *,
    failed: bool = False,
    conflict: bool = False,
    unresolved: bool = False,
    matched: bool = False,
    recording_identified: bool = False,
    meeting_identified: bool = False,
) -> NextAction:
    """An exact identifier can settle identity despite missing metadata."""
    if failed:
        return "check_failed"
    if conflict:
        return "conflict"
    if unresolved:
        return "resolve_needed"
    if matched:
        return "moment_needed"
    if recording_identified:
        return "ingest_needed"
    if meeting_identified:
        return "recording_needed"
    return "resolve_needed"
