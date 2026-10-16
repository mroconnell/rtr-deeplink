"""One shared test for "this video title is a camera or file name", and the
one fallback page title that replaces it (WO-931 decision, 2026-09-21).

A video's own title is sometimes not a title at all: a camera's file name
("video1516165031", "IMG_2041"), a bare number or date stamp ("20251021",
"7959635610958757251"), or an uploaded file's name with its extension
("CC20260908.mp4", "8-18-26_Council-Meeting.mp4"). The 2026-09-21 export
(10,280 pages) held 12 such page titles: Viebit 7, Granicus 3, YouTube 2.

Ryan's decisions (2026-09-21, chat):

- the fallback title is "<government name> archive video", on every
  platform, not only Vimeo;
- when the date is known, keep the month and year only ("Laramie County,
  WY archive video, October 2025"), never the day, because an upload date
  and a filming date can differ.

A file name that carries a date or meeting words (`9_8_26_Council_
Meeting.mp4`) is replaced too, not cleaned into a meeting name: the
fallback only ever uses data on the video itself (the government's name
and the date). Never invent a meeting name from elsewhere.

`is_file_name_title()` is the one test. The video gate
(`video_hand_check.is_placeholder_title()`) and the Archive's ingest
(`archive/db/crud.py`) both call it. No network, no I/O.
"""

from __future__ import annotations

import re
from datetime import date as _date
from typing import Optional

# Each pattern is from a real title. Do not add one without a real example.
_FILE_NAME_TITLE_RES = (
    # Camera file name. Real: Oak Bluffs, MA's Vimeo video "video1516165031"
    # (page 10200, WO-925); a YouTube page titled "video1254656692".
    re.compile(r"^video\d+$", re.IGNORECASE),
    re.compile(r"^img_\d+", re.IGNORECASE),
    # A bare number or date stamp. Real: Laramie County, WY's Granicus
    # titles "20251021", "171205", "20260901"; a YouTube page titled
    # "7959635610958757251".
    re.compile(r"^\d+$"),
    # An uploaded file's name, extension and all. Real: 7 Viebit titles,
    # e.g. "NYCC-PV-CH-CHA_251218-163834.mp4", "CC20260908.mp4",
    # "TBC_06_09_2026Mtg.mp4". Only a video file extension, and only a
    # title with no spaces (a file name has none; "Watch the meeting.mp4
    # here" is not one).
    re.compile(r"^\S+\.(?:mp4|m4v|mov)$", re.IGNORECASE),
)


def is_file_name_title(title: Optional[str]) -> bool:
    """True when `title` is a camera or file name, not a real title."""
    t = (title or "").strip()
    return bool(t) and any(r.search(t) for r in _FILE_NAME_TITLE_RES)


def _month_year(meeting_date: Optional[str]) -> Optional[str]:
    """Month and year ("October 2025") from an ISO date ("2025-10-21" or
    "2025-10-21T..."), else None. Never the day (see the module docstring)."""
    raw = (meeting_date or "").strip()[:10]
    try:
        d = _date.fromisoformat(raw)
    except ValueError:
        return None
    return f"{d.strftime('%B')} {d.year}"


def fallback_video_title(
    government_name: Optional[str], meeting_date: Optional[str] = None
) -> Optional[str]:
    """The fallback: "<government name> archive video[, <Month YYYY>]", or
    None when no government name is known (a blank is a finding, not a gap
    to fill)."""
    name = (government_name or "").strip()
    if not name:
        return None
    title = f"{name} archive video"
    month_year = _month_year(meeting_date)
    if month_year:
        title = f"{title}, {month_year}"
    return title


def page_title_for_video(
    source_title: Optional[str],
    government_name: Optional[str],
    meeting_date: Optional[str] = None,
) -> Optional[str]:
    """The title a page should show. The source's own title, unless it is a
    camera or file name and the government is known; then the fallback.
    With no government name the source title is kept as it is."""
    if not is_file_name_title(source_title):
        return source_title
    return fallback_video_title(government_name, meeting_date) or source_title
