"""WO-209 one-off: apply the 73 confirmed bare-name re-keys from the
conductor's post-deploy dry run (`/tmp/postdeploy5_dry.csv`,
`--hosts www.youtube.com,vimeo.com,player.vimeo.com,amsva.wistia.com`) --
see BACKLOG_DONE.md's WO-209 entry for the full writeup.

The dry run proposed 87 re-keys. 14 were the known-wrong Oak Bluffs, MA
wildcard (`gov_id_after == us:cousub:2500750390`, a blank-match pin
already removed by PR #953) -- excluded here entirely, never applied.
The other 73 key a blank/placeholder page to a real government BY NAME
alone (many of these names exist in several states/provinces -- Geneva,
Lincoln, Albany, Plymouth, Woodstock, ...), so the conductor held them
for individual verification before writing anything.

Verification method, for all 73: rather than trusting the page's own
YouTube channel/description (often silent on state -- "City of Bowling
Green" says nothing about Ohio vs Kentucky vs Missouri vs Florida vs
Virginia, all real), this WO cross-referenced each page's own slug
against `rtr-business/research/jurisdiction_coverage.csv`'s
`example_meeting_url` column. That file's row for the SAME government
was populated by an earlier, independent sweep (WO-183/184/191) that
started from the government's own known name+state and its OWN official
domain (bgohio.gov, cityofmanvel.com, arcadiaca.gov, ...), and only THEN
found this exact video linked from that domain -- the strongest
"source host" evidence there is, since a domain like
"townofchapelhilltn.gov" cannot plausibly be about a different Chapel
Hill. All 73 example_meeting_url rows point at the exact page slug this
backfill proposes to re-key, and the recorded government/domain agrees
with the dry run's own gov_id_after in every case -- see
`research/wo209_report.csv` for the full evidence table (one row per
page: domain, recorded government, evidence type).

Two videos (Spring Garden Township, PA and Ogden, IA) are no longer
available on YouTube (`yt-dlp`/oEmbed both return "not available" /
"Unauthorized") -- their government identity is still confirmed via the
same jurisdiction_coverage.csv domain evidence as every other row, since
that evidence predates and doesn't depend on the video still being
live.

Four pages get their gov_id fixed but deliberately get NO
`hub_slug_aliases.csv` row, because their OLD hub slug already belongs
to a DIFFERENT real, live government and must not be hijacked:

| page_id | hub_before | Already belongs to |
|---|---|---|
| 8230 | lincoln | Lincoln, ON (ca:csd:3526057) |
| 8300 | plymouth | Plymouth, MN (us:place:2751730) |
| 8552 | town-of-chapel-hill | Chapel Hill, NC (us:place:3711800) |
| 8319 | town-of-woodstock | Woodstock, NB (ca:csd:1311006) |

Uses the existing POST /internal/jurisdiction/override endpoint, a
narrow, id-scoped write (never a bulk DB sweep). Never prints
ARCHIVE_INGEST_TOKEN. The endpoint also drafts a blank-match
authoritative pin into a server-side pending file as a side effect of
every call -- per the conductor's instruction, that pending file is
never applied (same Oak Bluffs blank-match wildcard shape this WO
excluded above).

Usage: python scripts/wo209_override.py [--apply]
"""

import argparse
import os

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import asyncio  # noqa: E402
import json  # noqa: E402

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# (page_id, gov_id, label) -- label is "<jurisdiction_coverage.csv government>
# (domain <the domain the video was originally found on>)"
CORRECTIONS = [
    (8058, "us:place:3907972", "Bowling Green city, Ohio (domain bgohio.gov)"),
    (8060, "us:place:4846500", "Manvel city, Texas (domain cityofmanvel.com)"),
    (
        8069,
        "us:place:5533100",
        "Hartland village, Wisconsin (domain villageofhartland.wi.gov)",
    ),
    (8077, "us:place:1884878", "Winfield town, Indiana (domain winfieldgov.com)"),
    (8080, "us:place:3654485", "Ogdensburg city, New York (domain ogdensburgny.gov)"),
    (8082, "us:place:2003300", "Augusta city, Kansas (domain augustagov.org)"),
    (
        8083,
        "us:county:55077",
        "Marquette County, Wisconsin (domain marquettecountywi.gov)",
    ),
    (8089, "us:place:2945830", "Maplewood city, Missouri (domain maplewoodmo.gov)"),
    (8091, "us:place:1761899", "Princeton city, Illinois (domain princetonil.com)"),
    (
        8132,
        "ca:csd:3519046",
        "Aurora, Ontario (domain pub-auroraon.escribemeetings.com)",
    ),
    (8168, "us:place:4224000", "Erie city, Pennsylvania (domain cityof.erie.pa.us)"),
    (8175, "us:place:5338038", "Lakewood city, Washington (domain cityoflakewood.us)"),
    (8178, "us:place:0628168", "Gardena city, California (domain gardenaca.gov)"),
    (8181, "us:place:0602462", "Arcadia city, California (domain arcadiaca.gov)"),
    (8186, "us:cousub:3904133516", "Harlem township, Ohio (domain harlemtwp.com)"),
    (
        8188,
        "us:cousub:4213373168",
        "Spring Garden township, Pennsylvania (domain springgardentwp.org)",
    ),
    (
        8200,
        "us:cousub:4201916920",
        "Cranberry township, Pennsylvania (domain cranberrytownship.org)",
    ),
    (
        8212,
        "us:cousub:3901725984",
        "Fairfield township, Ohio (domain fairfieldtwp.org)",
    ),
    (8226, "us:cousub:3611175935", "Ulster town, New York (domain townofulster.org)"),
    (8230, "us:cousub:2301939475", "Lincoln town, Maine (domain lincolnmaine.org)"),
    (8233, "us:place:2213960", "Central city, Louisiana (domain central-la.gov)"),
    (8244, "us:place:2749138", "Otsego city, Minnesota (domain otsegomn.gov)"),
    (8248, "us:place:2966440", "Sedalia city, Missouri (domain cityofsedalia.com)"),
    (
        8257,
        "us:place:2656020",
        "Mount Pleasant city, Michigan (domain mt-pleasant.org)",
    ),
    (8260, "us:place:3976022", "Sylvania city, Ohio (domain cityofsylvania.com)"),
    (
        8263,
        "us:cousub:4208971344",
        "Smithfield township, Pennsylvania (domain smithfieldtownship.com)",
    ),
    (8279, "us:place:2946316", "Marshall city, Missouri (domain marshall-mo.com)"),
    (
        8283,
        "us:place:5530000",
        "Grafton village, Wisconsin (domain village.grafton.wi.us)",
    ),
    (8300, "us:place:1860822", "Plymouth city, Indiana (domain plymouthin.com)"),
    (8306, "us:place:4880224", "Woodway city, Texas (domain woodwaytexas.gov)"),
    (8316, "us:place:5570650", "St. Francis city, Wisconsin (domain stfranciswi.org)"),
    (
        8318,
        "us:place:2151024",
        "Maysville city, Kentucky (domain cityofmaysvilleky.gov)",
    ),
    (
        8319,
        "us:cousub:5002785975",
        "Woodstock town, Vermont (domain townofwoodstock.org)",
    ),
    (8331, "us:place:4933540", "Harrisville city, Utah (domain harrisvillecity.gov)"),
    (8341, "us:place:3929610", "Geneva city, Ohio (domain genevaohio.gov)"),
    (8351, "us:place:2964136", "St. Clair city, Missouri (domain stclairmo.us)"),
    (8357, "us:place:3548620", "Milan village, New Mexico (domain villageofmilan.com)"),
    (8363, "us:place:1800802", "Albany town, Indiana (domain albanyin.com)"),
    (8371, "us:place:4807864", "Bertram city, Texas (domain cityofbertram.org)"),
    (8373, "ca:csd:4811065", "Redwater, Alberta (domain redwater.ca)"),
    (8376, "us:place:3904150", "Batavia village, Ohio (domain bataviaoh.gov)"),
    (8377, "us:cousub:3609182403", "Wilton town, New York (domain townofwilton.com)"),
    (8378, "us:cousub:3602578047", "Walton town, New York (domain townofwalton.org)"),
    (8394, "us:cousub:5002752900", "Norwich town, Vermont (domain norwich.vt.us)"),
    (8398, "us:cousub:3905502904", "Auburn township, Ohio (domain auburntownship.com)"),
    (8404, "us:place:1820080", "Eaton town, Indiana (domain eatonindiana.org)"),
    (8409, "us:cousub:3300300420", "Albany town, New Hampshire (domain albanynh.org)"),
    (
        8412,
        "us:cousub:4209173088",
        "Springfield township, Pennsylvania (domain springfieldmontco.org)",
    ),
    (
        8416,
        "us:cousub:4203768392",
        "Scott township, Pennsylvania (domain scotttownship.com)",
    ),
    (
        8421,
        "us:cousub:4213311432",
        "Carroll township, Pennsylvania (domain carrolltownship.com)",
    ),
    (
        8452,
        "us:cousub:4209133120",
        "Hatfield township, Pennsylvania (domain hatfieldtownship.org)",
    ),
    (8456, "us:cousub:3906176028", "Symmes township, Ohio (domain symmestownship.org)"),
    (
        8471,
        "us:cousub:4201124384",
        "Exeter township, Pennsylvania (domain exetertownship.com)",
    ),
    (
        8479,
        "us:cousub:3905775201",
        "Sugarcreek township, Ohio (domain sugarcreektownship.com)",
    ),
    (
        8491,
        "us:cousub:3916533068",
        "Hamilton township, Ohio (domain hamilton-township.org)",
    ),
    (
        8492,
        "us:cousub:4209150640",
        "Montgomery township, Pennsylvania (domain montgomerytwp.org)",
    ),
    (
        8498,
        "us:place:3963716",
        "Pleasantville village, Ohio (domain villageofpleasantville.com)",
    ),
    (8499, "us:place:1885058", "Wolcott town, Indiana (domain wolcottindiana.org)"),
    (8506, "us:place:1850202", "Monroe town, Indiana (domain townofmonroe.com)"),
    (8518, "us:place:4237208", "Irwin borough, Pennsylvania (domain irwinborough.org)"),
    (8520, "us:place:4769620", "Somerville town, Tennessee (domain somervilletn.gov)"),
    (8526, "us:place:2036950", "Kingman city, Kansas (domain kingmanks.gov)"),
    (8536, "us:place:2731706", "Janesville city, Minnesota (domain janesvillemn.gov)"),
    (8539, "us:place:2610860", "Bronson city, Michigan (domain bronson-mi.com)"),
    (8548, "us:place:1958665", "Ogden city, Iowa (domain ogdeniowa.org)"),
    (8550, "us:place:1815994", "Cromwell town, Indiana (domain cromwellindiana.org)"),
    (
        8552,
        "us:place:4712880",
        "Chapel Hill town, Tennessee (domain townofchapelhilltn.gov)",
    ),
    (8554, "us:place:2980422", "Winfield city, Missouri (domain winfieldmo.org)"),
    (8566, "us:place:1851192", "Morristown town, Indiana (domain morristown.in.gov)"),
    (8574, "us:place:5164272", "Pound town, Virginia (domain poundva.gov)"),
    (8581, "us:place:4668380", "Wall town, South Dakota (domain cityofwall.gov)"),
    (8595, "us:cousub:2612119660", "Dalton township, Michigan (domain daltonmi.gov)"),
    (8601, "ca:csd:4805021", "Standard, Alberta (domain villageofstandard.ca)"),
]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    base = os.environ["ARCHIVE_BASE_URL"].rstrip("/")
    token = os.environ["ARCHIVE_INGEST_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(headers=headers) as sess:
        for page_id, gov_id, label in CORRECTIONS:
            params = {
                "ids": str(page_id),
                "gov_id": gov_id,
                "dry_run": "false" if args.apply else "true",
            }
            async with sess.post(
                f"{base}/internal/jurisdiction/override", params=params
            ) as resp:
                data = await resp.json()
            print(f"--- {label} (id={page_id} -> {gov_id}) ---")
            print(json.dumps(data, indent=2)[:1500])
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
