"""Verdict (WO-1024): one read-only result row per input, written as it
finishes so a rerun resumes.

docs/MEETING_FINDER.md's Verdict section: "One row per input, written as
it goes, so a rerun resumes. Read-only: nothing is ingested or queued
from here." This module never calls the Archive, never writes the tier-3
queue, and never writes a `tenant_overrides.csv` pin -- it only writes
its own two output files.

Two files, same `run_id`/`input_url` key: a flat CSV (every scalar
`VerdictRow` field, `path` joined with " -> ", `leads` as a count) for a
quick read/spreadsheet, and a JSONL twin (the whole row, including the
nested `path`/`leads` lists) for anything that needs the full detail.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Set

from .models import VerdictRow

CSV_FIELDS = [
    "run_id",
    "input_url",
    "entry_phase",
    "path",
    "phase_reached",
    "result_url",
    "meeting_url",
    "meeting_title",
    "platform",
    "tier",
    "duration_seconds",
    "outcome",
    "identity_verdict",
    "identity_expected_gov_id",
    "identity_resolved_gov_id",
    "identity_points_to",
    "leads_count",
    "hops",
    "forks",
    "fetches",
    "requests_total",
    "note",
    "try_next",
    "low_confidence_reason",
    "audio_only",
    "handcheck_lead",
    "other_gov_leads_count",
    "finished_at",
]

# Kept in sync with VerdictRow's own fields (minus the fields the CSV
# flattens: `path` -> a joined string, `leads`/`other_gov_leads` -> a
# count) -- asserted at import time so a field added to one and not the
# other fails loudly in CI rather than silently dropping data from the
# CSV. `other_gov_leads`' own full detail (named place, body words, title,
# date, url, hub host) is JSONL-only, same as `leads`/`path` -- WO-1058.
_DATACLASS_FIELDS = {f.name for f in fields(VerdictRow)}
_CSV_ONLY = {"leads_count", "other_gov_leads_count"}
_DATACLASS_ONLY = {"leads", "other_gov_leads"}
assert (set(CSV_FIELDS) - _CSV_ONLY) | _DATACLASS_ONLY == _DATACLASS_FIELDS, (
    "verdict.CSV_FIELDS drifted from models.VerdictRow -- update both"
)


def _jsonl_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(csv_path.suffix + ".jsonl")


def load_done(csv_path: Path) -> Set[str]:
    """Every `input_url` already written to `csv_path` -- a rerun skips
    these. Missing file (first run) is an empty set, not an error."""
    path = Path(csv_path)
    if not path.exists():
        return set()
    done: Set[str] = set()
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("input_url")
            if url:
                done.add(url)
    return done


def append_verdict(csv_path: Path, row: VerdictRow) -> None:
    """Append one `VerdictRow` to `csv_path` (creating it with a header
    if it doesn't exist yet) and to its JSONL twin, flushing both so a
    killed run's completed rows are never lost."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not csv_path.exists()

    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "run_id": row.run_id,
                "input_url": row.input_url,
                "entry_phase": row.entry_phase,
                "path": " -> ".join(row.path),
                "phase_reached": row.phase_reached,
                "result_url": row.result_url or "",
                "meeting_url": row.meeting_url or "",
                "meeting_title": row.meeting_title or "",
                "platform": row.platform or "",
                "tier": row.tier if row.tier is not None else "",
                "duration_seconds": (
                    row.duration_seconds if row.duration_seconds is not None else ""
                ),
                "outcome": row.outcome or "",
                "identity_verdict": row.identity_verdict or "",
                "identity_expected_gov_id": row.identity_expected_gov_id or "",
                "identity_resolved_gov_id": row.identity_resolved_gov_id or "",
                "identity_points_to": row.identity_points_to or "",
                "leads_count": len(row.leads),
                "hops": row.hops,
                "forks": row.forks,
                "fetches": row.fetches,
                "requests_total": row.requests_total,
                "note": row.note,
                "try_next": row.try_next,
                "low_confidence_reason": row.low_confidence_reason,
                "audio_only": row.audio_only,
                "handcheck_lead": row.handcheck_lead,
                "other_gov_leads_count": len(row.other_gov_leads),
                "finished_at": row.finished_at,
            }
        )
        f.flush()

    jsonl_path = _jsonl_path(csv_path)
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(row), sort_keys=True))
        f.write("\n")
        f.flush()
