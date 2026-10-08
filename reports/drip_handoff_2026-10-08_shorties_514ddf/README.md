# Drip handoff 2026-10-08_shorties_514ddf: 7 leads Ryan put through from the shorties review

Ryan decided on 2026-10-08 (chat) that these governments' own sites hold only short clips, so the long YouTube leads linked from their
own pages are assumed to be the real council video. They go in the drip feed for a hand check. No YouTube request was made.

Each address was checked first: not on the drip list (rtr-business `research/youtube_channel_leads.csv`) and not a lead in any
earlier handoff or queue file. Two of them (East Broughton) were seen before only inside the qc_giant handoff's
`all_youtube_addresses_seen` list, which is a list of addresses noticed, not a queued row. The same 7 rows were added to the
rtr-business drip list with `verified=false`. The addresses have not been read by hand.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs. `meeting_source_has_no_video` is `no` on every row: the
government's own site has video, only short clips.

| Lane | Kind | Count of 7 |
|---|---|---|
| youtube | channel | 1 |
| youtube | single_video | 6 |

## Governments

| Government | Count of 7 addresses |
|---|---|
| East Broughton, Quebec (ca:csd:2431122) | 2 |
| Baie-Comeau, Quebec (ca:csd:2496020) | 2 |
| La Vallée-du-Richelieu, Quebec (ca:cd:2457) | 2 |
| Montcalm, Quebec (ca:cd:2463) | 1 |

## Why each lead was suggested

What the government's own page said around the link (`found_context` in `leads.csv`).

| Government | Address | Found on the page |
|---|---|---|
| East Broughton, Quebec (ca:csd:2431122) | https://www.youtube.com/watch?v=CTzeWASJ5fM | found on https://www.municipaliteeastbroughton.com/fr/municipalite/conseil-municipal/proces-verbaux/: Link text 'Enregistrement vidéo' under the heading '14 septembre 2026 Conseil | Séance ordinaire' |
| East Broughton, Quebec (ca:csd:2431122) | https://www.youtube.com/watch?v=B-PYI7du_lI | found on https://www.municipaliteeastbroughton.com/fr/municipalite/conseil-municipal/proces-verbaux/: Link text 'Enregistrement vidéo' under the heading '15 juin 2026 Conseil | Séance ordinaire' (page address had &t=3180s, a start offset, dropped here) |
| Baie-Comeau, Quebec (ca:csd:2496020) | https://www.youtube.com/watch?v=NNi_yO0DKXs | found on https://www.ville.baie-comeau.qc.ca/ville/vie-democratique/seances-du-conseil-municipal/: Link text 'Enregistrement' next to 'Séance du 21 septembre' in the 'Séances ordinaires' column of 'Année 2026' |
| Baie-Comeau, Quebec (ca:csd:2496020) | https://www.youtube.com/watch?v=SjEkTqTw2zs | found on https://www.ville.baie-comeau.qc.ca/ville/vie-democratique/seances-du-conseil-municipal/: Link text 'Enregistrement' next to 'Séance du 24 août' in the 'Séances ordinaires' column of 'Année 2026' |
| La Vallée-du-Richelieu, Quebec (ca:cd:2457) | https://www.youtube.com/watch?v=i2b1qY-33X4 | found on https://www.mrcvr.ca/documentation/seances-du-conseil/: Link text 'visionner la séance' after '17 septembre' in 'Pour l’année 2026, les séances ordinaires du Conseil seront tenues aux dates suivantes' |
| La Vallée-du-Richelieu, Quebec (ca:cd:2457) | https://www.youtube.com/watch?v=c5uXEf8-SfE | found on https://www.mrcvr.ca/documentation/seances-du-conseil/: Link text 'visionner la séance' after '20 août' in the 2026 list of ordinary council meetings |
| Montcalm, Quebec (ca:cd:2463) | https://www.youtube.com/@mrcdemontcalm6277/streams | found on https://www.mrcmontcalm.com/la-mrc/gouvernance/seances-du-conseil: Channel link 'chaîne YouTube' in the sentence 'Les séances sont pour la plupart diffusées en direct sur notre chaîne YouTube' (no single video listed on the page) |
