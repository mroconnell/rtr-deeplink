"""WO-286 (2026-09-12): hand-read and ingest the 67 real non-YouTube leads
inside WO-281's "152 weak confirmations" bucket.

Population, re-derived directly against `research/wo281_targeted.csv`
rather than trusting the brief's "152" figure blind (see this repo's own
CLAUDE.md rule to re-derive a backlog claim before building from it): of
WO-281's 259 confirmed governments, minus the 13 WO-281 itself already
applied to `jurisdiction_coverage.csv` and 1 more it hand-read and
rejected (`ci.craig.co.us`), 93 have a STRONG youtube confirmation (the
scored candidate link itself is a youtube.com URL -- the drip's job,
close to WO-281's own "98" figure, small gap from the exclusions above)
and, of the remaining 152 non-strong-youtube governments, 85 have NO
confirmed platform anywhere on their fetched page other than a stray
weak youtube signal (a "Follow us" icon elsewhere on an otherwise
unrelated page, found by the same body-link scan, never the scored
candidate itself) -- these are also, in substance, youtube leads and
belong with the drip's population, not this WO's. The genuine remainder
-- a real, non-youtube platform confirmed via a link somewhere on the
fetched page -- is 67 governments: granicus 45, civicclerk 6, iqm2 3,
utah_pmn 3, escribe 2, suiteone 2, civicweb 2, swagit 2, legistar 1,
boxcast 1. See `scratch/wo286_derive_population2.py` (this session's
scratch dir) for the exact derivation and `research/wo281_targeted.csv`
for the source data.

This script deliberately does NOT reimplement platform-listing discovery
or the tier-3 probe/select/queue/pin machinery -- it imports the real,
tested functions from `scripts/wo134_confirmed_hits_ingest.py` (that
module's own top-level code only runs under `if __name__ == "__main__"`,
so importing it here has no side effects) and this repo's shared
`app/platforms/queue_probe.finish_candidate()`, per this WO's own brief
("captions -> page, no captions -> tier-3 through finish_candidate()").

Two phases:

  --phase resolve   For each government: `locate_platform_url()` re-reads
                     the SAME wo281 hit_url the homepage-hop sweep found
                     its weak signal on, to find the actual platform-
                     specific hub/listing link on that page (deterministic
                     -- same page, same link-detection code WO-281's own
                     `fetch_and_confirm()` used to set `platform_signal`
                     in the first place). Then `resolve_seed()` depth-
                     searches that platform's own listing for a recent
                     meeting with video (WO-170's probe-select: prefer
                     9-40 minutes, else shortest, up to 6 candidates
                     tried). Writes a report row per government --
                     title, video_url, segments count, agenda info,
                     jurisdiction, final seed URL, error -- for a human
                     (this session) to actually read before anything is
                     ingested or queued. NO ingest, NO queue write, NO
                     pin write in this phase.

  --phase apply     Reads `--decisions <csv>` (gov_id -> decision: one of
                     ingest / queue / meeting-without-video / wrong /
                     blocked), produced by hand-reading the resolve
                     report. For "ingest": shells out to
                     `python scripts/bulk_ingest.py <one-line urls file>
                     --gov-id <id>` (this WO's own brief: ingest only
                     through that script). For "queue": calls
                     `app.platforms.queue_probe.finish_candidate()`
                     directly (probe -- cached from the resolve phase's
                     own probe-select when available -- decide queue vs.
                     90-minute defer, write the queue line and a
                     `strength=fallback` tenant pin). "wrong"/"blocked"/
                     "meeting-without-video" write nothing here (the
                     jurisdiction_coverage.csv apply script records
                     those).

Environment: DATABASE_URL must be set explicitly (this repo's worktree
`.env` cwd-walk hazard) -- see CLAUDE.md. Live network calls, politely
paced (CANDIDATE_DELAY_SECONDS/REQUEST_DELAY_SECONDS from the imported
module).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402

import wo134_confirmed_hits_ingest as w134  # noqa: E402
from wo273_targeted import try_wayback_archived_body  # noqa: E402

sys.path.insert(0, str(Path.home() / "Documents" / "rtr-business" / "research"))
import wo133_headless_recheck_scan as wo133  # noqa: E402

BROWSER_HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink"
    "--claude-worktrees-platform-detection-backfill-c9742a/"
    "1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/"
    "affd8ae17518ee64d/wo286_population_full.csv"
)
REPORT_CSV = REPO_ROOT / "scripts" / "wo286_resolve_report.csv"
REQUEST_DELAY_SECONDS = w134.REQUEST_DELAY_SECONDS


def load_population():
    with POPULATION_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _report_fields():
    return [
        "domain",
        "gov_id",
        "state",
        "platform",
        "hit_url",
        "locate_error",
        "final_seed",
        "resolve_error",
        "title",
        "date",
        "jurisdiction",
        "video_url",
        "segments",
        "agenda_link",
        "agenda_items",
        "tier",
    ]


def _already_reported() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


async def fetch_html_politely(session: aiohttp.ClientSession, url: str):
    """Plain request first; browser headers ONLY after a 403 or a dropped
    connection (never after a 404) -- this repo's access-ladder rule.
    Returns (final_url, html) or (None, None)."""
    try:
        async with session.get(
            url,
            headers=w134.UA_HEADERS,
            timeout=w134.FETCH_TIMEOUT,
            allow_redirects=True,
        ) as resp:
            if resp.status == 403:
                pass  # fall through to the browser-header retry below
            elif resp.status >= 400:
                return None, None
            else:
                return str(resp.url), await resp.text(errors="replace")
    except Exception:
        pass  # dropped connection -- also retry with browser headers
    try:
        async with session.get(
            url,
            headers=BROWSER_HEADERS,
            timeout=w134.FETCH_TIMEOUT,
            allow_redirects=True,
        ) as resp:
            if resp.status >= 400:
                return None, None
            return str(resp.url), await resp.text(errors="replace")
    except Exception:
        return None, None


import re as _re  # noqa: E402

_URL_TEXT_RE = _re.compile(r"""https?://[^\s"'<>)\\]+""")


def _regex_extract_platform_url(html: str, platform: str) -> str | None:
    """Broader than `find_specific_platform_link()` (which only looks at
    `<a>`/`<iframe>`/`<video>`/`<source>` href/src/onclick) -- a plain
    regex scan of every URL-shaped substring anywhere in the raw HTML
    text, same as `platform_fingerprints.fingerprint()`'s own matching
    convention (the reason WO-281 flagged this government at all: its
    `granicus-vendor-host` signal is a bare `granicus\\.com` text search,
    not a tag-scoped one). Real, confirmed need building this WO: several
    granicus signals came from a `<link rel="dns-prefetch">`, an inline
    JSON config blob, or a plain-text mention, none of which
    `find_specific_platform_link()`'s tag walk sees. Reuses
    `detect_platform()` as the single source of truth for what counts as
    this platform's own URL shape, rather than hand-listing hostnames
    again here."""
    seen = set()
    for m in _URL_TEXT_RE.finditer(html):
        candidate = m.group(0).rstrip(".,;:")
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if detect_platform(candidate) == platform:
                return candidate
        except Exception:
            continue
    return None


async def headless_fetch(context, url: str):
    """One headless navigation via the shared Playwright context (WO-133's
    own stealth setup, reused not reimplemented). Returns
    (final_url, html, title) or (None, None, None) on a real navigation
    failure. Never used on its own to decide "human gate" -- the caller
    checks `wo133.is_human_verify_gate()` on the returned title/html and
    stops cold, per this repo's access-ladder rule."""
    page = await context.new_page()
    try:
        await page.goto(url, timeout=wo133.NAV_TIMEOUT_MS, wait_until="load")
        await page.wait_for_timeout(500)
        html = await page.content()
        title = await page.title()
        final_url = page.url
        return final_url, html, title
    except Exception:
        return None, None, None
    finally:
        await page.close()


async def locate_via_page(
    session: aiohttp.ClientSession, hit_url: str, platform: str, context=None
):
    """Re-reads the SAME wo281 hit_url the homepage-hop sweep found its
    weak platform signal on, looking for the actual platform-specific
    link on that page -- NOT `w134.locate_platform_url()`'s
    granicus/civicplus branches, which assume `hit_url` is already on or
    near the target platform's own tenant host (true for WO-134's own
    population, which came from real platform-hit URLs; false here,
    where `hit_url` is a page on the GOVERNMENT's own domain that merely
    links to the real platform elsewhere on the page).

    Access ladder (CLAUDE.md's "politely" rule): plain HTTP -> browser
    headers on a 403/dropped connection -> headless ONLY when both of
    those still come back empty/blocked, and only when the blocked
    response is a plain static denial, not an explicit human-verification
    widget (checked via WO-133's own `is_human_verify_gate()` against
    whatever body a plain 403 DID return, before ever launching a
    browser). A real, live, and common case building this WO: several
    municipal sites return a static Akamai/WAF "Access Denied" 403 to
    both a plain and a browser-header aiohttp request but load fine in
    a real browser -- not a CAPTCHA, so allowed to retry headless."""
    if detect_platform(hit_url) == platform:
        return hit_url, ""

    # Archive-first (this repo's standard rung, `wo273_targeted.
    # try_wayback_archived_body()`, reused not reimplemented) -- a real,
    # confirmed need building this WO: a large share of these municipal
    # .gov domains sit behind a static Akamai/WAF "Access Denied" 403 that
    # blocks BOTH a plain aiohttp request and a real headless Chromium
    # navigation equally (confirmed live: identical 403 body from both),
    # while `web.archive.org` itself answers normally from this
    # environment (unlike WO-281's own run, where the reverse was true --
    # see that WO's own investigation doc). The structural part of the
    # page this step needs (an embedded vendor link) rarely changes even
    # in an older capture, so a capture up to 18 months old is still
    # useful here even though it would be too stale for the actual
    # meeting-listing resolve that follows (which hits the vendor's OWN
    # host, e.g. granicus.com, never blocked this way).
    try:
        body, used_archive = await asyncio.to_thread(try_wayback_archived_body, hit_url)
    except Exception:
        body, used_archive = None, False
    if used_archive and body:
        archived_html = body.decode("utf-8", errors="replace")
        link = w134.find_specific_platform_link(
            archived_html, hit_url, platform
        ) or _regex_extract_platform_url(archived_html, platform)
        if link:
            return link, ""

    final_url, html = await fetch_html_politely(session, hit_url)
    if html:
        if wo133.is_human_verify_gate("", html):
            return None, f"human-verification gate on {hit_url} -- stopped, not retried"
        link = w134.find_specific_platform_link(
            html, final_url or hit_url, platform
        ) or _regex_extract_platform_url(html, platform)
        if link:
            return link, ""
        if context is None:
            return (
                None,
                f"no {platform} link found on the fetched page ({final_url or hit_url})",
            )
        # Plain fetch succeeded but found no matching link -- a real,
        # confirmed case here too: some of these pages are JS-rendered
        # shells server-side that only draw their real content/links via
        # client JS. Give headless one try before giving up entirely.
    if context is not None:
        h_final_url, h_html, h_title = await headless_fetch(context, hit_url)
        if h_html:
            if wo133.is_human_verify_gate(h_title, h_html):
                return (
                    None,
                    f"human-verification gate on {hit_url} -- stopped, not retried",
                )
            link = w134.find_specific_platform_link(
                h_html, h_final_url or hit_url, platform
            ) or _regex_extract_platform_url(h_html, platform)
            if link:
                return link, ""
            return (
                None,
                f"no {platform} link found even after headless fetch ({h_final_url or hit_url})",
            )
    if not html:
        return None, f"could not fetch hit_url even with headless ({hit_url})"
    return (
        None,
        f"no {platform} link found on the fetched page ({final_url or hit_url})",
    )


async def resolve_one(session: aiohttp.ClientSession, row: dict, context=None) -> dict:
    domain = row["domain"]
    gov_id = row["gov_id"]
    platform = row["platform"]
    hit_url = row["hit_url"]
    out = {
        "domain": domain,
        "gov_id": gov_id,
        "state": row["state"],
        "platform": platform,
        "hit_url": hit_url,
        "locate_error": "",
        "final_seed": "",
        "resolve_error": "",
        "title": "",
        "date": "",
        "jurisdiction": "",
        "video_url": "",
        "segments": 0,
        "agenda_link": "",
        "agenda_items": 0,
        "tier": "",
    }
    try:
        seed_url, reason = await locate_via_page(session, hit_url, platform, context)
    except Exception as e:  # noqa: BLE001
        out["locate_error"] = f"locate_via_page raised: {e}"
        return out
    if not seed_url:
        out["locate_error"] = reason or "no seed url found"
        return out

    try:
        result, final_seed, _high_risk = await w134.resolve_seed(
            session, platform, seed_url
        )
    except w134.ProbeRejected as e:
        out["final_seed"] = e.meeting_url or seed_url
        out["video_url"] = e.video_url or ""
        out["resolve_error"] = f"ProbeRejected: {e}"
        return out
    except w134.RowSkip as e:
        out["final_seed"] = getattr(e, "meeting_url", "") or seed_url
        out["resolve_error"] = f"RowSkip: {e}"
        return out
    except Exception as e:  # noqa: BLE001
        out["final_seed"] = seed_url
        out["resolve_error"] = f"unhandled: {e}"
        return out

    out["final_seed"] = final_seed
    out["title"] = result.title or ""
    out["date"] = result.date or ""
    out["jurisdiction"] = result.jurisdiction or ""
    out["video_url"] = result.video_url or ""
    out["segments"] = len(result.segments or [])
    out["agenda_link"] = result.agenda_link or ""
    out["agenda_items"] = len(result.agenda_items or [])
    if result.segments:
        out["tier"] = "tier1_2"
    elif result.video_url:
        out["tier"] = "tier3"
    elif result.agenda_items or result.agenda_link:
        out["tier"] = "no_video"
    else:
        out["tier"] = "nothing"
    return out


async def phase_resolve(limit: int | None):
    register_all_finders()
    global w134
    w134.PROBE_SELECT_HOOK = w134.build_probe_select_hook()

    population = load_population()
    done = _already_reported()
    todo = [r for r in population if r["gov_id"] not in done]
    if limit:
        todo = todo[:limit]

    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=_report_fields())
    if is_new:
        writer.writeheader()
        f.flush()

    print(f"{len(done)} already resolved, {len(todo)} to go this run.")
    consecutive_errors = 0
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, context = await wo133.new_browser_and_context(p)
        since_recycle = 0
        try:
            async with aiohttp.ClientSession(headers=w134.UA_HEADERS) as session:
                for i, row in enumerate(todo):
                    try:
                        if since_recycle >= 12:
                            await context.close()
                            await browser.close()
                            browser, context = await wo133.new_browser_and_context(p)
                            since_recycle = 0
                        out = await resolve_one(session, row, context)
                        since_recycle += 1
                        consecutive_errors = 0
                    except Exception as e:  # noqa: BLE001
                        out = {k: "" for k in _report_fields()}
                        out.update(
                            domain=row["domain"],
                            gov_id=row["gov_id"],
                            state=row["state"],
                            platform=row["platform"],
                            hit_url=row["hit_url"],
                            resolve_error=f"top-level exception: {e}",
                        )
                        consecutive_errors += 1
                    writer.writerow(out)
                    f.flush()
                    print(
                        f"[{i + 1}/{len(todo)}] {out['domain']:35s} {out['platform']:12s} "
                        f"tier={out.get('tier', ''):9s} segs={out.get('segments', '')} "
                        f"video={bool(out.get('video_url'))} "
                        f"err={out.get('locate_error') or out.get('resolve_error')}"
                    )
                    if consecutive_errors >= 5:
                        print("ABORTING: 5 consecutive errors.", file=sys.stderr)
                        break
                    if i < len(todo) - 1:
                        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        finally:
            await context.close()
            await browser.close()
    f.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["resolve"])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.phase == "resolve":
        await phase_resolve(args.limit)


if __name__ == "__main__":
    asyncio.run(main())
