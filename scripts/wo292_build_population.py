#!/usr/bin/env python3
"""WO-292 population builder: 1,000 school districts for the passive
discovery v2 pilot -- 600 from the no-platform-signature pool, 400 from
the never-tested pool, each stratified proportionally by state, domain
required, BoardDocs-labelled and known-YouTube/Vimeo-channel rows and
the 6 with-a-page rows excluded (they are the step-0 vocabulary set,
not the pilot population). Deterministic (fixed seed) for reproducibility.
"""

import csv
import random

JC_PATH = "/Users/mroconnell/Documents/rtr-business/research/jurisdiction_coverage.csv"
OUT_PATH = "/Users/mroconnell/Documents/rtr-business/research/wo292_population.csv"

random.seed(292)


def load_pools():
    no_sig, never_tested = [], []
    with open(JC_PATH, newline="") as f:
        for r in csv.DictReader(f):
            gid = r.get("gov_id", "")
            if not gid.startswith("us:sd:"):
                continue
            if not r.get("domain", "").strip():
                continue
            reject = r.get("reject_reason", "").strip()
            calv = r.get("suspected_calendar_provider", "").strip().lower()
            vidv = r.get("suspected_video_provider", "").strip().lower()
            transcribed = r.get("transcribed", "").strip() == "True"
            is_boarddocs = calv == "boarddocs"
            is_known_channel = "youtube" in vidv or "vimeo" in vidv
            if transcribed or is_known_channel or is_boarddocs:
                continue
            if reject == "no-platform-signature":
                no_sig.append(r)
            elif reject == "" and calv == "" and vidv == "":
                never_tested.append(r)
    return no_sig, never_tested


def stratified_sample(pool, n):
    by_state = {}
    for r in pool:
        by_state.setdefault(r["state_or_province"], []).append(r)
    for state_rows in by_state.values():
        random.shuffle(state_rows)
    total = len(pool)
    # proportional allocation by state share, largest remainder method
    shares = {s: len(rows) / total * n for s, rows in by_state.items()}
    alloc = {s: int(v) for s, v in shares.items()}
    remainder = n - sum(alloc.values())
    # distribute remainder to states with the largest fractional part
    frac_order = sorted(shares.items(), key=lambda kv: -(kv[1] - int(kv[1])))
    for s, _ in frac_order[:remainder]:
        alloc[s] += 1
    sample = []
    for s, k in alloc.items():
        sample.extend(by_state[s][:k])
    return sample


def main():
    no_sig, never_tested = load_pools()
    print(f"eligible no-platform-signature pool: {len(no_sig)}")
    print(f"eligible never-tested pool: {len(never_tested)}")

    sample_no_sig = stratified_sample(no_sig, min(600, len(no_sig)))
    sample_never_tested = stratified_sample(never_tested, min(400, len(never_tested)))

    print(f"sampled from no-platform-signature: {len(sample_no_sig)}")
    print(f"sampled from never-tested: {len(sample_never_tested)}")

    rows = []
    for r, src in [(x, "no-platform-signature") for x in sample_no_sig] + [
        (x, "never-tested") for x in sample_never_tested
    ]:
        rows.append(
            {
                "gov_id": r["gov_id"],
                "name": r["city_name"],
                "state": r["state_or_province"],
                "population": r.get("population_estimate", ""),
                "domain": r["domain"],
                "source_pool": src,
            }
        )

    with open(OUT_PATH, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "gov_id",
                "name",
                "state",
                "population",
                "domain",
                "source_pool",
            ],
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)

    print(f"total population rows: {len(rows)}")
    from collections import Counter

    print("by source_pool:", Counter(r["source_pool"] for r in rows))
    print("by state (top 10):", Counter(r["state"] for r in rows).most_common(10))
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
