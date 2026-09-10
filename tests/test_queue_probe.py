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
