"""Formats a segment offset (seconds) into a short human-readable timestamp.

Mirrors archive/static/meeting_page.js's (and app/static/player.js's
identical) formatTime() exactly: h > 0 ? "{h}:{mm}:{ss}" : "{m}:{ss}".
Needed server-side because meeting_page.html renders agenda-item and
transcript-segment timestamps directly in Jinja -- real bug, confirmed
live: the template used to do this itself with a naive
`"%d:%02d"|format(seconds // 60, seconds % 60)`, which has no hour
rollover at all. For a segment at 21887 seconds (6:04:47), that computed
`21887 // 60 = 364`, `21887 % 60 = 47` -> the literal string "364:47",
while the <video> element's own native controls correctly showed 6:05:03.
"""


def format_segment_time(seconds) -> str:
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
