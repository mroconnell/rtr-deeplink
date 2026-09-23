"""Context candidate intake and storage tests.

Hand-built rows below are marked synthetic. They exercise storage branches only;
their URLs and meeting facts use the real published San Diego and Indianapolis
examples documented in docs/CONTEXT_PIPELINE_PLAN.md.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update

from archive.context import importer, store
from archive.context.schemas import LookupResult
from archive.db.engine import async_session
from archive.db.models import (
    ContextCandidate,
    ContextCandidateObservation,
    ContextEntry,
)
from scripts import import_context_candidates as import_cli

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "context_candidates"
    / "ig_public_meetings_sample.json"
)
SAN_DIEGO_SOCIAL = "https://www.youtube.com/shorts/zJKrMk-uuSw"
PHILADELPHIA_SOCIAL = "https://www.youtube.com/shorts/5LZqoNDRMYk"
TEST_EDITOR_ID = "context-import-storage-test"
SAN_DIEGO_RTR = (
    "https://redtaperecordings.com/m/"
    "city-of-san-diego-ca-2026-08-19-public-safety-and-livable-neighborhoods-committe"
    "?t=9866"
)


async def _remove_candidates(*social_keys: str) -> None:
    async with async_session() as session:
        candidate_ids = list(
            (
                await session.execute(
                    select(ContextCandidate.id).where(
                        ContextCandidate.social_url_key.in_(social_keys)
                    )
                )
            ).scalars()
        )
        if candidate_ids:
            await session.execute(
                delete(ContextCandidateObservation).where(
                    ContextCandidateObservation.candidate_id.in_(candidate_ids)
                )
            )
            await session.execute(
                delete(ContextCandidate).where(ContextCandidate.id.in_(candidate_ids))
            )
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean_import_test_rows():
    """Keep the suite's shared SQLite session clean for later route tests."""

    yield
    keys = (
        "youtube:zJKrMk-uuSw",
        "youtube:5LZqoNDRMYk",
        "instagram:DdF8tEDMtZs",
    )
    await _remove_candidates(*keys)
    async with async_session() as session:
        await session.execute(
            delete(ContextEntry).where(
                ContextEntry.created_by_clerk_user_id == TEST_EDITOR_ID
            )
        )
        await session.commit()


def _synthetic_row(**changes):
    """Synthetic provider row using independently published San Diego facts."""

    row = {
        "social_url": SAN_DIEGO_SOCIAL,
        "source_record_key": "synthetic-san-diego",
        "jurisdiction": "San Diego",
        "state": "California",
        "meeting_date": "2026-08-19",
        "meeting_body": "Public Safety and Livable Neighborhoods Committee",
        "rtr_link": SAN_DIEGO_RTR,
        "t_seconds": 9866,
        "evidence": [{"kind": "published_example", "checked": True}],
    }
    row.update(changes)
    return row


def _fake_lookup_module(evaluator):
    return SimpleNamespace(evaluate_candidate=evaluator)


@pytest.mark.asyncio
async def test_real_sheet_timestamp_and_free_text_sources_normalize():
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    # This mapping is explicit test input, not a claim about a hidden source
    # schema. Every value and source header comes from the published Sheet row.
    row = {
        "social_url": source["Reel URL"],
        "state": source["State"],
        "meeting_date": source["Date"],
        "meeting_body": source["Meeting body"],
        "recording_url": source["Video URL"],
        "source_timestamp": source["Proposed Timestamp"],
        "t_seconds": source["Timestamp Seconds"],
        "source_notes": source["Sources"],
        "source_ingest_claim": source["Needs RTR Ingest"],
        "__raw_payload__": source,
    }
    normalized = importer.normalize_row(
        row, provider="ig-public-meetings", source_location="Sheet1!A2:P2"
    )

    assert normalized.social_url_key == "instagram:DdF8tEDMtZs"
    assert normalized.claims["t_seconds"] == 3926
    assert normalized.claims["source_timestamp"] == "1:05:26"
    assert normalized.claims["source_notes"].startswith("Primary: https://")
    assert normalized.claims["source_ingest_claim"] == "YES"
    assert normalized.raw_payload == source


def test_normalize_rejects_unknown_fields_and_bad_timestamp():
    with pytest.raises(ValueError, match="Unknown input field"):
        importer.normalize_row(
            {**_synthetic_row(), "sheet_guess": "value"}, provider="synthetic"
        )
    with pytest.raises(ValueError, match="valid HH:MM:SS"):
        importer.normalize_row(
            _synthetic_row(t_seconds="01:75:00"), provider="synthetic"
        )
    with pytest.raises(ValueError, match="conflicts"):
        importer.normalize_row(
            _synthetic_row(source_timestamp="01:00:00"), provider="synthetic"
        )


def test_ambiguous_date_remains_raw_with_warning():
    normalized = importer.normalize_row(
        _synthetic_row(meeting_date="August 19, 2026"), provider="synthetic"
    )
    assert normalized.claims["meeting_date"] is None
    assert normalized.claims["meeting_date_raw"] == "August 19, 2026"
    assert normalized.claims["normalization_warnings"]


@pytest.mark.asyncio
async def test_preview_deduplicates_batch_and_writes_nothing():
    await _remove_candidates("youtube:zJKrMk-uuSw")
    rows = [_synthetic_row(), _synthetic_row()]

    report = await importer.import_rows(rows, provider="preview-synthetic")

    assert report["apply"] is False
    assert report["created"] == 1
    assert report["unchanged"] == 1
    assert report["unique_candidates"] == 1
    assert report["next_actions"] == {"new": 1}
    async with async_session() as session:
        assert (
            await session.execute(
                select(ContextCandidate).where(
                    ContextCandidate.social_url_key == "youtube:zJKrMk-uuSw"
                )
            )
        ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_apply_report_is_idempotent(monkeypatch):
    await _remove_candidates("youtube:zJKrMk-uuSw")

    async def synthetic_lookup(_claims, *, session):
        return LookupResult(
            outcome="not_found",
            next_action="ingest_needed",
            reason="Synthetic importer isolation result.",
            method="test",
        )

    monkeypatch.setitem(
        sys.modules,
        "archive.context.lookup",
        _fake_lookup_module(synthetic_lookup),
    )
    first = await importer.import_rows(
        [_synthetic_row(source_record_key="apply-repeat")],
        provider="apply-repeat-synthetic",
        apply=True,
    )
    second = await importer.import_rows(
        [_synthetic_row(source_record_key="apply-repeat")],
        provider="apply-repeat-synthetic",
        apply=True,
    )

    assert (first["created"], first["updated"], first["unchanged"]) == (1, 0, 0)
    assert (second["created"], second["updated"], second["unchanged"]) == (0, 0, 1)
    assert first["unique_candidates"] == second["unique_candidates"] == 1


@pytest.mark.asyncio
async def test_preview_counts_changed_candidate_once_when_another_row_is_unchanged():
    await _remove_candidates("youtube:zJKrMk-uuSw")
    existing = _synthetic_row(source_record_key="preview-existing")
    normalized = importer.normalize_row(existing, provider="preview-mixed-synthetic")
    await store.store_observation(normalized)

    report = await importer.import_rows(
        [existing, _synthetic_row(source_record_key="preview-new-source")],
        provider="preview-mixed-synthetic",
    )

    assert [row["outcome"] for row in report["rows"]] == ["unchanged", "updated"]
    assert report["unique_candidates"] == 1
    assert report["next_actions"] == {"new": 1}


@pytest.mark.asyncio
async def test_real_duplicate_research_group_is_rejected_without_ordering_it():
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))[1:]
    mapped = [
        {
            "social_url": row["Reel URL"],
            "state": row["State"],
            "meeting_date": row["Date"],
            "meeting_body": row["Meeting body"],
            "recording_url": row["Video URL"],
            "summary": row["Summary"],
            "__raw_payload__": row,
        }
        for row in rows
    ]

    report = await importer.import_rows(mapped, provider="real-sheet-duplicate")

    assert report["input_rows"] == 2
    assert report["valid_rows"] == 0
    assert report["rejected_rows"] == 2
    assert [row["outcome"] for row in report["rows"]] == ["rejected", "rejected"]
    assert all("unordered batch" in row["message"] for row in report["rows"])


@pytest.mark.asyncio
async def test_repeat_change_and_old_replay_preserve_immutable_history():
    await _remove_candidates("youtube:zJKrMk-uuSw")
    original = importer.normalize_row(_synthetic_row(), provider="history-synthetic")
    changed = importer.normalize_row(
        _synthetic_row(notes="A later research correction."),
        provider="history-synthetic",
    )

    first = await store.store_observation(original)
    same = await store.store_observation(original)
    second = await store.store_observation(changed)
    old_again = await store.store_observation(original)

    assert [
        first["outcome"],
        same["outcome"],
        second["outcome"],
        old_again["outcome"],
    ] == [
        "created",
        "unchanged",
        "updated",
        "unchanged",
    ]
    detail = await store.get_candidate(first["candidate_id"])
    assert len(detail["observations"]) == 2
    assert sum(item["active"] for item in detail["observations"]) == 1
    active = next(item for item in detail["observations"] if item["active"])
    assert active["normalized_payload"]["notes"] == "A later research correction."


@pytest.mark.asyncio
async def test_two_providers_preserve_conflicting_active_claims():
    await _remove_candidates("youtube:zJKrMk-uuSw")
    one = importer.normalize_row(
        _synthetic_row(source_record_key="provider-a", meeting_body="Body A"),
        provider="provider-a",
    )
    two = importer.normalize_row(
        _synthetic_row(source_record_key="provider-b", meeting_body="Body B"),
        provider="provider-b",
    )

    result_one, result_two = await asyncio.gather(
        store.store_observation(one), store.store_observation(two)
    )

    candidate_id = result_one["candidate_id"] or result_two["candidate_id"]
    detail = await store.get_candidate(candidate_id)
    assert "meeting_body" not in detail["claims"]
    conflict = next(
        item for item in detail["source_conflicts"] if item["field"] == "meeting_body"
    )
    assert {item["value"] for item in conflict["values"]} == {"Body A", "Body B"}
    assert len(detail["observations"]) == 2


@pytest.mark.asyncio
async def test_source_record_key_cannot_retarget_another_social_post():
    await _remove_candidates("youtube:zJKrMk-uuSw", "instagram:DdF8tEDMtZs")
    first = importer.normalize_row(
        _synthetic_row(source_record_key="fixed-source-id"), provider="retarget-test"
    )
    await store.store_observation(first)
    second = importer.normalize_row(
        {
            "social_url": "https://www.instagram.com/reel/DdF8tEDMtZs/",
            "source_record_key": "fixed-source-id",
        },
        provider="retarget-test",
    )

    with pytest.raises(store.SourceRetargetError, match="different social post"):
        await store.store_observation(second)


@pytest.mark.asyncio
async def test_concurrent_exact_duplicate_creates_one_observation():
    await _remove_candidates("youtube:zJKrMk-uuSw")
    normalized = importer.normalize_row(
        _synthetic_row(source_record_key="concurrent-exact"),
        provider="concurrent-synthetic",
    )

    results = await asyncio.gather(
        *(store.store_observation(normalized) for _ in range(4))
    )

    assert sorted(result["outcome"] for result in results) == [
        "created",
        "unchanged",
        "unchanged",
        "unchanged",
    ]
    detail = await store.get_candidate(results[0]["candidate_id"])
    assert len(detail["observations"]) == 1


@pytest.mark.asyncio
async def test_sqlite_transaction_prevents_cross_process_source_retarget(
    monkeypatch,
):
    await _remove_candidates("youtube:zJKrMk-uuSw", "instagram:DdF8tEDMtZs")
    first = importer.normalize_row(
        _synthetic_row(source_record_key="cross-process-source"),
        provider="cross-process-synthetic",
    )
    second = importer.normalize_row(
        {
            "social_url": "https://www.instagram.com/reel/DdF8tEDMtZs/",
            "source_record_key": "cross-process-source",
        },
        provider="cross-process-synthetic",
    )

    # Synthetic process boundary: separate in-memory locks force correctness to
    # come from the SQLite transaction, as it must for two service processes.
    async def independent_lock(_provider, _source_key):
        return asyncio.Lock()

    monkeypatch.setattr(store, "_source_lock", independent_lock)
    results = await asyncio.gather(
        store.store_observation(first),
        store.store_observation(second),
        return_exceptions=True,
    )

    assert sum(isinstance(result, store.SourceRetargetError) for result in results) == 1
    assert sum(isinstance(result, dict) for result in results) == 1


@pytest.mark.asyncio
async def test_changed_claim_invalidates_lookup_without_editing_context_entry():
    await _remove_candidates("youtube:5LZqoNDRMYk")
    async with async_session() as session:
        await session.execute(
            delete(ContextEntry).where(
                ContextEntry.social_url_key == "youtube:5LZqoNDRMYk"
            )
        )
        await session.commit()
    async with async_session() as session:
        entry = ContextEntry(
            social_url=PHILADELPHIA_SOCIAL,
            social_url_key="youtube:5LZqoNDRMYk",
            network="youtube",
            summary="Existing editorial summary.",
            title="Existing editorial title",
            status="draft",
            created_by_clerk_user_id=TEST_EDITOR_ID,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        entry_id = entry.id

    normalized = importer.normalize_row(
        _synthetic_row(
            social_url=PHILADELPHIA_SOCIAL,
            source_record_key="editorial-preservation",
        ),
        provider="editorial-synthetic",
    )
    stored = await store.store_observation(normalized)
    async with async_session() as session:
        await session.execute(
            update(ContextCandidate)
            .where(ContextCandidate.id == stored["candidate_id"])
            .values(
                lookup_outcome="matched",
                next_action="moment_needed",
                lookup_result={"outcome": "matched"},
                checked_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
            )
        )
        await session.commit()

    changed = importer.normalize_row(
        _synthetic_row(
            social_url=PHILADELPHIA_SOCIAL,
            source_record_key="editorial-preservation",
            notes="New source evidence invalidates the lookup.",
        ),
        provider="editorial-synthetic",
    )
    await store.store_observation(changed)

    detail = await store.get_candidate(stored["candidate_id"])
    assert detail["lookup_outcome"] is None
    assert detail["lookup_result"] is None
    assert detail["checked_at"] is None
    assert detail["next_action"] == "new"
    assert detail["existing_entry"]["id"] == entry_id
    async with async_session() as session:
        editorial = await session.get(ContextEntry, entry_id)
        assert editorial.title == "Existing editorial title"
        assert editorial.summary == "Existing editorial summary."
        assert editorial.status == "draft"


@pytest.mark.asyncio
async def test_missing_previously_matched_meeting_requires_recheck_in_read_model():
    await _remove_candidates("youtube:zJKrMk-uuSw")
    normalized = importer.normalize_row(
        _synthetic_row(source_record_key="deleted-meeting"),
        provider="deleted-meeting-synthetic",
    )
    stored = await store.store_observation(normalized)
    async with async_session() as session:
        await session.execute(
            update(ContextCandidate)
            .where(ContextCandidate.id == stored["candidate_id"])
            .values(
                lookup_outcome="matched",
                next_action="moment_needed",
                lookup_result={
                    "outcome": "matched",
                    "next_action": "moment_needed",
                    "meeting_page_id": 999999,
                },
                meeting_page_id=None,
            )
        )
        await session.commit()

    detail = await store.get_candidate(stored["candidate_id"])
    listing = await store.list_candidates(next_action="new")

    assert detail["lookup_outcome"] is None
    assert detail["lookup_result"] is None
    assert detail["next_action"] == "new"
    assert detail["needs_recheck"] is True
    assert "no longer available" in detail["recheck_reason"]
    assert stored["candidate_id"] in {item["id"] for item in listing["candidates"]}


@pytest.mark.asyncio
async def test_editorial_link_follows_current_social_key_after_entry_retarget():
    candidate_key = "instagram:DdF8tEDMtZs"
    other_key = "youtube:zJKrMk-uuSw"
    await _remove_candidates(candidate_key, other_key)
    async with async_session() as session:
        await session.execute(
            delete(ContextEntry).where(
                ContextEntry.social_url_key.in_({candidate_key, other_key})
            )
        )
        original = ContextEntry(
            social_url="https://www.instagram.com/reel/DdF8tEDMtZs/",
            social_url_key=candidate_key,
            network="instagram",
            summary="Original editorial record.",
            status="draft",
            created_by_clerk_user_id=TEST_EDITOR_ID,
        )
        session.add(original)
        await session.commit()
        await session.refresh(original)
        original_id = original.id

    normalized = importer.normalize_row(
        {
            "social_url": "https://www.instagram.com/reel/DdF8tEDMtZs/",
            "source_record_key": "editorial-retarget-history",
        },
        provider="editorial-retarget-synthetic",
    )
    stored = await store.store_observation(normalized)

    async with async_session() as session:
        original = await session.get(ContextEntry, original_id)
        original.social_url = SAN_DIEGO_SOCIAL
        original.social_url_key = other_key
        original.network = "youtube"
        await session.flush()
        replacement = ContextEntry(
            social_url="https://www.instagram.com/reel/DdF8tEDMtZs/",
            social_url_key=candidate_key,
            network="instagram",
            summary="Replacement editorial record for the original post.",
            status="published",
            created_by_clerk_user_id=TEST_EDITOR_ID,
        )
        session.add(replacement)
        await session.commit()
        await session.refresh(replacement)
        replacement_id = replacement.id

    detail = await store.get_candidate(stored["candidate_id"])
    listing = await store.list_candidates()
    listed = next(
        item for item in listing["candidates"] if item["id"] == stored["candidate_id"]
    )

    assert detail["context_entry_id"] == replacement_id
    assert detail["existing_entry"] == {
        "id": replacement_id,
        "status": "published",
        "url": f"/context/{replacement_id}",
    }
    assert listed["existing_entry"]["id"] == replacement_id
    assert detail["existing_entry"]["id"] != original_id


@pytest.mark.asyncio
async def test_stale_recheck_cannot_overwrite_newer_import(monkeypatch):
    await _remove_candidates("youtube:zJKrMk-uuSw")
    normalized = importer.normalize_row(
        _synthetic_row(source_record_key="stale-cas"), provider="stale-synthetic"
    )
    stored = await store.store_observation(normalized)
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_lookup(_claims, *, session):
        started.set()
        await release.wait()
        return LookupResult(
            outcome="matched",
            next_action="moment_needed",
            reason="Synthetic delayed exact match.",
            method="test",
            meeting_page_id=None,
        )

    monkeypatch.setitem(
        sys.modules,
        "archive.context.lookup",
        _fake_lookup_module(delayed_lookup),
    )
    checking = asyncio.create_task(store.recheck_candidate(stored["candidate_id"]))
    await started.wait()
    changed = importer.normalize_row(
        _synthetic_row(source_record_key="stale-cas", notes="New evidence."),
        provider="stale-synthetic",
    )
    await store.store_observation(changed)
    release.set()

    result = await checking

    assert result["outcome"] == "stale"
    detail = await store.get_candidate(stored["candidate_id"])
    assert detail["next_action"] == "new"
    assert detail["lookup_result"] is None


@pytest.mark.asyncio
async def test_lookup_failure_is_error_while_not_found_is_checked(monkeypatch):
    await _remove_candidates("youtube:zJKrMk-uuSw")
    normalized = importer.normalize_row(
        _synthetic_row(source_record_key="lookup-outcome"), provider="lookup-synthetic"
    )
    stored = await store.store_observation(normalized)

    async def failed_lookup(_claims, *, session):
        raise RuntimeError("synthetic database failure")

    monkeypatch.setitem(
        sys.modules,
        "archive.context.lookup",
        _fake_lookup_module(failed_lookup),
    )
    failed = await store.recheck_candidate(stored["candidate_id"])
    assert failed["outcome"] == "error"
    assert failed["next_action"] == "check_failed"

    async def no_match(_claims, *, session):
        return LookupResult(
            outcome="not_found",
            next_action="ingest_needed",
            reason="No archive match under checked identifiers.",
            method="recording_url",
        )

    monkeypatch.setitem(
        sys.modules,
        "archive.context.lookup",
        _fake_lookup_module(no_match),
    )
    checked = await store.recheck_candidate(stored["candidate_id"])
    assert checked["outcome"] == "checked"
    assert checked["next_action"] == "ingest_needed"
    detail = await store.get_candidate(stored["candidate_id"])
    assert detail["lookup_outcome"] == "not_found"
    assert detail["next_action"] == "ingest_needed"


def test_cli_explicit_mapping_preserves_unmapped_raw_source_fields(tmp_path):
    source = {
        "Reel URL": SAN_DIEGO_SOCIAL,
        "City": "San Diego",
        "Provider-only audit note": "keep this verbatim",
    }
    path = tmp_path / "rows.json"
    path.write_text(json.dumps([source]), encoding="utf-8")

    mapping = import_cli._parse_mapping(
        ["social_url=Reel URL", "jurisdiction=City"], None
    )
    mapped = import_cli._map_rows(import_cli._read_input(path), mapping)

    assert mapped[0]["social_url"] == SAN_DIEGO_SOCIAL
    assert mapped[0]["jurisdiction"] == "San Diego"
    assert mapped[0]["__raw_payload__"] == source
    assert "Provider-only audit note" not in mapped[0]


def test_cli_without_mapping_rejects_unknown_source_headers(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps([{"Reel URL": SAN_DIEGO_SOCIAL}]), encoding="utf-8")
    with pytest.raises(ValueError, match="map them explicitly"):
        import_cli._map_rows(import_cli._read_input(path), {})


def test_cli_returns_nonzero_when_archive_reports_rejected_rows(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps([{"social_url": SAN_DIEGO_SOCIAL}]), encoding="utf-8")
    monkeypatch.setenv("ARCHIVE_BASE_URL", "http://127.0.0.1:18999")
    monkeypatch.setenv("ARCHIVE_INGEST_TOKEN", "local-test-token")
    monkeypatch.setattr(
        import_cli,
        "_post_import",
        lambda _base, _token, _payload: {"rejected_rows": 1, "error_rows": 0},
    )

    exit_code = import_cli.main([str(path), "--provider", "synthetic", "--dry-run"])

    assert exit_code == 1
    assert '"rejected_rows": 1' in capsys.readouterr().out
