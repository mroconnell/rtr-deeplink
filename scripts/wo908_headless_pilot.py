"""WO-908 (2026-09-19): headless-ladder pilot on 200 SMALL governments
(county/municipality/township -- no school districts) rejected
`no-platform-link-found`/`no-platform-signature`, to get a real hit rate

Renumbered from WO-906 to WO-908 after landing: a separate, unrelated
conductor session independently computed the same "next free WO number"
snapshot around the same time and used 904/905/906 (then 907 for its own
wrap-up) for a three-part meeting_body extraction effort -- see
`BACKLOG_DONE.md`'s "WO-904/905/906" and "WO-907" entries. This session's
own WO-904 and WO-905 had already merged to `main` before the collision
was caught, so those two numbers now legitimately collide in history
(both real, both documented, distinguishable by title). This WO -- not
yet merged when the collision was found -- was renumbered to the true
next-free number (908) instead of compounding a three-way collision. The
git branch name (`wo906-headless-pilot-small-govs`) was left as-is; only
the WO label and this script's/its test's own filenames changed.
for a question `docs/COVERAGE_HANDOVER.md` section 5's breakthrough #1
leaves open: a headless recheck found a real platform link on 41% of the
LARGEST governments previously rejected "no platform link found," and
"~1,180 smaller governments have not had it yet." This pilot is that
measurement on a real, random small-government sample -- it does not
assume 41% carries over.

Reuses `scripts/wo147_access_ladder_sweep.py`'s `run_access_ladder()`
UNCHANGED -- same plain -> browser-headers -> headless -> challenge/dead
ladder, same politeness constants (`HOST_DELAY_SECONDS`/`GOV_DELAY_SECONDS`,
`HONEST_HEADERS`/`BROWSER_HEADERS`, `CHALLENGE_MARKERS`/`is_challenge()`).
This script only adds a thin CSV-in, CSV-out, aggregate-and-report driver
around it -- `classify_bucket()`/`tally_buckets()`/`summarize_by_gov_kind()`
below are the only new logic, and are the only things
`tests/test_wo908_headless_pilot.py` exercises (see that file's own
docstring for why the live network call itself isn't unit-tested).

This is a MEASUREMENT, not a sweep: it never calls a resolve/ingest
function, never writes `tenant_overrides.csv` or any research file, and
never touches the Archive. It only records, per government, which rung of
the ladder answered and whether that rung found a real platform link.

Environment note: this pilot was run from a sandbox with no local
`rtr-business` checkout (see this repo's `CLAUDE.md`, "Business context
lives outside this repo"), so the NACo county-website recovery list
`run_access_ladder()` optionally consults (only when EVERY DNS candidate
for a row fails) isn't reachable at its usual path here. `ladder._naco_rows
= []` below pre-seeds that lazy cache to an empty list -- the exact steady
state `naco_website()` reaches on its own once it has read a real CSV with
no matching row for a given county -- so a DNS-dead row is reported here
exactly as it would be with the file present and simply having no match
for that row. This changes no logic inside `run_access_ladder()` itself,
and it is the only accommodation this script makes for that function.

Usage (from the repo root, with a venv that has requirements.txt
installed):
    python scripts/wo908_headless_pilot.py --candidates-csv <path> --out-csv /tmp/wo908_report.csv
    python scripts/wo908_headless_pilot.py --candidates-csv <path> --out-csv /tmp/wo908_report.csv --limit 5   # smoke test
    python scripts/wo908_headless_pilot.py --report-only /tmp/wo908_report.csv   # re-print the summary only
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
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

import scripts.wo147_access_ladder_sweep as ladder  # noqa: E402

# See module docstring's "Environment note" above -- no behavior change to
# run_access_ladder() itself, just supplying (as empty) an external data
# file this sandbox doesn't have.
ladder._naco_rows = []

# Same threshold as wo134_confirmed_hits_ingest.py / wo147_access_ladder_
# sweep.py's own circuit breaker (both MAX_CONSECUTIVE_ERRORS = 6) --
# reused rather than invented, per this repo's existing convention. Unlike
# those scripts, a "real error" here is specifically a Python exception
# escaping run_access_ladder() itself -- a dead/challenge/no-hit
# LadderResult is a normal, expected outcome for a real government site
# and does not count (mirrors WO-134's own "a content-based skip is
# normal signal and does not count" rule).
MAX_CONSECUTIVE_ERRORS = 6

CANDIDATE_FIELDS = (
    "gov_id",
    "name",
    "state",
    "country",
    "gov_kind",
    "population",
    "domain",
    "reject_reason",
)
RUNG_BUCKETS = ("plain", "browser-headers", "headless", "challenge", "dead")
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")

# `direct_file` (app/platforms/direct_file.py) is matched purely by URL
# extension -- `is_direct_file_url()` returns True for ANY url with a
# video/audio extension, with no host check at all, unlike every named
# vendor platform (granicus/civicclerk/legistar/...), which requires
# matching a specific vendor domain. That makes it the one platform
# category a broad homepage-anchor scan (what this pilot does, via
# find_platform_link()/find_hop_links() -- see wo147_access_ladder_
# sweep.py) can match on a video that has NOTHING to do with the
# government at all. Confirmed live in this pilot's own first smoke-test
# row: Dubois town, WY's homepage links out to the National Park Service,
# and a Yellowstone visitor-orientation .mp4 on nps.gov matched as a
# "direct_file" hit. direct_file_hit_is_plausible() below is this
# pilot's own sanity check, not a change to detect_platform() itself.
_DIRECT_FILE_TRUSTED_SHARING_HOSTS = ("drive.google.com", "dropbox.com")

REPORT_FIELDS = list(CANDIDATE_FIELDS) + [
    "access_mode",
    "rung_answered",
    "bucket",
    "platform",
    "hit_url",
    "final_url",
    "waf_family",
    "note",
    "elapsed_seconds",
    "exception",
    "final_url_is_youtube",
    "direct_file_plausible",
]


@dataclass
class PilotRow:
    gov_id: str
    name: str
    state: str
    country: str
    gov_kind: str
    population: str
    domain: str
    reject_reason: str


def load_candidates(csv_path: Path) -> List[PilotRow]:
    """Reads WO-908's candidate CSV: one real, random small-government
    row per line (gov_id, name, state, country, gov_kind, population,
    domain, reject_reason), pulled from the live Gov Coverage dashboard
    on 2026-09-19 -- county/municipality/township only, no school
    districts, every row with a real domain on file and a
    `no-platform-link-found`/`no-platform-signature` reject reason.
    Raises ValueError naming the missing column(s) if the file doesn't
    have what this pilot needs, rather than failing confusingly deep
    inside the ladder call."""
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(CANDIDATE_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{csv_path} is missing required column(s): {sorted(missing)}"
            )
        return [
            PilotRow(**{k: (row.get(k) or "").strip() for k in CANDIDATE_FIELDS})
            for row in reader
        ]


def classify_bucket(platform: Optional[str], rung_answered: str) -> str:
    """Buckets one `LadderResult` into exactly the 5 categories this
    pilot reports: plain / browser-headers / headless / challenge / dead.

    `dead` deliberately merges two different raw ladder outcomes -- a
    true access dead-end (DNS failure, blocked under both plain and
    browser headers, a timeout with no page at all -- `rung_answered` is
    "dead" or "none") and a rung that was reached but found no real
    platform link at all (`rung_answered` is "plain"/"browser-headers"/
    "headless" but `platform` is falsy). That is the literal shape asked
    for: "how many...via plain HTTP, via browser headers, via headless,
    how many hit a challenge, how many stayed dead/nothing found." The
    finer distinction inside "dead" (why) is preserved on every row of
    the report CSV via the raw `access_mode`/`note` columns."""
    if platform:
        if rung_answered in ("plain", "browser-headers", "headless"):
            return rung_answered
        # Not expected given LadderResult's own shape (a hit always
        # carries a rung_answered naming the rung that found it) -- fall
        # through to "dead" rather than raising; this is a report, not a
        # correctness gate on the ladder itself.
    if rung_answered == "challenge":
        return "challenge"
    return "dead"


def _registrable_domain(host: str) -> str:
    """Crude last-two-labels domain family (`duboiswyoming.org` ->
    `duboiswyoming.org`, `www.duboiswyoming.org` -> `duboiswyoming.org`,
    `sub.city.us` -> `city.us`). Good enough for this pilot's own
    same-government comparison below -- not a general public-suffix-list
    implementation, and not meant to be reused for anything stricter."""
    parts = [p for p in host.lower().split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def direct_file_hit_is_plausible(gov_domain: str, hit_url: str) -> bool:
    """See this module's `_DIRECT_FILE_TRUSTED_SHARING_HOSTS` comment
    above for why `direct_file` specifically needs this check. True when
    the hit's own host shares a domain family with the government's own
    site (the real Palisade/Dundee/Cayuga-Heights shape `direct_file.py`
    was built for), or is one of the two file-sharing hosts that
    module's own real fixtures confirm small governments actually use for
    meeting video (Google Drive, Dropbox)."""
    hit_host = urlparse(hit_url).netloc.lower()
    if not hit_host:
        return False
    if any(h in hit_host for h in _DIRECT_FILE_TRUSTED_SHARING_HOSTS):
        return True
    gov_host = urlparse(ladder.normalize_home_url(gov_domain)).netloc.lower()
    return _registrable_domain(hit_host) == _registrable_domain(gov_host)


@dataclass
class BucketCounts:
    plain: int = 0
    browser_headers: int = 0
    headless: int = 0
    challenge: int = 0
    dead: int = 0

    @property
    def total(self) -> int:
        return (
            self.plain
            + self.browser_headers
            + self.headless
            + self.challenge
            + self.dead
        )

    @property
    def found_total(self) -> int:
        return self.plain + self.browser_headers + self.headless


_BUCKET_ATTR = {
    "plain": "plain",
    "browser-headers": "browser_headers",
    "headless": "headless",
    "challenge": "challenge",
    "dead": "dead",
}


def tally_buckets(bucket_values: List[str]) -> BucketCounts:
    counts = BucketCounts()
    for b in bucket_values:
        attr = _BUCKET_ATTR.get(b)
        if attr is None:
            raise ValueError(f"unknown bucket value: {b!r}")
        setattr(counts, attr, getattr(counts, attr) + 1)
    return counts


def summarize_by_gov_kind(rows: List[dict]) -> Dict[str, BucketCounts]:
    """`rows` is a list of dicts each carrying at least "gov_kind" and
    "bucket" (already classified by `classify_bucket()`). Returns
    {"overall": ..., <gov_kind>: ...} for every distinct `gov_kind` seen
    in `rows`, so a caller can print a per-kind breakdown without forcing
    one on a kind that isn't actually present."""
    out: Dict[str, BucketCounts] = {
        "overall": tally_buckets([r["bucket"] for r in rows])
    }
    for kind in sorted({r["gov_kind"] for r in rows}):
        out[kind] = tally_buckets([r["bucket"] for r in rows if r["gov_kind"] == kind])
    return out


def print_summary(rows: List[dict]) -> None:
    by_kind = summarize_by_gov_kind(rows)
    print("\n--- WO-908 headless pilot summary ---")
    print(
        f"{'group':14} {'n':>4} {'plain':>6} {'browser-hdrs':>13} "
        f"{'headless':>9} {'challenge':>10} {'dead':>5} {'found':>6}"
    )
    for key in ["overall"] + sorted(k for k in by_kind if k != "overall"):
        c = by_kind[key]
        print(
            f"{key:14} {c.total:>4} {c.plain:>6} {c.browser_headers:>13} "
            f"{c.headless:>9} {c.challenge:>10} {c.dead:>5} {c.found_total:>6}"
        )


def _already_done(report_csv: Path) -> set:
    done = set()
    if report_csv.exists():
        with report_csv.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                gid = r.get("gov_id")
                if gid:
                    done.add(gid)
    return done


async def process_row(session: aiohttp.ClientSession, row: PilotRow) -> dict:
    """Runs the unmodified ladder for one government and returns a report
    row (dict, keyed by REPORT_FIELDS). Never raises: a real exception
    from run_access_ladder() itself is caught and recorded in the
    `exception` column (bucketed as `dead`) so one bad row can't kill the
    whole run -- the caller's own consecutive-exception counter is what
    decides whether to abort."""
    t0 = time.monotonic()
    out = {k: getattr(row, k) for k in CANDIDATE_FIELDS}
    try:
        result = await ladder.run_access_ladder(
            session, row.name, row.state, row.domain, ""
        )
        bucket = classify_bucket(result.platform, result.rung_answered)
        note = result.note
        direct_file_plausible = ""
        if result.platform == "direct_file" and result.hit_url:
            plausible = direct_file_hit_is_plausible(row.domain, result.hit_url)
            direct_file_plausible = str(plausible)
            if not plausible:
                # Downgrade: a direct_file hit that doesn't share the
                # government's own domain (and isn't a known file-sharing
                # host) is, on the evidence so far, an unrelated video
                # picked up by a bare extension match, not a real meeting
                # recording -- see this module's _DIRECT_FILE_TRUSTED_
                # SHARING_HOSTS comment. Reported in the "dead" bucket
                # rather than credited as a found platform link.
                bucket = "dead"
                note = (f"{note}; " if note else "") + (
                    "direct_file hit rejected as implausible (different "
                    f"domain than {row.domain}): {result.hit_url}"
                )
        final_host = urlparse(result.final_url or "").netloc.lower()
        out.update(
            access_mode=result.access_mode,
            rung_answered=result.rung_answered,
            bucket=bucket,
            platform=result.platform or "",
            hit_url=result.hit_url or "",
            final_url=result.final_url or "",
            waf_family=result.waf_family,
            note=note,
            exception="",
            direct_file_plausible=direct_file_plausible,
            # Belt-and-braces audit column, not a behavior change: this
            # repo's "never fetch youtube.com/youtu.be directly" rule for
            # this pilot should be a non-issue by construction --
            # find_platform_link() scans the ALREADY-fetched page's own
            # anchors and matches any youtube.com/youtu.be href straight
            # off that HTML with zero extra request, and it runs before
            # find_hop_links() is ever computed, so a bare YouTube anchor
            # can't survive into the hop-follow loop that actually issues
            # more HTTP requests. This column records the final fetch's
            # own host so that claim is verified from the real run's
            # data, not just asserted from reading the code.
            final_url_is_youtube=str(any(h in final_host for h in _YOUTUBE_HOSTS)),
        )
    except Exception as e:  # noqa: BLE001 -- record and keep going
        out.update(
            access_mode="",
            rung_answered="",
            bucket="dead",
            platform="",
            hit_url="",
            final_url="",
            waf_family="",
            note="",
            exception=f"{type(e).__name__}: {e}"[:300],
            final_url_is_youtube="False",
            direct_file_plausible="",
        )
    out["elapsed_seconds"] = f"{time.monotonic() - t0:.1f}"
    return out


async def run_pilot(
    candidates_csv: Path, out_csv: Path, limit: Optional[int]
) -> List[dict]:
    register_all_finders()
    rows = load_candidates(candidates_csv)
    if limit:
        rows = rows[:limit]
    done = _already_done(out_csv)
    to_process = [r for r in rows if r.gov_id not in done]
    print(
        f"{len(rows)} candidate(s) loaded, {len(done)} already in {out_csv}, "
        f"{len(to_process)} to process this run."
    )

    is_new = not out_csv.exists()
    all_records: List[dict] = []
    if not is_new:
        with out_csv.open(newline="", encoding="utf-8") as f:
            all_records.extend(csv.DictReader(f))

    consecutive_errors = 0
    with out_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
        if is_new:
            writer.writeheader()
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                record = await process_row(session, row)
                writer.writerow(record)
                f.flush()
                all_records.append(record)
                print(
                    f"[{i + 1}/{len(to_process)}] {row.name}, {row.state} "
                    f"({row.gov_kind}) -- {record['elapsed_seconds']}s -- "
                    f"bucket={record['bucket']} platform={record['platform'] or '-'}"
                )
                if record["exception"]:
                    consecutive_errors += 1
                    print(f"    EXCEPTION: {record['exception']}", file=sys.stderr)
                else:
                    consecutive_errors = 0
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors. "
                        "Re-run with the same --out-csv to resume (already-"
                        "processed gov_ids are skipped).",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(ladder.GOV_DELAY_SECONDS)
    return all_records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates-csv", type=Path, default=None)
    parser.add_argument(
        "--out-csv", type=Path, default=Path("/tmp/wo908_headless_pilot_report.csv")
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--report-only",
        type=Path,
        default=None,
        help="Skip the network sweep; just summarize an existing report CSV.",
    )
    args = parser.parse_args()

    if args.report_only:
        with args.report_only.open(newline="", encoding="utf-8") as f:
            records = list(csv.DictReader(f))
        print_summary(records)
        return

    if not args.candidates_csv:
        parser.error("--candidates-csv is required unless --report-only is given")

    records = asyncio.run(run_pilot(args.candidates_csv, args.out_csv, args.limit))
    print_summary(records)
    print(f"\nFull per-row report: {args.out_csv}")


if __name__ == "__main__":
    main()
