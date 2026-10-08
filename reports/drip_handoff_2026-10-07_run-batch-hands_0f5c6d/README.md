# Drip handoff 2026-10-07_run-batch-hands_0f5c6d: 5 leads from rtr-findmeeting run run_batch_hands

These come from the Find Meeting run `run_batch_hands` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 5 |
|---|---|---|
| youtube | channel | 3 |
| youtube | single_video | 2 |

## Low-confidence rows (1): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Batavia town, New York (us:cousub:3603704726) | https://www.youtube.com/@geneseecountynygovernment8122 | rtr-findmeeting run run_batch_hands (2026-10-08): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a county; suggested for Batavia town, New York; address also on the list under Genesee County, New York (us:county:36037); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body; found on https://www.geneseeny.gov/Department-Content/Legislature |

## Why each lead was suggested (5 of 5 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Lycoming County, Pennsylvania (us:county:42081) | https://www.youtube.com/@LycomingCountyGovernment/streams | found on https://lycomingcountypa.gov/government/commissioners/draft_agendas_minutes.php |
| Iron County, Michigan (us:county:26071) | https://www.youtube.com/watch?v=FkQuawiGWUw | found on https://ironmi.com/band-camp-videos |
| Batavia town, New York (us:cousub:3603704726) | https://www.youtube.com/@geneseecountynygovernment8122 | found on https://www.geneseeny.gov/Department-Content/Legislature |
| Dunkirk City School District, New York (us:sd:3609420) | https://www.youtube.com/user/advancedplacement | found on https://www.dunkirkcsd.org/departments/guidance/ap-college-board |
| Wayne Lakes village, Ohio (us:place:3982348) | https://youtu.be/PrrIKUDidfg | found on https://villageofwaynelakes.dreamhosters.com/2026-council-meetings-recorded/ |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
