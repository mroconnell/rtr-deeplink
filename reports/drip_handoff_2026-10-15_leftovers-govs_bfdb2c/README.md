# Drip handoff 2026-10-15_leftovers-govs_bfdb2c: 4 leads from rtr-findmeeting run leftovers_govs

These come from the Find Meeting run `leftovers_govs` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 4 |
|---|---|---|
| youtube | playlist | 1 |
| youtube | single_video | 3 |

## Why each lead was suggested (4 of 4 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Vernon township, Illinois (us:cousub:1709777668) | https://www.youtube.com/watch?v=9jp3Vq6BNU4 | found on https://vernontownship.com/286/Mental-Health-Board |
| Carlton city, Oregon (us:place:4111150) | https://www.youtube.com/watch?v=bdlwDfs6S9E&list=PL-UyxX1_KpXYiUNHmcuAhDjNlH7OhyoE5&index=57 | found on https://www.ci.carlton.or.us/meetings/recent?boards-commissions=98&combine=&department=All&field_smart_date_end_value=&field_smart_date_value_1= |
| New Castle town, Colorado (us:place:0853395) | https://www.youtube.com/watch?v=1SrJuyBWfw4 | found on https://www.newcastlecolorado.org/bc/page/climate-and-environment-commission |
| Mountain View town, Colorado (us:place:0852350) | https://youtu.be/3zE6MW3GT6Q | found on https://www.tomv.org/meetings/recent |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
