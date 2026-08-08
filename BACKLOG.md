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

## Player UX

- **The transcript's auto-scroll is too aggressive — big, jarring jumps
  between the video and wherever the transcript's active line is.**
  Reported directly by the user (2026-08-08): watching via the playhead
  jerks the page down to the active transcript line, and clicking a
  transcript timestamp jerks it back up — often crossing the whole
  Agenda section in between, since that sits between the video and the
  transcript in the DOM. Traced to the real cause in
  `app/static/player.js`, not guessed: clicking a `.segment-timestamp`
  itself does *not* scroll (`highlightSegment(segId, false)` — already
  deliberately no-scroll on click). The actual jerk comes from the
  `timeupdate`-driven side: every tick during normal playback calls
  `highlightSegment(currentSegId, autoScrollEnabled)`, which runs
  `scrollIntoView({behavior: 'smooth', block: 'center'})` on whatever
  line is now active — firing continuously throughout playback, so
  scrolling away to read the agenda or transcript elsewhere gets
  overridden and snapped back down as soon as the video keeps playing.
  An "Auto-scroll: On/Off" toggle already exists
  (`#toggleAutoScrollBtn`), but it's all-or-nothing and easy to miss/
  forget about.

  User brainstormed four directions: reduce/remove auto-scroll (some or
  all cases), keep the video sticky/floating near the top of the page on
  desktop so it never scrolls off-screen, shrink the video when scrolled
  away from it, or a Picture-in-Picture display.

  **Recommended fix, not yet built:**
  - **Rule out real Picture-in-Picture.** This app renders video two
    different ways depending on platform — a native `<video>` element
    for direct files, a YouTube iframe for YouTube sources (see
    `activeVideoAdapter`'s two implementations in `player.js`). The
    browser's real PiP API only works cleanly against a native
    `<video>` element; it doesn't apply the same way to an embedded
    YouTube iframe, so real PiP would behave inconsistently depending on
    which platform a given meeting came from — not a good foundation for
    a feature meant to feel uniform.
  - **Sticky/floating video on desktop is the strongest fix**, because
    it removes the *reason* half the jerking happens at all: if the
    video never scrolls out of view, there's nothing to jump back up to
    when a timestamp is clicked or when someone wants to check the
    frame. `position: sticky` (or `fixed`) on the video's container,
    above some desktop-width breakpoint (matches the user's own framing
    — "especially appropriate on desktop... where we have a lot of
    space" — a phone-width layout doesn't have room to dedicate to a
    permanently visible video alongside a readable transcript column).
  - **Don't remove the follow-along auto-scroll entirely** — it's a
    real, useful feature (watch the transcript track playback
    hands-free), the problem is how *forcefully* it moves, not that it
    exists. Soften it instead: `block: 'nearest'` instead of `block:
    'center'` (only scrolls when the active line is actually out of
    view, not every tick even when it's already visible), and/or only
    invoke `scrollIntoView` when the active line has actually left the
    viewport rather than unconditionally on every `timeupdate` — cheap
    changes to the same `highlightSegment()` call site, no new
    architecture needed.
  - Shrinking the video on scroll-away is a reasonable variant of the
    sticky idea (still keeps it visible, just smaller/less obtrusive)
    but is more CSS complexity for not much more benefit than simply
    pinning it — worth only if a plain sticky video turns out to feel
    too large/dominant once actually built and tried.

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
- **A real Dublin, CA Archive page
  (`/m/dublin-ca-2026-01-13-jan-13-2026-city-council`) shows no language on
  `/meetings` despite having a real English transcript.** Confirmed live
  (2026-08-08): its default `TranscriptVersion.language` is empty (the
  `/meetings` row shows "Dublin, CA · 2026-01-13" with no `· en`, unlike
  a second Dublin page — `/m/dublin-ca-city-council-regular-meeting` —
  which correctly shows "· en"). Root cause understood, not just
  observed: `app/platforms/swagit.py`'s language detection
  (`detect_language_from_texts()` on `#transcript-fragments` text) was
  only added today, 2026-08-08 (see that file's inline comment, and
  `app/utils/vtt_parser.py`'s `detect_language_from_texts()` docstring)
  — this specific page's version was ingested *before* that fix existed,
  so it's frozen with `language=None` from whenever it was first pushed.
  Running `/admin/recheck-archive-page` against it would very likely set
  `transcript_language="en"` on a fresh resolve, **but that alone
  probably still won't fix the `/meetings` listing**: `ingest_resolution()`
  (`archive/db/crud.py`) only marks a new version `is_default=True` when
  `any_version is None` — since a version already exists here (the
  null-language one), a recheck's fresh push would add a *second*,
  correctly-labeled version without promoting it over the stale
  default, the same general gap noted elsewhere in this file about
  `ingest_resolution()` never calling `promote_transcript_version()`
  the way the transcription-job completion path does. Two real fixes
  bundled in one root cause: (1) confirm whether a recheck actually
  behaves as predicted above (untested — needs `ADMIN_STATS_TOKEN`),
  (2) decide whether `ingest_resolution()`'s recheck path should also
  promote when the fresh version has a real improvement (a language
  where there was none, real segments where there were none) over the
  current default — the same open design question already raised for
  the Yountville stale-transcript bug above, worth solving once for
  both rather than twice.
- **Swagit's `#transcript-fragments` transcript is unreadable — one word
  per line, not phrases.** Confirmed with real data (2026-08-08) on the
  same Dublin, CA meeting above: consecutive segments read `[0:04] GOOD`,
  `[0:04] EVENING`, `[0:04] AND`, `[0:05] HAPPY`, `[0:05] NEW`,
  `[0:05] YEAR` — six separate clickable lines for one six-word phrase
  spoken in under two seconds. Root cause: `swagit.py`'s
  `#transcript-fragments` parsing (`app/platforms/swagit.py` ~line 110)
  creates one `TranscriptSegment` per DOM fragment with `start == end`
  (a true instant, not a real cue range) — this is genuinely how Swagit
  emits this data (one `<a data-ts>` per word), not a parsing bug. Every
  other adapter's segments come from real VTT/SRT cues, which are
  already authored in readable multi-word phrases, so this is Swagit-
  specific. **Wanted**: group consecutive word-level fragments into
  readable lines — a few seconds or a handful of words per line, segment
  `start` = the *first* word's timestamp in the group (not each word's
  own), `end` = the last word's. Needs a decision on the grouping rule
  before building: a rolling time window (e.g. ~3-5s per line), a fixed
  word count (e.g. 8-12 words), or something sentence-aware — complicated
  by these fragments apparently carrying no punctuation at all (`"GOOD
  EVENING AND HAPPY NEW YEAR"`, all-caps, no periods), so a
  punctuation-based grouper isn't available the way it might be for
  prose captions. A pure post-processing step over `segments` once
  collected, before they're returned in `ResolvedMeeting` — doesn't need
  to touch the DOM-scraping logic itself.
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
- **The transcription-complete email is bare — wants real copy, brand,
  and a share/support ask.** `archive/utils/email.py`'s
  `send_completion_email()` today is three unstyled `<p>` tags: a
  one-line "your transcript is ready," a plain `<blockquote>` excerpt
  (first 500 chars of the transcript — `EMAIL_EXCERPT_CHARS` in
  `worker/main.py`, already there, not missing), and a bare link to the
  page. No color, no logo, no font, nothing that reads as "Red Tape
  Recordings" rather than a generic system notification, and no ask of
  the recipient at all (share it, follow/subscribe, support the
  project). Real open questions before building this, not just a styling
  pass:
  - **No logo/brand image asset exists anywhere in this repo yet** —
    confirmed, `archive/static/` has no logo/icon file, and this is the
    same underlying gap already flagged in `CLAUDE_BACKLOG.md`'s
    og:image note (no thumbnail generation either). An email with real
    brand elements needs at least a wordmark image hosted somewhere
    email clients can fetch it from (most strip inline SVG) — this
    likely can't be built until that asset exists.
  - **Email HTML can't use the site's actual CSS** (`--primary` navy
    `#2c3e50`, `--accent` blue `#3498db`, the Georgia serif body font,
    etc., all in `archive/static/style.css`) — most email clients strip
    `<style>` blocks and CSS variables outright, so real "brand
    elements" here means hand-inlining hex values and font-family
    strings directly on each tag, a different (uglier, more
    maintenance-prone) discipline than the rest of this codebase's CSS.
  - **No "support us" mechanism exists yet to link to** — the only
    existing calls-to-action anywhere on the site are `/subscribe` (the
    newsletter) and `/about`; there's no donation/membership page. Worth
    deciding whether "support us" here just means "subscribe for
    updates" (cheap, reuses what exists) or implies building a real
    support mechanism first (bigger, a prerequisite, not a copy change).
  - **Share copy needs an actual mechanism to share** — a plain "share
    this with a friend" line plus the existing `page_url` might be
    enough (no code needed beyond copy), or this could mean real share
    buttons (pre-filled tweet/email text, etc.) — worth deciding which
    before writing copy that promises more than what's built.
  - **Excerpt selection is naive** — literally the transcript's first
    500 characters, which for a typical meeting is procedural
    throat-clearing (roll call, approving prior minutes), not the most
    shareable/interesting moment. Worth a real pick-a-better-excerpt
    pass (e.g. skip past a "procedural" first N seconds, or pick the
    longest/most substantive-looking segment) if the goal is content
    someone would actually want to share.
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
- **"Transcribe this meeting from audio" is too easy to miss.** Still a
  small `.link-button` text link (`app/templates/meeting.html` /
  `archive/templates/meeting_page.html`, styled identically to "Report a
  problem with this meeting" — same class, same treatment) — wants to be
  a real, obvious button, not a text link easy to scroll past. **The
  *placement* half of this is now fixed (2026-08-08)**: it's been moved
  off the top meta section and now renders directly next to the
  transcript-quality warnings on both pages — right after
  `#transcriptWarnings`/`#transcriptMissingWarnings` on the resolver,
  and inside both the has-a-garbled-transcript branch (after
  `active_version.transcript_warnings`) and the no-transcript branch on
  the Archive page (`archive/templates/meeting_page.html`) — plus the
  obsolete "contact ryan@how-to-adu.com for details" pitch was trimmed
  out of the four adapter warning messages that used to carry it
  (`app/platforms/granicus.py` x2, `civicclerk.py`, `escribe.py`), since
  the self-serve button sitting right there now does what that pitch
  used to ask people to email in for. Still open: the visual
  treatment itself — it's still a plain text link, not a real button.
- **Transcribe UI's styling doesn't match the rest of the page.** Inherited
  wholesale from `.report-problem-status`'s ad hoc styling (`.transcribe-
  status.success`/`.error` in both `app/static/style.css` and `archive/
  static/style.css`): a hardcoded green (`#2f855a`) for success, a small
  `font-size: 0.85rem` throughout — neither matches the page's existing
  typography/color system (`--fg`/`--accent`/`--muted`, the `.warnings`
  amber-pill treatment already used elsewhere for transcript-quality
  messages). Note this styling issue isn't unique to the new transcribe
  UI — `.report-problem-status` has the exact same ad hoc colors/sizing
  it was copied from, so fixing this well might mean fixing both
  together rather than just the newer one.
