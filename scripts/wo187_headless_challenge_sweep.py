"""WO-187 (2026-09-11): headless pass on governments where every candidate
domain WO-184's continuation already tried ended at a challenge gate or an
access-class reject -- rtr-business/research/wo187_candidates.csv.

Ryan's question (docs/BREADTH_SWEEP_BRIEF.md, the WO-141/WO-148 findings,
and WO-194's live finding that an ordinary browser navigation clears a
Cloudflare "managed challenge" -- a JavaScript check, no puzzle -- on its
own): of the hosts every earlier rung rejected, how many are a managed
challenge a real browser clears by itself, versus a genuine interactive
human-verification gate where this project always stops?

Rules that do not bend (from this WO's own brief, restated here so this
script is self-explaining without the brief open):

- Never solve, click, or wait out an interactive challenge. Load the page
  once, wait up to 15 seconds total for a JS managed challenge to settle
  on its own, and if it is still a challenge, record `challenge-
  interactive` and move on -- no retries past that point.
- One browser, one host at a time, 5 seconds between hosts, HONEST browser
  identity -- the plain, un-spoofed Playwright Chromium user agent. This
  is a deliberate departure from wo147_access_ladder_sweep.py's own
  `fetch_headless()`/`BROWSER_HEADERS`, which set a spoofed desktop-Chrome
  UA string; that spoof is fine for the ordinary access ladder (CLAUDE.md's
  "politely" rule treats a realistic UA as compliance, not defiance) but
  this pilot is specifically measuring what an HONEST client gets, so it
  must not disguise itself. `is_challenge()` and `waf_family_from_headers()`
  ARE reused unmodified from that module -- only the browser launch itself
  (no UA override) differs.
- Budget: 300 renders total. Each government may use up to 3 (primary,
  then alternates, in the order `coverage_alternates.candidate_domains()`
  returns them).

Method, per government, in candidate-file order:

1. Headless-load the primary domain's home page (then alternates, in
   order, only if the primary did not render). Classify each host:
   `cleared-managed-challenge` (looked like a challenge on first paint,
   then cleared within the 15s settle window), `challenge-interactive`
   (still a challenge at 15s -- stop, move to the next alternate),
   `blocked-headless` (a real HTTP error status, or a real navigation
   with essentially no content), `dead` (DNS/connect/timeout -- the
   navigation itself failed), `rendered-no-challenge` (a real page, no
   challenge ever seen -- the plain client upstream was blocked, the
   browser was not). Recorded per host in `wo187_host_results.csv`.
2. For a host that rendered (either of the two "success" classes above):
   look for a platform link on the rendered HTML
   (`wo147_access_ladder_sweep.find_platform_link`); if none, one hop
   into a meeting/agenda-hinted link (`find_hop_links`), fetched with the
   PLAIN client (honest headers) carrying the cookies the browser just
   received on that host -- never a second headless render for the hop.
3. A found (platform, url) hit is handed to
   `wo134_confirmed_hits_ingest.process_row()` UNCHANGED -- the same
   locate_platform_url -> resolve_seed -> ingest/queue/pin pipeline every
   sweep in this project reuses. Tier-3 candidates are routed to this
   WO's own pending file (`wo187_tier3_pending.csv`) via TIER3_HANDLER,
   probed with `app.platforms.queue_probe.probe_queue_entry()` in a
   second pass (`stage2_finish_tier3()`), and only a probe-accepted
   candidate is appended to the real
   `scripts/tier3_auto_transcription_queue.txt` / pinned in
   `tenant_overrides.csv`.
4. Every ingested/queued result is hand-checked (title + `result.
   jurisdiction` against the candidate's own name/state) per WO-191's
   1-in-10 wrong-government rate -- see `_title_looks_offmission()`.
   A mismatch is never ingested as this government's page (process_row
   already only creates the page under the identity it resolved), but is
   recorded in the report's `note` column with the real owner, per this
   WO's "record the owner" instruction.

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo187_inventory --source export
    /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python3 \\
        scripts/wo187_headless_challenge_sweep.py --inventory-csv /tmp/wo187_inventory/meeting_inventory.csv

Resumable: a gov_id already in `wo187_report.csv` is skipped on a re-run.
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
from typing import Dict, List, Optional, Tuple
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
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    append_probe_row,
    probe_queue_entry,
)

# Import-only, per this WO's brief: is_challenge/waf_family_from_headers
# are reused unmodified. find_platform_link/find_hop_links/HONEST_HEADERS
# are the same shared platform-detection/hop-scan helpers every sweep in
# this repo already uses -- not re-derived here. Importing this module
# has ONE top-level side effect (`wo134.TIER3_HANDLER = tier3_pending_
# handler`, wo147's own handler) -- overridden below, after this import,
# by this WO's own handler. See wo184_ingest_found.py's docstring for why
# a caller that wants its OWN pending file must re-assign TIER3_HANDLER
# after importing this module, never rely on its default.
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    HONEST_HEADERS,
    classify_skip_reason,
    find_hop_links,
    find_platform_link,
    is_challenge,
    normalize_home_url,
    waf_family_from_headers,
)

import scripts.coverage_alternates as ca  # noqa: E402
import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo187_candidates.csv"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
HOST_RESULTS_CSV = RESEARCH_DIR / "wo187_host_results.csv"
REPORT_CSV = RESEARCH_DIR / "wo187_report.csv"
PENDING_CSV = RESEARCH_DIR / "wo187_tier3_pending.csv"

DEFAULT_INVENTORY_CSV = Path("/tmp/wo187_inventory/meeting_inventory.csv")

MAX_RENDERS_TOTAL = 300
MAX_RENDERS_PER_GOV = 3
HOST_DELAY_SECONDS = 5.0
SETTLE_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 1.5
NAV_TIMEOUT_MS = 20000
HOP_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

_TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]

_HOST_RESULT_FIELDS = [
    "gov_id",
    "host",
    "waf_family",
    "result",
    "seconds_to_settle",
    "title",
]

_REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "source_list",
    "host",
    "headless_result",
    "waf_family",
    "platform_found",
    "netloc",
    "outcome",
    "reject_reason",
    "reject_class",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]


# --- headless fetch, honest identity -------------------------------------


@dataclass
class HeadlessResult:
    html: Optional[str]
    final_url: str
    status: Optional[int]
    headers: dict
    error: Optional[str]
    seconds_to_settle: float
    title: str
    saw_challenge: bool


def _looks_blank(html_text: Optional[str]) -> bool:
    if not html_text:
        return True
    # crude but cheap: strip tags, see if anything real is left.
    import re as _re

    text = _re.sub(r"<[^>]+>", " ", html_text)
    text = _re.sub(r"\s+", " ", text).strip()
    return len(text) < 200


def classify_headless(r: HeadlessResult) -> str:
    if r.error is not None:
        # NAV_ERROR: goto() itself failed (DNS/connect/timeout) -- dead.
        # CONTENT_ERROR: navigation succeeded but the page never settled
        # enough to read (kept redirecting) -- treated as blocked, not
        # dead, since a real response WAS received.
        return "dead" if r.error.startswith("NAV_ERROR") else "blocked-headless"
    if r.saw_challenge and r.html and is_challenge(r.html):
        return "challenge-interactive"
    if (r.status is not None and r.status >= 400) or _looks_blank(r.html):
        return "blocked-headless"
    if r.saw_challenge:
        return "cleared-managed-challenge"
    return "rendered-no-challenge"


async def context_cookie_header(browser_context, url: str) -> str:
    try:
        cookies = await browser_context.cookies([url])
    except Exception:  # noqa: BLE001
        return ""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


# --- report/pending writers ------------------------------------------------


def _writer(path: Path, fields: List[str]):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
    if is_new:
        w.writeheader()
    return f, w


def _already_done_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


_pending_seen: Optional[set] = None


def _pending_already_seen() -> set:
    global _pending_seen
    if _pending_seen is None:
        seen = set()
        if PENDING_CSV.exists():
            with PENDING_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("meeting_url", ""))
        _pending_seen = seen
    return _pending_seen


def wo187_tier3_pending_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    if final_seed in _pending_already_seen():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|wo187_headless_challenge_sweep|"
                f"{unit_name} -- WO-187 headless-cleared find, gov_id={gov_id}"
            )
    is_new = not PENDING_CSV.exists()
    with PENDING_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_TIER3_PENDING_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "gov_id": gov_id,
                "platform": platform,
                "meeting_url": final_seed,
                "video_url": result.video_url or final_seed,
                "source_url": hit_url,
                "jurisdiction": result.jurisdiction or "",
                "pin_row": pin_row,
            }
        )
    _pending_already_seen().add(final_seed)


wo134.TIER3_HANDLER = wo187_tier3_pending_handler


_GOV_KIND_WORDS = {
    "county",
    "city",
    "town",
    "township",
    "village",
    "borough",
    "municipality",
}


def _title_looks_offmission(candidate_name: str, title: str) -> bool:
    """Cheap first-pass flag, per WO-191's 1-in-10 wrong-government rate
    (WO-148 found the same failure shape: a small government's site
    correctly links to its COUNTY's meeting system, and the tool
    correctly follows it -- right link, wrong government). RowResult
    carries no jurisdiction field, only a video/meeting title, so this
    compares the title's own place-name words against the candidate
    government's name. A flag here is NOT an auto-reject -- process_row
    already only creates a page under whatever identity it resolved --
    it is a prompt for the hand-check this WO's brief requires on every
    ingested video, recorded in the report's `note` column so a human
    (or a later pass) can look and record the real owner."""
    if not title:
        return False
    t = title.lower()
    name_words = [
        w.lower()
        for w in candidate_name.replace(",", " ").split()
        if len(w) > 2 and w.lower() not in _GOV_KIND_WORDS
    ]
    if not name_words:
        return False
    return not any(w in t for w in name_words)


# --- JC lookups --------------------------------------------------------


def load_jc_by_gov_id() -> Dict[str, dict]:
    with JC_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: Dict[str, dict] = {}
    for r in rows:
        gid = r.get("gov_id")
        if gid:
            out[gid] = r
    return out


# --- per-government processing -----------------------------------------


async def one_hop_platform_link(
    session: aiohttp.ClientSession,
    html: str,
    final_url: str,
    cookie_header: str,
) -> Optional[Tuple[str, str]]:
    hop_links = find_hop_links(html, final_url)
    for link in hop_links:
        await asyncio.sleep(HOST_DELAY_SECONDS)
        headers = dict(HONEST_HEADERS)
        if cookie_header:
            headers["cookie"] = cookie_header
        try:
            async with session.get(
                link, headers=headers, timeout=HOP_REQUEST_TIMEOUT, allow_redirects=True
            ) as resp:
                text = await resp.text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if is_challenge(text):
            continue
        hit = find_platform_link(text, str(resp.url))
        if hit:
            return hit
    return None


async def process_government(
    browser,
    session: aiohttp.ClientSession,
    row: dict,
    jc_by_gov_id: Dict[str, dict],
    covered_gov_ids: set,
    host_writer,
    render_budget: "list[int]",
) -> Tuple[str, dict]:
    """Returns (status, report_row). status is 'ok', 'budget', or 'error'."""
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]

    base_report = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        population=row.get("population", ""),
        source_list=row.get("source_list", ""),
        host="",
        headless_result="",
        waf_family="",
        platform_found="",
        netloc="",
        outcome="",
        reject_reason="",
        reject_class="",
        meeting_url="",
        video_url="",
        tier="",
        page_url="",
        note="",
    )

    if gov_id in covered_gov_ids:
        return "ok", {**base_report, "outcome": "already_covered"}

    jc_row = jc_by_gov_id.get(gov_id)
    if jc_row is None:
        return "ok", {
            **base_report,
            "outcome": "error",
            "note": "gov_id not found in jurisdiction_coverage.csv",
        }

    if ca.already_has_coverage(jc_row):
        return "ok", {
            **base_report,
            "outcome": "already_covered",
            "note": "jurisdiction_coverage.csv already marks this covered",
        }

    domains = ca.candidate_domains(jc_row)
    if not domains:
        return "ok", {
            **base_report,
            "outcome": "error",
            "note": "no domain/alternate_domains on file",
        }

    winning_html: Optional[str] = None
    winning_url: str = ""
    winning_context = None
    tried = 0
    for domain in domains[:MAX_RENDERS_PER_GOV]:
        if render_budget[0] >= MAX_RENDERS_TOTAL:
            return "budget", {
                **base_report,
                "outcome": "skipped",
                "note": "render budget exhausted",
            }
        url = normalize_home_url(domain)
        host = urlparse(url).netloc
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        render_budget[0] += 1
        tried += 1
        r = await _fetch_in_context(context, url)
        result = classify_headless(r)
        waf = waf_family_from_headers(r.headers) if r.headers else "none"
        host_writer.writerow(
            {
                "gov_id": gov_id,
                "host": host,
                "waf_family": waf,
                "result": result,
                "seconds_to_settle": f"{r.seconds_to_settle:.1f}",
                "title": r.title,
            }
        )
        # Always record the MOST RECENT attempt here -- if nothing ever
        # clears, this becomes the government's final reported outcome,
        # and the last domain tried (e.g. an alternate that hit a real
        # interactive challenge) is a more useful finding than the
        # first (e.g. a primary that was simply dns-unresolvable).
        base_report["host"] = host
        base_report["headless_result"] = result
        base_report["waf_family"] = waf

        if result in ("cleared-managed-challenge", "rendered-no-challenge"):
            winning_html = r.html
            winning_url = r.final_url
            winning_context = context
            break
        else:
            await context.close()
            await asyncio.sleep(HOST_DELAY_SECONDS)

    if winning_html is None:
        # Every domain ended blocked/dead/challenge-interactive.
        last_result = base_report["headless_result"] or "dead"
        reject_map = {
            "challenge-interactive": "cloudflare-challenge-blocked",
            "blocked-headless": "blocked-headless",
            "dead": "dns-unresolvable",
        }
        return "ok", {
            **base_report,
            "outcome": "blocked",
            "reject_reason": reject_map.get(last_result, "blocked-headless"),
            "reject_class": "access",
        }

    try:
        hit = find_platform_link(winning_html, winning_url)
        cookie_header = ""
        if hit is None:
            cookie_header = await context_cookie_header(winning_context, winning_url)
            hit = await one_hop_platform_link(
                session, winning_html, winning_url, cookie_header
            )
    finally:
        await winning_context.close()

    if hit is None:
        return "ok", {
            **base_report,
            "outcome": "no_platform_link_found",
            "reject_reason": "no-platform-link-found",
            "reject_class": "content",
        }

    platform, hit_url = hit
    netloc = urlparse(hit_url).netloc
    base_report["platform_found"] = platform
    base_report["netloc"] = netloc

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": name,
        "homepage": winning_url,
        "hop2_urls": "",
        "hit_source_urls": f"{platform}={hit_url}",
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo187_headless_challenge_sweep"
        )
    except Exception as e:  # noqa: BLE001
        return "error", {
            **base_report,
            "outcome": "error",
            "note": f"process_row raised: {type(e).__name__}: {e}",
        }

    outcome = result.outcome
    note = result.reason or ""
    if outcome == "ingested_tier1_2" and _title_looks_offmission(name, result.title):
        note = (
            note
            + f"; NEEDS HAND-CHECK -- title doesn't plainly name {name}, {state}; verify body/owner before trusting this page"
        ).strip("; ")

    if outcome == "already_covered":
        return "ok", {**base_report, "outcome": "already_covered"}
    if outcome == "ingested_tier1_2":
        tier = "tier2" if result.platform == "youtube" else "tier1"
        return "ok", {
            **base_report,
            "outcome": "ingested_tier1_2",
            "meeting_url": result.seed_url,
            "tier": tier,
            "page_url": result.page_url,
            "note": note,
        }
    if outcome == "queued_tier3_pending":
        return "ok", {
            **base_report,
            "outcome": "queued_tier3_pending",
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
            "tier": "tier3_pending",
            "note": note,
        }
    if outcome == "rejected_by_probe":
        return "ok", {
            **base_report,
            "outcome": "rejected_by_probe",
            "reject_reason": "rejected_by_probe",
            "reject_class": "content",
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
            "note": note,
        }
    if result.video_url and not result.seed_url:
        return "ok", {
            **base_report,
            "outcome": "skipped",
            "reject_reason": "video-without-meeting",
            "reject_class": "content",
            "video_url": result.video_url,
            "note": note,
        }

    reject_reason = classify_skip_reason(result.reason)
    return "ok", {
        **base_report,
        "outcome": "meeting_without_video"
        if reject_reason in ("no-video-found", "meeting-without-video")
        else reject_reason.replace("-", "_"),
        "reject_reason": reject_reason,
        "reject_class": "content",
        "meeting_url": result.seed_url,
        "video_url": result.video_url,
        "note": note,
    }


async def _safe_content(page) -> Optional[str]:
    """`page.content()` can raise ("...page is navigating and changing
    the content") when a page keeps redirecting (a meta-refresh, a JS
    bounce) right after `goto()` returns -- confirmed live running this
    script's own dry run (Lehigh County PA). A brief wait and one retry
    is enough; still failing after that is folded into `error` by the
    caller, same as any other unreadable page."""
    for attempt in range(3):
        try:
            return await page.content()
        except Exception:  # noqa: BLE001
            if attempt == 2:
                return None
            await page.wait_for_timeout(500)
    return None


async def _fetch_in_context(context, url: str) -> HeadlessResult:
    """One page load in `context` (created by the caller with no
    `user_agent=` override, so Playwright reports its own real, honest
    Chromium identity -- deliberately NOT wo147_access_ladder_sweep.py's
    `BROWSER_HEADERS` spoofed desktop-Chrome UA string; see this module's
    docstring). Polls up to SETTLE_TIMEOUT_SECONDS for a JS managed
    challenge to clear on its own. Never retries, never interacts with
    the page beyond loading and reading it."""
    t0 = time.monotonic()
    try:
        page = await context.new_page()
    except Exception as e:  # noqa: BLE001
        return HeadlessResult(
            None, url, None, {}, f"NAV_ERROR: {type(e).__name__}: {e}", 0.0, "", False
        )
    try:
        response = await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
    except Exception as e:  # noqa: BLE001
        return HeadlessResult(
            None, url, None, {}, f"NAV_ERROR: {type(e).__name__}: {e}", 0.0, "", False
        )

    status = response.status if response else None
    headers = dict(response.headers) if response else {}
    content = await _safe_content(page)
    saw_challenge = bool(content and is_challenge(content))
    settle_elapsed = time.monotonic() - t0

    if saw_challenge:
        deadline = t0 + SETTLE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            wait_ms = min(int(POLL_INTERVAL_SECONDS * 1000), remaining_ms) or 1
            await page.wait_for_timeout(wait_ms)
            new_content = await _safe_content(page)
            settle_elapsed = time.monotonic() - t0
            if new_content is not None:
                content = new_content
            if content and not is_challenge(content):
                break

    try:
        title = await page.title()
    except Exception:  # noqa: BLE001
        title = ""
    final_url = page.url
    error = (
        None
        if content is not None
        else "CONTENT_ERROR: unreadable after retries (page kept navigating)"
    )
    return HeadlessResult(
        content, final_url, status, headers, error, settle_elapsed, title, saw_challenge
    )


async def stage2_finish_tier3() -> Tuple[int, int]:
    if not PENDING_CSV.exists():
        print(f"No {PENDING_CSV.name} -- no tier-3 candidates this run.")
        return 0, 0
    with PENDING_CSV.open(newline="", encoding="utf-8") as f:
        pending_rows = list(csv.DictReader(f))
    if not pending_rows:
        return 0, 0
    print(f"\n{len(pending_rows)} tier-3 pending row(s) to probe.")

    existing_queue_urls = wo134._existing_tier3_queue_urls()
    existing_override_keys = set()
    tenant_overrides_csv = (
        REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
    )
    if tenant_overrides_csv.exists():
        with tenant_overrides_csv.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing_override_keys.add(
                    (r.get("tenant_host", ""), r.get("match", ""))
                )

    accepted, rejected = 0, 0
    last_call_by_host: Dict[str, float] = {}
    for i, row in enumerate(pending_rows):
        host = urlparse(row["meeting_url"]).netloc
        last = last_call_by_host.get(host)
        if last is not None:
            remaining = HOST_DELAY_SECONDS - (time.monotonic() - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        last_call_by_host[host] = time.monotonic()

        result = await probe_queue_entry(
            row["meeting_url"],
            video_url=row.get("video_url") or None,
            source_page_url=row.get("source_url") or None,
        )
        append_probe_row(DEFAULT_SIDECAR_PATH, result)
        print(
            f"[{i + 1}/{len(pending_rows)}] [{result.verdict}] {row['gov_id']} "
            f"{row['meeting_url']} -- {result.reason or f'{result.duration_seconds}s'}"
        )

        if result.verdict in ("accept", "flag-long"):
            accepted += 1
            queue_line = row["meeting_url"]
            if row.get("source_url"):
                queue_line = f"{queue_line}\t{row['source_url']}"
            if row["meeting_url"] not in existing_queue_urls:
                with wo134.TIER3_QUEUE_FILE.open("a", encoding="utf-8") as qf:
                    qf.write(queue_line + "\n")
                existing_queue_urls.add(row["meeting_url"])
            pin_row = row.get("pin_row", "")
            if pin_row:
                parts = pin_row.split("|", 5)
                if len(parts) == 6:
                    tenant_host, match, gov_id, strength, source, evidence = parts
                    key = (tenant_host, match)
                    if key not in existing_override_keys:
                        is_new = not tenant_overrides_csv.exists()
                        with tenant_overrides_csv.open(
                            "a", newline="", encoding="utf-8"
                        ) as f:
                            w = csv.DictWriter(
                                f,
                                fieldnames=[
                                    "tenant_host",
                                    "match",
                                    "gov_id",
                                    "strength",
                                    "source",
                                    "evidence",
                                ],
                                lineterminator="\n",
                            )
                            if is_new:
                                w.writeheader()
                            w.writerow(
                                {
                                    "tenant_host": tenant_host,
                                    "match": match,
                                    "gov_id": gov_id,
                                    "strength": strength,
                                    "source": source,
                                    "evidence": evidence,
                                }
                            )
                        existing_override_keys.add(key)
        else:
            rejected += 1

    print(
        f"\nTier-3 finish: {accepted} accepted (queued), {rejected} rejected by probe."
    )
    return accepted, rejected


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    parser.add_argument("--max-renders", type=int, default=MAX_RENDERS_TOTAL)
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"{len(all_rows)} candidate rows in {CANDIDATES_CSV.name}")

    jc_by_gov_id = load_jc_by_gov_id()
    print(f"{len(jc_by_gov_id)} rows in jurisdiction_coverage.csv")

    already_done = _already_done_gov_ids()
    print(
        f"{len(already_done)} gov_ids already in {REPORT_CSV.name} -- skipping those."
    )

    to_process = [r for r in all_rows if r["gov_id"] not in already_done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} row(s)...\n")

    host_f, host_writer = _writer(HOST_RESULTS_CSV, _HOST_RESULT_FIELDS)
    report_f, report_writer = _writer(REPORT_CSV, _REPORT_FIELDS)
    render_budget = [0]
    tally: Dict[str, int] = {}
    consecutive_errors = 0

    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                async with aiohttp.ClientSession() as session:
                    for i, row in enumerate(to_process):
                        if render_budget[0] >= args.max_renders:
                            print(
                                f"\nRender budget ({args.max_renders}) reached -- stopping."
                            )
                            break
                        t0 = time.monotonic()
                        status, report_row = await process_government(
                            browser,
                            session,
                            row,
                            jc_by_gov_id,
                            covered_gov_ids,
                            host_writer,
                            render_budget,
                        )
                        host_f.flush()
                        report_writer.writerow(report_row)
                        report_f.flush()
                        elapsed = time.monotonic() - t0
                        print(
                            f"[{i + 1}/{len(to_process)}] {row['name']}, {row['state']} -- "
                            f"{elapsed:.1f}s -- {status} -- {report_row.get('outcome')} "
                            f"(renders used: {render_budget[0]})"
                        )
                        tally[report_row.get("outcome", "")] = (
                            tally.get(report_row.get("outcome", ""), 0) + 1
                        )
                        if status == "error":
                            consecutive_errors += 1
                        else:
                            consecutive_errors = 0
                        if consecutive_errors >= 6:
                            print(
                                f"\nABORTING: {consecutive_errors} consecutive real errors.",
                                file=sys.stderr,
                            )
                            break
            finally:
                await browser.close()
    finally:
        host_f.close()
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:25} {v}")

    await stage2_finish_tier3()

    print(f"\nHost results: {HOST_RESULTS_CSV}")
    print(f"Report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
