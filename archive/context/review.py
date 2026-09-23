"""Immutable editor reviews and safe handoff into the existing Context editor."""

from __future__ import annotations

import asyncio
from datetime import date

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from archive.db.engine import async_session
from archive.db.models import (
    ContextCandidate,
    ContextCandidateRevision,
    MeetingPage,
)
from archive.utils.context_links import (
    CONTEXT_SUMMARY_MAX,
    CONTEXT_TITLE_MAX,
    ContextLinkError,
    parse_rtr_link,
)

from . import store
from .importer import _http_url, _normalize_state, _parse_timestamp
from .schemas import CandidateReviewFields

REVIEW_FIELDS = (
    "jurisdiction",
    "state",
    "gov_id",
    "meeting_date",
    "meeting_body",
    "recording_url",
    "rtr_link",
    "t_seconds",
    "title",
    "summary",
    "source_label",
    "proposed_match",
    "notes",
)
_TEXT_FIELDS = set(REVIEW_FIELDS) - {"t_seconds"}
_SAVE_RETRIES = 4


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors(include_url=False):
        field = str(error["loc"][-1]) if error["loc"] else "fields"
        errors.setdefault(field, error["msg"])
    return errors


def normalize_review_fields(fields: dict) -> tuple[dict | None, dict[str, str]]:
    """Return a complete canonical snapshot or field-specific errors."""

    if not isinstance(fields, dict):
        return None, {"fields": "Send one complete object of review fields."}
    missing = set(REVIEW_FIELDS) - set(fields)
    unknown = set(fields) - set(REVIEW_FIELDS)
    errors: dict[str, str] = {}
    for field in sorted(missing):
        errors[field] = "This field is required; use null to clear it."
    for field in sorted(unknown):
        errors[field] = "This field is not editable."
    raw_timestamp = fields.get("t_seconds")
    if isinstance(raw_timestamp, (bool, float)):
        errors["t_seconds"] = "Use integer seconds, HH:MM:SS, or null."
    if errors:
        return None, errors

    try:
        parsed = CandidateReviewFields.model_validate(fields)
    except ValidationError as exc:
        return None, _validation_errors(exc)
    normalized = parsed.model_dump()

    for field in _TEXT_FIELDS:
        value = normalized[field]
        if isinstance(value, str):
            normalized[field] = value.strip() or None

    meeting_date = normalized["meeting_date"]
    if meeting_date is not None:
        try:
            parsed_date = date.fromisoformat(meeting_date)
        except ValueError:
            errors["meeting_date"] = "Use an exact YYYY-MM-DD date or leave it unknown."
        else:
            if parsed_date.isoformat() != meeting_date:
                errors["meeting_date"] = (
                    "Use an exact YYYY-MM-DD date or leave it unknown."
                )

    state = normalized["state"]
    if state is not None:
        normalized["state"] = _normalize_state(state)

    recording_url = normalized["recording_url"]
    if recording_url is not None:
        try:
            normalized["recording_url"] = _http_url(recording_url, "recording_url")
        except ValueError as exc:
            errors["recording_url"] = str(exc)

    try:
        normalized["t_seconds"] = _parse_timestamp(raw_timestamp)
    except ValueError as exc:
        errors["t_seconds"] = str(exc)

    rtr_link = normalized["rtr_link"]
    if rtr_link is not None:
        try:
            slug, _ = parse_rtr_link(rtr_link, None)
        except ContextLinkError as exc:
            errors["rtr_link"] = exc.message
        else:
            # The dedicated timestamp field is authoritative. Rebuilding also
            # drops line/version selectors that belong to a transcript view,
            # rather than to the proposed Context moment.
            seconds = normalized.get("t_seconds")
            normalized["rtr_link"] = (
                f"/m/{slug}?t={seconds}" if seconds is not None else f"/m/{slug}"
            )

    return (None, errors) if errors else (normalized, {})


def _conflict_clear_errors(
    candidate,
    fields: dict,
    clear_conflicts: set[str],
    latest_revision,
    latest_observation_id: int,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    conflict_fields = {
        conflict.get("field")
        for conflict in (candidate.source_conflicts or [])
        if conflict.get("field") in REVIEW_FIELDS
    }
    for field in conflict_fields:
        if fields[field] is not None or field in clear_conflicts:
            continue
        prior_null_still_current = bool(
            latest_revision is not None
            and latest_revision.fields.get(field) is None
            and latest_observation_id <= latest_revision.source_observation_id
        )
        if not prior_null_still_current:
            errors[field] = (
                "Sources disagree. Choose a value or explicitly leave this field unknown."
            )
    return errors


async def save_candidate_review(
    candidate_id: int,
    *,
    expected_version: int,
    fields: dict,
    clerk_user_id: str,
    clear_conflicts: list[str] | None = None,
) -> dict:
    """Atomically append one complete review, then recheck its effective facts."""

    normalized, errors = normalize_review_fields(fields)
    editor_id = (clerk_user_id or "").strip()
    if not editor_id or len(editor_id) > 255:
        errors["clerk_user_id"] = "A verified editor identity is required."
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        errors["expected_version"] = "expected_version must be an integer."
    elif expected_version < 1:
        errors["expected_version"] = "expected_version must be at least 1."
    if clear_conflicts is None:
        clear_conflicts = []
    if not isinstance(clear_conflicts, list) or any(
        not isinstance(field, str) for field in clear_conflicts
    ):
        errors["clear_conflicts"] = "clear_conflicts must be a list of field names."
        clear_set: set[str] = set()
    else:
        clear_set = set(clear_conflicts)
        unknown_clears = clear_set - set(REVIEW_FIELDS)
        if unknown_clears:
            errors["clear_conflicts"] = "Unknown conflict field(s): " + ", ".join(
                sorted(unknown_clears)
            )
    if errors or normalized is None:
        return {
            "outcome": "invalid",
            "message": "Review fields need correction.",
            "errors": errors,
        }

    last_error: Exception | None = None
    saved_version = None
    for attempt in range(_SAVE_RETRIES):
        async with async_session() as session:
            try:
                await store._begin_write_transaction(session)
                query = select(ContextCandidate).where(
                    ContextCandidate.id == candidate_id
                )
                if session.bind.dialect.name == "postgresql":
                    query = query.with_for_update()
                candidate = (await session.execute(query)).scalar_one_or_none()
                if candidate is None:
                    await session.rollback()
                    return {
                        "outcome": "not_found",
                        "message": "Candidate not found.",
                    }
                if candidate.version != expected_version:
                    await session.rollback()
                    return {
                        "outcome": "stale",
                        "message": "The candidate changed. Reload before saving.",
                    }

                latest_observation_id = await store._latest_observation_id(
                    session, candidate.id
                )
                latest_revision = await store._latest_revision(session, candidate.id)
                conflict_errors = _conflict_clear_errors(
                    candidate,
                    normalized,
                    clear_set,
                    latest_revision,
                    latest_observation_id,
                )
                if conflict_errors:
                    await session.rollback()
                    return {
                        "outcome": "invalid",
                        "message": "Resolve each conflicting source field.",
                        "errors": conflict_errors,
                    }

                active = await store._active_observations(session, candidate.id)
                source_claims, source_conflicts = store._aggregate_claims(active)
                saved_version = candidate.version + 1
                revision = ContextCandidateRevision(
                    candidate_id=candidate.id,
                    candidate_version=saved_version,
                    source_observation_id=latest_observation_id,
                    fields=normalized,
                    clerk_user_id=editor_id,
                )
                session.add(revision)
                candidate.claims = {**source_claims, **normalized}
                candidate.source_conflicts = source_conflicts
                candidate.version = saved_version
                candidate.meeting_page_id = None
                candidate.lookup_outcome = None
                candidate.next_action = "new"
                candidate.lookup_result = None
                candidate.checked_at = None
                await session.commit()
                break
            except (IntegrityError, OperationalError) as exc:
                await session.rollback()
                last_error = exc
                if attempt + 1 == _SAVE_RETRIES:
                    raise RuntimeError(
                        "The review could not be saved after retrying."
                    ) from last_error
        await asyncio.sleep(0.025 * (2**attempt))

    # Lookup is deliberately after the committed revision. A failed or stale
    # lookup can change queue status, but can never erase the editor's work.
    try:
        await store.recheck_candidate(candidate_id, expected_version=saved_version)
    except Exception:
        # The immutable revision is already committed. A transient lookup
        # failure must not turn an accepted editor save into apparent data
        # loss; the current `new` state keeps handoff disabled for retry.
        pass
    candidate = await store.get_candidate(candidate_id)
    return {
        "outcome": "saved",
        "message": "Review saved.",
        "candidate": candidate,
    }


async def get_candidate_prefill(candidate_id: int, review_id: int) -> dict:
    """Return an immutable saved review for the existing editor, without writes."""

    async with async_session() as session:
        candidate = await store._locked_candidate_for_read(session, candidate_id)
        if candidate is None:
            return {"outcome": "not_found"}
        requested = await session.get(ContextCandidateRevision, review_id)
        if requested is None or requested.candidate_id != candidate.id:
            return {"outcome": "not_found"}
        latest = await store._latest_revision(session, candidate.id)
        if latest is None or latest.id != requested.id:
            return {"outcome": "stale"}
        latest_observation_id = await store._latest_observation_id(
            session, candidate.id
        )
        if latest_observation_id > requested.source_observation_id:
            return {"outcome": "review_required"}
        meeting = (
            await session.get(MeetingPage, candidate.meeting_page_id)
            if candidate.meeting_page_id
            else None
        )

        if not store._editor_handoff_ready(
            candidate,
            meeting,
            has_review=True,
            research_changed=False,
        ):
            return {"outcome": "review_required"}

        fields = requested.fields
        t_seconds = fields.get("t_seconds")
        if not (
            isinstance(t_seconds, int)
            and not isinstance(t_seconds, bool)
            and 0 <= t_seconds <= 86400
        ):
            t_seconds = None
        matched = meeting is not None and candidate.lookup_outcome == "matched"
        warnings: list[str] = []
        if matched:
            deep_link = f"/m/{meeting.slug}"
            if t_seconds is not None:
                deep_link += f"?t={t_seconds}"
            match_kind = fields.get("proposed_match")
        else:
            # A checked not-found/ambiguous candidate may become a private
            # draft, but must not carry a guessed meeting association.
            deep_link = ""
            match_kind = None
            warnings.append(
                "No Archive meeting is matched. The draft has no deep link or match selection."
            )

        title = fields.get("title")
        summary = fields.get("summary")
        source_label = fields.get("source_label")
        if title is not None and len(title) > CONTEXT_TITLE_MAX:
            warnings.append(
                f"The headline is over {CONTEXT_TITLE_MAX} characters; shorten it before saving."
            )
        if summary is not None and len(summary) > CONTEXT_SUMMARY_MAX:
            warnings.append(
                f"The summary is over {CONTEXT_SUMMARY_MAX} characters; shorten it before saving."
            )
        if source_label is not None and len(source_label) > 120:
            warnings.append(
                "The source label is over 120 characters; shorten it before saving."
            )

        return {
            "outcome": "ready",
            "prefill": {
                "social_url": candidate.social_url,
                "headline": title,
                "summary": summary,
                "source_label": source_label,
                "deep_link": deep_link,
                "match_kind": match_kind,
            },
            "warnings": warnings,
        }
