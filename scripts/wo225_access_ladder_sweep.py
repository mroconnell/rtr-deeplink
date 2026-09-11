"""WO-225 (2026-09-11): re-test the 553 governments carrying
`reject_reason == "no-video-found"` in `jurisdiction_coverage.csv` that
recorded NOTHING at all -- blank `example_meeting_url`, blank
`example_agenda_or_calendar_url`, blank `suspected_meeting_link_provider`,
blank `suspected_calendar_provider` (see `scripts/wo225_build_candidates.py`
for the exact re-derivation: 553 rows, matching Ryan's own count).
`no-video-found` is only a true "meeting/agenda found, no video" label
when the row actually recorded one; for these 553 it was a guess. Ryan's
instruction: re-test each one and write back exactly what the test
finds, using the existing labels only.

Reused BY IMPORT, never copied or edited, same pattern as WO-216/WO-191:
  - `scripts/wo147_access_ladder_sweep.py`'s `run_access_ladder()` and its
    `classify_skip_reason()`, `normalize_known_platform()`,
    `normalize_home_url()`, `channel_scan_caution()`,
    `government_display_name()`.
  - `scripts/wo134_confirmed_hits_ingest.py`'s `process_row()`, which
    already sends `gov_id` in the ingest payload (WO-222, confirmed on
    this branch) -- via `PROBE_SELECT_HOOK` (WO-169/WO-170's real,
    already-built "probe every tier-3 candidate, prefer 9-40 minutes,
    else the shortest" rule) so a tier-3 candidate is ALWAYS probed
    before it is accepted, in one synchronous pass -- no separate
    pending/finish step. `TIER3_HANDLER` stays unset (None): the
    default behaviour (direct append to `tier3_auto_transcription_queue.txt`
    plus the tenant-override pin) already only runs once the probe has
    already accepted a candidate, which is what "tier 3 only after the
    probe accepts" means. This WO's own report outcome vocabulary
    (`queued_tier3` / `rejected_by_probe`, no "pending" state) matches
    this synchronous shape, not WO-216's older two-phase pending/finish
    one -- WO-224's shared finish helper (not merged as this file was
    written -- checked live: `git merge-base --is-ancestor` against
    `origin/main` said NOT MERGED) is therefore not needed here.
  - `scripts/coverage_alternates.py`'s `ladder_with_alternates()` +
    `classify_wo147_ladder_result()`, `trigger="no-meeting"` -- Ryan's
    rule an untested/found-nothing row keeps trying its next candidate
    domain, promoting whichever one answers.
  - `scripts/wo174_pipeline.py`'s `classify_video_hand_check()` as the
    automatic pre-ingest hand-check gate (Kind A/B), wired onto
    `wo134.IDENTITY_CHECK_HOOK` exactly like WO-216. Kind A owner bodies
    go to `research/wo225_owner_bodies.csv` for a later mint pass. This
    is the automatic pre-filter only -- every candidate that clears it
    and actually becomes a page or a queue line still gets a manual
    by-hand read (title + channel) as part of this WO's own review pass.

Domain candidate order, per Ryan's rule from the Carroll County NH spot
check (a hub host that answers is the better domain and gets tried
FIRST): if the candidate's `hub_url` (from `coverage_registry.csv`,
carried on `wo225_candidates.csv`) has a host that differs from the row's
own `domain`, a SYNTHETIC row is built for `ladder_with_alternates()`
whose own `domain` is the hub host and whose `alternate_domains` is the
row's real domain followed by its real alternates -- so
`candidate_domains()`'s own "primary first, then alternate_domains in
file order" logic naturally tries hub host, then domain, then each
alternate, in that order. Promotion is then judged against the REAL
original domain (not the synthetic row's), so a win on the row's own
unchanged `domain` is correctly "not promoted."

Meetings over 90 minutes (5,400s) that the probe still accepted
(`flag-long`, per queue_probe.select_best_probe_result()'s "prefer
9-40 minutes, else shortest plausible" rule -- `flag-long` stays
selectable when nothing shorter exists) are moved from
`tier3_auto_transcription_queue.txt` to `tier3_long_meetings_deferred.txt`
right after `process_row()` appends them -- read back from
`app.platforms.queue_probe.DEFAULT_SIDECAR_PATH`'s own `chosen=1` row
for this candidate's URL, written moments earlier inside
`process_row()`'s own resolve step.

A row with a BLANK `gov_id` (5 of the 553) is still access-ladder tested
and reported, but never ingested/queued -- Ryan's rule ("send the
government's id in every ingest payload") has no id to send for these;
a found video on one of these is logged with a note flagging it for a
mint/pin pass rather than silently ingested unkeyed.

Headless render budget: 300 for this whole run, a running total under
`research/wo225_headless_budget.json` so it holds across a resumed run.

Politeness: one government at a time, 2s between requests to the same
host (rung retries and alternate-domain retries alike), ~1.5s between
governments, an honest User-Agent by default, browser headers only after
a 403/dropped connection, headless only for a real page with no visible
meeting link, stop for good at any human-verification challenge marker.

Usage:
    python scripts/wo225_build_candidates.py
    python scripts/wo225_access_ladder_sweep.py --limit 20   # pilot
    python scripts/wo225_access_ladder_sweep.py              # full run, resumable
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms import queue_probe  # noqa: E402

import scripts.coverage_alternates as ca  # noqa: E402
import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
import scripts.wo147_access_ladder_sweep as wo147  # noqa: E402
from scripts.wo174_pipeline import classify_video_hand_check  # noqa: E402

SOURCE_TAG = "wo225"

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = RESEARCH_DIR / "jurisdiction_coverage.csv"
CANDIDATES_CSV = RESEARCH_DIR / "wo225_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo225_report.csv"
OWNER_BODIES_CSV = RESEARCH_DIR / "wo225_owner_bodies.csv"
HAND_CHECK_GATE_CSV = RESEARCH_DIR / "wo225_hand_check_gate.csv"
HEADLESS_BUDGET_JSON = RESEARCH_DIR / "wo225_headless_budget.json"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo225_inventory/meeting_inventory.csv")

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TIER3_LONG_DEFERRED_FILE = REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt"
LONG_MEETING_SECONDS = 90 * 60  # 90 minutes

GOV_DELAY_SECONDS = 1.5
ALTERNATE_DELAY_SECONDS = 2.0

HEADLESS_BUDGET_TOTAL = 300


# --- headless render budget, persisted across resumed runs --------------


def _load_headless_used() -> int:
    if HEADLESS_BUDGET_JSON.exists():
        try:
            return json.loads(HEADLESS_BUDGET_JSON.read_text()).get("used", 0)
        except Exception:  # noqa: BLE001
            return 0
    return 0


def _save_headless_used(used: int) -> None:
    HEADLESS_BUDGET_JSON.write_text(json.dumps({"used": used}))


_headless_used = _load_headless_used()
_original_fetch_headless = wo147.fetch_headless


async def _budgeted_fetch_headless(
    url: str,
) -> Tuple[Optional[str], str, Optional[str]]:
    global _headless_used
    if _headless_used >= HEADLESS_BUDGET_TOTAL:
        return (
            None,
            url,
            f"wo225 headless budget exhausted ({HEADLESS_BUDGET_TOTAL} used)",
        )
    _headless_used += 1
    _save_headless_used(_headless_used)
    return await _original_fetch_headless(url)


wo147.fetch_headless = _budgeted_fetch_headless


# --- pre-ingest hand-check gate (Kind A / Kind B), same shape as WO-216 --

_OWNER_BODY_FIELDS = [
    "owner_name",
    "channel",
    "video_url",
    "gov_id_if_known",
    "found_for_gov_id",
    "found_for_name",
    "note",
]


def record_owner_body(
    owner_name: str,
    channel: str,
    video_url: str,
    found_for_gov_id: str,
    found_for_name: str,
    note: str,
) -> None:
    is_new = not OWNER_BODIES_CSV.exists()
    with OWNER_BODIES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_OWNER_BODY_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "owner_name": owner_name,
                "channel": channel,
                "video_url": video_url,
                "gov_id_if_known": "",
                "found_for_gov_id": found_for_gov_id,
                "found_for_name": found_for_name,
                "note": note,
            }
        )


_HAND_CHECK_GATE_FIELDS = [
    "gov_id",
    "name",
    "state",
    "kind",
    "reason",
    "title",
    "channel",
    "video_url",
    "meeting_url",
]


def record_hand_check_gate(
    gov_id, name, state, kind, reason, title, channel, video_url, meeting_url
) -> None:
    is_new = not HAND_CHECK_GATE_CSV.exists()
    with HAND_CHECK_GATE_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_HAND_CHECK_GATE_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "gov_id": gov_id,
                "name": name,
                "state": state,
                "kind": kind,
                "reason": reason,
                "title": title or "",
                "channel": channel or "",
                "video_url": video_url or "",
                "meeting_url": meeting_url or "",
            }
        )


def wo225_identity_check_hook(row, platform, result, final_seed, effective_title):
    gov_id = row.get("gov_id", "")
    name = row.get("unit_name", "")
    state = row.get("_state", "")
    gov_kind = row.get("_gov_kind", "")

    channel_text = " ".join(
        filter(
            None,
            [
                (getattr(result, "video_channel", None) or "").lstrip("@"),
                result.jurisdiction or "",
            ],
        )
    )
    hand_check = classify_video_hand_check(
        effective_title, channel_text, name, gov_kind
    )
    if not hand_check:
        return None
    kind, reason = hand_check
    record_hand_check_gate(
        gov_id,
        name,
        state,
        kind,
        reason,
        effective_title,
        channel_text,
        result.video_url,
        final_seed,
    )
    if kind == "A":
        record_owner_body(
            reason,
            channel_text,
            result.video_url or final_seed,
            gov_id,
            name,
            f"WO-225 hand-check gate, kind A: {reason}",
        )
    return f"hand-check-kind-{kind.lower()}: {reason}"


wo134.IDENTITY_CHECK_HOOK = wo225_identity_check_hook

# WO-169/WO-170's already-built, already-tested "probe every tier-3
# candidate, prefer 9-40 minutes, else the shortest" rule -- see module
# docstring for why this replaces WO-216's own pending/finish shape here.
wo134.PROBE_SELECT_HOOK = wo134.build_probe_select_hook()
wo134.TIER3_HANDLER = None


def _move_long_meeting_to_deferred(video_url: str, meeting_url: str) -> bool:
    """After process_row() has already appended a `queued_tier3` line to
    TIER3_QUEUE_FILE, check the probe sidecar's own `chosen=1` row for
    this candidate; if its duration is over 90 minutes, move the just-
    appended line to TIER3_LONG_DEFERRED_FILE instead. Returns True if a
    move happened."""
    if not queue_probe.DEFAULT_SIDECAR_PATH.exists():
        return False
    chosen_duration = None
    with queue_probe.DEFAULT_SIDECAR_PATH.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("chosen") != "1":
                continue
            if r.get("url") not in (video_url, meeting_url):
                continue
            dur = r.get("duration_seconds") or ""
            try:
                chosen_duration = float(dur)
            except ValueError:
                chosen_duration = None
    if chosen_duration is None or chosen_duration <= LONG_MEETING_SECONDS:
        return False

    if not TIER3_QUEUE_FILE.exists():
        return False
    lines = TIER3_QUEUE_FILE.read_text(encoding="utf-8").splitlines()
    keep = []
    moved = []
    for line in lines:
        seed = line.split("\t", 1)[0]
        if seed in (meeting_url, video_url) and not moved:
            moved.append(line)
        else:
            keep.append(line)
    if not moved:
        return False
    TIER3_QUEUE_FILE.write_text(
        "\n".join(keep) + ("\n" if keep else ""), encoding="utf-8"
    )
    with TIER3_LONG_DEFERRED_FILE.open("a", encoding="utf-8") as f:
        f.write(moved[0] + "\n")
    return True


# --- report ---------------------------------------------------------------

_REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "population",
    "domain_before",
    "hub_host_tried",
    "alternates_tried",
    "domain_after",
    "rung_reached",
    "access_mode",
    "platform_found",
    "outcome",
    "reject_reason_after",
    "hand_check",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]


def _report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=_REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _already_done_gov_keys() -> set:
    """Keyed by (gov_id, name, state) since 5 candidates have a blank
    gov_id -- gov_id alone would collide those together on resume."""
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {(r["gov_id"], r["name"], r["state"]) for r in csv.DictReader(f)}


# --- live jurisdiction_coverage.csv lookup by (gov_id,name,state) -------


def _load_jc_rows() -> List[dict]:
    with JC_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _find_jc_row(
    jc_rows: List[dict], gov_id: str, name: str, state: str
) -> Optional[dict]:
    if gov_id:
        for r in jc_rows:
            if (r.get("gov_id") or "").strip() == gov_id:
                return r
        return None
    for r in jc_rows:
        if (r.get("gov_id") or "").strip():
            continue
        if (r.get("city_name") or "").strip() == name and (
            r.get("state_or_province") or ""
        ).strip() == state:
            return r
    return None


# --- main driver ------------------------------------------------------


async def process_candidate(
    session: aiohttp.ClientSession,
    cand: dict,
    jc_rows: List[dict],
    covered_gov_ids: set,
    writer,
) -> str:
    """Returns 'ok' or 'error' (for the consecutive-error breaker)."""
    gov_id = cand["gov_id"]
    country = cand["country"]
    population = cand["population"]

    jc_row = _find_jc_row(jc_rows, gov_id, cand["name"], cand["state"])
    name = (jc_row.get("city_name") if jc_row else "") or cand["name"]
    state = (jc_row.get("state_or_province") if jc_row else "") or cand["state"]
    real_domain = (jc_row.get("domain") if jc_row else "") or cand["domain"]
    real_domain_norm = ca.normalize_host(real_domain)

    base_report = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        country=country,
        population=population,
        domain_before=real_domain,
        hub_host_tried="",
        alternates_tried="",
        domain_after=real_domain,
        rung_reached="",
        access_mode="",
        platform_found="",
        outcome="",
        reject_reason_after="",
        hand_check="",
        meeting_url="",
        video_url="",
        tier="",
        page_url="",
        note="",
    )

    if gov_id and gov_id in covered_gov_ids:
        writer.writerow({**base_report, "outcome": "already_covered"})
        return "ok"

    if jc_row is None:
        writer.writerow(
            {
                **base_report,
                "outcome": "error",
                "note": "row not found in jurisdiction_coverage.csv by gov_id/name+state",
            }
        )
        return "error"

    # --- build the ladder row: hub host first (if it differs), then the
    # real domain, then the real alternates -- see module docstring.
    hub_url = (cand.get("hub_url") or "").strip()
    hub_host = ca.normalize_host(hub_url) if hub_url else ""
    ladder_row = dict(jc_row)
    if hub_host and hub_host != real_domain_norm:
        base_report["hub_host_tried"] = hub_host
        existing_alts = (jc_row.get("alternate_domains") or "").strip()
        ladder_row["domain"] = hub_host
        ladder_row["alternate_domains"] = ";".join(
            filter(None, [real_domain, existing_alts])
        )

    raw_results: Dict[str, wo147.LadderResult] = {}

    async def ladder_fn(candidate_domain: str, row: dict) -> ca.LadderOutcome:
        result = await wo147.run_access_ladder(
            session, name, state, candidate_domain, candidate_domain
        )
        raw_results[candidate_domain] = result
        return ca.classify_wo147_ladder_result(result)

    alt_result = await ca.ladder_with_alternates(
        ladder_row,
        ladder_fn,
        trigger="no-meeting",
        between_candidates_seconds=ALTERNATE_DELAY_SECONDS,
    )
    base_report["alternates_tried"] = alt_result.alternates_tried

    # Promotion judged against the REAL original domain, not the
    # synthetic ladder row's primary (which may be the hub host).
    promoted = (
        alt_result.outcome.reason == ca.FOUND
        and alt_result.answered_domain
        and alt_result.answered_domain != real_domain_norm
    )
    if promoted:
        base_report["domain_after"] = alt_result.answered_domain

    winning_raw = raw_results.get(alt_result.answered_domain)
    home_url = (
        winning_raw.home_url
        if winning_raw and winning_raw.home_url
        else wo147.normalize_home_url(alt_result.answered_domain or real_domain)
    )
    access_mode = winning_raw.access_mode if winning_raw else ""
    base_report["access_mode"] = access_mode
    base_report["rung_reached"] = access_mode

    reason = alt_result.outcome.reason

    if reason != ca.FOUND:
        if reason in ca.ACCESS_REASONS:
            writer.writerow(
                {
                    **base_report,
                    "outcome": "blocked",
                    "reject_reason_after": reason,
                    "note": alt_result.outcome.detail,
                }
            )
            return "ok"
        # content: nothing found at all on any candidate domain.
        writer.writerow(
            {
                **base_report,
                "outcome": "no_meeting_nor_video",
                "reject_reason_after": "no-meeting-nor-video",
                "note": alt_result.outcome.detail,
            }
        )
        return "ok"

    # FOUND -- a platform link exists somewhere. Gather hits.
    hits: List[Tuple[str, str]] = []
    if alt_result.outcome.platform and alt_result.outcome.hit_url:
        hits.append((alt_result.outcome.platform, alt_result.outcome.hit_url))

    known_platform_raw = (
        jc_row.get("suspected_meeting_link_provider")
        or jc_row.get("suspected_calendar_provider")
        or jc_row.get("suspected_video_provider")
        or ""
    )
    known_platform = wo147.normalize_known_platform(known_platform_raw)
    if known_platform and known_platform not in wo134.UNSUPPORTED_PLATFORMS:
        seed = home_url or wo147.normalize_home_url(alt_result.answered_domain)
        if not any(p == known_platform for p, _ in hits):
            hits.append((known_platform, seed))

    platform_found = alt_result.outcome.platform or known_platform or ""
    base_report["platform_found"] = platform_found

    if not hits:
        writer.writerow(
            {
                **base_report,
                "outcome": "no_meeting_nor_video",
                "reject_reason_after": "no-platform-link-found",
            }
        )
        return "ok"

    if not gov_id:
        # 5 candidates have no gov_id at all -- Ryan's rule requires
        # gov_id in every ingest payload, so a found platform link here
        # is reported, never ingested/queued.
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason_after": "no-gov-id",
                "note": (
                    f"platform link found ({platform_found}) but this row has no "
                    "gov_id -- needs identity resolution/minting before it can be "
                    "ingested; not ingested by this sweep"
                ),
            }
        )
        return "ok"

    hit_source_urls = ";".join(f"{p}={u}" for p, u in hits[:6])

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": name,
        "homepage": home_url,
        "hop2_urls": "",
        "hit_source_urls": hit_source_urls,
        "_state": state,
        "_gov_kind": cand.get("gov_kind", ""),
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, SOURCE_TAG
        )
    except Exception as e:  # noqa: BLE001
        writer.writerow(
            {
                **base_report,
                "outcome": "error",
                "note": f"process_row raised: {type(e).__name__}: {e}",
            }
        )
        return "error"

    outcome = result.outcome
    # wo134.process_row() wraps IDENTITY_CHECK_HOOK's own return string
    # (which starts "hand-check-kind-a/b: ...") as
    # f"{platform}: wrong-domain-mapping: {mismatch}" when it rejects a
    # hit and every other hit on the row is also exhausted -- so this is
    # a substring check, not a prefix check, and "wrong-domain-mapping"
    # in the reason is the signal a hand-check gate actually fired (not
    # a literal wrong-DOMAIN finding in this WO's own sense -- that
    # taxonomy value means something narrower elsewhere in this repo,
    # see coverage_alternates.py's own comment on it).
    hand_check_note = ""
    if result.reason and "hand-check-kind-" in result.reason:
        hand_check_note = result.reason
    base_report["hand_check"] = hand_check_note

    if outcome == "already_covered":
        writer.writerow({**base_report, "outcome": "already_covered"})
        return "ok"

    if outcome == "ingested_tier1_2":
        tier = "tier2" if result.platform == "youtube" else "tier1"
        writer.writerow(
            {
                **base_report,
                "outcome": "ingested_tier1_2",
                "meeting_url": result.seed_url,
                "tier": tier,
                "page_url": result.page_url,
                "note": result.reason,
            }
        )
        return "ok"

    if outcome == "queued_tier3":
        moved = _move_long_meeting_to_deferred(
            result.video_url or "", result.seed_url or ""
        )
        writer.writerow(
            {
                **base_report,
                "outcome": "queued_tier3" if not moved else "deferred_long_meeting",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "tier": "tier3" if not moved else "tier3_deferred",
                "note": result.reason
                + (
                    " -- moved to tier3_long_meetings_deferred.txt (>90min)"
                    if moved
                    else ""
                ),
            }
        )
        return "ok"

    if outcome == "rejected_by_probe":
        writer.writerow(
            {
                **base_report,
                "outcome": "rejected_by_probe",
                "reject_reason_after": "rejected-by-probe",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "note": result.reason,
            }
        )
        return "ok"

    if outcome == "no_video_found":
        writer.writerow(
            {
                **base_report,
                "outcome": "meeting_without_video",
                "reject_reason_after": "meeting-without-video",
                "meeting_url": result.seed_url,
                "note": result.reason,
            }
        )
        return "ok"

    if outcome == "error":
        writer.writerow({**base_report, "outcome": "error", "note": result.reason})
        return "error"

    # outcome == "skipped"
    if result.video_url and not result.seed_url:
        writer.writerow(
            {
                **base_report,
                "outcome": "video_without_meeting",
                "reject_reason_after": "video-without-meeting",
                "video_url": result.video_url,
                "note": result.reason,
            }
        )
        return "ok"

    if hand_check_note:
        # Every hit on this row was rejected by the hand-check gate
        # (Kind A: belongs to a different real body; Kind B: right
        # channel, wrong video) -- the government's own video was not
        # found. Per the brief: "mark the government's own row no-video;
        # look again for its own video" (a later pass, not this one).
        writer.writerow(
            {
                **base_report,
                "outcome": "no_meeting_nor_video",
                "reject_reason_after": "no-meeting-nor-video",
                "note": result.reason,
            }
        )
        return "ok"

    reject_reason = wo147.classify_skip_reason(result.reason)
    reject_reason = {
        "no-video-found": "meeting-without-video",
        "no-meetings-found": "no-meeting-nor-video",
    }.get(reject_reason, reject_reason)
    # NOTE: "blocked" in this report's outcome vocabulary means an
    # ACCESS-class reject (couldn't even reach the host); a
    # "no-adapter"/"off-mission" finding means we DID reach real content
    # and judged it -- that is a content-class answer, bucketed under
    # no_meeting_nor_video (closest of the five content outcomes: no
    # usable meeting/video content was actually found), with the
    # specific reason kept verbatim in reject_reason_after.
    outcome_label = {
        "no-platform-link-found": "no_meeting_nor_video",
        "meeting-without-video": "meeting_without_video",
        "no-meeting-nor-video": "no_meeting_nor_video",
        "unsupported-platform-no-adapter": "no_meeting_nor_video",
        "off-mission": "no_meeting_nor_video",
        "video-without-meeting": "video_without_meeting",
    }.get(reject_reason, "no_meeting_nor_video")
    writer.writerow(
        {
            **base_report,
            "outcome": outcome_label,
            "reject_reason_after": reject_reason,
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
            "note": result.reason,
        }
    )
    return "ok"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-after", type=str, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    jc_rows = _load_jc_rows()
    print(f"{len(jc_rows)} rows in {JC_PATH.name} (live lookup).")

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"{len(all_rows)} candidate rows in {CANDIDATES_CSV.name}")

    already_done = _already_done_gov_keys()
    print(f"{len(already_done)} rows already in {REPORT_CSV.name} -- skipping those.")

    skip_until_seen = args.start_after is not None
    to_process = []
    for row in all_rows:
        key = (row["gov_id"], row["name"], row["state"])
        if key in already_done:
            continue
        if skip_until_seen:
            if row["gov_id"] == args.start_after:
                skip_until_seen = False
            continue
        to_process.append(row)
    if args.limit:
        to_process = to_process[: args.limit]

    print(
        f"Processing {len(to_process)} row(s)... (headless used so far: {_headless_used}/{HEADLESS_BUDGET_TOTAL})\n"
    )

    report_f, writer = _report_writer()
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                t0 = time.monotonic()
                status = await process_candidate(
                    session, row, jc_rows, covered_gov_ids, writer
                )
                report_f.flush()
                elapsed = time.monotonic() - t0
                print(
                    f"[{i + 1}/{len(to_process)}] {row['name']}, {row['state']} "
                    f"(pop={row['population']}) -- {elapsed:.1f}s -- status={status}"
                )
                tally[status] = tally.get(status, 0) + 1
                if status == "error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= 6:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors. Re-run to resume.",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:10} {v}")
    print(
        f"\nHeadless renders used (cumulative, this whole WO): {_headless_used}/{HEADLESS_BUDGET_TOTAL}"
    )
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
