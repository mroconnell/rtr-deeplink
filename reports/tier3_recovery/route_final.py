"""Step 4: apply Ryan's routing rules using resolved_257_reconciled.jsonl +
coverage_257.jsonl + the existing probe-duration cache. One meeting per
government; prefers a 9-40 minute candidate, else the shortest known one.
"""
import csv
import json
from pathlib import Path
from collections import defaultdict

REPORTS = Path("reports/tier3_recovery")
RESOLVED = REPORTS / "resolved_257_reconciled.jsonl"
COVERAGE = REPORTS / "coverage_257.jsonl"
PROBE_CSV = Path("scripts/tier3_auto_transcription_queue_probe.csv")

STALE_YEARS = 2

rows = [json.loads(l) for l in RESOLVED.read_text().splitlines()]
coverage_by_gov = {}
if COVERAGE.exists():
    for l in COVERAGE.read_text().splitlines():
        c = json.loads(l)
        coverage_by_gov[c["gov_id"]] = c

probe_by_url = {}
with open(PROBE_CSV, newline="") as f:
    for r in csv.DictReader(f):
        probe_by_url[r["url"]] = r

VIEBIT = "viebit"


def duration_of(url: str):
    p = probe_by_url.get(url)
    if p and p.get("duration_seconds"):
        try:
            return float(p["duration_seconds"])
        except ValueError:
            return None
    return None


def bucket_line(row: dict) -> str:
    gov_id = row.get("gov_id")
    if not gov_id:
        return "TBD"
    cov = coverage_by_gov.get(gov_id)
    if cov and cov.get("has_page") and cov.get("stale") is False:
        return "already-covered"
    # uncovered (no page, or stale, or coverage check errored -- treat
    # coverage-check errors conservatively as "needs a look", not covered)
    if VIEBIT in row["url"].lower():
        return "viebit"
    tier = row["video_tier"]
    if tier == "2":
        return "tier2-drip"
    if tier == "3":
        return "tier3-requeue"
    if tier == "dead":
        return "dead"
    return "TBD"


for r in rows:
    r["bucket"] = bucket_line(r)

by_gov = defaultdict(list)
no_gov_rows = []
for r in rows:
    if r.get("gov_id"):
        by_gov[r["gov_id"]].append(r)
    else:
        no_gov_rows.append(r)

BUCKET_RANK = {"tier2-drip": 0, "tier3-requeue": 1, "viebit": 2, "dead": 3}

final_rows = []  # one decision per government (when gov_id known)
for gov_id, candidates in by_gov.items():
    already = [c for c in candidates if c["bucket"] == "already-covered"]
    if already:
        for c in candidates:
            c["final_action"] = "already-covered" if c is already[0] else "already-covered (duplicate line, same government)"
        final_rows.extend(candidates)
        continue

    actionable = [c for c in candidates if c["bucket"] in BUCKET_RANK]
    if not actionable:
        for c in candidates:
            c["final_action"] = c["bucket"]
        final_rows.extend(candidates)
        continue

    best_rank = min(BUCKET_RANK[c["bucket"]] for c in actionable)
    top = [c for c in actionable if BUCKET_RANK[c["bucket"]] == best_rank]

    if len(top) == 1:
        winner = top[0]
    else:
        def score(c):
            d = duration_of(c["url"])
            if d is None:
                return (2, 0)  # unknown duration, lowest priority
            if 540 <= d <= 2400:  # 9-40 minutes
                return (0, d)
            return (1, d)  # known but outside window -- prefer shorter
        top.sort(key=score)
        winner = top[0]

    for c in candidates:
        if c is winner:
            c["final_action"] = f"WINNER: {c['bucket']}"
        elif c["bucket"] == winner["bucket"]:
            c["final_action"] = f"{c['bucket']} (not chosen -- same government already covered by another candidate)"
        else:
            c["final_action"] = f"{c['bucket']} (not chosen -- a better candidate exists for this government)"
    final_rows.extend(candidates)

for r in no_gov_rows:
    r["final_action"] = "TBD (government not resolved)"
final_rows.extend(no_gov_rows)

with open(REPORTS / "final_routed_257.jsonl", "w") as f:
    for r in final_rows:
        f.write(json.dumps(r) + "\n")

from collections import Counter
print("bucket counts (all lines):", Counter(r["bucket"] for r in final_rows))
print("winners by bucket:", Counter(r["final_action"].replace("WINNER: ", "") for r in final_rows if r["final_action"].startswith("WINNER")))
print("distinct governments with an actionable winner:", sum(1 for r in final_rows if r["final_action"].startswith("WINNER")))
print(f"wrote {len(final_rows)} rows to final_routed_257.jsonl")
