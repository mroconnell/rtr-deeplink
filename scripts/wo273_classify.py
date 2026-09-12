"""WO-273 (2026-09-12): full-scale passive platform discovery, phase 2 --
offline classification over phase 1's raw recon file.

Reads `research/wo273_recon.jsonl` (written by `wo273_recon.py`) and scores
every URL phase 1 saw -- sitemap URLs, the Wayback CDX narrow-query URLs,
Common Crawl URLs, and DNS evidence -- with NO network access, so the
scoring rules can be rerun and improved without refetching anything (this
is the whole point of splitting phase 1/phase 2 per Ryan's 2026-09-12
design). Writes `research/wo273_classified.csv`, one row per government:
platform (if any) + its evidence URL, best candidate HUB url + score,
best candidate MEETING/VIDEO url + score, the method that found each, and
a confidence label. `wo273_targeted.py` (phase 3) reads this file and
fetches the top-ranked URLs live.

Scoring, in order:
  1. Vendor-host regex match (same alias list as wo273_recon.py) -- always
     "high" confidence, evidence is the matching URL itself. A resolving
     vendor label from DNS counts here too.
  2. Named first-party path shape (`/AgendaCenter`,
     `AgendaOnline/Meetings/ViewMeeting`, `/Citizens/`,
     `/Portal/MeetingInformation.aspx`, `/Archive.aspx?AMID=`) -- "high"
     confidence. WO-272's own template file
     (`app/utils/jurisdiction_data/first_party_meeting_paths.csv`) and
     WO-274's `hop_link_weights.csv` had not landed on `main` as of this
     run (checked directly, see the investigation doc) -- these are the
     literal paths named in this WO's own brief, not a guess at either
     file's contents.
  3. Measured flag-word lift scoring, split into HUB vocabulary (scores a
     listing/hub-shaped URL: agendacenter/supervisors/agendas/
     commissioners/meetings/mayor/council/minutes/boards/commission, plus
     bigrams of-commissioners/agendas-minutes/city-council/
     boards-commissions/public-meetings) and MEETING/VIDEO vocabulary
     (clip/mediaplayer/meetinginformation/meetingid/watch/splitview/
     meetingtemplateid/player/citizens/videos/view/portal/transcript/vod).
     Numbers are from the conductor's state file (tags "HUB LIFT", "HUB
     BIGRAMS", "LIFT over ALL", "FLAG-WORD LIFT", 2026-09-12) -- embedded
     directly in wo273_recon.py's HUB_WORD_LIFT/HUB_BIGRAM_LIFT/
     MEETING_WORD_HIT and imported from there so the two scripts never
     drift apart. Singular "agenda", "calendar", "government" and "media"
     are DELIBERATELY excluded (near-noise per that analysis) -- a URL
     matching only those scores zero and is not flagged at all.
  4. `platform_fingerprints.fingerprint()` (WO-267) is NOT applied in this
     phase: phase 1 never fetches a full HTML page body (only sitemap/
     robots XML/text), and platform_fingerprints' signals are measured
     against real page bodies. This is stated here rather than silently
     skipped -- phase 3 (`wo273_targeted.py`) is where a real page body
     exists and this matcher actually runs.

Output columns: domain, state, gov_id, population, platform,
platform_evidence_url, best_hub_url, hub_score, hub_method,
best_meeting_url, meeting_score, meeting_method, confidence,
n_urls_considered.

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo273_classify.py

This script imports no `app.*`/`archive.*` code and does no network I/O
at all -- no DATABASE_URL needed, safe to rerun freely.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wo273_recon import (  # noqa: E402
    HUB_BIGRAM_LIFT,
    HUB_WORD_LIFT,
    MEETING_WORD_HIT,
    _PATH_SHAPE_PLATFORMS,
    _PLATFORM_ALIASES,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo273_recon.jsonl"
CLASSIFIED_CSV = RESEARCH_DIR / "wo273_classified.csv"


def log(msg: str) -> None:
    print(msg, flush=True)


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


def _tokenize_path(url: str) -> list:
    path = urlparse(url).path.lower()
    return [seg for seg in path.replace("-", " ").replace("_", " ").split("/") if seg]


def hub_score(url: str) -> float:
    path_lower = urlparse(url).path.lower()
    score = 0.0
    for word, lift in HUB_WORD_LIFT.items():
        if word in path_lower:
            score = max(score, lift)
    for bigram, lift in HUB_BIGRAM_LIFT.items():
        if bigram.replace("-", "") in path_lower.replace("-", "").replace("/", ""):
            score = max(score, lift)
    return score


def meeting_score(url: str) -> float:
    path_lower = urlparse(url).path.lower()
    score = 0.0
    for word, hit in MEETING_WORD_HIT.items():
        if word in path_lower:
            score = max(score, hit)
    return score


def all_urls_from_record(rec: dict) -> list:
    """Every URL phase 1 saw for this government, from every source it
    recorded -- deduplicated, order preserved (sitemap first, since it's
    the government's own stated navigation; then the Wayback narrow
    index; then Common Crawl)."""
    urls = []
    seen = set()

    def add_many(lst):
        for u in lst or []:
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

    add_many(rec.get("sitemap_urls"))
    add_many((rec.get("wayback_index") or {}).get("narrow_urls"))
    add_many((rec.get("common_crawl") or {}).get("urls"))
    return urls


def dns_platform(rec: dict) -> tuple:
    """Returns (platform, evidence) from DNS, or ("", "") if none.
    Mirrors wo273_recon.py's own classify_from_dns logic (not imported,
    since that function lives with the DNS-fetch code, not the scoring
    code -- duplicated here deliberately, small enough to keep in sync by
    inspection)."""
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


def classify_record(rec: dict) -> dict:
    domain = rec.get("domain", "")
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

    best_hub_url, best_hub_score, hub_method = "", 0.0, ""
    best_meeting_url, best_meeting_score, meeting_method = "", 0.0, ""
    for u in urls:
        hs = hub_score(u)
        if hs > best_hub_score:
            best_hub_score, best_hub_url = hs, u
            hub_method = (
                "sitemap" if u in (rec.get("sitemap_urls") or []) else "wayback"
            )
        ms = meeting_score(u)
        if ms > best_meeting_score:
            best_meeting_score, best_meeting_url = ms, u
            meeting_method = (
                "sitemap" if u in (rec.get("sitemap_urls") or []) else "wayback"
            )

    if platform:
        confidence = "high"
    elif best_hub_score >= 20 or best_meeting_score >= 8:
        confidence = "medium"
    elif best_hub_score > 0 or best_meeting_score > 0:
        confidence = "low"
    else:
        confidence = "none"

    return {
        "domain": domain,
        "state": rec.get("state", ""),
        "gov_id": rec.get("gov_id", ""),
        "population": rec.get("population", ""),
        "sitemap_source": rec.get("sitemap_source", ""),
        "platform": platform,
        "platform_evidence_url": platform_evidence,
        "best_hub_url": best_hub_url,
        "hub_score": best_hub_score,
        "hub_method": hub_method,
        "best_meeting_url": best_meeting_url,
        "meeting_score": best_meeting_score,
        "meeting_method": meeting_method,
        "confidence": confidence,
        "n_urls_considered": len(urls),
    }


def main() -> None:
    if not RECON_JSONL.exists():
        log(f"{RECON_JSONL} missing -- run wo273_recon.py first")
        sys.exit(1)

    records = []
    with open(RECON_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    log(f"{len(records)} recon records loaded")

    rows = [classify_record(r) for r in records]

    fieldnames = [
        "domain",
        "state",
        "gov_id",
        "population",
        "sitemap_source",
        "platform",
        "platform_evidence_url",
        "best_hub_url",
        "hub_score",
        "hub_method",
        "best_meeting_url",
        "meeting_score",
        "meeting_method",
        "confidence",
        "n_urls_considered",
    ]
    with open(CLASSIFIED_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    log(f"wrote {CLASSIFIED_CSV} ({len(rows)} rows)")

    by_confidence = {}
    for r in rows:
        by_confidence[r["confidence"]] = by_confidence.get(r["confidence"], 0) + 1
    log(f"confidence split: {by_confidence}")
    platform_counts = {}
    for r in rows:
        if r["platform"]:
            platform_counts[r["platform"]] = platform_counts.get(r["platform"], 0) + 1
    log(f"platforms found: {platform_counts}")
    with_flagged = sum(
        1 for r in rows if r["hub_score"] > 0 or r["meeting_score"] > 0 or r["platform"]
    )
    log(
        f"governments with >=1 flagged URL (feeds phase 3): {with_flagged} / {len(rows)}"
    )


if __name__ == "__main__":
    main()
