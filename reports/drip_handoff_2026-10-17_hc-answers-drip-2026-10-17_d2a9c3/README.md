# Drip handoff 2026-10-17_hc-answers-drip-2026-10-17_d2a9c3: 15 leads from rtr-findmeeting run hc_answers_drip_2026-10-17

These come from the Find Meeting run `hc_answers_drip_2026-10-17` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 15 |
|---|---|---|
| youtube | channel | 13 |
| youtube | playlist | 1 |
| youtube | single_video | 1 |

## Why each lead was suggested (15 of 15 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Meadville city, Pennsylvania (us:place:4248360) | https://www.youtube.com/watch?v=9MjoVy0Jtis | Hand Checks (Ryan, 2026-10-17, card hl-15): Ryan: the city's page links a YouTube video for each meeting; this is one of them; YouTube not fetched; NOT hand-read by us |
| Hermantown city, Minnesota (us:place:2728682) | https://www.youtube.com/@cityofhermantownminnesota4642 | Hand Checks (Ryan, 2026-10-17, card hl-21): Ryan typed the city's channel; YouTube not fetched; NOT hand-read by us |
| Meridian School District, Washington (us:sd:5305010) | https://www.youtube.com/@meridianschoolboard | Hand Checks (Ryan, 2026-10-17, card hl-23): Ryan typed the board's channel for board meeting videos; YouTube not fetched; NOT hand-read by us |
| Upper Mount Bethel township, Pennsylvania (us:cousub:4209579184) | https://www.youtube.com/@UMBT-Meetings | Hand Checks (Ryan, 2026-10-17, card ov-61): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Chattahoochee County School District, Georgia (us:sd:1301050) | https://www.youtube.com/@chattco/streams | Hand Checks (Ryan, 2026-10-17, card ov-62): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Dougherty School District, Georgia (us:sd:1301830) | https://www.youtube.com/@DocoSchools | Hand Checks (Ryan, 2026-10-17, card ov-63): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Meridian Joint School District 2, Idaho (us:sd:1602100) | https://www.youtube.com/playlist?list=PLuqhqbAZs3_a5WKu3gklsT0GNOE-WSJ8R | Hand Checks (Ryan, 2026-10-17, card ov-64): Ryan: keep this playlist specifically (West Ada board playlist), not the whole channel; YouTube not fetched; NOT hand-read by us |
| Hiawatha Unified School District 415, Kansas (us:sd:2000006) | https://www.youtube.com/@415boe4/streams | Hand Checks (Ryan, 2026-10-17, card ov-66): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Middlesex Borough School District, New Jersey (us:sd:3410050) | https://www.youtube.com/@MBOETelevision/streams | Hand Checks (Ryan, 2026-10-17, card ov-67): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Mascenic Regional School District, New Hampshire (us:sd:3304670) | https://www.youtube.com/@MRSDBoard/streams | Hand Checks (Ryan, 2026-10-17, card ov-68): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| North Providence School District, Rhode Island (us:sd:4400780) | https://www.youtube.com/@NPSDSchoolCommittee/streams | Hand Checks (Ryan, 2026-10-17, card ov-69): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Lincoln Parish School District, Louisiana (us:sd:2200990) | https://www.youtube.com/@LPSBStream | Hand Checks (Ryan, 2026-10-17, card ov-70): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Smithfield School District, Rhode Island (us:sd:4400990) | https://www.youtube.com/@SPSVideoChannel-ln8eu/streams | Hand Checks (Ryan, 2026-10-17, card ov-71): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Keene School District, New Hampshire (us:sd:3304050) | https://www.youtube.com/@SAU29YouTube/streams | Hand Checks (Ryan, 2026-10-17, card ov-72): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |
| Great Salt Bay Community School District, Maine (us:sd:2306160) | https://www.youtube.com/@GSBCougars | Hand Checks (Ryan, 2026-10-17, card ov-73): Ryan: keep the lead (the held channel the apply screen could not tie to the name); YouTube not fetched; NOT hand-read by us |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
