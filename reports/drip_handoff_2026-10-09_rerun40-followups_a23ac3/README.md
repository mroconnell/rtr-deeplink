# Drip handoff 2026-10-09_rerun40-followups_a23ac3: 1 lead (Marshfield School District MA)

This lead comes from a hand look, not a run: rtr-findmeeting `data/better_videos_2026-10-09/better_videos.csv`. The district's own
School Committee page (https://www.mpsd.org/page/school-committee) links this YouTube playlist with the link text "School Committee
Meetings - Video". Ryan decided in chat on 2026-10-09 to add it ("go on adding the marshfield"). No YouTube request was made.

The district has no Archive page (better_videos.csv). The playlist is not on the drip list, in the tier-3 queue or in an earlier
handoff folder. The same row was added to the rtr-business drip list with `verified=false`. The rtr-findmeeting record is
`analysis/rerun40_followups_2026-10-09/`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 1 |
|---|---|---|
| youtube | playlist | 1 |

## Why each lead was suggested (1 of 1 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Marshfield School District, Massachusetts (us:sd:2507350) | https://www.youtube.com/playlist?list=PLN1bqMhmefvVsXWSETU-BdEIZPeTCZAzD | found on https://www.mpsd.org/page/school-committee: link text "School Committee Meetings - Video" (Ryan chat 2026-10-09) |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
