"""WO-1111: the weak-lead triage step (scripts/meeting_finder_weak_lead_triage.py).

SYNTHETIC rows: hand-built verdict dicts in the real VerdictRow shape. The
video keys are real ones from rtr-business research/known_non_meeting_videos.csv
(Vimeo 1082634179 is TASB's "Boardbook" demo, seen on 64 governments;
lmsoverview.mp4 is a learning-software tutorial hosted on several vendors).
"""

from scripts.meeting_finder_weak_lead_triage import band, triage, video_keys

KNOWN_BAD = {"vimeo:1082634179", "file:lmsoverview.mp4"}


def _row(url, seconds, outcome="video-low-confidence", **extra):
    return {"outcome": outcome, "result_url": url, "duration_seconds": seconds, **extra}


def test_known_bad_video_is_skipped_on_any_host_or_url_form():
    rows = [
        _row("https://player.vimeo.com/video/1082634179?h=abc", None),
        _row("https://www.schoolinsight.com/videos/lmsoverview.mp4", 262),
        _row("https://www.teacherease.com/videos/lmsoverview.mp4", None),
    ]
    kept, skipped = triage(rows, KNOWN_BAD)
    assert kept == []
    assert skipped["known non-meeting video"] == 3


def test_duration_bands_order_and_skip():
    rows = [
        _row("https://a.example/x.mp4", 30 * 60),  # 20-40
        _row("https://a.example/y.mp4", 90 * 60),  # 70+
        _row("https://a.example/z.mp4", 5 * 60),  # under 8: skipped
        _row("https://a.example/w.mp4", 12 * 60),  # 8-20: skipped by default
        _row("https://player.vimeo.com/video/111", None),  # unknown: kept
        _row("https://a.example/v.mp4", 50 * 60),  # 40-70
    ]
    kept, skipped = triage(rows, KNOWN_BAD)
    assert [c["band"] for c in kept] == ["70+", "40-70", "20-40", "unknown"]
    assert skipped["under 8 minutes"] == 1
    assert skipped["8-20 minutes (not requested)"] == 1
    kept2, _ = triage(rows, KNOWN_BAD, include_8_20=True)
    assert [c["band"] for c in kept2][-1] == "8-20"


def test_only_weak_leads_are_considered():
    rows = [
        _row(
            "https://a.example/found.mp4", 3600, outcome=""
        ),  # a find, not a weak lead
        _row(
            "https://a.example/lead.mp4",
            3600,
            outcome="youtube-lead-only",
            handcheck_lead="no",
        ),
        _row(
            "https://a.example/hc.mp4",
            3600,
            outcome="blocked-headless",
            handcheck_lead="yes",
        ),
    ]
    kept, _ = triage(rows, KNOWN_BAD)
    assert [c["result_url"] for c in kept] == ["https://a.example/hc.mp4"]


def test_video_keys_and_band_helpers():
    assert "youtube:oUiFfxPgFeM" in video_keys(
        "https://www.youtube.com/watch?v=oUiFfxPgFeM"
    )
    assert "file:shared authentication public users.mp4" in video_keys(
        "https://socshelp.socs.net/sharedvideos/Shared%20Authentication%20Public%20Users.mp4"
    )
    assert (
        band(None) == "unknown" and band(7 * 60) == "under-8" and band(70 * 60) == "70+"
    )
