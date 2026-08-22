"""The one definition of "this `video_format` is an embed page, not a
fetchable media file".

Extracted to its own module 2026-08-22 because the same predicate had
already been written twice and the two copies drifted: WO-35 added
"viebit" to the crud.py set, `meeting_page.html`'s JSON-LD branch kept
its own `("youtube", "vimeo")` literal, and Viebit meeting pages
advertised an HTML page as `contentUrl` until #303. A third copy --
`video_thumbnail.is_extractable()`, which gated on `"youtube"` alone --
was pointing ffmpeg at Vimeo and Viebit *HTML pages* the whole time.

So: import this, never re-spell it. Every caller wants the same answer
to the same question, and the failure mode when they disagree is silent.

Adding a format here is the *only* step for the Python callers; the
template's JSON-LD branch has to be updated by hand, and
tests/test_meeting_page_structured_data.py iterates this set to fail the
build if that is forgotten.
"""

from typing import Optional

# Adapters that store an iframe *player page* as MeetingPage.video_url
# rather than a real media URL:
#   youtube.py  -> youtube.com/embed/{id}
#   vimeo.py    -> player.vimeo.com/video/{id}
#   viebit.py   -> {origin}/embed/vod?v={id}
# Confirmed by grepping every adapter's `video_format=` assignment: every
# other value this app stores (mp4/m3u8/mp3/wav) is a genuine fetchable
# media URL.
IFRAME_EMBED_VIDEO_FORMATS: frozenset[str] = frozenset({"youtube", "vimeo", "viebit"})


def is_iframe_embed_format(video_format: Optional[str]) -> bool:
    """True when `video_format` names an embed page rather than media.

    `None` is False on purpose: an unknown format is *probably* a real
    media URL (that is what the ingest default has always meant), and
    the callers that care -- thumbnail extraction, the coverage table's
    "audio transcript possible" column -- each fail safe on their own if
    that guess is wrong, whereas excluding every unknown format would
    silently drop real pages.
    """
    return video_format in IFRAME_EMBED_VIDEO_FORMATS
