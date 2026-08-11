"""HTTP-level tests for /internal/transcription/create-job's clerk_verified
field (archive/main.py) -- user request 2026-08-11: a signed-in visitor's
already-Clerk-verified email should skip the confirm-by-email step the
same way an existing newsletter subscriber's email already does. Real DB
(archive/db/crud.py), only email_utils.check_audience_membership mocked
(no real Resend call).

Every "queued" job created here is drained immediately after asserting on
it (same convention as tests/test_transcription_jobs.py's own
_drain_job()) -- claim_next_chunk() picks the globally oldest queued job
across the whole shared fixture DB, so an undrained job here would get
picked up ahead of a job created by an unrelated test in a different
file, breaking its own claim_id assertion.
"""

import archive.main
from archive.db import crud
from fastapi.testclient import TestClient

client = TestClient(archive.main.app)
_HEADERS = {"Authorization": "Bearer test-token"}


def _body(external_id: str, requester_email: str, *, clerk_verified: bool = False) -> dict:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    return {
        "payload": {
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
        "input_url_normalized": url,
        "requester_email": requester_email,
        "media_url": "https://example.com/v.m3u8",
        "media_kind": "video",
        "probed_duration_seconds": 900,
        "chunk_size_seconds": 900,
        "clerk_verified": clerk_verified,
    }


async def _drain(job_id: int) -> None:
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job_id
    await crud.report_chunk_result(job_id, success=True, shifted_segments=[])


async def test_clerk_verified_skips_confirmation_even_when_not_a_newsletter_subscriber(monkeypatch):
    # The OR must short-circuit on clerk_verified alone -- a real
    # newsletter-audience check would say False here, proving this isn't
    # just accidentally passing via the other path.
    async def _not_a_subscriber(email):
        return False

    monkeypatch.setattr(archive.main.email_utils, "check_audience_membership", _not_a_subscriber)
    response = client.post(
        "/internal/transcription/create-job",
        json=_body("clerk-verified-1", "signedin@example.com", clerk_verified=True),
        headers=_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    await _drain(body["job_id"])


async def test_not_clerk_verified_still_falls_back_to_audience_membership_check(monkeypatch):
    async def _is_a_subscriber(email):
        return True

    monkeypatch.setattr(archive.main.email_utils, "check_audience_membership", _is_a_subscriber)
    response = client.post(
        "/internal/transcription/create-job",
        json=_body("clerk-verified-2", "subscriber@example.com", clerk_verified=False),
        headers=_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    await _drain(body["job_id"])


async def test_neither_clerk_verified_nor_subscriber_needs_confirmation(monkeypatch):
    async def _not_a_subscriber(email):
        return False

    monkeypatch.setattr(archive.main.email_utils, "check_audience_membership", _not_a_subscriber)
    response = client.post(
        "/internal/transcription/create-job",
        json=_body("clerk-verified-3", "stranger@example.com", clerk_verified=False),
        headers=_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending_confirmation"
