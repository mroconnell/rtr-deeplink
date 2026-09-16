"""WO-254: `.github/workflows/feed-tier3-transcription.yml`'s commit step
used to `git add` only `scripts/tier3_auto_transcription_queue.txt`, so
every probe row `feed_tier3_auto_transcription.py`'s `_push_if_has_video()`
wrote to the tracked sidecar CSV
(`scripts/tier3_auto_transcription_queue_probe.csv`, via
`app/platforms/queue_probe.py`'s `append_probe_row()`) sat only in the
ephemeral GitHub runner's working tree and was discarded when the job
ended -- every run, 4x/day, since the workflow started (BACKLOG.md,
filed during WO-248).

This doesn't execute the workflow (no real git/GH runner here) -- it
parses the committed YAML and asserts the commit step's shell script
actually stages both paths, the same style
`test_inbox_triage_ledger.py::test_ledger_is_excluded_from_render_build_
filters` already uses to assert a real property of a YAML config file
rather than just eyeballing it."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "feed-tier3-transcription.yml"

QUEUE_FILE_PATH = "scripts/tier3_auto_transcription_queue.txt"
PROBE_SIDECAR_PATH = "scripts/tier3_auto_transcription_queue_probe.csv"


def _advance_step_run_script() -> str:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    # YAML parses the bare key `on:` as the boolean True, not the string
    # "on" -- irrelevant here, just noting why this doesn't round-trip
    # byte-for-byte if ever dumped back out.
    steps = workflow["jobs"]["feed"]["steps"]
    for step in steps:
        if step.get("name") == "Advance queue via PR":
            return step["run"]
    raise AssertionError("no 'Advance queue via PR' step found in the workflow")


def test_advance_step_stages_both_the_queue_file_and_the_probe_sidecar():
    script = _advance_step_run_script()
    assert f"git add {QUEUE_FILE_PATH}" in script
    assert f"git add {PROBE_SIDECAR_PATH}" in script


def test_advance_step_checks_the_diff_after_staging_both_paths():
    """The no-op early-exit (`git diff --cached --quiet`) must run AFTER
    both `git add` calls, not between them -- otherwise a probe-only
    change (no queue-file change) would still get reported as "nothing to
    commit" and silently dropped, which is exactly the bug this test
    guards against."""
    script = _advance_step_run_script()
    queue_add_at = script.index(f"git add {QUEUE_FILE_PATH}")
    probe_add_at = script.index(f"git add {PROBE_SIDECAR_PATH}")
    diff_check_at = script.index("git diff --cached --quiet")
    assert queue_add_at < diff_check_at
    assert probe_add_at < diff_check_at


def test_workflow_still_runs_the_script_that_writes_the_probe_sidecar():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["feed"]["steps"]
    run_steps = [
        s.get("run", "") for s in steps if s.get("name") == "Feed the next batch"
    ]
    assert any("feed_tier3_auto_transcription.py" in s for s in run_steps)
