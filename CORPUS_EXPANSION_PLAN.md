# Corpus expansion: discover and ingest new meetings from already-covered tenants

**Status: planned, not built.** This document records the design so a
future session (or a returning one) doesn't have to re-derive the sizing
numbers or re-discover which platforms already support this. Nothing
described here exists in code yet.

## Why

The Archive already covers ~2,300 jurisdictions / 3,435 archived meeting
pages across ~2,358 distinct tenant sites (see `/coverage/detail`). All
of that was built one meeting at a time — the resolver has only ever
been designed to resolve a single, already-known URL, never to ask a
tenant "what other meetings do you have?" The ask this document answers:
build script-based infrastructure to *discover* additional meetings from
tenants we already know how to resolve, validate them, and ingest them
in bulk — filterable by platform, jurisdiction confidence, US/state,
date range, and topic — favoring a fast/bounded search over an
exhaustive one, with min/max goals overall and per tenant.

## Sizing (live production data, pulled 2026-08-30)

Only four mechanisms today can list a tenant's meetings beyond one
already-known URL:

| Mechanism | Tenants today |
| --- | --- |
| Granicus (per-tenant RSS feed) | 732 |
| CivicClerk (Events API) | 245 |
| PrimeGov (`ListArchivedMeetings` API) | 49 |
| YouTube channel listing (yt-dlp) | 4 configured (Phoenix, Baltimore, Albuquerque-committees, Philadelphia) — only Phoenix and Baltimore have ever actually been exercised in the corpus so far |
| **Total** | **~1,030 tenants (~44% of ~2,358)** |

Everything else — eScribe, CivicPlus, Hyland, CivicWeb, Lims, Cablecast,
TownHallStreams, ProudCity, TelVue, Swagit (tenant level), Vimeo,
generic_fallback — has no enumeration method built at all. Building one
for any of them is real, separate reverse-engineering work (per this
repo's own "test against a real live URL first" convention in
`CLAUDE.md`), not something a filter flag can shortcut. Legistar's own
enumeration API (`webapi.legistar.com/v1/{client}/events`, already used
in `scripts/find_tier3_short_meeting_substitutes.py`) adds essentially
nothing beyond the above: of only 8 Legistar tenants in the whole
corpus, 3 already resolve through Granicus, 4 through the YouTube
channel fallback, and 1 through Cablecast (not enumerable).

Auto-transcription overlap, by platform (jurisdiction-level, from the
live coverage table):

| Platform | Instant transcript already |
| --- | --- |
| PrimeGov | 43 / 43 (100%) |
| YouTube-hosted (incl. PrimeGov/CivicWeb/generic-YouTube-embed pages, which all store `platform="youtube"` due to delegation) | 216 / 216 (100%) |
| Granicus | 238 / 684 (35%) |
| CivicClerk | 69 / 258 (27%) |

Pulling more meetings from PrimeGov and YouTube-hosted tenants is close
to a sure thing for instant transcripts; Granicus and CivicClerk are
real but roughly a 1-in-3 hit rate on caption availability (resolve
still gets video either way).

## Explicitly out of scope, and why

- **Duration.** Not stored anywhere queryable at corpus scale
  (`MeetingPage` has no duration column; it only exists on the ephemeral
  `TranscriptionJob` row, meaningless for most of the corpus). Since
  transcription here is on-demand/instant rather than a pre-computed
  batch queue, duration was never really a cost lever to filter on in
  the first place — **dropped entirely**, not deferred, per the user's
  own call.
- **Topic in agenda specifically vs. transcript specifically.**
  `MeetingPage.search_corpus` already merges title+jurisdiction+
  agenda+transcript into one FTS-indexed blob
  (`archive/utils/search.py:64-83`), which makes "topic mentioned
  *anywhere*" cheap — but splitting that requires decoding
  `agenda_items`/`segments` JSON per candidate, the same per-row
  JSON-scan pattern that has previously saturated production I/O (see
  `BACKLOG.md`'s Standing Decisions). The user's stated direction: the
  eventual right architecture is the upcoming `rtr-upcoming` app
  discovering meetings/agendas *before* video exists, filtering on
  topic at that (cheap, text-only) stage, and only ingesting video as a
  last step — so this script was never meant to solve agenda-vs-
  transcript topic filtering itself.

## What v1 would do

One new script, `scripts/discover_new_meetings.py`, following this
repo's established bulk-script shape (mirrored from
`scripts/dedupe_rollup_transcripts.py`'s CLI/report conventions and
`scripts/backfill_archived_pages.py`'s circuit breaker):

1. **Seed candidate tenants** from the Archive's own data — reuse the
   existing `GET /internal/pages/all-urls` endpoint
   (`archive/db/crud.py:1074`, already called by
   `scripts/backfill_archived_pages.py`) to get every archived page's
   `platform`/`source_url_normalized`, group by netloc to get the real
   tenant list per platform (exactly the analysis behind the sizing
   table above). No new DB work needed — `MeetingPage` has no tenant
   column, but netloc-from-URL is already precedented
   (`scripts/dedupe_rollup_transcripts.py`'s `source_host()`).

2. **Per-platform "list this tenant's candidate meetings" functions** —
   lighter than originally scoped, since one of the four already has a
   general-purpose item lister built:
   - **Granicus**: `app/platforms/granicus_channel.py`'s `_ITEM_RE` /
     `_item_local_date()` / `_item_body_and_clip_url()` (lines 93-156)
     already parse *every* `<item>` in a `ViewPublisherRSS.php` feed
     into (body, date, clip URL) — built for
     `find_view_publisher_match()`'s one-match search, but the
     per-item parsing itself is already fully general. Needs a thin
     new function that returns the whole list instead of filtering to
     one match, plus extending `_VIEW_PUBLISHER_FALLBACKS` (currently
     a curated per-tenant registry, see that file) to cover ordinary
     direct-Granicus tenants, not just the Legistar-fallback case it
     was built for. `app/platforms/granicus.py`'s own
     `_fetch_channel_info()` (lines 1073-1173) parses the same feed
     shape a second, independent way (channel title + one clip_id's
     date) — worth reconciling into one shared parser rather than
     three separate regex sets across two files.
   - **PrimeGov**: generalize the `ListArchivedMeetings`/
     `GetArchivedMeetingYears` call (`app/platforms/primegov.py:26,
     479,530`) into "every meeting for this tenant, optionally bounded
     by year" — currently only used to match one `meetingTemplateId`.
   - **CivicClerk**: reuse `cc_list_past_events()`
     (`scripts/find_tier3_short_meeting_substitutes.py:256-368`)
     directly — already general.
   - **YouTube channel**: reuse `_list_channel()`/`_list_channel_tab()`
     (`app/platforms/youtube_channel.py:471-521`) directly — already
     general, already TTL-cached.
   - Each returns candidate URLs normalized enough to dedupe against
     step 1's known-URL set before ever resolving anything (skip
     anything already archived).

3. **Filters, applied to candidates before resolving** (cheap ones
   first, to shrink the resolve/ingest workload):
   - `--platform` (granicus/civicclerk/primegov/youtube_channel) —
     trivial.
   - `--min-confidence` (`jurisdiction_confidence IN (...)`, using the
     real ladder from `app/utils/jurisdiction_enrich.py`:
     `authoritative`/`validated`/`repaired`/`fallback`/`unverified`/
     `blank`) — applied post-resolve, since confidence is only known
     once a candidate is actually resolved.
   - `--state`/`--us-only` — parsed via the already-existing
     `state_abbr_from_jurisdiction()`/`is_canadian_abbr()`
     (`archive/utils/jurisdiction_format.py:152,166`), same pattern
     `crud.get_state_coverage_index()` already uses at full-corpus
     scale. Applied post-resolve, same reason as confidence.
   - `--date-from`/`--date-to` — cheap wherever the platform's own
     listing exposes a date (PrimeGov/Granicus RSS both do); applied
     at the candidate-list stage, before resolving, so it actually
     saves work.
   - `--topic` — matched against the resolved candidate's own text
     (title/agenda) at ingest-decision time via the same substring/
     keyword approach `archive/topics.py:367`'s `topics_in()` uses, or
     a plain case-insensitive substring check if the query isn't in
     the curated topic list. Cheap because it only runs on
     already-resolved candidates, not a corpus-wide scan.

4. **Speed vs. thoroughness** — a `--mode fast|thorough` flag mapping
   to per-platform pagination-depth presets (PrimeGov's year-range,
   YouTube channel's `playlistend`, Granicus RSS's natural item cap)
   and how many consecutive already-known-URL hits before giving up on
   a tenant early. Purely a tuning knob, no new computation.

5. **Min/max goals** — `--target-total` (overall) and
   `--target-per-tenant` (each), both cheap counters tracked during the
   sweep; a tenant that can't reach its per-tenant minimum (genuinely
   out of new candidates) is reported honestly, not retried.

6. **Validate + ingest**, reusing existing machinery directly:
   - Resolve via `detect_platform()`/`get_finder()`/
     `resolve_via_platform()` (`app/platforms/base.py`).
   - "Worth ingesting" gate: `result.segments or result.agenda_items or
     result.agenda_link or result.video_url`
     (`scripts/bulk_ingest.py`'s existing gate).
   - Push via `_ingest()` (`scripts/bulk_ingest.py`) — server-side
     dedup by content-hash already exists in `ingest_resolution()`, so
     a re-run is naturally idempotent.
   - Dry-run by default, `--apply` to actually write — same convention
     as every other script in `scripts/`.
   - Sequential only, per-request delay separated by call type (own
     Archive vs. real government site — same split
     `dedupe_rollup_transcripts.py` already uses:
     `DEFAULT_PROBE_DELAY_SECONDS = 0.25` vs
     `DEFAULT_RESOLVE_DELAY_SECONDS = 2.0`).
   - Circuit breaker: `MAX_CONSECUTIVE_FAILURES = 5`, checked on every
     failure path, immediate hard-stop on `looks_rate_limited()`
     (`app/utils/rate_limit.py`) — same as `backfill_archived_pages.py`
     /`dedupe_rollup_transcripts.py`.
   - SSL/import-order boilerplate (`SSL_CERT_FILE` set before `import
     aiohttp`, `load_dotenv()` only inside `__main__`) — copy verbatim
     from any sibling script.

7. **Report**: a `--report-file` JSON summary (per-tenant candidates
   found/filtered/ingested/skipped, honest min/max-goal shortfalls),
   matching `dedupe_rollup_transcripts.py`'s dry-run-report convention
   — though unlike that script's repair tools, ingestion here is
   additive and idempotent (never mutates an existing page), so
   `--apply` doesn't need a separate `--from-report` review step to be
   safe; it can run directly, still dry-run-gated by default.

## Files a real implementation would touch

- **New**: `scripts/discover_new_meetings.py` (the script itself).
- **New**: `tests/test_discover_new_meetings.py` (pure-logic tests for
  the filter/dedup/goal-tracking functions, plus per-platform
  candidate-listing tests using real fixture data — e.g. a real
  trimmed Granicus RSS feed, a real PrimeGov `ListArchivedMeetings`
  JSON response, following this repo's "synthetic tests need a
  real-verified schema" convention from `CLAUDE.md`).
- **Touched, lightly**: `app/platforms/granicus_channel.py` (add a
  "list every item" function alongside the existing one-match search;
  consider widening `_VIEW_PUBLISHER_FALLBACKS` beyond its current
  Legistar-fallback-only scope), `app/platforms/primegov.py`
  (generalize the archived-meetings API call to not require a target
  `meetingTemplateId`) — both additive; existing single-meeting call
  sites keep working unchanged.
- **Reused, untouched**: `app/platforms/base.py`,
  `app/platforms/youtube_channel.py`, `scripts/bulk_ingest.py`,
  `scripts/find_tier3_short_meeting_substitutes.py` (pattern reference
  for CivicClerk listing), `archive/utils/jurisdiction_format.py`,
  `archive/topics.py`, `app/utils/rate_limit.py`.

## Verification, when this is actually built

- Unit tests for filter logic, goal-tracking, and dedup-against-known-
  URLs (pure functions, no network).
- `--dry-run --limit 5 --platform primegov` (and one more platform)
  against production, read-only, to confirm real candidates are found
  and correctly filtered/reported before any `--apply` run.
- Full CI gates: `ruff check`, `ruff format --check`, `pytest`,
  `alembic check` (no schema change expected — this reads/writes
  existing tables through existing ingest machinery only).
- A small, explicitly-approved `--apply --limit 3` run against one real
  tenant to confirm an actual ingest round-trips correctly (new page
  appears, dedup on re-run is a no-op) before any larger sweep.
