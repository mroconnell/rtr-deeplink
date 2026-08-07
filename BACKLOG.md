# Backlog

Known bugs and features not yet addressed, roughly in priority order.

## Bugs

- **[Done 2026-08-06 for Legistar/CivicPlus; investigated for PrimeGov —
  not applicable] Unsupported-platform failure is too blunt.** Fixed for
  Legistar and CivicPlus specifically: both delegate to the embedded
  Granicus link when present, and a calendar/listing page returns a
  pick-list of real meetings rather than a bare error (see Platform
  coverage section below). The remaining "no adapter at all" case is only
  PrimeGov today (detected but unregistered) — investigated whether the
  same "find an embedded supported-platform link, then delegate" pattern
  would help there: checked 3 real PrimeGov cities (Los Angeles, San Jose,
  Petaluma) and all three embed video via a **YouTube** iframe player
  (`youtube.com/iframe_api` + a JS-driven show/hide player, video ID not
  statically present in the page HTML), not a link to any
  currently-supported vendor platform. Unlike Legistar/CivicPlus (which
  really are just wrappers around Granicus), PrimeGov is a genuine
  distinct video host — the "find a supported link" fallback has nothing
  to find here, so building it as a generic mechanism wouldn't help the
  one real unsupported case that exists. A real PrimeGov/YouTube adapter
  is a separate, bigger undertaking (extracting the video ID from page JS,
  and YouTube captions would need their own fetch path with no equivalent
  to Granicus's predictable `captions.vtt`) — not attempted this session.
- **[Done 2026-08-06] Zero-caption Granicus meetings — investigated with
  fresh real meetings** (since the original test clip IDs weren't recorded
  anywhere, re-tested against a current real meeting per flagged city:
  Cupertino, Mountain View, Berkeley, Paradise Valley AZ, San Diego city).
  Findings: Cupertino and San Diego now resolve real captions fine
  (2191 and 7349 segments) — the original zero-caption cases were likely
  specific to those particular old meetings, not a systemic bug. Berkeley
  and Paradise Valley AZ have a genuinely blank source `captions.vtt`
  (confirmed by fetching it directly — the standard 8-byte
  `"WEBVTT\n\n"` placeholder Granicus creates whether or not captioning
  was ever generated) — already correctly detected and warned about, not
  a bug. Mountain View uncovered a real bug, now fixed (see below).
- **[Done 2026-08-06] Real bug: caption/video-ID guessing used the
  pre-redirect URL, so `MediaPlayer.php?clip_id=...` links (how Granicus's
  own UI shares a link) never got their captions.vtt path guessed at
  all.** Found via the Mountain View investigation above: its page has no
  `<track>` tag (Flowplayer-based UI, not native HTML5 captions), so the
  guessed-path heuristic in `_extract_media_urls` was the *only* way to
  find its captions.vtt — but that heuristic pattern-matched against
  `granicus.com/player/clip/` or `granicus.com/videos/`, which a
  `MediaPlayer.php?view_id=&clip_id=` URL never matches even though it
  redirects to `/player/clip/{id}` immediately. Fixed: `_fetch_page` now
  returns the post-redirect URL alongside the HTML, and all URL-shape
  matching (`_extract_clip_id`, media guessing, RSS view_id/clip_id
  lookup) runs against that instead of the originally-submitted URL.
  Confirmed via real Mountain View, San Francisco, and DC
  `MediaPlayer.php` links — jurisdiction/date/captions all resolve
  correctly now where they silently wouldn't have before.
- **[Done 2026-08-06] Date extraction fixed via RSS `pubDateParts`.**
  `_fetch_channel_info` (renamed in spirit, same function) now also
  matches the resolved meeting's `clip_id` against the
  `ViewPublisherRSS.php` feed's `<item>` entries and reads the structured
  `<gran:pubDateParts yr= mo= day=>` attributes — confirmed live against 3
  of the originally-failing cities: San Francisco (clip 52945, page has
  no date signal anywhere — title is just "Board of Supervisors - Regular
  Meeting" — RSS gives 2026-07-28 correctly), DC (clip 10801 → 2026-07-14),
  Mountain View (clip 5389 → 2026-07-09). San Diego and Cupertino's fresh
  test meetings already had dates in their titles, so weren't a live
  reproduction of the original bug, but the RSS path is exercised for
  them too. **Alexandria VA remains unfixed** — confirmed its meeting
  page has no `view_id` in the URL at all (so no RSS feed to match
  against) and no date signal anywhere in the page body either; no
  further fallback source identified.

- **[Done 2026-08-06] Jurisdiction/title metadata cleanup.** Fixed via three
  tiers: the Granicus RSS channel title (constant per `view_id`, confirmed
  format `"{Jurisdiction}: {Body} (Videos Feed)"` across 6 cities) is tried
  first and also used to prepend the governing body to titles that don't
  already name one; then a "City/County/Town of X" (or reversed "X
  County") text search across page body *and* meta description (the
  sdcounty.granicus.com case only had it in `<meta name="description">`,
  invisible to `soup.get_text()`); then `wordninja`-based subdomain
  segmentation as a last resort (`sandiego` &rarr; "San Diego" instead of
  "Sandiego"). Applies to Legistar/CivicPlus too since both delegate to
  GranicusAssetFinder. One known residual gap: `dc.granicus.com` still
  resolves to jurisdiction "Dc" — no page-text signal or view_id available
  to do better, and not worth a DC-specific hardcode for one city.

- **[Done 2026-08-06] Caption quality heuristic.** `is_likely_garbled()`
  (`app/utils/vtt_parser.py`, shared by Granicus/eScribe/CA Legislature)
  flags a transcript as likely-garbled-at-the-source when >6% of its
  words are short junk fragments (≤2 letters, not a real short English
  word like "a"/"to"/"is"). Threshold calibrated against real samples:
  Alexandria VA's confirmed-garbled captions (clip 6490 — fragments like
  "test meele first item on t", "last meeting.Oa") sit at ~17%, while four
  independently-confirmed clean real sources (Boston, San Diego, DC, San
  Francisco) all sit under 2% — comfortable margin on both sides. Live
  re-verified after implementation: Alexandria correctly gets the new
  warning message (with the same manual-transcription contact CTA as the
  blank-VTT case), Boston/SF/DC/San Diego/Cupertino all resolve with zero
  false positives.

- **[Done 2026-08-06] Caption language detection.** Fixed: found via live
  review that Simi Valley clip 2840's only caption track is labeled
  `srclang="en"` on the page but is actually Spanish content (confirmed by
  fetching the raw VTT). `GranicusAssetFinder` now detects the real
  language of caption text via `langdetect` rather than trusting the page
  label, prefers a track matching `TARGET_LANGUAGE` ("en") when multiple
  tracks exist, and surfaces a warning when the best available track
  doesn't match. Follow-up not yet built: a UI dropdown to let the user
  pick between multiple language tracks when more than one exists (the
  user's original ask) — right now we auto-pick the best match and warn,
  we don't yet expose the alternates.

- **[Done 2026-08-06] San Francisco's ALL CAPS captions normalized.**
  `_normalize_shouting_caption()` (`app/utils/vtt_parser.py`, runs inside
  `parse_vtt` so every platform benefits) detects a track as
  all-caps-at-the-source (essentially zero lowercase letters across a
  40+-letter sample) and re-cases it to sentence case, capitalizing after
  real sentence punctuation across cue boundaries (cues are joined with a
  placeholder before casing, so a sentence split mid-cue isn't treated as
  two separate sentence starts) rather than per-cue. Confirmed live: a
  real San Francisco Board of Supervisors meeting (clip 52945) that was
  genuinely ALL CAPS at the source now renders as normal sentence-case
  text (e.g. "the july 28th 2026 regular meeting of the san francisco
  board of supervisors. Madam clerk, please call the roll."). Spot-checked
  the other 6 meetings with real transcripts (2026-08-06): 5 of 6 English
  ones (San Diego, Oakland, Boston, San Francisco, DC) are genuinely
  readable with only minor rough patches (a few garbled words
  mid-Boston); Alexandria VA remains the one clear outlier at genuinely
  unreadable quality — now caught by the caption quality-detection item
  above.

## UX polish (from live review, 2026-08-06)

- **[Done 2026-08-06] Video player sizing, play button, poster, and
  awkward-pause-on-play.** All four addressed together: the video wrapper
  now locks a 16:9 aspect-ratio via CSS so it never collapses to a tiny
  default box; a large, obvious overlay play button replaces the small
  native control-bar triangle; and a one-time muted-play-then-pause on
  `loadedmetadata` both renders a real first frame (serving as a poster,
  no separate thumbnail-fetch needed) and pre-buffers the initial
  segments, so the user's actual first play click starts instantly instead
  of visibly waiting to buffer — confirmed this measurably works in
  testing. Verified in-browser on desktop and mobile widths, and confirmed
  no regression to deep-link seeking (a real risk: the warm-up's play/pause
  could have clobbered a pending deep-link seek, since `currentTime` set
  before metadata loads just queues as the "default playback position" —
  fixed by capturing and restoring that value instead of resetting to 0).
- **[Done 2026-08-06] Transcript search, per-line link icon, manual
  timestamp entry, sticky toolbar.** All four verified end-to-end against
  a real 1073-segment Boston meeting. Search mirrors browser Ctrl+F
  (highlight all matches, "N/M" count, prev/next + Enter/Shift+Enter
  navigation — confirmed 21 real matches for "sidewalk"). Each transcript
  line has a chain-link icon that copies a link to that line without
  moving playback (distinct from clicking the timestamp, which seeks);
  after a follow-up look it was enlarged (14px&rarr;17px) and now also
  shows at rest (opacity 0.6) on whichever segment is current when the
  video is paused, suppressed during playback so it doesn't flicker line
  to line with auto-scroll. A "Go to time" input (accepts H:MM:SS, M:SS,
  or seconds) sits in the video toolbar and works even with no transcript,
  since deep-linking to a moment — not the transcript — is the primary
  goal. The toolbar itself is now `position: sticky` so it stays reachable
  when scrolling past it, addressing the original auto-scroll-fights-you
  complaint.
- **[Done 2026-08-07] "View original source" link on the meeting page.**
  Links back to the original government meeting page (`data.source_url`)
  in a new tab, styled small/muted so it reads as an outbound link rather
  than the page's own title. `source_url` is a required field on
  `ResolvedMeeting`, so this renders for every successfully-resolved
  meeting regardless of platform.

- **Newsletter signup box doesn't match the brand.** Built quickly with
  plain Bootstrap (`.btn.btn-primary` blue button, plain `.form-control`
  input) rather than the site's actual visual language — no dymo-label/
  cassette treatment, no Georgia/mono type pairing, doesn't feel like
  the rest of the page. Needs a real design pass, not just a font swap.
  Open question worth deciding when picked up: does it get its own
  cassette-btn-style treatment, or does that stay reserved for the two
  existing "rewind to a moment" buttons (homepage submit, "Copy link to
  current time") per the explicit scoping comment already in
  `style.css` — a signup button isn't really a "rewind" action, so a
  new-but-consistent treatment may fit better than reusing cassette-btn
  as-is.
- **[Done 2026-08-07] "Get Updates" link in the site nav pointing at
  the email signup.** Went with the footer-anchor approach (no new
  page): `href="#newsletterForm"` in `base.html`'s nav, plus a small
  `newsletter.js` enhancement that focuses the email input ~300ms after
  the click so it's not just a scroll — one less click for someone who
  came specifically to sign up. Verified in-browser: link renders with
  the correct href in the collapsed-nav menu, and `document.activeElement`
  is confirmed to be the email input after clicking it.

- **[Done 2026-08-07] Spinning cassette-reel animation on the "please
  wait" fetch message.** `player.js`'s loading-state line now renders
  two `.cassette-reel` SVGs (reusing the existing icon markup) with a
  new `.spinning` modifier class — a slower 1.6s spin than the 0.8s
  hover flourish elsewhere, since this can run for up to ~20s and a
  quick spin reads frantic sustained that long. Verified the animation
  is actually wired (not just present in markup) via computed style —
  `animationName: "reel-spin", animationDuration: "1.6s"` — after
  confirming a byte-fresh fetch of `style.css` contains the rule.

- **CivicClerk's real caption/transcript format is unverified.** The API
  schema has `EventsMedia.closedCaptionUrl`, `.transcriptionUrl`, and
  `.closedCaptionTracks`, but every sample meeting checked (Clovis CA,
  Highland CA, Lino Lakes MN) had these null/empty, so `CivicClerkAssetFinder`
  currently just shows a "not verified yet" warning when one of those fields
  is non-null instead of trying to parse it. Needs a real example with
  populated caption data to build and test that path properly.

## Platform coverage

- **[Done 2026-08-06] Legistar adapter** — confirmed and built: Legistar is
  purely a calendar/agenda wrapper, video always redirects via
  `Video.aspx?Mode=Granicus&ID1={id}&Mode2=Video` straight to Granicus.
  See `app/platforms/legistar.py`.
- **[Done 2026-08-06] CivicPlus adapter** — confirmed and built, same
  pattern as Legistar: an AgendaCenter listing page (`tr.catAgendaRow`
  rows) has a direct per-meeting video link in `td.media` when video
  exists (confirmed real: `ca-westlakevillage.civicplus.com`, 16 real
  Granicus links across one listing page). No "single meeting" URL shape
  observed — every AgendaCenter URL is a listing, so >1 video row always
  raises the calendar pick-list. See `app/platforms/civicplus.py`.
- **Row-level CC/SRT files in calendar listings — not yet found, keep
  watching for a real example.** User's instinct: some Legistar/CivicPlus
  calendar rows might expose a direct caption file link alongside the
  video link, which could be more reliable than whatever the destination
  video platform's own page offers (we've seen those come back empty a
  lot). Checked and found nothing in: Maricopa AZ (Legistar), Westlake
  Village CA (CivicPlus), and on a hunch from the user, San Diego city,
  San Diego County, and both `berkeley.legistar.com` and
  `cityofberkeley.legistar.com` calendars — none had a `.srt`/`.vtt`
  link in their row markup. Not disproven, just not found yet. When a
  concrete example turns up, extend `LegistarAssetFinder`/
  `CivicPlusAssetFinder`'s row-scraping to check for a caption link
  alongside the video link, and prefer it over (or merge with) whatever
  the destination platform returns. Separately: user also asked about
  backfilling captions for a *directly*-submitted media page by checking
  whether it came from a calendar with a caption file — not worth
  building; there's no reliable way to know which calendar (if any)
  originally listed a given direct video URL.
- **[Done 2026-08-07] Granicus agenda-item chapter-marker fallback,
  same role as CivicClerk's `eventBookmarks`/Swagit's `.playerControl`.**
  When there's no usable transcript, `GranicusAssetFinder` now tries
  `AgendaViewer.php?clip_id={id}&embedded=1` — Granicus's own agenda-index
  feature, when a customer has it turned on, renders each item as
  `<a name="agenda{id}" onclick="top.SetPlayerPosition('0:{seconds}',null)">
  {title}</a>`. Confirmed live: works on Simi Valley (17 items) and San
  Francisco (82 items). **Does not help either of the two jurisdictions
  confirmed genuinely blank-caption in the 2026-08-06 zero-caption
  investigation above**: Berkeley redirects `AgendaViewer.php` to its own
  external site (`berkeleyca.gov`) instead, with an empty `cuepoints`
  array on the player page too; Paradise Valley AZ redirects it to a
  Google Docs PDF preview, and its `cuepoints` array has real
  timestamps/ids but no titles anywhere to pair them with. Both simply
  return zero items and fall through to the existing "no transcript"
  warning, so this is additive, not a regression, for jurisdictions that
  don't have it. Real ratio of "has native agenda index" vs. "redirects
  elsewhere" across Granicus's full customer base is unknown — worth
  revisiting once more jurisdictions are checked.
- **[Done 2026-08-07] Surface an agenda link even when there's no
  timestamped chapter data (Berkeley/Paradise Valley AZ style).**
  `_fetch_agenda_items()` now returns `(items, fallback_url)` — when
  the native `<a name="agenda...">` structure isn't found but the
  request still resolved to a real page, `fallback_url` is that page's
  URL (`response.url` after `AgendaViewer.php`'s redirect, same pattern
  `_fetch_page` uses for the main page), and `resolve()` appends a
  plain "agenda is available here: {url}" warning instead of
  discarding it. Also fixed to make it *actually* clickable: `player.js`
  was rendering all transcript warnings through `escapeHtml` (plain
  text only), so a URL in a warning would've shown as inert text — new
  `linkifyWarning()` escapes first, then wraps bare URLs in a real
  `<a target="_blank">`. Verified against live Berkeley and Paradise
  Valley AZ (both get `fallback_url`, Simi Valley's 17 real items
  correctly get `None`), and end-to-end in-browser that the rendered
  warning contains a real anchor tag. Not yet investigated: whether
  this redirect-target pattern holds generally across other Granicus
  customers who lack the native agenda index, or is specific to these
  two.
- **Give the meeting page a dedicated "Agenda" section, structurally
  separate from "Transcript."** Right now agenda/chapter-marker data
  (Granicus's `AgendaViewer.php` items, CivicClerk's `eventBookmarks`,
  Swagit's `.playerControl` markers) gets folded directly into
  `ResolvedMeeting.segments` as if it were transcript content, only
  when there's no real transcript at all (`if not segments` in
  `granicus.py`) — that conflation was a reasonable v1 shortcut but
  doesn't hold once agenda is meant to be its own thing. Needs: a new
  field on `ResolvedMeeting` (e.g. `agenda_items`, kept separate from
  `segments`) populated independently of transcript availability; a new
  `#agendaSection` in `meeting.html` with its own "Agenda" heading,
  mirroring the existing transcript section's structure; `player.js`
  rendering for it (agenda items are start-time-linkable when Granicus's
  native structure is available, otherwise likely just plain text or
  the link-out from the item above). This also means revisiting
  `app/db/outcomes.py`'s `classify_outcome()` — the `agenda_fallback`
  bucket currently depends on detecting the shared warning-text marker
  inside `transcript_warnings`/`segments`; once agenda moves to its own
  field, that detection logic needs to move with it rather than break
  silently.
- **Always attempt to load the agenda, even when a real transcript
  exists.** Depends on the previous item's schema change (agenda as its
  own field, not conflated with `segments`). Currently
  `GranicusAssetFinder.resolve()` only calls `_fetch_agenda_items()`
  inside `if not segments:` — meaning a meeting with a perfectly good
  transcript never gets its agenda fetched at all. Decouple the two:
  fetch/attach the agenda regardless of transcript outcome, since it's
  useful navigation context either way (per the user's ask — agenda
  section loads under the video, transcript section below that, when
  both exist).
- **[Done 2026-08-06] CivicClerk, Swagit, eScribe adapters built.**
  BoardDocs deliberately excluded — confirmed across 2 real cities (South
  Portland ME, Taos NM) it's a document/agenda platform with no reliable
  video, despite a site-level `bd.videoservice` flag; not worth a
  video-resolver adapter. Also confirmed (Taos NM sample) that agendas
  embedding a live Zoom meeting ID/passcode give no path to a recording —
  Zoom join links and cloud-recording URLs are unrelated and unguessable
  from each other, and Zoom's Recordings API requires OAuth credentials
  tied to the hosting account, not a public lookup. Not building a Zoom
  integration; if a city happens to separately publish a real
  `zoom.us/rec/...` link on a page, normal page-scraping would already
  pick it up like any other link.
- **Swagit `#transcript-fragments` unverified.** The page's JS references
  `#transcript-fragments a[data-ts]` for a real free-text transcript
  feature, but that container was never present in the static HTML across
  any sample checked (a candidate forum and a full regular meeting) — only
  the `.playerControl` chapter markers were. `SwagitAssetFinder` checks for
  it defensively but has never seen it populated. Needs a real example.
- **Swagit custom-domain embeds unverified** (e.g. `dublin.ca.gov/
  swagit-video-player?video_id=...`). `detect_platform` recognizes the
  `swagit-video-player` path pattern, but the one sample URL for this case
  in the sample sheet 404'd (stale), so `SwagitAssetFinder`'s actual page-
  parsing has only been verified against real `*.swagit.com` domains, not
  a city's own iframe-wrapper page. Needs a fresh sample URL.
- **eScribe caption content-quality unverified.** iSiLIVE's per-language
  VTT naming convention (`{file}.vtt` = English, `{file}.fr.vtt`, etc.) was
  confirmed structurally on Richmond, CA, but none were actually populated
  (all 404) — so `EscribeAssetFinder`'s caption-fetching path is
  shape-verified only, not content-verified. Needs a real eScribe meeting
  with actual captions to confirm quality/format end-to-end.

## Reporting & caching

- **[Done 2026-08-07] Per-adapter reporting log + read-through cache.**
  New `app/db/` layer (SQLAlchemy async, Postgres via `DATABASE_URL` in
  prod — Render Postgres, user's choice over Neon/Supabase — local SQLite
  fallback otherwise). `/api/resolve` now checks for a prior successful
  resolve of the same normalized URL before fetching live, and logs every
  attempt (success or failure) unconditionally to `meeting_resolutions`.
  All DB calls are wrapped so a down/misconfigured database degrades
  silently rather than breaking resolving — verified live by pointing
  `DATABASE_URL` at an unreachable host and confirming `/api/resolve`
  still returned correct results with no 500. Two token-gated endpoints:
  `GET /admin/stats` (aggregates) and `GET /admin/log` (unaggregated
  per-URL list, JSON or CSV). Also added `external_id` to `ResolvedMeeting`
  (populated so far by Granicus and CivicClerk from ids they already
  extract internally) as a foundation for future dedup.
- **[Done 2026-08-07] Outcome classification fixed to reflect content
  quality, not just resolve status.** Real gap found via live testing: a
  resolve that returns a video with zero transcript segments — or with
  only chapter-marker fallback data (Granicus/CivicClerk/Swagit) — was
  counting as `"success"` in the reporting log, since both `status="success"`
  and `segments` being non-empty (chapter markers still populate
  `segments`) looked identical to a real transcript from the logging
  code's point of view. `app/db/outcomes.py`'s `classify_outcome()` now
  buckets every row into `success` / `agenda_fallback` / `blank_transcript`
  / `garbled_transcript` / `non_english_transcript` / `no_video`, on top of
  the existing `resolve_failed` / `calendar_page` / `unsupported_platform`
  cases — verified against live Simi Valley (garbled Spanish captions),
  Paradise Valley AZ (genuinely blank, no fallback available), and a
  synthetic test covering all five content-quality buckets directly.
- **[Done 2026-08-07] Real bug: non-UTF-8 captions.vtt crashed the whole
  transcript fetch.** `_fetch_vtt` in Granicus/eScribe/CA Legislature all
  called aiohttp's `response.text()`, which decodes strictly as UTF-8 and
  raises `UnicodeDecodeError` on anything else — confirmed live on Simi
  Valley clip 2840, whose real Spanish-language `captions.vtt` isn't valid
  UTF-8 (`0xf3` at byte 241), producing zero segments and a transcript
  warning instead of the actual captions. New `decode_vtt_bytes()`
  (`app/utils/vtt_parser.py`) reads the response as raw bytes and tries
  UTF-8, then Windows-1252, then finally UTF-8 with `errors="replace"`,
  shared by all three platforms' `_fetch_vtt`. Verified live: Simi Valley
  clip 2840 now returns 394 real Spanish-language segments instead of the
  decode-error warning.

## Roadmap (from 2026-08-07 product scoping conversation)

Not yet built — captured here so the sizing/sequencing reasoning survives
past the conversation it came from, per the "durable record" convention
above. Roughly grouped by how self-contained each piece is, not strict
priority order.

**Architectural call made in that conversation, applies to everything
below that touches permanent content:** grow a **separate app** ("the
Archive") for anything that's about content/audience rather than
resolving — permanent public meeting pages, search, accounts + token
billing, email alerts, the transcription crawler — rather than growing
this app into that. Reasoning: round 1 (`rtr-transcripts`) coupled
resolving, accounts, auth, and content into one codebase, and that
coupling is exactly what made it slow to work on. This app (the
"Deeplink" resolver) stays single-purpose: no accounts, no public
content pages, ever. The two apps would talk over a small API — likely
the resolver checking/publishing to the Archive instead of (or in
addition to) its own local `meeting_resolutions` cache once the Archive
exists; `get_cached_resolution`/`log_resolution` in `app/db/crud.py` are
deliberately the seam where that swap would happen, so this isn't
blocked by anything already built. Whether the resolver pushes to the
Archive synchronously or the Archive pulls/crawls independently is an
open question, deliberately left for when the Archive is actually being
scoped.

- **[Done 2026-08-07, live] Newsletter signup.** A footer signup form
  (sitewide, in `base.html`) POSTs to `/api/newsletter/signup`, which
  adds the email to a Resend audience. Chose Resend over Mailchimp
  specifically because it can also handle the future "email alerts for
  saved searches" item below (triggered per-user sends) on the same
  account/API, not just newsletter broadcasts — Mailchimp would need a
  separate paid add-on (Mandrill) for that later. Degrades gracefully
  like the DB layer: with no `RESEND_API_KEY`/`RESEND_AUDIENCE_ID` set,
  signups return a clean "not available right now" message instead of
  erroring. Live on `redtaperecordings.com` (DNS via Namecheap).
  **Real gotcha hit and fixed**: the first `RESEND_API_KEY` created was
  scoped to "Sending access" only, which Resend rejects for the
  audiences/contacts endpoint with `401 restricted_api_key` — Resend API
  keys need **Full access** to manage audience contacts, not just send
  mail, and permission level can't be changed on an existing key
  (create a new one, revoke the old). Confirmed via Render's live logs
  (the `logger.error("Resend signup failed (%s): %s", ...)` line in
  `main.py` was what surfaced the exact cause) and a real end-to-end
  signup afterward.
- **[Done 2026-08-07, live] Basic analytics.** Google Analytics 4, per
  the user's choice. `base.html` conditionally loads `gtag.js` from
  `GA_MEASUREMENT_ID` and always defines a global
  `window.trackEvent(name, params)` — a real call to `gtag('event', ...)`
  when GA is configured, a no-op otherwise — so call sites never need to
  branch on whether GA is set up. Three events wired so far:
  `submit_meeting_url` (homepage form), `copy_link_to_time` (the core
  viral action — someone creating a shareable deep link),
  `newsletter_signup`. Deliberately did **not** send which meeting URLs
  get pasted in as a GA event parameter — that's redundant with the
  per-adapter reporting log above (which already tracks this
  server-side, with outcome detail GA has no equivalent for) and there's
  no reason to also hand government meeting URLs to Google.
- **Permanent meeting pages** (the Archive's core feature) — the
  biggest single item below. Needs its own content model: versioned
  transcripts per meeting (to support language variants, edits, a
  future manual/higher-quality re-transcription, speaker diarization
  later), slugs, SEO/crawlability (server-rendered, sitemap). Video is
  never self-hosted, only embedded — matches this app's existing
  principle. Not sized in detail yet; do that when it's actually next.
- **Transcription crawler** (fetch audio/video for meetings with no
  captions, run our own transcription, store the result permanently) —
  separate from the Archive architecturally but only useful once the
  Archive exists to store results in. Some prior scar tissue to reuse:
  a "bad Whisper model" bug was already found and fixed once in round 1.
- **Search over permanent pages** — genuinely easy once the Archive
  exists; Postgres full-text search is enough at this scale, no need
  for Algolia/Elasticsearch.
- **Accounts + token billing** — the one piece of round 1's complexity
  being deliberately reintroduced, and only on the Archive, not here.
  Needed for: paid/subscribed features (already alluded to in several
  adapter warning messages — "contact ryan@how-to-adu.com" for manual
  transcription), and as a prerequisite for email alerts below. Not
  sized in detail yet.
- **Email alerts for saved searches** — depends on both accounts *and*
  search existing first, so it's downstream of both above.
- **On-demand / scheduled crawl requests** (let someone ask us to crawl
  a specific meeting or series, or schedule a recurring one) — depends
  on the Archive existing; shared here now mainly because it may affect
  the Archive's architecture even though it's not being built yet.
- **Video highlight clips ("Highlights") + algorithmic feed** — distant
  future per the user's own framing. Flagged tension worth resolving
  before scoping further: this app's "never host video, only embed"
  principle directly conflicts with hosting/serving clip segments,
  which a highlights feed would require.

The "Reporting & caching" section above is the one piece of this roadmap
already built — per-adapter success/failure reporting was pulled forward
ahead of everything else here because it was the smallest real step and
directly informs adapter-fix priority for the existing platforms.
