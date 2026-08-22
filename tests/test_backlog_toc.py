"""Guards on BACKLOG.md's generated table of contents.

The reading protocol in CLAUDE.md tells a session to read *only* the TOC
block at startup and to grep a quoted fragment when it needs the full
entry. Both halves of that only work if the generator's contract holds, so
these test it against the real file rather than a fixture:

  * every TOC title is a verbatim prefix of a real line further down (else
    the documented `grep -n -F` step silently returns nothing);
  * the TOC in the repo is current (the same check CI runs);
  * regenerating is idempotent;
  * entry detection matches the file's own "tag every entry" convention,
    which is what the per-section counts are built on.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_backlog_toc import TOC_END, TOC_START, build, parse  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKLOG = REPO_ROOT / "BACKLOG.md"
SCRIPT = REPO_ROOT / "scripts" / "build_backlog_toc.py"


@pytest.fixture(scope="module")
def backlog_text() -> str:
    return BACKLOG.read_text(encoding="utf-8")


def _toc_body(text: str) -> list[str]:
    lines = text.split("\n")
    start = lines.index(TOC_START)
    end = lines.index(TOC_END)
    body = lines[start:end]
    fence = body.index("```text")
    return body[fence + 1 : -2]


def _titles(text: str) -> list[str]:
    out = []
    for line in _toc_body(text):
        stripped = line.strip()
        if not stripped:
            continue
        # Section lines carry a trailing "  (N)" count; entries don't.
        if stripped.endswith(")") and "  (" in stripped:
            stripped = stripped[: stripped.rindex("  (")]
        out.append(stripped)
    return out


def test_toc_block_exists(backlog_text):
    assert TOC_START in backlog_text
    assert TOC_END in backlog_text
    assert backlog_text.index(TOC_START) < backlog_text.index(TOC_END)


def test_every_toc_title_greps_back_to_a_real_line(backlog_text):
    """The whole point of the TOC: a title is a usable grep target."""
    body = backlog_text.split(TOC_END, 1)[1]
    misses = []
    for title in _titles(backlog_text):
        needle = title[:-1] if title.endswith("…") else title
        if needle not in body:
            misses.append(needle)
    assert not misses, f"TOC titles that grep to nothing in BACKLOG.md: {misses}"


def test_toc_is_current(backlog_text):
    assert build(backlog_text) == backlog_text, (
        "BACKLOG.md's TOC is stale — run `python3 scripts/build_backlog_toc.py`"
    )


def test_build_is_idempotent(backlog_text):
    once = build(backlog_text)
    assert build(once) == once


def test_check_mode_passes_on_the_real_file():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(BACKLOG)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_untagged_sub_bullets_are_not_counted_as_entries():
    """A synthetic shape, exercising the one branch the real file's counts
    depend on: an entry whose body enumerates cases as untagged bullets.

    Shape copied from the real "transcribe_backlog_locally.py" entry in
    Ship next (tagged header, untagged case bullets underneath); kept
    synthetic so the test doesn't break when that entry ships.
    """
    doc = "\n".join(
        [
            "# Backlog",
            "",
            "## Ship next",
            "",
            "- **[JUST-DO-IT] A real entry.** Body.",
            "",
            "### `[JUST-DO-IT]` An entry written as a header",
            "",
            "- **First case, untagged.** Detail.",
            "- **Second case, untagged.** Detail.",
            "",
        ]
    )
    (section,) = parse(doc.split("\n"))
    assert section.title == "Ship next"
    assert section.leaf_count() == 2, "untagged case bullets must not count"
    assert [c.title for c in section.children] == [
        "[JUST-DO-IT] A real entry.",
        "`[JUST-DO-IT]` An entry written as a header",
    ]


def test_grouping_header_counts_its_tagged_bullets():
    doc = "\n".join(
        [
            "# Backlog",
            "",
            "## Platform & jurisdiction coverage",
            "",
            "### Adapter & platform gaps",
            "",
            "- **[LATER] One.** Detail.",
            "- **[NEEDS-AUDIT] Two.** Detail.",
            "",
        ]
    )
    (section,) = parse(doc.split("\n"))
    assert section.leaf_count() == 2
    (group,) = section.children
    assert group.title == "Adapter & platform gaps"
    assert not group.is_leaf_entry
