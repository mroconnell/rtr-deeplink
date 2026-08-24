# State pages and jurisdiction hubs

How `/state/{slug}` and `/j/{slug}` work, why they are built this way, and
what is worth doing next.

Written 2026-08-23, when both surfaces were rebuilt around real quoted
transcript text (WO-46). `README.md` carries the summary; this file is the
detail behind it. `BACKLOG.md` holds the live follow-ups, and
`BACKLOG_DONE.md` the original investigation.

---

## 1. Why these pages were rebuilt

Search Console showed ~585 non-indexed URLs, rising. Categorising the
"Crawled – currently not indexed" set against `sitemap.xml` found Google
**selectively declining hub pages**:

| Page type | Share of non-indexed URLs vs. their sitemap share |
| --- | --- |
| `/j/` jurisdiction hubs | **3.6×** over-represented |
| `/state/` state pages | **3.1×** over-represented |
| `/m/` meeting pages | **0.5×** — indexed *better* than their share |

That asymmetry is the whole argument. Crawl-budget exhaustion and domain
age would suppress everything roughly proportionally; they don't explain
one page type being declined while another on the same domain is
accepted. What was left is thin, templated, near-duplicate content.

A meeting-count threshold was tested as a fix and **ruled out by
measurement**, not opinion: against the full 291-row export, the median
hub showed two meetings whether Google indexed it or not, and any
threshold strong enough to catch the flagged pages suppressed essentially
the whole hub surface.

So the fix had to be *content*. A list of meeting titles is templated. A
resident explaining why they drove down at 9pm is not.

**This has not yet been proven to work.** See §7.

---

## 2. What a page shows now

Both surfaces share the same components, in this order:

1. **Summary lede** — counts of meetings and governments, plus a
   freshness line ("168 added in the last 7 days").
2. **Topic chips** — curated subjects present in this page's recent
   meetings, as real `?topic=` links.
3. **Featured meetings** — a genuine transcript quote per meeting, deep
   linked to the second it was said, with the stored video frame from
   that moment.
4. **Most watched governments** (state pages only).
5. **Government list** — grouped by kind; a sticky sidebar on desktop,
   below the results on mobile.

State pages show 12 featured cards, hubs show 6 — a hub is one
government, so after a handful the full meeting list below serves the
reader better.

---

## 3. How a snippet gets picked

`archive/utils/highlights.py`. The hard part is that **there is no
query**. `archive/utils/search.py`'s `find_snippet()` /
`find_matching_segment()` answer "where does this term appear"; here
nobody typed anything and the page still has to choose.

So every candidate window is scored, and the winner is stored.

### Windowing

A window is ~`TARGET_CHARS` (220) of consecutive segments — about two
spoken sentences. Windows start only at sentence-ish boundaries and slide
**one segment at a time** rather than tiling, so a good moment isn't
missed for straddling a fixed boundary. `_trim_to_sentence()` cuts at the
*first* sentence end past ~60% of target, so a quote stops once it has
said something complete instead of running into whatever followed.

Many caption tracks carry no sentence punctuation at all. For those,
`>>` (the near-universal speaker-change marker) is the only boundary
available, and the character cap at `MAX_CHARS` (420) is the fallback.

### Scoring

`score_window()` is deliberately plain arithmetic, not a model call: it
runs for every meeting at ingest, must be deterministic so a re-run
doesn't churn stored text, and has to be **explainable when a bad snippet
reaches a public page** — which has already happened twice.

| Signal | Weight | Why |
| --- | --- | --- |
| Procedural language | **−3.0 each** | Roll call, "motion", "all in favor", "you have three minutes". This is most of a meeting by volume, so a naive "first/longest window" lands here nearly every time. |
| Civic substance | +1.5 each | Dollar figures, "residents", "concerned", "taxpayers", percentages. |
| Curated topic hit | +2.0 each | Strongest available signal, and the reason a snippet is worth showing. |
| After public comment | +3.0 once | Where the quotable moments live. |
| Sentence length | up to +3.0 | Rewards fuller sentences; flat for unpunctuated tracks. |
| Low unique-word ratio | −5.0 | Stuck captions, hallucination loops. |
| Repetition guards | −6.0 each | See below. |
| Starts mid-sentence | −1.0 (implicit) | A capitalised start gets +1.0. |

Ceremony is skipped outright: the first `SKIP_HEAD_FRACTION` (8%) and
last `SKIP_TAIL_FRACTION` (3%) of the meeting. A window under `MIN_WORDS`
(25) is rejected — not enough context for a reader.

### The two coherence guards

`_repetition_penalty()` exists because in-browser verification surfaced
two bad snippets that **offline dry runs had not**:

- **A hammered content word.** Mission Viejo produced "…it talks about
  the personal data and it says personal data includes personal data,
  personal information, personally identifiable", where one word was 24%
  of the content. Good snippets in the same sample topped out at 15%, so
  the threshold is 18%.
- **A repeated content-bearing phrase.** Interleaved roll-up captions
  restate a phrase out of order ("Five flock data will", San Diego).
  Trigrams made only of function words are **exempt** — "as well as"
  recurring is ordinary English and appears in perfectly good snippets.

Both thresholds were set by measuring good *and* bad snippets from the
same render. The real strings are frozen in `tests/test_highlights.py`;
changing the scoring without re-running them is how a fix for one meeting
silently ruins twenty.

---

## 4. Why snippets are stored, not computed

`meeting_highlights` (one row per page) holds the default highlight plus
`topic_moments` — the best moment for each topic present anywhere in the
meeting.

The heuristic needs the meeting's **segments**, and a long meeting's
segment JSON is a six-figure-byte blob (San Diego's Board of Directors:
6,313 segments; the largest in the archive: 36,072). A state page
features a dozen meetings and a crawler walks every topic × state
combination — so computing on demand would decode megabytes per render on
the exact surface built *for* crawlers. Storing turns all of it into one
indexed row read, and makes a `?topic=` view a pure table read with no
transcript load at all.

**Kept in sync from `crud._refresh_search_corpus()`** — the same single
choke point that already recomputes `search_corpus` and upserts
`search_vocabulary`. Every path that creates a `TranscriptVersion`
already reaches it, so a highlight cannot silently go stale the way the
pre-2026-08-17 corpus did when a Whisper transcript finished after the
page's last ingest.

**The write is wrapped in a SAVEPOINT.** `_refresh_meeting_highlight()`
runs inside the *ingest* transaction, so an unguarded failure would roll
the transcript back with it — trading a missing snippet for a lost
transcript, which is strictly worse. A plain `try/except` is not enough:
on Postgres a failed statement poisons the surrounding transaction until
rollback, so catching and continuing would still fail at `commit()`.
`begin_nested()` scopes the damage.

A page with nothing quotable simply has **no row**, and every consumer
renders fine without one. Measured: 1,628 highlights from 2,464 pages —
of the 1,722 with transcripts, **5.5% had nothing quotable**.

### Performance

The first backfill run did not reach 100 pages in 10 minutes. Profiling
found three real causes, all since fixed:

1. `_candidate_windows()` ran **twice** per meeting (once per picker).
2. The backtracking repeated-phrase collapse and the all-caps scan ran on
   **all ~26,000 windows** instead of the handful returned.
3. Scoring ran **20 separate topic regexes** per window where one combined
   alternation answers the same question (`topics.any_topic_pattern()`).

Result: the three largest transcripts went from **14.1s to 3.1s (4.5×)**,
and a 260-page backfill from hours to minutes.

---

## 5. Topics

`archive/topics.py` is **meant to be edited by hand**. It is the one
place deciding which phrases get counted, ranked into chips, and
highlighted.

**Discovery is deliberately not unsupervised.** An unsupervised
"trending terms" pass over council transcripts surfaces `item`,
`supervisor`, `motion` — the vocabulary of procedure, not of subject
matter. Ranking a *curated* list by real corpus hits gets the useful half
of "trending" without the noise.

**Topics overlap on purpose.** `flock-cameras` was split out of
`surveillance-cameras` so Flock — a named vendor residents show up to
speak about by name — has its own findable chip. But Flock terms remain
in `surveillance-cameras` too, because Flock *is* surveillance and a
reader clicking either chip should find those meetings. A first pass made
them disjoint and silently removed every Flock meeting from the
surveillance chip.

**Pinned topics** (`Topic.pinned`) keep a chip below the count cutoff.
`data-centers` and `flock-cameras` are surfaced for being *newsworthy*,
not frequent — and both measurably lose a pure popularity contest:

| Topic | Meetings (archive-wide) |
| --- | --- |
| Property taxes | 450 |
| Libraries & parks | 422 |
| Schools | 385 |
| Housing & development | 377 |
| Homelessness | 364 |
| … | … |
| Data centers | 138 mentions |
| Flock cameras | 131 mentions |

Pinning never overrides the `count > 0` rule: a chip leading to an empty
page is worse than no chip.

**`TOPICS_VERSION`** is bumped whenever the phrase lists change in a way
that should invalidate stored rows. Stored highlights then self-identify
as stale and `scripts/backfill_meeting_highlights.py` re-runs exactly
those. Adding a `Topic` counts; fixing a typo in a `label` does not.

**Patterns are checked against the real corpus before shipping.** The
bare `flock` pattern is the obvious false-positive risk ("a flock of
geese"), so it was measured: 131 meetings mention it and **all 14** stored
highlights containing it are about the company. `flocks` is included
because transcription reliably produces it.

---

## 6. Rendering rules

### Diversity cap

Featured sets are date-ordered but at most `MAX_FEATURED_PER_TOPIC` (2)
cards may share a topic. The case that prompted it: San Diego's hub
showed two cannabis cards and two housing cards while a public comment
delivered *in character as Darth Vader* about flock-camera surveillance
sat in the same pool. Recency alone had no way to prefer it.

Implemented as **two passes, not a sort**, so the cap reorders without
ever shrinking the set — a page whose meetings genuinely all share one
topic still fills up. Cards with no topic are never constrained (they
cannot cluster, and excluding them would bias the page toward
topic-tagged meetings). A `?topic=` view is exempt: every card there is
about that topic by construction.

### One mark per snippet

`MAX_MARKED_TOPICS` is **1**, the rarest topic on the card. The Darth
Vader quote also matched `libraries-parks` on the word "playground" and
rendered with `flock` highlighted twice and **"playground" three times**,
burying the word the reader came for.

A rarity-*ratio* filter was tried first and **rejected by measurement**:
rarity is counted over the page's own pool, and in a six-meeting hub pool
both topics have a count of 1, so no ratio can separate them. Marking one
topic needs no archive-wide count query, and the tiebreak falls through to
curated `TOPICS` order — which is roughly newsworthiness-ordered and does
the real work at that scale.

### Untitled pages are never featured

A card headed "Untitled meeting" is fine in a dense list but reads as
broken as a *featured* card on an indexed page — and featuring is
optional, so `_featured_entry()` declines rather than publishing a
placeholder. A render-time guard, not a fix: the rows still want
re-resolving.

### Government grouping

`archive/utils/gov_classify.py` sorts each government into County /
City / School / Agency. It trusts `MeetingPage.meeting_body` where that
says something conclusive, falls back to the jurisdiction name, and
**defaults conservatively to city** — a special district misfiled as a
city is a mild inaccuracy; a city misfiled as a county reads as an error.

### Layout

Two panes on desktop (`min-width: 992px`), one column below it. The
sidebar is **after** the main pane in source order, so mobile gets
snippets first and the long list after. The government list is never
JS-collapsed: every `/j/` link stays in the initial HTML, because
internal links to the hubs are part of what this page is *for*. Topic
chips become a horizontal scroll strip on phones, where a dozen wrapped
chips would push results a full screen down.

### Structured data

`CollectionPage` + `BreadcrumbList` + an `ItemList` of `VideoObject`s.
`thumbnailUrl` is emitted **only** where `crud.pages_with_thumbnails()`
confirms a stored frame — advertising a card URL that would 404 is worse
than advertising none, the same rule `/m/{slug}` follows for `og:image`.

Canonical stays the **bare** state/hub URL even under `?topic=`: the
topic views are real, crawlable, server-rendered variants worth
following for their snippets, but they are alternate cuts of one page's
content, not separate pages competing for the same query.

---

## 7. Tuning reference

| Constant | Value | File |
| --- | --- | --- |
| `TARGET_CHARS` / `MAX_CHARS` | 220 / 420 | `utils/highlights.py` |
| `SKIP_HEAD_FRACTION` / `SKIP_TAIL_FRACTION` | 0.08 / 0.03 | `utils/highlights.py` |
| `MIN_WORDS` | 25 | `utils/highlights.py` |
| `PUBLIC_COMMENT_BONUS` | 3.0 | `utils/highlights.py` |
| `STATE_HIGHLIGHT_POOL` | 150 | `db/crud.py` |
| `STATE_FEATURED_COUNT` / `HUB_FEATURED_COUNT` | 12 / 6 | `db/crud.py` |
| `MAX_TOPIC_CHIPS` | 12 | `db/crud.py` |
| `MAX_FEATURED_PER_TOPIC` | 2 | `db/crud.py` |
| `MAX_MARKED_TOPICS` | 1 | `db/crud.py` |
| `MOST_ACTIVE_MIN_GOVERNMENTS` / `_WINDOW_DAYS` / `_COUNT` | 8 / 90 / 6 | `db/crud.py` |
| `FRESHNESS_WINDOW_DAYS` | 7 | `db/crud.py` |
| `JURISDICTION_HUB_MIN_INDEXABLE` | 2 | `db/crud.py` |

`STATE_HIGHLIGHT_POOL` is a *recent* pool on purpose: "which subjects are
live here right now" is the useful question, and an all-time count would
be dominated by whichever jurisdictions happened to be bulk-ingested
first.

---

## 8. Verifying a change

1. **Run the four CI gates** — `ruff check`, `ruff format --check`,
   `python -m pytest`, `alembic check`. See `CLAUDE.md`; a green pytest
   says nothing about the first two, which run first.
2. **Re-run the frozen snippet cases** in `tests/test_highlights.py` if
   you touched scoring.
3. **Look at a rendered page.** Both coherence guards and the
   one-mark-per-snippet rule exist because of things that were invisible
   in offline dry runs and obvious in a browser. Seed a local SQLite from
   production (read-only) and mount the Archive behind a wrapper that
   serves `/archive-static` — a standalone `archive.main:app` serves no
   stylesheet, and an unstyled page gives confident, wrong measurements.
   See `CLAUDE.md`.
4. **Backfill on Render, never from a laptop** against production. See
   `CLAUDE.md`; running it locally pulls every segment blob across the
   network.

---

## 9. What's worth doing next

Live follow-ups are in `BACKLOG.md`; this is the reasoning behind them.

**Measure whether any of this worked.** `[WAIT]` — the open question.
Needs a Search Console export a few weeks out, measured **against the
3.6× / 3.1× over-representation figures, not the raw non-indexed count**,
which moves with corpus growth and cannot answer this on its own.

**Rank topics by real demand.** `search_queries` now logs every
`/meetings` keyword with **no user identity at all** — keyword, optional
jurisdiction filter, result count, timestamp; no IP, user id, session or
user agent, which for a site about scrutinising local government is a
meaningful thing not to hold. `crud.top_search_keywords()` reads it.
Nothing ranks chips by it yet because there is no data until the table
fills. This is the natural successor to the curated list: keep curation
for *what counts as a topic*, use demand for *which chips show*.

**Fluently-wrong transcriptions still produce garbled snippets.** The
coherence guards catch a hammered word and an interleaved roll-up phrase,
but a plausible-sounding mistranscription (real example, Santa Rosa:
"brought for their concerns and need for essential anti displacement home
parks and aims of protections for the mobile emergency concerns") has no
repetition signal. Detecting it needs a coherence model, not a regex —
threshold attempts misfire on good snippets, measured. The honest framing
is that this is transcription quality surfacing, not snippet selection
failing.

### Put the chips and the moments feed on the home page

**Proposed 2026-08-23 by Ryan**, after seeing the rebuilt state pages:
the "being discussed" chips, the recent-moments feed, and the column of
jurisdictions, sitting on `/` directly below the instructions for the
lookup field.

Worth taking seriously. The home page currently explains a *tool* and
shows nothing of the archive behind it — a visitor who has no meeting URL
to paste has nothing to do there. These three components are exactly what
turns it into something you can browse, and they are the only content on
the site that is both unique and skimmable. It is also the highest-value
page on the domain for indexing.

**The main design question is a service boundary, not a UI one.** The
home page is rendered by the **resolver** (`app/main.py`'s `index()` →
`app/templates/index.html`), while every piece of this machinery lives in
the **archive** service — `meeting_highlights`, `archive/topics.py`,
`crud._build_featured()`, and the two shared Jinja includes
(`archive/templates/_topic_chips.html`,
`archive/templates/_featured_meetings.html`). Three ways across, roughly
in order of preference:

1. **An Archive fragment/JSON endpoint the resolver calls server-side.**
   Cleanest boundary and reuses the existing includes as-is, but adds a
   network hop to the busiest page on the site. Would need a short
   in-process cache on the resolver side, and a degrade-to-nothing path
   so an Archive blip can never take the home page down — the resolver
   already treats the Archive as optional everywhere else, and that
   posture must not regress here.
2. **Read the shared Postgres directly from the resolver.** Both services
   point at the same database, so this is possible and avoids the hop. It
   does mean `app/` importing Archive models; note the reverse import
   already exists (`archive/db/crud.py` imports
   `app.utils.jurisdiction_enrich`), so the boundary is already not
   absolute — but that one is a pure utility module, and this would be a
   schema dependency, which is a different thing.
3. **Proxy a whole rendered fragment.** Simplest to ship, worst to
   maintain; mentioned only so it is visibly considered and rejected.

**Scope changes at national level**, and this is the part worth designing
rather than assuming:

- **The pool.** `STATE_HIGHLIGHT_POOL` (150) is per state. Nationally the
  same query returns the newest 150 transcribed meetings overall, which
  will skew toward whichever jurisdictions were bulk-ingested most
  recently. The diversity cap (§6) helps but was tuned for a
  single-state pool; a **per-jurisdiction** cap probably matters more
  than the per-topic one here, or the feed becomes six Oklahoma City
  meetings.
- **The jurisdiction column.** 574 governments is not a sidebar. The
  state-page grouping (County/City/School/Agency) does not reduce it
  enough either. More likely: group **by state** and link to
  `/state/{slug}`, which also makes the home page a real hub for the
  state pages — an internal-linking win precisely where the indexing
  problem in §1 lives.
- **Caching is not optional.** This is the highest-traffic page; the
  per-request work that is fine on a state page is not fine here.

**Cheap first step**: ship it as *national* chips plus a moments feed
only, no jurisdiction column, behind a cache. That tests whether the
format works on the home page before anyone designs the 574-government
navigation problem.

### Search results got the card treatment — built 2026-08-24 (WO-48)

**It came out of asking whether user-suggested topics would just be
reinventing search (2026-08-23).** The answer turned out to be the
reverse: search was not reinvented here, it was *out-designed*, and it
has now adopted the better presentation.

What `/meetings` shows, before and after:

| | before | now | featured card |
| --- | --- | --- | --- |
| Snippet | query-matched | query-matched *(unchanged)* | heuristic-picked |
| Deep link to the moment | **no** | yes | yes |
| Timestamp label | **no** | yes | yes |
| Video frame at that moment | **no** | yes | yes |

**The snippet stayed query-matched, deliberately.** A search result's job
is showing *why this matched*, which the query-matched excerpt does and a
heuristic pick does not. What got borrowed is the deep link, the
timestamp and the card — never the selection.

**This was far cheaper than this section originally claimed, and the
claim was wrong in an instructive way.** It used to warn that
`find_matching_segment()` "needs the meeting's segments, which
`list_pages()` deliberately does not load (§4's whole argument)", and
that doing this would re-introduce per-render blob decoding on a
paginated page. In fact `list_pages()` **already loaded** the default
version's full `segments` for the current page of rows whenever a keyword
was set — `find_snippet()` simply joined them and discarded the segment
boundaries. The timestamp was a free by-product of text the query paid
for regardless. §4's argument is about *hub* pages, which render without
a keyword and genuinely load no segments; it was over-generalised to a
page it never covered. Worth remembering as a shape: a doc's *reasoning*
outlives its *specifics*, so re-derive the specific before building on it.

**Two things only the browser caught**, neither visible in the JSON:

- **A cue is not a sentence.** A caption cue runs 5–10 words, so quoting
  the matched segment alone made snippets *shorter* than the old
  blob-based ones — a regression traded for the deep link.
  `SEARCH_CONTEXT_SEGMENTS` folds in the neighbouring cues.
- **…but neighbouring cues are not neighbouring moments.** A sparse
  transcript put "…then we will begin" (0:05) directly beside a sentence
  spoken at 10:40, and joining them rendered a continuous-sounding quote
  nobody ever said. `SEARCH_CONTEXT_MAX_GAP_SECONDS` stops the window at
  a real gap. A misleading quote is a worse failure than a short one, and
  on this site it is the failure that matters most.

Cards are emitted only for keyword searches (the bare browse listing
stays the compact one-line-per-meeting listing), only when
`pages_with_thumbnails()` confirms stored bytes, and never warm a miss —
a crawler paging through results would otherwise fire a page's worth of
ffmpeg jobs per request. There is deliberately **no JSON-LD** on
`/meetings`: every filtered variant canonicalizes to the bare unfiltered
URL, so structured data there would describe a page pointing its
canonical elsewhere.

### Topic suggestions from readers — mostly already solved

**Proposed 2026-08-23; recorded here with the reasoning against, so it
isn't rebuilt from scratch later.** The idea: let readers suggest a
phrase for `archive/topics.py`, preview what it would surface, and have a
human approve it per state.

Two halves, and both are already covered:

- **"Show the reader their topic in real time"** is `/meetings?q=...`.
  That is search, and it already works.
- **"Collect suggestions to decide what to curate"** is what
  `search_queries` does (§9, added 2026-08-23) — *passively*. A form is a
  worse instrument for the same signal: far lower volume, and it records
  what people say they want rather than what they actually looked for.
  Zero-result searches, the single best source of candidate topics, are
  already captured via `result_count`.

**What is genuinely missing is the human decision workflow, not the
input.** The useful build is an *internal* view that ranks candidate
phrases out of `search_queries` (frequency, zero-result rate, not already
a topic) and, for a chosen phrase, previews what adding it would surface
— which is `topics_in()` plus a corpus count, not new machinery. That
keeps curation human, which §5 argues for, without asking readers to fill
in anything.

**Ideas not yet built**, roughly by value:

- **Per-meeting-body diversity**, alongside per-topic — a hub whose
  featured set is six City Council meetings could show the Planning
  Commission and the school board instead.
- **A snippet for the `og:description`** — these pages have real quotable
  text now and still share as generic boilerplate.
- **Let a hub inherit its state's chips** when its own pool is too thin
  to produce any, so small hubs get a way in rather than nothing.
- **Surface press coverage** beside a meeting: a small curated
  `press_mentions` table (headline, outlet, URL, meeting) rendered on
  `/m/`, `/j/` and state pages. Deferred 2026-08-23 because no outlet
  links to us yet; the reverse — a journalist using the tool and citing
  the meeting — has already happened at least once.
- **A Wikipedia one-liner per jurisdiction** (CC BY-SA, public REST API).
  Cheap and safe, but *duplicate* content from Google's perspective, so
  it supports the page rather than helping it index. Low value; listed so
  the next person doesn't re-derive the trade-off.

**Deliberately declined** — see `BACKLOG.md`'s Standing decisions before
re-proposing: a meeting-count threshold for hub indexability (ruled out
by measurement, §1), and unsupervised topic discovery (§5).
