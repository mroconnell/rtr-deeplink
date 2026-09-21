# Backlog phases and deliverables

Written 2026-09-21 (WO-930), from `origin/main` at commit `2c0ab6a` (PR #1280),
then corrected the same day for later PRs (#1281, #1282) and the conductor's review.
It turns `BACKLOG.md` into an ordered plan: what to do first, what each step
delivers, and what waits on Ryan.

`BACKLOG.md` is the record of what is open. This file is the order to work
in. It does not replace the backlog and does not edit any entry. When a
step ships, update the Status column here and move the finished entries to
`BACKLOG_DONE.md`, as `CLAUDE.md` says.

## Why this exists

`BACKLOG.md` is now 8,240 lines and about 390 open entries. Nobody can read
it end to end, so it was hard to say what to do first.

Ryan set the ordering rule on 2026-09-21: **fix what readers see wrong
first.** He also asked for two tracks. Track A is data, coverage, trust and
reliability. Track B is the product roadmap, where each step waits on a
decision from him.

## Terms

- **WO** is a numbered work order. One WO is one PR-sized piece of work.
- **gov_id** is the stable id we file each government under.
- **Tier-3** is the queue of meetings waiting for our own transcription.
- A **sweep** is a script that checks many governments in one run.
- An **identity gate** is a check that a page really belongs to the
  government it is filed under.
- The **registry** is `rtr-business/research/jurisdiction_coverage.csv`.

## Result: the phases

Counts are rounded to the nearest 5 and come from reading each section,
not from exact tagging. Phase 0 touches entries that also sit in other
phases, so the column adds to a little over the file's 392.

| Phase | Goal | Work orders | Entries (about) | Needs from Ryan | Status |
|---|---|---|---|---|---|
| 0 | Tidy the backlog so the rest is trustworthy | WO-931 | 20 | Nothing | Not started |
| 1 | Stop and repair wrong content readers can see | WO-932 to WO-935 | 55 | 5 quick page decisions, one deploy, then a yes or no on an Archive check | Not started |
| 2 | Stop the pipeline wasting effort or failing silently | WO-936 to WO-939 | 80 | One deploy | Not started |
| 3 | Fix the registry and identity foundations | WO-940, then numbers when it starts | 100 | A pin-rules design call | Not started |
| 4 | Grow coverage on the fixed base | Numbers when it starts | 95 | The tier-3 freshness cutoff | Not started |
| 5 | Improve what the pages say | Numbers when it starts | 10 | Nothing until Phase 4 is done | Not started |

WO-930 is this plan. The conductor reserved WO-931 to WO-940 for the
deliverables. Later phases get numbers from the conductor when they
start, so two agents never claim the same one.

## Cautions

- **Entries decay.** Only a handful were re-derived for this plan. Phase
  membership comes from what each entry is about. Every WO starts by
  re-deriving its own entries against the code before building anything.
  In the sample checked, about 20 entries were stale, duplicated or already
  done. Most entries were not checked, so the real number is probably
  higher.
- **Merging ships nothing.** All four services deploy by hand. Code on
  `main` is not live until Ryan deploys. Each phase ends at a deploy
  checkpoint (below).
- **GitHub Actions minutes are short.** The 2026-09-21 inbox triage (PR
  #1281) reports that the account had used 90% of its 2,000 included
  minutes by 2026-09-20, with the reset on 2026-10-01. Every PR, and every
  push to it, runs the full test workflow, and the queue-advance workflows
  run every 4 to 6 hours on top. This plan proposes about ten PRs. That
  figure comes from an unattended report and is not verified here, because
  the usage dashboard needs a login. Before a wave, check the usage. Merge
  PRs that touch the same files as one PR, and avoid extra pushes.
- **Do not start Phase 4 early.** If growth sweeps run before the Phase 1
  gates are live, they create new wrong pages.

## Recommendation

1. Start Phase 0 and Phase 1 together. WO-931 is small and runs beside the
   rest.
2. Run WO-932, WO-933 and WO-935 in parallel as the first wave.
3. Ask Ryan for one deploy when that wave merges. Then run WO-934.
4. Batch the merges. Say plainly which merged code is not yet live.
5. Check the GitHub Actions minutes before launching the first wave (see
   Cautions). If they are tight, stagger the wave rather than open all
   the PRs at once.

## How to find an entry

Each entry below is named by the first words of its title, in quotes.
Search for those words:

```bash
grep -n -F "The Archive files a page under whatever" BACKLOG.md
```

The first match is the table of contents. The second is the entry. A third
match, if any, is a cross-reference. Titles are used instead of line
numbers because line numbers drift.

## Rules for every deliverable

These come from `CLAUDE.md` and the conductor.

1. **Re-derive first.** Open the file the entry names, re-run its count,
   and `git log --grep` for a fix that already landed. Correct the entry in
   the same pass.
2. **WO numbers come from the conductor.** Never take max plus one alone.
3. **Say what is not live.** After merging anything under `app/`,
   `archive/`, `worker/`, `shared_static/`, `shared_templates/`,
   `requirements.txt` or `render.yaml`, say it is on `main` but not
   deployed. Docs and backlog files never need a deploy.
4. **A `BACKLOG.md` edit merges last.** Rebase on `origin/main`, then rerun
   `python3 scripts/build_backlog_toc.py` right before merging. A stale
   table of contents turned `main` red on 2026-09-14.
5. **Never commit in `~/Documents/rtr-business`.** The conductor commits
   there. Send the conductor a file list.
6. **Bulk work on production data runs from the Render shell**, never from a
   laptop against the production database.
7. **Run all five CI gates before pushing.** See `CLAUDE.md`.
8. **Name scratch files by WO** (`wo932_pr_body.md`), and re-read the PR body
   after `gh pr create`.
9. **Respect the Standing decisions.** They are listed at the end of this
   file.

---

## Phase 0: tidy the backlog

**WO-931.** Runs beside Phase 1. It is the only WO in Phases 0 to 2 that
edits `BACKLOG.md`, so it merges last.

What it delivers:

- **Merge two entries that each appear twice.** A merge dropped them and a
  restore on 2026-09-11 put them back while the originals were still there.
  Keep the restored copy, whose History line is current.
  - "`scripts/build_jurisdiction_data.py`'s blanket"
  - "`finalize_jurisdiction()`'s table validation doesn't"
- **Move finished entries to `BACKLOG_DONE.md`.** Each names the WO that
  shipped it:
  - "YouTube video-ID regex accepts a generic "live stream" embed" (WO-296)
  - "Boxcast tier-1 pages need the signed playlist" (WO-229 re-resolves at
    view time)
  - "Nothing has found which sweep/script ingests a Viebit" and "Two Archive
    pages (Buffalo MN and Big Lake MN, both" (WO-316 deleted the two pages)
  - "`app/platforms/queue_probe.write_pin_row()` refuses a" (WO-307)
  - "`civicplus.py`'s `resolve()` raises a raw" (the decode half, WO-285)
  - "A jurisdiction string with a leading "The " before the" (WO-251)
- **Rewrite entries that are only partly done**, so the live entry says what
  is left. "State legislatures: 91 of 99 chamber rows still have no page" is
  one: PR #1260's notes record six Sliq pages live and five more
  legislature meetings queued.
- **Fix structure.**
  - "97 of the 257 Diligent Community" is a build item filed under Standing
    decisions. Move it to Ship next.
  - Two real Standing decisions have no `###` heading, so the table of
    contents skips them: the video-only ingest rule and the no-backfill of
    partial transcripts.
  - A stray preamble near "Small, self-contained, no open design question"
    points at a section, "Platform & jurisdiction coverage", that no longer
    exists.
- **Correct decayed numbers.** "`CHALLENGE_MARKERS` is duplicated across 8
  scripts, and one" now finds 12 files.
- **Re-check the crash-loop entry.** "`rtr-deeplink`'s SIGABRT/SIGSEGV
  crash-loop" has been quiet since 2026-09-10. Its own test, a full week
  quiet (about 2026-09-17), has passed. Look for any new "Exited with status
  134" alert since 2026-09-13. Close it only if none arrived, and confirm
  with Ryan first, because the entry's constraint says not to close it on
  quiet alone.
- **Fix docs drift.** "Two rules the code and the WO briefs say are in
  `CLAUDE.md` are not" is a real gap. Regenerate `AGENTS.md` after, as #1210
  did. `ACCOUNTS_PLAN.md` still calls phase 1 a "magic link" although Clerk
  shipped.
- **Split one entry that has two halves.** "A partial transcript made by our
  own transcription cannot get the" covers an own-Whisper warning (WO-935)
  and 35 page addresses to hand-check (WO-934). They have different fixes.
- **Add a one-line pointer** to this file in `BACKLOG.md`'s header.

Done when: no duplicate headings, the table of contents is regenerated, CI
is green.

---

## Phase 1: stop and repair wrong content

**WO-932 to WO-935.** Close the door first (932, 933, 935), then clean up
(934).

| WO | What it delivers | Runs after |
|---|---|---|
| WO-932 | An identity gate at ingest. WO-134's checks become on by default. A dry run counts how many existing sweep payloads a blocking Archive check would refuse. | Nothing |
| WO-933 | One shared gate that asks whether a video is really a meeting, in `app/utils/video_hand_check.py`. It replaces the copies of `HIGH_RISK_TITLE_PLATFORMS` (6 files today). Sweeps and `verify_hub` use it. | Nothing |
| WO-935 | Transcript honesty for our own transcription. A decodability guard on cached audio, then the existing "may end before the meeting did" warning on a finished own-Whisper transcript that stops early, then the video length from YouTube so the check can run on YouTube pages. | Nothing |
| WO-934 | One bulk re-tag tool and one reviewed worklist for wrong live pages. It re-runs the 5,857-page screen afterwards. | The deploy checkpoint, and Ryan's page decisions |

**Entries WO-932 closes**

- "The Archive files a page under whatever `gov_id` a sweep sends"
- "The wrong-government checks never look at the resolved video's own"
- "A minted `rtr:` id's state code can be a false positive"
- "A real US government's YouTube video got minted with a"
- "A live page is keyed to the wrong government entirely — Bamberg"
- "A tenant with no video content never runs the identity conflict"

**Entries WO-933 closes**

- "A decorative video with no web-address signature at all"
- "A real tier 1/3 "video found" verdict off"
- "A bare YouTube channel-listing scan measurably ingests non-meeting"
- "`classify_video_hand_check()`'s title-keyword"
- "`find_platform_link()` accepts the first vendor-shaped"
- "`HIGH_RISK_TITLE_PLATFORMS` (`{"youtube", "vimeo"}`,"
- "A bare homepage link to a video file (`direct_file`"
- "A Vimeo video whose own title is a camera file"

**Entries WO-934 closes**

- "Full-corpus screen (5,857 pages) found the same"
- "Wrong-government-content pattern confirmed on 6 live"
- "Three pages from the school-district audit resolved"
- "6 `best_effort` YouTube pages archived a promotional/off-topic video"
- "`YouTubeAssetFinder.extract_video_id()`'s regex matches YouTube's own"
- "82 archived YouTube meetings have embedding switched off"
- "A partial transcript made by our own transcription cannot get the" (part
  2 only: hand-check the 35 page addresses marked `review:` in
  `rtr-business/research/wo925_slug_mismatch_scan.csv`; never re-key from an
  address alone)

**Entries WO-935 closes**

- "`slice_cached_audio()` skips the corrupt-chunk"
- "A chunk truncated only at its tail still passes the"
- "A partial transcript made by our own transcription cannot get the" (part 1
  only: the own-Whisper marker; WO-931 splits the entry)
- "Partial-transcript check has only measured 574 of ~5,800 non-YouTube" (the
  code half: YouTube video length; the other half is on Ryan's list)
- "Repetition-loop transcript-defect population" (mostly covered by WO-929)

**Already built, so not in this phase.** The warning for source captions
shipped in WO-923 (PR #1266). WO-925 (#1269) and WO-926 (#1272) made it
reach the version readers are shown. WO-927 and WO-928 (#1276, #1278) added
the version-quality tool, and WO-929 (#1280) built the re-transcription
queue. WO-935 must read those `BACKLOG_DONE.md` entries first and touch only
what is left. What is left is the own-Whisper gap: WO-925 records that page
1676 (Leon Valley TX) holds a Whisper transcript ending at 86% of a
6.5-hour video, and a re-check reads source captions only, so it can never
add a warning there. The only place the Archive checks a finished
transcript against the video's length today is when a transcription job is
created.

**Order inside Phase 1**

1. **Confirm what production is running.** Deploys are manual, so `main`
   moving does not mean production moved. This decides whether the 49
   CivicPlus pages are safe to re-push, because their identity fix (WO-214)
   only helps once deployed.
2. WO-932 and WO-933 run in parallel. They touch different code.
3. WO-935's decode guard is worth having before more large transcription
   runs, because a corrupt chunk can lose part of a meeting. It is not a
   gate for anything else. In particular WO-929's re-transcription queue
   (82 pages, 254 hours) does not depend on any WO here. The conductor
   confirms it is ready to run now, and `docs/RETRANSCRIPTION_QUEUE.md`
   lists no prerequisite. It starts with a pilot of 5 pages and no
   `--promote`.
4. **Deploy checkpoint.** Merge 932, 933 and 935, then ask Ryan for one
   manual deploy. The Chenango town page repair waits for it.
5. WO-934 applies its repairs after the deploy, from the Render shell.

**Done when**

- A test payload from a different government is refused or flagged.
- A re-run of the 5,857-page screen shows the wrong-government and
  non-meeting lists at zero, or every remaining page is accepted by Ryan in
  writing.
- A finished own-Whisper transcript that stops early carries the same
  warning a source-caption transcript already does.

**The one design choice left for Ryan**

After WO-932's dry run, Ryan decides: should the Archive return 409 when a
page's state disagrees with the registry's? The entry's own constraint says
not to build a blocking check before counting what it would refuse. WO-932
brings Ryan that number and one question.

---

## Phase 2: stop wasting effort

**WO-936 to WO-939.** All four can run in parallel.

| WO | What it delivers |
|---|---|
| WO-936 | A stuck-job detector and a line in the daily worker report. One fix covers the OOM and heartbeat entries. It also separates a real 5xx from an ordinary timeout. |
| WO-937 | Tier-3 queue hygiene in one PR: dedup by video id, no duplicate queue lines, an owner check at feed time. It touches `direct_file.py` and `queue_probe.py` once, not three times. |
| WO-938 | Adapter hardening: one typed `ResolveError`, one shared text-decode helper, and one helper that turns a bare listing page into its newest meeting. |
| WO-939 | Sweep robustness in one PR: a per-call wall-clock deadline, a "no YouTube calls" flag on `resolve()`, and one shared `CHALLENGE_MARKERS`. |

**Entries WO-936 closes**

- "An OOM-killed chunk is completely invisible — it"
- "WO-57's claim heartbeat has no cap, and transcription"
- "The 120s ffmpeg timeout is a flat value that doesn't"
- "A single job still makes N consecutive pulls to the"
- "Some old/archived Granicus clips' `chunklist.m3u8`"
- "East Lansing MI (Granicus): a new, deterministic"

**Entries WO-937 closes**

- "`_existing_tier3_queue_urls()`'s dedup key is an exact"
- "`queue_probe.finish_candidate()` can defer an already-queued meeting"
- "`_probe_direct_file()`'s HEAD fallback misfires on a host that"
- "The tier-3 probe has no recipe for two real delegated media shapes"
- "`feed_tier3_auto_transcription.py`'s per-line result"
- "`wo150_finish_tier3.py` never writes a probe reject back into"
- "A probe-confirmed-dead URL sits in the live"
- "A tier-3 probe's own report `note` always overwrites an"
- "`chunk_plan` stores JSON `null` rather than SQL NULL, so"

**Entries WO-938 closes**

- "`escribe.py`'s `resolve()` raises the same raw" (the CivicPlus half is
  already fixed, see Phase 0)
- "`suiteone.py`'s `resolve()` raises a raw `ValueError`"
- "`granicus.py`'s `_fetch_page()` raises an unhandled"
- "A bare YouTube channel/live URL raises a raw"
- "A bare eScribe tenant root (no `Meeting.aspx` path)"
- "`app/platforms/civicweb.py`'s `_fetch_text()`"

**Entries WO-939 closes**

- "`CHALLENGE_MARKERS` is duplicated across 8 scripts, and one"
- "`wo149_county_ladder_sweep.py` carries its own separate, unpatched"
- "`wo191_access_ladder_sweep.py`'s headless budget is computed at"
- "`scripts/wo321_recon.py`'s phase-1 reconnaissance hung"
- "`wo325_resolve_diagnostic.py` (and every sibling WO's"
- "A slow-trickling response can hang a sweep past every"
- "A sweep script's per-government wall-clock cap can't"
- "No sweep script calls the new playlist-expansion helper"

**Read first, for WO-937.** The `BACKLOG_DONE.md` entries for WO-929 and
for WO-918 (which records the WO-917 hand-check of 133 queued videos). PR
#1224 also took 627 non-YouTube lines out of the shared queue into a local
Whisper batch, so the shared queue and that batch are separate places.
Dedup and the owner check must know which side a line lives on.

**Cautions**

- WO-939: several entries warn that other sessions are editing the WO-147
  and WO-149 sweep scripts. Check open PRs and `git status` first. Land it
  as one PR.
- WO-938 and WO-933 both touch `generic_fallback.py`. Merge one, rebase the
  other.

**Deploy checkpoint 2** after Phase 2.

---

## Phase 3: registry and identity foundations

The first deliverable is **WO-940: one registry write helper.** It locks the
file, re-reads it, compares a content hash instead of a row count, and
renames atomically. It closes these entries and makes one-off registry fixes
safe:

- "`jurisdiction_coverage.csv`'s shared write helper still uses a"
- "`scripts/score_gov_registry.py` overwrites"
- "§158's write protocol doesn't catch a same-row-count"

Caution: the registry lives in `rtr-business`, where only the conductor
commits. WO-940 hands the conductor a file list.

The rest of the phase gets WO numbers when it starts:

| Deliverable | Why | Entries to start from |
|---|---|---|
| A domain-health sweep of the registry | Hand audits found wrong recorded domains on about 15% and about 24% of the rows they checked. Wrong domains feed wrong ingests. | "6 of 40 governments in a hand-audit sample (15%) had a" |
| A pin-rules model with a re-apply tool | At least 6 wrong per-video pins are still live, and a fallback pin beats the registry. | "A per-video fallback pin wins over the registry"; "A `tenant_overrides.csv` pin only affects future" |
| One resolver name-normalisation PR | About 12 name edge cases are batchable (Charter Township, HTML entities, "district" read as BC). | The "Jurisdiction extraction & backfill" group in the table of contents |
| One PR for Granicus and CivicPlus jurisdiction strings | Junk strings and split hubs show on live pages. | The same group |
| A list of source URLs never to re-ingest | A deleted page can currently come straight back (the Toledo OR example). | "Nothing records that a page was deliberately deleted" |
| Dedup by resolved identity | Dedup is by source URL today. | "The same YouTube video submitted via two different URL" |

---

## Phase 4: grow coverage

Starts only after the Phase 1 gates are deployed. Order inside the phase:

1. **Cheap wins, some needing no code.**
   - "Reprobe the rest of the Town Hall Streams tier-3 queue"
   - "97 of the 257 Diligent Community" (once WO-931 moves it)
   - "WO-153's leftover Part B/C rows: 111 shared-host domains still"
   - "The small-video-platform sweep's leftover 8 rows"
2. **State legislatures.** The entry says 91 of 99 chamber rows have no
   page, but #1260's notes record six Sliq pages already live, so re-count
   first. TVW is multi-day.
3. **Discovery re-runs that need machine time.**
   - "WO-259's full-ladder homepage re-scan: 431 of 964 governments done"
   - "WordPress's own `/?s=agenda` search is a confirmed, cheap way to find"
4. **New adapters, one at a time, only when a real sample exists.** The
   rule in `CLAUDE.md` stands: never build an adapter from assumption.
5. **YouTube work through the drip** on Ol McClaude's Mac.

About 50 Open-bugs entries say to wait for a second real example before
building anything. They stay asleep until one turns up.

## Phase 5: what the pages say

Roster names for transcription prompts depend on Track B's agenda text.

- "Meeting body is blank on ~90% of archived pages"
- "Topic chips are ranked by corpus hits, not real search"
- "Hallucinated-transcript detection doesn't catch"
- "Per-meeting `initial_prompt` seeded with real"

---

## Ryan's list: minutes, not build

These come from Needs a human. Each one blocks or feeds a deliverable.

| Item | What Ryan does | Unblocks |
|---|---|---|
| "Leon Valley TX has two pages for one meeting" | Already decided 2026-09-21: page 3973 survives, and deleting 1595 is approved (PR #1282 added the redirect). Only the delete is left, and it runs after the next Archive deploy. The backlog entry still reads as open. | WO-934, WO-931 |
| "Sequatchie County, TN's page (id 7377) is not a real" | Keep or delete | WO-934 |
| "3 live/pending Archive pages need `POST" | Approve three override calls, dry run first | WO-934 |
| "One live page is keyed to the wrong government: a real" | One scoped backfill after the deploy (Chenango town, NY) | WO-934 |
| "13 archived YouTube pages point at a video that is gone (7" | Noindex or delete | WO-934 |
| "A Pennsylvania Public Utility Commission hearing was briefly" | Mint it as a government or not | WO-934 |
| "Render account bandwidth hit its 25 GB/month Pro-plan cap on" | Read the billing dashboard | Ops |
| "Run `scripts/backfill_video_channel.py --apply` from the" | Two backfills from the Render shell | Makes 1,138 channel pins work across 1,903 pages |
| "45 of the 51 `transcribed=true`-no-page research rows found no live" | Approve the hand-checked plan | Phase 3 |
| "How stale is too stale for a tier-3 queue candidate?" | Set a cutoff | Phase 4 |
| "Farmington city, MO: Ryan saw 16 real agenda PDFs on" | Send one agenda PDF URL | Phase 4 |
| "4 LocalView channels from WO-175's recheck read as an" | Yes or no | Phase 4 |
| "Atlantic City NJ's CITISTAT broadcasts (22.5 and 30.9 min," | On-mission or not | Phase 4 |

Longer jobs, not minutes:

- "Decide which hidden transcript versions to promote (WO-928": about 6
  versions, one at a time.
- "Run the re-transcription queue for the pre-voice-filter": WO-929's run,
  82 pages, multi-day machine time. Ready now: pilot of 5 first, no
  `--promote`, per `docs/RETRANSCRIPTION_QUEUE.md`. It waits on nothing
  planned here.
- "Partial-transcript check has only measured 574 of ~5,800 non-YouTube": run
  `scripts/backfill_archived_pages.py` from the resolver's Render shell, then
  read the `truncated_transcript` count at `/internal/transcript-quality-audit`.
  It needs the WO-923 resolver code live. The conductor says it is; confirm
  first (Phase 1, step 1).
- "310 real school-district YouTube/Vimeo leads from the WO-292": route to
  the drip Mac.
- "~1,676 archived YouTube video ids have no channel on record": run after
  the two backfills above.
- "101 West Virginia towns/cities still carry a placeholder": low value.

---

## Track B: product roadmap

Each step waits on the decision in the last column. Nothing here is built
without it. `ACCOUNTS_PLAN.md` holds the full accounts and billing detail.

| Step | What | Needs first |
|---|---|---|
| B0 | Small prerequisites: live-check Resend, repoint ops email to `ally@`, add the sign-in link at the rate-limit message, confirm the Clerk `user.deleted` purge fires | Mastodon: create the account or drop it |
| B1 | Batch lookup gated by account, pulled ahead of profiles | Pull it ahead? What per-account limit? |
| B2 | Profiles and saved-search email alerts | Fold in timestamp annotations? How big is the free alert tier? |
| B3 | Agenda text as a first-class item | Scope: step 1 only, steps 1 and 2, or wait for rtr-upcoming |
| B4 | Posts and reposts | Moderation rules. Does a repost of a repost chain or nest? |
| B5 | Billing | What is free and what is paid. Credits or flat tiers. Stripe or another provider. |
| B6 | Media attachments, popularity sort | Object storage. Only after real use of B2 to B4. |

Entries to start from:

- "Accounts + token billing, phases 2-6"
- "Batch lookup — accept multiple meeting URLs at"
- "Lifecycle-triggered transactional emails (Resend)"
- "Consolidate every user-facing email address on"
- "A signed-out visitor who hits the"
- "Agenda text as a first-class,"
- "Mastodon auto-posting has made zero real posts"

Side bets that need a go or no-go from Ryan:

- "\"Feed cities\" — should this app ever"
- "YouTube captions via YouTube's official API, not InnerTube"
- "Video highlight clips + algorithmic" (conflicts with "never host video")
- "Proactive transcription crawler — grow the" (held back until the trust
  fixes are in)
- "App-wide audit — see"
- "Recurring operator email report every 6 hours,"

---

## Not in any phase

- **13 Standing decisions.** Nothing to build. The table of contents lists
  12, but one of those is a build item and two real decisions have no
  heading (Phase 0 fixes this). In short:
  - Viebit stays untranscribable.
  - Cloudflare human-verification challenges are never solved.
  - No unbounded scan or bulk run hits the production database from an
    interactive session.
  - `dedupe_rollup_transcripts.py --min-retained` stays at 0.05 or above.
  - `MIN_PLAUSIBLE_MEETING_SECONDS` stays at 60.
  - A small government's tenant is never guessed from a bare name.
  - Bulk sweeps ingest only meetings with video.
  - The 120 unresolved wildcard-sweep tenants stay a dead end for
    automation.
- **The Parked entries.** They stay parked.
- **Dormant** has no open entries.

## How this was made, and its limits

Three read-only agents each read a slice of `BACKLOG.md` on 2026-09-21:
Standing decisions with Ship next and Needs a human; Open bugs; and
Reliability with Trust and Roadmap. They grouped entries by the kind of work
and reported counts, blockers and stale entries. The rest was spot-checked
against code on `origin/main`:

| Claim checked | Result |
|---|---|
| `slice_cached_audio()` has no check that its output decodes | Confirmed |
| No typed `ResolveError` exists in the adapters | Confirmed |
| `HIGH_RISK_TITLE_PLATFORMS` is copied across scripts | Confirmed in 6 files |
| `CHALLENGE_MARKERS` is copied across scripts | Entry says 8; it is now 12 files |
| The two "duplicate" entries are true duplicates | Same entry twice; the restored copy has the newer History line |

The conductor reviewed the first draft the same day and made two
corrections, both checked against the repo. WO-935 had proposed a
partial-transcript warning that WO-923, WO-925 and WO-926 had already built
for source captions, so it now covers only the own-Whisper gap. And WO-929's
re-transcription run was described as waiting on WO-935. It does not.

Limits:

- About 100 entries are named above. The rest are placed by theme only.
  Each WO lists its exact entries when it starts.
- Counts are rounded and approximate.
- Line numbers were deliberately left out. Titles are searchable and line
  numbers drift.
