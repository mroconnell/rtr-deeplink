"""WO-1146: a Vimeo find with captions is tier 2, not tier 1.

Tier 2 = captions exist, but only a local run can read them (Ryan,
2026-09-26; rtr-discovery's `roster.TIER2_PLATFORMS`). From an office Mac
the Vimeo adapter still returns real caption segments -- Meeting Finder
read them for Gwinnett County Schools' board meeting on 2026-09-27 and
labelled it tier 1 -- but Vimeo answers the server with a 401 challenge
(BACKLOG.md, WO-1120), so the page could never be ingested with those
captions. The URLs below are SYNTHETIC shapes of real hosts.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.resolve import captions_local_only


def test_vimeo_platform_is_local_only():
    assert captions_local_only("vimeo", "https://player.vimeo.com/video/1")


def test_delegated_vimeo_video_is_local_only():
    # BoardDocs and Chicago ELMS pages embed Vimeo.
    assert captions_local_only("boarddocs", "https://player.vimeo.com/video/1")
    assert captions_local_only("chicago_elms", "https://vimeo.com/1")


def test_other_caption_platforms_stay_tier_1():
    assert not captions_local_only("escribe", "https://pub-x.escribemeetings.com/v")
    assert not captions_local_only("granicus", "https://x.granicus.com/MediaPlayer.php")
    assert not captions_local_only("swagit", None)


def test_lookalike_host_is_not_vimeo():
    assert not captions_local_only("direct_file", "https://notvimeo.com/a.mp4")


def test_tier2_lead_kind():
    vimeo = SimpleNamespace(platform="vimeo", video_url="https://vimeo.com/1")
    delegated = SimpleNamespace(
        platform="boarddocs", video_url="https://player.vimeo.com/video/2"
    )
    youtube = SimpleNamespace(platform="youtube", video_url="https://youtu.be/x")
    assert runner._tier2_lead_kind(vimeo) == "vimeo"
    assert runner._tier2_lead_kind(delegated) == "vimeo"
    assert runner._tier2_lead_kind(youtube) == "youtube"
