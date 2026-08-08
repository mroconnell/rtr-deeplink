# rtr-deeplink

Paste the URL of a public government meeting recording. Get back the video
and its transcript, side by side, with every line clickable — and a URL you
can share that lands someone at that exact moment.

No background jobs. Given a meeting URL, the app resolves its video and
transcript on demand and renders them. Deep-linking to an exact moment is
the primary goal; the transcript is a nice-to-have on top of that.

There's an optional database (see [Caching and reporting](#caching-and-reporting)
below) that caches resolved meetings and logs every resolve attempt for
admin reporting — but it's not required to run the app. With no `DATABASE_URL`
set, the app falls back to a local SQLite file, and if the database is ever
unreachable, `/api/resolve` degrades silently to its original zero-persistence
behavior rather than failing.

Permanent, publicly shareable meeting pages (with multiple transcript
versions/languages) live in a separate app, `archive/` — see
[Permanent pages (the Archive)](#permanent-pages-the-archive) below. This
resolver itself still never hosts public content pages directly; that's
the whole reason the Archive is a separate app rather than a feature bolted
onto this one.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```

Then open `http://localhost:8010`, paste a meeting URL, and go.

No further setup needed — with no `.env`, the app uses a local SQLite file
for caching/reporting. Copy `.env.example` to `.env` and fill in `DATABASE_URL`
only if you want to point at a real Postgres instance instead.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/` covers the platform-independent utilities (`app/utils/vtt_parser.py`,
`app/platforms/media_scan.py`, `app/platforms/base.py`'s `detect_platform`)
directly, and exercises Granicus/Legistar/CivicPlus/CivicClerk/Swagit/
CA Legislature end-to-end against real fixture files saved under
`tests/fixtures/` (fetched live from real government sites, not synthetic
— see each fixture directory for where it came from; `tests/fixtures/
civicplus/README.md` explains the one exception, hand-built to match a
real site's confirmed structure since that live site has since changed).
HTTP calls are mocked via a small in-repo `tests/aiohttp_mock.py`, not
`aioresponses` — its latest release doesn't support the aiohttp version
this project's unpinned `aiohttp>=3.9` resolves to today. Also covers
`archive/utils/search.py`'s exact/fuzzy matching logic directly (pure
functions, no DB or mocking needed —
`tests/test_archive_search.py`). eScribe and PrimeGov/YouTube don't have
test coverage yet — a good next place to extend this suite.

## How it works

### The resolve flow

When you paste a meeting URL, the app has to figure out which government
video platform it's looking at, fetch the video and transcript from that
platform's own site, and hand back something the page can render — all in
the few seconds you're waiting. Here's that path in detail:

1. The frontend (`app/static/player.js`) POSTs the pasted URL to
   `/api/resolve`.
2. `app/platforms/base.py`'s `detect_platform(url)` looks at the URL's
   domain (and sometimes path) and classifies it as one of the platforms
   below.
3. The matching `AssetFinder` (one class per platform, all in
   `app/platforms/`) fetches whatever it needs — usually the meeting page's
   HTML, sometimes a small REST API — and returns a `ResolvedMeeting`:
   title, date, jurisdiction, a playable video URL, transcript segments
   (`{start, end, text}`) if any were found, and agenda/chapter-marker
   items (`agenda_items`, same `{start, end, text}` shape) if any were
   found — kept as a separate field so agenda data is never mistaken for
   a real transcript.
4. `/meeting?url=<source>` (served by `app/templates/meeting.html` +
   `player.js`) calls `/api/resolve` client-side and renders the result:
   video player (hls.js for `.m3u8`, native `<video>` otherwise), then an
   Agenda section (if any agenda items were found), then a clickable
   Transcript section. Agenda is populated independently of transcript
   availability, so a meeting with both shows both at once.

The rendered page itself is never cached — every page load re-resolves from
the source URL. What *can* be cached is the resolve result: if a database is
configured, `/api/resolve` checks it first (keyed on a normalized version of
the URL) and serves a prior successful resolve instead of re-fetching from
the government source. Reloading a deep link re-runs the resolve either way
(live or cached) and lands you back at the same moment.

### Three response shapes from `/api/resolve`

Not every pasted URL is a clean win — sometimes it points at a list of
meetings instead of one specific meeting, and sometimes it's a platform
this app doesn't know how to read yet. `/api/resolve` always returns one
of these three shapes, so the frontend knows exactly how to react instead
of guessing from an error string:

- **A resolved meeting** — the normal case: a `ResolvedMeeting` JSON blob
  (see `app/platforms/models.py`).
- **`{"error": "calendar_page", "candidates": [...]}`** — the URL was a
  calendar/listing page (e.g. a Legistar `Calendar.aspx` or a CivicPlus
  AgendaCenter category) rather than one specific meeting. Instead of
  failing, the adapter pulls every meeting it can find on that page
  (title, date, direct URL) and the frontend shows a pick-list
  (`renderCalendarPage()` in `player.js`).
- **`{"error": "unsupported_platform" | "resolve_failed", ...}`** — the
  platform isn't recognized, or resolution threw. Shown as a plain message.

### Deep links

Linking someone straight to the exact moment in a meeting — not just the
video in general — is the entire reason this app exists. That link is
just a couple of URL query parameters, read back out on page load:

A URL like `/meeting?url=<source>&t=630&line=seg-42` means: seek the video
to 630 seconds and highlight transcript segment 42. `t` always wins for the
actual seek position; `line` is only used to decide which row to highlight
(see the comment above `applyDeepLink()` in `player.js` for why — `line`
used to take priority and silently truncate precision on coarse-grained
sources like chapter markers).

Every interaction that produces a link (clicking a timestamp, the per-line
link icon, "Copy link to current time", the manual "Go to time" box) goes
through the same `updateUrlParams()` helper, so all four stay consistent.

## Caching and reporting

Re-scraping a government site every single time someone revisits the same
meeting is wasteful and slow, and nobody can tell what's actually working
across hundreds of different city websites without some kind of record of
every attempt. `app/db/` solves both, optionally: `/api/resolve` can skip
the live fetch when it's already resolved a URL successfully before, and
every attempt — success or failure — gets logged for later review.

`app/db/` adds an optional Postgres-backed (SQLite locally) layer with two
jobs: a read-through cache in front of the live resolve, and a log of every
resolve attempt for admin reporting. Neither is required — see the note in
the intro above about graceful degradation with no `DATABASE_URL` set or an
unreachable database.

- **Cache**: `/api/resolve` checks for a prior *successful* resolve of the
  same normalized URL (`app/utils/url_normalize.py`) before doing a live
  fetch. Failed/calendar/unsupported attempts are never cached, so a
  currently-broken URL always re-fetches live — that's deliberate, both so a
  fixed bug or a transient outage doesn't get stuck serving a stale failure,
  and so every real failure still gets logged for reporting.
- **Reporting log**: every resolve attempt — success or failure — is logged
  unconditionally to the `meeting_resolutions` table (`app/db/models.py`).
  `app/db/outcomes.py`'s `classify_outcome()` buckets each logged row by
  actual content quality, not just whether `resolve()` raised:
  - `success` — a real transcript in the target language, not garbled
  - `agenda_fallback` — no real transcript, but agenda/chapter-marker data
    was found instead (Granicus, CivicClerk, or Swagit) — still deep-linkable,
    but not a real transcript
  - `blank_transcript` — video found, nothing usable for a transcript at all
  - `garbled_transcript` — a real transcript, but flagged as likely garbled
    at the source (see `is_likely_garbled()` in `vtt_parser.py`)
  - `non_english_transcript` — a real transcript, just not in the target
    language
  - `no_video` — resolved without a playable video
  - `resolve_failed` / `calendar_page` / `unsupported_platform` — the
    existing `/api/resolve` error shapes

  Agenda/chapter-marker data lives in its own `ResolvedMeeting.agenda_items`
  field, separate from `segments` (see "Supported platforms" below), and is
  fetched regardless of whether a real transcript was also found. So
  `classify_outcome()` checks `resolved_payload["agenda_items"]` directly to
  decide `agenda_fallback` vs. `blank_transcript` — only reached when
  `transcript_found` is false, since a meeting with both a real transcript
  and agenda data still classifies as `success`.

Admin endpoints, all gated by `ADMIN_STATS_TOKEN` (`?token=...`, returns 404
rather than 401/403 on a missing/wrong token so the route isn't
distinguishable from a typo):
- `GET /admin/stats` — aggregates: totals, success rate, cache hits, average
  resolve duration, counts by platform × outcome, recent non-success rows.
- `GET /admin/log?limit=&format=json|csv` — the unaggregated per-attempt
  list (URL, platform, outcome, language, timestamp), most recent first.
- `GET /admin/problem-reports?limit=` — user-submitted "something's wrong
  with this meeting" reports, most recent first.
- `GET /admin/recheck-archive-page?url=` — force an immediate re-resolve +
  Archive push for one meeting, instead of waiting for the passive 30-day
  `ARCHIVE_RECHECK_AFTER` recheck. For when a permanent page needs a fix
  (e.g. an adapter bug fix, or a source that's since added captions) to
  land sooner. Returns what it found (segment/agenda counts, warnings,
  whether anything was pushed) synchronously, unlike the passive recheck.

See `.env.example` for the two env vars (`DATABASE_URL`, `ADMIN_STATS_TOKEN`).

## Permanent pages (the Archive)

The resolver above is deliberately disposable — it re-fetches from
scratch every time and remembers nothing public. But some meetings
deserve a permanent, linkable, search-engine-indexed page of their own,
the way a news article does — so a second, separate app (`archive/`)
takes a successfully resolved meeting and gives it a real, permanent home
at `redtaperecordings.com/m/{slug}`.

This resolver stays deliberately stateless per meeting — the `meeting_resolutions`
table above is a private cache/log, not a public archive. Permanent,
SEO-indexed meeting pages live in a **separate app**, `archive/` (its own
FastAPI service, own database, own deploy) — not grown into this resolver,
so this app keeps its single job: resolving, not hosting public content
pages. See `archive/` for that app's own structure; this section covers
only the handoff between the two.

**Domain**: permanent pages are reachable at `redtaperecordings.com/m/{slug}`
— same domain as everything else, for SEO and sharing consistency. This
resolver's service holds the custom domain, so it reverse-proxies `/m/*`
and `/archive-static/*` through to the Archive's own Render service
(`app/archive_client.py`'s `proxy_get()`, wired up in `app/main.py`). A
failure to reach the Archive here returns a clean 503, not a hang or a raw
exception — these are public, potentially-indexed pages.

**Lookup, before resolving**: `/api/resolve` calls `archive_client.lookup()`
*before* checking its own local cache or doing a live resolve. If a
permanent page already exists for the normalized input URL, the response is
`{"redirect_url": "/m/{slug}"}` instead of a `ResolvedMeeting` — `player.js`
sends the browser there (preserving `?t=`/`?line=` from the current URL),
consolidating traffic and sharing on the canonical permanent URL rather than
re-scraping. This lookup only has the raw pasted URL to go on, which is why
the Archive keeps a `MeetingPageUrlAlias` table recording every URL that's
ever successfully pushed — without it, a Legistar/CivicPlus/PrimeGov URL
(whose real identity lives on the platform it delegates to, not the URL the
user pasted) would never match on a repeat paste.

**Push, after resolving**: after a live resolve succeeds with real content
(`segments` or `agenda_items` non-empty — blank/failed resolves are never
pushed, so test pastes and broken URLs don't create junk permanent pages),
`/api/resolve` fires `archive_client.push()` via FastAPI's `BackgroundTasks`
(not a bare `asyncio.create_task`, which risks the task being
garbage-collected mid-flight). The Archive matches the push against an
existing `MeetingPage` by `(platform, external_id)` when available, else by
the resolved URL, and either creates a new page or attaches a new
`TranscriptVersion` to an existing one (deduped by a content hash, so
re-pushing an unchanged meeting doesn't pile up duplicate versions). Both
`lookup()` and `push()` are wrapped in the same `safe()` pattern as the DB
calls above — a down/misconfigured Archive degrades silently, never breaks
`/api/resolve`.

**Redirect hits are logged too** — `status="archive_redirect"` — so
`/admin/stats`' totals don't develop a blind spot as more traffic migrates
to Archive-redirects over time; `classify_outcome()` in `app/db/outcomes.py`
returns it directly (any non-`"success"` `status` passes through as-is).

Local dev runs both services side by side:

```bash
# terminal 1
uvicorn app.main:app --reload --port 8010
# terminal 2
ARCHIVE_INGEST_TOKEN=devtoken uvicorn archive.main:app --reload --port 8020
```

With `ARCHIVE_BASE_URL=http://localhost:8020` and a matching
`ARCHIVE_INGEST_TOKEN` set for the resolver (see `.env.example`), pasting a
URL twice will resolve live the first time and redirect to `/m/{slug}` the
second. Leaving `ARCHIVE_BASE_URL` unset disables the integration entirely
— `/api/resolve` just always live-resolves, same as before this feature
existed.

**Discoverability**: `GET /meetings` (proxied like `/m/*`) is a paginated,
server-rendered index of every permanent page (`crud.list_pages()`,
20/page) with a search box and jurisdiction/date-range/has-transcript/
has-agenda filters — all plain GET params, so results are
shareable/bookmarkable URLs with no JS required. `GET /sitemap.xml` and
`GET /robots.txt` (the latter lives on the resolver, not proxied, since
`robots.txt` has to be at the domain root) give search engines an actual
crawl path to `/m/{slug}` pages, which previously had none —
`robots.txt` also disallows `/meeting` (the ephemeral resolver page) so
it doesn't compete with the permanent version of the same content once
one exists.

**Search** covers title, jurisdiction, agenda item text, and the default
transcript version's segment text — not just title/jurisdiction like the
original v1. Two modes, chosen by an "exact"/"fuzzy" checkbox in the UI
(`fuzzy=true` query param), exact by default:
- **Exact** (default, faster): a plain case-insensitive substring match
  against everything above, concatenated. No per-word computation, so
  this is the cheap path a search that doesn't need typo tolerance should
  use.
- **Fuzzy**: tokenizes that same text into words and matches each query
  term against real transcript words within a small edit-distance
  (typo tolerance) — so a query for "traffic" still finds a transcript
  that says "trafic" or "traffiq" (real transcription errors, not
  hypothetical), where exact substring search would silently miss it.

Both modes run entirely in Python, at query time, over whatever
`list_pages()`'s own DB query already returned — see `archive/utils/
search.py` and the docstring on `list_pages()` for the full reasoning.
Deliberately **not** what this eventually needs at real scale: a
materialized/indexed search column (e.g. Postgres trigram search over a
`tsvector`-style column, populated at ingest time) instead of scanning
every candidate meeting's JSON on every search request. Fine today at a
few dozen meetings; tracked as a real follow-up (not a hypothetical one)
in `BACKLOG.md`, including what populating that column would look like
without adding a job queue (piggybacking on the ingest write that's
already backgrounded via FastAPI's `BackgroundTasks`, not blocking
`/api/resolve`'s response — see "Push, after resolving" above) and what a
one-time backfill for already-archived meetings would need.

## Supported platforms

Most local governments don't build their own video/meeting-minutes
website — they buy one from a handful of vendors, so a fairly small
number of platforms cover a huge number of cities and counties. This app
supports a platform once, and every city on that platform works.

One `AssetFinder` per **platform**, not per city — cities on the same
platform share the same page/API structure. Detection lives in
`detect_platform()`; adapters are registered in `app/main.py`.

| Platform | File | How video is found | How captions/agenda are found |
|---|---|---|---|
| Granicus | `granicus.py` | Regex-scan the page HTML for `.m3u8`/`.mp4` URLs (shared `media_scan.py` helper) | Guessed `/videos/{id}/captions.vtt` path + scanned `.vtt` URLs; language verified from actual cue content (not the untrustworthy `srclang` label); RSS channel title (`ViewPublisherRSS.php`) used for reliable jurisdiction/title. Agenda items (`AgendaViewer.php`'s chapter markers) are fetched independently of transcript availability into their own `agenda_items` field, when that customer has Granicus's native agenda index turned on (not universal — some customers redirect it to their own site instead, surfaced as a plain link instead) |
| CivicClerk | `civicclerk.py` | Public REST API (`<subdomain>.api.civicclerk.com`) — the portal page itself is a client-rendered SPA with nothing to scrape | `closedCaptionTracks`/`closedCaptionUrl` when populated — real format is **SRT**, not VTT (confirmed live); language verified from actual cue content, same distrust-the-label approach as Granicus. The API's `eventBookmarks` (agenda-item timestamps) are fetched independently into `agenda_items` |
| Swagit | `swagit.py` | jwplayer JSON blob embedded in the page (shares Granicus's CDN infra, but a different page shape) | `.playerControl[data-ts]` agenda-item markers fetched independently into `agenda_items` |
| eScribe | `escribe.py` | `<div id="isi_player" data-client_id data-stream_name>` when present — video integration varies entirely by city, "no video" is a normal outcome here | iSiLIVE captions, keyed by language suffix in the filename (`{file}.vtt`, `{file}.fr.vtt`, ...) |
| California Legislature | `ca_legislature.py` | Self-hosted (`stream.{assembly,senate}.ca.gov`), not a vendor platform | Self-hosted `.vtt` at a matching filename; genuinely high quality when present |
| Legistar | `legistar.py` | Doesn't host video — finds the embedded/redirected link to a platform above (usually Granicus) and delegates via `resolve_via_platform()` | Whatever the delegated platform provides |
| CivicPlus | `civicplus.py` | Same delegation pattern as Legistar, from AgendaCenter listing rows | Whatever the delegated platform provides |
| PrimeGov | `primegov.py` | Doesn't host video — the video id is a plain JS variable (`var videoUrl = "..."`) directly in the page HTML; delegates to YouTube, preserving the original PrimeGov URL as `source_url` (unlike the Legistar/CivicPlus delegation pattern) | Whatever YouTube provides |
| YouTube | `youtube.py` | No direct video file URL exists (unlike every platform above) — playback is an embedded iframe + the YouTube IFrame Player API, not the native `<video>`/hls.js pathway. Handles a direct `youtube.com`/`youtu.be` URL too, not just PrimeGov delegation | yt-dlp (plain HTTP requests to YouTube's caption endpoints are blocked — see BACKLOG.md); prefers a manual/CC track over auto-generated only when its coverage is comparable, since a manual track can start well into the video and skip pre-meeting dead air |

**Not implemented**: BoardDocs (deliberately excluded — it's a
document/agenda platform with no reliable video, not worth an adapter).

**Caption format handling** is centralized in
`app/utils/vtt_parser.py`'s `parse_captions_by_extension()`, used by
Granicus/CA Legislature/Swagit/CivicClerk (the four adapters that ever
fetch a caption file) instead of each reimplementing its own format
detection. VTT and SRT are real, structurally-parsed formats, confirmed
against real samples on multiple platforms. TTML/DFXP/ITT also get a real
structured parser, but — unlike VTT/SRT — that's verified against the
W3C spec only, not any real captured sample (see `BACKLOG.md`). SBV/SUB/
SMI/SAMI/plain-`.txt` get a generic best-effort text extraction with no
per-line timing (`t=` deep-linking to the video never depended on
transcript timing anyway). SCC/STL (binary/encoded broadcast formats) are
detected but link out rather than attempting to display content, since
nothing can be extracted without real codec-level decoding.

## Frontend features (`app/static/player.js`)

What you can actually do once a meeting page has loaded:

- **Video player**: hls.js for `.m3u8` (Safari falls back to native HLS),
  locked to a 16:9 box so it never collapses to a tiny default size, with a
  large overlay play button and a warm-up trick (muted play-then-pause on
  `loadedmetadata`) that pre-buffers so the user's real first play starts
  instantly. YouTube videos use an embedded iframe + the YouTube IFrame
  Player API instead (no direct video file URL exists for YouTube) —
  transcript click-to-seek, "Copy link to current time", "Go to time",
  and deep-link-on-load all work identically either way, since both are
  wrapped behind the same `{currentTime, play, pause, addEventListener}`
  adapter shape (`createNativeAdapter` / `createYouTubeAdapter`).
- **Agenda**: a dedicated section (`renderAgenda()`), shown above the
  Transcript section whenever agenda/chapter-marker data was found,
  independent of whether a real transcript also exists. Reuses the
  transcript's timestamp/link-icon/text markup for visual consistency and
  click-to-seek + copy-link, but doesn't participate in the transcript's
  "currently playing" highlighting or the `line=` deep-link param — agenda
  items are seek-only via `t=`.
- **Transcript**: click a line to seek + highlight; a chain-link icon per
  line (visible on hover, or ambiently on the current line while paused)
  copies a link to that line without disturbing playback.
- **Search**: mirrors browser Ctrl+F — highlights every match, "N/M" count,
  cycles with prev/next or Enter/Shift+Enter.
- **Manual timestamp entry**: a "Go to time" box in the toolbar (accepts
  `H:MM:SS`, `M:SS`, or plain seconds) — works even with no transcript,
  since deep-linking is the point even when there's nothing to click.
- **Sticky toolbar**: stays reachable at the top of the viewport when
  scrolling, so auto-scroll never strands you away from the controls.
- **Language mismatch handling**: if the best available caption track
  isn't in the target language, it's used anyway but flagged with a
  warning rather than silently presented as if correct.
- **Transcript export**: "Text"/"SRT" download buttons above the
  transcript. Built client-side from the in-memory `segments` array (no
  server round-trip — this page has no persistence to download from); the
  Archive's permanent pages get a real server-side equivalent instead
  (`GET /m/{slug}/transcript.{txt,srt}`, since that data actually persists
  there).
- **Report a problem**: a small form (wrong video, bad transcript, wrong
  metadata, or other) that POSTs to `/api/report-problem`, visible on both
  a successful resolve and a failed one. Same control exists on the
  Archive's permanent pages. Reports land in the resolver's DB, viewable
  via the token-gated `GET /admin/problem-reports`.

## Project structure

A map of the codebase, for orientation — two independent apps
(`app/`, the resolver, and `archive/`, permanent pages), each with its
own routes, database, and frontend.

```
app/
  main.py                 FastAPI app: routes, adapter registration,
                           /api/resolve's cache-check + logging (rate
                           limited via slowapi), /api/report-problem,
                           /admin/*, /robots.txt, and the /m/*,
                           /archive-static/*, /meetings, /sitemap.xml,
                           /feed.xml Archive proxy routes
  archive_client.py        lookup()/push() to the Archive + proxy_get()
  db/
    engine.py              DATABASE_URL (falls back to local SQLite) +
                           async engine/session
    models.py              MeetingResolution (the cache/log table) +
                           ProblemReport (viewer-submitted issue reports)
    crud.py                 get_cached_resolution, log_resolution,
                           get_stats, list_resolutions,
                           log_problem_report, list_problem_reports
    outcomes.py             classify_outcome() — content-quality bucketing
  platforms/
    base.py               detect_platform(), AssetFinder ABC, the
                           adapter registry, CalendarPageError,
                           resolve_via_platform()
    models.py              ResolvedMeeting / TranscriptSegment
    media_scan.py          shared regex-based media-URL scanner
                           (Granicus + Swagit + CA Legislature), including
                           caption-file detection across VTT/SRT/TTML/DFXP/
                           ITT/SCC/STL/SBV/SUB/SMI/SAMI/keyword-gated XML/TXT
    granicus.py, civicclerk.py, swagit.py, escribe.py,
    ca_legislature.py, legistar.py, civicplus.py,
    primegov.py, youtube.py
                           one AssetFinder per platform
  utils/vtt_parser.py      WebVTT/SRT/TTML/DFXP/ITT parsers, a generic
                           best-effort text fallback for other caption
                           formats, and parse_captions_by_extension() --
                           the single dispatch point every caption-
                           fetching adapter goes through (see "Supported
                           platforms"'s "Caption format handling" note)
  utils/url_normalize.py   normalize_url() — the cache/log dedup key
  templates/base.html      shared layout (nav, brand, manifest/favicon link)
  templates/index.html     URL input page
  templates/meeting.html   video + transcript page shell
  templates/about.html     about page
  static/player.js         all client-side behavior
  static/style.css
  static/manifest.json     PWA manifest (Add to Home Screen)
  static/icon.svg          app icon referenced by the manifest + favicon
```

`archive/` is a second, independent FastAPI app (own `requirements.txt`,
own deploy) for permanent pages — see
[Permanent pages (the Archive)](#permanent-pages-the-archive) above.

```
archive/
  main.py                 FastAPI app: /internal/lookup, /internal/ingest
                           (both token-gated), /m/{slug},
                           /m/{slug}/transcript.{txt,srt}, /meetings,
                           /sitemap.xml, /feed.xml, /api/health
  db/
    engine.py              own DATABASE_URL resolution + local SQLite
                           fallback (archive_dev.db -- never shares the
                           resolver's dev.db)
    models.py               MeetingPage, TranscriptVersion,
                           MeetingPageUrlAlias
    crud.py                  identity matching/dedup, slug generation,
                           content-hash version dedup, list_pages()
                           (paginated + filtered, backs /meetings),
                           list_all_page_slugs() (backs /sitemap.xml),
                           list_recent_pages_for_feed() (backs /feed.xml)
  utils/
    slugify.py               slug generation
    search.py                 keyword matching for list_pages() -- exact
                           (substring) and fuzzy (bounded edit-distance
                           per word) search, see "Search" above
    transcript_export.py     to_txt()/to_srt() formatters, backs
                           /m/{slug}/transcript.{txt,srt}
    url_normalize.py         deliberate duplicate of
                           app/utils/url_normalize.py -- kept in sync
                           manually so the two services stay
                           deploy-independent
  templates/
    meeting_page.html        SSR permanent page + transcript-version
                           picker (real content on first byte, for
                           crawlability -- not client-fetched JSON like
                           app/templates/meeting.html); also carries the
                           schema.org VideoObject JSON-LD block and the
                           "Report a problem" form
    meeting_list.html         paginated index + search/filter form, plus
                           an RSS autodiscovery link
    sitemap.xml.jinja         sitemap.xml template
    feed.xml.jinja            feed.xml (RSS) template
  static/style.css          duplicated from app/static/style.css
  static/meeting_page.js    trimmed port of player.js's seek/highlight
                           logic, wired onto already-rendered DOM
```

## Known limitations

Nothing here is finished — this is a fast-moving project with real,
tracked gaps rather than silently-assumed correctness. See `BACKLOG.md`
for the full, up-to-date list of open issues (completed
fixes and their verification history have moved to `BACKLOG_DONE.md`,
linked from there) — a few caption paths are shape-verified but not
content-verified pending a real example, some metadata (Alexandria VA
dates) can't be extracted at all, and there's no UI yet to pick between
multiple caption language tracks when more than one exists.
