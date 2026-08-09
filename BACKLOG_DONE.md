# Backlog — done

Completed items moved out of [BACKLOG.md](BACKLOG.md) to keep the live
document short. Kept verbatim (not summarized) because the investigation
detail — what was checked, on which real cities, what turned out to be a
non-issue vs. a real bug — is itself useful project memory, not just a
changelog of task titles.

## Bugs

- **[Done 2026-08-08] `media_scan.scan_media_urls`'s "sources" JSON-blob
  branch was dead code — removed rather than fixed.** The regex
  `r'({[^}]*"sources"\s*:\s*\[[^}]*\][^}]*})'` used `[^}]*` to span from
  the array's `[` to its closing `]`, but that character class excludes
  `}` entirely — so it could never match past the closing `}` of an
  object *inside* the array, meaning it never matched any real
  JWPlayer-style config blob. Confirmed dead via a unit test
  (`tests/test_media_scan.py`) before touching it. Deleted the branch and
  its now-unused `json` import rather than writing a fixed JSON-aware
  version, since a "fixed" version would still be unverified against any
  real page — exactly the kind of unverified parsing path this project's
  own convention avoids shipping (see the "never build from assumption"
  rule above). Both adapters that call `scan_media_urls` (Granicus,
  Swagit) already get every real media URL they've ever needed from the
  plain regex patterns tried first in the same function. Verified: full
  `pytest` suite green after the change (including an updated version of
  the pinning test, renamed to `..._was_removed_as_dead_code` and
  re-documented rather than left describing code that no longer exists),
  and live against a real Simi Valley Granicus meeting — video URL and
  394 real transcript segments still resolve correctly with the branch
  gone.
- **[Done 2026-08-07] Caption language track picker.** Follow-up from the
  caption language detection fix (below) — `GranicusAssetFinder` already
  detected the real language of every fetched caption track internally
  (the `candidates` list in `app/platforms/granicus.py`) but only ever
  exposed the one it chose, silently discarding any others. Added a new
  `AlternateTranscript {language, segments}` model and
  `ResolvedMeeting.alternate_transcripts` field (`app/platforms/models.py`);
  Granicus's `resolve()` now populates it from every fetched, non-blank
  candidate track other than the chosen one, full segments included (not
  just a language label), so the frontend can switch client-side with no
  second `/api/resolve` round-trip. Frontend: a "Language: [ ]" `<select>`
  next to the Transcript heading (`#transcriptLanguagePicker` in
  `meeting.html`), hidden whenever there's nothing to switch between (the
  common single-track case). `player.js`'s `setupTranscriptLanguagePicker()`
  builds its options from the chosen track + alternates, using
  `Intl.DisplayNames` for a real language name (e.g. "Spanish") rather than
  showing a raw ISO code, and falling back to the code itself if the
  browser can't resolve it; switching reassigns the module-level `segments`
  array and calls the existing `renderTranscript()`, so search/highlighting/
  auto-scroll all keep working against whichever track is active without
  separate wiring.

  No real multi-caption-track meeting has been found live yet (every
  sample checked so far, like Simi Valley clip 2840, turned out to have
  exactly one track, just sometimes mislabeled) — confirmed live against
  Simi Valley that the field correctly stays `[]` and the picker stays
  hidden in that case, no regression. The actual multi-track code path
  was verified with a mocked `resolve()` (two synthetic VTT tracks, one
  English one Spanish): correctly chose English (matches
  `TARGET_LANGUAGE`) and carried the Spanish track through
  `alternate_transcripts` with its full 20 segments intact. The frontend
  switcher was verified in a real browser (`mcp__Claude_Browser__*`) by
  injecting synthetic two-track data into a live-rendered meeting page and
  driving the actual shipped `setupTranscriptLanguagePicker()`/
  `renderTranscript()` functions: the picker showed "English"/"Spanish"
  options, selecting "Spanish" correctly swapped the rendered transcript
  text and the global `segments` state, and the heading-row layout
  (`.transcript-heading-row` flex, `justify-content: space-between`) placed
  the picker at the row's right edge with no overlap against the "Transcript"
  heading. Confirmed the new field round-trips harmlessly through
  `archive_client.push()` — the Archive's `IngestRequest` schema
  (`archive/main.py`) has no `alternate_transcripts` field and Pydantic
  ignores unrecognized fields by default, so it's silently dropped there;
  deliberately resolver-only, since the Archive already has its own
  separate mechanism for multiple languages (`TranscriptVersion` rows,
  its own version picker).
- **[Done 2026-08-07] Real bug: a URL already cached locally never got
  backfilled into the Archive.** `/api/resolve`'s local-cache-hit branch
  (`app/main.py`) returned the cached payload directly without ever
  reaching the "push to the Archive" step, which only ran on a fresh live
  resolve — so any URL cached before the Archive integration existed, or
  while `ARCHIVE_BASE_URL` was unset/misconfigured, could never become a
  permanent page on its own, since every future resolve of that exact URL
  just kept serving the local cache. Confirmed live via `psql` on Simi
  Valley's `meeting_resolutions` row (`hit_count: 3`, predating the Archive
  integration). Fixed by making the local-cache-hit branch opportunistic:
  if the cached payload has real content (`segments` or `agenda_items`)
  and the Archive lookup at the top of `resolve()` already came back empty
  for this URL, fire the same `archive_client.push()` background task the
  fresh-resolve path uses. Verified live end-to-end with two local uvicorn
  processes (resolver + Archive, SQLite fallback): resolved a real Simi
  Valley meeting (clip 2840, 394 segments + 17 agenda items) with
  `ARCHIVE_BASE_URL` unset to reproduce a pre-Archive cached row, then
  restarted the resolver with the Archive wired up and re-resolved the
  same URL — `/internal/lookup` 404'd (Archive genuinely didn't have it
  yet), the local cache served the response, and the new opportunistic
  push fired and succeeded (`/internal/ingest` 200), after which
  `/internal/lookup` for that URL correctly returned a real `/m/{slug}`.
  Didn't build the one-time backfill pass (the other option raised in the
  original item) — the code fix closes the gap going forward for every
  URL as it's next resolved, which covers the real-world case without a
  separate one-off script.
- **[Done 2026-08-06 for Legistar/CivicPlus; investigated for PrimeGov —
  not applicable] Unsupported-platform failure is too blunt.** Fixed for
  Legistar and CivicPlus specifically: both delegate to the embedded
  Granicus link when present, and a calendar/listing page returns a
  pick-list of real meetings rather than a bare error (see Platform
  coverage section below). The remaining "no adapter at all" case is only
  PrimeGov today (detected but unregistered) — investigated whether the
  same "find an embedded supported-platform link, then delegate" pattern
  would help there: checked 3 real PrimeGov cities (Los Angeles, San Jose,
  Petaluma) and all three embed video via a **YouTube** iframe player,
  not a link to any currently-supported vendor platform. Unlike
  Legistar/CivicPlus (which really are just wrappers around Granicus),
  PrimeGov is a genuine distinct video host — the "find a supported
  link" fallback had nothing to find here, so a real PrimeGov/YouTube
  adapter was needed. **[Done 2026-08-07] Built — see the PrimeGov/
  YouTube entry in Platform coverage below.** (The "video ID not
  statically present" claim above turned out to be based on checking a
  PrimeGov URL shape without a video at all -- the shape a real shared
  link uses does have it, directly in the page HTML.)
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
  them too. Alexandria VA remains unfixed and is tracked as a live item
  in [BACKLOG.md](BACKLOG.md).

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
  to do better, and decided not worth a DC-specific hardcode for one city
  (wontfix, not tracked as a live item).

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
  doesn't match. Follow-up (UI dropdown to let the user pick between
  multiple language tracks when more than one exists) built 2026-08-07 —
  see the "Caption language track picker" entry above.

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
- **[Done 2026-08-07] Live playhead timestamp where the transcript
  would be.** Deep-linking to any moment already worked with zero
  transcript (`t=` has always been the sole seek-position authority),
  but nothing signaled that — a meeting with no transcript/agenda
  previously just showed a warning and a dead end. `#transcriptMissing`
  now shows a large live-updating timestamp (`updateNoTranscriptTime()`
  in `player.js`) plus a "Copy link to this moment" button, sharing one
  click handler with the existing toolbar button. Surfaced and fixed a
  real gap: the timestamp is now also updated immediately after
  `applyDeepLink()`, not just on `timeupdate` — for YouTube specifically,
  `timeupdate` is only polled while actually playing, so a paused/
  autoplay-blocked load would otherwise show a stale "0:00" instead of
  the real deep-linked position. Verified live against Paradise Valley
  AZ's confirmed blank-caption meeting.

- **[Done 2026-08-07] Newsletter signup box redesign.** Resolved the
  open question in favor of a new-but-consistent treatment: `.newsletter-btn`
  is a sibling to `cassette-btn` (same bold-mono/chunky-border family)
  but deliberately not `cassette-btn` itself — "sign up" isn't a "rewind
  to a moment" action, so it's solid navy instead of the reel-icon
  gimmick, keeping `cassette-btn` reserved for the two buttons its own
  scoping comment already calls out. Input now matches the homepage's
  fused-pill sizing (48px height, matching border-radius split) instead
  of plain unstyled Bootstrap. Added a small dymo-label-style kicker tag
  ("STAY IN THE LOOP") on the dedicated `/subscribe` page — reuses the
  wordmark's signature visual element as a secondary section tag.
  Verified visually and confirmed the submit flow still works unchanged.
- **[Done 2026-08-07] "Get Updates" link in the site nav pointing at
  the email signup.** Originally shipped as a same-page
  `#newsletterForm` anchor to a footer form; replaced same-day (see the
  dedicated `/subscribe` page item below) after the user pointed out
  three real problems with the anchor approach — no visible cue if
  you're already scrolled to the bottom, breaks Ctrl+click/open-in-new-
  tab, and a shared link lands people wherever the anchor happens to be
  rather than a clean destination. The nav link now points at
  `/subscribe` directly.
- **[Done 2026-08-07] Dedicated `/subscribe` page, replacing the
  footer-anchor approach above.** New `GET /subscribe` route +
  `subscribe.html` holds the actual signup form now (autofocused input,
  no anchor-jump needed). Nav's "Get Updates" and the About page's
  "Subscribe to get updates" both link straight to `/subscribe`. The
  sitewide footer keeps a plain text link to it (`request.url.path`
  check in `base.html` suppresses that link specifically on
  `/subscribe` itself, so the page doesn't show the same prompt twice).
  `newsletter.js`'s anchor-focus workaround was removed since it's no
  longer needed. Verified: page renders with the email input
  autofocused, footer link correctly present/absent on the right pages,
  and the full submit flow still works end-to-end (confirmed the
  graceful "not available" message renders when Resend isn't
  configured, via a direct programmatic submit after a manual click
  raced the screenshot).

- **[Done 2026-08-07] Spinning cassette-reel animation on the "please
  wait" fetch message.** `player.js`'s loading-state line now renders
  two `.cassette-reel` SVGs (reusing the existing icon markup) with a
  new `.spinning` modifier class — a slower 1.6s spin than the 0.8s
  hover flourish elsewhere, since this can run for up to ~20s and a
  quick spin reads frantic sustained that long. Verified the animation
  is actually wired (not just present in markup) via computed style —
  `animationName: "reel-spin", animationDuration: "1.6s"` — after
  confirming a byte-fresh fetch of `style.css` contains the rule.

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
- **[Done 2026-08-07] Granicus agenda-item chapter-marker fallback,
  same role as CivicClerk's `eventBookmarks`/Swagit's `.playerControl`.**
  When there's no usable transcript, `GranicusAssetFinder` now tries
  `AgendaViewer.php?clip_id={id}&embedded=1` — Granicus's own agenda-index
  feature, when a customer has it turned on, renders each item as
  `<a name="agenda{id}" onclick="top.SetPlayerPosition('0:{seconds}',null)">
  {title}</a>`. Confirmed live: works on Simi Valley (17 items) and San
  Francisco (82 items). Does not help either of the two jurisdictions
  confirmed genuinely blank-caption in the 2026-08-06 zero-caption
  investigation above: Berkeley redirects `AgendaViewer.php` to its own
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
- **[Done 2026-08-07] Dedicated "Agenda" section, structurally separate
  from "Transcript," always loaded regardless of transcript
  availability.** Agenda/chapter-marker data (Granicus's
  `AgendaViewer.php` items, CivicClerk's `eventBookmarks`, Swagit's
  `.playerControl` markers) previously got folded directly into
  `ResolvedMeeting.segments` as if it were transcript content, and only
  when there was no real transcript at all — a reasonable v1 shortcut
  that didn't hold once agenda was meant to be its own thing. Added a
  new `agenda_items: List[TranscriptSegment]` field on `ResolvedMeeting`
  (`app/platforms/models.py`), kept structurally separate from
  `segments` so agenda/chapter data is never mistaken for real
  transcript content. Granicus, CivicClerk, and Swagit adapters now
  populate it unconditionally (agenda fetch decoupled from `if not
  segments:`), so a meeting with both a real transcript and a real
  agenda shows both simultaneously — verified live on Simi Valley
  Granicus (394 real transcript segments + 17 agenda items
  simultaneously). New `#agendaSection` in `meeting.html`, positioned
  between the video and transcript sections; `player.js`'s
  `renderAgenda()` reuses the transcript's `.segment-timestamp`/
  `.segment-link-btn`/`.segment-text` markup for click-to-seek and
  copy-link, but deliberately doesn't participate in
  `findActiveSegment()`'s "currently playing" highlighting or the
  `line=` deep-link param — agenda items are seek-only via `t=`,
  simpler than transcript's fine-grained tracking. `classify_outcome()`
  in `app/db/outcomes.py` now checks `resolved_payload.agenda_items`
  directly instead of inferring the `agenda_fallback` bucket from a
  warning-text marker (`_AGENDA_FALLBACK_MARKER` removed). Verified
  live across three real scenarios: Simi Valley Granicus (transcript +
  agenda both shown), Yountville Swagit (agenda only, 7 items,
  transcript-missing block shows a plain "No transcript found"
  message), Paradise Valley AZ Granicus (no agenda section — no
  timestamped agenda data available — but the existing blank-caption
  warning and clickable agenda-PDF fallback link still render
  correctly in the transcript-missing block). YouTube/PrimeGov adapter
  untouched this round — confirmed it still resolves cleanly with an
  empty `agenda_items: []` (no crash, no regression).
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
- **[Done 2026-08-07] PrimeGov + standalone YouTube adapters.** Two new
  platforms, `app/platforms/primegov.py` and `app/platforms/youtube.py`.
  Confirmed live end-to-end (LA City Council, a real ~100-minute meeting)
  through the full pipeline: resolve, iframe playback, transcript render,
  deep-link seek on page load, click-to-seek from a transcript line, and
  "Copy link to current time" — all working.

  **PrimeGov → YouTube delegation**: confirmed live (`lacity.primegov.com`)
  that a real shared-link meeting page (`Portal/Meeting?
  compiledMeetingDocumentFileId=...`) has `var videoUrl = "{11-char-
  YouTube-id}";` directly in the server-rendered HTML, right next to a
  `youtube.com/iframe_api` script tag — simple regex extraction, no JS
  execution needed. (An agenda-only URL shape, `?meetingTemplateId=...`,
  is what got checked in the original "not statically present"
  investigation above — that page genuinely has no matching recording.)
  Unlike Legistar/CivicPlus's delegation, this preserves the *original*
  PrimeGov URL as `source_url` (calls `YouTubeAssetFinder.
  resolve_video_id()` directly rather than going through
  `resolve_via_platform()`), so "View original source" points back to
  the actual meeting page, not a raw youtube.com URL.

  **YouTube playback**: no direct video file URL exists for YouTube,
  unlike every other platform here — needs an embedded iframe + the
  YouTube IFrame Player API, a structurally different control surface
  (`seekTo()` instead of `currentTime=`, no native `timeupdate` event,
  async player creation) than the native `<video>`/hls.js pathway.
  `player.js` now wraps whichever one is active behind a shared
  `{currentTime get/set, play, pause, addEventListener}` adapter shape
  (`createNativeAdapter` / `createYouTubeAdapter`) set once as
  `activeVideoAdapter`, so transcript click-to-seek, "Copy link to
  current time", "Go to time", and `applyDeepLink()` all work unchanged
  against either one — verified all of the above live against the real
  LA meeting, including deep-link seeking on a fresh page load (the
  trickier async case, gated on the player's `onReady`).

  **YouTube caption download is blocked for plain HTTP requests** —
  real finding, not assumption: every caption URL YouTube hands out
  (via the watch page's embedded `ytInitialPlayerResponse` JSON, itself
  fetched fine with plain HTTP) returned `200 OK` with **0 bytes**
  across 5 different request shapes tried live: aiohttp/curl, with a
  real browser User-Agent, cross-origin `fetch()`, same-origin `fetch()`
  from youtube.com itself, and a freshly-signed same-session URL grabbed
  via JS on the actual watch page. **yt-dlp works reliably** where all of
  those failed (confirmed against the real LA meeting: 570KB, ~2000
  real caption segments) — it evidently has its own way of working
  around whatever's blocking bare HTTP clients, so caption fetching goes
  through yt-dlp's `urlopen()` (called via `asyncio.to_thread` since
  yt-dlp is synchronous), not our own aiohttp session. **Ongoing
  maintenance risk**: yt-dlp is under active, frequent maintenance
  specifically because YouTube keeps changing things to block scraping
  — left unpinned (latest) in `requirements.txt` on purpose; pinning an
  old version would risk this breaking sooner. If YouTube/PrimeGov
  resolves start failing, check for a yt-dlp update first.

  **YouTube's caption VTT uses a "roll-up" cue style**, not one cue per
  line (confirmed on both an auto-generated and, per a different real
  track on the same video, a manual/CC-sourced track) — each cue repeats
  the previous settled line and grows the *next* line word-by-word, so
  treating each cue as its own segment produces massive duplicate text.
  New `dedupe_rollup_cues()` in `vtt_parser.py` collapses this into real
  segments — verified against the real 4035-cue/570KB sample: 2004 clean
  segments, no visible duplication, fully coherent reconstructed text.

  **Manual vs. auto-generated caption track selection**: prefers a
  manual (non-ASR) track when available, but only when its coverage is
  comparable to the auto-generated one — real finding on the LA sample:
  the "manual" CC track only starts at 18:49 into the video (likely a
  government CART feed that skips pre-meeting dead air), while the
  auto-generated track covers the full video from :01. A transcript
  with a 19-minute unlinkable gap at the start is worse for a deep-link
  tool than a slightly lower-quality but complete one, so manual is only
  used when it starts within 60s of the auto-generated track's start
  (`YouTubeAssetFinder._pick_caption_track()`). Confirmed live: correctly
  fell back to the (complete, auto-generated) track for this video and
  warned the user it's auto-generated, not human-transcribed.

  Follow-ups not yet investigated (non-English caption handling, and
  whether the manual-track coverage gap is typical or one-off) are
  tracked as live items in [BACKLOG.md](BACKLOG.md).

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

## Roadmap items completed

- **[Done 2026-08-07, live] Newsletter signup.** A footer signup form
  (sitewide, in `base.html`) POSTs to `/api/newsletter/signup`, which
  adds the email to a Resend audience. Chose Resend over Mailchimp
  specifically because it can also handle the future "email alerts for
  saved searches" item (triggered per-user sends) on the same
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
- **[Done 2026-08-07] Permanent meeting pages** (the Archive's core
  feature). Built as a genuinely separate app, `archive/` — own FastAPI
  service, own database (same Render Postgres server as the resolver,
  but a separate logical database), own deploy — reachable at
  `redtaperecordings.com/m/{slug}` via a reverse-proxy in the resolver's
  `app/main.py` (`/m/*` and `/archive-static/*`), so the custom domain
  stays consolidated for SEO/sharing even though it's two services.
  Content model: `MeetingPage` (one per real-world meeting, identity via
  `(platform, external_id)` or normalized URL) + `TranscriptVersion`
  (many per page — language/source variants, deduped by a content hash
  of the segment text) + `MeetingPageUrlAlias` (every input URL that's
  ever pushed, so a lookup keyed on a wrapper-platform URL like Legistar
  still short-circuits even though its real identity lives on the
  platform it delegates to). Pages are fully server-rendered (real
  transcript/agenda content on first byte, not client-fetched JSON) for
  actual crawlability. Handoff: the resolver checks the Archive *before*
  resolving (`archive_client.lookup()`) and redirects to the permanent
  page if one exists, preserving `t=`/`line=`; after a live resolve
  with real content (transcript or agenda — never for blank/failed
  resolves), it pushes via `archive_client.push()` on a `BackgroundTasks`
  callback (not a bare `asyncio.create_task`, which risked the task
  being garbage-collected mid-flight). Both directions degrade silently
  through the same `safe()` pattern as the existing DB calls — a down
  Archive never breaks `/api/resolve`, and the resolver's `/m/*` proxy
  returns a clean 503 rather than hanging.

  Verified live end-to-end locally (two uvicorn processes): a real
  content-bearing resolve (Simi Valley Granicus, 394 segments + 17
  agenda items) correctly created a `MeetingPage`; re-pasting the same
  URL returned `{"redirect_url": "/m/{slug}"}` in ~20ms instead of
  re-scraping; the alias table correctly short-circuited a
  wrapper-platform-shaped URL pointed at the same `external_id`; deep
  links (`t=630&line=seg-4`) survived the redirect and correctly seeked
  + highlighted on the permanent page; a second transcript version
  (different language) correctly appeared in the version picker
  (`?version={id}`, full page reload) without disturbing the first; an
  identical re-push correctly did not create a duplicate version
  (content-hash dedup); a blank/no-content resolve (Paradise Valley AZ)
  correctly never reached the Archive at all; and killing the Archive
  process confirmed `/api/resolve` kept resolving live with no 500 while
  `/m/{slug}` degraded to a clean 503.

  Operational notes for when this goes live: Render's free web services
  spin down after 15 min idle (~30-60s cold start) — fine during
  testing, but the Archive service should move to a paid plan before
  `/m/*` links are actually shared or submitted for indexing, since a
  Googlebot fetch regularly eating that latency is a real crawl-health
  risk, not just a stray-visitor annoyance. Free Render web services can
  send private-network requests but not receive them, so the proxy
  targets the Archive's public `.onrender.com` URL for now — switching
  to Render's internal hostname once the Archive is paid is a one-line
  env var change. The second Postgres database
  (`CREATE DATABASE rtr_archive;` on the existing instance) and the
  second Render web service both still need to be provisioned by the
  user themselves before this is live in production.

  Explicitly not built in this pass (still gated on the Archive
  existing): the transcription crawler, search, accounts/billing, email
  alerts, on-demand crawl requests, video highlights — all tracked as
  live roadmap items in [BACKLOG.md](BACKLOG.md). Also not resolved:
  whether a genuine re-scrape of the same `(language, source)` with
  different content should replace that version in place or add a new
  one and flip which is default — flagged for a follow-up decision, not
  blocking.
- **[Done 2026-08-08] Meetings index page, sitemap.xml/robots.txt, and
  keyword search + filters — built together since search/filters narrow
  the same query the index page uses, not a separate feature.**
  `crud.list_pages()` (paginated, 20/page, `LIMIT`/`OFFSET`) backs a new
  `GET /meetings` route + `meeting_list.html`, reachable at
  `redtaperecordings.com/meetings` via a matching proxy route in
  `app/main.py`. Search box + jurisdiction/date-range/language filters
  are plain GET params on the same route (shareable/bookmarkable URLs,
  no JS required). v1 keyword search covers title + jurisdiction only,
  via a portable `.ilike()` (works on Postgres and the local SQLite
  fallback) — deliberately not full transcript-body search, since
  `segments` are JSON per `TranscriptVersion`, not a plain searchable
  column; that's flagged as a real follow-up in `BACKLOG.md`, not
  silently half-built. `GET /sitemap.xml` (`crud.list_all_page_slugs()`,
  unpaginated — fine at the current hundreds/thousands scale) plus a new
  `GET /robots.txt` on the resolver (`Disallow: /meeting` — the
  ephemeral resolver page — plus a `Sitemap:` line) give the Archive an
  actual crawl path for the first time; previously a `/m/{slug}` page
  was only reachable if you already had its exact URL. Verified live
  end-to-end (both locally and against `redtaperecordings.com`):
  pagination math, keyword search, jurisdiction/language filters
  (including a genuinely-correct edge case — `language=en` correctly
  excludes an agenda-only page with zero transcript versions, not a
  bug), combined filters, the empty-results state, and a real
  `sitemap.xml`/`robots.txt` render with absolute URLs in production.
- **[Done 2026-08-08] Bug: permanent Archive pages hardcoded `<html
  lang="en">` regardless of the actual transcript's language.**
  Confirmed live on the Simi Valley page, whose default transcript
  version is Spanish — the page declared `lang="en"` anyway. Fixed:
  `archive/main.py`'s `meeting_page()` route now passes the active
  `TranscriptVersion.language` into the template as `page_lang`
  (falling back to `"en"` for agenda-only pages with no transcript at
  all); `archive/templates/base.html` reads it via
  `{{ page_lang|default('en') }}`. Verified locally: the same Simi
  Valley page now renders `<html lang="es">`, and an agenda-only page
  (Yountville) correctly falls back to `<html lang="en">`. **Could not
  fully re-verify the non-English branch in production** against this
  specific URL — a real, separate gap surfaced while trying: Simi
  Valley had already been served 3 times from the resolver's own local
  `meeting_resolutions` cache (`hit_count: 3`, cached well before the
  Archive integration's env vars were fixed), so `/api/resolve` keeps
  short-circuiting on that local cache hit and never reaches the live
  resolve → Archive push path for this URL — confirmed directly via
  `psql` against `rtr_deeplink_db`. Production is running the identical
  code as the locally-verified build, so the fix itself isn't in doubt,
  but this exposed a real backfill gap — see the new "Bugs" entry in
  [BACKLOG.md](BACKLOG.md).
- **[Done 2026-08-08] Opportunistic re-check on a permanent-page hit.**
  Cadence decision made and built: a hit on an existing Archive page
  triggers a background re-resolve + re-push only if the page hasn't been
  touched in `ARCHIVE_RECHECK_AFTER` (30 days, `app/main.py` — not derived
  from measured data, a reasonable middle ground between "government
  caption pipelines can take weeks to catch up" and "don't hammer the
  source site on every visit to a popular meeting"). `GET /internal/lookup`
  (`archive/main.py`) now returns the page's `updated_at`; the resolver's
  `archived`-hit branch in `resolve()` parses it (`_parse_updated_at()`,
  treating a naive timestamp as UTC — SQLite doesn't enforce tz-awareness
  the way Postgres does, so which shape comes back depends on which DB the
  Archive happens to be running against) and fires
  `_recheck_archived_page()` via `BackgroundTasks` when stale, never
  blocking the redirect response. Reuses the same finder + `archive_client.
  push()` path as a fresh resolve.

  **Real bug found and fixed while verifying this**: `MeetingPage.
  updated_at`'s `onupdate=func.now()` (`archive/db/models.py`) only fires
  when SQLAlchemy actually detects a changed attribute — but
  `ingest_resolution`'s existing-page branch (`archive/db/crud.py`)
  reassigns `page.title`/`.date`/etc. to values that are usually identical
  to what's already stored, which doesn't dirty the row. Confirmed live
  with an isolated script: backdating `updated_at` and re-ingesting the
  exact same payload left it unchanged, meaning a re-check that found no
  new content would never stop being "stale" and would re-fire on *every*
  subsequent hit — precisely the hammering problem this feature exists to
  prevent. Fixed by having `ingest_resolution` explicitly set
  `page.updated_at = datetime.now(timezone.utc)` on every existing-page
  ingest, regardless of whether any field actually changed, so it reliably
  means "last time this page was checked."

  Verified live end-to-end with two local uvicorn processes (resolver +
  Archive, isolated ports/SQLite files to avoid colliding with other local
  activity against the conventional 8010/8020 dev ports): pushed a real
  Simi Valley meeting, backdated its `updated_at` to simulate a stale page,
  then resolved the same URL twice in a row. First hit: fast redirect
  response plus exactly one background `POST /internal/ingest` (the
  re-check). Second hit, immediately after: redirect only, no re-check —
  confirming the now-fresh `updated_at` correctly suppressed a repeat
  trigger. Ran the project's existing `pytest` suite (`tests/`, added
  concurrently by another session working this same backlog) before and
  after — all passing, no regressions from either change.

## Testing infrastructure

- **[Done 2026-08-07] Fixture-based pytest suite, from Claude's own
  suggested backlog (`CLAUDE_BACKLOG.md`).** 47 tests across
  `tests/test_vtt_parser.py`, `test_media_scan.py`, `test_base.py`, and
  end-to-end adapter tests for Granicus/Legistar/CivicPlus/CivicClerk.
  Built on branch `claude-backlog/round-1`.

  Real fixtures, not synthetic, wherever a live fetch was possible during
  this session (2026-08-07): Granicus — Napa City clip 3450 (genuinely
  blank captions.vtt, the real 8-byte placeholder) and Simi Valley clip
  2840 (the exact real Spanish-caption meeting `BACKLOG_DONE.md` already
  documents above); Legistar — a real `maricopa.legistar.com/Calendar.aspx`
  page (confirms the calendar pick-list against real markup); CivicClerk —
  real `clovisca.api.civicclerk.com` API responses for two real events (20:
  direct mp4 + 31 real agenda bookmarks; 17: `externalVideoUrl`/YouTube
  fallback, zero bookmarks). CivicPlus is the one exception: the real site
  this adapter was originally verified against
  (`ca-westlakevillage.civicplus.com`) has since been restructured (302s to
  a JS-redirect stub, no `AgendaCenter` markup) and the plain
  `civicplus.com` subdomain no longer resolves at all — that fixture is
  hand-built to match the exact real markup shape `civicplus.py`'s own
  docstring documents as confirmed live on 2026-08-06, not a guess (see
  `tests/fixtures/civicplus/README.md`).

  **Real tooling finding**: `aioresponses` (latest release, 0.7.9) doesn't
  support the aiohttp version this project's unpinned `aiohttp>=3.9`
  requirement resolves to today (3.14.3) — its `_build_response` omits the
  now-required `stream_writer` kwarg to `ClientResponse.__init__`, a hard
  `TypeError` on every mocked request. Rather than pin the app's real
  dependency down just to satisfy a test-only library, wrote a small
  self-contained `tests/aiohttp_mock.py` that monkeypatches
  `aiohttp.ClientSession.get` directly — a `FakeResponse`
  (status/text/read/json/raise_for_status) plus a `mock_session({url:
  FakeResponse})` context manager, exact-URL-keyed. Same "actively
  maintained dependency chasing a moving target" risk category as yt-dlp
  (see the working-conventions note in `CLAUDE.md`) — worth rechecking
  whether `aioresponses` has caught up next time this suite needs
  extending.

  **Two real bugs found while building this, unrelated to the feature
  being tested**:
  1. `media_scan.scan_media_urls`'s `"sources"` JSON-blob regex branch was
     dead code — confirmed via a unit test that its `[^}]*\]` could never
     span the closing `}` of an object inside the array, so no input shape
     that would produce a `source["src"]`-consumable dict could ever
     match. Not a live bug (both callers, Granicus and Swagit, already get
     real URLs from the plain regex patterns tried first) — flagged as a
     live `BACKLOG.md` item first, then removed outright (rather than
     fixed) the same day, since a "working" JSON-aware replacement would
     still be unverified against any real page. The regression test was
     renamed to `test_scan_media_urls_sources_json_branch_was_removed_as_
     dead_code` and still asserts the same input yields no URLs, now
     because the branch is gone rather than because it never matched.
  2. A test-writing mistake that would have hidden a **real fixture bug**
     if not caught: an early draft of the CivicClerk "externalVideoUrl
     fallback" test reused event 20's real `Events/20` JSON with only the
     `id` field patched to 17 — but event 20's `mediaStreamPath`/
     `mediaSourcePathMp4` fields are themselves populated with event 20's
     real direct mp4 URL, so the test would have silently asserted against
     the wrong video source (the shadowing field, not the fallback path it
     claimed to test) had the assertion not been checked against the real
     API response first. Fixed by fetching and saving event 17's own real
     `Events`/`EventsMedia` JSON instead of hand-editing a different
     event's — a reminder that even a "real fixture" test can lie if it's
     assembled from mismatched real pieces.

  Not yet covered: Swagit, eScribe, CA Legislature, PrimeGov/YouTube
  adapters (no test files yet — README's "Running tests" section flags
  this as the natural next extension), and the `app/db/` and `archive/`
  layers (no fixtures or tests for either). `requirements-dev.txt` and
  `pytest.ini` (`asyncio_mode = auto`) added; see README's new "Running
  tests" section for how to run it.

- **[Done 2026-08-08] Six more items from `CLAUDE_BACKLOG.md`, all on
  branch `claude-backlog/round-1`.** Verified live against real running
  instances of both services (not just unit tests) for every item below.

  **PWA manifest.** `app/static/manifest.json` + a new `app/static/icon.svg`
  (a square 192x192 SVG in the site's existing dymo-label red/navy, "RTR"
  monogram — SVG-only, no PNG fallback generated, so pre-maskable-icon
  Android/iOS install flows may not pick it up; a real gap, not silently
  claimed to be complete). Linked from both `app/templates/base.html` and
  `archive/templates/base.html` (`/static/manifest.json` is reachable from
  Archive-served pages too since `/static/` is mounted on the resolver,
  same-origin regardless of which service rendered the HTML).

  **schema.org `VideoObject` JSON-LD** on `archive/templates/meeting_page.html`,
  gated on `page.video_url` existing. `contentUrl` for a direct file
  (mp4/m3u8), `embedUrl` for YouTube (schema.org distinguishes the two).
  `duration` computed for real from the active transcript's last segment
  end time when one exists. No `thumbnailUrl` (this app doesn't generate
  one — same underlying gap as the missing `og:image`), so this likely
  isn't rich-result-eligible yet, just valid structured data. Verified via
  a standalone Jinja render (both a real-data case and a no-video case
  that correctly emits no `<script>` block at all).

  **Rate limiting on `/api/resolve`** via `slowapi`, keyed by client IP
  (`get_remote_address`), 20/minute. Verified live: 21 rapid requests
  against a real local server returned `200` x20 then `429` with
  `{"error":"Rate limit exceeded: 20 per 1 minute"}`. Real production
  correctness issue caught and fixed in the same pass: Render's edge
  proxy means `request.client.host` would otherwise show Render's own
  proxy IP for every request (making the limiter either a no-op shared
  across all real users, or a way one heavy caller starves everyone else)
  — `render.yaml`'s `startCommand` for the resolver now passes uvicorn
  `--proxy-headers --forwarded-allow-ips='*'` so `X-Forwarded-For` is
  trusted from Render's proxy specifically, a standard pattern for
  PaaS-hosted uvicorn. In-memory limiter storage (slowapi's default) is
  fine for the current single-instance free-tier deploy; would need a
  shared backend (Redis) to stay correct across multiple instances.

  **Transcript export (TXT/SRT).** Two different implementations for two
  different architectures, deliberately not shared code: the Archive's
  permanent pages get real server-side download endpoints
  (`GET /m/{slug}/transcript.{txt,srt}` in `archive/main.py`, formatting
  via new `archive/utils/transcript_export.py`, covered by
  `tests/test_transcript_export.py`) since the data is actually persisted
  there; the ephemeral resolver page (`app/templates/meeting.html`) has no
  server-side persistence at all (that's the whole point of this app per
  README), so its "Text"/"SRT" buttons build the file **client-side** in
  `app/static/player.js` from the `segments` array already in memory, via
  a `Blob` + synthetic download link. Verified live end-to-end: real HTTP
  downloads from the Archive endpoint (content-disposition header and
  body both correct, against a real 394-segment Simi Valley transcript),
  and the resolver's client-side path exercised directly in-browser
  (`downloadTranscript('txt')` triggered with no errors, output format
  confirmed to match the server-side formatter byte-for-byte in
  structure).

  **RSS feed of newly-archived meetings**, `GET /feed.xml` on the Archive
  (optionally `?jurisdiction=`), proxied through the resolver the same
  way `/sitemap.xml` already is. New `crud.list_recent_pages_for_feed()`
  (deliberately separate from the `/meetings` index's `list_pages()` —
  a feed just wants "last N, optionally scoped to one jurisdiction," no
  pagination). Autodiscovery `<link rel="alternate">` plus a visible "RSS
  feed" link added to `/meetings`. **Real bug found and fixed before
  shipping**: `feed.xml.jinja`'s name ends in `.jinja`, not `.xml` —
  `jinja2.select_autoescape()` keys off the literal extension, so
  autoescape was silently OFF for this template (same latent gap already
  present in `sitemap.xml.jinja`, harmless there only because it
  interpolates slug/date, not free-text titles). A real meeting title
  containing a bare `&` or `<` produced invalid, unparseable XML —
  confirmed via `xml.etree.ElementTree.fromstring()` failing on the
  unescaped output. Fixed by explicitly `|e`-escaping every interpolated
  value rather than relying on filename-based autoescape detection;
  `tests/test_feed.py` pins this down as a regression test. Also fixed:
  the feed's own `atom:link[rel=self]` initially built itself from
  `str(request.url)`, which — since this service is only ever reached
  through the resolver's proxy — reflected the Archive's own internal
  host:port, not the public one; switched to the same `PUBLIC_BASE_URL`-based
  `base_url` already used for canonical/OpenGraph URLs elsewhere in this
  app. Verified live through the real proxy chain (resolver → Archive →
  real SQLite-backed `MeetingPage` row), both unfiltered and with a real
  `?jurisdiction=` filter.

  **"Report a problem" feedback control**, on both the resolver's
  ephemeral page and the Archive's permanent pages. New `ProblemReport`
  table (`app/db/models.py`) + `POST /api/report-problem` (rate-limited,
  10/minute) + a token-gated `GET /admin/problem-reports`, mirroring the
  existing `/admin/log` pattern. Deliberately lives only on the resolver's
  DB (not a second table on the Archive) — reports from an Archive page
  reach it via a same-origin `fetch()`, since `/api/*` isn't part of the
  Archive proxy and Archive pages are served from the same public domain
  either way. **Real bug caught before shipping, not just after**: the
  first version wrapped `crud.log_problem_report()` in the existing
  `safe()` helper and checked `if result is None` to detect a storage
  failure — but `log_problem_report` itself returned `None` on *success*
  too (a bare `-> None` function), making success and failure
  indistinguishable and the error path effectively unreachable. Fixed by
  having it return `True` on success before ever running it live. Also
  corrected mid-build: an initial draft only treated `result is None` as
  a failure when `DATABASE_URL` was set, based on a false assumption that
  no-`DATABASE_URL` meant "no database" — this app always has *some*
  database (local SQLite fallback, per `engine.py`), so that condition
  would have silently swallowed real write failures in local/no-Postgres
  setups. Verified live end-to-end in-browser on both surfaces: a real
  submission from the resolver's `/meeting` page (filled form, submitted,
  "Thanks — we'll take a look." shown) confirmed to actually land in the
  DB via `GET /admin/problem-reports`; the Archive page's toggle/form
  confirmed to reveal correctly too. `.cassette-btn` reused for the
  submit button — technically outside the "just two buttons" scope
  `app/static/style.css`'s own comment claims, but consistent with
  `archive/templates/meeting_list.html`'s pre-existing "Search"/"Apply
  filters" buttons already extending past that scope; not re-litigated
  here, just noted.

- **[Done 2026-08-08] CivicClerk closed captions, previously unverified,
  now implemented from a real user-supplied example.** The user found a
  real CivicClerk event with populated captions —
  `emporiaks.portal.civicclerk.com/event/585/media` (Emporia, KS) —
  after 8 sampled cities across two sessions had all come back with null
  caption fields (`BACKLOG.md` had accumulated a theory that captioning
  is an opt-in add-on most customers don't turn on; this doesn't disprove
  that, just confirms it's real and working when a city does).

  **Real format finding, not assumed**: the caption file is **SRT, not
  VTT** — `closedCaptionTracks[].file` is a `.srt` URL
  (`cpmedia.azureedge.net/emporiaks/ClosedCaption/....srt`). This
  codebase had no SRT parser at all before this (`app/utils/vtt_parser.py`
  was VTT-only). New `parse_srt()` added there.

  **Real bug caught before shipping**: SRT differs from VTT in that each
  cue is preceded by a standalone sequence-number line ("1", "2", ...).
  Feeding raw SRT text into the existing `parse_vtt()` directly is unsafe
  — once the first cue is open, a later sequence-number line doesn't
  match the timestamp regex, so `parse_vtt`'s loop treats it as more cue
  *text*, silently appending the next cue's index number to the end of
  the current cue. Confirmed on the real 3677-cue Emporia file before the
  fix (every cue but the last corrupted); `parse_srt()` strips
  sequence-number lines first (only when immediately followed by a
  timestamp line, so a caption that's legitimately just a number is never
  touched) before reusing `parse_vtt`'s cue-accumulation logic.
  `tests/test_vtt_parser.py` pins this down with both a minimal synthetic
  case and the real fixture, asserting no cue's text is left over as a
  bare number.

  `app/platforms/civicclerk.py`'s `resolve()` rewritten to actually fetch
  and parse captions instead of showing a "not verified yet" warning:
  tries `closedCaptionTracks` first (richer — supports multiple language
  tracks, mirroring Granicus/eScribe's real-content-language-detection
  pattern rather than trusting any `label` field), falls back to a bare
  `closedCaptionUrl`/`transcriptionUrl` when there's no tracks array
  (matching the fallback order in the reference implementation the user
  supplied). Dispatches VTT vs. SRT parsing by the caption URL's file
  extension, since there's no other signal available. Verified live
  end-to-end against the real Emporia event: 3677 real segments, English
  correctly detected from content (not a label), zero transcript
  warnings, real title/date/jurisdiction/video/26 real agenda items — and
  in-browser, confirming the transcript actually renders on the page with
  no console errors. `tests/test_civicclerk.py` gained a third real-fixture
  test (`Events/585` + `EventsMedia/585` + the real 272KB `.srt` file) for
  this exact case, and `BACKLOG.md`'s "unverified" bug item was removed
  since it's now a positively-confirmed, tested, working path.

- **[Done 2026-08-08] Generalized the CivicClerk SRT lesson across every
  caption-fetching adapter: wider format *detection* everywhere, real
  *parsing* for TTML/DFXP/ITT, best-effort text fallback for the rest.**
  Directly prompted by discussing what the SRT fix implied more broadly —
  the same "assumed VTT because that's what everything else uses" mistake
  was a live risk on Granicus and CA Legislature specifically, which both
  filtered caption candidates to `.endswith(".vtt")` even though the
  shared page scanner already recognized `.srt` as a subtitle URL and
  would have silently skipped one if a customer ever linked to it.

  **New in `app/utils/vtt_parser.py`**: `parse_ttml()` (real structured
  parser for TTML/DFXP/ITT — XML `<p begin= end=>` cues, namespace-agnostic
  tag matching since vendors vary on `tt:p` vs. a default namespace,
  clock-time and offset-time timeExpression support, frame/tick-based
  timing explicitly skipped rather than guessed at since there's no frame
  rate available to convert with); `strip_unknown_caption_markup()` (a
  deliberately generic, format-agnostic best-effort text extractor for
  SBV/SUB/SMI/SAMI/plain-.txt — strips markup tags, MicroDVD-style
  `{123}{456}` frame markers, and SRT/SBV-style timing lines, keeps
  whatever real text remains, no per-line timestamps); and
  `parse_captions_by_extension(url, content)`, a single dispatch point
  every adapter now goes through instead of each reimplementing its own
  extension-sniffing — returns `(cues, fallback_text)`, exactly one
  populated on success, both empty for a genuinely unreadable format
  (`.scc`/`.stl`, real binary/encoded formats with nothing extractable
  without real codec decoding). A bare `.xml` extension is ambiguous
  (some vendors export real TTML with a plain `.xml` extension rather
  than `.ttml`), so that case probes `parse_ttml()` first — a safe probe
  since it returns `[]` cleanly on non-TTML-shaped input, not a guess
  that could corrupt anything — before falling through to the generic
  text fallback.

  **`app/platforms/media_scan.py`** (the shared scanner Granicus/Swagit/CA
  Legislature all use) now recognizes `.ttml`/`.dfxp`/`.itt`/`.scc`/
  `.stl`/`.sbv`/`.sub`/`.smi`/`.sami` unconditionally, plus `.xml`/`.txt`
  only when the URL path also looks caption-related (`caption`,
  `subtitle`, `transcript`, or `/cc[_./-]`) — those two extensions are too
  generic to match unconditionally (would also catch sitemap references,
  analytics config, any random text file on the page); confirmed via a
  real test that a real `sitemap.xml` correctly stays unmatched while a
  `ClosedCaption/....srt`-shaped URL correctly matches. `media_type()`
  applies the same keyword gate independently (not just relying on
  callers to have already gone through the gated scanner), since it's a
  general classifier some caller might run on an un-scanned URL (e.g. a
  caption URL straight from an API field, as CivicClerk does).

  **Adapter changes** (Granicus, CA Legislature, Swagit, CivicClerk — the
  four that ever fetch a caption file): each now tries every detected
  caption URL through `parse_captions_by_extension`. Structured results
  (`cues`) go through the exact same language-detection/best-track/
  garbled-check logic as before (Granicus/CivicClerk's multi-track
  selection was untouched, just fed from a wider candidate pool).
  Unstructured `fallback_text` becomes `segments` with every non-blank
  line as its own pseudo-cue at `start=0.0, end=0.0` (deliberately not a
  new model field — reuses the existing transcript-list rendering path
  for free, and a click still seeks to a valid position, just not a
  precise one), with a warning explaining the format limitation. Neither
  produced anything (binary formats, or a text-based one that came back
  genuinely empty) surfaces a direct "you can view it directly: {url}"
  warning instead of silence, mirroring the existing `AgendaViewer.php`
  fallback-link pattern. Swagit gained an entirely new code path here —
  it previously only ever tried `#transcript-fragments` (a DOM mechanism,
  still unverified per BACKLOG.md) and never looked at `media_urls` for a
  real caption *file* at all.

  **Everything re-verified live against the real meetings already used to
  build these adapters, confirming zero regressions**: Simi Valley
  (Granicus, 394 Spanish segments, same warnings, same language
  detection), Napa City (Granicus, blank-caption case, same "blank"
  message + agenda fallback link), Yountville CA (Swagit, 7 agenda items,
  same video resolution), Emporia KS (CivicClerk, 3677 SRT segments, zero
  warnings) — all byte-for-byte identical output to before this change.
  CA Legislature's real hearing samples from earlier sessions couldn't be
  re-located (no ID was ever recorded, and a live search for a current
  hearing with a populated caption track didn't turn one up in a
  reasonable amount of searching) — covered instead by new synthetic
  tests, including one confirming the real `/thumbnails/` scrubber-sprite
  VTT exclusion still holds under the wider extension list.

  **New test coverage**: 31 tests in `tests/test_vtt_parser.py` (up from
  14) covering `parse_ttml` (clock-time, offset-time, namespace prefixes,
  nested markup, frame-based-time skipping, malformed XML),
  `strip_unknown_caption_markup` (SBV/MicroDVD/SAMI shapes), and
  `parse_captions_by_extension`'s full dispatch tree; `test_media_scan.py`
  gained detection tests for every new extension plus the xml/txt
  keyword-gate (both positive and negative cases); Granicus/CivicClerk
  gained synthetic (not real — no non-VTT/SRT caption file has ever been
  observed on either platform) tests for both the text-fallback and
  link-only paths; and **CA Legislature and Swagit each got their first
  test file ever** (`test_ca_legislature.py`, `test_swagit.py`), scoped
  to the new caption-fallback logic specifically rather than full adapter
  coverage — the broader gap (no coverage of these two adapters' core
  resolve() flow at all) is still open, noted in the "Testing
  infrastructure" entry above.

- **[Done 2026-08-08] Permanent Archive page stuck showing no transcript
  after an adapter fix, with no way to refresh it besides waiting up to
  30 days — fixed with an on-demand admin recheck endpoint.** Found while
  investigating why `redtaperecordings.com/m/emporia-ks-2026-07-22-commission-meeting`
  (CivicClerk event 585) showed no transcript despite the SRT caption fix
  above being able to find one: that page had been pushed to the Archive
  *before* the fix landed, and `/api/resolve` checks the Archive before
  ever calling the adapter again ([app/main.py](app/main.py)) — so once a
  permanent page exists, every repeat visit just redirects to it,
  confirmed live by re-pasting the source URL and watching it bounce
  straight back with no new resolve. The only existing refresh path,
  `ARCHIVE_RECHECK_AFTER` (a 30-day passive background recheck on a stale
  lookup hit), hadn't elapsed for this page.

  **Fix**: `_recheck_archived_page()` (the function the passive recheck
  already used) changed from a fire-and-forget `-> None` to returning a
  summary dict (`pushed`, `platform`, `title`, `segment_count`,
  `agenda_item_count`, `transcript_warnings`, `video_warnings`) — the
  passive `BackgroundTasks` caller still discards it, unaffected. New
  `GET /admin/recheck-archive-page?token=&url=` calls it directly and
  awaits it synchronously (unlike the passive path, the caller here is
  explicitly waiting to see the outcome), gated by the same
  `ADMIN_STATS_TOKEN` pattern as the other `/admin/*` routes (404 on a
  bad/missing token, not 401/403, so it's not distinguishable from a
  typo).

  An earlier version of this fix was a one-off shell script
  (`scripts/refresh_archive_page.py`) meant to be run from a Render
  Shell, written before discovering the production plan doesn't have
  Shell access. Removed once the HTTP endpoint made it unnecessary — no
  reason to maintain two ways to do the same thing, and the endpoint
  works from anywhere (browser, curl, no Render access needed at all)
  rather than only from a shell on that one service.

  **Verified live end-to-end**: 84/84 tests still pass locally after the
  refactor. Once deployed, `curl
  ".../admin/recheck-archive-page?token=$ADMIN_STATS_TOKEN&url=https://emporiaks.portal.civicclerk.com/event/585/media"`
  (run from the user's own Render Shell, token substituted from that
  container's own env — never typed/pasted anywhere) returned
  `{"pushed":true,"platform":"civicclerk","title":"Commission
  Meeting","segment_count":3677,"agenda_item_count":26,
  "transcript_warnings":[],"video_warnings":[]}`. Reloading the permanent
  page immediately after confirmed the Transcript section now renders (a
  `<h2>Transcript</h2>` heading present, 3703 `.transcript-segment`
  elements — 3677 transcript lines + 26 agenda items, both reusing the
  same CSS class per the Agenda section's markup-reuse design — with the
  first three real lines: "CALL MEETING TO ORDER", "MEMBERS PRESENT",
  "PROCLAMATIONS").

  Residual gaps intentionally left open, split back out into
  [BACKLOG.md](BACKLOG.md): the *passive* 30-day recheck cadence still
  doesn't vary by transcript quality (this fix only added the on-demand
  manual path, not a smarter automatic one), and Emporia's own
  `eventBookmarks` all reporting `markerTimeStart: 0` (a separate, real
  source-data quirk noticed during this same investigation, unrelated to
  the missing-transcript bug) is still unaddressed.

- **[Done 2026-08-08] Granicus: video missing on cities whose
  `MediaPlayer.php` only embeds a legacy Flash player, fixed with a
  fallback to Granicus's newer `/videos/{id}/player` page.** Found via a
  user-reported real meeting,
  `redtaperecordings.com/m/city-of-fountain-valley-city-council-meeting-jun-16th-2026`
  (source: `fountainvalley.granicus.com/MediaPlayer.php?clip_id=607`),
  which showed no video at all. Root cause, confirmed directly against
  the live page: `MediaPlayer.php`'s HTML embeds only a `modernplayer.swf`
  Flash object whose `VideoUrl` param points at `ASX.php?...&stream_type=
  rtmp` — RTMP, unplayable in any modern browser, not a bug in our
  scanner correctly ignoring it. `GranicusAssetFinder` only ever fetched
  the originally-submitted page, so for a city on this legacy template
  there was never any `.m3u8`/`.mp4` to find. Separately confirmed
  Granicus does have a real, working HLS stream for the same clip, just
  on a page this adapter never fetched:
  `fountainvalley.granicus.com/videos/607/player`, which loads `hls.js`
  against a genuine `archive-stream.granicus.com/.../playlist.m3u8`.

  **Fix** (`app/platforms/granicus.py`): extracted the existing
  m3u8-preferred/mp4-fallback selection logic into a new
  `_pick_video_url()` staticmethod (previously inlined in `resolve()`),
  and added `_fetch_video_from_player_page()` — only called when the main
  page's candidates yield no video, so cities where it's already found
  there (the common case) pay no extra request. Single-attempt, not
  `_fetch_page`'s retry-with-backoff (matching `_fetch_caption_file`'s
  style) — this is an opportunistic fallback probe, not the one request
  the whole resolve depends on, so a slow/dead player page fails cheap
  rather than costing multiple retries with exponential backoff on every
  affected city.

  **Verified live end-to-end, twice**: first against Granicus's own
  `/videos/607/player` page directly in-browser (`readyState: 4`,
  i.e. fully loaded and playable, confirmed by actually calling
  `.play()` and watching `currentTime` advance) — ruling out that the
  discovered stream URL itself was somehow dead despite existing (a real
  risk: a bare `curl` to the same m3u8 URL got a 403 from Granicus's CDN,
  almost certainly hotlink/bot protection rather than a broken stream,
  since the real browser fetch succeeded fine). Then against this
  resolver's *own* frontend, run locally (`uvicorn app.main:app --port
  8010`) against `/meeting?url=<the real clip 607 URL>` — confirmed the
  video element reaches `readyState: 4` and visibly renders the real
  Fountain Valley council chamber footage (screenshot: title card "City
  Council Study Session Meeting, June 16, 2026", duration 7:31:13
  matching the stream's real `duration: 27073.36`s), ruling out a
  same-origin-only quirk (Granicus's own domain vs. a cross-origin
  `hls.js` fetch from `redtaperecordings.com` could plausibly have hit a
  different CORS/referrer outcome — it didn't).

  Incidentally, this is the same meeting CLAUDE.md already flagged as a
  useful caption-parsing sample ("language misdetected as Portuguese")
  — separately confirmed during this same investigation to be genuinely
  garbled at the source: fetched the real `.vtt` directly from Granicus,
  it's structurally valid WebVTT (correct header/timestamps) but the cue
  *text* is garbage (`###...@@@@@@@kkIkkkkk~kkkkkkkook?Ek?E?E?E`) —
  Granicus's own captioning pipeline failing for this meeting, not a
  decoding bug on our end. `langdetect` calling that noise `'pt'` is
  expected garbage-in/garbage-out behavior; the system already handles
  it correctly (`is_likely_garbled` fires, the "looks garbled at the
  source... treat it as approximate" warning shows). Nothing to fix
  there — CLAUDE.md's sample-list entry updated to describe it
  accurately (garbled-hence-misdetected, not just misdetected) and to
  note the video gap is now fixed.

  **New test coverage**: `tests/test_granicus.py::
  test_resolve_falls_back_to_player_page_for_video_when_mediaplayer_has_none`,
  backed by three new real fixtures (`fountainvalley_clip607_mediaplayer.html`,
  `fountainvalley_clip607_player.html`, `fountainvalley_clip607_captions.vtt`,
  all fetched live 2026-08-08) — pins the exact real m3u8 URL, `m3u8`
  format, zero video warnings, 146 real (garbled) segments, and the
  `'pt'`/garbled transcript warnings together, so this exact case can't
  silently regress. The three existing synthetic caption-fallback tests
  (blank-guessed-captions, unstructured-text-fallback, unreadable-format)
  needed a `/videos/{id}/player` 404 route added to their existing mocks,
  since none of their fixtures have a video either and would otherwise
  now trigger the new fallback request unmocked.

- **[Done 2026-08-08] Swagit and CA Legislature never ran language
  detection, so real English transcripts showed no "en" on the
  `/meetings` listing.** User-reported from the Browse Meetings page:
  "Jan 13, 2026 City Council" (Dublin, CA, Swagit) showed a bare
  jurisdiction/date with no language and no "agenda only" tag despite
  clearly having a real transcript. Root cause, confirmed by reading
  every adapter: Granicus and CivicClerk both call content-based language
  detection (never trusting a source `srclang` label — see the Simi
  Valley Spanish-mislabeled-`en` finding elsewhere in this file) and pass
  `transcript_language` through; `SwagitAssetFinder` and
  `CaliforniaLegislatureAssetFinder` never called it at all, leaving the
  field permanently `None` for every meeting on either platform,
  regardless of transcript quality. Masked on each individual meeting
  page because `archive/main.py`'s `page_lang` defaults to `"en"` when
  the stored value is falsy (`(active_version["language"] if
  active_version else None) or "en"`) — correct for the `<html lang>`
  attribute's own purpose, but it meant the gap was invisible anywhere
  except the `/meetings` list, which shows the raw stored value with no
  such fallback.

  Incidentally confirms a previously-"unverified" path for real: Dublin's
  Jan 13, 2026 meeting (Swagit clip 372020) has a genuine 36,072-cue
  English transcript via `#transcript-fragments a[data-ts]` (one word per
  cue) — `SwagitAssetFinder`'s class docstring and
  [BACKLOG.md](BACKLOG.md) both said this DOM path had "never been
  populated in any sample checked." It's real; that unverified note is
  removed. Separately confirmed a real Senate floor session
  (`senate.ca.gov/media/senate-floor-session-20260806`, 3,084 cues) has
  the same missing-language gap on the CA Legislature side.

  **Fix**: extracted the two byte-identical `_detect_cue_language`
  copies already duplicated across `granicus.py` and `civicclerk.py` into
  one shared `detect_language_from_texts()` in `app/utils/vtt_parser.py`
  (took a plain `Iterable[str]` rather than a cue-dict shape, since
  Swagit/CA Legislature's segments are already `TranscriptSegment`
  objects, not raw dicts, at the point language needs detecting) — three-
  strikes-you-extract, not premature, since this was about to become a
  fourth copy. `swagit.py` now detects language once from whichever real
  segments it found (`#transcript-fragments` or the caption-file
  fallback); `ca_legislature.py` detects it for both its structured-cue
  and unstructured-text-fallback paths.

  **Verified live end-to-end** against both real meetings that surfaced
  the gap: Dublin clip 372020 (`transcript_language: "en"`, 36,072
  segments) and the Senate floor session (`transcript_language: "en"`,
  3,084 segments, real `.m3u8` video URL too). 87/87 tests pass (85
  existing + 2 new: `test_swagit.py::
  test_resolve_detects_language_from_transcript_fragments` and
  `test_ca_legislature.py::test_resolve_detects_language_from_real_captions`,
  both synthetic — coherent English sentences fed through the same
  `#transcript-fragments`/caption-file code paths, pinning that language
  detection actually fires and gets wired through to
  `ResolvedMeeting.transcript_language`). Only fixes future resolves —
  the two real meetings' existing permanent Archive pages still need the
  same `/admin/recheck-archive-page` treatment as Emporia/Fountain Valley
  before this shows up live on `/meetings`.

  While auditing the `/meetings` listing for this, found a third,
  structurally different bug on the same page (a permanent page frozen
  with output from a since-removed code path, not fixable by a recheck at
  all) — kept as its own open item in [BACKLOG.md](BACKLOG.md) rather than
  folded in here, since the fix shape is completely different.

- **[Done 2026-08-08] `/meetings` search now covers transcript/agenda
  text, with an exact/fuzzy toggle, replacing the old title/jurisdiction-
  only keyword box.** User-requested: transcription errors mean a
  literal word like "traffic" can show up in a real transcript as
  "trafic" or "traffiq", so a plain substring search would silently miss
  real matches. Also dropped the `language` text-filter field per the
  request and added `has_transcript`/`has_agenda` checkboxes instead —
  more directly useful than a free-text language guess, and fixes real
  cases already found in this session (Yountville's stale/misleading
  transcript-shaped agenda, the Emporia/Fountain Valley pages before
  their admin-recheck refresh) being invisible to filter on before.

  **Design decision, made deliberately, not a placeholder:** no schema
  change, no Postgres-only extension. `archive/utils/search.py` does
  exact (plain substring) and fuzzy (bounded Levenshtein per word,
  threshold scaled by word length: 0 for <=4 chars, 1 for 5-7, 2 for 8+)
  matching in pure Python, over text read from the same JSON columns
  that already exist — no new column, so nothing to migrate. Exact is
  the default (per the user's explicit ask, "that way when searches run,
  they'll default to the faster one") since it skips per-word distance
  computation entirely. This is a real, acknowledged scale limit, not an
  oversight — see the new "Search: move to a materialized/indexed
  column" entry in [BACKLOG.md](BACKLOG.md) for what outgrowing it looks
  like and why it isn't built that way yet.

  **`archive/db/crud.py`'s `list_pages()` rewritten**: `has_transcript`
  still filters in SQL (cheap, no JSON involved — it's just "does a
  default `TranscriptVersion` row exist"). Transcript `segments` are only
  ever pulled from the DB when a keyword search is actually running,
  so a plain filter-only browse of `/meetings` never drags every
  meeting's full transcript JSON over the wire for nothing (Dublin's
  real 36k-segment transcript alone is over a megabyte of JSON — see the
  Swagit language-detection entry above). `has_agenda` and keyword
  matching can only be evaluated once content is in hand, so pagination
  for those runs in Python over the SQL-filtered candidate set instead
  of `LIMIT`/`OFFSET` — a real behavior change from before, fine at
  today's scale, called out explicitly in the function's own docstring
  for whoever touches this next.

  **Verified**: `tests/test_archive_search.py` (5 new tests, pure
  functions, no DB/mocking needed) pins the exact-vs-fuzzy behavior
  directly, including the motivating "traffic"/"trafic"/"traffiq"
  example and that short words (<=4 chars) require an exact token match
  rather than fuzzing into unrelated words ("cat" must not match "car").
  End-to-end verified live against a local archive service + seeded
  SQLite data (not synthetic-only): exact search for "traffic" found a
  real transcript containing it, the same search for the typo "trafic"
  correctly found nothing in exact mode and correctly found it in fuzzy
  mode, `has_agenda`/`has_transcript` checkboxes correctly filtered a
  two-meeting seed set, and the rendered `/meetings` page (screenshotted)
  showed both checkboxes, the language/​"agenda only" badges, and
  filter-state persistence through a real "Apply filters" submit — not
  just checked via the Python API. 92/92 tests pass.

- **[Done 2026-08-08] On-demand transcription from audio — a viewer can
  request our own transcript when the source's own captions are missing,
  garbled, or wrong-language.** User-designed feature, planned in detail
  before building (job execution infra, transcription engine, and
  email-verification strictness were all explicit decisions the user made
  rather than defaults picked silently). Real product goals stated
  alongside the request, intentionally not built now but designed around:
  speaker diarization + a name-mapping UI, and comparing the finished
  transcript against the agenda for topic coverage — both moved to
  `CLAUDE_BACKLOG.md`.

  **Architecture: a third service.** Neither the resolver nor the Archive
  web service can run something that might take hours, so a new
  `worker/` — a persistent, paid Render Background Worker (the first
  paid, always-on infrastructure this project has needed; no free tier
  exists for this) — processes jobs in the background. Deliberately
  breaks the resolver/Archive HTTP-only separation in one direction only:
  the worker imports `archive.db`/`archive.utils.email` directly (it *is*
  Archive backend logic, just in a process shape the Archive's own web
  dyno can't offer) and `app.platforms` directly (read-only, to re-resolve
  a fresh media URL before each chunk — HLS/signed URLs can go stale over
  a long job). `app/platforms/media_probe.py`'s ffmpeg/ffprobe wrapper and
  the adapter-registration helper (`app/platforms/__init__.py`'s new
  `register_all_finders()`, extracted from what used to be nine inline
  `register()` calls in `app/main.py`) both live under `app/platforms/`
  specifically so `app/main.py`'s synchronous feasibility-check endpoint
  and `worker/main.py`'s chunk processing can share them without `app/`
  ever depending on `worker/`.

  **The flow**: feasibility check (`POST /api/transcription/check-
  feasibility` — live-resolves, then `ffprobe`s the real duration, reject
  under 5min/over 14h) → submit (`POST /api/transcription/submit`,
  re-checks feasibility server-side, never trusts a client flag) → the
  Archive creates a `TranscriptionJob`
  (`POST /internal/transcription/create-job`) → **email-verification
  rule, exactly as specified**: if the address is already in the Resend
  newsletter audience, the job queues immediately; a first-time address
  requires one confirmation-email click
  (`GET /confirm-transcription` on the resolver →
  `POST /internal/transcription/confirm`), which also opts them into the
  audience so every request after their first is frictionless → the
  worker loops claiming one chunk at a time
  (`archive/db/crud.py`'s `claim_next_chunk()`), extracting that chunk's
  audio with `ffmpeg` (re-resolved media URL, realistic User-Agent/
  Referer headers — see the Fountain Valley 403 workaround below),
  transcribing it with self-hosted `faster-whisper` (model loaded once at
  worker startup, reused for every job/chunk after that — **exactly the
  "free service that won't suck" the user asked for**, since the worker's
  cost is already fixed regardless of how much gets transcribed, no
  per-minute API meter on top), shifting timestamps from chunk-relative to
  full-meeting-relative seconds (`worker/segment_utils.py`'s
  `shift_segments()`), and persisting the result
  (`report_chunk_result()`) before moving on — checkpointed after every
  chunk specifically so a worker restart/redeploy loses at most one
  in-flight chunk, never the whole job. On the last chunk: a new
  `TranscriptVersion(source="transcribed")` is created, its language
  detected from its own real text
  (`archive/utils/language.py`, a deliberate duplicate of `app/utils/
  vtt_parser.py`'s `detect_language_from_texts()` — same reasoning as the
  existing `url_normalize.py` duplicate, keeps the Archive's web service
  from gaining a dependency on `app/`), and — closing a real,
  independently-confirmed gap — promoted to the page's default via new
  `promote_transcript_version()`.

  **Real, previously-existing bug fixed as part of this**: before this
  build, only the very first `TranscriptVersion` a `MeetingPage` ever got
  was set `is_default=True` — nothing later ever promoted a subsequent
  one, an unresolved question already flagged in this file's own Archive-
  build entry above. `promote_transcript_version()` closes it: demotes
  the previous default, promotes the new one, never deletes anything (the
  demoted version stays reachable through the existing `?version=`
  picker).

  **Schema, deliberately minimal**: new `TranscriptionJob` table
  (`archive/db/models.py`) — status machine `pending_confirmation` →
  `queued` → `in_progress` → `completed`/`failed`, `partial_segments`
  accumulated as the durable per-chunk checkpoint, `confirmation_token`.
  No migration needed (`create_all()` handles a new table, per this
  repo's existing convention). One shared-code addition to a model that's
  used everywhere: `TranscriptSegment` (`app/platforms/models.py`) gained
  an optional `speaker` field, unused by every path today including this
  one — added now, cheaply, since it's free and saves a schema touch when
  diarization is actually built (the same base `faster-whisper` model
  WhisperX already builds real diarization on top of via
  `pyannote.audio`, so this wasn't a speculative guess at the eventual
  design).

  **`ingest_resolution()` refactored**: its inline find-or-create-
  `MeetingPage` logic was extracted into `_find_or_create_page()`, since
  `create_transcription_job()` needed the exact same "find this meeting's
  permanent page, or create one" behavior (a transcription request can be
  the very first thing that ever creates a page for a meeting, same as a
  normal resolve).

  **Verified live, not just unit-tested, at every layer**:
  - `app/platforms/media_probe.py`'s `ffprobe`/`ffmpeg` wrappers against a
    real public HLS stream (Apple's bipbop test stream, 1800.00059s probed
    duration matching the stream's actual real length) — and, the
    motivating case — the **exact** Granicus CDN URL that returned a bare
    403 earlier this session (Fountain Valley clip 607, `BACKLOG_DONE.md`
    entry above): with the realistic-headers workaround, `ffprobe`
    correctly returned `27073.362074`s, matching the `7:31:13` observed
    in-browser in that earlier entry exactly.
  - `worker/transcription_engine.py`'s `FasterWhisperEngine` against real
    speech (macOS `say` → `ffmpeg`-converted audio): produced an accurate
    transcript with correct per-segment timestamps; chained with
    `shift_segments()` at a simulated chunk-3 offset (2700s) and confirmed
    the shifted timestamps were exactly right.
  - The full `TranscriptionJob` lifecycle against a real (file-based,
    isolated) SQLite session — creation, the per-page duplicate-job lock,
    the global concurrent-job cap, chunk-by-chunk claim/report,
    finalization, promotion, and the confirm-token flow (including that a
    used/wrong token correctly fails) — both by hand and as 8 real pytest
    integration tests (`tests/test_transcription_jobs.py`, using a new
    session-scoped isolated-SQLite-file fixture in `tests/conftest.py`
    added specifically for this, since no archive/db test infra existed
    before this feature).
  - Every new HTTP endpoint over real HTTP (not just direct Python calls):
    `archive/main.py`'s new `/internal/transcription/*` routes (including
    confirming the 404-not-401 auth pattern holds, and that a
    validly-shaped-but-unauthenticated request is correctly rejected) and
    `app/main.py`'s new `/api/transcription/*` routes, run together as two
    live local services — feasibility check and submit both verified
    against the real Fountain Valley meeting, including the real
    `pending_confirmation` → confirm-link → `queued` transition and the
    correctly-stripped `requester_email` in every public-facing response.
  - `worker/main.py`'s actual `process_next_chunk()` end-to-end against a
    real seeded job (real bipbop audio, real `faster-whisper` "tiny"
    model, graceful fallback when the platform re-resolve legitimately
    fails, graceful degradation when Resend isn't configured for the
    completion email) — and separately, the real `run_forever()` polling
    loop (not just the underlying function) driven end-to-end with the
    actual default `"small"` model, confirming the full production
    startup → model-load → poll → claim → process → complete path works,
    not just its pieces in isolation.
  - The full frontend flow (toggle → feasibility check → email step →
    submit → correct success/error messaging) on **both** the resolver's
    ephemeral `/meeting` page and the Archive's permanent `/m/{slug}`
    page, screenshotted, against the real Fountain Valley meeting on both.
  - `render.yaml` validated as parseable YAML with the expected structure;
    `worker/Dockerfile` reviewed by hand but **not** build-tested (no
    Docker daemon available in the build environment) — flagged as a real
    gap in `BACKLOG.md`, not silently assumed to work.
  - 111/111 tests pass (was 92 before this feature; +19 new: 5
    `test_worker_segment_utils.py`, 1 `test_media_probe.py`, 8
    `test_transcription_jobs.py` covering the DB lifecycle including the
    new language-detection-on-completion behavior, plus the
    `TranscriptSegment.speaker` field addition needed no new test since
    it's a passive schema addition with no behavior to verify yet).

  Real gaps intentionally left open (see `BACKLOG.md`'s "On-demand
  transcription" section for the full list): ffmpeg availability on the
  resolver service is unverified (may need a Docker runtime switch, same
  as the worker), the worker's Render plan sizing for `faster-whisper` is
  a guess pending real memory profiling, Resend's contact-lookup-by-email
  endpoint shape is unverified against a real account, an unconfirmed
  `pending_confirmation` job blocks new requests for that meeting with no
  expiry, and — most importantly — **nothing here has been exercised
  against actual deployed Render infrastructure yet**, only locally and
  against real external services (Granicus's CDN, Apple's test stream,
  Hugging Face's model hub) from a local/sandboxed environment.

- **[Done 2026-08-08] First real deploy of the transcription worker
  crash-looped: `worker/requirements.txt` was missing `pydantic`.** Real
  production failure, confirmed from Render's own logs immediately after
  the entry above shipped:
  `ModuleNotFoundError: No module named 'pydantic'` at `worker/main.py`'s
  very first import (`app.platforms.base` → `app.platforms.models`,
  which imports `pydantic` directly) — `worker/Dockerfile`'s image built
  fine (a real, useful data point: the un-build-tested-locally risk
  flagged above turned out fine), but the container crashed on every
  start, Render restarting it in a loop.

  **Root cause of why local testing missed this**: every local
  verification of `worker/main.py` (BACKLOG_DONE.md's entry above lists
  several) ran inside this repo's one shared dev `.venv`, which already
  had `app/`'s full `requirements.txt` (including `pydantic`, via
  `fastapi`) installed alongside `worker/requirements.txt`'s packages —
  so a genuinely missing entry in `worker/requirements.txt` specifically
  was invisible no matter how thoroughly the *code* was exercised.
  **Fix, and the methodology lesson that matters more than the one-line
  diff**: added `pydantic>=2.0` to `worker/requirements.txt`, then
  re-verified all three services — not just the worker — each in a
  freshly created, genuinely isolated venv containing *only* that
  service's own `requirements.txt` (`python3 -m venv ...` +
  `pip install -r .../requirements.txt` + a plain import, nothing
  borrowed from the shared dev environment). `app/`, `archive/`, and
  `worker/` all now confirmed to import cleanly on their own declared
  dependencies alone. Worth remembering for any future change that
  touches more than one of these three services: a shared local dev venv
  is fine for iterating quickly, but the *last* check before pushing
  anything that adds a new cross-file import needs to happen against
  each service's real, isolated dependency set, or a missing-package bug
  like this one won't surface until it's already live and crash-looping.

- **[Done 2026-08-08] Set up `HF_TOKEN` for the worker.** No code change
  needed — `huggingface_hub` (a `faster-whisper` dependency) already
  reads `HF_TOKEN` from the environment on its own; this was purely an
  infra step. `render.yaml` updated to document the (optional) env var
  slot on `rtr-transcription-worker`. User created a free Hugging Face
  account, generated a read-only access token, and added it to the
  worker's environment in Render — future model-load logs should stop
  showing the "sending unauthenticated requests" warning.

- **[Done 2026-08-08] Unconfirmed `pending_confirmation` transcription
  jobs now expire instead of blocking a page forever.** Was: an
  unconfirmed first-time request had no expiry, so it would block any
  new request for that meeting indefinitely. Fixed exactly as previously
  scoped: `archive/db/crud.py` gained `PENDING_CONFIRMATION_EXPIRY =
  timedelta(hours=48)`; `create_transcription_job()`'s duplicate-request
  check now treats a `pending_confirmation` job older than that as not
  blocking (a fresh request creates a new job instead of returning the
  stale one); `confirm_transcription_job()` was updated to match — a
  stale confirmation-email link for an expired job now returns `None`
  (same "invalid or already used" response as an unknown token) rather
  than being able to resurrect an abandoned job after a newer one may
  have already superseded it. The now-unused `ACTIVE_JOB_STATUSES`
  constant was removed rather than left dead. Verified with new tests
  (`tests/test_transcription_jobs.py::test_expired_pending_confirmation_
  is_superseded_and_unconfirmable`, backdating a real row's `created_at`
  directly): a fresh request after expiry gets a new job id, and the old
  token no longer confirms. Full suite green (115 tests) after the
  change.

- **[Done 2026-08-08] All-zero agenda timestamps (Emporia, KS's CivicClerk
  `eventBookmarks`) no longer render as false clickable `[0:00]` links.**
  User picked the "suppress + plain outline" option over "keep the links
  with a warning" — a link that looks actionable but silently does
  nothing is worse than no link at all. Implemented generically (not
  CivicClerk-specific) since the root pattern — "more than one agenda
  item, all sharing the exact same start time" — could show up on any
  platform, not just this one: `app/static/player.js`'s `renderAgenda()`
  and `archive/templates/meeting_page.html`'s agenda block (mirroring
  each other, same pattern as the rest of this codebase's duplicated
  frontend logic) both detect `items.length > 1 and every item.start ===
  items[0].start`, and when true render a plain unlinked outline with a
  one-line note ("This source doesn't provide real per-item timestamps,
  so these agenda items aren't clickable.") instead of the normal
  clickable-timestamp treatment. A single item at `0:00` is deliberately
  *not* suppressed — that's the normal case of the first agenda topic
  starting at the top of the video. Verified: full pytest suite green
  (116 tests) plus a direct Jinja-render check of all three cases
  (all-zero, normal distinct times, single item at 0:00) confirming the
  right branch renders in each.

- **[Done 2026-08-08] Worker's chunk-failure log now uses the same
  1-indexed chunk numbering as the claim-success log.** Found while
  investigating a real production timeout (`worker/main.py`'s ffmpeg
  extraction hit `_SUBPROCESS_TIMEOUT_SECONDS` on one chunk of a real
  job): the claim log used `chunk_index + 1` (1-indexed, e.g. "chunk
  11/12") while the two failure logs used the raw 0-indexed `chunk_index`
  directly, so a failure and its immediate retry looked like two
  *different* chunks in the logs (off by one) even though
  `report_chunk_result()`'s failure path never advances
  `chunks_completed`, meaning the same chunk really was retried
  correctly with no data loss. Confirmed via the actual production log:
  "ffmpeg extraction failed for chunk 11" (0-indexed = the 12th/last
  chunk) immediately followed by "Claimed job 2: chunk 12/12" (1-indexed
  = the same chunk) — genuinely confusing to read together, not a real
  bug in the retry logic itself. Fixed both failure log lines to use
  `chunk_index + 1, total_chunks` and spell out "(will retry on next
  poll)" explicitly, so a future read of these logs doesn't need this
  same investigation to know the outcome.

- **[Done 2026-08-08] Swagit's `#transcript-fragments` word-level
  segments now get grouped into readable multi-word lines.** Was: real
  data confirmed on a Dublin, CA meeting — six separate clickable
  `[0:04]`/`[0:05]` lines for the single six-word phrase "GOOD EVENING
  AND HAPPY NEW YEAR," spoken in under two seconds, since Swagit's
  `#transcript-fragments` DOM emits one `<a data-ts>` per word
  (`start == end`, a true instant) rather than real multi-word VTT/SRT
  cues like every other adapter. Fixed with a new pure function,
  `_group_word_fragments()` (`app/platforms/swagit.py`), applied only to
  the `#transcript-fragments` DOM path (not the real-caption-file path,
  which already has proper cues and shouldn't be re-merged) — a rolling
  4-second time window per line, chosen over a fixed word count or
  sentence-aware grouping (these fragments carry no punctuation at all
  to key off of). Each group's `start` is its first word's real
  timestamp, `end` its last word's. Verified against the exact real
  Dublin timestamps from the bug report
  (`tests/test_swagit.py::test_group_word_fragments_merges_real_dublin_example`)
  plus three more unit tests (empty input, single word, window-boundary
  behavior) and an updated integration test confirming the existing
  language-detection test still passes with grouped (not one-per-word)
  segments. Full suite green (121 tests).

- **[Done 2026-08-08] `ingest_resolution()` now promotes/demotes a
  page's default `TranscriptVersion` when warranted — the general fix
  for both the Yountville stale-transcript bug and the Dublin
  missing-language bug.** Was: a recheck could never improve a page's
  displayed default — `ingest_resolution()` (`archive/db/crud.py`) only
  ever *added* a new version `if segments:`, and only the very first
  version a page ever got was `is_default=True`; nothing later ever
  promoted or demoted anything. Two confirmed real bugs from this: a
  Yountville page permanently stuck showing 10 fake "transcript" rows
  that were actually a copy of the agenda (from a since-removed code
  path), and a Dublin page permanently stuck showing no language on
  `/meetings` even after `swagit.py`'s language-detection fix landed,
  because a fresh recheck would only ever add a *second*,
  correctly-labeled version without promoting it over the stale one.

  Fixed with two new helper functions plus a new `current_default`
  lookup at the top of `ingest_resolution()`, before any version is
  created:
  - `_is_real_improvement(current_default, new_language)` — narrowly
    scoped to the two confirmed real cases, not a blanket "always
    promote the newest": true if the current default has no real
    segments at all, or has segments but no detected language while the
    fresh version has one. If the current default already has both real
    segments and a language, a fresh duplicate-ish version isn't
    confidently better and is left alone — avoids flip-flopping the
    default unpredictably. When true and a new version was actually
    created this ingest, `promote_transcript_version()` (already built
    for the transcription-job completion path) is called on it — the
    Dublin-style half.
  - `_default_looks_like_copied_agenda(current_default, agenda_items)`
    — true if the current default's segment texts are structurally
    identical, in order, to the *freshly resolved* agenda_items in this
    same ingest. Detects the Yountville failure mode generally (any
    page with that same data shape), not by matching old warning-message
    text, which would only ever catch that one historical bug. When true
    and no new version was created this ingest (nothing better found
    either), the stale default is demoted (`is_default = False`) even
    without a replacement, rather than staying stuck forever.
  Both checks only ever run when a `current_default` already exists — a
  brand-new page's first version keeps its existing simple
  `is_default=True`-on-creation behavior unchanged.

  Verified with 5 new real-DB integration tests
  (`tests/test_ingest_promotion.py`): the Dublin case (promotes a newly
  language-detected version over a language-less default), the
  Yountville case (demotes a copied-agenda default when a recheck finds
  real agenda but no segments), a stability check (no promotion when the
  default already has both segments and a language), a brand-new-page
  sanity check (no crash with no existing default), and a negative case
  for the agenda-copy detector (a default with real, non-agenda-matching
  segments is correctly left alone). Full suite green (126 tests).

  Not yet done, left as a residual live item: actually running
  `/admin/recheck-archive-page` against the two real motivating pages
  (Yountville, Dublin) to confirm this fires correctly outside of tests
  too — needs `ADMIN_STATS_TOKEN`, which this session doesn't have — and
  the originally-planned audit of all 12 permanent pages for the same
  stale-shape issue, now that there's a real fix to apply if any others
  turn up. See BACKLOG.md.

- **[Done 2026-08-08] Swagit's ALL-CAPS `#transcript-fragments` text now
  gets re-cased for readability, reusing the existing shouting-caption
  standard instead of inventing a second one.** Confirmed live on the
  real Dublin, CA meeting: the grouped word-fragments (see the grouping
  entry above) were still genuinely ALL CAPS at the source ("GOOD EVENING
  AND HAPPY NEW YEAR..."), reading as shouting even once grouped into
  real lines. `app/utils/vtt_parser.py` already had exactly this problem
  solved for Granicus's VTT captions (confirmed real on San Francisco's
  all-caps live captions) via `normalize_shouting_caption()` (renamed
  from `_normalize_shouting_caption` to make it importable — no other
  behavior change) + `_sentence_case()`: detects roughly-all-uppercase
  content (not per-cue, so a normal transcript with a few capitalized
  acronyms is never touched) and re-cases it. `swagit.py`'s
  `#transcript-fragments` branch now calls the same function on its
  grouped segments (converted to the dict shape the function expects,
  written back onto the `TranscriptSegment` objects afterward) right
  after grouping — reuses the exact tested detection/casing logic rather
  than a second Swagit-specific implementation, and correctly no-ops on
  a hypothetical future Swagit deployment that turns out to emit
  normal-case text. Verified with a new integration test
  (`tests/test_swagit.py::test_resolve_normalizes_all_caps_transcript_fragments`)
  using the real all-caps Dublin wording end-to-end through `resolve()`.
  Full suite green (127 tests).

- **[Done 2026-08-08] `/meetings`' fuzzy/exact search toggle moved into
  the filters dropdown; filters laid out in deliberate rows; a real
  "Clear all filters" button added.** The fuzzy checkbox had been hidden
  entirely in an earlier pass (per an explicit request, based on a
  mistaken belief it was already inside the filters dropdown when it was
  actually in the main search bar) — real regression, since that left it
  reachable only via a raw `?fuzzy=true` URL param with no UI control at
  all. Restored into `archive/templates/meeting_list.html`'s actual
  filters `<form>` this time, alongside "Has transcript"/"Has agenda."
  Also fixed the messy layout the user flagged: the filters form used to
  be one flat `flex-wrap` container, so narrow checkboxes landed on
  whatever row had leftover horizontal space next to unrelated text/date
  fields — accidental grouping, not deliberate. Now three explicit
  `.filters-row` groups (fields / checkboxes / actions) stacked in a
  column, each wrapping independently. "Clear all" already existed as a
  plain muted text link shown only when a filter was active (an existing,
  easy-to-miss `.clear-filters` class matching this session's recurring
  "small text link, easy to miss" pattern) — now a real always-visible
  `.cassette-btn-outline` button (a new, visually lighter sibling to the
  existing bold `.cassette-btn`, so it doesn't compete with "Apply
  filters" for attention) next to "Apply filters." Verified with a Jinja
  render check; no backend changes needed (`fuzzy: bool = False` in
  `archive/main.py` already parsed the checkbox correctly, same
  convention as the existing `has_agenda`/`has_transcript` checkboxes).

- **[Done 2026-08-08] The AI-transcript disclaimer now appears everywhere
  an AI-generated transcript is actually shown, not just the meeting
  page, and has real visual identity.** Audited every surface: the
  on-page disclaimer (`archive/templates/meeting_page.html`) was the
  *only* place it existed — the `.txt` transcript export
  (`/m/{slug}/transcript.txt`) and the transcription-completion email
  (`archive/utils/email.py`) both quoted/exported AI-generated text with
  zero indication it might be wrong. Fixed:
  - `.txt` export: the same disclaimer text prepended when
    `active_version.source == "transcribed"`. Deliberately *not* added to
    the `.srt` export — SRT is a strict cue format meant for subtitle
    players, and a fake cue at 00:00 would visually overlay the video as
    if it were spoken dialogue, competing with the real first line;
    plain text has no such constraint.
  - Completion email: added unconditionally (every completion email is,
    by definition, about an AI-transcribed version — `send_completion_
    email()` only ever gets called from the transcription-job completion
    path), matching the on-page wording.
  - Styling: the on-page disclaimer moved off the plain amber `.warnings`
    pill every other transcript-quality message uses, onto a new
    `.ai-disclaimer` treatment that reuses the site's `.dymo-label-small`
    motif (the same "label-maker tag" look as the site wordmark and the
    `/subscribe` page's section tag) as a real visual flag — a small
    "AI TRANSCRIPT" badge next to the text, per an explicit request to
    give this one more identity than a generic warning, since it's
    telling a reader the text might contain fabricated sentences, not
    just "approximate."
  Verified with Jinja render checks (both templates) and the full pytest
  suite (127 tests, unaffected — template/CSS/email-copy changes only).

- **[Done 2026-08-08] `/meetings` search results now show a "✓
  Transcript" badge instead of a raw language code, and it's
  quality-aware, not just presence-aware.** Was: the listing showed
  `· en` (or `· es`, etc.) — not intuitive at a glance, per direct
  feedback, and beside the point anyway since the real question a viewer
  has is just "does this meeting have a transcript," not which language
  it's in. Replaced with a `✓ Transcript` badge, shown regardless of
  language (per explicit follow-up: language-independent, but *only* for
  quality transcripts) — `archive/db/crud.py`'s `list_pages()` used to
  set `has_transcript` from bare row presence (`version_id is not
  None`), which would badge a genuinely garbled transcript the same as a
  clean one. Now reuses the same `_GARBLED_MARKER` signal
  `_has_good_transcript()` already uses (built earlier this session for
  the Archive recheck cadence), inlined directly in `list_pages()`'s row
  loop rather than calling that function per row -- it does its own DB
  query per page, which would be a real N+1 across a results page;
  `transcript_warnings` is now pulled in the same single batched query
  `list_pages()` already runs, cheap since it's a short list unlike full
  segment JSON. Styled with `.has-transcript-badge` (`--accent` blue,
  no new hardcoded color). Verified with a new real-DB test
  (`tests/test_list_pages_search.py::test_has_transcript_badge_is_quality_aware_not_just_presence`,
  a garbled page and a clean page in the same query, asserting the badge
  differs) plus a Jinja render check. Full suite green (128 tests).
