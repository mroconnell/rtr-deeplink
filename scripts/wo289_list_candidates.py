"""WO-289 phase 1: list candidate meetings for governments whose platform
is already on file (jurisdiction_coverage.csv), via each platform's real
listing -- rtr-discovery's enumerator for the platforms it supports
(granicus, civicclerk, civicweb, escribe, iqm2, cablecast,
municode_meetings, primegov, legistar, swagit, proudcity), reusing
scripts/wo145_api_first_sweep.py's tenant-derivation and identity-check
helpers (imported, not copied) exactly as that script's own module
docstring describes the pattern.

This does NOT ingest anything. It writes one row per government to
wo289_pending_handread.csv with the best still-unresolved candidate
meeting's title/date/body/url, for a human (WO-289's own agent) to
hand-read before scripts/wo289_finish_approved.py ingests the approved
ones -- the same shape as wo149_tier3_pending.csv's finishing pattern,
extended one step earlier because Ryan's rule (WO-289 brief) requires a
hand-read on EVERY chosen video, not only the tier-3 ones.

Must run under rtr-discovery's own venv (it imports `discovery`), same
requirement as wo145_api_first_sweep.py -- see that script's own usage
comment.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo289_test.db" \\
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo289_list_candidates.py --limit 50
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))
DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
sys.path.insert(0, str(DISCOVERY_ROOT))

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.models import ResolvedMeeting  # noqa: E402

import scripts.hub_sweep_wo126 as hs  # noqa: E402
from scripts.wo145_api_first_sweep import (  # noqa: E402
    ENUMERATOR_HIGH_RISK_TITLE_PLATFORMS,
    ENUMERATOR_PLATFORMS,
    CROSS_BORDER_RISK_PLATFORMS,
    MAX_CANDIDATES_TRIED,
    _cross_border_collision,
    _state_or_kind_conflict,
    _title_place_conflict,
    check_tenant_identity,
    netloc_of,
    polite_fetch,
)

from discovery.ledger import Ledger  # noqa: E402
from discovery.enumerate_stage import enumerate_candidates  # noqa: E402
from discovery.resolve import resolve_candidates  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
# "_remaining" -- the population minus governments already covered by a
# page or by another government's own already-queued/deferred tier-3
# entry (this run's own round-2 host cross-check; see wo289's
# BACKLOG_DONE.md entry). "_full_population.csv" (same directory) is
# the untrimmed re-derived population for the record -- re-run
# scripts/wo289_list_candidates.py's own population step to refresh
# either before resuming after a gap.
GROUP_C_CSV = RESEARCH_DIR / "wo289_candidates_group_c_remaining.csv"
GROUP_D_CSV = RESEARCH_DIR / "wo289_candidates_group_d_remaining.csv"
PENDING_CSV = RESEARCH_DIR / "wo289_pending_handread.csv"
LOG_CSV = RESEARCH_DIR / "wo289_list_log.csv"

REAL_LEDGER = DISCOVERY_ROOT / "ledger.db"
SCRATCH_LEDGER = Path("/tmp/wo289_ledger.db")

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

_GOV_KIND_PREFIX = {
    "us:place": "municipality",
    "us:cousub": "municipality",
    "ca:csd": "municipality",
    "us:county": "county",
    "ca:cd": "county",
    "us:sd": "school_district",
    "us:state": "state",
    "ca:pr": "province",
}


@dataclass
class Cand:
    gov_id: str
    name: str
    state: str
    country: str
    population: str
    domain: str
    platform_norm: str
    hub_url: str
    reject_reason: str
    group: str  # "C" or "D"

    @property
    def jurisdiction(self) -> str:
        return f"{self.name}, {self.state}"

    @property
    def gov_kind(self) -> str:
        prefix = ":".join(self.gov_id.split(":")[:2]) if self.gov_id else ""
        return _GOV_KIND_PREFIX.get(prefix, "other")


def load_candidates() -> list[Cand]:
    out = []
    for group, path in (("C", GROUP_C_CSV), ("D", GROUP_D_CSV)):
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.append(
                    Cand(
                        gov_id=r["gov_id"],
                        name=r["city_name"],
                        state=(r.get("state_or_province") or "").strip(),
                        country=(r.get("country") or "").strip(),
                        population=(r.get("population_estimate") or "").strip(),
                        domain=(r.get("domain") or "").strip(),
                        platform_norm=(r.get("primary_platform") or "").strip().lower(),
                        hub_url=(
                            r.get("example_meeting_url")
                            or r.get("example_agenda_or_calendar_url")
                            or ""
                        ).strip(),
                        reject_reason=(r.get("reject_reason") or "").strip(),
                        group=group,
                    )
                )
    return out


def derive_netloc(cand: Cand):
    suffix = _PLATFORM_SUFFIX.get(cand.platform_norm)
    dom = netloc_of(cand.domain)
    if suffix and dom.endswith(suffix):
        return dom, "domain"
    hub = netloc_of(cand.hub_url)
    if hub:
        return hub, "hub_url"
    return None, ""


def _is_akamai_govaccess_blocked(domain: str) -> bool:
    """Preamble's 2026-09-12 finding: every government website whose www
    CNAMEs to granicusgovaccess.net answers a 403 Access Denied
    (AkamaiGHost) to this machine right now -- an IP-level WAF block on
    tonight's volume, not a human gate. Check the CNAME first and skip
    those hosts rather than retrying them into the block."""
    if not domain:
        return False
    import subprocess

    for host in (domain, f"www.{domain}"):
        try:
            out = subprocess.run(
                ["dig", "+short", "CNAME", host],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except Exception:  # noqa: BLE001
            continue
        if "granicusgovaccess.net" in out:
            return True
    return False


async def find_tenant_via_homepage(session: aiohttp.ClientSession, cand: Cand):
    """WO-289 brief step 1's "one fetch" tenant lookup, for a row that
    only names the platform with no domain/hub_url that already resolves
    to it: fetch the government's own home page (honest headers, browser
    headers only after a 403/drop, never after a 404 -- polite_fetch,
    imported from wo145) and look for a link to the platform's own host.
    Returns (netloc_or_None, access_mode, note)."""
    dom = cand.domain
    if not dom:
        return None, "", "no domain on this row to fetch"
    if _is_akamai_govaccess_blocked(dom):
        return None, "blocked-waf-akamai", f"{dom} CNAMEs to granicusgovaccess.net"
    url = dom if "://" in dom else f"https://{dom}"
    mode, final_url, html = await polite_fetch(session, url)
    if html is None:
        reject = {"challenge": "cloudflare-challenge-blocked"}.get(
            mode,
            "blocked-browser-headers"
            if mode == "browser-headers"
            else "blocked-plain-http",
        )
        return None, reject, f"{mode}: no page returned from {url}"
    links = hs._platform_links(html, final_url)
    match = next((u for u, p in links if p == cand.platform_norm), None)
    if not match:
        return (
            None,
            "no-platform-link-found",
            f"{mode}: home page reachable, no {cand.platform_norm} link found",
        )
    return netloc_of(match), mode, f"{mode}: found via homepage scan"


def _already_done(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def _log_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    fieldnames = [
        "gov_id",
        "group",
        "platform",
        "netloc",
        "netloc_source",
        "outcome",
        "reject_reason",
        "note",
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    if is_new:
        w.writeheader()
    return f, w


def _pending_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    fieldnames = [
        "gov_id",
        "group",
        "jurisdiction",
        "platform",
        "netloc",
        "title",
        "date",
        "meeting_body",
        "adapter_jurisdiction",
        "meeting_url",
        "video_url",
        "source_url",
        "segments_count",
        "tier",
        "decision",
        "decision_note",
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    if is_new:
        w.writeheader()
    return f, w


async def check_candidate(
    session: aiohttp.ClientSession,
    cand: Cand,
    result: ResolvedMeeting,
    meeting_url: str,
) -> Optional[str]:
    """Runs the SAME automated identity/quality checks wo145's
    act_on_result() runs, imported not copied. Returns a reject reason
    string on a confident automated reject, None if it should go to the
    pending file for a hand-read. This does NOT replace the hand-read --
    it only screens out what's already confidently wrong so the
    hand-read isn't spent on collisions the code can already catch."""
    segments = result.segments or []
    agenda_items = result.agenda_items or []
    if not (segments or agenda_items or result.agenda_link or result.video_url):
        return "no-video-found"
    # Ryan's ingest rule (CLAUDE.md, BREADTH_SWEEP_BRIEF.md): only a
    # meeting WITH VIDEO becomes a page. `agenda_items`/`agenda_link`
    # are agenda/chapter markers, never a real transcript or a video --
    # see app/platforms/models.py's own ResolvedMeeting.agenda_items
    # comment ("kept separate from segments so they're never mistaken
    # for a real transcript"). A candidate with neither real segments
    # nor a playable video_url is an agenda-only record: never ingested,
    # regardless of how many agenda_items it carries.
    if not segments and not result.video_url:
        return "meeting-without-video"

    effective_title = result.title or ""
    if not effective_title and result.video_url:
        effective_title = await hs.youtube_oembed_title(session, result.video_url) or ""
    high_risk = cand.platform_norm in ENUMERATOR_HIGH_RISK_TITLE_PLATFORMS
    if not hs._looks_like_real_meeting(effective_title, require_allowlist=high_risk):
        return "off-mission"

    adapter_signal = f"{result.jurisdiction or ''} {result.meeting_body or ''}".strip()
    if _state_or_kind_conflict(cand, adapter_signal, "adapter jurisdiction/body"):
        return "wrong-domain-mapping"
    if _state_or_kind_conflict(cand, effective_title, "title"):
        return "wrong-domain-mapping"
    if _title_place_conflict(cand, effective_title):
        return "wrong-domain-mapping"
    if cand.platform_norm in CROSS_BORDER_RISK_PLATFORMS:
        combined = f"{result.jurisdiction or ''} {result.meeting_body or ''} {effective_title or ''}".strip()
        if _cross_border_collision(cand, combined):
            return "wrong-domain-mapping"
    return None


async def process_enumerator_platform(
    session, ledger, cand: Cand, netloc, netloc_source, log_w, pending_w
):
    ok, detail = await check_tenant_identity(session, netloc, cand)
    if not ok:
        log_w.writerow(
            dict(
                gov_id=cand.gov_id,
                group=cand.group,
                platform=cand.platform_norm,
                netloc=netloc,
                netloc_source=netloc_source,
                outcome="skipped",
                reject_reason="wrong-domain-mapping",
                note=detail,
            )
        )
        return

    ledger.upsert_tenant(netloc, cand.platform_norm)
    ledger.set_tenant_gov_id(netloc, cand.gov_id, state_abbr=cand.state.upper() or None)

    try:
        await enumerate_candidates(
            ledger, platforms=[cand.platform_norm], tenant=netloc, mode="thorough"
        )
    except Exception as e:  # noqa: BLE001
        log_w.writerow(
            dict(
                gov_id=cand.gov_id,
                group=cand.group,
                platform=cand.platform_norm,
                netloc=netloc,
                netloc_source=netloc_source,
                outcome="error",
                reject_reason="",
                note=f"enumerate raised: {type(e).__name__}: {e}",
            )
        )
        return

    listed = ledger.conn.execute(
        "SELECT COUNT(*) c FROM candidates WHERE tenant_netloc = ? AND status = 'new'",
        (netloc,),
    ).fetchone()["c"]

    if listed == 0:
        log_w.writerow(
            dict(
                gov_id=cand.gov_id,
                group=cand.group,
                platform=cand.platform_norm,
                netloc=netloc,
                netloc_source=netloc_source,
                outcome="skipped",
                reject_reason="no-meeting-nor-video",
                note="enumerator listed 0 new candidates",
            )
        )
        return

    try:
        await resolve_candidates(
            ledger,
            tenant=netloc,
            limit=MAX_CANDIDATES_TRIED,
            require_captions=False,
            min_tier="blank",
            include_tier3=True,
        )
    except Exception as e:  # noqa: BLE001
        log_w.writerow(
            dict(
                gov_id=cand.gov_id,
                group=cand.group,
                platform=cand.platform_norm,
                netloc=netloc,
                netloc_source=netloc_source,
                outcome="error",
                reject_reason="",
                note=f"resolve raised: {type(e).__name__}: {e}",
            )
        )
        return

    resolved_rows = ledger.conn.execute(
        "SELECT url_normalized, resolved_json FROM candidates "
        "WHERE tenant_netloc = ? AND status = 'resolved_ok' AND resolved_json IS NOT NULL "
        "ORDER BY date DESC",
        (netloc,),
    ).fetchall()

    reject_reasons_seen = []
    for row in resolved_rows:
        payload = json.loads(row["resolved_json"])
        result = ResolvedMeeting(**payload)
        meeting_url = row["url_normalized"]
        reject = await check_candidate(session, cand, result, meeting_url)
        if reject:
            reject_reasons_seen.append(reject)
            continue
        # tier1_2 needs REAL transcript segments, not just agenda_items
        # (see check_candidate's own comment -- agenda_items/agenda_link
        # are never a transcript). check_candidate() above already
        # guarantees segments or video_url is present by this point.
        tier = "tier1_2" if result.segments else "tier3"
        pending_w.writerow(
            dict(
                gov_id=cand.gov_id,
                group=cand.group,
                jurisdiction=cand.jurisdiction,
                platform=cand.platform_norm,
                netloc=netloc,
                title=result.title or "",
                date=result.date or "",
                meeting_body=result.meeting_body or "",
                adapter_jurisdiction=result.jurisdiction or "",
                meeting_url=meeting_url,
                video_url=result.video_url or "",
                source_url=result.source_url or meeting_url,
                segments_count=len(result.segments or []),
                tier=tier,
                decision="",
                decision_note="",
            )
        )
        log_w.writerow(
            dict(
                gov_id=cand.gov_id,
                group=cand.group,
                platform=cand.platform_norm,
                netloc=netloc,
                netloc_source=netloc_source,
                outcome="pending_handread",
                reject_reason="",
                note=f"tier={tier} title={result.title!r}",
            )
        )
        return

    if (
        reject_reasons_seen
        and reject_reasons_seen.count("wrong-domain-mapping")
        >= len(reject_reasons_seen) / 2
    ):
        final_reason = "wrong-domain-mapping"
    elif reject_reasons_seen and all(r == "off-mission" for r in reject_reasons_seen):
        final_reason = "off-mission"
    else:
        final_reason = "no-video-found"
    log_w.writerow(
        dict(
            gov_id=cand.gov_id,
            group=cand.group,
            platform=cand.platform_norm,
            netloc=netloc,
            netloc_source=netloc_source,
            outcome="skipped",
            reject_reason=final_reason,
            note=(
                f"{len(resolved_rows)} resolved candidates, none passed automated "
                f"checks (reasons seen: {collections.Counter(reject_reasons_seen)})"
            ),
        )
    )


async def main_async(args):
    if not SCRATCH_LEDGER.exists():
        import shutil

        shutil.copy2(REAL_LEDGER, SCRATCH_LEDGER)
        print(f"copied {REAL_LEDGER} -> {SCRATCH_LEDGER}")
    ledger = Ledger(str(SCRATCH_LEDGER))

    cands = load_candidates()
    done = _already_done(LOG_CSV)
    todo = [
        c
        for c in cands
        if c.gov_id not in done and c.platform_norm in ENUMERATOR_PLATFORMS
    ]
    skipped_no_enumerator = [
        c
        for c in cands
        if c.gov_id not in done and c.platform_norm not in ENUMERATOR_PLATFORMS
    ]
    if args.limit:
        todo = todo[: args.limit]

    print(
        f"{len(cands)} total candidates; {len(done)} already logged; "
        f"{len(skipped_no_enumerator)} on a platform with no discovery enumerator "
        f"(out of scope for this phase); processing {len(todo)} now."
    )

    log_f, log_w = _log_writer(LOG_CSV)
    pending_f, pending_w = _pending_writer(PENDING_CSV)

    consecutive_errors = 0
    async with aiohttp.ClientSession() as session:
        for i, cand in enumerate(todo):
            print(
                f"[{i + 1}/{len(todo)}] {cand.gov_id} {cand.jurisdiction} ({cand.platform_norm})"
            )
            try:
                netloc, source = derive_netloc(cand)
                if not netloc:
                    # Brief step 1's "one fetch" fallback: find the
                    # tenant on the government's own site.
                    found_netloc, mode, note = await find_tenant_via_homepage(
                        session, cand
                    )
                    if found_netloc:
                        netloc, source = found_netloc, f"homepage-scan({mode})"
                    else:
                        reject = (
                            "platform-tenant-not-found" if not cand.domain else mode
                        )
                        log_w.writerow(
                            dict(
                                gov_id=cand.gov_id,
                                group=cand.group,
                                platform=cand.platform_norm,
                                netloc="",
                                netloc_source="",
                                outcome="skipped",
                                reject_reason=reject or "platform-tenant-not-found",
                                note=note,
                            )
                        )
                        netloc = None
                if netloc:
                    await process_enumerator_platform(
                        session, ledger, cand, netloc, source, log_w, pending_w
                    )
                consecutive_errors = 0
            except Exception as e:  # noqa: BLE001
                log_w.writerow(
                    dict(
                        gov_id=cand.gov_id,
                        group=cand.group,
                        platform=cand.platform_norm,
                        netloc="",
                        netloc_source="",
                        outcome="error",
                        reject_reason="",
                        note=f"unhandled: {type(e).__name__}: {e}",
                    )
                )
                consecutive_errors += 1
            log_f.flush()
            pending_f.flush()
            if consecutive_errors >= 6:
                print("ABORTING: 6 consecutive errors.", file=sys.stderr)
                break

    log_f.close()
    pending_f.close()
    print("done.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    import asyncio

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
