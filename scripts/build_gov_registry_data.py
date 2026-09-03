"""Generator for the `gov_id` registry's national reference tables --
`app/utils/jurisdiction_data/{us_places,us_counties,us_cousubs,us_states,
us_school_districts,ca_csd,ca_cd,ca_pr,cog_units}.csv`, read at import
time by `app/utils/gov_registry/`.

WO-98, 2026-09-02. Sibling of `scripts/build_jurisdiction_data.py`, NOT a
replacement for it: that script's outputs (`places.csv`, `counties.csv`,
`county_subdivisions.csv`, `zcta_*.csv`) are what
`app/utils/jurisdiction_enrich.py` loads, and `jurisdiction_enrich.py` is
deliberately unchanged this phase -- the resolver calls it rather than
replacing it (GOVERNMENT_IDENTITY_ARCHITECTURE.md §5 step 2). The files
here are additive and name-distinct so the two sets can never be
confused for each other.

What's different about these tables, and why a second script exists at
all: the existing ones carry `name,state` only. The registry needs the
**id** (GEOID / FIPS / SGC code / Census school-district GEOID) that is
the whole point of `gov_id`, plus the LSAD the display rule
(architecture doc §4) needs to disambiguate a within-state name
collision ("Cottage Grove (village), WI"). Neither is recoverable from
the existing outputs, so this reads the same raw Census/StatCan files and
keeps more columns.

Source files (all public domain / open licence, none checked in -- the
trimmed outputs are). Ryan keeps the fetched originals in
`~/Documents/rtr-business/data-product/census_reference/`, which is the
default `--source` if you pass nothing:

  US Census 2024 Gazetteer (public domain, 17 U.S.C. Section 105):
    2024_Gaz_place_national.txt      places, with GEOID + LSAD + FUNCSTAT
    2024_Gaz_counties_national.txt   counties, with 5-digit FIPS GEOID
    2024_Gaz_cousubs_national.txt    county subdivisions, 10-digit GEOID
    2024_Gaz_unsd_national.txt       unified school districts
    2024_Gaz_elsd_national.txt       elementary school districts
    2024_Gaz_scsd_national.txt       secondary school districts
      https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/

  US Census of Governments 2022, Government Units Listing:
    Govt_Units_2022_Final.xlsx
      https://www2.census.gov/programs-surveys/gus/datasets/2022/govt_units_2022.ZIP
    See census_reference/COG_2022_NOTES.md for the column layout and, in
    particular, why `CENSUS_ID_GIDID` is NOT used as an identity code
    here (Census stopped generating it in 2022 and never published its
    segment layout) -- decision D3 keeps COG as pure enrichment this
    phase, so `cog_units.csv` exists to be joined against, not to mint a
    `us:cog:` namespace.

  Statistics Canada SGC 2021 + 2021 Census CSD boundary attributes
  (Statistics Canada Open Licence):
    sgc_2021/sgc-cgt-2021-structure-eng.csv     PR / CD / CSD codes+names
    sgc_2021/csd_types_by_uid_2021.csv          CSDUID -> CSDTYPE
      The second file is transcribed from the `.dbf` of
      lcsd000b21a_e.zip (the 2021 CSD cartographic boundary file) --
      see census_reference/SGC_2021_NOTES.md's 2026-09-02 addendum.
      It exists because the SGC Structure CSV carries NO per-row CSD
      type at all, which is what tells a real municipality apart from a
      statistical equivalent (an unorganized area, a reserve). Without
      it `ca_csd.csv` could not honour "municipalities and municipal
      equivalents only" and would key unorganized areas as governments.

Usage:
    python scripts/build_gov_registry_data.py [/path/to/census_reference/]

Every output is sorted and deterministic, so a rerun against unchanged
sources produces a byte-identical file and an empty diff.
"""

import csv
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, Iterator, List

OUT_DIR = Path(__file__).parent.parent / "app" / "utils" / "jurisdiction_data"
DEFAULT_SOURCE = (
    Path.home() / "Documents" / "rtr-business" / "data-product" / "census_reference"
)


# --- shared readers ---------------------------------------------------


def _read_gazetteer(source_dir: Path, txt_name: str) -> List[dict]:
    """A Gazetteer .txt (tab-separated, latin-1, header columns padded
    with trailing spaces), from the extracted file or its .zip."""
    zip_path = source_dir / txt_name.replace(".txt", ".zip")
    if (source_dir / txt_name).exists():
        text = (source_dir / txt_name).read_text(encoding="latin-1")
    elif zip_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            text = zf.read(txt_name).decode("latin-1")
    else:
        raise SystemExit(f"missing source file: {source_dir / txt_name}")
    rows = []
    for row in csv.DictReader(text.splitlines(), delimiter="\t"):
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _write(name: str, header: List[str], rows) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows)
    with open(OUT_DIR / name, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"{name}: {len(rows)} rows")


# --- US -------------------------------------------------------------


# FUNCSTAT "N" (nonfunctioning) rows kept by GEOID, one at a time, with
# the reason. There are only 4 nationally, so this is a real list, not a
# category: Washington DC (below), plus Louisville city KY, Tribune city
# KS and Houma city LA -- those three are genuinely defunct place
# governments superseded by a consolidated one, and Louisville in
# particular MUST stay out or it collides with the real
# "Louisville/Jefferson County metro government (balance)" row.
#
#   1150000  Washington city, DC. Census codes the District "N" as a
#            *place* because its government is state-level, not because
#            there is no government -- the District plainly governs
#            itself, and 14 real archived pages resolve to it. Confirmed
#            by reading the Gazetteer directly (2026-09-02): the row
#            exists with GEOID 1150000 and is the only DC place row.
_FUNCSTAT_N_KEEP = {"1150000"}


def build_us_places(source_dir: Path) -> None:
    """Incorporated places only, with GEOID + LSAD + FUNCSTAT kept.

    Same FUNCSTAT filter `build_jurisdiction_data.build_places()` already
    landed on and for the same measured reasons: "A" (active incorporated
    government), plus "B" and "F", which are how Census codes the real
    consolidated city-county governments (Nashville-Davidson, Louisville/
    Jefferson, Indianapolis, Baton Rouge -- 10 rows nationally). CDPs
    ("S") are excluded here as there: a CDP is a statistical area with no
    government, and the architecture doc (§4) is explicit that one never
    gets a `us:place` government row.

    LSAD is the column the existing tables don't have and the display
    rule needs -- it is what makes "Cottage Grove (village), WI" data
    rather than a parse of the words "Village of".
    """
    rows = _read_gazetteer(source_dir, "2024_Gaz_place_national.txt")
    out = [
        (r["GEOID"], r["NAME"], r["USPS"], r["LSAD"], r["FUNCSTAT"])
        for r in rows
        if r["FUNCSTAT"] in ("A", "B", "F") or r["GEOID"] in _FUNCSTAT_N_KEEP
    ]
    _write("us_places.csv", ["geoid", "name", "state", "lsad", "funcstat"], out)


def build_us_counties(source_dir: Path) -> Dict[str, str]:
    """Counties keyed by 5-digit FIPS. Returns {state_fips: usps}, the
    cheapest real source for that map (every county row carries both) --
    the same trick `build_jurisdiction_data.build_counties()` uses."""
    rows = _read_gazetteer(source_dir, "2024_Gaz_counties_national.txt")
    out = []
    fips_to_usps: Dict[str, str] = {}
    for r in rows:
        out.append((r["GEOID"], r["NAME"], r["USPS"]))
        fips_to_usps[r["GEOID"][:2]] = r["USPS"]
    _write("us_counties.csv", ["fips", "name", "state"], out)
    return fips_to_usps


def build_us_cousubs(source_dir: Path) -> None:
    """County subdivisions (townships), 10-digit GEOID, FUNCSTAT "A"
    only -- functioning governments.

    Deliberately the same narrow filter as
    `build_jurisdiction_data.build_county_subdivisions()`, not places.csv's
    wider "A"/"B"/"F": that script's own comment records that COUSUB's
    "F" rows are placeholder "County subdivisions not defined" junk, and
    its other codes had no confirmed real example needing them. Nothing
    found this phase changes that, so the filter is copied rather than
    re-litigated.
    """
    rows = _read_gazetteer(source_dir, "2024_Gaz_cousubs_national.txt")
    out = [(r["GEOID"], r["NAME"], r["USPS"]) for r in rows if r["FUNCSTAT"] == "A"]
    _write("us_cousubs.csv", ["geoid", "name", "state"], out)


# The 50 states + DC. Static, official, and small -- hardcoded here for
# the same reason `build_jurisdiction_data._SGC_PROVINCE_CODES` is: this
# script is stdlib-only and must not import from the app (the registry
# package it feeds has the same constraint), and no Gazetteer file
# carries a state *name* against its FIPS code. Names are the Census/USPS
# spellings; FIPS comes from the counties file at runtime, so a typo in a
# code can't silently invent a state.
_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}


def build_us_states(fips_to_usps: Dict[str, str]) -> None:
    """state FIPS -> USPS + name, for `us:state:<fips>` (decision D1: one
    government per state; the Senate/Assembly/agencies are meeting bodies
    under it). Territories present in the counties file (PR, GU, ...) are
    skipped rather than guessed at -- none has appeared in any real
    resolved jurisdiction string, and inventing a name for one here would
    be exactly the kind of unverified row this repo's conventions forbid.
    """
    out = [
        (fips, usps, _STATE_NAMES[usps])
        for fips, usps in fips_to_usps.items()
        if usps in _STATE_NAMES
    ]
    _write("us_states.csv", ["fips", "state", "name"], out)


_SCHOOL_DISTRICT_FILES = {
    "2024_Gaz_unsd_national.txt": "unified",
    "2024_Gaz_elsd_national.txt": "elementary",
    "2024_Gaz_scsd_national.txt": "secondary",
}


def build_us_school_districts(source_dir: Path) -> None:
    """The three Gazetteer school-district files merged, keyed by the
    7-digit GEOID = 2-digit state FIPS + 5-digit NCES LEA code -- the
    `us:sd:` namespace (architecture doc §7's "Clarification recorded
    while deciding": US school districts DO have a national id, it just
    isn't a place GEOID).

    `level` records which file a row came from, because the same district
    name can exist as both an elementary and a secondary district in one
    state (California in particular) -- and because the resolver's
    exactly-one-match-or-nothing rule needs to be able to say *what* it
    matched, not just that it did.
    """
    out = []
    for filename, level in _SCHOOL_DISTRICT_FILES.items():
        for r in _read_gazetteer(source_dir, filename):
            out.append((r["GEOID"], r["NAME"], r["USPS"], level))
    _write("us_school_districts.csv", ["geoid", "name", "state", "level"], out)


# --- Census of Governments (enrichment only, decision D3) -------------


def _xlsx_sheet_rows(path: Path, sheet_name: str) -> Iterator[List[str]]:
    """Minimal stdlib .xlsx reader: enough for this one flat, formula-free
    workbook. Written rather than adding openpyxl to requirements.txt --
    this is a build script that runs on a developer laptop when Census
    republishes, not app code, and the app must not grow a dependency for
    it.

    Handles the two cell shapes this workbook actually uses: shared
    strings (t="s", the default for text) and inline numbers. Cell
    references are decoded so a blank cell doesn't shift a row's columns
    left -- the failure that would silently mis-key every row after it.
    """
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{ns}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))

        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_target = {
            r.get("Id"): r.get("Target")
            for r in rels
            if r.get("Target", "").startswith(("worksheets/", "/xl/worksheets/"))
        }
        target = None
        for sheet in wb.iter(f"{ns}sheet"):
            if sheet.get("name") == sheet_name:
                rid = sheet.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                )
                target = rel_target.get(rid)
        if not target:
            raise SystemExit(f"{path.name}: no sheet named {sheet_name!r}")
        member = "xl/" + target.lstrip("/").removeprefix("xl/")

        with zf.open(member) as fh:
            for _event, elem in ET.iterparse(fh, events=("end",)):
                if elem.tag != f"{ns}row":
                    continue
                cells: Dict[int, str] = {}
                for c in elem.findall(f"{ns}c"):
                    ref = c.get("r") or ""
                    letters = re.match(r"[A-Z]+", ref)
                    idx = 0
                    for ch in letters.group(0) if letters else "A":
                        idx = idx * 26 + (ord(ch) - 64)
                    v = c.find(f"{ns}v")
                    if v is None or v.text is None:
                        text = ""
                    elif c.get("t") == "s":
                        text = shared[int(v.text)]
                    else:
                        text = v.text
                    cells[idx - 1] = text.strip()
                width = max(cells) + 1 if cells else 0
                yield [cells.get(i, "") for i in range(width)]
                elem.clear()


_COG_SHEETS = {
    # sheet name -> gov_type for this registry's vocabulary. The General
    # Purpose sheet is the exception: its own UNIT_TYPE column says which
    # of county/municipality/township a row is, so it is read per row.
    "Special District": "special_district",
    "School District": "school_district",
}
_COG_UNIT_TYPES = {"1": "county", "2": "municipality", "3": "township"}


def build_cog_units(source_dir: Path) -> None:
    """The 2022 Government Units Listing reduced to the five columns
    COG_2022_NOTES.md says matter: the Census id, the name, the type, the
    state and the county area.

    ENRICHMENT ONLY, per decision D3 -- there is deliberately no
    `us:cog:` namespace this phase. The notes' central finding is why:
    `CENSUS_ID_GIDID` is a legacy code Census stopped generating in 2022
    and whose segment layout it has never published (it does not even
    line up with FIPS -- California rows start "05"), and
    `CENSUS_ID_PID6`, while current, is an opaque internal key with no
    documented stability contract. Neither is a foundation for a public
    identifier. `cog_id` here is PID6, stored so a government row can be
    joined back to Census's own record; it is not what identifies it.

    The 'DEP School Dist' sheet is skipped: dependent school systems are
    not independent governments (they are folded into a parent county /
    municipality / township / state), which is exactly the case D2's test
    -- own board? own statute? own budget? -- resolves as `meeting_body`,
    not a government of its own.
    """
    path = source_dir / "Govt_Units_2022_Final.xlsx"
    if not path.exists():
        raise SystemExit(f"missing source file: {path}")
    out = []
    for sheet, fixed_type in [("General Purpose", None), *_COG_SHEETS.items()]:
        rows = _xlsx_sheet_rows(path, sheet)
        header = next(rows)
        col = {name: i for i, name in enumerate(header)}

        def get(row: List[str], name: str) -> str:
            i = col.get(name)
            return row[i] if i is not None and i < len(row) else ""

        for row in rows:
            if not any(row):
                continue
            gov_type = fixed_type
            if gov_type is None:
                unit_type = get(row, "UNIT_TYPE").split("-")[0].strip()
                gov_type = _COG_UNIT_TYPES.get(unit_type)
                if not gov_type:
                    continue
            out.append(
                (
                    get(row, "CENSUS_ID_PID6"),
                    get(row, "UNIT_NAME"),
                    gov_type,
                    get(row, "STATE"),
                    get(row, "COUNTY_AREA_NAME"),
                )
            )
    _write(
        "cog_units.csv",
        ["cog_id", "name", "gov_type", "state", "county_area_name"],
        out,
    )


# --- Canada ----------------------------------------------------------

# Straight from `build_jurisdiction_data._SGC_PROVINCE_CODES` -- the same
# official 13-entry map, duplicated rather than imported because these
# two scripts are independent entry points and neither should be able to
# break the other by moving a constant.
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

# CSD types that are NOT a municipality or municipal equivalent, so they
# get no `ca:csd` government row. Taken from SGC_2021_NOTES.md's own type
# table, row by row -- every code that table marks as something other
# than a municipal government:
#
#   NO, SNO          unorganized / subdivision of unorganized: genuinely
#                    no local government at all
#   IRI, S-É, TC,    reserves and reserved lands: a real government, but a
#   TI, TK           federal First Nations one under the Indian Act, not a
#                    provincial municipality
#   TAL, TWL, TL,    modern treaty / self-government lands
#   NL, SG
#   CC, CG           NT chartered community / community government
#   SET, SÉ          settlements, mostly unincorporated
#   SA               AB special area: administrative, not incorporated
#   RDA              BC regional district electoral area: an unincorporated
#                    area with a seat on a board, not itself a municipality
#
# Where the notes' prose ("everything else is some province's word for an
# incorporated municipality") and its own table disagree, the table wins:
# it is the more specific statement, and excluding a row costs only an
# `rtr:` minted id (the documented D4 fallback for exactly these), while
# wrongly including one would key a statistical area as a government.
# `HAM`/`NH`/`NV`/`VN`/`VC`/`VK` are KEPT: the notes call HAM "mixed --
# treat per-territory", and a northern hamlet/village does have a local
# council, so the less destructive reading applies until a real case says
# otherwise.
_NON_MUNICIPAL_CSD_TYPES = {
    "NO",
    "SNO",
    "IRI",
    "S-É",
    "TC",
    "TI",
    "TK",
    "TAL",
    "TWL",
    "TL",
    "NL",
    "SG",
    "CC",
    "CG",
    "SET",
    "SÉ",
    "SA",
    "RDA",
}


def _sgc_structure_rows(source_dir: Path) -> List[dict]:
    path = source_dir / "sgc_2021" / "sgc-cgt-2021-structure-eng.csv"
    if not path.exists():
        raise SystemExit(f"missing source file: {path}")
    return list(csv.DictReader(path.read_text(encoding="latin-1").splitlines()))


def build_ca_csd(source_dir: Path) -> None:
    """Canadian census subdivisions -- `ca:csd:<7 digits>` -- restricted
    to municipalities and municipal equivalents.

    Two files, because neither is sufficient alone: the SGC Structure CSV
    has every CSD's code and name but no type at all, and the CSD
    boundary file's attribute table has the type but is keyed by CSDUID.
    Joined on that 7-digit code, which is the same number in both.
    Any CSD missing from the type file is DROPPED rather than kept
    untyped -- an unknown type could be an unorganized area, and this
    table's whole contract is "these rows are governments".
    """
    types_path = source_dir / "sgc_2021" / "csd_types_by_uid_2021.csv"
    if not types_path.exists():
        raise SystemExit(
            f"missing source file: {types_path} -- see census_reference/"
            "SGC_2021_NOTES.md's 2026-09-02 addendum for how it is produced"
        )
    with open(types_path, encoding="utf-8") as fh:
        csd_type = {r["CSDUID"]: r["CSDTYPE"] for r in csv.DictReader(fh)}

    out = []
    untyped = 0
    for r in _sgc_structure_rows(source_dir):
        if r["Level"] != "4":
            continue
        code = r["Code"].strip()
        province = _SGC_PROVINCE_CODES.get(code[:2])
        if not province:
            continue
        kind = csd_type.get(code)
        if not kind:
            untyped += 1
            continue
        if kind in _NON_MUNICIPAL_CSD_TYPES:
            continue
        out.append((code, r["Class title"].strip(), kind, province))
    if untyped:
        print(f"ca_csd.csv: dropped {untyped} CSDs with no type in the boundary file")
    _write("ca_csd.csv", ["sgc_code", "name", "csd_type", "province"], out)


def build_ca_cd(source_dir: Path) -> None:
    """Census divisions -- `ca:cd:<4 digits>`. Ontario's upper-tier
    regional municipalities (Peel, Durham, Waterloo -- all real customers
    on this app today) live at this level, not the CSD level, which is why
    the namespace exists at all."""
    out = []
    for r in _sgc_structure_rows(source_dir):
        if r["Level"] != "3":
            continue
        code = r["Code"].strip()
        province = _SGC_PROVINCE_CODES.get(code[:2])
        if not province:
            continue
        out.append((code, r["Class title"].strip(), province))
    _write("ca_cd.csv", ["sgc_code", "name", "province"], out)


def build_ca_pr(source_dir: Path) -> None:
    """Provinces and territories -- `ca:pr:<2 digits>`, the Canadian
    counterpart of `us:state:<fips>`."""
    out = []
    for r in _sgc_structure_rows(source_dir):
        if r["Level"] != "2":
            continue
        code = r["Code"].strip()
        province = _SGC_PROVINCE_CODES.get(code)
        if not province:
            continue
        out.append((code, r["Class title"].strip(), province))
    _write("ca_pr.csv", ["sgc_code", "name", "province"], out)


def main(argv: List[str]) -> None:
    source = Path(argv[0]) if argv else DEFAULT_SOURCE
    if not source.exists():
        raise SystemExit(f"source directory not found: {source}")
    print(f"source: {source}")
    build_us_places(source)
    fips_to_usps = build_us_counties(source)
    build_us_cousubs(source)
    build_us_states(fips_to_usps)
    build_us_school_districts(source)
    build_cog_units(source)
    build_ca_csd(source)
    build_ca_cd(source)
    build_ca_pr(source)


if __name__ == "__main__":
    main(sys.argv[1:])
