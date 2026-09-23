"""Provider-independent contracts for Context research (schema version 1)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NextAction = Literal[
    "new",
    "check_failed",
    "conflict",
    "resolve_needed",
    "recording_needed",
    "ingest_needed",
    "moment_needed",
]
LookupOutcome = Literal["matched", "not_found", "ambiguous", "conflict", "error"]
MAX_IMPORT_ROWS = 100
MAX_RECHECK_ROWS = 25
PAGE_SIZE = 25


class NormalizedCandidate(BaseModel):
    """One normalized source observation; raw_payload preserves the input."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    provider: str
    source_record_key: str
    source_location: str | None = None
    social_url: str
    social_url_key: str
    network: str
    # Validated canonical fields: source_label, jurisdiction, state, gov_id,
    # meeting_date, meeting_body, recording_url, rtr_link, t_seconds, title,
    # summary, notes, evidence. Missing facts remain None.
    claims: dict[str, Any]
    raw_payload: dict[str, Any]
    content_hash: str


class LookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: LookupOutcome
    next_action: NextAction
    reason: str
    method: str | None = None
    meeting_page_id: int | None = None
    possible_pages: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    page_snapshot: dict[str, Any] | None = None


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    provider: str = Field(min_length=1, max_length=100)
    source_location: str | None = Field(default=None, max_length=2048)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_IMPORT_ROWS)
    apply: bool = False


class RecheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int] = Field(min_length=1, max_length=MAX_RECHECK_ROWS)


class InternalRecheckRequest(RecheckRequest):
    clerk_user_id: str
