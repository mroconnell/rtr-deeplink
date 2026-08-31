"""One definition of "this video_format is an embed page, not media",
shared by `video_thumbnail.is_extractable()` and crud's thumbnail
candidate query.

Both used to gate on `"youtube"` alone. vimeo.py (WO-29) and viebit.py
also store an iframe player *page* as `video_url`, so both callers
returned/selected True for them -- verified live 2026-08-22 -- and ffmpeg
was handed an HTML page. Those failures can never succeed, and every one
landed in the meeting-card sweep's failure set, which is what WO-42's
per-page failure reasons exist to make readable. Fixing this before
retrying the 179 recorded failures is the whole point.

Real URL shapes throughout: youtube.py's `youtube.com/embed/{11-char}`,
vimeo.py's `player.vimeo.com/video/{id}` (Salisbury NC's real id, as
tests/test_vimeo.py uses), viebit.py's `{origin}/embed/vod?v={id}` (the
exact URL tests/test_viebit.py pins against the real NYC Council
fixture). Pages are synthetic -- what is under test is one predicate and
one WHERE clause, not adapter parsing.
"""

import pytest

from archive.db import crud
from archive.utils.video_formats import (
    AUDIO_ONLY_VIDEO_FORMATS,
    IFRAME_EMBED_VIDEO_FORMATS,
    is_audio_only_format,
    is_iframe_embed_format,
)
from archive.utils.video_thumbnail import is_extractable

_EMBED_URLS = {
    "youtube": "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "vimeo": "https://player.vimeo.com/video/1212025580",
    "viebit": "https://councilnyc.viebit.com/embed/vod?v=hFWIQkuFLuWGb0mw",
}
_REAL_MEDIA = {
    "m3u8": "https://example.granicus.com/OnDemand/x/chunklist.m3u8",
    "mp4": "https://otv.ocfl.net/otv/BCC2026/BCC071626/BCC071626AA.mp4",
}
# Real CivicClerk media host (see tests/test_civicclerk.py) -- confirmed
# real audio-only shape: civicclerk.py sets video_format from the file
# extension it found (ext in ("mp4", "mp3", "m3u8", "wav")).
_AUDIO_ONLY_URLS = {
    "mp3": "https://cpmedia.azureedge.net/example/f32a4ab02f.mp3",
    "wav": "https://cpmedia.azureedge.net/example/f32a4ab02f.wav",
}


def test_the_set_covers_exactly_the_adapters_that_store_an_embed_page():
    # Guards the constant itself. A new iframe-embed adapter has to land
    # here deliberately, and meeting_page.html's JSON-LD branch has its
    # own guard in test_meeting_page_structured_data.py.
    assert IFRAME_EMBED_VIDEO_FORMATS == {"youtube", "vimeo", "viebit"}


def test_none_is_not_an_embed_format():
    # An unknown format is probably real media (the ingest default's
    # meaning). Excluding unknowns would silently drop real pages.
    assert is_iframe_embed_format(None) is False


@pytest.mark.parametrize("video_format", sorted(_EMBED_URLS))
def test_no_embed_platform_is_extractable(video_format):
    # The regression: vimeo and viebit both returned True here, so
    # ffmpeg got pointed at an HTML page.
    assert is_extractable(_EMBED_URLS[video_format], video_format) is False


@pytest.mark.parametrize("video_format", sorted(_REAL_MEDIA))
def test_real_media_is_still_extractable(video_format):
    assert is_extractable(_REAL_MEDIA[video_format], video_format) is True


def test_youtube_url_shape_still_caught_when_the_format_field_is_wrong():
    # Second line of defence, deliberately kept: a mislabeled row whose
    # URL is plainly YouTube is still not extractable.
    assert is_extractable(_EMBED_URLS["youtube"], "mp4") is False
    assert is_extractable(_EMBED_URLS["youtube"], None) is False


def test_the_two_callers_read_the_same_constant():
    # crud kept `_IFRAME_EMBED_VIDEO_FORMATS` as a re-export rather than
    # a second literal -- that duplication is what drifted and produced
    # the Viebit contentUrl bug (#303).
    assert crud._IFRAME_EMBED_VIDEO_FORMATS is IFRAME_EMBED_VIDEO_FORMATS


# --- WO-85: audio-only formats (mp3/wav), the URL-detectable half of the
# "19 audio-only meetings can never have a card" gap ---------------------


def test_the_audio_only_set_is_exactly_mp3_and_wav():
    assert AUDIO_ONLY_VIDEO_FORMATS == {"mp3", "wav"}


def test_none_is_not_an_audio_only_format():
    # Same reasoning as is_iframe_embed_format(None): an unknown format is
    # presumed real video, not silently excluded.
    assert is_audio_only_format(None) is False


@pytest.mark.parametrize("video_format", sorted(_AUDIO_ONLY_URLS))
def test_audio_only_format_is_not_extractable(video_format):
    assert is_extractable(_AUDIO_ONLY_URLS[video_format], video_format) is False


# --- the candidate query -----------------------------------------------


async def _page(external_id: str, video_url: str, video_format: str) -> str:
    url = f"https://example.com/iframe-gate/{external_id}"
    result = await crud.ingest_resolution(
        {
            "platform": video_format,
            "source_url": url,
            "external_id": external_id,
            "title": "Iframe Gate Test",
            "date": "2026-01-01",
            "jurisdiction": "Fresno, CA",
            "video_url": video_url,
            "video_format": video_format,
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
        },
        url,
    )
    return result["slug"]


async def test_candidate_query_excludes_every_embed_platform():
    # The SQL half. Before the fix this WHERE clause said
    # `video_format != "youtube"`, so vimeo and viebit rows were handed
    # to the sweep as thumbnail candidates.
    made = {}
    for video_format, video_url in _EMBED_URLS.items():
        made[video_format] = await _page(
            f"embed-{video_format}", video_url, video_format
        )
    real = await _page("real-m3u8", _REAL_MEDIA["m3u8"], "m3u8")

    candidates = await crud.list_pages_missing_default_thumbnail(limit=500)
    slugs = {c["slug"] for c in candidates}

    for video_format, slug in made.items():
        assert slug not in slugs, f"{video_format} offered as a thumbnail candidate"
    assert real in slugs, "a real media page stopped being a candidate"


async def test_candidate_query_excludes_url_detectable_audio_only_formats():
    # WO-85. mp3/wav is real, fetchable media (unlike the embed formats
    # above) but ffmpeg's `-frames:v 1` can only ever fail against it --
    # excluded in SQL for the same "never hand the sweep a doomed
    # candidate" reason as the embed formats.
    made = {}
    for video_format, video_url in _AUDIO_ONLY_URLS.items():
        made[video_format] = await _page(
            f"audio-only-{video_format}", video_url, video_format
        )
    real = await _page("real-mp4-2", _REAL_MEDIA["mp4"], "mp4")

    candidates = await crud.list_pages_missing_default_thumbnail(limit=500)
    slugs = {c["slug"] for c in candidates}

    for video_format, slug in made.items():
        assert slug not in slugs, f"{video_format} offered as a thumbnail candidate"
    assert real in slugs, "a real media page stopped being a candidate"


async def test_candidate_query_excludes_a_confirmed_no_video_stream_page():
    # WO-85, the other half: audio hiding *inside* an mp4/m3u8 container
    # (Granicus/IQM2), which looks identical to a real video file by URL
    # or video_format alone -- only known once extract_and_store() has
    # actually probed it and called crud.mark_no_video_stream_confirmed().
    # Before this, a page in this state stayed a "candidate" forever: it
    # has no default frame (extraction always fails) and nothing ever
    # stopped offering it up again.
    confirmed_url = "https://archive-stream.granicus.com/x/audio-only.m3u8"
    confirmed_slug = await _page("confirmed-no-video-stream", confirmed_url, "m3u8")
    real = await _page("real-m3u8-2", _REAL_MEDIA["m3u8"], "m3u8")

    page = await crud.get_page_by_slug(confirmed_slug)
    await crud.mark_no_video_stream_confirmed(page["id"])

    candidates = await crud.list_pages_missing_default_thumbnail(limit=500)
    slugs = {c["slug"] for c in candidates}

    assert confirmed_slug not in slugs, "a confirmed audio-only page stayed a candidate"
    assert real in slugs, "a real media page stopped being a candidate"
    assert await crud.is_no_video_stream_confirmed(page["id"]) is True
