"""Normalize and import provider-independent Context research rows."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from archive.utils.context_links import (
    CONTEXT_SUMMARY_MAX,
    CONTEXT_TITLE_MAX,
    ContextLinkError,
    parse_rtr_link,
    parse_social_url,
)
from archive.utils.jurisdiction_format import match_us_state_or_province

from .schemas import MAX_IMPORT_ROWS, NormalizedCandidate

# This is the complete provider-independent input shape. A source-specific
# export uses the CLI's explicit canonical-name -> source-header mapping; source
# headers which are not mapped survive only in the immutable raw payload.
CANONICAL_FIELDS = frozenset(
    {
        "social_url",
        "source_record_key",
        "source_label",
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
        "notes",
        "evidence",
        "proposed_match",
        "source_timestamp",
        "source_notes",
        "source_ingest_claim",
    }
)
_RAW_PAYLOAD_KEY = "__raw_payload__"
_MAX_RAW_BYTES = 256 * 1024
_MAX_TEXT_BYTES = 32 * 1024
_MAX_SOURCE_KEY_BYTES = 512
_MAX_SOCIAL_KEY_BYTES = 2000
_MAX_TIMESTAMP_SECONDS = 24 * 60 * 60
_CLAIM_FIELDS = tuple(
    field
    for field in CANONICAL_FIELDS
    if field not in {"social_url", "source_record_key"}
)


def _json_size(value: Any) -> int:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("The row must contain only JSON-compatible values.") from exc
    return len(encoded)


def _optional_text(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    value = value.strip()
    if not value:
        return None
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{field} is too long (maximum {_MAX_TEXT_BYTES} bytes).")
    return value


def _http_url(value: str, field: str) -> str:
    if len(value.encode("utf-8")) > 2048:
        raise ValueError(f"{field} is too long (maximum 2048 bytes).")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"{field} must be a complete http:// or https:// URL.")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{field} must not contain a username or password.")
    return value


def _parse_date(value: str | None, claims: dict[str, Any]) -> None:
    if value is None:
        claims["meeting_date"] = None
        return
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        claims["meeting_date"] = None
        claims["meeting_date_raw"] = value
        claims.setdefault("normalization_warnings", []).append(
            "meeting_date was not an exact YYYY-MM-DD date and remains unresolved"
        )
        return
    if parsed.isoformat() != value:
        claims["meeting_date"] = None
        claims["meeting_date_raw"] = value
        claims.setdefault("normalization_warnings", []).append(
            "meeting_date was not an exact YYYY-MM-DD date and remains unresolved"
        )
        return
    claims["meeting_date"] = value


def _parse_timestamp(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("t_seconds must be integer seconds or HH:MM:SS.")
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str):
        candidate = value.strip()
        if candidate.isdigit():
            seconds = int(candidate)
        else:
            parts = candidate.split(":")
            if len(parts) != 3 or any(not part.isdigit() for part in parts):
                raise ValueError("t_seconds must be integer seconds or HH:MM:SS.")
            hours, minutes, seconds_part = (int(part) for part in parts)
            if minutes >= 60 or seconds_part >= 60:
                raise ValueError("t_seconds must be a valid HH:MM:SS timestamp.")
            seconds = hours * 3600 + minutes * 60 + seconds_part
    else:
        raise ValueError("t_seconds must be integer seconds or HH:MM:SS.")
    if seconds < 0 or seconds > _MAX_TIMESTAMP_SECONDS:
        raise ValueError("t_seconds must be between 0 and 86400 seconds.")
    return seconds


def _normalize_state(value: str | None) -> str | None:
    if value is None:
        return None
    return match_us_state_or_province(value) or value


def _parse_evidence(value: Any) -> list[dict[str, Any]] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("evidence must be a JSON list of objects.") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("evidence must be a JSON list of objects.")
    _json_size(value)
    return value


def _default_source_record_key(social_url_key: str) -> str:
    if len(social_url_key.encode("utf-8")) <= _MAX_SOURCE_KEY_BYTES:
        return social_url_key
    digest = hashlib.sha256(social_url_key.encode("utf-8")).hexdigest()
    return f"social-sha256:{digest}"


def normalize_row(
    row: dict, *, provider: str, source_location: str | None = None
) -> NormalizedCandidate:
    """Validate one canonical row without fetching any supplied URL."""

    if not isinstance(row, dict):
        raise ValueError("Each input row must be an object.")
    provider = (provider or "").strip()
    if not provider or len(provider) > 100:
        raise ValueError("provider must contain 1 to 100 characters.")
    if source_location is not None:
        source_location = source_location.strip() or None
        if source_location and len(source_location.encode("utf-8")) > 2048:
            raise ValueError("source_location is too long (maximum 2048 bytes).")

    unknown = set(row) - CANONICAL_FIELDS - {_RAW_PAYLOAD_KEY}
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise ValueError(f"Unknown input field(s): {names}.")
    raw_payload = row.get(_RAW_PAYLOAD_KEY, row)
    if not isinstance(raw_payload, dict):
        raise ValueError(f"{_RAW_PAYLOAD_KEY} must be an object.")
    if _json_size(raw_payload) > _MAX_RAW_BYTES:
        raise ValueError(f"The raw row exceeds the {_MAX_RAW_BYTES}-byte limit.")

    social_input = _optional_text(row, "social_url")
    if social_input is None:
        raise ValueError("social_url is required.")
    try:
        social = parse_social_url(social_input)
    except ContextLinkError as exc:
        raise ValueError(exc.message) from exc
    if len(social.key.encode("utf-8")) > _MAX_SOCIAL_KEY_BYTES:
        raise ValueError("The canonical social URL identity is too long.")

    source_record_key = _optional_text(row, "source_record_key")
    if source_record_key is None:
        source_record_key = _default_source_record_key(social.key)
    if len(source_record_key.encode("utf-8")) > _MAX_SOURCE_KEY_BYTES:
        raise ValueError(
            f"source_record_key is too long (maximum {_MAX_SOURCE_KEY_BYTES} bytes)."
        )

    claims: dict[str, Any] = {}
    for field in _CLAIM_FIELDS:
        if field in {"meeting_date", "t_seconds", "evidence"}:
            continue
        claims[field] = _optional_text(row, field)

    _parse_date(_optional_text(row, "meeting_date"), claims)
    claims["t_seconds"] = _parse_timestamp(row.get("t_seconds"))
    claims["evidence"] = _parse_evidence(row.get("evidence"))
    claims["state"] = _normalize_state(claims.get("state"))

    source_timestamp = claims.get("source_timestamp")
    source_timestamp_seconds = (
        _parse_timestamp(source_timestamp) if source_timestamp is not None else None
    )
    if claims["t_seconds"] is None and source_timestamp_seconds is not None:
        claims["t_seconds"] = source_timestamp_seconds
    elif (
        claims["t_seconds"] is not None
        and source_timestamp_seconds is not None
        and claims["t_seconds"] != source_timestamp_seconds
    ):
        raise ValueError("source_timestamp conflicts with t_seconds.")

    recording_url = claims.get("recording_url")
    if recording_url:
        claims["recording_url"] = _http_url(recording_url, "recording_url")

    rtr_timestamp = None
    rtr_link = claims.get("rtr_link")
    if rtr_link:
        try:
            _, rtr_timestamp = parse_rtr_link(rtr_link, None)
        except ContextLinkError as exc:
            raise ValueError(exc.message) from exc
    if claims["t_seconds"] is None and rtr_timestamp is not None:
        claims["t_seconds"] = rtr_timestamp
    elif (
        claims["t_seconds"] is not None
        and rtr_timestamp is not None
        and claims["t_seconds"] != rtr_timestamp
    ):
        raise ValueError("t_seconds conflicts with the timestamp in rtr_link.")

    if claims.get("title") and len(claims["title"]) > CONTEXT_TITLE_MAX:
        claims.setdefault("normalization_warnings", []).append(
            f"title exceeds the {CONTEXT_TITLE_MAX}-character editorial limit"
        )
    if claims.get("summary") and len(claims["summary"]) > CONTEXT_SUMMARY_MAX:
        claims.setdefault("normalization_warnings", []).append(
            f"summary exceeds the {CONTEXT_SUMMARY_MAX}-character editorial limit"
        )

    # Null values remain explicit. This lets the queue distinguish a blank fact
    # from a field the importer silently discarded.
    # Provider and record key are already columns in the uniqueness constraint;
    # source_location is provenance, not content. Excluding all three means the
    # same payload replayed from a renamed export remains unchanged.
    normalized_for_hash = {
        "social_url": social.canonical_url,
        "social_url_key": social.key,
        "network": social.network,
        "claims": claims,
        "raw_payload": raw_payload,
    }
    content_hash = hashlib.sha256(
        json.dumps(
            normalized_for_hash,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    try:
        return NormalizedCandidate(
            provider=provider,
            source_record_key=source_record_key,
            source_location=source_location,
            social_url=social.canonical_url,
            social_url_key=social.key,
            network=social.network,
            claims=claims,
            raw_payload=raw_payload,
            content_hash=content_hash,
        )
    except ValidationError as exc:  # pragma: no cover - defensive contract guard
        raise ValueError(str(exc)) from exc


def _empty_report(input_rows: int, apply: bool) -> dict[str, Any]:
    return {
        "apply": apply,
        "input_rows": input_rows,
        "valid_rows": 0,
        "rejected_rows": 0,
        "error_rows": 0,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "unique_candidates": 0,
        "next_actions": {},
        "rows": [],
    }


async def import_rows(
    rows: list[dict],
    *,
    provider: str,
    source_location: str | None = None,
    apply: bool = False,
) -> dict:
    """Preview or store a bounded batch, returning a complete row funnel."""

    if not isinstance(rows, list):
        raise ValueError("rows must be a list.")
    if not rows or len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"rows must contain between 1 and {MAX_IMPORT_ROWS} items.")

    report = _empty_report(len(rows), apply)
    normalized_rows: list[tuple[int, NormalizedCandidate]] = []
    for row_number, row in enumerate(rows, start=1):
        try:
            normalized = normalize_row(
                row, provider=provider, source_location=source_location
            )
        except ValueError as exc:
            report["rejected_rows"] += 1
            report["rows"].append(
                {
                    "row_number": row_number,
                    "outcome": "rejected",
                    "candidate_id": None,
                    "message": str(exc),
                }
            )
        else:
            report["valid_rows"] += 1
            normalized_rows.append((row_number, normalized))

    # A batch has no stable ordering guarantee (a Sheet export can be sorted or
    # filtered before it reaches us). If one source identity appears with two
    # different payloads, choosing the last row would silently invent recency.
    grouped: dict[tuple[str, str], list[tuple[int, NormalizedCandidate]]] = {}
    for item in normalized_rows:
        normalized = item[1]
        grouped.setdefault(
            (normalized.provider, normalized.source_record_key), []
        ).append(item)
    ambiguous_rows = {
        row_number
        for group in grouped.values()
        if len({item.content_hash for _, item in group}) > 1
        for row_number, _ in group
    }
    if ambiguous_rows:
        report["valid_rows"] -= len(ambiguous_rows)
        report["rejected_rows"] += len(ambiguous_rows)
        report["rows"].extend(
            {
                "row_number": row_number,
                "outcome": "rejected",
                "candidate_id": None,
                "message": (
                    "This provider/source_record_key has different payloads in "
                    "the same unordered batch; supply distinct stable source keys."
                ),
            }
            for row_number in sorted(ambiguous_rows)
        )
        normalized_rows = [
            item for item in normalized_rows if item[0] not in ambiguous_rows
        ]

    from . import store

    if apply:
        successful_candidate_keys: set[str] = set()
        candidates_to_recheck: dict[int, list[dict[str, Any]]] = {}
        for row_number, normalized in normalized_rows:
            try:
                result = await store.store_observation(normalized)
            except Exception as exc:
                report["error_rows"] += 1
                report["rows"].append(
                    {
                        "row_number": row_number,
                        "outcome": "error",
                        "candidate_id": None,
                        "message": str(exc),
                    }
                )
                continue
            outcome = result["outcome"]
            report[outcome] += 1
            successful_candidate_keys.add(normalized.social_url_key)
            row_result = {
                "row_number": row_number,
                "outcome": outcome,
                "candidate_id": result["candidate_id"],
                "message": result.get("message", ""),
            }
            report["rows"].append(row_result)
            if outcome in {"created", "updated"}:
                candidates_to_recheck.setdefault(result["candidate_id"], []).append(
                    row_result
                )

        for candidate_id, affected_rows in candidates_to_recheck.items():
            checked = await store.recheck_candidate(candidate_id)
            if checked["outcome"] in {"error", "stale", "not_found"}:
                message = checked.get("reason") or checked["outcome"]
                for row_result in affected_rows:
                    row_result["message"] = (
                        f"{row_result['message']} Lookup: {message}."
                    ).strip()
        report["unique_candidates"] = len(successful_candidate_keys)
    else:
        preview = await store.preview_observations(
            [normalized for _, normalized in normalized_rows]
        )
        successful_candidate_keys: set[str] = set()
        for (row_number, normalized), result in zip(normalized_rows, preview):
            outcome = result["outcome"]
            if outcome == "error":
                report["error_rows"] += 1
            else:
                report[outcome] += 1
                successful_candidate_keys.add(normalized.social_url_key)
            report["rows"].append(
                {
                    "row_number": row_number,
                    "outcome": outcome,
                    "candidate_id": result.get("candidate_id"),
                    "message": result.get("message", ""),
                }
            )
        report["unique_candidates"] = len(successful_candidate_keys)

    report["rows"].sort(key=lambda item: item["row_number"])
    candidate_ids = {
        row["candidate_id"] for row in report["rows"] if row.get("candidate_id")
    }
    if apply:
        if candidate_ids:
            actions = await store.candidate_actions(candidate_ids)
            report["next_actions"] = dict(sorted(Counter(actions).items()))
    else:
        changed_keys = {
            normalized.social_url_key
            for (_, normalized), result in zip(normalized_rows, preview)
            if result["outcome"] in {"created", "updated"}
        }
        unchanged_ids = {
            result.get("candidate_id")
            for (_, normalized), result in zip(normalized_rows, preview)
            if result["outcome"] == "unchanged"
            and result.get("candidate_id")
            and normalized.social_url_key not in changed_keys
        }
        actions = await store.candidate_actions(unchanged_ids)
        action_counts = Counter(actions)
        action_counts["new"] += len(changed_keys)
        report["next_actions"] = dict(
            sorted((key, value) for key, value in action_counts.items() if value)
        )
    return report
