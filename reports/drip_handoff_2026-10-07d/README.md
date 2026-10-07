# Drip handoff 2026-10-07d: 3 leads from rtr-findmeeting run run_govs_untested_timeouts

These come from the Find Meeting run `run_govs_untested_timeouts` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 3 |
|---|---|---|
| youtube | single_video | 3 |

## Why each lead was suggested (3 of 3 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Gananda Central School District, New York (us:sd:3611740) | https://youtu.be/ni_Lhgbw3D0?si=nRJ-TcjYAmnLnu_A | found on https://www.gananda.org/apps/pages/index.jsp?uREC_ID=1035632&type=d&pREC_ID=2529222: "slide show video" under heading "New Bus Garage Proposal"; page "New Bus Garage Proposal – District – Gananda Central School District"; nearby: "New: Watch a slide show video or the slide show itself ( here ) with Dr. Van Scoy to learn more details about the project." |
| Little Axe Public Schools, Oklahoma (us:sd:4017880) | https://www.youtube.com/watch?time_continue=7&v=z3oAlipI-3A | found on https://www.littleaxeps.org/live-feed/?page_no=14 |
| Parkston School District 33-3, South Dakota (us:sd:4654300) | https://www.youtube.com/watch?v=rTUK__2LpLg | found on https://www.parkston.k12.sd.us/live-feed/?page_no=82 |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
