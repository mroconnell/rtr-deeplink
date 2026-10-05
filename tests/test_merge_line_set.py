"""WO-1184: tests for scripts/merge_line_set.py and the .gitattributes rules.

All fixtures here are SYNTHETIC (hand-built) per CLAUDE.md. Only the *shape*
of each line is copied from the real files (queue line columns, the
tenant_overrides.csv header and 6 columns, a CRLF row as in governments.csv).
The merge logic itself is exercised, not any real data.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import merge_line_set as mls  # noqa: E402

QUEUE = "scripts/tier3_auto_transcription_queue.txt"
TENANT = "app/utils/jurisdiction_data/tenant_overrides.csv"
GOVS = "app/utils/jurisdiction_data/governments.csv"

HDR = "tenant_host,match,gov_id,strength,source,evidence\n"


def q(n: int) -> str:
    return f"https://www.youtube.com/watch?v=vid{n:08d}\t\tus:place:{n:07d}\n"


def run(tmp_path, path, base, ours, theirs):
    """Run the driver the way git does; return (exit_code, merged_text)."""
    files = {}
    for name, text in (("O", base), ("A", ours), ("B", theirs)):
        p = tmp_path / name
        p.write_bytes(text.encode())
        files[name] = str(p)
    code = mls.main(["x", files["O"], files["A"], files["B"], path])
    return code, (tmp_path / "A").read_bytes().decode()


def test_both_append_at_same_spot_keeps_both(tmp_path):
    base = q(1) + q(2)
    code, out = run(tmp_path, QUEUE, base, base + q(3), base + q(4))
    assert code == 0
    assert out == q(1) + q(2) + q(3) + q(4)


def test_ours_consumed_line_and_theirs_appends_next_to_it(tmp_path):
    base = q(1) + q(2) + q(3)
    ours = q(2) + q(3)  # the feed consumed line 1
    theirs = q(1) + q(2) + q(3) + q(9)
    code, out = run(tmp_path, QUEUE, base, ours, theirs)
    assert code == 0
    assert out == q(2) + q(3) + q(9)  # removal sticks, append kept


def test_theirs_append_right_after_a_line_ours_removed(tmp_path):
    base = q(1) + q(2)
    ours = q(2)
    theirs = q(1) + q(7) + q(2)  # inserted just after the removed line
    code, out = run(tmp_path, QUEUE, base, ours, theirs)
    assert code == 0
    assert out == q(2) + q(7) or out == q(7) + q(2)
    assert q(1) not in out


def test_theirs_insert_goes_after_its_nearest_preceding_line(tmp_path):
    base = q(1) + q(3)
    code, out = run(tmp_path, QUEUE, base, base + q(5), q(1) + q(2) + q(3))
    assert code == 0
    assert out == q(1) + q(2) + q(3) + q(5)


def row(host, gov, source="wo1", match=""):
    return f"{host},{match},{gov},fallback,{source},evidence text\n"


def test_both_edit_same_tenant_row_conflicts_on_that_row_only(tmp_path):
    a, b, c = row("a.example.net", "us:place:1"), row("b.example.net", "us:place:2"), row(
        "c.example.net", "us:place:3"
    )
    base = HDR + a + b
    ours = HDR + a + row("b.example.net", "us:place:20") + c
    theirs = HDR + a + row("b.example.net", "us:place:21")
    code, out = run(tmp_path, TENANT, base, ours, theirs)
    assert code == 1
    assert out == (
        HDR
        + a
        + "<<<<<<< ours\n"
        + row("b.example.net", "us:place:20")
        + "=======\n"
        + row("b.example.net", "us:place:21")
        + ">>>>>>> theirs\n"
        + c
    )


def test_one_side_edit_is_taken(tmp_path):
    a, b = row("a.example.net", "us:place:1"), row("b.example.net", "us:place:2")
    base = HDR + a + b
    edited = row("b.example.net", "us:place:99")
    code, out = run(tmp_path, TENANT, base, base, HDR + a + edited)
    assert code == 0 and out == HDR + a + edited
    code, out = run(tmp_path, TENANT, base, HDR + a + edited, base)
    assert code == 0 and out == HDR + a + edited


def test_crlf_rows_preserved_byte_exact(tmp_path):
    a = "a.example.net,,us:place:1,fallback,wo1,e\r\n"
    b = "b.example.net,,us:place:2,fallback,wo1,e\n"
    c = "c.example.net,,us:place:3,fallback,wo1,e\r\n"
    d = "d.example.net,,us:place:4,fallback,wo1,e\n"
    base = HDR + a + b
    code, out = run(tmp_path, TENANT, base, base + c, base + d)
    assert code == 0
    assert out == HDR + a + b + c + d
    assert out.encode().count(b"\r\n") == 2


def test_crlf_header_kept_on_gov_id_file(tmp_path):
    h = "gov_id,name\r\n"
    base = h + "us:place:1,A\r\n"
    code, out = run(
        tmp_path, GOVS, base, base + "us:place:2,B\r\n", base + "us:place:3,C\r\n"
    )
    assert code == 0
    assert out == base + "us:place:2,B\r\nus:place:3,C\r\n"


def test_duplicate_key_falls_back_to_git_merge_file(tmp_path):
    a = row("dup.example.net", "us:place:1", "wo1")
    a2 = row("dup.example.net", "us:place:1", "wo2")  # same (host, match)
    base = HDR + a + a2
    code, out = run(tmp_path, TENANT, base, base + row("x.example.net", "g:1"), base)
    assert code == 0
    assert out == base + row("x.example.net", "g:1")  # plain 3-way result
    # Two appends at the same spot: plain git conflicts; we must not guess.
    code, out = run(
        tmp_path,
        TENANT,
        base,
        base + row("x.example.net", "g:1"),
        base + row("y.example.net", "g:2"),
    )
    assert code == 1
    assert "<<<<<<< ours" in out


def test_multiline_csv_record_falls_back(tmp_path):
    odd = 'a.example.net,,us:place:1,fallback,wo1,"line one\n'
    odd2 = 'line two"\n'
    base = HDR + odd + odd2
    code, out = run(tmp_path, TENANT, base, base + row("x.example.net", "g:1"), base)
    assert code == 0
    assert out == base + row("x.example.net", "g:1")


def test_header_kept(tmp_path):
    base = HDR + row("a.example.net", "g:1")
    code, out = run(
        tmp_path,
        TENANT,
        base,
        base + row("b.example.net", "g:2"),
        base + row("c.example.net", "g:3"),
    )
    assert code == 0
    assert out.startswith(HDR)


def test_no_trailing_newline_preserved(tmp_path):
    base = q(1) + q(2).rstrip("\n")
    code, out = run(tmp_path, QUEUE, base, base, base)
    assert code == 0 and out == base
    # Theirs appends after ours' unterminated last line: that line gains a
    # newline (it is no longer last), the new last line keeps no newline.
    theirs = base + "\n" + q(3).rstrip("\n")
    code, out = run(tmp_path, QUEUE, base, base, theirs)
    assert code == 0
    assert out == q(1) + q(2) + q(3).rstrip("\n")


def test_comment_lines_in_deferred_file(tmp_path):
    path = "scripts/tier3_long_meetings_deferred.txt"
    c = "# url<TAB>source_url<TAB>gov_id<TAB>jurisdiction<TAB>duration<TAB>title\n"
    line = lambda n: f"https://example.org/m/{n}\t\tus:place:{n}\tTown\t120\tTitle\n"  # noqa: E731
    code, out = run(tmp_path, path, c + line(1), c + line(1) + line(2), c + line(1) + line(3))
    assert code == 0
    assert out == c + line(1) + line(2) + line(3)


def test_unknown_path_uses_plain_merge(tmp_path):
    code, out = run(tmp_path, "README.md", "a\nb\n", "a\nb\nc\n", "a\nb\n")
    assert code == 0 and out == "a\nb\nc\n"


# --- integration: a real git repo, setup script, real `git merge` ---------


def git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    git(r, "config", "commit.gpgsign", "false")
    shutil.copy(ROOT / "scripts/merge_line_set.py", r / "scripts/merge_line_set.py")
    shutil.copy(ROOT / ".gitattributes", r / ".gitattributes")
    subprocess.run(
        ["sh", str(ROOT / "scripts/setup_merge_drivers.sh")], cwd=r, check=True
    )
    (r / QUEUE).write_text(q(1) + q(2))
    (r / "BACKLOG_DONE.md").write_text("# Done\n\n## WO-1 [Done]\nx\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    return r


def _branch_append(r, name, path, text):
    git(r, "checkout", "-q", "-b", name, "main")
    with open(r / path, "a") as fh:
        fh.write(text)
    git(r, "commit", "-qam", name)


def test_integration_queue_appends_merge_clean(repo):
    _branch_append(repo, "a", QUEUE, q(3))
    _branch_append(repo, "b", QUEUE, q(4))
    git(repo, "checkout", "-q", "a")
    res = git(repo, "merge", "-q", "b", "-m", "m", check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    assert (repo / QUEUE).read_text() == q(1) + q(2) + q(3) + q(4)


def test_integration_without_driver_config_plain_merge_conflicts(repo):
    git(repo, "config", "--unset", "merge.lineset.driver")
    _branch_append(repo, "a", QUEUE, q(3))
    _branch_append(repo, "b", QUEUE, q(4))
    git(repo, "checkout", "-q", "a")
    res = git(repo, "merge", "-q", "b", "-m", "m", check=False)
    assert res.returncode != 0  # safe default: plain text merge, real conflict


def test_integration_union_on_backlog_done(repo):
    _branch_append(repo, "a", "BACKLOG_DONE.md", "## WO-2 [Done]\nfrom a\n")
    _branch_append(repo, "b", "BACKLOG_DONE.md", "## WO-3 [Done]\nfrom b\n")
    git(repo, "checkout", "-q", "a")
    res = git(repo, "merge", "-q", "b", "-m", "m", check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    text = (repo / "BACKLOG_DONE.md").read_text()
    assert "WO-2" in text and "WO-3" in text and "WO-1" in text
