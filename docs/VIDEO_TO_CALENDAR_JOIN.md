# Video-to-calendar join

Shelved 2026-09-10 by Ryan as a future project. Piloted once (WO-158),
worked, modest yield, some risk of off-mission video. This document is
the record, so the next person can pick it up without redoing the pilot.

## What it is

Many governments publish meeting video somewhere that never links back
to the meeting: a YouTube channel, a Vimeo account, a playlist, a video
RSS feed. Their website has a meeting calendar with body names and
dates, but no link from a meeting to its recording. The join takes the
government's video source and its own calendar and matches them by body
name and date. The site stays the source of the government, the body,
the date and the agenda. The video source supplies the recording.

Wyoming, OH is the case that started it. Its site is CivicPlus with a
meetings calendar feed. Its home page links a YouTube channel. The
channel holds "Copy of Wyoming City Council Meeting 11/17/25", 61
minutes long. Nothing on the site links to it.

## Why it matters

The AgendaCenter audit (WO-137) found that of 30 CivicPlus governments
marked "no video found", 17 had an active video channel and no
per-meeting link. That is the largest single reason a government with
video is still missing from the Archive. Every other method reads what
the site links; this one reads what the site does not.

## The pilot, WO-158

40 CivicPlus governments marked "no video found", one per state. For
each: home page, then any YouTube channel link, then the channel's
uploads by metadata only, then the site's AgendaCenter calendar, then
the join.

| Result | Count of 40 |
|---|---|
| Linked a video channel | 12 |
| No channel link | 27 |
| Site unreachable | 1 |
| Channel and calendar both present, real match | 2 |
| Channel and calendar both present, no match | 10 |

The two matches: Natchez, MS (Board of Aldermen, 87 minutes) and
Webster Groves, MO (Historic Preservation Commission, 67 minutes). Both
confirmed by hand against the calendar row and the video title.

Wyoming, OH itself did not match: its calendar lists 38 meetings across
12 boards, but its one meeting video is from November 2025, older than
the calendar window the pilot used. The video is real; the window was
the limit.

Full write-up: `rtr-business/research/ENUMERATION_METHODS.md` §193.
Script: `rtr-business/research/wo158_channel_calendar_join.py`. Result
files: `rtr-business/research/wo158_*.csv` (candidates, home pages,
channel videos, calendar meetings, join results).

## The rules that make it safe

- A match needs the body name in the video title (or a clear alias,
  "Council" for City Council) and a date within one day of a calendar
  meeting. The body-name check is what protects the join. One channel
  in the pilot was mostly promotional videos with date-shaped titles.
- Ties decline. Two videos for one meeting, or one video matching two
  meetings, is not a match. The pilot's join reported a match count
  instead; the shipped channel matcher in
  `app/platforms/youtube_channel.py` already declines, and a real run
  must do the same.
- The nine-minute floor from the queue rule applies.
- The calendar window must reach back as far as the video source does,
  or a real recording is missed (the Wyoming case).
- Video is metadata only until the match is confirmed: never download
  or fetch captions to decide a match. YouTube blocked this Mac's
  address for both on 2026-09-09.

## Known failure shapes

- The calendar omits the body the channel films. Le Mars, IA has clearly
  labeled council videos and a calendar that exposes only Planning and
  Zoning and two other boards.
- A channel is shared across bodies or governments, or is a department's
  channel (a fire department's training videos under a city's name).
- Titles carry no date, or a date in a format the title parser does not
  know. rtr-discovery's `youtube_channel.py` parses dates from titles
  and is the parser to reuse.
- The source is not a channel: a playlist, a Vimeo showcase, a video
  RSS feed. The join is the same; the listing step differs per source.

## What running it at scale would take

- A calendar reader per platform, not only CivicPlus AgendaCenter: the
  CivicPlus calendar feed (`RSSFeed.aspx?ModID=`), Granicus's video feed,
  CivicClerk's events, and the generic feed a home page advertises.
- The channel listing promoted out of a scratch script, with the strict
  tie-break, reusing rtr-discovery's enumerator.
- A per-source listing for playlists, Vimeo accounts and video feeds.
- Results written as candidates for a person to confirm first, then
  ingested through the normal pipeline with the government's gov id
  passed in, so the page is keyed to the government and not to the
  video host.

Expected yield from the pilot: about 5% of "no video found" CivicPlus
governments, roughly 35 to 40 across that bucket, before other
platforms and before widening the calendar window.

## Where this is pointed to

`BACKLOG.md` (Parked deliberately), `README.md` (Known limitations),
`docs/COVERAGE_HANDOVER.md`, `docs/BREADTH_SWEEP_BRIEF.md`, rtr-discovery's
`README.md` at the YouTube channel enumerator, and the top of
`ENUMERATION_METHODS.md` §193 in rtr-business.
