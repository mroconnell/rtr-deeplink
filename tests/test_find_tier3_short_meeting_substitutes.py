"""Tests for scripts/find_tier3_short_meeting_substitutes.py.

The load-bearing claim under test is the module docstring's discovery
that CivicClerk's `durationMin` field holds seconds despite its name --
proven here from the committed Emporia KS fixture pair (real API
response + real caption file for the same event), not from synthetic
data. The candidate-filtering tests are synthetic but reuse the real
fixture's field shapes (isDeleted/hasMedia/durationMin/startDateTime/
id), per CLAUDE.md's synthetic-test rule; what remains unconfirmed live
is only which OData filter dialect each CivicClerk tenant accepts, and
the script handles that with a client-side past-date re-filter either
way (see cc_list_past_events)."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import find_tier3_short_meeting_substitutes as f3s  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "civicclerk"


def _emporia_event() -> dict:
    return json.loads((FIXTURES / "emporiaks_event585.json").read_text())


def test_duration_min_is_seconds_confirmed_by_real_caption_file():
    # The one real datapoint behind the whole cheap-classification path:
    # the API's durationMin and the same event's committed caption file
    # must agree to within a caption cue's slack.
    event = _emporia_event()
    api_seconds = f3s.cc_duration_seconds(event)
    assert api_seconds == 16821.0

    tail = f3s.srt_tail_seconds((FIXTURES / "emporiaks_585_captions.srt").read_text())
    assert tail is not None
    assert abs(tail - api_seconds) < 2.0


def test_unpopulated_duration_min_is_none_not_zero():
    # clovisca event 20 has real media but durationMin=0 -- 0 must read
    # as "unknown, fall back to ffprobe", never as a zero-length meeting.
    event = json.loads((FIXTURES / "clovisca_event20.json").read_text())
    assert f3s.cc_duration_seconds(event) is None
    assert f3s.cc_media_path(event) == (
        "https://cpmedia.azureedge.net/clovisca/f32a4ab02f.mp4"
    )


def test_relative_media_path_is_not_probeable():
    # Live finding (losaltoshillsca event 4354, 2026-08-28): some tenants'
    # event-level media fields hold a relative "stream/TENANT/{file}.mp4"
    # path; only EventsMedia's videoUrl is absolute. A relative value must
    # read as "fall back to EventsMedia", never be handed to ffprobe.
    event = dict(_emporia_event())
    event["mediaStreamPath"] = "stream/LOSALTOSHILLSCA/1b3aa745.mp4"
    event["mediaSourcePathMp4"] = "stream/LOSALTOSHILLSCA/1b3aa745.mp4"
    event["externalMediaUrl"] = ""
    assert f3s.cc_media_path(event) is None


def test_short_window_bounds():
    # 9-40 min since round 2 (2026-09-11), matching WO-170's pick rule
    assert not f3s.in_short_window(539)
    assert f3s.in_short_window(540)
    assert f3s.in_short_window(2400)
    assert not f3s.in_short_window(2401)


def test_classify_duration():
    assert f3s.classify_duration(None) == "probe_failed"
    assert f3s.classify_duration(90 * 60) == "not_long"
    assert f3s.classify_duration(90 * 60 + 1) == "long"


def test_cc_past_candidates_filters_and_orders():
    # Synthetic listing reusing the real Events field shapes (see module
    # docstring). Facts are real-shaped: ids/dates only.
    base = _emporia_event()

    def event(id_, start, *, deleted=False, has_media=True):
        e = dict(base)
        e.update(
            {
                "id": id_,
                "startDateTime": start,
                "isDeleted": deleted,
                "hasMedia": has_media,
            }
        )
        if not has_media:
            e.update(
                {
                    "mediaStreamPath": "",
                    "mediaSourcePathMp4": "",
                    "externalMediaUrl": "",
                }
            )
        return e

    now_iso = "2026-08-28T00:00:00Z"
    events = [
        event(1, "2026-08-01T18:00:00Z"),
        event(2, "2026-08-15T18:00:00Z"),
        event(3, "2026-09-15T18:00:00Z"),  # future: scheduled, no video yet
        event(4, "2026-08-20T18:00:00Z", deleted=True),
        event(5, "2026-08-21T18:00:00Z", has_media=False),
        event(6, "2026-08-10T18:00:00Z"),  # already queued (excluded below)
    ]
    picked = f3s.cc_past_candidates(events, exclude_ids={"6"}, now_iso=now_iso)
    assert [e["id"] for e in picked] == [2, 1]  # newest first, others filtered


def test_cc_url_helpers():
    url = "https://losaltoshillsca.portal.civicclerk.com/event/4354/media"
    assert f3s.cc_event_id(url) == "4354"
    assert f3s.tenant_of(url) == "losaltoshillsca.portal.civicclerk.com"
    assert (
        f3s.cc_api_base("losaltoshillsca.portal.civicclerk.com")
        == "https://losaltoshillsca.api.civicclerk.com/v1"
    )
    assert (
        f3s.cc_portal_url("losaltoshillsca.portal.civicclerk.com", 99)
        == "https://losaltoshillsca.portal.civicclerk.com/event/99/media"
    )


def test_legistar_url_helpers():
    # A real queue row's shape (a2gov, tier3_auto_transcription_queue.txt).
    url = (
        "https://a2gov.legistar.com/MeetingDetail.aspx?ID=1251581"
        "&GUID=3959006D-C1DA-4BED-A747-C43A0384D9D4&Options=info%7C&Search="
    )
    assert f3s.legistar_url_id(url) == "1251581"
    assert f3s.legistar_client("a2gov.legistar.com") == "a2gov"


def test_srt_tail_handles_missing_cues():
    assert f3s.srt_tail_seconds("no cues here") is None
    text = "1\n00:00:01,000 --> 00:00:04,500\nhi\n\n2\n00:10:00,000 --> 00:12:30,250\nbye\n"
    assert f3s.srt_tail_seconds(text) == 750.25


def test_hms():
    assert f3s.hms(16821) == "4:40:21"
    assert f3s.hms(750.25) == "12:30"


# --- round 2 (2026-09-11) --------------------------------------------------


def test_pick_substitute_window_then_shortest_then_none():
    cands = [("a", 100 * 60), ("b", 30 * 60), ("c", 12 * 60)]
    assert f3s.pick_substitute(cands, 180 * 60) == (
        "b",
        "window",
    )  # first in window, listing order
    cands = [("a", 100 * 60), ("b", 60 * 60), ("c", 3 * 60)]
    assert f3s.pick_substitute(cands, 180 * 60) == (
        "b",
        "shortest",
    )  # 3 min is under the floor
    assert f3s.pick_substitute([("a", 200 * 60)], 180 * 60) == (
        None,
        "none",
    )  # not shorter
    assert f3s.pick_substitute([], 180 * 60) == (None, "none")


def test_looks_on_mission_rule():
    assert f3s.looks_on_mission(
        "Canal Days Media Launch", "granicus"
    )  # meetings-only listing
    assert f3s.looks_on_mission("Fiscal Court Meeting", "swagit")
    assert not f3s.looks_on_mission("Canal Days Media Launch", "swagit")
    assert not f3s.looks_on_mission(None, "cablecast")


def test_duration_from_row_prefers_measured_then_size_proxy():
    rate = {"civicclerk": 20.0}
    assert f3s.duration_from_row(
        {"duration_seconds": "1200", "size_bytes": "9", "probe_method": "ffprobe"},
        "civicclerk",
        rate,
    ) == (1200.0, "ffprobe")
    secs, src = f3s.duration_from_row(
        {"duration_seconds": "", "size_bytes": str(400 * 1e6)}, "civicclerk", rate
    )
    assert src == "size_proxy" and abs(secs - 1200) < 1
    assert f3s.duration_from_row(
        {"duration_seconds": "", "size_bytes": "5000000"}, "unknownplat", rate
    ) == (None, "")
    assert f3s.duration_from_row(None, "civicclerk", rate) == (None, "")


def test_calibrate_mb_per_min_needs_three_rows_else_default():
    sidecar = {
        f"u{i}": {
            "platform": "swagit",
            "size_bytes": str(600 * 1e6),
            "duration_seconds": "3600",
        }
        for i in range(3)
    }
    sidecar["w"] = {
        "platform": "wistia",
        "size_bytes": str(600 * 1e6),
        "duration_seconds": "3600",
    }
    out = f3s.calibrate_mb_per_min(sidecar)
    assert abs(out["swagit"] - 10.0) < 0.01
    assert out["wistia"] == f3s.MB_PER_MIN_DEFAULTS["wistia"]  # one row is not enough
    assert out["civicclerk"] == f3s.MB_PER_MIN_DEFAULTS["civicclerk"]


def test_queue_lines_parse_tab_source_field(tmp_path, monkeypatch):
    q = tmp_path / "q.txt"
    q.write_text(
        "# c\nhttps://a.granicus.com/MediaPlayer.php?view_id=2&clip_id=9\thttps://gov.example/p\nhttps://b.swagit.com/videos/1\n"
    )
    monkeypatch.setattr(f3s, "QUEUE_FILE", q)
    lines = f3s.queue_lines()
    assert (
        lines[0][1] == "https://a.granicus.com/MediaPlayer.php?view_id=2&clip_id=9"
        and lines[0][2] == "https://gov.example/p"
    )
    assert lines[1][2] is None
    assert f3s.queue_urls() == [lines[0][1], lines[1][1]]


def test_cmd_apply_swaps_found_lines_and_defers_originals(
    tmp_path, monkeypatch, capsys
):
    q = tmp_path / "queue.txt"
    q.write_text(
        "https://x.granicus.com/MediaPlayer.php?view_id=1&clip_id=5\thttps://x.gov/m\n"
        "https://y.granicus.com/player/clip/7\n"
        "https://www.youtube.com/watch?v=aaaaaaaaaaa\n"
    )
    sidecar = tmp_path / "probe.csv"
    sidecar.write_text(
        "url,platform,probe_method,duration_seconds,date,size_bytes,over_nine_minutes,verdict,reason,probe_seconds,probed_at\n"
        "https://x.granicus.com/MediaPlayer.php?view_id=1&clip_id=5,granicus,hls,12000,2026-01-01,,1,flag-long,,1,t\n"
        "https://y.granicus.com/player/clip/7,granicus,hls,9000,2026-01-01,,1,flag-long,,1,t\n"
    )
    search = tmp_path / "search.csv"
    search.write_text(
        ",".join(f3s.SEARCH_FIELDS)
        + "\n"
        + 'x.granicus.com,granicus,City Council 2026-01-05,"Xville, CA",us:place:0000001,found,https://x.granicus.com/player/clip/99,Council,2026-08-01,1500,0:25:00,hls,2,\n'
        + "y.granicus.com,granicus,,,,none,,,,,,,3,nothing usable\n"
    )
    deferred = tmp_path / "deferred.txt"
    monkeypatch.setattr(f3s, "QUEUE_FILE", q)
    monkeypatch.setattr(f3s, "PROBE_SIDECAR", sidecar)
    monkeypatch.setattr(f3s, "SEARCH_CSV", search)
    monkeypatch.setattr(f3s, "DEFERRED_FILE", deferred)
    monkeypatch.setattr(f3s, "DURATIONS_CSV", tmp_path / "missing.csv")
    monkeypatch.setattr(
        f3s,
        "load_probe_sidecar",
        lambda path=sidecar: (
            f3s.load_probe_sidecar.__wrapped__(path)
            if hasattr(f3s.load_probe_sidecar, "__wrapped__")
            else _load(path)
        ),
    )

    def _load(path):
        import csv as _csv

        with open(path, newline="") as f:
            return {r["url"]: r for r in _csv.DictReader(f)}

    monkeypatch.setattr(f3s, "load_probe_sidecar", lambda path=sidecar: _load(path))

    class A:
        apply = False

    f3s.cmd_apply(A())
    assert (
        q.read_text()
        .splitlines()[0]
        .startswith("https://x.granicus.com/MediaPlayer.php")
    )  # dry run: unchanged
    A.apply = True
    f3s.cmd_apply(A())
    lines = q.read_text().splitlines()
    assert (
        lines[0] == "https://x.granicus.com/player/clip/99\thttps://x.gov/m"
    )  # swapped, source kept
    assert lines[1] == "https://y.granicus.com/player/clip/7"  # no substitute: kept
    assert lines[2].startswith("https://www.youtube.com/")  # untouched
    parked = deferred.read_text().splitlines()[-1].split("\t")
    assert parked[0].endswith("clip_id=5") and parked[1] == "https://x.gov/m"
    assert (
        parked[2] == "us:place:0000001"
        and parked[3] == "Xville, CA"
        and parked[4] == "3:20:00"
    )
    assert "1 line(s) would be swapped" in capsys.readouterr().out


def test_cc_fallback_picks_shortest_usable_past_event(monkeypatch):
    import asyncio

    events = [
        {
            "id": 1,
            "isDeleted": False,
            "hasMedia": True,
            "durationMin": 200 * 60,
            "startDateTime": "2026-08-01T18:00:00Z",
            "eventName": "Council",
        },
        {
            "id": 2,
            "isDeleted": False,
            "hasMedia": True,
            "durationMin": 55 * 60,
            "startDateTime": "2026-07-01T18:00:00Z",
            "eventName": "Council",
        },
        {
            "id": 3,
            "isDeleted": False,
            "hasMedia": True,
            "durationMin": 4 * 60,
            "startDateTime": "2026-06-01T18:00:00Z",
            "eventName": "Stub",
        },
    ]

    async def none_found(*a, **k):
        return {"search_status": "none", "note": "no 9-40 min meeting"}

    async def listing(session, base):
        return events

    async def media(session, base, event):
        return None

    monkeypatch.setattr(f3s, "_cc_find_substitute", none_found)
    monkeypatch.setattr(f3s, "cc_list_past_events", listing)
    monkeypatch.setattr(f3s, "cc_probeable_video_url", media)
    result = asyncio.run(
        f3s._cc_find_substitute_with_fallback(
            None,
            "x.portal.civicclerk.com",
            set(),
            180 * 60,
            max_candidates=4,
            window=(540.0, 2400.0),
        )
    )
    assert result["search_status"] == "found_shortest"
    assert (
        result["substitute_url"].endswith("/event/2/media")
        or "2" in result["substitute_url"]
    )
    assert result["substitute_duration_seconds"] == "3300.0"


def test_body_phrase_and_same_body_preference():
    assert (
        f3s.body_phrase("Regular City Council Meeting - Aug 5, 2026") == "city council"
    )
    assert (
        f3s.body_phrase("Board of Supervisors on 2026-08-19") == "board of supervisors"
    )
    assert f3s.body_phrase("Canal Days Recap") is None
    listing = [
        ("a", "Planning Commission 9/9/26"),
        ("b", "City Council 8/25/26"),
        ("c", "City Council 8/4/26"),
    ]
    assert [
        u for u, _ in f3s.prefer_same_body(listing, "City Council Meeting 7/7/26")
    ] == ["b", "c", "a"]
    assert (
        f3s.prefer_same_body(listing, None) == listing
    )  # no original title: listing order kept


def test_row_writer_refuses_a_stale_header(tmp_path):
    import pytest as _pytest

    path = tmp_path / "s.csv"
    w = f3s._RowWriter(path, ["a", "b"])
    w.write({"a": 1, "b": 2})
    w.close()
    with _pytest.raises(RuntimeError, match="rebuild the sidecar"):
        f3s._RowWriter(path, ["a", "b", "c"])
    f3s._RowWriter(path, ["a", "b"]).close()  # same header: fine
