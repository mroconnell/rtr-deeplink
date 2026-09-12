"""WO-253 (2026-09-12): the governments whose recorded
`jurisdiction_coverage.csv` `domain` is a meeting-platform tenant
hostname, not the government's own corporate site -- find the real site,
then re-run the WO-235/WO-247 YouTube-channel-link method
(`scripts/wo235_channel_pilot.py` / `scripts/wo247_channel_band.py`)
against it.

This is the named 36-government population from those two WOs'
`BACKLOG.md` entries (14 of 179 from WO-235, 22 of 564 from WO-247), not
a full re-implementation: every access-ladder, link-scanning, yt-dlp-
listing, hand-check-pipeline, and ingest/probe/pin function below is
imported unchanged from `scripts/wo247_channel_band.py` (itself WO-235's
own code, copied for a wider population). Only two things are this WO's
own: (1) the candidate list, hand-built below from real verification
(see `research/wo253_domain_findings.csv`) rather than read from
`jurisdiction_coverage.csv`'s `domain` column, since that column is
exactly what's wrong for this population; (2) the real-site domain used
as `domain` for the discovery fetch.

Of the 36 named rows, 2 are not in this script's candidate list at all:
- Patterson city, CA (`us:place:0656112`) -- already transcribed
  (`transcribed=True` in the live research file) by the time this WO
  started; no longer a "no-video" candidate.
- Providence County, RI (`us:county:44007`) -- confirmed by search
  (Rhode Island counties have had no governing function since 1846) to
  have no real corporate site at all; the row's existing
  `reject_reason=wrong-domain-mapping` and blank `domain` (the tenant
  host `providenceri.iqm2.com` actually belongs to the City of
  Providence, moved to `alternate_domains` already) are already correct
  and need no further action from this WO.

The other 34 each got a real corporate domain found and hand-verified
(see the docstring on CANDIDATES below and `research/
wo253_domain_findings.csv` for the evidence per row) before this script
ever fetches anything from them for the channel check.

Two real domain-MAPPING bugs (not just "recorded domain is a tenant
host", but "the tenant host belongs to an unrelated government
entirely") were found verifying this population and are filed in
`BACKLOG.md`, not silently fixed here: Amherst County, VA's recorded
`domain` (`amherstny.iqm2.com`) is the Town of Amherst, NEW YORK's IQM2
tenant; Destin city, FL's recorded `domain`
(`okaloosacountyfl.iqm2.com`) is Okaloosa COUNTY's own IQM2 tenant, not
Destin's. Alachua city, FL's recorded `domain` (`alachua.granicus.com`)
is suspected of the same shape (its own `example_meeting_url` names an
"alachua-county-fl" meeting) but wasn't independently confirmed the same
way. For all three, this script still runs the channel check against
the CONFIRMED-correct corporate site for the named government
(`countyofamherst.com`, `cityofdestin.com`, `cityofalachua.com`) --
finding the right site for the channel check doesn't require first
untangling the mapping bug, and re-mapping `domain` for a different
government than this WO is about is out of scope here.

Environment:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo253_scratch.db" \\
        .venv/bin/python scripts/wo253_platform_domain_recheck.py discover --limit 20
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo253_scratch.db" \\
        .venv/bin/python scripts/wo253_platform_domain_recheck.py finalize
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path
from typing import List

import aiohttp

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.wo247_channel_band import (  # noqa: E402
    DISCOVERY_FIELDS,
    OWNER_BODIES_FIELDS,
    REPORT_FIELDS,
    discover_one,
    finalize_one,
)
from scripts.wo174_pipeline import fetch_covered_gov_ids  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
DISCOVERY_CSV = RESEARCH_DIR / "wo253_discovery.csv"
DECISIONS_CSV = RESEARCH_DIR / "wo253_decisions.csv"
REPORT_CSV = RESEARCH_DIR / "wo253_report.csv"
OWNER_BODIES_CSV = RESEARCH_DIR / "wo253_owner_bodies.csv"

GOVERNMENT_DELAY_SECONDS = 1.5

# gov_id -> real corporate domain, hand-verified (see module docstring
# and research/wo253_domain_findings.csv). Population/state/name/
# known_platform pulled from the live jurisdiction_coverage.csv at the
# time this WO ran (2026-09-12) -- re-derive rather than trust if this
# script is ever re-run much later.
CANDIDATES = [
    # gov_id, name, state, population, known_platform, real_domain
    ("us:place:1921000", "Des Moines city", "Iowa", "212086", "civicweb", "dsm.city"),
    (
        "us:county:54081",
        "Raleigh County",
        "West Virginia",
        "71775",
        "escribe",
        "raleighcounty.gov",
    ),
    ("us:place:1301052", "Albany city", "Georgia", "66907", "escribe", "albanyga.gov"),
    (
        "us:place:0667112",
        "San Jacinto city",
        "California",
        "56014",
        "iqm2",
        "sanjacintoca.gov",
    ),
    (
        "us:place:5357535",
        "Redmond city",
        "Washington",
        "82506",
        "granicus",
        "redmond.gov",
    ),
    ("us:county:27169", "Winona County", "Minnesota", "50523", "", "co.winona.mn.us"),
    (
        "us:place:0616742",
        "Covina city",
        "California",
        "49404",
        "escribe",
        "covinaca.gov",
    ),
    (
        "us:place:3651055",
        "Niagara Falls city",
        "New York",
        "47255",
        "civicweb",
        "niagarafallsusa.org",
    ),
    (
        "us:county:19057",
        "Des Moines County",
        "Iowa",
        "38077",
        "civicweb",
        "desmoinescounty.iowa.gov",
    ),
    ("us:place:3035600", "Helena city", "Montana", "35138", "primegov", "helenamt.gov"),
    (
        "us:county:51009",
        "Amherst County",
        "Virginia",
        "31962",
        "iqm2",
        "countyofamherst.com",
    ),
    (
        "us:place:5309480",
        "Camas city",
        "Washington",
        "27749",
        "swagit",
        "cityofcamas.us",
    ),
    ("ca:csd:4812002", "Cold Lake", "Alberta", "15661", "escribe", "coldlake.com"),
    (
        "ca:csd:5909020",
        "Chilliwack",
        "British Columbia",
        "93203",
        "escribe",
        "chilliwack.com",
    ),
    (
        "us:place:0616378",
        "Coronado city",
        "California",
        "21094",
        "primegov",
        "coronado.ca.us",
    ),
    (
        "us:place:0665028",
        "San Bruno city",
        "California",
        "42305",
        "primegov",
        "sanbruno.ca.gov",
    ),
    (
        "us:place:1200375",
        "Alachua city",
        "Florida",
        "10612",
        "granicus",
        "cityofalachua.com",
    ),
    ("us:place:1217325", "Destin city", "Florida", "14046", "iqm2", "cityofdestin.com"),
    (
        "us:place:1706613",
        "Bloomington city",
        "Illinois",
        "78804",
        "iqm2",
        "bloomingtonil.gov",
    ),
    (
        "us:place:1753481",
        "Northbrook village",
        "Illinois",
        "34744",
        "iqm2",
        "northbrook.il.us",
    ),
    (
        "us:county:18091",
        "LaPorte County",
        "Indiana",
        "111294",
        "escribe",
        "laportecounty.org",
    ),
    ("us:place:2556585", "Revere city", "Massachusetts", "60141", "iqm2", "revere.org"),
    (
        "ca:csd:1301006",
        "Saint John",
        "New Brunswick",
        "69895",
        "escribe",
        "saintjohn.ca",
    ),
    (
        "us:place:3448300",
        "Morristown town",
        "New Jersey",
        "20750",
        "iqm2",
        "townofmorristown.org",
    ),
    (
        "us:county:37077",
        "Granville County",
        "North Carolina",
        "61421",
        "",
        "granvillecounty.org",
    ),
    (
        "us:place:3853380",
        "Minot city",
        "North Dakota",
        "47308",
        "civicclerk",
        "minotnd.gov",
    ),
    (
        "us:place:4131250",
        "Gresham city",
        "Oregon",
        "111513",
        "swagit",
        "greshamoregon.gov",
    ),
    (
        "us:place:5315290",
        "Covington city",
        "Washington",
        "21496",
        "primegov",
        "covingtonwa.gov",
    ),
    (
        "ca:csd:3509028",
        "Carleton Place",
        "Ontario",
        "12517",
        "escribe",
        "carletonplace.ca",
    ),
    (
        "ca:csd:3515013",
        "Cavan Monaghan",
        "Ontario",
        "10016",
        "escribe",
        "cavanmonaghan.net",
    ),
    ("ca:csd:3502008", "Hawkesbury", "Ontario", "10194", "escribe", "hawkesbury.ca"),
    ("ca:csd:3541024", "Kincardine", "Ontario", "12268", "escribe", "kincardine.ca"),
    ("ca:csd:3519048", "Newmarket", "Ontario", "87942", "escribe", "newmarket.ca"),
    ("ca:csd:4706027", "Regina", "Saskatchewan", "226404", "iqm2", "regina.ca"),
    # The 7 rows WO-252 (population 5,000-9,999 band) found and deferred
    # to this WO rather than guessing at (`research/wo252_platform_domain_rows.csv`).
    ("ca:csd:3547048", "Renfrew", "Ontario", "8190", "escribe", "renfrewontario.com"),
    ("us:place:5502250", "Antigo city", "Wisconsin", "8060", "iqm2", "antigo-city.org"),
    ("ca:csd:3515023", "Douro-Dummer", "Ontario", "7632", "escribe", "dourodummer.ca"),
    ("ca:csd:5933006", "Merritt", "British Columbia", "7051", "escribe", "merritt.ca"),
    (
        "us:county:21165",
        "Menifee County",
        "Kentucky",
        "6430",
        "primegov",
        "menifeecounty.ky.gov",
    ),
    (
        "ca:csd:3539060",
        "Lucan Biddulph",
        "Ontario",
        "5680",
        "escribe",
        "lucanbiddulph.on.ca",
    ),
    ("ca:csd:3534042", "West Elgin", "Ontario", "5060", "escribe", "westelgin.net"),
]


def _load_candidates() -> List[dict]:
    rows = []
    for gov_id, name, state, population, known_platform, domain in CANDIDATES:
        rows.append(
            {
                "gov_id": gov_id,
                "name": name,
                "state": state,
                "population": population,
                "known_platform": known_platform,
                "domain": domain,
                "hub_url": "",
            }
        )
    return rows


def _already_discovered_gov_ids() -> set:
    if not DISCOVERY_CSV.exists():
        return set()
    with DISCOVERY_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def _write_discovery_row(row: dict) -> None:
    is_new = not DISCOVERY_CSV.exists()
    with DISCOVERY_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DISCOVERY_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _already_reported_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def _write_report_row(row: dict) -> None:
    is_new = not REPORT_CSV.exists()
    with REPORT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _write_owner_body_row(row: dict) -> None:
    is_new = not OWNER_BODIES_CSV.exists()
    with OWNER_BODIES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OWNER_BODIES_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _discovery_row_by_gov_id() -> dict:
    out = {}
    if DISCOVERY_CSV.exists():
        with DISCOVERY_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["gov_id"]] = r
    return out


async def cmd_discover(args) -> None:
    candidates = _load_candidates()
    print(f"{len(candidates)} WO-253 candidates (hand-built, real domains)")
    already = _already_discovered_gov_ids()
    todo = [r for r in candidates if r["gov_id"] not in already]
    chunk = todo[: args.limit] if args.limit else todo
    print(f"processing {len(chunk)} of {len(todo)} remaining this run")

    covered = fetch_covered_gov_ids()
    print(f"{len(covered)} gov_ids already have an Archive page (live check)")

    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(chunk):
            if i:
                await asyncio.sleep(GOVERNMENT_DELAY_SECONDS)
            try:
                result = await discover_one(session, row, covered)
            except Exception as e:  # noqa: BLE001
                result = {
                    "gov_id": row["gov_id"],
                    "name": row["name"],
                    "state": row["state"],
                    "population": row.get("population") or "",
                    "known_platform": row.get("known_platform") or "",
                    "domain": row.get("domain") or "",
                    "hub_url": row.get("hub_url") or "",
                    "channel_urls": "",
                    "channel_owner_guess": "",
                    "channel_name": "",
                    "channel_uploader_id": "",
                    "channel_description_snippet": "",
                    "meetings_on_channel": "",
                    "candidates": "",
                    "access_mode": "error",
                    "note": f"error: {type(e).__name__}: {e}",
                }
            _write_discovery_row(result)
            print(
                f"[{i + 1}/{len(chunk)}] {result['gov_id']} {result['name']}, {result['state']}: "
                f"{result.get('channel_owner_guess') or ''} {result.get('note') or ''} "
                f"channels={result.get('channel_urls')!r}"
            )
    remaining = len(todo) - len(chunk)
    print(f"\n{remaining} candidates remain undiscovered after this run.")


async def cmd_finalize(args) -> None:
    if not DECISIONS_CSV.exists():
        print(f"{DECISIONS_CSV} does not exist -- nothing to finalize.")
        return
    with DECISIONS_CSV.open(newline="", encoding="utf-8") as f:
        decisions = list(csv.DictReader(f))
    already = _already_reported_gov_ids()
    todo = [d for d in decisions if d["gov_id"] not in already]
    print(
        f"{len(decisions)} decisions, {len(already)} already reported, {len(todo)} to finalize"
    )
    disc_by_id = _discovery_row_by_gov_id()

    chunk = todo[: args.limit] if args.limit else todo
    async with aiohttp.ClientSession() as session:
        for i, decision in enumerate(chunk):
            if i:
                await asyncio.sleep(GOVERNMENT_DELAY_SECONDS)
            disc = disc_by_id.get(decision["gov_id"], {})
            if decision.get("decision") == "owner_elsewhere":
                # Handled here, not via the imported finalize_one:
                # that function's owner_elsewhere branch calls
                # wo247_channel_band's OWN module-level
                # _write_owner_body_row, which would append into
                # wo247_owner_bodies.csv (a different WO's closed-out
                # file) rather than this WO's own wo253_owner_bodies.csv.
                _write_owner_body_row(
                    {
                        "gov_id_of_site_checked": decision["gov_id"],
                        "owner_name": decision.get("owner_name", ""),
                        "channel_url": decision.get("owner_channel_url")
                        or disc.get("channel_urls", ""),
                        "video_url": decision.get("owner_video_url", ""),
                        "owner_gov_id_if_known": "",
                        "note": decision.get("note", ""),
                    }
                )
                row = {
                    "gov_id": decision["gov_id"],
                    "name": disc.get("name", ""),
                    "state": disc.get("state", ""),
                    "population": disc.get("population", ""),
                    "known_platform": disc.get("known_platform", ""),
                    "channel_url": disc.get("channel_urls", ""),
                    "channel_owner": decision.get("channel_owner", ""),
                    "meetings_on_channel": disc.get("meetings_on_channel", ""),
                    "chosen_video": "",
                    "outcome": "wrong_channel",
                    "hand_check": "wrong (Kind A -- owner elsewhere)",
                    "page_url": "",
                    "note": f"owner: {decision.get('owner_name', '')}; "
                    + decision.get("note", ""),
                }
            else:
                try:
                    row = await finalize_one(session, decision, disc)
                except Exception as e:  # noqa: BLE001
                    row = {
                        "gov_id": decision["gov_id"],
                        "name": disc.get("name", ""),
                        "state": disc.get("state", ""),
                        "population": disc.get("population", ""),
                        "known_platform": disc.get("known_platform", ""),
                        "channel_url": disc.get("channel_urls", ""),
                        "channel_owner": decision.get("channel_owner", ""),
                        "meetings_on_channel": disc.get("meetings_on_channel", ""),
                        "chosen_video": "",
                        "outcome": "error",
                        "hand_check": "ok",
                        "page_url": "",
                        "note": f"error: {type(e).__name__}: {e}",
                    }
            _write_report_row(row)
            print(
                f"[{i + 1}/{len(chunk)}] {row['gov_id']} {row['name']}, {row['state']}: {row['outcome']} -- {row['note']}"
            )
    print(f"\n{len(todo) - len(chunk)} decisions remain unfinalized after this run.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--limit", type=int, default=0)
    p_discover.set_defaults(func=cmd_discover)

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--limit", type=int, default=0)
    p_finalize.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
