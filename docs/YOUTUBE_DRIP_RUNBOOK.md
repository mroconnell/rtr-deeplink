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
| feed | the YouTube lines in `scripts/tier3_auto_transcription_queue.txt` (the GitHub feed leaves these alone, WO-1064) | turns each into a site page (same checks as the GitHub feed), then the captions lane fetches its captions next | same budget |
| audio | pages marked "captions disabled" | downloads the audio and transcribes it with Whisper on this Mac | at most 3 downloads a day (raise only after a week without a block) |
| vimeo | pages on the site waiting for a transcript, `video_format=vimeo` (WO-1147, 2026-09-27, **opt-in — not in the default `--lanes`**) | resolves the video locally through the Vimeo adapter, the same way a real browser would, and either puts the real captions on the page or records a permanent "no captions" marker | same shared spacing as the other lanes — **not** the same shared YouTube budget (see below) |
| direct | the non-YouTube, non-Vimeo lines in `scripts/tier3_auto_transcription_queue.txt` (WO-1168, 2026-09-29, **opt-in — not in the default `--lanes`**) | turns each into a site page the same way the `feed` lane does, straight from this Mac's office connection — only while the cloud workers have fewer than `--direct-low-water` (default 10) non-YouTube, non-Vimeo pages still waiting for a transcript | same shared budget as captions/feed/audio (a fed page can itself embed YouTube) |

Every YouTube request comes out of one shared budget: about one every
three to four minutes. That pace ran five hours on 2026-09-11 with no
block, where the old once-a-day burst was blocked after 9–38 pages.

**Why there's a `vimeo` lane here at all, and why it's different from the
other three.** As of 2026-09-26, Render's own cloud IP gets a challenge
page on every Vimeo caption fetch — the same structural problem YouTube
has always had for this service (see `BACKLOG.md`'s "Vimeo blocks Render"
entry). `app/platforms/vimeo.py`'s resolver still works fine from an
ordinary residential/office IP, so it needs the same "fetch here, push to
the Archive" treatment. But Vimeo is a **completely different host**, not
part of YouTube's own request budget — there is no shared rate-limit
reason to pace it jointly with the three lanes above. It's bundled into
this same process purely for **operational convenience**: one always-on
Mac, one tick loop, one state file, one lock file — not because Vimeo
shares YouTube's block sensitivity. It reuses the same
`--spacing-seconds` every other lane uses (no separate pacing knob) and
has its own independent block ladder, entirely separate from the
YouTube-family one. **It is not in the default `--lanes` value** — add it
explicitly the first time it's wanted:
`--lanes captions,feed,audio,vimeo`.

**Why there's a `direct` lane here at all.** As of 2026-09-29, most of
`scripts/tier3_auto_transcription_queue.txt` is Granicus, Cablecast and
similar hosts that refuse GitHub Actions' own IP addresses outright (HTTP
403), even with the correct Referer/User-Agent — confirmed live: the
GitHub workflow's last real run ingested 0 of 12 lines. That workflow was
the only thing feeding new non-YouTube meetings onto the site, so both
cloud transcription workers went idle (0 active jobs, 1 finished in a
day) with real work still sitting in the queue. The same push, run from
this Mac's office connection, works — the `direct` lane is that push,
run continuously instead of once every 6 hours, and demand-gated
(`--direct-low-water`, default 10) so it tops the queue up rather than
feeding the whole remainder in one burst. It is **opt-in — add it
explicitly**: `--lanes captions,feed,audio,direct` (or add `vimeo` too if
that's also running: `--lanes captions,feed,audio,vimeo,direct`). Unlike
`vimeo`, it shares the YouTube-family spacing and block ladder — a
Granicus or CivicClerk page can itself embed a YouTube video, so a
`direct` push can still trip a YouTube block. The GitHub feed workflow
(`.github/workflows/feed-tier3-transcription.yml`) is retired in favor of
this lane (see its own header comment) but stays in the repo, disabled,
rather than deleted.

**A line the GitHub feed keeps isn't always this Mac's job.** The feed
tags a kept line in `tier3_auto_transcription_queue_feed_log.csv` two
ways: `YOUTUBE` (this Mac's feed lane, above) and, since WO-1143
(2026-09-27), `NOT-REACHABLE-FROM-GITHUB` for a Granicus/Cablecast/Swagit
line that 403s to GitHub's IP but works fine from an ordinary connection
(no YouTube involved at all). The drip doesn't claim those — they just
sit in the queue and get retried by GitHub each cycle. If one needs to
become a page sooner, run `scripts/feed_tier3_auto_transcription.py`
by hand from any non-GitHub-Actions machine (this Mac included) — the
same code succeeds there because it isn't GitHub's IP doing the asking.

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
5. **A script run on any other Mac must make zero YouTube requests,
   including the indirect ones.** Rule 1 says "any YouTube script"; the
   easy ones to miss are a CivicClerk, Legistar, CivicPlus, Granicus or
   PrimeGov event whose media is a YouTube embed (the adapter fetches
   captions), WO-144's queue probe (it calls yt-dlp for metadata), and
   WO-134's title check (YouTube's oEmbed). None of them look like a
   YouTube fetch in the calling script. WO-913 (2026-09-20) made about two
   such requests from the wrong Mac through a normal ingest of a
   CivicClerk find (Toledo OR). Any wrapper that resolves, probes or
   ingests off the drip Mac calls `scripts/youtube_fetch_guard.install()`
   before anything else: after that, any lookup of a YouTube hostname
   raises instead of connecting, and `youtube_fetch_guard.REFUSED` lists
   which hosts were refused so the caller can hand that row to the drip
   lane as a lead (`research/youtube_channel_leads.csv`) instead of losing
   it. `scripts/wo912_wo913_ingest_confirmed.py` is the worked example.
   A separate browser process (Playwright) is not covered by the guard;
   a script that drives one must refuse YouTube URLs itself. **This rule
   is YouTube-only.** Vimeo is not blocked the way YouTube is from a
   normal office/residential connection — a script run anywhere else can
   still make Vimeo requests for video/metadata. The one place Vimeo
   *is* blocked today is Render's own service specifically fetching
   Vimeo **captions** (see the "vimeo" lane row above and `BACKLOG.md`'s
   "Vimeo blocks Render" entry) — that's why the vimeo lane exists on
   this Mac at all, not because Vimeo shares rule 5's YouTube concern.

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
| `state.json` | what is done, what is queued, current block; survives restarts — now also holds the vimeo lane's own `vimeo_done`/`vimeo_blocked_until`/`vimeo_block_level` keys, kept entirely separate from the YouTube-family ones |
| `daily_status.csv` | one line per day: captions ingested / marked / failed, fed ok / skipped / needing identity review, dead videos, audio done / failed, blocks, and (WO-1147) vimeo ingested / marked / failed / blocks in their own columns — a Vimeo challenge bumps `vimeo_blocks`, never the shared `blocks` column |
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

**WO-1016 (2026-09-23): the queue file's line format.** A line is
`URL`, `URL<TAB>SOURCE_URL`, or, as of this WO, `URL<TAB>SOURCE_URL
<TAB>GOV_ID` (SOURCE_URL may be blank when only GOV_ID is known:
`URL\t\tGOV_ID`). `app.platforms.queue_probe.parse_queue_line()` is the
one place this shape is parsed — `scripts/feed_tier3_auto_
transcription.py`'s `_parse_queue_line()` and this script's own three
call sites of that name all delegate to it. Writers that know a
government emit the 3rd field since 2026-09-23
(`queue_probe.EMIT_GOV_ID_IN_QUEUE_LINES = True`), flipped only after
this Mac confirmed it runs the tolerant readers.

**This Mac runs the drip from its own worktree, not its main checkout:
`~/rtr-deeplink-drip-worktree`, branch `drip-local` (confirmed
2026-09-23).** Pulling `main` in the main checkout does not update the
drip. To update the drip, bring that worktree to the current `main`
commit, then restart the drip. On 2026-09-23 it was 136 commits behind,
and Ctrl-C (SIGINT) did not stop the drip; SIGTERM did. No diagnosis yet
— note it if it happens again.

## Backfill sweeps (occasional, not part of the drip loop)

`scripts/backfill_archived_pages.py --platform youtube --missing-channel-only`
(WO-295) also needs to run on this Mac, but it is a separate, one-off
script, not part of the three lanes above. It re-resolves archived
YouTube pages whose `video_channel` is still NULL (~1,676 as of
2026-09-12, after `scripts/backfill_video_channel.py` — see below —
filled the rest for free), one real YouTube call per page, paced by its
own `--delay`. It shares this Mac's one YouTube budget with the drip
(Rule 1 above), so stop the drip (Ctrl-C) or drop to
`--lanes captions,feed` first — the same accommodation Rule 4 describes
for a manual Whisper run.

Run `scripts/backfill_video_channel.py --apply` first, from the
Archive's Render shell (not this Mac — it makes no YouTube call and is a
plain DB write, so it belongs where every other DB-only backfill runs,
per CLAUDE.md). That fills most of the NULL rows from per-video records
already in the repo, so the drip-Mac sweep below only touches the
genuine remainder instead of all ~3,464 affected pages.

```bash
# dry run first, on a small slice
.venv/bin/python scripts/backfill_archived_pages.py --platform youtube --missing-channel-only --dry-run --limit 20
# the real run
.venv/bin/python scripts/backfill_archived_pages.py --platform youtube --missing-channel-only --delay 3
```

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

## One bad item never holds the drip (WO-1175)

A lane that raises on the same item twice, or is blocked on it three times,
pushes that item to the back of its queue: it is skipped for 4 hours, then
8, 16 and so on up to 48. The other lanes keep their turns in the meantime.
Each push-back writes one line to `~/.rtr/youtube_drip/alerts.log`, logs an
`!!! DRIP ALERT` at ERROR level and raises a macOS notification. A failure
before any item is picked (the Archive down) still pauses the whole drip
for 5 minutes, as before. The strike counts live in `state.json`
(`strikes`, `deferred_until`); a success clears an item's strikes.

The drip also puts its `drip.log` handler back if a library removes it. The
audio lane's import of `transcribe_backlog_locally.py` does exactly that
(`logging.basicConfig(force=True)`); on 2026-10-03 it left the drip working
but silent for 11 hours. That event now raises an alert too.

**Start it with its output captured**, not sent to `/dev/null`:
`... youtube_drip.py --lanes ... > ~/.rtr/youtube_drip/stdout.log 2>&1`.

## When to tell Ryan

- Any new line in `alerts.log` that you cannot explain.

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
--lanes captions,feed,audio,vimeo,direct   run a subset (vimeo and direct are opt-in, not in the default)
--spacing-seconds 180                      seconds between requests (do not lower)
--audio-per-day 3                          audio downloads per day
--direct-low-water 10                      direct lane: feed while fewer than this many non-YouTube/non-Vimeo pages are waiting
--model-size small                         Whisper model for the audio lane (default: sized from RAM)
--dry-run                                  do everything except write to the site
--once                                     one step, then exit (for a quick check)
```
