# Drip handoff 2026-10-11_run-ca_8fa0a0: 22 leads from rtr-findmeeting run run_ca

These come from the Find Meeting run `run_ca` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 22 |
|---|---|---|
| youtube | channel | 7 |
| youtube | single_video | 15 |

## Shared with a neighbouring body (1)

Ryan (2026-10-03): fine to give each neighbouring body the row.

| Government | Address | Note |
|---|---|---|
| Val Marie, Saskatchewan (ca:csd:4704002) | https://www.youtube.com/watch?v=t5sU7BM_7-A | rtr-findmeeting run run_ca (2026-10-11): 2 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; shared with neighbouring body Val Marie No. 17 (ca:csd:4704003, also in Division No. 4) |

## Why each lead was suggested (18 of 22 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Macklin, Saskatchewan (ca:csd:4713051) | https://www.youtube.com/watch?v=04Tk5wbheoc | found on https://macklin.ca/government/history.html; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Whitemouth, Manitoba (ca:csd:4601046) | https://www.youtube.com/channel/UCgyktR55AnUKOjJYq5fSynQ | "Let Your Heart Beat Here" |
| Shippagan, New Brunswick (ca:csd:1315031) | https://youtu.be/AYpHD67p94w?si=-tbPQ9Kt54No6WJM&fbclid=IwZXh0bgNhZW0CMTAAYnJpZBExSDVzOGpOSFphdHJpZDZadXNydGMGYXBwX2lkEDIyMjAzOTE3ODgyMDA4OTIAAR5UnuhyJJALelC5--wVGWi6Gh6-8sB-PqmrXjcY_xkOoT2j1IiIQJDPt6vTOw_aem_U1E83IOsBSTekrTxLSc8Kg | found on https://shippagan.ca/nouvelles/assermentation-du-conseil-municipal-2026-2030 |
| Regina Beach, Saskatchewan (ca:csd:4706058) | https://www.youtube.com/watch?v=3M_oofR7tlY | found on https://reginabeach.ca/information-access |
| Murray River, Prince Edward Island (ca:csd:1101004) | https://www.youtube.com/watch?v=RsojLsXU0is | found on https://www.murrayriverpei.ca/council-meeting-minutes/ |
| Moncton, New Brunswick (ca:csd:1307022) | https://m.youtube.com/@city-ville-moncton | found on https://www.moncton.ca/fr/commentaires-sur-le-site |
| Oxford, Nova Scotia (ca:csd:1211012) | https://www.youtube.com/@OxfordNovaScotia | found on https://oxfordns.ca/component/com_jcalpro/Itemid,498/id,218/view,category/ |
| Alma, Quebec (ca:csd:2493042) | https://www.youtube.com/channel/UCyzhllULjCifNrOCi7Q6jnQ | found on https://www.ville.alma.qc.ca/; page "Accueil - Ville d'Alma"; nearby: "Tourisme Affaires Ville d'Alma spectacles Nous joindre" |
| Boisbriand, Quebec (ca:csd:2473005) | https://www.youtube.com/user/VilleBoisbriand | found on https://www.ville.boisbriand.qc.ca/: "YouTube" under heading "Événements"; page "Ville de Boisbriand"; nearby: "© Ville de Boisbriand, 2026 Portail des employés Politique de confidentialité Témoins de navigation Nous joindre Blanko" |
| Leamington, Ontario (ca:csd:3537003) | https://www.youtube.com/user/TownofLeamington | found on https://events.leamington.ca/meetings |
| O'Connor, Ontario (ca:csd:3558016) | https://www.youtube.com/watch?v=FuxXSAEuUQE | found on https://www.oconnortownship.ca/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |
| Mortlach, Saskatchewan (ca:csd:4707034) | https://www.youtube.com/watch?v=A6vmqAZMH6M | found on https://mortlach.ca/videos/safety-days; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Winnipeg, Manitoba (ca:csd:4611040) | https://www.youtube.com/user/thecityofwinnipeg | found on https://www.winnipeg.ca/: "City of Winnipeg YouTube" under heading "How can we make this web page better?"; page "City of Winnipeg"; nearby: "City of Winnipeg 510 Main St. Winnipeg, Manitoba R3B 1B9 Home Accessibility Apps Open Data Maps Services & programs Recreation & leisure People & culture Building & development City governance Departm" |
| Arrowwood, Alberta (ca:csd:4805011) | https://www.youtube.com/watch?v=QhxWFY7HuM4 | found on https://villageofarrowwood.ca/here-for-you-video/ |
| Mossbank, Saskatchewan (ca:csd:4703092) | https://youtu.be/xLWg305oeLs | found on https://www.mossbank.ca/live/school |
| East St. Paul, Manitoba (ca:csd:4613032) | https://www.youtube.com/watch?v=eCl8uYWc9V0 | found on https://eaststpaul.com/p/meetings-minutes |
| Sayward, British Columbia (ca:csd:5924039) | https://youtu.be/RuM5tacFQXY | found on https://www.sayward.ca/municipal-services/council-meetings/regular-council-meeting-october-6-2026-rescheduled-oct-13-2026 |
| New Hazelton, British Columbia (ca:csd:5949024) | https://www.youtube.com/watch?v=uTjHqyd7va4 | found on https://newhazelton.ca/wp-json/wp/v2/posts?search=video&per_page=10&_fields=link,title,date,content |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
