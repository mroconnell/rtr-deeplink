# New drip leads: shared stations and row review (2026-09-30)

These 122 leads were added to the rtr-business drip list
(`research/youtube_channel_leads.csv`) on 2026-09-30. That file isn't on
GitHub, so here is a copy. Work them in the drip lane like any other lead.

## Where they came from

| Source (`source_wo`) | Count of 122 |
|---|---|
| Shared-station census: one playlist per government on public-access channels that carry several governments | 102 |
| Row review with Ryan (LaPorte County channel towns, Brazos County TX) | 10 |
| Special districts filed under their own id or their city/county | 9 |
| Charleston County SC: existing lead confirmed as the meetings channel | 1 |

## What "verified" means here

`verified=true` means a person read the playlist title (or, for Charleston,
the county's own hub) and it names this government's body and place. No one
opened the videos. Research sessions no longer make YouTube requests, so
reading the videos is the drip lane's job.

Most rows are playlists on a shared channel (`kind=channel`, URL
`youtube.com/playlist?list=...`). Use the playlist, not the whole channel:
the channel carries other governments. A note starting `meeting body:` means
the meetings are a district board filed under that city or county.

## If a lead is wrong

Record it in `drip_leads_out.csv` here (same columns plus a `result` column),
push to this branch, and don't merge. The coordinator folds results back into
the rtr-business list.
