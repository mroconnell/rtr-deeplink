# Drip handoff 2026-10-16_ryan-recs-channels_5a6909: 8 leads from rtr-findmeeting run ryan_recs_channels

These come from the Find Meeting run `ryan_recs_channels` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 8 |
|---|---|---|
| youtube | channel | 8 |

## Why each lead was suggested (8 of 8 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Tarrant County Emergency Services District #1, Texas (rtr:us:tx:tarrant-county-emergency-services-district-1) | https://youtube.com/@TCESD1 | titles read 2026-10-16: board meetings of the district (Oct 13, Sep 8, Aug 11, Jul 21, Jun 11 2026) / found on https://www.tarrantesd1.org/: "youtube" under heading "Contact Us"; page "Tarrant County ESD 1"; nearby: "﻿HOURS OF OPERATION Monday - Friday 8:00 am to 5:00 pm CONTACT US" |
| Prairielands Groundwater Conservation District, Texas (rtr:us:tx:prairielands-groundwater-conservation-district) | https://www.youtube.com/user/PGCDvideo1/ | titles read 2026-10-16: board of directors meetings and public hearings, newest 2021 (the channel is stale) / found on https://www.prairielandsgcd.org/: "YouTube"; page "Home - Prairielands Groundwater Conservation District"; nearby: "Facebook X LinkedIn YouTube" |
| Jefferson Davis Parish, Louisiana (us:county:22053) | https://www.youtube.com/@JDPPoliceJury | titles read 2026-10-16: Jefferson Davis Parish Police Jury voting and committee meetings through 10/14/2026 / found on https://www.jdppj.net/meeting-live-streaming-available/ |
| Sunbury-York South, New Brunswick (rtr:ca:nb:sunbury-york-south) | https://www.youtube.com/@SYSRC23 | titles read 2026-10-16: regular, special and committee council meetings through Oct 2026 / found on https://sysrc.ca/?page_id=1473&preview=true: "YouTube Live Stream" under heading "About Council Meetings"; page "Meetings of Council / Sunbury-York South Rural Community"; nearby: "2026 08 31 Agenda YouTube Live Stream" |
| Geneva Community Unit School District 304, Illinois (us:sd:1716380) | https://www.youtube.com/@CUSD304BOE | titles read 2026-10-16: Board of Education and committee meetings through 10-13-2026 / found on https://www.geneva304.org/Meetings.aspx: "Board of Education meetings will be recorded and available on the website in the days following the meeting" under heading "Overview"; page "Meetings"; nearby: "MEETING VIDEOS: To make Board of Education meetings accessible to all members of our com |
| Edwardsville Community Unit School District 7, Illinois (us:sd:1713530) | https://www.youtube.com/@EHSBroadcasting/featured | titles read 2026-10-16: ECUSD #7 school board meetings (Oct 13, Sep 28, Sep 14, Aug 24, Aug 10 2026) beside student-run sports and morning shows (off mission, not this channel's reason) / found on https://www.ecusd7.org/board-of-education: "Watch Board Meetings" under heading "BOARD OF EDUCATION"; page "BOARD OF EDUCATION - Edwardsville Community Unit School District #7"; nearby: "Watch Board Meetings" |
| Milltown town, Indiana (us:place:1849716) | https://www.youtube.com/@townofmilltown | titles read 2026-10-16: Town of Milltown council meetings through 9/14/2026; the town's channel was linked from milltown.in.gov (Ryan: in.gov towns belong to the town) |
| Redkey town, Indiana (us:place:1863450) | https://www.youtube.com/@TownofRedkey | titles read 2026-10-16: Redkey Town Board meetings through Oct 12, 2026; linked from townofredkey.in.gov (Ryan: in.gov towns belong to the town) |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
