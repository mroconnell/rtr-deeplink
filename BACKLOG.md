# Backlog

Known bugs and features not yet addressed, roughly in priority order.

## Bugs

- **Unsupported-platform failure is too blunt.** Right now an unsupported
  platform (e.g. Legistar) just returns "We don't support 'legistar' meeting
  pages yet." — but Legistar pages are usually a *calendar* that links out
  to the actual meeting video, often hosted on Granicus (which we do
  support). Before giving up, try to find and follow an embedded link to a
  supported platform on the page. If that still fails, replace the raw
  message with actual guidance instead of a bare error, e.g.:
  > "We didn't find a meeting at that URL. A common snafu is pasting a
  > calendar link instead of the link to the specific page where the video
  > is embedded. If that's not it, we've logged this and will dig in.
  > Subscribe for an alert when it's fixed."
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

- **Jurisdiction/title metadata needs cleanup.** Jurisdiction is derived by
  title-casing the URL subdomain (e.g. `sandiego` &rarr; "Sandiego"), which
  doesn't insert word breaks for multi-word city names — should read "San
  Diego". Title comes straight from the page's HTML title/og:title (e.g.
  "Tuesday Agenda Revised Added S500-S504" for a San Diego City Council
  meeting) and often doesn't include the governing body — should try to
  surface something like "San Diego City Council" rather than whatever
  string the source page happened to title itself.

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

- **Legistar adapter** — per the note above, Legistar is generally a
  calendar wrapper around an underlying Granicus (or other) video link.
  Worth trying "find the embedded supported-platform link and delegate"
  before building a full independent Legistar video/caption parser.
- **CivicPlus adapter** — similar pattern to Legistar: often links out to
  Granicus for the actual video, per user's read of the space. Same
  delegation strategy may apply.
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
