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

  **Mitigation options worth weighing, not yet decided or built:**
  - **noindex generic_fallback/`best_effort` pages by default** —
    confirmed via a direct code check: there is currently *no* per-page
    `noindex`, only a site-wide `robots.txt`. The highest-risk pathway
    (unverified, non-standard pages) is exactly the one getting full
    search-engine amplification today. Narrowest, cheapest mitigation
    on this list — doesn't block anything, just stops amplifying the
    least-verified content until a human's looked at it.
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

- **`/meetings` search-result rows wrap the title text at a different
  right margin depending on whether the row has a transcript badge.**
  Reported by the user via screenshot 2026-08-11. Root cause confirmed by
  reading the code: `archive/templates/meeting_list.html` (lines 73-88)
  renders each row as `.calendar-candidate.meeting-result-row`, a two-
  child flexbox (`.calendar-candidate-main` + an optional
  `.transcript-badge` span) using `justify-content: space-between`
  (`archive/static/style.css` lines 590-651) to push the badge to the
  right. The badge's `{% if m.has_transcript %}` (line 85) omits the
  `<span>` entirely when false, rather than rendering an empty/invisible
  placeholder of the same width — so on agenda-only rows,
  `.calendar-candidate-main` (and the unconstrained title `<a>` inside it)
  expands to fill the full row, wrapping wider than rows with a badge
  present. The CSS comment directly above (`style.css` lines 581-589)
  already describes the *intended* design ("a fixed badge column on the
  right... so the badge always lands in the same vertical line of
  sight") — the implementation just doesn't reserve that column's width
  when the badge is absent. Fix needs either a fixed `width`/`flex-basis`
  on `.transcript-badge` with the span always rendered (empty/invisible
  when no transcript), or an equivalent `flex-basis`/`max-width` on
  `.calendar-candidate-main` sized to leave the same room regardless.

## `/meetings` search & saved items — UI gaps found 2026-08-11

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

- **The saved-searches list on `/account/saved` doesn't display every
  filter that's actually saved, even though the underlying link does
  carry them.** Confirmed via `archive/templates/saved_items.html` lines
  38-48: the visible label only ever shows `sp.q` (as a quoted string, or
  "All meetings" if blank, line 43) plus `sp.jurisdiction` and
  `date_from`/`date_to` if set (lines 46-47) — `has_agenda`,
  `has_transcript`, and `fuzzy` are never rendered anywhere in the row,
  even though the `<a href>` right above (line 42) does correctly encode
  all of them into the `/meetings?...` query string. So clicking through
  re-applies the full saved search correctly, but a user scanning their
  saved-searches list has no way to tell, at a glance, that a given entry
  is (for example) filtered to "has transcript only" vs. not — the list
  under-describes its own entries. Fix is display-only: extend lines
  46-47's summary line to also surface `sp.has_agenda`/`sp.has_transcript`/
  `sp.fuzzy` when set (e.g. as extra `&middot;`-separated badges).

- **Meeting title/jurisdiction display has no consistent formatting
  convention — long names aren't truncated, casing varies row to row, and
  US states appear as both full names and two-letter abbreviations.**
  Reported by the user from real `/meetings` results (screenshot,
  2026-08-11). Confirmed there is currently **no centralized
  normalization at all** — no shared `app/utils/` helper for
  jurisdiction/title formatting exists (that directory only has
  `clerk_auth.py`, `url_normalize.py`, `vtt_parser.py`). What exists
  instead is ad hoc and per-platform: `app/platforms/granicus.py`'s
  `_humanize_subdomain()` (lines 187-214) title-cases and uppercases a
  trailing state code, but only as a last-resort fallback when its
  primary body-text regex extraction fails, and only for Granicus;
  `escribe.py`'s `_jurisdiction_from_subdomain()` (lines 192-198) does a
  blunt `.title()` with no state handling at all; `primegov.py`'s
  `_extract_jurisdiction()` (lines 128-146) only fixes all-caps headers
  (`"OKLAHOMA CITY"` → `"Oklahoma City"`) via `core.title() if
  core.isupper() else core`, leaving already-mixed-case text alone; every
  other adapter (`swagit.py:303`, `civicclerk.py:78`, `legistar.py:241`,
  `lims.py:108-112`) stores whatever casing/state form the source page
  used, unchanged. `title` gets no formatting treatment anywhere except
  an incidental `title[:500]` byte-cap in `granicus.py:185` (a
  storage-safety truncation, not a display one). None of this amounts to
  a real, consistent convention, and no adapter converts between full
  state names and abbreviations in either direction.

  **Open question, not yet decided: normalize at capture time (when a
  meeting is resolved/ingested) or at display time (formatting applied
  only when rendering search results)?** Scale differs sharply by field,
  which likely means different answers for each:
  - **State**: a closed set of ~50 values (already partially enumerated
    in `granicus.py`'s `US_STATE_ABBREVIATIONS`, lines 52-57) — cheap and
    safe to normalize once at capture time to a single canonical form
    (e.g. always store the 2-letter code). Low risk of ever mangling
    something.
  - **City/county/meeting-body names**: effectively unbounded (tens of
    thousands of real values), with real edge cases a blind
    `.title()`/casing rule gets wrong (acronyms like "MTA"/"ZBA", multi-
    word or apostrophe'd city names) — capture-time normalization risks
    silently and permanently corrupting a name with no easy undo.
    Display-time formatting (CSS `text-transform`, or a Jinja filter
    applied only at render) is non-destructive by comparison: the raw
    scraped value stays intact in the DB, and the formatting rule itself
    can be revised later without a backfill.
  - **Truncation**: almost certainly display-only regardless (CSS
    `text-overflow: ellipsis` or a length-capped Jinja filter) — capture-
    time truncation would permanently and needlessly lose data for no
    display-layer reason.

  Also relevant to any proposed fix: `jurisdiction` is confirmed to be a
  single free-text `VARCHAR(200)` column (`archive/db/models.py:33`,
  `app/db/models.py:42`) — there's no separate city/state columns
  anywhere in either schema, so a "convert full state name to
  abbreviation" rule would need to operate on the trailing portion of an
  opaque string (e.g. after the last comma), not a structured field.

## Accounts (Clerk) UI gaps found 2026-08-11

- **Missing nav divider between "My Saved Items" and "Sign in"** —
  reported by the user via screenshot. Confirmed via
  `archive/templates/base.html:44-53`: a `<li class="nav-divider ...">`
  sits before "My Saved Items" (line 45, matching the divider pattern
  used between every other nav item), but there's no equivalent divider
  between the "My Saved Items" `<li>` (46-48) and the "Sign in"/user-button
  `<li>` (49-52) — the one gap in an otherwise consistent
  divider-between-every-item pattern. One-line fix: add the same
  `<li class="nav-divider d-none d-lg-block" aria-hidden="true"></li>`
  between those two list items.
- **The nav briefly shows "Sign in" (then swaps to the account button)
  on every full page load, even for an already-signed-in visitor —
  reported by the user via "My Saved Items," which is a plain full-page
  `<a href>` navigation, so it re-triggers the flash on every click.**
  Root cause confirmed by reading the code: `archive/templates/base.html`
  (lines 44-53) always server-renders `<a ... id="clerk-sign-in-link">
  Sign in</a>` visible-by-default (no `hidden` attribute) alongside a
  `hidden` account-button placeholder — the swap only happens once
  `shared_static/clerk_nav.js` finishes loading ClerkJS asynchronously
  and calls `renderNavAuthState()` (lines 47-84), which checks
  `window.Clerk.user` client-side. There's no server-side fast path: this
  app *does* already have a working server-side session check —
  `get_clerk_user_id(request)` (`archive/utils/clerk_auth.py`) — used to
  set `active_account` in template context on specific routes
  (`archive/main.py:434`, `543`, `550`), but `base.html`'s nav block
  never references `active_account` at all, so even on a route that
  already computed it, the nav still starts from the "signed out" state
  and waits on client JS to correct itself. Fix would be picking the
  nav's *initial* rendered state from `active_account` (when present in
  context) instead of always defaulting to "Sign in," with the existing
  JS listener left in place only to handle a real client-side sign-in/out
  transition after page load, not to cover for every full navigation.

- **The Clerk sign-out flow lands the user on a bare page with no RTR
  nav/footer at all — reported live by the user.** Root cause not yet
  code-confirmed by testing a real sign-out (no live Clerk session
  available this session), but strongly indicated by the code: Clerk's
  `mountUserButton()` call in `shared_static/clerk_nav.js` (line 82) is
  invoked with no options object at all —
  `window.Clerk.mountUserButton(userButtonEl)` — so its built-in "Sign
  out" menu item uses Clerk's own default post-sign-out destination
  rather than anything on this site. **Answering the user's direct
  question: yes, Clerk supports this** — `mountUserButton()` (and/or
  `Clerk.load()`) accepts an `afterSignOutUrl` option that redirects back
  to a real in-app URL (e.g. `/`) instead of Clerk's own default/hosted
  page once sign-out completes; Clerk does not offer a way to reskin its
  *own* hosted sign-out page itself (nor is that needed here — the fix is
  redirecting away from it immediately, not styling it). Needs: (1) a
  real live sign-out to confirm this is actually where the "bare page"
  comes from (same "don't claim a fix without a positive example"
  convention as everywhere else in this file), (2) passing
  `afterSignOutUrl` (worth checking whether it belongs on the
  `mountUserButton()` call specifically or on `Clerk.load()`/the `new
  Clerk(pubKey)` constructor instead — Clerk's exact current API surface
  for this wasn't verified against live docs this pass, only inferred
  from general Clerk knowledge).

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

- **Phoenix's Legistar instance (`phoenix.legistar.com`) — one real
  meeting has no video link in the shape our parser expects; unclear
  yet whether that's Phoenix-wide or specific to this meeting.** Domain
  routing itself is confirmed correct (`phoenix.legistar.com` matches
  `_is_legistar_domain()`, so `LegistarAssetFinder` claims it as
  intended, not a routing bug). Checked live 2026-08-10
  (`MeetingDetail.aspx?ID=1425831...`): the real page's `a.videolink`
  anchor has `class="videolink audioDownloadNotAvailableLink"` and
  `data-running-text="In progress"`, with no `onclick` attribute at all
  — `_find_video_links()`'s regex requires `onclick="window.open(...)"`.
  or `OpenTelerikWindow(...)`, confirmed working on Maricopa AZ and
  NYC's Legistar instances, so finds nothing here and correctly falls
  back to Legistar's own honest "No video link found" message (not a
  crash, not silently wrong — the existing fallback behavior is doing
  its job). The meeting itself is dated 7/1/2026 (over a month before
  this check), so "In progress" is almost certainly stale leftover UI
  state, not a genuine live-meeting signal — meaning either this
  specific meeting never got a recording published, or Phoenix's
  Legistar instance uses a different video-link mechanism entirely from
  every other Legistar city confirmed so far. **Needs a second Phoenix
  meeting, ideally one confirmed to have a real published recording,
  before writing any fix** — building against one ambiguous sample risks
  exactly the kind of unverified-guess parsing this repo's whole
  adapter convention exists to avoid. Also worth noting while checking:
  Legistar's own adapter never attempts agenda-item parsing at all (by
  design, it only ever delegates to the underlying video platform for
  that), so a Legistar page never showing agenda items is expected
  behavior, not a second bug to chase.

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
- **ALL-CAPS transcript display — reported by the user 2026-08-11, but
  this is only a partial gap, not a missing feature.** A real fix already
  exists: `app/utils/vtt_parser.py:340-364`'s
  `normalize_shouting_caption()` re-cases an entire VTT/SRT/TTML track to
  sentence case, but only when its own "is this shouting" heuristic
  triggers (samples ≥40 alphabetic chars across the whole track, requires
  a ≤2% lowercase ratio) — called from `parse_vtt()` (line 96, also
  covers SRT via `parse_srt()`'s delegation to it) and `parse_ttml()`
  (line 188). Rendering itself (`archive/templates/meeting_page.html:276`,
  `{{ seg.text }}`) and storage (`archive/db/crud.py:267,310`, segments
  stored verbatim into `TranscriptVersion.segments`) apply no casing
  transform of their own — whatever `vtt_parser.py` already normalized is
  exactly what's stored and shown, so this was always meant to be a
  parse-time fix, not a template/CSS one, and largely already is one.
  **The real, still-open gap**: `strip_unknown_caption_markup()`
  (`vtt_parser.py:199-224` — the SBV/SUB/SMI/SAMI/plain-.txt fallback
  described just above) never calls `normalize_shouting_caption()` at
  all, so an ALL-CAPS transcript from one of those formats stays ALL
  CAPS unconditionally. A real VTT/SRT/TTML track could also in principle
  still slip through if it's shouting but doesn't clear the detection
  heuristic's thresholds (mixed-case enough, or under the 40-letter
  sample minimum) — worth checking against the specific transcript the
  user actually saw before assuming which case this is.
- **Literal `&gt;&gt;` (etc.) sometimes rendering as visible text instead
  of `>>` — reported by the user 2026-08-11; confirmed as a real,
  structurally-understood double-escaping bug, narrower than it might
  look.** `archive/templates/meeting_page.html:276` renders `{{ seg.text
  }}` with Jinja's default autoescaping on (`archive/main.py:50`'s
  `Jinja2Templates`, confirmed via Starlette's own
  `autoescape=True` default) — correct and necessary for real `<`/`>`/`&`
  characters in transcript text. The bug: if a caption source's *raw*
  text already contains the literal 8-character string `&gt;&gt;`
  (already-HTML-escaped text embedded directly in the source, not a real
  `>` character — confirmed present in raw YouTube auto-caption VTT) and
  nothing unescapes it once during parsing, Jinja's autoescape then
  escapes the `&` a second time (`&` → `&amp;`), producing `&amp;gt;&amp;gt;`
  in the actual HTML response, which a browser correctly renders back as
  the literal text `&gt;&gt;` on screen — a classic double-escape, not a
  missing-escape bug.

  **What's already fixed, narrowly, on purpose**: `vtt_parser.py:367-383`'s
  `normalize_speaker_change_marker()` (called from `parse_vtt()` line 97
  — VTT/SRT only, not TTML) matches *exactly* `&gt;&gt;` **anchored to the
  start of a cue** and converts it to a real `»` character — a
  deliberately narrow fix (see `BACKLOG_DONE.md:1269-1300` for the
  original reasoning and its regression test), not general HTML-entity
  unescaping; a real `html.unescape()` call doesn't exist anywhere in
  `vtt_parser.py` (confirmed via grep — the repo's only `html.unescape()`
  calls are in `app/platforms/lims.py`, unrelated). **What's still
  genuinely unhandled**: the same `&gt;&gt;` string appearing mid-cue
  rather than at the very start; any other HTML entity (`&amp;`, `&#39;`,
  `&lt;`, `&quot;`, `&nbsp;`, etc.) arriving pre-escaped in source caption
  text; and the entire `strip_unknown_caption_markup()` fallback path
  (SBV/SUB/SMI/SAMI/plain-.txt), which has no cue-level text normalization
  of any kind. TTML doesn't need this fix — its text comes from
  `ElementTree`'s own `itertext()` (line 184), which already resolves
  real XML entities during parsing, so this specific artifact can't arise
  there. A general fix would need a real (not narrowly-anchored)
  `html.unescape()` pass at the same point in the pipeline where
  `normalize_speaker_change_marker()` already runs, careful not to
  double-unescape text that was never double-escaped in the first place.
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

  **Status as of 2026-08-10: deployed to staging and live-verified by
  the user with their own real Clerk account, not yet merged to
  main/prod.** All routes/tables/webhook/frontend wiring built, 391
  tests passing. Live-verified on `rtr-deeplink-staging`/
  `rtr-deeplink-archive-staging`: real Google-OAuth sign-in via Clerk,
  "Save this meeting"/"Save this search" round-tripping to
  `/account/saved` and back, and the `user.created` webhook
  (Clerk's own delivery log showed "Successful Attempts: 1, Failed
  Attempts: 0" against `/api/clerk/webhook`, wired to the existing
  Resend auto-subscribe). A follow-up UI polish pass (nav, button
  sizing/prominence, `/account/saved` layout, a bookmark icon next to
  the meeting title) landed the same day, also live-verified locally
  and pushed to the branch.

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
- **Lifecycle email bugs found by the user 2026-08-11, real live example
  seen ("Your transcript's ready" via Gmail) — four separate issues, one
  of them root-caused to a precise one-line fix, not just "the excerpt
  looks off":**
  - **The transcript excerpt in the completion email is *always* empty
    (renders as just "…"), for every email, unconditionally — root cause
    fully traced, not guessed.** `worker/main.py:231-253`'s
    `_send_completion_email()` looks up the excerpt via `status.get(
    "transcript_version_id")` (line 240) to find the matching version in
    `page["versions"]`, then joins that version's segment text (line
    244). But `status` comes from `crud.get_transcription_job_status()`
    (`archive/db/crud.py:1088-1094`), which returns `_job_dict(job, page)`
    (line 1072-1085) — and **`_job_dict()`'s returned dict has no
    `transcript_version_id` key at all**, even though the job row itself
    does carry a real one (`job.transcript_version_id`, set at line 1057
    in `report_chunk_result()` once the job completes). So `status.get(
    "transcript_version_id")` in the worker always evaluates to `None`,
    the generator matching `v["id"] == None` against real integer version
    ids never matches anything, `version` stays `None`, and `excerpt`
    never leaves its `""` initial value (`worker/main.py:236`) — which
    then renders as bare `&hellip;` in `archive/utils/email.py:257`
    (`{html.escape(excerpt)}&hellip;`). This isn't an occasional or
    edge-case failure — every single completion email hits this same
    path and fails the same way, always. **Fix is a one-line addition**:
    add `"transcript_version_id": job.transcript_version_id,` to
    `_job_dict()`'s returned dict (`archive/db/crud.py:1072-1085`) — the
    data already exists on the model, it's just never surfaced through
    this function.
  - **The email header doesn't match the site nav's actual "dymo label"
    look, for two compounding reasons, not one.** Confirmed via
    `archive/static/style.css:33-46`'s real `.dymo-label` rule: real
    background `#b71c1c` (red), text **not** uppercased in CSS at all
    (no `text-transform`) — the *HTML source* itself is already Title
    Case (`archive/templates/base.html:22`, `Red Tape Recordings`), and a
    real `text-shadow: 0 2px 2px #7b1010, 0 -1px 1px #7b1010` emboss
    effect. Critically, on the actual site this red label sits *inside* a
    separately-dark navbar (`<nav class="navbar ... bg-dark">`, Bootstrap's
    near-black navbar background) — the red label reads as a label
    precisely because it contrasts against that dark bar. The email's
    header (`archive/utils/email.py:188-201`) gets this backwards: the
    *outer* `<td>` itself is set to the label's own red
    (`background:#b71c1c`, line 192), while the inner `<span>` (line 193)
    has no background of its own, just a border — so in the email, the
    "label" is really just an amber-outlined box sitting on a background
    of its own same color, with no contrasting dark bar at all, and the
    text is hardcoded ALL CAPS (`RED TAPE RECORDINGS`) rather than the
    site's real Title Case. **Fix needs both changed together**, not just
    one: the outer `<td>` background should become a dark/near-black
    shade (matching `bg-dark`) instead of red, *and* the inner `<span>`
    needs its own explicit `background:#b71c1c` added (since it currently
    only shows red by inheriting the outer cell's color — removing that
    without adding the span's own background would leave a black box with
    no red label inside at all); text should change to `Red Tape
    Recordings`. The missing emboss (`text-shadow`) is very likely a real
    HTML-email-client limitation, not a bug to chase — text-shadow support
    across email clients (Gmail included) is notoriously unreliable, so
    the user's own guess ("might be my email client") is probably right;
    not worth spending effort on unless a client-safe alternative (e.g. a
    tiny background image) is deliberately chosen later.
  - **Neither "Red Tape Recordings" occurrence (header, and the sign-off
    at the bottom) is a clickable link to the site.** Confirmed via
    `archive/utils/email.py`: the header `<span>` (line 193) and
    `_signoff_html()`'s `<p>` (lines 204-210, "Red Tape Recordings" as
    the last line) are both plain, unlinked text. Straightforward fix —
    wrap both in `<a href="{base}">`, where `base` is
    `os.environ.get("PUBLIC_BASE_URL", "")`, already read this exact way
    elsewhere in the same file (line 60) — but note neither
    `_branded_wrapper()` (line 172) nor `_signoff_html()` (line 204)
    currently accepts a URL parameter, so both signatures would need to
    grow one (and every call site updated to pass it through).
  - **Split off, not built this pass**: "People are talking about…"
    (saved-search alert emails, the doc's #5) — a real new feature (match
    detection + a per-alert one-click unsubscribe token), not just a
    template wired into an existing event. See the "Email alerts for
    saved searches" entry directly below, which is the same feature.
    The doc's own "Digest variant of #5" (batching multiple alerts into
    one email) is explicitly flagged there too as later-still: Resend has
    no built-in batching, so a digest needs its own accumulation +
    scheduled-or-event-driven send logic, not just copy.
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
- **Search bar has no explicit boolean operators (AND/OR/NOT/`-`/`+`/`&`)
  today — user request 2026-08-11.** Confirmed via
  `archive/utils/search.py`: `_parse_query()` (lines 64-77) splits a query
  into quoted phrases (`_PHRASE_RE`, line 14 — each required as an exact
  adjacent substring) and unquoted words (split on whitespace, line 76) —
  every phrase and every word is independently required, an **implicit
  AND with no way to express OR, an explicit AND, exclusion (NOT/`-`), or
  a literal `&`.** `matches()` (lines 84-107) enforces this directly:
  `all(phrase in corpus for phrase in phrases)` and (non-fuzzy)
  `all(term in corpus for term in terms)` — there's no code path anywhere
  that treats two terms as alternatives or excludes one. This is a
  hand-built Python scanner, not a real query-language parser or an
  indexed engine's query syntax (the module's own docstring: "no search
  index... fine at the Archive's current scale, not meant to scale past a
  few hundred") — so operator support has to be added by hand to
  `_parse_query`/`matches`, not inherited for free the way Postgres
  `tsquery` would give it.

  **Per-operator feasibility, not yet decided/built:**
  - **`-term` (exclusion/NOT)** — the most tractable addition: mark a
    term prefixed with `-` as "must not match," then require
    `term not in corpus` (or the fuzzy equivalent) instead of `in`. Small,
    contained change to `_parse_query`'s word-splitting and one new
    branch in `matches()`.
  - **`+term` / explicit `AND`** — effectively already the default
    behavior for every unquoted word today; would just need `+`/`AND` to
    be stripped as a no-op synonym rather than treated as a literal
    search term (right now a literal `+flock` or the word `AND` would be
    searched for verbatim, which is itself a minor rough edge worth
    fixing alongside real operator support).
  - **`&`** — same as above: redundant with implicit AND, so this is
    about *not* treating it as a literal character to match, not a new
    capability to build.
  - **`OR`** — the one genuinely hard part: `_parse_query` currently
    returns two flat lists that all get ANDed together with no concept of
    grouping — supporting `a OR b` (let alone mixed precedence like `a OR
    b AND c`) needs a real expression tree, not just a new token type.
    Worth deciding whether full boolean-expression parsing is actually
    needed, or whether `-exclude` plus no-op `+`/`AND`/`&` covers most of
    the practical value a journalist would want, at a fraction of the
    parser complexity.

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
- **A parallel disclaimer for source-provided (non-AI) transcripts —
  user request 2026-08-11, liked the existing AI-transcript disclaimer
  and wants an equivalent for the other case.** Confirmed via
  `archive/templates/meeting_page.html:262-267`: the amber "AI
  TRANSCRIPT" disclaimer box (`.ai-disclaimer`, `.dymo-label-small`) only
  renders `{% if active_version.source == "transcribed" %}` — a
  source-scraped transcript (`source="scraped"`, set at
  `archive/db/crud.py:308`, the actual value for every platform-provided
  caption) gets **no disclaimer at all** today, even though it's also
  unreviewed-for-accuracy content pulled from a third party, exactly the
  gap the user's asking to close. Their suggested copy: "This transcript
  is downloaded from the source you provided but we haven't reviewed it
  for accuracy. Treat it as a starting point, not a verbatim record. You
  can request an AI-transcription of the audio file by clicking here."

  Straightforward to build, and the CTA piece is nearly free: the
  "Request Transcript from Audio" button already exists and already
  appears on exactly these pages — `show_transcribe_cta`
  (`meeting_page.html:75`) is `True` precisely when the active version
  isn't a `"transcribed"` one, and the button itself renders right above
  the transcript at line 164-165 (`id="transcribeToggle"`). So the new
  disclaimer's "click here" doesn't need new plumbing, just an in-page
  anchor/JS trigger pointing at that existing button rather than
  duplicating its behavior. Implementation shape: add an `{% elif
  active_version.source == "scraped" %}` branch alongside the existing
  `{% if ... == "transcribed" %}` at line 262, with its own label/copy
  (worth a distinct color or label text from "AI TRANSCRIPT" — e.g.
  "SOURCE TRANSCRIPT" — so the two disclaimers stay visually
  distinguishable at a glance, not just distinguishable by reading the
  copy).
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

  **User independently re-requested this exact UI, 2026-08-11**: real
  tabs above the transcript pane, near where "Download Text/SRT"
  currently sits, to switch between multiple transcript versions for the
  same meeting (their concrete example: choosing the government's own
  captions over this app's AI-generated transcript even when the AI
  version happens to be the current default/surfaced one). This is the
  same feature as the JS-tabs redesign above, not a new one — the
  existing `.version-picker` (`archive/templates/meeting_page.html`,
  `?version=` link list, full page reload) already lets a visitor pick a
  non-default version, just not as inline tabs; this request is really
  about that picker's *placement and interaction style* specifically
  (tabs, positioned by the download links) rather than new underlying
  capability. Bumps this from "worth building for SEO reasons" to also
  "a real user-requested UX improvement," which may be worth weighing
  when prioritizing against everything else in this file.

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
