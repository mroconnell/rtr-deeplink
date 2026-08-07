# rtr-deeplink

Paste the URL of a public government meeting recording. Get back the video
and its transcript, side by side, with every line clickable — and a URL you
can share that lands someone at that exact moment.

No accounts, no background jobs. Given a meeting URL, the app resolves its
video and transcript on demand and renders them. Deep-linking to an exact
moment is the primary goal; the transcript is a nice-to-have on top of that.

There's an optional database (see [Caching and reporting](#caching-and-reporting)
below) that caches resolved meetings and logs every resolve attempt for
admin reporting — but it's not required to run the app. With no `DATABASE_URL`
set, the app falls back to a local SQLite file, and if the database is ever
unreachable, `/api/resolve` degrades silently to its original zero-persistence
behavior rather than failing.

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

## How it works

### The resolve flow

1. The frontend (`app/static/player.js`) POSTs the pasted URL to
   `/api/resolve`.
2. `app/platforms/base.py`'s `detect_platform(url)` looks at the URL's
   domain (and sometimes path) and classifies it as one of the platforms
   below.
3. The matching `AssetFinder` (one class per platform, all in
   `app/platforms/`) fetches whatever it needs — usually the meeting page's
   HTML, sometimes a small REST API — and returns a `ResolvedMeeting`:
   title, date, jurisdiction, a playable video URL, and transcript
   segments (`{start, end, text}`) if any were found.
4. `/meeting?url=<source>` (served by `app/templates/meeting.html` +
   `player.js`) calls `/api/resolve` client-side and renders the result:
   video player (hls.js for `.m3u8`, native `<video>` otherwise) above a
   clickable transcript.

The rendered page itself is never cached — every page load re-resolves from
the source URL. What *can* be cached is the resolve result: if a database is
configured, `/api/resolve` checks it first (keyed on a normalized version of
the URL) and serves a prior successful resolve instead of re-fetching from
the government source. Reloading a deep link re-runs the resolve either way
(live or cached) and lands you back at the same moment.

### Three response shapes from `/api/resolve`

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

  A chapter-marker fallback produces non-empty `segments` just like a real
  transcript does, so it's classified from the shared fallback warning text
  (`_AGENDA_FALLBACK_MARKER` in `outcomes.py`) checked *before* the
  found/not-found check — otherwise it would silently count as `success`.

Two admin endpoints, both gated by `ADMIN_STATS_TOKEN` (`?token=...`,
returns 404 rather than 401/403 on a missing/wrong token so the route isn't
distinguishable from a typo):
- `GET /admin/stats` — aggregates: totals, success rate, cache hits, average
  resolve duration, counts by platform × outcome, recent non-success rows.
- `GET /admin/log?limit=&format=json|csv` — the unaggregated per-attempt
  list (URL, platform, outcome, language, timestamp), most recent first.

See `.env.example` for the two env vars (`DATABASE_URL`, `ADMIN_STATS_TOKEN`).

## Supported platforms

One `AssetFinder` per **platform**, not per city — cities on the same
platform share the same page/API structure. Detection lives in
`detect_platform()`; adapters are registered in `app/main.py`.

| Platform | File | How video is found | How captions are found |
|---|---|---|---|
| Granicus | `granicus.py` | Regex-scan the page HTML for `.m3u8`/`.mp4` URLs (shared `media_scan.py` helper) | Guessed `/videos/{id}/captions.vtt` path + scanned `.vtt` URLs; language verified from actual cue content (not the untrustworthy `srclang` label); RSS channel title (`ViewPublisherRSS.php`) used for reliable jurisdiction/title. When there's no usable transcript, falls back to `AgendaViewer.php`'s agenda-item chapter markers when that customer has Granicus's native agenda index turned on (not universal — some customers redirect it to their own site instead) |
| CivicClerk | `civicclerk.py` | Public REST API (`<subdomain>.api.civicclerk.com`) — the portal page itself is a client-rendered SPA with nothing to scrape | API's caption fields when populated; falls back to the API's `eventBookmarks` (agenda-item timestamps) as clickable chapters when there's no real transcript |
| Swagit | `swagit.py` | jwplayer JSON blob embedded in the page (shares Granicus's CDN infra, but a different page shape) | `.playerControl[data-ts]` agenda-item markers, same chapter-fallback role as CivicClerk's bookmarks |
| eScribe | `escribe.py` | `<div id="isi_player" data-client_id data-stream_name>` when present — video integration varies entirely by city, "no video" is a normal outcome here | iSiLIVE captions, keyed by language suffix in the filename (`{file}.vtt`, `{file}.fr.vtt`, ...) |
| California Legislature | `ca_legislature.py` | Self-hosted (`stream.{assembly,senate}.ca.gov`), not a vendor platform | Self-hosted `.vtt` at a matching filename; genuinely high quality when present |
| Legistar | `legistar.py` | Doesn't host video — finds the embedded/redirected link to a platform above (usually Granicus) and delegates via `resolve_via_platform()` | Whatever the delegated platform provides |
| CivicPlus | `civicplus.py` | Same delegation pattern as Legistar, from AgendaCenter listing rows | Whatever the delegated platform provides |

**Not implemented**: PrimeGov (detected but no adapter — hits
`unsupported_platform`), BoardDocs (deliberately excluded — it's a
document/agenda platform with no reliable video, not worth an adapter).

## Frontend features (`app/static/player.js`)

- **Video player**: hls.js for `.m3u8` (Safari falls back to native HLS),
  locked to a 16:9 box so it never collapses to a tiny default size, with a
  large overlay play button and a warm-up trick (muted play-then-pause on
  `loadedmetadata`) that pre-buffers so the user's real first play starts
  instantly.
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

## Project structure

```
app/
  main.py                 FastAPI app: routes, adapter registration,
                           /api/resolve's cache-check + logging, /admin/*
  db/
    engine.py              DATABASE_URL (falls back to local SQLite) +
                           async engine/session
    models.py              MeetingResolution (the cache/log table)
    crud.py                 get_cached_resolution, log_resolution,
                           get_stats, list_resolutions
    outcomes.py             classify_outcome() — content-quality bucketing
  platforms/
    base.py               detect_platform(), AssetFinder ABC, the
                           adapter registry, CalendarPageError,
                           resolve_via_platform()
    models.py              ResolvedMeeting / TranscriptSegment
    media_scan.py          shared regex-based media-URL scanner
                           (Granicus + Swagit)
    granicus.py, civicclerk.py, swagit.py, escribe.py,
    ca_legislature.py, legistar.py, civicplus.py
                           one AssetFinder per platform
  utils/vtt_parser.py      pure WebVTT parser
  utils/url_normalize.py   normalize_url() — the cache/log dedup key
  templates/base.html      shared layout (nav, brand)
  templates/index.html     URL input page
  templates/meeting.html   video + transcript page shell
  templates/about.html     about page
  static/player.js         all client-side behavior
  static/style.css
```

## Known limitations

See `BACKLOG.md` for the full, up-to-date list — caption quality varies a
lot by source and isn't detected, a few caption paths are shape-verified
but not content-verified pending a real example, and PrimeGov has no
adapter yet.
