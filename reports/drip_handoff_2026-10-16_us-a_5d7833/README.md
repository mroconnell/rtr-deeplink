# Drip handoff 2026-10-16_us-a_5d7833: 7 leads from rtr-findmeeting run us_a

These come from the Find Meeting run `us_a` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 7 |
|---|---|---|
| youtube | channel | 4 |
| youtube | single_video | 3 |

## Why each lead was suggested (7 of 7 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Tarrant Regional Water District, Texas (rtr:us:tx:tarrant-regional-water-district) | https://www.youtube.com/channel/UCrsHQSCZ9NolkfA15XmjsIQ | found on https://www.trwd.com/: under heading "GET THE LATEST INFO"; page "Tarrant Regional Water District"; nearby: "© 2026 Tarrant Regional Water District" |
| Clackamas Fire District 1, Oregon (rtr:us:or:clackamas-fire-district-1) | https://www.youtube.com/channel/UCmthrwSK-A2gTUBCKa8JuaQ | found on https://clackamasfire.com/: "Youtube" under heading "Top Pages"; page "Home - Clackamas Fire District"; nearby: "Facebook-f Twitter Instagram Youtube Linkedin" |
| Lane Transit District, Oregon (rtr:us:or:lane-transit-district) | http://www.youtube.com/@lanetransitdistrict | found on https://www.ltd.org/: "YouTube" under heading "Find a Rewarding Career Here"; page "Lane Transit District"; nearby: "Facebook Instagram X LinkedIn YouTube" |
| Fort Bend County Municipal Utility District #131, Texas (rtr:us:tx:fort-bend-county-municipal-utility-district-131) | https://www.youtube.com/watch?v=61JCn5EfsUU | found on https://www.fbcmud131.com/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |
| Montgomery County Emergency Services District #10, Texas (rtr:us:tx:montgomery-county-emergency-services-district-10) | https://www.youtube.com/watch?v=9lmCSsnSoQo | found on https://www.magnoliafire.org/ |
| Rusk County Emergency Service District #1, Texas (rtr:us:tx:rusk-county-emergency-service-district-1) | https://www.youtube.com/@RuskCountyAlerts | found on https://www.ruskcountytxfire.gov/: "Social media icon for youtubeSocial media icon for youtube" under heading "Homepage of Rusk County Emergency Services District #1"; page "Homepage Rusk County Emergency Services District #1"; nearby: "Social media icon for twitter Social media icon for twitter Social media icon for youtube Social media icon for youtube Social media icon for instagram Social media icon for instagram Social media ico" |
| Medina County Emergency Services District #4, Texas (rtr:us:tx:medina-county-emergency-services-district-4) | https://www.youtube.com/watch?v=XHOmBV4js_E | found on https://medinacountyfireems.org/ |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
