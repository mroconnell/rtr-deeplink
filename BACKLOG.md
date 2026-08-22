# Backlog

**Open items only.** Completed work — including the investigation detail
behind each fix — lives in [BACKLOG_DONE.md](BACKLOG_DONE.md); entries
below link back to it for context. Ideas nobody has triaged yet live in
`CLAUDE_BACKLOG.md`, and the daily Routine's unreviewed findings live in
`CLAUDE_INBOX_TRIAGE.md` — neither is this file.

**Sections are ordered by actionability, not by subsystem.** Subsystem
buckets were what this file used until 2026-08-21, and they failed
measurably: four of them grew past a thousand lines each, mixed open bugs
with finished work and research notes, and hid three real user-visible
bugs near the bottom until an audit went looking. Actionability bounds
each section by a natural mechanism instead — "Ship next" stays short
because items leave it when they ship, "Needs a human" drains, and
"Dormant" is explicitly allowed to be long *and* explicitly skippable.

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
   purpose: this work used to be split across five places and read worse
   for it. Its `[JUST-DO-IT]`/`[HUMAN]`/`[NEEDS-AUDIT]` items keep their
   tags inline rather than being hoisted into sections 2-4.
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

## Standing decisions — do NOT re-raise

Decisions already made *against* doing something. Each was reached with
the tradeoff understood, and each has been (or is likely to be)
rediscovered by a later session that reads only the surrounding evidence.
Collected here in 2026-08-21 from depths of 500 to 4,900 lines in the old
structure, where they were effectively unfindable. **Read this section
before "fixing" anything it names.**

### Do NOT widen `noindex` / the sitemap filter / the `/j/*` hub filter to cover `best_effort`

**Explicitly NOT to be "fixed" by a later session**: the `noindex`
condition (`archive/templates/meeting_page.html`), the sitemap filter
(`crud.list_all_page_slugs()`) and the `/j/*` hub filter
(`crud._hub_base_conditions()`) were all left untouched on purpose, by
the user's own product decision — they want unverified pages *stopped
from being amplified* (the social gate) and *auditable* (the queue), but
still indexed. Most `best_effort` pages are legitimate small cities that
merely happened to resolve via the fallback rather than a vendor
adapter, and pulling them out of Google would cost real reach for no
proportionate trust gain. Widening any of those three to include
`best_effort` would reverse a decision that was made deliberately, with
the tradeoff understood.

### `ALERT_WEBHOOK_URL`

**`ALERT_WEBHOOK_URL` repo secret — DECLINED 2026-08-21, deliberately.
Don't re-raise this as an open gap.** Ryan's call, stated directly: he
doesn't use Slack or Discord, so a webhook that posts into a channel
nobody watches adds nothing over GitHub's own failed-scheduled-workflow
email, which already reaches him. The `if: failure()` step in all three
cron workflows (daily-report, send-search-alerts, adapter-canary) stays
as-is — it no-ops with a `::warning::` when the secret is unset, which
is the intended behavior, not a defect.

Recorded because the evidence for it looks stronger than it is, and a
future session will likely rediscover it and want to "fix" it: the
adapter canary's only failure in its visible run history (run
32155218602, 2026-08-18) logged `19/20 platforms OK` / `FAIL aurora:
resolve returned no real content`, then `##[warning]Adapter canary
failed and ALERT_WEBHOOK_URL isn't set`. It passed again 08-19 with no
code change — a transient auroratv.org blip. Note what actually
happened there: GitHub's email *did* fire, and the failure *was*
diagnosable from logs afterward. The webhook would have changed the
delivery channel, not the outcome.

**If email alerting is ever genuinely wanted**, the honest answer is
it'd mean wiring Resend credentials into GitHub Actions purely to
duplicate a notification GitHub already sends — not worth it. Revisit
only if Ryan starts using a chat tool day-to-day.

### The inbox-triage Routine holds no Gmail write scope — don't propose reauthorizing it

Ryan's explicit, permanent decision (WO-33, 2026-08-21): an unattended
job that merges its own PRs shouldn't also be able to write to his
mailbox. `label_thread` and the old `label:rtr-claude
-label:rtr-claude-processed` query are gone for good, replaced by the
repo-side `CLAUDE_INBOX_TRIAGE_SEEN.txt` ledger. Full reasoning in
`CLAUDE.md`'s `CLAUDE_INBOX_TRIAGE.md` bullet.

### On-demand transcription's email-only gate

**On-demand transcription's email-only gate is a deliberate middle path,
not a stepping-stone toward eventually requiring a full account —
explicit user correction, 2026-08-12.** Transcription is still the app's
single most cost-intensive feature by a wide margin (the real dollar/compute
figures are in `BACKLOG_DONE.md`'s worker plan-sizing entry), and email
confirmation was chosen specifically as real friction against abuse
without forcing a login onto the app's costliest path. Keep it this way
going forward rather than treating it as an implicit TODO to fully
account-gate later.

### PrimeGov's private known-domain override

**PrimeGov's private known-domain override can be absorbed into the
enricher once the registry-in-enricher design ships — but leave it
alone until then.** `primegov.py`'s `resolve()` calls
`jurisdiction_enrich.known_jurisdiction_display()` before its own
`_extract_jurisdiction()` — the only adapter with this plumbing, added
for the confirmed-misleading `slc.primegov.com` case and verified live
in prod. `JURISDICTION_METADATA_PLAN.md`'s settled design moves the
same lookup into the enricher's first step (with an authoritative/
fallback strength flag per entry), which will make PrimeGov's copy
redundant. User's explicit call: don't touch PrimeGov's working
override during the testing phase; delete it only after the
enricher-side version is built, tested, and confirmed to produce the
identical result on the real SLC pages (the two Holladay-bug meetings
are the regression cases to check).

### Legistar's "Meeting Items" table

**A real "Meeting Items" table** (`File #`, `Agenda #`, `Type`,
`Title`, columns) with substantive per-item text — e.g. this meeting's
real items were "Canvassing, declaring, and adopting the results of
the Primary Election held on July 21, 2026... Resolution No. 12562"
and a development-agreement resolution for "an AC Hotel by Marriott."
Doesn't cleanly fit `agenda_items` (typed `List[TranscriptSegment]` —
real per-item *timestamps*, like Granicus's AgendaViewer.php chapter
markers) since Legistar's table has no per-item time offset, only
ordering. **User's call 2026-08-12, after weighing the shape
mismatch: probably not worth pursuing** — the real agenda document
(`agenda_link`, shipped 2026-08-13) already covers the "what was on the agenda"
need without a new untimed-items shape just for this one platform.
Left here for context, not as an open TODO.

### Never run a full-`segments` / full-corpus scan against the production DB from an interactive session

**Found 2026-08-17 via `pg_stat_statements` while fixing the worker's
auto-transcription sweep (`BACKLOG_DONE.md`) — a house-rule finding, not
a code bug:** four one-off, hand-written analytics queries (`mp.`/`tv.`
aliases, one with `AVG(jsonb_array_length(tv.segments::jsonb))`, one
`SELECT mp.slug, mp.jurisdiction, tv.segments … JOIN`) each ran
**50–62 seconds** against production — full scans of every `segments`
blob on a `shared_buffers = 64MB` server whose TOAST reads run at
~3MB/s cold. Each is a minute of saturated I/O during which live
`/meetings` search crawls for real users. They aren't from app code
(SQLAlchemy never emits those aliases) — they're interactive sessions
exploring prod data. Source, as far as it could be traced (2026-08-17
evening): the "empty pages" peer session (PR #136) confirmed it never
opened a prod DB connection (curl + scratch SQLite only); the "Q&A
Prod" session confirmed *it* never ran raw SQL either — the auto-mode
permission classifier blocked its `psql` attempt and it used the app's
`/internal/*` endpoints instead — **but one of its spawned background
sub-agents had been told to "sample real archived rows" without raw
SQL being explicitly forbidden, and sub-agents evidently aren't held to
the same `psql` gate the top-level session hit.** That's the systemic
gap, not the specific query: a top-level permission block doesn't
propagate to sub-agents' instructions unless the spawning prompt says
so. All three of that session's agents have since been given an
explicit "never run raw SQL/psql against prod" correction.
`pg_stat_statements` itself has no timestamps or client identity to
pin it further. Best remaining lead (relayed second-hand by the Q&A
session, unverified): a since-ended peer session named "Whisper
instructions" had described "skimming ~780 real scraped-caption
transcripts in the archive DB for quality" as prep for a Whisper
prompt-eval harness — a close match for both the
`AVG(jsonb_array_length(tv.segments::jsonb))`-by-platform shape and
the segments-by-slug pulls. **Rule worth adding to `CLAUDE.md`, right
next to the existing `.env`-grep incident bullet (same "a shell command
with real consequences" class)**: never run a full-`segments`/full-
corpus scan against the production DB from an interactive session —
sample with `LIMIT`, aggregate over `pg_column_size()` instead of the
values, use `cast(segments AS text) <> '[]'`-style predicates for
emptiness (what #136's in-app code correctly does), or use the
PITR/restore path (`BACKLOG_DONE.md`'s PITR entry) for real analysis.
And the corollary that actually closes the gap: **any prompt that
spawns a sub-agent with prod access must restate the rule
explicitly** — a permission block the parent hit does not carry into
the child's instructions.

(The rule this entry proposed adding to `CLAUDE.md` is recorded here
instead — this section is where a standing "don't do that" belongs, and
`CLAUDE.md` already carries the sibling `.env`-grep rule it points at.)

### Prefer a generated/computed column over "add a column, then backfill it"

`scripts/backfill_search_corpus.py`-style
one-time backfills remain manual — prefer generated columns (the
`search_tsv` pattern) so there's nothing to backfill.

### Do NOT spread a transcription job's within-job pulls across hosts

WO-40 measured the failure pattern across all 514 production jobs and the
two real mechanisms both argue *against* it — cold-storage rehydration
means chunk 0 warms the asset for chunks 1..N, and a persistently-slow
source doesn't care about pacing. Full numbers in the "A single job still
makes N consecutive same-host pulls" entry under **Reliability, ops &
cost**, and in `BACKLOG_DONE.md`'s WO-40 entry.

### Do NOT raise `media_probe.py`'s `_SUBPROCESS_TIMEOUT_SECONDS` to match Granicus's ~4-6 minute gateway timeout

That would tie up a worker chunk slot for minutes on every genuinely-dead
archived asset, trading a fast clear failure for a slow identical one.
Full root cause (a real 504 at Granicus's own CloudFront edge, not a rate
limit) in the "Granicus `chunklist.m3u8`" entry under **Reliability, ops
& cost**.

### Never attempt to auto-solve a Cloudflare "Verify you are human" challenge

Hit live on Spokane WA while building the Vimeo adapter (WO-29). The
adapter ships video-only rather than going near it. Same rule applies to
any future platform that gates behind one.

### Sacramento County's doubled meeting title is not a bug to fix

`"Board Of Supervisors Board Of Supervisors Meeting"` is real text
straight from the source page's own agenda-link `title` attribute,
re-confirmed by a live re-resolve 2026-08-15 — plausibly a genuine
`"{meeting type} {body name} MEETING"` template, not an artifact worth
guessing a general dedup rule from one example. Full detail in the
generic-fallback rebuild residuals entry under **Dormant**.

## Ship next — root cause known, fix settled `[JUST-DO-IT]`

Small, self-contained, no open design question. Jurisdiction-extraction
items that also qualify live under **Platform & jurisdiction coverage**
so that work reads together.

- **[JUST-DO-IT] Every Archive page ingested before WO-34 (2026-08-21) still
  holds the duplicated roll-up transcript it was stored with — the fix is
  resolve-time only.** `dedupe_rollup_cues()` now runs on every fresh
  resolve, but `TranscriptVersion` rows already in the Archive are
  untouched, so e.g.
  `/m/city-of-tacoma-wa-2026-01-06-city-council-on-2026-01-06-5-00-pm`
  still serves the `">> Councilmember Hines: WE >> Councilmember Hines: WE
  WILL ..."` text (confirmed live 2026-08-21, after the fix was verified
  working on a fresh resolve of the same meeting). Needs a re-resolve
  script that walks affected pages and writes the new transcript back —
  deliberately out of WO-34's scope because it's a write-path job against
  real public pages, not a parser change. Worth scoping *which* pages
  first: the same roll-up detector this fix added
  (`_looks_like_rollup()` in `app/utils/vtt_parser.py`) can be run against
  stored segments to count them rather than guessing. See
  `BACKLOG_DONE.md`'s WO-34 entry for what the fixed output looks like.

- **[JUST-DO-IT] `generic_fallback.py`'s best-effort "we think the video is here"
  line shows the raw embed URL, which is now sometimes an ugly one
  (2026-08-21, WO-29).** On Sebastopol CA's page the line renders as "We
  think the video is here: `https://player.vimeo.com/video/1152708575?h=db9859a2aa`"
  — a bare player page, technically correct and clickable but not the
  human `vimeo.com/{id}` URL a visitor would expect, and visually noisy
  next to the working embedded player right below it. Pre-existing
  behavior for every delegated best-effort result (a Swagit delegation
  shows its Swagit URL the same way), just newly visible now that Vimeo
  delegations exist. Confirmed live in-browser. Small fix, deliberately
  not bundled into WO-29: either show the delegated adapter's own
  human-facing URL, or drop the pointer line entirely when a real
  playable `video_url` was found.

- **[JUST-DO-IT] `/coverage`'s "Every place we've covered" table is too narrow —
  the Transcript column gets cut off, forcing unintuitive horizontal
  scroll.** Real, confirmed live. Fix: narrow the "Example meeting"
  (title) and "Transcript" columns in `archive/templates/coverage.html`'s
  `.coverage-table` styling, and shrink the row-number column (`#`) to a
  smaller font/width.

- **[JUST-DO-IT] "Browse by state" (added 2026-08-17, PR #122) has no "Canada"
  entry — structurally, not just missing data.** The entire feature
  (`archive/utils/jurisdiction_format.py`'s `US_STATE_NAME_TO_ABBR`/
  `US_STATE_ABBR_TO_NAME`, `archive/db/crud.py`'s
  `get_state_coverage_index()`, `/state/{slug}` in `archive/main.py`) is
  built entirely on a hardcoded US-only state table. Real Canadian
  jurisdictions already exist in the archived data (e.g. Airdrie, AB;
  Amherstburg, ON) but have no equivalent province table, so they never
  appear under any "Browse by state" grouping. Fix needs a parallel
  Canadian-provinces table (13 provinces/territories) and a "Canada"
  grouping, most naturally a second `get_*_coverage_index()`-style
  function reusing the same pattern.

- **[JUST-DO-IT] Canadian province abbreviations look like typos to US readers
  everywhere a state abbreviation renders sitewide.** Same root cause as
  the "Browse by state" gap above — no Canada-aware formatting anywhere
  in `jurisdiction_format.py`. Fix: append ", Canada" or " (Canada)"
  whenever the trailing suffix is a recognized Canadian province code, in
  the same `jurisdiction_display` filter / `format_jurisdiction_display()`
  path that already normalizes US state display — needs a
  `CANADIAN_PROVINCE_ABBRS` set, shared with the "Browse by state" fix's
  new table.

- **[JUST-DO-IT] `rtr-business/BUSINESS_OVERVIEW.md` still says "Not built yet: ...
  saved-search alert emails"** — stale; that feature shipped 2026-08-13
  (PR #30) and runs daily. `README.md`'s own copy of this claim was
  already corrected 2026-08-16. One-line fix whenever anyone's next in
  that file — not done here since business-workspace edits are kept
  separate from code-repo sessions per `CLAUDE.md`.

- **[JUST-DO-IT] Meeting-card backfill can only say a page failed, never
  why — real gap, confirmed live 2026-08-21 by the first production
  sweep.** `archive/utils/video_thumbnail.py`'s `extract_and_store()`
  calls `media_probe.extract_frame()`, which already returns
  `(ok, reason)` — the reason gets logged (`ffmpeg timed out after 45s`,
  `Server returned 404`, ...) and then discarded; every failure path
  returns bare `None`. `POST /internal/thumbnails/backfill`'s response
  schema has no field for it, so `scripts/backfill_meeting_cards.py` can
  only group failures by media host and point operators at the Archive's
  own server logs — flagged as a known, deliberately-deferred residual in
  `BACKLOG_DONE.md`'s WO-37 entry, "worth plumbing through only if a real
  sweep's failure set proves the host grouping isn't enough." That
  trigger is now met: the live sweep started 2026-08-21 is running at
  roughly 70% success on first-touch pages, and nothing in the response
  says why the other 30% failed. Small fix — thread the string through
  `extract_and_store()`'s return value and into the endpoint's per-result
  response object; the driver already has a place to print it.

## Needs a human — dashboard, prod, or product call `[HUMAN]`

Nothing here is blocked on engineering. Most are one dashboard login or
one deliberate production action away from closing. Grouped by what kind
of human step they need.

### Confirmations nobody has actually watched happen

Left open across `AUDIT_EXECUTION_BRIEF.md`'s Phase 1 and Waves 1-6, all
of which are code-complete and merged (full Problem/Do/Fixed detail in
`BACKLOG_DONE.md`'s "Reliability/ops audit execution" entry; Wave 5 /
WO-10 closed 2026-08-21, see `BACKLOG_DONE.md`). Grouped here rather than
scattered as "still open" footnotes across six waves. None blocks
anything else; do whenever convenient, no particular order.

- **[HUMAN] Sentry: confirm a real raised exception actually appears in the
  dashboard.** `SENTRY_DSN` is live and set on all three services, but
  nobody has forced a real exception and watched it land in Sentry's UI
  — WO-7's own stated acceptance criterion, never run.
- **[HUMAN] Confirm Render's health-check gate actually fails a deploy** when
  `/api/health` (resolver or Archive) reports unhealthy (WO-6) — the 503
  logic is unit-tested, but nobody has watched a real Render deploy
  actually get blocked by it.
- **[HUMAN] Confirm both admin cron workflows run green against the deployed
  `Authorization: Bearer` header-auth change**, then remove WO-8's
  query-param fallback in a follow-up PR. The fallback is deliberately
  still live until this is confirmed — don't remove it without checking
  a real cron run first.
- **[HUMAN] Confirm a real Render deploy installed cleanly off the new pinned
  lockfiles** (WO-11) — verified locally in an isolated venv per service,
  but the actual Render build hasn't been watched since the lockfiles
  landed.
- **[HUMAN] P3: confirm GA is actually receiving `submit_meeting_url`/
  `copy_link_to_time`/`resolve_result`/`video_play`/`transcript_seek`
  events** in the GA dashboard's last-30-days view — these all fire
  client-side per the code and were checked via `window.dataLayer`
  locally, but never cross-checked against the live GA property itself.
  **Partly confirmed 2026-08-17 (Ryan, GA Realtime + the Aug 10–17
  reports)**: `submit_meeting_url` (185 that week), `resolve_result` and
  `copy_link_to_time` (17) all arrive; the 1:1 submit→result on Aug 17
  shows the funnel isn't dropping. `video_play` / `transcript_seek` still
  unconfirmed in the dashboard — but the bigger finding was *why* they'd
  be near-zero anyway: those events only existed on the resolver's
  ephemeral `/meeting` page, while the Archive's 1,200+ permanent `/m/*`
  pages (where sitemap/search/shared-link traffic lands) emitted **no
  custom events at all** — GA for Aug 17 with Ryan filtered out showed
  only page_view/session_start/first_visit/scroll/user_engagement.
  **Fixed the same day**: `archive/static/meeting_page.js` now fires the
  same `video_play` / `transcript_seek` / `copy_link_to_time` (identical
  names, no extra params — `page_location` already separates surfaces)
  plus `save_meeting` (`action: save|unsave`, only on a confirmed server
  flip); 5 jsdom tests exercise the real boot path; verified in-browser
  through the resolver→archive proxy. What's left of this item: watch
  the next week's GA for those four names on `/m/*` page paths — the
  first real answer to "does anyone use the deep links". Also worth one
  look: the Aug 10–16 daily split of `submit_meeting_url` (185 vs 1 on
  Aug 17) — evenly-spaced round-the-clock = a bot on the form; clustered
  on outreach days = the first-10 campaign working.
- **[HUMAN] P5: confirm a real `send-search-alerts` cron run actually sent a real
  email** to a real saved search — the workflow runs daily and reports
  success, but nobody's checked an inbox for the actual email.

### Production actions only Ryan should take

- **[HUMAN] Render "HTTP health check failed (timed out after 5 seconds)"
  on `rtr-deeplink-archive` (production) has now recurred twice — 2026-08-19
  13:17:28 UTC and 2026-08-20 21:38:36 UTC, ~32 hours apart — promoted from
  `CLAUDE_INBOX_TRIAGE.md`.** Distinct from the already-diagnosed 2026-08-17
  instability cluster (memory-limit restarts, proxy `TimeoutError`,
  `RuntimeError: Response content shorter than Content-Length`, DB-shutdown
  error) — this is a plain health-check timeout, no matching root cause
  identified yet. Neither occurrence had a "still down" follow-up email, and
  Render's own alert text says this class of alert often self-resolves, so
  real duration/user impact is unconfirmed without Render dashboard/log
  access. Two occurrences ~32h apart is mild evidence toward a pattern
  rather than a one-off blip, not proof either way. Worth a quick check of
  the Archive's Render logs/memory graph around both timestamps next time
  anyone's in the Render dashboard.
- **[HUMAN] Render account bandwidth limit reached — real, current cost
  exposure, found by the daily inbox-triage Routine's 2026-08-18 run.**
  Render's Hobby-plan bandwidth (5GB/month, shared account-wide across
  `rtr-deeplink`, `rtr-deeplink-archive`, and the worker) hit "Approaching
  Bandwidth Limit" (>70% used) 2026-08-17 12:13 UTC, then "Reached the
  Bandwidth Limit" (100%) 2026-08-18 12:17 UTC — roughly 30% of a whole
  month's allowance used in about 24 hours. Overage is now auto-billed at
  $15 per additional 100GB, uncapped, resetting at the start of next
  calendar month. **Open question for Ryan, not resolvable from here**:
  is this expected (real traffic growth from the first-10
  outreach/clips campaign — arguably good news) or something to check (a
  proxy/redirect loop, or the Archive serving full video bytes through
  `archive_client.py`'s proxy rather than just embedding a player/link)?
  Render's dashboard bandwidth breakdown would answer this in under a
  minute but requires the actual dashboard login.
- **[HUMAN] Archive service instability, 2026-08-17 ~14:10-22:04 UTC —
  mostly already-explained, but two pieces aren't, found by the daily
  inbox-triage Routine's 2026-08-18 run.** Sentry showed a cluster of
  production errors that evening: "Unclosed client session"/"Unclosed
  connection" (resolver's `/api/health` complaining about
  `archive_client.py` connections to `rtr-deeplink-archive.onrender.com`
  never closing), a proxy `TimeoutError`
  (`app/archive_client.py:362`, `proxy_get()` on `/meetings`),
  "RuntimeError: Response content shorter than Content-Length" (Archive's
  `/`, almost certainly Render's own health probe), and
  "CannotConnectNowError: the database system is shutting down" (Archive's
  `/api/health` DB connection). Most of this cluster is very likely
  explained by `BACKLOG_DONE.md`'s already-documented WO-10 outage that
  same evening (PR #116's model column deploying ~13 minutes ahead of its
  `ALTER TABLE`, causing `UndefinedColumnError` on every `meeting_pages`
  read — Sentry's own error for that is timestamped 16:26 UTC, right in
  the middle of this cluster). **Two things aren't accounted for by that
  explanation**: (a) four separate "Web Service rtr-deeplink-archive
  exceeded its memory limit" restart emails fired at 14:10, 14:15, 14:23,
  and 17:08 UTC — the first one **nearly 2.5 hours before** the first
  `UndefinedColumnError` alert (16:26 UTC), so an OOM-driven trigger
  *preceding* (and possibly contributing to) the schema-read errors is a
  real, currently-unexplained possibility, not just downstream fallout
  from them; (b) WO-10's own fix deploy (PR #156) itself failed to deploy
  at 23:54:28 UTC that same evening ("We encountered an error during the
  deploy process... your latest changes may not be live") — though
  `render.yaml` on `main` today confirms `preDeployCommand` is live, so a
  later attempt clearly succeeded, and the first attempt's own failure
  reason was never surfaced. **Open question for Ryan**: worth a quick
  look at Render's memory graph for the Archive around 14:00-17:00 UTC on
  2026-08-17 to check whether OOM genuinely preceded/triggered the
  schema-read cascade, or whether the timing is coincidental.
- **[HUMAN] Meeting-card backfill sweep — running, not yet done, real
  numbers so far.** Started 2026-08-21 ~18:37 PT via `scripts/
  backfill_meeting_cards.py --apply`, detached (`nohup`), log at
  `/private/tmp/claude-501/.../scratchpad/card_backfill.log` for whoever
  next checks this box. The first bounded 3-batch run caught a real
  production 500 (a shadowed `offset` variable — any batch whose last
  page failed to extract crashed the response; fixed same day, PR #286,
  with regression tests confirmed to fail against the pre-fix code).
  Since the real run started: **457 stored / 605 attempted (~76%
  success)**, ~1,000 pages left, ETA a few more hours from start. Safe to
  Ctrl-C and re-run — extracted pages leave the queue, failed slugs are
  recorded in `scripts/meeting_card_backfill_state.json` so they're
  skipped rather than re-probed (delete that file once, days later, to
  give them another chance — a CDN timeout is often transient). The
  ~24% failure rate is exactly what the new entry above (thread the
  failure `reason` through) exists to make diagnosable instead of a
  mystery. Full build detail in `BACKLOG_DONE.md`.
- **[HUMAN] Stray demo-shaped tables found in `rtr_deeplink_db` during
  the PITR test-restore verification (2026-08-17).**
  Confirmed live 2026-08-17 during the WO-4 PITR test-restore verification
  (see `BACKLOG_DONE.md`): the Postgres server backing `rtr-deeplink-db`
  hosts two logical databases, `rtr_deeplink_db` (the resolver's —
  `meeting_resolutions`, `problem_reports`, 355 real rows) and `rtr_archive`
  (the Archive's — `meeting_pages`, `transcript_versions`, 1,117 real
  rows). That two-database split is the documented, intentional
  architecture (README's "Database architecture" section), not the
  finding here.

  The actual finding: `rtr_deeplink_db` *also* contains a full set of
  Archive-shaped tables (`meeting_pages`, `transcript_versions`,
  `transcription_jobs`, `meeting_page_url_aliases`) holding only 4 old
  demo rows (`city-of-demo-...`, `nowhere-xx-...-some-raw-pasted-youtube-
  meeting`, dated 2026-08-12) — entirely separate from the real Archive
  data in `rtr_archive`. Nothing in `app/db/models.py` defines these table
  names, so nothing in the resolver's live code should be reading or
  writing them.

  Root cause not established — worth checking `rtr_deeplink_db`'s own
  `alembic_version` history and git blame around when `archive/db` was
  split from a shared database, rather than guessing. Timing note: the
  demo data's date (2026-08-12) is *after* both services adopted Alembic
  (2026-08-09/08-10 per `CLAUDE.md`), so "leftover from before the split"
  doesn't cleanly fit — a different explanation (e.g. a demo-seed script
  or test run that once pointed at production) is equally plausible.

  **Not urgent, not touched.** No data was modified or dropped as part of
  finding this. Any cleanup is a real, destructive action against
  production and should only be done by Ryan after the root cause is
  understood and Ryan executes or explicitly approves it — not something
  to do reflexively just because the tables look unused.

### Decisions about already-live content

- **[HUMAN] 4 already-completed, already-live default transcripts are real,
  confirmed candidates for the phase-cancellation hallucination bug fixed
  2026-08-16 (or a related hallucination symptom) — a real, user-facing
  decision still open, not code.** See
  [BACKLOG_DONE.md](BACKLOG_DONE.md)'s matching entry for the full
  `GET /internal/transcription/hallucination-candidates` build/run
  writeup (5 total real candidates found; the 5th, Port Coquitlam, BC,
  was already re-transcribed and promoted as part of the same pass, see
  that entry). The remaining 4, all still `is_default=True` today, not
  yet re-transcribed or otherwise touched (deliberately, matching the
  seam-duplication audit's own precedent right below — deciding what to
  re-transcribe is the user's call):
  - `revised-long-beach-ca-2026-08-04-aug-04-2026-city-council-special-meeting`
    (version 176, cloud-worker job 74, `en`, 1239 segments) — spot-checked
    live: real, confirmed hallucination-loop artifact (14+ consecutive
    segments of bare `"."`) is present at the very start of the actual
    rendered transcript, not a heuristic false-positive.
  - `san-diego-county-ca-2026-06-24-board-of-supervisors` (version 240,
    cloud-worker job 103, `en`, 4662 segments) — same `"."`-repetition-loop
    symptom, also spot-checked live and confirmed real.
  - `meeting-38ca49` (Sacramento County, CA Board of Supervisors 2026-08-11;
    version 246, cloud-worker job 111, `en`, 5052 segments) — spot-checked
    live: real, classic Whisper hallucination on quiet/no-speech audio at
    the very start (`"Thank you for your attention." ... "Thank you very
    much for watching this video and I'll see you in the next video."` —
    a well-known stock hallucinated phrase), before the transcript recovers
    into genuinely coherent real content once the meeting actually starts
    at 6:30.
  - `kitchener-2026-05-05-heritage-kitchener-committee` (version 981,
    cloud-worker job 201, `cy` — Welsh, 410 segments) — spot-checked live:
    real, confirmed garbled Welsh-script gibberish throughout, including a
    single ~500-character run of repeated `w` (`"Ymwwwww...w"`) and a
    later repetition loop (`"Ff. Ff. Ff. Ff."`) — two of the detector's
    three structural signals both genuinely present, not a misdetection
    edge case.
- **[HUMAN] 118 already-completed, already-live transcriptions are real
  candidates for the seam-duplication bug fixed 2026-08-16 — a real,
  user-facing decision still open, not code.** See
  [BACKLOG_DONE.md](BACKLOG_DONE.md)'s matching "Bugs" entry for the
  full root-cause/fix/verification writeup. The fix stops the bug from
  shipping on any *future* multi-chunk transcription, but doesn't touch
  what's already live — deliberately, per this task's own brief, since
  deciding what (if anything) to re-transcribe is the user's call, not
  something to do automatically. `GET /internal/transcription/completed-
  multichunk` (token-gated) returns the real, current list (job id, page
  slug, chunk count, duration, completion date) any time it's needed
  again. Two real open sub-questions, not yet decided: (1) whether to
  re-transcribe all 118, a prioritized subset (e.g. longest/most-viewed
  first), or none until a specific one gets reported; (2) this list only
  covers jobs the cloud worker's own queue processed — it does **not**
  cover `scripts/transcribe_backlog_locally.py`'s separate local-Mac
  backlog runs (which never touch the `transcription_jobs` table at
  all), a real, currently-uncounted second population also affected by
  the same pre-fix bug.
- **[HUMAN] The WO-36 fix makes `GET /internal/transcription/
  hallucination-candidates` surface a much larger already-live backlog —
  a real user-facing decision, not code.** That endpoint re-runs
  `detect_hallucination_warnings()` against *stored* segments, so pages
  pushed before the fix get re-scored the next time it's called. Measured
  while building the fix: of 304 real `source=="transcribed"` transcripts
  pulled from the live Archive, **74 (24%) contain a repetition loop the
  new rule flags** and were pushed with no warning. Every one hand-
  inspected was a genuine degenerate loop, not a false positive — the
  common shapes are a `"Thank you."` / `"you"` loop across a recess
  (Airdrie, Halifax NS, SCRD, Steamboat Springs, ~20 more), a fixed-cadence
  single-word tile (`"second."` x41, `"of."` x42, `"five."` x45), and the
  `initial_prompt` vocabulary itself leaking back out as text (Calgary's
  `"local government meeting."` x31). Same class of decision as the
  4-candidate `[HUMAN]` entry above, just much bigger: deciding what's
  worth re-transcribing (versus warning in place, or leaving) is the
  user's call. Note the prevention half is already live, so this is a
  backlog of pre-2026-08-18 transcriptions, not an ongoing rate.
- **[HUMAN] The Clerk `user.deleted` → `saved_items` purge has never
  been fired end to end.** Split out of the accounts entry (see **Roadmap
  & strategy**) so a real right-to-deletion gap isn't buried inside a
  feature writeup.
  The code path exists
  (`archive_client.delete_account_data()` → bearer-gated
  `/internal/account/delete-data` → `DELETE FROM saved_items WHERE
  clerk_user_id = ...`) and has unit coverage
  (`tests/test_clerk_webhook.py`), but no real Clerk account has been
  deleted via the UserButton flow to confirm the webhook fires and the
  rows actually disappear. User's decision: don't block merge on this:
  "we can do it manually if anybody actually requests it" — i.e. a real
  deletion request would be handled by hand (direct DB delete) rather
  than relying on this untested automation, at least until it's been
  exercised for real. Worth closing this gap for real before this phase
  is treated as a finished right-to-deletion story, not just before
  merge.

### Product calls

- **[HUMAN] `legistar.py`'s `_try_fallback_video_link()` still prefers the
  delegated platform's *title* over the Legistar page's own body name --
  unlike its date and jurisdiction, both of which the page now wins
  outright.** Found live 2026-08-21 alongside the date bug fixed in WO-30
  (see `BACKLOG_DONE.md`): Baltimore's real 2026-08-05 Public Health &
  Environment hearing renders as "City Council Hearing: Public Health &
  Environment; August 5, 2026" -- CharmTV's YouTube title, complete with a
  redundant embedded date -- rather than Legistar's own "Public Health &
  Environment Committee". Not obviously a bug: the existing
  `_looks_like_raw_filename()` heuristic exists precisely because a
  delegated platform's title is sometimes *better* (NYC/Viebit's is a raw
  `.mp4` filename), and a channel name plus a date is arguably more
  informative than a bare body name. Needs a product call on which reads
  better on the meeting page, not a code fix decided in isolation.

## Open bugs — real, root cause not settled `[NEEDS-AUDIT]`

Reproduced against real data, but the fix is a genuine open question —
not something to guess at. Jurisdiction-extraction bugs live under
**Platform & jurisdiction coverage** instead, so that work reads
together.

- **[NEEDS-AUDIT] A chunk truncated only at its *tail* still passes the
  new decodability guard — confirmed with real ffmpeg 2026-08-21, not
  assumed.** The first 1000 bytes of a real 12.6KB mp3 decode cleanly
  (exit 0, correct `mean_volume`), and PyAV opens such files too, so a
  chunk that's valid-but-short reaches whisper and silently transcribes
  only the part that survived. The obvious guard — reuse
  `probe_duration()` on the extracted file and compare against the
  requested `duration` — was considered during WO-25 and deliberately not
  built, because two *legitimate* cases produce a short chunk:
  `extract_chunk_audio()`'s fast input-side `-ss` seek makes real HLS
  chunk durations differ from the requested value (the same behavior
  behind the seam-dedup logic in `worker/main.py` /
  `tests/test_worker_segment_utils.py`), and the final chunk of a job is
  legitimately short. A tolerance loose enough to accommodate both may
  not be tight enough to catch a meaningful truncation — worth measuring
  real per-chunk `probe_duration()` deltas across a few live HLS and
  direct-file jobs *before* picking one, rather than guessing a number.
  Not observed in production yet; logged as a real, measured gap.

- **[NEEDS-AUDIT] `_sentence_case()` capitalises after every `\n`, so a de-shouted
  two-line roll-up track comes out with mid-sentence capitals** — real
  example, Antioch CA CivicClerk 2026-03-10 after WO-34: "good evening
  everyone and Welcome to our regular city Council meeting of march the
  10th, 2026." Pre-existing and unchanged by WO-34 (the same casing is on
  the live page today, just doubled up), and the roll-up fix deliberately
  did *not* try to repair it: lowercasing a line-initial capital would be
  a guess that destroys real proper nouns, and the ALL-CAPS de-shouting has
  already flattened those anyway ("antioch", "leon"). The honest fix is
  probably in `_sentence_case()` itself — a `\n` inside a caption cue is a
  line wrap, not a sentence boundary — but that changes output for every
  de-shouted track, so it needs its own pass with its own real samples.

### `scripts/transcribe_backlog_locally.py` skips a live meeting on one transient failure `[NEEDS-AUDIT]`

**Confirmed live, 4/4 tested, not a hypothetical.** During this session's
tier-3-queue local-Whisper batches, four meetings were logged as skipped
with `"no usable audio/video source on re-resolve"`: Diamond Bar, CA;
Genesee County, MI; Sullivan County, NY (all `iqm2`); and Brookhaven, NY
(`civicclerk`, a slightly different failure -- `ffmpeg extraction failed`
after a successful resolve, i.e. the same class of problem one step
later in the pipeline). Re-running `finder.resolve()` against the exact
same URLs, unchanged, minutes later: **all four succeeded immediately**,
zero warnings, real `video_url`s -- and for Diamond Bar, CA specifically
(which already had a real archived page from before this batch even
ran, `city-of-diamond-bar-ca-2020-06-02-city-council-regular-meeting`),
the stored `video_url` from that earlier successful resolve is still
live and reachable today (confirmed via a direct `HEAD` request: `200
OK`, 300MB, real `Content-Length`) -- meaning the video was never gone
at any point; the pipeline just happened to hit one slow/flaky moment
against that specific government server during the batch run and gave
up permanently instead of retrying.

**Why this is worse than an ordinary flaky-network bug for this
specific script**: `scripts/transcribe_backlog_locally.py`'s `process_
one()` treats every `transcribe_meeting()` failure identically (skip
and move on to the next candidate) whether the underlying cause is
"genuinely no video exists" or "the request timed out once." Diamond
Bar, CA is the sharpest case: a page that had *already* been live on
the site with a real video before this session touched it got a
transcript-attach attempt today, hit one bad moment, and is now
recorded as unresolvable -- even though nothing about the source
actually changed. A page that already passed the bar to exist on the
site is *more* suspicious to skip permanently on one failure, not less.

**Fix direction**: add a single retry (with a short backoff) around the
`finder.resolve()` / `extract_chunk_audio()` calls in `transcribe_
meeting()` before concluding a candidate is genuinely infeasible --
mirroring the retry-on-transient-failure pattern `_request_json()`
already uses for the archive-side HTTP calls in this same script, just
extended to the resolve/extraction side too, which currently has none.
Worth checking whether `worker/main.py`'s own idle-time auto-
transcription path has the same one-shot-no-retry gap, since it likely
shares similar resolve/extract call shape.

**A fifth case, same day, isolated further**: a 10-meeting `new.swagit.
com`-heavy batch hit `ffmpeg extraction failed on chunk 1/1` on 4/10
(Odessa/Midland/Cedar Hill TX, Grand Rapids MI) after a 120s timeout
each. Retried all 4 immediately after: 3 succeeded on the very next
attempt. Odessa specifically failed *twice* before succeeding on a
third try, which ruled out one theory worth recording — it's not that
the exact `ffmpeg` command is broken for this host: a manual `ffmpeg`
invocation, byte-for-byte identical to `extract_chunk_audio()`'s own
(`-headers ... -ss 0 -i <url> -t 900 -vn -ac 1 -ar 16000 -c:a libmp3lame
-b:a 32k`) run standalone against the exact URL that had just failed
inside the script, completed in ~12s both times it was tried. So the
video/host/command are all fine; whatever caused the in-script hang to
120s is specific to running under the script's actual asyncio/subprocess
context, not the source. Consistent with (not proof of) a resource
buildup across a long sequential batch in one process rather than a
purely random network blip — worth keeping in mind if the fix above
ends up being "add a retry" rather than "find and fix the root cause,"
since a retry would paper over this either way.

**Two more cases, 2026-08-19, one of which weakens the "just retry"
assumption above.** Plainfield, NJ (`iqm2`) hit the exact `"no usable
audio/video source on re-resolve"` skip during a 10-meeting tier-3
batch, despite a `--dry-run` earlier the same session confirming a real
video/95min duration for the identical URL — a 6th confirmed instance
of the same transient pattern, consistent with the fix direction above.
**Brookhaven, NY (`civicclerk`) is the concerning one**: retried twice,
back-to-back, immediately after the first failure (not just once, and
not with any delay) — both retries failed identically, same `ffmpeg
timed out extracting ... @ 0s` on chunk 1/2, same CDN host
(`cpmedia.azureedge.net`), same ~120s timeout. Unlike every other case
in this entry, one retry did not recover it. Doesn't disprove the
"add a retry" fix direction above (a single retry is still very likely
worth it given the other 5 cases), but does mean that fix alone won't
be sufficient for every case — Brookhaven either needs more than one
retry, a longer per-attempt timeout, or has a genuinely slower/more
rate-limited CDN than the other hosts seen so far. Not re-attempted a
third time this session; worth a fresh look (and worth checking whether
it's this specific media file or `cpmedia.azureedge.net` generally)
before assuming it's simply "still transient, just unlucky twice."

### `tier3_auto_transcription_queue.txt` holds at least one genuinely truncated URL `[NEEDS-AUDIT]`

While hand-picking real candidates for a local-Whisper batch, Orinda,
CA's queue entry (line 8) turned out to be cut off mid-query-string:
`http://orindaca.iqm2.com/Citizens/Detail_LegiFile.aspx?Frame=&MeetingID=2665&Me`
— confirmed via `od -c` that the line genuinely ends `...&Me\n` in the
file itself, not a display artifact. Distinct from the "URLs that look
like they were never actually formed" pattern the user separately
flagged for some iqm2/ClerkBase dead-list rows earlier this session
(those were absent a real ID/params entirely, not a well-formed URL cut
short mid-token) — this one clearly had the rest of a real query string
and lost it. Single confirmed instance so far; worth a broader scan of
the queue file for other lines that look implausibly short for their
platform's usual URL shape before assuming it's isolated.

### Some Swagit meetings have no single "whole meeting" video file `[NEEDS-AUDIT]`

**Confirmed live, not assumed.** While fixing a real bug in
`app/platforms/swagit.py` (see `BACKLOG_DONE.md`'s 2026-08-18 entry —
a dead legacy `player.src()` fallback URL was winning over the real
video data on some pages), a deeper structural fact surfaced: Yolo
County, CA's clip 324107 (and likely many other Swagit meetings with a
populated agenda) isn't stored as one continuous recording at all. The
page's real jwplayer `playlist: [...]` JSON has **12 separate entries**,
one per agenda item (`" 9:00 A.M. CALL TO ORDER"`, `"CONSENT AGENDA"`,
... `"CLOSED SESSION"`), each with its own distinct
`archive-stream.granicus.com/.../{date}-{id}.360.mp4/playlist.m3u8`
file. The bug fix above correctly picks a *real* file now instead of a
dead one, but for a chaptered meeting like this it's only the *first*
agenda item's own short clip -- confirmed live: resolved duration for
this meeting came back as 2.1 minutes, not the real multi-hour meeting
length. Verified this isn't a one-off: re-ran the same fixed resolver
against all 43 URLs that had been hitting the dead-fallback bug -- 14
resolved to a normal, plausible single-file duration (11 landed in the
5-45min "short" range, 3 came back >45min), but the other **29** came
back suspiciously short (many under a minute, one at flat 0.0 minutes),
consistent with the same first-chapter-only pattern.

**Not yet answered, needs real investigation before coding a fix**:
does Swagit still serve a true full-session file anywhere for these
customers (a different field/URL this session didn't find, possibly
alongside the chaptered playlist -- worth checking whether the now-dead
`player.src()`/`hls_path` fallback was *itself* originally meant to be
that whole-meeting stream, since the current chaptered `playlist` looks
like a newer addition it now loses to only because the old one is
broken, not because it was always meant to win), or whether "pre-split
into per-agenda-item clips, no single full recording" is simply how
some Swagit customers' pages have always worked. If it's the latter,
this app's whole per-chunk transcription/duration-probing pipeline
(built around "one video_url, one continuous duration") would need a
real design decision for this platform: concatenate all N clips into
one virtual timeline before chunking (extra complexity, but keeps the
rest of the pipeline unchanged), or treat each agenda-item clip as its
own independently-transcribed unit and stitch the resulting segments
back together using the clips' own real seq/title ordering (Swagit
already provides that structure for free, arguably a cleaner fit than
faking one continuous file).

**Which URLs are affected**: the 29 still-short ones out of the 43-URL
list already gathered this session (`alamoareampo`, `applevalleymn`,
`baytowntx`, `belfastme`, `breaca`, `conejovalleyusdca`,
`coronadousdca`, `delvalleisdtx`, `greenburghny`, `houstonisdtx`,
`jacksonms`, `jupiterfl`, `lagov`, `lubbockisdtx`, `mahwahnj`,
`missouricitytx`, `mobilityauthority`, `nassaucountysd`,
`newportricheyfl`, `olatheks`, `pelhampublicschoolsny`, `planotx`,
`princegeorgebc`, `sandovalcountynm`, `sedonaaz`, `siouxcityschools`,
`wallercountytx`, `whiteplainsny`, `yolocountyca` -- all
`{customer}.new.swagit.com/videos/{id}`), but likely a much broader
set across Swagit generally, not just these 43 -- these just happen to
be the ones that were already flagged dead by an unrelated bug and got
a second look. Worth a fresh, broader live audit of Swagit meetings
with populated agendas generally once the design question above is
answered, not just this specific 29.

## Platform & jurisdiction coverage

Everything adapter-, tenant-, or jurisdiction-extraction-shaped, kept
together on purpose — this work used to be split across five sections.
Tags are inline here rather than hoisted into the actionability sections
above.

### The 50 largest US cities — per-tenant status `[NEEDS-AUDIT]`

Distinct from the "no domain found yet" jurisdiction-coverage work
(`~/Documents/rtr-business/research/jurisdiction_coverage.csv`) -- these
cities' government video/meeting URLs are already known, but our
platform genuinely can't turn them into a working page yet, either
because the site shape isn't one of our adapters' patterns, or because a
*supported* platform's tenant has a real, tenant-specific quirk. One
related finding from the same table (Charlotte, NC mis-attributed to
Detroit, MI) turned out to be an already-fixable stale-ingest issue, not
an adapter gap -- see its own entry in `BACKLOG_DONE.md`, not repeated
here.

**Genuinely unsupported site shapes (real adapter work, not a quirk):**
- ~~**Phoenix, AZ** -- Legistar meeting detail pages always report video
  as "unavailable," but the real video exists on a separate, unlinked
  YouTube channel~~ **Built 2026-08-21 (WO-30) -- full detail in
  `BACKLOG_DONE.md`.** The user's own suggested shape (a hardcoded
  per-tenant YouTube-channel mapping) is exactly what shipped:
  `app/platforms/youtube_channel.py`'s curated netloc->channel dict plus
  a name+exact-date matcher. The real July 1, 2026 meeting now resolves
  to `youtube.com/watch?v=srjuXI5vGuw` with 4,916 real caption segments.
- ~~**Philadelphia, PA** -- same shape as Phoenix~~ **Built 2026-08-21
  (WO-30), same fix.** Confirmed live: `phila.legistar.com`'s 2025-06-04
  Committee on Finance now resolves with 5,877 caption segments. Note
  Philadelphia's channel titles use numeric dates with a two-digit year
  ("Committee on Finance 06-4-25") and split long meetings across
  "(Part 1)/(Part 2)" videos -- both handled, see `BACKLOG_DONE.md`.
- ~~**El Paso, TX** (`elpasotexas.gov/videos`) -- each government body gets
  its own Vimeo landing page rather than one consistent embed pattern;
  no adapter attempted yet.~~ **Mostly closed 2026-08-21 (WO-29)**: all
  13 of El Paso's per-body Vimeo showcases now resolve (a pick-list of
  that body's real meetings, each playable and deep-linkable). What's
  still missing is an adapter for the `elpasotexas.gov/videos` index
  itself, so a user has to paste a specific showcase rather than the
  city's own page -- see the fuller El Paso entry later in this file.
  **Chicago, IL is fully closed by the same PR** (new
  `app/platforms/chicago_elms.py`; it was tracked in its own entry, now
  in `BACKLOG_DONE.md`, rather than as a row here).
- **Portland, OR** (`portland.gov/council/agenda/...`) -- **corrected
  2026-08-21: this row's "not supported, needs real adapter work" was
  wrong.** Portland's council agenda pages resolve correctly through
  `generic_fallback.py` and have since at least 2026-08-12 -- the raw
  page server-renders a plain `<iframe src="youtube.com/embed/...">`, and
  a direct run of `register_all_finders() -> detect_platform() ->
  finder.resolve()` found video *and* agenda link on the first try. What
  looked like an adapter gap was a resolve-level cache with no expiry
  serving a permanently-cached negative result; fixed 2026-08-12, full
  detail in `BACKLOG_DONE.md`. **Genuinely still open**: no Portland page
  has been archived yet (zero rows on production `/coverage`, checked
  live 2026-08-21), and `<time datetime="...">` markup Portland publishes
  with real time-of-day is still unused -- see the "Feed cities" entry
  under **Roadmap & strategy**.
- **Tucson, AZ** ("Mayor and Council," Hyland-hosted at
  `tucsonaz.hylandcloud.com`) -- **partially closed, and this row's
  framing was wrong.** Hyland "OnBase Agenda Online" shipped 2026-08-16
  (`app/platforms/hyland.py`) with Tucson as one of its three original
  confirmed customers, so Tucson's agenda outline and per-item video-seek
  offsets do resolve. The real, still-open half is narrower than "no
  adapter": **Tucson's Hyland pages carry no video at all** -- confirmed
  across 2 independent meeting ids, see `hyland.py`'s own module
  docstring -- while the real video lives on a separately-hosted YouTube
  channel, with audio + minutes paired by matching filenames on a
  *different* page
  (`tucsonaz.gov/Departments/Clerks/Boards-Committees-Commissions/...?run=pastminutesaudio`),
  not attached to the Hyland agenda item itself. WO-30's
  `app/platforms/youtube_channel.py` (a curated `netloc -> channel id`
  dict plus a name+date matcher) is exactly the shape that would close
  it, but it is wired to Legistar netlocs only today. Production
  `/coverage` still carries the degenerate `/m/meeting` page for Tucson
  with no transcript (checked live 2026-08-21).
- ~~**Seattle, WA** (`seattlechannel.org`) -- "Seattle Channel," a custom
  city-run video platform, not yet triaged against any existing
  adapter.~~ **Stale -- built 2026-08-14**, `app/platforms/
  seattlechannel.py`, registered and canaried
  (`scripts/adapter_canary.py`'s `seattle_channel` key). Confirmed live
  on production `/coverage` 2026-08-21: `/m/seattlechannel-org-2026-08-11
  -city-council-8-11-2026`, jurisdiction "Seattle, WA", real transcript.
  Full build detail in `BACKLOG_DONE.md`.

**Supported platform, but a real tenant-specific gap:**
- **Atlanta, GA** -- ChampDS (`play.champds.com/atlantaga`), a platform
  this repo already supports elsewhere, but user-confirmed "not working"
  for this specific tenant -- worth a live recheck against a real
  Atlanta ChampDS event URL to find the actual failure mode.
- **Omaha, NE** -- videos and minutes/journals are hosted on separate
  pages under `cityclerk.cityofomaha.org`, not paired the way our
  ingest expects.
- **Tampa, FL** -- video/agenda live at `tampa.gov`, but transcripts are
  posted separately at `apps.tampagov.net/cttv_cc_webapp/` and need to be
  matched back to the right meeting.
- **Virginia Beach, VA** (`onboardgov.virginiabeach.gov`) -- user's own
  note: "difficult challenge," not yet triaged.
- ~~**Baltimore, MD** -- Legistar; user-confirmed only a handful of
  meetings have video actually attached, most real video is on YouTube
  instead and not linked from Legistar.~~ **Built 2026-08-21 (WO-30),
  the same city-YouTube-channel fallback as Phoenix/Philadelphia above.**
  The user's observation was exactly right and is now measured: across 53
  real Legistar events 2026-05-01..2026-08-20 (none of which Legistar
  itself gives a video for), 29 now match a real CharmTV recording. The handful that
  *do* carry their own "Recording" link keep using it, untouched -- which
  is also what let the matcher be checked against Baltimore's own answer
  (see `BACKLOG_DONE.md`).
- **Kansas City, MO** -- Granicus/Legistar, already partially working per
  the user, but oddly only the Transportation Infrastructure and
  Operations Committee is coming through; other committees' meetings
  are real and missing.
- **Detroit, MI** -- Cablecast, user flagged as "not working well"
  independent of the separate Charlotte/Detroit mis-attribution bug
  (`BACKLOG_DONE.md`) -- worth its own live recheck.
- **Austin, TX** -- `austintexas.gov/council/...`, user-flagged as
  "in progress, use this to improve unsupported page" -- a real page
  shape to test a fix against.
- **San Antonio, TX** (Swagit, `sanantoniotx.new.swagit.com`) and
  **Columbus, OH** (Legistar, `columbus.legistar.com`) -- both on
  already-supported platforms, but not yet spot-checked against these
  specific tenants; may just work, unconfirmed either way.

**Live re-verified against production `/coverage` 2026-08-21** (2,968
rows fetched and parsed, not eyeballed) -- several rows above are better
than they read, and a few are worse:
- **Atlanta, GA** -- has two live pages, one with a real transcript
  (`/m/city-of-atlanta-ga-2026-08-12-finance-executive-committee-regular-c`).
  ChampDS is not wholly broken for this tenant; whatever the user hit is
  narrower than "not working." Recheck against the specific failing URL.
- **Austin, TX** -- live with a real transcript
  (`/m/austin-tx-2026-04-23-apr-23-2026-city-council-meetings`).
- **San Antonio, TX** -- live with a real transcript
  (`/m/san-antonio-tx-2026-08-06-...`), so the Swagit tenant does work.
  **Columbus, OH** is still genuinely absent (only Columbus IN and a
  Columbus WI hub appear), so that half of the row stands.
- **Detroit, MI** -- live with a real transcript
  (`/m/detroit-mi-2024-05-28-city-council-formal-session`). Note a second
  row still carries the stale `detroit-mi-...` slug under the corrected
  "Charlotte, NC" jurisdiction -- that is the already-fixed
  mis-attribution (`BACKLOG_DONE.md`), not a live bug.
- **Kansas City, MO** -- the user's observation is confirmed exactly: the
  only live row is the Transportation Infrastructure and Operations
  Committee. Other committees are still missing.
- **Baltimore, MD** -- WO-30 is working in production
  (`/m/charmtv-citizens-hub-2025-10-20-city-council-hearing-...`,
  jurisdiction "Baltimore, MD", real transcript).
- **Omaha NE, Tampa FL, Virginia Beach VA, Portland OR, Philadelphia PA,
  Chicago IL** -- zero live rows each. Omaha/Tampa/Virginia Beach are
  genuine open gaps as written. Philadelphia and Chicago resolve in code
  (WO-30, WO-29, both merged 2026-08-21) but nothing has been ingested
  yet, so absence here is expected, not a regression.
- **El Paso, TX** -- one live row with a transcript (`/m/meeting-71ceb5`).

**Not yet re-checked, may already be fine (worth a quick live verify
before assuming any of these need work):**

- **New York City** -- New York City itself
(`legistar.council.nyc.gov` is the real calendar; this repo's own
Archive currently only has 2 old Viebit clips under a
`councilnyc.viebit.com` tenant that never matched a jurisdiction --
possibly the same class of gap as the Charlotte mis-attribution, not
confirmed).

  **Correction from the live check, 2026-08-21**: those Viebit clips *do*
  carry a jurisdiction today ("New York City, NY" on
  `/m/2025-12-19-nycc-pv-ch-cha-251218-163834-mp4`), so the "never matched
  a jurisdiction" half is stale. `legistar.council.nyc.gov` itself is
  still untried.

### Jurisdiction extraction & backfill

- **[JUST-DO-IT] The originally-reported eScribe subdomain rows (Bonnyville
  AB, Grand Valley ON, Point Edward ON, Boulder County CO, Beaumont AB,
  Mackenzie BC — "Townofbonnyville" and siblings) are STILL wrong in the
  live archive today** — this round's fix (`BACKLOG_DONE.md`'s
  "jurisdiction-bleed, third pass" entry) only corrects the CODE, so a
  FUTURE resolve of these customers comes out right; it doesn't touch what's
  already stored. Unlike the trim-repair/date/extension cases in the same
  fix (which the existing `POST /internal/jurisdiction/backfill-apply`,
  PR #165, can text-patch directly since the bled tail is still separable
  by word), these rows have no recoverable signal once glued together —
  "Townofbonnyville" cannot be turned into "Bonnyville" by re-running
  `finalize_jurisdiction()` on the stored string alone; it needs an actual
  re-resolve (`EscribeAssetFinder.resolve(url)` against the real source
  URL, now with the corrected subdomain logic, then re-ingest) — a heavier
  mechanism closer to `scripts/feed_granicus_auto_transcription.py`'s
  re-feed pattern than to #165's text-only endpoint. Not built this pass;
  a human should confirm the approach before writing it, same as any
  re-resolve script that writes to already-public pages.

- **[JUST-DO-IT] Bare/state-suffixed jurisdiction duplicates: root cause
  fixed 2026-08-21, production write step run the same day — 76 rows
  applied, 3 correctly held back, one residual left.** (See
  `BACKLOG_DONE.md`'s matching entry for the full WO-22 investigation.)
  Sequence, all completed: **(1)** re-ran `GET /internal/jurisdiction/
  bleed-backfill-candidates` after WO-22's state-consistency guard +
  generic-subdomain stoplist deployed — confirmed both prior known-bad
  repairs (`page_id 250` "Alameda County, CA" → "Bart, CA"; `page_id
  1108` "Modesto, CA" → "Agenda, CA") no longer appear in the candidate
  set at all. **(2)** `page_id 279` ("City of New Port Richey, FL" →
  "Clearwater, FL"), the third original suspect, is **confirmed CORRECT
  — verified live**: the page is City of Clearwater FL's own Council Work
  Session (`clearwater.granicus.com` clip 5244), and "New Port Richey"
  appears on it exactly once, inside agenda item 4.1, an interlocal
  gas-franchise agreement with that city. Same shape as the Peel
  Region/Caledon case — a repair to apply, not one to hold back.
  **(3)** Ran `POST .../backfill-apply?dry_run=false&only_ids=…`,
  filtered to every real text change **except** three consolidated
  city-county rows that silently drop the state suffix instead of adding
  one (`Jefferson County` → `Louisville`, `Davidson County` → `Nashville`,
  `Louisville / Jefferson County Metro` → `Louisville` — inconsistent
  with `Nashville-Davidson County, TN` → `Nashville, TN` getting a proper
  suffix; never diagnosed, WO-22 did not address them, promoted to its
  own live entry directly below). Dry run confirmed 76 applied / 3
  skipped-by-filter before the real write; applied for real: **76 rows**
  written (Dublin → Dublin, CA; Memphis normalizations; Clearwater; the
  Metchosin repair; and more), post-apply re-audit confirmed exactly the
  3 held-back rows remain candidates and nothing else; spot-checked the
  public Dublin page showing "Dublin, CA" live. **Only remaining part of
  this entry**: 3 of the original 16 examples (Ashland, Milton, San Jose)
  still have no
  confirmed real state** — each was checked live (their real source page
  and, where relevant, its channel-root page) and none carries reliable
  state-identifying text; Ashland sits on a shared/generic TelVue player
  domain, San Jose's Granicus pages are silent on state entirely, and
  Milton is genuinely uncertain between FL and eScribe's real Ontario,
  Canada customer base. Needs either a positive text match found some
  other way, or a second confirmed example before a domain registry
  entry can be added without guessing.

- **[NEEDS-AUDIT] Consolidated city-county repairs silently drop the
  state suffix instead of adding one — held back from the 2026-08-21
  backfill write, never diagnosed.** Three real candidates:
  `Jefferson County` → `Louisville`, `Davidson County` → `Nashville`,
  `Louisville / Jefferson County Metro` → `Louisville`. Inconsistent with
  the adjacent `Nashville-Davidson County, TN` → `Nashville, TN` case,
  which gets a correct state suffix through the same code path — so
  something about these three specifically is losing the state rather
  than validating one. Not yet root-caused; needs the same live-source
  investigation the Clearwater case above got before either applying or
  discarding them.

- **[NEEDS-AUDIT] Jurisdiction-bleed fix's single-word-tail gap, narrowed
  2026-08-18: "Brampton Meeting" and "Peterborough Attachments" are now
  fixed (a closed, curated stoplist — see `BACKLOG_DONE.md`'s "jurisdiction-
  bleed, third pass" entry); Castle Rock CO's "Town of Castle Rock
  Authorizing" is the one real case still open** — no confirmed second
  example of "Authorizing" as a bleed tail exists yet, so it stays off the
  stoplist per this repo's "don't guess, ground in real data" convention
  rather than being added speculatively. A single capitalized word is
  still genuinely indistinguishable from a legitimate short suffix using a
  word-count signal alone — confirmed by direct testing that lowering
  `_MIN_BLEED_WORD_RUN` to catch it would also wrongly trim real long
  names ("Lake Washington School District" → "Lake"). Closable the same
  way as "Meeting"/"Attachments" the moment a second real confirmed
  example of "Authorizing"-shaped bleed turns up.

- **[NEEDS-AUDIT] StatsCan/Census table completeness gap, surfaced
  2026-08-18 by gating eScribe's subdomain extraction (`BACKLOG_DONE.md`'s
  "jurisdiction-bleed, third pass" entry): a handful of real, currently-
  correct eScribe customer names would decline to blank on a FUTURE
  re-resolve, because the table PR #158 added doesn't cover them yet.**
  Confirmed via a full sweep of all 176 real eScribe + 253 real Granicus
  subdomains currently in production (`/internal/pages/all-urls`), not
  guessed: **Lloydminster** (AB/SK) and **Paso Robles** (CA) are
  unambiguous, well-known real places simply missing from the table;
  ~~**Durham Region / Peel Region / Region of Waterloo** are a whole
  category — Ontario's upper-tier "regional municipality" entities — the
  table doesn't include under that name~~ **partially fixed 2026-08-21 —
  see `BACKLOG_DONE.md`'s "jurisdiction-bleed, gate-blindness recovery"
  entry.** `scripts/build_jurisdiction_data.py`'s new
  `build_canada_regional_municipalities()` adds these 3 (both the "X
  Region" and "Region of X" real name forms) as a small curated list,
  grounded in StatsCan's own SGC 2021 structure file (Census division
  codes 3518/3521/3530) plus a 2019 provincial review Wikipedia cites —
  deliberately only these 3 confirmed-in-production customers, not the
  other 5 real Ontario regional municipalities that review also names
  (Halton, Muskoka, Niagara, Oxford, York), since no eScribe/Granicus
  customer for those has actually been confirmed live yet; **Chatham-Kent
  / Arran-Elderslie / Blue Mountains** are real Ontario municipalities
  lost purely on a hyphen-formatting mismatch (table likely has them as
  literal "Chatham-Kent" etc., and the wordninja-reconstructed candidate
  doesn't preserve the hyphen) — still open, not addressed by this pass.
  Scope note (still applies to the still-open Lloydminster/Paso Robles/
  hyphen cases): this can't retroactively blank an already-published page
  (the existing backfill endpoint only re-runs `finalize_jurisdiction()`
  on stored text, never re-invokes subdomain extraction) — it only
  affects a future new meeting from these customers, or an explicit
  re-feed.

- **[NEEDS-AUDIT] "RochestercityMN" root-caused, 2026-08-18 — a real page-
  title data-quality quirk on ONE specific customer, not an adapter code
  bug.** Investigated (not fixed, per this repo's "never build from
  assumption" rule and the specific ask that flagged this as
  out-of-scope-until-investigated): the real source is `app/platforms/
  iqm2.py`'s `_TITLE_RE`, which captures the jurisdiction verbatim from
  the page's own `<title>` tag (format `"{date} {time} {meeting_name} -
  Web Outline - {jurisdiction}"`). Rochester, MN's specific IQM2 tenant
  (`rochestercitymn.iqm2.com`) has "RochestercityMN" literally glued
  together as-is in its own page title — confirmed by checking IQM2's
  other real customer, Santa Clara County, CA, whose title correctly
  reads "...- Web Outline - The County of Santa Clara, California" (proper
  spacing, extraction working as designed). Not a Python f-string
  join-character bug as originally suspected — the regex is capturing
  exactly what's on the page; the glued text originates at IQM2's own
  vendor/tenant configuration for this one city. Only one example found
  (this is IQM2's only other confirmed customer besides Santa Clara), so
  not enough real data to design a general fix — if a second glued-title
  IQM2 customer turns up, this is the same shape of problem as eScribe's
  glued-subdomain fix above and could reuse `validated_label_extract()`
  the same way.

- **[NEEDS-AUDIT] Same sweep found one likely truncation case — the
  opposite failure from bleed (losing real characters, not gaining
  fake ones).** A bare "Pitt" appears as its own jurisdiction value on a
  real archived page, separate from "Pittsburg, CA" which also exists
  correctly elsewhere in the table — "Pitt" isn't a real jurisdiction on
  its own, so this reads as "Pittsburg, CA" chopped off mid-word. Only
  one example found; not enough to root-cause confidently yet (could be
  a regex length cap cutting a word in half, matching the
  mid-word-truncation signal already documented elsewhere in this file
  for title extraction — or something else). Worth watching for a second
  example before designing a fix.

- **[NEEDS-AUDIT] Swagit's jurisdiction extraction has no fallback at all when the page
  `<title>` doesn't end in a plain `"..., {2-letter state}"` shape — every
  special-purpose entity (school district, MPO, transit/utility authority,
  state agency) on Swagit comes through with a blank jurisdiction, even
  though the real jurisdiction-bearing text is sitting right there in the
  same title. Confirmed live 2026-08-15, found in the same `/meetings`
  audit as the Granicus entry above.** Root cause,
  [swagit.py:308](app/platforms/swagit.py:308): `_extract_metadata()`'s
  only jurisdiction source is
  `re.match(r"^(.*)\s*-\s*([^,]+),\s*([A-Za-z]{2})\s*$", raw_title)` — if
  that doesn't match, `jurisdiction` stays `None` with nothing else
  attempted (contrast with Granicus, which at least falls back to
  humanizing the subdomain). Live-verified on three real pages, fetching
  the raw `<title>` tag directly:
  - `sccoe.new.swagit.com/videos/383171` →
    `"Apr 22, 2026 County Board of Education - Santa Clara County Office
    of Education"` — no trailing `", ST"`, so the whole string ends up as
    the *title* instead (see
    [/m/apr-22-2026-county-board-of-education-santa-clara-county-office-of-education](https://redtaperecordings.com/m/apr-22-2026-county-board-of-education-santa-clara-county-office-of-education)),
    with the real jurisdiction text ("Santa Clara County Office of
    Education") never pulled out into its own field.
  - `ercot.new.swagit.com/videos/363073` →
    `"...Board of Directors Meeting - ERCOT - Electric Reliability
    Council of Texas"` — same shape, same gap.
  - `dfps.new.swagit.com/videos/355341` →
    `"Sep 12, 2025 DFPS Council Meeting\t - Texas Dept of Family and
    Protective Services"` — same gap, **plus a separate, smaller finding**:
    that's a literal tab character embedded in Swagit's own source
    `<title>` tag (confirmed via raw `curl`, not a copy artifact), which
    passes straight through unnormalized into this app's stored title —
    visible as a literal tab in the raw title text on
    [/m/sep-12-2025-dfps-council-meeting-texas-dept-of-family-and-protective-services](https://redtaperecordings.com/m/sep-12-2025-dfps-council-meeting-texas-dept-of-family-and-protective-services).
    ~~Cheap, low-risk fix on our side regardless of the jurisdiction gap:
    collapse internal whitespace (`\t`/`\n`) to a single space when
    extracting `raw_title`.~~ **Fixed 2026-08-16, wave 1 item 5 — full
    detail in `BACKLOG_DONE.md`.** The blank-jurisdiction gap itself (the
    other 16 examples below) is still open.

  16 real examples of the blank-jurisdiction gap turned up in one
  `/meetings` pass (Santa Clara County Office of Education, VIA
  Metropolitan Transit, Travis Central Appraisal District, Sioux City
  Community School District, Port of Galveston, Pelham Public Schools,
  HOMTV, Mansfield ISD, Louisiana Economic Development, Houston ISD,
  ERCOT, DFPS, Coppell ISD, Cecil County Public Schools, Broward MPO, plus
  one plain city — Rancho Cucamonga, CA — whose title also didn't end in
  the expected shape). Not designed yet: the real jurisdiction text
  appears in a different place per entity type (before the first ` - `
  for some, the whole remainder for others), so this isn't as
  mechanical a fix as it might look at first glance.

- **[JUST-DO-IT] PrimeGov's `_extract_jurisdiction()` still has no real structural fix
  for the SLC/Holladay false-positive — only patched for that one
  confirmed domain, not solved generally.** SLC's specific bug (every
  real `slc.primegov.com` meeting is fixed 2026-08-13 via a known-domain
  full override — see `BACKLOG_DONE.md`), but the underlying problem
  the earlier investigation surfaced is still real and open: an unscoped
  body-text search can't structurally tell a genuine page header from an
  agenda-item mention (confirmed against three real cities — OKC,
  Thousand Oaks, SLC — none of which separate cleanly by character
  position, and a bold-tag rule would fix OKC/SLC but miss Thousand
  Oaks's plain-prose header). **A fourth PrimeGov city with this same
  false-positive shape and no confirmed domain of its own would still
  hit the original bug** — the domain override only works because SLC
  happened to get reported and confirmed. Worth revisiting the
  structural options (bold-tag heuristic, etc.) against more real
  examples if this recurs, rather than adding a domain override per
  incident indefinitely.

- **[NEEDS-AUDIT] A Vimeo-hosted meeting usually resolves with no jurisdiction at all
  (residual of WO-29, 2026-08-21).** oEmbed's `author_name` is a Vimeo
  *account* name, not a place — real values range from "City of
  Sebastopol" (validates fine) through "CitySalisburyNC" /
  "cityofcorvallis" (glued) to "COC", which is Chicago's and is
  meaningless out of context. `vimeo.py` runs it through the shared
  Census-validated `validated_label_extract()`, which correctly declines
  rather than guessing — so most Vimeo-direct resolves carry
  `jurisdiction = None`, which keeps those pages out of `/state/{slug}`
  and `/j/{slug}` hubs. Wrappers that know their own jurisdiction
  (Chicago ELMS sets "Chicago, IL"; Sebastopol's real city page is
  reached through `generic_fallback.py`) are unaffected. The likely fix
  is a glued-label pass like the one `suiteone.py`/`townhallstreams.py`
  already share (wordninja split + trailing-state-code strip), applied to
  the account name — not attempted this pass, and worth doing only
  against several real account names at once, not one.

- **[LATER] Castus (`castus.py`) tenant-slug jurisdiction fallback is unconfirmed
  against any real second customer.** WO-19 (2026-08-21, see
  BACKLOG_DONE.md's Castus entry) built a full adapter — jurisdiction on
  the one real confirmed customer (Billings, MT, "comm7tv") comes from
  cross-checking a destinyhosted.com hyperlink found in that meeting's
  own agenda items, not the tenant slug itself (which is opaque channel
  branding, not a place name, on this one sample). `castus.py`'s
  `_jurisdiction_from_tenant_slug()` is a best-effort fallback for a
  future tenant with no destinyhosted (or otherwise-recognized) agenda
  hyperlink at all, and whose slug genuinely does look like a place name
  (e.g. a hypothetical "cityofsomewhereca") — real, generic
  Census-backed logic, but nothing has actually exercised it against a
  real second Castus customer yet. Also unconfirmed: whether every real
  Castus customer's agenda items carry a destinyhosted (or any other
  jurisdiction-bearing) hyperlink at all, or whether "comm7tv" happened to
  have one by coincidence of also using destinyhosted for agendas.
  Revisit once a second real customer (ideally one *without* a
  destinyhosted-linked agenda) is found — check the sample sheet or a
  fresh dotgov/CDX pass first.

- **[NEEDS-AUDIT] Census-table baseline validation of all 649 archived
  jurisdictions (2026-08-15, workstream 1 of
  `JURISDICTION_METADATA_PLAN.md`) — one real signal from it is still
  unbuilt.** Numbers: 510 valid as-is, 73 reachable by longest-valid-
  prefix trim, 44 not in table, 22 blank. The trim bucket splits cleanly
  on a tail-sanity check (lowercase prose/roman numerals/digits in the
  discarded tail): 16 true bleed cases (every one a correct repair —
  Hercules, Boston, Fort Worth...) vs 57 legitimate long entities where
  trimming would *destroy* a correct name ("Lake Washington School
  District" → "Lake", "Bay Area Headquarters Authority" → "Bay") — **so
  trim must always be gated on bleed signals, never applied bare.** Three
  bleed cases the current signals miss (Sarasota/Hollywood/Hampton —
  Title-Case/ALL-CAPS bleed, of which Sarasota was closed 2026-08-17);
  **a mid-word-truncation signal (tails ending "the Tex", "servic",
  "Standa" — the regex's own 40-char cap cutting words in half) would
  catch all three, and is still unbuilt.** A real live instance of that
  same signal turned up independently on the title side (a title cut off
  as "...Exhibit 1 was adde"), so it is confirmed, not hypothetical. Every
  other finding from this audit is now closed — full per-bullet history
  moved to `BACKLOG_DONE.md` 2026-08-21. `baseline_validation.csv` no
  longer exists in any session's scratchpad; regenerate via the script
  logged in `JURISDICTION_METADATA_PLAN.md`'s workstream 1 before
  re-running any of this.

- **[NEEDS-AUDIT] Tulare County/Visalia jurisdiction misattribution —
  not confirmed fixed, no known real hosting domain found.**
  Residual gap from BACKLOG_DONE.md's "Jurisdiction misattribution" entry
  (2026-08-19): of 4 real confirmed jurisdiction-misattribution instances
  investigated that session, 3 were root-caused and fixed (Douglas MI/"The
  Village, OK", Courtenay BC/Burlington, Victorville/San Bernardino
  County), but "Tulare County misattributed to Visalia" (Visalia is Tulare
  County's real, correct county seat) was not.

  The fix for the other two cross-jurisdiction cases
  (`extract_jurisdiction_chain()`'s new cross-check in
  `app/utils/jurisdiction_enrich.py`) only engages when the page's own URL
  carries a subdomain that independently validates against the Census
  tables — no such domain could be found for Tulare County specifically.
  Checked live 2026-08-19: `tularecounty.granicus.com`,
  `tulare.granicus.com`, and `tularecounty.civicweb.net` are all dead
  (`NotFound`/no DNS); `tularecounty.swagit.com` redirects to a 404;
  `tularecounty.legistar.com` does resolve (200) but wasn't investigated
  further. ~~Even a plausible `tularecounty`-shaped subdomain wouldn't
  validate through the existing wordninja-based subdomain validator
  regardless of the cross-check fix — `wordninja.split("tularecounty")`
  mis-segments to `['tul', 'are', 'county']` rather than
  `['tulare', 'county']` (confirmed live), a separate, narrower dictionary
  gap in `_validated_label_extract()`.~~ **That second half is fixed as of
  2026-08-21 (WO-22)**: wordninja still mis-segments the label exactly as
  described, but `_validated_label_extract()`'s new tier 4 strips the
  trailing "county" and re-attaches it to the glued remainder, so
  `tularecounty` now validates as "Tulare County" (unit-tested in
  `tests/test_jurisdiction_enrich.py`). The entry stays open for the half
  that still blocks it — no real, live Tulare County meeting-hosting
  subdomain is known, so there's still nothing to run the cross-check
  against.

  Next step: find the real originating URL for this misattribution (check
  `tularecounty.legistar.com` first, or the original session's own
  discovery notes if recoverable) and either (a) confirm the existing
  cross-check fix already covers it once the real subdomain is known, or
  (b) if the real subdomain is `tularecounty`-shaped, first fix the
  wordninja mis-segmentation before the cross-check can engage at all.

- **[LATER] Domain guesser matched a same-named US state's real portal
  instead of the county's -- fixed at the source, 6 wrong rows reverted,
  2026-08-21.**
  `find_gov_domains.py`'s unqualified `{bare_name}.gov` candidate
  systematically collides with a state's own real portal whenever a
  county's bare name (after stripping "County"/"Parish"/etc.) is itself a
  full US state name -- most states are literally hosted at
  `{statename}.gov`. Confirmed live: 6 rows in `jurisdiction_coverage.csv`
  had a wrong domain from this -- Delaware County PA/OH/IN and Oklahoma
  County, Utah County, Nevada County CA all got the matching *state's*
  portal (`delaware.gov`, `oklahoma.gov`, `utah.gov`, `nevada.gov`) instead
  of their own county government's site. The guesser's own
  bare-name-appears-on-page anti-false-positive check (added earlier this
  session for the `townof`/`cityof` false-positive class) can't catch this
  one -- the state's own name trivially appears on the state's own
  homepage. All 6 rows' domain-derived fields were reverted to blank in
  `jurisdiction_coverage.csv` (a research file, not under git); the root
  cause is fixed in `find_gov_domains.py` (skip the unqualified `{s}.gov`
  candidate when the bare name is a US state name; qualified variants like
  `{s}{st}.gov`/`{s}county.gov` are unaffected). No real domain re-found
  for these 6 yet -- lower priority given their small remaining population,
  open if revisited.

- **[LATER] ~25 smaller consolidated city-county governments still need
  a real domain -- 13 of ~38 already done, see BACKLOG_DONE.md,
  2026-08-20/21.**
  Real, structurally different gap from ordinary domain-guessing: a
  consolidated city-county's real domain often shares **no text at all**
  with the county's own Census name (Marion County, IN's real domain is
  `indy.gov`, Indianapolis's brand -- no guess built from the string
  "Marion" could ever produce that). 13 of the ~38 nationally have been
  found and verified (Marion/Indianapolis IN, Davidson/Nashville TN,
  Jefferson/Louisville KY, Muscogee/Columbus GA, Fayette/Lexington KY,
  Duval/Jacksonville FL, Clarke/Athens GA, Richmond/Augusta GA, Wyandotte/
  Kansas City KS, East Baton Rouge Parish LA, Orleans Parish/New Orleans
  LA -- see BACKLOG_DONE.md's "Consolidated city-county domain lookup"
  entry for the real near-miss caught applying these). San Francisco
  County, CA and Denver County, CO were never part of this gap -- their
  county's Census name is the same word as the consolidated city, so
  ordinary guessing already works for them.

  **Still open**: the smaller/harder-to-verify remainder -- Anaconda/Deer
  Lodge County MT, Butte/Silver Bow County MT, Houma/Terrebonne Parish LA,
  Hartsville/Trousdale County TN, Lynchburg/Moore County TN, and several
  small Georgia ones (Cusseta/Chattahoochee County, Georgetown/Quitman
  County, Preston/Webster County, Statenville/Echols County) -- lower
  population, lower priority, real gap not yet closed.

### Adapter & platform gaps

- **[NEEDS-AUDIT] Vimeo captions and on-demand Whisper audio are the same single
  blocker, and it is still unsolved (residual of WO-29, 2026-08-21 — see
  `BACKLOG_DONE.md` for the full context).** Real, populated English
  WebVTT genuinely exists on at least one of these meetings — Salisbury
  NC's real 7/21/2026 council meeting (`vimeo.com/1212025580`),
  confirmed via a real browser, served from a signed
  `captions.vimeo.com/captions/{id}.vtt?expires=...&sig=...` URL. It is
  not reachable server-side: that URL appears only inside
  `player.vimeo.com/video/{id}/config`, which returns a plain **403** to
  every non-browser client, and the same signed response is the only
  place the real progressive media file lives — which is why "fetch
  captions" and "extract audio for Whisper" are one problem, not two.
  `vimeo.com/{id}` also sometimes serves a real Cloudflare "Verify you
  are human" challenge (hit live on Spokane WA), which this app must
  never attempt to auto-solve. So the shipped Vimeo adapter is
  deliberately video-only, with a `transcript_warnings` line that says
  so and points the viewer at the player's own CC button. The plausible
  unlock is the same real-headless-browser approach `headless_browser.py`
  already built for Minneapolis LIMS/SLC (render the player, capture the
  signed URL it requests) — untried here, and not guaranteed to work
  every time if the Cloudflare challenge is probabilistic. Note the
  Player SDK's `getTextTracks()` *does* report a real track list from the
  browser (confirmed live on Salisbury) and a `cuechange` event exists,
  but neither yields a whole transcript without playing the entire video
  — not a shortcut around this.

- **[NEEDS-AUDIT] Chicago ELMS's 473 real agenda items have nowhere honest to go
  (residual of WO-29, 2026-08-21).** `agenda.groups[].items[]` from
  Chicago's own API is genuinely rich — matter title, matter type,
  record number, action taken, vote type — and carries **no time offsets
  of any kind**, confirmed directly against the real fixture (there's a
  test asserting it). Unlike LIMS/Hyland/IQM2 there's nothing to join
  against a video position, so populating `agenda_items` would mean
  inventing timestamps and shipping 473 rows that all seek to 0:00. The
  adapter surfaces the real agenda PDF as `agenda_link` instead, so
  Chicago pages have a working agenda *link* but no clickable agenda
  *items*. Making that item text visible would need a new
  untimestamped-agenda-text field on `ResolvedMeeting`, a matching
  Archive column + Alembic migration, and template work on both
  surfaces — a real, scoped follow-up, deliberately not smuggled into
  WO-29. Worth checking first whether any other already-supported
  platform has the same shape (rich agenda text, zero timestamps), since
  one shared field would then pay for itself more than once.

- **[JUST-DO-IT] Residual gaps left behind by WO-30's city-YouTube-channel
  fallback (2026-08-21) -- three real ones, each measured, none blocking.**
  Split out per this repo's own "if a completed item left a residual gap,
  make it its own live entry" convention; see `BACKLOG_DONE.md` for the
  build itself.
  1. **The channel listing only goes back ~400 entries per tab**, because
     yt-dlp's channel extraction is *not* lazy -- `extract_info()` returns
     a fully-materialized list, so `playlistend` is the only way to bound
     the call (measured: 34s for one full Philadelphia channel vs ~6s for
     400 entries). On Philadelphia's channel, the busiest of the four,
     400 entries reaches roughly 2025-06; a real 2024-06-05 Committee on
     Finance meeting was confirmed to fall outside it and decline. Older
     meetings therefore still show "No video link found." Fixable by
     caching listings in the DB and paginating deeper over time, or by
     using a per-body playlist where a city publishes one -- neither
     attempted.
  2. **A city that posts the same meeting twice declines.** Real case:
     Philadelphia's 2026-08-06 Committee on Education exists both as a
     `/streams` archive and a `/videos` re-upload, and nothing in either
     title says which is canonical, so `_pick()` declines. Same for
     Baltimore's 2026-06-17 "Board of Estimates Meeting" vs "Post Board of
     Estimates". Declining is the correct posture as built, but a real
     rule (prefer the longest? prefer the `/streams` original?) would
     recover a handful of meetings per city -- needs more real examples
     before committing to one.
  3. **No adapter-canary coverage for this path specifically.**
     `scripts/adapter_canary.py` is one URL per registered platform, and
     this rides on `legistar` (no new `platform_name`), so
     `tests/test_adapter_canary.py`'s coverage assertion passes untouched
     -- but a break in the channel matcher would only surface if the
     single Charlotte, NC canary URL happened to exercise it, and it
     doesn't. The honest fix is letting `CANARY_URLS` hold more than one
     URL per platform (a real per-tenant coverage gap that predates this
     work and applies to every multi-tenant adapter here), not bolting a
     second `legistar`-ish key onto the current dict shape.

- **[LATER] PrimeGov's own better date/title still isn't threaded through
  for Granicus `MediaPlayer.php?event_id=...` pages.** The residual left
  by the 2026-08-21 `MediaPlayer.php` fix (full root cause — `event_id`
  is a separate, non-interchangeable Granicus id namespace from `clip_id`,
  and those pages genuinely have no video yet — plus the 4 verified
  cities and 2 real subdomain-name corrections, in `BACKLOG_DONE.md`).
  PrimeGov's own API carries a better date and title for these meetings
  than the Granicus page does; nothing passes it along.

- **[LATER] Town Hall Streams: real transcript endpoint still
  unconfirmed-positive; 88-id Wayback population not yet ingested
  (2026-08-20).**
  Residual gaps left behind by the townhallstreams.com adapter build (see
  `BACKLOG_DONE.md`'s "Town Hall Streams: new platform adapter built" entry
  for the full investigation and what was actually shipped).

  - **Transcript AJAX endpoint still empty on every real sample checked** —
    now 7/7, not 2/2 (all 7 of BACKLOG_DONE's sample URLs re-checked live
    2026-08-20). `townhallstreams.py`'s `_check_for_transcript()`
    deliberately does NOT parse a non-empty response (no confirmed format
    exists — the page's own JS just dumps it as a raw HTML fragment via
    `.html(response)`, no per-cue timestamp shape visible anywhere in the
    client code) — it only surfaces a `transcript_warnings` entry so a real
    positive example doesn't go unnoticed if one ever appears. No actual
    parser exists yet; build one once a real positive response is found.
  - **Enumeration not yet done.** A Wayback CDX scan already surfaced 88
    distinct `location_id` values (range 28–175) as a real, cheap starting
    population for scaling past the 7 confirmed samples (same CDX-domain-
    scan method as every other platform, see
    `~/Documents/rtr-business/research/ENUMERATION_METHODS.md`'s §12) — the
    adapter itself is done and live-tested, but nothing has actually walked
    that population to find real meeting `id`s per town or bulk-ingested
    them into the Archive yet.

- **[LATER] SuiteOne Media: unconfirmed CDX leads and PDF-transcript
  fallback (2026-08-21).**
  Residual gaps left behind by the new SuiteOne Media (suiteonemedia.com)
  adapter build — see `BACKLOG_DONE.md`'s "SuiteOne Media: new platform
  adapter built" entry for the full investigation and what was actually
  shipped (`app/platforms/suiteone.py`). The jurisdiction gap that used to
  head this list (`stmarysga`/`camaswa` recovering no jurisdiction at all)
  was fixed 2026-08-21 in `jurisdiction_enrich.py` itself, exactly where
  that entry said it belonged — see `BACKLOG_DONE.md`'s "WO-22" entry.

  - **5 of the 11 CDX-derived tenant leads never got individually verified
    live**: `mcallentx`, `southbendin`, `prescottaz`, `richlandwa`,
    `laytonut` all 404 on their home page as of 2026-08-21 — dead leads (or
    a since-retired customer), not a bug in the adapter. The other 6
    (`lorainoh`, `pacificgroveca`, `tuscaloosaal`, `camaswa`, `holladayut`,
    `stmarysga`) are confirmed live and are what `tests/fixtures/suiteone/`
    is built from.
  - **No confirmed real case of the `/event/GetDocumentFile/{title}?did=N`
    endpoint serving a "Transcript" PDF on a meeting that has NO real VTT
    captions.** The one confirmed real "Transcript" PDF (Pacific Grove,
    event 2099) sits alongside that same event's real, populated VTT — so
    there's no positive example yet of this being the *only* transcript
    source for a meeting. `suiteone.py` deliberately does not attempt to
    fetch/link that PDF as a fallback (per this repo's "don't claim a data
    path works without a positive example" convention) — worth building
    once a real VTT-less-but-Transcript-PDF-present meeting is found.

- **[LATER] Granicus's own captions.vtt appears to hard-cap at exactly 36,000 cues
  per file, cutting a long meeting's transcript off mid-sentence with no
  warning — a source-side limitation, not a bug in this app's fetch/parse
  code, confirmed live 2026-08-15.** Found while reviewing the 204-URL
  Granicus dry-run batch (see `GRANICUS_DRY_RUN_BRIEF.md` in
  `rtr-business/research/`): three unrelated jurisdictions — College Park
  GA (`college-park.granicus.com/player/clip/1475`), Coral Gables FL
  (`coralgables.granicus.com/player/clip/2876`), and Marion County FL
  (`marionfl.granicus.com/player/clip/1368`) — all resolved to *exactly*
  36,000 segments, an implausible coincidence for three different meetings
  of different real lengths (last cue timestamps ~3.09h, ~3.4h, ~3.3h
  respectively). Root-caused by fetching each `captions.vtt` directly
  (`curl`, not through this app): College Park's file is a real, complete,
  untruncated-by-us 2.7MB download (confirmed via `Content-Length`/full
  read) containing precisely 36,000 `-->` cue markers, and the file's last
  cue ends mid-word: `"said the tip of the iceberg We"` with no closing
  punctuation, immediately followed by end-of-file — not a natural
  sentence/meeting end. Coral Gables's raw VTT, checked the same way, cuts
  off identically mid-phrase at cue 36,000: `"SETUP INCLUDES TENTS, THE
  SCREEN,"`. No `36000`/cue-count cap exists anywhere in this repo's own
  code (`app/platforms/granicus.py`, `app/utils/vtt_parser.py` — grepped
  for it directly), so this is Granicus's own captioning pipeline (almost
  certainly its live-auto-caption path, not a human-authored file)
  silently stopping at a fixed cue count rather than at the meeting's
  actual end.

  ~~**Not yet built**: any detection or user-facing signal for this.~~
  **Fixed 2026-08-16, wave 2 item 7 — full detail in
  `BACKLOG_DONE.md`.** A `transcript_warnings` entry now flags any
  Granicus resolve whose segment count is exactly 36,000, per the "cheap
  first heuristic" below. **Still open**: this only catches the
  exact-cap case, not a case where the true cap is some other round
  number on a different Granicus customer's config, which hasn't been
  checked. Worth checking a handful of the other long-running meetings
  in the same 204-URL batch (anything approaching 30-36k segments) to
  see whether the cap is a fixed constant across all Granicus customers
  or varies.

- **[LATER] YouTube-backed meetings' transcripts run through
  `scripts/fetch_youtube_transcripts.py` on a daily `launchd` schedule
  now (both shipped 2026-08-10, see BACKLOG_DONE.md) — real remaining
  gaps below, not "nothing runs automatically yet."** The server
  structurally cannot fetch these itself: confirmed live that yt-dlp,
  plain timedtext requests, *and* youtube-transcript-api (a different
  InnerTube recipe, tested specifically to close this question) are all
  blocked from Render's cloud IP, while the same library works perfectly
  from a home connection. Open follow-ups, in rough order:
  - **Whisper fallback for YouTube videos with no captions at all**
    (analysis option 8): extend the same local script to yt-dlp the
    *audio* (works from residential IPs) for queue entries whose
    caption fetch finds nothing, then feed local `faster-whisper` directly
    — **decided 2026-08-10: local, not the worker**, and deliberately
    **lower priority than everything else** in this backlog (most YouTube
    videos already have real captions; this only covers the rarer
    no-captions case). Not yet built. Still distinct from
    `scripts/transcribe_backlog_locally.py` (built 2026-08-16, see
    `BACKLOG_DONE.md`) even though both run local `faster-whisper`: that
    script works the general (any-platform) has-no-transcript backlog via
    direct remote audio extraction (`extract_chunk_audio()`), which
    can't work on a YouTube-backed page's `video_url` (a
    `youtube.com/embed/{id}` page, not something `ffprobe`/`ffmpeg` can
    pull audio from) — confirmed by that script's own candidate list
    still including YouTube pages, filtered out client-side rather than
    silently dropped. This yt-dlp-audio path is still what closes that
    gap, whenever it gets built.
  - **Human/source-side option (analysis option 9), user-side**: for
    big cities, ask the clerk for the caption file directly, or
    manually export from YouTube Studio-visible sources — the user is
    pursuing this angle themselves; `bulk_ingest.py`-style manual
    pushes can carry whatever comes back.

- **[IMPROVEMENT-ROUND] Four platforms account for ~78% of the 470 real
  live pages with no jurisdiction — a per-platform jurisdiction-extraction
  gap, not scattered noise.** Surfaced by WO-38's `/internal/
  low-trust-pages` call against production 2026-08-21 (see the "low-trust
  queue is really a jurisdiction-quality queue" entry above for the
  queue-mechanics half of this finding). Per-platform breakdown of the
  474 total (full numbers in `BACKLOG_DONE.md`'s WO-38 entry): **eScribe
  117, Cablecast 104, YouTube 78, Swagit 72** — 371 of 474 rows on just
  these four, versus Granicus 34, IQM2 33, CivicClerk 24, unknown 7,
  ChampDS 4, TelVue 1. Worth a dedicated investigation on those four
  specifically (why does jurisdiction extraction fail this often on
  exactly these adapters, and is it one shared root cause per platform or
  scattered per-tenant gaps) rather than treating each row as a one-off.
  Not investigated further here — this is a sizing finding, not a
  diagnosis.

## Reliability, ops & cost

### Media-source reliability

#### `[NEEDS-AUDIT]` Some old/archived Granicus clips' `chunklist.m3u8` genuinely times out at Granicus's own origin (real 504, not a rate limit)

Root cause confirmed 2026-08-21; corrects two earlier wrong theories in
this same entry. See also **Standing decisions** — do not raise
`_SUBPROCESS_TIMEOUT_SECONDS` to match Granicus's own gateway timeout.

**Root cause nailed down precisely, superseding both earlier theories
below (kept for the record, not because they're still believed).**
Reproduced directly with `ffprobe -v verbose` against the real resolved
`archive-stream.granicus.com` URL for Fountain Valley CA clip 607: with
the app's own real request headers (`realistic_headers()` in
`media_probe.py` -- a real desktop User-Agent plus a `Referer` matching
the meeting's own Granicus subdomain), `ffprobe` successfully parses the
top-level `playlist.m3u8`, follows it to the real `chunklist.m3u8` (the
actual segment index), and **that specific request hangs for minutes
before Granicus's own CloudFront edge gives up and returns a real `504
Gateway Timeout`** (one run: 6 minutes; a later run against the same
clip: ~4 minutes, same 5XX). This is Granicus's own origin failing to
answer in time for this specific archived asset -- not a rate limit, not
a block, and not fixable from this app's side by retrying faster or
pacing requests differently. `media_probe.py`'s own `_SUBPROCESS_TIMEOUT_
SECONDS` (120s) is shorter than Granicus's own gateway timeout, so in
production this always looks like our own "ffmpeg timed out after 120s"
first -- we never actually see the 504 that eventually would have
arrived, just our own earlier giving-up.

**Two earlier theories in this entry's history, now understood
correctly:**
1. *"CloudFront blocks a residential IP after rapid requests"* (original
   finding) -- the fast 403 behind this was real, but caused by
   something much simpler: the very first live test used a plain `curl`
   with no `Referer` header at all. Granicus's CloudFront distribution
   enforces hotlink protection (a `Referer` matching the meeting's own
   subdomain) and fast-rejects with 403 when it's missing/wrong --
   confirmed directly: the same bare-header `curl`/`ffprobe` call
   against Fountain Valley's real URL got an instant 403 (144ms) just
   now, while the *exact same URL* with the real `Referer` the app
   actually sends took over a minute before genuinely hanging on the
   chunklist. Not a rate limit or an IP block at all -- just a
   self-inflicted missing header in ad hoc testing.
2. *"Not IP-specific, since Render's worker hit the same timeout"*
   (first update) -- correct as far as it went (the failure isn't
   IP-specific), but attributed to generic "source flakiness" rather
   than the precise mechanism above.

**Real, if partial, good news: this seems to sometimes clear on its
own.** King County clip 11547 failed identically (ffmpeg timeout / 504
signature) on two earlier attempts (from this Mac, and from Render's
worker, job 433) over about a day -- then, on a later direct `ffprobe`
retest, resolved cleanly with a real duration (6578s) and no hang at
all. Consistent with (not proven to be) an on-demand rehydration/cold-
storage delay on Granicus's own archival backend for older, rarely-
accessed clips -- the first request(s) trigger a slow wake-up that can
outlast even CloudFront's own gateway timeout, and a later request
succeeds once whatever needed to warm up has. Fountain Valley clip 607,
by contrast, failed the same way on *every* attempt across the same
session (at least 4 separate tries, spread over roughly an hour) --
consistent with this specific archived asset being genuinely broken/
gone at the source rather than just cold, matching this same meeting's
already-known history as a real edge case (see CLAUDE.md's "genuinely
garbled at the source" / legacy-Flash-player note on this exact
meeting).

**Not fixed, and may not be fixable from this app's side.** Real
implications: (1) a "ffmpeg timed out" failure on a Granicus meeting
should not be assumed fixable by retrying immediately -- for a
cold-storage-shaped case it may need hours, for a genuinely-dead asset
it may never succeed; (2) worth having `process_one()`/`extract_chunk_
audio()` and `probe_duration()` distinguish a real 5XX-after-a-long-hang
from an ordinary connection-level timeout in their logging, so this
specific pattern doesn't keep getting rediscovered from scratch; (3) not
worth raising `_SUBPROCESS_TIMEOUT_SECONDS` to match Granicus's own
~4-6 minute gateway timeout blindly -- that would tie up a worker chunk
slot for minutes on every genuinely-dead asset, trading a fast, clear
failure for a slow, identical one.

#### `[NEEDS-AUDIT]` A single job still makes N consecutive same-host pulls, and the 120s ffmpeg timeout is fixed

The residual after WO-40 measured the failure pattern (2026-08-21).

WO-40 tested the "workers hammer one host across consecutive jobs, so
round-robin the queue by host" theory against all 514 production jobs and
**falsified it** — `same_host_different_job` failure pairs within 10
minutes: **0**; chunk 0 is 3-4x more failure-prone per attempt than any
later chunk (an accumulating rate limit predicts the opposite). No queue
reprioritization was built. Full numbers, method and the
`GET /internal/transcription-failure-analysis` endpoint that produced
them: `BACKLOG_DONE.md`.

**What that deliberately did not address**, and is genuinely open: a
21-chunk meeting is still 21 consecutive pulls from one host inside one
job, because `claim_next_chunk()` claims a whole *job* (despite its name)
and the worker holds it through every chunk. Queue ordering cannot reach
inside a job.

**Do not "fix" this by spreading within-job pulls.** The measured data
says the two real mechanisms both argue against it:
- *Cold storage / rehydration* (the dominant shape, and independently
  confirmed live via `ffprobe` — see the Granicus `chunklist.m3u8` 504
  entry above): within-job clustering **helps**, since chunk 0 warms the
  asset for chunks 1..N. Spreading would hurt.
- *Persistently slow source* (job 507 failed 26 of 31 chunks and still
  completed; job 411, 10 of 11): pacing changes nothing — every chunk
  sits near the fixed 120s limit regardless of when it's requested.

**The real open question is the timeout, not the ordering.**
`media_probe.py`'s `_SUBPROCESS_TIMEOUT_SECONDS` is a flat 120s for every
source. Two things worth considering, neither yet evidenced enough to
build:
1. Detect the slow-source shape early — a job whose first few chunks all
   need retries is going to need them throughout — and either widen that
   job's own timeout or defer it, rather than grinding 26 retries through
   the same worker slot.
2. Distinguish a real 5XX-after-a-long-hang from an ordinary
   connection-level timeout in logging, so this pattern stops being
   rediscovered from scratch (already noted in the Granicus entry above).

Note the priority framing that motivated the original idea still holds
and is worth preserving in anything built here: a real user-submitted
`PRIORITY_MEDIUM` job must never be starved behind automated
`PRIORITY_LOW` backlog work.

**Sizing caution before spending anything here**: ffmpeg timeouts are
loud but small — **2 of 218** terminal job failures. 129 are `No usable
audio or video source was found`. That is where the volume actually is.

### Transcription queue & workers

- **[LATER] `list_transcription_backlog_candidates()` still does a real N+1 query
  pattern, found 2026-08-21 while building the daily-report summary
  query.** Unlike `find_auto_transcription_candidate()` (rewritten
  2026-08-17 to a SQL `_good_default_transcript_exists()` predicate after
  its old Python-scan shape was confirmed the #1 consumer of production
  DB time — see BACKLOG_DONE.md), `list_transcription_backlog_
  candidates()` (`archive/db/crud.py`) still does `SELECT * FROM
  meeting_pages`, then a separate `_has_good_transcript()` +
  `_in_auto_transcription_cooldown()` DB round trip *per page* in a
  Python loop — its own docstring already says so ("Full Python-side
  scan over every page, same 'fine at today's scale, revisit at real
  scale' reasoning"). Each individual query is cheap
  (`_has_good_transcript()` only selects `content_hash`/
  `transcript_warnings`, never `segments`), so this isn't the
  102MB-JSON-load class of incident the search/candidate-sweep entries
  above describe — but it's still O(n) round trips, and `GET
  /internal/transcription-backlog` (the route built on this function)
  now gets hit **hourly** by `scripts/bulk_queue_transcription_backlog.py`'s
  own scheduled workflow (added the same day, see `BACKLOG_DONE.md`) where
  previously only a human ran `scripts/transcribe_backlog_locally.py`
  occasionally. Not fixed here — `crud.get_transcription_queue_summary()`
  (added the same day, for the daily report) needed only a *count*, not
  the full candidate list, so it reuses the fast
  `_good_default_transcript_exists()` predicate directly rather than
  inheriting this function's slower shape. Worth rewriting
  `list_transcription_backlog_candidates()` the same way
  `find_auto_transcription_candidate()` was, if hourly production load
  ever makes this a real, measured problem (check `pg_stat_statements`
  the same way the 2026-08-17 fix was diagnosed, don't assume).

- **[LATER] Second transcription worker's auto-generation TOCTOU race —
  avoided by construction at N=2, not fixed at the DB layer** (dropped
  from this file during the 2026-08-21 reorg; restored here since
  `CLAUDE.md` and `render.yaml` both still point at it by name).
  `render.yaml` defines `rtr-transcription-worker-2` as its own distinct
  service block specifically because a `numInstances` replica gets
  IDENTICAL env vars, and this pair needs to differ in exactly one:
  `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` is deliberately left unset on the
  second worker. `claim_next_chunk()` is genuinely race-safe for any
  number of workers (`FOR UPDATE SKIP LOCKED`) — the real gap is
  idle-time auto-generation: `maybe_generate_auto_job()` →
  `find_auto_transcription_candidate()` (a plain unlocked SELECT) →
  `create_transcription_job()`'s own unlocked check-then-insert, no
  unique constraint or row lock. Two workers both idle at once — routine
  once the queue trickles to empty — both configured with a real
  `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` could both pass the check for the
  same page before either commits: two duplicate low-priority jobs, real
  wasted compute plus two completion emails (`promote_transcript_version()`
  still cleanly settles on one final version, so it's wasteful, not
  data-corrupting). Leaving the env var unset on worker-2 makes
  `maybe_generate_auto_job()` short-circuit before ever reaching the
  unsafe path — the race is structurally impossible on this specific
  pair, not solved. **A third auto-gen-enabled worker (or setting that
  var on this second one) reintroduces it immediately.** The real fix, if
  this needs to scale past two workers, is a unique partial index / row
  lock in `create_transcription_job()`'s existing-job check — not another
  env-var-omission trick. Full build log in `BACKLOG_DONE.md`.

### Search Console, structured data & SEO plumbing

- **[HUMAN] Search Console "Page indexed without content" (alert 2026-08-17)
  is still genuinely unexplained — and specifically NOT explained by
  the outage above** (that started 09:25 PT today; the alert predates
  it, and Google's last crawl of the flagged `/m/welcome-to-clerkbase`
  was 2026-08-14). Best current theory, unverified: that page's stored
  content on Aug 14 was placeholder-shaped — its title was literally
  "Welcome to ClerkBase" (a ClerkBase landing-page title, not a
  meeting) — before a later re-resolve (WO-15's stale-page refresh, or
  a manual one) turned it into the real Yellow Springs, OH 2022-02-07
  village-council meeting it shows today. If so, it's the "adapter
  stored a landing page as a meeting" class of bug (see the ClerkBase
  row in README's platform table — only one real customer checked so
  far), and Google's verdict was correct for what it saw. Cheapest
  next step: Search Console → URL Inspection on that slug → "Request
  Indexing", then see whether the flag clears on recrawl of the
  now-real content; if it does, this is closed with no code change. If
  the flag list has *other* URLs beyond that one, paste them — that
  would point at a broader thin-content shape worth chasing. Partial
  mitigation shipped 2026-08-17 regardless: genuinely empty pages (no
  video/agenda/transcript — 17 live at the time) are now `noindex`ed and
  excluded from browse/sitemap/feed at query time, see `BACKLOG_DONE.md`
  "Empty ("zero-value") meeting pages"; if the flagged URLs turn out to
  be that shape, this closes on recrawl with no further code change.

- **[IMPROVEMENT-ROUND] Google Search Console flagged 3 "Videos" structured-data issues
  site-wide (alert received 2026-08-12)**: missing `thumbnailUrl`
  (critical — blocks video rich-result eligibility), plus `uploadDate`
  reported as both an invalid datetime value and missing a timezone
  (non-critical). Both trace to the same `VideoObject` JSON-LD block in
  [meeting_page.html:37-66](archive/templates/meeting_page.html:37-66):
  - ~~`thumbnailUrl` is omitted entirely~~ **Fixed in two passes —
    full detail in `BACKLOG_DONE.md`.** 2026-08-14 ("VideoObject.
    thumbnailUrl + Clip key moments"): YouTube-backed pages emit
    `thumbnailUrl` plus `og:image`/`twitter:card` from the free,
    predictable `i.ytimg.com` URL, and pages with real agenda timestamps
    gained `Clip` "key moments" markup in the same pass. 2026-08-21
    (WO-28, "Meeting card images"): direct mp4/m3u8 pages — the majority
    of the Archive — now get a real `ffmpeg`-extracted frame from the
    meeting's own video, stored in a new `meeting_page_thumbnails` table
    and served from `GET /m/{slug}/card.jpg`, targeted at the shared
    `?t=` moment when there is one. **[HUMAN] Still to confirm**: a
    Search Console re-crawl actually clearing the critical flag. Nothing
    in this repo can verify that — re-run URL Inspection on the San
    Carlos page (the one whose 2026-08-21 inspection reported this as
    its *only* critical issue) once it has been recrawled.
  - ~~`uploadDate` missing a timezone~~ **Fixed 2026-08-14 — full detail
    in `BACKLOG_DONE.md`'s "Wave 1" entry.** Now emits
    `date + "T00:00:00Z"`.
  - ~~`uploadDate` "invalid datetime value"~~ **Template side fixed
    2026-08-21 (WO-27) — full detail in `BACKLOG_DONE.md`.** The template
    used to concatenate `page.date` into `uploadDate` (and into Event
    `startDate`) with no validation anywhere in the chain — `date` is a
    free `Optional[str]` on `ResolvedMeeting`, on `IngestRequest`, and a
    `String(20)` column — so a malformed stored value went straight into
    the emitted markup. Both now go through
    `iso_meeting_date()` and are simply omitted when the stored date
    isn't a real date. **[HUMAN] Residual, one command away**: nobody has
    yet checked whether any *real* production row actually holds such a
    value (the original open question). `GET /internal/date-format-audit`
    was built to answer it in one call — run:

    ```bash
    curl -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" \
         "$ARCHIVE_BASE_URL/internal/date-format-audit"
    ```

    `by_shape.unparseable > 0` means real malformed rows exist and
    `suspect_rows` names them (slug + stored value) — chase those to the
    adapter that wrote them and consider a backfill. All-zero across both
    `unparseable` and `parseable_non_iso` means no stored value could have
    been the cause, and the flag should clear on recrawl from the template
    fix alone. Either way, close this out once the audit has actually been
    run.
  - ~~All 6 `Clip` entries on the real Minneapolis LIMS test page flag
    "Missing field endOffset"~~ **Fixed 2026-08-14 — full detail in
    `BACKLOG_DONE.md`'s "Wave 1" entry.** LIMS's `_flatten_timestamps()`
    now sets each item's `end` to the next item's `start`, matching
    Granicus/IQM2's convention, instead of always equaling `start`.
  - ~~12 more `Missing field endOffset` warnings on the real San Carlos
    IQM2 page (2026-08-21 URL Inspection)~~ **Fixed 2026-08-21 (WO-28) —
    full detail in `BACKLOG_DONE.md`.** A different root cause from the
    LIMS one above: IQM2 gave a whole consent-calendar block a single
    timestamp, so twelve consecutive items all carry `start == 982` with
    `end == start`. `archive/utils/clips.py`'s `clip_entries()` now uses
    the next *distinct* start (1056) as the end for a run like that —
    which is both warning-free and more accurate, since those items
    genuinely do span 982→1056 collectively. Verified on the real
    payload: 12 missing → 1 (the genuinely open-ended final item).

- **[JUST-DO-IT] Search Console "Video isn't on a watch page" (947 videos
  and growing, from 23 in an earlier screenshot the same session) —
  root-caused via real example URLs Ryan pulled from the report plus
  direct code inspection, 2026-08-21. Fix shipped same day — see
  `BACKLOG_DONE.md`.** All 10 real example URLs Search Console gave (San
  Carlos CA/IQM2 mp4, Calvert County MD & Cedar Rapids IA/Granicus-Swagit
  m3u8, Redlands CA & Riverview MI & Hopkins MN (Edina)/Cablecast m3u8,
  Greenbelt MD & Hartford City IN/Azure CDN mp4, Peterborough ON/
  isilive.ca m3u8, Leon Valley TX/Cablecast m3u8) were **every one
  non-YouTube** — confirmed this is the same population as the mp4/m3u8
  `thumbnailUrl` gap above, not a scattered issue, and explains that
  entry's near-zero thumbnail count as a downstream symptom (Google
  doesn't get far enough to check `thumbnailUrl` on a video it's already
  excluded here).

  **Real root cause, confirmed in code**:
  [archive/templates/meeting_page.html:274](archive/templates/meeting_page.html#L274)
  used to render every non-YouTube/non-viebit video as a bare
  `<video id="meetingVideo" controls playsinline preload="auto"></video>`
  — no `src` attribute, no `<source>` child, in the server-rendered HTML
  Googlebot first parses. The real URL only existed in the page's JSON-LD
  `contentUrl` (line 65) until JavaScript ran. And when it did
  ([archive/static/meeting_page.js:51-57](archive/static/meeting_page.js#L51-L57)):
  for `.m3u8` sources, `hls.attachMedia(video)` uses Media Source
  Extensions, which sets the real DOM `video.src` to an opaque `blob:`
  URL — never the real, fetchable m3u8 URL at all, in *any* browser
  (7 of the 10 examples are this case). For direct `.mp4` (3 of 10,
  IQM2/Azure CDN), `video.src = videoUrl` did eventually set the real
  URL, but only after JS executed — the initial HTML still shipped with
  no src. Either way, there was no reliable, server-rendered `<video
  src>`/`<source src>` for Google to match against the JSON-LD
  `contentUrl` and confirm the page genuinely hosts that video — exactly
  what "watch page" verification needs. (YouTube pages don't hit this:
  Google can verify those independently against its own already-indexed
  YouTube watch page, regardless of how the iframe is populated.)

  **Fix shipped 2026-08-21**: `meeting_page.html` now renders the real
  URL server-side too — a `<source src="{{ page.video_url }}"
  type="application/vnd.apple.mpegurl">` for `.m3u8`, and `src="{{
  page.video_url }}"` directly on the `<video>` tag for `.mp4` —
  matching `contentUrl`, while `meeting_page.js`'s existing hls.js/`.src`
  logic is untouched for actual playback (`<source>` and a later
  `.src`/`hls.attachMedia()` call coexist fine — the browser just uses
  whichever the JS ends up wiring up). **Not yet confirmed on a re-crawl**
  — Search Console needs to re-index affected pages before the flag
  count can be checked; that's the real verification, not just the code
  landing.

- **[JUST-DO-IT] Viebit has the same two structural mislabels Vimeo just got fixed for
  — half fixed 2026-08-21 (WO-35): (2) below is done, (1) is still open.**
  Only the `VideoObject` JSON-LD half remains — the `/coverage`
  `audio_transcript_possible` half is fixed and verified (writeup in
  `BACKLOG_DONE.md`, which also answers the "is `master.m3u8` probeable?"
  question this entry raised: it doesn't matter, the stored `video_url`
  is never that stream). Original text follows. Viebit's
  `video_url` is an iframe embed page (`/embed/vod?v={id}&t=`), exactly
  like YouTube's and Vimeo's, but two places still treat it as a real
  media file: (1) `archive/templates/meeting_page.html`'s `VideoObject`
  JSON-LD puts it under `contentUrl` rather than `embedUrl` (WO-29
  changed the condition to `video_format in ("youtube", "vimeo")`;
  `viebit` deliberately wasn't added, since that would change how
  existing live pages present themselves to Google and deserves its own
  check against Search Console rather than riding along), and (2)
  `archive/db/crud.py`'s `audio_transcript_possible` column on
  `/coverage` excludes `youtube` and now `vimeo`, but still claims
  on-demand Whisper is possible for a Viebit row. Neither is a new
  regression — both predate WO-29 — and (2) at least is cheap and safe to
  fix. Worth confirming first whether a Viebit `master.m3u8` really is
  unprobeable from this app: `viebit.py`'s own docstring says the raw
  stream 403s on a CDN Referer/Origin check, which would make the column
  wrong today.

### `/coverage` as a QA surface

- **[JUST-DO-IT] `/coverage`'s "Every place we've covered" table is a real, useful
  place to spot resolver bugs by eyeballing outliers — confirmed by
  actually doing it, 2026-08-15, per direct suggestion.** A single pass
  over all 501 rows (jurisdiction + example-meeting title columns,
  flagging anything unusually long or containing stray digits/punctuation)
  surfaced every finding logged just above in one session: 2 new
  wordninja-acronym examples, a whole second adapter with the same
  unbounded-regex bug as the already-known Granicus one (6 real
  examples), and a genuine wrong-title/wrong-jurisdiction data mismatch
  on an already-flagged page nobody had noticed before. Also surfaced,
  not written up separately since they're just more instances of the
  already-open "Census-table baseline validation" bug above rather than
  anything new: the two literal-date-as-jurisdiction rows ("August 11,
  2026," "July 21, 2026") are both still live and unfixed. On the title
  side, two real examples of title-extraction bleed worth keeping in mind
  for whatever eventually improves title extraction generally: a title
  that swallowed a full Zoom dial-in block (meeting ID, passcode, phone
  number) past the real title text, and a title truncated mid-word
  ("...Exhibit 1 was adde") — a live, real instance of the exact
  mid-word-truncation signal the Census-baseline entry above proposed but
  had no confirmed example of yet. Worth treating this kind of scan as a
  repeatable practice (e.g. after any batch of new adapter/jurisdiction
  work) rather than a one-off — cheap to do, and every hit this pass was
  a real, previously-undocumented bug, not noise.

  **Correction 2026-08-21**: the two literal-date-as-jurisdiction rows
  this entry says are "still live and unfixed" are gone — a fresh full
  scan (843 rows at the time, 2,968 today) found zero jurisdiction values
  matching a "Month Day, Year" shape. Most likely incidentally closed by
  WO-14's bleed fix; never independently root-caused, since the original
  two URLs were never recorded.

## Trust, safety & data quality

### `[LATER]` `best_effort` residuals: no backfill for pre-2026-08-21 pages, and the flag never clears itself

(The "explicitly NOT to be fixed" half of this entry now lives in
**Standing decisions** at the top of this file.)

WO-21 (2026-08-21) plumbed `ResolvedMeeting.best_effort` through to the
Archive — a real `meeting_pages.best_effort` column, a provenance gate on
social auto-posting, and `GET /internal/low-trust-pages` — see
`BACKLOG_DONE.md`'s entry for the full build. Three real residuals (a
fourth, "the queue is a JSON endpoint, not a workflow", was closed the
same day by WO-38 — `reviewed_at`, `?unreviewed=true`, `?reason=`, and a
mark-reviewed endpoint; see `BACKLOG_DONE.md`):

- **Every page archived before 2026-08-21 has `best_effort = false`,
  and no backfill is possible.** Not an oversight and not a script
  somebody forgot to run: `best_effort` records *how a resolve was
  performed*, and nothing on the stored row preserves that. A fallback
  result that delegated to YouTube is byte-for-byte indistinguishable
  from a native YouTube resolve on `meeting_pages`. Historical rows only
  become accurate as they're re-ingested. The `platform == "unknown"`
  and `jurisdiction_confidence` halves of the audit endpoint do cover
  old rows from a different angle, so the queue isn't blind to history —
  it just under-reports the delegated case for anything old. A
  re-resolve sweep (`scripts/backfill_archived_pages.py`) would fix it
  properly for any page it touches.
- **The flag is sticky: a re-ingest can set it, never clear it.**
  Deliberate (see `_find_or_create_page()`'s comment) — every
  transcript-only pusher sends a partial payload where `best_effort`
  defaults to `False`, and an unconditional overwrite would let them
  silently un-flag genuinely unverified pages. The cost is the mirror
  image: a page later re-resolved by a real vendor adapter keeps the
  flag, so the review queue needs pruning by hand rather than draining
  itself. Fixing this properly means distinguishing a full resolve from a
  partial push at the ingest boundary, which nothing does today.
- **`jurisdiction_confidence IS NULL` is not counted as low-trust.** The
  endpoint matches `"unverified"`/`"blank"` only. Pages archived before
  the column existed (pre-2026-08-15) have NULL, which means "we never
  asked", not "we asked and got nothing" — lumping them in would swamp
  the queue with rows whose jurisdiction is probably fine. Revisit if the
  queue proves too narrow rather than too noisy.

### `[IMPROVEMENT-ROUND]` The low-trust queue is really a jurisdiction-quality queue, and reviewing a row doesn't repair it

WO-38 (2026-08-21) gave `GET /internal/low-trust-pages` a memory —
`reviewed_at`, `?unreviewed=true`, `?reason=`, and a token-gated
mark-reviewed endpoint (see `BACKLOG_DONE.md`). Calling it against
production for the first time also settled what's *in* it: 474 rows, of
which **470 are `unverified_jurisdiction`, 7 `unknown_platform` (3 of
those overlapping — reasons aren't mutually exclusive), and zero
`best_effort`**. Three residuals follow from that (a fourth, the
per-platform breakdown behind that 470, is promoted to its own entry
under "Platform & jurisdiction coverage" below, since it's actionable
coverage work, not queue mechanics):

- **It's a data-quality queue, not a trust queue, today.** Those 470
  rows are real live pages with real video whose jurisdiction couldn't
  be determined — not suspected spoofs. Marking one reviewed records
  that a human looked; it does not fix the missing jurisdiction, and
  there's no repair path from the queue (the nearest thing is
  `POST /internal/jurisdiction/backfill-apply`, which recomputes from
  stored inputs and so can't help a row those inputs never resolved).
  A "review → correct the jurisdiction" write is the obvious next slice
  and was deliberately not built here.
- **A review doesn't expire when the page changes.** `reviewed_at`
  survives a later re-ingest, so a page reviewed today and re-resolved
  tomorrow with different content still reads as reviewed. Comparing
  `reviewed_at` against `updated_at` would surface those; nothing does.
- **Still curl-only.** No UI, by choice at this volume — 474 rows is
  workable from a terminal with `?reason=` + `?unreviewed=true`. Revisit
  if someone other than Ryan ever works the queue.

### Social auto-posting residuals

Bluesky auto-posting went live 2026-08-21 — a real prod resolve created
a page and the account made its first real post, confirmed by Ryan (see
`BACKLOG_DONE.md`'s "Social auto-posting" entry for the full build +
verification detail). Three real residuals, split out per convention:

- **[HUMAN] Facet clickability not yet explicitly confirmed.** The first post
  landed, but whether the `/m/{slug}` permalink renders as a *clickable*
  link (vs. plain text) is a distinct check on the facet byte-offset
  math in `_post_to_bluesky()` — Bluesky does no autolinking, so a
  wrong offset fails silently as dead text. One glance at the live post
  settles it; can't be checked from a Claude Code sandbox (`bsky.social`
  is egress-blocked there).
- **[LATER] The Mastodon client has still made zero real posts** — no account
  exists. It stays flagged schema-verified-but-not-content-verified
  (`archive/utils/social.py`'s docstring) until an account + token exist
  and one real post is watched, same bar the Bluesky side just cleared.
- **[IMPROVEMENT-ROUND] Only page *creation* triggers a post — deliberate v1 scope.** A page
  first created agenda-only (or garbled) that later gains a real,
  high-quality transcript — via a re-resolve, a caption source catching
  up, or an on-demand Whisper job (the worker writes transcripts through
  `report_chunk_result()`, which never touches this hook at all) — is
  never announced. If announcements prove worth having, the
  upgrade-triggered case is the natural phase 2; the `SocialPost` claim
  table already supports it without schema changes. (Related,
  further-out: `CLAUDE_BACKLOG.md`'s parked durable-queue idea for
  burst-dropped candidates.)

### `[HUMAN]` Fake/spoofed "government" content — real gaps, threat-modeled 2026-08-10

Prompted directly by the user asking "should I be worried about prompt
injection or people submitting fake government websites or people
submitting websites that aren't government at all" — a real think-through,
not a hypothetical checklist. Nothing here is built yet; this section
exists to make the actual risk shape visible before deciding what (if
anything) to build against it.

- **[LATER] Prompt injection: not a live product risk today, because no LLM sits
  in the deployed serving path at all.** Every adapter parses scraped
  page content with deterministic regex/BeautifulSoup/JSON extraction —
  nothing reads a page's text and *acts* on instructions found in it.
  `worker/`'s `faster-whisper` transcribes audio to text; it doesn't
  interpret or follow spoken instructions either. The one place this
  already matters for real: **when I (Claude, during development) fetch
  and read a real government page's raw content directly** — that's
  already covered by the same instruction-source-boundary rule I operate
  under generally (fetched content is data, not commands), not something
  new to build. **Where this stops being true**: the moment any feature
  reads scraped page content *through* an LLM in the live serving path —
  an "AI summary," topic classification, semantic re-ranking, anything
  like that — a malicious page's own content becomes a real injection
  vector against that feature specifically. Nothing like that is planned
  today; worth re-reading this section before building the first one
  that is.

- **[HUMAN] Fake/spoofed "government" pages and non-government content getting
  archived as if it were official: a real, currently wide-open gap, not
  a hypothetical one.** Confirmed by reading the actual code: nothing
  verifies a submitted URL's site is a genuine government body before
  archiving it. Platform detection is pure URL-shape pattern matching
  (`detect_platform()`), and `jurisdiction`/`title`/`date` are extracted
  *from the submitted page's own content* with zero cross-check against
  any independent government registry — a malicious actor could claim
  any jurisdiction name they want. `generic_fallback.py` (built
  specifically to catch anything that doesn't match a known platform) is
  the widest-open path: it best-effort-scans *any* page for a video +
  agenda-shaped text, with no domain restriction of any kind — a
  `.gov`/known-city check would be the obvious first mitigation, but
  most real, already-working platforms (`lacity.primegov.com`,
  `dallastx.new.swagit.com`, etc.) aren't `.gov` domains themselves
  either, so a naive TLD allowlist would break most of what currently
  works, not just block abuse.

  **Real consequences if this got exploited, not just abstract risk:**
  fabricated "official" video/transcript content published as a
  seemingly-legitimate, SEO-indexed permanent page under a real-sounding
  jurisdiction name (disinformation/astroturfing risk); a real named
  official's words fabricated or altered under the appearance of an
  authoritative civic record (defamation-adjacent risk, sharper than the
  already-flagged Whisper-hallucination risk in the on-demand
  transcription entries elsewhere in this file, since *that* risk at least starts from
  real audio); the Archive used as free SEO-boosted hosting for
  unrelated spam/harassment content via `generic_fallback`; reputational/
  trust erosion for the whole site if any of the above became public.

  **What already exists as a real, if reactive, mitigation**: the
  "Report a problem with this meeting" flow (`ProblemReport`,
  `app/db/models.py`) already gives any third party a path to flag a
  suspicious page — genuinely built, not aspirational, just reactive
  (after publication) rather than preventive.

  **Mitigation options worth weighing (the first two are built — 2026-08-11
  and 2026-08-21, see BACKLOG_DONE.md — the rest are not decided):**
  - ~~**noindex generic_fallback/`best_effort` pages by default**~~ Built
    2026-08-11: `archive/templates/meeting_page.html`'s meta block now
    renders `<meta name="robots" content="noindex">` whenever
    `page.platform == "unknown"` (the exact string `generic_fallback.py`
    registers under). The narrowest, cheapest mitigation on this list —
    doesn't block anything, just stops amplifying the least-verified
    content until a human's looked at it. The rest of this section's
    threat model (fake-jurisdiction risk, curated-list idea, trust tiers)
    is still open. **Known, deliberate limit (confirmed 2026-08-21):
    this condition only ever tested `platform == "unknown"`, so it never
    covered the YouTube-delegated fallback path — the most common real
    generic_fallback outcome, whose `platform` is `"youtube"`. WO-21
    plumbed a real `best_effort` signal into the Archive but deliberately
    did NOT widen this condition; see **Standing decisions** at the top
    of this file for why.**
  - ~~**Don't auto-announce unverified pages on social**~~ Built
    2026-08-21 (WO-21, see BACKLOG_DONE.md). PR #266's Bluesky/Mastodon
    auto-posting shipped with a quality gate that checked video, segment
    count, warnings and language but nothing about *provenance* — so a
    generic_fallback scrape of an arbitrary URL with a good transcript
    got announced from the project's own public accounts. This section's
    threat model predates that pipeline entirely, which is exactly how
    the gap got there. `payload_is_high_quality()` now refuses anything
    carrying `best_effort` or `platform == "unknown"`.
  - **Manual review before a brand-new jurisdiction goes live/indexed**
    — especially for `generic_fallback`/`best_effort` results. Real cost:
    turns part of the pipeline from fully automatic into something
    needing a human in the loop, at least for first-time jurisdictions.
    **Partially approached from the other side 2026-08-21**:
    `GET /internal/low-trust-pages` gives an after-the-fact review queue
    (unverified provenance, unverified jurisdiction) without making the
    pipeline synchronous. A genuine *pre*-publication hold is still
    unbuilt.
  - **Platform-based trust tiers** instead of domain allowlisting — the
    named-vendor adapters (Granicus, Legistar, CivicClerk, Swagit,
    PrimeGov, etc.) all target products specifically sold to local
    governments, which is real (if imperfect) signal a naive domain
    check can't get from a URL shape alone; `generic_fallback` results
    would sit in a lower-trust tier by default under this framing.
  - **A curated known-jurisdiction list**, grown deliberately over time
    as real cities get manually confirmed — ties naturally into the
    already-planned "Coverage page" (Archive roadmap, below), which
    could double as this list's public face rather than being a second,
    separate thing to maintain.

  Deliberately not prioritized/sequenced yet — this section exists to
  make the shape of the risk visible, not to commit to a fix, per the
  user's own framing ("at some point").

- **[NEEDS-AUDIT] Second real instance of the Fountain Valley-shaped garbled/wrong-
  language pattern (see `BACKLOG_DONE.md`), found 2026-08-16 via the same
  DB skim.** Chula Vista Public Comments, 2026-05-19 (eScribe,
  `chula-vista-public-comments-2026-05-19-city-council-meeting`):
  `transcript_language` and `transcript_warnings` both fire (tagged `es`
  with a "no matching-language track found" warning, plus the garbled-at-
  source marker), and the stored Spanish text does read as garbled rather
  than fluent. Not independently re-verified against the live page — just
  confirms this failure shape recurs on a different real customer, not a
  one-off.

## Roadmap & strategy `[IMPROVEMENT-ROUND]`

**Architectural context:** anything about content/audience rather than
resolving (permanent pages, search, accounts/billing, email alerts, the
transcription crawler) grows in a **separate app** ("the Archive"), not this
resolver — see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full reasoning.
The resolver/Archive seam is `get_cached_resolution`/`log_resolution` in
`app/db/crud.py` plus `archive_client.lookup()`/`.push()`.

### App-wide audit: industry best practices & resource management — scoped 2026-08-14, for handoff

The tool itself works well now — 15+ platform adapters, 683 tests,
accounts, on-demand transcription, admin outcome reporting. This section
scopes a **broad audit of everything around the tool**, prompted by a
strategy conversation that surfaced how lopsided that is: heavy
investment in features/reliability, comparatively little in
discoverability, user validation, and standard engineering/business
hygiene. Intended to be **handed to a separate agent (Cowork)** to
execute — written to be self-contained (real file paths, real findings,
real open questions) rather than assuming this conversation's context.

**What this session already found — starting leads, not finished
verification.** Each was a quick, targeted check (a handful of greps/
reads), not an audit — the whole point of this section is to do that
properly:

- **[IMPROVEMENT-ROUND] User feedback & validation — the single biggest blind spot found.**
  The only feedback channel is a passive mailto link on
  `app/templates/about.html` ("Questions, feedback, or a meeting that
  didn't work?"), never surfaced mid-use. `ProblemReport`
  (`app/db/models.py`) is scoped narrowly to "something's wrong with
  *this meeting*" (content-quality bugs), not general product
  feedback. GA's `trackEvent()` helper (`app/templates/base.html`) is
  wired up but only fired from three call sites total
  (`newsletter_signup`, two `copy_link_to_time` calls) — no event for a
  successful resolve, a save, or a returning visitor, so there is
  currently no way to answer "does anyone come back" even in
  principle. No documented user interview/usability session exists for
  *this* product (`rtr-deeplink`) — the "two things people wanted"
  finding `CLAUDE.md` cites is from round 1's testing, a different,
  bigger, now-superseded product. Competitive-landscape research is
  explicitly "nothing done yet" per `rtr-business/TASKS.md`. This
  matters most *right now* because the first-10 personalized-deeplink
  outreach and the clips campaign are starting — the cheapest window
  there will ever be to instrument real signal, before it becomes
  unrecoverable history.
- **[IMPROVEMENT-ROUND] Discoverability — already the subject of its own backlog work**
  (see `CLAUDE_BACKLOG.md`'s "Discoverability additions" section and
  `rtr-business/marketing/discoverability-ideas.md`) — included here
  only as a pointer so the audit doesn't duplicate it.
- **[JUST-DO-IT] Docs hygiene — a live, confirmed example of drift, not a
  hypothetical.** Saved-search alert emails
  (`archive/search_alerts.py`, a real daily cron sending real emails,
  merged 2026-08-13 as PR #30) are described as unbuilt future work in
  `BACKLOG.md`'s own "Accounts + token billing" section, in `README.md`
  (line ~754) — ~~fixed 2026-08-16, wave 1 item 3, see
  `BACKLOG_DONE.md`~~ — and in `rtr-business/BUSINESS_OVERVIEW.md`'s
  "Not built yet" list, **still wrong**, not this repo so out of scope
  for wave 1. Also: this feature has never been human-verified firing
  for real (see the live-verification checklist from this same session
  date). Worth checking whether other recently-merged work has the same
  gap.
- **[NEEDS-AUDIT] Legal/compliance — already tracked in `rtr-business/TASKS.md`**,
  included here only as a cross-reference: no privacy policy/ToS live,
  LLC formation status TBD, the Clerk `user.deleted` → data-purge
  cascade has unit coverage but has never fired against a real account.
- **[Closed 2026-08-21] ~~Data durability — an unverified unknown.~~**
  Stale: a real Postgres point-in-time-recovery test restore was performed
  and verified against real data 2026-08-17 (`BACKLOG_DONE.md`'s "PITR
  test restore" entry — which this same file references elsewhere). The
  `render.yaml`-has-no-`databases:`-block observation is still true and
  still deliberate.
- **[Closed 2026-08-21] ~~Security — no dependency-vulnerability scanning
  exists.~~** Stale for the scanning half: `.github/dependabot.yml`
  exists, and `.github/workflows/test.yml` runs `pip-audit` against all
  four requirements files on every PR (WO-11, `BACKLOG_DONE.md`). The
  *other* half of this bullet — the self-authored fake/spoofed-content
  threat model having few built mitigations — is real, partly addressed
  (noindex, the social provenance gate, the low-trust queue) and tracked
  under **Trust, safety & data quality**.
- **[NEEDS-AUDIT] Financial/resource management — costs not fully inventoried.**
  `rtr-business/TASKS.md` already flags this: the transcription
  worker's $25/mo is the only confirmed recurring cost; both `starter`
  web plans, the domain, Resend, and Clerk have no confirmed monthly
  total. No pricing decided, no revenue. Worth pairing with an actual
  Render usage/cost review (worker sizing was set from real OOM
  crashes, not re-verified against current usage since).
- **[NEEDS-AUDIT] Accessibility — a positive finding, not a gap, on a shallow
  check.** `aria-` attributes appear across most templates and a real
  `lang` attribute is set — better than expected on a five-minute grep.
  No automated a11y check (Lighthouse CI, axe) exists to keep it that
  way as the site grows, but this shouldn't be assumed broken without
  an actual audit.

**What "resource management" should mean for this audit**: not just
inventorying dollar costs (financial ops above), but asking whether
engineering effort itself is going to the right places — this session's
own framing was that feature/reliability work has been heavy relative to
discoverability and user validation; the audit should form its own
independent view on that rather than taking this session's read as
given.

**Scoping notes for whoever picks this up**: every finding above is a
starting lead from one session's quick checks, not a finished
conclusion — verify before acting on any of them. This is deliberately
broad (industry best practices generally: reliability, security,
compliance, cost, process, and user/product validation) rather than
scoped to one fix, since the point is to find what a systematic pass
surfaces that ad hoc work has missed — this list is a floor, not a
ceiling.

### Product direction & open strategic questions

- **[IMPROVEMENT-ROUND] "Feed cities" — should this app ever synthesize its own meeting
  pages for cities that have no well-defined per-meeting page at all?
  Open strategic question, not a build item, prompted by a 2026-08-12
  pass through the 50 biggest US cities.** A real, recurring pattern
  distinct from every other gap logged this session: a city publishes
  video as one big feed (a YouTube channel, a Vimeo showcase list, a
  Seattle-Channel-style video index) and agendas/meeting metadata as a
  *separate* feed (a Granicus/Legistar calendar, an agenda-only page),
  sometimes on two different pages, sometimes both crammed onto one —
  but never as a single stable, government-hosted URL that's "the page"
  for one specific meeting with both video and agenda attached. Every
  adapter in this app assumes that stable per-meeting page exists
  somewhere and just needs finding/parsing; these cities don't have one
  to find. Concretely already seen this session in that shape: Seattle
  Channel's video-plus-feed page (above), Phoenix/Philadelphia/
  Albuquerque's Legistar-page-with-no-video-link-at-all-but-a-separate-
  city-YouTube-channel (above), Chicago ELMS's agenda API paired with a
  separate Vimeo showcase (above), El Paso's `elpasotexas.gov/videos/`
  directory of per-body Vimeo showcases (above).

  **The idea, in the user's own words**: rather than only ever resolving
  a URL someone pastes, build a page ourselves that indexes a city's
  video feed and its separate agenda feed, matches them (e.g. by date —
  "the city hosts all its city council meetings on YouTube with the date
  of the meeting in the title" paired with "a list of all the agendas...
  on Granicus with the date in the metadata"), and creates a real,
  possibly-permanent meeting page on *our* site combining both. The
  user's own framing of the tradeoff: "in a way, this is a PITA. In
  another way, these might be the most helpful pages we create because
  there isn't a near duplicate on the government agency's website." That
  second point is real and worth sitting with — every other page this
  app makes mirrors something that already exists somewhere, just made
  more accessible/deep-linkable/transcribed; a synthesized feed-matched
  page would be the one case where the page genuinely doesn't exist
  anywhere else in this form. That's a stronger value proposition than
  usual, and a correspondingly higher bar for correctness (see below).

  **Real considerations to work through before scoping a specific
  version, not yet decided on any of these:**
  - **Match confidence is the central risk, not a side detail.** Date/
    title heuristic matching between two independent feeds *will*
    sometimes attach the wrong video to the wrong meeting — unlike
    today's "no video found" (an honest gap), a wrong match is
    fabricated-looking correct-seeming misattribution on what would be a
    real, publicly-indexed page under a real jurisdiction's name — a
    sharper version of the fabricated-content risk the Trust & Safety
    section above already threat-models for `generic_fallback`, not a
    new category of risk. Whatever gets built needs a real answer for
    "how confident is confident enough to publish," not just "best
    guess."
  - **One-time historical backfill vs. an ongoing/scheduled pipeline are
    two very different sizes of commitment — the user's own instinct is
    that ongoing is the harder one, worth taking seriously rather than
    assuming they're the same problem at different scales.** A one-time
    backfill for a fixed list of big cities is bounded: run it once,
    review the matches, publish, done — much closer to the existing
    `bulk_ingest.py` shape than to a new standing system. An ongoing
    pipeline means continuously matching new videos to new agendas
    forever, on a schedule, per city, with drift over time (a city
    changes its YouTube channel, changes its agenda vendor, changes its
    upload cadence) silently degrading match quality with nothing
    forcing a human to notice.
  - **Temporary vs. permanent doesn't have to be a single decision up
    front** — the existing `best_effort`/`generic_fallback` ephemeral
    `/meeting?url=` flow already has a real lower-trust tier "isn't
    pushed to the permanent Archive unless it has real content" pattern
    to borrow from; a synthesized match could start there (visible, but
    not yet a permanent indexed page) before anything gets promoted.
  - **Scale/cost is unscoped**: how many of the 50 cities checked
    actually hit this specific "two separate feeds" pattern (as opposed
    to the many *other* distinct problems logged this same session —
    rate limiting, wrong jurisdiction, infinite recursion, weak metadata
    — which aren't this problem and shouldn't get bundled into sizing
    it), how many historical meetings per city, and whether transcribing
    all of them is assumed as part of this or a separate ask on top —
    none of that's been counted yet.

  **On "is there an easy version" — the concrete next step is counting,
  not building.** Before sizing this at all, worth going back through
  the 50-city pass specifically to tag which cities hit *this* pattern
  (two separate feeds, no per-meeting page) rather than one of the other
  distinct bugs/gaps already logged individually this session — right
  now this entry is grounded in four real examples encountered
  incidentally, not a real count of how big "feed cities" actually are
  among the 50. That count is what would turn "maybe just do the big
  cities once" from a gut instinct into an actual scoped decision.

  **A real, promising extraction angle for whatever gets built: WCAG/
  accessibility-driven markup, not just date/title matching — user's own
  idea 2026-08-12, checked directly against real pages rather than left
  as speculation.** Government sites lean on standardized accessibility
  markup more than most (Section 508 compliance is often a legal
  requirement, not a nice-to-have), and unlike a proprietary player's
  internal JS config, these are standards-based and consistent across
  unrelated sites — real findings, not assumptions:
  - **`<track kind="captions" src="...">` inside a native `<video>`
    element** — the actual HTML5 captions standard. Confirmed present,
    identically shaped, on three separate real government meeting pages
    already fetched during earlier work in this repo (each a plain
    `/videos/{id}/captions.vtt` path) — about as reliable a caption-
    discovery signal as exists wherever a site uses native `<video>`
    rather than a JW Player/Vimeo/YouTube-style embed.
  - **`<time datetime="...">` semantic date/time markup** — confirmed
    real on Portland.gov, with full ISO datetime *including time of
    day* (`<time datetime="2026-07-29T16:30:00Z">`) — notably the exact
    missing piece from the earlier Google-Search-Console `uploadDate`/
    timezone finding (Bugs, above): this app doesn't capture meeting
    time-of-day anywhere today, and here's a real government source
    that already has it in clean, structured form.
  - **WCAG-required iframe `title` attributes, when a site populates
    them well** — Portland's video iframes carry real, descriptive
    titles (`"YouTube | Portland City Council AM Session 07/29/26"`,
    correctly distinguishing AM/PM sessions); confirmed *not* universal
    though — CRRMA's iframe title on the exact same YouTube-embed
    pattern (Bugs, above) was just the generic placeholder `"YouTube
    video player"`. Same accessibility requirement, inconsistent
    real-world compliance — has to be checked per site, not assumed.
  - **Real negative, worth not chasing further**: checked 7 real
    government pages this session (Portland, Seattle Channel x2, CRRMA,
    Columbus, Charlotte, Baltimore) for schema.org/JSON-LD structured
    data (the same VideoObject markup this app's *own* pages emit for
    SEO) — zero hits on all seven. Unlike the accessibility markup
    above, this doesn't look like a technique government sites
    reciprocate.

### Accounts + token billing — phases 2-6

**Phase 1 shipped 2026-08-11 and is live in production** (Clerk-based
sign-in, saving meetings and searches, `SavedItem`); its full build
history, the Clerk-not-hand-rolled-auth pivot, the superseded
magic-link design and the second-round UI/redirect saga all moved to
`BACKLOG_DONE.md` 2026-08-21. `CLAUDE.md` points here for what is still
ahead, which is everything below. The one live compliance gap split out
of phase 1 — the never-fired `user.deleted` purge — is under **Needs a
human**.

**Expanded scope, per user request 2026-08-10 — a real social/content
layer, not just accounts + saved searches.** The user wants, in their
own words: a profile page (public or private) made of notes (posts or
notifications, each independently public/private); saving a meeting to
a profile as a note (public/private per note); saving a search to a
profile as a note (public/private per note); subscribing to
in-profile/notification alerts for a search, separately from
subscribing to email alerts for the same search; reposting anything as
a new note carrying a user-written message, linking back to the
original (a quote-repost, not a plain retweet-with-no-comment);
eventually attaching clips/screenshots/PDFs/other media to notes;
eventually sorting/filtering `/meetings` search results by how many
people saved a given meeting (a popularity signal). This materially
reshapes the data model below from the original accounts+SavedSearch
sketch — capturing it now since it changes what "phase 1" even means,
not committing to build any of it yet.

**Revised proposed data model**, replacing the original
`Account`/`AccountSession`/`SavedSearch` sketch's third table: a single
polymorphic **`Note`** table instead of a separate `SavedSearch` table,
since "saved search," "saved meeting," "post," and "repost" all turn
out to be the same underlying shape (an account, a visibility flag, an
optional reference, optional user-written text) rather than four
independent features:
- `Account` (email, created_at, no password column) and
  `AccountSession` (session id, account id, expires_at) — unchanged
  from the original sketch.
- `Note` (account_id, `note_type` — `saved_meeting` / `saved_search` /
  `post` / `repost` — `visibility`: public or private, **set per note,
  not per account or globally**; `meeting_page_id` nullable FK, set
  only for `saved_meeting`/some `repost`s; `search_params` nullable
  JSON, set only for `saved_search`; `parent_note_id` nullable
  self-referential FK, set only for `repost` (the note being reposted —
  reposting a repost should probably chain to the *original*, not
  nest indefinitely, an open question); `body_text` nullable, the
  user-written message on a `post` or `repost`; `created_at`). A
  profile page is then just "this account's notes, filtered to public
  ones unless the viewer is the account owner."
- `NoteSubscription` (account_id, `search_params` JSON matching a
  saved search's shape, `notify_in_profile` bool, `notify_by_email`
  bool) — the two subscription channels the user described are
  independent toggles on the same row, not two separate features;
  `notify_by_email` is what the already-planned "Email alerts for
  saved searches" item below actually becomes once accounts exist,
  not a separate build.
- Media attachments (clips/screenshots/PDFs) on notes: flagged
  "eventually" by the user, and a real new category of infrastructure
  for this app — there is currently **zero file-upload/object-storage
  capability anywhere in this codebase** (every existing asset is
  either scraped-and-linked, not hosted, or a static file checked into
  the repo). Would need real new decisions (S3/R2/Cloudflare Images or
  similar, upload size limits, moderation) not touched by anything
  else in this scoping pass — deliberately not designed further until
  the base Note model ships and this becomes concretely next.
- Popularity-based sort/filter on `/meetings`: also flagged
  "eventually" by the user. Cheapest real implementation once `Note`
  exists: a `saved_meeting_count` column on `MeetingPage`, updated
  on save/unsave (or computed via a `COUNT(*)` on `Note WHERE
  note_type='saved_meeting'` at query time, matching this repo's
  existing "don't add a materialized column until the naive version
  actually gets slow" pattern from the search-scaling item below) —
  genuinely deferred until saving meetings itself exists and has real
  usage to rank by.

**Proposed phased plan, revised — deliberately still not one big
build:**
1. Passwordless accounts (magic link, session cookie) + the base
   `Note` model, covering just `saved_meeting` and `saved_search`
   (no `post`/`repost` yet, no profile page yet) — no billing yet,
   could ship as a free feature.
2. Public/private profile pages rendering an account's own notes;
   `NoteSubscription` (both notify channels) for saved searches —
   this is what actually unlocks "email alerts," not a separate
   build from it.
3. `post`/`repost` note types, making the profile a real lightweight
   feed rather than just a saved-items list.
4. Batch lookup, gated by account (rate-limited per-account instead
   of fully anonymous) — still no payment required, just removes the
   anonymous-abuse-vector concern the batch-lookup item below already
   flags.
5. Billing (Stripe is the obvious default — standard, well-documented
   webhook/subscription model) layered on only once there's a real
   paid tier to sell against — e.g. unlimited batch lookups, higher
   alert frequency, priority transcription queue position (the
   existing `TranscriptionJob.priority` column already supports a
   higher tier with zero schema change, per its own docstring).
6. Media attachments on notes, and popularity-based search
   sort/filter — both explicitly "eventually" per the user, sequenced
   last since both need real usage of the earlier phases to be worth
   building against.

**Business-model framing, from the user, 2026-08-12 — several rounds of
refinement the same day, replaces the original "journalists are the
paying user" framing entirely.** Advocates and grassroots organizers,
not journalists, are the primary intended audience — journalists are a
good example user (real distribution/credibility value) but a smaller
group than the grassroots/advocacy base this is actually being built
for, and shouldn't be built into the product's core definition anywhere
(`README.md`'s Vision section now reflects this). The intended paying
customer is a different group again: institutional users with real
budgets — special interest groups, corporations, city staff/management.

**The likely shape of the split, directionally — not priced or built
yet.** Usage seems likely to split into two real modes once there's a
regular user base: a light user following one or two meetings a month
for a single city council or planning commission, and a heavy user
tracking meaningfully more than that. Rough shape floated by the user
(not a commitment): an account-creation gate that grants free monthly
credits sized to comfortably cover the light-user case, with a paid tier
(the user's own reference point: something like $40/month) that raises
the ceiling high enough a heavy individual user doesn't have to think
about limits day to day. Separately, a B2B/institutional tier is the
intended answer for an organization tracking a specific topic across
many jurisdictions at once (the user's own example: a company's PR team
following a specific kind of siting decision across city councils) — a
different usage shape from an individual power user, likely
priced/scoped differently rather than being "the same paid tier, bought
by a company."

Search itself stays free as long as it's cheap to run; the plan for
if/when that stops being true is a real, explicitly limited free tier —
either the credit system above or narrower scope (e.g. free tier limited
to shorter date ranges) — rather than putting search behind a paywall
outright. Not yet decided: the actual credit amounts, the exact
paid-tier price/limits, whether B2B pricing is a multiple of the
individual paid tier or a separate negotiated thing, or what usage/cost
threshold triggers building any of this at all — all directional
thinking to conceive of usage modes, not a committed pricing plan.

**Real open questions, not decided yet — need the user's call before
building past phase 1:** what's actually free vs. paid (the phased
plan above is a sequencing proposal, not a pricing decision); whether
"token billing" specifically means a metered credit system (buy N
tokens, spend on transcriptions/batch lookups) vs. flat subscription
tiers, or both; whether Stripe is the intended/preferred provider or
just this write-up's default assumption; free tier size for saved
searches/alerts before hitting a paywall; whether a `repost` of a
`repost` should chain to the original note or nest (product decision,
not just a schema one); moderation for public notes/profiles in
general, not just future media attachments — public+free-text (`post`,
`repost` messages) is real new user-generated-content surface area
this app has never had before, worth its own look before phase 3
ships, not assumed fine because `ProblemReport` already covers the
Trust & safety section's narrower "is this a real government meeting"
concern above.

**Timestamp-level annotations on a note — proposed by the user,
2026-08-14.** Example given: save
`https://redtaperecordings.com/m/yellow-springs-oh-2022-02-07-virtual-village-council-2022-02-07?t=6153&line=seg-2543&version=251`
with a user-written notation like "Dave Chappelle speaks about
affordable housing in Yellow Springs, OH" — i.e. a `saved_meeting`
note pinned to one moment (a `t`/`line`/`version` triple, matching the
deep-link query params `app/main.py`'s resolve route already emits —
see `BACKLOG_DONE.md`'s "Deep links" entry), not just the meeting as a whole. This
is a real gap in the `Note` model sketched above: `saved_meeting`
currently only carries `meeting_page_id` + a whole-meeting reference,
with `body_text` reserved for `post`/`repost` types — nothing today
captures a specific timestamp *or* attaches free text to a
`saved_meeting` note. Cheapest fit: let `saved_meeting` notes also set
`body_text` (already nullable) and add nullable `t`/`line`/`version`
columns (or a single `deeplink_params` JSON blob, matching the existing
`search_params` JSON precedent on `saved_search`) so a note can
optionally pin to one moment instead of the whole meeting. Directly
useful for the advocate/organizer audience this app is being built for
(see "Business-model framing" above) — annotating *why* a specific
moment matters is a stronger unit than a bare saved meeting, and a
natural building block toward the already-planned `post`/`repost` note
types (a moment-annotation is close to a first-class quote-post).
Depends on phase 1 (`Note` model) already shipping — sequence alongside
or just after phase 2's profile pages, since a pinned-moment note is
most useful once it's actually visible somewhere. Overlaps with, but is
distinct from, `CLAUDE_BACKLOG.md`'s "Quote-clip sharing" idea: that one
is a *public* shareable image/card; this is a *personal* private-or-public
notation a user leaves for themselves or their profile, no image
generation required to be useful. Not yet built or scoped further.

### Growth, audience & discoverability

- **[IMPROVEMENT-ROUND] Proactive transcription crawler — re-prioritized 2026-08-09 to
  precede accounts/billing, then explicitly held back again 2026-08-10
  ("not yet — keep prioritizing bugs/gaps").** The reasoning below for
  *why* it matters still stands; the decision is about sequencing, not
  value — real reliability work (Alembic gaps, the Archive schema items
  above, Viebit) still takes priority over a bigger, more speculative
  build right now. Revisit once that work settles down. Cross-archive
  keyword search on
  `/meetings` is already live (built 2026-08-08), and its value is
  directly proportional to corpus size — a national-beat journalist
  searching "Flock" only gets real value once enough jurisdictions have
  actually been resolved and transcribed. Today the corpus only grows
  when someone happens to paste a URL, a slow, demand-driven way to fill
  an archive meant to support discovery. This reframes the crawler from
  "nice to have" to "the thing that makes the flagship search feature
  actually good." No new dependencies beyond what already exists
  (adapters, Archive schema, transcription worker are all already
  built) — this is a re-prioritization question, not a new build: worth
  deciding whether it jumps ahead of accounts/billing given it doesn't
  require them.
- **[IMPROVEMENT-ROUND] Batch lookup — accept multiple meeting URLs at once (paste-list,
  CSV, etc.) instead of one at a time.** Removes the main friction point
  for a journalist working many jurisdictions at once — pasting dozens
  of URLs one-by-one doesn't match how someone actually works a
  multi-city story. Worth sequencing after accounts even though it
  doesn't strictly require them: a batch endpoint is a natural abuse
  vector (someone queuing hundreds of transcription jobs at once), and
  the transcription worker's real per-job compute cost (see "On-demand
  transcription" below — a measured real dollar figure, not a
  hypothetical one) means unmetered batch access could get expensive
  fast. Rate-limiting or account-gating this is worth deciding before
  shipping it, not after.
- **[NEEDS-AUDIT] Companion "known gaps" page — same table shape, listing
  jurisdictions/platforms that don't resolve cleanly yet** (attempted but
  blocked, partially working, or simply not yet built), separate from
  the coverage page above. Turns "it didn't work" from a dead end into a
  visible, honest roadmap, sets expectations for a journalist checking a
  specific city before investing time, and doubles as a natural intake
  signal — anyone whose city shows up as a known gap has a concrete
  reason to check back or flag interest instead of silently bouncing.
  Partially self-populating: failed/low-quality resolve attempts are
  already logged by the same `meeting_resolutions` system the coverage
  page above would read from. The real open question is distinguishing
  "known gap actively being worked on" from "just hasn't been tried
  yet" — those read very differently to a visitor, and probably need a
  manual status field rather than being purely derived from logs. Could
  ship after or alongside the coverage page, reusing the same table
  component.
- **[IMPROVEMENT-ROUND] Video highlight clips + algorithmic feed** — distant future. Flagged
  tension: this app's "never host video, only embed" principle directly
  conflicts with hosting/serving clip segments.
- **[IMPROVEMENT-ROUND] A generated, branded share card would beat a raw
  video frame (WO-28 residual).** The extracted frame is a real, large
  improvement over no image at all, but it carries no jurisdiction, no
  meeting title, and no Red Tape Recordings identity — a reader scrolling
  Bluesky sees an anonymous council dais. The stronger unit is a
  composited card (frame as background, jurisdiction + title + date +
  logo overlaid), which is also what `CLAUDE_BACKLOG.md`'s "Quote-clip
  sharing" idea would need. Deliberately not built here: it needs an
  image-compositing library (Pillow, or ffmpeg's `drawtext` with a
  bundled font) that this repo does not currently have, and font
  rendering/wrapping quality is a real design problem rather than a small
  addition. The storage, route, cache headers and targeting all carry
  over unchanged if it happens.
- **[IMPROVEMENT-ROUND] PDF agenda links are never rendered inline or text-extracted for
  preview — a real product question raised live-testing, not yet a
  scoped bug.** Today, any agenda PDF `generic_fallback.py` finds is
  shown only as a plain outbound link
  (`.source-guess`/`_find_agenda_link()`), never embedded in a viewer or
  summarized. Two distinct asks worth separating if this gets scoped:
  (1) an inline PDF viewer (a real frontend/UX decision — embed via
  `<iframe>`/`<embed>` pointing at the PDF URL directly is the cheapest
  version, works today with zero backend change, but doesn't add
  searchability); (2) extracting real text from the PDF (even just the
  first page/top of document, per the user's own "regex of the top
  text" suggestion) to store as a searchable preview/snippet — this
  needs a real PDF-text-extraction dependency (e.g. `pypdf`/`pdfplumber`,
  neither currently in `requirements.txt`) and a place to store the
  extracted text (`MeetingPage` has no such column today). Not
  investigated further this pass — logged as a real gap/question, not
  designed.
- **[IMPROVEMENT-ROUND] Design reference for the cassette-reel button animation, flagged
  2026-08-16: the user likes the "Install GitHub App" button's animation
  on Sentry's onboarding page and wants to use it as a reference point
  for improving our own.** Reference:
  [how-to-adu.sentry.io/onboarding/scm-connect/](https://how-to-adu.sentry.io/onboarding/scm-connect/)
  (a private, logged-in page on the user's own Sentry org — not
  independently viewed this pass, since it needs their session; noted
  from a screenshot of that button's DOM in devtools, not the live page).
  What the screenshot actually shows, so this isn't lost: a
  `data-sentry-component="StyledButton"` button wrapping a
  `data-sentry-component="Button-Flex"` inner span, with real `::before`
  and `::after` pseudo-elements on the button itself (visible in the
  devtools tree) — suggesting a layered sweep/fill/underline-style effect
  built from those pseudo-elements, not just a plain color transition,
  but **the actual motion (timing, easing, what visually happens on
  hover/click) was never described or watched — only this static
  structure is confirmed.** Whoever works on this should visit the live
  URL and actually watch the animation first, not infer behavior from a
  DOM snapshot.

  Our own reel animation today:
  [archive/static/style.css:138-155](archive/static/style.css:138) —
  `.cassette-reel` is an inline SVG; `.cassette-btn:hover
  .cassette-reel, .cassette-btn:active .cassette-reel` spins it via
  `@keyframes reel-spin` (0.8s linear infinite) on hover/press, and a
  separate `.cassette-reel.spinning` variant runs the same keyframe
  slower (1.6s) as an ambient "please wait" state while a real
  fetch/resolve is in flight (up to ~20s, per the CSS's own comment on
  why it's intentionally slower than the hover flourish). Used on two
  buttons today: the homepage submit button and the meeting page's "Copy
  link to current time." A related, previously-floated idea already
  built once in a different spot — `cassette-btn-pop`
  ([style.css:164-171](archive/static/style.css:164), a "lift up and
  glow" attention cue used by `meeting_page.js`'s
  `wireSourceDisclaimerPointer()`) — is the closest existing precedent
  for a more elaborate cassette-button animation than the plain spin, if
  the Sentry reference turns out to be that kind of "pop/lift" effect
  rather than a sweep/fill one once actually watched.

### Search & metadata quality

- **[IMPROVEMENT-ROUND] Tune `_VOCAB_SIMILARITY_THRESHOLD` (`archive/db/crud.py`,
  currently 0.3, pg_trgm's own default) against real production fuzzy-search
  query logs — low priority, not a correctness issue.** Search Step 2b
  (see `BACKLOG_DONE.md`'s search entry) uses this threshold purely as a
  *candidate generator* for `search_vocabulary`'s trigram lookup — every
  candidate it turns up still gets re-verified against the exact
  Levenshtein check `matches()` uses, so a threshold that's too loose or
  too tight only costs extra/missed *candidate* checks, never a wrong
  final answer. Never tuned against real data; worth revisiting once
  there's a real corpus of production fuzzy queries to measure against
  (same class of follow-up as the earlier, now-superseded
  `_FUZZY_WORD_SIMILARITY_THRESHOLD` from PR #124, before Step 2b
  replaced that approach).
- **[IMPROVEMENT-ROUND] Audit per-adapter coverage of `meeting_body`, then be strategic about
  extending it — low priority, no urgency.** `meeting_pages.meeting_body`
  ([archive/db/models.py:47](archive/db/models.py:47), `Text`, nullable)
  landed 2026-08-15 alongside `jurisdiction_confidence` as part of
  `JURISDICTION_METADATA_PLAN.md`'s workstream 1, already merged, migrated,
  and backfilled in production — confirmed live end-to-end for the
  Santa Clara Housing Authority page (`meeting_body="Housing Authority"`,
  full detail in `BACKLOG_DONE.md`'s "Jurisdiction/title extraction
  pipeline" entry) and rendered on `/m/{slug}`, `/meetings`, and My Saved
  Items (see `JURISDICTION_METADATA_PLAN.md`'s Slice 4). It is genuinely
  live, not a dead column — the open gap is coverage, not plumbing.

  Today the field is populated exactly one way, centrally: `finalize_
  jurisdiction()` in `app/utils/jurisdiction_enrich.py` calls
  `_split_entity_prefix()` on whatever jurisdiction string it ends up
  with, splitting a leading `"<Entity> of <Jurisdiction>"` shape (e.g.
  "Housing Authority of the County of Santa Clara") into `meeting_body`
  and a cleaned `jurisdiction`. It's not adapter-specific extraction —
  every adapter's resolved jurisdiction text passes through the same
  generic split, so coverage depends entirely on how often a given
  adapter/platform's real jurisdiction strings happen to contain that
  exact "<Entity> of <Jurisdiction>" shape, which the code's own comments
  already flag as a minority case. `JURISDICTION_METADATA_PLAN.md` (line
  ~92) separately notes Granicus's `_fetch_channel_info()` already parses
  a body-shaped value out of its RSS channel title as an independent,
  adapter-native precedent — worth checking whether that value and the
  generic split ever disagree on the same page, since they're two
  different code paths today.

  The actual ask: figure out, per adapter/platform, how often real
  archived meetings *should* have a `meeting_body` but don't — i.e. cases
  where the raw title/jurisdiction text clearly contains a splittable
  entity prefix that the current generic regex/split doesn't catch
  (different wording than "X of Y", a prefix that isn't at the very
  start, a platform whose native metadata already separates body/
  jurisdiction but never gets threaded through `finalize_jurisdiction()`
  at all). Use the ~650 already-archived meetings as the test set per
  adapter (same approach as the census-baseline-validation bug above and
  the workstream-1/2 tournament in `JURISDICTION_METADATA_PLAN.md` —
  dry-run against real cached data, no guessing at shapes that haven't
  been seen), and be strategic rather than blanket about which adapters
  are worth extending — some platforms (special districts, transit
  authorities, housing authorities) will have real entity-prefix volume
  worth chasing; many won't, and forcing the split where it doesn't
  belong risks the same "loses information without a bleed signal"
  mistake `JURISDICTION_METADATA_PLAN.md` already called out and
  deliberately avoided when this field was designed.
- **[IMPROVEMENT-ROUND] Once `meeting_body` has real, strategic coverage (see above), add it
  as a `/meetings` search filter — separate, related item, sequenced
  after the coverage work, not before.** Today's search
  (`archive/utils/search.py`) matches title/jurisdiction/agenda/
  transcript text but has no `meeting_body`-aware filter or facet (e.g.
  "show me all Housing Authority meetings" as a distinct filter from a
  plain text search hitting the same words). Low value until coverage is
  broad enough that filtering by it actually narrows a real result set
  instead of just the handful of pages the entity-prefix split happens to
  catch today.

- **[IMPROVEMENT-ROUND] A demoted `TranscriptVersion`'s text is still
  invisible to external search.** The in-app half is fixed (this site's
  own `/meetings` search matches every version's segments) and the UX half
  shipped 2026-08-12 as a `<select>` version picker — both moved to
  `BACKLOG_DONE.md` 2026-08-21. What is still open, deliberately:
  **Still genuinely open, deliberately not attempted**: external search
  only ever indexes the canonical `/m/{slug}` URL's single active-version
  HTML — a demoted version's transcript text is still invisible to
  Google (though already findable via this site's *own* `/meetings`
  search, per the fix above). The real fix would still be rendering every
  version's segments into the DOM with JS-toggled visibility (Google's
  documented-correct pattern for tabbed content), which needs its own
  scoped work — deep-link segment IDs would need to be scoped per version
  (`seg-{version_id}-{n}`, not today's bare `seg-{n}`) to avoid collisions
  once multiple versions' segments coexist in the same page, and Dublin's
  real transcript alone is over a megabyte of JSON, so page-size cost for
  a multi-version page needs a real check before committing to it. Not
  prioritized — revisit only if the SEO angle specifically becomes worth
  it later.

### Transcription quality & cost

- **[IMPROVEMENT-ROUND] Per-meeting `initial_prompt` seeded with real council-member names,
  from the agenda — user idea, 2026-08-11, real proper-noun accuracy
  motivation (their example: "Council Member Rashi Kesarwani, Council
  Member Rigel Robinson").** Today's `MEETING_VOCABULARY_PROMPT`
  (`worker/transcription_engine.py:26-30`) is one fixed, generic
  constant, reused verbatim for every job's every chunk — real
  people's names (especially non-Anglicized or less-common ones, exactly
  where Whisper is most likely to mishear/misspell) aren't in it at all,
  and can't be with a single static prompt shared across every
  jurisdiction.

  **Real gap confirmed, not assumed**: nothing in this codebase currently
  extracts attendee/council-member names from anywhere — confirmed via
  grep across every `app/platforms/*.py` adapter, no hits for
  attendance/council_member/attendee/roster. `ResolvedMeeting.agenda_items`
  (`app/platforms/models.py:41`) holds agenda *topic* text (e.g. "Item 1:
  Approve minutes..."), not a roster of who's on the body — so this would
  be new extraction work, not a matter of wiring up an existing field.
  Whether that roster is even reliably available per-platform is itself
  unconfirmed — some agenda pages/PDFs list attendees or a member roster,
  some may not, and this hasn't been checked against a real sample yet
  (same "verify against a real example before building" convention as
  every adapter in this repo).

  **Plumbing gap, separate from the extraction gap**: even with names in
  hand, today's engine has no path to use them per-job.
  `FasterWhisperEngine` (`worker/transcription_engine.py:42-86`) is
  constructed once at worker process startup and reused across every
  job's every chunk (`worker/main.py:205`,
  `engine.transcribe_chunk(audio_path)` — no per-job context passed in
  at all). Making the prompt per-meeting would need `transcribe_chunk()`'s
  signature to accept extra per-job terms, threaded through from
  wherever the worker's job loop can look up that job's `meeting_page_id`
  and its (new) extracted names.

  **Real constraint worth weighing before building**: Whisper's
  `initial_prompt` is a soft bias with a real length ceiling, not an
  unlimited instruction list — the existing comment
  (`transcription_engine.py:21-24`) already warns that an overly long or
  suggestive prompt risks the model leaning on it past where it's
  actually relevant. Appending a growing per-meeting names list to the
  existing generic vocabulary needs some care not to dilute or overflow
  it, and — per this repo's "verify with a real example" convention
  throughout — would need a real before/after check against an actual
  meeting with known misspelled names, not assumed to help just because
  it's plausible.
- **[IMPROVEMENT-ROUND] The transcription-request rate limit's copy is unfriendly/non-native-
  reading and misses an obvious account-creation opportunity — and
  logged-in users shouldn't be rate-limited at all, flagged 2026-08-15.**
  Real copy, both duplicated copies of the fix from the already-closed
  "misleading 429 message" entry (`BACKLOG_DONE.md`):
  [app/static/player.js:468](app/static/player.js:468) and
  [archive/static/meeting_page.js:383](archive/static/meeting_page.js:383)
  — `"You've requested a few transcripts already this hour — please try
  again a bit later."` Two real, separate asks:

  1. ~~**Rewrite the copy**~~ **Fixed 2026-08-16, wave 1 item 2 — full
     detail in `BACKLOG_DONE.md`.** Now "You've hit the transcript
     request limit for now — please try again in about an hour." Doesn't
     yet use the moment productively (no sign-in/account-creation
     prompt) — deliberately left out, see ask 2 below, which is the
     harder, still-unbuilt half.
  2. **Signed-in users should never hit this limit at all**, and a
     signed-out visitor who hits it should be prompted to sign in/create
     an account instead of just told to wait.

  **Confirmed root cause: the rate limit has zero concept of accounts
  today, on either endpoint.** `limiter = Limiter(key_func=get_remote_address)`
  ([app/main.py:85](app/main.py:85)) is pure per-IP limiting, unconditionally
  applied via `@limiter.limit("5/hour")` on both
  `/api/transcription/check-feasibility` and `/api/transcription/submit`
  ([app/main.py:908-909](app/main.py:908),
  [app/main.py:954-955](app/main.py:954)) — a signed-in Clerk session
  changes nothing about which bucket a request counts against.

  **The building block for "is this visitor logged in" already exists in
  this exact file, proven and in active use nearby**:
  `get_clerk_user_id(request)` ([app/utils/clerk_auth.py:68](app/utils/clerk_auth.py:68))
  — cookie/header-based, no extra round trip once Clerk's JWKS cache is
  warm, already imported into `app/main.py` and already used by the
  save-meeting API routes right below these two endpoints
  ([app/main.py:788-789](app/main.py:788)) to gate on sign-in state. Both
  transcription routes already take `request: Request` as their first
  parameter, so the check itself is cheap to add. **What's not yet solved:
  slowapi's `@limiter.limit(...)` decorator applies unconditionally at
  decoration time** — there's no existing pattern in this codebase for a
  per-request conditional bypass (e.g. slowapi's own `exempt_when`, or
  restructuring the limit check to run inside the function body instead of
  the decorator). Worth checking slowapi's actual support for this rather
  than assuming — not attempted or confirmed this pass.

  **Real prior art directly relevant to the sign-in-CTA half of this,
  worth reading before building — this exact UI spot already tried
  something like this and deliberately backed out.** Per
  `player.js`/`meeting_page.js`'s own comments and the "Second round" note
  in `BACKLOG_DONE.md`'s accounts phase-1 entry: this same transcribe-form
  UI used to have an inline sign-in shortcut (a button opening Clerk's
  modal), and it was **removed entirely** after three rounds of Clerk's
  documented redirect options proved unreliable live — "per the user's
  call once that saga made clear it wasn't worth the complexity there
  specifically" (full saga in `BACKLOG_DONE.md`). A rate-limit-triggered
  CTA isn't necessarily the same failure mode (a plain link to a sign-in
  page behaves differently than a JS-driven modal-open shortcut), but
  whoever builds this should read that history first rather than
  re-discovering the same reliability problem — a plain link to a
  dedicated `/sign-in` page (rather than reaching for the modal again)
  may be the safer default given that track record.

### Email, ops tooling & internal reporting

- **[IMPROVEMENT-ROUND] Lifecycle-triggered transactional emails (Resend) — built 2026-08-11
  from rtr-business's `marketing/LIFECYCLE_EMAILS.md` (approved copy/
  voice, written by the user).** That doc defines six emails; five
  shipped this pass, one explicitly split off given its real scope:
  - **Shipped**, all reusing/extending existing Resend send
    infrastructure, no new mechanism: "Thanks" (account created — fires
    from the Clerk `user.created` webhook in `app/main.py`, *instead of*
    also sending "Welcome," since account creation already
    auto-subscribes to the newsletter and sending both would be two
    emails for one action — the user's explicit call); "Welcome" (joined
    the newsletter via the standalone `/subscribe` form only);
    "Goodbye for now" (`/unsubscribe`, deliberately skips the standard
    footer unsubscribe link since the email itself already **is** the
    unsubscribe confirmation); "Your transcript's ready" (rewrite of the
    existing `send_completion_email()`'s copy — kept the AI-transcript
    disclaimer box even though the approved doc omits it, the user's
    explicit call, since it's a real standing accuracy-expectation
    warning, not just legal cover); "We couldn't cook this one" (new —
    the doc's "Bonus" entry, the sad-path twin to the above, fires when a
    `TranscriptionJob` gives up after `MAX_CONSECUTIVE_CHUNK_FAILURES`,
    CC's `RESEND_REPLY_TO_ADDRESS` so failures get seen in real time).
  - **Real architecture change**: the resolver (`app/main.py`) previously
    only ever upserted Resend audience contacts — it had zero
    transactional-send capability (that lived solely in
    `archive/utils/email.py`, used by Archive/the worker). It now has its
    own `_resend_send()` + branded-template helpers, deliberately
    duplicated rather than proxied through Archive (same
    deliberate-duplication convention as `get_clerk_user_id()`/
    `_resend_audience_upsert()`) — needs its own copies of
    `RESEND_FROM_ADDRESS`/`RESEND_REPLY_TO_ADDRESS` set in Render (added
    to `render.yaml`, `sync: false` — user still needs to set the actual
    values on the live resolver service, staging and prod, matching
    Archive's existing values).
  - **Not yet live-verified against a real Resend account** — matches
    this repo's own "don't claim a path works without a positive
    example" convention (see `archive/utils/email.py`'s own docstring,
    which flagged the same gap when first built). Covered by monkeypatched
    unit tests only (`tests/test_lifecycle_emails.py`,
    `tests/test_worker_email_notifications.py`). Also unconfirmed live:
    whether Clerk's `user.created` webhook payload actually includes
    `first_name` for every signup method (e.g. email-code vs. Google
    OAuth) — "Hi there," is the documented fallback either way, so a
    missing field degrades gracefully, but the "Hi [First Name]," path
    itself hasn't been seen fire for real yet.
- **[IMPROVEMENT-ROUND] Audit every user-facing email address on the site and consolidate on
  `ally@redtaperecordings.com`.** User request 2026-08-12, after setting
  up `ally@`/`ryan@redtaperecordings.com` forwarding (see
  `BACKLOG_DONE.md`'s "Email deliverability" section) — now that `ally@`
  actually receives mail, make sure it's the address the site actually
  shows/uses, not `ryan@`. A first grep (2026-08-12) found:
  - ~~Two `mailto:` Contact links, both currently `ryan@redtaperecordings.com`~~
    **Fixed 2026-08-16, wave 1 item 1 — full detail in
    `BACKLOG_DONE.md`.** `app/templates/base.html:77` and
    `archive/templates/base.html:95`.
  - ~~`app/templates/about.html:19` shows `ryan@how-to-adu.com` directly
    (the personal inbox, not a `redtaperecordings.com` address at all)~~
    **Fixed 2026-08-16 — full detail in `BACKLOG_DONE.md`.**
  - `RESEND_REPLY_TO_ADDRESS` (`app/main.py`, `archive/utils/email.py`,
    Render dashboard env var per `BACKLOG_DONE.md`'s "Closed out
    2026-08-10" note) is currently `ryan@redtaperecordings.com` — this is
    where transactional-email replies and the "We couldn't cook this
    one" failure CC actually land, so it's in scope too even though it's
    config, not a template string.
  - **Form submissions**: grepped every `<form>` on both services.
    `/api/report-problem` (`app/main.py:704`) only writes a `ProblemReport`
    DB row — no email is sent anywhere today, so there's nothing to
    repoint there yet; this would only become relevant if problem
    reports later grow an email notification. The newsletter signup
    form (`/api/newsletter/signup`) posts to a Resend **audience**, not
    an inbox — no address to repoint either. So "form submissions" turned
    up no actual `ally@`-relevant address yet, unlike the static mailto
    links and `RESEND_REPLY_TO_ADDRESS`.
  - **Deliberately left alone, pending a decision**: `DAILY_REPORT_EMAIL_TO`
    and `YOUTUBE_FETCH_REPORT_EMAIL` (`scripts/daily_report.py`,
    `scripts/fetch_youtube_transcripts.py`) both default to
    `ryan@how-to-adu.com` — these are operator-facing ops digests, not
    site-facing addresses, so probably out of scope for this ask, but
    flagging since they're the same "which Ryan address" question.
- **[IMPROVEMENT-ROUND] New feature request, 2026-08-16: a recurring operator email report
  every 6 hours, to `ryan@redtaperecordings.com`, with 6 metrics** —
  queued worker jobs, failed jobs in the last 48h, succeeded jobs in the
  last 48h, total meetings on site, meetings with a transcript, meetings
  without one.

  **Partially superseded 2026-08-21 — a real, shipped, *daily* worker
  report now exists** (PRs #257-#259, `GET /internal/send-worker-daily-
  report`, triggered by `.github/workflows/worker-daily-report.yml`; full
  build log in `BACKLOG_DONE.md`). It lives on the Archive side exactly
  as this entry's "where this probably belongs" section below predicted,
  and covers overlapping ground: chunks/jobs completed in the last 24h,
  segments added, active jobs, remaining chunks, no-transcript backlog
  count, tier-3-queue-remaining. **What's genuinely still different, not
  covered by the shipped report**: cadence is daily, not 6-hourly; there's
  no explicit "failed in the last 48h" count or "total meetings on site"
  count; and the recipient is whatever `AUTO_TRANSCRIPTION_REQUESTER_EMAIL`
  is set to on the reporting call, not a resolved answer to the
  three-way "which Ryan address" question below. Read the rest of this
  entry as "what's left," not "what to build from scratch" — the
  aggregator half of the "confirmed no equivalent stats aggregator
  exists" claim a few paragraphs down is now stale too.

  Note this is a **third** distinct "Ryan" address in play
  (see the "consolidate on `ally@redtaperecordings.com`" entry in
  Archive roadmap below): `DAILY_REPORT_EMAIL_TO`'s current default is
  `ryan@how-to-adu.com`, the consolidation target is `ally@`, and now
  this request names `ryan@redtaperecordings.com` specifically — worth
  confirming which address this new report should actually use before
  building rather than assuming it should match either existing default.

  **A real, similar mechanism already exists and is the pattern to
  follow, but lives on the wrong service for this data.**
  `app/reporting.py` (imported by `GET /admin/daily-report` in
  `app/main.py:1184` and `scripts/daily_report.py`, triggered daily by
  `.github/workflows/daily-report.yml`) already does almost exactly this
  shape of thing — a `MetricResult` dataclass that lets one metric fail
  without blanking the whole digest, `compose_report_email()`/
  `send_report_email()`, a GitHub Actions cron hitting an admin-token-
  gated endpoint rather than a paid Render Cron Job (see that file's own
  docstring for why). But it queries Clerk/Resend and the **resolver's**
  own database (`meeting_resolutions`) — by design, per its own
  docstring, since `DATABASE_URL` there points at the resolver's DB, not
  the Archive's separate one. **All 6 metrics the user actually wants
  live in the Archive's database instead**: `TranscriptionJob`
  (`archive/db/models.py:95`, status `"pending_confirmation" ->
  "queued" -> "in_progress" -> "completed" | "failed"`, matching
  `worker/main.py`'s own claim query
  `TranscriptionJob.status.in_(("queued", "in_progress"))` for the
  "queued" count) and `MeetingPage`/`TranscriptVersion` for the meeting/
  transcript counts. ~~Confirmed no equivalent stats aggregator exists yet
  on the Archive side~~ **stale as of 2026-08-21 — see the correction at
  the top of this entry.** `archive/db/crud.py`'s
  `get_transcription_queue_summary()` now exists (built the same day for
  the shipped daily report) and is a real aggregator over exactly the
  `TranscriptionJob`/`MeetingPage` data this paragraph describes; it just
  doesn't emit all 6 of the metrics this request originally asked for.

  **Real design question worth deciding before building, not guessed
  at**: `TranscriptionJob` has only a `created_at` timestamp
  ([archive/db/models.py:163](archive/db/models.py:163)) — no
  `completed_at`/`failed_at` column. "Failed/succeeded in the last 48h"
  can only be approximated by *when the job was created*, not when it
  actually finished — a job created 3 days ago that just failed an hour
  ago wouldn't show up, while one created 47 hours ago that's still
  running would count as neither yet. Worth deciding whether that
  approximation is acceptable (cheap, no schema change) or whether this
  needs a new timestamp column (bigger scope, this repo's Alembic
  migration path per `archive/alembic/README.md`) before committing to
  a design. For "meetings with/without a transcript," reuse the
  already-existing quality-aware check
  (`archive/db/crud.py`'s `_has_good_transcript()`, the same
  `_GARBLED_MARKER`-checking logic `list_pages()`'s "✓ Transcript" badge
  uses) rather than a naive "does any `TranscriptVersion` row exist"
  count — this repo already fixed exactly that presence-vs-quality bug
  once (see `BACKLOG_DONE.md`'s "quality-aware, not just presence-aware"
  entry) and shouldn't reintroduce it here.

  **Where this probably belongs**: a sibling of `app/reporting.py`
  inside `archive/` (its own `reporting.py`, a new admin-token-gated
  endpoint in `archive/main.py` following the same `_admin_token_ok`
  pattern, a new GitHub Actions cron workflow on a 6-hour schedule
  instead of daily), reusing `archive/utils/email.py`'s existing
  Resend-send helper (already used for single-recipient internal ops
  email, e.g. the transcription-failed notification) rather than
  `app/reporting.py`'s private `send_report_email()`, which is scoped to
  the resolver service. Not started — this is a scoped feature request,
  not yet designed in full or built.

## Dormant — needs a real example first `[LATER]`

Long by design, and safe to skip. Nothing here can be built honestly
until a real example turns up — per `CLAUDE.md`'s "never build from
assumption" and "don't claim a data path works without a positive
example" rules. An entry leaving this section usually means somebody
found the example, not that somebody decided to guess.

### Captions — formats and sources with no confirmed positive example

- **[LATER] CLAUDE.md's working-conventions section currently states CivicClerk
  and eScribe have "no example anywhere with populated captions" — a DB
  query 2026-08-16 found real, populated caption content for both,
  worth reconciling rather than trusting either claim blind.** Counts
  from `transcript_versions` (`is_default=true, source='scraped'`): 26
  CivicClerk rows (avg ~2,200 segments each) and 147 eScribe rows (avg
  ~2,760 segments each), both with real, non-empty spoken-text content —
  not just placeholder/agenda-only rows. Two ways to reconcile this,
  neither confirmed: (1) CLAUDE.md's claim may be about a narrower thing
  specifically — e.g. CivicClerk's `closedCaptionTracks` field by name,
  which the same doc separately calls out as "schema-verified but not
  content-verified" — rather than "any populated caption content from
  this platform at all," in which case both claims could be true
  simultaneously about different things; or (2) the doc is genuinely
  stale and real examples have shown up since it was last updated (the
  same kind of doc-drift the "App-wide audit" section elsewhere in this
  file already flags as a real, confirmed problem, not hypothetical).
  Whoever picks this up should pull a couple of the 26/147 rows and read
  them end to end before editing CLAUDE.md either way — this entry is
  from a DB count, not a read-through.

  **Half-closed 2026-08-18**: eScribe's version of this gap is now
  settled with a real positive example — Peel Region, ON's "Regional
  Council" meeting resolves with 1101 real caption segments, zero
  warnings, and `CLAUDE.md` has been updated to say so. CivicClerk's own
  version is still unconfirmed either way, which is the half this entry
  should now be read as covering.

- **[LATER] ChampDS real captions confirmed to exist for at least one customer —
  but the URL to actually fetch them is still unknown (2026-08-16).**
  `champds.py`'s own docstring said `MediaInfo.Captions` was empty on
  every one of the 6 original customers checked, so caption parsing was
  deliberately never built. Re-checked against 61 fresh real URLs from
  this session's champds enumeration (see `BACKLOG_DONE.md`): 1 (`play.
  champds.com/atlantaga/event/1077`) has real, populated `Captions`:
  `[{"LanguageName": "English", "LanguageID": "en", "MediaPath":
  "/2026-03/eaec74850c81b8ef2877faa746c28b61dc836fb4.vtt"}]` -- a real
  positive example finally exists, so this is worth building. **But the
  URL to actually fetch that MediaPath is still unconfirmed** -- tried
  and ruled out: (1) the raw MediaPath prepended with `play.champds.com`,
  `playapi.champds.com`, and a `/{customer}/` prefix -- all 404. (2) Full
  reverse-engineering of every JS file the real event page loads
  (`cds.event.js`, `override.cds.event.js`, `cds.common.js`,
  `cds.constants.js`) -- zero references to "caption"/"vtt"/"track"
  anywhere, meaning the current champds.com frontend may not even render
  captions client-side yet, so there's no JS code to copy the pattern
  from the way the `/ATT/{customer}/...` attachment-URL pattern was
  found. (3) The confirmed-working `DOWNLOAD-MEDIA` endpoint
  (`/DOWNLOAD-MEDIA/{customer}/eventmainmedia/{event_id}`, what
  `video_url` already uses) accepts a `type` path segment -- tried 10
  plausible values (`caption`, `closedcaption`, `cc`, `transcript`,
  `subtitle`, etc.), every one came back **501 Not Implemented** (not
  404) confirming the endpoint recognizes *a* type parameter but not
  which string is correct. Stopped guessing rather than keep trying
  strings blind, per this repo's own "don't claim a caption path works
  without a positive example" convention -- a URL that happens to work
  by luck isn't understood well enough to trust or document.

  **Update 2026-08-16, same session: confirmed live in-browser this
  isn't a "wrong trigger" problem -- the champds.com frontend genuinely
  never wires up captions at all, for this meeting or any other.**
  Loaded `play.champds.com/atlantaga/event/1077` for real, played the
  video, and explicitly clicked the player's own "Captions" button and
  selected the "english cc" menu option -- no `.vtt`/caption network
  request fired at any point (confirmed checking every request, not just
  ones matching a `vtt` filter, in case the real URL is an opaque/hashed
  path the way TelVue's `closed_captions/{signed-blob}` one is). Direct
  DOM inspection after all of that confirms why:
  `document.querySelector('video').textTracks.length === 0` and zero
  `<track>` elements exist anywhere in the page -- the "Captions" menu
  video.js renders is its own generic default UI, not backed by a real
  track, so selecting a language does nothing. This matches the earlier
  JS-source finding (zero caption references in any loaded script) from
  the other direction: there is no live, observable request anywhere on
  champds.com's own site that reveals the real caption URL, for *any*
  customer, not just ones without a special "captions enabled" state.
  `MediaInfo.Captions` being populated in the API is real, but appears to
  be dead/unused data the current frontend doesn't consume -- building
  around it now would mean guessing a URL nobody has ever confirmed
  works, not copying a real one. Only remaining path forward is ChampDS's
  own API docs/support, not further live investigation from this side.
- **[LATER] TTML/DFXP/ITT caption parsing (`app/utils/vtt_parser.py`'s
  `parse_ttml()`) is spec-verified only, not sample-verified.** Built
  against the W3C TTML spec's documented shape after the CivicClerk SRT
  finding below prompted a broader look at caption format assumptions —
  no CivicClerk/Granicus/Swagit/CA Legislature sample has ever actually
  used TTML/DFXP/ITT (every real populated caption seen so far is VTT or
  SRT). Handles clock-time and offset-time (seconds/ms) timeExpressions;
  frame-based ("40f") and tick-based ("2t") are explicitly unsupported
  (no frame rate available to convert with — skips that cue rather than
  guessing). If a real TTML/DFXP sample turns up, verify against it and
  update this note.
- **[LATER] SBV/SUB/SMI/SAMI/plain-.txt captions get a generic best-effort text
  fallback (`strip_unknown_caption_markup()`), not real per-format
  parsing.** No per-line timing, since these formats were never actually
  observed either — the fallback exists so real caption text isn't
  silently dropped (per-line clickability isn't required; `t=`
  deep-linking to the video's playhead never depended on transcript
  timing). Wired into Granicus, CA Legislature, Swagit, and CivicClerk.
  If any of these turns out to be common on a real platform, worth a real
  structured parser instead of the generic strip.
- **[LATER] SCC/STL captions are detected but not readable at all.** Both are
  binary/encoded (EIA-608 line-21 data, EBU subtitle format) — no text
  can be extracted without real codec-level decoding, so these just
  surface as a direct link ("you can view it directly: {url}") rather
  than attempted content. Genuinely low-probability for a small city's
  web captioning vendor (these are broadcast-editing interchange
  formats), so not worth building unless a real example turns up.
- **[LATER] Row-level CC/SRT files in Legistar/CivicPlus calendar listings** —
  user's instinct that a calendar row might expose a direct caption file
  link alongside the video link, more reliable than what the destination
  video platform's own page offers. Checked Maricopa AZ, Westlake Village
  CA, San Diego city/county, both Berkeley Legistar calendars — none had
  one. Not disproven, just not found yet; extend `LegistarAssetFinder`/
  `CivicPlusAssetFinder`'s row-scraping when a real example turns up.
- **[LATER] YouTube/PrimeGov: non-English captions untested**, and it's unknown
  whether the manual-vs-auto-generated track coverage gap seen on the one
  real LA sample (see [BACKLOG_DONE.md](BACKLOG_DONE.md)) is typical or
  specific to that video. Two tangential non-English-caption leads found
  2026-08-11 (see below), neither on YouTube/PrimeGov itself: Riverside
  County CA runs a parallel `board-supervisors-meeting-videos-spanish`
  page, and a third-party Internet Archive mirror of Virginia Beach
  council meetings (`archive.org/details/covbva-*`) carries real
  `.es.asr.srt` files alongside the English ones.

### Per-tenant and per-adapter cases waiting on a second example

- **[LATER] `riversidecountyca.iqm2.com` stays `platform="unknown"` despite
  `iqm2.py` clearly having an adapter for `iqm2.com` domains — found
  2026-08-16 doing backlog hygiene, not yet root-caused.** This exact
  URL was already re-ingested once via the tier-3 feeder (see the
  `page.platform` entry in `BACKLOG_DONE.md`, PR #70) and a fresh
  `/internal/pages/all-urls` pull still shows it `unknown`. Read
  `scripts/feed_tier3_auto_transcription.py`'s own push logic
  end-to-end — it does call `detect_platform()`/`get_finder()` correctly
  and sends `result.model_dump()` (which includes a real `platform`
  field) to `/internal/ingest`, so the obvious "script bug" hypothesis
  doesn't hold up by inspection alone. Needs real live debugging (check
  the actual DB row / re-trigger and inspect the exact payload sent) to
  find the real cause, not another guess -- flagged here rather than
  guessed at further.

- **[LATER] IQM2 (`app/platforms/iqm2.py`) — Riverside County, CA's real title/
  jurisdiction extraction should work by inspection but doesn't in prod,
  user-reported 2026-08-14, not touched by the generic-fallback rebuild
  above (this is a separate dedicated adapter).** Real example:
  [riversidecountyca.iqm2.com/Citizens/SplitView.aspx?Format=Agenda&MeetingID=3499&Mode=Video](https://riversidecountyca.iqm2.com/Citizens/SplitView.aspx?Format=Agenda&MeetingID=3499&Mode=Video)
  (`/m/meeting-4fefb4`). Confirmed live: video plays fine (real Granicus
  HLS delegation working as designed), but "Untitled meeting," no
  jurisdiction. Fetched the exact `outline_url` this adapter itself
  builds
  (`.../Citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline&Mode=Video&Frame=Nothing&ID=3499`)
  directly via `curl` — its `<title>` is real and well-formed:
  "2026/08/12 09:30 AM (RCTC-GM) Riverside County Transportation
  Commission General Meeting Regular Meeting - Web Outline - Riverside
  County, California," which matches `_TITLE_RE` cleanly by inspection
  (date group, "(RCTC-GM) Riverside County Transportation Commission
  General Meeting Regular Meeting" as the meeting name, "Riverside
  County, California" as jurisdiction — the exact same "{name} - Web
  Outline - {jurisdiction}" shape already confirmed working for Atlanta
  and Santa Clara County per this file's own IQM2 build notes).

  So unlike the OCFL/Sacramento/Maricopa cases above, this doesn't look
  like a stale-archive-page artifact (no known IQM2 fix has shipped since
  this page was likely first resolved) or an extraction-logic gap (the
  regex should match) — it's a real, unexplained discrepancy between what
  a plain `curl` fetch sees and what production's actual resolve found,
  same open-question shape already flagged for the OnBase counties before
  their fix was found (a query-string/entity-decoding bug, in that case).
  Not yet root-caused for IQM2 specifically — needs the same kind of live
  debugging (what does `iqm2.py`'s own `aiohttp` fetch actually receive
  from Render, not just a replayed local `curl`) rather than a guess.

  **Update 2026-08-14: root cause narrowed further — the real
  `IQM2AssetFinder().resolve()` code path, run directly (not a bare
  `curl` replay), returns correct title/date/jurisdiction right now.**
  Ran the actual adapter against the live URL: title
  "(RCTC-GM) Riverside County Transportation Commission General Meeting
  Regular Meeting", date "2026-08-12", jurisdiction "Riverside County,
  California" — all correct, matching the by-inspection expectation
  exactly. `agenda_items` came back empty, but that's real and
  independently confirmed, not part of this bug: the live outline page
  for this specific meeting has zero `AgendaOutlineLink` entries (fetched
  directly, `AgendaOutlineLink` count is 0), the same "not every
  commission/meeting on this instance gets timestamped items" gap already
  documented for Santa Clara County above, not a title/jurisdiction
  extraction problem.

  This shifts the likely explanation back toward a **stale archived
  page**, not a live code defect — the earlier "doesn't look like a
  stale-archive-page artifact" reasoning assumed no relevant fix had
  shipped since this page was first resolved, but the code demonstrably
  works correctly *today*, on this exact real URL, with no code changes
  made. The existing archived page (`/m/meeting-4fefb4`) most likely
  predates whatever state made this resolve correctly (could be an
  incidental fix to shared code — `jurisdiction_enrich`, `_TITLE_RE`,
  or similar — landing after this page was first pushed, not a dedicated
  IQM2 fix). **Not fully closed — still needs one production step this
  session has no access to do**: hit
  `/admin/recheck-archive-page?url=...&token=$ADMIN_STATS_TOKEN` against
  the real production URL to force a fresh resolve + Archive push, then
  confirm `/m/meeting-4fefb4` (or wherever it lands) shows the correct
  title/jurisdiction. If that fixes it, this closes as a stale-page case,
  same shape as the OCFL/Sacramento/Maricopa entries above; if the
  production resolve *still* comes back wrong even after a forced
  recheck, that would be new, real evidence of an actual Render-specific
  runtime difference worth investigating further.

- **[LATER] `generic_fallback.py`'s YouTube-embed branch had no page-level
  metadata backfill, so CRRMA's meeting pages showed "Untitled meeting"
  with no jurisdiction — fixed 2026-08-13, full detail in
  `BACKLOG_DONE.md`.** A separate, real bug surfaced while re-verifying
  the fix live: `YouTubeAssetFinder.resolve_video_id()` unconditionally
  sets `jurisdiction=info.get("uploader")` (a channel name) whenever
  yt-dlp succeeds, and every caller that delegates to it has to know to
  override that afterward or the channel name leaks through as a fake
  jurisdiction. **Audited every direct `YouTubeAssetFinder` delegator
  2026-08-13**: PrimeGov (already unconditional-override), LIMS (already
  fixed, same day), `slc.py` (always unconditional, hardcoded single
  jurisdiction), generic_fallback (fixed this pass), and CivicWeb (fixed
  this pass, same day — see `BACKLOG_DONE.md`) are all now safe.
  **Still genuinely unconfirmed**: `legistar.py`'s *primary* delegation
  path ([legistar.py:111-117](app/platforms/legistar.py:111-117)) only
  overrides jurisdiction via `resolved.jurisdiction or page_info[...]`
  — i.e. prefers whatever the delegated platform set, falling back to
  Legistar's own page info only when empty — and only runs at all when
  `resolved.title` looks like a raw filename. This only matters if a
  Legistar video link ever resolves directly to a bare YouTube URL
  (rather than the far more common Granicus delegation, where this isn't
  an issue) with a raw-filename-shaped title; no real example of that
  specific combination has turned up yet, so not touched without one —
  same "don't fix without a confirmed example" convention as everywhere
  else in this file. Worth revisiting either this path or fixing the
  root cause once and for all in `youtube.py` itself (stop setting
  `jurisdiction` from `uploader` at the source, rather than requiring
  every caller to remember to override it) if a real example surfaces.

  **Still open, a real UI/copy question, independent of the extraction
  fix above**: what should render when metadata truly can't be found by
  any method at all? Today's convention is a bare "Untitled meeting"
  (`meeting_page.html:98`'s dropdown and `meeting_list.html:90`'s browse
  listing both share the exact same `m.title or "Untitled meeting"`
  fallback) — user's suggestion: something more like "Temporary Name:
  meeting-732f78" that signals "we know this is incomplete" rather than
  reading as broken/empty. Not decided or built.

  **User's follow-up idea, 2026-08-13**: instead of a bare placeholder,
  try a much looser best-effort grab (any plausible `<h1>`/`og:title`/
  meta-description text, not the strict `<title>` "split on `|`" pattern
  the CRRMA fix uses) and label it "Maybe: {result}" to signal low
  confidence. **Checked against the one real remaining "Untitled
  meeting" page in the whole Archive before building anything** (Tucson,
  AZ on Hyland's "221 Agenda Online" — see the new platform-coverage
  entry above) — it disproves that a looser regex would help in
  general: that page's raw HTML has *no* usable static text anywhere at
  all (confirmed via `curl`, everything renders client-side via AJAX),
  so even the loosest static-HTML regex would still find nothing. For
  this class of failure specifically, only a real headless-browser fetch
  (a much bigger, new-platform-shaped build) or the plain placeholder
  idea would actually help — the looser-regex idea is real and worth
  keeping for a *different* kind of failure (a page with SOME static
  text that just doesn't happen to match the strict `<title>`-pipe
  shape), but only one confirmed example exists today and it's the wrong
  shape to validate that specific idea. Needs a second real example of
  *that* failure mode before committing to a "Maybe:" shape — not
  abandoned, just not enough evidence yet either way.

  **Update 2026-08-13: that second example has now shown up, user-found
  at
  [cityofsebastopol.gov/events/city-council-meeting-january-6-2026/](https://www.cityofsebastopol.gov/events/city-council-meeting-january-6-2026/)
  — two real, separately-confirmed gaps on this one page.** ~~Title/
  jurisdiction extraction~~ **fixed 2026-08-13 — full detail in
  `BACKLOG_DONE.md`.** ~~The Vimeo video piece~~ **surfaced 2026-08-14
  via the new video-pointer outcome (`ResolvedMeeting.video_link`, see
  `BACKLOG_DONE.md`'s rebuild entry): the page now shows "we think the
  video is here: <the real vimeo link> — we recognize vimeo.com as a
  regular video host, but can't embed it here yet", live-verified
  in-browser.** Actual Vimeo *playback* (embedding + captions) is still
  the separate, bigger gap tracked in the Vimeo entry above — the
  pointer is the honest middle ground until that exists.
  **Closed 2026-08-21 (WO-29): real Vimeo playback now exists, and this
  page resolves through `_try_delegate_to_known_platform()` with a real
  embedded, seekable video plus the page's own agenda PDF — exactly the
  "for free, no page-specific work needed" outcome predicted here.
  Live-verified in-browser, `?t=` deep link included.**

  **Re-checked live 2026-08-14 after a user report that jurisdiction
  "still doesn't grab" here — doesn't reproduce.** Live-replayed this
  exact URL just now: jurisdiction renders correctly as "Sebastopol, CA"
  on its own line under the title, exactly the sitewide convention, plus
  the video pointer described above. Worth a straight correction rather
  than a new bug entry — this page appears to already be working as
  intended on both fronts described in this update; if the user still
  sees it missing, worth comparing browser/cache state rather than
  assuming a live regression, since this exact URL just resolved clean.

- **[LATER] ChampDS's `MediaInfo.VOD2` HLS case (the majority of real
  customers) still has no playable video.** The adapter itself was built
  2026-08-13, full detail in `BACKLOG_DONE.md`.
  New `app/platforms/champds.py`, confirmed live against 6 independent
  real customers. **Real, confirmed blocker found while building, not
  just theorized**: `MediaInfo.VOD2`'s HLS URL (the *majority* real
  case — 4 of 6 customers checked have no `DownloadURL` at all) sits
  behind a strict `Referer: https://play.champds.com/` check on
  `securestream10.champds.com` that this site's own browser requests
  can't satisfy — confirmed live via `curl` with several different
  referers, all rejected except champds.com's own. Only the direct-MP4
  `DownloadURL` case (2 of 6 customers) is wired up to actually play;
  the VOD2 case still gets full metadata + agenda link, just an honest
  "no video found" instead of a link that would 406 in the browser. A
  real streaming reverse-proxy (fetch server-side with the right
  header, rewrite every segment URL in the playlist to route back
  through it) would unblock the other 4 — real, scoped follow-up work,
  not attempted this pass.

- **[LATER] El Paso, TX studied as a real test case for the channel-discovery
  question above — user's idea 2026-08-12, prompted by the CRRMA
  "Untitled meeting" entry earlier in this file**: given a known Vimeo
  (or YouTube) channel with no direct government-page link, can search
  engines find the .gov page that embeds/links to a specific video?
  **Real answer for El Paso specifically: didn't need to find out** — a
  much better path exists and makes the search-engine approach
  unnecessary here. `www.elpasotexas.gov/videos/` is a plain,
  server-rendered page (confirmed via direct `curl`, no JS needed) that
  directly links out to **every one of the city's Vimeo showcases**, one
  per body — `vimeo.com/showcase/{ad-hoc, agenda-review, boac,
  budget-hearing, building-standards, city-plan, crrma, csc, fhtf, foac,
  open-space, special-cc, veterans-affairs}` — plus the city's real
  YouTube channel (`youtube.com/user/cityofelpasotx`). Notably,
  `vimeo.com/showcase/crrma` ("Camino Real Regional Mobility Authority")
  exists too — the *same* CRRMA meetings from the earlier "Untitled
  meeting" entry may have a second, better-organized source here, worth
  checking directly against that specific 2025-11-12 meeting before
  assuming CRRMA's own bare YouTube embed is the only source.

  **The search-engine reverse-lookup idea itself, tested directly, came
  back inconclusive/negative** — worth recording since it answers the
  user's actual question, not just the El Paso side-question: neither
  `site:elpasotexas.gov vimeo.com` nor a direct search for
  `"vimeo.com/eptx"` / a specific showcase URL surfaced the
  `elpasotexas.gov/videos/` page that's proven to link to it. Not
  conclusive proof the technique never works elsewhere (one real city,
  one real search backend, on one particular day), but real, live
  evidence that it isn't reliable enough to lean on as a general
  strategy — a direct, methodical crawl of a known city's own domain
  (the way `elpasotexas.gov/videos/` was actually found here, via a
  *different* real search query about El Paso's video setup generally,
  not a reverse-lookup of the Vimeo URL itself) looks like the more
  promising general pattern than reverse image/embed search.

  ~~**Still blocked on the same foundational gap already flagged for
  Chicago ELMS above**: this app has zero Vimeo playback support today~~
  **Unblocked 2026-08-21 (WO-29) — see `BACKLOG_DONE.md`.** Every one of
  El Paso's 13 showcases now resolves: pasting `vimeo.com/showcase/crrma`
  returns a real pick-list of that body's meetings, and picking one plays
  it with working deep links.

  **Two corrections to what this entry claimed, both found by actually
  checking rather than re-reading it**: (1) `vimeo.com/showcase/{id}`
  pages are **not** JS-rendered in the way that mattered — the *visible*
  markup is, but the raw HTML embeds a real, server-rendered JSON-LD
  `ItemList` of `VideoObject`s carrying each meeting's real name, URL and
  upload date. That's exactly the per-showcase video list this entry said
  "wasn't confirmed" and would need Vimeo's own API or a headless-browser
  fetch to get; it needs neither, just a plain `curl` and a JSON-LD read.
  (2) The same is true of channel pages (`vimeo.com/channels/{name}`),
  confirmed live on Salisbury NC. A bare *user* page
  (`vimeo.com/rocklandmaine`) genuinely IS client-rendered with zero video
  ids in the raw HTML — that part is real, and is why the adapter
  deliberately doesn't claim that shape.

  **Residual, still real**: `www.elpasotexas.gov/videos/` — the plain
  server-rendered index linking out to all 13 showcases — has no adapter
  of its own, so pasting *that* URL still lands in `generic_fallback.py`
  rather than producing a "pick a body, then pick a meeting" flow; a user
  has to know to paste a specific showcase. Low priority now that the
  showcases themselves work, but it's the honest remaining edge here.

- **[LATER] Legistar's own MeetingDetail.aspx page carries real metadata that
  `LegistarAssetFinder` never scrapes at all — confirmed live 2026-08-12
  on a real example the user flagged**
  ([mesa.legistar.com/MeetingDetail.aspx?ID=1428059](https://mesa.legistar.com/MeetingDetail.aspx?ID=1428059&GUID=C6D3581F-B224-4A1C-A59D-0885C238FD52&Options=info|&Search=),
  a real Mesa, AZ City Council meeting, video delegated to YouTube).
  - ~~**`Published agenda: Agenda / Accessible Agenda`**~~ **Fixed
    2026-08-13 — full detail in `BACKLOG_DONE.md`.** New
    `_extract_agenda_link()`, applied regardless of title quality (unlike
    the existing title/jurisdiction/date backfill, which only fires when
    the delegated platform's own title looks bad) since it's real, useful
    data even when everything else already resolved fine — it's just a
    fallback for whenever the delegated platform didn't already find its
    own agenda link.
  - **`Meeting location: Study Session / Special Council Meeting` — still
    open, deliberately not touched.** Re-checked live 2026-08-13: this
    field is genuinely labeled "Meeting location" but Mesa's real value
    is a meeting-type descriptor, not a physical address. Unconfirmed
    whether that's true for every Legistar customer or just how Mesa
    happens to use the field (a different customer might put a real
    room/address there instead) — blending it into the title without
    knowing which case applies risks either a useful distinction
    ("Study Session") or nonsense ("123 Main St, Council Chambers")
    depending on the customer. Needs a second real example before
    deciding how (or whether) to use it, same "verify against real
    examples" convention as everywhere else in this file.
  - The third item on this page — a real "Meeting Items" table with
    substantive per-item text — is a **standing decision**, not an open
    TODO: the user weighed it 2026-08-12 and called it "probably not worth
    pursuing." Full reasoning at the top of this file.

- **[LATER] Baltimore's Legistar instance (`baltimore.legistar.com`) — how often
  does a meeting actually have video in the attachments table, and is
  there a better way to find it when it's missing?** Prompted by the user
  noticing, 2026-08-12, that most Baltimore meetings they're seeing don't
  have one, "interesting that this one does" (the
  [City Council Hearing, 2025-10-20, ID=1282692](https://baltimore.legistar.com/MeetingDetail.aspx?GUID=5353B4B6-3F2D-4E02-8DA0-F62A82299422&ID=1282692&Options=info|&Search=)
  from the resolution-mechanics question just above — its real YouTube
  "Recording" link is what `_try_fallback_video_link()`
  ([app/platforms/legistar.py](app/platforms/legistar.py), built for
  Baltimore originally, see `BACKLOG_DONE.md`) exists to catch).

  **A quick real check confirms the pattern, doesn't yet explain it**:
  pulled 4 meeting IDs straight off `baltimore.legistar.com/Calendar.aspx`
  (1332199, 1376920, 1376921, 1405006) — every single one has a
  completely empty `Attachments:` field, no video, no Recording link,
  nothing. 4-for-4 empty vs. the one known-good example isn't enough of a
  sample to conclude anything about *why* (different meeting body?
  different era — this may just be a backlog of not-yet-processed/older
  meetings on the general calendar? only certain meeting types get a
  recording attached at all?), just enough to confirm the user's
  observation is real and not a fluke.

  **Next real step, not yet done**: work through
  [baltimore.legistar.com/Departments.aspx](https://baltimore.legistar.com/Departments.aspx)
  — Baltimore's full directory of boards/committees/departments — to find
  a specific body's own meeting list rather than sampling the mixed
  general calendar. Two candidate "City Council" entries found there
  already: `DepartmentDetail.aspx?ID=28879` ("City Council") and
  `ID=28881` ("Baltimore City Council") — worth checking whether either
  gives a curated meeting list for the same body the one working example
  belongs to (full Council plenary sessions, as opposed to a subcommittee)
  and, if so, whether *that* body's meetings consistently have video
  attached even when the general calendar sample above doesn't. (A first
  attempt at `DepartmentDetail.aspx?ID=28879` didn't surface meeting links
  directly — may need a different nav path, e.g. a Meetings tab/param,
  not yet found.) If a real pattern falls out (e.g. "only full Council
  sessions get recordings, subcommittees don't"), that's a genuine signal
  worth teaching the adapter or the frontend about; if it's closer to
  "video is attached inconsistently, no real pattern," that's useful to
  know too, before investing in a fancier fallback (e.g. a CharmTV-
  channel search, the same class of fix already flagged for Phoenix/
  Philadelphia/Albuquerque above).

  **Update 2026-08-21 (WO-30): the "fancier fallback" this entry was
  weighing got built, and it answers the practical half of the question
  without answering the curiosity half.** `app/platforms/youtube_channel.py`
  now matches Baltimore meetings against CharmTV's own channel
  (`@TV25BCOCC`, earned by reading `channel_id` off the one known-good
  `youtu.be/XFaAY2G_cl0` link this entry cites) -- measured across 53
  real Legistar events 2026-05-01..2026-08-20, 29 now resolve to a real
  recording. **The original question is still genuinely open and now
  lower-stakes**: attachment really is inconsistent rather than following
  a body/era rule (the 2026-08-05 Public Health & Environment hearing
  carries its own link while the same day's Board of Estimates doesn't,
  same era, both full standing bodies), and the `Departments.aspx` walk
  suggested above was never done. Worth finishing only if someone wants
  the *why*; the coverage cost of not knowing is now largely paid.

- **[LATER] Headless-browser adapters (Minneapolis LIMS, SLC meeting recaps) —
  built and shipped 2026-08-09, see BACKLOG_DONE.md for the full build.
  Real, still-open follow-ups:**
  - **Not yet checked: whether "LIMS" is a white-labeled product used by
    other cities under different domains** (would matter for whether a
    general detection rule is worth building, vs. this staying a
    Minneapolis-specific one-off) — no search attempted yet, per this
    repo's own convention of building from real found examples rather
    than speculation.
  - **SLC's `_nearest_topic_text()` silently drops one real item per
    page it's been checked against** — a page's single "highlight" story
    (e.g. "Fraud Risk Assessment for Salt Lake City" on the March 3,
    2026 page) uses a different HTML shape (a "Learn More" / "Watch the
    Briefing" promo box, topic text as a preceding heading rather than in
    the same paragraph as the link) than the plain "{topic}. (Watch)"
    pattern the other items use — confirmed live, that item's timestamp
    (`t=2455`) never becomes an `agenda_items` entry. Safe failure mode
    (silently skipped, not garbage text) but a real, known gap — fixing
    it would need walking up to a preceding heading when the same-
    container text comes back empty, deliberately not attempted yet
    given the risk of a fragile heuristic picking up the wrong heading on
    a page shaped differently again.
  - ~~**Real Render deployment of the `playwright install chromium`
    build step is genuinely unverified**~~ **Verified working 2026-08-14.**
    A fresh, never-archived Minneapolis LIMS meeting
    (`lims.minneapolismn.gov/MarkedAgenda/COW/6144`) resolved fully
    through production — real YouTube video, title, date, and 6
    timestamped agenda items. LIMS's `resolve()` calls
    `fetch_via_browser()` unconditionally for both of its fetches with
    no non-browser path, so that success is direct proof the plain
    `playwright install chromium` build step (post-`--with-deps`-removal,
    see `render.yaml`'s incident comment) produces a launchable Chromium
    on Render's `runtime: python` buildpack — Render's base image really
    does carry the needed shared libraries, same as ffprobe turned out
    to already be present. `runtime: docker` not needed. This
    verification is also what green-lit enabling the generic fallback's
    `GENERIC_FALLBACK_HEADLESS=1` escalation in prod the same day —
    end-to-end confirmed post-deploy: the Wayne County, MI page (fully
    Akamai-blocked, a total loss two days earlier) resolved through
    production's own browser with real video/title/jurisdiction/date/
    agenda-PDF, and got archived as a permanent page in the process.
  - **Headless-browser fetches are real, meaningfully slower than every
    other adapter here** — a real resolve for LIMS needs *two* sequential
    fetches (agenda page for title/date, JSON endpoint for video/
    timestamps), each with its own page-load + Cloudflare-challenge wait.
    No caching or performance work done yet; worth watching real-world
    resolve latency for these two platforms once deployed, not assumed
    fine because it worked acceptably in manual live-testing.
  - **Given Tier 1 (direct video embed via a real headless browser) now
    confirmed working for both real Cloudflare-gated cases found so
    far, the Tier 2 (iframe the government's own page) / Tier 3
    (explanatory fallback message) design questions raised alongside
    this work are lower priority than they looked before this was
    built** — not deleted, since a future Cloudflare-gated platform
    could in principle resist even a realistic-UA headless fetch (untested
    against a third real case), just no longer the default assumption
    for "what happens when we hit Cloudflare next."
- **[LATER] Stale archived transcripts have no automated refresh path — real gap
  confirmed 2026-08-12 fixing the Minneapolis ALL-CAPS report (see
  BACKLOG_DONE.md for the fix itself), two distinct pieces still open.**
  Everything needed to *manually* fix one specific page now exists
  (fetch a fresh transcript locally, push it, promote it), but nothing
  automated will ever do this on its own for a page that already has a
  transcript, however bad:
  - **Re-submitting an already-archived URL through the normal public
    `/api/resolve` flow does not refresh stale content.**
    `archive_client.lookup()` runs *before* any live resolve (see
    README's "Lookup, before resolving") and short-circuits straight to
    the existing page the moment a permanent page is found, so a live
    re-resolve never even starts. The only ways to force a refresh are
    `/admin/recheck-archive-page` (token-gated) or the passive 30-day
    `ARCHIVE_RECHECK_AFTER` cycle — no public, no-token way for anyone to
    ask for one specific stale page to refresh sooner.
  - **`scripts/fetch_youtube_transcripts.py`'s queue
    (`GET /internal/transcript-wanted`) only ever returns YouTube-backed
    pages with *no* default transcript at all** — a page with an
    existing-but-bad transcript (stale, ALL-CAPS, pre-fix artifacts, or
    otherwise low quality) never qualifies as "wanted," so the daily
    script will never pick it up and re-fetch it, no matter how long it
    runs. Combined with the point above, a YouTube-delegated page that
    got a bad transcript once will stay that way indefinitely unless
    someone manually repeats the exact fix-it-by-hand process used for
    Minneapolis (fetch locally, push via `/internal/ingest`, promote via
    the new `/admin/promote-transcript-version` — see BACKLOG_DONE.md).
    Worth deciding whether the queue should also surface low-quality-
    flagged pages, not just missing ones, and/or whether recheck should
    be able to trigger this same script's path for one page on demand.
- **[LATER] Swagit custom-domain embeds unverified** (e.g. `dublin.ca.gov/
  swagit-video-player?video_id=...`). `detect_platform` recognizes the URL
  shape, but the one sample URL 404'd — parsing has only been verified
  against real `*.swagit.com` domains. Needs a fresh sample URL.
  **Re-checked live 2026-08-11 (Wave 2 survey): still a hard 404, not
  fixed or superseded.** A broad survey of large-city Swagit usage
  turned up plenty of fresh `*.new.swagit.com`/`*.swagit.com` samples
  (Houston, Dallas, Austin, San Antonio, Long Beach, League City TX,
  Yountville CA) but zero examples of this specific
  `cityname.gov/swagit-video-player?video_id=...` shape working
  anywhere. The closest related case found — Dallas's
  `dallascityhall.com` embedding Swagit video via a plain `<iframe
  src="https://dallastx.swagit.com/...">` — is a different shape
  (generic fallback's existing "look for a link/iframe to a platform we
  support" logic already resolves it, since the iframe `src` is a real
  `*.swagit.com` URL) and doesn't substitute for a real sample of
  Dublin's self-contained custom-domain player. Genuinely still open.

### Platform discovery & enumeration — leads not yet chased

~~**[LATER] TelVue host enumeration — not yet built.**~~ **Partially done
  2026-08-16 via the web-search method, not the systematic CDX pass this
  entry originally called for — real result, real remaining gap.** The
  web-search-first method (proposed below, and validated on Legistar the
  same night) found several real, currently-working
  `videoplayer.telvue.com` meeting URLs, including one genuinely new
  real jurisdiction: Fitchburg, MA (FATV), 956 real transcript segments,
  22 agenda items — ingested for real. Full detail, including how its
  opaque per-customer token was identified (quoting the token itself in
  a follow-up search), in `CDX_QUERIES.md`. **Still not done**: a
  systematic `hosts_telvue.txt` the way Legistar's 19-host list exists
  now — this was a handful of confirmatory searches, not the same scale
  of effort, and the CDX-side complications this entry originally
  documented (200k-row cap, opaque token, mixed path shapes) are still
  real and still unaddressed if someone wants full coverage rather than
  a few more spot-checks.

  **Real bug found via this work, fixed same day**: `telvue.py`'s
  `_guess_jurisdiction()` mismatched a bare "City Council - 5.6.2025"
  title (Fitchburg's real title has no city-name prefix at all) as
  jurisdiction="City", which then got a state appended downstream —
  "City, MA" ended up as the real ingested jurisdiction, and the slug
  it produced (`city-ma-city-council-5-6-2025`) is now permanently
  wrong for that one already-ingested page (slugs don't regenerate on
  re-ingest, by design — re-ingesting after the fix didn't change it).
  Fixed in `_guess_jurisdiction()` to reject bare "city"/"town"/
  "village"/"township" as a name; regression test added
  (`tests/test_telvue.py::test_guess_jurisdiction_rejects_generic_placeholder_words`).
  The one bad existing slug is cosmetic (still resolves, still has the
  real transcript) and not worth a manual DB fix on its own.

  **Legistar CDX enumeration came back empty on the first attempt, then
  the web-search method fixed it for real, 2026-08-16.** A domain-wide
  CDX scan of `legistar.com` found 0 usable hosts (matches CivicPlus's
  same-shaped failure below). The web-search-first method found 19 real,
  currently-active customer subdomains instead — full list, stage-2
  seek results (19/19 hit), and the caption-yield breakdown are in
  `CDX_QUERIES.md`, not duplicated here. **Two of those 19 turned into
  genuinely new real captioned jurisdictions, checked against
  `/internal/pages/all-urls` before ingesting and confirmed not already
  present**: Lake County, IL (via `cablecast`, 162 segments) and City of
  Saint Paul, MN (via `granicus`, 1,029 segments) — both ingested for
  real via `bulk_ingest.py`.

  **CivicPlus CDX enumeration attempted 2026-08-16, came back empty**
  (`hosts_civicplus.txt` in `rtr-business/research/`, 0 usable hosts) —
  didn't surface a meeting-page path template the way CivicWeb's did.
  **Unlike Legistar/TelVue, the web-search method wasn't tried and isn't
  obviously the right next step**: CivicPlus is a general city-website
  CMS that delegates to Granicus/Legistar for actual video (confirmed,
  see this file's own delegation-pattern note near the top), not a
  distinct video platform — searching `civicplus.com` directly would
  mostly just re-surface Granicus/Legistar hosts already reachable more
  directly through their own enumeration. Not rated in
  `HYLAND_DISCOVERY.md`'s probability table for this reason. If this is
  ever worth revisiting, the real target is whatever specific
  meeting-page path CivicPlus sites link out to, not `civicplus.com`
  itself.

  Full status of every platform's CDX progress (including
  PrimeGov/CivicWeb/eScribe/IQM2/ClerkBase/ChampDS, which all got real
  stage-2 yields the same night) is in `CDX_QUERIES.md` directly — not
  duplicated here to avoid the two drifting apart again.

- **[LATER] CivicPlus has zero currently-live, confirmed-real URLs
  anywhere in this repo, re-confirmed 2026-08-16 building the WO-13
  adapter health canary.** `ca-westlakevillage.civicplus.com` — the one
  site this adapter was ever verified against — already had a documented
  note (`tests/fixtures/civicplus/README.md`) saying it stopped resolving
  as of 2026-08-07; a live DNS lookup while building the canary confirmed
  it's still dead (`ClientConnectorDNSError`, not an adapter bug). A real
  untested replacement candidate is already on file (the Maricopa County
  AZ note in the Wave 2 survey entry below):
  `maricopa.gov/324/Board-of-Supervisors-Meeting-Information`, a
  CivicPlus AgendaCenter page linking directly to YouTube — but its URL
  shape (`/324/...`, a generic CivicPlus content-module path) doesn't
  obviously match the `/AgendaCenter/...` shape `civicplus.py`'s
  docstring documents, so it needs a real fetch-and-verify pass before
  trusting it, not just wiring it in. Until then,
  `scripts/adapter_canary.py`'s `CANARY_URLS` deliberately excludes
  civicplus (see that file's own comment) rather than pointing at a dead
  or unverified URL.

- **[LATER] New: collect custom-domain examples for popular platforms as they're
  found, into the existing shared sample sheet** ("Watchdog Sample
  meetings," linked in `CLAUDE.md`) — not a code change, a standing
  habit. Motivated directly by the NYC Legistar case above: rather than
  guessing a general "detect by page structure" rule from a single
  custom-domain example, log each new one as it's found (custom domain,
  unusual URL shape, anything that could recur across other cities) and
  only build a general detection rule once several real examples exist
  to generalize from. Applies beyond Legistar — the same principle now
  also shapes the multi-video-detection decision below.
- **[LATER] New platform-vendor gaps found 2026-08-11, via a Wave 2 survey of
  the largest US cities/counties** (see BACKLOG roadmap doc for the full
  survey; full data compiled to an artifact, not saved in-repo). None of
  these were previously tracked here — real gaps, not yet-fixed known
  ones:
  - **Cablecast** (a government-access-TV VOD vendor, unrelated to
    anything currently supported) — confirmed as the actual video host
    for two large cities: **Charlotte, NC** (965k, delegated from its
    Legistar calendar — `charlotte.cablecast.tv/internetchannel/?site=1`)
    and **Detroit, MI** (649k, delegated from *both* its Legistar and
    eScribe calendars simultaneously —
    `detroit-vod.cablecast.tv/CablecastPublicSite/`). The clearest new-
    adapter candidate by population reach of anything found this pass.
    Detroit's eScribe side is also worth checking for populated captions
    while there — no eScribe example anywhere has one confirmed yet.
    **Update 2026-08-12**: `CablecastAssetFinder` is now built (see
    `BACKLOG_DONE.md`) and live for both Charlotte and Detroit, including
    real `vodTranscripts` extraction — see `BACKLOG_DONE.md`'s "Cablecast
    real transcript extraction" entry for the full build.
  - ~~**IQM2** — a Granicus-family product with a distinct UI/URL shape
    from the classic ViewPublisher/MediaPlayer this app already parses.
    Confirmed on Atlanta, GA and Santa Clara County, CA; real video-embed
    shape unconfirmed~~ **Built 2026-08-14 — `app/platforms/iqm2.py`, full
    detail in `BACKLOG_DONE.md`.** Confirmed live: video delegates to a
    real Granicus HLS URL sitting in a plain HTML comment, and real
    per-item timestamped agenda data (procedural entries plus full
    ordinance/resolution text) comes from the same per-meeting page in
    "AgendaOutline" mode.

    ~~**Santa Clara County's own video-population gap**~~ **Resolved
    2026-08-14, no code change needed — it really was body-type-dependent,
    the first hypothesis, not a second per-instance limitation.** Checked
    a real, clearly-past **Board of Supervisors** meeting specifically
    (`Detail_Meeting.aspx?ID=17601`, Aug 11 2026 Regular Meeting) that the
    earlier smaller-committee sample hadn't covered: the already-shipped
    adapter resolves it correctly with zero changes — real title/date/
    jurisdiction, a real playable Granicus HLS URL (same CloudFront
    403-without-a-real-UA / 200-with-one pattern as Atlanta, confirmed via
    direct `curl`), and 72 real timestamped agenda items. So SCC's flagship
    body works exactly like Atlanta's; the earlier gap was real but
    narrower than it looked — smaller commissions/committees on this
    instance apparently don't always get video attached, not a structural
    problem with this adapter or this customer's site.
  - ~~**CivicWeb** (iCompass, a Diligent brand) — confirmed as **Dallas
    County, TX**'s (2.6M) meeting-video host; page is JS-rendered, real
    embed shape unconfirmed~~ **Stale — this was actually built the next
    day, 2026-08-12: `app/platforms/civicweb.py` exists, confirmed live
    against this exact Dallas County instance, and has jurisdiction
    enrichment wired in (see `BACKLOG_DONE.md`). This bullet was never
    struck when that shipped. Re-verified live again 2026-08-13 (via a
    different, fresh Dallas County meeting, `Id=2126`) while researching
    IQM2/CivicWeb for other coverage gaps — `/api/videolink/{id}` and
    `/Services/MeetingsService.svc/meetings/{id}/meetingData` are both
    still plain, unauthenticated JSON, no regression.**
  - ~~**A new, unified Granicus product** (`webcontent.granicusops.com`)
    — possible forward-compat risk to the existing Granicus/Legistar
    adapters~~ **Re-checked live 2026-08-12: real risk to the video path
    not reproduced on either sample city, and `webcontent.granicusops.com`
    itself turns out to be a document CDN, not a video-player product.**
    Followed both cities' real, current Legistar video links end-to-end:
    Fresno's `ID1=2161`/`2162` and Colorado Springs's `ID1=2664`/`2662`/
    `2656` (the only video-linked meetings on each city's current calendar
    window) all still redirect cleanly through `Video.aspx?Mode=Granicus`
    → `MediaPlayer.php` → the classic `{city}.granicus.com/player/clip/
    {id}` shape `granicus.py` already fully supports — no
    `webcontent.granicusops.com` in the chain on either city, today.
    Separately confirmed what `webcontent.granicusops.com` actually is:
    `curl`ing it directly returns a raw S3 `AccessDenied` XML body (i.e.
    it's an S3-backed static-file host), and every real URL under it found
    via search is a per-customer **PDF document** (`/content/{customer}/
    *.pdf` — eComments user guides, virtual-meeting-attendance
    instructions), not a video page. So this looks like Granicus's
    existing document/PDF CDN, not a new video-player product migrating
    existing customers — the original 2026-08-11 survey most likely
    encountered it via an agenda/document link on these cities' calendars,
    not the video path, so the "cities this app already resolves could
    start silently failing" risk doesn't hold up on what's actually
    reachable today. Not fully closed (a genuinely different Granicus
    video product, e.g. the separately-observed `{city}-prod.civica.
    granicusops.com` pattern seen on Sunnyvale/Bellflower via search but
    not confirmed live against real video, could still exist and could
    still be a real migration risk) — but no longer treated as an
    active, unaddressed threat to Fresno/Colorado Springs specifically.
  - **A "decoupled transcript service" pattern** — a real transcript
    hosted entirely separately from the video, cross-referenced by
    meeting rather than embedded on the same page — found independently
    twice: **Tampa, FL**'s own "CTTV" webapp
    (`apps.tampagov.net/cttv_cc_webapp/`, real structured per-meeting
    transcripts; a third-party mirror at `meetings.tampamonitor.com`
    already builds a synced, clickable version worth studying as a
    reference implementation) and a "Transcript Room" service
    (`transcriptroom.org`) that **Philadelphia**'s Legistar committee-
    hearing pages link out to. Not a vendor to build one adapter for —
    a shape worth keeping in mind if either city (or another one like
    them) becomes a real adapter target.
  - **Maricopa County, AZ — a real correction to a standing assumption**:
    `maricopa.legistar.com` is **not** the county's Board of Supervisors
    system — live navigation confirms it's actually the small **City of
    Maricopa**'s calendar (title "City of Maricopa - Calendar", no Board
    of Supervisors content at all). The county's real system is a
    CivicPlus AgendaCenter (`maricopa.gov/324/Board-of-Supervisors-
    Meeting-Information`) linking directly to YouTube. If anything here
    special-cases Maricopa as Legistar, it's wrong.
  - **Tarrant County, TX** (2.1M) — confirmed migrated off Granicus to a
    direct YouTube channel; the old `tarrantcounty.granicus.com` archive
    is explicitly marked "(NOT IN USE)" on the site itself. A real
    platform-migration case, same shape as Long Beach's move off
    Legistar→Granicus to a custom "OneMeeting"→Swagit setup and Santa
    Clara County's PrimeGov-then-back-to-IQM2 flip — worth remembering
    that a city/county's platform isn't assumed stable once confirmed
    once.
  - **Riverside County, CA** (2.5M) — `rivco*.org` domains return a
    plain HTTP 403 (Cloudflare/WAF) to non-browser fetches, the same
    class of problem `headless_browser.py` was already built to solve
    for Minneapolis LIMS and Salt Lake City meeting recaps. Likely just
    needs the existing solution pointed at a new domain rather than new
    engineering, but unconfirmed — the in-session browser tool was also
    down for this check.
  - **Broward County, FL** — a real, confirmed **positive** two-tier
    Granicus captions example (`broward.granicus.com/ViewPublisher.php?
    view_id=15`): a live "CC" toggle plus a separate on-demand
    "enhanced/easier to read" captions link under a "Captioned" column.
    Worth checking against `granicus.py`'s existing caption-detection
    logic directly, since most other Granicus instances checked this
    pass showed no caption UI at all.

- **[LATER] Tarrant County, TX's own "Agenda Management System"
  (`agendamgmtprod.tarrantcountytx.gov`) — new platform, not supported
  at all today, user-reported 2026-08-13 with a real example**:
  [agendamgmtprod.tarrantcountytx.gov/Meetings/GetHTMLAgenda?meetingId=&dataSource=&id=21849bbe-d099-4637-1560-08ddc611a5e2](https://agendamgmtprod.tarrantcountytx.gov/Meetings/GetHTMLAgenda?meetingId=&dataSource=&id=21849bbe-d099-4637-1560-08ddc611a5e2)
  ("Commissioners Court," "TUESDAY, AUGUST 19, 2025 - 10:00 AM"). A
  custom ASP.NET/IIS agenda system (`X-Powered-By: ASP.NET`, real
  cookies set), designed to be iframed into `tarrantcountytx.gov` (its
  `Content-Security-Policy: frame-ancestors` and `X-Frame-Options` both
  only allow that origin), not a Hyland/CivicClerk/Granicus-family
  product — a genuinely new vendor. **Confirmed live in prod
  ([redtaperecordings.com](https://redtaperecordings.com)) that
  `generic_fallback.py` currently finds neither video nor agenda here**
  even though, per direct `curl` (409KB of real static HTML, no JS
  needed), both are genuinely present and unusually rich:

  1. **Video — a real root cause, not a missing feature.** The user's
     "floating picture-in-picture" video is a real YouTube embed, but
     built dynamically via the IFrame Player API rather than a plain
     `youtube.com/watch|embed/...` URL anywhere in the HTML: the only
     literal `youtube.com` string on the page is
     `<script src="https://www.youtube.com/iframe_api"></script>` (the
     API loader itself), and the actual video id sits in a bare JS
     assignment, `const videoId = 'Awrb74sMXyM';`, with no surrounding
     URL at all. `youtube.py`'s `_VIDEO_ID_RE` — the same regex
     `generic_fallback.py` calls via `YouTubeAssetFinder.extract_video_id()`
     — only matches an id immediately preceded by `youtube.com/(watch?v=|
     embed/|shorts/|live/)` or `youtu.be/`, so this shape structurally
     can't match today. A second, narrower pattern for a bare
     `videoId\s*=\s*['"]([A-Za-z0-9_-]{11})['"]`-style assignment would
     catch this specific case, but only one example exists so far — per
     this repo's "don't fix without a confirmed example, and don't
     over-generalize from one" convention, worth watching for a second
     Tarrant-style page (same county, a different meeting id) or another
     jurisdiction using this exact embedding pattern before writing a
     regex against it.
  2. **Metadata — genuinely excellent, and currently thrown away
     entirely.** Real, clean, static text: `<h1>Tarrant County</h1>`,
     `<h1>Commissioners Court</h1>`, and `<h4>TUESDAY, AUGUST 19, 2025 -
     10:00 AM` sit right at the top of the page. None of
     `generic_fallback.py`'s existing metadata backfill applies here —
     the CRRMA-derived logic
     (`_backfill_metadata_from_page`/`_TITLE_TAG_PIPE_RE`) only reads the
     `<title>` tag, and this page's `<title>` is a generic, non-specific
     "Commissioners Court - Archived Agendas and Videos" (no date, same
     for every meeting on this instance) — the real per-meeting signal is
     in `<h1>`/`<h4>` text instead. A second real static-text shape this
     backfill doesn't yet handle, same category as the Sebastopol,
     CA `" - "`-separated-`<title>` gap logged above, but a different
     concrete shape (heading text, not `<title>`) — reinforces that a
     single hardcoded pattern won't keep up and some kind of broader
     "plausible heading/title text" heuristic is worth prioritizing
     (echoes the user's own "Maybe: {result}" idea noted earlier in this
     file).
  3. **Agenda — the page doesn't link to an agenda, it *is* the full
     rendered agenda** (`GetHTMLAgenda` is a literal, accurate name):
     structured `class="accordion-item"` blocks with per-item labels
     (`class="itemLabelTab1 numberWithIndent..."`) run the whole length
     of the page — real structured agenda content, not a PDF link.
     `_find_agenda_link()`'s "any `<a>` tag whose text/href contains
     'agenda'" approach can't find this by design (there's no such
     `<a>` — confirmed via grep, zero matches), which is why the prod
     result shows "no agenda found" despite the richest agenda content
     seen in any generic-fallback case so far. This is closer to a real
     `agenda_items` extraction opportunity (parsing the accordion
     structure directly, LIMS-style) than anything `_find_agenda_link()`
     was designed to do.

  Taken together — a genuinely new vendor, real video, unusually strong
  structured metadata and agenda content, all currently invisible to the
  generic fallback for three separate, specific reasons — this reads as
  a real dedicated-adapter candidate (`app/platforms/tarrant_agenda.py`
  or similar), same shape as the Chicago ELMS entry above, rather than
  three independent fallback patches. Not started this pass — logged per
  this repo's "new bugs/gaps found while working go in BACKLOG.md"
  convention; needs a second real Tarrant County meeting id (or another
  jurisdiction on the same ASP.NET agenda-management product, if one
  turns up) before over-generalizing any of the three fixes above from
  a single example.

  **Update 2026-08-14: pieces (1) and (2) are now handled by the
  generic-fallback rebuild — full detail in `BACKLOG_DONE.md`.**
  Live-verified: the bare `videoId` assignment resolves to the real
  YouTube video (gated on the page's own iframe_api loader — the
  corroboration that made shipping on this one example acceptable), and
  title/date come from the h1 assembly + heading-date extractors when
  YouTube's own metadata is blocked. **Still open**: (3), parsing the
  accordion agenda structure into real `agenda_items` — that's the
  dedicated-adapter part, still gated on a second real example per the
  paragraph above — **and, re-confirmed live by the user this same day,
  jurisdiction specifically is still never set**, even though the
  h1-assembled title text ("Tarrant County Commissioners Court") already
  contains it in full. The title/jurisdiction extractors here fill
  `resolved.title` only, never split any of it back out into
  `resolved.jurisdiction`. **A second, independent real signal the user
  also pointed out**: the YouTube video's own channel name is a plain,
  unauthenticated, no-yt-dlp-needed way to get at the same answer —
  confirmed live via the public oEmbed endpoint
  (`https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=
  {id}&format=json`, no API key, not subject to the yt-dlp/Render-IP
  blocking documented elsewhere in this file) returning real
  `"author_name":"TarrantCountyTX"` for this exact video. Tempting as a
  generic fallback signal, but needs real care, not a blind reuse: this
  file already has a documented, fixed bug class
  (`generic_fallback.py`'s YouTube-embed branch entry, above) for
  exactly "jurisdiction set unconditionally from a YouTube
  channel/uploader name" being wrong in general (a channel name isn't
  always a clean jurisdiction string) — any use of oEmbed's `author_name`
  here should probably be a corroborating signal alongside the page's own
  h1 text, not a standalone source, and only after a second real example
  confirms the channel-name-to-jurisdiction mapping is reliable beyond
  this one (admittedly very clean, "TarrantCountyTX" → "Tarrant County,
  TX") case.

- **[LATER] Residuals from the 2026-08-14 generic-fallback rebuild** (the build
  itself is in `BACKLOG_DONE.md`; these are the real leftovers it
  deliberately did not attempt):
  - **Orange County FL (`netapps.ocfl.net/Mod/meetings/1/2069`) —
    multi-part meetings get only their first part.** Found by
    classifying all 223 archived pages' source URLs: the real page is a
    video.js playlist of 8 mp4 parts (AA–HH), each with its own real
    .vtt captions. The rebuilt fallback deterministically picks part AA
    (live-verified: real video + 1,098 caption segments — the archived
    page had been completely empty, an ingest-time failure predating the
    modern-UA fix). Surfacing the *other* parts needs a real multi-part
    UI/model decision, not a scan fix — no other multi-part example
    confirmed yet. **Also still missing, separate from the video-parts
    gap: jurisdiction.** ~~The user asked 2026-08-14 whether
    `netapps.ocfl.net` could just be marked as Orange County, FL~~
    **Fixed 2026-08-16, wave 1 item 4 — full detail in
    `BACKLOG_DONE.md`.** Confirmed real via that domain's own
    `Content-Security-Policy: frame-ancestors ... orangecountyfl.net`
    header and a `<meta name="keywords" content="...Orange County,
    Archive">` tag; registered in `app/utils/jurisdiction_enrich.py`'s
    `_KNOWN_DOMAINS`. Turned out `generic_fallback.py` needed no new
    `lookup_by_domain()` call after all — `finalize_jurisdiction()`
    (`archive/db/crud.py`'s ingest-time call) already consults the
    registry for every adapter, so the registry entry alone was the
    complete fix, same as `lims.py`'s existing Minneapolis/Dallas County
    precedent.
  - **Palm Beach County FL
    (`discover.pbc.gov/...bcc-meeting-videos.aspx?videoid=...`) — a
    JS-rendered SharePoint page the empty-shell escalation deliberately
    does NOT catch.** Also found via the archived-URL classification
    (its archived page is empty). The shell carries ~6KB of real
    nav/chrome text, so the escalation's near-empty-text gate (tuned to
    Tucson's real 153-char shell) never fires — widening it would make
    an enabled flag pay a ≥4s browser fetch on every ordinary no-video
    page. Needs either its own trigger idea or a dedicated look; note
    the Seattle-style `videoid=` query param. **User's own diagnosis,
    2026-08-14**: this page's `videoid` param made them initially expect
    a multi-video-feed problem like Seattle Channel's — checked directly
    and that's not quite it (this specific SharePoint page has *zero*
    static video/media of any kind, single or multiple; it's the
    empty-shell case above, not a disambiguation case). **But their
    underlying, more important point is real and independent of that**:
    ~~today's "no video found" result still offers "Request Transcript
    from Audio" even when no video was found at all~~ **Fixed
    2026-08-15.** Two real, connected bugs, not one: (1)
    `meeting_page.html`'s `show_transcribe_cta` was computed purely from
    whether an AI transcript already existed, with no `page.video_url`
    check at all, so the button rendered on every genuinely-empty page
    site-wide, not just this one — now gated on `page.video_url` too,
    verified live (no-video test page: button gone; has-video test page:
    button still renders). (2) A sharper, previously-unnoticed version of
    the same bug: `generic_fallback.py`'s own `_NO_VIDEO_FOUND_WARNING`
    text literally said "you can try to request a transcript from the
    audio" — and `render_warnings.py` auto-wraps that exact phrase into a
    clickable `.transcribe-inline-trigger` button, which
    `meeting_page.js:536` fires with **no null guard**
    (`document.getElementById('transcribeToggle').click()`), so simply
    fixing (1) alone would have made that inline warning-text link throw
    a JS error on click instead of silently doing nothing. Fixed by
    rewriting the warning text to no longer promise something impossible
    (confirmed: no other adapter's warning text contains this phrase).

    **Independently re-confirmed 2026-08-14 by the user live-testing the
    actual archived page**, `/m/meeting-890af1` — same misleading CTA
    (now fixed, see above), same underlying page. One small correction to
    "its archived page is
    empty" above, worth noting precisely rather than letting stand
    uncorrected: it isn't actually blank — live-checked and it shows a
    real (if generic, sitewide-not-per-meeting) title, "BCC Meeting
    Videos," pulled from the page's own `<h1 id="pageTitle"
    class="ms-core-pageTitle">` via the rebuild's h1-assembly extractor,
    plus a real (if also generic) agenda link to
    `discover.pbc.gov/countycommissioners/Pages/Agenda.aspx`. So the h1
    extractor *is* doing something useful here — it's just SharePoint's
    one static, page-wide heading, not this specific meeting's real
    title/date/jurisdiction, which per the SharePoint list-view markup
    confirmed in this file's own residual note only exists client-side.
    Doesn't change the real conclusion (still needs its own headless
    trigger idea), just corrects the "empty" description.
  - ~~**Video-only best-effort results are never archived**~~ **Stale —
    corrected 2026-08-21 (WO-21).** This entry claimed the push gate was
    `segments or agenda_items or agenda_link` and had been "deliberately
    not widened." Both halves were out of date: PR #204 (commit
    `7975288`, 2026-08-19, "Fix Archive-push gate to include video_url")
    widened it, and `app/main.py:686` reads
    `if result.segments or result.agenda_items or result.agenda_link or
    result.video_url:` today. The original example — a Tarrant resolve on
    Render where yt-dlp is blocked (no segments) and the page has no
    agenda `<a>` — now produces a page that *is* archived on the strength
    of its video alone. Left here rather than deleted because this exact
    entry is a confirmed instance of the doc-drift the "App-wide audit"
    entry flags, and because the widened gate is the direct upstream
    cause of the trust gap WO-21 then had to close: more best-effort
    results reaching the Archive is precisely what made an unverified
    page's exposure (public page, sitemap, and as of PR #266 an automatic
    social announcement) worth gating on provenance.
  - **Backstop expansion candidates**: `scan_page_for_video_evidence()`
    is wired into eScribe only. Each further adapter opt-in needs its
    own real no-video example plus a wrong-video risk check (Cablecast's
    related-shows carousel is the confirmed shape that must never get a
    blanket second pass).
  - **Unconfirmed-shape extensions awaiting a real example** (commented
    as such in code): `youtube-nocookie.com` embeds and HTML-escaped
    `&amp;v=` watch URLs (pure URL-shape variants, shipped), and the
    curated-pointer host list (Vimeo only until another unsupported
    video host shows up on a real page).
  - **A live check 2026-08-14 of three already-archived pages
    (`/m/meeting-7ac1da` = OCFL, `/m/meeting-38ca49` = Sacramento,
    `/m/meeting-1e9bac` = Maricopa `id=4694`, the same meeting already
    logged above) still shows pre-rebuild behavior** (Untitled/no video,
    despite this file's own notes above saying those exact gaps are
    fixed) — expected, not a regression: this rebuild's own entry in
    `BACKLOG_DONE.md` says existing archived pages were deliberately
    **not** re-resolved ("forward-looking fixes only"), and the "stale
    archived transcripts have no automated refresh path" gap already
    logged elsewhere in this file (no on-demand re-resolve short of the
    passive 30-day `ARCHIVE_RECHECK_AFTER` cycle or the token-gated
    admin endpoint) is exactly why. Also newly observed on the
    Sacramento page specifically: its title renders as "Board Of
    Supervisors Board Of Supervisors Meeting." **Resolved 2026-08-15 —
    checked with a live re-resolve of the real URL
    (`agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeeting?doctype=1&id=10231`),
    not the stale cached page: it reproduces identically today
    (`title="Board Of Supervisors Board Of Supervisors Meeting"`).** Not
    a stale-cache artifact — this is real text straight from the source
    page's own agenda-link `title` attribute (`_AGENDA_LINK_TITLE_RE`),
    matching CLAUDE.md's own already-documented reasoning for this exact
    shape: plausibly a real `"{meeting type} {body name} MEETING"`
    template that happens to coincide here, not a confirmed universal
    artifact worth guessing a general dedup rule from a single example.
    **Deliberately not a bug to fix** — no code change made.

- **[LATER] Vimeo's real-world prevalence among small local governments
  is still an extrapolation, not a count.** The adapter got built anyway
  (WO-29, 2026-08-21, `BACKLOG_DONE.md`), so this is now a question of how
  much it is worth rather than whether to build it: 6/200 Vimeo
  fingerprint hits in the dotgov coverage-map sample, extrapolated to
  roughly 290 jurisdictions nationally, still unreplaced by a real number
  from the full ~9,766-row run. **The one part of the original sizing
  question that came back "no": Vimeo's oEmbed does NOT expose captions**
  (it returns title/duration/upload_date/author only), and nothing else
  reachable by a plain HTTP client does either -- see the Vimeo
  captions/audio entry under **Platform & jurisdiction coverage** for the
  real wall and what might get past it.

- **[LATER] Direct-to-YouTube may be the single largest video source among
  small US local governments, ahead of Granicus — a resolver-prioritization
  signal, not a code change by itself (2026-08-18).** Same 200-row dotgov
  coverage-map checkpoint: `youtu.be` (11) + `youtube.com/embed` (7) = 18
  hits, against Granicus's 14 — YouTube already ahead of the single most
  common dedicated meeting-video vendor, in a sample skewed toward small
  rural counties (Alabama/Alaska-heavy — the checkpoint's alphabetical
  input ordering, since fixed for the full run; see this session's
  `DOTGOV_DISCOVERY.md` update). If the full run confirms this nationally,
  it means this project's own "Tier 2" platforms (those that delegate to
  YouTube rather than hosting video themselves — see `CDX_QUERIES.md`'s
  PrimeGov/CivicWeb sections, which already use this term) may be the
  *primary* channel for small-government video, not a fallback behind the
  dedicated-vendor platforms this project has prioritized adapter work for
  so far. Worth weighing against `CDX_QUERIES.md`'s existing CDX
  enumeration backlog once the full run's real number lands, not acted on
  from this sample alone.

- **[LATER] Hallucinated-transcript detection (`detect_hallucination_warnings()`,
  added 2026-08-16 alongside the phase-cancellation fix — see
  [BACKLOG_DONE.md](BACKLOG_DONE.md)'s matching "Bugs" entry) had two
  real, known limits.** (1) **Already-live exposure unaudited**: ~~unlike
  the seam-duplication bug's `GET /internal/transcription/completed-
  multichunk`~~ **built and run for real 2026-08-17** — see
  [BACKLOG_DONE.md](BACKLOG_DONE.md)'s matching entry for the new `GET
  /internal/transcription/hallucination-candidates` endpoint and its real
  5-candidate result. (2) **Doesn't catch semantic-nonsense
  hallucination**, still open: the three structural signals
  (repetition-run ratio, long character runs, non-Latin-script ratio)
  deliberately don't try to catch *coherent-looking but false* text —
  confirmed by a real, directly-quoted example from this same
  investigation (`"Did you ever see your mom will never wake up at the
  bus stop?"`) that the detector correctly does *not* flag (see
  `tests/test_worker_segment_utils.py`'s
  `test_detect_hallucination_warnings_does_not_claim_to_catch_semantic_nonsense`).
  Catching that shape would need a real language-model-judge pass (cost/
  latency tradeoff, not yet designed), not a cheap structural heuristic.

- **[LATER] A *sparse* loop of 5-11 cues is still missed** — the residual
  gap between WO-36's two rules. The tiled rule needs coverage `>= 0.9`,
  the absolute rule needs `>= 12` cues, so e.g. 8 repeats of `"Thank you."`
  spread across four minutes of dead air with real silence between them
  falls through both. Deliberate, not an oversight: the 304-transcript
  corpus had no example of that shape, and closing it would mean lowering
  the absolute threshold into the 8-9 range where real decoder stutters
  live (Blackford County IN's `"mo."` x8, Creve Coeur MO's `"it's mine."`
  x9 — both real speech, both must stay clean). Worth revisiting only with
  a real example in hand; a cadence-regularity signal (the real loops sit
  at exact 1.000/2.000/10.000/30.000s intervals, real speech doesn't) is
  the most promising next discriminator if one turns up. See
  [BACKLOG_DONE.md](BACKLOG_DONE.md)'s WO-36 entry for the measurements.
  The separate semantic-nonsense limit is unchanged and still tracked in
  its own `[LATER]` entry above.

## Parked deliberately — allowed back `[PARK]`

Parked here by the user during the jurisdiction/title extraction planning
conversation (see `JURISDICTION_METADATA_PLAN.md` for what *was*
green-lit). Not rejected — explicitly allowed to return.

- **[IMPROVEMENT-ROUND] School-district / special-entity jurisdiction lookup.** School
  districts don't conform to city/county boundaries — they're their own
  geography, so the Census places/counties tables (and the whole
  known-jurisdiction validation idea) structurally can't cover them. One
  real lead for whenever this comes back: the same Census Gazetteer
  program the existing `jurisdiction_data/` tables are built from *also*
  publishes school-district files (unified/elementary/secondary, name +
  state), so districts are tractable with the exact same
  build-script/lookup mechanism later. The 2026-08-15 Swagit batch alone
  surfaced ~10 real district/board-of-education pages, so there's real
  data waiting when this gets picked up.
- **[PARK] MPO / transit-authority / utility-district name table.** No national
  authoritative table exists (unlike cities/counties/districts), so
  these stay validation-exempt indefinitely — "not in table" must stay a
  keep-and-flag outcome, never a rejection, largely because of this
  class. VIA Metropolitan Transit, Broward MPO, ERCOT, Port of
  Galveston, Travis Central Appraisal District are the real examples on
  file from the 2026-08-15 audit.

- **[PARK] [Big, low priority] "Request Transcript from Audio" doesn't work for
  YouTube-hosted meetings.** Confirmed live 2026-08-10: clicking it on a
  YouTube meeting returns "We found a media source but couldn't read it
  — it may be unavailable." Root cause traced precisely, not guessed:
  `app/main.py`'s `check-feasibility` route runs `ffprobe -i
  <result.video_url>` (`app/platforms/media_probe.py`'s
  `probe_duration()`) to measure duration before allowing a job —
  but for YouTube, `result.video_url` is `https://www.youtube.com/
  embed/{video_id}` (`youtube.py`), an HTML iframe-embed *page* for the
  browser player, never a real media file. `ffprobe` can never read
  that, regardless of any blocking — this specific failure would happen
  even from a totally unblocked IP.

  **Real coupling to the still-open YouTube IP-block issue (see
  BACKLOG_DONE.md's "degrade gracefully" entries)**: the actual fix
  isn't just "point ffprobe somewhere else" — YouTube has no direct
  media-file URL by design (same reason playback needs the iframe
  Player API, not `<video>`), so getting a real downloadable stream URL
  requires yt-dlp's own extraction (the same internal pipeline already
  confirmed blocked by YouTube's anti-bot check on Render's IP for
  metadata/captions). Building real stream extraction here without
  first solving that IP block would very likely just trade one failure
  message for the same underlying block under a different one — worth
  confirming which is genuinely true (a totally separate, unblocked
  extraction step, or the same wall) before investing real build time.
  Real options for the underlying block itself (cookies-based auth, a
  PO-token-provider plugin, a proxy) were already surfaced and
  deliberately not attempted, given real cost/maintenance/risk
  tradeoffs none of them have been evaluated against yet.
