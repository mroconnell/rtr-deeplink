# Drip handoff 2026-10-11_run-rest_3b8ef6: 4 leads from rtr-findmeeting run run_rest

These come from the Find Meeting run `run_rest` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 4 |
|---|---|---|
| youtube | channel | 3 |
| youtube | single_video | 1 |

## Why each lead was suggested (4 of 4 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Anderson Community School Corporation, Indiana (us:sd:1800150) | https://www.youtube.com/@AndersonCommunitySchools | found on https://www.acsc.net/apps/pages/index.jsp?uREC_ID=619475&type=d&pREC_ID=1094399: "YouTube page" under heading "Upcoming Public Board Meeting Dates"; page "Upcoming Public Board Meeting Dates – Board – Anderson Community Schools"; nearby: "The Anderson Community Schools (ACS) Board of Trustees holds their public meetings monthly. Generally these meetings are held on the second Monday of the month and begin at 6:00 pm. They are located t" |
| Maconaquah School Corporation, Indiana (us:sd:1806090) | https://www.youtube.com/@MaconaquahStreaming | found on https://www.maconaquah.k12.in.us/apps/pages/index.jsp?uREC_ID=3791535&type=d&pREC_ID=2450634: "Streaming of Maconaquah School Board Meetings" under heading "School Board"; page "School Board – Our Corporation – Maconaquah School Corporation"; nearby: "Streaming of Maconaquah School Board Meetings" |
| Leechburg Area School District, Pennsylvania (us:sd:4213470) | https://www.youtube.com/channel/UCah22FUuPtO0G5PJS-ECzeg&sa=D&ust=1598542802743000&usg=AFQjCNF250uEEDYfL8RaHwByHGC068xkRw | found on https://www.leechburg.k12.pa.us/apps/pages/index.jsp?uREC_ID=1905058&type=d&pREC_ID=2049251: "LHS Productions: Home of the Blue Devil News" |
| Greenburgh Central School District, New York (us:sd:3612720) | https://www.youtube.com/watch?v=vDO9Qlf71PA | found on https://www.greenburghcsd.org/apps/pages/index.jsp?uREC_ID=4379587&type=d&pREC_ID=2583947: "GCSD Welcome Back Message" under heading "The Superintendent"; page "The Superintendent – About – Greenburgh Central School District" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
