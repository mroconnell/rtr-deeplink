# Backlog

Live items only, roughly in priority order. Completed work — including the
investigation detail behind each fix — lives in
[BACKLOG_DONE.md](BACKLOG_DONE.md); items below link back to it for context
where relevant.

## Bugs

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

## Platform coverage — open questions

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
- **Swagit `#transcript-fragments` unverified.** The page JS references it
  for a real free-text transcript feature, but it's never been populated in
  any sample checked (only `.playerControl` chapter markers were present).
  `SwagitAssetFinder` handles it defensively but it's unverified. Needs a
  real example.
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
