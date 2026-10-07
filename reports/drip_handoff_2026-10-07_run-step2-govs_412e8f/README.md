# Drip handoff 2026-10-07_run-step2-govs_412e8f: 10 leads from rtr-findmeeting run run_step2_govs

These come from the Find Meeting run `run_step2_govs` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 10 |
|---|---|---|
| youtube | channel | 8 |
| youtube | single_video | 2 |

## Low-confidence rows (4): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Shelby County, AL (us:county:01117) | https://www.youtube.com/@shelbyalschools | rtr-findmeeting run run_step2_govs (2026-10-04): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Shelby County, AL; address also on the list under Shelby County School District, Alabama (us:sd:0103030); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |
| Cumberland County, TN (us:county:47035) | https://www.youtube.com/watch?v=I2CzNqIa0_g | rtr-findmeeting run run_step2_govs (2026-10-04): its meeting source has no video; 23 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: the address is on the list under Cumberland County School District (us:sd:4700900), this county's school district; suggested for Cumberland County, TN; drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |
| Henry County, AL (us:county:01067) | https://www.youtube.com/@henrycountyschooldistrict | rtr-findmeeting run run_step2_govs (2026-10-04): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Henry County, AL; address also on the list under Henry County School District, Alabama (us:sd:0101740); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |
| Atoka County, OK (us:county:40005) | https://www.youtube.com/@CityofAtoka/streams | rtr-findmeeting run run_step2_govs (2026-10-04): its meeting source has no video; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Atoka city, Oklahoma; suggested for Atoka County, OK; address also on the list under Atoka city, Oklahoma (us:place:4003300); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
