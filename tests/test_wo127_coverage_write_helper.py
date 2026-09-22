"""Tests for `scripts/wo127_civicplus_pipeline.py`'s
`_coverage_read_modify_write()` after WO-940 rewired it through the new
shared `scripts/registry_write_helper` module.

Real, confirmed gap this closes (BACKLOG.md's "jurisdiction_coverage.csv's
shared write helper still uses a" entry): this function -- imported and
reused by `wo174_pipeline.py` and `wo259_full_ladder_scan.py` -- refused
to write below a hardcoded `MIN_SANE_ROW_COUNT = 25000`, not the dynamic
99%-of-committed-HEAD floor this repo's protocol now asks for. It's now a
thin wrapper around `registry_write_helper.read_modify_write()`, with
`MIN_SANE_ROW_COUNT` surviving only as the fallback used if the git-based
floor computation itself fails.

These tests build a throwaway `jurisdiction_coverage.csv`-SHAPED fixture
(never the real one -- that lives in `~/Documents/rtr-business`, which
this repo's CLAUDE.md says never to touch from here) inside a real,
synthetic git repo in `tmp_path`, and monkeypatch the module's
`COVERAGE_CSV`/`COVERAGE_LOCK` to point at it. The column names below are
the real `jurisdiction_coverage.csv` header (see
`tests/test_registry_write_helper.py`'s docstring for where they're
confirmed from) -- only the row values are synthetic.

The external contract this wrapper must preserve exactly, since
`wo174_pipeline.py`/`wo259_full_ladder_scan.py` both call it directly:
`_coverage_read_modify_write(mutate_fn) -> bool`, NEVER raising, False
meaning "nothing was written" for any reason (missing file, truncated
read, or `mutate_fn` returning False).
"""

from __future__ import annotations

import csv
import importlib.util
import subprocess
from pathlib import Path

FIELDNAMES = [
    "gov_id",
    "city_name",
    "state_or_province",
    "domain",
    "alternate_domains",
    "reject_reason",
    "transcribed",
]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "wo127_civicplus_pipeline",
        Path(__file__).parent.parent / "scripts" / "wo127_civicplus_pipeline.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_rows(n: int) -> list[dict]:
    return [
        {
            "gov_id": f"us:place:{1000 + i}",
            "city_name": f"Synthetic City {i}",
            "state_or_province": "Synthetic State",
            "domain": f"synthetic{i}.example.gov",
            "alternate_domains": "",
            "reject_reason": "",
            "transcribed": "False",
        }
        for i in range(n)
    ]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _git_repo_with_committed_csv(tmp_path: Path, n_rows: int) -> Path:
    """Synthetic throwaway git repo, never rtr-business -- see this
    file's own docstring."""
    repo = tmp_path / "repo"
    (repo / "research").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    csv_path = repo / "research" / "jurisdiction_coverage.csv"
    _write_csv(csv_path, _sample_rows(n_rows))
    subprocess.run(
        ["git", "add", "research/jurisdiction_coverage.csv"], cwd=repo, check=True
    )
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return csv_path


def test_missing_file_returns_false_never_raises(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "COVERAGE_CSV", tmp_path / "does_not_exist.csv")
    monkeypatch.setattr(module, "COVERAGE_LOCK", tmp_path / "does_not_exist.csv.lock")

    assert module._coverage_read_modify_write(lambda rows: True) is False


def test_a_real_edit_is_applied_and_returns_true(tmp_path, monkeypatch):
    module = _load_module()
    csv_path = _git_repo_with_committed_csv(tmp_path, 30)
    monkeypatch.setattr(module, "COVERAGE_CSV", csv_path)
    monkeypatch.setattr(module, "COVERAGE_LOCK", csv_path.with_suffix(".csv.lock"))

    def mutate(rows):
        for row in rows:
            if row["gov_id"] == "us:place:1005":
                row["reject_reason"] = "no-video-found"
                return True
        return False

    assert module._coverage_read_modify_write(mutate) is True
    rows = _read_csv(csv_path)
    by_id = {r["gov_id"]: r for r in rows}
    assert by_id["us:place:1005"]["reject_reason"] == "no-video-found"


def test_mutate_fn_returning_false_writes_nothing(tmp_path, monkeypatch):
    module = _load_module()
    csv_path = _git_repo_with_committed_csv(tmp_path, 30)
    monkeypatch.setattr(module, "COVERAGE_CSV", csv_path)
    monkeypatch.setattr(module, "COVERAGE_LOCK", csv_path.with_suffix(".csv.lock"))
    before = csv_path.read_text(encoding="utf-8")

    assert module._coverage_read_modify_write(lambda rows: False) is False
    assert csv_path.read_text(encoding="utf-8") == before


def test_dynamic_floor_refuses_a_truncated_read_even_above_the_old_hardcoded_25000(
    tmp_path, monkeypatch
):
    """The exact gap the entry describes: the old hardcoded 25,000-row
    floor would happily accept a read of, say, 26,000 rows even if the
    real committed file has 40,000+ -- comfortably "not truncated" by the
    old rule but badly truncated by the new 99%-of-HEAD one. Uses small
    numbers for test speed, same ratio."""
    module = _load_module()
    csv_path = _git_repo_with_committed_csv(tmp_path, 100)  # committed: 100 rows
    monkeypatch.setattr(module, "COVERAGE_CSV", csv_path)
    monkeypatch.setattr(module, "COVERAGE_LOCK", csv_path.with_suffix(".csv.lock"))
    # Old hardcoded floor stand-in would be far below this; the dynamic
    # floor (99% of 100 -> 99) must still catch a working-tree read of
    # only 40 rows.
    assert module.MIN_SANE_ROW_COUNT == 25000  # unchanged -- never lowered
    _write_csv(csv_path, _sample_rows(40))

    mutate_calls = []

    def mutate(rows):
        mutate_calls.append(rows)
        return True

    assert module._coverage_read_modify_write(mutate) is False
    assert mutate_calls == []  # refused before mutate_fn ever ran
    # File left exactly as the truncated read found it.
    assert len(_read_csv(csv_path)) == 40


def test_git_failure_falls_back_to_the_unchanged_25000_floor(tmp_path, monkeypatch):
    """No git repo at all -- `committed_row_count_floor()` must fall back
    to `MIN_SANE_ROW_COUNT` (still 25000, never lowered), not silently
    skip the floor check the way `score_gov_registry.py`'s
    `hub_slug_aliases.csv` write is allowed to."""
    module = _load_module()
    csv_path = tmp_path / "no_git_here" / "jurisdiction_coverage.csv"
    csv_path.parent.mkdir()
    _write_csv(csv_path, _sample_rows(30))
    monkeypatch.setattr(module, "COVERAGE_CSV", csv_path)
    monkeypatch.setattr(module, "COVERAGE_LOCK", csv_path.with_suffix(".csv.lock"))

    # 30 rows is far under the 25000 fallback floor -- must be refused.
    assert module._coverage_read_modify_write(lambda rows: True) is False
    assert len(_read_csv(csv_path)) == 30
