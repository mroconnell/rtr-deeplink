"""One-time (rerun-when-Census-updates-its-files) generator for
app/utils/jurisdiction_data/*.csv -- the reference tables
app/utils/jurisdiction_enrich.py loads at import time.

Source files are official US Census Bureau Gazetteer/relationship files --
public domain (17 U.S.C. Section 105), no login/API key needed. Download
these four before running (not checked into this repo -- multi-MB raw
files, only the trimmed output below is committed):

  Counties gazetteer:
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_counties_national.zip
  Places (cities/towns) gazetteer:
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip
  ZCTA-to-county relationship file:
    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt
  ZCTA-to-place relationship file:
    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_place20_natl.txt

Usage:
    python scripts/build_jurisdiction_data.py /path/to/downloaded/files/

Deliberately keeps every row, including name collisions across states and
ZCTAs that span multiple counties/places -- app/utils/jurisdiction_enrich.py
decides what to do with ambiguity at lookup time (only resolve a bare name
when it's unique; pick the largest-overlap candidate for a ZCTA using
AREALAND_PART), not here. Only unused columns (lat/long, water area, FIPS
codes not needed for a name/state lookup) are trimmed.
"""

import csv
import sys
import zipfile
from pathlib import Path

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
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/build_jurisdiction_data.py /path/to/downloaded/census/files/"
        )
        sys.exit(1)
    source = Path(sys.argv[1])
    fips_to_usps = build_counties(source)
    build_places(source)
    build_zcta_county(source, fips_to_usps)
    build_zcta_place(source, fips_to_usps)
