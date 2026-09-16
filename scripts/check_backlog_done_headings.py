#!/usr/bin/env python3
"""Fail a PR that silently drops a finished-work entry from BACKLOG_DONE.md.

Why this exists (WO-236, 2026-09-11): BACKLOG_DONE.md is append-only by
convention -- once an entry is written, it never leaves (see CLAUDE.md).
Nothing enforced that. Two hand-resolved rebase conflicts (`b88eee4` /
PR #948, and `9bb73d1` / PR #950) each took one side of a file that is a
union by nature, and between them silently dropped 22 already-recorded
headings in one evening; a third PR (#983, merged separately) found and
restored two more of its own the same way. There was no automated check
that would have caught any of this before merge -- this script is that
check. See `BACKLOG_DONE.md`'s own WO-236 entry for the restoration
detail and the (smaller than it first looked) actual damage: most of the
22 turned out to be an already-duplicated block that a rebase correctly
collapsed to one copy, but the collapse also clipped the last line off
several entries, and that real, if tiny, loss is what this guards
against going forward.

What it checks (BACKLOG_DONE.md, blocking): every distinct `## ` heading
present in BACKLOG_DONE.md at the merge-base of a BASE ref and the branch
being checked (see WO-269 in the Usage section below for why it's the
merge-base and not the BASE ref's own tip) must still be present -- at
least once -- in the current working tree's BACKLOG_DONE.md. This is a
plain set (existence) comparison, deliberately not a multiset/count one.
BACKLOG_DONE.md has, at least once, genuinely had a whole 21-entry block
duplicated by an earlier bad merge (see WO-236's own entry): a later
rebase collapsed each duplicated heading back down to one surviving
copy, which is the correct, desired fix, not a loss -- a count-based
check would have flagged that legitimate cleanup as a failure on the
very PR that did it. What actually causes damage is a heading dropping
to *zero* copies, and a plain existence check catches that exactly as
well as a count-based one would, without punishing dedup. It does not
check an entry's *body* -- a heading whose content grows (an entry
legitimately gets a "confirmed live in production" postscript added
after the fact) is never flagged, only a heading that vanished outright.
One known, accepted false-positive shape: an entry whose heading TEXT
itself is later rewritten in place (e.g. a "priority bands, N of M,
continuing" heading updated to "all M, done" once a sweep finishes) will
show as "missing" its old exact text against a comparison point old
enough to predate the rewrite -- CI only ever compares against the
merge-base with the branch's own fork point (or, on a direct push to
main, the immediately preceding commit), so this is not a practical risk
in normal use, only a caveat for anyone re-running this against an old,
arbitrary snapshot by hand.

What it checks (BACKLOG.md, warning only): a top-level entry (a
`### ...` heading, or a `- **[TAG] ...` bullet -- the same shapes
`scripts/build_backlog_toc.py` already recognizes as entries) present at
that same merge-base but missing from the working tree is printed as a
WARNING,
never a failure, UNLESS its title also appears as a `## ` heading
anywhere in the working tree's BACKLOG_DONE.md (the normal, healthy way
an open entry leaves BACKLOG.md: the work got done and the entry moved).
This is deliberately non-blocking. BACKLOG.md's own convention (see its
header, and CLAUDE.md's "overwrite-don't-append" bullet) is that an open
entry gets rewritten -- sometimes its whole title -- as the work behind
it narrows or a re-investigation corrects it; that is a normal, frequent,
*legitimate* edit, not a loss, and a hard gate on it would false-positive
on nearly every session that touches BACKLOG.md. The warning exists so a
human (or the next session) can glance at it and confirm a real
retirement happened -- moved to BACKLOG_DONE.md, or explained in the PR
body -- rather than silently losing an open item the way BACKLOG_DONE.md
entries did.

Usage:
    python3 scripts/check_backlog_done_headings.py [--base-ref REF]
        [--head-ref REF] [--done-file PATH] [--backlog-file PATH]
        [--repo-root PATH]

REF defaults to origin/main. Exits non-zero (and lists every missing
BACKLOG_DONE.md heading) only for a BACKLOG_DONE.md loss; a BACKLOG.md-only
loss prints a warning to stderr and still exits zero.

WO-269 (2026-09-12): the comparison point is the merge-base of
--base-ref and --head-ref (HEAD by default), never --base-ref's own tip.
Under a parallel wave, origin/main gains a BACKLOG_DONE.md heading every
few minutes while several PRs sit open; comparing against its tip meant
any PR whose branch point predated one of those new headings failed even
though it never touched the file (hit at least four times on 2026-09-12,
including #1027 twice and re-rebases of WO-241/WO-251 for the same
reason). The check's actual purpose -- catching a PR that DROPS a
heading it inherited -- only needs the state of --base-ref at the point
the branch forked from it, which is exactly what the merge-base is. If
git can't compute one (e.g. a shallow clone with too little fetched
history, or two refs with no common history at all), this falls back to
--base-ref's tip -- the previous behaviour -- rather than erroring out.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.build_backlog_toc import parse  # noqa: E402

DONE_HEADING_PREFIX = "## "


def git_show(ref: str, path: str, repo_root: Path = REPO_ROOT) -> str | None:
    """Return a file's content at `ref`, or None if it doesn't resolve.

    None covers both a ref git can't find (e.g. a base branch a shallow
    clone never fetched) and a path that didn't exist yet at that ref
    (e.g. a brand-new file) -- both are treated as "nothing to lose"
    rather than an error, since a script that hard-fails on either would
    itself become the thing that blocks an unrelated PR.
    """
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def resolve_merge_base(
    base_ref: str, head_ref: str, repo_root: Path = REPO_ROOT
) -> str:
    """Return the merge-base commit of `base_ref` and `head_ref`.

    WO-269: this is the fix for comparing against `base_ref`'s own tip,
    which made the check fail PRs that never touched BACKLOG_DONE.md --
    under a parallel wave, `origin/main` gains a heading every few
    minutes while PRs sit open, so any branch point predating one of
    those failed even though it inherited nothing missing. The merge-base
    is the state of `base_ref` at the point `head_ref`'s branch actually
    forked from it, which is what the check's heading-loss guarantee
    needs -- a heading `base_ref` gained *after* that fork point was never
    the branch's to lose.

    Falls back to `base_ref` itself (the previous, tip-based behaviour)
    if git can't compute a merge-base at all -- e.g. a shallow clone that
    didn't fetch enough shared history, or two refs with no common
    history. A script that hard-failed here would itself become the
    thing blocking an unrelated PR, same reasoning as `git_show`'s
    None-on-missing-ref handling above.
    """
    result = subprocess.run(
        ["git", "merge-base", base_ref, head_ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    merge_base = result.stdout.strip()
    if result.returncode != 0 or not merge_base:
        return base_ref
    return merge_base


def done_headings(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith(DONE_HEADING_PREFIX)]


def missing_items(base_items: list[str], working_items: list[str]) -> list[str]:
    """Distinct items in base_items with zero copies left in working_items.

    A plain set (existence) comparison -- see the module docstring for why
    this is deliberately not a count/multiset comparison. Order follows
    base_items' own first-seen order, for deterministic, readable output.
    """
    working_set = set(working_items)
    seen: set[str] = set()
    missing: list[str] = []
    for item in base_items:
        if item in working_set or item in seen:
            continue
        seen.add(item)
        missing.append(item)
    return missing


def backlog_entry_titles(text: str) -> list[str]:
    """Every top-level BACKLOG.md entry title (`### ...` leaf, or a
    top-level `- **[TAG] ...` bullet), using the same shapes
    `scripts/build_backlog_toc.py` already treats as real entries so this
    stays in lockstep with the TOC's own definition of "an entry"."""
    roots = parse(text.split("\n"))
    titles: list[str] = []

    def walk(node) -> None:
        if node.is_leaf_entry:
            titles.append(node.title)
            return
        for child in node.children:
            walk(child)

    for root in roots:
        walk(root)
    return titles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--base-ref",
        default="origin/main",
        help="git ref to compare against (default: origin/main)",
    )
    ap.add_argument(
        "--head-ref",
        default="HEAD",
        help=(
            "git ref for the branch being checked -- the comparison point "
            "is this ref's merge-base with --base-ref, not --base-ref's own "
            "tip (WO-269; default: HEAD)"
        ),
    )
    ap.add_argument(
        "--done-file",
        default="BACKLOG_DONE.md",
        help="path (repo-relative) to the done-log file",
    )
    ap.add_argument(
        "--backlog-file",
        default="BACKLOG.md",
        help="path (repo-relative) to the live backlog file",
    )
    ap.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        type=Path,
        help="repo root git commands run from (default: this script's repo)",
    )
    args = ap.parse_args()

    effective_base_ref = resolve_merge_base(
        args.base_ref, args.head_ref, args.repo_root
    )
    print(
        f"check_backlog_done_headings: comparing against the merge-base of "
        f"{args.base_ref!r} and {args.head_ref!r}: {effective_base_ref}"
    )

    base_done = git_show(effective_base_ref, args.done_file, args.repo_root)
    if base_done is None:
        print(
            f"check_backlog_done_headings: could not read "
            f"{effective_base_ref}:{args.done_file} -- skipping "
            f"(nothing to compare against; a brand-new file or an "
            f"unfetched ref both land here)."
        )
        return 0

    working_done_path = args.repo_root / args.done_file
    working_done = working_done_path.read_text(encoding="utf-8")

    missing_done = missing_items(done_headings(base_done), done_headings(working_done))

    exit_code = 0
    if missing_done:
        exit_code = 1
        print(
            f"BACKLOG_DONE.md is missing {len(missing_done)} heading(s) "
            f"present at {effective_base_ref} -- a finished-work entry "
            f"never leaves this file (see CLAUDE.md). If a rebase/merge "
            f"dropped these, restore them verbatim from git history (see "
            f"BACKLOG_DONE.md's WO-236 entry for how) rather than editing "
            f"around this check:",
            file=sys.stderr,
        )
        for heading in missing_done:
            print(f"  MISSING: {heading}", file=sys.stderr)

    # BACKLOG.md: warning-only. See module docstring for why this one
    # never fails the build.
    base_backlog = git_show(effective_base_ref, args.backlog_file, args.repo_root)
    if base_backlog is not None:
        working_backlog_path = args.repo_root / args.backlog_file
        working_backlog = working_backlog_path.read_text(encoding="utf-8")

        base_titles = backlog_entry_titles(base_backlog)
        working_titles = backlog_entry_titles(working_backlog)
        missing_open = missing_items(base_titles, working_titles)

        # An open entry that "left" but whose title now appears as a
        # BACKLOG_DONE.md heading was legitimately promoted/closed, not
        # lost -- the normal, healthy path. Only warn about the rest.
        done_heading_text = {
            h[len(DONE_HEADING_PREFIX) :] for h in done_headings(working_done)
        }
        genuinely_missing = [t for t in missing_open if t not in done_heading_text]

        if genuinely_missing:
            print(
                f"WARNING: {len(genuinely_missing)} BACKLOG.md entry title(s) "
                f"present at {effective_base_ref} are gone from the working "
                f"tree and don't match a BACKLOG_DONE.md heading. This is "
                f"not a failure -- an open entry legitimately gets rewritten "
                f"as work narrows (see CLAUDE.md's overwrite-don't-append "
                f"bullet) -- but if one of these was actually dropped rather "
                f"than rewritten, move it to BACKLOG_DONE.md or say so in "
                f"the PR body:",
                file=sys.stderr,
            )
            for title in genuinely_missing:
                print(f"  WARNING: {title}", file=sys.stderr)

    if exit_code == 0:
        print("check_backlog_done_headings: no BACKLOG_DONE.md headings lost.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
