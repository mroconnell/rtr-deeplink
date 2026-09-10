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

Standing decisions — do NOT re-raise  (9)
  Video-less meetings are not ingested by sweeps -- record "no video"…  (1)
    [JUST-DO-IT] `[EASY]` 20 rows in the national tables carry a…
  `jurisdiction_confidence IS NULL` is deliberately excluded from…
  Don't reach for a bigger Render plan before measuring what the peak…
  Never run an unbounded scan or bulk workload against the production…
  Prefer a generated/computed column over "add a column, then backfill…
  Never attempt to auto-solve a Cloudflare "Verify you are human"…
  Don't lower `dedupe_rollup_transcripts.py --min-retained` below 0.05
  Don't lower `MIN_PLAUSIBLE_MEETING_SECONDS` below 60s to catch more…
  Handover: 120 of the wildcard-sweep's 350 tenants remain unresolved —…

Ship next — root cause known, fix settled `[JUST-DO-IT]`  (11)
  `hub_slug_aliases.csv` can only redirect an old slug to ONE new home,…
  WO-153's leftover Part B/C rows: 111 shared-host domains still…
  `wo150_finish_tier3.py` never writes a probe reject back into…
  4 more wrong-government domain mappings, same fix shape as the 17…
  `wo150_muni_ladder_sweep.py`'s headless rung finds a real platform…
  Dashboard filters: exclude a string, and filter on blank / non-blank…
  Coverage registry: per-state view and other dashboard additions…  (5)
    [JUST-DO-IT] `slice_cached_audio()` skips the corrupt-chunk…
    [JUST-DO-IT] 82 archived YouTube meetings have embedding switched off…
    [JUST-DO-IT] `feed_tier3_auto_transcription.py`'s per-line result…
    [JUST-DO-IT] `[EASY]` Port `wo130_county_ingest.py`'s YouTube…
    [JUST-DO-IT] `[EASY]` `find_specific_platform_link()`'s…

Needs a human — dashboard, prod, or product call `[HUMAN]`  (6)
  Production actions only Ryan should take  (5)
    [HUMAN] One live page is keyed to the wrong government: a real…
    [HUMAN] Two live pages need deleting: real video, zero transcript…
    [HUMAN] 11 hosts the coverage registry ties to the wrong government:…
    [HUMAN] `www.sussex.nj.us` is pinned to Sussex *borough*…
    [HUMAN] 13 archived YouTube pages point at a video that is gone (7…
  Decisions about already-live content  (1)
    [NEEDS-AUDIT] `[BIG]` Repetition-loop transcript-defect population —…

Open bugs — real, root cause not settled `[NEEDS-AUDIT]`  (120)
Open bugs — real, root cause not settled `[NEEDS-AUDIT]`  (116)
  [NEEDS-AUDIT] A real US government's YouTube video got minted with a…
  [NEEDS-AUDIT] `rtr-deeplink`'s SIGABRT crash-loop (status 134) is…
  [NEEDS-AUDIT] `hub_sweep_wo126.Result` only fills…
  [NEEDS-AUDIT] `scripts/wo151_research_url_ladder_sweep.py`'s headless…
  [NEEDS-AUDIT] `detect_platform()`'s bare-substring match on a vendor
  [NEEDS-AUDIT] §158's write protocol doesn't catch a same-row-count
  [NEEDS-AUDIT] A minted `rtr:` id's state code can be a false positive
  [NEEDS-AUDIT] `scripts/tier3_auto_transcription_queue.txt`'s real…
  [NEEDS-AUDIT] A `tenant_overrides.csv` pin only affects future
  [NEEDS-AUDIT] Phase 2d's signal-based recovery (WO-110,
  [NEEDS-AUDIT] Several already-archived pages carry a confidently-
  [NEEDS-AUDIT] A bare unqualified name that exists in BOTH the
  [NEEDS-AUDIT] A jurisdiction string with a leading "The " before the
  [NEEDS-AUDIT] 16 real municipalities nationwide have a compound
  [NEEDS-AUDIT] eScribe serves the same meeting under multiple
  [NEEDS-AUDIT] A `strength=fallback` tenant pin cannot correct a
  [NEEDS-AUDIT] Wrong-government-content pattern confirmed on 6 live
  [NEEDS-AUDIT] Full-corpus screen (5,857 pages) found the same
  [NEEDS-AUDIT] Same source URL, different query string, two
  [NEEDS-AUDIT] Three pages from the school-district audit resolved
  [LATER] GovDelivery -- a proposed discovery lead for finding new
  [LATER] Two real, scoped enumerator/adapter gaps found chasing the
  [NEEDS-AUDIT] `scripts/score_gov_registry.py` overwrites
  [NEEDS-AUDIT] `scripts/score_gov_registry.py` can't see `match`-
  [NEEDS-AUDIT] `civicplus.py`'s `resolve()` has no encoding fallback
  [NEEDS-AUDIT] The same YouTube video submitted via two different URL
  [NEEDS-AUDIT] `[BIG]` No automated "pick the best candidate" step
  [NEEDS-AUDIT] `[BIG]` Microsoft Teams and Zoom are real, confirmed
  [NEEDS-AUDIT] No adapter for a PMN "Audio File Location" pointing at
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
  `YouTubeAssetFinder.extract_video_id()`'s regex matches YouTube's own…
  6 `best_effort` YouTube pages archived a promotional/off-topic video…
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
  `transcribe_backlog_locally.py`'s new yt-dlp audio download also hits…
  63 identity-checked pages still need a YouTube-transcript fetch —…
  ChampDS symptom B — instant 0.2s failures from the JSON API,…
  `[JUST-DO-IT]` ~10 OnBase/Hyland-family pages still resolve with no…
  Duration alone cannot separate a very short real meeting from an ad…
  Residual gaps from the 50-largest-cities audit `[NEEDS-AUDIT]`
  Granicus's GovAccess CMS product is undetected and blocked by…
  Jurisdiction extraction & backfill  (24)
    `[NEEDS-AUDIT]` A real "Hermantown" (city ending in "-town" as part…
    `[NEEDS-AUDIT]` A real, resolvable Albion, MI civicweb page archived…
    `[NEEDS-AUDIT]` `[EXAMPLE]` The county-form name of a fully…
    `[JUST-DO-IT]` `[EASY]` "Charter Township of X" keys to the village…
    `[JUST-DO-IT]` `[EASY]` A literal HTML entity in a stored…
    `[JUST-DO-IT]` `[EASY]` Census LSAD "corporation" is neither stripped…
    [HUMAN] Five `youtu.be` pages for the Wasatch Front Waste & Recycling…
    `[NEEDS-AUDIT]` `[EASY]` `"Regional Municipality of X"`/`"Region of…
    `[NEEDS-AUDIT]` `[EASY]` `classify.py`'s SPECIAL_DISTRICT rule…
    `[NEEDS-AUDIT]` `[EASY]` `pub-*` eScribe hosts resolve to a US…
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
    `[LATER]` 5 small Southampton County, VA towns (Boykins, Branchville,
    `[NEEDS-AUDIT]` A CivicPlus page that delegates to a video link on a
    `[NEEDS-AUDIT]` `rtr-business/research/jurisdiction_coverage.csv` has…
    `[NEEDS-AUDIT]` A same-state place/county name collision falls…
  Adapter & platform gaps  (39)
  Adapter & platform gaps  (38)
    [NEEDS-AUDIT] About 65 `www.youtube.com` rows in…
    [NEEDS-AUDIT] `ec1c24.com` is an unrecognized video-index wrapper…
    [NEEDS-AUDIT] A same-named Granicus tenant is a real video source for…
    [NEEDS-AUDIT] The coverage registry's `domain` field maps a small…
    [NEEDS-AUDIT] `HIGH_RISK_TITLE_PLATFORMS` (`{"youtube", "vimeo"}`,…
    [JUST-DO-IT] A bare eScribe tenant root (no `Meeting.aspx` path)…
    [NEEDS-AUDIT] `suiteone.py`'s `resolve()` raises a raw `ValueError`
    [JUST-DO-IT] Castus's URL regex only matches `/video/{id}`, silently
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
    [NEEDS-AUDIT] A resolve that delegates to a generic video host…
    [NEEDS-AUDIT] `granicus.py`'s `_fetch_page()` raises an unhandled…
    [NEEDS-AUDIT] `wo134_confirmed_hits_ingest.py`'s Granicus fallback…
    [NEEDS-AUDIT] `[EXAMPLE]` A newer CivicPlus product generation…
    [NEEDS-AUDIT] `[EXAMPLE]` Two real, unsupported video platforms found…
    [NEEDS-AUDIT] `civicplus.py`'s own docstring claims AgendaCenter rows…
    [NEEDS-AUDIT] `scripts/build_jurisdiction_data.py`'s blanket…
    [NEEDS-AUDIT] `finalize_jurisdiction()`'s table validation doesn't…
    [NEEDS-AUDIT] Guessing a fixed meetings-page path only works for…
    [EXAMPLE] Streamline Website Solutions has no confirmed real example…

Reliability, ops & cost  (14)
  `[JUST-DO-IT]` Render *pipeline minutes* — build volume cut twice,…  (1)
    [LATER] Tighten the two transcription workers to their real import
  Media-source reliability  (4)
    `[NEEDS-AUDIT]` Some old/archived Granicus clips' `chunklist.m3u8`…
    `[NEEDS-AUDIT]` A single job still makes N consecutive pulls to the…
    `[NEEDS-AUDIT]` The 120s ffmpeg timeout is a flat value that doesn't…
    `[NEEDS-AUDIT]` East Lansing MI (Granicus): a new, deterministic…
  Transcription queue & workers  (7)
    [JUST-DO-IT] `_existing_tier3_queue_urls()`'s dedup key is an exact
    [NEEDS-AUDIT] `chunk_plan` stores JSON `null` rather than SQL NULL, so
    [NEEDS-AUDIT] An OOM-killed chunk is completely invisible — it
    [NEEDS-AUDIT] WO-57's claim heartbeat has no cap, and transcription
    [NEEDS-AUDIT] Backlog keeps shrinking — re-derived 2026-08-31.
    [LATER] `list_transcription_backlog_candidates()` still does a real
    [LATER] Second transcription worker's auto-generation TOCTOU race —
  Search Console, structured data & SEO plumbing  (1)
    [NEEDS-AUDIT] New "Missing field" flags — Videos `uploadDate`, Events
  `/coverage` as a QA surface  (1)
    [JUST-DO-IT] `/coverage`'s "Every place we've covered" table is a

Trust, safety & data quality  (16)
  A bare YouTube channel-listing scan measurably ingests non-meeting…
  A live page is keyed to the wrong government entirely — Bamberg…
  `[EASY]` YouTube video-ID regex accepts a generic "live stream" embed…
  Meeting body is blank on ~90% of archived pages `[NEEDS-AUDIT]`…
  `[LATER]` No blanket backfill can make pre-2026-08-21 `best_effort`…
  `[NEEDS-AUDIT]` "County of {Name}" jurisdiction prefix form isn't…
  `[NEEDS-AUDIT]` A customer's own Granicus channel-title suffix…
  `[NEEDS-AUDIT]` YouTube-delegated ingests can land with…
  `[LATER]` `best_effort` is sticky — nothing at ingest distinguishes a…
  `[IMPROVEMENT-ROUND]` Low-trust queue rows have no repair workflow…
  `[IMPROVEMENT-ROUND]` A low-trust review doesn't expire when the page…
  `[LATER]` Mastodon auto-posting has made zero real posts
  `[IMPROVEMENT-ROUND]` Social auto-posting only fires on page…
  `[LATER]` Prompt injection isn't a live product risk today, but the…
  `[HUMAN]` `[BIG]` Nothing verifies a submitted URL is a genuine…
  `[NEEDS-AUDIT]` Chula Vista's stale garbled-marker survives its own…

Roadmap & strategy `[IMPROVEMENT-ROUND]`  (25)
  `[IMPROVEMENT-ROUND]` A general-purpose "is this a real government…
  `[HUMAN]` YouTube captions via YouTube's official API, not InnerTube…
  `[IMPROVEMENT-ROUND]` `[BIG]` Agenda text as a first-class,…
  `[IMPROVEMENT-ROUND]` `[BIG]` App-wide audit — see…
  Product direction & open strategic questions  (1)
    `[IMPROVEMENT-ROUND]` `[BIG]` "Feed cities" — should this app ever…
  `[IMPROVEMENT-ROUND]` `[BIG]` Accounts + token billing, phases 2-6 —…
  Growth, audience & discoverability  (8)
    `[IMPROVEMENT-ROUND]` Zero-signal jurisdiction rows are the real…
    `[IMPROVEMENT-ROUND]` Proactive transcription crawler — grow the…
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

Parked deliberately — allowed back `[PARK]`  (4)
  Video-to-calendar join: match a government's video source to its own…
  Friday-night queue (2026-09-12): the token-heavy coverage passes…  (3)
    [IMPROVEMENT-ROUND] School-district / special-entity jurisdiction…
    [PARK] MPO / transit-authority / utility-district name table.
    [PARK] `[BIG]` "Request Transcript from Audio" doesn't work for…
```

<!-- TOC-END -->

## Standing decisions — do NOT re-raise

### Video-less meetings are not ingested by sweeps -- record "no video" instead `[STANDING]`

- **[JUST-DO-IT] `[EASY]` 20 rows in the national tables carry a double-encoded ñ, so the page display name reads "CaÃ±on City".**
  - **Issue**: `app/utils/jurisdiction_data/us_places.csv` has 3 rows (`0811810` Cañon City CO, `0639003` La Cañada Flintridge CA, `3525170` Española NM) and `us_counties.csv` has 17 (`grep -c 'Ã'`) where UTF-8 was decoded as Latin-1 and re-encoded. Found 2026-09-10 pinning `@canoncitygov`: the pin resolved to the right id, and the backfill wrote "CaÃ±on City, CO" as the display name.
  - **Impact**: wrong display name and hub slug on every page keyed to those 20 governments; a plain-English worklist name "Cañon City, CO" still resolves (the resolver folds accents), so identity is right and only the display is wrong.
  - **Next action**: fix the 20 rows in place (decode once), re-run `backfill_gov_id.py` for their hosts, add a test that no national-table name contains "Ã".
  - **Constraint**: regenerate from the Census source rather than hand-edit if the table is ever rebuilt; the generator is where the bug lives.
  - **History**: found 2026-09-10 during the shared-host pin pass.

- **Issue:** Ryan's rule, 2026-09-09, for every enumeration/ingest sweep:
  only meetings WITH video become Archive pages. Tier 1/2 (captions
  reachable) ingest with segments; tier 3 (video, no captions) goes to
  the cloud auto-transcription queue and drips in; agenda-only meetings
  are NOT ingested.
- **Impact:** A host with no video is a legitimate, recorded outcome
  (`no-video-found` in `jurisdiction_coverage.csv`, "No video" on the
  coverage dashboards) -- not a page. The 789 governments over 5,000
  people already rejected as no-video-found stay where they are.
- **Next action:** None; cite this before proposing an agenda-only ingest.
- **Constraint:** The Archive still accepts agenda-only pages from a
  reader's own paste; this rule is about bulk sweeps flooding the site.
- **History:** Coverage registry review, 2026-09-09 (WO-124 thread).

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

### Handover: 120 of the wildcard-sweep's 350 tenants remain unresolved — don't re-try the methods already ruled out below

**Status as of 2026-09-06, after 4 rounds of work (`rtr-deeplink` PRs
#743, #746, #747, #749, #750, #752, #756; full narrative in
`~/Documents/rtr-business/research/WILDCARD_SWEEP_NEW_TENANTS_STATUS.md`)**:
224 of 350 tenants ingested, 120 remain across three buckets —
**99 `no-url-found`** (no discoverable meeting URL at all), **14
`skipped-empty`** (a real page resolved, but zero usable content), **7
`resolve-failed`** (the one candidate tried errored). The itemized list
of all 120 (slug, platform, guessed name/state, outcome, detail) is the
durable handover record — see
`scripts/wildcard_sweep_data/wildcard_sweep_unresolved_120.csv`.
**Read this before spending more effort on this cohort** — a lot has
already been tried and ruled out.

**Against the `no-url-found` cohort specifically** (77 Granicus tenants
with "no valid view_id 1-3", 28 Legistar tenants with no public-video
event via the Web API and no companion Granicus domain — the count was
105 originally, 6 recovered via manual search since, see the round-3/4
history below), five separate follow-up tricks were tried, same day,
and all five came back empty:
1. **Widening Granicus `view_id` to 4-15** (20-tenant sample): 0 additional hits.
2. **Granicus's `mode=vpodcast` alternate feed** (all 77): 0 additional hits
   — every dead tenant's feed genuinely has zero `<item>`s in either mode,
   confirmed by reading the raw RSS (a real channel `<title>`, just no
   items), not a parsing gap.
3. **Loosening Legistar's `EventVideoStatus == "Public"` filter** (all 28):
   moot — every one of the 28 fails at the Web API level itself (HTTP 500
   "LegistarConnectionString..." or 400), meaning the wildcard-guessed
   slug isn't a valid Legistar API client identifier at all. There's no
   event data to filter more loosely.
4. **Guessing the "other" slug variant against the Legistar API**
   (mechanically stripping/adding `cityof`/`city`/`county`/state suffixes
   — the exact inverse of how the wildcard sweep generated each guess —
   21 variants tried across the 10 tenants where a variant existed to
   try): 0/21 valid. The web subdomain and the API client id aren't
   always the same string, and nothing tried here can recover the real
   one without a different data source (e.g. a Legistar client-id
   directory, which doesn't exist in this repo).
5. **Resolving the tenant's bare `Calendar.aspx` page directly**, bypassing
   the Web API and letting `LegistarAssetFinder`'s own page parser look
   for a real video link (all 28): 0/28 found any usable content. This
   did surface one new fact worth keeping: two different guessed slugs,
   `erin` and `raymond`, both resolve to identical content ("Wyandotte
   County, KS") — meaning some of these HTTP-200 "hits" are unclaimed
   Legistar subdomains serving a shared generic/demo landing page, not
   real per-government tenants. A real false-positive class in the
   original sweep's HTTP-signature check, worth knowing if that method
   is reused for a future sweep — it doesn't change anything for this
   cohort's outcome (still zero content either way), just its diagnosis.

Combined with a manual spot-check (Ryan, same day) confirming several of
these genuinely don't host video via Granicus/Legistar at all, this
cohort is a real dead end for automated enumeration, not an under-tried
one. Recovering more of them needs a genuinely different signal per
tenant (checking the government's own website for an alternate video
host entirely, or a separate Legistar-client-id directory) — real,
per-tenant work, not automatable the way the sweep itself was.
**Manual per-tenant web search did pay off for a handful** (round 3/4,
same date): 6 of the larger/better-resourced tenants recovered this way
(Allegheny County PA, Montgomery County PA, Texarkana TX, Barrie ON,
Greater Sudbury ON, Erin ON — the last three all landed on a real
eScribe subdomain the sweep never guessed), but 7 more attempts on
smaller municipalities found nothing (3-for-3 large vs. 0-for-7 small is
a real signal) — the remaining ~93 `no-url-found` tenants are those two
result classes combined, so don't expect the same hit rate on what's
left without a materially different lever.

**The other two buckets aren't "no candidate exists," they're "the one
candidate tried was bad."** `scripts/adhoc_wildcard_sweep_retry.py`
(2026-09-06) retries with the next candidate in the same feed/event list
instead of giving up on the first, and recovered 18 of the original 41
(44%) — see `BACKLOG_DONE.md` for that `[JUST-DO-IT]` entry. The 14
`skipped-empty` and 7 `resolve-failed` tenants left in the CSV above are
what remained after that retry pass; a deeper retry (past the 6-candidate
cap already tried) was tested on 12 large-pool Legistar tenants and
recovered only 1 more for ~168 extra requests — not worth repeating.

## Ship next — root cause known, fix settled `[JUST-DO-IT]`

### `hub_slug_aliases.csv` can only redirect an old slug to ONE new home, and `/j/cambridge` genuinely needs two `[JUST-DO-IT]`

- **Issue:** `archive/utils/hub_aliases.py`'s map is a plain
  `old_slug -> new_slug` dict. WO-153 (2026-09-10) re-keyed 5 pages from
  `rtr:unknown` to Cambridge, ON (`ca:csd:3530010`), all previously
  filed under the generic hub slug `cambridge` -- the same slug an
  *existing* alias row already redirects to `cambridge-ma` (Cambridge,
  MA, `us:place:2511000`, which really does have 7 live pages of its
  own). A visitor with an old `/j/cambridge` link meant for the Ontario
  government now lands on Massachusetts's hub instead; there's no way
  to write a second, disambiguating alias for the same old slug with
  today's data shape.
- **Impact:** narrow (one retired slug, one specific mix-up) but a real
  wrong-government redirect for anyone still holding that old link.
- **Next action:** either rerun `scripts/score_gov_registry.py` (which
  regenerates this file wholesale and might resolve it structurally if
  it tracks retirement order) or extend `hub_slug_aliases.csv`'s shape
  to support more than one target per old slug (e.g. keyed by a hint in
  the referring page) -- a bigger change, so start with the regen.
- **Constraint:** don't hand-add a second `cambridge` row to the CSV as
  it stands today -- `hub_slug_aliases()` is a plain dict keyed by
  `old_slug`, so the second row silently wins or loses depending on
  file order, not on which one is "more correct."
- **History:** `BACKLOG_DONE.md` WO-153, 2026-09-10.

### WO-153's leftover Part B/C rows: 111 shared-host domains still unresolved, 45 governments that look ready to queue `[JUST-DO-IT]`

- **Issue:** WO-153's bookkeeping pass on `jurisdiction_coverage.csv`
  left two lists of real, already-narrowed-down leads rather than
  chasing them to zero in one session. (1) 111 rows still carry a bare
  shared-host domain (YouTube/Facebook/Vimeo/TelVue/Cablecast) instead
  of the government's real website --
  `rtr-business/research/wo153_partB_resolved.csv` has every row, with
  a `real_domain_found`/`real_domain_source` column already filled in
  for the 37 this session settled (28 applied, 9 already fixed by a
  concurrent session) so a follow-up doesn't redo that work. (2) 45
  governments' `video-no-captions-queued`/`duplicate-queued` rows have
  no matching entry in the real
  `scripts/tier3_auto_transcription_queue.txt` but DO have a real,
  playable-looking video URL on file (the exact Torrington WY shape this
  WO's own brief named) -- `rtr-business/research/wo153_partC_final.csv`
  lists them under `disposition = "should be queued"`. Neither list was
  enqueued or further researched by WO-153 -- explicitly out of that
  WO's scope ("do not enqueue anything").
- **Impact:** 111 rows still mis-key to a shared host against Ryan's
  own rule; up to 45 real meetings are sitting un-queued despite already
  having a known-good video URL on file.
- **Next action:** for (1), continue the WebSearch-per-government pass
  WO-153 started (or find a faster domain-lookup source) and apply
  through `wo153_partB_apply.py`'s pattern (re-verify the row's current
  `domain` is still a bare shared host immediately before overwriting
  it -- that check is what let this session's own writer skip 9 rows
  another concurrent session had already fixed, rather than clobbering
  them). For (2), verify each of the 45 governments' video is real and
  has captions (Torrington WY's did) before adding it to the tier-3
  queue -- don't bulk-enqueue from the CSV without that check.
- **Constraint:** `jurisdiction_coverage.csv` is a live, multi-session
  file -- follow ENUMERATION_METHODS.md §158's write protocol (`flock`,
  fresh read, row-count floor, atomic write) for any further edit, same
  as WO-153's own two writer scripts already do.
- **History:** `BACKLOG_DONE.md` WO-153, 2026-09-10.

### `wo150_finish_tier3.py` never writes a probe reject back into `wo150_report.csv` `[JUST-DO-IT]` `[EASY]`

- **Issue:** `scripts/wo150_finish_tier3.py` probes every WO-150 tier-3
  candidate and logs the verdict to its own
  `wo150_tier3_finish_log.csv`, but never rewrites the matching row in
  `wo150_report.csv` the way `wo147_finish_tier3_queue.py` already does
  (`queued_tier3_pending` -> `queued_tier3`/`rejected_by_probe`). Found
  building WO-169's re-run candidate list: the one WO-150 probe-rejected
  government (Great Falls city, MT) still reads `outcome=queued_tier3`
  in `wo150_report.csv`, with the real reject verdict visible only by
  cross-referencing the separate finish log.
- **Impact:** `wo150_report.csv` overstates how many governments were
  actually queued -- a government whose only candidate failed the probe
  looks identical, in that file, to one that's really in the queue. Any
  later pass that trusts `wo150_report.csv`'s own `outcome` column
  (a `jurisdiction_coverage.csv` apply script, a funnel count) will be
  wrong until this is fixed.
- **Next action:** Port `wo147_finish_tier3_queue.py`'s own
  report-rewrite step (see that file, lines ~296-330) into
  `wo150_finish_tier3.py`: on accept, `queued_tier3_pending` ->
  `queued_tier3`; on reject, `queued_tier3_pending` -> `rejected_by_probe`
  (not `no_video_found` -- WO-169 gave this its own outcome since a real
  video existed), keeping `meeting_url`/`video_url` rather than blanking
  them (the exact bug WO-169 fixed in `wo147_finish_tier3_queue.py`
  itself, `BACKLOG_DONE.md` 2026-09-10).
- **Constraint:** `wo150_muni_ladder_sweep.py`/`wo150_finish_tier3.py`
  had an active continuation session at the time this was found --
  coordinate before editing, or confirm no other session is mid-edit on
  either file.
- **History:** Found and worked around (not fixed) during WO-169,
  `BACKLOG_DONE.md` 2026-09-10.

### 4 more wrong-government domain mappings, same fix shape as the 17 already corrected `[JUST-DO-IT]` `[EASY]`

- **Issue:** WO-146's re-verification (`BACKLOG_DONE.md`, 2026-09-10)
  found `jurisdiction_coverage.csv` rows whose `domain` actually belongs
  to a different, same-named or same-CDN-slug government: Providence
  County, RI (`providenceri.iqm2.com` is really the City of Providence
  -- and Rhode Island has no functioning county governments at all, so
  there may be no real target row to move the domain to), Winona
  County, MN (`pub-winona.escribemeetings.com` is really Winona city),
  Imperial city, CA (`imperial.granicus.com` is really Imperial
  COUNTY), Colorado County, TX (`coloradoga.granicus.com` is the
  Colorado state legislature's own Granicus tenant, not a local
  government at all), and Arkansas County, AR
  (`arkansas-sc.granicus.com` is the Arkansas Supreme Court's).
- **Impact:** these 4 domains stay wrongly attributed and will keep
  producing the same wrong "found it" result if anyone re-sweeps them.
- **Next action:** apply the same clear-source/set-target pattern
  `research/wo146_wrong_domain_fix.py` already used for the other 17 --
  for the two state-entity cases (Colorado, Arkansas), there is no local
  government to redirect to, so just clear the domain and record
  `reject_reason=off-mission`, not `wrong-domain-mapping`.
- **Constraint:** Colorado County, TX's row already has `transcribed=
  True` from an older, unrelated sweep, which is why WO-146's own
  backfill left it alone (the standing "never overwrite a real True"
  rule) -- but a fresh `/internal/export/pages` check found ZERO live
  pages under this gov_id, so that `True` is stale, not evidence of a
  real page. WO-153 (2026-09-10) already cleared this exact staleness
  for Providence County, RI and Winona County, MN (both were in its
  transcribed-but-no-page sweep, confirmed the same way: the archived
  page really is the city's, not the county's) -- their `transcribed`
  flags are already cleared, so only the `domain` field itself still
  needs the clear-source/set-target fix described above. Worth a fresh
  look at what `transcribed=True` is actually
  based on for this row before trusting it elsewhere.
- **History:** WO-146, `BACKLOG_DONE.md` 2026-09-10.

### `wo150_muni_ladder_sweep.py`'s headless rung finds a real platform link but can't extract its host `[JUST-DO-IT]` `[EASY]`

- **Issue:** `scripts/wo150_muni_ladder_sweep.py`'s access ladder calls
  `wo141_access_ladder_pilot.try_headless()` for a page that loaded
  cleanly with no visible link, but that helper returns only a
  classification (`platform_link`/`listing`/`none`/`challenge`), not the
  raw HTML `page.content()` returned. When headless *does* classify a
  page as `platform_link`, `run_access_ladder()` has no text left to run
  `_extract_platform_hit()` against, so it falls through to
  `no-platform-link-found` instead of actually finding the government's
  platform.
- **Impact:** Every WO-150 government whose real platform link is only
  drawn by JavaScript is undercounted as `no_platform_link_found` even
  though the fix WO-133 already proved (headless finds JS-drawn links)
  would have worked here. See `wo150_report.csv` rows whose `note`
  contains "raw content wasn't retained for host extraction".
- **Next action:** Change `try_headless()` (or add a sibling) to return
  the page's HTML alongside its classification, and have
  `run_access_ladder()` call `_extract_platform_hit()` on it the same
  way the plain/browser-headers rungs already do.
- **Constraint:** `wo141_access_ladder_pilot.py` is a read-only pilot
  script another WO may still be running against; coordinate before
  changing its return shape, or make the change in a wo150-local copy
  of just `try_headless()` instead.
- **History:** WO-150, `BACKLOG_DONE.md` 2026-09-10.

### Dashboard filters: exclude a string, and filter on blank / non-blank `[JUST-DO-IT]` `[EASY]`

- **Issue:** Both review pages -- the meeting inventory
  (`scripts/export_meeting_inventory.py`'s HTML) and the coverage
  registry (`rtr-business/research/coverage_registry.py`'s HTML) -- only
  filter a column by "contains". Ryan wants (1) filter OUT a string per
  column, (2) show only blanks, (3) hide blanks.
- **Impact:** Finding "governments with a domain but no hub" or "pages
  whose body is blank" needs the CSV today; the page can't express it.
- **Next action:** In each page's filter row accept `!text` (exclude),
  `=` (blank only) and `!=` (non-blank), documented in the placeholder;
  the `matches()` function in both templates is the only place to touch.
  Same small change in both files; keep the two templates' JS aligned.
- **Constraint:** None.
- **History:** Asked 2026-09-09 in the WO-124 review.

### Coverage registry: per-state view and other dashboard additions `[JUST-DO-IT]`

- **Issue:** `rtr-business/research/coverage_registry.py`'s dashboard
  groups by government kind only. Wanted: a state/province picker that
  recomputes the same funnel for one state (IL, TX, QC, PA, MO each have
  1,000+ governments with no page and their state directories are the
  lists to work from), plus a "known platform but no page" tile and a
  tier breakdown tile.
- **Impact:** Picking a state to work is a CSV exercise today.
- **Next action:** Add the picker beside the population dropdown; the
  dashboard is computed client-side from the rows, so it is a filter on
  `state` before `renderDash()`.
- **Constraint:** Keep the page under the publisher's size limit (the
  hosted copy omits two URL columns for that reason, see the script).
- **History:** Asked 2026-09-09 in the WO-124 review.

Small, self-contained, no open design question. Jurisdiction-extraction
items that also qualify live under **Platform & jurisdiction coverage**
so that work reads together.

- **[JUST-DO-IT] `slice_cached_audio()` skips the corrupt-chunk decodability guard `extract_chunk_audio()` has had since 2026-08-21 — confirmed 5+ real production failures across 5 distinct sources on 2 platforms.**
  - **Issue**: WO-54/58's whole-audio-cache path (`app/platforms/media_probe.py:944-982`, `slice_cached_audio()`) only checks ffmpeg's exit code and that the output file is non-empty. It never calls `_mean_volume_db()` — the same decodability check `extract_chunk_audio()`'s `_extract_chunk_once()` already applies (see that function's own docstring, `media_probe.py:1011-1031`) — so a corrupt/undecodable byte range inside the cached whole-file audio reaches `engine.transcribe_chunk()` raw as an unhandled PyAV `InvalidDataError` instead of failing as a normal retryable `(False, reason)`. Re-confirmed by direct read of current `slice_cached_audio()` on 2026-09-05: still no guard.
  - **Impact**: real, repeated, cross-platform — job 1157 (San Diego CA, Granicus, lost 15/25 chunks, 60% of the meeting), job 1226 (College Station TX, CivicClerk, 11/17), job 1259 (Falls Church VA, Granicus, gave up at 14/15), job 1377 (Mansfield TX, CivicClerk, gave up at 1/6), job 1766 (Alameda County CA "BOS View", Granicus, gave up at 17/22, 2026-09-05) — same exact `errno 1094995529` signature every time, not one platform's quirk. WO-54/58's whole-audio-cache path targets exactly the seek-hostile progressive sources (ChampDS, Granicus) most likely to contain a corrupt/interrupted byte range, so this sits on the path most likely to need the guard.
  - **Next action**: add the same `_mean_volume_db()` decodability check to `slice_cached_audio()`, returning `(False, "...isn't decodable (likely truncated/corrupt)")` instead of `(True, None)` on an undecodable slice. `worker/main.py`'s existing per-chunk retry/budget logic already treats that shape as a normal retryable failure — no other code path needs to change.
  - **History**: found by the inbox-triage Routine's 2026-08-29 run; the 2026-08-30, -31, and 2026-09-01 runs each confirmed a fresh independent occurrence on a new source.

- **[JUST-DO-IT] 82 archived YouTube meetings have embedding switched off by the owner, so our player shows "Video unavailable" while the video is alive on YouTube and the transcript renders beside it.**
  - **Issue**: YouTube's oEmbed returns HTTP 401 for a video whose owner disabled playback on other sites (82 of 95 non-answering videos in the 2026-09-09 study; the watch page reports the video playable and all 82 pages already hold a transcript). The embed on our page then says "Playback on other websites has been disabled by the video owner — Watch on YouTube", verified live on `/m/peachtree-corners-ga-2026-08-27-peachtree-corners-city-council-meeting-august-25`. Deep links into these pages seek nothing.
  - **Impact**: 82 pages (plus every future one from those channels) deliver the transcript but not the product's core promise, a shareable moment in the video. Separately, 13 videos are genuinely gone (7 deleted/404, 3 private/403, 3 malformed ids/400) and 11 of those pages have no transcript either.
  - **Next action**: both halves shipped, but only reach *future* resolves, not these 82 already-archived pages. WO-135 (2026-09-09) made the detection real — `YouTubeAssetFinder.resolve_video_id()` reads yt-dlp's own `playable_in_embed` field (not oEmbed, which this entry's Issue line got wrong) at zero extra request cost and sets `YOUTUBE_EMBED_DISABLED_MARKER` (`app/platforms/youtube.py`) on `video_warnings`, and `check_permanent_failure()` lets a caller check it ahead of time. WO-136 (2026-09-09) shipped the consuming side — `archive/templates/meeting_page.html` and `app/static/player.js` both render a "Watch on YouTube" link (`youtube.com/watch?v=…&t=754s`, honouring the deep-linked start time) in place of the dead player whenever `video_warnings` carries that marker, or the player errors at runtime. **Still open**: neither path re-checks a page that already has a transcript — `scripts/fetch_youtube_transcripts.py`'s daily precheck only ever looks at `/internal/transcript-wanted`'s no-transcript queue, and these 82 pages are excluded from it by definition (they already hold one) — so a one-time backfill sweep (call `YouTubeAssetFinder.check_permanent_failure()` per page, POST the video marker to `/internal/pages/{slug}/video-status`) is what's left to actually reach them. The 13 dead pages want `noindex` and a removal list; that is a product call, filed under Needs a human.
  - **Constraint**: the check reuses the same metadata-only yt-dlp extraction WO-135 already added, not the caption fetch — not the request shape behind `docs/investigations/youtube_429_block.md`, but keep it off the cloud worker's hot path all the same; a periodic sweep from the Mac is a few thousand light requests.
  - **History**: gov-id enumeration audit, 2026-09-09; per-video statuses in the study's lookup cache `reports/shared_host_lookups.csv` (blank `channel` = did not answer). WO-135's detection and WO-136's consuming side + thin-page fold-in (a *second* shape — a dead embed with no transcript at all, noindexed/delisted until a transcript lands) are both `BACKLOG_DONE.md`.

- **[JUST-DO-IT] `feed_tier3_auto_transcription.py`'s per-line result needs a durable log, not just stdout.**
  - **Issue**: `_push_if_has_video()` already returns a real `[OK]`/`[SKIP]`/`[FAIL]` reason string per queue line, but `main()` only `print()`s it — nothing writes it to a durable file, so once a line is dropped from `tier3_auto_transcription_queue.txt` (the queue always advances "regardless of individual outcomes," `feed_tier3_auto_transcription.py:203-206`) its outcome only survives in that day's GitHub Actions run transcript.
  - **Impact**: tier-3 drain failures are invisible after the fact, unlike the `nationwide_*_ingest.py`/`wo130_county_ingest.py`/`wo134_confirmed_hits_ingest.py` scripts' own resumable per-row CSV log.
  - **Next action**: add a durable per-line result log to `feed_tier3_auto_transcription.py` (append each `[OK]/[SKIP]/[FAIL]` line + URL + timestamp to a CSV alongside the queue file, mirroring the ingest scripts' own resumable-log pattern) instead of only printing to stdout.
  - **Constraint**: none known.
  - **History**: raised directly by Ryan, 2026-09-09, mid-run on the 2,404-candidate batch. This entry originally bundled a second item — agenda-only rows going straight to Archive instead of queuing to tier 3 — resolved differently than either option it posed: WO-130 (2026-09-09, same day) got an explicit, more specific rule directly from Ryan for the county population, "ONLY meetings with video," and implemented it in `wo130_county_ingest.py` as a THIRD outcome, `no_video_found` — recorded (reject_reason `no-video-found`) and left out of the Archive entirely, not queued to tier 3 either. Queuing was rejected on the merits, not just deferred: an agenda-only resolve has no `video_url`, so `_push_if_has_video()`'s "no video found on re-resolve" check would skip it every drain cycle forever — a queue entry that can structurally never succeed. Apply the same three-way split (ingest tier1/2, queue tier3, record-not-ingest agenda-only) to the next `nationwide_NNNN_ingest.py` copy too, per this project's copy-per-batch convention — `nationwide_2404_ingest.py` itself keeps its original `ingested_agenda_only` behavior unchanged, consistent with its own already-running log. WO-134 (2026-09-09, same day, the WO-129 confirmed-hits batch) independently reached the same three-way split in `wo134_confirmed_hits_ingest.py`'s own `no_video_found` outcome — this rule is now applied in two separate batch scripts, worth carrying into the next `nationwide_NNNN_ingest.py` copy alongside the durable-log fix above.

- **[JUST-DO-IT] `[EASY]` Port `wo130_county_ingest.py`'s YouTube channel-URL fallback into the next `nationwide_NNNN_ingest.py` copy.**
  - **Issue**: a `known_platform=youtube` hit (or a two-hop scan hit) is very often the CHANNEL itself (`youtube.com/@CountyName`), not a specific video — confirmed live 2026-09-09, WO-130: every one of ~30 county rows with a channel-shaped hit failed outright under `nationwide_2404_ingest.py`'s original logic (`YouTubeAssetFinder.resolve()` only extracts a video id, raises `ValueError` otherwise). Fixed for counties in `wo130_county_ingest.py`'s `youtube_channel_latest_video()` + the `_looks_like_channel_url()` gate in `resolve_seed()`: list the channel's `/videos` tab (flat, capped, same yt-dlp options as `youtube_channel.py`'s own listing) and pick the newest entry passing the existing governing-body title allowlist.
  - **Impact**: without this, every channel-shaped YouTube hit across any future `nationwide_NNNN_ingest.py` batch silently fails as `resolve raised: Could not find a YouTube video ID in ...` instead of finding the real, playable meeting that's actually there.
  - **Next action**: copy `youtube_channel_latest_video()`, `_looks_like_channel_url()`, and the `resolve_seed()` branch that calls them (plus the `yt_dlp`/`YouTubeAssetFinder` imports) from `wo130_county_ingest.py` into the next new batch script. Two real bugs already fixed in that copy, worth carrying forward exactly as fixed rather than re-discovering: (1) gate on `_looks_like_channel_url()` alone, never "no video id found" alone — the latter also matches a non-channel, non-video URL (a `youtube.com/results?search_query=...` "search our channel" widget link matched and got yt-dlp'd as if it were a channel, live-caught on Dubois County, IN); (2) return the actual resolved `https://www.youtube.com/watch?v={video_id}` as the seed/final URL, never the channel URL itself — the channel can never be re-resolved later, so a tier-3-queued channel URL would sit failing forever (live-caught on Knox County, IN, queued as `youtube.com/@knoxcountycouncil?streams`).
  - **Constraint**: still bounded by the same allowlist-title gate as every other high-risk-title platform — a channel with no recent video whose title reads as a real governing-body meeting correctly finds nothing rather than guessing.
  - **History**: WO-130, 2026-09-09 (`rtr-deeplink` PR for this work order); see `BACKLOG_DONE.md`'s WO-130 entry for the funnel this closed.

- **[JUST-DO-IT] `[EASY]` `find_specific_platform_link()`'s onclick/href/src regex can capture a truncated, dangling query string straight from an iframe's HTML attribute.**
  - **Issue**: confirmed live 2026-09-09 (WO-130, Lake County OH): the extracted YouTube embed URL came back as `.../embed/AscWHEa0ay4?enablejsapi=1&...&disablekb=0&` — a trailing bare `&` with nothing after it, straight from the source page's own iframe `src` attribute. Functionally harmless (the video id is in the path, unaffected), but it fails `tests/test_transcription_queue_files.py`'s dangling-query-separator and mid-parameter-truncation checks once such a URL reaches `tier3_auto_transcription_queue.txt`, and would confuse a human skimming the queue.
  - **Impact**: low-frequency (one confirmed instance across ~660 real rows this session) but will recur with any other adapter/attribute source that copies a raw `src`/`href` value verbatim; currently caught only by the test suite after the fact, one row at a time, by hand.
  - **Next action**: strip a trailing `&` (and any `key=` with an empty value immediately before end-of-string, per `VALUELESS_OK`'s own exception list) when `find_specific_platform_link()` (or whichever helper ends up owning URL extraction) returns a URL, rather than leaving each batch script to notice via a failed test.
  - **Constraint**: don't strip query strings generally — some platforms need theirs intact (e.g. a real `?v=` parameter).
  - **History**: WO-130, 2026-09-09; fixed by hand for the one Lake County, OH row this run produced (`tier3_auto_transcription_queue.txt`), not yet fixed at the source.

## Needs a human — dashboard, prod, or product call `[HUMAN]`

Nothing here is blocked on engineering. Most are one dashboard login or
one deliberate production action away from closing. Grouped by what kind
of human step they need.

### Production actions only Ryan should take

- **[HUMAN] One live page is keyed to the wrong government: a real Chenango TOWN, NY meeting displays as Chenango COUNTY, NY -- fixed for future ingests, needs a deploy + backfill for this one page.**
  - **Issue**: WO-145's breadth sweep ingested `townofchenango.civicweb.net`'s real Town Board meeting under `us:cousub:3600715110` (Chenango town, NY), but `key_check()` couldn't resolve that jurisdiction string to the intended id at registry/pinned confidence (Chenango County, NY is a real, different, larger New York county with the same base name) -- the page live-keyed to the county instead. A `strength=fallback` pin (`townofchenango.civicweb.net` -> `us:cousub:3600715110`) is now in `tenant_overrides.csv` (this PR), which fixes every future ingest/re-resolve of this tenant, but does nothing for the page that already exists.
  - **Impact**: one live page, `/m/chenango-county-ny-2026-09-02-town-board-02-sep-2026`, displays and is keyed as "Chenango County, NY" instead of the real Chenango town whose meeting it actually is.
  - **Next action**: after this PR deploys, run `backfill_gov_id.py --hosts townofchenango.civicweb.net` to re-key the one existing page.
  - **Constraint**: the pin must be live (deployed) before the backfill runs, or it re-resolves to the same wrong id.
  - **History**: WO-145, `BACKLOG_DONE.md` 2026-09-10.

- **[HUMAN] Two live pages need deleting: real video, zero transcript segments, created by a WO-146 script bug (fixed, but the sandbox can't run the delete).**
  - **Issue**: `scripts/wo146_api_relist_sweep.py`'s first version treated rtr-discovery's ledger status `resolved_ok` as "has real captions" when it was actually called with `require_captions=False` (deliberate, so a video-only outcome stays visible) — `post_resolve()` marks a video-only candidate `resolved_ok` too, no captions required. That shipped two pages with real video and 0 transcript segments as if they were tier-1/2: `loudoun-county-va-2013-01-11-video04-maptab` and `waukesha-city-wi-2026-09-08-finance-committee-on-2026-09-08-6-00-pm`. Caught by hand-checking the pilot's own report per this WO's own instructions, within the first 20 rows. The script now splits tier 1/2 vs tier 3 on the payload's own `segments` field, not ledger status.
  - **Impact**: two indexable pages with a video but no transcript — the exact "agenda-only page a sweep shouldn't have made" shape Ryan already had to correct once, just for video-only instead of video-less.
  - **Next action**: `POST /internal/admin/delete-pages` with `{"slugs": ["loudoun-county-va-2013-01-11-video04-maptab", "waukesha-city-wi-2026-09-08-finance-committee-on-2026-09-08-6-00-pm"]}`, `dry_run=true` first to confirm (already confirmed once, both found, matching titles/URLs), then `dry_run=false`. The auto-mode safety classifier in this sandbox refuses the real delete call even with a confirmed dry run, so this needs a human or a differently-permissioned session.
  - **Constraint**: slug-only, exact match (the endpoint's own design) — don't broaden to a fuzzy match.
  - **History**: WO-146, `BACKLOG_DONE.md` 2026-09-10.

- **[HUMAN] 11 hosts the coverage registry ties to the wrong government: 9 still want a pin to the *correct* one, 2 are undecidable (WO-153 fixed 5 of the original 18, 2026-09-10; the 2 county hosts a `fallback` pin couldn't fix were settled the same day with `authoritative` pins, see `BACKLOG_DONE.md`).**
  - **Issue**: WO-125's identity join (`BACKLOG_DONE.md`, 2026-09-09) checked every (gov_id, host) pair the registry claims against the host's landing page and found `jurisdiction_coverage.csv` matches names without state or type. WO-153 fixed 5 of these live (pin + `backfill_gov_id.py`, confirmed via a landing-page or meeting-text fetch first): `townofchevychase.org` → `us:place:2416620` (Town of Chevy Chase, MD), `pub-cambridge.escribemeetings.com` → `ca:csd:3530010` (Cambridge, ON, 5 pages), `cityofoakgrove.com` → `us:place:2953624` (Oak Grove *city*, MO — the "undecidable" city-vs-village call is settled: the domain literally says "cityofoakgrove", the Village has its own separate, correct row), plus two more found the same session (`reflect-brewster-ma.cablecast.tv` → `us:cousub:2500107980` Brewster, MA; `tecumseh-pub.escribemeetings.com` → `ca:csd:3537048` Tecumseh, ON). Still open: `superiorwi.gov` → `us:place:5578650` (City of Superior; page "Common Council"); `shelbytownmi.iqm2.com` → `us:cousub:2609972820` (portal "Charter Township of Shelby"); `colonieny.iqm2.com` → `us:cousub:3600117343`, `townofvictorny.gov` → `us:cousub:3606977387`, `websterny.gov` → `us:cousub:3605578971`, `southamptonny.iqm2.com` → `us:cousub:3610368473` (Town Boards, filed as villages — not re-verified by WO-153); `pub-clearview.escribemeetings.com` → `ca:csd:3543005` (WO-153 confirmed live: this eScribe tenant serves Township of Clearview, ON, not Clearview, OK, whose own research row wrongly recorded it — not yet pinned); `pub-whiterockcity.escribemeetings.com` → `ca:csd:5915007`, `pub-creston.escribemeetings.com` → `ca:csd:5903004` (same shape, not yet pinned); `watertown.civicweb.net` → `us:place:4669300` (WO-125's own landing-page fetch already found the portal footer says ", SD 57201" — confirms Watertown SD, not WI; still not pinned). `mcleancountyil.gov` and `kankakeecountyil.gov` are done (2026-09-10, `authoritative` pins with Ryan's ok, both pages re-keyed — `BACKLOG_DONE.md`); the general "a `fallback` pin cannot override a clean `registry` match" bug they hit stays open as its own entry. Two undecidable, unchanged: `walton.civicweb.net` ("Walton County", no state; claimed for Walton County FL *and* Walton village NY — WO-153 found the archived meeting titles ("Board of County Commissioners") support Walton *County*, but not which state), `camas.new.swagit.com` (file says Camas city, page says Camas School District `us:sd:5300810`).
  - **Impact**: live pages minted or unresolved on 9 still-open hosts; the coverage registry's `archive_pages`/tier/hub columns are wrong for every one of these rows.
  - **Next action**: Ryan confirms the 9 remaining pin candidates and writes them as `tenant_overrides.csv` rows (source `ryan_stated`), then `backfill_gov_id.py --hosts …`. If any of the 9 turns out to have page text that already resolves cleanly to a *different* real government, a `fallback` pin will be inert the same way — go straight to asking Ryan for `authoritative`.
  - **Constraint**: never pin from the research file's gov_id without a landing-page or meeting-text check first — WO-125 found 56% of the research file's checkable host associations wrong, and WO-153 caught one more of the same shape (Chevy Chase Village, MD vs. the separate, real "Chevy Chase town, MD") that a name-only match would have mis-pinned.
  - **History**: WO-125, WO-153, `BACKLOG_DONE.md` 2026-09-09/2026-09-10.

- **[HUMAN] `www.sussex.nj.us` is pinned to Sussex *borough* (`us:place:3471670`, source `ryan_stated`), but its landing page title is "Sussex County, NJ | Official Website".**
  - **Issue**: WO-125 left the row alone by rule (an identity join never overwrites an existing pin) and lists it here instead: the research file says Sussex County (`us:county:34037`), the live site agrees, and the one archived page's stored name is just "Sussex, NJ".
  - **Impact**: one page and its hub on the wrong government.
  - **Next action**: Ryan confirms, changes that row's gov_id to `us:county:34037`, and runs `backfill_gov_id.py --hosts www.sussex.nj.us`.
  - **History**: WO-125, `BACKLOG_DONE.md` 2026-09-09.

- **[HUMAN] 13 archived YouTube pages point at a video that is gone (7 deleted, 3 private, 3 malformed ids); 11 have no transcript.**
  - **Issue**: per-video oEmbed statuses in `reports/shared_host_lookups.csv` (blank channel) cross-checked against the export; the video ids are the 404/403/400 rows in the study's classifier.
  - **Impact**: pages with neither video nor transcript are indexable and offer a reader nothing.
  - **Next action**: product call — `noindex` them, or delete via the existing delete-pages endpoint; the 2 that do have a transcript can stay with the dead-player fix from Ship next.
  - **History**: gov-id enumeration audit, 2026-09-09.

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

- **[NEEDS-AUDIT] A real US government's YouTube video got minted with a Canadian-province gov_id prefix (`rtr:ca:sk:bracken-county-ky-fiscal-court`).**
  - **Issue**: WO-153 (2026-09-10) found page `bracken-county-ky-fiscal-court-sk-2026-09-09-regular-fiscal-court-meeting-septem` — a real Bracken County, Kentucky Fiscal Court meeting, confirmed by its own title and description — minted as `rtr:ca:sk:bracken-county-ky-fiscal-court` (`ca:sk` = Canada/Saskatchewan) instead of resolving to the real national-table id `us:county:21023`. The video is on `www.youtube.com`, and `wo147_access_ladder_sweep` had already written a correctly-formatted `fallback` pin for this exact video (`www.youtube.com,youtube:xC4ICFWd9E4,us:county:21023`) before WO-153 started — that pin hasn't been backfilled yet, which is a separate, ordinary next step (see below), not this bug.
  - **Impact**: at least one real US government minted under the wrong country/province — a correctness bug in the minting path itself, not just this one page. Unknown how many other pages share it; not swept for more instances this session.
  - **Next action**: find where a bare `name, "KY"`-shaped signal (or similar) can produce a `ca:sk:` (or any non-US) prefix in the minting code path and trace why. Then run `backfill_gov_id.py --hosts www.youtube.com` (a broad sweep — scopes in every pending pin from every concurrent session, not just this one; coordinate before running) to re-key this page and the other governments already pinned and waiting.
  - **Constraint**: don't fix by just re-keying this one page — the minting bug that produced the wrong prefix is still live and will do this again.
  - **History**: `BACKLOG_DONE.md` WO-153, 2026-09-10.

- **[NEEDS-AUDIT] `rtr-deeplink`'s SIGABRT crash-loop (status 134) is real and ongoing — 30 occurrences since 2026-08-30, five more in one 23-minute span this morning — but dashboard/log access has hit its ceiling; memory pressure is now ruled out as the driver for the great majority of them.**
  - **Issue**: identical "Exited with status 134" Render alerts, now 30 occurrences since 2026-08-30 16:54 UTC through at least 2026-09-10 18:30 UTC (instance `zdd2t`, 11:30 AM PDT). Root cause is still unconfirmed at the application level — but two live-checked data points narrow it: (1) **the memory graph for both the last 4 hours and the last 14 days shows usage staying well under the `standard` plan's 2GB limit throughout, with exactly one exception already on record** — the 2026-09-01 morning spike (the one outage already correlated with a matching Render alert). Every other crash checked, including today's, happened with memory far from the ceiling — this rules out chronic memory pressure as the driver for the bulk of the crash-loop, leaving a native-extension fault (this app's C-extension deps: aiohttp/uvloop/asyncpg/PyAV) as the more likely explanation for most occurrences, 2026-09-01 aside. (2) **PR #795's `handle_head_requests` Content-Length fix is confirmed deployed** (Ryan verified directly) and confirmed working live — a `HEAD /m/menifee-ca-2026-09-09-planning-commission-meeting` request in a 2026-09-10 pasted log returns a clean `200 OK` with no `RuntimeError`, where the identical request shape crashed the same way in the 2026-09-01 log. That closes off PR #795 as a contributing factor going forward, distinct from (and not the cause of) the SIGABRT itself — the process survived the pre-fix version of that bug every time it was hit, per the 2026-09-01 log showing normal service resuming right after.
  - **Impact**: unchanged in kind from before — a genuine recurring resolver crash-loop, now with the memory-pressure hypothesis substantially weakened rather than confirmed, and today showing the crash-loop can cluster tightly (five separate "Instance failed" alerts between 11:08 AM and 11:31 AM PDT, each followed by "Service recovered," rather than being spread evenly across the day). 2026-09-01 remains the one occurrence where memory did spike; every other occurrence checked (14-day graph, multiple same-day graphs) shows no such spike.
  - **Next action**: app-level and dashboard-level investigation is exhausted — stdout logs never carry the actual abort (confirmed across three separate pasted logs now, 2026-09-01, and two from 2026-09-10, all only showing the post-restart boot sequence: Chromium self-heal install, then normal traffic, then the next restart), and Render's Events tab carries no more specific exit reason than the generic "Exited with status 134." The only remaining avenue is Render's own infra-level crash diagnostics (kernel `dmesg`/OOM-killer output), which isn't self-serve from either the dashboard or this repo's own tooling — would need Render support directly if this is worth pursuing further. Given today's tighter clustering (5 in 23 minutes vs. the ~2.5/day average implied by 30 over 11 days), worth a decision from Ryan: escalate to Render support now, or keep treating it as accepted background noise as long as it keeps auto-recovering within minutes (3 confirmed real UptimeRobot outages against 30 alerts to date). **`PYTHONFAULTHANDLER=1` was added to all four services' `render.yaml` env vars 2026-09-10 specifically to close the "nothing in `app/` shows explicit signal handling" gap** — it dumps every thread's stack to stderr the instant a fatal signal like this one hits, before the process dies. Diagnostic only, not yet deployed (deploys are manual, WO-59) and not yet confirmed to have caught anything — the next real occurrence after deploy is what confirms whether this actually surfaces the cause.
  - **History**: `BACKLOG_DONE.md` ("Four Render-dashboard `[HUMAN]` items walked through live with Ryan," 2026-08-29 — the starter-vs-standard decision this recurrence already revisited, current plan is `standard`/2GB). First flagged by the inbox-triage Routine 2026-08-30; recurred and updated in the 2026-08-31, 2026-09-01, 2026-09-03, 2026-09-05, and 2026-09-10 (two updates same day — a live dashboard walkthrough with Ryan that morning, then five more alerts within the same day) runs/sessions. Moved to "Needs a human" -> `[NEEDS-AUDIT]` 2026-09-10 once the dashboard-only step was done; what's left is either Render-support escalation or accepting it as background noise, not a quick dashboard glance.

- **[NEEDS-AUDIT] `hub_sweep_wo126.Result` only fills `meeting_url`/`video_url` on a success path, so a skipped/no-video row carries no signal to tell "video with no meeting" apart from "meeting with no video."**
  - **Issue**: `act_on_resolved()`'s `_fill()` helper (`scripts/hub_sweep_wo126.py`) is the only place that writes `res.meeting_url`/`res.video_url`, and it only runs when a candidate is actually ingested/queued/already-covered. Every `raise Skip(...)` path (agenda-only, no-video, off-mission) leaves those fields at their dataclass default (`""`).
  - **Impact**: WO-164's three sharper content reject reasons (`meeting-without-video`/`no-meeting-nor-video`/`video-without-meeting`, `wo164_retag_rules.md`) can't be assigned precisely by anything built on `hub_sweep_wo126`'s reused `Result`/`act_on_resolved` — WO-151's own sweep (`scripts/wo151_research_url_ladder_sweep.py`) worked around this with a coarser reason-string-only mapping and reports 0 `video-without-meeting` rows as an honest gap, not a real absence.
  - **Next action**: have `act_on_resolved()` (and its WO-151 override) record `meeting_url`/`video_url`/a candidates-tried count on `res` before raising `Skip`, not only on success, so a future sweep reusing this module can apply WO-164's exact field-based mapping instead of a reason-string approximation.
  - **Constraint**: touch the shared `hub_sweep_wo126.py` copy, not just WO-151's patched override, so every future sweep that reuses it benefits.
  - **History**: found 2026-09-10 building WO-151 (`docs/BREADTH_SWEEP_BRIEF.md`'s access-ladder sweep); see `BACKLOG_DONE.md`'s WO-151 entry.

- **[NEEDS-AUDIT] `scripts/wo151_research_url_ladder_sweep.py`'s headless rung is capped at 150 renders for the whole run — most of the 1,026-government candidate list will exhaust that budget before it's reached.**
  - **Issue**: `HEADLESS_BUDGET = 150` is a whole-run cap, and the pilot showed ~80% of "no-platform-link-found" candidates trigger a headless attempt (25 of 30). At that rate the budget runs out well before the full candidate list is processed.
  - **Impact**: governments processed after the cap is hit get no headless second opinion — `docs/COVERAGE_HANDOVER.md`'s breakthrough #1 found headless recovers a real platform link on ~41% of "no platform" verdicts for JS-rendered navigation, so some real coverage is left on the table for the tail of any run past 150 no-platform-link-found candidates.
  - **Next action**: either raise the budget for a dedicated follow-up pass restricted to `no-platform-link-found` rows from this WO's own report, or measure headless's actual yield on a larger sample before spending more wall-clock time on it (this WO's own 30-row pilot found 0/25 headless renders recovered a link — a small, possibly unrepresentative sample; the larger governments this coverage-registry note was based on may behave differently than the small towns this candidate list skews toward).
  - **Constraint**: one headless browser at a time, real delay — don't parallelize past a single browser without re-checking whether that changes a host's own rate-limiting behavior.
  - **History**: `BACKLOG_DONE.md`'s WO-151 entry has the pilot's exact headless numbers.

- **[NEEDS-AUDIT] `detect_platform()`'s bare-substring match on a vendor
  domain (`"granicus.com" in netloc`, etc.) false-positives on the
  vendor's own marketing/support pages when used to scan arbitrary page
  links, not just to classify an already-known real meeting URL.**
  - **Issue**: confirmed live in WO-147's 30-row pilot: Oceanside, CA's
    page links to `https://www.granicus.com/` (a "Powered by Granicus"
    footer badge) and New Haven, CT's links to
    `support.granicus.com/s/article/...` (a Granicus help-center
    article) — `detect_platform()` returns `"granicus"` for both, since
    its rule is a bare netloc substring test with no tenant-subdomain or
    marketing-subdomain check. `wo134_confirmed_hits_ingest.py`'s
    `find_specific_platform_link()` calls `detect_platform()` the same
    way and has the identical exposure; it just hadn't been hit before
    because every prior sweep already knew its *target* platform ahead
    of time (a marketing link only false-positives when scanning for
    *any* platform, which no caller did before this WO's
    `find_platform_link()` in `scripts/wo147_access_ladder_sweep.py`).
  - **Impact**: a government whose page merely credits a vendor in a
    footer/support link gets misclassified as a live tenant of that
    vendor, wasting a resolve attempt and landing a wrong
    `no-video-found`/`resolve-failed` outcome instead of the correct
    `no-platform-link-found`. Not known to have caused a wrong *ingest*
    yet (the resolve step still fails cleanly on a non-tenant URL), but
    it corrupts the reject-reason signal a later sweep would read.
  - **Next action**: give `detect_platform()` (or a thin wrapper used by
    every *scanning* caller, as opposed to *classifying* an
    already-known URL) the same guard `wo147_access_ladder_sweep.py`'s
    `_is_vendor_marketing_apex()` now has — exclude a bare vendor apex
    domain and its known marketing/support subdomains (`www`, `connect`,
    `support`, `help`, `university`, `go`, `info`, `status`, `docs`,
    `developer(s)`, `blog` — the same set `wo141_access_ladder_pilot.py`
    already validated) before trusting a scanned link as a real tenant.
  - **Constraint**: don't just harden `detect_platform()` itself without
    checking every existing caller's expectations first — some may rely
    on it recognizing a bare vendor URL on purpose (e.g. classifying an
    already-known real Granicus stream URL that happens to be on the
    apex domain, if one exists).
  - **History**: found and worked around locally in
    `scripts/wo147_access_ladder_sweep.py` (`_is_vendor_marketing_apex()`),
    not yet applied to the shared `find_specific_platform_link()`/
    `detect_platform()` path. See `BACKLOG_DONE.md`'s WO-147 entry.
- **[NEEDS-AUDIT] §158's write protocol doesn't catch a same-row-count
  concurrent write to `jurisdiction_coverage.csv`.**
  - **Issue**: every `*_apply_to_jc.py` script (wo146/148/149/150's)
    guards against a stale write with a pre-write re-check that compares
    the file's row COUNT and header fieldnames against what it read at
    the start of its lock hold. Real, confirmed-live collision,
    2026-09-10: WO-150's second apply run (uncommitted at the time) and
    WO-147's own apply run (a different candidate list) both touched the
    file around the same time. WO-147's own read-modify-write cycle
    apparently captured a snapshot that predated WO-150's second run,
    then WO-147 committed that snapshot — silently reverting WO-150's
    uncommitted row updates (Florence city AL, Lake Havasu City AZ, and
    others) even though the row count and fieldnames never changed, so
    the existing re-check never fired.
  - **Impact**: a same-row-count concurrent write from another session
    can silently clobber uncommitted work on this shared file, with no
    error raised by either writer. Recovered here only because WO-150
    diffed the file against its own last commit and noticed values it
    had just written were gone; a less careful session wouldn't catch
    this at all.
  - **Next action**: strengthen the pre-write re-check in the shared
    pattern (ideally factored into one real shared helper, per
    `docs/BREADTH_SWEEP_BRIEF.md`'s own "optional next steps" note) to
    compare a hash of the full file content (or at minimum the exact
    rows each run is about to touch) against what was read at
    lock-acquisition time, not just row count and fieldnames.
  - **Constraint**: committing immediately after every write (already
    the convention) shrinks the collision window but doesn't close it —
    WO-150's own collision happened inside that window, before its
    commit landed.
  - **History**: WO-150, `BACKLOG_DONE.md` 2026-09-10. Recovered by
    re-running `wo150_apply_to_jc.py` fresh against the post-collision
    state and committing immediately; no data was permanently lost.

- **[NEEDS-AUDIT] A minted `rtr:` id's state code can be a false positive
  lifted from an institutional-type word ("School District" → SD,
  "Supreme Court" → SC) rather than a real state abbreviation — confirmed
  on 2 live pages today, structurally able to recur on any of a
  currently-small but nonzero population.**
  - **Issue**: found live 2026-09-04 on two pages — id 757 "Arkansas
    Supreme Court" minted as `rtr:us:sc:arkansas-supreme-court` (looks
    like South Carolina; the real government is in Arkansas), and id
    5218 "Oxnard School District" minted as
    `rtr:us:sd:oxnard-school-district` (looks like South Dakota; the
    real government is in California). Both are the same shape: the
    mint path pulled a trailing two-letter code from inside the raw NAME
    text itself ("...**S**chool **D**istrict", "...**S**upreme **C**ourt"),
    not from an actual trailing state suffix, and nothing currently
    distinguishes that from a real ", SD"/", SC".
  - **Impact — real counts, queried live 2026-09-05, not estimated**:
    of the 6 `rtr:us:sd:*` ids currently minted in production, 5 are
    genuinely real South Dakota places (Brookings, Dell Rapids, Madison
    ×2 pages, Vermillion) and exactly 1 is this bug (Oxnard). Of the 1
    `rtr:us:sc:*` id minted, that 1 is this bug (Arkansas). For scale:
    62 pages are correctly keyed to a real `us:sd:` **school district**
    (the Gazetteer-backed national table, a completely different
    namespace from the 2-letter state code — see
    `GOVERNMENT_IDENTITY_ARCHITECTURE.md`'s "Clarification" in §7), and
    roughly 13 pages carry a real South Carolina government. So today's
    confirmed blast radius is small (2 wrong pages total) — the concern
    is the mechanism, not the current count, since nothing stops a third
    "___ Special District" or "___ Superior Court" from minting the same
    way tomorrow.
  - **Next action**: two tracks, not one.
    1. **Immediate, bounded**: before minting `rtr:us:<st>:...` from a
       cleaned name, check whether the *only* place the candidate state
       code appears is inside an institutional-type phrase in the name
       itself (a short, enumerable list — "school district," "supreme
       court," and whatever else the audit below turns up) rather than
       as a genuine trailing suffix the way `_split_state()` already
       distinguishes elsewhere in this file. A quick scoping count first
       (per Ryan's ask): how many minted `rtr:` ids nationally contain
       "school district" or "supreme court" in their name — this decides
       whether the guard needs to handle 2 known shapes or a longer tail
       worth enumerating up front.
    2. **Structural, for resilience going forward**: study what the
       *tenant URL itself* already reliably carries at resolve time
       (subdomain state suffixes are already proven reliable elsewhere —
       see the sibling entry above on `score_gov_registry.py`'s
       `match`-scoped blind spot and the Municode subdomain-state
       finding from the Abbotsford investigation) and thread that
       through the mint path as a real signal to cross-check a candidate
       state code against, instead of trusting whatever two letters a
       regex finds inside the name. This is the same shape as decision
       D2/§5's existing "a plausible wrong extraction passes validation"
       lesson, just at the minting step instead of the lookup step.
  - **Constraint**: don't fix this by blocklisting "school district" and
    "supreme court" alone and calling it done — that's the immediate
    patch for the 2 confirmed cases, not the structural fix. Verify
    whatever the audit finds before enumerating a "final" list; per this
    repo's own standing rule, a backlog entry's central claim decays
    fast and this one's counts should be re-checked, not assumed, by
    whoever picks it up next.
  - **History**: found 2026-09-04 investigating WO-110's Phase 2d
    scoring report while answering questions about the Abbotsford
    BC/WI fix; counts confirmed live 2026-09-05. Not yet in
    `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] `scripts/tier3_auto_transcription_queue.txt`'s real feasibility has collapsed to ~8%, far below the ~88% the feed script's own docstring still assumes.**
  - **Issue**: fed the first 50 queue rows live 2026-09-07 (all IQM2) —
    only 4 resolved a real video, 46 got `[SKIP] no video found on
    re-resolve`. Verified this isn't an adapter bug: replicated
    `IQM2AssetFinder.resolve()`'s own logic for all 46 skips (same
    `MeetingID` extraction, same derived `SplitView.aspx` fetch) and
    every single one returns a live `SetupJWPlayer(eval('[{"file":"",
    "default":true}]'))` — the government page's own JWPlayer call with
    a genuinely empty file URL — confirmed by direct curl against
    6+ unrelated tenants (boonenc, browardcollegefl, douglascountyco,
    kingslandcityga, franklincountymo, and others). One also showed
    `hfVideo` = `"False"` on its source `Detail_LegiFile.aspx` page.
    Real, current, live fact about these meetings, not a false
    negative.
  - **Impact**: at this hit rate, netting a real batch of N tier-3
    candidates costs ~12.5x N live resolves against many distinct
    government tenants — the remaining ~627-row queue would mostly be
    consumed chasing a fraction of its assumed yield. The feed
    workflow's throughput math (`feed-tier3-transcription.yml`'s own
    comment, and this docstring's 2026-08-22 "~88% feasibility" figure)
    is now stale and overstates real output.
  - **Next action**: none forced yet — this session topped up its local
    Whisper batch from the general `/internal/transcription-backlog`
    instead of continuing to drain this queue. Worth a real fix before
    relying on this queue again: re-probe a larger sample to size the
    true current rate, and figure out whether it's uniform decay (old
    Granicus-backed streams aging out — this repo already documents
    "some old/archived Granicus clips... genuinely time out," see
    `feed_tier3_auto_transcription.py`'s docstring) or a bug in how the
    queue was originally built.
  - **Constraint**: don't re-raise this queue's batch size, and don't
    burn through the rest of it in one sweep, until the real rate is
    known — same "verify a backlog entry's central claim" rule this
    file's own header states.
  - **History**: found 2026-09-07 feeding a manual 50-row batch for a
    local Whisper run (this session).

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

- **[NEEDS-AUDIT] A bare unqualified name that exists in BOTH the
  `us_places` and `us_cousubs` tables in the same state always resolves
  to the place, silently discarding the cousub — mostly correct, but
  wrong for at least 4 real Connecticut towns.**
  - **Issue**: `_general_purpose_lookup()`'s place-vs-cousub tie-break
    (`app/utils/gov_registry/resolver.py`) only runs `if type_preference`
    — a raw name that says "Town of X" or "City of X" is disambiguated
    correctly, but a bare name with no type word skips that block
    entirely, and `_national_lookup()` then returns `place` unconditionally
    whenever it's truthy, never even considering an available `cousub`
    match. Measured directly against the live tables (not assumed):
    **2,373** bare names nationally resolve to exactly one row in *both*
    tables in the same state. The large majority (~2,369, dominated by
    Illinois) are a Midwest platting artifact — a village sits inside a
    same-named township, and "Camp Point, IL"/"Flora, IL" colloquially
    *does* mean the village, so today's place-wins default is actually
    right there. But Connecticut's nested-borough tradition is the
    opposite: `Groton`/`Newtown`/`Stonington`/`Litchfield, CT` are each a
    **Town** (the real, encompassing government, `us:cousub:...`) that
    also contains a much smaller incorporated **city/borough** of the
    same base name (`us:place:...`) — confirmed live,
    `resolve_government("Groton, CT")` returns `us:place:0934180`
    (City of Groton) when the overwhelmingly more likely intended
    government for an unqualified "Groton, CT" meeting is the Town of
    Groton (`us:cousub:0918034250`). `"Town of Groton, CT"` /
    `"City of Groton, CT"` (with the type word) already resolve
    correctly to the two different governments — this is specifically
    the bare-name path.
  - **Impact**: narrow — only the 4 confirmed CT pairs (Litchfield,
    Groton, Stonington, Newtown) are known to be wrong by this today.
    **Checked 2026-09-09 via `GET /internal/export/pages` (6,410 pages):
    zero archived pages exist for any of the 4 under any name variant**
    (no `/j/groton-ct`, `/j/newtown-ct`, `/j/stonington-ct`, or
    `/j/litchfield-ct` hub is live) — so this is not confidently wrong in
    production today, it is a live landmine that will misfire the first
    time one of these four towns' meetings gets ingested with a bare
    (no-type-word) jurisdiction string. No evidence this pattern recurs
    outside CT — RI/MA/other New England states were not checked for the
    same nested-government shape.
  - **Next action**: don't blanket-flip the place-vs-cousub default —
    that would break the ~2,369 correct Illinois-pattern resolutions.
    Needs a name-level or state-level override (e.g. a small curated list
    of "cousub wins over place for this bare name in this state," the
    same mechanism `curated_aliases()` already provides) scoped to the
    confirmed CT pairs, plus a check of whether any archived page is
    currently mis-keyed this way before deciding it's worth a backfill.
  - **Constraint**: verify the RI/MA/ME/NH/VT town rosters for the same
    nested-borough pattern before assuming it's CT-only — this was found
    incidentally while verifying the `us:cousub:` namespace for WO-121
    (New England `us:cousub:` display fix), not from a targeted search.
  - **History**: found 2026-09-06 while verifying
    `GOVERNMENT_IDENTITY_ARCHITECTURE.md`/`COUSUB_REQUIREMENTS.md`'s
    claim that Places and active-government COUSUBs are disjoint by
    construction — they are not; not yet in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] A jurisdiction string with a leading "The " before the
  type phrase (`"The Town of X, ST"`) fails to resolve at all, even
  though `"Town of X, ST"` (same government, no "The") resolves
  correctly.**
  - **Issue**: `resolve_government("The Town of Hooksett, NH")` mints
    `rtr:us:nh:hooksett`; `resolve_government("Town of Hooksett, NH")`
    and `resolve_government("Hooksett, NH")` both correctly return
    `us:cousub:3301337300`. Hooksett is a real, active-government NH
    town, present in `us_cousubs.csv` — the leading article alone is
    what breaks the match. Found nationwide-measuring the `us:cousub:`
    resolver ladder for WO-121; not a New-England-only search, just the
    one real example turned up so far.
  - **Impact**: small but real and live — `hooksett.granicus.com` (2
    archived pages, confirmed via `GET /internal/export/pages`) is
    minted instead of keyed to the real NH town today. Unmeasured how
    many other hosts/pages carry the same "The Town/City/Village of X"
    phrasing.
  - **Next action**: find where the raw name is stripped of its type
    phrase (`resolver.py`'s name-normalization path) and confirm whether
    a leading "The " is handled there at all before deciding the fix —
    don't blindly strip every leading "The": at least one real
    government (`The Woodlands, TX`) legitimately keeps "The" as part of
    its common name, so the fix needs to distinguish "The" as an article
    in front of a type phrase from "The" as the first word of the name
    itself.
  - **Constraint**: verify the fix against both directions before
    landing — `"The Town of Hooksett, NH"` must resolve, and a genuine
    "The"-prefixed place name must not get mangled.
  - **History**: found 2026-09-09 while running `scripts/
    score_gov_registry.py` for the WO-121 `hub_slug_aliases.csv` regen;
    not yet in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] 16 real municipalities nationwide have a compound
  Census LSAD ("X Town city") that the resolver's type-word stripper
  can't parse, so none of them resolve by name at all.**
  - **Issue**: `us_places.csv` stores these as e.g. `"West Springfield
    Town city, MA"`, `"Agawam Town city, MA"`, `"Old Town city, ME"`,
    `"Charles Town city, WV"` — Census's LSAD for a Massachusetts-style
    town that is legally a "city" for some purposes appends TWO words
    ("Town city"), not one. `_census_type_word()`
    (`app/utils/gov_registry/resolver.py`) strips only the single
    trailing word, so `"West Springfield Town city"` normalizes to
    `"west springfield town"`, which matches neither `"West Springfield"`
    nor `"Town of West Springfield"`. Confirmed live:
    `resolve_government("West Springfield, MA")` and
    `resolve_government("Town of West Springfield, MA")` both mint
    `rtr:us:ma:west-springfield` instead of finding the real place row.
    Full list of the 16 affected (`grep "Town city," us_places.csv`):
    14 in MA (Agawam, Amherst, Barnstable, Braintree, Bridgewater,
    Franklin, North Attleborough, Palmer, Randolph, Southbridge, West
    Springfield, Weymouth, Winthrop) plus Old Town, ME; New Town, ND;
    Charles Town, WV.
  - **Impact**: small but real and live — `westspringfieldma.granicus.com`
    (2 archived pages, confirmed via `GET /internal/export/pages`) is
    minted instead of keyed to the real place today. The other 15 are
    unmeasured for archived-page impact.
  - **Next action**: teach `_census_type_word()` (or wherever the
    normalized lookup key is built) to recognize "Town city" as a single
    two-word LSAD phrase, the same way it already has to special-case
    other multi-word LSADs if any exist — check `us_places.csv`'s
    `lsad`/`funcstat` build script (`scripts/build_gov_registry_data.py`)
    for whether the LSAD code itself (not just the rendered name) is
    available to key off instead of pattern-matching the name string.
  - **History**: found 2026-09-09 while running `scripts/
    score_gov_registry.py` for the WO-121 `hub_slug_aliases.csv` regen;
    not yet in `BACKLOG_DONE.md`.

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
    the (negative, expected) result. Three more real cases, each settled
    by Ryan with an `authoritative` pin rather than a ladder change
    (`BACKLOG_DONE.md` 2026-09-10): `townofchenango.civicweb.net` (town
    page resolved to the county), `kankakeecountyil.gov` and
    `mcleancountyil.gov` (county pages resolved to the same-named city
    and village). In all three the tenant is the government's own domain
    and the page text names a real neighbouring government — the shape a
    ladder fix would have to recognise, if one is ever built.

- **[NEEDS-AUDIT] Wrong-government-content pattern confirmed on 6 live
  pages (not just the 1 Gloucester case above) -- a shared multi-
  government tenant's "pick something recent" candidate logic has no
  signal that distinguishes a school board from the city/county/town
  body sharing the same channel.**
  - **Issue**: found during a manual title-check audit of the school-
    district enumeration effort (`rtr-business/research/
    ENUMERATION_METHODS.md` §63), not assumed -- every one of these
    resolved through a real per-tenant listing/candidate-pick step, to a
    real, current meeting, on the correct platform, for the **wrong**
    government:
    - Canton City, OH (Cablecast) -> "The Poetry Room with Corey Lipkins
      Jr, Episode 7" -- a talk show, not a meeting at all.
      `/m/2026-08-03-the-poetry-room-with-corey-lipkins-jr-episode-7-the-return`
    - Champaign CUSD 4, IL (Cablecast) -> a real City Plan Commission
      meeting. `/m/2026-09-02-plan-commission-9-2-26`
    - Gloucester County Public Schools, VA (eScribe) -> a real County
      Planning Commission meeting (separate live page from the WO-106
      entry above, same underlying name-bleed root cause -- also mistagged
      jurisdiction as Gloucester, **MA**).
      `/m/gloucester-ma-2026-09-03-planning-commission`
    - Brookline, MA (CivicClerk) -> the **Town's** "Indigenous Peoples
      Celebration Committee," not a school committee.
      `/m/brookline-town-ma-2026-09-04-indigenous-peoples-celebration-committee-meeting`
    - Park County, MT (Granicus) -> the **County's** "Solid Waste
      Board." `/m/park-county-2026-08-20-solid-waste-board-8-20-2026`
    - Brooklyn School District, CT (CivicClerk) -> the **Town's**
      "Planning & Zoning Commission."
      `/m/brooklyn-town-ct-2026-09-02-planning-zoning-commission-meeting`
  - **Not yet checked**: title-checking only happened for the ~26 pages
    this specific school-district effort touched, not this Archive's
    full corpus of shared-tenant ingests generally -- this pattern is
    very likely present elsewhere (any Cablecast/CivicClerk/eScribe
    tenant shared across multiple governments), just not audited yet.
  - **Update 2026-09-06, corrected**: 2 of 3 candidates originally
    believed "caught before going live" (removed from
    `scripts/tier3_auto_transcription_queue.txt` on the same audit pass)
    really were caught in time -- Niagara Falls City SD, NY (Cablecast,
    would-have resolved to "Mayor Restaino Weekly Update," a general PR
    video) and St. Lucie, FL (Cablecast, a bare live-channel URL with no
    title/date/jurisdiction) never made it into any live page, confirmed
    by a full scan of all 5,399 pages in `/internal/export/pages` for
    their exact source URLs -- zero matches. **The third one was wrong:
    Prince George's County Public Schools, MD's `pgcps.cablecast.tv`
    tenant was already live, twice, before this session's own (never
    pushed/committed) queue-file edit could matter at all** --
    `/m/2026-03-03-student-built-tinyhome` and a duplicate
    `/m/2026-03-03-student-built-tinyhome-7c70cf` (same show,
    `?site=1` query-string difference on the source URL creating a
    second row -- a real, separate URL-normalization gap, not
    investigated further here), both "Student Built TinyHome," not a
    meeting. Neither came from anything in this session's own pipeline
    runs; almost certainly a separate, concurrent effort (the wildcard-
    sweep work, WO-115/116/117) independently swept the same
    `pgcps.cablecast.tv` tenant and hit the identical "pick something
    recent off a shared channel" failure mode. **A third pgcps page was
    found the same way, never flagged by this session's own pipeline at
    all**: `/m/2024-09-06-newsbreak-school-house-justice`, "Newsbreak:
    School House Justice" -- also clearly not a board meeting. All 3
    pgcps.cablecast.tv pages need the same takedown as the 6 above,
    total 9, not 6.
  - **Likely related, not yet confirmed as the same bug**: `jurisdiction`
    resolved to `None` (not wrong, just entirely missing) for 3 more of
    the same effort's pages -- Andover, MA (CivicPlus/castus.tv), Duval,
    FL (CivicClerk, `duvalcosb.portal.civicclerk.com` -- subdomain
    strongly suggests "Duval County School Board," a dedicated tenant,
    so likely correct content just missing the tag), and East Brunswick
    Township, NJ (NovusAgenda, where title/date also both came back
    `None` -- possibly not a real per-meeting page at all, unconfirmed).
  - **Next action**: not attempted here, per this project's
    established "flag it, don't touch code" pattern for jurisdiction/
    government-identity bugs -- these need the same kind of
    per-candidate discriminator (title/body-name keyword match against
    the expected government type) that `GOVERNMENT_IDENTITY_ARCHITECTURE
    .md` §4/§5 already discusses for the single-tenant case, generalized
    to reject a candidate outright rather than just mis-tag its
    jurisdiction. **Update 2026-09-07: all 9 wrong-content pages deleted**
    via `POST /internal/admin/delete-pages?dry_run=false` (`"deleted":9`,
    all 9 `found`, none `not_found`), after the FK-violation 500 fix
    (PR #751) deployed to `rtr-deeplink-archive` (confirmed live,
    `dep-daf2qu2d0e5s73aigg30`, commit `441388fd1c`, which includes
    `ed59dfa`). The underlying picker bug that produced these 9 pages is
    still open -- nothing above prevents a future enumeration pass from
    hitting the same shared-tenant/no-discriminator failure again.
  - **Priority: HIGH.** Confirmed by two independent audits (this one and
    the full-corpus screen below) to be a real, repeating failure mode,
    not a one-off -- every cleanup so far has been reactive (delete after
    the fact), and nothing stops the next enumeration pass from
    reproducing it. The per-candidate discriminator described in **Next
    action** above is the actual fix; flagged 2026-09-09 as the highest-
    leverage item on this whole list.

- **[NEEDS-AUDIT] Full-corpus screen (5,857 pages) found the same
  wrong-content pattern at much larger scale than the 9-page school-
  district batch, plus a second, distinct pattern: school-district
  meetings tagged to the wrong KIND of government, not just the wrong
  meeting.**
  - **Issue**: a title/jurisdiction/`gov_type` heuristic screen (see
    `rtr-business/research/archive_audit/AUDIT_REPORT.md` for full
    method and every category) flagged 414 of 5,857 live pages (7.1%).
    Of those, **16 are the same kind of bug as the entry above** --
    non-meeting content (talk shows, a Granicus vendor-conference video
    self-tagged with a fake "jurisdiction", 8 Legistar/CivicClerk staff
    admin-*training* videos ingested as if they were public meetings) --
    and **23 more are a real, independently-named school district
    (DJUSD, AUSD, Hopkins School District, etc.) tagged to the city/
    township it happens to be colocated with** (e.g. "DJUSD Board of
    Education" tagged `jurisdiction=Davis, CA, gov_type=municipality`
    instead of the actual school district) -- a re-tag fix, not a
    delete, since the meeting itself is real and correctly identified,
    just attached to the wrong government record.
  - **Real, material uncertainty, not yet resolved**: a further 13
    "county"-tagged school-board pages could not be classified with
    confidence -- several states (Florida, some Virginia divisions) run
    school districts genuinely coterminous with the county, so "county"
    may already be correct there; needs state-by-state research, not a
    blanket rule. Separately, 305 pages were flagged only by "no
    meeting-shaped keyword in the title," and a 50-item random sample
    of that bucket suggests it's a real mixed bag (~20-30% genuine
    non-meeting content -- PR videos, ceremonies, mayoral video blogs --
    the rest a mix of a regex limitation on plurals and a judgment call
    about whether ceremonial/civic content like State-of-the-City
    addresses is in scope at all) -- none of the 305 were individually
    re-verified. **Priority: HIGH** on finishing this specific bucket --
    the 50-item sample's ~20-30% hit rate on real non-meeting content,
    projected across all 305, implies real live junk this audit hasn't
    found yet; flagged 2026-09-09 as the other top-priority item
    alongside the discriminator fix above, not because the fix is hard
    but because nobody has looked at the other ~255 rows yet.
  - **Update 2026-09-08: the 16 non-meeting-content pages are deleted**
    (`"deleted":16`, all 16 `found`, none `not_found`, confirmed via the
    same `POST /internal/admin/delete-pages` treatment as the original 9).
  - **Impact**: 25 of the original 9+16=25 wrong-content pages found by
    this audit effort are now gone. The 23 wrong-government-*type* pages
    (real meetings, wrong government record) are still live and untouched
    -- these are a re-tag, not a delete. The real school districts behind
    them (15 distinct ones) were added to `rtr-business/research/
    master_open_candidates_deduped.csv` as their own tracked government
    units (`us:sd:` gov_ids, real NCES LEA IDs) so they don't get lost as
    open work.
  - **Next action**: the 23 wrong-government-type pages need either 23
    individual `POST /internal/jurisdiction/override` calls or a new
    bulk endpoint -- no bulk re-tag tool exists today. **Priority: LOW
    (trivial)** -- the content is already correct and live, this is a
    metadata correction with no user-facing urgency; flagged 2026-09-09.
    The 13 state-specific-review rows are similarly **Priority: LOW
    (trivial)** -- small count, needs desk research (state school-
    governance structure) more than engineering time. Both left to Ryan,
    not made unilaterally.
  - **History**: full per-category CSVs in `rtr-business/research/
    archive_audit/categorized/`; raw export in `all_pages_raw.jsonl`.

- **[NEEDS-AUDIT] Same source URL, different query string, two
  `MeetingPage` rows -- a real URL-normalization gap.**
  - **Issue**: Prince George's County Public Schools' "Student Built
    TinyHome" got ingested twice as two separate live pages
    (`/m/2026-03-03-student-built-tinyhome` and a duplicate
    `/m/2026-03-03-student-built-tinyhome-7c70cf`) from the same
    underlying Cablecast show, `pgcps.cablecast.tv/show/3178` vs
    `pgcps.cablecast.tv/show/3178?site=1` -- `normalize_url()` doesn't
    treat these as the same source, so the dedupe-by-source-URL path
    never catches it. Confirmed live 2026-09-06 while auditing the
    wrong-government-content pages above; both copies were deleted along
    with the rest of that batch, not investigated at the code level.
  - **Impact**: unknown how many more duplicate pairs exist across the
    corpus from the same class of query-string variation -- not
    scanned for.
  - **Next action**: none yet. **Priority: LOW (trivial)** -- a real
    gap, but low-frequency (this is the only confirmed instance) and
    each occurrence is cosmetic (a duplicate page, not wrong content)
    rather than user-facing-broken; flagged 2026-09-09.
  - **History**: found via `rtr-business/research/archive_audit/`'s
    full-corpus screen entry above.

- **[NEEDS-AUDIT] Three pages from the school-district audit resolved
  with `jurisdiction=None` entirely -- missing, not wrong.**
  - **Issue**: Andover, MA (CivicPlus/`cloud.castus.tv`), Duval, FL
    (CivicClerk, `duvalcosb.portal.civicclerk.com` -- subdomain strongly
    suggests "Duval County School Board," a dedicated tenant, so likely
    correct content just missing the tag), and East Brunswick Township,
    NJ (NovusAgenda, where title/date also both came back `None` --
    possibly not a real per-meeting page at all, unconfirmed) all
    resolved with no jurisdiction attached at all. Confirmed live
    2026-09-06/07 while re-resolving candidates for the school-district
    enumeration effort; not root-caused at the code level.
  - **Impact**: 3 confirmed instances; likely related to the same class
    of gap as the wrong-government-type pattern above (a tenant/platform
    the jurisdiction-enrichment pipeline doesn't have a rule for) but not
    confirmed as the same root cause.
  - **Next action**: none yet. **Priority: LOW (trivial)** -- 3 known
    instances, no user-facing harm beyond a missing metadata field;
    flagged 2026-09-09.
  - **History**: `rtr-business/research/ENUMERATION_METHODS.md` §63
    Round 7.

- **[LATER] GovDelivery -- a proposed discovery lead for finding new
  jurisdictions, never tried.**
  - **Issue**: GovDelivery is a real government email/SMS notification
    platform (`public.govdelivery.com/accounts/{ACCOUNT}/subscriber/new`)
    whose subscription pages could plausibly be enumerated the same way
    Legistar/Granicus hostnames were, and whose notices sometimes carry a
    direct meeting/agenda link -- a lead, not a built method.
  - **Impact**: none yet -- speculative, no candidate hosts collected.
  - **Next action**: none planned; full writeup with the open questions
    (does GovDelivery reliably link to a real meeting/agenda, or mostly
    generic announcements?) already lives in the History link below --
    start there before building anything. **Priority: LOW** -- proposed
    only, no evidence yet it's worth the enumeration effort.
  - **History**: `rtr-business/research/ENUMERATION_METHODS.md` §60,
    full detail and the "subscribe forward" idea.

- **[LATER] Two real, scoped enumerator/adapter gaps found chasing the
  school-district effort's remaining 45 leads -- CivicLive and a 4th
  Cablecast template.**
  - **Issue**: **CivicLive** (Conway School District, WA) -- no
    enumerator exists in `rtr-discovery`, but `rtr-deeplink` already has
    a real, resolvable `app/platforms/civiclive.py` adapter, so unlike a
    platform with no adapter at all, this genuinely just needs a
    `discovery/enumerators/civiclive.py` written -- no prior art to
    reuse. **Cablecast FrontDoor template** (Midland Public Schools, MI;
    Sioux Falls School District 49-5, SD) -- both fail `rtr-discovery`'s
    `CablecastEnumerator` with "no `__remixContext` found -- unsupported
    template," a real 4th Cablecast template (`cablecast.py` already
    documents 3: Remix, CablecastPublicSite/Ember, and the universal
    `cablecastapi` backend underneath both) not yet supported.
  - **Impact**: 3 known school districts blocked (1 CivicLive, 2
    Cablecast FrontDoor) -- likely not the only ones, since these are
    real platform-coverage gaps, not per-tenant issues.
  - **Next action**: CivicLive needs a new enumerator, no prior art.
    Cablecast FrontDoor needs `cablecast.py` extended to detect and
    handle the new template, following the same pattern as the
    CablecastPublicSite addition -- check the real raw HTML/API for one
    of the two known tenants first, per this project's own house rule,
    before writing anything. **Priority: LOW** -- 3 known-blocked
    districts, real but small.
  - **History**: `~/Documents/rtr-discovery/
    SCHOOL_DISTRICT_ENUMERATION_HANDOVER.md` Group 3;
    `rtr-business/research/ENUMERATION_METHODS.md` §63.

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
    `BACKLOG_DONE.md`, this is the first record of it. Second confirmed
    instance, cross-platform this time: Tompkins County, NY's real
    2025-03-18 Legislature meeting was ingested once via its Granicus URL
    and once via its Legistar URL (2026-09-06, wildcard-sweep retry
    pass), producing two separate pages for the identical meeting —
    same root cause, dedup keys on source URL rather than resolved
    identity.

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
    dedicated search pass before concluding either way. Further
    confirmation, 2026-09-08 (Utah PMN pilot, `rtr-business/research/
    ENUMERATION_METHODS.md` §105): 4 more real `zoom.us` "Audio File
    Location" values turned up unprompted in a 2,581-notice statewide
    scan (`us02web.zoom.us` x3, `utah-gov.zoom.us` x1) — not yet checked
    whether any are `rec/share`-shaped past recordings vs. live join
    links, but a second, independent discovery channel surfacing Zoom
    unprompted raises this past "three hits in one evening."
  - **Impact**: unknown real scope, but not zero — three independent real
    hits in one evening's research on an unrelated task, plus at least
    one confirmed real ingestible-shaped example (Rockport MA/Zoom), plus
    4 more real sightings from an unrelated statewide Utah scan. Any
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

- **[NEEDS-AUDIT] No adapter for a PMN "Audio File Location" pointing at
  a general-purpose file host (Google Drive, SoundCloud) — 28 real,
  confirmed-populated examples from one Utah scan.**
  - **Issue**: `utah_pmn.py` (see `BACKLOG_DONE.md`'s entry on that
    adapter) resolves a same-domain uploaded file directly, but a
    populated "Audio File Location" pointing to `drive.google.com` (21
    real examples) or `soundcloud.com` (7) isn't a directly-fetchable
    media URL the way a bare `utah.gov/pmn/files/*` file is — a Drive
    share link needs its own redirect-chain/direct-download investigation
    first.
  - **Impact**: 28 real, confirmed-populated links currently unresolvable
    — a small slice on their own, but the same pattern ("just put the
    recording on Drive") is plausible nationwide for
    smallest/least-resourced governments generally, not just Utah's PMN
    notices specifically.
  - **Next action**: per this project's own rule against building an
    adapter without a live sample, fetch a handful of the real Drive/
    SoundCloud links logged in `rtr-business/research/
    pmn_utah_pilot_log.csv` (`skipped` outcome, reason containing "isn't
    on a known video/audio platform") to confirm they're actually
    fetchable server-side (Drive's sharing-link redirect chain,
    direct-download vs. preview-only gating) before writing anything.
  - **Constraint**: don't assume every Drive/SoundCloud link is a full
    meeting recording without checking — a "Public Information Handout"
    or similar could plausibly also live on Drive.
  - **History**: found 2026-09-08 running the Utah PMN pilot; the
    same-domain-file half of this entry shipped 2026-09-09, see
    `BACKLOG_DONE.md`.

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

### `YouTubeAssetFinder.extract_video_id()`'s regex matches YouTube's own special-purpose embed tokens as if they were real video ids `[NEEDS-AUDIT]`

- **Issue**: WO-135 (2026-09-09) probing yt-dlp against all 96 real
  no-transcript YouTube Archive pages found 3 whose stored `video_url`
  isn't a real 11-character video id at all: `bamberg-county-sc-livestream`
  (`youtube.com/embed/live_stream` — YouTube's "this channel's current
  livestream" embed shortcut), `daviess-county-ky-fiscal-court-...`
  (`youtube.com/embed/videoseries` — a whole-playlist embed, no single
  video), and `mount-vernon-tx` (source URL
  `youtube.com/embed/livestreaming?rel=0` — `_VIDEO_ID_RE`'s
  `{11}`-character regex truncates this to the nonsense id
  `livestreami`, since `live_stream`/`videoseries` are exactly 11
  characters and `livestreaming` is 13). yt-dlp naturally raises "This
  video is unavailable" against each fake id, which the WO-135 permanent-
  failure classifier would otherwise mark `YouTube: video is unavailable
  (removed or private)` — technically true in effect but wrong about why,
  so these 3 were deliberately excluded from that backfill rather than
  mismarked.
- **Impact**: 3 real pages whose actual video (or channel livestream) is
  genuinely reachable never get a transcript, because nothing here can
  resolve a real single video from a live-stream/playlist embed shape.
  Likely not limited to these 3 — any jurisdiction whose government
  channel embeds `live_stream`/`videoseries` directly (rather than a
  specific archived video) would hit the same bug.
- **Next action**: decide the right resolution for each shape —
  `embed/live_stream` needs the channel's *current* live video id (a
  different yt-dlp/API call than a fixed video id), `embed/videoseries`
  needs the playlist's most relevant real video, and `_VIDEO_ID_RE`
  should stop matching a truncated prefix of a longer non-id token in the
  first place (e.g. require a word boundary or exact-length match rather
  than a bare `{11}` capture).
- **Constraint**: don't guess which real video these should point to —
  verify against the real channel/playlist first, per CLAUDE.md's "test
  against a real, live URL first" rule.
- **History**: found 2026-09-09 building WO-135's captions/embed/
  video-unavailable markers (`BACKLOG_DONE.md`).

### 6 `best_effort` YouTube pages archived a promotional/off-topic video instead of the real meeting `[NEEDS-AUDIT]`

- **Issue**: while building WO-136's local-transcription candidate list
  (2026-09-09), 6 of 91 YouTube-no-transcript pages turned out to hold a
  video that plainly isn't the claimed meeting: "Welcome to Crowley
  County!" (`/m/crowley-county-co-2025-09-08-welcome-to-crowley-county`),
  "Greenwood County, Kansas" (generic channel intro, no meeting-shaped
  title at all), "VFW Appreciation 2025"
  (`/m/athens-county-oh-2025-09-23-vfw-appreciation-2025`),
  "HugeDomains.com - Location Matters" (a domain-parking sales video, on
  a page whose own source URL is `hugedomains.com/domain_profile.cfm`),
  "Welcome to Rolling Meadows 2019", and "Drone footage over New Haven,
  Indiana". All 6 are `best_effort_resolve=yes` (generic_fallback) and
  all 6 resolved from a generic government homepage or an
  `.../AgendaCenter` root, not a specific meeting's own page.
- **Impact**: 6 live pages misrepresent a promotional/unrelated video as
  a named government meeting on a specific date; excluded from WO-136's
  transcription run for exactly this reason (transcribing a drone video
  or a domain-parking pitch is not this product's job). Likely a larger,
  uncounted population — this is only the slice inside one 91-page study.
- **Next action**: decide a real signal generic_fallback's video-guessing
  path (`app/platforms/generic_fallback.py`) could check before attaching
  a homepage's YouTube embed as *the* meeting video — e.g. an implausible
  duration for the claimed meeting type, or the video's own title/
  description having no meeting-shaped words at all. Until then, these 6
  pages want a manual look (unpublish or re-point at a real recording if
  one exists).
- **History**: WO-136, 2026-09-09 (`BACKLOG_DONE.md`).

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

### `transcribe_backlog_locally.py`'s new yt-dlp audio download also hits YouTube's anti-bot check after ~3 real downloads, not just the caption endpoint `[WAIT]`

- **Issue**: WO-136 (2026-09-09) added a yt-dlp audio-download path for
  YouTube meetings with no captions, on the premise (documented in
  `_yt_dlp_download_best_audio()`'s own docstring) that it's a
  "genuinely different request shape" from the caption-fetch endpoint
  that's separately 429-blocked (`docs/investigations/
  youtube_429_block.md`) — true for one isolated test download, but not
  for sustained use: a real unattended `--urls-file` run against 17
  candidates succeeded on the first 3 (952/3/2,631 real segments, all
  live) over ~44 minutes, then every one of the remaining 14 failed
  immediately with yt-dlp's `Sign in to confirm you're not a bot.`
  message — the same anti-bot check that hit Render's server IP in the
  original 2026-08-09 incident, now hit from a residential Mac.
- **Impact**: 14 of the 17 WO-136 candidates never got a real download
  attempt; the local-transcription path for YouTube is not yet reliable
  for a batch bigger than a handful of meetings in one run.
- **Next action**: after some idle time (untested how much), retry the
  14 skipped meetings with `--urls-file` narrowed to just them (their
  URLs are the `SKIPPED` lines in `/tmp/wo136_transcribe_run.log` /
  this entry's own History) one at a time, watching for how many succeed
  before the check reappears — that's the measurement neither this run
  nor the caption-fetch investigation has: does it clear, and after how
  long/how many successful downloads.
- **Constraint**: don't re-run a bulk sweep to test this — same standing
  rule as the caption-fetch block; one isolated retry is the right probe.
- **History**: `docs/investigations/youtube_429_block.md`'s new
  2026-09-09 section has the full write-up; `BACKLOG_DONE.md`'s WO-136
  entry has the real funnel numbers.

### 63 identity-checked pages still need a YouTube-transcript fetch — blocked mid-run by a real IP block signature `[WAIT]`

- **Issue**: WO-131 (2026-09-09) built the identity-checked YouTube
  transcript-fetch list per Ryan's criteria (national-table `gov_id`,
  `names_match` in yes/stale form/state missing, minus one page found to
  be mis-keyed — see the Trust & data quality entry above) — 78 good
  candidates. A real (non-dry-run) push attempt against them got through
  15 pages (all genuine per-video failures: `TranscriptsDisabled` x8,
  `VideoUnplayable` x4, `VideoUnavailable` x3 — disabled captions,
  private, live-not-yet-started, or deleted videos, not YouTube-side
  blocking) before the 16th page hit a real `IpBlocked` signature, which
  survived both of `fetch_youtube_transcripts.py`'s built-in backoff
  retries (30s, 120s) — see `docs/investigations/youtube_429_block.md`.
  Per that script's own design, the whole run then aborted rather than
  continuing to poll. 0 transcripts were pushed. WO-135 (same day) closed
  the *reason* this kept happening every day: those 15 (and every other
  page hitting the same 3 exception types) now get a permanent marker
  (`YouTube: captions are disabled by the channel` /
  `YouTube: video is unavailable (removed or private)`) recorded on the
  page and are never re-queued again — see `BACKLOG_DONE.md`. What's
  still open here is narrower: the IP-block cooldown itself, which no
  code change can skip.
- **Impact**: once WO-135 is deployed, only genuinely-untried or
  genuinely-transient (scheduled-but-not-live) candidates keep re-
  appearing in the queue — the 15 known-permanent failures drop out on
  the next run. The remaining wait is for the block to clear before the
  62-never-attempted (plus the one that hit the block) can even be tried.
- **Next action**: after WO-135 is merged **and deployed** (deploys are
  manual — check before assuming this landed), from this Mac run
  `python scripts/fetch_youtube_transcripts.py` with no `--slugs-file` at
  all once a real cooldown has passed (hours, not minutes — no reliable
  duration is known; see the investigation doc) — the daily script's own
  `/internal/transcript-wanted` queue now excludes the 15 automatically,
  so the old corrected-slug-list workaround is no longer needed.
- **Constraint**: don't run a bulk sweep just to test whether the block
  has cleared — a single isolated fetch is enough signal, per the
  investigation doc.
- **History**: WO-131, WO-135, `BACKLOG_DONE.md`.

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

- **`[NEEDS-AUDIT]` A real "Hermantown" (city ending in "-town" as part of its own proper name) resolved live to a different, much smaller "Herman Town" government.**
  - **Issue**: WO-148 ingested a real CivicClerk page for Hermantown city, MN (`hermantownmn.portal.civicclerk.com`, 2,174 real transcript segments, a genuine city council meeting) — but the archived page keyed to `us:place:2728646` ("Herman Town, MN"), a different, much smaller township, not Hermantown's own `us:place:2728682`. The page's own slug and stored jurisdiction both read "Herman Town, MN". Looks like the same shape as the already-fixed "city and borough"/"urban county" stripping bugs (`BACKLOG_DONE.md`, 2026-09-10 consolidated-governments entry) — something on the jurisdiction-extraction path is treating the trailing "town" in "Hermantown" as a government-type suffix to strip, turning the proper name "Hermantown" into "Herman" + "Town".
  - **Impact**: at least one live, real page misattributed to the wrong (and much smaller) government; the failure mode is name-shape-general (any real place name ending in "town", "city", "burg", etc. as part of the proper noun rather than a suffix) so likely more than one instance nationwide.
  - **Next action**: find the exact regex/strip step (start with `jurisdiction_enrich.py`'s type-suffix stripping, per CLAUDE.md's `_GOVERNMENT_TYPE_RE` note) and check it against a real name/place lookup before stripping a trailing type word — a "Hermantown, MN" registry entry existing should block treating "town" as a strippable suffix here.
  - **Constraint**: fix the extraction rule, not this one page by hand — the page itself needs a `POST /internal/jurisdiction/override` once the root cause is confirmed.
  - **History**: found and confirmed by hand (fresh-export lookup matching the archived page's real `gov_id` against WO-148's candidate list), 2026-09-10; see `BACKLOG_DONE.md`'s WO-148 entry.

- **`[NEEDS-AUDIT]` A real, resolvable Albion, MI civicweb page archived with a blank `gov_id` and an unformatted stored jurisdiction ("City of Albion", no state).**
  - **Issue**: WO-148 ingested a real CivicWeb page for Albion city, MI (`cialbionmius.civicweb.net`, 1,177 real transcript segments, a genuine city council meeting) — the page carries no `gov_id` at all (`names_match: no gov_id` in the meeting-inventory export) and its stored jurisdiction is the raw, un-normalized "City of Albion" rather than "Albion, MI". Several US states have a real Albion (MI, NY, NE, IN, PA, CA, WA, ...), so this may be the "exactly-one-rule declined, real ambiguity" case `COVERAGE_HANDOVER.md` §3 describes, or a genuine adapter/jurisdiction-extraction gap that never reached a state signal at all.
  - **Impact**: one real page with no identity, invisible to any `gov_id`-keyed report or dashboard.
  - **Next action**: check what the CivicWeb source page/tenant actually names as its state (a footer address, a Michigan-specific keyword) — if a state signal exists on the page and was simply never read, that's a real extraction gap; if none exists, this is a genuine ambiguous-name case for a human, same as the ~87 already flagged in the research file.
  - **History**: found and confirmed by hand (fresh-export lookup), 2026-09-10; see `BACKLOG_DONE.md`'s WO-148 entry.

- **`[NEEDS-AUDIT]` `[EXAMPLE]` The county-form name of a fully consolidated city-county ("Philadelphia County, PA", "San Francisco County, CA", "Denver County, CO") would key to the county row and open a second hub for one government.**
  - **Issue**: the ladder's county branch answers a county-typed name before any curated alias is consulted (by design -- "Boise County, ID" must not become the city), so an alias on the place row cannot collapse the county form. The 2026-09-10 consolidated-government audit found **no** archived page carrying such a form yet, which is why this is filed rather than built.
  - **Next action**: when a real page does, add a curated row that makes the county id itself resolve to the place id (or the reverse where the county id is the canonical one -- Honolulu, Terrebonne, Macon-Bibb's county neighbours), rather than widening alias precedence.
  - **History**: audit in `BACKLOG_DONE.md` ("Consolidated governments"), 2026-09-10.

- **`[JUST-DO-IT]` `[EASY]` "Charter Township of X" keys to the village or city of the same name: `_LEADING_TYPE_RE` knows "Township of" but not "Charter Township of".**
  - **Issue**: `resolve_government("Charter Township of Shelby, MI")` → `us:place:2672840` (Shelby *village*, Oceana County), while "Shelby Charter Township, MI" → `us:cousub:2609972820` correctly. `resolver.py`'s `_LEADING_TYPE_RE` lists `city|town|village|borough|township|…` without the `(?:charter\s+)?` prefix that `_TRAILING_TYPE_RE` and `_TRAILING_PAREN_TYPE_RE` already allow, so no township preference reaches the lookup and the place wins the tie. Michigan has ~130 charter townships and their IQM2/CivicClerk portals title themselves exactly this way.
  - **Impact**: `shelbytownmi.iqm2.com`'s two pages were minted `rtr:us:mi:shelby-village` from this; every charter-township tenant will repeat it.
  - **Next action**: add `(?:charter\s+)?` before `township` in `_LEADING_TYPE_RE` and a test with the Shelby pair. The page fix is in the `[HUMAN]` entry under Needs a human.
  - **History**: found by WO-125's landing-page check, 2026-09-09.

- **`[JUST-DO-IT]` `[EASY]` A literal HTML entity in a stored jurisdiction (`Kaua&apos;i County, HI`) is never unescaped, so the county lookup fails on an apostrophe.**
  - **Issue**: `kauai.granicus.com`'s two pages store `Kaua&apos;i County, HI` verbatim; `resolve_government()` on it is `unresolved` ("no 'Kaua&apos;i County' in HI"), while `Kaua'i County, HI` and `Kauai County, HI` both key to `us:county:15007` — `tables.lookup_keys()` already strips the ʻokina, it's only the entity that defeats it. Nothing on the path calls `html.unescape()`.
  - **Impact**: two pages sat on `/j/kaua-apos-i-county-hi` until WO-125 pinned the host; any adapter that passes an entity-encoded title through (Granicus RSS titles do) will repeat it.
  - **Next action**: `html.unescape()` the raw name at the top of the ladder (or in `finalize_jurisdiction()`), a test on the Kauaʻi string, and store the unescaped form at ingest.
  - **History**: WO-125, 2026-09-09; the `kaua-apos-i-county-hi` → `kauai-county-hi` alias is already in `hub_slug_aliases.csv`.

- **`[JUST-DO-IT]` `[EASY]` Census LSAD "corporation" is neither stripped on lookup nor on display: "Ranson, WV" mints, and the registry renders "Ranson corporation, WV".**
  - **Issue**: `us_places.csv` spells West Virginia's Ranson as "Ranson corporation" — the only row in the table with that LSAD (`grep -c ' corporation,'` = 1). `resolve_government("Ranson, WV")` → `rtr:us:wv:ranson` (unverified), and `display_name()` gives "Ranson corporation, WV" because `display._TRAILING_TYPE_RE` doesn't list `corporation`. Same shape as the Sitka "city and borough" fix (`BACKLOG_DONE.md` 2026-09-09).
  - **Impact**: `ransonwv.iqm2.com`'s two pages now live at `/j/ranson-corporation-wv` (pinned by WO-125).
  - **Next action**: add `corporation` to the lookup-side trailing-type strip and to `display._TRAILING_TYPE_RE`, add the Ranson pair to the Sitka test, then add a `ranson-corporation-wv` → `ranson-wv` alias row (the reverse of the one WO-125 wrote).
  - **History**: WO-125, 2026-09-09.

- **[HUMAN] Five `youtu.be` pages for the Wasatch Front Waste & Recycling District's board (channel `@WasatchFrontWaste`) sit under Wasatch **County**, UT — the minted row is in `governments.csv`; the override is one deploy away.**
  - **Issue**: the adapter extracted "Wasatch, UT" and the place ladder keyed it to `us:county:49051`. WFWRD is a Salt Lake valley special district with its own board (decision D2: its own `gov_id`). `rtr:us:ut:wasatch-front-waste-recycling-district` landed 2026-09-10 (source `ryan_stated`); the override endpoint refuses an id the *deployed* registry cannot render, so it has to wait for the Archive deploy that carries the row.
  - **Next action**: after that deploy, `POST /internal/jurisdiction/override?ids=6584,6973,6974,6975,6976&gov_id=rtr:us:ut:wasatch-front-waste-recycling-district` (dry run first), then a `channel=@WasatchFrontWaste` rule once the channel plumbing lands.
  - **History**: found spot-checking the 2026-09-09 backfill.

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

- **`[LATER]` 5 small Southampton County, VA towns (Boykins, Branchville,
  Capron, Ivor, Newsoms) have no distinguishable video content of their
  own — currently falls back to the county, which is benign but not
  exact.**
  - **Issue**: all 5 towns' only known web presence is Southampton
    County's own site (`southamptoncounty.org`), whose live-stream page
    embeds a single shared Swagit tenant
    (`southamptoncountyva.new.swagit.com/views/278/`). Checked that
    tenant's own channel listing directly (not assumed): the real,
    non-boilerplate categories are Board of Supervisors, Planning
    Commission, and Budget Workshops & Public Hearings — no per-town
    channel exists for any of the 5. This isn't a shared page hiding
    separable per-town content; the content is genuinely county-only.
  - **Impact**: currently low/benign. `resolve_government()` already
    lands on Southampton County's own correct `gov_id` for this host+path
    via its normal domain/content signal — not the wrong-government
    failure mode this project has hit elsewhere (e.g. the Gloucester
    VA/MA collision), just an imprecise-but-honest fallback to the parent
    government instead of the specific town. Ryan's read: fine as-is for
    now for this one VA case. The general shape (a small town's meetings
    genuinely living only on its county's platform, no per-town signal to
    recover) is a real, recurring class of problem this project has seen
    with mixed outcomes elsewhere -- worth fixing generally rather than
    per-town if revisited.
  - **Next action**: none required now. If revisited, a `tenant_overrides.csv`
    entry pinning `southamptoncounty.org`'s live-stream path to
    `us:county:51175` would make the current (correct) fallback
    authoritative rather than incidental, protecting it against a future
    override attempt that assumes per-town content exists. Only worth
    doing if/when a real per-town discriminator is found, or as pure
    hardening if this host's resolution ever changes behavior.
  - **History**: `rtr-business` research session, 2026-09-07/08
    (`research/ENUMERATION_METHODS.md` §96/§97/§99/§100 — StateDir-only
    two-hop scan, Step 3 dry run, Step 2 specify pass on this
    population).

- **`[NEEDS-AUDIT]` A CivicPlus page that delegates to a video link on a
  domain `_jurisdiction_from_subdomain()` can't parse loses jurisdiction
  entirely, filing under "Unidentified government" instead of falling
  back to the CivicPlus tenant's own government.**
  - **Issue**: Cambridge, MD's AgendaCenter (`choosecambridge.com`) is a
    real, live example: `resolve_civicplus_seed()`'s
    `subdomain_jurisdiction = finder._jurisdiction_from_subdomain(seed_url)`
    returns nothing for this domain (the town's name, "cambridge", isn't
    recoverable from "choosecambridge"), so the override
    `if subdomain_jurisdiction: result.jurisdiction = subdomain_jurisdiction`
    never fires. The picked agenda row's video link pointed at a
    Town Hall Streams URL with no video actually found there, and
    `townhallstreams.py`'s own resolve() has no jurisdiction signal of
    its own either — so the stored page ended up filed under
    "Unidentified government (townhallstreams.com)" even though the
    agenda title itself literally says "Cambridge, MD 21613" and the
    agenda link is `choosecambridge.com/AgendaCenter/...`. Live now:
    `/m/2026-09-03-thursday-september-3-2026-agenda-for-mayor-s-accessibility-committee`.
    Found running `scripts/nationwide_1911_ingest.py` (rtr-business
    batch 3, 2026-09-09) — this script's own `civicplus_seed_urls()`/
    `resolve_civicplus_seed()` already has the input CSV row's real
    `unit_name`/state in hand (from `nationwide_1911_confirmed_hits.csv`,
    keyed by a Census `gov_id`) but never threads it through as a
    fallback when the adapter-level jurisdiction guess comes back empty.
  - **Impact**: low volume so far (1 of 486 rows this batch), but the
    failure mode is silent — a correctly-ingested, real government page
    lands unfindable under `/j/*`/`/state/*` for its actual jurisdiction
    (Cambridge, MD) and instead pollutes a generic "Unidentified
    government (townhallstreams.com)" bucket that likely has other
    similar victims from the two prior nationwide batches (395/431) —
    not yet checked.
  - **Next action**: two independent fixes, either sufficient alone: (1)
    in the app itself, extend `_jurisdiction_from_subdomain()` or its
    caller to fall through to a Wikidata/Census place lookup keyed on the
    resolved page's own title/state text rather than only the domain
    string; (2) in the batch scripts specifically
    (`nationwide_395_ingest.py`/`nationwide_431_ingest.py`/
    `nationwide_1911_ingest.py`), thread the input CSV row's own
    `unit_name` (and state, derivable from the `gov_id`'s FIPS/GNIS
    prefix) through as `result.jurisdiction` whenever the adapter comes
    back empty — these scripts already know exactly which government
    each row is for, which is strictly more information than any
    adapter-side domain guess.
  - **Constraint**: don't just special-case `choosecambridge.com` — the
    same "self-hosted domain name doesn't obviously contain the town
    name" shape will recur (this repo has hit it before with white-labeled
    CivicPlus tenants generally, see `resolve_civicplus_seed()`'s own
    docstring).
  - **History**: found spot-checking `scripts/nationwide_1911_ingest.py`'s
    output, 2026-09-09 — not yet in `BACKLOG_DONE.md` (nothing fixed
    yet). `scripts/wo127_civicplus_pipeline.py` (WO-127, same day)
    implements fix (2) unconditionally rather than as an empty-guess
    fallback — every candidate's known `"{name}, {state}"` overwrites
    whatever the delegated platform guessed, always — and validated it
    at real scale: 4 tier-1 ingests across 4 different delegated
    platforms (Granicus/Vimeo/TelVue/Cablecast) landed on the correct
    jurisdiction, zero `rtr:unknown`. The named `nationwide_*` scripts
    here are still unfixed; this is a second, independent script proving
    the approach, not a fix to the ones named above.

- **`[NEEDS-AUDIT]` `rtr-business/research/jurisdiction_coverage.csv` has 1,339 duplicated `gov_id`s (2,132 extra rows), and some already-confirmed platform rows never got their stale `reject_reason` cleared.**
  - **Issue**: measured directly 2026-09-09 (WO-127) — `Counter(gov_id
    for row in csv)` finds 1,339 `gov_id` values with 2+ rows, on top of
    the single Clay City, KY duplicate ENUMERATION_METHODS.md §132
    already named (that one's real, this is the same defect at 40x the
    scale nobody had counted). Separately, several rows already carry a
    real `suspected_calendar_provider` (e.g. `civicplus`, with a working
    `example_agenda_or_calendar_url`) while `reject_reason` still reads
    `no-platform-link-found` from before that provider was confirmed —
    Alabaster city, AL and Rawlins/Torrington city, WY are three
    confirmed examples. A duplicate-row write also silently picks
    whichever row a plain dict lookup hits first (arbitrary file order),
    so two different pipelines can each "confirm" the same gov_id on two
    different rows and neither sees the other's write.
  - **Impact**: `coverage_registry.csv`'s `no-platform-link-found` slice
    (the WO-127/WO-130 candidate source) is measurably contaminated with
    governments already known to run a platform — this is the leading
    explanation for why WO-127's CivicPlus-own-domain hit rate (348/1946
    = 17.9%) ran well above the ~11% BuiltWith-sample baseline in
    `CIVICPLUS_FIRST_RUN.md`'s Addendum 4. Any future sweep filtering on
    `reject_reason` inherits the same contamination.
  - **Next action**: a one-time reconciliation script over
    `jurisdiction_coverage.csv`: merge rows sharing a `gov_id` (prefer
    the row with more non-blank fields; flag, don't guess, if both have
    conflicting non-blank values for the same column), then clear
    `reject_reason` on any row where `suspected_calendar_provider`,
    `suspected_meeting_link_provider`, `suspected_video_provider`, or
    `shares_video=True` is already populated.
  - **Constraint**: run from the Render shell / locally against a copy,
    never blind — this file is a live multi-session hotspot (see
    `CLAUDE.md`'s coordination bullet); re-read fresh immediately before
    writing, same as every other script that touches it.
  - **History**: `wo127_civicplus_pipeline.py`'s own coverage-file
    helpers were hardened the same day to update every matching `gov_id`
    row (not just the first) specifically because of this, after hitting
    it live mid-run.

- **`[NEEDS-AUDIT]` A same-state place/county name collision falls through to the county even when the place table has a genuine, unique match.**
  - **Issue**: `resolve_government("Waukesha city, WI")` and
    `resolve_government("Jefferson borough, PA")` both return the
    **county** (`us:county:55133` Waukesha County, `us:county:42065`
    Jefferson County) even though `classify.classify_government_type()`
    correctly tags both `municipality`, and `us_places.csv` has a real,
    unique-looking place row for the first (`5584250,Waukesha
    city,WI`) — the second has two real "Jefferson borough, PA" rows
    (`4237880`/`4237944`, genuinely two different boroughs, which is
    plausibly why place lookup declines and falls through). For Waukesha
    there's no such excuse: `us_places.csv` has exactly one "Waukesha
    city, WI" row and a differently-named "Waukesha village, WI"
    row — something in the place-lookup path still fails to return that
    single match and falls through to the county table where "Waukesha
    County, WI" is the sole hit. Four other same-pattern names tested
    clean (`Marquette city, MI`, `Marinette city, WI`, `Manitowoc city,
    WI`, `Oconto city, WI` all resolved correctly to their place), so
    this isn't a blanket "place lookup is broken" bug — it's narrower,
    tied to whatever makes these two names' lookup path fail even though
    a unique/near-unique place hit exists.
  - **Impact**: `jurisdiction_coverage.csv` had both wrong (assigned by
    an earlier, less careful pass — the same failure mode this file's
    `gov_id` column now correctly declines to reproduce, WO-132). Any
    live tenant serving Waukesha city, WI or Jefferson borough, PA
    meetings would key to the county today, not the city/borough.
  - **Next action**: instrument `_national_lookup()`/`NameStateTable.
    lookup()` for these two specific name+state pairs to see exactly why
    the place-table hit isn't returned before the county fallthrough
    fires — this needs step-through, not another blanket regex change,
    per this file's own adapter-testing convention.
  - **Constraint**: don't fix by just checking "was there a unique place
    hit" ahead of the county table in the general case without checking
    it against the real Alaska/Ontario dual-nature governments (Anchorage
    Municipality, Prince Edward County, ON) that legitimately have valid
    rows in BOTH tables for the same real government — those need the
    dual match kept, not silently narrowed to whichever table is checked
    first.
  - **History**: found while re-deriving `gov_id` for every
    `jurisdiction_coverage.csv` row from scratch (WO-132, 2026-09-09,
    rtr-business `ENUMERATION_METHODS.md` §159 / `GOV_ID_MATCH_REPORT.md`)
    — both rows were blanked rather than left wrong; not yet in
    `BACKLOG_DONE.md` since nothing is fixed yet.

### Adapter & platform gaps

- **[NEEDS-AUDIT] About 65 `www.youtube.com` rows in `tenant_overrides.csv` use a bare video id as `match` instead of the `youtube:<video_id>` form the resolver actually needs, so they likely never fire.**
  - **Issue**: `app/platforms/youtube.py` sets `ResolvedMeeting.external_id = f"youtube:{video_id}"` (confirmed at all three call sites, and asserted directly by a dozen tests including `tests/test_youtube.py`), and `resolve_government()`'s `_match_override()` (`app/utils/gov_registry/resolver.py`) satisfies a `match` value with no `=` in it by checking whether it equals a `page_hints` *value* — `page_hints["external_id"]` is that prefixed string, not the bare id. A YouTube watch URL's video id also isn't in the page's URL *path* (it's a `?v=` query parameter), so the other branch of `_match_override()` can't find it there either. Found and fixed in this WO's own pin-writing script before any row was written — the correct form was confirmed against `tenant_overrides.csv`'s own most recent real rows (`youtube:kGepCh07dg4`, `youtube:JCiKfYUACv4`, etc., all WO-134/WO-149-era, 404 of them by direct count) before writing WO-171's 439 new per-video pins in that form.
  - **Impact**: about 65 existing `www.youtube.com,<bare-video-id>,...` rows (no `youtube:` prefix, no `channel=`) most likely never match anything and have been silently inert since they were written — meaning whatever government they were meant to key never actually got keyed by them.
  - **Next action**: for each of the ~65 rows, check whether the video id's page is still unkeyed (`rtr:unknown:www.youtube.com`) today; if so, either rewrite the row's `match` to `youtube:<id>` (if there's still a real gov_id to key it to) or remove it (if the page has since been keyed a different way, e.g. a channel pin added later). A one-off script scanning `tenant_overrides.csv` for `www.youtube.com` rows whose `match` has no `:` and no `=` would find all ~65 directly.
  - **Constraint**: verify a sample actually is inert (re-resolve the government for one of the affected video ids with today's registry) before mass-editing — it's possible some of these were written back when the matching scheme was different and worked at the time.
  - **History**: found live 2026-09-10 building WO-171's LocalView pin writer; not audited or fixed here, since the ~65 existing rows are a different, separate cleanup from this WO's own new pins. See `BACKLOG_DONE.md`'s WO-171 entry.

- **[NEEDS-AUDIT] `ec1c24.com` is an unrecognized video-index wrapper domain — Temple City, CA's real CivicPlus meetings all point at it, and it embeds a real YouTube video with per-agenda-item timestamps.**
  - **Issue**: WO-162 (2026-09-10) fixed CivicPlus's corporate-host substring bug (`connect.civicplus.com` no longer misclassified as a real tenant — see `BACKLOG_DONE.md`), using Temple City, CA (`www.templecityca.gov/agendacenter`) as the live example. Fetching that real page live turned up a second, separate gap: every one of its 103 `tr.catAgendaRow` rows links its `td.media` video to `templecity.ec1c24.com/citycouncil/{yyyy}/{mm}/{slug}.html`, a domain `detect_platform()` doesn't recognize at all. Fetching one of those pages live confirms it embeds a real single YouTube video (`youtube.com/embed/hXcwEqIekkc`) with per-agenda-item `?start={seconds}` deep links already built in — a real, resolvable meeting, just one hop further than `civicplus.py`'s `_is_real_video_link()` currently looks (it requires the row's own href to already be a directly-recognized platform link, so it correctly treats these rows as "no video" rather than fabricating one).
  - **Impact**: Temple City, CA is recorded `no-video-found` (`jurisdiction_coverage.csv`, `hub_sweep_wo126_report.csv`) even though a real video with real per-item timestamps exists. Unknown how many other CivicPlus tenants use this same `ec1c24.com` wrapper — only Temple City has been checked.
  - **Next action**: find 2-3 more real `ec1c24.com` tenants (a `catAgendaRow` `td.media` href on that domain is the fingerprint) to confirm the page shape generalizes before building anything — per this repo's own "test against a real URL first" rule, one tenant isn't enough to register a new platform or teach `civicplus.py` to follow this one extra hop. If confirmed, the fix is likely a one-hop embedded-YouTube scan specifically for a `td.media` href that fails `_is_real_video_link()`, not a full new adapter — `ec1c24.com` appears to be a video-index/agenda-sync wrapper, not a distinct video host.
  - **Constraint**: don't register `ec1c24.com` as its own platform off one tenant.
  - **History**: found live 2026-09-10 building WO-162's Temple City fixture (`tests/fixtures/civicplus/temple_city_agendacenter.html`, see that directory's `README.md`); not fixed here — out of WO-162's scope (a different, unrelated gap from the corporate-host bug that PR fixed).

- **[NEEDS-AUDIT] A same-named Granicus tenant is a real video source for most "no video" Legistar cities — worth a standing sweep, confirmed on 25 of 29 tenants tested.**
  - **Issue**: WO-145 (2026-09-10) fixed Yonkers, NY's Legistar page having no video by finding its recording on a same-named Granicus tenant (`granicus_channel.py`, joining Kansas City, MO from 2026-08-29). A read-only test on 29 other Legistar tenants (no video previously found, or status unknown) found a same-named `*.granicus.com` tenant with real recent video for 25 of them; of those, 16 had a newest video whose body and date matched a real Legistar-tracked meeting outright, 3 more likely match but couldn't be checked (Legistar's own API rejected the guessed client name), and 5 were real misses (wrong channel, a dead channel, or a Granicus tenant shared across more than one government). Full numbers and per-tenant table: `rtr-business/research/ENUMERATION_METHODS.md`, 2026-09-10 section; `BACKLOG_DONE.md`'s matching entry.
  - **Impact**: an unknown number of the "no video found" Legistar rows in `jurisdiction_coverage.csv` likely have a real, findable Granicus recording today, the same shape as Yonkers.
  - **Next action**: build an offline sweep script (same shape as WO-103's `scripts/sweep_tenant_landing_pages.py` pin-worklist pattern) that runs this probe against every Legistar tenant marked no-video-found, and writes candidates needing a human/session look — not a direct write to `_VIEW_PUBLISHER_FALLBACKS` or `jurisdiction_coverage.csv`, since a same-named tenant needs its body+date match confirmed per candidate the way Kansas City's and Yonkers's were (WO-145's sweep found real false leads: a wrong channel, a dead channel, a shared-tenant case). Keep this a periodic offline sweep, not a live probe inside `legistar.py`'s `resolve()` path — a 15-view-id probe per unmatched page is too slow and too unreliable to run on a real user request.
  - **Constraint**: don't add an unverified tenant straight to `_VIEW_PUBLISHER_FALLBACKS` — confirm the body+date match by hand first, same bar as the two tenants already in it.
  - **History**: `BACKLOG_DONE.md`, WO-145 (2026-09-10).

- **[NEEDS-AUDIT] The coverage registry's `domain` field maps a small government to a completely different government's tenant far more often than WO-142's original sample suggested — 6 of 25 (24%) in WO-145's under-5,000-population pilot, not WO-142's ~14%.**
  - **Issue**: `coverage_registry.csv`/`wo145_candidates.csv`'s `domain` (and sometimes `hub_url`) column points at a real, live, structured-platform tenant that resolves fine — it just belongs to a different, usually larger, government that happens to share a name substring or sit in the same county. Six confirmed in one 25-row pilot: Ventura city, IA → Ventura *County, CA*'s PrimeGov tenant; Flemington borough, NJ → Hunterdon *County, NJ*'s CivicClerk tenant (`hunterdonconj.portal.civicclerk.com`); Crystal River city, FL → Citrus *County, FL*'s CivicClerk tenant (one candidate on it even resolved as *Inverness, FL* — a third, different city — not just "the county"); Jefferson city, OR → Jefferson *County, OR*'s Granicus tenant (`jeffco.granicus.com`); Kearny County, KS → an unrelated *Town of Kearny, New Jersey* on iqm2; Hometown city, IL → Cablecast's own vendor demo/sample tenant (`hometown.cablecast.tv`, show titles like "PEG Experts: PDFs" and "YourTown School Board Meeting" — coincidental name collision with the vendor's own generic placeholder branding, not even a real second government).
  - **Impact**: any script that seeds a tenant's government identity from this column without an independent post-resolve check (per-meeting content, not just the tenant host) will misattribute real content to the wrong government — one already happened: `scripts/wo145_api_first_sweep.py`'s Crystal River row briefly ingested a real Citrus County Value Adjustment Board meeting into production under Crystal River's `gov_id` before this check existed; deleted the same session via `POST /internal/admin/delete-pages`. At this rate, every future known-platform sweep over the smaller-population tail needs the same defense, not just WO-145's own script.
  - **Next action**: `wo145_api_first_sweep.py`'s `_state_or_kind_conflict()`/`_title_place_conflict()` (state-name conflict, county-vs-municipality keyword, and a specific different place-name in either the adapter's resolved jurisdiction/meeting_body or the resolved title, checked against the row's own name tokens) is the working reference implementation — port it into a shared helper (`app/utils/gov_registry/` or `scripts/`) that any future sweep imports, rather than each one re-discovering this the hard way. Separately, a dedicated backfill pass across the full registry (re-derive each `domain`'s actual resolved government from a real fetch/resolve, not just whether the platform responds) was already recommended in `ENUMERATION_METHODS.md` §182 and has not been built.
  - **Constraint**: the check needs BOTH the pre-resolve landing-page text and a post-resolve check of the adapter's own jurisdiction/meeting_body/title — a JS-rendered SPA portal shell (confirmed on CivicClerk) carries no identifying text server-side, so the landing-page check alone misses it, and a tenant-seeded `gov_id` makes the resolved jurisdiction field circular for a candidate with no per-meeting government signal of its own (the title is the only independent signal left in that case).
  - **History**: WO-142 (`ENUMERATION_METHODS.md` §182, 2026-09-10) found 4 of these in a 29-row sample of mixed population and recommended checking `domain` against the resolved government. WO-145 (`BACKLOG_DONE.md`, 2026-09-10) confirmed the rate is markedly worse in the under-5,000-population tail and built + verified the reference fix above.

- **[NEEDS-AUDIT] `HIGH_RISK_TITLE_PLATFORMS` (`{"youtube", "vimeo"}`, `scripts/nationwide_2404_ingest.py`) is missing Cablecast and Swagit, so a non-meeting video on either platform can resolve and queue as if it were a real government meeting.**
  - **Issue**: this set gates which platforms require a real governing-body keyword in the title (`_looks_like_real_meeting(..., require_allowlist=True)`) before a resolved candidate is trusted — every other known-platform sweep in this repo (`hub_sweep_wo126.py`, `wo134_confirmed_hits_ingest.py`) imports the same constant. Cablecast is a general PEG/community-access broadcast platform, not a dedicated meeting system, and a real tenant can carry non-meeting programming (community classes, religious content, vendor demo/training material) alongside real council meetings. Confirmed live, 2026-09-10 (WO-145 pilot): Hometown, IL's cablecast tenant resolved "Weekly Chat, Explosion in E-Learning!" and "Case Study: HCAM" — neither promotional-blocklisted nor allowlist-gated — as if they were real meetings.
  - **Impact**: any Cablecast (or plausibly Swagit, a government's own general-purpose video channel with the same shape of risk, not yet confirmed with a live example) candidate whose title happens to avoid the promo blocklist words gets treated as a real meeting regardless of content — a quieter failure mode than the blocklist catches, since ordinary non-meeting community-access programming doesn't use promotional language at all.
  - **Next action**: add `"cablecast"` (confirmed) and `"swagit"` (defensive, same reasoning, no live example yet) to `HIGH_RISK_TITLE_PLATFORMS` in `nationwide_2404_ingest.py`, and re-run `tests/` to confirm nothing already-shipped depended on Cablecast/Swagit being exempt from the allowlist check.
  - **Constraint**: a real Cablecast government meeting must still pass — check a live confirmed one (e.g. a `MEETING_ALLOWLIST` keyword like "council"/"board"/"meeting" already appears in real Cablecast meeting titles seen elsewhere in this repo) before widening the set, so this doesn't newly reject content that used to work.
  - **History**: found and worked around locally in `scripts/wo145_api_first_sweep.py` (`ENUMERATOR_HIGH_RISK_TITLE_PLATFORMS`) rather than fixed at the shared-constant level, per this project's "smallest change, verify before building broader" convention — see `BACKLOG_DONE.md`'s WO-145 entry, 2026-09-10.

- **[JUST-DO-IT] A bare eScribe tenant root (no `Meeting.aspx` path) resolves "successfully" with zero content instead of finding a real meeting — confirmed on ~29 of 43 WO-128 candidates.**
  - **Issue**: `escribe.py`'s `resolve()` fetches whatever URL it's given and never raises `CalendarPageError` for a listing/root page the way `civicplus.py`/`municode_meetings.py`/`vimeo.py` do, so `nationwide_*_ingest.py`'s `resolve_seed()` has no candidate list to pick from — it just returns an empty `ResolvedMeeting` (no agenda items, no video, no metadata), logged as `"resolved but no transcript/agenda/video"`. Real examples: `pub-southdundas.escribemeetings.com`, `pub-hawkesbury.escribemeetings.com`, `pub-smithsfalls.escribemeetings.com` (all real Ontario municipalities whose only known seed is the bare tenant host).
  - **Impact**: any candidate list whose eScribe lead is a tenant host rather than a specific `Meeting.aspx?Id=...` URL — jurisdiction_coverage.csv's own `domain` column holds the bare tenant host for many Canadian eScribe governments — silently reads as "no content" instead of "never actually checked a real meeting."
  - **Next action**: `scripts/adhoc_cdx_escribe_pipeline.py` already solved this for its own tenant-list input via `discover_candidate_ids()` (`POST {domain}/MeetingsCalendarView.aspx/GetCalendarMeetings`, most-recent-first, `HasVideo`-only). `scripts/wo128_known_platform_sweep.py` reuses that function directly for its own bare-tenant-root case (`_discover_escribe_meeting()`) — port the same pattern into `nationwide_2404_ingest.py`'s (or its next copy's) `locate_platform_url()`/`resolve_seed()`, the way `civicclerk_latest_event_url()` already handles the analogous bare-tenant-link case for CivicClerk.
  - **Constraint**: `GetCalendarMeetings` is a real but undocumented tenant API — keep the same 120-day lookback and polite delay `adhoc_cdx_escribe_pipeline.py` already uses.
  - **History**: found live 2026-09-09, WO-128 (known-platform sweep); worked around locally in `scripts/wo128_known_platform_sweep.py` rather than fixed at the shared-helper level, since `nationwide_2404_ingest.py` was mid-run against production the same day (same "don't change this mid-run" constraint as the agenda-only-ingest entry above).

- **[NEEDS-AUDIT] `suiteone.py`'s `resolve()` raises a raw `ValueError`
  on a bare tenant homepage instead of finding a real event — confirmed
  live on 3 counties in one run.**
  - **Issue**: `SuiteOneAssetFinder.resolve()` requires a URL that
    already carries an `event`/`id` query parameter (`_extract_ids()`);
    given a bare tenant root (`https://floydcoin.suiteonemedia.com/web/
    live`, `https://lunaconm.suiteonemedia.com/`, `https://
    rushcoin.suiteonemedia.com/?embed=1`) it raises `ValueError("Could
    not find a SuiteOne tenant/event id in URL: ...")`, uncaught by
    `wo134_confirmed_hits_ingest.py`'s `process_row()`, which surfaces
    as a hard `RowError` rather than a content-classified skip. Same
    shape as this section's own eScribe bare-tenant-root entry above and
    the Granicus bare-homepage-fallback entry a few sections down — a
    third adapter with the identical "given a listing/root page instead
    of a specific meeting URL, crash instead of degrading" gap.
  - **Impact**: confirmed live 2026-09-10, WO-149's county sweep: Floyd
    County IN, Luna County NM, Rush County IN all counted as `error`
    (not `skipped`) purely because their only known SuiteOne lead was
    the tenant's homepage/live-stream URL, not a specific
    `/event/?id=...` link.
  - **Next action**: give `SuiteOneAssetFinder` (or its caller) a real
    event-listing lookup for a bare tenant root, the way
    `civicclerk_latest_event_url()`/`_discover_escribe_meeting()` already
    do for their platforms — module docstring doesn't document a listing
    endpoint yet, so check for one on a live tenant (`floydcoin.
    suiteonemedia.com`) before assuming none exists.
  - **Constraint**: only 3 tenants confirmed so far, all from one sweep
    — a real second example before generalizing further, per this
    repo's "test against a real URL first" rule.
  - **History**: WO-149, 2026-09-10 (`BACKLOG_DONE.md`).

- **[JUST-DO-IT] Castus's URL regex only matches `/video/{id}`, silently
  missing the real `/private/{id}` path variant — confirmed live with
  Vero Beach, FL.**
  - **Issue**: `castus.py`'s `_URL_RE = re.compile(r"/vod/([^/?#]+)/
    video/([^/?#]+)")` hardcodes the literal path segment `video`. Vero
    Beach's own government-access channel (`cloud.castus.tv/vod/
    vero-beach/private/6a8dc49212e21f0002bd8a31`, a real 1h37m "City
    Council 08/25/2026" meeting, verified by loading it directly —
    full council chamber, live timestamp overlay, not a promo or
    placeholder) uses `private` instead, so the regex never matches at
    all and `resolve()` falls straight to `"Could not find a tenant/
    video id in this Castus URL."`. A same-tenant second video
    (`6a8dc49212e21f0002bd8a31`'s sibling `67d82e28352ecb0008fcf4da`)
    uses the same `private` shape, so this isn't a one-off typo on
    Vero Beach's side.
  - **Impact**: a same-day nationwide candidate sweep
    (`~/Documents/rtr-business/research/nationwide_395_ingest_log.csv`)
    hit this exact URL and, because the direct adapter call returned no
    video, mis-classified a real meeting as `ingested_agenda_only`
    (no video/transcript) instead of a real tier-1/2 ingest — caught
    and corrected by hand in `jurisdiction_coverage.csv`, but the
    underlying adapter gap is still live and would repeat for any other
    Castus tenant using the `private` path. Every other Castus example
    found in this project's research corpus (Andover MA, Seabrook TX,
    Billings MT, Fort Mitchell KY, Greene ME) uses the working `/video/`
    path, so this looks tenant/visibility-specific (private/unlisted
    videos) rather than a second widespread product variant — not
    confirmed beyond Vero Beach's two videos.
  - **Next action**: widen `_URL_RE` to accept either `video` or
    `private` as the path segment (e.g. `/vod/([^/?#]+)/(?:video|
    private)/([^/?#]+)`) and confirm the rest of `resolve()` (asset
    fetch, captions) behaves the same for a `private`-path video as a
    `video`-path one — not verified here, since this was found and
    fixed at the research layer, not by running the adapter itself.
  - **History**: castus.py itself shipped 2026-08-21 (`BACKLOG_DONE.md`
    "Castus (cloud.castus.tv): investigation spike... became a full new
    platform adapter") — this is a gap in that adapter's URL matching,
    not a missing platform. Found 2026-09-07 in rtr-business's
    `ENUMERATION_METHODS.md` nationwide sweep (§75-76 and the Vero Beach
    follow-up); a prior sighting of Castus generally (Andover, MA) is
    also noted there at §67, unrelated to this specific bug.

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
    6) plays. Confirmed at much larger scale 2026-09-06 (CDX
    enumeration, 48 fresh tenants never seen before): 39/48 (81%) came
    back empty for exactly this reason — this is the dominant yield
    limiter for ChampDS specifically, well above every other platform
    scanned the same day (Granicus 35% dead-tenant rate, IQM2/eScribe's
    discovery-step misses).
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

- **[NEEDS-AUDIT] A resolve that delegates to a generic video host (Vimeo/YouTube) can mint the wrong state for an ambiguous city name, even when the originating government page already unambiguously names the right one — confirmed live on 2 real pages from the 2026-09-09 2,404-candidate batch, two different mechanisms. The 2 known rows are hand-corrected; the mechanism is still open.**
  - **Issue**: (1) `rtr-deeplink.onrender.com/m/branford-fl-2026-07-01-board-of-selectmen-07-01-2026` — real content confirmed live (Connecticut General Statute cited on-camera, agenda link `branford-ct.gov/AgendaCenter/...`, closing line "town of Branford... branfordtd.org") but filed under Branford, **FL** instead of the real Branford, **CT**. Root cause: the candidate's own site is a white-labeled CivicPlus install (`www.branford-ct.gov`, no `civicplus.com` anywhere), whose AgendaCenter row delegated to a Vimeo video. `resolve_civicplus_seed()` (`scripts/nationwide_2404_ingest.py`, copied unchanged from `nationwide_1911_ingest.py`) computes `subdomain_jurisdiction = finder._jurisdiction_from_subdomain(seed_url)` specifically to override whatever the delegated platform guesses — but `CivicPlusAssetFinder._jurisdiction_from_subdomain()` (`app/platforms/civicplus.py:259-282`) only recognizes the `{state}-{name}.civicplus.com` tenant-subdomain shape: `netloc.split(".")[0]` on `www.branford-ct.gov` is `"www"`, which has no `-` to split on, so it returns `None` immediately — for *every* white-labeled CivicPlus domain, not just this one. With no override, Vimeo's own `_jurisdiction()` (`app/platforms/vimeo.py:641`, an oEmbed-`author_name` guess run through Census-validated `validated_label_extract()`) won with the wrong state for an ambiguous "Branford". (2) `rtr-deeplink.onrender.com/m/hartwick-ia-2026-09-02-planning-board-meeting-september-2026` — the candidate CSV's own row already names it unambiguously (`domain: hartwickny.gov`, `state_or_province: New York`, `hit_source_urls: vimeo=https://hartwickny.gov`), but the page is filed under Hartwick, **IA**. Different mechanism, same shape: this was a *direct* `platform=vimeo` hit (no CivicPlus wrapper), and `resolve_seed()`/`process_row()` never pass the CSV's own already-known city/state through as a hint or a post-resolve correction — the resolved `result.jurisdiction` is whatever Vimeo's own account-name guess produced, full stop.
  - **Impact**: both were live, real, currently-served pages under the wrong jurisdiction (wrong "More {place} meetings" / "More {state} meetings" links, wrong `/state/*` and `/j/*` attribution) — **both hand-corrected 2026-09-10** via `POST /internal/jurisdiction/override` (page 7075 → `us:cousub:0917007310`, "Branford, CT"; page 7082 → `us:cousub:3607732589`, "Hartwick Town, NY"), confirmed live afterward. That's a per-page patch, not the fix: (1) affects *every* white-labeled (non-`*.civicplus.com`) CivicPlus tenant whose delegated platform's own jurisdiction guess is wrong, not just Branford — self-hosted CivicPlus domains are the majority case this whole `resolve_civicplus_seed()` bypass function exists for (see its own docstring: "most CivicPlus tenants are white-labeled... e.g. klickitatcounty.gov"), so the override silently never fires for most of them. (2) affects any direct YouTube/Vimeo resolve nationwide-batch-wide, not just this run — the nationwide ingest scripts have never threaded the candidate CSV's own known city/state through to the resolved result at all, in any of the 4 batches (395/431/1911/2404). A follow-up automated check (comparing each ingested/queued row's resolved-page slug against the candidate CSV's own `state_or_province`, US states only) found no additional mismatches, but it's a partial check, not a real sweep: only 25 of the batch's ~412 ingested/queued rows have a slug shape a 2-letter state code can be pattern-matched out of at all (most slugs carry no state code, e.g. `/m/2026-09-08-county-commissioners-meeting-09-08-2026`) — a real sweep would need to compare each row's actual stored `jurisdiction` field via the Archive API, not guess from slug text.
  - **Next action**: two independent fixes, don't conflate them. (1) Either broaden `_jurisdiction_from_subdomain()` to also recognize a non-`civicplus.com` domain's own city/state (e.g. from the candidate's known `city_name`/`state_or_province`, threaded through as a parameter) or have `resolve_civicplus_seed()` treat "not a `{state}-name.civicplus.com` subdomain" as a signal to trust the caller's own known jurisdiction over whatever the delegated platform guesses, rather than silently declining to override. (2) In the next `nationwide_NNNN_ingest.py` copy, thread the candidate row's own `city_name`/`state_or_province` through to `process_row()`'s ingest payload as a jurisdiction hint/override for direct video-host resolves (youtube/vimeo), at minimum when the platform's own guess disagrees with (or can't validate) the known value — the CSV already has ground truth for every row in this batch shape, unlike a cold resolve with no other signal.
  - **Constraint**: the 2 known rows are already fixed by hand — don't re-patch them, and don't mistake the manual `tenant_override_rules` line the override endpoint emitted (`vimeo.com`/`player.vimeo.com`, blank `match`) for a safe rule to commit to `tenant_overrides.csv` as-is; the endpoint deliberately leaves `match` blank on a shared generic-video host because a blank match there would over-apply to every future Vimeo video, not just these two governments — a real per-host discriminator is still a human decision. Before building the systemic fix, consider whether a full sweep of this batch's other ~36 ingested + ~396 queued rows (via the Archive API, not slug text) for a similar mismatch is worth doing first, to size the real blast radius rather than guessing from 2 examples.
  - **History**: found 2026-09-09 spot-checking live pages from the 2,404-candidate platform-detection batch. Originally filed to this section, then swept into `BACKLOG_DONE.md` by mistake along with ~88 other unrelated open entries in PR #807's squashed "move the shadowed-county resolver bug to done" commit (which deleted this whole section's content from `BACKLOG.md` instead of just its own one entry) — restored here 2026-09-10 after noticing the whole section had vanished; the manual page fix is new, the systemic fix is not yet done. See this file's own note below about the other ~88 entries still needing the same recovery.
- **[NEEDS-AUDIT] `granicus.py`'s `_fetch_page()` raises an unhandled `UnicodeDecodeError` on a real `AgendaViewer.php` response, even though the same clip resolves fine via `MediaPlayer.php`.**
  - **Issue**: confirmed live 2026-09-09 building WO-134's confirmed-hits ingest — `GranicusAssetFinder.resolve("https://harrisonburg-va.granicus.com/AgendaViewer.php?view_id=2&clip_id=1369")` raises `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe2 in position 11` from `_fetch_page()`'s `await response.text()` call (`app/platforms/granicus.py:236`), which has no `errors=` argument. `MediaPlayer.php?view_id=2&clip_id=1369` — same tenant, same clip — resolves cleanly with a real `video_url`. Every candidate row on a Granicus `ViewPublisher.php` listing page links to `AgendaViewer.php`, not `MediaPlayer.php`, so anything that scrapes that listing (as WO-134's own `granicus_candidate_rows()` now does) hits this by default unless it deliberately swaps the URL over.
  - **Impact**: any code path that resolves a `AgendaViewer.php` URL directly crashes instead of degrading — worked around in `scripts/wo134_confirmed_hits_ingest.py` by rewriting the link to `MediaPlayer.php` before resolving, but `_fetch_page()` itself still has the bug for any other caller (a reader pasting an `AgendaViewer.php` link directly, for instance).
  - **Next action**: add `errors="replace"` to `_fetch_page()`'s `response.text()` call (matching the pattern other adapters already use for exactly this reason), and confirm with a real `AgendaViewer.php` fixture the resulting page still parses into something sane rather than replacing meaningful content.
  - **Constraint**: only confirmed on one tenant/clip so far (Harrisonburg VA) — worth a second real example before assuming the byte is always in the same spot/cause.
  - **History**: WO-134, 2026-09-09.

- **[NEEDS-AUDIT] `wo134_confirmed_hits_ingest.py`'s Granicus fallback treats a bot-blocked homepage fetch as a hard `error` instead of a content-classified `skipped` — 22 real, confirmed cases in one batch, all the same root cause.**
  - **Issue**: when a candidate row's `hit_source_urls[granicus]` is just the government's own bare homepage (not a real `*.granicus.com` URL or `ViewPublisher.php`/`AgendaViewer.php` path — a WO-133 headless-scan artifact, not a granicus.py bug), `granicus_locate_listing()` guesses `ViewPublisher.php?view_id=1..5` on the row's domain, and when that guess also comes up empty it falls back to fetching the bare homepage URL directly through `GranicusAssetFinder.resolve()`. 21 of 22 confirmed cases got a flat HTTP 403 back (one HTTP 520, one `SSLCertVerificationError`) — the same Akamai/WAF-style bot-blocking this file already documents elsewhere for plain-homepage fetches. The adapter's exception propagates all the way up as `RowError` (`"granicus: resolve raised: HTTP 403 for https://www.columbus.gov/Home"`), not a `RowSkip`.
  - **Impact**: confirmed live 2026-09-10, WO-139 (`wo139_confirmed_hits.csv`, 158 rows): 22 of 158 (14%) came back `error` rather than a content-classified `skipped`, all one shape — Columbus OH, Fort Collins CO, Salinas CA, Lakewood CO, Kansas City KS (`wycokck.org`), Syracuse NY, West Palm Beach FL, Renton WA, Melbourne FL, Commerce City CO, Goose Creek SC, Littleton CO, Florence AL, Quincy IL, Gillette WY, St. Charles IL, Dana Point CA, Bell CA, West Springfield MA, Union City GA, South Pasadena CA, San Fernando CA (gov_ids in `rtr-business/research/backfill_wo134_errors.csv`). An `error` outcome (a) needlessly counts toward `MAX_CONSECUTIVE_ERRORS` (didn't trip the breaker this run, but a future batch skewed toward this exact shape could), and (b) is permanently excluded from `jurisdiction_coverage.csv` by `backfill_wo134_ingest_into_jc.py`'s design (errors mean "retry me") — but re-running these 22 unchanged hits the identical wall every time, since the fallback URL never changes; they'll never resolve without a code fix.
  - **Next action**: in `granicus_locate_listing()`'s fallback path (`scripts/wo134_confirmed_hits_ingest.py`), wrap the final `return hit_url, ""` fallback's *caller* (`resolve_seed()`'s granicus branch) so a fetch/HTTP failure on that bare fallback URL raises `RowSkip("granicus: hit_url unreachable ({status}), no listing found")` instead of letting the adapter's exception surface as `RowError` — same shape `civicplus`'s branch already uses for "no reachable AgendaCenter page found" rather than crashing. Re-run the 22 gov_ids above once fixed to confirm they land as `skipped`/`no-platform-link-found` rather than `error`.
  - **Constraint**: this is a batch-ingest-script bug (`wo134_confirmed_hits_ingest.py`), not a production `app/platforms/granicus.py` bug — the fix belongs in the script's own fallback wrapper, not the adapter itself, since `GranicusAssetFinder.resolve()` correctly raising on an unreachable/blocked URL is the right behavior for a live resolve request.
  - **History**: `rtr-business/research/ENUMERATION_METHODS.md` §160, WO-139, 2026-09-10.

- **[NEEDS-AUDIT] `[EXAMPLE]` A newer CivicPlus product generation ("HCMS", a client-side-rendered SPA) has no adapter support at all — `civicplus.py` only handles the older server-rendered `catAgendaRow` table.**
  - **Issue**: confirmed live 2026-09-09, El Mirage, AZ (`elmirageaz.gov/AgendaCenter`) — the fetched HTML has zero `catAgendaRow` matches; instead it carries `window.hcmsClientToken`, a JWT with `client_id: "az-elmirage:default"`, and asset URLs under `content.civicplus.com/api/assets/...` — a fully different, JS-rendered CivicPlus product ("HCMS") that never server-renders its AgendaCenter table at all. A plain HTTP fetch (what `civicplus.py` and every ingest script's own seed-guessing does) sees an empty shell. Spot-checked two other WO-129 CivicPlus tenants the same session: Bremen, GA and Peachtree City, GA are both still the legacy server-rendered product (0 `hcmsClientToken` matches); Vernon Hills, IL has 121 real `catAgendaRow` rows. So this looks like a real but partial migration, not a wholesale platform shift.
  - **Impact**: unknown how many CivicPlus tenants nationwide are already on HCMS — every one of them currently resolves to "no reachable AgendaCenter page found" with no way to tell that apart from a tenant that's simply not on CivicPlus at all, or one with an empty AgendaCenter.
  - **Next action**: per this project's own "test against a real, live URL first" rule — find 2-3 more confirmed HCMS tenants before building anything, then check whether `content.civicplus.com`'s API (the same one the JWT scopes into, `civicplus.apps.{tenant}.contents.*.read`) is reachable without the page's own browser session, the way other SPA-fronted platforms in this repo (CivicClerk, eScribe) already resolve via their tenant's own API rather than scraping rendered HTML.
  - **Constraint**: `[EXAMPLE]` — needs more real samples before any adapter work, not just El Mirage alone.
  - **History**: WO-134, 2026-09-09.

- **[NEEDS-AUDIT] `[EXAMPLE]` Two real, unsupported video platforms found live sitting one click from a CivicPlus AgendaCenter page that `adhoc_civicplus_pipeline.py` marked `no-video-found` — `spectrumstream.com` (in the AgendaCenter row itself) and `12milesout.com` (on the government's own homepage nav).**
  - **Issue**: resolving the WO-127/WO-128 "no video" contradiction (WO-137, 2026-09-09 — see `BACKLOG_DONE.md`) turned up two new video platforms, confirmed live, one sample each. (1) Alhambra, CA (`alhambraca.gov/AgendaCenter`) has real, recent (within days) per-meeting `td.media` links to `spectrumstream.com/streaming/alhambra/meeting_{date}.cfm` — well within `_RETRY_LIMIT`, so `_find_candidate_rows()` reads them fine, but `detect_platform()` doesn't recognize `spectrumstream.com` at all, so `_is_real_video_link()` rejects every one and the page reads as having zero video candidates. The page itself is a real "Video Player" wrapping a JW-Player-style `file:` pointing at a real S3-hosted MP4 (`spectrum_streaming.s3.amazonaws.com/alhambra/alhambra_2026_07_27.mp4`) — confirmed by fetching one directly. (2) Escondido, CA's AgendaCenter module is genuinely empty (zero `catAgendaRow`s, zero configured categories — not a JS-hidden case), but its homepage links to "City Council Meeting Broadcasts" → `escondido.12milesout.com`, a real, plain-HTTP, server-rendered per-meeting video archive (`/Video/Meeting/{uuid}` links, real recent dates through 9/2/2026) that no code in this repo recognizes.
  - **Impact**: both governments are currently counted among the 521 CivicPlus `no-video-found` verdicts; both actually have real, resolvable video. Unknown how many of the other 519 share either shape — this was found via a 30-government live sample, not a targeted search for either domain.
  - **Next action**: per this project's own "test against a real, live URL first" rule, find 2-3 more confirmed samples of each domain before building either adapter (`external_hosts.txt` in `rtr-business/research` already has 2 unexamined `spectrumstream.com` hits from an earlier crawl — check those first). Once confirmed on multiple tenants: `spectrumstream.com` needs a `detect_platform()` entry plus a small adapter (the `.cfm` page's embedded JW-Player `file:` URL is the direct MP4, per Alhambra); `12milesout.com` needs the same plus per-meeting date/title matching against its `/Video/Meeting/{uuid}` listing.
  - **Constraint**: `[EXAMPLE]` — one confirmed live sample each is not enough to build an adapter from; don't generalize the page shape from a single tenant.
  - **History**: `BACKLOG_DONE.md`, WO-137, 2026-09-09.

- **[NEEDS-AUDIT] `civicplus.py`'s own docstring claims AgendaCenter rows render "newest-first" across the whole page — real, confirmed false for multi-category tenants; rows are newest-first *within* each category, with categories concatenated, not globally date-sorted.**
  - **Issue**: confirmed live 2026-09-09 (WO-137) on lowellma.gov/AgendaCenter (330 rows): each `tr.catAgendaRow` sits inside a `<div id="category-panel-{N}">` wrapper (City Council rows 0-28, then several unrelated boards, then the Lowell License Commission's own rows starting at index 199) — each category's own rows are newest-first, but the categories themselves are concatenated in some category-ID order, not merged by date. `_find_candidate_rows()`'s and `resolve()`'s `_RETRY_LIMIT`-bounded walk (both `civicplus.py` and `adhoc_civicplus_pipeline.py`) assumes the first 5 DOM rows are the 5 most recent meetings on the whole page; for a tenant whose first-rendered category doesn't happen to have a recent video-bearing row, this can never reach a genuinely more-recent video sitting in a later category, no matter how small or large `_RETRY_LIMIT` is.
  - **Impact**: measured on Lowell specifically: even walking the full 330-row page and correctly excluding `@handle`-only channel links (not real single-video links), the most recent genuinely resolvable per-meeting video is 6+ months old (License Commission, March 2026) — so this bug did not actually flip Lowell's real "no video" verdict in this instance, but the wrong assumption is real and would matter for a tenant whose first category is stale while a later category has a currently-active video-bearing series.
  - **Next action**: sort `_find_candidate_rows()`'s returned list by parsed date (falling back to original DOM order for the unparseable minority) before `resolve()`'s retry walk uses it, so "the 5 most recent candidates" is true globally, not just within whichever category the DOM happens to render first. Update the class docstring's "same rendering order this page already uses" claim once fixed.
  - **Constraint**: low priority on its own (didn't change any real verdict in the one confirmed case) — worth doing opportunistically alongside other `civicplus.py` work, not urgent by itself.
  - **History**: `BACKLOG_DONE.md`, WO-137, 2026-09-09.

- **[NEEDS-AUDIT] `scripts/build_jurisdiction_data.py`'s blanket `.decode("latin-1")` on raw Census source files double-corrupts the handful of rows whose real source bytes are UTF-8 — confirmed live, 23 real government names affected, root cause traced but not fixed at the generator.**
  - **Issue**: found 2026-09-10 investigating why `lacanadaflintridge-ca.granicus.com` never resolves a gov_id — `us_places.csv` stored the government's real name as `La CaÃ±ada Flintridge city` instead of `La Cañada Flintridge city`. That's classic double-encoding: the real source bytes for this row are UTF-8 (0xC3 0xB1 for "ñ"), but `build_jurisdiction_data.py` (line ~92/94) blanket-decodes every raw Census source file as `latin-1`, so those two UTF-8 bytes get read as two separate Latin-1 characters and re-encoded wrong. Same corruption hit 22 more rows across `us_places.csv`, `us_counties.csv` (mostly Puerto Rico municipios — Bayamón, Mayagüez, Añasco, etc. — plus Doña Ana County, NM), and `us_school_districts.csv`.
  - **Impact**: a corrupted name can never validate against real page text or a subdomain hint, so every one of these 23 governments was permanently unmatchable by name regardless of URL-parsing quality — not a rare edge case, since Puerto Rico's entire county-equivalent table (78 municipios) is disproportionately exposed (17 of 78 already confirmed corrupted).
  - **Next action**: the 23 already-corrupted rows are fixed directly in the checked-in CSVs (see the PR from this session, 2026-09-10) — this entry is about the generator itself, which will re-corrupt the same rows (and any other UTF-8-sourced row not yet noticed) on the next regeneration. Needs a per-row encoding detection (try UTF-8 first, fall back to `latin-1`, or an explicit list of known-UTF-8 source rows) rather than the current blanket decode — the fix must not touch the thousands of rows that genuinely are Latin-1 and decode correctly today.
  - **Constraint**: don't blanket-switch the decode to `utf-8` either — that would break whichever rows are genuinely Latin-1 (the Census source files predate consistent UTF-8 encoding, hence the original choice). Needs verification against real source bytes, not a guess.
  - **History**: gov-id enumeration audit, 2026-09-10 (this session).

- **[NEEDS-AUDIT] `finalize_jurisdiction()`'s table validation doesn't fold diacritics, so a real government's own page text (almost always spelled without the accent) can't match its own correctly-accented Census table entry.**
  - **Issue**: confirmed live 2026-09-10 on La Cañada Flintridge, CA — even after fixing the table's own encoding corruption (see the sibling entry above), the government's real Granicus page spells its name "La Canada Flintridge" (no tilde, confirmed via the page's own meta description). `finalize_jurisdiction("City of La Canada Flintridge", ...)` returns `confidence="unverified"`, while the identical string WITH the accent returns `confidence="validated"` — a byte-for-byte match is required, so the overwhelmingly common real-world spelling never validates against the table's official one. (Separately, `_table_lookup()`'s own subdomain-tier matching for `validated_subdomain_extract()` appears to fold accents already — `canoncityco` → `Canon City` succeeded post-fix without the accent — so the inconsistency is specifically in `finalize_jurisdiction()`'s own validation path, not universal across this file.)
  - **Impact**: every government with a diacritic in its official Census name (not just the 23 rows the sibling entry fixed — this is the more general, ongoing gap) will keep failing to auto-resolve from real page text, landing as "Unknown Jurisdiction" or requiring a manual pin, purely because real-world text drops accents and the validator doesn't account for that.
  - **Next action**: add accent-folding (e.g. NFKD-normalize and strip combining marks) to whichever comparison `finalize_jurisdiction()`'s table-validation step uses, so an accent-free candidate can still validate against an accented table row — mirroring whatever `_table_lookup()` already does for the subdomain tier. Needs care: `finalize_jurisdiction()` is heavily tuned (see this file's own tournament-testing comments), so verify against the existing test suite and the tournament data before changing it, not just the one confirmed case.
  - **Constraint**: don't fold accents in a way that creates a new collision (two distinctly-named real governments that only differ by a diacritic) — check for that before shipping.
  - **History**: gov-id enumeration audit, 2026-09-10 (this session).

- **[NEEDS-AUDIT] Guessing a fixed meetings-page path only works for CivicPlus so far — Revize's own confirmed live test found 0 of 17.**
  - **Issue**: WO-154 (2026-09-10) built `scripts/cms_fingerprint.py` to recognize a government website's CMS family (CivicPlus, Revize, OpenCities, ProudCity, Municode's meetings module, Town Web, CivicLive) and recorded a candidate meetings-page path per family in `app/utils/jurisdiction_data/cms_families.csv`. Only CivicPlus's `/AgendaCenter` is confirmed reliable (45 of 47 real training pages). Revize was live-tested on 17 real governments already recorded `no-platform-link-found`: guessing `/government/agendas_minutes.php` and `/agendas-minutes` found a real listing on **0 of 17** — Revize sites don't 404 a wrong guess, they return a real HTTP 200 "page not found" template (a "Your Link Name" social-share placeholder) that a naive check can misread as real content. `/Council/Agendas-and-Minutes` (OpenCities) 404'd live on 2 confirmed OpenCities governments (San Fernando CA, Littleton CO); `/meetings` (ProudCity) worked on 1 of 2 tried.
  - **Impact**: a future sweep that assumes "recognize the family, then fetch its one known path" will work well for CivicPlus and poorly-to-not-at-all for Revize, OpenCities, Town Web, and CivicLive as currently documented — Revize alone was the single most common family found in a 300-government `no-platform-link-found` sample (17 of 238 fetched, 7.1%), so this isn't a minor case.
  - **Next action**: for Revize specifically, don't guess a path — follow the real nav link already present in the fetched homepage (the government's own menu almost always names the real page in plain text, e.g. "Agendas & Minutes"); this is closer to what `generic_fallback.py`'s existing two-hop link-following already does than to a fixed-path guess. For OpenCities/ProudCity/Town Web/CivicLive, gather more real confirmed examples (each has under 15 training pages today) before trusting any path pattern at scale.
  - **Constraint**: `[EXAMPLE]` — don't generalize a path pattern from the single-digit sample sizes in `cms_families.csv` today; the table says so plainly per family rather than asserting one.
  - **History**: `BACKLOG_DONE.md`, WO-154, 2026-09-10; full numbers in `~/Documents/rtr-business/research/wo154_methods_section.md`.

- **[EXAMPLE] Streamline Website Solutions has no confirmed real example for the CMS-family fingerprinter — 0 of ~240 pages checked.**
  - **Issue**: WO-154 (2026-09-10) checked roughly 240 real government pages (training + negative sample) for a genuine "Streamline Website Solutions" vendor marker (`streamlinewebsites.com` or similar) while building `scripts/cms_fingerprint.py`. Every substring hit on the bare word "streamline" was unrelated (an analytics runtime flag, unrelated marketing copy, a different vendor's tagline) — no real confirming page was found, so no detection rule was built for it.
  - **Impact**: Streamline is named in `app/utils/jurisdiction_data/cms_families.csv` as a known-absent family (0 training pages) rather than silently missing — any government actually built on Streamline is currently invisible to the fingerprinter and falls through to `unknown`.
  - **Next action**: per this repo's "test against a real, live URL first" rule, find a real Streamline-built government site (a targeted search for the vendor's own customer list, or a hit from a future sweep) before writing a detection rule.
  - **Constraint**: `[EXAMPLE]` — do not guess at a marker string without a confirmed live page.
  - **History**: `BACKLOG_DONE.md`, WO-154, 2026-09-10.

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

- **[JUST-DO-IT] `_existing_tier3_queue_urls()`'s dedup key is an exact
  string match, so two differently-formatted URLs for the SAME video can
  both queue — confirmed live, one real duplicate line produced and
  removed by hand.**
  - **Issue**: `scripts/wo134_confirmed_hits_ingest.py`'s
    `_existing_tier3_queue_urls()` (shared by every WO-130/134/139/145-149
    -style sweep) compares the new URL against the queue file's existing
    first-tab-field values as plain strings. WO-149's county sweep queued
    `https://www.youtube.com/embed/AscWHEa0ay4?enablejsapi=1&autoplay=0&
    ...&disablekb=0&` (Lake County, OH) as a "new" URL even though the
    exact same video (`AscWHEa0ay4`) was already on the queue from
    earlier work as a slightly differently-formatted string — same video
    id, different player-widget query parameters attached. Caught by
    `tests/test_transcription_queue_files.py`'s dangling-query-separator
    check (the messy URL also had a trailing bare `&`), not by the dedup
    logic itself, which is the actual bug.
  - **Impact**: a real, exact-content duplicate line reached the queue
    file in this WO's own run (removed by hand, see `BACKLOG_DONE.md`'s
    WO-149 entry) — the dedup check gave false confidence that "not an
    exact string match" meant "not a duplicate."
  - **Next action**: extract each platform's stable video id (YouTube:
    the 11-char id already extracted by `_YT_ID_RE`/`canonicalize_
    youtube_url()`-style logic in `scripts/wo149_county_ladder_sweep.py`;
    Vimeo/TelVue/Cablecast have their own id shapes already used by
    `_tenant_override_match()`) and dedup on that instead of the raw URL
    string.
  - **Constraint**: don't over-generalize from one confirmed case yet —
    worth checking whether the existing ~2,180-line queue file has more
    of these before committing to a specific normalization function.
  - **History**: WO-149, 2026-09-10.

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

### A bare YouTube channel-listing scan measurably ingests non-meeting videos — 7 of 16 real examples across two independent sessions, all matching the title allowlist by accident `[NEEDS-AUDIT]`

- **Issue**: `wo134_confirmed_hits_ingest.py`'s `resolve_youtube_channel()`
  (used by every `nationwide_*`/`wo1*_confirmed_hits_ingest`-style sweep,
  including WO-130/134/139/149) lists a government's YouTube channel's
  most recent uploads and keeps the first that passes
  `_looks_like_real_meeting(..., require_allowlist=True)` — a word match
  against `MEETING_ALLOWLIST` ("council", "board", "commission", ...).
  Two independent same-day sessions found the identical gap from
  different angles. **WO-147's** 40-government pilot found 3 of 8
  channel-sourced hits are not real meetings despite passing that check,
  because a body name shows up in an unrelated video's own title too:
  "HAIRitage 2026 CROWN Act Workshop: Advice from Our Commissioner
  Board" (Union County, NJ), "Commissioners Tour Picatinny Arsenal's
  Revolutionary Roots" (Morris County, NJ), "Council Participation
  Instructions" (Fort Collins, CO). **WO-149's** full county sweep found
  4 of its own 159 tier-1/2 ingests were not real meetings, all via the
  same channel-listing fallback: "Larry J. Dix Boardroom" (Adams County,
  NE, a 59-second room-name livestream title — this one was a plain
  substring bug, `"board" in title` matching "Boardroom", now fixed with
  word-boundary matching, `_contains_word()`), "What Does a County
  Commissioner or Council Member Do?" (Millard County, UT, a 2017,
  2m51s civics explainer), "Pennsylvania Fish and Boat Commission Water
  Conservation Officer training: Boating Scenarios" (Perry County, PA —
  a *state* agency's own training video, wrong government entirely),
  and "Senate Bill 152: Foreign Funding Restrictions of Ballot Measures
  for Entities Other Than Committees" (Osage County, MO, a state-
  legislation explainer clip). The Adams County bug is fixed; the other
  6 are the same still-open, harder gap: a real allowlist word
  ("commissioner"/"council"/"commission"/"committees"/"board") appears
  in a title that a human would instantly recognize as not a meeting.
  WO-149's 3 remaining pages are flagged for deletion in
  `~/Documents/rtr-business/research/wo149_flagged_for_review.csv`. The
  other 5 of WO-147's 8 pilot hits — a specific already-linked video, a
  curated playlist, or a non-YouTube platform — were all real meetings;
  a curated "Board Meetings" playlist is a much stronger signal than a
  channel's raw upload list, which mixes everything the government ever
  posts.
- **Impact**: a wrong video can reach a live tier-1/2 page immediately
  (this path has no probe/review gate at all, unlike tier 3) or sit in
  the tier-3 queue as a real, current-looking but wrong "meeting" —
  undermining the "we ingested a real government meeting" claim this
  project makes across every WO write-up. Scope is unknown: this
  resolution path has been in production since WO-130 (2026-09-09) with
  no equivalent check, so already-ingested/queued pages may carry the
  same defect; nobody has audited them for it. Confirmed rate so far:
  7 of 167 combined channel-sourced hits across the two pilots/sweeps —
  roughly 4%, not a one-off.
- **Next action**: a duration floor alone does not fix this — WO-149's 3
  still-open cases ran 77s/171s/206s, all above the existing 60s
  `MIN_PLAUSIBLE_MEETING_SECONDS` floor used elsewhere (see the
  "Duration alone..." entry below, a related but distinct problem;
  WO-147's 3 examples' durations were not recorded). The
  real signal is topical, not temporal: before loosening/tightening
  `MEETING_ALLOWLIST` itself (risking false negatives on real meetings
  titled unusually — "LCBOC CM 8 25 26" in WO-147's pilot has no
  allowlist word spelled out and is real), design a check specific to
  *channel-listing* resolution (the playlist/direct-link paths don't
  need it, 5/5 and clean elsewhere in both sessions' samples) — e.g. a
  date-shaped token requirement, a `PROMO_BLOCKLIST`-style negative
  signal for explainer/training/state-level content, or holding
  channel-listing results for a lower-trust review queue rather than a
  direct tier-1/2 ingest. WO-147's own driver
  (`scripts/wo147_access_ladder_sweep.py`) already adds a non-blocking
  `channel_scan_caution()` note (`is_bare_youtube_channel_hit()`) to any
  row from a bare channel/handle/vanity URL — a mechanical proxy for
  "needs a human title check," reusable by whoever builds the real fix;
  WO-149's own driver (`scripts/wo149_county_ladder_sweep.py`) does not
  yet call it.
- **Constraint**: `MEETING_ALLOWLIST`/`PROMO_BLOCKLIST` are shared by
  every existing sweep script — don't change either from a 16-example
  combined sample; the false-negative risk on real, unusually-titled
  meetings is as real as the false-positive risk this entry documents.
  Don't hard-delete WO-149's 3 flagged pages without a human decision.
- **History**: found live during WO-147's and WO-149's required pilot/
  full-run hand-verification steps, both 2026-09-10. See
  `BACKLOG_DONE.md`'s WO-147 and WO-149 entries.

### A live page is keyed to the wrong government entirely — Bamberg County, SC's YouTube livestream page displays as Nottoway County, VA `[NEEDS-AUDIT]`

- **Issue**: `/m/bamberg-county-sc-livestream` (page_id 6124, `source_url`
  `https://www.bambergcounty.sc.gov/county-council/livestream`) is stored
  with `gov_id=us:county:51135` (Nottoway County, VA), `names_match=yes`,
  `jurisdiction_confidence=registry`, and `meeting_name="Welcome to
  Nottoway County, Virginia"` — and the live page's `<title>`, meta
  description and JSON-LD all render as Nottoway County, VA. Confirmed
  the source page itself says none of this: `curl` of the real Bamberg
  County SC URL contains "Bamberg" 96 times and "Nottoway" zero times, so
  the wrong jurisdiction/meeting-name text didn't come from the page —
  it was attached to this row somewhere in our own pipeline. No other row
  in the 2026-09-09 inventory export shares `gov_id=us:county:51135` or a
  `bambergcounty.sc.gov` source, so this isn't a clean two-row swap; it
  looks like a single corrupted row, cause not yet found.
- **Impact**: a real government (Bamberg County, SC) is invisible under
  this URL, and a reader who finds this page via search or a Nottoway
  County link sees a livestream and meeting name that have nothing to do
  with Virginia. Exactly the "mediocre outcome" Ryan flagged for bad
  gov-id/display-name enrichment — this passed WO-131's stated identity
  filter (`names_match=yes`, national-table `gov_id`) despite being
  wrong, so that filter alone isn't sufficient proof of a good page.
  WO-131 manually excluded this one page from its YouTube-transcript
  push list rather than trusting the filter here.
- **Next action**: find which ingest step wrote Nottoway's identity onto
  Bamberg's URL (a likely candidate: a `nationwide_NNNN_ingest.py` batch
  run processing adjacent CSV rows with an off-by-one or shared-buffer
  bug), fix the row by hand once found, and spot-check nearby rows from
  the same ingest batch for the same contamination.
- **History**: found while building WO-131's identity-checked slug list,
  2026-09-09; not otherwise investigated.

### `[EASY]` YouTube video-ID regex accepts a generic "live stream" embed placeholder as if it were a real 11-character video ID

- **Issue**: `_VIDEO_ID_RE` in `app/platforms/youtube.py` captures any
  `[A-Za-z0-9_-]{11}` following `embed/` (etc.). A source page whose
  embed is a generic "watch whatever's live now" widget rather than a
  specific archived video — `.../embed/live_stream` (YouTube's own
  reserved literal for "current live stream on this channel", exactly 11
  characters) or `.../embed/livestreaming?rel=0` (truncates to the
  11-char `livestreami`) — matches the same as a real ID, so
  `resolve_video_id()` treats it as a real video and only fails later, at
  transcript-fetch time (`VideoUnavailable`/`VideoUnplayable`).
- **Impact**: low — confirmed on 2 live pages in the 2026-09-09 export
  (`mount-vernon-tx`, `bamberg-county-sc-livestream` — the latter is also
  the mis-keyed-government entry above), both of which already show no
  video/transcript to readers, so the reader-facing outcome is the same
  as a correctly-detected "no real video." This is a diagnostic-accuracy
  gap, not a content-correctness one. Found while building WO-131's
  YouTube-transcript identity filter, not chased further.
- **Next action**: reject the literal `live_stream` outright, and treat
  an extracted ID containing "livestream" as suspect rather than a real
  video ID.
- **History**: found 2026-09-09, WO-131.

### Meeting body is blank on ~90% of archived pages `[NEEDS-AUDIT]` `[BIG]`

- **Issue:** `MeetingPage.meeting_body` (the governing body -- "City
  Council", "Planning Commission") is stored on only 667 of 6,529 pages
  (2026-09-09, `GET /internal/meeting-inventory/summary`); only Granicus
  (RSS channel title), Legistar (`body`) and Invintus (categories) send
  it, plus the "<Entity> of <Place>" name-split fallback, and some stored
  values are platform folder names ("City Council View").
- **Impact:** The user's mental model -- gov type says *what* Tampa is, body
  says *which* body of Tampa met -- can't be reported or browsed for most
  pages; the inventory report deliberately shows the blank rather than
  guessing from titles.
- **Next action:** Decide the source per platform (an adapter field where
  the platform has one; a reviewed title-phrase table otherwise, applied
  at ingest and backfilled with its confidence recorded, never at
  render), then extend the report's tile to track the count down.
- **Constraint:** Don't populate it from a title regex at read time -- the
  report exists to count the real gap, and a guess would hide it.
- **History:** Report built under WO-124 (`scripts/export_meeting_inventory.py`);
  first run's numbers in this entry.


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

### `[NEEDS-AUDIT]` "County of {Name}" jurisdiction prefix form isn't California-specific, and the Granicus RSS-title source is now confirmed

- **Issue**: some county pages store `jurisdiction` as `"County of
  {Name}, {state}"` (a raw, unnormalized prefix form) instead of this
  project's own majority convention, `"{Name} County, {state}"`.
  Confirmed live 2026-09-02 via `GET /internal/export/pages` (all 4,923
  archived pages): 44 CA counties use the suffix form correctly, but 13
  — Fresno, Humboldt, Imperial, Marin, Monterey, Napa, Placer, Plumas,
  San Bernardino, San Diego, San Mateo, Santa Clara, Solano — have at
  least one page stored as `"County of {Name}, CA"`.
  **Update 2026-09-06**: the 350-tenant HTTP wildcard-sweep pipeline
  (`scripts/adhoc_wildcard_sweep_pipeline.py`) confirms this is neither
  California-specific nor unconfirmed — two brand-new non-CA tenants
  resolved straight to the prefix form (Sedgwick County, KS via
  `sedgwick.granicus.com`'s own channel title "County of Sedgwick", and
  Cleveland County, NC via `clevelandcounty.granicus.com`'s "County of
  Cleveland, North Carolina"), plus Imperial County CA re-confirmed
  independently via `imperial.granicus.com`. In every case the value
  traces directly to the tenant's Granicus RSS `<title>` (`granicus.py`'s
  `channel_jurisdiction` path, ~line 654) being stored verbatim — exactly
  the suspected-but-unconfirmed source `_split_entity_prefix()`'s
  docstring pointed at.
- **Impact**: real, measured fragmentation for at least 3 CA counties —
  the same government's pages split across two different `/j/{slug}`
  hubs, invisible to each other: Santa Clara (7 pages under the correct
  suffix form, 1 stranded under the prefix form), San Diego (2 vs 1),
  Solano (1 vs 1). Marin (3 pages) and San Mateo (3 pages) aren't
  fragmented yet only because no suffix-form page exists for them yet —
  the next Marin/San Mateo County resolve could create the same split.
  Originally surfaced as a user report ("Napa County was already live in
  prod but called 'County of Napa'") — Napa itself has only the prefix
  form so isn't fragmented, but is the same underlying bug. Sedgwick
  County, KS and Cleveland County, NC (both newly ingested 2026-09-06)
  start life already in the prefix form with no suffix-form counterpart
  yet.
- **Next action**: route Granicus's `channel_jurisdiction` value (the RSS
  `<title>` text) through the existing `_split_entity_prefix()`
  normalization before it's stored, instead of bypassing it (confirmed
  bypass, not just suspected, per the update above); separately, a
  one-time backfill/merge is needed for the 3 already-fragmented CA
  counties (re-resolve or hand-correct the stranded pages' `jurisdiction`,
  then re-check `/j/{slug}` hub grouping) plus Sedgwick County, KS and
  Cleveland County, NC.
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

### `[NEEDS-AUDIT]` A customer's own Granicus channel-title suffix survives into the stored jurisdiction verbatim

- **Issue**: Granicus's `channel_jurisdiction` path (`granicus.py`
  ~line 654, RSS `<title>` taken verbatim once it passes the existing
  domain-shape guard) has no check for descriptive/technical text a
  customer appended to their own channel name. Two confirmed real
  cases from the 2026-09-06 350-tenant wildcard-sweep pipeline
  (`scripts/adhoc_wildcard_sweep_pipeline.py`): `enterprise.granicus.com`
  stored jurisdiction `"Enterprise - H264 Only"` (a video-codec note the
  customer appended to their own channel title, not part of the
  jurisdiction name), and `yorkcounty.granicus.com` stored
  `"York County Video Services"` (the customer's AV department name,
  not the county itself).
- **Impact**: both pages are live in production with a jurisdiction
  string a reader would find confusing or wrong
  (`/m/enterprise-2012-09-06-...`, `/m/york-county-video-services-2017-08-09-...`)
  and neither hub-groups correctly with any future same-government page
  that resolves the name cleanly.
- **Next action**: extend `granicus.py`'s existing colon-split jurisdiction
  guard (the one that already declines a domain-shaped title, see the
  2026-08-29 comment right above it) with a small denylist/pattern for
  trailing technical or department-name suffixes (` - H264 Only`,
  ` Video Services`, similar codec/AV-department noise) — decline rather
  than guess, consistent with the rest of that module's posture. Two
  confirmed real examples isn't enough to know the full shape of this
  yet; treat any fix as provisional until a few more surface.
- **Constraint**: don't build a broad free-text jurisdiction validator
  for this — two examples. A narrow, decline-on-match guard for the
  specific noise patterns seen so far is enough; widen it only when a
  third real example doesn't fit the pattern.
- **History**: found live 2026-09-06 during the 350-tenant HTTP
  wildcard-sweep ingest pass; not yet in `BACKLOG_DONE.md`.

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
  pass as the entry above; not yet in `BACKLOG_DONE.md`. Second confirmed
  instance, 2026-09-06: all 3 sampled Ogden, UT City Council YouTube
  videos (found via web search while manually chasing a wildcard-sweep
  gap, `ogdencity.granicus.com`'s own guessed slug was dead) resolved
  with real transcripts (0, 2,798, 8,304 segments) but `jurisdiction=None`
  every time — correctly declined ingestion this round rather than
  patched around, per the standing rule of only ingesting a YouTube
  result when it carries both real meeting data and a resolved
  jurisdiction. Third confirmed instance, 2026-09-09 (WO-127): the same
  gap applies at tier3-queue time too, not just direct ingest — 10
  CivicPlus-delegated YouTube/Vimeo/Viebit tier3-video-only candidates
  would lose their known government entirely when
  `feed_tier3_auto_transcription.py` re-resolves the bare video URL
  later (no jurisdiction hint travels with a queued URL, only an
  optional `source_url` override). Mitigated per-video via 10
  `app/utils/jurisdiction_data/tenant_overrides.csv` pins
  (`source=wo127_civicplus_pipeline`) rather than left to self-correct —
  same "per-page patch, not a fix" caveat as Portola Valley above; a
  future tier3-queue entry with an unpinned, self-unidentifying channel
  will hit this same gap again.

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

### Video-to-calendar join: match a government's video source to its own calendar by body and date `[PARK]` `[BIG]`

- **Issue:** Governments that publish meeting video on a channel, playlist
  or video feed with no link from the meeting page are the largest reason
  a government with video is still missing (17 of 30 "no video found"
  CivicPlus sites in WO-137). Joining the video source to the site's own
  calendar by body name and date recovers some of them.
- **Impact:** Pilot WO-158: 2 real matches in 40 CivicPlus "no video found"
  sites, about 5%, roughly 35 to 40 governments across that bucket; some
  risk of off-mission video without the body-name check.
- **Next action:** When picked up, read `docs/VIDEO_TO_CALENDAR_JOIN.md`
  first; it holds the pilot, the safety rules, the failure shapes and
  what running at scale needs.
- **Constraint:** Shelved by Ryan 2026-09-10 for modest yield; allowed
  back. Metadata-only video calls until a match is confirmed; ties
  decline; the government's gov id is passed into ingest.
- **History:** `ENUMERATION_METHODS.md` §193 (rtr-business); script and
  result files `research/wo158_*`. Supersedes the 2026-08-26 "YouTube
  Atom-feed polling" entry, now in `BACKLOG_DONE.md`.

### Friday-night queue (2026-09-12): the token-heavy coverage passes `[PARK]`

- **Issue:** Three passes from the 2026-09-09 coverage review were
  explicitly held for the weekly reset because they burn tokens or
  compute: (a) a headless-browser re-check of the 3,144 governments over
  5,000 people rejected as `no-platform-link-found` (a small trial
  recovered ~55% of 403s; the plain-HTTP CivicPlus AgendaCenter probe,
  WO-127, runs first and shrinks this list); (b) repairing the 475
  `dns-unresolvable` domains against the state directories and CISA's
  .gov list; (c) anything needing Playwright.
- **Impact:** Together these are most of the remaining "has a domain,
  no page" gap for larger governments.
- **Next action:** After WO-127..131 report, rebuild the coverage
  registry (`research/refresh_coverage_registry.sh`), re-count these
  groups, and run (a) then (b) as separate agents.
- **Constraint:** Headless browsing is resource-intensive; not before
  the Friday reset. Never on a host behind an explicit human-verification
  gate.
- **History:** WO-124 review thread, 2026-09-09.

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
