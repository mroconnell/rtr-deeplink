# Drip handoff 2026-10-09_run-rerun40_0b1295: 36 leads from rtr-findmeeting run run_rerun40

These come from the Find Meeting run `run_rerun40` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 36 |
|---|---|---|
| youtube | channel | 7 |
| youtube | playlist | 1 |
| youtube | single_video | 28 |

## Low-confidence rows (1): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Longueuil, Quebec (ca:cd:2458) | https://www.youtube.com/user/VilledeLongueuil | rtr-findmeeting run run_rerun40 (2026-10-09): 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Longueuil, Quebec; suggested for Longueuil, Quebec; address also on the list under Longueuil, Quebec (ca:csd:2458227); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body; found on https://longueuil.quebec/: "Ouvre dans une nouvelle fenêtre" under heading "SERVICES"; page "Accueil | Ville de Longueuil"; nearby: "Ouvre dans une nouvelle fenêtre" |

## Shared with a neighbouring body (1)

Ryan (2026-10-03): fine to give each neighbouring body the row.

| Government | Address | Note |
|---|---|---|
| Cleveland Township, Michigan (us:cousub:2608916400) | https://www.youtube.com/channel/UCNQTgIgcTedF2qB8floC1GQ | rtr-findmeeting run run_rerun40 (2026-10-09): its meeting source has no video; 402 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Suttons Bay township (us:cousub:2608977620, also in Leelanau County); found on https://leelanau.gov/: "View Meeting Video StreamsOpens in new window"; page "Leelanau County"; nearby: "View Meeting Video Streams Opens in new window" |

## Why each lead was suggested (14 of 36 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Irma, Alberta (ca:csd:4807056) | https://www.youtube.com/watch?v=GjIA5U4Raks | found on https://irma.ca/wpsite/explore-irma/irma-videos/ |
| Hyde Park town, Vermont (us:cousub:5001535050) | https://www.youtube.com/watch?v=IbIYC5HthPQ&list=PLT7pk1tW-pwuiS1vyXLKsuXxYlB0HM6st&index=5 | found on https://hydeparkvt.com/boardscommissions/selectboard/agendas_and_minutes.php |
| Cleveland Township, Michigan (us:cousub:2608916400) | https://www.youtube.com/channel/UCNQTgIgcTedF2qB8floC1GQ | found on https://leelanau.gov/: "View Meeting Video StreamsOpens in new window"; page "Leelanau County"; nearby: "View Meeting Video Streams Opens in new window" |
| Waveland city, Mississippi (us:place:2878200) | https://www.youtube.com/live/G6OeJHasd10?si=HAakreGx3O_XSxqM&t=105 | found on https://www.waveland.ms.gov/meetings/recent |
| Bardstown city, Kentucky (us:place:2103628) | https://www.youtube.com/channel/UCgLgOFab2kiQ1yPTET6rAzA | found on https://www.cityofbardstown.org/news_detail_T6_R137.php |
| Carrollton city, Georgia (us:place:1313492) | https://www.youtube.com/@CityOfCarrolltonGeorgia | found on https://carrolltonga.com/: "Livestream the Meeting" under heading "Report a Problem"; page "City of Carrollton, Georgia"; nearby: "Livestream the Meeting" |
| Longueuil, Quebec (ca:cd:2458) | https://www.youtube.com/user/VilledeLongueuil | found on https://longueuil.quebec/: "Ouvre dans une nouvelle fenêtre" under heading "SERVICES"; page "Accueil / Ville de Longueuil"; nearby: "Ouvre dans une nouvelle fenêtre" |
| South Redford School District, Michigan (us:sd:2632280) | https://www.youtube.com/channel/UCS0DogO-X30Pi11mjUtH_ng | found on https://www.southredford.org/: "Board Meeting Videos"; page "South Redford SD"; nearby: "Board Meeting Videos" |
| Meridian Community Unit School District 15, Illinois (us:sd:1700123) | https://youtu.be/E3282NeG5eY | found on https://www.meridianhawks.net/live-feed/?page_no=1 |
| Regional School Unit 78, Maine (us:sd:2314803) | https://youtu.be/YMmFKijyiME | found on https://www.rangeleyschool.org/live-feed/?page_no=16 |
| Smith Center Unified School District 237, Kansas (us:sd:2000007) | https://www.youtube.com/@SCMedia-237 | found on https://www.usd237.org/vnews/display.v/SEC/High%20School/Junior%20High%7COrganizations/Clubs%3E%3ESC%20TV: "SC Media YouTube Channel" under heading "SC TV Staff"; page "Smith Center USD 237 - SC TV Staff"; nearby: "SC Media YouTube Channel" |
| Amherst Exempted Village School District, Ohio (us:sd:3904519) | https://www.youtube.com/watch?v=d7M2ww_hbcg | found on https://www.amherstk12.org/live-feed/?page_no=1 |
| Scotland County R-I School District, Missouri (us:sd:2920700) | https://youtu.be/HVVcpdN5CEA | found on https://www.scotland.k12.mo.us/live-feed/?page_no=129 |
| Marceline R-V School District, Missouri (us:sd:2920050) | https://www.youtube.com/c/MarcelineStreaming | found on https://www.marcelineschools.org/: "Marceline School District Streaming Channel" under heading "Marceline R-V Schools"; page "Home / Marceline R-V Schools"; nearby: "Marceline School District Streaming Channel" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
