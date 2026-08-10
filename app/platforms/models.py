from typing import List, Optional
from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    # Unused by every adapter today (always None) -- forward-compat for a
    # future diarization pass over on-demand-transcribed audio, so that
    # feature won't need another schema touch when it's actually built.
    speaker: Optional[str] = None


class AlternateTranscript(BaseModel):
    """A caption track that was found and fetched but not chosen as the
    primary transcript (see `ResolvedMeeting.alternate_transcripts`) --
    typically a different language than TARGET_LANGUAGE. Carries full
    segments (not just a language label) so the frontend can switch the
    displayed transcript client-side with no extra round-trip."""

    language: Optional[str] = None  # ISO 639-1 code detected from actual caption text, same as transcript_language
    segments: List[TranscriptSegment] = []


class ResolvedMeeting(BaseModel):
    platform: str
    source_url: str
    external_id: Optional[str] = None  # namespaced e.g. "granicus:52945"; None until an adapter populates it
    title: Optional[str] = None
    date: Optional[str] = None
    jurisdiction: Optional[str] = None
    video_url: Optional[str] = None  # m3u8/mp4 URL playable by hls.js/<video>, OR a youtube.com/embed/{id} URL
    video_format: Optional[str] = None  # "m3u8" | "mp4" | "youtube" | None -- "youtube" needs the iframe+Player-API pathway, not <video>
    segments: List[TranscriptSegment] = []
    # Agenda/chapter markers (Granicus's AgendaViewer.php, CivicClerk's
    # eventBookmarks, Swagit's .playerControl) -- kept separate from
    # `segments` so they're never mistaken for a real transcript.
    # Populated independently of whether a real transcript exists, so a
    # meeting with both shows both (agenda above transcript on the page).
    agenda_items: List[TranscriptSegment] = []
    # A single raw agenda-document URL (not a sentence) -- e.g.
    # generic_fallback.py's best-effort "found a link that looks like the
    # agenda" result. Kept separate from agenda_items (a real per-item
    # timestamp list) so it's never mistaken for one; the frontend renders
    # it as a plain "we think we found an agenda here: <link>" line rather
    # than the clickable timestamp table agenda_items gets.
    agenda_link: Optional[str] = None
    transcript_language: Optional[str] = None  # ISO 639-1 code detected from actual caption text
    # Other real caption tracks found on the page but not chosen as
    # `segments` -- lets the frontend offer a language switcher instead of
    # silently discarding every track but the best-matching one. Empty
    # when only one usable track was found (the common case).
    alternate_transcripts: List[AlternateTranscript] = []
    # Split so the frontend can place video issues near the player and
    # caption/transcript issues near the transcript, instead of dumping
    # everything into one block above the video regardless of relevance.
    video_warnings: List[str] = []
    transcript_warnings: List[str] = []
    # True only for generic_fallback.py's best-effort results (whether or
    # not it delegated to YouTubeAssetFinder, whose own `platform` field
    # is "youtube", not "unknown" -- checking `platform == "unknown"`
    # alone would silently miss the delegated case, which is actually the
    # *most* common real outcome here). The frontend uses this, not
    # `platform`, to decide whether to show the "we're trying our best,
    # nothing here is guaranteed" framing (see meeting.html/player.js).
    best_effort: bool = False
