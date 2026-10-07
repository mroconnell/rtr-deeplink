# Drip handoff 2026-10-07f: 67 leads from rtr-findmeeting run run_govs_01

These come from the Find Meeting run `run_govs_01` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 67 |
|---|---|---|
| youtube | channel | 62 |
| youtube | playlist | 1 |
| youtube | single_video | 4 |

## Low-confidence rows (3): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Algona city, Iowa (us:place:1901135) | https://www.youtube.com/@AHSBroadcasting/videos | rtr-findmeeting run run_govs_01 (2026-10-03): its meeting source has no video; 44 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Algona city, Iowa; address also on the list under Algona Community School District, Iowa (us:sd:1903360); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |
| Bangor Township, Michigan (us:cousub:2615905160) | https://www.youtube.com/@vanburencountymi2620 | rtr-findmeeting run run_govs_01 (2026-10-03): its meeting source has no video; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a county; suggested for Bangor Township, Michigan; address also on the list under Waverly Township, Michigan (us:cousub:2615984820); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |
| North Plainfield borough, New Jersey (us:place:3453280) | https://www.youtube.com/@NorthPlainfieldSchools | rtr-findmeeting run run_govs_01 (2026-10-03): 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for North Plainfield borough, New Jersey; address also on the list under North Plainfield Borough School District, New Jersey (us:sd:3411640); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |

## Shared with a neighbouring body (2)

Ryan (2026-10-03): fine to give each neighbouring body the row.

| Government | Address | Note |
|---|---|---|
| Bangor Township, Michigan (us:cousub:2615905160) | https://www.youtube.com/channel/UCA-YlUJPurcVKPj6xTaoePg | rtr-findmeeting run run_govs_01 (2026-10-03): its meeting source has no video; 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Waverly Township (us:cousub:2615984820, also in Van Buren County) |
| Murphysboro city, Illinois (us:place:1751453) | https://www.youtube.com/channel/UC9TXvTlEhzY540afQr8nmUw | rtr-findmeeting run run_govs_01 (2026-10-03): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Murphysboro township (us:cousub:1707751466, also in Jackson County) |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
