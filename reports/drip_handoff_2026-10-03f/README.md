# Drip handoff, part f: 59 YouTube leads from Find Meeting chunk 4 (2026-10-03)

These come from one finished Find Meeting run (rtr-findmeeting `big_job/run_govs_04`, 3,566 governments), routed by the
`apply` step and then by the hand rules Ryan accepted on 2026-10-03. No YouTube request was made.

Every government here was checked first: it has no Archive page under 2 years old (Archive inventory export of 2026-10-03,
17:26), and the address is not already on the drip list (rtr-business `research/youtube_channel_leads.csv`) for this
government, in the Archive, the queue, the queue history or the fail file. The same rows were added to the rtr-business
drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as parts d and e. 59 rows for 58 governments.

| Lane | Kind | Count of 59 |
|---|---|---|
| youtube | channel | 18 |
| youtube | playlist | 5 |
| youtube | single_video | 36 |

Where the rows come from:

| Source | Count of 59 |
|---|---|
| The government's own route is a YouTube lead | 34 |
| Added alongside a Find Video route (a meeting page with no video) | 17 |
| Added alongside a tier 3 route (queued or held for a person) | 3 |
| Rule 1c: the address is on the list under another government (see below) | 5 |

## Rule 1c rows (5)

| Government | Address | Why it is here |
|---|---|---|
| Wilmington city, Illinois | https://www.youtube.com/channel/UCkyATwHPh43LiCZ0y8tpSMQ | Also on the list under a second "Wilmington city IL" row (us:cousub:1719782114); the same or an overlapping body |
| Killingly, Connecticut | https://www.youtube.com/channel/UCUT8mByfPfMQAqR9Q8-PiSg | Also on the list under Danielson borough CT, which lies inside Killingly |
| Mokane city, Missouri | https://www.youtube.com/embed/live_stream?channel=UCeHxfeo3l2Y2Q6_gjSd9GiQ | Not a real conflict: every live_stream embed shares one address key; this channel is on the list for no one else |
| Hilshire Village city, Texas | https://www.youtube.com/user/TxDOTpio | **Low confidence.** The handle names the Texas Department of Transportation. Also on the list under Terrell County TX |
| Brampton Township, Michigan | https://www.youtube.com/@deltacountymi/streams | **Low confidence.** The handle names Delta County MI. Also on the list (low confidence) under Wells Township MI |

For the two low-confidence rows: if the channel belongs to the other body, record "not this government's channel" for
the suggested government.

## Left out

| Why | Count |
|---|---|
| Another body or unrelated channel named in the handle (Association of Washington Cities, Mississippi Department of Revenue, DIRECTV, ozarkabb) | 4 |
| Website-builder channel (homesteadwebsites) | 1 |
| The West Virginia state channel Ryan removed on 2026-10-03 (Albright town WV) | 1 |
| Template embed bqLUp7GuUTg, or an address seen in two or more states | 20 |
| On the list under another government, undecided (listed for Ryan) | 3 |

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
