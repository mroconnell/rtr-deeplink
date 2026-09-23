"""Persistence and private read models for Context research candidates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import and_, case, func, or_, select, text, tuple_, update
from sqlalchemy.exc import IntegrityError, OperationalError

from archive.db.engine import async_session
from archive.db.models import (
    ContextCandidate,
    ContextCandidateObservation,
    ContextEntry,
    MeetingPage,
)
from archive.utils.context_links import context_permalink

from .schemas import PAGE_SIZE, NextAction, NormalizedCandidate

_WRITE_RETRIES = 4
_source_locks: dict[str, asyncio.Lock] = {}
_source_locks_guard = asyncio.Lock()


class SourceRetargetError(ValueError):
    """A provider record key was previously attached to another post."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_identity(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _source_lock(provider: str, source_record_key: str) -> asyncio.Lock:
    lock_key = f"{provider}\0{source_record_key}"
    async with _source_locks_guard:
        return _source_locks.setdefault(lock_key, asyncio.Lock())


async def _cross_process_source_lock(session, provider: str, source_key: str) -> None:
    if session.bind.dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"{provider}\0{source_key}".encode()).digest()[:8]
    signed_key = int.from_bytes(digest, byteorder="big", signed=True)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": signed_key}
    )


def _active_observation_stmt(candidate_id: int):
    latest = (
        select(func.max(ContextCandidateObservation.id).label("id"))
        .where(ContextCandidateObservation.candidate_id == candidate_id)
        .group_by(
            ContextCandidateObservation.provider,
            ContextCandidateObservation.source_record_key,
        )
        .subquery()
    )
    return (
        select(ContextCandidateObservation)
        .join(latest, ContextCandidateObservation.id == latest.c.id)
        .order_by(ContextCandidateObservation.id)
    )


async def _active_observations(session, candidate_id: int) -> list:
    return list(
        (await session.execute(_active_observation_stmt(candidate_id))).scalars()
    )


def _aggregate_claims(observations: Iterable) -> tuple[dict, list]:
    values_by_field: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for observation in observations:
        for field, value in (observation.normalized_payload or {}).items():
            if value is None:
                continue
            identity = _json_identity(value)
            slot = values_by_field[field].setdefault(
                identity, {"value": value, "sources": []}
            )
            slot["sources"].append(
                {
                    "provider": observation.provider,
                    "source_record_key": observation.source_record_key,
                }
            )

    claims: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for field in sorted(values_by_field):
        variants = values_by_field[field]
        if len(variants) == 1:
            claims[field] = next(iter(variants.values()))["value"]
        else:
            conflicts.append(
                {
                    "field": field,
                    "values": [variants[key] for key in sorted(variants)],
                }
            )
    return claims, conflicts


async def _source_target_key(session, provider: str, source_key: str) -> str | None:
    stmt = (
        select(ContextCandidate.social_url_key)
        .join(
            ContextCandidateObservation,
            ContextCandidateObservation.candidate_id == ContextCandidate.id,
        )
        .where(
            ContextCandidateObservation.provider == provider,
            ContextCandidateObservation.source_record_key == source_key,
        )
        .distinct()
    )
    keys = list((await session.execute(stmt)).scalars())
    if len(keys) > 1:
        raise SourceRetargetError(
            "This provider record key is already attached to multiple social posts."
        )
    return keys[0] if keys else None


async def _store_observation_once(normalized: NormalizedCandidate) -> dict[str, Any]:
    async with async_session() as session:
        # SQLite has no row/advisory locks. BEGIN IMMEDIATE takes its database
        # write reservation before the source-owner read, so two processes
        # cannot both observe an unclaimed (provider, source_record_key) and
        # attach it to different posts. PostgreSQL uses the narrower advisory
        # transaction lock below.
        if session.bind.dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        else:
            await session.begin()
        try:
            await _cross_process_source_lock(
                session, normalized.provider, normalized.source_record_key
            )
            target_key = await _source_target_key(
                session, normalized.provider, normalized.source_record_key
            )
            if target_key is not None and target_key != normalized.social_url_key:
                raise SourceRetargetError(
                    "source_record_key is already attached to a different social post."
                )

            candidate = (
                await session.execute(
                    select(ContextCandidate)
                    .where(ContextCandidate.social_url_key == normalized.social_url_key)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            created = candidate is None
            if candidate is None:
                candidate = ContextCandidate(
                    social_url=normalized.social_url,
                    social_url_key=normalized.social_url_key,
                    network=normalized.network,
                    claims={},
                    source_conflicts=[],
                    version=1,
                    next_action="new",
                )
                session.add(candidate)
                await session.flush()

            duplicate = (
                await session.execute(
                    select(ContextCandidateObservation.id).where(
                        ContextCandidateObservation.provider == normalized.provider,
                        ContextCandidateObservation.source_record_key
                        == normalized.source_record_key,
                        ContextCandidateObservation.content_hash
                        == normalized.content_hash,
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                candidate_id = candidate.id
                await session.rollback()
                return {
                    "outcome": "unchanged",
                    "candidate_id": candidate_id,
                    "message": "This exact source observation was already imported.",
                }

            observation = ContextCandidateObservation(
                candidate_id=candidate.id,
                provider=normalized.provider,
                source_record_key=normalized.source_record_key,
                source_location=normalized.source_location,
                content_hash=normalized.content_hash,
                raw_payload=normalized.raw_payload,
                normalized_payload=normalized.claims,
            )
            session.add(observation)
            await session.flush()

            observations = await _active_observations(session, candidate.id)
            claims, conflicts = _aggregate_claims(observations)
            candidate.claims = claims
            candidate.source_conflicts = conflicts
            candidate.social_url = normalized.social_url
            candidate.network = normalized.network
            candidate.lookup_outcome = None
            candidate.lookup_result = None
            candidate.checked_at = None
            candidate.meeting_page_id = None
            candidate.next_action = "new"
            if not created:
                candidate.version += 1

            # Link an existing editorial record for display only. Never change
            # that record or copy its editorial text into research.
            if candidate.context_entry_id is None:
                candidate.context_entry_id = (
                    await session.execute(
                        select(ContextEntry.id).where(
                            ContextEntry.social_url_key == candidate.social_url_key
                        )
                    )
                ).scalar_one_or_none()
            await session.flush()
            result = {
                "outcome": "created" if created else "updated",
                "candidate_id": candidate.id,
                "message": (
                    "Created a new candidate."
                    if created
                    else "Stored a new immutable source observation."
                ),
            }
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def store_observation(normalized: NormalizedCandidate) -> dict[str, Any]:
    """Atomically store one observation, retrying bounded uniqueness races."""

    lock = await _source_lock(normalized.provider, normalized.source_record_key)
    async with lock:
        last_error: Exception | None = None
        for attempt in range(_WRITE_RETRIES):
            try:
                return await _store_observation_once(normalized)
            except SourceRetargetError:
                raise
            except (IntegrityError, OperationalError) as exc:
                last_error = exc
                if attempt + 1 == _WRITE_RETRIES:
                    break
                await asyncio.sleep(0.025 * (2**attempt))
        raise RuntimeError(
            "The observation could not be stored after retrying."
        ) from last_error


async def preview_observations(
    normalized_rows: list[NormalizedCandidate],
) -> list[dict[str, Any]]:
    """Classify a batch against one DB snapshot without writing anything."""

    if not normalized_rows:
        return []
    async with async_session() as session:
        candidates = list(
            (
                await session.execute(
                    select(ContextCandidate).where(
                        ContextCandidate.social_url_key.in_(
                            {row.social_url_key for row in normalized_rows}
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        candidate_by_key = {row.social_url_key: row for row in candidates}
        source_pairs = {
            (row.provider, row.source_record_key) for row in normalized_rows
        }
        observations = list(
            (
                await session.execute(
                    select(ContextCandidateObservation, ContextCandidate.social_url_key)
                    .join(
                        ContextCandidate,
                        ContextCandidate.id == ContextCandidateObservation.candidate_id,
                    )
                    .where(
                        tuple_(
                            ContextCandidateObservation.provider,
                            ContextCandidateObservation.source_record_key,
                        ).in_(source_pairs)
                    )
                )
            ).all()
        )

    source_target_sets: dict[tuple[str, str], set[str]] = defaultdict(set)
    seen_hashes: set[tuple[str, str, str]] = set()
    for observation, social_url_key in observations:
        source_target_sets[(observation.provider, observation.source_record_key)].add(
            social_url_key
        )
        seen_hashes.add(
            (
                observation.provider,
                observation.source_record_key,
                observation.content_hash,
            )
        )

    results: list[dict[str, Any]] = []
    simulated_candidates = dict(candidate_by_key)
    for row in normalized_rows:
        source_pair = (row.provider, row.source_record_key)
        targets = source_target_sets.get(source_pair, set())
        if len(targets) > 1:
            results.append(
                {
                    "outcome": "error",
                    "candidate_id": None,
                    "message": (
                        "This provider record key is already attached to multiple "
                        "social posts."
                    ),
                }
            )
            continue
        target = next(iter(targets), None)
        if target is not None and target != row.social_url_key:
            results.append(
                {
                    "outcome": "error",
                    "candidate_id": None,
                    "message": "source_record_key is already attached to a different social post.",
                }
            )
            continue
        hash_key = (*source_pair, row.content_hash)
        candidate = simulated_candidates.get(row.social_url_key)
        if hash_key in seen_hashes:
            results.append(
                {
                    "outcome": "unchanged",
                    "candidate_id": getattr(candidate, "id", None),
                    "message": "This exact source observation was already imported.",
                }
            )
            continue
        outcome = "updated" if candidate is not None else "created"
        results.append(
            {
                "outcome": outcome,
                "candidate_id": getattr(candidate, "id", None),
                "message": (
                    "Would create a new candidate."
                    if outcome == "created"
                    else "Would store a new immutable source observation."
                ),
            }
        )
        if candidate is None:
            simulated_candidates[row.social_url_key] = object()
        source_target_sets[source_pair].add(row.social_url_key)
        seen_hashes.add(hash_key)
    return results


async def candidate_actions(candidate_ids: set[int]) -> list[str]:
    if not candidate_ids:
        return []
    async with async_session() as session:
        return list(
            (
                await session.execute(
                    select(ContextCandidate.next_action).where(
                        ContextCandidate.id.in_(candidate_ids)
                    )
                )
            ).scalars()
        )


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _candidate_dict(candidate, meeting, entry, *, observations=None) -> dict:
    meeting_dict = None
    if meeting is not None:
        meeting_dict = {
            "id": meeting.id,
            "slug": meeting.slug,
            "title": meeting.title,
            "url": f"/m/{meeting.slug}",
        }
    entry_dict = None
    if entry is not None:
        entry_dict = {
            "id": entry.id,
            "status": entry.status,
            "url": context_permalink(
                entry.id,
                entry.title,
                None,
                None,
            ),
        }
    missing_matched_page = candidate.lookup_outcome == "matched" and meeting is None
    result = {
        "id": candidate.id,
        "social_url": candidate.social_url,
        "social_url_key": candidate.social_url_key,
        "network": candidate.network,
        "claims": candidate.claims or {},
        "source_conflicts": candidate.source_conflicts or [],
        "version": candidate.version,
        "meeting_page_id": candidate.meeting_page_id,
        "context_entry_id": entry.id
        if entry is not None
        else candidate.context_entry_id,
        "lookup_outcome": None if missing_matched_page else candidate.lookup_outcome,
        "next_action": "new" if missing_matched_page else candidate.next_action,
        "lookup_result": None if missing_matched_page else candidate.lookup_result,
        "checked_at": _dt(candidate.checked_at),
        "created_at": _dt(candidate.created_at),
        "updated_at": _dt(candidate.updated_at),
        "meeting": meeting_dict,
        "existing_entry": entry_dict,
        "needs_recheck": missing_matched_page,
        "recheck_reason": (
            "The previously matched meeting is no longer available. Recheck this candidate."
            if missing_matched_page
            else None
        ),
    }
    if observations is not None:
        result["observations"] = observations
    return result


async def list_candidates(*, page: int = 1, next_action: str | None = None) -> dict:
    if page < 1:
        raise ValueError("page must be at least 1.")
    allowed: set[str] = set(NextAction.__args__)
    if next_action is not None and next_action not in allowed:
        raise ValueError("Unknown next_action.")
    effective_action = case(
        (
            and_(
                ContextCandidate.lookup_outcome == "matched",
                ContextCandidate.meeting_page_id.is_(None),
            ),
            "new",
        ),
        else_=ContextCandidate.next_action,
    )
    async with async_session() as session:
        filtered = select(ContextCandidate)
        count_stmt = select(func.count(ContextCandidate.id))
        if next_action:
            filtered = filtered.where(effective_action == next_action)
            count_stmt = count_stmt.where(effective_action == next_action)
        total = int((await session.execute(count_stmt)).scalar_one())
        rows = (
            await session.execute(
                filtered.order_by(
                    ContextCandidate.updated_at.desc(), ContextCandidate.id
                )
                .offset((page - 1) * PAGE_SIZE)
                .limit(PAGE_SIZE)
            )
        ).scalars()
        candidates = list(rows)
        meeting_ids = {row.meeting_page_id for row in candidates if row.meeting_page_id}
        entry_ids = {row.context_entry_id for row in candidates if row.context_entry_id}
        social_keys = {row.social_url_key for row in candidates}
        meetings = {
            row.id: row
            for row in (
                (
                    await session.execute(
                        select(MeetingPage).where(MeetingPage.id.in_(meeting_ids))
                    )
                )
                .scalars()
                .all()
                if meeting_ids
                else []
            )
        }
        entry_conditions = []
        if entry_ids:
            entry_conditions.append(ContextEntry.id.in_(entry_ids))
        if social_keys:
            entry_conditions.append(ContextEntry.social_url_key.in_(social_keys))
        entry_rows = (
            list(
                (
                    await session.execute(
                        select(ContextEntry).where(or_(*entry_conditions))
                    )
                )
                .scalars()
                .all()
            )
            if entry_conditions
            else []
        )
        entries_by_id = {row.id: row for row in entry_rows}
        entries_by_key = {row.social_url_key: row for row in entry_rows}
        counts = {
            action: int(count)
            for action, count in (
                await session.execute(
                    select(effective_action, func.count(ContextCandidate.id))
                    .group_by(effective_action)
                    .order_by(effective_action)
                )
            ).all()
        }
    return {
        "candidates": [
            _candidate_dict(
                row,
                meetings.get(row.meeting_page_id),
                entries_by_id.get(row.context_entry_id)
                or entries_by_key.get(row.social_url_key),
            )
            for row in candidates
        ],
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": math.ceil(total / PAGE_SIZE) if total else 0,
        "counts": counts,
    }


async def get_candidate(candidate_id: int) -> dict | None:
    async with async_session() as session:
        candidate = await session.get(ContextCandidate, candidate_id)
        if candidate is None:
            return None
        meeting = (
            await session.get(MeetingPage, candidate.meeting_page_id)
            if candidate.meeting_page_id
            else None
        )
        entry = None
        if candidate.context_entry_id:
            entry = await session.get(ContextEntry, candidate.context_entry_id)
        if entry is None:
            entry = (
                await session.execute(
                    select(ContextEntry).where(
                        ContextEntry.social_url_key == candidate.social_url_key
                    )
                )
            ).scalar_one_or_none()
        all_observations = list(
            (
                await session.execute(
                    select(ContextCandidateObservation)
                    .where(ContextCandidateObservation.candidate_id == candidate.id)
                    .order_by(ContextCandidateObservation.id.desc())
                )
            ).scalars()
        )
        active_ids = {
            observation.id
            for observation in await _active_observations(session, candidate.id)
        }
        observations = [
            {
                "id": observation.id,
                "provider": observation.provider,
                "source_record_key": observation.source_record_key,
                "source_location": observation.source_location,
                "content_hash": observation.content_hash,
                "raw_payload": observation.raw_payload,
                "normalized_payload": observation.normalized_payload,
                "received_at": _dt(observation.received_at),
                "active": observation.id in active_ids,
            }
            for observation in all_observations
        ]
        return _candidate_dict(candidate, meeting, entry, observations=observations)


async def _mark_check_failed(candidate_id: int, read_version: int, reason: str) -> dict:
    now = _utcnow()
    lookup_result = {
        "outcome": "error",
        "next_action": "check_failed",
        "reason": reason,
        "method": None,
        "meeting_page_id": None,
        "possible_pages": [],
        "evidence": [],
        "page_snapshot": None,
    }
    async with async_session() as session:
        changed = await session.execute(
            update(ContextCandidate)
            .where(
                ContextCandidate.id == candidate_id,
                ContextCandidate.version == read_version,
            )
            .values(
                lookup_outcome="error",
                next_action="check_failed",
                lookup_result=lookup_result,
                checked_at=now,
                meeting_page_id=None,
                version=read_version + 1,
            )
        )
        await session.commit()
    if changed.rowcount != 1:
        return {
            "id": candidate_id,
            "outcome": "stale",
            "reason": "The candidate changed while its lookup was running.",
        }
    return {
        "id": candidate_id,
        "outcome": "error",
        "next_action": "check_failed",
        "reason": reason,
    }


async def recheck_candidate(
    candidate_id: int, expected_version: int | None = None
) -> dict:
    """Evaluate active claims and save only if no newer import won the race."""

    failure_reason = None
    evaluation = None
    async with async_session() as session:
        candidate = await session.get(ContextCandidate, candidate_id)
        if candidate is None:
            return {
                "id": candidate_id,
                "outcome": "not_found",
                "reason": "Candidate not found.",
            }
        read_version = candidate.version
        if expected_version is not None and expected_version != read_version:
            return {
                "id": candidate_id,
                "outcome": "stale",
                "reason": "The candidate changed before its lookup started.",
            }
        observations = await _active_observations(session, candidate_id)
        claims = [
            {
                **(observation.normalized_payload or {}),
                "social_url": candidate.social_url,
                "social_url_key": candidate.social_url_key,
                "network": candidate.network,
                "provider": observation.provider,
                "source_record_key": observation.source_record_key,
            }
            for observation in observations
        ]
        try:
            from .lookup import evaluate_candidate

            evaluation = await evaluate_candidate(claims, session=session)
        except Exception as exc:
            # The failed transaction/session is discarded. Failure is recorded in
            # a new transaction and remains retryable; it never means not_found.
            failure_reason = f"Lookup failed: {type(exc).__name__}."

    if failure_reason is not None:
        return await _mark_check_failed(candidate_id, read_version, failure_reason)

    payload = evaluation.model_dump(mode="json")
    now = _utcnow()
    async with async_session() as session:
        changed = await session.execute(
            update(ContextCandidate)
            .where(
                ContextCandidate.id == candidate_id,
                ContextCandidate.version == read_version,
            )
            .values(
                meeting_page_id=evaluation.meeting_page_id,
                lookup_outcome=evaluation.outcome,
                next_action=evaluation.next_action,
                lookup_result=payload,
                checked_at=now,
                version=read_version + 1,
            )
        )
        await session.commit()
    if changed.rowcount != 1:
        return {
            "id": candidate_id,
            "outcome": "stale",
            "reason": "The candidate changed while its lookup was running.",
        }
    return {
        "id": candidate_id,
        "outcome": "checked",
        "next_action": evaluation.next_action,
        "reason": evaluation.reason,
    }
