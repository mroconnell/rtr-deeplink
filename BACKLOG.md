# Backlog

**Open items only.** Completed work — including the investigation detail
behind each fix — lives in [BACKLOG_DONE.md](BACKLOG_DONE.md); entries
below link back to it for context. Ideas nobody has triaged yet live in
`CLAUDE_BACKLOG.md`, and the daily Routine's unreviewed findings live in
`CLAUDE_INBOX_TRIAGE.md` — neither is this file.

**Sections are ordered by actionability, not by subsystem** (since
2026-08-21 — the old subsystem buckets hid real bugs at the bottom of
thousand-line sections). "Ship next" stays short because items leave it
when they ship; "Needs a human" drains; "Dormant" is explicitly allowed
to be long *and* explicitly skippable.

**Where to file a new entry** — take the first section that fits:

1. `## Standing decisions` — a decision already made *against* doing
   something. Nothing to build; the entry exists so it stops getting
   rediscovered.
2. `## Ship next` `[JUST-DO-IT]` — root cause known, fix settled, small.
3. `## Needs a human` `[HUMAN]` — blocked on a dashboard, a production
   action, or a product call, not on engineering.
4. `## Open bugs` `[NEEDS-AUDIT]` — real, reproduced, fix *not* settled.
5. `## Platform & jurisdiction coverage` — anything adapter-, tenant-, or
   jurisdiction-extraction-shaped, including bugs. Kept together on
   purpose. Its own `[JUST-DO-IT]`/`[HUMAN]`/`[NEEDS-AUDIT]` items keep
   their tags inline rather than being hoisted into sections 2-4.
6. `## Reliability, ops & cost`, `## Trust, safety & data quality`,
   `## Roadmap & strategy` `[IMPROVEMENT-ROUND]` — real and open, but not
   in one of the crisp states above.
7. `## Dormant` `[LATER]` — waiting on a real example before anything can
   honestly be built. Long by design; safe to skip.
8. `## Parked deliberately` `[PARK]` — set aside by the user, explicitly
   allowed back.

Within a section, group by theme. Tag every entry. When an item ships,
move it to `BACKLOG_DONE.md` with a `[Done YYYY-MM-DD]` marker and split
any residual back out here as its own live entry, per `CLAUDE.md`.

**Entry format (adopted 2026-08-31, after a user review flagged entries
reading like investigation journals; split rule and field-omission
tightened the same day after a dry-run retrofit of the whole file showed
the first version of this rule self-defeating — see `BACKLOG_DONE.md`)**
— five short fields, one tight sentence each (a shape to aim for, not a
hard line-count; a field can wrap to a second line if it genuinely needs
to):

1. **Issue** — what's failing or needed.
2. **Impact** — what breaks, or who/how much is affected.
3. **Next action** — the exact next step. Not a summary of past attempts.
4. **Constraint** — a warning, e.g. "don't bulk-test this."
5. **History** — a link, almost always `BACKLOG_DONE.md` (finished
   investigation work, `[Done]` or `[Investigated]`). Use
   `docs/investigations/<slug>.md` only for the rare entry that's a
   **living investigation spanning multiple sessions and still open** —
   new findings keep landing, it isn't close to done, and it doesn't fit
   `BACKLOG_DONE.md`'s finished-work model either (see
   `docs/investigations/youtube_429_block.md` for the first case). Most
   entries never need this tier.

**No field is required — omit any that don't apply, rather than filling
one with "none" or "n/a."** A dry-run retrofit found the opposite
instinct (every entry gets all 5, blank ones say "none") does two things
at once: it pads short entries with filler lines, and it pressures a
single settled fact into its own heading just so it has somewhere to put
an empty Next action. Skip the field instead. A `[LATER]`/Standing-
decision entry that's just a documented, accepted limitation often only
needs Issue + Impact — that's a complete entry, not an incomplete one.

**Overwrite, don't append.** When a re-test or new finding changes the
picture, rewrite the entry's own fields to reflect the current state —
don't stack a new paragraph ("re-tested 2026-08-29, still open...") onto
the old one. The old text is still recoverable from git history if anyone
needs it; the live entry should only ever describe what's true *now*.

**Split only on a genuinely different fix, not a different facet.** The
test: would fixing one half leave the other half's Next action
unchanged? If yes, they're separate entries. If several facets of one
feature all currently have no real next action (documented, accepted
limitations, not open work), that's a sign they're one entry, not several
— describe all the facets in Issue/Impact and let the single entry carry
them, rather than giving each its own heading and a repeated History
line pointing at the same build. The same dry run that motivated the
field-omission rule above found this cuts the other way just as often:
sections that split on "different facet" grew faster than sections that
compacted shrank, erasing the format's own gains at the whole-file level.
**Half-resolved → split** is the one case that still always applies: if a
fix lands for part of an entry, don't leave the other half riding along
under the old heading — give the still-open part its own entry (new
heading, fresh 5 fields) and move the resolved part's evidence into
`BACKLOG_DONE.md`. Two focused entries beat one entry that's half
current, half historical.

<!-- TOC-START -->
<!-- Generated by scripts/build_backlog_toc.py. Do not edit by hand;
     rerun that script after any edit to this file. -->

## Contents

**Read this block, not the whole file.** Every line below is a
verbatim prefix of a real line further down, so any entry opens with
`grep -n -F "<fragment>" BACKLOG.md`. Counts are entries per section.

```text

Standing decisions — do NOT re-raise  (7)
  `jurisdiction_confidence IS NULL` is deliberately excluded from…
  Don't reach for a bigger Render plan before measuring what the peak…
  Never run an unbounded scan or bulk workload against the production…
  Prefer a generated/computed column over "add a column, then backfill…
  Never attempt to auto-solve a Cloudflare "Verify you are human"…
  Don't lower `dedupe_rollup_transcripts.py --min-retained` below 0.05
  Don't lower `MIN_PLAUSIBLE_MEETING_SECONDS` below 60s to catch more…

Ship next — root cause known, fix settled `[JUST-DO-IT]`  (2)
  [JUST-DO-IT] `slice_cached_audio()` skips the corrupt-chunk…
  [JUST-DO-IT] `proxy_get()`/`_proxy_to_archive()` catch `except…

Needs a human — dashboard, prod, or product call `[HUMAN]`  (6)
  Production actions only Ryan should take  (5)
    [HUMAN] Click Validate Fix in Search Console for the reslug fix.
    [HUMAN] Two Archive fixes merged 2026-08-30 (WO-80's O(1) health…
    [HUMAN] WO-88's CivicClerk `mediaStreamPath` relative-path fix may…
    [HUMAN] `rtr-deeplink` (the production resolver) has SIGABRT-crashed…
    [HUMAN] Dismiss the GitHub secret-scanning alert on…
  Decisions about already-live content  (1)
    [NEEDS-AUDIT] `[BIG]` Repetition-loop transcript-defect population —…

Open bugs — real, root cause not settled `[NEEDS-AUDIT]`  (72)
  [NEEDS-AUDIT] A `tenant_overrides.csv` pin only affects future
  [NEEDS-AUDIT] Phase 2d's signal-based recovery (WO-110,
  [NEEDS-AUDIT] `RuntimeError: Response content shorter than
  [NEEDS-AUDIT] Several already-archived pages carry a confidently-
  [NEEDS-AUDIT] eScribe serves the same meeting under multiple
  [NEEDS-AUDIT] A `strength=fallback` tenant pin cannot correct a
  [NEEDS-AUDIT] `scripts/score_gov_registry.py` overwrites
  [NEEDS-AUDIT] `scripts/score_gov_registry.py` can't see `match`-
  [NEEDS-AUDIT] `civicplus.py`'s `resolve()` has no encoding fallback
  [NEEDS-AUDIT] The same YouTube video submitted via two different URL
  [NEEDS-AUDIT] `[BIG]` No automated "pick the best candidate" step
  [NEEDS-AUDIT] `[BIG]` Microsoft Teams and Zoom are real, confirmed
  [NEEDS-AUDIT] A bare YouTube channel/live URL raises a raw
  [NEEDS-AUDIT] SLC's `_nearest_topic_text()` silently drops one real
  [NEEDS-AUDIT] Non-YouTube garbled/truncated pages have no automated
  [NEEDS-AUDIT] `[LOGIN]` Missing-Playwright-binary error recurred
  [NEEDS-AUDIT] Search Console "video isn't on a watch page" — Granicus
  [NEEDS-AUDIT] Search Console "video isn't on a watch page" — Cablecast
  [NEEDS-AUDIT] Garbled source transcripts still produce garbled
  [NEEDS-AUDIT] Topic chips are ranked by corpus hits, not real search
  [NEEDS-AUDIT] [BLOCKED] Whether a sustained YouTube IP block ever…
  [NEEDS-AUDIT] Philadelphia's `_pick()` ambiguity gap — real, not yet
  [NEEDS-AUDIT] A chunk truncated only at its tail still passes the
  WO-34's roll-up calibration gap: a second, smaller defect shape sits…
  `transcribe_backlog_locally.py`'s asyncio/subprocess context hangs…
  Brookhaven NY's media host (`cpmedia.azureedge.net`) fails every…  (1)
    [LATER] `pec.iqm2.com` (IQM2) — a third same-day probe still shows
  `[LATER]` Swagit multi-clip meetings: both transcription paths now…
  High Plains Water District (Granicus) transcribed to zero usable…
  Adapter, tenant & jurisdiction-extraction odds and ends `[LATER]`  (3)
    `[NEEDS-AUDIT]` `jurisdiction_enrich.validated_label_extract()` can…
    `[NEEDS-AUDIT]` CivicPlus's subdomain jurisdiction hint is lost…
    `[NEEDS-AUDIT]` `appalachian.cablecast.tv` (show/3841) is genuinely…
  ChampDS symptom B — instant 0.2s failures from the JSON API,…
  `[JUST-DO-IT]` ~10 OnBase/Hyland-family pages still resolve with no…
  Duration alone cannot separate a very short real meeting from an ad…
  Residual gaps from the 50-largest-cities audit `[NEEDS-AUDIT]`
  Granicus's GovAccess CMS product is undetected and blocked by…
  Jurisdiction extraction & backfill  (14)
    `[NEEDS-AUDIT]` `[EASY]` `"Regional Municipality of X"`/`"Region of…
    `[NEEDS-AUDIT]` `[EASY]` `classify.py`'s SPECIAL_DISTRICT rule…
    `[NEEDS-AUDIT]` `[EASY]` `pub-*` eScribe hosts resolve to a US…
    `[NEEDS-AUDIT]` `[EASY]` A minted government's page and its hub show…
    `[NEEDS-AUDIT]` `[EXAMPLE]` eScribe, Swagit and CivicClerk landing…
    `[NEEDS-AUDIT]` `uatccta.primegov.com` is the first real…
    `[NEEDS-AUDIT]` Derry NH has no known-jurisdictions entry.
    `[NEEDS-AUDIT]` Jurisdiction-bleed single-word-tail gap: Castle Rock
    `[NEEDS-AUDIT]` Bare "Pitt" jurisdiction value — likely not a bug.
    `[NEEDS-AUDIT]` Swagit still resolves special-purpose entities with a
    `[NEEDS-AUDIT]` Lloydminster (AB/SK border city) needs a product
    `[NEEDS-AUDIT]` Census-table baseline validation: mid-word truncation
    `[LATER]` Domain guesser state-name collision — fixed, 6 rows still
    `[LATER]` ~25 smaller consolidated city-county governments still need
  Adapter & platform gaps  (22)
    [JUST-DO-IT] TelVue CDX enumeration solved and the full 313-token…
    [NEEDS-AUDIT] A shared regional TelVue org token spanning multiple
    [NEEDS-AUDIT] RVTV's org-token jurisdiction override
    [IMPROVEMENT-ROUND] AV Capture All (`avcaptureall.cloud`) is a real,
    [NEEDS-AUDIT] Tarrant County TX (TechShare.AgendaManagement)…
    [NEEDS-AUDIT] Tarrant County TX (TechShare.AgendaManagement)…
    [NEEDS-AUDIT] Anchorage AK's original "bot-blocked YouTube…
    [NEEDS-AUDIT] Vimeo captions and Whisper-fallback audio are blocked…
    [NEEDS-AUDIT] Chicago ELMS's 473 real agenda items have no time…
    [NEEDS-AUDIT] ProudCity: Holyoke MA's YouTube 429 recovery status is…
    [NEEDS-AUDIT] ProudCity: two tenants remain unpushed (undiscovered…
    [JUST-DO-IT] City-YouTube-channel fallback: listings only reach ~400…
    [JUST-DO-IT] City-YouTube-channel fallback: duplicate-posted meetings…
    [LATER] `[EXAMPLE]` Town Hall Streams: transcript endpoint…
    [LATER] `[EXAMPLE]` SuiteOne Media: dead CDX leads and unconfirmed…
    [LATER] `[EXAMPLE]` Granicus's `captions.vtt` caps at exactly 36,000…
    [LATER] YouTube Whisper fallback for videos with no captions at all…
    [IMPROVEMENT-ROUND] Cablecast, TelVue, Swagit, and YouTube still…
    [NEEDS-AUDIT] ChampDS's VOD2 HLS case (majority of customers) has no…
    [NEEDS-AUDIT] Palm Beach County FL's SharePoint page now escalates…
    [LATER] `elpasotexas.gov/videos/` has no adapter of its own.
    [NEEDS-AUDIT] `[EXAMPLE]` The Phoenix Legistar canary sample is a…

Reliability, ops & cost  (14)
  `[JUST-DO-IT]` Render *pipeline minutes* — build volume cut twice,…  (1)
    [LATER] Tighten the two transcription workers to their real import
  Media-source reliability  (4)
    `[NEEDS-AUDIT]` Some old/archived Granicus clips' `chunklist.m3u8`…
    `[NEEDS-AUDIT]` A single job still makes N consecutive pulls to the…
    `[NEEDS-AUDIT]` The 120s ffmpeg timeout is a flat value that doesn't…
    `[NEEDS-AUDIT]` East Lansing MI (Granicus): a new, deterministic…
  Transcription queue & workers  (6)
    [NEEDS-AUDIT] `chunk_plan` stores JSON `null` rather than SQL NULL, so
    [NEEDS-AUDIT] An OOM-killed chunk is completely invisible — it
    [NEEDS-AUDIT] WO-57's claim heartbeat has no cap, and transcription
    [NEEDS-AUDIT] Backlog keeps shrinking — re-derived 2026-08-31.
    [LATER] `list_transcription_backlog_candidates()` still does a real
    [LATER] Second transcription worker's auto-generation TOCTOU race —
  Search Console, structured data & SEO plumbing  (2)
    [HUMAN] `[LOGIN]` `[WAIT]` "Reasons preventing pages from being
    [NEEDS-AUDIT] New "Missing field" flags — Videos `uploadDate`, Events
  `/coverage` as a QA surface  (1)
    [JUST-DO-IT] `/coverage`'s "Every place we've covered" table is a

Trust, safety & data quality  (11)
  `[LATER]` No blanket backfill can make pre-2026-08-21 `best_effort`…
  `[NEEDS-AUDIT]` California county jurisdiction names split across two…
  `[NEEDS-AUDIT]` YouTube-delegated ingests can land with…
  `[LATER]` `best_effort` is sticky — nothing at ingest distinguishes a…
  `[IMPROVEMENT-ROUND]` Low-trust queue rows have no repair workflow…
  `[IMPROVEMENT-ROUND]` A low-trust review doesn't expire when the page…
  `[LATER]` Mastodon auto-posting has made zero real posts
  `[IMPROVEMENT-ROUND]` Social auto-posting only fires on page…
  `[LATER]` Prompt injection isn't a live product risk today, but the…
  `[HUMAN]` `[BIG]` Nothing verifies a submitted URL is a genuine…
  `[NEEDS-AUDIT]` Chula Vista's stale garbled-marker survives its own…

Roadmap & strategy `[IMPROVEMENT-ROUND]`  (26)
  `[IMPROVEMENT-ROUND]` A general-purpose "is this a real government…
  `[HUMAN]` YouTube captions via YouTube's official API, not InnerTube…
  `[IMPROVEMENT-ROUND]` `[BIG]` Agenda text as a first-class,…
  `[IMPROVEMENT-ROUND]` `[BIG]` App-wide audit — see…
  Product direction & open strategic questions  (1)
    `[IMPROVEMENT-ROUND]` `[BIG]` "Feed cities" — should this app ever…
  `[IMPROVEMENT-ROUND]` `[BIG]` Accounts + token billing, phases 2-6 —…
  Growth, audience & discoverability  (9)
    `[IMPROVEMENT-ROUND]` Zero-signal jurisdiction rows are the real…
    `[IMPROVEMENT-ROUND]` Proactive transcription crawler — grow the…
    `[IMPROVEMENT-ROUND]` YouTube Atom-feed polling as a narrower,…
    [IMPROVEMENT-ROUND] Batch lookup — accept multiple meeting URLs at
    [IMPROVEMENT-ROUND] Whether the resolver's existing `GET /admin/log`
    [IMPROVEMENT-ROUND] `[BIG]` Video highlight clips + algorithmic
    [IMPROVEMENT-ROUND] A generated, branded share card would beat a raw
    [IMPROVEMENT-ROUND] PDF agenda text-extraction for a searchable
    [IMPROVEMENT-ROUND] Design reference for the cassette-reel button
  Search & metadata quality  (5)
    [IMPROVEMENT-ROUND] Tune `_VOCAB_SIMILARITY_THRESHOLD`
    [IMPROVEMENT-ROUND] Audit per-adapter coverage of `meeting_body`,
    [IMPROVEMENT-ROUND] Once `meeting_body` has real, strategic coverage,
    [IMPROVEMENT-ROUND] Transcript version picker: real option labels
    [IMPROVEMENT-ROUND] A demoted `TranscriptVersion`'s text is still
  Transcription quality & cost  (3)
    [IMPROVEMENT-ROUND] Hallucinated-transcript detection doesn't catch
    [IMPROVEMENT-ROUND] Per-meeting `initial_prompt` seeded with real
    [IMPROVEMENT-ROUND] A signed-out visitor who hits the
  Email, ops tooling & internal reporting  (3)
    [IMPROVEMENT-ROUND] Lifecycle-triggered transactional emails (Resend)
    [IMPROVEMENT-ROUND] Consolidate every user-facing email address on
    [IMPROVEMENT-ROUND] Recurring operator email report every 6 hours,

Parked deliberately — allowed back `[PARK]`  (3)
  [IMPROVEMENT-ROUND] School-district / special-entity jurisdiction…
  [PARK] MPO / transit-authority / utility-district name table.
  [PARK] `[BIG]` "Request Transcript from Audio" doesn't work for…
```

<!-- TOC-END -->

## Standing decisions — do NOT re-raise

Durable calls worth carrying into any session, not narrow one-offs.
**Single-incident decisions** — one adapter's domain override, one SEO
judgment call, one ops-tooling choice — **live in `BACKLOG_DONE.md`'s
Standing decisions archive** instead; check there before assuming
something hasn't been decided.

- **Do NOT backfill partial transcripts onto historically-failed jobs.**
  - **Decision**: don't write a backfill that publishes stored partial
    segments onto old failed transcription jobs.
  - **Why**: measured 2026-08-24, from the Archive's Render shell — of
    **48 failed jobs holding segments (44 distinct pages)**, 33 already
    have a good transcript now, so only 11 would gain anything and only
    4 of those exceed 38% coverage. Most of the 48 self-heal anyway: 42
    failed at exactly chunk 1 (the now-fixed WO-45 ffmpeg HLS-seek bug),
    so they're re-transcribable end to end, and a partial would mark
    them `truncated_transcript` where a complete transcript is now
    achievable — strictly worse. The rest publish their own partial
    automatically on the next retry
    (`crud._publish_partial_transcript()`, shipped 2026-08-24). A
    backfill only helps a page that's never retried at all, which is a
    different, still-open problem (jobs 20 and 47 never recovering, see
    Open bugs).
  - **History**: re-run the numbers before re-raising this; both
    read-only scripts are reproduced in `BACKLOG_DONE.md`'s entry for
    the partial-publishing work.

### `jurisdiction_confidence IS NULL` is deliberately excluded from low-trust review

`NULL` (pages archived before that column existed, pre-2026-08-15) means
"we never asked," not "we asked and got nothing" — the low-trust query
excludes it on purpose, to avoid swamping the review queue with
probably-fine rows. Revisit only if the queue proves too narrow rather
than too noisy. WO-21 (2026-08-21) build in `BACKLOG_DONE.md`.

### Don't reach for a bigger Render plan before measuring what the peak actually is

Twice now the obvious read of a worker OOM has been "2GB isn't enough,
buy 4GB", and twice the measurement said otherwise. WO-94 (2026-09-01):
the real 900s peak was 1588MB, so the fix was a chunk-size change, not
$60/mo. WO-95 (2026-09-02): the chunk actually killing the worker was
2,519s, projecting **~3.6GB** — `pro` (4GB) would have left ~200MB of
margin, very likely kept crash-looping, and cost $85/mo per worker while
hiding the real bug behind a bigger number.

`_WORKER_DEFAULT_CHUNK_SIZE_SECONDS`' own comment carries the measured
duration/RSS curve; peak scales with **audio duration**, roughly 1.26MB
per second above a ~457MB floor. Project the peak for the longest chunk
the code can actually produce before pricing a plan — and note that "the
longest chunk the code can actually produce" is the part both incidents
got wrong, not the arithmetic.

### Never run an unbounded scan or bulk workload against the production DB from an interactive session

Found the hard way (2026-08-17): a handful of hand-written analytics
queries scanning every `segments` blob each ran 50–62s against
production, saturating I/O on a `shared_buffers = 64MB` server during
live search traffic. The specific query shape isn't the point — any
full-table scan, bulk read, or heavy analytics query run interactively
against prod risks the same thing. Sample with `LIMIT`, aggregate over
size rather than loading real values, or use the PITR/restore path
(`BACKLOG_DONE.md`) for real analysis. Any prompt spawning a sub-agent
with prod access must restate this explicitly — a permission block the
parent hit doesn't carry into a child's instructions.

### Prefer a generated/computed column over "add a column, then backfill it" — but weigh table size first

`scripts/backfill_search_corpus.py`-style one-time backfills remain
manual; a generated column (the `search_tsv` pattern) needs none.
**Caveat, not yet load-bearing but worth carrying forward**: a `STORED`
generated column forces a blocking, synchronous table rewrite on
`ALTER TABLE ADD COLUMN` — the same cost as a backfill, but un-batchable
and un-resumable. Fine at today's table size; won't stay fine as tables
grow. Check row count against realistic rewrite time before reaching for
this pattern once a table is large.

### Never attempt to auto-solve a Cloudflare "Verify you are human" challenge

General principle and good/bad examples now in `CLAUDE.md` — we query
sites politely and don't defeat a host's own access controls. Hit live
on Spokane WA building the Vimeo adapter (WO-29); that adapter ships
video-only rather than going near it.

### Don't lower `dedupe_rollup_transcripts.py --min-retained` below 0.05

Moved from Open bugs 2026-08-31. Real observed floor is **0.066**
(Delray Beach FL, Marco Island FL), not Tacoma's 0.117 as earlier
measurements suggested. The 0.05 default has a small but genuine margin
above that — don't lower it further without a new real measurement.

### Don't lower `MIN_PLAUSIBLE_MEETING_SECONDS` below 60s to catch more short real meetings

Moved from Open bugs 2026-08-31 — this was already a settled "don't
touch it" finding, not an open question. WO-46 moved the floor 300s →
60s off real measured data. That recovered three of four confirmed-real
short meetings, but a real County Council special meeting (53s,
`berkeleycountysc.iqm2.com` MeetingID=4203) sits three seconds above a
confirmed ad (50s, `gnat.cablecast.tv/.../13707`) — the two classes are
interleaved right at the floor, so a smaller number buys nothing.
Berkeley County stays an accepted miss. Separating them for real needs a
different signal entirely (`meeting_body`, real-agenda presence, page
framing) — worth building only if the daily failure digest (WO-46) shows
this class is actually common; as of 2026-08-31 it's one known case.

## Ship next — root cause known, fix settled `[JUST-DO-IT]`

Small, self-contained, no open design question. Jurisdiction-extraction
items that also qualify live under **Platform & jurisdiction coverage**
so that work reads together.

- **[JUST-DO-IT] `slice_cached_audio()` skips the corrupt-chunk decodability guard `extract_chunk_audio()` has had since 2026-08-21 — confirmed 5+ real production failures across 5 distinct sources on 2 platforms.**
  - **Issue**: WO-54/58's whole-audio-cache path (`app/platforms/media_probe.py:944-982`, `slice_cached_audio()`) only checks ffmpeg's exit code and that the output file is non-empty. It never calls `_mean_volume_db()` — the same decodability check `extract_chunk_audio()`'s `_extract_chunk_once()` already applies (see that function's own docstring, `media_probe.py:1011-1031`) — so a corrupt/undecodable byte range inside the cached whole-file audio reaches `engine.transcribe_chunk()` raw as an unhandled PyAV `InvalidDataError` instead of failing as a normal retryable `(False, reason)`. Re-confirmed by direct read of current `slice_cached_audio()` on 2026-09-05: still no guard.
  - **Impact**: real, repeated, cross-platform — job 1157 (San Diego CA, Granicus, lost 15/25 chunks, 60% of the meeting), job 1226 (College Station TX, CivicClerk, 11/17), job 1259 (Falls Church VA, Granicus, gave up at 14/15), job 1377 (Mansfield TX, CivicClerk, gave up at 1/6), job 1766 (Alameda County CA "BOS View", Granicus, gave up at 17/22, 2026-09-05) — same exact `errno 1094995529` signature every time, not one platform's quirk. WO-54/58's whole-audio-cache path targets exactly the seek-hostile progressive sources (ChampDS, Granicus) most likely to contain a corrupt/interrupted byte range, so this sits on the path most likely to need the guard.
  - **Next action**: add the same `_mean_volume_db()` decodability check to `slice_cached_audio()`, returning `(False, "...isn't decodable (likely truncated/corrupt)")` instead of `(True, None)` on an undecodable slice. `worker/main.py`'s existing per-chunk retry/budget logic already treats that shape as a normal retryable failure — no other code path needs to change.
  - **History**: found by the inbox-triage Routine's 2026-08-29 run; the 2026-08-30, -31, and 2026-09-01 runs each confirmed a fresh independent occurrence on a new source.

- **[JUST-DO-IT] `proxy_get()`/`_proxy_to_archive()` catch `except Exception`, which doesn't catch `asyncio.CancelledError` — a fresh, still-open instance of the "Unclosed connector" leak class the 2026-08-21 fix only partly closed.**
  - **Issue**: `app/archive_client.py`'s `proxy_get()` (`except Exception:` around `await session.get(...)`, currently line 490) and `app/main.py`'s `_proxy_to_archive()` (`except Exception:` around `archive_client.proxy_get(...)`, currently line 1701) both leave `asyncio.CancelledError` (a `BaseException` subclass since Python 3.8) unhandled, so a request cancelled mid-fetch (client/bot disconnects while the Archive fetch is in flight) leaks the aiohttp session's connector until GC finalizes it. Re-confirmed by direct read of current code on 2026-09-05 — the gap is unchanged; only the line numbers have drifted from the original triage note (`archive_client.py:465-474`, `app/main.py:1622-1632`).
  - **Impact**: same self-healing-via-GC leak class as the already-fixed PYTHON-FASTAPI-V/S/Q/T/W/X cases (`BACKLOG_DONE.md`'s "Five bundled easy-win fixes"), not a user-visible crash — surfaced fresh as Sentry **PYTHON-FASTAPI-13** (2026-08-28, real production traffic on `/state/massachusetts`), a new issue ID confirming this is a fresh recurrence via a path that fix didn't close. Structurally open on every proxied route (`/m/*`, `/state/*`, `/j/*`, `/meetings`, `/coverage`, sitemap, feed) since they all funnel through these two functions.
  - **Next action**: in both functions, close the session on `asyncio.CancelledError` too, before re-raising it — e.g. `except (Exception, asyncio.CancelledError):` wrapping the existing close, always re-raising the cancellation rather than swallowing it.
  - **History**: `BACKLOG_DONE.md`'s "Five bundled easy-win fixes" (2026-08-21). Found by the inbox-triage Routine's 2026-08-29 run.

## Needs a human — dashboard, prod, or product call `[HUMAN]`

Nothing here is blocked on engineering. Most are one dashboard login or
one deliberate production action away from closing. Grouped by what kind
of human step they need.

### Production actions only Ryan should take

- **[HUMAN] Click Validate Fix in Search Console for the reslug fix.**
  - **Issue**: the reslugged-pages fix is deployed and live (confirmed
    2026-08-31: reslugged pages serve real content), but Search Console
    hasn't been told to re-check them.
  - **Impact**: Google keeps flagging pages as broken that are actually
    fixed until Validate Fix is clicked.
  - **Next action**: click Validate Fix in Search Console now — this is
    actionable today, not "once it completes." Don't expect it to clear
    100%; see `BACKLOG_DONE.md`'s `[Investigated 2026-08-30]` writeup
    for the full numbers and why.
  - **History**: code side shipped and already deployed — see
    `BACKLOG_DONE.md`.

- **[HUMAN] Two Archive fixes merged 2026-08-30 (WO-80's O(1) health check, `delete_meeting_pages_by_slug()`'s FK cleanup) may still not be deployed — confirm and redeploy if not.**
  - **Issue**: both fixes are confirmed present on `main` (re-checked 2026-09-05): `archive/main.py`'s `/api/health` uses `LIMIT 1` not `SELECT count(*)`, and `archive/db/crud.py:9337`'s `delete_meeting_pages_by_slug()` deletes `SocialPost`/`MeetingPageThumbnail` rows before the page. Every service has `autoDeploy: false` in `render.yaml`, so a merge ships nothing until someone deploys it by hand.
  - **Impact**: as of the inbox-triage Routine's 2026-08-31/09-01 runs, alerts consistent with both gaps still being live kept arriving — repeated `rtr-deeplink-archive` "HTTP health check failed" Render alerts, a `ClientConnectorError` hitting real `/j/belvedere-ca` traffic 58s before one such alert, and a `ForeignKeyViolationError` on `/internal/admin/delete-pages`. No further alerts of either shape turned up in the runs reviewed through 2026-09-03 — consistent with (but not proof of) an intervening deploy.
  - **Next action**: check the Archive service's deploy history in Render; deploy if it's still running a pre-2026-08-30 13:28 PDT build. No code change needed — this is "ship what's already on `main`."
  - **History**: `BACKLOG_DONE.md` (WO-80); PR #577 (`delete_meeting_pages_by_slug` fix). Flagged by the inbox-triage Routine's 2026-08-31 run.

- **[HUMAN] WO-88's CivicClerk `mediaStreamPath` relative-path fix may not be deployed to the transcription worker services — confirm and redeploy if not.**
  - **Issue**: confirmed present on `main` (`app/platforms/civicclerk.py:77`'s `_reconstruct_cdn_stream_url()`), but the auto-transcription retry path calls `finder.resolve(source_url)` **in-process** (`worker/main.py:471`), importing the platform module directly rather than calling the deployed resolver's HTTP API — so a worker instance still running a pre-fix build hits the raw-relative-path bug regardless of the resolver's own deploy state. `rtr-transcription-worker`/`-2` are `type: worker` with `autoDeploy: false` like every other service, and neither has an `/admin/schema-info`-style endpoint to check deploy state directly.
  - **Impact**: transcription job 1308 (`kaysville-ut-2023-04-28-city-council-work-session`, 2026-08-31T13:14:37Z) failed 3/3 on chunk 0/14 with the exact pre-fix raw-path symptom the fix was built and tested against — the same event/GUID cited in the fix's own docstring. Stays stuck failing/in cooldown until a worker redeploy ships the already-merged fix; any other CivicClerk event hitting the same fallback fails the same way until then.
  - **Next action**: confirm whether `rtr-transcription-worker`/`rtr-transcription-worker-2` have deployed since 2026-08-31 13:14 UTC; redeploy if not. No code change needed.
  - **History**: `BACKLOG_DONE.md` (WO-88). Flagged by the inbox-triage Routine's 2026-09-01 run.

- **[HUMAN] `rtr-deeplink` (the production resolver) has SIGABRT-crashed (status 134) at least 13 times since 2026-08-30, with at least 3 confirmed real outages — and 2 of those 3 have no matching Render alert at all, so the true rate may be higher than what's counted. Needs Render's own crash logs and memory graph, which only Ryan can pull.**
  - **Issue**: identical "Exited with status 134" Render alerts recurring roughly every 5-12 hours from 2026-08-30 16:54 UTC through at least 2026-09-05 08:45 UTC (13 occurrences counted across ~6 days). Root cause is unconfirmed — nothing in `app/` shows explicit signal handling, `faulthandler`, or a multi-worker uvicorn config, and a SIGABRT from a CPython process usually means a native-extension fault (this app's C-extension deps are aiohttp/uvloop/asyncpg/PyAV) or an allocator abort under severe memory pressure. The latter has real precedent on this exact service: `rtr-deeplink` runs on `plan: starter` (512MB) — Ryan bumped it to `standard` after a 2026-08-25/26 memory-pressure crash investigation (`BACKLOG_DONE.md`, "Four Render-dashboard `[HUMAN]` items walked through live with Ryan") then reverted to starter the same day, betting that WO-80's health-check fix (landed the same night) would relieve the pressure — with an explicit note to revisit "if the same crash pattern recurs post-WO-80." It has. A second, possibly-related data point: Sentry **PYTHON-FASTAPI-1C** (`OSError: [Errno 9] Bad file descriptor` inside uvloop's `TCPTransport.get_extra_info` → `_get_socket`, 2026-09-01 20:48 UTC, same `srv-d9qhdobm8hqs738fgkog` service) is a separate C-level fault inside uvloop's own socket-handle code — no timestamp lines up with a known crash, but it's at minimum consistent with the same native-fault hypothesis.
  - **Impact**: 3 confirmed real UptimeRobot DOWN/UP outages now — 2026-09-01 11:57:22-12:07:31 UTC (~10 min, 10-11 min after a captured 11:46:53 crash alert); 2026-09-04 22:42:30-22:47:34 UTC (~5 min, `rtr-deeplink.onrender.com/api/health/resolve-check`); 2026-09-04 23:34:12-23:39:17 UTC (~5 min, `redtaperecordings.com` itself). Only the first has a plausibly-matching Render "server failure" alert inside a tight window — the other two don't line up with any captured alert within a reasonable margin, meaning the 13-alert count is very likely an undercount of the true crash rate, not the full picture.
  - **Next action**: pull Render's real crash/exit logs for `rtr-deeplink` — ideally around 2026-09-04 22:42 or 23:34 UTC, since neither of those has a matching alert to anchor the search on otherwise — for the actual abort traceback, and check its memory-usage graph around the same windows the same way the 2026-08-25/26 and WO-94/95 worker investigations did. This Routine's tools can't reach either.
  - **New data point (2026-09-05, from Ryan pasting the actual around-the-crash log for the first time)**: instance `8kp2j` exited status 134 at 8:05 AM local, **several minutes after a manual redeploy** — the first time a crash has been directly correlated with a fresh deploy rather than steady-state traffic. The pasted log shows only the aftermath (`Unclosed client session`/`Unclosed connection` to the Archive, `Unexpected error 9 on netlink descriptor 20` — GC-finalizer noise from the abrupt kill, not its cause) followed by Render's restart line; the actual abort still isn't in application-level stdout, confirming this needs Render's own crash log same as before. One thing the restart sequence *does* show: the fresh instance had to runtime-self-heal a missing Chromium binary (`headless_browser.py`'s existing, documented self-heal path, `warm_up_headless_browser()` at startup) before serving normally — consistent with Render having provisioned a genuinely new container rather than restarting the same one in place, which is worth mentioning to Ryan as a possible detail for whoever reads the real crash log, not a cause on its own.
  - **History**: `BACKLOG_DONE.md` ("Four Render-dashboard `[HUMAN]` items walked through live with Ryan," 2026-08-29 — the starter-vs-standard decision this recurrence should revisit). First flagged by the inbox-triage Routine 2026-08-30; recurred and updated in the 2026-08-31, 2026-09-01, 2026-09-03, and 2026-09-05 runs; redeploy-correlation data point added 2026-09-05 from Ryan's own pasted log.

- **[HUMAN] Dismiss the GitHub secret-scanning alert on `tests/fixtures/civicplus/durham_agendacenter_citycouncil.html:103` — confirmed false positive, no RTR secret involved.**
  - **Issue**: the flagged "Google API Key" is Durham NC's own public `GoogleMapsKey`, embedded in a real, live-fetched HTML fixture of Durham's own CivicPlus AgendaCenter page (exactly the "real fixture from a real live page" this repo's testing convention requires) — not an RTR credential. The alert's own "Public leaks" section lists the identical key already present in five unrelated public repos that scraped the same page, confirming it was already public before this repo's fixture captured it.
  - **Impact**: nothing to rotate, but the alert keeps showing as "Action needed" in GitHub's Security tab until dismissed.
  - **Next action**: dismiss the alert in GitHub's Security tab with reason "Used in tests." This Routine holds no GitHub write access for this, and dismissing a secret-scanning alert is a judgment call, so it's Ryan's to close.
  - **History**: flagged by the inbox-triage Routine's 2026-08-31 run.

### Decisions about already-live content

- **[NEEDS-AUDIT] `[BIG]` Repetition-loop transcript-defect population — residual work after the 2026-08-31 repair run.**
  - **Issue**: `scripts/repair_repetition_loops.py` ran for real
    2026-08-31 once WO-87 deployed — 14 of 18 scanned candidates had
    confirmed loops, all 14 repaired, 0 failed. Both halves of this
    defect population (seam-duplication, 111/111; repetition-loop,
    14/14) are now done.
  - **Impact**: three residual sub-tasks not covered by that run.
  - **Next action**: (1) trim the 3 remaining hallucinated-default
    transcripts that aren't Kitchener (e.g. Sacramento — Kitchener
    itself was re-transcribed 2026-08-30) — not started; (2) put
    anything the repair can't fix on the re-transcription report — not
    started; (3) extend the repair to the local-batch population by
    scanning stored segments instead of job records, since
    `scripts/transcribe_backlog_locally.py` never touches
    `transcription_jobs` — not started.
  - **History**: full run detail (per-page drop counts, the 18-vs-~74
    candidate-pool gap) is in `BACKLOG_DONE.md`. Full bug history — the
    unbounded-`limit` query fix and the WO-87 event-loop fix — is also
    there, WO-84 and WO-87.

## Open bugs — real, root cause not settled `[NEEDS-AUDIT]`

Reproduced against real data, but the fix is a genuine open question.
Jurisdiction-extraction bugs live under **Platform & jurisdiction
coverage** instead — that section name is currently stale (no `##
Platform & jurisdiction coverage` heading actually exists in this file;
its entries appear to have been folded in here at some point without the
routing text above being updated) — worth a real fix the next time
someone reorganizes this file, not attempted here since it's a bigger
structural change than the two entries below.

- **[NEEDS-AUDIT] A `tenant_overrides.csv` pin only affects future
  resolutions — nothing retroactively re-applies it to already-archived
  pages, and the one tool meant to make that reliable doesn't track
  every pin.**
  - **Issue**: fixing Edmonton (AB) and Niagara Falls (ON) — both the
    same wrong-country-collision bug as Abbotsford BC/WI — required
    deleting and resubmitting 6 pages by hand, then hand-writing 2 tenant
    pins directly into `tenant_overrides.csv`. Checked afterward whether
    the standard recovery path would have caught these two hosts:
    `reports/pin_worklist_hosts.txt` (the file
    `scripts/backfill_gov_id.py --hosts-file` is documented to use)
    **does not contain either host**, because they were added by hand
    outside `scripts/apply_pin_worklist.py`'s own workflow, which is the
    only thing that currently writes that file. A pin added any way
    other than through that one script's own run is invisible to the
    one mechanism meant to re-sync already-ingested pages against it.
  - **Impact**: every pin added outside a `apply_pin_worklist.py` batch
    (which includes every pin found by direct investigation rather than
    the worklist process — Abbotsford, Edmonton, Niagara Falls, and
    likely others already in the file from earlier sessions) needs its
    own by-hand `--hosts` backfill, discovered and run by whoever
    happens to remember it exists. Nothing durable tracks "these hosts
    have a pin newer than the last backfill that touched them."
  - **Next action**: not settled — Ryan wants to think through the
    right shape rather than build the first idea. **One approach
    considered and explicitly rejected**: wiring an unscoped
    `backfill_gov_id.py --apply` into the Archive's `preDeployCommand`
    (the same way `alembic upgrade head` already runs there), so every
    deploy re-syncs the whole corpus against whatever the registry
    currently says with zero manual step. Ryan's call: not that way —
    don't re-propose it without a new reason. Worth exploring instead:
    something that tracks which hosts have a pin more recent than their
    last backfill (so a human-triggered run stays complete without
    needing `reports/pin_worklist_hosts.txt` to happen to be current),
    or making `apply_pin_worklist.py`'s own hosts-file writer pick up
    hand-added `tenant_overrides.csv` rows too rather than only the ones
    it just wrote itself.
  - **Constraint**: don't build the `preDeployCommand` version — see
    above, already declined.
  - **History**: found 2026-09-05 fixing Edmonton/Niagara Falls; not yet
    in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] Phase 2d's signal-based recovery (WO-110,
  `scripts/score_gov_signals.py`) needs a human review step before any
  apply mode is built, not just a straight "recovered → write it"
  pipeline — confirmed by two real wrong-level matches in its own
  first report.**
  - **Issue**: applying 5 of WO-110's "recovered" pages by hand
    (2026-09-05) found 2 of the 5 were the wrong *level* of government,
    not just the wrong place — the `org_names` signal has no way to
    tell "this name matches a real place" apart from "this org IS that
    place's own government." Checked both against the real archived
    page before applying anything: id 335 "L. A. World Airports - Board
    of Airport Commissioners" would have been folded into plain
    `us:place:0644000` (Los Angeles, CA) — the real page names its own
    Board of Airport Commissioners individually and cites "Los Angeles
    City Charter Section 503(a)" as its own enabling authority, the
    same "own governing board / own enabling statute" shape decision D2
    already grants LADWP its own identity for. id 757 "Arkansas Supreme
    Court" would have been folded into `us:county:05001` — a real
    Arkansas county that coincidentally shares the word "Arkansas"; the
    actual page is a state supreme court case ("State of Arkansas...
    from Washington County Circuit Court"), which per decision D1
    belongs under the State of Arkansas as a `meeting_body`, not any
    county. The other 3 of the 5 (Oak Ridge TN, DeLand FL, Live Oak TX)
    were clean, exact, correctly-leveled matches and were applied.
  - **Impact**: an unreviewed apply mode built directly from WO-110's
    scoring output would have silently written 2 wrong identities (of
    5 checked — a 40% miss rate on this small sample, not something to
    extrapolate a rate from, but not negligible either) alongside the 3
    correct ones, with nothing distinguishing them in the output.
  - **Next action**: Ryan's call, recorded here so it isn't lost —
    **any apply mode needs a human review step between the confidence
    score and actually writing**, at least while it's being tested.
    Worth scoping a way to auto-sort the queue by risk rather than
    review all of it blind: a recovered government whose name is an
    exact or near-exact substring of the raw extracted text (Oak Ridge
    TN, DeLand FL, Live Oak TX's shape) is a very different confidence
    class from one where the match came from a *different* string found
    somewhere else on the page (LAWA, Arkansas Supreme Court's shape) —
    the second class is exactly where a name can validate against a
    real, unrelated place. Counting how many of WO-110's 102 recovered
    pages are which shape would say whether "auto-apply the exact-match
    ones, queue the rest" is a small manual backlog or a large one.
  - **Constraint**: don't build a straight apply mode (score → write)
    without the review step above — this entry exists specifically
    because that shape already produced 2 wrong answers out of 5 on the
    first hand check.
  - **History**: found 2026-09-05 applying WO-110's report by hand
    while answering a question about the Edmonton/Niagara Falls fix;
    not yet in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] `RuntimeError: Response content shorter than
  Content-Length` on the resolver, seen twice in one production log
  (2026-09-05) on two different routes.**
  - **Issue**: Ryan pasted a real Render log window that shows this
    exception raised twice, both times inside
    `starlette/middleware/base.py`'s `BaseHTTPMiddleware.__call__` →
    `starlette/responses.py:167`'s plain (non-streaming) `Response.
    __call__`, on `GET /api/health/resolve-check` and `GET /` — a
    `Content-Length` header disagreeing with the actual body bytes sent.
    `app/main.py`'s `handle_head_requests` middleware
    (`@app.middleware("http")`, which Starlette implements via
    `BaseHTTPMiddleware`) wraps every single request through this repo's
    resolver service, so it's the one shared thing both failing routes
    have in common — not confirmed as the actual cause yet, just the
    common factor visible from the log alone.
  - **Impact**: unconfirmed how often this fires or whether it's user-
    visible (a broken/truncated page load vs. a clean retry) — only
    known from this one pasted log window, not independently reproduced
    or measured against Sentry/UptimeRobot yet.
  - **Next action**: check Sentry for this exact `RuntimeError` string to
    get a real occurrence count and see if it correlates with anything
    (a specific route, a response size, gzip). If `handle_head_requests`
    is confirmed as the trigger, the fix is probably to stop
    unconditionally wrapping every request in `BaseHTTPMiddleware` for
    the (rare) HEAD case and instead route HEAD handling some other way
    that doesn't re-stream every GET too.
  - **Constraint**: don't assume this is related to the SIGABRT/status-134
    crash entry above just because both came out of the same pasted log
    — they're different failure shapes (a process-level abort vs. an
    HTTP-protocol-level assertion inside a request handler) with no
    evidence connecting them beyond appearing in the same window.
  - **History**: found 2026-09-05 from Ryan sharing a real Render log
    after a redeploy; not yet in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] Several already-archived pages carry a confidently-
  wrong `gov_id` from before the cross-border name-collision guard
  existed, and have never been re-backfilled since — the guard is
  correct today, but a page resolved before it landed is still wrong.**
  - **Issue**: `/m/abbotsford-wi-2025-06-24-council-meeting` (page 812)
    is a real Abbotsford, **British Columbia** council meeting (agenda
    items reference "Abbotsford Mission Highway 11" and real BC rezoning
    applications; the AI transcript even mentions the Abbotsford
    Canucks), keyed `us:place:5500100` — Abbotsford, **Wisconsin**, a
    village of a few thousand. `app/utils/gov_registry/resolver.py`'s
    national-table lookup has an explicit guard for exactly this shape
    (`if not state and tables.ca_csd().lookup(name, None): return None`
    — a bare name with no state that also exists in the Canadian table
    declines rather than confidently picking the US one) and its own
    code comment names this precise case among "16 real rows" a
    2026-09-02 audit found: Abbotsford BC/WI, Edmonton AB/KY, Niagara
    Falls ON/NY, Langford BC/SD, White Rock BC/SD, Port Hope ON/MI (3
    more — Nampa ID, New Carlisle OH, Hawarden IA — are confirmed
    genuinely American despite a same-named Canadian place, which is why
    the guard declines rather than auto-picks either side). Confirmed
    live 2026-09-04 that today's code gets it right:
    `resolve_government("Abbotsford", tenant_host="pub-abbotsford.escribemeetings.com")`
    returns `unresolved`, not the Wisconsin village. The guard's own
    commit (`27e0c8f0`, WO-99/#696, merged 2026-09-03 11:26 UTC) predates
    the page's last write (`updated_at` 2026-09-03 12:23 UTC, i.e. from
    the WO-99/WO-100 wholesale backfill itself) by about an hour — so by
    plain chronology the guard should have already been live when this
    row was written, and exactly why it wasn't is still an open
    question (a deploy-timing gap between merge and the Render rollout
    actually used by that `--apply` run is the leading guess, not
    confirmed). Not a currently-active resolver bug — a stale row the
    ladder would no longer produce if asked today.
  - **Impact**: at least one live page shows the wrong government and
    country on its own `/m/` page and would file under the wrong state
    on `/state/wisconsin` instead of not appearing there at all pending a
    real fix. Scope of the other 5 named collisions is unverified — they
    may be equally stale, already caught by a later backfill, or fine;
    nobody has checked since 2026-09-02.
  - **Next action**: `scripts/backfill_gov_id.py`'s own stated design
    ("skip rows already current... a run after a registry change re-does
    exactly the rows whose answer moved") means a plain unscoped re-run
    from the Archive's Render shell should catch and correct this row
    (and the other 5, if equally stale) automatically — it recomputes
    fresh and compares, it doesn't trust the stored tier. Worth doing as
    a full sweep rather than one-off pins, specifically because the
    other 5 names haven't been checked. `pub-abbotsford.escribemeetings.com`
    itself would settle to `unresolved` after a re-run (bare "Abbotsford"
    stays ambiguous by design) unless also given a tenant pin to
    `ca:csd:5909052` — a single-government eScribe host, no `match`
    needed.
  - **Constraint**: don't hand-fix this one row in isolation without
    also re-running the backfill broadly — a one-off pin fixes the
    symptom Ryan happened to notice and leaves the other 5 named
    collisions (and any other page resolved in that same pre-guard
    window) exactly as wrong and exactly as invisible.
  - **History**: found 2026-09-04 answering a user question about
    `/m/abbotsford-2025-06-24-council-meeting` showing no state; not yet
    in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] eScribe serves the same meeting under multiple
  `Agenda=` query-string values, and each one archives as a separate
  page.**
  - **Issue**: `pub-abbotsford.escribemeetings.com`'s real meeting
    `Id=c157e0a4-351f-49f2-bd63-bc0747196fed` exists as two full,
    separately-archived pages — `?Agenda=Merged&Id=...` (page 812) and
    `?Agenda=Agenda&Id=...` (page 2225) — identical agenda and
    transcript, different `source_url_normalized`, so nothing currently
    treats them as duplicates of each other. Checked the corpus for the
    same shape (same eScribe `Id=`, different `Agenda=` value) and found
    **7 such pairs** across 6 hosts as of the 2026-09-03
    `reports/gov_registry_scoring_2026-09-03/sheet_archive.csv` snapshot:
    `pub-forterie` (`Agenda`/`Addendum`), `pub-oshawa`
    (`PostMinutes`/`Agenda`), `pub-abbotsford` (`Merged`/`Agenda`),
    `pub-peelregion` (`Agenda`/`PostAgenda`), `pub-townshipofbrock`
    (`Merged`/`Agenda`), `pub-marvinnc` (`PostMinutes`/`Agenda`),
    `pub-sandag` (`PostMinutes`/`Agenda`). Same shape as BACKLOG.md's
    existing "same YouTube video, two URL forms" entry, different
    platform.
  - **Impact**: 7 known real duplicate archived meetings (14 pages for 7
    real events) — double-counted in per-jurisdiction page counts,
    double the storage/transcription cost per meeting, and a reader
    landing on either copy has no link to the other. Likely undercounts
    the true total since this was checked against one day's snapshot,
    not the live corpus.
  - **Next action**: at ingest time, treat `Agenda=`'s value as
    something to strip (not compare) when checking whether an eScribe
    `Meeting.aspx?Id=...` URL has already been archived — the `Id=` GUID
    alone identifies the meeting; `Agenda=` only selects which document
    view eScribe renders for it. Needs a real duplicate-merge pass for
    the 7 already-archived pairs, not just a forward-looking ingest fix.
  - **Constraint**: don't assume `Agenda=Agenda` is always the
    "canonical" one to keep — `PostMinutes`/`PostAgenda`/`Merged` may
    carry a fuller or more final document for some meetings; check
    content before merging a pair.
  - **History**: found 2026-09-04 investigating the Abbotsford
    duplicate above; not yet in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] A `strength=fallback` tenant pin cannot correct a
  confidently-wrong extraction on a confirmed-misleading host — the
  ladder validates a plausible wrong answer before the pin ever gets a
  chance to apply.**
  - **Issue**: `pub-gloucesterva.escribemeetings.com` is Gloucester
    County, VA's eScribe host, pinned `strength=fallback` to
    `us:county:51073` (added in #707, fixing a name-only host-matching
    bug). Fallback strength only applies when steps 2-4 of the resolver
    ladder (`GOVERNMENT_IDENTITY_ARCHITECTURE.md` §5) produce nothing —
    by design, so a real per-page extraction always wins over a tenant
    default. But eScribe GUID meeting URLs give `match` nothing to
    discriminate on, and this host's own page text ("School Board
    Meeting") resolves confidently, and wrongly, to `us:place:2526150`
    (Gloucester, **MA** — the exact name-bleed #707 fixed upstream,
    still baked into that one already-ingested candidate/page). The
    fallback pin never even gets consulted, because the ladder didn't
    fail — it succeeded at the wrong government. §4 predicted this
    exactly: "a plausible wrong extraction passes validation, so
    validation alone can never fix a confirmed-misleading host."
  - **Impact**: **the one live instance is fixed** — page 4097 (the
    `/j/gloucester-ma` page) was moved to `us:sd:5101620` via
    `POST /internal/jurisdiction/override` on 2026-09-03, confirmed live
    over `/internal/export/pages` (`gov_id: us:sd:5101620,
    jurisdiction_confidence: manual_override`); the tenant pin's proposed
    blank-`match`/`authoritative` rule was **not** copied into
    `tenant_overrides.csv`, per the constraint below. The `/j/gloucester-
    ma` → `/j/gloucester-county-public-schools-va` redirect needed a
    second fix: `scripts/score_gov_registry.py` cannot regenerate that
    row on its own (verified — it re-derives old/new from the same
    stored `jurisdiction` string, so a single-page manual override is
    invisible to it either before or after the override runs), so the
    row was **hand-added** to `archive/data/hub_slug_aliases.csv`, marked
    in its own `evidence` field as a deliberate exception. **This means a
    future wholesale regen of that file will silently drop the row** —
    whoever next runs `score_gov_registry.py` needs to re-add it (or fix
    the tool to be `manual_override`-aware first). This entry tracks the
    general failure mode, which stays open: any tenant whose URL shape
    carries no discriminator (eScribe GUIDs are the known case) and whose
    page text names a real place that collides with a different
    government's name is exposed the same way, and a `strength=fallback`
    pin gives no signal that it happened — the ladder reports `registry`
    tier (confidently resolved), not `unresolved` or `blank`.
  - **Next action**: **checked against Phase 2d's live run (WO-110,
    2026-09-04) — the current signals mechanism does NOT recover this
    case, and that's expected, not a gap in that pass.** Page 4097 is
    `manual_override` tier today, so it isn't in 2d's live corpus (only
    `unresolved`/`unverified` are); reconstructing its pre-override raw
    string ("Gloucester, MA", the exact bled value this entry describes)
    and running it through `extract_gov_signals()` +
    `resolve_government(signals=...)` confirms why: the plain ladder
    still lands `registry` tier on `us:place:2526150` (confidently, and
    wrongly) with no `signals` at all, and `resolve_government()`'s own
    hard constraint (`resolver.py`'s WO-105 comment block) skips the
    signals-enhancement pass entirely whenever the plain ladder already
    answered `registry`/`pinned` — by design, so it can't be the thing
    that catches a *confidently wrong* national-table hit. This is
    exactly the "validation alone can never fix a confirmed-misleading
    host" problem this entry already names, now confirmed against the
    real page rather than reasoned about in the abstract, and it's a
    Step B question (does something get to run to challenge an
    already-`registry` answer, and on what evidence) — not a Phase 2d
    Step A defect. A secondary, minor finding from the same check:
    `gov_signals.py`'s `_TYPE_WORDS` list has "Board of Education" but
    not the bare "School Board" this page's own title/nav actually use —
    moot for Step A either way (extracted `type_words` aren't consumed by
    any resolution decision yet, per that module's own docstring), worth
    fixing whenever Step B starts consuming them. The hand-added
    hub-alias row is a real, separate tooling gap worth its own small fix
    eventually (teach `score_gov_registry.py` to pass a `manual_override`
    row's DB gov_id straight through as "new" instead of re-deriving it),
    but not attempted here — out of scope for a two-page live fix.
  - **Constraint**: do not touch the `gov-signals-r1` branch, promote the
    existing tenant pin to `strength=authoritative`, or copy
    `POST /internal/jurisdiction/override`'s proposed
    `tenant_overrides.csv` rule (blank `match`, `strength=authoritative`,
    `gov_id=us:sd:5101620`) into the committed registry when applying
    WO-106's fix. Either one pins the whole tenant, including the Board
    of Supervisors' own meetings on that host (2 pages archived today —
    one county, one this wrongly-keyed one — plus every one this
    Archive hasn't ingested yet), to whichever single government wins,
    misfiling the other. The fallback pin is correctly doing its one job
    (a sane default where `dominant_gov_id()` ties 1-1) and should stay
    exactly as it is; the school-district fix belongs on the one
    affected page only, via that same endpoint's per-page write.
  - **History**: `~/Documents/rtr-business/research/
    STATE_gov_identity.md`'s "STILL OPEN: FINDING-11" section (Cowork
    review, 2026-09-03); `GOVERNMENT_IDENTITY_ARCHITECTURE.md` §4, §5.
    WO-110 (2026-09-04) ran Phase 2d's live corpus scan (604 target pages,
    300-page control, 102 real recoveries, 0 control regressions after a
    resolver round-trip fix — see `JURISDICTION_METADATA_PLAN.md`'s
    Phase 2d section) and, per this entry's own "add to corpus" note,
    specifically checked page 4097 against it — see Next action above for
    the (negative, expected) result.

- **[NEEDS-AUDIT] `scripts/score_gov_registry.py` overwrites
  `archive/data/hub_slug_aliases.csv` wholesale every run, so a second
  run can silently drop or corrupt a real, currently-serving redirect
  from an earlier run — not just the known `manual_override` blind spot
  above, but any row whose source page has since been re-backfilled.**
  - **Issue**: the script never reads the file it's about to overwrite —
    it derives every row fresh, per run, from `old_hub_slug =
    jurisdiction_hub_slug(CURRENT stored jurisdiction string)` vs `new_
    hub_slug = resolve_government(that same string)`. The FIRST run after
    a backfill can see genuine pre-backfill/post-backfill pairs; every
    run after that sees only ALREADY-backfilled strings, so a page whose
    retirement was captured once becomes permanently invisible to future
    runs (exactly what `hub_aliases.py`'s own docstring warns about, but
    the blast radius turned out to be the whole file, not one row). WO-109
    (2026-09-03) re-ran the script against production and confirmed
    it directly: of 672 previously-committed rows, a naive overwrite
    with the fresh run's 57-row output would have dropped **615** of
    them — real, currently-necessary redirects with no way to
    reconstruct them from the database again.
  - **Impact**: no damage today — WO-109 wrote a merge (keep every
    existing row, add only genuinely-new `old_slug`s) by hand instead of
    running the script's own overwrite, so the committed file lost
    nothing. But that merge is currently a one-off manual step, not
    something the tool does, so the very next person who runs
    `scripts/score_gov_registry.py` in the ordinary documented way (no
    special care) will regress this — silently, since the script prints
    a row count and nothing else, and a smaller "57 retired slugs"
    number reads as normal output, not a warning.
  - **Next action**: teach `_write_hub_slug_aliases()` to read the
    existing committed file first and union with the freshly-derived
    rows (existing row wins unless proven stale) instead of overwriting,
    the same merge WO-109 did by hand — see that PR's description for
    the exact logic and the three ambiguous cases (below) it had to
    reason through manually.
  - **Constraint**: a union isn't quite enough on its own — WO-109 also
    hit 3 real cases (`hamilton`, `victoria`, `woodland`) where the SAME
    bare `old_slug`, computed from two different tenants' raw
    jurisdiction text at two different points in time, legitimately wants
    two different destinations. Any fix needs a documented tie-break
    rule, not silent last-write-wins. **Update (WO-112, 2026-09-03):**
    2 of the 3 are no longer "kept safe at incumbent" — Ryan reviewed the
    live site after the WO-107 backfill and gave an explicit, direct
    call: `hamilton` now points to `hamilton-city-oh`
    (`us:place:3933012`) and `woodland` now points to `woodland-wa`
    (`us:place:5379625`), superseding WO-109's cautious default. Both old
    incumbent destinations (`hamilton-police-services-board-on`,
    `woodland-ca`) remain real, live hubs at their own unambiguous slugs
    — re-verified via `display.hub_slug()` on their own gov_ids before
    the flip — so nothing is orphaned, they're just no longer reachable
    via the bare, ambiguous slug. `victoria` is UNCHANGED: Ryan did not
    mention it, and it stays flagged for him per the note below (a
    genuinely different case — `victoria-bc` may itself be the wrong
    committed value, not just the less-preferred one). A durable
    tie-break rule for the *general* case (which of two colliding raw
    strings wins a bare slug) is still not built — WO-112 only resolved
    these two specific instances by direct instruction, it did not add a
    policy the tool applies on its own next run.
  - **History**: found and worked around by hand in WO-109's PR
    (2026-09-03); hamilton/woodland flipped by hand in WO-112's PR
    (2026-09-03) per Ryan's direct instruction. See both PRs'
    descriptions for the full row-by-row reasoning and before/after
    values.

- **[NEEDS-AUDIT] `scripts/score_gov_registry.py` can't see `match`-
  scoped `tenant_overrides.csv` pins, so its `hub_slug_aliases.csv` regen
  silently drops the retiring-slug redirect for any government that was
  only pinned that way.**
  - **Issue**: `score_rows()` (and `_seed_governments()`) call
    `resolve_government(jurisdiction, tenant_host=host,
    tenant_gov_id=...)` with no `path`/`page_hints` argument. Those two
    are exactly what `_pinned()` (`app/utils/gov_registry/resolver.py`)
    needs to match a `tenant_overrides.csv` row whose `match` column
    names a specific video id or TelVue org token rather than being
    blank — so the script can only ever see host-level pins, never
    `match`-scoped ones. WO-107 (#712) added 5 such groups (24 `youtu.be`
    ids → Woodside CA, 10 `youtu.be` ids → Hillsborough CA, 3
    `www.youtube.com` ids → Phoenix AZ, 2 `videoplayer.telvue.com` org
    tokens → Centre County PA and Summit NJ), and WO-109's regen the same
    day (#714) missed all 5 — confirmed by checking its own committed
    `reports/gov_registry_scoring_2026-09-03/sheet_archive.csv`: all 5
    pages still show `jurisdiction_confidence: unresolved` and a blank
    `gov_id` in that snapshot.
  - **Impact**: no live 404s today — WO-112 (2026-09-03) hand-added the
    5 missing redirect rows to `archive/data/hub_slug_aliases.csv` from
    that same pre-backfill snapshot before `scripts/backfill_gov_id.py
    --apply` erased the only source that could reconstruct them. But
    this is a real, general gap: any FUTURE `match`-scoped pin will hit
    the identical blind spot the next time someone runs
    `score_gov_registry.py` in the ordinary documented way, with no
    warning that it happened (same silent-drop shape as the wholesale-
    overwrite entry above, different root cause).
  - **Next action**: thread `path`/`page_hints` through
    `score_rows()`/`_seed_governments()` the way `page_hints_for()`
    (`resolver.py`) already builds them from a `MeetingPage` in
    production — the export payload would need the source URL fields
    `page_hints_for()` reads (it currently fetches only the light
    metadata shape, deliberately, per its own docstring on
    `fetch_export_pages()`) — then re-run the script and confirm the 5
    WO-107 rows above appear in its own regenerated output rather than
    needing another hand-add.
  - **Constraint**: don't build this against a fresh `/internal/
    export/pages` pull to verify — after `backfill_gov_id.py --apply`
    runs, every WO-107-pinned page's stored `jurisdiction` is already the
    registry display name, so a fresh export can no longer show the
    before/after gap this bug produces. Verify instead against the
    committed `sheet_archive.csv` snapshot above, or a newly-crafted
    synthetic case using a real, currently-unpinned `match` value.
  - **History**: found and worked around in WO-112's PR (2026-09-03);
    see that PR's description.

- **[NEEDS-AUDIT] `civicplus.py`'s `resolve()` has no encoding fallback
  on `response.text()`, crashing on a non-UTF8 CivicPlus response.**
  - **Issue**: `CivicPlusAssetFinder.resolve()` (`app/platforms/
    civicplus.py:68`) calls `await response.text()` with no `encoding=`
    argument and no fallback; a real CivicPlus `DocumentCenter` PDF-view
    response came back non-UTF8 and raised a raw `UnicodeDecodeError:
    'utf-8' codec can't decode byte 0xe2 in position 10: invalid
    continuation byte`, confirmed live 2026-09-01 resolving
    `https://ga-richmondhill2.civicplus.com/DocumentCenter/View/5032/
    City-Charter-Updated-2021` (reached via `generic_fallback.py`
    delegating a candidate link it found on `richmondhill-ga.gov/
    agendacenter`).
  - **Impact**: not a production crash today — both call sites that can
    reach this (`/api/resolve`'s top-level `except Exception` in
    `app/main.py`, and `generic_fallback._try_delegate_to_known_platform`'s
    own `except Exception` swallow) already catch it gracefully. The real
    cost is a silently-failed delegation attempt (logged as a `warning`,
    not surfaced) on any CivicPlus tenant whose only outbound-link
    candidate happens to be a non-UTF8 document view rather than a real
    meeting page — an undercount in exactly the kind of has_video=yes
    CivicPlus resolve this project is trying to get right (see the
    §49/coverage_map.csv Phase 1 sweep, `~/Documents/rtr-business/
    research/ENUMERATION_METHODS.md`).
  - **Next action**: decode with `encoding=response.get_encoding()` (or
    a `charset_normalizer`/`chardet` guess) falling back to `errors=
    "replace"` rather than raising, the way a real browser would render
    a mis-served page instead of refusing it outright; needs a second
    real non-UTF8 CivicPlus sample beyond this one before generalizing
    the fix, per this project's own "never build from one example" rule.
  - **History**: found during the §49 Phase 1 coverage_map.csv resolve
    sweep, 2026-09-01 (not yet in `BACKLOG_DONE.md` — this is the first
    record of it).

- **[NEEDS-AUDIT] The same YouTube video submitted via two different URL
  forms creates two separate Archive pages instead of deduping.**
  - **Issue**: Yamhill County, OR's real meeting video
    (`youtube.com/live/3dVHe0r2utc`) was submitted twice during tonight's
    tier1/2 ingest batch — once via the jurisdiction's plain
    `AgendaCenter` URL (which delegates to the YouTube video), once via
    the video's own direct YouTube URL. Both real-ingested successfully,
    but instead of the second submission recognizing the same underlying
    video and updating/reusing the existing page, it created a second,
    separate `MeetingPage` with a different segment count (1,726 vs 757)
    and a title/slug mismatch on the older of the two.
  - **Impact**: two live pages for the same real meeting — confusing for
    a reader who finds either one, and it undercounts real dedup
    coverage the same way a naive per-URL cache key would (the two
    submitted URLs are textually different even though they resolve to
    the identical video). Segment-count divergence (1,726 vs 757) also
    suggests the two ingests captured the transcript at different
    completeness, worth checking which is the better version before any
    fix consolidates them.
  - **Next action**: dedup key should be the resolved video identity
    (e.g. the YouTube video ID) rather than (or in addition to) the
    submitted source URL, so a second submission that resolves to an
    already-ingested video updates/merges rather than creating a new
    page. Needs a decision on which of the two existing Yamhill County
    pages to keep (or how to merge) before any fix ships, plus a
    one-time cleanup pass for this specific pair via the existing
    `POST /internal/admin/delete-pages` / reslug tooling.
  - **History**: found during tonight's Track A tier1/2 ingest batch
    (`~/Documents/rtr-business/research/coverage_gap_2026-09-01/
    track_a_tier12_ingest_RESULTS.csv`), 2026-09-01 — not yet in
    `BACKLOG_DONE.md`, this is the first record of it.

- **[NEEDS-AUDIT] `[BIG]` No automated "pick the best candidate" step
  exists anywhere in the resolve pipeline — the same root cause behind
  the Yamhill duplicate above and several other real bugs from the same
  night.**
  - **Issue**: `app/platforms/base.py`'s `CalendarPageError` mechanism
    already does real candidate-scanning inline inside `resolve()` for 5
    platforms (`civicplus.py`, `legistar.py`, `municode_meetings.py`,
    `tampa.py`, `vimeo.py`) — it finds every real meeting candidate on a
    listing/calendar page, but the moment there's more than one, it
    raises with the candidate list and stops. That's built entirely for
    a human viewer to click on the frontend. There is no code path that
    automatically picks a candidate for an unattended batch/ingestion
    script. Confirmed live 2026-09-01 across two full sweeps
    (`~/Documents/rtr-business/research/coverage_gap_2026-09-01/
    track_a_tier12_ingest_RESULTS.csv` and
    `track_a_964_resolve_known_url_RESULTS.csv`) and one enumeration
    session's full read of all 7 `CalendarPageError`-using platform
    files.
  - **Impact**: real, repeated damage in a single night's tier1/2 ingest
    batch alone — two fake pages ingested as real meetings (Chester
    County SC's tourism promo, Douglas County WI's instructional video,
    both from a bare "most recent" pick with no verification), 3 rows
    that resolved to a different meeting than what was reviewed because
    "most recent" is re-evaluated fresh every run with no stable
    candidate list to point at, the Yamhill County OR duplicate-page bug
    above, and 56 rows across two sweeps (5 + 51) that came back as
    errors specifically because a guessed link landed on a tenant's
    homepage rather than a specific meeting — a real candidate list was
    never built for any of these, so nothing had anything to pick from.
  - **Next action**: two real, independent fixes, either worth doing on
    its own: (1) build an automated picker (title/date heuristics, or
    "prefer the most recent title that looks like a real government
    meeting") that consumes the same candidate list `CalendarPageError`
    already produces for its 5 platforms, so a batch script gets a real
    answer instead of either guessing outside this mechanism or failing;
    (2) port the proactive per-tenant listing technique already
    live-verified in the sibling `rtr-discovery` repo
    (`~/Documents/rtr-discovery/discovery/enumerators/*.py` — 11
    platforms: primegov, civicclerk, civicweb, escribe, legistar,
    youtube_channel, granicus, swagit, iqm2, proudcity, cablecast) into
    this project's own step 2, since the technique (call the tenant's
    own listing API/feed) is proven and reusable even though that repo's
    own job (adding depth to already-covered jurisdictions) is out of
    scope here — only the technique transfers, not the depth-chasing
    behavior. CivicPlus's own general listing (beyond the `/AgendaCenter`
    direct check), TownHallStreams, BoardDocs, TelVue, ChampDS, and
    CivicLive (beyond the reactive picker) still have nothing anywhere,
    not even in `rtr-discovery`; Hyland is a confirmed dead end.
  - **History**: found and written up during a long enumeration-strategy
    session, 2026-09-01 — full detail in
    `~/Documents/rtr-business/research/ENUMERATION_METHODS.md`'s "Step
    2's real weak spot" section (end of file) and its "5 Steps"/"Key
    Scripts" intro. Not yet in `BACKLOG_DONE.md`, this is the first
    record of it.

- **[NEEDS-AUDIT] `[BIG]` Microsoft Teams and Zoom are real, confirmed
  government meeting platforms with zero adapter support — no
  `app/platforms/` module for either.**
  - **Issue**: tonight's StreamText-candidate research (see the entry
    above) independently surfaced multiple real government bodies whose
    actual meeting platform is Teams or Zoom, not any platform this
    project currently resolves: NYC Water Board (Microsoft Teams, live
    join link `teams.microsoft.com/meet/282741341051726`, found in a real
    Sept 2026 meeting-notice PDF), LA County Dept of Mental Health
    Commission (Microsoft Teams meetup-join link, found on
    `dmh.lacounty.gov`), Georgia Vocational Rehabilitation Services board
    (Zoom, `us06web.zoom.us/j/86536611218`, found on `gvs.georgia.gov`).
    Those three are all *live join links*, not archived recordings, so
    none are directly ingestible even with an adapter. Separately
    confirmed live, 2026-09-02: **Rockport, MA's own `.gov` site hosts
    real, archived past-meeting recordings via Zoom's cloud-recording
    share links** —
    [rockportma.gov/598/Recorded-Zoom-Meetings](https://www.rockportma.gov/598/Recorded-Zoom-Meetings)
    lists multiple real `zoom.us/rec/share/...` links across several
    boards (Board of Health, Cultural Council, Historical Commission,
    Planning Board) — this is the shape that would actually be
    ingestible. **No equivalent past-recording example was found for
    Microsoft Teams** despite real search effort (multiple queries,
    2026-09-02) — every real Teams hit found so far is a live join link;
    Teams' own recording model (OneDrive/SharePoint "Recordings" folder,
    access often permission-gated to the org's own tenant) may make
    public past-recording links structurally rarer than Zoom's shareable
    `rec/share` links, but that's inference, not confirmed — worth a
    dedicated search pass before concluding either way.
  - **Impact**: unknown real scope, but not zero — three independent real
    hits in one evening's research on an unrelated task, plus at least
    one confirmed real ingestible-shaped example (Rockport MA/Zoom). Any
    jurisdiction using Teams/Zoom as its primary or sole platform is
    currently invisible to every discovery method in this file, since
    none of them check for these two at all.
  - **Next action**: (1) a small, cheap discovery pass — dork for
    `"zoom.us/rec/share"` + the standard 5 governance-context phrases
    (same proven pattern as TelVue/Cablecast/Vimeo) to gauge real
    population size before committing to adapter work; (2) if that comes
    back with real density, a Zoom adapter is straightforward (the
    `rec/share` URL is a stable, directly-fetchable link) — a Teams
    adapter is a separate, harder question given the permission-gating
    concern above and deserves its own investigation, not an assumed
    parallel build.
  - **History**: found 2026-09-01/02 during the same enumeration session
    as the entry above, while researching StreamText candidates and
    following up on the user's question about competitor
    captioning/accessibility platforms. Not yet in `BACKLOG_DONE.md`,
    this is the first record of it.

- **[NEEDS-AUDIT] A bare YouTube channel/live URL raises a raw
  `ValueError` instead of a clean "not a specific video" message.**
  - **Issue**: `YouTubeAssetFinder`'s `resolve_video_id()` (`app/
    platforms/youtube.py:78`) raises `ValueError(f"Could not find a
    YouTube video ID in {url}")` for a URL shaped like `/channel/<id>/
    live` or a bare `/channel/<id>` with no parseable video ID. Confirmed
    live 2026-09-01 against `https://www.youtube.com/channel/
    UCWnFQlV4Fi0Pv5aqZy_fcPA/live` (Borough of Bernardsville, NJ) during
    the §49 Phase 1 resolve sweep; a second, related shape (`Could not
    find an event ID in URL path: /`) hit repeatedly on CivicClerk/
    Legistar-style URLs missing their event id, same underlying pattern.
  - **Impact**: not a production crash — `/api/resolve`'s top-level
    `except Exception` (`app/main.py:677`) already turns this into a
    `{"error": "resolve_failed", "message": "Could not find a YouTube
    video ID in ..."}` response rather than a 500. The gap is message
    quality: the surfaced text is a raw internal exception string, not
    something a reader (or this project's own resolve-sweep tooling)
    can tell apart from a genuine unexpected failure without string-
    matching on "Could not find".
  - **Next action**: decide whether this is worth a dedicated exception
    type (e.g. `NotASingleVideoError`) that `/api/resolve` renders as a
    distinct, friendlier `error` code — same shape as `CalendarPageError`
    already gets — versus leaving it as-is since the generic
    `resolve_failed` path already prevents a hard crash either way.
  - **History**: found during the §49 Phase 1 coverage_map.csv resolve
    sweep, 2026-09-01 (not yet in `BACKLOG_DONE.md` — this is the first
    record of it).

- **[NEEDS-AUDIT] SLC's `_nearest_topic_text()` silently drops one real
  item per page.**
  - **Issue**: a page's single "highlight" story uses a different HTML
    shape (a promo box, topic text in a preceding heading) than the plain
    pattern other items use, confirmed live.
  - **Impact**: one real item silently skipped per affected page — safe
    failure mode (skipped, not garbage), but a real known gap.
  - **Next action**: walk up to a preceding heading when same-container
    text comes back empty; needs a real design decision about how much
    heuristic fragility on a differently-shaped page is acceptable before
    attempting it.
  - **History**: moved out of Dormant 2026-08-30.

- **[NEEDS-AUDIT] Non-YouTube garbled/truncated pages have no automated
  re-transcription sweep.**
  - **Issue**: corrected 2026-08-31 — this entry was framed as if a manual
    refresh and an auto-requeue mechanism didn't exist; WO-15 (2026-08-16)
    already built both. `POST /api/refresh-archived-page` (`app/main.py:425`,
    public, 1hr cooldown) already lets anyone re-trigger a refresh on any
    archived URL, and `list_youtube_pages_missing_transcripts()`
    (`archive/db/crud.py:1186`) already uses `_has_good_transcript()`, so a
    garbled **YouTube** transcript already resurfaces in
    `fetch_youtube_transcripts.py`'s daily queue and gets auto-promoted.
  - **Impact**: the 11 Granicus-truncation-marked pages (of 31 flagged, per
    the 2026-08-30 `/internal/transcript-quality-audit` count) can't use
    that YouTube-only auto-queue; how many of the 20 garbled-marker pages
    are non-YouTube is unconfirmed.
  - **Next action**: decide whether to build an equivalent automated sweep
    for non-YouTube garbled/truncated pages, or treat the existing manual
    refresh button as sufficient at this bounded (31-page) scale.
  - **History**: WO-15 (`BACKLOG_DONE.md`, 2026-08-16); this entry's own
    framing corrected 2026-08-31 after being moved out of Dormant without
    being re-derived first.

- **[NEEDS-AUDIT] `[LOGIN]` Missing-Playwright-binary error recurred
  2026-08-30.**
  - **Issue**: the 2026-08-09 missing-binary failure (`BrowserType.launch:
    Executable doesn't exist at /opt/render/.cache/ms-playwright/
    chromium_headless_shell-1234/...`) recurred during that day's
    four-service redeploy — root cause still unconfirmed, same as
    `app/platforms/headless_browser.py`'s own docstring has recorded since
    2026-08-09.
  - **Impact**: likely self-healed in-process by `_get_browser()`
    (`playwright install chromium`, once, then retry) — `/api/health`
    polls and startup continued normally — but at the cost of a browser
    download on the first Cloudflare-gated resolve after every deploy.
  - **Next action**: read the resolver's actual build log for the
    `playwright install chromium` step (does it list
    `chromium_headless_shell`?), then hit a known headless-gated resolve
    (Minneapolis LIMS / Wayne County MI) and confirm it works without a
    mid-request download; if the build step skips the headless shell, the
    likely fix is `playwright install chromium --with-shell` or pinning
    `PLAYWRIGHT_BROWSERS_PATH` into the project dir — confirm from the
    build log first rather than guessing a fourth time.
  - **Constraint**: `[LOGIN]` — needs the Render dashboard to read the
    build log.
  - **History**: original finding in `app/platforms/headless_browser.py`'s
    docstring, 2026-08-09.

- **[NEEDS-AUDIT] Search Console "video isn't on a watch page" — Granicus
  and CivicClerk's Azure video host are confirmed, not fixable in this
  app's code.**
  - **Issue**: Granicus's CDN blocks Googlebot's own User-Agent outright
    (real browsers get 200, Googlebot/Bingbot/curl get 403, confirmed on
    two independent tenants); CivicClerk's Azure-hosted video
    (`cpmedia.azureedge.net`) serves `Content-Disposition: attachment`,
    which Google's validator plausibly can't treat as embeddable.
  - **Impact**: together these explain 65% of the real failing population
    in a 1,000-row GSC export (real total 1,764 rows, flat since
    2026-08-24) — Granicus 51.6%, CivicClerk Azure 13.4%. This app's own
    templates already render correct, matching video markup in both cases,
    so there is no template bug to fix. The same Granicus block also shows
    up as Events/Videos rich-result "invalid item" flags in URL
    Inspection, confirmed 2026-08-31 on
    `/m/beaufort-board-of-education-academics-committee` — its "Page
    resources couldn't be loaded" panel shows the Granicus media stream
    itself failing Googlebot's fetch ("Other error"), matching the 403
    finding above; not a new bug, another symptom of the same one.
  - **Next action**: none identified in-app.
  - **Constraint**: the only real lever (proxying video bytes through our
    own domain) is not recommended without a real cost check — see
    `BACKLOG_DONE.md`'s `ARCHIVE_BASE_URL` entry on double-proxied-HTML
    bandwidth overage found elsewhere.
  - **History**: full investigation (7 findings, real quantified breakdown
    from Ryan's own GSC export) in `BACKLOG_DONE.md`'s
    `[Investigated 2026-08-30]` entry. IQM2 (9.5%) and the `/j/`/`/state/`
    hub-page fix (6.5%) are already built, deployed, and confirmed live
    2026-08-31 — only a Search Console Validate Fix click remains, tracked
    under "Needs a human". eScribe/isilive (10.1%) needs only a fresh
    Google recrawl, not code — traced to a display artifact, not a real
    bug. The same Granicus block also shows up as Events/Videos
    rich-result "invalid item" flags in URL Inspection, not just the
    watch-page issue — its "Page resources couldn't be loaded" panel
    shows the same Granicus media stream failing Googlebot's fetch
    ("Other error"), matching the 403-to-Googlebot finding above; not a
    new bug, another symptom of the same one.

- **[NEEDS-AUDIT] Search Console "video isn't on a watch page" — Cablecast
  and the long tail remain unexplained.**
  - **Issue**: Cablecast (6.6% of the failing population, many small
    tenants) is fully reachable and correctly rendered but its root cause
    is still unconfirmed; champds (11), townhallstreams (5), and a long
    one-off tail remain unswept.
  - **Impact**: roughly 10% of the real failing GSC population stays
    unexplained; each individual platform is too small to prioritize on
    its own.
  - **Next action**: chase the one unverified lead for Cablecast — a
    possible minor HLS spec deviation in its own generated manifest, not
    something this app produces — before sweeping the smaller unswept
    platforms.
  - **History**: same investigation as the Granicus/CivicClerk entry
    above, `BACKLOG_DONE.md`'s `[Investigated 2026-08-30]` entry.

- **[NEEDS-AUDIT] Garbled source transcripts still produce garbled
  highlight snippets.**
  - **Issue**: the coherence guards catch a hammered content word and an
    interleaved roll-up phrase, but a *fluently wrong* transcription (real
    live example: Santa Rosa, CA — "brought for their concerns and need
    for essential anti displacement home parks and aims of protections
    for the mobile emergency concerns") has no repetition signal to
    detect and reads as word salad.
  - **Impact**: affects `/state/*` and `/j/*` hub-page snippets (see
    `STATE_HUB_PAGES.md`).
  - **Next action**: would need a coherence model, not a regex; a
    threshold-based approach was tried and misfires on good snippets —
    measured, see `tests/test_highlights.py`'s frozen cases.
  - **Constraint**: this is transcription quality surfacing, not a
    snippet-selection bug — framing matters for where a real fix would
    land.
  - **History**: deliberately left open by the 2026-08-23 state/hub
    rebuild; see `STATE_HUB_PAGES.md`.

- **[NEEDS-AUDIT] Topic chips are ranked by corpus hits, not real search
  demand.**
  - **Issue**: `/meetings` topic chips are ranked by corpus hit count.
    `search_queries` now logs every keyword (identity-free) and
    `crud.top_search_keywords()` can read it, but nothing ranks chips by
    it yet.
  - **Impact**: chip ordering doesn't reflect what people actually search
    for.
  - **Next action**: wire chip ranking to `top_search_keywords()` once the
    table has real volume — there is no data yet, the table just started
    filling.
  - **History**: deliberately left open by the 2026-08-23 state/hub
    rebuild; see `STATE_HUB_PAGES.md`.

- **[NEEDS-AUDIT] [BLOCKED] Whether a sustained YouTube IP block ever clears, and whether pacing avoids it, is unresolved.**
  - **Issue**: YouTube caption fetching sometimes returns `HTTP 429` even
    on a single, isolated, cold request — not just under bulk load.
  - **Impact**: hits every one of the **184** real jurisdictions on
    `platform="YouTube"` (confirmed 2026-08-26 via `/coverage`, not just
    the curated `youtube_channel.py` cities), since all of them share the
    same yt-dlp caption-fetch call.
  - **Next action**: a single isolated `resolve()` call from Render's own
    outbound IP (not a residential one — untried so far) to test whether
    the block is IP-specific.
  - **Constraint**: do not re-run a bulk YouTube sweep to test this —
    one isolated check is enough, more risks extending the block.
  - **History**: `docs/investigations/youtube_429_block.md`.

- **[NEEDS-AUDIT] Philadelphia's `_pick()` ambiguity gap — real, not yet
  fixed.**
  - **Issue**: `_pick()`'s only tie-break for >1 match is the "(Part N)"
    identical-token-set case; two real Aug 6 Philadelphia videos on
    different channel tabs have overlapping-but-different titles
    (durations differing ~18 min) and correctly decline rather than
    guess.
  - **Impact**: that Philadelphia Aug 6 meeting can't be auto-matched.
  - **Next action**: needs a second same-shape ambiguous-match case before
    a tie-break rule is trustworthy — this repo's own WO-34 lesson (a
    single case isn't enough to safely generalize a matching-logic
    change) applies directly.
  - **History**: full diagnosis in `BACKLOG_DONE.md`'s WO-77–82 entry
    (2026-08-30); this entry compacted 2026-08-31. Albuquerque re-checked
    2026-08-31 and confirmed working correctly on a fresh real example —
    see `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] A chunk truncated only at its tail still passes the
  decodability guard.**
  - **Issue**: confirmed with real ffmpeg 2026-08-21 — the first 1000
    bytes of a real 12.6KB mp3 decode cleanly and PyAV opens such files
    too, so a valid-but-short chunk reaches Whisper and silently
    transcribes only the surviving part.
  - **Impact**: not observed in production yet, but the underlying gap is
    real and unguarded.
  - **Next action**: measure real per-chunk `probe_duration()` deltas
    across live HLS and direct-file jobs before picking a tolerance.
  - **Constraint**: the obvious guard (compare `probe_duration()` against
    requested duration) was considered during WO-25 and deliberately not
    built — two legitimate cases also produce a short chunk (the fast
    input-side `-ss` seek makes real HLS chunk durations differ from
    requested, and a job's final chunk is legitimately short); a
    tolerance loose enough for both may not catch a meaningful
    truncation.
  - **History**: WO-25 (`BACKLOG_DONE.md`).
### WO-34's roll-up calibration gap: a second, smaller defect shape sits below the threshold `[NEEDS-AUDIT]`

- **Issue**: `_looks_like_rollup()`'s roll-up detector threshold (0.401) was
  never widened for a second, structurally distinct roll-up shape — a
  YouTube auto-caption track behind CivicWeb/Municode that double-emits
  each speaker-change line as both `>>` and `»` — which scores
  0.202-0.244, below the floor.
- **Impact**: a *new* page with this shape arriving via a fresh resolve
  won't get auto-deduped, even though the 10 already-known-affected pages
  were fixed by hand.
- **Next action**: decide whether `_looks_like_rollup()` should be widened
  to score this shape confidently, or whether the `>>`/`»`
  double-emission deserves its own detector and dedupe path.
- **Constraint**: don't lower `--min-retained` below its measured real
  floor of 0.066 (Delray Beach FL, Marco Island FL) — the 0.05 default
  has only a small margin already.
- **History**: `BACKLOG_DONE.md` — corpus-wide dry run #310 (2026-08-22)
  found the gap; all 10 known-affected pages rewritten via `--apply` on
  2026-08-30 (retention 0.51-0.85).

### `transcribe_backlog_locally.py`'s asyncio/subprocess context hangs where a manual run doesn't `[NEEDS-AUDIT]`

- **Issue**: a byte-for-byte-identical manual `ffmpeg` command finishes in
  ~12s while the script's own asyncio/subprocess context hangs the full
  120s on the exact same URL — measured twice; the video, host, and
  command are all fine, so the hang is specific to how the script runs
  it.
- **Impact**: local transcription batches lose real throughput to false
  120s timeouts the retry (below) papers over rather than explains.
- **Next action**: instrument a long sequential local batch to test the
  standing theory (resource buildup across the run) — currently
  untested.
- **History**: split out of the retry work, `BACKLOG_DONE.md` #305/#306
  (2026-08-22).

### Brookhaven NY's media host (`cpmedia.azureedge.net`) fails every attempt `[NEEDS-AUDIT]`

- **Issue**: Brookhaven NY's media consistently times out (`ffmpeg timed
  out ... @ 0s`) against `cpmedia.azureedge.net` — two immediate
  back-to-back retries both failed identically.
- **Impact**: this one jurisdiction's transcription stays permanently
  stuck without a way to tell "genuinely dead" from "needs different
  handling."
- **Next action**: check whether other `cpmedia.azureedge.net`-hosted
  meetings also fail, to tell "this specific file is gone" (one
  confirmed real 404 from a manual `ffmpeg` run against it) from "this
  CDN host generally doesn't work." `MEDIA_ATTEMPTS` is the tuning knob
  once the answer is known.
- **History**: split out of the retry work, `BACKLOG_DONE.md` #305/#306
  (2026-08-22).

- **[LATER] `pec.iqm2.com` (IQM2) — a third same-day probe still shows
  the same connection-level timeout (10s, no TLS handshake), now 3 for
  3.** Two prior probes on different days agreed 27 of 28 flagged
  tenants were identically dead and those rows were removed 2026-08-31
  (see `BACKLOG_DONE.md`). `pec` alone has never once returned the
  generic "Accela Meeting Portal" error page the other 27 share — every
  check is a bare connection timeout, which reads more like a real
  outage or firewall than a retired tenant serving a fallback page.
  Still not conclusive (never resolved even once), but the pattern is
  now 3-for-3 consistent. Left in the queue.

- **Issue**: 28 structurally-correct IQM2 queue rows resolve to tenants
  that appear to be retired (the Accela/IQM2 sunset) rather than
  truncated URLs — distinct from the 52 truncated rows already fixed.
- **Impact**: these 28 rows will never successfully transcribe left as-is
  in the queue; wildcard DNS means even a dead tenant still answers, so a
  single probe alone can't tell "retired" from "transient outage."
- **Next action**: Ryan's call on whether to drop the confirmed-dead rows,
  now that two probes on different days (2026-08-22 and 2026-08-31) agree
  on 26 of 28; `pec` needs separate handling first — it shows a
  connection-level timeout, not the shared generic-error signature the
  other 27 share.
- **Constraint**: never drop a row off a single probe on this population —
  a dead IQM2 tenant still returns the generic "Accela Meeting Portal"
  body instead of failing outright.
- **History**: `BACKLOG_DONE.md` — split from tier-3 queue repair #308
  (2026-08-22); repeat probe and full tenant list [Investigated
  2026-08-31].

### `[LATER]` Swagit multi-clip meetings: both transcription paths now handle it, two small residuals remain

- **Issue**: two known, unconfirmed-as-real gaps left after both paths
  shipped multi-clip handling (cloud worker WO-79 2026-08-30, local
  script 2026-08-31): a chunk-plan job skips the live per-chunk
  re-resolve the ordinary path uses to guard against stale URLs, and
  there's no sub-chunking for an individual very-long clip.
- **Impact**: neither has a confirmed real case forcing it yet — real but
  unobserved staleness risk, not an active bug.
- **Next action**: none until a real case turns up; separately, re-run the
  fixed resolver against the original 43-URL 2026-08-18 sweep to size how
  many are genuinely multi-segment, and do a broader live Swagit audit.
- **History**: `BACKLOG_DONE.md` — WO-79 (cloud worker) and the
  2026-08-31 local-script port.

### High Plains Water District (Granicus) transcribed to zero usable segments `[NEEDS-AUDIT]`

- **Issue**:
  `high-plains-underground-water-conservation-district-no-1-2022-11-08-board-of-dir`
  (`https://hpwd.granicus.com/player/clip/44?view_id=1`), a real board
  meeting, passed duration/probe checks and ran the full local Whisper
  pipeline but came out with zero usable segments.
- **Impact**: this meeting still has no transcript; unclear whether it's
  a genuinely silent/bad recording (nothing to fix) or a VAD-tuning gap
  (a real fix that would also apply elsewhere).
- **Next action**: manually listen to the source file to tell which case
  this is — the "no usable segments" symptom is distinct from this file's
  "implausible duration" ad-detection entry.
- **History**: `BACKLOG_DONE.md` — found auditing local-Whisper run logs
  2026-08-27; the same symptom hit two other URLs in that audit that have
  since self-resolved, plus a fourth that's arguably a correct zero-segment
  outcome, not carried forward as open [Investigated 2026-08-27].
### Adapter, tenant & jurisdiction-extraction odds and ends `[LATER]`

Everything adapter-, tenant-, or jurisdiction-extraction-shaped, kept
together on purpose. Tags are inline here rather than hoisted into the
actionability sections above.

- **`[NEEDS-AUDIT]` `jurisdiction_enrich.validated_label_extract()` can resolve a same-named-in-two-countries subdomain to the wrong country's real place**
  - **Issue**: a subdomain shared by two same-named tenants in different
    countries can resolve to the wrong country's place — confirmed once,
    eScribe's `pub-richmond.escribemeetings.com` resolved to "Richmond,
    CA" when the real customer is Richmond, BC.
  - **Impact**: wrong jurisdiction label on that one confirmed page; no
    second case found live-checking Granicus's own shared
    `_humanize_subdomain()` (5 candidate names checked, only 2 real
    tenants, neither a live collision).
  - **Next action**: nothing to build yet — revisit if a second real
    collision turns up.
  - **Constraint**: don't build speculative disambiguation logic off one
    confirmed case, per this repo's convention.
  - **History**: full discovery detail and the Granicus re-check in
    `~/Documents/rtr-business/research/ENUMERATION_METHODS.md` §35.

- **`[NEEDS-AUDIT]` CivicPlus's subdomain jurisdiction hint is lost whenever a multi-candidate pick is resolved or queued by its delegate URL, not the original AgendaCenter URL**
  - **Issue**: `CivicPlusAssetFinder._jurisdiction_from_subdomain()`'s
    authoritative `{state}-{name}.civicplus.com` hint is only applied
    inside `resolve()`'s own single-candidate delegation branch. A
    multi-candidate page raises `CalendarPageError` instead of
    returning, so anything that picks a candidate and resolves it
    directly via `resolve_via_platform(picked_url)` — `bulk_ingest.py`
    can't do this at all (it just reports "calendar page, not a single
    meeting" and fails), so this only happens in ad-hoc tooling like a
    dry-run scanner — never applies the hint. The delegate platform's
    own jurisdiction guess (channel name, page text) is used instead,
    with the same wrong/blank-jurisdiction risk documented for every
    other adapter's own guessing.
  - **Impact**: confirmed live 2026-08-31 — 15 of 17 CivicPlus tier-3
    queue entries added that day (multi-candidate picks, queued by their
    delegate YouTube/Vimeo/Viebit/Cablecast/Granicus/CivicClerk URL) will
    ingest with whatever jurisdiction the delegate derives on its own,
    not CivicPlus's authoritative subdomain-derived one. Same
    pre-existing limitation every other tier-3 queue entry from prior
    platforms already has (the flat queue file format has no field for a
    hint at all) — not a regression, but CivicPlus is the one platform
    in this project that actually has a reliable hint available and
    currently throws it away at exactly this step.
  - **Next action**: nothing built yet. If this is worth fixing: either
    give the tier-3 queue file (or the ingest payload generally) a way to
    carry a jurisdiction override alongside a URL, or teach
    `bulk_ingest.py`/the tier-3 feed script to re-derive and apply the
    CivicPlus subdomain hint whenever the URL being ingested is known to
    have come from a CivicPlus multi-candidate page.
  - **Constraint**: don't build this speculatively — check how often the
    delegate's own guess is actually wrong on a real sample of these 15
    (and future ones) before deciding it's worth a queue-format change.
  - **History**: found live 2026-08-31 while queueing PR
    [#659](https://github.com/mroconnell/rtr-deeplink/pull/659) (CivicPlus
    DNS enumeration sweep tier-3 candidates); see
    `~/Documents/rtr-business/research/dns_sweep_2026-08-31/` for the full
    scan data.

- **`[NEEDS-AUDIT]` `appalachian.cablecast.tv` (show/3841) is genuinely unreachable, jurisdiction unknown**
  - **Issue**: `appalachian.cablecast.tv` (show/3841) times out at the TCP
    level on both port 80 and 443; DNS resolves fine (152.10.10.157).
  - **Impact**: this one tenant's jurisdiction can't be recovered — no
    Wayback Machine snapshot exists for the URL either; skipped during
    the 2026-08-23 local-Whisper batch with "no usable audio/video source
    on re-resolve."
  - **Next action**: nothing to build — this tenant's own server appears
    down, not a bug here; quick re-check before assuming it's still down
    if the URL comes up again.
  - **Constraint**: not a cablecast.tv-wide issue —
    `barnstable.cablecast.tv` answered normally (200) in the same check.
  - **History**: none yet — confirmed directly 2026-08-23, no prior
    BACKLOG_DONE entry.

### ChampDS symptom B — instant 0.2s failures from the JSON API, instrumented but not yet recurred `[WAIT]`

- **Issue**: ChampDS resolves sometimes fail instantly (~0.2s) with
  "Could not reach the ChampDS API for this meeting," cause unexplained —
  distinct from symptom A (the timeout cluster), which is fully fixed.
- **Impact**: affects any ChampDS meeting hitting this path; previously
  unexplainable because `_fetch_json()` collapsed timeout/non-200/
  connection-error/malformed-body into a bare `return None` with no
  logging, which is why it survived two prior investigations.
- **Next action**: next time it recurs, grep resolver logs for `ChampDS
  API fetch failed` — `_fetch_json()` was instrumented 2026-08-25 and now
  logs the real reason (404, 429, connection reset, and
  200-that-isn't-JSON are all distinguishable).
- **Constraint**: if it turns out to be 429s, the fix is host-aware
  pacing — already deprioritised for symptom A on the evidence there, but
  this is the half it could genuinely fit.
- **History**: symptom A's full history is in `BACKLOG_DONE.md`.

### `[JUST-DO-IT]` ~10 OnBase/Hyland-family pages still resolve with no video — 2 named tenants now have a confirmed fix path

- **Issue**: real population is 31 pages across 25 OnBase/Hyland-family
  tenants (matched on the `OnBaseAgendaOnline`/`agendaonline` URL *path*,
  not a vendor-name grep). `meetings.muni.org` (Anchorage AK,
  `@moameetings`) and `ecm.cityofsantacruz.com` (Santa Cruz CA,
  `youtube.com/ctvsantacruz` — 5,695 real captions confirmed live) each
  have real video on their own YouTube channel, but `hyland.py` doesn't
  call `youtube_channel.py`'s fallback at all today.
- **Impact**: Sarasota's repoint (closed 2026-08-31) brought the open
  count down by one, to ~10. Video presence isn't caption presence
  either — most of the 31 pages have no real captions even once video is
  found, so repointing usually buys a video, not a transcript.
- **Next action**: wire Anchorage/Santa Cruz through the same
  date-matching join Legistar cities needed for their YouTube-channel
  fallback (not a trivial repoint); work the remaining per-tenant hunt
  using the repoint method already proven on the fixed pages.
- **History**: full investigation, the working repoint method, and the
  fixed pages are in `BACKLOG_DONE.md`'s OnBase/Hyland entries.

### Duration alone cannot separate a very short real meeting from an ad `[NEEDS-AUDIT]`

- **Issue**: `MIN_PLAUSIBLE_MEETING_SECONDS` moved 300s → 60s off real
  measured data (recovering 3 of 4 confirmed-real short meetings), but a
  4th case is unreachable by any threshold: Berkeley County SC's real 53s
  special Council meeting (`berkeleycountysc.iqm2.com` MeetingID=4203)
  sits 3 seconds from a confirmed 50s ad (`gnat.cablecast.tv/.../13707`)
  with the opposite right answer.
- **Impact**: Berkeley County stays permanently skipped — an accepted
  miss, not an oversight.
- **Next action**: needs a different signal than duration —
  `meeting_body`, whether the page carries a real agenda, or the page's
  own framing; not worth building for one known case, revisit if WO-46's
  daily failure digest shows this class is common.
- **Constraint**: do not lower the floor further to catch it — 60s
  already sits just above a confirmed ad, and below it the two classes
  interleave.
- **History**: recorded 2026-08-23 (WO-46); see
  `MIN_PLAUSIBLE_MEETING_SECONDS`'s own code comment for the full
  measured table.

### Residual gaps from the 50-largest-cities audit `[NEEDS-AUDIT]`

Full per-tenant history (what closed, when, and why) moved to
`BACKLOG_DONE.md` — this entry keeps only the tenants that never
closed. Distinct from the "no domain found yet" jurisdiction-coverage
work (`~/Documents/rtr-business/research/jurisdiction_coverage.csv`).
Tucson AZ is done (YouTube-channel fallback shipped 2026-08-31,
`youtube_channel.py` generalized to accept a Hyland netloc — see
`BACKLOG_DONE.md`); Atlanta's original ChampDS gap is also closed —
every re-check found the same thing (works via IQM2, no ChampDS URL
ever recorded anywhere) — see `BACKLOG_DONE.md`.

- **Omaha, NE — the real blocker is worse than framed: the whole domain
  is Akamai-gated, not just one page.** Re-checked 2026-08-31:
  `citycouncil.cityofomaha.org`, `cityclerk.cityofomaha.org`, and even
  bare `www.cityofomaha.org` all return a flat `403 AkamaiGHost "Access
  Denied"` regardless of client (tried a full Chrome UA+Referer+
  Accept-Language, and Googlebot's UA — no difference; same from `curl`
  and a real browser). A real per-date URL shape does exist
  (`citycouncil.cityofomaha.org/.../icalrepeat.detail/{YYYY}/{MM}/{DD}/
  {id}/-/city-council-meeting`, found via Wayback CDX) but is
  unreachable to fetch or verify by any client available here, so
  there's nothing to wire a date-match against. **@DOTComm2013**
  (`UCBJ5WE5dI3_GIBLoUNEgBXQ`) is still confirmed real and current
  ("Omaha City Council" playlist) — the channel-side fact holds — but
  there's no page this app can reach to trigger the fallback from. Not
  a code gap; a real access wall, same category as the GovAccess
  Granicus WAF entry below. Virginia Beach VA, previously listed here
  too, is resolved (`virginiabeach.cablecast.tv` has real, ongoing
  weekly Council coverage, confirmed live 2026-08-31 across 4
  consecutive weeks) — see `BACKLOG_DONE.md`.
  either way — re-checked against the live archive 2026-08-30, 14 real
  meeting links are now archived (up from "at least one"), but the
  working ones found are sourced from IQM2 (`atlantacityga.iqm2.com`),
  not ChampDS.
### Granicus's GovAccess CMS product is undetected and blocked by Akamai's WAF `[NEEDS-AUDIT]`

- **Issue**: Granicus's "GovAccess CMS" product (CNAMEs through
  `granicusgovaccess.net`) is completely undetected by
  `detect_platform()`, which only recognizes literal `granicus.com`
  URLs — a distinct product from the classic `{tenant}.granicus.com`
  hosting this project already supports.
- **Impact**: 97 real `.gov` domains CNAME to `granicusgovaccess.net`;
  every path 403s or connection-resets. A real headless Chromium browser
  (`app/platforms/headless_browser.py`) from a genuine residential IP
  still gets a domain-wide 403 from Akamai (confirmed on `belmont.gov`
  including the root path) — not a client-fingerprint problem a
  different User-Agent/header set can solve, the WAF config itself is
  the wall.
- **Next action**: two separate open pieces — (a) direct
  `detect_platform()`/adapter support for `granicusgovaccess.net` CNAMEs,
  blocked entirely by the WAF, matters only if that gets solved first;
  (b) extend the fuzzy-match workaround (guessing a GovAccess domain's
  classic Granicus subdomain by slug), which already found 11 genuinely
  new jurisdictions and caught 2 real wrong-entity matches before being
  trusted, but never matched 86 of the 97 GovAccess domains — no further
  lever on file beyond the WAF itself.
- **Constraint**: real adapter work for a future session, if picked up
  at all — no further ideas on file for getting past the WAF.
- **History**: relocated from Dormant 2026-08-30 (was already tagged
  `NEEDS-AUDIT` there, misfiled), compacted the same day; full
  fuzzy-match investigation in `BACKLOG_DONE.md`.
### Jurisdiction extraction & backfill

- **`[NEEDS-AUDIT]` `[EASY]` `"Regional Municipality of X"`/`"Region of X"` split off as a body instead of resolving as the government.**
  - **Issue**: `jurisdiction_enrich._split_entity_prefix()` reads
    "Regional Municipality of Durham" as the same "`<Entity> of
    <Jurisdiction>`" shape built for "Housing Authority of the County of
    Santa Clara" — splitting it into `meeting_body="Regional
    Municipality"`, `jurisdiction="Durham"`. For a housing authority that
    is correct (D2: it has its own board/statute/budget, "Durham" is a
    different question). For "Regional Municipality of X" it is wrong:
    that phrase IS the government's own identity (`classify.
    classify_government_type()` already returns `county` for it via
    `_CA_UPPER_TIER_RE`), not a body within a place called "Durham". By
    the time `resolve_government()`'s rung 3 classifies, the entity
    prefix is already gone from the cleaned name, so "Durham" alone
    classifies `other` and mints `rtr:ca:on:durham` instead of reaching
    `ca:cd:3521`. "Region of Peel"/"County of X" do NOT have this bug —
    only the longer "Regional Municipality of" phrasing triggers the
    split. Confirmed live against this repo's own code 2026-09-03 (not a
    hypothetical): `resolve_government("Regional Municipality of Durham,
    ON")` → `tier=unverified`, `gov_id=rtr:ca:on:durham`.
  - **Impact**: at least one real, named example (Durham) mints instead
    of keying to its census division — a fragmentation of exactly the
    shape Phase 1b/2 spent most of their effort closing. Scope beyond
    Durham not yet measured (needs a live corpus check for how many
    stored Ontario/other-province jurisdictions use this longer phrase).
  - **Next action**: teach `_split_entity_prefix()`/`classify.
    _ENTITY_OF_PLACE_RE` (or a guard ahead of them) to recognize
    "Regional Municipality"/"Region"/"County" as IDENTITY-carrying
    prefixes for a Canadian upper-tier name, not body-carrying ones — the
    same distinction `classify._CA_UPPER_TIER_RE` already draws, just
    applied before the entity-prefix split runs instead of after.
  - **Constraint**: don't weaken the housing-authority case this
    mechanism exists for — the fix needs to distinguish "this entity
    phrase names an upper-tier Canadian government" from "this entity
    phrase names a body", not just special-case the word "Regional".
  - **History**: WO-105 (2026-09-03), found writing
    `tests/test_gov_registry.py::
    test_regional_municipality_of_durham_type_word_widened_but_resolution_unchanged`
    while widening `resolver.py`'s type-word regexes — the widening
    itself does not cause or fix this, it is pre-existing on `main`.

- **`[NEEDS-AUDIT]` `[EASY]` `classify.py`'s SPECIAL_DISTRICT rule matches the bare word "district", misclassifying real BC "District of X" municipalities.**
  - **Issue**: `classify._RULES`' SPECIAL_DISTRICT pattern includes a bare
    `\bdistrict\b` alternative. District of North Vancouver, District of
    Squamish, District of Saanich and District of Sechelt are all real,
    current BC municipalities (a general-purpose government, StatCan CSD
    type `DM`), not special districts — but `classify_government_type()`
    files them SPECIAL_DISTRICT before `_CA_UPPER_TIER_RE`/the
    municipality rule ever gets a look, the same shape as the already-
    fixed "wastewater" (§1.4) and "port" (Phase 2's four-defects section)
    negative-lookahead gaps.
  - **Impact**: a real "District of X" name mints an `rtr:` id under
    NON_PLACE_TYPES routing instead of reaching `ca:csd`'s real row for
    it — confirmed live 2026-09-03:
    `classify.classify_government_type("District of North Vancouver",
    country="ca")` → `special_district`. `resolver.py`'s type-word
    widening this same pass (WO-105) now correctly extracts "district" as
    the raw name's own type word regardless, so the widening itself does
    not make this worse, but it also can't fix it — rung 3 (type
    classification) runs before `_leading_type_word()`'s result is ever
    consulted, and it decides the branch.
  - **Next action**: add a negative lookahead (or an upper-tier check
    ahead of the special_district rule, mirroring `_CA_UPPER_TIER_RE`'s
    own early check) so "district" only fires the special-district rule
    when NOT preceded by "of" naming a Census/StatCan place — i.e.
    "District of X" should classify the same way "Regional Municipality
    of X"/"Region of X" already correctly do, not the way "X Water
    District" should.
  - **Constraint**: don't lose real special districts that DO use
    "District of" phrasing, if any exist (not yet checked) — ground the
    fix in a real confirmed example the way the wastewater/port fixes
    were, not a blind exemption.
  - **History**: WO-105 (2026-09-03), found building the type-word
    widening; pinned as a known, current-state gap by
    `tests/test_gov_registry.py::
    test_district_of_north_vancouver_type_word_extracted_but_not_yet_resolved`.

- **`[NEEDS-AUDIT]` `[EASY]` `pub-*` eScribe hosts resolve to a US government of the same name.**
  - **Issue**: several Canadian eScribe tenants carry two `gov_id`s, one
    Canadian and one American: `pub-richmond` is Richmond BC *and*
    Richmond CA, `pub-salmonarm` is Salmon Arm BC *and* Salmon ID,
    `pub-courtenay` is Courtenay BC *and* Courtenay ND, `pub-owensound`
    is Owen Sound ON *and* Owen WI. WO-100's cross-border guard does not
    catch these because the STORED string carries a state suffix, so the
    name never reaches the stateless path. (`pub-gloucesterva` had the
    same symptom — bleeding into "Gloucester, MA" alongside Gloucester
    County, VA — but was US/US, not Canada/US; fixed 2026-09-03 by
    pinning it to `us:county:51073` in `tenant_overrides.csv`, see
    BACKLOG_DONE.md.)
  - **Impact**: a handful of pages per host on the wrong country's hub.
    Surfaced by `pin_worklist.csv`'s new `multiple_governments` section
    (WO-100), which is the first cut that made them visible.
  - **Next action**: read the section, then pin each remaining host —
    one landing fetch settles a `pub-*` host's country even where it
    cannot settle its name (`scripts/sweep_tenant_landing_pages.py`).
  - **Constraint**: don't infer the country from the `pub-` prefix.
    eScribe has real US customers (`pub-horrycountyschools` is SC), so
    the prefix is a hint, not a rule.
  - **History**: WO-100 (2026-09-03);
    `reports/gov_registry_scoring_2026-09-03/pin_worklist.csv`,
    `reason=multiple_governments`. That frozen copy is still the one with
    the `multiple_governments` section — WO-103's regenerated
    `reports/pin_worklist.csv` is one row per tenant that WANTS a pin and
    deliberately does not carry it.

- **`[NEEDS-AUDIT]` `[EASY]` A minted government's page and its hub show two different names.**
  - **Issue**: `_display_jurisdiction()` (`archive/db/crud.py`) rewrites
    `jurisdiction` to the registry name only for the `pinned` and
    `registry` tiers, as WO-99's brief specified. For a MINTED government
    that leaves the two out of step, because the resolver classified the
    raw name while `finalize_jurisdiction()` split it: the Housing
    Authority of the County of Santa Clara stores `jurisdiction =
    "County of Santa Clara, CA"` with `meeting_body = "Housing
    Authority"`, while its `gov_id` is
    `rtr:us:ca:housing-authority-of-the-county-of-santa-clara` and its
    hub reads "Housing Authority of the County of Santa Clara, CA".
  - **Impact**: cosmetic, and bounded — the hub is the surface a reader
    browses and it is correct; `/m/` and `/meetings` show the county's
    name with the authority as the body, which is what shipped before
    WO-99 and reads fine. 479 rows are minted, but only the non-place
    types (83 `special_district`, plus school districts) can diverge this
    way at all.
  - **Next action**: decide whether an `unverified` row should take the
    minted `gov_name` as its display too. It is not obviously right:
    doing so duplicates the entity name across `jurisdiction` and
    `meeting_body`, so the honest fix is probably to take the resolver's
    own `meeting_body` (which is `None` for a non-place type, by design —
    "the entity IS the government") at the same time, and that is a
    behaviour change to a field several audit paths read.
  - **Constraint**: don't widen the rewrite to every tier. An
    `inferred` row's id came from its neighbours rather than its own
    name, so its raw text is the evidence a reviewer needs.
  - **History**: WO-99 (2026-09-02). Pinned by
    `tests/test_ingest_promotion.py::test_ingest_resolution_splits_a_real_entity_prefix_end_to_end`,
    which asserts the current behaviour explicitly and says why.

- **`[NEEDS-AUDIT]` `[EXAMPLE]` eScribe, Swagit and CivicClerk landing pages do not name their customer — the pin worklist assumed they did.**
  - **Issue**: `pin_worklist.csv`'s ordering note calls eScribe,
    Cablecast, Swagit and TelVue "the four whose landing page reliably
    names its customer". Measured 2026-09-02 against real hosts, only
    Cablecast does. eScribe's `Meetings.aspx` is titled "Meetings" and
    the only place a customer name could live is a logo whose alt text
    is the literal string "Organization Logo"; Swagit's root is titled
    "SwagitAdmin" and `/videos` 404s; CivicClerk's is "Public Portal •
    CivicClerk", with the organisation name only behind its API.
    Granicus, which the note does not list, DOES name it — but on
    `ViewPublisher.php?view_id=N`, not the root.
  - **Impact**: the highest-yield block named in the report (eScribe:
    `pub-cambridge`, `pub-london`, `pub-halifax`, `pub-hamilton`, 41
    hosts) cannot be settled by a landing-page fetch at all. Those hosts
    stay `unresolved` and their pages have no `gov_id`. Measured over the
    real sweep (2026-09-03): 278 hosts fetched, 223 pages returned, **7**
    pins written — all 7 from Granicus's `ViewPublisher.php` and one
    CivicPlus root. Still unresolved: granicus 106, cablecast 61,
    escribe 41, swagit 39, iqm2 5, civicclerk 4, unknown 4, telvue 2,
    and one each of castus / champds / townhallstreams / vimeo (39
    cablecast and 14 granicus hosts were unreachable outright).
    **Correction (WO-103, same day)**: the Cablecast row above undercounts
    this entry's own real yield. The sweep's `_landing_url()` sent every
    Cablecast host to `/CablecastPublicSite/`, which 404s on every real
    host checked (`huron-township`, `wilson-co-schools`, `cerritos`, all
    confirmed live) — the host ROOT 200s instead, and its
    `<title>`/`og:site_name` already carry the real government name
    ("Huron Charter Township"), exactly the shape `candidate_names()`
    already reads. So an unknown share of "cablecast 61 unresolved" /
    "unreachable outright" is really a wrong-path 404 this entry
    mischaracterized as a content gap, not a genuine "landing page
    doesn't name its customer" case the way eScribe/Swagit/CivicClerk are.
  - **Next action**: for eScribe, read the organisation name from a
    real `Meeting.aspx` page instead of the listing (the adapter already
    fetches those, and the archive holds an example slug per host); for
    CivicClerk, its public API already returns `location.city/state` and
    the adapter already reads it. Both are per-platform work, not more
    sweeping. **Cablecast's own next action changed**: re-run
    `scripts/sweep_tenant_landing_pages.py --apply` now that
    `_landing_url()` sends it to root (WO-103) — likely real, immediate
    pins among the 61 currently unresolved, no code change needed to get
    them, just the fixed path.
  - **Constraint**: one fetch per host, politely paced, and read-only —
    `scripts/sweep_tenant_landing_pages.py` is the shape to extend, not
    a crawl.
  - **History**: WO-99 step 8 (2026-09-02);
    `reports/landing_page_sweep.csv` has what each host actually
    returned, and the script's `_PLATFORM_PATHS` comment records the
    per-platform measurements. WO-103 (2026-09-03) fixed the Cablecast
    404 (see the correction above) and left eScribe/Swagit/CivicClerk's
    real "doesn't name its customer" gap untouched — that part still
    needs the per-platform work in **Next action**. Two smaller changes
    landed alongside it: `reports/pin_worklist.csv` now carries a
    hostname/slug-derived `proposed_name` on 5 of the 43 eScribe rows and
    7 of the 40 Swagit ones, which settles a few of these without a fetch;
    and the sweep now skips the four shared YouTube netlocs rather than
    every page whose video is on YouTube, so hosts like
    `www.townofrossca.gov` are in its scope for the first time.

- **`[NEEDS-AUDIT]` `uatccta.primegov.com` is the first real multi-government tenant and still has no `match` discriminator.**
  - **Issue**: it is listed under El Cerrito **and** San Pablo in
    rtr-upcoming's roster — a real shared tenant (architecture doc
    §1.5), not a conflict. It gets no pin, because a host-level pin
    would be wrong for one of the two.
  - **Impact**: one tenant today, but the same shape as
    `wi-cottagegrove.civicplus.com` (Town and Village of Cottage Grove)
    and every `clerkshq.com` customer, and the `match` column exists
    unused.
  - **Next action**: find the path prefix or query parameter that
    separates the two cities' meetings on that host, then write two
    `tenant_overrides.csv` rows carrying it.
  - **Constraint**: `match` must come from a real observed URL shape,
    not a guess — a wrong discriminator over-applies silently.
  - **History**: WO-98 Phase 1b (2026-09-02),
    `app/utils/jurisdiction_data/tenant_overrides_conflicts.csv`.

- **`[NEEDS-AUDIT]` Derry NH has no known-jurisdictions entry.**
  - **Issue**: `_KNOWN_ORG_TOKEN_JURISDICTIONS` in `app/platforms/telvue.py`
    has no entry for Derry NH, so its jurisdiction field resolves
    empty/garbled.
  - **Impact**: Derry NH's TelVue page is live in production (ingested
    2026-08-30, confirmed via a real `/m/` page with a working player) but
    shows no jurisdiction.
  - **Next action**: find the live Derry `/m/` page in production (not via
    `/meetings?q=`/queue file/sitemap, which already failed once), read
    its org token, and add it to the known-jurisdictions map the same way
    Leominster/Royal Oak/Luverne were.
  - **History**: WO-67 fixed the sibling title-parsing gap this entry
    originally described (Leominster MA, Royal Oak MI, Summit NJ, Luverne
    MN, Albany NY) — see `BACKLOG_DONE.md`. Derry NH itself was never part
    of that fix; it surfaced as a "real bug found along the way" note in
    `BACKLOG_DONE.md`'s "TelVue: 10 of 12" entry (2026-08-30).

- **`[NEEDS-AUDIT]` Jurisdiction-bleed single-word-tail gap: Castle Rock
  CO.**
  - **Issue**: "Town of Castle Rock Authorizing" still bleeds an extra
    word ("Authorizing") into the jurisdiction field — a single
    capitalized word is indistinguishable from a legitimate short suffix
    using a word-count signal alone.
  - **Impact**: 1 confirmed page (Castle Rock CO) has a bled jurisdiction
    string; the "Meeting"/"Attachments" tails were already fixed via a
    closed, curated stoplist (2026-08-18).
  - **Next action**: wait for a second confirmed example of "Authorizing"
    (or a similar single-word tail) before adding it to the stoplist —
    per this repo's "don't guess" convention.
  - **Constraint**: lowering `_MIN_BLEED_WORD_RUN` was tried and
    rejected — confirmed it would also wrongly trim real long names like
    "Lake Washington School District" → "Lake". Closable the moment a
    second real example turns up.
  - **History**: none yet — open since the 2026-08-18 stoplist narrowing.

- **`[NEEDS-AUDIT]` Bare "Pitt" jurisdiction value — likely not a bug.**
  - **Issue**: a bare "Pitt" appears as its own jurisdiction value,
    separate from a correct "Pittsburg, CA" elsewhere; originally read as
    "Pittsburg, CA" truncated mid-word.
  - **Impact**: 1 page shows "Pitt" instead of a state-qualified name —
    but re-checking 2026-08-30 found `_table_lookup('Pitt')`
    independently validates against the Census table (Pitt County, NC is
    real), so this may be a legitimate, if incompletely typed, resolution
    rather than a truncation bug.
  - **Next action**: watch for a second example either way before
    building any truncation fix off this single case.
  - **History**: none yet — re-checked and re-scoped 2026-08-30, no fix
    built.

- **`[NEEDS-AUDIT]` Swagit still resolves special-purpose entities with a
  blank jurisdiction.**
  - **Issue**: Swagit resolves every special-purpose entity (school
    district, MPO, transit/utility authority, state agency) with a blank
    jurisdiction — confirmed still true 2026-08-29 against fresh real
    meetings from ERCOT, DFPS, and Santa Clara County Office of
    Education, none of which has a "City/County/Town of X" phrase or a
    subdomain that validates against the Census/StatsCan tables.
  - **Impact**: 16 real examples of the blank-jurisdiction gap turned up
    in one `/meetings` pass (2026-08-15); `resolve()`'s fallback to
    `jurisdiction_enrich.extract_jurisdiction_chain()`
    ([swagit.py:373](app/platforms/swagit.py:373)) does not recover any
    of them.
  - **Next action**: design a per-entity-type extraction path — the real
    jurisdiction text sits in a different place depending on entity type
    (school district vs. MPO vs. utility authority), so no single
    fallback covers all of them.
  - **History**: `BACKLOG_DONE.md`'s 2026-08-29 entry has the full
    re-verification detail (URLs used, exact outcomes). Same structural
    "no national table for non-Census entities" problem as the
    50-largest-cities audit entry.

- **`[NEEDS-AUDIT]` Lloydminster (AB/SK border city) needs a product
  decision.**
  - **Issue**: `pub-lloydminster.escribemeetings.com` is a real, active
    city that straddles the Alberta/Saskatchewan border; Census/StatsCan
    stores it as "Lloydminster (Part)" once per province, and both rows
    are correctly filtered out by the existing `(Part)`-stripping logic
    (which is correct for other `(Part)` rows that really are junk, e.g.
    First Nations reserve fragments with trailing numbers).
  - **Impact**: 1 real jurisdiction resolves blank as a side effect of
    otherwise-correct junk-filtering logic.
  - **Next action**: needs a product decision — pick one province to
    show, or build a way to represent "spans two provinces."
  - **History**: the one residual of the closed "eScribe residuals" entry
    (WO-69, 2026-08-30, 11 of 12 fixed) — see `BACKLOG_DONE.md`.

- **`[NEEDS-AUDIT]` Census-table baseline validation: mid-word truncation
  detector still unbuilt.**
  - **Issue**: a mid-word-truncation signal (tails ending "the Tex",
    "servic", "Standa" — caused by the extraction regex's own 40-char cap
    cutting words in half) is not yet built.
  - **Impact**: no jurisdiction-side example currently needs it — the
    three originally cited (Sarasota/Hollywood/Hampton) were already
    repaired via the existing `_MIN_BLEED_WORD_RUN=4` bleed signal and are
    moot (full baseline numbers and the bleed/trim split preserved in
    `E-OpenBugs-4-JurisdictionBackfill.done-additions.md`). It's
    independently motivated by one real title-side instance: a title cut
    off as "...Exhibit 1 was adde".
  - **Next action**: wait for a real jurisdiction-side example before
    building this detector.
  - **Constraint**: before re-running any part of this audit, regenerate
    `baseline_validation.csv` via the script logged in
    `JURISDICTION_METADATA_PLAN.md`'s workstream 1 — it no longer exists
    in any scratchpad.
  - **History**: `BACKLOG_DONE.md`'s 2026-08-17 "Jurisdiction-bleed,
    confirmed cross-platform" entry has the Sarasota/Hollywood/Hampton
    repair detail. Full 2026-08-15 baseline-validation numbers moved to
    `E-OpenBugs-4-JurisdictionBackfill.done-additions.md` for pasting into
    `BACKLOG_DONE.md`.

- **`[LATER]` Domain guesser state-name collision — fixed, 6 rows still
  blank.**
  - **Issue**: `find_gov_domains.py`'s unqualified `{bare_name}.gov`
    candidate systematically collides with a US state's own portal
    whenever a county's bare name (after stripping "County"/"Parish") is
    itself a full state name.
  - **Impact**: 6 rows in `jurisdiction_coverage.csv` had a wrong domain
    from this — Delaware County PA/OH/IN, Oklahoma/Utah/Nevada County —
    all 6 reverted to blank; low priority given the small population
    affected.
  - **Next action**: find a real replacement domain for each of the 6
    counties; none has been re-found yet.
  - **History**: root cause fixed in `find_gov_domains.py` (skip the
    unqualified candidate when the bare name is a US state name), 6 wrong
    rows reverted, 2026-08-21 — see `BACKLOG_DONE.md`.

- **`[LATER]` ~25 smaller consolidated city-county governments still need
  a real domain.**
  - **Issue**: a consolidated city-county's real domain often shares no
    text with the county's own Census name (e.g. Marion County IN's real
    domain is `indy.gov`), so the domain guesser can't find these
    automatically.
  - **Impact**: ~25 smaller/harder-to-verify consolidated city-counties
    still have no domain: Anaconda/Deer Lodge County MT, Butte/Silver Bow
    County MT, Houma/Terrebonne Parish LA, Hartsville/Trousdale County
    TN, Lynchburg/Moore County TN, and several small Georgia ones. 13 of
    ~38 total are already found and verified (Indianapolis, Nashville,
    Louisville, Columbus GA, Lexington, Jacksonville, Athens GA, Augusta,
    Kansas City KS, East Baton Rouge, New Orleans). San Francisco County
    CA and Denver County CO were never part of this gap — their Census
    name already matches the consolidated city.
  - **Next action**: manually research and verify a real domain for each
    remaining consolidated city-county, same process used for the 13
    already done.
  - **History**: `BACKLOG_DONE.md`, 2026-08-20/21.
### Adapter & platform gaps

- **[JUST-DO-IT] TelVue CDX enumeration solved and the full 313-token pool now classified; real remaining work is verification + sign-off, not discovery.**
  - **Issue**: `collapse=urlkey:64` returns the complete 313-org-token
    TelVue CDX set in one uncapped query (302 unrecognized by this
    project). All previously-unclassified tokens are now classified
    (2026-08-31, reproduced the batch-2 method exactly): of the 150
    genuinely-untouched tokens, 33 were `likely_civic`, 23
    independently cross-verified as real; of the remaining 127, 16
    `likely_civic`, 8 `vod_not_enabled` (real, terminal), 36
    `fetch_error` (mostly real dead/retired tokens), 66 `unclear`, 1
    `likely_sports_or_school`. 4 of those 16 spot-verified via a real
    `resolve()` call: 2 real active civic channels with jurisdiction
    still unidentified, 1 confirmed stale (Egg Harbor Township NJ,
    superseded by YouTube), 1 confirmed empty/live-only (New Castle
    County DE).
  - **Impact**: 23 already-verified real jurisdictions (16 needed a
    jurisdiction-parsing fix, shipped as WO-74) haven't been ingested
    into production; 12 of the 16 remaining civic tokens plus the 66
    unclear/1 sports tokens still need manual verification.
  - **Next action**: get explicit sign-off before ingesting the 23
    already-verified tokens as new public content; separately, verify
    the remaining ~79 unclassified-but-promising tokens (reproduction
    script and full classification output are in this session's
    scratchpad, not yet copied to
    `~/Documents/rtr-business/research/cc_scan_data/`).
  - **Constraint**: no ingestion of the 23 without explicit sign-off.
  - **History**: `BACKLOG_DONE.md` (full batch history, per-token
    verification, WO-74's jurisdiction-parsing fix including a real
    wrong-state collision, and the "~112 remaining" figure's
    correction — it never traced to a real artifact). Also surfaced a
    real jurisdiction-guess bug in `telvue.py`: guessed "Building" as a
    place name from a "Building Commission Meeting" title.

- **[NEEDS-AUDIT] A shared regional TelVue org token spanning multiple
  real cities defeats title-only jurisdiction guessing.**
  - **Issue**: org token `wuZKb9gwEY7sMACIIsr7VSJglB35kNZA`
    (`videoplayer.telvue.com/player/wuZKb9gwEY7sMACIIsr7VSJglB35kNZA/...`,
    reached from `cityofpacifica.org/departments/live-video`'s "Videos"
    tab, and via a real `u.peg.tv/s/htl405` share-link shortcut)
    genuinely serves more than one real city's council/commission
    meetings on the same channel — confirmed live 2026-09-02: a real
    "Pacifica City Council - 8/24/26" title extracts `jurisdiction=
    "Pacifica, CA"` correctly, but "Pacifica Special Meeting - 8/25/26"
    (no body suffix to anchor on) and "HMB City Council - 9/1/26" (Half
    Moon Bay, abbreviated — not a recognizable place name to any Census
    lookup) both come back with `jurisdiction=None`. The existing
    `_KNOWN_ORG_TOKEN_JURISDICTIONS` per-customer override map (this
    same file) can't fix this org token the way it fixes a single-city
    org, since a single override string would be wrong for whichever
    city it doesn't match.
  - **Impact**: real, playable meetings for this org resolve fine
    (video found, tier 3 — see the 3 URLs just added to
    `scripts/tier3_auto_transcription_queue.txt`) but land as
    unverified-jurisdiction/low-trust pages once ingested.
  - **Next action**: needs per-*meeting* (not per-org) jurisdiction
    resolution for this token — e.g. a small keyword map ("HMB" → "Half
    Moon Bay, CA", bare "Pacifica" already works) checked before falling
    through to the org-level override, or a real per-meeting metadata
    field on the page itself if one exists (not yet checked).
  - **History**: found live 2026-09-02 during a Bay Area corpus-expansion
    pass (`~/Documents/rtr-business/research/ENUMERATION_METHODS.md`);
    not yet in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] RVTV's org-token jurisdiction override
  (`w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP` = "Ashland, OR") is wrong for 5 of
  the 6 real governments on that channel.**
  - **Issue**: `_KNOWN_ORG_TOKEN_JURISDICTIONS` (`telvue.py`) maps this
    token to a single `"Ashland, OR"` string, added 2026-08-28 when the
    token was believed to serve just Ashland. A 2026-09-03 pin worklist
    (rtr-business's gov-identity cleanup pass) shows it's actually Rogue
    Valley Community Television, serving 6 real governments: Ashland
    city, Ashland School District, Jackson County, Grants Pass, Medford,
    and Eagle Point (real playlist IDs pinned: 5224/5237/5222/5226/5229/
    5242 respectively). Traced the `resolve()` logic (`telvue.py:606-640`):
    when a meeting's title fails to yield any jurisdiction guess at all
    (e.g. a generic, non-city-prefixed title), the code falls straight
    through to the org-level override unconditionally --
    `if not jurisdiction: jurisdiction = known_jurisdiction` -- so a
    Grants Pass or Medford meeting with an ambiguous title would land
    tagged `Ashland, OR`. The base-name-match guard just below it only
    protects against a *different, non-empty* guessed name being
    overwritten; it does nothing for this empty-guess fallback case.
  - **Impact**: any past or future ingest from this org token whose title
    doesn't self-disambiguate its own government risks landing mistagged
    as Ashland, OR instead of its real jurisdiction. Not yet checked
    whether any already-ingested RVTV pages are affected -- that's part
    of the audit, not confirmed either way.
  - **Next action**: needs the same per-meeting resolution this file's
    other multi-gov-token entry (Pacifica, `wuZKb9gwEY7sMACIIsr7VSJglB35kNZA`,
    just above) is waiting on -- a real fix, not a workaround. Held off
    ingesting any new RVTV meeting (Grants Pass/Medford/Eagle Point/
    Jackson County/Ashland-School-District pins) until this is
    addressed, per Ryan's direction 2026-09-03.
  - **History**: found 2026-09-03 investigating a new pin worklist from
    rtr-business's `research/` gov-identity cleanup session, before any
    ingest against these pins.

- **[IMPROVEMENT-ROUND] AV Capture All (`avcaptureall.cloud`) is a real,
  confirmed multi-tenant platform with no adapter yet.**
  - **Issue**: `media.avcaptureall.cloud/meeting/{meetingId}` is a
    Blazor WASM app (raw HTML has zero content — needs a real headless
    browser fetch, the `lims.py`/`slc.py` pattern, not a Cloudflare
    block) whose `<video>` element populates a real, plain,
    unauthenticated, range-capable direct MP4 at
    `download.avcaptureall.cloud/customer-{uuid}/meetings/{meetingId}/
    {title}_{date}.mp4` once it loads, plus a real agenda PDF at a
    sibling path under the same `customer-{uuid}/meetings/{meetingId}/`
    prefix. Confirmed live 2026-09-02 against two independent real
    customers: Suisun City, CA (`.../c9d1a041-ed11-4e78-a1b3-
    fbd6c56b33da`) and Farmington, NM (`.../2fdf5914-d126-4dae-ae03-
    28fb42fd6c05`, found via web search) — identical structure on both.
    Zero captions/text tracks on either sample (AVCaptureAll's own
    marketing claims closed-captioning as a feature, so it may exist on
    some meetings, just not these two) — would ship video-only/tier 3
    to start, same posture as Castus/ChampDS.
  - **Impact**: unblocks Suisun City, CA (this project's own earlier
    check found zero video on its Granicus tenant — real, still true,
    the video was just never on that platform) and at least Farmington,
    NM plus AVCaptureAll's other named clients (Great Falls, Jefferson
    County, Marysville, Oregon City per a web search, none independently
    verified yet).
  - **Next action**: build `app/platforms/avcaptureall.py` following the
    `lims.py`/`slc.py` headless-browser-fetch pattern — the DOM structure
    (real `<video>` `src`/`currentSrc`, a `Title:`/`Scheduled:`/
    `Published:`/`Location:`/`Department:` metadata block) is already
    confirmed on both samples above. Register it in the canary + coverage
    registries per this repo's standing dual-registry obligation for any
    new platform.
  - **Constraint**: needs the headless-browser fetch path
    (`GENERIC_FALLBACK_HEADLESS`-style), not plain `aiohttp` — confirmed
    live that raw HTML carries none of the real content.
  - **History**: found live 2026-09-02 during a Bay Area corpus-expansion
    pass (`~/Documents/rtr-business/research/ENUMERATION_METHODS.md`);
    not yet in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] Tarrant County TX (TechShare.AgendaManagement) agenda-item extraction needs a scoping decision.**
  - **Issue**: the one known sample's accordion markup and a second real
    sample (`meetingId=29112`/`29134`) are structurally different, so a
    parser built from either alone wouldn't work on the other — and the
    confirmed second jurisdiction on the same product, Bell County TX, is
    a client-rendered React SPA, not server-rendered HTML.
  - **Impact**: agenda items stay unextracted for this platform; video
    delegation and page-metadata extraction already work.
  - **Next action**: make a scoping decision before starting — a real
    parser needs headless-browser rendering (for Bell County's SPA), not
    a drop-in second-sample fix.
  - **History**: `BACKLOG_DONE.md` (video delegation and page-metadata
    extraction shipped 2026-08-14; full markup/vendor-discovery detail).

- **[NEEDS-AUDIT] Tarrant County TX (TechShare.AgendaManagement) jurisdiction is never extracted.**
  - **Issue**: jurisdiction is never set for these pages, even though the
    h1-assembled title text already contains it.
  - **Impact**: these pages resolve with no jurisdiction, adding to the
    low-trust/no-jurisdiction count.
  - **Next action**: parse jurisdiction out of the existing h1-assembled
    title text.
  - **History**: `BACKLOG_DONE.md` (same TechShare.AgendaManagement
    build, 2026-08-14).

- **[NEEDS-AUDIT] Anchorage AK's original "bot-blocked YouTube delegation" report no longer reproduces.**
  - **Issue**: the originally observed shape (`hyland.py` YouTube
    delegation finds a real embed, then yt-dlp gets bot-blocked fetching
    it, page ends up video-less) can't happen since commit `b097608`
    (2026-08-09, 16 days before this entry was written) — when an embed
    is found, `resolve_video_id()` already returns a real playable
    `video_url` even if yt-dlp itself is bot-blocked, only captions/
    metadata are lost. Re-tested live 2026-08-30: this specific Anchorage
    page now has zero YouTube references in its fetched HTML at all (a
    generic "no video found," not a bot-block) — a different, unconfirmed
    cause.
  - **Impact**: no confirmed real gap right now; the underlying code path
    is already correct.
  - **Next action**: watch for a fresh example of bot-block-during-
    delegation if this shape recurs elsewhere. Anchorage's new
    zero-YouTube-references cause is separate and not yet investigated.
  - **History**: `BACKLOG_DONE.md` (full re-test detail); PR #496
    (`hyland.py`'s `video_warnings` copy-through made bot-block warnings
    visible).

- **[NEEDS-AUDIT] Vimeo captions and Whisper-fallback audio are blocked by the same signed-config 403.**
  - **Issue**: real, populated English WebVTT genuinely exists (Salisbury
    NC, confirmed via a real browser) but isn't reachable server-side —
    the signed caption URL and the real progressive media file both live
    only inside `player.vimeo.com/video/{id}/config`, which 403s every
    non-browser client; `vimeo.com/{id}` also sometimes serves a real
    Cloudflare challenge.
  - **Impact**: Vimeo-hosted meetings (WO-29) ship video-only with a
    warning pointing at the player's own CC button — no transcript and no
    on-demand Whisper fallback possible today.
  - **Next action**: try the real-headless-browser approach
    `headless_browser.py` already uses for Minneapolis LIMS/SLC —
    untried on Vimeo, not guaranteed to work if the Cloudflare challenge
    is probabilistic.
  - **Constraint**: never attempt to auto-solve a Cloudflare challenge
    (see Standing decisions). The Player SDK's `getTextTracks()`/
    `cuechange` isn't a shortcut — it doesn't yield a whole transcript
    without playing the entire video.
  - **History**: `BACKLOG_DONE.md` (residual of WO-29).

- **[NEEDS-AUDIT] Chicago ELMS's 473 real agenda items have no time offsets to link to video.**
  - **Issue**: `agenda.groups[].items[]` is genuinely rich (matter title,
    type, record number, action, vote — confirmed against the real
    fixture, 473 items) but carries no time offsets at all, so there's
    nothing to join against a video position the way LIMS/Hyland/IQM2 do.
  - **Impact**: agenda item text can't be surfaced as clickable entries;
    the adapter falls back to a working `agenda_link` (the real agenda
    PDF) with no clickable items.
  - **Next action**: this is one instance of a general gap — see
    BACKLOG.md's "Roadmap & strategy" > "Agenda text as a first-class,
    versioned asset," which scopes the model, resolver/adapter work, and
    display together. Do not build a Chicago-specific fix; check whether
    other platforms share this shape first.
  - **History**: `BACKLOG_DONE.md` (residual of WO-29).

- **[NEEDS-AUDIT] ProudCity: Holyoke MA's YouTube 429 recovery status is unchecked.**
  - **Issue**: Holyoke MA's ProudCity push hit a real YouTube 429; a
    same-session retry ~40 minutes later failed a second time, confirming
    this needs real hours to pass, not a quick retry.
  - **Impact**: Holyoke's meeting isn't pushed.
  - **Next action**: do a fresh check now that more time has passed,
    rather than assuming it's recovered.
  - **Constraint**: the specific meeting that hit the 429 still isn't
    identified — checked 2026-08-31 via the WP REST API, which doesn't
    expose a video-URL field, so a fresh check needs that URL first, not
    just "retry once time has passed."
  - **History**: `BACKLOG_DONE.md` (ProudCity adapter shipped, ~18 real
    tenants pushed 2026-08-26).

- **[NEEDS-AUDIT] ProudCity: two tenants remain unpushed (undiscovered domain), one Cloudflare-gated.**
  - **Issue**: Charlotte TX and Brazos Valley COG are too ambiguous to
    guess a domain for and have never been chased. Talent OR remains
    Cloudflare-gated, reconfirmed 2026-08-31 (`www.cityoftalent.org`
    still 403s plain-HTTP). Lafayette CA is **not** actually
    Cloudflare-gated — that framing was stale; it's Akamai, already
    solved via header-spoofing, and its real blocker is no active
    "meeting" post type, not reachability.
  - **Impact**: low priority — the adapter and known-domains list already
    cover the real yield from this round; these tenants stay unpushed.
  - **Next action**: none scheduled. If pursued: Charlotte TX/Brazos
    Valley COG need a real domain lead first; Talent needs the
    Cloudflare-challenge question resolved (see Standing decisions).
  - **History**: `BACKLOG_DONE.md` (ProudCity build; Franklin Township
    NJ, Effingham IL, and George West TX were chased and resolved by
    commit `f838d8a` — Franklin Township confirmed real and pushed as
    agenda-only in `PROUDCITY_KNOWN_DOMAINS`, Effingham/George West
    confirmed no active "meeting" post type).

- **[JUST-DO-IT] City-YouTube-channel fallback: listings only reach ~400 entries per tab.**
  - **Issue**: yt-dlp's channel extraction is not lazy, so the WO-30
    city-YouTube-channel fallback is bounded by `playlistend` (34s for a
    full channel vs. ~6s for 400 entries); on Philadelphia's channel, 400
    entries only reaches back to roughly 2025-06.
  - **Impact**: older meetings on channel-fallback cities show "No video
    link found."
  - **Next action**: cache listings in the DB and paginate deeper over
    time, or use a per-body playlist where one exists — neither
    attempted.
  - **History**: `BACKLOG_DONE.md` (WO-30, 2026-08-21).

- **[JUST-DO-IT] City-YouTube-channel fallback: duplicate-posted meetings decline instead of resolving.**
  - **Issue**: when a city posts the same meeting twice — e.g.
    Philadelphia's 2026-08-06 Committee on Education, present as both a
    `/streams` archive and a `/videos` re-upload — nothing says which is
    canonical, so `_pick()` declines.
  - **Impact**: declining is the correct current posture, but a real
    disambiguation rule would recover a handful of meetings per city.
    Checked live 2026-08-30 across all four fallback cities (Phoenix,
    Baltimore, Albuquerque, Philadelphia; ~1,600 combined listing
    entries): zero other cross-tab date collisions found — Philadelphia
    is still the only confirmed instance of this exact shape.
  - **Next action**: needs more real examples before building anything —
    a rule from n=1 would still be a guess.
  - **Constraint**: don't build a disambiguation heuristic from this
    single example — two prior PrimeGov position/style heuristics for an
    adjacent jurisdiction-extraction bug were reverted for exactly this
    reason.
  - **History**: `BACKLOG_DONE.md` (WO-30, 2026-08-21; live re-check
    2026-08-30).

- **[LATER] `[EXAMPLE]` Town Hall Streams: transcript endpoint unconfirmed-positive; 88-id Wayback population uningested.**
  - **Issue**: the transcript AJAX endpoint is empty on all 7 real
    samples checked, so no confirmed response format exists —
    `townhallstreams.py` deliberately doesn't parse a non-empty response.
  - **Impact**: no transcripts for this platform yet.
  - **Next action**: find a real sample with a non-empty transcript AJAX
    response to confirm the format. Separately, a Wayback CDX scan
    already surfaced 88 distinct `location_id` values (range 28–175) as
    a cheap population to walk and bulk-ingest — not yet done.
  - **History**: `BACKLOG_DONE.md` (townhallstreams.com adapter build).

- **[LATER] `[EXAMPLE]` SuiteOne Media: dead CDX leads and unconfirmed PDF-transcript fallback.**
  - **Issue**: 5 of 11 CDX-derived tenant leads (`mcallentx`,
    `southbendin`, `prescottaz`, `richlandwa`, `laytonut`) 404 as of
    2026-08-21 — dead leads, not an adapter bug. No confirmed real case
    yet of the `/event/GetDocumentFile/{title}?did=N` endpoint serving a
    "Transcript" PDF as the *only* transcript source (the one confirmed
    PDF sits alongside that same event's real VTT).
  - **Impact**: PDF-transcript fallback isn't wired up, deliberately, per
    this repo's "don't claim a data path works without a positive
    example" rule.
  - **Next action**: find a real SuiteOne meeting whose only transcript
    source is the PDF endpoint before wiring up a fallback.
  - **History**: `BACKLOG_DONE.md` (`app/platforms/suiteone.py` build).

- **[LATER] `[EXAMPLE]` Granicus's `captions.vtt` caps at exactly 36,000 cues on some customers.**
  - **Issue**: Granicus's own captioning pipeline (almost certainly
    live-auto-caption) silently hard-caps at exactly 36,000 cues,
    confirmed live 2026-08-15 on three unrelated jurisdictions (College
    Park GA, Coral Gables FL, Marion County FL), each cutting off
    mid-word with no closing punctuation. No cap exists anywhere in this
    repo's own code.
  - **Impact**: long meetings on affected Granicus customers lose the
    tail of their transcript.
  - **Next action**: the exact-36,000 case is already flagged (fixed
    2026-08-16: a `transcript_warnings` entry fires on any Granicus
    resolve with exactly 36,000 segments). Still open: a different,
    unconfirmed round-number cap on a different Granicus customer's
    config — needs a real example before building a detector.
  - **History**: `BACKLOG_DONE.md` (fix shipped 2026-08-16).

- **[LATER] YouTube Whisper fallback for videos with no captions at all isn't built.**
  - **Issue**: the server structurally can't fetch YouTube captions
    itself (yt-dlp, plain timedtext requests, and youtube-transcript-api
    are all confirmed blocked from Render's cloud IP, working fine from a
    home connection), so `scripts/fetch_youtube_transcripts.py` runs on a
    daily schedule instead — but it has no fallback for videos with no
    captions at all.
  - **Impact**: YouTube-backed meetings with no source captions get no
    transcript. Most YouTube videos already have real captions, so this
    is lower priority than other open items.
  - **Next action**: extend the local script to yt-dlp the audio (works
    from residential IPs) for caption-fetch misses, then feed local
    `faster-whisper` directly — decided 2026-08-10 to run this locally,
    not on the worker; not yet built. Distinct from
    `scripts/transcribe_backlog_locally.py`, which can't work on a
    YouTube-backed page's `video_url` at all (its own candidate list
    filters YouTube pages out client-side).
  - **Constraint**: deliberately lower priority than everything else in
    this section. The user is separately pursuing a human/source-side
    option (asking clerks directly, manual YouTube Studio exports).
  - **History**: `BACKLOG_DONE.md`.

- **[IMPROVEMENT-ROUND] Cablecast, TelVue, Swagit, and YouTube still account for most no-jurisdiction pages.**
  - **Issue**: these four platforms account for the large majority of
    pages with no jurisdiction set at all.
  - **Impact**: per `GET /internal/jurisdiction/missing`'s first real run
    (built 2026-08-31): **245** total no-jurisdiction pages — Cablecast
    101, TelVue 50, Swagit 42, YouTube 17, eScribe 12, Vimeo 10,
    CivicClerk 7, unknown 4, TownHallStreams 1, Castus 1.
  - **Next action**: re-run `GET /internal/jurisdiction/missing` before
    trusting the 245 figure — eScribe's hyphen-matcher gap and 5 more
    Swagit special-purpose tenants were both fixed 2026-08-31, after this
    count was taken, so both numbers are likely already lower.
    Cablecast's 101-page per-row audit is the one concrete, scoped
    follow-up regardless (commit `731da71` already recovered 23 of a
    prior 101 via a subdomain-validation fallback at
    `cablecast.py:589-602`, so a similar per-row pass on the current 101
    is plausible). YouTube has no structural fix (`uploader` is a channel
    name, not a government field); Swagit still needs a non-Census entity
    table for the tenants beyond the 5 now registered.
  - **Constraint**: use `GET /internal/jurisdiction/missing` directly for
    current numbers — don't re-derive from `/internal/low-trust-pages`.
  - **History**: `BACKLOG_DONE.md` (WO-38's original 2026-08-21 audit and
    the full superseded-number history through 2026-08-30).

- **[NEEDS-AUDIT] ChampDS's VOD2 HLS case (majority of customers) has no playable video.**
  - **Issue**: confirmed live against 6 real customers when `champds.py`
    was built (2026-08-13): VOD2's HLS URL (4 of 6 customers, no
    `DownloadURL` at all) sits behind a strict
    `Referer: https://play.champds.com/` check this app's own
    server-side requests can't satisfy (confirmed via `curl` with several
    referers, all rejected).
  - **Impact**: VOD2 customers get full metadata + agenda link but an
    honest "no video found"; only the direct-MP4 `DownloadURL` case (2 of
    6) plays.
  - **Next action**: build a real streaming reverse-proxy (fetch
    server-side with the right `Referer`, rewrite segment URLs) — the fix
    is understood and scoped, not attempted.
  - **Constraint**: weigh the bandwidth cost against the same caution
    already attached to the Granicus/azureedge video-proxy idea — ChampDS
    volume would be smaller than Granicus, but the cost shape is the
    same.
  - **History**: `BACKLOG_DONE.md` (video-indexing investigation); moved
    out of Dormant 2026-08-30.

- **[NEEDS-AUDIT] Palm Beach County FL's SharePoint page now escalates correctly; the real video is still unreachable behind client-side JS.**
  - **Issue**: escalation itself is fixed (a SharePoint-specific
    `_spPageContextInfo`/`_layouts/15` fingerprint trigger shipped
    2026-08-31), but the real video — a plain-fetchable Wowza HLS
    manifest at `pbcmedia.pbcgov.org:1936/vod/_definst_/mp4:
    {videoid}.mp4/playlist.m3u8`, confirmed live via network capture,
    where `{videoid}` is literally the page's own query param — never
    appears in the DOM (rendered or raw), only constructed by client JS.
  - **Impact**: `media_scan.scan_media_urls()` still can't find the video
    even after escalation succeeds.
  - **Next action**: a PBC-specific URL-construction rule (derive the
    manifest URL directly from `videoid`) is the next real, scoped step.
  - **History**: `BACKLOG_DONE.md` (2026-08-14 generic-fallback rebuild,
    2026-08-31 SharePoint fingerprint trigger).

- **[LATER] `elpasotexas.gov/videos/` has no adapter of its own.**
  - **Issue**: pasting that URL lands in `generic_fallback.py` instead of
    a "pick a body, then pick a meeting" flow.
  - **Impact**: low priority — every one of El Paso's 13 Vimeo showcases
    already resolves individually (WO-29).
  - **Next action**: none scheduled; low priority.
  - **History**: `BACKLOG_DONE.md` (full investigation).

- **[NEEDS-AUDIT] `[EXAMPLE]` The Phoenix Legistar canary sample is a genuinely dead meeting, and `LegistarAssetFinder._fetch()` has no handling at all for a 404/410 page.**
  - **Issue**: `scripts/adapter_canary.py:150`'s second Legistar URL (`https://phoenix.legistar.com/MeetingDetail.aspx?ID=1425831`, added 2026-08-29) still 410s — re-confirmed live 2026-09-05 via `curl`, and Phoenix's own Legistar API (`webapi.legistar.com/v1/phoenix/events?$filter=EventId eq 1425831`) returns `[]`, so the event is genuinely gone, not a transient blip. `legistar.py`'s `_fetch()` (`app/platforms/legistar.py:466-471`) calls `response.raise_for_status()` unconditionally with no exception handling, so a 410'd page raises before any of the existing fallback chain (`_try_fallback_video_link()` / `_try_known_channel_video()` / `_try_granicus_view_publisher_video()`) ever runs.
  - **Impact**: not production-facing today — every real call site wraps `finder.resolve()` in a generic `except Exception` (`app/main.py`), so a real visitor just gets an unpolished raw-exception-string error rather than a friendly "this meeting listing is no longer available" message. The real cost is the canary itself: it's failed daily (15:00 UTC) since 2026-08-29, and a genuine adapter regression elsewhere in the 30+ platform sweep risks getting lost in an already-red build.
  - **Next action**: swap the canary's Phoenix sample for a currently-live one. Two things found while re-verifying this (2026-09-05) worth handing to whoever picks it up: (1) Phoenix's Legistar pages need the full `?ID=...&GUID=...&Options=info|&Search=` querystring to load at all — the bare `?ID=` form 410s even for a real, live ID (confirmed against three live candidates pulled from `Calendar.aspx`: `1364180`/GUID `FE7842A8-9AF7-4022-90A6-9B0247C8DAB9`, `1363991`, `1363958`); (2) Phoenix's Legistar API shows `EventVideoPath: null` for every one of its 10 most recent events, matching the existing "Phoenix has no direct Legistar video links site-wide" finding (`BACKLOG_DONE.md`, 2026-08-11 survey) — so a good replacement sample must specifically exercise the WO-30 YouTube-channel fallback (a *past* meeting whose date/title should match Phoenix's YouTube channel), not just any live page. Separately, catch 404/410 in `_fetch()` and return a `ResolvedMeeting` with a friendly `video_warnings` message, the same pattern "no video link found" already uses.
  - **History**: `BACKLOG_DONE.md` (2026-08-11 survey first documented this meeting ID as gone). Flagged by the inbox-triage Routine's 2026-08-30 run; recurred identically on every canary run since (2026-08-30, 08-31, twice on 09-01/09-02).

## Reliability, ops & cost

### `[JUST-DO-IT]` Render *pipeline minutes* — build volume cut twice, still at the allowance

- **Issue**: Render pipeline-minutes usage hit **1,001 / 1,000** (confirmed
  2026-08-29 via the Included Usage dashboard) — already over the included
  allowance, despite two rounds of `buildFilter` cuts and `autoDeploy:
  false` on all four blueprint services.
- **Impact**: risks the same silent, multi-hour deploy block hit on
  2026-08-19 (~5.5 hours, no alert, merge≈deploy just quietly stopped
  being true) recurring, and blocks Ryan's plan to downgrade the
  workspace tier once build volume is efficient enough — not yet met.
- **Next action**: read per-service build *minutes* (not just build
  *counts*) off the Included Usage dashboard to find where the remaining
  spend concentrates — nobody has done that yet.
- **Constraint**: don't add a new Render service without a `buildFilter`
  — two undeclared staging services rebuilt on every single push for
  weeks before being caught on 2026-08-25, because a service created only
  in the dashboard (not in `render.yaml`) has no filter and nothing in
  this repo will tell you it exists.
- **History**: `BACKLOG_DONE.md` `[Done 2026-08-22]` (root cause + the
  two `buildFilter` rounds) and WO-59 `[Done 2026-08-25]` (`autoDeploy:
  false` + the batch-merges/ask-before-deploy convention).

- **[LATER] Tighten the two transcription workers to their real import
  surface.** Scoping their `buildFilter` to the ~4 subtrees
  `worker/main.py` actually imports would cut their build count further.
  **Deliberately declined 2026-08-22**: it makes a build trigger depend
  on an import graph, so the first new `from app.… import …` added
  without a matching `render.yaml` edit leaves a worker silently running
  stale code. Only worth doing alongside a CI guard that keeps the two in
  sync. History: `BACKLOG_DONE.md` `[Done 2026-08-22]`.

### Media-source reliability

#### `[NEEDS-AUDIT]` Some old/archived Granicus clips' `chunklist.m3u8` genuinely times out at Granicus's own origin (real 504, not a rate limit)

- **Issue**: some archived Granicus clips hang for minutes on
  `chunklist.m3u8` before Granicus's own CloudFront edge returns a real
  `504 Gateway Timeout` — confirmed 2026-08-21 with `ffprobe -v verbose`
  against Fountain Valley CA clip 607 using the app's real request
  headers (4-6 minute hang, then a genuine 504). `media_probe.py`'s own
  120s timeout is shorter, so in production this always looks like our
  own "ffmpeg timed out" first — the 504 that would eventually arrive is
  never actually seen.
- **Impact**: affects a small, not-yet-fully-sized slice of old/archived
  clips. WO-83 (`2857d53`, #609, 2026-08-30) confirmed the failure mode
  is still live: the same 8 `archive-stream.granicus.com` candidates were
  being re-selected identically for 25+ hours before that fix landed.
- **Next action**: add worker logging that distinguishes a real
  5XX-after-a-long-hang from an ordinary connection-level timeout, so
  this pattern stops being rediscovered from scratch. Not yet built.
- **Constraint**: don't raise `_SUBPROCESS_TIMEOUT_SECONDS` to match
  Granicus's own gateway timeout — that ties up a worker chunk slot for
  minutes on every genuinely-dead asset, trading a fast clear failure for
  a slow identical one. Current measurement (2 of 218 terminal failures,
  ~4% of worker-hours) says this isn't costing much either way today, but
  that's one measurement — not a permanent Standing decision, worth
  re-checking as job volume grows.
- **History**: `BACKLOG_DONE.md` — WO-83 `[Done 2026-08-30]` fixed the
  downstream symptom (the backlog driver now records probe-only
  feasibility failures so cooldown engages instead of looping on the same
  dead candidates forever); the root 504/timeout issue and the logging
  distinction above remain open here, not touched by that fix.
- **Untested tool, not a fix**: `ViewPublisherRSS.php?mode=vpodcast` (a
  Granicus RSS mode found 2026-09-04, see
  `~/Documents/rtr-business/research/ENUMERATION_METHODS.md` §58) adds a
  direct-download `<enclosure>` URL (`DownloadFile.php?...clip_id=N`)
  per item, on a different origin than `archive-stream.granicus.com`'s
  CDN — a plausible alternate source for a clip stuck on this timeout,
  not verified against one.

#### `[NEEDS-AUDIT]` A single job still makes N consecutive pulls to the same host (WO-40 falsified the round-robin fix)

- **Issue**: `claim_next_chunk()` claims a whole *job* and the worker
  holds it through every chunk, so a 21-chunk meeting is still 21
  consecutive pulls from one host inside a single job — queue-level
  reordering can't reach inside a job.
- **Impact**: none currently measured. WO-40 (2026-08-21) tested "workers
  hammer one host across consecutive jobs, so round-robin the queue by
  host" against all 514 production jobs and falsified it:
  `same_host_different_job` failure pairs within 10 minutes were **0**,
  and chunk 0 is 3-4x more failure-prone per attempt than any later
  chunk — the opposite of what an accumulating rate limit would predict.
- **Next action**: none planned. Current default is to leave within-job
  pull ordering alone — both real mechanisms WO-40 found (cold-storage
  rehydration, where chunk 0 warms the asset for chunks 1..N; and a
  persistently-slow source, which doesn't care about pacing) argue
  against spreading pulls. Not re-measured since; worth another pass with
  fresh data as job volume grows rather than treating this as
  permanently settled.
- **History**: `BACKLOG_DONE.md` (WO-40, 2026-08-21) — full numbers and
  the `GET /internal/transcription-failure-analysis` endpoint.

#### `[NEEDS-AUDIT]` The 120s ffmpeg timeout is a flat value that doesn't adapt per source

- **Issue**: `_SUBPROCESS_TIMEOUT_SECONDS` is a flat 120s for every
  source, with no way to widen or defer it for a job that's already
  showing a slow-source pattern.
- **Impact**: measured small. Timeouts are 2 of 218 terminal job failures
  (129 are "No usable audio or video source was found," which is where
  the real volume is). A second, throughput-focused measurement
  (2026-08-22) found 106 timeout failures across 18 jobs in two days —
  ~3.5 hours of retry against ~96 worker-hours available, about **4%**.
  Timeouts are not what caps real output at ~35 jobs/day (see "backlog
  keeps shrinking," below, for the actual cap).
- **Next action**: two ideas considered, neither built: (1) detect the
  slow-source shape early — a job whose first few chunks all need retries
  will need them throughout — and widen or defer that job's timeout
  rather than grinding repeated retries through the same slot; (2) add
  the same real-5XX-vs-ordinary-timeout logging distinction called for in
  the Granicus entry above.
- **Constraint**: whatever gets built must never starve a real
  user-submitted `PRIORITY_MEDIUM` job behind automated `PRIORITY_LOW`
  backlog work.
- **History**: `BACKLOG_DONE.md` (WO-40, 2026-08-21) — same failure-
  pattern measurement this residual is drawn from.

#### `[NEEDS-AUDIT]` East Lansing MI (Granicus): a new, deterministic ffmpeg filter-graph failure has no known fix

- **Issue**: `eastlansing.granicus.com/player/clip/1211?view_id=2`, chunk
  1, fails identically every time with exit 234 / "Failed to configure
  output pad on auto_aresample_0" / "Error reinitializing filters!" —
  reproduced twice on separate transcription attempts two days apart
  (job 1238, 2026-08-30 05:56 UTC; job 1294, 2026-08-31 06:42 UTC), each
  with all 3 retries hitting the exact same error text, including after
  the WO-45 output-side-seek retry (which fixes a different, empty/
  undecodable-file failure shape, not this one). No fix attempted yet —
  confirmed 2026-09-05: no `aresample` reference anywhere in
  `app/platforms/media_probe.py` or `worker/main.py`.
- **Impact**: this meeting has zero transcript (gave up at chunk 1/27).
  Scope beyond this one source is unmeasured — no query groups failures
  by this exact error string yet.
- **Next action**: run `ffmpeg` directly against the real source at the
  chunk-1 offset to see if this reproduces outside the app's own
  subprocess context, and whether explicitly forcing
  `-af aresample=async=1` (already known safe from the Napa VOD
  investigation, for a different, cosmetic dts-warning case) happens to
  route around this filter-config failure too.
- **History**: found by the inbox-triage Routine's 2026-08-30 run;
  confirmed deterministic (2nd occurrence, same source/chunk) in the
  2026-08-31 run.

### Transcription queue & workers

- **[NEEDS-AUDIT] `chunk_plan` stores JSON `null` rather than SQL NULL, so
  `IS NOT NULL` matches 63 rows that aren't multi-clip jobs at all.**
  - **Issue**: `TranscriptionJob.chunk_plan` is
    `mapped_column(JSON, nullable=True)` (`archive/db/models.py`), and
    SQLAlchemy's `JSON` type defaults to `none_as_null=False` — a Python
    `None` is persisted as the JSON value `null`, not SQL NULL. Verified
    directly against SQLAlchemy 2026-09-03, not inferred from docs.
  - **Impact**: `WHERE chunk_plan IS NOT NULL` returns **66 rows, of
    which only 3 are real multi-clip jobs** — 95% noise. Nothing
    misbehaves at runtime (every consumer tests truthiness, `if
    chunk_plan:` / `if not plan`, which is correctly falsy for `None`),
    so this is a query-correctness and auditability problem, not a
    functional one. It bit a real audit: the 2026-09-03 sweep for
    oversized clips (WO-95) had to filter the decoded value in Python
    after `IS NOT NULL` let 63 single-video jobs through, and the
    obvious SQL-only version of that query would have looked like it
    worked while silently misreporting. The column's own comment also
    asserted "NULL for every ordinary single-video job", which was
    simply wrong — corrected in the same change as this entry.
  - **Next action**: prefer fixing the read side over migrating data —
    `jsonb_typeof`/`json_typeof(chunk_plan) = 'array'` (note `json`, not
    `jsonb`: this is a plain `JSON` column, the same distinction that
    produced a real 500 in `get_transcription_queue_summary()`, see its
    docstring) is an exact predicate and needs no migration. Setting
    `none_as_null=True` on the column would fix new writes but leaves
    every existing row, so it needs a backfill to be worth anything, and
    the runtime behaviour is already correct either way.
  - **Constraint**: any change must keep `if not chunk_plan` working for
    both shapes — a plan frozen before the change and one written after —
    since that truthiness test is what three separate consumers rely on
    (`worker/main.py`, `scripts/transcribe_backlog_locally.py`,
    `app/main.py`). Don't "fix" it by making consumers test for SQL NULL.
  - **History**: found 2026-09-03 while auditing every multi-clip job for
    WO-95's oversized-clip bug. Worth knowing alongside that entry: all
    3 real multi-clip jobs in the table's whole history had at least one
    clip over their own cap — the feature had a 100% failure rate on long
    clips, which was invisible partly because this predicate made
    multi-clip jobs look 22x more common than they are.

- **[NEEDS-AUDIT] An OOM-killed chunk is completely invisible — it
  records no failure, counts toward no retry cap, and silently discards
  up to a chunk's worth of work.**
  - **Issue**: a Render OOM kill terminates the worker process before
    `report_chunk_result()` can run, so nothing is written to
    `TranscriptionJob.failure_history`, `consecutive_chunk_failures`
    never increments, and `MAX_CONSECUTIVE_CHUNK_FAILURES` is never
    reached. `claimed_at` simply goes stale after `STALE_CLAIM_AFTER`
    (5 min) and the same chunk is re-claimed as if nothing happened.
  - **Impact**: OOMs are undetectable from the app's own data. Confirmed
    2026-09-01: Render reported two "Ran out of memory (used over 2GB)"
    kills on `rtr-transcription-worker-2`, while
    `/internal/transcription-failure-analysis?days=1` showed 7 failures,
    all ffmpeg timeouts, and zero trace of either kill. Every OOM also
    throws away that chunk's work in progress — up to ~15 min at the
    production pool's measured per-chunk pace — and a chunk that OOMs
    deterministically will loop on that cycle indefinitely rather than
    failing out. WO-94 removed one trigger (chunk size 900s → 450s,
    peak RSS 1588MB → 977MB) but not the blind spot — and on
    2026-09-02 the loop this describes ran for real: job 1419's
    2,519s multi-clip chunk (WO-95) OOMed ~40 times over 3.5 hours,
    and cost ~3.5 hours of diagnosis the worker's own data could not
    shorten, because it recorded nothing. Throughput fell 42 → 14
    jobs/day while it ran. No longer a theoretical cost.
  - **Next action**: detection before prevention, and the cheap version
    is enough — the process is killed, so it cannot report anything
    itself, but the *next* process can notice: on startup, look for a
    job whose `claimed_at` went stale without `chunks_completed` moving,
    and record that as a distinct outcome. That also covers the
    heartbeat-wedge entry below, which is the same blind spot seen from
    the other end.
  - **Constraint**: must not conflate an OOM with an ordinary
    crash/restart/deploy, all of which produce the same stale claim —
    and must not re-introduce the duplicate-window corruption WO-57
    shipped to stop. Detection only; do not shorten
    `STALE_CLAIM_AFTER` to make OOMs surface faster.
  - **History**: found 2026-09-01 while diagnosing the two live OOM
    kills that produced WO-94. Related: the heartbeat/no-timeout entry
    directly below (a wedged job, rather than a killed one, is the same
    invisibility from the opposite direction).

- **[NEEDS-AUDIT] WO-57's claim heartbeat has no cap, and transcription
  has no timeout — together they can pin a job `in_progress` forever.**
  - **Issue**: `_heartbeat_loop()` (`worker/main.py`) refreshes
    `claimed_at` every 60s `while True:` until its surrounding block
    exits, and that block ends in `engine.transcribe_chunk()` →
    `asyncio.to_thread(self._transcribe_sync, ...)`
    (`worker/transcription_engine.py:200`) with **no `wait_for` and no
    timeout**. ffmpeg is bounded (2x `_SUBPROCESS_TIMEOUT_SECONDS`);
    faster-whisper is not.
  - **Impact**: a wedged transcription call keeps its claim fresh
    indefinitely — `STALE_CLAIM_AFTER` never fires, no other worker
    reclaims the job, and it sits `in_progress` with no error and no
    failure email. Found 2026-08-25 by reading the code; **not yet
    observed firing in production.** This is a known trade-off, not a
    regression: before WO-57 the same wedge went stale after 5 minutes
    and got reclaimed, which is exactly the duplicate-window/skipped-
    chunk corruption WO-57 shipped to stop. Stuckness is the better
    failure than corruption, but it's silent.
  - **Next action**: build detection first, since it's the cheaper half —
    nothing currently reports a job whose `chunks_completed` hasn't moved
    far longer than its own observed per-chunk pace. This is the same
    blind spot as the pool-wide "chunks flat while jobs active" check
    shipped 2026-08-28, which only catches the whole pool going dead, not
    one job wedged while the rest of the pool keeps moving.
  - **Constraint**: any real cap must clear the measured legitimate case
    by a wide margin — job 911 (Detroit, 21 chunks, `probed_duration`
    18445.511s) completed 7 chunks between 14:22 and 16:08 UTC, ~15
    min/chunk on the production pool, itself 3x `STALE_CLAIM_AFTER`.
    Neither fix candidate is clean: capping the heartbeat's lifetime
    reopens WO-57's corruption whenever a chunk legitimately runs past
    the cap; wrapping transcription in `asyncio.wait_for` can't actually
    cancel `to_thread`, so the thread leaks and the model stays loaded.
  - **History**: `BACKLOG_DONE.md` — WO-57 (duplicate-window/skipped-
    chunk fix) and the 2026-08-28 pool-wide "chunks flat" check.

- **[NEEDS-AUDIT] Backlog keeps shrinking — re-derived 2026-08-31.**
  - **Issue**: tracking whether the transcription backlog is actually
    shrinking, and whether the tier-3/Granicus-feed rate cuts imposed
    earlier are still warranted.
  - **Impact**: none — this is a status check, not a bug. Live-checked
    via `GET /internal/transcription-queue-stats`: `backlog_no_transcript`
    is 547 today (was 781 on 2026-08-22, 562 on 2026-08-30), and
    `tier3_queue_remaining` is 1227 (was 1289, then 1317) — both
    declining, not just flat. `jobs_completed_last_24h: 38`.
  - **Next action**: re-derive these numbers again once a post-fix
    `bulk-queue-transcription-backlog.yml` run shows "N created" with
    N > 0 — today's figures predate or barely overlap WO-83's effect, and
    a separate ffprobe-missing-on-runner regression was masking runs as
    "0 created, 8 skipped" until it was found and fixed 2026-08-31.
    Re-decide the rate-cut question at the same time rather than assuming
    it's still needed.
  - **History**: `BACKLOG_DONE.md`'s "CI ffprobe regression, fixed" entry
    (2026-08-31).

- **[LATER] `list_transcription_backlog_candidates()` still does a real
  N+1 query pattern.**
  - **Issue**: found 2026-08-21 — unlike `find_auto_transcription_
    candidate()` (rewritten 2026-08-17 to a single SQL predicate after
    being confirmed the #1 consumer of production DB time), this
    function still does a full page scan plus a separate DB round trip
    per page in a Python loop.
  - **Impact**: each individual query is cheap, so this isn't the
    102MB-JSON-load class of incident — but it's O(n) round trips, and
    `GET /internal/transcription-backlog` is now hit **hourly** by a
    scheduled workflow (previously only occasional human use).
  - **Next action**: not fixed yet — the daily report's own summary query
    needed only a count and already reuses the fast predicate directly.
    Worth rewriting this function the same way if hourly load ever makes
    it a measured problem.
  - **Constraint**: check `pg_stat_statements` before assuming it's a
    problem — don't guess.
  - **History**: `BACKLOG_DONE.md` (2026-08-17 `find_auto_transcription_
    candidate()` rewrite) — the pattern to copy.

- **[LATER] Second transcription worker's auto-generation TOCTOU race —
  avoided by construction at N=2, not fixed at the DB layer.**
  - **Issue**: `maybe_generate_auto_job()`'s candidate check and
    `create_transcription_job()`'s check-then-insert are both unlocked,
    so two idle workers could both pass the check for the same page
    before either commits.
  - **Impact**: wasteful duplicate jobs, not data-corrupting —
    `promote_transcript_version()` still settles cleanly on one version.
    `claim_next_chunk()` itself is genuinely race-safe for any number of
    workers (`FOR UPDATE SKIP LOCKED`). Currently safe only because
    `render.yaml` defines `rtr-transcription-worker-2` as its own service
    block specifically so `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` can stay
    unset on it, making the unsafe path structurally unreachable on this
    two-worker pair.
  - **Next action**: none needed at N=2. If scaling past two workers, add
    a unique partial index/row lock in `create_transcription_job()`'s
    existing-job check.
  - **Constraint**: don't enable auto-generation on a third worker (or set
    that env var on worker-2) without building the real DB-layer fix
    first — it reintroduces the race immediately.
  - **History**: `BACKLOG_DONE.md` — full build log of the two-worker
    setup.

### Search Console, structured data & SEO plumbing

- **[HUMAN] `[LOGIN]` `[WAIT]` "Reasons preventing pages from being
  indexed" — three of four categories settled, one still open.**
  - **Issue**: the 2026-08-23 alert named four categories with no URLs
    attached. Three are now resolved or explained; "Not found (404)" is
    the one still without a URL list.
  - **Impact**: unknown how much of the "Not found (404)" category is
    real de-indexed content vs. explained noise. `/state/{slug}`,
    `/j/{slug}`, and `/m/{slug}` all correctly 404 for an unknown slug, so
    genuine 404s are expected after a de-index — and a related but
    distinct bug (a reslugged old permalink serving 200 with a different
    canonical instead of a real 301) was found and fixed 2026-08-31.
  - **Next action**: re-check a future Search Console export for whether
    any reslugged old permalinks now show up as 301s, now that the
    redirect fix has landed.
  - **Constraint**: the other two categories — "Alternate page with
    proper canonical tag" and "Duplicate, Google chose different
    canonical than user" — are the deliberate, documented consequence of
    `state_page.html:10-17` and `meeting_list.html:8-11`'s
    canonicalization. Do not "fix" these without deciding to reverse
    those choices.
  - **History**: `BACKLOG_DONE.md` — WO-62 (Soft 404 fix, Fairview TN's
    `agenda_link`-only page), "Five frozen-slug pages reslugged"
    (2026-08-28), and the 2026-08-31 redirect fix.

- **[NEEDS-AUDIT] New "Missing field" flags — Videos `uploadDate`, Events
  `startDate` (both 2026-08-31) — likely trade-off of the 2026-08-21
  datetime-validation fix.**
  - **Issue**: promoted from `CLAUDE_INBOX_TRIAGE.md`; a different flag
    from the now-closed `thumbnailUrl` entry (see `BACKLOG_DONE.md`).
    `archive/templates/meeting_page.html:128-138` and `:208-209` gate
    both fields on `{% if iso_date %}`, emitting only when present — a
    deliberate 2026-08-21 fix (per the template's own comment) for a
    companion "invalid datetime value" flag that used to concatenate an
    unvalidated free-string date straight into the JSON-LD.
  - **Impact**: a page whose `page.date` is null or unparseable now emits
    *neither* field, trading "invalid" for "missing" — exactly today's
    new flag. That trade-off was made in code 2026-08-21 but never
    written down. How many real pages this affects is unconfirmed.
  - **Next action**: with the `ARCHIVE_INGEST_TOKEN` bearer token (this
    session doesn't have one), run `curl -H "Authorization: Bearer
    $ARCHIVE_INGEST_TOKEN" "$ARCHIVE_BASE_URL/internal/date-format-
    audit"` — the endpoint (`archive/main.py:959`) already exists for
    exactly this — to get the real null/unparseable-date page count
    before deciding on a backfill, a per-adapter date-capture fix, or
    just accepting the gap.
  - **History**: none yet — this is a fresh finding, not previously
    investigated.

### `/coverage` as a QA surface

- **[JUST-DO-IT] `/coverage`'s "Every place we've covered" table is a
  real, useful place to spot resolver bugs by eyeballing outliers — but
  the practice has lapsed.**
  - **Issue**: confirmed useful 2026-08-15, but no fresh eyeball pass has
    been logged since 2026-08-21.
  - **Impact**: real bugs get missed until someone happens to scan again.
    The original 2026-08-15 pass over 501 rows surfaced several real bugs
    in one session (wordninja-acronym cases, a second adapter with the
    same unbounded-regex bug already known on Granicus, a genuine
    wrong-title/wrong-jurisdiction mismatch). A follow-up full-production
    scan (WO-16) found the table had grown to 843 rows within a week —
    roughly double. Substantial jurisdiction work has landed in the ten
    days since (Oakville/Courtenay fix, leading-"The" gap,
    subdomain-override repair, a missing-jurisdiction sweep, WO-88's
    CivicClerk fix) without a fresh pass over the table.
  - **Next action**: do a fresh eyeball pass over the full `/coverage`
    table — due for one.
  - **Constraint**: treat this as a repeatable practice after any batch of
    new adapter/jurisdiction work, not a one-time task.
  - **History**: `BACKLOG_DONE.md` (WO-16 full-production scan,
    2026-08-15/16).
## Trust, safety & data quality

### `[LATER]` No blanket backfill can make pre-2026-08-21 `best_effort` accurate

- **Issue**: `best_effort` records *how* a resolve was performed, and
  nothing on a page archived before WO-21 (2026-08-21) preserves that — a
  delegated-to-YouTube result reads byte-for-byte identical to a native
  one.
- **Impact**: every page archived before 2026-08-21 has `best_effort =
  false` regardless of its real trust level.
- **Next action**: no blanket fix is possible; run
  `scripts/backfill_archived_pages.py` (a re-resolve sweep) against
  whichever pages need real accuracy — it corrects them individually.
- **History**: WO-21 (2026-08-21) build in `BACKLOG_DONE.md`.

### `[NEEDS-AUDIT]` California county jurisdiction names split across two conventions, fragmenting hub pages

- **Issue**: some California county pages store `jurisdiction` as
  `"County of {Name}, CA"` (a raw, unnormalized prefix form) instead of
  this project's own majority convention, `"{Name} County, CA"`.
  Confirmed live 2026-09-02 via `GET /internal/export/pages` (all 4,923
  archived pages): 44 counties use the suffix form correctly, but 13 —
  Fresno, Humboldt, Imperial, Marin, Monterey, Napa, Placer, Plumas, San
  Bernardino, San Diego, San Mateo, Santa Clara, Solano — have at least
  one page stored as `"County of {Name}, CA"`. `jurisdiction_enrich.py`'s
  `_split_entity_prefix()` docstring already documents a "County of X"
  → "X County" normalization step (built for a different case, stripping
  it out of a body-name split like "Housing Authority of the County of
  Santa Clara"), so the raw prefix form surviving into `jurisdiction`
  itself suggests some resolve path (a Granicus RSS channel title taken
  verbatim is the leading suspect, not yet confirmed) bypasses that
  normalization rather than the normalization having a bug.
- **Impact**: real, measured fragmentation for at least 3 counties — the
  same government's pages split across two different `/j/{slug}` hubs,
  invisible to each other: Santa Clara (7 pages under the correct suffix
  form, 1 stranded under the prefix form), San Diego (2 vs 1), Solano (1
  vs 1). Marin (3 pages) and San Mateo (3 pages) aren't fragmented yet
  only because no suffix-form page exists for them yet — the next
  Marin/San Mateo County resolve could create the same split. Originally
  surfaced as a user report ("Napa County was already live in prod but
  called 'County of Napa'") — Napa itself has only the prefix form so
  isn't fragmented, but is the same underlying bug.
- **Next action**: find the actual resolve path producing the raw
  `"County of {Name}"` string (check Granicus's RSS-channel-title
  jurisdiction source first, per `_split_entity_prefix()`'s own docstring
  reasoning) and route it through the existing normalization instead of
  bypassing it; separately, a one-time backfill/merge is needed for the
  3 already-fragmented counties (re-resolve or hand-correct the stranded
  pages' `jurisdiction`, then re-check `/j/{slug}` hub grouping).
- **Constraint**: don't hand-fix only Napa/Santa Clara/San Diego/Solano
  and call it done — all 13 listed above carry the same latent risk of
  a future split. `~/Documents/rtr-upcoming/scripts/check_county_naming.py`
  solved the analogous problem in that sibling project (a jurisdiction
  name is display copy, nothing validates it) with two independent
  signals — vendor host/path containing "county", and real meeting
  titles containing "Board of Supervisors" — worth reusing that same
  detection shape here rather than inventing a new one.
- **History**: found live 2026-09-02 during a Bay Area corpus-expansion
  pass (`~/Documents/rtr-business/research/ENUMERATION_METHODS.md`);
  not yet in `BACKLOG_DONE.md`.

### `[NEEDS-AUDIT]` YouTube-delegated ingests can land with `jurisdiction=None` when the channel doesn't self-identify

- **Issue**: 10 real Portola Valley, CA Town Council meetings (direct
  `youtu.be` links from `portolavalley.net/town-government/town-council/
  minutes-and-agendas`, ingested 2026-09-02) all resolved with
  `jurisdiction=None` — confirmed directly via `YouTubeAssetFinder.
  resolve()`, not just observed on the rendered page. Real transcripts
  (2,109-8,049 segments each) are present; only jurisdiction is missing.
- **Impact**: these 10 pages won't appear on any `/state/{slug}` or
  `/j/{slug}` hub (both require a recognized `", ST"` suffix), and land
  in `/internal/low-trust-pages`'s `unverified_jurisdiction` bucket.
  **Patched live 2026-09-02** (real user report: pages visibly missing
  jurisdiction in prod) via `POST /internal/jurisdiction/override` — all
  10 page ids now carry `jurisdiction="Portola Valley, CA"` and
  `jurisdiction_confidence="manual_override"`, confirmed rendering
  correctly (state/hub links present) on `/m/2026-05-14-05-13-2026-town-
  council-meeting`. This is a per-page patch, not a fix — the root cause
  below is still open, and the next real YouTube ingest with this same
  gap won't self-correct.
- **Next action**: check what YouTube metadata (channel name/description,
  video description) is actually available for this channel and whether
  `youtube.py`'s jurisdiction extraction already tries it — video titles
  here are bare dates ("08-26-2026 Town Council Meeting"), no city name
  in the title itself, so a title-only guess was never going to work;
  the channel-level metadata is the more promising signal, not yet
  checked.
- **History**: found live 2026-09-02 during the same corpus-expansion
  pass as the entry above; not yet in `BACKLOG_DONE.md`.

### `[LATER]` `best_effort` is sticky — nothing at ingest distinguishes a full resolve from a partial push

- **Issue**: every transcript-only pusher sends a partial payload where
  `best_effort` defaults to `False`, and nothing at the ingest boundary
  can tell a full resolve from a partial push, so an unconditional
  overwrite would let a partial pusher silently un-flag a genuinely
  unverified page — so the flag only ever gets set, never cleared, by
  the current logic.
- **Impact**: a page later re-resolved for real by a vendor adapter keeps
  a stale `best_effort=true`, so the low-trust review queue needs pruning
  by hand instead of self-correcting.
- **Next action**: build a way to distinguish a full resolve from a
  partial push at the ingest boundary — nothing does this today.
- **History**: WO-21 (2026-08-21) build in `BACKLOG_DONE.md`.

### `[IMPROVEMENT-ROUND]` Low-trust queue rows have no repair workflow wired up

- **Issue**: `GET /internal/low-trust-pages` (WO-38, 2026-08-21) surfaces
  real data-quality rows and lets a human mark one reviewed, but that
  only records that someone looked — it doesn't repair the missing
  jurisdiction. No UI either — curl-only, workable only because it's Ryan
  alone working it.
- **Impact**: it's a data-quality queue, not a trust queue — real live
  pages with real video whose jurisdiction couldn't be determined, not
  suspected spoofs. Re-derived live 2026-08-31: **604 rows** (546
  `unverified_jurisdiction`, 61 `best_effort`, 14 `unknown_platform`;
  reasons can overlap per page, so they sum to more than 604) — up from
  474 at last count and 631 on 2026-08-30. `best_effort` was zero at the
  original 2026-08-21 measurement and no longer is.
- **Next action**: wire `POST /internal/jurisdiction/override` (built
  2026-08-31, writes an explicit jurisdiction string and stamps
  `reviewed_at` in the same call, but unused against any real row yet)
  into an actual review-then-repair workflow.
- **Constraint**: re-derive the row counts before quoting them — they
  move with every ingest.
- **History**: WO-38 (2026-08-21) build in `BACKLOG_DONE.md`.

### `[IMPROVEMENT-ROUND]` A low-trust review doesn't expire when the page is re-ingested

- **Issue**: `reviewed_at` survives a later re-ingest, so a page reviewed
  today and re-resolved tomorrow with different content still reads as
  reviewed.
- **Impact**: the review queue can silently mask a page whose content
  changed after it was checked.
- **Next action**: compare `reviewed_at` against `updated_at` to surface
  pages that changed post-review; nothing does this yet.
- **History**: WO-38 (2026-08-21) build in `BACKLOG_DONE.md`.

### `[LATER]` Mastodon auto-posting has made zero real posts

- **Issue**: no Mastodon account exists yet, so the Mastodon client is
  schema-verified but not content-verified.
- **Impact**: Mastodon announcements aren't confirmed to work at all,
  unlike Bluesky (live since 2026-08-21 — a real prod resolve created a
  page and the account made its first real post, confirmed by Ryan).
- **Next action**: create the account + token, then watch one real post go
  through — the same bar Bluesky already cleared.
- **History**: Bluesky auto-posting build in `BACKLOG_DONE.md`.

### `[IMPROVEMENT-ROUND]` Social auto-posting only fires on page creation, not on a later transcript upgrade

- **Issue**: only page *creation* triggers a social post — the worker's
  transcript-write path never touches the posting hook.
- **Impact**: a page first created agenda-only (or garbled) that later
  gains a real, high-quality transcript is never announced.
- **Next action**: not started — deliberate v1 scope. The `SocialPost`
  claim table already supports an upgrade-triggered post without schema
  changes if it's built.
- **History**: Bluesky auto-posting build (2026-08-21) in
  `BACKLOG_DONE.md`.

### `[LATER]` Prompt injection isn't a live product risk today, but the boundary needs re-checking before certain future features

- **Issue**: nothing in the deployed serving path lets an LLM read scraped
  content and act on it — every adapter parses with deterministic
  regex/BeautifulSoup/JSON extraction, and `worker/`'s Whisper transcribes
  audio to text without interpreting spoken instructions. The one place
  scraped government content reaches an LLM at all is when Claude, during
  development, fetches and reads a real government page directly —
  already covered by the standard instruction-source-boundary rule.
- **Impact**: none today; would become a live risk the moment any feature
  reads scraped content *through* an LLM in the deployed serving path (an
  "AI summary," semantic re-ranking, etc.) — nothing like that is planned.
- **Next action**: none now — re-read this entry before building the first
  feature that routes scraped content through an LLM in production.
- **History**: threat-modeled 2026-08-10, prompted directly by Ryan asking
  whether to worry about prompt injection / fake government submissions;
  see `TRUST_THREAT_MODEL.md`.

### `[HUMAN]` `[BIG]` Nothing verifies a submitted URL is a genuine government site

- **Issue**: fake/spoofed "government" pages and non-government content
  can be archived and presented as if official — no verification step
  exists for a submitted URL's site.
- **Impact**: wide open gap, threat-modeled in `TRUST_THREAT_MODEL.md`;
  affects trust in every page the product presents as official.
- **Next action**: Ryan's call on what to build next. Two mitigations
  already shipped: `noindex` on `generic_fallback`/`unknown` pages
  (2026-08-11), and social auto-posting refusing `best_effort` /
  `platform == "unknown"` pages (WO-21, 2026-08-21). The rest are
  unsequenced.
- **History**: threat-modeled 2026-08-10; see `TRUST_THREAT_MODEL.md`.

### `[NEEDS-AUDIT]` Chula Vista's stale garbled-marker survives its own fix until redeployed and re-resolved

- **Issue**: `is_likely_garbled()`'s tokenizer false-flagged real
  bilingual (Spanish) transcripts as garbled; fixed in code (PR #641,
  2026-08-31), but the already-stored page — Chula Vista Public Comments
  2026-05-19 (eScribe, version 816) — still carries the stale marker,
  since per this repo's marker-gating convention a garbled-marked page
  stays permanently un-re-transcribable until it's actually re-checked.
- **Impact**: low — the page already defaults to serving its
  English-transcribed version, so no reader currently sees the flagged
  Spanish one, but the marker won't clear itself.
- **Next action**: once `rtr-deeplink` (the resolver) is redeployed with
  the PR #641 fix, hit `/api/refresh-archived-page` for that meeting's
  `source_url` (or wait for its natural next re-check) so the fixed
  heuristic re-runs and clears the stale marker.
- **History**: fix detail and live verification against the real Chula
  Vista transcript in `BACKLOG_DONE.md`.
## Roadmap & strategy `[IMPROVEMENT-ROUND]`

**Architectural context:** anything about content/audience rather than
resolving (permanent pages, search, accounts/billing, email alerts, the
transcription crawler) grows in a **separate app** ("the Archive"), not
this resolver — see `BACKLOG_DONE.md` for the full reasoning. The
resolver/Archive seam is `get_cached_resolution`/`log_resolution` in
`app/db/crud.py` plus `archive_client.lookup()`/`.push()`.

### `[IMPROVEMENT-ROUND]` A general-purpose "is this a real government page" confidence scorer (added 2026-09-02)

- **Issue**: enumeration work keeps needing the same judgment call —
  given a candidate page (a domain-guess hit, a search result, a page
  that embeds a third-party widget like StreamText/Wordly), is it
  actually a real government page for the jurisdiction in question? Right
  now this is done ad hoc every time: a weak keyword/name-match script
  (real false-positive rate confirmed 2026-09-01 — see
  `~/Documents/rtr-business/research/ENUMERATION_METHODS.md`'s
  StreamText-candidate write-up, where both a government-keyword filter
  and a place-name substring matcher produced real, meaningful false
  positives — "Cement town, OK" matching inside "Commencement," "Council
  city, ID" matching inside "Council_Awards"), or a full agent doing a
  live web search and reasoning per candidate (real, but expensive —
  ~195K tokens for 30 candidates that same night, meaning a shortcut here
  has real leverage across every future sweep, not just one).
- **Impact**: every discovery method in this file inherits this same gap
  — `find_gov_domains.py`'s weak anti-false-positive check (does the
  jurisdiction's bare name appear on the page — already known to produce
  real false positives like state-portal collisions and tribal-nation
  name collisions, see §57), any future StreamText/Wordly-style
  third-party-widget sweep, and any human/agent reviewing a domain-guess
  batch all re-derive "does this look like a real government page" from
  scratch every time, at whatever cost that particular method's own
  verification step happens to use.
- **Next action**: build a standalone script that takes a URL (or fetched
  HTML) and returns a confidence score that it's a real government page
  — combining cheap, real signals already used piecemeal elsewhere in
  this project: TLD (`.gov`/`.us` scores higher than `.com`/`.org`),
  presence of the target jurisdiction's own bare name in the page text
  (the existing weak check, but as one signal among several rather than
  the sole gate), governance-context keywords in the page's own visible
  text (council/commission/board/agenda/minutes — the same 5-query
  vocabulary already proven in the TelVue/Cablecast/Vimeo dorking
  passes), known CMS/platform fingerprints (CivicPlus/CivicEngage
  markers, Granicus, etc.), and possibly a check against the state-portal/
  tribal-nation false-positive categories already catalogued in §57. Not
  meant to replace a real adapter resolve for final confirmation — meant
  to replace the *first-pass* triage step that currently costs either a
  fragile regex or a full agent turn.
- **Constraint**: needs real calibration against known-good and
  known-bad examples before being trusted (this project's own "never
  build from assumption" rule) — the §57 false-positive catalogue and the
  StreamText candidate results
  (`coverage_gap_2026-09-01/streamtext_candidates_RESULTS.csv`) are a
  ready-made labeled set to start from (both real hits and real
  ambiguous/not-found cases already exist there).
- **History**: proposed during a long enumeration session, 2026-09-01/02,
  after two consecutive automated candidate-filtering attempts (keyword
  match, then place-name match) both produced real, documented false
  positives on the same night. Not yet built.

### `[HUMAN]` YouTube captions via YouTube's official API, not InnerTube — investigate (added 2026-09-02)

- **Issue**: every YouTube caption path in this repo (`app/platforms/youtube.py`
  via `yt-dlp`, `scripts/fetch_youtube_transcripts.py` via `timedtext` /
  `youtube-transcript-api`) uses YouTube's *internal* player endpoints
  (InnerTube), which is why cloud IPs are refused and the daily fetch runs
  from Ryan's Mac. None of it is the official YouTube Data API v3.
- **Why it matters**: the data-product work (`rtr-business/data-product/`)
  excludes every YouTube-sourced transcript from anything sold, because the
  honest provenance sentence is "yt-dlp from a residential IP," not "the
  government's portal via its public API." ~455 proven tenants (incl. ~203
  CivicPlus) delegate to YouTube, so this exclusion roughly halves the
  sellable roster.
- **Decision wanted**: Ryan wants captions drawn through YouTube's official
  API. Open question to settle before any build: the Data API v3's
  `captions.download` is documented as requiring OAuth authorization from the
  video's *owner* (the government's channel), while `captions.list` only
  enumerates tracks. Determine (a) whether any official, ToS-compliant path
  exists for third-party captions with an API key alone, (b) if not, whether a
  per-government authorization (channel owner grants access) or a Public
  Records Act request for caption files is the workable route for the fixed
  roster, and (c) what quota/cost that implies. Report findings here; do not
  change the current InnerTube path in the meantime.
- Related: `rtr-business/data-product/RESEARCH_2026-09-01.md` (legal read,
  2026-09-02 addendum) and `BRIEF_fresh_transcript_feed.md` (YouTube
  exclusion rule).

### `[IMPROVEMENT-ROUND]` `[BIG]` Agenda text as a first-class, **versioned** asset — model, resolver, every adapter, and display

- **Issue**: agendas have no first-class text representation. `MeetingPage`
  has no agenda text field — `agenda_items` is video-timestamped chapter
  markers, not agenda text, and `agenda_link`
  ([archive/db/models.py:83](archive/db/models.py:83)) is a bare URL that's
  never fetched. A small, non-versioned slice already shipped 2026-08-31
  (PR #640): CivicPlus and CivicClerk now set a real `agenda_link`/
  `packet_link` at resolve time from data they already fetch — no nightly
  sweep, no versioning, no diffing, per Ryan's explicit call. Everything
  else below (the versioned model, fetch-and-extract across ~23 adapters,
  display/search) is still open.
- **Impact**: agenda text isn't stored, searchable, versioned, or diffable
  across the ~23 adapters that surface `agenda_link` at best today. It also
  blocks the `rtr-upcoming` integration: that sister repo resolves agendas
  across all 108 Bay Area jurisdictions but deliberately has no accounts,
  saved searches, or email alerts of its own, while this repo has all four
  — the ingest gate at [app/main.py:744](app/main.py:744) already accepts a
  video-less page on `agenda_link` alone, so agenda **text** is the one
  thing it can't yet carry.
- **Next action**: get Ryan's call on scope/sequencing — see
  `AGENDA_TEXT_BIG_VERSION_BRIEF.md` for the proposed step order (versioned
  model + migration first, one shared extraction path second tested against
  2-3 real documents, per-adapter rollout third cheapest-first, display/
  diff/search last) and the three options put to him (start at step 1 only;
  start at steps 1-2 together; hold entirely for the `rtr-upcoming`
  forcing function). If greenlit, start with the versioned child table
  (mirrors `TranscriptVersion`'s content-hash-dedupe shape — agendas get
  amended, transcripts don't).
- **Constraint**: this is a port of a working reference implementation
  (`rtr-upcoming`, `app/agenda_text.py` + `app/agenda_diff.py` +
  `UPCOMING_AGENDAS_FIELD_GUIDE.md`), not a from-scratch design. Read
  `docs/investigations/agenda_text_versioned_asset.md` in full before
  touching piece 2 (extraction) or piece 3 (display/search) — it holds a
  trap list where skipping any single item cost a full day when first hit
  in that repo.
- **History**: not started (beyond PR #640, see `BACKLOG_DONE.md`). Full
  design reasoning and trap list:
  `docs/investigations/agenda_text_versioned_asset.md`. Sequencing options:
  `AGENDA_TEXT_BIG_VERSION_BRIEF.md`.

### `[IMPROVEMENT-ROUND]` `[BIG]` App-wide audit — see [AUDIT_BRIEF.md](AUDIT_BRIEF.md)

- **Issue**: a scoped industry-best-practices audit (user feedback,
  discoverability, docs hygiene, legal/compliance, financial/resource
  management, accessibility) was handed off 2026-08-14; two areas (data
  durability, security scanning) closed 2026-08-21, the rest is still open.
- **Impact**: the still-open areas represent unassessed risk or process gaps
  in those categories until each is executed or explicitly declined.
- **Next action**: work through `AUDIT_BRIEF.md`'s remaining per-area items.
  Items already executed but not yet human-confirmed are tracked under
  **Needs a human** above, not here.
- **History**: `AUDIT_EXECUTION_BRIEF.md` and `BACKLOG_DONE.md` (the
  already-executed half of the audit, including the two closed areas).

### Product direction & open strategic questions

- **`[IMPROVEMENT-ROUND]` `[BIG]` "Feed cities" — should this app ever synthesize coverage for jurisdictions that publish nothing?**
  - **Issue**: open strategic question — whether the app should ever
    synthesize coverage for jurisdictions with no published meeting data at
    all.
  - **Impact**: undecided; determines how far coverage expansion can go
    beyond jurisdictions that already publish something.
  - **Next action**: read [FEED_CITIES.md](FEED_CITIES.md) for the full
    reasoning and the open questions it turns on. Not a plan and not
    scheduled — needs Ryan's call before it becomes one.
  - **History**: [FEED_CITIES.md](FEED_CITIES.md).

### `[IMPROVEMENT-ROUND]` `[BIG]` Accounts + token billing, phases 2-6 — see [ACCOUNTS_PLAN.md](ACCOUNTS_PLAN.md)

- **Issue**: phase 1 (Clerk sign-in, saved meetings/searches) shipped
  2026-08-11 and is live. Phases 2-6 (proposed polymorphic `Note` data
  model, token billing, advocate/organizer-and-institutional business
  framing) are proposed but not built.
- **Impact**: nothing broken — this is forward roadmap, gated on Ryan's
  call on open questions before phase 2 starts.
- **Next action**: read `ACCOUNTS_PLAN.md` for the full 6-phase sequence,
  the proposed data model, and the open questions needing a decision.
- **History**: `README.md` (shipped phase-1 architecture), `BACKLOG_DONE.md`
  (phase-1 build history), `ACCOUNTS_PLAN.md` (phases 2-6 plan).

### Growth, audience & discoverability

- **`[IMPROVEMENT-ROUND]` Zero-signal jurisdiction rows are the real remaining coverage frontier, but need a different kind of work than anything tried so far.**
  - **Issue**: ~21,331 rows in `jurisdiction_coverage.csv` have neither a
    meeting URL nor even a domain — only city/state/population — so every
    method that's worked on this project so far (known-gap-list checks,
    outbound-link scanning, `detect_platform()` against a row's own URL)
    has nothing to start from.
  - **Impact**: a 40-domain sample of the smaller adjacent tier (rows with
    a domain but no meeting URL) already showed this shape of data degrades
    fast, so extending the same technique further down to zero-signal rows
    isn't worth it.
  - **Next action**: treat as a "find the government's own website first"
    research task at real scale — structurally a different kind of project
    from URL-shape scanning, not just another platform to enumerate.
  - **History**: moved out of Dormant 2026-08-30; found 2026-08-28 closing
    out the CSV-mining phase — see `BACKLOG_DONE.md`'s "no-video-signal
    tier" entry and `~/Documents/rtr-business/research/
    ENUMERATION_METHODS.md` §21.

- **`[IMPROVEMENT-ROUND]` Proactive transcription crawler — grow the corpus without waiting on someone to paste a URL.**
  - **Issue**: the corpus only grows today when someone happens to paste a
    URL; there's no proactive discovery/crawl of new meetings or
    jurisdictions.
  - **Impact**: cross-archive search on `/meetings` is already live, and its
    value is directly proportional to corpus size — this reframes the
    crawler from "nice to have" to "the thing that makes the flagship
    search feature actually good."
  - **Next action**: revisit once reliability work settles down. No new
    dependencies needed — this is a re-prioritization question, not a new
    build.
  - **Constraint**: re-prioritized 2026-08-09, then explicitly held back
    again 2026-08-10 ("not yet — keep prioritizing bugs/gaps").
  - **History**: see the two narrower, related entries below (YouTube
    Atom-feed polling; `CORPUS_EXPANSION_PLAN.md`) for scoped-down/adjacent
    versions of this same question.

- **`[IMPROVEMENT-ROUND]` YouTube Atom-feed polling as a narrower, lower-risk re-check trigger — separate from the general crawler question above.**
  - **Issue**: a transcript-less page whose city just posted a new video
    today only gets re-checked on the existing passive hourly cadence
    (`ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT`, `app/main.py`) or a human visit
    — nothing proactively triggers a re-check when the city actually posts.
  - **Impact**: scoped to the 4 cities `youtube_channel.py` already curates
    a `netloc→channel_id` map for (Phoenix, Philadelphia, Baltimore,
    Albuquerque — cities whose Legistar page never gets a video link at
    all). Their Atom feed (`youtube.com/feeds/videos.xml?channel_id={id}`)
    is a plain unauthenticated GET — no yt-dlp, no bot-check surface — and
    a live fetch against Phoenix's real feed confirmed real `<published>`
    timestamps on every recent upload.
  - **Next action**: build a small scheduled script (no live worker exists
    in this app, deliberately) that polls those 4 feeds periodically and,
    on a new video whose date matches a known meeting page for that city,
    triggers a re-resolve of *that page's own original URL* (not the
    YouTube URL) — so the existing adapter chain (Legistar → city-YouTube-
    channel fallback) does the actual match/attach, the same way a manual
    visit already does, just sooner.
  - **Constraint**: doesn't fix the underlying attach — caption fetch still
    goes through yt-dlp at resolve time, the same call hitting the live,
    unresolved Render YouTube IP block (184 real jurisdictions on
    `platform="YouTube"` ride through it — see that entry under
    **Reliability, ops & cost** and `docs/investigations/
    youtube_429_block.md`). Deliberately scoped to only these 4 curated
    cities — broadening past the existing last-resort fallback list is a
    separate, real cost (see `youtube_channel.py`'s own docstring).
  - **History**: not built. Addendum written 2026-08-26. Full design
    reasoning (why route the re-resolve through the existing page URL
    rather than writing Atom data directly onto the page; why no
    Upcoming→Past state-switch needs to be built) preserved in this
    compaction's done-additions file, pending a real `BACKLOG_DONE.md` or
    `docs/investigations/` entry once this is built.

- **[IMPROVEMENT-ROUND] Batch lookup — accept multiple meeting URLs at
  once instead of one at a time.**
  - **Issue**: no way to submit multiple meeting URLs in one request —
    only one at a time today.
  - **Impact**: the main friction point for a journalist working many
    jurisdictions at once.
  - **Next action**: design the batch endpoint together with its
    abuse-prevention plan, not after — a batch endpoint is a natural
    abuse vector, and the transcription worker's real per-job compute
    cost means unmetered batch access could get expensive fast.
  - **Constraint**: worth sequencing after accounts even though it
    doesn't strictly require them, since rate-limiting or
    account-gating is the natural way to bound abuse.
  - **History**: none yet — proposal, not investigated.

- **[IMPROVEMENT-ROUND] Whether the resolver's existing `GET /admin/log`
  is actually used by (or sufficient for) the real jurisdiction-
  enumeration tooling that lives outside this repo is unconfirmed.**
  - **Issue**: the real ask behind this entry is a list of jurisdictions
    not yet ingested at all, to drive the (mostly CLI-driven, not
    website-driven) enumeration effort — and it's unconfirmed whether
    the mechanism that could answer that is already wired up.
  - **Impact**: enumeration tooling may be duplicating, or missing, a
    mechanism that already exists in this repo.
  - **Next action**: from a session with access to `~/Documents/
    rtr-business` (not a GitHub repo — confirmed unreachable from this
    session via `list_repos`), confirm whether any real enumeration
    script (`find_vendor_hosts.py`-style scripts, CDX passes) already
    calls `GET /admin/log`/`MeetingResolution`; if yes, document its real
    shape in `ENUMERATION_METHODS.md`; if no, wire it in — or widen
    `/admin/log` with a `?status=resolve_failed`-style filter first,
    given its 1000-row cap.
  - **Constraint**: needs a session with access to `~/Documents/
    rtr-business` to close out — can't finish verifying from a session
    scoped to this repo alone.
  - **History**: confirmed live in code 2026-08-31 that `GET /admin/log`
    (the resolver's own admin-token-gated endpoint, `app/main.py`, not an
    Archive route) already returns `url`/`platform`/`outcome`/
    `created_at` per logged resolve attempt (`?format=csv` supported),
    with `outcome` real-classified via `app/db/outcomes.py`'s
    `classify_outcome()` into `resolve_failed`/`calendar_page`/
    `unsupported_platform`/`archive_redirect` buckets — capped at 1000
    most-recent rows (`crud.list_resolutions()`), no failure-only or
    date-range filter yet. The companion half of this split — an
    Archive-side data-quality tool, already done, no public page needed —
    is in `BACKLOG_DONE.md` (see additions file).

- **[IMPROVEMENT-ROUND] `[BIG]` Video highlight clips + algorithmic
  feed.**
  - **Issue**: proposal — video highlight clips plus an algorithmic feed.
  - **Impact**: distant future; no current user-facing gap.
  - **Next action**: none — not started.
  - **Constraint**: this app's "never host video, only embed" principle
    directly conflicts with hosting/serving clip segments — that tension
    needs resolving before any real design work.
  - **History**: none.

- **[IMPROVEMENT-ROUND] A generated, branded share card would beat a raw
  video frame (WO-28 residual).**
  - **Issue**: the extracted video frame used for sharing carries no
    jurisdiction/title/logo branding.
  - **Impact**: a reader sees an anonymous council dais; weaker share
    unit than a composited card. Also blocks `CLAUDE_BACKLOG.md`'s
    "Quote-clip sharing" idea, which needs the same composited-card
    building block.
  - **Next action**: build a composited card (frame + overlay text +
    logo), which needs an image-compositing dependency not currently in
    the repo (Pillow, or ffmpeg's `drawtext`).
  - **Constraint**: font rendering/wrapping is a real design problem to
    solve as part of this. Storage/route/cache headers/targeting all
    carry over unchanged from the current frame-extraction approach.
  - **History**: none — deliberately not built yet.

- **[IMPROVEMENT-ROUND] PDF agenda text-extraction for a searchable
  preview.**
  - **Issue**: agenda PDFs have no extracted, searchable text — only the
    raw file is viewable.
  - **Impact**: no searchable preview of agenda content; low value until
    built.
  - **Next action**: add `pypdf`/`pdfplumber` (neither currently in
    `requirements.txt`) plus a new storage column to hold extracted text.
  - **Constraint**: a bigger, separate ask than the inline-viewer half
    that already shipped — not investigated further.
  - **History**: the cheap half — a plain `<iframe>` next to
    `agenda_link` rendering the PDF inline — shipped 2026-08-31, zero
    backend change. See `BACKLOG_DONE.md` addition.

- **[IMPROVEMENT-ROUND] Design reference for the cassette-reel button
  animation, flagged 2026-08-16.**
  - **Issue**: proposal — improve the cassette-reel button animation,
    using Sentry's "Install GitHub App" onboarding-page button animation
    ([how-to-adu.sentry.io/onboarding/scm-connect/](https://how-to-adu.sentry.io/onboarding/scm-connect/),
    a private page needing Ryan's session) as a design reference.
  - **Impact**: n/a — design exploration, not a bug.
  - **Next action**: visit the live reference URL and actually watch the
    motion. Only its static structure is confirmed so far, from a
    devtools screenshot: real `::before`/`::after` pseudo-elements
    suggesting a layered sweep/fill/underline effect.
  - **Constraint**: none.
  - **History**: current implementation is
    [archive/static/style.css:138-155](archive/static/style.css:138) — an
    inline-SVG spin on hover/press plus a slower ambient variant during a
    real fetch, used on the homepage submit button and "Copy link to
    current time." `cassette-btn-pop` (a "lift up and glow" cue at
    [style.css:164-171](archive/static/style.css:164)) is the closest
    existing precedent for something more elaborate, if the reference
    turns out to be a pop/lift effect rather than sweep/fill once
    actually watched.

### Search & metadata quality

- **[IMPROVEMENT-ROUND] Tune `_VOCAB_SIMILARITY_THRESHOLD`
  (`archive/db/crud.py`, currently 0.3, pg_trgm's default) against real
  production fuzzy-search query logs.**
  - **Issue**: the threshold has never been tuned against real production
    fuzzy-search query logs.
  - **Impact**: low priority, not a correctness issue — used purely as a
    candidate generator, and every candidate is re-verified against an
    exact Levenshtein check, so a mistuned threshold only costs
    extra/missed candidate checks, never a wrong final answer.
  - **Next action**: revisit once there's a real corpus of production
    fuzzy queries to measure against.
  - **Constraint**: none.
  - **History**: none — not yet investigated.

- **[IMPROVEMENT-ROUND] Audit per-adapter coverage of `meeting_body`,
  then be strategic about extending it.**
  - **Issue**: `meeting_body` is populated by only one generic heuristic
    (`finalize_jurisdiction()`'s `_split_entity_prefix()` on a leading
    "`<Entity> of <Jurisdiction>`" shape), which the code's own comments
    already flag as a minority case, not adapter-specific — real
    per-adapter coverage is unaudited.
  - **Impact**: low priority, no urgency. `meeting_pages.meeting_body`
    (landed 2026-08-15) is genuinely live, not a dead column (confirmed
    end-to-end for Santa Clara Housing Authority, rendered on
    `/m/{slug}`, `/meetings`, and My Saved Items) — but how much of the
    real archived corpus it actually covers is unknown.
  - **Next action**: using the ~650 already-archived meetings as the test
    set (same dry-run-against-real-data approach as the
    census-baseline-validation work), audit per adapter how often a real
    archived meeting should have a `meeting_body` but doesn't; also check
    whether Granicus's independent `_fetch_channel_info()` RSS-channel-
    title parse (a separate, adapter-native body-shaped value) ever
    disagrees with the generic split's result.
  - **Constraint**: be strategic — forcing the split where it doesn't
    belong risks the same "loses information without a bleed signal"
    mistake already called out when this field was designed.
  - **History**: none — not yet investigated.

- **[IMPROVEMENT-ROUND] Once `meeting_body` has real, strategic coverage,
  add it as a `/meetings` search filter.**
  - **Issue**: proposal — add `meeting_body` as a `/meetings` search
    filter/facet.
  - **Impact**: today's search matches title/jurisdiction/agenda/
    transcript text but has no `meeting_body`-aware filter or facet.
  - **Next action**: sequence after the coverage audit above.
  - **Constraint**: low value until coverage is broad enough to actually
    narrow a real result set.
  - **History**: none.

- **[IMPROVEMENT-ROUND] Transcript version picker: real option labels
  still open.**
  - **Issue**: the picker's option labels (`meeting_page.html`:
    `{{ v.language|language_name }} ({{ v.source|source_label }})`)
    distinguish versions only by language and provenance — two versions
    sharing both a language and a source still render identically, even
    after `source="deduped"` added one more axis.
  - **Impact**: a reader can't always tell two listed versions apart
    before picking one.
  - **Next action**: add a date to each label — the cheapest real fix,
    since `TranscriptVersion` already carries a timestamp and it needs no
    schema change; a free-text label column would read better but needs
    a migration.
  - **Constraint**: Ryan's call 2026-08-22 — UI is "fine enough" for now,
    ship transcripts first; not urgent.
  - **History**: split out of the `source="deduped"` work. The analytics
    half (`transcript_version_change`/`_available`/`_viewed` events,
    including the `label_ambiguous` param this entry called for) shipped
    2026-08-31 — see `BACKLOG_DONE.md` addition.

- **[IMPROVEMENT-ROUND] A demoted `TranscriptVersion`'s text is still
  invisible to external search.**
  - **Issue**: external search engines only ever see the canonical
    `/m/{slug}` URL's single active-version HTML.
  - **Impact**: a demoted version's transcript text is invisible to
    Google (and other external search) — never indexed.
  - **Next action**: render every version's segments into the DOM with
    JS-toggled visibility (Google's documented-correct tabbed-content
    pattern), which needs per-version-scoped deep-link segment IDs and a
    real page-size check first (Dublin's real transcript alone is over a
    megabyte of JSON).
  - **Constraint**: not prioritized — revisit only if the SEO angle
    specifically becomes worth it.
  - **History**: the in-app search half (this site's own `/meetings`
    search already matches every version) and the UX half (version
    picker, shipped 2026-08-12) are both in `BACKLOG_DONE.md`.

### Transcription quality & cost

- **[IMPROVEMENT-ROUND] Hallucinated-transcript detection doesn't catch
  semantic-nonsense hallucination (coherent-looking but false text).**
  - **Issue**: the detector's three structural signals (repetition-run
    ratio, long character runs, non-Latin-script ratio) deliberately
    don't try to catch semantic-nonsense hallucination.
  - **Impact**: confirmed by a real quoted example that the detector
    correctly does not flag — this failure mode is real, not
    hypothetical.
  - **Next action**: design a real LM-judge pass to catch it — a
    cost/latency tradeoff not yet designed. Not waiting on a real
    example; one already exists.
  - **Constraint**: none stated.
  - **History**: moved out of Dormant 2026-08-30. The other half of this
    original entry — already-live exposure — was audited for real
    2026-08-17 (see the "Needs a human" section).

- **[IMPROVEMENT-ROUND] Per-meeting `initial_prompt` seeded with real
  council-member names, from the agenda — user idea, 2026-08-11.**
  - **Issue**: today's `MEETING_VOCABULARY_PROMPT` is one fixed generic
    constant reused for every job — real people's names aren't in it.
  - **Impact**: names (especially non-Anglicized or uncommon ones,
    exactly where Whisper is most likely to misspell) go uncorrected.
  - **Next action**: three real gaps to close before building. (1)
    Extraction: nothing in this codebase currently extracts attendee/
    council-member names anywhere (grepped every adapter, no hits) —
    `agenda_items` holds topic text, not a roster, so this is new work,
    and whether a reliable roster is even available per-platform is
    unconfirmed. (2) Plumbing: `FasterWhisperEngine` is constructed once
    at worker startup and reused across every job with no per-job
    context passed in, so `transcribe_chunk()`'s signature needs to
    accept extra terms, threaded from wherever the worker's job loop can
    look up a job's `meeting_page_id`. (3) Validation: run a real
    before/after check against a meeting with known misspelled names
    before assuming this helps.
  - **Constraint**: Whisper's `initial_prompt` is a soft bias with a real
    length ceiling — a growing per-meeting names list needs care not to
    dilute or overflow it.
  - **History**: user idea, 2026-08-11. Not yet built.

- **[IMPROVEMENT-ROUND] A signed-out visitor who hits the
  transcription-request rate limit still isn't prompted to sign in.**
  - **Issue**: a signed-out visitor who hits the 5/hour transcription
    rate limit is just told to wait, with no path to the sign-in flow
    that would exempt them.
  - **Impact**: signed-out visitors who would benefit from signing in
    (signed-in users are now exempt, see History) have no prompt to do
    so at the point they hit the limit.
  - **Next action**: add a plain link to the dedicated `/sign-in` page at
    this UI spot.
  - **Constraint**: this exact UI spot already tried an inline sign-in
    shortcut (a Clerk modal button) and removed it entirely after three
    rounds of Clerk's redirect options proved unreliable live — read the
    full saga in `BACKLOG_DONE.md`'s accounts phase-1 entry before
    reaching for the modal again. A plain link to `/sign-in` is probably
    the safer default given that history.
  - **History**: the rate limit itself no longer applies to signed-in
    users, fixed 2026-08-31 — both `@limiter.limit("5/hour")` decorators
    (`app/main.py`'s `transcription_check_feasibility`/
    `transcription_submit`) now carry `exempt_when=lambda request:
    bool(get_clerk_user_id(request))`, confirmed live that slowapi
    0.1.10 genuinely supports this kwarg. The copy rewrite was already
    fixed 2026-08-16. `transcription_submit`'s separate
    `clerk_verified=bool(get_clerk_user_id(request))` plumbing
    (2026-08-22) still only skips a newsletter-confirmation step,
    unrelated to this rate limit. See `BACKLOG_DONE.md` addition.

### Email, ops tooling & internal reporting

- **[IMPROVEMENT-ROUND] Lifecycle-triggered transactional emails (Resend)
  — built 2026-08-11, not yet live-verified.**
  - **Issue**: five of six planned emails (Thanks, Welcome, Goodbye for
    now, Your transcript's ready, We couldn't cook this one) are built
    but covered by monkeypatched unit tests only — not yet live-verified
    against a real Resend account.
  - **Impact**: real send behavior, and whether Clerk's `user.created`
    webhook payload includes `first_name` for every signup method (the
    personalized greeting's precondition), are both unconfirmed live.
  - **Next action**: verify against a real Resend account, and confirm
    live whether the personalized-name path actually fires (the "Hi
    there," fallback degrades gracefully either way, but hasn't been
    observed firing for real).
  - **Constraint**: the resolver has its own `_resend_send()` + branded
    template helpers, deliberately duplicated rather than proxied
    through the Archive — needs its own `RESEND_FROM_ADDRESS`/
    `RESEND_REPLY_TO_ADDRESS` set in Render (added to `render.yaml` with
    `sync: false` — user still needs to set the real values on staging
    and prod).
  - **History**: built 2026-08-11 from `rtr-business`'s approved
    copy/voice, reusing/extending existing Resend infrastructure.

- **[IMPROVEMENT-ROUND] Consolidate every user-facing email address on
  `ally@redtaperecordings.com` — three configs still don't.**
  - **Issue**: `RESEND_REPLY_TO_ADDRESS` (currently
    `ryan@redtaperecordings.com`), `DAILY_REPORT_EMAIL_TO`, and
    `YOUTUBE_FETCH_REPORT_EMAIL` (the latter two default to
    `ryan@how-to-adu.com`) still don't point at the consolidated
    `ally@redtaperecordings.com` address.
  - **Impact**: transactional-email replies/failure CCs, and
    operator-facing ops digests, still land at the old addresses.
  - **Next action**: repoint all three to `ally@redtaperecordings.com` —
    the "which Ryan address" question this entry originally left pending
    for the latter two was resolved 2026-08-22 (see the operator-report
    entry below), settling all three at once.
  - **Constraint**: none remaining.
  - **History**: user request 2026-08-12, after `ally@`/
    `ryan@redtaperecordings.com` forwarding was set up. The two static
    `mailto:` Contact links and the `ryan@how-to-adu.com` address on
    `about.html` were fixed 2026-08-16 (see `BACKLOG_DONE.md` addition).
    Form submissions turned up nothing else to repoint
    (`/api/report-problem` only writes a DB row; the newsletter form
    posts to a Resend audience, not an inbox).

- **[IMPROVEMENT-ROUND] Recurring operator email report every 6 hours,
  requested 2026-08-16 — partially superseded by the shipped daily
  report, real gaps remain.**
  - **Issue**: proposal — a 6-hourly operator email report to the
    consolidated ops address, with metrics the existing daily report
    doesn't cover.
  - **Impact**: partially superseded 2026-08-21 by a real, shipped daily
    worker report (`GET /internal/send-worker-daily-report`, full build
    in `BACKLOG_DONE.md`) that covers overlapping ground (chunks/jobs
    completed in 24h, segments added, active jobs, remaining chunks,
    no-transcript backlog, tier-3-queue-remaining) — but cadence (daily
    vs. 6-hourly) and two metrics (an explicit "failed in last 48h"
    count, a "total meetings on site" count) are still genuinely
    missing.
  - **Next action**: build it as a sibling of `app/reporting.py` inside
    `archive/` (its own module, admin-token-gated endpoint, 6-hour cron
    workflow instead of daily), reusing `archive/utils/email.py`'s
    existing single-recipient Resend-send helper. Not started — a scoped
    feature request only.
  - **Constraint**: two real design questions to settle first. (1)
    `TranscriptionJob` has only `created_at`, no `completed_at`/
    `failed_at`, so "failed/succeeded in the last 48h" can only be
    approximated by job-creation time, not completion time — decide
    whether that's acceptable or whether it needs a new timestamp column
    via a real Alembic migration. (2) For "meetings with/without a
    transcript," reuse the existing quality-aware
    `_has_good_transcript()` check, not a naive presence check — this
    repo already fixed exactly that presence-vs-quality bug once. Two
    operational gotchas when wiring the recipient: it's set per-service
    in Render, so it must be changed on both `rtr-transcription-worker`
    and `rtr-transcription-worker-2` (which differ in exactly that
    variable by design — see `render.yaml`'s comment on the second
    block) without collapsing that distinction; and
    `ryan@ally.redtaperecordings.com` is the Resend *sending* subdomain,
    not the recipient address — nearly identical in a config diff,
    confirm `ally@redtaperecordings.com` actually receives mail before
    switching anything over.
  - **History**: the "which Ryan address" question was resolved
    2026-08-22 — `ally@redtaperecordings.com` — and all operator/ops
    reporting (this report, `AUTO_TRANSCRIPTION_REQUESTER_EMAIL`,
    `DAILY_REPORT_EMAIL_TO`'s prior `ryan@how-to-adu.com` default)
    consolidates there. See `BACKLOG_DONE.md` for both that resolution
    and the daily worker report's full build.
## Parked deliberately — allowed back `[PARK]`

Parked by the user during the jurisdiction/title extraction planning
conversation. Not rejected — explicitly allowed to return.

- **[IMPROVEMENT-ROUND] School-district / special-entity jurisdiction lookup.**
  - **Issue**: school districts don't conform to city/county boundaries,
    so the Census places/counties tables structurally can't cover them.
  - **Impact**: ~10 real district/board-of-education pages (surfaced in
    the 2026-08-15 Swagit batch) have no jurisdiction lookup path today.
  - **Next action**: when this comes back, use the Census Gazetteer
    program's school-district files (name + state) with the same
    build-script/lookup mechanism already used for cities/counties.

- **[PARK] MPO / transit-authority / utility-district name table.**
  - **Issue**: no national authoritative table exists for these entity
    types.
  - **Impact**: these stay validation-exempt indefinitely — "not in
    table" must stay a keep-and-flag outcome, never a rejection.
  - **Next action**: none planned; real examples on file if revisited —
    VIA Metropolitan Transit, Broward MPO, ERCOT, Port of Galveston,
    Travis Central Appraisal District.

- **[PARK] `[BIG]` "Request Transcript from Audio" doesn't work for YouTube-hosted meetings.**
  - **Issue**: `app/main.py`'s `check-feasibility` route runs `ffprobe`
    on `result.video_url` — for YouTube that's an HTML iframe-embed
    *page*, never a real media file, so `ffprobe` can never read it.
    Confirmed live 2026-08-10.
  - **Impact**: real fix needs yt-dlp's own stream extraction, the same
    pipeline already confirmed blocked by YouTube's anti-bot check —
    building it without first solving that block would likely just trade
    one failure message for another.
  - **Next action**: none planned — cookies-based auth, a PO-token-
    provider plugin, and a proxy were all surfaced as real options and
    deliberately not attempted (cost/maintenance/risk not yet evaluated).
  - **History**: coupled to the still-open YouTube IP-block investigation,
    `docs/investigations/youtube_429_block.md`.
