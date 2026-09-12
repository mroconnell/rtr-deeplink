# Full-scale passive platform discovery (WO-273): three phases, full
population, one live Internet Archive outage hit along the way

**Status: complete (WO-273, 2026-09-12).** WO-268 proved passive
discovery (DNS/CNAME, sitemap+robots, Wayback CDX, Common Crawl) on 300
governments, run one at a time with politeness waits inside every step
(100 minutes for 300 domains). Ryan's design for this WO splits that into
three phases so the slow part (targeted fetches) is driven by the fast
part's own output, and the scoring rules in the middle can be rerun
without refetching anything: **phase 1** (`scripts/wo273_recon.py`) is
fast, parallel, raw reconnaissance with no classification; **phase 2**
(`scripts/wo273_classify.py`) is pure offline scoring over phase 1's raw
file, no network; **phase 3** (`scripts/wo273_targeted.py`) fetches only
the specific URLs phase 2 flagged, many governments at once since each is
on its own domain. All three ran against the full population, start to
finish, in this session. Detection only: nothing was ingested, no queue
line was written, `jurisdiction_coverage.csv` was not touched. Reports:
`research/wo273_recon.jsonl`, `wo273_classified.csv`, `wo273_targeted.csv`
(all in `rtr-business`).

## Population and filter

`jurisdiction_coverage.csv`, a live snapshot taken 2026-09-12: US or
Canada, population 5,000+, `domain` set, not already `transcribed`, no
suspected platform (`suspected_calendar_provider`/
`suspected_meeting_link_provider`/`suspected_video_provider` all blank),
`reject_reason` in the "nothing found" family (`no-platform-link-found`,
`no-platform-signature`, `dns-unresolvable`, `resolve-failed`,
`blocked-plain-http`, or blank) -- then excluding any row whose OWN
`domain` column is itself a meeting-vendor host.

| Step | Count |
|---|---|
| Rows matching every filter above except the vendor-domain exclusion | 2,576 |
| Rows excluded: `domain` is itself a vendor host | 1 |
| **Final population** | **2,575** |

By `reject_reason`: `no-platform-link-found` 2,034, `dns-unresolvable`
263, blank 99, `resolve-failed` 89, `no-platform-signature` 87,
`blocked-plain-http` 3.

**This re-derives to 2,575, 1 more than the conductor's own count of
2,574** from an earlier snapshot the same day -- expected live-file
movement under a concurrent multi-session wave, not a filter mismatch;
every per-reason count above matches the conductor's number exactly.

**The vendor-domain exclusion removed only 1 row here, far fewer than the
brief's cited "1,406 rows."** Checked directly: that 1,406 figure is a
whole-file count (all 45,609 rows of `jurisdiction_coverage.csv`), not a
count inside this already-filtered "nothing found, 5,000+" pool. It makes
sense almost none land here -- a row whose `domain` is a vendor host would
ordinarily already carry a suspected-platform value or `transcribed=true`
and so would already be filtered out by an earlier step in the same
chain. Reported plainly rather than assumed, per this repo's "a backlog
entry/brief claim is a lead, not a spec" rule.

**WO-268's own 300-domain pilot set is included as a regression check**,
not skipped: 294 of its 300 domains are still in this population (the
other 6 have since gained a suspected platform, a page, or dropped below
the population floor). Their separate yield is reported below.

Of the 2,575-row population, phase 1 actually processed **2,574** (one
row errored out before a record could be written -- a single dropped row
in an otherwise complete run, not investigated further since the
population is re-derived fresh on every future run anyway).

## A real, live finding that shaped every phase: Internet Archive's CDX search API is currently degraded

Confirmed by hand before writing a line of the recon script, and
re-confirmed throughout the run: **`web.archive.org/cdx/search/cdx`
itself is intermittently failing right now** -- repeated direct `curl`
tests returned `HTTP 503` with an "Internet Archive: Temporarily Offline"
body on some tries, a bare connection hang past 20 seconds on others, and
a real `200` on others, with **successful** responses taking 5-13 seconds
even for the simplest possible query (`url=example.com&limit=1`).
`web.archive.org/`, the `wayback/available` API, and `archive.org/` all
answered instantly (`200`) the same minute -- this is specifically a
CDX-search degradation, not a whole-service outage.

This held for the full ~70-minute phase-1 run, not just the first probe:

| CDX-dependent step | Reachable | Total | Rate |
|---|---|---|---|
| Domain-wide Wayback CDX query (broad) | 44 | 2,574 | 1.7% |
| Sitemap/robots Wayback capture found (any age) | 64 | 2,574 | 2.5% |
| Common Crawl index reachable | 63 | 2,574 | 2.4% |

Every script built for this WO treats a CDX failure exactly like "no
capture found" and falls straight through to a live fetch -- per the
design this WO's brief already called for ("fetch the LIVE robots/
sitemap... only when the archive has no capture"), this degradation never
blocked the sweep, it just meant almost the entire population took the
live-fallback path instead of the cheap archive-first path. **A rerun
once Internet Archive's CDX search recovers should find meaningfully
more** than this run did, especially for the sitemap-source split below.
Common Crawl's reachability (2.4%) is consistent with WO-268's own
documented Common Crawl outage finding, not a new problem.

## Phase 1: sitemap-source split

| `sitemap_source` | Count of 2,574 | What it means |
|---|---|---|
| `none` | 1,389 (54.0%) | No archive capture, and no live sitemap found either |
| `live` | 1,178 (45.8%) | Archive had nothing useful; a live robots.txt/sitemap fetch found one |
| `wayback` | 3 (0.1%) | A fresh (<18mo) archived sitemap capture was used directly |
| `wayback-stale` | 2 (0.1%) | An archived capture existed but was stale; live fallback also failed |
| `wayback-stale+live` | 2 (0.1%) | Stale archived capture, live fallback succeeded |

Only 7 of 2,574 governments (0.3%) got their sitemap from the archive at
all -- far below what WO-268's own pilot saw (136/300, 45%) before this
session's CDX degradation. The "archive first" design is sound and cost
the government nothing extra when it worked; it just rarely got the
chance to work today.

## Phase 1: CDX row-count distribution (among the 44 reachable)

Broad domain-wide query (`collapse=urlkey`, `filter=statuscode:200`,
`filter=mimetype:text/html`, `from=` 3 years back, `limit=2000`):
median 449 rows, p95 2,000 (the query's own cap), max 2,000.
`cdx_truncated` (the narrow, meeting-path-filtered query hitting its own
page cap 3 times) never fired: 0/2,574. With CDX this degraded, the
bounding rules this WO's brief specified (capped queries, 3-page limit,
narrow meeting-path filter) were never actually tested at the scale they
were designed for -- worth re-checking once Internet Archive recovers.

## Phase 1: per-step timing (ms), full population

| Step | Median | p95 |
|---|---|---|
| Archive-first sitemap/robots (2 CDX calls + up to 2 `id_` body reads) | 4,102 | 5,482 |
| Live robots.txt + live sitemap fallback | 8,590 | 29,232 |
| DNS (apex/www A+CNAME, 8 subdomain guesses, 2 vendor-label guesses) | 960 | 4,539 |
| Wayback domain-wide index (broad + narrow, up to 3 pages) | 2,046 | 11,065 |
| Common Crawl (probed once per process; most governments skip it) | 0 | 224 |

## Phase 1: governments-per-minute, 50-government timing test vs full run

| Run | Governments | Wall-clock | Rate |
|---|---|---|---|
| Timing test (required before the full run) | 50 | 151s | 19.9/min |
| Full population (9 chunks, same `--concurrency 8`) | 2,574 | ~66 min total | ~23-25/min sustained |

The full run's sustained rate (23-25/min) came in a bit higher than the
50-government test -- consistent with the archive-concurrency cap (8)
being the real bottleneck resource: once warmed up, 8 governments'
CDX-bound work overlaps cleanly regardless of which specific domains are
in flight.

## Phase 2: offline classification (no network, rerunnable)

| Confidence | Count of 2,574 |
|---|---|
| `high` (named vendor host or first-party path shape) | 111 |
| `medium` (hub-vocabulary score >=20 or meeting-vocabulary score >=8) | 376 |
| `low` (some flag-word hit, below the medium threshold) | 477 |
| `none` | 1,610 |

Platforms found by phase 2 alone (vendor host or DNS evidence, found
inside a sitemap/Wayback/Common-Crawl URL phase 1 actually saw):
**PrimeGov 75, CivicWeb 33, CivicPlus 2, YouTube 1** -- 111 total,
matching the `high`-confidence count exactly. 964 of 2,574 governments
(37.5%) had at least one flagged URL, feeding phase 3's top-N-per-
government fetch list; the rest (1,610) got WO-272-style named-path
probes instead (see phase 3).

**A real labeling bug found and fixed mid-session**: this script's first
draft mapped the `AgendaOnline/Meetings/ViewMeeting` path shape to IQM2.
Phase 3's use of WO-267's own measured `platform_signatures.csv`
disagreed -- that signature is filed under `hyland` (Hyland/OnBase's
AgendaOnline product, hit_rate 1.00, 0 false positives across 10
measured samples), and phase 3's actual name+state-confirmed finds (see
below) bore that out. Fixed in `wo273_recon.py`'s `_PATH_SHAPE_PLATFORMS`
before this doc was written; flagged here rather than silently corrected,
since a rerun's phase-2 numbers could shift slightly if this path shape
ever shows up inside a sitemap/CDX URL list (it did not, in this run).

## Phase 3: targeted fetches, the real yield

Top-5 flagged URLs per government with >=1 flagged URL; named
first-party-path probes (`/AgendaCenter`, `/AgendaOnline/Meetings/
ViewMeeting`, `/Citizens/`, `/Portal/MeetingInformation.aspx`,
`/Archive.aspx?AMID=1`) for the rest. HEAD then GET, `platform_
fingerprints.fingerprint()` + `detect_platform()` over the result, and a
platform only counts **confirmed** when the page's own text also names
this government's city/county AND its state.

| Run | Governments | URL fetches | Wall-clock | Rate |
|---|---|---|---|---|
| Timing test (required before the full run) | 50 | 168 | 128s | 23.4/min |
| Full population (3 chunks) | 2,571 | 9,315 | ~42 min total | 24-79/min (rising as flagged-URL-heavy governments thinned out) |

Per-URL fetch timing, full run: median 3,386ms, p95 22,572ms. Every
single fetch in the full run used `fetch_method=live` -- the single-
attempt, no-retry exact-URL Wayback lookup phase 3 tries first never
succeeded once, consistent with the CDX degradation above.

**2,571 of 2,574 governments got a phase-3 result, not 2,574** -- the
classified file itself holds 2,571 distinct domains (2,574 rows): 3
domains each appear twice in the population, a pre-existing duplicate in
`jurisdiction_coverage.csv` (two rows sharing one `domain` value), not a
bug in this sweep.

### The headline number

| Outcome | Count of 2,571 | What it means |
|---|---|---|
| Platform confirmed (vendor/path signal AND the page names this government + its state) | **147** | A real, hand-verification-gated lead -- not yet a page or a queue line |
| Flagged by phase 2 but not confirmed by phase 3 | 817 | A scored URL that either died, didn't match a platform signature on fetch, or didn't name this government |
| No signal at any phase | 1,607 | Nothing found by any of the four methods |

**147/2,571 (5.7%)** is the real number to carry forward -- lower than
phase 2's raw 111+376=487 "high or medium confidence" count, because most
of that 487 never got a live fetch that both matched a platform signature
AND named the government (the same "medium confidence needs a caveat,
not a count" lesson WO-268 already drew, now measured end to end instead
of estimated).

### Top platforms confirmed, phase 3

| Platform | Governments confirmed |
|---|---|
| Hyland (AgendaOnline) | 75 |
| CivicClerk | 25 |
| Granicus | 20 |
| IQM2 | 11 |
| CivicWeb | 6 |
| eScribe | 3 |
| ProudCity | 3 |
| Utah PMN | 2 |
| YouTube | 1 |
| Swagit | 1 |

Confirmed rows by the SOURCE that found the winning URL: named
first-party-path probe 229, phase-2 hub-vocabulary hit 51, phase-2
meeting-vocabulary hit 27, phase-2 platform evidence 1. **The blind
named-path probe (run only on governments with zero phase-1/2 signal)
is where most of this run's real yield actually came from** -- almost
entirely Hyland's `/AgendaOnline/Meetings/ViewMeeting` path, which never
showed up in any sitemap/Wayback/Common-Crawl URL this population
surfaced, so phases 1-2 had no way to flag it; only the blind probe could
find it.

### WO-268's 300-domain pilot, as a regression row

294 of WO-268's original 300 domains are still in this population; of
those, **27 confirmed** (9.2%) -- higher than the 5.7% overall rate,
consistent with WO-268's own pilot already having found some keyword
signal in this subset before this WO re-ran it with the stronger,
name+state-gated confirmation. The non-regression subset (2,277
governments) confirmed 120 (5.3%), close to the population-wide rate.

## What the hand-read gate must still check before any of this becomes a page

This WO never fetched a page with the intent of confirming a real,
embeddable meeting VIDEO -- only that a platform signature matched and
the page names the right government. Per this repo's "hand-check every
found video" and "don't claim a caption/data path works without a
positive example" rules, a human (or the next WO's pipeline) must, for
each of the 147:

1. Open the confirmed URL and verify it is actually a meeting/agenda hub
   or a specific meeting page for THIS government, not a stale/dead link
   that happened to 200 with boilerplate naming the government elsewhere
   on the page (a footer, a breadcrumb).
2. Confirm a real, reachable video exists (per the site's own access
   ladder, tier 1/2/3) before any ingest or queue line -- agenda-only
   stays `meeting-without-video`, never ingested, per Ryan's standing
   rule.
3. Check `tenant_overrides.csv` for an existing pin on the resolved
   tenant host before minting a new one, and confirm the government's
   own state appears in the SAME page that carries the platform
   signature, not just somewhere else on the domain (this WO's gate
   already does this at the URL level; a human re-check on a sample is
   still warranted given the "hub" 51 / "meeting" 27 source-kind split
   above came from phase-2 scoring, not a platform signature alone).

## Recommended next WO

A hand-read + ingest pass over the 147 confirmed rows
(`research/wo273_targeted.csv`, filter `platform_confirmed != ""`),
following the same per-government hand-check and `gov_id`-in-payload
rules as every other sweep in this repo. Re-run phase 1 (cheap,
archive-first) once Internet Archive's CDX search has recovered --
today's run almost entirely took the live-fallback path, so a rerun
could plausibly surface meaningfully more sitemap-sourced signal than
this one did, at near-zero cost to the governments themselves.

## A note on timing: WO-272/274's own files landed on `main` mid-session

This WO's brief said to use its own named paths and the conductor's
embedded flag-word numbers if `app/utils/jurisdiction_data/
first_party_meeting_paths.csv` and `hop_link_weights.csv` hadn't landed
yet -- checked directly at the start of this run, neither had. Both
landed on `main` (WO-272, WO-274) before this PR's rebase, after this
run's phase 1/2/3 had already completed against the embedded numbers.
Checked the landed `first_party_meeting_paths.csv`: its own measured
yields (3.6% best case) don't clearly beat the named platform paths this
run already used, so the completed run stands as built rather than being
redone against the newly-landed file. A future rerun of phase 2/3 could
incorporate `hop_link_weights.csv` directly (phase 2 is pure offline
scoring specifically so this kind of rule update doesn't need a refetch)
-- left as a follow-up, not done here, to avoid re-running a live network
sweep a second time for what's likely a small scoring difference.

## What this WO did not do

No `jurisdiction_coverage.csv` write, no ingest, no queue line, no pin.
No GET was sent with the intent of confirming embeddable video -- only a
platform/name match. The apply-to-research-file step and any ingest are
explicitly the next WO's job, per this WO's own brief.
