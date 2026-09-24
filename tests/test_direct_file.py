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
    _classify_laserfiche_media,
    _is_laserfiche_edoc_url,
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
# WO-1042: the same real Kemmerer file id, through its other two
# recognized shapes -- see direct_file.py's own `_drive_file_id()`
# comment. `DRIVE_DOWNLOAD_URL` above is a real, confirmed-live URL
# (martin.k12.mn.us, us:sd:2718960, confirmed 2026-09-24 -- see
# scripts/meeting_finder_followups.py's docstring); `DRIVE_UC_URL` is
# Drive's own other documented direct-download alias, not yet seen on a
# real government site.
DRIVE_UC_URL = f"https://drive.google.com/uc?id={DRIVE_FILE_ID}"

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

# --- WO-317 (2026-09-12): audio-only Laserfiche -------------------------
# Two real, independently-confirmed audio-only sources named in
# BACKLOG.md's Laserfiche entry (WO-305/WO-315's full-population census).
# Re-derived live before building, per CLAUDE.md's "a backlog entry is a
# lead, not a spec" rule -- and found TWO distinct real URL shapes, not
# one (see direct_file.py's own module docstring's "Audio-only
# Laserfiche" section for the full investigation).

# Deschutes County, OR -- same extension-less `ElectronicFile.aspx?docid=`
# shape as Jefferson County's video. Historic Landmarks Commission audio
# minutes, 2021-08-05 (the newest entry in that folder), confirmed live
# 2026-09-12 via a real browser walk of weblink.deschutes.org (docid
# 94746, zero cookies, 31.7-minute real duration via ffprobe).
DESCHUTES_AUDIO_URL = (
    "https://weblink.deschutes.org/WebLink/ElectronicFile.aspx"
    "?docid=94746&dbid=0&repo=LFPUB"
)
# The real first-64-bytes response, confirmed live 2026-09-12 (a ranged
# GET with `Accept-Encoding: identity` -- see module docstring's caution
# on this host's own gzip-on-range-response bug, hit on Ramsey below, not
# Deschutes): a genuine ID3 tag, not the ISO-BMFF video this branch used
# to assume.
DESCHUTES_MP3_MAGIC_BYTES = (
    b"ID3\x04\x00\x00\x00\x00\x01\x00TXXX\x00\x00\x00\x12\x00\x00\x03major_brand"
    b"\x00mp42\x00TXXX\x00\x00\x00\x11\x00\x00\x03minor_version\x000"
)

# Ramsey city, MN -- an OLDER WebLink 9 install's different, friendlier
# `/WebLink/<n>/edoc/<docid>/<filename>` download path (a real extension
# already in the URL, unlike the docid-query shape above). Council Work
# Session, 2026-09-08 (the newest entry in the "Recordings - Audio/Video"
# folder), confirmed live 2026-09-12 via a real browser walk of
# weblink.cityoframsey.com (docid 813049, zero cookies once the
# gzip-on-range quirk is worked around, 82-minute real duration via
# ffprobe).
RAMSEY_AUDIO_URL = (
    "https://weblink.cityoframsey.com/WebLink/0/edoc/813049/"
    "Meeting%20AudioVideo%20-%20Council%20Work%20Session%20-%2009082026.mp3"
)
# The real first-64-bytes response, confirmed live 2026-09-12 -- also a
# genuine ID3 tag. A first attempt with aiohttp's default
# `Accept-Encoding: gzip` got a corrupt, undecompressable response from
# this host's IIS dynamic-compression module misapplying gzip to a
# 64-byte RANGED response (`zlib.error: invalid code lengths set`) --
# `curl` never showed this because it doesn't request compression by
# default. See `_laserfiche_classify_media()`'s own docstring.
RAMSEY_MP3_MAGIC_BYTES = (
    b"ID3\x03\x00\x00\x00\x00\x07vTXXX\x00\x00\x00\x0e\x00\x00\x00DDJ/VER"
    b"\x000100\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
)


@pytest.mark.parametrize(
    "url,expected",
    [
        (PALISADE_URL, True),
        (CAYUGA_HEIGHTS_URL, True),
        (DROPBOX_URL, True),
        (DRIVE_VIEW_URL, True),
        # WO-1042: the two other real shapes the same Drive file shows up
        # under -- see _drive_file_id()'s own comment.
        (DRIVE_DOWNLOAD_URL, True),
        (DRIVE_UC_URL, True),
        (JEFFERSON_VIDEO_URL, True),
        (JEFFERSON_CAPTION_URL, True),
        # WO-317: both real audio-only shapes are recognized too.
        (DESCHUTES_AUDIO_URL, True),
        (RAMSEY_AUDIO_URL, True),
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


def test_resolve_direct_media_url_leaves_an_already_rewritten_download_url_alone():
    """WO-1042: a government whose site links straight to the already-
    rewritten download URL (12 real rows confirmed live 2026-09-24, see
    scripts/meeting_finder_followups.py's docstring) shouldn't get
    rewritten a second time."""
    assert _resolve_direct_media_url(DRIVE_DOWNLOAD_URL) == DRIVE_DOWNLOAD_URL


def test_resolve_direct_media_url_rewrites_the_uc_alias_too():
    assert _resolve_direct_media_url(DRIVE_UC_URL) == DRIVE_DOWNLOAD_URL


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


async def test_resolve_confirms_an_already_rewritten_drive_download_url():
    """WO-1042: Meeting Finder (and a government site directly) can hand
    this adapter the already-rewritten download URL instead of the
    classic share link -- confirm it resolves the same way, unrewritten."""
    finder = DirectFileAssetFinder()
    routes = {
        DRIVE_DOWNLOAD_URL: FakeResponse(
            status=200, headers={"Content-Type": "video/mp4"}
        )
    }
    with mock_session({}, head_routes=routes):
        result = await finder.resolve(DRIVE_DOWNLOAD_URL)
    assert result.source_url == DRIVE_DOWNLOAD_URL
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
    # WO-1045: a Dropbox link is checked by ranged GET, never HEAD --
    # an empty `head_routes` fails the test if a HEAD is attempted.
    with mock_session(routes, head_routes={}):
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


# --- WO-317 (2026-09-12): audio-only Laserfiche -------------------------


def test_is_laserfiche_edoc_url():
    assert _is_laserfiche_edoc_url(RAMSEY_AUDIO_URL) is True
    assert _is_laserfiche_edoc_url(DESCHUTES_AUDIO_URL) is False
    assert _is_laserfiche_edoc_url(PALISADE_URL) is False


def test_classify_laserfiche_media_recognizes_real_video_bytes():
    assert _classify_laserfiche_media(JEFFERSON_MP4_MAGIC_BYTES) == "video"


def test_classify_laserfiche_media_recognizes_real_mp3_bytes():
    # Both real WO-317 fixtures are ID3-tagged MP3 -- confirmed live
    # against two independent governments on two different WebLink
    # generations, not assumed from one.
    assert _classify_laserfiche_media(DESCHUTES_MP3_MAGIC_BYTES) == "mp3"
    assert _classify_laserfiche_media(RAMSEY_MP3_MAGIC_BYTES) == "mp3"


def test_classify_laserfiche_media_recognizes_a_raw_mpeg_frame_sync():
    # No real fixture on file needed this branch (both real examples carry
    # an ID3 tag) -- synthetic bytes, not independently confirmed live,
    # covering the no-ID3-tag MP3 case queue_probe.py's own bare-.mp3
    # handling already assumes exists.
    assert _classify_laserfiche_media(b"\xff\xfb\x90\x00" + b"\x00" * 60) == "mp3"


def test_classify_laserfiche_media_recognizes_m4a_brand():
    # Synthetic bytes -- no real Laserfiche .m4a fixture is on file (see
    # direct_file.py's own module docstring caution); this only checks
    # the brand-string distinction against Apple's documented "M4A "
    # brand value, not a live-confirmed byte-for-byte match.
    synthetic_m4a = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A mp42"
    assert _classify_laserfiche_media(synthetic_m4a) == "m4a"


def test_classify_laserfiche_media_returns_none_for_unrecognized_bytes():
    assert _classify_laserfiche_media(b"%PDF-1.4 not media at all") is None


async def test_resolve_deschutes_audio_shape_sets_mp3_format():
    finder = DirectFileAssetFinder()
    routes = {
        DESCHUTES_AUDIO_URL: FakeResponse(
            status=206,
            raw=DESCHUTES_MP3_MAGIC_BYTES,
            headers={"Content-Type": "application/octet-stream"},
        ),
        # The sibling-docid caption check IS attempted for this shape
        # (docid - 1) -- a real, expected miss (no VTT next to a plain
        # audio recording), not a Zoom cloud recording.
        "https://weblink.deschutes.org/WebLink/ElectronicFile.aspx"
        "?docid=94745&dbid=0&repo=LFPUB": FakeResponse(status=404),
    }
    with mock_session(routes):
        result = await finder.resolve(DESCHUTES_AUDIO_URL)
    assert result.platform == "direct_file"
    assert result.video_url == DESCHUTES_AUDIO_URL
    assert result.video_format == "mp3"
    assert result.video_warnings == []
    assert result.segments == []
    assert "checked the docid immediately before it" in result.transcript_warnings[0]


async def test_resolve_ramsey_edoc_shape_sets_mp3_format_and_skips_caption_lookup():
    finder = DirectFileAssetFinder()
    routes = {
        RAMSEY_AUDIO_URL: FakeResponse(
            status=206,
            raw=RAMSEY_MP3_MAGIC_BYTES,
            headers={"Content-Type": "application/octet-stream"},
        ),
    }
    with mock_session(routes):
        result = await finder.resolve(RAMSEY_AUDIO_URL)
    assert result.platform == "direct_file"
    assert result.video_url == RAMSEY_AUDIO_URL
    assert result.video_format == "mp3"
    assert result.video_warnings == []
    assert result.segments == []
    # The edoc shape has no sibling-docid convention to check at all --
    # the wording must not claim a lookup was attempted (WO-317).
    assert "no known caption convention" in result.transcript_warnings[0]
    assert "checked the docid" not in result.transcript_warnings[0]


async def test_resolve_degrades_gracefully_for_edoc_shape_when_bytes_are_not_media():
    finder = DirectFileAssetFinder()
    routes = {
        RAMSEY_AUDIO_URL: FakeResponse(
            status=200,
            raw=b"<html>Error.aspx</html>",
            headers={"Content-Type": "text/html"},
        ),
    }
    with mock_session(routes):
        result = await finder.resolve(RAMSEY_AUDIO_URL)
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


# --- Audio-only own-domain recordings (Ryan, 2026-09-22: in scope) -------
#
# Real fixtures, both confirmed live 2026-09-22: Allouez village, WI posts
# its board meetings as a bare .mp3 to its own S3 bucket; Farmington city,
# UT posts its Planning Commission recordings as a bare .mp3 under its own
# wp-content/uploads. Both answer a plain HEAD with a real
# `Content-Type: audio/mpeg` -- the exact shape this adapter already
# resolves for video, previously rejected only because `resolve()`'s gate
# required a `video/` prefix.

ALLOUEZ_URL = (
    "https://allouez.s3.amazonaws.com/media/2026/09/16090630/"
    "Village-Board-9-15-2026.mp3"
)
FARMINGTON_PC_URL = (
    "https://farmington.utah.gov/wp-content/uploads/2026/09/"
    "09.03.26-PC-General-Session-Q-SYS.mp3"
)


@pytest.mark.parametrize("url", [ALLOUEZ_URL, FARMINGTON_PC_URL])
def test_is_direct_file_url_recognizes_a_bare_mp3(url):
    assert is_direct_file_url(url) is True


async def test_resolve_confirms_a_real_audio_only_file():
    finder = DirectFileAssetFinder()
    routes = {
        ALLOUEZ_URL: FakeResponse(status=200, headers={"Content-Type": "audio/mpeg"})
    }
    with mock_session({}, head_routes=routes):
        result = await finder.resolve(ALLOUEZ_URL)
    assert result.platform == "direct_file"
    assert result.video_url == ALLOUEZ_URL
    assert result.video_format == "mp3"
    assert result.video_warnings == []


async def test_resolve_confirms_a_second_independent_audio_only_file():
    finder = DirectFileAssetFinder()
    routes = {
        FARMINGTON_PC_URL: FakeResponse(
            status=200, headers={"Content-Type": "audio/mpeg"}
        )
    }
    with mock_session({}, head_routes=routes):
        result = await finder.resolve(FARMINGTON_PC_URL)
    assert result.video_url == FARMINGTON_PC_URL
    assert result.video_format == "mp3"


async def test_resolve_still_degrades_gracefully_for_non_media_content_type():
    # The video-only regression check: an ordinary HTML page still isn't
    # accepted just because the audio branch was added.
    finder = DirectFileAssetFinder()
    routes = {
        DROPBOX_URL + "?dl=1": FakeResponse(
            status=200, headers={"Content-Type": "text/html"}
        )
    }
    # WO-1045: a Dropbox link is checked by ranged GET, never HEAD --
    # an empty `head_routes` fails the test if a HEAD is attempted.
    with mock_session(routes, head_routes={}):
        result = await finder.resolve(DROPBOX_URL)
    assert result.video_url is None
    assert "playable video or audio" in result.video_warnings[0]


# --- WO-1045 (2026-09-24): HEAD refused, or unusable ---------------------
# Both hosts below were found walking county meeting pages and confirmed
# live the same day; the headers and first bytes are the real ones
# captured with curl (see direct_file.py's module docstring).

# Jefferson County, TX: the MP4 behind
# `jeffersoncountytx.gov/jcagenda/CourtVideo.aspx?f=JCCC092226`. IIS
# answers HEAD with 405 / `Allow: GET` and no Content-Type.
JEFFERSON_TX_URL = "https://jeffersoncountytx.gov/blobs/agenda/video_pl/JCCC092226.mp4"
# The real first 32 bytes of that file's 206 ranged response.
JEFFERSON_TX_FIRST_BYTES = bytes.fromhex(
    "000000206674797069736f6d0000020069736f6d69736f32617663316d703431"
)

# Ingham County, MI: a Board of Commissioners recording shared on Dropbox.
INGHAM_DROPBOX_URL = (
    "https://www.dropbox.com/scl/fi/9qi96bax8d2qvzbiwb5cq/9.22.26-BOC.mp4"
    "?rlkey=mw0v13mqiogaz6u0hp2ep12ew&st=k693mj6p&dl=0"
)
INGHAM_DROPBOX_DL_URL = (
    "https://www.dropbox.com/scl/fi/9qi96bax8d2qvzbiwb5cq/9.22.26-BOC.mp4"
    "?rlkey=mw0v13mqiogaz6u0hp2ep12ew&st=k693mj6p&dl=1"
)
# The real first 16 bytes of its 206 ranged response (`ftypmp42`).
INGHAM_FIRST_BYTES = bytes.fromhex("00000018667479706d70343200000000")


async def test_resolve_falls_back_to_a_ranged_get_when_head_is_405():
    finder = DirectFileAssetFinder()
    head_routes = {
        JEFFERSON_TX_URL: FakeResponse(
            status=405, headers={"Allow": "GET", "Server": "Microsoft-IIS/10.0"}
        )
    }
    routes = {
        JEFFERSON_TX_URL: FakeResponse(
            status=206,
            raw=JEFFERSON_TX_FIRST_BYTES,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": "bytes 0-1023/1131384015",
            },
        )
    }
    with mock_session(routes, head_routes=head_routes):
        result = await finder.resolve(JEFFERSON_TX_URL)
    assert result.video_url == JEFFERSON_TX_URL
    assert result.video_format == "mp4"
    assert result.video_warnings == []


async def test_resolve_still_warns_when_head_is_405_and_the_get_is_html():
    # The fallback is one more test, not a looser one: an HTML answer
    # to the ranged GET is still refused.
    finder = DirectFileAssetFinder()
    head_routes = {JEFFERSON_TX_URL: FakeResponse(status=405)}
    routes = {
        JEFFERSON_TX_URL: FakeResponse(
            status=200,
            raw=b"<!DOCTYPE html><html><body>Not found</body></html>",
            headers={"Content-Type": "text/html"},
        )
    }
    with mock_session(routes, head_routes=head_routes):
        result = await finder.resolve(JEFFERSON_TX_URL)
    assert result.video_url is None
    assert "text/html" in result.video_warnings[0]


def test_resolve_direct_media_url_turns_a_dropbox_dl_0_link_into_dl_1():
    assert _resolve_direct_media_url(INGHAM_DROPBOX_URL) == INGHAM_DROPBOX_DL_URL


def test_resolve_direct_media_url_turns_a_dropbox_raw_1_link_into_dl_1():
    raw_form = INGHAM_DROPBOX_URL.replace("&dl=0", "&raw=1")
    assert _resolve_direct_media_url(raw_form) == INGHAM_DROPBOX_DL_URL


async def test_resolve_confirms_a_dropbox_mp4_by_ranged_get_not_head():
    # Dropbox's download host answers HEAD with `application/json` and a
    # body aiohttp can't parse; its ranged GET answers the generic
    # `application/binary` -- so the MP4 signature is what confirms it.
    finder = DirectFileAssetFinder()
    routes = {
        INGHAM_DROPBOX_DL_URL: FakeResponse(
            status=206,
            raw=INGHAM_FIRST_BYTES,
            headers={
                "Content-Type": "application/binary",
                "Content-Range": "bytes 0-1023/259815205",
            },
        )
    }
    with mock_session(routes, head_routes={}):
        result = await finder.resolve(INGHAM_DROPBOX_URL)
    assert result.source_url == INGHAM_DROPBOX_URL
    assert result.video_url == INGHAM_DROPBOX_DL_URL
    assert result.video_format == "mp4"
    assert result.video_warnings == []
