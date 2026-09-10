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
dashboards included, joins these on `gov_id`.

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

### Coverage registry (per government, all of North America)

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

## 4. How coverage is grown: the sweep pattern

Every sweep in `scripts/` follows one shape, and new ones should too:
build the candidate list from the registry CSV with an explicit filter,
confirm "not in Archive" against a **fresh** export, resolve through the
real adapters, dedupe by source URL, flush a report CSV per row so a
re-run resumes, stop after a run of consecutive errors, and write every
outcome back to the research file with a reject reason from
`ENUMERATION_METHODS.md` §23's taxonomy.

**Ryan's ingest rule, verbatim in spirit:** only meetings with video
become pages. Tier 1 (captions the server can fetch) and tier 2 (YouTube
captions the local fetch can get) ingest with segments. Tier 3 (video, no
reachable captions) goes to `scripts/tier3_auto_transcription_queue.txt`
and the cloud worker drips it onto the site. Agenda-only is recorded as
`no-video-found` and never ingested. A host with no video is a legitimate
outcome to show on the dashboards, not a page.

What the 2026-09-09 sweeps established about *where video is*:

| Population | Finding | Implication |
|---|---|---|
| CivicPlus AgendaCenter sites | ~80% carry agendas but no video anywhere, even walked back several years. The ~20% that do link video per meeting resolve fine through the adapter's delegation to YouTube/Granicus/CivicClerk. | AgendaCenter is an agenda host, not a video host. Probe it for the 20%, then move on. |
| "Known platform, no page" | Three quarters had already been rejected once; the re-check still found real pages (two governments with 500–1,000 caption segments were blocked by a platform-name spelling mismatch). | Re-checks of rejected rows are worth it when the reject was made by an earlier, cruder pass. |
| Counties | Limited by stale data, not code: hundreds of NACo domains no longer resolve; several large counties sit behind web firewalls. | Fix the domain list before spending more resolver time. |
| Two-hop and headless candidates | Once a platform is found, roughly half convert to a video page or a queue entry. | Discovery is the bottleneck, not resolution. |

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
   mechanically (regenerate the TOC; take the union of queue and pin
   lines). Budget for the session limit: seven agents at once tripped it
   once; resumable per-row reports meant nothing was lost.

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
- **The 789 governments over 5,000 rejected as "no video found"** stay
  where they are by Ryan's decision; a video-less host is a valid record.

## 7. Where to look first next time

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
