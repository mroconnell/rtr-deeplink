#!/usr/bin/env python3
"""WO-274 (2026-09-12): the before/after measurement Ryan asked for --
old vs. new `find_hop_links()` scorer, on real saved government
homepages with a known recorded hub/meeting URL.

Reads (all read-only, all already on disk from WO-267, no fetches):
  - `<scratchpad>/agents/<wo267 agent id>/wo267_raw/*_home.html` --
    every positive homepage WO-267 saved.
  - That same directory's `wo267_manifest.csv`, `wo267_candidates.csv`,
    `wo267_supplemental_candidates.csv`, `wo267_supplemental_candidates2.csv`
    -- to map each saved home page back to its government (platform,
    city, state, domain).
  - `~/Documents/rtr-business/research/jurisdiction_coverage.csv` -- the
    RAW recorded `example_agenda_or_calendar_url` ("hub") and
    `example_meeting_url` ("meeting") for that government, looked up by
    domain, transcribed=true.

For every homepage, scores its real anchors with the OLD scorer
(`find_hop_links(..., legacy=True)`, WO-228) and the NEW scorer
(`find_hop_links(...)`, WO-274) and checks whether each one's top 8 put:
  (a) the known hub URL
  (b) the known meeting URL
  (c) any link on a meeting-vendor host or a named first-party path
(all matched by normalized host+path, not string equality, so a query
string or trailing slash difference doesn't count as a miss).

Also reports the "ceiling" -- how many of the 180 homepages link a
meeting-vendor host/named path AT ALL (not just in the top 8), and how
many link the recorded hub exactly -- and a separate "video straight
from the homepage" table: how often a link `detect_platform()` would
accept as a real meeting/video URL is present on the homepage at all,
and whether the MEETING-vocabulary-only scorer ranks it #1.

Run: `.venv/bin/python scripts/wo274_measure_hop_scorer.py` from the
repo root (needs `DATABASE_URL` set per this WO's brief, since importing
`app.platforms.base` pulls in the app's settings module).
"""

from __future__ import annotations

import csv
import glob
import os
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms.base import detect_platform  # noqa: E402
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    _NAMED_FIRSTPARTY_PATH_RE,
    _safe_soup,
    find_hop_links,
    is_vendor_href_host,
)
from scripts.derive_hop_weights import (  # noqa: E402
    WO267_AGENT_DIR,
    _is_internal,
    bigrams,
    is_vendor_host,
    norm_url_key,
    tokenize_url,
)

JC_PATH = Path(
    os.path.expanduser("~/Documents/rtr-business/research/jurisdiction_coverage.csv")
)

# The MEETING-shape vocabulary this WO's brief names for step 4, scored
# from the SAME measured weights file (vocabulary in {meeting_vendor,
# meeting_firstparty}) -- rather than re-typing the brief's example word
# list, this reads the actual measured weight for each of those exact
# words plus every other token that cleared MIN_SUPPORT under either
# vocabulary, so "the meeting vocabulary" here is the real measured set,
# not a hand-typed subset of it.
HOP_WEIGHTS_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "hop_link_weights.csv"
)


def _load_meeting_vocab():
    weights = {}
    with open(HOP_WEIGHTS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["vocabulary"] in ("meeting_vendor", "meeting_firstparty"):
                try:
                    w = float(row["weight"])
                except ValueError:
                    continue
                if w > weights.get(row["token_or_bigram"], float("-inf")):
                    weights[row["token_or_bigram"]] = w
    return weights


MEETING_VOCAB = _load_meeting_vocab()


def _meeting_vocab_score(url: str) -> float:
    tokens = tokenize_url(url)
    score = 0.0
    for t in set(tokens):
        score += MEETING_VOCAB.get(t, 0.0)
    for b in set(bigrams(tokens)):
        score += MEETING_VOCAB.get(b, 0.0)
    return score


def _key(plat, city, state):
    return (plat.strip().lower(), city.strip().lower(), state.strip().lower())


def build_candidates_lookup():
    lookup = {}
    for fname in (
        "wo267_candidates.csv",
        "wo267_supplemental_candidates.csv",
        "wo267_supplemental_candidates2.csv",
    ):
        path = f"{WO267_AGENT_DIR}/{fname}"
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                k = _key(row["platform"], row["city_name"], row["state_or_province"])
                if k not in lookup or (
                    not lookup[k].get("hub_url", "").strip()
                    and row.get("hub_url", "").strip()
                ):
                    lookup[k] = row
    return lookup


def build_jc_domain_index():
    index = {}
    with open(JC_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("transcribed") or "").strip().lower() != "true":
                continue
            d = (row.get("domain") or "").strip().lower()
            if d and d not in index:
                index[d] = row
    return index


def build_testbed():
    """Returns a list of dicts: gov_key, home_path, base_url, hub_url,
    meeting_url (hub_url/meeting_url are None when not recorded/internal)."""
    candidates = build_candidates_lookup()
    jc_index = build_jc_domain_index()
    manifest = list(csv.DictReader(open(f"{WO267_AGENT_DIR}/wo267_manifest.csv")))
    home_manifest = {r["raw_file"]: r for r in manifest if r["page"] == "home"}

    home_files = sorted(
        os.path.basename(p)
        for p in glob.glob(f"{WO267_AGENT_DIR}/wo267_raw/*_home.html")
    )
    testbed = []
    unmatched = 0
    for fn in home_files:
        m = home_manifest.get(fn)
        if not m:
            unmatched += 1
            continue
        k = _key(m["platform"], m["city_name"], m["state_or_province"])
        cand = candidates.get(k)
        if not cand:
            unmatched += 1
            continue
        domain = (cand.get("domain") or "").strip().lower()
        jc_row = jc_index.get(domain)
        hub_url = None
        meeting_url = None
        if jc_row:
            a = (jc_row.get("example_agenda_or_calendar_url") or "").strip()
            if a and not _is_internal(a):
                hub_url = a
            mu = (jc_row.get("example_meeting_url") or "").strip()
            if mu and not _is_internal(mu):
                meeting_url = mu
        else:
            # Supplemental candidate not in the research file by domain
            # (its "home" IS the platform's own tenant page) -- fall back
            # to the candidate row's own best_url() as a meeting URL,
            # since every supplemental platform added is a VIDEO
            # platform (champds/suiteone/telvue/townhallstreams/utah_pmn).
            best = (cand.get("hub_url") or "").strip()
            if best and not _is_internal(best):
                meeting_url = best

        base_url = m["final_url"] or m["url"]
        testbed.append(
            {
                "gov_key": f"{m['city_name']}, {m['state_or_province']}",
                "home_path": f"{WO267_AGENT_DIR}/wo267_raw/{fn}",
                "base_url": base_url,
                "hub_url": hub_url,
                "meeting_url": meeting_url,
            }
        )
    print(f"testbed: {len(testbed)} homepages ({unmatched} unmatched)", file=sys.stderr)
    return testbed


def _all_links(html_text: str, base_url: str):
    soup = _safe_soup(html_text)
    if soup is None:
        return []
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(base_url, href)
        if urlparse(full).scheme not in ("http", "https"):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
    return out


def _matches(url: str, target: str) -> bool:
    return norm_url_key(url) == norm_url_key(target)


def _is_vendor_or_named(url: str) -> bool:
    netloc = urlparse(url).netloc
    if is_vendor_href_host(netloc) or is_vendor_host(netloc):
        return True
    return bool(_NAMED_FIRSTPARTY_PATH_RE.search(url))


def main():
    testbed = build_testbed()

    with_hub = [t for t in testbed if t["hub_url"]]
    with_meeting = [t for t in testbed if t["meeting_url"]]
    print(
        f"of {len(testbed)} homepages: {len(with_hub)} have a recorded hub URL, "
        f"{len(with_meeting)} have a recorded meeting URL",
        file=sys.stderr,
    )

    results = {
        "legacy": {"hub": 0, "meeting": 0, "vendor_or_named": 0},
        "new": {"hub": 0, "meeting": 0, "vendor_or_named": 0},
    }
    ceiling_vendor_or_named = 0
    ceiling_hub_exact = 0
    homepage_has_meeting_link = 0
    meeting_vocab_ranks_first = 0
    unreadable = 0

    per_gov_rows = []

    for t in testbed:
        try:
            html = Path(t["home_path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            unreadable += 1
            continue

        links = _all_links(html, t["base_url"])
        has_vendor_or_named = any(_is_vendor_or_named(u) for u in links)
        if has_vendor_or_named:
            ceiling_vendor_or_named += 1
        if t["hub_url"] and any(_matches(u, t["hub_url"]) for u in links):
            ceiling_hub_exact += 1

        top8_legacy = find_hop_links(html, t["base_url"], legacy=True)
        top8_new = find_hop_links(html, t["base_url"])

        row = {
            "gov": t["gov_key"],
            "hub_url": t["hub_url"] or "",
            "meeting_url": t["meeting_url"] or "",
        }
        for label, top8 in (("legacy", top8_legacy), ("new", top8_new)):
            hub_hit = bool(t["hub_url"]) and any(
                _matches(u, t["hub_url"]) for u in top8
            )
            meeting_hit = bool(t["meeting_url"]) and any(
                _matches(u, t["meeting_url"]) for u in top8
            )
            vendor_hit = any(_is_vendor_or_named(u) for u in top8)
            results[label]["hub"] += int(hub_hit)
            results[label]["meeting"] += int(meeting_hit)
            results[label]["vendor_or_named"] += int(vendor_hit)
            row[f"{label}_hub_hit"] = hub_hit
            row[f"{label}_meeting_hit"] = meeting_hit
            row[f"{label}_vendor_hit"] = vendor_hit

        # Step 4: video straight from the homepage.
        platform_links = [
            u for u in links if detect_platform(u) not in (None, "unknown")
        ]
        if platform_links:
            homepage_has_meeting_link += 1
            scored = sorted(links, key=lambda u: -_meeting_vocab_score(u))
            top_scored = scored[0] if scored else None
            ranks_first = bool(top_scored) and detect_platform(top_scored) not in (
                None,
                "unknown",
            )
            if ranks_first:
                meeting_vocab_ranks_first += 1
            row["homepage_has_platform_link"] = True
            row["meeting_vocab_ranks_platform_link_first"] = ranks_first
        else:
            row["homepage_has_platform_link"] = False
            row["meeting_vocab_ranks_platform_link_first"] = False

        per_gov_rows.append(row)

    n = len(testbed)
    print("\n=== TABLE 1: old vs new scorer, top 8, counts of", n, "===")
    print(f"{'Metric':45s} {'Old (legacy)':>14s} {'New (weighted)':>15s}")
    print(
        f"{'Known hub URL in top 8':45s} {results['legacy']['hub']:>14d} {results['new']['hub']:>15d}  (of {len(with_hub)} with a recorded hub)"
    )
    print(
        f"{'Known meeting URL in top 8':45s} {results['legacy']['meeting']:>14d} {results['new']['meeting']:>15d}  (of {len(with_meeting)} with a recorded meeting URL)"
    )
    print(
        f"{'Vendor-host/named-path link in top 8':45s} {results['legacy']['vendor_or_named']:>14d} {results['new']['vendor_or_named']:>15d}  (of {n})"
    )

    print(f"\n=== CEILING (any link on the page, not just top 8), of {n} ===")
    print(
        f"Homepages linking a meeting-vendor host or named first-party path: {ceiling_vendor_or_named}"
    )
    print(
        f"Homepages linking the recorded hub URL exactly: {ceiling_hub_exact} (of {len(with_hub)} with a recorded hub)"
    )

    print(f"\n=== TABLE 2: video straight from the homepage, of {n} ===")
    print(
        f"Homepages with a detect_platform()-accepted link anywhere on the page: {homepage_has_meeting_link}"
    )
    print(
        f"Of those, MEETING-vocabulary scorer ranks that link's own URL #1 on the page: {meeting_vocab_ranks_first}"
    )

    # Written to /tmp, not the repo -- this is a report artifact, not
    # source; the investigation doc embeds the tables above directly.
    try:
        with open(
            "/tmp/wo274_measure_report.csv", "w", newline="", encoding="utf-8"
        ) as f:
            w = csv.DictWriter(
                f, fieldnames=list(per_gov_rows[0].keys()) if per_gov_rows else []
            )
            w.writeheader()
            for row in per_gov_rows:
                w.writerow(row)
        print(
            "\nwrote per-government detail to /tmp/wo274_measure_report.csv",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"could not write detail csv: {exc}", file=sys.stderr)

    if unreadable:
        print(f"\n{unreadable} homepages could not be read", file=sys.stderr)


if __name__ == "__main__":
    main()
