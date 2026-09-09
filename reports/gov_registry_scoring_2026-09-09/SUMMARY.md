# Phase 1 — gov_id registry scoring (2026-09-09)

Inputs: **6410** archived pages (`GET /internal/export/pages`, metadata only) and **876** distinct (tenant, jurisdiction) pairs from rtr-discovery's ledger. Read-only; no schema change, no production write.

## Tier distribution

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 322 (5.0%) | 73 (8.3%) |
| registry | 5255 (82.0%) | 780 (89.0%) |
| inferred | 23 (0.4%) | 1 (0.1%) |
| unverified | 205 (3.2%) | 2 (0.2%) |
| unresolved | 320 (5.0%) | 20 (2.3%) |
| blank | 285 (4.4%) | 0 (0.0%) |

**6372 of 7286** rows (87.5%) got a national id.

## Phase 1b targets — before / after

| check | Phase 1 | now | target |
| --- | --- | --- | --- |
| rows on the county table whose raw name had a municipal type word | 26 | **0** | 0 |
| `rtr:us:xx:` / `rtr:ca:xx:` ids | 624 | **0** | 0 |
| pins sourced only from `auto_derived` | 447 | **0** | 0 |

## The minting gate

**14** rows carry a string that is not a government name -- a subdomain fragment, an initialism or a station callsign -- and are tier `unresolved` with the raw text kept in `evidence`, rather than minting an `rtr:` id nobody could ever look up.

| platform | rows | distinct hosts |
| --- | --- | --- |
| granicus | 10 | 10 |
| escribe | 1 | 1 |
| telvue | 1 | 1 |
| swagit | 1 | 1 |
| civicclerk | 1 | 1 |

| country | rows |
| --- | --- |
| us | 13 |
| ca | 1 |

Examples: 'City, MA', 'Llbc', 'Sumterville, FL', 'TV, NY', 'Unknown Jurisdiction'

## Pin worklist

`pin_worklist.csv` -- **372** tenant hosts with no government across 625 rows, each with a landing URL to fetch once and read the organisation name out of the header, the way `jurisdiction_overrides.csv`'s `visual_confirmed` rows were made. Ordered eScribe / Cablecast / Swagit / TelVue first -- the four whose landing page reliably names its customer. TelVue rows carry the org token from the URL path as `match_value`, because every TelVue customer shares one host and a host-level pin would be wrong for all of them.

## Government types

| gov_type | rows |
| --- | --- |
| municipality | 5085 |
| county | 1175 |
| other | 531 |
| township | 184 |
| school_district | 154 |
| special_district | 133 |
| state | 17 |
| court | 7 |

## Merges and splits

- **271 merges** — two or more current `/j/` hubs collapsing into one `gov_id` (548 hubs in total).
- **16 splits** — one current hub becoming several `gov_id`s.

Largest merges:

- `us:place:4752006` — Nashville-Davidson, TN ← nashville|nashville-davidson-county-tn|nashville-davidson-tn
- `us:place:0812415` — Castle Rock, CO ← castle-rock-co|the-town-of-castle-rock-co|town-of-castle-rock
- `us:place:3668462` — Southampton (village), NY ← southampton|southampton-ny|southampton-village-ny
- `us:place:5516450` — Columbus (city), WI ← columbus-city-wi|columbus-wi|columbus-wisconsin-meetings-hub
- `us:place:4254184` — Newtown (borough), PA ← newtown-borough-pa|newtown-pa|township-of-newtown
- `us:place:5517175` — Cottage Grove (village), WI ← cottage-grove-village-wi|cottage-grove-wi|village-of-cottage-grove-wi
- `us:place:2021275` — Emporia (city), KS ← emporia-city-ks|emporia-ks
- `us:county:06055` — Napa County, CA ← county-of-napa-ca|napa-county-ca
- `us:place:2938000` — Kansas City, MO ← kansas-city|kansas-city-mo
- `us:place:5553000` — Milwaukee, WI ← milwaukee|milwaukee-wi
- `us:place:2148006` — Louisville/Jefferson County, KY ← louisville-jefferson-county-ky|louisville-ky
- `us:place:0656000` — Pasadena, CA ← pasadena|pasadena-ca
- `us:county:06071` — San Bernardino County, CA ← county-of-san-bernardino-ca|san-bernardino-county-ca
- `us:county:32003` — Clark County, NV ← clark-county-nv|county-of-clark
- `us:county:53033` — King County, WA ← king-county|king-county-wa

Splits:

- `/j/san-diego-ca` → rtr:us:ca:san-diego-association-of-governments|us:place:0666000
- `/j/los-angeles-ca` → rtr:us:ca:los-angeles-department-of-water-and-power|us:place:0644000
- `/j/los-angeles-county-ca` → rtr:us:ca:los-angeles-county-metropolitan-transportation-authority|us:county:06037
- `/j/horry-county-sc` → us:county:45051|us:sd:4502490
- `/j/lees-summit` → us:place:2941348|us:place:3775000
- `/j/amarillo-tx` → rtr:us:tx:amarillo|us:place:4803000
- `/j/beaufort-county-sc` → us:county:45013|us:place:4507210
- `/j/indio-ca` → rtr:us:ca:coachella-valley-water-district|us:place:0636448
- `/j/east-lansing-mi` → rtr:us:mi:east-lansing|us:place:2624120
- `/j/lincoln` → ca:csd:3526057|us:place:1743536
- `/j/municode-portal` → us:place:2445900|us:place:4739560
- `/j/tarrant-county-tx` → rtr:us:tx:tarrant-county-college-district|us:county:48439
- `/j/lincoln-park-mi` → rtr:us:mi:lincoln-park|us:place:2647800
- `/j/markham` → ca:csd:3519036|rtr:ca:on:toronto-and-region-conservation-authority
- `/j/town-of-atherton-ca` → rtr:us:ca:menlo-park-fire-protection-district|us:place:0603092

## What the /state/* headings will read

From `gov_type` via `archive/utils/gov_groups.py`, which replaced `archive/utils/gov_classify.py`'s regex over the display name (WO-99). Every row is a page, not a distinct government.

| heading | gov_type | rows |
| --- | --- | --- |
| Cities & towns | municipality | 5085 |
| Counties & regions | county | 1175 |
| Other public bodies | other | 531 |
| Cities & towns | township | 184 |
| School districts | school_district | 154 |
| Agencies & special districts | special_district | 133 |
| State government | state | 17 |
| Courts | court | 7 |

## Canada

**609 of 636** Canadian rows (95.8%) got a StatCan id (`ca:csd` / `ca:cd` / `ca:pr`); the rest mint `rtr:ca:`.

## Minted and unknown

- **320** distinct minted `rtr:` governments over 574 rows.
- **285** rows with nothing at all (`rtr:unknown:<host>`).
- **340** rows tier `unresolved` — a real government name with no state and nothing to key it by. Listed in `unresolved.csv` for a `tenant_overrides.csv` pin; deliberately NOT minted, because an id nobody can key looks resolved and is not.
- **24** rows resolved by same-tenant consistency (tier `inferred`).

