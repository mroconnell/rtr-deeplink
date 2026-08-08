# Backlog

Live items only, roughly in priority order. Completed work — including the
investigation detail behind each fix — lives in
[BACKLOG_DONE.md](BACKLOG_DONE.md); items below link back to it for context
where relevant.

## Bugs

- **Real bug, confirmed live (2026-08-08): a permanent Archive page can be
  permanently stuck with a stale, wrong-shaped `TranscriptVersion` from a
  since-removed code path, and `/admin/recheck-archive-page` can't fix it.**
  `redtaperecordings.com/m/yountville-ca-2026-04-21-apr-21-2026-town-council-budget-workshop`
  shows a "Transcript" section containing 10 rows that are actually a copy
  of the meeting's agenda items, with the warning "No transcript available
  for this event — showing agenda-item chapter markers instead, which
  still deep-link to the right moment." Neither that message nor the
  "copy agenda into segments" behavior it implies exist anywhere in the
  current codebase — confirmed via `git log --all -S"showing agenda-item
  chapter markers instead"`, which only finds it in two commits on the
  `claude-backlog/round-1` branch, the second of which (`231c5fc`, "Add
  dedicated Agenda section, separate from transcript") replaced it with
  today's design: `agenda_items` kept in its own field, *never* folded
  into `segments` (every current adapter's resolve() comments say this
  explicitly). So this page was pushed by an old version of the resolver,
  before that refactor, and has sat unrefreshed since.

  Unlike the Emporia/Fountain Valley cases in
  [BACKLOG_DONE.md](BACKLOG_DONE.md), `/admin/recheck-archive-page` can't
  fix this one: `ingest_resolution()` (`archive/db/crud.py`) only ever
  *adds* a new `TranscriptVersion` `if segments:` — a fresh resolve today
  correctly finds real `agenda_items` but empty `segments` for this
  meeting (matching current, correct behavior), so nothing about the
  existing bad default version ever gets touched, updated, or demoted.
  The stale version is permanently stuck as `is_default=True` until
  something explicitly deals with it.

  Needs a decision, not just a mechanical fix: should a recheck that
  finds real `agenda_items` but no `segments` actively demote/replace an
  existing default `TranscriptVersion` that also has no real segments
  (i.e., was itself never a genuine transcript)? That's a real behavior
  change to `ingest_resolution()`, not just a bug fix, since today it's
  deliberately append-only / never-delete for transcript history. Simpler
  alternative: a narrow one-off admin action to directly delete/demote a
  specific bad `TranscriptVersion` row by id, without generalizing the
  ingest logic at all — smaller blast radius, doesn't touch the
  version-history-preservation design for the (presumably rare) legacy-
  data case. No other page has been checked for the same stale-shape
  issue; worth a quick audit across all 12 current permanent pages before
  deciding which fix is worth building.
- **Archive passive recheck cadence should depend on transcript quality,
  not just page age.** Now that `GET /admin/recheck-archive-page` exists
  for fixing a stale page on demand (see
  [BACKLOG_DONE.md](BACKLOG_DONE.md)'s "permanent Archive page stuck
  showing no transcript" entry), the remaining gap is the *passive*
  30-day `ARCHIVE_RECHECK_AFTER` cadence, which applies uniformly
  regardless of whether a page already has a good transcript. A page
  missing one (blank/agenda-only/garbled) has real upside in rechecking
  often, since the source may catch up at any time (government caption
  pipelines lag, per the existing comment on `ARCHIVE_RECHECK_AFTER`); a
  page with a good transcript already doesn't need frequent rechecking.
  **Design agreed, not built:** keep the existing 30-day cadence for
  pages with a good transcript, use a **1-hour** cadence for pages
  missing one. Needs two pieces: (1) `/internal/lookup`'s response
  (`archive/db/crud.py`'s `lookup_page_for_url()`, currently just
  `{slug, url, updated_at}`) gains a quality signal — e.g. `has_transcript`
  derived from whether the page's active `TranscriptVersion` has
  non-empty segments and no blank/garbled/no-transcript-type warning; (2)
  `app/main.py`'s recheck condition (`_recheck_archived_page` gate at
  line ~171) branches on that flag instead of always comparing against
  the same 30-day window. Still needs *some* floor even at 1 hour (not
  "every hit") so a popular page whose source will just never add
  captions doesn't get scraped on every visit — impolite to the
  government site, same reasoning the 30-day window was originally built
  on.
- **Emporia, KS's CivicClerk `eventBookmarks` all report
  `markerTimeStart: 0`, so every agenda item on that page (and any other
  Emporia meeting) deep-links to the very start of the video regardless
  of the item's real position.** Confirmed live (2026-08-08) directly
  against `emporiaks.api.civicclerk.com/v1/EventsMedia/585` — all 26
  bookmarks have `markerTimeStart: 0`/`markerTimeHHMMSSFormat:
  "00:00:00"`, genuinely from the source, not a parsing bug in
  `civicclerk.py`. Right now `CivicClerkAssetFinder.resolve()` renders
  these as normal clickable `[0:00]` agenda links with no indication
  they're not real per-item times — misleading, since the item text
  ("PROCLAMATIONS", "NEW BUSINESS", etc.) implies real navigation.
  Unknown yet whether this is Emporia-specific or a wider CivicClerk
  pattern (only one CivicClerk city has real bookmark data confirmed at
  all so far — see [BACKLOG_DONE.md](BACKLOG_DONE.md)). Worth deciding:
  detect all-zero bookmark times and either suppress the Agenda section's
  per-item links (fall back to a plain outline, no false deep-links) or
  surface a warning explaining the timestamps aren't real, rather than
  presenting them as reliable.
- **Alexandria VA meeting dates can't be extracted.** No `view_id` in the
  URL (so no RSS feed to cross-reference, unlike the rest of Granicus — see
  [BACKLOG_DONE.md](BACKLOG_DONE.md)) and no date signal anywhere in the
  page body either. No fallback source identified yet.
- **Real bug: a genuinely public, working YouTube video gets misreported
  as "removed, private, or blocked."** Confirmed live (2026-08-08) via
  `https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446`
  (Thousand Oaks, CA) — the page has a real embedded video id
  (`VNMQYICdQvs`), and YouTube's own oEmbed API confirms that video is
  genuinely public (title "Thousand Oaks City Council Meeting - July 7,
  2026", channel "CTO Meetings", real thumbnail). `/api/resolve` still
  fails with `"YouTube video VNMQYICdQvs could not be resolved (removed,
  private, or blocked)."` Root cause: `YouTubeAssetFinder._extract_info()`
  (`app/platforms/youtube.py`) sets `"ignoreerrors": True` on yt-dlp, so
  `ydl.extract_info()` returns `None` on *any* failure — network hiccup,
  an anti-bot block on our server's IP, yt-dlp needing an update, an
  actually-removed video, anything — and the caller (`resolve_video_id()`)
  reports all of those identically as "removed, private, or blocked."
  That message is asserting something it hasn't actually verified. Real
  cause here is unconfirmed (this exact video should be a good repro to
  debug against); fix likely needs either `ignoreerrors: False` so the
  real yt-dlp exception surfaces, or explicitly checking `info.get(
  "availability")` / a similar signal before assuming removal.

  Also corrects an assumption from the original PrimeGov/YouTube build
  (see [BACKLOG_DONE.md](BACKLOG_DONE.md)): a `?meetingTemplateId=...`
  PrimeGov URL was believed to never have video, based on one LA sample
  that genuinely had none. This Thousand Oaks sample has a real
  `var videoUrl = "VNMQYICdQvs"` on a `meetingTemplateId` page — video
  presence isn't determined by the URL shape after all, at least not
  uniformly across cities.
- **`/meetings` (the Archive's browsable index) is missing from the site
  nav.** It's only reachable if you already know the URL — confirmed live
  on `redtaperecordings.com`, no nav link points at it anywhere. Add it
  to `app/templates/base.html`'s navbar as **"Search Meetings"**, and
  while touching that nav, rename the existing **"Look Up a Meeting"**
  link to **"Add Meeting"** (clearer contrast against the new "Search
  Meetings" link — one submits a new URL to resolve, the other searches
  what's already permanently archived). `archive/templates/base.html`
  mirrors the same nav markup (see the earlier nav-consistency fix) and
  needs the same two changes to stay in sync.

## Deep links

The `t`/`line` scheme itself is sound and hasn't changed since the initial
scaffold (`t`, raw seconds, always wins the actual seek; `line=seg-N` is
display-only highlighting — see the comment above `applyDeepLink()` in
`app/static/player.js` and the precedence-bug fix in
[BACKLOG_DONE.md](BACKLOG_DONE.md)). That's already the "robust, won't
shift under us" design a deep-link contract needs. Three real gaps found
auditing it (2026-08-08), code-verified but not all live-triggered yet:

- **An Archive permanent page's `line=seg-N` can point at the wrong line
  if that page's default `TranscriptVersion` ever changes.** `/m/{slug}`
  renders whichever version is currently `is_default` unless an explicit
  `?version=` is given (`archive/main.py`'s `_pick_active_version()`), and
  `crud.push_resolution()` can attach a new `TranscriptVersion` to an
  existing page when a re-resolve finds different content. Deep-link URLs
  from `updateUrlParams()` never include `version=` — only `t`/`line`. So
  a bookmarked `/m/some-meeting?t=630&line=seg-42` could, after that
  meeting's transcript is later improved/replaced, highlight a completely
  different line at index 42 in the new version — `t=630` still seeks the
  video correctly (unaffected), so this is a wrong-highlight bug, not a
  broken link. Not yet triggered live (no permanent page has had a second
  version pushed yet), but the code path for it already exists. Fix
  options: match `seg-N` by start-time proximity instead of raw index
  when it's out of range for the rendered version, or carry the version
  id the link was copied from into the URL so `line=` is only ever
  interpreted against the transcript it was generated from.
- **`app/static/player.js` and `archive/static/meeting_page.js` are two
  independent copies of the same `t`/`line`/`seg-N` logic**, kept in sync
  only by a comment (`archive/static/meeting_page.js:6-8`) saying they're
  intentionally matched, not by shared code. A future fix to one (like the
  seek-precedence fix already made once) could land in only one file and
  silently desync deep-link behavior between `/meeting` and `/m/{slug}`.
  Worth extracting the shared parse/apply logic into one file both pages
  load, or at minimum flagging it explicitly in both files' comments as a
  place that needs a matching edit.
- **No automated test coverage pins the `t`/`line` URL contract.** No JS
  test framework exists in this repo; every verification of deep-link
  behavior, including the precedence fix above, has been manual/in-browser.
  A regression (`line` regaining precedence over `t`, `seg-N` generation
  changing) would only be caught by live-testing — the same gap the
  pytest suite already closed on the Python side. Lower priority than the
  two items above since it needs JS test infra from scratch, but worth
  flagging given deep-linking is the entire reason this repo exists.

## Platform coverage — open questions

- **eScribe, PrimeGov, and YouTube adapters have zero test coverage.**
  Granicus/Legistar/CivicPlus/CivicClerk/CA Legislature/Swagit all have
  real fixture-backed tests (`tests/`, 84 as of 2026-08-08 — see
  `BACKLOG_DONE.md`'s "Testing infrastructure" entry); these three don't,
  so a regression in any of them would currently only ever be caught by
  live-testing, not automatically. YouTube in particular has real,
  documented complexity worth pinning down in tests (roll-up cue dedup,
  manual-vs-auto-generated track selection, yt-dlp as the caption-fetch
  path) — a good first target if picking just one.
- **TTML/DFXP/ITT caption parsing (`app/utils/vtt_parser.py`'s
  `parse_ttml()`) is spec-verified only, not sample-verified.** Built
  against the W3C TTML spec's documented shape after the CivicClerk SRT
  finding below prompted a broader look at caption format assumptions —
  no CivicClerk/Granicus/Swagit/CA Legislature sample has ever actually
  used TTML/DFXP/ITT (every real populated caption seen so far is VTT or
  SRT). Handles clock-time and offset-time (seconds/ms) timeExpressions;
  frame-based ("40f") and tick-based ("2t") are explicitly unsupported
  (no frame rate available to convert with — skips that cue rather than
  guessing). If a real TTML/DFXP sample turns up, verify against it and
  update this note.
- **SBV/SUB/SMI/SAMI/plain-.txt captions get a generic best-effort text
  fallback (`strip_unknown_caption_markup()`), not real per-format
  parsing.** No per-line timing, since these formats were never actually
  observed either — the fallback exists so real caption text isn't
  silently dropped (per-line clickability isn't required; `t=`
  deep-linking to the video's playhead never depended on transcript
  timing). Wired into Granicus, CA Legislature, Swagit, and CivicClerk.
  If any of these turns out to be common on a real platform, worth a real
  structured parser instead of the generic strip.
- **SCC/STL captions are detected but not readable at all.** Both are
  binary/encoded (EIA-608 line-21 data, EBU subtitle format) — no text
  can be extracted without real codec-level decoding, so these just
  surface as a direct link ("you can view it directly: {url}") rather
  than attempted content. Genuinely low-probability for a small city's
  web captioning vendor (these are broadcast-editing interchange
  formats), so not worth building unless a real example turns up.
- **Row-level CC/SRT files in Legistar/CivicPlus calendar listings** —
  user's instinct that a calendar row might expose a direct caption file
  link alongside the video link, more reliable than what the destination
  video platform's own page offers. Checked Maricopa AZ, Westlake Village
  CA, San Diego city/county, both Berkeley Legistar calendars — none had
  one. Not disproven, just not found yet; extend `LegistarAssetFinder`/
  `CivicPlusAssetFinder`'s row-scraping when a real example turns up.
- **NYC Council's Legistar (`legistar.council.nyc.gov`) isn't detected as
  Legistar at all, and its video access is structurally different from
  every Legistar city seen so far.** Confirmed live (2026-08-08):
  `detect_platform()` only checks for `"legistar.com"` in the netloc, but
  NYC's instance is hosted on its own `nyc.gov` domain — `/api/resolve`
  against `https://legistar.council.nyc.gov/Calendar.aspx` returns
  `unsupported_platform`, never even reaching `LegistarAssetFinder`.
  Separately, once detected, the actual video links on that calendar
  page (87 of them, one per row) don't behave like every other Legistar
  city checked so far (Boston, Lee's Summit MO, Maricopa AZ, Berkeley —
  all a plain `<a href>` to `Video.aspx?Mode=Granicus&ID1=...` or similar,
  straight to the destination platform). NYC's "Video" links instead call
  `onclick="OpenTelerikWindow(...)"` — a Telerik `RadWindow` JS modal —
  so the real video destination is never a plain href in the static HTML;
  reaching it needs either executing that JS or reverse-engineering what
  `OpenTelerikWindow` actually opens (untraced so far — worth a closer
  look via browser devtools, not just static HTML scraping). Worth
  fixing both, given NYC is about as high-profile a jurisdiction as this
  tool could support: (1) loosen/extend the Legistar domain check so a
  custom-domain instance like this one gets detected, (2) figure out
  the Telerik modal's actual target URL pattern and whether
  `LegistarAssetFinder` needs a second video-discovery strategy for it.
- **Swagit custom-domain embeds unverified** (e.g. `dublin.ca.gov/
  swagit-video-player?video_id=...`). `detect_platform` recognizes the URL
  shape, but the one sample URL 404'd — parsing has only been verified
  against real `*.swagit.com` domains. Needs a fresh sample URL.
- **eScribe caption content-quality unverified.** The per-language VTT
  naming convention was confirmed structurally on Richmond, CA, but none
  were populated (all 404) — shape-verified only, not content-verified.
  Needs a real eScribe meeting with actual captions.
- **YouTube/PrimeGov: non-English captions untested**, and it's unknown
  whether the manual-vs-auto-generated track coverage gap seen on the one
  real LA sample (see [BACKLOG_DONE.md](BACKLOG_DONE.md)) is typical or
  specific to that video.

- **Design question: what happens when one submitted URL contains more
  than one video?** Real example: SLC publishes meeting recap pages
  (e.g. `slc.gov/council/may-5-2026-meeting-recap/`) that embed several
  direct YouTube links on one page — not a PrimeGov page at all, just
  the city's own site. Right now nothing in this app has a concept of
  "one URL, several distinct videos" — every adapter assumes one URL =
  one video. If we just picked one video to auto-resolve (as today's
  adapters would try to), a user would have no way to deep-link into
  video #2 or #3 through that recap URL — the exact problem the user
  flagged. Possibly the same underlying shape shows up on calendar-style
  pages too (NYC's Legistar calendar was raised as a similar case,
  though that one is already a step removed — see the NYC Legistar item
  above — since a Legistar calendar's *rows* are already handled by the
  existing `calendar_page` pick-list; the open question here is really
  about a single row/URL that itself resolves to more than one video).

  **What already works today, no code change needed:** a user can just
  copy the direct YouTube link for video #2 or #3 off the recap page
  and paste *that* into the tool — `YouTubeAssetFinder` resolves a
  standalone `youtube.com`/`youtu.be` URL on its own, with no PrimeGov
  or recap-page involvement at all. The real gap isn't capability, it's
  discoverability: nothing tells a user this is possible, or that the
  page they submitted has other videos worth grabbing individually.

  **Possible single approach for both cases** (worth deciding, not
  built): when a resolve detects more than one distinct video on the
  submitted page, return the *same* `{"error": "calendar_page",
  "candidates": [...]}` shape the calendar-listing flow already uses,
  instead of silently picking one — reusing the existing frontend
  pick-list UI (`renderCalendarPage()` in `player.js`) rather than
  inventing a second interaction pattern for what is, from the user's
  side, the same kind of choice ("here's more than one meeting/video at
  this URL, pick one"). Open questions before building this:
  - **Detection is the hard part, not the picker.** A calendar page is
    detected structurally (many `<tr>` rows, one per meeting) by each
    platform's own adapter. A recap page like SLC's is just an arbitrary
    city webpage with multiple `youtube.com` links in the body — not
    tied to any of our 8 supported platforms, so this likely needs a
    new, generic "scan any page for multiple distinct video links"
    fallback rather than a tweak to one existing adapter. Scope that
    generic scan broadly (any unrecognized page) or narrowly (only when
    a known platform's page structurally contains >1 video)?
  - Does reusing the exact `calendar_page` shape/label read right to a
    user for this case, or does "here's several videos on one page"
    deserve its own distinct message/shape even if the underlying
    pick-list UI is shared?
  - Should the "just paste the individual video link instead" escape
    hatch be surfaced explicitly (e.g. as a `video_warnings` message
    listing the other video URLs found) even before/instead of building
    the full picker — cheaper, and covers the gap today?

## Archive roadmap

**Architectural context:** anything about content/audience rather than
resolving (permanent pages, search, accounts/billing, email alerts, the
transcription crawler) grows in a **separate app** ("the Archive"), not this
resolver — see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full reasoning.
The resolver/Archive seam is `get_cached_resolution`/`log_resolution` in
`app/db/crud.py` plus `archive_client.lookup()`/`.push()`.

- **Transcription crawler** — fetch audio/video for meetings with no
  captions, run our own transcription, store permanently via the Archive.
  Separate architecturally but only useful once the Archive exists.
- **Accounts + token billing** — needed for paid features (already alluded
  to in adapter warning messages) and as a prerequisite for email alerts
  below. Not sized in detail yet.
- **Email alerts for saved searches** — depends on accounts and search
  both existing first.
- **On-demand / scheduled crawl requests** — depends on the Archive
  existing; noted now because it may affect the Archive's architecture.
- **Video highlight clips + algorithmic feed** — distant future. Flagged
  tension: this app's "never host video, only embed" principle directly
  conflicts with hosting/serving clip segments.
- **Search: move to a materialized/indexed column once the Archive
  outgrows a Python-side scan.** Built 2026-08-08 (see
  [BACKLOG_DONE.md](BACKLOG_DONE.md)): `/meetings` search (title,
  jurisdiction, agenda text, transcript text — exact and fuzzy/typo-
  tolerant modes, see `archive/utils/search.py`) currently works by
  reading each candidate meeting's already-stored JSON and matching in
  Python at query time, deliberately, to avoid two things: a schema
  change (this repo has no migration tool — `Base.metadata.create_all()`
  only creates *new* tables, never alters an existing one, so adding a
  column to the already-live `MeetingPage`/`TranscriptVersion` tables in
  production needs either introducing real migration tooling, e.g.
  Alembic, or one carefully-run manual `ALTER TABLE`) and a Postgres-only
  extension (trigram search needs `pg_trgm`, which the local SQLite dev
  fallback has no equivalent for — would make dev and prod behave
  differently for the same query, which this codebase avoids on
  principle elsewhere too).

  Fine at today's scale (dozens of meetings); the real fix once the
  Archive grows into the hundreds/thousands is a materialized, indexed
  search column — a `tsvector`-backed column with a GIN trigram index on
  Postgres, populated at ingest time instead of recomputed per search
  request. Two things worth deciding when that becomes real, not before:
  - **No new job queue needed to populate it.** `archive_client.push()`
    already runs via FastAPI's `BackgroundTasks`, fired after
    `/api/resolve`'s response goes back to the browser (see "Push, after
    resolving" in README.md) — computing and storing the search column
    would just be one more step inside that same already-backgrounded
    DB write, not a new async system.
  - **Existing archived meetings would need a one-time backfill script**
    to populate the new column retroactively (nothing populates it for
    meetings ingested before the column existed) — a single one-off run,
    not an ongoing concern, similar in spirit to
    `/admin/recheck-archive-page`'s existing per-meeting refresh but
    needing to run once across every page rather than on demand for one.
