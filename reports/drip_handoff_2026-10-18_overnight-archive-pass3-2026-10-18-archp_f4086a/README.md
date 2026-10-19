# Drip handoff 2026-10-18_overnight-archive-pass3-2026-10-18-archp_f4086a: 3 leads from rtr-findmeeting run overnight_archive_pass3_2026-10-18_archpass3

These come from the Find Meeting run `overnight_archive_pass3_2026-10-18_archpass3` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 3 |
|---|---|---|
| youtube | channel | 2 |
| youtube | single_video | 1 |

## Why each lead was suggested (3 of 3 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Waubonsee Community College, Illinois (rtr:us:il:waubonsee-community-college) | https://www.youtube.com/user/waubonsee | found on https://www.waubonsee.edu/: "Youtube" under heading "Get Started"; page "Homepage / Waubonsee Community College"; nearby: "Facebook Instagram TikTok Snapchat LinkedIn Twitter Youtube Flickr" |
| Cannon Beach city, Oregon (us:place:4110850) | https://www.youtube.com/channel/UC5FP-JQFUMYyMrUS1oLwRrA/live | found on https://www.ci.cannon-beach.or.us/citycouncil |
| Sea Isle City School District, New Jersey (us:sd:3414760) | https://www.youtube.com/watch?v=CT1-LZwWWZg | found on http://www.sea-isle-city.nj.us/: "CLICK HERE"; page "Sea Isle City, New Jersey > Home"; nearby: "VETERANS DAY TRIBUTE VIDEO: Due to COVID-19, Sea Isle City's traditional Veterans Day Ceremony at Veterans Park was cancelled. However, the City created a brief Tribute Video in honor of the men and w" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
