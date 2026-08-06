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

## Platform coverage

- **Legistar adapter** — per the note above, Legistar is generally a
  calendar wrapper around an underlying Granicus (or other) video link.
  Worth trying "find the embedded supported-platform link and delegate"
  before building a full independent Legistar video/caption parser.
- **CivicPlus adapter** — similar pattern to Legistar: often links out to
  Granicus for the actual video, per user's read of the space. Same
  delegation strategy may apply.
- **New platforms to test**: CivicClerk, eScribe, BoardDocs, Swagit —
  sample URLs added to the shared "Watchdog Sample meetings" sheet.
