"""Shared, repo-agnostic read-modify-write helper for a locked, git-tracked
CSV registry file (e.g. `jurisdiction_coverage.csv`, `hub_slug_aliases.csv`).

WO-940. Three real, confirmed gaps in this repo's own write protocol
(`ENUMERATION_METHODS.md` §158, restated in `CLAUDE.md`'s multi-session
bullet) motivated this -- see `BACKLOG.md`'s "jurisdiction_coverage.csv's
shared write helper still uses a", "scripts/score_gov_registry.py
overwrites", and "§158's write protocol doesn't catch a same-row-count"
entries:

  1. `scripts/wo127_civicplus_pipeline.py`'s own read-modify-write helper
     had a hardcoded `MIN_SANE_ROW_COUNT = 25000` floor instead of a
     floor re-derived from the committed file's own size at run time.
  2. `scripts/score_gov_registry.py` overwrote `hub_slug_aliases.csv`
     wholesale every run, with no read-first -- a real, confirmed-live
     regression risk (WO-109 found a naive overwrite would have dropped
     615 of 672 real redirect rows).
  3. Every `*_apply_to_jc.py` script's pre-write re-check compared only a
     row COUNT and header fieldnames against what it read earlier -- a
     real, confirmed-live collision (2026-09-10, WO-150/WO-147) showed a
     same-row-count, same-fieldnames concurrent write can pass that check
     and silently clobber uncommitted rows.

One shared, pure module -- takes a file PATH, no assumption about which
registry or which repo -- fixes all three at once and gives any future
write path a single place to get this right by construction:

  - An exclusive `flock` on a sibling `.lock` file, held for the ENTIRE
    read-modify-write. `mutate_fn` always operates on the read taken
    fresh AFTER the lock is acquired -- never a snapshot a caller might
    already be holding from before it called in.
  - `expected_content_hash`: a caller that read the file earlier (e.g.
    to decide *what* to change, over a slow candidate-building pass done
    before it ever reaches this helper) can pass the hash of what it
    read, and this helper refuses to write unless the file's CURRENT
    content -- read fresh, under the lock -- still hashes to exactly
    that. A row-count/fieldname check would not catch a same-row-count,
    same-fieldnames concurrent write; a content hash always does. See
    `tests/test_registry_write_helper.py`'s
    `test_stale_hash_catches_a_same_row_count_concurrent_write` for a
    synthetic reproduction of the real WO-150/WO-147 collision shape.
  - `min_row_floor`: refuse a read that comes back under this many rows,
    the same truncation guard every `*_apply_to_jc.py` script already
    has -- but computed at RUN TIME from the file's own committed size
    (`committed_row_count_floor()` below), not a constant that goes
    stale as the file grows.
  - Atomic write: a same-directory, per-call-unique temp file, then
    `os.replace()` -- a reader of any process never observes a partial
    file. Explicit LF line endings throughout.

Pure and repo-agnostic on purpose: every function here takes a `path`
and operates on it generically. It is unit-tested only against local
fixture CSVs created in the test itself (`tmp_path`) -- never against a
real registry. The real ones live in `~/Documents/rtr-business`, which
this repo's own CLAUDE.md says never to read, write, or commit into from
here.
"""

from __future__ import annotations

import csv
import hashlib
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover -- POSIX only, fine for this project
    fcntl = None


class RegistryWriteError(Exception):
    """Base for every refusal this module raises. Each one means the
    file was NOT written -- this module never leaves a partial write."""


class TruncatedReadError(RegistryWriteError):
    """The fresh read came back with fewer rows than `min_row_floor` --
    treated as a corrupt or mid-write snapshot, never as a legitimate new
    baseline."""


class StaleReadError(RegistryWriteError):
    """The file's current content no longer matches what the caller
    asserted it had already read (`expected_content_hash`), or changed
    during `mutate_fn` itself. A same-row-count, same-fieldnames
    concurrent write is still caught here, since this compares the full
    file content, not counts."""


@dataclass(frozen=True)
class ReadModifyWriteResult:
    """What happened. `row_count`/`fieldnames` reflect `rows` AFTER
    `mutate_fn` ran (`mutate_fn` is expected to mutate `rows` in place,
    so this is the same list, post-mutation) -- i.e. what was written,
    when `changed` is True. `content_hash` is of the file's content AFTER
    this call returns, whether or not anything was written."""

    changed: bool
    row_count: int
    fieldnames: Sequence[str]
    content_hash: str


def hash_text(text: str) -> str:
    """SHA-256 of exact file text. The one comparison every staleness
    check in this module uses -- a hash catches ANY difference, not just
    a change in row count or header fieldnames."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lock_path_for(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def read_modify_write(
    path: "os.PathLike[str] | str",
    mutate_fn: Callable[[List[dict]], bool],
    *,
    lock_path: "os.PathLike[str] | str | None" = None,
    min_row_floor: Optional[int] = None,
    expected_content_hash: Optional[str] = None,
    encoding: str = "utf-8",
) -> ReadModifyWriteResult:
    """Lock `path`, read it fresh, call `mutate_fn(rows) -> bool`, and --
    only if it returns True -- write the result back atomically.

    - `path`: the CSV file to read-modify-write.
    - `mutate_fn(rows)`: `rows` is a list of dicts in the file's own row
      order (as `csv.DictReader` would yield), taken fresh under the
      lock. Mutate it IN PLACE (add/remove/edit entries, e.g. via
      `rows[:] = ...`) and return whether anything actually changed. If
      you return False, nothing is written.
    - `lock_path`: sibling `.lock` file to flock. Default: `<path>.lock`.
    - `min_row_floor`: refuse the read (raise `TruncatedReadError`,
      before ever calling `mutate_fn`) if it comes back with fewer rows
      than this. Compute it at run time with `committed_row_count_floor`
      below -- never hardcode it. `None` skips this check.
    - `expected_content_hash`: if given, refuse to write (raise
      `StaleReadError`, before calling `mutate_fn`) unless the file's
      CURRENT content -- read fresh, right after the lock is acquired --
      hashes to exactly this. Pass `hash_text(...)` of whatever you read
      earlier, before you built your mutation plan, to guarantee nothing
      else wrote to the file in the meantime.
    - Missing file: raises `FileNotFoundError`. This helper is for
      editing a file that already exists; a caller that wants to create
      one for the first time should write it directly (there is nothing
      to lock-protect against yet) -- see this module's docstring and
      `scripts/score_gov_registry.py`'s bootstrap of an empty
      `hub_slug_aliases.csv` for the reference example.

    Returns `ReadModifyWriteResult`. Writes LF line endings via a
    same-directory, per-call-unique temp file, `os.replace()`d over
    `path`.
    """
    path = Path(path)
    lock_path = Path(lock_path) if lock_path is not None else _lock_path_for(path)
    if not path.exists():
        raise FileNotFoundError(path)

    lock_path.touch(exist_ok=True)
    with open(lock_path, "w") as lock_f:
        if fcntl:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            raw_text = path.read_text(encoding=encoding)
            content_hash = hash_text(raw_text)

            if (
                expected_content_hash is not None
                and content_hash != expected_content_hash
            ):
                raise StaleReadError(
                    f"{path}: content changed since the caller's earlier "
                    f"read (expected hash {expected_content_hash[:12]}…, "
                    f"found {content_hash[:12]}…) -- another writer "
                    "touched this file in the meantime. Refusing to write; "
                    "re-read and retry."
                )

            reader = csv.DictReader(raw_text.splitlines())
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

            if min_row_floor is not None and len(rows) < min_row_floor:
                raise TruncatedReadError(
                    f"{path}: read back only {len(rows)} rows (< floor "
                    f"{min_row_floor}) -- looks truncated or mid-write, not "
                    "a legitimate new baseline. Investigate before retrying."
                )

            changed = mutate_fn(rows)
            if not changed:
                return ReadModifyWriteResult(
                    changed=False,
                    row_count=len(rows),
                    fieldnames=fieldnames,
                    content_hash=content_hash,
                )

            # Defense in depth on top of the lock, not a substitute for
            # it: catches the file changing during `mutate_fn` itself
            # (e.g. a non-cooperating writer that bypasses this lock
            # entirely). Under consistent flock use across every writer,
            # this should always match.
            recheck_hash = hash_text(path.read_text(encoding=encoding))
            if recheck_hash != content_hash:
                raise StaleReadError(
                    f"{path}: content changed while mutate_fn was running "
                    "-- refusing to write a result computed against a "
                    "now-stale read."
                )

            tmp_path = path.with_name(
                f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
            )
            try:
                with open(tmp_path, "w", newline="", encoding=encoding) as f:
                    writer = csv.DictWriter(
                        f, fieldnames=fieldnames, lineterminator="\n"
                    )
                    writer.writeheader()
                    writer.writerows(rows)
                os.replace(tmp_path, path)
            finally:
                tmp_path.unlink(missing_ok=True)

            new_hash = hash_text(path.read_text(encoding=encoding))
            return ReadModifyWriteResult(
                changed=True,
                row_count=len(rows),
                fieldnames=fieldnames,
                content_hash=new_hash,
            )
        finally:
            if fcntl:
                fcntl.flock(lock_f, fcntl.LOCK_UN)


def committed_row_count_floor(
    path: "os.PathLike[str] | str",
    *,
    repo_root: "os.PathLike[str] | str | None" = None,
    ref: str = "HEAD",
    ratio: float = 0.99,
    fallback: Optional[int] = None,
) -> Optional[int]:
    """99% (or `ratio`) of `path`'s own line count as committed at `ref`
    in git, re-derived at run time -- replaces a hardcoded row-count
    constant that goes stale as the file grows (see this module's own
    docstring). Counts lines the same way `wc -l`/the existing
    `*_apply_to_jc.py` scripts do (`git show <ref>:<path> | wc -l`, i.e.
    `output.count("\\n")`), so the result is directly comparable to
    `len(rows)` from a `csv.DictReader` read of the same file (off by the
    one header line, same as every existing caller -- immaterial at real
    file sizes).

    `repo_root` defaults to walking up from `path` to find a `.git`
    directory. Never raises: if `path` isn't inside a git repo, `git` is
    unavailable, or the show fails for any other reason, prints a
    warning to stderr and returns `fallback` (which may itself be
    `None`, meaning "skip the floor" -- it's the caller's call whether a
    git failure should block a write or not; see
    `scripts/wo127_civicplus_pipeline.py` and
    `scripts/score_gov_registry.py` for the two different real choices).
    """
    path = Path(path).resolve()
    try:
        root = Path(repo_root).resolve() if repo_root is not None else None
        if root is None:
            root = _find_repo_root(path)
        if root is None:
            raise RuntimeError(f"no .git directory found above {path}")
        rel = path.relative_to(root)
        env = dict(os.environ)
        env["GIT_DIR"] = str(root / ".git")
        env["GIT_WORK_TREE"] = str(root)
        out = subprocess.run(
            ["git", "show", f"{ref}:{rel.as_posix()}"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            cwd=root,
        ).stdout
        committed_lines = out.count("\n")
        floor = int(committed_lines * ratio)
        print(
            f"{path.name}: committed at {ref} with {committed_lines} lines "
            f"-> {ratio:.0%} floor {floor}",
            file=sys.stderr,
        )
        return floor
    except Exception as exc:  # noqa: BLE001 -- deliberately never raises
        print(
            f"WARNING: could not compute a live row-count floor for {path} "
            f"from git ({exc}); using fallback {fallback!r}",
            file=sys.stderr,
        )
        return fallback


def _find_repo_root(path: Path) -> Optional[Path]:
    """Walk up from `path`'s own directory looking for a `.git`. `path`
    is expected to be a file, so the search starts at its parent, not at
    `path` itself."""
    start = path.parent if path.parent != path else path
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None
