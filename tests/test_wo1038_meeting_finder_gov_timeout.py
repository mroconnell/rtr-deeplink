"""WO-1038 addendum (Ryan, 2026-09-23): a hard per-government wall-clock
cap for Meeting Finder. Real incident: run B had two governments
(villageofallouezwi.gov, athenslibrary.org) hang 30+ minutes each in a
batch run -- confirmed the hang sits inside a SYNCHRONOUS call
(`fetch.py`'s headless-browser helper, run via `asyncio.to_thread()`),
which an ordinary `asyncio.wait_for()` can, in the worst case, itself
block on past the deadline (see `runner._run_one_with_timeout()`'s own
docstring for why it's built on `asyncio.wait()` instead).

Synthetic (per CLAUDE.md): these stub `runner.run_one()` with a
coroutine that never returns -- no network, no real Meeting Finder walk
-- to prove the driver itself can't be made to hang by a government that
never comes back, regardless of what's actually stuck inside it."""

import asyncio
import time
from pathlib import Path

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.models import FinderInput


def test_gov_timeout_abandons_a_hanging_government(monkeypatch, tmp_path: Path):
    async def fake_run_one_hangs(finder_input, **kwargs):
        await asyncio.Event().wait()  # never set -- simulates a stuck sync helper

    monkeypatch.setattr(runner, "run_one", fake_run_one_hangs)

    started = time.monotonic()
    rows = asyncio.run(
        runner.run_inputs(
            [FinderInput(url="stuck.example", entry="start")],
            tmp_path / "v.csv",
            gov_timeout_minutes=0.001,  # 0.06s -- keep the test fast
        )
    )
    elapsed = time.monotonic() - started

    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == runner.OUTCOME_INTERNAL_TIMEOUT
    assert "rerun alone" in row.try_next
    assert "internal-timeout" in row.note
    # The run must actually finish -- not hang for the life of the test
    # process. Generous margin over the 0.6s deadline for slow CI.
    assert elapsed < 10, elapsed


def test_gov_timeout_reports_partial_progress(monkeypatch, tmp_path: Path):
    """Even though the hung task is never awaited to completion, the
    timeout row still carries the real path/fetch-count reached so far --
    via the `progress` dict `run_one()` populates as soon as its `state`/
    `fetcher` exist (see that function's own docstring)."""

    class _FakeFetcher:
        fetches_used = 7

    async def fake_run_one(finder_input, *, progress=None, **kwargs):
        if progress is not None:
            state = runner._WalkState()
            state.path.append("https://stuck.example/")
            state.path.append("https://stuck.example/meetings")
            state.reach("scan")
            progress["state"] = state
            progress["fetcher"] = _FakeFetcher()
        await asyncio.Event().wait()

    monkeypatch.setattr(runner, "run_one", fake_run_one)

    rows = asyncio.run(
        runner.run_inputs(
            [FinderInput(url="stuck.example", entry="start")],
            tmp_path / "v.csv",
            gov_timeout_minutes=0.001,  # 0.06s
        )
    )
    row = rows[0]
    assert row.outcome == runner.OUTCOME_INTERNAL_TIMEOUT
    assert row.path == [
        "https://stuck.example/",
        "https://stuck.example/meetings",
    ]
    assert row.fetches == 7
    assert row.phase_reached == "scan"


def test_gov_timeout_does_not_block_other_governments(monkeypatch, tmp_path: Path):
    """A government that hangs must not hold up the rest of a
    concurrent batch -- confirmed by running one stuck government
    alongside a fast one and checking the fast one's row lands quickly,
    not only after the stuck one's own timeout."""

    async def fake_run_one(finder_input, **kwargs):
        if finder_input.url.startswith("stuck"):
            await asyncio.Event().wait()
        else:
            await asyncio.sleep(0)
        from app.platforms.meeting_finder.models import VerdictRow

        return VerdictRow(run_id="t", input_url=finder_input.url, entry_phase="start")

    monkeypatch.setattr(runner, "run_one", fake_run_one)

    started = time.monotonic()
    rows = asyncio.run(
        runner.run_inputs(
            [
                FinderInput(url="stuck.example", entry="start"),
                FinderInput(url="fast.example", entry="start"),
            ],
            tmp_path / "v.csv",
            concurrency=2,
            gov_timeout_minutes=0.001,  # 0.06s
        )
    )
    elapsed = time.monotonic() - started

    assert {row.input_url for row in rows} == {"stuck.example", "fast.example"}
    stuck_row = next(r for r in rows if r.input_url == "stuck.example")
    assert stuck_row.outcome == runner.OUTCOME_INTERNAL_TIMEOUT
    fast_row = next(r for r in rows if r.input_url == "fast.example")
    assert fast_row.outcome is None
    # Rows are appended as each government FINISHES, so the fast one
    # landing first proves it never waited behind the stuck one -- a
    # direct check, where the old `elapsed < 10` only bounded it loosely.
    assert [row.input_url for row in rows] == ["fast.example", "stuck.example"]
    assert elapsed < 10, elapsed
