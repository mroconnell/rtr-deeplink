# Drip handoff 2026-10-12_station-youtube: 34 YouTube leads from 13 Massachusetts stations' own pages

## What these are and why

13 public-access stations post their government meetings on YouTube and not on a platform we ingest from. An agent read each station's own web pages (HTML only) and listed the YouTube addresses they link. No YouTube request was made to build this file. Ryan asked on 2026-10-12 for these to go to the drip a second time; many of these governments already have an older lead on the list, and a repeat is fine.

These are shared station addresses: each station carries more than one government, so the same channel appears once for each government it serves.

## The file

`leads.csv`, one row per address and government. Same columns as the earlier handoffs.

| Lane | Kind | Count of 34 |
|---|---|---:|
| youtube | channel | 18 |
| youtube | playlist | 13 |
| youtube | single_video | 3 |

Stations: 1623 Studios (Essex, Gloucester, Manchester-by-the-Sea, Rockport), Plymouth Area Community Access TV (Duxbury, Kingston, Pembroke, Plymouth), Frontier Community Access TV (Conway, Deerfield, Sunderland), Whitman Hanson Community Access (Hanson, Whitman), Westwood Media Center (Westwood: 13 board and project playlists), Area 58 (Halifax: 2 single videos), Buckland and Shelburne (Buckland: 1 single video), and one channel each for Attleboro, Berlin, Quincy, Holliston, Nantucket and Concord-Carlisle (Carlisle).

The same rows are in the rtr-business drip list (`research/youtube_channel_leads.csv`, `verified=false`, `source_wo=station_youtube_links_2026-10-12`).

## The pass

1. For a channel, check it is the station's own public channel and that it carries government meetings (a station channel can also hold sports and community shows; Nantucket's lead is the "Town Government" channel only).
2. For each government, find that government's own meetings; do not file a station's whole channel under every government it serves without checking titles.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. Westwood's 13 playlists are one per board or project: drip them as Westwood town's.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
