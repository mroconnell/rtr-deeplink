"""WO-190 (2026-09-11): resolve the research file's own never-tested
meeting/agenda URLs -- the cheaper cousin of WO-151.

WO-151 (see BACKLOG_DONE.md, scripts/wo151_research_url_ladder_sweep.py)
walked 1,026 governments whose research row had ALREADY been rejected
once (a prior `no-platform-link-found`/`resolve-failed`/`untested`
reason) and re-tried them from scratch. This work order is narrower and
cheaper: a row here is never-tested at all (`transcribed` and
`reject_reason` both blank in
~/Documents/rtr-business/research/jurisdiction_coverage.csv) but ALREADY
carries a real `example_meeting_url` or `example_agenda_or_calendar_url`
-- someone already found the meeting page by hand. Resolving it is
usually a single fetch, not a multi-hop hunt.

This is deliberately NOT a fifth ladder implementation. It reuses
`scripts.wo151_research_url_ladder_sweep` (imported, never copied, per
this WO's own instructions) for everything the ladder needs:

  * Importing it monkeypatches `scripts.hub_sweep_wo126.Fetcher` to
    `LadderFetcher` (plain HTTP first, browser headers once after a 403
    or a dropped connection, never after a 404; stops dead at a
    human-verification challenge), `hub_sweep_wo126.act_on_resolved` to
    `act_on_resolved_wo151` (WO-145's wrong-government checks, the
    probe-before-queue gate, Ryan's video-only ingest rule), and
    `hub_sweep_wo126.resolve_lead` to `resolve_lead_wo151` (the YouTube
    caption-block circuit breaker).
  * `w151.Cand151` is reused as this script's own candidate dataclass
    unmodified -- it already carries every field `hub_sweep_wo126`'s
    `_process_gov`/`key_check`/`pin_for` and `wo145_api_first_sweep`'s
    wrong-government checks need (gov_id, name, state, country, gov_kind,
    population, domain, known_platform, prior_reason,
    research_calendar_url, research_meeting_url).
  * `w151.process_candidate()` is reused as-is: it already tries
    `research_calendar_url`, then `research_meeting_url`, then `domain`,
    in order, falling through to the next start URL on a 404/dns/timeout/
    blocked outcome and stopping outright on a confirmed wrong-government
    or off-mission verdict (`CONTENT_STOP_REASONS`) -- exactly this WO's
    own "on a 404, try the domain home page" rule, already built.

What this script changes about the reused plumbing, and why:

  1. **No headless rung** (`w151.HEADLESS_BUDGET = 0` after import) --
     this WO's own instructions say no headless browsing; a budget of
     zero makes `maybe_try_headless` return immediately without ever
     importing Playwright.
  2. **2-second politeness delay** (`hs.REQUEST_DELAY_SECONDS = 2.0`,
     overriding hub_sweep_wo126's default 1.5s), per this WO's own
     instructions -- one request at a time per host, 2 seconds between
     requests.
  3. **This run's own pin attribution** (`hs.PIN_SOURCE`, `hs.PINS_CSV`)
     so a staged pin always says which work order actually found it,
     same pattern WO-151 itself uses over hub_sweep_wo126's defaults.
  4. **A narrower candidate source**: `wo190_candidates.csv`, built from
     `jurisdiction_coverage.csv` directly (never-tested rows with a
     `gov_id` and either URL, minus any gov_id already owned by
     `wo184_report.csv`/`wo189_report.csv` -- the two other sessions
     working this file tonight), not from a prior sweep's own reject
     list. `url_kind` (`meeting`/`agenda`) records which research column
     supplied the primary start URL, since that's this WO's own report
     column, not one `w151.REPORT_FIELDS` carries.
  5. **Stale-URL handling**: when the primary research URL 404s and the
     domain fallback finds a real, different working link, this script's
     own report row (`url_used_stale`, `replacement_url`) says so, so the
     CSV-apply step (`scripts/wo190_apply_to_research.py`) can move the
     stale URL into `alternate_urls` and put the working one in the
     column it came from, per this WO's own instructions -- neither
     `w151.process_candidate()` nor `hub_sweep_wo126` touches the
     research file's URL columns themselves.

Usage (repo root; needs the shared checkout's `.env` for
`ARCHIVE_BASE_URL`/`ARCHIVE_INGEST_TOKEN`, which a worktree inherits by
cwd-walk per CLAUDE.md):

    python scripts/wo190_resolve_research_urls.py --build-candidates
    python scripts/wo190_resolve_research_urls.py --pilot 20
    python scripts/wo190_resolve_research_urls.py             # full run, resumes

Resumable: `rtr-business/research/wo190_report.csv` is flushed one row
at a time; a gov_id already present there is skipped on re-run.

Politeness: one government at a time, 2 seconds between requests
(`hs.REQUEST_DELAY_SECONDS`), never past a human-verification challenge,
halts after `MAX_CONSECUTIVE_ERRORS` consecutive real errors. Ingest is
HTTP-only against the real Archive API; nothing here touches a database
directly.
"""

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from scripts.bulk_ingest import _base_url  # noqa: E402

import scripts.hub_sweep_wo126 as hs  # noqa: E402
import scripts.wo151_research_url_ladder_sweep as w151  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
CANDIDATES_CSV = RESEARCH_DIR / "wo190_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo190_report.csv"
SEEDS_CSV = RESEARCH_DIR / "wo190_discovery_seeds.csv"
EXPORT_JSON = RESEARCH_DIR / "wo190_export_pages.json"
WO184_REPORT = RESEARCH_DIR / "wo184_report.csv"
WO189_REPORT = RESEARCH_DIR / "wo189_report.csv"
CONSOLIDATED_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "consolidated_governments.csv"
)

# This run's own attribution -- distinct from hub_sweep_wo126's and
# w151's own PIN_SOURCE/PINS_CSV, so a pin/report row always says which
# work order actually found it (see module docstring point 3).
hs.PIN_SOURCE = "wo190_resolve_research_urls"
hs.PINS_CSV = RESEARCH_DIR / "wo190_pins.csv"

# No headless rung this WO -- see module docstring point 1. A budget of
# zero makes w151.maybe_try_headless's own `_headless_used >= HEADLESS_
# BUDGET` check true immediately, so headless_discover() never launches
# Playwright.
w151.HEADLESS_BUDGET = 0

# 2-second politeness delay, per this WO's own instructions (overrides
# hub_sweep_wo126's 1.5s default). LadderFetcher.get() and the w151 main
# loop both read this off the hs module at call time, so one assignment
# covers both.
hs.REQUEST_DELAY_SECONDS = 2.0

MAX_CONSECUTIVE_ERRORS = 6


# --------------------------------------------------------------------------
# Candidate list: built at run time from jurisdiction_coverage.csv
# directly, per this WO's own instructions -- never from a prior sweep's
# reject list. Reuses w151.Cand151 unmodified.
# --------------------------------------------------------------------------


def _owned_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _pop_of(row: dict) -> float:
    try:
        return float(row.get("population_estimate") or 0)
    except ValueError:
        return 0.0


def _load_state_abbrev_map() -> dict:
    """jurisdiction_coverage.csv's `state_or_province` column mixes full
    names ("Missouri") and, on a small minority of rows, USPS/province
    abbreviations ("MD") -- a real, confirmed data inconsistency between
    two rows that key the same government under different gov_ids (see
    docs/BREADTH_SWEEP_BRIEF.md's "Data quality to fix alongside", the
    Baltimore/Philadelphia/etc. duplicate-row entry). wo145_api_first_
    sweep.py's `_state_or_kind_conflict()` -- reused verbatim by
    act_on_resolved_wo151 -- compares `cand.state` (expected: an
    abbreviation) against a resolved page's own "City, ST" text, so a
    full-name `state` here would make it flag a false conflict on nearly
    every real US row. Confirmed live in this WO's own pilot run: 4 of
    the first 20 candidates were misclassified `wrong-domain-mapping`
    with `cand.state` left as the raw full name (e.g. "Missouri" never
    matches STATE_NAMES's abbreviation keys, so the row's OWN state never
    equals itself). This maps full name -> abbreviation so every
    candidate's `state` matches what the check actually expects."""
    out = {}
    with (REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "us_states.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            out[r["name"].strip().lower()] = r["state"].strip().upper()
    with (REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "ca_pr.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            out[r["name"].strip().lower()] = r["province"].strip().upper()
    return out


STATE_ABBREV = _load_state_abbrev_map()


def _normalize_state(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if len(raw) <= 3:
        return raw.upper()  # already an abbreviation (MD, DC, NL, ...)
    return STATE_ABBREV.get(raw.lower(), raw)


def _gov_kind_of(gov_id: str) -> str:
    prefix = ":".join(gov_id.split(":")[:2])
    return {
        "us:place": "municipality",
        "ca:csd": "municipality",
        "us:county": "county",
        "ca:cd": "county",
        "us:cousub": "township",
        "us:sd": "school_district",
        "us:state": "state",
        "ca:pr": "province",
    }.get(prefix, "")


CANDIDATES_FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "gov_kind",
    "population",
    "domain",
    "known_platform",
    "prior_reason",
    "research_calendar_url",
    "research_meeting_url",
    "url_kind",
]


def build_candidates() -> int:
    """Never-tested rows (blank `transcribed` AND `reject_reason`) with a
    real `gov_id` and either URL, minus gov_ids owned tonight by WO-184/
    WO-189. Ordered by population descending. Returns the skip count."""
    with JC_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    owned = _owned_gov_ids(WO184_REPORT) | _owned_gov_ids(WO189_REPORT)

    never_tested = [
        r
        for r in rows
        if not (r.get("transcribed") or "").strip()
        and not (r.get("reject_reason") or "").strip()
    ]
    with_url = [
        r
        for r in never_tested
        if (r.get("example_meeting_url") or "").strip()
        or (r.get("example_agenda_or_calendar_url") or "").strip()
    ]
    with_govid = [r for r in with_url if (r.get("gov_id") or "").strip()]

    skipped = [r for r in with_govid if r["gov_id"] in owned]
    candidates = [r for r in with_govid if r["gov_id"] not in owned]
    candidates.sort(key=_pop_of, reverse=True)

    with CANDIDATES_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CANDIDATES_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in candidates:
            meeting_url = (r.get("example_meeting_url") or "").strip()
            agenda_url = (r.get("example_agenda_or_calendar_url") or "").strip()
            if meeting_url:
                url_kind = "meeting"
                research_meeting_url, research_calendar_url = meeting_url, ""
            else:
                url_kind = "agenda"
                research_meeting_url, research_calendar_url = "", agenda_url
            known_platform = (
                (r.get("suspected_meeting_link_provider") or "").strip()
                or (r.get("suspected_video_provider") or "").strip()
                or (r.get("suspected_calendar_provider") or "").strip()
            )
            w.writerow(
                {
                    "gov_id": r["gov_id"],
                    "name": r.get("city_name") or "",
                    "state": _normalize_state(r.get("state_or_province") or ""),
                    "country": r.get("country") or "",
                    "gov_kind": _gov_kind_of(r["gov_id"]),
                    "population": r.get("population_estimate") or "",
                    "domain": r.get("domain") or "",
                    "known_platform": known_platform,
                    "prior_reason": "untested",
                    "research_calendar_url": research_calendar_url,
                    "research_meeting_url": research_meeting_url,
                    "url_kind": url_kind,
                }
            )

    print(
        f"never-tested rows: {len(never_tested)}; with a URL: {len(with_url)}; "
        f"with a gov_id: {len(with_govid)}; skipped (owned by WO-184/WO-189): "
        f"{len(skipped)}; candidates written: {len(candidates)} -> {CANDIDATES_CSV}"
    )
    return len(skipped)


def load_candidates() -> list:
    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append(
            (
                w151.Cand151(
                    gov_id=r["gov_id"],
                    name=r["name"],
                    state=(r.get("state") or "").strip(),
                    country=(r.get("country") or "").strip(),
                    gov_kind=(r.get("gov_kind") or "").strip(),
                    population=(r.get("population") or "").strip(),
                    domain=(r.get("domain") or "").strip(),
                    known_platform=(r.get("known_platform") or "").strip().lower(),
                    prior_reason=(r.get("prior_reason") or "").strip(),
                    research_calendar_url=(
                        r.get("research_calendar_url") or ""
                    ).strip(),
                    research_meeting_url=(r.get("research_meeting_url") or "").strip(),
                ),
                (r.get("url_kind") or "").strip(),
            )
        )
    return out


# --------------------------------------------------------------------------
# Report: the schema this WO's own instructions specify, plus a few extra
# fields the CSV-apply step needs for stale-URL handling.
# --------------------------------------------------------------------------

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "url_used",
    "url_kind",
    "access_mode",
    "platform_found",
    "outcome",
    "reject_reason",
    "hit_url",
    # extras, needed by the rtr-business apply script:
    "start_url_status",
    "corrected_domain",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
    # Stale-URL handling (this WO's own instruction #4): when the
    # primary research URL 404s and the domain fallback lands on a
    # DIFFERENT real host, url_used is stale. Detected here by comparing
    # hosts rather than by tracking which specific attempt 404'd (w151's
    # reused process_candidate() only reports the LAST start URL's
    # status, not a per-attempt history) -- an honest, coarser signal:
    # different host + a real find means the original URL almost
    # certainly didn't lead there directly. Same-host path differences
    # are not flagged stale.
    "url_used_stale",
    "replacement_url",
]


def _report_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(
        f, fieldnames=REPORT_FIELDS, extrasaction="ignore", lineterminator="\n"
    )
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _seeds_writer(path: Path):
    fields = ["gov_id", "tenant", "platform", "access_mode"]
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _already_done_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _load_consolidated_gov_ids() -> set:
    if not CONSOLIDATED_CSV.exists():
        return set()
    with CONSOLIDATED_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


async def process_one(
    session: aiohttp.ClientSession, cand: w151.Cand151, url_kind: str, index, finder
) -> dict:
    url_used = cand.research_meeting_url or cand.research_calendar_url
    row = {k: "" for k in REPORT_FIELDS}
    row.update(
        gov_id=cand.gov_id,
        name=cand.name,
        state=cand.state,
        gov_kind=cand.gov_kind,
        population=cand.population,
        url_used=url_used,
        url_kind=url_kind,
    )
    w151_row = await w151.process_candidate(session, cand, index, finder)
    row["access_mode"] = w151_row.get("access_mode") or ""
    row["platform_found"] = w151_row.get("platform_found") or ""
    row["outcome"] = w151_row.get("outcome") or ""
    row["reject_reason"] = w151_row.get("reject_reason") or ""
    row["hit_url"] = w151_row.get("hit_url") or ""
    row["start_url_status"] = w151_row.get("start_url_status") or ""
    row["corrected_domain"] = w151_row.get("corrected_domain") or ""
    row["meeting_url"] = w151_row.get("meeting_url") or ""
    row["video_url"] = w151_row.get("video_url") or ""
    row["tier"] = w151_row.get("tier") or ""
    row["page_url"] = w151_row.get("page_url") or ""
    row["note"] = w151_row.get("note") or ""

    replacement = row["hit_url"] or row["page_url"] or row["meeting_url"]
    success_outcomes = {"ingested_tier1_2", "queued_tier3", "duplicate_queued"}
    if (
        replacement
        and url_used
        and row["outcome"] in success_outcomes
        and urlparse(replacement).netloc.lower() != urlparse(url_used).netloc.lower()
    ):
        row["url_used_stale"] = "yes"
        row["replacement_url"] = replacement
    return row


async def main_async(args) -> None:
    if args.write_pins:
        # A separate, deliberate step -- same convention hub_sweep_wo126.py
        # itself uses (its own `--write-pins` flag): staged pins
        # (hs.PINS_CSV, overridden above to wo190_pins.csv) are reviewed
        # in place before landing in the real
        # app/utils/jurisdiction_data/tenant_overrides.csv, rather than
        # every sweep invocation silently rewriting it.
        hs.write_pins()
        return

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.build_candidates or not CANDIDATES_CSV.exists():
        build_candidates()
        if args.build_candidates and args.build_only:
            return

    register_all_finders()
    finder = hs.CivicPlusAssetFinder()

    if args.refresh_export or not EXPORT_JSON.exists():
        n = await hs.refresh_export(EXPORT_JSON)
        print(f"export refreshed: {n} pages -> {EXPORT_JSON}")
    index = hs.DedupeIndex(EXPORT_JSON, hs.TIER3_QUEUE_FILE)

    consolidated_ids = _load_consolidated_gov_ids()

    pairs = load_candidates()
    done = _already_done_gov_ids(REPORT_CSV)
    todo = [p for p in pairs if p[0].gov_id not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(
        f"Processing {len(todo)} of {len(pairs)} candidate(s) ({len(done)} already logged)...\n"
    )

    report_f, report_w = _report_writer(REPORT_CSV)
    seeds_f, seeds_w = _seeds_writer(SEEDS_CSV)
    seeded_govs: set = set()

    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, (cand, url_kind) in enumerate(todo):
                if cand.gov_id in index.gov_ids or cand.gov_id in consolidated_ids:
                    row = {k: "" for k in REPORT_FIELDS}
                    row.update(
                        gov_id=cand.gov_id,
                        name=cand.name,
                        state=cand.state,
                        gov_kind=cand.gov_kind,
                        population=cand.population,
                        url_used=cand.research_meeting_url
                        or cand.research_calendar_url,
                        url_kind=url_kind,
                        outcome="already_covered",
                        note="gov_id already has an archived page, or is a consolidated county-form id",
                    )
                    consecutive_errors = 0
                else:
                    try:
                        row = await process_one(session, cand, url_kind, index, finder)
                        is_error = row["outcome"] == "error"
                        consecutive_errors = consecutive_errors + 1 if is_error else 0
                    except Exception as e:  # noqa: BLE001
                        row = {k: "" for k in REPORT_FIELDS}
                        row.update(
                            gov_id=cand.gov_id,
                            name=cand.name,
                            state=cand.state,
                            gov_kind=cand.gov_kind,
                            population=cand.population,
                            url_used=cand.research_meeting_url
                            or cand.research_calendar_url,
                            url_kind=url_kind,
                            outcome="error",
                            note=f"unhandled: {type(e).__name__}: {e}",
                        )
                        consecutive_errors += 1

                report_w.writerow(row)
                report_f.flush()

                if row.get("platform_found") and row["gov_id"] not in seeded_govs:
                    hit = row.get("hit_url") or ""
                    tenant = urlparse(hit).netloc if hit else ""
                    if tenant:
                        seeds_w.writerow(
                            {
                                "gov_id": row["gov_id"],
                                "tenant": tenant,
                                "platform": row["platform_found"],
                                "access_mode": row.get("access_mode") or "",
                            }
                        )
                        seeds_f.flush()
                        seeded_govs.add(row["gov_id"])

                print(
                    f"[{i + 1}/{len(todo)}] [{row['outcome']:20}] {row['gov_id']} {row['name']!r} "
                    f"access={row.get('access_mode')!r} -- {row.get('reject_reason') or row.get('note', '')}"
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- "
                        "stopping per CLAUDE.md's politeness rule. Re-run to resume.",
                        file=sys.stderr,
                    )
                    break
                if i < len(todo) - 1:
                    await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
    finally:
        report_f.close()
        seeds_f.close()

    print(f"\nFull report: {REPORT_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-candidates", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refresh-export", action="store_true")
    parser.add_argument("--write-pins", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
