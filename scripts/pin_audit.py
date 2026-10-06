"""Pin audit: run the name rules and store rules over the pins (read-only).

    python scripts/pin_audit.py --scope pilot|ambiguous|all [--seed N]
        [--out DIR] [--inventory PATH] [--known-wrong]

Writes flags.csv, disagreements.csv (one row per address) and summary.md,
plus known_wrong_recall.md with --known-wrong. It changes no store.
The rules live in pin_audit_name_rules.py and pin_audit_store_rules.py.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import pin_audit_core as core  # noqa: E402
from scripts.pin_audit_core import AuditData, Flag, Pin  # noqa: E402

RULE_MODULES = ("scripts.pin_audit_name_rules", "scripts.pin_audit_store_rules")
KNOWN_WRONG = core.AUDIT_DATA_DIR / "known_wrong.csv"
FLAG_COLUMNS = [
    "rule", "severity", "store", "host", "match", "gov_id", "gov_name", "gov_state",
    "other_gov_id", "other_name", "other_state", "other_ref", "source", "ref", "detail",
]  # fmt: skip


def load_rules() -> Tuple[List[Callable], List[str]]:
    rules: List[Callable] = []
    notes: List[str] = []
    for name in RULE_MODULES:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            notes.append(f"Rule module {name} is missing; its rules did not run.")
            print(notes[-1])
            continue
        rules.extend(getattr(mod, "RULES", []))
    return rules, notes


def run_rules(
    rules: Sequence[Callable], data: AuditData, judged: Sequence[Pin]
) -> List[Flag]:
    flags: List[Flag] = []
    for rule in rules:
        flags.extend(rule(data, judged))
    return flags


def _pin_key(p: Pin) -> Tuple[str, str, str, str, str]:
    return (p.store, p.host, p.match, p.gov_id, p.ref)


def source_group(p: Pin) -> str:
    if p.store != core.STORE_OVERRIDE:
        return "other stores"
    if "ryan_stated" in p.source:
        return "ryan_stated"
    if "step0_dns_full" in p.source or "wildcard_http_sweep_2" in p.source:
        return "name-match sources"
    return "other sources"


GROUPS = ["name-match sources", "other sources", "ryan_stated", "other stores"]
COLS = list(core.SEVERITIES) + ["no flag"]


def worst_by_pin(judged: Sequence[Pin], flags: Sequence[Flag]) -> Dict[Tuple, str]:
    rank = {s: i for i, s in enumerate(core.SEVERITIES)}
    worst: Dict[Tuple, str] = {}
    for f in flags:
        k = _pin_key(f.pin)
        if k not in worst or rank[f.severity] < rank[worst[k]]:
            worst[k] = f.severity
    return {_pin_key(p): worst.get(_pin_key(p), "no flag") for p in judged}


def md_table(header: Sequence[str], rows: Sequence[Sequence]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def severity_table(
    judged: Sequence[Pin], flags: Sequence[Flag], groups: Sequence[str]
) -> str:
    worst = worst_by_pin(judged, flags)
    counts: Dict[str, Counter] = defaultdict(Counter)
    for p in judged:
        counts[source_group(p)][worst[_pin_key(p)]] += 1
    rows = []
    for g in groups:
        c = counts[g]
        rows.append([g] + [c[x] for x in COLS] + [sum(c.values())])
    tot = [sum(r[i] for r in rows) for i in range(1, len(COLS) + 2)]
    rows.append(["Total"] + tot)
    return md_table(["Pin group"] + COLS + ["total"], rows)


def flag_row(f: Flag) -> Dict[str, str]:
    p = f.pin
    g = core.gov_info(p.gov_id)
    o = core.gov_info(f.other_gov_id) if f.other_gov_id else None
    return {
        "rule": f.rule, "severity": f.severity, "store": p.store, "host": p.host,
        "match": p.match, "gov_id": p.gov_id, "gov_name": g.name if g else "",
        "gov_state": g.state if g else "", "other_gov_id": f.other_gov_id,
        "other_name": o.name if o else "", "other_state": o.state if o else "",
        "other_ref": f.other_ref, "source": p.source, "ref": p.ref, "detail": f.detail,
    }  # fmt: skip


def write_csv(path: Path, cols: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cols))
        w.writeheader()
        w.writerows(rows)


DISAGREEMENT_COLUMNS = [
    "host", "match", "worst", "rules", "governments_claimed", "claims",
    "ryan_stated_gov", "details",
]  # fmt: skip


def _gov_label(gov_id: str) -> str:
    g = core.gov_info(gov_id)
    return f"{g.name}, {g.state}" if g else gov_id


def disagreements(data: AuditData, flags: Sequence[Flag]) -> List[Dict[str, str]]:
    """One row per address with a high or medium flag: who claims what.

    Each disagreement is flagged from every side, so flags.csv repeats it.
    This file shows it once, with every stored claim on that address. It
    names no winner: the hand check found the wrong side is often not the
    flagged pin (a stale research row or a misfiled Archive page).
    """
    rank = {s: i for i, s in enumerate(core.SEVERITIES)}
    groups: Dict[Tuple[str, str], List[Flag]] = defaultdict(list)
    for f in flags:
        if f.severity in ("high", "medium"):
            host = f.pin.host[4:] if f.pin.host.startswith("www.") else f.pin.host
            groups[(host, f.pin.match)].append(f)
    rows = []
    for (host, match), fl in groups.items():
        claims: Dict[str, Counter] = defaultdict(Counter)
        ryan = set()
        for p in data.pins_by_host.get(host, []):
            if p.match != match:
                continue
            claims[p.gov_id][p.store] += 1
            if "ryan_stated" in p.source:
                ryan.add(p.gov_id)
        for (
            f
        ) in fl:  # the pin itself (a replayed one is not in data) and R1's other side
            claims[f.pin.gov_id]
            if f.other_gov_id:
                claims[f.other_gov_id]
        rows.append({
            "host": host, "match": match,
            "worst": min((f.severity for f in fl), key=rank.__getitem__),
            "rules": " ".join(sorted({f.rule for f in fl})),
            "governments_claimed": len(claims),
            "claims": " | ".join(
                f"{_gov_label(g)} ({g}): "
                + (", ".join(f"{n} {s}" for s, n in sorted(c.items())) or "named by a flag only")
                for g, c in sorted(claims.items())
            ),
            "ryan_stated_gov": " ".join(sorted(ryan)),
            "details": " | ".join(sorted({f.detail for f in fl}))[:1000],
        })  # fmt: skip
    return sorted(rows, key=lambda r: (rank[r["worst"]], r["host"], r["match"]))


def known_wrong_replay(data: AuditData, rules: Sequence[Callable], out: Path) -> str:
    """Replay pins the repo later fixed; report how many the rules catch.
    Works on a copy of the pin lists so the main run is untouched."""
    with open(KNOWN_WRONG, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    gone = {(r["host"].strip().lower(), (r.get("match") or "").strip()) for r in rows}
    replay = []
    for i, r in enumerate(rows, 1):
        replay.append(
            Pin(
                core.STORE_OVERRIDE,
                r["host"].strip().lower(),
                (r.get("match") or "").strip(),
                r["old_gov_id"].strip(),
                source=(r.get("old_source") or "").strip(),
                ref=f"known_wrong:{r.get('commit', i)}",
            )
        )
    copy = AuditData(
        pins=[
            p for p in data.pins
            if not (p.store == core.STORE_OVERRIDE and (p.host, p.match) in gone)
        ] + replay,
        pages=data.pages,
        missing=list(data.missing),
    )  # fmt: skip
    core.build_indexes(copy)
    flags = run_rules(rules, copy, replay)
    worst = worst_by_pin(replay, flags)
    # A "note" (R6) says only that a pin is unchecked, so it is not a catch.
    cols = ["high", "medium", "low", "note or no flag"]
    tally: Dict[str, Counter] = defaultdict(Counter)
    for r, p in zip(rows, replay):
        w = worst[_pin_key(p)]
        tally[r.get("change_kind") or "unknown"][w if w in cols else cols[-1]] += 1
    body = [
        [k, sum(c.values())] + [c[x] for x in cols] for k, c in sorted(tally.items())
    ]
    body.append(
        ["Total", len(rows)]
        + [sum(r[i] for r in body) for i in range(2, 2 + len(cols))]
    )
    text = (
        "# Known wrong pins: how many the rules catch\n\n"
        "Each row is a pin the repo later corrected. It was put back as it was "
        "before the fix, with the fixed pin removed, and every rule was run on it. "
        "Each pin is counted once, under its worst flag.\n\n"
        "Caution: Archive pages and research rows written after the fix still "
        "point at the corrected government, so this measures the rules with "
        "today's evidence, not the evidence that existed when the pin was made.\n\n"
        + md_table(["Change kind", "Known wrong pins"] + cols, body)
    )
    (out / "known_wrong_recall.md").write_text(text, encoding="utf-8")
    return text


def main(argv: Sequence[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scope", choices=["pilot", "ambiguous", "all"], default="pilot")
    ap.add_argument("--seed", type=int, default=20261006)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--inventory", type=Path, default=None)
    ap.add_argument("--known-wrong", action="store_true")
    args = ap.parse_args(argv)
    out = args.out or REPO_ROOT / "reports" / f"pin_audit_{date.today().isoformat()}"
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    paths = {"inventory": args.inventory} if args.inventory else None
    data = core.load_all(paths)
    rules, notes = load_rules()
    judged = core.select_pins(data, args.scope, args.seed)
    flags = run_rules(rules, data, judged)

    write_csv(out / "flags.csv", FLAG_COLUMNS, [flag_row(f) for f in flags])
    dis = disagreements(data, flags)
    write_csv(out / "disagreements.csv", DISAGREEMENT_COLUMNS, dis)

    stores = Counter(p.store for p in judged)
    rule_counts = Counter(f.rule for f in flags)
    lines = [
        f"# Pin audit, scope: {args.scope}\n",
        f"Run on {date.today().isoformat()}, seed {args.seed}. "
        f"This run judged {len(judged)} pins. It changed nothing.\n",
        "## Pins judged, by store\n",
        md_table(["Store", "Pins judged"], sorted(stores.items())),
        "## Files not found\n",
        "\n".join(f"- {m}" for m in data.missing + notes) or "None.",
        "\n\n## Pins judged, by worst flag\n",
        "Each pin is counted once, under its worst flag.\n",
        severity_table(judged, flags, GROUPS),
        "## Control: ryan_stated pins\n",
        "Ryan checked these by hand. Many flags here would mean the rules are too loud.\n",
        severity_table(judged, flags, ["ryan_stated"]),
        "## Flags per rule\n",
        md_table(["Rule", "Flags"], sorted(rule_counts.items()))
        if rule_counts
        else "No flags.\n",
        "\n## Addresses to settle\n",
        "Each disagreement is flagged from every side, so the flag counts repeat it. "
        "disagreements.csv lists each address once, with every stored claim on it. "
        "It names no winner.\n",
        md_table(
            ["Worst flag", "Addresses"],
            [[w, sum(1 for d in dis if d["worst"] == w)] for w in ("high", "medium")],
        ),
    ]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    if args.known_wrong:
        if KNOWN_WRONG.exists():
            known_wrong_replay(data, rules, out)
        else:
            print(f"--known-wrong: {KNOWN_WRONG} not found; skipped.")
    print(f"judged {len(judged)} pins ({dict(stores)}), {len(flags)} flags, "
          f"{time.time() - t0:.1f}s -> {out}")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
