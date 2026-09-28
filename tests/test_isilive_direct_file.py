"""A bare iSiLIVE file URL reads the caption file next to it (WO-1155).

Real fixtures, recorded live 2026-09-28 (one request at a time, 3 s
apart): the caption files for Miramichi NB (`miramichi/2026-05-19.mp4`,
full file, 826 cues), Bracebridge ON (full file, 297 cues) and Green
Cove Springs FL (first 99 cues of a 241 KB file). Whitehorse YT's and
Nunavut's `.vtt` answered 404. The Miramichi, Whitehorse and Bracebridge
`/download/` files answered HEAD with `Content-Type: video/mp4`.

No real HTTP request is made: `aiohttp_mock.mock_session` answers every
HEAD/GET from the routes below, and fails the test on any other URL.
"""

import pytest

from app.platforms.base import detect_platform
from app.platforms.direct_file import (
    DirectFileAssetFinder,
    _resolve_direct_media_url,
    is_direct_file_url,
    parse_isilive_file_url,
)
from app.platforms.escribe import KNOWN_LANGUAGE_SUFFIXES
from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture_bytes

MIRAMICHI_DOWNLOAD = "https://video.isilive.ca/download/miramichi/2026-05-19.mp4"
BRACEBRIDGE_FILE = (
    "2024-08-09%20Committee%20of%20Adjustment%20for%20Minor%20Variances%20Meeting.mp4"
)
BRACEBRIDGE_DOWNLOAD = (
    f"https://video.isilive.ca/download/bracebridge/{BRACEBRIDGE_FILE}"
)
GCS_DOWNLOAD = (
    "https://video.isilive.ca/download/greencovesprings/2025-09-16Council.mp4"
)
WHITEHORSE_DOWNLOAD = "https://video.isilive.ca/download/whitehorse/2026-09-14.mp4"
NUNAVUT_DOWNLOAD = "https://video.isilive.ca/download/nunavut/2026/2026-05-22-eng.mp4"


def _vtt_urls(client: str, encoded_file: str) -> list:
    return [
        f"https://video.isilive.ca/{client}/{encoded_file}"
        + (f".{suffix}" if suffix else "")
        + ".vtt"
        for suffix in KNOWN_LANGUAGE_SUFFIXES
    ]


def _routes(client, encoded_file, download_url, fixture=None):
    """HEAD on the download file, plus every caption URL: the English one
    from `fixture` when given, 404 for all others (the real answer for
    every language suffix on these files)."""
    vtts = _vtt_urls(client, encoded_file)
    gets = {u: FakeResponse(status=404, text="Not Found") for u in vtts}
    if fixture:
        gets[vtts[0]] = FakeResponse(
            status=200, raw=load_fixture_bytes("isilive", fixture)
        )
    heads = {
        download_url: FakeResponse(
            status=200,
            headers={"Content-Type": "video/mp4"},
        )
    }
    return gets, heads


@pytest.mark.parametrize(
    "url, expected",
    [
        (MIRAMICHI_DOWNLOAD, ("miramichi", "2026-05-19.mp4")),
        (
            "https://video.isilive.ca/miramichi/2026-05-19.mp4",
            ("miramichi", "2026-05-19.mp4"),
        ),
        (
            "https://video.isilive.ca/play/miramichi/2026-05-19.mp4",
            ("miramichi", "2026-05-19.mp4"),
        ),
        (
            "https://video.isilive.ca/whitehorse/2026-09-14.mp4.html",
            ("whitehorse", "2026-09-14.mp4"),
        ),
        (
            "https://cdn1.isilive.ca/vod/_definst_/mp4:miramichi/2026-05-19.mp4/playlist.m3u8",
            ("miramichi", "2026-05-19.mp4"),
        ),
        (NUNAVUT_DOWNLOAD, ("nunavut", "2026/2026-05-22-eng.mp4")),
        (BRACEBRIDGE_DOWNLOAD, ("bracebridge", BRACEBRIDGE_FILE)),
        # An unencoded space is normalised to the same encoded form.
        (
            "https://video.isilive.ca/download/bracebridge/"
            "2024-08-09 Committee of Adjustment for Minor Variances Meeting.mp4",
            ("bracebridge", BRACEBRIDGE_FILE),
        ),
        # Not a recording: the live-stream player, the player's own
        # assets, and the caption file itself.
        ("https://video.isilive.ca/play/bracebridge/live", None),
        ("https://video.isilive.ca/cdn/isi_player.js", None),
        ("https://video.isilive.ca/miramichi/2026-05-19.mp4.vtt", None),
        ("https://example.com/miramichi/2026-05-19.mp4", None),
    ],
)
def test_parse_isilive_file_url(url, expected):
    assert parse_isilive_file_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://video.isilive.ca/play/miramichi/2026-05-19.mp4",
        "https://video.isilive.ca/whitehorse/2026-09-14.mp4.html",
        "https://cdn1.isilive.ca/vod/_definst_/mp4:miramichi/2026-05-19.mp4/playlist.m3u8",
    ],
)
def test_every_isilive_shape_routes_to_direct_file_download(url):
    assert is_direct_file_url(url)
    assert detect_platform(url) == "direct_file"
    client, _ = parse_isilive_file_url(url)
    assert _resolve_direct_media_url(url).startswith(
        f"https://video.isilive.ca/download/{client}/"
    )


async def test_miramichi_download_url_resolves_with_captions():
    gets, heads = _routes(
        "miramichi",
        "2026-05-19.mp4",
        MIRAMICHI_DOWNLOAD,
        "miramichi_2026-05-19.mp4.vtt",
    )
    with mock_session(gets, head_routes=heads):
        result = await DirectFileAssetFinder().resolve(MIRAMICHI_DOWNLOAD)

    assert result.platform == "direct_file"
    assert result.source_url == MIRAMICHI_DOWNLOAD
    assert result.video_url == MIRAMICHI_DOWNLOAD
    assert result.video_format == "mp4"
    assert len(result.segments) == 826
    assert result.segments[0].start == 65.548
    assert result.segments[0].text.startswith("Good evening everybody.")
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []
    # The folder name is iSiLIVE's customer name, never the government.
    assert result.jurisdiction is None


async def test_bracebridge_player_page_resolves_to_file_with_captions():
    page_url = f"https://video.isilive.ca/bracebridge/{BRACEBRIDGE_FILE}.html"
    gets, heads = _routes(
        "bracebridge",
        BRACEBRIDGE_FILE,
        BRACEBRIDGE_DOWNLOAD,
        "bracebridge_2024-08-09_coa.mp4.vtt",
    )
    with mock_session(gets, head_routes=heads):
        result = await DirectFileAssetFinder().resolve(page_url)

    assert result.source_url == page_url
    assert result.video_url == BRACEBRIDGE_DOWNLOAD
    assert len(result.segments) == 297
    assert result.segments[0].text.startswith("Thank you for your patience")
    assert result.jurisdiction is None


async def test_green_cove_springs_hls_url_resolves_with_captions():
    hls_url = (
        "https://cdn1.isilive.ca/vod/_definst_/mp4:greencovesprings/"
        "2025-09-16Council.mp4/playlist.m3u8"
    )
    gets, heads = _routes(
        "greencovesprings",
        "2025-09-16Council.mp4",
        GCS_DOWNLOAD,
        "greencovesprings_2025-09-16Council_head.mp4.vtt",
    )
    with mock_session(gets, head_routes=heads):
        result = await DirectFileAssetFinder().resolve(hls_url)

    assert result.video_url == GCS_DOWNLOAD
    assert len(result.segments) == 99
    assert result.transcript_language == "en"


@pytest.mark.parametrize(
    "url, client, encoded_file, download_url",
    [
        (
            "https://video.isilive.ca/whitehorse/2026-09-14.mp4.html",
            "whitehorse",
            "2026-09-14.mp4",
            WHITEHORSE_DOWNLOAD,
        ),
        (
            NUNAVUT_DOWNLOAD,
            "nunavut",
            "2026/2026-05-22-eng.mp4",
            NUNAVUT_DOWNLOAD,
        ),
    ],
)
async def test_no_caption_file_keeps_plain_file_result(
    url, client, encoded_file, download_url
):
    gets, heads = _routes(client, encoded_file, download_url)
    with mock_session(gets, head_routes=heads):
        result = await DirectFileAssetFinder().resolve(url)

    assert result.platform == "direct_file"
    assert result.video_url == download_url
    assert result.video_format == "mp4"
    assert result.segments == []
    assert result.transcript_language is None
    assert result.transcript_warnings == []
    assert result.video_warnings == []
    assert result.jurisdiction is None


async def test_unconfirmed_file_skips_caption_lookup():
    """A download that is not a video never triggers caption requests
    (mock_session would fail on any unrouted GET)."""
    heads = {
        MIRAMICHI_DOWNLOAD: FakeResponse(
            status=200, headers={"Content-Type": "text/html"}
        )
    }
    with mock_session({}, head_routes=heads):
        result = await DirectFileAssetFinder().resolve(MIRAMICHI_DOWNLOAD)

    assert result.video_url is None
    assert result.segments == []
