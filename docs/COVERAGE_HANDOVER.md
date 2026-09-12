# Coverage handover: how the site's coverage is measured, grown, and kept honest

Written 2026-09-10 at the end of a two-day push that built the two coverage
dashboards and ran nine parallel sweeps against production. This is the
standing picture a new session needs before touching coverage, identity, or
the dashboards. It deliberately skips one-off fixes; `BACKLOG_DONE.md` has
those, with numbers. `CLAUDE.md` still governs conventions; this document
explains the *system* those conventions protect.

## 1. The model in one paragraph

A **government** is identified by a `gov_id` (`us:place:0627000`,
`us:county:06019`, `us:cousub:…`, `us:sd:…`, `us:state:06`, `ca:csd:…`,
`ca:cd:…`, `ca:pr:35`, or a minted `rtr:us:ca:<slug>` when no national
table covers it). A **tenant** is a hosted platform instance
(`southmiami.granicus.com`, `@TownofWoodside` on YouTube) and can serve
several governments. An Archive **page** is one meeting, keyed to a
government by `gov_id`, with the adapter's raw jurisdiction string kept in
`jurisdiction_raw` and the registry's display name in `jurisdiction`. The
**research file** (`rtr-business/research/jurisdiction_coverage.csv`,
~34k rows) records what we know about every government we have ever
looked at: domain, suspected platform, an example calendar URL, and an
honest test outcome (`reject_reason`). Everything downstream, the
dashboards included, joins these on `gov_id`. A trailing `website_status`
column (added WO-186, 2026-09-10) carries `none-known-2022` on rows
where UScityURL's 2022 dataset also found no website and ours is still
blank -- a cheap way for a sweep to deprioritize a row with no lead,
without touching `reject_reason`'s own taxonomy. **`domain` is a bare
host; URLs live in the URL columns** (`example_meeting_url`,
`example_agenda_or_calendar_url`, `alternate_urls`) -- WO-193
(2026-09-11) normalized every row to this rule after finding ~20% of
`domain` values were full links; see `BACKLOG_DONE.md`'s WO-193 entry
and `scripts/coverage_alternates.py`'s `canonicalize_domain()`.

## 2. The two dashboards

### Meeting inventory (per Archive page)

- Code: `archive/utils/meeting_inventory.py` (one flat row per page),
  `GET /internal/meeting-inventory` (paginated JSON or CSV),
  `GET /internal/meeting-inventory/summary` (missing-field counts in one
  query), `scripts/export_meeting_inventory.py` (walks either endpoint,
  or `--source export` when the endpoints are not deployed yet, and writes
  the CSV plus a self-contained sortable/filterable HTML page with CSV
  download).
- What it is for: reviewing identity and completeness page by page. The
  columns that earn their keep are the stored-vs-registry name comparison
  (`names_match`: yes / stale form / state missing / unidentified /
  no gov_id / no), the stored `meeting_body` (reported as-is, blank on
  ~90% of pages, never guessed from a title), the page-vs-video platform
  split, and the raw video host domain.
- Rule that shaped it, from Ryan: **a report reports; it never guesses.**
  A blank is a finding to count, not a gap to paper over. If a field is
  mostly empty, file that in `BACKLOG.md` rather than inferring it.

### Gov Coverage (the coverage registry: per government, all of North America)

- Code: `rtr-business/research/coverage_registry.py`, run by
  `rtr-business/research/refresh_coverage_registry.sh` (which first runs
  the inventory export in this repo). Outputs in
  `rtr-business/research/coverage_registry/`: the CSV, a markdown summary
  with the headline table, a JSON of the numbers, and the HTML page
  (gitignored; a publisher-safe copy is written with `--hosted-html`).
- Universe: every row of `app/utils/jurisdiction_data/{us_places,
  us_cousubs, us_counties, us_states, ca_csd, ca_cd, ca_pr}.csv`, 42,904
  governments. Special districts are deliberately not a lookup table
  (decision D3 in `rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md`);
  they are minted on request with "ok mint" in a pin worklist.
- "US school districts" is its own row (WO-214, 2026-09-11): the
  Gazetteer table `us_school_districts.csv`, 13,326 districts keyed
  `us:sd:<geoid>`. The research file has a row per district, seeded
  from the NCES website list and the 2026-09-05 platform scan
  (`rtr-business/research/ENUMERATION_METHODS.md` §262). Ryan's call:
  no Census of Governments rows on the dashboard.
- Two catch-all rows, "US other" and "Canada other" (added 2026-09-11),
  hold every government the research file or the Archive knows that is
  not in those tables: special districts, courts, untyped minted `rtr:`
  ids. A minted id typed municipality, county, township, state or
  school district sits in that tier's row instead. Registry-file
  entries with no Archive page and no research row are left out and
  listed in `coverage_registry/minted_orphans.csv` for a periodic
  audit (817 on 2026-09-11, mostly the first scoring run's page-title
  junk). `rtr:unknown:<host>` placeholders are not governments and sit
  in no row.
- The top table has a checkbox per row. The total row sums only the
  checked rows and says how many. US rows start checked, Canada rows
  start unchecked; "Include Canada" ticks the four Canada rows at once.
  Columns run in funnel order (Domain, Tested, Platform known, Hub URL,
  In Archive, Has transcript, Discovery tenant); under each count is
  its share of the universe and its share of the column to its left.
- Per government it joins four sources and says which one each column
  came from: the research file (domain, platform, tested, hub URL),
  rtr-discovery's ledger (a known tenant, last walked), rtr-upcoming's
  roster (verified calendar URLs), and the Archive inventory (pages, best
  tier, meeting/video URL, platforms).
- The dashboard is a funnel per kind of government: domain → platform
  known → tested → hub URL → discovery tenant → in Archive → has
  transcript, with a population dropdown (the toggle that changes the
  story most: townships drag every percentage down until you filter to
  5,000+). Each cell click shows the governments *missing* that step,
  which is the set you act on. A second table breaks "tested but not in
  the Archive" down by reject reason.
- A scheduled task ("Daily coverage registry refresh", 7:09 local, runs
  while the desktop app is open) refreshes it, republishes the hosted
  page, and commits the outputs. Re-running by hand is the one script
  above.

### Reading them together

The inventory tells you whether the pages we have are keyed and complete.
The registry tells you which governments we do not have and why. Most
useful pattern so far: pick a kind (US counties), read the funnel row,
click the biggest drop, sort by population, and look at the reject
reasons. That is how every sweep below was scoped.

## 3. How identity is assigned and repaired

- `app/utils/gov_registry/resolve_government()` runs a ladder: pinned →
  name repair → classify the type before any place lookup → national
  table → registry fallback → mint → blank. It refuses to guess: a bare
  "Kansas City" with no state stays unresolved on purpose.
- **Pins** (`app/utils/jurisdiction_data/tenant_overrides.csv`) are the
  human override: host → gov_id, optionally with a `match` discriminator
  for shared hosts (a YouTube handle or video id, a TelVue playlist).
  They are written through `scripts/apply_pin_worklist.py` from a
  worklist sheet Ryan fills in plain English ("Baltimore County, MD", or
  "ok mint" for a district). The apply reports every row it could not
  settle; typos are the usual reason a row "never took".
- **Backfill** (`scripts/backfill_gov_id.py`) re-keys already-archived
  pages after a registry change. Ryan has allowed it to run from this Mac
  for this metadata-only script; the pattern (map `ARCHIVE_DATABASE_URL`
  into `DATABASE_URL` in-process, dry run, apply, apply again for the
  tier-only residue, third dry run must be zero) is in `BACKLOG_DONE.md`'s
  2026-09-09 entries. Retired hub slugs need rows in
  `archive/data/hub_slug_aliases.csv` or they 404; the applied report's
  before/after slug columns are the source.
- **Identity joins** are the cheapest coverage win found so far: when the
  research file says a government is "ingested" but the registry shows no
  page, the page usually exists on that government's own host under a
  minted or `rtr:unknown` id. Pin the host, backfill, done. 55 hosts and
  76 pages moved this way in one pass.
- Deploys are manual and pins only reach *new* ingests after one. The
  transcription worker re-resolves a video when it transcribes it, so a
  shared-host pin must be deployed before the worker reaches that queue
  entry or the page loses its government.
- **Ryan's rule for who owns a meeting (2026-09-11, WO-201):** the source
  of the video is the truth, not our prior assumption about how
  government is organized. The body that actually publishes a meeting
  gets its own record, minted as a curated government
  (`curated_governments.csv`) when the Census has no row for it — a
  state agency (PennDOT), a river-corridor council, or a regional
  planning commission is not folded into the city, township, or state it
  happens to sit inside just because that's the government we already
  had a row for.
- **Multi-government hosts can never be pinned by host alone (2026-09-11,
  WO-210).** Ryan, verbatim: "We absolutely cannot use pins for the
  multi-gov hosts like vimeo, youtube, youtu.be, clerkshq, etc. because
  they're so prevalent and we KNOW they need a match... if youtu.be
  without a channel match, pin to NULL." A host like `youtube.com` or
  `vimeo.com` serves thousands of unrelated governments, so a blank-match
  row on one of them is not a normal per-tenant pin — it silently keys
  EVERY unidentified video on the whole host to one government. That is
  exactly what happened once: `vimeo.com,,<gov_id>` mis-attributed at
  least three other governments' real videos to Oak Bluffs, MA
  (`BACKLOG_DONE.md`'s WO-183/WO-206/WO-206b), and it came back once
  already through a rebase after being deleted. Three layers now enforce
  the rule: (1) a shared list, `app/utils/gov_registry/registry.py`'s
  `MULTI_GOV_HOSTS` (re-exported next to `CORPORATE_HOSTS_BY_PLATFORM` in
  `app/platforms/base.py` for discoverability, kept plain-stdlib in
  `registry.py` itself so `archive/db/crud.py` can use it without pulling
  `bs4` across the app/archive service boundary), with `is_multi_gov_host()`;
  (2) the `tenant_overrides.csv` loader refuses to load a blank-match row
  on one of these hosts at all — never applied, logged once, and counted
  via `registry.rejected_multi_gov_overrides()`, with a committed-file
  test that fails CI the moment one is added again; (3) the resolver
  itself (`resolver._resolve_government_ladder()`'s rung 1b) returns no
  government for one of these hosts absent a matching per-video, per-
  channel or per-external-id pin — never a national-table guess from a
  channel/video name alone, even one that would otherwise validate as a
  real place. `POST /internal/jurisdiction/override` follows the same
  rule: a batch touching one of these hosts gets one rule per real
  per-video match found in the batch, never a blank one, with any page it
  couldn't derive one for reported under `tenant_override_notes`. **A
  delegated CivicPlus/Legistar page keeps its own identity without a pin
  (2026-09-11, WO-214).** `civicplus.py`/`legistar.py`'s delegation to a
  multi-gov host still keeps the pre-existing "known quirk" (source_url
  and platform land on the delegated host, not the original one — see
  CLAUDE.md's platform-wrapper bullet) — that was never touched, since
  Archive pages are deduplicated by `source_url_normalized` and changing
  it retroactively risked a duplicate page on re-ingest. Instead
  `ResolvedMeeting.origin_host` carries the delegating tenant's own host
  separately, and rung 1b falls back to it (re-running the ladder against
  `origin_host` instead of blanking) only when the delegated host has no
  matching pin and `origin_host` is itself not a multi-gov host — a real
  per-video/channel pin on the delegated host still wins outright, and a
  bare paste with no pin and no `origin_host` still blanks exactly as
  before. This only fixes a FRESH resolve: `origin_host` is not persisted
  on `MeetingPage`, so `scripts/backfill_gov_id.py` still cannot recover
  it for an already-archived page (confirmed by a live dry run matching
  zero rows against 3 real affected tenant hosts) — see `BACKLOG.md`'s
  live entry for the 3 pages that need a manual re-push, and
  `BACKLOG_DONE.md`'s WO-214 entry for the full sizing and fix detail.
- **A blank answer on a shared host never downgrades a keyed page
  (2026-09-11, WO-215).** Rung 1b above answers tier `blank` (gov_id
  `rtr:unknown:<host>`) for EVERY page on a `MULTI_GOV_HOSTS` host with no
  matching per-video/channel/external-id pin — including a page that
  already carries a real, earned identity from before rung 1b existed.
  That answer means "no matching pin was found," not "this page has no
  government," so it must never overwrite a page's existing national or
  curated id (`us:*`, `ca:*`, `rtr:<country>:*` — anything that isn't
  itself `rtr:unknown:*`). Found the day after WO-210 shipped: a DRY RUN
  of `scripts/backfill_gov_id.py` against production proposed exactly
  this downgrade on 825 already-keyed rows and, separately, overwrote the
  `gov_id` on 228 `manual_override` rows (only the jurisdiction string and
  the tier were protected there before, not the identity itself). Both
  `scripts/backfill_gov_id.py` and `archive/db/crud.py`'s
  `_find_or_create_page()` (the live re-ingest path — a caption run, a
  re-resolve) now carry the same guard: a `blank`-tier answer on a
  `MULTI_GOV_HOSTS` host is a no-op against an already-keyed row's
  gov_id/gov_type/tier/display name, not a write. A NEW page on one of
  these hosts is unaffected — it still resolves to `rtr:unknown:<host>`
  exactly as rung 1b intends. See `BACKLOG_DONE.md`'s WO-215 entry for the
  before/after counts.
- **A sweep that already knows a government's id sends it in the ingest
  payload, so a new page never depends on a pin reaching production
  first (WO-222, 2026-09-11).** `scripts/wo134_confirmed_hits_ingest.py`
  and `scripts/bulk_ingest.py` (and every other sweep script that knows
  its row's `gov_id` at the ingest call site) now put it straight into
  the `POST /internal/ingest` payload, which `_resolve_page_government()`
  already honored as `caller_gov_id` — pins still matter for the
  transcription worker's later re-resolve and for the drip, just not for
  this first write.
- **A matched per-video pin on a shared host wins over the registry
  unconditionally (WO-221), and that cuts both ways.** It fixed the case
  it was built for, but it also made every OLDER fallback pin
  authoritative for the first time — including wrong ones the registry
  had quietly been out-voting until then. WO-231 (2026-09-11) found 13
  of them the hard way, when the very next post-deploy backfill made
  them fire: see its `BACKLOG_DONE.md` entry for the corrections and
  `BACKLOG.md`'s live entry for the precedence trade-off this leaves
  open (97 more pins flagged suspect by an oEmbed audit, not yet
  hand-checked).

## 4. How coverage is grown: the sweep pattern

Every sweep in `scripts/` follows one shape, and new ones should too:
build the candidate list from the registry CSV with an explicit filter,
confirm "not in Archive" against a **fresh** export, resolve through the
real adapters, dedupe by source URL, flush a report CSV per row so a
re-run resumes, stop after a run of consecutive errors, and write every
outcome back to the research file with a reject reason from
`ENUMERATION_METHODS.md` §23's taxonomy. When verifying a low-confidence
domain candidate (a third-party directory, an old crawl), a strict
name-in-title check misses real sites (JS-rendered pages with no static
title, or a title that's just a tagline) -- accept instead when the name
(allowing a "City/Town/Village/Borough of" prefix, a state abbreviation,
or punctuation stripped) appears in the title, `<h1>`, `og:site_name`,
the footer, or the domain string itself, OR the page carries an
independent government signal (a `.gov` host, or a link to an
agenda/minutes/council/board page or a known meeting platform); reject a
parked-domain page, a "coming soon" placeholder, or a page that plainly
names a different government (WO-186, 2026-09-10).

**Ryan's ingest rule, verbatim in spirit:** only meetings with video
become pages. Tier 1 (captions the server can fetch) and tier 2 (YouTube
captions the local fetch can get) ingest with segments. Tier 3 (video, no
reachable captions) goes to `scripts/tier3_auto_transcription_queue.txt`
and the cloud worker drips it onto the site. Agenda-only is recorded as
`no-video-found` and never ingested. A host with no video is a legitimate
outcome to show on the dashboards, not a page. Every `wo1XX_finish_tier3*.py`
script's own probe-verdict-to-queue-line decision goes through one shared
place, `app/platforms/queue_probe.py`'s `finish_candidate()`
(WO-224) — it is the only code that should turn a fresh or cached probe
verdict into a queue line, a pin, or a deferred-file line, so a new
finish script should call it rather than reimplementing the decision.

**Alternate domains (WO-181, 2026-09-10; widened by WO-184,
2026-09-10/11).** The research file carries two more columns,
`alternate_domains` and `alternate_urls` (added in WO-165's duplicate-row
cleanup): every other real domain or meeting URL a government was ever
recorded under, kept rather than thrown away when WO-165 folded its
duplicate rows into one. The row that survived kept whichever domain/URL
was already sitting in the row WO-165 chose as the keeper for that
government (see `BACKLOG_DONE.md`'s WO-165 entry); the other real one
moved sideways into these columns instead of being deleted.
`scripts/coverage_alternates.py` is the one place that reads them:
`candidate_domains()` returns the primary domain followed by every
alternate, and `ladder_with_alternates()` retries the next candidate
according to a `trigger` policy.

Ryan's rule (2026-09-10, quoted verbatim — this is now the standing
policy, and it supersedes WO-181's original narrower framing wherever
the two disagree):

> "A domain keeps priority when it has produced a resolved meeting: with
> video is best, but a meeting or agenda without video is still very
> high quality. If a domain has produced no meeting at all, we may
> simply be looking at the wrong domain, and we lose nothing by trying
> another. Every government posts agendas at least, so the line is:
> found a meeting or agenda, or not."

Concretely, that's `trigger="no-meeting"`: retry an alternate whenever
the primary produced nothing at all — an ACCESS-class reject (blocked,
timed out, DNS-dead, a challenge page), a CONTENT-class reject that
means "no platform link/meeting/video was found at all"
(`no-platform-link-found`, `no-meeting-nor-video`, `no-meetings-found`,
`no-platform-signature`), or a blank/never-tested reason. It is never
worth retrying once a real meeting or agenda was already found on the
primary, whether it had video or not, or once the row is off-mission or
already spoken for (`meeting-without-video`, `no-video-found`,
`off-mission`, `video-without-meeting`, `unsupported-platform-no-adapter`,
`ingested`, `queued`, `already-covered`). `trigger="access"` keeps
WO-181's original, narrower behavior (only an ACCESS-class reject
retries) for any caller that still wants it.

**Promotion.** When an alternate answers with a platform link and the
primary didn't, `decide_promotion()`/`apply_promotion()` make that
alternate the new `domain`, moving the old primary into
`alternate_domains` — nothing is ever lost. When the primary itself
answers, or nothing does, nothing is promoted.

**One more hop for "found a meeting, no video" (WO-184).** Even when a
government's primary domain already found a meeting or agenda but no
video, WO-184 still runs a single, no-promotion hop on the alternate
domain (`one_hop_alternate()`): one plain HTTP fetch of the alternate's
home page, plus up to a few of its own meeting/agenda links, checking
whether a DIFFERENT platform than the one already known turns up. A
Granicus/YouTube/CivicClerk/etc. link the primary didn't have is a new
view of the same meetings and may carry video the primary's view didn't.
Finding the same platform again isn't useful and changes nothing.

WO-181's own pilot ran the narrower `trigger="access"` retry against the
265 rows that had both an alternate domain and an access-class reject on
the primary; see `BACKLOG_DONE.md` for the count this actually found.
WO-184's wider run and its own counts are in `BACKLOG_DONE.md` too.

**The hop-link step ranks candidates now, rather than taking the first
document-order match (WO-228, 2026-09-11).** The old `find_hop_links()`
kept the first `MAX_HOP_LINKS` links whose text/href matched any of
twelve unranked words -- "calendar" in a nav bar won the slot as often
as the real agenda/minutes/video link, and 362 governments with a hub
URL and no Archive page ended up with an events calendar recorded as
their meeting hub as a direct result. It now scores every candidate
from weights measured against two real samples (90 governments where a
real hit followed a "no platform link found" verdict, 60 of the 362
calendar-shaped hubs): an "agenda"+"minutes" link led to the real hub
14/14 times it was tested and never to a wrong page; a bare
"calendar"/"events" link (no other qualifying word) led to a wrong page
14/14 times and never to a real one; a routine-municipal word (trash,
recycling, holiday, library, a 5K) showed up on 80% of the wrong-page
sample. 62% of the real positive hits were not the first HOP1-matching
link in document order -- the old rule handed the ladder something else
first on a majority of real cases. `looks_like_document_hub()` verifies
a fetched candidate before trusting it, and `find_calendar_entry_links()`
takes one more hop into a calendar's first two dated entries when the
calendar page itself shows no document evidence. Full study, both
tables and the weight list: `rtr-business/research/ENUMERATION_
METHODS.md` §270; code in `scripts/wo147_access_ladder_sweep.py`. The
161-row re-run of already-recorded calendar-shaped hubs against the
fixed ranker is a separate WO, not yet run.

**WO-228's own twelve-word candidate gate was itself replaced with
measured weights (WO-274, 2026-09-12)** -- the same "calendar wins as
often as the real link" pattern held for the WORDS themselves, not just
the ranking: plurals/role words (agendas, meetings, commissioners,
boards, supervisors) and named platform paths (AgendaCenter, Hyland's
ViewMeeting/AgendaOnline) measured far stronger than "calendar"/singular
"agenda"/"video"/"stream", none of which the old list weighted
correctly. `find_hop_links()`'s default is now driven by
`app/utils/jurisdiction_data/hop_link_weights.csv`
(`scripts/derive_hop_weights.py` re-derives it); `legacy=True` gets the
WO-228 scorer back verbatim. On 180 real homepages, the new scorer finds
a vendor-host/named-path link in its top 8 on strictly more governments
than the old one (123 vs 95, zero regressions) -- full tables, the two
real regressions found and fixed building it, and what the sample can't
show: `docs/investigations/hop_scorer_measurement.md`.

**Two guards Ryan approved 2026-09-11 (WO-226), now in code and unit-
tested in every apply script that writes `reject_reason`** (see
`~/Documents/rtr-business/research/wo226_apply_to_jc.py`'s
`apply_reject_reason()` for the reference implementation): an
access-class reject reason (`blocked-*`, `cloudflare-challenge-blocked`,
`dns-unresolvable`, `timeout`) must never overwrite a row that already
carries a real meeting or agenda URL; and an alternate domain's own
access-class result must never replace a content-class finding already
on file for the primary domain — the exact WO-184/Tomah WI bug this same
WO's spot-check found and fixed by hand three more times (Carroll County
NH, Tomah WI, Jefferson County WA).

What the 2026-09-09 sweeps established about *where video is*:

| Population | Finding | Implication |
|---|---|---|
| CivicPlus AgendaCenter sites | ~80% carry agendas but no video anywhere, even walked back several years. The ~20% that do link video per meeting resolve fine through the adapter's delegation to YouTube/Granicus/CivicClerk. | AgendaCenter is an agenda host, not a video host. Probe it for the 20%, then move on. |
| "Known platform, no page" | Three quarters had already been rejected once; the re-check still found real pages (two governments with 500–1,000 caption segments were blocked by a platform-name spelling mismatch). | Re-checks of rejected rows are worth it when the reject was made by an earlier, cruder pass. |
| Counties | Limited by stale data, not code: hundreds of NACo domains no longer resolve; several large counties sit behind web firewalls. | Fix the domain list before spending more resolver time. |
| Two-hop and headless candidates | Once a platform is found, roughly half convert to a video page or a queue entry. | Discovery is the bottleneck, not resolution. |

**Scanning a listing page itself for media, once no platform link was
found (WO-197, 2026-09-11).** For the 2,471 governments left over from a
listing-page sweep with no recognised platform, a cheap follow-up works:
scan the page for a direct video/audio link or a link to YouTube/Vimeo/
Google Drive/Dropbox/CivicWeb, follow one hop to a same-domain
meeting-shaped link if the page itself has nothing, then check for a
working RSS/Atom/ICS feed as a last resort. This found 29 real videos (18
ingested, 11 queued) out of 2,471 — a small direct yield, but each one is
a government no other method had reached. **The feed check is a lead,
not a result**: it only confirms a feed URL exists and answers over
HTTP — it never checks whether the feed lists meetings or links to
video. 1,443 of the 2,471 (58%) had a feed answer, and 93% of those are
plain WordPress `/feed` URLs (the site's generic content feed, not
necessarily a meetings calendar). Worth a dedicated feed-parsing method
later; not worth counting as coverage today. Every real video hit still
needs the same hand-check as any other new source — this pass found 2
wrong-government pages (a video for a completely different, unrelated
government sitting on the right government's own listing page) and 1
off-mission page (a real video, but a regional webinar, not a meeting of
the government it was filed under), all fixed after the fact. Full
write-up: `ENUMERATION_METHODS.md` §286; `BACKLOG_DONE.md`'s WO-197
finish entry.

## 5. The breakthroughs worth carrying forward

1. **Headless browsing recovers JavaScript-rendered navigation, not just
   firewalls.** On the largest governments previously rejected as "no
   platform link found", a headless pass found a platform on 41% of
   sites, and 149 of 150 of those pages had loaded cleanly for a plain
   client; the meeting links were simply drawn by JavaScript. An earlier
   trial had attributed its wins to bypassing 403s. The lesson is that
   the plain-HTTP two-hop scan's "no platform" verdict is unreliable on
   modern municipal sites, and the headless pass (one browser, one
   government at a time, never past a human-verification gate) is the
   right second opinion. ~1,180 smaller governments have not had it yet.
   Script: `rtr-business/research/wo133_headless_recheck_scan.py`.
2. **The identity join** (section 3): coverage that already exists but
   is invisible because of a minted id. Cheap, high-yield, repeatable
   whenever the research file and the Archive disagree.
3. **Counties that share a name with an independent city** (Baltimore,
   Roanoke, Fairfax, Richmond, St. Louis, Carson City) never resolved
   because the county table lists independent cities as county
   equivalents. The fix (`NameStateTable.lookup_typed()`: let the query's
   own type word break a tie) is a pattern: when the exactly-one rule
   declines, ask whether the input already said which kind it meant. The
   mirror case, a city sharing a name with its own county (Waukesha WI),
   is filed and not yet fixed.
4. **YouTube is two independent restrictions and one shared block.**
   Embedding disabled and captions disabled are separate channel
   settings; a video can have captions you cannot embed. Both are now
   recorded as permanent-failure markers on the page (so the daily fetch
   never re-tries them and burns its budget), a metadata call checks them
   at zero rate-limit cost before any transcript request, and an
   embed-disabled page shows a "Watch on YouTube" link and stays out of
   lists until a transcript lands. Audio download works around the
   embedding restriction and local Whisper produced full transcripts,
   but YouTube's bot check blocks this Mac's address for downloads as
   well as captions after roughly 45 minutes of activity. What clears the
   block is unmeasured (`docs/investigations/youtube_429_block.md`).
5. **The research file is a shared, unlocked, whole-file rewrite hazard.**
   Ten scripts from several sessions each read the whole file and wrote
   it back; two overlapping did so and half the rows vanished in the
   working tree (recovered from git, nothing committed lost). The
   protocol every writer now follows is `ENUMERATION_METHODS.md` §158:
   lock, re-read immediately before writing, refuse below 99% of the
   committed row count, temp file and atomic rename, LF endings, `git
   diff --stat` shows only your rows, commit at once. A shared apply
   helper that every script calls is the durable fix and is not built.
6. **Parallel agents on one repo work, with three rules.** Assign work
   order numbers centrally (agents cannot see each other's), partition
   populations by kind (municipalities vs counties) rather than by
   heuristic, and expect every agent to rebase through the others'
   merges; the generated `BACKLOG.md` table of contents, the tier-3 queue
   file, and the pins file conflict on nearly every merge and resolve
   mechanically (regenerate the TOC; for the queue and pin files, a line
   deleted on `main` stays deleted, union only what your own branch
   added, then subtract `scripts/tier3_long_meetings_deferred.txt` from
   the queue — a plain union of both sides re-added 103 deliberately
   removed long meetings and a removed pin on 2026-09-11, WO-212/WO-210,
   and CI now fails on both). Budget for the session limit: seven agents
   at once tripped it once; resumable per-row reports meant nothing was
   lost. `BACKLOG_DONE.md` is a union too — a hand-resolved rebase
   conflict there is exactly as likely to silently drop a finished-work
   entry as it is a queue or pin line, and as of WO-236 (2026-09-11) CI
   fails a PR that does.
7. **A hub's URL is now frozen to the government, not to its name**
   (WO-256, 2026-09-12, built from `docs/investigations/
   hub_architecture_audit.md`). Identity work used to move reader URLs:
   every rename, override, mint-scoring pass and `backfill_gov_id.py
   --apply` run recomputed a government's `/j/` slug from its *current*
   display name, and nothing wrote the alias that keeps the old URL
   alive — 829 alias rows for 784 governments by 2026-09-11, and on that
   evening one backfill run retired 35 hubs of which 12 were retired
   wrongly by a resolver regression (WO-243/WO-251). The slug now lives
   in an Archive table (`hub_slugs`, one row per `gov_id`), minted from
   exactly today's computed slug and frozen once the government has been
   known 7 days and has more than one page. **What this changes for pin
   work**: a page changing government no longer changes any URL, so the
   "does this re-key need an alias row?" review step after a pin round is
   gone. `scripts/freeze_hub_slugs.py --apply` (Render shell) is the
   one-time backfill and the catch-up sweep. **The same work order also
   replaced how a hub decides which un-keyed pages are its own**: shared
   tenant host, never raw jurisdiction text, with `MULTI_GOV_HOSTS` still
   the list of hosts that can never be keyed by host alone. Measured on
   the same export: 31 un-keyed pages gain a real hub, and four real hubs
   (Orem UT, Tooele UT, Box Elder County UT, Caledonia Township MI) stop
   showing unrelated YouTube video that matched on text alone. See
   `STATE_HUB_PAGES.md` §6 for both designs. **And the export-and-grep
   step is gone**: `GET /internal/unidentified-pages` groups every page
   with no government by the host it came from, biggest first, saying for
   each whether the host is multi-government, which real governments are
   already on it, and whether a hub already adopts those pages.

## 6. What is honest but unfinished

- **`meeting_body` is blank on ~90% of pages.** Ryan's model: `gov_type`
  says what Tampa is, `meeting_body` says which body of Tampa met. Only
  Granicus, Legistar and Invintus send it. Filed under Trust, safety &
  data quality; do not fill it from a title regex at read time.
- **The research file has ~1,300 gov ids on more than one row** and 87
  genuinely ambiguous ids flagged for a human. Both need eyes, not code.
- **State legislatures, US territories other than Puerto Rico, Canadian
  school boards, tribal governments** are not in the universe tables.
  Their absence is a decision, not an oversight.
- **Dashboard filters** still lack "exclude a string" and "blank /
  non-blank", and the registry lacks a per-state view; both are Ship-next
  entries in `BACKLOG.md`.
- **Governments rejected as "no video found" stay where they are by
  Ryan's decision when the row actually recorded a real meeting or
  agenda** -- a video-less host is a valid record (907 at population
  5,000+ as of 2026-09-11; this number moves daily as concurrent sweeps
  both add and clear rows, so treat it as a live count, not a fixed
  figure -- re-derive from the file rather than citing a stale one).
  **The subset that recorded nothing at all (a blank meeting URL, blank
  agenda URL, and no guessed platform) is different** -- that's not a
  valid "no video" record, it's an untested row wearing the label. WO-225
  (2026-09-11) found and re-tested all 553 of those; see
  `BACKLOG_DONE.md`'s WO-225 entry.
- **WO-174's CivicPlus AgendaCenter ladder sweep is finished (2026-09-11
  close-out).** All 14,553 governments with a domain and no page that
  WO-127 never touched have now been checked, across four earlier slices
  plus this close-out. It found 50 real captioned pages and 12 more
  queued for transcription — a small, shrinking yield (2.3% in the
  first, biggest-government pass, down to 0% in the smallest band) that
  says this particular finite list is exhausted, not that video coverage
  broadly is. Two real, sizeable buckets remain from this same sweep,
  and both are already on `docs/BREADTH_SWEEP_BRIEF.md`'s list rather
  than needing a new plan: 720 governments blocked by a "prove you're
  human" challenge page (candidates for a headless pass, never past an
  actual human-verification gate — see this file's own breakthrough #1
  and the standing rule in `CLAUDE.md`), and 152 "real meeting, no
  video" governments (candidates for a media scan of their agenda
  attachments, in case a meeting's video lives off-platform rather than
  missing entirely). Neither is "just re-run this same script" — both
  need the different method `docs/BREADTH_SWEEP_BRIEF.md` already
  describes.
- **BoxCast pages now resolve a fresh signed playlist at view time**
  instead of trusting the one stored at ingest (WO-229, 2026-09-11), but
  whether BoxCast actually re-signs with a later expiry once the current
  one passes is unconfirmed — see `BACKLOG.md`'s matching `[WAIT]` entry.
- **WO-264's overnight sweep of the 10,016 governments under 5,000
  people (2026-09-11/12) covers 1,894 of them; the remaining ~8,100 go
  to the Platforms conductor's own passive-discovery pipeline (WO-282/
  283), a different method, not a resume of this one.** The close-out's
  hand-read gate found two real, generalizable gaps worth knowing about
  before the next channel-scanning sweep: a French-language meeting
  vocabulary ("séance"/"conseil") that an English-only keyword check
  silently treats as off-mission (six real Quebec municipalities'
  channels were initially miscounted this way; the *production*
  `app/platforms/youtube_channel.py` already checks a channel's
  `/streams` tab, not just `/videos` — a gap that only existed in this
  close-out's own one-off checker script, already fixed by hand) — and
  a real confirmed gap in the codebase itself: no adapter can pull a
  playable video from a Google Drive share link, even when the file's
  own title says "City Council Meeting" (Kemmerer city, WY; see
  `BACKLOG.md`'s `[NEEDS-AUDIT]` entry).

## 7. Where to look first next time

- YouTube pages fed by the always-on drip (`scripts/youtube_drip.py`)
  arrive keyed only as well as the deployed pins allow; the review
  procedure, the per-page file, and the video-vs-channel pin shapes are
  in `docs/YOUTUBE_DRIP_IDENTITY_REVIEW.md` (2026-09-11).
- **The drip's feed lane no longer writes its probe rows straight to the
  tracked `scripts/tier3_auto_transcription_queue_probe.csv` (WO-248,
  2026-09-12).** It used to, live, all day, while `main` grew the same
  file through merged sweeps — a merge conflict on every `git pull` on
  the drip Mac (append-only, nothing lost, but hand-resolved daily). Rows
  now go to a local, gitignored buffer
  (`scripts/tier3_auto_transcription_queue_probe.local.csv`), and the
  drip's daily `advance` step (`fold_probe_sidecar()` in
  `scripts/youtube_drip.py`) folds that buffer into the tracked file once
  — keyed on `url`, skipping anything the tracked file already has a row
  for — right before the one daily commit, then empties the buffer.
  `docs/YOUTUBE_DRIP_RUNBOOK.md`'s "Once a day" section has the updated
  commit command.
- `docs/VIDEO_TO_CALENDAR_JOIN.md`: the shelved future project that joins a
  government's video channel, playlist or feed to its own calendar by body
  and date (pilot WO-158, about 5% yield). Read it before touching
  channel enumeration.
- `docs/BREADTH_SWEEP_BRIEF.md`: the brief for the next round of coverage
  work, written 2026-09-10 from four read-only pilots. Platform API first,
  then an honest plain client, browser headers on a 403, headless only for
  JavaScript-drawn links, never past a challenge; a probe before queuing;
  reject reasons split into access and content classes.
- `BACKLOG.md`'s TOC, then the Standing decisions section.
- `BACKLOG_DONE.md`'s 2026-09-09 and 2026-09-10 entries for every sweep's
  funnel, and `rtr-business/research/ENUMERATION_METHODS.md` §155–§180
  for the same from the research side.
- The coverage registry summary,
  `rtr-business/research/coverage_registry/COVERAGE_REGISTRY_SUMMARY.md`,
  for today's numbers with their sources and input timestamps.
