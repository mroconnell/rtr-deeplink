# Meeting body recount, 2026-10-17

## What was done

After the 2026-10-17 deploy, I counted how many Archive pages have a meeting body ("City Council", "Planning Commission"). I used `GET /internal/meeting-inventory/summary` and `scripts/export_meeting_inventory.py`, both over HTTP only, 500 rows per request.

## Result

971 of 12,934 pages have a meeting body (7.5%); 11,963 are blank.

| Date | Pages | With a body | Share |
|---|---|---|---|
| 2026-09-09 | 6,529 | 667 | 10.2% |
| 2026-10-17 | 12,934 | 971 | 7.5% |

Of the 1,997 pages created since 2026-10-01, 219 (11%) have a body.

| Platform | Pages | With a body |
|---|---|---|
| YouTube | 4,062 | 309 (7.6%) |
| Granicus | 2,362 | 295 (12.5%) |
| Swagit | 850 | 3 |
| CivicClerk | 791 | 66 (8.3%) |
| Cablecast | 654 | 2 |
| eScribe | 603 | 0 |
| Direct video file | 503 | 91 (18.1%) |
| Internet Archive | 409 | 0 |
| Utah PMN | 395 | 24 |
| TelVue | 388 | 23 |
| IQM2 | 344 | 8 |
| CivicWeb | 336 | 7 |
| Vimeo | 232 | 1 |
| PrimeGov | 152 | 0 |
| Sliq Harmony | 57 | 56 |
| AV Capture All | 39 | 38 |
| SuiteOne Media | 38 | 25 |

## Caution

The body is only written at ingest. CivicClerk has extracted it since WO-904, but pages archived before that never got it: only 66 of 791 CivicClerk pages have one.

## Recommendation

Re-check the old CivicClerk pages. That fills the body from a real source field, with no title guessing. PrimeGov's `committeeId` and IQM2's calendar are the next real sources (each has its own BACKLOG entry).

Files: `meeting_inventory_2026-10-17.csv` (one row per page), `meeting_inventory_2026-10-17.html` (a sortable review page), and `meeting_inventory_summary_2026-10-17.json`.
