# Drip handoff 2026-10-06: 1 leads from rtr-findmeeting run run

These come from the Find Meeting run `run` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 1 |
|---|---|---|
| youtube | single_video | 1 |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.

## The row is unverified (Ryan, 2026-10-06)

| Address | Government | gov_id | Where it was seen |
|---|---|---|---|
| https://www.youtube.com/watch?v=ZS3nzOMmPQE | Haymarket town, VA | us:place:5135976 | Embedded on the town's Municode meeting page "Town Council - Regular Meeting" (legacyhaymarket.teammunicode.com/bc-towncouncil/page/town-council-%E2%80%93-regular-meeting-8) |

Ryan approved this row by hand. YouTube was not read, so the channel, title, date and owner are not checked.
Please verify it is a Haymarket town VA meeting before using it. Haymarket also has an IQM2 meeting in the tier 3 queue.
