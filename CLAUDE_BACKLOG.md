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
  before it.
