"""WO-1031: back-pressure intake, the YouTube-lead outcome, the "try next"
field, and identity's empty-id case.

Synthetic (per CLAUDE.md): these exercise the runner's control logic
with stubbed phases -- no network. The outcome names and the Essex /
Pomona cases they encode come from the real 17-government review run of
2026-09-23 (see BACKLOG_DONE.md's WO-1031 entry)."""

import asyncio
from pathlib import Path

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.models import (
    OUTCOME_ACCOUNT_NOT_FOUND,
    OUTCOME_MEETING_WITHOUT_VIDEO,
    OUTCOME_YOUTUBE_LEAD_ONLY,
    Candidate,
    FinderInput,
    VerdictRow,
)


def test_youtube_lead_outranks_a_block_but_not_a_real_meeting_finding():
    # Essex, ON: a YouTube channel was found, but Verdict reported the block.
    assert (
        runner._pick_outcome(["blocked-browser-headers", OUTCOME_YOUTUBE_LEAD_ONLY])
        == OUTCOME_YOUTUBE_LEAD_ONLY
    )
    # Footer YouTube icons are everywhere: never hide meeting-without-video.
    assert (
        runner._pick_outcome([OUTCOME_YOUTUBE_LEAD_ONLY, OUTCOME_MEETING_WITHOUT_VIDEO])
        == OUTCOME_MEETING_WITHOUT_VIDEO
    )
    assert (
        runner._pick_outcome([OUTCOME_YOUTUBE_LEAD_ONLY, OUTCOME_ACCOUNT_NOT_FOUND])
        == OUTCOME_ACCOUNT_NOT_FOUND
    )


def test_every_failure_gets_a_try_next_label():
    assert runner._try_next(None, False) == ""
    for outcome in (
        OUTCOME_MEETING_WITHOUT_VIDEO,
        OUTCOME_ACCOUNT_NOT_FOUND,
        OUTCOME_YOUTUBE_LEAD_ONLY,
        "cloudflare-challenge-blocked",
        "blocked-browser-headers",
        "dns-unresolvable",
        "timeout",
    ):
        assert runner._try_next(outcome, False), outcome
    assert "budget" in runner._try_next("no-meeting-nor-video", True)
    assert "nav" in runner._try_next("no-meeting-nor-video", False)
    # An outcome nobody mapped still gets a generic, non-empty label.
    assert runner._try_next("some-new-outcome", False)


def test_identity_treats_an_empty_gov_id_as_silent(monkeypatch):
    # Pomona/Piedmont (2026-09-23): the resolver returned a non-blank tier
    # with an EMPTY gov_id, and identity reported "disagrees" with nothing.
    from app.platforms.meeting_finder import identity

    class _Match:
        tier = "unresolved"
        gov_id = ""

    class _Meeting:
        source_url = "https://reflect-pomona.cablecast.tv/internetchannel/show/322"
        jurisdiction = "Pomona"
        platform = "cablecast"
        external_id = None
        video_channel = None
        origin_host = None

    monkeypatch.setattr(identity, "resolve_government", lambda *a, **k: _Match())
    check = identity.check_identity(
        _Meeting(), FinderInput(url="pomonaca.gov", gov_id="us:place:0658072")
    )
    assert check.verdict == "silent"
    assert check.points_to is None


def test_back_pressure_stops_admitting_while_resolve_is_backed_up(
    monkeypatch, tmp_path: Path
):
    """The case back-pressure exists for: some governments finish fast
    (cheap failures) and free intake slots, while others queue for the
    one Resolve slot. Intake 4, 1 Resolve slot, max 1 waiting. Inputs:
    3 "slow" governments that need Resolve, then 10 "fast" ones that
    finish at once. Without back-pressure, the fast ones would keep
    streaming in through the freed slots; with it, admission stops once
    more than 1 government is waiting for Resolve."""
    resolve_gate = asyncio.Event()
    started = []

    class _Result:
        outcome = "no-meeting-nor-video"

    async def fake_resolve(*a, **k):
        await resolve_gate.wait()
        return _Result(), None

    async def fake_run_one(finder_input, **kwargs):
        started.append(finder_input.url)
        if finder_input.url.startswith("slow"):
            # WO-1035: `_try_resolve()` now dedupes candidates by meeting
            # key before touching the Resolve lane at all -- an empty
            # list here would short-circuit before ever reaching the
            # (mocked) `_resolve_candidates_with_meeting()`, which is not
            # what this test means to exercise. A real, non-empty
            # candidate still occupies the Resolve slot the same way.
            await runner._try_resolve(
                [Candidate(url=f"https://{finder_input.url}/meeting/1")],
                finder_input,
                runner._WalkState(),
                max_tries=1,
            )
        else:
            await asyncio.sleep(0)
        return VerdictRow(run_id="t", input_url=finder_input.url, entry_phase="start")

    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)
    monkeypatch.setattr(runner, "run_one", fake_run_one)

    async def scenario():
        inputs = [FinderInput(url=f"slow{i}.example") for i in range(3)] + [
            FinderInput(url=f"fast{i}.example") for i in range(10)
        ]
        task = asyncio.create_task(
            runner.run_inputs(
                inputs,
                tmp_path / "v.csv",
                concurrency=4,
                resolve_slots=1,
                max_waiting=1,
            )
        )
        await asyncio.sleep(0.5)
        started_while_blocked = len(started)
        resolve_gate.set()
        rows = await task
        return started_while_blocked, rows

    started_while_blocked, rows = asyncio.run(scenario())
    assert len(rows) == 13
    # The 3 slow ones + the first fast one fill the intake; then 2 slow
    # governments wait for Resolve (> max_waiting=1), so no further fast
    # ones are admitted even though the first fast one freed its slot.
    assert started_while_blocked == 4, started_while_blocked
    assert runner._LANES.get() is None  # lanes don't leak past run_inputs


def test_sequential_runs_skip_lanes(monkeypatch, tmp_path: Path):
    seen = []

    async def fake_run_one(finder_input, **kwargs):
        seen.append(runner._LANES.get())
        return VerdictRow(run_id="t", input_url=finder_input.url, entry_phase="start")

    monkeypatch.setattr(runner, "run_one", fake_run_one)
    asyncio.run(
        runner.run_inputs(
            [FinderInput(url="a.example"), FinderInput(url="b.example")],
            tmp_path / "v.csv",
            concurrency=1,
        )
    )
    assert seen == [None, None]
