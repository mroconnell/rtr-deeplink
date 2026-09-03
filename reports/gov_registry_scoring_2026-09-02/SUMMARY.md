# Phase 1 — gov_id registry scoring (2026-09-02)

Inputs: **5053** archived pages (`GET /internal/export/pages`, metadata only) and **876** distinct (tenant, jurisdiction) pairs from rtr-discovery's ledger. Read-only; no schema change, no production write.

## Tier distribution

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 175 (3.5%) | 23 (2.6%) |
| registry | 4013 (79.4%) | 799 (91.2%) |
| inferred | 7 (0.1%) | 2 (0.2%) |
| unverified | 235 (4.7%) | 12 (1.4%) |
| unresolved | 382 (7.6%) | 40 (4.6%) |
| blank | 241 (4.8%) | 0 (0.0%) |

**4919 of 5929** rows (83.0%) got a national id.

## Phase 1b targets — before / after

| check | Phase 1 | now | target |
| --- | --- | --- | --- |
| rows on the county table whose raw name had a municipal type word | 26 | **0** | 0 |
| `rtr:us:xx:` / `rtr:ca:xx:` ids | 624 | **0** | 0 |
| pins sourced only from `auto_derived` | 447 | **0** | 0 |

## Government types

| gov_type | rows |
| --- | --- |
| municipality | 4157 |
| county | 865 |
| other | 487 |
| township | 178 |
| school_district | 124 |
| special_district | 103 |
| state | 10 |
| court | 5 |

## Merges and splits

- **169 merges** — two or more current `/j/` hubs collapsing into one `gov_id` (345 hubs in total).
- **33 splits** — one current hub becoming several `gov_id`s.

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
- `us:place:4752006` — Nashville-Davidson, TN ← nashville|nashville-davidson-county-tn
- `us:place:2148006` — Louisville/Jefferson County, KY ← louisville|louisville-ky
- `us:place:0452930` — Paradise Valley, AZ ← paradise-valley|paradise-valley-az
- `us:county:48201` — Harris County, TX ← harris-county-tx|harris-tx
- `us:county:06073` — San Diego County, CA ← county-of-san-diego-ca|san-diego-county-ca
- `us:county:06059` — Orange County, CA ← county-of-orange|orange-county-ca

Splits:

- `/j/unknown-jurisdiction` → rtr:us:ak:unknown-jurisdiction|rtr:us:ca:unknown-jurisdiction|rtr:us:ma:unknown-jurisdiction|rtr:us:mn:unknown-jurisdiction|rtr:us:oh:unknown-jurisdiction|rtr:us:or:unknown-jurisdiction|rtr:us:tn:unknown-jurisdiction|rtr:us:tx:unknown-jurisdiction|rtr:us:ut:unknown-jurisdiction|us:place:0620956
- `/j/hollywood` → us:cousub:2701929726|us:place:1232000|us:place:4534495
- `/j/portland` → us:place:2360545|us:place:4760280|us:place:4858904
- `/j/portage` → us:place:1861092|us:place:2665560|us:place:5564100
- `/j/san-diego-ca` → rtr:us:ca:san-diego-association-of-governments|us:place:0666000
- `/j/los-angeles-ca` → rtr:us:ca:los-angeles-department-of-water-and-power|us:place:0644000
- `/j/los-angeles-county-ca` → rtr:us:ca:los-angeles-county-metropolitan-transportation-authority|us:county:06037
- `/j/fayetteville` → us:place:0523290|us:place:3722920
- `/j/college-park-md` → rtr:us:md:college-park|us:place:2418750
- `/j/horry-county-sc` → us:county:45051|us:sd:4502490
- `/j/miami` → us:county:20121|us:place:1245000
- `/j/tarrant-county-tx` → rtr:us:tx:tarrant-county-college-district|us:county:48439
- `/j/amarillo-tx` → rtr:us:tx:amarillo|us:place:4803000
- `/j/beaufort-county-sc` → us:county:45013|us:place:4507210
- `/j/indio-ca` → rtr:us:ca:coachella-valley-water-district|us:place:0636448

## Type disagreements with gov_classify.py

**419** rows where the new `gov_type` disagrees with `archive/utils/gov_classify.py`'s bucket (the classifier driving the `/state/*` headings today).

| gov_classify bucket | new gov_type | rows |
| --- | --- | --- |
| city | other | 237 |
| city | county | 54 |
| city | special_district | 47 |
| county | school_district | 29 |
| county | municipality | 17 |
| city | state | 9 |
| school | municipality | 9 |
| county | special_district | 5 |
| city | court | 5 |
| city | school_district | 5 |
| school | other | 1 |
| county | other | 1 |

## Canada

**441 of 498** Canadian rows (88.6%) got a StatCan id (`ca:csd` / `ca:cd` / `ca:pr`); the rest mint `rtr:ca:`.

## Minted and unknown

- **345** distinct minted `rtr:` governments over 588 rows.
- **241** rows with nothing at all (`rtr:unknown:<host>`).
- **422** rows tier `unresolved` — a real government name with no state and nothing to key it by. Listed in `unresolved.csv` for a `tenant_overrides.csv` pin; deliberately NOT minted, because an id nobody can key looks resolved and is not.
- **9** rows resolved by same-tenant consistency (tier `inferred`).

