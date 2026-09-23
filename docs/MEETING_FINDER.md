# Meeting Finder — design

**Status:** design agreed with Ryan on 2026-09-23 (WO-1023). WO-1024
(2026-09-23) built the core: `app/platforms/meeting_finder/` (`models.py`,
`pick.py`, `resolve.py`, `identity.py`, `verdict.py`, `runner.py`) and the
CLI, `scripts/meeting_finder.py`. WO-1025 (2026-09-23) added `fetch.py`,
the one fetch helper Start/Identify/Scan/Hop all use. WO-1027 (2026-09-23)
built **Identify** (`identify.py`), and WO-1029 (2026-09-23) built **Scan**
(`scan.py`, `scan_page()`) and **Hop** (`hop.py`, `rank_hops()`/
`is_document_hub()`/`calendar_entry_links()`) -- see this doc's Identify,
Scan and Hop sections below, now current. These are standalone modules,
**not yet wired into `runner.py`**: `resolve` is still the only entry
`runner.py` drives end to end, and `start`/`identify`/`list`/`scan` are
accepted by the CLI/`FinderInput` but return the outcome
`phase-not-built` until the wiring WO lands (including
`max_hops`/`max_forks`/`max_fetches` enforcement). See that package's own
module docstrings for the reasoning behind each piece; this section
records the interface details WO-1024/WO-1027 had to settle that this
design doc didn't spell out, and how Meeting Finder relates to
`app/platforms/passive_verify.py`, an existing module this design doc
missed on first pass.

**Identify's ranking implementation (WO-1027)**, on top of this doc's own
ranking table below:

- The link scan (rank 1-4 vendor/media/other-video-host links) always
  runs BEFORE `scripts/platform_fingerprints.fingerprint()`, and a
  platform the link scan already found is excluded from the fingerprint
  pass -- a link gives a real, specific account URL; a bare fingerprint
  hit on the same page is `url`-less and would otherwise win a rank tie
  by list order and silently downgrade `account_url` to the page's own
  base URL. See `identify.py`'s `_fingerprint_signals()`.
- Only `platform_signatures.csv`'s `first_party_path`-kind rows are
  trusted, never its `vendor_hostname` rows -- those are a plain "vendor
  domain anywhere in the page" text search with no corporate-host
  exclusion, and a real false positive surfaced building this WO: Lake
  Helen, FL's real Granicus "GovAccess" CMS footer credit ("Created By
  Granicus") contains the literal text "granicus.com" and fired the
  `granicus-vendor-host` signal as if it were a real tenant link. See
  `identify.py`'s `_FINGERPRINT_KIND_BY_SIGNAL_ID` comment.
- CivicLive on a city's OWN domain (not `*.hosted.civiclive.com`, which
  `detect_platform()` already recognizes by host) is NOT a
  `platform_signatures.csv` row -- per this WO's brief, that needs a
  real, measured signature first, not a guess. Measured live 2026-09-23
  against two real, independent first-party-domain tenants (Piedmont, CA
  and Williams, AZ -- byte-identical footer credit: `... Powered by
  <a href="https://www.civiclive.com" />CivicLive</a> ...`) and
  implemented as a narrow, sourced heuristic inside `identify.py`
  (`_civiclive_first_party_signal()`) rather than added to the CSV --
  two tenants and no negative sample is short of WO-267's own 10-per-
  platform measurement bar. A later WO should do the full measurement
  and move this into `platform_signatures.csv` properly.
- A **known false-positive risk, not yet fixed**: the rank-5 "YouTube
  meeting list" signal fires on any 2+ distinct YouTube video ids found
  on a page, with no check that they're actually meeting recordings --
  confirmed live on Piedmont, CA's own homepage, where 6 distinct
  promotional-video ids (parks/rec content, not council meetings)
  triggered it. Harmless today only because a real vendor link (rank 1)
  always outranks it when one exists; a page with ONLY a promotional
  video carousel and no vendor link would misreport a meeting list.
  Worth tightening in List/Scan (wave 2) with real per-item date/title
  context, the way `pick.py`'s own title filter already does for
  non-YouTube candidates.
- Identify never hands back `"youtube"` (or a YouTube channel) as
  `platform`/`account_url` -- even the rank-5 meeting-list case stays a
  `signals` entry plus `youtube_leads` URLs, for List to pick up on its
  own terms (e.g. via `app/platforms/youtube_channel.py`'s flat-channel-
  listing adapter). Confirmed live: no test or live-check input in this
  WO ever caused a real YouTube fetch -- every YouTube URL Identify
  reports came from parsing HTML already in hand.

## How Meeting Finder relates to `passive_verify.py`

`app/platforms/passive_verify.py` (WO-333, extended WO-355/933,
~2,850 lines) already does real, production-exercised work that
overlaps with several of this doc's phases. It was missed when this
design was written and corrected into the build mid-WO-1024
(2026-09-23). The division of labor, settled for wave 2 to build against:

| Capability | `passive_verify.py` has it | Meeting Finder (this design) |
|---|---|---|
| Walk a hub/listing URL to a real meeting | Yes -- `verify_hub()`, 11 registered listing walkers (granicus, champds, civicweb, legistar, escribe, civicclerk, civicplus, iqm2, townhallstreams, cablecast, invintus) + a generic listing-link scan + a first-party-agenda-page probe | List/Scan (wave 2) reuses this registry and scan directly, rather than rebuilding it |
| Fetch ladder (plain -> browser headers -> headless -> Wayback) | No -- one plain `aiohttp` GET (`_fetch()`), non-200 is a bare `fetch_failed` | WO-1025's `fetch.py` is the real ladder; wave 2 makes `passive_verify._fetch()` injectable so its walkers can use it instead of duplicating the ladder |
| Start (turn a domain into starting points; DNS gate) | No | wave 2, reusing stage 1's `wo282_recon.py` functions per this doc's Start section |
| Hop (ranked link-following, forks/budget) | A narrower one-hop "look deeper" search (`_deeper_hop_search()`), not the ranked signal table or `max_hops`/`max_forks`/`max_fetches` budget this doc's Hop section describes | wave 2 builds the real Hop, reusing `find_hop_links()`/the hop-weight tables already named in this doc |
| Account-unknown handling (`account-not-found`, guess-ladder) | No | Identify (wave 2) |
| The meeting-video gate | Yes -- `app/utils/video_hand_check.py`'s `assess_video_candidate()`/`classify_video_hand_check()`, plus the audio-only check (`_confirm_not_audio_only()`) | Resolve (WO-1024) reuses both directly rather than re-deriving them (see `resolve.py`'s own docstring) |
| YouTube guard | Yes -- `app/platforms/base.py`'s `youtube_resolve_guard()` (`passive_verify.py` aliases it `_youtube_resolve_guard`) | Resolve (WO-1024) uses the same guard via `resolve_via_platform(allow_youtube=False)` -- no second mechanism |
| Duration probe / tier-3 length preference | No -- confirmed by reading the whole file, no `queue_probe` import anywhere in it | Resolve (WO-1024) adds this: `app/platforms/queue_probe.py`'s `probe_queue_entry()` + `select_best_probe_result()` |
| Identity check (does the page agree with a believed government?) | No | `identity.py` (WO-1024) |
| A structured, resumable Verdict row | No -- `VerifyResult` is a return value, not a file | `verdict.py` (WO-1024) |

**One picking rule, used where each module needs it.** `pick.py` (moved
from `scripts/wo134_confirmed_hits_ingest.py` this WO, per the design's
"one picking rule" framing) filters candidates by date and title
cleanliness -- including, since 2026-09-23, a test/demo/"do not use"
title marker, a "minutes link" filter, and a governing-body preference
on a same-day tie (real examples: Fremont's Granicus demo tenant's "TEST
- CC - Livemeeting demo" rows, Marin County PrimeGov's "DO NOT USE -
Cathy Test Meeting", Tiburon's higher-volume "Heritage & Arts Only" view
outranking its own Town Council view by count alone -- see
`pick.py`'s own module docstring) -- *before* ever fetching a candidate.
`passive_verify.py`'s own walkers use a different rule (newest-first, no
pre-fetch title filter, judging each candidate only after resolving it
via the shared video gate). Resolve (WO-1024) applies `pick.py`'s rule
on top of whatever order a candidate list arrives in, regardless of
which lister produced it -- this is the "one rule" decision, not a third
implementation. `passive_verify.py`'s walkers keep their own ordering
for their existing callers; unifying the two is a real, open follow-up
for a later wave, not attempted here.

## Interface details WO-1024 settled

- **Identity derives "what the meeting itself says" the same way in pin
  and audit mode**: both switch off the specific tenant's own
  `tenant_overrides.csv` pin (`identity.tenant_pin_switched_off()`)
  before calling `resolve_government()`. The doc's own warning ("without
  switching the pin off, the resolver would just echo the pin back")
  applies to pin mode too, not only audit -- a host that already carries
  a whole-tenant pin would otherwise always "agree" with itself
  regardless of what the specific page actually said.
  **What actually distinguishes the two modes**, since the derivation is
  identical: not the mechanism, but what `gov_id` MEANS. In pin mode it's
  already the value in active use (an ingest would carry it forward
  regardless, per CLAUDE.md's "send the government's id in every ingest
  payload" rule) -- Identity here is a QA backstop. In audit mode it IS
  the thing under test (a `tenant_overrides.csv` pin being audited for
  correctness) -- a `disagrees`/`silent` verdict is the actual finding a
  human acts on. Meeting Finder itself never writes anything either way.
  **The switch-off mechanism itself (corrected 2026-09-23 after conductor
  review):** a single, permanent, idempotent wrapper installed on
  `resolver._override_rows_for_host` at import time, consulting a
  `contextvars.ContextVar` that holds the current set of switched-off
  hosts. An earlier version reassigned that attribute directly on each
  call's entry/exit, which corrupted state under `runner.py`'s own
  `--concurrency` flag (two overlapping calls could each restore the
  wrong prior state, per `identity.py`'s own docstring for the exact
  sequence). A `ContextVar` is task-local under asyncio, so two
  concurrent tasks switching off different hosts never see each other's
  switch-off -- proved by `tests/test_wo1024_meeting_finder_identity.py`'s
  `test_concurrent_switch_off_is_task_local`.
- **Resolve does not call `verify_hub()`** (a course correction during
  WO-1024's own build, see git history) -- Resolve's input is already a
  specific candidate URL, not a hub to walk; hub-walking stays List/
  Scan's job for wave 2. What Resolve reuses from `passive_verify.py` is
  the video gate, the audio-only check and the YouTube guard, not the
  walker.
- **`ResolveResult` (the public contract) never carries a raw
  `ResolvedMeeting`** -- `identity.check_identity()` needs the full
  object (raw jurisdiction text, tenant host, page hints), so
  `resolve.py` exposes a private `_resolve_candidates_with_meeting()`
  twin that `runner.py` calls instead of widening the small, typed
  public dataclass.
- **A live check found Whitehall, OH's CivicClerk tenant is no longer
  agenda-only** (CLAUDE.md's 2026-08-08 sample-sheet note) -- every real
  meeting from 2026-07-28 through 2026-09-22 now carries `hasMedia: true`
  via that tenant's own Events API, confirmed live 2026-09-23. Flagged in
  `BACKLOG.md` as a stale sample-sheet note to correct, not acted on
  further here.

## What it is and why

Meeting Finder takes a government and a domain (or any URL) and finds
one real meeting with video, or says plainly why it could not.

Today that job is spread across many tools: stage 1 of passive discovery
(`scripts/wo282_*`), the access ladder (`scripts/wo147_access_ladder_sweep.py`),
the hub walk (`resolve_seed()` in `scripts/wo134_confirmed_hits_ingest.py`
and its many per-sweep copies), alternate-domain retries
(`scripts/coverage_alternates.py`), and people reading pages by hand.
Each sweep picked a different mix. Meeting Finder is **one pipe** that
every government goes through, in the same order, with every failure
landing in a named place.

**Breadth, not depth.** rtr-discovery's walkers stay the depth tool: more
meetings from governments already in the Archive. Meeting Finder is for
governments that are not in the Archive yet. It borrows the walkers'
listing code where a walker exists.

## The phases

```
Start → Identify → List / Scan → Hop → Resolve → Verdict
```

| Phase | Job | Example |
|---|---|---|
| **Start** | Turn a domain into starting points | `pomonaca.gov` → the homepage, plus `live.pomonaca.gov` from a DNS guess |
| **Identify** | Say which platform a page is on, and which account | `live.pomonaca.gov` → Cablecast, account known |
| **List** | Turn a known account into candidate meetings, newest first | 20 Cablecast shows with dates and titles |
| **Scan** | Find media links and meeting-page links on a page | `/meetings/2026-09-08-council`, which embeds an `.mp4` |
| **Hop** | Pick the best next page to open | "Watch Meetings" → `cityx.granicus.com` |
| **Resolve** | Turn candidates into the first real meeting | the 2026-09-08 council meeting, 42 minutes, captions |
| **Verdict** | Write one read-only result row | tier 1, agrees with `us:place:0658072` |

List and Scan only gather candidates. Resolve is the one place adapters
run, so there is one picking rule. Verdict is the only phase that writes.

### Entry points

You can enter at the phase that matches what you already have.

| You have | Enter at | Example input |
|---|---|---|
| A domain | Start | `pomonaca.gov` |
| Any page URL | Identify | `www.ci.anytown.us/AgendaCenter` |
| A known account | List | `adamscounty.primegov.com`, platform `primegov` |
| One meeting URL | Resolve | `antiochca.portal.civicclerk.com/event/18/media` |

### Input rows

| Column | Required | Meaning |
|---|---|---|
| `url` | yes | A domain or any URL |
| `gov_id` | no | The government we believe this is |
| `platform_hint` | no | For custom domains where the platform is not obvious |
| `url_source` | no | `own-site`, `guessed` or `directory` |
| `mode` | no | `pin` (default) or `audit` |

### Pin mode and audit mode

A `gov_id` is sometimes wrong, so Verdict always checks it against what
the meeting itself says.

- **Pin mode:** the `gov_id` is sent through. Verdict compares it with the
  place the meeting names, and flags a disagreement.
- **Audit mode:** the `tenant_overrides.csv` pin for the account under test
  is switched off, and the resolver (`app/utils/gov_registry/resolver.py`)
  names the place from the page. Verdict reports **agrees**, **disagrees**
  (and what it points to) or **page says nothing**. Without switching the
  pin off, the resolver would just echo the pin back.

Identity carries over only along a path that started on the government's
own site. An account found by guessing is link-first and is checked in
audit mode (see rtr-business `research/LINK_FIRST_MATCHING.md`).

## Phase detail

### Start

- **DNS gate first.** If neither the domain nor `www.` resolves, stop with
  `dns-unresolvable`, then try the research row's alternate domains.
- **Homepage:** `https://domain/`, then `https://www.domain/`, then `http://`.
- **Cheap extra starting points,** reusing stage 1's functions in
  `scripts/wo282_recon.py` (`dns_lookup()`, the robots and sitemap
  readers, Wayback): guessed subdomains (`agenda.`, `meetings.`, `live.`,
  `video.`, `granicus.`, `legistar.`…) and meeting or vendor URLs found in
  sitemaps.
- Every starting point becomes its own fork.

### Identify

- `detect_platform()` (`app/platforms/base.py`) and `platform_for_host()` /
  `platform_for_path()` (`app/platforms/host_recognition.py`) on the URL.
- If still unknown, one fetch and `fingerprint()`
  (`scripts/platform_fingerprints.py`, reading `platform_signatures.csv`).
- Then every link on the page, **ranked** (Ryan, 2026-09-23):

| Rank | Signal |
|---|---|
| 1 | Meeting-platform vendor links (Granicus, Legistar, CivicClerk…) |
| 2 | Direct media files (`.mp4`, `.m3u8`) |
| 3 | Links to specific meeting pages on the government's own site |
| 4 | Other video hosts (Vimeo, BoxCast…) |
| 5 | YouTube, only as a meeting list where several meetings each have their own YouTube link |
| last | Any other YouTube link: saved as a drip lead, never the answer |

- A **web-host hint** (e.g. `granicusgovaccess.net`) says the website is
  hosted by a vendor. It is not a platform match.

**Platform known, account unknown.** Search this page and its hops for
that vendor's host and embedded players, weighting Hop toward that
vendor. If nothing is found, **do not guess slugs here**: the Verdict
says `account-not-found`, names the vendor and the evidence, and puts the
government on the guess-ladder queue (see Follow-ups).

### List

A known account becomes a list of candidate meetings. Try, in order:

| | Lister | Example |
|---|---|---|
| a | rtr-discovery's walker for the platform (`discovery/enumerators/*.py`, 14 platforms) | CivicClerk events API for `antiochca.portal.civicclerk.com` |
| b | `resolve_seed()`'s readers | `granicus_fetch_rss_candidates()` for `sandiego.granicus.com/ViewPublisher.php?view_id=3` |
| c | The adapter's own meeting list: some adapters answer a listing page with its meetings (`CalendarPageError`) | Legistar `boston.legistar.com/Calendar.aspx` |
| d | Generic: links on the page that `detect_platform()` puts on the same platform and that look like one meeting | a TelVue or Castus listing page |

If the platform has no adapter at all, the Verdict is
`unsupported-platform-no-adapter` and the platform is recorded per
rtr-business `research/UNSUPPORTED_PLATFORMS.md`.

### Scan

Built WO-1029: `app/platforms/meeting_finder/scan.py`'s
`scan_page(page, fetcher, *, max_meeting_pages=6) -> ScanResult`, where
`page` is a `fetch.py` `FetchResult` already in hand. Uses
`app/platforms/media_scan.py` for the direct-file scan, plus
`app/platforms/base.py`'s `detect_platform()` and
`app/platforms/direct_file.py`'s `is_direct_file_url()` for the anchor/
iframe-based Vimeo/Google Drive/CivicWeb cases those regexes miss.

- **Media links:** `.mp4`, `.m3u8`, Vimeo, Google Drive, CivicWeb.
  YouTube becomes a drip lead (`ScanResult.youtube_leads`), never a media
  candidate -- `youtube_ids.extract_video_id()`, pure regex, no network.
- **Meeting-page links:** dated agenda pages, `?EID=123`, `/event/123/`,
  `/meetings/2026-09-08-council`, a Municode-style `/page/town-council-
  meeting-278`. Detected by rtr-upcoming's `UPCOMING_AGENDAS_FIELD_
  GUIDE.md` three rules (link text, then table column header, then href
  shape), its minutes/subscribe/calendar guard (checked on link text, not
  href -- a real government page can serve both an agenda and its minutes
  from the same `/agendas-and-minutes/...`-shaped path, so an href-based
  guard would exclude both), and its ancestor date walk that skips a bare
  year heading. `ScanResult.meeting_page_links` lists every one found
  (newest first); `scan_page()` opens the newest `max_meeting_pages` of
  them through `fetcher` and scans each for media too -- one level only,
  since embedded video is often only visible one click down (confirmed on
  Municode's own "View Details" links and on a real CivicPlus tenant's
  Granicus player-page links alike). A link `scan_media_urls()`/
  `detect_platform()` already recognizes as direct media, or that
  `extract_video_id()` recognizes as YouTube, is never also offered as a
  page to open. A page fetched from Wayback (`FetchResult.links_only`)
  may still yield real meeting-page links, never media candidates.

### Hop

Built WO-1029: `app/platforms/meeting_finder/hop.py`'s
`rank_hops(page, *, prefer_vendor=None, school=False, french=False,
limit=8) -> List[HopLink]`, `is_document_hub(page) -> bool` and
`calendar_entry_links(page, limit=2) -> List[str]` -- thin wrappers
reusing `find_hop_links()`/`looks_like_document_hub()`/
`find_calendar_entry_links()` (`scripts/wo147_access_ladder_sweep.py`)
directly rather than moved into `app/` (see `hop.py`'s own module
docstring and `BACKLOG_DONE.md`'s WO-1029 entry for the reasoning --
`fetch.py`'s own precedent for reusing this same script's functions
directly).

- `find_hop_links()` with the measured
  `app/utils/jurisdiction_data/hop_link_weights.csv` (`school=True`/
  `french=True` select the school/French merges the same way
  `find_hop_links()`'s own `gov_id` parameter already does; `french=True`
  only takes effect when the page itself measures as French,
  `looks_french()`).
- **`prefer_vendor`** (new): once Identify already suspects a platform but
  not which account (the "platform known, account unknown" case above),
  a link `detect_platform()` resolves to that same platform gets an extra
  bonus on top of `find_hop_links()`'s own shared vendor-host bonus, so
  the known vendor's own host outranks a merely vendor-shaped link to
  some other platform.
- `looks_like_document_hub()` checks a landing page; on a plain events
  calendar, `find_calendar_entry_links()` opens its first dated entries.
- **Jev test (later):** score the same 180 real homepages the weights were
  measured on, and keep whichever finds the real hub more often.
- No `max_hops`/`max_forks`/`max_fetches` enforcement here -- the wiring
  WO applies these limits around `rank_hops()`'s own ranked output.

**Limits (settings):**

| Setting | Meaning | Default |
|---|---|---|
| `max_hops` | Depth of one path | 2 (one more from a homepage) |
| `max_forks` | Next-best links from the start page tried as new paths | 3 |
| `max_fetches` | Hard cap on page fetches per government | 12 |

Repeat Identify → List / Scan → Hop on each landing page within those limits.

### Resolve

- One picking rule (from `pick_calendar_candidates()`): a real date, a
  meeting-like title, newest first.
- Run the adapter on each candidate until one has a transcript, or a
  probed video of reasonable length (`queue_probe.probe_queue_entry()`).
- Tier-3 length rule: over 90 minutes, look for a shorter meeting from the
  same government first.
- Before calling a channel off-mission, look at 3 or more videos.

### Verdict

One row per input, written as it goes, so a rerun resumes. **Read-only:**
nothing is ingested or queued from here.

| Field | Example |
|---|---|
| Input, entry phase, path taken | `pomonaca.gov`, Start, homepage → "Watch" → `live.pomonaca.gov` |
| Result | meeting URL, platform, tier 1/2/3, length |
| Or a named outcome (§23 of rtr-business `ENUMERATION_METHODS.md`) | `meeting-without-video`, `unsupported-platform-no-adapter`, `off-mission`, `cloudflare-challenge-blocked`, `account-not-found` |
| Identity | agrees / disagrees (points to …) / page says nothing |
| Leads found on the way | YouTube channels, other governments' accounts |
| Budget used | hops, forks, fetches |

Ingesting, queuing tier 3 and writing the research row stay separate
steps, after the hand-read.

## How every page is fetched

Not a phase: one fetch helper used by Start, Identify, Scan and Hop.

| Rung | When |
|---|---|
| Plain request | Always first |
| Browser headers | Only after a 403 or a dropped connection |
| Headless browser | Only when a page loaded but shows no links |
| Wayback's latest copy | After a human-verification challenge. **For links only**, recorded with the snapshot date. Never the government's own media |

We never try to get past a site's challenge. Per-host politeness spacing
and robots.txt apply as in stage 1.

**YouTube:** Meeting Finder never fetches YouTube. It installs
`scripts/youtube_fetch_guard.py` first; YouTube finds become drip leads
in rtr-business `research/youtube_channel_leads.csv`.

## Follow-ups (slow queues, their own paced runs)

| Queue | Fed by | What it does |
|---|---|---|
| **Guess ladder** | `account-not-found` | Per vendor: learn the catch-all response once (status, size, body hash of a made-up slug); try slug shapes built from the government's name and state, ordered by how often each shape hit in past wildcard sweeps; every answering slug is a candidate, proven only by reading a meeting in audit mode. Two answering slugs are two candidates. |
| **Certificate log + Common Crawl** | Governments with nothing found | Today's stages 2 and 3 (rtr-business `dns_ctlog_sweep_2026-09-17/queue_pipeline.py`) |
| **YouTube drip** | YouTube leads | `scripts/youtube_drip.py` on the drip Mac |

Proven accounts and new starting points come back into Meeting Finder at
List or Identify.

## What it reuses and what it replaces

| Today | In Meeting Finder |
|---|---|
| Stage 1 recon (`wo282_recon.py`) | Start |
| Stage 1 classify and targeted fetch (`wo282_classify.py`, `wo282_targeted.py`) | Identify, and the walk itself |
| Access ladder (`run_access_ladder()`, `find_hop_links()`) | The fetch helper and Hop |
| Hub walk (`resolve_seed()` and its copies) | List (b) and Resolve's picking rule |
| Alternate-domain retries (`coverage_alternates.py`) | More starting points in Start |
| Stages 2 and 3 | A follow-up queue |

It calls, and does not copy: rtr-deeplink's adapters, resolver and
`host_recognition.py`; rtr-discovery's enumerators for listing.

## Suggested build order

Each step is useful on its own.

1. **Verdict row + Resolve.** Enter with meeting URLs; gives the shared
   output format and the identity check (pin and audit).
2. **List** with listers a–d. Enter with known accounts. First real use:
   the audit of the 696 `wildcard_http_sweep_2` pins.
3. **Identify**, including the ranked signals and web-host hints.
4. **Scan**, including meeting-page links.
5. **Hop**, with the settable limits.
6. **Start**, reusing stage 1's functions.
7. **Guess-ladder queue.**
8. **Jev test** against the hop weights.

## Open questions

- Whether rtr-discovery's enumerators need a small "list one tenant
  without the ledger" entry point, so Meeting Finder can call them for an
  account that is not in rtr-discovery's ledger.
