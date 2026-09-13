"""WO-338 (2026-09-13): phase 1 merge step -- the "adapt the recon-loading
step" piece of the WO-337/338 addendum ("skip phase 1 where recon_file is
present -- load the government's phase-1 record from that jsonl on disk;
rerun phase 1 only for rows with a blank recon_file or a v1-shaped
WO-273 record").

Builds one unified `research/wo338_recon.jsonl`, one v2-shaped record per
government, for `wo338_classify.py` (an otherwise-unmodified copy of
`wo325_classify.py`) to consume exactly the way it already consumes
`wo325_recon.jsonl`:

  - For a population row whose `recon_file` names an existing v2-shaped
    jsonl (anything except a blank cell or `research/wo273_recon.jsonl`
    -- see the WO-338 population split, `wo338_recon_needed.csv` vs. the
    2,179-row remainder), the matching record is looked up by `domain`
    in that source file and copied over verbatim. No network call.
  - For the remaining 646 rows, the record `wo338_recon.py` just fetched
    into `research/wo338_recon_fresh.jsonl` is used instead.

Population: `research/wo338_population.csv` (2,825 rows, the full
in-scope set: `passive_rerun_1-verifier-fix.csv` filtered to
`prior_reject_reason != no-platform-link-found`).

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo338_merge_recon.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo338_population.csv"
FRESH_RECON_JSONL = RESEARCH_DIR / "wo338_recon_fresh.jsonl"
MERGED_RECON_JSONL = RESEARCH_DIR / "wo338_recon.jsonl"

# recon_file values in the population csv that are v2-shaped and safe to
# load directly (everything actually observed in the 2,825-row population
# except the v1-shaped wo273 file and a blank cell).
V2_SOURCE_FILES = {
    "research/wo282_recon.jsonl",
    "research/wo283_recon.jsonl",
    "research/wo292_recon.jsonl",
    "research/wo320_recon.jsonl",
    "research/wo321_recon.jsonl",
    "research/wo322_recon.jsonl",
    "research/wo323_recon.jsonl",
    "research/wo324_recon.jsonl",
    "research/wo325_recon.jsonl",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_source_index(filename: str) -> dict:
    path = RESEARCH_DIR / Path(filename).name
    index = {}
    if not path.exists():
        log(f"WARNING: {path} does not exist, cannot load records from it")
        return index
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            index[rec.get("domain")] = rec
    return index


def main() -> int:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        population = list(csv.DictReader(f))
    log(f"{len(population)} governments in population")

    fresh_index = load_source_index(FRESH_RECON_JSONL.name)
    log(
        f"{len(fresh_index)} fresh (phase-1-rerun) records loaded from {FRESH_RECON_JSONL.name}"
    )

    source_indexes: dict[str, dict] = {}
    for fname in V2_SOURCE_FILES:
        source_indexes[fname] = load_source_index(fname)

    written = 0
    missing = []
    by_source_count: dict[str, int] = {}

    with open(MERGED_RECON_JSONL, "w", encoding="utf-8") as out:
        for row in population:
            domain = row["domain"]
            recon_file = row.get("recon_file", "")
            needs_fresh = (not recon_file) or recon_file == "research/wo273_recon.jsonl"

            rec = None
            source_label = ""
            if needs_fresh:
                rec = fresh_index.get(domain)
                source_label = "wo338_fresh"
            else:
                idx = source_indexes.get(recon_file)
                if idx is not None:
                    rec = idx.get(domain)
                    source_label = recon_file
                if rec is None:
                    # Stale recon_file annotation: the population csv names
                    # a v2-shaped source file that does not actually
                    # contain this domain (confirmed -- 10 such rows in the
                    # 2,825-row population, all re-reconned fresh and
                    # appended to wo338_recon_needed.csv/wo338_recon_fresh
                    # .jsonl by hand during this WO). Fall back to the
                    # fresh index rather than dropping the row.
                    rec = fresh_index.get(domain)
                    source_label = "wo338_fresh (stale recon_file fallback)"

            if rec is None:
                missing.append((domain, row.get("gov_id", ""), recon_file, needs_fresh))
                continue

            out.write(json.dumps(rec) + "\n")
            written += 1
            by_source_count[source_label] = by_source_count.get(source_label, 0) + 1

    log(f"wrote {written} of {len(population)} records to {MERGED_RECON_JSONL}")
    for k, v in sorted(by_source_count.items(), key=lambda kv: -kv[1]):
        log(f"  {v} from {k}")
    if missing:
        log(
            f"MISSING {len(missing)} records (not yet reconned, or source file lookup failed):"
        )
        for domain, gov_id, recon_file, needs_fresh in missing[:30]:
            log(
                f"  {domain} ({gov_id}) recon_file={recon_file!r} needs_fresh={needs_fresh}"
            )
        if len(missing) > 30:
            log(f"  ... and {len(missing) - 30} more")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
