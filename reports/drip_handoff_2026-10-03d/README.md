# Drip handoff, part d: 468 YouTube leads from Find Meeting chunks 2 and 3 (2026-10-03)

These come from two finished Find Meeting runs (rtr-findmeeting `big_job/run_govs_02` and `run_govs_03`, 7,076 governments),
routed by the `apply` step and then by hand rules Ryan accepted on 2026-10-03. No YouTube request was made.

Every government here was checked first: it has no Archive page under 2 years old (Archive inventory export of 2026-10-03,
11:06), and the address is not already on the drip list (rtr-business `research/youtube_channel_leads.csv`), in the Archive,
the queue, the queue history or the fail file. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as parts b and c.

| Lane | Kind | Count of 468 |
|---|---|---|
| youtube | channel | 268 |
| youtube | playlist | 22 |
| youtube | single_video | 178 |

Where the rows come from:

| Source | Count of 468 |
|---|---|
| The government's own route is a YouTube lead | 228 |
| Added alongside a Find Video route (a meeting page with no video) | 139 |
| Added alongside a tier 1, tier 3 or other route, or a route held for a person | 42 |
| Rule 1b: one channel found for 59 West Virginia towns | 59 |

## Cautions

- **The 59 West Virginia rows share one channel** (`UCW84nM-EAuCsIO7jHRtnOwg`). It was found on the state portal pages
  (local.wv.gov, wv.gov/local) that host these towns' sites, so it is probably the State of West Virginia's channel.
  Ryan's rule adds it for each town. Read it once; if it has no town meetings, record that for all 59.
- Addresses seen for governments in two or more states, the known template list (bqLUp7GuUTg, dewi11Channel, Wix),
  and 29 obvious off-mission or other-body channels (betting, FBI, DIRECTV, county or state channels on a town) were left out.

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
