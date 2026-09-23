"""WO-282 (2026-09-12): passive discovery v2, phase 2 -- offline
classification over phase 1's raw recon file (`wo282_recon.jsonl`).

Builds on WO-273's own scoring, moved in verbatim (WO-1019, 2026-09-23,
now that WO-273's own scripts are retired) rather than duplicated:
vendor-host/DNS platform detection, the measured HUB/MEETING flag-word
lift tables (imported from `wo282_recon.py`, which is where the flag-word
tables themselves live), and the named first-party path shapes. Adds what
WO-273's phase 2 could not do because WO-273's phase 1 never fetched a
homepage:

  - Every homepage link phase 1 cached (recon record's `homepage.links`,
    each with href/anchor text/`nav`|`footer`|`menu`|`body` position) is
    re-scored with `find_hop_links()` (`wo147_access_ladder_sweep.py`,
    the WO-274 measured weights in `hop_link_weights.csv`), reading the
    gzipped homepage HTML phase 1 saved (`homepage.homepage_gz_path`) --
    no network call. `find_hop_links()` doesn't itself report which link
    it picked, so its ranked URL list is joined back against the raw
    `homepage.links` records (by href) to recover `source` (homepage-nav
    / homepage-footer / homepage-body -- "menu" folds into "body" for
    this column, since neither WO-274's scorer nor the population table
    below distinguishes a menu list from a bare list) and to keep the
    HOMEPAGE candidates in with the sitemap/archive/DNS ones this
    script's WO-273 parent already scores.
  - `detect_platform()` (`app/platforms/base.py`) is run on every
    homepage href too, not just sitemap/Wayback/CommonCrawl URLs --
    counts as `kind=platform`, `confidence=high`, same as a vendor-host
    sitemap URL.
  - `classify_site_builder()` (`scripts/platform_fingerprints.py`,
    delegates to `cms_fingerprint.classify()`) runs on the cached
    homepage HTML, for the record (reported in the writeup's summary,
    not used to rank candidates).
  - A pre-flag for a catch-all-shaped site: this phase has no live
    network access to run the real nonsense-path test (that's phase 3's
    job), so it can only flag a weak proxy here -- a homepage with fewer
    than 5 extracted links at all (a real catch-all template WO-278
    found tends to be a near-empty parked-domain shell). Recorded as
    `catchall_preflag`, explicitly weak, never used to drop a candidate
    on its own.

Output: `research/wo282_classified.csv`, one row per government, with a
`candidates_json` column holding the ranked list phase 3 reads (top-5
taken there): `[{url, source, score, kind}, ...]`, `source` one of
homepage-nav / homepage-footer / homepage-body / sitemap / archive /
dns, `kind` one of platform / hub / meeting-detail.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo282_classify_scratch.db" \\
        .venv/bin/python scripts/wo282_classify.py

Needs DATABASE_URL set (unused, never opened) only because
`app.platforms.base` is imported transitively for `detect_platform()`
and some of that package's modules touch `os.environ` at import time;
does no network I/O itself and opens no database connection.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wo282_recon import (  # noqa: E402
    _PATH_SHAPE_PLATFORMS,
    _PLATFORM_ALIASES,
    hub_score,
    meeting_score,
)

from app.platforms.base import detect_platform  # noqa: E402
import wo147_access_ladder_sweep as w147  # noqa: E402
from platform_fingerprints import classify_site_builder  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo282_recon.jsonl"
CLASSIFIED_CSV = RESEARCH_DIR / "wo282_classified.csv"

CATCHALL_PREFLAG_LINK_FLOOR = 5

# A government's own hub/listing page can only ever live on its own domain
# or a recognized meeting-platform vendor -- never on a general-purpose
# video/social host. Confirmed live 2026-09-23 (Ryan): 11+ real phase-3
# fetches wasted on things like vimeo.com/search?q=Ward%20County%20
# Commissioners and vimeo.com/rockdalegov, both scored as a real "hub"
# candidate (kind="hub") because detect_platform() only recognizes a
# specific VIDEO url shape on these hosts (a numeric id or known embed
# path), not a channel/search/profile page -- so a link `find_hop_links()`
# ranked on one of these hosts fell through this function's "not a known
# platform -> must be a hub" assumption, and the URL's own path text
# (a search query, a channel slug) happened to contain real hub/meeting
# keywords, scoring it high enough to fetch. These hosts are excluded
# from candidate consideration entirely here, not reclassified as
# "platform" -- a search/profile page isn't a resolvable meeting either,
# so there is nothing useful to keep for it.
_THIRD_PARTY_HOST_APEXES = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "vimeo.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "tiktok.com",
        "linkedin.com",
    }
)


def _host_apex(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def is_unresolvable_third_party_host(url: str) -> bool:
    """True when `url` sits on a general-purpose video/social host AND
    isn't a URL shape `detect_platform()` can actually resolve (a specific
    video/embed). Never true for a URL `detect_platform()` already
    recognizes -- that case is real signal (`kind="platform"`), not noise."""
    if _host_apex(url) not in _THIRD_PARTY_HOST_APEXES:
        return False
    return detect_platform(url) == "unknown"


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Moved here from wo273_classify.py (WO-1019, 2026-09-23): WO-273's own
# scripts are retired, but this vendor-host/DNS platform scoring is real,
# shared logic this file (and every other wo282_classify.py-style import
# of it) still calls. Moved verbatim, not rewritten. `dns_subdomain_
# candidates()`/`DNS_VIDEO_LABELS`/`DNS_HUB_LABELS`/`DNS_HUB_SCORE`/
# `DNS_MEETING_SCORE` -- WO-273's own A-record-only guessed-subdomain
# rule (#1275, 2026-09-21) -- are intentionally NOT part of this move;
# see the separate block below this one for that addition, wired into
# `classify_record()`'s own candidate building.
# --------------------------------------------------------------------------


def vendor_platform_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for alias, platform in _PLATFORM_ALIASES.items():
        if alias in host:
            return platform
    path = urlparse(url).path
    for rx, platform in _PATH_SHAPE_PLATFORMS:
        if rx.search(path):
            return platform
    return ""


def all_urls_from_record(rec: dict) -> list:
    """Every URL phase 1 saw for this government, from every source it
    recorded -- deduplicated, order preserved (sitemap first, since it's
    the government's own stated navigation; then the Wayback CDX top-N
    scored URLs -- `top_urls`; then Common Crawl)."""
    urls = []
    seen = set()

    def add_many(lst):
        for u in lst or []:
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

    add_many(rec.get("sitemap_urls"))
    add_many((rec.get("wayback_index") or {}).get("top_urls"))
    add_many((rec.get("common_crawl") or {}).get("urls"))
    return urls


def dns_platform(rec: dict) -> tuple:
    """Returns (platform, evidence) from DNS, or ("", "") if none.
    Mirrors wo282_recon.py's own dns_lookup()/process_government_v2()
    logic (not imported, since that lives with the DNS-fetch code, not
    the scoring code -- duplicated here deliberately, small enough to
    keep in sync by inspection)."""
    dns = rec.get("dns") or {}
    for sub in dns.get("resolving_subdomains", []):
        if sub.get("likely_own_domain_wildcard"):
            continue
        cname = (sub.get("cname") or "").lower()
        for alias, platform in _PLATFORM_ALIASES.items():
            if alias in cname:
                return platform, f"{sub['host']} CNAME -> {sub['cname']}"
    for vl in dns.get("resolving_vendor_labels", []):
        return vl["platform"], f"guessed tenant host resolves: {vl['host']}"
    return "", ""


def load_records() -> list:
    records = []
    if not RECON_JSONL.exists():
        return records
    with open(RECON_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return records


def load_homepage_html(gz_path: str) -> str:
    if not gz_path:
        return ""
    try:
        with gzip.open(gz_path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def homepage_candidates(rec: dict) -> tuple[list[dict], str]:
    """Returns (candidates, site_builder_family). candidates is a list of
    {url, source, score, kind} for every homepage link find_hop_links()
    ranked, plus any homepage link detect_platform() recognizes as a
    vendor host outright (kind=platform, even if find_hop_links() itself
    didn't rank it -- a vendor-host link with weak anchor text/path
    vocabulary can legitimately score low under the measured weights
    while still being a certain platform find)."""
    homepage = rec.get("homepage") or {}
    gz_path = homepage.get("homepage_gz_path", "")
    html = load_homepage_html(gz_path)
    if not html:
        return [], ""

    final_url = homepage.get("final_url") or f"https://{rec.get('domain', '')}/"
    raw_links = homepage.get("links") or []
    position_by_href = {ln["href"]: ln.get("position", "body") for ln in raw_links}

    def source_for(url: str) -> str:
        pos = position_by_href.get(url, "body")
        if pos in ("nav", "menu"):
            return "homepage-nav" if pos == "nav" else "homepage-body"
        if pos == "footer":
            return "homepage-footer"
        return "homepage-body"

    candidates: dict[str, dict] = {}

    ranked = w147.find_hop_links(html, final_url)
    for i, url in enumerate(ranked):
        if is_unresolvable_third_party_host(url):
            continue
        # find_hop_links doesn't expose its own numeric score; rank
        # position (best-first) stands in as a monotonic score here so
        # this list still sorts correctly alongside sitemap/DNS
        # candidates that carry their own real lift-based score --
        # scaled well above a typical hub/meeting lift score so a
        # homepage-nav pick (position/anchor-scored against real
        # measured weights) is never silently buried under a lower-
        # value sitemap-path hit.
        score = max(1.0, 100.0 - i)
        candidates[url] = {
            "url": url,
            "source": source_for(url),
            "score": score,
            "kind": "platform" if detect_platform(url) != "unknown" else "hub",
        }

    for ln in raw_links:
        url = ln["href"]
        platform = detect_platform(url)
        if platform != "unknown" and url not in candidates:
            candidates[url] = {
                "url": url,
                "source": source_for(url),
                "score": 200.0,
                "kind": "platform",
            }

    builder = ""
    try:
        result = classify_site_builder(html, url=final_url)
        builder = getattr(result, "family", "") or ""
    except Exception:  # noqa: BLE001
        builder = ""

    return list(candidates.values()), builder


def classify_record(rec: dict) -> dict:
    domain = rec.get("domain", "")

    if rec.get("dns_gate") == "dns-unresolvable":
        return {
            "domain": domain,
            "gov_id": rec.get("gov_id", ""),
            "name": rec.get("name", ""),
            "state": rec.get("state", ""),
            "population": rec.get("population", ""),
            "group": rec.get("group", ""),
            "platform": "",
            "platform_evidence_url": "",
            "confidence": "none",
            "site_builder": "",
            "catchall_preflag": False,
            "n_candidates": 0,
            "candidates_json": "[]",
            "note": "dns-unresolvable",
        }

    urls = all_urls_from_record(rec)

    platform, platform_evidence = "", ""
    dns_plat, dns_evidence = dns_platform(rec)
    if dns_plat:
        platform, platform_evidence = dns_plat, dns_evidence
    else:
        for u in urls:
            p = vendor_platform_for_url(u)
            if p:
                platform, platform_evidence = p, u
                break

    all_candidates: dict[str, dict] = {}

    for u in urls:
        # Defense in depth: sitemap/Wayback/Common Crawl URLs are already
        # domain-scoped and structurally can't be on a third-party host,
        # but a malformed sitemap could still list one -- same skip as
        # homepage_candidates()'s, so a stray external link never scores
        # as a real hub/meeting candidate here either.
        if is_unresolvable_third_party_host(u):
            continue
        hs = hub_score(u)
        ms = meeting_score(u)
        best = max(hs, ms)
        if best <= 0:
            continue
        source = "sitemap" if u in (rec.get("sitemap_urls") or []) else "archive"
        all_candidates[u] = {
            "url": u,
            "source": source,
            "score": best,
            "kind": "meeting-detail" if ms >= hs else "hub",
        }

    hp_candidates, site_builder = homepage_candidates(rec)
    for c in hp_candidates:
        existing = all_candidates.get(c["url"])
        if existing is None or c["score"] > existing["score"]:
            all_candidates[c["url"]] = c

    if not platform:
        for c in all_candidates.values():
            if c["kind"] == "platform":
                platform, platform_evidence = detect_platform(c["url"]), c["url"]
                break

    ranked = sorted(all_candidates.values(), key=lambda c: -c["score"])

    if platform:
        confidence = "high"
    elif ranked and ranked[0]["score"] >= 20:
        confidence = "medium"
    elif ranked:
        confidence = "low"
    else:
        confidence = "none"

    link_count = (rec.get("homepage") or {}).get("link_count", 0)
    catchall_preflag = bool(
        (rec.get("homepage") or {}).get("fetched")
        and link_count < CATCHALL_PREFLAG_LINK_FLOOR
    )

    return {
        "domain": domain,
        "gov_id": rec.get("gov_id", ""),
        "name": rec.get("name", ""),
        "state": rec.get("state", ""),
        "population": rec.get("population", ""),
        "group": rec.get("group", ""),
        "platform": platform,
        "platform_evidence_url": platform_evidence,
        "confidence": confidence,
        "site_builder": site_builder,
        "catchall_preflag": catchall_preflag,
        "n_candidates": len(ranked),
        "candidates_json": json.dumps(ranked[:5]),
        "note": "",
    }


def main() -> None:
    records = load_records()
    log(f"{len(records)} recon records loaded")
    if not records:
        return

    rows = []
    for i, rec in enumerate(records):
        rows.append(classify_record(rec))
        if (i + 1) % 200 == 0:
            log(f"classified {i + 1}/{len(records)}")

    fieldnames = [
        "domain",
        "gov_id",
        "name",
        "state",
        "population",
        "group",
        "platform",
        "platform_evidence_url",
        "confidence",
        "site_builder",
        "catchall_preflag",
        "n_candidates",
        "candidates_json",
        "note",
    ]
    with open(CLASSIFIED_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    log(f"wrote {CLASSIFIED_CSV} ({len(rows)} rows)")

    by_confidence: dict[str, int] = {}
    for r in rows:
        by_confidence[r["confidence"]] = by_confidence.get(r["confidence"], 0) + 1
    log(f"confidence split: {by_confidence}")

    platform_counts: dict[str, int] = {}
    for r in rows:
        if r["platform"]:
            platform_counts[r["platform"]] = platform_counts.get(r["platform"], 0) + 1
    log(f"platforms found: {platform_counts}")

    no_candidate = sum(
        1 for r in rows if r["n_candidates"] == 0 and r["note"] != "dns-unresolvable"
    )
    log(
        f"governments with NO candidate (feed phase 3's fallback ladder): {no_candidate}"
    )
    log(f"catchall_preflag count: {sum(1 for r in rows if r['catchall_preflag'])}")


if __name__ == "__main__":
    main()
