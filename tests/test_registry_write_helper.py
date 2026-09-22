"""Tests for `scripts/registry_write_helper.py` (WO-940) -- the shared
read-modify-write helper for a locked, git-tracked CSV registry file.

Every test here is SYNTHETIC by design: this module is pure and
repo-agnostic (it takes a file PATH, not an assumption about which
registry), so it is exercised only against local fixture CSVs built in
`tmp_path`, never against a real registry -- the real ones
(`jurisdiction_coverage.csv`, `hub_slug_aliases.csv`) live outside this
test's reach on purpose (`hub_slug_aliases.csv` is the one exception,
inside this repo, and it has its own tests in
`tests/test_score_gov_registry_hub_aliases.py`, run against a fixture
too -- see that file's own docstring for why).

The fixture CSV's COLUMN NAMES below are not invented: they are the real
`jurisdiction_coverage.csv` header, confirmed from this repo's own
`scripts/wo357_apply_to_jc.py` and `scripts/wo360_apply_to_jc.py` (both
read/write that exact file in production) -- `gov_id`, `city_name`,
`state_or_province`, `domain`, `alternate_domains`, `reject_reason`,
`transcribed`. Only the ROW VALUES are made up for these tests.
"""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path

import pytest

from scripts import registry_write_helper as rwh

FIELDNAMES = [
    "gov_id",
    "city_name",
    "state_or_province",
    "domain",
    "alternate_domains",
    "reject_reason",
    "transcribed",
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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


# --- basic read-modify-write -------------------------------------------


def test_mutate_fn_edit_is_written_atomically_with_lf_endings(tmp_path):
    path = tmp_path / "registry.csv"
    _write_csv(path, _sample_rows(5))

    def mutate(rows):
        for row in rows:
            if row["gov_id"] == "us:place:1002":
                row["reject_reason"] = "no-video-found"
                return True
        return False

    result = rwh.read_modify_write(path, mutate)
    assert result.changed is True
    assert result.row_count == 5

    rows = _read_csv(path)
    assert rows[2]["reject_reason"] == "no-video-found"
    # Every other row is untouched -- an in-place, line-based edit, not a
    # rebuild.
    assert rows[0]["reject_reason"] == ""

    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")

    # No leftover temp file.
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_mutate_fn_returning_false_writes_nothing(tmp_path):
    path = tmp_path / "registry.csv"
    _write_csv(path, _sample_rows(3))
    before = path.read_text(encoding="utf-8")
    before_mtime = path.stat().st_mtime_ns

    result = rwh.read_modify_write(path, lambda rows: False)
    assert result.changed is False
    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime_ns == before_mtime


def test_missing_file_raises_file_not_found(tmp_path):
    path = tmp_path / "does_not_exist.csv"
    with pytest.raises(FileNotFoundError):
        rwh.read_modify_write(path, lambda rows: True)


# --- min_row_floor -------------------------------------------------------


def test_a_read_under_the_floor_is_refused_and_nothing_is_written(tmp_path):
    path = tmp_path / "registry.csv"
    _write_csv(path, _sample_rows(5))
    before = path.read_text(encoding="utf-8")

    mutate_calls = []

    def mutate(rows):
        mutate_calls.append(rows)
        return True

    with pytest.raises(rwh.TruncatedReadError):
        rwh.read_modify_write(path, mutate, min_row_floor=10)

    # mutate_fn must never even run -- the refusal happens before it.
    assert mutate_calls == []
    assert path.read_text(encoding="utf-8") == before


def test_a_read_at_or_above_the_floor_proceeds(tmp_path):
    path = tmp_path / "registry.csv"
    _write_csv(path, _sample_rows(10))

    result = rwh.read_modify_write(path, lambda rows: True, min_row_floor=10)
    assert result.changed is True
    assert result.row_count == 10


# --- expected_content_hash: the WO-150/WO-147 fix -----------------------


def test_stale_hash_catches_a_same_row_count_concurrent_write(tmp_path):
    """Synthetic reproduction of the real 2026-09-10 WO-150/WO-147
    collision (`BACKLOG.md`'s "§158's write protocol doesn't catch a
    same-row-count" entry, closed out by this WO).

    Shape of the real incident: two sessions both read the same starting
    content. Session A (standing in for WO-150) writes and its write
    lands on disk. Session B (standing in for WO-147) had ALREADY read
    the file before Session A's write -- its own mutation plan was built
    against that earlier snapshot -- and only now gets around to writing.
    The OLD `*_apply_to_jc.py` protocol re-checked only row COUNT and
    header FIELDNAMES immediately before writing; neither changes here
    (both sessions only edit a `reject_reason` cell on an existing row),
    so that check would have passed and Session B's write would have
    silently reverted Session A's already-landed change -- exactly what
    happened for real to Florence city AL and Lake Havasu City AZ's rows.

    This helper's `expected_content_hash` closes it: Session B passes the
    hash of what it read *before* Session A's write, and this call must
    refuse -- via the CONTENT hash, not row count or fieldnames, which
    are identical before and after Session A's write.
    """
    path = tmp_path / "registry.csv"
    _write_csv(path, _sample_rows(5))

    # Both "sessions" read the same starting content, at the same time,
    # before either has written anything.
    starting_hash = rwh.hash_text(path.read_text(encoding="utf-8"))

    # Session A (WO-150): edits a different row than Session B, writes,
    # and its write lands on disk first.
    def mutate_session_a(rows):
        for row in rows:
            if row["gov_id"] == "us:place:1000":
                row["reject_reason"] = "session-a-wrote-this"
                return True
        return False

    result_a = rwh.read_modify_write(
        path, mutate_session_a, expected_content_hash=starting_hash
    )
    assert result_a.changed is True

    # Row count and header fieldnames are UNCHANGED by Session A's write
    # -- the exact precondition that let the real collision slip past
    # the old count/fieldname-only re-check.
    assert result_a.row_count == 5
    assert list(result_a.fieldnames) == FIELDNAMES

    # Session B (WO-147): its mutation plan was built against
    # `starting_hash`, captured BEFORE Session A wrote. It only reaches
    # this call now.
    session_b_ran = []

    def mutate_session_b(rows):
        session_b_ran.append(True)
        for row in rows:
            if row["gov_id"] == "us:place:1001":
                row["reject_reason"] = "session-b-wrote-this"
        return True

    with pytest.raises(rwh.StaleReadError):
        rwh.read_modify_write(
            path, mutate_session_b, expected_content_hash=starting_hash
        )

    # mutate_fn never ran -- the staleness check happens before it, so
    # Session B never got a chance to compute a write from stale data.
    assert session_b_ran == []

    # Session A's change is intact; nothing was reverted or clobbered.
    rows = _read_csv(path)
    by_gov_id = {r["gov_id"]: r for r in rows}
    assert by_gov_id["us:place:1000"]["reject_reason"] == "session-a-wrote-this"
    assert by_gov_id["us:place:1001"]["reject_reason"] == ""


def test_matching_expected_hash_proceeds_normally(tmp_path):
    path = tmp_path / "registry.csv"
    _write_csv(path, _sample_rows(3))
    current_hash = rwh.hash_text(path.read_text(encoding="utf-8"))

    result = rwh.read_modify_write(
        path, lambda rows: True, expected_content_hash=current_hash
    )
    assert result.changed is True


# --- atomicity / concurrency (synthetic, exercises the lock itself) -----


def test_two_threads_racing_the_same_file_never_lose_a_write(tmp_path):
    """Synthetic: two threads simulate two processes both trying to
    increment a counter cell at the same time. Each opens its OWN file
    descriptor on the same `.lock` sibling file -- `flock` locks apply to
    the open file description, not the process, so this genuinely
    exercises the mutual-exclusion the real multi-process case relies
    on. Without the lock (or with a broken one), a lost-update race would
    drop one of the two increments; with it, both must land."""
    import threading

    path = tmp_path / "registry.csv"
    _write_csv(path, _sample_rows(1))
    barrier = threading.Barrier(2)
    errors = []

    def bump(field_suffix):
        try:
            barrier.wait(timeout=5)

            def mutate(rows):
                rows[0]["alternate_domains"] = (
                    rows[0]["alternate_domains"] + field_suffix
                )
                return True

            rwh.read_modify_write(path, mutate)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=bump, args=("a",))
    t2 = threading.Thread(target=bump, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors
    final = _read_csv(path)[0]["alternate_domains"]
    # Both increments landed -- order between "a" and "b" is not
    # guaranteed (whichever thread wins the lock first), but neither can
    # be silently dropped.
    assert sorted(final) == sorted("ab")


# --- committed_row_count_floor -------------------------------------------


def _init_git_repo(root: Path) -> None:
    """Synthetic: a throwaway git repo built in tmp_path purely to
    exercise the `git show HEAD:<path>` invocation itself -- never a real
    repo, never rtr-business."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def test_committed_row_count_floor_reads_the_real_head_blob(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    research = repo / "research"
    research.mkdir()
    csv_path = research / "registry.csv"
    _write_csv(csv_path, _sample_rows(100))
    subprocess.run(["git", "add", "research/registry.csv"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed 100 rows"], cwd=repo, check=True)

    # 100 data rows + 1 header line = 101 committed lines.
    floor = rwh.committed_row_count_floor(csv_path, repo_root=repo, ratio=0.99)
    assert floor == int(101 * 0.99)
    assert floor == 99


def test_committed_row_count_floor_autodetects_repo_root(tmp_path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    _init_git_repo(repo)
    csv_path = repo / "registry.csv"
    _write_csv(csv_path, _sample_rows(10))
    subprocess.run(["git", "add", "registry.csv"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)

    # No repo_root passed -- must walk up from the file to find .git.
    floor = rwh.committed_row_count_floor(csv_path, ratio=0.99)
    assert floor == int(11 * 0.99)


def test_committed_row_count_floor_falls_back_on_git_failure(tmp_path):
    # Not inside any git repo at all -- must never raise, must return the
    # caller's fallback.
    orphan = tmp_path / "no_repo_here" / "registry.csv"
    orphan.parent.mkdir()
    _write_csv(orphan, _sample_rows(3))

    floor = rwh.committed_row_count_floor(orphan, fallback=12345)
    assert floor == 12345


def test_committed_row_count_floor_falls_back_to_none_by_default(tmp_path):
    orphan = tmp_path / "no_repo_here2" / "registry.csv"
    orphan.parent.mkdir()
    _write_csv(orphan, _sample_rows(3))

    assert rwh.committed_row_count_floor(orphan) is None


def test_hash_text_is_deterministic_and_content_sensitive():
    a = rwh.hash_text("hello\nworld\n")
    b = rwh.hash_text("hello\nworld\n")
    c = rwh.hash_text("hello\nworld!\n")
    assert a == b
    assert a != c
