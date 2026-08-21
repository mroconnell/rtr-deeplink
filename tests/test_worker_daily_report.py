"""Tests for the transcription-worker daily activity report:
crud.get_transcription_queue_summary()/get_and_advance_worker_report_
snapshot() (archive/db/crud.py), and the two routes built on top of them
(archive/main.py's GET /internal/transcription-queue-stats and GET
/internal/send-worker-daily-report).

Real DB (shared SQLite fixture for the whole test session, same as every
other archive/db test -- see tests/conftest.py), only
email_utils.send_worker_daily_report mocked (no real Resend call, same
convention as tests/test_transcription_create_job_clerk_verified.py's
check_audience_membership mock).

WorkerReportSnapshot is a single global row (id=1) shared across the
whole test session -- these tests delete it before asserting "no
previous snapshot yet" behavior, and every job created here is drained
immediately after asserting on it (same convention as
tests/test_transcription_jobs.py's own _drain_job() and
test_transcription_create_job_clerk_verified.py's _drain()) so this file
doesn't leave stray active jobs behind for MAX_CONCURRENT_TRANSCRIPTION_
JOBS-sensitive tests elsewhere in the suite.
"""

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import WorkerReportSnapshot
from fastapi.testclient import TestClient

client = TestClient(archive.main.app)
_HEADERS = {"Authorization": "Bearer test-token"}


async def _delete_snapshot() -> None:
    async with async_session() as session:
        existing = await session.get(WorkerReportSnapshot, 1)
        if existing is not None:
            await session.delete(existing)
            await session.commit()


async def _create_job(external_id: str, *, total_chunks: int = 1) -> int:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    job = await crud.create_transcription_job(
        payload={
            "platform": "granicus",
            "source_url": url,
            "external_id": external_id,
            "title": "Test Meeting",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
        },
        input_url_normalized=url,
        requester_email="reporter@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900 * total_chunks,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    return job["job_id"]


async def _drain(job_id: int) -> None:
    while True:
        claim = await crud.claim_next_chunk()
        if claim is None or claim["job_id"] != job_id:
            return
        result = await crud.report_chunk_result(
            job_id, success=True, shifted_segments=[]
        )
        if result.get("status") == "completed":
            return


async def test_get_and_advance_worker_report_snapshot_diffs_against_previous():
    await _delete_snapshot()

    first_previous = await crud.get_and_advance_worker_report_snapshot(
        cumulative_chunks_completed=100, cumulative_jobs_completed=5
    )
    assert first_previous is None

    second_previous = await crud.get_and_advance_worker_report_snapshot(
        cumulative_chunks_completed=150, cumulative_jobs_completed=7
    )
    assert second_previous["cumulative_chunks_completed"] == 100
    assert second_previous["cumulative_jobs_completed"] == 5

    third_previous = await crud.get_and_advance_worker_report_snapshot(
        cumulative_chunks_completed=200, cumulative_jobs_completed=9
    )
    assert third_previous["cumulative_chunks_completed"] == 150
    assert third_previous["cumulative_jobs_completed"] == 7


async def test_queue_summary_reflects_a_freshly_created_active_job():
    before = await crud.get_transcription_queue_summary()

    job_id = await _create_job("queue-summary-1", total_chunks=3)
    try:
        after = await crud.get_transcription_queue_summary()
        assert after["active_jobs"] == before["active_jobs"] + 1
        assert (
            after["remaining_chunks_in_active_jobs"]
            == before["remaining_chunks_in_active_jobs"] + 3
        )
    finally:
        await _drain(job_id)

    drained = await crud.get_transcription_queue_summary()
    assert drained["active_jobs"] == before["active_jobs"]
    assert (
        drained["remaining_chunks_in_active_jobs"]
        == before["remaining_chunks_in_active_jobs"]
    )
    # chunks_completed is a monotonic all-time counter -- draining 3
    # chunks must raise it by exactly 3, never reset or double-count.
    assert (
        drained["cumulative_chunks_completed_all_time"]
        == before["cumulative_chunks_completed_all_time"] + 3
    )
    assert (
        drained["cumulative_jobs_completed_all_time"]
        == before["cumulative_jobs_completed_all_time"] + 1
    )


def test_transcription_queue_stats_route_requires_token():
    response = client.get(
        "/internal/transcription-queue-stats",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 404


def test_transcription_queue_stats_route_returns_expected_shape():
    response = client.get("/internal/transcription-queue-stats", headers=_HEADERS)
    assert response.status_code == 200
    body = response.json()
    for key in (
        "active_jobs",
        "remaining_chunks_in_active_jobs",
        "cumulative_chunks_completed_all_time",
        "cumulative_jobs_completed_all_time",
        "jobs_completed_last_24h",
        "segments_added_last_24h",
        "backlog_no_transcript",
        "tier3_queue_remaining",
    ):
        assert key in body
    assert isinstance(body["tier3_queue_remaining"], int)
    assert body["tier3_queue_remaining"] >= 0


def test_send_worker_daily_report_route_requires_token():
    response = client.get(
        "/internal/send-worker-daily-report",
        params={"to": "ops@example.com"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 404


async def test_send_worker_daily_report_route_sends_and_advances_snapshot(monkeypatch):
    await _delete_snapshot()

    calls = []

    async def _fake_send(to, *, summary, previous):
        calls.append({"to": to, "summary": summary, "previous": previous})
        return True

    monkeypatch.setattr(
        archive.main.email_utils, "send_worker_daily_report", _fake_send
    )

    first = client.get(
        "/internal/send-worker-daily-report",
        params={"to": "ops@example.com"},
        headers=_HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["sent"] is True
    assert len(calls) == 1
    assert calls[0]["to"] == "ops@example.com"
    assert calls[0]["previous"] is None  # snapshot was freshly deleted above

    second = client.get(
        "/internal/send-worker-daily-report",
        params={"to": "ops@example.com"},
        headers=_HEADERS,
    )
    assert second.status_code == 200
    assert len(calls) == 2
    # Second call's "previous" must be the totals the FIRST call recorded,
    # proving the snapshot actually advanced rather than staying static.
    assert calls[1]["previous"] is not None
    assert (
        calls[1]["previous"]["cumulative_chunks_completed"]
        == calls[0]["summary"]["cumulative_chunks_completed_all_time"]
    )
