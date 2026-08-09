# Backlog

Live items only, roughly in priority order. Completed work — including the
investigation detail behind each fix — lives in
[BACKLOG_DONE.md](BACKLOG_DONE.md); items below link back to it for context
where relevant.

## Bugs

- **Three real live pages are confirmed stuck on stale pre-fix data and
  need an actual `/admin/recheck-archive-page` run — the code fixes are
  built and verified, this session just doesn't have `ADMIN_STATS_TOKEN`
  to trigger them.** All three would pick up already-shipped fixes on a
  fresh recheck (promotion logic, language detection, word-grouping, and/
  or shouting-caps normalization, depending on the page):
  - `redtaperecordings.com/m/yountville-ca-2026-04-21-apr-21-2026-town-council-budget-workshop`
    — stuck showing agenda-copied-into-segments as a fake transcript; the
    new demotion logic should clear it.
  - `redtaperecordings.com/m/dublin-ca-2026-01-13-jan-13-2026-city-council`
    — confirmed live (2026-08-08) still showing no `· en` on `/meetings`
    *and* still rendering the old 36,085-word-fragment, ALL-CAPS
    transcript (`"GOOD" "EVENING" "AND"...` as separate lines) — this one
    row alone should pick up three separate fixes at once on a recheck:
    language detection, word-grouping, and shouting-caps normalization,
    none of which existed when this row was first ingested.
  - `redtaperecordings.com/m/california-state-senate-2026-08-06-senate-floor-session`
    — confirmed live (2026-08-08), same missing-`· en` symptom as
    Dublin, same root cause (`ca_legislature.py`'s language detection
    already exists in code, this row just predates it).

  Once confirmed working on these three, worth the originally-planned
  audit across all current permanent pages for the same stale-shape
  issue, now that there's a real fix to apply if any others turn up.
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
  cause here is still unconfirmed (this exact video should be a good
  repro to debug against). **Decided 2026-08-08: `ignoreerrors: False`**,
  not the `info.get("availability")` alternative — lets whatever yt-dlp's
  real exception is surface directly, rather than depending on yt-dlp
  returning usable partial info on failure (unconfirmed it even does).
  Whatever the real cause turns out to be, the error message becomes
  honest about it instead of always guessing "removed."

  Also corrects an assumption from the original PrimeGov/YouTube build
  (see [BACKLOG_DONE.md](BACKLOG_DONE.md)): a `?meetingTemplateId=...`
  PrimeGov URL was believed to never have video, based on one LA sample
  that genuinely had none. This Thousand Oaks sample has a real
  `var videoUrl = "VNMQYICdQvs"` on a `meetingTemplateId` page — video
  presence isn't determined by the URL shape after all, at least not
  uniformly across cities.
- **PrimeGov's date/jurisdiction come entirely from YouTube's own
  metadata, which is measurably worse than what's already sitting on the
  PrimeGov page itself.** Confirmed live (2026-08-08) via
  `https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482`
  (Oklahoma City) — video and transcript resolve cleanly (3503 real
  English auto-caption segments, no warnings beyond the standard
  auto-caption disclaimer), but:
  - `date` resolved to `2026-08-05`, one day off from the real meeting.
    The PrimeGov page has an embedded agenda document titled `"City
    Council - 8/4/2026 1:30:00 PM"` and body text saying `"August 4,
    2026"` — the *video's own title* even says "Oklahoma City Council
    Meeting - August 4, 2026". Root cause: `PrimeGovAssetFinder.resolve()`
    (`app/platforms/primegov.py`) extracts only the YouTube video id from
    the page HTML and discards everything else, delegating entirely to
    `YouTubeAssetFinder.resolve_video_id()` — which sets `date` from
    yt-dlp's `upload_date` (`app/platforms/youtube.py` line ~80), i.e.
    when the video was *posted to YouTube*, not the real meeting date.
    Plausible mismatch for any meeting uploaded the next morning after an
    evening session.
  - `jurisdiction` resolved to `"cityofokc"` — YouTube's raw `uploader`
    field (the channel handle), not a real jurisdiction string like
    "Oklahoma City, OK".
  Only affects PrimeGov pages that actually have video (the common case
  per the item above) — agenda-only PrimeGov pages never hit
  `YouTubeAssetFinder` at all. Not yet fixed: `PrimeGovAssetFinder`
  would need to parse the page's own embedded meeting-date text (real,
  present, confirmed above) and pass it through as an override to
  whatever `resolve_video_id()` returns, rather than trusting YouTube's
  upload date/uploader wholesale — same "delegate video, keep the
  wrapper's own better metadata" shape as the `source_url` fix already
  built for this same function, just for `date`/`jurisdiction` instead.
  Worth checking on a couple more real PrimeGov-with-video samples before
  building, to see how consistently the page's own embedded date text is
  actually present/parseable across cities.
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

- **Archive permanent pages have no equivalent of the resolver's "no
  transcript yet" live-playhead + copy-link feature.** Confirmed live
  (2026-08-08) against a real no-transcript/no-agenda Archive page
  (`redtaperecordings.com/m/city-of-cupertino-2024-11-18-city-council-
  public-facilities-corporation-meeting`, before its transcription job
  completed). The resolver's `app/templates/meeting.html` has a
  `#transcriptMissing` block — a live-updating `#noTranscriptTime` readout
  plus a `#noTranscriptLinkBtn` "copy link to this moment" button, driven
  by `updateNoTranscriptTime()` in `app/static/player.js` — shown whenever
  a resolve comes back with no transcript. `archive/templates/
  meeting_page.html` has no equivalent markup at all: when a page has
  neither transcript nor agenda it just renders a static "No transcript
  available for this meeting." paragraph (`meeting_page.html:181-185`),
  and `archive/static/meeting_page.js` has zero references to
  `transcriptMissing`/`noTranscriptTime`/`noTranscriptLinkBtn` anywhere —
  this looks like a feature that was simply never ported when the
  Archive's meeting page was built, not a regression. Fix would mean
  porting the resolver's `#transcriptMissing` block + `updateNoTranscriptTime()`
  logic into the Archive's template/JS pair, the same way the transcribe-
  request feature and report-a-problem feature were each deliberately
  duplicated into both.

## Deep links

The `t`/`line` scheme itself is sound and hasn't changed since the initial
scaffold (`t`, raw seconds, always wins the actual seek; `line=seg-N` is
display-only highlighting — see the comment above `applyDeepLink()` in
`shared_static/deep_link.js` and the precedence-bug fix in
[BACKLOG_DONE.md](BACKLOG_DONE.md)). That's already the "robust, won't
shift under us" design a deep-link contract needs. Three real gaps found
auditing it (2026-08-08) — two fixed since, one still open below:

- **~~Two independent copies of `t`/`line`/`seg-N` logic, and
  `line=seg-N` could point at the wrong line after a version change~~ —
  both fixed 2026-08-08.** Was: `app/static/player.js` and
  `archive/static/meeting_page.js` duplicated the exact same deep-link
  parsing/apply logic, kept in sync only by a comment; separately, a
  bookmarked `/m/some-meeting?t=630&line=seg-42` could highlight the
  wrong line if that page's default `TranscriptVersion` was ever
  replaced (`t=630` would still seek correctly — a wrong-highlight bug,
  not a broken link). Fixed together, since both touched the same
  parse/apply code: the shared logic (`getQueryParams`,
  `getDeepLinkTime/Line/Version`, `updateUrlParams`, `findActiveSegment`,
  `highlightSegment`, `applyDeepLink`, the `segments`/`autoScrollEnabled`
  module state) now lives in one new file, `shared_static/deep_link.js`
  — a new top-level directory mounted identically by both `app/main.py`
  and `archive/main.py` at `/shared-static` (one file on disk, two
  independent `StaticFiles` mounts, so either service serves it whether
  reached directly or through the resolver's reverse proxy). Loaded
  before `player.js`/`meeting_page.js` in each page's `{% block scripts
  %}`, both of which had their duplicate copies deleted. `updateUrlParams`
  now automatically tags every generated link with the Archive's current
  `TranscriptVersion.id` (read from a new `data-version-id` attribute on
  `archive/templates/meeting_page.html`'s `<body>`, via a `body_attrs`
  block added to `archive/templates/base.html` matching the resolver's
  existing pattern) — automatic per call site, not something a future
  new "copy link" button could forget to pass. `applyDeepLink` trusts
  `line` only when the URL's `version` matches the page's current one
  (or either side has no version info at all — an old pre-fix link, or
  the resolver's page, which has no version concept); on a real
  mismatch it falls back to `findActiveSegment(t)` (time-proximity
  matching) instead of highlighting a possibly-wrong index.

  Verified three ways, no JS test framework existing in this repo (see
  the item below): (1) a real behavioral difference caught and
  preserved during the merge — `player.js`'s `highlightSegment` respected
  an `autoScrollEnabled` toggle the Archive page doesn't have; folded
  into the shared file so the Archive page (which never toggles it)
  behaves identically to before. (2) A one-off Node `vm.runInContext`
  script (not a permanent test) simulating real multi-`<script>`-tag
  scoping — critically *not* a plain `eval()`, which was tried first and
  gave misleading results because direct eval creates its own nested
  lexical scope, unlike separate classic `<script>` tags which genuinely
  share top-level `let`/`const` bindings — covering version-match,
  version-mismatch-fallback, no-version-old-link, resolver-page (no
  version), and the URL-tagging behavior of `updateUrlParams` itself: 9
  cases, all passing. (3) Real local servers (resolver proxying to a
  real local Archive instance, matching production's reverse-proxy
  shape exactly) with a seeded real page, checked live in-browser —
  `/shared-static/deep_link.js` loads with no console errors, all
  shared functions (`applyDeepLink`, `findActiveSegment`,
  `updateUrlParams`, `highlightSegment`) are defined and callable from
  both `player.js` and `meeting_page.js`, `segments` populated by one
  script is correctly visible to functions defined in the other
  (confirming real cross-script-tag `let` sharing, not just the Node
  simulation), and `data-version-id` renders correctly. Full Python
  suite green throughout (121 tests, unaffected -- this was a pure
  frontend change).
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
  tool could support: **(1) decided 2026-08-08 — hardcode `nyc.gov` as a
  known Legistar exception** alongside the `legistar.com` check, rather
  than trying to infer a general page-structure signature from this one
  example. Generalizing detection is deliberately deferred until more
  custom-domain Legistar cities turn up — see the new "collect custom
  domains" item in this same section, and the `collect-edge-case-urls`
  Claude Code memory this session added specifically to make that habit
  durable across sessions. (2) The Telerik modal's actual target URL
  pattern is still untraced — real investigation needed, not a decision,
  before knowing whether `LegistarAssetFinder` needs a second
  video-discovery strategy for it.
- **New: collect custom-domain examples for popular platforms as they're
  found, into the existing shared sample sheet** ("Watchdog Sample
  meetings," linked in `CLAUDE.md`) — not a code change, a standing
  habit. Motivated directly by the NYC Legistar case above: rather than
  guessing a general "detect by page structure" rule from a single
  custom-domain example, log each new one as it's found (custom domain,
  unusual URL shape, anything that could recur across other cities) and
  only build a general detection rule once several real examples exist
  to generalize from. Applies beyond Legistar — the same principle now
  also shapes the multi-video-detection decision below.
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

  **Decided 2026-08-08, three real decisions, not built yet:**
  - **Reuse the existing `calendar_page` shape** (`{"error":
    "calendar_page", "candidates": [...]}`, `renderCalendarPage()`'s
    pick-list UI) rather than inventing a second, distinct interaction
    pattern — from the user's side this is the same kind of choice
    ("here's more than one thing at this URL, pick one"), whether it's
    several meetings on a calendar or several videos on one recap page.
  - **Start with detection scoped narrowly to known platforms only**,
    not a generic "scan any unrecognized page for multiple videos"
    fallback — same reasoning as the NYC Legistar domain-detection
    decision above and the new `collect-edge-case-urls` habit: a broad
    scanner built from one example (SLC) risks real false positives,
    specifically flagged by the user: a page with several video/audio
    *files* that are actually the same content (different quality
    renditions, mirrors) shouldn't trigger the multi-video picker just
    because there's more than one `<video>`/`<a>` tag. **Real signal
    worth building into detection once this gets generalized**: file
    *duration* similarity — several long files of nearly the same
    duration are more likely renditions of the same recording than
    genuinely distinct videos; genuinely distinct meeting videos
    wouldn't be expected to coincidentally share a duration. Until
    then: log real examples of pages with genuinely multiple distinct
    videos (via the sample sheet, same habit as the domain-collection
    item) and only build the general pattern once several exist.
  - **The narrow start effectively defers the "build the full picker
    now vs. just surface an escape-hatch message" question** — with
    detection scoped to known platforms only, there's no real SLC-style
    case being handled yet either way; revisit this specific question
    once enough logged examples justify actually building detection for
    a real case.

## Archive roadmap

**Architectural context:** anything about content/audience rather than
resolving (permanent pages, search, accounts/billing, email alerts, the
transcription crawler) grows in a **separate app** ("the Archive"), not this
resolver — see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full reasoning.
The resolver/Archive seam is `get_cached_resolution`/`log_resolution` in
`app/db/crud.py` plus `archive_client.lookup()`/`.push()`.

- **Accounts + token billing** — needed for paid features (already alluded
  to in adapter warning messages) and as a prerequisite for email alerts
  below. Not sized in detail yet. On-demand transcription (built
  2026-08-08, see [BACKLOG_DONE.md](BACKLOG_DONE.md)) deliberately doesn't
  wait on this — it uses the same lightweight, email-only, confirm-once
  pattern as the "Lightweight jurisdiction follow" idea in
  `CLAUDE_BACKLOG.md`, not real accounts.
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
## On-demand transcription — real gaps left open

Built 2026-08-08, see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full
build/verification detail. First real deploy attempt (also 2026-08-08)
immediately crash-looped on a missing `pydantic` dependency in
`worker/requirements.txt` — fixed, and see that same file's follow-up
entry for the methodology lesson (a shared local dev venv can hide a
missing-package bug that only surfaces once a service is actually
deployed with its own real, isolated dependency set). Confirmed by that
same deploy: `worker/Dockerfile` **does** build successfully on Render —
one item below is resolved as a result.

- **~~ffmpeg/ffprobe availability on the resolver service is
  unverified.~~ Confirmed live 2026-08-08.** A real `POST` to
  `/api/transcription/check-feasibility` against a live Granicus URL
  returned `{"ok": true, "duration_seconds": 27073.36, ...}` — the plain
  `runtime: python` Render buildpack already has `ffprobe` on `PATH`, no
  `runtime: docker` switch needed after all.
- **~~Render worker plan sizing is a guess.~~ Resolved for real 2026-08-08,
  after two live crashes, not one.** First real deploy OOM-killed on
  `plan: starter` (512MB) loading the original `"small"` model default.
  Switched to `"tiny"`, sized from local measurement -- but that
  measurement was only against a ~9-second synthetic clip (~382MB), and
  the **second** real deploy OOM-killed too, on a genuine 900-second
  (15-minute) real meeting chunk. Real lesson, not just a bigger number:
  `faster-whisper`'s memory usage scales substantially with audio
  *duration*, not just model size -- a short-clip measurement was
  actively misleading. Real curve, measured directly against real
  Fountain Valley clip 607 audio, `"tiny"` model, one duration per
  process:

  | duration | peak RSS |
  |---|---|
  | 0s (imports only, no model) | ~67MB |
  | ~9s (synthetic) | ~382MB |
  | 60s | ~454MB |
  | 180s | ~615MB |
  | 300s | ~814MB |
  | 900s (the real chunk size that crashed) | ~1421MB |

  Even 60s only clears 512MB by ~58MB -- too thin to trust, and shrinking
  further toward "safe" starts costing a full adapter re-resolve (RSS
  feed, agenda viewer, etc.) every ~30-45 seconds of audio, which is both
  slow and a real risk of getting rate-limited by the government source
  for hammering it that often. **Resolution: upgraded the worker's Render
  plan to Standard (2GB RAM, $25/mo)**, not shrinking chunks further --
  `900s` chunks at ~1421MB fit that with real (~600MB) margin, confirmed
  by the measurement above, not another guess. `TRANSCRIPTION_CHUNK_SIZE_
  SECONDS` (`app/main.py`) never needed to change once the plan did.

  **`"tiny"`'s real quality against actual meeting audio: assessed
  2026-08-08, real errors found, not just "approximate but fine."** Job 1
  (Cupertino, 2 chunks) completed successfully end-to-end and was mostly
  accurate on substance (real terms like "Form 8038-G" came through
  correctly), but a full read-through of the transcript found two
  distinct real problems, not hypothetical ones:
  - **A meaning-changing mistranscription**, not just noise: `"Okay, so
    that, that is this meeting, this meeting is a joke."` at 25:28 --
    almost certainly "this meeting is adjourned," misheard as "a joke."
    Puts a fabricated sentence in a real named official's mouth on a
    permanent public page — a real reputational-risk failure mode, not
    just lower search-match quality.
  - **A hallucination loop**: `"If it doesn't jump."` repeated five times
    in a row at 22:34-22:43 — a known Whisper failure mode where the
    model free-associates on quiet/unclear audio instead of stopping,
    not a real utterance at all.

  Two fixes made in response (2026-08-08): (1) a visible disclaimer now
  renders on any `source="transcribed"` version (`archive/templates/
  meeting_page.html`) — previously **no UI anywhere distinguished a
  self-transcribed version from a real scraped caption**, so a
  hallucinated sentence like the one above read exactly as authoritative
  as an official caption; (2) `worker/transcription_engine.py` now passes
  a short government-meeting-vocabulary `initial_prompt` to
  `faster-whisper` (explicitly includes "adjourned"), aimed at exactly
  this failure mode. Neither fix is a guarantee — worth re-checking
  quality on the next real job now that the prompt's in place, same as
  this check was itself the first real one. `"base"`'s real memory curve
  at realistic chunk durations
  (as opposed to the same misleadingly-short 9s clip that under-predicted
  `"tiny"`'s real cost) is still unmeasured -- deliberately not attempted
  in the same pass as the plan upgrade, to change one variable at a time
  after two live crashes. Worth a real `"base"`-at-900s measurement as
  its own follow-up once `"tiny"` is confirmed working end-to-end on the
  new plan, not stacked on top of an unconfirmed fix.
- **~~Resend's contact-lookup-by-email endpoint is unverified.~~ Confirmed
  live 2026-08-08.** A real request from an existing newsletter subscriber
  (`mroconnell@gmail.com`) correctly skipped the confirm-by-email step and
  went straight to `queued` — proof `archive/utils/email.py`'s
  `check_audience_membership()` and Resend's `GET /audiences/{id}/
  contacts/{email}` endpoint shape both work as written, not just
  degrading safely on failure.
- **Completion email's "share this" ask has no real "support us" CTA
  behind it — deliberately deferred, not forgotten.** The completion
  email now asks the recipient to forward it / share the link (see
  BACKLOG_DONE.md's 2026-08-08 entry), but the site has nothing to point
  a real support ask at yet — no donation/membership mechanism exists,
  only `/subscribe` and `/about`. Revisit once the site has something
  concrete to offer (account registration, referrals, or payments — all
  still pre-roadmap, see "Archive roadmap" below); don't build a support
  ask against nothing.
- **No language-track picker for a transcribed version yet** — a
  transcribed `TranscriptVersion`'s language is detected from its own text
  (`archive/utils/language.py`, mirroring every scraped-caption adapter's
  existing behavior), but if a meeting is bilingual or the detection is
  simply wrong, there's no way to fix or override it after the fact short
  of a database edit.
- **~~A non-default `TranscriptVersion` is invisible to internal
  search~~ — fixed 2026-08-08.** Confirmed by reading the actual code,
  prompted by asking whether a scraped caption and an AI transcript
  could both be shown/found once a meeting has both. The version-picker
  UI already existed for *viewing* both (`archive/templates/
  meeting_page.html`'s `.version-picker`, a `?version=` link list, not JS
  tabs — `promote_transcript_version()` never deletes the version it
  demotes), but `archive/db/crud.py`'s `list_pages()` (the `/meetings`
  search backing) used to join `TranscriptVersion` filtered to
  `is_default.is_(True)` only, so a demoted version's text was never
  matched by a keyword search. Fixed: `list_pages()` now runs a second
  query (only when a keyword search is active, same as before) pulling
  *every* version's segments per candidate page, and matches against the
  concatenation of all of them — still one result row per page, not one
  per version, since a viewer searching `/meetings` wants to find the
  meeting, not pick a version from search results. The display-facing
  columns (language/has_transcript badge) are unchanged, still sourced
  from the default version only. Verified with a new test
  (`tests/test_list_pages_search.py`, real DB: ingest a version with a
  unique keyword, promote a second version over it demoting the first,
  confirm `list_pages(keyword=...)` still finds the page). Full suite
  green (116 tests).

  **External search is still open.** The deliberate one-canonical-URL
  choice is right and shouldn't change (indexing `?version=1`,
  `?version=2`, etc. as separately-ranked pages would just be
  duplicate-content spam against ourselves). The real fix is rendering
  *all* versions' transcript text into the canonical page's own HTML,
  not just the active one — e.g. every version's segments present in the
  DOM, client-side-toggled visibility (real JS tabs replacing today's
  full-reload `?version=` link list) rather than server-side picking-one.
  Google's own guidance is that content inside JS-toggled tabs/accordions
  still gets crawled and indexed as long as it's actually present in the
  initial DOM, not injected only on click — so this isn't a hack, it's
  the documented-correct way to get a crawler to see supplementary
  content without duplicate-URL risk. Real cost to weigh before building:
  page HTML size grows with every version's full transcript (Dublin's
  real transcript alone is over a megabyte of JSON per BACKLOG.md's
  search-scale note) — fine for a typical 1-2-version page, worth a size
  check before assuming it's fine for a page with several. This also
  happens to be the actual "tabbed content" UI asked about earlier, so
  building it kills both asks with one change — worth its own scoped
  task given it touches `.version-picker`, `meeting_page.js`, and the
  template's rendering of `active_version` throughout.
- **Job priority — needed before the worker can auto-generate its own
  jobs (see the next item).** Right now `claim_next_chunk()`
  (`archive/db/crud.py`) claims strictly oldest-first: `.order_by(
  TranscriptionJob.created_at.asc())`, no other ordering signal exists.
  That's fine while every job comes from a real person clicking
  "Transcribe this meeting," but breaks down the moment anything else
  can create jobs (self-generated batch jobs, see below) — a real
  visitor's request would land at the back of the queue behind however
  much auto-generated work got queued first, which is exactly backwards.
  **Plan**: add a `priority` column to `TranscriptionJob`
  (`archive/db/models.py`), and have `claim_next_chunk()` order by
  `priority.desc(), created_at.asc()` instead of `created_at.asc()`
  alone — higher number claimed first, FIFO within the same priority
  tier. Two tiers to start (see the two items below): `PRIORITY_LOW` for
  self-generated idle work, `PRIORITY_MEDIUM` for real user requests —
  named constants, not raw numbers scattered through the code, with
  room to add a higher tier later without a schema change (the column's
  just an int).

  **Real blocker worth flagging now, not discovered later**:
  `transcription_jobs` is already a live table in production Postgres
  (real rows exist from real jobs already processed) — adding a new
  column to an *existing* table is exactly the kind of schema change
  `Base.metadata.create_all()` does **not** handle (per this repo's own
  documented convention — see CLAUDE.md and BACKLOG.md's "Search: move
  to a materialized/indexed column" entry for the other two cases that
  already flagged this same wall). **Decided 2026-08-08: adopt Alembic**
  as the real fix, rather than another one-off manual `ALTER TABLE` —
  but deliberately **left as its own backlog item, not bundled into
  building priority itself**, since other schema changes are already
  piling up against this same wall (the materialized search column, this
  priority column, possibly accounts down the line) and adopting
  migration tooling is worth doing once, deliberately, not rushed
  alongside the first feature that happens to need it.
- **New: adopt Alembic for the Archive's Postgres schema.** Decided
  2026-08-08 (see the job-priority item above) as the real fix for the
  migration-tool gap this repo has deliberately not had — three real
  schema changes are now piling up against `Base.metadata.create_all()`'s
  "new tables only, never alters existing ones" limitation: this
  priority column, the materialized/indexed search column ("Archive
  roadmap" section below), and eventually accounts. Left as its own
  item deliberately, not bundled into building priority — worth doing
  once, properly, not rushed alongside whichever feature happens to
  need it first.
- **Let the worker auto-generate transcription jobs during genuinely
  idle time**, so the Archive can fill in missing transcripts without
  someone manually clicking "Transcribe" on every meeting one at a time.
  `worker/main.py`'s `run_forever()` already polls continuously and
  currently just sleeps (`EMPTY_POLL_BACKOFF_SECONDS`) when
  `claim_next_chunk()` finds nothing — that idle branch is the natural
  place to add "look for a `MeetingPage` missing a good transcript
  (reusing `archive/db/crud.py`'s `_has_good_transcript()`, already
  built for the Archive recheck cadence) and create a job for it."
  **Must only run when the queue is completely empty** (no
  `queued`/`in_progress` jobs at all) — not on every single empty poll,
  and not just whenever the worker happens to be between chunks of a
  real job. Depends on job priority (above) existing first: even with
  the empty-queue guard, a newly-created auto job would otherwise be
  indistinguishable in claim order from a real user's next request; a
  self-generated job here should always use `PRIORITY_LOW`. Real
  decisions on job creation itself needed before building, not just the
  scheduling — one decided, one still open:
  - **Decided 2026-08-08: pick the oldest archived meeting first** among
    qualifying candidates — processes the Archive's backlog roughly in
    the order meetings were added, predictable and easy to reason about,
    over "most recently archived" (favors freshness/traffic) or a random
    pick.
  - **Still open**: how long to cool down after a failed transcription
    before a page becomes an auto-candidate again, so a page that just
    failed doesn't get auto-retried forever. Also needs the same
    feasibility-check logic `app/main.py`'s
    `/api/transcription/check-feasibility` already has (probe duration,
    plausible-length check) reused rather than assuming every candidate
    is actually transcribable.
- **User-submitted (self-serve) transcription requests should be
  `PRIORITY_MEDIUM`** — the real, immediate case a live visitor is
  waiting on, and needs to always claim ahead of any `PRIORITY_LOW`
  self-generated batch work sitting in the queue. This is the
  straightforward half of the priority rollout: `POST
  /internal/transcription/create-job` (`archive/main.py`) →
  `create_transcription_job()` (`archive/db/crud.py`) already has
  exactly one call site creating a real job from a real request: it just
  needs to set `priority=PRIORITY_MEDIUM` explicitly once the column
  exists, no new logic beyond that.
