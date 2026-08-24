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

**Which cap applies is a property of the surface (WO-49, 2026-08-24).**
The three caps answer different questions and the wrong one actively
hurts. A **hub** is one government with many bodies, so it caps per
`meeting_body` (`MAX_FEATURED_PER_BODY`) — six City Council cards while
the Planning Commission and the school board sit unshown is a worse page
for someone looking for the body that decides their issue. Measured on a
9-candidate pool: without it, 6 of 6 cards were City Council (**1**
distinct body); with it, **4**. A **state page** must not use that cap —
a dozen cards from a dozen cities are nearly all "City Council", so it
would exclude most of the state to manufacture variety that means
nothing; what a multi-government pool wants is `max_per_jurisdiction`,
the mirror image. Note the topic cap does **not** substitute: in that
same measurement each council meeting had a *different* topic, so topic
diversity was satisfied while body diversity was at its worst.

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
| `MAX_FEATURED_PER_BODY` | 2 (hub only) | `db/crud.py` |
| `MAX_FEATURED_PER_JURISDICTION` | 1 (home only) | `db/crud.py` |
| `HOME_HIGHLIGHT_POOL` / `HOME_FEATURED_COUNT` | 150 / 6 | `db/crud.py` |
| `_HOME_CACHE_TTL_SECONDS` (Archive) | 300 | `archive/main.py` |
| `_HOME_HIGHLIGHTS_TTL_SECONDS` / `_FAILURE_TTL` | 300 / 30 | `app/main.py` |
| `HOME_TIMEOUT` | 2s | `app/archive_client.py` |
| `META_DESCRIPTION_CHARS` | 200 | `utils/highlights.py` |
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

### The chips and the moments feed are on the home page — built 2026-08-24 (WO-50)

**Proposed by Ryan 2026-08-23**, after seeing the rebuilt state pages.
The home page explained a *tool* and showed nothing of the archive behind
it — a visitor with no meeting URL to paste had nothing to do — on the
highest-value page on the domain for indexing, which carried no unique
text of its own. It now renders topic chips, a national recent-moments
feed and a browse-by-state row below the lookup box.

**The boundary went the way this section recommended**: an Archive
endpoint (`/internal/home-highlights`) the resolver calls server-side via
`app/archive_client.py`, which already returns `None` on any failure for
every other call. The alternative — the resolver importing Archive models
— would have made an Archive migration able to break the resolver, which
is a different and much stronger coupling than the existing
`crud.py → app.utils.jurisdiction_enrich` utility import.

**Degrading is the feature, and it is the acceptance test.** With the
Archive stopped and the resolver's cache cold, `/` returns 200 in ~1.5 ms
with the lookup box untouched and the section simply absent. Two things
make that true and neither is obvious:

- **Failures are cached too** (30 s, vs 300 s for successes). Without it
  a cold or down Archive means *every* home-page request pays the full
  timeout to render the page it was always going to render.
- **`HOME_TIMEOUT` is 2 s, not `LOOKUP_TIMEOUT`'s 5 s.** Measured against
  a deliberately-hanging Archive, the 5 s budget made the home page take
  **5.2 s**. What the wait buys here is one optional section, not a saved
  live resolve, so the budget is smaller. A Render cold start is 30-60 s
  and hopeless at either value, so the only case a longer budget rescues
  is "alive but briefly slow".

**Scope at national level**, as this section predicted:

- **`max_per_jurisdiction` (1) is the cap that matters**, not the topic
  one. The pool is the newest transcribed meetings *anywhere*, so it
  skews to whatever was bulk-ingested last. Verified live: one city held
  the three newest meetings and the first five cards were still five
  different cities. The topic cap alone does not fix this — a single
  city's meetings routinely span six topics (measured in WO-49).
- **Browse-by-state, not 574 governments** — ~50 links, each to a
  `/state/{slug}` page, pointing the site's most-linked page at exactly
  the surface with the indexing problem.
- **Cached on both sides.** The Archive caches the payload in-process
  too, because several resolver instances share one Archive and a cold
  resolver cache must not become a corpus query.
- The query is **bounded in SQL** (joins `meeting_highlights`, LIMITs),
  unlike `get_state_page_data()`, which pulls a whole state and filters
  in Python — fine per state, a corpus scan nationally.

**One defect here was invisible to the entire test suite**, and it is the
generalisable lesson. Sharing the Jinja partials across services (via a
new repo-root `shared_templates/`, mounted by both loaders the way
`shared_static/` already was) meant the partial silently depended on
filters only the *Archive* registers — `jurisdiction_display`,
`meeting_date_html`. The home page 500'd on first load while 1,693 tests
passed. The fix makes the partial **filter-free**: `_featured_entry()`
pre-renders the display strings, which also lets them survive the JSON
hop. `tests/test_home_highlights.py` renders a realistic payload through
the *resolver's* real environment, and was confirmed to fail when the
filter dependency is put back.

**`?topic=` works here as on the state pages** — real crawlable links,
all canonicalizing to bare `/`, so variants add text without competing
for the same query.

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

- ~~**Per-meeting-body diversity**, alongside per-topic~~ — shipped
  WO-49, 2026-08-24; see the surface-specific cap note in §6.
- ~~**A snippet for the `og:description`**~~ — shipped WO-49,
  2026-08-24. Every `/m/` page previously carried the same sentence
  shape ("A public meeting in X on Y, with video and transcript."), which
  is the templated-thin content this whole rebuild was diagnosed with,
  on the one page type Google was *already* indexing well. Now the stored
  highlight fills it, trimmed on a word boundary by `meta_description()`
  — plain text via `display_text()`, never `highlight_html()`, since meta
  content cannot carry markup. A meeting with nothing quotable (808 of
  2,362 at the backfill) keeps the generic sentence, so the fallback is
  load-bearing, not theoretical. The `<title>` already carries
  meeting/jurisdiction/date, which is what frees the description to spend
  its whole budget on the one line unique to the page.
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
