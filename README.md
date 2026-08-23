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

## Vision

Red Tape Recordings builds power tools for the advocates, grassroots
organizers, and everyday citizens doing the real digging into local
government — people who need to skip straight to the moment, transcript
line, or agenda item that matters, and search across hundreds of
jurisdictions and meetings at once for a topic they're tracking, rather
than sitting through hours of video. Journalists are a good example user
of this (real distribution/credibility value) but a smaller group than the
grassroots/advocacy base this is actually built for — not the product's
core definition. `rtr-deeplink` is the tool that saves that time.

**Lean, fast, and useful is the standing bar, not a phase we graduated out
of.** Accounts, permanent pages, and site-wide search were all once "nice
to have," and they're real now — but the core function (resolve a meeting,
share a deep link) still works with no account and no signup, in the
lightest format that does the job.

**Who it's for, and how this is meant to eventually pay for itself.**
Advocates, grassroots organizers, and everyday citizens are the intended
core users, outnumbering local journalists by a wide margin even though a
journalist is a great example case. Two real usage modes are expected once
there's a regular user base: someone lightly following a meeting or two a
month for one city council or planning commission, and someone tracking
meaningfully more than that. The free tier is meant to comfortably cover
the light case; a paid individual tier removes the ceiling for a heavy
user, and a separate institutional/B2B tier is the intended answer for an
organization tracking a specific topic across many jurisdictions at once
(e.g. a company's PR team following a specific kind of siting decision
across city councils) — a different usage shape from an individual power
user. None of this is priced or built yet — see `BACKLOG.md`'s "Accounts +
token billing" section for the fuller, still-directional thinking.

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

Both this suite and the JS suite below also run in CI on every push/PR
(`.github/workflows/test.yml`, added 2026-08-14), pinned to Python 3.12.3
to match `render.yaml`.

`tests/` covers the platform-independent utilities (`app/utils/vtt_parser.py`,
`app/platforms/media_scan.py`, `app/platforms/base.py`'s `detect_platform`)
directly, and exercises every adapter in the "Supported platforms" table
below end-to-end against real fixture files saved under `tests/fixtures/`
(fetched live from real government sites, not synthetic
— see each fixture directory for where it came from; `tests/fixtures/
civicplus/README.md` explains the one exception, hand-built to match a
real site's confirmed structure since that live site has since changed).
HTTP calls are mocked via a small in-repo `tests/aiohttp_mock.py`, not
`aioresponses` — its latest release doesn't support the aiohttp version
this project's unpinned `aiohttp>=3.9` resolves to today. Also covers
`archive/utils/search.py`'s exact/fuzzy matching logic directly (pure
functions, no DB or mocking needed — `tests/test_archive_search.py`) and
`worker/segment_utils.py` + `app/platforms/media_probe.py`'s duration-
plausibility check the same way (`tests/test_worker_segment_utils.py`,
`tests/test_media_probe.py`) — that first file also carries the
hallucination detector's coverage, backed by real Archive transcript
excerpts under `tests/fixtures/hallucination_runs/` (see its own
`README.md`): six real hallucination loops that must be flagged, and real
decoder stutters and roll calls that must not be.
`tests/test_highlights.py` covers the featured-snippet heuristic
(`archive/utils/highlights.py`), the curated topic list, and the
government-type classifier the same pure-function way. Its snippet cases
are **frozen strings the heuristic actually produced against the live
archive** on 2026-08-23 — both the good ones and the two garbled ones
that reached a rendered page during in-browser verification and are why
the coherence guards exist. Tuning the scoring without re-running those
is how a fix for one meeting silently ruins twenty.
`tests/test_transcription_failure_analysis.py` is the same pure-function
shape and is deliberately kept that way: it exercises
`crud.summarize_failure_rows()` (the chunk-failure diagnostic behind
`/internal/transcription-failure-analysis`) against constructed rows
rather than the shared test database, which several other modules write
real failures into — any whole-table assertion there would be
order-dependent. `tests/test_transcription_jobs.py` is a
different shape — real integration tests against an isolated SQLite file
(set up once per test session by `tests/conftest.py`, not mocked), since
the transcription job lifecycle is genuinely DB-state-machine logic
(claim/report/finalize/promote) that a pure-function test can't exercise
honestly. Every adapter now has real fixture-backed test coverage.
`tests/test_youtube_channel.py` is a fourth shape again — it runs the
Legistar→YouTube-channel matcher (WO-30) against real, live-captured
channel listings saved as JSON under `tests/fixtures/youtube_channel/`,
because that matcher's whole risk is picking the *wrong* real meeting,
which only real titles can exercise; two of its cases have
independently-known right answers (BACKLOG.md's recorded Phoenix pairing,
and a Baltimore meeting where the city itself attached the video).
`tests/test_retry_async.py` covers `app/utils/retry.py`, the one shared
backoff policy `scripts/transcribe_backlog_locally.py` and
`worker/main.py` both use around their live-source calls — a
counting fake rather than a real site, because "fails once, then succeeds
unchanged" is exactly the behavior under test and no real government
source can be asked to do that on cue.

The suite is deliberately network-free, which leaves one thing it can't
catch: a government site quietly changing structure under a working
adapter. That's what `scripts/adapter_canary.py` is for — it re-resolves
one real, known-good meeting URL per platform against the live site
(in-process, so no production cache/Archive noise) and exits non-zero if
any comes back empty or broken. `.github/workflows/adapter-canary.yml`
runs it daily at 15:00 UTC. Adding a new platform adapter therefore means
adding a live-verified URL to that script's `CANARY_URLS` — or an entry to
its `CANARY_EXCLUSIONS` saying why no such URL exists;
`tests/test_adapter_canary.py` fails the build if a registered platform
has neither.

```bash
python scripts/adapter_canary.py   # real network calls, ~1 min
```

Adding a platform adapter has a **second** registry obligation of the
same shape (WO-35, 2026-08-21): every platform `register_all_finders()`
registers must also appear in `archive/db/crud.py`'s `DIRECT_PLATFORMS`,
`CUSTOM_PLATFORMS`, or `COVERAGE_EXCLUSIONS` — otherwise its rows fall
through `get_platform_coverage()`'s `if`/`elif` chain with no matching
branch and vanish from `/coverage` silently, with no error at all.
`tests/test_coverage_platform_registry.py` fails the build if one has no
decision, and (like `CANARY_EXCLUSIONS`) requires every exclusion to
state its reason. Four adapters shipped without this between 2026-08-19
and 2026-08-21 — see BACKLOG_DONE.md.

`shared_static/deep_link.js` (the `t`/`line`/`version` deep-link contract
both `app/static/player.js` and `archive/static/meeting_page.js` depend
on) has its own separate JS suite, since it's the one piece of this repo
with no Python equivalent:

```bash
npm install
npm test
```

`tests_js/helpers.js` loads the real file into a fresh `jsdom` window as
an actual `<script>` element per test (not `vm.runInContext` or `eval`) so
top-level `let`/`function` declarations land in real global script scope
— the same behavior two separate classic `<script>` tags share in an
actual browser, which matters here since `player.js`/`meeting_page.js`
both assign into `deep_link.js`'s module-level `segments` variable this
same way in production.

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

## Database architecture, in plain English

Skip this if you're already comfortable with SQLAlchemy/Alembic — it's
here because it's easy to lose track of which database is which, and what
actually happens when a new table or column shows up, once there are two
separate apps each with their own database plus a migration tool layered
on top of one of them.

**There are two separate databases, one per app, and they don't talk to
each other directly:**

- **`app/db/`** — the resolver's own database. Two tables:
  `meeting_resolutions` (a log of every URL anyone's ever tried to
  resolve, success or failure — powers the cache and the `/admin/stats`
  reporting) and `problem_reports` (the "something's wrong with this
  meeting" form submissions). See "Caching and reporting" below.
- **`archive/db/`** — the Archive's own database, holding the actual
  permanent-page content. Four tables: `meeting_pages` (one row per
  permanent `/m/{slug}` page), `transcript_versions` (a page can have
  several — original scrape, a self-transcribed replacement, etc.),
  `transcription_jobs` (the on-demand-transcription queue, see below),
  and `meeting_page_url_aliases` (every URL that's ever successfully
  matched to a page, so a repeat paste of a Legistar link finds the same
  page even though its real identity lives on Granicus). See "Permanent
  pages" below.
- **`worker/`** (the background transcription service) doesn't have its
  own database at all — it reaches directly into the Archive's database
  using the same models as `archive/db/`, since it's really just Archive
  logic that needs a long-running process instead of a web request.

**How a table used to get created: `create_all()` — no longer true in
production.** Every app startup calls `Base.metadata.create_all()`
(`app/db/engine.py`'s and `archive/db/engine.py`'s `init_models()`), which
looks at every model class defined in `models.py` and runs `CREATE TABLE
IF NOT EXISTS` for each one. That made adding a brand-new table
zero-friction: write the class, deploy, and the table just appeared in
production on the next restart. `ProblemReport` and `TranscriptionJob`
both shipped that way. **Both services' `init_models()` now return early
on Postgres** (archive 2026-08-17, resolver 2026-08-21) — `create_all()`
runs only on the local/test SQLite path, and Alembic is the sole writer
to the production schema. The convenience was exactly what let
`alembic_version` drift silently behind reality; see the incident below
and `CLAUDE.md`'s migration bullet.

**Where `create_all()` stopped working even before that: changing a
table that already has real rows in it.** It only ever adds tables it
doesn't see yet — it has
no idea how to add a column to a table that already exists, so if you add
a field to an existing model and just redeploy, nothing happens to
production at all; the app will start throwing "column does not exist"
errors the moment it tries to use that field. This actually happened
twice in this project's life (a materialized search column, then a
`priority` column on `transcription_jobs`) before Alembic was adopted for
exactly this reason.

**What Alembic actually does, without the jargon:**
- A **migration** is a small Python file that says how to change the
  schema one step at a time — "add this column," "rename that table" —
  each with matching instructions to undo itself. They're generated
  automatically (`alembic revision --autogenerate`) by diffing the real
  models against whatever the database currently looks like, though
  autogenerate is a first draft, not gospel — always read the file before
  committing it.
- Migrations chain together in a straight line, oldest to newest, like a
  numbered list. The most recent one is called **`head`**.
- The database keeps exactly one row, in a table Alembic manages itself
  (`alembic_version`), recording which migration it's currently at. That
  one row is Alembic's *entire* memory of what's already been applied —
  it never inspects the actual table structure to guess.
- **`alembic upgrade head`** is the "do the work" command: it looks at
  that one row, then actually runs every migration between there and the
  latest one — real `ALTER TABLE` statements against the real database.
- **`alembic stamp <revision>`** is the "just update the bookkeeping"
  command: it overwrites that one row directly and runs *no* SQL at all.
  This only exists for bootstrapping — telling Alembic "trust me, this
  database already matches this point in the history" for a database that
  had tables before Alembic was ever introduced (which was every table in
  this project, since they all started life via `create_all()`).

**The real incident this caused (2026-08-09), as a concrete example:**
production had four tables, all created by `create_all()`, with real rows
in them, and had never been stamped at all. The plan was `alembic stamp
head` as a one-time step to say "you're already caught up, nothing to
run." That was true for about twenty minutes — right up until a second
migration (the `priority` column) was added to the history afterward.
"`head`" isn't a fixed point, it's *whichever migration is newest right
now* — so running `stamp head` after that second migration existed
incorrectly told production "you already have the priority column" when
it didn't, and the deployed app immediately started failing every query
with `column transcription_jobs.priority does not exist`. The fix was to
stamp the *specific* baseline revision id instead of the word `head`
(`alembic stamp a8dc5aad7eff`), then actually run the real migration on
top of that (`alembic upgrade head`) — see `archive/alembic/README.md`
for the exact recovery sequence, and `BACKLOG_DONE.md` for how this was
confirmed fixed.

One more practical note: each service that has real rows to protect keeps
its **own** Alembic config, not a single shared one — `archive/`
(`archive/alembic.ini`, `archive/alembic/`) for `archive/db`, and `app/`
(`app/alembic.ini`, `app/alembic/`, added 2026-08-10 after `app/db` hit
this exact same wall for the first time — see `BACKLOG_DONE.md`) for the
resolver's own `app/db`. Every `alembic` command has to be run from
inside the matching directory (`cd archive` or `cd app`) — running it
from the repo root fails with `No 'script_location' key found in
configuration`, and running it from the wrong service's directory would
point at the wrong models/database entirely.

**Backups and recovery (WO-4, `AUDIT_EXECUTION_BRIEF.md`, confirmed live
2026-08-17).** All persistent state (both `app/db` and `archive/db`) lives
in one Render Postgres instance, `rtr-deeplink-db` (Basic-256mb, Oregon).
Render takes continuous backups automatically on paid instances — nothing
to configure — but two things about how that actually works matter more
than "backups exist":

- **The recovery window is 3 days, not a generic "we have backups."** This
  workspace is on Render's Hobby tier, and PITR (point-in-time recovery)
  retention follows the *workspace* tier, not the database's own plan —
  confirmed live via Render's dashboard, not assumed from their docs.
  Upgrading the database's own plan later would **not** extend this; only
  upgrading the whole workspace to a paid Team/Pro tier would (7 days).
  Concretely: a bad migration that lands on a Friday and isn't noticed
  until the following Wednesday is already past the window by the time
  anyone looks.
- **Restoring is a swap, not a rewind.** Render's PITR spins up a brand
  new database instance at the chosen point in time — it does not roll
  the existing `rtr-deeplink-db` back in place. Recovering for real means:
  1. In Render's dashboard, open `rtr-deeplink-db` → **Recovery** → pick a
     timestamp within the last 3 days → this creates a **new** Postgres
     instance (a new name, a new internal hostname).
  2. Copy the new instance's connection string.
  3. Update `DATABASE_URL` on all three services that use it
     (`rtr-deeplink`, `rtr-deeplink-archive`, `rtr-transcription-worker`)
     to point at the new instance, and redeploy each.
  4. If `EXPECTED_DB_HOST` is set on `rtr-deeplink-archive`/
     `rtr-transcription-worker` (`archive/db/engine.py`'s
     `_assert_expected_db_host()`, WO-4), update it too, or the two
     services will refuse to start against the recovered database — this
     is the check working as intended (a hostname that doesn't match is
     exactly the signal a manual recovery step got missed), not a bug to
     work around.
  5. Once confirmed working, update the old `rtr-deeplink-db` Render
     Blueprint entry (`render.yaml`'s `databases:` block) to the new
     instance's name so a future Blueprint sync doesn't try to reconcile
     against the now-abandoned original.

**Not yet done: an actual test restore.** This procedure is written from
Render's documented PITR behavior, cross-checked against this workspace's
real dashboard (tier, retention window, instance details) — but nobody
has actually clicked through a real recovery yet. An unexercised restore
procedure is a hypothesis, not a backup plan; doing one throwaway PITR
restore to a scratch instance (never repointing any real service at it)
to confirm these steps are accurate is a real, still-open follow-up, not
a formality — see `BACKLOG.md`.

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
- `GET /admin/sweep-pending-pushes` — on-demand version of the durable
  Archive-push retry mechanism (below), for checking on or forcing it
  directly. Returns exactly which resolutions it found and retried.
- `GET /admin/schema-info` — read-only introspection of this service's
  real live schema: the *actual* reflected columns on every table (via
  SQLAlchemy's `Inspector` against a real connection) next to what
  `app/db/models.py` expects, with `mismatched_tables` /
  `schema_matches_models` calling out any difference, plus whatever
  `alembic_version` currently says as context rather than as truth. The
  resolver's port of the Archive's `/internal/schema-info` (described
  under "Permanent pages" below), added 2026-08-21 so confirming
  production's real schema — specifically whether `meeting_resolutions`
  has `jurisdiction_confidence`, and what the resolver's untouched
  `alembic_version` actually holds — doesn't need Render shell access.
  See `app/alembic/README.md`'s runbook for how to read it. Note
  `actual_columns` reflects the whole database, which the Archive
  shares, so its tables appear here too; they aren't counted as
  mismatches since `app/db/models.py` says nothing about them.

**Durable Archive pushes**: a successful resolve's push to the Archive is
fired via `BackgroundTasks`, so a resolver process restart (a deploy, a
crash) between the response returning and the task actually running could
previously lose the push silently — no exception, no log line, since the
process that would have logged it is the one that got killed (real
incident, see `BACKLOG_DONE.md`'s 2026-08-10 entry). `MeetingResolution`
now tracks `archive_pushed_at`/`archive_push_attempts`, and an
opportunistic sweep (fired from `/api/resolve` itself, at most once every
few minutes — this app has no background job queue by design, so this
isn't a real scheduler, just the same pattern `ARCHIVE_RECHECK_AFTER`'s
stale-page recheck already uses) retries any row with real content that's
stayed unpushed past a grace period. `/admin/stats`' `pending_archive_pushes`
count and the `/admin/sweep-pending-pushes` endpoint above give direct
visibility into this instead of relying on someone happening to notice a
meeting missing from `/meetings`.

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

**YouTube transcripts — fetched locally, not server-side**: YouTube
blocks caption requests from cloud-provider IPs (confirmed live
2026-08-10: yt-dlp, plain timedtext requests, and `youtube-transcript-api`
all fail from Render's IP while the same calls work from a residential
connection — see `BACKLOG_DONE.md`'s experiment entry). So YouTube-backed
pages get their transcripts through a two-part loop instead:
`GET /internal/transcript-wanted` (token-gated like every `/internal/*`
route) lists every YouTube-backed page with no default transcript, and
`scripts/fetch_youtube_transcripts.py` — run locally, from a residential
connection, same `.env` setup as `scripts/bulk_ingest.py` plus
`pip install -r requirements-dev.txt` — drains that queue via
`youtube-transcript-api` and pushes results back through the normal
`POST /internal/ingest` (idempotent, content-hash-deduped, matched to
the existing page). Supports `--dry-run` and `--limit`; aborts the whole
run on an IP-level block rather than failing every queue entry
identically. Prints per-item timing (wall-clock timestamp + elapsed
seconds) and a final total/average — fetching an already-generated
caption track is one API call, so run time is independent of how long
the actual meeting is.

Runs automatically once a day via `launchd` on the user's own Mac (must
be that machine specifically — the residential IP is the whole point).
`scripts/com.redtaperecordings.fetch-youtube-transcripts.plist` has the
real install/test/uninstall commands in its own header comment; installed
copy lives at `~/Library/LaunchAgents/`, logs at `~/Library/Logs/
fetch-youtube-transcripts.log`.

Every real (non-dry-run) run emails a report to `YOUTUBE_FETCH_REPORT_EMAIL`
(default `ryan@how-to-adu.com`) via the Archive's existing Resend
integration (`archive/utils/email.py`, same `RESEND_API_KEY`/
`RESEND_FROM_ADDRESS` the Archive service already uses) — every transcript
actually added, with a real clickable link, even an empty report, so
silence itself is a signal the job stopped firing. A run that fails to
complete at all (an IP-level block, or any unhandled exception) sends a
different, explicitly-flagged failure email instead.

**Checking the Archive's real production schema**: `GET /internal/schema-info`
(token-gated the same way as every other `/internal/*` route — a bearer
token matching `ARCHIVE_INGEST_TOKEN`, 404 rather than 401/403 on a
missing/wrong token) reflects the *actual* live columns on every table via
SQLAlchemy's `Inspector` against a real connection, next to what
`archive/db/models.py`'s `Base.metadata` currently expects, and reports
any mismatch directly (`mismatched_tables`, `schema_matches_models`) —
plus whatever `alembic_version` currently says, as context only, not as
the source of truth. Exists specifically so confirming production's real
schema state doesn't require someone with `DATABASE_URL` access to run
`psql`/`alembic` commands by hand and paste the output back — added
2026-08-10 after a stale doc's account of "production has never been
stamped" turned out to be wrong and caused a real (contained) Alembic
mistake; see `archive/alembic/README.md` and `BACKLOG_DONE.md` for that
incident. Note this hits the Archive service's own base URL directly
(the same one `ARCHIVE_BASE_URL` points at) — `/internal/*` is
deliberately not one of the paths `redtaperecordings.com` proxies
through (only `/m/*` and `/archive-static/*` are, see "Domain" above),
so it isn't reachable at the public custom domain. Example:

```bash
curl -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" "$ARCHIVE_BASE_URL/internal/schema-info"
```

**Auditing what the pipeline published unverified**: `GET
/internal/low-trust-pages` (token-gated the same way, and reachable only
at the Archive service's own base URL for the same reason as above)
lists every archived page whose provenance was never actually confirmed
— `platform == "unknown"` (the name `generic_fallback.py` registers
under), `best_effort` (the resolver's own flag for that path, which also
covers the fallback results that delegate to YouTube and therefore
report `platform = "youtube"`), or a `jurisdiction_confidence` of
`unverified`/`blank`. Each row carries a `reasons` list saying which of
the three caught it, plus slug, title, platform, jurisdiction, source
URL, creation date and `reviewed_at`; `?limit=`/`?offset=` paginate and
`total` is the full match count. Exists because the resolve → Archive →
public page → social announcement path is fully automatic end to end,
with nothing that could otherwise answer "what has this published that
nobody looked at?" It's read-only and changes nothing: these pages stay
live, indexed, and in the sitemap by design (see `BACKLOG.md`) — the
`best_effort` flag's one enforcement effect is that social auto-posting
refuses to announce them.

**What's actually in the queue, measured** (first-ever production call,
2026-08-21): 474 rows — 470 `unverified_jurisdiction`, 7
`unknown_platform` (3 overlapping), and **zero** `best_effort`. So in
practice this reads as a *data-quality* queue — meetings whose
jurisdiction couldn't be determined, on real live pages with real video
— and as a trust/spoofing queue only prospectively. `best_effort` can't
be backfilled onto rows archived before its column existed, so it only
starts appearing on pages ingested from 2026-08-21 onward.

Two filters make that volume workable (added 2026-08-21, WO-38); both
are optional and an unfiltered call returns exactly what it always did:

- `?unreviewed=true` — only rows nobody has marked reviewed yet
  (`reviewed_at IS NULL`).
- `?reason=unknown_platform|best_effort|unverified_jurisdiction` — one
  reason at a time, which matters given the skew above: the 4 rows that
  aren't `unverified_jurisdiction` are otherwise invisible in practice.
  An unrecognised value is a 400, not a silently-unfiltered result.

**Marking pages reviewed**: `POST
/internal/low-trust-pages/mark-reviewed?ids=1,2,3` (same token gate)
stamps `meeting_pages.reviewed_at` on exactly the ids given and nothing
else — it does not hide, de-index, edit or delete anything, and the
public page is served exactly as before. `ids` is required and there is
deliberately no "mark everything" mode. Idempotent: an id already in the
requested state comes back under `already_reviewed` with its original
timestamp untouched, and an unknown id under `missing_ids` rather than
failing the batch. `?dry_run=true` is the default (returns the exact
diff it *would* write); `?unreview=true` clears the stamp back to NULL,
the undo for a mis-pasted id list.

```bash
# newest unreviewed rows
curl -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" \
  "$ARCHIVE_BASE_URL/internal/low-trust-pages?limit=50&unreviewed=true"

# the handful flagged for something other than a missing jurisdiction
curl -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" \
  "$ARCHIVE_BASE_URL/internal/low-trust-pages?reason=unknown_platform"

# mark three of them reviewed (drop dry_run=false to preview first)
curl -X POST -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" \
  "$ARCHIVE_BASE_URL/internal/low-trust-pages/mark-reviewed?ids=2215,2201,2200&dry_run=false"
```

**Diagnosing transcription chunk failures**: `GET
/internal/transcription-failure-analysis?days=N` (token-gated the same
way, reachable only at the Archive service's own base URL) groups every
recorded chunk failure by media host, page host, platform, and
position-within-job. It needs no new instrumentation —
`TranscriptionJob.failure_history` has stored a real per-attempt
`{chunk_index, error, at}` since 2026-08-19 — so this is a query over
data that already exists.

Two things about how to read it, both load-bearing:

- **Read `failure_rate_by_chunk_index` / `failure_rate_by_decile`, not
  the raw `failure_position` counts.** A job has exactly one chunk 0 but
  many later chunks, so raw counts always make later chunks look
  dominant. Normalized per attempt, the shape is diagnostic: rising with
  chunk index means an accumulating rate limit, a spike at chunk 0 means
  cold storage/rehydration, flat-and-high throughout means a source
  that's simply slow against the fixed 120s ffmpeg timeout.
- **Grouping is keyed on the media URL's host, not the page's.** Granicus
  serves ~300 distinct `{tenant}.granicus.com` page hosts off a handful
  of shared `archive-video`/`archive-stream`/`archive-media.granicus.com`
  media hosts — the throttling party would be the CDN, not the tenant.
  Both groupings are returned so the difference stays visible.

`concurrency_pairs_within_10min` directly tests whether workers are
contending for one host across different jobs. Measured across all 514
production jobs on 2026-08-21 that bucket was **0**, which is what ruled
out reordering the queue by host — see `BACKLOG_DONE.md`'s WO-40 entry.

```bash
curl -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" "$ARCHIVE_BASE_URL/internal/transcription-failure-analysis"
```

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
shareable/bookmarkable URLs with no JS required. Empty pages (no video,
no agenda, no transcript) are excluded from the default browse, the
sitemap and the feed at query time — not deleted, and still shown under
an explicit `has_transcript=false` filter (that's how gaps get found) —
and rows/pages carry an "Upcoming"/"Recent" pill when the meeting
hasn't happened yet or happened within the last 30 days without a
transcript (`archive/utils/date_status.py`; see `BACKLOG_DONE.md`'s
2026-08-17 entry). `GET /sitemap.xml` and
`GET /robots.txt` (the latter lives on the resolver, not proxied, since
`robots.txt` has to be at the domain root) give search engines an actual
crawl path to `/m/{slug}` pages, which previously had none —
`robots.txt` also disallows `/meeting` (the ephemeral resolver page) so
it doesn't compete with the permanent version of the same content once
one exists.

**`GET /coverage`** (proxied like `/meetings`, replacing a 2026-08-10
placeholder) is a public, per-platform table — one row per real,
distinct meeting platform (`archive/db/crud.py`'s
`get_platform_coverage()` + `DIRECT_PLATFORMS`/`CUSTOM_PLATFORMS`; the
line those two dicts draw is "one product many jurisdictions buy" vs. "a
bespoke scraper this app wrote for one government", *not* "hosts video"
vs. "doesn't" — Hyland, Destiny AgendaQuick and open.media are all
agenda/CMS front-ends with their own row), each linking to a real
`/m/{slug}` permanent page as proof when one exists, with the same
rubber-stamp "Transcript" badge `/meetings` uses. Deliberately excludes
calendar-tool detection routers that only ever delegate (Legistar,
CivicPlus, PrimeGov, CivicWeb) — on a real successful resolve their own
`ResolvedMeeting.platform` is always the *delegated* platform's, never
their own (see the "Supported platforms" table above), so a row for one
of them could never have a real example; a one-line note on the page
covers them instead of a permanently-empty row. Every platform is listed
even with zero live examples yet ("Supported, but no example archived
yet") rather than silently omitted, per this file's "don't claim a data
path works without a positive example" convention — the thing being
shown here is "does a real page exist," not "is this code path
exercised," which are different claims.

`/coverage` also has a per-government-body table ("Every place we've
covered", `crud.get_jurisdiction_coverage()`) below the per-platform one,
sorted alphabetically for Ctrl+F discoverability ("only software
engineers think platform first"), and — added 2026-08-17 — a fuller
**"Full jurisdiction detail table"** (`crud.get_full_jurisdiction_coverage()`),
one sortable/filterable row per successfully-archived jurisdiction with:
video-embeds / agenda-embedded / instant-transcript-from-source /
transcript-from-audio-possible (yes/no each — the last is derived from
`video_format not in _IFRAME_EMBED_VIDEO_FORMATS`
(`youtube`/`vimeo`/`viebit`), mirroring `app/main.py`'s own
`_unreadable_media_message()` reasoning that an iframe-embed page is
structurally unprobeable by ffprobe, not a live check; every other
stored `video_format` — mp4/m3u8/mp3/wav — is a genuine fetchable media
URL), a two-column
"Detail page" vs. "Video" provider split (recovers PrimeGov/CivicWeb/
LIMS/SLC/ClerkBase/open.media's real identity from `source_url_normalized` even
though `MeetingPage.platform` says "youtube" for all of them — see this
file's "when a platform turns out to be a wrapper around another" note in
CLAUDE.md for the Legistar/CivicPlus case this *can't* recover, since
their delegation overwrites `source_url` with the delegated platform's
own URL), an outcome bucket (mirrors `app/db/outcomes.py`'s
`classify_outcome()`), and a last-verified date. Sorting reuses
`archive/static/coverage.js`'s existing client-side pattern (now
generalized to any `table.sortable-table`); filtering is plain
client-side JS (dropdowns + a jurisdiction search box + yes/no checkbox
filters) — the whole roster is ~870 rows in production as of 2026-08-17,
small enough to render server-side in one page load and filter/sort
entirely in the browser, same reasoning the sort code already relied on.

**`GET /state/{slug}` (per-state landing pages, added 2026-08-17)** —
server-rendered, indexable SEO pages ("California public meeting videos &
transcripts", `/state/california`), proxied like `/coverage`. Each lists
that state's covered governments (same table shape as `/coverage`'s
"Every place we've covered", grouped from the stored jurisdiction's
canonical `", ST"` suffix via
`archive/utils/jurisdiction_format.py`'s `state_abbr_from_jurisdiction()`)
plus **featured transcript snippets** (see below), with a self-referential
canonical (deliberately unlike `/meetings`' filter-blind one) and a link
to the pre-filtered `/meetings?jurisdiction={StateName}` search. Backed by
`crud.get_state_page_data()` (anchored `LIKE '%, CA'` suffix match — not
`list_pages()`'s substring ilike, which would leak "Decatur, GA" into
California via its "ca" substring) and `crud.get_state_coverage_index()`
(one row per covered state; also feeds `/coverage`'s "Browse by state"
section and per-state `sitemap.xml` entries with real lastmod values).
Both queries exclude `platform == "unknown"` pages — the same trust
posture as the sitemap, which noindexed pages shouldn't leak through.
Jurisdictions without a recognized `", ST"` suffix (school districts,
state agencies, non-US) don't appear on any state page — a documented
limitation. A state with zero indexable meetings 404s rather than
rendering an empty shell, and every `/m/{slug}` page whose jurisdiction
has a state now links "More {State} meetings" to its state page.

**Rebuilt 2026-08-23** around real quoted transcript text, because
Search Console measured Google *selectively declining these two page
types*: `/j/` hubs appeared at 3.6x and `/state/` at 3.1x their sitemap
share among non-indexed URLs, while `/m/` meeting pages indexed better
than theirs (0.5x). That ruled out crawl budget and domain age and left
thin, templated, near-duplicate content — a list of meeting titles is
templated; a resident explaining why they came to a 9pm hearing is not.
Both surfaces now lead with:

* **Featured meetings with real transcript snippets** — a genuine quote
  from each meeting, deep-linked to the second it was said
  (`/m/{slug}?t={start}`), transcribed meetings only. Picked by
  `archive/utils/highlights.py`, which scores every candidate window of a
  transcript against what a reader finds substantive: procedural
  language (roll call, "motion", "all in favor", "you have three
  minutes") is heavily negative, dollar figures and "residents"/
  "concerned" are positive, a curated topic hit is the strongest signal,
  the first 8%/last 3% of the meeting are skipped as ceremony, and
  windows after a "public comment" marker get a bonus. Deterministic
  arithmetic, not an LLM call — it runs for every meeting at ingest and
  has to be explainable when a bad snippet reaches a public page. Two
  coherence guards (`_repetition_penalty()`) reject a hammered content
  word and an interleaved roll-up caption phrase; both were added
  against snippets this heuristic actually produced on a live page, and
  the real strings are frozen in `tests/test_highlights.py`.
  Featured sets are date-ordered but carry a **topic diversity cap**
  (`crud.MAX_FEATURED_PER_TOPIC`): at most two cards may share a topic,
  so one busy subject cannot take over a page. The case that prompted it
  — San Diego's hub showed two cannabis cards and two housing cards
  while a public comment delivered *in character as Darth Vader* about
  flock-camera surveillance sat unfeatured in the same pool; recency
  alone had no way to prefer it. Implemented as two passes rather than a
  sort, so the cap reorders without ever shrinking the set: a page whose
  meetings genuinely all share one topic still fills up. Cards with no
  topic are never constrained (they cannot cluster), and a `?topic=`
  view is exempt (every card is about that topic by construction).
  Exactly **one** topic is `<mark>`ed per snippet, the rarest on the
  card — the same Darth Vader quote also matched `libraries-parks` on
  the word "playground" and rendered with three highlighted
  "playground"s burying the `flock` the reader came for. A rarity-*ratio*
  filter was tried first and rejected by measurement: rarity is counted
  over the page's own pool, and in a six-meeting hub pool both topics
  have a count of 1, so no ratio can separate them. The tiebreak falls
  through to curated `TOPICS` order, which is roughly
  newsworthiness-ordered and does the real work at that scale.
* **Topic chips** — curated subjects (`archive/topics.py`, edited by
  hand) that actually appear in the page's recent transcribed meetings,
  ranked by how many mention each, top 12 shown. Real `?topic=` links,
  server-rendered, so a crawler follows them and each variant carries its
  own real snippets; the canonical stays the bare URL. Discovery is
  deliberately *not* unsupervised — an uncurated "trending terms" pass
  over council transcripts surfaces `item`, `supervisor`, `motion`.
* **Meeting-card thumbnails** at the quoted moment (`/m/{slug}/card.jpg
  ?t=`), and `VideoObject` structured data for each featured meeting.
  Both only where `crud.pages_with_thumbnails()` confirms a stored frame
  — advertising a card URL that would 404 is worse than advertising none.
* **Grouped government list** (state pages) — Counties & regions /
  Cities & towns / School districts / Agencies & special districts, via
  `archive/utils/gov_classify.py` (trusts `meeting_body` where it is
  conclusive, falls back to the jurisdiction name, defaults
  conservatively to city). A sticky sidebar beside the results on
  desktop; below them on mobile, where the results lead. Every `/j/`
  link stays in the initial HTML in both layouts.
* **"Most active governments"** (state pages, ≥8 governments) — most
  meetings archived in the last 90 days.

Snippets are **precomputed and stored** in `meeting_highlights`, not
computed per request: the heuristic needs a meeting's segments, and a
long meeting's segment JSON is a six-figure-byte blob (San Diego's Board
of Directors: 6,313 segments), so computing on demand would decode
megabytes per render on the exact surface built *for* crawlers. Kept in
sync from `crud._refresh_search_corpus()` — the same single choke point
that already recomputes `search_corpus` and upserts `search_vocabulary`
— so a highlight cannot go stale the way the pre-2026-08-17 corpus could.
A page with nothing quotable simply has no row, and every consumer
renders fine without one. `scripts/backfill_meeting_highlights.py` is
the retroactive sweep and the way to re-run after a change to the
heuristic (`--force`) or to `archive/topics.py` (which bumps
`TOPICS_VERSION`, making stale rows self-identify).

`search_queries` (added alongside) logs every `/meetings` keyword with
**no user identity at all** — keyword, optional jurisdiction filter,
result count, timestamp; no IP, user id, session, or user agent. It
exists so the curated topic list can eventually be ranked by real demand
rather than guesswork (`crud.top_search_keywords()`); nothing renders it
yet. Written from a FastAPI background task, so a logging failure can
never break a search.

**`GET /j/{slug}` (per-government hub pages, added 2026-08-17)** — one
landing page per jurisdiction ("Napa, CA public meeting videos &
transcripts", `/j/napa-ca`), proxied like `/state/*`. Grouped by
`jurisdiction_hub_slug()` (`archive/utils/jurisdiction_format.py`) — the
slug of the *display* form, so raw-string variants of one government
("City of Napa, CA" / "Napa, CA" / casing) consolidate into a single hub
while real distinctions ("County of Napa, CA", "City and County of San
Francisco, CA") stay separate; the state-page tables group by the same
slug and link each government to its hub. Each hub lists every archived
meeting for that government newest-first with transcript badges, a
meeting-body breakdown ("City Council (30) · Planning Commission (12)"
from `meeting_body`), date range, the same featured snippets and topic
chips the state pages carry (6 cards rather than 12 — a hub is one
government, so after a handful the full meeting list below serves the
reader better), a `BreadcrumbList` (Home › State › Jurisdiction),
`VideoObject` structured data and breadcrumb nav, and links to `/state/{slug}` and the
pre-filtered `/meetings?jurisdiction=` search; every `/m/{slug}` page
links "More {Jurisdiction} meetings" to its hub. **Thin-content
threshold**: the archive is wide and shallow (measured 2026-08-17: 574
stateful jurisdictions, 439 with exactly one meeting), so every hub
*renders* but only hubs with ≥ `crud.JURISDICTION_HUB_MIN_INDEXABLE` (2)
meetings are indexable and listed in `sitemap.xml` (real lastmod);
below that the page carries `noindex` and a "know of another?" note.
Evaluated live per request — a singleton hub becomes indexable by
itself when its second meeting lands. Backed by
`crud.get_jurisdiction_hub_data()` / `crud.list_indexable_hub_entries()`
(one `GROUP BY jurisdiction` over indexable, non-empty pages; no schema
change). Same `platform == "unknown"` / empty-page exclusions as the
sitemap and state pages.

**Search** covers title, jurisdiction, agenda item text, and *every*
transcript version's segment text (so a demoted version's text still
counts toward a match, though the listing's badge and snippet reflect the
default version). All of that is materialized at ingest into one
lowercased `meeting_pages.search_corpus` column (`compute_search_corpus()`
in `archive/utils/search.py`, refreshed by `crud._refresh_search_corpus()`
on every ingest and when a Whisper transcription completes), and every
filter runs in SQL with `LIMIT/OFFSET` + a windowed count — see
`list_pages()`'s docstring. Query syntax: bare words are ANDed,
`"quoted phrase"` requires adjacency, `-word` / `-"phrase"` excludes.
Three code paths, chosen per request:
- **Full-text (Postgres, once Alembic revision `c1d2e3f4a5b6` has been
  applied)** — the default in production: `search_tsv @@
  websearch_to_tsquery('english', q)` against a `GENERATED` tsvector
  column with a GIN index, answered from the index without reading the
  corpus, so a common word costs the same as a rare one. Adds stemming
  (budget/budgets/budgeting), stopword removal and `OR`. Word match, not
  substring. `?sort=relevance` ("Sort by relevance" checkbox) orders by
  `ts_rank_cd`; the default stays newest-first. `list_pages()`
  feature-detects the column (`crud._fts_available()`) and falls back to
  the next path when it's absent, so code and migration can deploy in
  either order.
- **Exact substring (SQLite in dev/CI, or Postgres before that
  migration)**: `search_corpus LIKE '%term%'` — byte-for-byte the
  predicate `archive/utils/search.py`'s `matches()` computes, GIN-trigram
  indexed on Postgres (revision `bf4f54a11e5f`).
- **Fuzzy** (`fuzzy=true`, "Fuzzy search (…slower)" checkbox): each query
  word must be within a small edit distance of a real word in the
  meeting's text — so "traffic" still finds a transcript that says
  "trafic" or "traffiq" (real transcription errors). On Postgres with
  `search_vocabulary` present (revision `c684908ce5ff`), this is
  SQL-authoritative too: each word longer than 4 chars is trigram-matched
  against that small, GIN-indexed table of distinct real words
  (`crud._vocab_candidate_stmt()`), every candidate re-verified with the
  same bounded-Levenshtein check for exact semantic parity, and the
  confirmed words checked against `search_corpus` via the substring path
  above — no full-archive scan. `list_pages()` feature-detects the table
  (`crud._vocab_available()`) the same way it does `search_tsv`, falling
  back to a Python-streamed scan over `search_corpus` text (SQLite dev/CI,
  or Postgres before that migration) otherwise. Still opt-in and slower
  than exact/full-text search — common short words can still take a few
  seconds since several individually-common real-word matches may need
  checking — but no longer scales with total archive size.

`BACKLOG_DONE.md`'s "Search: move to a materialized/indexed column — full
saga, closed" entry has the complete history, from the 2026-08-17 day
this went from a Python scan over transcript JSON (which OOM-crashed the
Archive on common terms) through exact-mode, full-text, and fuzzy all
becoming SQL-backed.

## On-demand transcription

Sometimes the government site's own captions are missing, garbled, or in
the wrong language — this app can't fix that at the source, but a viewer
can ask for a real transcript made from the meeting's own audio instead.
Click "Transcribe this meeting from audio" on any meeting page (ephemeral
or permanent), and — once a couple of quick checks pass — leave an email
address to be notified when it's ready. No account required — a Clerk
session isn't checked or needed; the email address (confirmed by a
one-click link the first time) is the only gate. It's added to the
permanent page alongside the original, not instead of it, so nothing is
ever silently replaced.

**Why this needs a third service.** Transcribing a multi-hour meeting is
real, sustained work — nothing like the sub-second checks the resolver and
Archive web services already handle per request. Neither of those is a
place to run something that might take hours, so a third, persistent
service (`worker/`, a Render Background Worker — the first paid, always-on
piece of infrastructure this project has needed) exists just to grind
through transcription jobs in the background. A second, identically-
configured replica (`rtr-transcription-worker-2` in `render.yaml`) can run
alongside it during a backlog catch-up window — real, distinct Render
services rather than `numInstances` scaling on one, since the two need to
differ in exactly one env var; see that file's own comment on the second
service block for why, and `claim_next_chunk()`'s docstring
(`archive/db/crud.py`) for why job/chunk claiming is already safe for any
number of concurrent worker processes.

**The flow, end to end:**
1. **Feasibility check** (`POST /api/transcription/check-feasibility`,
   `app/main.py`) — live-resolves the meeting fresh, then probes the
   discovered media URL's real duration via `ffprobe`
   (`app/platforms/media_probe.py`). Rejects anything implausibly short
   (under 5 minutes — almost certainly the wrong asset, not a real
   meeting) or implausibly long (over 14 hours). This is also what makes
   the button itself real friction against abuse: nothing past this point
   happens for a meeting with no usable source.
2. **Submit** (`POST /api/transcription/submit`) — re-runs the entire
   feasibility check server-side (never trusts a client-supplied "it
   passed" flag) and asks the Archive to create a job
   (`POST /internal/transcription/create-job`, token-gated like every
   other resolver↔Archive call). The Archive checks whether this email is
   already a newsletter audience member: if so, the job is queued
   immediately; if it's a first-time address, the job waits at
   `pending_confirmation` until a confirmation-email link is clicked
   (`GET /confirm-transcription` on the resolver) — one click, once, ever,
   per address, since confirming also opts them into the audience.
3. **Processing** (`worker/main.py`) — a persistent loop: claim the oldest
   pending chunk (`archive/db/crud.py`'s `claim_next_chunk()`/
   `report_chunk_result()` — the worker reaches into the Archive's
   database directly here, the one deliberate exception to the
   resolver↔Archive HTTP-only rule, since this process *is* Archive
   backend logic, just running in a process shape the Archive's own web
   dyno can't offer), extract that chunk's audio with `ffmpeg` (re-
   resolving a fresh media URL first — HLS/signed URLs can go stale over
   a long-running job; a chunk whose fast input-side seek comes back
   undecodable gets one retry with a slower output-side seek, which is
   what makes Cablecast's fMP4 VOD work at all — see
   `media_probe.py`'s `_extract_chunk_once()`), transcribe it with a
   self-hosted `faster-whisper`
   model (loaded once at process startup, reused for every job), shift
   its timestamps from chunk-relative to full-meeting-relative seconds
   (`worker/segment_utils.py`'s `shift_segments()` — the same `{start,
   end, text}` convention every adapter's real segments already use, so
   the existing deep-link/seek logic needs no changes to work on a
   transcribed transcript), and persist the result before moving to the
   next chunk. Checkpointed after every chunk specifically so a worker
   restart or redeploy loses at most one in-flight chunk, never the whole
   job.
4. **Completion** — the finished transcript becomes a new
   `TranscriptVersion` (`source="transcribed"`, language detected from its
   own real text the same way every scraped-caption adapter already does)
   and is promoted to the page's default (closing a real, previously-
   unaddressed gap: earlier, only a page's *very first* transcript version
   ever became default — see `BACKLOG_DONE.md`). Nothing is deleted — the
   original scraped version (if any) stays reachable through the existing
   version picker. An email goes out with an excerpt and a link to the
   permanent page.

**Speaker labels aren't built yet, on purpose.** `TranscriptSegment` (`app/
platforms/models.py`) already carries an optional `speaker` field, unused
by every path today (including this one) — added now, cheaply, so a future
diarization pass (self-hosted `faster-whisper` is the same base WhisperX
already builds real diarization on top of, via `pyannote.audio`) doesn't
need its own schema change later.

**Working the existing backlog locally, on a bigger model than the cloud
worker can afford.** `worker/`'s `faster-whisper` model size is forced
down to `"tiny"` by Render's 2GB worker plan (real OOM crashes on
`"small"`, not a quality choice — see `worker/transcription_engine.py`'s
own docstring), and `"tiny"`'s real accuracy against actual meeting audio
has two confirmed failure modes documented in `BACKLOG_DONE.md`'s "Worker
Render plan sizing" entry (a meaning-changing mistranscription, and a
near-total transcription failure on a real stretch of English speech). A
local Mac isn't under that ceiling, so `scripts/transcribe_backlog_
locally.py` works the archived-but-untranscribed backlog
(`/meetings?has_transcript=false`, ~209 meetings as of 2026-08-16) from
here instead:

```bash
python scripts/transcribe_backlog_locally.py --dry-run
python scripts/transcribe_backlog_locally.py --limit 5
python scripts/transcribe_backlog_locally.py --model-size medium --limit 1
python scripts/transcribe_backlog_locally.py --url "https://..."  # one specific meeting, bypassing the queue
# A real overnight/multi-day unattended batch (see "Thermal pacing" below):
caffeinate -s python scripts/transcribe_backlog_locally.py --cpu-threads 2 --chunk-cooldown-seconds 30
```

- **Model size is auto-picked from this Mac's real total RAM** (`"small"`
  at ≥16GB, `"medium"` at ≥32GB, `"base"` otherwise — see
  `_pick_default_model_size()`'s own docstring for the exact reasoning),
  not guessed — override with `--model-size`. `device="cpu"` stays correct
  even here: `faster-whisper`'s CTranslate2 backend has no Apple Silicon
  GPU acceleration, so this is still CPU inference, just on real
  multi-core hardware instead of Render's box.
- **Candidates** come from `GET /internal/transcription-backlog`
  (`archive/main.py`, token-gated like every other `/internal/*` route) —
  the any-platform, batch counterpart to `/internal/transcript-wanted`'s
  YouTube-only queue, reusing `find_auto_transcription_candidate()`'s own
  quality/cooldown checks (`archive/db/crud.py`) so this script and the
  worker's own idle-time auto-generation never duplicate feasibility-probe
  effort on the same page. `probe_duration()`/`is_plausible_meeting_
  duration()` (the same 5-minute-to-14-hour bounds the worker already
  uses) skip an infeasible candidate cheaply, before spending real
  transcription time on it.
- **No full download** — reuses `extract_chunk_audio()`
  (`app/platforms/media_probe.py`) for direct remote extraction (an HTTP
  Range fetch for a direct file, just the covering `.ts` segments for
  HLS), same as the worker. **Chunking is kept** (900 seconds, same as
  the worker's own `AUTO_TRANSCRIPTION_CHUNK_SIZE_SECONDS`) for a
  different reason than the worker's real one — RAM isn't the local
  constraint — see the script's own module docstring: it bounds each
  individual `ffmpeg`/`ffprobe` call under `media_probe.py`'s shared
  120-second subprocess timeout, proven safe at 900s in production but
  untested at a full multi-hour single pass.
- **Pushes with `"source": "transcribed"` explicitly** via
  `POST /internal/ingest` (now accepts an optional `source` field,
  default `"scraped"` for every other caller) — the same real AI-transcript
  disclaimer the worker's own output gets, not a silent "scraped" (i.e.
  authoritative government caption) mislabel. Dedup is scoped by `source`
  too, so a repeat run against an already-transcribed meeting is a no-op
  rather than a duplicate version.
- **Never touches `transcription_jobs`/`claim_next_chunk()`** — those are
  explicitly single-worker-process-safe only (see `claim_next_chunk()`'s
  own docstring), so this script discovers/pushes purely over the same
  token-gated `/internal/*` HTTP surface `scripts/fetch_youtube_
  transcripts.py` already established, and can safely run at the same
  time as the real worker.
- **Built for an unattended overnight run someone who isn't a developer
  checks on, not just an interactive one** — added 2026-08-17 after a
  real multi-hour run showed zero output in its redirected log file
  despite being alive (`print()` fully buffers on a redirected stream;
  see `BACKLOG_DONE.md`). Progress now goes through Python's `logging`
  module (same convention `worker/main.py` already uses), which flushes
  every line immediately even when piped to a file — plain-English,
  timestamped lines for the run's real config, each meeting starting/
  finishing, running ingested/skipped/failed totals after every meeting
  (not just at the end), and retries. Every call to the Archive's own
  `/internal/*` API (candidate list fetch, ingest push, promote) retries
  a 5xx or connection-level failure with exponential backoff instead of
  crashing the whole run — real incident: a transient 502 on the very
  first call used to end the entire batch before the main loop even
  started. If an ingest push still fails after retries, the finished
  transcription (the expensive part) is saved to `local_transcription_
  backups/` rather than discarded, recoverable with a plain `curl` once
  the Archive is reachable again. A detected wall-clock-vs-processing-time
  gap (the machine likely slept, or a request stalled) gets logged
  explicitly rather than passing silently. See `tests/test_transcribe_
  backlog_locally.py` for retry/gap-detection coverage against a real
  local HTTP server (not a mocked session).
- **One transient failure no longer costs a whole meeting** (2026-08-22,
  after ten-plus confirmed cases across three sessions — see
  `BACKLOG_DONE.md`). The three calls that reach a live government source
  — `finder.resolve()`, `probe_duration()`, `extract_chunk_audio()` — now
  retry with backoff through the shared `app/utils/retry.py` policy
  instead of recording a meeting as unusable on the first failure: four
  meetings marked permanently unresolvable all succeeded on an unchanged
  re-run minutes later, and 3 of 4 failed `new.swagit.com` extractions
  cleared on an immediate retry. Genuinely permanent failures (an
  unregistered platform, `ffmpeg` missing from PATH) still fail on the
  first attempt with no delay, the same discipline the Archive-API retry
  applies to a 4xx. And a chunk that still fails **checkpoints the chunks
  already transcribed** to `local_transcription_backups/partial/`, so the
  next run resumes from there rather than starting over — a real 55-chunk
  meeting previously discarded 50 finished chunks (~44 minutes of Whisper
  compute) after failing on chunk 51. `--no-resume` ignores a checkpoint;
  one is refused automatically if `--chunk-seconds` or the source's
  duration has changed since it was written. **`MEDIA_ATTEMPTS` is 2 (one
  retry) and deliberately a tunable constant, not a claim that one retry
  is always enough** — one confirmed case (Brookhaven NY) failed two
  identical back-to-back retries. `worker/main.py`'s idle-time
  auto-generation got the same treatment for its own feasibility check;
  its chunk-processing path never had the gap (see "On-demand
  transcription" above — chunk failures already get three tries plus
  job-level retries, and partial segments are persisted per job).
- **Thermal pacing, for a real multi-day unattended run on an older/
  fanless Mac (added 2026-08-21).** Nothing above throttles CPU usage by
  default — a genuinely long batch can run the CPU at a sustained high
  clock for hours at a stretch otherwise, a real overheating risk on
  hardware without much thermal headroom. Two independent knobs, meant to
  be used together: `--cpu-threads N` caps CTranslate2 to N CPU threads
  (default: half this machine's real physical core count); `--chunk-
  cooldown-seconds N` rests N seconds after every ~900s chunk — a real
  duty-cycle rest at the natural per-chunk boundary, not just between
  meetings — and also polls macOS's own `CPU_Speed_Limit` (`pmset -g
  therm`, no sudo needed) after each cooldown, waiting longer if the OS
  has already started throttling. Live-verified against a real
  ~5.25-hour meeting (Albemarle, NC) at `--cpu-threads 2`: `CPU_Speed_
  Limit` stayed at 100% (no throttling) for the entire run. Wrap the
  whole invocation in `caffeinate -s` (prevents *system* sleep on AC
  power only) so a multi-day run survives the machine's own idle-sleep
  timer.
- **A fresh Homebrew-Python venv has an empty default SSL trust store,**
  breaking every `aiohttp` call in this script (and six other local
  scripts) with `SSLCertVerificationError` — easy to mistake for a real
  network outage. Fixed by setting `SSL_CERT_FILE` from `certifi` before
  `import aiohttp` specifically (not just before first use — aiohttp
  caches its default `SSLContext` at import time). See `CLAUDE.md`'s
  matching convention bullet for the full incident and why the ordering
  matters.

Live-verified 2026-08-16 against a real backlog meeting (Welland/Elgin
County, ON — `welland-2026-01-27-county-council-meeting`, a real 783-second
eScribe recording with no prior transcript): `--model-size small` produced
102 real, coherent segments (language detected `en`) in 113 seconds,
pushed successfully, and the AI TRANSCRIPT disclaimer + real timestamped
segments (starting "We're live." at 0:00, ending with real adjournment/
motion dialogue) are live on the actual public page. The meeting no
longer appears in a follow-up `/internal/transcription-backlog` call.

**Giving both cloud workers real concurrent work, added 2026-08-21.**
`worker/`'s own idle-time auto-generation (`maybe_generate_auto_job()`)
only ever keeps ~1 job in flight at a time — it's only invoked once the
entire active job table is empty. A single job's chunks are inherently
serial (`claim_next_chunk()` claims one job's next chunk at a time), so a
second worker (`rtr-transcription-worker-2`, see "Why this needs a third
service" above) only gets real parallel throughput once ≥2 different jobs
are queued at once. `scripts/bulk_queue_transcription_backlog.py` closes
that gap: it pulls several candidates from the same
`GET /internal/transcription-backlog` endpoint the script above uses and
creates several real `TranscriptionJob` rows at once via
`POST /internal/transcription/create-job`, at the low-priority tier that
route now exposes (`priority`, added to `TranscriptionCreateJobRequest` —
previously only `worker/main.py`'s own in-process auto-generation call
could use `PRIORITY_LOW`).

```bash
python scripts/bulk_queue_transcription_backlog.py --dry-run
python scripts/bulk_queue_transcription_backlog.py
python scripts/bulk_queue_transcription_backlog.py --limit 4
```

Batch size defaults to 8, deliberately well under `archive/db/crud.py`'s
global `MAX_CONCURRENT_TRANSCRIPTION_JOBS = 15` (shared across every
priority tier) — leaves real headroom so a live visitor's own
transcription request never hits `too_many_active_jobs` during a catch-up
run, and `PRIORITY_LOW` means a real request still jumps the queue ahead
of whatever this script queued at the very next claim, regardless of how
full the batch is. `clerk_verified=True` on each created job (this script
holds `ARCHIVE_INGEST_TOKEN`, the same trusted-internal-caller position
the resolver itself is in after its own real Clerk check) skips the
confirmation-email step entirely — without it, a job would sit at
`pending_confirmation` until someone clicked a link, defeating the
purpose. Runs hourly via `.github/workflows/bulk-queue-transcription-
backlog.yml` (also safe to run by hand any time — server-side dedup and
the `too_many_active_jobs` early-stop are what make hourly safe, see the
script's own module docstring) — tied to the backlog catch-up window this
second worker exists for, and `BACKLOG.md` for the residual auto-
generation race this pairs with.

**Daily activity report, added 2026-08-21.** `GET /internal/send-worker-
daily-report` (Archive service, token-gated like every other
`/internal/*` route) composes and emails a plain-text-style HTML digest —
chunks completed, jobs finished, and (Postgres only) segments transcribed
in the last 24 hours, plus a snapshot of what's still ahead: active jobs,
remaining chunks in those jobs, meetings on the site with no transcript,
and how many URLs are still sitting in the tier-3 discovery queue
(`scripts/tier3_auto_transcription_queue.txt`, read directly off disk —
this service's own deploy already checks out the whole repo). Triggered
daily by `.github/workflows/worker-daily-report.yml`, which is a plain
`curl` ping — same pattern `/admin/send-search-alerts` already
established: GitHub Actions never touches `RESEND_API_KEY` or
`DATABASE_URL` directly, it just pings an already-running Render service
that already holds those credentials, rather than a new script
duplicating them as fresh GitHub secrets.

The 24h chunk-completion figure needs a real reference point to diff
against, since `TranscriptionJob.chunks_completed` has no per-chunk
timestamp anywhere in the schema — `WorkerReportSnapshot`
(`archive/db/models.py`, one row, overwritten on every send) holds
exactly that: the cumulative all-time totals as of the last report. The
first-ever send has nothing to diff against and reports "n/a (first
report)" for that one figure rather than a misleading number.
`GET /internal/transcription-queue-stats` exposes the same live summary
read-only (no snapshot advance), for anything else that wants it later
(a dashboard, say) without needing to trigger a real email.

## Accounts (Clerk)

Shipped 2026-08-11, phase 1: sign in and save meetings/searches to your
own account. Deliberately narrow scope — no public profile pages, no
posts/reposts, no billing yet (see `BACKLOG.md`'s "Accounts + token
billing" section for what's still ahead). A hard non-goal, tested for:
**nothing that worked anonymously before this shipped requires an account
now** — browsing, searching, watching a meeting, and reading a transcript
are all completely unaffected by whether you're signed in. The only new,
purely additive things a signed-in visitor sees are a "Save this
meeting"/"Save this search" button, a bookmark icon by the meeting title,
a "My Saved Items" nav link, and a user avatar.

### What needs an account, at a glance

| Works for everyone, no sign-in | Requires a signed-in Clerk session |
|---|---|
| Resolving/watching a meeting, transcript, and agenda | Saving a meeting (`POST /api/account/save-meeting`) |
| Deep-linking — seeking, "Copy link to current time", "Go to time" | Saving a search (`POST /api/account/save-search`) |
| In-page transcript search, transcript download (Text/SRT) | Unsaving either of the above |
| `/meetings` site-wide search across the Archive | "My Saved Items" (`/account/saved`) |
| "Report a problem with this meeting" | |
| Requesting on-demand transcription from audio — email only, see "On-demand transcription" below | |

Requesting a transcription is **not** Clerk-gated — by deliberate design,
not as a stepping-stone toward eventually requiring a full account. It's
the app's most cost-intensive feature by far (see "On-demand transcription"
below for real dollar/compute figures), and email confirmation (a one-click
click-through the first time) is the intentional middle path between
"fully open" and "requires a real account" — real friction against abuse
without putting a login wall in front of the app's single costliest
feature. See `BACKLOG.md`'s "Accounts + token billing — phases 2-6" entry
(under "Roadmap & strategy") for the broader account/billing thinking
this sits alongside.

(This paragraph used to flag an open UX gap — the "Save this meeting"/
"Save this search" buttons rendering for signed-out visitors. That
premise was investigated 2026-08-13 and turned out to be **false**: both
templates have gated on `{% if active_account %}` since the first
accounts commits. Corrected here 2026-08-21; see `BACKLOG_DONE.md`.)

**Why Clerk, not a hand-rolled session system.** The user explicitly chose
a third-party auth provider over building/maintaining login, sessions, and
password security by hand ("I'm kind of leaning away from becoming a
security expert" — see `BACKLOG.md` for the full tradeoff discussion).
Clerk also gives a real privacy-posture improvement as a side effect: this
app's own database **never stores an email address, name, or any other
PII for an account** — only Clerk's opaque user id (e.g. `user_2abc...`).
Clerk holds the actual identity data; this app just remembers what that id
saved.

**Architecture.** Clerk issues a signed session JWT in a `__session`
cookie on the shared public domain. Both services verify it **locally and
independently** — no session table, no per-request DB lookup, no
cross-service "who owns this session" problem:
- `app/utils/clerk_auth.py` / `archive/utils/clerk_auth.py` (deliberately
  duplicated, same reasoning as this repo's other cross-service
  duplication) — `get_clerk_user_id(request)` returns the signed-in
  visitor's Clerk user id or `None`, never raises, and returns `None`
  immediately (no verification work at all) whenever `CLERK_SECRET_KEY`
  isn't set or there's no session cookie/Authorization header present —
  so a Clerk outage or missing config degrades to "everyone looks signed
  out," never a broken page. `clerk_frontend_api_url(publishable_key)`
  derives Clerk's per-account "Frontend API" domain from the publishable
  key itself (matching Clerk's own `@clerk/shared` `parsePublishableKey`),
  so the ClerkJS script tag can be built without a hand-copied snippet.
- `shared_static/clerk_nav.js` — loads ClerkJS via a CDN script tag (using
  that derived Frontend API domain), mounts the nav's sign-in link/user
  avatar, and exposes `window.RTRClerk` for other page scripts. Entirely
  client-side and entirely optional: if `CLERK_PUBLISHABLE_KEY` isn't set,
  this does nothing at all, no script load attempted.
- **Cookie forwarding through the reverse proxy**: `/meetings`, `/m/*`,
  and `/account/saved` are all rendered by the Archive service but
  reached through the resolver's proxy (see "Permanent pages (the
  Archive)" above) — `app/archive_client.py`'s `proxy_get()` forwards the
  incoming request's raw `Cookie` header to Archive on exactly these three
  routes (not static assets/sitemap/feed, which don't need it), so Archive
  can verify the session itself with zero extra network round-trip.

**Data model.** One new table, `SavedItem` (`archive/db/models.py`) — it
lives in Archive's database (not the resolver's), since it needs a real
same-database foreign key to `MeetingPage.id`. Columns: `clerk_user_id`
(indexed, opaque — never an email), `item_type` (`saved_meeting` /
`saved_search`), `meeting_page_id` (nullable FK, set only for
`saved_meeting`), `search_params` (nullable JSON — the same filter dict
`/meetings` already accepts, set only for `saved_search`), `created_at`.
Unsaving is a hard delete; no soft-delete/undo.

**Routes:**
- Resolver: `POST /api/account/save-meeting` / `unsave-meeting` /
  `save-search` / `unsave-search` (public, 401 `not_logged_in` if no
  valid session) — each verifies the session locally, then calls a
  bearer-gated `/internal/account/*` route on Archive with the
  **already-verified** `clerk_user_id`, the same trust pattern every other
  resolver→Archive internal call already uses. `POST /api/clerk/webhook`
  handles Clerk's `user.created` (auto-subscribes the address to the
  Resend newsletter audience, sends the "Thanks" email — see "Lifecycle
  emails" below) and `user.deleted` (purges the account's `SavedItem` rows
  — the right-to-deletion story on this app's side, since it stores no
  other PII for an account at all). Verified via `svix` before trusting
  anything in the payload.
- Archive: the bearer-gated `/internal/account/*` counterparts, plus
  `GET /account/saved` (the "My Saved Items" page — a friendly "sign in to
  save things" state for an anonymous visitor, not an error).

**Lifecycle emails.** Five of the six emails from rtr-business's
`marketing/LIFECYCLE_EMAILS.md` (approved copy/voice) are live: "Thanks"
(account created), "Welcome" (newsletter-only signup), "Goodbye for now"
(unsubscribed), a branded "Your transcript's ready" (rewrite of the
existing completion email, keeping its AI-transcript disclaimer), and "We
couldn't cook this one" (new — fires when a transcription job gives up
after repeated chunk failures). The resolver gained its own transactional
Resend-send capability for this (`app/main.py`'s `_resend_send()` +
branded template, duplicated from `archive/utils/email.py`'s equivalent)
— previously it only ever upserted Resend audience contacts. Saved-search
alert emails (the doc's sixth entry, "People are talking about…") are
also live: `archive/search_alerts.py`, run daily by
`.github/workflows/send-search-alerts.yml` via
`scripts/send_search_alerts.py`, matches new results against saved
searches and sends a per-alert email with its own unsubscribe token.

**Env vars** — see `.env.example` / `archive/.env.example` for the full,
current list and setup notes. `CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY`
on both services; `CLERK_JWT_KEY` (optional — **leave it blank unless you
have a specific reason not to**, see the env file's comment for why a
malformed value here is strictly worse than an absent one);
`CLERK_WEBHOOK_SIGNING_SECRET` on the resolver only;
`RESEND_FROM_ADDRESS`/`RESEND_REPLY_TO_ADDRESS` newly needed on the
resolver as of this feature.

**Real incidents from the production cutover** (dev instance → real
Clerk production instance, custom-domain DNS, a new webhook) — all found
live and now fixed, full writeup in `BACKLOG_DONE.md`'s "Clerk production
cutover" entry: a base64-padding bug in `clerk_frontend_api_url()` that
disabled Clerk site-wide, a CSS-specificity bug that left a stray nav
divider visible when signed in, and a malformed `CLERK_JWT_KEY` that
silently made every signed-in visitor look signed out server-side while
looking completely normal client-side. Worth reading in full before
touching Clerk env vars/DNS again.

**Deliberately deferred, not yet verified end to end**: the
`user.deleted` webhook → `SavedItem` purge (the right-to-deletion
cascade) has unit test coverage but has never actually been fired for
real against a deleted Clerk account. See `BACKLOG.md` for the user's
explicit call on this.

## Email

Two independent pieces of plumbing, easy to conflate but separate
concerns:

**Outbound (sending)** — Resend (`archive/utils/email.py`, and
`app/main.py`'s own `_resend_send()` + branded templates as of the
accounts/lifecycle-emails feature — previously the resolver only ever
upserted Resend audience contacts, never sent transactional mail).
`RESEND_API_KEY` + `RESEND_FROM_ADDRESS` (currently `Ryan
<ryan@ally.redtaperecordings.com>` — `ally.redtaperecordings.com` is
Resend's verified sending subdomain, its DNS untouched since setup) +
`RESEND_REPLY_TO_ADDRESS` (currently `ryan@redtaperecordings.com`, the
root domain — set on all three Render services: resolver, Archive,
worker) + `RESEND_AUDIENCE_ID` (the newsletter audience). See "Accounts
(Clerk)" above for which lifecycle emails are actually live.

**Inbound (receiving)** — `redtaperecordings.com`'s MX records point at
ImprovMX (free forwarding: `mx1`/`mx2.improvmx.com` plus an SPF TXT
record), which forwards `ryan@`, `ally@`, and a wildcard catch-all, all
to `ryan@how-to-adu.com`. Set up and managed entirely in Namecheap DNS +
the ImprovMX dashboard — no code involved, nothing to configure
per-environment. One subdomain has its own separate, unrelated MX:
`send.ally.redtaperecordings.com` → `feedback-smtp.us-east-1.amazonses.com`,
Resend's own bounce-handling record for its SES backend — don't touch it
when editing DNS here even though it looks similar to the ImprovMX pair,
since it's a different subdomain serving a different purpose. Full setup
history (why Namecheap's own forwarding wizard couldn't be used
directly, both live-verification passes) is in `BACKLOG_DONE.md`'s
"Email deliverability" section.

**Site-facing addresses** currently shown/used are a mix, not yet
consolidated: footer `mailto:` links use `ryan@redtaperecordings.com`
(`app/templates/base.html`, `archive/templates/base.html`), the About
page shows `ryan@how-to-adu.com` directly
(`app/templates/about.html`), and `RESEND_REPLY_TO_ADDRESS` is
`ryan@redtaperecordings.com`. Auditing and consolidating these onto
`ally@redtaperecordings.com` is an open `BACKLOG.md` item as of
2026-08-12.

**Ops-only addresses**, unrelated to the site and out of scope for the
above: `DAILY_REPORT_EMAIL_TO` and `YOUTUBE_FETCH_REPORT_EMAIL` (both in
`scripts/`, both default to `ryan@how-to-adu.com`) send operator
digests, not user-facing mail.

## Social auto-posting (Bluesky / Mastodon)

When a brand-new permanent page is created in the Archive **and** the
resolve behind it was genuinely high-quality, the Archive can announce it
on a Bluesky and/or Mastodon account automatically
(`archive/utils/social.py`, hooked into `/internal/ingest`). Off by
default — with no credentials set the feature is completely inert.

**What counts as "high quality"** mirrors `app/db/outcomes.py`'s
`success` bucket (the same definition `/admin/stats` reports on): a real
video URL, a real transcript, no garbled-source/hallucination warning,
and English-or-undetected language — plus a minimum transcript length
this feature adds on top (`SOCIAL_MIN_SEGMENTS`, default 50 segments),
because a technically-successful caption stub isn't worth a public post.
Agenda-only pages, garbled transcripts (e.g. the Fountain Valley case),
and non-English detections never post.

**Provenance is a separate bar, and it's absolute**: nothing that came
out of `generic_fallback.py`'s scan-any-page path is ever announced —
`best_effort`, or `platform == "unknown"` — however good its transcript
looks. Everything else on the list above asks "is this content good?",
which is a different question from "do we actually know what this is?",
and a fallback resolve can score perfectly on all of it while nothing has
verified the scraped page is a genuine government meeting. Both checks
are needed, not one: the fallback delegates to YouTube whenever it finds
an embed, and those results carry `platform = "youtube"`, so a
platform-only check misses the most common real case (see
`ResolvedMeeting.best_effort`). Added 2026-08-21 — the pipeline shipped
without it, see `BACKLOG_DONE.md`. Note this deliberately does *not*
extend to `noindex`/sitemap/hub visibility: those pages stay indexed on
purpose, see `BACKLOG.md`.

**When it fires**: only when `/internal/ingest` *creates* the page.
Re-ingests — the resolver's push-retry sweep, stale-page rechecks,
`scripts/backfill_archived_pages.py`'s corpus-wide re-resolve — can never
trigger a post, and a `SocialPost` table row per (page, network),
claimed *before* the network call under a unique constraint, makes
posting at-most-once even under a race. A failed post is recorded and
deliberately never retried automatically (a missed announcement is
cheap; a duplicate on a public feed isn't). Announcements are also
spaced at least `SOCIAL_MIN_POST_INTERVAL_SECONDS` apart (default 180s):
a burst of qualifying new pages — several lookups at once, or a bulk
seed — posts at most one per window, with the rest skipped outright
rather than queued. Known residual: a page created agenda-only that
gains a real transcript *later* never gets announced — see `BACKLOG.md`.

**Setup** (the human half — none of this can be automated):

1. Create the account: for Bluesky this is done — the real account is
   [`redtaperecordings.bsky.social`](https://bsky.app/profile/redtaperecordings.bsky.social),
   registered 2026-08-21 (a custom `@redtaperecordings.com` domain
   handle can be set later without changing anything here except the
   `BLUESKY_HANDLE` value). For Mastodon, pick an instance and register
   there.
2. Get credentials: Bluesky — Settings → App Passwords → create one
   (never use the real account password); Mastodon — Preferences →
   Development → New application with the `write:statuses` scope, copy
   the access token.
3. Set env vars on the **Archive** Render service (see
   `archive/.env.example`): `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD`
   and/or `MASTODON_BASE_URL` + `MASTODON_ACCESS_TOKEN`.
   `PUBLIC_BASE_URL` must also be set (it already is in production) —
   posts link to `{PUBLIC_BASE_URL}/m/{slug}`.

Either network can be enabled alone; each posts and dedups
independently. Post text is composed once ("Somebody looked up
{title} — you can now search a transcript of that meeting and link to
specific timestamps at {url}", plus a "{jurisdiction} — {date}" footer
line), capped at 300 characters (Bluesky's limit, the stricter of the
two). The sentence and permalink always survive whole — an over-long
title is truncated with an ellipsis, and the footer is dropped before
the title would be gutted. A proper Bluesky link facet makes the URL
clickable.

> **Live status**: Bluesky posting is live-verified — the first real
> post from `redtaperecordings.bsky.social` landed 2026-08-21 off a
> real prod resolve (see `BACKLOG_DONE.md`). The Mastodon client is
> written against the documented API but has never made a real post
> (no account exists yet) — treat it as best-effort until one is
> watched, same as any schema-verified-but-not-content-verified path
> in this repo; see `BACKLOG.md` for the open residuals.

## Meeting card images (`og:image` / `thumbnailUrl`)

Every meeting page needs one image: search engines require a
`VideoObject.thumbnailUrl` before a video is eligible for a rich result
at all, and Bluesky/Mastodon (see "Social auto-posting" above) build
their link cards from `og:image`. YouTube-backed pages had one from
2026-08-14 (a free, predictable `i.ytimg.com` URL). Every *other* page —
direct mp4/m3u8, the majority of the Archive — got a real one on
2026-08-21: a frame pulled out of the meeting's own video with `ffmpeg`.

**Which frame** (`archive/utils/video_thumbnail.py`'s
`target_offset_seconds()`), in priority order:

1. **The shared moment, plus 20 seconds.** When the URL carries `?t=N` —
   someone shared that exact moment — the card shows the frame at
   `N + 20s`, landing *inside* the relevant content rather than on the
   transition into it. Verified against the real San Carlos meeting:
   `?t=982` produces a frame whose on-screen overlay reads
   "7. CONSENT CALENDAR", the item that timestamp points at.
2. **Otherwise, 300 seconds before the end.** Meetings routinely open
   with several minutes of dead air behind a static "meeting will begin
   shortly" placeholder, so an early-offset frame is frequently a literal
   blank slate; near the end there is reliably a real chamber with real
   people in it. Needs a duration, which comes from `ffprobe`
   (`probe_duration()`).
3. **Otherwise halfway through**, when the video is too short for (2) to
   mean anything — or a fixed 600s when `ffprobe` couldn't report a
   duration at all, since "halfway" isn't computable without one.

**Where the bytes live**: a `meeting_page_thumbnails` table, keyed
`(meeting_page_id, offset_seconds)`, one row per extracted frame with the
JPEG stored directly (`archive/db/models.py`). This repo has no object
storage, no persistent disk and no image library, and ~1200 pages × one
~30-55KB frame is not enough volume to justify adding a vendor. The
unique constraint doubles as the cache: a per-timestamp card is extracted
once and every later fetch is one indexed row read. `MAX_FRAMES_PER_PAGE`
(12) bounds what a crawl over many distinct `?t=` values can store, and
timestamps are quantized into 20s buckets before extraction for the same
reason.

**Serving**: `GET /m/{slug}/card.jpg?t=N` (proxied like `/m/*`) with
`Cache-Control` and a stored `ETag`, so a conditional refetch — which
Googlebot and every social scraper do — costs a 304 without ever loading
the image bytes. YouTube-backed pages 302 to their `i.ytimg.com`
thumbnail, so one card URL shape covers every page.

**Extraction never touches the render path.** A page render only *queues*
work (FastAPI `BackgroundTasks`) — new pages warm at ingest, older ones
the first time anyone loads them. The card route degrades in order: the
exact per-timestamp frame → the page's stored default frame → 404, and a
miss queues the precise extraction so the *next* fetch is exact. A page
only advertises `og:image`/`thumbnailUrl` once a frame is actually stored
(`crud.has_thumbnail()`) — a card URL that would 404 is worse than none,
since validators and scrapers fetch it. At most 2 extractions run at
once, a failing source is retried at most once every 6 hours, and none of
that can delay a response.

**Warming the pages nobody has viewed.** New pages warm at ingest and old
ones warm on first view — which leaves every page nobody has loaded since
2026-08-21 imageless indefinitely. Real dry runs that day measured that
backlog at ~1700 pages. `scripts/backfill_meeting_cards.py` sweeps them:

```bash
python scripts/backfill_meeting_cards.py                  # read-only survey: how many, which hosts, how long
python scripts/backfill_meeting_cards.py --apply          # the real sweep, resumable
python scripts/backfill_meeting_cards.py --apply --max-batches 3   # a bounded first run
```

**It is paced to stay out of the transcription workers' way, and that is
what sets its wall clock.** 996 of those pages (60%) are on
`archive-stream.granicus.com` — the same host the workers pull from
continuously and already hit `ffmpeg timed out after 120s (source likely
slow or rate-limited)` against. So the script does two things instead of
walking the queue newest-first:

* **Proportional interleaving.** The backlog is planned up front and
  reordered so each host's pages are spread evenly across the *whole*
  run (host `h` with `n` of `N` pages gets its `i`-th page at
  `(i + 0.5) * N / n`). Plain round-robin would drain the small hosts
  first and leave the tail as one unbroken Granicus run — exactly the
  pattern this avoids.
* **Per-host cooldowns** — `--host-cooldown` (default 10s) and
  `--granicus-cooldown` (default 30s). Enforced when a batch is composed,
  since the endpoint extracts a batch back-to-back with no pacing of its
  own: at most one page per host per batch, and only once that host's
  cooldown has elapsed. The pacing key is the registrable domain, so ~100
  per-city `*.cablecast.tv` subdomains share one lane and the two
  `*.granicus.com` media hosts share one budget.

At 996 Granicus pages and one per 30s that is a **~8h20m** run, with the
other ~670 pages fitting inside the same window. Deliberate: a slower
sweep that leaves the workers alone beats a fast one that fights them.
Raise `--granicus-cooldown` to go gentler still.

The script drives `POST /internal/thumbnails/backfill`, naming the exact
pages it wants via that endpoint's `slugs` parameter (which is what makes
client-side ordering possible at all), and is safe to Ctrl-C and re-run.
Two different things make resumption work:

* A page that gets a frame **leaves the queue**
  (`crud.list_pages_missing_default_thumbnail()` filters on "has no
  default thumbnail"), so a restart's survey already excludes finished
  work.
* A page whose extraction **fails** leaves no trace in the database, so
  the script remembers those locally
  (`scripts/meeting_card_backfill_state.json`, gitignored) and leaves
  them out of the next plan. That matters for cost, not tidiness:
  `extract_and_store()` runs `probe_duration()` *before* it checks its
  in-process failure cooldown, so re-attempting a dead source costs a
  fresh `ffprobe` every time. Delete that file to give every stuck page
  another chance — a CDN timeout is often transient.

Per batch it reports attempted/stored/failed/skipped, which lanes it
touched, each failing slug with its media host **and ffmpeg's own reason**
for the miss, and an ETA recomputed from observed throughput. The closing
summary groups the stuck pages twice — by media host, and by reason (with
one real example per group) — because those answer different questions:
the host says *which* CDN is unhappy, the reason says whether it is a rate
limit, a dead link, or an offset past the end of the video. Reasons are
bucketed rather than counted raw, since each carries a 300-character tail
of ffmpeg stderr including the media URL.

A result marked `skipped` is kept strictly apart from a failure: it means
the Archive attempted nothing at all (the frame was already in flight,
inside its 6h failure cooldown, or the extraction queue was full), so
those slugs are never written to the local stuck-page file and get
retried on the next run. The raw endpoint is still there for a one-off,
and its non-dry-run results carry `offset_seconds`, `reason` and
`skipped` per slug:

```bash
# Warm default frames for already-archived pages (dry_run defaults true)
curl -X POST -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" \
     "$ARCHIVE_BASE_URL/internal/thumbnails/backfill?limit=10&dry_run=false"

# ...or name exact pages (ignores limit/offset, max 50 per call)
curl -X POST -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" \
     "$ARCHIVE_BASE_URL/internal/thumbnails/backfill?slugs=some-slug&slugs=another&dry_run=false"
```

**`ffmpeg` availability — answered, 2026-08-21**: `ffmpeg 5.1.9` and
`ffprobe` are both really present on the Archive service, confirmed by a
live `GET /api/health` against production. The resolver-side extraction
fallback WO-28 documented in case they weren't is therefore not needed
and was never built. **Present is not the same as sufficient, though
(WO-45, 2026-08-23)**: 5.1.9 cannot read a Cablecast fMP4 VOD playlist
through an input-side seek *at any offset*, which is why 107 archived
pages still have no card — see `BACKLOG.md`'s `[HUMAN]` entry. The
services also run different ffmpeg versions and always have: the Archive
is `runtime: python` (Render's buildpack, 5.1.9) while the transcription
workers are `runtime: docker` off a now-pinned `python:3.12-slim-trixie`
(7.1.5). Check `media_tools` for the service you actually mean. `GET /api/health` reports `media_tools` (the real
`ffmpeg`/`ffprobe` versions on PATH, or `null`).
It's informational and never fails the check — Render gates deploys on
this endpoint, and a service that serves every page but can't generate
new thumbnails is healthy; those pages simply carry no `og:image`, which
is exactly where they were before this feature.

### Rewriting pre-WO-34 transcripts

`dedupe_rollup_cues()` (see "Caption format handling" below) shipped
2026-08-21 and runs on every *fresh* resolve, but nothing re-checks a
stored `TranscriptVersion` — so every page ingested before that date
still serves the duplicated roll-up text it was archived with.
`scripts/dedupe_rollup_transcripts.py` closes that half:

```bash
python scripts/dedupe_rollup_transcripts.py                   # read-only: which pages, with before/after excerpts
python scripts/dedupe_rollup_transcripts.py --slug some-slug  # spot-check one page
python scripts/dedupe_rollup_transcripts.py --apply --from-report scripts/rollup_dedupe_report.json
```

**It never scans the corpus.** No SQL, and no call that aggregates over
`segments` server-side. `GET /internal/pages/all-urls` (one query over
`meeting_pages` only, no join to transcripts) gives the page list; that
list is narrowed client-side to the four platforms WO-34 confirmed serve
roll-up — Granicus, CivicClerk, eScribe, YouTube, which also covers
Legistar/CivicPlus/PrimeGov/Chicago-ELMS pages since `MeetingPage.platform`
stores the *delegated* finder's name — and to pages archived before
2026-08-21. Each survivor is then probed one at a time via its own public
`GET /m/{slug}/transcript.srt` export and scored with the same
`_looks_like_rollup()` detector the fix gates on.

The dry run against production (2026-08-22) takes ~7 minutes:
2,389 pages → 1,163 candidates → **25 still holding roll-up duplication**,
976 clean, 162 with no transcript, 0 probe failures. Those 25 hold 13.8M
stored characters that become 2.5M — 81.9% of the text on them is
duplication. Eleven are Granicus, ten YouTube, two CivicClerk, two eScribe.
Jacksonville FL (`jaxcityc.granicus.com`, CLAUDE.md's named negative
control) came back clean on all eight of its archived pages.

An earlier run the same day reported 1,377 candidates and 26 findings.
The difference is not drift: `crud.list_all_page_urls()` only started
returning `created_at` when that change deployed, so until then the
`--created-before` bound was inert and 214 pages archived *after* WO-34
shipped were probed and cleared rather than excluded up front. The
smaller numbers are the accurate ones.

**Writes go through the normal ingest path**, with a promote after: a
fresh push does *not* become the page's default when the current default
already has segments and a language (`crud._is_real_improvement()`), which
is exactly a roll-up page, so ingest alone would file the fixed transcript
where nobody sees it. Four gates sit between a detection and a write —
the stored transcript must flag, the fresh resolve must *not* flag, the
result must be smaller than the stored one but above `--min-retained`
(default 0.05, against a real measured minimum of 0.066 across those
pages), and the page's own export is re-read afterwards and must come back
clean. Nothing is deleted: the old version stays reachable at
`/m/{slug}?version=<old id>`, and the rewritten one is stored with
`source="deduped"` rather than the ingest default `"scraped"`, so the
version picker can tell them apart — "English (de-duplicated)" against
"English (sourced)", which language and source alone could not do for two
versions of one meeting. That value is a real provenance flag as well as
a label: only `"transcribed"` means AI-generated, and every other source
gets `meeting_page.html`'s third-party disclaimer through a `{% else %}`
fallback (see `TranscriptVersion.source`'s own docstring).

The dry run splits findings by the detector's score. WO-34's 18-file
calibration measured real roll-up tracks at ≥ 0.401 and real non-roll-up
ones at ≤ 0.048 with nothing between; at corpus scale that gap is not
empty, and what sits in it is a coherent cluster rather than noise — 10 of
the 25 score 0.202–0.244 and every one is a YouTube auto-caption track
behind a CivicWeb or Municode portal emitting each speaker-change line as
both `>>` and `»`, retaining ~0.80 of its characters against ~0.07–0.12
for the Granicus ticker shape. Both bands are rewritten by default —
`--min-ratio 0.40` restricts a run to the confident one.

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
| Granicus | `granicus.py` | Regex-scan the page HTML for `.m3u8`/`.mp4` URLs (shared `media_scan.py` helper) | Guessed `/videos/{id}/captions.vtt` path + scanned `.vtt` URLs; language verified from actual cue content (not the untrustworthy `srclang` label); RSS channel title (`ViewPublisherRSS.php`) used for reliable jurisdiction/title. Agenda items (`AgendaViewer.php`'s chapter markers) are fetched independently of transcript availability into their own `agenda_items` field, when that customer has Granicus's native agenda index turned on (not universal — some customers redirect it to their own site instead, surfaced as a plain link instead). Date fallback chain: page text (excluding a "previous meeting" reference, a real confirmed false-positive trap) → RSS item date → Granicus's own published Minutes document (`MinutesViewer.php`, plain HTTP-fetchable, real date at the top) → document-link-filename guess |
| CivicClerk | `civicclerk.py` | Public REST API (`<subdomain>.api.civicclerk.com`) — the portal page itself is a client-rendered SPA with nothing to scrape | `closedCaptionTracks`/`closedCaptionUrl` when populated — real format is **SRT**, not VTT (confirmed live); language verified from actual cue content, same distrust-the-label approach as Granicus. The API's `eventBookmarks` (agenda-item timestamps) are fetched independently into `agenda_items` |
| Swagit | `swagit.py` | jwplayer JSON blob embedded in the page (shares Granicus's CDN infra, but a different page shape) | `.playerControl[data-ts]` agenda-item markers fetched independently into `agenda_items` |
| eScribe | `escribe.py` | `<div id="isi_player" data-client_id data-stream_name>` when present — video integration varies entirely by city, "no video" is a normal outcome here | iSiLIVE captions, keyed by language suffix in the filename (`{file}.vtt`, `{file}.fr.vtt`, ...). Real per-item agenda timestamps from an embedded `video.Bookmarks` JS array, when present — not every item gets one, so items without a match are omitted rather than guessed. `jurisdiction` falls back to the `pub-{city}.escribemeetings.com` subdomain when the page body has no "City of X" phrase — validated against the same Census/StatsCan tables Granicus uses (`jurisdiction_enrich.validated_label_extract()`) before being accepted, declining rather than guessing when nothing validates (gated 2026-08-18; previously an ungated wordninja-split guess, see BACKLOG_DONE.md) |
| California Legislature | `ca_legislature.py` | Self-hosted (`stream.{assembly,senate}.ca.gov`), not a vendor platform | Self-hosted `.vtt` at a matching filename; genuinely high quality when present |
| Legistar | `legistar.py` | Doesn't host video — finds the embedded/redirected link to a platform above (usually Granicus) and delegates via `resolve_via_platform()`. If its own `a.videolink` pattern finds nothing, falls back to a broader link scan (`base.find_platform_link()`, shared with the generic fallback below) before giving up — confirmed live on Baltimore's instance, whose real recording is a plain attachments-table link to YouTube, not the usual pattern. If *that* finds nothing either, a last-resort **city-YouTube-channel match** (`youtube_channel.py`, WO-30) covers the four confirmed instances where the page genuinely has no video to parse — Phoenix, Philadelphia, Baltimore and Albuquerque all publish recordings only to their own YouTube channel, unlinked from Legistar. It enumerates that city's known channel (a curated, human-verified netloc→channel-id dict, never a YouTube search) and matches the meeting's own body name and exact date against the video titles, declining on any ambiguity; a match carries a `video_warning` naming the channel and video it came from, since the meeting page never linked it | Whatever the delegated platform provides — for a channel match, YouTube's own captions |
| CivicPlus | `civicplus.py` | Same delegation pattern as Legistar, from AgendaCenter listing rows | Whatever the delegated platform provides |
| Destiny AgendaQuick | `destinyhosted.py` | Confirmed live 2026-08-21 across 61 real `destinyhosted.com` tenants (enumerated via Wayback CDX — see BACKLOG_DONE.md) to be a pure agenda/minutes CMS, not a video host — delegates to `GenericFallbackAssetFinder`'s own tiers unchanged (a thin wrapper, not a redundant parser), only claiming the `"destinyhosted"` platform identity itself when nothing deeper resolves. Registered as its own platform (rather than left as `"unknown"`) specifically so `base.find_platform_link()` follows a `destinyhosted.com` link found on some *other* wrapper's page as a real one-more-hop delegation target — confirmed necessary live: Roswell, NM runs CivicPlus's AgendaCenter self-hosted on its own domain rather than `*.civicplus.com` (so `detect_platform()`'s civicplus check never fires) and links straight to a `destinyhosted.com` backend. 18/61 sampled tenants have a real, confirmed Swagit video link — via a formal built-in AgendaQuick↔Swagit integration, `onclick="swagitPlay('https://...')"` rather than a plain href — some others use YouTube/Granicus/Cablecast-Castus/other vendors, several have none this month (a real per-tenant negative, not a gap) | Whatever the delegated platform provides |
| PrimeGov | `primegov.py` | Doesn't host video itself. Prefers a plain JS variable (`var videoUrl = "..."`) directly in the page HTML when present, delegating to YouTube — but some tenants' real video is actually hosted on Swagit or Granicus instead, with no trace of it in the page HTML at all (confirmed live 2026-08-19, see BACKLOG_DONE.md). When no YouTube id is on the page, falls back to the tenant's own `GET /api/v2/PublicPortal/ListArchivedMeetings?year={YYYY}` API, matching the page's `meetingTemplateId` against `documentList[].templateId` to find that meeting's real `videoUrl`, then delegates to whichever adapter matches. Every delegation path preserves the original PrimeGov URL as `source_url` (unlike the Legistar/CivicPlus delegation pattern) | Whatever the delegated platform (YouTube, Swagit, or Granicus) provides |
| YouTube | `youtube.py` | No direct video file URL exists (unlike every platform above) — playback is an embedded iframe + the YouTube IFrame Player API, not the native `<video>`/hls.js pathway. Handles a direct `youtube.com`/`youtu.be` URL too, not just PrimeGov delegation | yt-dlp (plain HTTP requests to YouTube's caption endpoints are blocked — see BACKLOG.md); prefers a manual/CC track over auto-generated only when its coverage is comparable, since a manual track can start well into the video and skip pre-meeting dead air |
| Viebit | `viebit.py` | Reached via Legistar delegation (confirmed so far only under NYC Council's instance) — a `var pageConfig = {...}` JS object embedded in plain HTML gives a real HLS `master.m3u8` URL, no JS execution needed for discovery. **Playback is an iframe embed** (`/embed/vod?v={id}&t={seconds}`), not the native `<video>`/hls.js pathway every other platform above uses — confirmed live 2026-08-12 that the raw `master.m3u8` 403s from a CDN-level Referer/Origin check, and that no `postMessage`-reachable seek API exists in Viebit's own player bundle (`lgx-videojs-plugins-*.js`/`vod-embedded-*.js`, pulled and read directly). `t=` is read by the iframe only at load time, so "seeking" after playback has started means reloading the iframe with a new `t=` — `wireSharedControls(adapter, { liveTracking: false })` degrades live-position-dependent UI (playhead tracking, "currently playing" highlight, play/pause control) honestly instead of faking it, a deliberate, user-confirmed tradeoff | Real, populated VTT captions from the same `pageConfig`; two-line rolling-caption shape, collapsed by `dedupe_rollup_cues()` (see "Caption format handling" below — that function was rewritten in WO-34 to handle four real roll-up shapes; this track's output is byte-for-byte unchanged by that rewrite apart from one segment it now de-duplicates correctly) |
| Minneapolis LIMS | `lims.py` | **The one adapter that isn't plain `aiohttp`** — both the agenda page and its `/MeetingYoutubeVideo/{id}` JSON endpoint return a genuine Cloudflare JS challenge to a normal HTTP request, so this uses `headless_browser.py`'s real (headless) Chromium fetch instead. Delegates to YouTube for the video itself | Whatever YouTube provides, via delegation. Real per-agenda-item timestamps from the JSON endpoint's `SerializedVideoTimestamps` tree — genuinely richer than most platforms above, since most don't have real per-item start times at all |
| Salt Lake City meeting recaps | `slc.py` | Also Cloudflare-gated (same `headless_browser.py` fetch as LIMS above) — scoped to `slc.gov/council/*-meeting-recap/` pages specifically. **Not multiple distinct videos per page** (confirmed live across four real pages, see BACKLOG_DONE.md) — one video, several manually-curated `t=` timestamp links into it, turned into `agenda_items` the same way LIMS's structured data is | Whatever YouTube provides, via delegation |
| Aurora, CO (auroratv.org) | `aurora.py` | Confirmed live 2026-08-12. Parses the page's own embedded Drupal `<script data-drupal-selector="drupal-settings-json">` blob for `jw_data`'s real `mp4_url` — already-supported `video_format="mp4"`, no frontend changes needed. A real early mistake worth flagging: the blob's top-level `video_caption` field looks like the caption URL but is actually a server filesystem path (`/home/atowntv/public_html/...`); only found by resolving and seeing 0 segments despite the real file curling fine directly, not by reading the schema | `jw_data.caption_file_path`, a real fetchable URL unlike the sibling field above |
| CivicWeb (iCompass/Diligent) | `civicweb.py` | Confirmed live 2026-08-12 to be a YouTube-delegating platform, not a video host of its own — its "Video" tab embeds a plain YouTube iframe. Delegates straight to `YouTubeAssetFinder.resolve_video_id()` (the PrimeGov pattern: original CivicWeb URL preserved as `source_url`, `platform` stays `"youtube"`) | Whatever YouTube provides. One real gotcha: `/api/videolink/{id}` is **double-JSON-encoded** — a first `.json()` parse yields a Python `str`, not the list it looks like; `_fetch_json()` re-parses if that happens |
| Cablecast | `cablecast.py` | Confirmed live 2026-08-12 on Detroit's Cablecast portal, then confirmed 2026-08-13 that Charlotte, NC's real `/internetchannel/show/{id}` pages use the exact same Remix.js SSR template (all data, including a ~35-item "related shows" carousel, embedded in one `window.__remixContext` JSON blob) — one adapter, two confirmed real customers so far, **still deliberately not a general `*.cablecast.tv` rule** given Cablecast is a multi-tenant product and an unconfirmed customer could use a different template. Jurisdiction is derived per-customer (see `_extract_jurisdiction()`), not hardcoded. Real quirk: Detroit's portal HTTPS hangs indefinitely for the whole domain (15s+ confirmed via direct curl) — `resolve()` always fetches over plain HTTP regardless of the scheme pasted, matching how Detroit's own city site (detroitmi.gov) actually links it. The real video is a direct, unauthenticated `.m3u8` on a separate `reflect-detroit-vod.cablecast.tv` subdomain (HTTPS works fine there), already fully supported by the existing hls.js pathway | `vodTranscripts` was empty on every one of 36 Detroit shows checked, but a real, populated, fetchable entry was found on a Charlotte show (`show/2451`) — a plain-text transcript file, parsed directly (`_parse_transcript()`), not through the shared VTT dispatch |
| CHAMP/ChampDS | `champds.py` | Confirmed live 2026-08-13 against 6 independent real customers via a plain, unauthenticated JSON API (`playapi.champds.com/{customer}/event/{id}`). Only the direct-MP4 `MediaInfo.DownloadURL` case is wired up to play (2 of 6 customers) — the majority-case `VOD2` HLS URL is deliberately withheld even when present, since it's gated by a strict `Referer: https://play.champds.com/` check this site can't satisfy (confirmed live via direct `curl`) | Agenda-only: `Agenda.Attachments`, preferring a `.pdf`-shaped one. No real captions confirmed on any of the 6 customers checked |
| IQM2 | `iqm2.py` | Confirmed live 2026-08-13 against Atlanta, GA — doesn't host video itself; a past meeting's real "Video" link carries a plain static `onclick="OpenWindow('/Citizens/SplitView.aspx?Mode=Video&MeetingID={id}...')"` (a future/no-recording meeting's link stays a bare unpopulated placeholder, the signal used to tell the two apart), and that page's raw static HTML carries a literal `<!-- MEDIA URL: ... -->` HTML comment with a direct Granicus HLS URL — no JS execution needed, a plain `curl` sees it, though the stream URL itself needs a real (non-default) User-Agent. Santa Clara County, CA is a second real confirmed customer — smaller commissions/committees checked there often have no video link populated, but its flagship Board of Supervisors meetings do (confirmed live 2026-08-14), so this is a real body-type-dependent gap on that instance, not a limitation of this adapter | Real per-item timestamps: the same per-meeting page, requested with `Target=Detail&CssClass=AgendaOutline&Mode=Video&Frame=Nothing`, renders every agenda item as a real `SetPosition({seconds})` onclick alongside the actual item text (procedural entries and full ordinance/resolution text alike) |
| ClerkBase (clerkshq.com) | `clerkbase.py` | Confirmed live 2026-08-14 against one real customer (Yellow Springs, OH) — doesn't host video itself. The landing page's static HTML (no JS execution needed) embeds the real agenda-document URL and title as plain JS variables (`window.autoOpenDocUrl`/`autoOpenDocTitle`); that document (a raw MS Word HTML export, also directly linkable on its own) embeds the video as an `opengovideo.com` wrapper link straight to a YouTube embed — delegates to `YouTubeAssetFinder`, `platform` stays `"youtube"` (same PrimeGov/CivicWeb pattern). Jurisdiction comes from the URL's own `{Name}-{ST}` client-site slug (a ClerkBase product convention), not page text | Whatever YouTube provides. Only one real customer checked so far — a second sample would confirm how general the landing-page/document-page shapes really are |
| TelVue | `telvue.py` | Confirmed live 2026-08-16 against a real Ashland, OR Planning Commission meeting on `videoplayer.telvue.com` (also reachable via a `peg.tv` shortlink, a plain HTTP redirect to the same page — no separate platform). Everything needed is a plain JSON `Player.setupData['playlist']` array embedded in the static HTML, no JS execution needed — a real `file:` HLS URL plus a `tracks:` list | Real captions confirmed present and high-quality on the one sample checked — WebVTT with `<v Speaker N>` voice tags, stripped by a TelVue-specific regex (`parse_vtt()` doesn't strip these on its own). A separate `chapters.vtt` track gives real start/end agenda-item ranges |
| Seattle Channel (seattlechannel.org) | `seattlechannel.py` | Confirmed live 2026-08-14 against two independent real meetings, scoped narrowly to the `/videos?videoid={id}` URL shape (the older feed-style index page and a bare `/videos` with no id are deliberately left to `generic_fallback.py`). The primary video's JW Player instance is always the fixed element id `vidPlayer` — HTML is sliced to that specific block, bounded by the following `.on('complete', ...)` call, so an unrelated "related video" embedded further down the same page is never picked up by mistake | Real SRT captions, plus real per-item `data-seek` timestamps from `<a class="seekItem">` elements, turned into `agenda_items` |
| Hyland "OnBase Agenda Online" | `hyland.py` | Confirmed live 2026-08-16 across 26 real customer domains, spanning two distinct real UI versions of the same vendor product. Version A's separate `/Meetings/ViewMeetingAgenda` endpoint and Version B's `/Documents/ViewAgenda` endpoint (a converted-Word-document render) are both plain server-rendered HTML, no JS execution needed — `resolve()` tries Version A first and falls back to Version B only when that yields nothing. Falls back to `YouTubeAssetFinder` delegation when no direct JW Player media file is found (one real customer's page uses a YouTube embed instead) | Real timestamped `agenda_items` on customers with video: each version's own agenda outline embeds a `loadAgendaItem({id})` link per item, joined against the main page's inline `itemEventPoints` video-seek-offset map on that same id. No caption/transcript track of any kind has been found on any JW-Player-backed customer — only the YouTube-delegated one has a real transcript |
| Town Hall Streams (townhallstreams.com) | `townhallstreams.py` | Confirmed live 2026-08-20 against 7 real towns — a plain `jwplayer(...).setup({file: "..."})` call in static HTML embeds a directly-fetchable HLS URL (no Referer/Origin gating, confirmed via direct `curl`), no JS execution needed. The page itself carries no jurisdiction/title/date text at all — everything comes from the video URL's own path, `mp4:{town_slug}/{date}_{numeric_id}_{Meeting_Title}.mp4`. Jurisdiction is routed through the shared, Census-validated `jurisdiction_enrich.validated_label_extract()` (never a by-eye slug decode — 2 of 7 real slugs carry zero state information at all, see BACKLOG_DONE.md), with a `wordninja`-split check of the slug's own trailing token for a real state abbreviation, falling back to a Census unambiguous-name lookup | A real `get_transcriptions` AJAX endpoint exists but returned empty on all 7 real meetings checked — treated as best-effort/unconfirmed per this repo's convention: a genuinely non-empty response is surfaced as a `transcript_warnings` entry (not silently dropped, and not guess-parsed) since no real positive example has been found yet to build an actual parser against |
| open.media (`{tenant}.open.media`) | `openmedia.py` | Confirmed live 2026-08-21 across 7 real tenants (Goodyear AZ, Eugene OR, Cortez CO, Santa Barbara CA, Surprise AZ, Georgetown CO, Pitkin County CO) — a YouTube-delegating platform, doesn't host video itself. Requires a modern desktop Chrome User-Agent (a bare/default UA 403s — same class of bot-check gap as `generic_fallback.py`'s own cityofsebastopol.gov fix). The visible player iframe is injected client-side and invisible to a plain fetch, but every tenant checked also carries a real `<meta property="og:video">` tag in the raw, un-rendered HTML pointing at the same video (`youtube.com/v/{id}` or `youtube.com/live/{id}`) — already a shape `YouTubeAssetFinder`'s own regex recognizes, so no headless-browser fetch is needed. Delegates to `YouTubeAssetFinder.resolve_video_id()`, original open.media URL preserved as `source_url` (the PrimeGov/CivicWeb pattern) | Whatever YouTube provides. Title comes from the page's own `og:title` (plain meeting title, no date suffix, independent of whether yt-dlp itself is blocked) rather than YouTube's metadata. Jurisdiction comes from the pre-pipe half of `<title>` ("{Jurisdiction} \| {Meeting title}" — the reverse order from `generic_fallback.py`'s own CRRMA-shaped title parsing, so that shared helper isn't reused here), falling back to the tenant subdomain itself (run through the same Census-validated `jurisdiction_enrich.validated_subdomain_extract()` eScribe/Granicus use) when the tenant has never customized its `<title>` away from the vendor's own default — confirmed real and live on Cortez, CO. Agenda comes from a `<iframe id="document">` present on every tenant checked — either a direct link to another already-registered platform (Goodyear links straight to a destinyhosted.com AgendaQuick page) or this tenant's own pdf.js viewer wrapping a direct S3-hosted PDF as its `?file=` query param (Eugene/Cortez/Santa Barbara/Surprise), unwrapped to the raw PDF URL |
| Castus (cloud.castus.tv) | `castus.py` | Confirmed live 2026-08-21 (WO-19) against one real customer (Billings, MT's "comm7tv" channel). The static page is a pure JS-redirect shell into a client-rendered React SPA — no headless browser needed, though: the SPA's own webpack bundles were fetched once and read directly, surfacing a plain, unauthenticated `POST .../upload/info {"file": videoId}` API that returns everything needed for one video (title/duration/readiness flags/an embedded `agenda` array) from a global endpoint shared by every tenant, plus a global CloudFront CDN (`outputs/{id}/Default/HLS/out.m3u8`) for the HLS video itself. Also solves the tenant-slug → internal-channel-id mapping this platform's first investigation pass had flagged as unsolved (see `castus.py`'s own module docstring for the endpoint, unused by this adapter but documented for a future per-tenant feature) | Real, populated AWS-Transcribe-style VTT (`captions/{videoId}.vtt` on the same CDN) with per-word confidence/speaker inline tags — `parse_vtt()`'s existing generic tag-stripping already handles this shape with no Castus-specific code. Real per-item `agenda_items` come from `/upload/info`'s own embedded `agenda` array (a separate `api.castus.tv/ccs/v1/agenda/{id}` endpoint returns the same data independently but isn't called, to save a request). Jurisdiction is cross-checked by fetching whichever destinyhosted.com page an agenda item's own hyperlinks point at (Destiny Software's AgendaQuick — real "City of Billings" text confirmed live), with a small known-tenant map filling in the state where the page's own ZIP isn't a real Census-covered ZCTA; falls back to a best-effort tenant-slug parse otherwise (unconfirmed against any real second example) |
| SuiteOne Media (suiteonemedia.com) | `suiteone.py` | Confirmed live 2026-08-21 across 6 real tenants (`pacificgroveca`, `lorainoh` from a prior investigation, plus `tuscaloosaal`, `camaswa`, `holladayut`, `stmarysga` newly confirmed live this session; 5 other CDX-derived leads — `mcallentx`, `southbendin`, `prescottaz`, `richlandwa`, `laytonut` — 404 and aren't registered). A plain, static-HTML JW Player setup embeds a direct, unauthenticated S3 mp4 (`var src = '...'` — genuinely empty when a meeting has no recording yet, confirmed on a real St Marys, GA event, not a parse failure). Jurisdiction reuses `jurisdiction_enrich.validated_label_extract_with_state()` directly plus the same wordninja-last-token state check `townhallstreams.py` established. The 2 tenants that originally couldn't resolve at all (`stmarysga`, `camaswa` — wordninja mis-splits their trailing state letters into a non-word chunk) were fixed 2026-08-21 in the shared module itself, not here: its new tier-5 strip removes a trailing state/province code from the raw label *before* wordninja sees it, and this adapter asks that module for the code it stripped rather than re-deriving it (the raw trailing letters aren't trustworthy on their own — "tacoma" ends in a real state code too). Both now resolve correctly ("St Marys, GA", "Camas, WA") — see `suiteone.py`'s own module docstring and BACKLOG_DONE.md | Real, populated WebVTT at a JW Player `tracks[].file` URL (`/Event/GetCaptions/?eventId={id}`, no file extension — parsed directly as VTT rather than through the usual extension-sniffed dispatch) — confirmed on 2 of the 6 tenants (Pacific Grove CA, Holladay UT); omitted entirely (not an empty array) when a meeting has none. A separate `/event/GetAgendaFile/Agenda?aid={N}` PDF embed, confirmed on 3 of 6 sampled events, is surfaced as `agenda_link` |
| Vimeo | `vimeo.py` | Not a civic-video vendor — a general-purpose host that a real, confirmed set of small local governments use directly, built 2026-08-21 (WO-29) against 8 named jurisdictions. **Playback is an iframe + Vimeo's own Player SDK**, not the native `<video>`/hls.js pathway: no direct media file URL exists (see captions column). Unlike Viebit's iframe, this one gets the *full* `wireSharedControls()` treatment with live playhead tracking, because Vimeo's postMessage API was verified live against a real **showcase** embed before any code was written (`ready`/`getDuration`/`setCurrentTime`/`getCurrentTime`/`play`/`timeupdate` all real) rather than assumed. Metadata comes from Vimeo's public, unauthenticated **oEmbed** endpoint (`vimeo.com/api/oembed.json`), which a plain `aiohttp` GET can reach; it rejects showcase URLs, so every shape is normalized to `vimeo.com/{id}` first. Six real URL shapes handled, including the privacy-hashed `vimeo.com/{id}/{hash}` (the hash must ride along on the embed URL or the player refuses). `detect_platform()` deliberately does **not** claim the bare domain — a city's `vimeo.com/cityname` footer link is a real false-positive class — only shapes with a real video id plus the two listing shapes | **No captions, and that's a wall, not an omission.** Real populated English WebVTT does exist on some meetings (confirmed via a real browser on Salisbury NC) but only behind a signed `captions.vimeo.com/...?expires=&sig=` URL that appears solely inside `player.vimeo.com/video/{id}/config` — which returns **403** to every non-browser client. The same signed response holds the only real media file, so on-demand Whisper audio is blocked by the identical wall, not a second one (see BACKLOG.md). A `transcript_warnings` line says so and points at the player's own CC button. `/showcase/{id}` and `/channels/{name}` listing pages return a real `calendar_page` pick-list instead, parsed from a server-rendered JSON-LD `ItemList` (a bare `vimeo.com/{username}` page genuinely is client-rendered and is left to `generic_fallback.py`). Jurisdiction comes from the oEmbed account name run through the shared Census-validated check, which usually and correctly declines |
| Chicago City Clerk ELMS | `chicago_elms.py` | Confirmed live 2026-08-21 (WO-29) against 5 real meetings spanning 2020–2026. A single-city platform, not a vendor product. The meeting page's raw HTML has **zero** mention of its video — it's injected client-side — so everything comes from the public, unauthenticated `api.chicityclerkelms.chicago.gov/meeting-agenda/{meetingId}` JSON API (`meetingId` is a GUID off the portal URL). `videoLink` is a real Vimeo URL in both showcase styles; delegates to `vimeo.py` while keeping the ELMS URL as `source_url` and re-asserting its own `platform` (the PrimeGov/CivicWeb pattern, plus an attribution fix so `/coverage` shows a real Chicago row) | Agenda **link** only. `transcriptLink` is in the API schema but empty on all 5 real samples; a populated one would be surfaced as a warning, never guess-parsed. **`agenda.groups[].items[]` is rich (473 real items on one sample: matter title, action taken, vote type) but carries no timestamps at all**, so `agenda_items` is deliberately left empty rather than fabricating offsets — Chicago pages have a working agenda PDF link but no clickable agenda items, unlike LIMS/Hyland/IQM2. Tracked as a real gap in BACKLOG.md |

**Every URL `detect_platform()` doesn't recognize** goes to
`generic_fallback.py`'s `GenericFallbackAssetFinder`, registered under
`platform_name = "unknown"` — rebuilt 2026-08-14 (see `BACKLOG_DONE.md`
for the full build, backtested against every real coverage-gap example
in `BACKLOG.md`) as a *diagnostic router*: figure out what the page
needs, then hand off to machinery that already exists. Video tiers, in
order: (1–2) an embedded YouTube video in any confirmed shape — a
URL-shaped id (raw or HTML-entity-escaped, youtube-nocookie included),
or a bare `videoId = '...'` JS assignment gated on the page actually
loading the IFrame Player API (Tarrant County's real shape) — delegated
to `YouTubeAssetFinder`; (3) a link to any OTHER platform this app fully
supports, delegated to that adapter's own `resolve()` — either a plain
`<a href>`/`<iframe src>` (Austin, TX → Swagit, confirmed live
2026-08-10) or an `onclick="someFunc('https://...')"` JS-modal link with
no real href at all (`base.find_platform_link()` checks both — see
`destinyhosted.py`'s table row below for the confirmed real example);
(4) a directly playable media URL
via `media_scan.py`'s shared scanner (which handles query-stringed
m3u8s, HTML-entity-escaped URLs, JW Player `file:` config keys, and
protocol-relative/relative paths — the Sacramento/Seattle shapes);
(5) when nothing playable exists, a **video pointer** —
`ResolvedMeeting.video_link` — "we think the video is here: `<link>`",
with two confidence tiers of copy: a curated known video host (Vimeo
video/showcase links) gets "we recognize {host} as a regular video
host", a looser video-shaped guess (a "Video"-texted anchor, a non-junk
third-party player iframe) gets "we don't recognize {host}... so
proceed with caution". Note that as of 2026-08-21 (WO-29) a Vimeo link
usually never reaches this tier at all — Vimeo is a fully supported
platform now, so tier 3 above delegates to its real adapter and produces
an actually playable video instead (confirmed live on Sebastopol, CA).
The curated tier survives for the Vimeo shapes `detect_platform()`
deliberately doesn't claim, and as the pattern for whatever unsupported
video host shows up next. Captions come from their own candidate chain
(`<track>` elements, plain caption-file `<a href>`s, JW `tracks:`
entries, scan results); metadata from a breadth of confirmed-real
shapes (title-tag separators, og:title, h1 assembly, `video_date`
meta, `<time datetime>`, heading dates, URL-slug humanization as last
resort) — every extractor only fills still-empty fields. The agenda
link finder is unchanged: a single best-effort `<a>`, never fabricated
`agenda_items`.

Blocked fetches escalate to the real headless-browser fetch
(`GENERIC_FALLBACK_HEADLESS=1` — **enabled in production** since
2026-08-14, the same day playwright-on-Render was finally verified
working for real; see `render.yaml`'s env-var comment for the
evidence): a block-family status (Wayne County MI's real Akamai 403),
a small challenge-interstitial body, or an empty-evidence resolve of a
client-rendered shell triggers at most one Chromium retry, whose
rendered HTML re-runs the same diagnosis — end-to-end confirmed in
prod against the previously fully-Akamai-blocked Wayne County page,
which now resolves with real video/title/jurisdiction/date/agenda. Dedicated adapters can also
opt into the same page-analysis tiers as a backstop when their own
extraction found no video (`scan_page_for_video_evidence()` — eScribe
is wired in; opt-in per adapter only, since a blind second pass on a
page carrying other meetings' videos could attach the wrong one).

Every fetch this adapter makes — the initial page load, a caption URL
found on that page, and the headless-browser escalation above (including
every redirect and sub-resource request the browser itself makes) —
passes through `app/utils/url_guard.py`'s SSRF guard first: an
`http`/`https` scheme allowlist, rejection of private/loopback/link-local/
reserved destinations re-checked on every redirect hop (not just the
entry URL), and a response-size cap. `/api/resolve` itself rejects a
blocked URL immediately, before any adapter — including this one — ever
runs. See that module's docstring for the real gap this closes.

Every result from this adapter (including when it delegates to
`YouTubeAssetFinder`, whose own `platform` field stays `"youtube"`) sets
`ResolvedMeeting.best_effort = True`, which drives a dedicated, openly
tentative UI on the meeting page (`app/static/player.js`): a full-width
"we're trying our best" banner, plain "we think the video/agenda is
here: `<link>`" lines instead of a declarative warning box, and a manual
timestamp-entry box in place of the live playhead-tracking reader other
platforms get (deep-link reliability isn't confirmed here, so there's no
adapter-driven "current time" to honestly display). The **video** line
specifically is only rendered when there's no playable video to show
(`renderBestEffortVideoPointer()`, WO-43, 2026-08-22): a real
`video_url` means the embedded player right below it is already the
answer, and that URL is always a machine artifact rather than a page a
human would open — a Vimeo/YouTube embed shell or a raw CDN media file
(all three confirmed live). The link a reader actually wants, the city's
own page, is the "View original source" line above it, which
`_try_delegate_to_known_platform()` deliberately resets back to the city
page after delegating. The two informative variants stay: the tier-5
`video_link` pointer, and a plain "[No video found]" when nothing turned
up at all.

Since 2026-08-21 that flag also survives the push to the Archive
(`meeting_pages.best_effort`), where it does two things: it disqualifies
the page from social auto-posting entirely, and it lists the page in
`GET /internal/low-trust-pages` for review. It deliberately does *not*
affect indexing, the sitemap, or hub listings — see `BACKLOG.md`. Note
the flag, not `platform`, is the signal to check anywhere this matters:
a fallback resolve that delegates to `YouTubeAssetFinder` reports
`platform = "youtube"`, and that's the most common real case.

**Not implemented**: BoardDocs (deliberately excluded — it's a
document/agenda platform with no reliable video, not worth an adapter).

**Caption format handling** is centralized in
`app/utils/vtt_parser.py`'s `parse_captions_by_extension()`, used by
Granicus/CA Legislature/Swagit/CivicClerk/Aurora/Seattle Channel and the
generic fallback instead of each reimplementing its own format detection.
It's also where **roll-up ("scrolling ticker") caption reconstruction**
runs, via `dedupe_rollup_cues()` — roll-up captioning is a property of how
a *city* captions its meetings, not of which platform hosts the video, so
wiring it per-adapter (as it was until WO-34, 2026-08-21) is what left
Granicus/CivicClerk/eScribe serving visibly duplicated transcripts while
YouTube and Viebit were fine. Four real cue shapes are handled, each
confirmed against a live-fetched file and kept as a fixture; a track that
doesn't look roll-up is returned untouched, which is what makes it safe to
run from a shared dispatch. eScribe parses VTT directly rather than
through this dispatch, so it calls `dedupe_rollup_cues()` itself.

**That fix is resolve-time only, so already-archived pages need a
sweep.** Nothing re-checks a stored `TranscriptVersion` on its own, so
every page ingested before 2026-08-21 still serves the text it was stored
with. `scripts/dedupe_rollup_transcripts.py` finds those pages and
rewrites them — see "Rewriting pre-WO-34 transcripts" above.

VTT and SRT are real, structurally-parsed formats, confirmed
against real samples on multiple platforms. TTML/DFXP/ITT also get a real
structured parser, but — unlike VTT/SRT — that's verified against the
W3C spec only, not any real captured sample (see `BACKLOG.md`). SBV/SUB/
SMI/SAMI/plain-`.txt` get a generic best-effort text extraction with no
per-line timing (`t=` deep-linking to the video never depended on
transcript timing anyway). SCC/STL (binary/encoded broadcast formats) are
detected but link out rather than attempting to display content, since
nothing can be extracted without real codec-level decoding.

**Platform coverage research**: this app supports a platform once and
every city on it works, so the actual bottleneck to growing coverage is
finding real, live samples of platforms it doesn't handle yet — per
this file's own "never build an adapter from assumption" convention.
A 2026-08-11 survey of the largest US cities/counties by population
(cross-checked against what's already live in the Archive) produced a
[filterable results table](https://claude.ai/code/artifact/2951935f-c5ca-4caa-b74e-b2ac2b7a6d1c)
of every jurisdiction checked — platform, rough population, and sample
URLs, split into "real coverage gap" vs. "already-supported pattern,
just not yet resolved." It's hosted as a private Claude artifact, not
version-controlled with the rest of this repo, so treat it as a
point-in-time research snapshot rather than a durable source of truth —
the concrete, actionable findings that came out of it (Phoenix's
Legistar-never-has-video pattern — **closed 2026-08-21 by WO-30's
city-YouTube-channel fallback, see the Legistar row above**, along with
the same pattern on Philadelphia, Baltimore and Albuquerque —
Chicago ELMS's now-unblocked API
samples, new unsupported vendors like Cablecast/IQM2/CivicWeb, etc.)
were folded into `BACKLOG.md`'s "Platform & jurisdiction coverage" and
"Dormant" sections at the same time, which are the durable record to check
before starting adapter work. Four of that survey's items (Cablecast/
Detroit, Aurora, CivicWeb, Viebit) were picked up and actually shipped
2026-08-12 — see the "Supported platforms" table above for what's real
in code today, and the artifact's own "Shipped since this survey"
section (added the same day) for two real corrections the
implementation work turned up in the original research (Cablecast isn't
one uniform template across cities; Detroit's own portal domain hangs
over HTTPS but works over plain HTTP).

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
                           /admin/*, /robots.txt, the /m/*,
                           /archive-static/*, /meetings, /account/saved,
                           /coverage, /state/*, /sitemap.xml, /feed.xml
                           Archive proxy routes,
                           /api/newsletter/signup, /unsubscribe, the
                           accounts routes (/api/account/*,
                           /api/clerk/webhook) and their three
                           lifecycle-triggered emails -- see "Accounts
                           (Clerk)" above
  archive_client.py        lookup()/push() to the Archive + proxy_get()
                           (cookie-forwarding for auth-aware pages) +
                           the /internal/account/* wrappers
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
                           formats, parse_captions_by_extension() --
                           the single dispatch point every caption-
                           fetching adapter goes through (see "Supported
                           platforms"'s "Caption format handling" note) --
                           dedupe_rollup_cues() for roll-up captions, and
                           detect_language_from_texts(), which votes
                           across the whole transcript rather than
                           sampling its opening
  utils/url_normalize.py   normalize_url() — the cache/log dedup key
  utils/clerk_auth.py      get_clerk_user_id()/clerk_frontend_api_url() --
                           see "Accounts (Clerk)" above; deliberately
                           duplicated in archive/utils/clerk_auth.py
  templates/base.html      shared layout (nav, brand, manifest/favicon
                           link, Clerk sign-in link/nav slot)
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
  main.py                 FastAPI app: /internal/lookup, /internal/ingest,
                           /internal/transcription/* (all token-gated),
                           /m/{slug}, /m/{slug}/transcript.{txt,srt},
                           /m/{slug}/card.jpg (see "Meeting card images"
                           above),
                           /meetings, /coverage, /state/{slug}, /j/{slug},
                           /sitemap.xml, /feed.xml,
                           /api/health, /account/saved, and the token-gated
                           /internal/account/* routes -- see "Accounts
                           (Clerk)" above
  db/
    engine.py              own DATABASE_URL resolution + local SQLite
                           fallback (archive_dev.db -- never shares the
                           resolver's dev.db)
    models.py               MeetingPage, TranscriptVersion,
                           MeetingPageUrlAlias, TranscriptionJob (see "On-
                           demand transcription" above), SavedItem (see
                           "Accounts (Clerk)" above),
                           MeetingPageThumbnail (extracted video frames,
                           see "Meeting card images" above)
    crud.py                  identity matching/dedup, slug generation,
                           content-hash version dedup, list_pages()
                           (paginated + filtered, backs /meetings),
                           get_platform_coverage()/get_jurisdiction_coverage()/
                           get_full_jurisdiction_coverage() (all back
                           /coverage's three sections),
                           get_state_coverage_index()/get_state_page_data()
                           (back /state/{slug} + /coverage's state links),
                           get_jurisdiction_hub_data()/
                           list_indexable_hub_entries() (back /j/{slug} +
                           its sitemap entries),
                           list_all_page_slugs() (backs /sitemap.xml),
                           list_recent_pages_for_feed() (backs /feed.xml),
                           the TranscriptionJob lifecycle (create/claim/
                           report/confirm/finalize),
                           promote_transcript_version(), and the saved-
                           items functions (save/unsave meeting/search,
                           list_saved_items, delete_account_data -- the
                           right-to-deletion cascade)
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
    language.py              same deliberate-duplicate pattern, of
                           app/utils/vtt_parser.py's
                           detect_language_from_texts() -- used to detect
                           a transcribed version's language (see "On-
                           demand transcription" above)
    email.py                  Resend integration: transactional sends
                           (confirmation, transcription-complete,
                           transcription-failed) and an
                           audience-membership check -- see "On-demand
                           transcription" and "Accounts (Clerk)" above
    clerk_auth.py             deliberate duplicate of
                           app/utils/clerk_auth.py -- see "Accounts
                           (Clerk)" above
    video_thumbnail.py       which frame a meeting card shows and the
                           background extraction that produces it, plus
                           the free i.ytimg.com URL for YouTube-backed
                           pages -- see "Meeting card images" above
    clips.py                  schema.org Clip entries out of stored
                           agenda_items, including the endOffset
                           resolution for a run of items sharing one
                           source timestamp
  templates/
    meeting_page.html        SSR permanent page + transcript-version
                           picker (real content on first byte, for
                           crawlability -- not client-fetched JSON like
                           app/templates/meeting.html); also carries the
                           schema.org VideoObject JSON-LD block, the
                           "Report a problem" form, and the "Save this
                           meeting" button/bookmark icon
    meeting_list.html         paginated index + search/filter form, an
                           RSS autodiscovery link, and the "Save this
                           search" button
    saved_items.html          "My Saved Items" page -- see "Accounts
                           (Clerk)" above
    coverage.html              per-platform table + real example page
                           links, backs /coverage
    sitemap.xml.jinja         sitemap.xml template
    feed.xml.jinja            feed.xml (RSS) template
  static/style.css          duplicated from app/static/style.css
  static/meeting_page.js    trimmed port of player.js's seek/highlight
                           logic, wired onto already-rendered DOM, plus
                           the Save-this-meeting toggle
  static/saved_items.js     unsave-button handlers on the saved-items page
```

`shared_static/` holds the handful of JS files identical between the
resolver and Archive — both services mount it at `/shared-static` and
serve the exact same files, rather than each keeping its own copy:

```
shared_static/
  deep_link.js              the t=/line=/version= deep-link contract both
                           app/static/player.js and
                           archive/static/meeting_page.js depend on --
                           see "Running tests" above for its own JS suite
  clerk_nav.js               loads ClerkJS, mounts the nav sign-in
                           link/user avatar, exposes window.RTRClerk --
                           see "Accounts (Clerk)" above
```

`worker/` is a third, independent service (own `requirements.txt`, own
Docker-based deploy — see "On-demand transcription" above) for processing
transcription jobs — it can run as more than one Render service from this
same codebase (`rtr-transcription-worker` / `rtr-transcription-worker-2`
in `render.yaml`) sharing one job queue, see that file's own comment.
Unlike the resolver/Archive split, it deliberately imports from both of
the other two: `archive.db`/`archive.utils.email` directly (it *is*
Archive backend logic, just in a process shape the Archive's own web dyno
can't offer) and `app.platforms` (read-only, to re-resolve a fresh media
URL before each chunk).

```
worker/
  main.py                  the poll-claim-process loop; loads the
                           transcription model once at startup, reused
                           for every job/chunk after that
  transcription_engine.py   TranscriptionEngine interface + the real v1
                           implementation, self-hosted faster-whisper
  media_probe.py            -- lives in app/platforms/, not here, so
                           app/main.py's feasibility check can use it too
                           without app/ depending on worker/; see that
                           file's own docstring
  segment_utils.py          pure, dependency-free chunk math + timestamp
                           shifting (shift_segments()) -- kept apart from
                           the two files above specifically so it stays
                           trivially unit-testable
  requirements.txt          app/'s adapter-fetch deps + archive/'s DB
                           deps + faster-whisper -- no fastapi/uvicorn/
                           jinja2/slowapi, this process never serves HTTP
  Dockerfile                installs ffmpeg (a system binary, not a pip
                           package) explicitly -- see render.yaml's
                           comment on the resolver service for why plain
                           `runtime: python` is a real, unverified risk
                           there too
```

## Known limitations

Nothing here is finished — this is a fast-moving project with real,
tracked gaps rather than silently-assumed correctness. See `BACKLOG.md`
for the full, up-to-date list of open issues (completed
fixes and their verification history have moved to `BACKLOG_DONE.md`,
linked from there) — a few caption paths are shape-verified but not
content-verified pending a real example, some metadata (Alexandria VA
dates) can't be extracted at all, there's no UI yet to pick between
multiple caption language tracks when more than one exists, and the
account-deletion webhook's `SavedItem`-purge cascade has unit coverage
but has never been fired against a real deleted Clerk account (see
"Accounts (Clerk)" above).
