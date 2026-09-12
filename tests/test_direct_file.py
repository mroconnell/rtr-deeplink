"""Tests for the direct_file.py adapter (WO-303, 2026-09-12).

Real fixtures: Palisade town CO, Dundee city OR, and Cayuga Heights
village NY all serve a real, clearly-labeled meeting recording as a bare
.mp4 on their own domain, confirmed live to answer a plain HEAD with a
real `Content-Type: video/mp4` (see BACKLOG_DONE.md's WO-303 entry and
BACKLOG.md's WO-284 entry this closes). Enterprise city, OR posts
recordings to Dropbox; Kemmerer city, WY shares real Google Drive files
whose virus-scan interstitial (Drive's own behavior on any file too
large to scan) is confirmed live to be bypassable with `confirm=t`, no
sign-in required -- see direct_file.py's own module docstring for the
full investigation and the caution on Enterprise's one stored URL, which
is missing its `rlkey=` token and could not be verified end to end.

Real HTTP responses are never made in tests -- `aiohttp_mock.mock_session`
patches `session.head()`/`session.get()` to canned `FakeResponse`s built
from the actual headers this WO captured live (see BACKLOG_DONE.md).
"""

import pytest

from app.platforms.direct_file import (
    DirectFileAssetFinder,
    _resolve_direct_media_url,
    is_direct_file_url,
)

from aiohttp_mock import FakeResponse, mock_session

PALISADE_URL = (
    "https://palisade.colorado.gov/sites/g/files/lrnvjt1146/files/"
    "Zoom-Video_Board-of-Trustees_08.25.2026.mp4"
)
CAYUGA_HEIGHTS_URL = (
    "https://cayugaheights.gov/wp-content/uploads/2025/10/video1478511047.mp4"
)
DROPBOX_URL = (
    "https://www.dropbox.com/scl/fi/jf8u7cx0atqmkirxzw6ec/"
    "2025-09-09-City-Council-Recording.mp4"
)
DRIVE_VIEW_URL = (
    "https://drive.google.com/file/d/1R6UKdoiv7_3nXk-sEmH7gil4toaEA1su/"
    "view?usp=share_link"
)
DRIVE_FILE_ID = "1R6UKdoiv7_3nXk-sEmH7gil4toaEA1su"
DRIVE_DOWNLOAD_URL = (
    f"https://drive.usercontent.google.com/download?id={DRIVE_FILE_ID}"
    "&export=download&confirm=t"
)


@pytest.mark.parametrize(
    "url,expected",
    [
        (PALISADE_URL, True),
        (CAYUGA_HEIGHTS_URL, True),
        (DROPBOX_URL, True),
        (DRIVE_VIEW_URL, True),
        # A Drive FOLDER listing is a distinct, out-of-scope shape (see
        # module docstring) -- no file id to extract, no video extension.
        (
            "https://drive.google.com/drive/folders/1Je8_qcPnv1mh2tdbUhjDtSeWllW9lnT8",
            False,
        ),
        ("https://example.gov/agendas", False),
    ],
)
def test_is_direct_file_url(url, expected):
    assert is_direct_file_url(url) is expected


def test_resolve_direct_media_url_leaves_a_first_party_file_untouched():
    assert _resolve_direct_media_url(PALISADE_URL) == PALISADE_URL
    assert _resolve_direct_media_url(CAYUGA_HEIGHTS_URL) == CAYUGA_HEIGHTS_URL


def test_resolve_direct_media_url_rewrites_a_drive_view_link():
    assert _resolve_direct_media_url(DRIVE_VIEW_URL) == DRIVE_DOWNLOAD_URL


def test_resolve_direct_media_url_appends_dl_1_to_a_dropbox_link():
    assert _resolve_direct_media_url(DROPBOX_URL) == DROPBOX_URL + "?dl=1"


def test_resolve_direct_media_url_replaces_an_existing_dl_param():
    # Dropbox's own share links default to `?dl=0` -- confirm the rewrite
    # replaces it rather than appending a second, conflicting `dl=`.
    assert (
        _resolve_direct_media_url(DROPBOX_URL + "?rlkey=abc123&dl=0")
        == DROPBOX_URL + "?rlkey=abc123&dl=1"
    )


async def test_resolve_confirms_a_real_first_party_video_file():
    finder = DirectFileAssetFinder()
    routes = {
        PALISADE_URL: FakeResponse(status=200, headers={"Content-Type": "video/mp4"})
    }
    with mock_session({}, head_routes=routes):
        result = await finder.resolve(PALISADE_URL)
    assert result.platform == "direct_file"
    assert result.video_url == PALISADE_URL
    assert result.video_format == "mp4"
    assert result.video_warnings == []


async def test_resolve_rewrites_and_confirms_a_drive_file():
    finder = DirectFileAssetFinder()
    routes = {
        DRIVE_DOWNLOAD_URL: FakeResponse(
            status=200, headers={"Content-Type": "video/mp4"}
        )
    }
    with mock_session({}, head_routes=routes):
        result = await finder.resolve(DRIVE_VIEW_URL)
    assert result.source_url == DRIVE_VIEW_URL
    assert result.video_url == DRIVE_DOWNLOAD_URL


async def test_resolve_degrades_gracefully_when_content_type_is_not_video():
    # The real, honest shape a caller hits if a share link's token has
    # expired or the file was removed -- Drive/Dropbox both fall back to
    # an ordinary HTML page in that case (confirmed live for the
    # Enterprise, OR fixture missing its rlkey -- see module docstring).
    finder = DirectFileAssetFinder()
    routes = {
        DROPBOX_URL + "?dl=1": FakeResponse(
            status=200, headers={"Content-Type": "text/html"}
        )
    }
    with mock_session({}, head_routes=routes):
        result = await finder.resolve(DROPBOX_URL)
    assert result.video_url is None
    assert result.video_warnings
    assert "text/html" in result.video_warnings[0]
