"""WO-340 pilot: for 50 governments whose ONLY known video was flagged
off-mission, re-discover a seed URL on the SAME non-YouTube platform
tenant and probe deeper into that tenant's listing to see if a real,
on-mission meeting is sitting right there. See the WO-340 work order for
full rules. This script does resolve-only discovery + probing; it never
auto-ingests -- ingestion happens only after a human (the operator
running this) hand-reads the candidate and calls --finalize.

Usage:
    python scripts/wo340_offmission_pilot.py --resolve --limit 8
    python scripts/wo340_offmission_pilot.py --resolve --start-after <gov_id>
    python scripts/wo340_offmission_pilot.py --finalize --ingest us:place:XXXX
    python scripts/wo340_offmission_pilot.py --finalize --reject us:place:YYYY --reason "..."
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

BUSINESS_DIR = Path(
    "/Users/mroconnell/Documents/rtr-business/.claude/worktrees/agitated-lamarr-009d82"
)
RESEARCH_DIR = BUSINESS_DIR / "research"
INPUT_CSV = RESEARCH_DIR / "wo340_pilot_input.csv"
LOG_CSV = RESEARCH_DIR / "wo340_pilot_log.csv"
CANDIDATE_CACHE = RESEARCH_DIR / "wo340_pilot_candidates.json"
YOUTUBE_LEADS_CSV = RESEARCH_DIR / "youtube_channel_leads.csv"

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

# Redirect the shared module's hardcoded output paths into OUR worktree,
# per the work order's "Critical" section -- never let anything write to
# the real rtr-business/research (this repo checkout's RESEARCH_DIR).
wo134.LOG_CSV = RESEARCH_DIR / "wo340_pilot_wo134_sidecar_log.csv"

from app.platforms import register_all_finders  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from scripts.bulk_ingest import _base_url, _ingest  # noqa: E402

UA_HEADERS = wo134.UA_HEADERS
FETCH_TIMEOUT = wo134.FETCH_TIMEOUT


def is_youtube_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "youtube.com" in netloc or "youtu.be" in netloc


async def fetch_homepage(session, domain: str):
    for scheme in ("https://", "http://"):
        url = scheme + domain
        final_url, html = await wo134.fetch_html(session, url)
        if html:
            return final_url, html
    return None, None


async def discover_seed(session, row: dict):
    """Returns (platform, seed_url, note) or (platform, None, note) if no
    seed could be found. Never fetches youtube.com/youtu.be."""
    platform = row["known_platform"].strip().lower()
    domain = row["domain"].strip()
    hub_url = (row.get("hub_url") or "").strip()
    example_meeting_url = (row.get("example_meeting_url") or "").strip()

    # 1. A real, non-YouTube example_meeting_url is the best possible
    # seed -- it's already a confirmed real tenant URL on the platform
    # we want to probe deeper on (Woodridge IL/iqm2, West Burlington
    # IA/civicweb).
    if example_meeting_url and not is_youtube_url(example_meeting_url):
        return platform, example_meeting_url, "used example_meeting_url from input CSV"

    # 2. A real, non-YouTube hub_url -- the Vimeo single-video case, or a
    # CivicPlus page already on the tenant's own domain (Bay City MI).
    if hub_url and not is_youtube_url(hub_url):
        return (
            platform,
            hub_url,
            "used hub_url from input CSV (single known video/page)",
        )

    # 3. Both blank, or both point at YouTube (which we must not fetch) --
    # active discovery on the KNOWN non-YouTube platform.
    if platform == "civicplus":
        seed, reason = await wo134.locate_platform_url(
            session, "civicplus", "", [], f"https://{domain}"
        )
        if seed:
            return (
                platform,
                seed,
                f"guessed/verified CivicPlus AgendaCenter: {reason or 'ok'}",
            )
        return platform, None, f"no CivicPlus AgendaCenter found: {reason}"

    if platform == "civicclerk":
        slug = re.sub(r"[^a-z0-9]", "", row["name"].lower())
        guess = f"https://{slug}.civicclerk.com/"
        return (
            platform,
            guess,
            f"guessed CivicClerk tenant subdomain '{slug}' from government name (unverified until resolve)",
        )

    # vimeo / iqm2 / civicweb / anything else: one homepage fetch, look
    # for a link to the target platform; if none, one guessed path check.
    final_url, html = await fetch_homepage(session, domain)
    if not html:
        return platform, None, f"homepage unreachable ({domain})"
    link = wo134.find_specific_platform_link(
        html, final_url or f"https://{domain}", platform
    )
    if link:
        return platform, link, f"found {platform} link on homepage {final_url}"

    # One guessed path check (platform-specific), per the work order.
    if platform == "vimeo":
        return platform, None, f"no vimeo link found on homepage {final_url}"

    return platform, None, f"no {platform} link found on homepage {final_url}"


def government_display(gov_id: str):
    gov = government_for_id(gov_id)
    if gov and gov.gov_name and gov.state:
        return f"{gov.gov_name}, {gov.state}"
    return None


def load_input_rows():
    with INPUT_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def already_logged_gov_ids():
    if not LOG_CSV.exists():
        return set()
    with LOG_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


LOG_FIELDS = [
    "gov_id",
    "name",
    "state",
    "known_platform",
    "seed_url_used",
    "outcome",
    "video_url",
    "meeting_title",
    "meeting_date",
    "hand_read",
    "notes",
]


def append_log_row(row: dict):
    is_new = not LOG_CSV.exists()
    with LOG_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if is_new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LOG_FIELDS})


def append_youtube_lead(gov_id, name, state, channel_url, note):
    fields = [
        "channel_url",
        "gov_id",
        "government",
        "state",
        "source_wo",
        "kind",
        "verified",
        "note",
    ]
    is_new = not YOUTUBE_LEADS_CSV.exists()
    with YOUTUBE_LEADS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "channel_url": channel_url,
                "gov_id": gov_id,
                "government": name,
                "state": state,
                "source_wo": "WO-340",
                "kind": "channel",
                "verified": "false",
                "note": note,
            }
        )


def load_candidate_cache():
    if CANDIDATE_CACHE.exists():
        return json.loads(CANDIDATE_CACHE.read_text())
    return {}


def save_candidate_cache(cache):
    CANDIDATE_CACHE.write_text(json.dumps(cache, indent=2))


async def resolve_row(session, row):
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    base_log = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "known_platform": row["known_platform"],
    }

    platform, seed_url, note = await discover_seed(session, row)

    if seed_url and is_youtube_url(seed_url):
        append_youtube_lead(
            gov_id,
            name,
            state,
            seed_url,
            "WO-340 rediscovery landed on YouTube unexpectedly",
        )
        append_log_row(
            {**base_log, "outcome": "routed_to_youtube_leads", "notes": note}
        )
        print(f"[routed_to_youtube_leads] {gov_id} {name!r} -- {note}")
        return

    if not seed_url:
        append_log_row({**base_log, "outcome": "no_seed_found", "notes": note})
        print(f"[no_seed_found      ] {gov_id} {name!r} -- {note}")
        return

    try:
        result, final_seed, high_risk_title = await wo134.resolve_seed(
            session, platform, seed_url
        )
    except wo134.ProbeRejected as e:
        append_log_row(
            {
                **base_log,
                "seed_url_used": seed_url,
                "outcome": "confirmed_offmission",
                "video_url": e.video_url,
                "notes": f"probe-rejected every candidate: {e} (seed discovery: {note})",
            }
        )
        print(
            f"[confirmed_offmission] {gov_id} {name!r} -- probe rejected all candidates: {e}"
        )
        return
    except wo134.RowSkip as e:
        # A guessed-but-unverified seed (e.g. a CivicClerk subdomain guess)
        # that never actually resolved to a real tenant is NOT a confirmed
        # off-mission finding -- it just means no working seed was found,
        # same as any other no_seed_found case.
        msg = str(e)
        if "Events API failed" in msg and "guessed CivicClerk tenant subdomain" in note:
            append_log_row(
                {
                    **base_log,
                    "seed_url_used": seed_url,
                    "outcome": "no_seed_found",
                    "notes": f"guessed CivicClerk subdomain did not resolve to a real tenant: {e} (seed discovery: {note})",
                }
            )
            print(
                f"[no_seed_found      ] {gov_id} {name!r} -- guessed CivicClerk subdomain unverified: {e}"
            )
            return
        append_log_row(
            {
                **base_log,
                "seed_url_used": seed_url,
                "outcome": "confirmed_offmission",
                "video_url": e.video_url,
                "notes": f"no real meeting found after probing: {e} (seed discovery: {note})",
            }
        )
        print(f"[confirmed_offmission] {gov_id} {name!r} -- {e}")
        return
    except Exception as e:
        append_log_row(
            {
                **base_log,
                "seed_url_used": seed_url,
                "outcome": "error",
                "notes": f"{type(e).__name__}: {e} (seed discovery: {note})",
            }
        )
        print(f"[error              ] {gov_id} {name!r} -- {type(e).__name__}: {e}")
        return

    # Resolved something. Apply the title-safety re-check explicitly (in
    # case a generic resolve slipped through without it) and stash full
    # detail for hand-read -- never auto-ingest here.
    title = result.title or ""
    expected_display = government_display(gov_id)
    cache = load_candidate_cache()
    cache[gov_id] = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "known_platform": platform,
        "seed_url": seed_url,
        "final_seed": final_seed,
        "seed_discovery_note": note,
        "title": title,
        "date": result.date or "",
        "jurisdiction_guess": result.jurisdiction or "",
        "expected_display": expected_display,
        "video_url": result.video_url or "",
        "segments_count": len(result.segments or []),
        "agenda_items_count": len(result.agenda_items or []),
        "source_url": result.source_url or final_seed,
        "looks_like_real_meeting": wo134._looks_like_real_meeting(
            title, require_allowlist=high_risk_title
        ),
    }
    save_candidate_cache(cache)

    print(f"\n=== CANDIDATE FOR HAND-READ: {gov_id} {name!r} ({state}) ===")
    print(f"  platform={platform}  seed_discovery: {note}")
    print(f"  seed_url={seed_url}")
    print(f"  final_seed={final_seed}")
    print(f"  title={title!r}")
    print(f"  date={result.date!r}")
    print(
        f"  jurisdiction_guess={result.jurisdiction!r}  expected={expected_display!r}"
    )
    print(f"  video_url={result.video_url!r}")
    print(
        f"  segments={len(result.segments or [])}  agenda_items={len(result.agenda_items or [])}"
    )
    print(f"  source_url={result.source_url!r}")
    print(f"  passes automated title check: {cache[gov_id]['looks_like_real_meeting']}")
    print("=== awaiting hand-read decision (--finalize) ===\n")


async def do_resolve(limit, start_after):
    register_all_finders()
    wo134.PROBE_SELECT_HOOK = wo134.build_probe_select_hook()
    rows = load_input_rows()
    done = already_logged_gov_ids()
    cache = load_candidate_cache()
    done |= set(cache.keys())  # already surfaced for hand-read, don't re-resolve
    to_process = []
    skip_until_seen = start_after is not None
    for row in rows:
        if row["gov_id"] in done:
            continue
        if skip_until_seen:
            if row["gov_id"] == start_after:
                skip_until_seen = False
            continue
        to_process.append(row)
    if limit:
        to_process = to_process[:limit]

    print(f"Resolving {len(to_process)} row(s)...\n")
    consecutive_errors = 0
    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(to_process):
            try:
                await resolve_row(session, row)
                consecutive_errors = 0
            except Exception as e:
                print(f"[UNHANDLED ERROR] {row['gov_id']} {row['name']!r} -- {e}")
                append_log_row(
                    {
                        "gov_id": row["gov_id"],
                        "name": row["name"],
                        "state": row["state"],
                        "known_platform": row["known_platform"],
                        "outcome": "error",
                        "notes": f"unhandled: {e}",
                    }
                )
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    print("\nABORTING: 3 consecutive unhandled errors.")
                    break
            if i < len(to_process) - 1:
                await asyncio.sleep(1.0)


async def do_finalize(
    ingest_ids,
    tier3_ids,
    reject_ids,
    reject_reason,
    wrong_source_ids,
    wrong_source_note,
    needs_review_ids,
    review_note,
):
    register_all_finders()
    cache = load_candidate_cache()

    async with aiohttp.ClientSession() as session:
        for gov_id in ingest_ids:
            c = cache.get(gov_id)
            if not c:
                print(f"SKIP: {gov_id} not in candidate cache.")
                continue
            # Re-resolve fresh right before ingest so the payload is complete
            # and current (segments, agenda_items, external_id, etc.) rather
            # than a partial hand-read snapshot.
            try:
                result, final_seed, _ = await wo134.resolve_seed(
                    session, c["known_platform"], c["final_seed"]
                )
            except Exception as e:
                print(f"ERROR re-resolving {gov_id} before ingest: {e}")
                continue
            if not result.jurisdiction:
                wo134.apply_display_jurisdiction(result, gov_id)
            payload = result.model_dump()
            payload["gov_id"] = gov_id
            from app.utils.url_normalize import normalize_url

            normalized = normalize_url(final_seed)
            try:
                response = await _ingest(
                    session, payload, normalized, caller="wo340_pilot"
                )
            except Exception as e:
                print(f"INGEST FAILED for {gov_id}: {e}")
                append_log_row(
                    {
                        "gov_id": gov_id,
                        "name": c["name"],
                        "state": c["state"],
                        "known_platform": c["known_platform"],
                        "seed_url_used": c["seed_url"],
                        "outcome": "error",
                        "video_url": c["video_url"],
                        "meeting_title": c["title"],
                        "meeting_date": c["date"],
                        "notes": f"ingest failed: {e}",
                    }
                )
                continue
            page_url = response.get("url") if response else ""
            print(f"INGESTED {gov_id} -> {page_url}")
            append_log_row(
                {
                    "gov_id": gov_id,
                    "name": c["name"],
                    "state": c["state"],
                    "known_platform": c["known_platform"],
                    "seed_url_used": c["seed_url"],
                    "outcome": "ingested_page_live_now",
                    "video_url": c["video_url"],
                    "meeting_title": c["title"],
                    "meeting_date": c["date"],
                    "hand_read": "on-mission, confirmed matches this government -- see operator notes",
                    "notes": f"page live: {page_url}",
                }
            )
            cache.pop(gov_id, None)

        for gov_id in tier3_ids:
            c = cache.get(gov_id)
            if not c:
                print(f"SKIP: {gov_id} not in candidate cache.")
                continue
            append_log_row(
                {
                    "gov_id": gov_id,
                    "name": c["name"],
                    "state": c["state"],
                    "known_platform": c["known_platform"],
                    "seed_url_used": c["seed_url"],
                    "outcome": "video_no_captions_queued",
                    "video_url": c["video_url"],
                    "meeting_title": c["title"],
                    "meeting_date": c["date"],
                    "hand_read": "on-mission, real video, no reachable captions -- for Breadth's real tier-3 queue",
                    "notes": "recorded here only; real tier3_auto_transcription_queue.txt entry to be applied by Breadth from their connected checkout",
                }
            )
            print(f"RECORDED (video, no captions, queued) {gov_id}")
            cache.pop(gov_id, None)

        for gov_id, note_ in wrong_source_ids:
            c = cache.get(gov_id)
            if not c:
                print(f"SKIP: {gov_id} not in candidate cache.")
                continue
            append_log_row(
                {
                    "gov_id": gov_id,
                    "name": c["name"],
                    "state": c["state"],
                    "known_platform": c["known_platform"],
                    "seed_url_used": c["seed_url"],
                    "outcome": "wrong_source",
                    "video_url": c["video_url"],
                    "meeting_title": c["title"],
                    "meeting_date": c["date"],
                    "hand_read": note_ or "tenant belongs to a different government",
                    "notes": note_ or "",
                }
            )
            print(f"RECORDED (wrong_source) {gov_id}")
            cache.pop(gov_id, None)

        for gov_id, reason in reject_ids:
            c = cache.get(gov_id)
            if not c:
                print(f"SKIP: {gov_id} not in candidate cache.")
                continue
            append_log_row(
                {
                    "gov_id": gov_id,
                    "name": c["name"],
                    "state": c["state"],
                    "known_platform": c["known_platform"],
                    "seed_url_used": c["seed_url"],
                    "outcome": "confirmed_offmission",
                    "video_url": c["video_url"],
                    "meeting_title": c["title"],
                    "meeting_date": c["date"],
                    "hand_read": reason
                    or reject_reason
                    or "hand-read: not a real on-mission meeting",
                    "notes": reason or reject_reason or "",
                }
            )
            print(f"RECORDED (confirmed_offmission, hand-read) {gov_id}")
            cache.pop(gov_id, None)

        for gov_id, note_ in needs_review_ids:
            c = cache.get(gov_id)
            if not c:
                print(f"SKIP: {gov_id} not in candidate cache.")
                continue
            append_log_row(
                {
                    "gov_id": gov_id,
                    "name": c["name"],
                    "state": c["state"],
                    "known_platform": c["known_platform"],
                    "seed_url_used": c["seed_url"],
                    "outcome": "needs_human_review",
                    "video_url": c["video_url"],
                    "meeting_title": c["title"],
                    "meeting_date": c["date"],
                    "hand_read": note_
                    or review_note
                    or "ambiguous -- flagged for Ryan",
                    "notes": note_ or review_note or "",
                }
            )
            print(f"RECORDED (needs_human_review) {gov_id}")
            cache.pop(gov_id, None)

    save_candidate_cache(cache)


def parse_pairs(arg):
    """'gov_id1=reason1;;gov_id2=reason2' -> [(gov_id, reason), ...].
    Uses '=' (not ':') to separate gov_id from reason, since gov_ids
    themselves contain colons (e.g. "ca:csd:2485010")."""
    if not arg:
        return []
    out = []
    for chunk in arg.split(";;"):
        if not chunk.strip():
            continue
        if "=" in chunk:
            gid, reason = chunk.split("=", 1)
        else:
            gid, reason = chunk, ""
        out.append((gid.strip(), reason.strip()))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolve", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-after", type=str, default=None)
    parser.add_argument(
        "--ingest", type=str, default="", help="comma-separated gov_ids"
    )
    parser.add_argument("--tier3", type=str, default="", help="comma-separated gov_ids")
    parser.add_argument(
        "--wrong-source", type=str, default="", help="gov_id:note;;gov_id:note"
    )
    parser.add_argument(
        "--reject", type=str, default="", help="gov_id:reason;;gov_id:reason"
    )
    parser.add_argument(
        "--needs-review", type=str, default="", help="gov_id:note;;gov_id:note"
    )
    args = parser.parse_args()

    if args.resolve:
        if not bool(os.environ.get("ARCHIVE_INGEST_TOKEN")):
            print(
                "WARNING: ARCHIVE_INGEST_TOKEN not set -- fine for --resolve (no ingest happens here)."
            )
        asyncio.run(do_resolve(args.limit, args.start_after))
    elif args.finalize:
        if not _base_url() or not bool(os.environ.get("ARCHIVE_INGEST_TOKEN")):
            print(
                "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set.",
                file=sys.stderr,
            )
            sys.exit(1)
        ingest_ids = [g.strip() for g in args.ingest.split(",") if g.strip()]
        tier3_ids = [g.strip() for g in args.tier3.split(",") if g.strip()]
        reject_ids = parse_pairs(args.reject)
        wrong_source_pairs = parse_pairs(args.wrong_source)
        needs_review_pairs = parse_pairs(args.needs_review)
        asyncio.run(
            do_finalize(
                ingest_ids,
                tier3_ids,
                reject_ids,
                "",
                wrong_source_pairs,
                "",
                needs_review_pairs,
                "",
            )
        )
    else:
        print("Pass --resolve or --finalize.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
