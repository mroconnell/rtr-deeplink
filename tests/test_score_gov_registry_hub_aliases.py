"""Tests for `scripts/score_gov_registry.py`'s `_write_hub_slug_aliases()`
(WO-940).

Real, confirmed bug this closes: the function used to overwrite
`archive/data/hub_slug_aliases.csv` wholesale every run, deriving every
row fresh with no read-first. WO-109 (2026-09-03) found that a naive
overwrite would have dropped 615 of 672 real, currently-serving redirect
rows (BACKLOG.md's "scripts/score_gov_registry.py overwrites" entry).
This now reads the existing committed file first (through the new shared
`scripts/registry_write_helper`) and unions it with the freshly-derived
rows, existing-wins-unless-proven-stale, the same merge WO-109 did by
hand.

Every test here loads `score_gov_registry.py` as a fresh module via
`importlib` (same pattern `tests/test_gov_registry.py`'s
`test_a_telvue_org_token_is_extracted_as_the_match_value` already uses)
and monkeypatches its `REPO_ROOT` to a `tmp_path`, so `_write_hub_slug_
aliases()` reads and writes a throwaway `archive/data/hub_slug_
aliases.csv` fixture -- never the real, committed one. The row SHAPE
(`old_slug, gov_id, new_slug, evidence` / the `all_rows` input's
`old_hub_slug`, `new_hub_slug`, `gov_id`, `jurisdiction`, `gov_name`
keys) is the real shape, confirmed from `score_gov_registry.py`'s own
`score_rows()` (which sets exactly those keys) and the real committed
`archive/data/hub_slug_aliases.csv` header -- only the row VALUES here
are synthetic.
"""

from __future__ import annotations

import csv
import importlib.util
import subprocess
from pathlib import Path

HUB_ALIASES_FIELDNAMES = ["old_slug", "gov_id", "new_slug", "evidence"]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "score_gov_registry",
        Path(__file__).parent.parent / "scripts" / "score_gov_registry.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_repo_root(tmp_path: Path) -> Path:
    (tmp_path / "archive" / "data").mkdir(parents=True)
    return tmp_path


def _write_existing_aliases(repo_root: Path, rows: list[dict]) -> Path:
    path = repo_root / "archive" / "data" / "hub_slug_aliases.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=HUB_ALIASES_FIELDNAMES, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def _read_aliases(repo_root: Path) -> dict:
    path = repo_root / "archive" / "data" / "hub_slug_aliases.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return {row["old_slug"]: row for row in csv.DictReader(f)}


def _archive_row(*, old_hub_slug, new_hub_slug, gov_id, jurisdiction, gov_name) -> dict:
    return {
        "old_hub_slug": old_hub_slug,
        "new_hub_slug": new_hub_slug,
        "gov_id": gov_id,
        "jurisdiction": jurisdiction,
        "gov_name": gov_name,
    }


# --- bootstrap: no committed file yet ------------------------------------


def test_first_run_with_no_existing_file_writes_fresh_rows(tmp_path, monkeypatch):
    module = _load_module()
    repo_root = _setup_repo_root(tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    all_rows = [
        _archive_row(
            old_hub_slug="old-springfield",
            new_hub_slug="springfield-il",
            gov_id="us:place:1000",
            jurisdiction="City of Springfield",
            gov_name="Springfield, IL",
        )
    ]
    count = module._write_hub_slug_aliases(all_rows)
    assert count == 1

    rows = _read_aliases(repo_root)
    assert rows["old-springfield"]["new_slug"] == "springfield-il"
    assert rows["old-springfield"]["gov_id"] == "us:place:1000"


# --- the WO-109 case: a hand-added row must survive a regen -------------


def test_an_existing_row_absent_from_this_runs_fresh_candidates_is_kept(
    tmp_path, monkeypatch
):
    """This is the WO-109 finding, reproduced directly: a row whose
    (old_slug, new_slug) pair is only ever derivable on the FIRST run
    after the backfill that produced it (or a hand-added exception, like
    the real `gloucester-ma` -> `gloucester-county-va` row --
    `tests/test_hub_aliases.py`'s `test_gloucester_ma_redirects_to_the_
    county_hub`) must NOT disappear just because this run's fresh
    candidates don't happen to reproduce it."""
    module = _load_module()
    repo_root = _setup_repo_root(tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    _write_existing_aliases(
        repo_root,
        [
            {
                "old_slug": "gloucester-ma",
                "gov_id": "us:sd:5101620",
                "new_slug": "gloucester-county-va",
                "evidence": "hand-added exception, see BACKLOG_DONE.md",
            }
        ],
    )

    # This run's fresh candidates say nothing about gloucester-ma at all
    # (e.g. no archived page currently carries that raw jurisdiction
    # string) -- a wholesale overwrite would have silently dropped it.
    all_rows = [
        _archive_row(
            old_hub_slug="old-newtown",
            new_hub_slug="newtown-ct",
            gov_id="us:place:2000",
            jurisdiction="Town of Newtown",
            gov_name="Newtown, CT",
        )
    ]
    module._write_hub_slug_aliases(all_rows)

    rows = _read_aliases(repo_root)
    assert rows["gloucester-ma"]["new_slug"] == "gloucester-county-va"
    assert rows["old-newtown"]["new_slug"] == "newtown-ct"


# --- "proven stale": old_slug reclaimed by a real live hub ---------------


def test_an_existing_row_is_dropped_once_its_old_slug_becomes_live_again(
    tmp_path, monkeypatch
):
    module = _load_module()
    repo_root = _setup_repo_root(tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    _write_existing_aliases(
        repo_root,
        [
            {
                "old_slug": "riverside",
                "gov_id": "us:place:3000",
                "new_slug": "riverside-ca",
                "evidence": "stale, riverside is now its own live hub",
            }
        ],
    )

    # This run's own world has SOME government now legitimately hubbed
    # at the exact slug "riverside" -- the same rule that already keeps
    # a FRESH candidate from ever redirecting a live hub (`old in live`)
    # now also applies to a row already on disk.
    all_rows = [
        _archive_row(
            old_hub_slug="riverside",
            new_hub_slug="riverside",
            gov_id="us:place:3000",
            jurisdiction="City of Riverside",
            gov_name="Riverside, CA",
        )
    ]
    module._write_hub_slug_aliases(all_rows)

    rows = _read_aliases(repo_root)
    assert "riverside" not in rows


# --- collision: existing wins, never silently auto-flipped --------------


def test_a_differing_fresh_candidate_never_silently_overrides_the_incumbent(
    tmp_path, monkeypatch, capsys
):
    """The hamilton/victoria/woodland shape (BACKLOG_DONE.md's WO-109/
    WO-112 writeup): the SAME old_slug, from two different points in
    time, legitimately wants two different destinations. No general
    tie-break rule exists -- WO-112 only resolved 2 of 3 by Ryan's direct
    instruction. So the incumbent (already-committed) row must win by
    default, and the collision must be visible in the run's own output,
    not silently dropped."""
    module = _load_module()
    repo_root = _setup_repo_root(tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    _write_existing_aliases(
        repo_root,
        [
            {
                "old_slug": "hamilton",
                "gov_id": "us:place:9001",
                "new_slug": "hamilton-police-services-board-on",
                "evidence": "incumbent, kept safe per WO-109's cautious default",
            }
        ],
    )

    all_rows = [
        _archive_row(
            old_hub_slug="hamilton",
            new_hub_slug="hamilton-city-oh",
            gov_id="us:place:3933012",
            jurisdiction="City of Hamilton",
            gov_name="Hamilton, OH",
        )
    ]
    count = module._write_hub_slug_aliases(all_rows)

    rows = _read_aliases(repo_root)
    # Incumbent kept -- not silently overwritten by the differing fresh
    # candidate.
    assert rows["hamilton"]["new_slug"] == "hamilton-police-services-board-on"
    assert count == 1

    out = capsys.readouterr().out
    assert "hamilton" in out
    assert "collision" in out.lower()
    assert "hamilton-city-oh" in out  # the declined candidate is named


def test_an_identical_existing_and_fresh_row_is_not_reported_as_a_collision(
    tmp_path, monkeypatch, capsys
):
    module = _load_module()
    repo_root = _setup_repo_root(tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    _write_existing_aliases(
        repo_root,
        [
            {
                "old_slug": "old-topeka",
                "gov_id": "us:place:4000",
                "new_slug": "topeka-ks",
                "evidence": "already correct",
            }
        ],
    )
    all_rows = [
        _archive_row(
            old_hub_slug="old-topeka",
            new_hub_slug="topeka-ks",
            gov_id="us:place:4000",
            jurisdiction="City of Topeka",
            gov_name="Topeka, KS",
        )
    ]
    module._write_hub_slug_aliases(all_rows)

    out = capsys.readouterr().out
    assert "collision" not in out.lower()


# --- the dynamic row-count floor actually protects this file too --------


def test_a_truncated_read_refuses_to_write_when_a_committed_floor_exists(
    tmp_path, monkeypatch
):
    """Synthetic: builds a real throwaway git repo (never rtr-business)
    so `committed_row_count_floor()` has something real to compute
    against, then corrupts the on-disk file to far fewer rows than what
    was committed -- the write must be refused, same protection
    `jurisdiction_coverage.csv`'s callers already rely on."""
    module = _load_module()
    repo_root = _setup_repo_root(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)

    # Commit 50 real rows.
    committed_rows = [
        {
            "old_slug": f"old-slug-{i}",
            "gov_id": f"us:place:{5000 + i}",
            "new_slug": f"new-slug-{i}",
            "evidence": "seed",
        }
        for i in range(50)
    ]
    _write_existing_aliases(repo_root, committed_rows)
    subprocess.run(
        ["git", "add", "archive/data/hub_slug_aliases.csv"], cwd=repo_root, check=True
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed 50 rows"], cwd=repo_root, check=True
    )

    # Now corrupt the working copy to look truncated -- e.g. a bad read
    # mid-write elsewhere -- well under 99% of the committed 50.
    _write_existing_aliases(repo_root, committed_rows[:2])

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    all_rows = [
        _archive_row(
            old_hub_slug="old-slug-99",
            new_hub_slug="new-slug-99",
            gov_id="us:place:9999",
            jurisdiction="Doesn't matter",
            gov_name="Doesn't matter",
        )
    ]
    from scripts.registry_write_helper import TruncatedReadError

    try:
        module._write_hub_slug_aliases(all_rows)
        raised = False
    except TruncatedReadError:
        raised = True
    assert raised, (
        "expected a TruncatedReadError for a read far under the committed floor"
    )

    # The corrupted 2-row file must be untouched -- refused, not written over.
    rows = _read_aliases(repo_root)
    assert len(rows) == 2
