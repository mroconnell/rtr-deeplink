# Re-transcription queue (WO-929)

For Ryan and for whoever runs the local Whisper machine (Ol McClaude's
Mac). Plain language on purpose. Read it once; the commands below are all
you need.

## What this queue is

94 pages on the site have only one usable transcript, and it is old
Whisper text with a real defect. "Old" means made before the voice filter
(voice-activity filtering, or VAD) went in on 2026-08-18, or a repair
copy of that text. The defect is in the text itself: 58 pages show the
silence signature ("Thank you." every 30 seconds over a silent stretch),
and 35 show loops of the same words. One shows neither of those (a
repeated line with roll-up overlap). WO-928 found 82 of them
(`BACKLOG_DONE.md`, WO-928). WO-944 (2026-09-21) added 12 more: 11 that
Ryan's full run of the same tool over all 9,976 pages found, and page
724, which the conductor found by hand (its shown text runs 522 minutes
with the silence signature, and its only cleaner hidden version covers
just 74 minutes, so a fresh transcription is the fix). None carries a
warning marker, so the cloud worker will never pick them up on its own.

The queue is `scripts/retranscription_queue.txt`. Its side file is
`scripts/retranscription_queue_meta.csv` (page id, slug, platform, hours,
defect, order, section, route for every line).

| Section | Pages | Audio hours | What it is |
|---|---|---|---|
| PILOT | 5 | 9.1 | Shortest pages with a clear silence signature, three platforms. Run first, by hand, and compare. |
| MAIN | 89 | 311.5 | The rest. Silence-signature pages first, then loops, then the one other. Shorter first inside each group. The last 12 lines are the WO-944 additions, shorter first (page 724 last), in their own group at the end. |
| DRIP-MAC-ONLY | 0 | 0 | YouTube-hosted pages. None of the 94 is YouTube-hosted (checked 2026-09-21), so it is empty. |

Total 94 pages, 320.6 hours of audio. Durations are the video's own
length, read from playlist and file headers on 2026-09-21. No media was
downloaded to build this list.

## How this differs from the tier-3 queue

The tier-3 queue (`scripts/tier3_auto_transcription_queue.txt`) holds
meetings that have video and no transcript at all. A GitHub workflow
advances it on its own. This queue holds pages that already have a
transcript. **Nothing reads, advances, prunes or deduplicates it
automatically.** A person runs it, and a person decides whether the new
text replaces the old. `tests/test_retranscription_queue.py` fails the
build if any script or workflow starts naming this file, if a broad file
pattern could reach it, or if any URL is in both queues.

Merging changes to this queue does not need a deploy. Render only builds
when files under `app/`, `archive/`, `worker/`, `shared_static/`,
`shared_templates/`, `requirements.txt` or `render.yaml` change, and
nothing here is under those paths.

## Two things to know before running

`transcribe_backlog_locally.py --urls-file` ignores `--limit`. It runs
every URL in the file. So "the next five" means a file with five lines.
`scripts/retranscription_queue_slice.py` makes that file.

A push without `--promote` does not change what readers see. The new text
is stored as a new hidden version on the page and the old text stays
shown, because the page already has a transcript with a language (this is
`_is_real_improvement()` in `archive/db/crud.py`). Only `--promote`, or a
call to the promote endpoint, switches the shown version. The old version
is never deleted.

## One-time setup on the machine

From the repo root, on an up-to-date `main`:

```
git pull
.venv/bin/python -m pip install faster-whisper     # once
```

Python 3.12, `ffmpeg` and `ffprobe` on the path, and `.env` holding
`ARCHIVE_BASE_URL` and `ARCHIVE_INGEST_TOKEN`. The script checks for the
token and stops if it is missing. Check for an old partial run first:

```
ls local_transcription_backups/partial 2>/dev/null
```

A leftover checkpoint from an older run holds text made by an older
setup. Use `--no-resume` on every command below so no old chunk is reused.

## Step 1: measure the speed (optional, harmless)

A dry run transcribes but pushes nothing. Use the shortest page in the
queue (a 17-minute Swagit meeting from the loop group). It tells you the
real speed of this machine:

```
echo "https://worcestercountymd.new.swagit.com/videos/355852" > /tmp/retranscribe_timing.txt
caffeinate -s .venv/bin/python scripts/transcribe_backlog_locally.py \
  --urls-file /tmp/retranscribe_timing.txt --dry-run --no-resume \
  --cpu-threads 2 --chunk-cooldown-seconds 30
```

Read the "RUN COMPLETE ... in N s" line. Divide the meeting's minutes
(about 17) by N/60 to get how many times faster than real time this
machine runs. The cooldown seconds are part of that number, so keep them
the same for the real run. Write the result down (see "How long it will
take").

## Step 2: the pilot (5 pages, no --promote)

```
.venv/bin/python scripts/retranscription_queue_slice.py --section PILOT > /tmp/retranscribe_pilot.txt
caffeinate -s .venv/bin/python scripts/transcribe_backlog_locally.py \
  --urls-file /tmp/retranscribe_pilot.txt --no-resume \
  --cpu-threads 2 --chunk-cooldown-seconds 30
```

Do not add `--promote`. Each page gets a new hidden version. The run
prints one line per page and a final "RUN COMPLETE" tally. A page shown as
"skipped" with a reason did not finish and pushed nothing; a page shown
as "failed" pushed nothing. Both can be run again.

Thermal flags: `--cpu-threads 2` caps the CPU, `--chunk-cooldown-seconds
30` rests 30 seconds after every 15-minute chunk (5 minutes for Granicus)
and waits longer if macOS is already throttling. `caffeinate -s` stops
sleep on AC power. Drop the flags only if the machine has thermal
headroom.

Pause and resume: press Ctrl-C between pages, or let it finish the page in
hand. A page that stops partway keeps its finished chunks in
`local_transcription_backups/partial`. Run the same command again without
`--no-resume` to continue that page; keep `--no-resume` for a fresh start
only. A finished transcript that failed to push is saved in
`local_transcription_backups/` (the run says where); nothing is lost.

## Step 3: review, page by page (a person decides)

```
.venv/bin/python scripts/retranscription_review.py --section PILOT --env /path/to/.env
```

For each page it prints the old shown version and the new hidden version
side by side, using the WO-928 signals (silence signature, loops, the
hallucination detector, roll-up, coarse cues), plus a link to the new
version's SRT. It judges the text. It never uses cue counts or word
counts: the old text invents words over silence, and the filtered text has
fewer words and is not worse for it. It reads the site (about two reads
per page, one per second) and never changes anything.

What "good" means, in the same words as the review's hint column:

| Hint | What it means | What to do |
|---|---|---|
| new-clean | The new text has no defect signal and reaches the old text's last cue (within 5%). | Read a few minutes of it. If it reads like speech, promote it. |
| new-shorter | No defect signal, but it ends more than 5% before the old text. | Open the SRT. Check the end of the meeting is really there before promoting. |
| new-still-flagged | The new text still shows a defect signal. | Do not promote by default. Loops come from the audio for some pages; note it in the meta file as `kept-old`. |
| no-new-version | Nothing new is stored (the run did not push, or it failed). | Run that page again. |

Also open the old and new SRT for at least the first pilot page and read
the stretch where the old one shows the silence signature:
`https://redtaperecordings.com/m/<slug>/transcript.srt?version=<id>`
(`<id>` is the version id the review prints). Good means: no repeated
line every 30 seconds, no long run of the same words, and the speech in
the new text matches the video.

Promote a version you have judged good (the conductor does this with the
promote endpoint; the operator can instead re-run that one page with
`--promote` once the pilot is judged good, which transcribes it again):

```
POST /internal/transcript-version/promote   {"slug": "<slug>", "version_id": <new id>}
```

Stop after the pilot. Ryan reads the review and decides whether the main
queue is worth running, and whether to run it with `--promote`.

## Step 4: the main queue, in batches

```
.venv/bin/python scripts/retranscription_queue_slice.py --section MAIN --count 10 > /tmp/retranscribe_next10.txt
caffeinate -s .venv/bin/python scripts/transcribe_backlog_locally.py \
  --urls-file /tmp/retranscribe_next10.txt --no-resume \
  --cpu-threads 2 --chunk-cooldown-seconds 30
.venv/bin/python scripts/retranscription_review.py --section MAIN --count 10 --env /path/to/.env
```

Only after the pilot is judged good, and only if Ryan says so, add
`--promote` to the transcribe command. Without it, every page waits for
review the same way the pilot pages did. Ten pages is a suggestion, not a
rule: about 25 hours of audio per batch is a comfortable overnight size.

`retranscription_queue_slice.py --status` shows how many pages are
finished in each section.

## How finished pages leave the queue

Nothing is deleted. After a page is decided, append one line to the end of
`scripts/retranscription_queue_meta.csv`:

```
# done,<page_id>,<YYYY-MM-DD>,<new_version_id>,<promoted|kept-old|failed>
```

`promoted` means the new text is now shown. `kept-old` means a person
judged the new text no better and left the old one. Both take the page out
of the next slice. `failed` records an attempt and leaves the page in
line. Commit that line in a normal pull request. The test checks that
each record is well formed and names a page in the queue.

## How long it will take

The speed of this machine's Whisper run has not been measured. It cannot
be from the cloud: the only recorded figure is the cloud worker's
(`BACKLOG_DONE.md`, the tier-3 feed-rate entry of 2026-08-21: about 5
times real time with the `tiny` model on Render, measured once and not
re-measured since).
The local machine uses a bigger model by
default, chosen from its RAM (`_pick_default_model_size()`), plus the
cooldown above, so that figure does not carry over. Step 1 gives the real
number.

Then the arithmetic is fixed. 254.3 hours of audio divided by the
measured speed:

| If this machine runs at | 320.6 hours of audio takes | The pilot (9.1 h) takes |
|---|---|---|
| 1 times real time | 320.6 hours | 9.1 hours |
| 2 times real time | 160.3 hours | 4.6 hours |
| 4 times real time | 80.2 hours | 2.3 hours |

## Cannot re-transcribe

None. All 94 pages were resolved fresh through the site's own adapters on
2026-09-21 and every one returned a playable video with a header-read
duration. If a page fails later (a removed video, a 404), do not remove
its line. Record it with a `# done,...,failed` line and tell the
conductor.

## Cautions

The push re-reads the meeting page and refreshes the page's stored fields
(title, date, video link), like any re-check does. Look at the page after
a run. Two slugs are stale names for the wrong body and were left alone:
page 775 (`port-colborne-resolution-...`, really Brockton, ON) and page
893 (`peterborough-attachments-...`, really Uxbridge, ON). Their source
URL, video and registry id all agree with Brockton and Uxbridge. Fixing a
slug is a separate decision.

Never run this on a YouTube-hosted page from any machine except the drip
Mac, and never from the office connection while the drip runs there. The
DRIP-MAC-ONLY section exists for that case and is empty today.
