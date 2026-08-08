# Claude-generated Backlog

Ideas proposed by Claude on 2026-08-07, after reviewing the full `BACKLOG.md`
and current repo state, specifically to avoid duplicating anything already
tracked there. Not yet reviewed/prioritized by the user — treat this as a
suggestions list, not a committed roadmap. Once an item is accepted, move it
into `BACKLOG.md` proper (in that file's style) rather than marking it done
here.

## Reliability / engineering health

- **Fixture-based regression test suite.** Save real HTML/VTT responses per
  platform (Granicus, Legistar, CivicPlus, CivicClerk, Swagit, eScribe,
  PrimeGov/YouTube, CA Legislature) as test fixtures and write pytest tests
  against them. Right now every adapter change gets re-verified by manually
  hitting live government sites each session — slow, and it doesn't protect
  against silent regressions between sessions (e.g. a later change to
  `_extract_media_urls` breaking Mountain View's fix without anyone noticing
  until a user hits it). Confirmed live: there is no test suite anywhere in
  the repo today (only third-party package tests under `.venv`).
- **Adapter health canary / synthetic monitoring.** A scheduled job that
  re-resolves ~1 known-good sample URL per platform on a timer and alerts
  (email to Ryan, or a Slack webhook) on failure. Given how many real
  breakages have already surfaced this way — Mountain View's redirect bug,
  YouTube's caption-fetch blocking, yt-dlp being an unpinned moving target —
  better to find out from a canary than from a user's dead link.
- **Error monitoring (Sentry or similar)** in both the resolver and Archive,
  beyond the current `logger.error` calls — production exceptions currently
  only surface if someone happens to check Render logs.
- **Rate limiting on `/api/resolve`.** It's a public, unauthenticated
  endpoint that fans out to scrape government sites — worth throttling both
  to be a good citizen toward those sites and to protect the Render bill
  from abuse/bots.

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
- **schema.org `VideoObject`/`Event` structured data** on permanent pages,
  for potential rich-result eligibility in Google search. Distinct from the
  `sitemap.xml` item already in `BACKLOG.md` — that's discovery, this is
  presentation once discovered. Confirmed live: no `application/ld+json`
  anywhere in the repo today.

## Utility for the actual audience

Journalists, watchdog orgs, researchers — the people `BACKLOG.md`'s "manual
transcription" contact CTAs and the civic-scraper research were already
oriented toward.

- **Transcript export** (TXT/SRT/PDF download) from a resolved or archived
  meeting page — a standard ask for anyone doing real research or reporting
  off a meeting.
- **RSS/Atom feed of newly-archived meetings**, optionally filterable by
  jurisdiction — lets a local watchdog group or reporter subscribe instead
  of checking back manually.
- **Read-only public API with API keys**, sitting on top of the Archive
  once search/filters exist (per `BACKLOG.md`'s roadmap). Civic-tech orgs —
  the `civic-scraper`/OpenGov community already evaluated for this project —
  are a natural audience to build on top of resolved data rather than
  duplicate the scraping work themselves.
- **"Report a problem with this meeting" feedback control** on resolved/
  archived pages — crowdsourced signal pointing at specific adapter
  failures, cheaper than manually re-testing a dozen cities per session.

## Reach

- **Lightweight jurisdiction "follow" (email-only, no account).** A
  magic-link-style "notify me when a new X meeting is archived" that
  doesn't require the full accounts+billing system already scoped in
  `BACKLOG.md`'s roadmap — much smaller than that item and could ship well
  before it.
- **Mobile installability (PWA manifest).** Civic engagement around a
  specific meeting is often a mobile, in-the-moment action; making the site
  "Add to Home Screen"-able is cheap relative to a native app.

## Suggested priority

Test suite and canary monitoring rank highest — the app's core value is
"scraping keeps working across dozens of independently-changing government
platforms," and every session so far has found real breakage by hand rather
than by any automated signal. Everything else here is a genuine feature gap,
not a structural risk.
