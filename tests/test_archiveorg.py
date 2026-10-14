"""Internet Archive item pages (archive.org/details/{item_id}), WO-1962. Fixtures in tests/fixtures/archiveorg/ are real answers read live on 2026-10-14:
the metadata JSON for `bos-2021-05-11` (Foxborough select board, uploaded by the town's own station: .mp4 + .mp3, no caption file), the metadata JSON for a
mirror item of ORCA Media's YouTube channel (Berlin VT Selectboard, 2026-09-28: youtube-id, .en.vtt, .en.asr.srt) and the first 60 lines of that item's real
`.en.vtt`. The 404 / dark / no-media / SRT / date-fallback cases are synthetic edits of those real metadata shapes (no such live item was fetched)."""

import json
from unittest import mock

import aiohttp

from app.platforms.archiveorg import (
    ArchiveOrgAssetFinder,
    item_id_from_url,
    parse_length,
)
from app.platforms.base import detect_platform
from app.utils.gov_registry.registry import is_multi_gov_host
from app.utils.tenant_key import tenant_key

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

OWN_ID = "bos-2021-05-11"
OWN_PAGE = f"https://archive.org/details/{OWN_ID}"
OWN_META = f"https://archive.org/metadata/{OWN_ID}"

MIRROR_ID = "orcavt-Berlin_Selectboard_-_September_28_2026_BNS-CRVIP1m2Lo0"
MIRROR_PAGE = f"https://archive.org/details/{MIRROR_ID}"
MIRROR_META = f"https://archive.org/metadata/{MIRROR_ID}"
MIRROR_VTT = (
    f"https://archive.org/download/{MIRROR_ID}/"
    "Berlin_Selectboard_-_September_28_2026_BNS-CRVIP1m2Lo0.en.vtt"
)


def _own_meta() -> dict:
    return json.loads(load_fixture("archiveorg", "metadata_bos-2021-05-11.json"))


def _own_routes():
    return {
        OWN_META: FakeResponse(
            text=load_fixture("archiveorg", "metadata_bos-2021-05-11.json")
        )
    }


def _mirror_routes():
    return {
        MIRROR_META: FakeResponse(
            text=load_fixture("archiveorg", "metadata_orcavt.json")
        ),
        MIRROR_VTT: FakeResponse(
            text=load_fixture("archiveorg", "vtt_head_orcavt_berlin_selectboard.en.vtt")
        ),
    }


def test_details_pages_route_to_archiveorg_in_all_spellings():
    for url in (
        OWN_PAGE,
        f"http://archive.org/details/{OWN_ID}",
        f"https://www.archive.org/details/{OWN_ID}",
        f"{OWN_PAGE}/",
        f"{OWN_PAGE}?tab=about",
        f"{OWN_PAGE}#x",
    ):
        assert detect_platform(url) == "archiveorg", url
        assert item_id_from_url(url) == OWN_ID


def test_download_media_links_still_route_to_direct_file():
    mp4 = f"https://archive.org/download/{OWN_ID}/BOS2021_05_11.mp4"
    assert item_id_from_url(mp4) is None
    assert detect_platform(mp4) == "direct_file"
    mp3 = f"https://archive.org/download/{OWN_ID}/BOS2021_05_11.mp3"
    assert detect_platform(mp3) == "direct_file"


def test_other_archive_org_addresses_are_not_claimed():
    assert item_id_from_url("https://archive.org/search?query=x") is None
    assert item_id_from_url("https://archive.org/details/") is None
    assert item_id_from_url("https://archive.org/details/a/b") is None


async def test_own_station_upload_is_tier_3_with_mp4_and_metadata_date():
    with mock_session(_own_routes()):
        result = await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
    assert result.platform == "archiveorg"
    assert result.external_id == f"archiveorg:{OWN_ID}"
    assert result.title == "Foxborough Board of Selectmen Meeting 2021/05/11"
    assert result.date == "2021-05-11"
    assert (
        result.video_url == f"https://archive.org/download/{OWN_ID}/BOS2021_05_11.mp4"
    )
    assert result.video_format == "mp4"
    assert abs(result.video_duration_seconds - 4271.3) < 0.01
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]
    assert result.video_warnings == []
    # The creator is the station, not the government: no government field is set.
    assert result.jurisdiction is None
    assert result.meeting_body is None


async def test_own_station_upload_makes_exactly_one_request():
    seen = []
    original = aiohttp.ClientSession.get

    def spy(self, url, **kw):
        seen.append(str(url))
        return original(self, url, **kw)

    with mock_session(_own_routes()):
        with mock.patch.object(aiohttp.ClientSession, "get", spy):
            await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
    assert seen == [OWN_META]


async def test_youtube_mirror_gets_segments_external_id_and_both_notes():
    with mock_session(_mirror_routes()):
        result = await ArchiveOrgAssetFinder().resolve(MIRROR_PAGE)
    assert result.external_id == "youtube:CRVIP1m2Lo0"
    assert result.title == "Berlin Selectboard - September 28, 2026 [BNS]"
    assert result.date == "2026-10-02"
    assert result.video_url.endswith(
        "Berlin_Selectboard_-_September_28_2026_BNS-CRVIP1m2Lo0.mp4"
    )
    assert result.video_format == "mp4"
    assert result.video_duration_seconds == 5058.05
    assert len(result.segments) >= 3
    assert result.segments[0].text.startswith("Good evening everyone")
    warnings = result.transcript_warnings
    assert "Copy of a YouTube video held by the Internet Archive." in warnings
    assert "Captions were copied from the YouTube video." in warnings
    assert "Captions are archive.org's own speech recognition." not in warnings
    assert "No captions found for this video." not in warnings
    assert result.jurisdiction is None and result.meeting_body is None


async def test_mirror_without_a_readable_caption_file_falls_back_to_tier_3():
    routes = _mirror_routes()
    routes[MIRROR_VTT] = FakeResponse(status=503)
    with mock_session(routes):
        result = await ArchiveOrgAssetFinder().resolve(MIRROR_PAGE)
    assert result.video_url
    assert result.segments == []
    assert "No captions found for this video." in result.transcript_warnings


async def test_srt_is_used_when_there_is_no_vtt():
    meta = json.loads(load_fixture("archiveorg", "metadata_orcavt.json"))
    meta["files"] = [f for f in meta["files"] if not f["name"].endswith(".vtt")]
    srt_name = "Berlin_Selectboard_-_September_28_2026_BNS-CRVIP1m2Lo0.en.asr.srt"
    srt_url = f"https://archive.org/download/{MIRROR_ID}/{srt_name}"
    srt = (
        "1\n00:00:12,507 --> 00:00:15,000\nGood evening everyone\n\n"
        "2\n00:00:15,000 --> 00:00:18,000\nwelcome to the meeting\n"
    )
    routes = {
        MIRROR_META: FakeResponse(text=json.dumps(meta)),
        srt_url: FakeResponse(text=srt),
    }
    with mock_session(routes):
        result = await ArchiveOrgAssetFinder().resolve(MIRROR_PAGE)
    assert [s.text for s in result.segments] == [
        "Good evening everyone",
        "welcome to the meeting",
    ]
    assert "Captions are archive.org's own speech recognition." in (
        result.transcript_warnings
    )


async def test_missing_item_gives_a_warning_and_no_exception():
    for response in (FakeResponse(status=404), FakeResponse(text="{}")):
        with mock_session({OWN_META: response}):
            result = await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
        assert result.video_url is None
        assert result.video_warnings
        assert result.segments == []


async def test_dark_item_gives_a_warning_and_no_video():
    meta = _own_meta()
    meta["is_dark"] = True
    with mock_session({OWN_META: FakeResponse(text=json.dumps(meta))}):
        result = await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
    assert result.video_url is None
    assert "restricted" in result.video_warnings[0]


async def test_item_with_no_mp4_or_mp3_gives_a_warning_and_no_video():
    meta = _own_meta()
    meta["files"] = [
        f for f in meta["files"] if f["name"].rsplit(".", 1)[-1] not in ("mp4", "mp3")
    ]
    with mock_session({OWN_META: FakeResponse(text=json.dumps(meta))}):
        result = await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
    assert result.video_url is None
    assert result.video_warnings


async def test_mp3_is_used_when_there_is_no_mp4():
    meta = _own_meta()
    meta["files"] = [f for f in meta["files"] if not f["name"].endswith(".mp4")]
    with mock_session({OWN_META: FakeResponse(text=json.dumps(meta))}):
        result = await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
    assert result.video_url.endswith("BOS2021_05_11.mp3")
    assert result.video_format == "mp3"


async def test_date_falls_back_to_the_title_and_stays_blank_when_absent():
    meta = _own_meta()
    del meta["metadata"]["date"]
    with mock_session({OWN_META: FakeResponse(text=json.dumps(meta))}):
        result = await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
    assert result.date == "2021-05-11"  # from the title "... 2021/05/11"
    meta["metadata"]["title"] = "Select board meeting"
    for f in meta["files"]:
        f["name"] = f["name"].replace("2021_05_11", "meeting")
    with mock_session({OWN_META: FakeResponse(text=json.dumps(meta))}):
        result = await ArchiveOrgAssetFinder().resolve(OWN_PAGE)
    assert result.date is None
    assert any("no meeting date" in w for w in result.transcript_warnings)


def test_length_reads_seconds_and_clock_times():
    assert parse_length("4271.3") == 4271.3
    assert parse_length("01:24:18") == 5058.0
    assert parse_length("24:18") == 1458.0
    assert parse_length(None) is None
    assert parse_length("") is None
    assert parse_length("abc") is None
    assert parse_length("0") is None


def test_the_host_is_a_shared_host_with_no_tenant_key():
    assert is_multi_gov_host("archive.org")
    assert tenant_key(OWN_PAGE) is None
    assert tenant_key(f"https://www.archive.org/details/{OWN_ID}") is None
