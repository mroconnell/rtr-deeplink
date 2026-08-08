# Backlog

Live items only, roughly in priority order. Completed work — including the
investigation detail behind each fix — lives in
[BACKLOG_DONE.md](BACKLOG_DONE.md); items below link back to it for context
where relevant.

## Bugs

- **A URL already cached in the resolver's local `meeting_resolutions`
  table never gets backfilled into the Archive.** `/api/resolve` checks
  the Archive first, then that local cache, then does a live resolve —
  but the "push to the Archive" step only runs on a *fresh live resolve*
  (see `app/main.py`). If a URL was already successfully cached locally
  before the Archive integration existed (or while its env vars were
  misconfigured — this happened for real, see
  [BACKLOG_DONE.md](BACKLOG_DONE.md)), every future resolve of that exact
  URL just serves the local cache and permanently never reaches the
  push step, so it can never become a permanent page on its own.
  Confirmed live via `psql`: Simi Valley's `meeting_resolutions` row has
  `hit_count: 3` and predates the Archive integration being wired up
  correctly. Not hypothetical — a real, silent gap for any URL resolved
  during this project's own bring-up period, and it'll recur for any
  future URL resolved while the Archive happens to be down. Needs either
  a one-time backfill pass (walk `meeting_resolutions`, push every
  `status="success"` row with real content to the Archive) or a change
  to the resolve flow so a local-cache hit can also opportunistically
  trigger a push if the Archive doesn't already have it — related to,
  but distinct from, the "opportunistic re-check on a permanent-page
  hit" item below (that's about refreshing an *existing* Archive page;
  this is about a page that never got created in the first place).
- **CivicClerk real caption/transcript format is unverified.** The API
  schema has `EventsMedia.closedCaptionUrl`, `.transcriptionUrl`, and
  `.closedCaptionTracks`, but every sample checked (Clovis CA, Highland CA,
  Lino Lakes MN) had these null/empty — `CivicClerkAssetFinder` just shows a
  "not verified yet" warning instead of parsing them. Needs a real example
  with populated caption data.
- **Alexandria VA meeting dates can't be extracted.** No `view_id` in the
  URL (so no RSS feed to cross-reference, unlike the rest of Granicus — see
  [BACKLOG_DONE.md](BACKLOG_DONE.md)) and no date signal anywhere in the
  page body either. No fallback source identified yet.
- **No UI to pick between multiple caption language tracks.** Language
  detection/selection auto-picks the best match and warns when it's not
  English (see [BACKLOG_DONE.md](BACKLOG_DONE.md)), but there's no way for
  a user to see or choose an alternate track when more than one exists.

## Platform coverage — open questions

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

## Archive roadmap

**Architectural context:** anything about content/audience rather than
resolving (permanent pages, search, accounts/billing, email alerts, the
transcription crawler) grows in a **separate app** ("the Archive"), not this
resolver — see [BACKLOG_DONE.md](BACKLOG_DONE.md) for the full reasoning.
The resolver/Archive seam is `get_cached_resolution`/`log_resolution` in
`app/db/crud.py` plus `archive_client.lookup()`/`.push()`.

- **Opportunistic re-check on a permanent-page hit.** Right now a
  permanent page's transcript is frozen at whatever quality it had on first
  push, even if the source later adds/improves captions. `TranscriptVersion`
  already supports multiple versions per page; what's missing is the
  trigger — background re-resolve on every hit vs. only for pages older
  than some age. Needs a cadence decision before building.
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
