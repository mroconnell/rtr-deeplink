# Backlog

Live items only, roughly in priority order. Completed work — including the
investigation detail behind each fix — lives in
[BACKLOG_DONE.md](BACKLOG_DONE.md); items below link back to it for context
where relevant.

## ~25 smaller consolidated city-county governments still need a real domain -- 13 of ~38 already done, see BACKLOG_DONE.md, 2026-08-20/21

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

## Domain guesser matched a same-named US state's real portal instead of the county's -- fixed at the source, 6 wrong rows reverted, 2026-08-21

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

## Real per-tenant/platform gaps found across several of the 50 largest US cities -- from the user's own manual research table, 2026-08-20

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
- **Phoenix, AZ** -- Legistar meeting detail pages
  (`phoenix.legistar.com/MeetingDetail.aspx?ID=...`) always report video
  as "unavailable," but the real video exists on a separate, apparently
  unlinked YouTube channel (confirmed real example: the July 1, 2026
  meeting's actual recording is `https://www.youtube.com/watch?v=srjuXI5vGuw`).
  Given the city's size/prominence, may be worth a hardcoded per-tenant
  YouTube-channel mapping rather than waiting on a general fix.
- **Philadelphia, PA** -- same shape as Phoenix: Legistar reports no
  video; the real recording is on YouTube but not linked from the
  Legistar page.
- **El Paso, TX** (`elpasotexas.gov/videos`) -- each government body gets
  its own Vimeo landing page rather than one consistent embed pattern;
  no adapter attempted yet.
- **Portland, OR** (`portland.gov/council/agenda/...`) -- not supported,
  needs real adapter work against Portland's own agenda-page structure.
- **Tucson, AZ** ("Mayor and Council," Hyland-hosted at
  `tucsonaz.hylandcloud.com`) -- video lives on a separately-hosted
  YouTube channel; audio + minutes are paired by matching filenames on a
  *different* page
  (`tucsonaz.gov/Departments/Clerks/Boards-Committees-Commissions/...?run=pastminutesaudio`),
  not attached to the Hyland agenda item itself.
- **Seattle, WA** (`seattlechannel.org`) -- "Seattle Channel," a custom
  city-run video platform, not yet triaged against any existing adapter.
- **Chicago, IL** (`chicityclerkelms.chicago.gov`) -- custom domain/
  platform shape, not yet triaged.

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
- **Baltimore, MD** -- Legistar; user-confirmed only a handful of
  meetings have video actually attached, most real video is on YouTube
  instead and not linked from Legistar.
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

**Not yet re-checked, may already be fine (worth a quick live verify
before assuming any of these need work):** New York City itself
(`legistar.council.nyc.gov` is the real calendar; this repo's own
Archive currently only has 2 old Viebit clips under a
`councilnyc.viebit.com` tenant that never matched a jurisdiction --
possibly the same class of gap as the Charlotte mis-attribution, not
confirmed).

## [JUST-DO-IT] Some old/archived Granicus clips' `chunklist.m3u8` genuinely times out at Granicus's own origin (real 504, not a rate limit) -- root cause confirmed 2026-08-21, corrects two earlier wrong theories in this same entry

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

## ~~[HIGH PRIORITY] Swagit adapter serves a wrong, bogus video for `/events/{id}` URLs~~

**Fixed 2026-08-21** — root cause found: `/events/{id}` is a genuinely
different Swagit page template from `/videos/{id}`, a *live-event*
stream page (confirmed straight from the template's own dead error-
handler text) with no archived recording linked from it at all. Its two
embedded candidates — a dead, byte-identical-across-every-tenant demo
placeholder and a real per-tenant live-channel stream that 404s once the
meeting's over — are both now detected and declined by
`SwagitAssetFinder` with a specific warning instead of silently served.
`PrimeGov`'s workaround guard was removed too, since the fix covers its
delegation path directly (confirmed live end-to-end). All 5 real tenants
(`petalumaca`, `norwalkca`, `westjordan`, `cambridgema`, `solvangca`)
independently `curl`-verified. Full root-cause writeup, live-fetch
detail, and test coverage in `BACKLOG_DONE.md`'s "Swagit adapter served a
wrong, bogus video for `/events/{id}` URLs" entry.

## ~~[JUST-DO-IT] Granicus adapter doesn't recognize `MediaPlayer.php?event_id=...` URLs~~ **Fixed 2026-08-21** — see `BACKLOG_DONE.md`

Full writeup, root cause (the pages genuinely have no video yet —
`event_id` is a separate, non-interchangeable Granicus id namespace from
`clip_id`, confirmed via PrimeGov's own API showing
`streamCompleted: false` on every real example), the 4 verified cities
(with 2 real subdomain-name corrections: `emeryville.granicus.com` and
`nassaufl.granicus.com`, not the PrimeGov tenant names), and the one
residual gap left open (PrimeGov's own better date/title not threaded
through for this specific sub-case) are all in `BACKLOG_DONE.md`'s
matching entry.

## ~~Running a service from a `.claude/worktrees/` subdirectory silently inherits the shared checkout's `.env`~~ **Fixed 2026-08-21** — see `BACKLOG_DONE.md`

Deliberately fixed with a `CLAUDE.md` warning note rather than a
`load_dotenv()` code change — see `BACKLOG_DONE.md` for the full
reasoning (a code change to `load_dotenv()`'s path resolution risks
affecting how production loads its real env vars, not worth taking on for
what is fundamentally a local-dev footgun).

## Tulare County/Visalia jurisdiction misattribution — not confirmed fixed, no known real hosting domain found

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
further. Even a plausible `tularecounty`-shaped subdomain wouldn't
validate through the existing wordninja-based subdomain validator
regardless of the cross-check fix — `wordninja.split("tularecounty")`
mis-segments to `['tul', 'are', 'county']` rather than
`['tulare', 'county']` (confirmed live), a separate, narrower dictionary
gap in `_validated_label_extract()`.

Next step: find the real originating URL for this misattribution (check
`tularecounty.legistar.com` first, or the original session's own
discovery notes if recoverable) and either (a) confirm the existing
cross-check fix already covers it once the real subdomain is known, or
(b) if the real subdomain is `tularecounty`-shaped, first fix the
wordninja mis-segmentation before the cross-check can engage at all.

## Town Hall Streams: real transcript endpoint still unconfirmed-positive; 88-id Wayback population not yet ingested (2026-08-20)

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

## SuiteOne Media: real, confirmed jurisdiction gap on 2 tenants; unconfirmed CDX leads and PDF-transcript fallback (2026-08-21)

Residual gaps left behind by the new SuiteOne Media (suiteonemedia.com)
adapter build — see `BACKLOG_DONE.md`'s "SuiteOne Media: new platform
adapter built" entry for the full investigation and what was actually
shipped (`app/platforms/suiteone.py`).

- **`stmarysga` (St Marys, GA) and `camaswa` (Camas, WA) can't recover a
  jurisdiction through the shared `jurisdiction_enrich` pipeline at all.**
  wordninja splits "stmarysga" as `['st', 'mary', 'sga']` and "camaswa" as
  `['ca', 'maswa']` — neither's last token is a real 2-letter state code
  (the real trailing state letters get absorbed into a longer non-word
  chunk, "sga"/"maswa", by wordninja's own dictionary-cost minimization),
  so `jurisdiction_enrich.validated_subdomain_extract()` never produces a
  bare name to attach a state to, and both end up `jurisdiction=None`.
  Confirmed by hand that stripping the real trailing state code first
  ("stmarys" / "camas") validates correctly ("St Marys" / "Camas") — so
  the underlying place names are real and resolvable, just not through
  this shared function as it stands today. Fixing this generically (e.g.
  trying a manual last-2-letters-against-known-US-state-codes strip
  before handing the remainder to `validated_label_extract()`, independent
  of whatever wordninja itself produced) would belong in
  `jurisdiction_enrich.py` itself, since other adapters using the same
  glued-slug shape would benefit too — not done here since this repo's
  own convention for this platform was "reuse jurisdiction_enrich
  directly, don't write new jurisdiction-parsing logic."
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

## Stray demo-shaped tables found in `rtr_deeplink_db` during PITR test-restore verification (2026-08-17)

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

## Reliability/ops audit — remaining manual/dashboard checks (2026-08-17)

`AUDIT_EXECUTION_BRIEF.md`'s Phase 1 and Waves 1, 2, 3, 4, and 6 are all
code-complete and merged (full Problem/Do/Fixed detail moved to
`BACKLOG_DONE.md`'s "Reliability/ops audit execution" entry). Only Wave 5
(WO-10, migrations survive deploys) remains real open engineering work,
tracked live in `AUDIT_EXECUTION_BRIEF.md` itself. What's below are small,
no-code, dashboard-or-manual confirmations that were left open across
those waves — grouped into one item instead of scattered as "still open"
footnotes across six waves, so they don't get lost. None block anything
else; do whenever convenient, no particular order.

- **[HUMAN] Sentry: confirm a real raised exception actually appears in the
  dashboard.** `SENTRY_DSN` is live and set on all three services, but
  nobody has forced a real exception and watched it land in Sentry's UI
  — WO-7's own stated acceptance criterion, never run.
- **[HUMAN] `ALERT_WEBHOOK_URL` repo secret** (Slack/Discord incoming webhook,
  shared by all three cron workflows: daily-report, send-search-alerts,
  adapter-canary) — optional, still unset. Without it, a workflow failure
  still surfaces via GitHub's own failed-scheduled-workflow email, so
  this is a nice-to-have, not a real gap.
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
- **[JUST-DO-IT] `rtr-business/BUSINESS_OVERVIEW.md` still says "Not built yet: ...
  saved-search alert emails"** — stale; that feature shipped 2026-08-13
  (PR #30) and runs daily. `README.md`'s own copy of this claim was
  already corrected 2026-08-16. One-line fix whenever anyone's next in
  that file — not done here since business-workspace edits are kept
  separate from code-repo sessions per `CLAUDE.md`.
- **[JUST-DO-IT] The audit's own doc-hygiene rule was never actually added to
  `CLAUDE.md`.** `AUDIT_EXECUTION_BRIEF.md`'s "Docs debt" section
  proposed: "a PR that ships a feature must update every doc that named
  it as unbuilt, and the PR description must list which" — a real,
  reasonable rule (the audit found three of its own eight starting leads
  were wrong because they trusted a stale doc), but it was only ever
  written down as a proposal, never landed as an actual `CLAUDE.md`
  addition. Small, no-code fix whenever anyone's next editing that file.

## Easy-win triage (2026-08-16) — two waves ready to execute

Per direct request: a pass through this whole file to pull out genuinely
easy, low-risk items — root cause and fix direction already established
in the entry itself (not "worth deciding"/open design questions), small
footprint (1-2 files), no new schema/migration/dependency/infra, nothing
touching Clerk auth (documented history of that being unreliable — see
the sign-in-redirect saga referenced in the Archive-roadmap accounts
entry below), not a from-scratch platform adapter build. Each item below
is a pointer to its full write-up elsewhere in this file, not a
duplicate — search this file for the quoted phrase to find the source
entry with all the evidence.

**Both waves shipped 2026-08-16 — full detail in `BACKLOG_DONE.md`'s
"Easy-win triage waves 1 + 2" entry.** All 9 items landed (items 1-5,
2-file copy/data fixes; items 6-9, small self-contained logic fixes),
full suite green throughout. Original numbered list kept below,
struck through, so this section's own history stays legible.

~~**Wave 1 — copy & data only, essentially zero logic risk.** Ship
together as one small PR; none of these touch branching logic.
1. Contact `mailto:` links still show `ryan@` instead of the live
   `ally@redtaperecordings.com`.
2. Transcription rate-limit 429 copy is unfriendly. (The same entry's
   other half — signed-in users bypassing the limit entirely — is real
   but not yet feasible to schedule; see "Left out" below.)
3. README.md wrongly says saved-search alert emails are "Not yet built."
4. One remaining confirmed jurisdiction-registry gap — Orange County, FL.
5. Swagit's `raw_title` carries a literal tab character straight through
   into stored titles.

**Wave 2 — small, self-contained logic fixes.**
6. CivicClerk never falls back when `eventLocation` is completely blank,
   confirmed live on Los Altos Hills, CA.
7. Granicus's `captions.vtt` hard-caps at exactly 36,000 cues with no
   warning, confirmed on 3 independent real customers.
8. Granicus's wordninja subdomain-humanization fallback produces
   confident garbage on acronym subdomains — "S Fw, MD" from `sfwmd`,
   "Psr C 2" from `psrc2`, etc.
9. `/coverage`'s "Every place we've covered" table wants a frozen
   row-number column and sortable headers.~~

**Left out on purpose, not an oversight**: signed-in users bypassing the
transcription rate limit entirely (the other half of item 2's source
entry) — the entry itself flags that slowapi's `@limiter.limit(...)`
applies unconditionally at decoration time with no existing per-request
bypass pattern in this codebase, so the implementation path is
unconfirmed. Worth a short feasibility spike before scheduling it
alongside item 6, which already has a proven fix.

## App-wide audit: industry best practices & resource management — scoped 2026-08-14, for handoff

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
- ~~**CI/CD — no automated test gate.**~~ **Fixed 2026-08-14** (WO-2 of
  `AUDIT_EXECUTION_BRIEF.md`): `.github/workflows/test.yml` runs `pytest`
  + `npm test` on every push to `main` and every PR (pinned to Python
  3.12.3 to match `render.yaml`), and a branch ruleset on `main` requires
  the `test` check to pass, blocks force pushes, and restricts deletions.
  Verified for real (throwaway failing-test PR, confirmed merge actively
  rejected, not just shown red) — see `BACKLOG_DONE.md`'s "Testing
  infrastructure" section for the full entry.
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
- **[NEEDS-AUDIT] Data durability — an unverified unknown, not a confirmed gap.** No
  Postgres backup/point-in-time-recovery policy is documented anywhere
  (`README.md`, `render.yaml`, `BACKLOG.md`) — and `render.yaml` has no
  `databases:` block at all, meaning the real Postgres instances exist
  outside the Blueprint's tracked config. A five-minute check of
  Render's dashboard would resolve this either way; nobody's done it.
- **[NEEDS-AUDIT] Security — one open, self-authored threat model with no built
  mitigations.** The "fake/spoofed government content" threat model
  above (this file's own "Trust & safety" section, written
  2026-08-10) still has nothing beyond a reactive report form and one
  `noindex` tag. Separately: no dependency-vulnerability scanning
  exists (no Dependabot config, nothing like `pip-audit` anywhere in
  CI — which itself doesn't run automatically, see above).
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

## Trust & safety — real gaps, threat-modeled 2026-08-10

Prompted directly by the user asking "should I be worried about prompt
injection or people submitting fake government websites or people
submitting websites that aren't government at all" — a real think-through,
not a hypothetical checklist. Nothing here is built yet; this section
exists to make the actual risk shape visible before deciding what (if
anything) to build against it.

- **[DONE?] Prompt injection: not a live product risk today, because no LLM sits
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
  transcription section below, since *that* risk at least starts from
  real audio); the Archive used as free SEO-boosted hosting for
  unrelated spam/harassment content via `generic_fallback`; reputational/
  trust erosion for the whole site if any of the above became public.

  **What already exists as a real, if reactive, mitigation**: the
  "Report a problem with this meeting" flow (`ProblemReport`,
  `app/db/models.py`) already gives any third party a path to flag a
  suspicious page — genuinely built, not aspirational, just reactive
  (after publication) rather than preventive.

  **Mitigation options worth weighing, not yet decided or built (except
  the first, built 2026-08-11 — see BACKLOG_DONE.md):**
  - ~~**noindex generic_fallback/`best_effort` pages by default**~~ Built
    2026-08-11: `archive/templates/meeting_page.html`'s meta block now
    renders `<meta name="robots" content="noindex">` whenever
    `page.platform == "unknown"` (the exact string `generic_fallback.py`
    registers under). The narrowest, cheapest mitigation on this list —
    doesn't block anything, just stops amplifying the least-verified
    content until a human's looked at it. The rest of this section's
    threat model (fake-jurisdiction risk, curated-list idea, trust tiers)
    is still open.
  - **Manual review before a brand-new jurisdiction goes live/indexed**
    — especially for `generic_fallback`/`best_effort` results. Real cost:
    turns part of the pipeline from fully automatic into something
    needing a human in the loop, at least for first-time jurisdictions.
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

## Bugs

- **[NEEDS-AUDIT] Worker can produce a chunk `extract_chunk_audio()` calls
  successful that's actually truncated/corrupt — surfaced via Sentry issue
  PYTHON-FASTAPI-R, 2026-08-19 15:57:32 UTC, promoted from
  `CLAUDE_INBOX_TRIAGE.md`.** Real error: `InvalidDataError: [Errno
  1094995529] Invalid data found when processing input:
  '/tmp/rtr_transcribe_hwou97hq/chunk_1.mp3'`, `server_name =
  srv-d9rluvqfngtc73dmrbug` (the transcription worker), `handled = yes`,
  app log "Job 287: transcription failed for chunk 2/21 (will retry on
  next poll)". Root cause traced to real code: `worker/main.py`'s
  per-chunk loop (~lines 237-243) only guards `extract_chunk_audio()`'s
  ffmpeg call via return-value truthiness — this occurrence got past that
  check (ffmpeg reported success) but the resulting file was invalid when
  `transcription_engine.py`'s `_transcribe_sync()` tried to decode it via
  PyAV (`av.container.core.open`), landing in the broader `except
  Exception` at worker/main.py:250-256 (logs + retries next poll, hence
  `handled = yes`, not a crash). **Impact**: caught/retried automatically,
  not user-visible by itself; whether job 287's retry for chunk 2/21
  actually succeeded is unconfirmed (no DB access from the triage
  Routine). First occurrence of this exact signature as of 2026-08-19 —
  may be a one-off transient (likely an interrupted read from the source
  media stream during ffmpeg extraction), not yet confirmed as recurring.
  **Fix, if it recurs**: have `extract_chunk_audio()` sanity-check its own
  output (non-zero size, or a quick `ffprobe`) rather than trusting
  ffmpeg's exit code alone, so a corrupt chunk retries immediately instead
  of failing over to the whisper-decode step first. Not fixed yet —
  logged as a real, traced gap, not designed/built this pass.

- ~~**[JUST-DO-IT] Jurisdiction-bleed, confirmed cross-platform (Granicus
  AND eScribe)**~~ **Fixed 2026-08-17 — Canadian city/town data table
  (5,028 real Statistics Canada rows) + a Title-Case/ALL-CAPS word-run
  signal in `_looks_like_bleed()`. Full root-cause detail, the real
  confirmed table, and both fixes' verification are in
  `BACKLOG_DONE.md`.** Real, honestly-flagged residual gaps left open by
  that fix, not silently closed — see the three entries directly below:

- ~~**[JUST-DO-IT] Jurisdiction-bleed fix can turn an honestly-garbled value
  into a confidently WRONG one, when the bled text happens to contain a
  different, unrelated but real city name — confirmed live 2026-08-17
  with 2 real eScribe examples, newly surfaced by the Canadian-data fix
  above (`BACKLOG_DONE.md`).**~~ **Fixed 2026-08-21 — see `BACKLOG_DONE.md`'s
  "jurisdiction-bleed, gate-blindness recovery" entry.** `finalize_jurisdiction()`
  now cross-checks its own trim-repair result against a validated
  subdomain-derived candidate (the mitigation direction this entry
  originally identified but hadn't verified), preferring the subdomain's
  identity when they disagree.

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
  fixed and 12 of 16 examples resolved 2026-08-21 (see BACKLOG_DONE.md's
  matching entry for the full investigation) — two residuals still
  open, and a NEW real bug found 2026-08-21 running the GET audit that
  BLOCKS just running the backfill as originally planned.** (1)
  **Backfill audit run against production 2026-08-21 — found far more
  candidates than expected, some of them genuinely wrong, so the write
  step (`POST .../backfill-apply?dry_run=false`) was deliberately NOT
  run.** `GET /internal/jurisdiction/bleed-backfill-candidates` returned
  635 candidates (not the ~13 expected), of which 552 are confidence-field-
  only changes (identical jurisdiction text, `current_confidence: None`
  → a real confidence value — likely harmless, a one-time backfill of a
  field that didn't exist yet when those rows were first written) and 83
  are real jurisdiction-text changes. Of those 83, 68 are simple, clearly-
  safe state-suffix appends (e.g. "Dublin" → "Dublin, CA", "Airdrie" →
  "Airdrie, AB") — but the remaining 15 include **at least two confirmed-
  wrong repairs that would corrupt already-correct live pages**: `page_id
  250` ("Alameda County, CA" → **"Bart, CA"** — a BART board-of-directors
  meeting; "Bart" is coincidentally a real tiny Census place name
  unrelated to this meeting, an acronym/place-name collision, not a
  repair) and `page_id 1108` ("Modesto, CA" → **"Agenda, CA"** — "Agenda"
  is a real small Kansas town name that happens to collide with the
  literal word "agenda" appearing somewhere in the source text). Also
  suspect in the same 15, not yet independently confirmed either way:
  `page_id 279` ("City of New Port Richey, FL" → "Clearwater, FL" — two
  distinct real FL cities, looks like a wrong reassignment, not a
  repair), plus several consolidated-city-county cases that silently
  drop the state suffix instead of adding one (`Jefferson County` →
  `Louisville`, `Davidson County` → `Nashville`, `Louisville / Jefferson
  County Metro` → `Louisville`) inconsistent with `Nashville-Davidson
  County, TN` → `Nashville, TN` right above them getting a proper suffix.
  **Real, newly-confirmed gap**: `finalize_jurisdiction()`'s repair path
  validates a candidate purely against the Census/StatsCan place table
  with no guard against a short, common, or acronym-shaped string
  coincidentally matching an unrelated real small place — this is a
  distinct failure mode from anything the original jurisdiction-bleed
  investigations found, and needs its own fix (something like: require a
  minimum edit-distance/containment relationship between the current and
  candidate values, or exclude single common-English-word matches) before
  this backfill can be safely applied in bulk. **Until that guard exists,
  do NOT run `backfill-apply?dry_run=false` against the full candidate
  set** — at most, the 68 confirmed-safe simple-suffix-append rows could
  be applied individually/filtered, but the endpoint has no per-ID filter
  today, so even that needs a small endpoint change first. (2) **3 of the
  original 16 examples (Ashland, Milton, San Jose) still have no
  confirmed real state** — each was checked live (their real source page
  and, where relevant, its channel-root page) and none carries reliable
  state-identifying text; Ashland sits on a shared/generic TelVue player
  domain, San Jose's Granicus pages are silent on state entirely, and
  Milton is genuinely uncertain between FL and eScribe's real Ontario,
  Canada customer base. Needs either a positive text match found some
  other way, or a second confirmed example before a domain registry
  entry can be added without guessing.

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

- ~~**[HUMAN] Schema-migration deploy ordering has now caused a real,
  sitewide Archive outage (2026-08-17)** — the ask was a *mechanism*
  making "model references a column prod doesn't have" impossible to
  deploy.~~ **Built for the Archive the same evening (WO-10, PR pending
  merge as of this edit — full detail in `BACKLOG_DONE.md`'s "WO-10"
  entry)**: `render.yaml` `preDeployCommand: cd archive && alembic
  upgrade head` (schema lands before the code goes live; a failing
  migration cancels the deploy and keeps the old build), `archive/db/
  engine.py`'s `create_all()` a no-op on Postgres (Alembic is the only
  writer to the prod schema), and CI `alembic check` on every PR (a model
  edit without a migration fails before merge). Precondition verified
  before automating: archive `alembic_version` == head after Ryan's two
  `upgrade head` runs that day, and `alembic check` against a fresh
  `upgrade head` DB reported no missing model tables/columns.

  **What's still open — the resolver half, Ryan-gated:** `app/`'s Alembic
  history (`app/alembic/`, 2 revisions) has never been stamped in
  production, so the same `preDeployCommand` there would fail on its
  first run (it would try the baseline `CREATE TABLE`s against tables
  that already exist — the brief's "step 3 before step 2" warning). One
  shell step unlocks it, on the **`rtr-deeplink`** (resolver) service's
  Render shell, not the archive's: `cd app && alembic current` (expect
  empty), confirm the real columns match head (`GET /admin/stats`
  returning `pending_archive_pushes` cleanly is the documented check —
  see `app/alembic/README.md`), then `cd app && alembic stamp head`. Then
  a small PR: add `preDeployCommand: cd app && alembic upgrade head` to
  the `rtr-deeplink` service (a comment marks the exact spot in
  `render.yaml`), gate `app/db/engine.py`'s `create_all()` to
  non-Postgres the way archive's is, and extend the CI `alembic check`
  step to `app/`. Until then a new *resolver* table still appears via
  `create_all()` and an altered resolver table still needs a hand-run
  migration — the resolver has never had a schema incident, which is why
  it's the half that could wait. Also still true: `scripts/
  backfill_search_corpus.py`-style one-time backfills remain manual —
  prefer generated columns (the `search_tsv` pattern) so there's nothing
  to backfill.

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

- ~~**[JUST-DO-IT] Every route on both services returns 405 to HTTP `HEAD`
  requests — site-wide, app-level, confirmed live and reproduced locally
  2026-08-17.**~~ **Fixed 2026-08-21** — see `BACKLOG_DONE.md`. (Turned
  out to already be fixed in code by PR #138, 2026-08-17, the same day
  this entry was written — this entry itself was the stale doc-drift;
  the 2026-08-21 pass confirmed the fix live with `curl -I` against both
  services and added `tests/test_head_requests.py` coverage, which
  already existed too. Full detail in `BACKLOG_DONE.md`.)

- ~~**[JUST-DO-IT] Archive reverse-proxy streaming has no error handling
  once the response body starts streaming — a cut-short upstream
  connection raises an unhandled exception instead of failing cleanly,
  confirmed live in code 2026-08-21, promoted from
  `CLAUDE_INBOX_TRIAGE.md`'s 2026-08-19 run.**~~ **Fixed 2026-08-21** —
  see `BACKLOG_DONE.md`.

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

- **[JUST-DO-IT] `is_likely_garbled()` only samples the transcript's first 4000
  characters, so a transcript that starts clean and degrades later is
  invisible to it — found 2026-08-16 via a DB skim for transcript-quality
  examples, root cause confirmed by reading the source directly.** Real
  case: Cincinnati OH Budget & Finance Committee, 2023-02-13
  (`cincinnati-oh-2023-02-13-budget-and-finance-committee-on-2023-02-13-1-00-pm`,
  Granicus). The stored transcript (98,449 chars total) is clean prose
  through roughly char 5,500, then degrades into raw binary-looking
  garbage (`*eqt*eqt*eq*eqt*eqt*eqaeq(T*zq4m fs~d= 8 yx2z2"BCMvf;jv6...`)
  for a long stretch after that. `is_likely_garbled()`
  ([app/utils/vtt_parser.py:462](app/utils/vtt_parser.py#L462)) takes
  `sample = " ".join(...)[:4000]` — a hardcoded prefix, not a spread
  sample across the transcript — so this specific row's corruption starts
  just past the sampling window and the heuristic never sees it.
  `transcript_warnings` on this row is empty, consistent with the
  heuristic silently passing it. Calibrated originally against Alexandria
  VA (garbled from very early on, see `BACKLOG_DONE.md`'s 2026-08-06
  entry) — that case likely happened to be garbled within the first 4000
  chars, which is probably why this gap wasn't caught at the time.
  Possible fix direction (untested): sample from multiple offsets across
  the transcript, not just the start — but worth checking whether other
  archived rows have the same "clean prefix, garbled tail" shape before
  picking a specific sampling strategy.

- **[JUST-DO-IT] `app/utils/vtt_parser.py`'s `parse_vtt()` has (at least) two separate
  real content-corruption gaps, plus one existing fix that's wired to the
  wrong adapters — all found 2026-08-16 via the same DB skim, all
  root-caused by reading the parser source directly against real stored
  output (not yet independently re-fetched from the live source VTT
  byte-for-byte, so treat the *symptom* as confirmed and the *fix
  direction* as a strong lead rather than a sure thing):**
  - **WebVTT `NOTE` (comment/metadata) blocks aren't recognized at all,
    so their text gets silently absorbed into whatever cue is open at
    that point.** Real example: Tavares FL CivicClerk BCC meeting,
    2024-06-11 (`tavares-fl-2024-06-11-bcc-regular-board-meeting`) —
    stored segments alternate real spoken text with literal metadata
    lines like `NOTE Confidence: 0.962116034285714`, e.g. "Good morning
    and welcome to the June 11th, NOTE Confidence: 0.962116034285714
    2024 meeting of the Board NOTE Confidence: 0.962116034285714 of
    County Commissioners." `parse_vtt()`
    ([app/utils/vtt_parser.py:34](app/utils/vtt_parser.py#L34)) only
    special-cases blank lines, `WEBVTT`, timestamp lines, and (as of a
    2026 fix) a cue-identifier lookahead — nothing checks for a line
    starting with `NOTE`, so per the WebVTT spec these comment blocks
    fall straight into the "append as cue text" branch.
  - **Inline WebVTT voice tags (`<v.Male.spk3 Speaker2>` etc.) are never
    stripped**, and can visibly mangle words when a tag lands mid-word
    across the source's line wrapping. Real example: a platform=`unknown`
    meeting (`meeting-7ac1da`, an Orange County FL budget presentation,
    parsed via `app/platforms/generic_fallback.py`, which also goes
    through `parse_vtt()` for `.vtt` content) — stored text includes raw
    `<v.Male.spk3 Speaker2>` tags inline, and what's very likely a real
    person's name comes out mangled as "misbranded rigors." `parse_vtt()`
    itself does no tag-stripping at all; the only tag-stripping in this
    file (`_TAG_RE`/`_MARKUP_TAG_RE`) lives in `dedupe_rollup_cues()` and
    `strip_unknown_caption_markup()`, neither of which runs on this path.
  - **A "growing/rollup caption" duplication artifact appears on multiple
    non-YouTube adapters, and the fix for exactly this pattern already
    exists but isn't wired to them.** `dedupe_rollup_cues()`
    ([app/utils/vtt_parser.py:291](app/utils/vtt_parser.py#L291)) was
    built for YouTube's growing-caption cue structure and is called only
    from `app/platforms/youtube.py` and `app/platforms/viebit.py` — never
    from `granicus.py`, `civicclerk.py`, or `escribe.py`, confirmed by
    grep. Real examples of the same symptom class on those un-wired
    adapters: Tacoma WA council meeting (Granicus,
    `city-of-tacoma-wa-2026-01-06-city-council-on-2026-01-06-5-00-pm` —
    `">> Councilmember Hines: >> Councilmember Hines: WE >> Councilmember
    Hines: WE WILL >> Councilmember Hines: WE WILL GET..."`), two DC
    Judiciary & Public Safety Committee hearings (Granicus, 2026), a
    CivicClerk meeting (`2026-03-10-city-council-meeting`), and an
    eScribe meeting (Essex County,
    `2025-12-03-county-of-essex-2026-advocacy-priorities-essex-county-council-regular`).
    Worth checking whether `dedupe_rollup_cues()`'s generic
    prefix-growing logic actually handles these adapters' cue shape
    correctly before wiring it in blind — its docstring and worked
    example are YouTube-specific, and these sources include a repeated
    role-label prefix (`>> Councilmember Hines:`) that YouTube's pattern
    doesn't have, so the fix may need adjusting rather than a direct
    wire-through.

- **[JUST-DO-IT] Second real instance of the Fountain Valley-shaped garbled/wrong-
  language pattern (see `BACKLOG_DONE.md`), found 2026-08-16 via the same
  DB skim.** Chula Vista Public Comments, 2026-05-19 (eScribe,
  `chula-vista-public-comments-2026-05-19-city-council-meeting`):
  `transcript_language` and `transcript_warnings` both fire (tagged `es`
  with a "no matching-language track found" warning, plus the garbled-at-
  source marker), and the stored Spanish text does read as garbled rather
  than fluent. Not independently re-verified against the live page — just
  confirms this failure shape recurs on a different real customer, not a
  one-off.

- **[DONE?] Census-table baseline validation of all 649 archived jurisdictions
  (2026-08-15, workstream 1 of `JURISDICTION_METADATA_PLAN.md`) — new
  confirmed findings beyond the two adapter bugs below.** Numbers: 510
  valid as-is, 73 reachable by longest-valid-prefix trim, 44 not in
  table, 22 blank. The trim bucket splits cleanly on a tail-sanity check
  (lowercase prose/roman numerals/digits in the discarded tail): 16 true
  bleed cases (every one a correct repair — Hercules, Boston, Fort
  Worth...) vs 57 legitimate long entities where trimming would *destroy*
  a correct name ("Lake Washington School District" → "Lake", "Bay Area
  Headquarters Authority" → "Bay") — so trim must always be gated on
  bleed signals, never applied bare. Three bleed cases the current
  signals miss (Sarasota/Hollywood/Hampton — Title-Case/ALL-CAPS bleed);
  a mid-word-truncation signal (tails ending "the Tex", "servic",
  "Standa" — the regex's own 40-char cap cutting words in half) would
  catch all three. Specific new bugs found, each verified against the
  data, all unfixed:
  - ~~**Granicus's wordninja subdomain-humanization fallback produces
    confident garbage on acronym subdomains**~~ **Fixed 2026-08-16, wave
    2 item 8 — full detail in `BACKLOG_DONE.md`.** (~15 archived rows):
    "Ride Uta" (rideuta), "La Usd" (lausd), "Ccs F" (ccsf), "Pcb Gov"
    (pcbgov), and the best one: **"S Fw, MD" from `sfwmd`** — the South
    Florida Water Management District's trailing "md" misread as a
    Maryland state suffix. `_humanize_subdomain()` now declines (rather
    than guessing) via the new public
    `jurisdiction_enrich.validated_subdomain_extract()`, which checks the
    raw unsplit subdomain against the Census tables first and validates
    wordninja's split output after. Not yet re-resolved against the
    ~15 already-archived rows above (this fix only changes future
    resolves) — worth a bulk re-check same as the other stale-archive
    cases in this file. A second, distinct failure mode in the same
    fallback (user's correction 2026-08-15) is fixed by the same change:
    **"Gales Burg" from `galesburg`** — not an acronym at all, but
    wordninja *over-splitting* a real one-word city name that validates
    against the Census table untouched ("galesburg" is literally already
    a valid places.csv key, Galesburg IL/MI/ND) — the new raw-label-first
    check catches this too.
    **Two more real confirmed examples, found 2026-08-15 scanning all 501
    rows of the live `/coverage` "Every place we've covered" table for
    outliers (see the new entry below on that table being a real, useful
    QA surface):** `psrc2.granicus.com/player/clip/1001` → jurisdiction
    "Psr C 2" (Puget Sound Regional Council — a real acronym-named
    regional agency, not a Census place, same shape as `sfwmd`/`rideuta`
    above) and `loswegok12.granicus.com/player/clip/903` → "L Oswego K
    12" (Lake Oswego School District, OR — same class as the already-
    flagged "townships/school districts aren't in the places table"
    gap above, compounded by the acronym-humanization bug here).
  - **Two pages store a literal date as the jurisdiction** ("July 21,
    2026", "August 11, 2026") — source adapter not yet traced. **Checked
    2026-08-16 (WO-16): no longer reproducible.** A fresh full scan of
    production `/coverage` (843 rows, up from 649 at the original audit —
    fetched live via `curl`, not guessed) found zero jurisdiction values
    matching a plain "Month Day, Year" shape, and neither exact date
    string appears anywhere in the page. Most likely explanation: these
    were Granicus/eScribe bleed cases the same shape as the ones WO-14
    fixed (a "City of X" match running on into unrelated agenda date
    text), incidentally closed by that fix or a peer session's parallel
    work rather than independently root-caused here. Not claiming this as
    a verified fix — the original two URLs were never recorded and
    `baseline_validation.csv` no longer exists in any session's
    scratchpad, so there's no way to confirm *why* they're gone, only
    that they are. Worth watching for a recurrence next time this kind of
    scan is run, not reopening speculatively now.
  - ~~**`app/utils/jurisdiction_data/places.csv` is missing every Census
    "(balance)" consolidated city**~~ **Fixed 2026-08-15 — full detail in
    `BACKLOG_DONE.md`.**
  - ~~**"Saint"↔"St." normalization gap**~~ **Fixed 2026-08-16 —
    `app/utils/jurisdiction_enrich.py`'s `_table_lookup()` now also tries
    a `_contract_saints()` candidate ("Saint"/"Sainte" → "St."/"Ste.",
    the reverse of the existing `_expand_abbreviations()`, needed because
    a direct grep confirmed the Census table stores this one family
    abbreviated — 148 real "St. " rows, zero "Saint " rows — unlike
    Fort/Mount/North/South/East/West, all stored spelled out) and a
    `_strip_okina()` candidate (Hawaiian ʻokina/apostrophe variants —
    "Kauai County" in-table vs "Kauaʻi County" on pages). New tests in
    `tests/test_jurisdiction_enrich.py`.
  - ~~**Townships/county-subdivisions aren't in the places table at
    all**~~ **Fixed 2026-08-16 (WO-16) — full detail in
    `BACKLOG_DONE.md`, including a real new collision this surfaced**
    (a genuine, obscure "Oshawa Township, MN" now shares a name with the
    much-better-known Oshawa, ON — a real, if narrow, structural
    limitation of the whole validate-against-Census-tables approach,
    documented rather than fixed since it doesn't actually corrupt the
    stored jurisdiction text, only its internal confidence tag — see the
    `BACKLOG_DONE.md` entry for why).
  - **One Canadian jurisdiction** (Elliot Lake, ON — eScribe) — the
    tables are US-only by construction. **Checked 2026-08-16 (WO-16): no
    live bug found.** Directly tested `finalize_jurisdiction()` against
    "Elliot Lake"/"Elliot Lake, ON" shapes — both correctly grade
    `"unverified"` (kept as-given, not rejected, not force-fit to a wrong
    US state) and `enrich_jurisdiction_text()` doesn't attempt a
    wrong-country ZIP/domain lookup either. `"unverified"` is
    `JurisdictionResult`'s own documented correct category for "a real
    entity type no national table covers" (school districts, MPOs, and —
    per this finding — non-US jurisdictions generally), and
    `jurisdiction_confidence` is explicitly a diagnostic-only field with
    zero UI surface (`JURISDICTION_METADATA_PLAN.md`), so there's no
    user-visible symptom to fix. The "exemption flag" this bullet
    originally asked for would matter for a future re-run of the
    Census-baseline *validation audit script* specifically (so Elliot
    Lake doesn't inflate its "not in table" count) — that script itself
    no longer exists in any session's scratchpad to extend, so left as a
    note for whoever rebuilds it next, not a runtime code change.
  - **Validation caught one subtly wrong stored name**: "Bainbridge, WA"
    — the real WA city is Bainbridge *Island*; plain "Bainbridge" only
    exists in GA/IN/NY/OH, so the table's state-mismatch flag was
    correct, not noise.

  Full per-row detail: `baseline_validation.csv` in this session's
  scratchpad; regenerate any time via the script logged in
  `JURISDICTION_METADATA_PLAN.md`'s workstream 1.

- ~~**[JUST-DO-IT] `GranicusAssetFinder._extract_metadata()`'s page-body jurisdiction regex
  has no sentence/tag boundary, so it can swallow unrelated agenda text
  into the stored jurisdiction**~~ **Fixed 2026-08-16 (WO-14) — both
  Granicus and eScribe's independent copies of this bug now share
  `jurisdiction_enrich.extract_jurisdiction_chain()`. Full detail
  (root cause, all 9 Granicus + 6 eScribe confirmed examples, live
  re-verification against the real Hercules page) in `BACKLOG_DONE.md`.**
  One real gap found and left explicitly open by that fix, not silently
  closed:

  ~~**Residual gap: `_looks_like_bleed()`'s trim-repair gate still misses
  pure Title-Case/ALL-CAPS bleed with no lowercase/digit/roman-numeral
  signal in the discarded tail**~~ **Fixed 2026-08-17 as part of the
  broader Canadian-data + Title-Case-bleed pass — see `BACKLOG_DONE.md`'s
  "Jurisdiction-bleed, confirmed cross-platform" entry for the
  `_MIN_BLEED_WORD_RUN = 4` signal and its calibration evidence.**
  Directly re-verified against the two examples named here: Sarasota
  (`"City of Sarasota Legacy Business PLEDGE OF"`) now repairs correctly
  to `"City of Sarasota, FL"`. Castle Rock (`"Town of Castle Rock
  Authorizing"`) does NOT — its discarded tail is only 1 word
  ("Authorizing"), below the new threshold, so it falls into the
  single-word-tail gap now tracked as its own live entry above (search
  "single-word-tail gap" in this file). Punta Gorda/Castle Pines weren't
  re-tested directly this pass (their exact raw strings weren't recorded
  in this entry), but Castle Pines was already confirmed fixed via the
  pre-existing lowercase signal (see `test_finalize_jurisdiction_fills_a_state_the_bled_original_never_could`
  in `tests/test_jurisdiction_enrich.py`), and Punta Gorda's tail shape
  ("Punta Gorda ..." off a Granicus body-regex bleed) matches the same
  pattern the new signal was built and verified against.

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

- **[IMPROVEMENT-ROUND] Swagit's jurisdiction extraction has no fallback at all when the page
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

- **[DONE?] Granicus's own captions.vtt appears to hard-cap at exactly 36,000 cues
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

  ~~**A fourth real case did show up, 2026-08-18** — user-shared
  `bedfordoh.primegov.com/Portal/Meeting?meetingTemplateId=518` (real
  video/captions both resolve correctly: YouTube embed, 1346 real
  auto-caption segments; only `jurisdiction` is wrong). Confirmed live:
  `jurisdiction` comes back `"County of Cuyahoga, OH"` instead of `"City
  of Bedford, OH"`.~~ **Fixed 2026-08-21 — see `BACKLOG_DONE.md`'s
  "PrimeGov Bedford/Cuyahoga" entry.** A new, narrowly-scoped
  `_COUNCIL_HEADER_RE` tier (tried before `_JURISDICTION_RE`) matches the
  bare "{Name} City/Town/Village Council" header shape and now wins over
  the adjacent "County of Cuyahoga" letterhead cell. This closes the
  specific letterhead-adjacency failure shape below, not the whole class
  of SLC/OKC/Thousand-Oaks-style false positive (a genuine body-prose
  mention winning by unscoped first-match, unrelated to a letterhead) --
  that broader structural gap is still open, see this entry's own opening
  paragraph above.

  Root cause, fetched and checked directly: the page's
  letterhead is a small header table with "Bedford City Council" and
  "County of Cuyahoga" in adjacent cells (identical styling, both near
  the top) — but `_JURISDICTION_RE` only matches the literal `"(city|
  county|town) of ..."` shape, so "Bedford City Council" (no "of") never
  matches while "County of Cuyahoga" does, and wins via unscoped
  first-match same as the OKC/Thousand Oaks/SLC cases. The real, correct
  "City of Bedford" text does exist on the page (an ordinance title
  further down in the agenda body) but sits after the false-positive
  county match, so position-based tie-breaking still doesn't separate
  them. **New failure shape worth noting**: unlike SLC/Holladay (a false
  positive buried in unrelated body prose), this one's false positive is
  *also* structurally a header/letterhead mention — just the wrong
  entity within it (the parent county, not the specific city) — so a
  "prefer the first header-shaped match" heuristic would not have fixed
  this case even if one existed.

  ~~**Separately: PrimeGov never backfilled `title` from the page itself
  when YouTube's own extraction is empty**~~ **Fixed 2026-08-13 — full
  detail in `BACKLOG_DONE.md`.** Confirmed live on a real LA City
  Council meeting the user flagged: every `Portal/Meeting` page carries
  a real, useful inner `<title>` tag (confirmed across 3 independent
  customers — OKC, Thousand Oaks, LA), sitting right after a useless
  outer `<title>Meeting</title>` — never read before this fix, so a page
  came through with no title at all whenever yt-dlp is blocked (the
  documented Render-IP gap), even though jurisdiction/date already had
  their own page-based fallbacks.

- ~~**[JUST-DO-IT] eScribe now has a real, confirmed positive caption
  example — but its jurisdiction chain-extraction picks the wrong
  government for two-tier (regional + constituent-town) sites.**~~
  **Fixed 2026-08-21 — see `BACKLOG_DONE.md`'s "jurisdiction-bleed,
  gate-blindness recovery" entry.** `finalize_jurisdiction()` now
  cross-checks its top-level literal-match branch (not just
  `_trim_repair()`) against a validated subdomain-derived candidate, and
  `scripts/build_jurisdiction_data.py` now includes Ontario's real
  Durham/Peel/Waterloo regional municipalities (the StatsCan
  completeness gap this bug's own root cause depended on — see the
  "StatsCan/Census table completeness gap" entry above, now partially
  closed for these 3 confirmed-in-production customers). Together these
  make the `peelregion` subdomain resolve to "Peel Region, ON" and
  override the constituent-town "Town of Caledon" text match.
  User-shared 2026-08-18:
  `pub-peelregion.escribemeetings.com/Meeting.aspx?Id=c129beef-a3cf-49ae-827d-27c6b3a547a5&Agenda=Agenda&lang=English`
  (Peel Region, ON "Regional Council" meeting). Resolves with real video
  (iSiLIVE, `cdn1.isilive.ca`) **and 1101 real caption segments, zero
  warnings** — this closes the "no eScribe example with populated
  captions has ever been found" gap called out in `CLAUDE.md`/
  `BACKLOG.md` (CivicClerk's own version of that same gap is separately
  still unconfirmed either way, not addressed by this). Meeting `Id` is
  an opaque GUID (`c129beef-...`), not a sequential/guessable number like
  Granicus's `clip_id` or CivicClerk's `event_id` — no way to enumerate
  more eScribe meetings by incrementing an ID; discovery would need each
  customer's own calendar/index page. One incidental correlation that
  might help elsewhere: the iSiLIVE `data-client_id` embed attribute
  matched the eScribe subdomain label exactly (`peelregion` for both).

  Real bug found alongside it: `jurisdiction` comes back `"Town of
  Caledon, ON"` instead of `"Regional Municipality of Peel"`/"Peel
  Region". Root cause, fetched and checked directly: Peel Region's
  agenda covers infrastructure/committee items located within its three
  constituent lower-tier municipalities (Caledon, Brampton, Mississauga),
  so "Town of Caledon" appears validly and repeatedly in item text and
  in a clerk-signature line near the top of the page — `_stoprule_extract`/
  `_capitalization_walk_extract` (the shared chain in `app/utils/
  jurisdiction_enrich.py`, tried in that order by `extract_jurisdiction_
  chain()`) finds and validates it first, so the chain returns immediately
  and never reaches its own tier-3 subdomain fallback
  (`_jurisdiction_from_subdomain`), which *would* have correctly produced
  "Peel Region" from the `peelregion` subdomain alone (confirmed by
  reading `_jurisdiction_from_subdomain()`'s own wordninja-split logic
  against that label). Structurally the same "first validated candidate
  wins, positional order isn't a reliable signal" problem already
  documented for PrimeGov's `_JURISDICTION_RE` above, but on a different
  code path (the shared chain, not PrimeGov's own regex) and a distinct
  new failure shape: here the false-positive candidate is a real,
  legitimately-*mentioned* jurisdiction (a constituent town), just not
  the meeting's *own* jurisdiction (its regional parent) — not stray
  body prose or a copy-pasted address like the chain's other documented
  false positives. Fixed 2026-08-21 (see strikethrough above) by
  extending `finalize_jurisdiction()`'s existing subdomain cross-check
  (previously only applied inside `_trim_repair()`, added 2026-08-19 for
  the Courtenay/Victorville cases) to its top-level literal-match branch
  too, plus adding the 3 confirmed-in-production Ontario regional
  municipalities the cross-check's own subdomain candidate needed to
  validate at all.

- ~~**`find_platform_link()`'s fallback delegation could self-loop into
  real infinite recursion**~~ **Fixed 2026-08-12 — full detail in
  `BACKLOG_DONE.md`.** A same-page `#fragment` anchor (e.g. a "skip to
  content" accessibility link, present on nearly every Legistar page)
  used to resolve back to the current page and get delegated to again,
  recursing without bound. `find_platform_link()` now skips any candidate
  resolving to the same URL as `page_url`, closing this at the root for
  every caller.

- ~~**`CablecastAssetFinder` hardcodes jurisdiction as "Detroit, MI" for
  *every* Cablecast customer, not just Detroit**~~ **Fixed 2026-08-12 —
  full detail in `BACKLOG_DONE.md`.** Now derived per-customer from the
  already-parsed Remix `site` object instead of a hardcoded constant; a
  state suffix is only appended for a customer actually confirmed so far
  (Detroit, Charlotte — see the "no-state jurisdiction audit" item below
  for the general version of this gap). Not yet checked against a third
  real Cablecast customer, so `_extract_jurisdiction()`'s single-word-city
  assumption is worth revisiting once one turns up.

- ~~**Portland, OR's council agenda pages really do resolve correctly
  today — the resolve-level cache had no expiry, unlike its Archive-level
  counterpart, and was serving a stale, permanently-cached negative
  result from before that was true.**~~ **Fixed 2026-08-12 — full detail
  in `BACKLOG_DONE.md`.** `get_cached_resolution()` (`app/db/crud.py`) now
  expires a `video_found=False` row after an hour, mirroring the Archive's
  own `ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT` reasoning; a row that did find
  a video keeps no TTL.

- ~~**"Request Transcript from Audio" showed a misleading "no usable
  audio or video source" error that was actually just the transcription-
  request rate limit**~~ **Fixed 2026-08-12 — full detail in
  `BACKLOG_DONE.md`.** slowapi's 429 response body has no `ok`/`message`
  keys, so both duplicated copies of `runFeasibilityCheck()`
  (`app/static/player.js`, `archive/static/meeting_page.js`) used to fall
  through to the generic failure message. Both now check `res.status ===
  429` explicitly first and show real rate-limit copy instead.

- **[IMPROVEMENT-ROUND] Google Search Console flagged 3 "Videos" structured-data issues
  site-wide (alert received 2026-08-12)**: missing `thumbnailUrl`
  (critical — blocks video rich-result eligibility), plus `uploadDate`
  reported as both an invalid datetime value and missing a timezone
  (non-critical). Both trace to the same `VideoObject` JSON-LD block in
  [meeting_page.html:37-66](archive/templates/meeting_page.html:37-66):
  - ~~`thumbnailUrl` is omitted entirely~~ **Partially fixed 2026-08-14
    — full detail in `BACKLOG_DONE.md`'s "VideoObject.thumbnailUrl +
    Clip key moments" entry.** YouTube-backed pages (the free,
    predictable `i.ytimg.com` slice) now emit `thumbnailUrl` plus
    `og:image`/`twitter:card`, and pages with real agenda timestamps
    also gained `Clip` "key moments" markup in the same pass. **Still
    open**: direct mp4/m3u8 pages — the majority of the Archive — still
    have no thumbnail; that needs real `ffmpeg` frame extraction (not a
    new dependency category, `ffprobe` is already in the
    transcription-feasibility pipeline) and somewhere to host the
    extracted frames, which is a real new decision (this app hosts no
    images today). Re-check Search Console once YouTube-backed pages
    are re-crawled to confirm the critical flag actually clears there.
    **Update 2026-08-21, from a real Search Console "Videos" enhancement
    report screenshot**: "No thumbnail URL provided" is now down to just
    1 video site-wide — but this is NOT confirmation the mp4/m3u8 gap
    above is closed (it isn't; `archive/utils/video_thumbnail.py` still
    only handles YouTube-backed pages, unchanged since the 2026-08-14
    fix). The same report shows a much larger, likely-explanatory issue
    instead — see the new entry immediately below.
  - ~~`uploadDate` missing a timezone~~ **Fixed 2026-08-14 — full detail
    in `BACKLOG_DONE.md`'s "Wave 1" entry.** Now emits
    `date + "T00:00:00Z"`. **Still open**: the separate "invalid
    datetime value" flag suggests at least one real row has a
    non-`YYYY-MM-DD` value in `date` (a bad adapter extraction) — never
    cross-checked against actual production values, so it's not known
    whether this is already fixed as a side effect or still live.
  - ~~All 6 `Clip` entries on the real Minneapolis LIMS test page flag
    "Missing field endOffset"~~ **Fixed 2026-08-14 — full detail in
    `BACKLOG_DONE.md`'s "Wave 1" entry.** LIMS's `_flatten_timestamps()`
    now sets each item's `end` to the next item's `start`, matching
    Granicus/IQM2's convention, instead of always equaling `start`.

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

- ~~**[DONE?] `sitemap.xml` includes `generic_fallback` pages that the page template
  itself `noindex`es**~~ **Fixed 2026-08-17 — full detail in
  `BACKLOG_DONE.md`'s "Sitemap no longer lists noindexed
  `generic_fallback` pages" entry.** The separate "Page indexed without
  content" reason from the same 2026-08-17 alert batch is not explained
  by this fix, but is likely resolved separately by PR #136's empty-page
  exclusion (also shipped 2026-08-17, see `BACKLOG_DONE.md`'s "Empty
  ('zero-value') meeting pages" entry) — not confirmed, needs a Search
  Console re-crawl to clear; see `CLAUDE_BACKLOG.md`'s 2026-08-17 entry
  for the updated detail, and for the third reason ("Page with redirect",
  alert received 2026-08-16) that's still genuinely uninvestigated.

- **YouTube-backed meetings' transcripts run through
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

- ~~**PrimeGov's `_extract_jurisdiction()` regex wasn't scoped to the page
  header, so it could pick up an unrelated city name mentioned in agenda
  body text.**~~ **Fixed 2026-08-12 — full detail in `BACKLOG_DONE.md`.**
  `_extract_jurisdiction()` now strips `<script>`/`<style>` boilerplate
  and caps the search to the first 2000 characters of what's left
  (matching `_extract_date()`'s own convention), and `resolve()` no
  longer falls back to YouTube's `uploader` name when the page itself has
  no match — a page whose header doesn't fit the "City/County/Town of X"
  pattern (e.g. real "SALT LAKE CITY COUNCIL"-shaped headers) now
  correctly comes through with no jurisdiction rather than a wrong one.
- ~~**Jurisdiction display was verbose and inconsistent site-wide — "City
  of Napa, CA" everywhere read as redundant.**~~ **Fixed 2026-08-12 — full
  detail in `BACKLOG_DONE.md`.** A display-time Jinja filter
  (`jurisdiction_display`, backed by `archive/utils/
  jurisdiction_format.py`'s `format_jurisdiction_display()`) now drops a
  leading "City of "/"City " everywhere a stored jurisdiction renders;
  "County of X" and state-legislature-style names are untouched. What's
  actually stored is unchanged. The resolver's own client-rendered page
  has a small JS mirror in `app/static/player.js`.

- ~~**Swagit's title-parsing regex swallowed a "- Revised -"/"- Closed
  Session -" marker into the jurisdiction on Long Beach meetings**~~
  **Fixed 2026-08-13 — full detail in `BACKLOG_DONE.md`.** A lazy
  title-part match locked onto the first hyphen it could make work rather
  than the real city/state boundary, e.g. "Revised - Long Beach, CA"
  instead of "Long Beach, CA". Made the title-part match greedy so it
  always lands on the last hyphen before ", {State}". Live-reverified
  2026-08-13: re-resolving `longbeachca.new.swagit.com/videos/395182`
  fresh with the current code correctly returns `Long Beach, CA` — the
  fix itself is confirmed working, and the stale archived pages have
  since been corrected too — see "Bulk backfill of archived pages" in
  `BACKLOG_DONE.md`.

## Meeting page UI gaps found 2026-08-14 (live testing)

~~Agenda/transcript timestamp column drift, meeting pages rendering
unusually wide, and the missing auto-scroll toggle on archived pages~~
**Fixed 2026-08-14 — full detail in `BACKLOG_DONE.md`'s "Wave 1" entry.**

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

- **[JUST-DO-IT] `/coverage`'s "By platform" section should list more platforms.**
  `DIRECT_PLATFORMS`/`CUSTOM_PLATFORMS` in `archive/db/crud.py` don't
  reflect the full current adapter registry
  (`app/platforms/__init__.py`'s `register_all_finders()`) — confirmed by
  actually diffing the two: the registry has 22 finders total, of which
  `legistar`/`civicplus`/`primegov`/`civicweb`/`youtube` are deliberately
  and correctly excluded (`crud.py`'s own comment explains why — they're
  calendar-tool routers whose `MeetingPage.platform` always ends up as
  whatever they delegated to, never their own name, so a row for them
  could never have a real example), but **six real, dedicated adapters
  with their own `platform_name` are registered and can produce real
  ingested pages, yet aren't in `DIRECT_PLATFORMS` or `CUSTOM_PLATFORMS`
  and so fall through `get_platform_coverage()`'s `if`/`elif` chain with
  no matching branch — silently dropped from the page entirely, not just
  under-labeled**: ChampDS, IQM2, ClerkBase, Seattle Channel, TelVue, and
  Hyland. Needs both: (a) adding these six to `DIRECT_PLATFORMS` (or a
  new grouping, if any behave like the YouTube-delegating `CUSTOM_PLATFORMS`
  entries — not checked here), and (b) updating the page's intro
  paragraph, which currently only names the six original `DIRECT_PLATFORMS`
  vendors ("Granicus, CivicClerk, Swagit, Viebit, eScribe, and Cablecast")
  and doesn't mention any of the newer ones.

## Platform coverage — open questions

Split 2026-08-17 into sub-groups by real status, since lumping all of
these under one undifferentiated priority hid real signal -- a live
broken automation and two items genuinely needing a human decision were
sitting next to purely dormant, needs-a-real-example items. This section
has grown since the original triage pass sorted 19 items into these
buckets -- several additional items turned up on re-read and were sorted
by the same test (see BACKLOG_DONE.md's triage-session note, or the PR
that added this reorg, for which ones are new).

### Done

~~**[DONE?] Cablecast/Swagit/CivicClerk stage-2 seeks — not yet run.**~~ **Done
  2026-08-17.** 728 real candidate URLs found (Cablecast 44/256 hosts,
  Swagit 430/434, CivicClerk 254/257 — full breakdown in
  `CDX_QUERIES.md`). Sample-checked for real caption content (44/30/30):
  25 confirmed real, **ingested for real**; the other 703 added to
  `scripts/tier3_auto_transcription_queue.txt` for the existing cron
  feeder to resolve and push at pickup time, rather than re-checking each
  one by hand first. Also fixed a real bug in `hosts_to_urls.py` found
  live during this run: a shared single-thread executor meant to bound a
  DNS-hang per-call instead let one real hang silently wedge every host
  after it for the rest of the run — fixed to use a fresh one-shot
  executor per call. That script lives in `rtr-business/research/`, not
  this repo.

  **CivicPlus has zero currently-live, confirmed-real URLs anywhere in
  this repo, re-confirmed 2026-08-16 building the WO-13 adapter health
  canary.** `ca-westlakevillage.civicplus.com` — the one site this
  adapter was ever verified against — already had a documented note
  (`tests/fixtures/civicplus/README.md`) saying it stopped resolving as
  of 2026-08-07; a live DNS lookup while building the canary confirmed
  it's still dead (`ClientConnectorDNSError`, not an adapter bug). A real
  untested replacement candidate is already on file above (this same
  section, Maricopa County AZ note): `maricopa.gov/324/Board-of-
  Supervisors-Meeting-Information`, a CivicPlus AgendaCenter page linking
  directly to YouTube — but its URL shape (`/324/...`, a generic CivicPlus
  content-module path) doesn't obviously match the `/AgendaCenter/...`
  shape `civicplus.py`'s docstring documents, so it needs a real fetch-
  and-verify pass before trusting it, not just wiring it in. Until then,
  `scripts/adapter_canary.py`'s `CANARY_URLS` deliberately excludes
  civicplus (see that file's own comment) rather than pointing at a dead
  or unverified URL.

~~**`page.platform` never gets updated on a re-ingest of an existing
  page.**~~ **Fixed 2026-08-16 — full detail, including a real
  unrelated production deploy incident hit right after merging, in
  `BACKLOG_DONE.md`.**

~~**Seattle Channel (`seattlechannel.org`) — new platform, not supported
  at all today**~~ **Built 2026-08-14 — new `app/platforms/seattlechannel.py`,
  full detail in `BACKLOG_DONE.md`.** Confirmed live against two independent
  real meetings on the `/videos?videoid={id}` shape: direct mp4, real SRT
  captions, and real per-item `data-seek` agenda timestamps. Scoped
  narrowly to that exact URL shape — the older feed-style index page and a
  bare `/videos` with no `videoid` are deliberately left to
  `generic_fallback.py`'s own JW-config scan, which already handles them
  reasonably (see `BACKLOG_DONE.md`'s 2026-08-14 rebuild entry).

- **[DONE?] Wayne County, MI's own meeting-listing site
  (`waynecountymi.gov`) — user-reported 2026-08-13, root cause confirmed
  to be a fetch-level block, not a parsing gap.** Real example:
  [waynecountymi.gov/.../Wayne-County-Commission-January-8-2026](https://www.waynecountymi.gov/Government/Elected-Officials/Commission/Committees/Full-Commission-Meetings/2026/Wayne-County-Commission-January-8-2026)
  (calendar/listing page:
  [.../Full-Commission-Meetings](https://www.waynecountymi.gov/Government/Elected-Officials/Commission/Committees/Full-Commission-Meetings)).
  Prod currently shows a bare "Meeting" — no title, no jurisdiction, no
  video, no agenda — even though, per the user, the page has all of it:
  a plain "Video" link to `youtu.be/RFwXrAzkXR8`, an agenda PDF, and a
  header reading "Wayne County Commission - January 8, 2026" that the
  URL slug also spells out.

  **Confirmed via a real browser (`mcp__Claude_Browser__*`) that every
  one of those is real, static, server-rendered content** — no JS
  needed to see it: `<title>Wayne County Commission - January 8, 2026 -
  Wayne County, Michigan</title>`, a plain `<a href="https://youtu.be/
  RFwXrAzkXR8">Video</a>`, and a plain `<a href=".../agenda2026-0108.pdf">
  Agenda2026-0108.pdf</a>`. This is exactly the shape
  `generic_fallback.py`'s priority-1 path (a plain linked YouTube video)
  and `_find_agenda_link()` (a same-page `<a>` whose text contains
  "agenda") are already built to catch — so the empty prod result isn't
  a missing-pattern gap like the Sebastopol/Tarrant entries above.

  **Root cause instead: the site's own edge/WAF blocks the fetch itself.**
  A plain `curl` with the same Chrome `User-Agent`
  `generic_fallback.py` already sends returned a 403 with a literal
  Akamai `Access Denied` / `errors.edgesuite.net` body (~550 bytes, no
  page content at all) — and `resolve()`'s `response.raise_for_status()`
  (`generic_fallback.py:149`) turns that straight into a raised
  exception, caught generically in `app/main.py`'s `/api/resolve`
  handler (`except Exception as e:` around line 358) and surfaced as an
  empty best-effort result with nothing populated — matching the "bare
  'Meeting', no video, no jx, no agenda" symptom exactly. A real browser
  (real TLS/JS/cookie behavior) gets through fine; a plain server-side
  `aiohttp`/`curl` request does not. Not the same failure mode as the
  YouTube-caption-fetch IP block noted elsewhere in this file (that one
  is Render's cloud IP specifically vs. a residential one); this looks
  like Akamai Bot Manager reacting to the request's fingerprint rather
  than its origin IP, though that's not independently confirmed here.

  Not fixed this pass — logged per this repo's "new bugs/gaps found
  while working go in BACKLOG.md" convention. If this turns out to
  affect other government sites (Akamai is a common CDN/WAF for larger
  county/state sites), a shared retry-via-headless-browser fallback for
  a confirmed-blocked fetch would fix all of them at once rather than
  a Wayne-County-specific patch — but only one example exists so far,
  so not worth generalizing yet.

  **Ruled out, not the same root cause as the Sebastopol UA fix below**:
  re-checked live 2026-08-13 after bumping `generic_fallback.py`'s UA to
  a modern Chrome string (see `BACKLOG_DONE.md`) — this page is still
  fully blocked with the new UA too, confirming Akamai's block here isn't
  simply reacting to the old Chrome/91 string the way Sebastopol's WAF
  was. A deeper fingerprint check (TLS/JA3, cookies, JS challenge) or a
  genuinely different WAF product, not yet isolated.

  **Update 2026-08-14: the headless-browser escalation this entry asked
  for is now built AND enabled in prod.** Full detail in
  `BACKLOG_DONE.md`'s rebuild entry: a block-family status (this page's
  real Akamai 403 was the trigger it was built against) escalates to one
  real-Chromium fetch, whose rendered HTML re-runs the same diagnosis.
  Verified locally flag-on against this exact live page (resolves fully:
  real youtu.be video + agenda PDF + real title). The operational
  precondition — playwright actually working on Render — was then
  verified for real the same day (a fresh, never-archived Minneapolis
  LIMS meeting, `MarkedAgenda/COW/6144`, resolved fully through
  production; LIMS has no non-browser path, so that's direct proof —
  closing `render.yaml`'s open build question from the 2026-08-09
  incidents), and `GENERIC_FALLBACK_HEADLESS=1` was committed to
  `render.yaml`'s resolver env block (a literal value, not a secret).

~~**Sacramento County, CA's own agenda site (`agendanet.saccounty.gov`)
  — a third real customer of the same OnBase Agenda Online product.**~~
  **Built 2026-08-16 as part of the new `app/platforms/hyland.py`
  adapter, full detail in `BACKLOG_DONE.md`.** The `itemEventPoints`/
  `sectionEventPoints` deep-link mechanism noted below as "not
  investigated further" turned out to be exactly the missing piece —
  joined against the AJAX agenda outline's own item ids, it's now the
  adapter's real timestamped `agenda_items` mechanism.

### Needs a human decision

- **[HUMAN] Chicago's City Clerk ELMS (`chicityclerkelms.chicago.gov`) is a real,
  strong dedicated-adapter candidate — found 2026-08-10 while confirming
  the generic fallback correctly caught it (it did, as an "unsupported
  gate," per user testing).** The video (a real Vimeo link) never showed
  up because the page injects it client-side from a separate API call
  (`data.videoLink`) — the raw server HTML has zero mention of "vimeo,"
  confirmed directly (a real curl of the meeting page, then grepping for
  the string, found nothing; the JS embedding it references
  `data.videoLink.forEach(...)`). Traced the real API the JS calls:
  `https://api.chicityclerkelms.chicago.gov/meeting-agenda/{meetingId}`
  — a genuine public, unauthenticated, no-headless-browser-needed JSON
  endpoint (confirmed live via plain `curl`, real response), returning:
  `videoLink` (the real Vimeo URL), `agenda.groups[].items[]` (real
  structured items — matter title, action taken, vote type — but **no
  timestamps**, so still not clickable-to-a-moment agenda_items the way
  LIMS's are), `files[]` (real PDF attachments including a real
  "Agenda"-typed one), `date`, `body` (jurisdiction), `attendance`.

  **Real, two-part reason this isn't a quick fix**: (1) building
  `chicago_elms.py` itself is straightforward (a plain `aiohttp` GET
  against that API, same shape as LIMS's JSON-endpoint step, no
  Cloudflare/headless-browser complication found so far); but (2) this
  app has **zero existing Vimeo playback support** — no adapter, and no
  frontend logic for it at all. YouTube's iframe-embed + Player API
  integration was itself a real, distinct piece of work (see
  `app/static/player.js`'s `initYouTubeVideo()`); Vimeo would need its
  own equivalent (Vimeo's own Player SDK/iframe embed — a showcase URL
  like `vimeo.com/showcase/citycouncil?video={id}` is not a raw file any
  more than a YouTube link is). Building the adapter without the
  playback piece would just produce a `video_url` nothing can actually
  embed. Whether Vimeo captions are even fetchable at all is also
  unconfirmed — no positive example checked yet, same "don't claim a
  caption path works without a positive example" convention as every
  other adapter here.

  **Update 2026-08-11 (Wave 2 survey): the API/data half is now fully
  unblocked with three fresh confirmed real examples**, meetingId
  confirmed to be a GUID (not a plain integer as the shape above might
  imply) — `?meetingId=9DB35AFF-9811-ED11-82E3-001DD80682F6` (2020-09-09
  City Council), `?meetingId=DCB45AFF-9811-ED11-82E3-001DD80682F6`
  (2021-10-14 City Council), `?meetingId=0852FF86-2DF4-ED11-A7C6-001DD806AE67`
  (2023-05-15 City Council) — all three confirmed via the real API to
  have a populated `videoLink` (Vimeo). **`transcriptLink` is present in
  the API schema but empty on all three samples** — still no positive
  caption example *from Chicago's own ELMS API* for this platform,
  consistent with the "don't claim a caption path works without a
  positive example" note above. Part (2), Vimeo playback support, is
  unchanged and still the real blocker.

  **Update 2026-08-11 (part 2): "are Vimeo captions fetchable at all"
  is now answered — yes, confirmed live — via a different city, not
  Chicago's own ELMS instance.** Chicago is also not a one-off: at least
  four other real US city council channels host meeting video directly
  on Vimeo, confirmed live via `vimeo.com/{account}` channel pages —
  **Salisbury, NC** (`vimeo.com/channels/coscouncil`), **Rockland, ME**
  (`vimeo.com/rocklandmaine`), **Spokane, WA**
  (`vimeo.com/spokanecitycouncil`), **Corvallis, OR**
  (`vimeo.com/cityofcorvallis`), and **Wilson, NC** (`vimeo.com/wilsonnc`)
  — so a general Vimeo playback+caption adapter would have more than one
  beneficiary. Salisbury's real 7/21/2026 meeting
  (`vimeo.com/1212025580`) has a live "CC/subtitles" toggle in the
  player; toggling it (confirmed via real browser, not a plain HTTP
  client — see below) triggers a request to a signed
  `captions.vimeo.com/captions/{id}.vtt?expires=...&sig=...` URL that
  returns **real, populated, correctly-timed English WEBVTT** — genuine
  per-cue dialogue ("I'll go ahead and call the special meeting to order
  on July 21st, 2026...."), not placeholder or blank content.

  **Real caveat this surfaces**: that signed caption URL is only
  discoverable through the player's own client-side config — a plain
  `aiohttp`/WebFetch request to `player.vimeo.com/video/{id}/config`
  (where that URL would normally be found) returns a **403**, and
  `vimeo.com/{id}` itself sometimes serves a real Cloudflare "Verify you
  are human" checkbox challenge (hit live on the Spokane sample this
  same check) — this app must never attempt to auto-solve that. So
  fetching Vimeo captions server-side, whenever a real example is
  eventually built against, likely needs the same real-headless-browser
  approach `headless_browser.py` already built for Minneapolis LIMS/SLC
  (a real Chromium render to let the player load and capture the signed
  URL it requests), not a plain HTTP client the way Granicus/Swagit/
  CivicClerk captions are fetched today — and even then, may not work
  100% of the time if the Cloudflare challenge is probabilistic rather
  than consistent. Unconfirmed whether Chicago's own ELMS-embedded Vimeo
  player behaves the same way as these channels' pages, or whether the
  showcase-embed shape it uses (`vimeo.com/showcase/.../video/...`)
  differs.

  **Update 2026-08-12: a real Chicago-native showcase-shaped example is
  now in hand, exactly the case flagged as unconfirmed just above** —
  user tried
  [chicityclerkelms.chicago.gov/Meeting/?meetingId=B2E99313-3D76-F111-AB0C-001DD80BE073](https://chicityclerkelms.chicago.gov/Meeting/?meetingId=B2E99313-3D76-F111-AB0C-001DD80BE073)
  directly, expecting the resolver to find, embed, caption, and offer
  AI-transcription on its Vimeo video. Confirmed via the same real API:
  `videoLink: ["https://vimeo.com/showcase/8925576?video=1210310337"]`
  — real "Committee on Budget and Government Operations" meeting,
  2026-07-16, `transcriptLink` empty (`[""]`) same as every other sample
  so far. This *is* the `vimeo.com/showcase/.../video/...` shape the
  entry above hadn't tested yet — but only the data side; whether its
  caption-fetching (signed URL + possible Cloudflare challenge) behaves
  the same as the channel-page samples above is **still unconfirmed**,
  same real-browser check needed, not attempted in this pass.

  **Clarifying the user's third ask ("use it for... AI transcription
  requests") — this is not a separate blocker from the captions one,
  it's the same one.** On-demand Whisper transcription needs a real
  probeable audio/video *file* URL (what `probe_duration()`/
  `extract_chunk_audio()` work against for every other platform), and
  Vimeo doesn't expose that any more directly than it exposes captions —
  both live behind the same signed `player.vimeo.com/video/{id}/config`
  response the entry above already found returns a plain **403** to a
  non-browser request. So "embed the video" (needs a new Vimeo
  player/iframe integration, `app/static/player.js` has none today) and
  "captions + AI-transcription audio" (both need getting past the same
  signed-config/Cloudflare wall) are two separate pieces of work, not
  three — worth keeping that framing when this eventually gets built,
  so the audio-extraction piece isn't accidentally re-investigated as if
  it were a new, unrelated problem.

  **Fourth confirmed example, same day**:
  [?meetingId=DF5C52EA-0D6B-F111-A823-001DD8019941](https://chicityclerkelms.chicago.gov/Meeting/?meetingId=DF5C52EA-0D6B-F111-A823-001DD8019941)
  → `videoLink: ["https://vimeo.com/showcase/citycouncil?video=1209979957"]`
  — full "City Council" body this time (not a committee), and notably
  the showcase identifier is a human slug (`citycouncil`) rather than
  the numeric one (`8925576`) from the Budget committee example above —
  confirms the `vimeo.com/showcase/{slug-or-id}?video={id}` shape holds
  across different showcase-ID styles, not just one body's own naming.

  **Update 2026-08-13: a fifth real example, and a third distinct URL
  shape — user-confirmed at
  [cityofsebastopol.gov/events/city-council-meeting-january-6-2026/](https://www.cityofsebastopol.gov/events/city-council-meeting-january-6-2026/).**
  A plain top-level `vimeo.com/{id}/{privacy-hash}?fl=sm&fe=ec` link
  (`https://vimeo.com/1152708575/db9859a2aa?fl=sm&fe=ec`) — different
  from both the channel-page shape (Salisbury/Rockland/Spokane/
  Corvallis/Wilson) and the showcase shape (Chicago ELMS). This is a
  WordPress city-events page hit through `generic_fallback.py`, not a
  dedicated adapter, and unlike Chicago's client-injected `videoLink`,
  the Vimeo link here is server-rendered as a plain `<a href>` (confirmed
  via WebFetch of the raw page) — so once general Vimeo playback support
  exists, `generic_fallback.py`'s existing "any known-platform link on
  the page" scan (`_try_delegate_to_known_platform()`) would likely pick
  this one up for free, no page-specific work needed. Whether this
  specific privacy-hash'd URL shape has a fetchable signed caption URL
  the same way the channel-page samples did is unconfirmed — no
  real-browser check attempted yet for this one. Same underlying blocker
  as the rest of this entry: no Vimeo playback/caption support exists in
  this app today.

- **[HUMAN] Phoenix's Legistar instance (`phoenix.legistar.com`) — root cause
  now confirmed structural, not one ambiguous sample.** Domain routing
  itself is confirmed correct (`phoenix.legistar.com` matches
  `_is_legistar_domain()`, so `LegistarAssetFinder` claims it as
  intended, not a routing bug). Original check (2026-08-10,
  `MeetingDetail.aspx?ID=1425831...`) found a `videolink` anchor with no
  `onclick` at all, `data-running-text="In progress"` despite being over
  a month stale — ambiguous at the time. **A 2026-08-11 Wave 2 survey
  resolved the ambiguity: 18 real Phoenix Legistar meetings checked
  (Formal Meetings, Policy Sessions, a Subcommittee), spanning
  2020–2026, every single one server-renders
  `class="audioDownloadNotAvailableLink"` / "Not Available" for video —
  and the original ID=1425831 URL now 410 Gones entirely.** This is
  Phoenix-wide, not one meeting's quirk. The real recordings exist and
  are public — just never linked from Legistar's own page — on Phoenix's
  own YouTube channel instead (e.g. `youtube.com/watch?v=srjuXI5vGuw`,
  confirmed live, "Phoenix City Council Formal Meeting July 1, 2026",
  matching the same meeting ID=1425831 was for). **Independently, the
  same symptom — Legistar video column always empty, real recording
  only on a separate city YouTube channel — was also found on
  Philadelphia (`phila.legistar.com`) and Albuquerque
  (`cabq.legistar.com`'s "GOV TV" channel)** during the same survey, so
  this may be a general "Legistar city with a non-Granicus video vendor"
  case worth handling once, not three separate one-offs. **The fix is
  not a Legistar parser change** (there is nothing in the page to parse
  differently — the video link genuinely isn't there) **but a
  YouTube-channel search/match fallback** for Legistar cities where the
  video link is absent: given a known channel + the meeting's date/title,
  find the matching upload. Needs a product decision on how that channel
  gets configured per city (hardcoded per the size/political-importance
  of Phoenix specifically, per the user's own suggestion, vs. a general
  mechanism) before writing it. Also worth noting while checking:
  Legistar's own adapter never attempts agenda-item parsing at all (by
  design, it only ever delegates to the underlying video platform for
  that), so a Legistar page never showing agenda items is expected
  behavior, not a second bug to chase.

### Dormant / needs a real example

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

~~**[LATER] Hyland "OnBase Agenda Online" — new platform, not supported at all
  today.**~~ **Built 2026-08-16 — new `app/platforms/hyland.py`, full
  detail in `BACKLOG_DONE.md`.** Grew same-day from the initial 3
  customers (Tucson AZ, Maricopa County AZ, Sacramento County CA) to
  **26 real customer domains** across two distinct UI versions, plus
  YouTube-embed delegation for customers whose player isn't JW Player —
  see `BACKLOG_DONE.md`'s "expanded from 3 to 23" entry (title now
  understates the final count; not renamed so the entry's own history
  stays legible) for the full discovery-methodology writeup, and
  `~/Documents/rtr-business/research/HYLAND_DISCOVERY.md` for the
  reusable enumeration/search playbook this produced.

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

  **Re-checked live 2026-08-14 after a user report that jurisdiction
  "still doesn't grab" here — doesn't reproduce.** Live-replayed this
  exact URL just now: jurisdiction renders correctly as "Sebastopol, CA"
  on its own line under the title, exactly the sitewide convention, plus
  the video pointer described above. Worth a straight correction rather
  than a new bug entry — this page appears to already be working as
  intended on both fronts described in this update; if the user still
  sees it missing, worth comparing browser/cache state rather than
  assuming a live regression, since this exact URL just resolved clean.

- ~~**CHAMP/ChampDS (`play.champds.com`) — new platform, not supported at
  all today**~~ **Built 2026-08-13 — full detail in `BACKLOG_DONE.md`.**
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

  **Still blocked on the same foundational gap already flagged for
  Chicago ELMS above**: this app has zero Vimeo playback support today
  (no adapter, no frontend player integration) — building real support
  for any of this needs that piece regardless of how the specific video
  gets found. A per-showcase video list (real titles/dates per meeting)
  wasn't confirmed either — `vimeo.com/showcase/{id}` pages are
  JS-rendered (confirmed: `curl` returns only the showcase's own title,
  no individual video data), so listing real per-meeting entries would
  need either Vimeo's own API or a headless-browser fetch, not yet
  checked which.

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
  - **A real "Meeting Items" table** (`File #`, `Agenda #`, `Type`,
    `Title`, columns) with substantive per-item text — e.g. this meeting's
    real items were "Canvassing, declaring, and adopting the results of
    the Primary Election held on July 21, 2026... Resolution No. 12562"
    and a development-agreement resolution for "an AC Hotel by Marriott."
    Doesn't cleanly fit `agenda_items` (typed `List[TranscriptSegment]` —
    real per-item *timestamps*, like Granicus's AgendaViewer.php chapter
    markers) since Legistar's table has no per-item time offset, only
    ordering. **User's call 2026-08-12, after weighing the shape
    mismatch: probably not worth pursuing** — the real agenda document
    (`agenda_link`, above) already covers the "what was on the agenda"
    need without a new untimed-items shape just for this one platform.
    Left here for context, not as an open TODO.

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

- **[LATER] YouTube/PrimeGov: non-English captions untested**, and it's unknown
  whether the manual-vs-auto-generated track coverage gap seen on the one
  real LA sample (see [BACKLOG_DONE.md](BACKLOG_DONE.md)) is typical or
  specific to that video. Two tangential non-English-caption leads found
  2026-08-11 (see below), neither on YouTube/PrimeGov itself: Riverside
  County CA runs a parallel `board-supervisors-meeting-videos-spanish`
  page, and a third-party Internet Archive mirror of Virginia Beach
  council meetings (`archive.org/details/covbva-*`) carries real
  `.es.asr.srt` files alongside the English ones.

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
  - **Video-only best-effort results are never archived** — the push
    gate (`app/main.py`, `segments or agenda_items or agenda_link`)
    predates the rebuild, but matters more now that the fallback finds
    more videos: e.g. a Tarrant resolve on Render (yt-dlp blocked → no
    segments; no agenda `<a>` on the page) produces a real video no
    permanent page will record. Deliberately not widened — the gate's
    junk-page rationale stands — but worth revisiting if pointer/video-
    only pages turn out to be worth archiving.
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

- **[LATER] Castus has zero support anywhere in the resolver — first real
  signal it exists in the wild, from the `rtr-business/research`
  government-first coverage-map crawl (2026-08-18).** Not in
  `detect_platform()` (`app/platforms/base.py`), no adapter file, not in
  `generic_fallback.py`'s curated-pointer list — genuinely unhandled, not
  just unbuilt. 1 hit (`castus`) out of a 200-row national-ish sample of
  `.gov` city/county homepages (`dotgov_probe.py`'s fingerprint list,
  extrapolated in `discover_from_dotgov.sh`'s `coverage_map.csv`) — too
  small an n to size the opportunity yet (the full ~9,766-row run this
  checkpoint fed into will give a real count), but confirms Castus is a
  real, in-use PEG/government-access video platform worth a first look
  once a real customer URL is in hand, the same "test against a real live
  URL first" rule this file's own working conventions require for any
  new adapter. **A real customer URL is now in hand** (2026-08-21, via
  the destinyhosted.com enumeration — see BACKLOG_DONE.md): destinyhosted
  tenant id=24568 links to
  `https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d?page=HOME`
  — jurisdiction not independently confirmed (destinyhosted's own
  `/{code}docs/` folder-name convention suggests `bilmt`, but that wasn't
  cross-checked against real page text, so treat as unconfirmed). Not
  investigated further this session — still the first real lead to build
  an adapter against, not a build.

- **[LATER] Vimeo's real-world prevalence among small local governments is
  now quantified for the first time — worth deciding if the existing
  pointer-only handling is enough (2026-08-18).** Not an "add support"
  gap the way Castus is: Vimeo is already recognized, but only via
  `generic_fallback.py`'s curated pointer-link detector
  (`_VIMEO_VIDEO_LINK_RE`, numeric video-id and `showcase/` links only) —
  not in `detect_platform()`'s dispatch table, and with no Vimeo-native
  caption/transcript extraction (unlike Granicus/Swagit/etc., which parse
  the platform's own caption format). The same 200-row dotgov coverage-map
  checkpoint found 6/200 Vimeo fingerprint hits — extrapolated (not
  confirmed) to roughly 290 jurisdictions nationally at that rate, which
  would make Vimeo a meaningfully larger population than several platforms
  that already have dedicated adapters. Worth revisiting once the full
  ~9,766-row run gives a real national count: if it holds up, decide
  whether generic_fallback's pointer-only handling is sufficient at that
  scale or whether native Vimeo caption support (if Vimeo's oEmbed/API
  exposes captions — unconfirmed either way, no adapter work has looked at
  this) is worth building.

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

## Archive roadmap

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

**Architectural context:** anything about content/audience rather than
resolving (permanent pages, search, accounts/billing, email alerts, the
transcription crawler) grows in a **separate app** ("the Archive"), not this
resolver — see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full reasoning.
The resolver/Archive seam is `get_cached_resolution`/`log_resolution` in
`app/db/crud.py` plus `archive_client.lookup()`/`.push()`.

- **[IMPROVEMENT-ROUND] Accounts + token billing — scoping started 2026-08-10, per the
  user's explicit go-ahead ("start scoping," not "start building").
  Phase 1 build actually started the same day, on a dedicated branch
  (`accounts-clerk-phase1`) — see below.** Needed for paid features
  (already alluded to in adapter warning messages) and as a
  prerequisite for email alerts below.

  **Auth pivot, same day: Clerk, not a hand-rolled internal auth
  system.** The paragraph below (passwordless magic-link + a
  self-issued `AccountSession` cookie) was the original design and is
  now **superseded** — the user explicitly weighed the tradeoff
  ("I'm kind of leaning away from becoming a security expert") and
  chose a third-party auth provider instead. Real reasons, not just
  preference: Clerk gives prebuilt login UI, session handling, and
  built-in account-deletion flows for free; it keeps user email/PII
  entirely off this app's own database (a real privacy-posture
  improvement — the new `SavedItem` table is keyed only by Clerk's
  opaque user id, never an email); and its session JWT can be verified
  **locally by both services independently** (no shared signing secret
  to manage, no internal HTTP round-trip needed to check "is this
  visitor logged in" on the hot-path pages), which turned out to be a
  *simpler* fit for this app's two-separate-databases architecture than
  the original self-issued-cookie design, not just a safer one. Stripe
  (for billing, phase 5 below) and Resend (email) are unchanged.

  **Phase 1 scope, decided via direct questions, unchanged by the Clerk
  pivot:** accounts + saving meetings/searches to your own account
  only — no public profile pages, no visibility toggles, no posts/
  reposts, no subscriptions/notifications, no billing yet. Account
  creation auto-subscribes to the existing Resend newsletter audience
  (via a `user.created` Clerk webhook). A **non-goal, explicitly
  designed and tested for**: nothing existing is gated behind login —
  every route works identically for an anonymous visitor; the only
  changes are purely additive "Save this meeting"/"Save this search"
  buttons that appear if (and only if) a real session is present.

  New table: `SavedItem` (`clerk_user_id`, `item_type` —
  `saved_meeting`/`saved_search` — `meeting_page_id` nullable FK,
  `search_params` nullable JSON, `created_at`) in `archive/db/models.py`
  — stays in Archive's DB (not `app/db`) since it needs a real
  same-database FK to `MeetingPage.id`. No `Account`/`AccountSession`
  tables at all anymore — Clerk owns that state entirely.

  **Status as of 2026-08-11: merged to `main` and live in production**
  (PR #5), on a real Clerk **production** instance (custom-domain DNS
  verified in Namecheap, Google OAuth credentials configured) rather
  than the development instance staging used. Getting production
  actually working surfaced three real bugs, all found via live
  production debugging and now fixed — see BACKLOG_DONE.md's
  "Clerk production cutover" entry for the full incident writeup
  (base64 padding, a CSS specificity bug, and a malformed
  `CLERK_JWT_KEY`). All routes/tables/webhook/frontend wiring built,
  413 tests passing. Live-verified end to end on production with the
  user's own real account: sign-up (both Google OAuth and email-code),
  session verification, and `/account/saved` correctly showing saved
  items instead of the signed-out prompt. A follow-up UI polish pass
  (nav, button sizing/prominence, `/account/saved` layout, a bookmark
  icon next to the meeting title) landed the same day as the merge,
  live-verified locally first.

  **Second round, same day: a large backlog-cleanup pass surfaced
  several more real UI/UX bugs and a sign-in/sign-out redirect saga**
  (nav "Sign in"/"Get Updates" flash-on-load, saved-search filter
  display, meeting-row title wrap, a source-transcript disclaimer with
  a pop/glow pointer, and — after three rounds of Clerk's own
  documented redirect options proved unreliable live — a client-side
  forced-return safety net in `shared_static/clerk_nav.js`, plus
  dropping the transcribe-form's inline sign-in shortcut entirely per
  the user's call once that saga made clear it wasn't worth the
  complexity there specifically). See BACKLOG_DONE.md for the full
  detail on each. 425 tests passing.

  **Explicitly deferred, by the user's own call: the `user.deleted`
  webhook → `saved_items` purge (the right-to-deletion cascade) has
  never actually been fired/verified end-to-end.** The code path exists
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

  **Original design below, kept for its still-valid parts.** The auth-
  mechanism paragraph immediately following this one is superseded (see
  above); the `Note`/`NoteSubscription` social-layer design, the phased
  plan, and the open questions still describe the real plan for phases
  2+ once phase 1 ships.

  ~~**Proposed auth mechanism: passwordless, email-only — not round 1's
  Google OAuth/JWT.** `archive/utils/email.py` already has a working,
  live-verified confirm-by-email pattern (`send_confirmation_email()` +
  `TranscriptionJob.confirmation_token`, built for on-demand
  transcription) — accounts should extend this exact mechanism (a magic
  link, one-time token, no password ever stored) rather than
  introducing a second, heavier auth system. Matches `CLAUDE.md`'s own
  framing of round 1's real mistake: building full auth/accounts before
  validating the core feature, not that accounts themselves were wrong
  — the fix isn't "build auth more carefully," it's "build the smallest
  auth that actually works," and this app already has proof that
  pattern works (Resend audience-membership skip-confirmation is
  already live and confirmed working end-to-end). Session: a signed,
  httponly cookie holding an opaque session id checked against a new
  `AccountSession` row — no JWT needed, since this is one service
  issuing and checking its own sessions, not a distributed multi-service
  handoff.~~ Superseded by the Clerk pivot above.

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

  **On-demand transcription's email-only gate is a deliberate middle path,
  not a stepping-stone toward eventually requiring a full account —
  explicit user correction, 2026-08-12.** Transcription is still the app's
  single most cost-intensive feature by a wide margin (see "On-demand
  transcription" below for real dollar/compute figures), and email
  confirmation was chosen specifically as real friction against abuse
  without forcing a login onto the app's costliest path. Keep it this way
  going forward rather than treating it as an implicit TODO to fully
  account-gate later.

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
  see "Deep links" section above), not just the meeting as a whole. This
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
- ~~**Smaller, near-term polish request (2026-08-15) for the "Every place
  we've covered" table that already shipped**~~ **Fixed 2026-08-16, wave
  2 item 9 — full detail in `BACKLOG_DONE.md`.** Distinct from the bigger
  sortable/filterable redesign above, which is still unbuilt. All three
  original asks landed in `archive/templates/coverage.html` + new
  `archive/static/coverage.js` + `style.css`: a frozen (`position:
  sticky; left: 0`) leftmost row-number column in a lighter font-weight,
  clickable Government/Example meeting/Transcript headers that sort the
  table (repeat click toggles ascending/descending, "Transcript" sorts by
  badge presence), and row numbers that renumber to the sorted display
  order rather than staying tied to the original alphabetical rows.
  Verified live in-browser (sort-by-click + sticky column both confirmed
  against a locally-seeded table), not just against the test suite.
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

## On-demand transcription — real gaps left open

- **`list_transcription_backlog_candidates()` still does a real N+1 query
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
  own scheduled workflow (added the same day, see the entry below) where
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

- **Worker daily activity report, added 2026-08-21.** `GET /internal/
  send-worker-daily-report` (Archive service) emails a 24h digest
  (chunks completed, jobs finished, segments transcribed) plus a current-
  queue snapshot (active jobs, remaining chunks, meetings with no
  transcript, tier-3 queue remaining) — see README.md's matching entry
  for the full design and why it needed one new table
  (`WorkerReportSnapshot`, a single overwritten row) rather than a Render
  log-parsing script: `chunks_completed` has no per-chunk timestamp
  anywhere in the schema, so a real 24h delta needs *some* stored
  reference point, and diffing against a DB snapshot avoids introducing
  a brand-new Render API key + log-pagination dependency this repo
  doesn't otherwise have, for a number that's already implicit in
  existing columns. Triggered by `.github/workflows/
  worker-daily-report.yml`, a plain `curl` ping — same "GitHub Actions
  never touches Resend credentials directly" pattern
  `/admin/send-search-alerts` already established, not a new script with
  its own copy of `RESEND_API_KEY`.

  **First real manual trigger (same day) found a real bug the test suite
  couldn't catch**: `crud.get_transcription_queue_summary()`'s
  `segments_added_last_24h` query used `jsonb_array_length()`, but
  `TranscriptVersion.segments` is a plain SQLAlchemy `JSON` column
  (Postgres `json`, not `jsonb`) — a real 500 in production,
  `UndefinedFunctionError: function jsonb_array_length(json) does not
  exist`. Fixed to `json_array_length()`. This specific branch is
  Postgres-only and dialect-gated to `None` on SQLite by design, so
  nothing in `tests/test_worker_daily_report.py` (SQLite fixture DB)
  could have caught it — the mistake only surfaced by actually curling
  the route against real production, confirming this file's own "verify
  against a real case, don't guess" convention applies to reporting
  endpoints too, not just adapters.

  **Live-verified working end to end after the fix, 2026-08-21, same
  day**: real manual trigger (`workflow_dispatch`) against production
  returned `{"sent": true, "summary": {"active_jobs": 1,
  "remaining_chunks_in_active_jobs": 1,
  "cumulative_chunks_completed_all_time": 2986,
  "cumulative_jobs_completed_all_time": 281, "jobs_completed_last_24h":
  34, "segments_added_last_24h": 90441, "backlog_no_transcript": 638,
  "tier3_queue_remaining": 1630}}` — a real Resend send, real numbers,
  `json_array_length` computing correctly. First scheduled run is
  23:40 UTC tonight; this manual trigger already exercised the exact
  same code path, so that run is expected to succeed too, not a new
  unknown.

- **Second transcription worker added for backlog catch-up, 2026-08-21 —
  residual auto-gen TOCTOU gap now recorded, not fixed at the DB layer.**
  `render.yaml` now defines a second `type: worker` service
  (`rtr-transcription-worker-2`) alongside the original, to work down the
  ~1600+ archived-but-untranscribed meeting backlog faster. It's a real,
  distinct service block (not `numInstances` on the original) specifically
  because Render gives every `numInstances` replica of one service block
  IDENTICAL env vars, and this pair needs to differ in exactly one:
  `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` is deliberately left unset on the
  new service.

  **Why that one omission matters.** `claim_next_chunk()`
  (`archive/db/crud.py`) already uses `FOR UPDATE SKIP LOCKED` and is
  genuinely safe for any number of concurrent worker processes — confirmed
  by reading its own docstring, no code change needed there. The real,
  separate race lives in idle-time auto-generation:
  `maybe_generate_auto_job()` → `find_auto_transcription_candidate()` (a
  plain, unlocked SELECT) → `create_transcription_job()`'s own separate,
  unlocked "does an active job already exist for this page" check-then-
  insert, no unique constraint or row lock guarding it. Two worker
  processes both idle at the same moment — which happens routinely once
  the queue trickles down to empty — and both configured with a real
  `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` could both pass that check for the
  same candidate page before either commits, creating two duplicate
  low-priority jobs. Confirmed downstream cost: `report_chunk_result()`'s
  completion path creates a new `TranscriptVersion` with no content-hash
  dedup against a same-source in-flight duplicate (unlike `/internal/
  ingest`'s push path, which does dedupe by hash) — real wasted compute
  and two completion emails, though `promote_transcript_version()` still
  cleanly settles on one final default version, so it's wasteful, not
  data-corrupting.

  **This is avoided by construction here, not fixed at the DB layer**:
  leaving `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` unset on the second worker
  means its own `maybe_generate_auto_job()` always short-circuits
  (`worker/main.py`, `if not AUTO_TRANSCRIPTION_REQUESTER_EMAIL: return
  False`) and never reaches `create_transcription_job()` — the race is
  structurally impossible on this specific pair. **A future third
  auto-gen-enabled worker (or setting that var on this second one) would
  reintroduce it immediately** — the real fix, if this pattern needs to
  scale past two workers, is a unique partial index / row lock in
  `create_transcription_job()`'s existing-job check, not another
  env-var-omission trick. Not built now since it's not needed at N=2 with
  this specific split.

  **Bulk backlog concurrency**: `scripts/bulk_queue_transcription_
  backlog.py` (new) pulls candidates from the existing `GET /internal/
  transcription-backlog` and creates up to 8 `TranscriptionJob` rows per
  run via `POST /internal/transcription/create-job` at the newly-exposed
  `priority=PRIORITY_LOW` (that field was added to
  `TranscriptionCreateJobRequest` — previously only `worker/main.py`'s own
  direct in-process call could ever use that tier). 8, not closer to
  `MAX_CONCURRENT_TRANSCRIPTION_JOBS=15`, deliberately leaves ~7 slots free
  so a real live visitor's own transcription request never hits
  `too_many_active_jobs` during the catch-up window, and LOW priority
  means any such real request still jumps the queue ahead of already-queued
  backlog jobs at the very next claim, regardless of how full the batch is.
  **Live-verified 2026-08-21, same day**: a manual run against production
  created 4 brand-new jobs (482/483/484/485) and correctly deduped a 5th
  candidate onto an already-in-progress job (476) instead of duplicating
  it; watching both workers' real Render logs directly confirmed the
  no-collision design end to end — worker-2 claimed job 476's chunk 4,
  hit a real (unrelated) ffmpeg timeout, released the claim, and worker-1
  picked up the same chunk 3 seconds later and completed it; worker-2 then
  picked up newly-created job 482 once the manual push landed. Two
  distinct `job_id`s `in_progress` at once, confirmed live, not just in
  theory.

  **Runs hourly now, not manually**: `.github/workflows/bulk-queue-
  transcription-backlog.yml` (added 2026-08-21, same day) — the first
  manual run above also confirmed worker-2 sits genuinely idle for
  multi-minute stretches between whenever someone happens to re-run this
  by hand, which defeats the point of having a second worker. Hourly is
  safe because of the same two properties noted above:
  `create_transcription_job()`'s server-side dedup (a page with an
  already-active job is a no-op, not a duplicate) and the
  `too_many_active_jobs` early-stop, so this can't pile up an
  ever-growing queue between runs. New repo secret:
  `AUTO_TRANSCRIPTION_REQUESTER_EMAIL` (Settings → Secrets and variables
  → Actions), same address as the Render-side env var of the same name.
  Tied to the backlog catch-up window this second worker exists for —
  revisit the cadence (or disable the workflow) once this backlog figure
  is worked down.

- **Tier-3 feed rate raised to match real two-worker throughput,
  2026-08-21 — real measurements, not a guess.** Real scope, checked
  live: 644 meetings on the site have no transcript
  (`/meetings?has_transcript=false`, paged through in full), 562 of
  those are currently eligible candidates (447 HLS, 91 direct MP4, 20
  YouTube — only ~3.6% blocked on the separate residential-IP caption
  path, 3 MP3), and a separate 1,630-URL tier-3 *discovery* queue
  (`scripts/tier3_auto_transcription_queue.txt`) hadn't even reached the
  Archive yet. At the old feed rate (12 pages/6h = 48/day,
  `feed_tier3_auto_transcription.py`), draining that 1,630-entry queue
  would've taken **~34 days** just to get the pages *into* the Archive —
  regardless of how fast either worker could transcribe, since a page
  isn't a transcription candidate until it's a real `MeetingPage` row.
  Meanwhile real production measurements the same day showed each
  worker processing a real 900s chunk in ~180-200s (**~5x realtime**,
  ~10x combined for both), and a real 25-page sample of this exact queue
  averaged ~70 minutes/meeting at an 88% feasibility rate — so the old
  feed rate was the actual bottleneck, not worker capacity, by roughly
  4-5x. Raised `BATCH_SIZE` 12 → 48 (192/day) in
  `feed_tier3_auto_transcription.py` — sized to roughly match, not
  wildly exceed, the two workers' real combined throughput; see that
  script's own docstring for the full math. Estimated result: ~8.5 days
  to feed the full 1,630-entry queue at the new rate, with the two
  workers keeping pace with it rather than idling on a starved queue —
  call it **~9-10 days for the whole combined backlog** (644 already-live
  + 1,630 tier-3) at current throughput, not the ~34+ days the old
  mismatch implied. Real quality caveat carried over from the "tiny"
  model findings above still applies to all of this — quantity isn't the
  only axis that matters here, and speed doesn't change the existing
  quality tradeoffs already documented. Revisit if either side's real
  throughput changes materially (worker plan/model-size/count change, or
  this platform mix's real average duration turning out different at a
  larger sample size).

- ~~**[JUST-DO-IT] `find_auto_transcription_candidate()` streams the
  entire transcript corpus through the DB every 5 idle minutes — an N+1
  that loads full `segments` JSON per page.**~~ **Fixed 2026-08-17 (same
  day it was found) — full detail in `BACKLOG_DONE.md`'s "Worker
  auto-transcription candidate sweep" entry.** Short version: `pg_stat_
  statements` showed `_has_good_transcript()`'s full-entity select
  (segments JSON included) as the **#1 consumer of production DB time**
  (218,480 calls, 47 min); the sweep now runs as one `NOT EXISTS`
  candidate query over `content_hash`/`transcript_warnings` (never
  `segments`) plus one status/updated_at history query, then the
  unchanged cooldown rule in Python — verified on real Postgres as a
  Hash Anti Join touching 8 buffers where it used to move 102MB.
  `_has_good_transcript()` and `_in_auto_transcription_cooldown()` (which
  was also dragging `TranscriptionJob.partial_segments` along) are fixed
  for their other callers too. **What this fix does NOT claim**: that the
  sweep was the search-latency contention — see the search entry; the
  `pg_stat_statements` answer there is that the app's own LIKE scans
  average 16.5s each on this I/O-starved DB, so removing the sweep helps
  the DB generally but is not the search fix.
  **Related, same `pg_stat_statements` read — a house-rule finding, not
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

Built 2026-08-08, see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full
build/verification detail. First real deploy attempt (also 2026-08-08)
immediately crash-looped on a missing `pydantic` dependency in
`worker/requirements.txt` — fixed, and see that same file's follow-up
entry for the methodology lesson (a shared local dev venv can hide a
missing-package bug that only surfaces once a service is actually
deployed with its own real, isolated dependency set). Confirmed by that
same deploy: `worker/Dockerfile` **does** build successfully on Render —
one item below is resolved as a result.

- **[DONE?] ~~ffmpeg/ffprobe availability on the resolver service is
  unverified.~~ Confirmed live 2026-08-08.** A real `POST` to
  `/api/transcription/check-feasibility` against a live Granicus URL
  returned `{"ok": true, "duration_seconds": 27073.36, ...}` — the plain
  `runtime: python` Render buildpack already has `ffprobe` on `PATH`, no
  `runtime: docker` switch needed after all.
- **[DONE?] ~~Render worker plan sizing is a guess.~~ Resolved for real 2026-08-08,
  after two live crashes, not one.** First real deploy OOM-killed on
  `plan: starter` (512MB) loading the original `"small"` model default.
  Switched to `"tiny"`, sized from local measurement -- but that
  measurement was only against a ~9-second synthetic clip (~382MB), and
  the **second** real deploy OOM-killed too, on a genuine 900-second
  (15-minute) real meeting chunk. Real lesson, not just a bigger number:
  `faster-whisper`'s memory usage scales substantially with audio
  *duration*, not just model size -- a short-clip measurement was
  actively misleading. Real curve, measured directly against real
  Fountain Valley clip 607 audio, `"tiny"` model, one duration per
  process:

  | duration | peak RSS |
  |---|---|
  | 0s (imports only, no model) | ~67MB |
  | ~9s (synthetic) | ~382MB |
  | 60s | ~454MB |
  | 180s | ~615MB |
  | 300s | ~814MB |
  | 900s (the real chunk size that crashed) | ~1421MB |

  Even 60s only clears 512MB by ~58MB -- too thin to trust, and shrinking
  further toward "safe" starts costing a full adapter re-resolve (RSS
  feed, agenda viewer, etc.) every ~30-45 seconds of audio, which is both
  slow and a real risk of getting rate-limited by the government source
  for hammering it that often. **Resolution: upgraded the worker's Render
  plan to Standard (2GB RAM, $25/mo)**, not shrinking chunks further --
  `900s` chunks at ~1421MB fit that with real (~600MB) margin, confirmed
  by the measurement above, not another guess. `TRANSCRIPTION_CHUNK_SIZE_
  SECONDS` (`app/main.py`) never needed to change once the plan did.

  **`"tiny"`'s real quality against actual meeting audio: assessed
  2026-08-08, real errors found, not just "approximate but fine."** Job 1
  (Cupertino, 2 chunks) completed successfully end-to-end and was mostly
  accurate on substance (real terms like "Form 8038-G" came through
  correctly), but a full read-through of the transcript found two
  distinct real problems, not hypothetical ones:
  - **A meaning-changing mistranscription**, not just noise: `"Okay, so
    that, that is this meeting, this meeting is a joke."` at 25:28 --
    almost certainly "this meeting is adjourned," misheard as "a joke."
    Puts a fabricated sentence in a real named official's mouth on a
    permanent public page — a real reputational-risk failure mode, not
    just lower search-match quality.
  - **A hallucination loop**: `"If it doesn't jump."` repeated five times
    in a row at 22:34-22:43 — a known Whisper failure mode where the
    model free-associates on quiet/unclear audio instead of stopping,
    not a real utterance at all.

  Two fixes made in response (2026-08-08): (1) a visible disclaimer now
  renders on any `source="transcribed"` version (`archive/templates/
  meeting_page.html`) — previously **no UI anywhere distinguished a
  self-transcribed version from a real scraped caption**, so a
  hallucinated sentence like the one above read exactly as authoritative
  as an official caption; (2) `worker/transcription_engine.py` now passes
  a short government-meeting-vocabulary `initial_prompt` to
  `faster-whisper` (explicitly includes "adjourned"), aimed at exactly
  this failure mode. Neither fix is a guarantee — worth re-checking
  quality on the next real job now that the prompt's in place, same as
  this check was itself the first real one. `"base"`'s real memory curve
  at realistic chunk durations
  (as opposed to the same misleadingly-short 9s clip that under-predicted
  `"tiny"`'s real cost) is still unmeasured -- deliberately not attempted
  in the same pass as the plan upgrade, to change one variable at a time
  after two live crashes. Worth a real `"base"`-at-900s measurement as
  its own follow-up once `"tiny"` is confirmed working end-to-end on the
  new plan, not stacked on top of an unconfirmed fix.

  **A second, distinct manifestation of the same hallucination failure
  mode found live 2026-08-12** (County of Napa, Board of Supervisors
  2026-06-02:
  [/m/county-of-napa-2026-06-02-board-of-supervisors-on-2026-06-02-9-00-am-final-suppl](https://redtaperecordings.com/m/county-of-napa-2026-06-02-board-of-supervisors-on-2026-06-02-9-00-am-final-suppl)),
  reported by the user as "meeting is in English but the transcript is in
  Spanish." Read through the actual segments: the meeting genuinely is in
  English throughout (real content from ~9:02 onward, e.g. a whole LGBTQ+
  Pride Month proclamation, transcribes correctly) — the `en (transcribed)`
  label itself is correct, langdetect isn't the bug here. The real defect
  sits earlier, 0:00–8:57: the transcript reads as a long stretch of
  "Testing one, two, three." repeated ~17 times, then several lines of
  fabricated Spanish-*looking* text with no real-world referent —
  `"donde es el de dependimiento no es todo eso es un futuro en la
  secuencia de una sección"`, `"¿Como se no le pumping? ¿Se puede ser un
  mal."` **Initially assumed (wrongly) to be Whisper free-associating over
  dead air/a mic test — corrected by the user 2026-08-12, who confirmed
  people are actually speaking real content throughout that whole
  stretch, i.e. this is ~0% transcription accuracy against real speech,
  not a quiet-audio hallucination loop.** That reopens the root-cause
  question rather than closing it: two real, untested possibilities, not
  one confirmed one —
  (1) genuinely poor source audio for this stretch specifically (heavy
  noise/echo/crosstalk/low mic gain) that the `"tiny"` model can't get a
  usable signal from even though real speech is present, or
  (2) an extraction bug: `extract_chunk_audio()`
  ([app/platforms/media_probe.py](app/platforms/media_probe.py)) pulling
  the wrong audio stream/offset/a corrupted segment for this specific
  chunk, so what Whisper actually receives for 0:00–8:57 doesn't
  faithfully represent the real speech happening in the source recording
  at all. **Neither is confirmed** — telling them apart needs someone to
  actually listen to the extracted chunk audio itself (not just read the
  transcript output, which is all that's been checked so far) against the
  real meeting recording for that same time range. The `vad_filter`
  fix proposed in the original write-up of this entry assumed silence and
  is likely the wrong fix if it's actually (1) or (2) — VAD only skips
  non-speech spans, so it wouldn't touch a chunk with continuous real
  speech in it. Don't build a fix here until the audio itself has been
  checked. Same "verify against a
  real example" convention as everywhere else in this file.

  **Update 2026-08-12: user has now listened to it directly — very clear
  audio, no noise/echo/crosstalk.** That rules out hypothesis (1)
  (genuinely poor source audio the model can't parse) and points at (2),
  an extraction bug specific to this chunk — though note the user listened
  to the source recording itself, not the transient chunk audio file
  `extract_chunk_audio()` actually hands to Whisper (deleted after
  processing, inside `worker/main.py`'s `tempfile.TemporaryDirectory`
  block — nothing to inspect after the fact today). Since the source is
  confirmed clean, the next real step if anyone picks this up is to
  reproduce one real chunk locally (same `extract_chunk_audio()` call,
  same 0:00–900s range, same real source URL) and actually listen to *that
  file* before it gets deleted — if it's also clean, the bug is in
  faster-whisper's handling of this chunk (parameters, first-chunk
  cold-start behavior, `MEETING_VOCABULARY_PROMPT` biasing it toward a
  wrong track somehow); if it's already corrupted/garbled/wrong-content at
  that point, the bug is in extraction (wrong stream, bad seek offset,
  transcoding artifact), not in Whisper at all.

  **Update 2026-08-12: reproduced directly, root cause is now a real,
  well-evidenced extraction bug, not a Whisper problem.** Ran the exact
  production media URL (`archive-stream.granicus.com/OnDemand/.../
  napa_10ae7709-....mp4/playlist.m3u8`, pulled from the live page's own
  embedded video URL) through the same `extract_chunk_audio()` ffmpeg
  invocation the worker uses, then transcribed the result with the same
  `faster-whisper` "tiny" model/prompt/`beam_size` `worker/
  transcription_engine.py` uses — this reproduced the *exact* reported
  symptom locally: "Testing one, two, three" (and the Spanish-sounding
  gibberish after it) from 0:00 through ~508s, then a clean, correct
  transition into the real Pride Month proclamation content around
  555–570s, matching the "~9:02" real-content start already reported live.
  Three concrete findings rule out both original hypotheses and point at a
  specific new one:
  - **Not silence/quiet audio**: `ffmpeg`'s `volumedetect` on the 0–508s
    "bad" region measured `mean_volume: -32.3 dB`, essentially identical
    to the confirmed-real-speech 570–600s region's `-31.3 dB` — real
    audio energy is present throughout, not silence a VAD filter would
    have caught.
  - **`ffmpeg` itself warns during extraction**, independent of `-ss`
    placement (reproduced identically with `-ss` before *and* after
    `-i`, ruling out a bad seek offset specifically): `"Queue input is
    backward in time"` / `"Application provided invalid, non
    monotonically increasing dts to muxer"`, repeated dozens of times —
    real evidence the underlying HLS segments this specific
    `archive-stream.granicus.com` "OnDemand" VOD serves have
    non-monotonic/overlapping timestamps, not that `extract_chunk_audio()`
    is asking for the wrong offset.
  - **The hallucinated phrase repeats at suspiciously mechanical ~30-second
    intervals** (0, 30, 60, 90, ... 480s — confirmed via local
    re-transcription, not eyeballed) — real organic speech doesn't repeat
    identically on a metronome; this is much more consistent with
    something in the HLS segment sequence itself looping or duplicating a
    short real segment (plausibly a genuine pre-broadcast mic-check
    recording — "Vamos a hacer una prueba... Testing one, two, three" is
    real, meaningful audio content, not noise) than with either a clean
    signal or true silence.

  **Update 2026-08-16: both the proposed ffmpeg fix and the underlying
  bug itself were tested for real, with a surprising result — there was
  never anything to fix in `extract_chunk_audio()` at all.** Three real
  checks, same production `archive-stream.granicus.com` URL as above,
  local ffmpeg 8.1.2 + the repo's own `faster-whisper==1.2.1` (no
  version pin exists in `worker/requirements.txt`, see below for why
  that matters):
  1. **`-fflags +genpts` (the proposed fix) does nothing** — reproduced
     the same "Queue input is backward in time" warnings with the flag
     present, identically to without it.
  2. **A different flag, `-af aresample=async=1`, does eliminate every
     warning — but changes nothing about the extracted audio itself.**
     Transcribing the warning-free output and the original
     warning-riddled output through the exact same `faster-whisper`
     "tiny"/prompt/`beam_size=5` config produced line-for-line identical
     transcripts (one trivial 2-second segment-boundary difference).
     The "non monotonically increasing dts" warnings are a cosmetic
     libmp3lame-muxer complaint about container-level timestamp
     metadata — they never affected which audio samples actually reach
     Whisper. There's no real bug in this function to fix.
  3. **The originally-reported symptom itself doesn't reproduce
     anymore.** Re-ran the *exact* repro from the 2026-08-12 update
     above (same URL, same single continuous 0–900s chunk, same model
     config) and got a single brief "Testing 1, 2, 3" at 0–15.7s,
     immediately followed by clean, correct, real content the rest of
     the way through 900s (a real Pledge of Allegiance, "Pet of the
     Week," and the full Pride Month proclamation, all transcribed
     accurately) — not the ~17x repeated "Testing 123" + fabricated
     Spanish gibberish through 508s originally reported. Most plausible
     explanation, not conclusively pinned down: `worker/requirements.txt`
     pins no version for `faster-whisper` (confirmed: bare `faster-whisper`
     line, no `==`), so every fresh build picks up whatever's newest at
     build time — a real possibility that an upstream release between
     2026-08-12 and now (repetition-loop hallucination is a known class
     of Whisper-family bug with a history of upstream fixes) already
     resolved this, not anything in this app's own code. Not chased
     further (would need pinning + testing multiple historical
     `faster-whisper` versions to confirm which release changed it,
     out of scope for closing this entry). **Closing as "no code fix
     needed, and the original symptom is unreproducible with today's
     dependencies"** rather than leaving a stale, disproven fix
     hypothesis open.
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
- **[DONE?] ~~Resend's contact-lookup-by-email endpoint is unverified.~~ Confirmed
  live 2026-08-08.** A real request from an existing newsletter subscriber
  (`mroconnell@gmail.com`) correctly skipped the confirm-by-email step and
  went straight to `queued` — proof `archive/utils/email.py`'s
  `check_audience_membership()` and Resend's `GET /audiences/{id}/
  contacts/{email}` endpoint shape both work as written, not just
  degrading safely on failure.
- **[DONE?] ~~Completion email's "share this" ask has no real "support us" CTA
  behind it~~ — moot as of 2026-08-11: the ask itself is gone.** The
  completion email's copy was fully rewritten that day to match
  `marketing/LIFECYCLE_EMAILS.md`'s approved "Your transcript's ready"
  copy (see the "Lifecycle-triggered transactional emails" entry above),
  which doesn't include a forward/share line at all. If a real "support
  us" ask gets built later (once accounts/billing exist — see "Archive
  roadmap" below), it'd need to be added back as new copy against that
  doc's now-current version, not restored as it was.
- **[DONE?] ~~A non-default `TranscriptVersion` is invisible to internal
  search~~ — fixed 2026-08-08.** Confirmed by reading the actual code,
  prompted by asking whether a scraped caption and an AI transcript
  could both be shown/found once a meeting has both. The version-picker
  UI already existed for *viewing* both (`archive/templates/
  meeting_page.html`'s `.version-picker`, a `?version=` link list, not JS
  tabs — `promote_transcript_version()` never deletes the version it
  demotes), but `archive/db/crud.py`'s `list_pages()` (the `/meetings`
  search backing) used to join `TranscriptVersion` filtered to
  `is_default.is_(True)` only, so a demoted version's text was never
  matched by a keyword search. Fixed: `list_pages()` now runs a second
  query (only when a keyword search is active, same as before) pulling
  *every* version's segments per candidate page, and matches against the
  concatenation of all of them — still one result row per page, not one
  per version, since a viewer searching `/meetings` wants to find the
  meeting, not pick a version from search results. The display-facing
  columns (language/has_transcript badge) are unchanged, still sourced
  from the default version only. Verified with a new test
  (`tests/test_list_pages_search.py`, real DB: ingest a version with a
  unique keyword, promote a second version over it demoting the first,
  confirm `list_pages(keyword=...)` still finds the page). Full suite
  green (116 tests).

  **The UX half shipped 2026-08-12, per the user's own simpler call —
  the SEO/external-search half is explicitly still open, by choice.**
  The user re-requested a real placement/interaction change (a picker
  near the Download Text/SRT links, not a separate block above the whole
  transcript section) and, when offered the bigger all-versions-in-DOM
  JS-tabs redesign originally proposed here, explicitly opted out of it:
  alternate versions don't need to be independently searchable, and
  don't need to track playback live without a reload. What shipped
  instead: `.version-picker` is now a `<select>` dropdown (a macro,
  `version_picker()`, in `meeting_page.html`) positioned inline with the
  Download line, submitting a plain GET form to `?version={id}` — the
  same full-page-reload-per-version mechanism as the old link list, just
  restyled and repositioned, so `data-version-id`/deep-link
  time-tracking against the newly active version work unchanged (no
  changes needed to `shared_static/deep_link.js` at all). Verified live:
  seeded a real two-version test page, confirmed the dropdown shows both
  versions, selecting the non-default one reloads to `?version=2` with
  that version's own segments, download links, and `data-version-id` all
  updating together. Full suite green (440 tests).

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

- **[IMPROVEMENT-ROUND] The transcription-request rate limit's copy is unfriendly/non-native-
  reading and misses an obvious account-creation opportunity — and
  logged-in users shouldn't be rate-limited at all, flagged 2026-08-15.**
  Real copy, both duplicated copies of the fix from the already-closed
  "misleading 429 message" entry above:
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
  in the Archive-roadmap accounts entry above: this same transcribe-form
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

- **[JUST-DO-IT] PrimeGov's private known-domain override can be absorbed into the
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

- **[IMPROVEMENT-ROUND] New feature request, 2026-08-16: a recurring operator email report
  every 6 hours, to `ryan@redtaperecordings.com`, with 6 metrics** —
  queued worker jobs, failed jobs in the last 48h, succeeded jobs in the
  last 48h, total meetings on site, meetings with a transcript, meetings
  without one. Note this is a **third** distinct "Ryan" address in play
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
  transcript counts. Confirmed no equivalent stats aggregator exists yet
  on the Archive side (`archive/db/crud.py` has no `get_stats()`-shaped
  function at all, unlike `app/db/crud.py`'s resolver-side one) — this
  would be new query code, not a wire-up of something already built,
  unlike most of this session's other easy-win items.

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

- **`detect_language_from_texts()` samples only the first 2000 characters
  of the merged transcript, so a bad start-of-meeting stretch can mislabel
  the whole page's language even when the rest is confidently English —
  confirmed live 2026-08-17/18 on two real pages from
  `scripts/transcribe_backlog_locally.py`'s local-Whisper batches.**
  `/m/meeting-00bbd1` (Lincoln City, OR): only chunk 1 of 5 came back
  low-confidence on Whisper's own per-chunk language guess (`cy` at 63%);
  chunks 2-5 were confident `en` (99-100%). `/m/meeting-d09fc0` (Moraine
  City, OH): the reverse pattern -- chunk 1 was confident `en` (100%), but
  chunks 2-8 (a genuinely very quiet ~1.8h recording, repeated
  "suspiciously quiet" ffmpeg warnings, several chunks under 30 segments
  for 15 minutes of audio) kept guessing `cy` at low confidence. Both
  pages still ended up with the whole meeting's `transcript_language`
  field set to `cy` (Welsh) in the final ingest. Root cause, confirmed by
  reading the code (not guessed): the per-chunk language values logged
  during transcription are Whisper's own internal guesses and are never
  used for the page-level language -- `transcribe_meeting()`
  (`scripts/transcribe_backlog_locally.py`) instead calls
  `detect_language_from_texts()` (`app/utils/vtt_parser.py`) on the full
  merged-and-sorted segment text, which joins every segment's text and
  hard-truncates to `[:2000]` characters before running `langdetect` on
  that sample alone -- there is no chunk-level voting or weighting
  anywhere in the pipeline. Since segments are sorted by start time, the
  first ~2000 characters are dominated by whatever is at the start of the
  meeting, so a bad opening stretch (dead air/music before the meeting is
  gaveled in, an invocation or proclamation genuinely in another
  language, or just a quiet/noisy chunk Whisper hallucinates
  foreign-looking text from) can single-handedly decide the label for a
  multi-hour, overwhelmingly-English meeting. This matches a real,
  recurring pattern in these sources per the user directly (2026-08-18):
  short (2-3 min) foreign-language stretches (proclamations, individual
  speakers) and dead-air/music (meeting start, or a recess in 4+ hour
  meetings) that Whisper isn't designed to handle well, embedded inside
  meetings that are otherwise clearly one language throughout. Worth
  fixing with a real per-chunk-text vote (or a length-weighted one) rather
  than "first 2000 characters of whatever comes first" -- `vtt_parser.py`'s
  function is shared with the scraped-caption adapters too, so check
  whether they have the same 2000-char-of-whichever-track-sorts-first
  exposure before changing it, not just the Whisper path.

- **[JUST-DO-IT] `detect_hallucination_warnings()`'s repetition check is
  diluted against total meeting length, so it structurally can't catch a
  real hallucination loop shorter than ~50% of a long meeting, no matter
  how blatant -- confirmed root cause (read the code, not guessed) plus
  six live, currently-undetected examples across five different meetings
  from this session's local-Whisper batches, on top of the already-fixed
  Port Coquitlam case (`BACKLOG_DONE.md`) this detector exists to catch.**
  None of the pages below show a hallucination warning; all were pushed
  live as normal, clean transcripts.

  **Root cause, confirmed by reading `worker/segment_utils.py`.**
  `_repetition_run_ratio()` finds the single longest run of consecutive
  near-duplicate segments (via `SequenceMatcher(...).ratio() >= 0.85`,
  which *does* handle minor text variation, not just byte-identical
  repeats -- an earlier draft of this entry wrongly assumed otherwise)
  and divides by the **total segment count of the entire meeting**, then
  flags only if that ratio is `>= 0.5`. That works fine for a short
  meeting where a loop dominates most of it (Port Coquitlam: 2 chunks,
  ~1572s total) -- but for any longer meeting, a loop has to eat *half the
  entire recording* to ever trip the threshold. A blatant, obviously-fake
  loop that's short relative to a multi-hour meeting mathematically
  cannot cross 0.5 no matter how repetitive it is locally. Confirmed
  numerically against three of the cases below: Moraine City's 93-cue
  Welsh loop is 38.6% of its (short, 241-cue) meeting -- close, but still
  under threshold; Cumberland County's 41-cue `"340,000,"` loop is only
  3.2% of its 1,291-cue meeting; Haines City's 7-cue *exact-repeat* loop
  (would trivially pass the 0.85 near-duplicate check on its own) is a
  mere 1.3% of its 525-cue meeting. The near-duplicate matching genuinely
  works -- the global-length dilution is what's actually broken.

  - **Hermosa Beach, CA** (`hermosa-beach-ca-2026-02-03-city-council`) --
    the worst case, two back-to-back loops. **`00:02:30` ->
    `01:30:00`** ([deep link](https://redtaperecordings.com/m/hermosa-beach-ca-2026-02-03-city-council?t=150))
    of 121 cues rotating between two differently-*length* phrasings of
    `"Local government meeting. Common terms..."` (their low
    cross-phrasing `SequenceMatcher` ratio, ~0.45, means this specific
    sub-loop evades even the near-duplicate check, not just the length
    dilution), immediately followed by **`01:00:30` -> `01:15:03`**
    of 176 consecutive cues reading just `"Music"` (Whisper's own
    non-speech tag, degenerately repeated once every ~5 seconds instead
    of emitted once) -- both inside the same bad stretch, before the real
    meeting abruptly starts at
    [`?t=5400`](https://redtaperecordings.com/m/hermosa-beach-ca-2026-02-03-city-council?t=5400)
    ("Good evening, everyone. And I called to order this February 3rd,
    2026 regular meeting..."). `language=en` and zero
    `transcript_warnings`, despite ~87 of this 6.14h meeting's first 90
    minutes being fabricated.
  - **Moraine City, OH** (`meeting-d09fc0`) -- roughly **`00:46:30` ->
    `01:46:21`** ([deep link](https://redtaperecordings.com/m/meeting-d09fc0?t=2790),
    real content resumes at
    [`?t=6381`](https://redtaperecordings.com/m/meeting-d09fc0?t=6381))
    of a genuinely very quiet ~1.8h recording (repeated "suspiciously
    quiet" ffmpeg warnings across nearly every chunk, some down to
    **-75dB** -- worse than Port Coquitlam's confirmed-broken -44/-45dB)
    is fabricated Welsh-language text with zero connection to an Ohio
    city council meeting -- `"Y Llywodraeth Cymru"` ("The Welsh
    Government"), 98 occurrences total (93 of them one single unbroken
    run, 40.7% of the page's 241 cues), plus nonsense Welsh sentences and
    repeated isolated numbers (`"19."` x6 around `00:15:52`-`01:04:58`,
    a possibly-related weaker instance of the same failure). This
    directly explains the page's `transcript_language="cy"` mislabeling
    filed above under the `detect_language_from_texts()` entry -- here
    the language tag is actually *consistent* with a large fraction of
    the transcript's real (fabricated) content, not just an unlucky
    2000-character sample. Real content resumes cleanly at `01:46:21`.
  - **North Kingstown School Committee, RI** (`meeting-89d6b1`) --
    confirmed, not just a suspected mic-check: **`00:01:00` ->
    `00:15:06`**, 80 consecutive cues of `"Test, test."` /
    `"Test, test, test."` at a mechanically uniform ~10-second cadence
    with **zero** real speech interspersed for the entire span (100%
    local density) -- a real AV check would have pauses, adjustments,
    someone else talking; this doesn't. 38% of the meeting's 210 total
    cues. Real roll call starts immediately after, at `00:15:00`.
  - **Cumberland County, NJ**
    (`cumberland-county-nj-2020-01-28-board-of-county-commissioners-regular-board-meet`)
    -- `"340,000,"` repeated exactly once per second for 41 straight
    seconds, `00:53:21` -> `00:54:02`, 100% local density, only 3.2% of
    the meeting's 1,291 total cues.
  - **Haines City, FL** (`meeting-16157c`) -- `"You're in the process."`,
    byte-identical, 7 times in 16 seconds (`00:09:42` -> `00:09:58`),
    100% density -- the cleanest possible case for the near-duplicate
    check (would trivially score 1.0), and it *still* wasn't flagged,
    purely because 7/525 total cues is nowhere near 50%. The clearest
    single proof that the global-ratio design, not the matching logic, is
    the actual bug.
  - **Lincoln City, OR** (`meeting-00bbd1`, previously only flagged above
    for its `language=cy` mislabeling) -- also has real fabricated
    content, just a smaller dose: a `"Yn ymwneud?"` ("relating to?")
    cluster around `00:09:02`-`00:09:30`, plus an isolated fabricated
    Welsh sentence at `00:10:21`. Confirms the language mislabeling
    there wasn't purely a sampling-bad-luck metadata issue -- there's a
    real, if minor, garbled patch underneath it too.
  - **Vacaville, CA** (`vacaville-ca-2026-06-09-regular-meeting-of-the-city-council`,
    version 1287) -- found live 2026-08-19, shipped to the public site
    *after* the fix above was already prototyped/validated but still
    unmerged: `00:00`-`06:29` is real dead air/pre-meeting silence (the
    meeting doesn't actually start until "I do believe the vice mayor is
    attempting to be online tonight..." at `06:33`), but the stored
    transcript instead has "In this video, I will show you how to make
    a new video." looped 5x (`00:58`-`01:33`), then a run of bare digits
    (`"5." "6." "5."` ..., `03:42`-`04:34`), then a run of decimals
    (`"1.3x." "1.4x."` ..., `05:36`-`06:00`) -- the app's own
    `detect_hallucination_warnings()` correctly flagged it
    (`already_flagged` would be true), so the *detection* side is
    working; this is purely evidence the *prevention* fix (`vad_filter=
    True`) still isn't deployed. `git show HEAD:worker/transcription_engine.py`
    confirms zero mentions of `vad_filter` in the last-committed
    version -- the fix genuinely only exists in the uncommitted working
    tree, not "was live at some point and regressed." Traced while
    investigating an unrelated on-demand-transcription request (job 256,
    Redwood City CA, `jlevine@hlcsmc.org` -- see `BACKLOG_DONE.md`'s
    2026-08-19 entry) whose own chunk 1 is a plausible but *not yet
    confirmed* third instance of the same pattern (that meeting's
    original pre-fix chunk-1 content was never pulled from
    `transcription_jobs.partial_segments` to check).

  **Fix direction**: the near-duplicate matching (`SequenceMatcher` at
  0.85) is the right primitive and doesn't need to change. What needs to
  change is scoring a *sliding window* (or absolute run length in
  seconds/cues, not just a ratio against the whole meeting) rather than
  one global fraction -- so a short, obviously-looping stretch inside a
  long meeting can trip it independent of how long the rest of the
  meeting is.

  **False-positive caution for whoever picks this up**: a cruder first
  pass at this same scan (raw repeat count over the whole meeting, not
  contiguous-run clustering) also flagged `"thank you"`, `"okay"`,
  `"yes"`, and `"here"` recurring dozens of times each in several *other*
  meetings from this session. Re-checked with actual clustering: those
  don't show the same signature as the six cases above (100% local
  density, zero real content interspersed) -- e.g. Halifax's 28 "thank
  you"s are ~29 seconds apart on average (consistent with a chair
  thanking distinct public commenters over a real 13-minute comment
  period), and short 5-7x roll-call bursts of "yes"/"here" a few seconds
  apart are consistent with distinct real speakers answering a roll call
  in turn. Not proof either way without listening to the audio, but a
  materially different pattern from the six confirmed cases -- any fix
  should be validated against both sets (catch the six, don't flag
  ordinary meetings) before shipping.

  **Fix approach prototyped and empirically validated 2026-08-18 --
  root cause is upstream of this detector, not a smarter detector.**
  Rather than only improving `detect_hallucination_warnings()` after the
  fact, the real fix is stopping Whisper from hallucinating on dead
  audio in the first place: enable faster-whisper's built-in VAD
  (`vad_filter=True`, Silero VAD under the hood -- a real
  speech-vs-non-speech classifier, not a volume threshold, so it also
  catches loud-but-non-speech audio like a musical intro, not just
  literal silence) in `worker/transcription_engine.py`'s
  `FasterWhisperEngine._transcribe_sync()`. Confirmed on the exact
  Hermosa Beach clip behind the "Music" loop above: old settings
  reproduce the fabricated `"Local government meeting. Common terms..."`
  text directly; with `vad_filter=True` it correctly returns **zero
  segments** instead (and ~7x faster, since it skips decoding
  non-speech instead of attempting it). Same clean result on a
  Moraine-City-zone clip: old settings burned 141s decoding nothing;
  new settings took 1s to reach the same (correct) empty conclusion.

  **A second, real bug was found *by* this same validation, independent
  of the fix above** -- worth its own record since it would have been a
  regression if shipped blind: `vad_filter=True` alone can merge two
  genuinely separate real speech bursts, on either side of a real VAD-
  skipped silent stretch, into one output segment -- keeping correct
  *text* but assigning a wildly wrong *timestamp range* (the first
  word's start to the last word's end, silent gap included). Reproduced
  on North Kingstown RI's `meeting-89d6b1` chunk 1: one segment came
  back as `[66.8s-735.9s]` (an 11-minute span) for what's actually two
  distinct real utterances -- a lone word ("So") at 67.5s, then real
  content resuming at 732.8s -- confirmed independent of every other
  setting tried (`condition_on_previous_text` True or False, custom or
  default `vad_parameters`: identical bug every time). Given this app's
  entire product is deep-linking to an exact timestamp, a wrong segment
  boundary is arguably worse than a missing one. **Fix**: also enable
  `word_timestamps=True`, then re-split any segment wherever two
  consecutive words have a gap larger than ~2s, using the real
  surrounding word timestamps instead of trusting the model's own
  reported `segment.start`/`segment.end`. Validated on the same North
  Kingstown chunk: correctly split the broken 668-second segment into
  `[67.5-67.9] "So"` and `[732.8-736.2] "folks, just a quick
  reminder..."`, and caught several *other* smaller instances of the
  same bug in the same chunk (25s and 83s hidden gaps) that weren't
  otherwise obvious -- longest segment after the fix: 7.2s, versus 668s
  before it.

  Full validated combination: `vad_filter=True` + `word_timestamps=True`
  + gap-based re-splitting (new code, not a library flag) +
  `condition_on_previous_text=False` (kept as defense-in-depth for
  within-chunk cascading per faster-whisper's own docstring, though
  confirmed *not* the cause of the timestamp bug above -- reproduces
  identically either way). Regression-checked clean against Buffalo,
  NY's already-good transcript (352 sane, correctly-ordered segments,
  same coherent content start-to-finish) and North Kingstown's real
  content once past the fixed boundary (roll call, Pledge of Allegiance,
  etc., all intact). Not yet wired into production
  `worker/transcription_engine.py` or `scripts/
  transcribe_backlog_locally.py` -- next step once Port Coquitlam's raw
  (unfixed-audio, no left-channel retry) case finishes validating too.

  **Two alternative approaches were considered and parked, not
  rejected** -- allowed back if the above ever proves insufficient on a
  case it doesn't handle:
  - Skip trusting faster-whisper's internal VAD-region stitching
    entirely: call Silero's `get_speech_timestamps()` directly, decode
    each real speech region as its own separate clip, and place each
    one using this app's own already-trusted `shift_segments()`
    chunk-offset math (`worker/segment_utils.py`) instead of the
    library's internal remapping. More control, more new code to
    maintain.
  - Physically strip non-speech out of the audio ourselves before
    Whisper ever sees it (e.g. `ffmpeg silenceremove`), with fully
    manual bookkeeping of what got cut so timestamps can be shifted back
    correctly by hand. The most manual of the three, full control, but
    the most new surface area for a first-party timestamp bug --
    parked in favor of leaning on the library's already-tested
    `word_timestamps` machinery instead, now that the gap-split fix
    above is confirmed to work.

## ~~`GET /internal/transcription/hallucination-candidates` returns 502~~

**Fixed 2026-08-21** — diagnosis (same unbounded-full-scan shape as
`find_auto_transcription_candidate` before its 2026-08-17 rewrite)
confirmed by code review; fixed with a data-shaped split (small
already-flagged set pulled in full, big not-yet-flagged population
bounded by `limit`/keyset `after_id` pagination) rather than a pure SQL
predicate, since this endpoint's whole job is running
`detect_hallucination_warnings()` itself. Full root-cause writeup, the
NULL-`transcript_warnings` bug caught while fixing it, and test
verification detail in `BACKLOG_DONE.md`.

## `scripts/transcribe_backlog_locally.py`'s "no usable audio/video source on re-resolve" skip has no retry -- confirmed a real, live meeting can get wrongly skipped by one transient failure (2026-08-18)

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

## `tier3_auto_transcription_queue.txt` has at least one genuinely truncated URL, not just dead/never-formed ones (found 2026-08-19)

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

## Some Swagit meetings have no single "whole meeting" video file — pre-split into per-agenda-item clips instead (found 2026-08-18, real fix landed for a related bug, this part still open)

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

## Deprioritized ideas — allowed back if we wish (parked 2026-08-15)

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
