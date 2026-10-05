# Drip handoff 2026-10-05 trace: 8 YouTube addresses for 3 school districts

Ryan asked for the trace fixes on 2026-10-05. The trace of "routed but not in the Archive" governments found three school districts on the drip list with no handoff folder yet: Paradise Valley AZ, Ann Arbor Public Schools MI and Lancaster ISD TX.
No YouTube or other web request was made for this handoff. Every address comes from the government's own site, as recorded by rtr-findmeeting (run `districts_combined`, 2026-10-04) and by earlier Meeting Finder runs.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs. Count of 8.

| Government | gov_id | New addresses (count of 3) | Already on the drip list, not in any handoff yet (count of 5) |
|---|---|---|---|
| Paradise Valley Unified District, AZ | us:sd:0405930 | 1 video | 1 (https://www.youtube.com/pvschools) |
| Ann Arbor Public Schools, MI | us:sd:2602820 | 1 channel (@CTNAnnArbor) | 2 (their own channel, 1 video) |
| Lancaster Independent School District, TX | us:sd:4826670 | 1 channel (@LANCASTERISDTV) | 2 (1 channel, 1 video) |

The `run` column says which rows are new (`trace_fix_2026-10-05`) and which came from the earlier source (WO-914, Meeting Finder runs).
All 8 rows are on the rtr-business drip list (`research/youtube_channel_leads.csv`), `verified=false`.

## Things to check

- `@CTNAnnArbor` is also the Ann Arbor city station. It is filed under the city (us:place:2603000) as `/user/ctnannarbor`. Check that it carries Ann Arbor Public Schools board meetings. If not, reject it for the district.
- The Paradise Valley "channel" row `https://www.youtube.com/pvschools` is typed single_video on the list. Check what it really is.
- Paradise Valley and Lancaster ISD may have a meeting source outside YouTube. If a YouTube channel turns out to hold the board meetings, that still counts.

## The pass

1. Check that the channel is the government's own public body.
2. Check for meeting videos.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
