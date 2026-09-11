"""WO-148 (2026-09-10): headless/access-ladder sweep of the 1,132 smaller
governments WO-133's headless pass never reached (population >= 5,000,
non-county, `no-platform-link-found`, in `wo133_headless_input.csv` but
outside its cleared 25,000+ subset -- candidate list 4 in
`docs/BREADTH_SWEEP_BRIEF.md`, built as
`~/Documents/rtr-business/research/wo148_candidates.csv`).

One government at a time. Per government:

  1. Plain HTTP, honest headers (home page + one hop of meeting/agenda/
     council/video links). "Works" means a platform link or a listing
     was found, not merely a 200.
  2. Browser headers, once, only after a 403 or a dropped connection at
     rung 1 -- never after a plain 404.
  3. Headless (Playwright), only for a host that answered rung 1 or 2
     with a page that has no visible meeting link -- reuses
     `wo133_headless_recheck_scan.py`'s `scan_one()` verbatim (imported,
     not re-implemented) for the actual render/hop2/platform-detect
     logic.
  4. A human-verification interstitial at any rung stops the ladder for
     that host immediately: `cloudflare-challenge-blocked`, never
     retried.

Once a platform link is found: platform API first, via rtr-discovery's
own enumerator against a THROWAWAY ledger copy
(`/tmp/wo148_ledger.db`, copied from `~/Documents/rtr-discovery/
ledger.db` once -- the real ledger is never opened for writing). The
row's `gov_id` is seeded into the tenant (`ledger.set_tenant_gov_id`)
before enumerating, thorough mode, up to `MAX_CANDIDATES_TRIED` newest
candidates resolved (oldest-to-give-up-on last), first one with a real
video signal wins. For a platform rtr-discovery cannot enumerate (no
adapter in `discovery/enumerators/`), falls back to
`wo134_confirmed_hits_ingest.py`'s own seed-resolution
(`locate_platform_url` + `resolve_seed`) -- the SAME functions that
script uses, imported, not copied.

Ryan's ingest rule, enforced here directly: only a meeting WITH VIDEO
becomes a page. Tier 1/2 (captions reachable) POST to
`/internal/ingest` for real, right now. Tier 3 (real video, no reachable
captions) is NOT appended to `scripts/tier3_auto_transcription_queue.txt`
directly -- every tier-3 candidate found this run is written first to
`~/Documents/rtr-business/research/wo148_tier3_pending.csv` and only
moved into the real queue (with a probe: reject a dead link or an
under-60-second clip, prefer over nine minutes, prefer recent/shorter
where a government offers several) once WO-144's `probe_queue_entry`
helper is confirmed on `origin/main` -- see this repo's WO-148 report
for whether that happened this run. Agenda-only (`no-video-found`) is
never ingested, never queued.

YouTube: this Mac's address was blocked for YouTube caption fetches on
2026-09-09 (`docs/investigations/youtube_429_block.md`). The first
YouTube-platform resolve that raises the documented block signature
(HTTP 429 on the caption fetch, or yt-dlp's "Sign in to confirm you're
not a bot" on an audio path) sets a module-level flag; every YouTube
resolve after that in this run is skipped and the hit is recorded
straight to `wo148_tier3_pending.csv` instead (video presumed
reachable, captions presumed not, per the doc's own framing) -- never
re-attempted this run.

Usage (real requests against real government hosts -- see the ladder
above and CLAUDE.md's "politely" bullet):

    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo148_headless_sweep.py --pilot 30
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo148_headless_sweep.py

Resumable: `~/Documents/rtr-business/research/wo148_report.csv` is
flushed one row per government; a gov_id already in it is skipped on
re-run. Stops after 6 consecutive real errors (a content outcome --
no-video-found, no-platform-link-found, blocked, challenge -- does not
count; a request-level exception or a failed-twice Archive POST does).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib.util
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/wo148_scratch.db")

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()  # walks up from cwd -- picks up the shared checkout's ARCHIVE_* per CLAUDE.md

from app.platforms import register_all_finders  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
REAL_LEDGER = DISCOVERY_ROOT / "ledger.db"
SCRATCH_LEDGER = Path("/tmp/wo148_ledger.db")

CANDIDATES_CSV = RESEARCH_DIR / "wo148_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo148_report.csv"
CONFIRMED_HITS_CSV = RESEARCH_DIR / "wo148_confirmed_hits.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo148_discovery_seeds.csv"
HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo148_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo148_tier3_pending.csv"

GOV_DELAY_SECONDS = 1.5
HOST_DELAY_SECONDS = 2.0
MAX_CANDIDATES_TRIED = 6
MAX_CONSECUTIVE_ERRORS = 6

# --- load wo133/wo134/wo141 as importable modules (none of the three is
# a package; they were written as standalone scripts, per this repo's
# "reuse, do not rewrite" instruction) ---


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wo133 = _load_module(
    "wo133_headless_recheck_scan", RESEARCH_DIR / "wo133_headless_recheck_scan.py"
)
wo141 = _load_module(
    "wo141_access_ladder_pilot", RESEARCH_DIR / "wo141_access_ladder_pilot.py"
)
wo134 = _load_module(
    "wo134_confirmed_hits_ingest",
    REPO_ROOT / "scripts" / "wo134_confirmed_hits_ingest.py",
)

# wo134's own process_row() appends straight to the real tier-3 queue
# file and writes tenant_overrides.csv pins unconditionally. WO-148
# defers both for a tier-3 hit (see module docstring), so this script
# does NOT call process_row() at all -- main() below re-does just its
# ingest/tier-3 branch inline, reusing wo134's helper functions
# (locate_platform_url, resolve_seed, _looks_like_real_meeting,
# _dedup_key, maybe_write_tenant_override, _ingest_with_retry, ...)
# individually instead.

detect_platforms = wo133.detect_platforms
HOP1_HINT_WORDS = wo133.HOP1_HINT_WORDS
HONEST_HEADERS = wo141.HONEST_HEADERS
BROWSER_HEADERS = wo141.BROWSER_HEADERS
classify_body = wo141.classify_body

DISCOVERY_ENUMERABLE = {
    "granicus",
    "legistar",
    "civicplus",
    "civicclerk",
    "civicweb",
    "escribe",
    "iqm2",
    "swagit",
    "cablecast",
    "municode_meetings",
    "primegov",
}

YOUTUBE_BLOCKED = False
YOUTUBE_BLOCK_SIGNATURE = ""


def is_youtube_block_signature(exc_text: str) -> bool:
    low = (exc_text or "").lower()
    return "429" in low or "sign in to confirm" in low or "not a bot" in low


# --------------------------------------------------------------------
# Rung 1/2: plain HTTP / browser headers, home page + one hop
# --------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _extract_hop_links(html: str, base_url: str) -> list:
    # Cheap regex-free approach reusing wo133's hint-word matching via a
    # tiny hand-rolled anchor scan (this rung is plain aiohttp text, no
    # DOM) -- good enough because we only need candidate URLs to fetch,
    # not a full parse; detect_platforms() re-scans full hop2 HTML anyway.
    import re

    links = []
    seen = set()
    for m in re.finditer(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S
    ):
        href, text = m.group(1), re.sub("<[^>]+>", "", m.group(2))
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        hay = f"{text} {href}".lower()
        if any(w in hay for w in HOP1_HINT_WORDS):
            full = urljoin(base_url, href)
            parsed = urlparse(full)
            if full not in seen and parsed.scheme in ("http", "https"):
                seen.add(full)
                links.append(full)
        if len(links) >= 8:
            break
    return links


async def plain_probe(session: aiohttp.ClientSession, url: str, headers: dict):
    """One rung of the ladder using aiohttp (home page + up to 4 hop
    links). Returns a dict: status, error, challenge(bool), platform_hits
    (set), hit_sources (dict), hop2_urls (list), final_url."""
    out = {
        "status": None,
        "error": None,
        "challenge": False,
        "platform_hits": set(),
        "hit_sources": {},
        "hop2_urls": [],
        "final_url": url,
    }
    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            out["status"] = resp.status
            out["final_url"] = str(resp.url)
            html = await resp.text(errors="replace")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        return out

    cls = classify_body(html)
    if cls == "challenge" or out["status"] in (403,) and cls == "challenge":
        out["challenge"] = True
        return out
    if out["status"] and out["status"] >= 400:
        return out

    hop1 = detect_platforms(html)
    for h in hop1:
        out["platform_hits"].add(h)
        out["hit_sources"].setdefault(h, out["final_url"])

    hop2_links = _extract_hop_links(html, out["final_url"])
    out["hop2_urls"] = hop2_links
    checked = 0
    for link in hop2_links:
        if checked >= 4:
            break
        try:
            async with session.get(
                link,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=12),
                allow_redirects=True,
            ) as r2:
                if r2.status >= 400:
                    continue
                h2 = await r2.text(errors="replace")
        except Exception:
            continue
        checked += 1
        c2 = classify_body(h2)
        if c2 == "challenge":
            out["challenge"] = True
            return out
        for h in detect_platforms(h2):
            out["platform_hits"].add(h)
            out["hit_sources"].setdefault(h, link)
    return out


async def run_access_ladder(
    session: aiohttp.ClientSession, homepage: str, row: dict
) -> dict:
    """Returns dict: access_mode, rung_answered, platform_hits (set),
    hit_sources (dict), hop2_urls (list), outcome_hint ('challenge' |
    'blocked' | 'found' | 'no_link'), reject_reason, reject_class."""
    result = {
        "access_mode": "dead",
        "rung_answered": "none",
        "platform_hits": set(),
        "hit_sources": {},
        "hop2_urls": [],
        "outcome_hint": "no_link",
        "reject_reason": "",
        "reject_class": "",
    }
    url = _normalize_url(homepage)
    if not url:
        result["outcome_hint"] = "blocked"
        result["reject_reason"] = "dns-unresolvable"
        result["reject_class"] = "access"
        return result

    # Rung 1: plain
    r1 = await plain_probe(session, url, HONEST_HEADERS)
    if r1["challenge"]:
        result.update(
            access_mode="challenge",
            rung_answered="challenge",
            outcome_hint="challenge",
            reject_reason="cloudflare-challenge-blocked",
            reject_class="access",
        )
        return result
    if r1["platform_hits"]:
        result.update(
            access_mode="plain",
            rung_answered="plain",
            platform_hits=r1["platform_hits"],
            hit_sources=r1["hit_sources"],
            hop2_urls=r1["hop2_urls"],
            outcome_hint="found",
        )
        return result

    is_404 = r1["status"] == 404
    refused = (
        r1["error"] is not None
        or r1["status"] == 403
        or (r1["status"] is not None and r1["status"] >= 500)
    )
    page_loaded = r1["status"] is not None and r1["status"] < 400

    await asyncio.sleep(HOST_DELAY_SECONDS)

    r2 = None
    if refused and not is_404:
        r2 = await plain_probe(session, url, BROWSER_HEADERS)
        if r2["challenge"]:
            result.update(
                access_mode="challenge",
                rung_answered="challenge",
                outcome_hint="challenge",
                reject_reason="cloudflare-challenge-blocked",
                reject_class="access",
            )
            return result
        if r2["platform_hits"]:
            result.update(
                access_mode="browser-headers",
                rung_answered="browser-headers",
                platform_hits=r2["platform_hits"],
                hit_sources=r2["hit_sources"],
                hop2_urls=r2["hop2_urls"],
                outcome_hint="found",
            )
            return result
        still_refused = r2["error"] is not None or r2["status"] == 403
        if still_refused:
            result.update(
                access_mode="browser-headers",
                rung_answered="browser-headers",
                outcome_hint="blocked",
                reject_reason="blocked-browser-headers",
                reject_class="access",
            )
            return result
        page_loaded = r2["status"] is not None and r2["status"] < 400
        await asyncio.sleep(HOST_DELAY_SECONDS)
    elif refused and is_404:
        # a plain 404 on the home page itself: nothing to browser-header
        # retry (never after a 404), but still worth a headless look --
        # some sites 404 a bare scheme-only fetch and render fine in a
        # browser (redirects driven by JS/meta-refresh).
        pass
    elif not page_loaded and r1["error"] is not None:
        result.update(
            access_mode="dead",
            rung_answered="none",
            outcome_hint="blocked",
            reject_reason="timeout",
            reject_class="access",
        )
        return result

    # Rung 3: headless, only for a host that answered with a page (no
    # visible link) -- never for one that 403'd browser headers (handled
    # above by returning early).
    row_for_headless = {
        "gov_id": row.get("gov_id", ""),
        "unit_name": row.get("name", ""),
        "state": row.get("state", ""),
        "country": row.get("country", ""),
        "population": row.get("population", ""),
        "homepage": url,
    }
    try:
        async with wo133_context_lock:
            res = await asyncio.wait_for(
                wo133.scan_one(wo133_browser_context[0], row_for_headless), timeout=55
            )
    except Exception as e:
        result.update(
            access_mode="dead",
            rung_answered="none",
            outcome_hint="blocked",
            reject_reason="timeout",
            reject_class="access",
        )
        result["detail"] = f"headless exception: {e}"
        return result

    if res["outcome"] == "cloudflare-challenge-blocked":
        result.update(
            access_mode="challenge",
            rung_answered="challenge",
            outcome_hint="challenge",
            reject_reason="cloudflare-challenge-blocked",
            reject_class="access",
        )
        return result
    if res["outcome"] == "still_blocked_generic":
        result.update(
            access_mode="headless",
            rung_answered="headless",
            outcome_hint="blocked",
            reject_reason="blocked-headless",
            reject_class="access",
        )
        return result
    if res["outcome"] == "fetch_error":
        result.update(
            access_mode="headless",
            rung_answered="headless",
            outcome_hint="blocked",
            reject_reason="timeout",
            reject_class="access",
        )
        return result
    if res["outcome"] == "platform_hit":
        hits = (
            set((res["platform_hits"] or "").split(";"))
            if res["platform_hits"]
            else set()
        )
        hit_sources = {}
        for pair in (res["hit_source_urls"] or "").split(";"):
            if "=" in pair:
                p, u = pair.split("=", 1)
                hit_sources[p] = u
        result.update(
            access_mode="headless",
            rung_answered="headless",
            platform_hits=hits,
            hit_sources=hit_sources,
            hop2_urls=(res["hop2_urls"] or "").split(";") if res["hop2_urls"] else [],
            outcome_hint="found",
        )
        return result

    # confirmed_no_platform
    result.update(
        access_mode="headless",
        rung_answered="headless",
        outcome_hint="no_link",
        reject_reason="no-platform-link-found",
        reject_class="content",
    )
    return result


# --------------------------------------------------------------------
# Discovery enumerate+resolve (primary), wo134 seed-resolve (fallback)
# --------------------------------------------------------------------

_PLATFORM_SUFFIX = {
    "granicus": "granicus.com",
    "civicclerk": "civicclerk.com",
    "primegov": "primegov.com",
    "escribe": "escribemeetings.com",
    "legistar": "legistar.com",
    "swagit": "swagit.com",
    "iqm2": "iqm2.com",
    "cablecast": "cablecast.tv",
    "municode_meetings": "municodemeetings.com",
    "civicweb": "civicweb.net",
}


def _netloc_of(raw: str) -> str:
    raw = (raw or "").strip()
    if "://" in raw:
        netloc = urlparse(raw).netloc
    else:
        netloc = raw.split("/", 1)[0]
    return netloc.lower().rstrip("/")


def choose_netloc(platform: str, domain: str, hit_url: str, homepage: str) -> str:
    dom_netloc = _netloc_of(domain)
    hit_netloc = _netloc_of(hit_url)
    suffix = _PLATFORM_SUFFIX.get(platform)
    if platform == "civicplus":
        return dom_netloc or _netloc_of(homepage)
    if suffix and hit_netloc.endswith(suffix):
        return hit_netloc
    if suffix and dom_netloc.endswith(suffix):
        return dom_netloc
    return hit_netloc or dom_netloc


async def extract_link_via_headless(url: str, platform: str):
    """Same job as wo134.locate_platform_url()'s plain-aiohttp fetch +
    find_specific_platform_link(), but via the shared headless browser
    context instead of a fresh aiohttp GET. Needed because a hit whose
    ladder rung was `headless` was, by definition, unreachable to a
    plain client (confirmed live 2026-09-10 during the pilot spot-check:
    Menasha WI's real civicclerk.com link only exists inside a page that
    403s a plain aiohttp GET with wo134's own UA_HEADERS, even though
    the headless render that originally found the "civicclerk" mention
    got a clean 200 -- locate_platform_url's plain re-fetch silently
    failed and this fell back to choose_netloc()'s much weaker
    domain/hit-url guess). Returns the extracted link, or None.

    Known limitation, also confirmed live on the same Menasha WI host: a
    SECOND headless visit to a page moments after the first (this
    function's own re-visit of the ladder's hit_url) can itself draw a
    real Cloudflare "Attention Required" block even though the ladder's
    original single visit rendered cleanly -- looks rate/frequency-based,
    not a permanent block. When that happens this simply returns None
    (falls back to the weaker domain/hit-url guess, a legitimate "found
    the platform, couldn't pin the exact tenant" outcome, never a false
    ingest) rather than retrying past what reads as a human-verification
    gate -- retrying would break CLAUDE.md's "politely" rule the same as
    retrying the ladder itself would."""
    context = wo133_browser_context[0]
    page = await context.new_page()
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        except Exception:
            return None
        try:
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        try:
            html = await page.content()
            final_url = page.url
        except Exception:
            return None
    finally:
        await page.close()
    if not html:
        return None
    return wo134.find_specific_platform_link(html, final_url or url, platform)


async def try_discovery(ledger, platform: str, netloc: str, gov_id: str, state: str):
    """Seed the tenant, enumerate thorough, resolve up to
    MAX_CANDIDATES_TRIED newest, return (payload_dict_or_None, detail)."""
    from discovery.enumerate_stage import enumerate_candidates
    from discovery.resolve import resolve_candidates

    ledger.upsert_tenant(netloc, platform)
    ledger.set_tenant_gov_id(netloc, gov_id, state_abbr=state)

    try:
        await enumerate_candidates(
            ledger, platforms=[platform], tenant=netloc, mode="thorough"
        )
    except Exception as e:
        return None, f"enumerate_error: {type(e).__name__}: {str(e)[:150]}"

    try:
        await resolve_candidates(
            ledger,
            tenant=netloc,
            limit=MAX_CANDIDATES_TRIED,
            require_captions=False,
            min_tier="blank",
            include_tier3=True,
            store_tier3=True,
        )
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if platform == "youtube" and is_youtube_block_signature(msg):
            global YOUTUBE_BLOCKED, YOUTUBE_BLOCK_SIGNATURE
            YOUTUBE_BLOCKED = True
            YOUTUBE_BLOCK_SIGNATURE = msg[:200]
        return None, f"resolve_error: {msg[:150]}"

    cur = ledger.conn.execute(
        "SELECT url_normalized, status, status_reason, gov_tier, resolved_json, date "
        "FROM candidates WHERE tenant_netloc = ? ORDER BY date DESC",
        (netloc,),
    )
    rows = cur.fetchall()
    import json as _json

    for r in rows:
        if not r["resolved_json"]:
            continue
        try:
            payload = _json.loads(r["resolved_json"])
        except Exception:
            continue
        segs = payload.get("segments") or []
        video_url = payload.get("video_url")
        if segs or video_url:
            payload["_seed_url"] = r["url_normalized"]
            return payload, r["status_reason"] or ""
    return None, "no candidate with a real video signal in top " + str(len(rows))


async def try_wo134_fallback(
    session: aiohttp.ClientSession,
    platform: str,
    hit_url: str,
    hop2_urls: list,
    homepage: str,
    seed_url_override: Optional[str] = None,
):
    if seed_url_override:
        # Already extracted (headless, when a plain re-fetch would hit
        # the same block that made headless necessary -- see
        # extract_link_via_headless()'s docstring).
        seed_url, reason = seed_url_override, ""
    else:
        seed_url, reason = await wo134.locate_platform_url(
            session, platform, hit_url, hop2_urls, homepage
        )
    if not seed_url:
        return None, reason
    try:
        result, final_seed, high_risk_title = await wo134.resolve_seed(
            session, platform, seed_url
        )
    except wo134.RowSkip as e:
        return None, str(e)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if platform == "youtube" and is_youtube_block_signature(msg):
            global YOUTUBE_BLOCKED, YOUTUBE_BLOCK_SIGNATURE
            YOUTUBE_BLOCKED = True
            YOUTUBE_BLOCK_SIGNATURE = msg[:200]
        return None, f"resolve_raised: {msg[:150]}"
    payload = result.model_dump()
    payload["_seed_url"] = final_seed
    payload["_high_risk_title"] = high_risk_title
    return payload, ""


# --------------------------------------------------------------------
# CSV plumbing
# --------------------------------------------------------------------

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "homepage",
    "access_mode",
    "rung_answered",
    "platform_found",
    "hit_url",
    "netloc",
    "outcome",
    "reject_reason",
    "reject_class",
    "candidates_listed",
    "candidates_tried",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]
# Exact 10-column shape as wo129_confirmed_hits.csv / wo133_confirmed_hits.csv.
CONFIRMED_HITS_FIELDS = [
    "gov_id",
    "unit_name",
    "population",
    "homepage",
    "homepage_status",
    "hop2_pages_checked",
    "hop2_urls",
    "platform_hits",
    "hit_source_urls",
    "detail",
]
SEEDS_FIELDS = ["netloc", "platform", "gov_id", "access_mode"]
HOST_MODE_FIELDS = ["host", "access_mode"]
TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]


def _csv_writer(path: Path, fields: list):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _done_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["gov_id"] for r in csv.DictReader(fh) if r.get("gov_id")}


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

wo133_browser_context = [None]
wo133_context_lock = asyncio.Lock()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pilot",
        type=int,
        default=None,
        help="process only the first N not-yet-done rows",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--inventory-csv",
        type=str,
        default="/tmp/wo148_inventory/meeting_inventory.csv",
    )
    args = ap.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    covered = wo134._load_covered_gov_ids(Path(args.inventory_csv))
    print(f"{len(covered)} gov_ids already have an archived page (fresh export).")

    rows = list(csv.DictReader(open(CANDIDATES_CSV, newline="", encoding="utf-8")))
    done = _done_gov_ids(REPORT_CSV)
    todo = [r for r in rows if r["gov_id"] not in done]
    print(
        f"{len(rows)} candidates, {len(done)} already reported, {len(todo)} to do this run."
    )
    if args.pilot:
        todo = todo[: args.pilot]
    elif args.limit:
        todo = todo[: args.limit]

    if not todo:
        print("Nothing to do.")
        return

    if not SCRATCH_LEDGER.exists():
        import shutil

        shutil.copy2(REAL_LEDGER, SCRATCH_LEDGER)
        print(
            f"copied {REAL_LEDGER} -> {SCRATCH_LEDGER} (scratch, never the real ledger)"
        )

    sys.path.insert(0, str(DISCOVERY_ROOT))
    from discovery.ledger import Ledger
    from discovery import config as discovery_config

    discovery_config.load_env()
    ledger = Ledger(str(SCRATCH_LEDGER))

    report_f, report_w = _csv_writer(REPORT_CSV, REPORT_FIELDS)
    hits_f, hits_w = _csv_writer(CONFIRMED_HITS_CSV, CONFIRMED_HITS_FIELDS)
    seeds_f, seeds_w = _csv_writer(DISCOVERY_SEEDS_CSV, SEEDS_FIELDS)
    hosts_f, hosts_w = _csv_writer(HOST_ACCESS_MODES_CSV, HOST_MODE_FIELDS)
    pending_f, pending_w = _csv_writer(TIER3_PENDING_CSV, TIER3_PENDING_FIELDS)

    consecutive_errors = 0
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, context = await wo133.new_browser_and_context(p)
        wo133_browser_context[0] = context
        since_recycle = 0

        try:
            async with aiohttp.ClientSession() as session:
                for i, row in enumerate(todo, 1):
                    gov_id = row["gov_id"]
                    name = row["name"]
                    state = row["state"]
                    population = row["population"]
                    homepage = row.get("homepage") or row.get("domain") or ""

                    out = {f: "" for f in REPORT_FIELDS}
                    out.update(
                        gov_id=gov_id,
                        name=name,
                        state=state,
                        population=population,
                        homepage=homepage,
                    )

                    try:
                        if gov_id in covered:
                            out["outcome"] = "already_covered"
                            out["note"] = (
                                "gov_id already has an archived page (fresh export)"
                            )
                            report_w.writerow(out)
                            report_f.flush()
                            consecutive_errors = 0
                            print(
                                f"[{i}/{len(todo)}] {name}, {state} -> already_covered"
                            )
                            continue

                        if since_recycle >= 12:
                            await context.close()
                            await browser.close()
                            browser, context = await wo133.new_browser_and_context(p)
                            wo133_browser_context[0] = context
                            since_recycle = 0

                        ladder = await run_access_ladder(session, homepage, row)
                        since_recycle += 1
                        out["access_mode"] = ladder["access_mode"]
                        out["rung_answered"] = ladder["rung_answered"]
                        netloc = _netloc_of(homepage)
                        hosts_w.writerow(
                            {"host": netloc, "access_mode": ladder["access_mode"]}
                        )
                        hosts_f.flush()

                        if ladder["outcome_hint"] in (
                            "challenge",
                            "blocked",
                            "no_link",
                        ):
                            out["outcome"] = (
                                "blocked"
                                if ladder["outcome_hint"] in ("challenge", "blocked")
                                else "no_platform_link_found"
                            )
                            out["reject_reason"] = ladder["reject_reason"]
                            out["reject_class"] = ladder["reject_class"]
                            report_w.writerow(out)
                            report_f.flush()
                            consecutive_errors = 0
                            print(
                                f"[{i}/{len(todo)}] {name}, {state} -> {out['outcome']} "
                                f"({ladder['reject_reason']}, rung={ladder['rung_answered']})"
                            )
                            await asyncio.sleep(GOV_DELAY_SECONDS)
                            continue

                        # found a platform link
                        platforms_found = sorted(ladder["platform_hits"])
                        out["platform_found"] = ";".join(platforms_found)
                        hit_sources = ladder["hit_sources"]
                        out["hit_url"] = ";".join(
                            f"{p}={hit_sources.get(p, '')}" for p in platforms_found
                        )
                        out["netloc"] = netloc

                        hits_w.writerow(
                            {
                                "gov_id": gov_id,
                                "unit_name": name,
                                "population": population,
                                "homepage": homepage,
                                "homepage_status": "",
                                "hop2_pages_checked": len(ladder["hop2_urls"]),
                                "hop2_urls": ";".join(ladder["hop2_urls"]),
                                "platform_hits": ";".join(platforms_found),
                                "hit_source_urls": ";".join(
                                    f"{p}={hit_sources.get(p, '')}"
                                    for p in platforms_found
                                ),
                                "detail": "platform_hit",
                            }
                        )
                        hits_f.flush()

                        # try each platform hit, newest real-video signal wins
                        from types import SimpleNamespace

                        payload = None
                        result_ns = None
                        detail = ""
                        winning_platform = ""
                        candidates_tried_total = 0
                        for platform in platforms_found:
                            hit_url = hit_sources.get(platform, "")
                            if platform in wo134.UNSUPPORTED_PLATFORMS:
                                detail = f"{platform}: unsupported platform, no adapter in this repo"
                                continue
                            if platform == "youtube" and YOUTUBE_BLOCKED:
                                detail = f"skipped: YouTube block signature seen this run ({YOUTUBE_BLOCK_SIGNATURE})"
                                continue
                            netloc_for_platform = choose_netloc(
                                platform, row.get("domain", ""), hit_url, homepage
                            )

                            # The ladder's hit_url is the PAGE the platform
                            # substring was found on, not the platform's own
                            # link (wo133.scan_one's hit_sources records
                            # final_url, same convention as its own
                            # confirmed_hits.csv) -- e.g. Menasha WI's real
                            # tenant is menashawi.portal.civicclerk.com, found
                            # only as a link INSIDE a cms5.revize.com page.
                            # Extract the real link first so both the
                            # discovery path (netloc) and the wo134 fallback
                            # path (seed_url) act on the actual tenant, not a
                            # guess from the domain/hit-page host. When the
                            # ladder rung that answered was `headless`, a
                            # plain aiohttp re-fetch (wo134.locate_platform_
                            # url's own approach) hits the exact same block
                            # that made headless necessary in the first place
                            # -- confirmed live 2026-09-10 during the pilot
                            # spot-check (Menasha WI 403'd a plain UA-headers
                            # GET even though the headless render got a clean
                            # 200) -- so use the shared headless context
                            # instead in that case.
                            # civicplus/granicus keep wo134's own smarter
                            # special-cased seed-finding (AgendaCenter path
                            # guessing / ViewPublisher listing discovery)
                            # even on a headless-rung hit -- headless
                            # extraction is a generic link scan, weaker than
                            # either of those for their own platform.
                            if ladder[
                                "rung_answered"
                            ] == "headless" and platform not in (
                                "civicplus",
                                "granicus",
                            ):
                                real_seed = await extract_link_via_headless(
                                    hit_url, platform
                                )
                                real_seed_reason = ""
                            else:
                                (
                                    real_seed,
                                    real_seed_reason,
                                ) = await wo134.locate_platform_url(
                                    session,
                                    platform,
                                    hit_url,
                                    ladder["hop2_urls"],
                                    homepage,
                                )
                            if real_seed:
                                netloc_for_platform = _netloc_of(real_seed)

                            seeds_w.writerow(
                                {
                                    "netloc": netloc_for_platform,
                                    "platform": platform,
                                    "gov_id": gov_id,
                                    "access_mode": ladder["access_mode"],
                                }
                            )
                            seeds_f.flush()

                            if platform in DISCOVERY_ENUMERABLE:
                                cand_payload, detail = await try_discovery(
                                    ledger, platform, netloc_for_platform, gov_id, state
                                )
                                candidates_tried_total += MAX_CANDIDATES_TRIED
                            else:
                                cand_payload, detail = await try_wo134_fallback(
                                    session,
                                    platform,
                                    hit_url,
                                    ladder["hop2_urls"],
                                    homepage,
                                    seed_url_override=real_seed,
                                )
                                if not cand_payload and not real_seed:
                                    detail = real_seed_reason or detail
                                candidates_tried_total += 1

                            if not cand_payload:
                                await asyncio.sleep(0.75)
                                continue

                            ns = SimpleNamespace(
                                video_url=cand_payload.get("video_url"),
                                external_id=cand_payload.get("external_id"),
                                jurisdiction=cand_payload.get("jurisdiction") or "",
                                source_url=cand_payload.get("source_url")
                                or cand_payload.get("_seed_url")
                                or "",
                                title=cand_payload.get("title") or "",
                                date=cand_payload.get("date") or "",
                            )
                            title = ns.title
                            high_risk = platform in wo134.HIGH_RISK_TITLE_PLATFORMS
                            if not title and ns.video_url:
                                title = (
                                    await wo134.youtube_oembed_title(
                                        session, ns.video_url
                                    )
                                    or ""
                                )
                            if not wo134._looks_like_real_meeting(
                                title, require_allowlist=high_risk
                            ):
                                detail = (
                                    f"{platform}: title looks like a non-meeting video, "
                                    f"not accepted: {title!r} ({ns.source_url})"
                                )
                                await asyncio.sleep(0.75)
                                continue
                            key = wo134._dedup_key(ns)
                            if key in wo134._seen_keys:
                                detail = f"{platform}: duplicate of an already-processed meeting this run ({key})"
                                await asyncio.sleep(0.75)
                                continue

                            payload = cand_payload
                            result_ns = ns
                            winning_platform = platform
                            break

                        out["candidates_listed"] = str(len(platforms_found))
                        out["candidates_tried"] = str(candidates_tried_total)

                        if not payload:
                            out["outcome"] = "no_video_found"
                            out["reject_reason"] = "no-video-found"
                            out["reject_class"] = "content"
                            out["note"] = detail[:300]
                            report_w.writerow(out)
                            report_f.flush()
                            consecutive_errors = 0
                            print(
                                f"[{i}/{len(todo)}] {name}, {state} -> no_video_found ({detail[:80]})"
                            )
                            await asyncio.sleep(GOV_DELAY_SECONDS)
                            continue

                        segs = payload.get("segments") or []
                        video_url = payload.get("video_url")
                        seed_url = payload.get("_seed_url") or result_ns.source_url
                        out["meeting_url"] = seed_url
                        out["video_url"] = video_url or ""
                        out["page_url"] = ""

                        gov = government_for_id(gov_id)
                        jurisdiction = (
                            f"{gov.gov_name}, {gov.state}"
                            if gov and gov.gov_name and gov.state
                            else name
                        )
                        if not result_ns.jurisdiction:
                            result_ns.jurisdiction = jurisdiction

                        if segs:
                            wo134._seen_keys.add(wo134._dedup_key(result_ns))
                            out["tier"] = "1_or_2"
                            payload_for_ingest = dict(payload)
                            payload_for_ingest.pop("_seed_url", None)
                            payload_for_ingest.pop("_high_risk_title", None)
                            # WO-222: this row already knows its government
                            # -- send it in the payload so a page on a
                            # shared host never depends on a
                            # tenant_overrides.csv pin reaching production
                            # first. See
                            # scripts/wo134_confirmed_hits_ingest.py's
                            # matching comment and
                            # docs/COVERAGE_HANDOVER.md §3.
                            if gov_id:
                                payload_for_ingest["gov_id"] = gov_id
                            if winning_platform in wo134.SHARED_HOST_PLATFORMS:
                                payload_for_ingest["jurisdiction"] = jurisdiction
                                wo134.maybe_write_tenant_override(
                                    winning_platform,
                                    result_ns,
                                    seed_url,
                                    gov_id,
                                    name,
                                    "wo148_headless_sweep",
                                )
                            from app.utils.url_normalize import normalize_url as _norm

                            try:
                                response = await wo134._ingest_with_retry(
                                    session, payload_for_ingest, _norm(seed_url)
                                )
                            except Exception as e:
                                out["outcome"] = "error"
                                out["note"] = f"ingest raised: {e}"[:300]
                                report_w.writerow(out)
                                report_f.flush()
                                consecutive_errors += 1
                                print(
                                    f"[{i}/{len(todo)}] {name}, {state} -> ERROR ingest: {e}"
                                )
                                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                    print("STOPPING: too many consecutive errors.")
                                    break
                                await asyncio.sleep(GOV_DELAY_SECONDS)
                                continue
                            if response is None:
                                out["outcome"] = "error"
                                out["note"] = "Archive POST failed twice"
                                report_w.writerow(out)
                                report_f.flush()
                                consecutive_errors += 1
                                print(
                                    f"[{i}/{len(todo)}] {name}, {state} -> ERROR: Archive POST failed twice"
                                )
                                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                    print("STOPPING: too many consecutive errors.")
                                    break
                                await asyncio.sleep(GOV_DELAY_SECONDS)
                                continue
                            out["outcome"] = "ingested_tier1_2"
                            out["page_url"] = response.get("url", "")
                            out["note"] = (
                                f"{len(segs)} transcript segments, platform={winning_platform}"
                            )
                            report_w.writerow(out)
                            report_f.flush()
                            consecutive_errors = 0
                            print(
                                f"[{i}/{len(todo)}] {name}, {state} -> ingested_tier1_2 ({winning_platform}, {out['page_url']})"
                            )

                        elif video_url:
                            wo134._seen_keys.add(wo134._dedup_key(result_ns))
                            out["tier"] = "3"
                            out["outcome"] = "queued_tier3_pending"
                            out["note"] = (
                                f"platform={winning_platform}, pending WO-144 probe before real queue append"
                            )
                            pin_row = ""
                            if winning_platform in wo134.SHARED_HOST_PLATFORMS:
                                host = wo134._tenant_override_host(
                                    winning_platform, result_ns, seed_url
                                )
                                match = wo134._tenant_override_match(
                                    winning_platform, result_ns, seed_url
                                )
                                if host and match:
                                    pin_row = f"{host}|{match}"
                            pending_w.writerow(
                                {
                                    "gov_id": gov_id,
                                    "platform": winning_platform,
                                    "meeting_url": seed_url,
                                    "video_url": video_url,
                                    "source_url": hit_sources.get(winning_platform, ""),
                                    "jurisdiction": jurisdiction,
                                    "pin_row": pin_row,
                                }
                            )
                            pending_f.flush()
                            report_w.writerow(out)
                            report_f.flush()
                            consecutive_errors = 0
                            print(
                                f"[{i}/{len(todo)}] {name}, {state} -> queued_tier3_pending ({winning_platform})"
                            )
                        else:
                            out["outcome"] = "no_video_found"
                            out["reject_reason"] = "no-video-found"
                            out["reject_class"] = "content"
                            report_w.writerow(out)
                            report_f.flush()
                            consecutive_errors = 0
                            print(
                                f"[{i}/{len(todo)}] {name}, {state} -> no_video_found"
                            )

                    except Exception as e:
                        out["outcome"] = "error"
                        out["note"] = f"unhandled: {type(e).__name__}: {e}"[:300]
                        report_w.writerow(out)
                        report_f.flush()
                        consecutive_errors += 1
                        print(
                            f"[{i}/{len(todo)}] {name}, {state} -> UNHANDLED ERROR: {e}"
                        )
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            print("STOPPING: too many consecutive errors.")
                            break

                    await asyncio.sleep(max(0.0, GOV_DELAY_SECONDS))
        finally:
            report_f.close()
            hits_f.close()
            seeds_f.close()
            hosts_f.close()
            pending_f.close()
            ledger.conn.commit()
            ledger.close()
            await context.close()
            await browser.close()

    if YOUTUBE_BLOCKED:
        print(f"\nYouTube block signature seen this run: {YOUTUBE_BLOCK_SIGNATURE}")
    print(f"\nDone. Report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
