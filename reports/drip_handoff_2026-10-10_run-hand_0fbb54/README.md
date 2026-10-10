# Drip handoff 2026-10-10_run-hand_0fbb54: 3 leads from rtr-findmeeting run run_hand

These come from the Find Meeting run `run_hand` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 3 |
|---|---|---|
| youtube | channel | 2 |
| youtube | single_video | 1 |

## Why each lead was suggested (3 of 3 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Sherbrooke, Quebec (ca:csd:2443027) | https://www.youtube.com/watch?v=sVvf9_1rsNs | found on https://www.sherbrooke.ca/fr/vie-municipale/seances-du-conseil-municipal-et-des-conseils-d-arrondissement/723/seance-extraordinaire |
| Lévis, Quebec (ca:csd:2425213) | https://www.youtube.com/user/VilleDeLevis | found on https://levis.ca/: "Utube" under heading "Conditions et politiques"; page "Ville de Lévis / Services municipaux et informations"; nearby: "Facebook instagram X Utube LIn Tiktok" |
| Dollard-Des Ormeaux, Quebec (ca:csd:2466142) | https://www.youtube.com/channel/UCHrt7GQahGdCXNMwMpvo_dA | found on https://ville.ddo.qc.ca/: "Youtube"; page "Ville de Dollard-des-Ormeaux"; nearby: "Facebook Instagram Youtube" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
