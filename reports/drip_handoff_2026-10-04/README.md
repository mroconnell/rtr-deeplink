# Drip handoff 2026-10-04: 180 leads from rtr-findmeeting run run_step2_govs

These come from the Find Meeting run `run_step2_govs` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 180 |
|---|---|---|
| youtube | channel | 121 |
| youtube | playlist | 6 |
| youtube | single_video | 53 |

## Low-confidence rows (8): please verify identity first

The handle names another body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Vermilion County, IL (us:county:17183) | https://www.youtube.com/@vermilioncountylocalgovern5949 | rtr-findmeeting run run_step2_govs (2026-10-04): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Vermilion village, Illinois; suggested for Vermilion County, IL; address also on the list under Vermilion village, Illinois (us:place:1777551); drip judge please verify identity |
| Anderson County, TN (us:county:47001) | https://www.youtube.com/channel/UCYTQlugIspG8XzzmUdcCtKQ/featured?view_as=subscriber | rtr-findmeeting run run_step2_govs (2026-10-04): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: the address is on the list under Anderson County School District (us:sd:4700090), this county's school district; suggested for Anderson County, TN; drip judge please verify identity |
| Shelby County, AL (us:county:01117) | https://www.youtube.com/@shelbyalschools | rtr-findmeeting run run_step2_govs (2026-10-04): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Shelby County, AL; address also on the list under Shelby County School District, Alabama (us:sd:0103030); drip judge please verify identity |
| Mason County, WV (us:county:54053) | https://www.youtube.com/channel/UCEQshYGKXF35ZeDz0jQ92_w | rtr-findmeeting run run_step2_govs (2026-10-04): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: the address is on the list under Mason County School District (us:sd:5400780), this county's school district; suggested for Mason County, WV; drip judge please verify identity |
| Henry County, AL (us:county:01067) | https://www.youtube.com/@henrycountyschooldistrict | rtr-findmeeting run run_step2_govs (2026-10-04): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Henry County, AL; address also on the list under Henry County School District, Alabama (us:sd:0101740); drip judge please verify identity |
| Atoka County, OK (us:county:40005) | https://www.youtube.com/@CityofAtoka/streams | rtr-findmeeting run run_step2_govs (2026-10-04): its meeting source has no video; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Atoka city, Oklahoma; suggested for Atoka County, OK; address also on the list under Atoka city, Oklahoma (us:place:4003300); drip judge please verify identity |
| Wabash County, IN (us:county:18169) | https://www.youtube.com/@GovBraun | rtr-findmeeting run run_step2_govs (2026-10-04): 5 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: low confidence: the Indiana governor's channel, reached through the in.gov portal; passed as low confidence as for the Indiana towns of chunks 2-3; drip judge please verify identity |
| Crawford County, IN (us:county:18025) | https://youtube.com/@GovBraun | rtr-findmeeting run run_step2_govs (2026-10-04): 7 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; hand decision: low confidence: the Indiana governor's channel, reached through the in.gov portal; passed as low confidence as for the Indiana towns of chunks 2-3; drip judge please verify identity |

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
