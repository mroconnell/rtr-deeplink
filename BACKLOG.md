# Backlog

**Open items only.** Completed work — including the investigation detail
behind each fix — lives in [BACKLOG_DONE.md](BACKLOG_DONE.md); entries
below link back to it for context. Ideas nobody has triaged yet live in
`CLAUDE_BACKLOG.md`, and the daily Routine's unreviewed findings live in
`CLAUDE_INBOX_TRIAGE.md` — neither is this file.

**The big pieces of work** (the ones that change what readers get) are
tracked on the Backlog Kanban board:
https://claude.ai/artifact/QpbFxqYVLhfExLVKJ2U7tC. Their entries stay
here as the record. `docs/BACKLOG_PHASES.md` is retired (2026-10-16).

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

**Claim tag (2026-10-16).** When work on an entry is under way or
assigned out, its Next action starts with `**Claimed YYYY-MM-DD** (<who>,
<WO or PR>):` and one short line on what is happening. Ryan or the
conductor that assigned the work adds it. Remove the claim when the entry
moves to `BACKLOG_DONE.md` or the work stops.

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

Standing decisions — do NOT re-raise  (23)
  The tier-3 queue is hand-approved meetings, not crawling: robots.txt…
  English Whisper stays shown over a station's English captions; fix…
  No Viebit meeting can get a real transcript today -- confirmed at…
  Cablecast, Granicus, eScribe, and Swagit have no real `meeting_body`…
  Guessing a bare tenant name for a small government is unsafe unless…
  Bulk sweeps ingest only meetings that have video — agenda-only…
  Do NOT backfill partial transcripts onto historically-failed jobs…
  `jurisdiction_confidence IS NULL` is deliberately excluded from…
  Don't reach for a bigger Render plan before measuring what the peak…
  Never run an unbounded scan or bulk workload against the production…
  Prefer a generated/computed column over "add a column, then backfill…
  Never attempt to auto-solve a Cloudflare "Verify you are human"…
  Don't lower `dedupe_rollup_transcripts.py --min-retained` below 0.05
  Don't lower `MIN_PLAUSIBLE_MEETING_SECONDS` below 60s to catch more…
  Handover: 120 of the wildcard-sweep's 350 tenants remain unresolved —…
  The Archive files a page under whatever `gov_id` a sweep sends: do…
  A single job still makes N consecutive pulls to the same host — WO-40…
  [NEEDS-AUDIT] Phase 2d's signal-based recovery (WO-110,…
  Don't proxy Granicus/CivicClerk video bytes to clear Search Console's…
  [LATER] Tighten the two transcription workers to their real import…
  [LATER] Second transcription worker's auto-generation TOCTOU race —…
  `[LATER]` Prompt injection isn't a live product risk today, but the…
  `[LATER]` If a Content-Security-Policy is ever added, it must allow…

Ship next — root cause known, fix settled `[JUST-DO-IT]`  (3)
  Coverage registry: per-state view and other dashboard additions…
  iQM2's meeting body is only on the calendar listing page; fetch it…
  Granicus: discover a tenant's `view_id` so a bare tenant hub lists…

Needs a human — dashboard, prod, or product call `[HUMAN]`  (31)
  [HUMAN] Archive page 12994 carries a job label as its source address;…
  [HUMAN] Two Granicus lead-sheet feeds need Ryan's call: Gretna LA's…
  [HUMAN] WO-1165: 15 CivicMedia page renames, one refresh and one…
  [HUMAN] Promote the hidden transcript version on about 6 pages where…
  [HUMAN] 19 Cablecast pages still show label-only or empty station…
  [HUMAN] Run the re-transcription queue for the pre-voice-filter…
  [HUMAN] Other Cablecast pages with no `external_id` may be twins of a…
  Pin audit follow-up (WO-1186): 16 re-keyed Archive pages still carry…
  Existing Invintus pages need one re-resolve after WO-1065 deploys, to…
  After WO-1056 and WO-1057 deploy, re-resolve archived pages so…
  Finish the WO-310 fixes: 2 identity joins, 1 blank gov_id and 42…
  Production actions only Ryan should take  (5)
    [HUMAN] ~1,676 archived YouTube video ids have no channel on record…
    [HUMAN] Apply the reviewed wrong-page sheet,…
    [HUMAN] 13 archived YouTube pages point at a video that is gone (7…
    [HUMAN] Two TelVue stations (`gmcC3sJ6...`, `5ZgpAPx0...`) still have…
    [HUMAN] Town Square Television: 3 shows need re-filing, and South St.…
  Decisions about already-live content
  Laval's own archive: walk its ~260 meeting posts, then decide on the…
  Some tier-3 lines need YouTube but the drip Mac can't claim them, so…
  [JUST-DO-IT] 82 archived YouTube meetings have embedding switched off…
  [JUST-DO-IT] WO-1004 built a domain-health check for the registry's…
  `[NEEDS-AUDIT]` SharePoint share links (Yakima County, WA) resolve,…
  [JUST-DO-IT] `[EASY]` Page 8494 (Middletown Township, Delaware County…
  High Plains Water District (Granicus) transcribed to zero usable…
  [HUMAN] Five `youtu.be` pages for the Wasatch Front Waste & Recycling…
  [EASY] `scripts/wo288_youtube_date_backfill.py` is built and dry-run…
  [NEEDS-AUDIT] `[EASY]` Existing Vimeo meetings may be secretly tier…
  `[JUST-DO-IT]` Render *pipeline minutes* — build volume cut twice,…
  `[HUMAN]` YouTube-sourced transcripts and the data product: is there…
  `[IMPROVEMENT-ROUND]` Full Context entries on YouTube-backed meetings…
  [IMPROVEMENT-ROUND] Lifecycle-triggered transactional emails (Resend)…

Open bugs — real, root cause not settled `[NEEDS-AUDIT]`  (77)
  [NEEDS-AUDIT] Tampa deep links assume the video starts at the first…
  [NEEDS-AUDIT] Some stored captions do not line up with their video,…
  [NEEDS-AUDIT] Meeting Finder picks the wrong clip from a Granicus…
  [NEEDS-AUDIT] Near-empty station captions are only guarded on…
  [NEEDS-AUDIT] 10 Cablecast pages on shared cable-channel hosts have…
  [NEEDS-AUDIT] Every stored iQM2 recording tried on 2026-09-27 is gone…
  [NEEDS-AUDIT] `cablecast.py`'s "Cablecast Connect" resolve path 404s…
  [NEEDS-AUDIT] The government registry creates duplicate ids and…
  [NEEDS-AUDIT] Meeting Finder files another government's meeting under…
  [NEEDS-AUDIT] Meeting Finder's video gate rejects some real board…
  [NEEDS-AUDIT] Swagit tenants whose `/views/{id}` page is not known…
  [NEEDS-AUDIT] `[EASY]` `municode_meetings.py` cannot tell an…
  [NEEDS-AUDIT] `[EXAMPLE]` `civicplus.io`: platform or CivicPlus web…
  [NEEDS-AUDIT] Seven hand-confirmed government platform links still…
  Blackstone, MA's Castus hub walk resolves, but to a 5-day-stale…
  Self-hosted Castus VOD widget (`{tenant}.vod.castus.tv`) has no…  (23)
    [NEEDS-AUDIT] `[EASY]` Two writers still emit the dead…
    [NEEDS-AUDIT] Four Kind-A/wrong-domain findings from WO-349's…
    [NEEDS-AUDIT] 146 tier-3 queue lines on shared video hosts have no…
    [NEEDS-AUDIT] `[EASY]` Pierce County WA's tier-3 queue line may be a…
    [NEEDS-AUDIT] `fetch_headless_sync()` has no wall-clock limit on…
    [NEEDS-AUDIT] 6 TelVue pages still keyed to Pittsford village NY have…
    [JUST-DO-IT] YouTube video `ci9jnPULx5M` is pinned to Ste. Genevieve…
    [NEEDS-AUDIT] Real meetings found under the wrong government, never…
    [NEEDS-AUDIT] Check whether BoxCast re-signed Livermore Falls ME's…
    [NEEDS-AUDIT] Wheatfield town, IN's Town Board videos are linked from…
    [NEEDS-AUDIT] Two manual_override town pages resolve, via a fresh…
    [HUMAN] Should an unverified per-video pin still beat the registry on…
    [NEEDS-AUDIT] Three governments' `jurisdiction_coverage.csv` rows…
    [NEEDS-AUDIT] `[EASY]` SLC, LIMS and PrimeGov fail the whole resolve…
    [NEEDS-AUDIT] `[EASY]` yt-dlp's "This live event has ended." message…
    [NEEDS-AUDIT] Two tests failed only in full local runs on Ryan's Mac,…
    [NEEDS-AUDIT] A bare unqualified name that exists in BOTH the
    [NEEDS-AUDIT] eScribe archives one meeting once per `Agenda=` value…
    [HUMAN] Re-run the wrong-content screen after the wrong-page sheet is…
    [NEEDS-AUDIT] `scripts/score_gov_registry.py` can't see `match`-
    [NEEDS-AUDIT] Two known duplicate-page pairs for one meeting (Yamhill…
    [IMPROVEMENT-ROUND] `[BIG]` Zoom cloud recordings…
    [NEEDS-AUDIT] Topic chips are ranked by corpus hits, not real search
  Pages filed under a wrong government by a since-removed pin can't be…
  `backfill_gov_id.py --apply` writes hub redirects to a file the live…
  WO-171 LocalView channel pins: at least two named a neighbouring…
  WO-34's roll-up calibration gap: a second, smaller defect shape sits…
  `transcribe_backlog_locally.py`'s asyncio/subprocess context hangs…
  Adapter, tenant & jurisdiction-extraction odds and ends `[LATER]`
  `[JUST-DO-IT]` Anchorage and Santa Cruz OnBase/Hyland pages resolve…
  Jurisdiction extraction & backfill  (6)
    `[HUMAN]` Page 8878 (Town of Franklin, MA's Community Preservation…
    `[JUST-DO-IT]` `[EASY]` Census LSAD "corporation" is not stripped:…
    `[NEEDS-AUDIT]` `uatccta.primegov.com` is the first real…
    `[NEEDS-AUDIT]` A Swagit video opened through another government's
    `[NEEDS-AUDIT]` `[EASY]` Lloydminster, AB/SK: the hub is on neither…
    `[NEEDS-AUDIT]` A same-state place/county name collision falls…
  Adapter & platform gaps  (14)
    [NEEDS-AUDIT] A TikiLive title can still be a file name.
    [EASY] `jurisdiction_coverage.csv`'s…
    [JUST-DO-IT] `[EASY]` The shared meeting-title filter still passes…
    [NEEDS-AUDIT] `ec1c24.com` is an unrecognized video-index wrapper…
    [NEEDS-AUDIT] A same-named Granicus tenant is a real video source for…
    [NEEDS-AUDIT] SuiteOne: a bare tenant management root…
    [JUST-DO-IT] City-YouTube-channel fallback: listings only reach ~400…
    [NEEDS-AUDIT] Pages with no jurisdiction ship an Event JSON-LD with…
    [NEEDS-AUDIT] Palm Beach County FL's SharePoint page now escalates…
    [NEEDS-AUDIT] `[WAIT]` open.media broke on 2026-09-26 (empty…
    [NEEDS-AUDIT] TelVue's `resolve()` can return a perpetual…
    [NEEDS-AUDIT] `civicclerk.py`'s `resolve()` can return a Zoom join…
    [NEEDS-AUDIT] A real tier 1/3 "video found" verdict off…
    [NEEDS-AUDIT] A pasted custom (non-vendor) hub page with many…
  Very long Cablecast meetings whose audio is split into many files…
  State legislatures: residual per-chamber gaps after the WO-1012 push…
  97 of the 257 Diligent Community "no video" tenants link their own…
  Two Cablecast tenants list a real meeting with no video file:…
  13 Cablecast tenants with no Archive page show no meetings on the…
  [JUST-DO-IT] `[EXAMPLE]` Winona County, MN's own homepage links an…
  Five platform URL-shape findings from rtr-upcoming, not yet verified…
  Mad River Valley TV's three playlist pins still sit outside its…
  Three Archive pages store a source address ending in a backslash, so…
  `repair_wrong_pages.py --apply` refuses on the Archive's own shell…
  16 pins in `tenant_overrides.csv` name a minted id with no registry…
  Two TelVue pages for separate Vail-area bodies would be re-keyed to…

Reliability, ops & cost  (6)
  `[BIG]` Make BACKLOG.md a generated doc: one file per entry
  `[WAIT]` Run the local Whisper recovery on the ~159 Granicus/Swagit…  (1)
    [NEEDS-AUDIT] `rtr-deeplink-archive`'s "HTTP health check failed"…
  Media-source reliability  (1)
    `[NEEDS-AUDIT]` The 120s ffmpeg timeout is a flat value that doesn't…
  Transcription queue & workers  (1)
    [LATER] `list_transcription_backlog_candidates()` still does a real…
  Search Console, structured data & SEO plumbing  (1)
    [NEEDS-AUDIT] Search Console "Missing field" flags (Videos…
  `/coverage` as a QA surface

Trust, safety & data quality  (12)
  Shade the stretches of a Whisper transcript where Whisper itself was…
  Known wrong names in Whisper transcripts are not fixed yet…
  Pinned hosts: machine-made pins with no Archive pages yet are…
  2 already-pinned YouTube channels still disagree with the Archive's…
  27 real Quebec municipalities are marked `reject_reason=off-mission`,…
  `jurisdiction_coverage.csv` rows whose recorded website belongs to…
  8 rows carrying `prior_reject_reason=already-covered` checked live,…
  A bare YouTube channel-listing scan measurably ingests non-meeting…
  Meeting body is blank on ~90% of archived pages `[NEEDS-AUDIT]`…
  `[HUMAN]` `[BIG]` Nothing verifies a submitted URL is a genuine…
  `[NEEDS-AUDIT]` One row in `jurisdiction_coverage.csv` has…
  `[NEEDS-AUDIT]` `rtr-business/research/jurisdiction_coverage.csv` has…

Roadmap & strategy `[IMPROVEMENT-ROUND]`  (20)
  Adapters drop signals that show a person captioned the meeting (found…
  `[IMPROVEMENT-ROUND]` Pierce County TV: per-government YouTube leads…
  `[IMPROVEMENT-ROUND]` Vendor slug guess ladder for governments whose…
  `[IMPROVEMENT-ROUND]` `[BIG]` Agenda text as a first-class,…
  Product direction & open strategic questions  (1)
    `[IMPROVEMENT-ROUND]` `[BIG]` Open submissions to the Full Context…
  `[IMPROVEMENT-ROUND]` `[BIG]` Accounts + token billing, phases 2-6 —…
  Growth, audience & discoverability  (5)
    `[IMPROVEMENT-ROUND]` Governments with no domain on record: find the…
    `[IMPROVEMENT-ROUND]` `[BIG]` Recurring crawler: pull each covered…
    [IMPROVEMENT-ROUND] Batch lookup — accept multiple meeting URLs at
    [IMPROVEMENT-ROUND] A generated, branded share card would beat a raw
    `[IMPROVEMENT-ROUND]` Auto-post each newly published Full Context…
  Search & metadata quality  (1)
    `[IMPROVEMENT-ROUND]` Full Context entries drop `line`/`version` from…
  Transcription quality & cost  (3)
    [IMPROVEMENT-ROUND] `[BIG]` Split speakers by voice (diarization) in…
    [IMPROVEMENT-ROUND] Hallucinated-transcript detection doesn't catch
    [IMPROVEMENT-ROUND] Per-meeting `initial_prompt` seeded with real
  Email, ops tooling & internal reporting  (2)
    [IMPROVEMENT-ROUND] Point the ops email defaults at…
    [IMPROVEMENT-ROUND] Add two missing metrics to the daily worker…
  YouTube channels the access ladder found for 5,000+ governments are…
  37 of the 212 dead government addresses over 5,000 people were not…
  Tier 1.5: show a transcript that has no timestamps…

Dormant — needs a real example first `[LATER]`  (24)
  Granicus `TranscriptViewer.php` as a transcript fallback: wait for a…
  `hub_slug_aliases.csv` can only redirect an old slug to ONE new home,…
  PrimeGov has a real, structured `committeeId` field — but no…
  101 West Virginia towns still have a placeholder (`local.wv.gov`) or…
  [HUMAN] Farmington city, MO: Ryan saw 16 real agenda PDFs on…
  [NEEDS-AUDIT] A real platform adapter's OWN aiohttp session still…
  [NEEDS-AUDIT] The new body-name/government-TYPE filter (WO-1078)…
  [NEEDS-AUDIT] `pick.filter_candidates_to_government()`'s place-name…
  [NEEDS-AUDIT] `detect_platform()`/`parse_vimeo_video()` never…
  [NEEDS-AUDIT] Jefferson County WA's real CivicPlus video is one hop…
  [NEEDS-AUDIT] A real ProudCity or viebit tenant page named "watch…
  [NEEDS-AUDIT] A Google Drive FOLDER listing (as opposed to a single…
  [NEEDS-AUDIT] `[WAIT]` Palm Beach County, FL's real Granicus tenant…
  [NEEDS-AUDIT] South Bay, FL is the real example an earlier Dormant…
  [NEEDS-AUDIT] No adapter for a meeting recording pointing at a…
  [NEEDS-AUDIT] Garbled source transcripts still produce garbled…
  `[LATER]` ~25 smaller consolidated city-county governments still need…
  [NEEDS-AUDIT] Vimeo Whisper-fallback audio: unverified whether the…
  [JUST-DO-IT] City-YouTube-channel fallback: duplicate-posted meetings…
  [LATER] `[EXAMPLE]` Town Hall Streams: transcript endpoint…
  [LATER] `[EXAMPLE]` SuiteOne Media: dead CDX leads and unconfirmed…
  [NEEDS-AUDIT] `direct_file.py`'s Google Drive `&confirm=t` bypass…
  `[LATER]` `best_effort` is sticky — nothing at ingest distinguishes a…
  `[IMPROVEMENT-ROUND]` Social auto-posting only fires on page…

Parked deliberately — allowed back `[PARK]`  (3)
  Video-to-calendar join: match a government's video source to its own…
  SparQ Meetings adapter: agenda pages, six hosts and per-organization…
  `[LATER]` Mastodon auto-posting has made zero real posts
```

<!-- TOC-END -->

## Standing decisions — do NOT re-raise

Durable calls worth carrying into any session, not narrow one-offs.
**Single-incident decisions** — one adapter's domain override, one SEO
judgment call, one ops-tooling choice — **live in `BACKLOG_DONE.md`'s
Standing decisions archive** instead; check there before assuming
something hasn't been decided.

### The tier-3 queue is hand-approved meetings, not crawling: robots.txt does not apply to it `[STANDING]`

- **Issue**: on 2026-10-02 the queue-acceptance probe (`app/platforms/queue_probe.py`, PRs #1692/#1693) began always enforcing robots.txt. Google Drive lines were then logged `reject-dead: robots.txt disallows...` and dropped.
- **What this means**: Ryan, 2026-10-03: every line in `scripts/tier3_auto_transcription_queue.txt` is a specific meeting a person approved. That is not crawling, so robots.txt does not apply to the queue probe. The probe no longer reads it (WO-1176). Meeting Finder IS crawling and still honors it (`app/utils/robots_check.py`, hook in `meeting_finder/pacing.py`). Do not re-add the rule to the queue path.
- **History**: `BACKLOG_DONE.md` WO-1176 (same PR also lets a queue line carry title, date and meeting body, and stops the feed bouncing a shared-host line that has its own gov_id).

### English Whisper stays shown over a station's English captions; fix wrong names instead `[STANDING]`

- **Issue**: some pages hold two English versions: our Whisper transcript and the station's own captions. Whisper reads more cleanly. The captions are more word-for-word and sometimes get a name right that Whisper missed ("Groton Hill", not "Grotten Hill").
- **What this means**: Ryan, 2026-09-29: keep Whisper shown. Do not promote sourced English captions over it by default. Where a name is wrong, correct the word with `POST /internal/transcript-version/correct-text` (WO-1964; see "Trust, safety & data quality").
- **History**: `BACKLOG_DONE.md` WO-1160 (the 3 TelVue pages, caption versions 12320, 12322, 12326 left hidden).

### No Viebit meeting can get a real transcript today -- confirmed at both the probe level and the transcription level `[STANDING]`

- **Issue**: `app/platforms/queue_probe.py`'s `_probe_viebit()` already
  documented (WO-306, 2026-09-12) that Viebit's raw video file
  (`master.m3u8`) refuses the request (HTTP 403) even with the right
  Referer/Origin/browser-like headers -- so the step that decides
  whether to *queue* a Viebit meeting never actually fetches the real
  video; it accepts on a different, weaker signal instead. Confirmed
  live 2026-09-15, running a real end-to-end transcription attempt
  against 4 independent real Viebit meetings: the exact same 403 also
  blocks the *transcription* step itself. `transcribe_backlog_locally.
  py --url` against a real Viebit meeting skips in about 6 seconds with
  "ffprobe couldn't read the media" -- not a dead video, a CDN gate
  only a real browser gets through.
- **Impact**: every Viebit meeting ever queued -- past or future --
  will sit forever as a video-only page with no transcript. This
  includes 16 meetings in the 2026-09-15 breadth-355 local Whisper
  batch; they'll add a real page (a real improvement on their own,
  since the government previously had no page at all), but none of
  them will get a transcript from this attempt or any future retry,
  by either the local script or the cloud worker (both share the same
  `app/platforms/media_probe.py` extraction code).
- **What this means**: nothing to build here without a much bigger
  piece of work (real browser automation specifically for Viebit,
  since a plain HTTP client can never satisfy whatever gate their CDN
  checks). Not worth doing for one small platform today. Revisit only
  if Viebit meetings become a large enough share of remaining coverage
  gaps to justify it, or if a real sample is ever found where the gate
  doesn't apply.
- **History**: `CLAUDE.md`'s ffmpeg-trust-store gotcha (2026-09-15, the
  same investigation that confirmed this); `app/platforms/queue_probe.
  py`'s own WO-306 comment (the original, narrower probe-level finding).

### Cablecast, Granicus, eScribe, and Swagit have no real `meeting_body` field to extract -- checked, not assumed `[STANDING]`

- **Issue**: WO-904/905/906 (`BACKLOG_DONE.md`) extracted a real,
  structured `meeting_body` for CivicClerk/CivicPlus/Legistar after
  confirming each platform's own API/HTML genuinely carries a
  committee/body name distinct from the meeting title. The same check
  against Cablecast, Granicus, eScribe, and Swagit -- the platform this
  repo's own biggest tenant pool (Granicus, ~240 real tenants) runs on
  -- found nothing real to extract.
- **Impact**: none of these four will ever get a non-title
  `meeting_body` without a materially different data source than what
  each adapter already fetches -- most of the corpus by tenant count
  stays at today's ~10% `meeting_body` coverage regardless of any
  further per-adapter work here.
- **What this means**: do not "fix" `meeting_body` on any of these
  four from a title guess -- that's exactly the thing this repo's own
  convention (never guess a body from a title) exists to prevent.
  Cablecast: the only category field in any real captured response
  (`PublicSite`, Remix `__remixContext`) is a bare integer id with no
  name anywhere in the payload -- a name lookup would need a second,
  never-yet-captured `/categories/{id}` call. Granicus: the RSS
  `<channel><title>` some tenants expose is a real, structured field
  (already used, `channel_body` in `granicus.py`), but it names the
  *channel*, not the meeting's committee (real fixtures: Tulsa's is
  "TGOV - Tulsa Government Access Television", Prince William County's
  is "Streaming Media Archive2") -- and it requires `view_id` in the
  URL, so a bare `/player/clip/NNNN` link gets nothing regardless.
  eScribe: the calendar JSON's `MeetingType` field is real and
  independent of `MeetingName`, but in every real captured row (Peel
  Region, Hazelton) its value is byte-identical to `MeetingName` --
  no actual signal -- and it's only on the listing endpoint, which the
  resolve path never calls. Swagit: checked live 2026-09-20 against
  three real, currently-archived pages (Dublin CA, Yountville CA, San
  Antonio TX) -- the only category-shaped labels anywhere on the page
  ("COMMITTEES"/"CATEGORY"/"DEPARTMENT"/"BOARD" aria-labels) are chapter
  markers for skipping within *that one video's own agenda*, the same
  role `agenda_items` already fills, not a meeting-level committee
  field. The `<title>` itself is the same blended shape as every other
  write-off here -- Dublin's cleanly reads "Jan 13, 2026 City Council -
  Dublin, CA" but Yountville's and San Antonio's run the body and
  meeting type together with no separator ("Town Council Regular
  Meeting", "City Council Zoning and Land Use Session") -- so it can't
  be split reliably across tenants either.
- **History**: `BACKLOG_DONE.md`'s WO-904/905/906 entry has the full
  per-platform evidence (real field names, real captured values) this
  finding is based on. Swagit's own check (2026-09-20, live against
  Dublin CA `dublinca.new.swagit.com/videos/372020`, Yountville CA
  `yountvilleca.new.swagit.com/videos/394093`, San Antonio TX
  `sanantoniotx.new.swagit.com/videos/395469` -- all three sourced from
  the real Archive's already-ingested pages) isn't its own
  `BACKLOG_DONE.md` entry, just this one.

### Guessing a bare tenant name for a small government is unsafe unless it beats an existing-pin check and an own-state match — 8 of the first 14 "confirmed" WO-168 tenants were a different, larger, same-named government `[STANDING]`

- **Issue**: WO-168 (2026-09-10, `BACKLOG_DONE.md`) guessed platform
  tenant hosts (`{slug}.granicus.com`, `{slug}.legistar.com`, ...) by
  bare government name for 321 governments whose website is gated. Hand-
  verifying every "confirmed" tenant — not just the pilot's 30, the full
  run too — found the dominant failure mode: a small, obscure
  government's bare name collides with a much larger, more famous
  government of the exact same name, and the big government is who
  actually holds the obvious subdomain. Confirmed wrong, one at a time,
  by reading the real page: San Juan city TX → San Juan Unified School
  District, Sacramento County CA; Salem city IL → Salem, OREGON (state
  capital); Fremont city OH → Fremont, CALIFORNIA; Lake County MI → Lake
  County, CALIFORNIA; Wilmington town MA → Wilmington, NORTH CAROLINA;
  Fulton County KY → Fulton County, GEORGIA (Atlanta); Clark County KS →
  Clark County, NEVADA (Las Vegas); York County SC → York County,
  VIRGINIA ("Board of Supervisors" is Virginia's term; SC counties use
  "County Council"). Two more (Woodstock town CT → Woodstock, ONTARIO;
  Lakewood city CO → Lakewood Township, NEW JERSEY) were a related but
  distinct gap: the identity checks never ran at all, because they only
  fire on a candidate that resolves with real content, and a real
  meeting with no *embeddable* video (legitimate, common) never does.
- **What this means for any future sweep that guesses a tenant host
  rather than reading it off a real page**: a bare name-token match on a
  raw page proves nothing — the identically-named larger government's
  real content of course also contains its own name (Clark County, NV's
  zoning notices say "Clark County" throughout; that is not evidence for
  Clark County, KS). Two checks made this method safe enough to ship at
  all, and both belong in any future sweep of this shape:
  1. **Check `tenant_overrides.csv` for the guessed host FIRST, before
     any network call.** If a real pin already exists for that exact
     host naming a *different* government, stop — someone already
     identified this tenant, and it isn't the one being guessed for.
     This is free (no network) and was the single highest-value check
     found (`existing_pin_conflict()`,
     `scripts/wo168_gated_tenant_guess.py`).
  2. **A raw-page identity match requires the row's own state
     (abbreviation or full name) to also appear in the text, not just
     the row's own name.** A name match with no state confirmation is
     inconclusive, not confirmed (`raw_candidate_identity_check()`,
     same file). Apply this to EVERY path that can result in an ingest
     or a queue/pin, including tier-1/2 — WO-168's own York County VA
     mistake happened twice specifically because the first fix only
     covered tier-3, and a short real transcript (4 segments) never
     mentioned either state by name.
  3. A full-transcript scan for state-name conflicts (not a short
     sample) is worth doing too, but is not sufficient on its own — the
     disambiguating word can land anywhere across an hour, or never
     appear at all in a short/thin transcript. Treat a thin transcript
     as weaker evidence, not a clean pass.
- **Net result once fixed**: WO-168's real, hand-verified yield was 2 of
  321 governments (0.6%), not the 14 of 321 (4.4%) it looked like before
  verification. That is the honest number for this method against a
  cohort of small/obscure governments; don't expect a materially
  different rate without a stronger signal than bare-name guessing.
- **History**: `BACKLOG_DONE.md`'s WO-168 entry, 2026-09-10.

### Bulk sweeps ingest only meetings that have video — agenda-only meetings are not ingested (Ryan's rule, 2026-09-09) `[STANDING]`

- **Issue:** Ryan's rule, 2026-09-09, for every enumeration/ingest sweep:
  only meetings WITH video become Archive pages. Audio-only recordings
  count as video here (Ryan, 2026-09-22 and 2026-09-30). Tier 1/2 (captions
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

### Do NOT backfill partial transcripts onto historically-failed jobs `[STANDING]`

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

### The Archive files a page under whatever `gov_id` a sweep sends: do not add a blocking Archive check (409) on a state mismatch

Decided by Ryan 2026-09-21, taking WO-932's recommendation. The count, on
the local export of 2026-09-21: a blocking check would refuse 12 of 10,280
pages. Ten are correct pages with a wrongly guessed state, one is a real
error (page 9073) and one is unclear (page 7885), so it would refuse more
right pages than wrong ones. The check that shipped is WO-134's
jurisdiction hook, on by default (WO-932, `scripts/identity_gate.py`).
`/internal/ingest` still treats a caller's `gov_id` as a pin and only
checks that it exists. If a signal is wanted later, log a flag first, and
re-run `scripts/wo932_state_check_dry_run.py` on a fresh inventory before
building anything that refuses. Several sweeps force `result.jurisdiction =
unit_name` and rely on the ladder being skipped. A same-state mismatch (a
town filed under its county's site) is not caught either way; that gap is
tracked under the registry-domain entries. History: `BACKLOG_DONE.md`
WO-932 and WO-913.

### A single job still makes N consecutive pulls to the same host — WO-40 tested and falsified the round-robin fix `[STANDING]`

- **Issue**: `claim_next_chunk()` claims a whole *job* and the worker
  holds it through every chunk, so a 21-chunk meeting is still 21
  consecutive pulls from one host inside a single job — queue-level
  reordering can't reach inside a job.
- **What this means**: leave within-job pull ordering alone. WO-40
  (2026-08-21) tested "workers hammer one host across consecutive jobs,
  so round-robin the queue by host" against all 514 production jobs and
  falsified it: `same_host_different_job` failure pairs within 10
  minutes were **0**, and chunk 0 is 3-4x more failure-prone per attempt
  than any later chunk — the opposite of what an accumulating rate limit
  would predict. Both real mechanisms WO-40 found (cold-storage
  rehydration, where chunk 0 warms the asset for chunks 1..N; and a
  persistently-slow source, which doesn't care about pacing) argue
  against spreading pulls.
- **Re-derived, not re-raised (WO-936, 2026-09-21)**: this entry sat
  under `[NEEDS-AUDIT]` in Open bugs with its own "Next action: none
  planned" already written — moved here rather than left to be
  rediscovered as an open bug again. Worth another pass with fresh data
  if job volume grows a lot, but not a currently-open question.
- **History**: `BACKLOG_DONE.md` (WO-40, 2026-08-21) — full numbers and
  the `GET /internal/transcription-failure-analysis` endpoint.

### [NEEDS-AUDIT] Phase 2d's signal-based recovery (WO-110, `scripts/score_gov_signals.py`) needs a human review step before any apply mode is built, not just a straight "recovered → write it" pipeline — confirmed by two real wrong-level matches in its own first report

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

### Don't proxy Granicus/CivicClerk video bytes to clear Search Console's "video isn't on a watch page"

- **Issue**: Granicus's CDN returns 403 to Googlebot, and CivicClerk's Azure host (`cpmedia.azureedge.net`) serves `Content-Disposition: attachment`. Together they explain about 65% of GSC's failing watch-page rows (Granicus 51.6%, CivicClerk 13.4%, 2026-08 export) and the Granicus "invalid item" rich-result flags.
- **Impact**: our templates already render correct video markup, so there is no in-app bug.
- **Next action**: none. The only lever is proxying video bytes through our own domain.
- **Constraint**: don't proxy without a real bandwidth cost check (see `BACKLOG_DONE.md`'s `ARCHIVE_BASE_URL` double-proxy entry).
- **History**: `BACKLOG_DONE.md` `[Investigated 2026-08-30]` GSC entry.

### [LATER] Tighten the two transcription workers to their real import surface

`worker/main.py` actually imports would cut their build count further.
**Deliberately declined 2026-08-22**: it makes a build trigger depend
on an import graph, so the first new `from app.… import …` added
without a matching `render.yaml` edit leaves a worker silently running
stale code. Only worth doing alongside a CI guard that keeps the two in
sync. History: `BACKLOG_DONE.md` `[Done 2026-08-22]`.

### [LATER] Second transcription worker's auto-generation TOCTOU race — avoided by construction at N=2, not fixed at the DB layer

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

### `[LATER]` If a Content-Security-Policy is ever added, it must allow the three Full Context embed origins

- **Issue**: neither the resolver nor the Archive sets a
  Content-Security-Policy header today, so this isn't live-blocking
  anything — but WO-943's Full Context feed (2026-09-21) added
  click-to-load embeds from `www.youtube-nocookie.com`,
  `www.instagram.com`, and `www.tiktok.com` (see README's "Full Context
  feed" section). A CSP written without checking current features first
  would silently break those three embeds.
- **Impact**: none today. Would break every Instagram/TikTok/YouTube Full
  Context embed the moment a CSP shipped without these three origins
  allowed — both the ones a reader clicks "Show the post here" to load,
  and (WO-945, 2026-09-21) the first few embeds on page 1 that now load
  on their own; see README's "Full Context feed" section.
- **Next action**: none now — re-read this entry (and grep the codebase
  for every third-party origin actually loaded, not just these three)
  before adding a CSP.
- **History**: `BACKLOG_DONE.md`'s WO-943 and WO-945 entries.

- **Ryan, 2026-10-16**: keep `/j/victoria` pointing at Victoria, BC. (Was the entry "[HUMAN] The bare `/j/victoria` slug may be pinned to the wrong destination — the one real"; see `BACKLOG_DONE.md`.)
- **Ryan, 2026-10-16**: no age cutoff. Queue a real meeting of the right body at any age. (Was the entry "How stale is too stale for a tier-3 queue candidate? `[HUMAN]`"; see `BACKLOG_DONE.md`.)
- **Ryan, 2026-10-16**: no, do not queue CITISTAT broadcasts. (Was the entry "[HUMAN] Atlantic City NJ's CITISTAT broadcasts (22.5 and 30.9 min, probed clean) -- queue"; see `BACKLOG_DONE.md`.)
- **Ryan, 2026-10-16**: no do-not-ingest list for now. (Was the entry "Nothing records that a page was deliberately deleted, so a later sweep can put it straight"; see `BACKLOG_DONE.md`.)
- **Ryan, 2026-10-16**: do not auto-ingest every new meeting of the pinned tier-1 governments. It grows the Archive's depth too fast, and it shows observers which governments are well covered. rtr-discovery already covers most of the need. The hold, its trigger and its one exception are on the "Recurring crawler" entry.
- **Ryan, 2026-10-16**: no public read-only API until a data product sells. (Was the `CLAUDE_BACKLOG.md` idea "Read-only public API with API keys".)
- **Ryan, 2026-10-16**: no ChampDS streaming proxy. It would send every viewer's video bytes through our server, the same cost reason as "Don't proxy Granicus/CivicClerk video bytes". The cheaper test of showing ChampDS's own player is on the ChampDS VOD2 entry.
- **Ryan, 2026-10-16**: keep re-keying old pages by hand (backfill_gov_id.py after each deploy) for now. (Was the entry "[NEEDS-AUDIT] A `tenant_overrides.csv` pin only affects future resolutions — nothing retro"; see `BACKLOG_DONE.md`.)

## Ship next — root cause known, fix settled `[JUST-DO-IT]`

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

### iQM2's meeting body is only on the calendar listing page; fetch it there `[JUST-DO-IT]`
- **Update 2026-10-16**: Partly fixed in the backlog round-2 PR (`d0173e72`): Calendar fetch built and tested on fixtures; live check on Atlanta GA and Santa Clara County CA still needed.

- **Issue**: `iqm2.py` reads only the meeting detail page, whose title runs body and meeting type together. The calendar (`Citizens/calendar.aspx?View=List&From={date}&To={date}`) answers a plain GET, and each `MeetingRow`'s `RowDetails` splits cleanly on `" - "` into body and type (checked live 2026-09-20 on Atlanta GA and Santa Clara County CA).
- **Impact**: iQM2 pages have no `meeting_body`.
- **Next action**: after the detail fetch, GET the calendar for that one day, find the row whose `Detail_Meeting.aspx?ID=` matches, and take the text before `" - "`. Live-check on Atlanta and Santa Clara, then add a fixture test.
- **Constraint**: match the row by meeting id, never by position.
- **History**: `BACKLOG_DONE.md` WO-904/905/906.

### Granicus: discover a tenant's `view_id` so a bare tenant hub lists its video meetings `[IMPROVEMENT-ROUND]`

- **Issue**: a bare Granicus host like `cityoftacoma.granicus.com` does not say which `view_id` lists its videos. Meeting Finder's live probe (`_granicus_discover_view_id()`) tries only ids 1-6. WO-1965 added the stored map `app/utils/jurisdiction_data/granicus_views.csv`, read first by that probe and by `granicus.py`'s `resolve()` for a pasted bare host, and the script that fills it. The map holds only 4 seed rows (feeds saved as test fixtures).
- **Impact**: about 240 Granicus tenants, the largest pool. Until the map is filled, a bare hub, pasted in or swept, still finds no meeting unless its feed is at ids 1-6.
- **Next action**: **Claimed 2026-10-16** (office Mac, WO-1965 / PR #2083): the probe runs from the office Mac after the deploy. Run `scripts/probe_granicus_view_ids.py` from the Mac (the cloud gets a 403 from granicus.com): first a dry run on the 274 no-feed hosts from the 2026-10-07 check, then again with `--write`, and commit the new rows.
- **Constraint**: ids 1-6 are not enough (11 of 25 feeds only at 44-50; Alexandria at 29 and 57), so the script probes 1-60. `ViewPublisher.php` without a view_id is gated on purpose. A row proves the host serves the feed, not who owns the host: confirm an owner by hand before pinning or subscribing.
- **History**: WO-1965 (stored map, loader, probe script); `meeting_finder/listing.py` WO-1030 comment; `~/Documents/rtr-findmeeting/data/granicus_norss_rss_check_2026-10-07/`; findmeeting PR 73.

## Needs a human — dashboard, prod, or product call `[HUMAN]`

Nothing here is blocked on engineering. Most are one dashboard login or
one deliberate production action away from closing. Grouped by what kind
of human step they need.

- **[HUMAN] Archive page 12994 carries a job label as its source address; repair it and find who wrote the label into queue column 2 (2026-10-14).**
  - **Issue**: 24 tier-3 queue lines carry the text `meeting_finder_group4` in column 2 (source page), not a web address. The local Whisper run sent that as the page's source, so the first such ingest (Cambridge Central School District NY, 2026-10-11 11:05) created page 12994 with source `meeting_finder_group4`, and 9 later pushes for other governments matched it and were refused with 409 (`gov_id mismatch`). WO-1963 makes `parse_queue_entry()` treat a non-URL column 2 as blank, which stops it for every reader of the queue.
  - **Impact**: page 12994 shows the Cambridge transcript but its source address is wrong. 9 finished transcripts are saved as backups under `local_transcription_backups/` (batches 30b, 30c) and need a re-push once WO-1963 is on the Mac that runs them.
  - **Next action**: an admin sets page 12994's source address to its Drive link `https://drive.google.com/file/d/1Z2ir3mX1Fjhz3XlYpc-yLSXbD0dBdloI/view?usp=sharing`; Find Meeting finds which group4 job wrote the label and stops it; then re-push the 9 backups.
  - **Constraint**: do not overwrite page 12994 from any queue line. Not verified: whether the drip `direct` lane or the cloud feed ever created another page this way (the 2026-10-14 inventory shows one page with a non-URL source).

- **[HUMAN] Two Granicus lead-sheet feeds need Ryan's call: Gretna LA's "New View", and Scranton's two authority views filed under the city (2026-10-16).**
  - **Issue**: (1) Gretna's only feed, `gretnala.granicus.com` view 1, is titled "Gretna, LA: New View". findmeeting's internal/test title rule holds it back, but the page lists real "Mayor and City Council" meetings (owner checked by hand 2026-10-16, now pinned to `us:place:2231915`). (2) `scrantonpa.granicus.com` views 10 ("Scranton Housing Authority") and 14 ("Scranton Redevelopment Authority") were subscribed on 2026-10-07 under the City of Scranton (`us:place:4269000`), but each is a separate public body.
  - **Impact**: (1) Gretna's council meetings are not read. (2) Pages from those two views would be filed under the city.
  - **Next action**: (1) Ryan decides whether to subscribe Gretna view 1 by hand despite its title. (2) Ryan decides whether to remove the two Scranton authority views from `feed_subscriptions.csv` in rtr-findmeeting, or give each its own government and a `match` pin.
  - **Constraint**: never pin from the sheets' own match.
  - **History**: `BACKLOG_DONE.md`, "Granicus feeds from Ryan's two lead sheets: owners checked by hand".

- **[HUMAN] WO-1165: 15 CivicMedia page renames, one refresh and one title decision after the resolver and Archive deploy.**
  - **Issue**: WO-1165 (#1610) gives CivicMedia pages the government's own title, and the follow-up (#1611) added 15 `_SLUG_REDIRECTS` entries in `archive/main.py`. The renames themselves have not been run. Rosetown, East Baton Rouge and Fort Madison were already re-ingested; Chanute stays as it is.
  - **Impact**: 11 pages read wrong in their address (e.g. `/m/davie-fl`). Once a redirect is live, its old address 301s to a page that 404s until the rename runs.
  - **Next action**: (1) confirm both services are deployed with #1610/#1611; (2) run `POST /internal/admin/reslug-page` with `dry_run=false` for each of the 15 pages in #1611's order, checking each against its preview; (3) refresh Isanti County with `POST /api/refresh-archived-page`; (4) Ryan decides whether to re-ingest Graham County as "SWFRS Public Scoping Mtg Recording 05-13-23" and rename it.
  - **Constraint**: run each rename straight after the deploy. The preview does not check for a clash with another page's address (WO-942). Keep TikiLive requests few.
  - **History**: `BACKLOG_DONE.md` WO-1165.

- **[HUMAN] Promote the hidden transcript version on about 6 pages where it is clearly better (WO-928).**
  - **Issue**: on about 6 pages the shown transcript has a loop or unlinkable caption blocks while a hidden version is clean: 1018, 1022, 1225, 1353 (loops) and 1967, 1990 (huge all-caps caption blocks). Page 725 is low priority; 1658 stays as is.
  - **Impact**: readers see a worse transcript than the one already stored. Small: a random sample of 78 other multi-version pages found no more.
  - **Next action**: read `rtr-business/research/wo928_candidates.csv` (rows A and B, high confidence first), then promote each confirmed page with `POST /internal/transcript-version/promote`, one at a time, after reading it.
  - **Constraint**: never promote from counts alone, and check the version's language (a station feed can carry French or Spanish tracks; see page 7104). A later version can be a repair copy, so compare content, not `created_at`.
  - **History**: `BACKLOG_DONE.md` WO-928 (corrects WO-927).

- **[HUMAN] 19 Cablecast pages still show label-only or empty station captions after the 2026-10-03 repair.**
  - **Issue**: 25 label-only Cablecast pages were fixed (#1699, #1701, hand promotions). 14 pages now get no captions from the station at all (e.g. Hopkins School Board, Rutland, Holden). 5 stored no second version after a refresh, cause unknown (Redlands, Holden Board of Selectmen, Virginia Beach page 1604, Artesia, Edison Planning Board).
  - **Impact**: these 19 pages show speaker tags or nothing instead of a transcript.
  - **Next action**: send the real meetings among the 14 to audio transcription (skip concerts, commencements and sports). Refresh the 5 once more and read what the Archive stores.
  - **Constraint**: promote only an English version, after reading the text; `research/promote_hidden_versions.py` refuses a non-English one.
  - **History**: rtr-business `research/cablecast_*_2026-10-0*.csv`; #1699, #1701. Scanning other platforms is the separate "Near-empty station captions" entry.

- **[HUMAN] Run the re-transcription queue for the pre-voice-filter Whisper pool: pilot, review, promote, then the other 89 pages (WO-929, from WO-928; grown by WO-944).**
  - **Issue**: 94 pages show only older Whisper text (made before the voice filter, or a repair copy of it) with a real defect in the text: 58 with the silence signature ("Thank you." every 30 seconds), 35 with loops, 1 other. (82 found by WO-928; WO-944 added 12 on 2026-09-21: 11 from Ryan's full-Archive run of the same tool, plus page 724, found by the conductor.) None carries a warning marker, so the cloud worker never picks them up. Ryan decided (2026-09-21) to re-transcribe them on the local Whisper machine through their own queue, `scripts/retranscription_queue.txt` (5-page PILOT, 89-page MAIN, an empty DRIP-MAC-ONLY section; sidecar `scripts/retranscription_queue_meta.csv`; runbook `docs/RETRANSCRIPTION_QUEUE.md`). All 94 re-checked live on 2026-09-21: shown version unchanged, defect still present, video resolves.
  - **Impact**: 320.6 hours of meeting audio (pilot 9.1 h, main 311.5 h). The local machine's speed is not measured yet, so the run time is unknown; the runbook's step 1 measures it.
  - **Next action**: Ol McClaude runs the runbook's step 1 (timing dry run) and step 2 (pilot, no `--promote`); `scripts/retranscription_review.py --section PILOT` compares old and new text; Ryan or the conductor promotes the pages judged good with `POST /internal/transcript-version/promote`; then the main queue in batches, adding `--promote` only if Ryan says so. Record each decided page with a `# done,...` line in the sidecar. If the pilot's loop pages reproduce their loops, repair them with `scripts/repair_repetition_loops.py` instead of re-running the rest.
  - **Constraint**: nothing reads or advances this queue automatically (a test fails the build if it did); no automatic promotion; never resolve a YouTube page from any machine except the drip Mac (none of the 94 is YouTube-hosted). The 2026-08-22 standing decision against bulk re-transcription is respected: this is a bounded, evidence-backed set with a human review gate. Two stale slugs found while checking (page 775 `port-colborne-resolution-...` is really Brockton ON, page 893 `peterborough-attachments-...` is really Uxbridge ON) are left alone.
  - **History**: `BACKLOG_DONE.md` WO-929 and WO-928; `rtr-business/research/wo928_era_evidence.md`, `wo929_population_recheck.csv`.

- **[HUMAN] Other Cablecast pages with no `external_id` may be twins of a keyed page, as Leon Valley's was.**
  - **Issue**: page 1595 (a `?site=1` copy of Leon Valley show 185, no `external_id`) was a twin of page 3973 and no re-check could reach it; Ryan had it deleted on 2026-09-21 (WO-941 entry in `BACKLOG_DONE.md`). The same shape (a Cablecast page made from a `?site=1` or other query-string URL, so its `external_id` is NULL) may exist on other pages. Nobody has counted them.
  - **Impact**: unknown; each such twin shows a stale, unwarned transcript that no re-check can update.
  - **Next action**: list Cablecast pages with a NULL `external_id` from `/internal/export/pages` (read-only), group by normalised show URL, and report the pairs that share a show with a keyed page; delete or key each after a hand-check.
  - **Constraint**: deleting a page needs a `_SLUG_REDIRECTS` entry first; never bulk-delete.
  - **History**: `BACKLOG_DONE.md` WO-925 and WO-941.

### Pin audit follow-up (WO-1186): 16 re-keyed Archive pages still carry the old place in their web address `[HUMAN]`

- **Issue**: every store the 2026-10-06 pin audit named is now fixed (pins, Archive pages, 26 rtr-business research lines in commit 599789d6, 9 rtr-discovery ledger fixes on 2026-10-07). What is left: 16 re-keyed pages keep their old addresses, for example `/m/sunnyside-nl-2026-09-09-...` for a Sunnyside WA meeting.
- **Impact**: the address names the wrong state or province, which looks wrong to a reader and to search engines.
- **Next action**: Ryan runs the reslug dry run on the Archive shell (`POST /internal/admin/reslug-page`, script in this entry's PR thread); its previews become `_SLUG_REDIRECTS` entries in `archive/main.py`; deploy; then the same script with `--apply` straight after.
- **Constraint**: rtr-discovery reads pins from the shared `~/Documents/rtr-deeplink` checkout, 166 commits behind main on 2026-10-07. A `resolve` or `backfill_gov_ids` run there would put back the old ids on the ledger's fixed tenant rows. Set `RTR_DEEPLINK_PATH` to an up-to-date worktree before either.
- **History**: `BACKLOG_DONE.md` WO-1185 (the audit) and WO-1186 (the fixes).

### Existing Invintus pages need one re-resolve after WO-1065 deploys, to find captions carried in the video `[HUMAN]` `[WAIT]`

- **Issue**: WO-1065 makes the Invintus resolver spot captions carried inside the video, and the worker extract them. Pages ingested before that deploy still say "No captions found" and don't carry the note the worker looks for.
- **Impact**: any archived Invintus page with no transcript and captions in its video (5 of 11 sampled meetings on 2026-09-25) waits in the ordinary oldest-first queue for a Whisper run instead of getting its own captions. Not yet counted.
- **Next action**: after the resolver, Archive and both workers are deployed, count archived `platform='invintus'` pages with no good transcript, then re-resolve and re-ingest them one at a time (each probe reads about 1 MB). The workers take it from there. The same deploy carries the two new Invintus government ids from PR #2080 (Southwest Washington Regional Transportation Council, Tacoma-Pierce County Health Department). They are on `main` but not live. Their existing pages stay blank until `backfill_gov_id.py` runs after the deploy.
- **Constraint**: Render shell only, never a laptop against production. One request at a time per host; stop on 403 or 429.
- **History**: `BACKLOG_DONE.md` WO-1065.

### After WO-1056 and WO-1057 deploy, re-resolve archived pages so shared-host pages get their government `[HUMAN]`

- **Issue**: WO-1056 fixed pin matching (CMNtv playlist pins now beat the station pin; DestinyHosted `id=N` pins reach `/{N}/agenda/...` pages). WO-1057 removed three pins (Yarmouth MA, and the RVTV and CMNtv whole-station pins) and lets a one-government tenant on a shared host keep its adapter's name. Archived pages keep the `gov_id` they got at ingest.
- **Impact**: resolved over the 6,410-page 2026-09-09 archive export, WO-1057 moves 8 pages: 2 from unknown to the right government (University Place WA, Leon County FL), 6 from the shared-host unknown bucket to "unresolved", and 0 to a different government. The one Fond du Lac WI page (`/fonddulacwi/event/77`) is a County Board of Supervisors meeting that the name ladder read as Fond du Lac city; `fonddulacwi` is now in `MULTI_GOVERNMENT_TENANTS`, so it stays unknown (see "ChampDS customers that carry a second government" below). RVTV and CMNtv pages filed under Ashland or Berkley's schools by the removed pins become unknown unless a narrower pin matches.
- **Next action**: after the deploy, run `python scripts/backfill_gov_id.py` from the Archive service's Render shell. It's a dry run by default; review the rows it reports, then rerun with `--apply`.
- **Constraint**: Render shell only, never a laptop against production (the script's own docstring).
- **History**: `BACKLOG_DONE.md` WO-1056 and WO-1057.

### Finish the WO-310 fixes: 2 identity joins, 1 blank gov_id and 42 research rows wrongly marked transcribed `[HUMAN]`
- **Issue**: WO-310 hand-checked 51 `jurisdiction_coverage.csv` rows marked `transcribed=true` with no Archive page. Hamilton Township NJ (page 7302) is now pinned. Still open: Lexington-Fayette KY (pages 338, 5789 to `us:place:2146027`, no pin yet), North Bay ON (pages 1036, 1805; check the `pub-northbay.escribemeetings.com` form is covered by the existing `northbay.escribemeetings.com` pin), Waukesha WI's blank `gov_id` (`us:place:5584250`), and 42 rows with no live page that should have `transcribed` blanked.
- **Impact**: real coverage that readers cannot find under the right government, and 42 rows that overstate coverage.
- **Next action**: follow `rtr-business/research/wo310_51_rows_plan.csv` row by row: add the Lexington pin and re-key its pages, confirm North Bay, fill Waukesha, blank the 42.
- **Constraint**: use the plan file's per-row verdicts; never bulk-blank or bulk-re-key.
- **History**: `BACKLOG_DONE.md` WO-301, WO-310.

### Production actions only Ryan should take

- **[HUMAN] ~1,676 archived YouTube video ids have no channel on record anywhere in the repo -- needs a real lookup from the YouTube-drip Mac, not this one.**
  - **Update 2026-10-16**: the `backfill_video_channel.py` dry run on the Archive shell found 266 YouTube pages whose video id is in no channel map (and 1 with no readable id). That is the real size of this gap now.
  - **Issue**: WO-246 (2026-09-11) found no per-video channel record (in `reports/pin_worklist_youtube.csv`, `reports/shared_host_lookups.csv`, or `tenant_overrides.csv`'s pin evidence) for 1,676 of the 3,562 distinct archived YouTube video ids. `scripts/backfill_archived_pages.py --platform youtube` fills these in via a real yt-dlp re-resolve, but that calls YouTube, and this Mac's office connection has no YouTube budget of its own -- the drip Mac (Ol McClaude's) owns it (see MEMORY.md's "YouTube drip ownership" note).
  - **Impact**: these pages' `channel=` pins (existing or future) stay unreachable until someone runs a real lookup from a machine with YouTube budget.
  - **Next action**: run `scripts/backfill_video_channel.py --apply` first (the entry above), then from the YouTube-drip Mac, with the drip's own lanes stopped or dropped to `--lanes captions,feed` (shared YouTube budget): first a small `--dry-run`, then the real run -- `python scripts/backfill_archived_pages.py --platform youtube --missing-channel-only --dry-run --limit 20`, then `python scripts/backfill_archived_pages.py --platform youtube --missing-channel-only --delay 3`. WO-295 (2026-09-12) added `--missing-channel-only`, so this now restricts to pages whose `video_channel` is still NULL/blank instead of re-touching all ~3,464 archived YouTube pages -- see `docs/YOUTUBE_DRIP_RUNBOOK.md`'s "Backfill sweeps" section for the full command and the accommodation with the drip's lanes.
  - **Constraint**: run it on the drip Mac, one drip per office connection -- don't run it here or from any other machine sharing this office's connection.
  - **History**: `BACKLOG_DONE.md`, WO-246, 2026-09-11; WO-295, 2026-09-12.

- **[HUMAN] Apply the reviewed wrong-page sheet, `reports/wrong_page_worklist.csv` (82 rows): deploy, then run the tool on the Archive's Render shell.**
  - **Update 2026-10-16**: ran on the Archive shell: 51 rows already done, 25 re-keyed, page 3385 already on a better id (Shawsheen Valley Technical School District). Left: the 6906 Sebring and 7086 Malibu deletes need a fresh check (the 2026-09-21 one is past the 14-day limit), and page 2504, whose row now expects `(none)`.
  - **Issue**: WO-934 built `scripts/repair_wrong_pages.py` and the sheet. Ryan decided the first 48 rows on 2026-09-21; #1568 added 32 reviewed rows on 2026-09-28. Approved deletes: 6114, 6101, 6830, plus Sebring 6906 and Malibu 7086, whose replacement videos were ingested on 2026-09-21 (#1370).
  - **Impact**: dozens of live pages show the wrong government (or none), and 5 show a video that is not a meeting or does not play.
  - **Next action**: on the Archive's Render shell, after a deploy that includes the minted governments: `python scripts/repair_wrong_pages.py check reports/wrong_page_worklist.csv`; `... run ...` (dry run, read it); `... run ... --apply --batch-size 5` until nothing is left; then `... --apply --allow-deletes --only-ids 6114,6101,6830,6906,7086`, dry run first. Page 2504 (Minnesota PUC): re-push with `scripts/repoint_page.py` on the resolver's shell. Then re-run `scripts/wrong_page_screen.py --from-archive` (read-only).
  - **Constraint**: commit no draft `tenant_overrides.csv` line for a shared host. Copy the log out before any deploy (a deploy wipes `/tmp`). The tool refuses a delete until the replacement page is live under the same government.
  - **History**: `BACKLOG_DONE.md` WO-934 and its follow-ups.

- **[HUMAN] 13 archived YouTube pages point at a video that is gone (7 deleted, 3 private, 3 malformed ids) says a 2026-09-09 study, but the 13 are not on record and no delete is approved on that finding.**
  - **Issue**: the study kept only counts per oEmbed status. `reports/shared_host_lookups.csv` has no status column (a blank channel only means the video did not answer, which also covers embedding-off videos), so the 13 cannot be rebuilt. Of the 184 live pages with a blank-channel lookup there, 181 have English transcripts, so their videos exist; only 3 have none (pages 6114, 6906, 7086). The 2026-09-21 export has 101 YouTube pages with no transcript (89 "Captions disabled / video unavailable", 12 blank). The stored warnings are counts (1 or 0), so local data cannot tell a gone video from disabled captions.
  - **Impact**: no page can be named as gone, so none can be deleted or hidden on evidence. Deleting from the unchecked 101 would remove pages whose videos are alive and only lack captions, which the drip's audio lane can transcribe.
  - **Next action**: (1) the drip Mac owner runs `scripts/check_youtube_video_status.py` on `reports/wo934_youtube_no_transcript_pool.csv` (101 videos, about 4 hours). (2) `python scripts/repair_wrong_pages.py gone-videos reports/wo934_youtube_no_transcript_pool.csv STATUS --exclude-worklist reports/wrong_page_worklist.csv --out ROWS` writes a delete row for each video confirmed gone. (3) Ryan reads each row and writes approve or reject. (4) The Render-shell run, dry run first, with `--video-status STATUS`.
  - **Constraint**: YouTube requests come from the drip Mac only. Three deletes in this group are approved, each on its own grounds: 6114 (a county-homepage intro video, not a meeting) and 6906 and 7086 (Ryan clicked both videos on 2026-09-21 and neither plays; 6906's approval is inferred and being confirmed). Neither 6906 nor 7086 runs until its replacement video (`yTeXBxcodt8`, `PveTE-5yFiU`) is on a live page under the same government. No other page in this group is approved, and none is named until a checked status file exists.
  - **History**: `BACKLOG_DONE.md` WO-934; gov-id enumeration audit, 2026-09-09.

- **[HUMAN] Two TelVue stations (`gmcC3sJ6...`, `5ZgpAPx0...`) still have meetings with no government: nobody has identified who runs them.**
  - **Issue**: WO-1180 pinned 106 TelVue meetings per video from rtr-discovery's no-government list, but left 38 TelVue meetings unpinned, mostly on two stations it could not identify (`gmcC3sJ6AGUdIb568B18VQd22AGea7RE`, `5ZgpAPx0jUMwAvILE2CIBql85kdlcB1R`). The four tokens from the 2026-09-27 ledger are all in `MULTI_GOVERNMENT_TENANTS`.
  - **Impact**: those meetings stay unfiled.
  - **Next action**: identify each station's owner (one live look at a player page each), then pin per video as WO-1180 did, or decide to leave them.
  - **History**: `BACKLOG_DONE.md` WO-1149/WO-1150, WO-1180.

- **[HUMAN] Town Square Television: 3 shows need re-filing, and South St. Paul has no `site=` pin.**
  - **Issue**: `reflect-tst-mn.cablecast.tv` shows `/show/5977` (Mendota Heights), `/show/6267` (West St. Paul EDA) and `/show/5979` (South St. Paul City Council) were rejected `no_government:blank`. The `site=8` and `site=15` pins exist (WO-336); WO-1180 left these shows out because a per-show pin on this host fails `tests/test_tenant_key.py`.
  - **Impact**: 3 real meetings are unfiled.
  - **Next action**: re-run rtr-discovery's `resolve --retry-no-government` for the two with a site pin. For South St. Paul, find its `site=N` with one live check, then add a pin.
  - **Constraint**: no South St. Paul pin without that live check.
  - **History**: `BACKLOG_DONE.md` WO-336, WO-1059, WO-1180.

### Decisions about already-live content

### Laval's own archive: walk its ~260 meeting posts, then decide on the 273 channel-less Laval videos on webtv.coop `[HUMAN]`
- **Decision 2026-10-16**: Ryan, 2026-10-16: queue one meeting only, the shortest available. Needs a run from Ryan's Mac (the cloud cannot reach webtv.coop).

- **Issue**: the webtv.coop adapter now reads Laval's own archive site (`archivesvilledelaval.webtv.coop`, a WordPress site, one post per meeting) and the host is pinned to Laval (`ca:csd:2465005`). Nothing has been walked, queued or ingested from it yet. See `BACKLOG_DONE.md`, "Laval's own archive".
- **Impact**: the site's WordPress API counts 260 posts, 2015-05-05 to 2026-10-07 (not all are council meetings: the categories include ceremonies, press conferences and public consultations). No post has a caption track seen, so each one is Tier 3 (our own transcription). The recent ones are 3 to 4 hours long. Separately, 273 videos on the main webtv.coop site are titled "date + Laval" but carry no channel number, so they stay unpinned; they are NOT covered by this work.
- **Next action**: Ryan said on 2026-10-16 to queue ONE meeting first, the shortest council meeting. Done: the 30 most recent council posts (categories Conseil municipal, Assemblée spéciale, Budget; split "1/2"/"2/2" parts left out) were measured, and the shortest, "Assemblée extraordinaire de la Ville de Laval du 27 avril 2026" (266 seconds), is queued as one tier-3 line with `ca:csd:2465005`. Once its page is live and reads right, Ryan decides whether to queue more (the other short special sittings run 4 to 20 minutes; regular sittings run 3 to 5 hours). For the 273 main-site videos: decide whether to pin them by title or leave them.
- **Constraint**: one request at a time, 3 seconds apart, stop on 429. Each meeting costs 3 requests to resolve (page, stream playlist, chunklist); a length check costs 2, because the WordPress API's post content already carries the stream address (on `streamlock.net`). Never fetch YouTube.
- **History**: built 2026-10-09; findings in `BACKLOG_DONE.md`.

### Some tier-3 lines need YouTube but the drip Mac can't claim them, so they circle the queue `[NEEDS-AUDIT]`

- **Issue**: since WO-1064 the GitHub feed sets aside, instead of dropping, a line that turns out to need YouTube. But the drip only claims lines by URL shape, so two kinds are handled by nobody and go round the queue once a cycle: a page that embeds YouTube indirectly (New Trier Township IL's CivicClerk event, `newtriertwpil.portal.civicclerk.com/event/233/media`, and Alfred and Plantagenet ON's eScribe meeting, `pub-alfred-plantagenet.escribemeetings.com/Meeting.aspx?Id=42c217b8-671f-43a6-a2f9-884e728b2060`, both among the restored lines), and two malformed links with a channel or playlist ID where a video ID belongs (`youtube.com/watch?v=UC1UQVyMyybLHYJrI_Ms7pgA`, `youtube.com/watch?v=PLHelQFD49yC0pEwIoNeti336MKWKm46Wk`).
- **Impact**: 4 lines today. No YouTube requests are made for them, but they never get a page, and each cycle adds a `[YOUTUBE]` row to the feed log.
- **Next action**: for the two malformed links, find the real meeting video each was meant to be (or remove the line); that is Ryan's call. For the indirect case, decide whether the drip should also take lines the GitHub feed has logged `[YOUTUBE]`.
- **History**: `BACKLOG_DONE.md` WO-1064.

### [JUST-DO-IT] 82 archived YouTube meetings have embedding switched off by the owner, so our player shows "Video unavailable" while the video is alive on YouTube and the transcript renders beside it

- **Issue**: WO-135 detects embed-disabled videos and WO-136 shows a "Watch on YouTube" link instead of the dead player, but only for pages resolved after those shipped. The ~82 pages archived earlier (they already have transcripts) were never re-checked.
- **Impact**: those pages show "Video unavailable" in the player, so deep links seek nothing.
- **Next action**: on the drip Mac, run `scripts/check_youtube_video_status.py` (WO-934) over the YouTube pages that have a transcript (2026-09-21 export: 203 with no channel on record), then POST each `embedding_disabled` result to `/internal/pages/{slug}/video-status`.
- **Constraint**: drip Mac only; zero YouTube requests from the cloud or the worker.
- **History**: `BACKLOG_DONE.md` WO-135, WO-136, WO-934.

### [JUST-DO-IT] WO-1004 built a domain-health check for the registry's `domain` field, but it hasn't been run yet — needs a machine with `rtr-business` checked out

- **Issue**: two separate hand audits found the registry's `domain` field wrong or stale on a real slice of rows. WO-347's 60-government audit (15% of a 40-row sample) found stale/dead domains: Emigration Canyon township UT's recorded link actually belonged to a different government sharing the same platform, and the domain itself now redirects elsewhere; Floydada TX and Foristell MO's domains migrated to a new TLD (real content, just moved); Wheaton WI's domain now links to an unrelated tourism bureau's YouTube channel; Elmore City OK's domain was repurposed by a laser-engraving company; Leamington UT's `.gov` domain links to an unrelated ghost-sightings site. WO-145's 25-government under-5,000-population pilot (24%) found a different shape — the domain is real and live, just belongs to a different, usually bigger, government: Ventura city IA → Ventura County CA's tenant; Flemington borough NJ → Hunterdon County NJ's tenant; Crystal River city FL → Citrus County FL's tenant (one candidate on it even resolved as a third city, Inverness FL); Jefferson city OR → Jefferson County OR's tenant; Kearny County KS → an unrelated Town of Kearny, NJ; Hometown city IL → a vendor's own demo tenant, not a real second government. Both times the problem surfaced only because a human hand-audited a sample of pipeline output after the fact — nothing flagged it on its own until this WO.
- **Impact**: if either rate holds across the registry, a meaningful slice of rows are pointed at a domain that will never produce a real page for that government, permanently blocking any future sweep from finding one. The wrong-tenant shape is the more dangerous of the two: it already caused one real wrong-government ingest (WO-145's Crystal River row briefly took on a real Citrus County meeting; caught and deleted the same session).
- **Next action**: run `python3 scripts/wo1004_domain_health_check.py` from a machine with `~/Documents/rtr-business` checked out (resumable — `--limit`/`--concurrency` flags, skips any `gov_id` already in its output on a rerun). It reuses `wo273_targeted.py`'s own fetch and identity-check machinery, adding one new outcome — `domain_mismatch` (page fetches fine but doesn't name the right government) — alongside `domain_confirmed`/`domain_catch_all`/`domain_challenge_gate`/`domain_unreachable`, written to `research/wo1004_domain_health.csv`. Once it's run, hand-confirm every `domain_mismatch`/`domain_catch_all` row before moving a replacement to `alternate_domains`.
- **Constraint**: never blank or overwrite `domain` outright (`CLAUDE.md`'s standing rule) — a confirmed replacement goes to `alternate_domains`/`alternate_urls`, the original stays. Never auto-write the registry from this outcome — same hand-confirm bar WO-347 and WO-145 both used. This session built and unit-tested the tool but cannot run it itself — `rtr-business` is off-limits to it per `CLAUDE.md`'s standing rule.
- **History**: `BACKLOG_DONE.md`'s WO-1004 entry (the build, 2026-09-22), WO-347 (2026-09-13, `research/wo347_wrong_domain_findings.csv`), and WO-145 (2026-09-10). See also this file's "coverage registry's `domain` field maps a small government..." entry (Open bugs) for the still-open shared-helper half of WO-145's finding that WO-1004 doesn't cover.

### `[NEEDS-AUDIT]` SharePoint share links (Yakima County, WA) resolve, but the in-browser player and the download-then-transcribe path are not yet checked with one

- **Issue**: `direct_file.py` now resolves `https://<tenant>.sharepoint.com/:v:/s/<site>/<token>` to the share URL plus `&download=1` (the file URL alone fails without the guest cookie). ffprobe and `follow_with_cookies()` handle that; a browser `<video>` tag and the worker's ffmpeg chunk pull on a real transcription job were not run.
- **Impact**: a Yakima page may show video that will not play for a visitor, or a job may fail at chunk time, even though the ingest dry-run is clean.
- **Next action**: ingest the Yakima link for real (Ryan's call), open the page, and watch the first transcription chunk complete.
- **Constraint**: do not cache the final `.mp4` URL; it redirects to Microsoft sign-in without the cookie.
- **History**: 2026-09-30 PR for audio-only walkers, SharePoint `:v:` and DNN LinkClick links; `direct_file.py` module docstring.

### [JUST-DO-IT] `[EASY]` Page 8494 (Middletown Township, Delaware County PA) is keyed correctly but its permalink slug still carries the government it was first keyed to (`oak-bluffs-ma-…`) — a misleading URL, not a mis-key

- **Issue**: the page is keyed correctly; only its address names Oak Bluffs MA, left over from the WO-183 blank-match bug. WO-925 added `_SLUG_REDIRECTS` in `archive/main.py` for 8494, 7863, 8192, 8309 and 8483.
- **Impact**: the address bar and any shared link name another town.
- **Next action**: Ryan: confirm the Archive deploy carries the WO-925 redirects, then run the five `reslug-page` calls in `BACKLOG_DONE.md`'s WO-925 entry (dry run first) and move this entry to `BACKLOG_DONE.md`.
- **Constraint**: do not re-key the page; never re-key from a slug or title.
- **History**: `BACKLOG_DONE.md` WO-310, WO-316, WO-318, WO-925.

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

### [HUMAN] Five `youtu.be` pages for the Wasatch Front Waste & Recycling District's board (channel `@WasatchFrontWaste`) sit under Wasatch

- **Issue**: the registry row `rtr:us:ut:wasatch-front-waste-recycling-district` exists (governments.csv:1130) and channel pins are supported, but there is no `@WasatchFrontWaste` pin and the pages were never overridden.
- **Impact**: 5 pages (6584, 6973-6976) show on Wasatch County's hub.
- **Next action**: add a `youtu.be`/`www.youtube.com` `channel=@WasatchFrontWaste` pin row, then on the Archive run `POST /internal/jurisdiction/override?ids=6584,6973,6974,6975,6976&gov_id=rtr:us:ut:wasatch-front-waste-recycling-district`, dry run first.
- **History**: found spot-checking the 2026-09-09 backfill; decision D2 (own `gov_id`).

### [EASY] `scripts/wo288_youtube_date_backfill.py` is built and dry-run verified (1,349 pages would be corrected) but not yet applied -- needs one Render Shell run

- **Issue**: WO-288 (2026-09-12) re-derived WO-285's 1,298-page audit
  with the real production title-date parser, built the correction
  script, and dry-ran it against the live Archive DB. It has not
  written anything yet.
- **Impact**: 1,349 archived YouTube pages still show the wrong date
  to readers until this runs.
- **Next action**: from the Archive service's Render Shell, run
  `python scripts/wo288_youtube_date_backfill.py --apply --report
  /tmp/wo288_apply_report.csv`, then spot-check a handful of the
  written rows against their real `/m/{slug}` pages.
- **Constraint**: none -- script is tested and merged. Never run
  `--apply` from a laptop against the production `DATABASE_URL`.
- **History**: `BACKLOG_DONE.md`'s WO-285 and WO-288 entries,
  2026-09-12.

### [NEEDS-AUDIT] `[EASY]` Existing Vimeo meetings may be secretly tier 1: re-resolve the ones without a transcript

- **Issue**: Vimeo captions work (PR #643), but pages filed before then are video-only (32 pages across 18 governments on 2026-09-23). WO-1147 built the `vimeo` drip lane (`GET /internal/transcript-wanted?platform=vimeo`). It is not in the default `--lanes`, and as of 2026-10-12 (WO-1961) it is still off.
- **Impact**: up to 32 pages could show real captions, and Vimeo queue lines could skip paid transcription.
- **Next action**: Ryan restarts the drip with `--lanes captions,feed,audio,vimeo` (plus `direct` if used), then checks a fresh count of untranscribed Vimeo pages.
- **History**: WO-1146/1147 (2026-09-27), WO-1961 (feed lane skips Vimeo lines while the lane is off).

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

### `[HUMAN]` YouTube-sourced transcripts and the data product: is there a clean provenance route?

- **Issue:** every YouTube caption path here uses InnerTube (yt-dlp, youtube-transcript-api) from the drip Mac. The official Data API's `captions.download` needs the video owner's OAuth, so there is no API-key route.
- **Impact:** the data product excludes YouTube-sourced transcripts, roughly halving the sellable roster.
- **Next action:** Ryan decides whether to pursue per-government channel authorization or public-records requests for caption files, or to accept the exclusion. Where archive.org mirrors the same meeting (WO-1962), that source may already give clean provenance.
- **Constraint:** do not change the current InnerTube path in the meantime.
- **History:** `BACKLOG_DONE.md` (the 2026-08-10 YouTube experiment entry that confirmed the OAuth requirement); rtr-business `data-product/RESEARCH_2026-09-01.md`.

### `[IMPROVEMENT-ROUND]` Full Context entries on YouTube-backed meetings show the generic YouTube thumbnail, not the clipped moment

- **Issue**: `/m/{slug}/card.jpg` redirects a YouTube-backed meeting to
  YouTube's own standard thumbnail regardless of `t` (see "Meeting card
  images" above) — only a non-YouTube meeting gets a true extracted
  frame at the timestamp. Many meetings that get clipped on social
  media are on YouTube.
- **Impact**: many Full Context entries will show a generic video
  thumbnail rather than the actual clipped moment, weakening the
  entry's own visual hook.
- **Next action**: Ryan's call between two options — accept the generic
  thumbnail as a known limitation, or extract a real frame for
  YouTube-backed pages, which this app has deliberately not done so
  far (YouTube serves its own thumbnail cheaply; a real frame would
  need downloading/seeking the video, unlike the ffmpeg extraction
  already used for non-YouTube pages).
- **History**: `BACKLOG_DONE.md`'s WO-943 entry (states the caveat);
  README's "Meeting card images" section (the existing YouTube-redirect
  behavior this inherits).

### [IMPROVEMENT-ROUND] Lifecycle-triggered transactional emails (Resend) — built 2026-08-11, not yet live-verified

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

## Open bugs — real, root cause not settled `[NEEDS-AUDIT]`

- **[NEEDS-AUDIT] Tampa deep links assume the video starts at the first caption (found 2026-10-09, WO-1960).**
  - **Issue**: Tampa's transcript stamps are wall-clock times of day (for example 5:04:14 PM), not positions in the video. `app/platforms/tampa.py` turns the first caption's clock time into video 0:00 (`t0 = raw_entries[0][0]`, line 422) and nothing checks it. On meeting 2698 (2026-08-20) the page header gives a 5:01 PM start and the first caption is at 5:04:14 PM, a 3 minute 14 second gap; whether the video starts at the first caption was never measured. There is also no midnight handling: a line stamped after midnight gives a negative offset and `max(0, seconds - t0)` (line 425) clamps it to 0.
  - **Impact**: if the video has any lead-in, every Tampa deep link and click-to-seek is off by that amount (unmeasured). A meeting that runs past midnight puts all later lines at 0:00.
  - **Next action**: on the drip Mac, play the video for pkey 2698 (YouTube `DJD_5jUOmLc`) and one more pkey, note the video time of three known spoken lines, and compare with the offsets the adapter gives. Then set the offset from the measured start, handle midnight by adding 24 hours when the clock drops below the previous line, and add a fixture test from the saved `tests/fixtures/tampa/` pages.
  - **Constraint**: YouTube requests come only from the drip Mac (`docs/YOUTUBE_DRIP_RUNBOOK.md`); do not play or fetch the video from any other machine.
  - **History**: found 2026-10-09 while reading Tampa's live transcript page; not investigated further.

- **[NEEDS-AUDIT] Some stored captions do not line up with their video, so deep links land at the wrong moment (found 2026-10-10, WO-1960).**
  - **Issue**: matching a meeting's audio to its stored captions with a speech model (`scripts/align_captions_to_audio.py`, 2-minute windows) found pages whose caption times differ from the video by far more than normal live-caption lag (1 to 6 seconds): Dunnellon FL 2026-07-15 (about 13 minutes, 0% agreement at three sampled points), Coral Gables FL 2023-06-01 (32.6 seconds off for the first half, 4.3 seconds after a step near the middle; the video is 7.46 hours and the captions cover 3.41), and Venice FL 2026-08-25 (99% agreement to the midpoint, about 20% in the last third). Frame rate was checked and is not the cause: drift was under 1 second an hour on most meetings.
  - **Impact**: on those pages transcript click-to-seek and `?t=` links go to the wrong moment and nothing flags it. How many of the roughly 7,000 sourced pages are affected is unknown: 24 meetings were checked, chosen for human captions, not at random.
  - **Next action**: **Claimed 2026-10-16** (office Mac session, A4): 100-page non-YouTube audit; report `wo-a4_caption_audit_2026-10-16.md`. Pick 100 sourced pages at random, run the aligner's window check on each (it needs the page's audio), and count pages with a median lag over 10 seconds or a step. If more than a few show up, store a per-page offset map and apply it when the page seeks.
  - **Constraint**: needs audio from the city's own host (some serve about 150 KB a second; Granicus wants a normal Referer); the check runs about 12 times faster than real time on a laptop CPU. No YouTube pages from a machine other than the drip Mac. Do not bulk-fetch one host in one go.
  - **History**: results in rtr-business `research/CAPTION_METHODOLOGY.md` and `data-product/samples/E_annotated_speech/alignment/`.

- **[NEEDS-AUDIT] Meeting Finder picks the wrong clip from a Granicus archive on a shared host (found 2026-10-05, Bay Area transit run).**
  - **Issue**: given a `ViewPublisher.php?view_id=N` link on a Granicus host shared by several bodies, `scripts/meeting_finder.py --entry start` ignored the view. Three SamTrans-family views (ids 1, 2, 3) all returned the same old clip (`view_id=1&clip_id=1516`, note "picked by: undated, lister order"); TAM's view 24 returned a Marin County clip; TJPA's view 29 returned a view 2 clip. `granicus.list_recent_video_meetings()` on the same URLs returns the right view, newest first, so the fault is in how the runner picks, not in the lister.
  - **Impact**: a find on a shared Granicus host can be an old or wrong-body meeting. Identity says "silent" or "disagrees", which only a hand read catches.
  - **Next action**: find which path the runner takes for a `ViewPublisher` entry (it never reached the lister's newest-first order) and make it list that view's clips, newest first, before picking. Add a fixture test with a shared-host listing of 2+ views.
  - **Constraint**: until fixed, hand-list each Granicus view with `list_recent_video_meetings()` and resolve the newest clip; always send the government's own `gov_id` (the resolver names the host's owner, e.g. "County of Marin" for TAM).
  - **History**: found 2026-10-05 in the Bay Area transit session; results in rtr-business `research/bay_area_transit_2026-10-05.md`.

- **[NEEDS-AUDIT] Near-empty station captions are only guarded on Cablecast and Swagit (found 2026-10-04, WO-1181).**
  - **Issue**: `caption_text_is_sparse()` gates Cablecast and (WO-1181) Swagit. Granicus, eScribe, CivicClerk, TelVue and the other caption platforms have no such gate, and only Swagit's stored pages were scanned (1 of 448 under 8 words a minute).
  - **Impact**: unknown. A near-empty caption feed on those platforms still passes as a good transcript and is never sent to Whisper. About 7,171 sourced pages are stored in total.
  - **Next action**: scan all sourced default versions for words a minute under 8 (span 10+ minutes) from the Render shell, not from a laptop. Report counts per platform, then gate the adapters that show hits and mark existing pages by hand with `_SPARSE_CAPTIONS_MARKER` via `correct-warnings`.
  - **Constraint**: the scan reads every `segments` blob; run it on Render, per the bulk-sweep rule. Page 12372's marker is a separate manual step after deploy.
  - **History**: WO-1181 in `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] 10 Cablecast pages on shared cable-channel hosts have no government (found 2026-10-03, WO-1176).**
  - **Issue**: while re-keying 70 Whisper-made pages that had an unknown government, 10 more were Cablecast pages on a shared cable-channel host with no `tenant_overrides.csv` pin. A different cause from the missing `gov_id` WO-1176 fixed: no queue line names their government.
  - **Impact**: those 10 pages stay filed as `rtr:unknown:<host>` (no hub, no identity).
  - **Next action**: census each channel (one meeting per government, per-video pins, see the shared-host channel census rule), write the pins, then re-key the 10 with `/internal/jurisdiction/override` (dry run first).
  - **Constraint**: do not reslug existing pages (Ryan, 2026-10-03). A pin needs a real source.
  - **History**: `BACKLOG_DONE.md` WO-1176.

- **[NEEDS-AUDIT] Every stored iQM2 recording tried on 2026-09-27 is gone at the source — 24 Archive pages across 19 tenants now point at video that returns 404 (WO-1152).**
  - **Issue**: the media files on `MediaHTTP.IQM2.com/<Tenant>/<id>_480.mp4` behind 24 Archive pages (19 tenants) return HTTP 404; the tenant's own `SplitView.aspx` still links the dead file. On Prescott AZ newer recordings 404 too. Several tenants have since moved to CivicClerk or a new site (WO-1158, WO-1159, WO-1161, WO-1163).
  - **Impact**: 24 pages show a video that does not play and can never get a transcript. Nothing tells the reader.
  - **Next action**: mark the 24 pages with a reader-facing "video no longer available at the source" warning. Then check one still-active iQM2 tenant's newest recording: if it 404s too, stop offering iQM2 video as a transcription source in `app/platforms/iqm2.py`.
  - **Constraint**: do not delete the pages; the agenda and the page still have value.
  - **History**: `BACKLOG_DONE.md` WO-1152 (#1550, #1609 evidence update).

- **[NEEDS-AUDIT] `cablecast.py`'s "Cablecast Connect" resolve path 404s on a real tenant whose own `watch-vod-embed` page already carries the video data directly.**
  - **Issue**: `_resolve_watch_vod_embed()` always delegates to `_resolve_fastboot_embed()`'s `{origin}/embed/vod?show=&site=` endpoint, and discards its "embed unreachable" flag. On Town Square TV (`reflect-tst-mn.cablecast.tv`, Mendota Heights MN, show 5977 site 8) that endpoint is a 404, so resolve fails with "Could not find a show id".
  - **Impact**: Meeting Finder's Cablecast Connect lister (WO-1054) finds this tenant's meetings, but Resolve cannot finish them. Any other Cablecast Connect site on the same template hits the same wall.
  - **Next action**: when the `/embed/vod` fetch is unreachable, fall back to `_resolve_publicsite()` (the CablecastPublicSite JSON API, already used this way for the `/show/` path since #1637) before trying to parse the large `watch-vod-embed` page. Verify on show 5977.
  - **Constraint**: WO-1180 notes this host's pins are keyed by `site=N`; a per-show pin there is refused by `tests/test_tenant_key.py`.
  - **History**: `BACKLOG_DONE.md` WO-1054, WO-1180.

- **[NEEDS-AUDIT] The government registry creates duplicate ids and matches the wrong place for some real governments (Meeting Finder calibration run B, 2026-09-24).**
  - **Issue**: Meeting Finder's identity check disagreed on 11 of 272 real finds in calibration run B. Most were registry problems, not wrong finds: (1) a duplicate `rtr:` id was created for a government that already has a real id: Leduc County AB, Cape Elizabeth ME, Ogunquit ME, Wappinger NY, Teaneck NJ, Prince William County VA (and Wake County NC -> `rtr:us:nc:wake-county-north-carolina` in run A); (2) a name matched the wrong place: Newmarket NH -> Newmarket, Ontario (`ca:csd:3519048`); "Stephentown" -> `rtr:us:ny:stephen`; Petersburgh NY -> `rtr:us:ny:petersburg`. Evidence: rtr-deeplink Meeting Finder scratch output `calB/verdicts.csv` (identity_verdict = disagrees, identity_points_to).
  - **Impact**: a pin or ingest resolved through the registry can file a page under a duplicate or a different government; coverage counts double or miss. Identity "disagrees" is also noisy, which is why Meeting Finder now sends it to a person (WO-1041).
  - **Next action**: reproduce each case with `app/utils/gov_registry/resolver.py` (name + state -> id) and find why a new `rtr:` id is minted when a real one exists (likely a name-normalisation miss: "town", "township", county suffixes, "-north-carolina" style slugs) and why a cross-border/prefix match wins (Newmarket, Stephen/Stephentown). Fix the matcher, then merge the minted duplicates into the real ids.
  - **Constraint**: never rebuild the registry or the research file through a gov_id-keyed dict (duplicate/blank ids exist); read `docs/COVERAGE_HANDOVER.md` §3 (identity) first.
  - **History**: found 2026-09-23/24 by Meeting Finder calibration runs A and B (conductor session 93b5f9ae).

- **[NEEDS-AUDIT] Meeting Finder files another government's meeting under the searched one, through guessed CivicWeb accounts and state-agency accounts (no-platform-signature run, 2026-09-26).**
  - **Issue**: of 44 wrong-government finds in the 2026-09-26 hand-check, two sources are still unhandled: (a) a civicweb tenant guessed from the name (`mapleton.civicweb.net` matched to 4 US governments, `hamilton` to 2, the empty template account `riverside` to 3); (b) state-agency accounts linked from district sites (Missouri DESE's Vimeo for 6 districts, Michigan's `misenate` Castus for 2). Shared school/town TV accounts are handled by WO-1078; the Cuddeback/Humboldt COE page by WO-1079.
  - **Impact**: wrong-government finds and research rows; the ingest `gov_id` pin does not catch them.
  - **Next action**: treat a civicweb/Diligent subdomain guessed from the name as a lead only unless its page title names the searched government; drop known state-agency accounts (DESE, `misenate`, `usbe`, tn.gov) as a district's own.
  - **Constraint**: never discard these meetings; another government's meeting is a good find, filed under that government (Ryan).
  - **History**: `BACKLOG_DONE.md` WO-1078, WO-1079; verdicts in session 93b5f9ae `scratchpad/hc7/all_verdicts.csv`.

- **[NEEDS-AUDIT] Meeting Finder's video gate rejects some real board meetings as not-a-meeting, and the identity check wrongly says "disagrees" on some real ids.**
  - **Issue**: after WO-1049 (#1430) fixed the missing filename/Drive-title evidence, two causes of demoted real meetings remain: the video gate's `hand_check_kind` rejects real board meetings (Sag Harbor SD "Board of Education Business Meeting", SFUSD "Board of Education"), and the identity check said "disagrees" on 3 real approvals because an id was written a different way (e.g. Robbinsdale ISD).
  - **Impact**: some real finds land as weak leads and wait for a person instead of flowing to ingest or the queue.
  - **Next action**: add those titles as fixture cases to `app/utils/video_hand_check.py`'s tests and fix the gate's rule; reproduce the Robbinsdale id mismatch in the identity check.
  - **Constraint**: Ryan's rules stand: dates order, never eliminate; every filter keeps at least one labelled weak lead.
  - **History**: `BACKLOG_DONE.md` WO-1041 (#1408) and WO-1049 (#1430).

- **[NEEDS-AUDIT] Swagit tenants whose `/views/{id}` page is not known yet are still under-listed, and category pages are read only to their first page.**
  - **Issue**: a Swagit tab-slug page is an empty JS shell; only a numeric `/views/{id}` page lists meetings. WO-1081/1087/1091/1123 built `app/utils/jurisdiction_data/swagit_views.csv` from owner proof, WO-1085 reads every tab, WO-1102 follows index views to category pages, and #1824 returns a hub pick list. Still open: tenants with no known view (measured 252 of 438 on 2026-09-26, not re-counted), and category pages beyond page 1 (San Benito TX has 26).
  - **Impact**: those tenants' meetings are not found by bulk sweeps; older meetings on long category lists are skipped.
  - **Next action**: re-count tenants with no view in `swagit_views.csv`; map the rest by matching a view page's video numbers to videos the Archive already holds (one tenant per view, at least 2 matches); follow category-page pagination.
  - **Constraint**: view and video numbers are shared across all Swagit hosts: read them, never guess. Stop at the first 429 or challenge page.
  - **History**: `BACKLOG_DONE.md` WO-1036, WO-1081, WO-1087, WO-1102, WO-1123; rtr-discovery PRs #42, #79.

- **[NEEDS-AUDIT] `[EASY]` `municode_meetings.py` cannot tell an agenda-only tenant apart from an empty one, and Meeting Finder's List has no fallback for it.**
  - **Issue**: `municode_meetings.py`'s `resolve()` still builds its pick list from `_find_video_rows()`, which drops rows without video, the shape CivicPlus had before its 2026-09-07 fix. CivicPlus got a List fallback (`listing._civicplus_agenda_only_fallback()`, WO-1028); Municode Meetings did not.
  - **Impact**: an agenda-only Municode Meetings tenant not covered by rtr-discovery's enumerator reports "nothing found" instead of "meeting found, no video".
  - **Next action**: return every real row from `_find_video_rows()` (rename it as CivicPlus's was) and add `_municode_meetings_agenda_only_fallback()` to `app/platforms/meeting_finder/listing.py`; test with a saved Bristol RI fixture.
  - **History**: `BACKLOG_DONE.md` WO-1028. The `verify_hub()` half is dropped: the sweep scripts that use it were replaced by Meeting Finder.

- **[NEEDS-AUDIT] `[EXAMPLE]` `civicplus.io`: platform or CivicPlus web host? Not decided — defaulting to platform pending real data.**
  - **Issue**: `app/platforms/host_recognition.py`'s WO-1015 replay (2026-09-23) found `civicplus.io` CDN hosts (`pt-west-001.civicplus.io`, `guardian.civicplus.io`) via `detect_platform()`'s own bare `"civicplus"` substring branch (`app/platforms/base.py`). That branch was written for `civicplus.com` tenants; whether `civicplus.io` is the same kind of real per-government tenant host, or CivicPlus's own general-purpose website hosting (the same shape Ryan ruled `granicusgovaccess.net` to be on 2026-09-23 — see `BACKLOG_DONE.md`'s WO-1015 entry — "a hint/signature ... sometimes but it is in fact a web host") has not been checked against real data either way.
  - **Impact**: every `civicplus.io` host currently counts as a confirmed CivicPlus platform match, both in `detect_platform()` and in `host_recognition.py`'s stage-2/3 discovery helpers — an unverified default, not a confirmed classification, in either direction.
  - **Next action**: Ryan's call (2026-09-23, verbatim): "we need to base the civicplus.io decision on real examples and data - can you default to keeping it for now but note in the backlog that we should look for signs of civicplus.io in our research file and archive, and see if we would benefit from thinking about it as a different platform." Concretely: count governments in `rtr-business/research/jurisdiction_coverage.csv` and the stage-2 DNS/CNAME sweep results whose domain CNAMEs to or links a `civicplus.io` host, and count Archive pages whose `source_url`/`platform` is CivicPlus; then compare how many of those actually have a real AgendaCenter with video vs. agenda-only vs. nothing, the same way `civicplus.com`'s own real tenant behavior is already characterized (`civicplus.py`'s own module docstring). Decide from that whether `civicplus.io` should move to `VENDOR_WEB_HOST_HINTS` (a hint, not a platform match, mirroring `granicusgovaccess.net`) or stay a confirmed platform host.
  - **Constraint**: keep it classified as `"civicplus"` (no code change) until that data exists — do not guess either way.
  - **History**: `BACKLOG_DONE.md`'s WO-1015 entry (the replay that surfaced this); `app/platforms/base.py`'s civicplus branch carries a one-line comment pointing back here.

- **[NEEDS-AUDIT] Seven hand-confirmed government platform links still can't be turned into a meeting: three broken or empty, three tenant front doors, one tenant with no video.**
  - **Issue**: broken or empty: Georgetown CO (`townofgeorgetown.ompnetwork.org/embed/full`, the OpenMedia adapter expects `/sessions/{id}`), Marina CA (TelVue media 545969 now 404), Broadview Heights OH (ChampDS event 315, no video). Tenant front doors: IQM2 (Macoupin County IL), Swagit (Barnegat NJ), PrimeGov (Dodge County MN). No video: Hutchinson County TX (CivicClerk).
  - **Impact**: 7 governments with a confirmed platform and no meeting page.
  - **Next action**: re-run the three front doors through Meeting Finder: IQM2, Swagit and PrimeGov hub URLs now return a pick-a-meeting list (#1809, #1824). For Georgetown, find its `/sessions/{id}` URLs (YouTube media, so drip lane).
  - **History**: `BACKLOG_DONE.md` WO-912, WO-913; `rtr-business/research/wo912_wo913_ingest_log.csv`.

### Blackstone, MA's Castus hub walk resolves, but to a 5-day-stale meeting -- the newest one is skipped because its title has no governing-body word `[NEEDS-AUDIT]`

- **Issue**: confirmed live 2026-09-26 -- `https://cloud.castus.tv/vod/blackstone/?page=HOME` resolves through `castus.py`'s new hub walk (#1363), but to the 2026-09-16 "Zoning Board" meeting, not the real newest one, a 2026-09-21 "Parks and Recreation" meeting. `_pick_newest(candidates, require_allowlist=True)` calls `looks_like_real_meeting(title, require_allowlist=True)` on each candidate's `metadata.filename`; "Parks and Recreation 09-21-26.mp4" fails that gate (no governing-body word the allowlist recognizes) and is skipped in favor of the next-newest candidate that passes.
- **Impact**: any Castus hub resolved this way can silently return a meeting up to `_HUB_CANDIDATE_LOOKBACK`-worth of days stale whenever the real newest meeting's own filename doesn't happen to carry an allowlisted word (parks/recreation boards, not just planning/zoning/select boards, are common enough that this isn't a one-off).
- **Next action**: either widen `looks_like_real_meeting`'s allowlist to cover more real governing-body types (parks, recreation, conservation, library, water/sewer commissions -- check what other skipped Castus/Cablecast candidates look like first) or, for the hub-walk path specifically, fall back to accepting an otherwise-well-formed newest candidate rather than silently preferring a much older allowlisted one.
- **Constraint**: don't loosen the allowlist so far it re-admits the kind of non-meeting video (sports, promotional) it exists to filter -- check a sample of real non-meeting Castus/Cablecast titles before changing it.
- **History**: found by the session that built #1363 (2026-09-25/26); re-confirmed live 2026-09-26 (`_id` 6ab1b9a3.../"Parks and Recreation 09-21-26" vs the picked `_id` 6aab2089.../"Zoning Board 09-16-26").

### Self-hosted Castus VOD widget (`{tenant}.vod.castus.tv`) has no adapter; meetings are queued as raw S3 files `[LATER]`

- **Issue**: the self-hosted Castus VOD Widget (own `/api/v1/...`, UUID video ids) is a different product from the `cloud.castus.tv` SPA `castus.py` walks; `resolve()` returns a clean warning for it. The "find more examples" trigger has passed: #1951 and #1956 queued 72 meetings from 9 such stations (Boxford, Lynn, Millbury, Bolton, Sturbridge, Greene, Kitsap County, two school committees) as direct S3 `video.original.mp4` files.
- **Impact**: Millbury and the others are covered by hand-built queue lines; a new station or a newer meeting needs another hand pass, and a pasted station URL does not resolve.
- **Next action**: decide whether to build a resolver/lister for `{tenant}.vod.castus.tv` from the API shape these 9 stations already showed.
- **History**: #1363 (cloud adapter), #1951, #1956.

- **[NEEDS-AUDIT] `[EASY]` Two writers still emit the dead `<id-prefix>:<id>` pin shape: `archive/db/crud.py::_multi_gov_match_for_video_url()` (Vimeo) and 1,374 committed YouTube `youtube:<id>` rows.**
  - **Update 2026-10-16**: Partly fixed in the backlog round-2 PR (`cc51c866`): 1,117 youtube:<id> pins rewritten to the bare id and 255 exact duplicates dropped; has_owner() now misses 0 (was 1,054). Left: 2 pins that disagree with a bare pin (lNJoncQNJbM Clinton town vs village NY; s2TTtUcnzag Millinocket school district vs town), then make match_shape_problem() refuse the prefixed shape.
  - **Issue**: (1) `_multi_gov_match_for_video_url()` (`archive/db/crud.py` line ~4053) drafts a Vimeo rule as `vimeo:<id>`, which the loader refuses since WO-924. (2) `tenant_overrides.csv` has 1,374 `youtube:<id>` rows; they match at ingest through the `external_id` hint but not in `queue_probe.has_owner()`, which passes no hints.
  - **Impact**: (1) a wrong draft that fails CI if pasted. (2) a YouTube queue line can be refused as "no owner" though a pin exists; count not measured.
  - **Next action**: (1) return the bare Vimeo id and update the docstring and its test. (2) measure how many `youtube:` rows `has_owner()` misses, rewrite them to the bare 11-character id, and make `registry.match_shape_problem()` refuse the prefixed shape.
  - **Constraint**: keep each row's `source` and gov_id; never drop a row that is the only pin for its video.
  - **History**: `BACKLOG_DONE.md` WO-924.
  - **Update 2026-10-16**: Partly fixed in #2077 (`6365d170`): New override drafts use the bare Vimeo id; rewriting ~1,400 youtube:<id> rows still open.

- **[NEEDS-AUDIT] Four Kind-A/wrong-domain findings from WO-349's CivicPlus run need the owning government matched: Town of Hempstead NY, City of Melbourne FL, Seward County KS, City of Bossier City LA.**
  - **Issue**: WO-349 found four hubs or videos that belong to a different real government than the row: Hempstead village's hub links the Town of Hempstead's YouTube; Melbourne Village links the City of Melbourne; Seward city's Swagit tenant is Seward County's; Bossier Parish's hub is the City of Bossier City's site. Bossier City already has YouTube channel pins (`us:place:2208920`).
  - **Impact**: up to 3 real videos or tenants unused.
  - **Next action**: for Hempstead town, Melbourne city and Seward County, check whether the owner has a pin or page; if not, add one from `research/wo349_owner_bodies.csv`.
  - **Constraint**: Hempstead and Melbourne were read from channel handles only (no YouTube fetch); confirm before pinning.
  - **History**: `BACKLOG_DONE.md` WO-349.

- **[NEEDS-AUDIT] 146 tier-3 queue lines on shared video hosts have no proven government (WO-346).**
  - **Issue**: WO-346 found 478 queue/deferred lines on `MULTI_GOV_HOSTS` hosts with no pin; 332 were pinned from evidence, 146 had none (`scripts/wo346_hand_read.csv`). `has_owner()` keeps them in the queue rather than ingesting them as `rtr:unknown`. Not re-counted since; later queue clean-ups (#1691, #1772) and pins (WO-1180) may have removed many.
  - **Impact**: real coverage stalled until each owner is confirmed.
  - **Next action**: re-count which of the 146 are still in the queue without an owner; hand-read the rest and write per-video pins.
  - **Constraint**: never pin from a video id or a plausible channel name alone; 9 lines had two disagreeing evidence sources.
  - **History**: `BACKLOG_DONE.md` WO-346.

- **[NEEDS-AUDIT] `[EASY]` Pierce County WA's tier-3 queue line may be a stale 2022 non-council video.**
  - **Issue**: WO-341's hand-read found Pierce County's hub leads to "SSHAP Executive Board Meeting - May 6, 2022" on Vimeo, stale and not clearly the county's own body. The queue still holds `https://vimeo.com/707985726` for `us:county:53053` (line 249); an id in that range dates from about May 2022, so it is likely the same video.
  - **Impact**: a wrong, stale meeting may be transcribed and published as Pierce County's.
  - **Next action**: check the title of Vimeo 707985726 (oEmbed); if it is the SSHAP video, remove the queue line.
  - **History**: `BACKLOG_DONE.md` WO-341. The Rowan County NC registry-label half is dropped (one-off; Meeting Finder's WO-1131 rerun re-derived platforms).

- **[NEEDS-AUDIT] `fetch_headless_sync()` has no wall-clock limit on browser start-up, and Meeting Finder calls it without one.**
  - **Issue**: `scripts/wo147_access_ladder_sweep.py`'s `fetch_headless_sync()` bounds `page.goto` (15 s) but not `sync_playwright()` start-up or `chromium.launch()` beyond Playwright's own default. Meeting Finder's fetch rung (`app/platforms/resolving/fetch.py`, `_headless()`) runs it via `asyncio.to_thread` with no deadline. WO-337 saw a 400-government chunk at concurrency 32 hang for 9+ minutes with several headless renders at once.
  - **Impact**: a large Meeting Finder run can stall with no warning when many governments hit the headless rung together.
  - **Next action**: cap concurrent headless renders in `fetch.py` (WO-337's 4-way semaphore is the reference) and put a deadline around the call that also kills the browser process.
  - **Constraint**: `Future.result(timeout=...)` only stops waiting; it leaks a stuck Chromium. Use a killable launch.
  - **History**: `BACKLOG_DONE.md` WO-337; `scripts/wo337_targeted.py`'s `HEADLESS_SEMAPHORE`. The old `wo273_targeted.py` caller is retired (WO-1019).

- **[NEEDS-AUDIT] 6 TelVue pages still keyed to Pittsford village NY have no proven government (pages 3368, 3371, 3385, 3415, 3420, 3421).**
  - **Issue**: WO-318 hand-read about 40 pages left by the old blank-match TelVue pin and closed 34. These 6 name no government in any frame checked. Page 3368's media is gone at the source. WO-1180 also left TelVue stations `gmcC3sJ6` (page 3371) and `5ZgpAPx0` (page 3421) unidentified.
  - **Impact**: 6 pages show the wrong government (`us:place:3658354`).
  - **Next action**: delete page 3368 (media gone); for the other 5, check a different frame or listen for a spoken place name, then re-key with `/internal/jurisdiction/override` (dry run first). Station tokens are in `BACKLOG_DONE.md` WO-318.
  - **Constraint**: do not re-key from title alone.
  - **History**: `BACKLOG_DONE.md` WO-316, WO-318, WO-1180.

- **[JUST-DO-IT] YouTube video `ci9jnPULx5M` is pinned to Ste. Genevieve city, MO, but its own title says it is St. Mary, MO's Board of Aldermen.**
  - **Issue**: the `tenant_overrides.csv` row (`wo175_localview_recheck`) quotes the title "St. Mary (Mo, USA) Board of Aldermen, Tax Hearing" and pins it to `us:place:2964180` (Ste. Genevieve). St. Mary city, MO exists as `us:place:2965034`.
  - **Impact**: Ste. Genevieve shows coverage that belongs to St. Mary, and St. Mary shows none.
  - **Next action**: repoint the pin to `us:place:2965034`. If an Archive page exists, re-key it in production through `/internal/jurisdiction/override`. Mark Ste. Genevieve's research row as no-video unless `@Stegentv` has a real Ste. Genevieve meeting (checking that is drip-Mac work).
  - **History**: `BACKLOG_DONE.md` WO-258 part 2.

- **[NEEDS-AUDIT] Real meetings found under the wrong government, never filed under their owner: NYS Board of Elections, Early County GA schools, Springfield MA School Committee, Chisholm MN.**
  - **Issue**: hand-read gates caught each one before ingest. `@NYSBOE` (found on Orleans County NY's row) is a state agency. `@earlycountyschoolsystem1705` (Early County GA) is a school district. The Springfield School Committee's CivicClerk event was found on Springfield city's row. "Chisholm City Council, September 9th, 2026" is on Mesabi Community TV (found on Mountain Iron MN's row).
  - **Impact**: real leads sit unused. Springfield city's existing Archive page, on the same `springfieldma.portal.civicclerk.com` tenant, may be a School Committee meeting filed under the city.
  - **Next action**: check Springfield city's live page first and re-key it if it is the School Committee. Then look up the gov_ids (`us_school_districts.csv`, `us_places.csv`) and resolve and ingest each video under its owner. Ryan accepted state bodies as in scope (#1613), so the NYSBOE can be minted.
  - **Constraint**: never pin any of these to the government whose row found it.
  - **History**: `BACKLOG_DONE.md` WO-258, WO-264.

- **[NEEDS-AUDIT] Check whether BoxCast re-signed Livermore Falls ME's and Bartow FL's playlists after the 2026-09-13 expiry.**
  - **Issue**: WO-229 asks BoxCast for a fresh signed playlist at view time. That only helps if BoxCast issues a new `Expires=` once 1789329408 (2026-09-13 19:56 UTC) has passed. That date has passed, and nobody has recorded a result.
  - **Impact**: if BoxCast did not rotate it, both pages have shown a dead video since 2026-09-13.
  - **Next action**: `curl -sI https://rtr-deeplink-archive.onrender.com/m/livermore-falls-me-2026-09-01-livermore-falls-select-board-meeting-september-1st/video` (and Bartow's slug), then confirm the redirect's `Expires=` is later than 1789329408 and that it plays. If it does, close this. If not, it becomes a `[HUMAN]` BoxCast-support item.
  - **History**: `BACKLOG_DONE.md` WO-229.

- **[NEEDS-AUDIT] Wheatfield town, IN's Town Board videos are linked from Wheatfield town, NY's AgendaCenter, and one may be pinned to the NY town.**
  - **Issue**: `wheatfield-ny.gov/AgendaCenter` links meeting videos from the channel "Town of Wheatfield" that are Wheatfield town, IN's (`us:place:1883528`). Pin `youtube:keVEP85fA4w` (WO-221: channel "Town of Wheatfield", title "May 4, 2026 REGULAR TOWN BOARD MEETING") is keyed to Wheatfield NY (`us:cousub:3606381380`). That is the same channel name.
  - **Impact**: possibly an Indiana meeting filed under a New York town. Unverified.
  - **Next action**: on the drip Mac, check `keVEP85fA4w`'s channel and description. If it is Indiana, repoint the pin to `us:place:1883528` and re-key any page.
  - **Constraint**: the NY research row (`wrong-domain-mapping`) is correct; leave it alone.
  - **History**: `BACKLOG_DONE.md` WO-174 close-out.

- **[NEEDS-AUDIT] Two manual_override town pages resolve, via a fresh ladder run, to a same-named COUNTY — a likely name-collision bug in the registry lookup, not a real government change.**
  - **Issue**: WO-215's dry run of `scripts/backfill_gov_id.py` (restricted to `www.youtube.com,youtube.com,youtu.be`, 2026-09-11) found two `manual_override` pages whose fresh resolve landed on a county with the same name as the town: page 8226, "Ulster Town, NY" (`us:cousub:3611175935`, a real township id) resolved fresh to `us:county:36111` (Ulster **County**, NY — a different, larger government); page 8230, "Lincoln, ME" (`us:cousub:2301939475`) resolved fresh to `us:county:23015` (Lincoln **County**, ME). Both evidence strings read `us_counties.csv Ulster County` / `us_counties.csv Lincoln County` — the classifier looks like it is matching the town's own name against the *counties* table and winning, when the government at that host/page is the town, not the county.
  - **Impact**: none today — WO-215's fix protects every `manual_override` row's `gov_id` from this backfill unconditionally, so neither row is actually proposed as a change (would-change count went from 1,063 to 22, and these two are not among the 22). But the underlying resolver behavior (a town name apparently satisfying a county-table match) could misfire on a NON-override page with the same name collision and no human protecting it.
  - **Next action**: trace `app/utils/gov_registry/resolver.py`'s national-table rung for a raw name like "Ulster Town, NY" or "Lincoln, ME" and confirm whether it's genuinely falling through to a county match (and why a town-type name string reaches the county table at all), or whether this is an artifact specific to these two page's stored `jurisdiction` strings. Check for other town/county name pairs with the same shape before deciding this is systemic.
  - **Constraint**: don't touch either page — both are correctly protected `manual_override` rows and need no fix themselves; this is about the ladder's own county-matching behavior for a future unprotected page with the same name collision.
  - **History**: found by WO-215's dry run, 2026-09-11; see `BACKLOG_DONE.md`'s WO-215 entry.
  - **Update 2026-10-16**: Partly fixed in #2077 (`5e0e0ddd`): "Ulster Town" keys to the town; bare county-name towns are a policy call.
- **[HUMAN] Should an unverified per-video pin still beat the registry on a shared host?**
  - **Issue**: WO-221 made any matched per-video pin win. WO-1068 (#1466) later added a rule for the human-checked case: a person-checked fallback pin beats a namesake national-table match. WO-1185's pin audit (#1799) flags pins that contradict each other. A new unverified sweep pin still wins without any check.
  - **Next action**: Ryan picks one of two options. (a) Only pins with a "verified" strength beat the registry. (b) Cross-check the pin against the video's title or channel at resolve time. Separately, check whether the 4 WO-242 pages that were waiting on an owner mint (Bland County VA, Tangent OR, Canadice NY, Spencer County IN) were fixed by the 2026-10-06 owner-audit mints (#1804, #1826).
  - **History**: `BACKLOG_DONE.md` WO-221, WO-231, WO-242; #1466, #1799.

- **[NEEDS-AUDIT] Three governments' `jurisdiction_coverage.csv` rows still say `no-video-found` even though the Archive already has real, transcribed pages for them.**
  - **Issue**: WO-185 (2026-09-10, meeting/agenda URL backfill) found a real government-meeting video on the homepages of Apple Valley UT (`us:place:4901905`), South Weber UT (`us:place:4971180`) and Woodland Hills UT (`us:place:4985050`) while filling blank URL cells for rows tagged `no-video-found`. `research/coverage_registry/coverage_registry.csv` shows all three already have real Archive coverage — 9, 15 and 21 pages respectively, tier 1 — that the research file never learned about, the same "identity join" gap `docs/COVERAGE_HANDOVER.md` §3 describes for other cases.
  - **Impact**: at least these 3 governments read as uncovered on the coverage registry funnel and dashboard when they are not; likely more exist across the file (this WO only found these 3 as a side effect of a fresh homepage fetch on rows with no provenance URL — it didn't go looking for this pattern on purpose).
  - **Next action**: run the identity-join check `docs/COVERAGE_HANDOVER.md` §3/§5.2 describes (research file says not-covered, Archive inventory says otherwise) across the whole `no-video-found`/`meeting-without-video` population, not just these 3, and reclassify every stale row's `reject_reason` (most likely to `already-covered`) in one pass under the §158 write protocol.
  - **Constraint**: don't reclassify by hand one government at a time — this is exactly the kind of whole-file sweep the identity-join pattern already has a repeatable shape for; do it as one bulk apply so it doesn't quietly recreate the same drift the next time a batch of governments gets covered without a corresponding research-file update.
  - **History**: `BACKLOG_DONE.md`, WO-185, 2026-09-10; `rtr-business/research/ENUMERATION_METHODS.md` §234.

- **[NEEDS-AUDIT] `[EASY]` SLC, LIMS and PrimeGov fail the whole resolve when their YouTube video is gone, and no test covers it.**
  - **Issue**: since WO-167, `resolve_video_id()` raises `YouTubeUnavailableError` for a gone, private or terminated video. `slc.py:78`, `lims.py:88` and `primegov.py:393` do not catch it, so their own title, date and agenda are lost too.
  - **Next action**: keep failing outright (no new dead-embed pages; that matches current policy), and add one fixture-backed test per adapter that pins this behavior. Revisit only if a real page needs the degraded version.
  - **Constraint**: do not change `resolve_video_id()` itself.
  - **History**: `BACKLOG_DONE.md` WO-167.
  - **Update 2026-10-16**: Tests added in #2077 (`4bf35e72`): Tests pin current behavior; the code fix is still open.

- **[NEEDS-AUDIT] `[EASY]` yt-dlp's "This live event has ended." message isn't classified by `classify_unavailability()` — falls through to the generic "YouTube is blocking us" degrade, which is wrong.**
  - **Issue**: found live 2026-09-10 (WO-167) in `scripts/tier3_auto_transcription_queue_probe.csv` — two real ids (`my1pQX-Vhik`, `RzLW9WPBfAQ`) raised exactly `This live event has ended.` from yt-dlp's metadata-only extract. `app/platforms/youtube.py`'s `classify_unavailability()` only recognizes "will begin in" (not yet started), "removed"/"unavailable"/HTTP 404-410 (gone), "private", and "terminated" — this message matches none of them, so `resolve_video_id()` currently reports it as "YouTube is currently blocking automated caption requests from our server," which is inaccurate (nothing is blocked; the stream simply ended and yt-dlp hasn't/can't surface a VOD for it yet, or the VOD is delayed).
  - **Impact**: a meeting in this state gets a misleading video/transcript warning; unclear from this round's data whether the underlying video ever becomes resolvable again (i.e. whether this is temporary like "not yet started" or permanent like "gone") — needs a re-check against one of the two real ids above after some time has passed before deciding which bucket it belongs in.
  - **Next action**: re-probe `my1pQX-Vhik`/`RzLW9WPBfAQ` after a delay to see whether the message changes (VOD becomes available) or persists (effectively gone); then add a `_ENDED_SIGNATURES` bucket to `classify_unavailability()` with the correct temporary/permanent classification, following WO-167's pattern in `app/platforms/youtube.py`.
  - **Constraint**: don't guess the classification without the re-check above — CLAUDE.md's "don't claim a data path works without a positive example" applies directly here.
  - **History**: `BACKLOG_DONE.md`, WO-167, 2026-09-10 (found while sourcing real message-shape samples for that work order; not in its scope to fix).

- **[NEEDS-AUDIT] Two tests failed only in full local runs on Ryan's Mac, never in CI or a cloud container; the one Mac-only difference found is that collecting the suite there imports rtr-discovery.**
  - **Issue**: `test_schema_info_ignores_tables_this_service_does_not_own` and `test_detail_read_is_one_snapshot_during_concurrent_save` failed in some full local runs on the Mac and passed alone. In a cloud container neither failed once: 4 full runs (1 in normal order, 3 with the test files shuffled) and 55 repeats of the second test's file, 30 of them with every CPU busy. When pytest collects `tests/test_wo932_wo145_raw_identity.py`, it imports `scripts/wo145_api_first_sweep.py`, which puts `~/Documents/rtr-discovery` first on Python's import path for the rest of the run and imports that repo's `discovery` package. That only happens where the sibling checkout exists (the Mac), and it happens before any test runs. Its effect on these two tests is not confirmed: this session was not given access to rtr-discovery.
  - **Impact**: none today. WO-1082 changed both tests so they no longer depend on the shared test database or on a fixed wait. But an import that changes the import path for the whole run can still affect other tests on the Mac.
  - **Next action**: on the Mac, run the full suite with `-p no:cacheprovider` and compare `sys.path`, `os.environ['DATABASE_URL']` and `sys.modules['app.db.engine'].engine.url` before and after collection. If rtr-discovery changes any of them, make those test modules import the script inside a fixture that restores `sys.path` afterwards.
  - **History**: `BACKLOG_DONE.md`, WO-1082 (2026-09-26); first seen 2026-09-10 (WO-166).
  - **Update 2026-10-16**: Partly fixed in #2077 (`393f7a80`): conftest drops outside-repo import paths; not checked on the Mac.

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
  - **Update 2026-10-16**: Partly fixed in #2077 (`63f93c79`): CT bare Groton/Litchfield/Newtown/Stonington key to the town; 19 VT pairs left.

- **[NEEDS-AUDIT] eScribe archives one meeting once per `Agenda=` value (Agenda, Merged, PostMinutes...), creating duplicate pages.**
  - **Issue**: `escribe.py` sets no `external_id`, so the Archive dedupes on the full URL, and `?Agenda=Merged&Id=X` and `?Agenda=Agenda&Id=X` count as different meetings. As of 2026-09-03 there were 7 known pairs on 6 hosts (forterie, oshawa, abbotsford, peelregion, townshipofbrock, marvinnc, sandag).
  - **Impact**: duplicate pages, double transcription cost, and inflated counts.
  - **Next action**: set `external_id=f"escribe:{host}:{Id}"` in `escribe.py` (the same pattern as cablecast.py:659), with a test. Then do a production merge pass for the existing pairs, keeping the copy with the fuller transcript.
  - **Constraint**: do not assume `Agenda=Agenda` is the canonical copy.
  - **History**: found 2026-09-04 (Abbotsford).
  - **Update 2026-10-16**: Partly fixed in #2077 (`ea1a5afa`): eScribe Agenda= views now share one page via external_id; 7 existing pairs and older pages still need a merge pass.

- **[HUMAN] Re-run the wrong-content screen after the wrong-page sheet is applied.**
  - **Issue**: the 2026-09-21 re-screen flagged 639 of 10,280 pages: 540 have no meeting word in the title, 90 hit the school-body rule, and 9 are talk-show or school-title cases.
  - **Next action**: (1) apply `reports/wrong_page_worklist.csv` (line 2452). (2) Re-run the screen. (3) Do not hand-read the 540 no-meeting-word pages; they belong to the A, B and C video-kind rules. (4) Check the 14 unexplained school-body pages (list in `BACKLOG_DONE.md` WO-934).
  - **Constraint**: the screen is a lead, not a verdict. Never delete on it alone.
  - **History**: `rtr-business/research/archive_audit/AUDIT_REPORT.md`; `BACKLOG_DONE.md` WO-934.

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

- **[NEEDS-AUDIT] Two known duplicate-page pairs for one meeting (Yamhill County OR via AgendaCenter and YouTube; Tompkins County NY via Granicus and Legistar), cause not found.**
  - **Issue**: the Archive already matches on `platform`+`external_id` before the URL (`_find_existing_page`), and YouTube pages carry `youtube:{id}` (since 2026-08-07). So "dedupe keys on URL only" is not the cause. Most likely the two submissions produced different `platform` or `external_id` values (for example, a delegated page keeping its delegating platform). Unverified.
  - **Next action**: read both pairs' `platform`/`external_id` in the export to find which field differed, then fix that adapter. Merge each pair, keeping the copy with more segments (1,726 vs 757 for Yamhill).
  - **History**: found 2026-09-01 (Yamhill) and 2026-09-06 (Tompkins).

- **[IMPROVEMENT-ROUND] `[BIG]` Zoom cloud recordings (`zoom.us/rec/share/...`) and Microsoft Teams have no adapter.**
  - **Issue**: some governments publish past meetings only as Zoom cloud-recording share links (Rockport MA's `rockportma.gov/598/Recorded-Zoom-Meetings`, Brookline MA's zoomgov links on CivicClerk, 4 `zoom.us` values in Utah PMN notices). No Teams past-recording example has been found; every Teams hit so far is a live join link.
  - **Impact**: governments whose only platform is Zoom are invisible to every discovery path.
  - **Next action**: **Claimed 2026-10-16** (office Mac session, A7): a 5-link pilot. Size it first. Search for `"zoom.us/rec/share"` together with governance phrases. If density is real, build a Zoom `rec/share` adapter from a live Rockport sample. Teams needs its own investigation.
  - **Constraint**: confirm a share link plays without sign-in before building.
  - **History**: found 2026-09-01/02; Utah PMN pilot 2026-09-08.

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

### Pages filed under a wrong government by a since-removed pin can't be cleared back to "unknown" `[NEEDS-AUDIT]`

- **Issue**: WO-1060 removed the `@ulctTube` channel pin (Utah League of Cities and Towns, an association) and the Kalamazoo TelVue whole-station pin. The resolver now answers "unknown" for their pages, but `backfill_gov_id.py` never downgrades a real `gov_id` to `rtr:unknown:` on a shared host (WO-215's guard, added after a run nearly blanked 825 YouTube pages), and `/internal/jurisdiction/override` accepts only a real government.
- **Impact**: 7 pages keep a wrong government: 5 ULCT board meetings and a ULCT training video under Utah County, and a Kalamazoo community-arts video under Kalamazoo city (pages 6577, 6935-6938, 8772, 3356).
- **Next action**: add an explicit, per-page way to clear a page's government (e.g. `/internal/jurisdiction/override?clear=true&ids=...`, dry run by default), then clear these 7.
- **Constraint**: keep WO-215's bulk guard; only a named, per-page clear.
- **History**: `BACKLOG_DONE.md` WO-1060 (#1448) and WO-1061.

### `backfill_gov_id.py --apply` writes hub redirects to a file the live site never reads, and the next deploy erases it `[NEEDS-AUDIT]`

- **Issue**: on `--apply`, the script writes retired-hub redirects into `archive/data/hub_slug_aliases.csv` on the Render instance it runs on. Checked 2026-09-25 after the WO-1057 backfill: the 23 rows it wrote were not served (`/j/hooper`, `/j/yarmouth-ma` both 404), and a redeploy replaces the file with the repo's copy. The rows only reach users if someone copies them into a PR by hand (WO-204b, WO-1060).
- **Impact**: every backfill run leaves its retired hubs 404ing until a follow-up PR lands. The tidy-up step also leaves a stale reverse row behind: the 2026-09-11 `baltimore-md` -> `baltimore-city-md` row and today's `baltimore-city-md` -> `baltimore-md` row formed a loop (caught by `test_committed_file_has_no_alias_resolving_to_another_alias`).
- **Next action**: have `--apply` print the rows it wrote as CSV (or write them to `--report`'s folder) so they can be committed directly, and make `write_retirements()` drop a row whose old slug is now a live hub.
- **Constraint**: don't let the script redirect one government's hub to a different government: WO-1060 found 9 such rows (Yarmouth MA -> ME, Armada Township -> village, ...). Only same-government renames should get a redirect.
- **History**: `BACKLOG_DONE.md` WO-1060.
- **Update 2026-10-16**: Partly fixed in #2077 (`5b8da07e`): backfill_gov_id --apply prints/writes hub alias changes and avoids loops; same-government check still open.

### WO-171 LocalView channel pins: at least two named a neighbouring government, so the rest need a check `[NEEDS-AUDIT]`

- **Issue**: WO-1060 found two WO-171 "own-channel verdict" pins wrong: `@cityofrichmondheightsohio6020` pointed at Richmond village, OH instead of Richmond Heights city, and `@doversherborncabletv` (a Dover-Sherborn shared cable channel) at Dover alone. Two more wrong pins came from other runs (wo221 Cape Vincent town -> village; wo346 Armada Township -> village).
- **Impact**: each wrong channel pin files every video on that channel under the wrong government. The pattern (a place name matched to a similarly named neighbour) is exactly what a name-based join produces.
- **Next action**: for each `wo171_localview` channel pin, compare the pinned government's name with its own evidence text and the titles of its archived pages (via `GET /internal/export/pages`); list mismatches for Ryan.
- **Constraint**: read the export over HTTP; never query production directly.
- **History**: `BACKLOG_DONE.md` WO-1060.

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

### Adapter, tenant & jurisdiction-extraction odds and ends `[LATER]`

Everything adapter-, tenant-, or jurisdiction-extraction-shaped, kept
together on purpose. Tags are inline here rather than hoisted into the
actionability sections above.

### `[JUST-DO-IT]` Anchorage and Santa Cruz OnBase/Hyland pages resolve with no video: add their YouTube channel fallbacks

- **Issue**: `hyland.py` already calls `youtube_channel.find_channel_match()` (hyland.py:316), but `_CHANNEL_FALLBACKS` holds only Tucson (youtube_channel.py:213). `meetings.muni.org` (Anchorage, `@moameetings`) and `ecm.cityofsantacruz.com` (Santa Cruz, `youtube.com/ctvsantacruz`) have no entry.
- **Impact**: about 10 OnBase/Hyland pages still show no video. Most will gain a video, not a transcript.
- **Next action**: add `ChannelFallback` entries for the two netlocs (channel ids checked live), with a date-match test like Tucson's.
- **History**: `BACKLOG_DONE.md` OnBase/Hyland entries; Tucson fallback 2026-08-31.

### Jurisdiction extraction & backfill

- **`[HUMAN]` Page 8878 (Town of Franklin, MA's Community Preservation Committee 3/30/21) is filed under Franklin County, MA.**
  - **Issue**: the video sits under `us:county:25011`. The Town is `us:place:2525172` and its channel `@townoffranklinma104` is pinned (tenant_overrides.csv:5354). A per-video pin `GGErk0S1ZOg` -> `us:county:25011` (tenant_overrides.csv:1850) may be this same video and would keep re-filing it under the county.
  - **Impact**: one live page shows the Town's meeting on the county's hub.
  - **Next action**: check whether `GGErk0S1ZOg` is page 8878's video. If it is, re-point that pin row to `us:place:2525172`. Then `POST /internal/jurisdiction/override?ids=8878&gov_id=us:place:2525172` (dry run first).
  - **History**: WO-235, WO-247 (`BACKLOG_DONE.md`).

- **`[JUST-DO-IT]` `[EASY]` Census LSAD "corporation" is not stripped: "Ranson, WV" mints a duplicate and the hub reads "Ranson corporation, WV".**
  - **Issue**: `us_places.csv` lists "Ranson corporation" (`us:place:5466988`). `resolve_government("Ranson, WV")` mints `rtr:us:wv:ranson`, which now has its own governments.csv row (line 1167), and `display._TRAILING_TYPE_RE` lacks `corporation`.
  - **Impact**: Ranson's pages sit at `/j/ranson-corporation-wv`. Meeting Finder's resolver named the minted duplicate (WO-1163).
  - **Next action**: add `corporation` to the lookup-side trailing-type strip and to `display._TRAILING_TYPE_RE`. Add the Ranson pair to the Sitka test, add a `ranson-corporation-wv` -> `ranson-wv` alias, and retire the minted `rtr:us:wv:ranson` row.
  - **History**: WO-125, 2026-09-09; WO-1163 pin.
  - **Update 2026-10-16**: Partly fixed in #2077 (`cc30ce13`): "corporation" suffix stripped; Ranson hub alias and minted row still need a call.

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

- **`[NEEDS-AUDIT]` A Swagit video opened through another government's
  Swagit host is filed under the host's government, not its own.**
  - **Issue**: Swagit's `/videos/<id>` numbers are shared across every
    customer, so any customer's host serves any customer's video.
    Confirmed live 2026-09-23: `dublinca.new.swagit.com/videos/401655`
    is titled "Sep 21, 2026 City Council Meeting - Carmel, IN", and its
    stream path reads `swagitVideo/carmelin/`. The reverse also works:
    `sccoe.new.swagit.com/videos/401121` serves a Dublin, CA meeting.
    `finalize_jurisdiction()`'s subdomain cross-check then prefers the
    host over the page title. `resolve_government("Carmel, IN",
    tenant_host="dublinca.new.swagit.com")` returns Dublin
    (`us:place:0620018`, evidence "us_places.csv Dublin city").
  - **Impact**: none found yet. All 6 pages on `/j/dublin-ca` are real
    Dublin meetings (checked 2026-09-23; each Swagit one streams from
    `swagitVideo/dublinca/`). A cross-host URL only arises if someone
    pastes or discovers one, because each customer's own listing
    (`/views/<n>`, e.g. Dublin's `/views/876`) lists only its own
    videos. When it does arise, the page is filed under the wrong
    government with no warning.
  - **Next action**: in `app/platforms/swagit.py`, read the
    `swagitVideo/<slug>/` segment of the stream URL. When it differs
    from the host's subdomain, pick one fix: pass the owning host
    (`<slug>.new.swagit.com`) as `origin_host` for identity, or rewrite
    `source_url` to the owning host before ingest. Then audit every
    Archive page on a `*.new.swagit.com` host for the same mismatch.
  - **Constraint**: do not remove the `dublinca.new.swagit.com` pin in
    `tenant_overrides.csv`. It is correct: that host's own archive is
    Dublin's. A pin (or subdomain) is right for a host's own videos and
    wrong only for a borrowed one.
  - **History**: found during WO-1032's live check of the fetch pacing
    hook (2026-09-23). That session also reported a "Carmel City
    Council" heading and a link to video 401655 on Dublin's Swagit
    homepage. Not reproduced the same day: the homepage redirects to
    `/recycle-bin/`, a leftover admin template ("SwagitAdmin", "NCTCOG
    Live" placeholder links) that listed no videos at all.

- **`[NEEDS-AUDIT]` `[EASY]` Lloydminster, AB/SK: the hub is on neither province page, and two stray ids remain.**
  - **Issue**: Ryan decided (2026-09-10) on one government, `rtr:ca:ab-sk:lloydminster`, displayed "Lloydminster, AB/SK" (governments.csv:554). `state_abbr_from_jurisdiction()` reads no province from "AB/SK". A minted `rtr:us:ab/sk:lloydminster-ab-sk` row (country `us`, governments.csv:779) also exists, and `resolve_government("Lloydminster, AB")` still mints `rtr:ca:ab:lloydminster` despite the alias.
  - **Impact**: the hub doesn't appear on /state/alberta or /state/saskatchewan, and new pages can split off onto a minted id.
  - **Next action**: list the hub on both province pages, delete the stray `us` row, and make "Lloydminster, AB"/"SK" key to the curated id (with a test).
  - **History**: WO-69, WO-89 (`BACKLOG_DONE.md`).

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

- **[NEEDS-AUDIT] A TikiLive title can still be a file name.**
  - **Issue**: WO-1174 strips the leading "NNN - " upload counter from a TikiLive title. Some titles are still file names ("BudgetHearing_11292022"). `looks_like_file_name()` is not applied, because no second title exists to prefer. Ryan chose counter stripping only (2026-09-30). The government's own title needs its `VID=` page, and `VID=` is a separate id that the embed cannot name.
  - **Impact**: a bare embed's page can carry a file-name title. Better than none, worse than the government's title.
  - **Next action**: decide whether a file-name title should be dropped rather than kept. Do not guess: measure it on the walk's `/video/{id}` pages first.
  - **Constraint**: keep TikiLive requests low while a CivicMedia number walk is running on the same host.
  - **History**: `BACKLOG_DONE.md` WO-1165, WO-1172 and WO-1174; `app/platforms/civicmedia.py` "Which title".

- **[EASY] `jurisdiction_coverage.csv`'s `suspected_meeting_link_provider`/`suspected_video_provider` columns sometimes store a raw domain-shaped value instead of the normalized platform key.**
  - **Issue**: found while building WO-267's candidate sampler: 67 rows
    across the file (as of 2026-09-12) carry `civicplus.com` (21),
    `civicclerk.com` (9), `youtu.be` (9), `vimeo.com` (8),
    `granicus.com` (8), `youtube.com/embed` (6), `legistar.com` (3),
    `champds.com` (2) instead of the short key (`civicplus`,
    `civicclerk`, `youtube`, `vimeo`, `granicus`, `legistar`, `champds`)
    every other row in that column uses.
  - **Impact**: any `Counter`/`groupby` over these columns silently
    splits one platform's population across two label spellings --
    cost WO-267 a few minutes to notice; a future sweep filtering on
    `suspected_video_provider == "civicplus"` would quietly miss 21 real
    rows without ever erroring.
  - **Next action**: a one-time normalization pass mapping each
    domain-shaped value to its short key, through the §158 write
    protocol (lock, re-read, row-count floor, atomic rename, `git diff
    --stat` shows only the touched rows).
  - **Constraint**: don't touch any other column on a row while fixing
    this -- it's a pure relabeling, not a re-test.
  - **History**: found by WO-267, 2026-09-12 (not fixed in that WO --
    out of its measurement-only scope).
- **[JUST-DO-IT] `[EASY]` The shared meeting-title filter still passes recap clips, information sessions, recruitment PSAs and other non-meetings.**
  - **Issue**: `PROMO_BLOCKLIST` (`app/utils/video_hand_check.py:336`) now has "state of the city" and "interview", but hand reviews (WO-235, WO-247) confirmed more misses that contain a body word: "Recap"/"Resumen" clips (Pullman WA, Worthington MN), "Information Session" (North Battleford SK), "is seeking new members"/"Join the ... Commission" (Lone Tree CO), "Personal Meeting Room" (Knox County IL), "training ... session" (West Haven CT), produced shows ("Mayor's Minute", "Special Episode").
  - **Impact**: every sweep and Meeting Finder run that uses this gate can queue these as meetings; so far only hand reads catch them.
  - **Next action**: add those phrases; widen "training video" to "training session"; consider a duration floor (under about 2 minutes with a body word: the known examples are 34-141 s). Add each real title as a test case.
  - **Constraint**: add only phrases confirmed by a real example ("town hall" stays out).
  - **History**: WO-235 (2026-09-11), WO-247 (2026-09-12), `BACKLOG_DONE.md`.
  - **Update 2026-10-16**: Partly fixed in #2077 (`c8078f78`): Recap/info session/training/podcast titles blocked; duration floor and two ambiguous phrases still open.

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

- **[NEEDS-AUDIT] SuiteOne: a bare tenant management root (`{tenant}.suiteonemedia.com/`) has no event-listing lookup.**
  - **Issue**: `SuiteOneAssetFinder.resolve()` needs an `event`/`id` in the URL (`_extract_ids()`); a bare root raises `ResolveError` (comment at `app/platforms/suiteone.py:227`). Confirmed on Luna County NM, Rush County IN, Lincoln County NM.
  - **Impact**: governments whose only SuiteOne lead is the root page come back as errors, not meetings.
  - **Next action**: look for a listing endpoint on a live tenant (`lunaconm.suiteonemedia.com`); if one exists, list events and reuse `resolve_newest_candidate()` (`app/platforms/base.py`, built for eScribe in WO-938).
  - **Constraint**: confirm on a real tenant before building.
  - **History**: WO-149, WO-285 (fixed the `/web/live` stub), WO-938 (typed error), all in `BACKLOG_DONE.md`.

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

- **[NEEDS-AUDIT] Pages with no jurisdiction ship an Event JSON-LD with no `location`, which Search Console flags.**
  - **Issue**: `archive/templates/meeting_page.html:240` emits `location` only `{% if page.jurisdiction %}`. On 2026-08-31, 245 pages had no jurisdiction (mostly Cablecast, TelVue, Swagit); Search Console flagged "Events: Missing field 'location'" on 2026-09-15. The counts are older than gov_id-driven display (WO-114) and the many pins since then.
  - **Impact**: Google flags these pages' Event rich results as invalid.
  - **Next action**: re-run `GET /internal/jurisdiction/missing` for a current count by platform; then either fix the remaining pages per platform or drop the Event block when there is no location. Consider merging with the "Missing field" entry in Trust, safety & data quality.
  - **Constraint**: use `/internal/jurisdiction/missing`, not `/internal/low-trust-pages`.
  - **History**: WO-38 (2026-08-21), `BACKLOG_DONE.md`.

- **ChampDS's VOD2 stream (majority of customers) can be transcribed but still can't play on our pages.**
  - **Issue**: VOD2's HLS stream (`securestream10.champds.com`) answers
    only requests carrying `Referer: https://play.champds.com/`; with
    no referer or ours, every request gets HTTP 406. Our server can send
    that header, so since WO-1045 (2026-09-24) the adapter returns the
    stream as `server_media_url` and every transcription path uses it.
    A reader's browser cannot send it, so the page still has no player.
    `MediaInfo.MediaPath` (`.mp4`) is not a way round it: 404 on every
    host tried.
  - **Impact**: VOD2-only meetings (39 of 48 fresh tenants in the
    2026-09-06 CDX scan; Cobb and Gwinnett County GA, 2026-09-24) now
    get a transcript but show "ChampDS only streams it inside its own
    player" instead of a player, so transcript timestamps can't seek.
  - **Next action**: **Claimed 2026-10-16** (office Mac session, A9):
    embed test. From the office Mac, check whether a `play.champds.com`
    event page allows framing on our page and accepts a start time. A
    frame would send ChampDS's own Referer.
  - **Constraint**: no streaming proxy (Ryan, 2026-10-16; see Standing
    decisions). The cloud gets HTTP 403 from ChampDS, so the test runs
    from the office Mac.
  - **History**: `BACKLOG_DONE.md` (video-indexing investigation; WO-1045
    for the live re-check and the transcription path).

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

- **[NEEDS-AUDIT] `[WAIT]` open.media broke on 2026-09-26 (empty JavaScript shell on every tenant); re-check is overdue.**
  - **Issue**: every open.media page returned a 501-byte shell whose `/api/settings/` call 404s; the `og:video`/`om_youtube` data `openmedia.py` reads is gone. `openmedia.py` is unchanged since.
  - **Impact**: no open.media meeting resolves; the canary's `open_media` sample fails.
  - **Next action**: open `https://eugene.open.media/sessions/344982/city-council-work-session-july-15-2026` now. If a new structure is live, rebuild against its `/api/sessions/{id}/` and `/cue-points/` calls; if still broken, add `open_media` to `CANARY_KNOWN_CI_BLOCKS` with the date.
  - **Constraint**: do not build against the broken shell.
  - **History**: WO-1112 (2026-09-26), `BACKLOG_DONE.md`.

- **[NEEDS-AUDIT] TelVue's `resolve()` can return a perpetual live-channel stream (no fixed start/end) indistinguishable from a specific completed meeting recording.**
  - **Issue**: found live, WO-338, 2026-09-13. Two governments' confirmed TelVue hub pages (Oshtemo Charter Township, MI's own "Watch Live & Recorded Meetings" page; Cranford, NJ's Calendar EID page) both resolved via `verify_hub()` to a titled "LIVE" stream (`PMN Three - LIVE`, `Cranford TV-35 Live Stream`) rather than one specific past meeting — `resolve()` returned a real `video_url` (an `.m3u8` playlist) with no signal distinguishing "this is a 24/7 public-access channel" from "this is one saved meeting."
  - **Impact**: a live channel has no fixed duration, so it can't be safely queued to the tier-3 auto-transcription pipeline (which expects a bounded recording) — both were hand-rejected this WO rather than queued, but an unaudited sweep could queue an indefinite live stream by mistake.
  - **Next action**: check whether TelVue's API surfaces a `live`/`scheduled` flag or a null/absent duration for a channel stream vs. a VOD item, and have `telvue.py`'s `resolve()` refuse (or flag) a video_url with no derivable duration rather than returning it as if it were a normal meeting video.
  - **Constraint**: don't reject every TelVue live URL outright — a `probe_tier3_queue.py` duration probe might already catch some of these naturally (no duration = reject); confirm what the probe actually does with an indefinite `.m3u8` before assuming this needs an adapter-level fix rather than a probe-level one.
  - **History**: `BACKLOG_DONE.md`'s WO-338 entry.

- **[NEEDS-AUDIT] `civicclerk.py`'s `resolve()` can return a Zoom join link as `video_url`, a second confirmed occurrence of the same content shape.**
  - **Issue**: WO-325 (2026-09-12) first found this on Jo Daviess County, IL — a CivicClerk event whose `video_url` field is a live-meeting Zoom join link (`us06web.zoom.us/j/...`), not a saved recording. WO-338 (2026-09-13) hit the exact same government and event field shape again (a DIFFERENT event id, `event/7503`) via `verify_hub()`'s listing walk. Both times a hand-check caught it before anything was queued.
  - **Impact**: low severity (always caught by the hand-check gate so far) but a repeat, predictable false-tier-3 candidate on at least one real CivicClerk tenant, and any government whose CivicClerk instance is configured to post the Zoom join link in the same field would hit it too.
  - **Next action**: have `civicclerk.py`'s `resolve()` recognize a `zoom.us`/`meet.google.com`/`teams.microsoft.com` (or similar live-meeting-join) domain in the raw `video_url` field it reads from CivicClerk's API and treat it as "no video" (a live-meeting link, not a recording) rather than passing it through as a real `video_url`.
  - **Constraint**: match by domain, not by guessing at a URL shape — a real recording URL hosted on a video vendor should never collide with this check.
  - **History**: `BACKLOG_DONE.md`'s WO-325 and WO-338 entries.

- **[NEEDS-AUDIT] A real tier 1/3 "video found" verdict off `verify_hub()`'s bare-homepage fallback: three checks are still not built.**
  - **Issue**: WO-933 built the address, looping-video, meeting-context and test-title checks. `verify_hub()` now records a homepage video it cannot verify as `resolved_unverified_video` (tier empty). Not built: (1) `_civicclerk_walker()` carries only title, date and url, so an event with no `agendaId`/`agendaName` is not caught; (2) a dead `externalVideoUrl` (Winter Garden city FL, a 404) is caught only later by the queue probe; (3) the same video address on unrelated domains (Coatesville IN and Genoa WI, one shared stock video) is not checked.
  - **Impact**: a CivicClerk test event is caught only when its title is just "test" and a number ("TEST 3", Forest Park city GA). A test event with a real-looking title still passes.
  - **Next action**: make the walker carry `agendaId`/`agendaName` and treat both empty as `cannot_tell`; HEAD-check `externalVideoUrl` before crediting it; add a per-run check for one video address seen on several unrelated governments.
  - **Constraint**: one real test-event example only, so do not widen the title rule (`^TEST\b` also rejects "Test City Council Meeting", which a fixture caught). Test against real CivicClerk events with and without agendas.
  - **History**: `BACKLOG_DONE.md` WO-933, WO-348, WO-355.

- **[NEEDS-AUDIT] A pasted custom (non-vendor) hub page with many meetings takes the first YouTube id on the page, not the newest row with video.**
  - **Issue**: `generic_fallback.py`'s `_find_youtube_video_id()` returns the first YouTube id in the raw HTML. Quincy MA's agenda table resolved correctly only because its rows are newest-first. Meeting Finder's Scan phase already reads table rows and their dates (`app/platforms/meeting_finder/scan.py`), but the live paste path does not use it.
  - **Impact**: a hub page with a different row order, or a sidebar video earlier in the page, would attach the wrong meeting's video with no error.
  - **Next action**: when a pasted page looks like a dated multi-row listing, reuse Meeting Finder's row/date scan to pick the newest row that has video before the first-match fallback; test on Quincy plus one more real hub page.
  - **Constraint**: leave single-meeting-page behavior unchanged; this runs first only on multi-row pages.
  - **History**: Quincy MA finding, 2026-09-18.

### Very long Cablecast meetings whose audio is split into many files still stop transcribing partway `[NEEDS-AUDIT]`

- **Issue**: WO-1062 fixed Cablecast streams whose separate audio track is one file, but 3 of 10 tenants checked (Burlington/BCIT, Hudson OH, Yarmouth) split that track into hundreds of `.m4s` files. On the worker's ffmpeg (7.1.5), jumping into those streams also writes the 224-byte empty file (Burlington 2 h 30 min in, Yarmouth 3 h 53 min in, 2026-09-25), so they depend on the slow fallback, which runs past its 120 s limit deep into a long meeting.
- **Impact**: a long enough meeting on these tenants loses its ending, as job 4306 did before WO-1062. How long "long enough" is on these tenants has not been measured.
- **Next action**: test, on the worker's image, whether ffmpeg reads a chunk correctly from a trimmed copy of the audio playlist that starts at the segment containing the chunk's start (the `#EXT-X-MAP` line plus only the segments covering the window, with absolute URLs). That needs no seek at all, and would cover the one-file shape too.
- **Constraint**: first measure the fast jump's own cost: on these tenants the failing first attempt took 104-135 s, close to the 120 s limit by itself.
- **History**: `BACKLOG_DONE.md` WO-1062.

### State legislatures: residual per-chamber gaps after the WO-1012 push `[IMPROVEMENT-ROUND]`

- **Issue**: no remaining vendor unlocks more than ~6 chambers. Open: (1) a generic same-path `.vtt` sibling caption lookup in `direct_file.py` (Massachusetts); (2) Vimeo's dynamically fetched event id (Illinois, Georgia); (3) a modern Swagit URL for Louisiana Senate; (4) one more hop on the Idaho, Louisiana House, NJ, ND, Ohio, SD and Texas House hubs; (5) an Invintus depth sweep on the TVW tenant (CVTV now resolves via Invintus, #1940); (6) send the recorded YouTube/Vimeo channel leads (AL, GA, KY, MD, VT, MS, NH) to the drip.
- **Impact**: a handful of chambers each.
- **Next action**: do (1) first; it is the cheapest. Before building anything state-specific for (4), check the `generic_fallback.py` custom-hub entry (Quincy MA).
- **Constraint**: New York Senate's Cloudflare challenge stays blocked; never solve it.
- **History**: `BACKLOG_DONE.md` WO-1012 (2026-09-22).

### 97 of the 257 Diligent Community "no video" tenants link their own YouTube channel from the portal page — none is in the leads file yet `[JUST-DO-IT]`

- **Issue:** WO-914 (2026-09-20) re-read the `MeetingTypeList.aspx` page
  of all 257 `no_video` tenants and found 97 that carry a
  `youtube.com/@handle`, `/channel/` or `/user/` link on the page
  itself (footer or header social links, for example
  `fusd1` -> `@flagstaffunifiedschooldistrict`). The government put that
  link on its own meeting portal, so it is a strong channel identity
  with no YouTube fetch. None was recorded as a channel lead by WO-911
  or WO-914 (they only recorded video ids found inside meetings).
- **Impact:** up to 97 governments have a channel lead that costs one
  page read each. Some channels will be a school's general channel, not a
  meeting channel; the drip's hand-read decides.
- **Next action:** extract the channel URL per tenant from the saved
  page, tie each tenant to its `gov_id` through the portal's own website
  link (the method in `research/wo914_identity.csv`), dedupe against
  `research/youtube_channel_leads.csv`, and append `kind=channel` rows.
- **Constraint:** no YouTube fetch; a tenant with no registry row goes to
  needs-human, not a guessed id.
- **History:** `BACKLOG_DONE.md` WO-914 entry.

### Two Cablecast tenants list a real meeting with no video file: recheck, then call it a live-only case `[NEEDS-AUDIT]` `[WAIT]`

- **Issue:** on 2026-10-12 the Cablecast adapter resolved two listed meetings with no video address: Linden NJ's "BOE Meeting 09/17/2026" (`linden-nj.cablecast.tv/internetchannel/show/53`, Linden City School District, `us:sd:3408610`) and Governor Wentworth Regional School District NH's "GWRSD 3-9-2026" (`wolfeboro.cablecast.tv/internetchannel/show/16`, `us:sd:3303330`). Both tenants also serve a live stream, so these may be live-only.
- **Impact:** two governments with no Archive page and nothing queued. If the replay never appears, they are the first confirmed live-only Cablecast cases, and live capture is the only way to get their video.
- **Next action:** re-resolve both shows in about a week. If a video address appears, route it under §398i. If it still has none, record `meeting-without-video` for each (source, date, "listed, no replay file"). Only then ask whether live capture is worth it.
- **Constraint:** a newly posted show can get its video file late; one empty resolve is not proof. Do not build a recorder for two tenants.
- **History:** none yet; `BACKLOG_DONE.md` will get this session's finding when the entry closes.

### 13 Cablecast tenants with no Archive page show no meetings on the home list: read their full past-shows lists `[NEEDS-AUDIT]`

- **Issue:** of 17 Cablecast tenants with zero Archive pages and nothing queued (2026-10-12), 13 showed no meeting on their `/internetchannel/` home list: University Park IL, Anne Arundel County MD, Mount Lebanon schools PA (empty list), Southern Regional schools NJ, Warren MA (empty list), marintv, metvweb, mycommunityfocus, jpschools, pcc, trojanvision, wilson-co-schools and kdol. Most look like school, college or community-TV channels. Six of my search-page checks came back empty or were cut off, so this is a first pass, not a verdict.
- **Impact:** unknown. A longer past-shows list could hold board or council meetings. A tenant with truly none is an honest negative to record, not a gap.
- **Next action:** read each tenant's full past-shows list (the home page shows only the latest 10 to 20 items), keep any real public meeting, and route it under §398i with a `gov_id`. Record a no-video outcome (`no-meeting-nor-video`, source, date) for each tenant with none. The 9 unmatched tenants (no `gov_id` in `tenant_overrides.csv`) first need an owner via Step 0 in `ENUMERATION_METHODS.md`.
- **Constraint:** the dashboard file used for the zero count was dated 2026-10-12 07:08. Canandaigua city NY already had a page (2026-09-23) that it missed, so recheck coverage live (`/api/jurisdictions`) before queueing anything.
- **History:** none yet.

### [JUST-DO-IT] `[EXAMPLE]` Winona County, MN's own homepage links an AgendaCenter and a YouTube page, neither checked for a real current meeting yet

- **Issue**: WO-238 (2026-09-11) promoted `co.winona.mn.us` into the county's `domain` field (it was a wrong-government mapping before, `pub-winona.escribemeetings.com`, which is really Winona city's). While verifying the real domain live, its homepage was found to link `/AgendaCenter` and `/youtube` — a real, unswept lead for the county's own meeting coverage.
- **Impact**: Winona County, MN has no meeting/video coverage recorded at all today (`reject_reason` blank after WO-238's fix) despite having a plausible real path to one.
- **Next action**: hand-check `co.winona.mn.us/AgendaCenter` for a real, current meeting, and check whether `/youtube` is a real channel with meeting recordings (per `CLAUDE.md`'s hand-check rule — confirm it's the county's own channel, not a wrong body reached through it).
- **Constraint**: none known — this is a fresh, unswept lead, not yet even fetched past the homepage.
- **History**: `BACKLOG_DONE.md`'s WO-238 entry, 2026-09-11.

### Five platform URL-shape findings from rtr-upcoming, not yet verified here `[EXAMPLE]`

- **Issue:** rtr-upcoming reported these from real pages on 2026-09-23. None is recorded or handled in rtr-deeplink yet:
  1. **Municode Meetings has a monthly calendar** at `/calendar/YYYY-MM`, listing meetings even before an agenda exists, with machine-readable dates (e.g. `content="2026-10-06T19:00:00-07:00"`). The homepage table `municode_meetings.py` reads shows only the latest 25.
  2. **Cancelling a Municode meeting changes its address:** "CANCELLED" is added to the title and the slug is rebuilt from it (`.../development-review-committee-cancelled-78`), so a stored URL can stop matching.
  3. **Laserfiche Cloud can sit behind a city's own address:** `publicrecords.cityofsanrafael.org` redirects to `portal.laserfiche.com/Portal/Welcome.aspx?repo=r-40198117`. A host check before following redirects misses it.
  4. **Laserfiche Cloud folders are readable without a browser or login:** `FolderListingService.aspx/GetFolderListing2` returns a folder's contents as JSON; the top folder's id is the Browse page's `"rootFolder"` value.
  5. **CivicLive can run on a city's own domain** (`piedmont.ca.gov`), which the `.hosted.civiclive.com` host check can't see. The page shows it: a "Powered by CivicLive" footer, and documents under `/UserFiles/Servers/Server_<n>/` on `{tenant}.hosted.civiclive.com`. `platform_signatures.csv` has no CivicLive signature.
- **Impact:** Municode listing depth (1); stale Municode URLs (2); missed platform identification on custom domains (3, 5); a cheap way to list Laserfiche Cloud if it's ever built (4).
- **Next action:** Verify each on its real example first. Then: add the calendar as a Municode listing source; note the cancellation shape in `municode_meetings.py`; make Meeting Finder's Identify run host checks on the final URL after redirects; add a measured CivicLive page signature to `platform_signatures.csv`; add 3 and 4 to rtr-business `research/UNSUPPORTED_PLATFORMS.md`'s Laserfiche row.
- **History:** rtr-upcoming session reviewing rtr-deeplink's adapters, relayed by Ryan 2026-09-23.

### Mad River Valley TV's three playlist pins still sit outside its TelVue org token `[EASY]` `[EXAMPLE]`
- **Issue**: pins `playlists/4259`, `4260`, `4261` (Waitsfield, Warren, Fayston, VT) carry no org token, so `tests/test_tenant_key.py` lists them in `KNOWN_UNMAPPED_PINS`. MRVTV's token (`rb5Cd5C4A-90O1S3556SjZ8grdhFAYJy`) is now known and is already in `MULTI_GOVERNMENT_TENANTS` (`app/utils/tenant_key.py`).
- **Impact**: none for readers; it is a test exception and a loose pin shape.
- **Next action**: check (one request each) that the three playlists answer under `videoplayer.telvue.com/player/rb5Cd5C4A-.../playlists/{n}`, then rewrite the three pins with the token and empty `KNOWN_UNMAPPED_PINS`.
- **History**: `BACKLOG_DONE.md` WO-1056 and WO-1057.

### Three Archive pages store a source address ending in a backslash, so a re-ingest cannot find them `[NEEDS-AUDIT]` `[EASY]`

- **Issue**: `normalize_url()` now drops a trailing backslash, but pages 1142 (Abilene TX), 1151 (West Chester PA) and 1178 (Kaufman County TX) still store a `source_url_normalized` that ends in one. `scripts/wo1055_prepare_worklist.py` lists them (run on the Archive shell 2026-10-16).
- **Impact**: a new ingest of the same meeting looks the page up by its address, finds nothing, and can create a second copy.
- **Next action**: rewrite the three stored keys to the normalized form (an admin endpoint or a small Render-shell script), after checking no page already holds the clean key.
- **Constraint**: run it from the Archive's Render shell; check for a twin before rewriting each key.
- **History**: found 2026-10-16 in the WO-1055 prepare run. Page 1171 had the same problem and was deleted as a twin that day.

### `repair_wrong_pages.py --apply` refuses on the Archive's own shell unless given `--base-url` `[EASY]`

- **Issue**: the Archive's Render shell sets `ARCHIVE_BASE_URL` to `http://rtr-deeplink-archive:10000`. `resolve_base_url()` prefers that over `127.0.0.1:$PORT`, and `--apply` refuses any address that is not this machine.
- **Impact**: every apply run on the right shell fails once, then needs `--base-url "http://127.0.0.1:$PORT"` (2026-10-16).
- **Next action**: prefer `http://127.0.0.1:$PORT` when `PORT` is set and the script runs on the Archive service, or treat the service's own internal hostname as local. Add a test.
- **Constraint**: keep refusing a real remote address, such as a laptop pointed at production.
- **History**: 2026-10-16 after-deploy runs (WO-1055 deletes, wrong-page sheet).

### 16 pins in `tenant_overrides.csv` name a minted id with no registry row, so the loader drops them `[NEEDS-AUDIT]`

- **Issue**: on 2026-10-16 the `backfill_gov_id.py` dry run printed 16 "dropping row" warnings. 13 are `wildcard_http_sweep_2` fallback pins for eScribe and CivicWeb tenants (Alaska; Bathurst, Hillsborough, Moncton, Saint Andrews and Sussex NB; Souris PE; Athabasca, Ponoka, Red Deer, Vulcan and Westlock counties AB; North Battleford SK). 3 are Great Neck Park District NY CivicMedia channels (91485, 91500, 91505).
- **Impact**: these pins do nothing. Pages on those hosts get no government from them.
- **Next action**: mint the missing ids with the registry write helper (most are real Statistics Canada subdivisions, which may already have a `ca:csd:` id to use instead), or drop the rows.
- **Constraint**: never re-point a pin to a namesake; check each host's owner by hand.
- **History**: `backfill_gov_id.py` dry run on the Archive shell, 2026-10-16.

### Two TelVue pages for separate Vail-area bodies would be re-keyed to the Town of Vail by a whole-channel pin `[NEEDS-AUDIT]`

- **Issue**: `tenant_overrides.csv` pins TelVue channel `player/YGktjFZCLukJd_8Fx53BkVRk4tAZafS4` (High Five Access Media) to Vail, CO (`us:place:0880040`). The 2026-10-16 `backfill_gov_id.py` dry run would move page 13056 ("Eagle Valley Transportation Authority") and page 13057 ("EagleVail Metropolitan District") to Vail. The same dry run shows page 11427 ("Cumberland, ME", pinned to the town, `us:cousub:2300515430`) displayed as "Cumberland County, ME".
- **Impact**: two real special districts would be filed under the wrong government, and one town would show a county's name.
- **Next action**: add per-video pins (or mint ids) for the two Vail-area bodies, as WO-1153 did for the Vail Housing Authority. Check why the Cumberland town id displays as the county. Then rerun the backfill for `videoplayer.telvue.com`.
- **Constraint**: `videoplayer.telvue.com` was left out of the 2026-10-16 apply run for this reason, which also held back 5 TelVue moves that looked right (pages 11276, 11337, 11340, 11897, 12826).
- **History**: `backfill_gov_id.py` dry run on the Archive shell, 2026-10-16.

## Reliability, ops & cost

### `[BIG]` Make BACKLOG.md a generated doc: one file per entry

- **Issue**: BACKLOG.md conflicts on most parallel PRs because entries are edited and moved in place. A union merge is unsafe for it (it would bring back moved or edited entries), and the line-set merge driver does not fit multi-line entries.
- **Impact**: 128 commits in two weeks touched it; each pair of concurrent PRs risks a hand-resolved conflict.
- **Next action**: store each entry as its own file (for example `backlog/<section>/<slug>.md`, with the section and title in front matter). Generate BACKLOG.md and its TOC from those files by extending `scripts/build_backlog_toc.py`, and have CI check the generated file is current.
- **Constraint**: keep the TOC grep protocol working (each TOC line stays a verbatim prefix of a real line). Keep `scripts/check_backlog_done_headings.py` working. Migrate in one PR, when no other backlog PRs are open.
- **History**: WO-1184 (2026-10-05) added union for BACKLOG_DONE.md and a line-set driver for the queue and pin files; see its entry in `BACKLOG_DONE.md`.

### `[WAIT]` Run the local Whisper recovery on the ~159 Granicus/Swagit pages with no transcript, once the office's Granicus sweep is done (WO-1163)

- **Issue**: 159 Archive pages whose video is on `*.granicus.com` (Granicus and Swagit) have no transcript. The cloud worker's media pull fails on them: `archive-stream.granicus.com` accounts for 439 of 650 recorded transcription failures, mostly ffmpeg timeouts. The same hosts work from an office connection.
- **Impact**: the largest group of real meetings on the site with no transcript.
- **Next action**: when no other Granicus job is running from the office connection, rebuild the list (pages with no default-version segments whose video host is `*.granicus.com`, excluding YouTube/Viebit). Then run `scripts/transcribe_backlog_locally.py --urls-file` on the drip-free Mac, with `scripts/youtube_fetch_guard.install()`, under `caffeinate`.
- **Constraint**: one Granicus-heavy job per office connection. About 30 minutes per meeting on a 4-core Mac (Whisper `small`). New tier-3 Granicus lines no longer need a hand run: the drip's direct lane feeds them (WO-1168).
- **History**: 2026-09-27 conductor session; WO-1152's entry (method and per-platform results); WO-1168.

- **[NEEDS-AUDIT] `rtr-deeplink-archive`'s "HTTP health check failed" alert recurs roughly weekly; WO-80 (2026-08-30) didn't fully close it.**
  - **Issue**: the 5-second health-check timeout fired at least 5 times in 30 days after WO-80 made `/api/health` O(1) (2026-08-29, twice on 08-31, 09-13, 09-17). Render restarts the instance each time.
  - **Impact**: no reader-facing outage recorded. One confirmed side effect: the 2026-09-17 blip made the daily saved-search alert call 502, and that day's alerts were skipped.
  - **Next action**: ship the `send_search_alerts()` retry (Ship next) first; it removes the only known consequence. If the alert keeps recurring, Ryan pulls Render's log for one of the 5-second windows to see what is slow.
  - **Constraint**: don't blame Render's bandwidth cap without checking its usage dashboard; that link was never confirmed.
  - **History**: `BACKLOG_DONE.md` WO-80; inbox-triage runs 2026-09-14 and 2026-09-17.

### Media-source reliability

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
- **Next action**: detect the slow-source shape early — a job whose
  first few chunks all need retries will need them throughout — and
  widen or defer that job's timeout rather than grinding repeated
  retries through the same slot. Not built: a real per-job adaptive-
  timeout policy, bigger than a single-PR change (WO-936, 2026-09-21,
  narrowed this entry to just this half — the other half, a real-5xx-
  vs-timeout logging distinction, is done, see `BACKLOG_DONE.md`).
- **Constraint**: whatever gets built must never starve a real
  user-submitted `PRIORITY_MEDIUM` job behind automated `PRIORITY_LOW`
  backlog work.
- **History**: `BACKLOG_DONE.md` (WO-40, 2026-08-21) — same failure-
  pattern measurement this residual is drawn from; WO-936 (2026-09-21)
  closed the logging-distinction half of this entry's old Next action.

### Transcription queue & workers

- **[LATER] `list_transcription_backlog_candidates()` still does a real N+1 query pattern.**
  - **Issue**: it scans pages oldest-first and calls `_has_good_transcript()` once per page (`archive/db/crud.py`), unlike `find_auto_transcription_candidate()`, which became one SQL predicate on 2026-08-17.
  - **Impact**: O(n) small queries. Callers today are the worker's batch top-up (`worker/main.py` `maybe_generate_batch_auto_jobs()`, WO-1148), the drip's direct lane via `GET /internal/transcription-backlog` (WO-1168), and the local script.
  - **Next action**: rewrite it with the same single predicate only if `pg_stat_statements` shows it is a measured cost.
  - **Constraint**: check `pg_stat_statements` first; don't guess.
  - **History**: `BACKLOG_DONE.md` (2026-08-17 `find_auto_transcription_candidate()` rewrite).

### Search Console, structured data & SEO plumbing

- **[NEEDS-AUDIT] Search Console "Missing field" flags (Videos `uploadDate`, Events `startDate`) are pages with no valid date.**
  - **Issue**: `archive/templates/meeting_page.html` emits both fields only when `iso_date` is set. That was a deliberate 2026-08-21 trade, "missing" in place of "invalid".
  - **Impact**: `GET /internal/date-format-audit` on 2026-08-29 found 226 of 2,389 pages with a null date. Those pages lose video and event rich results.
  - **Next action**: re-run the date-format audit, group the null-date pages by platform, and fix date capture in the adapter with the most. Otherwise accept the gap and record it as a Standing decision.
  - **History**: `BACKLOG_DONE.md` "Search Console dashboard walkthrough" (2026-08-29); dashboard checklist #1338.

### `/coverage` as a QA surface

## Trust, safety & data quality

### Shade the stretches of a Whisper transcript where Whisper itself was unsure

- **Issue**: readers see one whole-page "AI transcript" note, but nothing marks the shaky stretch itself (a short foreign-language proclamation, dead air, music at a recess). Since WO-1968, new Whisper segments store `avg_logprob`, `no_speech_prob` and `compression_ratio`; nothing reads them yet.
- **Impact**: a reader cannot tell a solid stretch from a guessed one inside the same AI transcript.
- **Next action**: after the worker and Archive deploys, let new transcripts build up, then pull 20 or more through `/internal/export/pages?include_segments=true`. Read the numbers next to the text by hand and pick a threshold from what is actually wrong. Then build the shade in `archive/templates/meeting_page.html` (no shade on a segment with no numbers).
- **Constraint**: transcripts made before WO-1968 have no numbers and are not backfilled; they must show no shade, not a guessed one. The numbers score a whole Whisper segment, so every piece of a gap-split segment carries the same values. Ryan's own framing (CLAUDE_BACKLOG, 2026-08-18): flag the stretch, not the page. Hold the separate "reads well but false" AI check (cost undesigned, prompt-injection review first).
- **History**: `BACKLOG_DONE.md` WO-1968.

### Known wrong names in Whisper transcripts are not fixed yet (correct-text route waits on a deploy)

- **Issue**: WO-1964 added `POST /internal/transcript-version/correct-text`, which fixes one word or name in one segment. No real page has been corrected with it yet, and it is not live until the Archive is deployed.
- **Impact**: known wrong names stay on the page. Example: `/m/city-ma-city-council-5-6-2025` (Whisper version 1762) reads "Grotten Hill Music Center"; it is Groton Hill.
- **Next action**: after the deploy, fix the Groton Hill example first. For every other fix, take the spelling from the meeting's own agenda: it names the members, staff, speakers and places in writing. Use the government's member list where the agenda does not name someone. Never fix a name from the captions alone.
- **Constraint**: a caption/Whisper disagreement is a lead, not proof. A word-by-word comparison on the 3 WO-1160 pages (2026-09-29) found dozens of name differences per page; captions were right on some (Groton Hill, Framingham, HVAC), and on many (councilor names) neither text could be confirmed without the agenda.
- **History**: `BACKLOG_DONE.md` WO-1964, WO-1160, WO-1164.

### Pinned hosts: machine-made pins with no Archive pages yet are unchecked `[NEEDS-AUDIT]`

- **Issue**: WO-1068's rule (a person-checked fallback pin beats a namesake name match) trusts only `registry.HUMAN_PIN_SOURCES`. WO-1075 re-checked and marked the 10 machine-made pins that had already misfiled a page. Every other machine-made whole-host pin is still unchecked, and 7 of the 15 wrong pins found on 2026-09-25 came from the name-guess `wildcard_http_sweep_*` runs (Durham NC pinned to Durham ON, Eustis FL to Eustis ME, and so on). The rule also fires only for a namesake match, so a special body filed under an unrelated place (Broward MPO -> Davie) still needs a hand re-file.
- **Impact**: a wrong pin does no harm until a page with no resolvable name lands on its host; then the page goes to the wrong government with nothing flagging it.
- **Next action**: for each `wildcard_http_sweep_*` pin, compare the pinned government's state with the host's own landing page (title or footer), the check that caught all 7 on 2026-09-25; fix mismatches and add `landing_page` to the ones that hold. `reflect-townofwellfleet.cablecast.tv` stays unmarked on purpose: its channel also carries Barnstable County shows ("Assembly", "County Com").
- **Constraint**: report before re-filing any existing page.
- **History**: `BACKLOG_DONE.md` WO-1068, WO-1074, WO-1075; per-page table in `docs/investigations/whole_host_pin_mismatch_2026-09-25.md`.

### 2 already-pinned YouTube channels still disagree with the Archive's own pages `[NEEDS-AUDIT]`

- **Issue**: WO-257 found 7 of 108 pinned channels whose pin disagreed with the Archive's pages. WO-1060 and the 2026-10-06 pin audit fixed North Miami, Osage County, Richmond Heights and Dover-Sherborn, and the `@ulctTube` pin is gone. Two remain: `@TV25BCOCC` is pinned to `us:place:2404000` (Baltimore city as a place), while its pages carry `us:county:24510` (Baltimore city as a county-equivalent), the same government under two ids. `@townmeetingtv` is pinned to Burlington VT (`us:place:5010675`), while a page says South Burlington (`us:place:5066175`).
- **Impact**: Baltimore pages may be split across two ids. Town Meeting TV is a regional channel, so a whole-channel pin to one city may be wrong.
- **Next action**: pick one Baltimore id and re-key the pages. For `@townmeetingtv`, decide whether it is a multi-government channel (per-video pins) or Burlington's own.
- **History**: `BACKLOG_DONE.md` WO-257 and WO-1060; `reports/wo257_study/already_pinned.csv`.

### 27 real Quebec municipalities are marked `reject_reason=off-mission`, including Terrebonne (population 119,944) and Rivière-du-Loup (20,118) `[NEEDS-AUDIT]`

- **Issue**: found live 2026-09-13 (WO-327), rerunning WO-323's 92 and
  WO-324's 258 Quebec rows with the new French hop-link vocabulary. 75
  governments got a real, name-matched council-session page confirmed
  (`www.ville.terrebonne.qc.ca/conseil-municipal/`,
  `www.villerdl.ca` -> a real Rivière-du-Loup council page, etc.). Of
  those 75, this WO safely applied `reject_reason=meeting-without-video`
  to the 47 whose CURRENT reason was `deferred-french-vocab` or
  `no-platform-link-found` (both clearly meant to be superseded). The
  other 27 currently read `reject_reason=off-mission` -- a real,
  deliberate-sounding classification this WO has no record of the
  reasoning for, and no `note`-shaped field exists on the row to explain
  it. Every one of the 27 has a real domain, a real population, and (per
  this rerun) a real, current, name-matched municipal council page --
  nothing in the 27 examples looks like a genuine off-mission entity
  (a federal/tribal body, a private organization, a defunct
  municipality). Not overwritten here, on purpose: this project's own
  "off-mission" reason is presumably a real, considered call somewhere,
  and a name-match on a fetched page is real but not strong enough
  evidence to unilaterally reverse it without knowing why it was set.
- **Impact**: potentially 27 real, current Quebec municipalities
  (including at least one major city, Terrebonne, ~120K population) are
  being silently skipped by every future sweep that filters out
  `off-mission` rows, for a reason nobody can currently reconstruct.
- **Next action**: find where/when `off-mission` was set for these 27
  gov_ids (git-blame or a prior WO's own findings/report file naming
  them) to learn the real reason; if it turns out to be a stale/wrong
  bulk classification, correct it the same way this WO corrected the 47
  safe rows. The full list of 27 (gov_id, domain, city_name,
  population_estimate, the real URL this WO found) is in this WO's own
  `research/wo327_off_mission_anomaly.json` (on disk, not committed by
  this WO per the never-commit-in-rtr-business rule).
- **Constraint**: don't bulk-overwrite `off-mission` rows from a
  name-match signal alone across the wider population -- this is a
  27-row anomaly found by chance in one rerun's output, not a general
  audit of every `off-mission` row in the file.
- **History**: `BACKLOG_DONE.md`'s WO-327 entry;
  `ENUMERATION_METHODS.md` §336.

### `jurisdiction_coverage.csv` rows whose recorded website belongs to another government or organization: 21 confirmed by hand in WO-912/913, 5 more from WO-282 `[NEEDS-AUDIT]`

- **Issue**: a row's `domain` is not that government's own site. Known cases: 21 from WO-912/913 (`rtr-business/research/wo913_wrong_recorded_domains.csv`), for example De Kalb TX carrying De Kalb IL's site, plus 5 from WO-282 (Berks County and `colorado.gov`). Lake City FL's domain is now a parking page. Bare placeholder hosts are shared by many rows (`www.facebook.com` 44, `sites.google.com` 11). At least 9 domains are shared by 2-3 unrelated gov_ids (WO-338, e.g. `stearnscountymn.gov` on two towns).
- **Impact**: any sweep that trusts `domain` reads the wrong government's page, and a domain-keyed resumable sweep treats every row sharing a host as done after the first.
- **Next action**: run the WO-1004 domain-health check (its own entry in Ship next) to get the full worklist. Then, per row, find the real site by a targeted lookup and move the wrong value to `alternate_domains`. Add `sites.google.com` and `www.facebook.com` to the population builders' skip list.
- **Constraint**: never blank or guess a `domain`. Check the state too, since namesakes pass a name check. A real shared city-county site is legitimate, so check each shared domain individually.
- **History**: `BACKLOG_DONE.md` WO-912, WO-913, WO-282, WO-283, WO-292, WO-320, WO-338, WO-1004.

### 8 rows carrying `prior_reject_reason=already-covered` checked live, all 8 were stale `[NEEDS-AUDIT]`

- **Issue**: WO-320's brief flagged `already-covered` (no page today) as
  meaning the government is probably keyed to a different `gov_id` for
  the same real government elsewhere in the Archive, and asked for a
  live check before trusting it. All 8 rows in WO-320's own 194-row
  population carrying that reason (Lincoln city NE, Jefferson City MO,
  Agawam Town MA, Pleasantville NJ, Cambridge MD, Lake City FL,
  Lovington NM, London KY) were checked live against
  `/internal/jurisdiction/search` by name -- every one came back either
  empty or matching only a different, same-named government in another
  state/province (Lincoln ON/OR/RI, Salt Lake City UT, Pleasantville NY/
  OH, Cambridge MA/ON, London ON, Londonderry NH, New London NH/WI).
  None of the 8 is actually covered anywhere in the Archive today.
- **Impact**: at least these 8 rows have a misleading `reject_reason`
  that would make a future sweep skip a government that actually has no
  coverage at all. Unknown how many more of the reason's other
  occurrences across the full file are similarly stale -- this WO only
  checked its own 8.
- **Next action**: a small follow-up sweep of every `already-covered`
  row in `jurisdiction_coverage.csv` against `/internal/jurisdiction/
  search`, correcting the reason (or clearing it) wherever no real match
  exists.
- **Constraint**: none beyond the usual per-name-query politeness; this
  is a read-only Archive endpoint check, no fetching of government sites
  needed.
- **History**: `rtr-business/research/wo320_report.csv`; this WO's final
  report.

### A bare YouTube channel-listing scan measurably ingests non-meeting videos: Ryan set three outcomes and the rules on 2026-09-21, nothing built yet `[NEEDS-AUDIT]` `[BIG]`

- **Issue**: about 4% of channel-listing hits are not government meetings (7 of 167 in WO-147 and WO-149). WO-933's word-boundary rule now rejects "Commissioners Tour Picatinny Arsenal's ...", "Larry J. Dix Boardroom" and "Senate Bill 152: ... Committees". Four still pass and are pinned as strict expected-fail tests in `tests/test_video_gate_wo933.py`: "HAIRitage 2026 CROWN Act Workshop: Advice from Our Commissioner Board", "Council Participation Instructions", "What Does a County Commissioner or Council Member Do?", "Pennsylvania Fish and Boat Commission Water Conservation Officer training: Boating Scenarios". Titles alone cannot decide, in either direction. In the local export of 2026-09-21, 145 of 4,072 YouTube and Vimeo page titles (3.6%) carry no meeting signal and many are real meetings ("LCBOC CM 8 25 26", "06 17 2026 CC Video"), while a title with a meeting word can be a non-meeting.
- **Impact**: a wrong video can go live on a tier-1/2 page with no review. An unrelated video promoted in a hub looks ridiculous, and a channel-sourced or pasted video is a way to plant a spoofed or misleading page. Not measured on pages already live beyond the title scan above.
- **Next action**: on hold (Ryan, 2026-10-16). Meeting Finder already ends every find with a programmatic check, a JEV classifier pass and a human hand check (`rtr-findmeeting/findmeeting/handcheck/`). The design below stays as the plan if the hold lifts. Ryan decided 2026-09-21 that a video is one of three outcomes, and that the rules below are a starting point. Edge cases are expected and can wait for a real exception on a larger user base.
  - **A, meeting**: a normal page.
  - **B, government video that is not a meeting** (training, tour, explainer, ceremony, orientation, forum, a promo or "welcome" video that has speech): the page exists and a direct link works, but it is noindexed and left out of the sitemap, hubs, `/meetings`, the feed, search and topic chips.
  - **C, not related**: no page is created, and a live one is taken down. C means personal videos, TV clips, school sports and performances, children or minors as the primary speakers, and videos with little to no speech to transcribe (security camera footage, music videos).
  - **Rules, first that fires wins**: (1) source: a channel pinned to this government in the registry is trusted, a pasted or unpinned one never rises above B until confirmed; (2) meeting procedure in the transcript ("call to order", "roll call", "motion", "all in favor", "adjourn"; vocabulary already in `archive/utils/highlights.py`) makes it an A whatever the title says, which also covers a school board meeting about youth; (3) C signals; (4) B signals; (5) otherwise a trusted source with a meeting title is an A, and **"cannot tell" is a B, never an A**. A video with no captions starts on title and source, and is judged again once our own transcript exists.
  - **Build in three steps**: (a) the hiding, on the column that already exists: `MeetingPage.meeting_kind` (decision D2a, `String(20)`, NULL means an ordinary meeting; allowed values are `MEETING_KINDS` in `archive/db/crud.py`: `meeting`, `press_conference`, `public_statement`, `town_hall`, `workshop`, `hearing`). No list, sitemap, hub or feed query filters on it and no template uses it (checked 2026-09-21), so no new column or migration is probably needed (recheck before building). Add a B-tier value to `MEETING_KINDS` (it must fit in 20 characters), then wire the hiding into the same conditions as the empty-page rule (`crud._is_empty_page_condition()`, the hub conditions) and the template noindex. Which values hide is Ryan's later call: a town hall, a workshop and a hearing are legitimate meetings and stay listed. Pages 6119 and 6218 (kept by Ryan 2026-09-21) are the first B pages; (b) extend `assess_video_candidate()` in `app/utils/video_hand_check.py` from pass, reject or cannot tell to meeting, government video, unrelated or cannot tell; (c) apply it to pages already live through WO-934's worklist. Real titles now live that the rules would move: "Role of City Council in Government", "Agenda Center", "DIY Cardboard Boat!", "Youth Council Gives Students Power To Learn - Season 6 Episode 3", "2025 Events Highlight | Brampton Board of Trade". Remove the expected-fail markers when it works.
- **Constraint**: never judge "no speech" from missing or thin captions. In the same export, 176 pages labelled "Blank/no transcript" are almost all real meetings with no transcript yet, and 135 pages with only 1 to 15 caption cues are real meetings with bad source captions. Judge speech only from our own transcription output, and measure words per minute on finished own transcripts (read-only) before choosing a threshold. Minors cannot be measured from text: use proxies (school-event words, channel type, YouTube's category or made-for-kids flag if the fetch returns them; our adapter does not read those fields today and a live check is blocked from this machine) and do no voice-age analysis. Do not change `MEETING_ALLOWLIST`/`PROMO_BLOCKLIST` from this small sample.
- **History**: `BACKLOG_DONE.md` WO-933, WO-147, WO-149. Decided in the WO-930 session on 2026-09-21.

### Meeting body is blank on ~90% of archived pages `[NEEDS-AUDIT]` `[BIG]`

- **Issue**: `MeetingPage.meeting_body` ("City Council", "Planning Commission") was on 667 of 6,529 pages on 2026-09-09. Since then, CivicClerk, CivicPlus and Legistar extract it (WO-904/905/906). Cablecast, Granicus, eScribe and Swagit have no source field (Standing decision). iQM2 and PrimeGov have their own entries.
- **Impact**: most pages can't be filtered or reported by body.
- **Next action**: re-count with `GET /internal/meeting-inventory/summary` after the next deploy (the iQM2 calendar lookup from PR #2080 rides with it). The remaining real sources are iQM2's calendar and PrimeGov's `committeeId`, each on its own entry. New tier-3 lines already carry a body from Meeting Finder (WO-1176).
- **Constraint**: no title-phrase table and no title guess, at ingest or at read time. The Standing decision "Cablecast, Granicus, eScribe, and Swagit have no real `meeting_body`" rules it out; the report exists to count the real gap.
- **History**: `BACKLOG_DONE.md` WO-904/905/906/907; report from WO-124 (`scripts/export_meeting_inventory.py`).

### `[HUMAN]` `[BIG]` Nothing verifies a submitted URL is a genuine government site

- **Issue**: fake/spoofed "government" pages and non-government content
  can be archived and presented as if official — no verification step
  exists for a submitted URL's site.
- **Impact**: wide open gap, threat-modeled in `TRUST_THREAT_MODEL.md`;
  affects trust in every page the product presents as official.
- **Next action**: on hold (Ryan, 2026-10-16). Meeting Finder already
  ends with a programmatic check, a JEV classifier pass and a human hand
  check before a find is ingested. Two mitigations also shipped:
  `noindex` on `generic_fallback`/`unknown` pages (2026-08-11), and
  social auto-posting refusing `best_effort` / `platform == "unknown"`
  pages (WO-21, 2026-08-21).
- **History**: threat-modeled 2026-08-10; see `TRUST_THREAT_MODEL.md`.

### `[NEEDS-AUDIT]` One row in `jurisdiction_coverage.csv` has shifted/corrupted columns (`domain` reads `'False'`, blank `gov_id`)

- **Issue**: found while auditing `domain` shapes for WO-193
  (2026-09-11): one row's fields are shifted left by several columns —
  `city_name` is `9`, `state_or_province` is `carrollcountyil.gov`,
  `country` is `http://www.blackhawkhills.com/`, `domain` is the literal
  string `False`, `suspected_meeting_link_provider` holds
  `no-platform-link-found`, and `gov_id` is blank. This looks like a
  real government (Carroll County, IL area) whose row got mis-shifted
  by an earlier script, not a domain-shape problem.
- **Impact**: small (one row) but this government is currently
  unidentifiable by `gov_id` and would sort oddly in any tool that reads
  `domain` expecting a real host.
- **Next action**: find this row (grep `carrollcountyil.gov` in
  `jurisdiction_coverage.csv`) and manually re-derive its correct column
  values, or delete and re-add it cleanly, once someone can confirm
  what its real fields should be.
- **Constraint**: don't guess the shift amount from this one row alone —
  confirm against a live source (the county's actual site/domain)
  before rewriting it.
- **History**: WO-193 (`BACKLOG_DONE.md`) left this row's other columns
  untouched on purpose — normalizing `domain` on a already-corrupted row
  doesn't fix the corruption, and guessing the intended shift wasn't in
  scope for a domain-shape pass.

### `[NEEDS-AUDIT]` `rtr-business/research/jurisdiction_coverage.csv` has 1,339 duplicated `gov_id`s (2,132 extra rows), and some already-confirmed platform rows never got their stale `reject_reason` cleared

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

## Roadmap & strategy `[IMPROVEMENT-ROUND]`

### Adapters drop signals that show a person captioned the meeting (found 2026-10-09, WO-1960) `[IMPROVEMENT-ROUND]`

- **Issue**: WebVTT voice tags now fill `speaker` (WO-1967, `BACKLOG_DONE.md`). Still dropped: Cablecast's `S1:` labels and Tampa's typed "ALAN CLENDENIN :" names (no real fixture of either shape in `tests/fixtures` yet), and Tampa's page header ("unedited version of realtime captioning"), which is cut before the first timestamp. The Archive's `source` only separates `transcribed` from everything else, so human, edited and automatic captions all look the same.
- **Impact**: finding human-captioned meetings takes a text-pattern scan of every stored transcript (`scripts/find_named_speaker_transcripts.py`), and it cannot use the header. Name labels also appear in video-call machine transcripts, so a label alone is not evidence of a person.
- **Next action**: (1) save a real Cablecast `S1:` transcript and a real Tampa transcript page as fixtures, then set `speaker` in `cablecast._parse_transcript()` and `tampa.py`, leaving the text as is; (2) keep a short caption credit (Tampa's header) on the transcript version, which needs a new column. Room labels are already skipped by `vtt_parser.clean_speaker_label()`; reuse it.
- **Constraint**: the caption credit is a new field on the ingest payload and needs an Alembic migration (`archive/alembic/`). The speaker label itself needs none (it lives in the segments JSON). A label alone is not a person.
- **History**: rtr-business `research/CAPTION_METHODOLOGY.md` (2026-10-09 to 10-12). WO-1967 (2026-10-16) built voice tags, the page display and the `.txt` export.

### `[IMPROVEMENT-ROUND]` Pierce County TV: per-government YouTube leads for the drip Mac

- **Issue:** Pierce County TV (piercecountytv.org, YouTube `piercecountytv`) carries DuPont, Fife, Orting, Pierce County Council, Port of Tacoma, Puyallup, Sumner, University Place and the Tacoma-Pierce County Health Dept. Its own site hides the video list behind a JS widget, so no government has a confident match.
- **Impact:** those governments read as "no video" while their meetings sit on the hub's channel.
- **Next action:** write one lead per government (channel plus a title pattern) in the drip's `youtube_channel_leads.csv` format for the drip Mac to list and match.
- **Constraint:** YouTube is fetched only by the drip Mac; never fetch it from here.
- **History:** WO-1053 (#1434) built `regional_tv_hubs.csv` and `scripts/hub_harvest.py`; WO-1054/1058 (#1436, #1445) taught Meeting Finder shared hubs; station censuses (#1604, #1606, #1945) routed the rest, TVCTV included. See `BACKLOG_DONE.md`.

### `[IMPROVEMENT-ROUND]` Vendor slug guess ladder for governments whose own site blocks us

- **Issue:** when a government's own site blocks every request form and the drains (DNS/CNAME, certificate log, Common Crawl) find nothing, nothing tries the vendor's own servers. The guess ladder (`docs/MEETING_FINDER.md`, build step 7) is not built; Meeting Finder already labels these rows `account-not-found` / blocked.
- **Impact:** an unknown, smaller-than-feared population. Re-measure from the latest Meeting Finder verdicts before sizing; WO-1122/1134 showed most "blocked" rows were false.
- **Next action:** per vendor, learn the catch-all response for a made-up slug once; try slug shapes from the government's name and state, ordered by past hit rate; send each answering slug to List/Resolve in audit mode.
- **Constraint:** a guessed account is a candidate, never a pin, until a real meeting passes the identity check, with an existing-pin check and own-state match (Standing: "Guessing a bare tenant name..."; WO-168 had 8 of 14 wrong). Never touch the blocked site.
- **History:** drains wired by WO-1043 (#1406); blocked re-run of 3,170 governments (#1520); WO-1122, WO-1134 in `BACKLOG_DONE.md`.

### `[IMPROVEMENT-ROUND]` `[BIG]` Agenda text as a first-class, **versioned** asset — model, resolver, every adapter, and display

- **Issue**: steps 1 and 2 shipped in WO-1966 (2026-10-16, see
  `BACKLOG_DONE.md`): an `agenda_versions` table and one shared
  extraction path (`app/agenda_text.py`, ported from `rtr-upcoming`).
  CivicPlus and CivicClerk agenda **and** packet text is read once at
  ingest and stored per page, deduplicated by content hash. Still open:
  nobody can see or search the text, and 11 other adapter files that set
  `agenda_link` (13 in all; 4 set `packet_link`) are not read.
- **Impact**: the stored text is invisible to readers until display and
  search exist. It also still blocks the `rtr-upcoming` integration: the
  ingest gate at [app/main.py](app/main.py) accepts a video-less page on
  `agenda_link` alone, and text now has a place to land, but nothing
  surfaces it.
- **Next action**: (1) **Fix CivicClerk links first (claimed 2026-10-17, office Mac; needs that Mac's network and fresh real fixtures)**: the office-Mac A2 check (2026-10-17, 6 real meetings, report `wo-a2_agenda_real_check.md`) found CivicClerk's API now returns `"url": null` on every published file, and the old `GetMeetingFile(...)` address answers 404. Only `streamUrl` (`GetMeetingFileStream`) works. So the adapter gets no agenda or packet link on new resolves, and `app/agenda_text.py` does not recognise stream links. Fix: read `streamUrl`, accept `GetMeetingFileStream` links, refresh the fixtures. CivicPlus read correctly on 3 of 3 (a 315-page Anacortes packet: about 606,000 characters, 8 s, 111 MB peak), and the scanned-PDF and over-100 MB guards worked. Deploying WO-1966 is safe for CivicPlus; CivicClerk reads nothing until this lands. (2) **Display**: the newest agenda text on
  `/m/{slug}`, loaded per page only, and a version list. (3) **Amendment
  classification and diff**: port `rtr-upcoming`'s `agenda_diff.py` and
  its `initial`/`amendment`/`reissued`/`alternate` kinds; compare an
  agenda with an agenda and a packet with a packet; ignore changes that
  only reflect a newer `extractor_version`. (4) **Search**: a separate
  index over `agenda_versions`, never folded into `search_corpus` (packet
  text runs to 1.8M characters). (5) **Other adapters**: Legistar and
  Granicus next, each checked against a real sample first.
- **Constraint**: port, don't reinvent. Read
  `docs/investigations/agenda_text_versioned_asset.md` before touching
  extraction or display. Ryan, 2026-10-16: store agendas and packets; no
  nightly re-read (read at ingest only). Never load agenda text in a query
  that spans every page. PDFs parse only in the child process
  (`app/agenda_extract_worker.py`).
- **History**: PR #640 (2026-08-31) added the links. WO-1966 (2026-10-16)
  added the table, the extraction path and the CivicPlus/CivicClerk
  ingest read. Sequencing: `AGENDA_TEXT_BIG_VERSION_BRIEF.md`.

### Product direction & open strategic questions

- **`[IMPROVEMENT-ROUND]` `[BIG]` Open submissions to the Full Context feed, plus a moderation/review queue.**
  - **Issue**: WO-943 (2026-09-21) shipped `/context` as editor-only —
    only Clerk user ids listed in `CONTEXT_EDITOR_CLERK_IDS` can post.
    Letting any signed-in user submit a clip would grow the feed much
    faster, but needs a review step before a submission goes public.
  - **Impact**: today the feed's size is capped by how much time an
    allowlisted editor has, not by how many good clips exist.
  - **Next action**: build a submission form for any signed-in user, plus
    an editor review queue (approve/reject/edit before publish). The
    schema already supports this without a migration — `ContextEntry`'s
    `status` column just needs a new value (e.g. `pending_review`) and
    `created_by_clerk_user_id` already records the real submitter.
  - **Constraint**: blocked on the same open moderation question
    `ACCOUNTS_PLAN.md` already flags for `post`/`repost` notes — public,
    free-text user-generated content is real new surface area this app
    has never had. Don't build the open submission form before that
    question has an answer.
  - **History**: `BACKLOG_DONE.md`'s WO-943 entry; `ACCOUNTS_PLAN.md`'s
    2026-09-21 note.

### `[IMPROVEMENT-ROUND]` `[BIG]` Accounts + token billing, phases 2-6 — see [ACCOUNTS_PLAN.md](ACCOUNTS_PLAN.md)

- **Issue**: phase 1 (Clerk sign-in, saved meetings/searches) shipped
  2026-08-11 and is live. Phases 2-6 (proposed polymorphic `Note` data
  model, token billing, advocate/organizer-and-institutional business
  framing) are proposed but not built.
- **Impact**: nothing broken — this is forward roadmap, gated on Ryan's
  call on open questions before phase 2 starts.
- **Next action**: wait until Ryan is back from France (Ryan,
  2026-10-16). Then build it as part of the KQED trial on rtr-upcoming,
  which needs its own logins. `ACCOUNTS_PLAN.md` has the 6-phase
  sequence, the proposed data model and the open questions.
- **History**: `README.md` (shipped phase-1 architecture), `BACKLOG_DONE.md`
  (phase-1 build history), `ACCOUNTS_PLAN.md` (phases 2-6 plan).

### Growth, audience & discoverability

- **`[IMPROVEMENT-ROUND]` Governments with no domain on record: find the official website first.**
  - **Issue**: registry rows with neither a meeting URL nor a domain give Meeting Finder nothing to start from. The last count (21,331, 2026-08-28) predates the DNS guess run (#1559, 2,260 fallback pins) and the WO-1077/WO-1142 domain repairs.
  - **Impact**: the largest remaining coverage gap by row count, though mostly very small places.
  - **Next action**: recount no-domain rows by population band, then decide whether a website-finding pass (CISA .gov list, state directories, as WO-1077 did) is worth running on the over-5,000 band only.
  - **History**: `BACKLOG_DONE.md` "no-video-signal tier"; rtr-business `ENUMERATION_METHODS.md` §21.

- **`[IMPROVEMENT-ROUND]` `[BIG]` Recurring crawler: pull each covered government's new meetings automatically.**
  - **Issue**: the corpus now grows through Meeting Finder runs, hand-approved tier-3 queues and the drip Mac, all started by a person. Nothing checks pinned governments on a schedule for meetings newer than their latest Archive page.
  - **Impact**: coverage goes stale government by government; `/meetings` search is only as good as the corpus is fresh.
  - **Next action**: hold (Ryan, 2026-10-16). rtr-discovery mostly covers this. Do not auto-ingest all new tier-1 meetings (Standing decisions). When the tier-3 queue is under 200 lines, start drawing in new tier-3 meetings. One part is worth doing now: find sources that keep video up only briefly (for example some Midwest state legislatures) and pull those before they go.
  - **Constraint**: the trigger will not arrive on its own. Tier-3 queue lines (`scripts/tier3_auto_transcription_queue.txt`):

    2026-09-20: 986 lines

    2026-10-06: 992 lines

    2026-10-16: 1,486 lines (about +49 a day since 2026-10-06)

    This is crawling, so it honors robots.txt (Standing: "The tier-3 queue is hand-approved meetings, not crawling"); YouTube only from the drip Mac; one meeting per government per run.
  - **History**: held back 2026-08-10; `CORPUS_EXPANSION_PLAN.md` was closed as handled by rtr-discovery (#657).

- **[IMPROVEMENT-ROUND] Batch lookup — accept multiple meeting URLs at
  once instead of one at a time.**
  - **Issue**: no way to submit multiple meeting URLs in one request —
    only one at a time today.
  - **Impact**: the main friction point for a journalist working many
    jurisdictions at once.
  - **Next action**: not yet (Ryan, 2026-10-16); wait for a real user
    to ask. When it starts, design the batch endpoint together with its
    abuse-prevention plan, not after — a batch endpoint is a natural
    abuse vector, and the transcription worker's real per-job compute
    cost means unmetered batch access could get expensive fast.
  - **Constraint**: worth sequencing after accounts even though it
    doesn't strictly require them, since rate-limiting or
    account-gating is the natural way to bound abuse.
  - **History**: none yet — proposal, not investigated.

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

- **`[IMPROVEMENT-ROUND]` Auto-post each newly published Full Context entry to Bluesky.**
  - **Issue**: WO-943 (2026-09-21) shipped the Full Context feed
    (`/context`) but nothing announces a newly published entry the way a
    newly created Archive page already does.
  - **Impact**: a real, editor-curated moment (a social clip tied to its
    exact meeting second) is exactly the kind of content the existing
    Bluesky account was built to announce — see "Social auto-posting"
    above — but today it never does.
  - **Next action**: reuse `archive/utils/social.py`'s existing
    Bluesky-posting code, triggered from `set_context_entry_status()`
    when an entry's status transitions to `published`.
  - **Constraint**: `SocialPost`'s unique constraint is per (meeting
    page, network) — see `archive/db/models.py`. A Full Context
    announcement is a different post about a page that may already have
    its own `SocialPost` row from the page's own creation, so posting
    both needs a real design decision (a second `SocialPost` row keyed
    differently, or a separate ledger table) before this can reuse the
    existing dedupe mechanism as-is.
  - **History**: `BACKLOG_DONE.md`'s WO-943 entry; README's "Social
    auto-posting" and "Full Context feed" sections.

### Search & metadata quality

- **`[IMPROVEMENT-ROUND]` Full Context entries drop `line`/`version` from the pasted share link — only `t` is kept.**
  - **Issue**: WO-943's editor form parses a pasted "Share video at M:SS"
    link's `slug` and `t`, but reads and discards any `line`/`version`
    params the link also carries.
  - **Impact**: arriving at a meeting from a Full Context entry never
    highlights the matching transcript row, unlike a plain deep link
    copied with a transcript line selected — the video still seeks to
    `t`, but the transcript-side highlight is silently lost.
  - **Next action**: extend `ContextEntry` (or `context_links.py`'s
    parse) to also store `line`/`version` when present, and pass them
    through to the `/m/{slug}` deep link the feed renders.
  - **Constraint**: not started — `t_seconds` is the only timestamp field
    on `ContextEntry` today; adding `line`/`version` is a small schema
    change (nullable columns), not a redesign.
  - **History**: `BACKLOG_DONE.md`'s WO-943 entry.

### Transcription quality & cost

- **[IMPROVEMENT-ROUND] `[BIG]` Split speakers by voice (diarization) in our own Whisper transcripts.**
  - **Issue**: our own Whisper transcripts carry no speaker. Diarization means splitting the audio by voice into "Speaker 1", "Speaker 2". Since WO-1967 (PR #2086) the page and the `.txt` download show `TranscriptSegment.speaker` where it changes, but only source captions with WebVTT voice tags fill it.
  - **Impact**: a quote with no speaker is weaker for a journalist than "Councilmember X said".
  - **Next action**: **Claimed 2026-10-16** (conductor thread, A14): Ryan likes it. Next step is a one-meeting cost test on the office Mac (time and memory for one diarization pass). It follows A5, keeping station speaker names (WO-1967, merged 2026-10-16).
  - **Constraint**: ship unnamed "Speaker 1 / Speaker 2" first; mapping to real names is the harder, later half. Size the compute before committing. WhisperX builds diarization on the same faster-whisper model through `pyannote.audio`. Any change to the worker must be checked against `scripts/transcribe_backlog_locally.py` too (two transcription paths).
  - **History**: moved from `CLAUDE_BACKLOG.md` 2026-10-16 (proposed 2026-08-09); WO-1967 in `BACKLOG_DONE.md`.

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

### Email, ops tooling & internal reporting

- **[IMPROVEMENT-ROUND] Point the ops email defaults at `ally@redtaperecordings.com`.**
  - **Issue**: code defaults still send to `ryan@how-to-adu.com`: `app/main.py:2367` and `scripts/daily_report.py:50` (`DAILY_REPORT_EMAIL_TO`), `scripts/fetch_youtube_transcripts.py:165` (`YOUTUBE_FETCH_REPORT_EMAIL`), `archive/utils/email.py:402` (`TRANSCRIPTION_FAILURE_ALERT_EMAIL`). `RESEND_REPLY_TO_ADDRESS` is set in Render.
  - **Impact**: ops digests and reply/failure mail land at the old address.
  - **Next action**: change the four defaults and the `render.yaml` comment; Ryan sets `RESEND_REPLY_TO_ADDRESS` (and any explicit overrides) in Render on both workers.
  - **Constraint**: `ryan@ally.redtaperecordings.com` is the Resend *sending* subdomain, not the inbox; confirm `ally@` receives mail before switching.
  - **History**: decided 2026-08-22 (`BACKLOG_DONE.md`).

- **[IMPROVEMENT-ROUND] Add two missing metrics to the daily worker report.**
  - **Issue**: the daily worker report (`GET /internal/send-worker-daily-report`) lacks "jobs failed in the last 48h" and "total meetings on the site". The 6-hourly cadence from the 2026-08-16 request was not reaffirmed.
  - **Impact**: the operator can't see failure spikes or corpus size from the report.
  - **Next action**: add both to the existing report. Count failures by `TranscriptionJob.created_at` (no `failed_at` column) and say so in the label; use `_has_good_transcript()` for any with/without-transcript split.
  - **History**: daily report build in `BACKLOG_DONE.md`.

### YouTube channels the access ladder found for 5,000+ governments are recorded but not confirmed as meeting channels `[IMPROVEMENT-ROUND]`

- **Issue:** WO-1077 (2026-09-25) recorded 105 YouTube channels as `suspected_video_provider=youtube` in `jurisdiction_coverage.csv` because the government's own page ties the channel to its meetings ("Watch Commission meetings", a Video column in a meetings table). Nobody opened the channels: this Mac is not the drip Mac. Another 197 found channels sit only behind a footer icon ("likely own general channel") and were not recorded.
- **Impact:** about 300 larger governments may already have meeting video on YouTube with no Archive page.
- **Next action:** hand the 105 recorded channels, then the 197 icon-only ones, to the drip Mac (`scripts/youtube_drip.py`) for a channel listing check; the list, with the page evidence for each, is `rtr-business/research/wo1077_passA_results.csv` (verdict column).
- **Constraint:** YouTube is fetched only by the drip Mac (`docs/YOUTUBE_DRIP_RUNBOOK.md`).
- **History:** `BACKLOG_DONE.md` WO-1077.

### 37 of the 212 dead government addresses over 5,000 people were not repaired `[IMPROVEMENT-ROUND]`

- **Issue:** WO-1077 repaired 175 `dns-unresolvable` rows (www/http forms, alternate domains, CISA's .gov list, state directories, all hand-confirmed). Not repaired: 14 not found, 16 behind a human-verification wall (Cloudflare or SiteGround's "sgcaptcha"), 6 where the proposed site was wrong or unclear (Columbia MS is a hacked WordPress site; Newburyport MA's homepage carries unrelated Mexican ID-verification text; Scioto County OH got Scioto Township; Polk County GA got a parked domain; Dallas County MO got the Buffalo chamber of commerce; Monmouth OR is walled), plus Greene County TN, whose only working site is a WP Engine staging host.
- **Impact:** these keep `reject_reason=dns-unresolvable`, which is wrong for some: Vermont counties (Chittenden, Orange) have no county board, and six Oklahoma counties (Stephens, Garvin, Caddo, Pushmataha, Murray, Cotton) publish only through local newspapers.
- **Next action:** give those eight a reason that says so (ENUMERATION_METHODS.md section 23 has no bucket yet; propose `no-county-government` and `no-official-website`), and recheck Pontotoc County MS and Pontotoc MS, whose sites were down together at one host that evening.
- **Constraint:** never try to get past the walls.
- **History:** `BACKLOG_DONE.md` WO-1077; per-government results in `rtr-business/research/wo1077_passB_results.csv`.

### Tier 1.5: show a transcript that has no timestamps `[IMPROVEMENT-ROUND]`

- **Issue:** Our tiers assume a transcript has times (tier 1 source captions, tier 3 our Whisper). Some sources publish a transcript without times, such as SparQ's public HTML minutes (`/Public/Minutes/`).
- **Impact:** Such text is real content, but today it has no home on a meeting page. A reader could read it, though not jump to a moment.
- **Next action:** Decide whether it earns a tier of its own (working name tier 1.5, "source transcript, no times") and what a page shows when there are no clickable jumps. An agenda without item times is a separate flag, not a tier: agendas already display as a link.
- **Constraint:** Ryan 2026-10-14: show an agenda whenever one exists, with no clickable jumps when it has no times.

## Dormant — needs a real example first `[LATER]`

### Granicus `TranscriptViewer.php` as a transcript fallback: wait for a tenant that runs Granicus captioning `[LATER]` `[EXAMPLE]`

- **Issue**: `https://<tenant>.granicus.com/TranscriptViewer.php?clip_id=N&view_id=V` shows a meeting's closed captions as plain text with `>>` speaker marks and no timestamps. South San Francisco clip 1966 had 32,715 characters there while its player page linked no caption file, so the resolver found no transcript.
- **Impact**: 0 of 30 clips on 14 tenants in the 2026-10-07 pilot had a real transcript (all under 1,400 characters, no `>>`): 6 blank, 5 HTTP 500, 19 agenda or title only. Only the hand-found South San Francisco control passed. 14 of 15 host robots.txt files say Disallow all, so the fallback would read pages those hosts ask automated clients to skip.
- **Next action**: find tenants that run Granicus captioning (what marks them on the player page is unknown) and re-test. If several pass, build about 40 lines in `granicus.py`'s caption branch: one capped read (`read_capped_text`) when no caption file exists, a "real transcript" test (at least 2,000 characters, no "$Title" template, at least 3 `>>`), and the existing untimed path (`TranscriptSegment(start=0, end=0)` lines) with a distinct warning marker added to `archive/db/crud.py`'s marker list.
- **Constraint**: needs Ryan's yes on reading these pages (robots.txt); a pilot needs 10 s per host and the generic User-Agent. Build tests from real pages, not synthetic ones.
- **History**: pilot sample, results and saved pages are in `~/Documents/rtr-findmeeting/data/granicus_transcriptviewer_pilot_2026-10-07/` (not in this repo).

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

### PrimeGov has a real, structured `committeeId` field — but no confirmed way to turn it into a name `[NEEDS-AUDIT]`

- **Issue**: found live 2026-09-20, following up on the meeting_body investigation. PrimeGov's own `api/v2/PublicPortal/ListArchivedMeetings?year={YYYY}` endpoint (already used by `primegov.py` for Swagit/Granicus video delegation, see that file's module docstring) returns a real `committeeId` integer on every meeting (confirmed live on cambridgema, baycountyfl, and slc — distinct ids per tenant, e.g. `1`/`3`/`5`), separate from the meeting's own `title`. This is a genuinely different shape from Cablecast's write-off (a bare id with truly nothing else to check) — but no committee-name lookup has been found yet either: `ListCommittees`/`Committees`/`ListMeetingTypes`/`MeetingTypes` all 404 on the tenant's own API host, and the public `Portal`/`Portal/Meeting?meetingTemplateId=...` pages (confirmed real, server-rendered, hundreds of KB) carry no embedded id-to-name mapping anywhere in their markup or inline scripts.
- **Impact**: unclear whether real — could be a genuinely missing lookup (in which case this joins the Standing Decision write-off list), or a real endpoint this session's plain-HTTP guessing just didn't find (PrimeGov's `Portal` page is a real app, not an empty shell — the name mapping most plausibly loads via an XHR call from its own JS after page load, which a plain `aiohttp` fetch can't see).
- **Next action**: the fastest real answer is a human (or a headless browser) watching the Network tab while `Portal/Meeting?meetingTemplateId=...` loads in an actual browser, looking for the request that supplies a committee name — rtr-discovery's FINDING-14 already flags this machine's own playwright/headless setup as blocked by a CPU-architecture mismatch, so this may need a different machine or a human to check. Confirm on at least 2 tenants before trusting whatever's found (this repo's own "one platform's file is not enough" rule).
- **Constraint**: don't guess a REST path further without narrowing it from real traffic first — four guesses already 404'd, and PrimeGov's actual route naming isn't a fully predictable pattern from what's confirmed so far.
- **History**: this repo's own `primegov.py` module docstring (the existing `ListArchivedMeetings`/`GetArchivedMeetingYears` API usage this finding builds on); `tests/test_primegov.py`'s real sample URLs (cambridgema, baycountyfl, slc, okc, toaks, lacity) used to check this live.

### 101 West Virginia towns still have a placeholder (`local.wv.gov`) or blank website `[LATER]`
- **Issue**: 103 WV `us:place`/`us:cousub` rows had no real site (57 `local.wv.gov`, 46 blank). WO-360's walk of the 55 county sites found real sites for only 2 (Ansted, Mount Hope).
- **Impact**: a sweep cannot tell which government a `local.wv.gov` page belongs to, so these 101 stay uncovered.
- **Next action**: try the WV Municipal League member directory (unverified) or a per-town search. A person confirms each match.
- **Constraint**: do not automate the confirmation; same-named towns in other states are a known trap.
- **History**: `BACKLOG_DONE.md` WO-337, WO-360; `rtr-business/research/wo360_*.csv`.

### [HUMAN] Farmington city, MO: Ryan saw 16 real agenda PDFs on `/city-council` that neither a plain fetch nor a real browser can reproduce

- **Issue**: Ryan reported 16 agenda PDFs (01-08-2026 through
  09-10-2026) on Farmington, MO's `/city-council` page. WO-226's
  conductor could not reproduce this in a plain fetch OR a real
  headless browser -- www and non-www both return an identical
  155,691-byte Duda page with no agenda text, no PDF links, and no
  iframe. The only outbound channels found are
  `facebook.com/CityofFarmington` (the city) and the county library's
  YouTube channel -- no video source reachable either way.
- **Impact**: a real government with real agendas Ryan has seen
  firsthand reads as `meeting-without-video` with no path to ingest,
  and it's not clear whether the site changed, the PDFs live behind a
  login/different URL, or something else is blocking both check
  methods.
- **Next action**: ask Ryan for one real agenda PDF URL from what he
  saw -- that single URL would show whether it's a different path (a
  Duda-hosted `#!` fragment page, a document library subdomain the
  crawl never found) or something session-gated.
- **History**: `BACKLOG_DONE.md`'s WO-226 entry, 2026-09-11.

### [NEEDS-AUDIT] A real platform adapter's OWN aiohttp session still hits the missing-intermediate-certificate gap WO-1145 fixed for `fetch.py` — confirmed live on the same 6 governments' own linked video files

- **Issue**: WO-1145 fixed `fetch.py`'s own `Fetcher` (Start/Identify/List/Scan/Hop) to verify certificates through `truststore`, so all 6 of WO-1134's flagged `site-broken` governments now load past Start. But Resolve calls each candidate's own platform adapter (`app/platforms/*.py`, e.g. a direct-file finder), which opens its OWN `aiohttp.ClientSession` — untouched by WO-1145 on purpose, since those adapters are shared with the cloud worker and resolver, not Meeting-Finder-only. Confirmed live in WO-1145's own re-run: `vercounty.org`'s `wp-content/plugins/easy-video-player/lib/blank.mp4` and `desmet.k12.sd.us`'s `videos/cheer.mp4`/`videos/homecoming2.mp4`/`videos/De-Smet-2021-22.mp4` all failed resolve with the identical `SSLCertVerificationError: unable to get local issuer certificate` on the SAME host WO-1145 just fixed for page-fetching.
- **Impact**: narrower than it sounds — both real cases found so far are YouTube-lead-only outcomes anyway (no real non-YouTube video was lost), and it's unconfirmed whether a real, working, non-YouTube video is currently being missed by this gap anywhere. But the underlying gap is real and will misreport a genuinely-fine direct-file/video URL as broken whenever a candidate's own host has this certificate shape.
- **Next action**: once a real case turns up where this gap actually costs a real find (not just a YouTube-lead-only outcome that would've gone to the drip either way), decide whether to extend `truststore` verification to the specific adapter(s) involved — same live-verify-first discipline as WO-1145 (confirm the failure, confirm truststore fixes it, confirm a genuinely bad cert still fails) — or whether it's narrow enough to fix per-adapter as each case appears.
- **Constraint**: any fix here touches a platform adapter shared with the cloud worker, not just Meeting Finder — read CLAUDE.md's media-extraction-sharing rule (the one about `scripts/transcribe_backlog_locally.py` vs `worker/main.py`) before assuming a fix in one place reaches the other.
- **History**: found live verifying WO-1145, 2026-09-27; see `BACKLOG_DONE.md`'s WO-1145 entry.

### [NEEDS-AUDIT] The new body-name/government-TYPE filter (WO-1078) misses 22 of 44 real wrong-government finds — no recognizable body phrase, or a deliberately excluded ambiguous one

- **Issue**: WO-1078's own re-check of the 2026-09-26 hand-check's 44 real other-government rows caught 22 (50%). The other 22 either name no body phrase `app/utils/gov_body_types.py`'s table recognizes at all ("Committee on Administration Finance and Law", "BCC Budget Public Hearing", "MTG-PZC-2026-09-21", several blank titles), or use a phrase deliberately excluded as ambiguous (Zoning Board of Appeals, Board of Finance, Board of Appeals, "Historic District Commission").
- **Impact**: these 22 still come back as a wrong find with no lead recorded, same as before this WO — no regression, but no improvement either. A human hand-check is still the only backstop for them.
- **Next action**: once more real examples of each miss shape accumulate (this repo's own "verify against real data" rule — a table built from 1-2 examples risks a wrong generalization, e.g. "BCC" could mean things other than Board of County Commissioners elsewhere), add narrowly-scoped phrases/rules for the ones that repeat. Not urgent: `[LATER]`-shaped, waiting on volume.
- **Constraint**: don't widen the ambiguous exclusions (Zoning Board of Appeals, Board of Finance, Finance Committee, bare Board of Trustees, Planning Commission) without a real, confirmed case — they were excluded specifically because they can name either a school district's own body or a different government's, per Ryan's 2026-09-26 brief.
- **History**: found building and verifying WO-1078, 2026-09-26; see `BACKLOG_DONE.md`'s WO-1078 entry for the full before/after tables.

### [NEEDS-AUDIT] `pick.filter_candidates_to_government()`'s place-name match still misses a government's own meeting when its title abbreviates the place name

- **Issue**: WO-1058's live re-run (80 governments, 2026-09-25) found one residual false positive: Elizabeth City NC's own Vimeo hub lists a real meeting titled "City of EC Council Sept 14 2026 Part 2" — "EC" is the government's own name abbreviated, but `_place_core()` reduces it to the literal core `"ec"`, which doesn't match `_place_core("Elizabeth City")` -> `"elizabeth"`, so the filter treats it as a different government's meeting.
- **Impact**: net still an improvement, not a regression — before WO-1058 this government reported `hub-carries-other-governments-not-this-one` with zero candidates; after, it reports the same outcome but WITH a real candidate kept as a low-confidence lead (`handcheck_lead=yes`, a real video URL), so a human reviewing it will very likely approve it as-is. But it isn't a clean find, and any other government whose own meetings are titled with an initialism/abbreviation of its name hits the same gap.
- **Next action**: teach `_place_core()`/`filter_candidates_to_government()` to also accept a title phrase that is a plausible initialism of `gov_name` (e.g. first letters of each word) before treating it as a different place — check a few more real examples first (this WO's own convention) rather than guessing the matching rule from one case.
- **Constraint**: don't loosen the match so far that it stops catching a real different government whose name happens to share initials (e.g. "EC" could also be "Essex County") — needs a real second example before deciding how loose to make it.
- **History**: found live verifying WO-1058's 80-government re-run, 2026-09-25; see `BACKLOG_DONE.md`'s WO-1058 entry.

### [NEEDS-AUDIT] `detect_platform()`/`parse_vimeo_video()` never recognizes a Vimeo "Event" (livestream) URL — never resolvable today, by design, not just unbuilt

- **Issue**: `app/platforms/vimeo.py`'s `parse_vimeo_video()` explicitly, by design, never matches a `/event/{id}` URL ("a different id space that `player.vimeo.com/video/{id}` does not accept" — its own docstring), and `is_vimeo_listing()` doesn't match it either, so `detect_platform()` returns `"unknown"` for it. That's correct for a LIVE stream (it's either live right now or it's nothing — WO-1046, 2026-09-24, made this explicit: Hop no longer even offers one as a hop candidate). The open question is narrower than the original framing here suggested: does a Vimeo Event page also expose a VOD replay link/API worth resolving once the event ends?
- **Impact**: corrected 2026-09-24 (WO-1046) — this entry previously implied Suffolk County NY (`us:county:36103`) was stuck reporting `youtube-lead-only` because of this gap. That's no longer true: Suffolk's real answer was never the Event embed, it was the 14 real `vimeo.com/showcase/{id}/embed` archives on the SAME page (already parseable before this entry was filed) — a separate resolve-time bug (source-url tracking + a hop/scan dedup race, both fixed in WO-1046) was what actually blocked them. Suffolk now resolves to `embed-restricted` (a confirmed real meeting, domain-restricted by its owner — see `BACKLOG_DONE.md`'s WO-1046 entry). The live-event-VOD question itself remains genuinely open, but no known real government is currently blocked on it.
- **Next action**: only worth building if a real government surfaces whose ONLY video is behind a Vimeo Event's own VOD replay (none confirmed as of 2026-09-24) — confirm what that page's own HTML/API offers on 2-3 real examples first, per the "test against a real URL first" rule.
- **Constraint**: resolver-level (`app/platforms/vimeo.py`/`base.py`), not a Hop/Scan link-ranking bug.
- **History**: found live verifying WO-1044's Suffolk County NY fix; narrowed and Suffolk's own resolve unblocked in WO-1046 — see `BACKLOG_DONE.md`'s WO-1044 and WO-1046 entries.

### [NEEDS-AUDIT] Jefferson County WA's real CivicPlus video is one hop deeper than any listing walker reaches — inside an individual row's own agenda/minutes document, not a `td.media` link

- **Issue**: WO-341 (2026-09-13) confirmed live: `www.co.jefferson.wa.us/AgendaCenter` has 15 real (title+date) rows, none with a `td.media` video link — `_civicplus_walker()`'s own nav-link scan and `Calendar.aspx?EID=` walk (built this WO) both come back empty too, since neither the confirmed page nor its nav links nor its newest calendar events carry a recognizable vendor link. WO-333's own investigation doc already named the real vendor as "a direct file," reachable only by opening an individual row's agenda/minutes PDF and finding a link inside it — not built this WO (a single-tenant PDF-drilling feature, not a generalizable pattern across the 3 real tenants a listing walker was built from).
- **Impact**: Jefferson County WA (`us:county:53031`) stays a confident tier-4 "meeting found, no video" rather than reaching the real video that exists — one government, not surveyed for prevalence elsewhere.
- **Next action**: once a second real CivicPlus tenant shows the same "video only inside an agenda PDF" shape, build a bounded PDF-link-scan step (open the row's own `agenda_link`, regex-scan for a recognized vendor URL) — one sample isn't enough to generalize from yet, per `CLAUDE.md`'s adapter-building rule.
- **Constraint**: don't build a PDF-fetching step from this one tenant alone — real cost (PDF fetch + parse per row) for an unconfirmed-common shape.
- **History**: `docs/investigations/wo333_verification_walk.md` ("CivicPlus, video one hop deeper"), `BACKLOG_DONE.md`'s WO-341 entry.

### [NEEDS-AUDIT] A real ProudCity or viebit tenant page named "watch live"/"video archive"/a folder listing can exist and still make the adapter extract nothing at all — two confirmed real examples, cause not yet read

- **Issue**: `holyoke.org/live-stream-video-archive/` and `holyoke.org/departments/city-council/` return no title, video or agenda from `proudcity.py`. Not known whether the pages embed a video the adapter misses.
- **Impact**: unknown; one example.
- **Next action**: fetch both pages once by hand; if either embeds a playable video, widen `proudcity.py` for that shape.
- **History**: `docs/investigations/passive_discovery_phase3b.md` (WO-281). The Viebit `?folder=ALL` half is dropped: no Viebit meeting can be transcribed (Standing decision).

### [NEEDS-AUDIT] A Google Drive FOLDER listing (as opposed to a single file's view page) still has no adapter — Walbridge village, OH's real "Meeting Recordings" folder cannot be enumerated

- **Issue**: WO-303 (2026-09-12) built `app/platforms/direct_file.py`, closing the two gaps this entry used to describe (a bare video file on a government's own domain/Dropbox, and a Google Drive single-FILE view link — confirmed live that `&confirm=t` bypasses Drive's virus-scan interstitial with no sign-in, against both of Kemmerer city WY's real files). What's left: Walbridge village, OH's real Drive folder (`drive.google.com/drive/folders/...`, named "Meeting Recordings" alongside its Agendas/Minutes/Packets folders) renders its contents via JavaScript — confirmed live, a plain HTTP fetch of the folder page returns no enumerable file list, only a client-rendered shell.
- **Impact**: one real, confirmed government (Walbridge, OH) has evidence of real recordings that cannot be found without enumerating the folder first — the single-file adapter above has nothing to resolve until an individual file URL is known.
- **Next action**: either a headless-browser fetch of the folder page (same tool this repo already uses for other JS-rendered listings) or Google Drive's own (unauthenticated, for a public folder) API `files.list` endpoint, to enumerate the folder's real file ids, then hand each one to `direct_file.py`'s existing single-file resolve.
- **Constraint**: a public Drive folder's API access shape hasn't been confirmed live yet — check whether an unauthenticated `files.list` call actually works for a public folder before assuming it does, per this repo's own "test against a real URL first" rule.
- **History**: `BACKLOG_DONE.md`'s WO-264 and WO-303 entries; `rtr-business/research/ENUMERATION_METHODS.md` §303/§308.

### [NEEDS-AUDIT] `[WAIT]` Palm Beach County, FL's real Granicus tenant carries only internal Legistar-migration training calls, and its real target (Legistar) shows zero meetings — worth a recheck once the migration finishes

- **Issue**: `pbc.granicus.com` carries only Legistar-migration training calls (re-checked 2026-09-28, pin note). `pbc.legistar.com` showed 0 meetings.
- **Next action**: re-check `pbc.legistar.com/Calendar.aspx` when someone is next working on Legistar; see also the Palm Beach SharePoint entry (line 5905).
- **Constraint**: never ingest the training calls.
- **History**: `BACKLOG_DONE.md` WO-260.

### [NEEDS-AUDIT] South Bay, FL is the real example an earlier Dormant entry was waiting for: a BoxCast government only reachable via a per-meeting pseudo-channel on a SHARED account, so its own safe pin can't fire

- **Issue**: confirmed live 2026-09-12 (WO-245) while fixing the separate per-broadcast `external_id` bug: South Bay, FL's BoxCast account (`nqkdxkaoowxb8iyvornm`, "Primestar Digital Network - PALM SPRINGS, fl") is a SHARED regional vendor account also carrying at least seven other real Florida governments' own meetings (Boynton Beach, Boynton Beach CRA, Belle Glade, Clewiston, Pahokee, Mangonia Park, Delray Beach — confirmed by reading the account's own `GET /channels/{channel}/broadcasts` listing). South Bay's own distinct channel (`kddihfjxfiskfydfkwgy`, carrying only its own meetings, found on the city's site) has a correct, safe pin in `tenant_overrides.csv`. But the real page (8903) was ingested from a direct `boxcast.tv/view/{broadcast}` link, and `boxcast.py`'s `channel_hint` is only ever populated when the ORIGINAL url was itself a `/channel/{id}` scan — a direct `/view/` link never is, so the adapter has no way to discover South Bay's distinct channel from that URL alone, and its `video_channel` instead falls back to the shared account's own channel (confirmed by a real, read-only resolve: `boxcast:nvot5avtqaaljac4xhxt`). This is exactly the shape the earlier WO-227b Dormant entry on this subject ("A BoxCast government reached only via a fresh per-meeting pseudo-channel on a SHARED account") was waiting for a real example of.
- **Impact**: contained today — WO-245 deliberately did NOT widen South Bay's pin to the shared account channel (that would misattribute the other seven governments' broadcasts to South Bay the moment any of their own `/view/` links got ingested the same way). So the existing safe pin simply never fires for page 8903 or any future South Bay page ingested the same way; South Bay's identity still comes from the explicit `gov_id` every ingest payload now carries (CLAUDE.md's rule), not from this pin. No misattribution has happened.
- **Next action**: no fix without a second signal. Two real options, neither built: (a) teach the adapter to read the account's own broadcast listing at resolve time and cross-check whether it looks single- or multi-tenant (the same check this WO did by hand for Primestar, Mt. Blue Television and Media Mike), trusting `account.channel_id` only when it does; or (b) maintain a small hand-verified map (shared account id -> known distinct per-government channel ids), consulted when `distinct_channel` is None but the account is known-shared. Either needs at least one more confirmed shared-account case before shipping, per CLAUDE.md's "never build from one example" rule for a fix this shape.
- **Constraint**: never widen a `tenant_overrides.csv` boxcast pin to an account-level channel without first confirming via the account's own broadcast listing that it is single-tenant — this is exactly what caught Primestar. Don't re-pin South Bay to the shared channel as a workaround.
- **History**: `BACKLOG_DONE.md`'s WO-227b entry (the original Dormant version of this question, now superseded by this entry) and WO-245 entry; `app/platforms/boxcast.py`'s "An account can be a shared regional media operator" docstring section.

### [NEEDS-AUDIT] No adapter for a meeting recording pointing at a general-purpose file host (Google Drive, Dropbox, SoundCloud) — 87 real, confirmed-populated examples now, from two independent sources

- **Issue**: Google Drive and Dropbox single files now resolve through `direct_file` (#1409, #1429). Only SoundCloud is left: 7 Utah PMN "Audio File Location" links.
- **Next action**: wait for a non-Utah SoundCloud example before building. Samples are in `rtr-business/research/pmn_utah_pilot_log.csv`.
- **History**: Utah PMN pilot 2026-09-08; WO-197 widened it to Drive and Dropbox, which are now resolved.

### [NEEDS-AUDIT] Garbled source transcripts still produce garbled highlight snippets

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

### `[LATER]` ~25 smaller consolidated city-county governments still need a real domain

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

### [NEEDS-AUDIT] Vimeo Whisper-fallback audio: unverified whether the headless route reaches the media file

- **Issue**: The captions half of this entry is solved: since 2026-08-31
  (PR #643) `app/platforms/vimeo.py` reads the signed caption URL from
  the player page in the headless browser (re-confirmed 2026-09-23:
  Salisbury NC `player.vimeo.com/video/1223368476`, 1,336 caption
  segments). What is not known is whether a Vimeo video WITHOUT
  captions can get an on-demand Whisper transcript: the real progressive
  media file sits in `player.vimeo.com/video/{id}/config`, which 403s
  plain clients, and nobody has checked whether the headless route (or a
  `.m3u8` from the player) gives the worker usable audio.
- **Impact**: Vimeo meetings with no captions stay video-only, with the
  existing reader-facing warning.
- **Next action**: find a real captionless Vimeo meeting and try the
  headless route for its media URL, then `media_probe.py`'s extraction.
- **Constraint**: never attempt to auto-solve a Cloudflare challenge
  (see Standing decisions).
- **History**: `BACKLOG_DONE.md` (residual of WO-29); captions half
  closed by PR #643 (2026-08-31); entry narrowed 2026-09-23.

### [JUST-DO-IT] City-YouTube-channel fallback: duplicate-posted meetings decline instead of resolving

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

### [LATER] `[EXAMPLE]` Town Hall Streams: transcript endpoint unconfirmed-positive; 88-id Wayback population uningested

- **Issue**: the transcript AJAX endpoint is empty on all 7 real
  samples checked, so no confirmed response format exists —
  `townhallstreams.py` deliberately doesn't parse a non-empty response.
- **Impact**: no transcripts for this platform yet.
- **Next action**: find a real sample with a non-empty transcript AJAX
  response to confirm the format. Separately, a Wayback CDX scan
  already surfaced 88 distinct `location_id` values (range 28–175) as
  a cheap population to walk and bulk-ingest — not yet done.
- **History**: `BACKLOG_DONE.md` (townhallstreams.com adapter build).

### [LATER] `[EXAMPLE]` SuiteOne Media: dead CDX leads and unconfirmed PDF-transcript fallback

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

### [NEEDS-AUDIT] `direct_file.py`'s Google Drive `&confirm=t` bypass doesn't always work — a real, hand-confirmed meeting recording on Alamosa County CO's AgendaCenter still fails `ffprobe`

- **Issue**: found live 2026-09-13/14 (WO-352). BACKLOG_DONE's WO-303 entry confirmed `&confirm=t` bypasses Drive's virus-scan interstitial against Kemmerer city WY's two real files. Alamosa County, CO's own AgendaCenter "Board of County Commissioners Agenda 9-9" row (2026-09-09) links a real Drive file — the share page's own title ("September 9 2026") and the agenda row's `aria-label` both confirm it's the real meeting recording — but `_resolve_direct_media_url()`'s resolved download URL (`drive.usercontent.google.com/download?id=...&export=download&confirm=t`) still returns something `ffprobe` reports as "Invalid data found when processing input", not a real stream.
- **Impact**: at least one real, hand-confirmed government recording can't be queued. Unknown how many more of the ~200 `drive.google.com` candidates already pinned/queued across the corpus hit the same gap — this is one data point, not a sample.
- **Next action**: fetch the resolved download URL's first response bytes directly (a ranged GET, not ffprobe) to see what's actually being served — a second virus-scan/quota interstitial the current `confirm=t` doesn't clear, a large-file warning page, or a permissions gate. Compare against Kemmerer's two working files (same code path) to find what differs.
- **Constraint**: one real example — don't generalize a fix from it alone; find at least one more failing Drive candidate before changing `_resolve_direct_media_url()`.
- **History**: `BACKLOG_DONE.md`, WO-352, 2026-09-13/14.

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

### SparQ Meetings adapter: agenda pages, six hosts and per-organization pins `[PARK]` `[BIG]`

- **Issue:** SparQ Meetings (also BOEconnect, Assemble Meetings, BoardBook, Keystone Agenda, KASB: one database, six host names) holds agendas and minutes only, no video of its own. A pasted SparQ link resolves as `platform=unknown`, and the six hosts are not in `MULTI_GOV_HOSTS`, so a blank-match pin on any of them would mis-file thousands of meetings.
- **Impact:** About 1,350 matched governments with 0 Archive pages would gain agenda facts; only about 75 have a video link, and those are already in the drip. Agenda-only pages are never ingested (Ryan's rule).
- **Next action:** When picked up, read `ADAPTER_SCOPE.md` in rtr-business `research/boeconnect_2026-10-12/`: build the adapter, register the six hosts in `MULTI_GOV_HOSTS` and `tenant_key.py`, and add about 1,600 per-organization pin rows (skip the 307 duplicate org ids). Canonical host `meeting.sparqdata.com`. About 1.5 days.
- **Constraint:** Parked by Ryan 2026-10-14: the coverage outcome (video leads in the drip, the rest marked `meeting-without-video`) is already done without it. Agenda list stays as a link only, no per-item times. Minutes are linked, not parsed.
- **History:** `ENUMERATION_METHODS.md` §402 (rtr-business); 163 governments marked and 158 relabelled `meeting-without-video` on 2026-10-13/14.

### `[LATER]` Mastodon auto-posting has made zero real posts

- **Issue**: no Mastodon account exists yet, so the Mastodon client is
  schema-verified but not content-verified.
- **Impact**: Mastodon announcements aren't confirmed to work at all,
  unlike Bluesky (live since 2026-08-21 — a real prod resolve created a
  page and the account made its first real post, confirmed by Ryan).
- **Next action**: create the account + token, then watch one real post go
  through — the same bar Bluesky already cleared.
- **History**: Bluesky auto-posting build in `BACKLOG_DONE.md`.
