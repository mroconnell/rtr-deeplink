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

Standing decisions — do NOT re-raise  (4)
  `jurisdiction_confidence IS NULL` is deliberately excluded from…
  Never run an unbounded scan or bulk workload against the production…
  Prefer a generated/computed column over "add a column, then backfill…
  Never attempt to auto-solve a Cloudflare "Verify you are human"…

Ship next — root cause known, fix settled `[JUST-DO-IT]`

Needs a human — dashboard, prod, or product call `[HUMAN]`  (4)
  Confirmations nobody has actually watched happen  (2)
    [HUMAN] `[LOGIN]` `[WAIT]` Measure whether the 2026-08-23 state/hub…
    [HUMAN] Decide the /meetings result link order from real click data,…
  Production actions only Ryan should take  (1)
    [HUMAN] Click Validate Fix in Search Console for the reslug fix.
  Decisions about already-live content  (1)
    [JUST-DO-IT] `[BIG]` Repair the repetition-loop transcript-defect…

Open bugs — real, root cause not settled `[NEEDS-AUDIT]`  (54)
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
  Brookhaven NY's media host (`cpmedia.azureedge.net`) fails every…
  28 well-formed IQM2 queue rows point at retired tenants…
  Swagit multi-clip meetings: local script still needs the cloud…
  High Plains Water District (Granicus) transcribed to zero usable…
  Adapter, tenant & jurisdiction-extraction odds and ends `[LATER]`  (2)
    `[NEEDS-AUDIT]` `jurisdiction_enrich.validated_label_extract()` can…
    `[NEEDS-AUDIT]` `appalachian.cablecast.tv` (show/3841) is genuinely…
  ChampDS symptom B — instant 0.2s failures from the JSON API,…
  ~12 OnBase/Hyland-family pages still resolve with no video…
  Duration alone cannot separate a very short real meeting from an ad…
  Tucson, AZ's one archived page has no video (50-largest-cities audit)…
  Atlanta, GA's original ChampDS gap is unconfirmed (50-largest-cities…
  Omaha, NE has zero archived pages (50-largest-cities audit)…
  Virginia Beach, VA's OnBoardGOV SPA gap is real but less urgent than…
  Granicus's GovAccess CMS product is undetected and blocked by…
  Jurisdiction extraction & backfill  (10)
    `[NEEDS-AUDIT]` Derry NH has no known-jurisdictions entry.
    `[HUMAN]` Santa Clara's already-valid jurisdiction strings need a
    `[NEEDS-AUDIT]` Kansas City pair (`154`/`155`) has no single correct
    `[NEEDS-AUDIT]` Jurisdiction-bleed single-word-tail gap: Castle Rock
    `[NEEDS-AUDIT]` Bare "Pitt" jurisdiction value — likely not a bug.
    `[NEEDS-AUDIT]` Swagit still resolves special-purpose entities with a
    `[NEEDS-AUDIT]` Lloydminster (AB/SK border city) needs a product
    `[NEEDS-AUDIT]` Census-table baseline validation: mid-word truncation
    `[LATER]` Domain guesser state-name collision — fixed, 6 rows still
    `[LATER]` ~25 smaller consolidated city-county governments still need
  Adapter & platform gaps  (18)
    [JUST-DO-IT] TelVue CDX enumeration solved; ~127 tokens still…
    [NEEDS-AUDIT] Tarrant County TX (TechShare.AgendaManagement)…
    [NEEDS-AUDIT] Tarrant County TX (TechShare.AgendaManagement)…
    [NEEDS-AUDIT] Anchorage AK's original "bot-blocked YouTube…
    [NEEDS-AUDIT] Vimeo captions and Whisper-fallback audio are blocked…
    [NEEDS-AUDIT] Chicago ELMS's 473 real agenda items have no time…
    [NEEDS-AUDIT] ProudCity: Holyoke MA's YouTube 429 recovery status is…
    [NEEDS-AUDIT] ProudCity: four tenants remain unpushed (two…
    [JUST-DO-IT] City-YouTube-channel fallback: listings only reach ~400…
    [JUST-DO-IT] City-YouTube-channel fallback: duplicate-posted meetings…
    [LATER] `[EXAMPLE]` Town Hall Streams: transcript endpoint…
    [LATER] `[EXAMPLE]` SuiteOne Media: dead CDX leads and unconfirmed…
    [LATER] `[EXAMPLE]` Granicus's `captions.vtt` caps at exactly 36,000…
    [LATER] YouTube Whisper fallback for videos with no captions at all…
    [IMPROVEMENT-ROUND] Cablecast, TelVue, Swagit, and YouTube still…
    [NEEDS-AUDIT] ChampDS's VOD2 HLS case (majority of customers) has no…
    [NEEDS-AUDIT] Palm Beach County FL's JS-rendered SharePoint page…
    [LATER] `elpasotexas.gov/videos/` has no adapter of its own.

Reliability, ops & cost  (12)
  `[JUST-DO-IT]` Render *pipeline minutes* — build volume cut twice,…  (1)
    [LATER] Tighten the two transcription workers to their real import
  Media-source reliability  (3)
    `[NEEDS-AUDIT]` Some old/archived Granicus clips' `chunklist.m3u8`…
    `[NEEDS-AUDIT]` A single job still makes N consecutive pulls to the…
    `[NEEDS-AUDIT]` The 120s ffmpeg timeout is a flat value that doesn't…
  Transcription queue & workers  (4)
    [NEEDS-AUDIT] WO-57's claim heartbeat has no cap, and transcription
    [NEEDS-AUDIT] Backlog keeps shrinking — re-derived 2026-08-31.
    [LATER] `list_transcription_backlog_candidates()` still does a real
    [LATER] Second transcription worker's auto-generation TOCTOU race —
  Search Console, structured data & SEO plumbing  (3)
    [HUMAN] `[LOGIN]` `[WAIT]` "Reasons preventing pages from being
    [WAIT] `thumbnailUrl` "Videos" structured-data flag — fixed, only the
    [NEEDS-AUDIT] New "Missing field" flags — Videos `uploadDate`, Events
  `/coverage` as a QA surface  (1)
    [JUST-DO-IT] `/coverage`'s "Every place we've covered" table is a

Trust, safety & data quality  (9)
  `[LATER]` No blanket backfill can make pre-2026-08-21 `best_effort`…
  `[LATER]` `best_effort` is sticky — nothing at ingest distinguishes a…
  `[IMPROVEMENT-ROUND]` Low-trust queue rows have no repair workflow…
  `[IMPROVEMENT-ROUND]` A low-trust review doesn't expire when the page…
  `[LATER]` Mastodon auto-posting has made zero real posts
  `[IMPROVEMENT-ROUND]` Social auto-posting only fires on page…
  `[LATER]` Prompt injection isn't a live product risk today, but the…
  `[HUMAN]` `[BIG]` Nothing verifies a submitted URL is a genuine…
  `[NEEDS-AUDIT]` Chula Vista's stale garbled-marker survives its own…

Roadmap & strategy `[IMPROVEMENT-ROUND]`  (25)
  `[IMPROVEMENT-ROUND]` `[BIG]` Agenda text as a first-class,…
  `[IMPROVEMENT-ROUND]` `[BIG]` App-wide audit — see…
  Product direction & open strategic questions  (1)
    `[IMPROVEMENT-ROUND]` `[BIG]` "Feed cities" — should this app ever…
  `[IMPROVEMENT-ROUND]` `[BIG]` Accounts + token billing, phases 2-6 —…
  Growth, audience & discoverability  (10)
    `[IMPROVEMENT-ROUND]` Zero-signal jurisdiction rows are the real…
    `[IMPROVEMENT-ROUND]` Proactive transcription crawler — grow the…
    `[IMPROVEMENT-ROUND]` YouTube Atom-feed polling as a narrower,…
    `[IMPROVEMENT-ROUND]` Corpus expansion — discover additional meetings…
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

## Ship next — root cause known, fix settled `[JUST-DO-IT]`

Small, self-contained, no open design question. Jurisdiction-extraction
items that also qualify live under **Platform & jurisdiction coverage**
so that work reads together.


## Needs a human — dashboard, prod, or product call `[HUMAN]`

Nothing here is blocked on engineering. Most are one dashboard login or
one deliberate production action away from closing. Grouped by what kind
of human step they need.

### Confirmations nobody has actually watched happen

- **[HUMAN] `[LOGIN]` `[WAIT]` Measure whether the 2026-08-23 state/hub rebuild moved Google's indexing verdict.**
  - **Issue**: no Search Console data yet on whether the 2026-08-23
    `/state/*`/`/j/*` rebuild changed Google's indexing verdict.
  - **Impact**: can't tell if the rebuild worked, or tune these surfaces
    further, without this data.
  - **Next action**: pull a Search Console export at least a few weeks
    out from the 2026-08-23 rebuild date, and measure against the
    **3.6× (`/j/`) and 3.1× (`/state/`) over-representation figures** —
    not the raw non-indexed count, which moves with corpus growth and
    can't answer this on its own. Nothing to change in code meanwhile.
  - **Constraint**: read `STATE_HUB_PAGES.md` before touching `/state/*`
    or `/j/*` — the full reasoning, tried-and-rejected list with
    measurements, tuning table, and future-work ranking live there.
  - **History**: `BACKLOG_DONE.md` keeps the original investigation.
    Separate, still-open engineering residuals this rebuild left behind
    are filed under Open bugs, not blocked on this dashboard step.

- **[HUMAN] Decide the /meetings result link order from real click data, not from taste.**
  - **Issue**: the row's headline link now opens the matched segment
    and "Play from 0:00" below opens the whole meeting (Ryan's call,
    2026-08-24) — untested against real user behavior.
  - **Impact**: the current order could be wrong for how people actually
    use search results; no evidence behind the choice yet.
  - **Next action**: once there's enough traffic to be meaningful, read
    GA4's `search_result_click` event (`link_type`:
    `deep_link`/`meeting_page`, `result_position`) and keep or flip the
    order. Two confounds to weigh when reading it: the headline is a
    much bigger click target (partly just Fitts's law), and the
    home/state page featured cards deliberately did *not* get the same
    reversal, so they aren't a control group — different question.
  - **History**: the event has fired since 2026-08-24; its custom
    dimensions (`link_type`/`result_position`) were registered in GA4
    and verified end-to-end via a live test click on 2026-08-30 —
    measurement is confirmed wired correctly, just waiting on real
    traffic volume.

Left open across `AUDIT_EXECUTION_BRIEF.md`'s Phase 1 and Waves 1-6, all
code-complete and merged (full detail in `BACKLOG_DONE.md`'s "Reliability/
ops audit execution" entry). None blocks anything else; do whenever
convenient.

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

### Decisions about already-live content

- **[JUST-DO-IT] `[BIG]` Repair the repetition-loop transcript-defect population in stored segments — blocked on deploy, not code.**
  - **Issue**: `scripts/repair_repetition_loops.py` (~74 candidates) is
    built and CI-tested but has never completed a run against
    production.
  - **Impact**: ~74 pages carry repetition-loop transcript defects that
    can be repaired in place instead of needing a full re-transcribe.
  - **Next action**: once the WO-87 fix (merged to `main` 2026-08-31,
    not yet deployed — `asyncio.to_thread()` plus
    `CANDIDATE_PAGE_SIZE` dropped 500 → 25) is deployed, run
    `scripts/repair_repetition_loops.py --dry-run`, review the report,
    then apply. Still open after that: (1) trim the 3 remaining
    hallucinated-default transcripts that aren't Kitchener (e.g.
    Sacramento — Kitchener itself was re-transcribed 2026-08-30); (2)
    put anything the repair can't fix on the re-transcription report —
    not started; (3) extend the repair to the local-batch population by
    scanning stored segments instead of job records, since
    `scripts/transcribe_backlog_locally.py` never touches
    `transcription_jobs` — not started.
  - **Constraint**: don't run this before the WO-87 deploy lands — its
    predecessor (`limit=500`) triggered a full-service outage,
    `detect_hallucination_warnings()` blocking the worker's event loop
    for 128s+ and failing Render's health check.
  - **History**: the seam-duplication half of this same defect
    population is already done (111/111 pages repaired live). Full bug
    history — the unbounded-`limit` query fix and the WO-87 event-loop
    fix — is in `BACKLOG_DONE.md`, WO-84 and WO-87.

## Open bugs — real, root cause not settled `[NEEDS-AUDIT]`

Reproduced against real data, but the fix is a genuine open question.
Jurisdiction-extraction bugs live under **Platform & jurisdiction
coverage** instead.

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
    bug.

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
    Albuquerque is also still unchecked — its Legistar calendar page's
    current HTML doesn't match the link-scraping shape used for the other
    three cities.
  - **Next action**: needs a second same-shape ambiguous-match case before
    a tie-break rule is trustworthy — this repo's own WO-34 lesson (a
    single case isn't enough to safely generalize a matching-logic
    change) applies directly; separately, take a fresh look at
    Albuquerque's Legistar calendar page structure.
  - **History**: full diagnosis in `BACKLOG_DONE.md`'s WO-77–82 entry
    (2026-08-30); this entry compacted 2026-08-31.

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

### 28 well-formed IQM2 queue rows point at retired tenants `[NEEDS-AUDIT]` `[WAIT]`

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

### Swagit multi-clip meetings: local script still needs the cloud worker's fix (WO-79) `[NEEDS-AUDIT]`

- **Issue**: `scripts/transcribe_backlog_locally.py` doesn't consume
  `video_segments`/`chunk_plan`, so it can't stitch a Swagit multi-clip
  meeting the way the cloud worker now does after WO-79 (2026-08-30).
- **Impact**: local-Whisper runs against Swagit tenants with no single
  combined source recording (confirmed: Yolo County CA, White Plains NY,
  Apple Valley MN) still can't produce one meeting-relative transcript.
- **Next action**: port the cloud worker's `probe_multi_clip_chunk_plan()`
  + `shift_segments()` stitch approach into the local script, per this
  repo's "two independent transcription paths" convention; also re-run
  the fixed resolver against the original 43-URL 2026-08-18 sweep to size
  how many are genuinely multi-segment, and do a broader live Swagit
  audit.
- **Constraint**: even the cloud-worker path has two known unhandled
  edges — chunk-plan jobs skip the live per-chunk re-resolve the
  ordinary path uses to guard against stale URLs, and there's no
  sub-chunking for an individual very-long clip yet — neither has a
  confirmed real case forcing it.
- **History**: `BACKLOG_DONE.md` — WO-79 (2026-08-30) built the cloud
  worker fix.

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

### ~12 OnBase/Hyland-family pages still resolve with no video `[NEEDS-AUDIT]`

- **Issue**: ~12 OnBase/Hyland-family tenant pages still resolve with no
  video, each needing its own per-tenant "where does this jurisdiction
  actually put video" hunt.
- **Impact**: real population is 31 pages across 25 OnBase/Hyland-family
  tenants (matched on the `OnBaseAgendaOnline`/`agendaonline` URL *path*,
  not a vendor-name grep, which misses most of the platform) — 17 with no
  video, 4 already fixed (Santa Barbara/Pittsburg), leaving ~12 open and
  growing: 3 new tenants surfaced in a single day via WO-46's daily
  failure digest (`egenda.scgov.net`, `meetings.muni.org`,
  `ecm.cityofsantacruz.com`). Video presence isn't caption presence
  either — only 1 of the 31 pages has real captions, so repointing buys a
  video, not a transcript.
- **Next action**: work the per-tenant hunt using the repoint method
  already proven on the 3 fixed pages.
- **History**: full investigation, the working repoint method, and the 3
  fixed pages are in `BACKLOG_DONE.md`'s "Four archived pages pointed at
  agenda systems with no video" entry — this entry is only the residual
  left open.

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

### Tucson, AZ's one archived page has no video (50-largest-cities audit) `[NEEDS-AUDIT]`

- **Issue**: Tucson AZ's one archived page
  (`tucson-az-2026-08-05-regular-meeting`, source
  `tucsonaz.hylandcloud.com`) genuinely has no video — confirmed real,
  re-checked against the live archive 2026-08-30.
- **Impact**: no video/transcript for this Tucson meeting; real
  video/audio+minutes exist on a separate city YouTube channel/page not
  yet wired to `youtube_channel.py`, which today only covers Legistar
  netlocs.
- **Next action**: same shape as the Columbus OH fix (WO-72) — a real,
  buildable fallback entry once a channel ID is confirmed.
- **History**: full per-tenant audit history in `BACKLOG_DONE.md`.

### Atlanta, GA's original ChampDS gap is unconfirmed (50-largest-cities audit) `[NEEDS-AUDIT]`

- **Issue**: Atlanta's originally reported ChampDS gap can't be confirmed
  either way — re-checked against the live archive 2026-08-30, 14 real
  meeting links are now archived (up from "at least one"), but the
  working ones found are sourced from IQM2 (`atlantacityga.iqm2.com`),
  not ChampDS.
- **Impact**: Atlanta apparently runs both IQM2 and ChampDS for different
  bodies, so the original ChampDS-specific gap is unverified.
- **Next action**: get the user's specific failing ChampDS URL for
  Atlanta before chasing further — not otherwise actionable.
- **History**: full per-tenant audit history in `BACKLOG_DONE.md`.

### Omaha, NE has zero archived pages (50-largest-cities audit) `[NEEDS-AUDIT]`

- **Issue**: Omaha NE still has zero archived pages — confirmed
  2026-08-30 (`/api/jurisdictions?q=omaha` returns no matches).
- **Impact**: no coverage for Omaha at all. Live video exists only at
  `citycouncil.cityofomaha.org` during scheduled meeting times, with no
  archive; the "past videos" link routes to `cityclerk.cityofomaha.org`,
  which is Cloudflare-protected and returned inconsistent results live
  2026-08-30 (sometimes a JS challenge shell, sometimes a plain 403).
- **Next action**: genuinely needs real investigation, not a quick fix —
  find a path past `cityclerk.cityofomaha.org`'s Cloudflare protection or
  another source entirely.
- **History**: full per-tenant audit history in `BACKLOG_DONE.md`.

### Virginia Beach, VA's OnBoardGOV SPA gap is real but less urgent than framed (50-largest-cities audit) `[NEEDS-AUDIT]`

- **Issue**: the `onboardgov.virginiabeach.gov` SPA gap is real, but
  Virginia Beach already has a real, working City Council meeting page
  (`virginia-2026-08-18-city-council-meeting-8-18-2026`) sourced from
  Cablecast (`virginiabeach.cablecast.tv`, an already-supported
  platform) — confirmed against the live archive 2026-08-30; its
  jurisdiction was also corrected from bare "Virginia" to "Virginia
  Beach, VA" the same night.
- **Impact**: if Cablecast keeps covering Council meetings going forward,
  the OnBoardGOV SPA investigation may not be worth the headless-browser
  cost at all.
- **Next action**: confirm Cablecast's real ongoing Council-meeting
  coverage before investing in the SPA gap.
- **History**: full per-tenant audit history in `BACKLOG_DONE.md`.

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

- **`[HUMAN]` Santa Clara's already-valid jurisdiction strings need a
  canonical form applied.**
  - **Issue**: four independently-valid Santa Clara jurisdiction strings —
    `County of Santa Clara, CA`, `The County of Santa Clara, CA`, `Santa
    Clara County, CA`, `County of Santa Clara Office` — all pass
    validation as-is, so `finalize_jurisdiction()`'s recompute makes zero
    changes to any of them (confirmed live, current==repaired on every
    one). City of Santa Clara and the VTA also need `", CA"` suffixes
    added.
  - **Impact**: 4+ Santa Clara-area pages carry inconsistent jurisdiction
    strings instead of the decided canonical form, and no existing admin
    endpoint can write an explicit override — `POST
    /internal/jurisdiction/backfill-apply` only ever recomputes via
    `finalize_jurisdiction()`.
  - **Next action**: build a small new admin capability (an
    explicit-string override endpoint, scoped tightly), or make a
    deliberate one-off decision to bypass `finalize_jurisdiction()` for
    this case.
  - **Constraint**: canonical form already decided (2026-08-23): `Santa
    Clara County, CA` for the county rows, consistent with every other
    county in the archive. This is a product/engineering call, not a
    token-access one.
  - **History**: split out of WO-47, which closed the
    Redding/Healdsburg/Arcata/Paso Robles half of the same original entry
    via `backfill-apply` — see `BACKLOG_DONE.md`'s 2026-08-29 "needs a
    human" review entry for full row/cause detail, and its 2026-08-30
    production-write entry (98 real jurisdiction corrections applied
    across 6 rounds) for the broader cleanup this fell out of.

- **`[NEEDS-AUDIT]` Kansas City pair (`154`/`155`) has no single correct
  jurisdiction.**
  - **Issue**: pages `154`/`155` ("City of Kansas City" → "Kansas City")
    span the KS/MO state line, so there's no single correct jurisdiction
    string derivable from this data alone.
  - **Impact**: 2 pages show an ambiguous jurisdiction with no clean fix.
  - **Next action**: needs a product decision on how to represent a
    cross-state-line "Kansas City" (pick one state, or a dual-state
    representation) before any code change.
  - **History**: the other 5 pages this entry originally covered — Oxford
    County ON, Breckenridge TX, Eustis FL, Hendersonville NC, Loganville
    GA — were confirmed deployed and applied 2026-08-30; see
    `BACKLOG_DONE.md`.

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

- **[JUST-DO-IT] TelVue CDX enumeration solved; ~127 tokens still unclassified, 23 verified but unpublished.**
  - **Issue**: `collapse=urlkey:64` now returns the complete 313-org-token
    TelVue CDX set in one uncapped query, but ~127 tokens remain
    unclassified, and 23 already-verified real tokens (out of the last
    150 untouched ones checked; 16 of those 23 needed a
    jurisdiction-parsing fix, shipped as WO-74) haven't been ingested
    into production.
  - **Impact**: real TelVue-hosted jurisdictions stay unpublished until
    classified and signed off.
  - **Next action**: classify the remaining ~127 tokens, then get
    explicit sign-off before ingesting the 23 already-verified tokens as
    new public content.
  - **Constraint**: no ingestion of the 23 without explicit sign-off.
  - **History**: `BACKLOG_DONE.md` (full batch history, per-token
    verification, and the "~112 remaining" figure's correction).

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
    this needs real hours to pass, not a quick retry — which specific
    meeting hit the 429 wasn't recorded.
  - **Impact**: Holyoke's meeting isn't pushed.
  - **Next action**: do a fresh check now that more time has passed,
    rather than assuming it's recovered.
  - **History**: `BACKLOG_DONE.md` (ProudCity adapter shipped, ~18 real
    tenants pushed 2026-08-26).

- **[NEEDS-AUDIT] ProudCity: four tenants remain unpushed (two undiscovered domains, two Cloudflare-gated).**
  - **Issue**: Charlotte TX and Brazos Valley COG are too ambiguous to
    guess a domain for and have never been chased. Lafayette CA and
    Talent OR remain Cloudflare-gated (`www.cityoftalent.org` still 403s
    live as of 2026-08-30).
  - **Impact**: low priority — the adapter and known-domains list already
    cover the real yield from this round; these four stay unpushed.
  - **Next action**: none scheduled. If pursued: Charlotte TX/Brazos
    Valley COG need a real domain lead first; Lafayette/Talent need the
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
  - **Next action**: Cablecast's 101-page per-row audit is the one
    concrete, scoped follow-up (commit `731da71` already recovered 23 of
    a prior 101 via a subdomain-validation fallback at
    `cablecast.py:589-602`, so a similar per-row pass on the current 101
    is plausible). YouTube has no structural fix (`uploader` is a channel
    name, not a government field). Swagit needs a non-Census entity
    table; eScribe needs its hyphen-matcher gap closed (see that
    platform's own corrected entry elsewhere in "Platform & jurisdiction
    coverage").
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

- **[NEEDS-AUDIT] Palm Beach County FL's JS-rendered SharePoint page evades the empty-shell escalation trigger.**
  - **Issue**: the page's shell carries ~6KB of real nav/chrome text, so
    the near-empty-text escalation trigger (tuned to Tucson's 153-char
    shell) never fires.
  - **Impact**: this JS-rendered SharePoint page never gets the
    headless-browser escalation it needs.
  - **Next action**: build a SharePoint-specific fingerprint, or a
    different heuristic than raw text length — not a wider version of the
    existing trigger, which would make every enabled fetch pay a ≥4s
    browser cost on ordinary no-video pages.
  - **History**: `BACKLOG_DONE.md` (2026-08-14 generic-fallback rebuild);
    moved out of Dormant 2026-08-30.

- **[LATER] `elpasotexas.gov/videos/` has no adapter of its own.**
  - **Issue**: pasting that URL lands in `generic_fallback.py` instead of
    a "pick a body, then pick a meeting" flow.
  - **Impact**: low priority — every one of El Paso's 13 Vimeo showcases
    already resolves individually (WO-29).
  - **Next action**: none scheduled; low priority.
  - **History**: `BACKLOG_DONE.md` (full investigation).
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

### Transcription queue & workers

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

- **[WAIT] `thumbnailUrl` "Videos" structured-data flag — fixed, only the
  validation click is left.**
  - **Issue**: Search Console flagged "Missing field 'thumbnailUrl'" on
    the Videos structured-data report, for Lynchburg's meeting page (not
    San Carlos, as an earlier unverified guess had it).
  - **Impact**: none currently — root cause corrected and confirmed fixed
    2026-08-29; `thumbnailUrl` is already correctly populated and live on
    the page.
  - **Next action**: open Search Console's Videos structured-data report
    and click **VALIDATE FIX** — validation still reads "Not Started,"
    nobody has asked Google to re-verify yet.
  - **History**: `BACKLOG_DONE.md` (root-cause correction and fix,
    2026-08-29).

- **[NEEDS-AUDIT] New "Missing field" flags — Videos `uploadDate`, Events
  `startDate` (both 2026-08-31) — likely trade-off of the 2026-08-21
  datetime-validation fix.**
  - **Issue**: promoted from `CLAUDE_INBOX_TRIAGE.md`; a different flag
    from the `thumbnailUrl` entry above.
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

- **`[IMPROVEMENT-ROUND]` Corpus expansion — discover additional meetings from tenants already in the Archive — distinct from the new-tenant crawler above.**
  - **Issue**: there's no way today to discover a tenant's meetings beyond
    one already-known URL, for tenants already in the Archive (as opposed
    to discovering brand-new tenants, which is what the crawler entry above
    is about).
  - **Impact**: real sizing pulled live from production — only 4 mechanisms
    (Granicus RSS, CivicClerk Events API, PrimeGov `ListArchivedMeetings`,
    YouTube channel listings) can list a tenant's meetings beyond one known
    URL today, covering ~1,030 of ~2,358 tenants (~44%).
  - **Next action**: see `CORPUS_EXPANSION_PLAN.md` — a sized-out design
    exists, planned but not yet built. Duration filtering was already
    ruled out (transcription is on-demand, not a batch queue, so it's not
    a real cost lever); agenda-vs-transcript topic splitting is
    deliberately left to `rtr-upcoming`, which will discover agendas
    before video exists and filter on topic at that cheaper stage.
  - **History**: `CORPUS_EXPANSION_PLAN.md` (planned, not built). Addendum
    written 2026-08-30.
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
