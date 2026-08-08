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
