# Drip handoff 2026-10-05c: 11 leads from rtr-findmeeting run civicplus_combined

These come from the Find Meeting run `civicplus_combined` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 11 |
|---|---|---|
| youtube | channel | 6 |
| youtube | single_video | 5 |

## Low-confidence rows (1): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Woodbridge township, NJ (us:cousub:3402382000) | https://www.youtube.com/user/WoodbridgeTv | rtr-findmeeting run civicplus_combined (2026-10-05): its meeting source has no video; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Woodbridge township, NJ; address also on the list under Woodbridge Township School District, New Jersey (us:sd:3418120); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
