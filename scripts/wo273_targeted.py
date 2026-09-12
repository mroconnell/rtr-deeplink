"""WO-273 (2026-09-12): full-scale passive platform discovery, phase 3 --
targeted fetches of the SPECIFIC URLs phase 2 flagged, many governments at
once.

Unlike phase 1 (broad, cheap, per-government reconnaissance), phase 3 is
driven by phase 2's scored output, URL by URL: for every government with
at least one flagged URL, take the top N (default 5, strongest first --
a named platform-path hit, then the highest-lift hub-vocabulary hit, then
the best meeting/video-vocabulary hit) and actually fetch them: HEAD
first (alive?), GET the ones that answer, run
`scripts/platform_fingerprints.py`'s `fingerprint()` and
`app.platforms.base.detect_platform()` over the page's own links, and
require the page to NAME this government (its city/county name AND its
state) before a platform or hub counts as confirmed -- a resolving vendor
label or a bare 200 is never evidence on its own (WO-260/268's finding:
7 of 9 vendors answer any label). Where a Wayback capture of that exact
URL exists and is fresh (<18 months), its `id_` raw body is read first;
live GET only when the capture is missing or stale. Governments with NO
flagged URL are probed instead against a short list of named first-party
paths (this WO's own brief's list -- WO-272's own longer template file
had not landed on `main` as of this run, checked directly).

**Concurrency (Ryan, 2026-09-12): every government is on its own domain,
so run a lot of them at once.** Default 32 governments concurrently
(`--concurrency`), politeness enforced PER HOST (not globally) via the
same `HostRateLimiter` phase 1 uses: one request in flight per host,
>=2.5s between requests to the SAME host, honest User-Agent. A flagged
URL that resolves to a known vendor host is rate-limited under the
VENDOR FAMILY NAME, not its literal host, so 32 governments that all
happen to flag a granicus.com URL don't turn into 32 simultaneous hits on
one vendor (`wo273_recon.vendor_family_for_url`). Wayback `id_` archive
reads are capped separately at ARCHIVE_CONCURRENCY (8) in flight across
the whole run, same as phase 1, and the SAME confirmed-live CDX
degradation applies here (see wo273_recon.py's module docstring) -- an
exact-URL CDX lookup gets one short-timeout attempt, no retry (phase 3
already fetches many more distinct URLs than phase 1 did governments, so
retrying every one would multiply an already-slow resource), and falls
straight through to a live fetch on any failure.

Output: `research/wo273_targeted.csv`, one row per (government, URL)
actually fetched: domain, state, url, rank, source_score, fetch_method
(archived_id_/live), http_status, platform_confirmed, platform_signal,
name_match (bool -- did the page mention this government's own
name+state), timing_ms, error.

This script imports `app.platforms.base.detect_platform` and
`scripts/platform_fingerprints.py` -- per CLAUDE.md's worktree `.env`
bullet, ANY command running this script must set `DATABASE_URL`
explicitly (even though `detect_platform()` itself opens no DB
connection -- the import chain is pure regex/CSV, checked directly in
`app/platforms/base.py` and `app/utils/gov_registry/registry.py`, but the
rule is followed regardless as the safety net it's meant to be).

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo273_test.db" \\
        .venv/bin/python scripts/wo273_targeted.py --limit 50 --concurrency 32
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wo273_recon import (  # noqa: E402
    HEADERS,
    STALE_DAYS,
    _ARCHIVE_SEMA,
    RATE_LIMITER,
    capture_age_days,
    is_challenge,
    vendor_family_for_url,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from app.platforms.base import detect_platform  # noqa: E402
except Exception:  # noqa: BLE001 -- keep this script runnable even if the
    # app import chain ever grows a real dependency; platform_fingerprints
    # below still gives useful signal on its own.
    detect_platform = None

import platform_fingerprints  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo273_candidates.csv"
CLASSIFIED_CSV = RESEARCH_DIR / "wo273_classified.csv"
TARGETED_CSV = RESEARCH_DIR / "wo273_targeted.csv"

TOP_N_FLAGGED = 5
FIRST_PARTY_PROBE_PATHS = [
    "/AgendaCenter",
    "/AgendaOnline/Meetings/ViewMeeting",
    "/Citizens/",
    "/Portal/MeetingInformation.aspx",
    "/Archive.aspx?AMID=1",
]
GOV_TIMEOUT = 10  # 3s connect target / 10s read, one retry at most (brief)
CDX_EXACT_TIMEOUT = 6  # short, single attempt -- see module docstring


def log(msg: str) -> None:
    print(msg, flush=True)


def load_candidates() -> dict:
    by_domain = {}
    if CANDIDATES_CSV.exists():
        with open(CANDIDATES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                by_domain[row["domain"]] = row
    return by_domain


def load_classified() -> list:
    if not CLASSIFIED_CSV.exists():
        log(f"{CLASSIFIED_CSV} missing -- run wo273_classify.py first")
        sys.exit(1)
    with open(CLASSIFIED_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def top_flagged_urls(row: dict, n: int = TOP_N_FLAGGED) -> list:
    """(url, score, kind) tuples, strongest first: the platform's own
    evidence URL leads (implicitly highest), then the best hub URL, then
    the best meeting URL. Phase 2 already keeps only the single best hub
    and best meeting URL per government (not a full ranked list), so this
    is at most 3 URLs today -- the brief's "top N=5" is an upper bound,
    not a promise this phase always has 5 distinct candidates per
    government; recorded honestly rather than padded."""
    out = []
    seen = set()

    def add(url, score, kind):
        if url and url not in seen:
            seen.add(url)
            out.append((url, score, kind))

    if row.get("platform"):
        add(row.get("platform_evidence_url", ""), 9999.0, "platform")
    try:
        hub_score = float(row.get("hub_score") or 0)
    except ValueError:
        hub_score = 0.0
    try:
        meeting_score = float(row.get("meeting_score") or 0)
    except ValueError:
        meeting_score = 0.0
    if hub_score > 0:
        add(row.get("best_hub_url", ""), hub_score, "hub")
    if meeting_score > 0:
        add(row.get("best_meeting_url", ""), meeting_score, "meeting")
    out.sort(key=lambda t: -t[1])
    return out[:n]


def try_wayback_archived_body(url: str) -> tuple:
    """One short, single-attempt exact-URL CDX lookup (see module
    docstring on why this is deliberately not retried the way phase 1's
    per-government calls are). Returns (body_bytes_or_None, used_archive:
    bool)."""
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={url}&filter=statuscode:200&collapse=urlkey"
        "&limit=-3&fl=original,timestamp&output=json"
    )
    with _ARCHIVE_SEMA:
        try:
            resp = requests.get(cdx_url, headers=HEADERS, timeout=CDX_EXACT_TIMEOUT)
        except Exception:  # noqa: BLE001
            return None, False
    if resp.status_code != 200:
        return None, False
    try:
        rows = json.loads(resp.text)[1:]
    except Exception:  # noqa: BLE001
        return None, False
    if not rows:
        return None, False
    orig, ts = max(rows, key=lambda r: r[1] if len(r) > 1 else "")
    if capture_age_days(ts) > STALE_DAYS:
        return None, False
    id_url = f"https://web.archive.org/web/{ts}id_/{orig}"
    with _ARCHIVE_SEMA:
        try:
            resp = requests.get(id_url, headers=HEADERS, timeout=CDX_EXACT_TIMEOUT)
        except Exception:  # noqa: BLE001
            return None, False
    if resp.status_code == 200:
        return resp.content, True
    return None, False


def polite_fetch(url: str, method: str = "GET"):
    key = vendor_family_for_url(url)
    return RATE_LIMITER.wait_and_request(
        key,
        requests.request,
        method,
        url,
        headers=HEADERS,
        timeout=GOV_TIMEOUT,
        allow_redirects=True,
    )


def name_matches(html: str, city_name: str, state: str) -> bool:
    if not html or not city_name:
        return False
    text = html.lower()
    city_tokens = re.findall(r"[a-z]+", city_name.lower())
    city_hit = any(len(t) > 2 and t in text for t in city_tokens)
    state_hit = bool(state) and state.lower() in text
    return city_hit and state_hit


def fetch_and_score(url: str, city_name: str, state: str) -> dict:
    t0 = time.monotonic()
    out = {
        "url": url,
        "fetch_method": "",
        "http_status": None,
        "platform_confirmed": "",
        "platform_signal": "",
        "name_match": False,
        "error": "",
        "timing_ms": 0,
    }
    body, used_archive = try_wayback_archived_body(url)
    html = ""
    if body is not None:
        out["fetch_method"] = "archived_id_"
        out["http_status"] = 200
        try:
            html = body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            html = ""
    else:
        head_status = None
        try:
            head_resp = polite_fetch(url, method="HEAD")
            head_status = head_resp.status_code
            alive = head_status < 400
        except Exception:  # noqa: BLE001
            alive = True  # some servers reject HEAD; try GET anyway
        if not alive:
            out["fetch_method"] = "live"
            out["http_status"] = head_status
            out["error"] = "dead-on-head"
            out["timing_ms"] = int((time.monotonic() - t0) * 1000)
            return out
        out["fetch_method"] = "live"  # attempted regardless of outcome below
        try:
            resp = polite_fetch(url, method="GET")
            out["http_status"] = resp.status_code
            if resp.status_code == 200 and resp.text:
                if is_challenge(resp.text):
                    out["error"] = "challenge-gate"
                else:
                    html = resp.text
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:200]

    if html:
        out["name_match"] = name_matches(html, city_name, state)
        signals = platform_fingerprints.fingerprint(html, url=url)
        if signals:
            best = max(signals, key=lambda s: s[2])
            out["platform_signal"] = f"{best[0]}:{best[1]}({best[2]:.2f})"
            if out["name_match"]:
                out["platform_confirmed"] = best[0]
        elif detect_platform is not None:
            try:
                dp = detect_platform(url)
                if dp and dp != "unknown":
                    out["platform_signal"] = f"{dp}:url-shape"
                    if out["name_match"]:
                        out["platform_confirmed"] = dp
            except Exception:  # noqa: BLE001
                pass

    out["timing_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def process_government_targeted(row: dict, candidate_info: dict) -> list:
    city_name = candidate_info.get("city_name", "")
    state = candidate_info.get("state_or_province", "")
    domain = row["domain"]

    flagged = top_flagged_urls(row)
    results = []
    if flagged:
        for rank, (url, score, kind) in enumerate(flagged, start=1):
            r = fetch_and_score(url, city_name, state)
            r.update(
                domain=domain,
                state=state,
                rank=rank,
                source_score=score,
                source_kind=kind,
            )
            results.append(r)
    else:
        base = f"https://{domain}"
        for rank, path in enumerate(FIRST_PARTY_PROBE_PATHS, start=1):
            r = fetch_and_score(base + path, city_name, state)
            r.update(
                domain=domain,
                state=state,
                rank=rank,
                source_score=0.0,
                source_kind="first_party_probe",
            )
            results.append(r)
    return results


def load_done_domains() -> set:
    done = set()
    if TARGETED_CSV.exists():
        with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
            done = {row["domain"] for row in csv.DictReader(f)}
    return done


_write_lock = threading.Lock()
_FIELDNAMES = [
    "domain",
    "state",
    "url",
    "rank",
    "source_kind",
    "source_score",
    "fetch_method",
    "http_status",
    "platform_confirmed",
    "platform_signal",
    "name_match",
    "timing_ms",
    "error",
]


def cmd_sweep(limit: int, concurrency: int) -> None:
    classified = load_classified()
    candidates = load_candidates()
    done = load_done_domains()
    remaining = [r for r in classified if r["domain"] not in done]
    log(
        f"{len(done)} governments already done, {len(remaining)} remaining of {len(classified)}"
    )

    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} governments at concurrency={concurrency}")

    write_header = not TARGETED_CSV.exists()
    start = time.monotonic()
    completed = 0
    with (
        open(TARGETED_CSV, "a", newline="", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        writer = csv.DictWriter(out, fieldnames=_FIELDNAMES)
        if write_header:
            writer.writeheader()
        futures = {
            pool.submit(
                process_government_targeted, row, candidates.get(row["domain"], {})
            ): row
            for row in to_process
        }
        for fut in as_completed(futures):
            row = futures[fut]
            domain = row["domain"]
            try:
                results = fut.result()
            except Exception as e:  # noqa: BLE001
                results = [
                    {
                        **{k: "" for k in _FIELDNAMES},
                        "domain": domain,
                        "state": row.get("state", ""),
                        "error": str(e)[:200],
                    }
                ]
            with _write_lock:
                for r in results:
                    writer.writerow({k: r.get(k, "") for k in _FIELDNAMES})
                out.flush()
            completed += 1
            if completed % 10 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                    f"rate={rate:.1f} govs/min last={domain}"
                )

    elapsed = time.monotonic() - start
    rate = len(to_process) / (elapsed / 60) if elapsed > 0 else 0
    log(
        f"chunk done: {len(to_process)} governments in {elapsed:.0f}s "
        f"({rate:.2f} governments/min), "
        f"{len(remaining) - len(to_process)} remain unprocessed."
    )


def cmd_finalize() -> None:
    if not TARGETED_CSV.exists():
        log(f"{TARGETED_CSV} missing")
        return
    with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log(f"{len(rows)} (government, url) rows in {TARGETED_CSV}")
    doms = {r["domain"] for r in rows}
    log(f"  covering {len(doms)} distinct governments")
    by_method = {}
    for r in rows:
        by_method[r["fetch_method"] or "none"] = (
            by_method.get(r["fetch_method"] or "none", 0) + 1
        )
    log(f"fetch_method split: {by_method}")
    confirmed = [r for r in rows if r["platform_confirmed"]]
    log(
        f"platform_confirmed (name+state matched): {len(confirmed)} rows, "
        f"{len({r['domain'] for r in confirmed})} governments"
    )
    timings = [int(r["timing_ms"]) for r in rows if r.get("timing_ms")]
    if timings:
        timings.sort()
        log(
            f"per-URL fetch timing (ms): median={statistics.median(timings):.0f} "
            f"p95={timings[max(0, int(len(timings) * 0.95) - 1)]}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    if args.finalize:
        cmd_finalize()
        return
    cmd_sweep(args.limit, args.concurrency)


if __name__ == "__main__":
    main()
