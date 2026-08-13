# Backlog

Live items only, roughly in priority order. Completed work — including the
investigation detail behind each fix — lives in
[BACKLOG_DONE.md](BACKLOG_DONE.md); items below link back to it for context
where relevant.

## Trust & safety — real gaps, threat-modeled 2026-08-10

Prompted directly by the user asking "should I be worried about prompt
injection or people submitting fake government websites or people
submitting websites that aren't government at all" — a real think-through,
not a hypothetical checklist. Nothing here is built yet; this section
exists to make the actual risk shape visible before deciding what (if
anything) to build against it.

- **Prompt injection: not a live product risk today, because no LLM sits
  in the deployed serving path at all.** Every adapter parses scraped
  page content with deterministic regex/BeautifulSoup/JSON extraction —
  nothing reads a page's text and *acts* on instructions found in it.
  `worker/`'s `faster-whisper` transcribes audio to text; it doesn't
  interpret or follow spoken instructions either. The one place this
  already matters for real: **when I (Claude, during development) fetch
  and read a real government page's raw content directly** — that's
  already covered by the same instruction-source-boundary rule I operate
  under generally (fetched content is data, not commands), not something
  new to build. **Where this stops being true**: the moment any feature
  reads scraped page content *through* an LLM in the live serving path —
  an "AI summary," topic classification, semantic re-ranking, anything
  like that — a malicious page's own content becomes a real injection
  vector against that feature specifically. Nothing like that is planned
  today; worth re-reading this section before building the first one
  that is.

- **Fake/spoofed "government" pages and non-government content getting
  archived as if it were official: a real, currently wide-open gap, not
  a hypothetical one.** Confirmed by reading the actual code: nothing
  verifies a submitted URL's site is a genuine government body before
  archiving it. Platform detection is pure URL-shape pattern matching
  (`detect_platform()`), and `jurisdiction`/`title`/`date` are extracted
  *from the submitted page's own content* with zero cross-check against
  any independent government registry — a malicious actor could claim
  any jurisdiction name they want. `generic_fallback.py` (built
  specifically to catch anything that doesn't match a known platform) is
  the widest-open path: it best-effort-scans *any* page for a video +
  agenda-shaped text, with no domain restriction of any kind — a
  `.gov`/known-city check would be the obvious first mitigation, but
  most real, already-working platforms (`lacity.primegov.com`,
  `dallastx.new.swagit.com`, etc.) aren't `.gov` domains themselves
  either, so a naive TLD allowlist would break most of what currently
  works, not just block abuse.

  **Real consequences if this got exploited, not just abstract risk:**
  fabricated "official" video/transcript content published as a
  seemingly-legitimate, SEO-indexed permanent page under a real-sounding
  jurisdiction name (disinformation/astroturfing risk); a real named
  official's words fabricated or altered under the appearance of an
  authoritative civic record (defamation-adjacent risk, sharper than the
  already-flagged Whisper-hallucination risk in the on-demand
  transcription section below, since *that* risk at least starts from
  real audio); the Archive used as free SEO-boosted hosting for
  unrelated spam/harassment content via `generic_fallback`; reputational/
  trust erosion for the whole site if any of the above became public.

  **What already exists as a real, if reactive, mitigation**: the
  "Report a problem with this meeting" flow (`ProblemReport`,
  `app/db/models.py`) already gives any third party a path to flag a
  suspicious page — genuinely built, not aspirational, just reactive
  (after publication) rather than preventive.

  **Mitigation options worth weighing, not yet decided or built (except
  the first, built 2026-08-11 — see BACKLOG_DONE.md):**
  - ~~**noindex generic_fallback/`best_effort` pages by default**~~ Built
    2026-08-11: `archive/templates/meeting_page.html`'s meta block now
    renders `<meta name="robots" content="noindex">` whenever
    `page.platform == "unknown"` (the exact string `generic_fallback.py`
    registers under). The narrowest, cheapest mitigation on this list —
    doesn't block anything, just stops amplifying the least-verified
    content until a human's looked at it. The rest of this section's
    threat model (fake-jurisdiction risk, curated-list idea, trust tiers)
    is still open.
  - **Manual review before a brand-new jurisdiction goes live/indexed**
    — especially for `generic_fallback`/`best_effort` results. Real cost:
    turns part of the pipeline from fully automatic into something
    needing a human in the loop, at least for first-time jurisdictions.
  - **Platform-based trust tiers** instead of domain allowlisting — the
    named-vendor adapters (Granicus, Legistar, CivicClerk, Swagit,
    PrimeGov, etc.) all target products specifically sold to local
    governments, which is real (if imperfect) signal a naive domain
    check can't get from a URL shape alone; `generic_fallback` results
    would sit in a lower-trust tier by default under this framing.
  - **A curated known-jurisdiction list**, grown deliberately over time
    as real cities get manually confirmed — ties naturally into the
    already-planned "Coverage page" (Archive roadmap, below), which
    could double as this list's public face rather than being a second,
    separate thing to maintain.

  Deliberately not prioritized/sequenced yet — this section exists to
  make the shape of the risk visible, not to commit to a fix, per the
  user's own framing ("at some point").

## Bugs

- **PrimeGov's `_extract_jurisdiction()` still has no real structural fix
  for the SLC/Holladay false-positive — only patched for that one
  confirmed domain, not solved generally.** SLC's specific bug (every
  real `slc.primegov.com` meeting is fixed 2026-08-13 via a known-domain
  full override — see `BACKLOG_DONE.md`), but the underlying problem
  the earlier investigation surfaced is still real and open: an unscoped
  body-text search can't structurally tell a genuine page header from an
  agenda-item mention (confirmed against three real cities — OKC,
  Thousand Oaks, SLC — none of which separate cleanly by character
  position, and a bold-tag rule would fix OKC/SLC but miss Thousand
  Oaks's plain-prose header). **A fourth PrimeGov city with this same
  false-positive shape and no confirmed domain of its own would still
  hit the original bug** — the domain override only works because SLC
  happened to get reported and confirmed. Worth revisiting the
  structural options (bold-tag heuristic, etc.) against more real
  examples if this recurs, rather than adding a domain override per
  incident indefinitely.

- ~~**`find_platform_link()`'s fallback delegation could self-loop into
  real infinite recursion**~~ **Fixed 2026-08-12 — full detail in
  `BACKLOG_DONE.md`.** A same-page `#fragment` anchor (e.g. a "skip to
  content" accessibility link, present on nearly every Legistar page)
  used to resolve back to the current page and get delegated to again,
  recursing without bound. `find_platform_link()` now skips any candidate
  resolving to the same URL as `page_url`, closing this at the root for
  every caller.

- ~~**`CablecastAssetFinder` hardcodes jurisdiction as "Detroit, MI" for
  *every* Cablecast customer, not just Detroit**~~ **Fixed 2026-08-12 —
  full detail in `BACKLOG_DONE.md`.** Now derived per-customer from the
  already-parsed Remix `site` object instead of a hardcoded constant; a
  state suffix is only appended for a customer actually confirmed so far
  (Detroit, Charlotte — see the "no-state jurisdiction audit" item below
  for the general version of this gap). Not yet checked against a third
  real Cablecast customer, so `_extract_jurisdiction()`'s single-word-city
  assumption is worth revisiting once one turns up.

- ~~**Portland, OR's council agenda pages really do resolve correctly
  today — the resolve-level cache had no expiry, unlike its Archive-level
  counterpart, and was serving a stale, permanently-cached negative
  result from before that was true.**~~ **Fixed 2026-08-12 — full detail
  in `BACKLOG_DONE.md`.** `get_cached_resolution()` (`app/db/crud.py`) now
  expires a `video_found=False` row after an hour, mirroring the Archive's
  own `ARCHIVE_RECHECK_AFTER_NO_TRANSCRIPT` reasoning; a row that did find
  a video keeps no TTL.

- ~~**"Request Transcript from Audio" showed a misleading "no usable
  audio or video source" error that was actually just the transcription-
  request rate limit**~~ **Fixed 2026-08-12 — full detail in
  `BACKLOG_DONE.md`.** slowapi's 429 response body has no `ok`/`message`
  keys, so both duplicated copies of `runFeasibilityCheck()`
  (`app/static/player.js`, `archive/static/meeting_page.js`) used to fall
  through to the generic failure message. Both now check `res.status ===
  429` explicitly first and show real rate-limit copy instead.

- **Google Search Console flagged 3 "Videos" structured-data issues
  site-wide (alert received 2026-08-12)**: missing `thumbnailUrl`
  (critical — blocks video rich-result eligibility), plus `uploadDate`
  reported as both an invalid datetime value and missing a timezone
  (non-critical). Both trace to the same `VideoObject` JSON-LD block in
  [meeting_page.html:37-66](archive/templates/meeting_page.html:37-66):
  - `thumbnailUrl` is omitted entirely — already a known, named gap (see
    the comment at
    [meeting_page.html:29-36](archive/templates/meeting_page.html:29-36),
    which cross-references the same underlying missing-thumbnail
    limitation noted for `og:image` in `CLAUDE_BACKLOG.md`). No adapter
    in `app/platforms/` currently extracts or generates a thumbnail
    image for a meeting.
  - `uploadDate` is set directly from `page.date|tojson` at
    [meeting_page.html:52](archive/templates/meeting_page.html:52).
    `date` is stored as a bare `String(20)` 
    ([archive/db/models.py:32](archive/db/models.py:32)) and populated
    per-adapter as plain `YYYY-MM-DD` text with no time-of-day or
    timezone component — which is exactly what Google's "missing a
    timezone" complaint describes. schema.org itself accepts a
    date-only `ISO 8601` value, but Google's stricter rich-result
    validator wants a full datetime; fixing this means deciding on (and
    threading through) a real timestamp per meeting, since the app
    genuinely doesn't track meeting time-of-day today, only date. The
    separate "invalid datetime value" flag suggests at least one
    real row has a non-`YYYY-MM-DD` value in `date` (a bad adapter
    extraction) — worth cross-checking actual production values before
    assuming both complaints share one root cause.

- **YouTube-backed meetings' transcripts run through
  `scripts/fetch_youtube_transcripts.py` on a daily `launchd` schedule
  now (both shipped 2026-08-10, see BACKLOG_DONE.md) — real remaining
  gaps below, not "nothing runs automatically yet."** The server
  structurally cannot fetch these itself: confirmed live that yt-dlp,
  plain timedtext requests, *and* youtube-transcript-api (a different
  InnerTube recipe, tested specifically to close this question) are all
  blocked from Render's cloud IP, while the same library works perfectly
  from a home connection. Open follow-ups, in rough order:
  - **Whisper fallback for YouTube videos with no captions at all**
    (analysis option 8): extend the same local script to yt-dlp the
    *audio* (works from residential IPs) for queue entries whose
    caption fetch finds nothing, then feed local `faster-whisper` directly
    — **decided 2026-08-10: local, not the worker**, and deliberately
    **lower priority than everything else** in this backlog (most YouTube
    videos already have real captions; this only covers the rarer
    no-captions case). Not yet built.
  - **Human/source-side option (analysis option 9), user-side**: for
    big cities, ask the clerk for the caption file directly, or
    manually export from YouTube Studio-visible sources — the user is
    pursuing this angle themselves; `bulk_ingest.py`-style manual
    pushes can carry whatever comes back.

- ~~**PrimeGov's `_extract_jurisdiction()` regex wasn't scoped to the page
  header, so it could pick up an unrelated city name mentioned in agenda
  body text.**~~ **Fixed 2026-08-12 — full detail in `BACKLOG_DONE.md`.**
  `_extract_jurisdiction()` now strips `<script>`/`<style>` boilerplate
  and caps the search to the first 2000 characters of what's left
  (matching `_extract_date()`'s own convention), and `resolve()` no
  longer falls back to YouTube's `uploader` name when the page itself has
  no match — a page whose header doesn't fit the "City/County/Town of X"
  pattern (e.g. real "SALT LAKE CITY COUNCIL"-shaped headers) now
  correctly comes through with no jurisdiction rather than a wrong one.
- ~~**Jurisdiction display was verbose and inconsistent site-wide — "City
  of Napa, CA" everywhere read as redundant.**~~ **Fixed 2026-08-12 — full
  detail in `BACKLOG_DONE.md`.** A display-time Jinja filter
  (`jurisdiction_display`, backed by `archive/utils/
  jurisdiction_format.py`'s `format_jurisdiction_display()`) now drops a
  leading "City of "/"City " everywhere a stored jurisdiction renders;
  "County of X" and state-legislature-style names are untouched. What's
  actually stored is unchanged. The resolver's own client-rendered page
  has a small JS mirror in `app/static/player.js`.

- ~~**Swagit's title-parsing regex swallowed a "- Revised -"/"- Closed
  Session -" marker into the jurisdiction on Long Beach meetings**~~
  **Fixed 2026-08-13 — full detail in `BACKLOG_DONE.md`.** A lazy
  title-part match locked onto the first hyphen it could make work rather
  than the real city/state boundary, e.g. "Revised - Long Beach, CA"
  instead of "Long Beach, CA". Made the title-part match greedy so it
  always lands on the last hyphen before ", {State}". Live-reverified
  2026-08-13: re-resolving `longbeachca.new.swagit.com/videos/395182`
  fresh with the current code correctly returns `Long Beach, CA` — the
  fix itself is confirmed working, and the stale archived pages have
  since been corrected too — see "Bulk backfill of archived pages" in
  `BACKLOG_DONE.md`.

## `/meetings` search & saved items — UI gaps found 2026-08-11

- **"Save this meeting"/"Save this search" buttons render for every
  visitor regardless of sign-in status, and an anonymous click silently
  no-ops.** Confirmed 2026-08-12 while documenting which features are
  Clerk-gated for README.md: `archive/templates/meeting_page.html`'s Save
  buttons have no client-side signed-in check, and
  `archive/static/meeting_page.js`'s click handler (~lines 460-496) just
  leaves state unchanged on the `POST /api/account/save-meeting` 401
  (`_NOT_LOGGED_IN`, `app/main.py:744`) rather than surfacing a "sign in to
  save this" prompt. An anonymous visitor gets no feedback at all — the
  button just does nothing, indistinguishable from a silent failure. Same
  underlying gap presumably applies to the `/meetings` "Save this search"
  button. Worth deciding the fix alongside the item directly below (both
  are about this button not reflecting real state) — likely either a
  sign-in prompt on a 401, or hiding/disabling the button for anonymous
  visitors in the first place.

- **"Save this search" can silently save the wrong search, and gives no
  feedback that it's already been saved.** Reported by the user via two
  concrete scenarios: (1) type a query but don't hit Search, then click
  "Save this search" — nothing stops this, and what gets saved is
  whatever the *last-applied* search was (e.g. "All meetings" if none
  yet), not the just-typed, unsubmitted text; (2) search "Cameras", hit
  Search, hit Save, then type "Flock" without hitting Search again, hit
  Save again — silently re-saves "Cameras," not "Flock." Confirmed by
  reading the code: `archive/templates/meeting_list.html`'s Save button
  (`#saveSearchBtn`, lines 23-30) gets its `data-q`/`data-jurisdiction`/
  etc. (lines 24-26) from the *server-rendered, already-applied* `q`/
  `jurisdiction`/etc. template variables — i.e. whatever `/meetings` was
  last loaded with — not a live read of the search box's current DOM
  value. `archive/static/meeting_list.js`'s `wireSaveSearchButton()`
  (lines 6-44) then POSTs exactly those baked-in `data-*` values to
  `/api/account/save-search` on click (confirmed via
  `app/main.py:775-780` → `app/archive_client.py:220-236` →
  `archive/main.py:373-377` → `crud.save_search`,
  `archive/db/crud.py:1194`) — so the button's actual behavior is "save
  the search currently showing on this page," which only matches user
  intent if Search was just clicked. The label also never changes: it
  always reads "Save this search" regardless of whether this exact
  search was already saved (there's no "Saved"/"Unsave" state on this
  page — confirmed via the JS file's own header comment, which notes
  unsaving only exists on `/account/saved`, wired separately by
  `saved_items.js`), so a user also gets no cue they're about to create
  a duplicate.

  **User's own brainstormed fixes, not decided/built — worth weighing
  together since they overlap:** turn "Save this search" into "Unsave
  search" immediately after a successful save, reverting to "Save this
  search" the moment the query box or any filter changes; give the
  Search button itself a visual "ready to click" cue (glow/color) when
  the box/filters differ from what's currently applied, clearing once
  Search is clicked; conversely have the Save button/its bookmark icon
  light up once a search *has* been applied and is save-able. A
  "depressed vs. popped-up" (tape-deck button) visual metaphor was also
  floated for the same cue, matching the page's existing cassette-deck
  styling (`cassette-btn` class already used by both buttons, line 18 and
  the outline variant in `saved_items.html`). All riffing, not a chosen
  design — needs a real decision before building.

- **Meeting title/jurisdiction display: casing still inconsistent row to
  row — the state-abbreviation and truncation parts of this gap shipped
  2026-08-11, see BACKLOG_DONE.md.** State names are now normalized to
  their 2-letter abbreviation at Archive ingest time
  (`archive/utils/jurisdiction_format.py`'s `normalize_state_suffix()`,
  wired into `archive/db/crud.py`'s `_find_or_create_page()`), and long
  titles/jurisdiction lines now truncate with an ellipsis on `/meetings`
  (`.calendar-candidate-main a` / `.calendar-candidate-date` in
  `style.css`) instead of wrapping. **Still open, deliberately not
  touched**: city/county/meeting-body name casing itself. That's
  effectively unbounded (tens of thousands of real values) with real
  edge cases a blind `.title()`/casing rule gets wrong (acronyms like
  "MTA"/"ZBA", multi-word or apostrophe'd city names) — every adapter
  still stores whatever casing the source page used, unchanged, and
  fixing that safely would need either a real per-value dictionary/
  exception list or a narrower heuristic (e.g. something like
  `vtt_parser.py`'s existing `normalize_shouting_caption()` ALL-CAPS
  detector, which only re-cases when its own heuristic is confident,
  rather than a blanket `.title()`) — not attempted this pass, since a
  wrong guess here silently corrupts a real name with no easy undo.

  **Also flagged by the user 2026-08-12, real and separate from the above:
  some jurisdictions never had a state at all to begin with** —
  `normalize_state_suffix()` only fires on a trailing `", <State>"`
  suffix, so a jurisdiction with no state component just passes through
  untouched. **Audited, designed, and partly built 2026-08-12 — full
  detail in `BACKLOG_DONE.md`.** A new shared module,
  `app/utils/jurisdiction_enrich.py`, fills in a missing state using real
  US Census Bureau data (counties, places, and ZIP-to-county/ZIP-to-place
  crosswalks, ~3.2MB, checked into the repo) plus a small confirmed-domain
  registry for names that are ambiguous nationally (e.g. "Detroit" is a
  real city in 4 different states) — tried in priority order: confirmed
  domain → unambiguous name lookup → a ZIP-anchored address found in page
  text, scoped to never let a county government's own city-shaped mailing
  address stand in for the county itself (see `BACKLOG_DONE.md` for why
  that's a real, specific trap, not a hypothetical one). Wired into
  **Granicus** (the largest single source of this gap) and **Cablecast**
  so far.

  **Update 2026-08-12: fully wired now, every adapter identified in the
  audit — full detail in `BACKLOG_DONE.md`.** Legistar, PrimeGov, eScribe,
  CivicWeb, and LIMS all now call the same shared
  `jurisdiction_enrich.enrich_jurisdiction_text()`; CivicClerk gets a
  narrower fallback (`lookup_city_state()` when its own API's
  `location.city` is present but `location.state` is empty) since its
  data already arrives as separate structured fields rather than free
  text. Two real bugs in the shared module were found and fixed along the
  way (an "Oklahoma City"-shaped double-normalization collision with
  "Oklahoma borough, PA", and a since-reverted PrimeGov window-cap
  regression — see the bug entry above, still genuinely open). Full suite
  green (551 tests); live-verified against real Cablecast, Granicus,
  PrimeGov, and CivicWeb pages.

  **Still open, real gaps not touched by either pass**: YouTube's
  `uploader`-as-jurisdiction and the cases where no jurisdiction is set at
  all (`generic_fallback.py`, `civicplus.py`) are different problems this
  module doesn't address (not a missing state — a wrong or absent field
  entirely). CivicClerk's new fallback is schema-verified but not
  content-verified — no real customer with a blank `location.state` has
  turned up yet to confirm it fires correctly in practice (covered by a
  synthetic test only, per `tests/test_civicclerk.py`).

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
## Platform coverage — open questions

- **Seattle Channel (`seattlechannel.org`) — new platform, not supported
  at all today, flagged by the user 2026-08-12 with a real example**
  ([seattlechannel.org/.../city-council-all-videos-index?videoid=x189286](https://www.seattlechannel.org/mayor-and-council/city-council/city-council-all-videos-index?videoid=x189286),
  "City Council 8/11/2026"). User's own diagnosis was right on both
  counts, confirmed live: the page really is "one video with a lot of
  good detail" sitting above "a whole feed of videos" for *other*
  meetings, and the `?videoid=x189286` query param really is the key
  that disambiguates which one is wanted.

  **Root cause of "no video found" today, confirmed via direct `curl`
  (plain HTTP, no JS needed)**: every video on the page — the requested
  one *and* the whole feed below it — has its real direct `.mp4` URL
  (`video.seattle.gov/media/council/{file}.mp4`) sitting only inside an
  inline `onclick="javascript:loadJWPlayer7('//video.seattle.gov/...',
  ...)"` string, never as a real `href`/`src` attribute. That's exactly
  what neither `media_scan.scan_media_urls()` nor
  `find_platform_link()` look inside — both are `href`/`src`-attribute
  scanners, so this page has zero matches for either, which is why
  today's `generic_fallback.py` result comes back completely empty
  rather than finding the *wrong* video from the feed — there's nothing
  in an `href`/`src` for it to (correctly or incorrectly) find at all.

  **What a real adapter has to work with here is unusually rich for an
  unsupported platform** — confirmed present in the raw HTML for *every*
  feed item, not just the requested one:
  - `<meta name="video_date" content="2026-08-11">` — a clean,
    machine-readable date, no parsing needed.
  - The page's own `<title>` (`"City Council 8/11/2026 |
    seattlechannel.org"`) already matches the requested video exactly,
    not the feed's first/most-recent item.
  - Each feed item's `loadJWPlayer7(...)` call carries, as plain
    JS-string arguments: the direct `.mp4` URL, a full real agenda
    description as HTML (e.g. this meeting's: "Call to Order; Roll
    Call; Proclamation: Susan Han Day; ...; CB 121254: relating to
    rental agreement regulation; ..."), title, date, duration, a numeric
    ID, and a relative SRT caption path
    (`documents/SeattleChannel/closedcaption/2026/{file}.srt`) — a real
    caption file per meeting, not just a maybe.
  - **The disambiguation signal is exactly what the user guessed**: each
    feed item's wrapping `<a href="…?videoid={id}" onclick="…">` pairs a
    real `videoid` with its own `loadJWPlayer7(...)` call — so scoping
    extraction to the one `<a>` whose `videoid` matches the URL's own
    query param (not "the first `.mp4` on the page," which could easily
    be a *different* meeting from the feed) is the reliable way to get
    the right video, confirmed consistent here: the top-of-page player
    init and the matching feed item both point at the identical
    `council_081126_2022663.mp4`.

  **Open question, not yet checked**: what happens when a Seattle
  Channel URL has no `?videoid=` at all (just the bare index page) —
  the user's own framing ("a video ID fed in with the URL *sometimes*")
  implies this is a real, not-yet-seen case, possibly needing the same
  "ambiguous, here are the candidates" handling `CalendarPageError`
  already gives Legistar calendar pages, rather than silently guessing
  the first/most-recent feed item.

  **Found, and it's a real upgrade — user's own alternate suggestion,
  confirmed live 2026-08-12**: the same meeting at
  [seattlechannel.org/videos?videoid=x189286](https://www.seattlechannel.org/videos?videoid=x189286)
  (vs. the original `/mayor-and-council/city-council/city-council-all-
  videos-index?videoid=...` path) has **zero feed items** (`curl`
  confirms 0 matches for the `tiledThumbnailItem` class that made the
  other URL confusing) — "the only city council video is the top one,"
  exactly as the user described. This isn't just a cleaner page, it's a
  structurally simpler extraction target:
  - The video's real source config sits in one plain
    `jwplayer('vidPlayer').setup({ sources: [{file:
    "//video.seattle.gov/media/council/council_081126_2022663.mp4", ...}],
    tracks: [{file: "documents/seattlechannel/closedcaption/2026/
    council_081126_2022663.srt", kind: "captions", ...}], ga: {idstring:
    'City Council 8/11/2026'} })` call in a `<script>` tag — title,
    direct mp4, and caption path all in one well-scoped JS object literal,
    no per-feed-item disambiguation needed at all (same "real JSON/JS
    object embedded in a script tag" shape this codebase already parses
    elsewhere — Cablecast's `window.__remixContext`, ChampDS's
    `playapi.champds.com` response).
  - The SRT caption file is *also* separately reachable as a plain
    `<a href="documents/SeattleChannel/closedcaption/2026/council_081126
    _2022663.srt">` inside `.episodeDescription` — a real `href`
    attribute this time, confirming the user's "the caption file is
    right there downloadable in the video description" observation and
    giving a second, even-simpler extraction path for captions alone.
  - **A genuine bonus found while checking**: `.seekItem` elements
    (`<a class="seekItem" href="#" data-seek="8865">CB 121254: relating
    to rental agreement regulation - 2:27:45</a>`) give real per-agenda-
    item *timestamps* (`data-seek`, in seconds) paired with real item
    text — unlike Legistar's untimed agenda table (above), this is
    exactly the shape `ResolvedMeeting.agenda_items` wants
    (`List[TranscriptSegment]`, real start times), not a compromise or
    a new field needed.
  - Same `?videoid=` disambiguation question as the other URL still
    applies here (what happens with none present) — not yet checked
    whether `/videos` bare (no query param) behaves differently than
    the `all-videos-index` page did.

  **Given this page is both cleaner and richer, it's the better build
  target of the two** — worth confirming a second real `/videos?videoid=`
  example before writing `seattlechannel.py`, same convention as
  everywhere else in this file, but this one URL shape alone already
  looks sufficient for direct video + real captions + timestamped agenda,
  better coverage than several already-shipped adapters manage.

- **`generic_fallback.py`'s YouTube-embed branch never attempts *any*
  page-level metadata backfill — a real, confirmed gap distinct from the
  already-known yt-dlp/Render-IP-block issue, found via a real example
  2026-08-12**: user praised the resolver's handling of an unsupported
  site overall
  ([/m/meeting-732f78](https://redtaperecordings.com/m/meeting-732f78),
  original: [crrma.org/information/meetings/board/2025-11-12](https://www.crrma.org/information/meetings/board/2025-11-12),
  El Paso's Camino Real Regional Mobility Authority) but flagged that the
  result shows "Untitled meeting" with zero jurisdiction/date, which
  "looks funny and clutters search" — asked for a better convention for
  this case, even suggested pulling the video/channel name from YouTube,
  or "grabbing the subdomain/url from the source or scraping the text of
  the source."

  **Confirmed two separate, stacked causes, not one**:
  1. `_extract_info()`'s yt-dlp call is blocked by YouTube's anti-bot
     check from Render's IP (already documented, `youtube.py:78-113` —
     this is the *existing*, harder infrastructure problem, not new here)
     — so the channel/video-title metadata the user's first suggestion
     wants genuinely isn't available today. Not re-opening that fight in
     this entry.
  2. **The real, easy gap**: when `generic_fallback.py` finds a YouTube
     embed ([generic_fallback.py:145-157](app/platforms/generic_fallback.py:145-157)),
     it delegates straight to `YouTubeAssetFinder.resolve_video_id()` and
     does *nothing else* — no fallback to the source page's own `<title>`
     tag, no URL-path parsing, nothing. Confirmed live what's sitting
     right there, unused, on this exact example: CRRMA's own `<title>`
     tag reads **"Camino Real Regional Mobility Authority | El Paso,
     Texas"** (a real, usable jurisdiction, `curl`'d directly, no JS
     needed) and the source URL's own path is
     `/information/meetings/board/2025-11-12` — a real ISO-shaped date
     and a real meeting-type word ("board"), sitting in the URL itself,
     unparsed. Exactly the user's second suggestion, and it would work
     here without any new network call — this data is already in hand
     (the same `html`/`url` `generic_fallback.py` already fetched) by the
     time `resolve()` gives up on a real title. Legistar's equivalent
     fallback path already does something structurally similar
     (`_extract_page_meeting_info()` reading the page's own `<title>`/RSS
     as a metadata source when the delegated platform's own is missing/
     bad) — same pattern, just never built for `generic_fallback.py`'s
     YouTube branch specifically.
  3. Both current YouTube-branch gaps compound: with #1 blocked, the
     genuinely-known-good fallback (#2, unbuilt) is the only real path
     to a usable title/jurisdiction here today.

  **User's exact target output for this specific example, 2026-08-12** —
  concrete enough to implement directly against, not just "do something
  better": `Meeting name: Camino Real Regional Mobility Authority
  11/12/2025` / `Jurisdiction: El Paso, TX`. Maps cleanly onto the raw
  `<title>` tag confirmed above (`"Camino Real Regional Mobility
  Authority | El Paso, Texas"`) split on `|`: the part before is the
  body/org name (paired with the URL-path date for the title), the part
  after is the jurisdiction. `"El Paso, Texas"` → `"El Paso, TX"` should
  already fall out for free if this jurisdiction value gets run through
  the existing `normalize_state_suffix()`
  (`archive/utils/jurisdiction_format.py`, already applied to every
  normal ingest via `_find_or_create_page()` in `archive/db/crud.py`)
  rather than stored raw — not a new utility to write, just needs this
  new fallback path to actually call it. Worth checking a second `{org} | {City, State}`-shaped
  `<title>` on another real generic-fallback site before assuming this
  exact split-on-`|` shape generalizes, same convention as everywhere
  else in this file — CRRMA is the only confirmed example so far.

  **Separately, a real UI/copy question, independent of whether #2 above
  ever gets built**: what should render when metadata truly can't be
  found by any method? Today's convention is a bare "Untitled meeting"
  (`meeting_page.html:98`'s dropdown and `meeting_list.html:90`'s browse
  listing both share the exact same `m.title or "Untitled meeting"`
  fallback) — user's suggestion: something more like "Temporary Name:
  meeting-732f78" that signals "we know this is incomplete" rather than
  reading as broken/empty. Distinct from the extraction gap above — worth
  deciding even if #2 closes most real cases, since some will always slip
  through (a truly metadata-free source page, e.g. a bare unlabeled video
  iframe with no page `<title>` and a non-date-shaped URL).

  **Update 2026-08-13, still broken in prod, confirmed again with stronger
  evidence — this is the next thing to actually build, not just study
  further**: user re-tested the same
  [/m/meeting-732f78](https://redtaperecordings.com/m/meeting-732f78) page
  live in prod and it's still "Untitled meeting" with no jurisdiction (code
  confirms #2 above was never implemented — no `title`/`jurisdiction`
  handling exists anywhere in `generic_fallback.py` today, only the
  original YouTube-delegate call). Re-`curl`'d all 5 known CRRMA board
  URLs directly (the original 2025-11-12 one plus four more the user gave —
  2026-05-13, 2026-04-08, 2026-03-11, 2026-01-28) and every single one
  returns the exact same `<title>Camino Real Regional Mobility Authority |
  El Paso, Texas</title>` — confirms the split-on-`|` shape is stable
  across at least 5 real examples now, not just 1, closing the "worth
  checking a second example" caveat above (for this exact site; still only
  one *site* overall, per this file's usual convention of not
  over-generalizing from one platform).

  **New signal found this pass, richer than the `<title>` tag alone**: the
  page body itself has a real, semantically-marked "Notice of meeting"
  block — `<h1 id="notice-of-meeting">NOTICE OF MEETING</h1>` followed by
  `<h2 id="november-12-2025-----900am">November 12, 2025 - 9:00am</h2>`
  and a `<p>` reading *"A meeting of the CRRMA Board of Directors will be
  held on Wednesday November 12, 2025, at 9:00am in the 2nd Floor Main
  Conference Room of El Paso City Hall, located at 300 N. Campbell, El
  Paso, Texas 79901."* — confirmed live via `curl`, present identically
  (modulo the date) on all 5 URLs, and cross-confirmed by the user against
  the linked agenda PDF too. This is a *better* jurisdiction/date source
  than the `<title>` tag for this site specifically: it has the full
  street address (useful if jurisdiction enrichment ever wants
  address-level precision, not just city/state) and an unambiguous
  same-page date independent of the URL's own `YYYY-MM-DD` path segment
  (today's plan already reads the date from the URL path per point #2
  above — this is a second, corroborating same-page source, not a
  replacement).

  **Naming preference, user's own words 2026-08-13**: whatever the meeting
  title ends up being, "I'd expect it to have CRRMA in there somewhere" —
  e.g. `"CRRMA Board of Directors"` or `"Camino Real Regional Mobility
  Authority Board"` rather than just the bare org name from the `<title>`
  tag. The Notice-of-meeting `<p>` text above already contains "CRRMA
  Board of Directors" verbatim, so this naming preference and the new
  signal solve each other — worth preferring that phrase (or a regex
  extracting `"{ACRONYM} Board of Directors"`/`"{Org} Board"` from the
  notice paragraph) over the bare `<title>`-derived org name when both are
  available.

- **CHAMP/ChampDS (`play.champds.com`) — new platform, not supported at
  all today, flagged by the user 2026-08-12 via a real Atlanta, GA
  example**
  ([play.champds.com/atlantaga/event/1227](https://play.champds.com/atlantaga/event/1227),
  a real "Committee on Council Meeting"). Confirmed why the resolver
  can't find the embedded video: exactly the same shape as the Chicago
  ELMS case just below — the video is injected client-side from a
  separate JSON call, real server HTML has none of it
  (`curl`'d directly, confirmed empty — every field on the page,
  `#h3EventTitle`/`#h4EventDate`/the player itself, starts blank in the
  markup and gets filled in by `cds.event.js` after load).

  **Traced the real API, confirmed live, no headless browser needed** —
  same URL as the page itself, just on a different host:
  `https://playapi.champds.com/{customer}/event/{id}` (i.e.
  `window.location.host` with `api.` spliced in before the last two
  domain labels — `play.champds.com` → `playapi.champds.com`; see
  `cds.common.js`'s `HOST = hosts[0] + 'api.' + hosts[1] + '.' + hosts[2]`
  for the exact client-side logic this mirrors) returns a complete,
  well-structured JSON payload, plain GET, no auth, no special headers:
  - `Event.EventTitle` ("Committee on Council Meeting"),
    `Event.EventDateTimeCustomerLocal` (real local date/time, already
    customer-timezone-adjusted — no UTC conversion needed),
    `Customer.CustomerName` ("Atlanta GA" — jurisdiction),
    `Board.BoardName` ("Committee on Council" — the meeting body/type,
    same kind of richer sub-classification flagged as missing from
    Legistar above).
  - **Two independent, both-confirmed-live ways to get real video**:
    (1) `MediaInfo.DownloadURL` (e.g.
    `/DOWNLOAD-MEDIA/atlantaga/eventmainmedia/{id}`, relative to
    `play.champds.com`) — a direct, unauthenticated MP4 download,
    confirmed 200 with a real `Content-Length`/`Content-Disposition` on
    **two different event IDs** (1227 from this investigation, 1233 from
    a second URL the user separately supplied mid-investigation) — this
    is the simpler, more robust option, and probably what `video_format`
    should map to (plain `mp4`, like every other direct-file case this
    app already supports, no new player-integration work needed unlike
    Chicago's Vimeo gap below).
    (2) `MediaInfo.VOD2` (a relative HLS path, e.g.
    `/VOD/event/AtlantaGA/1227/.../master.m3u8`) combined with
    `ServicesAndMachineInfo["8"].URLBase` (e.g.
    `https://securestream10.champds.com`) — confirmed this reconstruction
    exactly matches the real URL the page's own player actually requests
    (`vjs2026` player's own console log: `"USING VOD2! {clipURL:
    https://securestream10.champds.com/VOD/event/Atlan.../master.m3u8}"`)
    — a real `m3u8`, this app's already-supported format, but needs the
    numbered `securestream{N}.champds.com` host read out of
    `ServicesAndMachineInfo` per-customer rather than hardcoded (it's `7`
    for regular playback services in this response, `10` specifically for
    the VOD2/HLS pairing — not yet clear if that number is
    customer-specific or fixed platform-wide).
  - **Agenda items, if present, ride in the same JSON** under
    `Agenda.AgendaItems` (per `cds.event.js`'s own
    `if(data.Agenda && data.Agenda.AgendaItems)` check — no separate
    endpoint) — **unconfirmed with a positive example**: this specific
    Atlanta meeting has none (`Event.AgendaStyleMask: 0`, no `Agenda` key
    in the response at all), so the real per-item shape (timestamped or
    not?) is still unknown, same "flagged, not assumed" gap as CivicClerk/
    eScribe's caption fields.

  **Only one city checked so far (Atlanta, GA)** — per this repo's own
  convention, worth confirming the `playapi.` host-splicing trick and the
  JSON shape hold on a second, independently-run ChampDS customer site
  before writing `champds.py` for real, not assuming one city
  generalizes. Otherwise this is about as fleshed-out as a pre-build
  investigation gets in this file — a real adapter here looks
  straightforward (plain `aiohttp` JSON GET, no Cloudflare/JS-rendering
  hurdle found, direct-mp4 option needs no new frontend work at all).

- **Chicago's City Clerk ELMS (`chicityclerkelms.chicago.gov`) is a real,
  strong dedicated-adapter candidate — found 2026-08-10 while confirming
  the generic fallback correctly caught it (it did, as an "unsupported
  gate," per user testing).** The video (a real Vimeo link) never showed
  up because the page injects it client-side from a separate API call
  (`data.videoLink`) — the raw server HTML has zero mention of "vimeo,"
  confirmed directly (a real curl of the meeting page, then grepping for
  the string, found nothing; the JS embedding it references
  `data.videoLink.forEach(...)`). Traced the real API the JS calls:
  `https://api.chicityclerkelms.chicago.gov/meeting-agenda/{meetingId}`
  — a genuine public, unauthenticated, no-headless-browser-needed JSON
  endpoint (confirmed live via plain `curl`, real response), returning:
  `videoLink` (the real Vimeo URL), `agenda.groups[].items[]` (real
  structured items — matter title, action taken, vote type — but **no
  timestamps**, so still not clickable-to-a-moment agenda_items the way
  LIMS's are), `files[]` (real PDF attachments including a real
  "Agenda"-typed one), `date`, `body` (jurisdiction), `attendance`.

  **Real, two-part reason this isn't a quick fix**: (1) building
  `chicago_elms.py` itself is straightforward (a plain `aiohttp` GET
  against that API, same shape as LIMS's JSON-endpoint step, no
  Cloudflare/headless-browser complication found so far); but (2) this
  app has **zero existing Vimeo playback support** — no adapter, and no
  frontend logic for it at all. YouTube's iframe-embed + Player API
  integration was itself a real, distinct piece of work (see
  `app/static/player.js`'s `initYouTubeVideo()`); Vimeo would need its
  own equivalent (Vimeo's own Player SDK/iframe embed — a showcase URL
  like `vimeo.com/showcase/citycouncil?video={id}` is not a raw file any
  more than a YouTube link is). Building the adapter without the
  playback piece would just produce a `video_url` nothing can actually
  embed. Whether Vimeo captions are even fetchable at all is also
  unconfirmed — no positive example checked yet, same "don't claim a
  caption path works without a positive example" convention as every
  other adapter here.

  **Update 2026-08-11 (Wave 2 survey): the API/data half is now fully
  unblocked with three fresh confirmed real examples**, meetingId
  confirmed to be a GUID (not a plain integer as the shape above might
  imply) — `?meetingId=9DB35AFF-9811-ED11-82E3-001DD80682F6` (2020-09-09
  City Council), `?meetingId=DCB45AFF-9811-ED11-82E3-001DD80682F6`
  (2021-10-14 City Council), `?meetingId=0852FF86-2DF4-ED11-A7C6-001DD806AE67`
  (2023-05-15 City Council) — all three confirmed via the real API to
  have a populated `videoLink` (Vimeo). **`transcriptLink` is present in
  the API schema but empty on all three samples** — still no positive
  caption example *from Chicago's own ELMS API* for this platform,
  consistent with the "don't claim a caption path works without a
  positive example" note above. Part (2), Vimeo playback support, is
  unchanged and still the real blocker.

  **Update 2026-08-11 (part 2): "are Vimeo captions fetchable at all"
  is now answered — yes, confirmed live — via a different city, not
  Chicago's own ELMS instance.** Chicago is also not a one-off: at least
  four other real US city council channels host meeting video directly
  on Vimeo, confirmed live via `vimeo.com/{account}` channel pages —
  **Salisbury, NC** (`vimeo.com/channels/coscouncil`), **Rockland, ME**
  (`vimeo.com/rocklandmaine`), **Spokane, WA**
  (`vimeo.com/spokanecitycouncil`), **Corvallis, OR**
  (`vimeo.com/cityofcorvallis`), and **Wilson, NC** (`vimeo.com/wilsonnc`)
  — so a general Vimeo playback+caption adapter would have more than one
  beneficiary. Salisbury's real 7/21/2026 meeting
  (`vimeo.com/1212025580`) has a live "CC/subtitles" toggle in the
  player; toggling it (confirmed via real browser, not a plain HTTP
  client — see below) triggers a request to a signed
  `captions.vimeo.com/captions/{id}.vtt?expires=...&sig=...` URL that
  returns **real, populated, correctly-timed English WEBVTT** — genuine
  per-cue dialogue ("I'll go ahead and call the special meeting to order
  on July 21st, 2026...."), not placeholder or blank content.

  **Real caveat this surfaces**: that signed caption URL is only
  discoverable through the player's own client-side config — a plain
  `aiohttp`/WebFetch request to `player.vimeo.com/video/{id}/config`
  (where that URL would normally be found) returns a **403**, and
  `vimeo.com/{id}` itself sometimes serves a real Cloudflare "Verify you
  are human" checkbox challenge (hit live on the Spokane sample this
  same check) — this app must never attempt to auto-solve that. So
  fetching Vimeo captions server-side, whenever a real example is
  eventually built against, likely needs the same real-headless-browser
  approach `headless_browser.py` already built for Minneapolis LIMS/SLC
  (a real Chromium render to let the player load and capture the signed
  URL it requests), not a plain HTTP client the way Granicus/Swagit/
  CivicClerk captions are fetched today — and even then, may not work
  100% of the time if the Cloudflare challenge is probabilistic rather
  than consistent. Unconfirmed whether Chicago's own ELMS-embedded Vimeo
  player behaves the same way as these channels' pages, or whether the
  showcase-embed shape it uses (`vimeo.com/showcase/.../video/...`)
  differs.

  **Update 2026-08-12: a real Chicago-native showcase-shaped example is
  now in hand, exactly the case flagged as unconfirmed just above** —
  user tried
  [chicityclerkelms.chicago.gov/Meeting/?meetingId=B2E99313-3D76-F111-AB0C-001DD80BE073](https://chicityclerkelms.chicago.gov/Meeting/?meetingId=B2E99313-3D76-F111-AB0C-001DD80BE073)
  directly, expecting the resolver to find, embed, caption, and offer
  AI-transcription on its Vimeo video. Confirmed via the same real API:
  `videoLink: ["https://vimeo.com/showcase/8925576?video=1210310337"]`
  — real "Committee on Budget and Government Operations" meeting,
  2026-07-16, `transcriptLink` empty (`[""]`) same as every other sample
  so far. This *is* the `vimeo.com/showcase/.../video/...` shape the
  entry above hadn't tested yet — but only the data side; whether its
  caption-fetching (signed URL + possible Cloudflare challenge) behaves
  the same as the channel-page samples above is **still unconfirmed**,
  same real-browser check needed, not attempted in this pass.

  **Clarifying the user's third ask ("use it for... AI transcription
  requests") — this is not a separate blocker from the captions one,
  it's the same one.** On-demand Whisper transcription needs a real
  probeable audio/video *file* URL (what `probe_duration()`/
  `extract_chunk_audio()` work against for every other platform), and
  Vimeo doesn't expose that any more directly than it exposes captions —
  both live behind the same signed `player.vimeo.com/video/{id}/config`
  response the entry above already found returns a plain **403** to a
  non-browser request. So "embed the video" (needs a new Vimeo
  player/iframe integration, `app/static/player.js` has none today) and
  "captions + AI-transcription audio" (both need getting past the same
  signed-config/Cloudflare wall) are two separate pieces of work, not
  three — worth keeping that framing when this eventually gets built,
  so the audio-extraction piece isn't accidentally re-investigated as if
  it were a new, unrelated problem.

  **Fourth confirmed example, same day**:
  [?meetingId=DF5C52EA-0D6B-F111-A823-001DD8019941](https://chicityclerkelms.chicago.gov/Meeting/?meetingId=DF5C52EA-0D6B-F111-A823-001DD8019941)
  → `videoLink: ["https://vimeo.com/showcase/citycouncil?video=1209979957"]`
  — full "City Council" body this time (not a committee), and notably
  the showcase identifier is a human slug (`citycouncil`) rather than
  the numeric one (`8925576`) from the Budget committee example above —
  confirms the `vimeo.com/showcase/{slug-or-id}?video={id}` shape holds
  across different showcase-ID styles, not just one body's own naming.

- **Phoenix's Legistar instance (`phoenix.legistar.com`) — root cause
  now confirmed structural, not one ambiguous sample.** Domain routing
  itself is confirmed correct (`phoenix.legistar.com` matches
  `_is_legistar_domain()`, so `LegistarAssetFinder` claims it as
  intended, not a routing bug). Original check (2026-08-10,
  `MeetingDetail.aspx?ID=1425831...`) found a `videolink` anchor with no
  `onclick` at all, `data-running-text="In progress"` despite being over
  a month stale — ambiguous at the time. **A 2026-08-11 Wave 2 survey
  resolved the ambiguity: 18 real Phoenix Legistar meetings checked
  (Formal Meetings, Policy Sessions, a Subcommittee), spanning
  2020–2026, every single one server-renders
  `class="audioDownloadNotAvailableLink"` / "Not Available" for video —
  and the original ID=1425831 URL now 410 Gones entirely.** This is
  Phoenix-wide, not one meeting's quirk. The real recordings exist and
  are public — just never linked from Legistar's own page — on Phoenix's
  own YouTube channel instead (e.g. `youtube.com/watch?v=srjuXI5vGuw`,
  confirmed live, "Phoenix City Council Formal Meeting July 1, 2026",
  matching the same meeting ID=1425831 was for). **Independently, the
  same symptom — Legistar video column always empty, real recording
  only on a separate city YouTube channel — was also found on
  Philadelphia (`phila.legistar.com`) and Albuquerque
  (`cabq.legistar.com`'s "GOV TV" channel)** during the same survey, so
  this may be a general "Legistar city with a non-Granicus video vendor"
  case worth handling once, not three separate one-offs. **The fix is
  not a Legistar parser change** (there is nothing in the page to parse
  differently — the video link genuinely isn't there) **but a
  YouTube-channel search/match fallback** for Legistar cities where the
  video link is absent: given a known channel + the meeting's date/title,
  find the matching upload. Needs a product decision on how that channel
  gets configured per city (hardcoded per the size/political-importance
  of Phoenix specifically, per the user's own suggestion, vs. a general
  mechanism) before writing it. Also worth noting while checking:
  Legistar's own adapter never attempts agenda-item parsing at all (by
  design, it only ever delegates to the underlying video platform for
  that), so a Legistar page never showing agenda items is expected
  behavior, not a second bug to chase.

- **El Paso, TX studied as a real test case for the channel-discovery
  question above — user's idea 2026-08-12, prompted by the CRRMA
  "Untitled meeting" entry earlier in this file**: given a known Vimeo
  (or YouTube) channel with no direct government-page link, can search
  engines find the .gov page that embeds/links to a specific video?
  **Real answer for El Paso specifically: didn't need to find out** — a
  much better path exists and makes the search-engine approach
  unnecessary here. `www.elpasotexas.gov/videos/` is a plain,
  server-rendered page (confirmed via direct `curl`, no JS needed) that
  directly links out to **every one of the city's Vimeo showcases**, one
  per body — `vimeo.com/showcase/{ad-hoc, agenda-review, boac,
  budget-hearing, building-standards, city-plan, crrma, csc, fhtf, foac,
  open-space, special-cc, veterans-affairs}` — plus the city's real
  YouTube channel (`youtube.com/user/cityofelpasotx`). Notably,
  `vimeo.com/showcase/crrma` ("Camino Real Regional Mobility Authority")
  exists too — the *same* CRRMA meetings from the earlier "Untitled
  meeting" entry may have a second, better-organized source here, worth
  checking directly against that specific 2025-11-12 meeting before
  assuming CRRMA's own bare YouTube embed is the only source.

  **The search-engine reverse-lookup idea itself, tested directly, came
  back inconclusive/negative** — worth recording since it answers the
  user's actual question, not just the El Paso side-question: neither
  `site:elpasotexas.gov vimeo.com` nor a direct search for
  `"vimeo.com/eptx"` / a specific showcase URL surfaced the
  `elpasotexas.gov/videos/` page that's proven to link to it. Not
  conclusive proof the technique never works elsewhere (one real city,
  one real search backend, on one particular day), but real, live
  evidence that it isn't reliable enough to lean on as a general
  strategy — a direct, methodical crawl of a known city's own domain
  (the way `elpasotexas.gov/videos/` was actually found here, via a
  *different* real search query about El Paso's video setup generally,
  not a reverse-lookup of the Vimeo URL itself) looks like the more
  promising general pattern than reverse image/embed search.

  **Still blocked on the same foundational gap already flagged for
  Chicago ELMS above**: this app has zero Vimeo playback support today
  (no adapter, no frontend player integration) — building real support
  for any of this needs that piece regardless of how the specific video
  gets found. A per-showcase video list (real titles/dates per meeting)
  wasn't confirmed either — `vimeo.com/showcase/{id}` pages are
  JS-rendered (confirmed: `curl` returns only the showcase's own title,
  no individual video data), so listing real per-meeting entries would
  need either Vimeo's own API or a headless-browser fetch, not yet
  checked which.

- **Legistar's own MeetingDetail.aspx page carries real metadata that
  `LegistarAssetFinder` never scrapes at all — confirmed live 2026-08-12
  on a real example the user flagged**
  ([mesa.legistar.com/MeetingDetail.aspx?ID=1428059](https://mesa.legistar.com/MeetingDetail.aspx?ID=1428059&GUID=C6D3581F-B224-4A1C-A59D-0885C238FD52&Options=info|&Search=),
  a real Mesa, AZ City Council meeting, video delegated to YouTube). The
  resolved page today shows title "City Council" / jurisdiction "City of
  Mesa" / date 2026-08-10 — technically correct (from
  `_extract_page_meeting_info()`'s `<title>` parse,
  [app/platforms/legistar.py:236-260](app/platforms/legistar.py:236-260)),
  but weak, and the user (correctly) expected more from that link. The
  live page itself has real, server-rendered content this adapter
  currently ignores entirely:
  - **`Published agenda: Agenda / Accessible Agenda`** — a direct link to
    the real agenda document, sitting right in the "Meeting Details"
    table. `ResolvedMeeting.agenda_link`
    ([app/platforms/models.py:42-48](app/platforms/models.py:42-48)) exists
    for exactly this ("a single raw agenda-document URL... found a link
    that looks like the agenda") and other adapters already populate it —
    Legistar's own adapter never does. This is the cheapest real win here:
    one new selector, no new field needed.
  - **`Meeting location: Study Session / Special Council Meeting`** — a
    real distinguishing sub-type Legistar tracks that the generic
    `{jurisdiction} - Meeting of {body} on {date}` `<title>`/RSS pattern
    (the adapter's only metadata source today) doesn't carry at all. Every
    Legistar meeting from this body would currently title identically
    ("City Council"), even a Study Session vs. a regular session vs. a
    Special Meeting — this field is exactly what would tell them apart.
  - **A real "Meeting Items" table** (`File #`, `Agenda #`, `Type`,
    `Title`, columns) with substantive per-item text — e.g. this meeting's
    real items were "Canvassing, declaring, and adopting the results of
    the Primary Election held on July 21, 2026... Resolution No. 12562"
    and a development-agreement resolution for "an AC Hotel by Marriott."
    Doesn't cleanly fit `agenda_items` (typed `List[TranscriptSegment]` —
    real per-item *timestamps*, like Granicus's AgendaViewer.php chapter
    markers) since Legistar's table has no per-item time offset, only
    ordering. **User's call 2026-08-12, after weighing the shape
    mismatch: probably not worth pursuing** — the real agenda document
    (`agenda_link`, above) already covers the "what was on the agenda"
    need without a new untimed-items shape just for this one platform.
    Left here for context, not as an open TODO.

- **Baltimore's Legistar instance (`baltimore.legistar.com`) — how often
  does a meeting actually have video in the attachments table, and is
  there a better way to find it when it's missing?** Prompted by the user
  noticing, 2026-08-12, that most Baltimore meetings they're seeing don't
  have one, "interesting that this one does" (the
  [City Council Hearing, 2025-10-20, ID=1282692](https://baltimore.legistar.com/MeetingDetail.aspx?GUID=5353B4B6-3F2D-4E02-8DA0-F62A82299422&ID=1282692&Options=info|&Search=)
  from the resolution-mechanics question just above — its real YouTube
  "Recording" link is what `_try_fallback_video_link()`
  ([app/platforms/legistar.py](app/platforms/legistar.py), built for
  Baltimore originally, see `BACKLOG_DONE.md`) exists to catch).

  **A quick real check confirms the pattern, doesn't yet explain it**:
  pulled 4 meeting IDs straight off `baltimore.legistar.com/Calendar.aspx`
  (1332199, 1376920, 1376921, 1405006) — every single one has a
  completely empty `Attachments:` field, no video, no Recording link,
  nothing. 4-for-4 empty vs. the one known-good example isn't enough of a
  sample to conclude anything about *why* (different meeting body?
  different era — this may just be a backlog of not-yet-processed/older
  meetings on the general calendar? only certain meeting types get a
  recording attached at all?), just enough to confirm the user's
  observation is real and not a fluke.

  **Next real step, not yet done**: work through
  [baltimore.legistar.com/Departments.aspx](https://baltimore.legistar.com/Departments.aspx)
  — Baltimore's full directory of boards/committees/departments — to find
  a specific body's own meeting list rather than sampling the mixed
  general calendar. Two candidate "City Council" entries found there
  already: `DepartmentDetail.aspx?ID=28879` ("City Council") and
  `ID=28881` ("Baltimore City Council") — worth checking whether either
  gives a curated meeting list for the same body the one working example
  belongs to (full Council plenary sessions, as opposed to a subcommittee)
  and, if so, whether *that* body's meetings consistently have video
  attached even when the general calendar sample above doesn't. (A first
  attempt at `DepartmentDetail.aspx?ID=28879` didn't surface meeting links
  directly — may need a different nav path, e.g. a Meetings tab/param,
  not yet found.) If a real pattern falls out (e.g. "only full Council
  sessions get recordings, subcommittees don't"), that's a genuine signal
  worth teaching the adapter or the frontend about; if it's closer to
  "video is attached inconsistently, no real pattern," that's useful to
  know too, before investing in a fancier fallback (e.g. a CharmTV-
  channel search, the same class of fix already flagged for Phoenix/
  Philadelphia/Albuquerque above).

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
- **Stale archived transcripts have no automated refresh path — real gap
  confirmed 2026-08-12 fixing the Minneapolis ALL-CAPS report (see
  BACKLOG_DONE.md for the fix itself), two distinct pieces still open.**
  Everything needed to *manually* fix one specific page now exists
  (fetch a fresh transcript locally, push it, promote it), but nothing
  automated will ever do this on its own for a page that already has a
  transcript, however bad:
  - **Re-submitting an already-archived URL through the normal public
    `/api/resolve` flow does not refresh stale content.**
    `archive_client.lookup()` runs *before* any live resolve (see
    README's "Lookup, before resolving") and short-circuits straight to
    the existing page the moment a permanent page is found, so a live
    re-resolve never even starts. The only ways to force a refresh are
    `/admin/recheck-archive-page` (token-gated) or the passive 30-day
    `ARCHIVE_RECHECK_AFTER` cycle — no public, no-token way for anyone to
    ask for one specific stale page to refresh sooner.
  - **`scripts/fetch_youtube_transcripts.py`'s queue
    (`GET /internal/transcript-wanted`) only ever returns YouTube-backed
    pages with *no* default transcript at all** — a page with an
    existing-but-bad transcript (stale, ALL-CAPS, pre-fix artifacts, or
    otherwise low quality) never qualifies as "wanted," so the daily
    script will never pick it up and re-fetch it, no matter how long it
    runs. Combined with the point above, a YouTube-delegated page that
    got a bad transcript once will stay that way indefinitely unless
    someone manually repeats the exact fix-it-by-hand process used for
    Minneapolis (fetch locally, push via `/internal/ingest`, promote via
    the new `/admin/promote-transcript-version` — see BACKLOG_DONE.md).
    Worth deciding whether the queue should also surface low-quality-
    flagged pages, not just missing ones, and/or whether recheck should
    be able to trigger this same script's path for one page on demand.
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
  **Re-checked live 2026-08-11 (Wave 2 survey): still a hard 404, not
  fixed or superseded.** A broad survey of large-city Swagit usage
  turned up plenty of fresh `*.new.swagit.com`/`*.swagit.com` samples
  (Houston, Dallas, Austin, San Antonio, Long Beach, League City TX,
  Yountville CA) but zero examples of this specific
  `cityname.gov/swagit-video-player?video_id=...` shape working
  anywhere. The closest related case found — Dallas's
  `dallascityhall.com` embedding Swagit video via a plain `<iframe
  src="https://dallastx.swagit.com/...">` — is a different shape
  (generic fallback's existing "look for a link/iframe to a platform we
  support" logic already resolves it, since the iframe `src` is a real
  `*.swagit.com` URL) and doesn't substitute for a real sample of
  Dublin's self-contained custom-domain player. Genuinely still open.
- **YouTube/PrimeGov: non-English captions untested**, and it's unknown
  whether the manual-vs-auto-generated track coverage gap seen on the one
  real LA sample (see [BACKLOG_DONE.md](BACKLOG_DONE.md)) is typical or
  specific to that video. Two tangential non-English-caption leads found
  2026-08-11 (see below), neither on YouTube/PrimeGov itself: Riverside
  County CA runs a parallel `board-supervisors-meeting-videos-spanish`
  page, and a third-party Internet Archive mirror of Virginia Beach
  council meetings (`archive.org/details/covbva-*`) carries real
  `.es.asr.srt` files alongside the English ones.

- **New platform-vendor gaps found 2026-08-11, via a Wave 2 survey of
  the largest US cities/counties** (see BACKLOG roadmap doc for the full
  survey; full data compiled to an artifact, not saved in-repo). None of
  these were previously tracked here — real gaps, not yet-fixed known
  ones:
  - **Cablecast** (a government-access-TV VOD vendor, unrelated to
    anything currently supported) — confirmed as the actual video host
    for two large cities: **Charlotte, NC** (965k, delegated from its
    Legistar calendar — `charlotte.cablecast.tv/internetchannel/?site=1`)
    and **Detroit, MI** (649k, delegated from *both* its Legistar and
    eScribe calendars simultaneously —
    `detroit-vod.cablecast.tv/CablecastPublicSite/`). The clearest new-
    adapter candidate by population reach of anything found this pass.
    Detroit's eScribe side is also worth checking for populated captions
    while there — no eScribe example anywhere has one confirmed yet.
    **Update 2026-08-12**: `CablecastAssetFinder` is now built (see
    `BACKLOG_DONE.md`) and live for both Charlotte and Detroit, including
    real `vodTranscripts` extraction — see `BACKLOG_DONE.md`'s "Cablecast
    real transcript extraction" entry for the full build.
  - **IQM2** — a Granicus-family product (footer: `support@granicus.com`)
    with a distinct UI/URL shape from the classic ViewPublisher/
    MediaPlayer this app already parses. Confirmed on **Atlanta, GA**
    (`atlantacityga.iqm2.com/Citizens/`, one of three parallel systems
    Atlanta runs) and **Santa Clara County, CA**
    (`sccgov.iqm2.com/citizens/default.aspx?frame=no` — the county
    briefly moved to PrimeGov in Jan 2024, then reverted back to IQM2
    "until further notice"; video links render as unresolved `#`
    placeholders server-side, unconfirmed whether real video is
    reachable without JS execution).
  - **CivicWeb** (iCompass, a Diligent brand — footer-confirmed, and a
    genuinely different vendor from eScribe despite both being Canadian
    civic-meeting platforms) — confirmed as **Dallas County, TX**'s
    (2.6M) meeting-video host: `dallascounty.civicweb.net/Portal/
    Video.aspx`. Page is JS-rendered; WebFetch only ever saw "Loading…"
    placeholders, so the real video-embed shape is still unconfirmed —
    needs a live-browser check before any adapter work, not just a
    positive ID of the vendor.
  - ~~**A new, unified Granicus product** (`webcontent.granicusops.com`)
    — possible forward-compat risk to the existing Granicus/Legistar
    adapters~~ **Re-checked live 2026-08-12: real risk to the video path
    not reproduced on either sample city, and `webcontent.granicusops.com`
    itself turns out to be a document CDN, not a video-player product.**
    Followed both cities' real, current Legistar video links end-to-end:
    Fresno's `ID1=2161`/`2162` and Colorado Springs's `ID1=2664`/`2662`/
    `2656` (the only video-linked meetings on each city's current calendar
    window) all still redirect cleanly through `Video.aspx?Mode=Granicus`
    → `MediaPlayer.php` → the classic `{city}.granicus.com/player/clip/
    {id}` shape `granicus.py` already fully supports — no
    `webcontent.granicusops.com` in the chain on either city, today.
    Separately confirmed what `webcontent.granicusops.com` actually is:
    `curl`ing it directly returns a raw S3 `AccessDenied` XML body (i.e.
    it's an S3-backed static-file host), and every real URL under it found
    via search is a per-customer **PDF document** (`/content/{customer}/
    *.pdf` — eComments user guides, virtual-meeting-attendance
    instructions), not a video page. So this looks like Granicus's
    existing document/PDF CDN, not a new video-player product migrating
    existing customers — the original 2026-08-11 survey most likely
    encountered it via an agenda/document link on these cities' calendars,
    not the video path, so the "cities this app already resolves could
    start silently failing" risk doesn't hold up on what's actually
    reachable today. Not fully closed (a genuinely different Granicus
    video product, e.g. the separately-observed `{city}-prod.civica.
    granicusops.com` pattern seen on Sunnyvale/Bellflower via search but
    not confirmed live against real video, could still exist and could
    still be a real migration risk) — but no longer treated as an
    active, unaddressed threat to Fresno/Colorado Springs specifically.
  - **A "decoupled transcript service" pattern** — a real transcript
    hosted entirely separately from the video, cross-referenced by
    meeting rather than embedded on the same page — found independently
    twice: **Tampa, FL**'s own "CTTV" webapp
    (`apps.tampagov.net/cttv_cc_webapp/`, real structured per-meeting
    transcripts; a third-party mirror at `meetings.tampamonitor.com`
    already builds a synced, clickable version worth studying as a
    reference implementation) and a "Transcript Room" service
    (`transcriptroom.org`) that **Philadelphia**'s Legistar committee-
    hearing pages link out to. Not a vendor to build one adapter for —
    a shape worth keeping in mind if either city (or another one like
    them) becomes a real adapter target.
  - **Maricopa County, AZ — a real correction to a standing assumption**:
    `maricopa.legistar.com` is **not** the county's Board of Supervisors
    system — live navigation confirms it's actually the small **City of
    Maricopa**'s calendar (title "City of Maricopa - Calendar", no Board
    of Supervisors content at all). The county's real system is a
    CivicPlus AgendaCenter (`maricopa.gov/324/Board-of-Supervisors-
    Meeting-Information`) linking directly to YouTube. If anything here
    special-cases Maricopa as Legistar, it's wrong.
  - **Tarrant County, TX** (2.1M) — confirmed migrated off Granicus to a
    direct YouTube channel; the old `tarrantcounty.granicus.com` archive
    is explicitly marked "(NOT IN USE)" on the site itself. A real
    platform-migration case, same shape as Long Beach's move off
    Legistar→Granicus to a custom "OneMeeting"→Swagit setup and Santa
    Clara County's PrimeGov-then-back-to-IQM2 flip — worth remembering
    that a city/county's platform isn't assumed stable once confirmed
    once.
  - **Riverside County, CA** (2.5M) — `rivco*.org` domains return a
    plain HTTP 403 (Cloudflare/WAF) to non-browser fetches, the same
    class of problem `headless_browser.py` was already built to solve
    for Minneapolis LIMS and Salt Lake City meeting recaps. Likely just
    needs the existing solution pointed at a new domain rather than new
    engineering, but unconfirmed — the in-session browser tool was also
    down for this check.
  - **Broward County, FL** — a real, confirmed **positive** two-tier
    Granicus captions example (`broward.granicus.com/ViewPublisher.php?
    view_id=15`): a live "CC" toggle plus a separate on-demand
    "enhanced/easier to read" captions link under a "Captioned" column.
    Worth checking against `granicus.py`'s existing caption-detection
    logic directly, since most other Granicus instances checked this
    pass showed no caption UI at all.

## Archive roadmap

- **"Feed cities" — should this app ever synthesize its own meeting
  pages for cities that have no well-defined per-meeting page at all?
  Open strategic question, not a build item, prompted by a 2026-08-12
  pass through the 50 biggest US cities.** A real, recurring pattern
  distinct from every other gap logged this session: a city publishes
  video as one big feed (a YouTube channel, a Vimeo showcase list, a
  Seattle-Channel-style video index) and agendas/meeting metadata as a
  *separate* feed (a Granicus/Legistar calendar, an agenda-only page),
  sometimes on two different pages, sometimes both crammed onto one —
  but never as a single stable, government-hosted URL that's "the page"
  for one specific meeting with both video and agenda attached. Every
  adapter in this app assumes that stable per-meeting page exists
  somewhere and just needs finding/parsing; these cities don't have one
  to find. Concretely already seen this session in that shape: Seattle
  Channel's video-plus-feed page (above), Phoenix/Philadelphia/
  Albuquerque's Legistar-page-with-no-video-link-at-all-but-a-separate-
  city-YouTube-channel (above), Chicago ELMS's agenda API paired with a
  separate Vimeo showcase (above), El Paso's `elpasotexas.gov/videos/`
  directory of per-body Vimeo showcases (above).

  **The idea, in the user's own words**: rather than only ever resolving
  a URL someone pastes, build a page ourselves that indexes a city's
  video feed and its separate agenda feed, matches them (e.g. by date —
  "the city hosts all its city council meetings on YouTube with the date
  of the meeting in the title" paired with "a list of all the agendas...
  on Granicus with the date in the metadata"), and creates a real,
  possibly-permanent meeting page on *our* site combining both. The
  user's own framing of the tradeoff: "in a way, this is a PITA. In
  another way, these might be the most helpful pages we create because
  there isn't a near duplicate on the government agency's website." That
  second point is real and worth sitting with — every other page this
  app makes mirrors something that already exists somewhere, just made
  more accessible/deep-linkable/transcribed; a synthesized feed-matched
  page would be the one case where the page genuinely doesn't exist
  anywhere else in this form. That's a stronger value proposition than
  usual, and a correspondingly higher bar for correctness (see below).

  **Real considerations to work through before scoping a specific
  version, not yet decided on any of these:**
  - **Match confidence is the central risk, not a side detail.** Date/
    title heuristic matching between two independent feeds *will*
    sometimes attach the wrong video to the wrong meeting — unlike
    today's "no video found" (an honest gap), a wrong match is
    fabricated-looking correct-seeming misattribution on what would be a
    real, publicly-indexed page under a real jurisdiction's name — a
    sharper version of the fabricated-content risk the Trust & Safety
    section above already threat-models for `generic_fallback`, not a
    new category of risk. Whatever gets built needs a real answer for
    "how confident is confident enough to publish," not just "best
    guess."
  - **One-time historical backfill vs. an ongoing/scheduled pipeline are
    two very different sizes of commitment — the user's own instinct is
    that ongoing is the harder one, worth taking seriously rather than
    assuming they're the same problem at different scales.** A one-time
    backfill for a fixed list of big cities is bounded: run it once,
    review the matches, publish, done — much closer to the existing
    `bulk_ingest.py` shape than to a new standing system. An ongoing
    pipeline means continuously matching new videos to new agendas
    forever, on a schedule, per city, with drift over time (a city
    changes its YouTube channel, changes its agenda vendor, changes its
    upload cadence) silently degrading match quality with nothing
    forcing a human to notice.
  - **Temporary vs. permanent doesn't have to be a single decision up
    front** — the existing `best_effort`/`generic_fallback` ephemeral
    `/meeting?url=` flow already has a real lower-trust tier "isn't
    pushed to the permanent Archive unless it has real content" pattern
    to borrow from; a synthesized match could start there (visible, but
    not yet a permanent indexed page) before anything gets promoted.
  - **Scale/cost is unscoped**: how many of the 50 cities checked
    actually hit this specific "two separate feeds" pattern (as opposed
    to the many *other* distinct problems logged this same session —
    rate limiting, wrong jurisdiction, infinite recursion, weak metadata
    — which aren't this problem and shouldn't get bundled into sizing
    it), how many historical meetings per city, and whether transcribing
    all of them is assumed as part of this or a separate ask on top —
    none of that's been counted yet.

  **On "is there an easy version" — the concrete next step is counting,
  not building.** Before sizing this at all, worth going back through
  the 50-city pass specifically to tag which cities hit *this* pattern
  (two separate feeds, no per-meeting page) rather than one of the other
  distinct bugs/gaps already logged individually this session — right
  now this entry is grounded in four real examples encountered
  incidentally, not a real count of how big "feed cities" actually are
  among the 50. That count is what would turn "maybe just do the big
  cities once" from a gut instinct into an actual scoped decision.

  **A real, promising extraction angle for whatever gets built: WCAG/
  accessibility-driven markup, not just date/title matching — user's own
  idea 2026-08-12, checked directly against real pages rather than left
  as speculation.** Government sites lean on standardized accessibility
  markup more than most (Section 508 compliance is often a legal
  requirement, not a nice-to-have), and unlike a proprietary player's
  internal JS config, these are standards-based and consistent across
  unrelated sites — real findings, not assumptions:
  - **`<track kind="captions" src="...">` inside a native `<video>`
    element** — the actual HTML5 captions standard. Confirmed present,
    identically shaped, on three separate real government meeting pages
    already fetched during earlier work in this repo (each a plain
    `/videos/{id}/captions.vtt` path) — about as reliable a caption-
    discovery signal as exists wherever a site uses native `<video>`
    rather than a JW Player/Vimeo/YouTube-style embed.
  - **`<time datetime="...">` semantic date/time markup** — confirmed
    real on Portland.gov, with full ISO datetime *including time of
    day* (`<time datetime="2026-07-29T16:30:00Z">`) — notably the exact
    missing piece from the earlier Google-Search-Console `uploadDate`/
    timezone finding (Bugs, above): this app doesn't capture meeting
    time-of-day anywhere today, and here's a real government source
    that already has it in clean, structured form.
  - **WCAG-required iframe `title` attributes, when a site populates
    them well** — Portland's video iframes carry real, descriptive
    titles (`"YouTube | Portland City Council AM Session 07/29/26"`,
    correctly distinguishing AM/PM sessions); confirmed *not* universal
    though — CRRMA's iframe title on the exact same YouTube-embed
    pattern (Bugs, above) was just the generic placeholder `"YouTube
    video player"`. Same accessibility requirement, inconsistent
    real-world compliance — has to be checked per site, not assumed.
  - **Real negative, worth not chasing further**: checked 7 real
    government pages this session (Portland, Seattle Channel x2, CRRMA,
    Columbus, Charlotte, Baltimore) for schema.org/JSON-LD structured
    data (the same VideoObject markup this app's *own* pages emit for
    SEO) — zero hits on all seven. Unlike the accessibility markup
    above, this doesn't look like a technique government sites
    reciprocate.

**Architectural context:** anything about content/audience rather than
resolving (permanent pages, search, accounts/billing, email alerts, the
transcription crawler) grows in a **separate app** ("the Archive"), not this
resolver — see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full reasoning.
The resolver/Archive seam is `get_cached_resolution`/`log_resolution` in
`app/db/crud.py` plus `archive_client.lookup()`/`.push()`.

- **Accounts + token billing — scoping started 2026-08-10, per the
  user's explicit go-ahead ("start scoping," not "start building").
  Phase 1 build actually started the same day, on a dedicated branch
  (`accounts-clerk-phase1`) — see below.** Needed for paid features
  (already alluded to in adapter warning messages) and as a
  prerequisite for email alerts below.

  **Auth pivot, same day: Clerk, not a hand-rolled internal auth
  system.** The paragraph below (passwordless magic-link + a
  self-issued `AccountSession` cookie) was the original design and is
  now **superseded** — the user explicitly weighed the tradeoff
  ("I'm kind of leaning away from becoming a security expert") and
  chose a third-party auth provider instead. Real reasons, not just
  preference: Clerk gives prebuilt login UI, session handling, and
  built-in account-deletion flows for free; it keeps user email/PII
  entirely off this app's own database (a real privacy-posture
  improvement — the new `SavedItem` table is keyed only by Clerk's
  opaque user id, never an email); and its session JWT can be verified
  **locally by both services independently** (no shared signing secret
  to manage, no internal HTTP round-trip needed to check "is this
  visitor logged in" on the hot-path pages), which turned out to be a
  *simpler* fit for this app's two-separate-databases architecture than
  the original self-issued-cookie design, not just a safer one. Stripe
  (for billing, phase 5 below) and Resend (email) are unchanged.

  **Phase 1 scope, decided via direct questions, unchanged by the Clerk
  pivot:** accounts + saving meetings/searches to your own account
  only — no public profile pages, no visibility toggles, no posts/
  reposts, no subscriptions/notifications, no billing yet. Account
  creation auto-subscribes to the existing Resend newsletter audience
  (via a `user.created` Clerk webhook). A **non-goal, explicitly
  designed and tested for**: nothing existing is gated behind login —
  every route works identically for an anonymous visitor; the only
  changes are purely additive "Save this meeting"/"Save this search"
  buttons that appear if (and only if) a real session is present.

  New table: `SavedItem` (`clerk_user_id`, `item_type` —
  `saved_meeting`/`saved_search` — `meeting_page_id` nullable FK,
  `search_params` nullable JSON, `created_at`) in `archive/db/models.py`
  — stays in Archive's DB (not `app/db`) since it needs a real
  same-database FK to `MeetingPage.id`. No `Account`/`AccountSession`
  tables at all anymore — Clerk owns that state entirely.

  **Status as of 2026-08-11: merged to `main` and live in production**
  (PR #5), on a real Clerk **production** instance (custom-domain DNS
  verified in Namecheap, Google OAuth credentials configured) rather
  than the development instance staging used. Getting production
  actually working surfaced three real bugs, all found via live
  production debugging and now fixed — see BACKLOG_DONE.md's
  "Clerk production cutover" entry for the full incident writeup
  (base64 padding, a CSS specificity bug, and a malformed
  `CLERK_JWT_KEY`). All routes/tables/webhook/frontend wiring built,
  413 tests passing. Live-verified end to end on production with the
  user's own real account: sign-up (both Google OAuth and email-code),
  session verification, and `/account/saved` correctly showing saved
  items instead of the signed-out prompt. A follow-up UI polish pass
  (nav, button sizing/prominence, `/account/saved` layout, a bookmark
  icon next to the meeting title) landed the same day as the merge,
  live-verified locally first.

  **Second round, same day: a large backlog-cleanup pass surfaced
  several more real UI/UX bugs and a sign-in/sign-out redirect saga**
  (nav "Sign in"/"Get Updates" flash-on-load, saved-search filter
  display, meeting-row title wrap, a source-transcript disclaimer with
  a pop/glow pointer, and — after three rounds of Clerk's own
  documented redirect options proved unreliable live — a client-side
  forced-return safety net in `shared_static/clerk_nav.js`, plus
  dropping the transcribe-form's inline sign-in shortcut entirely per
  the user's call once that saga made clear it wasn't worth the
  complexity there specifically). See BACKLOG_DONE.md for the full
  detail on each. 425 tests passing.

  **Explicitly deferred, by the user's own call: the `user.deleted`
  webhook → `saved_items` purge (the right-to-deletion cascade) has
  never actually been fired/verified end-to-end.** The code path exists
  (`archive_client.delete_account_data()` → bearer-gated
  `/internal/account/delete-data` → `DELETE FROM saved_items WHERE
  clerk_user_id = ...`) and has unit coverage
  (`tests/test_clerk_webhook.py`), but no real Clerk account has been
  deleted via the UserButton flow to confirm the webhook fires and the
  rows actually disappear. User's decision: don't block merge on this:
  "we can do it manually if anybody actually requests it" — i.e. a real
  deletion request would be handled by hand (direct DB delete) rather
  than relying on this untested automation, at least until it's been
  exercised for real. Worth closing this gap for real before this phase
  is treated as a finished right-to-deletion story, not just before
  merge.

  **Original design below, kept for its still-valid parts.** The auth-
  mechanism paragraph immediately following this one is superseded (see
  above); the `Note`/`NoteSubscription` social-layer design, the phased
  plan, and the open questions still describe the real plan for phases
  2+ once phase 1 ships.

  ~~**Proposed auth mechanism: passwordless, email-only — not round 1's
  Google OAuth/JWT.** `archive/utils/email.py` already has a working,
  live-verified confirm-by-email pattern (`send_confirmation_email()` +
  `TranscriptionJob.confirmation_token`, built for on-demand
  transcription) — accounts should extend this exact mechanism (a magic
  link, one-time token, no password ever stored) rather than
  introducing a second, heavier auth system. Matches `CLAUDE.md`'s own
  framing of round 1's real mistake: building full auth/accounts before
  validating the core feature, not that accounts themselves were wrong
  — the fix isn't "build auth more carefully," it's "build the smallest
  auth that actually works," and this app already has proof that
  pattern works (Resend audience-membership skip-confirmation is
  already live and confirmed working end-to-end). Session: a signed,
  httponly cookie holding an opaque session id checked against a new
  `AccountSession` row — no JWT needed, since this is one service
  issuing and checking its own sessions, not a distributed multi-service
  handoff.~~ Superseded by the Clerk pivot above.

  **Expanded scope, per user request 2026-08-10 — a real social/content
  layer, not just accounts + saved searches.** The user wants, in their
  own words: a profile page (public or private) made of notes (posts or
  notifications, each independently public/private); saving a meeting to
  a profile as a note (public/private per note); saving a search to a
  profile as a note (public/private per note); subscribing to
  in-profile/notification alerts for a search, separately from
  subscribing to email alerts for the same search; reposting anything as
  a new note carrying a user-written message, linking back to the
  original (a quote-repost, not a plain retweet-with-no-comment);
  eventually attaching clips/screenshots/PDFs/other media to notes;
  eventually sorting/filtering `/meetings` search results by how many
  people saved a given meeting (a popularity signal). This materially
  reshapes the data model below from the original accounts+SavedSearch
  sketch — capturing it now since it changes what "phase 1" even means,
  not committing to build any of it yet.

  **Revised proposed data model**, replacing the original
  `Account`/`AccountSession`/`SavedSearch` sketch's third table: a single
  polymorphic **`Note`** table instead of a separate `SavedSearch` table,
  since "saved search," "saved meeting," "post," and "repost" all turn
  out to be the same underlying shape (an account, a visibility flag, an
  optional reference, optional user-written text) rather than four
  independent features:
  - `Account` (email, created_at, no password column) and
    `AccountSession` (session id, account id, expires_at) — unchanged
    from the original sketch.
  - `Note` (account_id, `note_type` — `saved_meeting` / `saved_search` /
    `post` / `repost` — `visibility`: public or private, **set per note,
    not per account or globally**; `meeting_page_id` nullable FK, set
    only for `saved_meeting`/some `repost`s; `search_params` nullable
    JSON, set only for `saved_search`; `parent_note_id` nullable
    self-referential FK, set only for `repost` (the note being reposted —
    reposting a repost should probably chain to the *original*, not
    nest indefinitely, an open question); `body_text` nullable, the
    user-written message on a `post` or `repost`; `created_at`). A
    profile page is then just "this account's notes, filtered to public
    ones unless the viewer is the account owner."
  - `NoteSubscription` (account_id, `search_params` JSON matching a
    saved search's shape, `notify_in_profile` bool, `notify_by_email`
    bool) — the two subscription channels the user described are
    independent toggles on the same row, not two separate features;
    `notify_by_email` is what the already-planned "Email alerts for
    saved searches" item below actually becomes once accounts exist,
    not a separate build.
  - Media attachments (clips/screenshots/PDFs) on notes: flagged
    "eventually" by the user, and a real new category of infrastructure
    for this app — there is currently **zero file-upload/object-storage
    capability anywhere in this codebase** (every existing asset is
    either scraped-and-linked, not hosted, or a static file checked into
    the repo). Would need real new decisions (S3/R2/Cloudflare Images or
    similar, upload size limits, moderation) not touched by anything
    else in this scoping pass — deliberately not designed further until
    the base Note model ships and this becomes concretely next.
  - Popularity-based sort/filter on `/meetings`: also flagged
    "eventually" by the user. Cheapest real implementation once `Note`
    exists: a `saved_meeting_count` column on `MeetingPage`, updated
    on save/unsave (or computed via a `COUNT(*)` on `Note WHERE
    note_type='saved_meeting'` at query time, matching this repo's
    existing "don't add a materialized column until the naive version
    actually gets slow" pattern from the search-scaling item below) —
    genuinely deferred until saving meetings itself exists and has real
    usage to rank by.

  **Proposed phased plan, revised — deliberately still not one big
  build:**
  1. Passwordless accounts (magic link, session cookie) + the base
     `Note` model, covering just `saved_meeting` and `saved_search`
     (no `post`/`repost` yet, no profile page yet) — no billing yet,
     could ship as a free feature.
  2. Public/private profile pages rendering an account's own notes;
     `NoteSubscription` (both notify channels) for saved searches —
     this is what actually unlocks "email alerts," not a separate
     build from it.
  3. `post`/`repost` note types, making the profile a real lightweight
     feed rather than just a saved-items list.
  4. Batch lookup, gated by account (rate-limited per-account instead
     of fully anonymous) — still no payment required, just removes the
     anonymous-abuse-vector concern the batch-lookup item below already
     flags.
  5. Billing (Stripe is the obvious default — standard, well-documented
     webhook/subscription model) layered on only once there's a real
     paid tier to sell against — e.g. unlimited batch lookups, higher
     alert frequency, priority transcription queue position (the
     existing `TranscriptionJob.priority` column already supports a
     higher tier with zero schema change, per its own docstring).
  6. Media attachments on notes, and popularity-based search
     sort/filter — both explicitly "eventually" per the user, sequenced
     last since both need real usage of the earlier phases to be worth
     building against.

  **Business-model framing, from the user, 2026-08-12 — several rounds of
  refinement the same day, replaces the original "journalists are the
  paying user" framing entirely.** Advocates and grassroots organizers,
  not journalists, are the primary intended audience — journalists are a
  good example user (real distribution/credibility value) but a smaller
  group than the grassroots/advocacy base this is actually being built
  for, and shouldn't be built into the product's core definition anywhere
  (`README.md`'s Vision section now reflects this). The intended paying
  customer is a different group again: institutional users with real
  budgets — special interest groups, corporations, city staff/management.

  **The likely shape of the split, directionally — not priced or built
  yet.** Usage seems likely to split into two real modes once there's a
  regular user base: a light user following one or two meetings a month
  for a single city council or planning commission, and a heavy user
  tracking meaningfully more than that. Rough shape floated by the user
  (not a commitment): an account-creation gate that grants free monthly
  credits sized to comfortably cover the light-user case, with a paid tier
  (the user's own reference point: something like $40/month) that raises
  the ceiling high enough a heavy individual user doesn't have to think
  about limits day to day. Separately, a B2B/institutional tier is the
  intended answer for an organization tracking a specific topic across
  many jurisdictions at once (the user's own example: a company's PR team
  following a specific kind of siting decision across city councils) — a
  different usage shape from an individual power user, likely
  priced/scoped differently rather than being "the same paid tier, bought
  by a company."

  **On-demand transcription's email-only gate is a deliberate middle path,
  not a stepping-stone toward eventually requiring a full account —
  explicit user correction, 2026-08-12.** Transcription is still the app's
  single most cost-intensive feature by a wide margin (see "On-demand
  transcription" below for real dollar/compute figures), and email
  confirmation was chosen specifically as real friction against abuse
  without forcing a login onto the app's costliest path. Keep it this way
  going forward rather than treating it as an implicit TODO to fully
  account-gate later.

  Search itself stays free as long as it's cheap to run; the plan for
  if/when that stops being true is a real, explicitly limited free tier —
  either the credit system above or narrower scope (e.g. free tier limited
  to shorter date ranges) — rather than putting search behind a paywall
  outright. Not yet decided: the actual credit amounts, the exact
  paid-tier price/limits, whether B2B pricing is a multiple of the
  individual paid tier or a separate negotiated thing, or what usage/cost
  threshold triggers building any of this at all — all directional
  thinking to conceive of usage modes, not a committed pricing plan.

  **Real open questions, not decided yet — need the user's call before
  building past phase 1:** what's actually free vs. paid (the phased
  plan above is a sequencing proposal, not a pricing decision); whether
  "token billing" specifically means a metered credit system (buy N
  tokens, spend on transcriptions/batch lookups) vs. flat subscription
  tiers, or both; whether Stripe is the intended/preferred provider or
  just this write-up's default assumption; free tier size for saved
  searches/alerts before hitting a paywall; whether a `repost` of a
  `repost` should chain to the original note or nest (product decision,
  not just a schema one); moderation for public notes/profiles in
  general, not just future media attachments — public+free-text (`post`,
  `repost` messages) is real new user-generated-content surface area
  this app has never had before, worth its own look before phase 3
  ships, not assumed fine because `ProblemReport` already covers the
  Trust & safety section's narrower "is this a real government meeting"
  concern above.
- **Lifecycle-triggered transactional emails (Resend) — built 2026-08-11
  from rtr-business's `marketing/LIFECYCLE_EMAILS.md` (approved copy/
  voice, written by the user).** That doc defines six emails; five
  shipped this pass, one explicitly split off given its real scope:
  - **Shipped**, all reusing/extending existing Resend send
    infrastructure, no new mechanism: "Thanks" (account created — fires
    from the Clerk `user.created` webhook in `app/main.py`, *instead of*
    also sending "Welcome," since account creation already
    auto-subscribes to the newsletter and sending both would be two
    emails for one action — the user's explicit call); "Welcome" (joined
    the newsletter via the standalone `/subscribe` form only);
    "Goodbye for now" (`/unsubscribe`, deliberately skips the standard
    footer unsubscribe link since the email itself already **is** the
    unsubscribe confirmation); "Your transcript's ready" (rewrite of the
    existing `send_completion_email()`'s copy — kept the AI-transcript
    disclaimer box even though the approved doc omits it, the user's
    explicit call, since it's a real standing accuracy-expectation
    warning, not just legal cover); "We couldn't cook this one" (new —
    the doc's "Bonus" entry, the sad-path twin to the above, fires when a
    `TranscriptionJob` gives up after `MAX_CONSECUTIVE_CHUNK_FAILURES`,
    CC's `RESEND_REPLY_TO_ADDRESS` so failures get seen in real time).
  - **Real architecture change**: the resolver (`app/main.py`) previously
    only ever upserted Resend audience contacts — it had zero
    transactional-send capability (that lived solely in
    `archive/utils/email.py`, used by Archive/the worker). It now has its
    own `_resend_send()` + branded-template helpers, deliberately
    duplicated rather than proxied through Archive (same
    deliberate-duplication convention as `get_clerk_user_id()`/
    `_resend_audience_upsert()`) — needs its own copies of
    `RESEND_FROM_ADDRESS`/`RESEND_REPLY_TO_ADDRESS` set in Render (added
    to `render.yaml`, `sync: false` — user still needs to set the actual
    values on the live resolver service, staging and prod, matching
    Archive's existing values).
  - **Not yet live-verified against a real Resend account** — matches
    this repo's own "don't claim a path works without a positive
    example" convention (see `archive/utils/email.py`'s own docstring,
    which flagged the same gap when first built). Covered by monkeypatched
    unit tests only (`tests/test_lifecycle_emails.py`,
    `tests/test_worker_email_notifications.py`). Also unconfirmed live:
    whether Clerk's `user.created` webhook payload actually includes
    `first_name` for every signup method (e.g. email-code vs. Google
    OAuth) — "Hi there," is the documented fallback either way, so a
    missing field degrades gracefully, but the "Hi [First Name]," path
    itself hasn't been seen fire for real yet.
- **Audit every user-facing email address on the site and consolidate on
  `ally@redtaperecordings.com`.** User request 2026-08-12, after setting
  up `ally@`/`ryan@redtaperecordings.com` forwarding (see
  `BACKLOG_DONE.md`'s "Email deliverability" section) — now that `ally@`
  actually receives mail, make sure it's the address the site actually
  shows/uses, not `ryan@`. A first grep (2026-08-12) found:
  - Two `mailto:` Contact links, both currently `ryan@redtaperecordings.com`:
    `app/templates/base.html:77` and `archive/templates/base.html:95`.
  - `app/templates/about.html:19` shows `ryan@how-to-adu.com` directly
    (the personal inbox, not a `redtaperecordings.com` address at all).
  - `RESEND_REPLY_TO_ADDRESS` (`app/main.py`, `archive/utils/email.py`,
    Render dashboard env var per `BACKLOG_DONE.md`'s "Closed out
    2026-08-10" note) is currently `ryan@redtaperecordings.com` — this is
    where transactional-email replies and the "We couldn't cook this
    one" failure CC actually land, so it's in scope too even though it's
    config, not a template string.
  - **Form submissions**: grepped every `<form>` on both services.
    `/api/report-problem` (`app/main.py:704`) only writes a `ProblemReport`
    DB row — no email is sent anywhere today, so there's nothing to
    repoint there yet; this would only become relevant if problem
    reports later grow an email notification. The newsletter signup
    form (`/api/newsletter/signup`) posts to a Resend **audience**, not
    an inbox — no address to repoint either. So "form submissions" turned
    up no actual `ally@`-relevant address yet, unlike the static mailto
    links and `RESEND_REPLY_TO_ADDRESS`.
  - **Deliberately left alone, pending a decision**: `DAILY_REPORT_EMAIL_TO`
    and `YOUTUBE_FETCH_REPORT_EMAIL` (`scripts/daily_report.py`,
    `scripts/fetch_youtube_transcripts.py`) both default to
    `ryan@how-to-adu.com` — these are operator-facing ops digests, not
    site-facing addresses, so probably out of scope for this ask, but
    flagging since they're the same "which Ryan address" question.
- **Lifecycle email bugs found by the user 2026-08-11 — three of the four
  fixed 2026-08-11, see BACKLOG_DONE.md for the full root-cause detail on
  each.** The fourth, "People are talking about…" (saved-search alert
  emails, `marketing/LIFECYCLE_EMAILS.md`'s #5), was always a real new
  feature rather than a bug in this batch — see the "Email alerts for
  saved searches" entry directly below, which is the same feature. That
  doc's own "Digest variant of #5" (batching multiple alerts into one
  email) is flagged there too as later-still: Resend has no built-in
  batching, so a digest needs its own accumulation + scheduled-or-
  event-driven send logic, not just copy.
- **Email alerts for saved searches — confirmed 2026-08-09 as the most
  concrete "worth paying for" feature identified so far.** Depends on
  accounts and search both existing first (search already live; accounts
  is not). This is what turns a one-time lookup into something a
  journalist keeps coming back to for an ongoing beat — it converts
  passive search into active monitoring, the actual job-to-be-done for
  someone covering the same story across dozens of jurisdictions over
  time. Also directly benefits from the crawler re-prioritization below
  (more corpus = more useful alerts). **As of the expanded accounts scope
  above (2026-08-10), this is no longer a separate build** — it's the
  `notify_by_email` toggle on `NoteSubscription`, phase 2 of that plan,
  alongside the equivalent in-profile `notify_in_profile` toggle the
  user also asked for. Kept as its own bullet here since it's still the
  concrete "worth paying for" signal that justifies building that phase
  at all, not because it's architecturally separate anymore. **Copy
  already approved**: this is `marketing/LIFECYCLE_EMAILS.md`'s #5,
  "People are talking about…" — subject `Somebody said "[keyword]"`,
  quotes the matching transcript line, deep-links straight to it. When
  this actually gets built: needs real match-detection (event-driven off
  meeting ingestion/transcription, reusing the same filter logic
  `/meetings` already runs, rather than a new polling job — keeps this
  app's "no background job queue" stance intact) and a per-alert
  one-click unsubscribe token (the doc's copy shows both a "[manage]" and
  an "[unsubscribe from this alert]" link, distinct from the existing
  full-list `/unsubscribe`). The doc's own "digest variant" (batch
  multiple alerts into one email instead of one-per-match) is flagged
  there as later still — Resend has no built-in batching/digest feature,
  so that needs its own accumulation logic on top of whatever ships
  first.
- **Proactive transcription crawler — re-prioritized 2026-08-09 to
  precede accounts/billing, then explicitly held back again 2026-08-10
  ("not yet — keep prioritizing bugs/gaps").** The reasoning below for
  *why* it matters still stands; the decision is about sequencing, not
  value — real reliability work (Alembic gaps, the Archive schema items
  above, Viebit) still takes priority over a bigger, more speculative
  build right now. Revisit once that work settles down. Cross-archive
  keyword search on
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
  jurisdiction/platform combination successfully resolved so far.**
  Currently a real, live, `noindex`'d placeholder, not vaporware: `/coverage`
  (`app/main.py:1027-1033`) renders `app/templates/coverage.html`, whose
  entire content today is "Coming soon: a public, sortable list of every
  city and platform we already support," pointing visitors at pasting a
  URL or `/meetings` search in the meantime.

  **Concrete column spec from the user, 2026-08-11** — one row per
  successfully-added city/jurisdiction, with columns:
  - Video embeds (yes/no)
  - Agenda embedded (yes/no)
  - Instant transcript from the source itself (yes/no) — i.e. the
    platform's own captions, not this app's transcription
  - Transcript from audio possible (yes/no) — i.e. the on-demand
    Whisper transcription path (see "On-demand transcription" below)
  - **Provider, split into two columns, not one** — e.g. "Detail page:
    Granicus; Video: Granicus," "Detail page: Swagit; Video: YouTube,"
    "Detail page: Custom; Video: Vimeo." This directly reflects a real,
    already-documented fact about this codebase (see `CLAUDE.md`'s
    "when a platform turns out to be a wrapper around another" bullet):
    Legistar/CivicPlus both delegate to Granicus for video, and PrimeGov
    embeds a YouTube video — so "platform" isn't actually one value per
    meeting today, and a single "platform" column (the original spec
    below) would hide that real, useful distinction. Maps onto
    `detect_platform()` (detail-page platform) vs. the resolved
    `video_format`/video source (video platform) — worth checking
    against the existing `source_url` delegation quirk noted in
    `CLAUDE.md` (Legistar/CivicPlus delegation ends up with the
    *delegated* platform's URL as `source_url`) since that same
    delegation shapes what "detail page" even means for those rows.

  (Minor ambiguity to resolve when building, not blocking the write-up:
  the user's phrasing was "a column for each city" — read here as "a row
  per city, with the columns above," since a literal column-per-city
  table would be unusably wide at any real scale; worth a quick confirm
  before building.)

  **Original spec, still relevant, folds in above:** also include an
  example meeting URL per row, an outcome bucket (real transcript /
  agenda-only / blank / garbled / wrong-language / no-video, per
  `app/db/outcomes.py`'s existing `classify_outcome()`), and a
  last-verified date. Directly addresses a real gap: today, a user only
  learns whether their city is supported by pasting a URL and seeing what
  happens — costly for someone checking many jurisdictions one at a
  time. Also doubles as a trust/credibility signal ("look how much we
  already cover") and light SEO surface area — exactly the kind of page
  other people link to and cite (worth removing the current `noindex`
  once the real table replaces the placeholder). Mostly a front-end
  exposure task, not new backend work — `/admin/stats` already tracks
  resolve outcomes by platform and quality bucket (see "Caching and
  reporting" in README.md); this needs a *public* (non-admin) read path
  into that same data, a rule for picking a representative example URL
  per jurisdiction/platform pair (e.g. most recent successful resolve),
  and the sort/filter UI itself.
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
- **Search bar has no `OR` support.** `-exclude`/`-"phrase"` and no-op
  `+`/`&`/`AND` shipped 2026-08-11 (see BACKLOG_DONE.md) — this entry now
  covers only the one operator still genuinely missing. `_parse_query()`
  (`archive/utils/search.py`) returns flat phrase/word lists that all get
  ANDed together with no concept of grouping — supporting `a OR b` (let
  alone mixed precedence like `a OR b AND c`) needs a real expression
  tree, not just a new token type. Worth deciding whether full
  boolean-expression parsing is actually needed, or whether `-exclude`
  plus no-op `+`/`AND`/`&` already covers most of the practical value a
  journalist would want, at a fraction of the parser complexity.

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

  **A second, distinct manifestation of the same hallucination failure
  mode found live 2026-08-12** (County of Napa, Board of Supervisors
  2026-06-02:
  [/m/county-of-napa-2026-06-02-board-of-supervisors-on-2026-06-02-9-00-am-final-suppl](https://redtaperecordings.com/m/county-of-napa-2026-06-02-board-of-supervisors-on-2026-06-02-9-00-am-final-suppl)),
  reported by the user as "meeting is in English but the transcript is in
  Spanish." Read through the actual segments: the meeting genuinely is in
  English throughout (real content from ~9:02 onward, e.g. a whole LGBTQ+
  Pride Month proclamation, transcribes correctly) — the `en (transcribed)`
  label itself is correct, langdetect isn't the bug here. The real defect
  sits earlier, 0:00–8:57: the transcript reads as a long stretch of
  "Testing one, two, three." repeated ~17 times, then several lines of
  fabricated Spanish-*looking* text with no real-world referent —
  `"donde es el de dependimiento no es todo eso es un futuro en la
  secuencia de una sección"`, `"¿Como se no le pumping? ¿Se puede ser un
  mal."` **Initially assumed (wrongly) to be Whisper free-associating over
  dead air/a mic test — corrected by the user 2026-08-12, who confirmed
  people are actually speaking real content throughout that whole
  stretch, i.e. this is ~0% transcription accuracy against real speech,
  not a quiet-audio hallucination loop.** That reopens the root-cause
  question rather than closing it: two real, untested possibilities, not
  one confirmed one —
  (1) genuinely poor source audio for this stretch specifically (heavy
  noise/echo/crosstalk/low mic gain) that the `"tiny"` model can't get a
  usable signal from even though real speech is present, or
  (2) an extraction bug: `extract_chunk_audio()`
  ([app/platforms/media_probe.py](app/platforms/media_probe.py)) pulling
  the wrong audio stream/offset/a corrupted segment for this specific
  chunk, so what Whisper actually receives for 0:00–8:57 doesn't
  faithfully represent the real speech happening in the source recording
  at all. **Neither is confirmed** — telling them apart needs someone to
  actually listen to the extracted chunk audio itself (not just read the
  transcript output, which is all that's been checked so far) against the
  real meeting recording for that same time range. The `vad_filter`
  fix proposed in the original write-up of this entry assumed silence and
  is likely the wrong fix if it's actually (1) or (2) — VAD only skips
  non-speech spans, so it wouldn't touch a chunk with continuous real
  speech in it. Don't build a fix here until the audio itself has been
  checked. Same "verify against a
  real example" convention as everywhere else in this file.

  **Update 2026-08-12: user has now listened to it directly — very clear
  audio, no noise/echo/crosstalk.** That rules out hypothesis (1)
  (genuinely poor source audio the model can't parse) and points at (2),
  an extraction bug specific to this chunk — though note the user listened
  to the source recording itself, not the transient chunk audio file
  `extract_chunk_audio()` actually hands to Whisper (deleted after
  processing, inside `worker/main.py`'s `tempfile.TemporaryDirectory`
  block — nothing to inspect after the fact today). Since the source is
  confirmed clean, the next real step if anyone picks this up is to
  reproduce one real chunk locally (same `extract_chunk_audio()` call,
  same 0:00–900s range, same real source URL) and actually listen to *that
  file* before it gets deleted — if it's also clean, the bug is in
  faster-whisper's handling of this chunk (parameters, first-chunk
  cold-start behavior, `MEETING_VOCABULARY_PROMPT` biasing it toward a
  wrong track somehow); if it's already corrupted/garbled/wrong-content at
  that point, the bug is in extraction (wrong stream, bad seek offset,
  transcoding artifact), not in Whisper at all.

  **Update 2026-08-12: reproduced directly, root cause is now a real,
  well-evidenced extraction bug, not a Whisper problem.** Ran the exact
  production media URL (`archive-stream.granicus.com/OnDemand/.../
  napa_10ae7709-....mp4/playlist.m3u8`, pulled from the live page's own
  embedded video URL) through the same `extract_chunk_audio()` ffmpeg
  invocation the worker uses, then transcribed the result with the same
  `faster-whisper` "tiny" model/prompt/`beam_size` `worker/
  transcription_engine.py` uses — this reproduced the *exact* reported
  symptom locally: "Testing one, two, three" (and the Spanish-sounding
  gibberish after it) from 0:00 through ~508s, then a clean, correct
  transition into the real Pride Month proclamation content around
  555–570s, matching the "~9:02" real-content start already reported live.
  Three concrete findings rule out both original hypotheses and point at a
  specific new one:
  - **Not silence/quiet audio**: `ffmpeg`'s `volumedetect` on the 0–508s
    "bad" region measured `mean_volume: -32.3 dB`, essentially identical
    to the confirmed-real-speech 570–600s region's `-31.3 dB` — real
    audio energy is present throughout, not silence a VAD filter would
    have caught.
  - **`ffmpeg` itself warns during extraction**, independent of `-ss`
    placement (reproduced identically with `-ss` before *and* after
    `-i`, ruling out a bad seek offset specifically): `"Queue input is
    backward in time"` / `"Application provided invalid, non
    monotonically increasing dts to muxer"`, repeated dozens of times —
    real evidence the underlying HLS segments this specific
    `archive-stream.granicus.com` "OnDemand" VOD serves have
    non-monotonic/overlapping timestamps, not that `extract_chunk_audio()`
    is asking for the wrong offset.
  - **The hallucinated phrase repeats at suspiciously mechanical ~30-second
    intervals** (0, 30, 60, 90, ... 480s — confirmed via local
    re-transcription, not eyeballed) — real organic speech doesn't repeat
    identically on a metronome; this is much more consistent with
    something in the HLS segment sequence itself looping or duplicating a
    short real segment (plausibly a genuine pre-broadcast mic-check
    recording — "Vamos a hacer una prueba... Testing one, two, three" is
    real, meaningful audio content, not noise) than with either a clean
    signal or true silence.

  **Not yet built, and deliberately not attempted this pass**: a real fix
  needs to establish *why* this specific VOD's HLS timestamps are
  non-monotonic (a Granicus live-to-VOD stitching artifact? a genuine
  duplicated segment in the source?) and whether a targeted `ffmpeg` flag
  (e.g. `-fflags +genpts`, forcing regenerated presentation timestamps
  instead of trusting the source's) actually produces clean audio for this
  same range — untested, and this is one sample from one CDN path
  (`archive-stream.granicus.com`'s "OnDemand" proxy specifically, not
  every Granicus clip), so worth checking whether this recurs on a second
  real `archive-stream.granicus.com` VOD before generalizing a fix, per
  this file's own "verify with a real example" convention.
- **Per-meeting `initial_prompt` seeded with real council-member names,
  from the agenda — user idea, 2026-08-11, real proper-noun accuracy
  motivation (their example: "Council Member Rashi Kesarwani, Council
  Member Rigel Robinson").** Today's `MEETING_VOCABULARY_PROMPT`
  (`worker/transcription_engine.py:26-30`) is one fixed, generic
  constant, reused verbatim for every job's every chunk — real
  people's names (especially non-Anglicized or less-common ones, exactly
  where Whisper is most likely to mishear/misspell) aren't in it at all,
  and can't be with a single static prompt shared across every
  jurisdiction.

  **Real gap confirmed, not assumed**: nothing in this codebase currently
  extracts attendee/council-member names from anywhere — confirmed via
  grep across every `app/platforms/*.py` adapter, no hits for
  attendance/council_member/attendee/roster. `ResolvedMeeting.agenda_items`
  (`app/platforms/models.py:41`) holds agenda *topic* text (e.g. "Item 1:
  Approve minutes..."), not a roster of who's on the body — so this would
  be new extraction work, not a matter of wiring up an existing field.
  Whether that roster is even reliably available per-platform is itself
  unconfirmed — some agenda pages/PDFs list attendees or a member roster,
  some may not, and this hasn't been checked against a real sample yet
  (same "verify against a real example before building" convention as
  every adapter in this repo).

  **Plumbing gap, separate from the extraction gap**: even with names in
  hand, today's engine has no path to use them per-job.
  `FasterWhisperEngine` (`worker/transcription_engine.py:42-86`) is
  constructed once at worker process startup and reused across every
  job's every chunk (`worker/main.py:205`,
  `engine.transcribe_chunk(audio_path)` — no per-job context passed in
  at all). Making the prompt per-meeting would need `transcribe_chunk()`'s
  signature to accept extra per-job terms, threaded through from
  wherever the worker's job loop can look up that job's `meeting_page_id`
  and its (new) extracted names.

  **Real constraint worth weighing before building**: Whisper's
  `initial_prompt` is a soft bias with a real length ceiling, not an
  unlimited instruction list — the existing comment
  (`transcription_engine.py:21-24`) already warns that an overly long or
  suggestive prompt risks the model leaning on it past where it's
  actually relevant. Appending a growing per-meeting names list to the
  existing generic vocabulary needs some care not to dilute or overflow
  it, and — per this repo's "verify with a real example" convention
  throughout — would need a real before/after check against an actual
  meeting with known misspelled names, not assumed to help just because
  it's plausible.
- **~~Resend's contact-lookup-by-email endpoint is unverified.~~ Confirmed
  live 2026-08-08.** A real request from an existing newsletter subscriber
  (`mroconnell@gmail.com`) correctly skipped the confirm-by-email step and
  went straight to `queued` — proof `archive/utils/email.py`'s
  `check_audience_membership()` and Resend's `GET /audiences/{id}/
  contacts/{email}` endpoint shape both work as written, not just
  degrading safely on failure.
- **~~Completion email's "share this" ask has no real "support us" CTA
  behind it~~ — moot as of 2026-08-11: the ask itself is gone.** The
  completion email's copy was fully rewritten that day to match
  `marketing/LIFECYCLE_EMAILS.md`'s approved "Your transcript's ready"
  copy (see the "Lifecycle-triggered transactional emails" entry above),
  which doesn't include a forward/share line at all. If a real "support
  us" ask gets built later (once accounts/billing exist — see "Archive
  roadmap" below), it'd need to be added back as new copy against that
  doc's now-current version, not restored as it was.
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

  **The UX half shipped 2026-08-12, per the user's own simpler call —
  the SEO/external-search half is explicitly still open, by choice.**
  The user re-requested a real placement/interaction change (a picker
  near the Download Text/SRT links, not a separate block above the whole
  transcript section) and, when offered the bigger all-versions-in-DOM
  JS-tabs redesign originally proposed here, explicitly opted out of it:
  alternate versions don't need to be independently searchable, and
  don't need to track playback live without a reload. What shipped
  instead: `.version-picker` is now a `<select>` dropdown (a macro,
  `version_picker()`, in `meeting_page.html`) positioned inline with the
  Download line, submitting a plain GET form to `?version={id}` — the
  same full-page-reload-per-version mechanism as the old link list, just
  restyled and repositioned, so `data-version-id`/deep-link
  time-tracking against the newly active version work unchanged (no
  changes needed to `shared_static/deep_link.js` at all). Verified live:
  seeded a real two-version test page, confirmed the dropdown shows both
  versions, selecting the non-default one reloads to `?version=2` with
  that version's own segments, download links, and `data-version-id` all
  updating together. Full suite green (440 tests).

  **Still genuinely open, deliberately not attempted**: external search
  only ever indexes the canonical `/m/{slug}` URL's single active-version
  HTML — a demoted version's transcript text is still invisible to
  Google (though already findable via this site's *own* `/meetings`
  search, per the fix above). The real fix would still be rendering every
  version's segments into the DOM with JS-toggled visibility (Google's
  documented-correct pattern for tabbed content), which needs its own
  scoped work — deep-link segment IDs would need to be scoped per version
  (`seg-{version_id}-{n}`, not today's bare `seg-{n}`) to avoid collisions
  once multiple versions' segments coexist in the same page, and Dublin's
  real transcript alone is over a megabyte of JSON, so page-size cost for
  a multi-version page needs a real check before committing to it. Not
  prioritized — revisit only if the SEO angle specifically becomes worth
  it later.

- **[Big, low priority] "Request Transcript from Audio" doesn't work for
  YouTube-hosted meetings.** Confirmed live 2026-08-10: clicking it on a
  YouTube meeting returns "We found a media source but couldn't read it
  — it may be unavailable." Root cause traced precisely, not guessed:
  `app/main.py`'s `check-feasibility` route runs `ffprobe -i
  <result.video_url>` (`app/platforms/media_probe.py`'s
  `probe_duration()`) to measure duration before allowing a job —
  but for YouTube, `result.video_url` is `https://www.youtube.com/
  embed/{video_id}` (`youtube.py`), an HTML iframe-embed *page* for the
  browser player, never a real media file. `ffprobe` can never read
  that, regardless of any blocking — this specific failure would happen
  even from a totally unblocked IP.

  **Real coupling to the still-open YouTube IP-block issue (see
  BACKLOG_DONE.md's "degrade gracefully" entries)**: the actual fix
  isn't just "point ffprobe somewhere else" — YouTube has no direct
  media-file URL by design (same reason playback needs the iframe
  Player API, not `<video>`), so getting a real downloadable stream URL
  requires yt-dlp's own extraction (the same internal pipeline already
  confirmed blocked by YouTube's anti-bot check on Render's IP for
  metadata/captions). Building real stream extraction here without
  first solving that IP block would very likely just trade one failure
  message for the same underlying block under a different one — worth
  confirming which is genuinely true (a totally separate, unblocked
  extraction step, or the same wall) before investing real build time.
  Real options for the underlying block itself (cookies-based auth, a
  PO-token-provider plugin, a proxy) were already surfaced and
  deliberately not attempted, given real cost/maintenance/risk
  tradeoffs none of them have been evaluated against yet.
