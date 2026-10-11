# Drip handoff 2026-10-11_csur-playlists: 9 council-meeting playlists from the CSUR channel

## What these are and why

CSUR (the Vaudreuil-Soulanges community TV, YouTube channel `@csurtv`) keeps one playlist of council meetings per municipality. You listed the channel's 78 playlists in one call on 2026-10-11 (branch `csur-playlists-2026-10-11`). Nine are named "<municipality> | LES SÉANCES DU CONSEIL MUNICIPAL". The other 68 are shows, festivals and elections, and are not part of this handoff.

**Ryan confirmed on 2026-10-11 that these nine are the real, municipality-specific playlists.** Each playlist is the lead for its municipality. They are French-language council meetings, which also fit the French audio request. No YouTube request was made to build this file.

## The file

`leads.csv`, one row per playlist. Same columns as the earlier handoffs.

| Lane | Kind | Count of 9 |
|---|---|---|
| youtube | playlist | 9 |

| Government | gov_id | Playlist |
|---|---|---|
| Rigaud | ca:csd:2471133 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIdXBcf-uFvxrzqWprpQsn3g |
| Saint-Zotique | ca:csd:2471025 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIdaAqynTJ9ppKa3jO57oZJ6 |
| Hudson | ca:csd:2471100 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIeCUsBsYfDnojB7jCc67p4H |
| Les Coteaux | ca:csd:2471033 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIdZleDKCG6W-c6UKPTgD16- |
| Les Cèdres | ca:csd:2471050 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIdklmk7Ke5w7ms5pp1ouqOA |
| Vaudreuil-sur-le-Lac | ca:csd:2471090 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIcjNfEmU4ueycap2Th7jZjL |
| Saint-Polycarpe | ca:csd:2471020 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIdPMlD_Mlq6SBK3cYU00yiY |
| Vaudreuil-Dorion | ca:csd:2471083 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIfs-XBfV-njQv_eJbdgb9N7 |
| Coteau-du-Lac | ca:csd:2471040 | https://www.youtube.com/playlist?list=PLTQbtGFPJIIeeJXiaMNqYswFG4rLPAQQ8 |

The same nine rows are in the rtr-business drip list (`research/youtube_channel_leads.csv`, `verified=false`, `source_wo=csur_playlists_2026-10-11`). Seven of these municipalities also have an older channel or single-video lead on the list (for example `youtube.com/user/csurlatele` for Vaudreuil-sur-le-Lac). Keep those; the playlist is the better lead for each.

## The pass

The ownership check is already done (Ryan's confirmation). Drip each playlist as its municipality's council meetings.

1. Take the playlist as the lead for its municipality. Do not file it under another government.
2. Check that the playlist holds recent council meetings (dates and titles).
3. Drip through the normal `leads` lane. Record "no meetings" or "playlist empty" as findings, with a reason.
4. Other CSUR playlists on the channel are not part of this; do not walk them.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
