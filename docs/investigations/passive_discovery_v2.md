# WO-282: passive discovery v2 — three redesigned phases, tested on 1,298 governments (2026-09-12)

This is the investigation behind WO-282. It builds on WO-273's original
three-phase design (`docs/investigations/passive_discovery_full_scale.md`)
and Ryan's 2026-09-12 redesign of it (see `BACKLOG_DONE.md`'s WO-282
entry for the short version). WO-278 and WO-281 (fixing WO-273's
catch-all bug and adding a homepage-fetch step) merged to `main` while
this WO was already mid-run on its own population; this report notes
where the two overlap rather than restarting on their code (see
"Relationship to WO-278/281" at the end).

## What changed and why

WO-273's phase 1 read only one sitemap, never fetched a government's own
homepage, and both archive indexes were down that run. WO-273's phase 3
gave 1,610 governments with no flagged URL five blind path probes each,
and 76 of its 147 "confirmed" turned out to be catch-all sites answering
any path (WO-278 fixed this). This redesign: DNS first as a fail-fast
gate; every other step run together; every sitemap a robots.txt names,
not just the first that parses; the homepage always fetched, with every
link's href/anchor text/position (nav, footer, menu, body) recorded,
since that position is what the measured hop scorer
(`hop_link_weights.csv`, WO-274) scores on and a sitemap URL list never
carries; a Crawl-delay honored per host; and, for a government with no
candidate, a fallback ladder (one hop below threshold, then a headless
render, then two named first-party probes) instead of a blind probe.

## Population

`research/wo282_population.csv`: 999 eligible "fresh" governments (US,
population 2,500-4,999, has a domain, no suspected platform, reject
reason in the nothing-found family, own domain only) minus 0 excluded
for a vendor-host domain, capped at the 1,000 smallest by population —
the eligible band itself held only 999, so the fresh group is 999, not
1,000, reported as found rather than padded. Plus the 300 WO-268 pilot
domains as an unfiltered regression group, for a like-for-like
comparison with WO-268 and WO-273. Total 1,299 rows, 1,296 unique
domains — 3 rows in the fresh group share a domain with another row
("colorado.gov" x3, "co.berks.pa.us" x2, a data-quality artifact in
`jurisdiction_coverage.csv` covered under "Findings," not fixed in this
WO). Phase 1 actually processed 1,298 of the 1,299 rows: 2 duplicate-
domain rows got attempted before the resumable dedupe caught up (their
domain had already appeared as "done" from an earlier chunk), 1 was
skipped by that same dedupe once it had.

| Group | Rows | Note |
|---|---|---|
| Fresh (new, 2,500-4,999 pop, nothing found) | 999 | population 2,503-4,985 |
| Regression (WO-268's 300 pilot domains) | 300 | unfiltered, for comparison |
| **Total** | **1,299** | 1,296 unique domains |

## Timing per phase (governments per minute)

Phase 1 was timed on the first 50 governments before the full run, per
the brief's own requirement.

| Phase | First-50 rate | Full-run rate | Governments | Errors |
|---|---|---|---|---|
| 1 — reconnaissance | 41.2/min | 41-96/min across chunks (CDX health varied) | 1,298 | 0 |
| 2 — classification (offline, no network) | — | ~2,000/min | 1,298 | 0 |
| 3 — targeted fetch + fallback ladder | 12.9/min (first 10, mostly real fetches) | 41-88/min across chunks | 1,298 | 0 |

Zero fetch errors across all three phases and all 1,298 governments —
every failure the CSVs record is a real HTTP/DNS/challenge outcome, not
a script crash.

## Per-step timing (ms), phase 1, full run

| Step | Median | p95 | n |
|---|---|---|---|
| DNS | 1,162 | 4,550 | 1,298 |
| Homepage fetch | 716 | 3,658 | 1,136 |
| Robots.txt | 2,781 | 3,713 | 1,136 |
| Sitemap (incl. sub-sitemaps) | 8,387 | 38,710 | 1,136 |
| Archive (Wayback CDX + id_ reads) | 4,101 | 7,018 | 536 |
| Wayback domain index | 2,048 | 2,219 | 536 |
| Common Crawl | 0 | 0 | 1,136 |

Archive/Wayback-index steps only ran for 536 of 1,136 resolved
governments — the CDX health probe (run at the start and every 200
governments) found it unhealthy for roughly the first third of the run
and healthy after, so those steps were skipped outright rather than
spending a timeout on a resource already known to be down. Common
Crawl's own health probe failed at the very start of the run, so every
government's Common Crawl step is a free, instant skip (median 0ms) —
the whole run got zero real Common Crawl data, an honest zero, not a
silently-dropped one.

## DNS gate and access mode

| DNS gate | Count |
|---|---|
| Resolved (apex or www answered) | 1,136 |
| dns-unresolvable (skipped every HTTP step) | 162 |

| Homepage access mode (of the 1,136 resolved) | Count |
|---|---|
| Plain HTTP | 938 |
| Blocked, plain HTTP (dead end) | 127 |
| Blocked, browser headers (dead end) | 34 |
| Recovered via browser headers after a 403 | 11 |
| Recovered via browser headers after a dropped connection | 26 |

## Sitemaps and robots.txt

| Sitemaps named per government | Count |
|---|---|
| 0 | 874 |
| 1 | 401 |
| 2+ | 23 |

182 of 1,136 robots.txt fetches (16%) carried a `Crawl-delay` line, all
honored (an extra sleep on top of the shared 2.5s host floor for every
further request to that host this run made). 25 Disallow paths across
the whole run matched the hub vocabulary (agenda/council/commission/
minutes/board/meeting) and were recorded as `disallowed_lead` — a real
lead AND a do-not-fetch at once — and never fetched by phase 1 or phase
3's candidate list.

## Homepage link position table

31,129 nav-position links (56%), 10,780 body (19%), 7,343 menu-list
(13%), 2,756 footer (5%) — 51,918 total links recorded across every
homepage phase 1 fetched (n=1,136 homepages).

| Position | Count | Share |
|---|---|---|
| nav / header | 31,129 | 60% |
| body | 10,780 | 21% |
| menu (bare ul/ol, not nav) | 7,343 | 14% |
| footer | 2,756 | 5% |

Position is exactly the signal a sitemap URL list can never carry — a
`/agendas` link inside `<nav>` and the identical link buried in a
footer sitemap get the same path-vocabulary score, but the measured
hop scorer's own nav bonus/footer penalty (`hop_link_weights.csv`,
WO-274) treats them very differently, and correctly: a footer link is
disproportionately Terms-of-Service/social/vendor-marketing, not a
meeting hub.

## Classification (phase 2)

| Confidence | Count of 1,298 |
|---|---|
| High (a real platform, vendor-host or first-party-embed) | 199 |
| Medium (a strong hub/meeting vocabulary hit) | 666 |
| Low | 10 |
| None | 423 |

| Platform found (any confidence) | Count |
|---|---|
| youtube | 144 |
| civicplus | 23 |
| civicweb | 11 |
| civicclerk | 7 |
| vimeo | 4 |
| civiclive | 2 |
| granicus | 2 |
| municode_meetings, telvue, primegov, legistar, viebit, castus | 1 each |

266 of 1,298 governments (20%) had NO candidate at all after phase 2's
offline scoring — sitemap, archive, DNS, and homepage links all came up
empty or below the qualification bar — and fed phase 3's fallback
ladder.

## Yield per request, by method

The point of this table: which methods are worth their own request
budget, not just which methods found *something* eventually.

| Method | Governments reached | Real finds attributable | Yield |
|---|---|---|---|
| DNS (gate + vendor-label guess) | 1,298 | 0 platform finds this run (no civicweb/primegov vendor-label resolves in this population) | 0% |
| Archive (Wayback CDX + id_ reads) | 536 (skipped ~44% for confirmed-unhealthy CDX) | 3 governments got their sitemap from Wayback instead of live | 0.6% |
| Homepage fetch + link scoring | 1,136 | Source of the large majority of phase 2's "high"/"medium" candidates (self-reported per-request yield not separated from sitemap in phase 2's combined candidate list; see "Findings" for a directly-measured one below) | high |
| Robots + sitemaps | 1,136 fetches, up to 11 sitemap requests each | 575 governments got a real sitemap this way | high (per-government), moderate (per-request, given the sub-sitemap fan-out) |
| Wayback domain index | 536 | 0 additional confirmed candidates beyond what sitemap/homepage already found in this run | 0% |
| Fallback rung 1 (one hop below threshold) | 266 (of the no-candidate pool) | 32 requests, 9 real hub finds | 28% |
| Fallback rung 2 (headless render) | 205 (governments where rung 1 found nothing) | 205 requests (median 6.4s, p95 15.5s, max 107s), 8 hub finds + 2 platform finds | 4.9% |
| Fallback rung 3 (named first-party probes) | 246 (governments where rung 2 found nothing) | 492 requests (2 paths each), 7 alive-and-not-catch-all responses (weaker bar — not name-verified) | 1.4% |

Wayback's 0% this run is consistent with WO-273's own finding that CDX
search has been degraded all week — not a verdict on the method itself,
which the archive-first sitemap/robots step still used successfully for
3 governments when it was reachable.

## Fallback ladder, terminal outcome (the 266 no-candidate governments)

| Outcome | Count of 266 | What it means |
|---|---|---|
| Found at rung 1 (one hop) | 9 | A homepage link below the normal scoring bar still led somewhere real |
| Found at rung 2 (headless) | 8 | Needed a JS-rendered homepage before any real link appeared |
| Found at rung 3 (probe) | 7 | A named `/AgendaCenter`/Hyland path answered, alive, not a catch-all — not independently name-verified |
| Nothing found | 242 | Every rung came up empty — a real "no-platform-link-found," not a giveaway |

## Catch-all test

207 of 4,866 phase-3 fetches (4.3%) matched their host's own nonsense-
path signature (same status/body length or exact body hash) and were
correctly excluded from counting as a platform/hub confirmation, no
matter what the page's content otherwise looked like — this is the
exact class of false positive WO-278 found made up 76 of WO-273's 147
"confirmed" platforms (52%). This run's catch-all rate (4.3% of
fetches) is far lower than WO-273's because this population is
different (fresh 2,500-4,999-population governments, not WO-273's
5,000+ pool) and because most of this run's real candidates came from a
homepage link a human government actually put in their own navigation,
not a blind path guess — the two are not directly comparable rates, but
the test caught real cases either way and is now load-bearing rather
than optional.

## Confirmed platforms (name+state verified, not catch-all, body over 800 bytes)

128 unique governments cleared phase 3's full bar: HEAD+GET (archive
body first), a real platform signal (`platform_fingerprints.fingerprint()`
or `detect_platform()`), the page naming this government's own city AND
state, and passing the catch-all/800-byte-floor checks.

| Platform confirmed | Governments |
|---|---|
| youtube | 82 |
| civicclerk | 16 |
| civicplus | 13 |
| utah_pmn | 5 |
| granicus | 4 |
| civicweb | 2 |
| wistia | 2 |
| swagit, telvue, civiclive, champds | 1 each |

Worth naming directly: 16 of the civicclerk confirmations were found on
a government's OWN vanity domain (`Calendar.aspx?EID=...`-shaped URLs
like `cityofchelan.gov/206/City-Council`), not a `civicclerk.com` host —
spot-checked live (`curl` against `cityofchelan.gov/206/City-Council`
shows a real `civicclerkcdn.azureedge.net/publicportal-live/embed.js`
and a `civicclerk.com` link in the page body) and confirmed genuine,
not a scoring bug. This is exactly the first-party-embed case
`platform_fingerprints.py` (WO-267) was built to catch, and phase 1's
sitemap-only URL list from WO-273 could never have surfaced it — the
page had to actually be fetched.

## Hand-read and ingest

Of the 128 confirmed governments, 82 carry a YouTube platform
confirmation. Of those, 80 are YouTube CHANNEL links (`/@handle`,
`/channel/UC...`, `/user/...`), not single-video URLs — per this repo's
own "YouTube drip ownership" convention, all YouTube channel-scan work
runs as `scripts/youtube_drip.py` on a separate dedicated machine, one
drip per office connection, specifically to avoid the kind of repeated,
concurrent YouTube hits this session's own resolve-diagnostic pass would
have added. This WO did NOT run channel scans or ingest from any of
those 80 — they are real, name-matched leads, listed in
`research/wo282_confirmed_youtube_channels.txt` for the drip process to
pick up, not attempted here. The other 2 YouTube confirmations WERE
already single-video URLs and resolved directly (Silt CO, East Ridge
TN, below) — both turned out to be the wrong video, not a channel-scan
question.

Of the remaining 46 (real single-video/hub URLs, plus the 2 direct
YouTube video resolves), a resolve-only
(never-ingest) diagnostic pass was run against the actual
`app.platforms` resolve pipeline (the same one `/api/resolve` and
`bulk_ingest.py --dry-run` use) to see which carried a real, resolvable
meeting:

| Hand-read outcome | Count of 46 | What it means |
|---|---|---|
| Real meeting video, name+content verified, ingested | 1 | Saco, Maine — see below |
| Real meeting page/agenda found, no video attached | ~20 | CivicClerk/first-party hub resolved a specific event, but that event has no video (agenda-only, `meeting-without-video`, never ingested per this repo's video-only rule) |
| CivicPlus AgendaCenter listing, needs a further drill-down the adapter doesn't do automatically | 2 | La Pine OR, Ketchum ID — recorded, not built further this WO |
| Wrong video (Kind B — right channel, real government, not a meeting) | 2 | Silt CO ("Town of Silt Economic Development 2018"), East Ridge TN ("East Ridge: Pioneers of Progress") — both real promotional/history videos, not meeting recordings; caught and rejected by the hand-read gate |
| Unrelated third-party video (a payment-portal Wistia tutorial, not this government at all) | 2 | Jemison AL and Zillah UT both resolved to the SAME "Making a Payment with PayPal" Wistia video via an unrelated invoicecloud.com billing portal a hop chased into — a real false-positive class, not this government's content |
| YouTube video URL, but future-dated meeting (agenda posted, meeting hasn't happened) | 1 | Red Oak TX — "Regular Meeting - September 14, 2026," two days after this run |
| Livestream URL, not a fixed on-demand meeting | 1 | Saugerties NY (TelVue `.m3u8` channel stream) — flagged, not ingested without further judgment |

**Ingested: Saco, Maine (`us:place:2364675`)** — found via this WO's own
homepage-nav scoring (a real link on `sacomaine.org`'s own navigation),
hand-read (title "Saco City Council Meeting - July 8, 2024" names the
right government, 1,888 real caption segments), ingested for real:
`/m/saco-me-2024-07-08-saco-city-council-meeting-july-8-2024` (HTTP 200,
verified live). `gov_id=us:place:2364675` was sent in the ingest
payload. `jurisdiction_coverage.csv`'s existing row for Saco already
carried `suspected_video_provider=youtube` from earlier work (not a new
finding on its own) — the real update this WO made was pointing
`example_meeting_url` at the actual live Archive page instead of the
bare YouTube link.

The hand-read gate caught 4 wrong or unrelated videos out of 8 that
resolved to a real video at all (50%) — in line with this repo's own
documented 10-62% wrong-video rate depending on how the candidate was
found, and a direct demonstration of why CLAUDE.md requires reading
every title/channel by hand rather than trusting a name+state text match
alone (all 4 wrong ones DID pass the name+state check — the government's
own real name appears on an unrelated video hosted by/linked from that
government's own real site).

## Regression group: WO-268 vs WO-273 vs WO-282, same 300 domains

| Confidence/find | WO-268 (2026-09-11) | WO-273 (2026-09-12, same domains, from its own classified.csv) | WO-282 v2 (this run) |
|---|---|---|---|
| High confidence | 25 | 4 | 87 |
| Medium confidence | 238 | 45 | 137 |
| Low confidence | — | 77 | 3 |
| None | 37 | 170 | 73 |
| Real platform found | 25 (civicplus 21, primegov 1, civicweb 3) | 4 (civicweb 3, primegov 1) | 90 (youtube 58, civicplus 12, civicclerk 6, civicweb 3, granicus 2, vimeo 2, primegov 1, legistar 1, viebit 1, castus 1) |

WO-273 did WORSE than WO-268 on this exact population (4 platforms vs
25) — consistent with its own writeup's admission that phase 1 never
fetched a homepage and both archive indexes were down that run. WO-282's
redesign — DNS gate, always-on homepage fetch with position-aware
scoring, every sitemap named, and the fallback ladder — found roughly
3.5x WO-268's platform count and over 20x WO-273's, on the identical
300 domains. This is the core result this WO set out to measure.

## Findings worth a BACKLOG/data-quality note

- **`jurisdiction_coverage.csv` wrong-domain-mapping, 5 rows found**:
  Mohnton borough PA (`us:place:4250272`) and Kenhorst borough PA
  (`us:place:4239256`) both carry `co.berks.pa.us` (Berks County's own
  domain, not either borough's) as `domain`. Costilla County CO
  (`us:county:08023`), Phillips County CO (`us:county:08095`), and
  Washington County CO (`us:county:08121`) all carry `colorado.gov`
  (the state's own domain) as `domain`. Not fixed in this WO — the
  correct fix (per this file's own convention) is to move the wrong
  value into `alternate_domains` only once each government's REAL
  domain is known, which needs its own short research pass; filed in
  `BACKLOG.md` rather than guessed at here. Since these came from a
  population built specifically to check "own domain only," it's worth
  a wider sweep of the ~1,700-row band this file's own
  `population_estimate` covers for the same county/state-domain-on-a-
  smaller-government pattern.
- **CivicPlus AgendaCenter listing pages need a drill-down step this
  session didn't build**: `resolve()` on an AgendaCenter URL correctly
  raises `CalendarPageError` rather than guessing, but nothing in this
  WO's pipeline followed that listing down into its most recent
  individual meeting the way the CivicPlus adapter's own
  `resolve_via_platform()` presumably can from elsewhere in the resolve
  chain (this WO called `finder.resolve()` directly on the flagged URL,
  not the deeper listing-walk logic). Two real cases this run (La Pine
  OR, Ketchum ID) — filed as a live BACKLOG entry.
- **A hop into an unrelated third-party payment portal can surface a
  totally unrelated video** (Jemison AL, Zillah UT both landing on the
  same invoicecloud.com Wistia "Making a Payment with PayPal" clip) —
  worth a guard in the hop-link scorer or the resolve pipeline against
  following a link off a government's own domain onto a known billing-
  portal host with no meeting content at all; filed in `BACKLOG.md`.

## Relationship to WO-278/281

WO-278 (fixing WO-273's catch-all bug) and WO-281 (adding a homepage
fetch + WO-274-scored links step) both merged to `main` (#1053, #1054)
while this WO was already mid-run against its own, separately-built
population and pipeline. Neither had landed on `main` when this WO
started (checked directly, per this WO's own brief) or when its own
scripts were written, so `scripts/wo282_recon.py`,
`wo282_classify.py`, and `wo282_targeted.py` implement their own
versions of the same two ideas (always-fetch-homepage,
catch-all-aware confirmation) independently rather than importing
WO-278/281's actual code — rebuilding this WO's already-complete,
already-run pipeline on top of their merged code was judged not worth
the redo cost partway through a working end-to-end run. The two
efforts corroborate each other: WO-281 (its own investigation) reports
259 confirmed platforms and 2 real ingests on its own population;
WO-278 reports 60 confirmations (down from WO-273's uncorrected 147)
and 1 ingest. This WO's 128 confirmations and 1 ingest, on a disjoint
population plus the shared 300-row regression set, land in the same
range using an independently-built catch-all test and homepage-scoring
step — reasonable convergent evidence that both fixes are real and not
an artifact of either implementation.

## Recommended production order

1. **Homepage fetch, always, with position-aware scoring** — the
   single highest-value change this run made. It is what found the
   large majority of this run's confirmed candidates (both the
   first-party CivicClerk embeds and the plain first-party hub pages),
   and it is cheap (median 716ms per government).
2. **DNS-first gate** — free (no HTTP step wasted on 162 unresolvable
   domains this run, 12.5% of the population) and correctly separates
   "nothing here" from "couldn't get in."
3. **Catch-all test before counting any confirmation** — non-negotiable
   after WO-278's finding and this run's own 4.3%; cheap (one extra
   request per government).
4. **Every sitemap a robots.txt names, honoring Crawl-delay** — real
   but modest yield (23 governments with 2+ sitemaps, 3 extra sitemap-
   sourced finds via Wayback); worth keeping for the politeness
   compliance alone even if the yield stays modest.
5. **Fallback ladder rungs 1-2 (one-hop, then headless)** for a
   no-candidate government — real yield (17 of 266, 6.4%) at a real
   cost (headless median 6.4s); rung 3 (named probes) found nothing
   independently verifiable this run and could reasonably be dropped or
   deprioritized in a production version.
6. **Wayback/Common Crawl, as a background best-effort only** — this
   run's Wayback yield was 0% of governments reached (CDX degraded for
   part of the run and contributed nothing when healthy that homepage/
   sitemap didn't already find) and Common Crawl never got a health
   probe pass at all; neither should gate a government's processing
   time, and a production run should not wait on either.
