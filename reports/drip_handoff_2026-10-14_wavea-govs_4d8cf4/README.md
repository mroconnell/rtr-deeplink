# Drip handoff 2026-10-14_wavea-govs_4d8cf4: 2 leads from rtr-findmeeting run waveA_govs

These come from the Find Meeting run `waveA_govs` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 2 |
|---|---|---|
| youtube | playlist | 1 |
| youtube | single_video | 1 |

## Why each lead was suggested (2 of 2 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Milton town, Massachusetts (us:cousub:2502141690) | https://www.youtube.com/playlist?list=PLk5NCS3UGButs3VfEQgTpHtfoo4HiEREM | found on https://www.miltonma.gov/376/Boards-Committees |
| Newcastle city, Oklahoma (us:place:4051150) | https://www.youtube.com/live/gQJ6rL9Muuc | found on https://newcastleok.gov/: "https://www.youtube.com/live/gQJ6rL9Muuc" under heading "Social Stream"; page "Welcome to the City of Newcastle, OK"; nearby: "Newcastle City Council meeting is streaming LIVE now! (Tuesday meeting due to federal holiday on Monday)￼ ￼ https://www.youtube.com/live/gQJ6rL9Muuc" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
