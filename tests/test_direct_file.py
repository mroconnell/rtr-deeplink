"""Tests for the direct_file.py adapter (WO-303, 2026-09-12; Laserfiche
WebLink support added WO-304, 2026-09-12).

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

Jefferson County, WA's Laserfiche WebLink fixtures (WO-304): the docids,
byte counts and caption content below are all real, captured live
2026-09-12 against `test.co.jefferson.wa.us/WeblinkExternal/` with zero
cookies and no session -- see direct_file.py's own module docstring for
the full investigation, including the confirmed `docid - 1` caption
pattern (checked against TWO independent real meetings, not one).
"""

import pytest

from app.platforms.direct_file import (
    DirectFileAssetFinder,
    _is_laserfiche_weblink_url,
    _laserfiche_sibling_caption_url,
    _resolve_direct_media_url,
    is_direct_file_url,
)
from app.utils import url_guard
from conftest import load_fixture

from aiohttp_mock import FakeResponse, mock_session


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """`guarded_get()` (used for the Laserfiche caption fetch below)
    resolves hostnames for real unless patched -- same fixture as
    test_wistia.py's/test_vimeo.py's identical one, so this suite stays
    network-free."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


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

# Jefferson County, WA's real September 8, 2026 Board of County
# Commissioners meeting -- video docid 10559483, caption docid 10559482
# (docid - 1, the confirmed real pattern -- see module docstring).
JEFFERSON_VIDEO_URL = (
    "https://test.co.jefferson.wa.us/WeblinkExternal/ElectronicFile.aspx"
    "?docid=10559483&dbid=0&repo=Jefferson"
)
JEFFERSON_CAPTION_URL = (
    "https://test.co.jefferson.wa.us/WeblinkExternal/ElectronicFile.aspx"
    "?docid=10559482&dbid=0&repo=Jefferson"
)
# The real ISO-BMFF header bytes at the start of Jefferson County's real
# MP4 response (`ftypmp42` -- confirmed live 2026-09-12).
JEFFERSON_MP4_MAGIC_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"


@pytest.mark.parametrize(
    "url,expected",
    [
        (PALISADE_URL, True),
        (CAYUGA_HEIGHTS_URL, True),
        (DROPBOX_URL, True),
        (DRIVE_VIEW_URL, True),
        (JEFFERSON_VIDEO_URL, True),
        (JEFFERSON_CAPTION_URL, True),
        # A Drive FOLDER listing is a distinct, out-of-scope shape (see
        # module docstring) -- no file id to extract, no video extension.
        (
            "https://drive.google.com/drive/folders/1Je8_qcPnv1mh2tdbUhjDtSeWllW9lnT8",
            False,
        ),
        # A Laserfiche WebLink page that ISN'T the document-download
        # endpoint (e.g. the folder-browsing SPA URL) has no docid at
        # all -- not recognized, same as any other non-media page.
        ("https://test.co.jefferson.wa.us/WeblinkExternal/browse.aspx", False),
        ("https://example.gov/agendas", False),
    ],
)
def test_is_direct_file_url(url, expected):
    assert is_direct_file_url(url) is expected


def test_is_laserfiche_weblink_url():
    assert _is_laserfiche_weblink_url(JEFFERSON_VIDEO_URL) is True
    assert _is_laserfiche_weblink_url(PALISADE_URL) is False
    assert _is_laserfiche_weblink_url(DRIVE_VIEW_URL) is False


def test_laserfiche_sibling_caption_url_is_docid_minus_one():
    assert _laserfiche_sibling_caption_url(JEFFERSON_VIDEO_URL) == JEFFERSON_CAPTION_URL
    # The second real, independently-confirmed meeting (2026-08-24) --
    # same pattern, different docids, so this isn't a one-example fluke.
    assert (
        _laserfiche_sibling_caption_url(
            "https://test.co.jefferson.wa.us/WeblinkExternal/ElectronicFile.aspx"
            "?docid=10549043&dbid=0&repo=Jefferson"
        )
        == "https://test.co.jefferson.wa.us/WeblinkExternal/ElectronicFile.aspx"
        "?docid=10549042&dbid=0&repo=Jefferson"
    )


def test_laserfiche_sibling_caption_url_is_none_for_a_non_laserfiche_url():
    assert _laserfiche_sibling_caption_url(PALISADE_URL) is None


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


# --- Laserfiche WebLink (WO-304) -----------------------------------------


async def test_resolve_confirms_and_attaches_real_captions_for_laserfiche():
    # The real end-to-end shape: a ranged GET on the video docid returns
    # real MP4 magic bytes (this host's Content-Type is always the
    # generic application/octet-stream, so the check can't use it), and
    # a plain GET on the sibling docid - 1 returns the real captured VTT.
    finder = DirectFileAssetFinder()
    vtt_body = load_fixture("direct_file", "captions_jefferson_county_wa_10559482.vtt")
    routes = {
        JEFFERSON_VIDEO_URL: FakeResponse(
            status=206,
            raw=JEFFERSON_MP4_MAGIC_BYTES,
            headers={"Content-Type": "application/octet-stream"},
        ),
        JEFFERSON_CAPTION_URL: FakeResponse(
            status=200,
            text=vtt_body,
            headers={"Content-Type": "application/octet-stream"},
        ),
    }
    with mock_session(routes):
        result = await finder.resolve(JEFFERSON_VIDEO_URL)
    assert result.platform == "direct_file"
    assert result.video_url == JEFFERSON_VIDEO_URL
    assert result.video_format == "mp4"
    assert result.video_warnings == []
    assert len(result.segments) == 1700  # the real cue count, WO-304
    assert result.segments[0].text.startswith("All right")
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []


async def test_resolve_degrades_gracefully_when_laserfiche_bytes_are_not_video():
    # The real, honest outcome if a docid ever pointed at something else
    # (a PDF, a dead link) -- no ISO-BMFF marker in the first bytes.
    finder = DirectFileAssetFinder()
    routes = {
        JEFFERSON_VIDEO_URL: FakeResponse(
            status=200,
            raw=b"%PDF-1.4 not a video at all",
            headers={"Content-Type": "application/octet-stream"},
        ),
    }
    with mock_session(routes):
        result = await finder.resolve(JEFFERSON_VIDEO_URL)
    assert result.video_url is None
    assert result.video_warnings
    assert "Laserfiche WebLink" in result.video_warnings[0]


async def test_resolve_warns_when_no_caption_sibling_is_found():
    # The confirmed real miss case: the video confirms fine, but docid - 1
    # isn't a real caption file (a 404, or some other document type) --
    # the page still ingests, just without a transcript.
    finder = DirectFileAssetFinder()
    routes = {
        JEFFERSON_VIDEO_URL: FakeResponse(
            status=200,
            raw=JEFFERSON_MP4_MAGIC_BYTES,
            headers={"Content-Type": "application/octet-stream"},
        ),
        JEFFERSON_CAPTION_URL: FakeResponse(status=404),
    }
    with mock_session(routes):
        result = await finder.resolve(JEFFERSON_VIDEO_URL)
    assert result.video_url == JEFFERSON_VIDEO_URL
    assert result.segments == []
    assert result.transcript_warnings
    assert "caption file" in result.transcript_warnings[0]
