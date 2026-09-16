"""WO-292 (2026-09-12): school-district pilot, phase 2 -- offline
classification over phase 1's raw recon file (`wo292_recon.jsonl`).

Copied from `wo282_classify.py` (WO-282/283's phase 2) and adapted for
school sites in three places only -- everything else (vendor-host/DNS
platform detection, the measured HUB/MEETING flag-word lift tables, the
named first-party path shapes, `detect_platform()` on every homepage
href, `classify_site_builder()`, the catch-all preflag) is unchanged:

  1. `find_hop_links()` is now called WITH this row's `gov_id`
     (`wo147_access_ladder_sweep.find_hop_links(html, url, gov_id=...)`,
     the change the WO-292 step-0 agent landed in
     `wo147_access_ladder_sweep.py`) so a `us:sd:` row's homepage links
     are scored against the city/county vocabulary PLUS the WO-292
     school vocabulary (`hop_link_weights_school.csv`) -- a non-`us:sd:`
     row (there shouldn't be any in this population, but the guard costs
     nothing) is scored exactly as before.
  2. BoardDocs (`go.boarddocs.com/<st>/<label>`) and Simbli
     (`simbli.eboardsolutions.com`) are recognized as AGENDA-ONLY
     platforms -- `app/platforms/base.py`'s `detect_platform()` doesn't
     know either host (confirmed by grep before writing this: no
     `boarddocs`/`simbli`/`eboardsolutions` hit anywhere under
     `app/platforms/`), so this script does its own narrow hostname
     match, tags the candidate `kind="agenda_only"`, and the row's
     `agenda_only_platform` column records which one -- these are
     reported, never chased for video (per the brief). Diligent
     Community (`*.community.diligentoneplatform.com`) is DELIBERATELY
     NOT added to this list: `app/platforms/base.py`'s own
     `detect_platform()` already routes `diligentoneplatform.com` to
     `"civicweb"`, and that routing's own module comment cites a
     confirmed-live real video link on a school-district tenant
     (Washoe County School District, `washoeschools.community.
     diligentoneplatform.com`) -- treating it as agenda-only here would
     contradict code already shipped and verified against a real
     district. Re-deriving the brief's claim against the code is exactly
     what CLAUDE.md's "a backlog entry is a lead, not a spec" rule asks
     for; this discrepancy is flagged in the WO-292 report rather than
     silently followed.
  3. Every YouTube (`youtube.com`/`youtu.be`) or Vimeo (`vimeo.com`)
     link found on a homepage is recorded to `wo292_youtube_leads.txt`
     (anchor text, position, domain, gov_id, name, state) for the
     dedicated YouTube-drip process (`scripts/youtube_drip.py`, see
     CLAUDE.md's "YouTube drip ownership" convention) to pick up later
     -- this script makes NO YouTube/Vimeo network call of its own, a
     channel URL is just a link seen on the district's own homepage.

Output: `research/wo292_classified.csv` (same columns as
`wo282_classified.csv` plus `agenda_only_platform`), and
`research/wo292_youtube_leads.txt`.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo292_classify_scratch.db" \\
        .venv/bin/python scripts/wo292_classify.py
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

from wo273_classify import (  # noqa: E402
    all_urls_from_record,
    dns_platform,
    hub_score,
    meeting_score,
    vendor_platform_for_url,
)

from app.platforms.base import detect_platform  # noqa: E402
import wo147_access_ladder_sweep as w147  # noqa: E402
from platform_fingerprints import classify_site_builder  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo292_recon.jsonl"
CLASSIFIED_CSV = RESEARCH_DIR / "wo292_classified.csv"
YOUTUBE_LEADS_TXT = RESEARCH_DIR / "wo292_youtube_leads.txt"

CATCHALL_PREFLAG_LINK_FLOOR = 5

# WO-292: hostname-only match, narrow on purpose (see module docstring
# point 2). "label" here is just which agenda-only vendor, not a claim
# about video presence.
AGENDA_ONLY_HOSTS = {
    "boarddocs": ("go.boarddocs.com", "boarddocs.com"),
    "simbli": ("simbli.eboardsolutions.com",),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def agenda_only_platform_for_url(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    for label, hosts in AGENDA_ONLY_HOSTS.items():
        if any(netloc == h or netloc.endswith("." + h) for h in hosts):
            return label
    return ""


def is_youtube_or_vimeo(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "youtube.com" in netloc or netloc == "youtu.be" or "vimeo.com" in netloc


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


def homepage_candidates(rec: dict, gov_id: str, leads_out) -> tuple[list[dict], str]:
    """Same as wo282_classify.homepage_candidates, plus: (a) gov_id
    passed through to find_hop_links() so a us:sd: row picks up the
    WO-292 school vocabulary; (b) BoardDocs/Simbli hrefs tagged
    kind="agenda_only" instead of "hub"/"platform"; (c) any YouTube/Vimeo
    href on the homepage written to the leads file, once per government
    (this function is called once per government)."""
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

    ranked = w147.find_hop_links(html, final_url, gov_id=gov_id)
    for i, url in enumerate(ranked):
        score = max(1.0, 100.0 - i)
        agenda_only = agenda_only_platform_for_url(url)
        if agenda_only:
            kind = "agenda_only"
        elif detect_platform(url) != "unknown":
            kind = "platform"
        else:
            kind = "hub"
        candidates[url] = {
            "url": url,
            "source": source_for(url),
            "score": score,
            "kind": kind,
            "agenda_only_platform": agenda_only,
        }

    for ln in raw_links:
        url = ln["href"]
        agenda_only = agenda_only_platform_for_url(url)
        platform = detect_platform(url)
        if agenda_only and url not in candidates:
            candidates[url] = {
                "url": url,
                "source": source_for(url),
                "score": 200.0,
                "kind": "agenda_only",
                "agenda_only_platform": agenda_only,
            }
        elif platform != "unknown" and url not in candidates:
            candidates[url] = {
                "url": url,
                "source": source_for(url),
                "score": 200.0,
                "kind": "platform",
                "agenda_only_platform": "",
            }
        if is_youtube_or_vimeo(url) and leads_out is not None:
            leads_out.append(
                {
                    "url": url,
                    "anchor_text": ln.get("text", ""),
                    "position": ln.get("position", ""),
                }
            )

    builder = ""
    try:
        result = classify_site_builder(html, url=final_url)
        builder = getattr(result, "family", "") or ""
    except Exception:  # noqa: BLE001
        builder = ""

    return list(candidates.values()), builder


def classify_record(rec: dict, leads_file) -> dict:
    domain = rec.get("domain", "")
    gov_id = rec.get("gov_id", "")
    name = rec.get("name", "")
    state = rec.get("state", "")

    if rec.get("dns_gate") == "dns-unresolvable":
        return {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "population": rec.get("population", ""),
            "group": rec.get("group", ""),
            "platform": "",
            "platform_evidence_url": "",
            "agenda_only_platform": "",
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

    agenda_only_platform = ""
    # WO-292: wo273_classify's own _PLATFORM_ALIASES table (built before
    # this WO existed) already labels "boarddocs.com" -> "boarddocs" and
    # "eboardsolutions.com" -> "eboardsolutions" as a vendor "platform" --
    # neither has a real app/platforms/ adapter (confirmed by grep, see
    # this file's module docstring), so a sitemap/archive/Wayback URL on
    # either host is rerouted to agenda_only_platform here, the same
    # bucket a homepage-found BoardDocs/Simbli link already lands in via
    # agenda_only_platform_for_url(), rather than being counted as a real
    # "platform" confirmation phase 3 would spend a live fetch chasing.
    if platform in ("boarddocs", "eboardsolutions"):
        agenda_only_platform = "boarddocs" if platform == "boarddocs" else "simbli"
        platform, platform_evidence = "", ""
    if not platform and not agenda_only_platform:
        for u in urls:
            a = agenda_only_platform_for_url(u)
            if a:
                agenda_only_platform = a
                break

    all_candidates: dict[str, dict] = {}

    for u in urls:
        hs = hub_score(u)
        ms = meeting_score(u)
        best = max(hs, ms)
        a = agenda_only_platform_for_url(u)
        if a:
            source = "sitemap" if u in (rec.get("sitemap_urls") or []) else "archive"
            all_candidates[u] = {
                "url": u,
                "source": source,
                "score": max(best, 15.0),
                "kind": "agenda_only",
                "agenda_only_platform": a,
            }
            continue
        if best <= 0:
            continue
        source = "sitemap" if u in (rec.get("sitemap_urls") or []) else "archive"
        all_candidates[u] = {
            "url": u,
            "source": source,
            "score": best,
            "kind": "meeting-detail" if ms >= hs else "hub",
            "agenda_only_platform": "",
        }

    leads_for_this_gov: list[dict] = []
    hp_candidates, site_builder = homepage_candidates(rec, gov_id, leads_for_this_gov)
    for c in hp_candidates:
        existing = all_candidates.get(c["url"])
        if existing is None or c["score"] > existing["score"]:
            all_candidates[c["url"]] = c

    if leads_for_this_gov and leads_file is not None:
        for lead in leads_for_this_gov:
            leads_file.write(
                "\t".join(
                    [
                        domain,
                        gov_id,
                        name,
                        state,
                        lead["url"],
                        lead["anchor_text"].replace("\t", " ").replace("\n", " "),
                        lead["position"],
                    ]
                )
                + "\n"
            )

    if not platform:
        for c in all_candidates.values():
            if c["kind"] == "platform":
                platform, platform_evidence = detect_platform(c["url"]), c["url"]
                break
    if not agenda_only_platform:
        for c in all_candidates.values():
            if c["kind"] == "agenda_only":
                agenda_only_platform = c.get("agenda_only_platform", "")
                break

    ranked = sorted(all_candidates.values(), key=lambda c: -c["score"])

    if platform:
        confidence = "high"
    elif agenda_only_platform:
        confidence = "medium"
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
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "population": rec.get("population", ""),
        "group": rec.get("group", ""),
        "platform": platform,
        "platform_evidence_url": platform_evidence,
        "agenda_only_platform": agenda_only_platform,
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
    with open(YOUTUBE_LEADS_TXT, "w", encoding="utf-8") as leads_file:
        leads_file.write("# domain\tgov_id\tname\tstate\turl\tanchor_text\tposition\n")
        for i, rec in enumerate(records):
            rows.append(classify_record(rec, leads_file))
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
        "agenda_only_platform",
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

    agenda_only_counts: dict[str, int] = {}
    for r in rows:
        if r["agenda_only_platform"]:
            agenda_only_counts[r["agenda_only_platform"]] = (
                agenda_only_counts.get(r["agenda_only_platform"], 0) + 1
            )
    log(f"agenda-only platforms found: {agenda_only_counts}")

    n_leads = 0
    if YOUTUBE_LEADS_TXT.exists():
        with open(YOUTUBE_LEADS_TXT, encoding="utf-8") as f:
            n_leads = sum(1 for ln in f if ln.strip() and not ln.startswith("#"))
    log(f"YouTube/Vimeo leads written for the drip: {n_leads}")

    no_candidate = sum(
        1 for r in rows if r["n_candidates"] == 0 and r["note"] != "dns-unresolvable"
    )
    log(
        f"governments with NO candidate (feed phase 3's fallback ladder): {no_candidate}"
    )
    log(f"catchall_preflag count: {sum(1 for r in rows if r['catchall_preflag'])}")


if __name__ == "__main__":
    main()
