# CSUR playlists: one list request for the drip Mac (Ryan, 2026-10-11)

## What is asked and why

The YouTube channel CSUR (https://www.youtube.com/@csurtv/playlists) has many playlists, apparently one per Quebec municipality (for example "Vaudreuil Sur le Lac" and "Saint Polycarpe"). We hold almost none of them: the drip list has one old-style CSUR row (`youtube.com/user/csurlatele`, Vaudreuil-sur-le-Lac) and no playlists. Ryan wants every playlist title and address in one dump, so the playlists can be matched to Quebec governments and added to the drip list.

Only the drip Mac makes YouTube requests, so this is handed to it.

## The request

1. Read the channel's playlists tab, https://www.youtube.com/@csurtv/playlists , with **one call** that returns the whole list (for example a flat playlist listing of the channel's playlists tab).
2. If the list does not come back complete in that call, page through it with **at most 5 calls in total**. Stop at 5, even if the list is incomplete.
3. Write `playlists.csv` in this folder with one row per playlist and these columns: `title`, `playlist_url`, `playlist_id`, `video_count` (blank if the call does not return it), `call_number` (which of the 1 to 5 calls returned it).
4. Write `RESULT.md` in this folder (short sentences): how many calls were used, how many playlists came back, whether the list looks complete (and why), and anything odd (blocked, rate-limited, a channel redirect).
5. Commit both files and push to this branch (`csur-playlists-2026-10-11`). Nothing else: no video pages, no captions, no ingest, no changes to the drip list.

## Rules

Ryan's limit is 5 calls for this job. Follow the drip runbook's rate rules for pacing.

## What happens next

The requesting session (Enumeration - Bloomington) reads the branch, matches each title to a Quebec government (`ca:csd`), and writes one playlist drip row per match into the drip list in rtr-business. Titles that match more than one government go to the Hand Checks page.
