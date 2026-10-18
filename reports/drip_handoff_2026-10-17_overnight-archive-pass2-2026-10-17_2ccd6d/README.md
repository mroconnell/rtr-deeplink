# Drip handoff 2026-10-17_overnight-archive-pass2-2026-10-17_2ccd6d: 5 leads from rtr-findmeeting run overnight_archive_pass2_2026-10-17

These come from the Find Meeting run `overnight_archive_pass2_2026-10-17` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 5 |
|---|---|---|
| youtube | channel | 3 |
| youtube | playlist | 1 |
| youtube | single_video | 1 |

## Why each lead was suggested (5 of 5 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Neola city, Iowa (us:place:1955560) | https://www.youtube.com/watch?v=qmtYhsslDfw | found on https://www.neola-iowa.com/City Council/; flagged (Jev moment 4: no title evidence): the videos shown with it on the government's page had too few titles to judge |
| Fox Chase city, Kentucky (us:place:2128785) | https://www.youtube.com/c/ZIKAnalytics | found on http://cityoffoxchase.org/: "youtube" under heading "Zik Analytics Customer Reviews"; page "最新大发官网/大发体育平台官网下载~安卓版下载 v7.5.14"; nearby: "Follow us on Social Media Get ZIK Analytics for Mobile" |
| Petersburg city, North Dakota (us:place:3861860) | https://www.youtube.com/channel/UC59F7uJYG8ZbdsCBQDy1nbA | found on https://petersburgnd.com: "Follow on YouTube"; page "SV66 / Đăng Ký + Nạp Đầu Tặng 188K Bet Thủ" |
| Wayne township, Indiana (us:cousub:1800381620) | https://www.youtube.com/@waynetownshiptrustee6341 | found on https://waynetownship.org/employment-training-center/ |
| Mount Carmel city, Illinois (us:place:1750868) | https://www.youtube.com/watch?v=4-N8Ow4-RdU&amp%3Blist=PLqZpFy_oNJ-xqt2dfMXwpyurJl1vdooPK | found on https://www.cityofmtcarmel.com/meetings/recent |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
