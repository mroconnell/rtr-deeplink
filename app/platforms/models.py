from typing import List, Optional
from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


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
    transcript_language: Optional[str] = None  # ISO 639-1 code detected from actual caption text
    # Split so the frontend can place video issues near the player and
    # caption/transcript issues near the transcript, instead of dumping
    # everything into one block above the video regardless of relevance.
    video_warnings: List[str] = []
    transcript_warnings: List[str] = []
