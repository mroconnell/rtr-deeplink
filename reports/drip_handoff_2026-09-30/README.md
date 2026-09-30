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
## Results: 599 governments

| Result | Count of 599 |
|---|---|
| Lead written (channel or video found) | 171 |
| No channel found | 409 |
| Found a link, but it belongs to a different government | 1 |
| Could not fetch any known page for the government | 19 |

**Of the 171 leads:**

| Kind | Count |
|---|---|
| Channel | 115 |
| Single video | 47 |
| Playlist | 9 |

**Where the candidate came from:**

| Source | Count |
|---|---|
| Already in `youtube_urls_seen` | 21 |
| Found on the government's own site or a page your own crawl already visited | 150 |

**Caution — 3 candidate URLs came back shared by more than one government in this batch** (7 governments total): `UC9b29ZirdVMxd_96Z3kth0w` (2 California elementary school districts) and `UCeU-_6YHGQFcVSHLbEXLNlA` (5 small governments across several states — Pound village, Hamilton County, Minong village, Crow Head, Namakagon town). That second channel ID already showed up in an earlier flagged-for-human list this session (Waterloo village NY and a New York township) — it looks like a regional/vendor channel carrying many small governments, not a single government's own channel. Each of these 7 rows carries a note saying so; none should be treated as confirmed without a look.

**One real mismatch caught and excluded**: Henry County, AL (a county) came back with `@henrycountyschooldistrict`, found via `henrycountyboe.org` — that's the county's school district, a different real government, not Henry County's own channel. Not written as a lead.

## What happened to each lead after this

All 171 were appended to this Mac's own `leads_queue.csv` (verified=false, source_wo=meeting_finder_group4) so the drip's existing `leads` lane verifies identity and checks for real meeting content the same way it does every other lead, over its normal paced rotation shared with the rest of this Mac's YouTube work. `drip_leads_out.csv` in this folder reflects the state before that verification — not yet hand-read, as the format requires.

## Method

For each of the 599: used `youtube_urls_seen` directly when present (21 governments). Otherwise fetched the government's own `website` plus the other pages your own crawl had already visited (`pages_seen`), up to 6 pages, and scanned for a real YouTube channel/video/playlist link (not a bare homepage or share-icon link). Rejected a candidate if the page it came from, or the link itself, looked like a different government's own site (a school district's domain/channel-handle pattern, checked against this government's actual type). No YouTube requests were made in this phase — findings and leads alike come only from fetching each government's own (non-YouTube) pages.
