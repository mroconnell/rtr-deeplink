"""Tests for scripts/youtube_drip.py's pure helpers and its scheduler,
with every YouTube- or Archive-touching lane replaced by a fake -- the
real lanes are the three existing scripts' own functions, covered by
their own tests."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import youtube_drip as yd  # noqa: E402


def test_is_block_text_matches_real_signals_only():
    assert yd.is_block_text("ERROR: [youtube] abc: Sign in to confirm you're not a bot")
    assert yd.is_block_text("IpBlocked: You have done too many requests")
    assert yd.is_block_text("HTTP Error 429: Too Many Requests")
    assert yd.is_block_text(
        "YouTube is currently blocking caption requests from our server"
    )
    assert not yd.is_block_text(
        "ERROR: [youtube] mVJ3mgtlvtY: This video is unavailable"
    )
    assert not yd.is_block_text("[SKIP] no video found on re-resolve: https://x")
    assert not yd.is_block_text("")


def test_next_block_sleep_escalates_and_caps():
    assert [yd.next_block_sleep(i) for i in range(7)] == [
        900,
        1800,
        3600,
        7200,
        14400,
        14400,
        14400,
    ]


def test_youtube_queue_lines_keeps_only_youtube_videos():
    lines = [
        "# comment",
        "",
        "https://www.youtube.com/watch?v=ax-OzF0VRk4\thttps://www.youtube.com/channel/UCx",
        "https://youtu.be/L3DcyYnvty0",
        "https://cityoftacoma.granicus.com/player/clip/7460",
        "https://www.youtube.com/@CityofEnnisTexas/streams",
        "https://www.youtube.com/embed/livestreaming?rel=0",
        "https://desmoines.civicweb.net/Portal/MeetingInformation.aspx?Id=582",
    ]
    out = yd.youtube_queue_lines(lines)
    assert [u for _, u, _ in out] == [
        "https://www.youtube.com/watch?v=ax-OzF0VRk4",
        "https://youtu.be/L3DcyYnvty0",
        "https://desmoines.civicweb.net/Portal/MeetingInformation.aspx?Id=582",
    ]
    assert out[0][2] == "https://www.youtube.com/channel/UCx"
    assert out[1][2] is None


def test_slug_from_page_url():
    assert (
        yd.slug_from_page_url("https://redtaperecordings.com/m/new-prague-mn")
        == "new-prague-mn"
    )
    assert yd.slug_from_page_url("https://redtaperecordings.com/m/x/") == "x"
    assert yd.slug_from_page_url(None) is None


def test_pick_caption_page_prefers_freshly_fed_pages_and_skips_done():
    pages = [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]
    assert yd.pick_caption_page(pages, {"a": "ingested"}, ["c"])["slug"] == "c"
    assert yd.pick_caption_page(pages, {"a": "ingested"}, [])["slug"] == "b"
    assert yd.pick_caption_page(pages, {"a": 1, "b": 1, "c": 1}, ["c"]) is None


def test_advance_queue_lines_drops_only_fed_urls_and_keeps_comments():
    lines = [
        "# keep me",
        "https://www.youtube.com/watch?v=aaaaaaaaaaa\thttps://gov.example",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        "https://cityoftacoma.granicus.com/player/clip/7460",
    ]
    kept, dropped = yd.advance_queue_lines(
        lines, {"https://www.youtube.com/watch?v=aaaaaaaaaaa"}
    )
    assert dropped == 1
    assert kept == [
        "# keep me",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        "https://cityoftacoma.granicus.com/player/clip/7460",
    ]


def test_audio_page_from_export_row_needs_youtube_and_the_marker():
    row = {
        "slug": "s",
        "platform": "youtube",
        "external_id": None,
        "video_format": "youtube",
        "source_url_normalized": "https://x.civicweb.net/p",
        "video_url": "https://www.youtube.com/embed/aaaaaaaaaaa",
        "versions": [{"transcript_warnings": [yd.YOUTUBE_CAPTIONS_DISABLED_MARKER]}],
    }
    page = yd.audio_page_from_export_row(row)
    assert page["slug"] == "s" and page["video_format"] == "youtube"
    assert yd.audio_page_from_export_row({**row, "video_format": "m3u8"}) is None
    assert (
        yd.audio_page_from_export_row(
            {**row, "versions": [{"transcript_warnings": ["other"]}]}
        )
        is None
    )


def test_state_rollover_writes_yesterday_and_resets(tmp_path):
    state = yd.State(tmp_path / "state.json")
    state.rollover(tmp_path / "daily.csv", today="2026-09-11")
    state.bump("captions_ingested", 3)
    state.bump("blocks")
    state.rollover(tmp_path / "daily.csv", today="2026-09-12")
    rows = (tmp_path / "daily.csv").read_text().splitlines()
    assert rows[0].startswith("day,captions_ingested")
    assert rows[1] == "2026-09-11,3,0,0,0,0,0,0,1"
    assert state.data["today"] == {} and state.data["day"] == "2026-09-12"


def _drip(tmp_path, lanes=("captions", "feed", "audio")):
    state = yd.State(tmp_path / "state.json")
    return yd.Drip(
        state,
        dry_run=True,
        lanes=lanes,
        audio_per_day=3,
        spacing=100.0,
        model_size=None,
        cpu_threads=None,
    )


def test_tick_runs_first_lane_with_work_and_paces(tmp_path, monkeypatch):
    drip = _drip(tmp_path)
    calls = []

    async def captions(session):
        calls.append("captions")
        return False, None

    async def feed(session):
        calls.append("feed")
        return True, None

    async def audio(session):
        calls.append("audio")
        return True, None

    monkeypatch.setattr(drip, "lane_captions", captions)
    monkeypatch.setattr(drip, "lane_feed", feed)
    monkeypatch.setattr(drip, "lane_audio", audio)
    sleep = asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert calls == ["captions", "feed"]  # audio not reached: feed touched YouTube
    assert 100.0 <= sleep <= 100.0 + yd.SPACING_JITTER_SECONDS
    assert (tmp_path / "state.json").exists()


def test_tick_idles_when_no_lane_has_work(tmp_path, monkeypatch):
    drip = _drip(tmp_path)

    async def nothing(session):
        return False, None

    for name in ("lane_captions", "lane_feed", "lane_audio"):
        monkeypatch.setattr(drip, name, nothing)
    assert asyncio.run(drip.tick(None, tmp_path / "daily.csv")) == yd.IDLE_SLEEP_SECONDS


def test_tick_honours_a_block_and_the_ladder_escalates(tmp_path, monkeypatch):
    drip = _drip(tmp_path, lanes=("captions",))

    async def blocked(session):
        return True, drip._block("blocked_until", "block_level", "IpBlocked")

    monkeypatch.setattr(drip, "lane_captions", blocked)
    first = asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert first == 900.0
    # while blocked, tick sleeps out the block without calling any lane
    remaining = asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert 0 < remaining <= 900.0
    drip.state.data["blocked_until"] = 0
    assert asyncio.run(drip.tick(None, tmp_path / "daily.csv")) == 1800.0
    assert drip.state.data["blocks_total"] == 2


def test_lane_audio_respects_daily_cap(tmp_path):
    drip = _drip(tmp_path, lanes=("audio",))
    drip.state.data["audio_queue"] = [{"slug": "s"}]
    drip.state.data["today"]["audio_downloads"] = 3
    assert asyncio.run(drip.lane_audio(None)) == (False, None)


@pytest.mark.parametrize("cmd", [["run", "--once", "--dry-run"], ["advance"]])
def test_parser_accepts_documented_commands(cmd):
    args = yd.build_parser().parse_args(cmd)
    assert args.command in ("run", "advance")


def test_needs_identity_review_mirrors_evidence_tiers():
    ok = {"gov_id": "us:place:0686440", "jurisdiction_confidence": "registry"}
    assert not yd.needs_identity_review(ok)
    assert not yd.needs_identity_review({**ok, "jurisdiction_confidence": "pinned"})
    assert yd.needs_identity_review({**ok, "jurisdiction_confidence": "inferred"})
    assert yd.needs_identity_review({**ok, "gov_id": "rtr:unknown"})
    assert yd.needs_identity_review(
        {"gov_id": "", "jurisdiction_confidence": "registry"}
    )
    assert yd.needs_identity_review({"slug": "only"})


def test_fed_page_row_and_append(tmp_path):
    row = yd.fed_page_row(
        {
            "slug": "s",
            "gov_id": "rtr:abc",
            "jurisdiction": "Somewhere",
            "jurisdiction_confidence": "minted",
            "video_channel": "@x",
            "video_channel_id": "UC1",
        },
        queue_url="https://www.youtube.com/watch?v=aaaaaaaaaaa",
        source_url=None,
        fed_at="2026-09-11T02:00:00",
    )
    assert (
        row["page_url"] == "/m/s"
        and row["needs_review"] == "yes"
        and row["source_url"] == ""
    )
    path = tmp_path / "fed_pages.csv"
    yd.append_fed_page_row(path, row)
    yd.append_fed_page_row(path, row)
    lines = path.read_text().splitlines()
    assert lines[0].split(",") == list(yd.FED_PAGES_COLUMNS)
    assert len(lines) == 3


def test_find_channel_on_page_and_meeting_words():
    html = (
        '<a href="https://www.youtube.com/channel/UCzhcoASavyb3nVr4jxzx8vA">YouTube</a>'
    )
    assert (
        yd.find_channel_on_page(html)
        == "https://www.youtube.com/channel/UCzhcoASavyb3nVr4jxzx8vA"
    )
    assert (
        yd.find_channel_on_page('href="https://youtube.com/@CityofEnnisTexas"')
        == "https://www.youtube.com/@CityofEnnisTexas"
    )
    assert yd.find_channel_on_page("<p>no links</p>") is None
    assert yd.looks_like_meeting("Regular Council - 12 May 2026")
    assert yd.looks_like_meeting("Fiscal Court Meeting")
    assert not yd.looks_like_meeting("Welcome to Crowley County")
    assert not yd.looks_like_meeting(None)


def test_dead_video_rows_one_per_candidate_or_a_blank_row():
    page = {
        "slug": "s",
        "source_url_normalized": "https://x.civicweb.net/p",
        "video_url": "https://www.youtube.com/embed/aaaaaaaaaaa",
    }
    rows = yd.dead_video_rows(
        page,
        "YouTube: video is unavailable",
        "https://www.youtube.com/channel/UC1",
        [
            ("bbbbbbbbbbb", "Council - 02 Sep 2026"),
            ("ccccccccccc", "Council - 20 Aug 2026"),
        ],
        "t",
    )
    assert [r["candidate_video_id"] for r in rows] == ["bbbbbbbbbbb", "ccccccccccc"]
    assert rows[0]["channel_url"].endswith("UC1") and rows[0]["slug"] == "s"
    blank = yd.dead_video_rows(page, "reject-dead", None, [], "t")
    assert (
        len(blank) == 1
        and blank[0]["candidate_video_id"] == ""
        and blank[0]["channel_url"] == ""
    )


def test_fed_page_row_carries_title_and_meeting_flag():
    row = yd.fed_page_row(
        {"slug": "s", "title": "100th Anniversary of the Courthouse"},
        queue_url="u",
        source_url=None,
        fed_at="t",
    )
    assert row["looks_like_meeting"] == "no" and row["needs_review"] == "yes"
