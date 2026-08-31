"""Tests for scripts/bulk_queue_transcription_backlog.py's WO-83 fix.

BACKLOG.md's "hourly transcription top-up driver has been creating zero
jobs" entry: this script's own client-side ffprobe-feasibility skip used
to happen entirely client-side, before any TranscriptionJob row existed
for the candidate, so archive/db/crud.py's
_in_auto_transcription_cooldown() (which only ever looks at
TranscriptionJob history) never engaged. Real, measured effect: the same
8 archive-stream.granicus.com candidates -- all hitting the platform's
known origin 504 ("ffprobe couldn't read the media") -- were re-selected
and re-skipped identically on every single hourly run, for 25+ sampled
hours, permanently blocking the driver from reaching further into the
backlog to find real probeable work.

The fix: an infeasible candidate now has its failure recorded via
_record_probe_failure() (POST /internal/transcription/record-probe-
failure, crud.create_failed_auto_transcription_job() under the hood --
the exact mechanism worker/main.py's own maybe_generate_auto_job()
already uses for an identical situation), which lets the escalating
cooldown finally apply. These tests mock the HTTP layer (this repo's
aiohttp version is too new for aioresponses -- see
tests/aiohttp_mock.py's own docstring -- so, following
tests/test_feed_tier3_auto_transcription.py's precedent, this monkeypatches
the module's own thin wrapper functions instead of aiohttp itself) and
exercise the pure per-candidate decision logic directly; the end-to-end
proof that a recorded failure actually removes a candidate from the next
GET /internal/transcription-backlog call is a separate, real-DB test:
tests/test_transcription_jobs.py's
test_probe_failure_recording_removes_candidate_from_next_backlog_call.
"""

import scripts.bulk_queue_transcription_backlog as mod


class _Recorder:
    """A tiny call-recording async stand-in, so a test can assert both
    whether a mocked function was called and with what arguments."""

    def __init__(self):
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _FakeResolvedMeeting:
    def __init__(self, video_url="https://example.com/v.m3u8", video_format="m3u8"):
        self.video_url = video_url
        self.video_format = video_format

    def model_dump(self):
        return {"video_url": self.video_url, "video_format": self.video_format}


# --- _record_probe_failure() ------------------------------------------------


async def test_record_probe_failure_posts_expected_body(monkeypatch):
    monkeypatch.setattr(mod, "_base_url", lambda: "https://archive.example.com")
    monkeypatch.setattr(mod, "_headers", lambda: {"Authorization": "Bearer tok"})

    captured = {}

    async def fake_request_json(session, method, url, *, label, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return {"job_id": 123, "status": "failed"}

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    page = {"slug": "example-meeting", "meeting_page_id": 42}
    await mod._record_probe_failure(
        session=None,
        page=page,
        reason="ffprobe couldn't read the media",
        requester_email="auto@example.com",
    )

    assert captured["method"] == "POST"
    assert (
        captured["url"]
        == "https://archive.example.com/internal/transcription/record-probe-failure"
    )
    assert captured["json"] == {
        "meeting_page_id": 42,
        "requester_email": "auto@example.com",
        "error_message": "ffprobe couldn't read the media",
    }


async def test_record_probe_failure_is_a_noop_without_meeting_page_id(monkeypatch):
    # An older Archive deploy that hasn't picked up the meeting_page_id
    # field on GET /internal/transcription-backlog yet -- must not send a
    # malformed request.
    called = False

    async def fake_request_json(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    await mod._record_probe_failure(
        session=None,
        page={"slug": "no-id-here"},
        reason="ffprobe couldn't read the media",
        requester_email="auto@example.com",
    )
    assert called is False


async def test_record_probe_failure_swallows_request_errors(monkeypatch):
    async def fake_request_json(*args, **kwargs):
        raise RuntimeError("HTTP 500 for record probe failure: boom")

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    # Must not raise -- a failure recording the failure shouldn't abort
    # the batch (see the function's own docstring).
    await mod._record_probe_failure(
        session=None,
        page={"slug": "boom", "meeting_page_id": 7},
        reason="ffprobe couldn't read the media",
        requester_email="auto@example.com",
    )


# --- _process_candidate() ---------------------------------------------------


async def test_process_candidate_records_probe_failure_for_infeasible_candidate(
    monkeypatch,
):
    """The core regression, at the per-candidate decision level: an
    infeasible candidate (standing in for the real
    archive-stream.granicus.com 504 case) must have its probe failure
    recorded on a real (non-dry-run) run -- this is what lets it enter
    cooldown and stop being handed back out on the next run."""

    async def fake_check_feasible(page):
        return {"ok": False, "reason": "ffprobe couldn't read the media"}

    recorder = _Recorder()
    monkeypatch.setattr(mod, "_check_feasible", fake_check_feasible)
    monkeypatch.setattr(mod, "_record_probe_failure", recorder)

    page = {"slug": "bad-granicus-clip", "meeting_page_id": 1}
    outcome = await mod._process_candidate(
        session="fake-session",
        page=page,
        requester_email="auto@example.com",
        dry_run=False,
    )

    assert outcome == mod._OUTCOME_SKIPPED
    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert args == (
        "fake-session",
        page,
        "ffprobe couldn't read the media",
        "auto@example.com",
    )
    assert kwargs == {}


async def test_process_candidate_does_not_record_failure_on_dry_run(monkeypatch):
    async def fake_check_feasible(page):
        return {"ok": False, "reason": "ffprobe couldn't read the media"}

    recorder = _Recorder()
    monkeypatch.setattr(mod, "_check_feasible", fake_check_feasible)
    monkeypatch.setattr(mod, "_record_probe_failure", recorder)

    page = {"slug": "bad-granicus-clip", "meeting_page_id": 1}
    outcome = await mod._process_candidate(
        session="fake-session",
        page=page,
        requester_email="auto@example.com",
        dry_run=True,
    )

    assert outcome == mod._OUTCOME_SKIPPED
    assert recorder.calls == []


async def test_process_candidate_creates_job_for_feasible_candidate_and_skips_recording(
    monkeypatch,
):
    async def fake_check_feasible(page):
        return {"ok": True, "result": _FakeResolvedMeeting(), "duration": 900.0}

    created_calls = []

    async def fake_create_job(session, **kwargs):
        created_calls.append(kwargs)
        return {"job_id": 999, "status": "queued"}

    recorder = _Recorder()
    monkeypatch.setattr(mod, "_check_feasible", fake_check_feasible)
    monkeypatch.setattr(mod, "_create_job", fake_create_job)
    monkeypatch.setattr(mod, "_record_probe_failure", recorder)

    page = {
        "slug": "good-clip",
        "meeting_page_id": 2,
        "source_url_normalized": "https://example.com/meeting/2",
    }
    outcome = await mod._process_candidate(
        session="fake-session",
        page=page,
        requester_email="auto@example.com",
        dry_run=False,
    )

    assert outcome == mod._OUTCOME_CREATED
    assert len(created_calls) == 1
    assert recorder.calls == []  # a feasible candidate never records a failure


async def test_process_candidate_stops_batch_on_too_many_active_jobs(monkeypatch):
    async def fake_check_feasible(page):
        return {"ok": True, "result": _FakeResolvedMeeting(), "duration": 900.0}

    async def fake_create_job(session, **kwargs):
        return {"error": "too_many_active_jobs", "slug": "x"}

    monkeypatch.setattr(mod, "_check_feasible", fake_check_feasible)
    monkeypatch.setattr(mod, "_create_job", fake_create_job)

    page = {
        "slug": "capped-clip",
        "meeting_page_id": 3,
        "source_url_normalized": "https://example.com/meeting/3",
    }
    outcome = await mod._process_candidate(
        session="fake-session",
        page=page,
        requester_email="auto@example.com",
        dry_run=False,
    )
    assert outcome == mod._OUTCOME_CAPPED


async def test_process_candidate_create_job_http_failure_does_not_record_probe_failure(
    monkeypatch,
):
    # A create-job HTTP failure is a different problem from an infeasible
    # candidate (the candidate itself looked fine) -- it must not be
    # recorded as a probe failure, which would incorrectly push a
    # perfectly good candidate into a day-long cooldown over what might
    # just be a transient Archive-side error.
    async def fake_check_feasible(page):
        return {"ok": True, "result": _FakeResolvedMeeting(), "duration": 900.0}

    async def fake_create_job(session, **kwargs):
        raise RuntimeError("create-job failed (500) -- not retrying")

    recorder = _Recorder()
    monkeypatch.setattr(mod, "_check_feasible", fake_check_feasible)
    monkeypatch.setattr(mod, "_create_job", fake_create_job)
    monkeypatch.setattr(mod, "_record_probe_failure", recorder)

    page = {
        "slug": "transient-error-clip",
        "meeting_page_id": 4,
        "source_url_normalized": "https://example.com/meeting/4",
    }
    outcome = await mod._process_candidate(
        session="fake-session",
        page=page,
        requester_email="auto@example.com",
        dry_run=False,
    )

    assert outcome == mod._OUTCOME_CREATE_FAILED
    assert recorder.calls == []


# --- Regression: an all-failing batch must not starve out probeable ------
# --- candidates that appear later in the SAME run --------------------------


async def test_a_batch_of_mixed_candidates_records_failures_only_for_the_infeasible_ones(
    monkeypatch,
):
    """Drives _process_candidate() over a realistic mixed batch -- several
    genuinely-broken Granicus candidates (ffprobe 504s) interleaved with
    genuinely-probeable ones -- and confirms every infeasible candidate
    gets its failure recorded (so it'll be in cooldown for the *next*
    run) while every feasible one creates a real job and is never
    recorded as a failure. This is the within-a-run half of "a batch of
    all-failing candidates should not starve out probeable candidates" --
    the cross-run half (a recorded failure actually vanishes from the
    next backlog call) is proven at the DB layer in
    tests/test_transcription_jobs.py.
    """
    pages = [
        {"slug": "granicus-bad-1", "meeting_page_id": 10, "feasible": False},
        {"slug": "granicus-bad-2", "meeting_page_id": 11, "feasible": False},
        {
            "slug": "probeable-1",
            "meeting_page_id": 12,
            "feasible": True,
            "source_url_normalized": "https://example.com/meeting/12",
        },
        {"slug": "granicus-bad-3", "meeting_page_id": 13, "feasible": False},
        {
            "slug": "probeable-2",
            "meeting_page_id": 14,
            "feasible": True,
            "source_url_normalized": "https://example.com/meeting/14",
        },
    ]

    async def fake_check_feasible(page):
        if page["feasible"]:
            return {"ok": True, "result": _FakeResolvedMeeting(), "duration": 900.0}
        return {"ok": False, "reason": "ffprobe couldn't read the media"}

    recorded_failure_ids = []

    async def fake_record_probe_failure(session, page, reason, requester_email):
        recorded_failure_ids.append(page["meeting_page_id"])

    created_ids = []

    async def fake_create_job(session, **kwargs):
        created_ids.append(kwargs["source_url"])
        return {"job_id": len(created_ids), "status": "queued"}

    monkeypatch.setattr(mod, "_check_feasible", fake_check_feasible)
    monkeypatch.setattr(mod, "_record_probe_failure", fake_record_probe_failure)
    monkeypatch.setattr(mod, "_create_job", fake_create_job)

    outcomes = [
        await mod._process_candidate(
            session="fake-session",
            page=page,
            requester_email="auto@example.com",
            dry_run=False,
        )
        for page in pages
    ]

    assert outcomes == [
        mod._OUTCOME_SKIPPED,
        mod._OUTCOME_SKIPPED,
        mod._OUTCOME_CREATED,
        mod._OUTCOME_SKIPPED,
        mod._OUTCOME_CREATED,
    ]
    # Every infeasible candidate got its failure recorded -- next run,
    # each of these is in cooldown and the driver reaches past it.
    assert recorded_failure_ids == [10, 11, 13]
    # Both probeable candidates -- despite being interleaved among
    # failing ones -- created real jobs in this same run.
    assert created_ids == [
        "https://example.com/meeting/12",
        "https://example.com/meeting/14",
    ]
