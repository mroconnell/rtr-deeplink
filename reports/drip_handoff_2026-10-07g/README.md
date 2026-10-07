# Drip handoff 2026-10-07g: 7 leads from rtr-findmeeting run run_govs_02

These come from the Find Meeting run `run_govs_02` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 7 |
|---|---|---|
| youtube | channel | 3 |
| youtube | playlist | 2 |
| youtube | single_video | 2 |

## Low-confidence rows (2): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Honaker town, Virginia (us:place:5138280) | https://www.youtube.com/@russellcountyvirginia8228 | rtr-findmeeting run run_govs_02 (2026-10-03): its meeting source has no video; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a county; suggested for Honaker town, Virginia; address also on the list under Russell County, VA (us:county:51167); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |
| Mill Creek borough, Pennsylvania (us:place:4249552) | https://www.youtube.com/@millcreektownshippa | rtr-findmeeting run run_govs_02 (2026-10-03): its meeting source has no video; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Millcreek township, Pennsylvania; suggested for Mill Creek borough, Pennsylvania; address also on the list under Millcreek township, Pennsylvania (us:cousub:4204949548); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
