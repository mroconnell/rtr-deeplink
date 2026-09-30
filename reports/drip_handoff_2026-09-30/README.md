# Drip-lead pass: 1,595 YouTube-only governments (2026-09-30)

Meeting Finder ran on 10,000 governments from the Red Tape Recordings research file (research rows marked no-platform-link-found, meeting-without-video-unverified, no-meetings-found, or never checked). For 1,595 of them it found meeting links, but only on YouTube. Meeting Finder makes no YouTube requests, so these need the drip Mac.

## The file

`youtube_only_group4.csv`, one row per government:

| Column | What it holds |
|---|---|
| gov_id, government, state | The government, from the research file |
| website | Where Meeting Finder started |
| pages_seen | The pages it walked (joined with ` -> `) |
| youtube_urls_seen | YouTube addresses kept in the saved results (82 rows only; the rest were lost in a scratch-folder wipe) |
| youtube_links_count | How many YouTube links the finder saw |
| already_on_drip_list | `yes` if this gov_id already has a row in `research/youtube_channel_leads.csv` (rtr-business copy, 2026-09-30) |
| drip_list_urls | Those existing drip-list addresses |

| Already on the drip list | Count of 1,595 |
|---|---|
| No: work these | 599 |
| Yes: skip, unless the existing lead is dead | 996 |

## The pass (for the 599)

1. Find the government's own YouTube channel. Look on `website` and `pages_seen`, or use `youtube_urls_seen`.
2. Check that it's the government's own channel, not the county's, a school team's, or a person's. A channel named for another public body goes to that body, not here.
3. Check for meeting videos on the channel.
4. Write one lead per government in the drip list's format: `channel_url,gov_id,government,state,source_wo,kind,verified,note`. Use `source_wo=meeting_finder_group4` and `kind=channel`, or `single_video` or `playlist`. Set `verified=true` only if you saw a meeting video.
5. Record no channel found and no meetings on the channel as findings, each with a reason.

Put the results in `drip_leads_out.csv` here, with a short results table in this README. Push to this branch. Don't merge; the coordinator adds the leads to the rtr-business drip list.
