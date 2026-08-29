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
from archive.utils import email as email_utils
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


async def _read_then_advance(*, cumulative_chunks_completed, cumulative_jobs_completed):
    """The old combined get_and_advance...() behaviour, as the route used
    it before WO-52 -- kept here so this test still exercises the same
    read-then-write sequence now that crud exposes the two halves
    separately."""
    previous = await crud.read_worker_report_snapshot()
    await crud.advance_worker_report_snapshot(
        cumulative_chunks_completed=cumulative_chunks_completed,
        cumulative_jobs_completed=cumulative_jobs_completed,
    )
    return previous


async def test_get_and_advance_worker_report_snapshot_diffs_against_previous():
    await _delete_snapshot()

    first_previous = await _read_then_advance(
        cumulative_chunks_completed=100, cumulative_jobs_completed=5
    )
    assert first_previous is None

    second_previous = await _read_then_advance(
        cumulative_chunks_completed=150, cumulative_jobs_completed=7
    )
    assert second_previous["cumulative_chunks_completed"] == 100
    assert second_previous["cumulative_jobs_completed"] == 5

    third_previous = await _read_then_advance(
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

    async def _fake_send(to, *, summary, previous, failures=None):
        calls.append(
            {
                "to": to,
                "summary": summary,
                "previous": previous,
                "failures": failures,
            }
        )
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
    # WO-46: the route must always pass a real list, never omit it -- an
    # omitted `failures` renders no section at all, which would make a
    # clean day and a broken digest look identical in the mail.
    assert isinstance(calls[0]["failures"], list)

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


# --- WO-46: the failure digest (2026-08-23) --------------------------------
#
# The gap this closes is real and measured, not hypothetical. A job only
# emails Ryan if it got far enough to attempt a chunk (worker/main.py's
# _send_failure_email() has one call site, reachable only from the
# report_chunk_result(success=False) paths). On 2026-08-23 the IQM2 cluster
# was ~20 jobs -- the second largest of three that day -- and sent ZERO
# emails, because every one died at re-resolve. The reasons below are the
# real literals those jobs stored.

_REAL_RESOLVE_STAGE_REASON = "No usable audio or video source was found."
_REAL_DURATION_GATE_REASON = (
    "Media duration doesn't look like a full meeting recording."
)
_REAL_CHUNK_STAGE_REASON = (
    "ffmpeg reported success but the output file isn't decodable "
    "(likely truncated/corrupt)"
)


def _failure(job_id, reason, *, slug, title, platform, source_url, done=0, total=1):
    return {
        "job_id": job_id,
        "error_message": reason,
        "chunks_completed": done,
        "total_chunks": total,
        "failed_at": None,
        "slug": slug,
        "title": title,
        "platform": platform,
        "source_url": source_url,
    }


def test_failure_digest_groups_by_reason_most_common_first(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    # Real shapes from the 2026-08-23 sweep.
    failures = [
        _failure(
            773,
            _REAL_RESOLVE_STAGE_REASON,
            slug="santa-barbara-ca-2026-08-11-regular-city-council-meeting",
            title="Regular City Council Meeting",
            platform="hyland",
            source_url="https://docs.santabarbaraca.gov/OnBaseAgendaOnline/Meetings/ViewMeeting?doctype=1&id=1184",
        ),
        _failure(
            781,
            _REAL_DURATION_GATE_REASON,
            slug="bluffton-in-2025-06-24-board-of-public-works-and-safety",
            title="Board of Public Works and Safety",
            platform="civicclerk",
            source_url="https://blufftonin.portal.civicclerk.com/event/81/media",
        ),
        _failure(
            783,
            _REAL_DURATION_GATE_REASON,
            slug="oroville-ca-2024-08-27-thompson-flat-cemetery-district-meeting",
            title="Thompson Flat Cemetery District  Meeting",
            platform="civicclerk",
            source_url="https://buttecoca.portal.civicclerk.com/event/140/media",
        ),
    ]

    out = email_utils._render_failure_digest(failures)

    assert "Failures, last 24 hours (3)" in out
    # The 2-job reason must be rendered before the 1-job reason.
    assert out.index(_REAL_DURATION_GATE_REASON.replace("'", "&#x27;")) < out.index(
        "No usable audio or video source"
    )
    # Every row carries BOTH the archive page and the real source URL --
    # the source URL is the whole point: it's what a human can open.
    assert "https://redtaperecordings.com/m/bluffton-in-2025-06-24" in out
    assert "https://blufftonin.portal.civicclerk.com/event/81/media" in out
    assert "https://docs.santabarbaraca.gov/OnBaseAgendaOnline" in out
    # The chunk counter is what distinguishes a resolve-stage rejection
    # (0/1, nothing attempted) from a real chunk failure.
    assert "chunks 0/1" in out


def test_failure_digest_includes_chunk_stage_failures_too(monkeypatch):
    """Both classes belong in one digest. The per-job emails cover only the
    chunk-stage half; this must not repeat that split."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    out = email_utils._render_failure_digest(
        [
            _failure(
                692,
                _REAL_CHUNK_STAGE_REASON,
                slug="2026-08-06-planning-commission-meeting-8-6-26",
                title="Planning Commission Meeting 8-6-26",
                platform="cablecast",
                source_url="http://portagemi.cablecast.tv/internetchannel/show/304?site=1",
            )
        ]
    )
    assert "isn&#x27;t decodable" in out or "isn't decodable" in out
    assert "chunks 0/1" in out


def test_failure_digest_says_so_when_there_were_none():
    """Silence must never be the only signal -- same reasoning as this
    report sending daily even on a quiet day."""
    out = email_utils._render_failure_digest([])
    assert "Failures, last 24 hours" in out
    assert "None" in out


def test_failure_digest_truncates_a_bad_day_and_says_how_many_it_dropped():
    """The 2026-08-23 Cablecast cluster was 33 jobs in one day. A digest
    that silently shows the first N would understate exactly the day it
    matters most."""
    failures = [
        _failure(
            1000 + i,
            _REAL_CHUNK_STAGE_REASON,
            slug=f"page-{i}",
            title=f"Meeting {i}",
            platform="cablecast",
            source_url=f"https://example.cablecast.tv/show/{i}",
        )
        for i in range(email_utils.MAX_FAILURES_LISTED + 7)
    ]
    out = email_utils._render_failure_digest(failures)
    assert f"Failures, last 24 hours ({email_utils.MAX_FAILURES_LISTED + 7})" in out
    assert "and 7 more not listed" in out


def test_failure_digest_survives_a_page_with_no_title():
    """A page ingested without a title is a real, confirmed shape in this
    archive (see the PrimeGov untitled-page entry) -- it must not blank out
    a whole row in the mail."""
    out = email_utils._render_failure_digest(
        [
            _failure(
                1,
                _REAL_RESOLVE_STAGE_REASON,
                slug="some-slug",
                title=None,
                platform="iqm2",
                source_url="https://example.iqm2.com/Citizens/Detail_LegiFile.aspx?ID=1",
            )
        ]
    )
    assert "some-slug" in out


# --- WO-52: a failed send must not consume the day's snapshot -------------
#
# Real occurrence, 2026-08-23: a send failed on an invalid recipient (Resend
# 422 -- an empty `to`), and the very next report 35 seconds later read
# "Chunks completed 0" against a true figure of ~488, because the failed
# attempt had already advanced the snapshot it diffed against. The number was
# silently wrong rather than obviously missing, which is what makes this worth
# a regression test rather than a one-line fix and a shrug.


async def test_failed_send_leaves_the_snapshot_untouched(monkeypatch):
    await _delete_snapshot()

    # Seed a known snapshot so there is a real reference point to protect.
    await crud.advance_worker_report_snapshot(
        cumulative_chunks_completed=1000, cumulative_jobs_completed=100
    )
    before = await crud.read_worker_report_snapshot()

    async def _fake_send_failing(to, *, summary, previous, failures=None):
        return False

    monkeypatch.setattr(
        archive.main.email_utils, "send_worker_daily_report", _fake_send_failing
    )
    resp = client.get(
        "/internal/send-worker-daily-report",
        params={"to": "ops@example.com"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["sent"] is False

    after = await crud.read_worker_report_snapshot()
    assert after["cumulative_chunks_completed"] == before["cumulative_chunks_completed"]
    assert after["cumulative_jobs_completed"] == before["cumulative_jobs_completed"]
    assert after["recorded_at"] == before["recorded_at"]


async def test_successful_send_does_advance_the_snapshot(monkeypatch):
    """Positive control: the fix must not stop the snapshot advancing on a
    real send, or every report after it reports a runaway delta."""
    await _delete_snapshot()
    await crud.advance_worker_report_snapshot(
        cumulative_chunks_completed=1000, cumulative_jobs_completed=100
    )
    before = await crud.read_worker_report_snapshot()

    async def _fake_send_ok(to, *, summary, previous, failures=None):
        return True

    monkeypatch.setattr(
        archive.main.email_utils, "send_worker_daily_report", _fake_send_ok
    )
    resp = client.get(
        "/internal/send-worker-daily-report",
        params={"to": "ops@example.com"},
        headers=_HEADERS,
    )
    assert resp.json()["sent"] is True

    after = await crud.read_worker_report_snapshot()
    assert after["cumulative_chunks_completed"] != before["cumulative_chunks_completed"]


async def test_the_delta_survives_a_failed_send_and_lands_on_the_next_one(monkeypatch):
    """The point of the fix, end to end: after a failed send, the NEXT
    report must still diff against the original reference point rather than
    reporting zero. This is the exact shape of the live incident."""
    await _delete_snapshot()
    await crud.advance_worker_report_snapshot(
        cumulative_chunks_completed=1000, cumulative_jobs_completed=100
    )

    seen = []

    async def _fail_then_succeed(to, *, summary, previous, failures=None):
        seen.append(previous)
        return len(seen) > 1  # first call fails, second succeeds

    monkeypatch.setattr(
        archive.main.email_utils, "send_worker_daily_report", _fail_then_succeed
    )
    for _ in range(2):
        client.get(
            "/internal/send-worker-daily-report",
            params={"to": "ops@example.com"},
            headers=_HEADERS,
        )

    # Both attempts saw the SAME reference point -- pre-fix, the second would
    # have diffed against what the first attempt wrote, yielding a zero delta.
    assert seen[0]["cumulative_chunks_completed"] == 1000
    assert seen[1]["cumulative_chunks_completed"] == 1000


def _summary(*, active_jobs: int, cumulative_chunks: int) -> dict:
    return {
        "active_jobs": active_jobs,
        "remaining_chunks_in_active_jobs": 0,
        "cumulative_chunks_completed_all_time": cumulative_chunks,
        "cumulative_jobs_completed_all_time": 0,
        "jobs_completed_last_24h": 0,
        "segments_added_last_24h": 0,
        "backlog_no_transcript": 0,
        "tier3_queue_remaining": 0,
    }


async def test_daily_report_warns_when_chunks_are_flat_with_active_jobs(monkeypatch):
    """The dead-worker-pool signal (2026-08-24 incident, BACKLOG_DONE.md):
    cumulative_chunks_completed_all_time not moving while active_jobs > 0
    is the one number that separated a real outage from healthy pacing."""
    captured = {}

    async def _fake_send(to, subject, html, *, cc=""):
        captured["html"] = html
        return True

    monkeypatch.setattr(email_utils, "_send", _fake_send)

    await email_utils.send_worker_daily_report(
        "ops@example.com",
        summary=_summary(active_jobs=10, cumulative_chunks=4028),
        previous={"cumulative_chunks_completed": 4028},
    )
    assert "stalled or dead" in captured["html"]


async def test_daily_report_no_warning_when_chunks_are_moving(monkeypatch):
    captured = {}

    async def _fake_send(to, subject, html, *, cc=""):
        captured["html"] = html
        return True

    monkeypatch.setattr(email_utils, "_send", _fake_send)

    await email_utils.send_worker_daily_report(
        "ops@example.com",
        summary=_summary(active_jobs=10, cumulative_chunks=4100),
        previous={"cumulative_chunks_completed": 4028},
    )
    assert "stalled or dead" not in captured["html"]


async def test_daily_report_no_warning_when_no_active_jobs(monkeypatch):
    """Zero chunks completed with zero active jobs is just an idle queue,
    not a stalled pool -- the warning is specifically about looking busy
    while making no progress."""
    captured = {}

    async def _fake_send(to, subject, html, *, cc=""):
        captured["html"] = html
        return True

    monkeypatch.setattr(email_utils, "_send", _fake_send)

    await email_utils.send_worker_daily_report(
        "ops@example.com",
        summary=_summary(active_jobs=0, cumulative_chunks=4028),
        previous={"cumulative_chunks_completed": 4028},
    )
    assert "stalled or dead" not in captured["html"]
