# URL shape mining: what our own held URLs already say about recurring path shapes (WO-272)

Written 2026-09-12. Read this before building a new probe pass against
first-party government domains, before touching
`app/utils/jurisdiction_data/first_party_meeting_paths.csv`, and before
proposing a new platform adapter from a recurring path shape.

## Why

WO-267 (`docs/investigations/platform_fingerprints.md`) measured
platform clues on live homepages and hub pages and found exactly one
discovery-grade win: Hyland OnBase's `/Meetings/ViewMeeting` path
catches 10 of 10 real tenants, while the vendor's own hostname appears
on only 1 of 10 (most real tenants white-label it onto a reseller or
city-owned domain). Ryan's reframing from that finding: the resolver
(`app/platforms/base.py`'s `detect_platform()`) already classifies a
meeting URL by its SHAPE, not by "what platform is this" in the
abstract — so the real question for growing coverage is narrower and
cheaper to answer than it looks: **find a meeting or video URL whose
shape we already recognize, on a government we haven't resolved yet.**

We hold thousands of real meeting/agenda/video URLs already, across the
research file and the Archive's own pages. This WO mines them for
recurring path shapes — zero network requests — and turns the result
into two things: (a) a probe set of first-party path templates worth
trying against an UNKNOWN government's own domain, and (b) the list of
recurring shapes `detect_platform()` does NOT yet recognize.

## Stage 1 — mining, zero fetches

### Sources

1. **`jurisdiction_coverage.csv`** (45,610 rows) — `example_meeting_url`,
   `example_agenda_or_calendar_url`, and `alternate_urls` (semicolon-
   separated; 663 rows carry at least one, 78 of those carry more than
   one). **9,569 raw URLs** collected. Source label `jc_csv`.
2. **The Archive's own page export** — a one-time, read-only pull of
   `GET /internal/export/pages` (paginated at 500/page, no segments,
   `source_url_normalized`/`platform`/`gov_id`/`gov_type`/`video_url`
   only), saved locally to this session's private scratch directory,
   never committed. **8,483 pages, one URL each** (every row here
   produced a real page with video, so its shape is proven, not just
   suspected). Source label `archive_export`.
3. **`wo268_passive_pilot.csv`'s `candidate_hub_url` column** — WO-268
   landed 2026-09-11/12 (confirmed via `ls`, not assumed — the brief's
   own "if it hasn't landed, say so and skip" instruction). 300
   governments where the access ladder had already found nothing; its
   `candidate_hub_url` is a real URL found via DNS/sitemap/Wayback/
   Common Crawl on THAT government's own domain. **263 raw URLs**, all
   confirmed first-party by construction (the URL is on the government's
   own recorded domain). Source label `wo268_passive`. This is the
   bias-correcting source the brief asked for: sources 1-2 only ever
   show a URL that already led somewhere; this one shows URLs found on
   governments that, as of WO-268, still hadn't.
4. **`wo268_hub_path_frequency.csv`** — a fourth, separate, COARSER
   source. This file is WO-268's own aggregated first-PATH-SEGMENT
   frequency table (1,127 distinct patterns, not full path templates)
   over the same 300-government "nothing found" population, already
   counted by that WO. Kept separate rather than merged into the
   per-URL mining above, since its granularity differs (first segment
   only, no per-row distinct-government/distinct-host count available)
   — see "What the data cannot show" below. Source label
   `wo268_hub_freq`. **2,148 raw rows** (its own `count` column, summed).

**18,315 individual URLs** went through the per-URL pipeline (sources
1-3); source 4 contributes its own 1,127 pre-aggregated rows on top.

### Method

For every URL: split host and path, lowercase, and normalize the path
into a template — each path segment becomes `{id}` (pure digits),
`{guid}` (a real GUID, dashed or bare-32-hex), `{date}` (`YYYY-MM-DD`/
`YYYYMMDD`/`MM-DD-YYYY`), `{token}` (16+ hex chars, or 20+ mixed-case/
digit chars that aren't a plain word-slug), or `word{id}` for a
word-then-digits segment like `clip7460`; everything else is kept
literally. Query-parameter NAMES are kept (sorted, lowercase), values
dropped. Rows are grouped and counted by `(source, host_family,
template)`.

`host_family` is **first-party** when the URL's host matches (or is a
subdomain of) that row's own recorded `domain` (available for `jc_csv`
and `wo268_passive` directly); otherwise it's **vendor** when the host
contains one of ~45 known vendor substrings read directly out of
`detect_platform()`'s own dispatch code (`granicus.com`, `civicclerk.com`,
`iqm2.com`, …, plus a few real vendor products with no rtr-deeplink
adapter yet — `boarddocs.com`, `laserfiche.com`, `novusagenda.com`,
`hylandcloud.com`) **or** — for a host with no known name and no
recorded government domain to compare against (every `archive_export`
row) — when that exact host is shared by 3 or more distinct governments
in this combined dataset (a data-driven "this is a shared tenant host"
signal, not a guess). Everything else defaults to first-party, which is
the safe default for a government's own, otherwise-unclassified domain.

Each template is labeled, checking in this order:

- **`known`** — `detect_platform()` is actually RUN (not guessed)
  against a real example URL of this template, and recognizes it.
- **`meeting-shaped-unknown`** — recurs ≥5 times across ≥3 distinct
  hosts, carries a meeting/agenda/minutes/council/board/video/stream
  word, and `detect_platform()` returns `"unknown"`.
- **`first-party`** — anything left on a first-party host.
- **`vendor-other`** — anything left on a vendor-classified host that
  clears neither bar above (this fourth label isn't one the brief named;
  it exists so every row gets exactly one label instead of a gap — see
  below).

**A real bug found and fixed while building this**: the mining script
originally imported `app/platforms/base.py` from a hardcoded path to
the MAIN checkout (`/Users/mroconnell/Documents/rtr-deeplink`), not this
worktree. The main checkout turned out to be several commits BEHIND
this worktree (missing the Wistia/BoxCast platform registrations,
confirmed live by diffing the two files), which silently mislabeled
every real BoxCast/Wistia URL in the sample as `vendor-other` (unknown)
instead of `known`. Fixed by resolving the import relative to the
script's own file location instead of a hardcoded path — a worktree-
specific trap worth remembering for any future script that imports
`app`/`archive` code by an absolute path rather than relative to itself.

### Results

| Source | Raw URLs | Templates | known | meeting-shaped-unknown | first-party | vendor-other |
|---|---|---|---|---|---|---|
| `jc_csv` | 9,569 | 2,979 | 1,257 | 53 | 1,632 | 37 |
| `archive_export` | 8,483 | 1,204 | 1,100 | 3 | 99 | 2 |
| `wo268_passive` | 263 | 216 | 0 | 1 | 215 | 0 |
| `wo268_hub_freq` | 2,148 | 1,127 | 0 | 14 | 1,113 | 0 |
| **Total** | **20,463** | **5,526** | **2,357** | **71** | **3,059** | **39** |

(`wo268_hub_freq`'s `known`/`meeting-shaped-unknown` counts are computed
the same way against its own `example_url` column, but its "rows" are
its own pre-aggregated `count`, not a per-URL count — see the caveat
above.)

### The headline finding: CivicPlus's self-hosted `/AgendaCenter` has no path-based dispatch entry

The single most common recurring first-party template across BOTH proven
sources is the bare path `/agendacenter`:

| Source | Distinct governments | Distinct hosts | Rows | Example |
|---|---|---|---|---|
| `jc_csv` | 1,209 | 1,205 | 1,215 | `https://welcometoatmore.com/AgendaCenter` |
| `archive_export` | 245 | 245 | 250 | `https://www.voluntown.gov/AgendaCenter` |
| `wo268_passive` | 20 | 20 | 20 | `https://www.natronacounty-wy.gov/AgendaCenter` |
| `wo268_hub_freq` | — | — | 18 | `https://www.natronacounty-wy.gov/AgendaCenter` |

All four sources agree, including the bias-correcting WO-268 population.
245 of these are *already-archived real pages with video* (YouTube,
Cablecast, others) — confirmed by inspecting the raw export: every one
of them carries the DELEGATED platform (`youtube`/`cablecast`/etc.), not
`platform=civicplus`, which means these pages exist only because a
dedicated sweep script (WO-174 and its follow-ups) called `civicplus.py`
directly — `detect_platform()` itself returns `"unknown"` for every one
of them, because its CivicPlus branch checks the HOSTNAME
(`"civicplus.com" in netloc or "civicplus" in netloc`), and a self-hosted
tenant (CivicPlus installed on the government's own domain) never
matches that.

This is exactly the shape `detect_platform()` already has a fix for —
just not applied here. Hyland/OnBase's own branch was widened
specifically because real tenants run on arbitrary reseller domains with
no shared hostname (`if "/meetings/viewmeeting" in path: return
"hyland"`, no netloc check at all). Self-hosted CivicPlus is the
identical problem and has no equivalent path check. Filed as its own
`BACKLOG.md` entry (`[JUST-DO-IT]` `[EASY]`, grouped with the file's
other `detect_platform()` entries) rather than fixed here, since Stage 1
is analysis-only per this WO's scope — see that entry for the exact fix
and the precedent it follows.

This is NOT a new video-coverage lead on its own: CivicPlus AgendaCenter
sites are already measured (`CLAUDE.md`) at ~80% agenda-only, no video
anywhere, and WO-174's dedicated sweep across the entire 14,553-
government CivicPlus-candidate population is already closed out
(`docs/COVERAGE_HANDOVER.md` §6). What this finding adds is narrower: any
OTHER path that reaches a self-hosted AgendaCenter URL — a hop-link
scorer result, a passive-discovery candidate (WO-268 already found 20
this way), a reader's own paste — gets weaker generic handling today
instead of the adapter that already knows how to walk it.

### Full top-40 tables

**`meeting-shaped-unknown`** (71 total; the adapter/dispatch lead list —
all 71 turned out to be `first-party` host_family; see "What this data
shows" below for why vendor-host shapes didn't clear this bar), top 40
by distinct governments, `jc_csv`/`archive_export`/`wo268_passive`
sources:

| Source | Govs | Hosts | Rows | Template |
|---|---|---|---|---|
| jc_csv | 1,209 | 1,205 | 1,215 | `/agendacenter` |
| archive_export | 245 | 245 | 250 | `/agendacenter` |
| jc_csv | 131 | 131 | 131 | `/{id}/agendas-minutes` |
| jc_csv | 72 | 72 | 72 | `/city-council` |
| jc_csv | 70 | 70 | 70 | `/meetings` |
| jc_csv | 65 | 65 | 65 | `/agendas-minutes` |
| jc_csv | 49 | 49 | 49 | `/{id}/city-council` |
| jc_csv | 37 | 37 | 37 | `/council` |
| jc_csv | 34 | 33 | 34 | `/{id}/boards-commissions` |
| jc_csv | 34 | 34 | 34 | `/agendas` |
| jc_csv | 29 | 29 | 29 | `/government/city-council` |
| jc_csv | 26 | 26 | 26 | `/government/city_council/index.php` |
| jc_csv | 23 | 23 | 23 | `/agendasandminutes` |
| jc_csv | 22 | 22 | 22 | `/county-board` |
| wo268_passive | 20 | 20 | 20 | `/agendacenter` (independent confirmation) |
| jc_csv | 19 | 19 | 19 | `/boards` |
| archive_export | 18 | 18 | 42 | `/meetings/{token}` (openpublica.com) |
| jc_csv | 18 | 18 | 18 | `/town-council` |
| jc_csv | 17 | 17 | 17 | `/{id}/boards-committees` |
| jc_csv | 16 | 16 | 16 | `/citycouncil` |
| jc_csv | 16 | 16 | 16 | `/minutes` |
| jc_csv | 16 | 16 | 16 | `/{id}/agendas-and-minutes` |
| jc_csv | 15 | 15 | 15 | `/board` |
| jc_csv | 13 | 13 | 13 | `/agendacenter/{token}` |
| jc_csv | 12 | 12 | 12 | `/mayor-and-council` |
| jc_csv | 10 | 10 | 10 | `/mayor-council` |
| jc_csv | 10 | 10 | 10 | `/village-council` |
| jc_csv | 9 | 9 | 9 | `/{id}/public-meetings` |
| jc_csv | 9 | 9 | 9 | `/government/city_council.php` |
| jc_csv | 9 | 9 | 9 | `/village-board` |
| jc_csv | 8 | 8 | 8 | `/meeting-minutes` |
| jc_csv | 7 | 7 | 7 | `/council-members` |
| jc_csv | 7 | 6 | 7 | `/{id}/agenda-center` |
| jc_csv | 7 | 7 | 7 | `/government/agendas___minutes/index.php` |
| jc_csv | 7 | 7 | 7 | `/boards-commissions` |
| jc_csv | 7 | 7 | 7 | `/government/boards-and-committees` |
| jc_csv | 6 | 6 | 6 | `/hueytownal.gov/1201/boards` (`/{id}/boards`) |
| jc_csv | 6 | 6 | 6 | `/{id}/agendas` |
| jc_csv | 6 | 6 | 6 | `/towncouncil` |
| jc_csv | 6 | 6 | 6 | `/government/meetings` |
| jc_csv | 6 | 6 | 6 | `/agendas-and-minutes` |

`wo268_hub_freq`'s own 14 `meeting-shaped-unknown` rows (same bias-
correcting population, coarser first-segment granularity): `/council-
meeting` (25), `/meetings` (21), `/boards` (19), `/agendacenter` (18),
`/board-county-commissioners` (11), `/city-council-members` (9),
`/city-council` (7), `/city-council-regular-meetings` (7), `/boards-and-
comissions` (7), `/town-council` (7), `/weed-board` (6), `/board-of-
commissioners` (5), `/board-equalization` (5), `/commissions-boards`
(5). These overlap heavily with the per-URL list above (`/meetings`,
`/boards`, `/agendacenter`, `/city-council`-family, `/town-council`) —
the bias-correcting source agrees with the proven-URL sources on which
generic names recur, which is exactly the validation Stage 2 exists to
turn into a measured yield rather than a guess.

**`vendor-other`** (39 total — the genuinely-new-platform lead list; all
shown, since none is long):

| Govs | Hosts | Rows | Template | Example |
|---|---|---|---|---|
| 6 | 1 | 6 | `/m/v/redesign4?fp&pid` | elocallink.tv |
| 5 | 1 | 5 | `/m/{token}` | redtaperecordings.com (our own site) |
| 3 | 1 | 3 | `/portal/browse.aspx?id&repo` | portal.laserfiche.com |
| 3 | 1 | 3 | `/meetings` | watchctv.org |
| 2 | 2 | 2 | `/` (bare root) | cablecast.tv tenants |
| 2 | 1 | 2 | `/portal/browse.aspx?repo` | portal.laserfiche.com |
| 2 | 1 | 2 | `/publishpage/index?cid&p&ppid` | meetings.municode.com |
| 2 | 1 | 2 | `/adahtmldocument/index?cc&ip&me` | meetings.municode.com |
| 2 | 1 | 2 | `/milocator/default.aspx?fips` | mcgi.state.mi.us |
| 2 | 1 | 2 | `/company/{id}/admin/dashboard` | linkedin.com |
| 2 | 1 | 2 | `/uas/login?session_redirect` | linkedin.com |
| 2 | 1 | 2 | `/j/{id}?pwd` | zoom.us |
| remaining 27 templates | 1 each | 1-2 each | assorted | boarddocs, vimeo bare-tenant-path, Google Drive, Facebook, ecode360, destinyhosted's `agenda_publish.cfm`, zoom `/rec/play/…`, invintus direct `.mp4`, utah.gov `/pmn/index.html`, meetings.municode.com `MeetingsPage` |

**None of the 39 `vendor-other` templates reaches the ≥10-distinct-
government bar** the WO brief set for "worth a new adapter" — the
largest is 6. Two are worth a one-line note rather than a BACKLOG entry:
`/m/{token}` on `redtaperecordings.com` is our OWN internal permalink
leaking into `example_meeting_url` (the exact data-quality gap WO-267
already found and filed — see that WO's doc and `BACKLOG.md`'s existing
entry; not re-filed here). The `meetings.municode.com` variants
(`PublishPage`, `AdaHtmlDocument`, `MeetingsPage`) are a different
Municode product from the already-registered `municode_meetings.com`
adapter, each at n=1-2 — a real, distinct shape, but too thin to act on;
noted here for a future session that happens to be working Municode
territory anyway.

**`known`**, sanity-check of the labeling (top platforms by distinct
governments, both proven sources):

| Source | Platform | Govs | Template |
|---|---|---|---|
| archive_export | youtube | 1,500 | `/watch?v` |
| jc_csv | youtube | 715 | `/watch?v` |
| archive_export | granicus | 405 | `/mediaplayer.php?clip_id&view_id` |
| archive_export | granicus | 285 | `/mediaplayer.php?clip_id&view_id` (variant) |
| jc_csv | swagit | 229 | `/videos/{id}` |
| archive_export | swagit | 228 | `/videos/{id}` |
| jc_csv | granicus | 220 | `/player/clip/{id}?view_id` |
| archive_export | civicclerk | 216 | `/event/{id}/media` |
| archive_export | granicus | 204 | `/player/clip/{id}?view_id` (variant) |
| archive_export | granicus | 200-201 | `/player/clip/{id}` |
| jc_csv | youtube | 177 | `/channel/{token}` |
| jc_csv | civicclerk | 166 | `/event/{id}/media` |
| jc_csv | granicus | 165 | `/player/clip/{id}` |
| archive_export | swagit | 157 | `/videos/{id}` (variant) |

Matches expectation — the resolver's existing dispatch already owns
this population; nothing new here, included to show the labeling
pipeline agrees with known ground truth.

**`first-party`** (3,059 total; top by distinct governments — the raw
candidate pool Stage 2 draws its probe templates from, before excluding
the ones that are only navigation noise):

| Source | Govs | Hosts | Rows | Template |
|---|---|---|---|---|
| jc_csv | 188 | 188 | 188 | `/` (bare root) |
| jc_csv | 113 | 113 | 113 | `/calendar` |
| jc_csv | 96 | 96 | 96 | `/calendar-of-events` |
| jc_csv | 44 | 44 | 44 | `/civicalerts.aspx?aid` |
| archive_export | 43 | 43 | 43 | `/` (bare root — see caveat below) |
| jc_csv | 41 | 40 | 41 | `/{id}` |
| jc_csv | 38 | 38 | 38 | `/government/{token}/index.php` |
| jc_csv | 36 | 36 | 36 | `/events` |
| jc_csv | 34 | 34 | 34 | `/calendar.aspx?cid` |
| jc_csv | 31 | 31 | 31 | `/calendar.aspx?cid&day&month&view&year` |
| jc_csv | 28 | 28 | 28 | `/calendar.aspx` |
| jc_csv | 25 | 25 | 26 | `/en/index.aspx` |
| jc_csv | 25 | 25 | 25 | `/weblink` |
| jc_csv | 24 | 24 | 25 | `/documentcenter/view/{id}/{token}` |
| jc_csv | 22 | 22 | 22 | `/commissioners` |
| jc_csv | 21 | 21 | 21 | `/calendar.php` |
| jc_csv | 19 | 19 | 19 | `/calendar.aspx?eid` |
| jc_csv | 19 | 1 | 19 | `/profile.php?id` (Facebook) |
| jc_csv | 14 | 14 | 14 | `/{token}` |
| jc_csv | 13 | 13 | 13 | `/fr` (bilingual Canadian sites) |
| jc_csv | 12 | 12 | 12 | `/feed` |
| wo268_passive | 12 | 12 | 12 | `/{token}` |
| jc_csv | 11 | 11 | 11 | `/government` |
| jc_csv | 10 | 10 | 10 | `/archive.aspx` |
| jc_csv | 10 | 1 | 10 | `/milocator/default.aspx?fips` (MI locator, not first-party) |
| jc_csv | 9 | 9 | 9 | `/departments/commissioners` |

Most of this list is generic CMS navigation (calendar pages, a bare
homepage, `/events`), not a meeting-specific signal — this matches
WO-268's own finding about its hub-frequency table exactly ("probe named
platform paths, not the raw frequency table's top entries"). The 43-gov
`archive_export` bare-root row is a separate, genuine data-quality
finding, not a platform shape: 43 already-archived real pages have a
`source_url_normalized` that is literally just a bare domain root with
no path at all — worth a look by whoever next touches ingest URL
storage, but out of this WO's scope to chase further.

## Stage 2 — bounded validation

Ryan's brief named illustrative examples (`/AgendaCenter`,
`/government/city-council/agendas-minutes`, `/meetings`, `/minutes-
agendas`, a `/{number}/…-Agendas-Minutes` shape, `/Archive.aspx?AMID=
{id}`, `/DocumentCenter/…`) and asked to probe "whatever the data
actually shows." The data shows a cleaner, shorter list than the
illustrative one, once `/AgendaCenter` is set aside as already
exhaustively probed (see above) and the `{id}`/`{token}` variants are
set aside as needing an id this probe has no way to guess cheaply (the
bare-path question — "does a path with this NAME exist at all" — is the
one a single-shot probe can actually answer). Nine templates were
probed: `/Agendas-Minutes`, `/City-Council`, `/meetings`, `/government/
city-council`, `/AgendasAndMinutes`, `/boards`, `/council`,
`/DocumentCenter`, `/town-council`.

**Candidates**: governments in `jurisdiction_coverage.csv` with
population ≥5,000, a non-blank `domain`, both
`suspected_meeting_link_provider` and `suspected_video_provider` blank,
and `reject_reason` blank or in the "nothing found" family
(`no-platform-link-found`, `no-platform-signature`, `no-meeting-nor-
video`, `no-meetings-found`) — 60 governments, taken in file order (no
filter against WO-268's own 300-government sample; the brief says
disjointness isn't required here).

**Method**: one plain `HONEST_HEADERS` GET per (government, template),
one government's host at a time, 2.2s between requests, stopping
outright (marking every remaining template for that government
`skipped-host-blocked`, never retrying) on a 403 or a Cloudflare/
captcha-style challenge marker. A 200 is checked for real content, not
trusted on its own (WO-260's finding: several vendors answer any bogus
path with a 200) — "real" means the page's own body names THIS
government (a name-token match after stripping "city/town/village/
county/township/of") AND carries a meeting word, AND the body is at
least 800 bytes (added after a live false-positive, see the caution
below).

**Results**: 541 requests across 60 governments (9 templates x 60,
minus 4 skipped once one government's host was marked blocked after its
first template hit a 403).

| Template | Tried | Real hit | Soft-404/shell | 404 | Blocked | Error/timeout |
|---|---|---|---|---|---|---|
| `/City-Council` | 56 | 2 | 12 | 30 | 0 | 12 |
| `/council` | 56 | 2 | 9 | 32 | 0 | 13 |
| `/meetings` | 56 | 1 | 8 | 35 | 0 | 12 |
| `/government/city-council` | 56 | 1 | 15 | 28 | 0 | 12 |
| `/AgendasAndMinutes` | 56 | 1 | 6 | 37 | 0 | 12 |
| `/Agendas-Minutes` | 60 | 0 | 7 | 35 | 4 | 14 |
| `/boards` | 56 | 0 | 8 | 34 | 0 | 14 |
| `/DocumentCenter` | 56 | 0 | 9 | 34 | 0 | 13 |
| `/town-council` | 56 | 0 | 5 | 37 | 0 | 14 |

**3 of the 60 governments probed (5%) got a real hit on at least one of
the 9 templates** — Pinson city AL (`pinsonal.gov`, hits on
`/City-Council`, `/government/city-council`, and `/council`, all real,
substantially-sized pages, 182-187KB each), Fairfield city AL
(`fairfieldal.us`, hits on `/meetings`, `/AgendasAndMinutes`, and
`/council`, 27KB each, genuinely different sizes confirming distinct
real content, not one shell), and Robertsdale city AL
(`robertsdale.org`, `/City-Council`, 19.8KB). `/City-Council` and
`/council` are the only two templates that found a real page on more
than one government; the remaining six templates in the probed set
(`/Agendas-Minutes`, `/boards`, `/DocumentCenter`, `/town-council`, plus
the two single-hit templates above once their one hit is subtracted)
found zero real pages in this sample. `/Agendas-Minutes` had the most
blocks (4) despite the widest sample-size run (60, since it ran before
any host of this WO's own run had been marked blocked).

None of the 3 real hits carries a video link on its own — all three are
generic municipal navigation pages (a council roster/contact page, an
agendas listing), consistent with WO-268's own finding that a named-path
hit still needs a further hop to reach a platform link, not a video
source itself. This probe answers "does the NAME exist on this
domain," which is the narrower, cheaper question Stage 2 was built to
answer — it does not by itself measure video yield.

## What this data cannot show

- **`host_family`'s data-driven fallback (a host shared by ≥3 distinct
  governments counts as "vendor" even with no name for it) is a
  heuristic, not ground truth.** It will misclassify a genuinely
  first-party host that happens to recur for an unrelated reason (a
  shared regional government IT consortium hosting several small towns'
  sites, say) as "vendor". None confirmed in this sample, but worth
  knowing before trusting the vendor/first-party split on a template
  with a small, unfamiliar host count.
- **`wo268_hub_freq` is a different granularity (first path segment
  only) from the other three sources (full normalized path template)**,
  and carries no per-row distinct-government/distinct-host count — kept
  as its own source rather than merged in, so its numbers should not be
  read as directly additive with the others'.
- **The `≥5 rows across ≥3 hosts` bar for `meeting-shaped-unknown` is a
  threshold choice, not a derived one** — a genuinely rare but real
  platform shape with 2-4 examples would be filed under `first-party` or
  `vendor-other` instead and could be missed by a reader who only reads
  the named label.
- **Stage 1 has zero information about whether a first-party template
  actually carries video** once fetched — that is exactly what Stage 2
  measures, and only for the 9 templates and 60 governments actually
  probed; the other ~50 first-party templates in the top-40 table above
  are unmeasured.
- **A 200 response's raw body length matters, confirmed live mid-run**:
  Geneva County, AL (`genevacounty.us`) answered `/City-Council`,
  `/meetings`, `/government/city-council`, and `/AgendasAndMinutes` —
  four DIFFERENT probed paths — with the same ~485-500-byte generic page
  each time, which trivially contains both the county's own name and a
  meeting word in a shared nav/footer. This is exactly WO-260's "a 200
  proves nothing" finding, one level more specific: without the 800-byte
  floor added after this was caught, this run's real-hit count would
  have been inflated by 4 false positives from one government alone.
- **Stage 2's 60-government, population≥5,000, US-only sample is a
  pilot, not a full-scale run**, and its 3 real hits were all navigation/
  contact pages, not video — see the recommendation below for what a
  full pass, and a further hop past a real hit, should change.

## Recommendation for a full-scale own-domain probe pass

1. Fix the `detect_platform()` CivicPlus self-hosted `/AgendaCenter`
   dispatch gap first (the filed `BACKLOG.md` entry) — it's a three-line,
   precedented change that makes every OTHER method in this repo that
   finds a self-hosted AgendaCenter URL (hop-link scoring, WO-268's
   passive discovery, a reader's own paste) get the adapter that already
   knows how to look for delegated video.
2. Wire the measured-yield templates from
   `app/utils/jurisdiction_data/first_party_meeting_paths.csv` into
   `scripts/wo147_access_ladder_sweep.py`'s hop step (or whatever WO-268's
   full-scale pass becomes) as an EARLY candidate hop — a named path is
   cheaper and more specific than the existing generic hop-link-word
   scan — and add one more hop past a real hit (the same
   `find_platform_link()`/hop-link-scorer step every other rung already
   uses), since all 3 of this pilot's real hits were navigation pages,
   not a platform link themselves. Per this WO's scope, none of this
   wiring is done here.
3. Run Stage 2's probe at full scale (the whole ~30,000-row "nothing
   found, has a domain" population, not 60) before trusting the measured
   yield numbers as representative — a 60-government pilot is enough to
   decide whether a template is worth wiring in, not enough to set a
   production threshold.
4. Re-run this mining pass after WO-268's eventual full-scale pass lands
   (today's run only had its 300-government pilot) — a larger
   bias-correcting sample may surface first-party templates this pass's
   smaller one didn't reach ≥5/≥3 on.
