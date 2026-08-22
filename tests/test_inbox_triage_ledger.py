"""Tests for scripts/inbox_triage_ledger.py (WO-33) -- the repo-side
processed-message-ID ledger that replaced the daily triage Routine's
`rtr-claude-processed` Gmail label (no Gmail write scope, permanently:
see CLAUDE_INBOX_TRIAGE.md's "Open item").

These are pure-logic tests against a tmp_path ledger -- no Gmail calls,
no network. The message IDs below are synthetic (16-hex-ish strings in
Gmail's real shape) because the *format* is what's under test, not any
particular message; nothing here asserts anything about real mail. Per
CLAUDE.md's synthetic-test rule, what's genuinely unverified is only that
Gmail's message IDs never contain whitespace -- the parser's one
assumption about their shape.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import inbox_triage_ledger as ledger  # noqa: E402

TODAY = date(2026, 8, 21)


def _ledger(tmp_path):
    return tmp_path / "seen.txt"


def _run(command, tmp_path, stdin="", today=TODAY):
    class _Stdin:
        def read(self):
            return stdin

    argv = [command, "--ledger", str(_ledger(tmp_path)), "--today", today.isoformat()]
    return ledger.main(argv, stdin=_Stdin())


def test_record_then_filter_hides_known_ids(tmp_path, capsys):
    assert _run("record", tmp_path, "aaa111\nbbb222\n") == 0
    capsys.readouterr()

    assert _run("filter", tmp_path, "aaa111\nccc333\n") == 0
    out = capsys.readouterr().out.split()
    assert out == ["ccc333"]


def test_filter_on_missing_ledger_returns_everything(tmp_path, capsys):
    assert _run("filter", tmp_path, "aaa111\nbbb222\n") == 0
    assert capsys.readouterr().out.split() == ["aaa111", "bbb222"]
    assert not _ledger(tmp_path).exists()


def test_record_is_append_only_and_idempotent(tmp_path):
    _run("record", tmp_path, "aaa111\n")
    first = _ledger(tmp_path).read_text()
    _run("record", tmp_path, "aaa111\nbbb222\n")
    second = _ledger(tmp_path).read_text()

    # The whole point of the append-only format (CLAUDE.md's multi-session
    # hazard): an existing line is never rewritten, only new lines added.
    assert second.startswith(first)
    assert ledger.seen_ids(_ledger(tmp_path)) == {"aaa111", "bbb222"}
    assert second.count("aaa111") == 1


def test_record_defaults_to_today_but_accepts_a_message_date(tmp_path):
    _run("record", tmp_path, "aaa111\nbbb222\t2026-08-02\n2026-07-30 ccc333\n")
    entries = dict((i, d) for d, i in ledger.read_ledger(_ledger(tmp_path)))
    assert entries == {
        "aaa111": TODAY,
        "bbb222": date(2026, 8, 2),
        "ccc333": date(2026, 7, 30),
    }


def test_prune_drops_only_entries_past_window_plus_grace(tmp_path):
    # Window is 30d; grace is 7d, so the cutoff is 37 days back
    # (2026-07-15). An entry one day inside the cutoff must survive --
    # pruning at the window edge exactly is what would let a message come
    # back from `newer_than:30d` and get re-reviewed.
    _run(
        "record",
        tmp_path,
        "\n".join(
            [
                "old111 2026-07-14",  # past cutoff -> dropped
                "edge222 2026-07-15",  # exactly at cutoff -> kept
                "recent333 2026-08-20",
            ]
        ),
    )
    _run("prune", tmp_path)
    assert ledger.seen_ids(_ledger(tmp_path)) == {"edge222", "recent333"}


def test_prune_keeps_undated_hand_written_ids(tmp_path):
    _ledger(tmp_path).write_text("# comment\nhandwritten\n2026-01-01\told999\n")
    _run("prune", tmp_path)
    assert ledger.seen_ids(_ledger(tmp_path)) == {"handwritten"}


def test_prune_rewrite_preserves_the_explanatory_header(tmp_path):
    _run("record", tmp_path, "old111 2026-01-01\nkeep222\n")
    _run("prune", tmp_path)
    text = _ledger(tmp_path).read_text()
    assert text.startswith("# Processed-message-ID ledger")
    assert "old111" not in text


def test_prune_collapses_duplicate_ids_from_a_hand_edit(tmp_path):
    _ledger(tmp_path).write_text("2026-08-20\tdup111\n2026-08-21\tdup111\n")
    kept, dropped = ledger.prune(_ledger(tmp_path), today=TODAY)
    assert [i for _, i in kept] == ["dup111"]
    assert len(dropped) == 1


def test_a_date_in_the_id_column_is_rejected_not_stored(tmp_path):
    # Guards the one silent-corruption mode: a swapped column would write
    # an entry that can never match a real message ID again.
    assert _run("record", tmp_path, "2026-08-20\n") == 2
    assert not _ledger(tmp_path).exists()


def test_malformed_input_line_is_rejected(tmp_path):
    assert _run("record", tmp_path, "aaa111 not-a-date\n") == 2


def test_blank_and_comment_lines_are_ignored_in_input(tmp_path):
    _run("record", tmp_path, "\n# a note\n\naaa111\n")
    assert ledger.seen_ids(_ledger(tmp_path)) == {"aaa111"}


def test_stats_reports_window_and_cutoff(tmp_path, capsys):
    _run("record", tmp_path, "aaa111 2026-08-01\nbbb222 2026-08-20\n")
    capsys.readouterr()
    assert _run("stats", tmp_path) == 0
    out = capsys.readouterr().out
    assert "entries: 2" in out
    assert "oldest:  2026-08-01" in out
    assert "newest:  2026-08-20" in out
    assert "2026-07-15" in out  # 30d window + 7d grace, back from TODAY


def test_repo_ledger_file_exists_and_parses():
    # The real file must stay parseable -- the Routine appends to it
    # unattended, and a hand edit that breaks the format would make the
    # next run silently re-review everything.
    real = ledger.LEDGER_PATH
    assert real.exists(), f"{real} is missing -- the Routine expects it in-repo"
    ledger.read_ledger(real)


def test_ledger_is_excluded_from_render_build_filters():
    # Constraint 4 of WO-33: the Routine auto-merges its own commits with
    # no human in the loop, so a file it writes daily MUST NOT be able to
    # trigger a production redeploy. Every service that already excludes
    # CLAUDE_INBOX_TRIAGE.md must exclude the ledger too.
    render_yaml = (ledger.REPO_ROOT / "render.yaml").read_text()
    assert render_yaml.count("CLAUDE_INBOX_TRIAGE.md") == render_yaml.count(
        ledger.LEDGER_PATH.name
    )
    assert render_yaml.count(ledger.LEDGER_PATH.name) >= 3
