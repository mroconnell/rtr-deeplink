# Drip handoff: 516 leads from rtr-findmeeting runs (2026-10-03)

These come from four finished Find Meeting runs (rtr-findmeeting: group4_pilot300, group4_batch2, group4_final and big_job/run_govs_01).
For each government below, the run found YouTube or Vimeo links on the government's own website. No YouTube request was made.

Every government here was checked first: it has no Archive page under 2 years old, and neither the lead nor the government is
already on the drip list (rtr-business `research/youtube_channel_leads.csv`), in the queue, or in the queue history.
The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per government:

| Column | What it holds |
|---|---|
| gov_id, government, state | The government |
| lane | youtube or vimeo |
| lead_url | The one address picked: a channel first, then a playlist, then the first video seen |
| kind | channel, playlist or single_video |
| meeting_source_has_no_video | yes when the run also found the government's meeting page, with no video on it |
| run | The Find Meeting run |
| all_youtube_addresses_seen | Every YouTube address the run saw for this government, space separated |

| Lane | Kind | Count of 516 |
|---|---|---|
| vimeo | single_video | 17 |
| youtube | channel | 354 |
| youtube | playlist | 17 |
| youtube | single_video | 128 |

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
