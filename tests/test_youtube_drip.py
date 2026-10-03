"""Tests for scripts/youtube_drip.py's pure helpers and its scheduler,
with every YouTube- or Archive-touching lane replaced by a fake -- the
real lanes are the three existing scripts' own functions, covered by
their own tests."""

import asyncio
import csv
import sys
import time
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
        # WO-367: BoardDocs (WO-365) is a YOUTUBE_DELEGATING_PLATFORMS member
        # too -- real Tallahassee City Commission goto URL, confirmed live
        # 2026-09-09 (see full_wo367.md).
        "https://go.boarddocs.com/fla/talgov/Board.nsf/goto?open&id=DU8S8U718044",
    ]
    out = yd.youtube_queue_lines(lines)
    assert [u for _, u, _ in out] == [
        "https://www.youtube.com/watch?v=ax-OzF0VRk4",
        "https://youtu.be/L3DcyYnvty0",
        "https://desmoines.civicweb.net/Portal/MeetingInformation.aspx?Id=582",
        "https://go.boarddocs.com/fla/talgov/Board.nsf/goto?open&id=DU8S8U718044",
    ]
    assert out[0][2] == "https://www.youtube.com/channel/UCx"
    assert out[1][2] is None


def test_check_lines_reports_keep_and_skip_with_a_reason():
    # WO-367: real Tallahassee (fla) and Colorado City schools (az)
    # BoardDocs goto URLs (full_wo367.md) -- both must KEEP now that
    # "boarddocs" is a YOUTUBE_DELEGATING_PLATFORMS member, and both are
    # confirmed to have SKIPPED before that (see this WO's report: run
    # with YOUTUBE_DELEGATING_PLATFORMS reverted to ("civicweb", "primegov")
    # reproduces two skips for these same two lines).
    lines = [
        "# comment",
        "",
        "https://go.boarddocs.com/fla/talgov/Board.nsf/goto?open&id=DU8S8U718044",
        "https://go.boarddocs.com/az/ccschools/Board.nsf/goto?open&id=DGTU4S7A4526",
        "https://cityoftacoma.granicus.com/player/clip/7460",
    ]
    out = yd.check_lines(lines)
    assert [(line, verdict) for line, verdict, _ in out] == [
        (lines[2], "keep"),
        (lines[3], "keep"),
        (lines[4], "skip"),
    ]
    assert out[0][2] == "boarddocs"
    assert out[1][2] == "boarddocs"
    assert out[2][2] == "platform=granicus, not a YouTube or Vimeo delegator"


def test_run_check_lines_cli_prints_one_line_per_row(tmp_path, capsys):
    queue_file = tmp_path / "queue.txt"
    queue_file.write_text(
        "https://go.boarddocs.com/fla/talgov/Board.nsf/goto?open&id=DU8S8U718044\n"
        "https://cityoftacoma.granicus.com/player/clip/7460\n"
    )
    args = yd.build_parser().parse_args(
        ["check-lines", "--check-lines-file", str(queue_file)]
    )
    yd._run_check_lines(args)
    out = capsys.readouterr().out
    assert "keep boarddocs" in out
    assert "skip " in out
    assert "go.boarddocs.com" in out
    assert "granicus.com" in out


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


# WO-248: real rows copied verbatim from the tail of
# scripts/tier3_auto_transcription_queue_probe.csv (2026-09-12) -- the
# shape (full 13-column header, including the WO-156 "caller" and WO-170
# "chosen" columns) and the values are real; only the split across a
# tracked file and a local buffer below is synthetic, per CLAUDE.md's
# "synthetic tests reuse a real schema" convention.
_PROBE_HEADER = [
    "url",
    "platform",
    "probe_method",
    "duration_seconds",
    "date",
    "size_bytes",
    "over_nine_minutes",
    "verdict",
    "reason",
    "probe_seconds",
    "probed_at",
    "caller",
    "chosen",
]
_PROBE_ROW_ALREADY_TRACKED = [
    "https://www.youtube.com/watch?v=qKVcd0uCrXU",
    "youtube",
    "yt-dlp-metadata",
    "627.00",
    "2026-07-15",
    "17428006",
    "1",
    "accept",
    "",
    "3.02",
    "2026-09-12T00:26:24+00:00",
    "bulk_ingest",
    "0",
]
_PROBE_ROW_NEW_1 = [
    "https://www.youtube.com/watch?v=WQx8E-QozpU",
    "youtube",
    "yt-dlp-metadata",
    "586.00",
    "2026-09-01",
    "15973103",
    "1",
    "accept",
    "",
    "1.94",
    "2026-09-12T00:26:32+00:00",
    "bulk_ingest",
    "0",
]
_PROBE_ROW_NEW_2 = [
    "https://www.youtube.com/watch?v=wTjmI6zMgXI",
    "youtube",
    "yt-dlp-metadata",
    "559.00",
    "2026-07-09",
    "11129787",
    "1",
    "accept",
    "",
    "1.90",
    "2026-09-12T00:26:43+00:00",
    "bulk_ingest",
    "0",
]


def _write_csv(path, header, rows):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _read_csv(path):
    with path.open(newline="") as f:
        return list(csv.reader(f))


def test_fold_probe_sidecar_appends_only_urls_the_tracked_file_lacks(tmp_path):
    tracked = tmp_path / "tracked.csv"
    _write_csv(tracked, _PROBE_HEADER, [_PROBE_ROW_ALREADY_TRACKED])

    local = tmp_path / "local.csv"
    # The drip re-probed a URL main already has a row for (a duplicate
    # from a different day/run) plus two genuinely new ones.
    _write_csv(
        local,
        _PROBE_HEADER,
        [_PROBE_ROW_ALREADY_TRACKED, _PROBE_ROW_NEW_1, _PROBE_ROW_NEW_2],
    )

    appended = yd.fold_probe_sidecar(local, tracked)
    assert appended == 2

    rows = _read_csv(tracked)
    assert rows[0] == _PROBE_HEADER
    assert [r[0] for r in rows[1:]] == [
        _PROBE_ROW_ALREADY_TRACKED[0],
        _PROBE_ROW_NEW_1[0],
        _PROBE_ROW_NEW_2[0],
    ]
    # fold_probe_sidecar never touches the local buffer itself.
    assert local.exists()


def test_fold_probe_sidecar_creates_the_tracked_file_when_it_does_not_exist(
    tmp_path,
):
    local = tmp_path / "local.csv"
    _write_csv(local, _PROBE_HEADER, [_PROBE_ROW_NEW_1])

    tracked = tmp_path / "tracked.csv"
    assert not tracked.exists()

    appended = yd.fold_probe_sidecar(local, tracked)
    assert appended == 1
    assert _read_csv(tracked) == [_PROBE_HEADER, _PROBE_ROW_NEW_1]


def test_fold_probe_sidecar_is_a_noop_for_a_missing_or_header_only_buffer(
    tmp_path,
):
    tracked = tmp_path / "tracked.csv"
    _write_csv(tracked, _PROBE_HEADER, [_PROBE_ROW_ALREADY_TRACKED])
    before = tracked.read_text()

    missing_local = tmp_path / "missing.csv"
    assert yd.fold_probe_sidecar(missing_local, tracked) == 0

    empty_local = tmp_path / "empty.csv"
    _write_csv(empty_local, _PROBE_HEADER, [])
    assert yd.fold_probe_sidecar(empty_local, tracked) == 0

    assert tracked.read_text() == before  # untouched either way


def test_clear_local_probe_sidecar_removes_the_file_and_is_safe_if_missing(
    tmp_path,
):
    local = tmp_path / "local.csv"
    _write_csv(local, _PROBE_HEADER, [_PROBE_ROW_NEW_1])
    yd.clear_local_probe_sidecar(local)
    assert not local.exists()

    yd.clear_local_probe_sidecar(local)  # already gone -- must not raise


def test_lane_feed_sends_the_local_probe_buffer_not_the_tracked_sidecar(
    tmp_path, monkeypatch
):
    """WO-248: lane_feed must route every probe row through the drip's own
    local, gitignored buffer (LOCAL_PROBE_SIDECAR_PATH), never the tracked
    DEFAULT_SIDECAR_PATH -- that's the whole fix. Confirmed by monkeypatching
    the real scripts.feed_tier3_auto_transcription._push_if_has_video and
    capturing which sidecar path lane_feed actually passed it, rather than
    trusting the call site wasn't changed back."""
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text("https://www.youtube.com/watch?v=ccccccccccc\n")
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)

    drip = yd.Drip(
        yd.State(tmp_path / "state.json"),
        dry_run=False,
        lanes=("feed",),
        audio_per_day=3,
        spacing=100.0,
        model_size=None,
        cpu_threads=None,
    )

    captured = {}

    async def fake_push(session, url, src=None, *, probe_sidecar_path=None):
        captured["probe_sidecar_path"] = probe_sidecar_path
        return f"[OK] {url} -> /m/example"

    monkeypatch.setattr(feed_mod, "_push_if_has_video", fake_push)

    touched, override = asyncio.run(drip.lane_feed(None))
    assert touched is True
    assert override is None
    assert captured["probe_sidecar_path"] == yd.LOCAL_PROBE_SIDECAR_PATH
    assert captured["probe_sidecar_path"] != yd.DEFAULT_SIDECAR_PATH


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
    # WO-1147: the CSV row grew four new vimeo_* columns at the end
    # (ingested/marked/failed/blocks) -- this test's expected row is
    # updated to match, still all-zero here since no vimeo activity
    # happened in this test.
    state = yd.State(tmp_path / "state.json")
    state.rollover(tmp_path / "daily.csv", today="2026-09-11")
    state.bump("captions_ingested", 3)
    state.bump("blocks")
    state.rollover(tmp_path / "daily.csv", today="2026-09-12")
    rows = (tmp_path / "daily.csv").read_text().splitlines()
    assert rows[0].startswith("day,captions_ingested")
    assert rows[0].endswith("vimeo_ingested,vimeo_marked,vimeo_failed,vimeo_blocks")
    assert rows[1] == "2026-09-11,3,0,0,0,0,0,0,1,0,0,0,0"
    assert state.data["today"] == {} and state.data["day"] == "2026-09-12"


def test_state_rollover_records_vimeo_activity_in_its_own_columns(tmp_path):
    state = yd.State(tmp_path / "state.json")
    state.rollover(tmp_path / "daily.csv", today="2026-09-11")
    state.bump("vimeo_ingested", 2)
    state.bump("vimeo_marked")
    state.bump("vimeo_blocks")
    state.rollover(tmp_path / "daily.csv", today="2026-09-12")
    rows = (tmp_path / "daily.csv").read_text().splitlines()
    # captions/feed/audio/blocks columns stay 0 -- vimeo activity never
    # touches the shared YouTube-family counters.
    assert rows[1] == "2026-09-11,0,0,0,0,0,0,0,0,2,1,0,1"


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


def test_lane_vimeo_ingests_and_tracks_its_own_done_dict(tmp_path, monkeypatch):
    import scripts.fetch_vimeo_transcripts as vimeo_fetch

    drip = _drip(tmp_path, lanes=("vimeo",))
    drip.dry_run = False

    async def fake_get_wanted(session):
        return [{"slug": "v1", "platform": "vimeo", "video_url": "https://vimeo.com/1"}]

    async def fake_process_one(session, page, *, dry_run):
        return {"slug": page["slug"], "status": "ingested", "detail": "3 segments"}

    monkeypatch.setattr(vimeo_fetch, "_get_wanted", fake_get_wanted)
    monkeypatch.setattr(vimeo_fetch, "process_one", fake_process_one)

    touched, override = asyncio.run(drip.lane_vimeo(None))
    assert touched is True and override is None
    assert drip.state.data["vimeo_done"] == {"v1": "ingested"}
    assert drip.state.data["today"]["vimeo_ingested"] == 1
    # The YouTube-family done dict is untouched.
    assert drip.state.data["captions_done"] == {}


def test_lane_vimeo_block_is_independent_of_the_youtube_ladder(tmp_path, monkeypatch):
    import scripts.fetch_vimeo_transcripts as vimeo_fetch

    drip = _drip(tmp_path, lanes=("vimeo",))
    drip.dry_run = False

    async def fake_get_wanted(session):
        return [{"slug": "v1", "platform": "vimeo", "video_url": "https://vimeo.com/1"}]

    async def fake_process_one(session, page, *, dry_run):
        return {
            "slug": page["slug"],
            "status": "blocked",
            "detail": "player page returned a challenge (HTTP 401)",
        }

    monkeypatch.setattr(vimeo_fetch, "_get_wanted", fake_get_wanted)
    monkeypatch.setattr(vimeo_fetch, "process_one", fake_process_one)

    touched, sleep_for = asyncio.run(drip.lane_vimeo(None))
    assert touched is True
    assert sleep_for == 900.0
    # Vimeo's own ladder moved -- the YouTube-family one did not.
    assert drip.state.data["vimeo_blocked_until"] > 0
    assert drip.state.data["vimeo_block_level"] == 1
    assert drip.state.data["blocked_until"] == 0
    assert drip.state.data["block_level"] == 0
    # And the shared "blocks" counter (YouTube-family) is untouched --
    # only the Vimeo-only counter bumped.
    assert drip.state.data["today"].get("blocks", 0) == 0
    assert drip.state.data["today"]["vimeo_blocks"] == 1
    assert drip.state.data["vimeo_done"] == {}  # a blocked page is not "done"


def test_lane_vimeo_returns_no_work_when_queue_is_empty(tmp_path, monkeypatch):
    import scripts.fetch_vimeo_transcripts as vimeo_fetch

    drip = _drip(tmp_path, lanes=("vimeo",))

    async def fake_get_wanted(session):
        return []

    monkeypatch.setattr(vimeo_fetch, "_get_wanted", fake_get_wanted)
    assert asyncio.run(drip.lane_vimeo(None)) == (False, None)


def test_tick_includes_vimeo_lane_only_when_enabled(tmp_path, monkeypatch):
    drip = _drip(tmp_path, lanes=("vimeo",))
    calls = []

    async def vimeo(session):
        calls.append("vimeo")
        return False, None

    monkeypatch.setattr(drip, "lane_vimeo", vimeo)
    asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert calls == ["vimeo"]

    drip2 = _drip(tmp_path, lanes=("captions",))  # vimeo not in lanes

    async def should_not_run(session):
        raise AssertionError("lane_vimeo must not run when not in --lanes")

    monkeypatch.setattr(drip2, "lane_vimeo", should_not_run)
    monkeypatch.setattr(drip2, "lane_captions", lambda session: _ok_no_work())
    asyncio.run(drip2.tick(None, tmp_path / "daily.csv"))


async def _ok_no_work():
    return False, None


def test_youtube_queue_lines_keeps_a_real_vimeo_video_and_skips_a_listing():
    # Real Vimeo URL shapes from tests/test_vimeo.py's own fixtures (per
    # CLAUDE.md's synthetic-test convention: reuse a confirmed-real shape).
    lines = [
        "https://vimeo.com/1212025580",
        "https://player.vimeo.com/video/1223368476",
        "https://vimeo.com/showcase/crrma",  # a listing, not one meeting
        "https://cityoftacoma.granicus.com/player/clip/7460",
    ]
    out = yd.youtube_queue_lines(lines)
    assert [u for _, u, _ in out] == [
        "https://vimeo.com/1212025580",
        "https://player.vimeo.com/video/1223368476",
    ]


def test_classify_queue_url_vimeo_listing_is_skipped():
    keep, detail = yd._classify_queue_url("https://vimeo.com/showcase/crrma")
    assert keep is False
    assert "not a real single-video URL" in detail


def test_lane_audio_respects_daily_cap(tmp_path):
    drip = _drip(tmp_path, lanes=("audio",))
    drip.state.data["audio_queue"] = [{"slug": "s"}]
    drip.state.data["today"]["audio_downloads"] = 3
    assert asyncio.run(drip.lane_audio(None)) == (False, None)


@pytest.mark.parametrize(
    "cmd", [["run", "--once", "--dry-run"], ["advance"], ["check-lines"]]
)
def test_parser_accepts_documented_commands(cmd):
    args = yd.build_parser().parse_args(cmd)
    assert args.command in ("run", "advance", "check-lines")


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


def test_safe_tick_turns_an_archive_timeout_into_a_pause(tmp_path, monkeypatch, caplog):
    # Confirmed live 2026-09-11: a ClientConnectorError from the captions
    # lane's Archive GET escaped asyncio.run() and ended the process.
    drip = _drip(tmp_path, lanes=("captions",))
    attempts = []

    async def flaky(session):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError(
                "Cannot connect to host rtr-deeplink-archive.onrender.com:443"
            )
        return False, None

    monkeypatch.setattr(drip, "lane_captions", flaky)
    csv_path = tmp_path / "daily.csv"
    with caplog.at_level("INFO", logger="youtube_drip"):
        first = asyncio.run(drip.safe_tick(None, csv_path))
        second = asyncio.run(drip.safe_tick(None, csv_path))
        third = asyncio.run(drip.safe_tick(None, csv_path))
    assert first == second == yd.TRANSIENT_ERROR_SLEEP_SECONDS
    assert third == yd.IDLE_SLEEP_SECONDS  # the lane ran and found nothing
    assert drip.consecutive_errors == 0
    assert "tick failed (2 in a row)" in caplog.text
    assert "tick recovered after 2 failure(s)" in caplog.text
    # not the YouTube block ladder: no block recorded, nothing to wait out
    assert drip.state.data["blocks_total"] == 0
    assert drip.state.data["blocked_until"] == 0


def test_safe_tick_reraises_for_a_one_shot_run(tmp_path, monkeypatch):
    drip = _drip(tmp_path, lanes=("captions",))

    async def boom(session):
        raise ConnectionError("Operation timed out")

    monkeypatch.setattr(drip, "lane_captions", boom)
    with pytest.raises(ConnectionError):
        asyncio.run(drip.safe_tick(None, tmp_path / "daily.csv", reraise=True))


# --- WO-1168: the direct lane -----------------------------------------------


def test_direct_lane_takes_the_complement_of_the_feed_lanes_filter(
    tmp_path, monkeypatch
):
    """The direct lane must never claim a YouTube or Vimeo line (or a
    delegating-platform one) -- those stay lane_feed's job. A granicus
    line, which _classify_queue_url() always skips, is exactly what the
    direct lane should pick up."""
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text(
        "https://www.youtube.com/watch?v=ax-OzF0VRk4\n"
        "https://vimeo.com/1212025580\n"
        "https://cityoftacoma.granicus.com/player/clip/7460\n"
    )
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)

    drip = _drip(tmp_path, lanes=("direct",))
    drip.dry_run = False
    monkeypatch.setattr(drip, "_direct_backlog_count", _async_const(0))

    captured = {}

    async def fake_push(
        session, url, src=None, gov_id=None, *, probe_sidecar_path=None
    ):
        captured["url"] = url
        return f"[OK] {url} -> /m/example"

    monkeypatch.setattr(feed_mod, "_push_if_has_video", fake_push)

    touched, override = asyncio.run(drip.lane_direct(None))
    assert touched is True and override is None
    assert captured["url"] == "https://cityoftacoma.granicus.com/player/clip/7460"


def _async_const(value):
    async def f(*args, **kwargs):
        return value

    return f


def test_direct_lane_ok_skip_fail_go_to_the_shared_fed_dict(tmp_path, monkeypatch):
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text("https://cityoftacoma.granicus.com/player/clip/7460\n")
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)

    for outcome, expected_counter in (
        ("[OK] u -> /m/x", "direct_ok"),
        ("[SKIP] no video found on re-resolve: u", "direct_skipped"),
        ("[FAIL] ingest failed: u (500)", "direct_skipped"),
    ):
        drip = _drip(tmp_path, lanes=("direct",))
        drip.dry_run = False
        monkeypatch.setattr(drip, "_direct_backlog_count", _async_const(0))
        monkeypatch.setattr(feed_mod, "_push_if_has_video", _async_const(outcome))
        touched, override = asyncio.run(drip.lane_direct(None))
        assert touched is True and override is None
        assert (
            "https://cityoftacoma.granicus.com/player/clip/7460"
            in drip.state.data["fed"]
        )
        assert drip.state.data["direct_parked"] == []
        assert drip.state.data["today"].get(expected_counter, 0) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        "[NO-OWNER] no tenant_overrides.csv pin (u)",
        "[NOT-REACHABLE-FROM-GITHUB] hls-403: HTTP 403 (u)",
    ],
)
def test_direct_lane_parks_no_owner_and_not_reachable_instead_of_dropping(
    tmp_path, monkeypatch, outcome
):
    """A [NO-OWNER] or route_kept_line()-kept result is a real, fixable
    gap -- it must land in direct_parked (skipped, never dropped by
    advance), not in the shared `fed` dict advance_queue_lines() drops
    lines from."""
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text("https://cityoftacoma.granicus.com/player/clip/7460\n")
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)

    drip = _drip(tmp_path, lanes=("direct",))
    drip.dry_run = False
    monkeypatch.setattr(drip, "_direct_backlog_count", _async_const(0))
    monkeypatch.setattr(feed_mod, "_push_if_has_video", _async_const(outcome))

    touched, override = asyncio.run(drip.lane_direct(None))
    assert touched is True and override is None
    assert drip.state.data["fed"] == {}
    assert drip.state.data["direct_parked"] == [
        "https://cityoftacoma.granicus.com/player/clip/7460"
    ]
    assert drip.state.data["today"]["direct_parked"] == 1

    # A parked url survives advance_queue_lines() -- only the shared
    # `fed` dict drops a line.
    kept, dropped = yd.advance_queue_lines(
        queue.read_text().splitlines(), set(drip.state.data["fed"])
    )
    assert dropped == 0
    assert kept == ["https://cityoftacoma.granicus.com/player/clip/7460"]

    # And the lane skips the same parked line on the next tick instead of
    # retrying it -- with nothing else in the queue, there's no work left.
    called = {"n": 0}

    async def counting_push(
        session, url, src=None, gov_id=None, *, probe_sidecar_path=None
    ):
        called["n"] += 1
        return "[OK] u -> /m/x"

    monkeypatch.setattr(feed_mod, "_push_if_has_video", counting_push)
    touched2, _ = asyncio.run(drip.lane_direct(None))
    assert touched2 is False
    assert called["n"] == 0


def test_direct_lane_gate_closed_makes_no_push_and_is_not_touched(
    tmp_path, monkeypatch
):
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text("https://cityoftacoma.granicus.com/player/clip/7460\n")
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)

    drip = _drip(tmp_path, lanes=("direct",))
    drip.dry_run = False
    monkeypatch.setattr(
        drip, "_direct_backlog_count", _async_const(drip.direct_low_water)
    )

    def boom(*args, **kwargs):
        raise AssertionError("gate closed -- must not push")

    monkeypatch.setattr(feed_mod, "_push_if_has_video", boom)
    assert asyncio.run(drip.lane_direct(None)) == (False, None)


def test_direct_backlog_count_is_cached_for_30_minutes_and_decremented_on_ok(
    tmp_path, monkeypatch
):
    import aiohttp

    from tests.aiohttp_mock import FakeResponse, mock_session

    drip = _drip(tmp_path, lanes=("direct",))
    from scripts import fetch_youtube_transcripts as fetch

    url = f"{fetch._base_url()}/internal/transcription-backlog"
    pages = {
        "pages": [
            {"platform": "granicus"},
            {"platform": "granicus"},
            {"platform": "youtube"},
            {"platform": "vimeo"},
            {"platform": "civicclerk"},
        ]
    }
    import json as _json

    async def run():
        async with aiohttp.ClientSession() as session:
            count = await drip._direct_backlog_count(session)
            assert count == 3  # granicus x2 + civicclerk; youtube/vimeo excluded

            drip.state.data["direct_backlog_count"] = 999  # would show if re-fetched
            count2 = await drip._direct_backlog_count(session)
            assert count2 == 999  # cache honoured within 30 min, no re-fetch

    with mock_session({url: FakeResponse(200, text=_json.dumps(pages))}):
        asyncio.run(run())


def test_direct_backlog_count_decrements_locally_on_each_ok_feed(tmp_path, monkeypatch):
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text(
        "https://cityoftacoma.granicus.com/player/clip/7460\n"
        "https://antiochca.portal.civicclerk.com/event/18/media\n"
    )
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)

    drip = _drip(tmp_path, lanes=("direct",))
    drip.dry_run = False
    drip.state.data["direct_backlog_count"] = 5
    drip.state.data["direct_backlog_checked_at"] = time.time()

    monkeypatch.setattr(feed_mod, "_push_if_has_video", _async_const("[OK] u -> /m/x"))
    asyncio.run(drip.lane_direct(None))
    assert drip.state.data["direct_backlog_count"] == 4


def test_direct_lane_block_text_uses_the_youtube_ladder(tmp_path, monkeypatch):
    """A Granicus/CivicClerk page can embed YouTube -- a block signal from
    the direct lane's push must escalate the same shared YouTube-family
    ladder lane_feed/lane_captions use, not a separate one."""
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text("https://cityoftacoma.granicus.com/player/clip/7460\n")
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)

    drip = _drip(tmp_path, lanes=("direct",))
    drip.dry_run = False
    monkeypatch.setattr(drip, "_direct_backlog_count", _async_const(0))
    monkeypatch.setattr(
        feed_mod,
        "_push_if_has_video",
        _async_const("ERROR: [youtube] abc: Sign in to confirm you're not a bot"),
    )

    touched, sleep_for = asyncio.run(drip.lane_direct(None))
    assert touched is True
    assert sleep_for == 900.0
    assert drip.state.data["blocked_until"] > 0
    assert drip.state.data["block_level"] == 1
    assert drip.state.data["today"]["blocks"] == 1
    assert drip.state.data["fed"] == {}
    assert drip.state.data["direct_parked"] == []


def test_tick_includes_direct_lane_only_when_enabled(tmp_path, monkeypatch):
    drip = _drip(tmp_path, lanes=("direct",))
    calls = []

    async def direct(session):
        calls.append("direct")
        return False, None

    monkeypatch.setattr(drip, "lane_direct", direct)
    asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert calls == ["direct"]

    drip2 = _drip(tmp_path, lanes=("captions",))  # direct not in lanes

    async def should_not_run(session):
        raise AssertionError("lane_direct must not run when not in --lanes")

    monkeypatch.setattr(drip2, "lane_direct", should_not_run)
    monkeypatch.setattr(drip2, "lane_captions", lambda session: _ok_no_work())
    asyncio.run(drip2.tick(None, tmp_path / "daily.csv"))


# --- WO-1175: a bad item goes to the back, failures are loud ------------------


def test_add_strike_defers_after_the_threshold_and_doubles(tmp_path):
    state = yd.State(tmp_path / "state.json")
    assert state.add_strike("feed|u", 2) == (1, None)
    assert not state.is_deferred("feed|u")
    n, retry_at = state.add_strike("feed|u", 2)
    assert n == 2 and retry_at is not None
    assert state.is_deferred("feed|u")
    first = retry_at - time.time()
    n, retry_at = state.add_strike("feed|u", 2)
    assert (retry_at - time.time()) > first * 1.9  # doubled
    state.clear_strikes("feed|u")
    assert not state.is_deferred("feed|u")
    assert state.data["strikes"] == {}


def test_add_strike_delay_is_capped(tmp_path):
    state = yd.State(tmp_path / "state.json")
    for _ in range(30):
        _, retry_at = state.add_strike("k", 1)
    assert retry_at - time.time() <= yd.STRIKE_RETRY_MAX_SECONDS + 1


def test_a_lane_that_keeps_raising_on_one_item_defers_it_and_loudly_alerts(
    tmp_path, monkeypatch, caplog
):
    drip = _drip(tmp_path, lanes=("feed", "captions"))
    drip.alerts_path = tmp_path / "alerts.log"
    ran = []

    async def feed(session):
        drip.current_item = "feed|https://bad.example/v"
        raise RuntimeError("probe exploded")

    async def captions(session):
        ran.append("captions")
        return False, None

    monkeypatch.setattr(drip, "lane_feed", feed)
    monkeypatch.setattr(drip, "lane_captions", captions)

    asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    # first failure: logged, not yet deferred, and the next lane still ran
    assert not drip.state.is_deferred("feed|https://bad.example/v")
    assert ran == ["captions"]
    assert not (tmp_path / "alerts.log").exists()

    asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert drip.state.is_deferred("feed|https://bad.example/v")
    assert "!!! DRIP ALERT" in caplog.text
    assert "pushed to the back" in (tmp_path / "alerts.log").read_text()


def test_feed_lane_skips_a_deferred_url_and_takes_the_next(tmp_path, monkeypatch):
    import scripts.feed_tier3_auto_transcription as feed_mod

    queue = tmp_path / "queue.txt"
    queue.write_text(
        "https://www.youtube.com/watch?v=aaaaaaaaaaa\n"
        "https://www.youtube.com/watch?v=bbbbbbbbbbb\n"
    )
    monkeypatch.setattr(yd, "QUEUE_FILE", queue)
    seen = []

    async def fake_push(session, url, src, **kw):
        seen.append(url)
        return "[OK] x -> /m/slug"

    monkeypatch.setattr(feed_mod, "_push_if_has_video", fake_push)
    drip = _drip(tmp_path, lanes=("feed",))
    drip.dry_run = False
    drip.fed_pages_csv = None
    for _ in range(2):
        drip.state.add_strike("feed|https://www.youtube.com/watch?v=aaaaaaaaaaa", 2)
    monkeypatch.setattr(yd, "lookup_recent_page", _async_const(None))
    asyncio.run(drip.lane_feed(None))
    assert seen == ["https://www.youtube.com/watch?v=bbbbbbbbbbb"]


def test_a_success_clears_the_items_strikes(tmp_path, monkeypatch):
    drip = _drip(tmp_path, lanes=("feed",))

    async def feed(session):
        drip.current_item = "feed|u"
        return True, None

    monkeypatch.setattr(drip, "lane_feed", feed)
    drip.state.add_strike("feed|u", 5)
    asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert drip.state.data["strikes"] == {}


def test_a_repeated_block_on_one_item_eventually_defers_it(tmp_path, monkeypatch):
    drip = _drip(tmp_path, lanes=("feed",))
    drip.alerts_path = tmp_path / "alerts.log"

    async def feed(session):
        drip.current_item = "feed|u"
        return True, 60.0  # a block override

    monkeypatch.setattr(drip, "lane_feed", feed)
    for _ in range(yd.STRIKE_DEFER_AFTER_BLOCKS):
        asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
    assert drip.state.is_deferred("feed|u")


def test_the_drip_log_handler_is_put_back_if_a_library_removes_it(
    tmp_path, monkeypatch
):
    """transcribe_backlog_locally.py runs logging.basicConfig(force=True) at
    import; the audio lane imports it, which used to silence drip.log."""
    import logging

    handler = logging.FileHandler(tmp_path / "drip.log")
    monkeypatch.setattr(yd, "_DRIP_FILE_HANDLER", handler)
    root = logging.getLogger()
    root.removeHandler(handler)
    drip = _drip(tmp_path, lanes=())
    drip.alerts_path = tmp_path / "alerts.log"
    try:
        asyncio.run(drip.tick(None, tmp_path / "daily.csv"))
        assert handler in root.handlers
        assert "removed the drip.log handler" in (tmp_path / "alerts.log").read_text()
    finally:
        root.removeHandler(handler)
        handler.close()
