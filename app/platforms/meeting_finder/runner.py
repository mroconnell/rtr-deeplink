"""Runner (WO-1024): wires Resolve/Identity/Verdict together for one
`FinderInput`, and drives a whole input file for `scripts/meeting_finder.py`.

Entries other than `resolve` are accepted (so the CLI's `--entry` flag
takes every value docs/MEETING_FINDER.md names from day one) but produce
`OUTCOME_PHASE_NOT_BUILT` -- List, Identify, Scan, Hop and Start are wave
2's job.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .identity import check_identity
from .models import (
    OUTCOME_PHASE_NOT_BUILT,
    Candidate,
    FinderInput,
    VerdictRow,
)
from .resolve import _resolve_candidates_with_meeting
from .verdict import append_verdict, load_done


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def run_one(
    finder_input: FinderInput, *, run_id: str, max_tries: int = 6
) -> VerdictRow:
    """Run every phase WO-1024 built for one input, and return its
    `VerdictRow`. Never raises for an ordinary resolve failure -- those
    come back as a `ResolveResult.outcome`; a genuinely unexpected
    exception is left to propagate, since Verdict should never silently
    swallow a real bug."""
    if finder_input.entry != "resolve":
        return VerdictRow(
            run_id=run_id,
            input_url=finder_input.url,
            entry_phase=finder_input.entry,
            path=[finder_input.url],
            phase_reached=finder_input.entry,
            outcome=OUTCOME_PHASE_NOT_BUILT,
            identity_verdict="not-checked",
            note=f"entry={finder_input.entry!r} is not built yet (wave 2)",
            finished_at=_now_iso(),
        )

    candidates = [Candidate(url=finder_input.url, source_phase="input")]
    result, meeting = await _resolve_candidates_with_meeting(
        candidates, finder_input, max_tries=max_tries
    )
    identity = check_identity(meeting, finder_input)

    leads = []
    if result.tier == 2 and result.candidate is not None:
        leads.append({"kind": "youtube", "url": result.candidate.url})

    return VerdictRow(
        run_id=run_id,
        input_url=finder_input.url,
        entry_phase=finder_input.entry,
        path=[finder_input.url]
        + (
            [result.candidate.url]
            if result.candidate and result.candidate.url != finder_input.url
            else []
        ),
        phase_reached="resolve",
        result_url=result.video_url,
        platform=result.platform,
        tier=result.tier,
        duration_seconds=result.duration_seconds,
        outcome=result.outcome,
        identity_verdict=identity.verdict,
        identity_expected_gov_id=identity.expected_gov_id,
        identity_resolved_gov_id=identity.resolved_gov_id,
        identity_points_to=identity.points_to,
        leads=leads,
        hops=0,
        forks=0,
        fetches=1,
        note=result.note,
        finished_at=_now_iso(),
    )


async def run_inputs(
    inputs: Iterable[FinderInput],
    out_path: Path,
    *,
    max_tries: int = 6,
    concurrency: int = 1,
    run_id: Optional[str] = None,
) -> List[VerdictRow]:
    """Drive every input in `inputs`, appending a `VerdictRow` to
    `out_path` (+ its JSONL twin) as each one finishes so a rerun resumes
    (`load_done()` skips an `input_url` already in `out_path`).

    `concurrency=1` (the default) runs one input at a time -- CLAUDE.md's
    "we query sites politely" rule; a `--concurrency` above 1 is a
    deliberate opt-in the CLI exposes."""
    run_id = run_id or uuid.uuid4().hex[:12]
    done = load_done(out_path)
    todo = [i for i in inputs if i.url not in done]

    rows: List[VerdictRow] = []
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(finder_input: FinderInput) -> None:
        async with sem:
            row = await run_one(finder_input, run_id=run_id, max_tries=max_tries)
            append_verdict(out_path, row)
            rows.append(row)

    if concurrency <= 1:
        for finder_input in todo:
            await _one(finder_input)
    else:
        await asyncio.gather(*(_one(fi) for fi in todo))

    return rows
