# YouTube drip runbook

For the person (or Claude session) running `scripts/youtube_drip.py` on
the dedicated Mac. Plain language on purpose. Read it once; then the
commands below are all you need.

## What it does

YouTube blocks requests from our Render servers, so every YouTube job
runs from a home or office internet connection. This one process does
all three jobs, slowly and steadily, so YouTube never sees a burst:

| Lane | What it works on | What it does | Pace |
|---|---|---|---|
| captions | pages on the site waiting for a transcript | asks YouTube for the video's captions and puts them on the page; if the channel disabled captions, marks the page so nobody asks again | one page every 3–4 minutes |
| feed | the YouTube lines in `scripts/tier3_auto_transcription_queue.txt` | turns each into a site page (same checks as the GitHub feed), then the captions lane fetches its captions next | same budget |
| audio | pages marked "captions disabled" | downloads the audio and transcribes it with Whisper on this Mac | at most 3 downloads a day (raise only after a week without a block) |

Every YouTube request comes out of one shared budget: about one every
three to four minutes. That pace ran five hours on 2026-09-11 with no
block, where the old once-a-day burst was blocked after 9–38 pages.

When YouTube does block ("too many requests", "sign in to confirm you're
not a bot"), the process pauses everything for 15 minutes, then 30, 1
hour, 2 hours, 4 hours, and tries again. A success resets that ladder.
This is routine. Do nothing.

Any other error (the Archive not answering for a moment, say) is logged
as `tick failed (N in a row)` and the process tries again five minutes
later. It does not exit. This is also routine.

## Rules

1. **One drip per internet connection.** Two Macs on the same office
   connection share one YouTube budget. If this one is running, the other
   Mac must not run the daily caption job or any YouTube script.
2. **Don't change the pacing.** Faster is how the daily job got blocked
   every morning. If it seems slow, that is the design.
3. **Pull `main` once a day** so the feed lane sees new queue lines, and
   run `advance` (below) so the queue file stays honest.
4. **The audio lane shares the CPU** with any manual Whisper run on this
   Mac (a tier-3 batch never touches YouTube, so that is the only
   interaction). Start the drip with `--lanes captions,feed` during a big
   manual run and add `audio` back after — Ctrl-C, restart with the
   default lanes. `--seed-audio-from-site` is safe with a lane subset: it
   only fills the audio queue in the state file for later. Running all
   three lanes alongside a batch breaks nothing; both Whisper jobs just
   run slower.

## Start it

From a checkout of rtr-deeplink on `main`, with the repo's `.env` in place:

```bash
caffeinate -i .venv/bin/python scripts/youtube_drip.py --seed-audio-from-site
```

`caffeinate -i` stops the Mac idle-sleeping; keep the lid open or use
clamshell mode with power — a closed lid still sleeps and the drip
crawls at ~1 page an hour. `--seed-audio-from-site` (first start only)
loads every page already marked captions-disabled into the audio lane.

It keeps its memory in `~/.rtr/youtube_drip/`:

| File | What it is |
|---|---|
| `drip.log` | every page, every block, timestamped |
| `state.json` | what is done, what is queued, current block; survives restarts |
| `daily_status.csv` | one line per day: captions ingested / marked / failed, fed ok / skipped / needing identity review, dead videos, audio done / failed, blocks |
| `fed_pages.csv` | one row per page the feed lane created, with the government the Archive keyed it to and whether a human should check it |
| `dead_videos.csv` | one row per removed video with the channel's newest streams, for a human to pick a replacement meeting from |
| `lock` | stops a second copy starting on this Mac |

Stop it with Ctrl-C; start it again the same way. It resumes.

## Once a day

```bash
git pull
.venv/bin/python scripts/youtube_drip.py advance
```

`advance` removes the queue lines the feed lane has already handled,
tells the Archive the new remaining count, and folds the feed lane's
probe rows (piled up locally all day — see below) into the tracked
`scripts/tier3_auto_transcription_queue_probe.csv`. Commit **both**
files (`git add scripts/tier3_auto_transcription_queue.txt
scripts/tier3_auto_transcription_queue_probe.csv`) on a branch and open
a PR titled "Advance tier 3 auto-transcription queue (YouTube drip)" —
the same thing the GitHub feed does for the other platforms. If the PR
conflicts, take the union of both sides' lines (see
`docs/COVERAGE_HANDOVER.md` §5.6 for the one exception — a deliberately
*deleted* line stays deleted).

**WO-248 (2026-09-12):** the feed lane's probe rows used to go straight
to the tracked CSV above, live, all day — every one of those writes made
the working tree dirty hours before this once-a-day commit, and `main`
kept growing the same file through merged sweeps in the meantime, so
`git pull` conflicted on it every single day (append-only, nothing was
ever lost, but it took a hand-resolved union each time). They now go to
a local, gitignored buffer instead
(`scripts/tier3_auto_transcription_queue_probe.local.csv`), and `advance`
folds that buffer into the tracked file once, right here, then empties
it. **After this lands, `git pull` on this Mac once more; every pull
after that is clean.**

## Identity: what the drip does not do

The drip never decides which government a video belongs to, never
writes a pin, never judges whether a video is a real meeting, and never
picks a replacement for a dead one. The Archive keys each fed page with whatever pins are
deployed; pages it could not key with evidence are listed with
`needs_review=yes` in `~/.rtr/youtube_drip/fed_pages.csv`. Someone
reviews that file and writes pins — how, in
`docs/YOUTUBE_DRIP_IDENTITY_REVIEW.md`.

## What healthy looks like

`daily_status.csv` shows 200–400 captions or feed actions a day, a few
blocks or none, and no day with zero actions while there was work.

## When to tell Ryan

- A block that lasts more than 24 hours (the log shows repeated
  `BLOCK ... sleeping 240 min` with nothing between).
- The audio lane blocked twice in one week — YouTube's tolerance for
  downloads is still being measured, and that number is the measurement.
- `tick failed (12 in a row)` or higher — an hour of the same error is
  no longer a blip. The log line above it names the error.
- `another youtube_drip is already running` when you know it isn't:
  delete `~/.rtr/youtube_drip/lock` only after `pgrep -f youtube_drip`
  shows nothing.

## Options

```
--lanes captions,feed,audio   run a subset
--spacing-seconds 180         seconds between YouTube requests (do not lower)
--audio-per-day 3             audio downloads per day
--model-size small            Whisper model for the audio lane (default: sized from RAM)
--dry-run                     do everything except write to the site
--once                        one step, then exit (for a quick check)
```
