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
    IFRAME_EMBED_VIDEO_FORMATS,
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
