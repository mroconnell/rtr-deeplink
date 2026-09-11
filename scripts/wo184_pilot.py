"""WO-184 (2026-09-10/11): the retry-set sweep -- Ryan's wider "no-meeting"
trigger from `scripts/coverage_alternates.py`, run against every row that
has an alternate AND produced no meeting/agenda at all on its primary
domain.

Ryan's rule, verbatim (2026-09-10, supersedes WO-181's narrower framing):

    "A domain keeps priority when it has produced a resolved meeting:
    with video is best, but a meeting or agenda without video is still
    very high quality. If a domain has produced no meeting at all, we
    may simply be looking at the wrong domain, and we lose nothing by
    trying another. Every government posts agendas at least, so the
    line is: found a meeting or agenda, or not."

Candidate list: every row in
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` with a
non-blank `alternate_domains`/`alternate_urls` AND a `reject_reason`
that is retry-worthy under `trigger="no-meeting"` -- computed fresh at
run time, not a fixed list, since the file is live.

A stricter allow-list than `is_retry_worthy()`'s own deny-list is used
for ROW SELECTION here (`STRICT_RETRY_REASONS` below): ACCESS_REASONS,
NO_MEETING_CONTENT_REASONS, or blank. A handful of other reason strings
found live in the file on 2026-09-10/11 -- `video-no-captions-queued`,
`duplicate-queued`, `video-queued-pending-probe`, `resolve-failed`,
`wrong-domain-mapping`, `broken-template-false-positive`,
`rejected_by_probe`, `signature-found-not-verified`,
`no-active-meeting-content` -- are NOT in Ryan's explicit do-not-retry
list, but several of them plainly mean "already spoken for" (a queued
tier-3 candidate, a probe rejection) or "a data-quality call already
made" (a false positive already caught), not "no meeting was found."
Retrying those would burn sweep time on rows that are not this WO's
target population and are excluded here rather than guessed into either
bucket -- see BACKLOG.md's WO-184 residual entry.

A second, more important filter, found live running this script's own
first test batch: `already_has_coverage(row)` (coverage_alternates.py)
excludes any row where `transcribed`/`shares_video` is already "True" --
the research file does NOT spell "already covered" as a `reject_reason`
string; a government with a real, live page sits with a BLANK
`reject_reason`, indistinguishable from "never tested" by
`reject_reason` alone. Cook County, IL (`cook-county.granicus.com`,
already transcribed) was caught this way in the very first test run,
before this filter existed -- 1,252 of the naive 4,686-row candidate
count turned out to already have real coverage. See
`coverage_alternates.already_has_coverage()`'s own docstring.

Rungs 2 and 3 ONLY, same restriction as WO-181: plain honest HTTP, then
browser headers once after a 403 or a dropped connection, never after a
404, NO headless. Politeness: one request in flight at a time, 2 seconds
between every request (within a government's own candidate list, and
between governments). Honest User-Agent. Stops at any human-verification
challenge and records it, never retries past it.

Order: counties first (they have been the best video source), then
municipalities by population descending, then townships -- each tier
sorted by population descending internally too, since a bigger
government within a tier is still a better bet. Within each tier, hosts
are interleaved by "vendor bucket" (the shared platform suffix a
candidate domain belongs to, e.g. civicclerk.com, or the government's
own gov_id when no known vendor suffix matches) so consecutive requests
rarely land on the same shared vendor host's infrastructure back to
back -- see `_vendor_bucket()`/`_interleave_by_vendor_bucket()` below.

This script is READ-MOSTLY: it never writes jurisdiction_coverage.csv
itself. It only appends to wo184_report.csv (resumable -- a re-run
skips gov_ids already present). Applying the report's outcomes back onto
the research file (promotion included) is `wo184_apply_to_jc.py`, a
separate, deliberate step -- same split WO-181 established, so a run can
be killed and re-run freely with zero risk to the shared research file.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo184_pilot.db" \\
        python3 scripts/wo184_pilot.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Set

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.coverage_alternates import (  # noqa: E402
    ACCESS_REASONS,
    FOUND,
    NO_MEETING_CONTENT_REASONS,
    already_has_coverage,
    decide_promotion,
    ladder_with_alternates,
    normalize_host,
    rungs_2_3_ladder_fn,
)

# Pure primitives reused unchanged from wo147 -- see
# coverage_alternates.rungs_2_3_ladder_fn's docstring for why importing
# them (rather than copying) is safe for a caller like this one that
# never calls wo134_confirmed_hits_ingest.process_row() itself.
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    BROWSER_HEADERS,
    HONEST_HEADERS,
    fetch_one,
    find_platform_link,
    is_challenge,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RESEARCH_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
REPORT_CSV = RESEARCH_DIR / "wo184_report.csv"

GOV_DELAY_SECONDS = 2.0
HOST_DELAY_SECONDS = 2.0

TRIGGER = "no-meeting"

STRICT_RETRY_REASONS = ACCESS_REASONS | NO_MEETING_CONTENT_REASONS | {""}

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "alternate_source",
    "prior_reason",
    "primary_domain",
    "alternates_tried",
    "answered_domain",
    "rung_answered",
    "access_mode",
    "platform_found",
    "platform_differs_from_primary",
    "hit_url",
    "promoted",
    "outcome",
    "reject_reason",
]

# Shared-vendor SaaS suffixes worth spreading requests across -- see the
# module docstring's "Order" section. Not exhaustive, just the platforms
# this repo's own adapters (app/platforms/) already know about.
_VENDOR_SUFFIXES = (
    "civicclerk.com",
    "granicus.com",
    "escribemeetings.com",
    "legistar.com",
    "swagit.com",
    "cablecast.tv",
    "telvue.com",
    "primegov.com",
    "youtube.com",
    "vimeo.com",
    "wistia.com",
    "civicweb.net",
    "iqm2.com",
    "clerkshq.com",
    "champds.com",
    "portal.civicclerk.com",
)


def gov_kind_from_id(gov_id: str) -> str:
    """Mechanical parse of the gov_id's own prefix (e.g. 'us:place:0627000'
    -> 'us:place') -- not a guess, just the leading colon-separated
    segments with the trailing numeric/slug id dropped."""
    gov_id = (gov_id or "").strip()
    if not gov_id:
        return ""
    parts = gov_id.split(":")
    if len(parts) <= 1:
        return gov_id
    return ":".join(parts[:-1])


def _population(row: Dict[str, str]) -> float:
    try:
        return float((row.get("population_estimate") or "0").replace(",", ""))
    except ValueError:
        return 0.0


def _row_candidates(row: Dict[str, str]) -> List[str]:
    out = []
    seen = set()
    for key in ("domain",):
        h = normalize_host(row.get(key))
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    for d in (row.get("alternate_domains") or "").split(";"):
        h = normalize_host(d)
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    for u in (row.get("alternate_urls") or "").split(";"):
        h = normalize_host(u)
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _vendor_bucket(row: Dict[str, str]) -> str:
    for cand in _row_candidates(row):
        for suf in _VENDOR_SUFFIXES:
            if cand == suf or cand.endswith("." + suf):
                return suf
    return f"gov:{row.get('gov_id', '')}"


def _interleave_by_vendor_bucket(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Stable round-robin across vendor buckets, preserving each bucket's
    own relative (population-descending) order -- most buckets hold
    exactly one row (an ordinary government with no shared-vendor
    alternate), so this is a no-op for them; it only reorders the rows
    that DO share a vendor suffix, spreading them out."""
    buckets: Dict[str, deque] = {}
    order: List[str] = []
    for r in rows:
        b = _vendor_bucket(r)
        if b not in buckets:
            buckets[b] = deque()
            order.append(b)
        buckets[b].append(r)
    out: List[Dict[str, str]] = []
    while order:
        next_order = []
        for b in order:
            out.append(buckets[b].popleft())
            if buckets[b]:
                next_order.append(b)
            else:
                del buckets[b]
        order = next_order
    return out


def order_candidates(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Counties first, then municipalities by population descending, then
    townships -- each tier sorted by population descending internally,
    then interleaved by vendor bucket within the tier (see module
    docstring's "Order" section)."""
    counties, munis, townships, other = [], [], [], []
    for r in rows:
        kind = gov_kind_from_id(r.get("gov_id", ""))
        if kind == "us:county":
            counties.append(r)
        elif kind == "us:cousub":
            townships.append(r)
        elif kind in ("us:place", "ca:csd"):
            munis.append(r)
        else:
            other.append(r)

    ordered_tiers = []
    for tier in (counties, munis, townships, other):
        tier.sort(key=_population, reverse=True)
        ordered_tiers.append(_interleave_by_vendor_bucket(tier))
    return ordered_tiers[0] + ordered_tiers[1] + ordered_tiers[2] + ordered_tiers[3]


# --- alternate_source best-effort crosswalk -----------------------------
#
# jurisdiction_coverage.csv itself carries NO per-row column recording
# which enumeration pass added a given alternate_domains/alternate_urls
# entry -- confirmed by reading its header (2026-09-11). This crosswalk
# is a best-effort join against the two enumeration passes that DID leave
# a gov_id-level ledger of what they added (WO-180's Wikidata pass,
# WO-177's CivicMirror cousub pass); anything not found in either ledger
# is reported as "other" rather than guessed at UScityURL/WO-165 -- see
# BACKLOG.md's WO-184 residual entry for the reasoning.
_WIKIDATA_ALT_CSV = RESEARCH_DIR / "wo180_wikidata_alt_domain_added_rows.csv"
_CIVICMIRROR_ALT_CSV = RESEARCH_DIR / "wo177_cousub_alternates_verified.csv"

_alt_source_cache: Dict[str, str] = {}


def _load_alt_source_crosswalk() -> Dict[str, str]:
    global _alt_source_cache
    if _alt_source_cache:
        return _alt_source_cache
    mapping: Dict[str, str] = {}
    if _WIKIDATA_ALT_CSV.exists():
        with _WIKIDATA_ALT_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                gid = (r.get("gov_id") or "").strip()
                if gid:
                    mapping[gid] = "Wikidata WO-180"
    if _CIVICMIRROR_ALT_CSV.exists():
        with _CIVICMIRROR_ALT_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                gid = (r.get("gov_id") or "").strip()
                # only rows where CivicMirror's own domain differs from
                # ours are a real alternate addition, not a same-domain
                # confirmation.
                if gid and (r.get("same_as_ours") or "0").strip() != "1":
                    mapping[gid] = "CivicMirror WO-177"
    _alt_source_cache = mapping
    return mapping


def alternate_source(row: Dict[str, str]) -> str:
    mapping = _load_alt_source_crosswalk()
    return mapping.get((row.get("gov_id") or "").strip(), "other")


def load_candidates() -> List[Dict[str, str]]:
    with RESEARCH_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = [
        r
        for r in rows
        if (
            (r.get("alternate_domains") or "").strip()
            or (r.get("alternate_urls") or "").strip()
        )
        and (r.get("reject_reason") or "").strip() in STRICT_RETRY_REASONS
        and not already_has_coverage(r)
    ]
    return order_candidates(out)


def already_done_gov_ids() -> Set[str]:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


async def process_row(
    session: aiohttp.ClientSession, row: Dict[str, str]
) -> Dict[str, str]:
    ladder_fn = rungs_2_3_ladder_fn(
        session,
        HONEST_HEADERS,
        BROWSER_HEADERS,
        fetch_one,
        is_challenge,
        find_platform_link,
        host_delay_seconds=HOST_DELAY_SECONDS,
    )
    result = await ladder_with_alternates(
        row,
        ladder_fn,
        trigger=TRIGGER,
        between_candidates_seconds=HOST_DELAY_SECONDS,
    )
    outcome = result.outcome
    promoted = decide_promotion(result)

    if outcome.reason == FOUND:
        classification = "found"
        new_reject_reason = ""
    elif outcome.reason in ACCESS_REASONS:
        classification = "still-access-blocked"
        new_reject_reason = outcome.reason
    else:
        classification = "content-reject-on-alternate"
        new_reject_reason = outcome.reason

    access_mode = (
        "challenge"
        if outcome.reason == "cloudflare-challenge-blocked"
        else outcome.rung
    )

    return {
        "gov_id": row.get("gov_id", ""),
        "name": row.get("city_name", ""),
        "state": row.get("state_or_province", ""),
        "gov_kind": gov_kind_from_id(row.get("gov_id", "")),
        "population": row.get("population_estimate", ""),
        "alternate_source": alternate_source(row),
        "prior_reason": row.get("reject_reason", ""),
        "primary_domain": row.get("domain", ""),
        "alternates_tried": result.alternates_tried,
        "answered_domain": result.answered_domain,
        "rung_answered": outcome.rung,
        "access_mode": access_mode,
        "platform_found": outcome.platform or "",
        "platform_differs_from_primary": "",  # not applicable to this
        # mode -- the primary found nothing, so there is no known
        # platform to differ from (see one_hop_alternate for that).
        "hit_url": outcome.hit_url or "",
        "promoted": "yes" if promoted else "no",
        "outcome": classification,
        "reject_reason": new_reject_reason,
    }


def _error_row(row: Dict[str, str], exc: Exception) -> Dict[str, str]:
    return {
        "gov_id": row.get("gov_id", ""),
        "name": row.get("city_name", ""),
        "state": row.get("state_or_province", ""),
        "gov_kind": gov_kind_from_id(row.get("gov_id", "")),
        "population": row.get("population_estimate", ""),
        "alternate_source": alternate_source(row),
        "prior_reason": row.get("reject_reason", ""),
        "primary_domain": row.get("domain", ""),
        "alternates_tried": "",
        "answered_domain": "",
        "rung_answered": "",
        "access_mode": "",
        "platform_found": "",
        "platform_differs_from_primary": "",
        "hit_url": "",
        "promoted": "no",
        "outcome": "error",
        "reject_reason": f"pilot-error: {exc}"[:200],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="print candidate count and exit"
    )
    args = parser.parse_args()

    candidates = load_candidates()
    print(
        f"{len(candidates)} candidate rows (alternate present, no-meeting-trigger retry-worthy)."
    )

    if args.dry_run:
        return

    done = already_done_gov_ids()
    print(f"{len(done)} gov_ids already in {REPORT_CSV.name} -- skipping those.")

    to_process = [r for r in candidates if r.get("gov_id", "") not in done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} rows this run.")

    tally: Dict[str, int] = {}
    report_f, writer = report_writer()
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                started = time.monotonic()
                try:
                    result_row = await process_row(session, row)
                except Exception as e:  # noqa: BLE001 -- log and keep going
                    result_row = _error_row(row, e)
                writer.writerow(result_row)
                report_f.flush()
                tally[result_row["outcome"]] = tally.get(result_row["outcome"], 0) + 1
                elapsed = time.monotonic() - started
                print(
                    f"[{i + 1}/{len(to_process)}] {result_row['name']}, {result_row['state']}: "
                    f"{result_row['outcome']} (promoted={result_row['promoted']}) ({elapsed:.1f}s)"
                )
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
