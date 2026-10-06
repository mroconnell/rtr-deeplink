#!/usr/bin/env python3
"""Git custom merge driver for keyed, one-record-per-line files (WO-1184).

Usage (set up by scripts/setup_merge_drivers.sh):

    merge_line_set.py %O %A %B %P      # base, ours, theirs, path

Writes the merged result into %A. Exit 0 = clean, 1 = left conflict markers.

Why: the tier-3 queue and the pin CSVs are touched by dozens of parallel
branches, and git's normal text merge reports a conflict whenever two
branches add lines at the same spot. Every line in these files is an
independent record with a key, so most of those conflicts are not real.

Rules, per key (base / ours / theirs):
  - ours == theirs      -> take it
  - ours == base        -> take theirs (includes theirs deleting it)
  - theirs == base      -> take ours (includes ours deleting it)
  - otherwise           -> both changed the same record: conflict markers
                           around just that record, exit 1

Order: ours' order, with theirs' edits applied in place. A record only
theirs added goes right after the nearest preceding line of theirs that is
in the result (else at the end), after any lines ours itself added at that
spot, so two branches that both append end up ours-then-theirs.

Keys, by path:
  - the tier-3 queue file and scripts/tier3_long_meetings_deferred.txt:
    field 1 (the URL) of the tab-separated line. The deferred file's other
    columns mean different things, but only field 1 is used here. '#'
    comment and blank lines are keyed by their own text.
  - tenant_overrides.csv: first two CSV fields (tenant_host, match).
  - curated_governments.csv / governments.csv: first CSV field (gov_id).
  CSV files: line 1 is the header and is kept (merged like a record).

Byte exact: each line keeps its own line ending (some rows are CRLF), and
the file's trailing-newline state is kept. Nothing is normalized.

Safety: if a key repeats within any of the three inputs, a CSV record spans
more than one line (a quoted newline), or the path is unknown, this runs
plain `git merge-file` on the inputs instead and returns its result. It
never guesses.

Stdlib only, so it starts fast.
"""

from __future__ import annotations

import csv
import subprocess
import sys

# path suffix -> (kind, key_fields). kind "tsv" = tab-separated, no header;
# kind "csv" = header on line 1.
_RULES = [
    ("scripts/tier3_auto_transcription_queue.txt", ("tsv", 1)),
    ("scripts/tier3_long_meetings_deferred.txt", ("tsv", 1)),
    ("app/utils/jurisdiction_data/tenant_overrides.csv", ("csv", 2)),
    ("app/utils/jurisdiction_data/curated_governments.csv", ("csv", 1)),
    ("app/utils/jurisdiction_data/governments.csv", ("csv", 1)),
]


class _Fallback(Exception):
    """Inputs are not safe to merge record by record."""


def _rule_for(path: str):
    p = path.replace("\\", "/")
    for suffix, rule in _RULES:
        if p == suffix or p.endswith("/" + suffix):
            return rule
    return None


def _split_lines(text: str) -> list[str]:
    """Split on '\\n' only, each piece keeping its own ending (so a CRLF row
    keeps its '\\r'). A final piece without a newline stays unterminated."""
    pieces = text.split("\n")
    out = [p + "\n" for p in pieces[:-1]]
    if pieces[-1] != "":
        out.append(pieces[-1])
    return out


def _key(raw: str, kind: str, n: int):
    content = raw.rstrip("\r\n")
    if kind == "tsv":
        if content.startswith("#") or not content.strip():
            return ("raw", content)
        return ("url", content.split("\t")[0].strip())
    if content.count('"') % 2:
        raise _Fallback("CSV record may span lines")
    row = next(csv.reader([content]), [])
    return ("csv", *row[:n])


def _parse(text: str, kind: str, n: int):
    """(header_or_None, ordered keys, {key: raw})."""
    lines = _split_lines(text)
    header = None
    if kind == "csv" and lines:
        header, lines = lines[0], lines[1:]
    keys: list = []
    recs: dict = {}
    for raw in lines:
        k = _key(raw, kind, n)
        if k in recs:
            raise _Fallback(f"duplicate key {k!r}")
        keys.append(k)
        recs[k] = raw
    return header, keys, recs


def _nl(s: str) -> str:
    return s if s.endswith("\n") or not s else s + "\n"


def _conflict(ours: str | None, theirs: str | None) -> str:
    return (
        "<<<<<<< ours\n"
        + (_nl(ours) if ours else "")
        + "=======\n"
        + (_nl(theirs) if theirs else "")
        + ">>>>>>> theirs\n"
    )


def merge_text(base: str, ours: str, theirs: str, kind: str, n: int):
    """Return (merged_text, has_conflict). Raises _Fallback when unsafe."""
    bh, _, brec = _parse(base, kind, n)
    oh, okeys, orec = _parse(ours, kind, n)
    th, tkeys, trec = _parse(theirs, kind, n)

    conflict = False
    # Header (csv): same three-way rule.
    if kind == "csv":
        if oh == th or th == bh:
            header = oh
        elif oh == bh:
            header = th
        else:
            raise _Fallback("header changed on both sides")
    else:
        header = None

    # entries: list of [key, raw]; raw None = dropped.
    entries: list[list] = []
    for k in okeys:
        o = orec[k]
        b = brec.get(k)
        if k in trec:
            t = trec[k]
            if o == t or (b is not None and t == b):
                entries.append([k, o])
            elif b is not None and o == b:
                entries.append([k, t])
            else:
                conflict = True
                entries.append([k, _conflict(o, t)])
        else:
            if b is None or False:
                entries.append([k, o])  # ours added it
            elif o == b:
                continue  # theirs deleted it, ours untouched
            else:
                conflict = True
                entries.append([k, _conflict(o, None)])

    present = {e[0] for e in entries}
    for i, k in enumerate(tkeys):
        if k in orec:
            continue
        t = trec[k]
        b = brec.get(k)
        if b is not None:
            if t == b:
                continue  # ours deleted it, theirs untouched
            conflict = True
            raw = _conflict(None, t)
        else:
            raw = t  # theirs added it
        # Anchor: nearest preceding line of theirs that is in the result.
        pos = len(entries)
        for pk in reversed(tkeys[:i]):
            if pk in present:
                pos = next(j for j, e in enumerate(entries) if e[0] == pk) + 1
                # Step over lines ours added right there, so two branches
                # that both append stay in ours-then-theirs order.
                while (
                    pos < len(entries)
                    and entries[pos][0] in orec
                    and entries[pos][0] not in brec
                    and entries[pos][0] not in trec
                ):
                    pos += 1
                break
        entries.insert(pos, [k, raw])
        present.add(k)

    parts = [header] if header is not None else []
    parts += [e[1] for e in entries]
    out = "".join(_nl(p) for p in parts[:-1]) + (parts[-1] if parts else "")
    return out, conflict


def _git_merge_file(a: str, o: str, b: str) -> int:
    r = subprocess.run(
        ["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", a, o, b]
    )
    return 1 if r.returncode > 0 else (2 if r.returncode < 0 else 0)


def _read(path: str) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "surrogateescape")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("usage: merge_line_set.py BASE OURS THEIRS PATH", file=sys.stderr)
        return 2
    base_p, ours_p, theirs_p, path = argv[1:]
    rule = _rule_for(path)
    if rule is None:
        return _git_merge_file(ours_p, base_p, theirs_p)
    try:
        merged, conflict = merge_text(
            _read(base_p), _read(ours_p), _read(theirs_p), *rule
        )
    except _Fallback:
        return _git_merge_file(ours_p, base_p, theirs_p)
    with open(ours_p, "wb") as fh:
        fh.write(merged.encode("utf-8", "surrogateescape"))
    return 1 if conflict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
