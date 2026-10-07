# Drip handoff 2026-10-07b: 22 leads from rtr-findmeeting run run_AB_resume

These come from the Find Meeting run `run_AB_resume` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 22 |
|---|---|---|
| youtube | channel | 15 |
| youtube | playlist | 1 |
| youtube | single_video | 6 |

## Low-confidence rows (1): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Thomaston city, GA (us:place:1376168) | https://www.youtube.com/@T-USchools | rtr-findmeeting run run_AB_resume (2026-10-07): its meeting source has no video; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names a school district (the address is on a school district's row); suggested for Thomaston city, GA; address also on the list under Upson County School District, Georgia (us:sd:1305280); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body; found on https://cityofthomaston.com/211/Thomaston-Upson-County-Board-of-Educatio |

## Shared with a neighbouring body (1)

Ryan (2026-10-03): fine to give each neighbouring body the row.

| Government | Address | Note |
|---|---|---|
| University Heights city, IA (us:place:1979770) | https://www.youtube.com/watch?v=8GGsKvnrl4A | rtr-findmeeting run run_AB_resume (2026-10-07): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Iowa City city (us:place:1938595, also in Johnson County) |

## Why each lead was suggested (18 of 22 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Hermitage city, PA (us:place:4234064) | https://www.youtube.com/playlist?list=PLo9VcFaBuTuhGFHXI8ucthlTqVVRvXOZJ | found on https://hermitage.net/: embed title "Discover Hermitage Video Feed" under heading "Reminder: Our Online Bill Pay Has Moved!"; page "Hermitage, PA / Official Website" |
| Moose Lake city, MN (us:place:2743954) | https://www.youtube.com/channel/UC-zjI-TRr5IlZMdTmZ-vFIA | found on https://cityofmooselake.gov/220/Public-Access-Television |
| Camanche city, IA (us:place:1910135) | https://www.youtube.com/channel/UCEmLFxC3S-jz-ab-5n6DfNw | found on https://www.camancheia.org/27/Government |
| North Platte city, NE (us:place:3135000) | https://www.youtube.com/channel/UCC8LPJOuQr6A3atE9Wr1bBg/featured | found on https://northplattene.gov/353/Local-Media-Internet |
| North Platte city, NE (us:place:3135000) | https://www.youtube.com/@NTVNews | found on https://nebraska.tv/watch |
| Thomaston city, GA (us:place:1376168) | https://www.youtube.com/@T-USchools | found on https://cityofthomaston.com/211/Thomaston-Upson-County-Board-of-Educatio |
| Chesterton town, IN (us:place:1812412) | http://youtube.com/@TownofChesterton | found on https://chestertonin.org/204/Plan-Commission |
| Wayne city, NE (us:place:3151840) | https://www.youtube.com/watch?v=lGdw8Lrb2GA | found on https://cityofwayne.org/598/Wayne-Works-Video |
| Williston city, FL (us:place:1277825) | https://www.youtube.com/channel/UCKt1468kcNjBS2AYgOaBsRQ | found on https://www.willistonfl.org/: under heading "Home Page"; page "Home Page / Williston, FL" |
| Le Sueur city, MN (us:place:2736746) | https://www.youtube.com/channel/UC7J4O2D9wTvasMx2Hspqovw | found on https://cityoflesueur.com/217/City-Council |
| Roanoke city, VA (us:place:5168000) | https://www.youtube.com/channel/UCSxtU27c3Levk1e-uIasfvw?view_as=subscriber | found on https://www.roanokeva.gov/989 |
| Roanoke city, VA (us:place:5168000) | https://www.youtube.com/@cityofroanoke4841 | found on https://www.roanokeva.gov/1112/Watch-City-Council-Meetings |
| Roanoke city, VA (us:place:5168000) | https://www.youtube.com/@RoanokeValleyTV/videos | found on https://www.roanokeva.gov/1112/Watch-City-Council-Meetings |
| Center Line city, MI (us:place:2614320) | https://www.youtube.com/@CITYOFCENTERLINE/videos | found on https://www.centerline.gov/251/5873/City-Council |
| Port Royal town, SC (us:place:4558030) | https://www.youtube.com/@townofportroyal6217/streams | found on https://portroyal.org/Calendar.aspx?EID=995 |
| Fairbury city, NE (us:place:3116410) | https://www.youtube.com/watch?v=sIHNyUCgo-g | found on https://fairburyne.org/: under heading "EMERGENCY ALERTS"; page "Fairbury, NE / Official Website" |
| San Angelo city, TX (us:place:4864472) | https://www.youtube.com/@CityofSanAngelo | found on https://www.sanangelo.gov/507/Civil-Service-Commission |
| Gallatin city, TN (us:place:4728540) | https://www.youtube.com/c/CityofGallatin | found on https://gallatintn.gov/: "YouTube (opens in new window)" under heading "Connect with City Government"; page "Gallatin, TN / Official Website" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
