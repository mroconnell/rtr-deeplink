"""Tests for `scripts/backfill_video_channel.py` (WO-246).

The video ids and channel handles below are synthetic placeholders, not
real YouTube data -- unlike a jurisdiction-resolution test (see CLAUDE.md's
"Synthetic tests" convention), this script does no identity resolution of
its own: it joins a video id to a channel string from a CSV and writes it
verbatim. There is no geographic or identity fact here to get wrong, so a
fabricated 11-character id is exactly as good a test of the join/write/
skip mechanics as a real one, and doesn't risk anyone mistaking it for a
real channel pin later.
"""

import csv
import sys

from archive.db import crud
from scripts import backfill_video_channel


def _payload(**overrides) -> dict:
    payload = {
        "platform": "youtube",
        "source_url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "external_id": "youtube:aaaaaaaaaaa",
        "title": "Town Council Regular Meeting",
        "date": "2026-09-01",
        "jurisdiction": None,
        "video_url": "https://www.youtube.com/embed/aaaaaaaaaaa",
        "video_format": "youtube",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _seed(video_id: str, *, video_channel=None) -> str:
    payload = _payload(
        source_url=f"https://www.youtube.com/watch?v={video_id}",
        external_id=f"youtube:{video_id}",
        video_url=f"https://www.youtube.com/embed/{video_id}",
    )
    if video_channel is not None:
        payload["video_channel"] = video_channel
    result = await crud.ingest_resolution(payload, payload["source_url"])
    return result["slug"]


async def _get(slug: str) -> dict:
    return await crud.get_page_by_slug(slug)


def _write_map(tmp_path, rows, name="map.csv"):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["video_id", "channel", "channel_title"])
        writer.writeheader()
        writer.writerows(rows)
    return path


async def _run(monkeypatch, *, apply: bool, map_files, report_path=None):
    argv = ["backfill_video_channel.py"]
    for m in map_files:
        argv += ["--map-file", str(m)]
    if apply:
        argv.append("--apply")
    if report_path:
        argv += ["--report", str(report_path)]
    monkeypatch.setattr(sys, "argv", argv)
    await backfill_video_channel.main()


def test_load_channel_map_reads_both_shapes(tmp_path):
    plain = _write_map(
        tmp_path,
        [
            {
                "video_id": "aaaaaaaaaaa",
                "channel": "@TestTownA",
                "channel_title": "Town A",
            }
        ],
        name="plain.csv",
    )
    keyed = tmp_path / "keyed.csv"
    with open(keyed, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["video_key", "channel", "channel_title"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "video_key": "youtube:bbbbbbbbbbb",
                "channel": "@TestTownB",
                "channel_title": "Town B",
            }
        )
        # A Vimeo row in the same file must be ignored -- this script only
        # ever writes video_channel for YouTube pages.
        writer.writerow(
            {
                "video_key": "vimeo:123456",
                "channel": "someowner",
                "channel_title": "Someone",
            }
        )
        # A blank channel (oEmbed reachable, no channel found) must be
        # skipped, not stored as an empty string.
        writer.writerow(
            {"video_key": "youtube:ccccccccccc", "channel": "", "channel_title": ""}
        )

    mapping = backfill_video_channel.load_channel_map([plain, keyed])
    assert mapping == {
        "aaaaaaaaaaa": ("@TestTownA", "Town A"),
        "bbbbbbbbbbb": ("@TestTownB", "Town B"),
    }


def test_earlier_map_file_wins_a_conflict(tmp_path):
    first = _write_map(
        tmp_path,
        [{"video_id": "aaaaaaaaaaa", "channel": "@FirstWins", "channel_title": ""}],
        name="first.csv",
    )
    second = _write_map(
        tmp_path,
        [{"video_id": "aaaaaaaaaaa", "channel": "@SecondLoses", "channel_title": ""}],
        name="second.csv",
    )
    mapping = backfill_video_channel.load_channel_map([first, second])
    assert mapping["aaaaaaaaaaa"] == ("@FirstWins", None)


async def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    slug = await _seed("ddddddddddd")
    map_file = _write_map(
        tmp_path,
        [{"video_id": "ddddddddddd", "channel": "@DryRunTown", "channel_title": ""}],
    )
    await _run(monkeypatch, apply=False, map_files=[map_file])
    page = await _get(slug)
    assert page["video_channel"] is None


async def test_apply_sets_video_channel_for_a_matched_video_id(tmp_path, monkeypatch):
    slug = await _seed("eeeeeeeeeee")
    map_file = _write_map(
        tmp_path,
        [
            {
                "video_id": "eeeeeeeeeee",
                "channel": "@ApplyTown",
                "channel_title": "Apply Town",
            }
        ],
    )
    await _run(monkeypatch, apply=True, map_files=[map_file])
    page = await _get(slug)
    assert page["video_channel"] == "@ApplyTown"


async def test_a_page_already_carrying_a_channel_is_left_alone(tmp_path, monkeypatch):
    """A page ingested by the fixed adapter (or a previous run of this
    script) already has a real channel -- the static map must never
    overwrite it, even if the map disagrees."""
    slug = await _seed("fffffffffff", video_channel="@AlreadySet")
    map_file = _write_map(
        tmp_path,
        [
            {
                "video_id": "fffffffffff",
                "channel": "@WouldOverwrite",
                "channel_title": "",
            }
        ],
    )
    await _run(monkeypatch, apply=True, map_files=[map_file])
    page = await _get(slug)
    assert page["video_channel"] == "@AlreadySet"


async def test_a_video_id_missing_from_the_map_is_left_null(tmp_path, monkeypatch):
    slug = await _seed("ggggggggggg")
    map_file = _write_map(tmp_path, [])
    await _run(monkeypatch, apply=True, map_files=[map_file])
    page = await _get(slug)
    assert page["video_channel"] is None


async def test_report_csv_lists_the_change(tmp_path, monkeypatch):
    slug = await _seed("hhhhhhhhhhh")
    map_file = _write_map(
        tmp_path,
        [
            {
                "video_id": "hhhhhhhhhhh",
                "channel": "@ReportTown",
                "channel_title": "Report Town",
            }
        ],
    )
    report_path = tmp_path / "report.csv"
    await _run(monkeypatch, apply=True, map_files=[map_file], report_path=report_path)
    rows = list(csv.DictReader(open(report_path)))
    matching = [r for r in rows if r["slug"] == slug]
    assert len(matching) == 1
    assert matching[0]["channel"] == "@ReportTown"
    assert matching[0]["video_id"] == "hhhhhhhhhhh"


async def test_a_re_run_only_touches_rows_still_null(tmp_path, monkeypatch):
    """The idempotence property the docstring promises: --apply twice in
    a row with the same map changes nothing the second time."""
    slug = await _seed("iiiiiiiiiii")
    map_file = _write_map(
        tmp_path,
        [{"video_id": "iiiiiiiiiii", "channel": "@ResumeTown", "channel_title": ""}],
    )
    await _run(monkeypatch, apply=True, map_files=[map_file])
    page = await _get(slug)
    assert page["video_channel"] == "@ResumeTown"

    # Second run: the row no longer matches video_channel.is_(None), so
    # it's excluded from the query entirely -- confirm nothing changes
    # even if the map now disagrees.
    map_file2 = _write_map(
        tmp_path,
        [
            {
                "video_id": "iiiiiiiiiii",
                "channel": "@ShouldNotApply",
                "channel_title": "",
            }
        ],
        name="map2.csv",
    )
    await _run(monkeypatch, apply=True, map_files=[map_file2])
    page = await _get(slug)
    assert page["video_channel"] == "@ResumeTown"
