# Drip handoff 2026-10-09_run-qc_7e4c40: 15 leads from rtr-findmeeting run run_qc

These come from the Find Meeting run `run_qc` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 15 |
|---|---|---|
| youtube | channel | 2 |
| youtube | single_video | 13 |

## Why each lead was suggested (10 of 15 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Les Éboulements, Quebec (ca:csd:2416048) | https://www.youtube.com/watch?v=4II6cGJ3xx0 | found on https://leseboulements.com/ |
| L'Ascension-de-Patapédia, Quebec (ca:csd:2406060) | https://www.youtube.com/watch?v=fcW-ghyKGqU | found on https://matapedialesplateaux.com/photos-et-videos/ |
| Bury, Quebec (ca:csd:2441070) | https://www.youtube.com/watch?v=DGQwd1_dpuc | found on https://municipalitedebury.qc.ca/wp-json/wp/v2/posts?search=meeting&per_page=10&_fields=link,title,date,content |
| Deschaillons-sur-Saint-Laurent, Quebec (ca:csd:2438070) | https://www.youtube.com/watch?v=SIVOQxukoY4 | found on https://www.deschaillons.ca/ |
| Potton, Quebec (ca:csd:2445030) | http://youtube.com/@CommunicationsPotton | found on https://potton.ca/: under heading "Danger d’incendie"; page "Potton - Potton" |
| Marieville, Quebec (ca:csd:2455048) | https://www.youtube.com/watch?v=mbs2TWGcnOM | found on https://www.ville.marieville.qc.ca/fr/la-ville/conseil-municipal/seances-du-conseil |
| Saint-Pie, Quebec (ca:csd:2454008) | https://www.youtube.com/watch?v=dMSvNbnva84 | found on https://villest-pie.ca/ville/conseil-municipal/calendrier-des-seances-du-conseil-et-proces-verbaux/ |
| Orford, Quebec (ca:csd:2445115) | https://www.youtube.com/channel/UCvKMK8q9c1gkjQaW9Kz252w?view_as=subscriber | found on https://canton.orford.qc.ca/ordre-du-jour-seance-ordinaire-du-conseil-6-octobre-2026-2/ |
| Brébeuf, Quebec (ca:csd:2478075) | https://www.youtube.com/watch?v=fbiv8X8WZAE | found on https://brebeuf.ca/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |
| Lac-Supérieur, Quebec (ca:csd:2478095) | https://www.youtube.com/watch?v=HxUyghMLlQg | found on https://muni.lacsuperieur.qc.ca/seance-du-conseil-municipal-en-ligne/ |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
