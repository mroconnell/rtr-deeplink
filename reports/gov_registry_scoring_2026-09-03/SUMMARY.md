# Phase 1 — gov_id registry scoring (2026-09-03)

Inputs: **5053** archived pages (`GET /internal/export/pages`, metadata only) and **876** distinct (tenant, jurisdiction) pairs from rtr-discovery's ledger. Read-only; no schema change, no production write.

## Tier distribution

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 207 (4.1%) | 38 (4.3%) |
| registry | 3896 (77.1%) | 803 (91.7%) |
| inferred | 11 (0.2%) | 0 (0.0%) |
| unverified | 287 (5.7%) | 2 (0.2%) |
| unresolved | 414 (8.2%) | 33 (3.8%) |
| blank | 238 (4.7%) | 0 (0.0%) |

**4880 of 5929** rows (82.3%) got a national id.

## Phase 1b targets — before / after

| check | Phase 1 | now | target |
| --- | --- | --- | --- |
| rows on the county table whose raw name had a municipal type word | 26 | **0** | 0 |
| `rtr:us:xx:` / `rtr:ca:xx:` ids | 624 | **0** | 0 |
| pins sourced only from `auto_derived` | 447 | **0** | 0 |

## The minting gate

**20** rows carry a string that is not a government name -- a subdomain fragment, an initialism or a station callsign -- and are tier `unresolved` with the raw text kept in `evidence`, rather than minting an `rtr:` id nobody could ever look up.

| platform | rows | distinct hosts |
| --- | --- | --- |
| granicus | 14 | 14 |
| youtube | 2 | 1 |
| swagit | 2 | 2 |
| escribe | 1 | 1 |
| telvue | 1 | 1 |

| country | rows |
| --- | --- |
| us | 19 |
| ca | 1 |

Examples: 'City of Al', 'City, MA', 'Llbc', 'Ps C, FL', 'Rye (city), NY', 'Rye (town), NY', 'S Fw, MD', 'TV, NY', 'Unknown Jurisdiction'

## Pin worklist

`pin_worklist.csv` -- **381** tenant hosts with no government across 685 rows, each with a landing URL to fetch once and read the organisation name out of the header, the way `jurisdiction_overrides.csv`'s `visual_confirmed` rows were made. Ordered eScribe / Cablecast / Swagit / TelVue first -- the four whose landing page reliably names its customer. TelVue rows carry the org token from the URL path as `match_value`, because every TelVue customer shares one host and a host-level pin would be wrong for all of them.

## Government types

| gov_type | rows |
| --- | --- |
| municipality | 4085 |
| county | 851 |
| other | 610 |
| township | 161 |
| school_district | 125 |
| special_district | 82 |
| state | 10 |
| court | 5 |

## Merges and splits

- **199 merges** — two or more current `/j/` hubs collapsing into one `gov_id` (400 hubs in total).
- **16 splits** — one current hub becoming several `gov_id`s.

Largest merges:

- `us:place:4752006` — Nashville-Davidson, TN ← nashville|nashville-davidson-county-tn|nashville-davidson-tn
- `us:county:44001` — Bristol County, RI ← bristol-county-ri|bristol-ri|bristol-town-ri
- `us:county:06055` — Napa County, CA ← county-of-napa-ca|napa-county-ca
- `us:place:2938000` — Kansas City, MO ← kansas-city|kansas-city-mo
- `us:place:5553000` — Milwaukee, WI ← milwaukee|milwaukee-wi
- `us:place:2148006` — Louisville/Jefferson County, KY ← louisville-jefferson-county-ky|louisville-ky
- `us:county:06071` — San Bernardino County, CA ← county-of-san-bernardino-ca|san-bernardino-county-ca
- `us:county:32003` — Clark County, NV ← clark-county-nv|county-of-clark
- `us:county:53033` — King County, WA ← king-county|king-county-wa
- `us:county:06085` — Santa Clara County, CA ← county-of-santa-clara-ca|santa-clara-county-ca
- `us:county:06081` — San Mateo County, CA ← county-of-san-mateo-ca|san-mateo-county-ca
- `us:county:06041` — Marin County, CA ← county-of-marin-ca|marin-county-ca
- `us:place:5107784` — Blacksburg, VA ← blacksburg-va|town-of-blacksburg
- `us:place:0808675` — Brighton, CO ← brighton|brighton-co
- `us:place:0608954` — Burbank, CA ← burbank|burbank-ca

Splits:

- `/j/san-diego-ca` → rtr:us:ca:san-diego-association-of-governments|us:place:0666000
- `/j/los-angeles-ca` → rtr:us:ca:los-angeles-department-of-water-and-power|us:place:0644000
- `/j/los-angeles-county-ca` → rtr:us:ca:los-angeles-county-metropolitan-transportation-authority|us:county:06037
- `/j/horry-county-sc` → us:county:45051|us:sd:4502490
- `/j/amarillo-tx` → rtr:us:tx:amarillo|us:place:4803000
- `/j/beaufort-county-sc` → us:county:45013|us:place:4507210
- `/j/indio-ca` → rtr:us:ca:coachella-valley-water-district|us:place:0636448
- `/j/east-lansing-mi` → rtr:us:mi:east-lansing|us:place:2624120
- `/j/municode-portal` → rtr:us:md:municode-portal|rtr:us:tn:municode-portal
- `/j/tarrant-county-tx` → rtr:us:tx:tarrant-county-college-district|us:county:48439
- `/j/hamilton` → rtr:ca:on:hamilton-police-services-board|us:place:3933012
- `/j/lincoln-park-mi` → rtr:us:mi:lincoln-park|us:place:2647800
- `/j/victoria` → ca:csd:5917034|us:place:2767036
- `/j/markham` → rtr:ca:on:toronto-and-region-conservation-authority|us:place:1747007
- `/j/town-of-atherton-ca` → rtr:us:ca:menlo-park-fire-protection-district|us:place:0603092

## What the /state/* headings will read

From `gov_type` via `archive/utils/gov_groups.py`, which replaced `archive/utils/gov_classify.py`'s regex over the display name (WO-99). Every row is a page, not a distinct government.

| heading | gov_type | rows |
| --- | --- | --- |
| Cities & towns | municipality | 4085 |
| Counties & regions | county | 851 |
| Other public bodies | other | 610 |
| Cities & towns | township | 161 |
| School districts | school_district | 125 |
| Agencies & special districts | special_district | 82 |
| State government | state | 10 |
| Courts | court | 5 |

## Canada

**477 of 503** Canadian rows (94.8%) got a StatCan id (`ca:csd` / `ca:cd` / `ca:pr`); the rest mint `rtr:ca:`.

## Minted and unknown

- **369** distinct minted `rtr:` governments over 602 rows.
- **238** rows with nothing at all (`rtr:unknown:<host>`).
- **447** rows tier `unresolved` — a real government name with no state and nothing to key it by. Listed in `unresolved.csv` for a `tenant_overrides.csv` pin; deliberately NOT minted, because an id nobody can key looks resolved and is not.
- **11** rows resolved by same-tenant consistency (tier `inferred`).

