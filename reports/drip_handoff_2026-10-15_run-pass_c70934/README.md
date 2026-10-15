# Drip handoff 2026-10-15_run-pass_c70934: 3 leads from rtr-findmeeting run run_pass

These come from the Find Meeting run `run_pass` (rtr-findmeeting `apply`). For each government below, the run found YouTube or Vimeo
links on the government's own website. No YouTube request was made.

Every government here was checked first: no Archive page under 2 years old, and the address is not already on the drip list
(rtr-business `research/youtube_channel_leads.csv`), in the queue or in the queue history. Template addresses and addresses seen in
two or more states were left out. The same rows were added to the rtr-business drip list with `verified=false`.

## The file

`leads.csv`, one row per address. Same columns as the earlier handoffs.

| Lane | Kind | Count of 3 |
|---|---|---|
| youtube | channel | 3 |

## Why each lead was suggested (3 of 3 have the page's own words)

What the government's own page said around the link (`found_context` in `leads.csv`). Rows from runs before 2026-10-05 have none.

| Government | Address | Found on the page |
|---|---|---|
| Oelwein Community School District, Iowa (us:sd:1921630) | https://www.youtube.com/@champthehusky5781/streams | found on https://www.oelweinschools.com/: "Live Streams of Board Meetings" under heading "Quick Links"; page "Home - Oelwein Community School District"; nearby: "Live Streams of Board Meetings" |
| Monomoy Regional School District, Massachusetts (us:sd:2500544) | https://www.youtube.com/user/MRSDTV1/playlists | found on https://www.monomoy.edu/school-committee/school-committee-meeting-agendas-and-minutes/monomoy-regional-school-committee-meetings-youtube-channel |
| West Bend School District, Wisconsin (us:sd:5516290) | https://www.youtube.com/@WBSDcommsdept | found on https://www.wbsd-schools.org/stay-connected/social-media |

## The pass

Verify every row skeptically: add it only if the channel or video shows clear meetings of this government's board or school district body. Columbus City Schools OH is the good example: an explainer video, on a channel that also carries the board's meetings.

1. Check that the channel or video is the government's own public body, not a school, a county, a tourism office or a person.
2. Check for meeting videos of that body.
3. Verify through the drip's normal `leads` lane. Record "no channel" or "no meetings" as findings with a reason.
4. A row whose note says "do not walk channel": file the single video only; never walk its channel.

Push results to this branch under this folder. Don't merge; the coordinator folds them into the rtr-business drip list.
