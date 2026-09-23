"""WO-282 (2026-09-12): passive discovery v2, phase 3 -- targeted
fetches of phase 2's top-5 candidates per government, plus the
fallback ladder for a government phase 2 found NO candidate for.

Reuses WO-273's own fetch machinery directly -- moved into this file
verbatim (WO-1019, 2026-09-23; see the "Moved here from
wo273_targeted.py" banner below) now that WO-273's own scripts are
retired: `try_wayback_archived_body()` + `polite_fetch()` (HEAD then GET,
archive body first via a short single-attempt exact-URL CDX lookup),
`platform_fingerprints.fingerprint()` + `detect_platform()` over the
fetched page, `name_matches()` requiring the page to name this
government's own city AND state, the same per-host/per-vendor-family
`RATE_LIMITER`.

Adds what WO-273's phase 3 got wrong (WO-278's real finding: 76 of 147
"confirmed" were a catch-all template answering any path) and what this
WO's own redesign calls for:

  - **Catch-all test.** One nonsense path per host
    (`/__wo282_nonsense_<random>__`), fetched once per government and
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

Output: `research/wo282_targeted.csv`, one row per (government, URL)
actually fetched -- domain, gov_id, rank, source, source_kind,
source_score, fetch_method, http_status, body_len, catchall_confirmed,
platform_confirmed, platform_signal, name_match, fallback_rung, error,
timing_ms.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo282_targeted_scratch.db" \\
        .venv/bin/python scripts/wo282_targeted.py --limit 50 --concurrency 32
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import re
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from wo282_recon import (  # noqa: E402
    HEADERS,
    STALE_DAYS,
    _ARCHIVE_SEMA,
    RATE_LIMITER,
    capture_age_days,
    is_challenge,
    vendor_family_for_url,
)
from sweep_deadline import run_with_deadline  # noqa: E402
import wo147_access_ladder_sweep as w147  # noqa: E402
import platform_fingerprints  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402
from app.platforms.host_recognition import (  # noqa: E402
    FIRST_PARTY_PROBE_PATHS,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CLASSIFIED_CSV = RESEARCH_DIR / "wo282_classified.csv"
TARGETED_CSV = RESEARCH_DIR / "wo282_targeted.csv"

BODY_FLOOR_BYTES = 800
# FIRST_PARTY_PROBE_PATHS moved to app.platforms.host_recognition
# (WO-1021, 2026-09-23) -- imported above -- so this script's rung-3
# fallback-ladder probe paths stay in sync with the same shared source
# wo282_recon.py/wo282_classify.py now use, instead of its own hand-
# copied `["/AgendaCenter", "/AgendaOnline/Meetings/ViewMeeting"]` list.

_write_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Moved here from wo273_targeted.py (WO-1019, 2026-09-23): WO-273's own
# scripts are retired, but this fetch/scoring plumbing -- the shared
# per-host/per-vendor-family polite_fetch(), the archive-first exact-URL
# CDX lookup, the streamed-body/redirect helpers, the WO-278 catch-all
# guard (fetch_domain_reference()/is_catch_all_response()/is_same_domain()),
# and name_matches() -- is real, shared library code other scripts (and
# this file's own fetch_and_score_v2()) still call. Moved verbatim, not
# rewritten. WO-273's own fetch_and_score()/top_flagged_urls()/
# process_government_targeted()/cmd_sweep()/affected_domains()/main() were
# NOT moved: nothing outside wo273_targeted.py's own CLI ever called them
# (this file has its own fetch_and_score_v2()/process_with_candidates()/
# process_fallback_ladder()/cmd_sweep(), reading a differently-shaped
# wo282_classified.csv candidates_json column rather than wo273's
# per-kind best_hub_url/best_meeting_url columns).
# --------------------------------------------------------------------------

GOV_TIMEOUT = 10  # 3s connect target / 10s read, one retry at most (brief)
CDX_EXACT_TIMEOUT = 6  # short, single attempt -- see module docstring

# WO-939: real wall-clock cap on top of GOV_TIMEOUT's per-read bound, same
# gap and same fix as wo282_recon.py's own GOV_REQUEST_WALL_CLOCK_DEADLINE
# (see that constant's own comment, and scripts/sweep_deadline.py's
# module docstring) -- confirmed live by the same WO-322 incident this
# entry's siblings cite. `wo337_targeted.py`'s own `capped_polite_fetch()`
# already worked around this in ITS OWN copy (a byte-cap + hand-rolled
# streaming wall-clock loop) rather than editing this shared module,
# since other WOs were running against it concurrently at the time --
# this is the real, shared-module fix that comment said still belonged
# here.
GOV_REQUEST_WALL_CLOCK_DEADLINE = 25

# WO-278 catch-all guard.
MIN_CONFIRM_BODY_BYTES = 800  # same floor url_shape_mining.md's Stage 2 uses
CATCH_ALL_SIZE_TOLERANCE = 0.05  # "a few percent" per this WO's brief
NONSENSE_LABEL_LEN = 10


def try_wayback_archived_body(url: str) -> tuple:
    """One short, single-attempt exact-URL CDX lookup (see module
    docstring on why this is deliberately not retried the way phase 1's
    per-government calls are). Returns (body_bytes_or_None, used_archive:
    bool)."""
    if non_page_url(url):
        return None, False
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={url}&filter=statuscode:200&collapse=urlkey"
        "&limit=-3&fl=original,timestamp&output=json"
    )
    with _ARCHIVE_SEMA:
        try:
            resp, skip = bounded_redirect_fetch(
                cdx_url,
                lambda next_url: requests.get(
                    next_url,
                    headers=HEADERS,
                    timeout=CDX_EXACT_TIMEOUT,
                    stream=True,
                    allow_redirects=False,
                ),
            )
        except Exception:  # noqa: BLE001
            return None, False
        if skip or resp is None:
            return None, False
        try:
            if resp.status_code != 200:
                return None, False
            cdx_body = bytearray()
            for chunk in resp.iter_content(chunk_size=16384):
                if len(cdx_body) + len(chunk) > 65536:
                    return None, False
                cdx_body.extend(chunk)
            rows = json.loads(cdx_body)[1:]
        except Exception:  # noqa: BLE001
            return None, False
        finally:
            resp.close()
    if not rows:
        return None, False
    orig, ts = max(rows, key=lambda r: r[1] if len(r) > 1 else "")
    if capture_age_days(ts) > STALE_DAYS:
        return None, False
    id_url = f"https://web.archive.org/web/{ts}id_/{orig}"
    with _ARCHIVE_SEMA:
        try:
            resp, skip = bounded_redirect_fetch(
                id_url,
                lambda next_url: requests.get(
                    next_url,
                    headers=HEADERS,
                    timeout=CDX_EXACT_TIMEOUT,
                    stream=True,
                    allow_redirects=False,
                ),
            )
        except Exception:  # noqa: BLE001
            return None, False
        if skip or resp is None:
            return None, False
        try:
            if resp.status_code == 200:
                body, reason = bounded_page_body(resp)
                if not reason:
                    return body, True
        except Exception:  # noqa: BLE001
            return None, False
        finally:
            resp.close()
    return None, False


def polite_fetch(url: str, method: str = "GET", **kwargs):
    key = vendor_family_for_url(url)
    allow_redirects = kwargs.pop("allow_redirects", True)
    # WO-939: run_with_deadline() wraps requests.request() itself, inside
    # wait_and_request()'s per-vendor-family lock -- so a hung response
    # releases that lock after GOV_REQUEST_WALL_CLOCK_DEADLINE instead of
    # holding it (wedging every OTHER candidate sharing that vendor
    # family) forever. See GOV_REQUEST_WALL_CLOCK_DEADLINE's own comment.
    return RATE_LIMITER.wait_and_request(
        key,
        run_with_deadline,
        requests.request,
        method,
        url,
        headers=HEADERS,
        timeout=GOV_TIMEOUT,
        allow_redirects=allow_redirects,
        deadline_seconds=GOV_REQUEST_WALL_CLOCK_DEADLINE,
        **kwargs,
    )


PAGE_BODY_LIMIT = 2 * 1024 * 1024
_NON_PAGE_SUFFIXES = (
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".avi",
    ".mp3",
    ".wav",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
)


def non_page_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(_NON_PAGE_SUFFIXES)


def page_url_skip(url: str, redirected: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "skipped-non-http-redirect"
    host = parsed.netloc.lower().split(":", 1)[0]
    if host in ("youtube.com", "youtu.be", "www.youtube.com") or host.endswith(
        ".youtube.com"
    ):
        return "skipped-youtube-redirect" if redirected else "skipped-youtube-url"
    return "skipped-media-url" if non_page_url(url) else ""


def bounded_redirect_fetch(url: str, request_fn) -> tuple[object | None, str]:
    """Follow page redirects without consuming redirect response bodies."""
    for hop in range(6):
        skip = page_url_skip(url, redirected=hop > 0)
        if skip:
            return None, skip
        resp = request_fn(url)
        if resp.status_code not in (301, 302, 303, 307, 308):
            return resp, ""
        location = resp.headers.get("Location", "")
        next_url = urljoin(resp.url or url, location) if location else ""
        resp.close()
        if not next_url:
            return None, "skipped-broken-redirect"
        url = next_url
    return None, "skipped-redirect-loop"


def polite_page_fetch(url: str, method: str = "GET"):
    return bounded_redirect_fetch(
        url,
        lambda next_url: polite_fetch(
            next_url, method=method, stream=True, allow_redirects=False
        ),
    )


def bounded_page_body(resp) -> tuple[bytes | None, str]:
    """Read at most one small HTML page from a streamed response."""
    skip = page_url_skip(resp.url or "", redirected=True)
    if skip:
        return None, skip
    content_type = resp.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type and content_type not in (
        "text/html",
        "application/xhtml+xml",
        "text/plain",
    ):
        return None, "skipped-non-html"
    try:
        declared = int(resp.headers.get("Content-Length", "0"))
    except ValueError:
        declared = 0
    if declared > PAGE_BODY_LIMIT:
        return None, "skipped-oversize"
    body = bytearray()
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        if len(body) + len(chunk) > PAGE_BODY_LIMIT:
            return None, "skipped-oversize"
        body.extend(chunk)
        if len(body) <= len(chunk):
            sample = chunk[:512]
            if (
                b"\x00" in sample
                or sample.startswith((b"%PDF", b"\x89PNG", b"PK\x03\x04"))
                or sample[4:8] == b"ftyp"
                or (
                    not content_type
                    and sample
                    and sum(c in b"\t\n\r" or 32 <= c <= 126 for c in sample)
                    < len(sample) * 0.8
                )
            ):
                return None, "skipped-non-html"
    return bytes(body), ""


def _body_fingerprint(body: bytes) -> tuple:
    return len(body), hashlib.sha256(body).hexdigest()


def _sizes_close(a: int, b: int, tolerance: float = CATCH_ALL_SIZE_TOLERANCE) -> bool:
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tolerance


def is_same_domain(host: str, domain: str) -> bool:
    """True when `host` (a fetched response's own netloc) is the
    government's own domain or a subdomain of it -- the "probed URL's own
    path" case this WO's fix disqualifies as evidence. False when the
    request actually landed on a different host (a real redirect or
    delegation to a vendor's own infrastructure), which is genuine page
    evidence rather than a guessed path."""
    host = (host or "").lower()
    domain = (domain or "").lower()
    if not host or not domain:
        return True
    return host == domain or host.endswith("." + domain)


def is_catch_all_response(body: bytes, refs: dict) -> bool:
    """WO-278: compares one probed response's body against the domain's
    own nonsense-path and homepage references (see
    `fetch_domain_reference()`). A match on size or hash against EITHER
    reference means this host answers an unrelated path with (close to)
    the same body it gave for a made-up path or its own homepage -- the
    exact catch-all shape WO-260/268/272 already documented."""
    if not body:
        return False
    size, digest = _body_fingerprint(body)
    for ref in refs.values():
        if ref is None:
            continue
        ref_size, ref_digest = ref
        if digest == ref_digest or _sizes_close(size, ref_size):
            return True
    return False


def fetch_domain_reference(domain: str) -> dict:
    """Fetches one nonsense path and the homepage ONCE per government,
    used only to detect a catch-all host (WO-278's fix). A fetch failure
    is recorded as None rather than raising -- a domain with no usable
    reference simply never catches anything via this guard; the 800-byte
    floor and content-only matching in `fetch_and_score()` are the
    primary defenses, this is the second one, so it fails open rather
    than blocking the whole domain on a transient error."""
    label = "".join(
        random.choices(string.ascii_lowercase + string.digits, k=NONSENSE_LABEL_LEN)
    )
    nonsense_url = f"https://{domain}/rtr-probe-{label}"
    homepage_url = f"https://{domain}/"
    refs = {}
    for kind, url in (("nonsense", nonsense_url), ("homepage", homepage_url)):
        try:
            resp = polite_fetch(url, method="GET")
            refs[kind] = (
                _body_fingerprint(resp.content)
                if resp.status_code == 200 and resp.content
                else None
            )
        except Exception:  # noqa: BLE001
            refs[kind] = None
    return refs


def name_matches(html: str, city_name: str, state: str) -> bool:
    if not html or not city_name:
        return False
    text = html.lower()
    city_tokens = re.findall(r"[a-z]+", city_name.lower())
    city_hit = any(len(t) > 2 and t in text for t in city_tokens)
    state_hit = bool(state) and state.lower() in text
    return city_hit and state_hit


def body_hash(body: bytes) -> str:
    return hashlib.sha1(body[:4000]).hexdigest() if body else ""


def nonsense_path() -> str:
    token = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    return f"/__wo282_nonsense_{token}__"


def catchall_signature(domain: str) -> dict:
    """Fetch one nonsense path for this host, once. Returns a signature
    dict (status, body_len, body_hash) used to recognize a soft-200
    catch-all template answering every path the same way."""
    url = f"https://{domain}{nonsense_path()}"
    try:
        resp = polite_fetch(url, method="GET")
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
    wo282_recon.jsonl for its cached homepage HTML path -- phase 3 keeps
    no separate index, this is a small file read per government, far
    cheaper than a live refetch."""
    # Lazy module-level cache: built once, reused across threads (read
    # only after the sweep starts, so no lock needed beyond the GIL's own
    # atomic dict assignment).
    global _HOMEPAGE_INDEX
    if _HOMEPAGE_INDEX is None:
        idx: dict[str, dict] = {}
        recon_path = RESEARCH_DIR / "wo282_recon.jsonl"
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
    body, used_archive = try_wayback_archived_body(url)
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
            head_resp = polite_fetch(url, method="HEAD")
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
            resp = polite_fetch(url, method="GET")
            out["http_status"] = resp.status_code
            body = resp.content or b""
            out["body_len"] = len(body)
            if resp.status_code == 200 and resp.text:
                if is_challenge(resp.text):
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
        out["name_match"] = name_matches(html, name, state)
        signals = platform_fingerprints.fingerprint(html, url=url)
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
    name = row.get("name", "")
    state = row.get("state", "")
    try:
        candidates = json.loads(row.get("candidates_json") or "[]")
    except Exception:  # noqa: BLE001
        candidates = []
    sig = catchall_signature(domain)
    results = []
    for rank, c in enumerate(candidates[:5], start=1):
        t0 = time.monotonic()
        r = fetch_and_score_v2(c["url"], name, state, sig)
        r.update(
            domain=domain,
            gov_id=row.get("gov_id", ""),
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
    remaining = [r for r in classified if r["domain"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(classified)}")

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
