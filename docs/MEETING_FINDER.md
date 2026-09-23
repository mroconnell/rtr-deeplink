# Meeting Finder — design

**Status:** design agreed with Ryan on 2026-09-23 (WO-1023). Not built yet.
Code will live beside the adapters, in `app/platforms/meeting_finder/`,
with a command-line runner in `scripts/meeting_finder.py`.

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

Uses `app/platforms/media_scan.py`.

- **Media links:** `.mp4`, `.m3u8`, Vimeo, Google Drive, CivicWeb.
  YouTube becomes a drip lead.
- **Meeting-page links:** dated agenda pages, `?EID=123`, `/event/123/`,
  `/meetings/2026-09-08-council`. Open the newest few and scan each.
  Embedded video is often only visible one click down.

### Hop

- `find_hop_links()` (`scripts/wo147_access_ladder_sweep.py`) with the
  measured `app/utils/jurisdiction_data/hop_link_weights.csv` (school and
  French versions exist).
- `looks_like_document_hub()` checks a landing page; on a plain events
  calendar, `find_calendar_entry_links()` opens its first dated entries.
- **Jev test (later):** score the same 180 real homepages the weights were
  measured on, and keep whichever finds the real hub more often.

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
