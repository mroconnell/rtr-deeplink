"""One-off: apply the 102 pages the Phase 2d signal scan (WO-110,
reports/gov_signals_scoring_2026-09-03/) found recoverable via
extract_gov_signals() + resolve_government(signals=...) -- code that
merged via PR #715 on 2026-09-04 (gov-signals-r2).

This script does NOT depend on that code being deployed. Every target
gov_id/gov_type/jurisdiction below was computed locally (same fallback
derivation resolve_government()'s _as_government() uses for a national
id with no committed governments.csv row -- a place/county/cousub/school-
district/CSD id's fields are a pure function of the id, so this is exact,
not approximate) and is embedded inline as data. This script only needs
the MeetingPage model and DB session -- both long-stable, already
deployed -- so it is safe to run from the CURRENTLY deployed Archive
Render shell regardless of whether #715 has shipped.

Writes `jurisdiction_confidence = "manual_override"`, NOT "registry" --
deliberately. These are real, signal-confirmed resolutions, but the
PLAIN ladder (no signals) still can't reach the same answer on a future
re-ingest, since production ingest doesn't call extract_gov_signals()
yet (that's Step B, not built). "registry" is the one tier a passive
re-ingest happily overwrites; "manual_override" is the one tier
_find_or_create_page() refuses to touch -- see BACKLOG_DONE.md's Santa
Clara entry for why a plain stamp doesn't survive re-ingest and a
protected one does. Unlike POST /internal/jurisdiction/override, this
does NOT write a tenant_overrides.csv rule -- a signal recovery on one
page is not evidence the whole tenant should be pinned to that
government, and 41 of these 102 rows don't even have a committed
governments.csv row yet for such a rule to reference safely.

Safety, same two properties every backfill in this directory has:
  * commit per row -- killing it mid-run leaves a consistent partial
    state;
  * skip a row whose CURRENT gov_id no longer matches what the scan saw
    (something else touched it since 2026-09-03 -- real risk right now,
    several concurrent sessions are active on this exact territory) or
    that is already `manual_override` (a human already decided).

Dry run by default, same convention as backfill_gov_id.py. Run from the
Archive service's Render Shell, with DATABASE_URL already set in that
environment -- never from a laptop against production.

Usage:
    python apply_signal_recovered_pages.py                    # dry run
    python apply_signal_recovered_pages.py --apply --report /tmp/signals_applied.csv
"""

import argparse
import asyncio
import csv
import sys

OVERRIDES = [
    {
        "page_id": 322,
        "gov_id": "us:place:0137000",
        "gov_type": "municipality",
        "jurisdiction": "Huntsville, AL",
        "old_gov_id": "rtr:us:al:huntsville-ordinance-no",
        "tenant_host": "huntsvilleal.granicus.com",
    },
    {
        "page_id": 329,
        "gov_id": "us:county:15007",
        "gov_type": "county",
        "jurisdiction": "Kauai County, HI",
        "old_gov_id": None,
        "tenant_host": "kauai.granicus.com",
    },
    {
        "page_id": 440,
        "gov_id": "us:place:3775000",
        "gov_type": "municipality",
        "jurisdiction": "Winston-Salem, NC",
        "old_gov_id": "rtr:us:nc:lees-summit",
        "tenant_host": "winston-salem.granicus.com",
    },
    {
        "page_id": 693,
        "gov_id": "ca:csd:3519044",
        "gov_type": "municipality",
        "jurisdiction": "Whitchurch-Stouffville, ON",
        "old_gov_id": None,
        "tenant_host": "pub-townofws.escribemeetings.com",
    },
    {
        "page_id": 696,
        "gov_id": "ca:csd:5935029",
        "gov_type": "municipality",
        "jurisdiction": "West Kelowna, BC",
        "old_gov_id": "rtr:ca:bc:west-kelowna-council-chambers",
        "tenant_host": "pub-westkelowna.escribemeetings.com",
    },
    {
        "page_id": 749,
        "gov_id": "us:county:42003",
        "gov_type": "county",
        "jurisdiction": "Allegheny County, PA",
        "old_gov_id": None,
        "tenant_host": "allegheny.granicus.com",
    },
    {
        "page_id": 750,
        "gov_id": "us:place:4202000",
        "gov_type": "municipality",
        "jurisdiction": "Allentown, PA",
        "old_gov_id": None,
        "tenant_host": "allentownpa.granicus.com",
    },
    {
        "page_id": 779,
        "gov_id": "us:place:0613392",
        "gov_type": "municipality",
        "jurisdiction": "Chula Vista, CA",
        "old_gov_id": "rtr:us:ca:chula-vista-public-comments",
        "tenant_host": "pub-chulavista.escribemeetings.com",
    },
    {
        "page_id": 783,
        "gov_id": "ca:csd:4811056",
        "gov_type": "municipality",
        "jurisdiction": "Fort Saskatchewan, AB",
        "old_gov_id": None,
        "tenant_host": "pub-cofs.escribemeetings.com",
    },
    {
        "page_id": 788,
        "gov_id": "ca:csd:3557041",
        "gov_type": "municipality",
        "jurisdiction": "Elliot Lake, ON",
        "old_gov_id": "rtr:ca:on:elliot-lake-gis-services-ssmic",
        "tenant_host": "pub-elliotlake.escribemeetings.com",
    },
    {
        "page_id": 862,
        "gov_id": "us:place:0655184",
        "gov_type": "municipality",
        "jurisdiction": "Palm Desert, CA",
        "old_gov_id": "rtr:us:ca:palm-desert-city-negotiator",
        "tenant_host": "pub-palmdesert.escribemeetings.com",
    },
    {
        "page_id": 906,
        "gov_id": "ca:csd:5915007",
        "gov_type": "municipality",
        "jurisdiction": "White Rock, BC",
        "old_gov_id": None,
        "tenant_host": "pub-whiterockcity.escribemeetings.com",
    },
    {
        "page_id": 918,
        "gov_id": "us:cousub:2500556375",
        "gov_type": "township",
        "jurisdiction": "Rehoboth Town, MA",
        "old_gov_id": "rtr:us:de:rehoboth-beach",
        "tenant_host": "cityofrehoboth.civicweb.net",
    },
    {
        "page_id": 932,
        "gov_id": "ca:csd:5917005",
        "gov_type": "municipality",
        "jurisdiction": "North Saanich, BC",
        "old_gov_id": None,
        "tenant_host": "northsaanich.civicweb.net",
    },
    {
        "page_id": 1032,
        "gov_id": "ca:csd:3530010",
        "gov_type": "municipality",
        "jurisdiction": "Cambridge, ON",
        "old_gov_id": None,
        "tenant_host": "pub-cambridge.escribemeetings.com",
    },
    {
        "page_id": 1554,
        "gov_id": "us:place:5567625",
        "gov_type": "municipality",
        "jurisdiction": "Richland Center, WI",
        "old_gov_id": None,
        "tenant_host": "www.richlandcenterwi.gov",
    },
    {
        "page_id": 1629,
        "gov_id": "us:place:0845970",
        "gov_type": "municipality",
        "jurisdiction": "Longmont, CO",
        "old_gov_id": "rtr:us:co:longmont-for-the-fiscal",
        "tenant_host": "longmont.primegov.com",
    },
    {
        "page_id": 1642,
        "gov_id": "us:place:0670686",
        "gov_type": "municipality",
        "jurisdiction": "Seal Beach, CA",
        "old_gov_id": None,
        "tenant_host": "sealbeach.primegov.com",
    },
    {
        "page_id": 1653,
        "gov_id": "us:place:0682590",
        "gov_type": "municipality",
        "jurisdiction": "Victorville, CA",
        "old_gov_id": None,
        "tenant_host": "victorvilleca.primegov.com",
    },
    {
        "page_id": 2243,
        "gov_id": "us:place:1729938",
        "gov_type": "municipality",
        "jurisdiction": "Glenview, IL",
        "old_gov_id": None,
        "tenant_host": "glenview.granicus.com",
    },
    {
        "page_id": 2384,
        "gov_id": "ca:csd:5915007",
        "gov_type": "municipality",
        "jurisdiction": "White Rock, BC",
        "old_gov_id": None,
        "tenant_host": "pub-whiterockcity.escribemeetings.com",
    },
    {
        "page_id": 2784,
        "gov_id": "us:place:5367167",
        "gov_type": "municipality",
        "jurisdiction": "Spokane Valley, WA",
        "old_gov_id": None,
        "tenant_host": "spokanevalley.granicus.com",
    },
    {
        "page_id": 2848,
        "gov_id": "us:place:1861092",
        "gov_type": "municipality",
        "jurisdiction": "Portage (city), IN",
        "old_gov_id": None,
        "tenant_host": "inportageparks.com",
    },
    {
        "page_id": 2974,
        "gov_id": "us:place:0631260",
        "gov_type": "municipality",
        "jurisdiction": "Gridley, CA",
        "old_gov_id": None,
        "tenant_host": "gridleyca.gov",
    },
    {
        "page_id": 2976,
        "gov_id": "us:place:0686440",
        "gov_type": "municipality",
        "jurisdiction": "Woodside, CA",
        "old_gov_id": None,
        "tenant_host": "woodsideca.gov",
    },
    {
        "page_id": 2991,
        "gov_id": "us:place:2302795",
        "gov_type": "municipality",
        "jurisdiction": "Bangor, ME",
        "old_gov_id": None,
        "tenant_host": "bangormaine.gov",
    },
    {
        "page_id": 2994,
        "gov_id": "us:place:2406800",
        "gov_type": "municipality",
        "jurisdiction": "Berlin, MD",
        "old_gov_id": None,
        "tenant_host": "berlinmd.gov",
    },
    {
        "page_id": 2999,
        "gov_id": "us:place:2747680",
        "gov_type": "municipality",
        "jurisdiction": "Oakdale, MN",
        "old_gov_id": None,
        "tenant_host": "oakdalemn.gov",
    },
    {
        "page_id": 3001,
        "gov_id": "us:place:2771428",
        "gov_type": "municipality",
        "jurisdiction": "Woodbury, MN",
        "old_gov_id": None,
        "tenant_host": "woodburymn.gov",
    },
    {
        "page_id": 3003,
        "gov_id": "us:place:3117670",
        "gov_type": "municipality",
        "jurisdiction": "Fremont, NE",
        "old_gov_id": None,
        "tenant_host": "fremontne.gov",
    },
    {
        "page_id": 3012,
        "gov_id": "us:cousub:3605578971",
        "gov_type": "township",
        "jurisdiction": "Webster (town), NY",
        "old_gov_id": None,
        "tenant_host": "websterny.gov",
    },
    {
        "page_id": 3019,
        "gov_id": "us:place:3954334",
        "gov_type": "municipality",
        "jurisdiction": "New Carlisle, OH",
        "old_gov_id": None,
        "tenant_host": "newcarlisleohio.gov",
    },
    {
        "page_id": 3043,
        "gov_id": "us:county:48259",
        "gov_type": "county",
        "jurisdiction": "Kendall County, TX",
        "old_gov_id": None,
        "tenant_host": "kendallcountytx.gov",
    },
    {
        "page_id": 3044,
        "gov_id": "us:place:4843888",
        "gov_type": "municipality",
        "jurisdiction": "Longview, TX",
        "old_gov_id": None,
        "tenant_host": "longviewtexas.gov",
    },
    {
        "page_id": 3051,
        "gov_id": "us:place:5300100",
        "gov_type": "municipality",
        "jurisdiction": "Aberdeen, WA",
        "old_gov_id": None,
        "tenant_host": "www.aberdeenwa.gov",
    },
    {
        "page_id": 3064,
        "gov_id": "us:place:1743536",
        "gov_type": "municipality",
        "jurisdiction": "Lincoln (city), IL",
        "old_gov_id": None,
        "tenant_host": "lincolnil.gov",
    },
    {
        "page_id": 3066,
        "gov_id": "us:place:1861092",
        "gov_type": "municipality",
        "jurisdiction": "Portage (city), IN",
        "old_gov_id": None,
        "tenant_host": "portagein.gov",
    },
    {
        "page_id": 3073,
        "gov_id": "us:place:2621000",
        "gov_type": "municipality",
        "jurisdiction": "Dearborn, MI",
        "old_gov_id": None,
        "tenant_host": "dearborn.gov",
    },
    {
        "page_id": 3081,
        "gov_id": "us:county:34037",
        "gov_type": "county",
        "jurisdiction": "Sussex County, NJ",
        "old_gov_id": None,
        "tenant_host": "www.sussex.nj.us",
    },
    {
        "page_id": 3082,
        "gov_id": "us:place:3479040",
        "gov_type": "municipality",
        "jurisdiction": "Westfield, NJ",
        "old_gov_id": None,
        "tenant_host": "westfieldnj.gov",
    },
    {
        "page_id": 3097,
        "gov_id": "us:place:4148300",
        "gov_type": "municipality",
        "jurisdiction": "Millersburg, OR",
        "old_gov_id": None,
        "tenant_host": "millersburgoregon.gov",
    },
    {
        "page_id": 3101,
        "gov_id": "us:place:4967825",
        "gov_type": "municipality",
        "jurisdiction": "Saratoga Springs, UT",
        "old_gov_id": None,
        "tenant_host": "saratogasprings-ut.gov",
    },
    {
        "page_id": 3102,
        "gov_id": "us:place:4965330",
        "gov_type": "municipality",
        "jurisdiction": "St. George, UT",
        "old_gov_id": None,
        "tenant_host": "sgcityutah.gov",
    },
    {
        "page_id": 3107,
        "gov_id": "us:place:5582600",
        "gov_type": "municipality",
        "jurisdiction": "Verona (city), WI",
        "old_gov_id": None,
        "tenant_host": "veronawi.gov",
    },
    {
        "page_id": 3163,
        "gov_id": "us:place:2273640",
        "gov_type": "municipality",
        "jurisdiction": "Sulphur, LA",
        "old_gov_id": None,
        "tenant_host": "www.sulphurla.gov",
    },
    {
        "page_id": 3193,
        "gov_id": "ca:csd:4801018",
        "gov_type": "municipality",
        "jurisdiction": "Redcliff, AB",
        "old_gov_id": None,
        "tenant_host": "redcliff.civicweb.net",
    },
    {
        "page_id": 3221,
        "gov_id": "us:cousub:3603557353",
        "gov_type": "township",
        "jurisdiction": "Perth Town, NY",
        "old_gov_id": None,
        "tenant_host": "perth.civicweb.net",
    },
    {
        "page_id": 3253,
        "gov_id": "ca:csd:3530020",
        "gov_type": "municipality",
        "jurisdiction": "Wilmot, ON",
        "old_gov_id": None,
        "tenant_host": "pub-wilmot.escribemeetings.com",
    },
    {
        "page_id": 3267,
        "gov_id": "ca:csd:3530010",
        "gov_type": "municipality",
        "jurisdiction": "Cambridge, ON",
        "old_gov_id": None,
        "tenant_host": "pub-cambridge.escribemeetings.com",
    },
    {
        "page_id": 4072,
        "gov_id": "ca:csd:3530010",
        "gov_type": "municipality",
        "jurisdiction": "Cambridge, ON",
        "old_gov_id": None,
        "tenant_host": "pub-cambridge.escribemeetings.com",
    },
    {
        "page_id": 4166,
        "gov_id": "ca:csd:3530020",
        "gov_type": "municipality",
        "jurisdiction": "Wilmot, ON",
        "old_gov_id": None,
        "tenant_host": "pub-wilmot.escribemeetings.com",
    },
    {
        "page_id": 4687,
        "gov_id": "ca:csd:3530010",
        "gov_type": "municipality",
        "jurisdiction": "Cambridge, ON",
        "old_gov_id": None,
        "tenant_host": "pub-cambridge.escribemeetings.com",
    },
    {
        "page_id": 335,
        "gov_id": "us:place:0644000",
        "gov_type": "municipality",
        "jurisdiction": "Los Angeles, CA",
        "old_gov_id": "rtr:us:ca:l-a-world-airports-board-of-airport-commissioners",
        "tenant_host": "lawa.granicus.com",
    },
    {
        "page_id": 376,
        "gov_id": "us:place:4755120",
        "gov_type": "municipality",
        "jurisdiction": "Oak Ridge, TN",
        "old_gov_id": "rtr:us:tn:oak-ridge",
        "tenant_host": "oakridgetn.granicus.com",
    },
    {
        "page_id": 465,
        "gov_id": "us:place:4869032",
        "gov_type": "municipality",
        "jurisdiction": "Southlake, TX",
        "old_gov_id": "rtr:us:tx:carroll-isd",
        "tenant_host": "carrollisdtx.new.swagit.com",
    },
    {
        "page_id": 473,
        "gov_id": "us:place:0612552",
        "gov_type": "municipality",
        "jurisdiction": "Cerritos, CA",
        "old_gov_id": "rtr:us:ca:cerritos-college",
        "tenant_host": "cerritos.new.swagit.com",
    },
    {
        "page_id": 510,
        "gov_id": "us:place:4829000",
        "gov_type": "municipality",
        "jurisdiction": "Garland, TX",
        "old_gov_id": "rtr:us:tx:garland-isd",
        "tenant_host": "garlandisdtx.new.swagit.com",
    },
    {
        "page_id": 516,
        "gov_id": "us:place:4830464",
        "gov_type": "municipality",
        "jurisdiction": "Grand Prairie, TX",
        "old_gov_id": "rtr:us:tx:grand-prairie-isd",
        "tenant_host": "grandprairieisdtx.new.swagit.com",
    },
    {
        "page_id": 549,
        "gov_id": "us:place:4839148",
        "gov_type": "municipality",
        "jurisdiction": "Killeen, TX",
        "old_gov_id": "rtr:us:tx:killeen-isd",
        "tenant_host": "killeenisdtx.new.swagit.com",
    },
    {
        "page_id": 752,
        "gov_id": "us:place:4803000",
        "gov_type": "municipality",
        "jurisdiction": "Amarillo, TX",
        "old_gov_id": "rtr:us:tx:amarillo",
        "tenant_host": "amarillo.granicus.com",
    },
    {
        "page_id": 757,
        "gov_id": "us:county:05001",
        "gov_type": "county",
        "jurisdiction": "Arkansas County, AR",
        "old_gov_id": "rtr:us:sc:arkansas-supreme-court",
        "tenant_host": "arkansas-sc.granicus.com",
    },
    {
        "page_id": 760,
        "gov_id": "us:place:0603204",
        "gov_type": "municipality",
        "jurisdiction": "Auburn, CA",
        "old_gov_id": "rtr:us:ca:auburn",
        "tenant_host": "auburn.granicus.com",
    },
    {
        "page_id": 839,
        "gov_id": "us:place:1228400",
        "gov_type": "municipality",
        "jurisdiction": "Haines City, FL",
        "old_gov_id": "rtr:us:fl:haines-city-settlement",
        "tenant_host": "pub-hainescity.escribemeetings.com",
    },
    {
        "page_id": 952,
        "gov_id": "us:place:3611000",
        "gov_type": "municipality",
        "jurisdiction": "Buffalo, NY",
        "old_gov_id": "rtr:us:ny:buffalo",
        "tenant_host": "buffalony.iqm2.com",
    },
    {
        "page_id": 1013,
        "gov_id": "us:cousub:3610368473",
        "gov_type": "township",
        "jurisdiction": "Southampton (town), NY",
        "old_gov_id": "rtr:us:ny:southampton-long-island",
        "tenant_host": "southamptonny.iqm2.com",
    },
    {
        "page_id": 1124,
        "gov_id": "us:place:4819000",
        "gov_type": "municipality",
        "jurisdiction": "Dallas, TX",
        "old_gov_id": "rtr:us:tx:dallas-isd",
        "tenant_host": "dallasisdtx.new.swagit.com",
    },
    {
        "page_id": 1150,
        "gov_id": "us:place:0612552",
        "gov_type": "municipality",
        "jurisdiction": "Cerritos, CA",
        "old_gov_id": "rtr:us:ca:cerritos-college",
        "tenant_host": "cerritos.new.swagit.com",
    },
    {
        "page_id": 1173,
        "gov_id": "us:place:4811080",
        "gov_type": "municipality",
        "jurisdiction": "Buda, TX",
        "old_gov_id": "rtr:us:tx:hays-cisd",
        "tenant_host": "hayscisdtx.new.swagit.com",
    },
    {
        "page_id": 1198,
        "gov_id": "us:place:0602000",
        "gov_type": "municipality",
        "jurisdiction": "Anaheim, CA",
        "old_gov_id": "rtr:us:ca:yorba-linda-usd",
        "tenant_host": "pylusd.new.swagit.com",
    },
    {
        "page_id": 1263,
        "gov_id": "us:place:3611000",
        "gov_type": "municipality",
        "jurisdiction": "Buffalo, NY",
        "old_gov_id": "rtr:us:ny:buffalo",
        "tenant_host": "buffalony.iqm2.com",
    },
    {
        "page_id": 1267,
        "gov_id": "us:place:0646842",
        "gov_type": "municipality",
        "jurisdiction": "Menifee, CA",
        "old_gov_id": "rtr:us:ca:menifee-nbsp",
        "tenant_host": "cityofmenifee.primegov.com",
    },
    {
        "page_id": 1330,
        "gov_id": "us:place:1005690",
        "gov_type": "municipality",
        "jurisdiction": "Bethany Beach, DE",
        "old_gov_id": "rtr:us:de:bethany-beach",
        "tenant_host": "bethanybeach.granicus.com",
    },
    {
        "page_id": 1404,
        "gov_id": "us:cousub:3610368000",
        "gov_type": "township",
        "jurisdiction": "Smithtown Town, NY",
        "old_gov_id": "rtr:us:ny:smithtown-smithtown",
        "tenant_host": "smithtownny.iqm2.com",
    },
    {
        "page_id": 1405,
        "gov_id": "us:cousub:3610369463",
        "gov_type": "township",
        "jurisdiction": "Southold Town, NY",
        "old_gov_id": "rtr:us:ny:southold-long-island",
        "tenant_host": "southoldtown.iqm2.com",
    },
    {
        "page_id": 1434,
        "gov_id": "us:place:2407850",
        "gov_type": "municipality",
        "jurisdiction": "Bladensburg, MD",
        "old_gov_id": "rtr:us:md:july13-2026-town-of-bladensburg-maryland-meetings-hub",
        "tenant_host": "bladensburgtown-md.municodemeetings.com",
    },
    {
        "page_id": 1437,
        "gov_id": "us:place:5516450",
        "gov_type": "municipality",
        "jurisdiction": "Columbus (city), WI",
        "old_gov_id": "rtr:us:wi:columbus-wisconsin-meetings-hub",
        "tenant_host": "columbus-wi.municodemeetings.com",
    },
    {
        "page_id": 1444,
        "gov_id": "us:place:4739560",
        "gov_type": "municipality",
        "jurisdiction": "Kingsport, TN",
        "old_gov_id": "rtr:us:tn:municode-portal",
        "tenant_host": "kingsport-tn.municodemeetings.com",
    },
    {
        "page_id": 1446,
        "gov_id": "us:place:2445900",
        "gov_type": "municipality",
        "jurisdiction": "Laurel, MD",
        "old_gov_id": "rtr:us:md:municode-portal",
        "tenant_host": "laurel-md.municodemeetings.com",
    },
    {
        "page_id": 1449,
        "gov_id": "us:place:1242400",
        "gov_type": "municipality",
        "jurisdiction": "Madeira Beach, FL",
        "old_gov_id": "rtr:us:fl:madeira-beach-florida-meetings-hub",
        "tenant_host": "madeirabeach-fl.municodemeetings.com",
    },
    {
        "page_id": 1450,
        "gov_id": "us:place:4861904",
        "gov_type": "municipality",
        "jurisdiction": "Richwood, TX",
        "old_gov_id": "rtr:us:tx:richwood-texas",
        "tenant_host": "richwood-tx.municodemeetings.com",
    },
    {
        "page_id": 1454,
        "gov_id": "us:county:13297",
        "gov_type": "county",
        "jurisdiction": "Walton County, GA",
        "old_gov_id": "rtr:us:ga:walton-county-meetings-portal",
        "tenant_host": "waltoncounty-ga.municodemeetings.com",
    },
    {
        "page_id": 1455,
        "gov_id": "us:place:4879492",
        "gov_type": "municipality",
        "jurisdiction": "Willow Park, TX",
        "old_gov_id": "rtr:us:tx:willow-park-texas-meetings-hub",
        "tenant_host": "willowpark-tx.municodemeetings.com",
    },
    {
        "page_id": 1634,
        "gov_id": "us:place:0655618",
        "gov_type": "municipality",
        "jurisdiction": "Paramount, CA",
        "old_gov_id": "rtr:us:ca:paramount-retiree",
        "tenant_host": "paramountcity.primegov.com",
    },
    {
        "page_id": 1639,
        "gov_id": "us:place:3260600",
        "gov_type": "municipality",
        "jurisdiction": "Reno, NV",
        "old_gov_id": "rtr:us:nv:reno-logo",
        "tenant_host": "reno.primegov.com",
    },
    {
        "page_id": 1775,
        "gov_id": "us:place:5336850",
        "gov_type": "municipality",
        "jurisdiction": "LaCrosse, WA",
        "old_gov_id": "rtr:us:wi:la-crosse",
        "tenant_host": "cityoflacrosse.granicus.com",
    },
    {
        "page_id": 1922,
        "gov_id": "us:place:2616160",
        "gov_type": "municipality",
        "jurisdiction": "Clawson, MI",
        "old_gov_id": "rtr:us:mi:clawson",
        "tenant_host": "clawson.granicus.com",
    },
    {
        "page_id": 1994,
        "gov_id": "us:place:4829000",
        "gov_type": "municipality",
        "jurisdiction": "Garland, TX",
        "old_gov_id": "rtr:us:tx:garland-isd",
        "tenant_host": "garlandisdtx.new.swagit.com",
    },
    {
        "page_id": 2081,
        "gov_id": "us:place:1216875",
        "gov_type": "municipality",
        "jurisdiction": "DeLand, FL",
        "old_gov_id": "rtr:us:fl:deland",
        "tenant_host": "delandfl.granicus.com",
    },
    {
        "page_id": 2105,
        "gov_id": "us:place:2624120",
        "gov_type": "municipality",
        "jurisdiction": "East Lansing, MI",
        "old_gov_id": "rtr:us:mi:east-lansing",
        "tenant_host": "eastlansing.granicus.com",
    },
    {
        "page_id": 2128,
        "gov_id": "us:cousub:3610322194",
        "gov_type": "township",
        "jurisdiction": "East Hampton (town), NY",
        "old_gov_id": "rtr:us:ny:east-hampton-long-island",
        "tenant_host": "easthamptontown.iqm2.com",
    },
    {
        "page_id": 2291,
        "gov_id": "us:place:5135624",
        "gov_type": "municipality",
        "jurisdiction": "Harrisonburg, VA",
        "old_gov_id": "rtr:us:va:harrisonburg",
        "tenant_host": "harrisonburg-va.granicus.com",
    },
    {
        "page_id": 2351,
        "gov_id": "us:cousub:3301337300",
        "gov_type": "township",
        "jurisdiction": "Hooksett Town, NH",
        "old_gov_id": "rtr:us:nh:hooksett",
        "tenant_host": "hooksett.granicus.com",
    },
    {
        "page_id": 2357,
        "gov_id": "us:place:0636056",
        "gov_type": "municipality",
        "jurisdiction": "Huntington Park, CA",
        "old_gov_id": "rtr:us:ca:huntington-park",
        "tenant_host": "huntingtonpark.granicus.com",
    },
    {
        "page_id": 2420,
        "gov_id": "us:cousub:3610368000",
        "gov_type": "township",
        "jurisdiction": "Smithtown Town, NY",
        "old_gov_id": "rtr:us:ny:smithtown-smithtown",
        "tenant_host": "smithtownny.iqm2.com",
    },
    {
        "page_id": 2454,
        "gov_id": "us:place:2647800",
        "gov_type": "municipality",
        "jurisdiction": "Lincoln Park, MI",
        "old_gov_id": "rtr:us:mi:lincoln-park",
        "tenant_host": "lincolnpark-mi.granicus.com",
    },
    {
        "page_id": 2455,
        "gov_id": "us:place:4843096",
        "gov_type": "municipality",
        "jurisdiction": "Live Oak, TX",
        "old_gov_id": "rtr:us:tx:live-oak-texas",
        "tenant_host": "liveoaktx.granicus.com",
    },
    {
        "page_id": 2502,
        "gov_id": "us:cousub:3610310000",
        "gov_type": "township",
        "jurisdiction": "Brookhaven Town, NY",
        "old_gov_id": "rtr:us:ny:farmingville",
        "tenant_host": "brookhavenny.portal.civicclerk.com",
    },
    {
        "page_id": 2528,
        "gov_id": "us:place:5455756",
        "gov_type": "municipality",
        "jurisdiction": "Morgantown, WV",
        "old_gov_id": "rtr:us:wv:morgantown",
        "tenant_host": "morgantown.granicus.com",
    },
    {
        "page_id": 2553,
        "gov_id": "us:place:1855080",
        "gov_type": "municipality",
        "jurisdiction": "North Salem, IN",
        "old_gov_id": "rtr:us:ny:north-salem",
        "tenant_host": "northsalem.granicus.com",
    },
    {
        "page_id": 2609,
        "gov_id": "us:county:02195",
        "gov_type": "county",
        "jurisdiction": "Petersburg Borough, AK",
        "old_gov_id": "rtr:us:ak:petersburg",
        "tenant_host": "petersburg.granicus.com",
    },
    {
        "page_id": 2687,
        "gov_id": "us:place:5357535",
        "gov_type": "municipality",
        "jurisdiction": "Redmond, WA",
        "old_gov_id": "rtr:us:wa:redmond",
        "tenant_host": "redmond.granicus.com",
    },
    {
        "page_id": 3129,
        "gov_id": "us:place:5538675",
        "gov_type": "municipality",
        "jurisdiction": "Juneau, WI",
        "old_gov_id": "rtr:us:ak:juneau",
        "tenant_host": "juneauak.portal.civicclerk.com",
    },
]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=str, default=None)
    args = parser.parse_args()

    from archive.db.crud import _MANUAL_OVERRIDE_CONFIDENCE
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    mode = "APPLY" if args.apply else "DRY RUN"
    print(
        f"signal-recovered-pages backfill -- {mode} -- {len(OVERRIDES)} candidate rows"
    )

    changed = 0
    skipped_mismatch = 0
    skipped_manual = 0
    skipped_missing = 0
    report_rows = []

    async with async_session() as session:
        for row in OVERRIDES:
            page = await session.get(MeetingPage, row["page_id"])
            if page is None:
                skipped_missing += 1
                print(f"  SKIP page {row['page_id']}: no longer exists")
                continue
            if page.jurisdiction_confidence == _MANUAL_OVERRIDE_CONFIDENCE:
                skipped_manual += 1
                print(
                    f"  SKIP page {row['page_id']}: already manual_override, a human decided this one"
                )
                continue
            current = page.gov_id or None
            expected_old = row["old_gov_id"]
            if current != expected_old:
                skipped_mismatch += 1
                print(
                    f"  SKIP page {row['page_id']}: gov_id changed since the 2026-09-03 scan "
                    f"(scan saw {expected_old!r}, now {current!r}) -- something else already touched this row"
                )
                continue

            report_rows.append(
                {
                    "page_id": row["page_id"],
                    "tenant_host": row["tenant_host"],
                    "gov_id_before": current,
                    "gov_id_after": row["gov_id"],
                    "jurisdiction_after": row["jurisdiction"],
                }
            )
            changed += 1
            if args.apply:
                page.gov_id = row["gov_id"]
                page.gov_type = row["gov_type"]
                page.jurisdiction = row["jurisdiction"]
                page.jurisdiction_confidence = _MANUAL_OVERRIDE_CONFIDENCE
                await session.commit()
                print(
                    f"  APPLIED page {row['page_id']}: {current!r} -> {row['gov_id']!r} ({row['jurisdiction']})"
                )
            else:
                print(
                    f"  would change page {row['page_id']}: {current!r} -> {row['gov_id']!r} ({row['jurisdiction']})"
                )

    print()
    print(f"changed     : {changed}")
    print(f"skip (moved): {skipped_mismatch}")
    print(f"skip (human): {skipped_manual}")
    print(f"skip (gone) : {skipped_missing}")
    if not args.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply to write.")

    if args.report:
        with open(args.report, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "page_id",
                    "tenant_host",
                    "gov_id_before",
                    "gov_id_after",
                    "jurisdiction_after",
                ],
            )
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"\nreport written: {args.report}")


if __name__ == "__main__":
    sys.path.insert(0, ".")
    asyncio.run(main())
