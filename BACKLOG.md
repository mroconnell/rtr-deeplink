# Backlog

Known bugs and features not yet addressed, roughly in priority order.

## Bugs

- **[Done 2026-08-06 for Legistar] Unsupported-platform failure is too
  blunt.** Fixed for Legistar specifically: `LegistarAssetFinder` now finds
  and delegates to the embedded Granicus link when present, and when given
  a calendar/listing page instead of one meeting (confirmed real: Maricopa,
  AZ's Calendar.aspx had 20 video links across 47 rows), returns a
  dedicated "this is a calendar" response with a pick-list of real
  meetings (title/date/url) pulled from the page, rather than a bare
  error. Still generic/unbuilt for platforms with no adapter at all (the
  plain "We don't support 'x' meeting pages yet." message) — worth
  applying the same "try to find a supported link, then give real
  guidance" treatment there too, per the original ask.
- **5 of the first 12 Granicus test meetings returned zero caption
  segments** (San Diego County, Cupertino, Mountain View, Berkeley,
  Paradise Valley AZ). Not yet confirmed these meetings simply lack
  captions vs. a caption file existing elsewhere on the page that current
  extraction patterns miss. Needs investigation before assuming "no
  captions available" is the right conclusion.
- **Date extraction still fails for some meetings** even after the title
  extraction fix (San Diego, Berkeley, Alexandria VA, San Francisco, DC in
  initial testing). Scraping the clip page's static HTML is unreliable for
  JS-heavy Granicus pages; an RSS-feed-based metadata source (per
  `civic-scraper`'s Granicus adapter, which parses `ViewPublisherRSS.php`)
  may be more reliable than scraping the clip page directly.

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

- **Source caption quality varies wildly by jurisdiction and isn't
  detected.** Alexandria VA's captions (clip 6490) are genuinely garbled at
  the source — confirmed by fetching the raw VTT directly from
  `alexandria.granicus.com/videos/6490/captions.vtt`: fragments like "test
  meele first item on t" and "last meeting.Oa", not a parsing bug. Boston's
  captions (clip 10382), by contrast, are clean full sentences. We currently
  render whatever we find with no quality check. Need either (a) a
  heuristic to detect low-quality/garbled captions (e.g. abnormal fragment
  length, merged-word ratio) and warn the user or fall back to
  Whisper-generated transcription instead, or (b) at minimum, surface a
  confidence/quality indicator so users know not to trust a garbled
  transcript at face value.

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

- **San Francisco's captions render in ALL CAPS** (a live-caption source
  convention, not a bug) — reads as shouting. Consider normalizing to
  sentence case for display. Spot-checked the other 6 meetings with real
  transcripts (2026-08-06): 5 of 6 English ones (San Diego, Oakland,
  Boston, San Francisco, DC) are genuinely readable with only minor rough
  patches (a few garbled words mid-Boston); Alexandria VA remains the one
  clear outlier at genuinely unreadable quality — see the caption
  quality-detection item above.

## UX polish (from live review, 2026-08-06)

- Video embed defaults to an oddly short/cramped player size — should look
  like a normal video player's proportions, not whatever it's currently
  defaulting to.
- The play button isn't obvious enough on the video player.
- Preload a thumbnail/poster image for the video so there's something to
  look at before playback starts.
- There's an awkward pause after clicking play while the video loads.
  Consider preloading the video, or auto-playing briefly and immediately
  pausing, to smooth over that gap.
- Add a search box next to the transcript that mirrors Ctrl+F — filter/jump
  within the transcript text.
- Add a deep-link icon next to individual transcript lines — right now
  only the timestamp itself is clickable, which isn't an obvious
  "copy a link to this line" affordance.
- Let users type in a specific timestamp to deep-link to, not just click a
  transcript segment. Deep-linking to an exact moment is the primary goal
  of this app — the transcript is a nice-to-have — so this should work even
  when there's no (or poor-quality) transcript available for a meeting.
- On smaller monitors, when auto-scroll is on and the video is playing,
  the page keeps scrolling the transcript into view, making it hard to
  scroll back up to the toolbar to turn auto-scroll off. The toolbar
  (copy-link / auto-scroll toggle) should float/stick near the top of the
  page on scroll instead of disappearing.

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
