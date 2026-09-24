"""WO-1024: app/platforms/meeting_finder/verdict.py -- append-as-you-go
CSV + JSONL, and load_done() resume."""

import json

from app.platforms.meeting_finder.models import VerdictRow
from app.platforms.meeting_finder.verdict import append_verdict, load_done


def _row(url: str, **overrides) -> VerdictRow:
    fields = dict(
        run_id="testrun",
        input_url=url,
        entry_phase="resolve",
        path=[url],
        phase_reached="resolve",
        result_url=None,
        platform="civicclerk",
        tier=1,
        duration_seconds=None,
        outcome=None,
        identity_verdict="agrees",
        identity_expected_gov_id="us:place:0627000",
        identity_resolved_gov_id="us:place:0627000",
        identity_points_to=None,
        leads=[],
        hops=0,
        forks=0,
        fetches=1,
        note="",
        finished_at="2026-09-23T00:00:00Z",
    )
    fields.update(overrides)
    return VerdictRow(**fields)


def test_load_done_on_missing_file_is_empty(tmp_path):
    assert load_done(tmp_path / "does_not_exist.csv") == set()


def test_append_then_load_done_resumes(tmp_path):
    out = tmp_path / "verdicts.csv"
    append_verdict(out, _row("https://a.example/1"))
    append_verdict(out, _row("https://b.example/2"))

    done = load_done(out)
    assert done == {"https://a.example/1", "https://b.example/2"}

    # A third input is not in `done` yet -- a rerun would process it.
    assert "https://c.example/3" not in done


def test_jsonl_twin_carries_the_full_nested_row(tmp_path):
    out = tmp_path / "verdicts.csv"
    row = _row(
        "https://a.example/1",
        path=["https://a.example/1", "https://a.example/1/hop"],
        leads=[{"kind": "youtube", "url": "https://youtube.com/watch?v=x"}],
    )
    append_verdict(out, row)

    jsonl_path = out.with_suffix(out.suffix + ".jsonl")
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["path"] == ["https://a.example/1", "https://a.example/1/hop"]
    assert payload["leads"] == [
        {"kind": "youtube", "url": "https://youtube.com/watch?v=x"}
    ]


def test_csv_flattens_path_and_leads(tmp_path):
    out = tmp_path / "verdicts.csv"
    row = _row(
        "https://a.example/1",
        path=["https://a.example/1", "https://a.example/1/hop"],
        leads=[{"kind": "youtube", "url": "https://youtube.com/watch?v=x"}],
    )
    append_verdict(out, row)

    text = out.read_text(encoding="utf-8")
    assert "https://a.example/1 -> https://a.example/1/hop" in text
    assert ",1," in text  # leads_count column


def test_append_is_idempotent_free_and_flushes_each_row(tmp_path):
    """Two rows appended in sequence both land, in order, with a header
    written only once."""
    out = tmp_path / "verdicts.csv"
    append_verdict(out, _row("https://a.example/1"))
    append_verdict(out, _row("https://b.example/2"))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("run_id,")
    assert len(lines) == 3


def test_meeting_url_and_title_round_trip_through_csv_and_jsonl(tmp_path):
    """WO-1042: the real meeting/candidate page URL Resolve was called
    with, plus its title when known, both survive the flat CSV and the
    JSONL twin."""
    out = tmp_path / "verdicts.csv"
    row = _row(
        "https://granicus.example.gov/",
        meeting_url="https://granicus.example.gov/MediaPlayer.php?view_id=1&clip_id=42",
        meeting_title="City Council -- 2026-09-08",
    )
    append_verdict(out, row)

    csv_text = out.read_text(encoding="utf-8")
    assert "MediaPlayer.php?view_id=1&clip_id=42" in csv_text
    assert "City Council -- 2026-09-08" in csv_text

    jsonl_path = out.with_suffix(out.suffix + ".jsonl")
    payload = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    assert (
        payload["meeting_url"]
        == "https://granicus.example.gov/MediaPlayer.php?view_id=1&clip_id=42"
    )
    assert payload["meeting_title"] == "City Council -- 2026-09-08"


def test_meeting_url_and_title_default_to_blank(tmp_path):
    out = tmp_path / "verdicts.csv"
    append_verdict(out, _row("https://a.example/1"))
    csv_text = out.read_text(encoding="utf-8")
    header = csv_text.splitlines()[0].split(",")
    assert "meeting_url" in header
    assert "meeting_title" in header
