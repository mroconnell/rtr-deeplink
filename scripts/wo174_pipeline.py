"""WO-174: probe `https://{domain}/AgendaCenter` on the ~14,000 governments
WO-127 (BACKLOG_DONE.md §163, ENUMERATION_METHODS.md §163) never touched --
every registry government with no Archive page, a domain, and either
`no-platform-link-found`, `untested`, or a CivicPlus `known_platform` label
(candidates: `~/Documents/rtr-business/research/wo174_candidates.csv`,
14,553 rows) -- then resolve+ingest the real hits through the same pattern
WO-127 used, hardened with three fixes that landed after WO-127 shipped:
WO-133's stricter AgendaCenter marker (a bare "agendacenter" substring is
not proof -- see that script's own docstring on the Plain City, UT Facebook
false positive), WO-145/WO-146's wrong-government content check (a same-
named different government, or a different KIND of government sharing a
name, can sit behind a resolved video with no other signal to catch it),
and WO-169's probe-then-try-next-candidate loop (a rejected video must not
drop the whole government when other real candidates are sitting right
there).

Detection step reuses WO-127's own probe rule verbatim (see
`_probe_agendacenter()`'s docstring below) -- this file does not redesign
that rule, only re-points it at a new candidate list and a stricter
politeness schedule (sequential, not WO-127's own concurrency=15/chunk=100:
this WO's own Rules section asks for one government at a time, 2s between
requests to one host, 1.5s between governments). Resolve step reuses
`scripts/hub_sweep_wo126.py`'s `civicplus_walk()` -- the actual
`UpdateCategoryList` year-fragment walker (governing body first, newest
year first, budget-limited) -- rather than `wo127_civicplus_pipeline.py`'s
own simpler `finder.resolve()` call, which only reads the AgendaCenter
root page's current-year rows and can't see a video that only shows up in
an older year or a different category. (The WO-174 brief attributes this
walk to wo127_civicplus_pipeline.py; it actually lives in hub_sweep_wo126.py
-- corrected here per CLAUDE.md's "verify a brief's claims against the
code" rule, not silently.)

Run from rtr-deeplink repo root with the shared venv active:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo174_scratch.db" \
        .venv/bin/python scripts/wo174_pipeline.py [--limit N] [--dry-run]

ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN come from .env via cwd-walk (see
CLAUDE.md's worktree bullet -- confirmed pointed at production before
running for real). DATABASE_URL is set explicitly and unused by this
script (no `archive` import), only set because some transitively-imported
module may probe for it.

Resumable: REPORT_CSV is flushed after every government (one row each, per
the WO-174 spec), and a completed gov_id (any non-empty `outcome`) is
skipped on restart. `jurisdiction_coverage.csv` is updated per-government
via the existing §158 write protocol (imported from
wo127_civicplus_pipeline.py, unchanged), batched implicitly since every
write already re-locks/re-reads/re-writes safely; this script also prints a
batch marker every ~500 governments per the WO-174 brief.
"""

import argparse
import asyncio
import csv
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms import queue_probe  # noqa: E402
from app.platforms.base import (  # noqa: E402
    resolve_via_platform,
)
from app.platforms.civicplus import CivicPlusAssetFinder  # noqa: E402
from app.platforms.vimeo import parse_vimeo_video  # noqa: E402
from app.platforms.youtube import YouTubeAssetFinder  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402,F401

import hub_sweep_wo126 as hsw  # noqa: E402
from adhoc_civicplus_pipeline import homepage_civicclerk_fallback  # noqa: E402
from bulk_ingest import (  # noqa: E402
    IngestGateRejected,
    _ingest,
)
from wo127_civicplus_pipeline import (  # noqa: E402
    _safe_coverage_call,
    update_coverage_calendar_confirmed,
    update_coverage_on_success,
    update_coverage_reject_reason,
)
from wo146_api_relist_sweep import _looks_wrong_government  # noqa: E402

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
CANDIDATES_CSV = RESEARCH_DIR / "wo174_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo174_report.csv"
HITS_CSV = RESEARCH_DIR / "wo174_civicplus_hits.csv"
SEEDS_CSV = RESEARCH_DIR / "wo174_discovery_seeds.csv"
# Own staged-pins file -- deliberately NOT hub_sweep_wo126.PINS_CSV, which
# is a shared rtr-business/research file other parallel sessions' sweeps
# also stage into; a second writer racing that file has the exact same
# corruption shape ENUMERATION_METHODS.md §158 documents for
# jurisdiction_coverage.csv. tenant_overrides.csv itself lives inside this
# worktree's own rtr-deeplink checkout, so it needs no cross-process lock
# (conflicts, if any, are resolved as a normal git merge at PR time).
PINS_STAGED_CSV = RESEARCH_DIR / "wo174_pins_staged.csv"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)
QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"

SKIP_PRIOR_REASONS = {"no-video-found", "off-mission"}

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "domain",
    "probe_status",
    "agendacenter_hit",
    "vendor_hint",
    "access_mode",
    "outcome",
    "reject_reason",
    "reject_class",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]

# --------------------------------------------------------------------------
# Politeness (WO-174's own Rules section -- stricter than WO-127's own
# probe script, which used concurrency=15/chunk=100; this run is
# sequential, one government at a time)
# --------------------------------------------------------------------------

HOST_RETRY_DELAY = 2.0  # between repeated requests to the SAME host
GOV_DELAY = 1.5  # between governments
CONSECUTIVE_ERROR_HALT = 6
PROBE_TIMEOUT = aiohttp.ClientTimeout(total=15)
DETECT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
DETECT_HEADERS = {"User-Agent": DETECT_USER_AGENT}
# hub_sweep_wo126's own Fetcher sleeps REQUEST_DELAY_SECONDS between its
# own fetches (root page already fetched by us -- the walk only spends
# this on UpdateCategoryList fragments) -- bumped from that module's 1.5s
# default to this WO's own 2s "same host" rule; a module-level override,
# not a fork, so the walk's own fetch/budget/cloudflare logic is reused
# unchanged.
hsw.REQUEST_DELAY_SECONDS = HOST_RETRY_DELAY
PER_GOV_FRAGMENT_BUDGET = hsw.PER_GOV_FETCH_BUDGET

DRY_RUN = os.environ.get("DRY_RUN") == "1"

# Cloudflare "prove you're human" markers -- same list
# hub_sweep_wo126.py/wo146_api_relist_sweep.py already use; a hit here
# means stop, never retry (CLAUDE.md's "politely" bullet).
_CHALLENGE_MARKERS = hsw._CLOUDFLARE_CHALLENGE_MARKERS

_YT_HOSTS = ("youtube.com", "youtu.be")
_SHARED_HOST_PLATFORMS = ("youtube", "vimeo", "viebit", "telvue", "cablecast")
# Hosts that are genuinely one shared server for many tenants (need a
# match= key); every other host on these platforms is a per-tenant
# subdomain and gets a bare host pin, same convention
# tenant_overrides.csv already uses throughout (see e.g. artesiaca.
# cablecast.tv vs the shared videoplayer.telvue.com rows).
_GENUINELY_SHARED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "vimeo.com",
    "player.vimeo.com",
    "videoplayer.telvue.com",
    "livestream.telvue.com",
}

_BARE_YOUTUBE_CHANNEL_RE = re.compile(r"youtube\.com|youtu\.be")
_SPECIFIC_YOUTUBE_VIDEO_RE = re.compile(r"(watch\?v=|youtu\.be/|/embed/|/shorts/)")


def slugify_name(name: str) -> str:
    low = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return low


def normalize_domain(raw: str) -> str:
    """The candidates CSV's own `domain` column is not always a bare
    host -- confirmed live: 4,769 of 14,553 rows (about a third) carry a
    full URL with scheme and/or a trailing path/slash instead (e.g.
    "https://www.fairfaxcounty.gov/"), which a bare `f"https://{domain}/
    AgendaCenter"` concatenation turns into a nonsense URL that always
    dead-ends. Strips a leading scheme and everything from the first `/`
    onward, leaving just the host -- `www.` is left alone (WO-127's own
    `variants_for()` already tries a `www.` variant separately when the
    host doesn't already start with it)."""
    d = (raw or "").strip()
    d = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", d)
    d = d.split("/", 1)[0]
    d = d.split("?", 1)[0]
    return d.strip().rstrip(".")


# --------------------------------------------------------------------------
# Detection: WO-127's own rule, reused verbatim + WO-133's strict reverify
# --------------------------------------------------------------------------


def is_civicplus_hit(final_url: str, body: str) -> bool:
    """WO-127's exact rule (coverage_gap_2026-09-09/
    wo127_civicplus_owndomain_probe.py `_try_one()`): the final URL's own
    host contains civicplus.com, OR the raw (not lowercased) HTML contains
    the literal `catAgendaRow` marker -- never a bare HTTP 200."""
    return "civicplus.com" in final_url.lower() or "catAgendaRow" in body


def strict_reverify_ok(body: str) -> bool:
    """WO-133's stricter re-check (wo133_agendacenter_strict_reverify.py
    `is_real_hit()`): requires BOTH "civicplus" and "agendacenter" as
    substrings anywhere on the page. Built after a real false positive
    (Plain City, UT -- a Facebook page whose own vanity URL is
    "agendacenter") slipped past a looser bare-word check. Applied here as
    a second gate on top of `is_civicplus_hit()`, per this WO's brief."""
    low = (body or "").lower()
    return "civicplus" in low and "agendacenter" in low


def has_civicplus_footer_hint(body: str) -> bool:
    return "government websites by civicplus" in (body or "").lower()


async def _one_get(session, url):
    """Returns (ok, final_url, status, body, error_detail). ok=False is a
    connection-level failure only."""
    try:
        async with session.get(
            url, allow_redirects=True, timeout=PROBE_TIMEOUT, headers=DETECT_HEADERS
        ) as resp:
            final_url = str(resp.url)
            status = resp.status
            body = await resp.text(errors="replace")
            return True, final_url, status, body, None
    except Exception as e:
        return False, None, None, "", repr(e)[:200]


async def probe_agendacenter(session, domain: str):
    """One GET to https://{domain}/AgendaCenter; a www./http:// variant
    only on a connection-level failure (WO-127's own rule -- a clean
    non-CivicPlus response is accepted after one request, never retried).
    Returns a dict: access_mode, agendacenter_hit, final_url, body (of the
    LAST real response received, for the vendor-hint check), detail."""
    variants = [f"https://{domain}/AgendaCenter"]
    if not domain.startswith("www."):
        variants.append(f"https://www.{domain}/AgendaCenter")
    variants.append(f"http://{domain}/AgendaCenter")

    last_detail = None
    for i, url in enumerate(variants):
        if i > 0:
            await asyncio.sleep(HOST_RETRY_DELAY)
        ok, final_url, status, body, detail = await _one_get(session, url)
        if not ok:
            last_detail = detail
            continue

        if any(m in body[:4000].lower() for m in _CHALLENGE_MARKERS) or (
            status in (403, 503) and "cloudflare" in body.lower()[:6000]
        ):
            return {
                "access_mode": "challenge",
                "agendacenter_hit": "no",
                "final_url": final_url,
                "url_tried": url,
                "body": "",
                "detail": "cloudflare-challenge-blocked",
            }

        hit = is_civicplus_hit(final_url, body)
        if hit and not strict_reverify_ok(body):
            return {
                "access_mode": "plain",
                "agendacenter_hit": "false-positive",
                "final_url": final_url,
                "url_tried": url,
                "body": body,
                "detail": (
                    "WO-127 rule matched but WO-133 strict reverify "
                    "failed (no 'civicplus'+'agendacenter' pair)"
                ),
            }
        return {
            "access_mode": "plain",
            "agendacenter_hit": "yes" if hit else "no",
            "final_url": final_url,
            "url_tried": url,
            "body": body,
            "detail": f"HTTP {status}",
        }

    # every variant failed at the connection level
    reason = (last_detail or "").lower()
    if "timeout" in reason or "timed out" in reason:
        access_mode = "dead"
    elif any(
        s in reason
        for s in ("nodename nor servname", "name or service not known", "getaddrinfo")
    ):
        access_mode = "dead"
    else:
        access_mode = "dead"
    return {
        "access_mode": access_mode,
        "agendacenter_hit": "no",
        "final_url": None,
        "url_tried": variants[0],
        "body": "",
        "detail": last_detail or "all variants failed to connect",
    }


async def try_vendor_hint_subdomain(session, name: str, state: str):
    """WO-168's rule: a CivicPlus footer with no working /AgendaCenter on
    the government's own domain -- try the tenant subdomain shape once,
    then stop regardless of the result."""
    st = (state or "").strip().lower()
    slug = slugify_name(name or "")
    if not st or not slug:
        return None
    url = f"https://{st}-{slug}.civicplus.com/AgendaCenter"
    ok, final_url, status, body, detail = await _one_get(session, url)
    if not ok:
        return {"hit": False, "url": url, "detail": detail}
    hit = is_civicplus_hit(final_url, body) and strict_reverify_ok(body)
    return {
        "hit": hit,
        "url": url,
        "final_url": final_url,
        "body": body,
        "detail": f"HTTP {status}",
    }


# --------------------------------------------------------------------------
# Already-covered gov_ids (fresh export, per the WO-174 brief step 3)
# --------------------------------------------------------------------------


def fetch_covered_gov_ids() -> set:
    """Same endpoint/pagination contract as export_meeting_inventory.py's
    `fetch_rows_via_export()`: GET /internal/export/pages?after_id=&limit=,
    body {"pages": [...], "next_after_id": int|None}, each page carrying
    its own `gov_id` (archive/utils/meeting_inventory.py's `inventory_row()`
    reads it the same way)."""
    import json

    base = os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    if not base or not token:
        print(
            "[WARN] ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN not set -- "
            "cannot check already_covered, treating none as covered"
        )
        return set()
    covered = set()
    after_id = 0
    while True:
        url = f"{base}/internal/export/pages?after_id={after_id}&limit=500"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        rows = payload.get("pages") or []
        for row in rows:
            gid = row.get("gov_id")
            if gid:
                covered.add(gid)
        next_after_id = payload.get("next_after_id")
        if next_after_id is None:
            break
        after_id = next_after_id
        time.sleep(0.2)
    return covered


# --------------------------------------------------------------------------
# Pins (tenant_overrides.csv) -- own staging file, merged at the end
# --------------------------------------------------------------------------


def derive_pin(
    gov_id: str,
    name: str,
    state: str,
    source_url: str,
    video_url: str,
    platform: str,
    agendacenter_url: str,
):
    if platform not in _SHARED_HOST_PLATFORMS:
        return None
    host = urlparse(video_url or source_url).netloc.lower()
    match = ""
    if host in _GENUINELY_SHARED_HOSTS or platform == "youtube":
        if platform == "youtube":
            vid = YouTubeAssetFinder.extract_video_id(video_url or source_url)
            if not vid:
                return None
            host = "www.youtube.com"
            match = vid
        elif platform == "vimeo":
            parsed = parse_vimeo_video(video_url or source_url)
            if not parsed:
                return None
            host = "vimeo.com"
            match = parsed[0]
        elif host in ("videoplayer.telvue.com", "livestream.telvue.com"):
            # per-page token: the last non-empty path segment before any
            # query string, same shape existing videoplayer.telvue.com
            # rows use.
            path_parts = [
                p for p in urlparse(video_url or source_url).path.split("/") if p
            ]
            match = path_parts[-1] if path_parts else ""
    if not host:
        return None
    return {
        "tenant_host": host,
        "match": match,
        "gov_id": gov_id,
        "strength": "fallback",
        "source": "wo174_agendacenter_probe",
        "evidence": (
            f"coverage registry row {gov_id} ({name}, {state}); "
            f"hub {agendacenter_url}; meeting found via {platform} at {source_url}"
        ),
    }


def stage_pin(pin: dict):
    if not pin or DRY_RUN:
        return
    is_new = not PINS_STAGED_CSV.exists()
    with PINS_STAGED_CSV.open("a", newline="", encoding="utf-8") as f:
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
        )
        if is_new:
            w.writeheader()
        w.writerow(pin)


def merge_pins_into_tenant_overrides() -> int:
    """Dedup-append PINS_STAGED_CSV into TENANT_OVERRIDES_CSV (per-worktree
    file -- see PINS_STAGED_CSV's own comment on why no cross-process lock
    is needed here). Safe to call repeatedly / at the end of a partial
    run.

    Deliberately APPENDS new rows rather than re-sorting the whole file
    (hub_sweep_wo126.py's own `write_pins()` re-sorts on every write,
    which this function originally copied) -- confirmed live 2026-09-10:
    that re-sort touched 4,135 of the file's ~4,136 lines for a single
    real new pin, because the file's existing order wasn't already
    alphabetical. A diff that size makes real review impossible and is a
    guaranteed merge conflict with any other parallel WO's own pin, for
    zero functional benefit -- `tenant_overrides.csv`'s own loader reads
    the whole file into a dict keyed by host regardless of row order."""
    if not PINS_STAGED_CSV.exists():
        return 0
    with PINS_STAGED_CSV.open(newline="", encoding="utf-8") as f:
        staged = list(csv.DictReader(f))
    with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        existing = list(reader)
    have = {(r["tenant_host"].lower(), r.get("match") or "") for r in existing}
    new_rows = []
    for p in staged:
        key = (p["tenant_host"].lower(), p.get("match") or "")
        if key in have:
            continue
        have.add(key)
        new_rows.append({k: p.get(k, "") for k in fields})
    if not new_rows:
        print(f"[PINS] 0 new pin(s) ({len(staged)} staged, all already present)")
        return 0
    with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writerows(new_rows)
    print(
        f"[PINS] {len(new_rows)} pin(s) appended to {TENANT_OVERRIDES_CSV} ({len(staged)} staged)"
    )
    return len(new_rows)


# --------------------------------------------------------------------------
# Report / hits / seeds writers
# --------------------------------------------------------------------------


class ReportWriter:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        self._f = path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._f, fieldnames=REPORT_FIELDS)
        if write_header:
            self._writer.writeheader()
            self._f.flush()

    def write(self, row):
        out = {f: row.get(f, "") for f in REPORT_FIELDS}
        self._writer.writerow(out)
        self._f.flush()

    def close(self):
        self._f.close()


def append_csv_row(path: Path, fieldnames, row: dict):
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fieldnames})


def load_done_gov_ids(path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {
            r["gov_id"] for r in csv.DictReader(f) if (r.get("outcome") or "").strip()
        }


# --------------------------------------------------------------------------
# Per-government processing
# --------------------------------------------------------------------------

_youtube_block_signature_seen = False
_hits_written: set = set()
_queue_urls: set = set()


def load_hits_written(path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def load_queue_urls(path) -> set:
    """The bare video URL half of every existing tier-3 queue line (a
    line is `URL` or `URL<TAB>SOURCE_URL` -- see
    tests/test_transcription_queue_files.py's `_rows()` for the same
    split). Real, confirmed-live incident this guards against
    (2026-09-10): Pierce County, WA's own AgendaCenter delegated to
    `vimeo.com/707985726`, a video an EARLIER, unrelated sweep had
    already queued for the same government before this WO's own
    candidate snapshot was taken -- `wo174_candidates.csv`'s
    `duplicate-queued` prior_reason category exists for exactly this
    case but didn't catch this one row, and `tests/
    test_transcription_queue_files.py::test_no_duplicate_rows` failed on
    the resulting duplicate line. Loaded once at startup and updated as
    this run queues its own URLs, so a later candidate that resolves to
    an already-queued video is caught before it's appended again."""
    if not path.exists():
        return set()
    urls = set()
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line:
            urls.add(line.split("\t", 1)[0])
    return urls


def _youtube_looks_blocked(result) -> bool:
    warnings = " ".join(getattr(result, "transcript_warnings", None) or [])
    return "429" in warnings or "too many requests" in warnings.lower()


async def resolve_candidate(session, row, agendacenter_url):
    """Try `row['url']` (a real delegated video link found by
    civicplus_walk / homepage fallback) through the real adapter, apply
    the known-jurisdiction pin and the bare-YouTube-channel guard (both
    from wo127_civicplus_pipeline.py, unchanged logic), and probe it via
    queue_probe before it's allowed to count as a real candidate. Returns
    (result_or_None, reject_note)."""
    global _youtube_block_signature_seen
    url = row["url"]

    if _youtube_block_signature_seen and _BARE_YOUTUBE_CHANNEL_RE.search(url or ""):
        # Today's constraint (docs/investigations/youtube_429_block.md):
        # a sustained block already confirmed once this run -- treat every
        # further YouTube delegation as tier-3 straight away rather than
        # re-running a doomed local caption fetch, per this WO's brief.
        vid = YouTubeAssetFinder.extract_video_id(url)
        if not vid:
            return None, "youtube blocked and no video id parseable"
        try:
            info = await asyncio.to_thread(queue_probe._yt_dlp_probe, vid)
        except Exception as e:
            return None, f"youtube metadata probe failed: {e}"
        if not info or info.get("duration") is None:
            return None, "youtube metadata probe returned nothing (dead/blocked)"

        class _Stub:
            pass

        result = _Stub()
        result.platform = "youtube"
        result.video_url = f"https://www.youtube.com/watch?v={vid}"
        result.segments = []
        result.agenda_items = []
        result.jurisdiction = None
        result.meeting_body = row.get("body") or ""
        result.title = row.get("title") or ""
        result.date = row.get("date") or None
        result.agenda_link = row.get("agenda_link")
        result.packet_link = row.get("packet_link")
        result.source_url = url
        result.transcript_warnings = [
            "youtube-block-signature: treated as tier-3 directly"
        ]
        return result, None

    try:
        result = await resolve_via_platform(url)
    except Exception as e:
        return None, f"resolve raised: {e}"

    result.agenda_link = result.agenda_link or row.get("agenda_link")
    result.packet_link = result.packet_link or row.get("packet_link")
    result.title = result.title or row.get("title")
    result.date = result.date or row.get("date")

    if getattr(result, "platform", None) == "youtube" and not result.segments:
        if _youtube_looks_blocked(result):
            _youtube_block_signature_seen = True

    if _BARE_YOUTUBE_CHANNEL_RE.search(
        result.video_url or ""
    ) and not _SPECIFIC_YOUTUBE_VIDEO_RE.search(result.video_url or ""):
        # WO-138 guard, reused verbatim: a bare channel/handle/streams
        # listing link is not this meeting's video.
        result.video_url = ""

    if not result.video_url:
        return None, "resolved but no video_url"

    return result, None


# `classify_video_hand_check()` (the WO-191 phrase-list hand check) moved to
# `app/utils/video_hand_check.py` in WO-227 (2026-09-11) so `app/platforms/
# boxcast.py` can reuse the same phrase list without `app/` depending on
# `scripts/` -- see that module's own docstring for the full history. Still
# imported above as `classify_video_hand_check`, so every caller below (and
# every other script/test that imports it off this module) is unaffected.

HAND_CHECK_FLAGS_CSV = RESEARCH_DIR / "wo174_hand_check_flags.csv"
_HAND_CHECK_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "kind",
    "reason",
    "title",
    "video_url",
    "meeting_url",
]


def record_hand_check_flag(
    gov_id, name, state, gov_kind, kind, reason, title, video_url, meeting_url
):
    """Append-only sidecar, separate from REPORT_CSV so the shared
    report file's existing column schema (already 1,449 rows written by
    the first WO-174 session) never needs to change -- see this WO's
    own `RESEARCH_DIR` file list for the same pattern (`wo174_civicplus_
    hits.csv`, `wo174_discovery_seeds.csv`, etc. are all separate,
    append-only files rather than extra REPORT_CSV columns)."""
    append_csv_row(
        HAND_CHECK_FLAGS_CSV,
        _HAND_CHECK_FIELDS,
        {
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "gov_kind": gov_kind,
            "kind": kind,
            "reason": reason,
            "title": title or "",
            "video_url": video_url or "",
            "meeting_url": meeting_url or "",
        },
    )


async def process_government(
    session, cand, report: ReportWriter, covered_ids: set
) -> str:
    """Returns 'ok' | 'connect-error' for the caller's consecutive-error
    counter."""
    gov_id = cand["gov_id"]
    name = cand["name"]
    state = cand["state"]
    gov_kind = (cand.get("gov_kind") or "").strip().lower()
    population = cand.get("population") or ""
    domain = normalize_domain(cand.get("domain") or "")

    row = {f: "" for f in REPORT_FIELDS}
    row.update(
        gov_id=gov_id,
        name=name,
        state=state,
        gov_kind=gov_kind,
        population=population,
        domain=domain,
    )

    if gov_id in covered_ids:
        row.update(outcome="already_covered", probe_status="skipped")
        report.write(row)
        return "ok"

    if not domain:
        row.update(outcome="error", note="empty domain")
        report.write(row)
        return "ok"

    probe = await probe_agendacenter(session, domain)
    row["access_mode"] = probe["access_mode"]
    row["agendacenter_hit"] = probe["agendacenter_hit"]
    row["probe_status"] = "done"

    if probe["access_mode"] == "challenge":
        row.update(
            outcome="blocked",
            reject_reason="cloudflare-challenge-blocked",
            reject_class="access",
            note=probe["detail"],
        )
        report.write(row)
        return "ok"

    if probe["access_mode"] == "dead":
        row.update(outcome="dead", note=probe["detail"])
        report.write(row)
        return "connect-error"

    agendacenter_url = probe["url_tried"]
    body = probe["body"]

    if probe["agendacenter_hit"] == "false-positive":
        row.update(outcome="no_agendacenter", note=probe["detail"])
        report.write(row)
        await asyncio.sleep(GOV_DELAY)
        return "ok"

    if probe["agendacenter_hit"] == "no":
        if has_civicplus_footer_hint(body):
            row["vendor_hint"] = "civicplus"
            vendor_try = await try_vendor_hint_subdomain(session, name, state)
            if vendor_try and vendor_try.get("hit"):
                agendacenter_url = vendor_try["url"]
                body = vendor_try["body"]
                row["agendacenter_hit"] = "yes"
                row["domain"] = urlparse(vendor_try["final_url"]).netloc
            else:
                row.update(
                    outcome="no_agendacenter",
                    note="vendor hint tried, no real AgendaCenter found",
                )
                report.write(row)
                await asyncio.sleep(GOV_DELAY)
                return "ok"
        else:
            row.update(outcome="no_agendacenter", note=probe["detail"])
            report.write(row)
            await asyncio.sleep(GOV_DELAY)
            return "ok"

    # Real AgendaCenter hit confirmed -- record it in the hits CSV (WO-127
    # shape: gov_id, unit_name, web_address) and the discovery seeds file
    # regardless of what the resolve step below finds. Guarded against
    # re-appending on a resume (a crash between this write and the final
    # REPORT_CSV row would otherwise reprocess this gov_id and duplicate
    # both rows -- _hits_written tracks what's already on disk, loaded
    # once at startup).
    unit_name = f"{name}, {state}"
    host_for_hits = urlparse(agendacenter_url).netloc
    if gov_id not in _hits_written:
        append_csv_row(
            HITS_CSV,
            ["gov_id", "unit_name", "web_address"],
            {"gov_id": gov_id, "unit_name": unit_name, "web_address": host_for_hits},
        )
        append_csv_row(
            SEEDS_CSV,
            ["netloc", "platform", "gov_id", "access_mode"],
            {
                "netloc": host_for_hits,
                "platform": "civicplus",
                "gov_id": gov_id,
                "access_mode": row["access_mode"],
            },
        )
        _hits_written.add(gov_id)

    finder = CivicPlusAssetFinder()
    fetcher = hsw.Fetcher(session, budget=PER_GOV_FRAGMENT_BUDGET)
    try:
        rows, fragments, note = await hsw.civicplus_walk(
            fetcher, agendacenter_url, body, finder
        )
    except hsw.FetchError as e:
        if e.kind == "cloudflare":
            row.update(
                outcome="blocked",
                reject_reason="cloudflare-challenge-blocked",
                reject_class="access",
                note=str(e),
            )
        elif e.kind == "dns":
            row.update(outcome="dead", note=str(e))
        else:
            row.update(outcome="error", note=str(e))
        report.write(row)
        return "ok" if e.kind != "network" else "connect-error"

    video_rows = [r for r in rows if r.get("url")]

    if not rows:
        # AgendaCenter walk (root + fragments) found no real (title+date)
        # rows at all -- try WO-138's homepage-CivicClerk fallback before
        # giving up, same as wo127_civicplus_pipeline.py.
        fallback_url, fallback_reason = await homepage_civicclerk_fallback(
            session, urlparse(agendacenter_url).netloc.replace("www.", "")
        )
        if not fallback_url:
            row.update(
                outcome="no_meeting_nor_video",
                reject_reason="no-meeting-nor-video",
                reject_class="content",
                meeting_url=agendacenter_url,
                note=f"{fragments} fragment(s) walked, no candidates; homepage fallback: {fallback_reason}",
            )
            report.write(row)
            if not DRY_RUN:
                _safe_coverage_call(
                    update_coverage_reject_reason, gov_id, "no-meeting-nor-video"
                )
                _safe_coverage_call(
                    update_coverage_calendar_confirmed, gov_id, agendacenter_url
                )
            await asyncio.sleep(GOV_DELAY)
            return "ok"
        video_rows = [
            {
                "url": fallback_url,
                "title": "",
                "date": "",
                "agenda_link": None,
                "packet_link": None,
                "body": "",
            }
        ]

    if not video_rows:
        row.update(
            outcome="meeting_without_video",
            reject_reason="meeting-without-video",
            reject_class="content",
            meeting_url=agendacenter_url,
            note=f"{len(rows)} real listing row(s), {fragments} fragment(s) walked, none had video ({note})",
        )
        report.write(row)
        if not DRY_RUN:
            _safe_coverage_call(
                update_coverage_reject_reason, gov_id, "meeting-without-video"
            )
            _safe_coverage_call(
                update_coverage_calendar_confirmed, gov_id, agendacenter_url
            )
        await asyncio.sleep(GOV_DELAY)
        return "ok"

    chosen = None
    any_had_video_url = False
    reject_notes = []
    for cand_row in video_rows:
        result, note2 = await resolve_candidate(session, cand_row, agendacenter_url)
        if result is None:
            if note2:
                reject_notes.append(note2)
            continue
        any_had_video_url = True

        wrong = _looks_wrong_government(
            {
                "state": state,
                "gov_kind": "municipality" if gov_kind == "township" else gov_kind,
            },
            {
                "jurisdiction": result.jurisdiction or "",
                "meeting_body": getattr(result, "meeting_body", "") or "",
                "title": result.title or "",
            },
        )
        if wrong:
            reject_notes.append(f"wrong-government: {wrong}")
            continue

        hand_check_channel_text = " ".join(
            filter(
                None,
                [
                    (getattr(result, "video_channel", None) or "").lstrip("@"),
                    result.jurisdiction or "",
                ],
            )
        )
        hand_check = classify_video_hand_check(
            result.title, hand_check_channel_text, unit_name, gov_kind
        )
        if hand_check:
            kind, reason = hand_check
            reject_notes.append(f"hand-check-kind-{kind.lower()}: {reason}")
            record_hand_check_flag(
                gov_id,
                name,
                state,
                gov_kind,
                kind,
                reason,
                result.title,
                result.video_url,
                cand_row["url"],
            )
            continue

        meeting_url = cand_row["url"]
        tier = "tier1" if result.segments else "tier3"
        if tier == "tier3" and meeting_url in _queue_urls:
            reject_notes.append(
                "already queued (duplicate of an existing tier3 queue line)"
            )
            continue
        if tier == "tier3":
            probe_result = await queue_probe.probe_queue_entry(
                meeting_url,
                video_url=result.video_url,
                source_page_url=agendacenter_url,
                platform=result.platform,
            )
            queue_probe.append_probe_row(
                queue_probe.DEFAULT_SIDECAR_PATH, probe_result, caller="wo174"
            )
            if probe_result.verdict.startswith("reject-"):
                reject_notes.append(
                    f"probe rejected: {probe_result.verdict} ({probe_result.reason})"
                )
                continue

        # Known-jurisdiction pin: the registry's own name wins outright
        # (wo127_civicplus_pipeline.py's rule, unchanged).
        result.jurisdiction = unit_name
        chosen = (result, meeting_url, tier)
        break

    if chosen is None:
        # "wrong-government" (WO-145/146's own check) and "hand-check-
        # kind-a" (this WO's own addition, above) are the same underlying
        # finding -- a real video that belongs to a different,
        # identifiable body -- so they fold into the same outcome bucket.
        all_wrong_gov = bool(reject_notes) and all(
            "wrong-government" in n or "hand-check-kind-a" in n for n in reject_notes
        )
        any_hand_check_b = any("hand-check-kind-b" in n for n in reject_notes)
        if all_wrong_gov:
            row.update(
                outcome="wrong_domain_mapping",
                reject_reason="wrong-domain-mapping",
                reject_class="content",
                meeting_url=agendacenter_url,
                note="; ".join(reject_notes)[:500],
            )
        elif any_hand_check_b:
            # Distinct from the generic "rejected_by_probe" bucket below
            # so a report can count hand-check catches on their own (this
            # WO's own brief asks for a Kind A/Kind B split) -- reached
            # only when every video candidate this government offered was
            # rejected, at least one of them by the Kind B check.
            row.update(
                outcome="off_mission_hand_check",
                # Canonical reject_reason string used across every other
                # sweep in this repo (see CONTENT_STOP_REASONS in
                # wo151_research_url_ladder_sweep.py and the many
                # `base["reject_reason"] = "off-mission"` sites) --
                # matching it, rather than inventing a new string, is
                # what lets SKIP_PRIOR_REASONS above (and any future
                # candidate rebuild) correctly skip this government
                # again rather than re-probing it.
                reject_reason="off-mission",
                reject_class="content",
                meeting_url=agendacenter_url,
                note="; ".join(reject_notes)[:500],
            )
        elif any_had_video_url:
            row.update(
                outcome="rejected_by_probe",
                reject_reason="",
                reject_class="content",
                meeting_url=agendacenter_url,
                note="; ".join(reject_notes)[:500],
            )
        else:
            row.update(
                outcome="meeting_without_video",
                reject_reason="meeting-without-video",
                reject_class="content",
                meeting_url=agendacenter_url,
                note="; ".join(reject_notes)[:500]
                or "no candidate resolved to a real video",
            )
        report.write(row)
        if not DRY_RUN:
            if row["outcome"] == "meeting_without_video":
                _safe_coverage_call(
                    update_coverage_reject_reason, gov_id, "meeting-without-video"
                )
                _safe_coverage_call(
                    update_coverage_calendar_confirmed, gov_id, agendacenter_url
                )
            elif row["outcome"] == "wrong_domain_mapping":
                _safe_coverage_call(
                    update_coverage_reject_reason, gov_id, "wrong-domain-mapping"
                )
            elif row["outcome"] == "off_mission_hand_check":
                _safe_coverage_call(
                    update_coverage_reject_reason, gov_id, "off-mission"
                )
        await asyncio.sleep(GOV_DELAY)
        return "ok"

    result, meeting_url, tier = chosen
    row["meeting_url"] = meeting_url
    row["video_url"] = result.video_url or ""
    row["tier"] = tier

    normalized = normalize_url(meeting_url)
    if DRY_RUN:
        row.update(outcome=f"dry-run-{tier}")
        report.write(row)
        await asyncio.sleep(GOV_DELAY)
        return "ok"

    if tier == "tier1":
        try:
            response = await _ingest(
                session,
                result.model_dump(),
                normalized,
                already_probed=False,
                caller="wo174",
            )
            page_url = response.get("url") if response else None
            row.update(outcome="ingested_tier1_2", page_url=page_url or "")
            _safe_coverage_call(
                update_coverage_on_success,
                gov_id,
                shares_video=True,
                transcribed=True,
                example_meeting_url=page_url or meeting_url,
                agendacenter_url=agendacenter_url,
                video_platform=result.platform or "",
            )
        except IngestGateRejected as e:
            row.update(outcome="rejected_by_probe", note=str(e)[:500])
        except Exception as e:
            row.update(outcome="error", note=f"ingest raised: {e}"[:500])
    else:
        with QUEUE_FILE.open("a") as qf:
            qf.write(meeting_url + "\n")
        _queue_urls.add(meeting_url)
        row.update(outcome="queued_tier3")
        _safe_coverage_call(
            update_coverage_on_success,
            gov_id,
            shares_video=True,
            transcribed=False,
            example_meeting_url=meeting_url,
            agendacenter_url=agendacenter_url,
            video_platform=result.platform or "",
        )

    if row["outcome"] in ("ingested_tier1_2", "queued_tier3"):
        pin = derive_pin(
            gov_id,
            name,
            state,
            meeting_url,
            result.video_url,
            result.platform or "",
            agendacenter_url,
        )
        stage_pin(pin)

    report.write(row)
    await asyncio.sleep(GOV_DELAY)
    return "ok"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


async def main():
    global DRY_RUN, REPORT_CSV
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--candidates", type=Path, default=CANDIDATES_CSV)
    ap.add_argument("--report", type=Path, default=REPORT_CSV)
    ap.add_argument(
        "--skip-covered-fetch",
        action="store_true",
        help="pilot/test convenience: skip the live already-covered export call",
    )
    args = ap.parse_args()
    DRY_RUN = DRY_RUN or args.dry_run
    REPORT_CSV = args.report

    register_all_finders()

    global _hits_written, _queue_urls
    _hits_written = load_hits_written(HITS_CSV)
    _queue_urls = load_queue_urls(QUEUE_FILE)

    with args.candidates.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    candidates = [
        r for r in all_rows if (r.get("prior_reason") or "") not in SKIP_PRIOR_REASONS
    ]
    print(
        f"{len(all_rows)} total candidates, {len(candidates)} after skipping no-video-found/off-mission"
    )

    done = load_done_gov_ids(REPORT_CSV)
    todo = [c for c in candidates if c["gov_id"] not in done]
    print(f"{len(done)} already processed, {len(todo)} to go")

    if args.limit:
        todo = todo[: args.limit]
        print(f"--limit {args.limit}: processing {len(todo)} this run")

    if args.skip_covered_fetch:
        covered_ids = set()
    else:
        print("fetching already-covered gov_ids from a fresh export...")
        covered_ids = fetch_covered_gov_ids()
        print(f"{len(covered_ids)} gov_ids already have an Archive page")

    report = ReportWriter(REPORT_CSV)
    consecutive_errors = 0
    processed_this_run = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(todo):
                status = await process_government(session, cand, report, covered_ids)
                processed_this_run += 1
                if status == "connect-error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= CONSECUTIVE_ERROR_HALT:
                    print(
                        f"[HALT] {CONSECUTIVE_ERROR_HALT} consecutive connect errors -- "
                        f"stopping after {processed_this_run} this run (resumable)"
                    )
                    break
                if processed_this_run % 500 == 0:
                    print(
                        f"--- {processed_this_run}/{len(todo)} processed this run ---"
                    )
                    merge_pins_into_tenant_overrides()
    finally:
        report.close()
        merge_pins_into_tenant_overrides()

    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        results = list(csv.DictReader(f))
    by_outcome = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    print("\n=== SUMMARY (cumulative across all runs) ===")
    for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
        print(f"outcome {outcome}: {count}")
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
