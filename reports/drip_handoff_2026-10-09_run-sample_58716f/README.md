# Drip handoff 2026-10-09_run-sample_58716f: 13 leads from rtr-findmeeting run run_sample

These come from the Find Meeting run `run_sample` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 13 |
|---|---|---|
| youtube | channel | 4 |
| youtube | single_video | 9 |

## Shared with a neighbouring body (1)

Ryan (2026-10-03): fine to give each neighbouring body the row.

| Government | Address | Note |
|---|---|---|
| Carrabelle city, Florida (us:place:1210725) | https://www.youtube.com/watch?v=MiH4QyJWobo | rtr-findmeeting run run_sample (2026-10-09): its meeting source has no video; 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Apalachicola city (us:place:1201625, also in Franklin County); found on https://www.mycarrabelle.com/: under heading "Quick Links"; page "City of Carrabelle, Florida - Official Website for the City of Carrabelle Florida 32322"; nearby: "Quick Links Pay Water & Sewer Bill Online Building Permit Portal Pay Building Permit Online Report a Concern Forms Code of Ordinances 2023-24 Budget Final Actual Budgets 2020 Comprehensive Plan Future" |

## Why each lead was suggested (9 of 13 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Peoria Heights village, Illinois (us:place:1759026) | https://www.youtube.com/user/PeoriaHeightsVillage?feature=mhee | found on https://www.peoriaheights.org/board-of-trustees |
| Dos Palos-Oro Loma Joint Unified School District, California (us:sd:0600033) | https://www.youtube.com/channel/UCHiqnO4HR4Fy32g3BsyISRA/videos | found on https://www.dpol.net/apps/pages/index.jsp?uREC_ID=1556567&type=d&pREC_ID=1742491 |
| Hanover-Horton Schools, Michigan (us:sd:2617640) | https://www.youtube.com/watch?v=8ki657oybpE | found on https://www.hanoverhorton.org/: embed title "Hanover Horton Schools November 2023" under heading "Welcome Video"; page "Hanover Horton Schools"; nearby: "Back to School Resources 2026-27 School Calendar Supply Lists Daily Schedule School Meals & Summer EBT FAQs Summer EBT Funds Application Portal Welcome Video" |
| Carrabelle city, Florida (us:place:1210725) | https://www.youtube.com/watch?v=MiH4QyJWobo | found on https://www.mycarrabelle.com/: under heading "Quick Links"; page "City of Carrabelle, Florida - Official Website for the City of Carrabelle Florida 32322"; nearby: "Quick Links Pay Water & Sewer Bill Online Building Permit Portal Pay Building Permit Online Report a Concern Forms Code of Ordinances 2023-24 Budget Final Actual Budgets 2020 Comprehensive Plan Future" |
| North Thurston Public Schools, Washington (us:sd:5305850) | https://www.youtube.com/watch?v=SD9HvY_g-TI | found on https://www.ntps.org/about/school-board/community-conversations: embed title "A YouTube video" under heading "Attend Today, Achieve Tomorrow - March 19, 2024"; page "Community Conversations - North Thurston Public Schools / Lacey, Washington"; nearby: "This Community Conversation was aligned with NTPS Strategic Plan Goal 2–Responsible, Resilient, Empowered Learners, Outcome b, Increased percentage of regular school attendees, focusing on attendance."; flagged (Jev moment 4: unsure): Jev could not tell whether the videos shown with it on the government's page are meetings |
| Marlette city, Michigan (us:place:2651820) | https://www.youtube.com/@CityofMarletteYouTube | found on https://www.cityofmarlette.gov/: "YouTube"; page "City of Marlette" |
| Slate Valley Unified Union School District 62, Vermont (us:sd:5000440) | https://youtube.com/shorts/GC_yC-37ixc?feature=share | found on https://www.slatevalleyunified.org/live-feed/?page_no=1 |
| Issaquah School District, Washington (us:sd:5303750) | https://www.youtube.com/@IssaquahSchools | found on https://www.isd411.org/about-us/announcements/single-announcement/~board/board-recaps/post/school-board-recap-september-24-2026-1790636044708 |
| Groton Area School District 06-6, South Dakota (us:sd:4600045) | https://www.youtube.com/live/eEWoVxHMdR4 | found on https://www.grotonarea.com/live-feed/?page_no=1 |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
