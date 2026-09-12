"""WO-284 (2026-09-12): the WO-264 rows the close-out never worked.

WO-264's overnight sweep (`scripts/wo264_overnight_sweep.py`) stopped at
1,894 completed governments per Ryan's instruction, but the worker kept
running and wrote 376 more rows before it was actually killed (2,270
completed total, `research/wo264_completed_gov_ids.txt`). The close-out
session (`BACKLOG_DONE.md`, "WO-264 close-out") only hand-read the 464
video candidates the first 1,894 rows produced. This script works the
three groups that leaves:

  (a) `listing-found-no-platform` rows (1,246, re-derived directly
      against `research/wo264_report.csv` -- the brief's "1,016" was
      wrong, corrected here): a meetings/agendas listing page was found
      but never fetched a second time to look one hop further into it.
      `cmd_hop_a` fetches `listing_url`, scores its links with BOTH the
      hub and meeting/video vocabularies (`wo281_homepage_hop`'s
      `extract_links()`/`link_kind_for_url()`, WO-274's measured
      weights), runs `detect_platform()` on every href, and follows the
      best meeting-detail-or-video link one hop further (<=3 fetches per
      government total) with the catch-all + 800-byte-floor confirmation
      `wo281_homepage_hop.fetch_and_confirm()` already implements.
  (b) The 53 actionable rows among the 376 post-stop rows (47
      `platform-found`, 6 `video-candidate`) that were never hand-read at
      all -- re-derived count, not the brief's "376" (that's the whole
      post-stop population, most of which is `nothing`/`blocked`/
      `human-gate` and needs no action).
  (c) 47 `no-platform-link-found` rows from `wo264_platform_decisions.csv`
      -- re-checked, and NOT "channel found, no meeting on it" as the
      brief assumed: every one of these 47 rows' `platform_evidence_url`
      is a bare `https://www.youtube.com` or `https://www.youtube.com/`
      (a generic "visit YouTube" player button or footer social icon),
      never a real channel link -- exactly the false-positive shape
      `detect_platform()`'s plain netloc match produces and
      `classify_youtube_url()` (WO-285, widened `find_youtube_links()`)
      correctly rejects. `cmd_second_look_c` re-fetches the government's
      own front page and looks for a REAL channel-shaped YouTube link
      with the widened WO-285 scanner before giving up a second time.

Reuses, not reimplements: `wo281_homepage_hop.fetch_with_ladder/
extract_links/fetch_and_confirm/link_kind_for_url`, `wo273_recon`'s
HEADERS/RATE_LIMITER/is_challenge/vendor_family_for_url, `wo273_targeted.
try_wayback_archived_body/name_matches`, `wo147_access_ladder_sweep.
find_hop_links`, `wo264_overnight_sweep.find_video_candidates`,
`wo235_channel_pilot.find_youtube_links/classify_youtube_url`,
`app.platforms.base.detect_platform`.

Politeness: concurrency 32 governments in flight (--concurrency), one
request per host >=2.5s apart (`wo273_recon.RATE_LIMITER`, imported not
reimplemented), archive-first fetch, browser headers only after a 403 or
a dropped connection, stop cold at a human-verification gate.

Usage (repo root, shared venv, DATABASE_URL required by the app/archive
import chain per CLAUDE.md's worktree .env bullet):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo284_test.db" \\
        /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python \\
        scripts/wo284_listing_hop.py population
    ... hop-a --limit 200 --concurrency 32
    ... second-look-c --limit 50 --concurrency 16
    ... group-b --limit 60 --concurrency 16
"""

from __future__ import annotations

import argparse
import csv
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from wo273_recon import (  # noqa: E402
    vendor_family_for_url,
)
import wo281_homepage_hop as h1  # noqa: E402
from wo147_access_ladder_sweep import find_hop_links  # noqa: E402
import wo264_overnight_sweep as overnight  # noqa: E402
import wo235_channel_pilot as ytscan  # noqa: E402


RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
WO264_REPORT = RESEARCH_DIR / "wo264_report.csv"
WO264_PLATFORM_DECISIONS = RESEARCH_DIR / "wo264_platform_decisions.csv"
WO264_HAND_READ = RESEARCH_DIR / "wo264_hand_read_decisions.csv"

POPULATION_CSV = RESEARCH_DIR / "wo284_population.csv"
HOP_A_CSV = RESEARCH_DIR / "wo284_hop_a.csv"
SECOND_LOOK_C_CSV = RESEARCH_DIR / "wo284_second_look_c.csv"
GROUP_B_CSV = RESEARCH_DIR / "wo284_group_b.csv"

GOV_TIMEOUT = (3, 10)

_write_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------


def load_report_rows() -> list:
    with open(WO264_REPORT, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def hand_read_gov_ids() -> set:
    with open(WO264_HAND_READ, newline="", encoding="utf-8") as f:
        return {row["gov_id"] for row in csv.DictReader(f)}


def group_a_rows() -> list:
    rows = load_report_rows()
    return [
        r
        for r in rows
        if r["outcome"] == "listing-found-no-platform" and r.get("listing_url")
    ]


def group_b_rows() -> list:
    rows = load_report_rows()
    hr = hand_read_gov_ids()
    return [
        r
        for r in rows
        if r["outcome"] in ("platform-found", "video-candidate")
        and r["gov_id"] not in hr
    ]


def group_c_rows() -> list:
    with open(WO264_PLATFORM_DECISIONS, newline="", encoding="utf-8") as f:
        decisions = list(csv.DictReader(f))
    c_ids = [r["gov_id"] for r in decisions if r["verdict"] == "no-platform-link-found"]
    by_gov = {r["gov_id"]: r for r in load_report_rows()}
    out = []
    for gid in c_ids:
        rep = by_gov.get(gid)
        if rep:
            out.append(rep)
    return out


def cmd_population() -> None:
    a = group_a_rows()
    b = group_b_rows()
    c = group_c_rows()
    rows = load_report_rows()
    log(f"wo264_report.csv total completed rows: {len(rows)}")
    log(f"group a (listing-found-no-platform, has listing_url): {len(a)}")
    log(f"group b (platform-found/video-candidate, never hand-read): {len(b)}")
    log(f"group c (no-platform-link-found, bare-youtube-link false positive): {len(c)}")
    with open(POPULATION_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "definition", "count"])
        w.writerow(["a", "listing-found-no-platform, one hop into listing_url", len(a)])
        w.writerow(["b", "platform-found/video-candidate, never hand-read", len(b)])
        w.writerow(["c", "no-platform-link-found second look", len(c)])
    log(f"wrote {POPULATION_CSV}")


# ---------------------------------------------------------------------------
# Group (a): one hop into listing_url
# ---------------------------------------------------------------------------

_A_FIELDS = [
    "gov_id",
    "name",
    "state",
    "listing_url",
    "hop1_access_mode",
    "hop1_fetch_method",
    "outcome",
    "best_url",
    "best_link_kind",
    "platform_found",
    "video_candidate_urls",
    "hop2_name_match",
    "hop2_platform_confirmed",
    "error",
]


def process_group_a_row(row: dict) -> dict:
    gov_id = row["gov_id"]
    name = row.get("name", "")
    state = row.get("state", "")
    listing_url = row["listing_url"]
    domain = urlparse(listing_url).netloc or row.get("domain_tried", "")
    out = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "listing_url": listing_url,
        "hop1_access_mode": "",
        "hop1_fetch_method": "",
        "outcome": "listing-unreachable",
        "best_url": "",
        "best_link_kind": "",
        "platform_found": "",
        "video_candidate_urls": "",
        "hop2_name_match": "",
        "hop2_platform_confirmed": "",
        "error": "",
    }
    try:
        fetch = h1.fetch_with_ladder(listing_url, rate_key=domain)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        return out
    out["hop1_access_mode"] = fetch["access_mode"]
    out["hop1_fetch_method"] = fetch["fetch_method"]
    if not fetch["html"]:
        out["error"] = fetch.get("error", "")
        return out

    html, final_url = fetch["html"], fetch["final_url"]

    # detect_platform() on every href, scored with hub AND meeting vocab.
    links = h1.extract_links(html, final_url)
    outright = [link for link in links if link.get("platform_outright")]
    video_cands = overnight.find_video_candidates(html, final_url)
    if video_cands:
        out["video_candidate_urls"] = "|".join(video_cands[:5])
    if outright:
        best = outright[0]
        out["outcome"] = "platform-found-on-listing"
        out["best_url"] = best["url"]
        out["best_link_kind"] = best["link_kind"]
        out["platform_found"] = best["platform_outright"]
        return out
    if video_cands:
        out["outcome"] = "video-found-on-listing"
        out["best_url"] = video_cands[0]
        return out

    # No outright platform/video link -- take the best meeting-detail or
    # hub link up to 3 hops further.
    meeting_links = [link for link in links if link["link_kind"] == "meeting"]
    ranked_hub_urls = find_hop_links(html, final_url)[:5]
    candidates = []
    seen = set()
    for link in meeting_links:
        if link["url"] not in seen:
            candidates.append((link["url"], "meeting"))
            seen.add(link["url"])
    for u in ranked_hub_urls:
        if u not in seen:
            meta = next((link for link in links if link["url"] == u), None)
            kind = meta["link_kind"] if meta else "hub"
            candidates.append((u, kind))
            seen.add(u)
    candidates = candidates[:3]

    if not candidates:
        out["outcome"] = "nothing"
        return out

    for cand_url, cand_kind in candidates:
        conf = h1.fetch_and_confirm(cand_url, cand_kind, name, state, None)
        if conf.get("below_byte_floor") or conf.get("is_soft_200"):
            continue
        if conf.get("platform_confirmed"):
            out["outcome"] = (
                "meeting-detail-page-found"
                if cand_kind == "meeting"
                else "platform-found-on-hop2"
            )
            out["best_url"] = cand_url
            out["best_link_kind"] = cand_kind
            out["platform_found"] = conf["platform_confirmed"]
            out["hop2_name_match"] = conf.get("name_match")
            out["hop2_platform_confirmed"] = conf["platform_confirmed"]
            return out
        # even without a full confirm, a raw video link on the hop2 page
        # is worth recording
        hop2_html = ""
        try:
            hop2_fetch = h1.fetch_with_ladder(
                cand_url, rate_key=vendor_family_for_url(cand_url)
            )
            hop2_html = hop2_fetch.get("html", "")
        except Exception:  # noqa: BLE001
            hop2_html = ""
        if hop2_html:
            hop2_video = overnight.find_video_candidates(hop2_html, cand_url)
            if hop2_video:
                out["outcome"] = "video-found-on-hop2"
                out["best_url"] = hop2_video[0]
                out["video_candidate_urls"] = "|".join(hop2_video[:5])
                return out

    out["outcome"] = "nothing"
    out["best_url"] = candidates[0][0] if candidates else ""
    return out


def load_done(path: Path, key: str = "gov_id") -> set:
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {row[key] for row in csv.DictReader(f)}


def cmd_hop_a(limit: int, concurrency: int) -> None:
    population = group_a_rows()
    done = load_done(HOP_A_CSV)
    remaining = [r for r in population if r["gov_id"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(population)}")
    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} at concurrency={concurrency}")

    write_header = not HOP_A_CSV.exists()
    start = time.monotonic()
    completed = 0
    with (
        open(HOP_A_CSV, "a", newline="", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        writer = csv.DictWriter(out, fieldnames=_A_FIELDS)
        if write_header:
            writer.writeheader()
        futures = {pool.submit(process_group_a_row, r): r for r in to_process}
        for fut in as_completed(futures):
            row = futures[fut]
            try:
                result = fut.result()
            except Exception as e:  # noqa: BLE001
                result = {k: "" for k in _A_FIELDS}
                result.update(
                    gov_id=row["gov_id"],
                    name=row.get("name", ""),
                    state=row.get("state", ""),
                    listing_url=row.get("listing_url", ""),
                    outcome="error",
                    error=str(e)[:200],
                )
            with _write_lock:
                writer.writerow({k: result.get(k, "") for k in _A_FIELDS})
                out.flush()
            completed += 1
            if completed % 25 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                    f"rate={rate:.1f}/min last={result.get('gov_id')}"
                )
    elapsed = time.monotonic() - start
    log(
        f"chunk done: {len(to_process)} in {elapsed:.0f}s, "
        f"{len(remaining) - len(to_process)} remain. resume with the same command."
    )


def cmd_finalize_hop_a() -> None:
    if not HOP_A_CSV.exists():
        log("no hop-a output yet")
        return
    with open(HOP_A_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    from collections import Counter

    c = Counter(r["outcome"] for r in rows)
    log(f"{len(rows)} rows processed")
    for k, v in c.most_common():
        log(f"  {v}  {k}")


# ---------------------------------------------------------------------------
# Group (c): second look for a real YouTube channel link
# ---------------------------------------------------------------------------

_C_FIELDS = [
    "gov_id",
    "name",
    "state",
    "domain_tried",
    "front_page_access_mode",
    "real_channel_links",
    "outcome",
    "note",
]


def process_group_c_row(row: dict) -> dict:
    gov_id = row["gov_id"]
    name = row.get("name", "")
    state = row.get("state", "")
    domain = row.get("domain_tried", "")
    out = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "domain_tried": domain,
        "front_page_access_mode": "",
        "real_channel_links": "",
        "outcome": "front-page-unreachable",
        "note": "",
    }
    if not domain:
        out["note"] = "no domain_tried recorded"
        return out
    url = domain if domain.startswith("http") else f"https://{domain}/"
    try:
        fetch = h1.fetch_with_ladder(url, rate_key=urlparse(url).netloc or domain)
    except Exception as e:  # noqa: BLE001
        out["note"] = str(e)[:200]
        return out
    out["front_page_access_mode"] = fetch["access_mode"]
    if not fetch["html"]:
        out["note"] = fetch.get("error", "")
        return out

    hits = ytscan.find_youtube_links(fetch["html"], fetch["final_url"])
    real_channels = [
        u
        for kind, u in hits
        if kind == "channel"
        and u.rstrip("/")
        not in (
            "https://www.youtube.com",
            "http://www.youtube.com",
        )
    ]
    if not real_channels:
        out["outcome"] = "no-real-channel-link-confirmed-still-a-false-positive"
        return out
    out["real_channel_links"] = "|".join(sorted(set(real_channels))[:3])
    out["outcome"] = "real-channel-link-found"
    out["note"] = "channel found, still needs the hand-read gate + channel scan"
    return out


def cmd_second_look_c(limit: int, concurrency: int) -> None:
    population = group_c_rows()
    done = load_done(SECOND_LOOK_C_CSV)
    remaining = [r for r in population if r["gov_id"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(population)}")
    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} at concurrency={concurrency}")

    write_header = not SECOND_LOOK_C_CSV.exists()
    start = time.monotonic()
    completed = 0
    with (
        open(SECOND_LOOK_C_CSV, "a", newline="", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        writer = csv.DictWriter(out, fieldnames=_C_FIELDS)
        if write_header:
            writer.writeheader()
        futures = {pool.submit(process_group_c_row, r): r for r in to_process}
        for fut in as_completed(futures):
            row = futures[fut]
            try:
                result = fut.result()
            except Exception as e:  # noqa: BLE001
                result = {k: "" for k in _C_FIELDS}
                result.update(
                    gov_id=row["gov_id"],
                    name=row.get("name", ""),
                    state=row.get("state", ""),
                    outcome="error",
                    note=str(e)[:200],
                )
            with _write_lock:
                writer.writerow({k: result.get(k, "") for k in _C_FIELDS})
                out.flush()
            completed += 1
            if completed % 10 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                log(f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s")
    elapsed = time.monotonic() - start
    log(
        f"chunk done: {len(to_process)} in {elapsed:.0f}s, "
        f"{len(remaining) - len(to_process)} remain."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("population")

    p_a = sub.add_parser("hop-a")
    p_a.add_argument("--limit", type=int, default=0)
    p_a.add_argument("--concurrency", type=int, default=32)
    p_a.add_argument("--finalize", action="store_true")

    p_c = sub.add_parser("second-look-c")
    p_c.add_argument("--limit", type=int, default=0)
    p_c.add_argument("--concurrency", type=int, default=16)

    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    if args.cmd == "population":
        cmd_population()
    elif args.cmd == "hop-a":
        if args.finalize:
            cmd_finalize_hop_a()
        else:
            cmd_hop_a(args.limit, args.concurrency)
    elif args.cmd == "second-look-c":
        cmd_second_look_c(args.limit, args.concurrency)


if __name__ == "__main__":
    main()
