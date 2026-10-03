"""WO-1176: tier-3 queue lines carry title, date and meeting body; the feed
and the local Whisper script apply them; a line with its own gov_id is not
bounced as [NO-OWNER].

All SYNTHETIC (pure parsing/logic, no network). The URL shapes are real:
a Google Drive file link and `drive.usercontent.google.com` (the host a
Drive file actually downloads from, confirmed in app/platforms/
direct_file.py's own docstring). The gov_id/title/body values are made up;
what is not confirmed here is any real queue line carrying columns 4-6,
since none exists yet.
"""

import pytest

from app.platforms import queue_probe
from app.platforms.queue_probe import (
    QueueLine,
    append_queue_line,
    apply_queue_metadata,
    built_title,
    parse_queue_entry,
    parse_queue_line,
)
from app.utils.gov_registry.registry import MULTI_GOV_HOSTS
from tests.test_feed_tier3_auto_transcription import (
    _accepting_probe_stub,
    _FakeFinder,
    _FakeResolvedMeeting,
    _noop_append_probe_row,
)

DRIVE = "https://drive.google.com/file/d/1AbCdEfGhIjK/view"


# --- the shared parser ---------------------------------------------------


def test_parse_one_column():
    assert parse_queue_entry("https://x.example/a.mp4") == QueueLine(
        "https://x.example/a.mp4", None, None, None, None, None
    )


def test_parse_two_and_three_columns_unchanged():
    assert parse_queue_entry("u\ts") == QueueLine("u", "s")
    assert parse_queue_entry("u\ts\tus:place:1") == QueueLine("u", "s", "us:place:1")
    assert parse_queue_entry("u\t\tus:place:1") == QueueLine("u", None, "us:place:1")
    # the 3-tuple wrapper every old caller unpacks
    assert parse_queue_line("u\ts\tg\tT\t2026-01-02\tB") == ("u", "s", "g")


def test_parse_four_columns():
    assert parse_queue_entry("u\ts\tg\tBoard Packet") == QueueLine(
        "u", "s", "g", "Board Packet", None, None
    )


def test_parse_six_columns():
    line = "u\ts\tg\tRegular Meeting\t2026-09-23\tSchool Board"
    assert parse_queue_entry(line) == QueueLine(
        "u", "s", "g", "Regular Meeting", "2026-09-23", "School Board"
    )


def test_parse_blank_middle_columns():
    assert parse_queue_entry("u\t\t\t\t2026-09-23\tBoard") == QueueLine(
        "u", None, None, None, "2026-09-23", "Board"
    )


@pytest.mark.parametrize("bad", ["09/23/2026", "2026-13-40", "2026-9-3", "soon"])
def test_parse_bad_date_is_blank_not_an_error(bad, caplog):
    entry = parse_queue_entry(f"u\ts\tg\tT\t{bad}\tB")
    assert entry.date is None
    assert entry.title == "T" and entry.meeting_body == "B"
    assert "unparseable date" in caplog.text


# --- append_queue_line ---------------------------------------------------


def test_append_writes_metadata_and_it_round_trips(tmp_path):
    q = tmp_path / "queue.txt"
    assert append_queue_line(
        DRIVE,
        None,
        gov_id="us:place:1",
        title="Regular\tMeeting\n",
        date="2026-09-23",
        meeting_body="School Board",
        queue_path=q,
    )
    (line,) = q.read_text().splitlines()
    assert line.count("\t") == 5
    assert parse_queue_entry(line) == QueueLine(
        DRIVE, None, "us:place:1", "Regular Meeting", "2026-09-23", "School Board"
    )


def test_append_omits_trailing_empty_columns_and_drops_a_bad_date(tmp_path):
    q = tmp_path / "queue.txt"
    append_queue_line(DRIVE, None, gov_id="g", title="T", date="nope", queue_path=q)
    assert q.read_text() == f"{DRIVE}\t\tg\tT\n"


def test_append_without_metadata_keeps_the_old_shapes(tmp_path):
    q = tmp_path / "queue.txt"
    append_queue_line("https://a.example/1.mp4", queue_path=q)
    append_queue_line("https://a.example/2.mp4", "https://gov.example/p", queue_path=q)
    append_queue_line("https://a.example/3.mp4", None, gov_id="g", queue_path=q)
    assert q.read_text().splitlines() == [
        "https://a.example/1.mp4",
        "https://a.example/2.mp4\thttps://gov.example/p",
        "https://a.example/3.mp4\t\tg",
    ]


# --- built title and precedence -----------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ("School Board", "School Board meeting"),
        ("City Council Meeting", "City Council Meeting"),
        ("Planning Commission meetings", "Planning Commission meetings"),
        ("Special Session", "Special Session"),
        ("Public HEARING", "Public HEARING"),
        ("", None),
        (None, None),
    ],
)
def test_built_title_from_body_only_when_untitled(body, expected):
    assert built_title(None, None, body) == expected


def test_built_title_prefers_resolver_then_queue_title():
    assert built_title("Queue", "Resolver", "Board") == "Resolver"
    assert built_title("Queue", "  ", "Board") == "Queue"


def test_apply_queue_metadata_fills_blanks_and_keeps_resolver_values():
    blank = apply_queue_metadata(
        {"title": None, "date": "", "meeting_body": None},
        title="Q title",
        date="2026-09-23",
        meeting_body="School Board",
    )
    assert blank == {
        "title": "Q title",
        "date": "2026-09-23",
        "meeting_body": "School Board",
    }
    kept = apply_queue_metadata(
        {"title": "R", "date": "2025-01-01", "meeting_body": "R body"},
        title="Q title",
        date="2026-09-23",
        meeting_body="School Board",
    )
    assert kept == {"title": "R", "date": "2025-01-01", "meeting_body": "R body"}


def test_apply_queue_metadata_builds_a_title_from_the_body():
    out = apply_queue_metadata({}, meeting_body="School Board")
    assert out["title"] == "School Board meeting"
    assert "title" not in apply_queue_metadata({})


# --- the feed -------------------------------------------------------------


def _wire_feed(monkeypatch, result, platform="direct_file"):
    import scripts.feed_tier3_auto_transcription as mod

    monkeypatch.setattr(mod, "detect_platform", lambda url: platform)
    monkeypatch.setattr(mod, "get_finder", lambda p: _FakeFinder(result))
    monkeypatch.setattr(mod, "probe_queue_entry", _accepting_probe_stub)
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)
    captured = {}

    async def _fake_ingest(
        session, payload, input_url_normalized, *, already_probed=False, caller=""
    ):
        captured["payload"] = payload
        return {"url": "/m/x"}

    monkeypatch.setattr(mod, "_ingest", _fake_ingest)
    return mod, captured


class _BlankResult(_FakeResolvedMeeting):
    """A bare file link's resolver result: no title, date or body."""

    def model_dump(self):
        return {
            "video_url": self.video_url,
            "source_url": self.source_url,
            "title": None,
            "date": None,
            "meeting_body": None,
        }


async def test_feed_fills_blank_metadata_from_the_queue_line(monkeypatch):
    result = _BlankResult(video_url=DRIVE, source_url=DRIVE)
    mod, captured = _wire_feed(monkeypatch, result)
    outcome = await mod._push_if_has_video(
        None,
        DRIVE,
        None,
        "us:place:1",
        queue_title="Regular Meeting",
        queue_date="2026-09-23",
        queue_meeting_body="School Board",
    )
    assert outcome.startswith("[OK]")
    p = captured["payload"]
    assert (p["title"], p["date"], p["meeting_body"]) == (
        "Regular Meeting",
        "2026-09-23",
        "School Board",
    )
    assert p["gov_id"] == "us:place:1"


async def test_feed_builds_a_title_when_only_the_body_is_known(monkeypatch):
    result = _BlankResult(video_url=DRIVE, source_url=DRIVE)
    mod, captured = _wire_feed(monkeypatch, result)
    await mod._push_if_has_video(
        None, DRIVE, None, "us:place:1", queue_meeting_body="School Board"
    )
    assert captured["payload"]["title"] == "School Board meeting"


async def test_feed_keeps_the_resolvers_own_values(monkeypatch):
    class _Full(_FakeResolvedMeeting):
        def model_dump(self):
            return {
                "video_url": self.video_url,
                "source_url": self.source_url,
                "title": "Resolver title",
                "date": "2025-05-05",
                "meeting_body": "Resolver body",
            }

    result = _Full(video_url=DRIVE, source_url=DRIVE)
    mod, captured = _wire_feed(monkeypatch, result)
    await mod._push_if_has_video(
        None,
        DRIVE,
        None,
        "us:place:1",
        queue_title="Queue title",
        queue_date="2026-09-23",
        queue_meeting_body="Queue body",
    )
    p = captured["payload"]
    assert (p["title"], p["date"], p["meeting_body"]) == (
        "Resolver title",
        "2025-05-05",
        "Resolver body",
    )


async def test_feed_no_longer_bounces_a_shared_host_line_with_its_own_gov_id(
    monkeypatch,
):
    result = _BlankResult(video_url=DRIVE, source_url=DRIVE)
    mod, captured = _wire_feed(monkeypatch, result)
    outcome = await mod._push_if_has_video(None, DRIVE, None, "us:place:1")
    assert outcome.startswith("[OK]")
    assert captured["payload"]["gov_id"] == "us:place:1"


async def test_feed_still_bounces_a_shared_host_line_with_no_gov_id(monkeypatch):
    result = _BlankResult(video_url=DRIVE, source_url=DRIVE)
    mod, captured = _wire_feed(monkeypatch, result)
    outcome = await mod._push_if_has_video(None, DRIVE, None, None)
    assert outcome.startswith("[NO-OWNER]")
    assert "payload" not in captured


def test_drive_download_host_is_a_multi_government_host():
    assert "drive.usercontent.google.com" in MULTI_GOV_HOSTS
    assert "drive.google.com" in MULTI_GOV_HOSTS


# --- the local Whisper script's --urls-file -------------------------------


def test_urls_file_six_column_line_becomes_a_payload_with_gov_and_metadata():
    import scripts.transcribe_backlog_locally as mod

    line = f"{DRIVE}\thttps://school.example.gov/board\tus:place:1\t\t2026-09-23\tSchool Board"
    page = mod._page_from_queue_line(line)
    assert page["gov_id"] == "us:place:1"
    assert page["source_url_override"] == "https://school.example.gov/board"
    assert page["queue_date"] == "2026-09-23"
    assert page["queue_meeting_body"] == "School Board"

    result = {
        "platform": "direct_file",
        "external_id": None,
        "title": None,
        "date": None,
        "jurisdiction": None,
        "meeting_body": None,
        "video_url": "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjK",
        "video_format": "mp4",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}],
        "language": "en",
        "transcript_warnings": [],
    }
    payload = mod._ingest_payload_fields(page, result)
    assert payload["gov_id"] == "us:place:1"
    assert payload["source_url"] == "https://school.example.gov/board"
    assert payload["date"] == "2026-09-23"
    assert payload["meeting_body"] == "School Board"
    assert payload["title"] == "School Board meeting"  # built, no title anywhere


def test_urls_file_bare_url_line_still_works():
    import scripts.transcribe_backlog_locally as mod

    page = mod._page_from_queue_line("https://example.gov/recordings/a.mp4")
    assert page["gov_id"] is None and page["source_url_override"] is None
    payload = mod._ingest_payload_fields(
        page,
        {
            "platform": "direct_file",
            "title": "T",
            "video_url": "v",
            "video_format": "mp4",
            "segments": [],
            "language": "en",
            "transcript_warnings": [],
        },
    )
    assert "gov_id" not in payload
    assert payload["title"] == "T"


def test_urls_file_ignores_the_source_override_on_a_real_meeting_page():
    """Same rule as the feed's WO-1073: an override is for bare video links."""
    import scripts.transcribe_backlog_locally as mod

    page = mod._page_from_queue_line(
        "https://example.granicus.com/player/clip/9\thttps://other.example/p\tg"
    )
    assert page["source_url_override"] is None
    assert page["gov_id"] == "g"


async def test_process_one_sends_the_queue_line_fields(monkeypatch):
    """Mocks transcription and the network; checks the ingest body."""
    import scripts.transcribe_backlog_locally as mod

    async def fake_transcribe(engine, url, platform, **kw):
        return {
            "ok": True,
            "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}],
            "language": "en",
            "transcript_warnings": [],
            "video_url": "https://drive.usercontent.google.com/download?id=1",
            "video_format": "mp4",
            "platform": "direct_file",
            "external_id": None,
            "title": None,
            "date": None,
            "jurisdiction": None,
            "meeting_body": None,
        }

    sent = {}

    async def fake_ingest(session, body):
        sent["body"] = body
        return {"url": "/m/x", "version_id": None}

    monkeypatch.setattr(mod, "transcribe_meeting", fake_transcribe)
    monkeypatch.setattr(mod, "_ingest", fake_ingest)
    page = mod._page_from_queue_line(
        f"{DRIVE}\t\tus:place:1\tBoard Packet\t2026-09-23\t"
    )
    result = await mod.process_one(
        None, object(), page, dry_run=False, chunk_seconds_override=None
    )
    assert result["status"] == "ingested"
    body = sent["body"]
    assert body["gov_id"] == "us:place:1"
    assert body["title"] == "Board Packet"
    assert body["date"] == "2026-09-23"
    assert body["source"] == "transcribed"


def test_queue_probe_no_longer_carries_a_robots_guard():
    assert not hasattr(queue_probe, "media_disallowed_by_robots")


# --- slugs (new pages only; existing pages are never reslugged) ------------

ALAMEDA = "us:place:0600562"  # real, confirmed in tests/test_gov_id_zip_recovery.py


async def _ingest_from_queue_line(line: str, file_id: str) -> str:
    """The payload the feed builds for a bare Drive file: blank resolver
    fields, then the queue line applied BEFORE ingest, so the built title
    reaches the slug (not render time)."""
    from archive.db import crud

    entry = parse_queue_entry(line)
    url = f"https://drive.google.com/file/d/{file_id}/view"
    payload = {
        "platform": "direct_file",
        "source_url": url,
        "external_id": None,
        "title": None,
        "date": None,
        "meeting_body": None,
        "jurisdiction": None,
        "video_url": f"https://drive.usercontent.google.com/download?id={file_id}",
        "video_format": "mp4",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
        "gov_id": entry.gov_id,
    }
    apply_queue_metadata(
        payload, title=entry.title, date=entry.date, meeting_body=entry.meeting_body
    )
    result = await crud.ingest_resolution(payload, url)
    return result["slug"]


async def test_full_queue_line_makes_a_government_date_title_slug():
    line = f"https://drive.google.com/file/d/wo1176a/view\t\t{ALAMEDA}\t\t2026-09-23\tCity Council"
    slug = await _ingest_from_queue_line(line, "wo1176a")
    # <government>-<yyyy-mm-dd>-<title words>, title built from the body
    assert slug.startswith("alameda")
    assert "-2026-09-23-city-council-meeting" in slug
    assert not slug.startswith("meeting-")


async def test_gov_id_only_line_still_gets_a_government_slug():
    line = f"https://drive.google.com/file/d/wo1176b/view\t\t{ALAMEDA}"
    slug = await _ingest_from_queue_line(line, "wo1176b")
    assert slug.startswith("alameda")
    assert not slug.startswith("meeting-")


# --- find_tier3_short_meeting_substitutes: a swapped line keeps its government


def test_swap_keeps_gov_id_and_body_and_drops_title_and_date_for_a_new_video():
    line = (
        "https://a.example/old\thttps://gov.example/p\tg\tOld title\t2026-01-02\tBoard"
    )
    assert (
        queue_probe.swap_queue_line_url(line, "https://a.example/new")
        == "https://a.example/new\thttps://gov.example/p\tg\t\t\tBoard"
    )


def test_swap_keeps_everything_when_the_url_is_unchanged():
    line = "https://a.example/old\t\tg\tOld title\t2026-01-02\tBoard"
    assert queue_probe.swap_queue_line_url(line, "https://a.example/old") == line


def test_swap_of_a_plain_line_matches_the_old_shapes():
    assert queue_probe.swap_queue_line_url("u", "n") == "n"
    assert queue_probe.swap_queue_line_url("u\ts", "n") == "n\ts"
    assert queue_probe.swap_queue_line_url("u\ts\tg", "n") == "n\ts\tg"
