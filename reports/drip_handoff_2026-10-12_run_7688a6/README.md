# Drip handoff 2026-10-12_run_7688a6: 2 leads from rtr-findmeeting run run

These come from the Find Meeting run `run` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 2 |
|---|---|---|
| youtube | channel | 2 |

## Low-confidence rows (1): verify skeptically

The handle names another body. Add a row only if the channel or video shows clear meetings of this government's board or school district body. `leads.csv` has no note column, so the doubt is written here (and in the drip-list note).

| Government | Address | Note |
|---|---|---|
| Sylvan township, Michigan (us:cousub:2616177800) | https://www.youtube.com/@SylvanTownship/videos | rtr-findmeeting run run (2026-10-12): 1 YouTube address(es) linked from the government's own site; YouTube not fetched; NOT hand-read; low confidence: handle names Sylvan township, Michigan; suggested for Sylvan township, Michigan; address also on the list under Sylvan township, Michigan (us:cousub:2613377760); drip: verify skeptically: add only if the channel or video shows clear meetings of this government's board or school district body |

## Why each lead was suggested (1 of 2 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Dexter Township, Michigan (us:cousub:2616122180) | https://www.youtube.com/@DexterTownship | found on https://www.dextertownshipmi.gov/: "Watch a Dexter Township Video"; page "Dexter Township – MI"; nearby: "Watch a Dexter Township Video" |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
