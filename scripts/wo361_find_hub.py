#!/usr/bin/env python3
"""WO-361 (2026-09-13): find the real meeting hub FIRST for the WO-355
homepage-only off-mission governments, then only run the video walk on
a confirmed hub -- never on a bare homepage.

Why: WO-355 re-verified 518 non-YouTube off-mission governments and
found 62 of 64 "videos" were the homepage's own welcome/promo clip,
because `verify_hub()` was pointed straight at a bare homepage for 476
of the 518 rows and its own single-fetch fallback has no access-ladder
climbing (no browser-headers retry on a 403, no headless render, no
sitemap/robots discovery). Ryan: "we need to find their platform page
by doing the passive pipe and ladder access and then we will have
videos that might actually be on mission."

Per government, in order:
  1. govAccess/Akamai CNAME check (`scripts.wo283_recon.govaccess_cname_
     match` via `scripts.wo282_recon.dns_lookup`) -- if the www or apex
     CNAME ends in granicusgovaccess.net or opencities.com, this
     machine's IP is WAF-blocked there; record `blocked-waf-akamai` with
     the CNAME as evidence and skip outright (no fetch attempted).
  2. Access ladder (`scripts.wo147_access_ladder_sweep.run_access_ladder`):
     plain HTTP -> browser headers (after a 403/dropped connection,
     never after a 404) -> one hop into agenda/calendar/council-hinted
     links (ranked, WO-228 weights) -> headless only when a real page
     was reached with no visible hop links -> stop at a human-
     verification challenge, never past it.
  3a. If the ladder found a real platform link (`hit_url`/`platform`
      via `find_platform_link()`, on the homepage, a hop page, or a
      calendar entry) -- that is a confirmed, non-homepage hub. Run
      `verify_hub(hit_url, platform_hint=platform, deep_walk=True)`
      (up to 15 listed meetings, up to 3 with video) for the tier.
  3b. Else, if the ladder reached real HTML with no vendor link, try
      `_probe_first_party_agenda_pages()` (the guessable
      /agendacenter, /agendas-minutes, /government/agendas-minutes
      paths, the home page's own body, and one hop deeper) against the
      page the LADDER actually reached (which may be a headless-
      rendered or browser-headers page plain HTTP never saw) -- this
      already returns a full tier verdict when it finds real content.
  3c. Else -- dead/challenge/blocked/no hop links/no first-party content
      -- no hub found; record the honest reason and the candidates
      tried. The video walk never runs on a bare homepage.

Never fetches a youtube.com/youtu.be URL (verify_hub's own guard).
Never downloads a media file. Politeness: one government at a time
(GOV_DELAY_SECONDS between governments), 2s between requests to the
same host (built into `run_access_ladder`).

Writes `research/wo361_verify.csv`, resumable (a gov_id already present
is skipped). Each government is wrapped in a hard per-government
timeout so one slow/hanging host can't stall a chunk.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo361_find_hub_scratch.db" \\
        .venv/bin/python scripts/wo361_find_hub.py --limit 40
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

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import (  # noqa: E402
    verify_hub,
    _probe_first_party_agenda_pages,
)

import scripts.wo147_access_ladder_sweep as ladder  # noqa: E402
import scripts.wo282_recon as w273  # noqa: E402
import scripts.wo283_recon as w283  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo361_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo361_verify.csv"

GOV_DELAY_SECONDS = 1.5
PER_GOVERNMENT_TIMEOUT_SECONDS = 60

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "homepage_url",
    "govaccess_blocked",
    "govaccess_cname",
    "ladder_access_mode",
    "ladder_rung",
    "ladder_note",
    "hub_url",
    "hub_source",
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
    "no_hub_reason",
    "error",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_population() -> list[dict]:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_done_gov_ids() -> set:
    done = set()
    if VERIFY_CSV.exists():
        with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
            done = {row["gov_id"] for row in csv.DictReader(f) if row.get("gov_id")}
    return done


def _blank_out() -> dict:
    return {k: "" for k in FIELDNAMES}


# Same decorative-embed signature WO-355's hand-read pass confirmed live
# (Bowling Green KY "Video Ad", Garfield NJ's sidebar hero embed, and now
# reproduced here for Mirabel QC and Garfield NJ again): a vendor link
# `find_platform_link()` scans up off a bare homepage is not necessarily a
# real meeting hub -- it can be the SAME decorative/promotional embed the
# homepage carries as a hero background video. A raw single-video player
# URL with these markers is never treated as a confirmed hub; the ladder
# falls through to the first-party agenda probe / no-hub path instead.
#
# WO-904 (2026-09-19): relocated into scripts/wo147_access_ladder_sweep.py
# (as `_is_decorative_hit`) so `run_access_ladder()` ITSELF can also use
# it -- before this, only THIS caller checked, so `run_access_ladder()`
# would already have returned (and stopped) on a decorative hit before
# this check ever ran; every other sweep calling `run_access_ladder()`
# directly had no protection at all. Imported here, not reimplemented,
# per CLAUDE.md's "reuse, don't reinvent" rule -- this module's own
# `decorative_hit` check below now mostly catches a decorative hit
# surfacing from a hop link or calendar entry (the two rungs
# `run_access_ladder()` deliberately does NOT decorative-filter, since a
# hop/calendar-entry page is a different, agenda/minutes-hinted page,
# not the homepage's own body -- see that module's own comment).
_is_decorative_hit = ladder._is_decorative_hit


def _no_hub_reason_for_ladder(result: "ladder.LadderResult") -> str:
    mode = result.access_mode
    if mode == "dead":
        return "dns-unresolvable"
    if mode == "timeout":
        return "timeout"
    if mode == "challenge":
        return "cloudflare-challenge-blocked"
    if mode == "blocked-plain-http":
        return "blocked-plain-http"
    if mode == "blocked-browser-headers":
        return "blocked-browser-headers"
    return "no-platform-link-found"


async def find_hub_and_verify(session: aiohttp.ClientSession, row: dict) -> dict:
    gov_id = row["gov_id"]
    name = row.get("name", "")
    state = row.get("state", "")
    domain = row.get("domain", "")
    homepage_url = row.get("homepage_url") or f"https://{domain}"

    out = _blank_out()
    out.update(
        {
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "population": row.get("population", ""),
            "domain": domain,
            "homepage_url": homepage_url,
            "govaccess_blocked": False,
            "meeting_found": False,
            "video_found": False,
            "captions_found": False,
            "candidates_checked": 0,
            "video_candidates_json": "[]",
        }
    )

    if not domain:
        out["no_hub_reason"] = "no-domain"
        return out

    # Step 1: govAccess/Akamai CNAME gate.
    dns_info = w273.dns_lookup(domain)
    cname = w283.govaccess_cname_match(dns_info)
    if cname:
        out["govaccess_blocked"] = True
        out["govaccess_cname"] = cname
        out["no_hub_reason"] = "blocked-waf-akamai"
        out["evidence"] = f"CNAME {cname} (govAccess/OpenCities WAF block)"
        return out

    # Step 2: access ladder.
    try:
        lresult = await ladder.run_access_ladder(session, name, state, domain, "")
    except Exception as e:  # noqa: BLE001
        out["error"] = f"ladder {type(e).__name__}: {str(e)[:300]}"
        out["no_hub_reason"] = "unclassified_fetch_failure"
        return out

    out["ladder_access_mode"] = lresult.access_mode
    out["ladder_rung"] = lresult.rung_answered
    out["ladder_note"] = (lresult.note or "")[:300]

    # Step 3a: a real platform link was found by the ladder -- unless it
    # is a decorative/promotional embed on the homepage itself (the
    # WO-355 false-positive class; see _is_decorative_hit's docstring).
    decorative_hit = lresult.hit_url and _is_decorative_hit(lresult.hit_url)
    if lresult.hit_url and lresult.platform and not decorative_hit:
        out["hub_url"] = lresult.hit_url
        out["hub_source"] = "ladder_hit"
        try:
            vresult = await asyncio.wait_for(
                verify_hub(
                    lresult.hit_url,
                    platform_hint=lresult.platform,
                    name=name,
                    state=state,
                    deep_walk=True,
                ),
                timeout=PER_GOVERNMENT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            out["error"] = f"verify_hub timeout after {PER_GOVERNMENT_TIMEOUT_SECONDS}s"
            out["verdict"] = "timeout"
            return out
        except Exception as e:  # noqa: BLE001
            out["error"] = f"verify_hub {type(e).__name__}: {str(e)[:300]}"
            out["verdict"] = "exception"
            return out
        _fill_verify_result(out, vresult)
        return out

    # Step 3b: real HTML reached, no vendor link -- try first-party
    # agenda probes against the page the LADDER actually reached (not
    # necessarily the same bytes plain HTTP would have seen).
    if lresult.final_html:
        try:
            probed = await asyncio.wait_for(
                _probe_first_party_agenda_pages(
                    lresult.final_url or homepage_url,
                    home_html=lresult.final_html,
                    home_final_url=lresult.final_url,
                    name=name,
                    state=state,
                ),
                timeout=PER_GOVERNMENT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            out["error"] = (
                f"first-party probe timeout after {PER_GOVERNMENT_TIMEOUT_SECONDS}s"
            )
            out["verdict"] = "timeout"
            return out
        except Exception as e:  # noqa: BLE001
            out["error"] = f"first-party probe {type(e).__name__}: {str(e)[:300]}"
            out["verdict"] = "exception"
            return out
        if probed is not None:
            out["hub_url"] = lresult.final_url or homepage_url
            out["hub_source"] = "first_party_probe"
            _fill_verify_result(out, probed)
            return out

    # Step 3c: nothing found.
    out["no_hub_reason"] = _no_hub_reason_for_ladder(lresult)
    if decorative_hit:
        out["ladder_note"] = (
            out["ladder_note"]
            + f" | rejected decorative homepage embed as a false hub: {lresult.hit_url[:200]}"
        )[:500]
    return out


def _fill_verify_result(out: dict, result) -> None:
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


async def main_async(limit: int) -> None:
    population = load_population()
    done = load_done_gov_ids()
    remaining = [row for row in population if row["gov_id"] not in done]
    log(
        f"{len(population)} in population, {len(done)} already processed, "
        f"{len(remaining)} remaining"
    )
    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} sequentially (one government at a time)")

    write_header = not VERIFY_CSV.exists()
    start = time.monotonic()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) RedTapeRecordings-PassiveVerify/1.0 "
            "(+https://redtaperecordings.com)"
        )
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        with open(VERIFY_CSV, "a", newline="", encoding="utf-8") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
            if write_header:
                writer.writeheader()
                out_f.flush()

            for i, row in enumerate(to_process, 1):
                try:
                    result = await asyncio.wait_for(
                        find_hub_and_verify(session, row),
                        timeout=PER_GOVERNMENT_TIMEOUT_SECONDS + 15,
                    )
                except asyncio.TimeoutError:
                    result = _blank_out()
                    result.update(
                        {
                            "gov_id": row["gov_id"],
                            "name": row.get("name", ""),
                            "state": row.get("state", ""),
                            "population": row.get("population", ""),
                            "domain": row.get("domain", ""),
                            "error": "hard-timeout",
                            "no_hub_reason": "timeout",
                        }
                    )
                writer.writerow(result)
                out_f.flush()
                elapsed = time.monotonic() - start
                rate = i / elapsed * 60 if elapsed > 0 else 0
                log(
                    f"[{i}/{len(to_process)}] elapsed={elapsed:.0f}s rate={rate:.1f}/min "
                    f"{row['gov_id']} ({row.get('name', '')} {row.get('state', '')}) "
                    f"-> hub={result.get('hub_source') or result.get('no_hub_reason')} "
                    f"tier={result.get('tier')}"
                )
                if i < len(to_process):
                    await asyncio.sleep(GOV_DELAY_SECONDS)

    log(
        f"chunk done: {len(to_process)} processed, "
        f"{len(remaining) - len(to_process)} remaining"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main_async(args.limit))


if __name__ == "__main__":
    main()
