"""Build a "known wrong pins" test set from the git history of
tenant_overrides.csv (read-only).

A *change* is a key (tenant_host lowercase, match) whose gov_id differs from
its last known gov_id, either inside one commit (row removed and re-added) or
across commits (row vanished, later reappeared with another id). Most changes
are corrections of a wrong pin; ``change_kind`` separates the ones that are
plainly refinements (consolidated governments, minted -> national id).

Usage: python scripts/pin_audit_known_wrong.py [--out PATH] [--since DATE]
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TENANT_PATH = "app/utils/jurisdiction_data/tenant_overrides.csv"
DATA = REPO / "app/utils/jurisdiction_data"
DEFAULT_OUT = REPO / "scripts/pin_audit_data/known_wrong.csv"

FIELDS = [
    "host",
    "match",
    "old_gov_id",
    "new_gov_id",
    "old_source",
    "new_source",
    "commit",
    "date",
    "commit_subject",
    "change_kind",
    "same_base_name",
    "reverted_later",
    "new_evidence",
]

_NAME_WORDS = re.compile(
    r"\b(city|town|village|township|borough|county|municipality|of|the)\b"
)


def parse_csv_line(line: str):
    """One CSV row (host, match, gov_id, strength, source, evidence) or None."""
    try:
        rows = list(csv.reader(io.StringIO(line)))
    except csv.Error:
        return None
    if not rows or len(rows[0]) < 3:
        return None
    r = rows[0] + [""] * (6 - len(rows[0]))
    if r[0] == "tenant_host":
        return None
    return {
        "host": r[0].strip().lower(),
        "match": r[1].strip(),
        "gov_id": r[2].strip(),
        "source": r[4],
        "evidence": ",".join(r[5:]) if len(r) > 6 else r[5],
    }


def parse_log(text: str):
    """Yield (meta, removed, added) per commit from `git log -p -U0` output
    whose commit header lines look like `@@@sha|date|subject`."""
    meta = None
    removed: dict = {}
    added: dict = {}
    for line in text.splitlines():
        if line.startswith("@@@"):
            if meta:
                yield meta, removed, added
            sha, date, subj = (line[3:].split("|", 2) + ["", ""])[:3]
            meta = {"commit": sha, "date": date, "subject": subj}
            removed, added = {}, {}
        elif meta is None or line.startswith(("---", "+++", "@@")):
            continue
        elif line[:1] in "-+" and len(line) > 1:
            row = parse_csv_line(line[1:])
            if row:
                (removed if line[0] == "-" else added)[(row["host"], row["match"])] = (
                    row
                )
    if meta:
        yield meta, removed, added


def find_changes(commits):
    last: dict = {}
    changes = []
    for meta, removed, added in commits:
        for key, new in added.items():
            old = removed.get(key) or last.get(key)
            if (
                old
                and old["gov_id"]
                and new["gov_id"]
                and old["gov_id"] != new["gov_id"]
            ):
                changes.append(
                    {
                        "host": key[0],
                        "match": key[1],
                        "old_gov_id": old["gov_id"],
                        "new_gov_id": new["gov_id"],
                        "old_source": old["source"],
                        "new_source": new["source"],
                        "commit": meta["commit"],
                        "date": meta["date"],
                        "commit_subject": meta["subject"],
                        "new_evidence": new["evidence"][:200],
                    }
                )
            last[key] = new
    return changes


# ---- classification -------------------------------------------------------

_cache: dict = {}


def _load_relations():
    if "rel" in _cache:
        return _cache["rel"]
    canon, rel = {}, set()
    for name, fn in (
        (
            "consolidated_governments.csv",
            lambda r: canon.update({r["gov_id"]: r["canonical_gov_id"]}),
        ),
        (
            "gov_relations.csv",
            lambda r: rel.add(frozenset((r["from_gov_id"], r["to_gov_id"]))),
        ),
    ):
        p = DATA / name
        if p.exists():
            with p.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    fn(r)
    _cache["rel"] = (canon, rel)
    return _cache["rel"]


def _info(gov_id: str):
    """(name, state, country, gov_type) or None if unresolvable."""
    from app.utils.gov_registry.registry import government_for_id

    try:
        g = government_for_id(gov_id)
    except Exception:
        g = None
    if g:
        return g.gov_name, (g.state or "").upper(), g.country, g.gov_type
    m = re.match(r"rtr:([a-z]{2}):([a-z]{2}):(.+)$", gov_id)
    if m:
        return m.group(3).replace("-", " "), m.group(2).upper(), m.group(1), "minted"
    return None


def base_name(name: str) -> str:
    name = re.sub(r"\([^)]*\)", " ", name.lower())
    return " ".join(_NAME_WORDS.sub(" ", name).split())


def _same_base(a, b) -> str:
    if not a or not b:
        return "no"
    x, y = base_name(a[0]), base_name(b[0])
    return "yes" if x and x == y else "no"


def _is_county(gov_id: str) -> bool:
    return gov_id.startswith(("us:county", "ca:cd"))


def classify(old_id: str, new_id: str, info=_info):
    """Return (change_kind, same_base_name)."""
    canon, rel = _load_relations()
    a, b = info(old_id), info(new_id)
    same_name = _same_base(a, b)
    if (
        canon.get(old_id, old_id) == canon.get(new_id, new_id)
        or frozenset((old_id, new_id)) in rel
    ):
        return "consolidated", same_name
    if old_id.startswith("rtr:") != new_id.startswith("rtr:"):
        return "minted_to_registry", same_name
    if not a or not b or not a[1] or not b[1]:
        return "unknown", same_name
    if a[1] != b[1] or a[2] != b[2]:
        return "different_state", same_name
    if _is_county(old_id) != _is_county(new_id):
        return "county_place_level", same_name
    return "same_state_other_gov", same_name


def annotate(changes):
    for i, c in enumerate(changes):
        c["change_kind"], c["same_base_name"] = classify(
            c["old_gov_id"], c["new_gov_id"]
        )
        c["reverted_later"] = (
            "yes"
            if any(
                d["host"] == c["host"]
                and d["match"] == c["match"]
                and d["new_gov_id"] == c["old_gov_id"]
                for d in changes[i + 1 :]
            )
            else "no"
        )
    return changes


def read_history(since: str | None = None) -> str:
    cmd = ["git", "log", "--reverse", "--format=@@@%h|%as|%s", "-p", "-U0"]
    if since:
        cmd.append(f"--since={since}")
    cmd += ["--", TENANT_PATH]
    return subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    changes = annotate(find_changes(parse_log(read_history())))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(changes)
    counts = Counter((c["change_kind"], c["same_base_name"]) for c in changes)
    print(f"{len(changes)} changes -> {out}")
    print(f"{'change_kind':<22}{'same_base_name':<16}count")
    for (k, s), n in sorted(counts.items()):
        print(f"{k:<22}{s:<16}{n}")


if __name__ == "__main__":
    main()
