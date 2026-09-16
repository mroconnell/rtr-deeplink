"""WO-360, part A step 2: match `research/wo360_muni_links.csv` (every
outbound link found on a WV county's municipalities page/homepage,
WO-360's `wo360_county_muni_walk.py`) against the 103 WV `us:place`/
`us:cousub` rows whose `domain` is the `local.wv.gov` placeholder (57)
or blank (46), by exact name-and-state match (never a token/substring
match -- "watch same-name towns across counties" per the brief), and
fill `domain` on a confirmed match.

Match rule: normalize both the target place's `city_name` (strip a
trailing " town"/" city"/" village") and the link's visible text (strip
a leading "Town of "/"City of "/"Village of ", trailing " town"/" city"/
" village", punctuation, case) and require an EXACT string match. A
normalized name that matches more than one of the 103 target rows (a
real same-name collision within this population) is left unmatched and
recorded as ambiguous -- never guessed. A normalized name that resolves
to more than one distinct host across the found links is also left
unmatched and recorded as ambiguous.

For every filled row: the OLD placeholder `local.wv.gov` domain (57 of
the 103) moves to `alternate_domains` per the never-blank-a-domain rule;
a blank domain (46 of 103) has nothing to move. The county page used as
evidence is NOT written into `jurisdiction_coverage.csv` (no evidence
column exists there) -- it lives in `research/wo360_report.csv`
(one row per matched government: gov_id, name, old domain, new domain,
county gov_id, county page URL) for the conductor/audit trail, per the
pattern other WOs in this wave use for their own report csv.

Follows the Sec 158 write protocol: `flock` on the sibling `.lock`,
re-read jurisdiction_coverage.csv immediately before writing, refuse to
write below 99% of `git show HEAD`'s line count, temp file + os.replace,
line-based (never a gov_id dict rebuild -- ~1,700 rows carry a blank/
duplicate gov_id), LF endings.

Usage (from the rtr-deeplink repo root, shared venv -- no app/archive
import here, so DATABASE_URL is not required, but harmless if set):
    .venv/bin/python scripts/wo360_apply_to_jc.py            # dry run
    .venv/bin/python scripts/wo360_apply_to_jc.py --apply    # write

Writes `research/wo360_report.csv`, `research/wo360_jc_applied_gov_ids.txt`,
and (dry-run and apply both) `research/wo360_ambiguous_matches.csv` for
the audit trail.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import os
import re
import sys
from pathlib import Path

RTR_BUSINESS = Path("/Users/mroconnell/Documents/rtr-business")
RESEARCH = RTR_BUSINESS / "research"
JC_CSV = RESEARCH / "jurisdiction_coverage.csv"
JC_LOCK = RESEARCH / "jurisdiction_coverage.csv.lock"
MUNI_LINKS_CSV = RESEARCH / "wo360_muni_links.csv"
REPORT_CSV = RESEARCH / "wo360_report.csv"
APPLIED_GOV_IDS_TXT = RESEARCH / "wo360_jc_applied_gov_ids.txt"
AMBIGUOUS_CSV = RESEARCH / "wo360_ambiguous_matches.csv"

SUFFIX_RE = re.compile(r"\s+(town|city|village)$", re.IGNORECASE)
PREFIX_RE = re.compile(r"^(town of|city of|village of)\s+", re.IGNORECASE)
PUNCT_RE = re.compile(r"[.,'’]")
WS_RE = re.compile(r"\s+")

JUNK_HOST_SUBSTR = (
    "wvaco.org",
    "wvassessor.com",
    "reddit.com",
    "arcgis.com",
    "courtswv.gov",
    "wikipedia.org",
    "visitwv.com",
    "wvtourism.com",
    "travelwv.com",
    "wondertravel",
    "census.gov",
    "google.com",
    "goo.gl",
    "bing.com",
    "yelp.com",
    "tripadvisor.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "wvpublic.org",
    "wboy.com",
    "wsaz.com",
    "wchstv.com",
    "wvmetronews.com",
    "wvculture.org",
    "usgs.gov",
    "noaa.gov",
    "weather.gov",
)


def normalize(name: str) -> str:
    n = (name or "").strip()
    n = PREFIX_RE.sub("", n)
    n = SUFFIX_RE.sub("", n)
    n = PUNCT_RE.sub("", n)
    n = WS_RE.sub(" ", n).strip().lower()
    return n


def load_targets():
    targets = []
    with open(JC_CSV, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row["state_or_province"] != "West Virginia":
                continue
            gid = row["gov_id"]
            if not (gid.startswith("us:place:54") or gid.startswith("us:cousub:54")):
                continue
            dom = (row["domain"] or "").strip()
            if dom == "local.wv.gov":
                targets.append((row, "placeholder"))
            elif dom == "":
                targets.append((row, "blank"))
    return targets


def load_links():
    links = []
    with open(MUNI_LINKS_CSV, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            host = (row["host"] or "").strip().lower()
            if not host or any(j in host for j in JUNK_HOST_SUBSTR):
                continue
            links.append(row)
    return links


def build_name_to_hosts(links):
    name_to_hosts = {}
    name_to_evidence = {}
    for link in links:
        norm = normalize(link["link_text"])
        if not norm:
            continue
        name_to_hosts.setdefault(norm, set()).add(link["host"])
        name_to_evidence.setdefault(norm, []).append(link)
    return name_to_hosts, name_to_evidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    targets = load_targets()
    links = load_links()
    name_to_hosts, name_to_evidence = build_name_to_hosts(links)

    # Detect same-normalized-name collisions WITHIN the 103 target rows
    # themselves (two different WV places sharing a name) -- these are
    # never guessed at even if the link name matches, since we cannot
    # tell which government the county page meant.
    target_name_counts = {}
    for row, _kind in targets:
        norm = normalize(row["city_name"])
        target_name_counts[norm] = target_name_counts.get(norm, 0) + 1

    report_rows = []
    applied_gov_ids = []
    ambiguous_rows = []
    fills = {}  # gov_id -> (new_domain, old_domain_to_alternate)

    for row, kind in targets:
        gov_id = row["gov_id"]
        norm = normalize(row["city_name"])
        if target_name_counts[norm] > 1:
            ambiguous_rows.append(
                {
                    "gov_id": gov_id,
                    "name": row["city_name"],
                    "reason": "name-collision-within-target-set",
                }
            )
            continue
        hosts = name_to_hosts.get(norm)
        if not hosts:
            continue
        if len(hosts) > 1:
            ambiguous_rows.append(
                {
                    "gov_id": gov_id,
                    "name": row["city_name"],
                    "reason": f"multiple-hosts-found: {sorted(hosts)}",
                }
            )
            continue
        new_domain = next(iter(hosts))
        if new_domain.startswith("www."):
            new_domain_bare = new_domain[4:]
        else:
            new_domain_bare = new_domain
        old_domain = (row["domain"] or "").strip()
        evidence = name_to_evidence[norm][0]
        fills[gov_id] = (new_domain_bare, old_domain if kind == "placeholder" else "")
        report_rows.append(
            {
                "gov_id": gov_id,
                "name": row["city_name"],
                "old_domain": old_domain,
                "new_domain": new_domain_bare,
                "county_gov_id": evidence["county_gov_id"],
                "county_name": evidence["county_name"],
                "evidence_link_text": evidence["link_text"],
                "evidence_url": evidence["resolved_url"],
            }
        )
        applied_gov_ids.append(gov_id)

    print(f"targets: {len(targets)}")
    print(f"muni links loaded (after junk-host filter): {len(links)}")
    print(f"distinct normalized link names: {len(name_to_hosts)}")
    print(f"matched + filled: {len(fills)}")
    print(f"ambiguous (skipped): {len(ambiguous_rows)}")

    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "gov_id",
                "name",
                "old_domain",
                "new_domain",
                "county_gov_id",
                "county_name",
                "evidence_link_text",
                "evidence_url",
            ],
        )
        w.writeheader()
        w.writerows(report_rows)

    with open(AMBIGUOUS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["gov_id", "name", "reason"])
        w.writeheader()
        w.writerows(ambiguous_rows)

    if not args.apply:
        print("Dry run only -- pass --apply to write jurisdiction_coverage.csv")
        return

    if not fills:
        print("Nothing to apply.")
        return

    with open(JC_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            with open(JC_CSV, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
                rows = list(reader)
            before_lines = len(rows) + 1

            col = {name: i for i, name in enumerate(header)}
            gi = col["gov_id"]
            di = col["domain"]
            ai = col["alternate_domains"]
            ri = col["reject_reason"]

            changed = 0
            for r in rows:
                if len(r) <= max(gi, di, ai, ri):
                    continue
                gid = r[gi]
                if gid in fills:
                    new_domain, old_to_alt = fills[gid]
                    r[di] = new_domain
                    if old_to_alt:
                        existing_alt = [a for a in (r[ai] or "").split(";") if a]
                        if old_to_alt not in existing_alt:
                            existing_alt.append(old_to_alt)
                        r[ai] = ";".join(existing_alt)
                    # A prior reject_reason was tested against the OLD
                    # domain (usually the local.wv.gov placeholder, or
                    # nothing at all) -- clear it so the real site gets a
                    # fresh test, same convention as the county-level
                    # wv.gov corrections (commit 60c7036).
                    r[ri] = ""
                    changed += 1

            after_lines = len(rows) + 1
            if after_lines < before_lines * 0.99:
                print(
                    f"REFUSING to write: {after_lines} lines < 99% of {before_lines}",
                    file=sys.stderr,
                )
                sys.exit(1)

            tmp_path = JC_CSV.with_suffix(".csv.wo360.tmp")
            with open(tmp_path, "w", newline="\n", encoding="utf-8") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(header)
                w.writerows(rows)
            os.replace(tmp_path, JC_CSV)
            print(f"Applied {changed} domain fills to jurisdiction_coverage.csv")
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)

    with open(APPLIED_GOV_IDS_TXT, "w", encoding="utf-8") as f:
        for gid in applied_gov_ids:
            f.write(gid + "\n")


if __name__ == "__main__":
    main()
