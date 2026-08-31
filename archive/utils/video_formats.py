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


# Real, fetchable media that is nonetheless audio-only -- a URL-detectable
# subset of the "19 audio-only meetings can never have a card" gap (found
# 2026-08-22, see BACKLOG_DONE.md). civicclerk.py sets `video_format` to
# the raw file extension it found (`ext in ("mp4", "mp3", "m3u8", "wav")`,
# app/platforms/civicclerk.py), so a page whose source is literally an
# `.mp3`/`.wav` URL on cpmedia.azureedge.net already carries that fact in
# `video_format` -- no ffprobe needed to know ffmpeg's `-frames:v 1` can
# only ever fail against it. This is deliberately NOT the whole gap: the
# rest is audio hiding *inside* an mp4/m3u8 container on Granicus/IQM2,
# which looks identical to a real video file by URL/format alone and is
# only detectable by actually probing the stream (see
# video_thumbnail.extract_and_store()).
AUDIO_ONLY_VIDEO_FORMATS: frozenset[str] = frozenset({"mp3", "wav"})


def is_audio_only_format(video_format: Optional[str]) -> bool:
    """True when `video_format` itself already says "this is audio, not
    video" -- see AUDIO_ONLY_VIDEO_FORMATS. `None` is False for the same
    reason as is_iframe_embed_format(): an unknown format is presumed a
    real video file, not silently excluded."""
    return video_format in AUDIO_ONLY_VIDEO_FORMATS
