"""WO-934: tests for scripts/check_youtube_video_status.py.

That script makes YouTube requests and may only run on the drip Mac, so every
test here injects a stand-in for the request. NOTHING here reaches YouTube.

The status codes are the ones the 2026-09-09 shared-host study recorded
(BACKLOG.md's "82 archived YouTube meetings have embedding switched off"
entry: 401 for embedding off, 404 deleted, 403 private, 400 malformed ids).
The fetch stand-ins are SYNTHETIC; the mapping they exercise is that study's.
"""

import csv
import datetime as dt
from pathlib import Path

import pytest

from scripts import check_youtube_video_status as checker
from scripts import repair_wrong_pages as repair

REPO_ROOT = Path(__file__).resolve().parent.parent
POOL = REPO_ROOT / "reports" / "wo934_youtube_no_transcript_pool.csv"
TODAY = dt.date(2026, 9, 21)


@pytest.mark.parametrize(
    "code, status",
    [
        (200, "ok"),
        (401, "embedding_disabled"),
        (403, "private"),
        (404, "deleted"),
        (400, "malformed"),
        (429, "unknown"),
        (500, "unknown"),
        (None, "unknown"),
    ],
)
def test_the_studys_codes_map_to_statuses(code, status):
    assert checker.classify_oembed(code)[0] == status


def test_only_gone_statuses_are_the_ones_the_repair_tool_will_delete_on():
    assert set(repair.GONE_STATUSES) == {"deleted", "private", "malformed"}
    assert "unknown" not in repair.GONE_STATUSES
    assert "embedding_disabled" not in repair.GONE_STATUSES
    assert repair.STATUS_COLUMNS == [
        "page_id",
        "video_id",
        "status",
        "checked_on",
        "http_status",
        "note",
    ]


def _pool(*ids):
    return [
        {"page_id": str(100 + i), "video_url": f"https://www.youtube.com/embed/{v}"}
        for i, v in enumerate(ids)
    ]


class Fetch:
    """SYNTHETIC oEmbed. Answers from a table; records what was asked."""

    def __init__(self, table):
        self.table = table
        self.asked = []

    def __call__(self, video_id):
        self.asked.append(video_id)
        return self.table.get(video_id)


def _rows(path):
    return list(csv.DictReader(open(path, newline="", encoding="utf-8")))


def _check(pool, path, fetch, **kw):
    sleeps = []
    kw.setdefault("log", lambda _line: None)
    counts = checker.check_pool(
        pool, path, fetch=fetch, sleep=sleeps.append, today=TODAY, **kw
    )
    return counts, sleeps


def test_each_video_is_asked_once_and_the_answer_is_written(tmp_path):
    out = tmp_path / "status.csv"
    fetch = Fetch({"aaaaaaaaaaa": 200, "bbbbbbbbbbb": 404, "ccccccccccc": 403})
    counts, _ = _check(_pool("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"), out, fetch)
    assert counts == {"ok": 1, "deleted": 1, "private": 1}
    rows = _rows(out)
    assert [(r["page_id"], r["video_id"], r["status"]) for r in rows] == [
        ("100", "aaaaaaaaaaa", "ok"),
        ("101", "bbbbbbbbbbb", "deleted"),
        ("102", "ccccccccccc", "private"),
    ]
    assert all(r["checked_on"] == "2026-09-21" for r in rows)
    # and the repair tool can read the file it writes
    index, problems = repair.read_status_file(out)
    assert problems == []
    assert index.by_page[101][0] == "deleted"


def test_a_rerun_skips_videos_already_answered(tmp_path):
    out = tmp_path / "status.csv"
    pool = _pool("aaaaaaaaaaa", "bbbbbbbbbbb")
    _check(pool, out, Fetch({"aaaaaaaaaaa": 200, "bbbbbbbbbbb": 404}))
    fetch = Fetch({"aaaaaaaaaaa": 200, "bbbbbbbbbbb": 404})
    counts, _ = _check(pool, out, fetch)
    assert fetch.asked == [] and counts == {}
    assert len(_rows(out)) == 2
    # --recheck asks again
    fetch2 = Fetch({"aaaaaaaaaaa": 200, "bbbbbbbbbbb": 404})
    _check(pool, out, fetch2, recheck=True)
    assert fetch2.asked == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_an_address_with_no_readable_id_is_malformed_without_a_request(tmp_path):
    out = tmp_path / "status.csv"
    pool = [
        {
            "page_id": "7",
            "video_url": "https://www.youtube.com/embed/live_stream?channel=x",
        },
        {"page_id": "8", "video_url": ""},
    ]
    fetch = Fetch({})
    counts, _ = _check(pool, out, fetch)
    assert fetch.asked == [] and counts == {"malformed": 2}
    rows = _rows(out)
    assert [(r["page_id"], r["video_id"], r["status"]) for r in rows] == [
        ("7", "", "malformed"),
        ("8", "", "malformed"),
    ]
    # a re-run does not write them twice
    _check(pool, out, fetch)
    assert len(_rows(out)) == 2


def test_the_wait_doubles_after_a_miss_and_resets_after_an_ok(tmp_path):
    out = tmp_path / "status.csv"
    fetch = Fetch(
        {"aaaaaaaaaaa": 200, "bbbbbbbbbbb": 404, "ccccccccccc": 200, "ddddddddddd": 200}
    )
    _, sleeps = _check(
        _pool("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"),
        out,
        fetch,
        delay_seconds=150.0,
    )
    # No wait before the first request. Then 150 (after an ok), 300 (after
    # the 404), and back to 150 (after the ok that followed).
    assert sleeps == [150.0, 300.0, 150.0]


def test_it_stops_at_once_when_youtube_says_too_many_requests(tmp_path):
    out = tmp_path / "status.csv"
    fetch = Fetch({"aaaaaaaaaaa": 200, "bbbbbbbbbbb": 429, "ccccccccccc": 200})
    lines = []
    _check(
        _pool("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"),
        out,
        fetch,
        log=lines.append,
    )
    assert fetch.asked == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert any("too many requests" in line for line in lines)
    assert [r["status"] for r in _rows(out)] == ["ok", "unknown"]


def test_it_stops_after_three_unclear_answers_in_a_row(tmp_path):
    out = tmp_path / "status.csv"
    ids = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"]
    fetch = Fetch({})  # every request "fails": None
    _check(_pool(*ids), out, fetch)
    assert fetch.asked == ids[:3]


def test_limit_caps_the_requests_in_one_run(tmp_path):
    out = tmp_path / "status.csv"
    fetch = Fetch({"aaaaaaaaaaa": 200, "bbbbbbbbbbb": 200, "ccccccccccc": 200})
    _check(_pool("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"), out, fetch, limit=2)
    assert fetch.asked == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_it_refuses_to_run_without_the_drip_mac_flag(tmp_path, monkeypatch, capsys):
    def boom(_video_id):
        raise AssertionError("a request was made")

    monkeypatch.setattr(checker, "real_fetch", boom)
    code = checker.main([str(POOL), "--out", str(tmp_path / "s.csv")])
    assert code == 1 and "only the drip Mac may" in capsys.readouterr().err
    assert not (tmp_path / "s.csv").exists()


def test_it_refuses_a_pace_faster_than_the_drip(tmp_path, capsys):
    code = checker.main(
        [
            str(POOL),
            "--out",
            str(tmp_path / "s.csv"),
            "--i-am-on-the-drip-mac",
            "--delay-seconds",
            "5",
        ]
    )
    assert code == 1 and "drip pacing" in capsys.readouterr().err


def test_the_real_pool_reads_and_every_address_has_an_id():
    with open(POOL, newline="", encoding="utf-8") as fh:
        pool = list(csv.DictReader(fh))
    assert len(pool) == 101
    ids = [checker.extract_video_id(r["video_url"]) for r in pool]
    assert all(ids), "a pool page has no readable video id"
    assert len(set(ids)) == 101


def test_no_request_is_made_on_import():
    """The module must be inert until main() runs with the flag."""
    assert callable(checker.real_fetch)
    assert checker.OEMBED_URL.startswith("https://www.youtube.com/oembed")
