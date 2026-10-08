# Drip handoff 2026-10-08_run-retry_7ba3f5: 10 leads from rtr-findmeeting run run_retry

These come from the Find Meeting run `run_retry` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 10 |
|---|---|---|
| youtube | channel | 7 |
| youtube | single_video | 3 |

## Why each lead was suggested (9 of 10 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| ,  (us:place:1236475) | https://www.youtube.com/watch?v=BLCN0JiDeqo | found on https://agenda.keystoneheights.us/ |
| ,  (us:county:19171) | https://www.youtube.com/@Tama-County-Iowa | found on https://tamacounty.iowa.gov/supervisors/meetings/ |
| ,  (us:sd:1601830) | https://www.youtube.com/@MathTV | found on https://www.mathtv.com/ |
| ,  (us:sd:0403420) | https://www.youtube.com/user/glendaleelementary | found on https://www.gesd40.org/: "YouTube(opens in new window/tab)"; page "Glendale Elementary School District / GESD 40"; nearby: "YouTube (opens in new window/tab)" |
| ,  (us:sd:3408700) | https://www.youtube.com/@lehsdlive | found on https://www.lehsd.org/board-of-education/board-meeting-agendas-minutes: "lehsd youtube channel" under heading "Board Meeting Agendas & Minutes"; page "Board Meeting Agendas & Minutes - Little Egg Harbor School District"; nearby: "lehsd youtube channel" |
| ,  (us:sd:3611250) | https://www.youtube.com/channel/UC45CaEoDRPkVSbizG3h2mnw | found on https://www.forestville.com/athletics/streaming-live-athletic-events |
| ,  (us:sd:3611250) | https://www.youtube.com/channel/UCsVZzF-XAJ1yACA71OiLd8g/videos?view=57 | found on https://www.forestville.com/athletics/streaming-live-athletic-events |
| ,  (us:place:4212536) | http://www.youtube.com/user/CompleteCommunities?feature=watch | found on https://www.completecommunitiesde.org/community-design-tools/videos/ |
| ,  (us:sd:0504380) | https://youtu.be/Pfl5LmQ4Aa4 | found on https://www.csdar.org/live-feed/?page_no=19 |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
