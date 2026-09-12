"""WO-272 Stage 2: summarize the raw probe log into the two deliverables.

Reads this session's private `wo272_probe_yield_raw.csv` (written by
`wo272_probe_first_party_paths.py`) and writes:

- `rtr-business/research/wo272_probe_yield.csv` (template, tried,
  real_hit, soft404, 404, blocked, examples).
- `app/utils/jurisdiction_data/first_party_meeting_paths.csv` (template,
  measured_yield, sample_size, measured_on) -- the probe set. NOT wired
  into the access ladder by this WO; see the module's own header comment
  and docs/investigations/url_shape_mining.md for why.

Applies one correction the raw per-row `real_hit` column does not: a 200
response under ~800 bytes is treated as a soft-404/generic-shell page
even when it happens to contain both a name-token match and a meeting
word (confirmed live during this run: several sites answer EVERY probed
path with the same ~485-500 byte generic page, which trivially contains
both signals in a shared nav/footer -- exactly the WO-260 finding that a
200 alone proves nothing, just one level stricter). This script's
`real_hit` counts are the corrected ones; the raw file keeps the
uncorrected per-row value for anyone who wants to re-derive differently.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRATCH = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/a7e73d38a61b93564"
)
RAW = SCRATCH / "wo272_probe_yield_raw.csv"

OUT_YIELD = Path(
    "/Users/mroconnell/Documents/rtr-business/research/wo272_probe_yield.csv"
)
OUT_FIRST_PARTY = (
    REPO_ROOT / "app/utils/jurisdiction_data/first_party_meeting_paths.csv"
)

MIN_REAL_BODY_LEN = 800


def corrected_real_hit(row: dict) -> bool:
    if row["outcome"] != "200":
        return False
    if row["real_hit"] not in ("True",):
        return False
    note = row.get("note") or ""
    if note.startswith("len="):
        try:
            length = int(note.split("=", 1)[1])
        except ValueError:
            length = 0
        if length < MIN_REAL_BODY_LEN:
            return False
    return True


def main():
    per_template = defaultdict(
        lambda: {
            "tried": 0,
            "real_hit": 0,
            "soft404": 0,
            "404": 0,
            "blocked": 0,
            "error": 0,
            "skipped": 0,
            "examples": [],
        }
    )

    with RAW.open(newline="") as f:
        for row in csv.DictReader(f):
            template = row["template"]
            bucket = per_template[template]
            outcome = row["outcome"]
            if outcome.startswith("skipped"):
                bucket["skipped"] += 1
                continue
            bucket["tried"] += 1
            if outcome == "200":
                if corrected_real_hit(row):
                    bucket["real_hit"] += 1
                    if len(bucket["examples"]) < 3:
                        bucket["examples"].append(row["url"])
                else:
                    bucket["soft404"] += 1
            elif outcome == "soft404":
                bucket["soft404"] += 1
            elif outcome == "404":
                bucket["404"] += 1
            elif outcome == "blocked":
                bucket["blocked"] += 1
            else:
                bucket["error"] += 1

    templates = sorted(per_template.keys(), key=lambda t: -per_template[t]["real_hit"])

    with OUT_YIELD.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            ["template", "tried", "real_hit", "soft404", "404", "blocked", "examples"]
        )
        for t in templates:
            b = per_template[t]
            writer.writerow(
                [
                    t,
                    b["tried"],
                    b["real_hit"],
                    b["soft404"],
                    b["404"],
                    b["blocked"],
                    ";".join(b["examples"]),
                ]
            )

    today = date.today().isoformat()
    with OUT_FIRST_PARTY.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["template", "measured_yield", "sample_size", "measured_on"])
        for t in templates:
            b = per_template[t]
            tried = b["tried"]
            yield_ = round(b["real_hit"] / tried, 3) if tried else 0.0
            writer.writerow([t, yield_, tried, today])

    print(f"Wrote {OUT_YIELD}")
    print(f"Wrote {OUT_FIRST_PARTY}")
    for t in templates:
        b = per_template[t]
        print(
            f"{t:30s} tried={b['tried']:3d} real_hit={b['real_hit']:3d} "
            f"soft404={b['soft404']:3d} 404={b['404']:3d} blocked={b['blocked']:3d} "
            f"error={b['error']:3d}"
        )


if __name__ == "__main__":
    main()
