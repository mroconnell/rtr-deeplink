#!/usr/bin/env python3
"""WO-919 (2026-09-20): passive check + access ladder on the state
legislature chamber rows from rtr-business's 50_state_legislative_media_recon.md.

Architecture rule (rtr-business research/open-questions.md, "State legislature
meeting media"): one government per state (gov_id us:state:NN), the chamber is
the body. This script never mints ids and never touches
jurisdiction_coverage.csv; per-chamber results go to wo919_ files only.

Input: research/wo919_population.csv (one row per chamber, parsed from the
recon table, plus `hub_used` = the hub actually checked -- the recon row's own
hub except the four suspect rows Phase 1 corrected, and the cleanup-section
alternates where the recon's own cleanup pass found a better one).

Phase "passive": `verify_hub(hub_used, deep_walk=True)` once per distinct hub
(cached), so two chambers sharing a hub share one check; the verdict is then
copied to each chamber row and flagged `shared_hub`. A shared-hub verdict says
nothing about which chamber a meeting belongs to -- that is the hand-read's job.

Phase "ladder": for rows the passive phase left with no meeting, run
`run_access_ladder()` against the hub's own host (plain -> browser headers
after a 403/drop -> one hop -> headless only for a loaded page with no visible
link; stops at a human-verification gate) and record access_mode per host.
Hosts whose www CNAMEs to granicusgovaccess.net/opencities.com are skipped
(`blocked-waf-akamai`).

Never fetches youtube.com/youtu.be (verify_hub's own guard). Never downloads a
media file. One host at a time, 2 s between requests to a host (in the
ladder), 1.5 s between distinct hubs.

Usage (repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo919_scratch.db" \\
        .venv/bin/python scripts/wo919_verify.py --phase passive --limit 25
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
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

import scripts.wo147_access_ladder_sweep as ladder  # noqa: E402
import scripts.wo273_recon as w273  # noqa: E402
import scripts.wo283_recon as w283  # noqa: E402

register_all_finders()


async def _headless_disabled(url):  # noqa: ARG001
    """Conductor rule (2026-09-20): a headless Chromium load of a page that
    embeds YouTube makes the browser itself contact youtube.com from this
    machine, which only the drip Mac may do. Until `_block_youtube_requests()`
    lands in wo147_access_ladder_sweep.py, this run never uses the headless
    rung; a row that would have needed it carries the note
    "headless failed: needing-headless-youtube-rule" in `ladder_note`."""
    return None, url, "needing-headless-youtube-rule"


if not hasattr(ladder, "_block_youtube_requests"):
    ladder.fetch_headless = _headless_disabled

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo919_population.csv"
HUB_CSV = RESEARCH_DIR / "wo919_hub_verify.csv"

GOV_DELAY_SECONDS = 1.5
TIMEOUT_SECONDS = 120

FIELDNAMES = [
    "hub_url",
    "phase",
    "govaccess_cname",
    "ladder_access_mode",
    "ladder_rung",
    "ladder_note",
    "ladder_hit_url",
    "ladder_platform",
    "resolved_platform",
    "verdict",
    "tier",
    "meeting_found",
    "video_found",
    "captions_found",
    "meeting_url",
    "evidence",
    "candidates_checked",
    "video_candidates_json",
    "error",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_population() -> list[dict]:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def distinct_hubs(rows: list[dict]) -> list[str]:
    seen: list[str] = []
    for r in rows:
        h = r["hub_used"]
        if h and h not in seen:
            seen.append(h)
    return seen


def load_done(phase: str) -> set:
    done = set()
    if HUB_CSV.exists():
        with open(HUB_CSV, newline="", encoding="utf-8") as f:
            done = {
                r["hub_url"] for r in csv.DictReader(f) if r.get("phase") == phase
            }
    return done


def load_passive_no_meeting() -> list[str]:
    out = []
    if HUB_CSV.exists():
        with open(HUB_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("phase") == "passive" and r.get("meeting_found") != "True":
                    out.append(r["hub_url"])
    return out


def fill(out: dict, result) -> None:
    out["resolved_platform"] = result.platform or ""
    out["verdict"] = result.verdict
    out["tier"] = result.tier if result.tier is not None else ""
    out["meeting_found"] = result.meeting_found
    out["video_found"] = result.video_found
    out["captions_found"] = result.captions_found
    out["meeting_url"] = result.meeting_url or ""
    out["evidence"] = (result.evidence or "")[:500]
    out["candidates_checked"] = result.candidates_checked
    out["video_candidates_json"] = json.dumps(
        getattr(result, "video_candidates", []) or []
    )


async def passive_one(hub: str) -> dict:
    out = {k: "" for k in FIELDNAMES}
    out.update({"hub_url": hub, "phase": "passive"})
    try:
        res = await asyncio.wait_for(
            verify_hub(hub, name=None, state=None, deep_walk=True),
            timeout=TIMEOUT_SECONDS,
        )
        fill(out, res)
    except asyncio.TimeoutError:
        out["verdict"] = "timeout"
        out["error"] = f"verify_hub timeout after {TIMEOUT_SECONDS}s"
    except Exception as e:  # noqa: BLE001
        out["verdict"] = "exception"
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return out


async def ladder_one(session: aiohttp.ClientSession, hub: str) -> dict:
    out = {k: "" for k in FIELDNAMES}
    out.update({"hub_url": hub, "phase": "ladder"})
    host = urlparse(hub).netloc
    dns_info = w273.dns_lookup(host)
    cname = w283.govaccess_cname_match(dns_info)
    if cname:
        out["govaccess_cname"] = cname
        out["verdict"] = "blocked-waf-akamai"
        out["evidence"] = f"CNAME {cname}"
        return out
    try:
        lres = await asyncio.wait_for(
            ladder.run_access_ladder(session, host, "", host, hub),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as e:  # noqa: BLE001
        out["verdict"] = "ladder-exception"
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        return out
    out["ladder_access_mode"] = lres.access_mode
    out["ladder_rung"] = lres.rung_answered
    out["ladder_note"] = (lres.note or "")[:300]
    out["ladder_hit_url"] = lres.hit_url or ""
    out["ladder_platform"] = lres.platform or ""
    decorative = lres.hit_url and ladder._is_decorative_hit(lres.hit_url)
    if lres.hit_url and lres.platform and not decorative:
        try:
            res = await asyncio.wait_for(
                verify_hub(
                    lres.hit_url,
                    platform_hint=lres.platform,
                    deep_walk=True,
                ),
                timeout=TIMEOUT_SECONDS,
            )
            fill(out, res)
        except Exception as e:  # noqa: BLE001
            out["verdict"] = "exception"
            out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    else:
        out["verdict"] = "ladder-no-platform-link"
    return out


async def main_async(phase: str, limit: int) -> None:
    rows = load_population()
    hubs = distinct_hubs(rows)
    if phase == "ladder":
        hubs = [h for h in load_passive_no_meeting() if h in hubs]
    done = load_done(phase)
    todo = [h for h in hubs if h not in done]
    log(f"{len(hubs)} hubs in scope, {len(done)} done, {len(todo)} remaining")
    todo = todo[:limit] if limit else todo
    write_header = not HUB_CSV.exists()
    start = time.monotonic()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) RedTapeRecordings-PassiveVerify/1.0 "
            "(+https://redtaperecordings.com)"
        )
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        with open(HUB_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if write_header:
                w.writeheader()
                f.flush()
            for i, hub in enumerate(todo, 1):
                if phase == "passive":
                    out = await passive_one(hub)
                else:
                    out = await ladder_one(session, hub)
                w.writerow(out)
                f.flush()
                log(
                    f"[{i}/{len(todo)}] {int(time.monotonic() - start)}s {hub[:70]} -> "
                    f"{out['verdict']} tier={out['tier']} mode={out['ladder_access_mode']}"
                )
                if i < len(todo):
                    await asyncio.sleep(GOV_DELAY_SECONDS)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=["passive", "ladder"], required=True)
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()
    asyncio.run(main_async(a.phase, a.limit))


if __name__ == "__main__":
    main()
