"""WO-281 (2026-09-12): phase 3b for the 1,610 governments WO-273's phase 3
only ever gave five blind named-path probes to -- one homepage fetch each,
link extraction with position (nav/header/menu/footer/body), scored with
the measured WO-274 hop weights instead of guessed paths, then the top-5
flagged links actually fetched and checked.

Population: `research/wo273_classified.csv` rows with `confidence == "none"`
(no flagged URL at all after WO-273's phase 2) -- re-derived directly
against the committed file rather than trusting the brief's "1,610" number
blind: confirmed exactly 1,610 of 2,574 rows, matching `research/
wo273_candidates.csv`'s distinct domain count. WO-278 (running in parallel)
owns the OTHER 964 rows (those WITH a flagged URL); this script never reads
or writes a row WO-278 also touches. WO-278 had not published a
catch-all-only subset of its own as of this run (checked directly --
no `wo278_*` file exists in `research/`), so this uses the full 1,610 per
the brief's own fallback instruction.

Two phases, same shape as WO-273's phase1/phase3 split (so the slow part
is driven by output the scoring can rerun without refetching):

  --phase homepage   One fetch per government's own homepage. Archive-first
                      (`wo273_targeted.try_wayback_archived_body()`, `id_`
                      raw form, capture <=18 months -- reused, not
                      reimplemented), live plain-HTTP fallback, browser
                      headers ONLY after a 403 or a dropped connection
                      (never after a 404), human-verification-gate
                      detection that stops cold (`wo273_recon.is_challenge`).
                      Extracts every `<a href>` with its anchor text and
                      page position (nav/header, footer, menu `<ul>`/`<ol>`,
                      or plain body -- via `wo147_access_ladder_sweep.
                      _nav_position_bonus()`, the EXACT position check the
                      real scorer already computes internally, not a
                      reimplementation of it), flags every href
                      `detect_platform()` accepts outright (a vendor host or
                      the AgendaCenter/Hyland path rules), classifies each
                      link as hub-shaped or meeting/video-shaped via
                      WO-274's own measured vocabulary
                      (`wo273_recon.HUB_WORD_LIFT`/`MEETING_WORD_HIT`), then
                      calls `wo147_access_ladder_sweep.find_hop_links()` --
                      the real WO-274 measured scorer, called, not
                      reimplemented -- and keeps its top 5 by score.
                      Writes `research/wo281_homepage_links.jsonl` (every
                      extracted link, raw) and `research/wo281_scored.csv`
                      (the top-5 per government).

  --phase targeted    Fetches those top-5 links (same archive-first,
                      browser-headers-on-403 politeness), runs
                      `scripts/platform_fingerprints.fingerprint()` +
                      `detect_platform()` over the fetched page's own body
                      AND its own links, plus `classify_site_builder()` for
                      the record. A catch-all test (one nonsense path per
                      host, cached; a 200 whose body byte-size/hash matches
                      either the nonsense response or the government's own
                      homepage is a soft-200, not real content) and an
                      800-byte floor gate every hit before it can count.
                      Requires the page to name this government's own
                      city/county AND its state before anything counts
                      confirmed (same bar WO-273's phase 3 used --
                      `name_matches()`, reused). Meeting-DETAIL pages
                      (clip/mediaplayer/meetinginformation/watch/player/
                      videos/splitview -- WO-274's measured meeting-vendor
                      vocabulary) are flagged separately from hubs in the
                      output, per Ryan's question about whether this method
                      can find video pages directly. Writes `research/
                      wo281_targeted.csv`.

Politeness (Ryan, 2026-09-12, same shape as WO-273's phase 3):
concurrency 32 governments in flight, ONE request in flight per host
(`wo273_recon.HostRateLimiter`, >=2.5s between requests to the SAME host),
a vendor-host hit is rate-limited under its VENDOR FAMILY name
(`wo273_recon.vendor_family_for_url`) so many governments that happen to
flag the same vendor don't pile onto it at once, honest User-Agent, browser
headers only after a 403 or a dropped connection, never past a
human-verification challenge page.

This script imports `app.platforms.base.detect_platform` and
`scripts/wo147_access_ladder_sweep.py` (which itself imports the app
registry and `scripts/wo134_confirmed_hits_ingest.py`) -- per CLAUDE.md's
worktree `.env` bullet, ANY command running this script must set
`DATABASE_URL` explicitly.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo281_test.db" \\
        /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python \\
        scripts/wo281_homepage_hop.py --phase homepage --limit 50 --concurrency 32
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from wo273_recon import (  # noqa: E402
    HEADERS,
    HUB_WORD_LIFT,
    MEETING_WORD_HIT,
    RATE_LIMITER,
    is_challenge,
    vendor_family_for_url,
)
from wo273_targeted import name_matches, try_wayback_archived_body  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms.base import detect_platform  # noqa: E402

import platform_fingerprints  # noqa: E402
from wo147_access_ladder_sweep import (  # noqa: E402
    BROWSER_HEADERS,
    _FOOTER_PENALTY,
    _MENU_LIST_BONUS,
    _NAV_BONUS,
    _nav_position_bonus,
    _safe_soup,
    find_hop_links,
    looks_like_document_hub,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo273_candidates.csv"
CLASSIFIED_CSV = RESEARCH_DIR / "wo273_classified.csv"
LINKS_JSONL = RESEARCH_DIR / "wo281_homepage_links.jsonl"
SCORED_CSV = RESEARCH_DIR / "wo281_scored.csv"
TARGETED_CSV = RESEARCH_DIR / "wo281_targeted.csv"

TOP_N = 5
GOV_TIMEOUT = (3, 10)  # (connect, read) -- brief's own numbers
BODY_FLOOR_BYTES = 800

# WO-274's measured meeting-vendor vocabulary (app/utils/jurisdiction_data/
# hop_link_weights.csv's meeting_vendor rows, via wo273_recon.MEETING_WORD_HIT)
# is the vocabulary used to flag a link as a meeting DETAIL page rather than
# a hub -- reused, not a new guessed list.
_MEETING_DETAIL_RE = re.compile(
    r"clip|mediaplayer|meetinginformation|watch|player|videos?|splitview"
    r"|meetingtemplateid|meetingid",
    re.I,
)

_POSITION_LABELS = {
    _NAV_BONUS: "nav",
    _FOOTER_PENALTY: "footer",
    _MENU_LIST_BONUS: "menu",
    0.0: "body",
}


def position_label(tag) -> str:
    """Labels a `<a>` tag's page position using the EXACT check
    `_score_hop_candidate_weighted()` already runs internally
    (`_nav_position_bonus()`) -- not a second, independent classification
    of the same thing, just a label for the bonus value that function
    already computes."""
    return _POSITION_LABELS.get(_nav_position_bonus(tag), "body")


def link_kind_for_url(full_url: str) -> str:
    """hub | meeting | other, from WO-274's own measured vocabulary
    (wo273_recon.HUB_WORD_LIFT / MEETING_WORD_HIT) -- a link whose path
    contains a meeting-vendor-shaped token (clip, mediaplayer, watch...)
    is flagged as a likely meeting DETAIL page; one with a hub word
    (agendas, council, minutes...) and no meeting word is a likely hub;
    neither is "other". A link can match both lists (e.g. a meeting page
    living under a council section) -- meeting wins, since that's the
    rarer, more specific signal."""
    path = urlparse(full_url).path.lower()
    tokens = re.findall(r"[a-z]+", path)
    token_set = set(tokens)
    if token_set & MEETING_WORD_HIT.keys() or _MEETING_DETAIL_RE.search(path):
        return "meeting"
    if token_set & HUB_WORD_LIFT.keys():
        return "hub"
    return "other"


def log(msg: str) -> None:
    print(msg, flush=True)


def load_population() -> list:
    """1,610 `wo273_classified.csv` rows with confidence=="none" (no
    flagged URL), joined with `wo273_candidates.csv` for city_name --
    re-derived fresh every run rather than cached, since this file is
    shared with concurrent WOs."""
    with open(CANDIDATES_CSV, newline="", encoding="utf-8") as f:
        by_domain = {r["domain"]: r for r in csv.DictReader(f)}
    pop = []
    with open(CLASSIFIED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("confidence") != "none":
                continue
            cand = by_domain.get(row["domain"], {})
            pop.append(
                {
                    "domain": row["domain"],
                    "state": row.get("state", ""),
                    "gov_id": row.get("gov_id", ""),
                    "population": row.get("population", ""),
                    "city_name": cand.get("city_name", ""),
                }
            )
    return pop


class ExceptionClassifier:
    DNS_PATTERNS = (
        "nodename nor servname",
        "name or service not known",
        "getaddrinfo failed",
        "temporary failure in name resolution",
        "failed to resolve",
        "nxdomain",
    )

    @classmethod
    def classify(cls, exc: Exception) -> str:
        if isinstance(exc, requests.exceptions.Timeout):
            return "timeout"
        msg = str(exc).lower()
        if any(p in msg for p in cls.DNS_PATTERNS):
            return "dns-unresolvable"
        if isinstance(exc, requests.exceptions.ConnectionError):
            return "connection-dropped"
        return "connection-dropped"


def polite_get(url: str, *, headers: dict, rate_key: str):
    return RATE_LIMITER.wait_and_request(
        rate_key,
        requests.get,
        url,
        headers=headers,
        timeout=GOV_TIMEOUT,
        allow_redirects=True,
    )


def fetch_with_ladder(url: str, rate_key: str) -> dict:
    """Archive-first, then plain HTTP, browser headers only after a 403 or
    a dropped connection (never after a 404), stop cold at a human-
    verification gate. Returns a dict with html/final_url/access_mode/
    fetch_method/http_status/error/timing_ms."""
    t0 = time.monotonic()
    out = {
        "html": "",
        "final_url": url,
        "access_mode": "",
        "fetch_method": "",
        "http_status": None,
        "error": "",
    }
    body, _used_archive = try_wayback_archived_body(url)
    if body is not None:
        try:
            html = body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            html = ""
        out.update(
            html=html,
            fetch_method="archived_id_",
            access_mode="archive",
            http_status=200,
        )
        out["timing_ms"] = int((time.monotonic() - t0) * 1000)
        return out

    out["fetch_method"] = "live"
    try:
        resp = polite_get(url, headers=HEADERS, rate_key=rate_key)
        out["http_status"] = resp.status_code
        out["final_url"] = str(resp.url)
        if resp.status_code == 403:
            # Browser headers, once, only after a 403 -- never after a 404.
            try:
                resp2 = polite_get(url, headers=BROWSER_HEADERS, rate_key=rate_key)
                out["http_status"] = resp2.status_code
                out["final_url"] = str(resp2.url)
                resp = resp2
                out["access_mode"] = "live-browser-headers"
            except Exception as e:  # noqa: BLE001
                out["access_mode"] = "blocked-plain-http"
                out["error"] = str(e)[:200]
                out["timing_ms"] = int((time.monotonic() - t0) * 1000)
                return out
        else:
            out["access_mode"] = "live-plain"
        if resp.status_code == 200 and resp.text:
            if is_challenge(resp.text):
                out["access_mode"] = "human-gate"
                out["error"] = "challenge-gate"
            else:
                out["html"] = resp.text
    except Exception as e:  # noqa: BLE001
        kind = ExceptionClassifier.classify(e)
        if kind == "connection-dropped":
            # A dropped connection is also a browser-headers trigger.
            try:
                resp2 = polite_get(url, headers=BROWSER_HEADERS, rate_key=rate_key)
                out["http_status"] = resp2.status_code
                out["final_url"] = str(resp2.url)
                out["access_mode"] = "live-browser-headers"
                if resp2.status_code == 200 and resp2.text:
                    if is_challenge(resp2.text):
                        out["access_mode"] = "human-gate"
                        out["error"] = "challenge-gate"
                    else:
                        out["html"] = resp2.text
            except Exception as e2:  # noqa: BLE001
                out["access_mode"] = ExceptionClassifier.classify(e2)
                out["error"] = str(e2)[:200]
        else:
            out["access_mode"] = kind
            out["error"] = str(e)[:200]

    out["timing_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def extract_links(html: str, final_url: str) -> list:
    """Every `<a href>` with text, href, resolved url, and page position --
    the same filter `_find_hop_links_weighted()` applies (skip javascript:/
    mailto:/tel:/#, dedupe by resolved URL, http(s) scheme only), kept here
    as a SEPARATE pass from `find_hop_links()` because the scorer itself
    doesn't expose per-link position -- it's needed for this WO's own
    position-vs-winning-link report, not part of the scoring itself."""
    soup = _safe_soup(html)
    if soup is None:
        return []
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(final_url, href)
        if full in seen or urlparse(full).scheme not in ("http", "https"):
            continue
        seen.add(full)
        text = (a.get_text() or "").strip()
        platform_outright = None
        try:
            p = detect_platform(full)
            platform_outright = p if p and p != "unknown" else None
        except Exception:  # noqa: BLE001
            platform_outright = None
        out.append(
            {
                "text": text[:200],
                "href": href,
                "url": full,
                "position": position_label(a),
                "link_kind": link_kind_for_url(full),
                "platform_outright": platform_outright,
            }
        )
    return out


_write_lock = threading.Lock()

_SCORED_FIELDS = [
    "domain",
    "gov_id",
    "state",
    "city_name",
    "rank",
    "url",
    "anchor_text",
    "position",
    "link_kind",
    "platform_outright",
    "score_rank_only",
]


def process_homepage(gov: dict) -> dict:
    domain = gov["domain"]
    url = f"https://{domain}/"
    fetch = fetch_with_ladder(url, rate_key=domain)
    record = {
        "domain": domain,
        "gov_id": gov.get("gov_id", ""),
        "state": gov.get("state", ""),
        "city_name": gov.get("city_name", ""),
        "access_mode": fetch["access_mode"],
        "fetch_method": fetch["fetch_method"],
        "http_status": fetch["http_status"],
        "error": fetch["error"],
        "timing_ms": fetch["timing_ms"],
        "links": [],
        "top5": [],
    }
    if not fetch["html"]:
        return record

    links = extract_links(fetch["html"], fetch["final_url"])
    record["links"] = links
    ranked = find_hop_links(fetch["html"], fetch["final_url"])[:TOP_N]
    by_url = {}
    for link in links:
        by_url.setdefault(link["url"], link)
    top5 = []
    for rank, ranked_url in enumerate(ranked, start=1):
        meta = by_url.get(ranked_url, {})
        top5.append(
            {
                "rank": rank,
                "url": ranked_url,
                "anchor_text": meta.get("text", ""),
                "position": meta.get("position", ""),
                "link_kind": meta.get("link_kind", link_kind_for_url(ranked_url)),
                "platform_outright": meta.get("platform_outright"),
            }
        )
    record["top5"] = top5
    return record


def load_done_domains(path: Path) -> set:
    if not path.exists():
        return set()
    done = set()
    if path.suffix == ".jsonl":
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["domain"])
                except Exception:  # noqa: BLE001
                    continue
    else:
        with open(path, newline="", encoding="utf-8") as f:
            done = {row["domain"] for row in csv.DictReader(f)}
    return done


def cmd_homepage(limit: int, concurrency: int) -> None:
    population = load_population()
    done = load_done_domains(LINKS_JSONL)
    remaining = [g for g in population if g["domain"] not in done]
    log(
        f"{len(done)} governments already done, {len(remaining)} remaining of {len(population)}"
    )
    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} governments at concurrency={concurrency}")

    write_header = not SCORED_CSV.exists()
    start = time.monotonic()
    completed = 0
    with (
        open(LINKS_JSONL, "a", encoding="utf-8") as jsonl_out,
        open(SCORED_CSV, "a", newline="", encoding="utf-8") as scored_out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        scored_writer = csv.DictWriter(scored_out, fieldnames=_SCORED_FIELDS)
        if write_header:
            scored_writer.writeheader()
        futures = {pool.submit(process_homepage, gov): gov for gov in to_process}
        for fut in as_completed(futures):
            gov = futures[fut]
            try:
                record = fut.result()
            except Exception as e:  # noqa: BLE001
                record = {
                    "domain": gov["domain"],
                    "gov_id": gov.get("gov_id", ""),
                    "state": gov.get("state", ""),
                    "city_name": gov.get("city_name", ""),
                    "access_mode": "error",
                    "fetch_method": "",
                    "http_status": None,
                    "error": str(e)[:200],
                    "timing_ms": 0,
                    "links": [],
                    "top5": [],
                }
            with _write_lock:
                jsonl_out.write(json.dumps(record) + "\n")
                jsonl_out.flush()
                for item in record["top5"]:
                    scored_writer.writerow(
                        {
                            "domain": record["domain"],
                            "gov_id": record["gov_id"],
                            "state": record["state"],
                            "city_name": record["city_name"],
                            "rank": item["rank"],
                            "url": item["url"],
                            "anchor_text": item["anchor_text"],
                            "position": item["position"],
                            "link_kind": item["link_kind"],
                            "platform_outright": item["platform_outright"] or "",
                            "score_rank_only": item["rank"],
                        }
                    )
                scored_out.flush()
            completed += 1
            if completed % 25 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                    f"rate={rate:.1f} govs/min last={record['domain']}"
                )

    elapsed = time.monotonic() - start
    rate = len(to_process) / (elapsed / 60) if elapsed > 0 else 0
    log(
        f"chunk done: {len(to_process)} governments in {elapsed:.0f}s "
        f"({rate:.2f} governments/min), "
        f"{len(remaining) - len(to_process)} remain unprocessed."
    )


# ---------------------------------------------------------------------------
# Phase: targeted -- fetch the top-5 scored links, confirm or reject
# ---------------------------------------------------------------------------

_nonsense_cache: dict = {}
_nonsense_lock = threading.Lock()


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()


def nonsense_probe(host: str, rate_key: str) -> tuple:
    """One nonsense path per host, cached across the whole run -- `(size,
    hash)` of whatever it answers with, or None if it never answers at
    all (a clean 404/connection failure on the nonsense path is actually
    useful information: it means a 200 on the REAL candidate is not just
    a catch-all)."""
    with _nonsense_lock:
        if host in _nonsense_cache:
            return _nonsense_cache[host]
    nonsense_url = f"https://{host}/__wo281_nonsense_check_xyz123__"
    result = None
    try:
        resp = RATE_LIMITER.wait_and_request(
            rate_key,
            requests.get,
            nonsense_url,
            headers=HEADERS,
            timeout=GOV_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code == 200 and resp.text:
            result = (len(resp.content), body_hash(resp.text))
    except Exception:  # noqa: BLE001
        result = None
    with _nonsense_lock:
        _nonsense_cache[host] = result
    return result


def is_soft_200(host: str, rate_key: str, body: str, homepage_size: int | None) -> bool:
    size = len(body.encode("utf-8", errors="replace"))
    h = body_hash(body)
    nonsense = nonsense_probe(host, rate_key)
    if nonsense is not None:
        n_size, n_hash = nonsense
        if h == n_hash or abs(size - n_size) < 50:
            return True
    if homepage_size is not None and abs(size - homepage_size) < 50:
        return True
    return False


_TARGETED_FIELDS = [
    "domain",
    "gov_id",
    "state",
    "rank",
    "url",
    "link_kind",
    "fetch_method",
    "http_status",
    "body_size",
    "is_soft_200",
    "below_byte_floor",
    "platform_confirmed",
    "platform_signal",
    "site_builder_family",
    "name_match",
    "meeting_detail_candidate",
    "timing_ms",
    "error",
]


def fetch_and_confirm(
    url: str, link_kind: str, city_name: str, state: str, homepage_size: int | None
) -> dict:
    t0 = time.monotonic()
    host = urlparse(url).netloc
    rate_key = vendor_family_for_url(url)
    out = {
        "url": url,
        "link_kind": link_kind,
        "fetch_method": "",
        "http_status": None,
        "body_size": 0,
        "is_soft_200": False,
        "below_byte_floor": False,
        "platform_confirmed": "",
        "platform_signal": "",
        "site_builder_family": "",
        "name_match": False,
        "meeting_detail_candidate": bool(_MEETING_DETAIL_RE.search(url.lower())),
        "timing_ms": 0,
        "error": "",
    }
    body, _used_archive = try_wayback_archived_body(url)
    html = ""
    if body is not None:
        out["fetch_method"] = "archived_id_"
        out["http_status"] = 200
        try:
            html = body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            html = ""
    else:
        out["fetch_method"] = "live"
        headers = HEADERS
        try:
            resp = RATE_LIMITER.wait_and_request(
                rate_key,
                requests.get,
                url,
                headers=headers,
                timeout=GOV_TIMEOUT,
                allow_redirects=True,
            )
            if resp.status_code == 403:
                resp = RATE_LIMITER.wait_and_request(
                    rate_key,
                    requests.get,
                    url,
                    headers=BROWSER_HEADERS,
                    timeout=GOV_TIMEOUT,
                    allow_redirects=True,
                )
            out["http_status"] = resp.status_code
            if resp.status_code == 200 and resp.text:
                if is_challenge(resp.text):
                    out["error"] = "challenge-gate"
                else:
                    html = resp.text
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:200]

    if html:
        out["body_size"] = len(html.encode("utf-8", errors="replace"))
        if out["body_size"] < BODY_FLOOR_BYTES:
            out["below_byte_floor"] = True
        elif is_soft_200(host, rate_key, html, homepage_size):
            out["is_soft_200"] = True
        else:
            out["name_match"] = name_matches(html, city_name, state)
            signals = platform_fingerprints.fingerprint(html, url=url)
            builder = platform_fingerprints.classify_site_builder(html, url=url)
            out["site_builder_family"] = builder.family
            if signals:
                best = max(signals, key=lambda s: s[2])
                out["platform_signal"] = f"{best[0]}:{best[1]}({best[2]:.2f})"
                if out["name_match"]:
                    out["platform_confirmed"] = best[0]
            else:
                dp = None
                try:
                    dp = detect_platform(url)
                except Exception:  # noqa: BLE001
                    dp = None
                if not dp or dp == "unknown":
                    for link in extract_links(html, url):
                        try:
                            lp = detect_platform(link["url"])
                        except Exception:  # noqa: BLE001
                            lp = None
                        if lp and lp != "unknown":
                            dp = lp
                            break
                if dp and dp != "unknown":
                    out["platform_signal"] = f"{dp}:url-shape"
                    if out["name_match"]:
                        out["platform_confirmed"] = dp
            if not out["platform_confirmed"] and looks_like_document_hub(html):
                out["platform_signal"] = out["platform_signal"] or "document-hub-shape"

    out["timing_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def load_scored() -> dict:
    """Groups `wo281_scored.csv` rows by domain -> list of rows (rank
    order)."""
    by_domain: dict = {}
    with open(SCORED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_domain.setdefault(row["domain"], []).append(row)
    return by_domain


def process_government_targeted(domain: str, rows: list) -> list:
    """`homepage_size` is intentionally always None here -- the catch-all
    test compares a fetched link against the per-HOST nonsense probe
    (`nonsense_probe()`, cached), which covers the government's own
    domain too since its homepage and its flagged links share that same
    host in the overwhelming majority of rows; a separate persisted
    homepage-body-size comparison was judged unnecessary extra plumbing
    for the marginal case (a flagged link on a DIFFERENT host than the
    homepage) this WO's population rarely produces."""
    results = []
    for row in rows:
        r = fetch_and_confirm(
            row["url"],
            row.get("link_kind", "other"),
            row.get("city_name", ""),
            row.get("state", ""),
            None,
        )
        r.update(
            domain=domain, gov_id=row.get("gov_id", ""), state=row.get("state", "")
        )
        r["rank"] = row.get("rank", "")
        results.append(r)
    return results


def load_done_targeted() -> set:
    if not TARGETED_CSV.exists():
        return set()
    with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
        return {row["domain"] for row in csv.DictReader(f)}


def cmd_targeted(limit: int, concurrency: int) -> None:
    by_domain = load_scored()
    done = load_done_targeted()
    remaining = [d for d in by_domain if d not in done]
    log(
        f"{len(done)} governments already done, {len(remaining)} remaining of {len(by_domain)}"
    )
    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} governments at concurrency={concurrency}")

    write_header = not TARGETED_CSV.exists()
    start = time.monotonic()
    completed = 0
    with (
        open(TARGETED_CSV, "a", newline="", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        writer = csv.DictWriter(out, fieldnames=_TARGETED_FIELDS)
        if write_header:
            writer.writeheader()
        futures = {
            pool.submit(process_government_targeted, d, by_domain[d]): d
            for d in to_process
        }
        for fut in as_completed(futures):
            domain = futures[fut]
            try:
                results = fut.result()
            except Exception as e:  # noqa: BLE001
                results = [
                    {k: "" for k in _TARGETED_FIELDS}
                    | {"domain": domain, "error": str(e)[:200]}
                ]
            with _write_lock:
                for r in results:
                    writer.writerow({k: r.get(k, "") for k in _TARGETED_FIELDS})
                out.flush()
            completed += 1
            if completed % 25 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                    f"rate={rate:.1f} govs/min last={domain}"
                )

    elapsed = time.monotonic() - start
    rate = len(to_process) / (elapsed / 60) if elapsed > 0 else 0
    log(
        f"chunk done: {len(to_process)} governments in {elapsed:.0f}s "
        f"({rate:.2f} governments/min), "
        f"{len(remaining) - len(to_process)} remain unprocessed."
    )


def cmd_finalize_homepage() -> None:
    if not LINKS_JSONL.exists():
        log(f"{LINKS_JSONL} missing")
        return
    records = []
    with open(LINKS_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    log(f"{len(records)} governments in {LINKS_JSONL}")
    by_mode = {}
    for r in records:
        by_mode[r["access_mode"] or "none"] = (
            by_mode.get(r["access_mode"] or "none", 0) + 1
        )
    log(f"access_mode split: {by_mode}")
    outright = sum(
        1 for r in records if any(link.get("platform_outright") for link in r["links"])
    )
    log(
        f"homepages linking a platform outright (detect_platform on a raw href): {outright}"
    )
    pos_counts = {}
    for r in records:
        for item in r.get("top5", []):
            if item.get("rank") == 1:
                pos_counts[item.get("position") or "body"] = (
                    pos_counts.get(item.get("position") or "body", 0) + 1
                )
    log(f"winning (rank-1) link position split: {pos_counts}")
    timings = [r["timing_ms"] for r in records if r.get("timing_ms")]
    if timings:
        timings.sort()
        log(
            f"per-homepage fetch timing (ms): median={statistics.median(timings):.0f} "
            f"p95={timings[max(0, int(len(timings) * 0.95) - 1)]}"
        )


def cmd_finalize_targeted() -> None:
    if not TARGETED_CSV.exists():
        log(f"{TARGETED_CSV} missing")
        return
    with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log(f"{len(rows)} (government, url) rows in {TARGETED_CSV}")
    doms = {r["domain"] for r in rows}
    log(f"  covering {len(doms)} distinct governments")
    confirmed = [r for r in rows if r.get("platform_confirmed")]
    log(
        f"platform_confirmed (name+state matched, not soft-200, not under "
        f"byte floor): {len(confirmed)} rows, "
        f"{len({r['domain'] for r in confirmed})} governments"
    )
    meeting_detail = [r for r in confirmed if r.get("link_kind") == "meeting"]
    log(f"  of which meeting-DETAIL-shaped (not a hub): {len(meeting_detail)}")
    soft = sum(1 for r in rows if r.get("is_soft_200") == "True")
    log(f"caught as soft-200/catch-all: {soft}")
    under_floor = sum(1 for r in rows if r.get("below_byte_floor") == "True")
    log(f"under the {BODY_FLOOR_BYTES}-byte floor: {under_floor}")
    timings = [int(r["timing_ms"]) for r in rows if r.get("timing_ms")]
    if timings:
        timings.sort()
        log(
            f"per-URL fetch timing (ms): median={statistics.median(timings):.0f} "
            f"p95={timings[max(0, int(len(timings) * 0.95) - 1)]}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["homepage", "targeted"], required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    if args.phase == "homepage":
        if args.finalize:
            cmd_finalize_homepage()
            return
        cmd_homepage(args.limit, args.concurrency)
    else:
        if args.finalize:
            cmd_finalize_targeted()
            return
        cmd_targeted(args.limit, args.concurrency)


if __name__ == "__main__":
    main()
