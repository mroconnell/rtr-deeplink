# Drip handoff 2026-10-07b: 25 leads from rtr-findmeeting run run_wordpress

These come from the Find Meeting run `run_wordpress` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 25 |
|---|---|---|
| youtube | channel | 14 |
| youtube | playlist | 1 |
| youtube | single_video | 10 |

## Shared with a neighbouring body (2)

Ryan (2026-10-03): fine to give each neighbouring body the row.

| Government | Address | Note |
|---|---|---|
| Washington Grove town, Maryland (us:place:2481675) | https://www.youtube.com/@MontgomeryMunicipalCable/search?query=%22washington%20grove%22 | rtr-findmeeting run run_wordpress (2026-10-07): its meeting source has no video; 15 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Garrett Park town (us:place:2431525, also in Montgomery County); found on https://washingtongrovemd.gov/about-wg/our-town/video-gallery/ |
| Golovin city, Alaska (us:place:0229180) | https://www.youtube.com/channel/UC7R_SI65b92ktfqebcxNh7g | rtr-findmeeting run run_wordpress (2026-10-07): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Diomede city (us:place:0219060, also in Nome Census Area); found on https://kawerak.org/: "YouTube"; page "Kawerak"; nearby: "Facebook Instagram YouTube" |

## Why each lead was suggested (19 of 25 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Kawawachikamach, Quebec (ca:csd:2499065) | https://www.youtube.com/channel/UCb8SeL3HZAMaqDLJdL47w0Q | found on https://naskapi.ca/: "YouTube" under heading "Language"; page "Naskapi Nation of Kawawachikamach – A unique Nation proudly working together towards autonomy, pros…"; nearby: "The Naskapi Nation of Kawawachikamach Naskapi.ca P.O. Box 5111 Kawawachikamach, QC G0G 2Z0 (418) 585-2686" |
| Humboldt, Saskatchewan (ca:csd:4715008) | https://www.youtube.com/@CityofHumboldt | found on https://humboldt.ca/: "Follow" under heading "Facebook"; page "City Of Humboldt - Strategically Located In The Heart Of Saskatchewan"; nearby: "Follow Follow Follow Follow" |
| Phelps County, Missouri (us:county:29161) | https://www.youtube.com/watch?v=PGUK36okjLE | found on http://www.phelpscounty.org/commission-meetings-via-zoom/ |
| Hertford County, North Carolina (us:county:37091) | https://www.youtube.com/@CountyofHertford | found on https://www.hertfordcountync.gov/: "Youtube"; page "Hertford County, NC"; nearby: "Facebook Youtube Twitter" |
| Ship Bottom borough, New Jersey (us:place:3467110) | https://youtu.be/VKxUpu1kp0k | found on https://shipbottom.org/: "Pedestrian Safety Video" under heading "QUICK LINKS"; page "Home - Borough of Ship Bottom"; nearby: "Pedestrian Safety Video Ocean County Fire Marshal Inspections" |
| Lavallette borough, New Jersey (us:place:3439390) | http://www.youtube.com/c/LavalletteBorough | found on https://www.lavallette.org/councilmeetings.html |
| Washington Grove town, Maryland (us:place:2481675) | https://www.youtube.com/@MontgomeryMunicipalCable/search?query=%22washington%20grove%22 | found on https://washingtongrovemd.gov/about-wg/our-town/video-gallery/ |
| Washington Grove town, Maryland (us:place:2481675) | https://www.youtube.com/@AllanJanus | found on https://washingtongrovemd.gov/about-wg/our-town/video-gallery/ |
| Harvey, New Brunswick (ca:csd:1310005) | https://www.youtube.com/channel/UCf-b9DLU-kGHk2aPFplMD2A | found on https://harveyruralcommunity.ca/document-category/council-meeting-minutes/ |
| Holden, Alberta (ca:csd:4810021) | https://www.youtube.com/channel/UCm_n9jdVno-TTIKZUAGvk2w | found on https://holden.ca/: under heading "Click hear for Virtual Tour"; page "Village of Holden / Share the charm of country living"; nearby: "Click hear for Virtual Tour click here for Video" |
| Rollinsford town, New Hampshire (us:cousub:3301765540) | https://www.youtube.com/channel/UCUcBr4OzfZRYwSxdF8w-8vA | found on https://rollinsfordnh.gov/boards-committees/select-board/ |
| Corning city, Arkansas (us:place:0515460) | https://www.youtube.com/watch?v=rm1Od9XkVN4 | found on https://corningar.gov/city-of-corning/ |
| Fort Payne city, Alabama (us:place:0127616) | https://www.youtube.com/channel/UCh2HqVpRhvnWYzyL6ad-m2A?sub_confirmation=1&feature=subscribe-embed-click | found on https://fortpayne.org/city-services/city-council-meetings/ |
| West Lebanon town, Indiana (us:place:1882934) | https://www.youtube.com/live/5drtkxSJMoc?si=Mdvgj5RLBYCmPtry | found on https://westlebanonindiana.com/meeting-minutes/; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Goodland city, Kansas (us:place:2026875) | https://www.youtube.com/c/goodlandks/live | found on https://goodlandks.gov/city-departments/information-technology-department/live-stream/view-live-stream/ |
| New Freedom borough, Pennsylvania (us:place:4253568) | https://youtu.be/s3NOSJyW28s?si=ojuWjx_BwI5VIs4l | found on https://newfreedomboro.org/2026-meeting-minutes/; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| School Administrative District 40, Maine (us:sd:2311550) | https://www.youtube.com/watch?v=ULi4QGRwFEI&list=TLPQMTUxMTIwMjQkcmRk8VgQYQ&index=2&pp=gAQBiAQB | found on https://rsu40.org/agendas-minutes/: "Link" under heading "Agendas and Minutes"; page "Agendas & Minutes / Regional School Unit 40"; nearby: "November 7, 2024 November 7, 2024 Link"; flagged (Jev moment 4: unsure): Jev could not tell whether the videos shown with it on the government's page are meetings |
| Eastern Howard School Corporation, Indiana (us:sd:1803150) | https://www.youtube.com/@EasternComets | found on https://www.eastern.k12.in.us/corp/board-meetings/: "https://www.youtube.com/@EasternComets" under heading "Board Meetings"; page "Board Meetings – Eastern Howard School Corporation"; nearby: "https://www.youtube.com/@EasternComets" |
| Golovin city, Alaska (us:place:0229180) | https://www.youtube.com/channel/UC7R_SI65b92ktfqebcxNh7g | found on https://kawerak.org/: "YouTube"; page "Kawerak"; nearby: "Facebook Instagram YouTube" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
