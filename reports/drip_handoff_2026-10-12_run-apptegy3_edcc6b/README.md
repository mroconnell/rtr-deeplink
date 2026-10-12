# Drip handoff 2026-10-12_run-apptegy3_edcc6b: 3 leads from rtr-findmeeting run run_apptegy3

These come from the Find Meeting run `run_apptegy3` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 3 |
|---|---|---|
| youtube | channel | 3 |

## Why each lead was suggested (2 of 3 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Grand Ridge Community Consolidated School District 95, Illinois (us:sd:1717220) | https://www.youtube.com/@grgs95live8 | found on https://www.grgs95.org/live-feed/?page_no=3 |
| White River School District 47-1, South Dakota (us:sd:4678570) | https://youtube.com/@gettysburgbattlers9559?si=lv5fHFrNJiDP_ND7 | found on https://www.whiteriver.k12.sd.us/live-feed/?page_no=2 |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
