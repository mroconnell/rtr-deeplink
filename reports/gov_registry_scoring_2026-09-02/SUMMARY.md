# Phase 1 — gov_id registry scoring (2026-09-02)

Inputs: **5053** archived pages (`GET /internal/export/pages`, metadata only) and **876** distinct (tenant, jurisdiction) pairs from rtr-discovery's ledger. Read-only; no schema change, no production write.

## Tier distribution

| tier | archive pages | ledger pairs |
| --- | --- | --- |
| pinned | 410 (8.1%) | 94 (10.7%) |
| registry | 3743 (74.1%) | 731 (83.4%) |
| unverified | 673 (13.3%) | 51 (5.8%) |
| blank | 227 (4.5%) | 0 (0.0%) |

**4719 of 5929** rows (79.6%) got a national id.

## Government types

| gov_type | rows |
| --- | --- |
| municipality | 3926 |
| county | 955 |
| other | 569 |
| township | 236 |
| school_district | 124 |
| special_district | 104 |
| state | 10 |
| court | 5 |

## Merges and splits

- **142 merges** — two or more current `/j/` hubs collapsing into one `gov_id` (289 hubs in total).
- **50 splits** — one current hub becoming several `gov_id`s.

Largest merges:

- `us:place:0667000` — San Francisco, CA ← ccs-f|city-and-county-of-san-francisco|san-francisco-ca
- `us:county:12095` — Orange County, FL ← orange-county|orange-county-comptroller|orange-county-fl
- `us:county:06085` — Santa Clara County, CA ← county-of-santa-clara-ca|santa-clara|santa-clara-county-ca
- `us:place:0828690` — Frisco, CO ← frisco-co|town-of-frisco|town-of-frisco-co
- `us:county:53009` — Clallam County, WA ← clallam|clallam-county-wa|clallam-wa
- `us:place:5553000` — Milwaukee, WI ← milwaukee|milwaukee-wi
- `rtr:us:tn:nashville-davidson-county` — Nashville-Davidson County, TN ← nashville|nashville-davidson-county-tn
- `rtr:us:ky:louisville` — Louisville, KY ← louisville|louisville-ky
- `us:place:0452930` — Paradise Valley, AZ ← paradise-valley|paradise-valley-az
- `us:county:48201` — Harris County, TX ← harris-county-tx|harris-tx
- `us:county:04013` — Maricopa County, AZ ← maricopa|maricopa-county-az
- `us:county:06073` — San Diego County, CA ← county-of-san-diego-ca|san-diego-county-ca
- `us:county:06059` — Orange County, CA ← county-of-orange|orange-county-ca
- `us:county:12086` — Miami-Dade County, FL ← miami-dade-county|miami-dade-county-fl
- `us:county:06065` — Riverside County, CA ← riverside|riverside-county-ca

Splits:

- `/j/unknown-jurisdiction` → rtr:us:xx:unknown-jurisdiction|us:place:0620956|us:place:4852356
- `/j/san-diego-ca` → rtr:us:ca:san-diego-association-of-governments|us:place:0666000
- `/j/los-angeles-ca` → rtr:us:ca:los-angeles-department-of-water-and-power|us:place:0644000
- `/j/los-angeles-county-ca` → rtr:us:ca:los-angeles-county-metropolitan-transportation-authority|us:county:06037
- `/j/beverly-hills` → rtr:us:xx:beverly-hills|us:place:0606308
- `/j/horry-county-sc` → us:county:45051|us:sd:4502490
- `/j/marion` → rtr:us:xx:marion|us:county:12083
- `/j/montgomery-county` → rtr:us:md:montgomery-county-planning-board|rtr:us:xx:montgomery-county
- `/j/nashville` → rtr:us:tn:nashville-davidson-county|rtr:us:tn:nashville-davidson-metropolitan-government
- `/j/miami` → rtr:us:xx:miami|us:place:1249225
- `/j/tarrant-county-tx` → rtr:us:tx:tarrant-county-college-district|us:county:48439
- `/j/lees-summit` → rtr:us:xx:lees-summit|us:place:3775000
- `/j/amarillo-tx` → rtr:us:tx:amarillo|us:place:4803000
- `/j/beaufort-county-sc` → us:county:45013|us:place:4507210
- `/j/indio-ca` → rtr:us:ca:coachella-valley-water-district|us:place:0636448

## Type disagreements with gov_classify.py

**583** rows where the new `gov_type` disagrees with `archive/utils/gov_classify.py`'s bucket (the classifier driving the `/state/*` headings today).

| gov_classify bucket | new gov_type | rows |
| --- | --- | --- |
| city | other | 330 |
| city | county | 135 |
| city | special_district | 46 |
| county | school_district | 29 |
| school | municipality | 10 |
| city | state | 9 |
| county | municipality | 8 |
| county | special_district | 5 |
| city | court | 5 |
| city | school_district | 5 |
| county | other | 1 |

## Canada

**415 of 450** Canadian rows (92.2%) got a StatCan id (`ca:csd` / `ca:cd` / `ca:pr`); the rest mint `rtr:ca:`.

## Minted and unknown

- **636** distinct minted `rtr:` governments over 1210 rows.
- **227** rows with nothing at all (`rtr:unknown:<host>`).

