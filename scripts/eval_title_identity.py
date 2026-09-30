#!/usr/bin/env python3
"""Measure `app/utils/title_identity.classify_title` against real labels.

Offline: reads local CSVs only, no network, no database.

Three questions, each one table in the report:

1. Archive pages (all real meetings): how often does the classifier say
   "meeting" and return the page's own `gov_id`?
2. The 2026-09-30 census hand-read: of the proposals a person rejected,
   how many does it catch; of the ones a person accepted, how many does it
   contradict?
3. All census list titles: what share does it settle at high confidence
   (what a model no longer has to read)?

Inputs (defaults are the rtr-business worktree that produced them):
  --inventory   inputs_meeting_inventory.csv (meeting_name, gov_id, ...)
  --census-dir  shared_station_census_2026-09-30 (bodies.csv, stations.csv,
                proposed_*.csv, run2/)
  --apply-dir   folder holding the two apply_shared_station_census_*.py
                scripts, whose REJECT dicts are the hand-read rejects

Usage:
  .venv/bin/python scripts/eval_title_identity.py --out reports/title_identity_eval_2026-09-30
"""

from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.utils import title_identity as ti  # noqa: E402
from app.utils.gov_registry import registry  # noqa: E402

csv.field_size_limit(10**9)

DEFAULT_RESEARCH = Path(
    "/Users/mroconnell/Documents/rtr-business/.claude/worktrees/"
    "502-errors-instance-crashes-d49b54/research"
)

# Reject reasons that say "this list is not a meeting at all". Every other
# reject says "a meeting, but not this government".
_NON_MEETING_REASON = re.compile(
    r"show|tour|town hall|outreach|programs|tourism|parent meetings|"
    r"neighborhood meetings|annual meeting|recap|caucus|not a meeting body",
    re.I,
)


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(path: Path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _state_of(gov_id: str) -> str:
    g = registry.government_for_id(gov_id)
    return (g.state or "").upper() if g else ""


def _station_context(station_row):
    known = [g for g in (station_row.get("gov_ids") or "").split(";") if g]
    states = {_state_of(g) for g in known if g.startswith("us:")}
    states.discard("")
    state = next(iter(states)) if len(states) == 1 else None
    key = station_row["station_key"]
    handle = key.split(":", 1)[1] if key.startswith("yt:") else None
    return known, state, handle


def _pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def eval_inventory(path: Path, limit=None):
    rows = _rows(path)
    if limit:
        rows = rows[:limit]
    out = {}
    detail = []
    for scen in ("state_only", "state_and_known_gov"):
        c = collections.Counter()
        for r in rows:
            gid = r["gov_id"]
            title = r["meeting_name"]
            if not title:
                c["no_title"] += 1
                continue
            state = _state_of(gid) or None
            known = [gid] if scen == "state_and_known_gov" else None
            v = ti.classify_title(
                title,
                channel_name=r.get("video_channel") or None,
                station_state=state,
                known_gov_ids=known,
            )
            us = gid.startswith("us:")
            grp = "us" if us else ("rtr" if gid.startswith("rtr:") else "other")
            c[f"{grp}:n"] += 1
            c[f"{grp}:meeting_{v.meeting}"] += 1
            if v.meeting is False and v.confidence == ti.HIGH:
                c[f"{grp}:meeting_false_high"] += 1
            if v.meeting is None and ti.NO_EVIDENCE_REASON in v.reasons:
                c[f"{grp}:no_evidence"] += 1
            if v.meeting is True:
                c[f"{grp}:meeting_true_{v.confidence}"] += 1
            if v.gov_id:
                c[f"{grp}:gov_returned"] += 1
                c[f"{grp}:gov_returned_{v.identity_confidence}"] += 1
                if v.gov_id == gid:
                    c[f"{grp}:gov_same_{v.identity_confidence}"] += 1
                    c[f"{grp}:gov_same"] += 1
                else:
                    c[f"{grp}:gov_different"] += 1
                    if scen == "state_only" and grp == "us":
                        detail.append(
                            dict(
                                title=title,
                                true=gid,
                                got=v.gov_id,
                                why=";".join(v.reasons),
                            )
                        )
            else:
                c[f"{grp}:gov_blank"] += 1
            if v.meeting is True and v.gov_id == gid and v.confidence == ti.HIGH:
                c[f"{grp}:settled_high_right"] += 1
            if v.meeting is False:
                detail.append(
                    dict(
                        title=title,
                        true=gid,
                        got="MEETING=False",
                        why=";".join(v.reasons),
                    )
                )
        out[scen] = c
    return out, detail


def build_labeled(research: Path, apply_dir: Path):
    """Hand-read proposals from both census runs, each labeled accept,
    reject-not-a-meeting, reject-wrong-government, or held (dropped)."""
    census = research / "shared_station_census_2026-09-30"
    rej1 = _load(apply_dir / "apply_shared_station_census_2026-09-30.py").REJECT
    rej2 = _load(
        apply_dir / "apply_shared_station_census_run2_2026-09-30.py"
    ).base.REJECT
    items = []
    for run, folder, rej, stn in (
        ("run1", census, rej1, "stations.csv"),
        ("run2", census / "run2", rej2, "stations_run.csv"),
    ):
        stations = {r["station_key"]: r for r in _rows(folder / stn)}
        bodies = {}
        for r in _rows(folder / "bodies.csv"):
            bodies[(r["station_key"], r["title"])] = r
        props = [
            p
            for p in _rows(folder / "proposed_row_updates.csv")
            if p["archive_pages"] == "0"
        ]
        cands = [
            dict(gov_id=p["gov_id"], title=p["body"], station_key=p["station_key"])
            for p in props
        ]
        for p in _rows(folder / "proposed_leads.csv"):
            m = re.search(r"playlist '(.*)' on shared channel (\S+?);", p["note"])
            if not m:
                m = re.search(r"'(.*)' on (\S+?);", p["note"])
            if not m:
                continue
            cands.append(
                dict(gov_id=p["gov_id"], title=m.group(1), station_key=m.group(2))
            )
        seen = set()
        for c in cands:
            k = (c["gov_id"], c["title"], c["station_key"])
            if k in seen:
                continue
            seen.add(k)
            reason = rej.get((c["gov_id"], c["title"])) or rej.get((c["gov_id"], None))
            if reason and reason.startswith("hold"):
                label = "held"
            elif reason:
                label = (
                    "reject_non_meeting"
                    if _NON_MEETING_REASON.search(reason)
                    else "reject_wrong_gov"
                )
            else:
                label = "accept"
            st = stations.get(c["station_key"])
            known, state, handle = _station_context(st) if st else ([], None, None)
            b = bodies.get((c["station_key"], c["title"]), {})
            channel_name = b.get("site_or_channel") or None
            items.append(
                dict(
                    c,
                    run=run,
                    label=label,
                    reason=reason or "",
                    known=known,
                    state=state,
                    handle=handle,
                    channel_name=channel_name,
                )
            )
    return items


def eval_labeled(items):
    rows = []
    for it in items:
        v = ti.classify_title(
            it["title"],
            channel_name=it["channel_name"],
            channel_handle=it["handle"],
            station_state=it["state"],
            known_gov_ids=it["known"],
        )
        rows.append(dict(it, v=v))
    return rows


def eval_census_titles(census: Path):
    """Run every census list title; compare with the census script's own
    off_mission flag (a script guess, NOT a hand-read label)."""
    c = collections.Counter()
    samples = collections.defaultdict(list)
    for folder, stn in (
        (census, "stations.csv"),
        (census / "run2", "stations_run.csv"),
    ):
        stations = {r["station_key"]: r for r in _rows(folder / stn)}
        for r in _rows(folder / "bodies.csv"):
            st = stations.get(r["station_key"])
            known, state, handle = _station_context(st) if st else ([], None, None)
            v = ti.classify_title(
                r["title"],
                channel_name=r.get("site_or_channel") or None,
                channel_handle=handle,
                station_state=state,
                known_gov_ids=known,
            )
            c["titles"] += 1
            if v.meeting is not None and v.meeting_confidence == ti.HIGH:
                c["meeting_question_settled_high"] += 1
            if v.gov_id and v.identity_confidence == ti.HIGH:
                c["identity_settled_high"] += 1
            if v.meeting is True:
                c["says_meeting"] += 1
            census_off = r["off_mission"] == "yes"
            if v.meeting is None and ti.NO_EVIDENCE_REASON in v.reasons:
                grp = "no_evidence"
            elif v.meeting is False and v.confidence == ti.HIGH:
                grp = "settled_no"
            elif v.meeting is True and v.confidence == ti.HIGH and v.gov_id:
                grp = "settled_yes_with_government"
            elif v.meeting is True and v.confidence == ti.HIGH:
                grp = "meeting_yes_government_blank"
            elif v.meeting is True:
                grp = "meeting_yes_not_high"
            else:
                grp = "unsettled"
            c[grp] += 1
            c[f"{grp}|census_off={census_off}"] += 1
            if len(samples[f"{grp}|census_off={census_off}"]) < 400:
                samples[f"{grp}|census_off={census_off}"].append(
                    dict(
                        title=r["title"],
                        census_gov=r["gov_id"],
                        got=v.gov_id,
                        station=r["station_key"],
                        why=";".join(v.reasons),
                    )
                )
            if v.gov_id and r["gov_id"]:
                c["both_have_gov"] += 1
                c["both_same_gov"] += int(v.gov_id == r["gov_id"])
    return c, samples


def report(args):
    research = Path(args.research)
    census = research / "shared_station_census_2026-09-30"
    inv_path = (
        Path(args.inventory)
        if args.inventory
        else census / "inputs_meeting_inventory.csv"
    )
    apply_dir = Path(args.apply_dir) if args.apply_dir else research
    lines = []
    w = lines.append

    inv, inv_detail = eval_inventory(inv_path)
    w("# Title identity rules: measured results")
    w("")
    w("All numbers come from `scripts/eval_title_identity.py`. No network was used.")
    w("")
    w("## 1. Archive pages (every one is a real meeting)")
    w("")
    w(
        "Question: for a US Archive page, does the classifier say it is a meeting, and does it return the page's own government?"
    )
    w(
        "The second run gives the classifier the page's state only. The third run also tells it the page's own government is one the station carries (an upper bound, because a real station lists other governments too)."
    )
    w("")
    w("| Result | State only | State and known government |")
    w("|---|---|---|")
    a, b = inv["state_only"], inv["state_and_known_gov"]
    n = a["us:n"]

    def row(label, key, denom_key="us:n"):
        w(
            f"| {label} | {a[key]} ({_pct(a[key], a[denom_key])}) | {b[key]} ({_pct(b[key], b[denom_key])}) |"
        )

    w(f"| US pages scored | {n} | {b['us:n']} |")
    row("Says meeting", "us:meeting_True")
    row("Says meeting at high confidence", "us:meeting_true_high")
    row("Says not a meeting (wrong)", "us:meeting_False")
    row("Says not a meeting at high confidence (wrong)", "us:meeting_false_high")
    row("Cannot tell (blank)", "us:meeting_None")
    row("Of the blanks: no body, meeting or non-meeting word at all", "us:no_evidence")
    row("Returns a government", "us:gov_returned")
    row("Government matches the page", "us:gov_same")
    row("Government differs from the page", "us:gov_different")
    row("No government returned", "us:gov_blank")
    row("Settled: meeting, high confidence, right government", "us:settled_high_right")
    w("")
    for grp, label in (
        ("rtr", "minted rtr: special-district pages"),
        ("other", "non-US pages"),
    ):
        if a[f"{grp}:n"]:
            w(
                f"Not in the table above: {a[f'{grp}:n']} {label}. "
                f"Says meeting: {a[f'{grp}:meeting_True']}. "
                f"(An rtr: page is filed under its local government by Ryan's rule, so its id is not compared.)"
            )
    w("")
    for tier in ("high", "medium", "low"):
        r_ = a[f"us:gov_returned_{tier}"]
        w(
            f"Government precision at {tier} identity confidence (state only): {_pct(a[f'us:gov_same_{tier}'], r_)} ({a[f'us:gov_same_{tier}']} of {r_})."
        )
    w("")
    gov_ret = a["us:gov_returned"]
    w(
        f"Precision of the government when one is returned (state only): {_pct(a['us:gov_same'], gov_ret)} ({a['us:gov_same']} of {gov_ret})."
    )
    w("")

    items = eval_labeled(build_labeled(research, apply_dir))
    lab = collections.Counter(i["label"] for i in items)
    w("## 2. Census hand-read (2026-09-30, both runs)")
    w("")
    w(
        "Question: on the proposals for governments with no Archive page, how does the classifier compare with what a person decided?"
    )
    w("Held items are left out: a person did not decide them.")
    w("")
    w("| Hand-read label | Count |")
    w("|---|---|")
    for k in ("accept", "reject_non_meeting", "reject_wrong_gov", "held"):
        w(f"| {k} | {lab[k]} |")
    w("")

    def verdict_bucket(i):
        v = i["v"]
        lbl = i["label"]
        if lbl == "reject_non_meeting":
            if v.meeting is False:
                return "caught"
            if v.meeting is None or v.confidence == ti.LOW:
                return "unsettled (goes to a model)"
            return "missed (says meeting)"
        if lbl == "reject_wrong_gov":
            if v.meeting is False or v.gov_id != i["gov_id"]:
                return "caught (no government, or a different one)"
            return "missed (returns the rejected government)"
        if lbl == "accept":
            if v.meeting is False:
                return "contradicts (says not a meeting)"
            if v.meeting is True and v.gov_id and v.gov_id != i["gov_id"]:
                return "contradicts (different government)"
            if v.meeting is True and v.gov_id == i["gov_id"]:
                return "agrees (meeting, same government)"
            return "unsettled (goes to a model)"

    tab = collections.defaultdict(collections.Counter)
    for i in items:
        if i["label"] != "held":
            tab[i["label"]][verdict_bucket(i)] += 1
    w("| Hand-read label | Classifier result | Count |")
    w("|---|---|---|")
    for lbl in ("reject_non_meeting", "reject_wrong_gov", "accept"):
        for k, v in sorted(tab[lbl].items()):
            w(f"| {lbl} | {k} | {v} |")
    w("")
    # yes/no precision and recall over: accepts (meeting) + Archive positives + non-meeting rejects
    tp = fp = fn_unsettled = 0
    tn = fn = 0
    nm_total = lab["reject_non_meeting"]
    for i in items:
        v = i["v"]
        if i["label"] == "accept":
            if v.meeting is True:
                tp += 1
            elif v.meeting is False:
                fn += 1
            else:
                fn_unsettled += 1
        elif i["label"] == "reject_non_meeting":
            if v.meeting is True:
                fp += 1
            elif v.meeting is False:
                tn += 1
    inv_tp = a["us:meeting_True"]
    inv_fn = a["us:meeting_False"]
    inv_blank = a["us:meeting_None"]
    w("## 3. Meeting yes/no: precision and recall")
    w("")
    w(
        "Actual meetings here are the Archive pages plus the accepted proposals. Actual non-meetings are the hand-rejected non-meeting proposals, so that side is a small sample."
    )
    w("")
    T = tp + inv_tp
    F = fn + inv_fn
    U = fn_unsettled + inv_blank
    w("| Measure | Count | Share |")
    w("|---|---|---|")
    w(f"| Actual meetings scored | {T + F + U} | |")
    w(f"| Said meeting | {T} | {_pct(T, T + F + U)} recall |")
    w(f"| Said not a meeting (wrong) | {F} | {_pct(F, T + F + U)} |")
    w(f"| Cannot tell | {U} | {_pct(U, T + F + U)} |")
    w(f"| Actual non-meetings scored | {nm_total} | |")
    w(f"| Said not a meeting | {tn} | {_pct(tn, nm_total)} recall |")
    w(f"| Said meeting (wrong) | {fp} | {_pct(fp, nm_total)} |")
    w(f"| Cannot tell | {nm_total - tn - fp} | {_pct(nm_total - tn - fp, nm_total)} |")
    w(f"| Precision of yes | {T} of {T + fp} | {_pct(T, T + fp)} |")
    w("")

    cen, samples = eval_census_titles(census)
    w("## 4. What a model no longer has to read (all census list titles)")
    w("")
    w(
        f"Question: of {cen['titles']} playlist, gallery and channel titles from both census runs, how many does the classifier settle at high confidence?"
    )
    w(
        "The second column counts titles the census script also flagged off-mission (a script guess, not a hand-read label)."
    )
    w("")
    w("| Result | Count of titles | Of which census script said off-mission |")
    w("|---|---|---|")
    order = [
        ("settled_no", "Settled: not a meeting (high)"),
        ("settled_yes_with_government", "Settled: meeting and government (high)"),
        ("meeting_yes_not_high", "Meeting, not high confidence"),
        ("no_evidence", "Cannot tell: no body, meeting or non-meeting word at all"),
        ("unsettled", "Cannot tell: any other reason"),
    ]
    T0 = cen["titles"]
    for k, label in order:
        w(
            f"| {label} | {cen[k]} ({_pct(cen[k], T0)}) | {cen[k + '|census_off=True']} |"
        )
    settled = cen["settled_no"] + cen["settled_yes_with_government"]
    w("")
    w(
        f"Share settled completely (not a meeting, or meeting with a government) at high confidence: {settled} of {T0} ({_pct(settled, T0)})."
    )
    w(
        f"Where both the census script and the classifier name a government: {cen['both_have_gov']} titles, same government in {cen['both_same_gov']} ({_pct(cen['both_same_gov'], cen['both_have_gov'])}). The census script is itself a guess, not a label."
    )
    w("")
    w("Two narrower questions, counted on the same titles:")
    w("")
    w("| Question | Count of titles | Share |")
    w("|---|---|---|")
    w(
        f"| Meeting yes/no settled at high confidence | {cen['meeting_question_settled_high']} | {_pct(cen['meeting_question_settled_high'], T0)} |"
    )
    w(
        f"| Government named at high confidence | {cen['identity_settled_high']} | {_pct(cen['identity_settled_high'], T0)} of all titles; {_pct(cen['identity_settled_high'], cen['says_meeting'])} of the {cen['says_meeting']} titles that say meeting |"
    )
    w("")
    text = "\n".join(lines) + "\n"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(text, encoding="utf-8")
    with open(out / "inventory_disagreements.json", "w") as fh:
        json.dump(inv_detail[:3000], fh, indent=1)
    with open(out / "labeled_results.csv", "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(
            [
                "run",
                "label",
                "reason",
                "title",
                "proposed_gov_id",
                "meeting",
                "gov_id",
                "confidence",
                "why",
            ]
        )
        for i in items:
            v = i["v"]
            wr.writerow(
                [
                    i["run"],
                    i["label"],
                    i["reason"],
                    i["title"],
                    i["gov_id"],
                    v.meeting,
                    v.gov_id,
                    v.confidence,
                    ";".join(v.reasons),
                ]
            )
    import random

    rnd = random.Random(20260930)
    audit = []
    for grp in ("settled_no", "settled_yes_with_government", "no_evidence"):
        pool = samples[f"{grp}|census_off=True"] + samples[f"{grp}|census_off=False"]
        for x in rnd.sample(pool, min(40, len(pool))):
            audit.append(dict(group=grp, **x))
    with open(out / "audit_sample.json", "w") as fh:
        json.dump(audit, fh, indent=1)
    print(text)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--research", default=str(DEFAULT_RESEARCH))
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--apply-dir", default=None)
    ap.add_argument(
        "--out", default=str(ROOT / "reports" / "title_identity_eval_2026-09-30")
    )
    report(ap.parse_args())


if __name__ == "__main__":
    main()
