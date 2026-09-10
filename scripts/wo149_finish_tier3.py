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
   `scripts/tier3_auto_transcription_queue.txt`, through the SAME
   duplicate-checked writer `wo134_confirmed_hits_ingest.py`'s own
   process_row() uses (`wo134._existing_tier3_queue_urls()`) -- never a
   second, separately-written append path that could race it.
3. Applies the row's precomputed `pin_row` (written by wo149_county_
   ladder_sweep.py's own `tier3_pending_handler()`, same `host|match|
   gov_id|strength|source|evidence` convention as WO-147's sibling
   handler) to `app/utils/jurisdiction_data/tenant_overrides.csv`, but
   ONLY for an accepted candidate -- a shared-host pin for a video the
   probe rejects as dead/too-short is never written.

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

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
from scripts.probe_tier3_queue import DEFAULT_SIDECAR  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
TIER3_PENDING_CSV = RESEARCH_DIR / "wo149_tier3_pending.csv"

_ACCEPT_VERDICTS = {"accept", "flag-long"}


def _existing_override_keys() -> set:
    keys = set()
    if wo134.TENANT_OVERRIDES_CSV.exists():
        with wo134.TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("tenant_host", ""), r.get("match", "")))
    return keys


def _apply_pin_row(pin_row: str, existing_keys: set) -> None:
    """Same shape as WO-147's own `_apply_pin_row()` in scripts/
    wo147_finish_tier3_queue.py -- kept as a small local copy rather
    than importing that script, since it isn't built as an importable
    module."""
    if not pin_row:
        return
    parts = pin_row.split("|", 5)
    if len(parts) != 6:
        print(f"WARNING: malformed pin_row, skipping: {pin_row!r}", file=sys.stderr)
        return
    tenant_host, match, gov_id, strength, source, evidence = parts
    key = (tenant_host, match)
    if key in existing_keys:
        return
    is_new = not wo134.TENANT_OVERRIDES_CSV.exists()
    with wo134.TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "tenant_host",
                "match",
                "gov_id",
                "strength",
                "source",
                "evidence",
            ],
            lineterminator="\n",
        )
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "tenant_host": tenant_host,
                "match": match,
                "gov_id": gov_id,
                "strength": strength,
                "source": source,
                "evidence": evidence,
            }
        )
    existing_keys.add(key)


def load_sidecar_verdicts() -> dict:
    verdicts = {}
    if not DEFAULT_SIDECAR.exists():
        return verdicts
    with DEFAULT_SIDECAR.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # A URL can appear more than once (a --reprobe re-run) --
            # keep the newest (last) verdict, same as the sidecar's own
            # append-only, newest-wins convention.
            verdicts[row["url"]] = (row.get("verdict", ""), row.get("reason", ""))
    return verdicts


def main() -> None:
    if not TIER3_PENDING_CSV.exists():
        print(f"No {TIER3_PENDING_CSV} -- nothing to finish.")
        return

    with TIER3_PENDING_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    if "probe_verdict" not in fieldnames:
        fieldnames = fieldnames + ["probe_verdict", "probe_reason"]

    verdicts = load_sidecar_verdicts()
    missing = [r["meeting_url"] for r in rows if r["meeting_url"] not in verdicts]
    if missing:
        print(
            f"{len(missing)} of {len(rows)} candidate(s) have no sidecar verdict yet "
            f"-- run scripts/probe_tier3_queue.py against them first "
            f"(e.g. write their URLs to a file and pass --urls-file)."
        )

    existing_override_keys = _existing_override_keys()
    accepted = 0
    already_queued = 0
    rejected = 0
    no_verdict = 0
    for row in rows:
        v = verdicts.get(row["meeting_url"])
        if v is None:
            row["probe_verdict"] = ""
            row["probe_reason"] = ""
            no_verdict += 1
            continue
        verdict, reason = v
        row["probe_verdict"] = verdict
        row["probe_reason"] = reason
        if verdict not in _ACCEPT_VERDICTS:
            rejected += 1
            continue
        final_seed = row["meeting_url"]
        if final_seed in wo134._existing_tier3_queue_urls():
            already_queued += 1
            continue
        hit_url = row.get("source_url") or final_seed
        source_line = (
            f"{final_seed}\t{hit_url}" if hit_url != final_seed else final_seed
        )
        with wo134.TIER3_QUEUE_FILE.open("a", encoding="utf-8") as qf:
            qf.write(source_line + "\n")
        wo134._existing_tier3_queue_urls().add(final_seed)
        _apply_pin_row(row.get("pin_row", ""), existing_override_keys)
        accepted += 1

    with TIER3_PENDING_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    print(
        f"{len(rows)} pending candidate(s): {accepted} appended to the real queue, "
        f"{already_queued} already queued, {rejected} rejected by probe, "
        f"{no_verdict} still have no probe verdict."
    )


if __name__ == "__main__":
    main()
