# Claude-generated Backlog

Ideas proposed by Claude on 2026-08-07, after reviewing the full `BACKLOG.md`
and current repo state, specifically to avoid duplicating anything already
tracked there. Not yet reviewed/prioritized by the user — treat this as a
suggestions list, not a committed roadmap. Once an item is accepted, move it
into `BACKLOG.md` proper (in that file's style) rather than marking it done
here.

**Status (2026-08-08):** 6 of the original 12 items are done — test suite,
rate limiting, schema.org markup, transcript export, RSS feed, and
report-a-problem all shipped, each with real bugs caught along the way (see
`BACKLOG_DONE.md`'s entries dated 2026-08-07/08 for the full writeups). This
file now holds only the 6 still-open ones.

## Reliability / engineering health

- **Adapter health canary / synthetic monitoring.** A scheduled job that
  re-resolves ~1 known-good sample URL per platform on a timer and alerts
  (email to Ryan, or a Slack webhook) on failure. Given how many real
  breakages have already surfaced this way — Mountain View's redirect bug,
  YouTube's caption-fetch blocking, yt-dlp being an unpinned moving target —
  better to find out from a canary than from a user's dead link. Still the
  highest-value remaining item: the test suite protects against
  *regressions* on known-good cases, but won't catch a government site
  changing its page structure out from under a working adapter, which is how
  every real breakage so far has actually been found.
- **Error monitoring (Sentry or similar)** in both the resolver and Archive,
  beyond the current `logger.error` calls — production exceptions currently
  only surface if someone happens to check Render logs. A smaller,
  complementary piece of the same reliability gap as the canary above.

## Growth mechanics

Ties directly to the app's stated growth mechanism: shareable deep link →
organic growth (see `BACKLOG.md`'s roadmap intro and the newsletter/GA
items).

- **Social share previews with an image.** `archive/templates/
  meeting_page.html` currently has `og:title`/`og:description`/`og:url` but
  no `og:image` or `twitter:card` — a shared deep link currently renders as
  a bare text card on Slack/Twitter/iMessage. Worth generating a simple
  share-card image (jurisdiction + meeting title + maybe a quoted
  transcript line) server-side.
- **Quote-clip sharing.** Let a user select a transcript excerpt and
  generate a shareable image/card of that quote + timestamp + a link back
  to that exact moment — a much stronger viral unit than a bare link, and
  journalists/advocates already do this manually with screenshots.
- **Newsletter subscribe copy is generic — could be more specific about
  what a subscriber actually gets.** Current copy (`app/templates/
  subscribe.html`, `app/templates/base.html`'s footer prompt): "Get
  notified about new features and tools for finding public meetings."
  Inspiration flagged by the user (2026-08-09): Vikram Oberoi's
  citymeetings.nyc (see BACKLOG.md's NYC/Viebit entries for how this came
  up) uses "Highlights of meeting moments and curious claims every 1-2
  weeks" — concrete, content-focused, and sets a real cadence expectation,
  vs. our vague "new features" framing. Worth rewriting once there's
  actually a recurring content cadence to describe honestly (a newsletter
  promising specific content needs to actually deliver it) — not just a
  copy swap today.

## Utility for the actual audience

Journalists, watchdog orgs, researchers — the people `BACKLOG.md`'s "manual
transcription" contact CTAs and the civic-scraper research were already
oriented toward.

- **Read-only public API with API keys**, sitting on top of the Archive
  once search/filters exist (per `BACKLOG.md`'s roadmap). Civic-tech orgs —
  the `civic-scraper`/OpenGov community already evaluated for this project —
  are a natural audience to build on top of resolved data rather than
  duplicate the scraping work themselves.

## Reach

- **Lightweight jurisdiction "follow" (email-only, no account).** A
  magic-link-style "notify me when a new X meeting is archived" that
  doesn't require the full accounts+billing system already scoped in
  `BACKLOG.md`'s roadmap — much smaller than that item and could ship well
  before it. Its core mechanism (email address, confirm once via a
  clicked link, frictionless after that) is now proven out for real —
  on-demand transcription (built 2026-08-08, see `BACKLOG_DONE.md`) uses
  exactly this pattern for its own email step, so building this would
  mostly mean reusing `archive/utils/email.py`'s confirmation-email/
  audience-membership functions for a different trigger, not inventing
  the mechanism from scratch.

## YouTube transcript acquisition — further-out ideas

From the 2026-08-10 analysis session that produced the transcript-wanted
queue + local fetcher (see BACKLOG_DONE.md); these are the not-chosen
options worth remembering if the local-script approach ever stops
scaling.

- **A visitor-powered "contribute this transcript" bookmarklet.** A
  plain button on our page *cannot* fetch YouTube captions from the
  visitor's browser — CORS blocks cross-origin reads regardless of IP.
  But a bookmarklet clicked *while on the youtube.com watch page itself*
  runs same-origin: it could call the same InnerTube endpoints the
  page's own "Show transcript" panel uses (visitor's residential IP,
  visitor's session) and POST the result to a new Archive endpoint.
  Flow: meeting page says "no transcript yet — help us get it" → deep
  link to the video on YouTube → visitor clicks the (once-installed)
  bookmarklet → transcript lands in the Archive. Real challenges before
  building: an inbound public submission endpoint needs real abuse
  hardening (validate segment monotonicity/density against the video's
  known duration, land as a non-default version pending review, rate
  limit), bookmarklets are a power-user ask, and browser CSP handling of
  `javascript:` URLs varies. A browser extension is the heavier,
  more-legitimate version of the same idea. Neither is worth building
  while one person running one script covers the volume.
- **Residential-proxy or third-party transcript API fallbacks** (Bright
  Data-style proxies for server-side yt-dlp; Supadata/SearchAPI-style
  paid transcript APIs). Both work without any local machine, both cost
  real money per month/call, and both outsource a ToS-gray dependency.
  The decision record and per-option tradeoffs live in BACKLOG_DONE.md's
  2026-08-10 experiment entry; revisit only if the local script becomes
  the bottleneck.

## On-demand transcription follow-ups

Both raised directly by the user alongside the original transcription
request, deliberately not built as part of it — see `BACKLOG_DONE.md`'s
2026-08-08 entry for the full feature this extends.

- **Speaker diarization + a UI to map detected speakers to real names —
  confirmed 2026-08-09 as a good future feature, journalistic-value
  framing added.** For journalistic use, an unattributed quote is much
  weaker than one that can be cited as "Councilmember X said..." — this
  is the difference between a transcript being a navigation aid and being
  a citable source. The transcription pipeline already uses self-hosted
  `faster-whisper` specifically because it's the same base model WhisperX
  builds real diarization on top of (via `pyannote.audio`) — and
  `TranscriptSegment` (`app/platforms/models.py`) already carries an
  unused `speaker` field for exactly this, added cheaply now rather than
  needing a schema touch later, so this is additive to the existing data
  model, not a redesign. Real work still needed: running the diarization
  pass itself (a real compute/latency cost on top of transcription — size
  it before committing), and a UI for someone to label "Speaker 1" as an
  actual name (per meeting, or per recurring seat/role if a
  jurisdiction's council composition is known) — no design started on
  that UI yet. Real name resolution is the harder, longer-term half of
  this — worth explicitly sequencing unlabeled diarization first (ship
  "Speaker 1 vs. Speaker 2" attribution on its own) rather than blocking
  the whole feature on solving name-mapping too.
- **Compare the finished transcript against the meeting's agenda for
  topic-coverage accuracy.** E.g. flag agenda items that don't seem to
  have been discussed, or roughly locate where each agenda item's
  discussion starts in the transcript beyond what the source's own
  chapter markers (when present) already provide. No design started —
  open questions include what "coverage" even means precisely (exact
  phrase match against agenda text would miss most real discussion,
  which paraphrases rather than reads the agenda aloud) and whether this
  needs an LLM pass over the transcript or something simpler.
