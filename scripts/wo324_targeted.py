"""WO-324 (2026-09-12): passive discovery v2 at full scale, phase 3 -- targeted
fetches of phase 2's top-5 candidates per government, plus the
fallback ladder for a government phase 2 found NO candidate for.

Reuses `wo273_targeted.py`'s fetch machinery directly (imported, not
duplicated): `fetch_and_score()` (HEAD then GET, archive body first via
a short single-attempt exact-URL CDX lookup, `platform_fingerprints.
fingerprint()` + `detect_platform()` over the fetched page, `name_
matches()` requiring the page to name this government's own city AND
state), the same per-host/per-vendor-family `RATE_LIMITER`.

Adds what WO-273's phase 3 got wrong (WO-278's real finding: 76 of 147
"confirmed" were a catch-all template answering any path) and what this
WO's own redesign calls for:

  - **Catch-all test.** One nonsense path per host
    (`/__wo324_nonsense_<random>__`), fetched once per government and
    compared (status + body length + a cheap body hash) against both the
    homepage (from phase 1's cache) and every "confirmed" candidate
    fetch. A candidate whose body matches either is a soft-200 --
    recorded as `catchall_confirmed=True` and NEVER counted as a real
    platform/hub confirmation, no matter what `fetch_and_score()` found.
  - **800-byte floor.** A 200 response under 800 bytes is treated as
    empty/parked, same reasoning as the catch-all test -- too little
    content to mean anything either way.
  - **Fallback ladder**, for a government phase 2 flagged with NO
    candidate at all (confidence=none, n_candidates=0, and NOT
    dns-unresolvable): rungs, in order, stopping at the first real find:
      1. One hop from the BEST-scored homepage link even below the
         normal find_hop_links() qualification gate (score computed with
         the same path/anchor vocabulary and position bonus, but without
         requiring a positive path/target score -- the highest-scoring
         link, whatever its sign, if the homepage had any links at all).
      2. A headless render of the homepage (`wo147_access_ladder_sweep.
         fetch_headless_sync()`, reused as-is) and a rescore of ITS links
         the same way.
      3. `/AgendaCenter` and `/AgendaOnline/Meetings/ViewMeeting` probes,
         behind the same catch-all test.
      4. Record the outcome (`no-platform-link-found` etc.) with
         whatever evidence the ladder gathered, even if nothing.
    `fallback_rung` records which rung (1-4) produced each government's
    outcome.

Output: `research/wo324_targeted.csv`, one row per (government, URL)
actually fetched -- domain, gov_id, rank, source, source_kind,
source_score, fetch_method, http_status, body_len, catchall_confirmed,
platform_confirmed, platform_signal, name_match, fallback_rung, error,
timing_ms.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo324_targeted_scratch.db" \\
        .venv/bin/python scripts/wo324_targeted.py --limit 50 --concurrency 32
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover -- POSIX only, fine for this project
    fcntl = None

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

import wo273_targeted as w273t  # noqa: E402
import wo273_recon as w273  # noqa: E402
import wo147_access_ladder_sweep as w147  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CLASSIFIED_CSV = RESEARCH_DIR / "wo324_classified.csv"
TARGETED_CSV = RESEARCH_DIR / "wo324_targeted.csv"
PORTAL_GUARD_CSV = RESEARCH_DIR / "wo324_portal_guard_hosts.csv"

# WO-324: absolute rule for this run (repeated in the brief because WO-283
# broke it) -- never fetch a youtube.com/youtu.be URL for any reason, not
# even a plain page GET. WO-283's own targeted phase 3 fetched a candidate
# URL as soon as it ranked in the top 5, with no host check at all, which is
# exactly how it made 439 real page-fetches to YouTube before the mistake
# was caught. Any youtube.com/youtu.be candidate this WO's classify phase
# ranks (it can -- detect_platform() calls youtube.com/youtu.be a real
# "platform" like any other, and that check is offline/no-network so it is
# fine there) is intercepted HERE, before fetch_and_score_v2() ever calls
# polite_fetch() on it: recorded as a lead in the shared
# research/youtube_channel_leads.csv (verified=false, for the drip Mac /
# a human), never fetched, never counted as a platform confirmation.
YOUTUBE_LEADS_CSV = RESEARCH_DIR / "youtube_channel_leads.csv"
YOUTUBE_LEADS_LOCK = RESEARCH_DIR / "youtube_channel_leads.csv.lock"
YOUTUBE_LEADS_FIELDNAMES = [
    "channel_url",
    "gov_id",
    "government",
    "state",
    "source_wo",
    "kind",
    "verified",
    "note",
]
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)
YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")


def is_youtube_url(url: str) -> bool:
    return urlparse(url).netloc.lower() in YOUTUBE_HOSTS


def youtube_kind(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    if (
        netloc == "youtu.be"
        or "/watch" in path
        or "/shorts/" in path
        or "/embed/" in path
    ):
        return "single_video"
    return "channel"


def _youtube_dedupe_key(url: str) -> str:
    """Normalized key for deduping a YouTube URL against existing leads and
    pins -- the video id for a /watch or youtu.be URL, else the @handle or
    /channel//c//user/ id, lowercased. Two differently-decorated URLs for
    the same video/channel (extra query params, trailing slash) collapse to
    the same key."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path
    if netloc == "youtu.be":
        return "video:" + path.strip("/").lower()
    qs = parse_qs(parsed.query)
    if qs.get("v"):
        return "video:" + qs["v"][0].lower()
    if path.startswith("/@"):
        return "channel:" + path.strip("/").lower()
    for prefix in ("/channel/", "/c/", "/user/"):
        if path.startswith(prefix):
            return "channel:" + path[len(prefix) :].strip("/").lower()
    return "channel:" + path.strip("/").lower()


def _read_csv_skipping_comments(path: Path) -> list[dict]:
    """youtube_channel_leads.csv opens with `#`-prefixed explainer lines
    before its real header -- csv.DictReader would otherwise treat the
    first comment line as the header row."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(lines))


_youtube_dedupe_keys: set | None = None
_youtube_pinned_keys: set | None = None


def _load_youtube_dedupe_sets() -> tuple[set, set]:
    global _youtube_dedupe_keys, _youtube_pinned_keys
    if _youtube_dedupe_keys is None:
        _youtube_dedupe_keys = {
            _youtube_dedupe_key(row["channel_url"])
            for row in _read_csv_skipping_comments(YOUTUBE_LEADS_CSV)
            if row.get("channel_url")
        }
    if _youtube_pinned_keys is None:
        pinned = set()
        if TENANT_OVERRIDES_CSV.exists():
            with open(TENANT_OVERRIDES_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    m = (row.get("match") or "").strip()
                    if m.startswith("channel="):
                        pinned.add("channel:/" + m[len("channel=") :].strip().lower())
        _youtube_pinned_keys = pinned
    return _youtube_dedupe_keys, _youtube_pinned_keys


def record_youtube_lead(
    url: str, gov_id: str, government: str, state: str, note: str = ""
) -> bool:
    """Appends one row to the shared youtube_channel_leads.csv, deduped
    against the file's own existing rows and against tenant_overrides.csv
    channel pins. Returns True if a new row was written. Locked with a
    sibling .lock file (advisory flock) since sibling WO-320/322/323
    agents append to this same shared file concurrently -- same shape as
    jurisdiction_coverage.csv's own lock, just for a single-row append
    rather than a full rewrite."""
    key = _youtube_dedupe_key(url)
    lock_fd = open(YOUTUBE_LEADS_LOCK, "w")
    try:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Re-read fresh under the lock -- another process may have added
        # this exact lead (or its pin) since this process's in-memory
        # cache was built.
        global _youtube_dedupe_keys
        _youtube_dedupe_keys = None
        keys, pins = _load_youtube_dedupe_sets()
        if key in keys or key in pins:
            return False
        write_header = not YOUTUBE_LEADS_CSV.exists()
        with open(
            YOUTUBE_LEADS_CSV, "a", newline="", encoding="utf-8", buffering=1
        ) as f:
            w = csv.DictWriter(f, fieldnames=YOUTUBE_LEADS_FIELDNAMES)
            if write_header:
                w.writeheader()
            w.writerow(
                {
                    "channel_url": url,
                    "gov_id": gov_id,
                    "government": government,
                    "state": state,
                    "source_wo": "WO-324",
                    "kind": youtube_kind(url),
                    "verified": "false",
                    "note": note,
                }
            )
        keys.add(key)
        return True
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


BODY_FLOOR_BYTES = 800
FIRST_PARTY_PROBE_PATHS = [
    "/AgendaCenter",
    "/AgendaOnline/Meetings/ViewMeeting",
]

# WO-324 change 4: a Wistia/Vimeo/YouTube video reached through a payment,
# billing, or forms portal host is never a candidate -- WO-282's own
# Jemison AL / Zillah UT finding: both resolved to the SAME unrelated
# "Making a Payment with PayPal" Wistia clip via an invoicecloud.com
# billing portal a homepage hop chased into. A host is a "portal" here
# only when it is (a) not the government's own domain and (b) not itself
# a recognized first-party meeting-platform host (detect_platform() !=
# "unknown" -- e.g. wistia.com/vimeo.com/youtube.com themselves are real
# platforms and stay eligible) and (c) matches known payment/billing/
# forms vocabulary in its hostname.
PORTAL_HOST_KEYWORDS = (
    "invoicecloud",
    "billing",
    "paybill",
    "epay",
    "e-pay",
    "xpresspay",
    "xpress-pay",
    "munisselfservice",
    "paypal",
    "payment",
    "docusign",
    "jotform",
    "wufoo",
    "surveymonkey",
    "forms.",
)


def third_party_portal_host(url: str, government_domain: str) -> str:
    """Returns the offending netloc if `url` is on a third-party payment/
    billing/forms portal host, else ''."""
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        return ""
    gov_host = government_domain.lower()
    if netloc == gov_host or netloc.endswith("." + gov_host):
        return ""
    try:
        if detect_platform(url) != "unknown":
            return ""
    except Exception:  # noqa: BLE001
        pass
    if any(kw in netloc for kw in PORTAL_HOST_KEYWORDS):
        return netloc
    return ""


_portal_guard_write_lock = threading.Lock()


def record_portal_guard(domain: str, gov_id: str, host: str, url: str) -> None:
    write_header = not PORTAL_GUARD_CSV.exists()
    with _portal_guard_write_lock:
        with open(PORTAL_GUARD_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f, fieldnames=["domain", "gov_id", "portal_host", "candidate_url"]
            )
            if write_header:
                w.writeheader()
            w.writerow(
                {
                    "domain": domain,
                    "gov_id": gov_id,
                    "portal_host": host,
                    "candidate_url": url,
                }
            )


_write_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


def body_hash(body: bytes) -> str:
    return hashlib.sha1(body[:4000]).hexdigest() if body else ""


def nonsense_path() -> str:
    token = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    return f"/__wo324_nonsense_{token}__"


def catchall_signature(domain: str) -> dict:
    """Fetch one nonsense path for this host, once. Returns a signature
    dict (status, body_len, body_hash) used to recognize a soft-200
    catch-all template answering every path the same way."""
    url = f"https://{domain}{nonsense_path()}"
    try:
        resp = w273t.polite_fetch(url, method="GET")
        body = resp.content or b""
        return {
            "status": resp.status_code,
            "body_len": len(body),
            "body_hash": body_hash(body),
        }
    except Exception as e:  # noqa: BLE001
        return {"status": None, "body_len": 0, "body_hash": "", "error": str(e)[:200]}


def is_catchall_match(sig: dict, status: int | None, body_len: int, hsh: str) -> bool:
    if status != 200 or sig.get("status") != 200:
        return False
    if hsh and hsh == sig.get("body_hash"):
        return True
    # Soft-200 heuristic: near-identical length (within 2%) to the
    # nonsense-path response counts as the same catch-all template even
    # when a timestamp/nonce in the body changes the hash.
    sig_len = sig.get("body_len") or 0
    if sig_len and abs(body_len - sig_len) <= max(20, sig_len * 0.02):
        return True
    return False


def load_classified() -> list[dict]:
    with open(CLASSIFIED_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_homepage_cached(domain: str) -> dict:
    """Reads this government's phase-1 recon record straight back out of
    wo324_recon.jsonl for its cached homepage HTML path -- phase 3 keeps
    no separate index, this is a small file read per government, far
    cheaper than a live refetch."""
    # Lazy module-level cache: built once, reused across threads (read
    # only after the sweep starts, so no lock needed beyond the GIL's own
    # atomic dict assignment).
    global _HOMEPAGE_INDEX
    if _HOMEPAGE_INDEX is None:
        idx: dict[str, dict] = {}
        recon_path = RESEARCH_DIR / "wo324_recon.jsonl"
        if recon_path.exists():
            with open(recon_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    idx[rec.get("domain", "")] = rec
        _HOMEPAGE_INDEX = idx
    return _HOMEPAGE_INDEX.get(domain, {})


_HOMEPAGE_INDEX: dict | None = None


def score_raw_link(text: str, href: str, full_url: str, base_netloc: str, tag) -> float:
    """Same vocabulary/position scoring find_hop_links() uses internally
    (_score_hop_candidate_weighted), but WITHOUT its disqualifying gate
    -- rung 1 of the fallback ladder wants the single best-scored link on
    a homepage that had no link clear a normal qualification bar, even
    if every link scores zero or negative."""
    netloc = urlparse(full_url).netloc.lower()
    hay = f"{text} {href}".lower()
    path = urlparse(full_url).path
    path_tokens = w147._hop_tokenize(path)
    anchor_words = w147._hop_tokenize(text)
    path_score = sum(w147._HOP_PATH_WEIGHTS.get(t, 0.0) for t in set(path_tokens))
    path_score += sum(
        w147._HOP_PATH_WEIGHTS.get(b, 0.0) for b in set(w147._hop_bigrams(path_tokens))
    )
    anchor_score = sum(w147._HOP_ANCHOR_WEIGHTS.get(w, 0.0) for w in set(anchor_words))
    target_bonus = 0.0
    is_vendor = (
        bool(netloc) and netloc != base_netloc and w147.is_vendor_href_host(netloc)
    )
    if is_vendor or w147._NAMED_FIRSTPARTY_PATH_RE.search(hay):
        target_bonus = w147._TARGET_SHAPE_BONUS
    routine_penalty = -8.0 if any(w in hay for w in w147._ROUTINE_WORDS) else 0.0
    position_bonus = w147._nav_position_bonus(tag)
    return path_score + anchor_score + target_bonus + routine_penalty + position_bonus


def best_link_even_below_threshold(
    html: str, final_url: str
) -> tuple[str, float] | None:
    soup = w147._safe_soup(html)
    if soup is None:
        return None
    base_netloc = urlparse(final_url).netloc.lower()
    best_url, best_score = None, float("-inf")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(final_url, href)
        if urlparse(full).scheme not in ("http", "https"):
            continue
        text = (a.get_text() or "").strip()
        score = score_raw_link(text, href, full, base_netloc, a)
        if score > best_score:
            best_score, best_url = score, full
    if best_url is None:
        return None
    return best_url, best_score


def fetch_and_score_v2(
    url: str, name: str, state: str, catchall_sig: dict | None
) -> dict:
    """Same fetch/score pipeline as wo273_targeted.fetch_and_score() --
    archive body first (short single-attempt exact-URL CDX lookup), else
    one HEAD (alive?) + one GET via the shared per-host/per-vendor-family
    RATE_LIMITER -- but done here directly (not by calling
    fetch_and_score() AND re-fetching) so the catch-all/800-byte checks
    below reuse the SAME fetched body instead of costing this host a
    second real request."""
    t0 = time.monotonic()
    out = {
        "url": url,
        "fetch_method": "",
        "http_status": None,
        "platform_confirmed": "",
        "platform_signal": "",
        "name_match": False,
        "body_len": 0,
        "catchall_confirmed": False,
        "error": "",
        "timing_ms": 0,
    }
    body, used_archive = w273t.try_wayback_archived_body(url)
    html = ""
    if body is not None:
        out["fetch_method"] = "archived_id_"
        out["http_status"] = 200
        out["body_len"] = len(body)
        try:
            html = body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            html = ""
    else:
        head_status = None
        try:
            head_resp = w273t.polite_fetch(url, method="HEAD")
            head_status = head_resp.status_code
            alive = head_status < 400
        except Exception:  # noqa: BLE001
            alive = True  # some servers reject HEAD; try GET anyway
        if not alive:
            out["fetch_method"] = "live"
            out["http_status"] = head_status
            out["error"] = "dead-on-head"
            out["timing_ms"] = int((time.monotonic() - t0) * 1000)
            return out
        out["fetch_method"] = "live"
        try:
            resp = w273t.polite_fetch(url, method="GET")
            out["http_status"] = resp.status_code
            body = resp.content or b""
            out["body_len"] = len(body)
            if resp.status_code == 200 and resp.text:
                if w273.is_challenge(resp.text):
                    out["error"] = "challenge-gate"
                else:
                    html = resp.text
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:200]
            body = b""

    hsh = body_hash(body or b"")
    if catchall_sig and is_catchall_match(
        catchall_sig, out.get("http_status"), out["body_len"], hsh
    ):
        out["catchall_confirmed"] = True

    if html and not out["catchall_confirmed"] and out["body_len"] >= BODY_FLOOR_BYTES:
        out["name_match"] = w273t.name_matches(html, name, state)
        signals = w273t.platform_fingerprints.fingerprint(html, url=url)
        if signals:
            best = max(signals, key=lambda s: s[2])
            out["platform_signal"] = f"{best[0]}:{best[1]}({best[2]:.2f})"
            if out["name_match"]:
                out["platform_confirmed"] = best[0]
        else:
            try:
                dp = detect_platform(url)
                if dp and dp != "unknown":
                    out["platform_signal"] = f"{dp}:url-shape"
                    if out["name_match"]:
                        out["platform_confirmed"] = dp
            except Exception:  # noqa: BLE001
                pass
    elif out["body_len"] and out["body_len"] < BODY_FLOOR_BYTES:
        out["error"] = (
            (out["error"] + ";under-800-byte-floor")
            if out["error"]
            else "under-800-byte-floor"
        )

    out["timing_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def process_with_candidates(row: dict) -> list[dict]:
    domain = row["domain"]
    gov_id = row.get("gov_id", "")
    name = row.get("name", "")
    state = row.get("state", "")
    try:
        candidates = json.loads(row.get("candidates_json") or "[]")
    except Exception:  # noqa: BLE001
        candidates = []
    sig = catchall_signature(domain)
    results = []
    for rank, c in enumerate(candidates[:5], start=1):
        if is_youtube_url(c["url"]):
            record_youtube_lead(
                c["url"],
                gov_id,
                name,
                state,
                note=f"WO-324 phase-3 candidate rank={rank} source={c.get('source', '')}",
            )
            results.append(
                {
                    "domain": domain,
                    "gov_id": gov_id,
                    "url": c["url"],
                    "rank": rank,
                    "source": c.get("source", ""),
                    "source_kind": c.get("kind", ""),
                    "source_score": c.get("score", 0),
                    "fetch_method": "",
                    "http_status": None,
                    "body_len": 0,
                    "catchall_confirmed": False,
                    "platform_confirmed": "",
                    "platform_signal": "",
                    "name_match": False,
                    "fallback_rung": 0,
                    "error": "youtube-skipped-no-fetch-rule",
                    "timing_ms": 0,
                }
            )
            continue
        portal_host = third_party_portal_host(c["url"], domain)
        if portal_host:
            record_portal_guard(domain, gov_id, portal_host, c["url"])
            results.append(
                {
                    "domain": domain,
                    "gov_id": gov_id,
                    "url": c["url"],
                    "rank": rank,
                    "source": c.get("source", ""),
                    "source_kind": c.get("kind", ""),
                    "source_score": c.get("score", 0),
                    "fetch_method": "",
                    "http_status": None,
                    "body_len": 0,
                    "catchall_confirmed": False,
                    "platform_confirmed": "",
                    "platform_signal": "",
                    "name_match": False,
                    "fallback_rung": 0,
                    "error": f"third-party-portal-guard:{portal_host}",
                    "timing_ms": 0,
                }
            )
            continue
        t0 = time.monotonic()
        r = fetch_and_score_v2(c["url"], name, state, sig)
        r.update(
            domain=domain,
            gov_id=gov_id,
            rank=rank,
            source=c.get("source", ""),
            source_kind=c.get("kind", ""),
            source_score=c.get("score", 0),
            fallback_rung=0,
            timing_ms=int((time.monotonic() - t0) * 1000),
        )
        results.append(r)
    return results


def process_fallback_ladder(row: dict) -> list[dict]:
    domain = row["domain"]
    name = row.get("name", "")
    state = row.get("state", "")
    rec = load_homepage_cached(domain)
    homepage = rec.get("homepage") or {}
    gz_path = homepage.get("homepage_gz_path", "")
    final_url = homepage.get("final_url") or f"https://{domain}/"
    sig = catchall_signature(domain)
    results = []

    html = ""
    if gz_path:
        try:
            with gzip.open(gz_path, "rb") as f:
                html = f.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            html = ""

    rung = 4

    # Rung 1: best homepage link even below threshold.
    if html:
        best = best_link_even_below_threshold(html, final_url)
        if best and is_youtube_url(best[0]):
            record_youtube_lead(
                best[0],
                row.get("gov_id", ""),
                name,
                state,
                note="WO-324 fallback-rung1-onehop best link",
            )
            best = None
        if best and third_party_portal_host(best[0], domain):
            record_portal_guard(
                domain,
                row.get("gov_id", ""),
                third_party_portal_host(best[0], domain),
                best[0],
            )
            best = None
        if best:
            url, score = best
            t0 = time.monotonic()
            r = fetch_and_score_v2(url, name, state, sig)
            r.update(
                domain=domain,
                gov_id=row.get("gov_id", ""),
                rank=1,
                source="fallback-rung1-onehop",
                source_kind="hop",
                source_score=score,
                fallback_rung=1,
                timing_ms=int((time.monotonic() - t0) * 1000),
            )
            results.append(r)
            if r.get("platform_confirmed") or (
                r.get("name_match") and not r.get("catchall_confirmed")
            ):
                rung = 1

    # Rung 2: headless render of the homepage, rescore links.
    if rung == 4:
        t0 = time.monotonic()
        try:
            content, headless_final_url, herr = w147.fetch_headless_sync(final_url)
        except Exception as e:  # noqa: BLE001
            content, headless_final_url, herr = None, final_url, str(e)[:200]
        headless_ms = int((time.monotonic() - t0) * 1000)
        if content:
            best = best_link_even_below_threshold(content, headless_final_url)
            if best and is_youtube_url(best[0]):
                record_youtube_lead(
                    best[0],
                    row.get("gov_id", ""),
                    name,
                    state,
                    note="WO-324 fallback-rung2-headless best link",
                )
                best = None
            if best and third_party_portal_host(best[0], domain):
                record_portal_guard(
                    domain,
                    row.get("gov_id", ""),
                    third_party_portal_host(best[0], domain),
                    best[0],
                )
                best = None
            if best:
                url, score = best
                t1 = time.monotonic()
                r = fetch_and_score_v2(url, name, state, sig)
                r.update(
                    domain=domain,
                    gov_id=row.get("gov_id", ""),
                    rank=1,
                    source="fallback-rung2-headless",
                    source_kind="hop",
                    source_score=score,
                    fallback_rung=2,
                    timing_ms=headless_ms + int((time.monotonic() - t1) * 1000),
                )
                results.append(r)
                if r.get("platform_confirmed") or (
                    r.get("name_match") and not r.get("catchall_confirmed")
                ):
                    rung = 2
        else:
            results.append(
                {
                    "domain": domain,
                    "gov_id": row.get("gov_id", ""),
                    "url": final_url,
                    "rank": 1,
                    "source": "fallback-rung2-headless",
                    "source_kind": "hop",
                    "source_score": 0,
                    "fetch_method": "headless",
                    "http_status": None,
                    "body_len": 0,
                    "catchall_confirmed": False,
                    "platform_confirmed": "",
                    "platform_signal": "",
                    "name_match": False,
                    "fallback_rung": 2,
                    "error": herr or "headless-no-content",
                    "timing_ms": headless_ms,
                }
            )

    # Rung 3: named first-party probes, behind the catch-all test.
    if rung == 4:
        for path in FIRST_PARTY_PROBE_PATHS:
            url = f"https://{domain}{path}"
            t0 = time.monotonic()
            r = fetch_and_score_v2(url, name, state, sig)
            r.update(
                domain=domain,
                gov_id=row.get("gov_id", ""),
                rank=1,
                source="fallback-rung3-probe",
                source_kind="first_party_probe",
                source_score=0,
                fallback_rung=3,
                timing_ms=int((time.monotonic() - t0) * 1000),
            )
            results.append(r)
            if (
                r.get("http_status")
                and r.get("http_status") < 400
                and not r.get("catchall_confirmed")
            ):
                rung = 3
                break

    # Rung 4: record the outcome, whatever the ladder gathered.
    if rung == 4 and not results:
        results.append(
            {
                "domain": domain,
                "gov_id": row.get("gov_id", ""),
                "url": "",
                "rank": 1,
                "source": "fallback-rung4-none",
                "source_kind": "",
                "source_score": 0,
                "fetch_method": "",
                "http_status": None,
                "body_len": 0,
                "catchall_confirmed": False,
                "platform_confirmed": "",
                "platform_signal": "",
                "name_match": False,
                "fallback_rung": 4,
                "error": "no-platform-link-found",
                "timing_ms": 0,
            }
        )

    return results


def load_done_domains() -> set:
    done = set()
    if TARGETED_CSV.exists():
        with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
            done = {row["domain"] for row in csv.DictReader(f)}
    return done


FIELDNAMES = [
    "domain",
    "gov_id",
    "url",
    "rank",
    "source",
    "source_kind",
    "source_score",
    "fetch_method",
    "http_status",
    "body_len",
    "catchall_confirmed",
    "platform_confirmed",
    "platform_signal",
    "name_match",
    "fallback_rung",
    "error",
    "timing_ms",
]


def cmd_sweep(limit: int, concurrency: int) -> None:
    classified = load_classified()
    done = load_done_domains()
    # Conductor instruction, mid-run (2026-09-12): WO-323 proved the hop-link
    # vocabulary phase 3 scores against is English-only (0/92 confirmed on
    # Quebec sites whose own nav says "Conseil municipal"/"Séances du
    # conseil", never the English hub/meeting words this pipeline looks
    # for). Spending further phase-3 network effort on a Quebec row can't
    # produce a trustworthy negative -- it would look like
    # no-platform-link-found for a reason that has nothing to do with
    # whether a platform exists. Skip phase 3 for every Quebec row (phase 1
    # already ran for all of them, so the saved homepage HTML exists for
    # WO-327's French-vocabulary rerun); they are reported as
    # deferred-french-vocab, never as a phase-3 outcome.
    quebec_skipped = [r for r in classified if r.get("state") == "Quebec"]
    remaining = [
        r for r in classified if r["domain"] not in done and r.get("state") != "Quebec"
    ]
    log(
        f"{len(done)} already done, {len(remaining)} remaining of "
        f"{len(classified)} ({len(quebec_skipped)} Quebec rows deferred "
        "to WO-327's French-vocabulary rerun, not swept here)"
    )

    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} governments at concurrency={concurrency}")

    write_header = not TARGETED_CSV.exists()
    start = time.monotonic()
    completed = 0
    errors = 0
    with (
        open(TARGETED_CSV, "a", newline="", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        writer = csv.DictWriter(out, fieldnames=FIELDNAMES, extrasaction="ignore")
        if write_header:
            writer.writeheader()

        def work(row):
            if row.get("note") == "dns-unresolvable":
                return []
            if int(row.get("n_candidates") or 0) > 0:
                return process_with_candidates(row)
            return process_fallback_ladder(row)

        futures = {pool.submit(work, row): row for row in to_process}
        for fut in as_completed(futures):
            row = futures[fut]
            domain = row["domain"]
            try:
                results = fut.result()
            except Exception as e:  # noqa: BLE001
                errors += 1
                results = [
                    {
                        "domain": domain,
                        "gov_id": row.get("gov_id", ""),
                        "url": "",
                        "rank": 1,
                        "error": str(e)[:300],
                    }
                ]
            if not results:
                results = [
                    {
                        "domain": domain,
                        "gov_id": row.get("gov_id", ""),
                        "url": "",
                        "rank": 0,
                        "error": "dns-unresolvable-skip",
                    }
                ]
            with _write_lock:
                for r in results:
                    writer.writerow(r)
                out.flush()
            completed += 1
            if completed % 10 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s rate={rate:.1f}/min errors={errors} last={domain}"
                )

    elapsed = time.monotonic() - start
    rate = len(to_process) / (elapsed / 60) if elapsed > 0 else 0
    log(
        f"chunk done: {len(to_process)} processed in {elapsed:.0f}s "
        f"({rate:.2f} governments/min), {errors} errors, "
        f"{len(remaining) - len(to_process)} remain unprocessed."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=32)
    args = parser.parse_args()
    cmd_sweep(args.limit, args.concurrency)


if __name__ == "__main__":
    main()
