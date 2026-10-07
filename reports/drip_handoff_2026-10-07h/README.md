# Drip handoff 2026-10-07h: 2 leads from rtr-findmeeting run run

These come from the Find Meeting run `run` (rtr-findmeeting `apply`). That run folder is the CivicPlus platform-dispatch pilot
(`data/pilot_civicplus_2026-10-06/run`), so the notes say "run run". For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 2 |
|---|---|---|
| youtube | channel | 2 |

## Why each lead was suggested (2 of 2 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Braidwood city, Illinois (us:place:1707770) | https://www.youtube.com/@CityofBraidwood-u1d | found on https://www.braidwood.gov/Calendar.aspx?EID=408 |
| Bee County, Texas (us:county:48025) | https://www.youtube.com/@BeeCounty/streams | found on https://beecounty.gov/169/Commissioners-Court |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
