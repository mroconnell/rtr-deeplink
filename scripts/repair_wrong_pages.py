"""WO-934: repair wrong live pages in bulk, from one reviewed sheet.

Why this exists. About 50 live pages are filed under the wrong government
or hold a video that is not a meeting. Until now each one meant a hand-
typed call to `POST /internal/jurisdiction/override` or
`POST /internal/admin/delete-pages`. This tool reads ONE reviewed CSV
(`reports/wrong_page_worklist.csv`) and makes those same calls, in small
batches, with a safety check on every row. It adds no new production
endpoint. It uses the two existing ones, plus the read-only
`GET /internal/export/pages?ids=`.

Three commands.

    check      Read the sheet and find its faults. Reads no production data.
               With `--inventory FILE` it also compares every row with a
               local export of the Archive (the one
               `scripts/export_meeting_inventory.py` writes) and says which
               rows are already stale.
    run        Dry run by default. Reads the live pages, decides each row,
               and prints what it would do. With `--apply` it does the rekeys.
               With `--apply --allow-deletes` it also does the deletes.
    gone-videos  Turns a CHECKED video-status file (from the drip Mac) into
               delete rows for a person to review. Makes no request.

The sheet. One row per page. `page_id`, `action` (`rekey` or `delete`),
`target_gov_id` (rekey only), `expected_current_gov_id` (what the page
carries NOW; `(none)` means no government id), `expected_slug`, `requires`,
`confidence` (`high`, `medium`, `low`), `needs_ryan` (`yes` or `no`),
`ryan_decision` (blank, `approve` or `reject`), `source_entry`,
`shown_today`, `reason`, `evidence`. A blank `target_gov_id` is a finding,
not a gap to fill: it means a government has to be minted first.

The safety rules, all enforced here.

  * A stale row never acts. Before any call the tool reads the live page
    and refuses the row when the page id no longer has the expected slug or
    the expected government id. Three of five backlog entries were already
    stale on the day this was written, so this is the rule that matters most.
  * A row whose live page already carries the target is "already done" and
    is left alone. A delete whose page is already gone is the same.
  * A row that needs Ryan (`needs_ryan=yes`) does nothing until `ryan_decision`
    says `approve`. `reject` skips it. Deletes ALWAYS need `approve`, even
    when `needs_ryan` says `no`, and need `--allow-deletes` on top.
  * `requires` holds conditions the tool checks, all of which must hold:
      `video-gone`  a checked, recent status file (`--video-status`) must say
                    this page's video is deleted, private or malformed.
      `video-gone:<who>-<YYYY-MM-DD>`  a person's recorded check on that date
                    (for example `video-gone:ryan-2026-09-21`, Ryan clicking
                    the link) stands in for the status file. It is trusted
                    for the same 14 days a status check is, and a NEWER status
                    file that says the video is alive overrules it.
      `replacement-video:<video_id>`  the live Archive must hold ANOTHER page
                    for that video, filed under the same government. The tool
                    finds it by reading the Archive's page list (read-only,
                    500 pages per request), because the replacement's page id
                    cannot be known before the page exists.
    An unknown or malformed condition is never met, and a sheet that carries
    one fails `check`.
  * Every row is tried as a dry run first, even under `--apply`, and the
    answer must match the expected values. After a write the page is read
    again and must show the new state.
  * The tool stops on the first unexpected answer (any HTTP status other
    than 200, a missing field, a before/after that does not match). It never
    retries and never skips ahead. A refused stale row is NOT unexpected; it
    is counted and the run goes on.
  * `--batch-size` (default 5) is the most rows written per run. Run it
    again to continue; finished rows show up as "already done".
  * It writes a log CSV with the before and after of every row.

Where to run it. From the Archive service's Render shell, never from a
laptop against production (CLAUDE.md, "Run any backfill or bulk sweep from
the service's Render shell"). It never reads a `.env` file (a `.env` in a
parent folder is exactly how a worktree once reached production by
accident). The token comes from `ARCHIVE_INGEST_TOKEN` in the environment
and is never printed. The address comes from `--base-url`, then
`ARCHIVE_BASE_URL`, then `http://127.0.0.1:$PORT` (the Archive's own port on
its Render shell). `--apply` refuses any address that is not this machine
unless `--allow-remote` is also given.

About the draft rules. `POST /internal/jurisdiction/override` also appends a
`tenant_overrides.csv`-shaped line for the page's host to a file on the
Archive machine. For a shared host (a city's Granicus, Cablecast or
CivicClerk site that also carries its school board) such a line would file
the city's OTHER meetings under the school district. The log keeps those
lines in `draft_tenant_rules` so nobody has to guess what was written.
Commit none of them without checking that the host serves one government.

Usage (Archive Render shell, repo root):
    python scripts/repair_wrong_pages.py check reports/wrong_page_worklist.csv
    python scripts/repair_wrong_pages.py run reports/wrong_page_worklist.csv
    python scripts/repair_wrong_pages.py run reports/wrong_page_worklist.csv \\
        --apply --batch-size 5 --only-ids 9073,9681
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms.youtube_ids import _RESERVED_NON_IDS, extract_video_id  # noqa: E402

DEFAULT_WORKLIST = REPO_ROOT / "reports" / "wrong_page_worklist.csv"

WORKLIST_COLUMNS = [
    "page_id",
    "action",
    "target_gov_id",
    "expected_current_gov_id",
    "expected_slug",
    "requires",
    "confidence",
    "needs_ryan",
    "ryan_decision",
    "source_entry",
    "shown_today",
    "reason",
    "evidence",
]
REQUIRED_COLUMNS = [
    "page_id",
    "action",
    "target_gov_id",
    "expected_current_gov_id",
    "expected_slug",
    "requires",
    "confidence",
    "needs_ryan",
    "ryan_decision",
]

ACTIONS = ("rekey", "delete")
CONFIDENCES = ("high", "medium", "low")
NO_GOV = "(none)"  # "the page carries no government id"

# The tier the Archive writes on an override (archive/db/crud.py
# _MANUAL_OVERRIDE_CONFIDENCE); a test pins the two together.
MANUAL_OVERRIDE = "manual_override"

# A video's checked state, as the drip Mac writes it.
GONE_STATUSES = ("deleted", "private", "malformed")
STATUS_VALUES = GONE_STATUSES + ("ok", "embedding_disabled", "unknown")
STATUS_COLUMNS = ["page_id", "video_id", "status", "checked_on", "http_status", "note"]
# A "gone" verdict older than this is not trusted: a private video can be
# made public again.
MAX_STATUS_AGE_DAYS = 14

LOG_COLUMNS = [
    "time_utc",
    "page_id",
    "action",
    "outcome",
    "detail",
    "slug",
    "target_gov_id",
    "before_gov_id",
    "before_jurisdiction",
    "before_confidence",
    "after_gov_id",
    "after_jurisdiction",
    "after_confidence",
    "draft_tenant_rules",
]

# Outcomes. Everything that is not "done" or "would do" leaves the page alone.
WOULD_REKEY = "would-rekey"
WOULD_DELETE = "would-delete"
REKEYED = "rekeyed"
DELETED = "deleted"
ALREADY_DONE = "already-done"
SKIP_REJECTED = "skipped-rejected"
SKIP_BLOCKED = "skipped-no-target"
SKIP_AWAITING = "skipped-awaiting-ryan"
SKIP_NO_DELETES = "skipped-deletes-not-allowed"
SKIP_BATCH_FULL = "skipped-batch-full"
REFUSED_STALE = "refused-stale"
REFUSED_MISSING = "refused-page-missing"
REFUSED_REQUIRES = "refused-requirement-not-met"
HALTED = "HALTED"

# What a written row will show once applied, for the plain-language summary.
OUTCOME_LABELS = {
    WOULD_REKEY: "Would re-key (dry run)",
    WOULD_DELETE: "Would delete (dry run)",
    REKEYED: "Re-keyed",
    DELETED: "Deleted",
    ALREADY_DONE: "Already done, left alone",
    SKIP_REJECTED: "Rejected by Ryan",
    SKIP_BLOCKED: "No target government yet (a mint is needed first)",
    SKIP_AWAITING: "Waiting for Ryan's approve or reject",
    SKIP_NO_DELETES: "Approved delete, but --allow-deletes was not given",
    SKIP_BATCH_FULL: "Eligible, but this run's batch was full",
    REFUSED_STALE: "Refused: the live page no longer matches the row",
    REFUSED_MISSING: "Refused: the page is not live",
    REFUSED_REQUIRES: "Refused: a required condition is not met",
    HALTED: "Stopped on an unexpected answer",
}


class UnexpectedResponse(Exception):
    """The Archive answered in a way this tool does not accept. The run stops."""


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------


@dataclass
class Row:
    page_id: int
    action: str
    target_gov_id: str
    expected_current_gov_id: str
    expected_slug: str
    requires: List[Tuple[str, str]]
    confidence: str
    needs_ryan: bool
    ryan_decision: str
    source_entry: str = ""
    shown_today: str = ""
    reason: str = ""
    evidence: str = ""
    origin: str = ""  # "file:line", for messages

    @property
    def approved(self) -> bool:
        return self.ryan_decision == "approve"

    @property
    def rejected(self) -> bool:
        return self.ryan_decision == "reject"


_HUMAN_CHECK_RE = re.compile(r"^([a-z][a-z0-9]*)-(\d{4}-\d{2}-\d{2})$")
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_human_check(arg: str) -> Optional[Tuple[str, dt.date]]:
    """`ryan-2026-09-21` -> ("ryan", date(2026, 9, 21)); None when malformed."""
    match = _HUMAN_CHECK_RE.match(arg)
    if not match:
        return None
    try:
        return match.group(1), dt.date.fromisoformat(match.group(2))
    except ValueError:
        return None


def parse_requires(text: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """`video-gone:ryan-2026-09-21;replacement-video:PveTE-5yFiU` ->
    [("video-gone", "ryan-2026-09-21"), ("replacement-video", "PveTE-5yFiU")].
    Returns (tokens, problems)."""
    tokens: List[Tuple[str, str]] = []
    problems: List[str] = []
    for part in (text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        kind, _, arg = part.partition(":")
        kind, arg = kind.strip(), arg.strip()
        if kind == "video-gone" and (not arg or parse_human_check(arg)):
            tokens.append((kind, arg))
        elif kind == "video-gone":
            problems.append(
                f"{part!r}: a human check reads video-gone:<who>-<YYYY-MM-DD>"
            )
        elif (
            kind == "replacement-video"
            and _VIDEO_ID_RE.match(arg)
            and arg not in _RESERVED_NON_IDS
        ):
            tokens.append((kind, arg))
        elif kind == "replacement-video":
            problems.append(
                f"{part!r}: replacement-video needs an 11-character video id"
            )
        elif kind == "replacement-page":
            problems.append(
                f"{part!r}: replacement-page is gone; use replacement-video:<video_id>"
            )
        else:
            problems.append(f"unknown condition {part!r} in requires")
    return tokens, problems


def parse_row(raw: Dict[str, str], origin: str) -> Tuple[Optional[Row], List[str]]:
    """One CSV row -> (Row, problems). Row is None when it cannot be read at all."""
    problems: List[str] = []

    def cell(name: str) -> str:
        return (raw.get(name) or "").strip()

    try:
        page_id = int(cell("page_id"))
    except ValueError:
        return None, [f"{origin}: page_id {cell('page_id')!r} is not an integer"]

    action = cell("action")
    if action not in ACTIONS:
        problems.append(f"{origin}: action must be rekey or delete, got {action!r}")
    confidence = cell("confidence")
    if confidence not in CONFIDENCES:
        problems.append(f"{origin}: confidence must be high, medium or low")
    needs = cell("needs_ryan").lower()
    if needs not in ("yes", "no"):
        problems.append(f"{origin}: needs_ryan must be yes or no")
    decision = cell("ryan_decision").lower()
    if decision not in ("", "approve", "reject"):
        problems.append(f"{origin}: ryan_decision must be blank, approve or reject")

    target = cell("target_gov_id")
    expected = cell("expected_current_gov_id")
    slug = cell("expected_slug")
    if not expected:
        problems.append(
            f"{origin}: expected_current_gov_id is required (use {NO_GOV} for "
            "a page with no government id)"
        )
    if action == "delete" and target:
        problems.append(f"{origin}: a delete row must not carry a target_gov_id")
    if action == "delete" and not slug:
        problems.append(f"{origin}: a delete row needs expected_slug")
    if action == "rekey" and target and target == expected:
        problems.append(f"{origin}: target_gov_id equals expected_current_gov_id")
    if needs == "no" and confidence != "high":
        problems.append(f"{origin}: only a high-confidence row may say needs_ryan=no")
    if action == "delete" and needs == "no":
        problems.append(
            f"{origin}: a delete row must say needs_ryan=yes (deletes always wait for approve)"
        )
    if action == "rekey" and not target and needs == "no":
        problems.append(f"{origin}: a rekey with no target must say needs_ryan=yes")

    requires, req_problems = parse_requires(cell("requires"))
    problems.extend(f"{origin}: {p}" for p in req_problems)

    row = Row(
        page_id=page_id,
        action=action,
        target_gov_id=target,
        expected_current_gov_id=expected,
        expected_slug=slug,
        requires=requires,
        confidence=confidence,
        needs_ryan=needs == "yes",
        ryan_decision=decision,
        source_entry=cell("source_entry"),
        shown_today=cell("shown_today"),
        reason=cell("reason"),
        evidence=cell("evidence"),
        origin=origin,
    )
    return row, problems


def read_worklists(paths: Iterable[Path]) -> Tuple[List[Row], List[str]]:
    """Read one or more sheets. A page id may appear once across all of them."""
    rows: List[Row] = []
    problems: List[str] = []
    seen: Dict[int, str] = {}
    for path in paths:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = [
                c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])
            ]
            if missing:
                problems.append(f"{path}: missing column(s) {', '.join(missing)}")
                continue
            for line_no, raw in enumerate(reader, start=2):
                origin = f"{path.name}:{line_no}"
                row, row_problems = parse_row(raw, origin)
                problems.extend(row_problems)
                if row is None:
                    continue
                if row.page_id in seen:
                    problems.append(
                        f"{origin}: page {row.page_id} is already on the sheet at {seen[row.page_id]}"
                    )
                    continue
                seen[row.page_id] = origin
                rows.append(row)
    return rows, problems


# ---------------------------------------------------------------------------
# Video status (from the drip Mac)
# ---------------------------------------------------------------------------


@dataclass
class StatusIndex:
    by_page: Dict[int, Tuple[str, dt.date]] = field(default_factory=dict)
    by_video: Dict[str, Tuple[str, dt.date]] = field(default_factory=dict)

    def lookup(
        self, page_id: int, video_id: Optional[str]
    ) -> Optional[Tuple[str, dt.date]]:
        """Newest verdict for this page, else for this video id."""
        found = self.by_page.get(page_id)
        if found is None and video_id:
            found = self.by_video.get(video_id)
        return found


def read_status_file(path: Path) -> Tuple[StatusIndex, List[str]]:
    """Read a checked status file: `page_id` and/or `video_id`, `status`, `checked_on`."""
    index = StatusIndex()
    problems: List[str] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        for needed in ("status", "checked_on"):
            if needed not in fields:
                problems.append(f"{path}: missing column {needed}")
        if not ({"page_id", "video_id"} & set(fields)):
            problems.append(f"{path}: needs a page_id or a video_id column")
        if problems:
            return index, problems
        for line_no, raw in enumerate(reader, start=2):
            origin = f"{path.name}:{line_no}"
            status = (raw.get("status") or "").strip().lower()
            if status not in STATUS_VALUES:
                problems.append(
                    f"{origin}: status {status!r} is not one of {STATUS_VALUES}"
                )
                continue
            try:
                checked = dt.date.fromisoformat((raw.get("checked_on") or "").strip())
            except ValueError:
                problems.append(f"{origin}: checked_on must be YYYY-MM-DD")
                continue
            page_text = (raw.get("page_id") or "").strip()
            video_id = (raw.get("video_id") or "").strip()
            if not page_text and not video_id:
                problems.append(f"{origin}: row names neither a page_id nor a video_id")
                continue
            if page_text:
                if not page_text.isdigit():
                    problems.append(
                        f"{origin}: page_id {page_text!r} is not an integer"
                    )
                    continue
                _keep_newest(index.by_page, int(page_text), status, checked)
            if video_id:
                _keep_newest(index.by_video, video_id, status, checked)
    return index, problems


def _keep_newest(table: dict, key, status: str, checked: dt.date) -> None:
    old = table.get(key)
    if old is None or checked >= old[1]:
        table[key] = (status, checked)


def page_video_ids(page: dict) -> List[str]:
    """Every YouTube video id a live page carries: its video address, its
    source address, and a `youtube:<id>` external id. Empty for a page with
    none (a Granicus or CivicClerk page, say)."""
    found: List[str] = []
    for text in (page.get("video_url"), page.get("source_url_normalized")):
        video_id = extract_video_id(text or "")
        if video_id and video_id not in found:
            found.append(video_id)
    external = (page.get("external_id") or "").strip()
    if external.startswith("youtube:"):
        tail = external[len("youtube:") :]
        if (
            _VIDEO_ID_RE.match(tail)
            and tail not in _RESERVED_NON_IDS
            and tail not in found
        ):
            found.append(tail)
    return found


# ---------------------------------------------------------------------------
# The Archive, over HTTP
# ---------------------------------------------------------------------------


class ArchiveClient:
    """The three calls this tool makes. Nothing else touches the Archive.

    `http` is any httpx-style client. Production use builds one from a base
    URL; the tests pass a Starlette TestClient wired to a real Archive app on
    a local SQLite file. The token is only ever put in a header.
    """

    def __init__(
        self, base_url: str, token: str, http: Optional[httpx.Client] = None
    ) -> None:
        self.base_url = base_url
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http or httpx.Client(base_url=base_url, timeout=60.0)
        self.calls: List[str] = []
        # Every call that was NOT a dry run. Empty means nothing was written.
        self.writes: List[str] = []
        self._video_index: Optional[Dict[str, List[dict]]] = None

    def _send(self, method: str, path: str, **kwargs) -> dict:
        self.calls.append(f"{method} {path}")
        try:
            response = self._http.request(method, path, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise UnexpectedResponse(
                f"{method} {path} failed: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            # A 404 here usually means a wrong or missing token: the Archive
            # answers 404, not 401, on purpose. Never echo the request headers.
            raise UnexpectedResponse(
                f"{method} {path} answered HTTP {response.status_code}: {response.text[:200]!r}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise UnexpectedResponse(f"{method} {path} did not answer JSON") from exc
        if not isinstance(body, dict):
            raise UnexpectedResponse(
                f"{method} {path} answered JSON that is not an object"
            )
        return body

    def read_pages(self, ids: Iterable[int]) -> Dict[int, dict]:
        """Live pages by id, at most 100 ids per call. A page that is not live is absent."""
        wanted = sorted(set(ids))
        found: Dict[int, dict] = {}
        for start in range(0, len(wanted), 100):
            chunk = wanted[start : start + 100]
            body = self._send(
                "GET",
                "/internal/export/pages",
                params={"ids": ",".join(str(i) for i in chunk), "limit": 100},
            )
            pages = body.get("pages")
            if not isinstance(pages, list):
                raise UnexpectedResponse("export/pages answered no 'pages' list")
            for page in pages:
                if page.get("id") in chunk:
                    found[int(page["id"])] = page
        return found

    def reset_video_index(self) -> None:
        """Forget the page list read for `replacement-video`; run_rows() calls
        this first, so one run never reads a list older than itself."""
        self._video_index = None

    def pages_with_video(self, video_id: str) -> List[dict]:
        """Live pages whose video is `video_id`, for `replacement-video`.

        There is no route that finds a page by video id, and a replacement
        page's id cannot be known before it exists, so this reads the page
        list the same read-only way `scripts/wrong_page_screen.py` does:
        `GET /internal/export/pages`, 500 metadata rows per request, no
        transcripts. It reads the whole list once per run and keeps only a
        small dict per page, so later calls cost nothing.
        """
        if self._video_index is None:
            index: Dict[str, List[dict]] = {}
            after_id = 0
            while True:
                body = self._send(
                    "GET",
                    "/internal/export/pages",
                    params={"after_id": after_id, "limit": 500},
                )
                pages = body.get("pages")
                if not isinstance(pages, list):
                    raise UnexpectedResponse("export/pages answered no 'pages' list")
                for page in pages:
                    small = {
                        "id": page.get("id"),
                        "slug": page.get("slug"),
                        "gov_id": page.get("gov_id"),
                    }
                    for found in page_video_ids(page):
                        index.setdefault(found, []).append(small)
                after_id = body.get("next_after_id")
                if after_id is None:
                    break
            self._video_index = index
        return list(self._video_index.get(video_id, []))

    def override(self, page_id: int, gov_id: str, *, dry_run: bool) -> dict:
        if not dry_run:
            self.writes.append(f"override page {page_id} -> {gov_id}")
        return self._send(
            "POST",
            "/internal/jurisdiction/override",
            params={
                "ids": str(page_id),
                "gov_id": gov_id,
                "dry_run": "true" if dry_run else "false",
            },
        )

    def delete(self, slug: str, *, dry_run: bool) -> dict:
        if not dry_run:
            self.writes.append(f"delete {slug}")
        return self._send(
            "POST",
            "/internal/admin/delete-pages",
            params={"dry_run": "true" if dry_run else "false"},
            json={"slugs": [slug]},
        )


# ---------------------------------------------------------------------------
# Deciding a row
# ---------------------------------------------------------------------------


@dataclass
class Context:
    live: Dict[int, dict]
    status: Optional[StatusIndex] = None
    today: dt.date = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc).date()
    )
    max_status_age_days: int = MAX_STATUS_AGE_DAYS
    apply: bool = False
    allow_deletes: bool = False
    # video id -> the live pages that carry it (ArchiveClient.pages_with_video).
    # None means "cannot look", and a `replacement-video` row is then refused.
    find_video: Optional[Callable[[str], List[dict]]] = None


def _live_gov(page: dict) -> str:
    return (page.get("gov_id") or "").strip()


def _expected_matches(row: Row, page: dict) -> Optional[str]:
    """None when the live page matches the row's expectations, else why not."""
    if row.expected_slug and page.get("slug") != row.expected_slug:
        return (
            f"slug is now {page.get('slug')!r}, the row expected {row.expected_slug!r}"
        )
    live_gov = _live_gov(page)
    expected = (
        "" if row.expected_current_gov_id == NO_GOV else row.expected_current_gov_id
    )
    if live_gov != expected:
        return (
            f"government id is now {live_gov or NO_GOV!r}, the row expected "
            f"{row.expected_current_gov_id!r}"
        )
    return None


def check_requirements(row: Row, ctx: Context) -> Optional[str]:
    """None when every `requires` condition holds, else the first one that does not."""
    page = ctx.live.get(row.page_id) or {}
    for kind, arg in row.requires:
        if kind == "video-gone":
            problem = _video_gone_unmet(row, page, arg, ctx)
            if problem:
                return problem
        elif kind == "replacement-video":
            problem = _replacement_video_unmet(row, page, arg, ctx)
            if problem:
                return problem
    return None


def _status_for(row: Row, page: dict, ctx: Context) -> Optional[Tuple[str, dt.date]]:
    if ctx.status is None:
        return None
    video_id = extract_video_id(page.get("video_url") or "") or extract_video_id(
        page.get("source_url_normalized") or ""
    )
    return ctx.status.lookup(row.page_id, video_id)


def _video_gone_unmet(row: Row, page: dict, arg: str, ctx: Context) -> Optional[str]:
    """None when the video is shown gone: by a person's dated check (`arg`),
    or, with no `arg`, by a recent status file."""
    found = _status_for(row, page, ctx)
    if arg:
        who, checked = parse_human_check(arg)  # validated when the sheet was read
        age = (ctx.today - checked).days
        if age < 0:
            return f"the recorded check by {who} is dated {checked}, in the future"
        if age > ctx.max_status_age_days:
            return (
                f"the check by {who} on {checked} is {age} days old "
                f"(limit {ctx.max_status_age_days}): look again and re-date it"
            )
        # A status file that is NEWER than the person's check and says the
        # video is alive overrules it: a private video can be made public.
        if found is not None:
            status, status_date = found
            if status_date > checked and status not in GONE_STATUSES:
                return (
                    f"a status check on {status_date} says {status!r}, newer than "
                    f"the check by {who} on {checked}"
                )
        return None
    if ctx.status is None:
        return "video-gone needs a checked status file (--video-status)"
    if found is None:
        return "the status file has no check of this page's video"
    status, checked = found
    age = (ctx.today - checked).days
    if age > ctx.max_status_age_days:
        return f"the video check is {age} days old (limit {ctx.max_status_age_days})"
    if status not in GONE_STATUSES:
        return f"the video check on {checked} says {status!r}, not gone"
    return None


def _replacement_video_unmet(
    row: Row, page: dict, video_id: str, ctx: Context
) -> Optional[str]:
    """None when the live Archive holds another page for `video_id`, filed
    under the same government as the page this row would delete."""
    if ctx.find_video is None:
        return (
            "replacement-video needs a live read of the Archive, and none is available"
        )
    holders = [p for p in ctx.find_video(video_id) if p.get("id") != row.page_id]
    if not holders:
        return f"no live page has video {video_id} yet: ingest the replacement first"
    mine = _live_gov(page)
    if any(_live_gov(p) == mine for p in holders):
        return None
    filed = sorted({_live_gov(p) or NO_GOV for p in holders})
    return (
        f"video {video_id} is live on page {holders[0].get('id')}, but under "
        f"{', '.join(filed)}, not this page's {mine or NO_GOV}"
    )


def decide(row: Row, ctx: Context) -> Tuple[str, str]:
    """Everything that can be decided from the sheet and the live read alone.

    Returns (outcome, detail). An outcome of WOULD_REKEY or WOULD_DELETE means
    "eligible: now try it as a dry run". Nothing here calls a write endpoint.
    """
    if row.rejected:
        return SKIP_REJECTED, "ryan_decision is reject"

    page = ctx.live.get(row.page_id)
    if page is None:
        if row.action == "delete":
            return ALREADY_DONE, "the page is not live any more"
        return REFUSED_MISSING, "no live page has this id"

    if (
        row.action == "rekey"
        and row.target_gov_id
        and _live_gov(page) == row.target_gov_id
    ):
        return ALREADY_DONE, f"the page already carries {row.target_gov_id}"
    stale = _expected_matches(row, page)
    if stale:
        return REFUSED_STALE, stale

    if row.action == "rekey" and not row.target_gov_id:
        # An approved row can still land here (a state commission Ryan will
        # not mint, for one): the override route needs a registry id, so the
        # row's evidence carries the path that does apply.
        return SKIP_BLOCKED, (
            "target_gov_id is blank: no registry id to write. "
            "Read the row's evidence for the path that applies"
        )
    if row.action == "delete" and not row.approved:
        return SKIP_AWAITING, "a delete needs ryan_decision=approve"
    if row.action == "rekey" and row.needs_ryan and not row.approved:
        return SKIP_AWAITING, "needs_ryan=yes and ryan_decision is blank"

    unmet = check_requirements(row, ctx)
    if unmet:
        return REFUSED_REQUIRES, unmet

    if row.action == "delete":
        if ctx.apply and not ctx.allow_deletes:
            return SKIP_NO_DELETES, "add --allow-deletes to apply an approved delete"
        return WOULD_DELETE, f"delete /m/{page.get('slug')}"
    return WOULD_REKEY, f"{_live_gov(page) or NO_GOV} -> {row.target_gov_id}"


# ---------------------------------------------------------------------------
# Trying a row against the Archive
# ---------------------------------------------------------------------------


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise UnexpectedResponse(message)


def check_rekey_answer(answer: dict, row: Row, live: dict, *, dry_run: bool) -> str:
    """Validate an override answer. Returns "already" when nothing would change."""
    _expect(
        answer.get("dry_run") is dry_run, "override answered the wrong dry_run mode"
    )
    _expect(
        answer.get("gov_id") == row.target_gov_id,
        "override answered a different gov_id",
    )
    _expect(not answer.get("missing_ids"), "override says the page id is missing")
    changed = answer.get("changed") or []
    already = answer.get("already_overridden") or []
    if not changed and len(already) == 1 and dry_run:
        return "already"
    _expect(len(changed) == 1, f"override would change {len(changed)} pages, not 1")
    entry = changed[0]
    _expect(
        entry.get("meeting_page_id") == row.page_id, "override named a different page"
    )
    _expect(
        (entry.get("gov_id_before") or "") == _live_gov(live),
        "override saw a different current gov_id than the live read: the page changed mid-run",
    )
    _expect(
        entry.get("gov_id_after") == row.target_gov_id,
        "override would write a different gov_id",
    )
    if dry_run:
        _expect(answer.get("would_update") == 1, "override would_update is not 1")
    else:
        _expect(answer.get("updated") == 1, "override updated is not 1")
    return "changed"


def check_delete_answer(answer: dict, row: Row, live: dict, *, dry_run: bool) -> None:
    _expect(
        answer.get("dry_run") is dry_run, "delete-pages answered the wrong dry_run mode"
    )
    found = answer.get("found") or []
    _expect(not answer.get("not_found"), "delete-pages did not find the slug")
    _expect(len(found) == 1, f"delete-pages found {len(found)} pages, not 1")
    _expect(
        found[0].get("slug") == live.get("slug"), "delete-pages found a different slug"
    )
    _expect(
        found[0].get("source_url_normalized") == live.get("source_url_normalized"),
        "delete-pages found a page with a different source address",
    )
    if not dry_run:
        _expect(answer.get("deleted") == 1, "delete-pages deleted is not 1")


@dataclass
class Result:
    row: Row
    outcome: str
    detail: str
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    draft_rules: list = field(default_factory=list)


def try_row(row: Row, ctx: Context, client: ArchiveClient) -> Result:
    """Run one eligible row: dry run first, then (under --apply) the write and a re-read."""
    live = ctx.live[row.page_id]
    if row.action == "rekey":
        dry = client.override(row.page_id, row.target_gov_id, dry_run=True)
        verdict = check_rekey_answer(dry, row, live, dry_run=True)
        rules = dry.get("tenant_override_rules") or []
        if verdict == "already":
            return Result(
                row, ALREADY_DONE, "already a manual override of this government", live
            )
        if not ctx.apply:
            return Result(row, WOULD_REKEY, _rekey_detail(dry), live, draft_rules=rules)
        done = client.override(row.page_id, row.target_gov_id, dry_run=False)
        check_rekey_answer(done, row, live, dry_run=False)
        after = client.read_pages([row.page_id]).get(row.page_id)
        _expect(after is not None, "the page vanished after the re-key")
        _expect(
            _live_gov(after) == row.target_gov_id,
            "the page does not show the new gov_id",
        )
        _expect(
            after.get("jurisdiction_confidence") == MANUAL_OVERRIDE,
            "the page did not become a manual override",
        )
        return Result(
            row,
            REKEYED,
            _rekey_detail(done),
            live,
            after,
            done.get("tenant_override_rules") or [],
        )

    dry = client.delete(live["slug"], dry_run=True)
    check_delete_answer(dry, row, live, dry_run=True)
    if not ctx.apply:
        return Result(row, WOULD_DELETE, f"would delete /m/{live['slug']}", live)
    done = client.delete(live["slug"], dry_run=False)
    check_delete_answer(done, row, live, dry_run=False)
    _expect(
        row.page_id not in client.read_pages([row.page_id]),
        "the page is still live after the delete",
    )
    return Result(row, DELETED, f"deleted /m/{live['slug']}", live, {})


def _rekey_detail(answer: dict) -> str:
    changed = (answer.get("changed") or [{}])[0]
    return (
        f"{changed.get('gov_id_before') or NO_GOV} -> {answer.get('gov_id')} "
        f"({answer.get('gov_name')}); shown as {changed.get('jurisdiction_after')!r}"
    )


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def _log_row(result: Result, now: str) -> Dict[str, str]:
    before, after = result.before, result.after
    return {
        "time_utc": now,
        "page_id": str(result.row.page_id),
        "action": result.row.action,
        "outcome": result.outcome,
        "detail": result.detail,
        "slug": before.get("slug") or result.row.expected_slug,
        "target_gov_id": result.row.target_gov_id,
        "before_gov_id": _live_gov(before) if before else "",
        "before_jurisdiction": before.get("jurisdiction") or "",
        "before_confidence": before.get("jurisdiction_confidence") or "",
        "after_gov_id": _live_gov(after) if after else "",
        "after_jurisdiction": after.get("jurisdiction") or "",
        "after_confidence": after.get("jurisdiction_confidence") or "",
        "draft_tenant_rules": json.dumps(result.draft_rules)
        if result.draft_rules
        else "",
    }


class LogWriter:
    """Appends one flushed line per row, so stopping at any moment loses nothing."""

    def __init__(self, path: Optional[Path]) -> None:
        self._fh = None
        self._writer = None
        if path is not None:
            self._fh = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._fh, fieldnames=LOG_COLUMNS)
            self._writer.writeheader()
            self._fh.flush()

    def write(self, result: Result) -> None:
        if self._writer is None:
            return
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self._writer.writerow(_log_row(result, now))
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()


@dataclass
class RunReport:
    results: List[Result] = field(default_factory=list)
    halted: Optional[str] = None
    eligible_left: int = 0


def run_rows(
    rows: List[Row],
    client: ArchiveClient,
    *,
    apply: bool = False,
    allow_deletes: bool = False,
    batch_size: int = 5,
    only_ids: Optional[set] = None,
    status: Optional[StatusIndex] = None,
    log: Optional[LogWriter] = None,
    pause_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    today: Optional[dt.date] = None,
    max_status_age_days: int = MAX_STATUS_AGE_DAYS,
) -> RunReport:
    """Decide every row from a fresh live read, then try the eligible ones."""
    report = RunReport()
    chosen = [r for r in rows if only_ids is None or r.page_id in only_ids]
    reset = getattr(client, "reset_video_index", None)
    if reset is not None:
        reset()

    wanted = {r.page_id for r in chosen if not r.rejected}
    try:
        live = client.read_pages(wanted)
    except UnexpectedResponse as exc:
        report.halted = str(exc)
        return report

    ctx = Context(
        live=live,
        status=status,
        apply=apply,
        allow_deletes=allow_deletes,
        max_status_age_days=max_status_age_days,
        find_video=getattr(client, "pages_with_video", None),
    )
    if today is not None:
        ctx.today = today

    written = 0
    for row in chosen:
        try:
            outcome, detail = decide(row, ctx)
        except UnexpectedResponse as exc:
            # The page list read for `replacement-video` failed.
            result = Result(row, HALTED, str(exc), live.get(row.page_id) or {})
            report.results.append(result)
            if log:
                log.write(result)
            report.halted = f"page {row.page_id}: {exc}"
            return report
        if outcome not in (WOULD_REKEY, WOULD_DELETE):
            result = Result(row, outcome, detail, live.get(row.page_id) or {})
        elif apply and written >= batch_size:
            report.eligible_left += 1
            result = Result(
                row,
                SKIP_BATCH_FULL,
                "run again to continue",
                live.get(row.page_id) or {},
            )
        else:
            try:
                result = try_row(row, ctx, client)
            except UnexpectedResponse as exc:
                result = Result(row, HALTED, str(exc), live.get(row.page_id) or {})
                report.results.append(result)
                if log:
                    log.write(result)
                report.halted = f"page {row.page_id}: {exc}"
                return report
            if apply and result.outcome in (REKEYED, DELETED):
                written += 1
                if written < batch_size:
                    sleep(pause_seconds)
        report.results.append(result)
        if log:
            log.write(result)
    return report


# ---------------------------------------------------------------------------
# Summary, in plain words
# ---------------------------------------------------------------------------


def summarise(report: RunReport, *, apply: bool) -> str:
    lines: List[str] = []
    mode = "APPLY" if apply else "DRY RUN (nothing was changed)"
    lines.append(f"Mode: {mode}")
    lines.append("")
    lines.append("One line per row:")
    for r in report.results:
        lines.append(
            f"  page {r.row.page_id:>6}  {r.row.action:<6}  {r.outcome:<28} {r.detail}"
        )
    lines.append("")
    counts: Dict[str, int] = {}
    for r in report.results:
        counts[r.outcome] = counts.get(r.outcome, 0) + 1
    lines.append("Result | Count of rows")
    for outcome, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"{OUTCOME_LABELS.get(outcome, outcome)} | {n}")
    if report.eligible_left:
        lines.append("")
        lines.append(
            f"{report.eligible_left} more row(s) are eligible. Run the same command again to continue."
        )
    if report.halted:
        lines.append("")
        lines.append(f"STOPPED: {report.halted}")
        lines.append(
            "No later row was tried. Read the log, then decide before running again."
        )
    rules = [(r.row.page_id, rule) for r in report.results for rule in r.draft_rules]
    if rules:
        lines.append("")
        lines.append(
            "Draft tenant rules the Archive produced (do NOT commit any for a host that serves more than one government):"
        )
        for page_id, rule in rules:
            lines.append(f"  page {page_id}: {rule}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# check: the sheet against the registry and (optionally) a local export
# ---------------------------------------------------------------------------


def check_sheet(
    rows: List[Row],
    *,
    registry_lookup: Optional[Callable[[str], object]] = None,
    inventory: Optional[Dict[int, dict]] = None,
) -> Tuple[List[str], Dict[str, int]]:
    """Problems that need fixing in the sheet, and counts of each row's state."""
    problems: List[str] = []
    counts: Dict[str, int] = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    for row in rows:
        if row.target_gov_id and registry_lookup is not None:
            if registry_lookup(row.target_gov_id) is None:
                problems.append(
                    f"{row.origin}: target_gov_id {row.target_gov_id!r} is not a government the Archive knows"
                )
        if inventory is None:
            continue
        page = inventory.get(row.page_id)
        if page is None:
            bump("page not in the export")
            continue
        if (
            row.action == "rekey"
            and row.target_gov_id
            and _live_gov(page) == row.target_gov_id
        ):
            bump("already carries the target")
            continue
        stale = _expected_matches(row, page)
        bump(
            "stale: the export no longer matches the row"
            if stale
            else "matches the export"
        )
        if stale:
            problems.append(f"{row.origin}: page {row.page_id}: {stale}")
    return problems, counts


def read_inventory(path: Path) -> Dict[int, dict]:
    """A local export from scripts/export_meeting_inventory.py, shaped like the live read."""
    pages: Dict[int, dict] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            try:
                page_id = int(raw["page_id"])
            except (KeyError, ValueError):
                continue
            slug = (raw.get("archive_url") or "").rsplit("/m/", 1)[-1]
            pages[page_id] = {
                "id": page_id,
                "slug": slug,
                "gov_id": raw.get("gov_id") or "",
                "jurisdiction": raw.get("page_display_name") or "",
                "jurisdiction_confidence": raw.get("jurisdiction_confidence") or "",
                "source_url_normalized": raw.get("source_url") or "",
                "video_url": raw.get("video_url") or "",
            }
    return pages


# ---------------------------------------------------------------------------
# gone-videos: rows built ONLY from a checked status file
# ---------------------------------------------------------------------------


def build_gone_video_rows(
    pool: List[Dict[str, str]],
    status: StatusIndex,
    *,
    today: dt.date,
    max_status_age_days: int = MAX_STATUS_AGE_DAYS,
    skip_page_ids: Iterable[int] = (),
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    """Delete rows for pool pages a recent, checked status file calls gone.

    A page with no check, an old check, or any status other than deleted,
    private or malformed gets no row. Every row is needs_ryan=yes with a blank
    ryan_decision: this tool never approves a delete on its own.
    """
    skip = set(skip_page_ids)
    out: List[Dict[str, str]] = []
    counts: Dict[str, int] = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    for entry in pool:
        try:
            page_id = int(entry["page_id"])
        except (KeyError, ValueError):
            bump("pool row without a page id")
            continue
        video_id = extract_video_id(entry.get("video_url") or "")
        found = status.lookup(page_id, video_id)
        if found is None:
            bump("not checked yet")
            continue
        state, checked = found
        if (today - checked).days > max_status_age_days:
            bump("check too old to trust")
            continue
        if state not in GONE_STATUSES:
            bump(f"video is {state.replace('_', ' ')}: no row")
            continue
        if page_id in skip:
            bump("already on the committed sheet")
            continue
        bump(f"video is gone ({state}): row written")
        slug = (entry.get("archive_url") or "").rsplit("/m/", 1)[-1]
        out.append(
            {
                "page_id": str(page_id),
                "action": "delete",
                "target_gov_id": "",
                "expected_current_gov_id": (entry.get("gov_id") or "").strip()
                or NO_GOV,
                "expected_slug": slug,
                "requires": "video-gone",
                "confidence": "high",
                "needs_ryan": "yes",
                "ryan_decision": "",
                "source_entry": "13 archived YouTube pages point at a video that is gone",
                "shown_today": f"{entry.get('government') or ''} - {entry.get('title') or '(no title)'}",
                "reason": f"The video's own check on {checked} says {state}, and the page holds no transcript.",
                "evidence": f"video {video_id or '(no id)'}; status file check {checked}: {state}; page {entry.get('archive_url') or ''}",
            }
        )
    return out, counts


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _is_local(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "testserver")


def resolve_base_url(cli_value: Optional[str], environ=os.environ) -> str:
    if cli_value:
        return cli_value.rstrip("/")
    if environ.get("ARCHIVE_BASE_URL"):
        return environ["ARCHIVE_BASE_URL"].rstrip("/")
    if environ.get("PORT"):
        return f"http://127.0.0.1:{environ['PORT']}"
    return ""


def _cmd_check(args: argparse.Namespace) -> int:
    rows, problems = read_worklists([Path(p) for p in args.worklists])
    from app.utils.gov_registry import government_for_id

    inventory = read_inventory(Path(args.inventory)) if args.inventory else None
    more, counts = check_sheet(
        rows, registry_lookup=government_for_id, inventory=inventory
    )
    problems.extend(more)

    print(f"Rows read: {len(rows)}")
    by_action: Dict[str, int] = {}
    for r in rows:
        by_action[r.action] = by_action.get(r.action, 0) + 1
    print("Action | Count of rows")
    for action, n in sorted(by_action.items()):
        print(f"{action} | {n}")
    print("Needs Ryan | Count of rows")
    print(f"yes | {sum(1 for r in rows if r.needs_ryan)}")
    print(f"no | {sum(1 for r in rows if not r.needs_ryan)}")
    print("Ryan's decision | Count of rows")
    for label, wanted in (("approve", "approve"), ("reject", "reject"), ("blank", "")):
        print(f"{label} | {sum(1 for r in rows if r.ryan_decision == wanted)}")
    if counts:
        print("Against the export | Count of rows")
        for name, n in sorted(counts.items()):
            print(f"{name} | {n}")
    if problems:
        print("\nProblems to fix:")
        for p in problems:
            print(f"  {p}")
        return 1
    print("\nNo problems found.")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    rows, problems = read_worklists([Path(p) for p in args.worklists])
    if problems:
        print("The sheet has problems. Run `check` and fix them first:")
        for p in problems:
            print(f"  {p}")
        return 1

    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    if not token:
        print("ARCHIVE_INGEST_TOKEN is not set in the environment.", file=sys.stderr)
        return 1
    base_url = resolve_base_url(args.base_url)
    if not base_url:
        print(
            "No Archive address. Pass --base-url, or set ARCHIVE_BASE_URL, or run on the "
            "Archive's Render shell where $PORT is set.",
            file=sys.stderr,
        )
        return 1
    if args.apply and not _is_local(base_url) and not args.allow_remote:
        print(
            f"Refusing to --apply against {base_url}: it is not this machine. Run this on the "
            "Archive's Render shell, or add --allow-remote if you really mean it.",
            file=sys.stderr,
        )
        return 1
    if args.allow_deletes and not args.apply:
        print(
            "--allow-deletes only means something together with --apply.",
            file=sys.stderr,
        )
        return 1
    if not 1 <= args.batch_size <= 25:
        print("--batch-size must be between 1 and 25.", file=sys.stderr)
        return 1

    status = None
    if args.video_status:
        status, status_problems = read_status_file(Path(args.video_status))
        if status_problems:
            print("The status file has problems:")
            for p in status_problems:
                print(f"  {p}")
            return 1

    only = (
        {int(x) for x in args.only_ids.split(",") if x.strip()}
        if args.only_ids
        else None
    )
    log_path = (
        Path(args.log)
        if args.log
        else Path(
            f"wrong_page_repair_log_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
        )
    )
    log = LogWriter(log_path)
    client = ArchiveClient(base_url, token)
    print(
        f"Archive: {base_url}   Mode: {'APPLY' if args.apply else 'dry run'}   Log: {log_path}\n"
    )
    try:
        report = run_rows(
            rows,
            client,
            apply=args.apply,
            allow_deletes=args.allow_deletes,
            batch_size=args.batch_size,
            only_ids=only,
            status=status,
            log=log,
            pause_seconds=args.pause_seconds,
            max_status_age_days=args.max_status_age_days,
        )
    finally:
        log.close()
    print(summarise(report, apply=args.apply))
    return 2 if report.halted else 0


def _cmd_gone_videos(args: argparse.Namespace) -> int:
    status, problems = read_status_file(Path(args.status_file))
    if problems:
        print("The status file has problems:")
        for p in problems:
            print(f"  {p}")
        return 1
    with open(args.pool, newline="", encoding="utf-8") as fh:
        pool = list(csv.DictReader(fh))
    skip: List[int] = []
    for path in args.exclude_worklist or []:
        existing, _ = read_worklists([Path(path)])
        skip.extend(r.page_id for r in existing)
    today = dt.datetime.now(dt.timezone.utc).date()
    rows, counts = build_gone_video_rows(
        pool,
        status,
        today=today,
        max_status_age_days=args.max_status_age_days,
        skip_page_ids=skip,
    )
    print(f"Pool pages: {len(pool)}")
    print("Result | Count of pool pages")
    for name, n in sorted(counts.items()):
        print(f"{name} | {n}")
    if rows:
        out = Path(args.out)
        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=WORKLIST_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(
            f"\nWrote {len(rows)} delete row(s) to {out}. Every one is needs_ryan=yes with no decision."
        )
    else:
        print(
            "\nNo row written: no page has a recent check that says its video is gone."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check", help="find faults in the sheet (reads no production data)"
    )
    check.add_argument("worklists", nargs="+")
    check.add_argument(
        "--inventory", help="a local export CSV to compare every row with"
    )
    check.set_defaults(func=_cmd_check)

    run = sub.add_parser("run", help="dry run by default; --apply writes")
    run.add_argument("worklists", nargs="+")
    run.add_argument(
        "--apply",
        action="store_true",
        help="write the re-keys (deletes need --allow-deletes too)",
    )
    run.add_argument(
        "--allow-deletes", action="store_true", help="also apply approved delete rows"
    )
    run.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="most rows written per run (default 5)",
    )
    run.add_argument(
        "--only-ids", help="comma-separated page ids; act on these rows only"
    )
    run.add_argument("--video-status", help="a checked status file from the drip Mac")
    run.add_argument("--max-status-age-days", type=int, default=MAX_STATUS_AGE_DAYS)
    run.add_argument(
        "--base-url",
        help="the Archive's address (default: ARCHIVE_BASE_URL, then http://127.0.0.1:$PORT)",
    )
    run.add_argument(
        "--allow-remote",
        action="store_true",
        help="let --apply talk to an address that is not this machine",
    )
    run.add_argument("--pause-seconds", type=float, default=1.0)
    run.add_argument("--log", help="where to write the before/after log CSV")
    run.set_defaults(func=_cmd_run)

    gone = sub.add_parser(
        "gone-videos", help="build delete rows from a checked status file"
    )
    gone.add_argument(
        "pool",
        help="the pool CSV (page_id, gov_id, title, video_url, archive_url, ...)",
    )
    gone.add_argument("status_file")
    gone.add_argument("--out", required=True)
    gone.add_argument(
        "--exclude-worklist",
        action="append",
        help="a sheet whose page ids to leave out",
    )
    gone.add_argument("--max-status-age-days", type=int, default=MAX_STATUS_AGE_DAYS)
    gone.set_defaults(func=_cmd_gone_videos)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
