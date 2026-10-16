def _srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def to_srt(segments: list) -> str:
    """segments: list of {"start": float, "end": float, "text": str}."""
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(seg['start'])} --> {_srt_timestamp(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def _txt_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def to_txt(segments: list) -> str:
    """Plain-text transcript, one timestamped line per segment -- readable
    on its own, not just a stripped-down SRT (no cue numbers/arrows).

    WO-1967: when a segment carries a speaker label from the station's
    captions and it differs from the last label shown, the line reads
    "[1:05] NAME: text", the same rule the meeting page uses. The .srt
    export stays label-free: subtitle players show cue text as it is."""
    lines = []
    last_speaker = None
    for seg in segments:
        speaker = seg.get("speaker")
        prefix = f"{speaker}: " if speaker and speaker != last_speaker else ""
        if speaker:
            last_speaker = speaker
        lines.append(f"[{_txt_timestamp(seg['start'])}] {prefix}{seg['text']}")
    return "\n".join(lines)
