"""WO-217 (2026-09-11): Group 1 -- municipalities of 5,000+ with no
Archive page, `reject_reason` `no-video-found`/`meeting-without-video`,
that ALREADY carry an alternate domain WO-184's one-hop pass never
checked (`research/wo217_candidates.csv`, `wo184_onehop_done == "no"`
rows with an alternate).

Same one-hop method as `wo184_onehop_pilot.py` (plain HTTP only, home
page plus up to 3 of its own meeting/agenda hop links, looking for a
platform DIFFERENT from the one already known) -- see
`scripts/coverage_alternates.one_hop_alternate()`. No promotion: the
primary already found a meeting or agenda, which Ryan's rule treats as
"very high quality" on its own, so `domain` is never changed here.

Unlike `wo184_onehop_pilot.py` (read-mostly, leads only), this script
resolves and ingests a different-platform lead's video in the SAME pass
as the one-hop check, per this WO's own brief -- Group 1's population is
small enough (119 rows at this run's start) that a single foreground
pass, per-government, is simpler and just as resumable as a two-stage
split. Same-site-redirect check, resolve/ingest via
`wo134_confirmed_hits_ingest.process_row()`, hand-check via
`scripts/wo217_handcheck.hand_check_hook` (wired onto
`wo134.IDENTITY_CHECK_HOOK`, runs BEFORE ingest/queue), tier-3 probe via
`app.platforms.queue_probe.probe_queue_entry()` (run immediately, not
deferred to a bulk stage2) -- a probe-accepted candidate under 90 minutes
joins `tier3_auto_transcription_queue.txt`; 90 minutes or over is parked
in `tier3_long_meetings_deferred.txt` instead, per this WO's brief
(narrower than `queue_probe`'s own 6-hour flag-long threshold).

Writes ONE row per government to `research/wo217_report.csv`
(resumable: skips gov_ids already present with `group=has_alternate`),
in the brief's own column order.

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo217_inv --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo217_g1.db" \\
        python3 scripts/wo217_group1_sweep.py --inventory-csv /tmp/wo217_inv/meeting_inventory.csv [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import probe_queue_entry  # noqa: E402

from scripts.coverage_alternates import (  # noqa: E402
    FOUND,
    candidate_domains,
    normalize_host,
    one_hop_alternate,
)
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    HONEST_HEADERS,
    fetch_one,
    find_hop_links,
    find_platform_link,
    is_challenge,
)
from scripts.wo217_handcheck import get_last_verdict, hand_check_hook  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

wo134.IDENTITY_CHECK_HOOK = hand_check_hook

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo217_candidates.csv"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
REPORT_CSV = RESEARCH_DIR / "wo217_report.csv"

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
DEFERRED_FILE = REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

HOST_DELAY_SECONDS = 2.0
GOV_DELAY_SECONDS = 1.5
DEFER_OVER_SECONDS = 90 * 60  # WO-217's own 90-minute cutoff, narrower than
# queue_probe's 6-hour flag-long threshold.

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "primary_reason",
    "primary_platform",
    "group",
    "alternate_tried",
    "alternate_source",
    "alternate_verified_by",
    "hop_platform_found",
    "different_platform",
    "outcome",
    "hand_check",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]

_pending_tier3_candidate: Optional[dict] = None


def _tier3_capture_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    """wo134.TIER3_HANDLER -- captures the one tier-3 candidate for THIS
    government into a module-level slot instead of writing a pending
    file, since this script probes and finishes each candidate
    immediately (see module docstring)."""
    global _pending_tier3_candidate
    pin_row = None
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                host,
                match,
                gov_id,
                "fallback",
                "wo217",
                f"{unit_name} -- WO-217 one-hop alternate-domain lead, gov_id={gov_id}",
            )
    _pending_tier3_candidate = {
        "gov_id": gov_id,
        "platform": platform,
        "meeting_url": final_seed,
        "video_url": result.video_url or final_seed,
        "source_url": hit_url,
        "pin_row": pin_row,
    }


wo134.TIER3_HANDLER = _tier3_capture_handler


def load_jc_rows() -> Dict[str, dict]:
    with JC_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"]: r for r in csv.DictReader(f) if r.get("gov_id")}


def load_candidates() -> List[dict]:
    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        r
        for r in rows
        if (r.get("alternate_domains") or "").strip()
        or (r.get("alternate_urls") or "").strip()
        if r.get("wo184_onehop_done") == "no"
    ]


def already_done_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {
            r["gov_id"]
            for r in csv.DictReader(f)
            if r.get("gov_id") and r.get("group") == "has_alternate"
        }


def report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _existing_override_keys() -> set:
    keys = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("tenant_host", ""), r.get("match", "")))
    return keys


def _apply_pin_row(pin_row_tuple, existing_keys: set) -> None:
    if not pin_row_tuple:
        return
    tenant_host, match, gov_id, strength, source, evidence = pin_row_tuple
    key = (tenant_host, match)
    if key in existing_keys:
        return
    is_new = not TENANT_OVERRIDES_CSV.exists()
    with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
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
            writer.writeheader()
        writer.writerow(
            {
                "tenant_host": tenant_host,
                "match": match,
                "gov_id": gov_id,
                "strength": strength,
                "source": source,
                "evidence": evidence,
            }
        )
    existing_keys.add(key)


async def _is_same_site_redirect(
    session: aiohttp.ClientSession, primary_domain: str, alternate_domain: str
) -> bool:
    primary_host = normalize_host(primary_domain)
    if not primary_host:
        return False
    url = (
        alternate_domain if "://" in alternate_domain else f"https://{alternate_domain}"
    )
    r = await fetch_one(session, url, HONEST_HEADERS)
    final_host = normalize_host(getattr(r, "final_url", "") or "")
    return bool(final_host) and final_host == primary_host


def _base_row(cand: dict, jc_row: dict) -> dict:
    return {
        "gov_id": cand["gov_id"],
        "name": cand["name"],
        "state": cand["state"],
        "population": cand["population"],
        "domain": cand["domain"],
        "primary_reason": cand["reject_reason"],
        "primary_platform": (jc_row.get("suspected_video_provider") or "").strip()
        or (jc_row.get("suspected_meeting_link_provider") or "").strip(),
        "group": "has_alternate",
        "alternate_source": "recorded",
    }


async def process_one(
    session: aiohttp.ClientSession,
    cand: dict,
    jc_row: dict,
    covered_gov_ids: set,
    existing_pin_keys: set,
) -> dict:
    global _pending_tier3_candidate
    base = _base_row(cand, jc_row)

    candidates = candidate_domains(jc_row)
    if len(candidates) < 2:
        return {
            **base,
            "alternate_tried": "",
            "alternate_verified_by": "",
            "hop_platform_found": "",
            "different_platform": "",
            "outcome": "no_alternate_found",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": "candidate_domains() found <2 candidates at run time (alternate may have been dropped/normalized)",
        }

    alternate = candidates[1]

    async def fetch_one_fn(url, headers):
        return await fetch_one(session, url, headers)

    hop_result = await one_hop_alternate(
        jc_row,
        alternate,
        fetch_one_fn,
        HONEST_HEADERS,
        is_challenge,
        find_platform_link,
        find_hop_links,
        between_requests_seconds=HOST_DELAY_SECONDS,
    )

    base["alternate_tried"] = hop_result.alternate_domain

    if hop_result.reason != FOUND:
        return {
            **base,
            "alternate_verified_by": "",
            "hop_platform_found": "",
            "different_platform": "",
            "outcome": hop_result.reason,
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": hop_result.detail,
        }

    base["hop_platform_found"] = hop_result.platform or ""
    base["different_platform"] = "yes" if hop_result.differs_from_primary else "no"

    if not hop_result.differs_from_primary:
        return {
            **base,
            "alternate_verified_by": "",
            "outcome": "same_platform",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": f"hit_url={hop_result.hit_url}",
        }

    await asyncio.sleep(HOST_DELAY_SECONDS)
    same_site = await _is_same_site_redirect(session, cand["domain"], alternate)
    if same_site:
        return {
            **base,
            "alternate_verified_by": "",
            "outcome": "same_site_redirect",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": "alternate's resolved final URL host matches the primary's",
        }

    _pending_tier3_candidate = None
    synthetic_row = {
        "gov_id": cand["gov_id"],
        "unit_name": cand["name"],
        "homepage": f"https://{alternate}",
        "hop2_urls": "",
        "hit_source_urls": f"{hop_result.platform}={hop_result.hit_url}"
        if hop_result.platform and hop_result.hit_url
        else "",
        "_wo217_gov_id": cand["gov_id"],
        "_wo217_name": cand["name"],
        "_wo217_state": cand["state"],
        # WO-217's own candidate list is filtered to gov_kind ==
        # "municipality" at the coverage-registry level (see
        # wo217_build_candidates.py), so this is a constant, not derived
        # from gov_id -- gov_kind_from_id() returns the raw id-prefix
        # shape ("us:place", "ca:csd", ...), which _looks_wrong_government
        # /classify_video_hand_check's own _WRONG_KIND_PHRASES lookup
        # does not recognize (it expects "municipality"/"town"/"city"/
        # "village"/"county"/"cousub"), so passing it through unmapped
        # would silently skip the wrong-kind check for every row.
        "_wo217_gov_kind": "municipality",
    }

    await asyncio.sleep(HOST_DELAY_SECONDS)
    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo217"
        )
    except Exception as e:  # noqa: BLE001
        return {
            **base,
            "alternate_verified_by": "",
            "outcome": "error",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": f"process_row raised: {type(e).__name__}: {e}"[:300],
        }

    hand_check_verdict = get_last_verdict() or "n/a"

    if result.outcome == "ingested_tier1_2":
        return {
            **base,
            "alternate_verified_by": "",
            "outcome": "ingested_tier1_2",
            "hand_check": "ok" if hand_check_verdict == "ok" else hand_check_verdict,
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
            "tier": "1_2",
            "page_url": result.page_url,
            "note": result.reason,
        }

    if result.outcome == "queued_tier3_pending" and _pending_tier3_candidate:
        cand3 = _pending_tier3_candidate
        probe = await probe_queue_entry(
            cand3["meeting_url"],
            video_url=cand3.get("video_url") or None,
            source_page_url=cand3.get("source_url") or None,
        )
        from app.platforms.queue_probe import append_probe_row, DEFAULT_SIDECAR_PATH

        append_probe_row(DEFAULT_SIDECAR_PATH, probe)

        if probe.verdict not in ("accept", "flag-long"):
            return {
                **base,
                "alternate_verified_by": "",
                "outcome": "rejected_by_probe",
                "hand_check": hand_check_verdict,
                "meeting_url": cand3["meeting_url"],
                "video_url": cand3["video_url"],
                "tier": "3",
                "page_url": "",
                "note": f"probe: {probe.reason}",
            }

        duration = probe.duration_seconds or 0
        if duration >= DEFER_OVER_SECONDS:
            hms = time.strftime("%H:%M:%S", time.gmtime(duration))
            line = (
                f"{cand3['meeting_url']}\t\t{cand['gov_id']}\t{cand['name']}, "
                f"{cand['state']}\t{hms}\tWO-217 one-hop lead, over 90 min"
            )
            with DEFERRED_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            return {
                **base,
                "alternate_verified_by": "",
                "outcome": "deferred_long_meeting",
                "hand_check": hand_check_verdict,
                "meeting_url": cand3["meeting_url"],
                "video_url": cand3["video_url"],
                "tier": "3",
                "page_url": "",
                "note": f"{duration / 60:.0f} min, over the 90-min WO-217 cutoff -- parked in {DEFERRED_FILE.name}",
            }

        existing_queue_urls = wo134._existing_tier3_queue_urls()
        if cand3["meeting_url"] not in existing_queue_urls:
            queue_line = cand3["meeting_url"]
            if cand3.get("source_url"):
                queue_line = f"{queue_line}\t{cand3['source_url']}"
            with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(queue_line + "\n")
        _apply_pin_row(cand3.get("pin_row"), existing_pin_keys)

        return {
            **base,
            "alternate_verified_by": "",
            "outcome": "queued_tier3",
            "hand_check": hand_check_verdict,
            "meeting_url": cand3["meeting_url"],
            "video_url": cand3["video_url"],
            "tier": "3",
            "page_url": "",
            "note": f"duration {duration / 60:.1f} min",
        }

    outcome_map = {
        "already_covered": "already_covered",
        "no_video_found": "lead_no_video",
        "skipped": "lead_no_video",
    }
    return {
        **base,
        "alternate_verified_by": "",
        "outcome": outcome_map.get(result.outcome, result.outcome),
        "hand_check": hand_check_verdict,
        "meeting_url": result.seed_url,
        "video_url": result.video_url,
        "tier": "",
        "page_url": result.page_url,
        "note": result.reason,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-csv", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set.", file=sys.stderr
        )
        sys.exit(1)

    register_all_finders()

    candidates = load_candidates()
    jc_rows = load_jc_rows()
    print(f"{len(candidates)} Group 1 (has_alternate, new work) candidates.")

    if args.dry_run:
        return

    done = already_done_gov_ids()
    print(f"{len(done)} gov_ids already in {REPORT_CSV.name} (group=has_alternate).")
    to_process = [c for c in candidates if c["gov_id"] not in done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} rows this run.")

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    existing_pin_keys = _existing_override_keys()

    tally: Dict[str, int] = {}
    report_f, writer = report_writer()
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(to_process):
                jc_row = jc_rows.get(cand["gov_id"])
                if jc_row is None:
                    row_out = {
                        **_base_row(cand, {}),
                        "alternate_tried": "",
                        "alternate_verified_by": "",
                        "hop_platform_found": "",
                        "different_platform": "",
                        "outcome": "error",
                        "hand_check": "n/a",
                        "meeting_url": "",
                        "video_url": "",
                        "tier": "",
                        "page_url": "",
                        "note": "gov_id not found in jurisdiction_coverage.csv at run time",
                    }
                else:
                    started = time.monotonic()
                    try:
                        row_out = await process_one(
                            session, cand, jc_row, covered_gov_ids, existing_pin_keys
                        )
                    except Exception as e:  # noqa: BLE001
                        row_out = {
                            **_base_row(cand, jc_row),
                            "alternate_tried": "",
                            "alternate_verified_by": "",
                            "hop_platform_found": "",
                            "different_platform": "",
                            "outcome": "error",
                            "hand_check": "n/a",
                            "meeting_url": "",
                            "video_url": "",
                            "tier": "",
                            "page_url": "",
                            "note": f"{type(e).__name__}: {e}"[:300],
                        }
                    elapsed = time.monotonic() - started
                    print(
                        f"[{i + 1}/{len(to_process)}] {cand['name']}, {cand['state']}: "
                        f"{row_out['outcome']} ({elapsed:.1f}s)"
                    )
                writer.writerow(row_out)
                report_f.flush()
                tally[row_out["outcome"]] = tally.get(row_out["outcome"], 0) + 1
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:28} {v}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
