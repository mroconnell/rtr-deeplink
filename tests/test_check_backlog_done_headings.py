"""Tests for scripts/check_backlog_done_headings.py.

WO-236 (2026-09-11): BACKLOG_DONE.md is append-only by convention -- once
an entry is written, it never leaves (see CLAUDE.md). Two hand-resolved
rebase conflicts silently dropped 22 already-recorded headings before
this check existed; see BACKLOG_DONE.md's own WO-236 entry. These tests
use small, hand-built fixture files (never the real BACKLOG.md/
BACKLOG_DONE.md) so they stay fast and independent of whatever either
file currently contains.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_backlog_done_headings import (  # noqa: E402
    backlog_entry_titles,
    done_headings,
    git_show,
    main,
    missing_items,
    resolve_merge_base,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "backlog_done_headings"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- missing_items (the core existence-comparison primitive) --------------


def test_missing_items_is_order_preserving_and_dedupes():
    base = ["## A", "## B", "## A", "## C"]
    working = ["## B"]
    # "## A" is missing twice in base but should only be reported once --
    # this is an existence check, not a count check (see the module
    # docstring for why: a heading legitimately duplicated by an earlier
    # bad merge and correctly collapsed back to one copy must not trip
    # this check).
    assert missing_items(base, working) == ["## A", "## C"]


def test_missing_items_empty_when_nothing_lost():
    base = ["## A", "## B"]
    working = ["## B", "## A", "## Z"]  # order and extras don't matter
    assert missing_items(base, working) == []


# --- done_headings / backlog_entry_titles parsing --------------------------


def test_done_headings_extracts_only_top_level_headings():
    text = _read("base_done.md")
    headings = done_headings(text)
    assert headings == [
        "## WO-901: fixed the widget [Done 2026-01-01]",
        "## WO-900: fixed the gadget [Done 2025-12-31]",
        "## WO-899: fixed the doohickey [Done 2025-12-30]",
    ]


def test_backlog_entry_titles_reads_tagged_bullets_and_headings():
    titles = backlog_entry_titles(_read("base_backlog.md"))
    assert "[JUST-DO-IT] Some tagged bullet that will be silently dropped" in titles
    assert "WO-900: fixed the gadget [Done 2025-12-31]" in titles


# --- the actual regression cases this script exists for --------------------


def test_a_heading_dropped_to_zero_copies_is_missing():
    """The real damage shape: a heading present in the base entirely
    absent from the working tree (what b88eee4/9bb73d1 actually did to
    22 headings)."""
    base = done_headings(_read("base_done.md"))
    working = done_headings(_read("working_done_missing.md"))
    missing = missing_items(base, working)
    assert missing == ["## WO-900: fixed the gadget [Done 2025-12-31]"]


def test_a_heading_whose_body_grows_is_not_flagged():
    """An entry legitimately getting a 'confirmed live in production'
    postscript added after the fact must never look like a loss -- only
    the heading LINE is compared, not the body underneath it."""
    base = done_headings(_read("base_done.md"))
    working = done_headings(_read("working_done_clean.md"))
    assert missing_items(base, working) == []


def test_a_duplicated_heading_collapsed_to_one_copy_is_not_flagged():
    """The specific false-positive this script deliberately avoids (see
    the module docstring): BACKLOG_DONE.md really did once have a whole
    block of headings duplicated by an earlier bad merge, and a later
    rebase correctly collapsed each one back down to a single surviving
    copy. That is a fix, not a loss, and a count-based (multiset)
    comparison would have flagged the very PR that did it -- this is
    exactly why the check is existence-based, not count-based."""
    base = done_headings(_read("base_done_duplicated.md"))  # WO-900 appears twice
    working = done_headings(_read("working_done_clean.md"))  # WO-900 appears once
    assert missing_items(base, working) == []


def test_backlog_open_entry_missing_but_promoted_to_done_is_not_a_warning_case():
    """An open BACKLOG.md entry that disappears because the work finished
    and got a BACKLOG_DONE.md entry (the normal, healthy path) must be
    distinguishable from one that was simply dropped -- main() does this
    by checking the missing title against the working tree's DONE
    headings, which callers of backlog_entry_titles/missing_items need to
    do themselves; this test documents the exact titles main() relies on
    lining up for that cross-check to work."""
    base_titles = backlog_entry_titles(_read("base_backlog.md"))
    working_titles = backlog_entry_titles(_read("working_backlog.md"))
    missing_open = missing_items(base_titles, working_titles)
    assert "WO-900: fixed the gadget [Done 2025-12-31]" in missing_open
    assert (
        "[JUST-DO-IT] Some tagged bullet that will be silently dropped" in missing_open
    )

    working_done_heading_text = {
        h[len("## ") :] for h in done_headings(_read("working_done_clean.md"))
    }
    # The promoted one now has a matching DONE heading; the dropped one doesn't.
    assert "WO-900: fixed the gadget [Done 2025-12-31]" in working_done_heading_text
    assert (
        "[JUST-DO-IT] Some tagged bullet that will be silently dropped"
        not in working_done_heading_text
    )


# --- end-to-end via main(), against a real (temporary) git repo -----------


def _git(repo: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    return repo


def test_main_exits_nonzero_and_lists_missing_heading(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    (repo / "BACKLOG_DONE.md").write_text(_read("base_done.md"), encoding="utf-8")
    (repo / "BACKLOG.md").write_text(_read("base_backlog.md"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    # Simulate a bad rebase: drop WO-900's heading from BACKLOG_DONE.md.
    (repo / "BACKLOG_DONE.md").write_text(
        _read("working_done_missing.md"), encoding="utf-8"
    )

    old_argv = sys.argv
    try:
        sys.argv = [
            "check_backlog_done_headings.py",
            "--base-ref",
            "HEAD",
            "--repo-root",
            str(repo),
        ]
        exit_code = main()
    finally:
        sys.argv = old_argv

    out = capsys.readouterr()
    assert exit_code == 1
    assert "WO-900: fixed the gadget" in out.err


def test_main_exits_zero_when_nothing_lost(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    (repo / "BACKLOG_DONE.md").write_text(_read("base_done.md"), encoding="utf-8")
    (repo / "BACKLOG.md").write_text(_read("base_backlog.md"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    # Body grows, heading stays -- must not trip the check.
    (repo / "BACKLOG_DONE.md").write_text(
        _read("working_done_clean.md"), encoding="utf-8"
    )

    old_argv = sys.argv
    try:
        sys.argv = [
            "check_backlog_done_headings.py",
            "--base-ref",
            "HEAD",
            "--repo-root",
            str(repo),
        ]
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0


def test_git_show_returns_none_for_unresolvable_ref(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "BACKLOG_DONE.md").write_text("# empty\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    assert git_show("not-a-real-ref", "BACKLOG_DONE.md", repo) is None


# --- WO-269: compare against the merge-base, not base-ref's own tip -------
#
# origin/main gains a BACKLOG_DONE.md heading every few minutes under a
# parallel wave while PRs sit open. Comparing against its raw tip failed
# any PR whose branch point predated one of those new headings, even
# though the PR never touched the file. The fix is to compare against
# the merge-base of base-ref and the branch being checked -- the state
# base-ref was in at the actual fork point -- which these tests exercise
# directly against a real (temporary) git repo with two diverged branches.


def test_resolve_merge_base_falls_back_to_base_ref_when_no_common_history(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    # An orphan branch shares no history at all with "main" -- merge-base
    # has nothing to find, so this must fall back to base_ref itself
    # rather than raising or returning a nonsense value.
    _git(repo, "checkout", "-q", "--orphan", "orphan")
    (repo / "f.txt").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "orphan commit")

    assert resolve_merge_base("main", "HEAD", repo) == "main"


def test_resolve_merge_base_returns_the_common_ancestor_of_diverged_branches(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("base", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    fork_point = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "f.txt").write_text("feature", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feature commit")

    _git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("main advances", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main advances")

    _git(repo, "checkout", "-q", "feature")
    assert resolve_merge_base("main", "HEAD", repo) == fork_point


def _build_diverged_repo(tmp_path: Path) -> Path:
    """A repo with `main` and `feature` branches sharing one base commit,
    where `feature` never touches BACKLOG_DONE.md/BACKLOG.md after the
    fork and `main` is free to keep moving on its own."""
    repo = _init_repo(tmp_path)
    (repo / "BACKLOG_DONE.md").write_text(_read("base_done.md"), encoding="utf-8")
    (repo / "BACKLOG.md").write_text(_read("base_backlog.md"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    _git(repo, "checkout", "-q", "main")
    return repo


def test_main_passes_when_main_gains_a_heading_after_the_branch_point(tmp_path, capsys):
    """A PR branch that never touched BACKLOG_DONE.md must not fail just
    because `main` added a new entry after the branch forked -- the real
    failure this replaced (#1027, WO-241, WO-251, 2026-09-12)."""
    repo = _build_diverged_repo(tmp_path)

    # main gains a brand-new heading after the fork point.
    new_done = _read("base_done.md") + (
        "\n## WO-999: a heading added after the branch point "
        "[Done 2026-09-12]\n\nNot visible to feature.\n"
    )
    (repo / "BACKLOG_DONE.md").write_text(new_done, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main gains a heading")

    _git(repo, "checkout", "-q", "feature")

    old_argv = sys.argv
    try:
        sys.argv = [
            "check_backlog_done_headings.py",
            "--base-ref",
            "main",
            "--repo-root",
            str(repo),
        ]
        exit_code = main()
    finally:
        sys.argv = old_argv

    out = capsys.readouterr()
    assert exit_code == 0
    assert "WO-999" not in out.err


def test_main_still_fails_when_branch_drops_an_inherited_heading(tmp_path, capsys):
    """The case the gate exists for must keep failing even while `main`
    has moved on: a branch that drops a heading it actually inherited."""
    repo = _build_diverged_repo(tmp_path)

    _git(repo, "checkout", "-q", "feature")
    (repo / "BACKLOG_DONE.md").write_text(
        _read("working_done_missing.md"), encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feature drops a heading")

    _git(repo, "checkout", "-q", "main")
    new_done = _read("base_done.md") + (
        "\n## WO-999: a heading added after the branch point "
        "[Done 2026-09-12]\n\nNot visible to feature.\n"
    )
    (repo / "BACKLOG_DONE.md").write_text(new_done, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main gains a heading")

    _git(repo, "checkout", "-q", "feature")

    old_argv = sys.argv
    try:
        sys.argv = [
            "check_backlog_done_headings.py",
            "--base-ref",
            "main",
            "--repo-root",
            str(repo),
        ]
        exit_code = main()
    finally:
        sys.argv = old_argv

    out = capsys.readouterr()
    assert exit_code == 1
    assert "WO-900: fixed the gadget" in out.err
    # WO-999 was never the branch's to lose -- it didn't exist yet at the
    # branch's fork point -- so it must not be reported missing.
    assert "WO-999" not in out.err


def test_main_passes_when_branch_only_adds_headings(tmp_path):
    """A branch that adds new BACKLOG_DONE.md entries of its own (and
    drops nothing it inherited) must pass, even against a diverged main."""
    repo = _build_diverged_repo(tmp_path)

    _git(repo, "checkout", "-q", "feature")
    new_done = _read("base_done.md") + (
        "\n## WO-777: a brand new entry on the branch [Done 2026-09-12]\n"
    )
    (repo / "BACKLOG_DONE.md").write_text(new_done, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feature adds a heading")

    old_argv = sys.argv
    try:
        sys.argv = [
            "check_backlog_done_headings.py",
            "--base-ref",
            "main",
            "--repo-root",
            str(repo),
        ]
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0
