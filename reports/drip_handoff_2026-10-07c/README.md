# Drip handoff 2026-10-07c: 9 leads from rtr-findmeeting run run_govs_stale670

These come from the Find Meeting run `run_govs_stale670` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 9 |
|---|---|---|
| youtube | channel | 3 |
| youtube | single_video | 6 |

## Why each lead was suggested (9 of 9 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Henderson County Schools, North Carolina (us:sd:3702100) | https://www.youtube.com/live/Ok8-CN8ZJcE?si=SGN4xW_UalBCVD5S | found on https://www.hendersoncountypublicschoolsnc.org/district/administration/board-meeting-videos/; flagged (Jev moment 4: unsure): Jev could not tell whether the videos shown with it on the government's page are meetings |
| Creede School District, Colorado (us:sd:0803150) | https://www.youtube.com/watch?v=7pJ9s-J5NQA | found on https://www.creedek12.net/live-feed/?page_no=22 |
| Capay Joint Union Elementary School District, California (us:sd:0607410) | https://youtu.be/h3hQ8hK7oj4 | found on https://www.capayschool.org/live-feed/?page_no=41 |
| Harvard city, Illinois (us:place:1733331) | https://www.youtube.com/@cityofharvard1286 | found on https://www.cityofharvard.org/: "Youtube" under heading "Latest News"; page "Home Page / Harvard IL"; nearby: "Facebook Instagram X (Twitter) Youtube" |
| Hochatown town, Oklahoma (us:place:4035030) | https://www.youtube.com/channel/UC47XpIxM9mfI9V2Jr8Sy2rA | found on https://www.hochatown.gov/town-maps |
| Fowler city, California (us:place:0625436) | https://youtu.be/_n5hNFvpuec | found on https://www.fowlercity.org/meetings/recent |
| Webb town, New York (us:cousub:3604378927) | https://youtu.be/iiBCO3gDoPY | found on https://www.townofwebbny.gov/meetings/recent |
| Bolivar city, Missouri (us:place:2906976) | https://youtube.com/@cityofbolivarmissouri?si=bpm-_PkVF1nptQbD | found on https://www.bolivar.mo.us/board-alderman |
| Scio city, Oregon (us:place:4165650) | https://www.youtube.com/watch?v=_D74RXIlOl4 | found on https://www.sciooregon.gov/public-safety/page/dea-drug-take-back-event |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
