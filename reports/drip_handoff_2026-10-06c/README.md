# Drip handoff 2026-10-06c: 7 leads from rtr-findmeeting run run_overnight2

These come from the Find Meeting run `run_overnight2` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 7 |
|---|---|---|
| youtube | channel | 5 |
| youtube | single_video | 2 |

## Why each lead was suggested (5 of 7 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Stormont, Dundas and Glengarry, Ontario (ca:cd:3501) | https://www.youtube.com/@SDGCounties | found on https://www.sdgcounties.ca/agendasandminutes |
| Peterborough, Ontario (ca:cd:3515) | https://www.youtube.com/@ptbo.county | found on https://www.ptbocounty.ca/: "YouTube" under heading "Apply"; page "Home / County of Peterborough"; nearby: "Facebook Instagram YouTube LinkedIn" |
| Athabasca County, Alberta (ca:csd:4813044) | https://www.youtube.com/channel/UCD96fyUTxbqI0mV0Gh0O7xA | found on https://athabascacounty.com/government/council/council-information/ |
| Frontenac, Ontario (ca:cd:3510) | https://www.youtube.com/@frontenaccounty | found on https://www.frontenaccounty.ca/: "Youtube" under heading "We’re Hiring"; page "County of Frontenac"; nearby: "Facebook Twitter LinkedIn Instagram Youtube" |
| Simcoe, Ontario (ca:cd:3543) | https://www.youtube.com/user/CountyofSimcoe | found on https://simcoe.ca/; page "Simcoe County"; nearby: "CONTACT JOBS Residents RESIDENTS Children's Services Contact Us Homelessness Housing LINX Transit Long-Term Care Newcomers Ontario Works Organics, Recycling, & Garbage Paramedic Services Roads & Const" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
