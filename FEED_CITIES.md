# "Feed cities" — should this app ever synthesize its own meeting pages?

An open strategic question, not a plan. Moved out of `BACKLOG.md`
2026-08-22 because it is a long piece of reasoning that belongs
read whole, not skimmed in a list.

Split out of [BACKLOG.md](BACKLOG.md) 2026-08-22; that file keeps a
short stub entry pointing here. Update both together.

---

**"Feed cities" — should this app ever
synthesize its own meeting pages for cities that have no well-defined
per-meeting page at all? Open strategic question, not a build item,
prompted by a 2026-08-12 pass through the 50 biggest US cities.** A
real, recurring pattern: a city publishes video as one big feed (a
YouTube channel, a Vimeo showcase list) and agendas as a *separate*
feed (a Granicus/ Legistar calendar) — never as one stable
government-hosted URL that's "the page" for one specific meeting with
both attached. Every adapter here assumes that stable per-meeting page
exists and just needs finding; these cities don't have one. Seen this
shape in: Seattle Channel, Phoenix/Philadelphia/Albuquerque's
Legistar-with-no-video-link case, Chicago ELMS's agenda API paired
with a separate Vimeo showcase, El Paso's per-body Vimeo showcase
directory.

**The idea, in the user's own words**: build a page ourselves that
indexes a city's video feed and its separate agenda feed, matches them
(e.g. by date), and creates a real, possibly-permanent meeting page on
*our* site combining both. The user's own framing: "in a way, this is
a PITA. In another way, these might be the most helpful pages we
create because there isn't a near duplicate on the government agency's
website" — every other page this app makes mirrors something that
already exists somewhere; a synthesized feed-matched page would be the
one case where the page genuinely doesn't exist anywhere else in this
form, a stronger value proposition with a correspondingly higher bar
for correctness.

**Real considerations, not yet decided on any of these:**
- **Match confidence is the central risk, not a side detail.** A
  date/title heuristic match *will* sometimes attach the wrong video
  to the wrong meeting — a sharper version of the fabricated-content
  risk the Trust & Safety section already threat-models for
  `generic_fallback`. Needs a real answer for "how confident is
  confident enough to publish," not just "best guess."
- **One-time historical backfill vs. an ongoing/scheduled pipeline are
  two very different sizes of commitment** — a one-time backfill for a
  fixed list of cities is bounded, closer to the existing
  `bulk_ingest.py` shape; an ongoing pipeline means continuously
  matching new videos to new agendas forever, with drift (a city
  changes its channel/vendor/cadence) silently degrading match quality
  with nothing forcing a human to notice.
- **Temporary vs. permanent doesn't have to be a single decision up
  front** — the existing `best_effort`/`generic_fallback` ephemeral
  flow already has a real lower-trust "visible but not permanent"
  pattern to borrow from.
- **Scale/cost is unscoped**: how many of the 50 cities actually hit
  this specific pattern (vs. the many other distinct gaps already
  logged separately), how many historical meetings per city, whether
  transcribing all of them is assumed as part of this — none counted
  yet.

**Next step is counting, not building** — go back through the 50-city
pass to tag which cities hit *this* pattern specifically, since this
entry is currently grounded in four real examples encountered
incidentally, not a real count.

**A real, promising extraction angle: WCAG/accessibility-driven
markup, not just date/title matching — checked directly against real
pages.** Government sites lean on standardized accessibility markup
more than most (Section 508 compliance is often a legal requirement).
Confirmed real: `<track kind="captions">` inside native `<video>`
elements on three separate real government pages; `<time
datetime="...">` with full ISO datetime *including time of day* on
Portland.gov (notably the exact missing piece from the `uploadDate`/
timezone finding above — this app doesn't capture meeting time-of-day
anywhere today); WCAG-required iframe `title` attributes, present and
descriptive on Portland but genericplaceholder on CRRMA — has to be
checked per site. **Real negative**: checked 7 real government pages
for schema.org/JSON-LD structured data — zero hits on all seven, unlike
the accessibility markup above.
