"""WO-1004 (2026-09-22): give the registry's `domain` field an automatic
health check, by reusing the passive-discovery pipeline's own fetch and
identity-check machinery (`scripts/wo282_targeted.py`, imported
unchanged: `polite_page_fetch`/`bounded_page_body` for the fetch,
`is_catch_all_response`/`_body_fingerprint` for the parked-domain guard,
`name_matches` for the identity check) against every government that
already HAS a `domain` on file in
`rtr-business/research/jurisdiction_coverage.csv` -- a different
population from the one WO-283 and its descendants (WO-292/320-338)
targeted, which was governments with NO known platform yet.

Why this exists: two hand audits found the registry's own `domain` field
is wrong or stale on a real slice of rows, and nothing catches this
automatically -- WO-145 (6 of 25, 24%: the domain is real and live, just
belongs to a DIFFERENT government sharing the platform/name/county --
e.g. Ventura city, IA resolving to Ventura County, CA's tenant) and
WO-347 (6 of 40, 15%: the domain is dead, migrated, or repurposed by an
unrelated site -- e.g. one taken over by a laser-engraving company). Both
times a human found this by hand-auditing a small sample of pipeline
output after the fact; nothing flags it on its own. See BACKLOG.md's
"The registry's `domain` field is wrong or stale on a real slice of
rows" entry (Ship next) for the full writeup and both audits' real
examples.

What this actually adds: one classification a domain-on-file row can
land in that the existing pipeline doesn't distinguish --
`domain_mismatch` (the page fetched fine, isn't a parked/catch-all
shell, isn't a human-verification challenge, but doesn't name this
government) -- alongside `domain_confirmed`, `domain_catch_all`,
`domain_challenge_gate`, and `domain_unreachable`. `classify_domain_
health()` below is the one pure function this WO adds; everything
around it -- the fetch, the catch-all guard, the identity check, the
per-host rate limiter, the wall-clock deadline, and the refusal to ever
follow a redirect onto a youtube.com/youtu.be host (already wired into
`bounded_page_body`'s own `page_url_skip()`) -- is imported unchanged
from `wo282_targeted.py`. This is deliberately a thin driver, not a new
ladder, the same shape WO-152's own docstring describes for its reuse of
`wo147_access_ladder_sweep.py`.

One deliberate difference from calling `fetch_domain_reference()`
wholesale: that function fetches BOTH a random nonsense path AND the
real homepage, to compare a later PROBED url against either. This
script's own primary fetch already IS the homepage -- comparing that
body against a homepage-vs-itself reference would trivially always
"match" -- so it only fetches the nonsense-path half itself
(`_fetch_nonsense_reference()` below, a narrow, explained reuse of
`fetch_domain_reference()`'s own nonsense-path branch, not a blind copy)
and compares the real homepage body against THAT. Skipping the wasted
second homepage fetch roughly halves the homepage-related request count
at this script's scale (every row in the registry with a domain, not a
few thousand).

Detection only: this script never writes to `jurisdiction_coverage.csv`
(`CLAUDE.md`'s standing rule -- never blank or overwrite `domain`),
never ingests, never resolves through an adapter. Its only output is a
worklist CSV for a human to hand-confirm before anything moves to
`alternate_domains`, the same bar WO-145 and WO-347 both used.

This session could not verify jurisdiction_coverage.csv's live header
directly -- `~/Documents/rtr-business` is off-limits to it per
`CLAUDE.md`'s standing rule -- so `load_registry_rows()` reads it
generically (`csv.DictReader`, no hardcoded column count, same defensive
pattern `scripts/registry_write_helper.py` uses) and only *requires* the
one column this WO's own filter needs (`domain`); `gov_id`/`name`/
`state`/`gov_kind` are read via `.get()` so a header that's close but not
byte-identical to what `docs/COVERAGE_HANDOVER.md` documents (and what
every WO script since WO-152 that reads this same file has used) doesn't
crash the run outright -- a row missing `name`/`state` just can't be
identity-checked and comes back `domain_unreachable` with that said
plainly in `evidence`, per this repo's "reports report, never guess"
rule, rather than a guessed verdict.

Usage (repo root, shared venv -- must run from a machine with
`~/Documents/rtr-business` checked out; this session cannot run it
itself, see the boundary note above):
    python3 scripts/wo1004_domain_health_check.py --limit 50
    python3 scripts/wo1004_domain_health_check.py   # full run, resumable

Output: `research/wo1004_domain_health.csv` (gov_id, name, state,
gov_kind, domain, outcome, evidence, http_status, checked_at),
append-mode, resumable by `gov_id` -- a rerun skips any `gov_id` already
in the output file, so an interrupted run restarts without re-fetching
what it already checked, the same pattern `wo283_targeted.py`'s own
`cmd_sweep()` uses.
"""

from __future__ import annotations

import argparse
import csv
import random
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from wo282_targeted import (  # noqa: E402
    NONSENSE_LABEL_LEN,
    _body_fingerprint,
    bounded_page_body,
    is_catch_all_response,
    name_matches,
    polite_fetch,
    polite_page_fetch,
)
from challenge_markers import is_challenge  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
REGISTRY_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
OUTPUT_CSV = RESEARCH_DIR / "wo1004_domain_health.csv"

OUTPUT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "domain",
    "outcome",
    "evidence",
    "http_status",
    "checked_at",
]

# Outcomes, in the order a reviewer should triage them: the new bucket
# this WO adds first, then the two inconclusive buckets, then the
# ordinary "couldn't even reach it" and "looks right" outcomes.
DOMAIN_MISMATCH = "domain_mismatch"
DOMAIN_CATCH_ALL = "domain_catch_all"
DOMAIN_CHALLENGE_GATE = "domain_challenge_gate"
DOMAIN_UNREACHABLE = "domain_unreachable"
DOMAIN_CONFIRMED = "domain_confirmed"

_write_lock = Lock()


def classify_domain_health(
    *,
    html: str | None,
    http_status: int | None,
    fetch_error: str,
    catch_all: bool,
    city_name: str,
    state: str,
) -> tuple[str, str]:
    """Pure classifier, no network -- easy to unit-test on its own.
    Checks in the order a human reviewer actually would: can we reach it
    at all, does it look like a parked/generic shell, does it look like
    a human-verification gate, and only then does the page actually name
    the right government. `evidence` is always a short, human-checkable
    string, never just a verdict -- this repo's "reports report, never
    guess" rule (CLAUDE.md)."""
    if fetch_error:
        return DOMAIN_UNREACHABLE, fetch_error
    if not html:
        status = f"http {http_status}" if http_status else "no response"
        return DOMAIN_UNREACHABLE, status
    if is_challenge(html):
        return DOMAIN_CHALLENGE_GATE, "human-verification challenge page"
    if catch_all:
        return (
            DOMAIN_CATCH_ALL,
            "homepage body matches this host's own nonsense-path response -- looks like a parked/generic template",
        )
    if not city_name:
        return DOMAIN_UNREACHABLE, "row has no name to check the page against"
    if name_matches(html, city_name, state):
        return DOMAIN_CONFIRMED, f"page names {city_name}, {state}"
    return (
        DOMAIN_MISMATCH,
        f"page fetched (http {http_status}) but does not name {city_name}, {state}",
    )


def _fetch_nonsense_reference(domain: str) -> tuple | None:
    """One extra light request per domain: a random nonsense path,
    fingerprinted the same way `fetch_domain_reference()`'s own
    'nonsense' entry is -- see this module's docstring for why this
    script doesn't call that function wholesale."""
    label = "".join(
        random.choices(string.ascii_lowercase + string.digits, k=NONSENSE_LABEL_LEN)
    )
    url = f"https://{domain}/rtr-probe-{label}"
    try:
        resp = polite_fetch(url, method="GET")
        if resp.status_code == 200 and resp.content:
            return _body_fingerprint(resp.content)
    except Exception:  # noqa: BLE001 -- a failed reference fetch just
        # means the catch-all guard can't fire for this domain; it fails
        # open, same as fetch_domain_reference()'s own reasoning.
        pass
    return None


def _normalize_domain(raw: str) -> str:
    """The registry's own `domain` column is documented and used
    elsewhere in this repo as a bare host (e.g. `emigration.utah.gov`),
    but this script can't verify that's true for every one of its rows
    from here -- strip an accidental scheme/path defensively rather than
    let a malformed value silently become a wrong probe URL."""
    value = (raw or "").strip()
    if "://" in value:
        value = value.split("://", 1)[1]
    return value.split("/", 1)[0].strip().lower()


def check_one_domain(row: dict) -> dict:
    domain = _normalize_domain(row.get("domain", ""))
    city_name = (row.get("name") or "").strip()
    state = (row.get("state") or "").strip()
    url = f"https://{domain}/"

    nonsense_ref = _fetch_nonsense_reference(domain)
    resp, skip_reason = polite_page_fetch(url)
    html = ""
    http_status = None
    catch_all = False
    fetch_error = skip_reason
    if resp is not None:
        http_status = resp.status_code
        try:
            body, body_skip = bounded_page_body(resp)
        finally:
            resp.close()
        if body_skip:
            fetch_error = fetch_error or body_skip
        elif body:
            if nonsense_ref is not None:
                catch_all = is_catch_all_response(body, {"nonsense": nonsense_ref})
            try:
                html = body.decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                html = ""

    outcome, evidence = classify_domain_health(
        html=html,
        http_status=http_status,
        fetch_error=fetch_error,
        catch_all=catch_all,
        city_name=city_name,
        state=state,
    )
    return {
        "gov_id": row.get("gov_id", ""),
        "name": city_name,
        "state": state,
        "gov_kind": row.get("gov_kind", ""),
        "domain": domain,
        "outcome": outcome,
        "evidence": evidence,
        "http_status": http_status or "",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def load_registry_rows() -> list[dict]:
    with open(REGISTRY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if (r.get("domain") or "").strip()]


def load_done_gov_ids() -> set[str]:
    if not OUTPUT_CSV.exists():
        return set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def log(msg: str) -> None:
    print(f"[wo1004] {msg}", file=sys.stderr, flush=True)


def cmd_sweep(limit: int, concurrency: int) -> None:
    rows = load_registry_rows()
    done = load_done_gov_ids()
    remaining = [r for r in rows if r.get("gov_id") not in done]
    log(
        f"{len(rows)} rows with a domain on file, {len(done)} already "
        f"checked, {len(remaining)} remaining"
    )

    to_process = remaining[:limit] if limit else remaining
    log(f"checking {len(to_process)} at concurrency={concurrency}")

    write_header = not OUTPUT_CSV.exists()
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    completed = 0
    outcome_counts: dict[str, int] = {}
    with (
        open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        writer = csv.DictWriter(out, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()

        futures = {pool.submit(check_one_domain, row): row for row in to_process}
        for fut in as_completed(futures):
            row = futures[fut]
            try:
                result = fut.result()
            except Exception as e:  # noqa: BLE001
                result = {
                    "gov_id": row.get("gov_id", ""),
                    "name": row.get("name", ""),
                    "state": row.get("state", ""),
                    "gov_kind": row.get("gov_kind", ""),
                    "domain": row.get("domain", ""),
                    "outcome": DOMAIN_UNREACHABLE,
                    "evidence": f"exception: {e}"[:300],
                    "http_status": "",
                    "checked_at": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                }
            with _write_lock:
                writer.writerow(result)
                out.flush()
            outcome_counts[result["outcome"]] = (
                outcome_counts.get(result["outcome"], 0) + 1
            )
            completed += 1
            if completed % 25 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                    f"rate={rate:.1f}/min {outcome_counts}"
                )

    log(f"done: {completed} checked, {outcome_counts}")
    if outcome_counts.get(DOMAIN_MISMATCH):
        log(
            f"{outcome_counts[DOMAIN_MISMATCH]} rows classified domain_mismatch -- "
            f"hand-confirm each in {OUTPUT_CSV} before moving anything to "
            "alternate_domains. Never overwrite domain directly (CLAUDE.md's "
            "standing rule)."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap how many rows to check this run (0 = all remaining).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=16,
        help=(
            "Governments checked at once (default 16, lower than "
            "wo283_targeted.py's 32 -- every request here already has a "
            "confirmed live domain, not a guess, so a slower opening pace "
            "is the safer default for a first run over this population)."
        ),
    )
    args = parser.parse_args()
    cmd_sweep(args.limit, args.concurrency)


if __name__ == "__main__":
    main()
