# Drip handoff 2026-10-06f: 5 leads from rtr-findmeeting run run_overnight2

These come from the Find Meeting run `run_overnight2` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
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

## Why each lead was suggested (5 of 5 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Port of Seattle, Washington (rtr:us:wa:port-of-seattle) | https://www.youtube.com/user/PortofSeattle | found on https://www.portseattle.org/: "Watch Port of Seattle Videos on YouTube" under heading "Environment"; page "Home / Port of Seattle"; nearby: "Watch Port of Seattle Videos on YouTube" |
| State of Michigan, Michigan (us:state:26) | https://www.youtube.com/channel/UCH8SLxXSIBjCwptObzo5ZGg | found on https://www.michigan.gov/sos/elections/bsc |
| Saint-Rémi, Quebec (ca:csd:2468055) | https://youtu.be/iSWp70BFOYY | found on https://www.saint-remi.ca/ville/vie-municipale/seances-du-conseil |
| Squamish-Lillooet, British Columbia (ca:cd:5931) | https://www.youtube.com/channel/UCApJtgiPU9kq2mxkKfHrTYA | found on https://www.slrd.bc.ca/inside-slrd/meetings-agendas/watch-meetings |
| Saint-Étienne-des-Grès, Quebec (ca:csd:2451090) | https://www.youtube.com/watch?v=RT-ByorJjHI | found on https://mun-stedg.qc.ca/calendrier-des-seances-ordinaires-et-proces-verbaux/ |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
