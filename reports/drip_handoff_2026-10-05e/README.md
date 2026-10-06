# Drip handoff 2026-10-05e: Millcreek township PA leads re-keyed to the right government

Ryan approved this in chat on 2026-10-05. The evidence is rtr-findmeeting
`data/loose_ends_2026-10-05/README.md`, part B. No YouTube or web request was made.

Both addresses belong to Millcreek township, Erie County, PA (`us:cousub:4204949548`).
Its own site is millcreektownship.com.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs. Count of 2.

| Address | Kind | Right government | gov_id | Was filed under |
|---|---|---|---|---|
| https://www.youtube.com/watch?v=LULgUnnzqwY | single video | Millcreek township, Erie County, PA | us:cousub:4204949548 | `us:cousub:4200048000`, an id that is not a real government |
| https://www.youtube.com/@millcreektownshippa | channel | Millcreek township, Erie County, PA | us:cousub:4204949548 | Mill Creek borough, PA (`us:place:4249552`) in `reports/drip_handoff_2026-10-03e/leads.csv`; also on the rtr-business drip list under the township since WO-913 |

Why Erie: the video is embedded on millcreektownship.com as "Supervisors' Meeting
7/28/2026". The channel is linked from the same site's "Follow Us" icon. Who uploaded
the video is not known; YouTube was not read.

The video row was on the rtr-business drip list (since 2026-09-23) but in no handoff
folder. The channel row under the township was also in no handoff folder.

## Old wrong-government address the drip should reject

Please reject this line from `reports/drip_handoff_2026-10-03e/leads.csv`. It was
removed from the rtr-business drip list.

| Address | Wrong government (gov_id) | Right government |
|---|---|---|
| https://www.youtube.com/@millcreektownshippa | Mill Creek borough, PA (us:place:4249552) | Millcreek township, Erie County (us:cousub:4204949548) |

Also: any drip result filed under `us:cousub:4200048000` belongs to `us:cousub:4204949548`.

## The pass

1. Check that the channel or video is the township's own public body.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
