# Drip handoff 2026-10-07_holds-put-through-2026-10-07_def20d: 83 leads from rtr-findmeeting run holds_put_through_2026-10-07

These come from the Find Meeting run `holds_put_through_2026-10-07` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 83 |
|---|---|---|
| vimeo | vimeo | 25 |
| youtube | channel | 24 |
| youtube | playlist | 6 |
| youtube | single_video | 28 |

## Low-confidence rows (1): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Windham, Connecticut (us:cousub:0918086790) | https://www.youtube.com/c/WindhamPublicSchools | rtr-findmeeting run run_govs_04 (2026-10-03): also routed another way; 5 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Windham, Connecticut; address also on the list under Windham School District, CT (us:sd:0905190); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |

## Why each lead was suggested (5 of 83 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Brockway Township, Michigan (us:cousub:2614710820) | https://www.youtube.com/watch?v=a7pq3eRZIhA&list=UUvA7S5vHfE4ewWgrQ0f1dUQ | found on https://stclaircounty.org/Offices/41 |
| West Nodaway County R-I School District, Missouri (us:sd:2930900) | https://www.youtube.com/channel/UCBmwzQnSoj9b6HzNmFrg_yw/ | found on https://workspace.google.com/resources/video-conferencing/ |
| Selmaville Community Consolidated School District 10, Illinois (us:sd:1735770) | https://www.youtube.com/channel/UCZanXd5Ec2T-bydMGz_b2Lw | found on https://www.isbe.net/ |
| Traver Joint Elementary School District, California (us:sd:0639600) | https://www.youtube.com/channel/UC7OlV21GxDCDUTQKb1oH-lA | found on https://tcoe.org/: "Tulare County Office of Education on YouTube"; page "TCOE / Home"; nearby: "Job Opportunities Board Agenda LCAP" |
| Salmo, British Columbia (ca:csd:5903011) | https://www.youtube.com/channel/UCyouyD3-wU1glqiOcshA87w | found on https://www.rdck.ca/EN/main/government/meetings-agendas-minutes.html |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
