"""Zoom cloud recordings (A7). Every response is a real capture, taken
2026-10-17 from two government share links (tests/fixtures/zoom/):

* health: "Board of Health Meetings Jul 1 26" (us02web), with a Zoom
  transcript (59 KB WebVTT).
* sidney: "Impact Fee Committee 9/30/26" (Sidney MT, us06web), no transcript.

The share and play pages are ~500 KB player shells; only their real
`window.__data__` block is kept, which is all the adapter reads.
"""

import json
import re

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

from app.platforms.base import detect_platform
from app.platforms.media_probe import _ffmpeg_input_header_args
from app.platforms.zoom import (
    ZoomAssetFinder,
    _remember_cookies,
    is_zoom_recording_url,
    media_cookie_header,
)

HEALTH = (
    "https://us02web.zoom.us/rec/share/dctR-wr7P5VmzyuWuF9Bhg1WEvZ8etC21OigaW4"
    "BXwO-a7z3qkweE4CWokFMR0LX.qzF2blT1wqOFoy3F?startTime=1782927037000"
)
SIDNEY = (
    "https://us06web.zoom.us/rec/share/CgvcJgv57Wt5pR4qSFae_32Wh4bg5prvquNECq"
    "GXp7P6bKSeci9bymncN1kFc-Fp.AH84e3UKU1HEp0z1"
)


def _routes(name: str, share_url: str) -> dict:
    base = "https://" + share_url.split("/")[2]
    share_page = load_fixture("zoom", f"{name}_share_page.html")
    share_info = load_fixture("zoom", f"{name}_share_info.json")
    play_page = load_fixture("zoom", f"{name}_play_page.html")
    play_info = load_fixture("zoom", f"{name}_play_info.json")
    meeting_id = re.search(r"meetingId:\s*'([^']+)'", share_page).group(1)
    redirect = json.loads(share_info)["result"]["redirectUrl"]
    file_id = re.search(r"fileId:\s*'([^']+)'", play_page).group(1)
    routes = {
        share_url: FakeResponse(status=200, text=share_page),
        f"{base}/nws/recording/1.0/play/share-info/{meeting_id}": FakeResponse(
            status=200, text=share_info
        ),
        base + redirect: FakeResponse(status=200, text=play_page),
        f"{base}/nws/recording/1.0/play/info/{file_id}": FakeResponse(
            status=200, text=play_info
        ),
    }
    transcript = json.loads(play_info)["result"].get("transcriptUrl")
    if transcript:
        routes[base + transcript] = FakeResponse(
            status=200, text=load_fixture("zoom", f"{name}_transcript.vtt")
        )
    return routes


async def test_recording_with_a_zoom_transcript():
    with mock_session(_routes("health", HEALTH)):
        r = await ZoomAssetFinder().resolve(HEALTH)
    assert r.platform == "zoom"
    assert r.title == "Board of Health Meetings Jul 1 26"
    assert r.date == "2026-07-01"
    assert r.video_duration_seconds == 3020.0
    assert r.video_url is None  # the MP4 needs Zoom's cookies: server-only
    assert r.server_media_url.startswith("https://ssrweb.zoom.us/replay02/2026/07/01/")
    assert ".mp4" in r.server_media_url
    assert len(r.segments) > 100
    assert r.segments[0].text.startswith("Public Meetings: Okay, we should be good")
    assert r.segments[0].start == 1.82
    assert r.external_id.startswith("zoom:dctR-wr7P5")
    assert "View original source" in r.video_warnings[0]


async def test_recording_without_a_transcript_is_tier_3():
    with mock_session(_routes("sidney", SIDNEY)):
        r = await ZoomAssetFinder().resolve(SIDNEY)
    assert r.title == "Impact Fee Committee 9/30/26"
    assert r.date == "2026-09-30"
    assert r.video_duration_seconds == 2075.0
    assert r.server_media_url and r.segments == []
    assert r.transcript_warnings == ["No captions found for this video."]


async def test_a_failed_step_says_so_plainly():
    with mock_session({SIDNEY: FakeResponse(status=403, text="")}):
        r = await ZoomAssetFinder().resolve(SIDNEY)
    assert r.video_warnings == ["Could not load this Zoom recording."]
    assert r.server_media_url is None


def test_only_recording_links_are_zoom():
    assert is_zoom_recording_url(SIDNEY)
    assert detect_platform(SIDNEY) == "zoom"
    assert detect_platform("https://bristolct-gov.zoom.us/rec/play/abc.def") == "zoom"
    assert not is_zoom_recording_url("https://us02web.zoom.us/j/81234567890")
    assert detect_platform("https://us02web.zoom.us/j/81234567890") != "zoom"


def test_the_mp4_gets_its_cookies_and_nothing_else_does():
    mp4 = "https://ssrweb.zoom.us/replay02/2026/09/30/x/rec.mp4?sig=1"
    _remember_cookies(mp4, "_zm_ssid=abc; cred=def")
    assert media_cookie_header(mp4) == "_zm_ssid=abc; cred=def"
    args = _ffmpeg_input_header_args(SIDNEY, mp4)
    assert "Cookie: _zm_ssid=abc; cred=def\r\n" in args[1]
    other = _ffmpeg_input_header_args(SIDNEY, "https://example.com/a.mp4")
    assert "Cookie" not in other[1]
