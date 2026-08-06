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
    warnings: List[str] = []
