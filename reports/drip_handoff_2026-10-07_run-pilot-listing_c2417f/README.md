# Drip handoff 2026-10-07_run-pilot-listing_c2417f: 5 leads from rtr-findmeeting run run_pilot_listing

These come from the Find Meeting run `run_pilot_listing` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 5 |
|---|---|---|
| youtube | channel | 4 |
| youtube | single_video | 1 |

## Why each lead was suggested (5 of 5 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Frelinghuysen Township, New Jersey (us:cousub:3404125320) | https://youtu.be/k25h6siqmKU | found on https://www.frelinghuysen-nj.us/environmental-commission |
| Morristown town, Vermont (us:cousub:5001546675) | https://www.youtube.com/channel/UCq4WCmZvUNiKUrupq14-a2g/videos | found on https://www.morristownvt.gov/community/page/meetings-agendas-minutes |
| Alexander City city, Alabama (us:place:0101132) | https://www.youtube.com/@alexandercity3892/streams | found on https://www.alexandercityal.gov/node/98 |
| Monroe City city, Missouri (us:place:2949394) | https://www.youtube.com/@Monroe63456 | found on https://www.monroecitymo.org/board-alderman/meeting/board-aldermen-meeting-8 |
| Highlands town, North Carolina (us:place:3731360) | https://www.youtube.com/@townofhighlandsboardofcomm2380/streams | found on https://www.highlandsnc.org/: "Board of Commissioners Live Stream"; page "Home Page / Highlands, North Carolina"; nearby: "Board of Commissioners Live Stream" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
