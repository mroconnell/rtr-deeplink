import re
from typing import List, Dict, Any


def parse_vtt(content: str) -> List[Dict[str, Any]]:
    """Parse WebVTT content into a list of cue dicts with 'start', 'end', 'text'.

    Ported from rtr-transcripts/app/utils/vtt_parser.py (unchanged — this part
    already worked correctly in testing).
    """
    content = content.lstrip("﻿")
    lines = content.splitlines()

    cues = []
    current_cue = None

    for line in lines:
        line = line.strip()

        if not line or line == "WEBVTT":
            continue

        timestamp_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[\.\,]\d{3}) --> ((\d{2}:\d{2}:\d{2}[\.\,]\d{3}).*)",
            line,
        )

        if timestamp_match:
            if current_cue:
                cues.append(current_cue)

            start, end_line = timestamp_match.groups()[:2]
            end = end_line.split(" ", 1)[0]

            current_cue = {
                "start": _parse_timestamp(start),
                "end": _parse_timestamp(end),
                "text": "",
            }
        elif current_cue is not None:
            if current_cue["text"]:
                current_cue["text"] += "\n" + line
            else:
                current_cue["text"] = line

    if current_cue:
        cues.append(current_cue)

    return cues


def _parse_timestamp(timestamp: str) -> float:
    parts = timestamp.replace(",", ".").split(":")

    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    else:
        return float(parts[0])
