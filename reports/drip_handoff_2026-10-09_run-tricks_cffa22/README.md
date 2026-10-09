# Drip handoff 2026-10-09_run-tricks_cffa22: 6 leads from rtr-findmeeting run run_tricks

These come from the Find Meeting run `run_tricks` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 6 |
|---|---|---|
| youtube | channel | 2 |
| youtube | single_video | 4 |

## Why each lead was suggested (4 of 6 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Northville Public Schools, Michigan (us:sd:2625980) | https://www.youtube.com/@northvillepublicschoolsvideo/streams | found on https://www.northvilleschools.org/fs/pages/897 |
| Sheffield-Sheffield Lake City School District, Ohio (us:sd:3904476) | https://www.youtube.com/channel/UCo5z7UcvBFCbr9_1I2kJ-kQ | found on https://www.sheffieldschools.org/for-families/cardinal-community-tv: "Subscribe" under heading "Image"; page "Cardinal Community TV - Sheffield-Sheffield Lake City Schools"; nearby: "Cardinal Community TV Streaming is the proud service of the District Video Club. Click the images below to get connected to our events through social media! Follow us on Twitter @cardcommunitytv Tryin" |
| Sharon Hill borough, Pennsylvania (us:place:4269752) | https://www.youtube.com/watch?v=3p-UnjCNpXM | found on https://sharonhillboro.com/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |
| Cedarburg city, Wisconsin (us:place:5513375) | https://www.youtube.com/watch?v=HllFFrAqUAw | found on https://www.cityofcedarburg.wi.gov/: "A Cedarburg Christmas" under heading "Come See What Cedarburg Has to Offer"; page "Cedarburg, WI / Official Website"; nearby: "A Cedarburg Christmas"; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
