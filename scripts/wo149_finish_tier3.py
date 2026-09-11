"""WO-149 finishing step: probe every tier-3 candidate scripts/
wo149_county_ladder_sweep.py found (rtr-business/research/
wo149_tier3_pending.csv) before any of them reach the real queue, per
docs/BREADTH_SWEEP_BRIEF.md's "probe before queue" rule and WO-144's
probe_queue_entry() helper.

This is a thin glue script on purpose (CLAUDE.md's "reuse, do not
rewrite"): it shells out to the existing `scripts/probe_tier3_queue.py`
CLI (so the probe logic, the per-host politeness gate, and the shared
sidecar CSV are the same ones every other session's tier-3 candidates
already go through), then does two things that script doesn't:

1. Writes a `probe_verdict`/`probe_reason` column onto
   `wo149_tier3_pending.csv` itself (joined from the shared sidecar by
   URL) so the WO-149 funnel report can show "rejected by probe" as its
   own row, per this WO's brief.
2. Appends every "accept"/"flag-long" verdict to the real
   `scripts/tier3_auto_transcription_queue.txt`, through
   `app.platforms.queue_probe.append_queue_line()` (WO-224) -- the same
   dedupe-checked writer every other finish script now uses, never a
   second, separately-written append path that could race it.
3. Applies the row's precomputed `pin_row` (written by wo149_county_
   ladder_sweep.py's own `tier3_pending_handler()`, same `host|match|
   gov_id|strength|source|evidence` convention as WO-147's sibling
   handler) via `app.platforms.queue_probe.write_pin_row()`/
   `parse_pin_row()` (WO-224) to `app/utils/jurisdiction_data/
   tenant_overrides.csv`, but ONLY for an accepted candidate -- a
   shared-host pin for a video the probe rejects as dead/too-short is
   never written.
4. A winning candidate whose duration is over 90 minutes goes to
   `scripts/tier3_long_meetings_deferred.txt` instead of the queue
   (WO-205/WO-212's rule, via `append_deferred_line()`) -- this script
   never did that before WO-224.

wo134_confirmed_hits_ingest.py's own `maybe_write_tenant_override()` no
longer fires for a TIER3_HANDLER-intercepted candidate (see that
function's call site) -- pinning is this finish step's job now, exactly
so a rejected video never earns one.

Usage (run after scripts/wo149_county_ladder_sweep.py has produced rows
in wo149_tier3_pending.csv; safe to re-run, both the probe sidecar and
the queue-append are dedupe-checked):
    python scripts/probe_tier3_queue.py --urls-file /tmp/wo149_tier3_urls.txt
    python scripts/wo149_finish_tier3.py
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    DEFER_OVER_SECONDS,
    TENANT_OVERRIDES_CSV,
    TIER3_LONG_MEETINGS_DEFERRED_FILE,
    TIER3_QUEUE_FILE,
    append_deferred_line,
    append_queue_line,
    cached_verdict,
    is_deferred,
    parse_pin_row,
    write_pin_row,
)

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
TIER3_PENDING_CSV = RESEARCH_DIR / "wo149_tier3_pending.csv"

CALLER = "wo149_finish_tier3"


def main() -> None:
    if not TIER3_PENDING_CSV.exists():
        print(f"No {TIER3_PENDING_CSV} -- nothing to finish.")
        return

    with TIER3_PENDING_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    if "probe_verdict" not in fieldnames:
        fieldnames = fieldnames + ["probe_verdict", "probe_reason"]

    accepted = 0
    already_queued = 0
    deferred = 0
    rejected = 0
    no_verdict = 0
    for row in rows:
        # WO-224: this script never probes itself -- it always reads
        # whatever `scripts/probe_tier3_queue.py` already wrote to the
        # shared sidecar (cached_verdict() is the one place that read
        # happens now, same as every other finish script). A candidate
        # with no sidecar row at all still needs `probe_tier3_queue.py`
        # run against it first.
        result = cached_verdict(row["meeting_url"], sidecar_path=DEFAULT_SIDECAR_PATH)
        if result is None:
            row["probe_verdict"] = ""
            row["probe_reason"] = ""
            no_verdict += 1
            continue
        row["probe_verdict"] = result.verdict
        row["probe_reason"] = result.reason or ""
        if result.verdict not in ("accept", "flag-long"):
            rejected += 1
            continue

        meeting_url = row["meeting_url"]
        source_url = row.get("source_url") or ""
        pin = parse_pin_row(row.get("pin_row", ""))

        # A duration over 90 minutes goes straight to the deferred file
        # instead of the queue (WO-205/WO-212's rule), and a candidate
        # already sitting there (a deliberate removal) never gets
        # re-queued, whatever verdict it carries now -- this script had
        # neither check before WO-224.
        if is_deferred(meeting_url, deferred_path=TIER3_LONG_MEETINGS_DEFERRED_FILE):
            continue
        duration = result.duration_seconds or 0.0
        if duration > DEFER_OVER_SECONDS:
            if append_deferred_line(
                meeting_url,
                source_url=source_url,
                gov_id=row.get("gov_id", ""),
                duration_seconds=result.duration_seconds,
                deferred_path=TIER3_LONG_MEETINGS_DEFERRED_FILE,
            ):
                deferred += 1
            continue

        queued = append_queue_line(meeting_url, source_url, queue_path=TIER3_QUEUE_FILE)
        if not queued:
            already_queued += 1
            continue
        if pin:
            write_pin_row(
                host=pin["host"],
                match=pin["match"],
                gov_id=pin["gov_id"],
                strength=pin["strength"],
                source=pin["source"],
                evidence=pin["evidence"],
                pins_path=TENANT_OVERRIDES_CSV,
            )
        accepted += 1

    with TIER3_PENDING_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    print(
        f"{len(rows)} pending candidate(s): {accepted} appended to the real queue, "
        f"{already_queued} already queued, {deferred} deferred (over 90 min), "
        f"{rejected} rejected by probe, {no_verdict} still have no probe verdict."
    )


if __name__ == "__main__":
    main()
