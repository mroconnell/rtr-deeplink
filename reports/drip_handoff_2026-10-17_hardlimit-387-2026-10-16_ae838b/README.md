# Drip handoff 2026-10-17_hardlimit-387-2026-10-16_ae838b: 9 leads from rtr-findmeeting run hardlimit_387_2026-10-16

These come from the Find Meeting run `hardlimit_387_2026-10-16` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
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
| Moraine Valley Community College, Illinois (rtr:us:il:moraine-valley-community-college) | https://www.youtube.com/user/MoraineValleyCC | found on https://www.morainevalley.edu/: "YouTube" under heading "We’re here to help you succeed."; page "Moraine Valley Community College - Degrees & Certificates in Palos Hills, IL - Moraine Valley Commu…"; nearby: "Instagram Facebook LinkedIn YouTube tiktok" |
| Allen Park city, Michigan (us:place:2601380) | https://youtu.be/1bGySWzR9AQ | found on https://www.cityofallenpark.org/government/agenda_and_minutes/allen_park_michigan_city_council.php |
| Kennett Square borough, Pennsylvania (us:place:4239352) | https://youtu.be/E0uQ2evr61s | found on https://www.kennettsq.org/government/borough_documents.php |
| Monmouth city, Oregon (us:place:4149550) | https://www.youtube.com/channel/UCsjsOG_2-C3QrBdts9qi85w | found on https://www.ci.monmouth.or.us/pview.aspx?id=4759&catid=551 |
| Itasca Fire Protection District 1, Illinois (rtr:us:il:itasca-fire-protection-district-1) | https://youtube.com/@itascafpd166?si=3xWqR4yDbAyerubK | found on https://itascafd.org/: "YouTube"; page "Itasca Fire Protection District, IL"; nearby: "Nextdoor facebook instagram YouTube" |
| Quincy School District 172, Illinois (us:sd:1733000) | https://www.youtube.com/watch?v=H1_O4uhVosY | found on https://www.qps.org/schools/qhs/live-streams/: "NEW STUDENT ORIENTATION LIVE STREAM LINK" under heading "NEW STUDENT ORIENTATION LIVE STREAM LINK THURSDAY, AUGUST 3RD, 2023-6:00PM-QHS CAFETERIA"; page "LIVE STREAMS / Quincy Public Schools"; nearby: "NEW STUDENT ORIENTATION LIVE STREAM LINK" |
| Jacksonville city, Illinois (us:place:1738115) | https://www.youtube.com/watch?v=QfVuAHZJDPk | found on https://jacksonvilleil.gov/government/agendas___minutes/../city_council/agendas___minutes.php |
| Chireno Independent School District, Texas (us:sd:4813980) | https://youtu.be/J0MIkrrf77w | found on https://www.chirenoisd.org/live-feed/?page_no=43 |
| Northern Lebanon School District, Pennsylvania (us:sd:4217640) | https://youtube.com/live/exgdaC2Jfhw?feature=share | found on https://www.norleb.org/school-board/board-meetings: "https://youtube.com/live/exgdaC2Jfhw?feature=share"; page "Board Meetings - Northern Lebanon School District"; nearby: "https://youtube.com/live/exgdaC2Jfhw?feature=share" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
