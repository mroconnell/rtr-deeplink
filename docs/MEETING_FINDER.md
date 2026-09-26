# Meeting Finder — design

**Status:** design agreed with Ryan on 2026-09-23 (WO-1023). WO-1024
(2026-09-23) built the core: `app/platforms/meeting_finder/` (`models.py`,
`pick.py`, `resolve.py`, `identity.py`, `verdict.py`, `runner.py`) and the
CLI, `scripts/meeting_finder.py`. WO-1025 (2026-09-23) added `fetch.py`,
the one fetch helper Start/Identify/Scan/Hop all use. WO-1027 (2026-09-23)
built **Identify** (`identify.py`); WO-1028 (2026-09-23) built **List**
(`listing.py`'s `list_account()` -- see this doc's List section below for
the five listers and the order they're tried in); WO-1029 (2026-09-23)
built **Scan** (`scan.py`, `scan_page()`) and **Hop** (`hop.py`,
`rank_hops()`/`is_document_hub()`/`calendar_entry_links()`); and WO-1030
(2026-09-23) **wired every phase together** in `runner.py` and built
**Start** (`start.py`) -- see this doc's Identify, List, Scan, Hop and
Start sections below, now current, and the "The phase loop (WO-1030)"
section further down for how the wiring itself works.
**Every entry point (`start`/`identify`/`list`/`scan`/`resolve`) is now
live end to end**, with `max_hops`/`max_forks`/`max_fetches` enforced --
`phase-not-built` no longer applies to any entry. WO-1033 (2026-09-23)
then fixed five real link-quality bugs in **Hop** and **Scan**, found by
Ryan hand-checking Dublin, CA and Emporia, KS: a word-less nav link
scoring nothing, calendar events crowding out hub links, a new
`prefer_video` ranking boost, a same-site social redirect (`/youtube`)
never treated as a hop or a meeting page, and a `canonical_page_key()`
helper for `runner.py`'s own de-duplication -- see this doc's Hop/Scan
sections below and `BACKLOG_DONE.md`'s WO-1033 entry for the full
write-up. See that package's own module docstrings for the reasoning
behind each piece; this section records the interface details WO-1024/
WO-1027/WO-1028/WO-1030/WO-1033 had to settle that this design doc didn't
spell out, and how Meeting Finder relates to
`app/platforms/passive_verify.py`, an existing module this design doc
missed on first pass.

**The first WO-1030 smoke test missed every one of 4 real, known-video
governments it was tried against** (conductor review, 2026-09-23) --
`cityoftacoma.granicus.com`, `pomonaca.gov`, `boston.gov` and
`piedmont.ca.gov` all came back with nothing found, despite each having
a real, confirmed video the design should have reached. A second pass
(WO-1030 follow-up, same day) traced each one against the real page and
found five separate real bugs, all fixed and reverified live -- see "The
phase loop" section below for the fixes themselves:

1. A vendor account URL entered at `start` (Tacoma: `cityoftacoma.
   granicus.com` is already a Granicus tenant host) was treated as a
   government domain to DNS-guess homepages around, instead of going
   straight to Identify -> List.
2. Granicus's own `list_recent_video_meetings()` needs a URL that already
   carries a `view_id` -- nothing discovered one for a bare Granicus hub
   root, so List always came back empty for exactly this shape.
3. One fork (Start's own first starting point) could spend the ENTIRE
   government fetch budget on its own Scan/Hop chain before any other
   starting point Start found -- including a real, one-fetch-away answer
   -- ever got tried (Pomona: `live.pomonaca.gov`, a real Cablecast
   account, never reached).
4. `rank_hops()` (a generic link scorer) ranked a homepage's own YouTube
   channel/video links, and a known platform's OWN further navigation
   pages, above the real next hop -- both fixed at the wiring layer
   (Boston, Piedmont).
5. `_civicplus_walker()` (List's lister a) could spend most of a
   government's fetch budget confirming a real agenda-only CivicPlus
   tenant has no video, starving the agenda-only fallback that exists
   specifically to report that case correctly (Cass County, MN).

All four governments, plus Whitehall, OH (re-run against its real
CivicClerk tenant domain instead of a guessed one) and Cass County, MN,
now resolve correctly -- see the WO-1030 follow-up PR's own smoke-test
table for the full per-government numbers.

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

## Back-pressure and "try next" (WO-1031, 2026-09-23)

- `--concurrency N` is the **intake**: governments in the cheap phases at once. Resolve takes a slot from a small pool (`--resolve-slots`, default N // 4). While more than `--max-waiting` (default 2 x slots) governments wait for Resolve, no new government is admitted; intake reopens as they convert. `--lanes-log FILE` records the counts over time.
- Every failure's Verdict row has a `try_next` label (e.g. "blocked: try another network, or Wayback by hand", "YouTube only: send to the drip", "budget ran out: hand-check the site nav (Meetings / Agendas & Minutes)").
- `youtube-lead-only` ranks above access blocks and below meeting-without-video.

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

**Built, WO-1030.** `app/platforms/meeting_finder/start.py`'s
`start(domain_or_url, fetcher, *, alternates=None, guess_subdomains=True)
-> StartResult(starting_points, outcome, note)`.

- **DNS gate first.** If neither the domain nor `www.` resolves, stop with
  `dns-unresolvable`, then try the research row's alternate domains
  (passed in via `alternates` -- Start itself never reads rtr-business).
- **Homepage:** `https://domain/`, then `https://www.domain/`, then `http://`.
- **Cheap extra starting points,** reusing stage 1's functions in
  `scripts/wo282_recon.py` (`dns_lookup()`, the robots and sitemap
  readers): guessed subdomains that actually resolved (`agenda.`,
  `meetings.`, `live.`, `video.`, `granicus.`, `legistar.`…, minus any
  that's really just the apex domain's own DNS wildcard), a guessed
  CivicWeb/PrimeGov tenant-label host that resolved, and sitemap URLs
  that `detect_platform()`/`host_recognition` recognizes as a known
  platform or that look like one specific meeting page (Identify's own
  rank-3 shape, reused verbatim). The DNS/robots/sitemap reads are their
  own small budget -- like `fetch.py`'s Wayback lookup, they never spend
  any of `Fetcher.max_fetches`. A robots.txt `Crawl-delay` found here is
  handed to `fetcher.note_crawl_delay()` before the phase loop's own
  Identify/Scan/Hop calls start spending that budget.
- Every starting point becomes its own fork (see "The phase loop"
  below for how forks/hops are budgeted).

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

**Built, WO-1028.** `app/platforms/meeting_finder/listing.py`'s
`list_account(platform, account_url, fetcher, *, limit=15,
platform_params=None) -> ListResult` turns a known account into a list of
candidate meetings, newest-first. It only lists -- Resolve is still the
only place an adapter's `resolve()` runs to pick and confirm one. Seven
listers, tried in order, stopping at the first that returns candidates:

| | Lister | Example |
|---|---|---|
| a | `app/platforms/passive_verify.py`'s registered listing walkers (granicus, champds, civicweb, legistar, escribe, civicclerk, civicplus, iqm2, townhallstreams, cablecast, invintus) | CivicClerk events API for `antiochca.portal.civicclerk.com` |
| b | rtr-discovery's `list_tenant()` (`discovery/list_one.py`, WO-1026), for a platform passive_verify has no walker for -- primegov, swagit, municode_meetings, proudcity, hyland | `lacity.primegov.com`'s PrimeGov enumerator |
| c | The adapter's own meeting list: some adapters answer a listing page with its meetings (`CalendarPageError`) | Legistar `boston.legistar.com/Calendar.aspx` |
| d | Adapters that walk a hub themselves and resolve straight to ONE meeting | Castus's own `_pick_newest`, a Cablecast gallery, a townhallstreams town page |
| e | Generic: `passive_verify._generic_link_scan_walker()` on links that look like one meeting | a TelVue listing page with no bespoke walker |
| f | "Cablecast Connect" (WO-1054): a WordPress plugin whose page IS already a real listing -- reads its own `.gc-cc-card` markup, topped up via its `wp-json/cablecast/v1/recent-shows` REST route, then unwraps each show page's own `watch-vod-embed` iframe into a real, resolvable Cablecast candidate | `townsquare.tv/programs/site/mendota-heights-8/` (Mendota Heights, MN) |
| g | A plain WordPress site (WO-1054): searches `wp-json/wp/v2/posts?search=meeting`/`?search=video` for a post that embeds a real video | tried on Wilder, KY per Ryan's own brief -- came back empty there (its real video is found a different way, a direct homepage link) |

If the platform has no adapter at all (no passive_verify walker, no
rtr-discovery enumerator, no registered `AssetFinder`), the outcome is
`unsupported-platform-no-adapter` and the platform is recorded per
rtr-business `research/UNSUPPORTED_PLATFORMS.md`. Otherwise, nothing
found is `no-meeting-nor-video`.

**Shared-hub government filter (WO-1054, Ryan's rule 2026-09-24).** One
TelVue org token or Cablecast tenant root routinely serves several nearby
governments off the same account. `pick.filter_candidates_to_government()`
drops a candidate whose title clearly names a DIFFERENT government's own
place name (compared as a whole phrase, not a shared word -- confirmed
live College Township, PA and the Borough of State College, PA both
contain the bare word "college" but are different places), applied to
every lister's own output in `list_account()` whenever a caller passes
`gov_name` (`runner.py` looks this up once per government from the
`gov_id` registry). A title with no governing-body word, or no
recognizable place name, is left alone -- ambiguous, never treated as
evidence of another government. When EVERY candidate names a different
government, the outcome is `models.OUTCOME_HUB_OTHER_GOVERNMENT` ("hub
carries other governments, not this one") rather than a bare "nothing
found".

**Fetch injection (WO-1028).** Listers (a) and (e) call straight into
`passive_verify.py`'s own walker functions, which fetch pages through
that module's private `_fetch()`. So those walkers use Meeting Finder's
own `Fetcher` (the ladder + `max_fetches` budget from `fetch.py`) instead
of a bare `aiohttp` GET, `passive_verify.py` gained `fetch_override()`:
a task-local (`contextvars`) override of `_fetch()`, the same mechanism
`identity.py`'s `tenant_pin_switched_off()` already uses for an identical
reason. Set only for the duration of `listing.list_account()`'s own
walker call; every other existing caller of `_fetch()` (`verify_hub()`,
every `wo3xx_resolve_diagnostic.py` sweep script) never sets it and sees
identical behavior to before this WO -- confirmed by the full, unmodified
`tests/test_passive_verify*.py` suite still passing.

**Agenda-only fallback (found live-testing, fixed for List in the same
WO after conductor review).** `_civicplus_walker()`'s step 1 only adds a
candidate when a listing row's own parsed `url` field is set -- an
AgendaCenter tenant that is genuinely agenda-only (posts agendas/minutes
but no video link on the row itself, e.g. Cass County, MN,
`mn-casscounty.civicplus.com/AgendaCenter`, confirmed live 2026-09-23:
37 real rows, every one missing a video `url`) came back with zero
candidates from List, the same as a tenant with no meetings at all.
`listing._civicplus_agenda_only_fallback()` closes this for List:
tried after every other lister comes back empty for a `civicplus`
account, it re-parses the page with `CivicPlusAssetFinder()._find_
candidate_rows()` directly (not `_civicplus_walker()`, which stays
exactly as it is for `verify_hub()` and every other existing caller) and
returns the video-less rows as `Candidate`s (`lister=
"civicplus_agenda_only"`, `has_video_hint=False`), so Verdict has real
rows to read as `meeting-without-video` instead of `no-meeting-nor-
video`. Every other registered listing walker was checked for the same
video-only filtering and found NOT to have it (CivicWeb/Legistar/
eScribe/IQM2 never filtered on video; CivicClerk's walker only sorts
`hasMedia`-true first, never drops the rest; Townhallstreams/Cablecast/
Invintus list links that are inherently video). `municode_meetings.py`
has the identical shape CivicPlus had before its own 2026-09-07 fix (its
`resolve()` still calls the never-renamed `_find_video_rows()`) -- not
given a fallback here (a different adapter file, and rtr-discovery's own
enumerator already answers most real Municode Meetings accounts before
that path is reached); see `BACKLOG.md`'s matching entry.
`verify_hub()`'s own CivicPlus path keeps today's limit -- also
`BACKLOG.md`, a separate entry from the one this WO closed for List.

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
- **False-positive shapes excluded (WO-1033, found live on Dublin CA/
  Emporia KS's own homepages):** a `CivicAlerts.aspx` news item (a real
  council/commission headline still isn't a meeting page); an email-
  signup page (GovDelivery's own `.../subscribers/...`, `/list.aspx`,
  "Stay Informed"/"Notify Me"); and a bare calendar-event permalink
  (`/calendar/event/detail/<n>`, `Calendar.aspx?EID=<n>`) whose own title
  names no governing body or meeting (`GOVERNING_BODY_KEYWORDS`,
  `app/platforms/granicus.py`, plus "meeting" itself) -- an ordinary
  community event ("Night Market", "Senior Info Fair") otherwise
  qualified on a bare date alone, same as a real meeting entry.
- **A same-site social redirect is a YouTube lead, not a page or a
  media candidate (WO-1033).** CivicPlus's own quick-link-widget shape,
  confirmed live on Emporia KS: `<a href="/youtube" aria-label="YouTube">
  <img alt="YouTube"></a>`, no visible anchor text at all --
  `extract_video_id()` never recognizes a same-site path, so this used to
  vanish silently. `_youtube_leads()` now also reports this shape
  (`video_id=None`); `identify.py`'s own link scan does the same.

### Hop

Built WO-1029: `app/platforms/meeting_finder/hop.py`'s
`rank_hops(page, *, prefer_vendor=None, prefer_video=False, school=False,
french=False, limit=8) -> List[HopLink]`, `is_document_hub(page) -> bool`,
`calendar_entry_links(page, limit=2) -> List[str]` and (WO-1033)
`canonical_page_key(url) -> str` -- thin wrappers reusing
`find_hop_links()`/`looks_like_document_hub()`/`find_calendar_entry_
links()` (`scripts/wo147_access_ladder_sweep.py`) directly rather than
moved into `app/` (see `hop.py`'s own module docstring and
`BACKLOG_DONE.md`'s WO-1029 entry for the reasoning -- `fetch.py`'s own
precedent for reusing this same script's functions directly).

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
- **A word-less nav link is rescued, not rejected (WO-1033).** wo147's own
  scorer requires real path/target-shape evidence before it looks at
  anchor text at all (a guard against a real false positive: a
  CivicAlerts.aspx press release scoring high on prose alone) -- so a
  link with real hub vocabulary but a bare numeric-slug path (Emporia
  KS's real meetings hub: `<a href="/1300">Agendas & Minutes</a>`, a
  CivicPlus quick-link button) used to score nothing and not even appear
  in the top 60 candidates. `_looks_like_nav_hub_label()` recognizes a
  SHORT anchor text built only from meeting-hub vocabulary ("Agendas &
  Minutes", "Watch Meetings", as opposed to a prose sentence that merely
  contains one of the same words) and rescues it, after re-deriving
  wo147's own vendor-apex/boilerplate guards -- confirmed live: `/1300`
  now ranks #1 on Emporia's real homepage.
- **Calendar events are penalized and capped, not left to a plain score
  sort (WO-1033).** A homepage's own calendar widget (individual
  `Calendar.aspx?EID=`/`/calendar/event/detail/<n>` entries, `view=list`
  day views) can otherwise fill most of the top candidates just by
  outnumbering the real hub links -- confirmed live on both Dublin CA and
  Emporia KS. `rank_hops()` never returns more than 2 calendar-shaped
  links in its output, regardless of their individual score.
- **`prefer_video`** (new, WO-1033): once a page is known to have
  meetings but no video (the "meetings without video" case), a link
  whose text/path says watch/video/video-on-demand/live-stream/meeting-
  video gets a real boost -- confirmed on a real Dublin CA page,
  `/2875/Watch-Meetings` moves from rank 5 to rank 3 (a real 10-point
  boost). Off by default.
- **A same-site social redirect is never a hop (WO-1033).** CivicPlus's
  own `/youtube`/`/facebook` quick-link-button redirects are excluded
  outright -- Meeting Finder never fetches these hosts anyway, so ranking
  one only wastes a hop slot; `scan.py`'s `_youtube_leads()` reports the
  YouTube one as a lead instead (see Scan's own section above).
- **`canonical_page_key(url)`** (new, WO-1033): collapses a calendar URL
  that differs only in a volatile display parameter (`PREVIEW`, `month`,
  `year`, `day`, `calType`, `view`) to one key, while keeping `EID`/`CID`
  distinct -- confirmed live on Emporia KS, where the same real event is
  linked three different ways on the same page. For `runner.py`'s (WO-
  1031) own `seen`-set to use; `hop.py` doesn't call it itself.
- `looks_like_document_hub()` checks a landing page; on a plain events
  calendar, `find_calendar_entry_links()` opens its first dated entries.
- **Jev test (later):** score the same 180 real homepages the weights were
  measured on, and keep whichever finds the real hub more often.
- No limits logic inside `hop.py` itself -- `runner.py` (WO-1030) applies
  `max_hops`/`max_forks`/`max_fetches` around `rank_hops()`'s own ranked
  output (see "The phase loop" below). `rank_hops()` only takes the
  single best not-yet-seen link per level; a rejected/already-seen link
  isn't retried at that same depth.

**Limits (settings, enforced by `runner.py` since WO-1030):**

| Setting | Meaning | Default |
|---|---|---|
| `max_hops` | Depth of one path | 2 (one more from a homepage) |
| `max_forks` | Next-best links from the start page tried as new paths | 3 |
| `max_fetches` | Hard cap on page fetches per government (one shared `Fetcher`) | 12 |

Repeat Identify → List / Scan → Hop on each landing page within those limits.

### The phase loop (WO-1030)

`app/platforms/meeting_finder/runner.py`'s `run_one()`/`_run_phase_loop()`
wire every phase above into the pipe docs/MEETING_FINDER.md opens with.
One `Fetcher` per government (`FinderInput`) -- every fork and hop for
that input shares its `max_fetches` budget and its per-host politeness
spacing. A `seen` URL set, also shared across the whole walk, means a URL
is never fetched twice no matter which fork or hop reaches it.

- **Entry dispatch:** `entry="resolve"` is unchanged from WO-1024 -- the
  input URL goes straight to Resolve, no Identify/List/Scan/Hop.
  `entry="list"` requires `platform_hint` and goes straight to
  `list_account()` then Resolve. `entry="scan"` fetches the one input URL
  and runs `scan_page()` then Resolve. `entry="identify"` treats the
  input URL as the sole starting point and runs the full Identify ->
  List/Scan -> Hop loop on it (no Start, no forks beyond what Hop finds).
  `entry="start"` runs `start()` first; a DNS-dead domain reports
  `dns-unresolvable` immediately; otherwise each of `start()`'s own
  starting points becomes a fork.
- **One fork's own path:** Identify, then (if a platform+account was
  found) List, then (if nothing resolved yet) Scan on the same page, then
  (if still nothing and hops remain) Hop's single best next link,
  recursing with `hops_left - 1`. The walk stops the instant Resolve
  succeeds.
- **Forks vs hops:** a fork is one of Start's own starting points tried
  as an independent path (`max_forks` bounds how many past the first);
  a hop is Hop's own best-next-link choice made *within* one fork's path
  (`max_hops` bounds how deep one fork goes, with one extra hop for the
  very first/homepage fork -- "one more from a homepage").
- **Budget exhaustion:** a `BudgetExceeded` from any phase's own fetch
  ends that government's walk cleanly (never crashes the run) -- Verdict
  reports whatever outcome was already collected, or a plain "budget
  exhausted" note.
- **Verdict's outcome choice** ("the most informative of the phases'
  outcomes"): `_pick_outcome()` ranks every outcome collected along the
  way and keeps the highest -- a real `meeting-without-video` beats
  `account-not-found`, which beats `unsupported-platform-no-adapter`,
  which beats a generic access block (a challenge/WAF block, then a
  plain `blocked-*`, then `timeout`/`dns-unresolvable`), which beats
  reporting nothing at all (`no-meeting-nor-video`, the floor).
- **Politeness across governments sharing a vendor host:** `fetch.py`'s
  own per-`Fetcher` spacing only paces one government's own requests: two
  DIFFERENT `Fetcher`s (two governments running concurrently under
  `--concurrency`) could otherwise both hit the same shared host (many
  tenants on `*.granicus.com`, for instance) at once. WO-1030 added a
  small process-wide, host-keyed pacer in `fetch.py`
  (`_global_wait_for_host()`) that every `Fetcher` instance consults in
  addition to its own bookkeeping, so this can't happen.
- **Two known wave-2 gaps closed by WO-1030:** (1) Identify's rank-5
  "YouTube meeting list" signal used to fire on any page with 2+ distinct
  YouTube video links, including a plain promotional carousel (confirmed
  live on Piedmont, CA's own homepage: 6 unrelated parks/rec videos). It
  now only counts a video whose own link sits in a per-item dated
  row/section (reusing `scan.py`'s own date-detection helpers) -- Piedmont
  no longer reports a false `youtube_meeting_list` signal. (2) A List
  candidate with `has_video_hint=False` (e.g. `civicplus_agenda_only`'s
  real agenda rows) needed one more fix (see "Follow-up fixes" below --
  the adapter's own `resolve()` call raises rather than returning
  `agenda_items` for this shape) before it actually reached
  `meeting-without-video`; it does now, confirmed by
  `test_meeting_without_video_outcome_surfaces_from_list`.

#### Follow-up fixes (WO-1030 follow-up, same day)

The first smoke test above missed real, known-video governments -- see
this doc's Status section for the summary. Real root causes, each
confirmed fixed against the live government afterward:

- **A vendor account URL entered at `start` skips `start()` entirely.**
  `runner.py` now checks the input against the same rule-1 URL/host match
  `identify()` itself uses first; if it already recognizes a platform
  (Tacoma: `cityoftacoma.granicus.com`), the walk goes straight to
  Identify -> List on that URL, never treating it as a domain to
  DNS-guess homepages around.
- **Granicus bare-hub `view_id` discovery.** `list_recent_video_meetings()`
  (what List's Granicus walker calls) requires a URL that already carries
  a `view_id` -- a bare hub root has none. `listing.py`'s
  `_granicus_discover_view_id()` probes `ViewPublisherRSS.php?view_id=
  1..6` (RSS first, cheapest -- same range and ordering
  `scripts/wo134_confirmed_hits_ingest.py`'s own
  `granicus_locate_listing()` already uses, ported to Meeting Finder's own
  `Fetcher` so it respects the budget/politeness) and hands the real
  `ViewPublisher.php?view_id=N` URL to every other lister.
- **Breadth before depth, for real.** The phase loop now runs a cheap
  "shallow" pass (Identify -> List -> Resolve) across every fork FIRST,
  and only spends the more expensive Scan/Hop budget on a fork once none
  of them resolved on their own (`runner.py`'s `_shallow_step()`/
  `_deep_step()` split) -- confirmed necessary on Pomona, CA: the
  homepage fork's own Scan+Hop chain used to burn the entire government
  budget before `live.pomonaca.gov` (Start's own guessed subdomain, a
  real one-fetch Cablecast answer) ever got a turn.
- **Hop ranking fixes, three of them, all found on Boston/Piedmont:**
  (1) a homepage's own YouTube channel/video links are excluded from Hop
  entirely (recorded as leads instead) -- Meeting Finder never fetches
  YouTube anyway, so ranking one as the best hop just burns a hop slot on
  a guaranteed dead end. (2) A link to a platform Identify ALREADY has a
  real account for (Piedmont: CivicLive, the city's own website CMS, kept
  ranking its own further navigation pages above the real Granicus hub
  two hops away) is excluded too -- List already tried that account,
  another link to it adds nothing. (3) `rank_hops()`'s own small default
  result limit (8) meant a real candidate further down the ranked list
  never even got a chance once (1) and (2) filtered out everything ahead
  of it -- the call site now asks for a much larger candidate list before
  filtering. A URL-normalization fix (trailing slash/fragment) also
  stops a page's own canonical self-link from being mistaken for a new,
  unvisited hop.
- **Scan's own sub-page opening only recognizes vimeo/civicweb/direct-file
  media** -- a real vendor PLATFORM (Granicus) embedded on a page Scan
  opened (Piedmont's `/government/meeting_videos`) was invisible to
  Scan's own narrow media check, and the fetch was wasted. `_deep_step()`
  now asks Scan only to FIND meeting-page links (`max_meeting_pages=0`,
  no extra fetch cost), then runs the full Identify/List pass on a
  bounded number of them itself -- catching a vendor platform one click
  down, not just a bare media file.
- **CivicPlus's own listing walker can spend most of a government's
  budget confirming a real agenda-only tenant has no video** (Cass
  County, MN: up to ~8 fetches across 4 AgendaCenter category pages plus
  3 video-nav links), leaving nothing for the agenda-only fallback that
  exists specifically to report that case as `meeting-without-video`
  rather than empty. `listing.py`'s `_list_via_civicplus_light_check()`
  now runs FIRST, one real fetch to the account/AgendaCenter page (two if
  it has to fall back to the canonical `/AgendaCenter` guess), answering
  both "is there video" and "is there a real agenda-only meeting" from
  the SAME page before the heavier walker ever runs. `resolve.py` also
  needed a companion fix: CivicPlus's own adapter `resolve()` raises
  `NoVideoCandidateFound` for a single `ViewFile/Agenda` URL rather than
  returning `agenda_items`, so a lister-confirmed `has_video_hint=False`
  candidate now counts as a real `meeting-without-video` finding even
  when the adapter itself never returns a `ResolvedMeeting` to read
  `agenda_items` off of.

**WO-1054 (Ryan's link-context rule, 2026-09-24): a link's own nearby
paragraph, not just its click text, can make it a strong hop, off-site
included.** `hop.py`'s `_rescue_link_context_broadcast_score()` reads the
anchor's nearest paragraph/list-item/table-cell for phrases like "streams
the meetings", "airs replays", "broadcast", "channel 18", or "watch ...
live"/"watch ... replay" -- confirmed live on Lake Oswego, OR's real
meetings page, whose own link text is a generic "Check their website"
pointing at `tvctv.org` (the actual sentence naming the broadcast partner
is one paragraph away). Guarded by the same vendor-marketing-apex check
every other rescue in this module uses.

### Resolve

- One picking rule (from `pick_calendar_candidates()`): a real date, a
  meeting-like title, newest first.
- Run the adapter on each candidate until one has a transcript, or a
  probed video of reasonable length (`queue_probe.probe_queue_entry()`).
- Tier-3 length rule: over 90 minutes, look for a shorter meeting from the
  same government first.
- Before calling a channel off-mission, look at 3 or more videos.
- **WO-1054 (Ryan's rule, 2026-09-24): a broken TelVue link falls back to
  the same channel's own listing once.** A TelVue candidate found via Hop
  can itself be a stale link (confirmed live: College Township, PA's own
  "C-Net Meeting Broadcasts" nav points at a `/playlists/{n}/media/{m}`
  URL that 404s). When a TelVue candidate's `resolve()` call fails,
  `resolve.py`'s `_telvue_broken_media_fallback()` tries the SAME org
  token's `/home`/`/videos` listing once (reusing `passive_verify.
  _telvue_walker()`, which already reduces any TelVue URL to that
  canonical entry point) and offers its real videos as fresh candidates,
  rather than reporting the one broken link as "nothing found".

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

Not a phase: one fetch helper (`app/platforms/meeting_finder/fetch.py`)
used by Start, Identify, Scan and Hop.

| Rung | When |
|---|---|
| Plain request | Always first |
| Browser headers | Only after a 403 or a dropped connection |
| Headless browser | Only when a page loaded but shows no links |
| Wayback's latest copy | After a human-verification challenge, **or after the ladder ends in an ordinary hard block with no challenge marker** (a 403/dropped connection that persists through the browser-headers rung -- WO-1032). **For links only**, recorded with the snapshot date. Never the government's own media. The outcome string itself doesn't change; `FetchResult.wayback_timestamp` being set is the flag that Wayback links were used |

We never try to get past a site's challenge. Per-host politeness spacing
and robots.txt apply as in stage 1.

**YouTube:** Meeting Finder never fetches YouTube. It installs
`scripts/youtube_fetch_guard.py` first; YouTube finds become drip leads
in rtr-business `research/youtube_channel_leads.csv`.

**Pacing and counting cover the WHOLE walk, not just `fetch.py`'s own
budgeted fetches (WO-1032).** `max_fetches` (12 by default) only ever
counted `Fetcher`'s own requests of the target site. A conductor trace of
`dublin.ca.gov` found 55 real HTTP requests for one government, only 12
of them counted -- the other 43 came from adapters opening their own
`aiohttp` sessions (`app/platforms/granicus.py`'s caption/agenda/channel
fetches, `app/platforms/queue_probe.py`'s HLS probe), which skipped
`Fetcher`'s per-host pacer entirely. `app/platforms/meeting_finder/
pacing.py`'s `pace_all_requests(fetcher)` is a context manager the runner
activates around one government's whole walk: while active, EVERY real
`aiohttp` request process-wide -- not just `fetcher`'s own -- is paced
against the same per-host pacer (robots.txt `Crawl-delay` included where
`fetcher` already knows it) and counted into a `RequestStats`
(`requests_total`, `requests_by_host`), reported *alongside*
`fetcher.fetches_used`, never folded into it (folding it in would let one
Granicus caption fetch's several requests starve the walk's real
`max_fetches` budget before Resolve got a turn). See that module's own
docstring for why `fetcher`'s own requests are counted but not
re-paced (avoids doubling the wait for its own already-paced fetches),
and for the `contextvars` mechanics that keep two concurrent governments'
counts from mixing.

## Second pass, one more hop, adaptive budget (WO-1074, 2026-09-25)

Calibration set D (2026-09-25) found 1,581 known-video governments, 728
found (46%): 380 ending `youtube-lead-only` (about 190 of those had a
known non-YouTube video platform on file), 149 ending
`meeting-without-video`, and about 70 running out of budget. Three
rescues, all in `runner.py`, all bounded so a government that never
shows promising evidence pays nothing extra:

1. **Second pass** (`_second_pass_for_youtube_only()`): before settling
   for `OUTCOME_YOUTUBE_LEAD_ONLY` (no platform account, no meeting video
   anywhere in the walk), spend `second_pass_extra_fetches` more (default
   8, `--second-pass-extra-fetches`) on a focused pass across every
   fork's own already-fetched page, following only links whose text/URL
   carries site-nav vocabulary (Meetings / Agendas & Minutes / Government
   / Council / Board / Watch / Video / Media / TV --
   `_SECOND_PASS_NAV_WORDS_RE`). Never fires once real, non-YouTube
   evidence (a meeting-without-video listing, a foreign-hub lead) is
   already on record -- that walk reports the real finding instead.
2. **One more hop** (the `_deep_step()` `elif` branch, `_CONTEXT_HOP_
   WORDS_RE`): when the ordinary hop budget for a fork is spent but the
   page in hand is a real meetings/agenda hub (`hop.is_document_hub()`)
   or the walk already found a meeting with no video, one extra hop is
   allowed for a link whose own anchor text or URL carries a broadcast
   context word (video/watch/broadcast/stream/replay/TV/channel). Test
   case: Lake Oswego, OR (`citycouncil` -> `city-council-meetings` -> the
   TVCTV sentence -> `tvctv.org`, three real hops past a homepage that
   itself already cost one). One extra hop total per government
   (`_WalkState.bonus_hop_available`), not a second `max_hops`.
3. **Adaptive budget** (`_maybe_raise_budget()`): once a government's
   walk turns up a meetings page, a recognized video-platform account, or
   a meeting-without-video listing, its own fetch cap is raised to
   `adaptive_max_fetches` (default 24, `--adaptive-max-fetches`) instead
   of stopping at the ordinary default -- once per walk, logged on the
   Verdict row's own `note` ("adaptive budget: raised to N fetches
   (reason)").

Live before/after numbers against calibration set D's own youtube-lead-
only/meeting-without-video/budget-exhausted governments are in this WO's
own PR description.

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
