# Phase 1 — gov_id registry scoring (2026-09-03)

Inputs: **5053** archived pages (`GET /internal/export/pages`, metadata only) and **876** distinct (tenant, jurisdiction) pairs from rtr-discovery's ledger. Read-only; no schema change, no production write.

## Tier distribution

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 186 (3.7%) | 27 (3.1%) |
| registry | 4005 (79.3%) | 802 (91.6%) |
| inferred | 12 (0.2%) | 0 (0.0%) |
| unverified | 138 (2.7%) | 2 (0.2%) |
| unresolved | 471 (9.3%) | 45 (5.1%) |
| blank | 241 (4.8%) | 0 (0.0%) |

**4956 of 5929** rows (83.6%) got a national id.

## Phase 1b targets — before / after

| check | Phase 1 | now | target |
| --- | --- | --- | --- |
| rows on the county table whose raw name had a municipal type word | 26 | **0** | 0 |
| `rtr:us:xx:` / `rtr:ca:xx:` ids | 624 | **0** | 0 |
| pins sourced only from `auto_derived` | 447 | **0** | 0 |

## The minting gate

**17** rows carry a string that is not a government name -- a subdomain fragment, an initialism or a station callsign -- and are tier `unresolved` with the raw text kept in `evidence`, rather than minting an `rtr:` id nobody could ever look up.

| platform | rows | distinct hosts |
| --- | --- | --- |
| granicus | 14 | 14 |
| escribe | 1 | 1 |
| telvue | 1 | 1 |
| swagit | 1 | 1 |

| country | rows |
| --- | --- |
| us | 16 |
| ca | 1 |

Examples: 'City of Al', 'City, MA', 'Llbc', 'Ps C, FL', 'S Fw, MD', 'TV, NY', 'Unknown Jurisdiction'

## Pin worklist

`pin_worklist.csv` -- **395** tenant hosts with no government across 757 rows, each with a landing URL to fetch once and read the organisation name out of the header, the way `jurisdiction_overrides.csv`'s `visual_confirmed` rows were made. Ordered eScribe / Cablecast / Swagit / TelVue first -- the four whose landing page reliably names its customer. TelVue rows carry the org token from the URL path as `match_value`, because every TelVue customer shares one host and a host-level pin would be wrong for all of them.

## Government types

| gov_type | rows |
| --- | --- |
| municipality | 4219 |
| county | 847 |
| other | 476 |
| township | 164 |
| school_district | 125 |
| special_district | 83 |
| state | 10 |
| court | 5 |

## Merges and splits

- **179 merges** — two or more current `/j/` hubs collapsing into one `gov_id` (365 hubs in total).
- **28 splits** — one current hub becoming several `gov_id`s.

Largest merges:

- `us:place:0667000` — San Francisco, CA ← ccs-f|city-and-county-of-san-francisco|san-francisco-ca
- `us:county:12095` — Orange County, FL ← orange-county|orange-county-comptroller|orange-county-fl
- `us:county:06023` — Humboldt County, CA ← county-of-humboldt-ca|humboldt-county|humboldt-county-ca
- `us:place:2511000` — Cambridge, MA ← cambridge|cambridge-city-ma|cambridge-ma
- `us:place:5136648` — Herndon, VA ← herndon|herndon-va|town-of-herndon
- `us:place:0828690` — Frisco, CO ← frisco-co|town-of-frisco|town-of-frisco-co
- `us:county:53009` — Clallam County, WA ← clallam|clallam-county-wa|clallam-wa
- `us:place:1245000` — Miami, FL ← miami|miami-fl
- `us:place:3755000` — Raleigh, NC ← raleigh|raleigh-nc
- `us:place:5553000` — Milwaukee, WI ← milwaukee|milwaukee-wi
- `us:place:4752006` — Nashville-Davidson, TN ← nashville|nashville-davidson-county-tn
- `us:place:2148006` — Louisville/Jefferson County, KY ← louisville|louisville-ky
- `us:place:0452930` — Paradise Valley, AZ ← paradise-valley|paradise-valley-az
- `us:county:48201` — Harris County, TX ← harris-county-tx|harris-tx
- `us:county:06073` — San Diego County, CA ← county-of-san-diego-ca|san-diego-county-ca

Splits:

- `/j/unknown-jurisdiction` → us:place:0620956|us:place:0655380|us:place:4852356|us:place:4967440|us:sd:4838730
- `/j/portland` → us:place:2360545|us:place:4760280|us:place:4858904
- `/j/portage` → us:place:1861092|us:place:2665560|us:place:5564100
- `/j/san-diego-ca` → rtr:us:ca:san-diego-association-of-governments|us:place:0666000
- `/j/los-angeles-ca` → rtr:us:ca:los-angeles-department-of-water-and-power|us:place:0644000
- `/j/los-angeles-county-ca` → rtr:us:ca:los-angeles-county-metropolitan-transportation-authority|us:county:06037
- `/j/fayetteville` → us:place:0523290|us:place:3722920
- `/j/hollywood` → us:place:1232000|us:place:4534495
- `/j/horry-county-sc` → us:county:45051|us:sd:4502490
- `/j/miami` → us:county:20121|us:place:1245000
- `/j/tarrant-county-tx` → rtr:us:tx:tarrant-county-college-district|us:county:48439
- `/j/amarillo-tx` → rtr:us:tx:amarillo|us:place:4803000
- `/j/beaufort-county-sc` → us:county:45013|us:place:4507210
- `/j/indio-ca` → rtr:us:ca:coachella-valley-water-district|us:place:0636448
- `/j/victoria` → ca:csd:5917034|us:place:2767036

## What the /state/* headings will read

From `gov_type` via `archive/utils/gov_groups.py`, which replaced `archive/utils/gov_classify.py`'s regex over the display name (WO-99). Every row is a page, not a distinct government.

| heading | gov_type | rows |
| --- | --- | --- |
| Cities & towns | municipality | 4219 |
| Counties & regions | county | 847 |
| Other public bodies | other | 476 |
| Cities & towns | township | 164 |
| School districts | school_district | 125 |
| Agencies & special districts | special_district | 83 |
| State government | state | 10 |
| Courts | court | 5 |

## Canada

**471 of 497** Canadian rows (94.8%) got a StatCan id (`ca:csd` / `ca:cd` / `ca:pr`); the rest mint `rtr:ca:`.

## Minted and unknown

- **269** distinct minted `rtr:` governments over 457 rows.
- **241** rows with nothing at all (`rtr:unknown:<host>`).
- **516** rows tier `unresolved` — a real government name with no state and nothing to key it by. Listed in `unresolved.csv` for a `tenant_overrides.csv` pin; deliberately NOT minted, because an id nobody can key looks resolved and is not.
- **12** rows resolved by same-tenant consistency (tier `inferred`).

