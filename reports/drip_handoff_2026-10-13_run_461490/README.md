# Drip handoff 2026-10-13_run_461490: 5 leads from rtr-findmeeting run run

These come from the Find Meeting run `run` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 5 |
|---|---|---|
| youtube | channel | 4 |
| youtube | single_video | 1 |

## Why each lead was suggested (5 of 5 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Hardin County, Iowa (us:county:19083) | https://www.youtube.com/user/HardinCountyIA | found on https://www.hardincountyia.gov/: "YouTube Official" under heading "Events"; page "Hardin County - Hardin County"; nearby: "View All Calendar Events YouTube Official" |
| Northampton School District, Massachusetts (us:sd:2508850) | https://www.youtube.com/@northamptontv | found on https://www.northamptonopenmedia.org/watch |
| Spearville Unified School District 381, Kansas (us:sd:2011820) | https://www.youtube.com/channel/UCyysvM8OADSUs1cFmyety6g | found on https://www.usd381.org/: "Subscribe on Youtube" under heading "Fair"; page "Spearville Schools, USD 381"; nearby: "USD 381 will ensure each child has the tools to meet the challenges of tomorrow. Current conditions as of 13 Oct 07:52 am CDT Fair Location: Spearville Feels like: NA° Humidity: 84 Wind: N mph 69° Tod" |
| Forest City Community School District, Iowa (us:sd:1911790) | https://www.youtube.com/watch?v=Q1LcDhDIUV8 | found on https://www.forestcity.k12.ia.us/district/achieve-family-portal |
| Maquoketa Community School District, Iowa (us:sd:1918510) | https://www.youtube.com/channel/UC7yqGDmsrIRa9sERJYmVxxg | found on https://www.maquoketaschools.org/o/maquoketa-csd/page/parent-links |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
