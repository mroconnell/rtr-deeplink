# Drip handoff 2026-10-10_run-blind_872d1c: 4 leads from rtr-findmeeting run run_blind

These come from the Find Meeting run `run_blind` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 4 |
|---|---|---|
| youtube | channel | 4 |

## Why each lead was suggested (4 of 4 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Saint-Lazare, Quebec (ca:csd:2471105) | https://www.youtube.com/channel/UC42OBIMKLHziilr3BwKmfEA | found on https://www.ville.saint-lazare.qc.ca/fr: "Navigation vers YouTube - Ville Saint-Lazare" under heading "De nombreuses activités pour tous les âges"; page "Ville de Saint-Lazare"; nearby: "M’abonner à l’infolettre" |
| Chambly, Quebec (ca:csd:2457005) | https://www.youtube.com/user/VilledeChambly | found on https://chambly.ca/: "YouTube" under heading "Recherchez votre adresse"; page "Ville de Chambly / Ville accueillante alliant nature et histoire"; nearby: "© Ville de Chambly, 2026 Politique de confidentialité Accessibilité universelle Témoins de navigation Nous joindre Blanko" |
| Saint-Eustache, Quebec (ca:csd:2472005) | https://www.youtube.com/user/villesainteustache | found on https://www.saint-eustache.ca/: "YouTube" under heading "La campagne Branché sur ma sécurité, portant sur l’utilisation des appareils de transport personnel motorisés (ATPM), c…"; page "Ville de Saint-Eustache"; nearby: "Suivez-nous Abonnez-vous à l’infolettre" |
| Varennes, Quebec (ca:csd:2459020) | https://www.youtube.com/user/VilleVarennes | found on https://www.ville.varennes.qc.ca/: under heading "D’exploits et d’avenir!"; page "Ville de Varennes / Site officiel"; nearby: "Portrait et statistiques Parc et sites d'activités Calendrier des activités Programme de subventions" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
