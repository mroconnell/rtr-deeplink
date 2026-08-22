#!/usr/bin/env python3
"""Regenerate BACKLOG.md's table of contents in place.

Why this exists (2026-08-22): BACKLOG.md is the file a session is supposed
to read at startup, and at 4,300 lines nobody did -- which is how three
real user-visible bugs sat unread near the bottom of it until an audit went
looking (see this repo's CLAUDE.md, and BACKLOG.md's own header). The
compaction that preceded this script halved the file; this closes the rest
of the gap by making the *whole* backlog readable in one screenful of
titles, with an exact grep target for pulling up any single entry.

The contract the reading protocol depends on:

  * Every line in the TOC is a **verbatim prefix of a real line in the
    file**, so `grep -n -F "<fragment>" BACKLOG.md` always lands on the
    entry it names. That is why titles are truncated out of the entry's
    *first source line only* and never re-joined across the file's ~72-col
    wrap -- a fragment stitched across a newline would grep to nothing.
  * Output is a pure function of the input: no timestamps, no counters
    that depend on run order. CI regenerates and diffs (see
    .github/workflows/test.yml), so any non-determinism here would fail
    every unrelated PR.

Structure it understands, matching how BACKLOG.md is actually written:

  * `##` is a section.
  * `###`/`####` are sometimes an entry in their own right (a titled entry
    with prose under it, e.g. everything in "Standing decisions") and
    sometimes just a grouping whose entries are the bullets beneath it
    (e.g. "Jurisdiction extraction & backfill"). Rather than guess, both
    get a TOC line; the *count* on a section only tallies leaves -- a
    header with nothing structural under it, or a top-level bullet -- so
    a grouping isn't double-counted with its own children.
  * A top-level `- **...` bullet is an entry **only when its title opens
    with a tag** (`[JUST-DO-IT]`, `[LATER]`, `[Closed …]`, …). That is the
    file's own stated convention -- "Tag every entry" -- and it is what
    separates a real entry from the untagged sub-point bullets that some
    long entries use to enumerate cases or residuals. Getting this wrong
    in either direction is what makes the section counts lie, so it is
    checked by tests/test_backlog_toc.py against the real file.

Usage:  python3 scripts/build_backlog_toc.py [--check] [path]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOC_START = "<!-- TOC-START -->"
TOC_END = "<!-- TOC-END -->"

#: Max width of a TOC title, before the ellipsis. Deliberately under
#: BACKLOG.md's own ~72-col wrap so a truncated title stays inside the
#: entry's first source line and remains greppable.
TITLE_WIDTH = 70

#: A top-level bullet counts as an entry only if its bold title opens with
#: a tag. Backticks are optional because headers write theirs as `[TAG]`
#: while bullets write them bare.
ENTRY_BULLET = re.compile(r"^- \*\*`?\[[^\]]+\]`?")


class Node:
    """A section header or a top-level entry bullet."""

    def __init__(self, level: int, title: str) -> None:
        self.level = level  # 2/3/4 for headers, 5 for entry bullets
        self.title = title
        self.children: list[Node] = []

    @property
    def is_leaf_entry(self) -> bool:
        return not self.children

    def leaf_count(self) -> int:
        if self.is_leaf_entry:
            return 1
        return sum(c.leaf_count() for c in self.children)


def truncate(text: str) -> str:
    """Shorten to TITLE_WIDTH on a word boundary, marking any elision.

    The result must stay a verbatim prefix of the source line, so this only
    ever cuts -- it never normalises whitespace or punctuation.
    """
    text = text.rstrip()
    if len(text) <= TITLE_WIDTH:
        return text
    cut = text[:TITLE_WIDTH]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip() + "…"


def entry_title(line: str) -> str:
    """The greppable title of a `- **...` entry bullet.

    Strips only the list marker and the opening bold run; a closing `**`
    is stripped too when the bold text happens to end on this same line.
    """
    text = line[2:].lstrip()
    if text.startswith("**"):
        text = text[2:]
    # Cut at the closing `**` when the bold run ends on this same line, so
    # the title is exactly the bold text rather than the bold text plus a
    # stray marker and half a sentence of body.
    close = text.find("**")
    if close != -1:
        text = text[:close]
    return truncate(text)


def parse(lines: list[str]) -> list[Node]:
    """Build the section tree, ignoring any existing TOC block."""
    roots: list[Node] = []
    stack: list[Node] = []
    in_toc = False

    for raw in lines:
        line = raw.rstrip("\n")

        if line.strip() == TOC_START:
            in_toc = True
            continue
        if line.strip() == TOC_END:
            in_toc = False
            continue
        if in_toc:
            continue

        node = None
        if line.startswith("#### "):
            node = Node(4, truncate(line[5:]))
        elif line.startswith("### "):
            node = Node(3, truncate(line[4:]))
        elif line.startswith("## "):
            node = Node(2, truncate(line[3:]))
        elif line.startswith("# "):
            stack.clear()  # the document title; resets any open section
            continue
        elif ENTRY_BULLET.match(line):
            node = Node(5, entry_title(line))

        if node is None:
            continue

        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        # Entry bullets never own children; don't let them capture the
        # sub-bullets that belong to their own body text.
        if node.level < 5:
            stack.append(node)

    return roots


def render(roots: list[Node]) -> list[str]:
    out = [
        TOC_START,
        "<!-- Generated by scripts/build_backlog_toc.py. Do not edit by hand;",
        "     rerun that script after any edit to this file. -->",
        "",
        "## Contents",
        "",
        "**Read this block, not the whole file.** Every line below is a",
        "verbatim prefix of a real line further down, so any entry opens with",
        '`grep -n -F "<fragment>" BACKLOG.md`. Counts are entries per section.',
        "",
        "```text",
    ]

    def walk(node: Node, depth: int) -> None:
        indent = "  " * depth
        if node.level < 5 and not node.is_leaf_entry:
            out.append(f"{indent}{node.title}  ({node.leaf_count()})")
        else:
            out.append(f"{indent}{node.title}")
        for child in node.children:
            walk(child, depth + 1)

    for root in roots:
        out.append("")
        walk(root, 0)

    out += ["```", "", TOC_END]
    return out


def build(text: str) -> str:
    lines = text.split("\n")
    toc = render(parse(lines))

    try:
        start = lines.index(TOC_START)
        end = lines.index(TOC_END)
    except ValueError:
        # No markers yet: place the block just above the first section, so
        # the file's own "where to file a new entry" preamble stays first.
        insert = next(
            (i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines)
        )
        return "\n".join(lines[:insert] + toc + [""] + lines[insert:])

    return "\n".join(lines[:start] + toc + lines[end + 1 :])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", default="BACKLOG.md", type=Path)
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the TOC is stale, without writing",
    )
    args = ap.parse_args()

    original = args.path.read_text(encoding="utf-8")
    updated = build(original)

    if args.check:
        if original != updated:
            print(
                f"{args.path} TOC is stale — run "
                f"`python3 scripts/build_backlog_toc.py`",
                file=sys.stderr,
            )
            return 1
        return 0

    if original != updated:
        args.path.write_text(updated, encoding="utf-8")
        print(f"{args.path}: TOC updated")
    else:
        print(f"{args.path}: TOC already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
