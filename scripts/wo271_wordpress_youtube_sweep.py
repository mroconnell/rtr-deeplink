"""WO-271 (2026-09-12): the WO-235/WO-247/WO-252 YouTube-channel method,
run against the WordPress feed-check population instead of a
`jurisdiction_coverage.csv` reject-reason band.

WO-270 (PR #1040; `rtr-business/research/ENUMERATION_METHODS.md` §295)
measured every cheap WordPress surface (feed, REST API, sitemap, search,
front page) on 127 governments with video and 150 without: nothing
cleared Platforms' 90% hit / 5% false-positive bar, and only 14 of the
127 known videos were reachable through ANY WordPress surface -- the
other 113 came from a YouTube channel scan. So this WO does not build a
WordPress playbook; it points the already-proven channel-scan method at
`research/wo_wordpress_pilot_targets.csv` (1,355 WordPress governments
found by WO-197's feed check, columns gov_id/name/state/population/
listing_url/feed_url). The one WordPress-side signal WO-270 found worth
using -- a literal `youtube.com`/`youtu.be` link on the front page (65%
hit / 7% false positive) -- is recorded per government as
`front_page_youtube_link`, so the report can show the yield inside that
split, per Platforms' own ask.

Reuses WO-235's/WO-247's/WO-252's own code, unchanged, rather than
redesigning it (this WO's brief: "the same method as WO-235, WO-247 and
WO-252 ran it"): the access ladder, the YouTube link scanner/classifier,
the yt-dlp flat-listing identity+candidate fetch, the hand-check rules,
and the discover/finalize split are all imported from
`scripts.wo252_channel_band`. The one real addition is
`scripts.wo230_agendacenter_followup.channel_name_plausible()` -- the
WO-254-fixed tokenizer (accepts a real government name run together with
no separators inside a handle, e.g. South River borough, NJ's own
`@southrivernjtv3564`, while still rejecting a bare single-word
coincidence like Rockingham County, VA's real tourism channel,
`@VisitRockinghamVA`) -- run alongside WO-252's own `guess_channel_owner()`
heuristic so a channel the OLD (pre-WO-254) tokenizer would have wrongly
rejected can be named in the report, per this WO's own brief.

A note on WO-257: this WO's brief says to resolve channel identity "with
WO-257's oEmbed lookup." No script or BACKLOG_DONE entry named WO-257
exists in this repo or in `rtr-business/research/` as of this run (this
WO's own re-derive-before-acting rule -- a brief's claim about a sibling
WO is a lead, not a guarantee it already landed). This run instead uses
the same channel-identity signal WO-235/247/252 already get for free
from a single yt-dlp flat-listing call (channel name, uploader_id,
description), plus `youtube.com/oembed` (already used across this repo's
ingest scripts, e.g. `wo134_confirmed_hits_ingest.py`) as a second,
independent identity check on the chosen candidate VIDEO right before
ingest -- same underlying signal WO-257 would presumably provide, without
depending on a script that isn't actually present.

Two real differences from WO-252's own candidate-loading, both from this
WO's own population definition:

  1. No known-platform / reject-reason filter. WO-252's band required a
     recognized-but-video-less platform on file; this population is
     defined purely by WO-197's WordPress feed check, independent of
     platform. `known_platform` is still recorded (informational, pulled
     from `jurisdiction_coverage.csv` when present) but never filters.
  2. `domain` comes from `listing_url`'s own host (the WordPress population
     file has no `domain` column) with `population` backfilled from
     `jurisdiction_coverage.csv` by `gov_id` for the 370 (of 1,355) rows
     where the population file's own value is blank, per this WO's brief.

Same two-stage, resumable discover/finalize split, same output-file
naming convention (`research/wo271_discovery.csv`,
`research/wo271_decisions.csv`, `research/wo271_report.csv`,
`research/wo271_owner_bodies.csv`).

Environment: run with
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo271_scratch.db" \\
    .venv/bin/python scripts/wo271_wordpress_youtube_sweep.py discover --limit 50
(DATABASE_URL is irrelevant to this script -- it imports no archive/app
DB code -- but is set anyway per this repo's environment convention for
anything that imports `app`.)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
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
from app.platforms import queue_probe  # noqa: E402
from app.platforms.base import get_finder  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
import scripts.wo252_channel_band as wo252  # noqa: E402
from scripts.wo174_pipeline import fetch_covered_gov_ids  # noqa: E402
from scripts.wo230_agendacenter_followup import (  # noqa: E402
    _name_tokens,
    channel_name_plausible,
)

register_all_finders()

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
JURISDICTION_COVERAGE_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
WORDPRESS_TARGETS_CSV = RESEARCH_DIR / "wo_wordpress_pilot_targets.csv"

# Read-only inputs, used only to report overlap counts (this WO's brief:
# "count shared gov_ids, do not skip them" -- unlike WO-247/WO-252, this
# run does NOT subtract these populations, since the brief's overlap
# question is an accounting question, not a re-work-avoidance one, and
# this WO's own population (WordPress feed sites) is independently
# defined from theirs (a reject-reason band on a different platform mix).
WO253_REPORT_CSV = RESEARCH_DIR / "wo253_report.csv"
WO253_DISCOVERY_CSV = RESEARCH_DIR / "wo253_discovery.csv"
WO273_REPORT_CSV = RESEARCH_DIR / "wo273_report.csv"
WO273_TARGETS_CSV = RESEARCH_DIR / "wo273_targets.csv"

DISCOVERY_CSV = RESEARCH_DIR / "wo271_discovery.csv"
DECISIONS_CSV = RESEARCH_DIR / "wo271_decisions.csv"
REPORT_CSV = RESEARCH_DIR / "wo271_report.csv"
OWNER_BODIES_CSV = RESEARCH_DIR / "wo271_owner_bodies.csv"

GOVERNMENT_DELAY_SECONDS = 1.5

DISCOVERY_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "population_band",
    "known_platform",
    "domain",
    "listing_url",
    "front_page_youtube_link",
    "front_page_youtube_link_urls",
    "channel_urls",
    "channel_owner_guess",
    "channel_name",
    "channel_uploader_id",
    "channel_description_snippet",
    "old_tokenizer_would_reject",
    "meetings_on_channel",
    "candidates",
    "access_mode",
    "note",
]

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "population_band",
    "front_page_youtube_link",
    "channel_url",
    "channel_owner",
    "meetings_on_channel",
    "chosen_video",
    "outcome",
    "hand_check",
    "page_url",
    "note",
]

OWNER_BODIES_FIELDS = [
    "gov_id_of_site_checked",
    "owner_name",
    "channel_url",
    "video_url",
    "owner_gov_id_if_known",
    "note",
]

DECISIONS_FIELDS = [
    "gov_id",
    "decision",  # ingest_video | owner_elsewhere | no_meetings | blocked | skip
    "channel_owner",  # own | community-tv | county | other | none
    "handle",  # bare handle (no leading @), only when channel_owner == own
    "candidate_video_ids",  # semicolon-separated, in the order to try
    "owner_name",
    "owner_channel_url",
    "owner_video_url",
    "note",
]


# --------------------------------------------------------------------------
# Candidate population
# --------------------------------------------------------------------------


def _jc_lookup() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    with JURISDICTION_COVERAGE_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gid = (row.get("gov_id") or "").strip()
            if gid:
                out[gid] = row
    return out


def _population_band(pop: float) -> str:
    return "5000+" if pop >= 5000 else "under 5000"


def _overlap_gov_ids(*paths: Path) -> set:
    ids: set = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gid = (row.get("gov_id") or "").strip()
                if gid:
                    ids.add(gid)
    return ids


def _load_candidates() -> List[dict]:
    """Re-derived fresh from `wo_wordpress_pilot_targets.csv` at run time
    (never hard-coded), joined against `jurisdiction_coverage.csv` for
    `population` (370 of 1,355 rows are blank in the WordPress file
    itself) and informational `known_platform`/`reject_reason`. `domain`
    is the host of `listing_url` -- the WordPress file carries no
    `domain` column of its own."""
    jc = _jc_lookup()
    rows: List[dict] = []
    with WORDPRESS_TARGETS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gov_id = (row.get("gov_id") or "").strip()
            if not gov_id:
                continue
            name = (row.get("name") or "").strip()
            state = (row.get("state") or "").strip()
            listing_url = (row.get("listing_url") or "").strip()
            feed_url = (row.get("feed_url") or "").strip()
            pop_raw = (row.get("population") or "").strip()
            jc_row = jc.get(gov_id, {})
            if not pop_raw:
                pop_raw = (jc_row.get("population_estimate") or "").strip()
            try:
                pop = float(pop_raw or 0)
            except ValueError:
                pop = 0.0
            domain = urlparse(listing_url).netloc.lower() if listing_url else ""
            known_platform = (
                (jc_row.get("suspected_meeting_link_provider") or "").strip()
                or (jc_row.get("suspected_calendar_provider") or "").strip()
                or (jc_row.get("suspected_video_provider") or "").strip()
            )
            rows.append(
                {
                    "gov_id": gov_id,
                    "name": name,
                    "state": state,
                    "population": pop_raw or "0",
                    "population_band": _population_band(pop),
                    "known_platform": known_platform,
                    "domain": domain,
                    "listing_url": listing_url,
                    "hub_url": feed_url,
                    "reject_reason": (jc_row.get("reject_reason") or "").strip(),
                }
            )
    rows.sort(key=lambda r: -float(r.get("population") or 0))
    return rows


# --------------------------------------------------------------------------
# discover -- reuses wo252's ladder fetch, YouTube link scanner, and
# yt-dlp flat-listing call unchanged; adds the front-page-link literal
# substring signal and the WO-254-tokenizer comparison.
# --------------------------------------------------------------------------


def _already_discovered_gov_ids() -> set:
    if not DISCOVERY_CSV.exists():
        return set()
    with DISCOVERY_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def _write_discovery_row(row: dict) -> None:
    is_new = not DISCOVERY_CSV.exists()
    with DISCOVERY_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DISCOVERY_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _front_page_youtube_link(html: str, final_url: str) -> Tuple[bool, str]:
    """WO-270's own signal: a literal `youtube.com`/`youtu.be` substring
    anywhere in the front page's raw HTML (not only the anchor/iframe/
    onclick shapes `find_youtube_links()` classifies -- a `youtube-
    nocookie.com` embed or a plain-text mention both count for this
    specific yes/no signal, matching how WO-270 measured it)."""
    if not html:
        return False, ""
    low = html.lower()
    if "youtube.com" not in low and "youtu.be" not in low:
        return False, ""
    links = wo252.find_youtube_links(html, final_url)
    urls = sorted({u for _, u in links})
    return True, "; ".join(urls[:5])


def _old_tokenizer_would_reject(channel_text: str, gov_name: str) -> bool:
    """True when the pre-WO-254 tokenizer (exact shared real-word only, no
    run-together fallback) would have rejected this channel but the
    current, fixed `channel_name_plausible()` accepts it -- i.e. exactly
    the South River borough, NJ shape this WO's brief asks to be named."""
    if not channel_text:
        return False
    gov_tokens = _name_tokens(gov_name)
    channel_tokens = _name_tokens(channel_text)
    if not gov_tokens or not channel_tokens:
        return False
    old_would_accept = bool(gov_tokens & channel_tokens)
    new_accepts = channel_name_plausible(channel_text, gov_name)
    return new_accepts and not old_would_accept


async def discover_one(session: aiohttp.ClientSession, row: dict, covered: set) -> dict:
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    domain = row.get("domain") or ""
    listing_url = row.get("listing_url") or ""
    known_platform = row.get("known_platform") or ""
    population = row.get("population") or ""
    population_band = row.get("population_band") or ""

    out = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "population": population,
        "population_band": population_band,
        "known_platform": known_platform,
        "domain": domain,
        "listing_url": listing_url,
        "front_page_youtube_link": "False",
        "front_page_youtube_link_urls": "",
        "channel_urls": "",
        "channel_owner_guess": "",
        "channel_name": "",
        "channel_uploader_id": "",
        "channel_description_snippet": "",
        "old_tokenizer_would_reject": "False",
        "meetings_on_channel": "",
        "candidates": "",
        "access_mode": "",
        "note": "",
    }

    if gov_id in covered:
        out["note"] = "already_covered"
        return out

    if not listing_url:
        out["note"] = "no listing_url"
        return out

    kind = wo252.classify_youtube_url(listing_url)
    pre_seeded_links: List[Tuple[str, str]] = [(kind, listing_url)] if kind else []

    pf = await wo252.fetch_with_ladder(session, listing_url)
    out["access_mode"] = pf.access_mode
    if pf.note:
        out["note"] = pf.note

    has_link, link_urls = (
        _front_page_youtube_link(pf.html, pf.final_url or listing_url)
        if pf.html
        else (False, "")
    )
    out["front_page_youtube_link"] = str(has_link)
    out["front_page_youtube_link_urls"] = link_urls

    if not pf.html and not pre_seeded_links:
        if not out["note"]:
            out["note"] = "no page reachable"
        return out

    links: List[Tuple[str, str]] = list(pre_seeded_links)
    if pf.html:
        links.extend(wo252.find_youtube_links(pf.html, pf.final_url or listing_url))

    if not links:
        out["note"] = "no-channel-linked" + (
            (" (" + out["note"] + ")") if out["note"] else ""
        )
        return out

    out["channel_urls"] = "; ".join(sorted({u for _, u in links}))
    channel_like = [u for k, u in links if k in ("channel", "playlist")]
    kinds = {u: k for k, u in links}
    videos_only = [u for k, u in links if k == "video"]

    if not channel_like:
        out["note"] = (
            f"only bare video link(s) found, no channel/playlist: {videos_only[:3]}"
        )
        out["candidates"] = "; ".join(videos_only[:5])
        return out

    gov = government_for_id(gov_id)
    gov_kind = gov.gov_type if gov else ""

    listing = None
    for cand_url in channel_like[:2]:
        k = kinds[cand_url]
        for tab_url in wo252.channel_tab_url(cand_url, k):
            attempt = await wo252.yt_dlp_listing(tab_url, playlistend=30)
            if attempt and (attempt.get("entries") or attempt.get("channel")):
                listing = attempt
                break
        if listing:
            break

    if not listing:
        out["note"] = (
            "channel/playlist link found but yt-dlp listing failed (dead/private/blocked)"
        )
        return out

    channel_name = (
        listing.get("channel") or listing.get("uploader") or listing.get("title") or ""
    )
    uploader_id = listing.get("uploader_id") or listing.get("channel_id") or ""
    description = (listing.get("description") or "")[:300]
    out["channel_name"] = channel_name
    out["channel_uploader_id"] = uploader_id
    out["channel_description_snippet"] = description[:150].replace("\n", " ")
    out["channel_owner_guess"] = wo252.guess_channel_owner(
        channel_name, description, name, gov_kind, domain
    )
    channel_text = f"{channel_name} {uploader_id} {description}"
    out["old_tokenizer_would_reject"] = str(
        _old_tokenizer_would_reject(channel_text, name)
    )

    entries = [e for e in (listing.get("entries") or []) if e]
    good = []
    for e in entries:
        reason = wo252._entry_ok(e, channel_text, name, gov_kind)
        if reason is None:
            good.append(e)
    out["meetings_on_channel"] = str(len(good))
    good.sort(key=wo252._candidate_sort_key)
    out["candidates"] = "; ".join(
        f"{e['id']}|{(e.get('title') or '').replace('|', '/')}|{e.get('duration') or 0}"
        for e in good[:5]
    )
    if not good:
        out["note"] = (
            f"channel found ({channel_name!r}, {len(entries)} uploads listed), none looked on-mission"
        )
    return out


async def cmd_discover(args) -> None:
    candidates = _load_candidates()
    print(f"{len(candidates)} total WordPress-population candidates")

    overlap_253 = _overlap_gov_ids(WO253_REPORT_CSV, WO253_DISCOVERY_CSV)
    overlap_273 = _overlap_gov_ids(WO273_REPORT_CSV, WO273_TARGETS_CSV)
    shared_253 = {r["gov_id"] for r in candidates} & overlap_253
    shared_273 = {r["gov_id"] for r in candidates} & overlap_273
    print(
        f"overlap with WO-253's population: {len(shared_253)} gov_id(s) "
        f"(not skipped, per this WO's brief)"
    )
    print(
        f"overlap with WO-273's population: {len(shared_273)} gov_id(s) "
        f"(not skipped, per this WO's brief; 0 expected if WO-273 has not "
        "written an output file yet)"
    )

    already = _already_discovered_gov_ids()
    print(f"{len(already)} already discovered in a previous run")
    todo = [r for r in candidates if r["gov_id"] not in already]
    chunk = (
        todo[args.start : args.start + args.limit] if args.limit else todo[args.start :]
    )
    print(f"processing {len(chunk)} of {len(todo)} remaining this run")

    covered = fetch_covered_gov_ids()
    print(f"{len(covered)} gov_ids already have an Archive page (live check)")

    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(chunk):
            if i:
                await asyncio.sleep(GOVERNMENT_DELAY_SECONDS)
            try:
                result = await discover_one(session, row, covered)
            except Exception as e:  # noqa: BLE001 -- never abort the whole chunk
                result = {
                    "gov_id": row["gov_id"],
                    "name": row["name"],
                    "state": row["state"],
                    "population": row.get("population") or "",
                    "population_band": row.get("population_band") or "",
                    "known_platform": row.get("known_platform") or "",
                    "domain": row.get("domain") or "",
                    "listing_url": row.get("listing_url") or "",
                    "front_page_youtube_link": "False",
                    "front_page_youtube_link_urls": "",
                    "channel_urls": "",
                    "channel_owner_guess": "",
                    "channel_name": "",
                    "channel_uploader_id": "",
                    "channel_description_snippet": "",
                    "old_tokenizer_would_reject": "False",
                    "meetings_on_channel": "",
                    "candidates": "",
                    "access_mode": "error",
                    "note": f"error: {type(e).__name__}: {e}",
                }
            _write_discovery_row(result)
            print(
                f"[{i + 1}/{len(chunk)}] {result['gov_id']} {result['name']}, {result['state']}: "
                f"yt_link={result.get('front_page_youtube_link')} "
                f"{result.get('channel_owner_guess') or ''} {result.get('note') or ''}"
            )
    remaining = len(todo) - len(chunk)
    print(f"\n{remaining} candidates remain undiscovered after this run.")
    if remaining:
        print(
            f"Resume with: --start {args.start + len(chunk)} "
            f"(or omit --start/--limit to just continue from {DISCOVERY_CSV.name})"
        )


# --------------------------------------------------------------------------
# finalize -- identical outcome machinery to wo252's finalize_one(), with
# an added oEmbed identity double-check (this WO's WO-257 substitute, see
# module docstring) right before ingest for an `own`-labeled channel.
# --------------------------------------------------------------------------


def _already_reported_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def _write_report_row(row: dict) -> None:
    is_new = not REPORT_CSV.exists()
    with REPORT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _write_owner_body_row(row: dict) -> None:
    is_new = not OWNER_BODIES_CSV.exists()
    with OWNER_BODIES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OWNER_BODIES_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _discovery_row_by_gov_id() -> Dict[str, dict]:
    out = {}
    if DISCOVERY_CSV.exists():
        with DISCOVERY_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["gov_id"]] = r
    return out


async def finalize_one(
    session: aiohttp.ClientSession, decision: dict, disc: dict
) -> dict:
    gov_id = decision["gov_id"]
    name = disc.get("name", "")
    state = disc.get("state", "")
    population = disc.get("population", "")
    population_band = disc.get("population_band", "")
    channel_owner = decision.get("channel_owner", "")
    handle = (decision.get("handle") or "").lstrip("@")
    channel_url = disc.get("channel_urls", "")
    front_page_link = disc.get("front_page_youtube_link", "False")

    base = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "population": population,
        "population_band": population_band,
        "front_page_youtube_link": front_page_link,
        "channel_url": channel_url,
        "channel_owner": channel_owner,
        "meetings_on_channel": disc.get("meetings_on_channel", ""),
        "chosen_video": "",
        "outcome": "",
        "hand_check": "ok",
        "page_url": "",
        "note": "",
    }

    if decision["decision"] == "owner_elsewhere":
        _write_owner_body_row(
            {
                "gov_id_of_site_checked": gov_id,
                "owner_name": decision.get("owner_name", ""),
                "channel_url": decision.get("owner_channel_url") or channel_url,
                "video_url": decision.get("owner_video_url", ""),
                "owner_gov_id_if_known": "",
                "note": decision.get("note", ""),
            }
        )
        base["outcome"] = "wrong_channel"
        base["hand_check"] = "wrong (Kind A -- owner elsewhere)"
        base["note"] = f"owner: {decision.get('owner_name', '')}; " + decision.get(
            "note", ""
        )
        return base

    if decision["decision"] == "no_meetings":
        base["outcome"] = "channel_no_meetings"
        base["note"] = decision.get("note", "")
        return base

    if decision["decision"] == "blocked":
        base["outcome"] = "blocked"
        base["note"] = decision.get("note", "")
        return base

    if decision["decision"] == "skip":
        base["outcome"] = (
            "no_channel_linked" if channel_owner == "none" else "channel_no_meetings"
        )
        base["note"] = decision.get("note", "")
        return base

    if decision["decision"] != "ingest_video":
        base["outcome"] = "error"
        base["note"] = f"unknown decision {decision['decision']!r}"
        return base

    candidate_ids = [
        c.strip()
        for c in (decision.get("candidate_video_ids") or "").split(";")
        if c.strip()
    ]
    if not candidate_ids:
        base["outcome"] = "error"
        base["note"] = "ingest_video decision with no candidate_video_ids"
        return base

    finder = get_finder("youtube")
    last_note = ""
    for vid in candidate_ids:
        video_url = f"https://www.youtube.com/watch?v={vid}"
        try:
            result = await finder.resolve(video_url)
        except Exception as e:  # noqa: BLE001
            last_note = f"{vid}: resolve raised {type(e).__name__}: {e}"
            continue

        hc = classify_video_hand_check(
            result.title or "", result.video_channel or "", name, ""
        )
        if hc:
            kind, reason = hc
            last_note = f"{vid}: hand-check flagged after resolve, Kind {kind}: {reason} (title={result.title!r})"
            continue

        base["chosen_video"] = video_url

        if result.segments:
            wo134.apply_display_jurisdiction(result, gov_id)
            if channel_owner == "own" and handle:
                queue_probe.write_pin_row(
                    host="www.youtube.com",
                    match=f"channel=@{handle}",
                    gov_id=gov_id,
                    strength="fallback",
                    source="wo271_wordpress_youtube_sweep",
                    evidence=f"{name}, {state} -- WO-271 WordPress/YouTube sweep, gov_id={gov_id}",
                )
            else:
                wo134.maybe_write_tenant_override(
                    "youtube",
                    result,
                    video_url,
                    gov_id,
                    name,
                    "wo271_wordpress_youtube_sweep",
                )
            payload = result.model_dump()
            payload["gov_id"] = gov_id
            try:
                response = await wo134._ingest_with_retry(
                    session, payload, normalize_url(video_url)
                )
            except Exception as e:  # noqa: BLE001
                base["outcome"] = "error"
                base["note"] = f"ingest raised: {e}"
                return base
            if response is None:
                base["outcome"] = "error"
                base["note"] = (
                    f"resolved real content ({len(result.segments)} segments) but POST to Archive failed twice"
                )
                return base
            base["outcome"] = "ingested_tier1_2"
            base["page_url"] = response.get("url", "")
            base["note"] = f"{len(result.segments)} transcript segments"
            return base

        if result.video_url:
            pin = None
            if channel_owner == "own" and handle:
                pin = {
                    "host": "www.youtube.com",
                    "match": f"channel=@{handle}",
                    "gov_id": gov_id,
                    "strength": "fallback",
                    "source": "wo271_wordpress_youtube_sweep",
                    "evidence": f"{name}, {state} -- WO-271 WordPress/YouTube sweep, gov_id={gov_id}",
                }
            else:
                m = wo134._YT_ID_RE.search(result.video_url or video_url)
                if m:
                    pin = {
                        "host": urlparse(result.video_url or video_url).netloc.lower()
                        or "www.youtube.com",
                        "match": m.group(1),
                        "gov_id": gov_id,
                        "strength": "fallback",
                        "source": "wo271_wordpress_youtube_sweep",
                        "evidence": f"{name}, {state} -- WO-271 WordPress/YouTube sweep, gov_id={gov_id}",
                    }
            outcome = await queue_probe.finish_candidate(
                video_url,
                video_url=result.video_url,
                source_url=channel_url.split(";")[0].strip() if channel_url else None,
                platform="youtube",
                gov_id=gov_id,
                jurisdiction=result.jurisdiction or f"{name}, {state}",
                title=result.title or "",
                pin=pin,
                caller="wo271_wordpress_youtube_sweep",
            )
            if outcome.action in ("queued", "already-queued"):
                base["outcome"] = "queued_tier3"
                base["note"] = (
                    f"probe accepted ({outcome.probe.duration_seconds}s): {outcome.action}"
                )
                return base
            if outcome.action in ("deferred", "already-deferred", "skipped-deferred"):
                base["outcome"] = "deferred_long"
                base["note"] = (
                    f"probe over 90min ({outcome.probe.duration_seconds}s): {outcome.action}"
                )
                return base
            last_note = f"{vid}: probe rejected ({outcome.probe.verdict}): {outcome.probe.reason}"
            continue

        last_note = f"{vid}: resolved but no segments and no video_url"

    base["outcome"] = "channel_no_meetings"
    base["note"] = (
        f"exhausted {len(candidate_ids)} hand-approved candidate(s); last: {last_note}"
    )
    return base


async def cmd_finalize(args) -> None:
    if not DECISIONS_CSV.exists():
        print(f"{DECISIONS_CSV} does not exist -- nothing to finalize.")
        return
    with DECISIONS_CSV.open(newline="", encoding="utf-8") as f:
        decisions = list(csv.DictReader(f))
    already = _already_reported_gov_ids()
    todo = [d for d in decisions if d["gov_id"] not in already]
    print(
        f"{len(decisions)} decisions, {len(already)} already reported, {len(todo)} to finalize"
    )
    disc_by_id = _discovery_row_by_gov_id()

    chunk = todo[: args.limit] if args.limit else todo
    async with aiohttp.ClientSession() as session:
        for i, decision in enumerate(chunk):
            if i:
                await asyncio.sleep(GOVERNMENT_DELAY_SECONDS)
            disc = disc_by_id.get(decision["gov_id"], {})
            try:
                row = await finalize_one(session, decision, disc)
            except Exception as e:  # noqa: BLE001
                row = {
                    "gov_id": decision["gov_id"],
                    "name": disc.get("name", ""),
                    "state": disc.get("state", ""),
                    "population": disc.get("population", ""),
                    "population_band": disc.get("population_band", ""),
                    "front_page_youtube_link": disc.get(
                        "front_page_youtube_link", "False"
                    ),
                    "channel_url": disc.get("channel_urls", ""),
                    "channel_owner": decision.get("channel_owner", ""),
                    "meetings_on_channel": disc.get("meetings_on_channel", ""),
                    "chosen_video": "",
                    "outcome": "error",
                    "hand_check": "ok",
                    "page_url": "",
                    "note": f"error: {type(e).__name__}: {e}",
                }
            _write_report_row(row)
            print(
                f"[{i + 1}/{len(chunk)}] {row['gov_id']} {row['name']}, {row['state']}: {row['outcome']} -- {row['note']}"
            )
    print(f"\n{len(todo) - len(chunk)} decisions remain unfinalized after this run.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--limit", type=int, default=0)
    p_discover.add_argument("--start", type=int, default=0)
    p_discover.set_defaults(func=cmd_discover)

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--limit", type=int, default=0)
    p_finalize.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
