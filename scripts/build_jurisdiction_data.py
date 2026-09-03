"""One-time (rerun-when-Census-updates-its-files) generator for
app/utils/jurisdiction_data/*.csv -- the reference tables
app/utils/jurisdiction_enrich.py loads at import time.

Source files are official US Census Bureau Gazetteer/relationship files --
public domain (17 U.S.C. Section 105), no login/API key needed. Download
these five before running (not checked into this repo -- multi-MB raw
files, only the trimmed output below is committed):

  Counties gazetteer:
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_counties_national.zip
  Places (cities/towns) gazetteer:
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip
  County subdivisions (townships etc.) gazetteer:
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_cousubs_national.zip
  ZCTA-to-county relationship file:
    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt
  ZCTA-to-place relationship file:
    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_place20_natl.txt

Usage:
    python scripts/build_jurisdiction_data.py /path/to/downloaded/files/ [--canada /path/to/ca/files/]

Deliberately keeps every row, including name collisions across states and
ZCTAs that span multiple counties/places -- app/utils/jurisdiction_enrich.py
decides what to do with ambiguity at lookup time (only resolve a bare name
when it's unique; pick the largest-overlap candidate for a ZCTA using
AREALAND_PART), not here. Only unused columns (lat/long, water area, FIPS
codes not needed for a name/state lookup) are trimmed.

--- Canadian data (added 2026-08-17, BACKLOG.md's "Jurisdiction-bleed,
confirmed cross-platform" entry) ---

`--canada` is optional and additive: it appends Canadian census
subdivisions (cities/towns/townships/etc.) into the SAME `places.csv`
`_load_name_state_table()` already reads (confirmed by reading that
function directly: it's purely data-driven, no US-specific code) --
deliberately not a separate table, so a bare name lookup already gets
Canada coverage for free. Source is Statistics Canada's own Standard
Geographical Classification (SGC) 2021, "Structure" file -- the direct
name+code equivalent of what the US Gazetteer's places file already is,
public/open data (statcan.gc.ca), no login needed:

  SGC 2021 structure (English):
    https://www.statcan.gc.ca/eng/statistical-programs/document/sgc-cgt-2021-structure-eng.csv

Download that one file into its own directory and pass it as `--canada`.
Every "Level 4 / Census subdivision" row is a real Canadian
municipal-level government (city, town, township, village, rural
municipality, regional municipality, etc.) -- the direct Canadian
equivalent of a US incorporated place. The file's 7-digit `Code` encodes
the 2-digit province/territory SGC code as its first two digits;
`_SGC_PROVINCE_CODES` below is that fixed, official 13-entry map (10
provinces + 3 territories -- stable, not something StatsCan revises
year to year the way place boundaries are).

Not split into a separate Canadian "counties" table the way the US data
is: Canada's CSD level doesn't cleanly separate into "city" vs "county"
government the way US places.csv/counties.csv do (a Census Division, the
closer Canadian analogue to a US county, is a *statistical* grouping in
most provinces, not a separate governing body the way a US county
almost always is) -- and every real bleed case this was built to fix
(BACKLOG.md) is a plain city/town name, not a "County of X"-shaped one.
Revisit as a real, confirmed county-shaped Canadian case turns up, same
"verify before generalizing" convention as every other table here.

Real, confirmed, deliberately NOT solved by this pass: Canadian names
with French diacritics (Québec, Montréal, Trois-Rivières, ...) are
stored exactly as StatsCan spells them -- an English-language page that
writes the unaccented "Quebec"/"Montreal" spelling will NOT match this
table today. No real BACKLOG-confirmed bleed case needs this yet (every
confirmed case is a plain-ASCII English city name), so left as a
documented gap rather than adding untested accent-folding logic --
same "don't fix what isn't confirmed broken yet" convention as this
file's other narrow, evidence-driven choices.
"""

import csv
import sys
import zipfile
from pathlib import Path
from typing import List, Tuple

OUT_DIR = Path(__file__).parent.parent / "app" / "utils" / "jurisdiction_data"


def _read_tsv_from_zip_or_dir(source_dir: Path, zip_name: str, txt_name: str):
    zip_path = source_dir / zip_name
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(txt_name) as f:
                text = f.read().decode("latin-1")
    else:
        text = (source_dir / txt_name).read_text(encoding="latin-1")
    return list(csv.DictReader(text.splitlines(), delimiter="\t"))


def _read_pipe_delimited(source_dir: Path, name: str):
    text = (source_dir / name).read_text(encoding="utf-8-sig")
    return list(csv.DictReader(text.splitlines(), delimiter="|"))


def build_counties(source_dir: Path) -> dict:
    """Returns {state_fips: usps} alongside writing counties.csv -- the
    ZCTA relationship files only carry FIPS codes, and this is the
    cheapest real source for the FIPS->USPS mapping they need (every
    county row already carries both)."""
    rows = _read_tsv_from_zip_or_dir(
        source_dir, "2024_Gaz_counties_national.zip", "2024_Gaz_counties_national.txt"
    )
    fips_to_usps = {}
    out_rows = []
    for r in rows:
        name = r["NAME"].strip()
        state = r["USPS"].strip()
        out_rows.append((name, state))
        fips_to_usps[r["GEOID"].strip()[:2]] = state

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "counties.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "state"])
        writer.writerows(sorted(out_rows))
    print(f"counties.csv: {len(out_rows)} rows")
    return fips_to_usps


def build_places(source_dir: Path) -> None:
    rows = _read_tsv_from_zip_or_dir(
        source_dir, "2024_Gaz_place_national.zip", "2024_Gaz_place_national.txt"
    )
    # FUNCSTAT "A" = active incorporated government -- excludes CDPs (12,820
    # rows, FUNCSTAT "S") and other purely-statistical entities with no real
    # government to be "the jurisdiction" of a meeting -- correct as far as
    # it went.
    #
    # But "A" alone silently dropped every real consolidated city-county
    # government (Nashville-Davidson, Louisville/Jefferson, Indianapolis,
    # Baton Rouge...) -- found live 2026-08-15 auditing the Archive's real
    # jurisdiction values against this table. Root cause, confirmed against
    # the actual 2024 Gazetteer file (not guessed): Census codes these as
    # "B" (2 rows nationally -- Baton Rouge, Lafayette LA, both real
    # governed cities, just legally overlapping with their parish) or "F"
    # ("Nashville-Davidson metropolitan government (balance)",
    # "Indianapolis city (balance)", "Louisville/Jefferson County metro
    # government (balance)", "Athens-Clarke County unified government
    # (balance)", "Augusta-Richmond County consolidated government
    # (balance)", "Butte-Silver Bow (balance)", "Milford city (balance)",
    # "Greeley County unified government (balance)" -- 8 rows nationally,
    # every one a real active government, Census's own docs describe "F" as
    # a statistical "balance" construct for the *area*, not a claim the
    # government itself is fictitious). Confirmed safe to include both:
    # only 10 rows total nationally, none overlapping the "S"/"I"/"N" codes
    # (CDPs, inactive, nonfunctioning) this filter still correctly excludes.
    out_rows = [
        (r["NAME"].strip(), r["USPS"].strip())
        for r in rows
        if r["FUNCSTAT"] in ("A", "B", "F")
    ]
    with open(OUT_DIR / "places.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "state"])
        writer.writerows(sorted(out_rows))
    print(f"places.csv: {len(out_rows)} rows")


def build_county_subdivisions(source_dir: Path) -> None:
    """WO-16 (BACKLOG.md, 2026-08-16): townships/county subdivisions
    (Upper Providence PA, Greenburgh NY, Upper Dublin PA -- all confirmed
    real, live-flagged jurisdiction lookup misses) aren't covered by
    counties.csv or places.csv at all -- Census tracks them as a third,
    separate gazetteer (COUSUB), not a subset of either. FUNCSTAT "A"
    only (active government providing primary general-purpose functions)
    -- deliberately narrower than places.csv's "A"/"B"/"F" (that
    expansion was earned by real confirmed consolidated-government
    examples; COUSUB's own F rows are literally placeholder "County
    subdivisions not defined" junk, and this table's other codes (G, C,
    B -- also real townships/towns on a quick sample) have no
    BACKLOG-confirmed real example needing them yet, so left out rather
    than guessed at, same "verify before generalizing" convention as
    every other table here)."""
    rows = _read_tsv_from_zip_or_dir(
        source_dir, "2024_Gaz_cousubs_national.zip", "2024_Gaz_cousubs_national.txt"
    )
    out_rows = [
        (r["NAME"].strip(), r["USPS"].strip()) for r in rows if r["FUNCSTAT"] == "A"
    ]
    with open(
        OUT_DIR / "county_subdivisions.csv", "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["name", "state"])
        writer.writerows(sorted(out_rows))
    print(f"county_subdivisions.csv: {len(out_rows)} rows")


def build_zcta_county(source_dir: Path, fips_to_usps: dict) -> None:
    rows = _read_pipe_delimited(source_dir, "tab20_zcta520_county20_natl.txt")
    out_rows = []
    for r in rows:
        zcta = r["GEOID_ZCTA5_20"].strip()
        if not zcta:
            continue
        county_fips = r["GEOID_COUNTY_20"].strip()
        state = fips_to_usps.get(county_fips[:2])
        if not state:
            continue
        out_rows.append(
            (zcta, r["NAMELSAD_COUNTY_20"].strip(), state, int(r["AREALAND_PART"] or 0))
        )
    with open(OUT_DIR / "zcta_county.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["zcta", "county_name", "state", "area_land_part"])
        writer.writerows(sorted(out_rows))
    print(f"zcta_county.csv: {len(out_rows)} rows")


# Standard Geographical Classification 2021, Volume I -- the official,
# stable 2-digit province/territory codes (first two digits of every
# 7-digit CSD `Code`). Confirmed directly against the real downloaded
# structure file's own "Level 2 / Province and territory" rows, not
# guessed -- see this module's docstring for the source URL.
_SGC_PROVINCE_CODES = {
    "10": "NL",
    "11": "PE",
    "12": "NS",
    "13": "NB",
    "24": "QC",
    "35": "ON",
    "46": "MB",
    "47": "SK",
    "48": "AB",
    "59": "BC",
    "60": "YT",
    "61": "NT",
    "62": "NU",
}


def build_canada_places(canada_source_dir: Path) -> None:
    """Appends real Canadian census subdivisions (city/town/township-level
    governments) into the SAME places.csv the US build_places() above
    writes -- see this module's docstring for why one merged file, not a
    separate Canadian table. Additive: reads whatever places.csv already
    has (US rows, from a prior build_places() run in this same
    invocation) and adds Canada's rows on top, so re-running this alone
    doesn't require re-downloading the US Gazetteer files too."""
    text = (canada_source_dir / "sgc-cgt-2021-structure-eng.csv").read_text(
        encoding="latin-1"
    )
    rows = list(csv.DictReader(text.splitlines()))

    existing_rows: List[Tuple[str, str]] = []
    places_path = OUT_DIR / "places.csv"
    if places_path.exists():
        with open(places_path, encoding="utf-8") as f:
            existing_rows = [(r["name"], r["state"]) for r in csv.DictReader(f)]

    canada_rows: List[Tuple[str, str]] = []
    skipped_unmapped = 0
    for r in rows:
        if r["Level"] != "4":  # Level 4 = "Census subdivision"
            continue
        code = r["Code"].strip()
        prov = _SGC_PROVINCE_CODES.get(code[:2])
        if not prov:
            skipped_unmapped += 1
            continue
        canada_rows.append((r["Class title"].strip(), prov))

    if skipped_unmapped:
        print(
            f"build_canada_places: skipped {skipped_unmapped} rows with an unmapped province code"
        )

    combined = sorted(set(existing_rows) | set(canada_rows))
    with open(places_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "state"])
        writer.writerows(combined)
    print(
        f"places.csv: added {len(set(canada_rows))} Canadian rows "
        f"({len(combined)} total, was {len(existing_rows)})"
    )


# Real, curated, bounded addition (2026-08-21, BACKLOG.md's "StatsCan/
# Census table completeness gap" entry, confirmed still open per that
# entry's own list): Ontario's upper-tier "regional municipality"
# governments -- Durham, Peel, and Waterloo -- aren't census subdivisions
# (build_canada_places() above only reads SGC "Level 4 / Census
# subdivision" rows, the lower-tier city/town level: Caledon, Brampton,
# Mississauga, etc.), they're "Level 3 / Census division" rows in the SAME
# real SGC 2021 structure file this module already downloads -- confirmed
# directly by grepping it: codes 3518 (Durham), 3521 (Peel), and 3530
# (Waterloo) all appear under Ontario's "35" province prefix with the
# Class titles "Durham"/"Peel"/"Waterloo" (bare, no "Regional
# Municipality" annotation in this particular StatsCan file). Only these
# three, not the other 5 real Ontario regional municipalities a 2019
# provincial review also names (Halton, Muskoka, Niagara, Oxford, York,
# per Wikipedia's "Regional municipality" article, citing that review) --
# BACKLOG.md's own completeness-gap audit (a full sweep of all 176 real
# eScribe + 253 real Granicus subdomains in production) only confirmed
# Durham/Peel/Waterloo as customers actually live on this app today, so
# only those three are added here rather than guessing the other five are
# needed too, per this repo's "ground fixes in real confirmed data, don't
# speculate ahead of it" convention (see e.g. the StatsCan/Census
# completeness gap entry itself, or the Tulare County residual-gap test in
# tests/test_jurisdiction_enrich.py for the same discipline applied
# elsewhere).
#
# Both the "X Region" and "Region of X" forms are added for each --
# BACKLOG.md's own gap description already names both shapes ("Durham
# Region", "Region of Waterloo"), and a real eScribe/Granicus subdomain's
# wordninja split (see `_validated_label_extract()` in
# app/utils/jurisdiction_enrich.py) naturally produces the "X Region"
# shape from a label like "peelregion" -- confirmed live for Peel
# specifically (pub-peelregion.escribemeetings.com, BACKLOG_DONE.md).
# Real municipal/self-branding usage for a page's own body text can go
# either way (e.g. Waterloo's own regional government uses
# "regionofwaterloo.ca" as its domain), so both forms are stored as
# independent, equally-real rows rather than picking just one.
_ONTARIO_REGIONAL_MUNICIPALITIES = ["Durham", "Peel", "Waterloo"]


# Which of Canada's 13 provinces/territories actually call their
# upper-tier census divisions "County" in real, everyday usage -- the
# rest use a different word entirely, and appending "County" to their
# names would be fabricating a government type that doesn't exist, not
# a translation:
#
#   ON, NS, NB, PE  the only four that are genuinely counties -- Bruce
#                   County, Yarmouth County, Charlotte County, Kings
#                   County, confirmed against each province's own
#                   Municipal Affairs department (real, standing
#                   provincial-level administrative divisions).
#   BC              "Regional District" (East Kootenay, Fraser Valley --
#                   `ca_cd.csv`'s BC rows are exactly the real Regional
#                   District names, bare).
#   QC              "MRC" / municipalité régionale de comté -- a French
#                   name, not an English "County" at all.
#   AB, MB, NL, SK  "Division No. N" -- Census statistical divisions with
#                   no governing county council; nobody calls these
#                   "County".
#   NT              "Region N" -- same, a statistical division.
#   NU              Qikiqtaaluk/Kivalliq/Kitikmeot -- regions, not
#                   counties.
#   YT              One territory-wide census division ("Yukon" itself);
#                   Yukon has no county-level government at all.
#
# Scoped to public, stable facts about provincial government structure --
# not per-tenant confirmation the way a `tenant_overrides.csv` pin needs,
# because this is reference data (what a name IS), the same category
# `build_canada_places()` already added for all 5,028 Canadian CSDs in
# one shot with no per-row live check.
_ENGLISH_COUNTY_PROVINCES = {"ON", "NS", "NB", "PE"}


def build_canada_counties(canada_source_dir: Path) -> None:
    """Appends Canada's real, English-language "County"-named census
    divisions into the SAME counties.csv the US build_counties() above
    writes -- architecture doc SS4/CLAUDE.md's own "the resolver can key
    a Canadian county but jurisdiction_enrich's state-recovery can't see
    one at all" gap (Bruce County ON never got a province, because
    `_COUNTY_STATES` only ever had US rows). Same additive pattern as
    `build_canada_places()`: reads whatever counties.csv already has and
    adds Canada's rows on top, from the SAME real SGC 2021 structure file
    that function and `scripts/build_gov_registry_data.py::build_ca_cd()`
    both already read (Level "3" = census division) -- independently
    re-derived rather than reading `ca_cd.csv`'s own output, matching
    this file's existing convention that the two build scripts stay
    independent entry points (see `_SGC_PROVINCE_CODES`'s own comment).

    Only `_ENGLISH_COUNTY_PROVINCES` rows are added, and "County" is
    appended to each -- `ca_cd.csv` stores these bare ("Bruce", "Elgin",
    not "Bruce County"), which is correct for an ID-bearing table where a
    government TYPE code sits in a separate column, but wrong for this
    one: `counties.csv` has no type column, every existing US row already
    spells the type word IN the name ("Abbeville County", "Acadia
    Parish"), and `_normalize_candidates()`'s query-side matching tries
    the UNSTRIPPED lowercased form FIRST -- a real page's "Bruce County"
    has to equal a stored key of "bruce county", not "bruce", to match on
    that first (most common) try.
    """
    text = (canada_source_dir / "sgc-cgt-2021-structure-eng.csv").read_text(
        encoding="latin-1"
    )
    rows = list(csv.DictReader(text.splitlines()))

    existing_rows: List[Tuple[str, str]] = []
    counties_path = OUT_DIR / "counties.csv"
    if counties_path.exists():
        with open(counties_path, encoding="utf-8") as f:
            existing_rows = [(r["name"], r["state"]) for r in csv.DictReader(f)]

    canada_rows: List[Tuple[str, str]] = []
    skipped_other_word = 0
    for r in rows:
        if r["Level"] != "3":  # Level 3 = "Census division"
            continue
        code = r["Code"].strip()
        prov = _SGC_PROVINCE_CODES.get(code[:2])
        if not prov:
            continue
        if prov not in _ENGLISH_COUNTY_PROVINCES:
            skipped_other_word += 1
            continue
        canada_rows.append((f"{r['Class title'].strip()} County", prov))

    if skipped_other_word:
        print(
            f"build_canada_counties: skipped {skipped_other_word} census divisions "
            'whose province doesn\'t call them "County" (Regional District/MRC/'
            "statistical division)"
        )

    combined = sorted(set(existing_rows) | set(canada_rows))
    with open(counties_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "state"])
        writer.writerows(combined)
    print(
        f"counties.csv: added {len(set(canada_rows))} Canadian county rows "
        f"({len(combined)} total, was {len(existing_rows)})"
    )


def build_canada_regional_municipalities() -> None:
    """Appends the curated list above into the same places.csv
    build_canada_places() just wrote to -- additive, same union-with-
    existing-rows pattern that function already uses, so re-running just
    this step doesn't require re-downloading anything."""
    places_path = OUT_DIR / "places.csv"
    existing_rows: List[Tuple[str, str]] = []
    if places_path.exists():
        with open(places_path, encoding="utf-8") as f:
            existing_rows = [(r["name"], r["state"]) for r in csv.DictReader(f)]

    new_rows: List[Tuple[str, str]] = []
    for name in _ONTARIO_REGIONAL_MUNICIPALITIES:
        new_rows.append((f"{name} Region", "ON"))
        new_rows.append((f"Region of {name}", "ON"))

    combined = sorted(set(existing_rows) | set(new_rows))
    with open(places_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "state"])
        writer.writerows(combined)
    print(
        f"places.csv: added {len(set(new_rows) - set(existing_rows))} Ontario "
        f"regional-municipality rows ({len(combined)} total, was {len(existing_rows)})"
    )


def build_zcta_place(source_dir: Path, fips_to_usps: dict) -> None:
    rows = _read_pipe_delimited(source_dir, "tab20_zcta520_place20_natl.txt")
    out_rows = []
    for r in rows:
        zcta = r["GEOID_ZCTA5_20"].strip()
        if not zcta or r["FUNCSTAT_PLACE_20"] != "A":
            continue
        place_fips = r["GEOID_PLACE_20"].strip()
        state = fips_to_usps.get(place_fips[:2])
        if not state:
            continue
        out_rows.append(
            (zcta, r["NAMELSAD_PLACE_20"].strip(), state, int(r["AREALAND_PART"] or 0))
        )
    with open(OUT_DIR / "zcta_place.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["zcta", "place_name", "state", "area_land_part"])
        writer.writerows(sorted(out_rows))
    print(f"zcta_place.csv: {len(out_rows)} rows")


if __name__ == "__main__":
    args = sys.argv[1:]
    canada_dir = None
    if "--canada" in args:
        idx = args.index("--canada")
        canada_dir = Path(args[idx + 1])
        del args[idx : idx + 2]
    if len(args) != 1:
        print(
            "Usage: python scripts/build_jurisdiction_data.py "
            "/path/to/downloaded/census/files/ [--canada /path/to/ca/files/]"
        )
        sys.exit(1)
    source = Path(args[0])
    fips_to_usps = build_counties(source)
    build_places(source)
    build_county_subdivisions(source)
    build_zcta_county(source, fips_to_usps)
    build_zcta_place(source, fips_to_usps)
    if canada_dir:
        build_canada_places(canada_dir)
        build_canada_regional_municipalities()
        build_canada_counties(canada_dir)
