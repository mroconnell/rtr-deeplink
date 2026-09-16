"""WO-259 (2026-09-11): full access-ladder re-scan of the homepage for the
964 governments of 5,000+ in
`~/Documents/rtr-business/research/wo174_leftover_5k_plus.csv` flagged
`step_full_ladder=yes` -- part of the same conductor wave as WO-260/261/262,
each owning a different `step_*` column on the same file (mine is
`step_full_ladder`; do not touch the others).

These 964 governments were rejected `no-platform-link-found` by an earlier,
cruder pass: a plain HTTP fetch of the domain plus a link scan, nothing
more. Nothing has ever fetched their front page with browser headers or a
real (headless) browser, so a JS-rendered nav menu or a plain-client block
has never been seen through -- exactly the gap WO-133/WO-141/WO-147 already
found and fixed for other candidate lists (see docs/COVERAGE_HANDOVER.md
§5.1 and docs/BREADTH_SWEEP_BRIEF.md).

Method, reusing existing modules rather than re-deriving the ladder:

1. **Ladder** -- `wo147_access_ladder_sweep.run_access_ladder()`, imported
   unchanged: plain HTTP (honest headers) -> browser headers only after a
   403 or a dropped connection (never after a 404) -> headless only when an
   earlier rung got a real page with no visible meeting-shaped link at all
   -> stop at a human-verification challenge marker. One hop into a
   meeting/agenda/council/board-hinted link is built into that function
   already (`find_hop_links`/`find_platform_link`), including the WO-228
   calendar-entry follow-hop. `prior_url` is deliberately left blank so the
   ladder starts at the government's own bare domain (its front page) --
   `hub_url`, where this CSV has one, is a hint some *earlier* pass left
   behind, not what this WO's brief asks to be re-tested.
2. **Vendor footer hint** -- a front page that mentions a known platform
   vendor's name in its own body text (a "Powered by X" style footer badge)
   but has no clickable per-tenant link is recorded in the report's
   `vendor_hint` column even when rung (1) otherwise finds nothing --
   chasing that hint into a real tenant subdomain is `step_vendor_guess`'s
   job (a different WO in this wave), not this one's.
3. **Resolve** -- a found (platform, url) hit is handed to
   `wo134_confirmed_hits_ingest.process_row()` UNCHANGED, same as every
   other sweep in this repo (locate_platform_url -> resolve_seed ->
   ingest/queue/pin).
4. **Mandatory hand-read gate (Ryan, 2026-09-11)** -- `IDENTITY_CHECK_HOOK`
   (wired to `wo134.process_row` for exactly this purpose, see that
   module's own docstring on the hook) runs, in order: (a) the automatic
   wrong-government check (`wo146_api_relist_sweep._looks_wrong_government`
   -- state/kind/off-mission-entity mismatches), (b) the automatic phrase
   list (`app.utils.video_hand_check.classify_video_hand_check` -- Kind A/
   Kind B). Anything BOTH checks pass through still needs an actual human
   read of the title/channel per Ryan's rule -- rather than auto-approve,
   this parks it in `wo259_pending_hand_read.csv` and reports
   `awaiting_hand_read`; a human (this session, reading the pending file
   directly) records a one-line reason in `wo259_hand_read_decisions.csv`
   (approve/reject + reason), and a second run of this same script picks
   the decision up and finishes the ingest/queue for an approved row (see
   `wo230_agendacenter_followup.py`'s identical two-stage pattern -- not
   re-derived here, this is the same shape). No automated verdict passes
   without a decision row.
5. **Tier-3 candidates are probed before they reach the real queue file**
   (CLAUDE.md's "probe before queue" rule) -- routed through TIER3_HANDLER
   to `wo259_tier3_pending.csv`, finished by `stage2_finish_tier3()` at the
   end of a run (same shape as `wo187_headless_challenge_sweep.py`'s own
   `stage2_finish_tier3()`).
6. **Research file** -- every outcome writes back to
   `jurisdiction_coverage.csv` per ENUMERATION_METHODS.md §158, via the
   locking/re-read/atomic-replace helper already built for this
   (`wo127_civicplus_pipeline._coverage_read_modify_write`), through two
   small platform-agnostic wrapper functions in this file (the CivicPlus-
   specific `update_coverage_on_success`/`update_coverage_calendar_
   confirmed` helpers in that module hardcode `suspected_calendar_provider
   = "civicplus"` regardless of what was actually found, which is wrong
   for a multi-platform sweep like this one -- see `jc_update_success()`'s
   own docstring below).

Run from rtr-deeplink repo root with the shared venv active:
    python3 scripts/export_meeting_inventory.py --out-dir /tmp/wo259_inventory --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo259_scratch.db" \\
        .venv/bin/python scripts/wo259_full_ladder_scan.py [--limit N]

Resumable: a gov_id whose most recent report row has a real terminal
outcome (anything other than `awaiting_hand_read`) is skipped on restart;
one still `awaiting_hand_read` is retried every run so a freshly-recorded
decision takes effect on the next pass.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
import scripts.wo147_access_ladder_sweep as wo147  # noqa: E402
from scripts.wo127_civicplus_pipeline import (  # noqa: E402
    _coverage_read_modify_write,
    _safe_coverage_call,
    update_coverage_reject_reason,
)
from scripts.wo146_api_relist_sweep import _looks_wrong_government  # noqa: E402
from app.platforms import queue_probe  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
CANDIDATES_CSV = RESEARCH_DIR / "wo174_leftover_5k_plus.csv"
REPORT_CSV = RESEARCH_DIR / "wo259_report.csv"
HOST_ACCESS_CSV = RESEARCH_DIR / "wo259_host_access_modes.csv"
HAND_CHECK_LOG_CSV = RESEARCH_DIR / "wo259_hand_check_log.csv"
PENDING_HAND_READ_CSV = RESEARCH_DIR / "wo259_pending_hand_read.csv"
HAND_READ_DECISIONS_CSV = RESEARCH_DIR / "wo259_hand_read_decisions.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo259_tier3_pending.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo259_inventory/meeting_inventory.csv")

TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)
TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"

GOV_DELAY_SECONDS = 0.75  # between governments (different hosts -- no
# forced same-host delay needed; run_access_ladder already sleeps 2s
# between its own retries to the SAME host)
CONSECUTIVE_ERROR_HALT = 6

_REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "prior_reject_reason",
    "host",
    "access_mode",
    "rung_answered",
    "vendor_hint",
    "platform_found",
    "netloc",
    "outcome",
    "reject_reason",
    "reject_class",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "waf_family",
    "note",
]

_VENDOR_NAME_HINTS = [
    "civicplus",
    "granicus",
    "civicclerk",
    "escribe",
    "legistar",
    "swagit",
    "primegov",
    "iqm2",
    "cablecast",
    "telvue",
    "champds",
    "clerkbase",
    "clerkshq",
    "municode",
    "civicweb",
    "boxcast",
    "vimeo",
    "proudcity",
]


def vendor_hints_in_body(html_text: Optional[str]) -> str:
    if not html_text:
        return ""
    low = html_text.lower()
    return ",".join(v for v in _VENDOR_NAME_HINTS if v in low)


# --------------------------------------------------------------------------
# jurisdiction_coverage.csv writers -- platform-agnostic (see module
# docstring point 6 on why the CivicPlus-hardcoded helpers in
# wo127_civicplus_pipeline.py aren't reused for the success/confirmed
# cases here).
# --------------------------------------------------------------------------


def jc_update_platform_found(gov_id: str, platform: str, url: str) -> bool:
    def mutate(rows):
        matches = [r for r in rows if r.get("gov_id") == gov_id]
        if not matches:
            return False
        changed = False
        for m in matches:
            if (
                platform
                and not (m.get("suspected_meeting_link_provider") or "").strip()
            ):
                m["suspected_meeting_link_provider"] = platform
                changed = True
            if url and not (m.get("example_agenda_or_calendar_url") or "").strip():
                m["example_agenda_or_calendar_url"] = url
                changed = True
        return changed

    return _coverage_read_modify_write(mutate)


def jc_update_success(
    gov_id: str, *, meeting_url: str, platform: str, tier: str
) -> bool:
    """Platform-agnostic analogue of wo127_civicplus_pipeline.py's own
    update_coverage_on_success() -- that function unconditionally stamps
    `suspected_calendar_provider = "civicplus"` on a blank field, which is
    wrong here since this sweep finds Granicus/Legistar/escribe/YouTube/etc
    just as often. Sets `suspected_video_provider` to whatever platform was
    actually resolved instead, and never touches
    `suspected_calendar_provider`."""

    def mutate(rows):
        matches = [r for r in rows if r.get("gov_id") == gov_id]
        if not matches:
            return False
        changed = False
        for m in matches:
            if not (m.get("shares_video") or "").strip():
                m["shares_video"] = "True"
                changed = True
            if tier in ("tier1", "tier2") and not (m.get("transcribed") or "").strip():
                m["transcribed"] = "True"
                changed = True
            if meeting_url and not (m.get("example_meeting_url") or "").strip():
                m["example_meeting_url"] = meeting_url
                changed = True
            if platform and not (m.get("suspected_video_provider") or "").strip():
                m["suspected_video_provider"] = platform
                changed = True
            if (m.get("reject_reason") or "").strip() == "no-platform-link-found":
                m["reject_reason"] = ""
                changed = True
        return changed

    return _coverage_read_modify_write(mutate)


def jc_update_reject(gov_id: str, reason: str) -> bool:
    return update_coverage_reject_reason(gov_id, reason)


# --------------------------------------------------------------------------
# Hand-read gate: automatic checks first, then park for a real human read.
# --------------------------------------------------------------------------

_HAND_CHECK_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "platform",
    "kind",
    "reason",
    "title",
    "channel_text",
    "meeting_url",
    "video_url",
    "verdict",
]

_PENDING_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "platform",
    "meeting_url",
    "video_url",
    "title",
    "channel_text",
    "jurisdiction",
]

_DECISION_FIELDS = ["gov_id", "decision", "kind", "reason"]

_hand_read_decisions: Dict[str, dict] = {}
_pending_seen: set = set()


def load_hand_read_decisions() -> Dict[str, dict]:
    if not HAND_READ_DECISIONS_CSV.exists():
        return {}
    with HAND_READ_DECISIONS_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"]: r for r in csv.DictReader(f) if r.get("gov_id")}


def load_pending_seen() -> set:
    if not PENDING_HAND_READ_CSV.exists():
        return set()
    with PENDING_HAND_READ_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _append_csv(path: Path, fields, row: dict) -> None:
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def _log_hand_check(
    gov_id,
    name,
    state,
    gov_kind,
    platform,
    kind,
    reason,
    title,
    channel_text,
    meeting_url,
    video_url,
    verdict,
):
    _append_csv(
        HAND_CHECK_LOG_CSV,
        _HAND_CHECK_FIELDS,
        dict(
            gov_id=gov_id,
            name=name,
            state=state,
            gov_kind=gov_kind,
            platform=platform,
            kind=kind,
            reason=reason,
            title=title or "",
            channel_text=channel_text or "",
            meeting_url=meeting_url or "",
            video_url=video_url or "",
            verdict=verdict,
        ),
    )


def _park_pending(
    gov_id,
    name,
    state,
    gov_kind,
    platform,
    meeting_url,
    video_url,
    title,
    channel_text,
    jurisdiction,
):
    _append_csv(
        PENDING_HAND_READ_CSV,
        _PENDING_FIELDS,
        dict(
            gov_id=gov_id,
            name=name,
            state=state,
            gov_kind=gov_kind,
            platform=platform,
            meeting_url=meeting_url or "",
            video_url=video_url or "",
            title=title or "",
            channel_text=channel_text or "",
            jurisdiction=jurisdiction or "",
        ),
    )


def wo259_identity_hook(row, platform, result, final_seed, effective_title):
    """wo134.IDENTITY_CHECK_HOOK signature:
    hook(row, platform, result, final_seed, effective_title) -> Optional[str].
    A non-empty return skips this candidate (process_row's own `continue`);
    None accepts it. See this module's docstring point 4."""
    gov_id = row["gov_id"]
    name = row["unit_name"]
    state = row.get("state", "")
    gov_kind = row.get("gov_kind", "")

    wrong = _looks_wrong_government(
        {
            "state": state,
            "gov_kind": "municipality" if gov_kind == "township" else gov_kind,
        },
        {
            "jurisdiction": result.jurisdiction or "",
            "meeting_body": getattr(result, "meeting_body", "") or "",
            "title": effective_title or "",
        },
    )
    channel_text = " ".join(
        filter(
            None,
            [
                (getattr(result, "video_channel", None) or "").lstrip("@"),
                result.jurisdiction or "",
            ],
        )
    )
    if wrong:
        _log_hand_check(
            gov_id,
            name,
            state,
            gov_kind,
            platform,
            "kind-A-auto",
            wrong,
            effective_title,
            channel_text,
            final_seed,
            result.video_url,
            "auto-reject",
        )
        return f"AUTO-WRONG-GOV: {wrong}"

    hand = classify_video_hand_check(effective_title, channel_text, name, gov_kind)
    if hand:
        kind, reason = hand
        _log_hand_check(
            gov_id,
            name,
            state,
            gov_kind,
            platform,
            f"kind-{kind}",
            reason,
            effective_title,
            channel_text,
            final_seed,
            result.video_url,
            "auto-reject",
        )
        return f"AUTO-HAND-CHECK-{kind}: {reason}"

    decision = _hand_read_decisions.get(gov_id)
    if decision is not None:
        if (decision.get("decision") or "").strip().lower() == "approve":
            _log_hand_check(
                gov_id,
                name,
                state,
                gov_kind,
                platform,
                "ok",
                decision.get("reason", ""),
                effective_title,
                channel_text,
                final_seed,
                result.video_url,
                "approved",
            )
            return None
        _log_hand_check(
            gov_id,
            name,
            state,
            gov_kind,
            platform,
            decision.get("kind", "reject"),
            decision.get("reason", ""),
            effective_title,
            channel_text,
            final_seed,
            result.video_url,
            "rejected",
        )
        return f"HAND-READ-REJECTED: {decision.get('reason', '')}"

    if gov_id not in _pending_seen:
        _park_pending(
            gov_id,
            name,
            state,
            gov_kind,
            platform,
            final_seed,
            result.video_url,
            effective_title,
            channel_text,
            result.jurisdiction,
        )
        _pending_seen.add(gov_id)
    return (
        f"AWAITING-HAND-READ: parked in {PENDING_HAND_READ_CSV.name} "
        f"(title={effective_title!r}, channel={channel_text!r})"
    )


wo134.IDENTITY_CHECK_HOOK = wo259_identity_hook


# --------------------------------------------------------------------------
# Tier-3: probe before queue (CLAUDE.md's rule) -- own pending file,
# finished at the end of a run.
# --------------------------------------------------------------------------

_TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]

_tier3_pending_seen: Optional[set] = None


def _tier3_pending_seen_urls() -> set:
    global _tier3_pending_seen
    if _tier3_pending_seen is None:
        seen = set()
        if TIER3_PENDING_CSV.exists():
            with TIER3_PENDING_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("meeting_url", ""))
        _tier3_pending_seen = seen
    return _tier3_pending_seen


def wo259_tier3_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    if final_seed in _tier3_pending_seen_urls():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|wo259_full_ladder_scan|"
                f"{unit_name} -- WO-259 full-ladder find, gov_id={gov_id}"
            )
    _append_csv(
        TIER3_PENDING_CSV,
        _TIER3_PENDING_FIELDS,
        dict(
            gov_id=gov_id,
            platform=platform,
            meeting_url=final_seed,
            video_url=result.video_url or final_seed,
            source_url=hit_url,
            jurisdiction=result.jurisdiction or "",
            pin_row=pin_row,
        ),
    )
    _tier3_pending_seen_urls().add(final_seed)


wo134.TIER3_HANDLER = wo259_tier3_handler


async def stage2_finish_tier3():
    if not TIER3_PENDING_CSV.exists():
        print(f"No {TIER3_PENDING_CSV.name} -- no tier-3 candidates this run.")
        return 0, 0
    with TIER3_PENDING_CSV.open(newline="", encoding="utf-8") as f:
        pending_rows = list(csv.DictReader(f))
    if not pending_rows:
        return 0, 0
    print(f"\n{len(pending_rows)} tier-3 pending row(s) to probe.")

    existing_queue_urls = wo134._existing_tier3_queue_urls()
    existing_override_keys = wo134._existing_override_keys()

    accepted, rejected = 0, 0
    last_call_by_host: Dict[str, float] = {}
    for i, row in enumerate(pending_rows):
        host = urlparse(row["meeting_url"]).netloc
        last = last_call_by_host.get(host)
        if last is not None:
            remaining = 2.0 - (time.monotonic() - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        last_call_by_host[host] = time.monotonic()

        result = await queue_probe.probe_queue_entry(
            row["meeting_url"],
            video_url=row.get("video_url") or None,
            source_page_url=row.get("source_url") or None,
        )
        queue_probe.append_probe_row(
            queue_probe.DEFAULT_SIDECAR_PATH, result, caller="wo259"
        )
        print(
            f"[{i + 1}/{len(pending_rows)}] [{result.verdict}] {row['gov_id']} "
            f"{row['meeting_url']} -- {result.reason or f'{result.duration_seconds}s'}"
        )

        if result.verdict in ("accept", "flag-long"):
            accepted += 1
            queue_line = row["meeting_url"]
            if row.get("source_url"):
                queue_line = f"{queue_line}\t{row['source_url']}"
            if row["meeting_url"] not in existing_queue_urls:
                with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as qf:
                    qf.write(queue_line + "\n")
                existing_queue_urls.add(row["meeting_url"])
            pin_row = row.get("pin_row", "")
            if pin_row:
                parts = pin_row.split("|", 5)
                if len(parts) == 6:
                    tenant_host, match, gov_id, strength, source, evidence = parts
                    key = (tenant_host, match)
                    if key not in existing_override_keys:
                        is_new = not TENANT_OVERRIDES_CSV.exists()
                        with TENANT_OVERRIDES_CSV.open(
                            "a", newline="", encoding="utf-8"
                        ) as f:
                            w = csv.DictWriter(
                                f,
                                fieldnames=[
                                    "tenant_host",
                                    "match",
                                    "gov_id",
                                    "strength",
                                    "source",
                                    "evidence",
                                ],
                                lineterminator="\n",
                            )
                            if is_new:
                                w.writeheader()
                            w.writerow(
                                dict(
                                    tenant_host=tenant_host,
                                    match=match,
                                    gov_id=gov_id,
                                    strength=strength,
                                    source=source,
                                    evidence=evidence,
                                )
                            )
                        existing_override_keys.add(key)
            _safe_coverage_call(
                jc_update_success,
                row["gov_id"],
                meeting_url=row["meeting_url"],
                platform=row.get("platform", ""),
                tier="tier3",
            )
        else:
            rejected += 1

    print(
        f"\nTier-3 finish: {accepted} accepted (queued), {rejected} rejected by probe."
    )
    return accepted, rejected


# --------------------------------------------------------------------------
# Per-government processing
# --------------------------------------------------------------------------


def _write_host_access(host, access_mode, waf_family):
    is_new = not HOST_ACCESS_CSV.exists()
    with HOST_ACCESS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["host", "access_mode", "waf_family"], lineterminator="\n"
        )
        if is_new:
            w.writeheader()
        w.writerow({"host": host, "access_mode": access_mode, "waf_family": waf_family})


async def process_government(session, cand: dict, covered_gov_ids: set, writer) -> str:
    """Returns 'ok' or 'error' (for the consecutive-error breaker)."""
    gov_id = cand["gov_id"]
    name = cand["name"]
    state = cand["state"]
    gov_kind = cand["gov_kind"]
    population = cand["population"]
    domain = cand["domain"]
    prior_reason = cand.get("prior_reject_reason", "")

    base = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        gov_kind=gov_kind,
        population=population,
        prior_reject_reason=prior_reason,
        host="",
        access_mode="",
        rung_answered="",
        vendor_hint="",
        platform_found="",
        netloc="",
        outcome="",
        reject_reason="",
        reject_class="",
        meeting_url="",
        video_url="",
        tier="",
        page_url="",
        waf_family="",
        note="",
    )

    if gov_id in covered_gov_ids:
        writer.writerow({**base, "outcome": "already_covered"})
        return "ok"

    base["host"] = urlparse(wo147.normalize_home_url(domain)).netloc

    ladder = await wo147.run_access_ladder(session, name, state, domain, "")
    base["access_mode"] = ladder.access_mode
    base["rung_answered"] = ladder.rung_answered
    base["waf_family"] = ladder.waf_family
    if ladder.note:
        base["note"] = ladder.note
    _write_host_access(base["host"], ladder.access_mode, ladder.waf_family)

    if ladder.access_mode in (
        "challenge",
        "dead",
        "timeout",
        "blocked-plain-http",
        "blocked-browser-headers",
    ):
        reject_map = {
            "challenge": "cloudflare-challenge-blocked",
            "dead": "dns-unresolvable",
            "timeout": "timeout",
            "blocked-plain-http": "blocked-plain-http",
            "blocked-browser-headers": "blocked-browser-headers",
        }
        reason = reject_map[ladder.access_mode]
        writer.writerow(
            {
                **base,
                "outcome": "blocked",
                "reject_reason": reason,
                "reject_class": "access",
            }
        )
        _safe_coverage_call(jc_update_reject, gov_id, reason)
        return "ok"

    base["vendor_hint"] = vendor_hints_in_body(ladder.final_html)

    hits = []
    if ladder.platform and ladder.hit_url:
        hits.append((ladder.platform, ladder.hit_url))

    if not hits:
        writer.writerow(
            {
                **base,
                "outcome": "no_platform_link_found",
                "reject_reason": "no-platform-link-found",
                "reject_class": "content",
            }
        )
        _safe_coverage_call(jc_update_reject, gov_id, "no-platform-link-found")
        return "ok"

    platform, hit_url = hits[0]
    netloc = urlparse(hit_url).netloc
    base["platform_found"] = platform
    base["netloc"] = netloc
    # A bare vendor-host hit with no path at all (e.g. a "watch on YouTube"
    # badge linking straight to https://www.youtube.com, not a real
    # per-tenant channel/video) is not real evidence this government has a
    # working presence there -- confirmed live, 2026-09-11: Winston County
    # AL, Vermilion Parish LA and Jackson County IN all produced exactly
    # this shape and all three correctly resolved to "0 video(s) listed"
    # downstream, yet a naive unconditional write would have still stamped
    # suspected_meeting_link_provider=youtube on their jurisdiction_
    # coverage.csv rows. Skip the coverage-file write for a bare host;
    # nothing else about detection/resolve changes.
    if urlparse(hit_url).path.strip("/"):
        _safe_coverage_call(jc_update_platform_found, gov_id, platform, hit_url)

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": name,
        "homepage": ladder.home_url or wo147.normalize_home_url(domain),
        "hop2_urls": "",
        "hit_source_urls": f"{platform}={hit_url}",
        "state": state,
        "gov_kind": gov_kind,
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo259_full_ladder_scan"
        )
    except Exception as e:  # noqa: BLE001
        writer.writerow(
            {
                **base,
                "outcome": "error",
                "note": (
                    base["note"] + f"; process_row raised: {type(e).__name__}: {e}"
                ).strip("; "),
            }
        )
        return "error"

    outcome = result.outcome
    reason = result.reason or ""

    if outcome == "already_covered":
        writer.writerow({**base, "outcome": "already_covered"})
        return "ok"

    if outcome == "ingested_tier1_2":
        tier = "tier2" if result.platform == "youtube" else "tier1"
        writer.writerow(
            {
                **base,
                "outcome": "ingested_tier1_2",
                "meeting_url": result.seed_url,
                "tier": tier,
                "page_url": result.page_url,
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        _safe_coverage_call(
            jc_update_success,
            gov_id,
            meeting_url=result.page_url or result.seed_url,
            platform=result.platform,
            tier=tier,
        )
        return "ok"

    if outcome == "queued_tier3_pending":
        writer.writerow(
            {
                **base,
                "outcome": "queued_tier3_pending",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "tier": "tier3_pending",
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "rejected_by_probe":
        writer.writerow(
            {
                **base,
                "outcome": "rejected_by_probe",
                "reject_reason": "rejected_by_probe",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        _safe_coverage_call(jc_update_reject, gov_id, "rejected_by_probe")
        return "ok"

    if outcome == "no_video_found":
        writer.writerow(
            {
                **base,
                "outcome": "no_video_found",
                "reject_reason": "no-video-found",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        _safe_coverage_call(jc_update_reject, gov_id, "no-video-found")
        return "ok"

    if outcome == "error":
        writer.writerow(
            {
                **base,
                "outcome": "error",
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        return "error"

    # outcome == "skipped" -- everything else, including our own hand-read
    # gate markers, comes through here (see wo259_identity_hook()).
    if "AWAITING-HAND-READ" in reason:
        writer.writerow(
            {
                **base,
                "outcome": "awaiting_hand_read",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        return "ok"

    if "AUTO-WRONG-GOV" in reason or "AUTO-HAND-CHECK-A" in reason:
        writer.writerow(
            {
                **base,
                "outcome": "wrong_domain_mapping",
                "reject_reason": "wrong-domain-mapping",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        _safe_coverage_call(jc_update_reject, gov_id, "wrong-domain-mapping")
        return "ok"

    if "AUTO-HAND-CHECK-B" in reason or "HAND-READ-REJECTED" in reason:
        writer.writerow(
            {
                **base,
                "outcome": "off_mission_hand_check",
                "reject_reason": "off-mission",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        _safe_coverage_call(jc_update_reject, gov_id, "off-mission")
        return "ok"

    if result.video_url and not result.seed_url:
        writer.writerow(
            {
                **base,
                "outcome": "skipped",
                "reject_reason": "video-without-meeting",
                "reject_class": "content",
                "video_url": result.video_url,
                "note": (base["note"] + "; " + reason).strip("; "),
            }
        )
        return "ok"

    reject_reason = wo147.classify_skip_reason(reason)
    writer.writerow(
        {
            **base,
            "outcome": "no_platform_link_found"
            if reject_reason == "no-platform-link-found"
            else "no_video_found"
            if reject_reason == "no-video-found"
            else "no_meetings_found"
            if reject_reason == "no-meetings-found"
            else "blocked"
            if reject_reason == "unsupported-platform-no-adapter"
            else "skipped",
            "reject_reason": reject_reason,
            "reject_class": "content",
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
            "note": (base["note"] + "; " + reason).strip("; "),
        }
    )
    _safe_coverage_call(jc_update_reject, gov_id, reject_reason)
    return "ok"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def _report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=_REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _last_outcome_by_gov() -> Dict[str, str]:
    if not REPORT_CSV.exists():
        return {}
    out: Dict[str, str] = {}
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["gov_id"]] = r.get("outcome", "")
    return out


async def main() -> None:
    global _hand_read_decisions, _pending_seen
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    ap.add_argument("--skip-covered-fetch", action="store_true")
    args = ap.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    _hand_read_decisions = load_hand_read_decisions()
    _pending_seen = load_pending_seen()
    print(f"{len(_hand_read_decisions)} hand-read decision(s) loaded")

    if args.skip_covered_fetch:
        covered_gov_ids = set()
    else:
        covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    candidates = [
        r
        for r in all_rows
        if (r.get("step_full_ladder") or "").strip().lower() == "yes"
    ]
    print(f"{len(all_rows)} total rows, {len(candidates)} with step_full_ladder=yes")

    # A gov_id with no report row yet, or whose most recent row is still
    # "awaiting_hand_read" (a decision may have landed since), is reprocessed.
    # Every other recorded outcome is terminal and is skipped on resume.
    last_outcome = _last_outcome_by_gov()
    todo = [
        c
        for c in candidates
        if last_outcome.get(c["gov_id"], "awaiting_hand_read") == "awaiting_hand_read"
    ]
    print(
        f"{len(candidates) - len(todo)} already have a terminal outcome, {len(todo)} to go"
    )

    if args.limit:
        todo = todo[: args.limit]
        print(f"--limit {args.limit}: processing {len(todo)} this run")

    report_f, writer = _report_writer()
    consecutive_errors = 0
    processed = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(todo):
                t0 = time.monotonic()
                status = await process_government(
                    session, cand, covered_gov_ids, writer
                )
                report_f.flush()
                elapsed = time.monotonic() - t0
                print(
                    f"[{i + 1}/{len(todo)}] {cand['name']}, {cand['state']} "
                    f"({cand['gov_kind']}) -- {elapsed:.1f}s -- status={status}"
                )
                processed += 1
                if status == "error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= CONSECUTIVE_ERROR_HALT:
                    print(
                        f"[HALT] {CONSECUTIVE_ERROR_HALT} consecutive errors -- "
                        f"stopping after {processed} this run (resumable)",
                        file=sys.stderr,
                    )
                    break
                if i < len(todo) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    await stage2_finish_tier3()

    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        results = list(csv.DictReader(f))
    by_outcome: Dict[str, int] = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    print("\n=== SUMMARY (cumulative across all runs) ===")
    for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
        print(f"outcome {outcome}: {count}")
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
