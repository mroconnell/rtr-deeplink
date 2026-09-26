"""Saved Context candidate review tests.

The hand-built provider rows are synthetic storage inputs. Their facts use the
real Indianapolis public-meeting example recorded in the Context pipeline plan:
Instagram reel DdF8tEDMtZs, the September 9, 2026 meeting, and moment 1:05:26.
No URL is fetched by these tests.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from archive.context import importer, review, store
from archive.context.schemas import LookupResult
from archive.db.engine import async_session
from archive.db.models import (
    ContextCandidate,
    ContextCandidateObservation,
    ContextCandidateRevision,
    ContextEntry,
    MeetingPage,
)

SOCIAL_URL = "https://www.instagram.com/reel/DdF8tEDMtZs/"
SOCIAL_KEY = "instagram:DdF8tEDMtZs"
EDITOR_ID = "context-review-test-editor"
PROVIDER_PREFIX = "review-test-"
MEETING_SLUG = "indianapolis-in-2026-09-09-metropolitan-development-commission"


def _source_row(**changes):
    """Synthetic source row populated with real published Indianapolis facts."""

    row = {
        "social_url": SOCIAL_URL,
        "source_record_key": "indianapolis-research",
        "jurisdiction": "Indianapolis",
        "state": "Indiana",
        "meeting_date": "2026-09-09",
        "meeting_body": "Metropolitan Development Commission",
        "recording_url": (
            "https://indianapolis.granicus.com/player/clip/26230"
            "?view_id=14&redirect=true"
        ),
        "t_seconds": "1:05:26",
        "title": "Indianapolis public meeting clip",
        "summary": "A researched moment from a public meeting.",
        "source_label": "Public meeting research",
        "proposed_match": "EXACT",
        "notes": "Synthetic storage input; facts are from the published example.",
    }
    row.update(changes)
    return row


def _review_fields(**changes):
    fields = {
        "jurisdiction": "Indianapolis",
        "state": "IN",
        "gov_id": None,
        "meeting_date": "2026-09-09",
        "meeting_body": "Metropolitan Development Commission",
        "recording_url": (
            "https://indianapolis.granicus.com/player/clip/26230"
            "?view_id=14&redirect=true"
        ),
        "rtr_link": f"/m/{MEETING_SLUG}",
        "t_seconds": 3926,
        "title": "Reviewed Indianapolis public meeting clip",
        "summary": "Reviewed explanation of the public meeting moment.",
        "source_label": "@publicmeetingresearch",
        "proposed_match": "exact",
        "notes": "Editor checked the source evidence.",
    }
    fields.update(changes)
    return fields


async def _candidate(*, provider: str, row: dict | None = None) -> int:
    normalized = importer.normalize_row(
        row or _source_row(),
        provider=f"{PROVIDER_PREFIX}{provider}",
        source_location="synthetic-review-test",
    )
    return (await store.store_observation(normalized))["candidate_id"]


async def _no_recheck(_candidate_id: int, expected_version: int | None = None):
    return {"outcome": "skipped", "expected_version": expected_version}


def _lookup_module(evaluator):
    return SimpleNamespace(evaluate_candidate=evaluator)


async def _clean_review_rows() -> None:
    async with async_session() as session:
        candidate_ids = list(
            (
                await session.execute(
                    select(ContextCandidateObservation.candidate_id).where(
                        ContextCandidateObservation.provider.like(f"{PROVIDER_PREFIX}%")
                    )
                )
            ).scalars()
        )
        if candidate_ids:
            await session.execute(
                delete(ContextCandidateRevision).where(
                    ContextCandidateRevision.candidate_id.in_(candidate_ids)
                )
            )
            await session.execute(
                delete(ContextCandidateObservation).where(
                    ContextCandidateObservation.candidate_id.in_(candidate_ids)
                )
            )
            await session.execute(
                delete(ContextCandidate).where(ContextCandidate.id.in_(candidate_ids))
            )
        await session.execute(
            delete(ContextEntry).where(
                ContextEntry.created_by_clerk_user_id == EDITOR_ID
            )
        )
        await session.execute(
            delete(MeetingPage).where(MeetingPage.platform == "review-test")
        )
        await session.commit()


@pytest.fixture(autouse=True)
async def _isolate_review_rows():
    await _clean_review_rows()
    yield
    await _clean_review_rows()


@pytest.mark.asyncio
async def test_save_preserves_source_observations_and_public_entry(monkeypatch):
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    async with async_session() as session:
        entry = ContextEntry(
            social_url=SOCIAL_URL,
            social_url_key=SOCIAL_KEY,
            network="instagram",
            source_label="Published label",
            title="Published title",
            summary="Published editorial copy must remain unchanged.",
            status="draft",
            created_by_clerk_user_id=EDITOR_ID,
        )
        session.add(entry)
        await session.commit()
        entry_id = entry.id

    candidate_id = await _candidate(provider="preservation")
    before = await store.get_candidate(candidate_id)
    raw_payload = before["observations"][0]["raw_payload"]
    result = await store.save_candidate_review(
        candidate_id,
        expected_version=before["version"],
        fields=_review_fields(summary=None, notes="The summary was cleared."),
        clerk_user_id=EDITOR_ID,
    )

    assert result["outcome"] == "saved"
    detail = result["candidate"]
    assert detail["review_fields"]["summary"] is None
    assert detail["claims"]["summary"] is None
    assert detail["has_saved_review"] is True
    assert len(detail["review_history"]) == 1
    assert detail["observations"][0]["raw_payload"] == raw_payload
    async with async_session() as session:
        observations = list(
            (
                await session.execute(
                    select(ContextCandidateObservation).where(
                        ContextCandidateObservation.candidate_id == candidate_id
                    )
                )
            ).scalars()
        )
        saved_entry = await session.get(ContextEntry, entry_id)
    assert len(observations) == 1
    assert (
        saved_entry.title,
        saved_entry.summary,
        saved_entry.source_label,
        saved_entry.status,
    ) == (
        "Published title",
        "Published editorial copy must remain unchanged.",
        "Published label",
        "draft",
    )


@pytest.mark.asyncio
async def test_conflicted_null_requires_explicit_clear_and_remains_audit_visible(
    monkeypatch,
):
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    candidate_id = await _candidate(provider="conflict-a")
    await _candidate(
        provider="conflict-b",
        row=_source_row(
            source_record_key="indianapolis-second-research",
            meeting_date="2026-09-10",
        ),
    )
    detail = await store.get_candidate(candidate_id)
    assert {item["field"] for item in detail["source_conflicts"]} >= {"meeting_date"}

    rejected = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(meeting_date=None),
        clerk_user_id=EDITOR_ID,
    )
    assert rejected["outcome"] == "invalid"
    assert "meeting_date" in rejected["errors"]

    saved = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(meeting_date=None),
        clerk_user_id=EDITOR_ID,
        clear_conflicts=["meeting_date"],
    )
    assert saved["outcome"] == "saved"
    assert saved["candidate"]["claims"]["meeting_date"] is None
    assert {item["field"] for item in saved["candidate"]["source_conflicts"]} >= {
        "meeting_date"
    }

    # A second explicit-null review remains valid while its source snapshot is
    # unchanged. New research makes the editor acknowledge that conflict again.
    current = saved["candidate"]
    repeated = await store.save_candidate_review(
        candidate_id,
        expected_version=current["version"],
        fields=_review_fields(meeting_date=None, notes="Still intentionally unknown."),
        clerk_user_id=EDITOR_ID,
    )
    assert repeated["outcome"] == "saved"
    await _candidate(
        provider="conflict-c",
        row=_source_row(
            source_record_key="indianapolis-third-research",
            meeting_date="2026-09-11",
        ),
    )
    changed = await store.get_candidate(candidate_id)
    assert changed["research_changed_since_review"] is True
    rejected_again = await store.save_candidate_review(
        candidate_id,
        expected_version=changed["version"],
        fields=_review_fields(meeting_date=None),
        clerk_user_id=EDITOR_ID,
    )
    assert rejected_again["outcome"] == "invalid"
    assert "meeting_date" in rejected_again["errors"]


@pytest.mark.asyncio
async def test_nonnull_review_resolves_effective_claim_without_erasing_conflict(
    monkeypatch,
):
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    candidate_id = await _candidate(provider="choice-a")
    await _candidate(
        provider="choice-b",
        row=_source_row(
            source_record_key="indianapolis-choice-b", meeting_date="2026-09-10"
        ),
    )
    detail = await store.get_candidate(candidate_id)
    saved = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(meeting_date="2026-09-09"),
        clerk_user_id=EDITOR_ID,
    )

    assert saved["outcome"] == "saved"
    assert saved["candidate"]["claims"]["meeting_date"] == "2026-09-09"
    assert {item["field"] for item in saved["candidate"]["source_conflicts"]} >= {
        "meeting_date"
    }


@pytest.mark.asyncio
async def test_later_import_keeps_review_override_and_requires_resave(monkeypatch):
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    candidate_id = await _candidate(provider="later-import")
    detail = await store.get_candidate(candidate_id)
    saved = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(title="Editor-owned title", meeting_body=None),
        clerk_user_id=EDITOR_ID,
    )
    review_id = saved["candidate"]["review_id"]

    changed = importer.normalize_row(
        _source_row(
            title="New provider title",
            meeting_body="New provider body",
            notes="A later synthetic provider observation.",
        ),
        provider=f"{PROVIDER_PREFIX}later-import",
        source_location="synthetic-review-test",
    )
    await store.store_observation(changed)
    after = await store.get_candidate(candidate_id)

    assert after["claims"]["title"] == "Editor-owned title"
    assert after["claims"]["meeting_body"] is None
    assert after["review_id"] == review_id
    assert after["research_changed_since_review"] is True
    assert after["editor_url"] is None
    assert len(after["observations"]) == 2
    assert (await store.get_candidate_prefill(candidate_id, review_id))[
        "outcome"
    ] == "review_required"


@pytest.mark.asyncio
async def test_stale_and_concurrent_saves_never_overwrite(monkeypatch):
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    candidate_id = await _candidate(provider="concurrent")
    original = await store.get_candidate(candidate_id)

    first, second = await asyncio.gather(
        store.save_candidate_review(
            candidate_id,
            expected_version=original["version"],
            fields=_review_fields(title="First concurrent choice"),
            clerk_user_id=f"{EDITOR_ID}-one",
        ),
        store.save_candidate_review(
            candidate_id,
            expected_version=original["version"],
            fields=_review_fields(title="Second concurrent choice"),
            clerk_user_id=f"{EDITOR_ID}-two",
        ),
    )

    assert sorted([first["outcome"], second["outcome"]]) == ["saved", "stale"]
    detail = await store.get_candidate(candidate_id)
    assert len(detail["review_history"]) == 1
    assert detail["review_fields"]["title"] in {
        "First concurrent choice",
        "Second concurrent choice",
    }
    stale = await store.save_candidate_review(
        candidate_id,
        expected_version=original["version"],
        fields=_review_fields(title="Late stale overwrite"),
        clerk_user_id=EDITOR_ID,
    )
    assert stale["outcome"] == "stale"
    assert (await store.get_candidate(candidate_id))["review_fields"]["title"] != (
        "Late stale overwrite"
    )


@pytest.mark.asyncio
async def test_detail_read_is_one_snapshot_during_concurrent_save(monkeypatch):
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    candidate_id = await _candidate(provider="read-snapshot")
    original = await store.get_candidate(candidate_id)
    first = await store.save_candidate_review(
        candidate_id,
        expected_version=original["version"],
        fields=_review_fields(title="First snapshot title", t_seconds=10),
        clerk_user_id=EDITOR_ID,
    )
    first_detail = first["candidate"]

    real_active = store._active_observations
    writer_task = None
    interleaved = False
    # Set by the writer's own _active_observations call, which it makes
    # inside its write transaction just before committing. Waiting on this
    # rather than on a fixed sleep means the check below always runs with
    # the save genuinely in flight: under a fixed 0.05s sleep, a slow run
    # could reach the check before the save had even begun.
    writer_in_transaction = asyncio.Event()

    async def interleave_after_candidate_read(session, read_candidate_id):
        nonlocal interleaved, writer_task
        if not interleaved:
            interleaved = True
            writer_task = asyncio.create_task(
                store.save_candidate_review(
                    candidate_id,
                    expected_version=first_detail["version"],
                    fields=_review_fields(title="Second snapshot title", t_seconds=20),
                    clerk_user_id=EDITOR_ID,
                )
            )
            # The reader's transaction holds the candidate snapshot. The save
            # may begin, but it cannot commit a revision into this response.
            await asyncio.wait_for(writer_in_transaction.wait(), timeout=10)
            await asyncio.sleep(0.05)
            assert not writer_task.done(), (
                "the save finished while the read was still open: "
                f"{writer_task.exception() or writer_task.result()['outcome']!r}"
            )
        else:
            writer_in_transaction.set()
        return await real_active(session, read_candidate_id)

    monkeypatch.setattr(store, "_active_observations", interleave_after_candidate_read)
    read_detail = await store.get_candidate(candidate_id)
    writer_result = await writer_task

    assert read_detail["version"] == first_detail["version"]
    assert read_detail["review_id"] == first_detail["review_id"]
    assert read_detail["review_fields"]["title"] == "First snapshot title"
    assert read_detail["proposed_moment_url"] is None
    assert writer_result["outcome"] == "saved"
    assert writer_result["candidate"]["review_fields"]["title"] == (
        "Second snapshot title"
    )


@pytest.mark.parametrize(
    ("changes", "error_field"),
    [
        ({"t_seconds": True}, "t_seconds"),
        ({"t_seconds": 12.5}, "t_seconds"),
        ({"meeting_date": "September 9, 2026"}, "meeting_date"),
        ({"recording_url": "javascript:alert(1)"}, "recording_url"),
        ({"proposed_match": "EXACT"}, "proposed_match"),
    ],
)
def test_typed_review_validation_is_field_specific(changes, error_field):
    normalized, errors = review.normalize_review_fields(_review_fields(**changes))
    assert normalized is None
    assert error_field in errors


def test_complete_snapshot_and_editor_identity_are_required():
    fields = _review_fields()
    fields.pop("summary")
    normalized, errors = review.normalize_review_fields(fields)
    assert normalized is None
    assert errors["summary"].startswith("This field is required")


def test_explicit_timestamp_rebuilds_rtr_link_and_null_removes_timestamp():
    old_link = f"/m/{MEETING_SLUG}?t=99&line=12&version=old"
    normalized, errors = review.normalize_review_fields(
        _review_fields(rtr_link=old_link, t_seconds="00:00:00")
    )
    assert errors == {}
    assert normalized["t_seconds"] == 0
    assert normalized["rtr_link"] == f"/m/{MEETING_SLUG}?t=0"

    cleared, errors = review.normalize_review_fields(
        _review_fields(rtr_link=old_link, t_seconds=None)
    )
    assert errors == {}
    assert cleared["rtr_link"] == f"/m/{MEETING_SLUG}"


@pytest.mark.asyncio
async def test_zero_timestamp_and_latest_matched_revision_prefill(monkeypatch):
    async with async_session() as session:
        meeting = MeetingPage(
            slug=MEETING_SLUG,
            platform="review-test",
            external_id="review-test:matched",
            source_url_normalized=(
                "https://indianapolis.granicus.com/player/clip/26230"
            ),
            title="Metropolitan Development Commission",
            date="2026-09-09",
            jurisdiction="Indianapolis, IN",
        )
        session.add(meeting)
        await session.commit()
        meeting_id = meeting.id

    async def matched_lookup(_claims, *, session):
        return LookupResult(
            outcome="matched",
            next_action="moment_needed",
            reason="Synthetic lookup result for the stored real meeting facts.",
            method="test",
            meeting_page_id=meeting_id,
        )

    monkeypatch.setitem(
        sys.modules, "archive.context.lookup", _lookup_module(matched_lookup)
    )
    candidate_id = await _candidate(provider="matched-prefill")
    original = await store.get_candidate(candidate_id)
    first = await store.save_candidate_review(
        candidate_id,
        expected_version=original["version"],
        fields=_review_fields(t_seconds=12, title="First reviewed title"),
        clerk_user_id=EDITOR_ID,
    )
    first_review_id = first["candidate"]["review_id"]
    second = await store.save_candidate_review(
        candidate_id,
        expected_version=first["candidate"]["version"],
        fields=_review_fields(t_seconds=0, title="Latest reviewed title"),
        clerk_user_id=EDITOR_ID,
    )
    detail = second["candidate"]
    latest_review_id = detail["review_id"]

    assert detail["proposed_moment_url"] == f"/m/{MEETING_SLUG}?t=0"
    assert detail["proposed_moment_label"] == "0:00"
    assert detail["editor_url"].endswith(f"&review={latest_review_id}")
    assert (await store.get_candidate_prefill(candidate_id, first_review_id))[
        "outcome"
    ] == "stale"
    ready = await store.get_candidate_prefill(candidate_id, latest_review_id)
    assert ready == {
        "outcome": "ready",
        "prefill": {
            "social_url": SOCIAL_URL,
            "headline": "Latest reviewed title",
            "summary": "Reviewed explanation of the public meeting moment.",
            "source_label": "@publicmeetingresearch",
            "deep_link": f"/m/{MEETING_SLUG}?t=0",
            "match_kind": "exact",
        },
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_checked_unmatched_prefill_has_no_guessed_meeting(monkeypatch):
    async def no_match(_claims, *, session):
        return LookupResult(
            outcome="not_found",
            next_action="ingest_needed",
            reason="Synthetic checked no-match result.",
            method="test",
        )

    monkeypatch.setitem(sys.modules, "archive.context.lookup", _lookup_module(no_match))
    candidate_id = await _candidate(provider="unmatched-prefill")
    detail = await store.get_candidate(candidate_id)
    saved = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(),
        clerk_user_id=EDITOR_ID,
    )
    current = saved["candidate"]

    assert current["editor_url"] is not None
    ready = await store.get_candidate_prefill(candidate_id, current["review_id"])
    assert ready["outcome"] == "ready"
    assert ready["prefill"]["deep_link"] == ""
    assert ready["prefill"]["match_kind"] is None
    assert ready["warnings"]


@pytest.mark.asyncio
async def test_lookup_failure_preserves_revision_and_blocks_handoff(monkeypatch):
    async def failed_lookup(_claims, *, session):
        raise RuntimeError("synthetic lookup failure")

    monkeypatch.setitem(
        sys.modules, "archive.context.lookup", _lookup_module(failed_lookup)
    )
    candidate_id = await _candidate(provider="lookup-failure")
    detail = await store.get_candidate(candidate_id)
    saved = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(),
        clerk_user_id=EDITOR_ID,
    )

    assert saved["outcome"] == "saved"
    assert saved["candidate"]["next_action"] == "check_failed"
    assert saved["candidate"]["has_saved_review"] is True
    assert saved["candidate"]["editor_url"] is None
    blocked = await store.get_candidate_prefill(
        candidate_id, saved["candidate"]["review_id"]
    )
    assert blocked["outcome"] == "review_required"


@pytest.mark.asyncio
async def test_recheck_overlays_complete_review_on_every_active_source(monkeypatch):
    candidate_id = await _candidate(provider="overlay-a")
    await _candidate(
        provider="overlay-b",
        row=_source_row(
            source_record_key="overlay-second",
            title="Different source title",
            meeting_body="Different source body",
        ),
    )
    real_recheck = store.recheck_candidate
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    detail = await store.get_candidate(candidate_id)
    saved = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(title="One reviewed title", meeting_body=None),
        clerk_user_id=EDITOR_ID,
        clear_conflicts=["meeting_body", "title"],
    )

    captured = []

    async def capture_lookup(claims, *, session):
        captured.extend(claims)
        return LookupResult(
            outcome="not_found",
            next_action="ingest_needed",
            reason="Synthetic overlay inspection.",
            method="test",
        )

    monkeypatch.setitem(
        sys.modules, "archive.context.lookup", _lookup_module(capture_lookup)
    )
    checked = await real_recheck(
        candidate_id, expected_version=saved["candidate"]["version"]
    )

    assert checked["outcome"] == "checked"
    assert len(captured) == 2
    assert all(claim["title"] == "One reviewed title" for claim in captured)
    assert all(claim["meeting_body"] is None for claim in captured)


@pytest.mark.asyncio
async def test_invalid_identity_and_unknown_clear_field_write_nothing(monkeypatch):
    monkeypatch.setattr(store, "recheck_candidate", _no_recheck)
    candidate_id = await _candidate(provider="invalid-save")
    detail = await store.get_candidate(candidate_id)
    result = await store.save_candidate_review(
        candidate_id,
        expected_version=detail["version"],
        fields=_review_fields(),
        clerk_user_id=" ",
        clear_conflicts=["not_editable"],
    )

    assert result["outcome"] == "invalid"
    assert set(result["errors"]) == {"clerk_user_id", "clear_conflicts"}
    async with async_session() as session:
        revisions = await session.scalar(
            select(ContextCandidateRevision.id)
            .where(ContextCandidateRevision.candidate_id == candidate_id)
            .limit(1)
        )
    assert revisions is None
