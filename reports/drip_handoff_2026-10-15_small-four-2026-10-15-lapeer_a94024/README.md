# Drip handoff 2026-10-15_small-four-2026-10-15-lapeer_a94024: 1 leads from rtr-findmeeting run small_four_2026-10-15_lapeer

These come from the Find Meeting run `small_four_2026-10-15_lapeer` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 1 |
|---|---|---|
| youtube | channel | 1 |

## Why each lead was suggested (1 of 1 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Lapeer County, Michigan (us:county:26087) | https://www.youtube.com/@countyoflapeermichigan8302/streams | Ryan's Hand Checks answer, 2026-10-15: Ryan, chat 2026-10-15: moved off Marathon Township MI; the handle names Lapeer County, Michigan |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
