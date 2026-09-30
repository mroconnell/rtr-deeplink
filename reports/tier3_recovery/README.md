# Tier-3 recovery: the September local Whisper batches

## What this checks

Twice in September, lines were pulled out of the shared tier-3 queue
(`scripts/tier3_auto_transcription_queue.txt`) to run in a local Whisper
batch on this Mac instead of the cloud worker:

- **355 lines**, PR #1186 / commit `d4b238b`, 2026-09-15.
- **627 lines**, PR #1224 / commit `cfe6da9`, 2026-09-18.

The assumption going in was that each batch was probably interrupted
(laptop closed) and never finished. This PR checks that assumption
against real evidence on this Mac, then closes the real gap.

## What actually happened to the two batches

Both batches left real run logs behind in
`local_transcription_backups/` (gitignored, local to this Mac). Reading
them line-by-line (matching each queue URL to its "Meeting N/M" outcome
by position in the batch's own url-file) gives a definitive answer:

- **The 355 batch ran start to finish**, 2026-09-15 to 2026-09-18 (three
  days — these are long meetings). It ends with a real summary line:
  `RUN COMPLETE: 273 ingested, 81 skipped, 1 failed (of 355 candidates)`.
- **The 627 batch was genuinely interrupted once, then resumed twice, and
  also finished.** `batch3` (Sep 18–20) stopped mid-meeting at 484/627
  with no summary line — the real interruption. `batch3b` (Sep 20–22)
  picked up the not-yet-processed meetings and finished cleanly.
  `batch3c` (Sep 22) covered 3 replacement meetings for ones `batch3b`
  had skipped. Combined, only 44 of the 627 lines were never handed to
  any local run at all.

So of 982 lines total, 725 already have a real outcome (ingested,
correctly skipped, or one real processing failure) and needed nothing
more. Only **257 lines** — 81 skipped + 1 failed + 44 never-touched in
the 355/627, plus their 627-side counterparts — actually needed the
government-mapping-and-routing work below.

## How the 257 were routed

For each line: re-resolved the meeting locally (`resolve_via_platform()`,
the same platform adapters ingest itself uses) to get its current video
state, resolved its government via `resolve_government()` (tenant pins +
the national registry ladder — the same function `archive/db/crud.py`
calls at ingest time), then checked the live Archive
(`/api/jurisdictions`) for an existing page and its newest page date.

- A government with a real page whose newest page is under 2 years old:
  nothing more.
- Otherwise (no page, or a stale one): routed by the meeting's *current*
  tier — 1 (server-readable captions, ingest immediately — none turned
  up in this set, which makes sense: a tier-1 meeting would never have
  been in the tier-3 queue to begin with), 2 (YouTube/Vimeo — queued the
  same way tier 3 is, since the drip's own lane dispatch already routes
  a queue line to the right lane by URL), or 3 (no captions — added to
  `scripts/tier3_auto_transcription_queue.txt` with a real probe row in
  `scripts/tier3_auto_transcription_queue_probe.csv`).
- One meeting per government: when a government had more than one
  candidate line, the highest-tier one won; among ties, the one probed
  at 9–40 minutes, else the shortest known.
- Viebit and dead-video lines are recorded with their reason, not
  queued — see "No Viebit meeting can get a real transcript today" in
  `BACKLOG.md`'s Standing decisions, which already covers the Viebit
  case for this exact batch.
- A government resolved only at low confidence (an ambiguous or
  unregistered name) is marked TBD, never guessed.

Two script bugs were found and fixed *during* this pass, both explained
in the scripts' own comments and worth knowing about before re-running
anything here: an unregistered platform-finder call that silently made
every probe fail as "dead" (fixed by calling `register_all_finders()`),
and a missing `video_url` check that classified 43 genuinely video-less
meetings as tier 3 instead of dead (fixed in `resolve_worklist.py`'s
`classify_video_tier()`).

One resolution was hand-corrected rather than trusted automatically:
`hastingsonhudsonny.swagit.com`'s real title got parsed as jurisdiction
"Hudson, NY" (a real but different government) by a `swagit.py` regex
bug — see the new `BACKLOG.md` entry. Corrected to Hastings-on-Hudson
village, NY (`us:place:3632710`) using the same real title text.

## Results

**Batch of 355** (PR #1186, 2026-09-15):

| Result | Count of 82 |
|---|---|
| Already has a page | 3 |
| Ingested | 0 |
| Re-queued | 36 |
| YouTube/Vimeo drip | 3 |
| Re-routed (another line covers this government) | 1 |
| Viebit or dead | 10 |
| TBD | 29 |

**Batch of 627** (PR #1224, 2026-09-18):

| Result | Count of 175 |
|---|---|
| Already has a page | 22 |
| Ingested | 0 |
| Re-queued | 50 |
| YouTube/Vimeo drip | 5 |
| Re-routed (another line covers this government) | 0 |
| Viebit or dead | 35 |
| TBD | 63 |

(One government in the 627 batch, Bedford NY, had a real page over 2
years old — treated as uncovered per Ryan's rule, re-queued.)

## What's in this PR

- `scripts/tier3_auto_transcription_queue.txt`: 95 new lines (the
  tier-2/tier-3 winners above), each with its real `gov_id`.
- `scripts/tier3_auto_transcription_queue_probe.csv`: real probe rows
  for the winners that didn't already have a cached one (44 probed
  fresh; 2 of those turned out to have real video after all —
  Hastings-on-Hudson NY and Janesville WI, both now correctly queued).
- `BACKLOG.md`: one new entry for the `swagit.py` hyphenated-place-name
  bug found while hand-verifying a resolution.
- `reports/tier3_recovery/`: the scripts and final per-line data behind
  every number above, for anyone who wants to re-derive or spot-check
  a specific line. `final_routed_257_reported.jsonl` is the authoritative
  one-row-per-line result.

**Not done here, on purpose**: no ingest was performed (there were no
tier-1 candidates to ingest), and neither `tier3_long_meetings_deferred.txt`
nor any government's actual Archive page was touched. This PR is not
merged — queue lines and probe rows only, for review.

## Governments that got nothing (TBD), and why

92 lines' government could not be resolved with confidence and were
left TBD rather than guessed. The two largest patterns:

- **`townhallstreams.com` and `www.utah.gov`** (shared, multi-government
  hosts) sometimes gave a real jurisdiction name from the page itself
  (used when unambiguous — see "resolved from the page's own text" notes
  in `resolved_257_reconciled.jsonl`), but many pages gave either no name
  at all, or a special-purpose district (a hospital district, a library
  board) not yet in the national registry tables — these need either a
  `tenant_overrides.csv` pin or a new minted government id, both a human
  call, not something to invent here.
- A handful of pages resolved to a name at low confidence (e.g. "Fremont"
  with no state, ambiguous across several real Fremonts) — left TBD
  rather than guessed at the wrong one.

The full list, with each line's specific reason, is in
`resolved_257_reconciled.jsonl`'s `gov_resolution_note` field.
