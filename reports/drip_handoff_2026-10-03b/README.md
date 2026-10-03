# Drip handoff, part b: 33 YouTube leads from the 2026-10-03 catch-up

The first drip handoff (`reports/drip_handoff_2026-10-03/`) picked one address per government. For governments the run routed
to tier 1, tier 3 or Vimeo, some YouTube addresses on the government's own website were not passed on.
A catch-up screen found 33 more addresses to add, across 31 governments. No YouTube request was made.

Every government here was checked again today: it has no Archive page under 2 years old, and neither the government nor the address
is on the drip list (rtr-business `research/youtube_channel_leads.csv`), in the queue, or in the queue history.
37 addresses passed the screen; 4 were dropped because their government is already on the drip list (Montpelier OH, Scottsbluff NE, Fairport NY, Sugar Land TX).
The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address (two governments, Atwater CA and New Albany OH, have two addresses each). Same columns as part one.
`meeting_source_has_no_video` is `no` on every row: these governments already have a tier 1, tier 3 or Vimeo route.

| Lane | Kind | Count of 33 |
|---|---|---|
| youtube | channel | 28 |
| youtube | playlist | 2 |
| youtube | single_video | 3 |

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
