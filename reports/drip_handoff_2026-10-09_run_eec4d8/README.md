# Drip handoff 2026-10-09_run_eec4d8: 10 leads from rtr-findmeeting run run

These come from the Find Meeting run `run` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
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

## Why each lead was suggested (10 of 10 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Baldwin, Ontario (ca:csd:3552028) | https://www.youtube.com/watch?v=Q5_j3JLAFh8 | found on https://baldwin.ca/wp-json/wp/v2/posts?search=meeting&per_page=10&_fields=link,title,date,content |
| Calvin, Ontario (ca:csd:3548022) | https://www.youtube.com/channel/UCMo4GLlG21lqEsZ03Re9P8Q | found on https://calvintownship.ca/en/council-and-council-business/council |
| Calvin, Ontario (ca:csd:3548022) | https://www.youtube.com/@calvintownship2718 | found on https://calvintownship.ca/en/general-information/youtube-channel |
| East Ferris, Ontario (ca:csd:3548034) | https://www.youtube.com/channel/UCR61pHieWNY_IArCfBNW0pg | found on https://eastferris.ca/en/our-community/community-events/show/council-meeting-regular-1 |
| Ignace, Ontario (ca:csd:3560001) | https://www.youtube.com/watch?v=gto2CcnEqf0 | found on https://www.ignace.ca/town-hall/strategies-and-plans/willingness-dgr-process#cecagendas |
| North Glengarry, Ontario (ca:csd:3501050) | https://www.youtube.com/channel/UCyHgS_xNDqjpiY9sMdVRL3A | found on https://www.northglengarry.ca/: "Youtube" under heading "Upcoming Events"; page "Home / Township of North Glengarry"; nearby: "Facebook Youtube Instagram LinkedIn" |
| North Glengarry, Ontario (ca:csd:3501050) | https://www.youtube.com/@townshipofnorthglengarry3419 | found on https://www.northglengarry.ca/government/council-meeting-information/ |
| Laurentian Valley, Ontario (ca:csd:3547075) | https://www.youtube.com/channel/UCMkkFax4XkheFET1AbQ6z3g | found on https://www.lvtownship.ca/lv-government-services/council/council-members/ |
| Pembroke, Ontario (ca:csd:3547064) | https://www.youtube.com/user/TheCityofPembroke?feature=watch | found on https://www.pembroke.ca/: "Council Meeting Livestream" under heading "Events"; page "Home / City of Pembroke"; nearby: "Council Meeting Livestream" |
| Tiny, Ontario (ca:csd:3543068) | https://www.youtube.com/channel/UC7Oz4SOg6TRYX1TuJ716WQQ | found on https://www.tiny.ca/: "Tiny on Youtube" under heading "Footer menu"; page "Home / Township of Tiny" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
