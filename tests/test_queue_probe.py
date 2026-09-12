"""Tests for app/platforms/queue_probe.py (WO-144).

Synthetic fixtures below (HLS master/variant playlists, TelVue's
Player.setupData JSON) reuse *shapes* already confirmed live in WO-143's
real 25-entry probe pilot (BACKLOG_DONE.md) -- an HLS master playlist
with zero #EXTINF entries pointing at a variant that carries the real
segment list, and a TelVue page embedding
`Player.setupData['playlist'] = [...]` with a real `duration` field --
per CLAUDE.md's synthetic-test convention: the payload shape is real and
confirmed, only the exact numbers/urls here are made up for the test.
Every dataclass/verdict-boundary test below is pure logic, no fixture
needed.

The opt-in live smoke test at the bottom (RTR_LIVE_TESTS=1) re-probes one
real URL per platform from WO-143's own 25-entry table -- run manually,
never in CI, same convention scripts/transcribe_backlog_locally.py's own
live tests already use.
"""

import os
from contextlib import contextmanager
from unittest import mock

import aiohttp
import pytest
import yt_dlp

from app.platforms import media_probe, queue_probe
from app.platforms.queue_probe import (
    _first_variant_url,
    _sum_extinf,
    probe_queue_entry,
)
from conftest import load_fixture
from tests.aiohttp_mock import FakeResponse, mock_session

# --- pure logic: verdict boundaries -----------------------------------


def test_finish_below_min_plausible_is_reject_short():
    result = queue_probe._finish(
        "https://example.com/v", "swagit", "hls-master+variant", 35.7, None, None, 0.0
    )
    assert result.verdict == "reject-short"
    assert "35.7" in result.reason
    assert result.over_nine_minutes is False


def test_finish_over_flag_long_threshold_still_counts_as_accept_shaped():
    # Anaheim's real 8.45h Granicus meeting (WO-143) is the confirmed
    # counterexample to a hard multi-hour ceiling -- flag, don't reject.
    result = queue_probe._finish(
        "https://example.com/v",
        "granicus",
        "hls-master+variant",
        30411.5,
        None,
        None,
        0.0,
    )
    assert result.verdict == "flag-long"
    assert result.over_nine_minutes is True


def test_finish_ordinary_duration_is_accept_and_over_nine_minutes_true():
    result = queue_probe._finish(
        "https://example.com/v",
        "vimeo",
        "vimeo-oembed",
        2228.0,
        "2026-08-17",
        None,
        0.0,
    )
    assert result.verdict == "accept"
    assert result.reason is None
    assert result.over_nine_minutes is True


def test_finish_under_nine_minutes_but_plausible_is_accept_not_over_nine():
    result = queue_probe._finish(
        "https://example.com/v", "vimeo", "vimeo-oembed", 300.0, None, None, 0.0
    )
    assert result.verdict == "accept"
    assert result.over_nine_minutes is False


def test_dead_never_sets_over_nine_minutes():
    result = queue_probe._dead(
        "https://example.com/v", "youtube", "yt-dlp-metadata", 0.0, "gone"
    )
    assert result.verdict == "reject-dead"
    assert result.duration_seconds is None
    assert result.over_nine_minutes is False


# --- HLS playlist parsing (Granicus/Swagit/Cablecast shape) -----------
#
# Synthetic: real shape confirmed live WO-143 (BACKLOG_DONE.md) -- master
# playlist carries zero #EXTINF entries, the variant it names carries the
# real segment list. Numbers/urls here are made up.

_SYNTHETIC_MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
chunklist.m3u8
"""

_SYNTHETIC_VARIANT_PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION=10
#EXTINF:10.0,
seg0.ts
#EXTINF:10.0,
seg1.ts
#EXTINF:10.0,
seg2.ts
#EXTINF:10.0,
seg3.ts
#EXTINF:10.0,
seg4.ts
#EXTINF:10.0,
seg5.ts
#EXTINF:5.5,
seg6.ts
"""


def test_first_variant_url_resolves_relative_to_master():
    variant = _first_variant_url(
        _SYNTHETIC_MASTER_PLAYLIST, "https://example.granicus.com/path/master.m3u8"
    )
    assert variant == "https://example.granicus.com/path/chunklist.m3u8"


def test_first_variant_url_none_when_no_stream_inf():
    assert _first_variant_url("#EXTM3U\n", "https://example.com/master.m3u8") is None


def test_sum_extinf_adds_real_segment_durations():
    assert _sum_extinf(_SYNTHETIC_VARIANT_PLAYLIST) == pytest.approx(65.5)


def test_sum_extinf_zero_on_master_playlist_alone():
    # The real WO-143 finding this guards: the master alone always
    # reports zero segments.
    assert _sum_extinf(_SYNTHETIC_MASTER_PLAYLIST) == 0.0


async def test_probe_hls_accepts_a_real_shaped_master_plus_variant():
    master_url = "https://example.granicus.com/path/master.m3u8"
    variant_url = "https://example.granicus.com/path/chunklist.m3u8"
    with mock_session(
        {
            master_url: FakeResponse(status=200, text=_SYNTHETIC_MASTER_PLAYLIST),
            variant_url: FakeResponse(status=200, text=_SYNTHETIC_VARIANT_PLAYLIST),
        }
    ):
        result = await probe_queue_entry(
            "https://example.granicus.com/MediaPlayer.php?clip_id=1",
            video_url=master_url,
            source_page_url="https://example.granicus.com/MediaPlayer.php?clip_id=1",
            platform="granicus",
        )
    assert result.verdict == "accept"
    assert result.duration_seconds == pytest.approx(65.5)
    assert result.probe_method == "hls-master+variant"


async def test_probe_hls_master_404_is_reject_dead():
    master_url = "https://example.granicus.com/path/master.m3u8"
    with mock_session({master_url: FakeResponse(status=404, text="")}):
        result = await probe_queue_entry(
            "https://example.granicus.com/MediaPlayer.php?clip_id=1",
            video_url=master_url,
            platform="granicus",
        )
    assert result.verdict == "reject-dead"
    assert "404" in result.reason


async def test_probe_hls_variant_with_zero_segments_is_reject_dead():
    master_url = "https://example.granicus.com/path/master.m3u8"
    variant_url = "https://example.granicus.com/path/chunklist.m3u8"
    with mock_session(
        {
            master_url: FakeResponse(status=200, text=_SYNTHETIC_MASTER_PLAYLIST),
            variant_url: FakeResponse(status=200, text="#EXTM3U\n"),
        }
    ):
        result = await probe_queue_entry(
            "https://example.granicus.com/MediaPlayer.php?clip_id=1",
            video_url=master_url,
            platform="granicus",
        )
    assert result.verdict == "reject-dead"
    assert "zero segments" in result.reason


# --- TelVue Player.setupData JSON ---------------------------------------
#
# Synthetic: real shape confirmed live WO-143 -- a `duration` field
# directly in the playlist entry, and a `livestream.telvue.com` host
# meaning a live placeholder rather than an archived recording (both real
# TelVue samples probed in WO-143 were placeholders). Numbers/tokens made
# up.

_SYNTHETIC_TELVUE_PAGE = """<html><body><script>
Player.setupData['playlist'] = [{{"title": "Council Meeting - {date}",
"file": "{file_url}", "duration": {duration},
"tracks": []}}];
</script></body></html>"""


async def test_probe_telvue_accepts_a_real_shaped_archived_recording():
    page_url = "https://videoplayer.telvue.com/player/TOKEN/stream/100"
    html = _SYNTHETIC_TELVUE_PAGE.format(
        date="Sept 1, 2026",
        file_url="https://videoplayer.telvue.com/stream/master.m3u8",
        duration=3600,
    )
    with mock_session({page_url: FakeResponse(status=200, text=html)}):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="telvue"
        )
    assert result.verdict == "accept"
    assert result.duration_seconds == 3600.0


async def test_probe_telvue_zero_duration_is_reject_dead():
    page_url = "https://videoplayer.telvue.com/player/TOKEN/stream/101"
    html = _SYNTHETIC_TELVUE_PAGE.format(
        date="", file_url="https://livestream.telvue.com/stream/master.m3u8", duration=0
    )
    with mock_session({page_url: FakeResponse(status=200, text=html)}):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="telvue"
        )
    assert result.verdict == "reject-dead"
    assert "live placeholder" in result.reason


async def test_probe_telvue_livestream_host_is_reject_dead_even_with_nonzero_duration():
    # Belt-and-suspenders case: a nonzero duration on a livestream.telvue.com
    # host should still be treated as a placeholder, not trusted at face value.
    page_url = "https://videoplayer.telvue.com/player/TOKEN/stream/102"
    html = _SYNTHETIC_TELVUE_PAGE.format(
        date="",
        file_url="https://livestream.telvue.com/stream/master.m3u8",
        duration=42,
    )
    with mock_session({page_url: FakeResponse(status=200, text=html)}):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="telvue"
        )
    assert result.verdict == "reject-dead"
    assert "livestream.telvue.com" in result.reason


async def test_probe_telvue_no_playlist_found_is_reject_dead():
    page_url = "https://videoplayer.telvue.com/player/TOKEN/stream/103"
    with mock_session(
        {page_url: FakeResponse(status=200, text="<html>nothing here</html>")}
    ):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="telvue"
        )
    assert result.verdict == "reject-dead"
    assert "no Player.setupData" in result.reason


# --- Viebit ----------------------------------------------------------------
# WO-306 (2026-09-12): every Viebit candidate died here as "no probe recipe"
# before this -- resolve() rebuilds video_url as the safe-to-iframe
# /embed/vod?v={id} page (see viebit.py's own docstring), never the raw HLS
# master.m3u8, so this dispatch never saw anything HLS-shaped. The synthetic
# pageConfig shape below is real and confirmed (a live Delano, MN fetch,
# 2026-09-12) -- only the id/title/hash values here are made up.

_SYNTHETIC_VIEBIT_PAGE_CONFIG = (
    '<script>var pageConfig = {{"video":{{"id":"abc123","title":"City '
    'Council Meeting","dateCreated":1787102320,"src":[{{"storage":'
    '"https://vbfast-vod.viebit.com/example/abc123/","url":'
    '"master.m3u8","type":"application/x-mpegurl"}}],"textTracks":[]}},'
    '"hasAccess":{has_access}}};</script>'
)


async def test_probe_viebit_accepts_with_unknown_duration():
    page_url = "https://example.viebit.com/watch?hash=abc123"
    html = _SYNTHETIC_VIEBIT_PAGE_CONFIG.format(has_access="true")
    with mock_session({page_url: FakeResponse(status=200, text=html)}):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="viebit"
        )
    assert result.verdict == "accept"
    assert result.duration_seconds is None
    assert "CDN-gated" in result.reason


async def test_probe_viebit_no_access_is_reject_dead():
    page_url = "https://example.viebit.com/watch?hash=gated"
    html = _SYNTHETIC_VIEBIT_PAGE_CONFIG.format(has_access="false")
    with mock_session({page_url: FakeResponse(status=200, text=html)}):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="viebit"
        )
    assert result.verdict == "reject-dead"
    assert "hasAccess=false" in result.reason


async def test_probe_viebit_no_page_config_is_reject_dead():
    page_url = "https://example.viebit.com/watch?hash=missing"
    with mock_session(
        {page_url: FakeResponse(status=200, text="<html>nothing here</html>")}
    ):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="viebit"
        )
    assert result.verdict == "reject-dead"
    assert "no Viebit pageConfig" in result.reason


async def test_probe_viebit_no_video_src_is_reject_dead():
    page_url = "https://example.viebit.com/watch?hash=novideo"
    html = (
        '<script>var pageConfig = {"video":{"id":"abc123","src":[]},'
        '"hasAccess":true};</script>'
    )
    with mock_session({page_url: FakeResponse(status=200, text=html)}):
        result = await probe_queue_entry(
            page_url, video_url=page_url, platform="viebit"
        )
    assert result.verdict == "reject-dead"
    assert "no video.src" in result.reason


# --- Vimeo oEmbed ---------------------------------------------------------


def _vimeo_oembed_route(video_id: str) -> str:
    from urllib.parse import quote

    target = f"https://vimeo.com/{video_id}"
    return "https://vimeo.com/api/oembed.json?url=" + quote(target, safe="")


async def test_probe_vimeo_accepts_real_shaped_oembed_response():
    video_id = "123456789"
    route = _vimeo_oembed_route(video_id)
    body = (
        '{"duration": 2228, "upload_date": "2026-08-17 10:01:23", '
        '"title": "Council Meeting"}'
    )
    with mock_session({route: FakeResponse(status=200, text=body)}):
        result = await probe_queue_entry(
            f"https://vimeo.com/{video_id}",
            video_url=f"https://vimeo.com/{video_id}",
            platform="vimeo",
        )
    assert result.verdict == "accept"
    assert result.duration_seconds == 2228.0
    assert result.date == "2026-08-17"
    # No size signal exists on Vimeo at all -- see queue_probe.py's own
    # docstring -- so this must stay blank, not guessed.
    assert result.size_bytes is None


async def test_probe_vimeo_oembed_404_is_reject_dead():
    video_id = "000000000"
    route = _vimeo_oembed_route(video_id)
    with mock_session({route: FakeResponse(status=404, text="")}):
        result = await probe_queue_entry(
            f"https://vimeo.com/{video_id}",
            video_url=f"https://vimeo.com/{video_id}",
            platform="vimeo",
        )
    assert result.verdict == "reject-dead"


# --- YouTube (yt-dlp metadata-only, mocked -- never a real network call) --


async def test_probe_youtube_accepts_real_shaped_metadata(monkeypatch):
    def _fake_probe(video_id):
        assert video_id == "KF4N78Gz64g"
        return {
            "duration": 4163,
            "upload_date": "20260116",
            "release_date": None,
            "filesize": 113897164,
            "filesize_approx": None,
        }

    monkeypatch.setattr(queue_probe, "_yt_dlp_probe", _fake_probe)

    result = await probe_queue_entry(
        "https://www.youtube.com/watch?v=KF4N78Gz64g",
        video_url="https://www.youtube.com/embed/KF4N78Gz64g",
        platform="youtube",
    )
    assert result.verdict == "accept"
    assert result.duration_seconds == 4163.0
    assert result.date == "2026-01-16"
    assert result.size_bytes == 113897164
    # yt-dlp's own metadata-only extract_info() call never fetches a
    # caption track -- this module must never call _pick_caption_track().
    assert result.probe_method == "yt-dlp-metadata"


async def test_probe_youtube_live_event_not_started_is_reject_dead(monkeypatch):
    def _fake_probe(video_id):
        raise yt_dlp.utils.DownloadError(
            f"ERROR: [youtube] {video_id}: This live event will begin in 4 days."
        )

    monkeypatch.setattr(queue_probe, "_yt_dlp_probe", _fake_probe)

    result = await probe_queue_entry(
        "https://www.youtube.com/watch?v=ESfzST-yOSM",
        video_url="https://www.youtube.com/embed/ESfzST-yOSM",
        platform="youtube",
    )
    assert result.verdict == "reject-dead"
    assert "will begin in 4 days" in result.reason


async def test_probe_youtube_removed_video_is_reject_dead(monkeypatch):
    def _fake_probe(video_id):
        raise yt_dlp.utils.DownloadError(
            "ERROR: Private video. If the owner of this video has granted you access, ..."
        )

    monkeypatch.setattr(queue_probe, "_yt_dlp_probe", _fake_probe)

    result = await probe_queue_entry(
        "https://www.youtube.com/watch?v=deadbeef123",
        video_url="https://www.youtube.com/embed/deadbeef123",
        platform="youtube",
    )
    assert result.verdict == "reject-dead"


async def test_probe_youtube_confirmed_gone_video_is_reject_dead(monkeypatch):
    # WO-167, 2026-09-10. Pacific City, MO's real queued video
    # (XeWevpU5Kpc) -- confirmed live 2026-09-10 (see tests/test_youtube.py
    # for the same sample against resolve_video_id()). This is the probe
    # side of the same real gap: this already worked (reject-dead) before
    # WO-167, since the probe never relied on resolve_video_id()'s own
    # classification -- pinned here as a regression test, and to confirm
    # the new `reason` prefix (below) doesn't change the verdict.
    def _fake_probe(video_id):
        raise yt_dlp.utils.DownloadError(
            f"ERROR: [youtube] {video_id}: This video is unavailable"
        )

    monkeypatch.setattr(queue_probe, "_yt_dlp_probe", _fake_probe)

    result = await probe_queue_entry(
        "https://www.youtube.com/watch?v=XeWevpU5Kpc",
        video_url="https://www.youtube.com/embed/XeWevpU5Kpc",
        platform="youtube",
    )
    assert result.verdict == "reject-dead"
    assert "gone: " in result.reason
    assert "This video is unavailable" in result.reason


async def test_probe_youtube_reason_prefix_distinguishes_not_yet_started_from_gone(
    monkeypatch,
):
    # WO-167, 2026-09-10: the probe's verdict stays reject-dead either
    # way (unchanged, deliberately -- see this module's own docstring),
    # but the `reason` column now carries youtube.py's shared
    # classify_unavailability() label so a human (or a later script)
    # reading the tier-3 sidecar CSV can tell "will resolve once it airs"
    # apart from "never will" without parsing free-text yt-dlp wording.
    def _fake_probe_not_yet_started(video_id):
        raise yt_dlp.utils.DownloadError(
            f"ERROR: [youtube] {video_id}: This live event will begin in 4 days."
        )

    monkeypatch.setattr(queue_probe, "_yt_dlp_probe", _fake_probe_not_yet_started)
    not_yet_started = await probe_queue_entry(
        "https://www.youtube.com/watch?v=ESfzST-yOSM",
        video_url="https://www.youtube.com/embed/ESfzST-yOSM",
        platform="youtube",
    )
    assert not_yet_started.verdict == "reject-dead"
    assert not_yet_started.reason.startswith("yt-dlp: not_yet_started: ")

    def _fake_probe_gone(video_id):
        raise yt_dlp.utils.DownloadError(
            f"ERROR: [youtube] {video_id}: This video has been removed by the uploader"
        )

    monkeypatch.setattr(queue_probe, "_yt_dlp_probe", _fake_probe_gone)
    gone = await probe_queue_entry(
        "https://www.youtube.com/watch?v=_RZBcYEbQr4",
        video_url="https://www.youtube.com/embed/_RZBcYEbQr4",
        platform="youtube",
    )
    assert gone.verdict == "reject-dead"
    assert gone.reason.startswith("yt-dlp: gone: ")


async def test_probe_youtube_unrecognized_message_has_no_reason_prefix(monkeypatch):
    # The generic-degrade safety valve carries through to the probe too:
    # a phrasing classify_unavailability() doesn't recognise (e.g. the
    # anti-bot block) gets no misleading label prepended.
    def _fake_probe(video_id):
        raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(queue_probe, "_yt_dlp_probe", _fake_probe)

    result = await probe_queue_entry(
        "https://www.youtube.com/watch?v=abcdefghijk",
        video_url="https://www.youtube.com/embed/abcdefghijk",
        platform="youtube",
    )
    assert result.verdict == "reject-dead"
    assert result.reason == "yt-dlp: Sign in to confirm you're not a bot"


# --- Direct file (CivicClerk mp4/mov): HEAD + ffprobe ----------------


@contextmanager
def _mock_head(routes: dict):
    """aiohttp_mock.mock_session only patches .get()/.post() -- this
    module is the first caller here that needs .head(), so a small local
    patch rather than widening the shared helper for one new caller."""

    def fake_head(self, url, **kwargs):
        key = str(url)
        if key not in routes:
            raise AssertionError(f"Unmocked HEAD in test: {key}")
        response = routes[key]
        if not response.url:
            response.url = key
        return response

    with mock.patch.object(aiohttp.ClientSession, "head", fake_head):
        yield


async def test_probe_direct_file_accepts_real_shaped_head_plus_ffprobe(monkeypatch):
    media_url = "https://example.portal.civicclerk.com/media/event-1.mp4"

    async def _fake_probe_duration(url, *, source_page_url):
        assert url == media_url
        return 8139.26

    monkeypatch.setattr(media_probe, "probe_duration", _fake_probe_duration)

    with _mock_head(
        {
            media_url: FakeResponse(
                status=200,
                headers={
                    "Content-Length": "4051753490",
                    "Last-Modified": "Wed, 09 Sep 2026 12:00:00 GMT",
                },
            )
        }
    ):
        result = await probe_queue_entry(
            "https://example.portal.civicclerk.com/event/1/media",
            video_url=media_url,
            platform="civicclerk",
        )

    assert result.verdict == "accept"
    assert result.duration_seconds == 8139.26
    assert result.size_bytes == 4051753490
    assert result.date == "2026-09-09"
    assert result.probe_method == "head+ffprobe"


async def test_probe_direct_file_head_and_ranged_get_both_404_is_reject_dead():
    # HEAD fails, and the WO-166 ranged-GET fallback below fails too (a
    # genuinely dead file, not the CivicPlus DocumentCenter shape the next
    # test covers) -- still reject-dead.
    media_url = "https://example.portal.civicclerk.com/media/gone.mp4"
    with (
        _mock_head({media_url: FakeResponse(status=404)}),
        mock_session({media_url: FakeResponse(status=404)}),
    ):
        result = await probe_queue_entry(
            "https://example.portal.civicclerk.com/event/2/media",
            video_url=media_url,
            platform="civicclerk",
        )
    assert result.verdict == "reject-dead"
    assert "404" in result.reason


async def test_probe_direct_file_head_404_falls_back_to_ranged_get(monkeypatch):
    # Real shape confirmed live 2026-09-10 (WO-166): a CivicPlus
    # DocumentCenter link (e.g. Hudson, CO's own
    # `/DocumentCenter/View/6698/PC-Recording-09092026`) answers a plain
    # HEAD with a genuine 404 while the identical URL answers a GET (with
    # or without a Range header -- this server ignores Range and always
    # serves the whole response) with a real 200 and the real file's
    # headers. `_probe_direct_file()` must fall back to a ranged GET
    # rather than declaring the file dead on the HEAD 404 alone.
    media_url = "https://hudsonco.gov/DocumentCenter/View/6698/PC-Recording-09092026"

    async def _fake_probe_duration(url, *, source_page_url):
        assert url == media_url
        return 1234.5

    monkeypatch.setattr(media_probe, "probe_duration", _fake_probe_duration)

    with (
        _mock_head({media_url: FakeResponse(status=404)}),
        mock_session(
            {
                media_url: FakeResponse(
                    status=200,
                    headers={
                        "Content-Length": "106103482",
                        "Content-Disposition": "inline;filename=PC%20Recording.mp4",
                    },
                )
            }
        ),
    ):
        result = await probe_queue_entry(
            "https://hudsonco.gov/DocumentCenter/View/6698/PC-Recording-09092026",
            video_url=media_url,
            platform="unknown",
            video_format="mp4",
        )

    assert result.verdict == "accept"
    assert result.probe_method == "ranged-get+ffprobe"
    assert result.size_bytes == 106103482
    assert result.duration_seconds == 1234.5


# --- WO-166 (2026-09-10): a direct file with no URL extension at all,
# routed here via the resolved ResolvedMeeting's own `video_format`
# (generic_fallback.py's `_classify_direct_media()` sets this from
# Content-Type/Content-Disposition, since the real government URLs this
# was built from -- e.g. Cheney, WA's own DocumentCenter link -- never
# carry an extension in the URL itself). -----------------------------


async def test_probe_queue_entry_dispatches_direct_file_via_video_format_no_url_extension(
    monkeypatch,
):
    # Same shape as the real Cheney, WA URL this WO was built from --
    # `video_url` here is deliberately extension-less.
    media_url = "https://www.cityofcheney.org/DocumentCenter/View/4867/9-8-26-Recording"
    fake_result = _FakeResolvedMeeting(video_url=media_url, source_url=media_url)
    fake_result.video_format = "mp4"
    monkeypatch.setattr(queue_probe, "detect_platform", lambda url: "unknown")
    monkeypatch.setattr(
        queue_probe, "get_finder", lambda platform: _FakeFinder(fake_result)
    )

    async def _fake_probe_duration(url, *, source_page_url):
        assert url == media_url
        return 2145.0

    monkeypatch.setattr(media_probe, "probe_duration", _fake_probe_duration)

    with _mock_head(
        {media_url: FakeResponse(status=200, headers={"Content-Length": "500000000"})}
    ):
        result = await probe_queue_entry(media_url)

    assert result.verdict == "accept"
    assert result.probe_method == "head+ffprobe"
    assert result.duration_seconds == 2145.0


async def test_probe_queue_entry_dispatches_direct_file_for_bare_mp3_via_video_format(
    monkeypatch,
):
    # An audio-only direct file (no URL extension either) -- still a real,
    # queueable candidate; probed the same way as a video file.
    media_url = "https://example-county.gov/DocumentCenter/View/900/Board-Meeting-Audio"
    fake_result = _FakeResolvedMeeting(video_url=media_url, source_url=media_url)
    fake_result.video_format = "mp3"
    monkeypatch.setattr(queue_probe, "detect_platform", lambda url: "unknown")
    monkeypatch.setattr(
        queue_probe, "get_finder", lambda platform: _FakeFinder(fake_result)
    )

    async def _fake_probe_duration(url, *, source_page_url):
        assert url == media_url
        return 612.0

    monkeypatch.setattr(media_probe, "probe_duration", _fake_probe_duration)

    with _mock_head(
        {media_url: FakeResponse(status=200, headers={"Content-Length": "9000000"})}
    ):
        result = await probe_queue_entry(media_url)

    assert result.verdict == "accept"
    assert result.probe_method == "head+ffprobe"
    assert result.duration_seconds == 612.0


async def test_probe_queue_entry_dispatches_direct_file_for_utah_pmn_m4a(monkeypatch):
    # WO-205: Utah PMN's uploaded recordings are bare .m4a files on
    # utah.gov (real shape: https://www.utah.gov/pmn/files/1375421.m4a);
    # 277 real queue lines were rejected "no probe recipe" before .m4a
    # joined _DIRECT_FILE_EXTENSIONS.
    media_url = "https://www.utah.gov/pmn/files/1375421.m4a"

    async def _fake_probe_duration(url, *, source_page_url):
        assert url == media_url
        return 1830.0

    monkeypatch.setattr(media_probe, "probe_duration", _fake_probe_duration)

    with _mock_head(
        {media_url: FakeResponse(status=200, headers={"Content-Length": "14000000"})}
    ):
        result = await probe_queue_entry(
            "https://www.utah.gov/pmn/sitemap/notice/1050205.html",
            video_url=media_url,
            source_page_url="https://www.utah.gov/pmn/sitemap/notice/1050205.html",
            platform="utah_pmn",
        )

    assert result.verdict == "accept"
    assert result.probe_method == "head+ffprobe"
    assert result.duration_seconds == 1830.0


# --- Resolve-first path (video_url not given) ---------------------------


class _FakeResolvedMeeting:
    def __init__(self, video_url, source_url):
        self.video_url = video_url
        self.source_url = source_url


class _FakeFinder:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    async def resolve(self, url):
        if self._exc:
            raise self._exc
        return self._result


async def test_probe_queue_entry_resolves_first_when_no_video_url_given(monkeypatch):
    fake_result = _FakeResolvedMeeting(
        video_url="https://vimeo.com/999999999", source_url="https://city.gov/agenda/1"
    )
    monkeypatch.setattr(queue_probe, "detect_platform", lambda url: "vimeo")
    monkeypatch.setattr(
        queue_probe, "get_finder", lambda platform: _FakeFinder(fake_result)
    )

    async def _fake_probe_vimeo(url, video_url, start):
        assert video_url == "https://vimeo.com/999999999"
        return queue_probe._finish(
            url, "vimeo", "vimeo-oembed", 1200.0, None, None, start
        )

    monkeypatch.setattr(queue_probe, "_probe_vimeo", _fake_probe_vimeo)

    result = await probe_queue_entry("https://city.gov/agenda/1")
    assert result.verdict == "accept"
    assert result.duration_seconds == 1200.0


async def test_probe_queue_entry_resolve_with_no_video_url_is_reject_dead(monkeypatch):
    fake_result = _FakeResolvedMeeting(
        video_url=None, source_url="https://city.gov/agenda/2"
    )
    monkeypatch.setattr(queue_probe, "detect_platform", lambda url: "cablecast")
    monkeypatch.setattr(
        queue_probe, "get_finder", lambda platform: _FakeFinder(fake_result)
    )

    result = await probe_queue_entry("https://city.gov/agenda/2")
    assert result.verdict == "reject-dead"
    assert "no video_url" in result.reason


async def test_probe_queue_entry_resolve_exception_is_reject_dead(monkeypatch):
    monkeypatch.setattr(queue_probe, "detect_platform", lambda url: "cablecast")
    monkeypatch.setattr(
        queue_probe,
        "get_finder",
        lambda platform: _FakeFinder(exc=RuntimeError("connection reset")),
    )

    result = await probe_queue_entry("https://city.gov/agenda/3")
    assert result.verdict == "reject-dead"
    assert "resolve raised" in result.reason


# --- Opt-in live smoke test (never in CI) --------------------------------


@pytest.mark.skipif(
    os.environ.get("RTR_LIVE_TESTS") != "1",
    reason="live smoke test -- set RTR_LIVE_TESTS=1 to run against real platforms",
)
async def test_probe_queue_entry_live_five_real_urls_one_per_platform():
    """One real URL per platform, all five taken directly from WO-143's
    own 25-entry table (BACKLOG_DONE.md) -- run manually
    (RTR_LIVE_TESTS=1 pytest tests/test_queue_probe.py -k live), never in
    CI. If YouTube's block signature (HTTP 429 on captions, or "Sign in
    to confirm you're not a bot") appears here, stop -- see
    docs/investigations/youtube_429_block.md."""
    from app.platforms import register_all_finders

    register_all_finders()

    cases = [
        # (url, platform, expected verdict)
        ("https://www.youtube.com/watch?v=KF4N78Gz64g", "youtube", "accept"),
        ("https://vimeo.com/1219072948", "vimeo", "accept"),
        (
            "https://albanyca.granicus.com/MediaPlayer.php?view_id=2&clip_id=2731",
            "granicus",
            "accept",
        ),
        (
            "https://anacorteswa.portal.civicclerk.com/event/1452/media",
            "civicclerk",
            "accept",
        ),
        (
            "https://videoplayer.telvue.com/player/KPxII4Dm-djtTqV7JZXpXeOM2kiyqvRV/stream/983",
            "telvue",
            "reject-dead",
        ),
    ]
    for url, platform, expected_verdict in cases:
        result = await probe_queue_entry(url, platform=platform)
        assert result.verdict == expected_verdict, (
            f"{platform} ({url}): expected {expected_verdict}, got "
            f"{result.verdict} ({result.reason})"
        )


async def test_probe_queue_entry_dispatches_youtube_for_a_civicweb_page(monkeypatch):
    # WO-205: a CivicWeb page resolves to a YouTube embed; the probe used to
    # fall through to "no probe recipe" because it dispatched on the page's
    # platform only (41 real queue lines).
    page = "https://desmoines.civicweb.net/Portal/MeetingInformation.aspx?Id=582"
    embed = "https://www.youtube.com/embed/ax-OzF0VRk4"
    fake_result = _FakeResolvedMeeting(video_url=embed, source_url=page)
    fake_result.video_format = "youtube"
    monkeypatch.setattr(queue_probe, "detect_platform", lambda url: "civicweb")
    monkeypatch.setattr(
        queue_probe, "get_finder", lambda platform: _FakeFinder(fake_result)
    )
    seen = {}

    async def _fake_youtube(url, video_url, start):
        seen["video_url"] = video_url
        return queue_probe._finish(
            url, "civicweb", "yt-dlp-metadata", 1500.0, "2026-08-10", None, start
        )

    monkeypatch.setattr(queue_probe, "_probe_youtube", _fake_youtube)
    result = await probe_queue_entry(page)
    assert seen["video_url"] == embed
    assert result.verdict == "accept" and result.duration_seconds == 1500.0


# --- WO-285: SuiteOne (CivicClerk delegation) ---------------------------


async def test_probe_queue_entry_dispatches_suiteone_for_a_civicclerk_delegation():
    # Real shape, WO-213/BACKLOG.md: CivicClerk resolves Vineyard, UT's
    # event/1453 to a SuiteOne player page
    # (`vineyardut.suiteonemedia.com/web/Player.aspx?id=1612&...`) --
    # `queue_probe.py` had no SuiteOne branch at all, so all 16 of
    # Vineyard's real CivicClerk lines were "no probe recipe for this
    # media shape" even though the video is real. `platform="civicclerk"`
    # here matches the real sidecar row's own platform column exactly --
    # dispatch must go by the SuiteOne HOST in `video_url`, not
    # `resolved_platform`, the same "what the video IS" reasoning WO-205
    # used for CivicWeb->YouTube above.
    meeting_url = "https://vineyardut.portal.civicclerk.com/event/1453/media"
    player_url = (
        "http://vineyardut.suiteonemedia.com/web/Player.aspx"
        "?id=1612&key=-1&mod=-1&mk=-1&nov=0"
    )
    player_html = load_fixture("suiteone", "vineyardut_player.html")
    media_url = "https://s3.amazonaws.com/suiteone.vineyardut.videofiles/cb54ea20.mp4"
    home_url = "http://vineyardut.suiteonemedia.com/"
    captions_url = "http://vineyardut.suiteonemedia.com/Event/GetCaptions/?eventId=1612"

    routes = {
        player_url: FakeResponse(status=200, text=player_html, url=player_url),
        home_url: FakeResponse(status=404, text=""),
        captions_url: FakeResponse(status=404, text=""),
    }

    async def _fake_probe_duration(url, *, source_page_url):
        assert url == media_url
        return 3912.0

    with mock.patch.object(media_probe, "probe_duration", _fake_probe_duration):
        with mock_session(routes):
            with _mock_head(
                {
                    media_url: FakeResponse(
                        status=200, headers={"Content-Length": "600000000"}
                    )
                }
            ):
                result = await probe_queue_entry(
                    meeting_url, video_url=player_url, platform="civicclerk"
                )

    assert result.verdict == "accept"
    assert result.platform == "suiteone"
    assert result.duration_seconds == 3912.0


async def test_probe_suiteone_resolve_error_is_reject_dead_not_a_crash():
    # The Constraint this WO's own BACKLOG.md entry names: suiteone.py's
    # resolve() can still raise a raw ValueError for a URL shape it
    # can't parse at all (the separate, narrower bare-tenant-management-
    # root gap WO-149 already filed) -- must not abort the whole probe
    # run.
    result = await queue_probe._probe_suiteone(
        "https://example.gov/meeting",
        "https://lunaconm.suiteonemedia.com/",
        None,
        0.0,
    )
    assert result.verdict == "reject-dead"
    assert "SuiteOne resolve raised" in result.reason


async def test_probe_suiteone_no_video_yet_is_reject_dead():
    # Real shape: a not-yet-recorded SuiteOne event serves `var src =
    # '';` (St Marys, GA event 1000 -- see tests/test_suiteone.py) --
    # this must be a clean reject, not an exception.
    live_html = load_fixture("suiteone", "floydcoin_live.html")
    live_url = "https://floydcoin.suiteonemedia.com/web/live/"

    with mock_session(
        {live_url: FakeResponse(status=200, text=live_html, url=live_url)}
    ):
        result = await queue_probe._probe_suiteone(
            "https://example.gov/meeting", live_url, None, 0.0
        )

    assert result.verdict == "reject-dead"
    assert "no playable video" in result.reason


# --- WO-224: the shared finish step ----------------------------------------
#
# The bug: every wo1XX_finish_tier3*.py script's own "already probed,
# skipping fetch" branch checked only that the sidecar had A row for a
# URL, never what its verdict WAS -- so a real `accept` sitting there from
# an earlier run got silently dropped, never queued, never pinned.
# finish_candidate() is the fix: it reads the cached verdict via
# cached_verdict() and always acts on it. Every test below uses tmp_path
# files so nothing here ever touches the real queue/sidecar/pins/deferred
# files.


def _write_probe_row(sidecar_path, url, *, verdict, duration_seconds=None, reason=None):
    """Writes one real sidecar row via append_probe_row() (not a hand-typed
    CSV line) so these tests exercise the same read path a real probe run
    would populate."""
    result = queue_probe.ProbeResult(
        url=url,
        platform="youtube",
        probe_method="yt-dlp-metadata",
        duration_seconds=duration_seconds,
        date="2026-09-01",
        size_bytes=None,
        verdict=verdict,
        reason=reason,
        probe_seconds=0.5,
        over_nine_minutes=bool(duration_seconds and duration_seconds > 540),
    )
    queue_probe.append_probe_row(sidecar_path, result)
    return result


def _paths(tmp_path):
    return {
        "sidecar_path": tmp_path / "sidecar.csv",
        "queue_path": tmp_path / "queue.txt",
        "deferred_path": tmp_path / "deferred.txt",
        "pins_path": tmp_path / "pins.csv",
    }


async def test_finish_candidate_cached_accept_queues_and_pins(tmp_path):
    paths = _paths(tmp_path)
    url = "https://www.youtube.com/watch?v=abc123"
    _write_probe_row(
        paths["sidecar_path"], url, verdict="accept", duration_seconds=1200.0
    )

    outcome = await queue_probe.finish_candidate(
        url,
        gov_id="us:place:0000001",
        pin={
            "host": "www.youtube.com",
            "match": "youtube:abc123",
            "gov_id": "us:place:0000001",
        },
        **paths,
    )

    assert outcome.used_cache is True
    assert outcome.action == "queued"
    assert outcome.queued is True
    assert outcome.pinned is True
    assert url in paths["queue_path"].read_text()
    pins_text = paths["pins_path"].read_text()
    assert "www.youtube.com" in pins_text and "youtube:abc123" in pins_text


async def test_finish_candidate_cached_reject_dead_never_queues(tmp_path):
    paths = _paths(tmp_path)
    url = "https://www.youtube.com/watch?v=deadvideo"
    _write_probe_row(
        paths["sidecar_path"], url, verdict="reject-dead", reason="video removed"
    )

    outcome = await queue_probe.finish_candidate(url, **paths)

    assert outcome.used_cache is True
    assert outcome.action == "rejected"
    assert outcome.queued is False
    assert outcome.probe.reason == "video removed"
    assert not paths["queue_path"].exists()


async def test_finish_candidate_cached_accept_already_queued_is_a_noop(tmp_path):
    paths = _paths(tmp_path)
    url = "https://www.youtube.com/watch?v=alreadyqueued"
    _write_probe_row(
        paths["sidecar_path"], url, verdict="accept", duration_seconds=900.0
    )
    # Pre-seed the queue file AND the pin, as if an earlier run already
    # finished this candidate.
    paths["queue_path"].write_text(url + "\n")
    paths["pins_path"].write_text(
        "tenant_host,match,gov_id,strength,source,evidence\n"
        "www.youtube.com,youtube:alreadyqueued,us:place:0000002,fallback,test,pre-existing\n"
    )

    outcome = await queue_probe.finish_candidate(
        url,
        pin={
            "host": "www.youtube.com",
            "match": "youtube:alreadyqueued",
            "gov_id": "us:place:0000002",
        },
        **paths,
    )

    assert outcome.action == "already-queued"
    assert outcome.queued is False
    assert outcome.pinned is False
    # No duplicate line/row was appended.
    assert paths["queue_path"].read_text().count(url) == 1
    assert paths["pins_path"].read_text().count("www.youtube.com") == 1


async def test_finish_candidate_cached_accept_url_in_deferred_file_is_skipped(tmp_path):
    paths = _paths(tmp_path)
    url = "https://www.youtube.com/watch?v=deliberatelyremoved"
    _write_probe_row(
        paths["sidecar_path"], url, verdict="accept", duration_seconds=600.0
    )
    # A deliberate WO-205-style removal: this URL was swapped out of the
    # queue on purpose and parked here.
    paths["deferred_path"].write_text(
        f"{url}\t\tus:place:0000003\tSome City, ST\t10:00\t\n"
    )

    outcome = await queue_probe.finish_candidate(url, **paths)

    assert outcome.action == "skipped-deferred"
    assert outcome.queued is False
    assert not paths["queue_path"].exists()


async def test_finish_candidate_flag_long_goes_to_deferred_not_queue(tmp_path):
    paths = _paths(tmp_path)
    url = "https://www.youtube.com/watch?v=verylongmeeting"
    # Over the 6-hour flag-long threshold -- also over the 90-minute
    # deferred threshold, so this must land in the deferred file, never
    # the queue.
    _write_probe_row(
        paths["sidecar_path"], url, verdict="flag-long", duration_seconds=8.45 * 3600
    )

    outcome = await queue_probe.finish_candidate(
        url, gov_id="us:place:0000004", jurisdiction="Anaheim, CA", **paths
    )

    assert outcome.action == "deferred"
    assert outcome.deferred is True
    assert outcome.queued is False
    assert not paths["queue_path"].exists()
    deferred_text = paths["deferred_path"].read_text()
    assert url in deferred_text
    assert "us:place:0000004" in deferred_text
    assert "8:27:00" in deferred_text  # hms(8.45 * 3600)


async def test_finish_candidate_accept_over_90_minutes_defers_even_without_flag_long(
    tmp_path,
):
    """A plain `accept` verdict (under the 6h flag-long ceiling) whose
    duration is still over the 90-minute deferred threshold must defer,
    not queue -- the deferred-file rule is about duration, not verdict."""
    paths = _paths(tmp_path)
    url = "https://www.youtube.com/watch?v=onehundredminutes"
    _write_probe_row(
        paths["sidecar_path"], url, verdict="accept", duration_seconds=100 * 60
    )

    outcome = await queue_probe.finish_candidate(url, **paths)

    assert outcome.action == "deferred"
    assert outcome.queued is False
    assert url in paths["deferred_path"].read_text()


async def test_finish_candidate_no_cache_probes_fresh_and_appends_sidecar(
    tmp_path, monkeypatch
):
    paths = _paths(tmp_path)
    url = "https://www.youtube.com/watch?v=freshprobe"

    async def _fake_probe(*args, **kwargs):
        return queue_probe._finish(
            url, "youtube", "yt-dlp-metadata", 700.0, "2026-09-11", None, 0.0
        )

    monkeypatch.setattr(queue_probe, "probe_queue_entry", _fake_probe)
    outcome = await queue_probe.finish_candidate(url, caller="test", **paths)

    assert outcome.used_cache is False
    assert outcome.action == "queued"
    assert paths["sidecar_path"].exists()
    assert url in paths["sidecar_path"].read_text()


def test_cached_verdict_returns_the_most_recently_written_row(tmp_path):
    sidecar_path = tmp_path / "sidecar.csv"
    url = "https://www.youtube.com/watch?v=reprobed"
    _write_probe_row(sidecar_path, url, verdict="reject-dead", reason="first try")
    _write_probe_row(sidecar_path, url, verdict="accept", duration_seconds=1000.0)

    result = queue_probe.cached_verdict(url, sidecar_path=sidecar_path)

    assert result.verdict == "accept"
    assert result.duration_seconds == 1000.0


def test_cached_verdict_none_when_url_never_probed(tmp_path):
    sidecar_path = tmp_path / "sidecar.csv"
    _write_probe_row(sidecar_path, "https://example.com/other", verdict="accept")
    assert (
        queue_probe.cached_verdict(
            "https://example.com/never-probed", sidecar_path=sidecar_path
        )
        is None
    )


def test_append_queue_line_is_dedupe_checked(tmp_path):
    queue_path = tmp_path / "queue.txt"
    url = "https://example.com/m.mp4"
    assert (
        queue_probe.append_queue_line(
            url, "https://example.com/page", queue_path=queue_path
        )
        is True
    )
    assert (
        queue_probe.append_queue_line(
            url, "https://example.com/page", queue_path=queue_path
        )
        is False
    )
    lines = [ln for ln in queue_path.read_text().splitlines() if ln.strip()]
    assert lines == ["https://example.com/m.mp4\thttps://example.com/page"]


def test_append_deferred_line_writes_the_real_column_shape(tmp_path):
    deferred_path = tmp_path / "deferred.txt"
    queue_probe.append_deferred_line(
        "https://example.com/long.mp4",
        source_url="https://example.com/page",
        gov_id="us:place:0000005",
        jurisdiction="Some City, ST",
        duration_seconds=13001,  # 3:36:41
        title="City Council Meeting",
        deferred_path=deferred_path,
    )
    lines = [
        ln for ln in deferred_path.read_text().splitlines() if not ln.startswith("#")
    ]
    assert lines == [
        "https://example.com/long.mp4\thttps://example.com/page\tus:place:0000005"
        "\tSome City, ST\t3:36:41\tCity Council Meeting"
    ]


def test_append_deferred_line_never_re_adds_a_url_already_present(tmp_path):
    deferred_path = tmp_path / "deferred.txt"
    url = "https://example.com/long.mp4"
    assert (
        queue_probe.append_deferred_line(
            url, duration_seconds=6000, deferred_path=deferred_path
        )
        is True
    )
    assert (
        queue_probe.append_deferred_line(
            url, duration_seconds=6000, deferred_path=deferred_path
        )
        is False
    )
    match_count = sum(1 for ln in deferred_path.read_text().splitlines() if url in ln)
    assert match_count == 1


def test_parse_pin_row_pipe_shape():
    parsed = queue_probe.parse_pin_row(
        "www.youtube.com|youtube:abc123|us:place:0000001|fallback|wo216|evidence text"
    )
    assert parsed == {
        "host": "www.youtube.com",
        "match": "youtube:abc123",
        "gov_id": "us:place:0000001",
        "strength": "fallback",
        "source": "wo216",
        "evidence": "evidence text",
    }


def test_parse_pin_row_malformed_returns_none():
    assert queue_probe.parse_pin_row("not|enough|fields") is None
    assert queue_probe.parse_pin_row("") is None
    assert queue_probe.parse_pin_row(None) is None


def test_write_pin_row_dedupe_checked(tmp_path):
    pins_path = tmp_path / "pins.csv"
    kwargs = dict(
        host="www.youtube.com",
        match="youtube:xyz",
        gov_id="us:place:0000006",
        pins_path=pins_path,
    )
    assert queue_probe.write_pin_row(**kwargs) is True
    assert queue_probe.write_pin_row(**kwargs) is False
    assert pins_path.read_text().count("www.youtube.com") == 1


def test_write_pin_row_blank_match_allowed_on_single_tenant_host(tmp_path):
    """WO-307 (2026-09-12): a blank `match` is exactly what the
    committed tenant_overrides.csv already uses for a single-tenant
    Viebit/Cablecast/TelVue subdomain (one government per tenant) --
    this function used to refuse it unconditionally, silently blocking a
    real already-queued government (buffalo.viebit.com) from ever being
    pinned via the shared finish path."""
    pins_path = tmp_path / "pins.csv"
    assert (
        queue_probe.write_pin_row(
            host="buffalo.viebit.com",
            match="",
            gov_id="us:place:2708452",
            pins_path=pins_path,
        )
        is True
    )
    assert "buffalo.viebit.com" in pins_path.read_text()


def test_write_pin_row_blank_match_still_refused_on_multi_gov_host(tmp_path):
    """The WO-210 safeguard this function was built to honour: a blank
    match on a real multi-government host (youtube.com, vimeo.com, ...)
    must still be refused outright -- it would key every unidentified
    video on the whole host to one government."""
    pins_path = tmp_path / "pins.csv"
    assert (
        queue_probe.write_pin_row(
            host="www.youtube.com",
            match="",
            gov_id="us:place:0000006",
            pins_path=pins_path,
        )
        is False
    )
    assert not pins_path.exists()
