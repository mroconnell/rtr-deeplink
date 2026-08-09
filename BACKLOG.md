# Backlog

Live items only, roughly in priority order. Completed work — including the
investigation detail behind each fix — lives in
[BACKLOG_DONE.md](BACKLOG_DONE.md); items below link back to it for context
where relevant.

## Bugs

- **⚠️ Production incident, active as of 2026-08-09: the `worker`
  service crashed outright at startup** (`Exited with status 1 while
  running your code`, `ModuleNotFoundError: No module named
  'playwright'` — a real Render worker crash log, not a hypothetical).
  Cause: `worker/main.py` imports `app.platforms` for fresh `video_url`
  re-resolution before each transcription chunk, which registers every
  adapter including `LimsAssetFinder`/`SlcAssetFinder` — both import
  `app/platforms/headless_browser.py`, which had a top-level `from
  playwright.async_api import ...`. `playwright` is deliberately absent
  from `worker/requirements.txt` (kept lean on purpose, per that file's
  own comment) — this app/worker requirements split predates the
  playwright-dependent LIMS/SLC adapters, and wasn't reconciled when
  they were added, so just importing `app.platforms` took down the
  *entire* worker process, not just LIMS/SLC-related jobs.

  Fix shipped (`app/platforms/headless_browser.py`): made the playwright
  import lazy (`try`/`except ImportError`, sentinel `None`), so
  `register_all_finders()` always succeeds regardless of whether
  playwright is installed — only a resolve that actually needs a real
  browser now fails, with the same clean `HeadlessBrowserUnavailable`
  message as the missing-binary case, not a whole-service outage.
  Verified by simulating a playwright-less import environment locally
  (blocking the import, confirming `register_all_finders()` succeeds and
  a LIMS resolve raises the clean error instead of crashing) — **not yet
  confirmed against the real worker deploy**. **Remove this item once
  the worker service has redeployed and stayed up.**

  **Real, deliberate decision, not an accident: the worker will NOT get
  playwright/Chromium added, for now.** The obvious next question —
  "just add it to `worker/Dockerfile` too" — was checked for real
  tradeoffs rather than assumed safe, matching how the plan's own memory
  sizing above was resolved (measured, not guessed). Measured directly
  (real Playwright launch + a real fetch of the actual Minneapolis LIMS
  Cloudflare-challenge page): Chromium's *own subprocess tree* (separate
  from the Python process, purely additive to total container memory)
  uses ~266MB just launched with no page loaded, ~535MB after actually
  loading that real page. `headless_browser.py` keeps one shared browser
  alive for the whole process lifetime (launched once, reused) — fine for
  the resolver web service, but on this worker the whisper model is
  *also* loaded for the whole process lifetime (see the memory table
  above), so that ~266MB becomes a permanent tax on top of it, and a
  LIMS/SLC job's per-chunk re-resolve overlapping with active whisper
  inference on `standard`'s 2GB plan works out to roughly `1421MB
  (whisper, 900s chunk) + 535MB (Chromium mid-fetch) ≈ 1956MB` — only
  ~92MB under the ceiling, a thinner margin than the ~600MB that was
  already proven too tight once (two real OOM crashes) before this same
  plan was sized. **Decision (2026-08-09): leave the gap as-is** — a
  transcription job for a LIMS/SLC meeting fails cleanly (no browser
  available) rather than risking a third OOM crash for a platform combo
  no real request has hit yet. Per the user: revisit as a natural
  follow-on next time the worker's Render plan is upgraded anyway (for
  this or any other reason) — not worth a dedicated plan bump on its own
  just for this.

- **⚠️ Production incident, active as of 2026-08-09: real Minneapolis
  LIMS video resolves failing at the YouTube step with "Sign in to
  confirm you're not a bot."** Reported live by the user re-testing
  Minneapolis after the Playwright deploy fix landed (see
  BACKLOG_DONE.md) — a real, different failure signature than the
  earlier Playwright launch error, which itself is now confirmed fixed
  (this new error happens *after* Playwright successfully launches,
  scrapes the LIMS agenda page, and hands a real YouTube video ID
  downstream). Root cause: YouTube's anti-bot check on yt-dlp's default
  "web" internal client, which requires a PO token this app doesn't
  have — hit our Render server's IP specifically (already-current
  yt-dlp, 2026.7.4, ruled out as a stale-extractor issue).

  Fix shipped (`app/platforms/youtube.py`'s `_extract_info()`): added
  `extractor_args: {"youtube": {"player_client": ["android", "ios",
  "tv", "web"]}}` — those three internal clients have historically not
  enforced the same PO-token check "web" does, falling back to "web"
  last. Verified locally against the exact real failing video
  (`YgAu_4xWvGU`) both for metadata and a full caption download (1564
  real segments) — but **not yet confirmed against production**, since
  YouTube's own anti-bot rules shift periodically and this is
  inherently an ongoing arms race, not a one-time fix (same framing
  `youtube.py`'s existing docstring already gives for why yt-dlp is
  left unpinned). **Remove this item once Minneapolis (or any other
  YouTube-delegating unsupported-city page) has been retried in
  production and confirmed working.** If this specific client list
  stops working later, check yt-dlp's own issue tracker for the
  currently-recommended `player_client` values before re-guessing.

## UX polish

- **Some transcripts show a raw `&gt;&gt;` encoding artifact instead of a
  clean speaker-change marker.** Confirmed root cause 2026-08-09, not a
  bug in this app's own escaping: YouTube's own raw auto-caption VTT
  source contains the *literal* 8-character string `&gt;&gt;` as real
  cue text (not an actual `>` character that we're mis-escaping) —
  confirmed by downloading the raw VTT for a real video directly (69
  cues out of one ~43-minute meeting had it, always at the start of a
  new speaker's first cue, e.g. `&gt;&gt; Welcome everyone. Today is
  March the 3rd...`). This app's rendering is doing the technically
  correct, safe thing with that literal text (escaping the `&` for safe
  HTML output, which is why it displays as `&gt;&gt;` rather than either
  `>>` or a raw unescaped `&` that could be a real security problem) —
  the ugliness is a display/polish gap, not a correctness or security
  bug, and the fix must stay narrowly scoped to avoid becoming one:
  broadly HTML-unescaping *all* transcript text would be a real risk if
  a caption ever legitimately contains an ampersand or literal
  angle-bracket-like text spoken aloud (e.g. someone reading a web
  address or discussing HTML markup in a meeting) — that content must
  reach the page as plain, inert text, not get a second, unintended
  round of interpretation.
  - **Recommended narrow fix**: in `app/utils/vtt_parser.py`'s
    `parse_vtt()` (or a small new post-processing pass alongside
    `dedupe_rollup_cues()`/`normalize_shouting_caption()`), detect
    specifically the literal substring `&gt;&gt;` at the start of a cue
    (this exact shape, not a general entity-decoding pass) and either
    strip it or replace it with a real, safe-to-render Unicode marker
    (e.g. `»`, U+00BB — not an HTML metacharacter, so it can't
    round-trip into another escaping issue) — genuinely preserves the
    source's own "new speaker" signal rather than discarding real
    information, without broadening what gets decoded. Also worth
    considering whether this is the moment to finally populate the
    already-unused `speaker` field (`TranscriptSegment.speaker`,
    currently always `None` — see the diarization entry in
    `CLAUDE_BACKLOG.md`) with a generic, un-named "new speaker" boundary
    marker instead of/alongside a text symbol, though that's a bigger
    scope than the display fix alone needs.
  - **Not yet checked**: whether this same literal-entity pattern shows
    up in any non-YouTube source (Granicus/CivicClerk/Swagit/eScribe VTT
    or SRT files) — only confirmed against a real YouTube auto-caption
    file so far. If it turns out to be YouTube-specific, the fix could
    live in `youtube.py`'s own caption-handling instead of the shared
    `vtt_parser.py`; if it shows up elsewhere too, the shared parser is
    the right place. Check before deciding where to put the fix.
- **`/meetings` results would read more cleanly with a line break between
  the meeting title and its jurisdiction/date line.** Currently
  `archive/templates/meeting_list.html`'s `.calendar-candidate-main` runs
  the title link and the jurisdiction/date `<span>` together inline with
  no line break, so skimming down the page for city+date means visually
  parsing past a variable-length title on every row first. Making that
  span its own line (`display: block`, or an explicit `<br>`) would let a
  reader's eye track straight down one left-aligned jurisdiction/date
  column instead.
- **Transcript rows on permanent meeting pages (and the resolver's
  ephemeral pages — same `.transcript-segment` shape in both stylesheets)
  are hard to read once a line wraps, because the wrapped text falls back
  to the far-left margin (under the timestamp) instead of aligning under
  where the text itself started.** `.transcript-segment`
  (`archive/static/style.css` / `app/static/style.css`) lays out the
  timestamp link, copy-link button, and text as plain inline content in
  one block — no fixed-width timestamp column exists today. A CSS
  grid/flex layout (fixed-width timestamp+button column, text column
  taking the remaining width with normal word-wrap) would keep every
  wrapped line's left edge aligned under the first line's text instead of
  falling back under the timestamp. Same fix needed in both stylesheets,
  matching the "shared markup/CSS pattern, kept in sync manually" note at
  the top of `archive/static/style.css`.
- **Viebit/NYCC meetings resolve `jurisdiction` to "New York City
  Council" (a legislative body name), not "New York City, NY" (the
  city+state format most other platforms use, e.g. Swagit's
  `f"{city}, {state}"`, PrimeGov's recent "City of X" fix).** Not wrong,
  exactly — `LegistarAssetFinder._extract_page_meeting_info()`
  (2026-08-09, see BACKLOG_DONE.md) deliberately extracts the real
  legislative body name from the page's own `<title>` tag, just a
  different shape than the convention used elsewhere. Worth deciding: try
  to fix generally (would need a real second, non-NYC Viebit sample to
  know whether "extract the city name, not the body name" is even a valid
  general rule — Viebit is currently confirmed used only by NYC Council,
  per `ViebitAssetFinder`'s own docstring, so there's nothing to
  generalize from yet), or just hardcode `"New York City, NY"` for this
  one confirmed-single-jurisdiction platform rather than over-generalizing
  from a single example — matching this repo's established "narrow fix
  until real examples exist" convention (see the
  `collect_edge_case_urls` memory).

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

- **Headless-browser adapters (Minneapolis LIMS, SLC meeting recaps) —
  built and shipped 2026-08-09, see BACKLOG_DONE.md for the full build.
  Real, still-open follow-ups:**
  - **Not yet checked: whether "LIMS" is a white-labeled product used by
    other cities under different domains** (would matter for whether a
    general detection rule is worth building, vs. this staying a
    Minneapolis-specific one-off) — no search attempted yet, per this
    repo's own convention of building from real found examples rather
    than speculation.
  - **SLC's `_nearest_topic_text()` silently drops one real item per
    page it's been checked against** — a page's single "highlight" story
    (e.g. "Fraud Risk Assessment for Salt Lake City" on the March 3,
    2026 page) uses a different HTML shape (a "Learn More" / "Watch the
    Briefing" promo box, topic text as a preceding heading rather than in
    the same paragraph as the link) than the plain "{topic}. (Watch)"
    pattern the other items use — confirmed live, that item's timestamp
    (`t=2455`) never becomes an `agenda_items` entry. Safe failure mode
    (silently skipped, not garbage text) but a real, known gap — fixing
    it would need walking up to a preceding heading when the same-
    container text comes back empty, deliberately not attempted yet
    given the risk of a fragile heuristic picking up the wrong heading on
    a page shaped differently again.
  - **Real Render deployment of the new `playwright install --with-deps
    chromium` build step is genuinely unverified** — see `render.yaml`'s
    own comment and `headless_browser.py`'s docstring. Chromium needs
    real system-level shared libraries Render's plain `python` buildpack
    has never been confirmed to have (a much bigger ask than ffprobe's
    single binary, which *did* turn out to already be present). May need
    `runtime: docker` instead if `--with-deps` can't install what it
    needs in Render's build environment. Needs a real deploy attempt,
    expecting a real possible failure the way the worker's own first two
    deploys hit real OOM crashes — not assumed to work on the first try.
  - **Headless-browser fetches are real, meaningfully slower than every
    other adapter here** — a real resolve for LIMS needs *two* sequential
    fetches (agenda page for title/date, JSON endpoint for video/
    timestamps), each with its own page-load + Cloudflare-challenge wait.
    No caching or performance work done yet; worth watching real-world
    resolve latency for these two platforms once deployed, not assumed
    fine because it worked acceptably in manual live-testing.
  - **Given Tier 1 (direct video embed via a real headless browser) now
    confirmed working for both real Cloudflare-gated cases found so
    far, the Tier 2 (iframe the government's own page) / Tier 3
    (explanatory fallback message) design questions raised alongside
    this work are lower priority than they looked before this was
    built** — not deleted, since a future Cloudflare-gated platform
    could in principle resist even a realistic-UA headless fetch (untested
    against a third real case), just no longer the default assumption
    for "what happens when we hit Cloudflare next."
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
- **⚠️ Viebit video playback is confirmed broken in production, not just
  unverified from the sandbox — this is now a real, live bug, not a
  risk.** Reported by the user 2026-08-09 against a real NYC Council
  meeting (`legistar.council.nyc.gov/MeetingDetail.aspx?ID=1362373...`):
  the deployed page shows "Video failed to load; source link only." and
  the browser console logs a real `403` on the `master.m3u8` request —
  confirmed live via `mcp__Claude_Browser__*` against
  `redtaperecordings.com` itself (the same 403 previously only seen from
  this dev sandbox, per the original entry this replaces). Root cause is
  now also confirmed, not just theorized: navigating directly to Viebit's
  own embed page (`councilnyc.viebit.com/embed/vod?v=...`) plays the exact
  same video successfully, and that same origin has no
  `X-Frame-Options`/`frame-ancestors` header restricting it from being
  iframed — meaning Viebit's CDN gates the raw `master.m3u8` on
  Referer/Origin (same *class* of issue as Granicus's already-solved
  Referer-only 403, but confirmed to need more than matching Referer/
  Origin/User-Agent headers alone — see BACKLOG_DONE.md for what was
  already ruled out), while a same-origin `<iframe>` embed of Viebit's own
  player page would sidestep that gating entirely, the same way this app
  already handles YouTube (`video_format="youtube"` → IFrame Player API,
  not a raw `<video>`/hls.js load).

  **Not built yet — this is a real architecture decision, not a quick
  fix, so it's being deliberately deferred rather than rushed.** The
  YouTube iframe pathway works today because YouTube's IFrame Player API
  exposes a real, documented `seekTo()` postMessage call, which is what
  lets deep links (`?t=`/`?line=`) actually work through an iframe.
  Whether Viebit's own embed player (Video.js-based, confirmed via its
  `vod-embedded-*.js`/`lgx-videojs-plugins-*.js` bundle) exposes anything
  equivalent is genuinely unconfirmed — a quick grep of the small
  entry-point bundle found no `postMessage`/`seekTo` calls, but the real
  player logic is very likely in the larger, webpack-bundled
  `lgx-videojs-plugins-*.js` file, not yet actually inspected. Building
  the iframe switch without confirming that first risks silently breaking
  deep-linking (this app's actual core feature, per `CLAUDE.md`) for
  every Viebit meeting — worse than the current honest "source link only"
  fallback. Needs: (1) check whether `lgx-videojs-plugins-*.js` exposes a
  seek API reachable via `postMessage` from a parent frame, (2) if not,
  decide whether "no deep-link seeking, but a working embedded video" is
  an acceptable degradation for Viebit specifically, vs. leaving today's
  "source link only" behavior in place. Title/jurisdiction bug from the
  same report (`LegistarAssetFinder` discarding a good page-derived title
  in favor of Viebit's own raw-filename `video.title`) was a real, unrelated,
  much smaller bug — fixed separately, see BACKLOG_DONE.md.
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
- **YouTube/PrimeGov: non-English captions untested**, and it's unknown
  whether the manual-vs-auto-generated track coverage gap seen on the one
  real LA sample (see [BACKLOG_DONE.md](BACKLOG_DONE.md)) is typical or
  specific to that video.

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
- **Email alerts for saved searches — confirmed 2026-08-09 as the most
  concrete "worth paying for" feature identified so far.** Depends on
  accounts and search both existing first (search already live; accounts
  is not). This is what turns a one-time lookup into something a
  journalist keeps coming back to for an ongoing beat — it converts
  passive search into active monitoring, the actual job-to-be-done for
  someone covering the same story across dozens of jurisdictions over
  time. Also directly benefits from the crawler re-prioritization below
  (more corpus = more useful alerts).
- **Proactive transcription crawler — re-prioritized 2026-08-09 to
  precede accounts/billing, not just "noted now because it may affect
  the Archive's architecture."** Cross-archive keyword search on
  `/meetings` is already live (built 2026-08-08), and its value is
  directly proportional to corpus size — a national-beat journalist
  searching "Flock" only gets real value once enough jurisdictions have
  actually been resolved and transcribed. Today the corpus only grows
  when someone happens to paste a URL, a slow, demand-driven way to fill
  an archive meant to support discovery. This reframes the crawler from
  "nice to have" to "the thing that makes the flagship search feature
  actually good." No new dependencies beyond what already exists
  (adapters, Archive schema, transcription worker are all already
  built) — this is a re-prioritization question, not a new build: worth
  deciding whether it jumps ahead of accounts/billing given it doesn't
  require them.
- **Batch lookup — accept multiple meeting URLs at once (paste-list,
  CSV, etc.) instead of one at a time.** Removes the main friction point
  for a journalist working many jurisdictions at once — pasting dozens
  of URLs one-by-one doesn't match how someone actually works a
  multi-city story. Worth sequencing after accounts even though it
  doesn't strictly require them: a batch endpoint is a natural abuse
  vector (someone queuing hundreds of transcription jobs at once), and
  the transcription worker's real per-job compute cost (see "On-demand
  transcription" below — a measured real dollar figure, not a
  hypothetical one) means unmetered batch access could get expensive
  fast. Rate-limiting or account-gating this is worth deciding before
  shipping it, not after.
- **Coverage page — a public, sortable/filterable table of every
  jurisdiction/platform combination successfully resolved so far**
  (columns: jurisdiction, platform, an example meeting URL, outcome
  bucket — real transcript / agenda-only / blank / garbled /
  wrong-language / no-video, per `app/db/outcomes.py`'s existing
  `classify_outcome()` — last-verified date, and whether the transcript
  came from the source's own captions vs. the on-demand transcription
  worker). Directly addresses a real gap: today, a user only learns
  whether their city is supported by pasting a URL and seeing what
  happens — costly for someone checking many jurisdictions one at a
  time. Also doubles as a trust/credibility signal ("look how much we
  already cover") and light SEO surface area — exactly the kind of page
  other people link to and cite. Mostly a front-end exposure task, not
  new backend work — `/admin/stats` already tracks resolve outcomes by
  platform and quality bucket (see "Caching and reporting" in
  README.md); this needs a *public* (non-admin) read path into that same
  data, a rule for picking a representative example URL per
  jurisdiction/platform pair (e.g. most recent successful resolve), and
  the sort/filter UI itself.
- **Companion "known gaps" page — same table shape, listing
  jurisdictions/platforms that don't resolve cleanly yet** (attempted but
  blocked, partially working, or simply not yet built), separate from
  the coverage page above. Turns "it didn't work" from a dead end into a
  visible, honest roadmap, sets expectations for a journalist checking a
  specific city before investing time, and doubles as a natural intake
  signal — anyone whose city shows up as a known gap has a concrete
  reason to check back or flag interest instead of silently bouncing.
  Partially self-populating: failed/low-quality resolve attempts are
  already logged by the same `meeting_resolutions` system the coverage
  page above would read from. The real open question is distinguishing
  "known gap actively being worked on" from "just hasn't been tried
  yet" — those read very differently to a visitor, and probably need a
  manual status field rather than being purely derived from logs. Could
  ship after or alongside the coverage page, reusing the same table
  component.
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
  change (adding a column to the already-live `MeetingPage`/
  `TranscriptVersion` tables — no longer blocked on migration tooling
  itself now that Alembic's adopted, see BACKLOG_DONE.md, but still a
  real production schema change to run deliberately) and a Postgres-only
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
