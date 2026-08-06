from typing import List, Optional
from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class ResolvedMeeting(BaseModel):
    platform: str
    source_url: str
    title: Optional[str] = None
    date: Optional[str] = None
    jurisdiction: Optional[str] = None
    video_url: Optional[str] = None  # m3u8 or mp4, playable by hls.js/<video>
    video_format: Optional[str] = None  # "m3u8" | "mp4" | None
    segments: List[TranscriptSegment] = []
    transcript_language: Optional[str] = None  # ISO 639-1 code detected from actual caption text
    # Split so the frontend can place video issues near the player and
    # caption/transcript issues near the transcript, instead of dumping
    # everything into one block above the video regardless of relevance.
    video_warnings: List[str] = []
    transcript_warnings: List[str] = []
