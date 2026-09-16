#!/usr/bin/env python3
"""WO-337 (2026-09-13): builds `research/wo337_population.csv` from
`research/passive_neither_7-us-muni-twp-ladder-only.csv` (2,010 US
municipalities/townships that only ever had the access-ladder sweeps,
never a passive pass), filling the 665 rows whose `population` column is
blank/0 from the Census Bureau's `sub-est2024.csv` subcounty population
estimates file (already on disk at
`~/Documents/rtr-business/data-product/census_reference/sub-est2024.csv`
-- the same file WO-322 used for group 3's under-5k municipalities/
townships; no download performed by this script), then sorts the whole
population largest-first, per the brief.

Same shape as WO-325's own `wo325_split_population.py` (excludes any row
whose `domain` is itself a bare youtube.com/youtu.be host with no path --
this WO's absolute rule is never to fetch YouTube for any reason and
there's no id to recover from a bare host).

**Join method: by gov_id's own FIPS codes, not by name/state text.** This
source file's `gov_id` is already a minted Census-derived id in one of
two shapes (checked directly against all 2,010 rows -- both parse
cleanly, 0 malformed):
  - `us:place:<SSPPPPP>` -- 2-digit state FIPS + 5-digit PLACE code
    (incorporated cities/villages/boroughs). Joins to `sub-est2024.csv`
    rows where STATE==SS, PLACE==PPPPP, COUNTY=="000" (SUMLEV 162, the
    place-level total row -- a place can appear 2-3 times in this file,
    once per county it spans, plus once as the place-level total; only
    the COUNTY=="000" row is the whole place).
  - `us:cousub:<SSCCCNNNNN>` -- 2-digit state FIPS + 3-digit county FIPS
    + 5-digit COUSUB code (minor civil divisions -- townships in the
    township states). Joins to STATE==SS, COUNTY==CCC, COUSUB==NNNNN.

A first pass tried a (state, name) TEXT join instead and got 186 of 665
rows back "ambiguous" -- checked directly, every one was a real
same-named township in a different county of the same state (Michigan
alone has multiple "Wright township"s), not a data problem the text join
could resolve. The gov_id's own FIPS codes disambiguate these exactly, so
this script joins on gov_id, falling back to the text join (with its
honest ambiguous-match rejection) only for a gov_id this script's own
regex doesn't recognize.

Usage:
    .venv/bin/python scripts/wo337_census_fill.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urlparse

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
SOURCE_CSV = RESEARCH_DIR / "passive_neither_7-us-muni-twp-ladder-only.csv"
POPULATION_CSV = RESEARCH_DIR / "wo337_population.csv"
UNFILLED_CSV = RESEARCH_DIR / "wo337_census_fill_unfilled.csv"

CENSUS_SUB_EST = (
    Path.home()
    / "Documents"
    / "rtr-business"
    / "data-product"
    / "census_reference"
    / "sub-est2024.csv"
)

BARE_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}

FIELDNAMES = ["domain", "gov_id", "name", "state", "population", "group"]

PLACE_GOV_ID_RE = re.compile(r"^us:place:(\d{2})(\d{5})$")
COUSUB_GOV_ID_RE = re.compile(r"^us:cousub:(\d{2})(\d{3})(\d{5})$")

SUFFIXES = [
    "town",
    "Town",
    "township",
    "Township",
    "village",
    "Village",
    "city",
    "City",
    "borough",
    "Borough",
    "CDP",
    "municipality",
    "Municipality",
]
_SUFFIX_RE = re.compile(
    r"\s+(town|township|village|city|borough|municipality|CDP)\s*$",
    re.IGNORECASE,
)


def is_bare_youtube(domain: str) -> bool:
    host = domain.strip().lower()
    parsed = urlparse(host if "://" in host else f"//{host}")
    netloc = (parsed.netloc or host).split("/")[0]
    path = parsed.path if "://" in domain else ""
    return netloc in BARE_YOUTUBE_HOSTS and not path.strip("/")


def load_census() -> tuple[dict, dict, dict]:
    """Returns (place_idx, cousub_idx, name_state_idx).
    place_idx: (state_fips, place_fips) -> POPESTIMATE2024, only the
      COUNTY=="000" (whole-place) row.
    cousub_idx: (state_fips, county_fips, cousub_fips) -> POPESTIMATE2024.
    name_state_idx: (STNAME, NAME) -> [pop, ...] for the text-join
      fallback.
    """
    place_idx: dict[tuple[str, str], int] = {}
    cousub_idx: dict[tuple[str, str, str], int] = {}
    name_state_idx: dict[tuple[str, str], list[int]] = {}

    with open(CENSUS_SUB_EST, newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f):
            name = (row.get("NAME") or "").strip()
            stname = (row.get("STNAME") or "").strip()
            pop_raw = row.get("POPESTIMATE2024") or ""
            state = row.get("STATE") or ""
            county = row.get("COUNTY") or ""
            place = row.get("PLACE") or ""
            cousub = row.get("COUSUB") or ""
            if not pop_raw:
                continue
            try:
                pop = int(pop_raw)
            except ValueError:
                continue

            if name and stname:
                name_state_idx.setdefault((stname, name), []).append(pop)

            if place != "00000" and county == "000":
                place_idx[(state, place)] = pop
            if cousub != "00000":
                cousub_idx[(state, county, cousub)] = pop

    return place_idx, cousub_idx, name_state_idx


def strip_suffix(name: str) -> str:
    return _SUFFIX_RE.sub("", name).strip()


def text_join(name: str, state: str, name_state_idx: dict) -> tuple[int | None, str]:
    name = name.strip()
    hit = name_state_idx.get((state, name))
    if hit and len(set(hit)) == 1:
        return hit[0], "text-exact"
    if hit and len(set(hit)) > 1:
        return None, "text-ambiguous-exact"

    base = strip_suffix(name)
    tried_bases = {name}
    if base != name:
        tried_bases.add(base)
    matches: set[int] = set()
    matched_any = False
    for b in tried_bases:
        for suf in SUFFIXES:
            hit = name_state_idx.get((state, f"{b} {suf}"))
            if hit:
                matched_any = True
                matches.update(hit)
    if matched_any and len(matches) == 1:
        return matches.pop(), "text-suffix-search"
    if matched_any and len(matches) > 1:
        return None, "text-ambiguous-suffix-search"
    return None, "no-match"


def find_population(row: dict, place_idx: dict, cousub_idx: dict, name_state_idx: dict):
    gov_id = row.get("gov_id", "")
    m = PLACE_GOV_ID_RE.match(gov_id)
    if m:
        state, place = m.group(1), m.group(2)
        pop = place_idx.get((state, place))
        if pop is not None:
            return pop, "gov_id-place"
        # fall through to text join if the FIPS code itself doesn't
        # match anything in this Census vintage (e.g. a place that
        # incorporated/disincorporated since the id was minted).
    else:
        m = COUSUB_GOV_ID_RE.match(gov_id)
        if m:
            state, county, cousub = m.group(1), m.group(2), m.group(3)
            pop = cousub_idx.get((state, county, cousub))
            if pop is not None:
                return pop, "gov_id-cousub"

    return text_join(row["name"], row["state"], name_state_idx)


def main() -> None:
    with open(SOURCE_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} source rows")

    excluded = [r for r in rows if is_bare_youtube(r["domain"])]
    kept = [r for r in rows if not is_bare_youtube(r["domain"])]
    print(f"{len(excluded)} excluded (bare youtube.com/youtu.be domain, no path)")
    for r in excluded:
        print("  excluded:", r["domain"], r.get("gov_id", ""), r.get("name", ""))

    place_idx, cousub_idx, name_state_idx = load_census()
    print(
        f"census sub-est2024 index: {len(place_idx)} place keys, "
        f"{len(cousub_idx)} cousub keys, {len(name_state_idx)} (state,name) text keys"
    )

    blank_before = [
        r for r in kept if not r.get("population") or r["population"] == "0"
    ]
    print(f"{len(blank_before)} rows with blank/0 population to fill")

    filled = 0
    unfilled_rows = []
    method_counts: dict[str, int] = {}
    for r in kept:
        pop_raw = (r.get("population") or "").strip()
        if pop_raw and pop_raw != "0":
            continue
        pop, method = find_population(r, place_idx, cousub_idx, name_state_idx)
        method_counts[method] = method_counts.get(method, 0) + 1
        if pop is not None:
            r["population"] = str(pop)
            filled += 1
        else:
            unfilled_rows.append(r)

    print(f"filled {filled} of {len(blank_before)}")
    print("method breakdown:", method_counts)
    print(f"{len(unfilled_rows)} still unfilled (written to {UNFILLED_CSV})")

    with open(UNFILLED_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        w.writeheader()
        for r in unfilled_rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    def sort_key(r):
        try:
            return -int(r.get("population") or 0)
        except ValueError:
            return 0

    kept.sort(key=sort_key)

    with open(POPULATION_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        w.writeheader()
        for r in kept:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})
    print(f"wrote {POPULATION_CSV} ({len(kept)} rows, sorted population desc)")


if __name__ == "__main__":
    main()
