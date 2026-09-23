"""Provider-independent contracts for Context research (schema version 1)."""

from typing import Annotated, Any, Literal

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
CandidateId = Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]


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
    # summary, notes, evidence, proposed_match, source_timestamp, source_notes,
    # source_ingest_claim. Missing facts remain None.
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
    ids: list[CandidateId] = Field(min_length=1, max_length=MAX_RECHECK_ROWS)


class InternalRecheckRequest(RecheckRequest):
    clerk_user_id: str


class CandidateReviewFields(BaseModel):
    """Complete saved review: null explicitly clears a proposed fact."""

    model_config = ConfigDict(extra="forbid")
    jurisdiction: str | None = Field(max_length=32768)
    state: str | None = Field(max_length=32768)
    gov_id: str | None = Field(max_length=320)
    meeting_date: str | None = Field(max_length=32)
    meeting_body: str | None = Field(max_length=32768)
    recording_url: str | None = Field(max_length=2048)
    rtr_link: str | None = Field(max_length=2048)
    t_seconds: Annotated[int, Field(strict=True)] | str | None
    title: str | None = Field(max_length=32768)
    summary: str | None = Field(max_length=32768)
    source_label: str | None = Field(max_length=32768)
    proposed_match: Literal["exact", "approximate", "related"] | None
    notes: str | None = Field(max_length=32768)


class CandidateSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: CandidateId
    expected_version: CandidateId
    fields: CandidateReviewFields
    clear_conflicts: list[str] = Field(default_factory=list, max_length=13)


class InternalCandidateSaveRequest(CandidateSaveRequest):
    clerk_user_id: str
