# Drip handoff 2026-10-04 (modes pilot): 59 leads for 57 governments

These come from the county and school-district pilot (100 counties and 200 school districts), re-applied with the new owner-check rules
(rtr-findmeeting main 60a2bcc, PR #8). For each government below, the pilot walk found a YouTube link on the government's own website.
No YouTube request was made, by the pilot, by the apply step, or while writing this handoff.

The owner check is skipped for YouTube on purpose. The drip lane does its own owner work, as it does for every lead run. So every row is
`verified=false`, "NOT hand-read".

Each government was checked first: no Archive page under 2 years old (inventory re-exported today), and the address is not already on the drip
list (rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in two
or more states were left out. The same rows were added to the rtr-business drip list with source tag `findmeeting_modes_pilot_2026-10-03`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 59 |
|---|---|---|
| youtube | channel | 48 |
| youtube | single_video | 10 |
| youtube | playlist | 1 |

| Does the government's meeting source have no video? | Count of 59 |
|---|---|
| no | 50 |
| yes (a Find Video government) | 9 |

11 of the 59 rows sit alongside another route for the same government (9 Find Video governments and Osborne County KS, whose tier 3 file is held).

## What was left out

| Result | Count of governments |
|---|---|
| Not added: the government's YouTube address is already on the drip list | 46 |
| Not added: the government already has a drip row | 7 |
| Not added: the address is in the queue history | 1 |
| Held for Ryan: the address is on the list under another government, and a channel id or single video cannot say whose it is (Escanaba Area Public Schools MI, Red Lake Falls Public School District MN) | 2 |
| Dropped with the government: the pilot hand-check found its meeting belongs to another body (Taylor County WV, York County ME, Randolph County IN, Isle of Wight County Public Schools VA, Daggett UT; 14 YouTube addresses) | 5 |

One more address is held in `remaining_conflicts` for Ryan: the handle `DSTechForFamilies` for Dover-Sherborn School District MA is on the list under
Dover School District MA, and the handle names neither clearly. Dover-Sherborn's other route (tier 3) is not affected.

## Caution

Read the channel name first. These channel names look like a team, a student group or an event channel rather than the district's board:
`@fpstigerpride` (Fremont Public Schools), `@eastonjaguars` (Easton), `@TritonTrojans` (Triton), `@cgbrockets5466` (Cedar Grove-Belgium),
`c/SkagwaySchoolEvents` (Skagway), `@MIARadio4015` (Montgomery County SD), `@NH_SAU9` (Conway). Skip a channel that has no board meetings. Skip
any video of students, 911, police, body cameras or a jail.

Clay County WV was found with three channels. Only one (an unnamed channel id) is in this file. The other two are named for the West Virginia
legislature and a state environment agency, and apply did not add them.

## The pass

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
