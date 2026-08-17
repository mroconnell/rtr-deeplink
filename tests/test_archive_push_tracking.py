"""Tests for app/main.py's durable Archive-push tracking: _push_and_track(),
_sweep_pending_archive_pushes(), and GET /admin/sweep-pending-pushes.

Built alongside the fix for a real bug: a fire-and-forget BackgroundTasks
push to the Archive could be silently lost if the resolver process
restarted between the response returning and the task actually running,
with zero log trace of the loss (reported live by a user 2026-08-10 --
see BACKLOG_DONE.md). archive_client.push() itself is monkeypatched
throughout -- these tests are about the tracking/retry wiring around it,
not the real HTTP call (already covered by app/archive_client.py's own
usage elsewhere).
"""

from fastapi.testclient import TestClient

import app.main
from app.db import crud

client = TestClient(app.main.app)


async def _log(url_suffix: str, *, transcript_found: bool = True) -> int:
    url = f"https://example.granicus.com/player/clip/push-tracking-{url_suffix}"
    return await crud.log_resolution(
        input_url=url,
        input_url_normalized=url,
        input_platform="granicus",
        status="success",
        transcript_found=transcript_found,
        segment_count=1 if transcript_found else 0,
        resolved_payload={
            "segments": [{"start": 0, "end": 1, "text": "hi"}]
            if transcript_found
            else [],
            "agenda_items": [],
        },
    )


async def test_push_and_track_marks_pushed_on_success(monkeypatch):
    async def _fake_push(payload, normalized):
        return True

    monkeypatch.setattr(app.main.archive_client, "push", _fake_push)

    resolution_id = await _log("success")
    await app.main._push_and_track(resolution_id, {}, "https://example.com")

    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id not in [p["resolution_id"] for p in pending]


async def test_push_and_track_records_failure_on_unsuccessful_push(monkeypatch):
    async def _fake_push(payload, normalized):
        return False

    monkeypatch.setattr(app.main.archive_client, "push", _fake_push)

    resolution_id = await _log("failure")
    await app.main._push_and_track(resolution_id, {}, "https://example.com")

    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    match = [p for p in pending if p["resolution_id"] == resolution_id]
    assert len(match) == 1
    assert match[0]["attempts"] == 1


async def test_sweep_retries_every_pending_push_and_returns_what_it_found(monkeypatch):
    pushed_urls = []

    async def _fake_push(payload, normalized):
        pushed_urls.append(normalized)
        return True

    monkeypatch.setattr(app.main.archive_client, "push", _fake_push)
    # A row logged mid-test is well within the real grace period (the
    # sweep must not race a fresh row's still-in-flight fast-path push) --
    # zero it out here so this test can see the row as a candidate.
    monkeypatch.setattr(app.main, "ARCHIVE_PUSH_RETRY_AFTER_MINUTES", 0)

    resolution_id = await _log("sweep")
    retried = await app.main._sweep_pending_archive_pushes()

    assert resolution_id in [r["resolution_id"] for r in retried]
    assert any(url.endswith("push-tracking-sweep") for url in pushed_urls)

    # And it's no longer pending after a successful sweep.
    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id not in [p["resolution_id"] for p in pending]


async def test_sweep_leaves_a_failed_push_pending_for_next_time(monkeypatch):
    async def _fake_push(payload, normalized):
        return False

    monkeypatch.setattr(app.main.archive_client, "push", _fake_push)

    resolution_id = await _log("sweep-fail")
    await app.main._sweep_pending_archive_pushes()

    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id in [p["resolution_id"] for p in pending]


def test_sweep_endpoint_rejects_missing_token():
    response = client.get("/admin/sweep-pending-pushes")
    assert (
        response.status_code == 404
    )  # not 401/403 -- matches every other /admin/* and /internal/* route


def test_sweep_endpoint_rejects_wrong_token():
    response = client.get("/admin/sweep-pending-pushes", params={"token": "wrong"})
    assert response.status_code == 404


async def test_sweep_endpoint_retries_and_reports_pending_pushes(monkeypatch):
    async def _fake_push(payload, normalized):
        return True

    monkeypatch.setattr(app.main.archive_client, "push", _fake_push)
    monkeypatch.setattr(app.main, "ARCHIVE_PUSH_RETRY_AFTER_MINUTES", 0)

    resolution_id = await _log("endpoint")
    response = client.get(
        "/admin/sweep-pending-pushes", params={"token": "test-admin-token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert resolution_id in [r["resolution_id"] for r in data["retried"]]
    assert data["retried_count"] >= 1


def test_maybe_schedule_push_sweep_is_gated_and_does_not_double_schedule():
    from fastapi import BackgroundTasks

    app.main._last_push_sweep_at = None
    tasks = BackgroundTasks()
    app.main._maybe_schedule_push_sweep(tasks)
    assert len(tasks.tasks) == 1

    # Immediately after -- still within ARCHIVE_PUSH_SWEEP_INTERVAL, so a
    # second call in the same window should not schedule a second sweep
    # (the real point of the in-memory gate: a burst of concurrent
    # requests shouldn't all trigger redundant sweeps at once).
    tasks2 = BackgroundTasks()
    app.main._maybe_schedule_push_sweep(tasks2)
    assert len(tasks2.tasks) == 0
